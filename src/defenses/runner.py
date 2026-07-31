"""Real zero-API response-layer defenses for PCV-MIA v20."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..evaluation.metrics import (
    bootstrap_auc_ci,
    bootstrap_conformal_ci,
    summarize_membership_scores,
)
from ..evaluation.v20_release_controls import calibration_source_keys
from ..parsing.stance_parser import parse_stance_response
from ..scoring.pcv_scorer import compute_pcv_scores
from ..utils.hash import sha256_file
from ..utils.io import read_json, read_jsonl, write_json, write_jsonl


def _replace_literal(text: str, value: str) -> str:
    if not value:
        return text
    return re.sub(re.escape(value), "[REDACTED]", text, flags=re.IGNORECASE)


def answer_without_correction(
    response_row: dict[str, Any],
    query_row: dict[str, Any],
) -> dict[str, Any]:
    """Retain an Inconsistent stance while removing the correction value."""

    transformed = dict(response_row)
    parsed = parse_stance_response(response_row, query_row)
    if parsed.get("corrects_to_original_entity"):
        transformed["response"] = "Inconsistent"
    transformed["defense"] = "answer_without_correction"
    return transformed


def target_entity_redaction(
    response_row: dict[str, Any],
    query_row: dict[str, Any],
) -> dict[str, Any]:
    """Redact literal original/counterfactual entities from a saved response."""

    transformed = dict(response_row)
    text = str(response_row.get("response") or "")
    original = str(
        query_row.get("expected_entity")
        or query_row.get("original_entity")
        or ""
    )
    counterfactual = str(
        query_row.get("counterfactual_entity")
        or query_row.get("conflict_entity")
        or ""
    )
    transformed["response"] = _replace_literal(
        _replace_literal(text, original),
        counterfactual,
    )
    transformed["defense"] = "target_entity_redaction"
    return transformed


POLICIES: dict[
    str,
    Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
] = {
    "answer_without_correction": answer_without_correction,
    "target_entity_redaction": target_entity_redaction,
}


def _utility(
    original: list[dict[str, Any]],
    defended: list[dict[str, Any]],
) -> dict[str, float]:
    original_by_query = {str(row["query_id"]): row for row in original}
    defended_by_query = {str(row["query_id"]): row for row in defended}
    common = sorted(set(original_by_query) & set(defended_by_query))
    if not common:
        raise RuntimeError("Defense utility has no matched parsed responses")
    stance_preserved = sum(
        str(original_by_query[key].get("stance"))
        == str(defended_by_query[key].get("stance"))
        for key in common
    )
    correction_original = sum(
        bool(original_by_query[key].get("corrects_to_original_entity"))
        for key in common
    )
    correction_defended = sum(
        bool(defended_by_query[key].get("corrects_to_original_entity"))
        for key in common
    )
    refusal_original = sum(
        bool(original_by_query[key].get("refuses")) for key in common
    )
    refusal_defended = sum(
        bool(defended_by_query[key].get("refuses")) for key in common
    )
    return {
        "stance_preservation": stance_preserved / len(common),
        "answer_availability": sum(
            str(defended_by_query[key].get("parse_status")) == "success"
            for key in common
        )
        / len(common),
        "correction_availability": correction_defended / len(common),
        "correction_availability_change": (
            correction_defended - correction_original
        )
        / len(common),
        "refusal_rate_change": (
            refusal_defended - refusal_original
        )
        / len(common),
    }


def _privacy_metrics(
    source_rows: list[dict[str, Any]],
    *,
    score_key: str,
    threshold: float,
    calibration_keys: set[str],
    bootstrap: int,
    seed: int,
    conformal_alphas: list[float],
) -> dict[str, Any]:
    eval_rows = [
        row for row in source_rows if str(row.get("group")) != "Reserve"
    ]
    raw = summarize_membership_scores(
        eval_rows,
        score_key=score_key,
        threshold=threshold,
    )
    raw["AUC_CI"] = bootstrap_auc_ci(
        eval_rows,
        score_key=score_key,
        n_bootstrap=bootstrap,
        seed=seed,
    )
    conformal = {
        f"alpha_{alpha:g}": bootstrap_conformal_ci(
            source_rows,
            score_key=score_key,
            alpha=alpha,
            n_bootstrap=bootstrap,
            seed=seed,
            calibration_source_keys=calibration_keys,
        )
        for alpha in conformal_alphas
    }
    return {"raw": raw, "conformal": conformal}


def run_defense_experiments(
    *,
    dataset: str,
    queries_path: str | Path,
    rag_responses_path: str | Path,
    benchmark_path: str | Path,
    reserve_roles_path: str | Path,
    output_path: str | Path,
    facts_path: str | Path | None = None,
    threshold: float = 0.3,
    score_key: str = "pcv_score",
    bootstrap: int = 2000,
    seed: int = 42,
    conformal_alphas: list[float] | None = None,
    policies: list[str] | None = None,
    resume: bool = True,
    force: bool = False,
    config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transform saved responses, then rerun parser, scorer and calibration."""

    output = Path(output_path)
    if resume and not force and output.is_file() and output.stat().st_size:
        existing = read_json(output)
        if any(
            not row.get("implemented")
            or not row.get("privacy")
            or not row.get("utility")
            for row in existing.get("defenses", [])
        ):
            raise RuntimeError("Existing defense report is placeholder/incomplete")
        return {
            "dataset": dataset,
            "output_path": str(output),
            "skipped_existing": True,
        }
    queries = {str(row["query_id"]): row for row in read_jsonl(queries_path)}
    responses = list(read_jsonl(rag_responses_path))
    if not responses or len({str(row.get("query_id")) for row in responses}) != len(
        responses
    ):
        raise RuntimeError("Defense requires complete, unique saved RAG responses")
    missing = sorted(
        str(row.get("query_id"))
        for row in responses
        if str(row.get("query_id")) not in queries
    )
    if missing:
        raise RuntimeError(f"Defense responses reference unknown queries: {missing[:3]}")
    original_parsed = [
        parse_stance_response(row, queries[str(row["query_id"])])
        for row in responses
    ]
    calibration_keys = calibration_source_keys(reserve_roles_path)
    selected_policies = policies or list(POLICIES)
    unknown = sorted(set(selected_policies) - set(POLICIES))
    if unknown:
        raise ValueError(f"Unknown defense policies: {unknown}")
    output.parent.mkdir(parents=True, exist_ok=True)
    defense_rows: list[dict[str, Any]] = []
    for policy_name in selected_policies:
        transform = POLICIES[policy_name]
        policy_dir = output.parent / policy_name
        policy_dir.mkdir(parents=True, exist_ok=True)
        defended_responses = [
            transform(row, queries[str(row["query_id"])]) for row in responses
        ]
        response_path = policy_dir / f"{dataset}_rag_responses.jsonl"
        parsed_path = policy_dir / f"{dataset}_parsed_stances.jsonl"
        score_path = policy_dir / f"{dataset}_pcv_scores.jsonl"
        write_jsonl(defended_responses, response_path)
        defended_parsed = [
            parse_stance_response(row, queries[str(row["query_id"])])
            for row in defended_responses
        ]
        write_jsonl(defended_parsed, parsed_path)
        score_manifest = compute_pcv_scores(
            dataset=dataset,
            parsed_stance_path=parsed_path,
            output_path=score_path,
            facts_path=facts_path,
            benchmark_path=benchmark_path,
            queries_path=queries_path,
            resume=False,
            force=True,
        )
        source_score_path = Path(
            score_manifest.get("source_output_path")
            or score_path.with_name(score_path.stem + "_source_scores.jsonl")
        )
        source_rows = list(read_jsonl(source_score_path))
        privacy = _privacy_metrics(
            source_rows,
            score_key=score_key,
            threshold=threshold,
            calibration_keys=calibration_keys,
            bootstrap=bootstrap,
            seed=seed,
            conformal_alphas=conformal_alphas or [0.01, 0.05],
        )
        utility = _utility(original_parsed, defended_parsed)
        if not privacy["raw"] or not privacy["conformal"] or not utility:
            raise RuntimeError(f"{policy_name}: defense metrics are incomplete")
        defense_rows.append(
            {
                "defense": policy_name,
                "implemented": True,
                "status": "complete",
                "layer": "offline_response",
                "privacy": privacy,
                "utility": utility,
                "utility_scope": (
                    "stance preservation, answer/correction availability, "
                    "and refusal-rate change only"
                ),
                "generic_qa_utility_claimed": False,
                "artifacts": {
                    "responses": str(response_path),
                    "responses_hash": sha256_file(response_path),
                    "parsed_stances": str(parsed_path),
                    "parsed_stances_hash": sha256_file(parsed_path),
                    "source_scores": str(source_score_path),
                    "source_scores_hash": sha256_file(source_score_path),
                },
            }
        )
    report = {
        "protocol_version": "pcv-mia-v20",
        "dataset": dataset,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "defenses": defense_rows,
        "calibration_scope": "post_retriever_frozen_nonmember_calibration",
        "conformal_source_count": 245,
        "pilot_reserve_excluded_from_calibration": True,
        "input_provenance": {
            "queries_hash": sha256_file(queries_path),
            "rag_responses_hash": sha256_file(rag_responses_path),
            "benchmark_hash": sha256_file(benchmark_path),
            "reserve_roles_hash": sha256_file(reserve_roles_path),
        },
        "config_snapshot": config_snapshot or {},
    }
    write_json(report, output)
    return report
