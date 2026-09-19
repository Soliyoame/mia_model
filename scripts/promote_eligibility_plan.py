"""Promote the frozen pre-split v6.3 pair plan into formal artifacts.

The source eligibility stage is label-independent and already fixes the
configured stealth-passed claim-pair budget per eligible source.  Once the
formal split selects 1,250 of those sources, this script joins the frozen
rows to the formal benchmark and replaces only the temporary group/audit
labels.  It does not rerun NER, regenerate counterfactuals, or re-rank pairs.
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

from src.paired_claims.validator import VALIDATOR_VERSION, validate_query_pair  # noqa: E402
from src.prepare.eligibility_scan import (  # noqa: E402
    validate_formal_eligibility_manifest,
)
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import (  # noqa: E402
    ensure_parent,
    load_yaml,
    read_json,
    read_jsonl,
    resolve_path,
    write_json,
    write_jsonl,
)


QUERY_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_query_eligibility_v6_3_precision_cascade_"
    "unique_query_text"
)
PROMOTION_PROTOCOL = "formal_fixed_pair_promotion_v2"
FORMAL_GROUPS = ("KB_Member", "True_Non_Member", "Reserve")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote a frozen v6.3 eligibility pair plan into formal artifacts"
    )
    parser.add_argument("--dataset", choices=["edgar", "enron", "pubmed"], required=True)
    parser.add_argument(
        "--data-config",
        default=str(PROJECT_ROOT / "configs" / "data_config.yaml"),
    )
    parser.add_argument(
        "--attack-config",
        default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"),
    )
    parser.add_argument(
        "--eligibility-path",
        default=None,
        help=(
            "显式覆盖 eligibility manifest；用于 Enron v4，"
            "无需修改共享 data config。"
        ),
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _unique_index(
    rows: Iterable[dict[str, Any]],
    field: str,
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get(field) or "")
        _require(bool(key), f"{label} row is missing {field}")
        _require(key not in result, f"Duplicate {field} in {label}: {key}")
        result[key] = row
    return result


def _benchmark_bindings(
    benchmark_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    by_doc: dict[str, dict[str, str]] = {}
    group_by_source: dict[str, str] = {}
    for row in benchmark_rows:
        doc_id = str(row.get("doc_id") or "")
        source_key = str(row.get("source_key") or "")
        audit_id = str(row.get("audit_id") or "")
        group = str(row.get("group") or "")
        _require(doc_id and source_key and audit_id, "Formal benchmark row lacks binding fields")
        _require(group in FORMAL_GROUPS, f"Unexpected formal benchmark group: {group!r}")
        _require(doc_id not in by_doc, f"Duplicate formal benchmark doc_id: {doc_id}")
        by_doc[doc_id] = {
            "source_key": source_key,
            "audit_id": audit_id,
            "group": group,
        }
        previous_group = group_by_source.setdefault(source_key, group)
        _require(
            previous_group == group,
            f"Formal source crosses groups: {source_key} ({previous_group}/{group})",
        )
    return by_doc, group_by_source


def _relabel_row(
    row: dict[str, Any],
    benchmark_by_doc: dict[str, dict[str, str]],
) -> dict[str, Any]:
    doc_id = str(row.get("doc_id") or "")
    _require(doc_id in benchmark_by_doc, f"Frozen-plan doc_id missing from benchmark: {doc_id}")
    binding = benchmark_by_doc[doc_id]
    source_key = str(row.get("source_key") or "")
    _require(
        source_key == binding["source_key"],
        f"source_key drift for {doc_id}: {source_key!r} != {binding['source_key']!r}",
    )
    promoted = dict(row)
    promoted["audit_id"] = binding["audit_id"]
    promoted["group"] = binding["group"]
    promoted["promotion_protocol"] = PROMOTION_PROTOCOL
    return promoted


def promote_fixed_plan_rows(
    *,
    benchmark_rows: list[dict[str, Any]],
    candidate_facts: list[dict[str, Any]],
    candidate_claims: list[dict[str, Any]],
    candidate_queries: list[dict[str, Any]],
    pairs_per_source: int = 3,
) -> dict[str, Any]:
    """Validate and relabel the exact frozen pair plan for formal sources."""

    _require(pairs_per_source > 0, "pairs_per_source must be positive")
    benchmark_by_doc, group_by_source = _benchmark_bindings(benchmark_rows)
    formal_sources = set(group_by_source)
    _require(bool(formal_sources), "Formal benchmark contains no sources")

    selected_queries = [
        row for row in candidate_queries if str(row.get("source_key") or "") in formal_sources
    ]
    _require(bool(selected_queries), "Frozen query plan has no rows for formal sources")
    _require(
        all(str(row.get("group")) == "Eligibility_Candidate" for row in selected_queries),
        "Frozen query plan must be group-label independent",
    )
    _require(
        all(row.get("accepted") is True for row in selected_queries),
        "Frozen query plan contains a non-accepted row",
    )
    _require(
        all(str(row.get("claim_validator_version")) == VALIDATOR_VERSION for row in selected_queries),
        "Frozen query plan validator version drift",
    )

    query_ids: set[str] = set()
    pair_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pairs_by_source: dict[str, set[str]] = defaultdict(set)
    query_texts_by_source: dict[str, set[str]] = defaultdict(set)
    for row in selected_queries:
        query_id = str(row.get("query_id") or "")
        pair_id = str(row.get("pair_id") or "")
        source_key = str(row.get("source_key") or "")
        query_text = str(row.get("query") or "")
        _require(query_id and pair_id and query_text, "Frozen query row lacks identity/text")
        _require(query_id not in query_ids, f"Duplicate frozen query_id: {query_id}")
        _require(
            query_text not in query_texts_by_source[source_key],
            f"Duplicate frozen query text within source: {source_key}",
        )
        query_ids.add(query_id)
        query_texts_by_source[source_key].add(query_text)
        pair_rows[pair_id].append(row)
        pairs_by_source[source_key].add(pair_id)

    expected_queries = pairs_per_source * 2
    _require(
        set(pairs_by_source) == formal_sources,
        "Formal source set and frozen-plan source set do not match",
    )
    for source_key in sorted(formal_sources):
        _require(
            len(pairs_by_source[source_key]) == pairs_per_source,
            f"{source_key}: expected {pairs_per_source} pairs, "
            f"found {len(pairs_by_source[source_key])}",
        )
        _require(
            len(query_texts_by_source[source_key]) == expected_queries,
            f"{source_key}: expected {expected_queries} unique queries, "
            f"found {len(query_texts_by_source[source_key])}",
        )

    selected_pair_ids = set(pair_rows)
    claims_by_pair = _unique_index(candidate_claims, "pair_id", label="candidate claims")
    _require(
        selected_pair_ids <= set(claims_by_pair),
        "Frozen query plan references a missing candidate claim",
    )
    selected_claims = [claims_by_pair[pair_id] for pair_id in sorted(selected_pair_ids)]
    _require(
        all(str(row.get("claim_validator_version")) == VALIDATOR_VERSION for row in selected_claims),
        "Candidate claim validator version drift",
    )

    for pair_id, rows in pair_rows.items():
        _require(len(rows) == 2, f"{pair_id}: expected Q+/Q- rows, found {len(rows)}")
        by_type = {str(row.get("claim_type")): row for row in rows}
        _require(
            set(by_type) == {"true", "counterfactual"},
            f"{pair_id}: missing true/counterfactual query",
        )
        claim = claims_by_pair[pair_id]
        validation = validate_query_pair(
            str(by_type["true"].get("query") or ""),
            str(by_type["counterfactual"].get("query") or ""),
            str(claim.get("original_entity") or ""),
            str(claim.get("counterfactual_entity") or ""),
        )
        _require(validation.valid, f"{pair_id}: Q+/Q- validation failed: {validation.reasons}")

    selected_fact_ids = {str(row.get("fact_id") or "") for row in selected_claims}
    _require("" not in selected_fact_ids, "Selected claim is missing fact_id")
    facts_by_id = _unique_index(candidate_facts, "fact_id", label="candidate facts")
    _require(
        selected_fact_ids <= set(facts_by_id),
        "Frozen claim plan references a missing candidate fact",
    )
    selected_facts = [facts_by_id[fact_id] for fact_id in sorted(selected_fact_ids)]

    promoted_facts = [_relabel_row(row, benchmark_by_doc) for row in selected_facts]
    promoted_claims = [_relabel_row(row, benchmark_by_doc) for row in selected_claims]
    promoted_queries = [_relabel_row(row, benchmark_by_doc) for row in selected_queries]
    promoted_queries.sort(
        key=lambda row: (
            str(row.get("source_key")),
            int(row.get("fixed_budget_pair_rank") or 0),
            str(row.get("claim_type")),
        )
    )

    group_source_counts = Counter(group_by_source.values())
    group_pair_counts = Counter(str(row.get("group")) for row in promoted_claims)
    group_query_counts = Counter(str(row.get("group")) for row in promoted_queries)
    expected_pair_counts = {
        group: group_source_counts[group] * pairs_per_source
        for group in FORMAL_GROUPS
        if group_source_counts[group]
    }
    expected_query_counts = {
        group: expected_pair_counts[group] * 2 for group in expected_pair_counts
    }
    _require(dict(group_pair_counts) == expected_pair_counts, "Formal pair group counts mismatch")
    _require(dict(group_query_counts) == expected_query_counts, "Formal query group counts mismatch")

    plan_keys = sorted(
        f"{row['source_key']}::{row['pair_id']}" for row in promoted_claims
    )
    return {
        "facts": promoted_facts,
        "claims": promoted_claims,
        "queries": promoted_queries,
        "source_count": len(formal_sources),
        "pair_count": len(promoted_claims),
        "query_count": len(promoted_queries),
        "pairs_per_source": pairs_per_source,
        "queries_per_source": expected_queries,
        "source_counts_by_group": dict(group_source_counts),
        "pair_counts_by_group": dict(group_pair_counts),
        "query_counts_by_group": dict(group_query_counts),
        "fixed_budget_plan_hash": sha256_obj(plan_keys),
    }


def _atomic_write_jsonl(rows: Iterable[dict[str, Any]], path: Path) -> int:
    target = ensure_parent(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    count = write_jsonl(rows, temporary)
    temporary.replace(target)
    return count


def _assert_hash(path: Path, expected: object, label: str) -> None:
    actual = sha256_file(path)
    _require(bool(expected), f"Missing expected {label} hash")
    _require(actual == str(expected), f"{label} hash drift: {actual} != {expected}")


def _output_paths(dataset: str, attack_config: dict[str, Any]) -> dict[str, Path]:
    paths = attack_config["paths"]
    return {
        "benchmark": resolve_path(paths["benchmark_dir"]) / f"{dataset}_attack_benchmark.jsonl",
        "benchmark_manifest": resolve_path(paths["benchmark_dir"])
        / f"{dataset}_benchmark_manifest.json",
        "facts": resolve_path(paths["facts_dir"]) / f"{dataset}_facts.jsonl",
        "facts_errors": resolve_path(paths["facts_dir"]) / f"{dataset}_facts.errors.jsonl",
        "facts_manifest": resolve_path(paths["facts_dir"]) / f"{dataset}_facts.manifest.json",
        "claims": resolve_path(paths["paired_claims_dir"]) / f"{dataset}_paired_claims.jsonl",
        "claims_errors": resolve_path(paths["paired_claims_dir"])
        / f"{dataset}_paired_claims.errors.jsonl",
        "claims_manifest": resolve_path(paths["paired_claims_dir"])
        / f"{dataset}_paired_claims.manifest.json",
        "queries": resolve_path(paths["paired_queries_dir"]) / f"{dataset}_paired_queries.jsonl",
        "queries_errors": resolve_path(paths["paired_queries_dir"])
        / f"{dataset}_paired_queries.errors.jsonl",
        "queries_manifest": resolve_path(paths["paired_queries_dir"])
        / f"{dataset}_paired_queries.manifest.json",
        "stealth": resolve_path(paths["stealth_filtered_queries_dir"])
        / f"{dataset}_paired_queries.jsonl",
        "stealth_rejected": resolve_path(paths["stealth_filtered_queries_dir"])
        / f"{dataset}_paired_queries_rejected.jsonl",
        "stealth_manifest": resolve_path(paths["stealth_filtered_queries_dir"])
        / f"{dataset}_paired_queries.manifest.json",
    }


def main() -> int:
    args = parse_args()
    data_config = load_yaml(args.data_config)
    attack_config = load_yaml(args.attack_config)
    eligibility_path = (
        resolve_path(args.eligibility_path)
        if args.eligibility_path
        else resolve_path(
            data_config["datasets"][args.dataset][
                "source_eligibility_path"
            ]
        )
    )
    eligibility_dir = eligibility_path.parent
    query_eligibility = read_json(eligibility_path)
    _require(query_eligibility.get("dataset") == args.dataset, "Eligibility dataset mismatch")
    _require(
        query_eligibility.get("claim_validator_version") == VALIDATOR_VERSION,
        "Query eligibility validator version mismatch",
    )
    validate_formal_eligibility_manifest(
        query_eligibility,
        dataset=args.dataset,
        required_sources=1250,
    )
    pairs_per_source = int(query_eligibility.get("minimum_stealth_pairs") or 0)
    _require(pairs_per_source == 3, "Formal v6.3 protocol requires exactly three pairs")
    _require(
        query_eligibility.get("query_text_uniqueness_enforced") is True,
        "Eligibility did not enforce query-text uniqueness",
    )
    eligible_keys = sorted(str(value) for value in query_eligibility["eligible_source_keys"])
    _require(
        sha256_obj(eligible_keys) == query_eligibility.get("whitelist_hash"),
        "Eligibility source whitelist hash drift",
    )

    candidate_facts_path = eligibility_dir / f"{args.dataset}_candidate_facts.jsonl"
    candidate_claims_path = eligibility_dir / f"{args.dataset}_candidate_claims.jsonl"
    candidate_queries_path = eligibility_dir / f"{args.dataset}_candidate_queries.jsonl"
    candidate_stealth_path = (
        eligibility_dir / f"{args.dataset}_candidate_stealth_queries.jsonl"
    )
    candidate_stealth_manifest_path = candidate_stealth_path.with_suffix(
        ".manifest.json"
    )
    _assert_hash(
        candidate_claims_path,
        query_eligibility.get("candidate_claims_hash"),
        "candidate claims",
    )
    _assert_hash(
        candidate_queries_path,
        query_eligibility.get("candidate_queries_hash"),
        "candidate queries",
    )
    _assert_hash(
        candidate_stealth_path,
        query_eligibility.get("candidate_stealth_queries_hash"),
        "candidate stealth queries",
    )
    claim_eligibility = read_json(
        eligibility_dir / f"{args.dataset}_claim_eligible_sources.json"
    )
    _assert_hash(
        candidate_facts_path,
        claim_eligibility.get("candidate_facts_hash"),
        "candidate facts",
    )
    candidate_stealth_manifest = read_json(candidate_stealth_manifest_path)
    upstream_fixed = candidate_stealth_manifest.get("fixed_budget") or {}
    _require(
        upstream_fixed.get("fixed_budget_plan_hash")
        == query_eligibility.get("fixed_budget_plan_hash"),
        "Eligibility fixed-budget plan hash drift",
    )
    finalization_manifest_path = (
        eligibility_dir / f"{args.dataset}_finalization_manifest.json"
    )
    finalization_manifest = read_json(finalization_manifest_path)
    _require(
        finalization_manifest.get("scan_plan_sha256")
        == query_eligibility.get("scan_plan_sha256")
        and finalization_manifest.get("scan_checkpoint_sha256")
        == query_eligibility.get("scan_checkpoint_sha256"),
        "Eligibility finalization identity drift",
    )
    finalized_query = (
        finalization_manifest.get("outputs", {}).get(
            "query_eligibility",
            {},
        )
    )
    _assert_hash(
        eligibility_path,
        finalized_query.get("sha256"),
        "finalized query eligibility",
    )

    outputs = _output_paths(args.dataset, attack_config)
    for required in (outputs["benchmark"], outputs["benchmark_manifest"]):
        if not required.exists():
            raise FileNotFoundError(required)
    benchmark_manifest = read_json(outputs["benchmark_manifest"])
    _assert_hash(
        outputs["benchmark"],
        benchmark_manifest.get("benchmark_hash"),
        "formal benchmark",
    )

    writable = [
        path
        for key, path in outputs.items()
        if key not in {"benchmark", "benchmark_manifest"}
    ]
    if not args.force:
        existing = [str(path) for path in writable if path.exists()]
        _require(not existing, f"Formal artifacts already exist; use --force: {existing[:3]}")

    promoted = promote_fixed_plan_rows(
        benchmark_rows=list(read_jsonl(outputs["benchmark"])),
        candidate_facts=list(read_jsonl(candidate_facts_path)),
        candidate_claims=list(read_jsonl(candidate_claims_path)),
        candidate_queries=list(read_jsonl(candidate_stealth_path)),
        pairs_per_source=pairs_per_source,
    )
    expected_sources = sum(
        int((benchmark_manifest.get("source_counts") or {}).get(group, 0))
        for group in FORMAL_GROUPS
    )
    _require(
        promoted["source_count"] == expected_sources == 1250,
        f"Formal source count mismatch: {promoted['source_count']}/{expected_sources}",
    )

    _atomic_write_jsonl(promoted["facts"], outputs["facts"])
    _atomic_write_jsonl([], outputs["facts_errors"])
    _atomic_write_jsonl(promoted["claims"], outputs["claims"])
    _atomic_write_jsonl([], outputs["claims_errors"])
    _atomic_write_jsonl(promoted["queries"], outputs["queries"])
    _atomic_write_jsonl([], outputs["queries_errors"])
    _atomic_write_jsonl(promoted["queries"], outputs["stealth"])
    _atomic_write_jsonl([], outputs["stealth_rejected"])

    created_at = datetime.now(timezone.utc).isoformat()
    common_provenance = {
        "created_at": created_at,
        "promotion_protocol": PROMOTION_PROTOCOL,
        "dataset": args.dataset,
        "benchmark_path": str(outputs["benchmark"].resolve()),
        "benchmark_hash": sha256_file(outputs["benchmark"]),
        "benchmark_manifest_hash": sha256_file(outputs["benchmark_manifest"]),
        "query_eligibility_path": str(eligibility_path.resolve()),
        "query_eligibility_hash": sha256_file(eligibility_path),
        "query_eligibility_protocol": query_eligibility["protocol"],
        "query_eligibility_whitelist_hash": query_eligibility["whitelist_hash"],
        "upstream_fixed_budget_plan_hash": query_eligibility["fixed_budget_plan_hash"],
        "formal_fixed_budget_plan_hash": promoted["fixed_budget_plan_hash"],
        "claim_validator_version": VALIDATOR_VERSION,
        "extractor_version": query_eligibility.get("extractor_version"),
        "source_count": promoted["source_count"],
        "pairs_per_source": promoted["pairs_per_source"],
        "queries_per_source": promoted["queries_per_source"],
        "source_counts_by_group": promoted["source_counts_by_group"],
        "pair_counts_by_group": promoted["pair_counts_by_group"],
        "query_counts_by_group": promoted["query_counts_by_group"],
    }
    fact_entity_counts = Counter(str(row.get("entity_type")) for row in promoted["facts"])
    fact_tier_counts = Counter(str(row.get("selection_tier")) for row in promoted["facts"])
    fact_group_counts = Counter(str(row.get("group")) for row in promoted["facts"])
    claim_entity_counts = Counter(str(row.get("entity_type")) for row in promoted["claims"])
    query_type_counts = Counter(str(row.get("query_type")) for row in promoted["queries"])

    write_json(
        {
            **common_provenance,
            "output_path": str(outputs["facts"].resolve()),
            "error_path": str(outputs["facts_errors"].resolve()),
            "facts": promoted["pair_count"],
            "facts_by_group": dict(fact_group_counts),
            "facts_by_entity_type": dict(fact_entity_counts),
            "facts_by_tier": dict(fact_tier_counts),
            "promotion_scope": "facts_referenced_by_frozen_formal_pair_plan",
            "output_hash": sha256_file(outputs["facts"]),
            "error_hash": sha256_file(outputs["facts_errors"]),
        },
        outputs["facts_manifest"],
    )
    write_json(
        {
            **common_provenance,
            "output_path": str(outputs["claims"].resolve()),
            "error_path": str(outputs["claims_errors"].resolve()),
            "pairs": promoted["pair_count"],
            "errors": 0,
            "pairs_by_group": promoted["pair_counts_by_group"],
            "pairs_by_entity_type": dict(claim_entity_counts),
            "validation_failures_by_reason": {},
            "perturbation_levels": ["light"],
            "max_pairs_per_fact": 1,
            "output_hash": sha256_file(outputs["claims"]),
            "error_hash": sha256_file(outputs["claims_errors"]),
        },
        outputs["claims_manifest"],
    )
    write_json(
        {
            **common_provenance,
            "output_path": str(outputs["queries"].resolve()),
            "error_path": str(outputs["queries_errors"].resolve()),
            "queries": promoted["query_count"],
            "errors": 0,
            "query_types": sorted(query_type_counts),
            "queries_by_type": dict(query_type_counts),
            "validation_failures_by_reason": {},
            "output_hash": sha256_file(outputs["queries"]),
            "error_hash": sha256_file(outputs["queries_errors"]),
        },
        outputs["queries_manifest"],
    )
    write_json(
        {
            **common_provenance,
            "output_path": str(outputs["stealth"].resolve()),
            "rejected_path": str(outputs["stealth_rejected"].resolve()),
            "accepted": promoted["query_count"],
            "rejected": 0,
            "accepted_pairs": promoted["pair_count"],
            "rejected_pairs": 0,
            "stealth_detection_rate": 0.0,
            "pair_rejection_rate": 0.0,
            "fixed_budget": {
                "pairs_per_source": promoted["pairs_per_source"],
                "queries_per_source": promoted["queries_per_source"],
                "eligible_sources": promoted["source_count"],
                "insufficient_sources": {},
                "selected_pairs": promoted["pair_count"],
                "query_text_uniqueness_enforced": True,
                "duplicate_query_text_pairs": 0,
                "fixed_budget_plan_hash": promoted["fixed_budget_plan_hash"],
                "enabled": True,
            },
            "upstream_candidate_filter": {
                "accepted": candidate_stealth_manifest.get("accepted"),
                "rejected": candidate_stealth_manifest.get("rejected"),
                "accepted_pairs": candidate_stealth_manifest.get("accepted_pairs"),
                "rejected_pairs": candidate_stealth_manifest.get("rejected_pairs"),
                "stealth_detection_rate": candidate_stealth_manifest.get(
                    "stealth_detection_rate"
                ),
                "pair_rejection_rate": candidate_stealth_manifest.get(
                    "pair_rejection_rate"
                ),
            },
            "embedding_model": query_eligibility.get("embedding_model"),
            "embedding_local_files_only": query_eligibility.get(
                "embedding_local_files_only"
            ),
            "output_hash": sha256_file(outputs["stealth"]),
            "rejected_hash": sha256_file(outputs["stealth_rejected"]),
        },
        outputs["stealth_manifest"],
    )

    print(
        {
            "dataset": args.dataset,
            "promotion_protocol": PROMOTION_PROTOCOL,
            "sources": promoted["source_count"],
            "pairs": promoted["pair_count"],
            "queries": promoted["query_count"],
            "fixed_budget_plan_hash": promoted["fixed_budget_plan_hash"],
            "benchmark_hash": common_provenance["benchmark_hash"],
            "claims_hash": sha256_file(outputs["claims"]),
            "queries_hash": sha256_file(outputs["stealth"]),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
