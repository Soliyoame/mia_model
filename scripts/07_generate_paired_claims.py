"""07: 生成真实/反事实配对断言(paired claim)。

中文说明
========
本文件对应流水线第 07 步:读入第 06 步产出的事实单元 `{dataset}_facts.jsonl`,
为每个事实造一对断言——一条与原文一致的"真实断言",一条把关键信息改掉的
"反事实断言",写到 `{dataset}_paired_claims.jsonl`。这对断言是配对核验攻击的核心:
后续会分别问模型这两条是否成立,通过两者回答的差异来推断该文档是否被 RAG 检索到。

真假断言的具体改写逻辑在 `src.paired_claims.claim_generator` 里,本脚本只负责读配置、
设随机种子,并把扰动强度(perturbation_levels)、每个事实最多生成几对(max_pairs_per_fact)
等参数传进去。输入是事实单元 jsonl,输出是配对断言 jsonl。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.paired_claims.claim_generator import generate_paired_claims_file
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、force、no_resume,
        含义与其它流水线脚本一致。
    """
    parser = argparse.ArgumentParser(description="Generate PCV-MIA paired claims.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--log-file", default=None)
    return parser.parse_args()


def main() -> int:
    """脚本入口:生成配对断言并写盘。

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
    claim_cfg = config.get("paired_claims", {})
    out_dir = ensure_dir(resolve_path(config["paths"]["paired_claims_dir"]))
    manifest = generate_paired_claims_file(
        facts_path=resolve_path(config["paths"]["facts_dir"]) / f"{args.dataset}_facts.jsonl",
        output_path=out_dir / f"{args.dataset}_paired_claims.jsonl",
        benchmark_path=resolve_path(config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        # perturbation_levels 控制反事实断言的改写强度(如 light=轻度替换关键信息)。
        perturbation_levels=claim_cfg.get("perturbation_levels", ["light"]),
        max_pairs_per_fact=int(claim_cfg.get("max_pairs_per_fact", 1)),
        semantic_resolver_config=dict(
            config.get("fact_extraction", {}).get("semantic_resolver", {})
        ),
        dataset=args.dataset,
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info("Step 07 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
