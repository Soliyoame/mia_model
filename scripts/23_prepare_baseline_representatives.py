"""Build the zero-API representative-chunk manifests for v20 baselines."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.baselines.representative import build_representative_chunk_manifest  # noqa: E402
from src.rag.paths import retriever_index_dir  # noqa: E402
from src.rag.retriever import RagRetriever  # noqa: E402
from src.utils.io import ensure_dir, load_yaml, resolve_path  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare one frozen BGE representative chunk per source"
    )
    parser.add_argument("--dataset", choices=["edgar", "enron", "pubmed"])
    parser.add_argument("--rag-config", default="configs/rag_config.yaml")
    parser.add_argument("--baseline-config", default="configs/baseline_config.yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rag_config = load_yaml(args.rag_config)
    baseline_config = load_yaml(args.baseline_config)
    datasets = [args.dataset] if args.dataset else ["edgar", "enron", "pubmed"]
    output_root = ensure_dir(
        resolve_path(baseline_config["paths"]["representative_manifest_dir"])
    )
    for dataset in datasets:
        retriever = RagRetriever(retriever_index_dir(rag_config, dataset, "dense"))
        output = output_root / f"{dataset}_representative_chunks.jsonl"
        manifest = build_representative_chunk_manifest(
            dataset=dataset,
            splits_dir=resolve_path(
                rag_config["dataset_paths"][dataset]["splits_dir"]
            ),
            queries_path=(
                resolve_path(baseline_config["paths"]["queries_dir"])
                / f"{dataset}_paired_queries.jsonl"
            ),
            dense_retriever=retriever,
            output_path=output,
            chunk_size=128,
            chunk_overlap=32,
        )
        print(
            f"[saved] {output} sources={manifest['source_count']} "
            f"hash={manifest['representative_chunk_manifest_hash']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
