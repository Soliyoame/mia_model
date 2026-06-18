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

from src.prepare.splitter import split_dataset_pcv_mia
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


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
    return parser.parse_args()


def main() -> int:
    """流水线第 2 步入口:把单个数据集切成四个互斥子集。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    split_cfg = config["split"]
    # 命令行 --scale 优先,否则用配置里的 scale;再据此取对应的各子集目标数量。
    scale = args.scale or split_cfg.get("scale", "small")
    sizes = split_cfg[scale]
    processed_path = resolve_path(config["paths"]["processed_dir"]) / f"{args.dataset}.jsonl"
    output_dir = ensure_dir(resolve_path(config["paths"]["splits_dir"]) / args.dataset)
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
        config_snapshot=config,
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info("Step 02 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
