"""Verify promoted v6.3 three-pair formal artifacts without external calls."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_v19_offline_artifacts import (  # noqa: E402
    _audit_query_manifest,
    _load_splits,
    audit_fixed_queries,
)
from src.paired_claims.validator import VALIDATOR_VERSION  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import read_json, read_jsonl, write_json  # noqa: E402


DATASETS = ("edgar", "enron", "pubmed")
EXPECTED_SOURCES = 1250
PAIRS_PER_SOURCE = 3
QUERIES_PER_SOURCE = 6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify v6.3 budget-6 formal artifacts.",
    )
    parser.add_argument("--artifacts-dir", default="artifacts/v6_3")
    parser.add_argument(
        "--output",
        default=(
            "artifacts/v6_3/audits/"
            "budget6_formal_integrity_report.json"
        ),
    )
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
        _require(key not in result, f"{label} has duplicate {field}: {key}")
        result[key] = row
    return result


def verify_promoted_relations(
    dataset: str,
    facts: Iterable[dict[str, Any]],
    claims: Iterable[dict[str, Any]],
    queries: Iterable[dict[str, Any]],
    *,
    expected_sources: int,
) -> dict[str, Any]:
    """Verify source, fact, claim, and query referential integrity."""

    fact_rows = list(facts)
    claim_rows = list(claims)
    query_rows = list(queries)
    facts_by_id = _unique_index(fact_rows, "fact_id", label="facts")
    claims_by_id = _unique_index(claim_rows, "pair_id", label="claims")
    queries_by_id = _unique_index(query_rows, "query_id", label="queries")
    sources = {str(row.get("source_key") or "") for row in claim_rows}
    _require("" not in sources, f"{dataset}: claim source identity is missing")
    _require(
        len(sources) == expected_sources,
        f"{dataset}: expected {expected_sources} claim sources",
    )
    _require(
        len(claim_rows) == expected_sources * PAIRS_PER_SOURCE,
        f"{dataset}: formal pair count mismatch",
    )
    _require(
        len(query_rows) == expected_sources * QUERIES_PER_SOURCE,
        f"{dataset}: formal query count mismatch",
    )
    _require(
        len(fact_rows) == len(claim_rows),
        f"{dataset}: selected facts/claims are not one-to-one",
    )

    fact_ids = set(facts_by_id)
    claim_fact_ids = {str(row.get("fact_id") or "") for row in claim_rows}
    query_pair_ids = {str(row.get("pair_id") or "") for row in query_rows}
    _require(
        claim_fact_ids == fact_ids,
        f"{dataset}: claim/fact reference set mismatch",
    )
    _require(
        query_pair_ids == set(claims_by_id),
        f"{dataset}: query/claim reference set mismatch",
    )
    _require(
        all(
            row.get("claim_validator_version") == VALIDATOR_VERSION
            for row in claim_rows + query_rows
        ),
        f"{dataset}: validator identity drift",
    )
    _require(
        all(row.get("promotion_protocol") for row in fact_rows + claim_rows + query_rows),
        f"{dataset}: missing formal promotion provenance",
    )
    for row in claim_rows:
        fact = facts_by_id[str(row["fact_id"])]
        _require(
            str(row.get("source_key")) == str(fact.get("source_key"))
            and str(row.get("group")) == str(fact.get("group")),
            f"{dataset}: claim/fact source or group drift",
        )
    for row in query_rows:
        claim = claims_by_id[str(row["pair_id"])]
        _require(
            str(row.get("source_key")) == str(claim.get("source_key"))
            and str(row.get("group")) == str(claim.get("group")),
            f"{dataset}: query/claim source or group drift",
        )

    return {
        "source_count": len(sources),
        "fact_count": len(facts_by_id),
        "pair_count": len(claims_by_id),
        "query_count": len(queries_by_id),
        "groups": dict(Counter(str(row.get("group")) for row in claim_rows)),
        "fixed_budget_plan_hash": sha256_obj(
            sorted(
                f"{row['source_key']}::{row['pair_id']}"
                for row in claim_rows
            )
        ),
    }


def _assert_output_hash(
    manifest: dict[str, Any],
    path: Path,
    *,
    label: str,
) -> None:
    _require(
        sha256_file(path) == str(manifest.get("output_hash") or ""),
        f"{label} output hash drift",
    )


def _verify_dataset(dataset: str, artifacts_dir: Path) -> dict[str, Any]:
    sources_by_group, split_meta = _load_splits(dataset, artifacts_dir)
    split_sources = set().union(*sources_by_group.values())
    _require(
        len(split_sources) == EXPECTED_SOURCES,
        f"{dataset}: split source count mismatch",
    )

    benchmark_path = (
        artifacts_dir / "benchmarks" / f"{dataset}_attack_benchmark.jsonl"
    )
    benchmark_manifest_path = (
        artifacts_dir / "benchmarks" / f"{dataset}_benchmark_manifest.json"
    )
    benchmark_manifest = read_json(benchmark_manifest_path)
    _require(
        sha256_file(benchmark_path) == benchmark_manifest.get("benchmark_hash"),
        f"{dataset}: benchmark hash drift",
    )
    benchmark_rows = list(read_jsonl(benchmark_path))
    benchmark_sources = {
        str(row.get("source_key") or "") for row in benchmark_rows
    }
    _require(
        benchmark_sources == split_sources,
        f"{dataset}: benchmark/split source set mismatch",
    )
    _require(
        set(str(row.get("group")) for row in benchmark_rows)
        <= {"KB_Member", "True_Non_Member", "Reserve"},
        f"{dataset}: benchmark contains a forbidden group",
    )

    facts_path = artifacts_dir / "facts" / f"{dataset}_facts.jsonl"
    claims_path = (
        artifacts_dir / "paired_claims" / f"{dataset}_paired_claims.jsonl"
    )
    queries_path = (
        artifacts_dir / "paired_queries" / f"{dataset}_paired_queries.jsonl"
    )
    stealth_path = (
        artifacts_dir
        / "stealth_filtered_queries"
        / f"{dataset}_paired_queries.jsonl"
    )
    facts_manifest = read_json(
        artifacts_dir / "facts" / f"{dataset}_facts.manifest.json"
    )
    claims_manifest = read_json(
        artifacts_dir
        / "paired_claims"
        / f"{dataset}_paired_claims.manifest.json"
    )
    queries_manifest = read_json(
        artifacts_dir
        / "paired_queries"
        / f"{dataset}_paired_queries.manifest.json"
    )
    stealth_manifest = read_json(
        artifacts_dir
        / "stealth_filtered_queries"
        / f"{dataset}_paired_queries.manifest.json"
    )
    _assert_output_hash(facts_manifest, facts_path, label=f"{dataset} facts")
    _assert_output_hash(claims_manifest, claims_path, label=f"{dataset} claims")
    _assert_output_hash(queries_manifest, queries_path, label=f"{dataset} queries")
    _assert_output_hash(stealth_manifest, stealth_path, label=f"{dataset} stealth")
    _require(
        sha256_file(queries_path) == sha256_file(stealth_path),
        f"{dataset}: promoted query/stealth files differ",
    )
    for path in (
        artifacts_dir / "facts" / f"{dataset}_facts.errors.jsonl",
        artifacts_dir
        / "paired_claims"
        / f"{dataset}_paired_claims.errors.jsonl",
        artifacts_dir
        / "paired_queries"
        / f"{dataset}_paired_queries.errors.jsonl",
        artifacts_dir
        / "stealth_filtered_queries"
        / f"{dataset}_paired_queries_rejected.jsonl",
    ):
        _require(path.is_file() and path.stat().st_size == 0, f"Non-empty failure artifact: {path}")

    facts = list(read_jsonl(facts_path))
    claims = list(read_jsonl(claims_path))
    queries = list(read_jsonl(stealth_path))
    relation_report = verify_promoted_relations(
        dataset,
        facts,
        claims,
        queries,
        expected_sources=EXPECTED_SOURCES,
    )
    _require(
        {str(row.get("source_key") or "") for row in claims}
        == split_sources,
        f"{dataset}: promoted source set differs from split",
    )
    query_report = audit_fixed_queries(
        dataset,
        queries,
        sources_by_group,
    )
    query_report.update(_audit_query_manifest(dataset, artifacts_dir))
    _require(
        relation_report["fixed_budget_plan_hash"]
        == query_report["fixed_budget_plan_hash"]
        == claims_manifest.get("formal_fixed_budget_plan_hash"),
        f"{dataset}: formal fixed-budget hash drift",
    )
    eligibility_path = Path(
        str(claims_manifest.get("query_eligibility_path") or "")
    )
    _require(
        eligibility_path.is_file()
        and sha256_file(eligibility_path)
        == claims_manifest.get("query_eligibility_hash"),
        f"{dataset}: release eligibility provenance drift",
    )
    return {
        "split_source_counts": split_meta["source_counts"],
        "split_row_counts": split_meta["row_counts"],
        "benchmark_rows": len(benchmark_rows),
        "benchmark_hash": benchmark_manifest["benchmark_hash"],
        "relations": relation_report,
        "queries": query_report,
        "claims_hash": sha256_file(claims_path),
        "queries_hash": sha256_file(stealth_path),
        "release_eligibility_hash": sha256_file(eligibility_path),
    }


def verify(artifacts_dir: Path) -> dict[str, Any]:
    return {
        "status": "passed",
        "protocol": "v6_3_budget6_formal_integrity_v1",
        "api_calls_performed": 0,
        "retriever_runs": 0,
        "datasets": {
            dataset: _verify_dataset(dataset, artifacts_dir)
            for dataset in DATASETS
        },
    }


def main() -> int:
    args = parse_args()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    report = verify(artifacts_dir)
    if args.output:
        output = Path(args.output).resolve()
        write_json(report, output)
        print(f"[saved] {output}")
    print(
        {
            dataset: {
                "sources": data["relations"]["source_count"],
                "pairs": data["relations"]["pair_count"],
                "queries": data["relations"]["query_count"],
                "benchmark_rows": data["benchmark_rows"],
            }
            for dataset, data in report["datasets"].items()
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
