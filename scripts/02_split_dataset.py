"""02: 切分 KB_Member / True_Non_Member / Spoof_Seed / Reserve。

中文说明
========
本文件对应流水线第 2 步:把第 1 步清洗好的 <dataset>.jsonl 按配置的数量切成四个互斥子集:
KB_Member(进 RAG 知识库的成员)、True_Non_Member(真实非成员)、Spoof_Seed(用于第 4 步
仿造非成员的种子)、Reserve(预留)。切分逻辑在 src.prepare.splitter,这里只做命令行入口:
读 data_config.yaml、选规模(small/formal)、调用 split_dataset_pcv_mia 并写出各子集 jsonl
与 split_manifest.json。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.splitter import split_dataset_pcv_mia  # noqa: E402
from src.prepare.eligibility_scan import (  # noqa: E402
    ENRON_CAPACITY_PROMOTION_PROTOCOL,
    ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
    configured_release_protocol,
    validate_formal_eligibility_manifest,
)
from src.prepare.enron_capacity_promotion import (  # noqa: E402
    validate_enron_capacity_promotion,
)
from src.utils.dataset_paths import resolve_dataset_dir, resolve_processed_path  # noqa: E402
from src.utils.hash import sha256_file  # noqa: E402
from src.utils.io import ensure_dir, load_yaml, read_json, resolve_path  # noqa: E402
from src.utils.logger import setup_logging  # noqa: E402
from src.utils.seed import set_seed_from_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、scale、force、no_resume 等字段。
    """
    parser = argparse.ArgumentParser(description="Split processed dataset for PCV-MIA.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "data_config.yaml"))
    # scale 选 small/formal,对应配置里两套不同的子集规模;不指定则用配置默认。
    parser.add_argument("--scale", choices=["small", "formal"], default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--log-file", default=None, help="Optional log path override.")
    parser.add_argument(
        "--eligibility-path",
        default=None,
        help=(
            "显式覆盖 source eligibility manifest；Enron v4 使用该参数，"
            "无需修改共享 data_v6_3.yaml。"
        ),
    )
    return parser.parse_args()


def main() -> int:
    """流水线第 2 步入口:把单个数据集切成四个互斥子集。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging(
        "pcv_mia",
        log_file=resolve_path(args.log_file or config["logging"]["file"]),
        level=config["logging"].get("level", "INFO"),
    )
    split_cfg = config["split"]
    # 命令行 --scale 优先,否则用配置里的 scale;再据此取对应的各子集目标数量。
    scale = args.scale or split_cfg.get("scale", "small")
    sizes = split_cfg[scale]
    processed_path = resolve_processed_path(config, args.dataset)
    output_dir = ensure_dir(resolve_dataset_dir(config, "splits_dir", args.dataset))
    dataset_cfg = config["datasets"].get(args.dataset, {})
    eligibility_path_value = (
        args.eligibility_path
        or dataset_cfg.get("source_eligibility_path")
        or dataset_cfg.get("claim_eligibility_path")
    )
    eligible_source_keys = None
    claim_eligibility_snapshot = None
    if eligibility_path_value and str(sizes.get("target_unit", "records")) == "sources":
        eligibility_path = resolve_path(eligibility_path_value)
        eligibility = read_json(eligibility_path)
        if (
            eligibility.get("scan_protocol")
            == ENRON_CAPACITY_PROMOTION_PROTOCOL
        ):
            eligibility = validate_enron_capacity_promotion(
                eligibility_path,
                require_current_runtime=True,
            )
        if str(eligibility.get("dataset")) != args.dataset:
            raise RuntimeError(f"Claim eligibility dataset mismatch: {eligibility.get('dataset')!r}")
        eligible_source_keys = {
            str(value)
            for value in eligibility.get("eligible_source_keys", [])
        }
        scan_cfg = config.get("eligibility_scan")
        requires_formal_validation = eligibility.get("scan_protocol") in {
            ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
            ENRON_CAPACITY_PROMOTION_PROTOCOL,
        }
        if (
            isinstance(scan_cfg, dict)
            or args.eligibility_path
            or requires_formal_validation
        ):
            if isinstance(scan_cfg, dict) and not args.eligibility_path:
                expected_protocol = configured_release_protocol(scan_cfg)
                if eligibility.get("scan_protocol") != expected_protocol:
                    raise RuntimeError("Eligibility scan protocol mismatch")
            required_sources = sum(
                int(sizes[name])
                for name in (
                    "KB_Member",
                    "True_Non_Member",
                    "Spoof_Seed",
                    "Reserve",
                )
            )
            eligible_source_keys = validate_formal_eligibility_manifest(
                eligibility,
                dataset=args.dataset,
                required_sources=required_sources,
            )
        claim_eligibility_snapshot = {
            "path": str(eligibility_path.resolve()),
            "manifest_hash": sha256_file(eligibility_path),
            "protocol": eligibility.get("protocol"),
            "whitelist_hash": eligibility.get("whitelist_hash"),
            "eligible_source_count": eligibility.get("eligible_source_count"),
            "minimum_valid_claims": eligibility.get("minimum_valid_claims"),
            "minimum_stealth_pairs": eligibility.get("minimum_stealth_pairs"),
            "queries_per_source": eligibility.get("queries_per_source"),
            "query_text_uniqueness_enforced": eligibility.get(
                "query_text_uniqueness_enforced"
            ),
            "claim_validator_version": eligibility.get("claim_validator_version"),
            "query_types": eligibility.get("query_types"),
            "embedding_model": eligibility.get("embedding_model"),
            "scan_protocol": eligibility.get("scan_protocol"),
            "scan_plan_sha256": eligibility.get("scan_plan_sha256"),
            "scan_checkpoint_sha256": eligibility.get(
                "scan_checkpoint_sha256"
            ),
            "capacity_status": eligibility.get("capacity_status"),
        }
    manifest = split_dataset_pcv_mia(
        dataset=args.dataset,
        processed_path=processed_path,
        output_dir=output_dir,
        kb_member=int(sizes["KB_Member"]),
        true_non_member=int(sizes["True_Non_Member"]),
        spoof_seed=int(sizes["Spoof_Seed"]),
        reserve=int(sizes["Reserve"]),
        seed=int(split_cfg.get("seed", 42)),
        # source_exclusive=True 时同一来源不跨子集,避免成员/非成员之间信息泄漏。
        source_exclusive=bool(split_cfg.get("source_exclusive", True)),
        # per_source_cap 放在 scale 段内(small/formal 各自配):每篇原始文档最多贡献的 chunk 数;
        # 缺省 None=旧行为(单个来源可填满整组)。用于按「独立文档数」而非 chunk 数控制规模。
        per_source_cap=(int(sizes["per_source_cap"]) if sizes.get("per_source_cap") is not None else None),
        target_unit=str(sizes.get("target_unit", "records")),
        membership_unit=dataset_cfg.get("membership_unit"),
        split_scale=scale,
        min_entities_per_source=(
            int(dataset_cfg.get("min_entities_per_source"))
            if str(sizes.get("target_unit", "records")) == "sources"
            and dataset_cfg.get("min_entities_per_source") is not None
            else None
        ),
        eligible_source_keys=eligible_source_keys,
        claim_eligibility_snapshot=claim_eligibility_snapshot,
        config_snapshot=config,
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info(
        "Step 02 finished: dataset=%s target_unit=%s source_counts=%s counts=%s hash_summary=%s",
        manifest.get("dataset"),
        manifest.get("target_unit"),
        manifest.get("source_counts"),
        manifest.get("counts"),
        manifest.get("hash_summary"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
