"""09: 过滤低质量或"探针味"过重的配对核验查询。

中文说明
========
本文件对应流水线第 09 步:读入第 08 步产出的配对查询 `{dataset}_paired_queries.jsonl`,
把不够"隐蔽"或质量不佳的查询剔除掉,只保留干净的那部分,写回同名文件到隐蔽过滤目录。
攻击要想成立,查询得像正常用户提问,不能一看就是在套库里的内容(否则容易被防御识破)。

判定逻辑在 `src.query_generation.stealth_filter` 里,本脚本只负责读配置、设随机种子,
并把若干阈值传进去:自然度下限(min_naturalness)、上下文探针上限(max_context_probe)、
提示注入上限(max_prompt_injection)，以及实体遮蔽后的 5-gram/最长连续公共 token 串。
embedding 只记录 query--claim 与 query--chunk 的语义诊断，不参与拒绝。输入输出都是配对查询 jsonl。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.query_generation.stealth_filter import filter_stealth_queries
from src.rag.embeddings import DEFAULT_EMBEDDING_MODEL
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、force、no_resume,
        含义与其它流水线脚本一致。
    """
    parser = argparse.ArgumentParser(description="Filter PCV-MIA paired queries.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """脚本入口:过滤配对查询并写盘。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    stealth_cfg = config.get("stealth_filter", {})
    out_dir = ensure_dir(resolve_path(config["paths"]["stealth_filtered_queries_dir"]))
    manifest = filter_stealth_queries(
        queries_path=resolve_path(config["paths"]["paired_queries_dir"]) / f"{args.dataset}_paired_queries.jsonl",
        output_path=out_dir / f"{args.dataset}_paired_queries.jsonl",
        benchmark_path=resolve_path(config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        # 配置没给 embedding_model 时退回默认模型,用于计算查询与原文的语义相似度。
        embedding_model=str(stealth_cfg.get("embedding_model", DEFAULT_EMBEDDING_MODEL)),
        embedding_local_files_only=bool(stealth_cfg.get("embedding_local_files_only", False)),
        min_naturalness=float(stealth_cfg.get("min_naturalness", 0.55)),
        max_context_probe=float(stealth_cfg.get("max_context_probe", 0.5)),
        max_prompt_injection=float(stealth_cfg.get("max_prompt_injection", 0.5)),
        # 隐蔽性使用实体遮蔽后的字面复制指标；embedding 只保留语义诊断。
        max_five_gram_containment=float(stealth_cfg.get("max_five_gram_containment", 0.35)),
        max_longest_common_token_run=int(stealth_cfg.get("max_longest_common_token_run", 8)),
        max_dataset_duplicate_template_rate=float(
            stealth_cfg.get("max_dataset_duplicate_template_rate", 0.01)
        ),
        max_dataset_opening_4gram_rate=float(
            stealth_cfg.get("max_dataset_opening_4gram_rate", 0.15)
        ),
        embedding_batch_size=int(stealth_cfg.get("embedding_batch_size", 256)),
        pairs_per_source=(
            int(stealth_cfg["pairs_per_source"])
            if stealth_cfg.get("pairs_per_source") is not None
            else None
        ),
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info("Step 09 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
