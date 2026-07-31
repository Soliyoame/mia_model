"""使用 Reserve 构建与正式 indexes 物理隔离的检索门禁索引。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.index_builder import build_rag_index
from src.utils.dataset_paths import resolve_dataset_dir
from src.utils.io import ensure_dir, load_yaml, resolve_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Reserve-only retrieval dev indexes.")
    parser.add_argument("--dataset", required=True, choices=["edgar", "enron", "pubmed"])
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--fallback-large",
        action="store_true",
        help="仅在 base BGE 三数据集门禁失败后运行一次预注册 large fallback。",
    )
    return parser.parse_args()


def _candidate_id(chunk_size: int, overlap: int) -> str:
    return f"tokens-{chunk_size}-overlap-{overlap}"


def main() -> int:
    args = parse_args()
    config = load_yaml(args.config)
    formal_root = resolve_path(config["paths"]["indexes_dir"]).resolve()
    dev_root = resolve_path(config["paths"]["retrieval_dev_indexes_dir"]).resolve()
    if dev_root == formal_root or formal_root in dev_root.parents:
        raise RuntimeError("Reserve dev indexes must be outside formal indexes_dir")
    reserve_path = resolve_dataset_dir(config, "splits_dir", args.dataset) / "reserve.jsonl"
    if not reserve_path.is_file():
        raise FileNotFoundError(f"Reserve split not found: {reserve_path}")
    embedding = dict(config["embedding"])
    chunking = config["chunking"]
    if args.fallback_large:
        gate = config["retrieval"]["offline_gate"]
        embedding["model"] = gate["fallback_dense_model"]
        embedding["revision"] = gate.get("fallback_dense_revision")
        candidates = [{
            "chunk_size": int(gate["fallback_chunk_size"]),
            "chunk_overlap": int(gate["fallback_chunk_overlap"]),
        }]
        candidate_prefix = "bge-large-"
    else:
        candidates = list(chunking.get("offline_gate_candidates") or [])
        candidate_prefix = ""
    for candidate in candidates:
        chunk_size = int(candidate["chunk_size"])
        overlap = int(candidate["chunk_overlap"])
        candidate_root = ensure_dir(
            dev_root
            / args.dataset
            / f"{candidate_prefix}{_candidate_id(chunk_size, overlap)}"
        )
        for backend in ("dense", "bm25"):
            build_rag_index(
                dataset=args.dataset,
                kb_member_path=reserve_path,
                output_dir=candidate_root / backend,
                embedding_model=str(embedding["model"]),
                embedding_backend=str(embedding.get("backend", "auto")),
                embedding_local_files_only=bool(embedding.get("local_files_only", True)),
                embedding_revision=embedding.get("revision"),
                query_instruction=str(embedding.get("query_instruction") or ""),
                embedding_dim=int(embedding.get("dim", 768)),
                chunk_size=chunk_size,
                chunk_overlap=overlap,
                chunking_unit="tokens",
                tokenizer_model=(
                    str(embedding["model"])
                    if args.fallback_large
                    else str(chunking.get("tokenizer_model") or embedding["model"])
                ),
                tokenizer_revision=(
                    embedding.get("revision")
                    if args.fallback_large
                    else chunking.get("tokenizer_revision") or embedding.get("revision")
                ),
                tokenizer_local_files_only=bool(
                    chunking.get("tokenizer_local_files_only", True)
                ),
                resume=not args.no_resume,
                force=args.force,
                config_snapshot=config,
                allowed_group="Reserve",
                retriever_backend=backend,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
