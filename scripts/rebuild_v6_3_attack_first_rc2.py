"""Rebuild v6.3 candidates with the bounded attack-first RC2 protocol.

The expensive original-entity extraction is intentionally reused.  Those
facts have already passed the frozen v6.3 semantic resolver.  This script only
regenerates deterministic counterfactuals, enforces the local RC2 hard gates
and complete-source absence, rebuilds paired queries, runs the local MiniLM
stealth filter, and retains the first requested eligible sources.

It never calls an API, a retriever, or GLiNER.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.attack.perturbation_generator import (  # noqa: E402
    ATTACK_FIRST_GENERATION_PROTOCOL,
)
from src.paired_claims.claim_generator import (  # noqa: E402
    generate_paired_claims_file,
    load_complete_source_lookup,
)
from src.paired_claims.validator import (  # noqa: E402
    VALIDATOR_VERSION,
    find_entity_spans,
)
from src.query_generation.paired_query_builder import (  # noqa: E402
    generate_paired_queries_file,
)
from src.query_generation.stealth_filter import filter_stealth_queries  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import (  # noqa: E402
    ensure_dir,
    load_yaml,
    read_json,
    read_jsonl,
    resolve_path,
    write_json,
    write_jsonl_atomic,
)


PROTOCOL = "v6_3_attack_first_counterfactual_rc2_rebuild_v1"
DATASETS = ("edgar", "enron", "pubmed")
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "artifacts" / "v6_3" / "attack_first_rc2"
DEFAULT_FACT_INPUTS = {
    "edgar": (
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/precision_cascade_fixed_double_pool/cap_5/edgar/edgar_candidate_facts.jsonl",
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/edgar_rc1_budget6_targeted_cap8/waves/wave_0000_attempt_000/edgar_candidate_facts.jsonl",
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/edgar_rc1_budget6_targeted_cap8/waves/wave_0001_attempt_000/edgar_candidate_facts.jsonl",
    ),
    "enron": (
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/precision_cascade_ranked_expandable_pool/cap_5/enron/enron_candidate_facts.jsonl",
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/precision_cascade_ranked_expandable_pool_rc1/cap_5/enron/waves/wave_0008_attempt_000/enron_candidate_facts.jsonl",
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/precision_cascade_ranked_expandable_pool_rc1/cap_5/enron/waves/wave_0009_attempt_000/enron_candidate_facts.jsonl",
    ),
    "pubmed": (
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/precision_cascade_fixed_double_pool/cap_5/pubmed/pubmed_candidate_facts.jsonl",
    ),
}
DEFAULT_SOURCE_ORDER_INPUTS = {
    "edgar": (
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/precision_cascade_fixed_double_pool/cap_5/edgar/scan_source_order.json",
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/edgar_rc1_budget6_targeted_cap8/targeted_source_order.json",
    ),
    "enron": (
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/precision_cascade_ranked_expandable_pool_rc1/cap_5/enron/scan_source_order.json",
    ),
    "pubmed": (
        PROJECT_ROOT
        / "artifacts/v6_3/eligibility/precision_cascade_fixed_double_pool/cap_5/pubmed/scan_source_order.json",
    ),
}
DEFAULT_CORPORA = {
    dataset: PROJECT_ROOT / "artifacts" / "v6_3" / "processed" / f"{dataset}.jsonl"
    for dataset in DATASETS
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Locally rebuild v6.3 attack-first RC2 claims and retain a fixed "
            "three-pair/six-query source plan."
        )
    )
    parser.add_argument("--dataset", choices=DATASETS, required=True)
    parser.add_argument(
        "--attack-config",
        default="configs/pcv_attack_v6_3.yaml",
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--target-sources", type=int, default=1250)
    parser.add_argument("--pairs-per-source", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _fact_content_key(row: dict[str, Any]) -> tuple[str, ...]:
    span = row.get("claim_entity_span")
    span_text = (
        f"{span[0]}:{span[1]}"
        if isinstance(span, list) and len(span) == 2
        else ""
    )
    return (
        str(row.get("source_key") or row.get("source_id") or ""),
        str(row.get("entity_type") or "").upper(),
        str(row.get("object_entity") or ""),
        str(row.get("factual_claim") or row.get("supporting_sentence") or ""),
        span_text,
    )


def canonicalize_fact_rows(
    rows: Iterable[dict[str, Any]],
    source_order: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deduplicate facts by content and assign collision-free RC2 identities."""

    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    duplicate_count = 0
    for original in rows:
        row = dict(original)
        key = _fact_content_key(row)
        if not key[0]:
            raise RuntimeError("Candidate fact is missing source_key/source_id")
        previous = unique.get(key)
        if previous is not None:
            duplicate_count += 1
            continue
        identity = sha256_obj(key)[:24]
        source_identity = sha256_obj(key[0])[:24]
        row["fact_id"] = f"fact_rc2_{identity}"
        row["audit_id"] = f"attack_first_rc2_{source_identity}"
        row["source_key"] = key[0]
        unique[key] = row

    rank = {source_key: index for index, source_key in enumerate(source_order)}
    missing_from_order = sorted(
        {
            str(row["source_key"])
            for row in unique.values()
            if str(row["source_key"]) not in rank
        }
    )
    next_rank = len(rank)
    for source_key in missing_from_order:
        rank[source_key] = next_rank
        next_rank += 1

    facts = sorted(
        unique.values(),
        key=lambda row: (
            rank[str(row["source_key"])],
            -float(row.get("quality_weight") or 0.0),
            str(row["fact_id"]),
        ),
    )
    return facts, {
        "input_rows": len(facts) + duplicate_count,
        "unique_facts": len(facts),
        "duplicate_facts_removed": duplicate_count,
        "sources_missing_from_frozen_order": len(missing_from_order),
    }


