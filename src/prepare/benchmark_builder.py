"""PCV-MIA 不可变攻击基准构建器。

中文说明
========
本文件把切分好的各组(KB_Member/True_Non_Member/可选的 Spoofed_Non_Member)合并成一份
固定的攻击基准 jsonl,后续所有攻击步骤都以它为唯一输入。每条记录被赋予稳定的 audit_id、
组别与实验角色(experimental_role),并对非成员组校验其未被误标进知识库。写出后会计算文件
sha256 落盘,断点续跑时据此校验基准未被篡改,从而保证实验可复现、各步骤口径一致。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def build_pcv_attack_benchmark(
    dataset: str,
    kb_member_path: str | Path,
    true_non_member_path: str | Path,
    spoofed_non_member_path: str | Path | None,
    output_path: str | Path,
    config_snapshot: dict[str, Any] | None = None,
    split_seed: int | None = None,
    include_spoofed_nonmember: bool = True,
    reserve_path: str | Path | None = None,
    include_reserve: bool = True,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """构建所有攻击步骤共用的固定 PCV-MIA 基准。

    参数:
        dataset:                  数据集名。
        kb_member_path:           KB_Member 组 jsonl 路径(成员)。
        true_non_member_path:     True_Non_Member 组 jsonl 路径(主要负类)。
        spoofed_non_member_path:  Spoofed_Non_Member 组 jsonl 路径(对照组,可为 None)。
        output_path:              基准输出路径(并派生 .sha256 与 manifest)。
        config_snapshot:          配置快照,写进 manifest 便于复现。
        split_seed:               切分种子,记入每条记录的 metadata。
        include_spoofed_nonmember: 是否纳入 Spoofed_Non_Member 对照组。
        reserve_path:             Reserve 组 jsonl 路径(L1 群体校准的零分布来源,可为 None)。
        include_reserve:          是否纳入 Reserve 校准组(纳入后它会随主流水线跑出 cvg,
                                  但只用于估计"非成员零分布",评估指标时必须排除它)。
        resume:                   断点续跑:基准/哈希/manifest 都存在则校验后跳过。
        force:                    强制重建。
    返回:
        manifest(字典);若跳过则带 skipped_existing。
    异常:
        ValueError:   要求纳入对照组却未提供其路径时抛出。
        RuntimeError: 续跑时基准文件哈希与已存哈希不一致,或非成员记录被误标进知识库时抛出。
    """
    output = Path(output_path)
    hash_path = output.with_suffix(".sha256")
    manifest_path = output.with_name(f"{dataset}_benchmark_manifest.json")
    if output.exists() and hash_path.exists() and manifest_path.exists() and resume and not force:
        # 续跑前先校验基准内容未被改动:实测哈希必须与落盘哈希一致。
        current_hash = sha256_file(output)
        saved_hash = hash_path.read_text(encoding="utf-8").strip()
        if current_hash != saved_hash:
            raise RuntimeError(f"Benchmark hash mismatch: {output}")
        LOGGER.info("Skipping existing PCV-MIA benchmark for %s: %s", dataset, output)
        return {"dataset": dataset, "output_path": str(output), "benchmark_hash": current_hash, "skipped_existing": True}

    # 三元组:(组名, 文件路径, 是否在知识库内)。
    groups: list[tuple[str, str | Path, bool]] = [
        ("KB_Member", kb_member_path, True),
        ("True_Non_Member", true_non_member_path, False),
    ]
    if include_spoofed_nonmember:
        if spoofed_non_member_path is None:
            raise ValueError("spoofed_non_member_path is required when include_spoofed_nonmember=True")
        groups.append(("Spoofed_Non_Member", spoofed_non_member_path, False))
    # Reserve 校准组:同分布、非成员、与其它组 source 互斥。它随主流水线跑出 cvg,
    # 仅用于 L1 群体校准估计"非成员零分布",评估指标时必须排除(见 metrics 调用方)。
    if include_reserve:
        if reserve_path is None:
            raise ValueError("reserve_path is required when include_reserve=True")
        groups.append(("Reserve", reserve_path, False))

    records: list[dict[str, Any]] = []
    audit_idx = 0
    created_at = datetime.now(timezone.utc).isoformat()
    for group, path, in_kb in groups:
        for row in read_jsonl(path):
            # 安全校验:非成员组的记录绝不能带 in_knowledge_base=True,否则负类被污染。
            if group != "KB_Member" and bool(row.get("in_knowledge_base", False)):
                raise RuntimeError(f"Non-member row is incorrectly marked as in_knowledge_base: {row.get('doc_id')}")
            records.append(
                {
                    "audit_id": f"{dataset}_audit_{audit_idx:06d}",
                    "dataset": dataset,
                    "group": group,
                    "doc_id": row.get("doc_id") or row.get("sample_id") or row.get("source_id"),
                    "text": row["text"],
                    "text_hash": row["text_hash"],
                    "in_knowledge_base": in_kb,
                    "experimental_role": _experimental_role(group),
                    "metadata": {
                        "source": row.get("source_path") or row.get("source_id"),
                        "split_seed": split_seed,
                        # spoof_scores 只对 Spoofed_Non_Member 组有意义,其它组留空。
                        "spoof_scores": row.get("spoof_scores") if group == "Spoofed_Non_Member" else None,
                        "experimental_role": _experimental_role(group),
                        "source_metadata": row.get("metadata", {}),
                        "created_at": created_at,
                    },
                }
            )
            audit_idx += 1

    write_jsonl(records, output)
    # 落盘后计算基准文件 sha256 并单独保存,作为不可变性校验依据。
    digest = sha256_file(output)
    hash_path.write_text(digest + "\n", encoding="utf-8")
    counts = Counter(row["group"] for row in records)
    manifest = {
        "dataset": dataset,
        "num_kb_member": counts["KB_Member"],
        "num_true_non_member": counts["True_Non_Member"],
        "num_spoofed_non_member": counts["Spoofed_Non_Member"],
        "num_reserve": counts["Reserve"],
        "include_spoofed_nonmember": include_spoofed_nonmember,
        "include_reserve": include_reserve,
        "spoofed_non_member_switch": "PCV_ENABLE_SPOOFED_NONMEMBER",
        "group_roles": {
            "KB_Member": "positive member class",
            "True_Non_Member": "primary negative class",
            "Spoofed_Non_Member": "experimental control group only",
            "Reserve": "calibration group only (excluded from evaluation metrics)",
        },
        "benchmark_hash": digest,
        "output_path": str(output),
        "input_hashes": {group: sha256_file(path) for group, path, _ in groups},
        "config_hash": sha256_obj(config_snapshot or {}),
        "config_snapshot": config_snapshot or {},
        "created_at": created_at,
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Built PCV-MIA benchmark for %s: rows=%s sha256=%s", dataset, len(records), digest)
    return manifest


def _experimental_role(group: str) -> str:
    """把组名映射成实验角色标签(写进基准记录,标明各组在实验中的定位)。

    参数:
        group: 组名,如 "KB_Member"。
    返回:
        对应的实验角色字符串;未知组返回 "auxiliary_group"。
    """
    if group == "KB_Member":
        return "positive_member_class"
    if group == "True_Non_Member":
        return "primary_negative_class"
    if group == "Spoofed_Non_Member":
        return "experimental_control_group"
    if group == "Reserve":
        return "calibration_group"
    return "auxiliary_group"
