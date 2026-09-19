"""Package frozen v6.3 three-pair plans for formal promotion.

This local-only step normalizes the completed Edgar, Enron, and PubMed RC1
artifacts into the file layout consumed by ``promote_eligibility_plan.py``.
It does not run a model, embedding backend, retriever, or API.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.attack.entity_extractor import EXTRACTOR_VERSION  # noqa: E402
from src.attack.semantic_entity_resolver import (  # noqa: E402
    SEMANTIC_RESOLVER_PROTOCOL,
    SEMANTIC_SCHEMA_SHA256,
)
from src.paired_claims.validator import (  # noqa: E402
    VALIDATOR_VERSION,
    validate_query_pair,
)
from src.prepare.eligibility_scan import (  # noqa: E402
    ATTACK_FIRST_RC2_RELEASE_CLAIM_ELIGIBILITY_PROTOCOL,
    ATTACK_FIRST_RC2_RELEASE_QUERY_ELIGIBILITY_PROTOCOL,
    ATTACK_FIRST_RC2_RELEASE_SCAN_PROTOCOL,
    BUDGET6_RELEASE_CLAIM_ELIGIBILITY_PROTOCOL,
    BUDGET6_RELEASE_QUERY_ELIGIBILITY_PROTOCOL,
    BUDGET6_RELEASE_SCAN_PROTOCOL,
)
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import (  # noqa: E402
    ensure_dir,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl_atomic,
)


RC1_RELEASE_INPUT_PROTOCOL = "v6_3_rc1_budget6_release_input_v1"
ATTACK_FIRST_RC2_RELEASE_INPUT_PROTOCOL = (
    "v6_3_attack_first_rc2_budget6_release_input_v1"
)
RELEASE_INPUT_PROTOCOL = RC1_RELEASE_INPUT_PROTOCOL
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "artifacts" / "v6_3" / "budget6_release_inputs"
)
DEFAULT_ATTACK_FIRST_RC2_OUTPUT_ROOT = (
    PROJECT_ROOT
    / "artifacts"
    / "v6_3"
    / "budget6_release_inputs_attack_first_rc2"
)
DATASETS = ("edgar", "enron", "pubmed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package local v6.3 three-pair plans for formal promotion.",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=DATASETS,
        default=list(DATASETS),
    )
    parser.add_argument(
        "--input-mode",
        choices=("attack_first_rc2", "rc1"),
        default="attack_first_rc2",
    )
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def validate_selected_plan(
    claims: Iterable[dict[str, Any]],
    queries: Iterable[dict[str, Any]],
    *,
    dataset: str,
) -> dict[str, Any]:
    """Validate the exact three-pair/six-query release plan."""

    claim_rows = list(claims)
    query_rows = list(queries)
    claims_by_pair: dict[str, dict[str, Any]] = {}
    pairs_by_source: dict[str, set[str]] = defaultdict(set)
    fact_ids: set[str] = set()
    for row in claim_rows:
        pair_id = str(row.get("pair_id") or "")
        fact_id = str(row.get("fact_id") or "")
        source_key = str(row.get("source_key") or "")
        _require(pair_id and fact_id and source_key, "Claim identity is incomplete")
        _require(
            pair_id not in claims_by_pair,
            f"Duplicate selected pair_id: {pair_id}",
        )
        _require(
            row.get("dataset") == dataset,
            f"Claim dataset drift: {pair_id}",
        )
        _require(
            row.get("group") == "Eligibility_Candidate",
            f"Claim group label leakage: {pair_id}",
        )
        _require(
            row.get("claim_validator_version") == VALIDATOR_VERSION,
            f"Claim validator identity drift: {pair_id}",
        )
        _require(
            fact_id not in fact_ids,
            f"Selected facts are not one-to-one with pairs: {fact_id}",
        )
        claims_by_pair[pair_id] = row
        pairs_by_source[source_key].add(pair_id)
        fact_ids.add(fact_id)

    queries_by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    query_ids: set[str] = set()
    query_texts_by_source: dict[str, set[str]] = defaultdict(set)
    for row in query_rows:
        query_id = str(row.get("query_id") or "")
        pair_id = str(row.get("pair_id") or "")
        source_key = str(row.get("source_key") or "")
        query = str(row.get("query") or "").strip()
        _require(
            query_id and pair_id and source_key and query,
            "Query identity/text is incomplete",
        )
        _require(query_id not in query_ids, f"Duplicate query_id: {query_id}")
        _require(
            pair_id in claims_by_pair,
            f"Query references missing selected claim: {pair_id}",
        )
        _require(
            source_key == str(claims_by_pair[pair_id].get("source_key")),
            f"Query source drift: {query_id}",
        )
        _require(
            row.get("dataset") == dataset,
            f"Query dataset drift: {query_id}",
        )
        _require(
            row.get("group") == "Eligibility_Candidate",
            f"Query group label leakage: {query_id}",
        )
        _require(row.get("accepted") is True, f"Rejected query selected: {query_id}")
        _require(
            row.get("claim_validator_version") == VALIDATOR_VERSION,
            f"Query validator identity drift: {query_id}",
        )
        _require(
            query not in query_texts_by_source[source_key],
            f"Duplicate query text within source: {source_key}",
        )
        query_ids.add(query_id)
        query_texts_by_source[source_key].add(query)
        queries_by_pair[pair_id].append(row)

    _require(
        set(queries_by_pair) == set(claims_by_pair),
        "Selected claim/query pair sets differ",
    )
    for source_key, pair_ids in pairs_by_source.items():
        _require(
            len(pair_ids) == 3,
            f"{source_key}: expected three selected pairs, found {len(pair_ids)}",
        )
        _require(
            len(query_texts_by_source[source_key]) == 6,
            f"{source_key}: expected six unique queries",
        )
    for pair_id, rows in queries_by_pair.items():
        _require(len(rows) == 2, f"{pair_id}: expected two query variants")
        by_type = {str(row.get("claim_type") or ""): row for row in rows}
        _require(
            set(by_type) == {"true", "counterfactual"},
            f"{pair_id}: missing Q+/Q- variant",
        )
        claim = claims_by_pair[pair_id]
        validation = validate_query_pair(
            str(by_type["true"].get("query") or ""),
            str(by_type["counterfactual"].get("query") or ""),
            str(claim.get("original_entity") or ""),
            str(claim.get("counterfactual_entity") or ""),
        )
        _require(
            validation.valid,
            f"{pair_id}: Q+/Q- validation failed: {validation.reasons}",
        )

    sources = set(pairs_by_source)
    _require(bool(sources), f"{dataset}: selected plan is empty")
    return {
        "source_keys": sorted(sources),
        "source_count": len(sources),
        "pair_count": len(claim_rows),
        "query_count": len(query_rows),
        "fact_ids": fact_ids,
        "fixed_budget_plan_hash": sha256_obj(
            sorted(
                f"{row['source_key']}::{row['pair_id']}"
                for row in claim_rows
            )
        ),
    }


def collect_selected_facts(
    fact_paths: Iterable[Path],
    required_fact_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect every required fact once and bind its source-file hash."""

    found: dict[str, dict[str, Any]] = {}
    provenance: list[dict[str, Any]] = []
    for path in fact_paths:
        _require(path.is_file(), f"Candidate facts file is missing: {path}")
        provenance.append(
            {
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }
        )
        for row in read_jsonl(path):
            fact_id = str(row.get("fact_id") or "")
            if fact_id not in required_fact_ids:
                continue
            previous = found.get(fact_id)
            if previous is not None:
                _require(
                    sha256_obj(previous) == sha256_obj(row),
                    f"Conflicting duplicate candidate fact: {fact_id}",
                )
                continue
            found[fact_id] = row
    missing = sorted(required_fact_ids - set(found))
    _require(not missing, f"Missing selected candidate facts: {missing[:3]}")
    return [found[fact_id] for fact_id in sorted(found)], provenance


