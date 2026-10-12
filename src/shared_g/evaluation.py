"""来源级指标、配对 macro 统计、覆盖率和成本报告。"""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

from src.evaluation.metrics import (bootstrap_auc_ci, bootstrap_macro_auc_ci, clopper_pearson_interval,
                                    rates_at_threshold, roc_auc, threshold_curve, tpr_at_fpr_details)
from src.utils.hash import sha256_file

from .artifacts import ArtifactStore, read_json, read_rows, request_records, write_once, read_response_adjudications
from .config import ExperimentConfig
from .construction import generation_records, qualification_progress, review_decisions
from .scoring import answer_judgment, gated_queries, source_scores
from .types import ARMS, GROUPS, SCORE_KEYS
from .victim import response_records, validate_responses
from .retrieval import validate_retrieval


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    left, right = math.floor(position), math.ceil(position)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def finite_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: finite_json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(child) for child in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "+inf" if value > 0 else "-inf" if value < 0 else None
    return value


def paired_macro_auc_delta(dataset_rows: dict[str, list[dict[str, Any]]], left: str, right: str,
                            n_bootstrap: int, seed: int) -> dict[str, Any]:
    strata = {name: [[row for row in rows if row["group"] == group] for group in GROUPS]
              for name, rows in sorted(dataset_rows.items())}

    def delta(grouped: dict[str, list[dict[str, Any]]]) -> float | None:
        values = []
        for rows in grouped.values():
            lvalue, rvalue = roc_auc(rows, score_key=left), roc_auc(rows, score_key=right)
            if lvalue is None or rvalue is None:
                return None
            values.append(lvalue - rvalue)
        return sum(values) / len(values) if values else None

    point = delta(dataset_rows)
    samples: list[float] = []
    if point is not None and all(all(groups) for groups in strata.values()):
        rng = random.Random(seed)
        for _ in range(n_bootstrap):
            # 同一组 source 抽样同时用于左右方法，保持配对关系。
            grouped = {name: rng.choices(groups[0], k=len(groups[0])) + rng.choices(groups[1], k=len(groups[1]))
                       for name, groups in strata.items()}
            value = delta(grouped)
            if value is not None:
                samples.append(value)
    return {"left": left, "right": right, "estimate": point,
            "ci95": [percentile(samples, 0.025), percentile(samples, 0.975)],
            "bootstrap": len(samples), "seed": seed, "unit": "source_document",
            "dataset_weighting": "equal", "common_sources": sum(map(len, dataset_rows.values()))}


