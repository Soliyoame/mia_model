"""在三个数据集上评估 Reserve-only BGE/BM25/hybrid 门禁，API 调用为 0。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.retrieval_gate import (
    apply_dense_gate,
    evaluate_target_retrieval,
    forbidden_overlap_audit,
    rank_passing_chunk_configs,
)
from src.rag.retriever import HybridRagRetriever, RagRetriever
from src.utils.dataset_paths import resolve_dataset_dir
from src.utils.hash import sha256_file, sha256_obj
from src.utils.io import (
    ensure_dir,
    load_yaml,
    read_json,
    read_jsonl,
    resolve_path,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the v20 offline retrieval gate.")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["edgar", "enron", "pubmed"],
        choices=["edgar", "enron", "pubmed"],
    )
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument(
        "--output",
        default="artifacts/v20/retrieval_gate/retrieval_gate_report.json",
    )
    parser.add_argument("--fallback-large", action="store_true")
    return parser.parse_args()


def _candidate_id(chunk_size: int, overlap: int) -> str:
    return f"tokens-{chunk_size}-overlap-{overlap}"


def main() -> int:
    args = parse_args()
    config = load_yaml(args.config)
    output_path = resolve_path(args.output)
    ensure_dir(output_path.parent)
    dev_root = resolve_path(config["paths"]["retrieval_dev_indexes_dir"])
    query_root = resolve_path(config["paths"]["queries_dir"])
    benchmark_root = resolve_path(config["paths"]["benchmark_dir"])
    if args.fallback_large:
        gate = config["retrieval"]["offline_gate"]
        chunk_candidates = [{
            "chunk_size": int(gate["fallback_chunk_size"]),
            "chunk_overlap": int(gate["fallback_chunk_overlap"]),
        }]
        candidate_prefix = "bge-large-"
    else:
        chunk_candidates = list(config["chunking"]["offline_gate_candidates"])
        candidate_prefix = ""
    gate_cfg = config["retrieval"]["offline_gate"]
    hybrid_cfg = config["retrieval"]["hybrid"]
    checkpoint_version = "retrieval-gate-checkpoint-v1"
    report: dict[str, object]
    if output_path.is_file():
        existing = read_json(output_path)
        if (
            existing.get("checkpoint_version") == checkpoint_version
            and existing.get("requested_datasets") == args.datasets
            and bool(existing.get("fallback_run")) == bool(args.fallback_large)
        ):
            report = existing
        else:
            report = {}
    else:
        report = {}
    if not report:
        report = {
            "protocol_version": "pcv-mia-v20",
            "checkpoint_version": checkpoint_version,
            "requested_datasets": args.datasets,
            "selection_uses_attack_metrics": False,
            "datasets": {},
            "candidate_identities": {},
            "completed": False,
            "fallback_run": bool(args.fallback_large),
        }
    dense_for_ranking: dict[str, dict[str, dict]] = {}
    for dataset in args.datasets:
        queries = list(read_jsonl(query_root / f"{dataset}_paired_queries.jsonl"))
        benchmark = {
            str(row["audit_id"]): row
            for row in read_jsonl(
                benchmark_root / f"{dataset}_attack_benchmark.jsonl"
            )
        }
        forbidden_source_keys: set[str] = set()
        split_dir = resolve_dataset_dir(config, "splits_dir", dataset)
        for filename in (
            "kb_member.jsonl",
            "true_non_member.jsonl",
            "spoof_seed.jsonl",
            "spoofed_non_member.jsonl",
        ):
            path = split_dir / filename
            if not path.is_file():
                continue
            forbidden_source_keys.update(
                str(row.get("source_key") or row.get("source_id") or row.get("doc_id"))
                for row in read_jsonl(path)
            )
        dataset_report: dict[str, object] = {}
        for candidate in chunk_candidates:
            chunk_size = int(candidate["chunk_size"])
            overlap = int(candidate["chunk_overlap"])
            config_id = f"{candidate_prefix}{_candidate_id(chunk_size, overlap)}"
            root = dev_root / dataset / config_id
            candidate_identity = sha256_obj(
                {
                    "dataset": dataset,
                    "config_id": config_id,
                    "dense_index_manifest_hash": sha256_file(
                        root / "dense" / "index_manifest.json"
                    ),
                    "bm25_index_manifest_hash": sha256_file(
                        root / "bm25" / "index_manifest.json"
                    ),
                    "queries_hash": sha256_file(
                        query_root / f"{dataset}_paired_queries.jsonl"
                    ),
                    "benchmark_hash": sha256_file(
                        benchmark_root / f"{dataset}_attack_benchmark.jsonl"
                    ),
                    "gate_config": gate_cfg,
                    "hybrid_config": hybrid_cfg,
                }
            )
            existing_dataset = (report.get("datasets") or {}).get(dataset, {})
            existing_identities = (
                (report.get("candidate_identities") or {}).get(dataset, {})
            )
            if (
                config_id in existing_dataset
                and existing_identities.get(config_id) == candidate_identity
            ):
                dataset_report[config_id] = existing_dataset[config_id]
                dense_for_ranking.setdefault(config_id, {})[dataset] = (
                    existing_dataset[config_id]["methods"]["dense"]
                )
                continue
            hybrid = HybridRagRetriever(
                root / "dense",
                root / "bm25",
                dense_candidate_top_k=int(hybrid_cfg["dense_candidate_top_k"]),
                bm25_candidate_top_k=int(hybrid_cfg["bm25_candidate_top_k"]),
                rrf_k=int(hybrid_cfg["rrf_k"]),
                fusion_top_k=int(hybrid_cfg["fusion_top_k"]),
                final_top_k=int(hybrid_cfg["final_top_k"]),
                reranker_model=str(hybrid_cfg["reranker_model"]),
                reranker_revision=hybrid_cfg.get("reranker_revision"),
                reranker_local_files_only=bool(
                    hybrid_cfg.get("reranker_local_files_only", True)
                ),
            )
            dense = hybrid.dense
            bm25 = hybrid.bm25
            overlap_audit = forbidden_overlap_audit(
                dense.docstore,
                forbidden_source_keys,
            )
            methods = {
                "dense": evaluate_target_retrieval(dense, queries, benchmark),
                "bm25": evaluate_target_retrieval(bm25, queries, benchmark),
                "hybrid_reranker": evaluate_target_retrieval(
                    hybrid,
                    queries,
                    benchmark,
                    retrieve_top_k=5,
                ),
            }
            dense_gate = apply_dense_gate(
                methods["dense"],
                overlap_audit,
                recall_at_5_min=float(gate_cfg["recall_at_5_min"]),
                recall_at_10_min=float(gate_cfg["recall_at_10_min"]),
                zero_hit_source_rate_max=float(
                    gate_cfg["zero_hit_source_rate_max"]
                ),
            )
            methods["dense"]["gate"] = dense_gate
            methods["hybrid_reranker"]["recall_at_5_drop_vs_dense"] = (
                float(methods["dense"]["target_doc_recall_at_5"])
                - float(methods["hybrid_reranker"]["target_doc_recall_at_5"])
            )
            dataset_report[config_id] = {
                "chunk_size": chunk_size,
                "chunk_overlap": overlap,
                "overlap_audit": overlap_audit,
                "methods": methods,
            }
            dense_for_ranking.setdefault(config_id, {})[dataset] = methods["dense"]
            report.setdefault("datasets", {}).setdefault(dataset, {})[
                config_id
            ] = dataset_report[config_id]
            report.setdefault("candidate_identities", {}).setdefault(
                dataset, {}
            )[config_id] = candidate_identity
            report["completed"] = False
            report["completed_candidate_count"] = sum(
                len(rows)
                for rows in (report.get("candidate_identities") or {}).values()
            )
            write_json(report, output_path)
        report["datasets"][dataset] = dataset_report
    ranked = rank_passing_chunk_configs(dense_for_ranking)
    report["passing_chunk_config_ranking"] = ranked
    report["selected_chunk_config"] = ranked[0] if ranked else None
    report["base_bge_gate_passed"] = bool(ranked)
    report["fallback_run"] = bool(args.fallback_large)
    report["fallback_required"] = not bool(ranked) and not args.fallback_large
    report["completed"] = True
    report["completed_candidate_count"] = sum(
        len(rows)
        for rows in (report.get("candidate_identities") or {}).values()
    )
    write_json(report, output_path)
    return 0 if ranked else 2


if __name__ == "__main__":
    raise SystemExit(main())
