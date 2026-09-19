"""检查主 Generator 的 150-query pilot；不发 API，只读取既有响应。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.generator_pilot_gate import evaluate_generator_pilot_dataset
from src.llm.generator_registry import resolve_generator_from_pipeline_config
from src.rag.paths import retriever_id_from_config, retriever_index_dir
from src.utils.io import load_yaml, read_json, read_jsonl, resolve_path, write_json
from src.utils.run_context import experiment_scoped_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the primary Generator v20 compatibility pilot.")
    parser.add_argument("--dataset", required=True, choices=["edgar", "enron", "pubmed"])
    parser.add_argument("--queries-path", required=True)
    parser.add_argument("--suite-id", default="llama-3.1-70b-instruct-pilot")
    parser.add_argument("--rag-config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--plan-config", default=str(PROJECT_ROOT / "configs" / "experiment_plan_v20.yaml"))
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rag_config = load_yaml(args.rag_config)
    plan = load_yaml(args.plan_config)
    family = str(rag_config.get("generator_family") or "")
    identity, _ = resolve_generator_from_pipeline_config(rag_config, family=family)
    base = rag_config["paths"]
    suite_root = (
        resolve_path(base.get("pilots_dir", "artifacts/v20/pilots"))
        / args.suite_id
    )
    stage_bases = {
        "rag_responses_dir": suite_root / "rag_responses",
        "llm_only_responses_dir": suite_root / "llm_only_responses",
    }

    def response_path(stage: str, retriever_id: str, filename: str) -> Path:
        return (
            experiment_scoped_dir(
                stage_bases[stage],
                args.dataset,
                generator_family=identity.generator_family,
                concrete_model=identity.concrete_model,
                retriever_id=retriever_id,
            )
            / filename
        )

    systems = {
        "dense": list(read_jsonl(response_path(
            "rag_responses_dir",
            retriever_id_from_config(rag_config, "dense"),
            f"{args.dataset}_rag_responses.jsonl",
        ))),
        "bm25": list(read_jsonl(response_path(
            "rag_responses_dir",
            retriever_id_from_config(rag_config, "bm25"),
            f"{args.dataset}_rag_responses.jsonl",
        ))),
        "hybrid": list(read_jsonl(response_path(
            "rag_responses_dir",
            retriever_id_from_config(rag_config, "hybrid"),
            f"{args.dataset}_rag_responses.jsonl",
        ))),
        "llm_only": list(read_jsonl(response_path(
            "llm_only_responses_dir",
            "none",
            f"{args.dataset}_llm_only_responses.jsonl",
        ))),
        "oracle": list(read_jsonl(response_path(
            "rag_responses_dir",
            "oracle-context",
            f"{args.dataset}_rag_responses.jsonl",
        ))),
        "random": list(read_jsonl(response_path(
            "rag_responses_dir",
            "random-distractor",
            f"{args.dataset}_rag_responses.jsonl",
        ))),
    }
    pilot_cfg = plan["primary_generator_pilot"]
    report = evaluate_generator_pilot_dataset(
        systems,
        list(read_jsonl(resolve_path(args.queries_path))),
        expected_model=identity.concrete_model,
        stance_parse_rate_min=float(pilot_cfg["gates"]["stance_parse_rate_min"]),
        hybrid_max_drop=float(
            pilot_cfg["gates"]["hybrid_recall_at_5_max_drop_vs_bge"]
        ),
        oracle_random_min_margin=float(
            pilot_cfg["gates"]["oracle_minus_random_utility_min"]
        ),
    )
    isolation = {}
    for backend in ("dense", "bm25"):
        manifest_path = retriever_index_dir(rag_config, args.dataset, backend) / "index_manifest.json"
        manifest = read_json(manifest_path)
        boundary = manifest.get("security_boundary") or {}
        isolation[backend] = (
            boundary.get("allowed_groups") == ["KB_Member"]
            and not bool(boundary.get("is_shadow_index"))
        )
    report["kb_isolation"] = isolation
    report["passed"] = bool(report["passed"] and all(isolation.values()))
    output = (
        resolve_path(args.output)
        if args.output
        else resolve_path("artifacts/v20/pilots")
        / args.dataset
        / identity.generator_family
        / identity.concrete_model.replace("/", "--")
        / "pilot_gate.json"
    )
    write_json(report, output)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
