"""Generator pilot 的完整性、可解析性和机制对照门禁。"""

from __future__ import annotations

from typing import Any

from ..llm.response_validation import (
    detect_api_error_text,
    response_record_is_success,
)
from ..parsing.stance_parser import parse_stance_response


def _useful_stance(parsed: dict[str, Any]) -> bool:
    return bool(
        parsed.get("supports_true_claim")
        or parsed.get("corrects_to_original_entity")
        or parsed.get("rejects_counterfactual")
    )


def evaluate_response_rows(
    rows: list[dict[str, Any]],
    queries_by_id: dict[str, dict[str, Any]],
    *,
    expected_model: str,
) -> dict[str, Any]:
    query_ids = [str(row.get("query_id") or "") for row in rows]
    unique_ids = set(query_ids)
    expected_ids = set(queries_by_id)
    candidate_rows = [
        row
        for row in rows
        if not row.get("error") and str(row.get("response") or "").strip()
    ]
    valid_rows = [
        row
        for row in rows
        if response_record_is_success(row)
    ]
    parsed = [
        parse_stance_response(row, queries_by_id[str(row["query_id"])])
        for row in valid_rows
        if str(row.get("query_id") or "") in queries_by_id
    ]
    parseable = sum(str(row.get("stance") or "") != "unrelated" for row in parsed)
    identity_drift = sum(
        1
        for row in candidate_rows
        if row.get("provider_model_id")
        and str(row["provider_model_id"]) != expected_model
    )
    missing_provider_model = sum(
        1 for row in candidate_rows if not row.get("provider_model_id")
    )
    api_error_text_responses = sum(
        detect_api_error_text(str(row.get("response") or "")) is not None
        for row in candidate_rows
    )
    useful = sum(_useful_stance(row) for row in parsed)
    parsed_by_group: dict[str, list[dict[str, Any]]] = {}
    for row in parsed:
        parsed_by_group.setdefault(str(row.get("group")), []).append(row)
    useful_by_group = {
        group: sum(_useful_stance(row) for row in group_rows)
        / max(1, len(group_rows))
        for group, group_rows in parsed_by_group.items()
    }
    member_rows = [
        row for row in valid_rows if str(row.get("group")) == "KB_Member"
    ]
    target_hits = sum(
        bool(row.get("target_doc_retrieved") or row.get("target_source_retrieved"))
        for row in member_rows
    )
    return {
        "expected": len(expected_ids),
        "rows": len(rows),
        "unique_queries": len(unique_ids),
        "duplicates": len(query_ids) - len(unique_ids),
        "missing_queries": len(expected_ids - unique_ids),
        "unexpected_queries": len(unique_ids - expected_ids),
        "valid_responses": len(valid_rows),
        "empty_or_error_responses": len(rows) - len(valid_rows),
        "response_completeness": len(valid_rows) / max(1, len(expected_ids)),
        "stance_parse_rate": parseable / max(1, len(valid_rows)),
        "useful_stance_rate": useful / max(1, len(parsed)),
        "useful_stance_rate_by_group": useful_by_group,
        "target_doc_recall_at_5": target_hits / max(1, len(member_rows)),
        "target_doc_recall_denominator_group": "KB_Member",
        "target_doc_recall_denominator": len(member_rows),
        "model_identity_drift": identity_drift,
        "missing_provider_model_metadata": missing_provider_model,
        "api_error_text_responses": api_error_text_responses,
    }


def evaluate_generator_pilot_dataset(
    systems: dict[str, list[dict[str, Any]]],
    queries: list[dict[str, Any]],
    *,
    expected_model: str,
    stance_parse_rate_min: float = 0.99,
    hybrid_max_drop: float = 0.02,
    oracle_random_min_margin: float = 0.10,
) -> dict[str, Any]:
    queries_by_id = {str(row["query_id"]): row for row in queries}
    metrics = {
        name: evaluate_response_rows(
            rows,
            queries_by_id,
            expected_model=expected_model,
        )
        for name, rows in systems.items()
    }
    required = {
        "dense",
        "bm25",
        "hybrid",
        "llm_only",
        "oracle",
        "random",
    }
    missing_systems = sorted(required - set(metrics))
    integrity_passed = not missing_systems and all(
        row["response_completeness"] == 1.0
        and row["stance_parse_rate"] >= stance_parse_rate_min
        and row["duplicates"] == 0
        and row["missing_queries"] == 0
        and row["unexpected_queries"] == 0
        and row["empty_or_error_responses"] == 0
        and row["model_identity_drift"] == 0
        and row["missing_provider_model_metadata"] == 0
        and row["api_error_text_responses"] == 0
        for row in metrics.values()
    )
    hybrid_drop = (
        float(metrics.get("dense", {}).get("target_doc_recall_at_5", 0.0))
        - float(metrics.get("hybrid", {}).get("target_doc_recall_at_5", 0.0))
    )
    oracle_margin = (
        float(metrics.get("oracle", {}).get("useful_stance_rate", 0.0))
        - float(metrics.get("random", {}).get("useful_stance_rate", 0.0))
    )
    oracle_random_by_group = {
        group: {
            "oracle": float(
                metrics.get("oracle", {})
                .get("useful_stance_rate_by_group", {})
                .get(group, 0.0)
            ),
            "random": float(
                metrics.get("random", {})
                .get("useful_stance_rate_by_group", {})
                .get(group, 0.0)
            ),
        }
        for group in ("KB_Member", "True_Non_Member", "Reserve")
    }
    checks = {
        "all_systems_present": not missing_systems,
        "response_and_parse_integrity": integrity_passed,
        "hybrid_recall_drop": hybrid_drop <= hybrid_max_drop,
        "oracle_better_than_random": oracle_margin >= oracle_random_min_margin,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "missing_systems": missing_systems,
        "hybrid_recall_at_5_drop_vs_dense": hybrid_drop,
        "oracle_minus_random_utility": oracle_margin,
        "oracle_random_utility_by_group": oracle_random_by_group,
        "systems": metrics,
    }
