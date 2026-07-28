"""Prepare a deterministic, API-free single-cell pilot query plan and budget."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import ensure_dir, load_yaml, read_jsonl, resolve_path, write_json, write_jsonl  # noqa: E402


DEFAULT_SOURCE_COUNTS = {
    "KB_Member": 10,
    "True_Non_Member": 10,
    "Reserve": 5,
}


def _stable_source_rank(source_key: str, group: str, seed: int) -> str:
    payload = f"{seed}|{group}|{source_key}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_fixed_source_rows(
    source_key: str,
    rows: list[dict[str, Any]],
    pairs_per_source: int,
) -> None:
    expected_queries = pairs_per_source * 2
    query_ids = [str(row.get("query_id") or "") for row in rows]
    if len(rows) != expected_queries or len(set(query_ids)) != expected_queries:
        raise RuntimeError(
            f"Pilot source {source_key} must have exactly {expected_queries} unique queries; "
            f"observed rows={len(rows)} unique={len(set(query_ids))}"
        )
    query_texts = [str(row.get("query") or "") for row in rows]
    if not all(query_texts) or len(set(query_texts)) != expected_queries:
        raise RuntimeError(
            f"Pilot source {source_key} must have exactly {expected_queries} non-empty, "
            f"text-unique queries; observed rows={len(rows)} "
            f"unique_texts={len(set(query_texts))}"
        )
    pairs: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pair_key = f"{row.get('pair_id')}::{row.get('query_type') or 'default'}"
        pairs.setdefault(pair_key, []).append(row)
    if len(pairs) != pairs_per_source:
        raise RuntimeError(
            f"Pilot source {source_key} must have exactly {pairs_per_source} pairs; "
            f"observed={len(pairs)}"
        )
    for pair_key, members in pairs.items():
        claim_types = sorted(str(member.get("claim_type")) for member in members)
        if claim_types != ["counterfactual", "true"]:
            raise RuntimeError(
                f"Pilot pair {pair_key} is incomplete: claim_types={claim_types}"
            )


def select_pilot_queries(
    rows: list[dict[str, Any]],
    source_counts: dict[str, int],
    *,
    seed: int,
    pairs_per_source: int,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    by_group: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        group = str(row.get("group") or "")
        source_key = str(row.get("source_key") or row.get("source_id") or "")
        if not group or not source_key:
            raise RuntimeError(f"Query is missing group/source_key: {row.get('query_id')}")
        by_group.setdefault(group, {}).setdefault(source_key, []).append(row)

    selected_source_keys: dict[str, list[str]] = {}
    selected_rows: list[dict[str, Any]] = []
    selected_query_texts: set[str] = set()
    for group, requested_count in source_counts.items():
        candidates = by_group.get(group, {})
        if len(candidates) < requested_count:
            raise RuntimeError(
                f"Pilot requires {requested_count} {group} sources; available={len(candidates)}"
            )
        ranked = sorted(
            candidates,
            key=lambda source_key: (_stable_source_rank(source_key, group, seed), source_key),
        )
        chosen: list[str] = []
        for source_key in ranked:
            source_rows = candidates[source_key]
            _validate_fixed_source_rows(source_key, source_rows, pairs_per_source)
            source_query_texts = {str(row["query"]) for row in source_rows}
            if source_query_texts & selected_query_texts:
                continue
            chosen.append(source_key)
            selected_query_texts.update(source_query_texts)
            if len(chosen) == requested_count:
                break
        if len(chosen) != requested_count:
            raise RuntimeError(
                f"Pilot requires {requested_count} globally text-unique {group} sources; "
                f"selected={len(chosen)} available={len(candidates)}"
            )
        selected_source_keys[group] = chosen
        for source_key in chosen:
            source_rows = candidates[source_key]
            selected_rows.extend(source_rows)

    selected_rows.sort(
        key=lambda row: (
            str(row.get("group")),
            str(row.get("source_key") or row.get("source_id")),
            int(row.get("fixed_budget_pair_rank") or 0),
            str(row.get("claim_type")),
        )
    )
    return selected_rows, selected_source_keys


def formal_cell_reference(pairs_per_source: int) -> dict[str, int]:
    """Return formal call counts derived from the frozen per-source budget."""

    queries_per_source = pairs_per_source * 2
    formal_sources = 1250
    evaluation_sources = 1000
    return {
        "sources_including_reserve": formal_sources,
        "rag_calls_including_reserve": formal_sources * queries_per_source,
        "matched_llm_only_calls_including_reserve": (
            formal_sources * queries_per_source
        ),
        "member_nonmember_evaluation_sources": evaluation_sources,
        "member_nonmember_rag_calls": evaluation_sources * queries_per_source,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a deterministic API-free single-cell pilot plan"
    )
    parser.add_argument("--dataset", default="enron")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--queries-path", default=None)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional exact pilot output directory.",
    )
    parser.add_argument("--pilot-id", default="pilot_qwen3_5_397b_dense")
    parser.add_argument("--generator-id", default="Qwen3.5-397B")
    parser.add_argument(
        "--retriever-id", default="sentence-transformers/all-MiniLM-L6-v2"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--member-sources", type=int, default=10)
    parser.add_argument("--nonmember-sources", type=int, default=10)
    parser.add_argument("--reserve-sources", type=int, default=5)
    parser.add_argument("--input-price-usd-per-million-tokens", type=float, default=None)
    parser.add_argument("--output-price-usd-per-million-tokens", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_yaml(args.config)
    protocol = config.get("experiment_protocol", {})
    pairs_per_source = int(protocol.get("pairs_per_source", 3))
    queries_path = (
        resolve_path(args.queries_path)
        if args.queries_path
        else resolve_path(config["paths"]["queries_dir"])
        / f"{args.dataset}_paired_queries.jsonl"
    )
    if not queries_path.exists():
        raise FileNotFoundError(queries_path)

    source_counts = {
        "KB_Member": args.member_sources,
        "True_Non_Member": args.nonmember_sources,
        "Reserve": args.reserve_sources,
    }
    if any(count < 0 for count in source_counts.values()) or sum(source_counts.values()) < 1:
        raise ValueError("Pilot source counts must be non-negative and sum to at least one")

    selected_rows, selected_source_keys = select_pilot_queries(
        list(read_jsonl(queries_path)),
        source_counts,
        seed=args.seed,
        pairs_per_source=pairs_per_source,
    )
    query_ids = [str(row["query_id"]) for row in selected_rows]
    query_texts = [str(row["query"]) for row in selected_rows]
    source_total = sum(source_counts.values())
    rag_calls = len(selected_rows)
    llm_only_calls = len(selected_rows)
    total_calls = rag_calls + llm_only_calls
    max_output_tokens = int(config.get("generation", {}).get("max_tokens", 512))

    output_dir = ensure_dir(
        resolve_path(args.output_dir)
        if args.output_dir
        else (
            resolve_path(config["paths"]["query_controls_dir"])
            / args.dataset
            / args.pilot_id
        )
    )
    output_queries = output_dir / "queries.jsonl"
    write_jsonl(selected_rows, output_queries)

    pricing_available = (
        args.input_price_usd_per_million_tokens is not None
        and args.output_price_usd_per_million_tokens is not None
    )
    output_only_hard_cap_usd = None
    if args.output_price_usd_per_million_tokens is not None:
        output_only_hard_cap_usd = (
            total_calls
            * max_output_tokens
            * args.output_price_usd_per_million_tokens
            / 1_000_000
        )

    budget = {
        "pilot_id": args.pilot_id,
        "dataset": args.dataset,
        "generator_id": args.generator_id,
        "retriever_backend": "dense",
        "retriever_id": args.retriever_id,
        "seed": args.seed,
        "source_counts": source_counts,
        "source_total": source_total,
        "pairs_per_source": pairs_per_source,
        "queries_per_source": pairs_per_source * 2,
        "query_count": len(selected_rows),
        "unique_query_count": len(set(query_ids)),
        "unique_query_text_count": len(set(query_texts)),
        "query_text_uniqueness_enforced": True,
        "per_source_query_text_uniqueness_enforced": True,
        "global_query_text_uniqueness_enforced": True,
        "calls": {
            "rag": rag_calls,
            "matched_llm_only": llm_only_calls,
            "total": total_calls,
        },
        "formal_cell_reference": formal_cell_reference(pairs_per_source),
        "token_budget": {
            "max_output_tokens_per_call": max_output_tokens,
            "hard_output_token_cap_total": total_calls * max_output_tokens,
            "input_tokens": "unavailable_until_retrieval_prompts_are_materialized",
        },
        "pricing": {
            "status": "configured" if pricing_available else "unavailable",
            "input_usd_per_million_tokens": args.input_price_usd_per_million_tokens,
            "output_usd_per_million_tokens": args.output_price_usd_per_million_tokens,
            "output_only_hard_cap_usd": output_only_hard_cap_usd,
            "total_cost_formula": (
                "(rag_input_tokens + llm_only_input_tokens) * input_price / 1e6 "
                "+ output_tokens * output_price / 1e6"
            ),
            "unavailable_reason": (
                None
                if pricing_available
                else "The Qwen3.5-397B endpoint/provider token prices are not frozen."
            ),
        },
        "selected_source_keys": selected_source_keys,
        "input_queries_path": str(queries_path),
        "input_queries_hash": sha256_file(queries_path),
        "queries_path": str(output_queries),
        "queries_hash": sha256_file(output_queries),
        "selected_query_ids_hash": sha256_obj(sorted(query_ids)),
        "group_query_counts": dict(Counter(str(row["group"]) for row in selected_rows)),
        "api_calls_made": 0,
    }
    write_json(budget, output_dir / "budget.json")
    print(json.dumps({key: value for key, value in budget.items() if key != "selected_source_keys"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
