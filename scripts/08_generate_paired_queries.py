"""08: 生成配对核验查询 Q+ 与 Q-。

中文说明
========
本文件对应流水线第 08 步:读入第 07 步产出的配对断言 `{dataset}_paired_claims.jsonl`,
把每对断言包装成一对自然的提问——Q+(围绕真实断言提问)和 Q-(围绕反事实断言提问),
写到 `{dataset}_paired_queries.jsonl`。这两条查询稍后会真正发给 RAG 系统,
通过对比两者的回答来判断目标文档是否在知识库里。

具体的查询构造逻辑在 `src.query_generation.paired_query_builder` 里,本脚本只负责读配置、
设随机种子,并把查询类型(query_types,如 compressed_verification 压缩式核验)传进去。
输入是配对断言 jsonl,输出是配对查询 jsonl。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.query_generation.paired_query_builder import generate_paired_queries_file
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、force、no_resume,
        含义与其它流水线脚本一致。
    """
    parser = argparse.ArgumentParser(description="Generate PCV-MIA paired verification queries.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """脚本入口:生成配对核验查询并写盘。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    query_cfg = config.get("paired_queries", {})
    out_dir = ensure_dir(resolve_path(config["paths"]["paired_queries_dir"]))
    manifest = generate_paired_queries_file(
        paired_claims_path=resolve_path(config["paths"]["paired_claims_dir"]) / f"{args.dataset}_paired_claims.jsonl",
        output_path=out_dir / f"{args.dataset}_paired_queries.jsonl",
        # query_types 决定查询的提问方式,默认用压缩式核验(compressed_verification)。
        query_types=query_cfg.get("query_types", ["compressed_verification"]),
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info("Step 08 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