def metrics(config: ExperimentConfig, rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluation = config.data["evaluation"]
    cutoff = config.data["scoring"]["operational_cutoff"]
    result: dict[str, Any] = {}
    for arm in SCORE_KEYS:
        rates = rates_at_threshold(rows, cutoff, score_key=arm)
        fixed = {"cutoff": cutoff, "tpr": rates["TPR"] if rates["positive_count"] else None,
                 "fpr": rates["FPR"] if rates["negative_count"] else None,
                 "true_positive_count": rates["true_positive_count"], "false_positive_count": rates["false_positive_count"],
                 "positive_count": rates["positive_count"], "negative_count": rates["negative_count"],
                 "tpr_ci95": clopper_pearson_interval(rates["true_positive_count"], rates["positive_count"]),
                 "fpr_ci95": clopper_pearson_interval(rates["false_positive_count"], rates["negative_count"])}
        low_fpr: dict[str, Any] = {}
        curve = threshold_curve(rows, score_key=arm)
        for target in evaluation["low_fpr_targets"]:
            point = tpr_at_fpr_details(curve, target) if rows and rates["positive_count"] and rates["negative_count"] else None
            low_fpr[str(target)] = None if point is None else {"target_fpr": point["target_fpr"], "tpr": point["TPR"],
                "achieved_fpr": point["achieved_FPR"], "threshold": point["threshold"],
                "false_positive_count": point["false_positive_count"], "negative_count": point["negative_count"],
                "interpolation": False, "usage": "descriptive_empirical_roc_only"}
        result[arm] = {"auc": bootstrap_auc_ci(rows, score_key=arm, n_bootstrap=evaluation["bootstrap_samples"],
                                              seed=config.data["seed"]), "fixed_cutoff": fixed, "low_fpr": low_fpr,
                       "score_distribution": dict(Counter(str(row[arm]) for row in rows))}
    return finite_json(result)


def coverage(sources: list[dict[str, Any]], usable: list[dict[str, Any]], generations: dict[str, dict[str, Any]],
             cutoff: float) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for group in GROUPS:
        original = [row for row in sources if row["group"] == group]
        accepted = [row for row in usable if row["group"] == group]
        count = len(original)
        structural = sum(generations[row["source_key"]]["status"] == "passed" for row in original)
        output[group] = {"population": "qualified_cohort", "cohort_sources": count, "structural_pass": structural, "query_usable": len(accepted),
                         "coverage": len(accepted) / count if count else None, "abstained": count - len(accepted),
                         "cohort_alert_rate": {arm: sum(row[arm] >= cutoff for row in accepted) / count if count else None
                                                    for arm in SCORE_KEYS}}
    return output


def cost_summary(rows: list[dict[str, Any]], generations: list[dict[str, Any]],
                 responses: list[dict[str, Any]], reviews: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    reviews = reviews or []
    queries = [3 + 2 * sum(row["initial_bits"]) for row in rows]
    single = [3 + sum(row["initial_bits"]) for row in rows]
    wire_calls = sum(row.get("transport_request_count", 1 + row.get("retry_count", 0)) for row in generations)
    return {"construction_calls": wire_calls, "construction_logical_calls": len(generations),
            "construction_reconnects": max(0, wire_calls - len(generations)), "victim_calls": len(responses),
            "ai_review_calls": sum(row.get("transport_request_count", 0) for row in reviews),
            "ai_review_logical_batches": len(reviews),
            "both_arms_per_usable_source": {"mean": sum(queries) / len(queries) if queries else None,
                                            "median": percentile(queries, 0.5), "p95": percentile(queries, 0.95)},
            "each_method_per_usable_source": {"mean": sum(single) / len(single) if single else None,
                                              "median": percentile(single, 0.5), "p95": percentile(single, 0.95)},
            "tokens": {role: {field: {"observed_total": sum(row.get(field) or 0 for row in values),
                                      "missing_count": sum(row.get(field) is None for row in values)}
                              for field in ("input_tokens", "output_tokens")}
                       for role, values in (("construction", generations), ("ai_review", reviews), ("victim", responses))}}


def evaluate_dataset(config: ExperimentConfig, store: ArtifactStore, dataset: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sources = [row for row in read_rows(store.path("source_manifest.jsonl")) if row["dataset"] == dataset]
    queries = [row for row in read_rows(store.path("query_plan.jsonl")) if row["dataset"] == dataset]
    validate_retrieval(config, store, dataset)
    initial, followups = response_records(store, dataset, False), response_records(store, dataset, True)
    adjudications = read_response_adjudications(store)
    validate_responses(config, store, dataset, [q for q in queries if q["arm"] == "initial"], initial)
    expected = gated_queries(queries, initial, matcher=config.data["answer_policy"]["matcher"], adjudications=adjudications)
    validate_responses(config, store, dataset, expected, followups)
    accepted = {q["source_key"] for q in queries}
    rows = source_scores([s for s in sources if s["source_key"] in accepted], queries, initial, followups,
                        config.data["scoring"]["lambda"], matcher=config.data["answer_policy"]["matcher"], adjudications=adjudications)
    generations = generation_records(store)
    candidates = {row["source_key"] for row in read_rows(store.path("candidate_manifest.jsonl")) if row["dataset"] == dataset}
    all_attempts = [row for row in request_records(store.path("generation.jsonl")) if row["source_key"] in candidates]
    cutoff = config.data["scoring"]["operational_cutoff"]
    correction = read_json(store.path("run_config.json")).get("scoring_correction")
    query_map = {q["query_id"]: q for q in queries}
    label_sources = {}
    for phase, responses in (("initial", initial), ("followup", followups)):
        judgments = [answer_judgment(r, query_map[r["query_id"]], matcher=config.data["answer_policy"]["matcher"],
                                     adjudications=adjudications) for r in responses]
        label_sources[phase] = {
            "automatic": sum(j["label_source"] == "automatic" for j in judgments),
            "assistant_post_response": sum(j["label_source"] == "assistant_post_response" for j in judgments),
            "changed_from_automatic": sum(j["label"] != j["automatic_label"] for j in judgments),
            "unresolved": sum(j["review_status"] == "uncertain" for j in judgments),
        }
    output = {"dataset": dataset, "run_role": "formal", "statistical_unit": "source_document",
              "answer_policy": config.data["answer_policy"],
              "scoring_correction": correction,
              "response_label_sources": label_sources,
              "status": "scoring_corrected_cell_complete" if correction else "formal_cell_complete",
              "query_usable_source_count": len(rows), "metrics": metrics(config, rows),
              "coverage": coverage(sources, rows, generations, config.data["scoring"]["operational_cutoff"]),
              "qualification": qualification_progress(config, store)[dataset],
              "cost": cost_summary(rows, all_attempts, initial + followups,
                                   [r for r in request_records(store.path("semantic_review_requests.jsonl"))
                                    if r["dataset"] == dataset]),
              "gate_audit": {"triggered_slots": len(expected) // 2, "expected_followups": len(expected),
                             "observed_followups": len(followups), "missing": 0, "extra": 0},
              "paired_transitions_at_fixed_cutoff": {arm: {group: {
                  "rescued": sum(row["local_only"] < cutoff <= row[arm] for row in rows if row["group"] == group),
                  "lost": sum(row[arm] < cutoff <= row["local_only"] for row in rows if row["group"] == group)}
                  for group in GROUPS} for arm in ARMS},
              "run_config_sha256": sha256_file(store.path("run_config.json")),
              "artifact_hashes": {name: sha256_file(store.path(name, dataset)) for name in
                                  ("retrieval.jsonl", "initial_responses.jsonl", "followup_responses.jsonl", "index/index.json")
                                  if store.path(name, dataset).exists()}}
    write_once(store.path("scores.jsonl", dataset), rows)
    write_once(store.path("report.json", dataset), output)
    return output, rows


def report(config: ExperimentConfig, store: ArtifactStore, dataset: str | None = None) -> dict[str, Any]:
    run = store.validate(frozen=True)
    if dataset is not None:
        if dataset not in config.datasets:
            raise ValueError("unknown_dataset")
        return evaluate_dataset(config, store, dataset)[0]
    per_dataset: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for name in config.datasets:
        per_dataset[name], grouped[name] = evaluate_dataset(config, store, name)
    boot, seed = config.data["evaluation"]["bootstrap_samples"], config.data["seed"]
    macro = {arm: bootstrap_macro_auc_ci(grouped, score_key=arm, n_bootstrap=boot, seed=seed) for arm in SCORE_KEYS}
    rows = [row for values in grouped.values() for row in values]
    attempts = request_records(store.path("generation.jsonl"))
    responses = [row for name in config.datasets for followup in (False, True) for row in response_records(store, name, followup)]
    if len({row.get("system_fingerprint") for row in responses}) > 1:
        raise RuntimeError("formal_suite_fingerprint_drift")
    decisions = review_decisions(store)
    output = finite_json({"experiment_id": config.data["experiment_id"], "run_role": "formal",
              "answer_policy": config.data["answer_policy"], "scoring_correction": run.get("scoring_correction"),
              "status": ("scoring_corrected_evaluation_complete" if run.get("scoring_correction") else "formal_evaluation_complete")
                        if macro["correct_anchor"]["estimate"] is not None else "complete_primary_unavailable",
              "primary": "correct_anchor_macro_source_auc_conditional_on_query_usable_sources",
              "dataset_weighting": "equal", "statistical_unit": "source_document", "qualified_source_count": run["source_count"],
              "candidate_source_count": run["candidate_count"], "qualification": qualification_progress(config, store),
              "query_usable_sources": len(rows), "per_dataset": per_dataset, "macro_auc": macro,
              "paired_macro_auc_deltas": {"correct_anchor_vs_local_only": paired_macro_auc_delta(grouped, "correct_anchor", "local_only", boot, seed),
                                         "correct_anchor_vs_remote_only": paired_macro_auc_delta(grouped, "correct_anchor", "remote_only", boot, seed)},
              "cost": cost_summary(rows, attempts, responses,
                                   request_records(store.path("semantic_review_requests.jsonl"))),
              "model_profiles": run["model_profiles"],
              "retrieval_query_count": sum(len(read_rows(store.path("retrieval.jsonl", name))) for name in config.datasets),
              "observed_provider_models": sorted({row["provider_model_id"] for row in responses}),
              "observed_response_fingerprints": sorted({str(row.get("system_fingerprint")) for row in responses}),
              "run_config_sha256": sha256_file(store.path("run_config.json")),
              "prior_v24_raw_document_reuse": run["prior_v24_raw_document_reuse"],
              "historical_raw_document_reuse": run["historical_raw_document_reuse"],
              "failures": {"construction_final_statuses": dict(Counter(row["status"] for row in generation_records(store).values())),
                           "construction_reasons": dict(Counter(reason for row in generation_records(store).values()
                                                                 for reason in row.get("quality_reasons", []))),
                           "semantic_rejections": {key: decision["reason"] for key, decision in decisions.items() if not decision["accepted"]}},
              "interpretation": {"reviewer_type": read_json(store.path("semantic_review.json"))["reviewer_type"],
                                 "independent_human_annotation": False,
                                 "raw_documents_all_untouched": False, "query_budget_matched_comparison": False,
                                 "inference_population": "construction_and_semantic_qualified_sources",
                                 "selection_before_membership_and_victim": True,
                                 "cutoff_change_is_not_g_contribution": True,
                                 "no_posthoc_tuning": not bool(run.get("scoring_correction")),
                                 "response_semantic_review_is_independent_human": False,
                                 "response_semantic_review_scope": "reviewed_responses_only"
                                     if config.data["answer_policy"].get("response_adjudications") else None}})
    write_once(store.path("report.json"), output)
    return output
