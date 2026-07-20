"""生成 P0 source-level PCV 消融、预算曲线和可追溯元数据。"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import (  # noqa: E402
    bootstrap_auc_ci,
    paired_bootstrap_metric_delta,
    summarize_membership_scores,
)
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import ensure_dir, load_yaml, read_jsonl, write_json  # noqa: E402
from src.utils.run_context import git_snapshot, model_scoped_dir, victim_model_slug  # noqa: E402

EVAL_GROUPS = {"KB_Member", "True_Non_Member"}
DEFAULT_VARIANTS = (
    "full_pvs",
    "qplus_only",
    "qminus_only",
    "correction_only",
    "quality_weighted",
    "primary_only",
)
NOT_APPLICABLE_VARIANTS = {
    "unweighted": (
        "The frozen P0 full_pvs already uses unweighted hierarchical means; "
        "an unweighted ablation would be identical to the main method."
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PCV-MIA source-level offline ablation")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", default=None, help="模型目录 slug；默认读取 PCV_VICTIM_MODEL")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pair_value(row: dict[str, Any], variant: str) -> float:
    if variant == "qplus_only":
        return float(row.get("support_score_rag", 0.0))
    if variant == "qminus_only":
        return float(row.get("correction_score_rag", 0.0))
    if variant == "correction_only":
        return float(bool(row.get("correct_counterfactual_rag")))
    if variant in {"full_pvs", "quality_weighted", "primary_only"}:
        return float(row.get("cvg_rag", 0.0))
    if variant in NOT_APPLICABLE_VARIANTS:
        raise ValueError(f"Variant {variant} is not applicable: {NOT_APPLICABLE_VARIANTS[variant]}")
    raise ValueError(f"Unknown ablation variant: {variant}")


def _aggregate_variant(pairs: list[dict[str, Any]], variant: str) -> float:
    """严格按 pair→chunk(audit)→source 分层聚合，复现冻结的 source 主公式。"""
    by_audit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pairs:
        audit_id = str(row.get("audit_id") or row.get("doc_id") or row.get("logical_pair_id") or "")
        by_audit[audit_id].append(row)

    chunk_scores: list[float] = []
    for rows in by_audit.values():
        selected = rows
        if variant == "primary_only":
            primary = [row for row in rows if str(row.get("selection_tier")) == "primary"]
            selected = primary or rows
        if variant == "quality_weighted":
            weights = [max(0.0, float(row.get("quality_weight", 1.0))) for row in selected]
            weight_sum = sum(weights)
            score = (
                sum(weight * _pair_value(row, variant) for weight, row in zip(weights, selected))
                / weight_sum
                if weight_sum > 0
                else _mean([_pair_value(row, variant) for row in selected])
            )
        else:
            score = _mean([_pair_value(row, variant) for row in selected])
        chunk_scores.append(score)
    return _mean(chunk_scores)


def _group_complete_pairs(
    pair_rows: list[dict[str, Any]],
    eligible_sources: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        if str(row.get("group")) not in EVAL_GROUPS or not row.get("complete_rag_pair", True):
            continue
        source_key = str(row.get("source_key") or "")
        if source_key and (eligible_sources is None or source_key in eligible_sources):
            by_source[source_key].append(row)
    for source_key, rows in by_source.items():
        groups = {str(row.get("group")) for row in rows}
        if len(groups) != 1:
            raise RuntimeError(f"Source crosses groups: {source_key}: {sorted(groups)}")
        rows.sort(key=lambda row: (
            str(row.get("audit_id") or row.get("doc_id") or ""),
            str(row.get("logical_pair_id") or row.get("pair_id") or ""),
        ))
    return by_source


def build_source_variants(
    pair_rows: list[dict[str, Any]],
    *,
    eligible_sources: set[str] | None = None,
    variants: tuple[str, ...] = DEFAULT_VARIANTS,
) -> dict[str, list[dict[str, Any]]]:
    by_source = _group_complete_pairs(pair_rows, eligible_sources)
    output: dict[str, list[dict[str, Any]]] = {variant: [] for variant in variants}
    for source_key, rows in sorted(by_source.items()):
        base = {"source_key": source_key, "group": str(rows[0].get("group")), "num_pairs": len(rows)}
        for variant in variants:
            output[variant].append({**base, "score": _aggregate_variant(rows, variant)})
    return output


def build_budget_curves(
    pair_rows: list[dict[str, Any]],
    *,
    eligible_sources: set[str] | None = None,
    variants: tuple[str, ...] = DEFAULT_VARIANTS,
    query_budgets: tuple[int, ...] = (2, 4, 6, 8),
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    by_source = _group_complete_pairs(pair_rows, eligible_sources)
    if not query_budgets or any(calls <= 0 or calls % 2 for calls in query_budgets):
        raise ValueError("Query budgets must be positive even integers")
    if "full_pvs" not in variants:
        raise ValueError("Budget curves require full_pvs as the paired reference")
    max_pair_budget = max(query_budgets) // 2
    common_sources = {
        source_key for source_key, pairs in by_source.items() if len(pairs) >= max_pair_budget
    }
    curves: dict[str, Any] = {}
    for calls in query_budgets:
        pair_budget = calls // 2
        variant_rows: dict[str, list[dict[str, Any]]] = {}
        for variant in variants:
            variant_rows[variant] = [
                {
                    "source_key": source_key,
                    "group": str(by_source[source_key][0].get("group")),
                    "score": _aggregate_variant(by_source[source_key][:pair_budget], variant),
                }
                for source_key in sorted(common_sources)
            ]
        baseline = variant_rows["full_pvs"]
        variant_metrics: dict[str, Any] = {}
        for variant in variants:
            rows = variant_rows[variant]
            variant_metrics[variant] = {
                "variant_id": variant,
                "query_budget": calls,
                "source_count": len(rows),
                "metrics": summarize_membership_scores(rows, score_key="score"),
                "auc_ci95": bootstrap_auc_ci(
                    rows,
                    score_key="score",
                    n_bootstrap=n_bootstrap,
                    seed=seed,
                ),
                "paired_delta_full_pvs_minus_variant": (
                    None
                    if variant == "full_pvs"
                    else paired_bootstrap_metric_delta(
                        baseline,
                        rows,
                        left_score_key="score",
                        right_score_key="score",
                        n_bootstrap=n_bootstrap,
                        seed=seed,
                    )
                ),
            }
        curves[str(calls)] = {
            "query_budget": calls,
            "source_count": len(common_sources),
            "source_whitelist_hash": sha256_obj(sorted(common_sources)),
            "variants": variant_metrics,
        }
    return {
        "bootstrap": n_bootstrap,
        "seed": seed,
        "common_source_count": len(common_sources),
        "common_source_whitelist_hash": sha256_obj(sorted(common_sources)),
        "excluded_for_max_budget": len(by_source) - len(common_sources),
        "curves": curves,
    }


def _eligible_eval_sources(coverage_rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("source_key"))
        for row in coverage_rows
        if str(row.get("group")) in EVAL_GROUPS and bool(row.get("evaluation_eligible"))
    }


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    config = load_yaml(config_path)
    variant_cfg = config.get("experiment_variants", {})
    configured = tuple(str(value) for value in variant_cfg.get("offline", DEFAULT_VARIANTS))
    not_applicable = {variant: NOT_APPLICABLE_VARIANTS[variant] for variant in configured if variant in NOT_APPLICABLE_VARIANTS}
    variants_to_run = tuple(variant for variant in configured if variant not in NOT_APPLICABLE_VARIANTS)
    unknown = sorted(set(variants_to_run) - set(DEFAULT_VARIANTS))
    if unknown:
        raise ValueError(f"Unsupported offline variants: {unknown}")
    query_budgets = tuple(int(value) for value in variant_cfg.get("query_budgets", (2, 4, 6, 8)))
    model = args.model or victim_model_slug()
    scores_dir = model_scoped_dir("outputs/scores", args.dataset, model=model)
    pair_path = scores_dir / f"{args.dataset}_pcv_scores_pair_scores.jsonl"
    if not pair_path.exists():
        raise FileNotFoundError(f"Pair scores are required: {pair_path}")
    coverage_path = scores_dir / f"{args.dataset}_pcv_scores_source_coverage.jsonl"
    source_scores_path = scores_dir / f"{args.dataset}_pcv_scores_source_scores.jsonl"
    if not coverage_path.exists() or not source_scores_path.exists():
        raise FileNotFoundError("Source coverage and source scores are required for canonical ablation")
    pair_rows = list(read_jsonl(pair_path))
    eligible_sources = _eligible_eval_sources(list(read_jsonl(coverage_path)))
    variants = build_source_variants(
        pair_rows,
        eligible_sources=eligible_sources,
        variants=variants_to_run,
    )
    baseline = variants["full_pvs"]
    source_keys = sorted(str(row["source_key"]) for row in baseline)
    if set(source_keys) != eligible_sources:
        raise RuntimeError("Ablation source whitelist does not match the source coverage ledger")
    expected_full = {
        str(row.get("source_key")): float(row.get("pcv_score", 0.0))
        for row in read_jsonl(source_scores_path)
        if str(row.get("group")) in EVAL_GROUPS
    }
    mismatched = [
        row["source_key"] for row in baseline
        if abs(float(row["score"]) - expected_full.get(str(row["source_key"]), float("inf"))) > 1e-9
    ]
    if mismatched:
        raise RuntimeError(f"full_pvs does not reproduce source scores for {len(mismatched)} sources")

    benchmark_hash_path = PROJECT_ROOT / "datasets" / "benchmarks" / f"{args.dataset}_attack_benchmark.sha256"
    provenance = {
        "benchmark_hash": benchmark_hash_path.read_text(encoding="utf-8").strip() if benchmark_hash_path.exists() else "",
        "config_hash": sha256_file(config_path),
        "code": git_snapshot(),
        "source_whitelist_hash": sha256_obj(source_keys),
        "main_score_definition": "pair mean within chunk, then equal chunk mean within source",
    }

    variant_report: dict[str, Any] = {}
    for variant_id, rows in variants.items():
        variant_report[variant_id] = {
            "variant_id": variant_id,
            "query_budget": "all_available_pairs",
            "source_count": len(rows),
            **provenance,
            "metrics": summarize_membership_scores(rows, score_key="score"),
            "auc_ci95": bootstrap_auc_ci(
                rows, score_key="score", n_bootstrap=args.bootstrap, seed=args.seed
            ),
            "paired_delta_full_pvs_minus_variant": (
                None
                if variant_id == "full_pvs"
                else paired_bootstrap_metric_delta(
                    baseline,
                    rows,
                    left_score_key="score",
                    right_score_key="score",
                    n_bootstrap=args.bootstrap,
                    seed=args.seed,
                )
            ),
        }

    report = {
        "dataset": args.dataset,
        "model": model,
        "evaluation_unit": "source",
        "bootstrap": args.bootstrap,
        "seed": args.seed,
        **provenance,
        "source_count": len(source_keys),
        "variants": variant_report,
        "not_applicable_variants": not_applicable,
        "budget_curves": build_budget_curves(
            pair_rows,
            eligible_sources=eligible_sources,
            variants=variants_to_run,
            query_budgets=query_budgets,
            n_bootstrap=args.bootstrap,
            seed=args.seed,
        ),
        "pending_query_controls": [
            "random_same_type_counterfactual",
            "independent_unpaired_query",
            "no_stealth_filter",
        ],
    }
    output = Path(args.output) if args.output else (
        model_scoped_dir("outputs/diagnostics", args.dataset, model=model)
        / f"{args.dataset}_p0_ablation.json"
    )
    ensure_dir(output.parent)
    write_json(report, output)
    print(f"[saved] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
