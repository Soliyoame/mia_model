"""PCV-MIA 数据集切分。

中文说明
========
本文件负责把"已处理"的记录切分成 PCV-MIA 实验所需的几组:KB_Member(进知识库的成员)、
True_Non_Member(主要负类)、Spoof_Seed(仿冒非成员的种子,可选对照用)和 Reserve(预留不用)。
切分前先按 text_hash 去重;可选 source_exclusive 模式保证同一来源文档只落进同一组,避免组间
信息泄漏。切完会做哈希互斥校验,并写出各组 jsonl 与一份可复现的 split_manifest.json。
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.hash import sha256_obj
from ..utils.io import ensure_dir, read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)

GROUP_FILENAMES = {
    "KB_Member": "kb_member.jsonl",
    "True_Non_Member": "true_non_member.jsonl",
    "Spoof_Seed": "spoof_seed.jsonl",
    "Reserve": "reserve.jsonl",
}


def _source_key(row: dict[str, Any]) -> str:
    """计算一条记录的"来源键",用于 source_exclusive 模式下判定同源。

    参数:
        row: 一条记录(字典)。
    返回:
        优先用 "source_path::source_id" 作为来源键;两者都缺时退回 text_hash。
    """
    source_id = str(row.get("source_id") or "").strip()
    source_path = str(row.get("source_path") or "").strip()
    if source_id or source_path:
        return f"{source_path}::{source_id}"
    return str(row.get("text_hash") or "")


def _source_exclusive_slices(
    records: list[dict[str, Any]],
    targets: dict[str, int],
    rng: random.Random,
    per_source_cap: int | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """按"来源互斥"方式切分记录:同一来源的所有记录只会落进同一组。

    先把记录按 source_key 聚成桶并打乱顺序,再依次填满各组的目标数量;一旦某桶的记录
    超出当前组的剩余名额,多出来的部分直接丢弃(不跨组分配),以严格保证组间来源不重叠。

    per_source_cap 用于按「独立文档数」控制规模:限制单个来源对一个组最多贡献的 chunk 数,
    逼迫覆盖更多来源(覆盖文档数 ≈ 目标数 / per_source_cap),从而把有效独立样本数从 chunk
    数拉回到文档数。None 表示不限制(单个来源可填满整组,旧行为)。

    参数:
        records:        待切分记录列表。
        targets:        各组的目标数量,如 {"KB_Member": 500, ...}。
        rng:            随机数发生器(由固定 seed 构造,保证可复现)。
        per_source_cap: 每个来源对单个组最多贡献的 chunk 数;None=不限制。
    返回:
        (各组记录字典, 因来源互斥/cap 而丢弃的记录数)。
    异常:
        ValueError: 来源互斥约束下记录不够填满目标数量时抛出。
    """
    groups_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups_by_source[_source_key(row)].append(row)

    source_keys = list(groups_by_source)
    rng.shuffle(source_keys)
    slices = {name: [] for name in targets}
    discarded = 0
    target_items = list(targets.items())
    target_idx = 0

    for source in source_keys:
        # 跳过已填满的组,推进到下一个还缺记录的组。
        while target_idx < len(target_items) and len(slices[target_items[target_idx][0]]) >= target_items[target_idx][1]:
            target_idx += 1
        if target_idx >= len(target_items):
            break
        group, target = target_items[target_idx]
        source_rows = groups_by_source[source][:]
        rng.shuffle(source_rows)
        remaining = target - len(slices[group])
        # per_source_cap:限制单个来源(原始文档)对当前组的最大贡献,逼迫覆盖更多来源,
        # 从而把「有效独立样本数」从 chunk 数拉回到文档数(避免一组样本集中在极少数文档上)。
        take = remaining if per_source_cap is None else min(remaining, per_source_cap)
        slices[group].extend(source_rows[:take])
        # 该来源未被本组选用的 chunk 一律丢弃:维持来源互斥 + per_source_cap 限额。
        discarded += max(0, len(source_rows) - take)

    missing = {group: target - len(slices[group]) for group, target in targets.items() if len(slices[group]) < target}
    if missing:
        raise ValueError(f"Not enough source-exclusive records to satisfy split targets: {missing}")
    return slices, discarded


def split_dataset_pcv_mia(
    dataset: str,
    processed_path: str | Path,
    output_dir: str | Path,
    kb_member: int = 500,
    true_non_member: int = 500,
    spoof_seed: int = 500,
    reserve: int = 200,
    seed: int = 42,
    source_exclusive: bool = True,
    per_source_cap: int | None = None,
    config_snapshot: dict[str, Any] | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """把已处理记录切分成 PCV-MIA 各组。

    只有 KB_Member 组允许进入 RAG 知识库;True_Non_Member 是主要负类;Spoof_Seed 仅供
    可选的 Spoofed_Non_Member 对照组使用,Reserve 组保留不用。

    参数:
        dataset:          数据集名。
        processed_path:   预处理产出的记录文件(jsonl)。
        output_dir:       各组 jsonl 与 manifest 的输出目录。
        kb_member:        KB_Member 组目标数量。
        true_non_member:  True_Non_Member 组目标数量。
        spoof_seed:       Spoof_Seed 组目标数量。
        reserve:          Reserve 组目标数量。
        seed:             随机种子,保证切分可复现。
        source_exclusive: 是否启用来源互斥切分(同源文档不跨组)。
        per_source_cap:   每个来源(原始文档)对单个组最多贡献的 chunk 数;None=不限制(旧行为)。
                          用于按「独立文档数」而非 chunk 数控制规模:目标数 / per_source_cap ≈ 覆盖文档数。
        config_snapshot:  配置快照,写进 manifest 便于复现。
        resume:           断点续跑:各组文件与 manifest 都已存在则跳过。
        force:            强制重跑。
    返回:
        manifest(字典);若跳过则带 skipped_existing。
    异常:
        ValueError:   去重后唯一记录数不足以满足切分目标数量时抛出。
        RuntimeError: 切分结果出现组间 text_hash 或来源重叠时抛出。
    """
    out_dir = ensure_dir(output_dir)
    expected_paths = [out_dir / filename for filename in GROUP_FILENAMES.values()]
    manifest_path = out_dir / "split_manifest.json"
    # 断点续跑:各组文件非空且 manifest 存在则跳过。
    if resume and not force and all(p.exists() and p.stat().st_size > 0 for p in expected_paths) and manifest_path.exists():
        LOGGER.info("Skipping existing PCV-MIA split for %s: %s", dataset, out_dir)
        return {"dataset": dataset, "output_dir": str(out_dir), "skipped_existing": True}

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    # 按 text_hash 去重:重复正文只保留首次出现的一条。
    for row in read_jsonl(processed_path):
        text_hash = row.get("text_hash")
        if not text_hash or text_hash in seen_hashes:
            continue
        seen_hashes.add(text_hash)
        records.append(row)

    targets = {
        "KB_Member": int(kb_member),
        "True_Non_Member": int(true_non_member),
        "Spoof_Seed": int(spoof_seed),
        "Reserve": int(reserve),
    }
    required = sum(targets.values())
    if len(records) < required:
        raise ValueError(f"{dataset} has {len(records)} unique records, but PCV-MIA split requires {required}")

    rng = random.Random(seed)
    if source_exclusive:
        slices, discarded_source_chunks = _source_exclusive_slices(records, targets, rng, per_source_cap=per_source_cap)
    else:
        # 非互斥模式:整体打乱后按目标数量顺序切片即可。
        rng.shuffle(records)
        start = 0
        slices = {}
        for group, count in targets.items():
            slices[group] = records[start : start + count]
            start += count
        discarded_source_chunks = 0

    # 互斥校验之一:任意两组的 text_hash 集合不得相交,否则同一正文被分进了多组。
    hash_sets = {name: {str(r["text_hash"]) for r in rows} for name, rows in slices.items()}
    group_names = list(hash_sets)
    for i, left in enumerate(group_names):
        for right in group_names[i + 1 :]:
            overlap = hash_sets[left] & hash_sets[right]
            if overlap:
                raise RuntimeError(f"Split groups overlap for {dataset}: {left} vs {right}, overlap={len(overlap)}")

    # 互斥校验之二:启用来源互斥时,任意两组的来源键集合也不得相交。
    source_sets = {name: {_source_key(r) for r in rows} for name, rows in slices.items()}
    if source_exclusive:
        groups = list(source_sets)
        for i, left in enumerate(groups):
            for right in groups[i + 1 :]:
                overlap = source_sets[left] & source_sets[right]
                if overlap:
                    raise RuntimeError(f"Source-exclusive split overlap for {dataset}: {left} vs {right}, overlap={len(overlap)}")

    counts: dict[str, int] = {}
    for group, rows in slices.items():
        output_rows = []
        for idx, row in enumerate(rows):
            doc_id = str(row.get("doc_id") or row.get("id") or f"{dataset}_{idx:06d}")
            output_rows.append(
                {
                    "doc_id": doc_id,
                    "sample_id": f"{dataset}_{group.lower()}_{idx:06d}",
                    "dataset": dataset,
                    "group": group,
                    "text": row["text"],
                    "text_hash": row["text_hash"],
                    "source_id": row.get("source_id") or doc_id,
                    "source_path": row.get("source_path"),
                    "metadata": {
                        **(row.get("metadata") if isinstance(row.get("metadata"), dict) else {}),
                        "split_seed": seed,
                        "source_key": _source_key(row),
                        # 只有 KB_Member 组的记录会进入知识库,这里据此打标。
                        "in_knowledge_base": group == "KB_Member",
                    },
                }
            )
        output_path = out_dir / GROUP_FILENAMES[group]
        counts[group] = write_jsonl(output_rows, output_path)
        LOGGER.info("Wrote PCV-MIA split group %s/%s: %s rows", dataset, group, counts[group])

    created_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "dataset": dataset,
        "seed": seed,
        "source_exclusive": source_exclusive,
        "per_source_cap": per_source_cap,
        "counts": counts,
        "hashes": {group: sorted(values) for group, values in hash_sets.items()},
        # 各组哈希集合再算一个摘要,便于快速比对切分是否一致。
        "hash_summary": {group: sha256_obj(sorted(values)) for group, values in hash_sets.items()},
        "source_counts": {name: len(values) for name, values in source_sets.items()},
        "discarded_source_chunks": discarded_source_chunks,
        "source": str(processed_path),
        "created_at": created_at,
        "config_snapshot": config_snapshot or {},
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Finished PCV-MIA split for %s: %s", dataset, Counter(counts))
    return manifest
