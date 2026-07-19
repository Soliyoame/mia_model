"""Source-level attribution analysis for the independent LLM-only matched control."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from ..parsing.stance_parser import parse_stance_response
from ..rag.runner import response_is_success
from ..scoring.pcv_scorer import score_pair
from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import ensure_dir, read_jsonl, write_json, write_jsonl
from .metrics import (
    bootstrap_auc_ci,
    paired_bootstrap_metric_delta,
    summarize_membership_scores,
)


EVAL_GROUPS = {"KB_Member", "True_Non_Member"}


def _unique_by(rows: list[dict[str, Any]], key: str, *, label: str) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if not value:
            raise RuntimeError(f"{label} row is missing {key}")
        if value in values:
            raise RuntimeError(f"Duplicate {label} {key}: {value}")
        values[value] = row
    return values


def build_matched_control_analysis(
    *,
    dataset: str,
    queries_path: str | Path,
    llm_responses_path: str | Path,
    main_source_scores_path: str | Path,
    output_dir: str | Path,
    unknown_lambda: float = 0.5,
    refusal_penalty: float = 0.5,
    false_acceptance_penalty_value: float = 0.0,
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Parse and aggregate LLM-only responses, then pair them with canonical RAG scores."""
    query_file = Path(queries_path)
    response_file = Path(llm_responses_path)
    main_file = Path(main_source_scores_path)
    out_dir = ensure_dir(output_dir)

    query_rows = [row for row in read_jsonl(query_file) if row.get("accepted", True)]
    queries = _unique_by(query_rows, "query_id", label="query")
    response_rows = list(read_jsonl(response_file))
    responses = _unique_by(response_rows, "query_id", label="LLM-only response")
    invalid = [
        query_id
        for query_id, row in responses.items()
        if str(row.get("mode") or "") != "llm_only" or not response_is_success(row)
    ]
    if invalid:
        raise RuntimeError(f"Invalid LLM-only responses: {len(invalid)}")
    if set(responses) != set(queries):
        raise RuntimeError(
            "Matched response/query ids differ: "
            f"missing={len(set(queries) - set(responses))} "
            f"unexpected={len(set(responses) - set(queries))}"
        )

    stance_by_pair: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for query_id, query in queries.items():
        response = responses[query_id]
        for key in (
            "pair_id",
            "audit_id",
            "source_id",
            "source_key",
            "dataset",
            "group",
            "claim_type",
            "query_type",
        ):
            response_value = str(response.get(key) or "")
            query_value = str(query.get(key) or "")
            if response_value and response_value != query_value:
                raise RuntimeError(
                    f"Matched response/query metadata differ: {query_id}/{key}"
                )
        stance = parse_stance_response(response, query)
        pair_id = str(stance.get("pair_id") or "")
        if not pair_id:
            raise RuntimeError(f"Query is missing pair_id: {query_id}")
        query_type = str(stance.get("query_type") or "default")
        logical_id = f"{pair_id}::{query_type}"
        claim_type = str(stance.get("claim_type") or "")
        if claim_type not in {"true", "counterfactual"}:
            raise RuntimeError(f"Invalid claim type: {query_id}/{claim_type}")
        if claim_type in stance_by_pair[logical_id]:
            raise RuntimeError(f"Duplicate matched pair cell: {logical_id}/{claim_type}")
        stance_by_pair[logical_id][claim_type] = stance

    pair_rows: list[dict[str, Any]] = []
    by_audit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for logical_id, cells in sorted(stance_by_pair.items()):
        if set(cells) != {"true", "counterfactual"}:
            raise RuntimeError(f"Incomplete matched pair: {logical_id}")
        plus = cells["true"]
        minus = cells["counterfactual"]
        for key in ("audit_id", "source_key", "group"):
            plus_value = str(plus.get(key) or "")
            minus_value = str(minus.get(key) or "")
            if not plus_value or plus_value != minus_value:
                raise RuntimeError(f"Matched pair has inconsistent {key}: {logical_id}")
        score = score_pair(
            plus,
            minus,
            unknown_lambda=unknown_lambda,
            refusal_penalty=refusal_penalty,
            false_acceptance_penalty_value=false_acceptance_penalty_value,
        )
        pair_row = {
            "logical_pair_id": logical_id,
            "pair_id": plus.get("pair_id"),
            "query_type": plus.get("query_type") or "default",
            "audit_id": plus.get("audit_id"),
            "doc_id": plus.get("doc_id"),
            "source_id": plus.get("source_id"),
            "source_key": plus.get("source_key"),
            "dataset": plus.get("dataset") or dataset,
            "group": plus.get("group"),
            "pvs_llm": score["cvg"],
            "support_score_llm": score["support_score"],
            "correction_score_llm": score["correction_score"],
            "false_acceptance_penalty_llm": score["false_acceptance_penalty"],
        }
        pair_rows.append(pair_row)
        by_audit[str(pair_row["audit_id"])].append(pair_row)

    audit_rows: list[dict[str, Any]] = []
    for audit_id, rows in sorted(by_audit.items()):
        audit_rows.append({
            "audit_id": audit_id,
            "doc_id": rows[0].get("doc_id"),
            "source_id": rows[0].get("source_id"),
            "source_key": rows[0].get("source_key"),
            "dataset": rows[0].get("dataset") or dataset,
            "group": rows[0].get("group"),
            "num_pairs": len(rows),
            "pvs_llm": mean(float(row["pvs_llm"]) for row in rows),
        })

    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in audit_rows:
        source_key = str(row.get("source_key") or "")
        if not source_key:
            raise RuntimeError(f"Audit row is missing source_key: {row.get('audit_id')}")
        by_source[source_key].append(row)
    matched_source_rows: list[dict[str, Any]] = []
    for source_key, rows in sorted(by_source.items()):
        groups = {str(row.get("group")) for row in rows}
        if len(groups) != 1:
            raise RuntimeError(f"Matched source crosses groups: {source_key}")
        matched_source_rows.append({
            "source_key": source_key,
            "source_id": rows[0].get("source_id"),
            "dataset": rows[0].get("dataset") or dataset,
            "group": rows[0].get("group"),
            "num_chunks": len(rows),
            "num_pairs": sum(int(row.get("num_pairs", 0)) for row in rows),
            "pvs_llm": mean(float(row["pvs_llm"]) for row in rows),
        })

    main_rows = list(read_jsonl(main_file))
    main_by_source = _unique_by(main_rows, "source_key", label="main source score")
    matched_by_source = _unique_by(
        matched_source_rows,
        "source_key",
        label="matched source score",
    )
    main_eval = {
        key for key, row in main_by_source.items() if str(row.get("group")) in EVAL_GROUPS
    }
    matched_eval = {
        key for key, row in matched_by_source.items() if str(row.get("group")) in EVAL_GROUPS
    }
    if main_eval != matched_eval:
        raise RuntimeError(
            "Main/matched evaluation source sets differ: "
            f"main_only={len(main_eval - matched_eval)} "
            f"matched_only={len(matched_eval - main_eval)}"
        )

    merged_rows: list[dict[str, Any]] = []
    for source_key, main_row in sorted(main_by_source.items()):
        matched_row = matched_by_source.get(source_key)
        if matched_row is None:
            if str(main_row.get("group")) in EVAL_GROUPS:
                raise RuntimeError(f"Matched score missing for evaluation source: {source_key}")
            continue
        if str(main_row.get("group") or "") != str(matched_row.get("group") or ""):
            raise RuntimeError(f"Main/matched source groups differ: {source_key}")
        rag_score = float(main_row.get("pcv_score", main_row.get("cvg_rag", 0.0)))
        llm_score = float(matched_row["pvs_llm"])
        merged_rows.append({
            **main_row,
            "pvs_rag": rag_score,
            "cvg_rag": rag_score,
            "pvs_llm": llm_score,
            "cvg_llm": llm_score,
            "cg_cvg": rag_score - llm_score,
            "matched_num_chunks": matched_row.get("num_chunks"),
            "matched_num_pairs": matched_row.get("num_pairs"),
        })

    eval_rows = [row for row in merged_rows if str(row.get("group")) in EVAL_GROUPS]
    rag_metrics = summarize_membership_scores(eval_rows, score_key="pcv_score")
    llm_metrics = summarize_membership_scores(eval_rows, score_key="pvs_llm")
    context_metrics = summarize_membership_scores(eval_rows, score_key="cg_cvg")
    group_means: dict[str, dict[str, Any]] = {}
    for group in sorted(EVAL_GROUPS):
        rows = [row for row in eval_rows if str(row.get("group")) == group]
        if not rows:
            raise RuntimeError(f"Matched analysis has no source rows for group: {group}")
        group_means[group] = {
            "count": len(rows),
            "pcv_score": mean(float(row["pcv_score"]) for row in rows),
            "pvs_llm": mean(float(row["pvs_llm"]) for row in rows),
            "cg_cvg": mean(float(row["cg_cvg"]) for row in rows),
        }
    report = {
        "dataset": dataset,
        "evaluation_unit": "source",
        "role": "matched_control_attribution",
        "planned_queries": len(queries),
        "complete_pairs": len(pair_rows),
        "audit_chunks": len(audit_rows),
        "source_count": len(eval_rows),
        "source_whitelist_hash": sha256_obj(sorted(main_eval)),
        "score_definitions": {
            "pcv_score": "canonical RAG-only PVS from the main run",
            "pvs_llm": "same pair/chunk/source aggregation using LLM-only responses",
            "cg_cvg": "pcv_score - pvs_llm; attribution diagnostic only",
        },
        "metrics": {
            "rag_main": rag_metrics,
            "llm_only_negative_control": llm_metrics,
            "context_gain_diagnostic": context_metrics,
        },
        "auc_ci95": {
            "rag_main": bootstrap_auc_ci(
                eval_rows,
                score_key="pcv_score",
                n_bootstrap=n_bootstrap,
                seed=seed,
            ),
            "llm_only_negative_control": bootstrap_auc_ci(
                eval_rows,
                score_key="pvs_llm",
                n_bootstrap=n_bootstrap,
                seed=seed,
            ),
            "context_gain_diagnostic": bootstrap_auc_ci(
                eval_rows,
                score_key="cg_cvg",
                n_bootstrap=n_bootstrap,
                seed=seed,
            ),
        },
        "paired_delta_rag_minus_llm": paired_bootstrap_metric_delta(
            eval_rows,
            eval_rows,
            left_score_key="pcv_score",
            right_score_key="pvs_llm",
            n_bootstrap=n_bootstrap,
            seed=seed,
        ),
        "group_means": group_means,
        "scoring": {
            "unknown_lambda": unknown_lambda,
            "refusal_penalty": refusal_penalty,
            "false_acceptance_penalty": false_acceptance_penalty_value,
            "bootstrap": n_bootstrap,
            "seed": seed,
        },
        "input_provenance": {
            "queries": {"path": str(query_file.resolve()), "sha256": sha256_file(query_file)},
            "llm_only_responses": {
                "path": str(response_file.resolve()),
                "sha256": sha256_file(response_file),
            },
            "main_source_scores": {
                "path": str(main_file.resolve()),
                "sha256": sha256_file(main_file),
            },
        },
    }

    pair_path = out_dir / f"{dataset}_matched_control_pair_scores.jsonl"
    audit_path = out_dir / f"{dataset}_matched_control_audit_scores.jsonl"
    source_path = out_dir / f"{dataset}_matched_control_source_scores.jsonl"
    merged_path = out_dir / f"{dataset}_canonical_source_scores.jsonl"
    report_path = out_dir / f"{dataset}_matched_control_analysis.json"
    write_jsonl(pair_rows, pair_path)
    write_jsonl(audit_rows, audit_path)
    write_jsonl(matched_source_rows, source_path)
    write_jsonl(merged_rows, merged_path)
    write_json(report, report_path)
    return {
        "report": report,
        "paths": {
            "pair_scores": pair_path,
            "audit_scores": audit_path,
            "source_scores": source_path,
            "canonical_source_scores": merged_path,
            "analysis": report_path,
        },
    }
