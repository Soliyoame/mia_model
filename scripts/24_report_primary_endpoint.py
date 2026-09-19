"""Report the single preregistered v20 primary endpoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import bootstrap_macro_auc_ci  # noqa: E402
from src.llm.generator_registry import resolve_generator_from_pipeline_config  # noqa: E402
from src.rag.paths import retriever_id_from_config  # noqa: E402
from src.utils.hash import sha256_file  # noqa: E402
from src.utils.io import load_yaml, read_jsonl, resolve_path, write_json  # noqa: E402
from src.utils.run_context import experiment_scoped_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the v20 primary endpoint report")
    parser.add_argument("--rag-config", default="configs/rag_config.yaml")
    parser.add_argument("--attack-config", default="configs/pcv_attack_config.yaml")
    parser.add_argument(
        "--output",
        default="artifacts/v20/reports/primary_endpoint_llama_bge.json",
    )
    args = parser.parse_args()
    rag_config = load_yaml(args.rag_config)
    attack_config = load_yaml(args.attack_config)
    generator, _ = resolve_generator_from_pipeline_config(rag_config, family="llama")
    retriever_id = retriever_id_from_config(rag_config, "dense")
    scope = {
        "generator_family": generator.generator_family,
        "concrete_model": generator.concrete_model,
        "retriever_id": retriever_id,
    }
    dataset_rows = {}
    provenance = {}
    for dataset in ("edgar", "enron", "pubmed"):
        path = (
            experiment_scoped_dir(
                attack_config["paths"]["scores_dir"],
                dataset,
                **scope,
            )
            / f"{dataset}_pcv_scores_source_scores.jsonl"
        )
        rows = [
            row for row in read_jsonl(path) if str(row.get("group")) != "Reserve"
        ]
        dataset_rows[dataset] = rows
        provenance[dataset] = {"path": str(path), "sha256": sha256_file(path)}
    endpoint = bootstrap_macro_auc_ci(
        dataset_rows,
        score_key="pcv_score",
        n_bootstrap=2000,
        seed=42,
    )
    report = {
        "protocol_version": "pcv-mia-v20",
        "metrics_version": "source-conformal-bootstrap-v2",
        "endpoint_role": "unique_primary",
        "endpoint": (
            "equal-weight macro source-level AUC across Edgar, Enron and "
            "PubMed for meta/llama-3.1-70b-instruct + BGE dense"
        ),
        "generator_family": "llama",
        "concrete_model": "meta/llama-3.1-70b-instruct",
        "retriever": "BAAI/bge-base-en-v1.5",
        "result": endpoint,
        "bootstrap": {
            "unit": "source",
            "stratification": "dataset x Member/True_Non_Member",
            "replicates": 2000,
            "seed": 42,
        },
        "secondary_inference_policy": (
            "Conformal, BM25, hybrid, baselines, defenses and mechanisms "
            "report confidence intervals only; no multiplicity-adjusted "
            "significance claims."
        ),
        "input_provenance": provenance,
    }
    output = resolve_path(args.output)
    write_json(report, output)
    print(f"[saved] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