def _source_spec(
    dataset: str,
    input_mode: str = "rc1",
) -> dict[str, Any]:
    if input_mode == "attack_first_rc2":
        selected_dir = (
            PROJECT_ROOT
            / "artifacts"
            / "v6_3"
            / "attack_first_rc2"
            / dataset
        )
        return {
            "selected_dir": selected_dir,
            "claims": selected_dir / f"{dataset}_selected_claims_rc2.jsonl",
            "queries": selected_dir / f"{dataset}_selected_queries_rc2.jsonl",
            "whitelist": selected_dir
            / f"{dataset}_eligible_source_keys_rc2.json",
            "whitelist_is_list": True,
            "fact_paths": [
                selected_dir / f"{dataset}_selected_facts_rc2.jsonl"
            ],
            "upstream_paths": [
                selected_dir
                / f"{dataset}_attack_first_rc2_manifest.json",
            ],
        }
    if input_mode != "rc1":
        raise ValueError(f"Unsupported release input mode: {input_mode}")
    if dataset == "edgar":
        selected_dir = (
            PROJECT_ROOT
            / "artifacts"
            / "v6_3"
            / "eligibility"
            / "edgar_rc1_budget6_targeted_cap8"
        )
        checkpoint_path = selected_dir / "targeted_checkpoint.json"
        checkpoint = read_json(checkpoint_path)
        fact_paths = [
            PROJECT_ROOT
            / "artifacts"
            / "v6_3"
            / "eligibility"
            / "precision_cascade_fixed_double_pool"
            / "cap_5"
            / "edgar"
            / "edgar_candidate_facts.jsonl"
        ]
        upstream_paths = [
            selected_dir / "edgar_budget6_targeted_cap8_manifest.json",
            checkpoint_path,
        ]
        for record in checkpoint.get("completed_waves", []):
            manifest_path = Path(str(record["manifest_path"]))
            manifest = read_json(manifest_path)
            fact_paths.append(Path(str(manifest["outputs"]["facts"]["path"])))
            upstream_paths.append(manifest_path)
        return {
            "selected_dir": selected_dir,
            "claims": selected_dir / "edgar_selected_claims_rc1.jsonl",
            "queries": selected_dir / "edgar_selected_queries_rc1.jsonl",
            "whitelist": selected_dir / "edgar_query_eligible_sources_rc1.json",
            "fact_paths": fact_paths,
            "upstream_paths": upstream_paths,
        }
    if dataset == "enron":
        selected_dir = (
            PROJECT_ROOT
            / "artifacts"
            / "v6_3"
            / "rc1_budget6_revalidation"
            / "enron"
        )
        checkpoint_path = (
            PROJECT_ROOT
            / "artifacts"
            / "v6_3"
            / "eligibility"
            / "precision_cascade_ranked_expandable_pool_rc1"
            / "cap_5"
            / "enron"
            / "checkpoints"
            / "checkpoint_0010.json"
        )
        checkpoint = read_json(checkpoint_path)
        fact_paths: list[Path] = []
        upstream_paths = [
            selected_dir / "enron_rc1_revalidation_manifest.json",
            checkpoint_path,
        ]
        for record in checkpoint.get("completed_waves", []):
            manifest_path = Path(str(record["wave_manifest_path"]))
            manifest = read_json(manifest_path)
            fact_path = Path(str(manifest["outputs"]["facts"]["path"]))
            _require(
                sha256_file(fact_path)
                == str(manifest["outputs"]["facts"]["sha256"]),
                f"Enron wave facts hash drift: {fact_path}",
            )
            fact_paths.append(fact_path)
            upstream_paths.append(manifest_path)
        return {
            "selected_dir": selected_dir,
            "claims": selected_dir / "enron_selected_claims_rc1.jsonl",
            "queries": selected_dir / "enron_selected_queries_rc1.jsonl",
            "whitelist": selected_dir / "enron_query_eligible_sources_rc1.json",
            "fact_paths": fact_paths,
            "upstream_paths": upstream_paths,
        }
    if dataset == "pubmed":
        selected_dir = (
            PROJECT_ROOT
            / "artifacts"
            / "v6_3"
            / "rc1_budget6_revalidation"
            / "pubmed"
        )
        fact_path = (
            PROJECT_ROOT
            / "artifacts"
            / "v6_3"
            / "eligibility"
            / "precision_cascade_fixed_double_pool"
            / "cap_5"
            / "pubmed"
            / "pubmed_candidate_facts.jsonl"
        )
        return {
            "selected_dir": selected_dir,
            "claims": selected_dir / "pubmed_selected_claims_rc1.jsonl",
            "queries": selected_dir / "pubmed_selected_queries_rc1.jsonl",
            "whitelist": selected_dir / "pubmed_query_eligible_sources_rc1.json",
            "fact_paths": [fact_path],
            "upstream_paths": [
                selected_dir / "pubmed_rc1_revalidation_manifest.json",
                fact_path.parent / "pubmed_finalization_manifest.json",
            ],
        }
    raise ValueError(f"Unsupported dataset: {dataset}")


