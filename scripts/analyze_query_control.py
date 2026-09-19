"""Parse and score one explicit online query control on a common source whitelist."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import (  # noqa: E402
    bootstrap_auc_ci,
    paired_bootstrap_metric_delta,
    summarize_membership_scores,
)
from src.parsing.stance_parser import parse_stance_files  # noqa: E402
from src.scoring.pcv_scorer import compute_pcv_scores  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import ensure_dir, load_yaml, read_json, read_jsonl, resolve_path, write_json  # noqa: E402
from src.utils.run_context import git_snapshot, model_scoped_dir, victim_model_slug  # noqa: E402

EVAL_GROUPS = {"KB_Member", "True_Non_Member"}
SUPPORTED_CONTROLS = {
    "random_same_type_counterfactual",
    "independent_unpaired_query",
    "no_stealth_filter",
}


def _eval_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("group")) in EVAL_GROUPS]


def build_query_control_report(
    main_rows: list[dict[str, Any]],
    control_rows: list[dict[str, Any]],
    *,
    variant_id: str,
    query_budget: int,
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Compare main and control only on sources present in both with matching labels."""
    main = {str(row.get("source_key")): row for row in _eval_rows(main_rows)}
    control = {str(row.get("source_key")): row for row in _eval_rows(control_rows)}
    common = sorted(
        key for key in set(main) & set(control)
        if str(main[key].get("group")) == str(control[key].get("group"))
    )
    main_common = [main[key] for key in common]
    control_common = [control[key] for key in common]
    return {
        "variant_id": variant_id,
        "evaluation_unit": "source",
        "query_budget": query_budget,
        "common_source_count": len(common),
        "positive_sources": sum(1 for key in common if str(main[key].get("group")) == "KB_Member"),
        "negative_sources": sum(1 for key in common if str(main[key].get("group")) == "True_Non_Member"),
        "common_source_whitelist_hash": sha256_obj(common),
        "excluded_main_only": len(set(main) - set(common)),
        "excluded_control_only": len(set(control) - set(common)),
        "full_pvs": {
            "metrics": summarize_membership_scores(main_common),
            "auc_ci95": bootstrap_auc_ci(
                main_common, n_bootstrap=n_bootstrap, seed=seed
            ),
        },
        "control": {
            "metrics": summarize_membership_scores(control_common),
            "auc_ci95": bootstrap_auc_ci(
                control_common, n_bootstrap=n_bootstrap, seed=seed
            ),
        },
        "paired_delta_full_pvs_minus_control": paired_bootstrap_metric_delta(
            main_common,
            control_common,
            left_score_key="pcv_score",
            right_score_key="pcv_score",
            n_bootstrap=n_bootstrap,
            seed=seed,
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze one PCV-MIA online query control")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--variant", choices=sorted(SUPPORTED_CONTROLS), required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = args.model or victim_model_slug()
    config_path = Path(args.config)
    config = load_yaml(config_path)
    scoring = config.get("scoring", {})

    query_dir = resolve_path("outputs/query_controls") / args.dataset / args.variant
    queries_path = query_dir / "queries.jsonl"
    control_manifest_path = query_dir / "control_manifest.json"
    response_dir = model_scoped_dir(
        "outputs/query_control_responses", args.dataset, model=model
    ) / args.variant
    rag_path = response_dir / "rag_responses.jsonl"
    llm_path = response_dir / "llm_only_responses.jsonl"
    response_manifest_path = rag_path.with_suffix(".manifest.json")
    required = [queries_path, control_manifest_path, rag_path, response_manifest_path]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Query-control inputs are incomplete: {missing}")

    output_dir = ensure_dir(
        model_scoped_dir("outputs/query_control_scores", args.dataset, model=model)
        / args.variant
    )
    parsed_path = output_dir / "parsed_stance.jsonl"
    score_path = output_dir / "pcv_scores.jsonl"
    parse_stance_files(
        dataset=args.dataset,
        queries_path=queries_path,
        rag_responses_path=rag_path,
        llm_responses_path=llm_path,
        output_path=parsed_path,
        resume=not args.force,
        force=args.force,
    )
    score_manifest = compute_pcv_scores(
        dataset=args.dataset,
        parsed_stance_path=parsed_path,
        output_path=score_path,
        unknown_lambda=float(scoring.get("unknown_lambda", 0.5)),
        refusal_penalty=float(scoring.get("refusal_penalty", 0.5)),
        false_acceptance_penalty_value=float(scoring.get("false_acceptance_penalty", 0.0)),
        thresholds=[float(value) for value in scoring.get("thresholds", [0.3, 0.5, 0.7, 1.0])],
        facts_path=resolve_path(config["paths"]["facts_dir"]) / f"{args.dataset}_facts.jsonl",
        benchmark_path=resolve_path(config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        queries_path=queries_path,
        resume=not args.force,
        force=args.force,
    )

    control_source_path = Path(score_manifest.get("source_scores_path") or score_path.with_name("pcv_scores_source_scores.jsonl"))
    if not control_source_path.exists():
        control_source_path = score_path.with_name(score_path.stem + "_source_scores.jsonl")
    main_source_path = (
        model_scoped_dir("outputs/scores", args.dataset, model=model)
        / f"{args.dataset}_pcv_scores_source_scores.jsonl"
    )
    if not main_source_path.exists():
        raise FileNotFoundError(f"Main full_pvs source scores are required: {main_source_path}")

    control_manifest = read_json(control_manifest_path)
    response_manifest = read_json(response_manifest_path)
    report = build_query_control_report(
        list(read_jsonl(main_source_path)),
        list(read_jsonl(control_source_path)),
        variant_id=args.variant,
        query_budget=int(response_manifest.get("query_budget", 0)),
        n_bootstrap=args.bootstrap,
        seed=args.seed,
    )
    report.update({
        "dataset": args.dataset,
        "model": model,
        "bootstrap": args.bootstrap,
        "seed": args.seed,
        "benchmark_hash": control_manifest.get("benchmark_hash"),
        "config_hash": sha256_file(config_path),
        "code": git_snapshot(),
        "input_provenance": {
            "queries": {"path": str(queries_path), "sha256": sha256_file(queries_path)},
            "rag_responses": {"path": str(rag_path), "sha256": sha256_file(rag_path)},
            "main_source_scores": {"path": str(main_source_path), "sha256": sha256_file(main_source_path)},
            "control_source_scores": {"path": str(control_source_path), "sha256": sha256_file(control_source_path)},
        },
        "planned_source_whitelist_hash": control_manifest.get("source_whitelist_hash"),
        "response_source_whitelist_hash": response_manifest.get("source_whitelist_hash"),
        "score_manifest": score_manifest,
    })
    output = (
        model_scoped_dir("outputs/diagnostics", args.dataset, model=model)
        / f"{args.dataset}_{args.variant}_query_control.json"
    )
    ensure_dir(output.parent)
    write_json(report, output)
    print(f"[saved] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