def filter_counterfactual_absence(
    claims: Iterable[dict[str, Any]],
    source_lookup: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Reject counterfactual values already present in their complete source."""

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for original in claims:
        row = dict(original)
        source_key = str(row.get("source_key") or "")
        source_text = source_lookup.get(source_key)
        reason: str | None = None
        if source_text is None:
            reason = "source_text_missing_for_counterfactual_check"
        elif find_entity_spans(
            source_text,
            str(row.get("counterfactual_entity") or ""),
        ):
            reason = "counterfactual_entity_present_in_source"
        if reason is not None:
            row["claim_validation_status"] = "failed"
            row["validation_failure_reason"] = reason
            row["validation_failure_reasons"] = [reason]
            rejected.append(row)
            reasons[reason] += 1
            continue
        row["claim_validation_status"] = "passed"
        row["claim_validator_version"] = VALIDATOR_VERSION
        row["counterfactual_generation_protocol"] = (
            ATTACK_FIRST_GENERATION_PROTOCOL
        )
        row["counterfactual_source_absence_status"] = "passed"
        accepted.append(row)
    return accepted, rejected, dict(sorted(reasons.items()))


def retain_target_sources(
    selected_queries: Iterable[dict[str, Any]],
    claims_by_pair: dict[str, dict[str, Any]],
    facts_by_id: dict[str, dict[str, Any]],
    source_order: list[str],
    *,
    target_sources: int,
    pairs_per_source: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    """Retain the first target eligible sources and verify fixed-budget shape."""

    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected_queries:
        by_source[str(row.get("source_key") or "")].append(dict(row))
    ordered_sources = [key for key in source_order if key in by_source]
    ordered_set = set(ordered_sources)
    ordered_sources.extend(sorted(set(by_source) - ordered_set))
    retained_sources = ordered_sources[:target_sources]
    retained_set = set(retained_sources)

    queries = [
        row
        for source_key in retained_sources
        for row in by_source[source_key]
    ]
    expected_queries = pairs_per_source * 2
    pair_ids: set[str] = set()
    query_ids: set[str] = set()
    for source_key in retained_sources:
        rows = by_source[source_key]
        source_pair_ids = {str(row.get("pair_id") or "") for row in rows}
        source_query_ids = {str(row.get("query_id") or "") for row in rows}
        source_query_texts = {str(row.get("query") or "") for row in rows}
        if (
            len(rows) != expected_queries
            or len(source_pair_ids) != pairs_per_source
            or len(source_query_ids) != expected_queries
            or len(source_query_texts) != expected_queries
        ):
            raise RuntimeError(
                "Attack-first RC2 fixed-budget integrity failure for "
                f"{source_key!r}: rows={len(rows)}, pairs={len(source_pair_ids)}, "
                f"query_ids={len(source_query_ids)}, "
                f"query_texts={len(source_query_texts)}"
            )
        pair_ids.update(source_pair_ids)
        overlap = query_ids & source_query_ids
        if overlap:
            raise RuntimeError(f"Duplicate selected query IDs: {sorted(overlap)[:3]}")
        query_ids.update(source_query_ids)

    claims = [claims_by_pair[pair_id] for pair_id in pair_ids]
    fact_ids = {str(row.get("fact_id") or "") for row in claims}
    facts = [facts_by_id[fact_id] for fact_id in fact_ids]
    claims.sort(
        key=lambda row: (
            retained_sources.index(str(row.get("source_key") or "")),
            str(row.get("pair_id") or ""),
        )
    )
    facts.sort(
        key=lambda row: (
            retained_sources.index(str(row.get("source_key") or "")),
            str(row.get("fact_id") or ""),
        )
    )
    queries.sort(
        key=lambda row: (
            retained_sources.index(str(row.get("source_key") or "")),
            int(row.get("fixed_budget_pair_rank") or 0),
            str(row.get("claim_type") or ""),
        )
    )
    if any(
        str(row.get("source_key") or "") not in retained_set
        for row in (*claims, *facts, *queries)
    ):
        raise RuntimeError("Rows after the retained source boundary leaked into RC2")
    return facts, claims, queries, retained_sources


def _load_source_order(paths: Iterable[Path]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        payload = read_json(path)
        values = (
            payload.get("source_order")
            or payload.get("targeted_source_order")
            or payload.get("source_keys")
            or []
        )
        if not isinstance(values, list):
            raise RuntimeError(f"Invalid source order file: {path}")
        for value in values:
            source_key = str(value)
            if source_key not in seen:
                seen.add(source_key)
                order.append(source_key)
    return order


def _require_files(paths: Iterable[Path]) -> None:
    for path in paths:
        if not path.exists() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Required non-empty artifact is missing: {path}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset = str(args.dataset)
    if args.target_sources < 1 or args.pairs_per_source < 1:
        raise ValueError("target-sources and pairs-per-source must be positive")
    fact_inputs = tuple(DEFAULT_FACT_INPUTS[dataset])
    order_inputs = tuple(DEFAULT_SOURCE_ORDER_INPUTS[dataset])
    corpus_path = DEFAULT_CORPORA[dataset]
    attack_config_path = resolve_path(args.attack_config)
    _require_files((*fact_inputs, *order_inputs, corpus_path, attack_config_path))

    output_dir = ensure_dir(resolve_path(args.output_root) / dataset)
    final_manifest_path = output_dir / f"{dataset}_attack_first_rc2_manifest.json"
    input_identity = {
        "protocol": PROTOCOL,
        "dataset": dataset,
        "target_sources": int(args.target_sources),
        "pairs_per_source": int(args.pairs_per_source),
        "claim_validator_version": VALIDATOR_VERSION,
        "counterfactual_generation_protocol": ATTACK_FIRST_GENERATION_PROTOCOL,
        "fact_inputs": {
            str(path.resolve()): sha256_file(path) for path in fact_inputs
        },
        "source_order_inputs": {
            str(path.resolve()): sha256_file(path) for path in order_inputs
        },
        "source_corpus_sha256": sha256_file(corpus_path),
        "attack_config_sha256": sha256_file(attack_config_path),
    }
    input_identity_sha256 = sha256_obj(input_identity)
    if final_manifest_path.exists() and not args.force:
        existing = read_json(final_manifest_path)
        if (
            existing.get("input_identity_sha256") == input_identity_sha256
            and existing.get("status") == "complete"
        ):
            return {**existing, "skipped_existing": True}
        raise RuntimeError(
            "Existing RC2 output does not match current inputs/protocol; "
            "rerun with --force into the isolated RC2 directory."
        )

    source_order = _load_source_order(order_inputs)
    all_fact_rows = (
        row
        for path in fact_inputs
        for row in read_jsonl(path)
    )
    facts, merge_stats = canonicalize_fact_rows(all_fact_rows, source_order)
    merged_facts_path = output_dir / f"{dataset}_candidate_facts_rc2.jsonl"
    write_jsonl_atomic(facts, merged_facts_path)

    raw_claims_path = output_dir / f"{dataset}_candidate_claims_rc2_raw.jsonl"
    claim_manifest = generate_paired_claims_file(
        merged_facts_path,
        raw_claims_path,
        perturbation_levels=["light"],
        max_pairs_per_fact=1,
        semantic_resolver_config={"enabled": False},
        enforce_original_metadata_semantics=False,
        dataset=dataset,
        resume=not args.force,
        force=args.force,
    )

    fact_sources = {str(row["source_key"]) for row in facts}
    source_lookup = load_complete_source_lookup(
        corpus_path,
        source_key_allowlist=fact_sources,
    )
    claims, absence_rejected, absence_stats = filter_counterfactual_absence(
        read_jsonl(raw_claims_path),
        source_lookup,
    )
    claims_path = output_dir / f"{dataset}_candidate_claims_rc2.jsonl"
    absence_rejected_path = (
        output_dir / f"{dataset}_candidate_claims_rc2_source_rejected.jsonl"
    )
    write_jsonl_atomic(claims, claims_path)
    write_jsonl_atomic(absence_rejected, absence_rejected_path)

    queries_path = output_dir / f"{dataset}_candidate_queries_rc2.jsonl"
    query_manifest = generate_paired_queries_file(
        claims_path,
        queries_path,
        query_types=["compressed_verification"],
        resume=False,
        force=True,
    )

    attack_config = load_yaml(attack_config_path)
    stealth_config = dict(attack_config.get("stealth_filter") or {})
    stealth_path = output_dir / f"{dataset}_candidate_stealth_queries_rc2.jsonl"
    stealth_rejected_path = (
        output_dir / f"{dataset}_candidate_stealth_queries_rc2_rejected.jsonl"
    )
    stealth_manifest = filter_stealth_queries(
        queries_path,
        stealth_path,
        rejected_path=stealth_rejected_path,
        embedding_model=str(
            stealth_config.get(
                "embedding_model",
                "sentence-transformers/all-MiniLM-L6-v2",
            )
        ),
        embedding_local_files_only=bool(
            stealth_config.get("embedding_local_files_only", True)
        ),
        embedding_batch_size=int(
            stealth_config.get("embedding_batch_size", 64)
        ),
        min_naturalness=float(stealth_config.get("min_naturalness", 0.55)),
        max_context_probe=float(
            stealth_config.get("max_context_probe", 0.5)
        ),
        max_prompt_injection=float(
            stealth_config.get("max_prompt_injection", 0.5)
        ),
        min_similarity=float(stealth_config.get("min_similarity", 0.03)),
        max_similarity=float(stealth_config.get("max_similarity", 0.97)),
        pairs_per_source=int(args.pairs_per_source),
        resume=not args.force,
        force=args.force,
    )

    facts_by_id = {str(row["fact_id"]): row for row in facts}
    claims_by_pair = {str(row["pair_id"]): row for row in claims}
    selected_facts, selected_claims, selected_queries, retained_sources = (
        retain_target_sources(
            read_jsonl(stealth_path),
            claims_by_pair,
            facts_by_id,
            source_order,
            target_sources=int(args.target_sources),
            pairs_per_source=int(args.pairs_per_source),
        )
    )
    status = (
        "complete"
        if len(retained_sources) == int(args.target_sources)
        else "insufficient_capacity"
    )
    selected_facts_path = output_dir / f"{dataset}_selected_facts_rc2.jsonl"
    selected_claims_path = output_dir / f"{dataset}_selected_claims_rc2.jsonl"
    selected_queries_path = output_dir / f"{dataset}_selected_queries_rc2.jsonl"
    retained_sources_path = (
        output_dir / f"{dataset}_eligible_source_keys_rc2.json"
    )
    write_jsonl_atomic(selected_facts, selected_facts_path)
    write_jsonl_atomic(selected_claims, selected_claims_path)
    write_jsonl_atomic(selected_queries, selected_queries_path)
    write_json(retained_sources, retained_sources_path)

    manifest = {
        **input_identity,
        "input_identity_sha256": input_identity_sha256,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "design": {
            "original_entity_gate": "frozen_v6_3_gliner2_large_facts",
            "redundant_claim_stage_metadata_semantic_recheck": False,
            "counterfactual_gate": (
                "deterministic_typed_pool_plus_attack_subtype_plus_source_absence"
            ),
            "model_calls": 0,
            "api_calls": 0,
            "retriever_calls": 0,
        },
        "merge": merge_stats,
        "claim_generation": claim_manifest,
        "source_absence_rejections": absence_stats,
        "query_generation": query_manifest,
        "stealth": stealth_manifest,
        "eligible_sources_before_target_cut": int(
            (stealth_manifest.get("fixed_budget") or {}).get(
                "eligible_sources",
                0,
            )
        ),
        "retained_source_count": len(retained_sources),
        "retained_pair_count": len(selected_claims),
        "retained_query_count": len(selected_queries),
        "retained_boundary_source": (
            retained_sources[-1] if retained_sources else None
        ),
        "outputs": {
            "facts": {
                "path": str(selected_facts_path.resolve()),
                "sha256": sha256_file(selected_facts_path),
            },
            "claims": {
                "path": str(selected_claims_path.resolve()),
                "sha256": sha256_file(selected_claims_path),
            },
            "queries": {
                "path": str(selected_queries_path.resolve()),
                "sha256": sha256_file(selected_queries_path),
            },
            "eligible_sources": {
                "path": str(retained_sources_path.resolve()),
                "sha256": sha256_file(retained_sources_path),
            },
        },
    }
    write_json(manifest, final_manifest_path)
    if status != "complete":
        raise RuntimeError(
            f"{dataset} RC2 capacity is insufficient: "
            f"{len(retained_sources)} < {args.target_sources}. "
            f"Diagnostics were written to {final_manifest_path}."
        )
    return manifest


def main() -> None:
    result = run(parse_args())
    print(
        f"{result['dataset']}: status={result['status']} "
        f"sources={result['retained_source_count']} "
        f"pairs={result['retained_pair_count']} "
        f"queries={result['retained_query_count']}"
    )


if __name__ == "__main__":
    main()