def _output_paths(output_dir: Path, dataset: str) -> dict[str, Path]:
    return {
        "facts": output_dir / f"{dataset}_candidate_facts.jsonl",
        "claims": output_dir / f"{dataset}_candidate_claims.jsonl",
        "queries": output_dir / f"{dataset}_candidate_queries.jsonl",
        "stealth": output_dir / f"{dataset}_candidate_stealth_queries.jsonl",
        "stealth_manifest": output_dir
        / f"{dataset}_candidate_stealth_queries.manifest.json",
        "claim_eligibility": output_dir
        / f"{dataset}_claim_eligible_sources.json",
        "query_eligibility": output_dir
        / f"{dataset}_query_eligible_sources.json",
        "checkpoint": output_dir
        / f"{dataset}_budget6_release_checkpoint.json",
        "finalization": output_dir / f"{dataset}_finalization_manifest.json",
        "release_manifest": output_dir
        / f"{dataset}_budget6_release_input_manifest.json",
    }


def build_release_input(
    dataset: str,
    output_root: Path,
    *,
    input_mode: str = "rc1",
    force: bool,
) -> dict[str, Any]:
    """Build one promotion-compatible release directory."""

    spec = _source_spec(dataset, input_mode)
    release_input_protocol = (
        ATTACK_FIRST_RC2_RELEASE_INPUT_PROTOCOL
        if input_mode == "attack_first_rc2"
        else RC1_RELEASE_INPUT_PROTOCOL
    )
    scan_protocol = (
        ATTACK_FIRST_RC2_RELEASE_SCAN_PROTOCOL
        if input_mode == "attack_first_rc2"
        else BUDGET6_RELEASE_SCAN_PROTOCOL
    )
    claim_eligibility_protocol = (
        ATTACK_FIRST_RC2_RELEASE_CLAIM_ELIGIBILITY_PROTOCOL
        if input_mode == "attack_first_rc2"
        else BUDGET6_RELEASE_CLAIM_ELIGIBILITY_PROTOCOL
    )
    query_eligibility_protocol = (
        ATTACK_FIRST_RC2_RELEASE_QUERY_ELIGIBILITY_PROTOCOL
        if input_mode == "attack_first_rc2"
        else BUDGET6_RELEASE_QUERY_ELIGIBILITY_PROTOCOL
    )
    output_dir = output_root / dataset
    paths = _output_paths(output_dir, dataset)
    existing = [path for path in paths.values() if path.exists()]
    if existing and not force:
        raise FileExistsError(
            f"{dataset} release input already exists; use --force"
        )
    ensure_dir(output_dir)

    claims_path = Path(spec["claims"])
    queries_path = Path(spec["queries"])
    whitelist_path = Path(spec["whitelist"])
    for path in (claims_path, queries_path, whitelist_path):
        _require(path.is_file(), f"Selected input is missing: {path}")
    claims = list(read_jsonl(claims_path))
    queries = list(read_jsonl(queries_path))
    plan = validate_selected_plan(claims, queries, dataset=dataset)

    upstream_whitelist = read_json(whitelist_path)
    if spec.get("whitelist_is_list"):
        _require(
            isinstance(upstream_whitelist, list),
            f"{dataset}: RC2 whitelist must be a JSON list",
        )
        upstream_sources = sorted(str(value) for value in upstream_whitelist)
        upstream_whitelist_hash = sha256_obj(upstream_sources)
        upstream_pairs_per_source = 3
        upstream_queries_per_source = 6
    else:
        _require(
            isinstance(upstream_whitelist, dict),
            f"{dataset}: RC1 whitelist must be a JSON object",
        )
        upstream_sources = sorted(
            str(value)
            for value in upstream_whitelist.get("eligible_source_keys", [])
        )
        upstream_whitelist_hash = str(
            upstream_whitelist.get("whitelist_hash") or ""
        )
        upstream_pairs_per_source = int(
            upstream_whitelist.get("pairs_per_source", 0)
        )
        upstream_queries_per_source = int(
            upstream_whitelist.get("queries_per_source", 0)
        )
    _require(
        upstream_sources == plan["source_keys"],
        f"{dataset}: selected rows/whitelist source sets differ",
    )
    _require(
        sha256_obj(upstream_sources) == upstream_whitelist_hash,
        f"{dataset}: upstream whitelist hash drift",
    )
    _require(
        upstream_pairs_per_source == 3
        and upstream_queries_per_source == 6,
        f"{dataset}: upstream fixed budget is not 3/6",
    )
    _require(
        int(plan["source_count"]) >= 1250,
        f"{dataset}: fewer than 1,250 release sources",
    )

    facts, fact_provenance = collect_selected_facts(
        list(spec["fact_paths"]),
        set(plan["fact_ids"]),
    )
    _require(
        all(row.get("dataset") == dataset for row in facts),
        f"{dataset}: candidate fact dataset drift",
    )
    _require(
        all(row.get("group") == "Eligibility_Candidate" for row in facts),
        f"{dataset}: candidate fact group label leakage",
    )

    claims.sort(key=lambda row: str(row["pair_id"]))
    queries.sort(
        key=lambda row: (
            str(row["source_key"]),
            int(row.get("fixed_budget_pair_rank") or 0),
            str(row.get("claim_type") or ""),
            str(row["query_id"]),
        )
    )
    write_jsonl_atomic(facts, paths["facts"])
    write_jsonl_atomic(claims, paths["claims"])
    write_jsonl_atomic(queries, paths["queries"])
    write_jsonl_atomic(queries, paths["stealth"])

    upstream_provenance = []
    for path in [
        claims_path,
        queries_path,
        whitelist_path,
        *list(spec["upstream_paths"]),
    ]:
        path = Path(path)
        _require(path.is_file(), f"Upstream provenance file is missing: {path}")
        upstream_provenance.append(
            {
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }
        )
    candidate_hashes = {
        "facts": sha256_file(paths["facts"]),
        "claims": sha256_file(paths["claims"]),
        "queries": sha256_file(paths["queries"]),
        "stealth": sha256_file(paths["stealth"]),
    }
    scan_plan_sha256 = sha256_obj(
        {
            "protocol": release_input_protocol,
            "dataset": dataset,
            "source_keys": plan["source_keys"],
            "fixed_budget_plan_hash": plan["fixed_budget_plan_hash"],
            "candidate_hashes": candidate_hashes,
            "upstream_provenance": upstream_provenance,
            "fact_provenance": fact_provenance,
        }
    )
    checkpoint = {
        "protocol": release_input_protocol,
        "scan_protocol": scan_protocol,
        "dataset": dataset,
        "status": "complete",
        "scan_plan_sha256": scan_plan_sha256,
        "source_count": plan["source_count"],
        "pair_count": plan["pair_count"],
        "query_count": plan["query_count"],
        "pairs_per_source": 3,
        "queries_per_source": 6,
        "whitelist_hash": sha256_obj(plan["source_keys"]),
        "fixed_budget_plan_hash": plan["fixed_budget_plan_hash"],
        "candidate_hashes": candidate_hashes,
        "upstream_provenance": upstream_provenance,
        "fact_provenance": fact_provenance,
        "gliner_inference_calls": 0,
        "api_calls": 0,
        "retriever_calls": 0,
    }
    write_json(checkpoint, paths["checkpoint"])
    checkpoint_hash = sha256_file(paths["checkpoint"])

    common = {
        "dataset": dataset,
        "scan_protocol": scan_protocol,
        "scan_plan_sha256": scan_plan_sha256,
        "scan_checkpoint_path": str(paths["checkpoint"].resolve()),
        "scan_checkpoint_sha256": checkpoint_hash,
        "claim_validator_version": VALIDATOR_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "semantic_resolver_protocol": SEMANTIC_RESOLVER_PROTOCOL,
        "semantic_schema_sha256": SEMANTIC_SCHEMA_SHA256,
        "source_count": plan["source_count"],
        "pairs_per_source": 3,
        "queries_per_source": 6,
        "gliner_inference_calls": 0,
        "api_calls": 0,
        "retriever_calls": 0,
    }
    write_json(
        {
            **common,
            "protocol": claim_eligibility_protocol,
            "candidate_facts_hash": candidate_hashes["facts"],
            "candidate_claims_hash": candidate_hashes["claims"],
            "eligible_source_keys": plan["source_keys"],
            "eligible_source_count": plan["source_count"],
            "whitelist_hash": sha256_obj(plan["source_keys"]),
            "minimum_valid_claims": 3,
            "capacity_status": "passed",
        },
        paths["claim_eligibility"],
    )
    write_json(
        {
            "dataset": dataset,
            "protocol": release_input_protocol,
            "accepted": plan["query_count"],
            "rejected": 0,
            "accepted_pairs": plan["pair_count"],
            "rejected_pairs": 0,
            "stealth_detection_rate": 0.0,
            "pair_rejection_rate": 0.0,
            "fixed_budget": {
                "enabled": True,
                "pairs_per_source": 3,
                "queries_per_source": 6,
                "eligible_sources": plan["source_count"],
                "insufficient_sources": {},
                "selected_pairs": plan["pair_count"],
                "query_text_uniqueness_enforced": True,
                "duplicate_query_text_pairs": 0,
                "fixed_budget_plan_hash": plan["fixed_budget_plan_hash"],
            },
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "embedding_local_files_only": True,
            "output_path": str(paths["stealth"].resolve()),
            "output_hash": candidate_hashes["stealth"],
        },
        paths["stealth_manifest"],
    )
    query_eligibility = {
        **common,
        "protocol": query_eligibility_protocol,
        "capacity_status": "passed",
        "stop_status": "target_reached",
        "deduplicate_complete_sources": True,
        "scan_full_candidate_pool": True,
        "scanned_source_count": plan["source_count"],
        "effective_candidate_pool_source_count": plan["source_count"],
        "eligible_source_keys": plan["source_keys"],
        "eligible_source_count": plan["source_count"],
        "whitelist_hash": sha256_obj(plan["source_keys"]),
        "minimum_valid_claims": 3,
        "minimum_stealth_pairs": 3,
        "query_text_uniqueness_enforced": True,
        "candidate_claims_hash": candidate_hashes["claims"],
        "candidate_queries_hash": candidate_hashes["queries"],
        "candidate_stealth_queries_hash": candidate_hashes["stealth"],
        "fixed_budget_plan_hash": plan["fixed_budget_plan_hash"],
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_local_files_only": True,
    }
    write_json(query_eligibility, paths["query_eligibility"])
    query_eligibility_hash = sha256_file(paths["query_eligibility"])
    finalization = {
        **common,
        "protocol": release_input_protocol,
        "status": "complete",
        "outputs": {
            "query_eligibility": {
                "path": str(paths["query_eligibility"].resolve()),
                "sha256": query_eligibility_hash,
            }
        },
    }
    write_json(finalization, paths["finalization"])
    release_manifest = {
        **common,
        "protocol": release_input_protocol,
        "status": "complete",
        "candidate_hashes": candidate_hashes,
        "claim_eligibility_sha256": sha256_file(paths["claim_eligibility"]),
        "query_eligibility_sha256": query_eligibility_hash,
        "stealth_manifest_sha256": sha256_file(paths["stealth_manifest"]),
        "finalization_sha256": sha256_file(paths["finalization"]),
        "whitelist_hash": sha256_obj(plan["source_keys"]),
        "fixed_budget_plan_hash": plan["fixed_budget_plan_hash"],
        "upstream_provenance": upstream_provenance,
        "fact_provenance": fact_provenance,
    }
    write_json(release_manifest, paths["release_manifest"])
    return release_manifest


def main() -> int:
    args = parse_args()
    default_output_root = (
        DEFAULT_ATTACK_FIRST_RC2_OUTPUT_ROOT
        if args.input_mode == "attack_first_rc2"
        else DEFAULT_OUTPUT_ROOT
    )
    output_root = Path(args.output_root or default_output_root).resolve()
    results = {}
    for dataset in args.datasets:
        result = build_release_input(
            dataset,
            output_root,
            input_mode=str(args.input_mode),
            force=bool(args.force),
        )
        results[dataset] = {
            "sources": result["source_count"],
            "pairs": result["source_count"] * 3,
            "queries": result["source_count"] * 6,
            "whitelist_hash": result["whitelist_hash"],
            "fixed_budget_plan_hash": result["fixed_budget_plan_hash"],
        }
    print(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
