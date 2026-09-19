"""Validate the complete v20 offline release state without making API calls."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import load_yaml, read_json, read_jsonl, write_json  # noqa: E402
from src.paired_claims.validator import validate_query_pair  # noqa: E402
from src.query_generation.diverse_slot_questions import (  # noqa: E402
    PROTOCOL_VERSION as DIVERSE_QUERY_PROTOCOL,
    QUERY_TYPE as DIVERSE_QUERY_TYPE,
)


DATASETS = ("edgar", "enron", "pubmed")
GROUP_FILES = {
    "KB_Member": ("kb_member.jsonl", 500),
    "True_Non_Member": ("true_non_member.jsonl", 500),
    "Reserve": ("reserve.jsonl", 250),
}
FORMAL_QUERY_ROOT = PROJECT_ROOT / "artifacts" / "v6_3" / "stealth_filtered_queries"
SPLIT_ROOT = PROJECT_ROOT / "artifacts" / "v6_3" / "splits"
PILOT_ROOT = PROJECT_ROOT / "artifacts" / "v6_3" / "query_controls"
V20_ROOT = PROJECT_ROOT / "artifacts" / "v20"
PAIRED_QUERY_ROOT = PROJECT_ROOT / "artifacts" / "v6_3" / "paired_queries"
MODEL_SLUG = "llama-3.1-70b-instruct-pilot"
EXPECTED_MODEL = "meta/llama-3.1-70b-instruct"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the zero-API PCV-MIA v20 canonical preflight"
    )
    parser.add_argument(
        "--output",
        default="artifacts/v20/release_controls/preflight_report.json",
    )
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def source_key(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return str(
        row.get("source_key")
        or metadata.get("source_key")
        or row.get("source_id")
        or row.get("doc_id")
        or ""
    )


def validate_environment() -> dict[str, Any]:
    executable = Path(sys.executable).resolve()
    require(
        executable == Path(r"D:\python\anaconda\envs\mia_model\python.exe").resolve(),
        f"wrong Python environment: {executable}",
    )
    import torch

    require(torch.cuda.is_available(), "CUDA PyTorch is required; CPU fallback is forbidden")
    return {
        "python_executable": str(executable),
        "torch_version": str(torch.__version__),
        "cuda_available": True,
        "cuda_device": str(torch.cuda.get_device_name(0)),
    }


def validate_registry() -> dict[str, Any]:
    registry = load_yaml(PROJECT_ROOT / "configs" / "generator_families.yaml")
    llama = (registry.get("generator_families") or {}).get("llama") or {}
    require(llama.get("status") == "frozen", "Llama generator family is not frozen")
    require(
        llama.get("concrete_model") == EXPECTED_MODEL,
        "frozen Llama concrete model drifted",
    )
    require(
        llama.get("model_version") == EXPECTED_MODEL,
        "frozen Llama model version drifted",
    )
    require(
        llama.get("first_formal_call_at") is None,
        "formal Llama calls already exist according to the registry",
    )
    return {
        "family": "llama",
        "status": "frozen",
        "concrete_model": llama["concrete_model"],
        "model_version": llama["model_version"],
        "first_formal_call_at": None,
    }


def validate_splits_and_queries(dataset: str) -> tuple[dict[str, set[str]], dict[str, Any]]:
    split_dir = SPLIT_ROOT / dataset
    groups: dict[str, set[str]] = {}
    split_hashes: dict[str, str] = {}
    for group, (filename, expected_count) in GROUP_FILES.items():
        path = split_dir / filename
        keys: set[str] = set()
        for row in read_jsonl(path):
            require(str(row.get("group")) == group, f"{dataset}/{group}: group label drift")
            key = source_key(row)
            require(bool(key), f"{dataset}/{group}: missing source identity")
            keys.add(key)
        require(
            len(keys) == expected_count,
            f"{dataset}/{group}: expected {expected_count} sources, got {len(keys)}",
        )
        groups[group] = keys
        split_hashes[group] = sha256_file(path)
    require(
        not (groups["KB_Member"] & groups["True_Non_Member"]),
        f"{dataset}: Member/Non-member source overlap",
    )
    require(
        not (groups["KB_Member"] & groups["Reserve"]),
        f"{dataset}: Member/Reserve source overlap",
    )
    require(
        not (groups["True_Non_Member"] & groups["Reserve"]),
        f"{dataset}: Non-member/Reserve source overlap",
    )

    query_path = FORMAL_QUERY_ROOT / f"{dataset}_paired_queries.jsonl"
    generated_query_path = PAIRED_QUERY_ROOT / f"{dataset}_paired_queries.jsonl"
    generation_manifest = read_json(generated_query_path.with_suffix(".manifest.json"))
    filter_manifest = read_json(query_path.with_suffix(".manifest.json"))
    benchmark_path = (
        PROJECT_ROOT
        / "artifacts"
        / "v6_3"
        / "benchmarks"
        / f"{dataset}_attack_benchmark.jsonl"
    )
    benchmark_hash = sha256_file(benchmark_path)
    require(
        generation_manifest.get("query_generation_protocol") == DIVERSE_QUERY_PROTOCOL,
        f"{dataset}: Step 08 diverse query protocol is not frozen",
    )
    require(
        generation_manifest.get("query_type") == DIVERSE_QUERY_TYPE,
        f"{dataset}: Step 08 query type drift",
    )
    require(
        generation_manifest.get("input_benchmark_hash") == benchmark_hash,
        f"{dataset}: Step 08 benchmark binding drift",
    )
    require(
        filter_manifest.get("lexical_copy_protocol")
        == "entity_masked_query_vs_original_chunk",
        f"{dataset}: Step 09 lexical-copy protocol is not frozen",
    )
    require(
        filter_manifest.get("embedding_role") == "diagnostic_only",
        f"{dataset}: Step 09 embedding must be diagnostic-only",
    )
    require(
        filter_manifest.get("input_benchmark_hash") == benchmark_hash,
        f"{dataset}: Step 09 benchmark binding drift",
    )
    require(
        filter_manifest.get("input_queries_hash") == sha256_file(generated_query_path),
        f"{dataset}: Step 09 input-query binding drift",
    )
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    query_ids: set[str] = set()
    for row in read_jsonl(query_path):
        query_id = str(row.get("query_id") or "")
        require(query_id and query_id not in query_ids, f"{dataset}: duplicate query_id")
        require(
            row.get("query_type") == DIVERSE_QUERY_TYPE,
            f"{dataset}: legacy query leaked into formal matrix",
        )
        require(
            row.get("query_generation_protocol") == DIVERSE_QUERY_PROTOCOL,
            f"{dataset}: query protocol provenance drift",
        )
        require(
            str(row.get("question_template") or "").count("{ENTITY}") == 1,
            f"{dataset}: invalid entity-slot template",
        )
        require(
            8 <= int(row.get("question_word_count") or 0) <= 45
            and str(row.get("query") or "").endswith("?"),
            f"{dataset}: formal query structure/naturalness drift",
        )
        query_ids.add(query_id)
        by_source[source_key(row)].append(row)
    expected_sources = set().union(*groups.values())
    require(set(by_source) == expected_sources, f"{dataset}: query/split source identity drift")
    require(len(query_ids) == 7_500, f"{dataset}: expected 7,500 formal queries")
    require(
        all(len(rows) == 6 for rows in by_source.values()),
        f"{dataset}: every source must have exactly six queries",
    )
    for source_rows in by_source.values():
        by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source_rows:
            by_pair[str(row.get("pair_id") or "")].append(row)
        require(len(by_pair) == 3, f"{dataset}: every source must retain three pairs")
        for pair_rows in by_pair.values():
            require(len(pair_rows) == 2, f"{dataset}: incomplete query pair")
            true_row = next(
                (row for row in pair_rows if row.get("claim_type") == "true"),
                None,
            )
            counterfactual_row = next(
                (row for row in pair_rows if row.get("claim_type") == "counterfactual"),
                None,
            )
            require(
                true_row is not None and counterfactual_row is not None,
                f"{dataset}: claim-type pair drift",
            )
            validation = validate_query_pair(
                str(true_row["query"]),
                str(counterfactual_row["query"]),
                str(true_row["original_entity"]),
                str(true_row["paired_counterfactual_entity"]),
            )
            require(validation.valid, f"{dataset}: Q+/Q- minimal-difference invariant failed")
    query_group_sources = Counter(str(rows[0].get("group")) for rows in by_source.values())
    require(
        query_group_sources == Counter(
            {"KB_Member": 500, "True_Non_Member": 500, "Reserve": 250}
        ),
        f"{dataset}: formal query group counts drifted",
    )
    return groups, {
        "source_counts": {group: len(keys) for group, keys in groups.items()},
        "split_hashes": split_hashes,
        "query_count": len(query_ids),
        "query_hash": sha256_file(query_path),
        "query_generation_manifest_hash": sha256_file(
            generated_query_path.with_suffix(".manifest.json")
        ),
        "stealth_filter_manifest_hash": sha256_file(query_path.with_suffix(".manifest.json")),
    }


def validate_benchmark(dataset: str) -> dict[str, Any]:
    root = PROJECT_ROOT / "artifacts" / "v6_3" / "benchmarks"
    benchmark = root / f"{dataset}_attack_benchmark.jsonl"
    expected = (root / f"{dataset}_attack_benchmark.sha256").read_text(
        encoding="utf-8"
    ).strip().split()[0]
    actual = sha256_file(benchmark)
    require(actual == expected, f"{dataset}: attack benchmark hash drift")
    manifest = read_json(root / f"{dataset}_benchmark_manifest.json")
    manifest_hash = str(
        manifest.get("benchmark_hash")
        or manifest.get("attack_benchmark_hash")
        or manifest.get("sha256")
        or ""
    )
    if manifest_hash:
        require(manifest_hash == actual, f"{dataset}: benchmark manifest hash drift")
    return {"benchmark_hash": actual}


def validate_reserve_roles(dataset: str, groups: dict[str, set[str]]) -> dict[str, Any]:
    path = (
        V20_ROOT
        / "release_controls"
        / "reserve_roles"
        / f"{dataset}_reserve_roles.json"
    )
    manifest = read_json(path)
    roles = list(manifest.get("roles") or [])
    require(sha256_obj(roles) == manifest.get("roles_hash"), f"{dataset}: role hash drift")
    pilot = {
        str(row["source_key"])
        for row in roles
        if row.get("reserve_role") == "pilot_diagnostic"
    }
    calibration = {
        str(row["source_key"])
        for row in roles
        if row.get("reserve_role") == "conformal_calibration"
    }
    require(len(pilot) == 5, f"{dataset}: expected five Pilot Reserve sources")
    require(len(calibration) == 245, f"{dataset}: expected 245 calibration sources")
    require(not (pilot & calibration), f"{dataset}: Pilot/calibration overlap")
    require(pilot | calibration == groups["Reserve"], f"{dataset}: Reserve role drift")
    require(
        manifest.get("calibration_scope")
        == "post_retriever_frozen_nonmember_calibration",
        f"{dataset}: calibration scope drift",
    )
    require(
        manifest.get("retriever_selection_used_attack_scores") is False,
        f"{dataset}: Retriever selection may not use attack scores",
    )
    return {
        "pilot_diagnostic": len(pilot),
        "conformal_calibration": len(calibration),
        "roles_file_hash": sha256_file(path),
    }


def validate_pilot(dataset: str, groups: dict[str, set[str]]) -> dict[str, Any]:
    root = PILOT_ROOT / dataset / MODEL_SLUG
    budget = read_json(root / "budget.json")
    rows = list(read_jsonl(root / "queries.jsonl"))
    require(budget.get("generator_id") == EXPECTED_MODEL, f"{dataset}: Pilot model drift")
    require(
        budget.get("input_queries_hash")
        == sha256_file(FORMAL_QUERY_ROOT / f"{dataset}_paired_queries.jsonl"),
        f"{dataset}: Pilot is not bound to the rebuilt formal queries",
    )
    require(len(rows) == 150, f"{dataset}: Pilot must contain 150 queries")
    require(
        len({str(row.get("query_id") or "") for row in rows}) == 150,
        f"{dataset}: Pilot query identities are not unique",
    )
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        require(
            row.get("query_type") == DIVERSE_QUERY_TYPE
            and row.get("query_generation_protocol") == DIVERSE_QUERY_PROTOCOL,
            f"{dataset}: Pilot contains legacy query protocol",
        )
        by_source[source_key(row)].append(row)
    require(len(by_source) == 25, f"{dataset}: Pilot must contain 25 sources")
    require(
        all(len(source_rows) == 6 for source_rows in by_source.values()),
        f"{dataset}: Pilot sources must each have six queries",
    )
    group_counts = Counter(str(rows[0].get("group")) for rows in by_source.values())
    require(
        group_counts == Counter({"KB_Member": 10, "True_Non_Member": 10, "Reserve": 5}),
        f"{dataset}: Pilot group counts drifted",
    )
    for group, selected in (budget.get("selected_source_keys") or {}).items():
        require(set(map(str, selected)) <= groups[group], f"{dataset}: Pilot source outside {group}")
    require(int((budget.get("calls") or {}).get("total") or 0) == 900, f"{dataset}: Pilot calls drift")
    require(int(budget.get("api_calls_made") or 0) == 0, f"{dataset}: Pilot API calls already made")
    require(
        budget.get("queries_hash") == sha256_file(root / "queries.jsonl"),
        f"{dataset}: Pilot query hash drift",
    )
    return {
        "source_count": len(by_source),
        "query_count": len(rows),
        "planned_calls": 900,
        "api_calls_made": 0,
        "queries_hash": budget["queries_hash"],
    }


def validate_representatives(
    dataset: str,
    groups: dict[str, set[str]],
    query_hash: str,
) -> dict[str, Any]:
    root = V20_ROOT / "release_controls" / "representative_chunks"
    path = root / f"{dataset}_representative_chunks.jsonl"
    manifest = read_json(root / f"{dataset}_representative_chunks.manifest.json")
    rows = list(read_jsonl(path))
    source_ids = [source_key(row) for row in rows]
    expected = groups["KB_Member"] | groups["True_Non_Member"]
    require(len(rows) == 1_000, f"{dataset}: representative row count drift")
    require(len(set(source_ids)) == 1_000, f"{dataset}: representative source duplicate")
    require(set(source_ids) == expected, f"{dataset}: representative source universe drift")
    require(
        sha256_file(path) == manifest.get("representative_chunk_manifest_hash"),
        f"{dataset}: representative manifest hash drift",
    )
    require(
        (manifest.get("input_hashes") or {}).get("queries") == query_hash,
        f"{dataset}: representative chunks are not bound to rebuilt queries",
    )
    require(manifest.get("shared_across_methods") is True, f"{dataset}: chunks not shared")
    return {
        "source_count": len(source_ids),
        "manifest_hash": manifest["representative_chunk_manifest_hash"],
    }


def validate_index(dataset: str, groups: dict[str, set[str]], backend: str) -> dict[str, Any]:
    if backend == "dense":
        root = V20_ROOT / "indexes" / dataset / "bge-base-en-v1.5"
        index_name = "faiss.index"
    else:
        root = V20_ROOT / "indexes" / dataset / "bm25"
        index_name = "bm25.index.json"
    manifest = read_json(root / "index_manifest.json")
    require(manifest.get("dataset") == dataset, f"{dataset}/{backend}: dataset drift")
    require(manifest.get("retriever_backend") == backend, f"{dataset}/{backend}: backend drift")
    require(manifest.get("chunk_size") == 128, f"{dataset}/{backend}: chunk size drift")
    require(manifest.get("chunk_overlap") == 32, f"{dataset}/{backend}: overlap drift")
    kb_path = SPLIT_ROOT / dataset / "kb_member.jsonl"
    require(manifest.get("kb_hash") == sha256_file(kb_path), f"{dataset}/{backend}: KB hash drift")
    require(
        manifest.get("docstore_hash") == sha256_file(root / "docstore.jsonl"),
        f"{dataset}/{backend}: docstore hash drift",
    )
    require(
        manifest.get("index_hash") == sha256_file(root / index_name),
        f"{dataset}/{backend}: index file hash drift",
    )
    allowed_source_ids = {
        str(row.get("source_id") or "")
        for row in read_jsonl(SPLIT_ROOT / dataset / "kb_member.jsonl")
    }
    require("" not in allowed_source_ids, f"{dataset}: KB source_id is missing")
    require(
        len(allowed_source_ids) == len(groups["KB_Member"]),
        f"{dataset}: KB source_id is not source-unique",
    )
    seen_sources: set[str] = set()
    for row in read_jsonl(root / "docstore.jsonl"):
        require(str(row.get("group")) == "KB_Member", f"{dataset}/{backend}: forbidden group indexed")
        key = str(row.get("source_id") or (row.get("metadata") or {}).get("source_id") or "")
        require(key in allowed_source_ids, f"{dataset}/{backend}: unknown source indexed")
        seen_sources.add(key)
    require(seen_sources == allowed_source_ids, f"{dataset}/{backend}: KB source coverage drift")
    return {
        "retriever_id": manifest.get("retriever_id"),
        "num_chunks": manifest.get("num_chunks"),
        "index_manifest_hash": sha256_file(root / "index_manifest.json"),
    }


def validate_schedule(query_hashes: dict[str, str]) -> dict[str, Any]:
    root = V20_ROOT / "release_controls"
    path = root / "execution_schedule.jsonl"
    manifest = read_json(root / "execution_schedule.manifest.json")
    require(manifest.get("request_count") == 90_000, "schedule manifest count drift")
    require(manifest.get("query_hashes") == query_hashes, "schedule query binding drift")
    require(manifest.get("schedule_hash") == sha256_file(path), "schedule file hash drift")
    ordinals: set[int] = set()
    identities: set[tuple[str, str, str]] = set()
    cells = Counter()
    datasets = Counter()
    row_count = 0
    for row in read_jsonl(path):
        row_count += 1
        ordinal = int(row.get("ordinal"))
        identity = (
            str(row.get("dataset")),
            str(row.get("query_id")),
            str(row.get("cell")),
        )
        require(ordinal not in ordinals, "duplicate schedule ordinal")
        require(identity not in identities, "duplicate scheduled request identity")
        ordinals.add(ordinal)
        identities.add(identity)
        cells[identity[2]] += 1
        datasets[identity[0]] += 1
    require(row_count == 90_000, "schedule row count drift")
    require(ordinals == set(range(90_000)), "schedule ordinals are not contiguous")
    require(
        cells == Counter({"dense": 22_500, "bm25": 22_500, "hybrid": 22_500, "none": 22_500}),
        "schedule cell counts drift",
    )
    require(
        datasets == Counter({"edgar": 30_000, "enron": 30_000, "pubmed": 30_000}),
        "schedule dataset counts drift",
    )
    return {
        "request_count": row_count,
        "schedule_hash": manifest["schedule_hash"],
        "cell_counts": dict(cells),
        "dataset_counts": dict(datasets),
    }


def validate_retrieval_gate(query_hashes: dict[str, str]) -> dict[str, Any]:
    report = read_json(V20_ROOT / "retrieval_gate" / "retrieval_gate_report.json")
    require(report.get("completed") is True, "retrieval gate is incomplete")
    require(report.get("completed_candidate_count") == 9, "retrieval gate candidate count drift")
    require(report.get("selection_uses_attack_metrics") is False, "gate used attack metrics")
    require(report.get("base_bge_gate_passed") is True, "base BGE gate did not pass")
    require(
        report.get("query_hashes") == query_hashes,
        "retrieval gate is not bound to the rebuilt formal queries",
    )
    selected = report.get("selected_chunk_config") or {}
    require(
        selected.get("chunk_config_id") == "tokens-128-overlap-32",
        "selected BGE chunk configuration drift",
    )
    return {
        "completed_candidate_count": 9,
        "selected_chunk_config": selected,
        "base_bge_gate_passed": True,
    }


def validate_query_rewrite_shadow_gate() -> dict[str, Any]:
    path = V20_ROOT / "query_rewrite_shadow" / "promotion_gate.json"
    report = read_json(path)
    require(report.get("passed") is True, "diverse-query shadow promotion gate did not pass")
    require(
        report.get("gate_protocol") == "diverse_query_shadow_noninferiority_v1",
        "diverse-query shadow gate protocol drift",
    )
    audit = report.get("audit") or {}
    require(
        int(audit.get("logical_victim_calls") or 0) == 7_200,
        "diverse-query shadow victim budget drift",
    )
    require(
        audit.get("neutral_prompt_robustness_cell") is False,
        "neutral prompt robustness cell is outside the paper protocol",
    )
    require(not report.get("failures"), "diverse-query shadow gate contains failures")
    return {
        "gate_report_hash": sha256_file(path),
        "gate_identity_hash": report.get("gate_identity_hash"),
        "macro_auc_difference_ci95": (
            report.get("auc_noninferiority") or {}
        ).get("macro_difference_ci95"),
        "lexical": report.get("lexical"),
    }


def validate_no_responses() -> dict[str, Any]:
    found: list[str] = []
    for dirname in ("rag_responses", "llm_only_responses", "runs", "scores", "reports"):
        root = V20_ROOT / dirname
        if root.exists():
            found.extend(str(path.relative_to(PROJECT_ROOT)) for path in root.rglob("*") if path.is_file())
    require(not found, f"formal v20 response/result artifacts already exist: {found[:3]}")
    return {"formal_response_or_result_files": 0, "api_calls_made": 0}


def main() -> int:
    args = parse_args()
    report: dict[str, Any] = {
        "protocol_version": "pcv-mia-v20",
        "method_version": "pcv-rag-only-source-v20",
        "api_calls_made": 0,
        "environment": validate_environment(),
        "generator": validate_registry(),
        "query_rewrite_shadow": validate_query_rewrite_shadow_gate(),
        "datasets": {},
    }
    query_hashes: dict[str, str] = {}
    for dataset in DATASETS:
        groups, dataset_report = validate_splits_and_queries(dataset)
        query_hashes[dataset] = dataset_report["query_hash"]
        dataset_report["benchmark"] = validate_benchmark(dataset)
        dataset_report["reserve_roles"] = validate_reserve_roles(dataset, groups)
        dataset_report["pilot"] = validate_pilot(dataset, groups)
        dataset_report["representative_chunks"] = validate_representatives(
            dataset,
            groups,
            dataset_report["query_hash"],
        )
        dataset_report["indexes"] = {
            "dense": validate_index(dataset, groups, "dense"),
            "bm25": validate_index(dataset, groups, "bm25"),
        }
        report["datasets"][dataset] = dataset_report
    report["execution_schedule"] = validate_schedule(query_hashes)
    report["retrieval_gate"] = validate_retrieval_gate(query_hashes)
    report["response_state"] = validate_no_responses()

    release = read_json(V20_ROOT / "release_controls" / "release_controls_manifest.json")
    require(release.get("api_calls_made") == 0, "release manifest records API calls")
    require(
        release.get("schedule_hash") == report["execution_schedule"]["schedule_hash"],
        "release/schedule hash drift",
    )
    report["release_controls_hash"] = sha256_file(
        V20_ROOT / "release_controls" / "release_controls_manifest.json"
    )
    report["status"] = "passed"
    report["checks_hash"] = sha256_obj(
        {key: value for key, value in report.items() if key != "checks_hash"}
    )
    output = PROJECT_ROOT / args.output
    write_json(report, output)
    print(f"[PASS] PCV-MIA v20 zero-API preflight: {output}")
    print("[PASS] 3 datasets, 22,500 formal queries, 90,000 scheduled main requests")
    print("[PASS] Pilot plan: 2,700 calls; formal/API calls made: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
