"""数据预处理主流程。

把本地 Enron、CUAD、EDGAR、PubMed 数据统一清洗、切分、过滤并写成 JSONL。

中文说明
========
本文件是流水线第 01 步的"总指挥"，把 data 包里的各个零件(读取→清洗→切分→过滤)
按顺序串起来跑：逐条读入原始文档，洗干净，切成片段，再筛掉不适合攻击的片段，
最后把保留下来的片段写成统一的 JSONL，并产出一份统计信息(stats)。
- 设计要点:逐条读、逐条写,不把整个数据集一次性读进内存(EDGAR/PubMed 文件很大)。
- 去重:用文本 hash 记录已见过的片段,跳过完全重复的内容。
- 断点续跑:产物已存在则默认跳过,除非传 force 强制重跑。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

try:
    # 进度条;没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from .chunker import chunk_text
from .cleaner import clean_dataset_text, cleaner_version_for_dataset
from .filter import contains_required_entity, has_min_perturbable_entities, is_template_like, metadata_for_text
from .reader import read_local_records
from ..utils.hash import sha256_text
from ..utils.io import ensure_parent, read_json, write_json
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def preprocess_dataset(
    dataset: str,
    input_path: str | Path,
    output_path: str | Path,
    min_chars: int = 200,
    max_chars: int = 3000,
    target_chars: int = 1000,
    limit: int | None = None,
    source_limit: int | None = None,
    require_entity: bool = True,
    require_numeric: bool = False,
    min_entities: int = 2,
    membership_unit: str | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """预处理单个数据集。

    该函数具备断点续跑能力：目标文件存在且非空时默认跳过，除非传入 force。

    参数:
        dataset:        数据集名(enron/cuad/edgar/pubmed 等)。
        input_path:     原始数据的文件或目录路径。
        output_path:    清洗后片段的输出 JSONL 路径(并派生 .stats/.errors/.manifest)。
        min_chars/max_chars/target_chars: 切块的大小参数(见 chunker)。
        limit:          软性的片段上限；达到后仍会写完当前 membership unit。
        source_limit:   最多处理多少个不同 source；None 表示不限。
        require_entity: 是否要求片段必须含有某类实体。
        require_numeric:是否要求必须含有数字类实体。
        min_entities:   片段需要的最少可扰动实体数。
        resume:         断点续跑:产物已存在则跳过。
        force:          强制重跑。
    返回:
        stats(字典):各阶段计数与统计信息;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    # 统计信息、错误记录分别写到同名的 .stats.json / .errors.jsonl。
    stats_path = output.with_suffix(".stats.json")
    error_path = output.with_suffix(".errors.jsonl")
    manifest_path = output.with_suffix(".manifest.json")
    # 断点续跑:产物非空且开启 resume、未 force,则跳过。
    if output.exists() and output.stat().st_size > 0 and resume and not force:
        existing_manifest = read_json(manifest_path) if manifest_path.exists() else {}
        existing_unit = str(existing_manifest.get("membership_unit") or "")
        expected_unit = str(membership_unit or "")
        if expected_unit and existing_unit != expected_unit:
            raise RuntimeError(
                f"Existing {dataset} preprocessing artifact has membership_unit={existing_unit!r}; "
                f"expected {expected_unit!r}. Rebuild Step 01 with --force."
            )
        expected_cleaner_version = cleaner_version_for_dataset(dataset)
        if expected_cleaner_version and existing_manifest.get("cleaner_version") != expected_cleaner_version:
            raise RuntimeError(
                f"Existing {dataset} preprocessing artifact has cleaner_version="
                f"{existing_manifest.get('cleaner_version')!r}; expected {expected_cleaner_version!r}. "
                "Rebuild Step 01 with --force."
            )
        LOGGER.info("Skipping existing processed file: %s", output)
        return {
            "dataset": dataset,
            "output_path": str(output),
            "membership_unit": expected_unit or existing_unit,
            "skipped_existing": True,
        }

    # 确保输出目录存在。
    ensure_parent(output)
    counters: Counter[str] = Counter()   # 各种计数器(原始条数/保留数/被各原因丢弃数...)
    seen_hashes: set[str] = set()         # 已见过的文本 hash,用于去重
    record_idx = 0                        # 已保留片段的序号
    lengths: list[int] = []               # 收集片段长度,用于统计
    densities: list[float] = []           # 收集实体密度,用于统计
    examples: list[dict[str, Any]] = []   # 留几个样例,便于人工抽查
    raw_source_ids: set[str] = set()
    kept_source_ids: set[str] = set()
    visited_source_ids: set[str] = set()

    LOGGER.info("Preprocessing dataset=%s input=%s output=%s", dataset, input_path, output)
    # 逐条读取、逐条写出，避免 EDGAR / PubMed 这类大文件占用过多内存。
    # 同时打开正文输出文件 f 和错误输出文件 ef。
    with output.open("w", encoding="utf-8", newline="\n") as f, error_path.open("w", encoding="utf-8", newline="\n") as ef:
        for raw in tqdm(read_local_records(dataset, input_path), desc=f"preprocess {dataset}", unit="doc"):
            raw_source_id = str(raw.source_id)
            if (
                source_limit is not None
                and raw_source_id not in visited_source_ids
                and len(visited_source_ids) >= source_limit
            ):
                LOGGER.info("Reached source limit for %s: %s", dataset, source_limit)
                break
            visited_source_ids.add(raw_source_id)
            counters["raw_records"] += 1
            # 读取阶段就报错的记录:记到错误文件,跳过。
            if raw.metadata.get("read_error"):
                counters["read_errors"] += 1
                ef.write(json.dumps({"source_path": raw.source_path, "error": raw.metadata.get("read_error")}, ensure_ascii=False))
                ef.write("\n")
                continue
            raw_source_ids.add(str(raw.source_id))
            # 清洗文本(按数据集选策略)。
            cleaned = clean_dataset_text(dataset, raw.text)
            # 洗完为空 → 丢弃。
            if not cleaned:
                counters["empty"] += 1
                continue
            # 像模板/套话 → 丢弃。
            if is_template_like(cleaned):
                counters["template_like"] += 1
                continue
            # 切成片段。
            fragments = chunk_text(cleaned, min_chars=min_chars, max_chars=max_chars, target_chars=target_chars)
            # 一个合格片段都没切出来 → 丢弃。
            if not fragments:
                counters["no_valid_chunk"] += 1
                continue
            for frag_idx, fragment in enumerate(fragments):
                counters["fragments"] += 1
                # PCV-MIA paired claims rely on replaceable entities.
                # 没有所需实体 → 丢弃(没法对它构造攻击)。
                if require_entity and not contains_required_entity(fragment, require_numeric=require_numeric):
                    counters["no_entity"] += 1
                    continue
                # 可扰动实体太少 → 丢弃。
                if min_entities > 0 and not has_min_perturbable_entities(fragment, min_entities=min_entities):
                    counters["too_few_entities"] += 1
                    continue
                # 生成该片段的实体元信息和文本 hash。
                metadata = metadata_for_text(fragment)
                text_hash = sha256_text(fragment)
                # 与之前完全重复 → 丢弃。
                if text_hash in seen_hashes:
                    counters["duplicate"] += 1
                    continue
                seen_hashes.add(text_hash)
                # 生成稳定的文档 id,如 enron_000007。
                doc_id = f"{dataset}_{record_idx:06d}"
                record = {
                    "doc_id": doc_id,
                    # 保留旧字段 id，避免旧脚本或测试直接依赖 id 时失效。
                    "id": doc_id,
                    "dataset": dataset,
                    "text": fragment,
                    "source_id": raw.source_id,
                    "source_path": raw.source_path,
                    "membership_unit": membership_unit,
                    "chunk_index": frag_idx,
                    "text_hash": text_hash,
                    "metadata": metadata,
                }
                # 写出这条保留片段(一行一个 JSON)。
                f.write(json.dumps(record, ensure_ascii=False))
                f.write("\n")
                kept_source_ids.add(str(raw.source_id))
                lengths.append(int(metadata["length"]))
                densities.append(float(metadata["entity_density"]))
                # 只留前 5 个样例供抽查。
                if len(examples) < 5:
                    examples.append(
                        {
                            "doc_id": doc_id,
                            "source_id": raw.source_id,
                            "text_preview": fragment[:300],
                            "metadata": metadata,
                        }
                    )
                record_idx += 1
                counters["kept"] += 1
            # 片段上限只在一个原始 membership unit 完整写出后生效，禁止产生半份
            # filing/email/PMCID article。
            if limit is not None and record_idx >= limit:
                LOGGER.info("Reached soft chunk limit for %s: %s", dataset, limit)
                break

    # 汇总实体密度的最小/最大/平均。
    density_distribution = {
        "min": min(densities) if densities else 0.0,
        "max": max(densities) if densities else 0.0,
        "avg": mean(densities) if densities else 0.0,
    }
    stats = {
        "dataset": dataset,
        "output_path": str(output),
        "error_path": str(error_path),
        "membership_unit": membership_unit,
        "cleaner_version": cleaner_version_for_dataset(dataset),
        "chunk_limit": limit,
        "source_limit": source_limit,
        "raw_unique_source_count": len(raw_source_ids),
        "unique_source_count": len(kept_source_ids),
        "raw_sample_count": counters["raw_records"],
        "cleaned_sample_count": counters["kept"],
        "avg_length": mean(lengths) if lengths else 0.0,
        "entity_density_distribution": density_distribution,
        "examples": examples,
        # 把所有计数器也展开并进统计(各丢弃原因的条数)。
        **dict(counters),
    }
    # 统计信息同时写一份 .stats.json 和一份 .manifest.json。
    write_json(stats, stats_path)
    write_json(stats, manifest_path)
    LOGGER.info("Finished preprocessing %s: kept=%s stats=%s", dataset, counters["kept"], stats_path)
    return stats
