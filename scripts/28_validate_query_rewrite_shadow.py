"""28：验证旧逐字查询与新实体槽问句的 shadow 非劣晋升门禁。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.query_rewrite_shadow import evaluate_query_rewrite_shadow_files
from src.utils.io import load_yaml, resolve_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate diverse-query shadow promotion.")
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "configs" / "query_rewrite_shadow.yaml"),
    )
    return parser.parse_args()


def main() -> int:
    config = load_yaml(parse_args().config)
    paths = config["paths"]
    bootstrap = config.get("bootstrap") or {}
    evaluate_query_rewrite_shadow_files(
        sources_path=resolve_path(paths["sources"]),
        scores_path=resolve_path(paths["scores"]),
        retrieval_path=resolve_path(paths["retrieval"]),
        lexical_path=resolve_path(paths["lexical"]),
        audit_path=resolve_path(paths["audit"]),
        output_path=resolve_path(paths["output"]),
        datasets=tuple(config.get("datasets", ["enron", "edgar", "pubmed"])),
        bootstrap_iterations=int(bootstrap.get("iterations", 2000)),
        seed=int(bootstrap.get("seed", 42)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
