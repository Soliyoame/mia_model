"""Re-run shared-G retrieval with the designated Member sources included.

The first combined retrieval attempt is preserved as diagnostic evidence because
its legacy helper selected only the first 50 Member slots from the source pool
and could omit late replacement Members.  This runner copies the frozen 100
source/query identity, constructs a corrected 50-source-per-dataset Member
index, and writes a separate retrieval/victim identity.  No queries or source
facts are regenerated.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.prepare.restoration_first_v25 import source_pool_paths  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj, sha256_text  # noqa: E402
from src.utils.io import read_jsonl, write_json, write_jsonl_atomic  # noqa: E402


COMBINED_PATH = ROOT / "scripts/100_run_v25_shared_g_combined.py"
COMBINED_SPEC = importlib.util.spec_from_file_location("v25_shared_g_combined_fixed_index", COMBINED_PATH)
if COMBINED_SPEC is None or COMBINED_SPEC.loader is None:
    raise RuntimeError("combined_runner_import_spec_unavailable")
COMBINED = importlib.util.module_from_spec(COMBINED_SPEC)
COMBINED_SPEC.loader.exec_module(COMBINED)

PILOT = COMBINED.PILOT
INPUT_OUT = COMBINED.OUT
OUT = ROOT / "artifacts/v25/development/shared_g_anchor_cohort_query_usable_100sample_50plus50_member_index_fixed_20261002"
SOURCE_PLAN = OUT / "source_plan.json"
SOURCE_MANIFEST = OUT / "source_manifest.jsonl"
RUN_CONFIG = OUT / "run_config.json"
GENERATION = OUT / "generation.jsonl"
CONSTRUCTION_REPORT = OUT / "construction_report.json"
QUERY_PLAN = OUT / "query_plan.jsonl"
QUERY_FREEZE = OUT / "query_freeze.json"
RETRIEVAL = OUT / "retrieval.jsonl"
INITIAL_RESPONSES = OUT / "initial_responses.jsonl"
FOLLOWUP_RESPONSES = OUT / "followup_responses.jsonl"
REPORT = OUT / "report.json"
INDEX_MANIFEST = OUT / "index_manifest.json"

SEED = "v25-shared-g-anchor-query-usable-100sample-50plus50-member-index-fixed-20261002"
DATASETS = tuple(COMBINED.DATASETS)
INDEX_MEMBER_SOURCES_PER_DATASET = 50
EXPECTED_QUERY_COUNT = COMBINED.EXPECTED_QUERY_COUNT


def _read_rows(path: Path) -> list[dict[str, Any]]:
    return list(read_jsonl(path)) if path.is_file() else []


def _copy_frozen_inputs() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    names = (
        "source_plan.json",
        "source_manifest.jsonl",
        "generation.jsonl",
        "construction_report.json",
        "query_plan.jsonl",
        "query_freeze.json",
    )
    for name in names:
        source = INPUT_OUT / name
        if not source.is_file():
            raise FileNotFoundError(f"frozen_input_missing:{source}")
        shutil.copy2(source, OUT / name)


def _patch_paths() -> None:
    COMBINED.OUT = OUT
    COMBINED.SOURCE_PLAN = SOURCE_PLAN
    COMBINED.SOURCE_MANIFEST = SOURCE_MANIFEST
    COMBINED.RUN_CONFIG = RUN_CONFIG
    COMBINED.GENERATION = GENERATION
    COMBINED.CONSTRUCTION_REPORT = CONSTRUCTION_REPORT
    COMBINED.QUERY_PLAN = QUERY_PLAN
    COMBINED.QUERY_FREEZE = QUERY_FREEZE
    COMBINED.RETRIEVAL = RETRIEVAL
    COMBINED.INITIAL_RESPONSES = INITIAL_RESPONSES
    COMBINED.FOLLOWUP_RESPONSES = FOLLOWUP_RESPONSES
    COMBINED.REPORT = REPORT
    COMBINED.SEED = SEED
    COMBINED._patch_pilot_paths()


def _candidate_member_keys(dataset: str) -> tuple[list[str], dict[str, Any]]:
    paths = source_pool_paths(ROOT, PILOT.V25_CONFIG, dataset)
    order_payload = json.loads(paths["source_order"].read_text(encoding="utf-8"))
    exclusion_payload = json.loads(paths["development_exclusions"].read_text(encoding="utf-8"))
    excluded = {
        str(row["source_key"])
        for row in exclusion_payload.get("exclusions", [])
        if row.get("source_key")
    }
    candidates = [str(key) for key in order_payload["source_order"] if str(key) not in excluded]
    return candidates, {
        "source_order_sha256": sha256_file(paths["source_order"]),
        "development_exclusions_sha256": sha256_file(paths["development_exclusions"]),
        "candidate_count": len(candidates),
    }


def _member_index_rows(dataset: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sources, _ = COMBINED._load_combined()
    designated = {
        str(row["source_key"])
        for row in sources
        if str(row["dataset"]) == dataset and str(row["group"]) == "KB_Member"
    }
    candidates, pool_meta = _candidate_member_keys(dataset)
    candidate_index = {key: index for index, key in enumerate(candidates)}
    missing_designated = sorted(designated - set(candidates))
    if missing_designated:
        raise RuntimeError(f"designated_member_not_in_source_pool:{dataset}:{missing_designated}")
    pool_members = [key for index, key in enumerate(candidates) if index % 2 == 0]
    selected_keys = sorted(designated, key=lambda key: candidate_index[key])
    selected_keys.extend(
        key for key in pool_members
        if key not in designated and len(selected_keys) < INDEX_MEMBER_SOURCES_PER_DATASET
    )
    if len(selected_keys) != INDEX_MEMBER_SOURCES_PER_DATASET:
        raise RuntimeError(f"member_index_size_drift:{dataset}:{len(selected_keys)}")
    if not designated.issubset(set(selected_keys)):
        raise RuntimeError(f"designated_member_omitted:{dataset}")
    paths = source_pool_paths(ROOT, PILOT.V25_CONFIG, dataset)
    placeholders = ",".join("?" for _ in selected_keys)
    with sqlite3.connect(paths["database"]) as connection:
        fetched = connection.execute(
            "SELECT source_key, dataset, document_id, source_order_rank, source_hash, "
            "normalized_text_hash, full_text FROM sources WHERE source_key IN (" + placeholders + ")",
            selected_keys,
        ).fetchall()
    by_key = {
        str(row[0]): {
            "source_key": str(row[0]),
            "dataset": str(row[1]),
            "document_id": str(row[2]),
            "source_order_rank": str(row[3]),
            "source_hash": str(row[4]),
            "normalized_text_hash": str(row[5]),
            "full_text": str(row[6]),
        }
        for row in fetched
    }
    if set(by_key) != set(selected_keys):
        raise RuntimeError(f"member_index_source_missing:{dataset}")
    rows = [by_key[key] for key in selected_keys]
    for row in rows:
        if sha256_text(row["full_text"]) != row["source_hash"]:
            raise RuntimeError(f"member_index_hash_drift:{row['source_key']}")
    return rows, {
        "dataset": dataset,
        "selection_rule": "designated_cohort_members_plus_earliest_source_order_member_fill_to_50",
        "designated_member_count": len(designated),
        "designated_member_keys": sorted(designated, key=lambda key: candidate_index[key]),
        "selected_source_keys": selected_keys,
        "selected_source_keys_sha256": sha256_obj(selected_keys),
        "selected_source_hashes_sha256": sha256_obj([(row["source_key"], row["source_hash"]) for row in rows]),
        "candidate_order_metadata": pool_meta,
    }


def _install_context(index_rows_by_dataset: dict[str, list[dict[str, Any]]]) -> None:
    _patch_paths()
    COMBINED._install_pilot_context()

    def member_rows(dataset: str) -> list[dict[str, Any]]:
        return index_rows_by_dataset[dataset]

    PILOT._source_pool_member_rows = member_rows


def _write_fixed_config(index_metadata: dict[str, Any]) -> None:
    original = json.loads((INPUT_OUT / "run_config.json").read_text(encoding="utf-8"))
    original.update({
        "kind": "v25_shared_g_anchor_query_usable_combined_member_index_fixed_config",
        "status": "fixed_before_retrieval_or_victim_calls",
        "seed": SEED,
        "parent_combined_run_config_sha256": sha256_file(INPUT_OUT / "run_config.json"),
        "parent_combined_retrieval_sha256": sha256_file(INPUT_OUT / "retrieval.jsonl") if (INPUT_OUT / "retrieval.jsonl").is_file() else None,
        "retrieval_identity": {
            "index_selection": "designated_cohort_members_plus_earliest_source_order_member_fill_to_50",
            "index_member_sources_per_dataset": INDEX_MEMBER_SOURCES_PER_DATASET,
            "index_manifest_sha256": sha256_file(INDEX_MANIFEST),
            "query_plan_sha256": sha256_file(QUERY_PLAN),
        },
        "downstream_calls": {"retriever": 0, "victim": 0},
        "diagnostic_superseded_artifact": str((INPUT_OUT / "retrieval.jsonl").relative_to(ROOT)),
    })
    write_json(original, RUN_CONFIG)


def prepare() -> None:
    _copy_frozen_inputs()
    _patch_paths()
    sources, _ = COMBINED._load_combined()
    if len(sources) != 100:
        raise RuntimeError("fixed_index_source_count_drift")
    index_rows_by_dataset: dict[str, list[dict[str, Any]]] = {}
    index_metadata: dict[str, Any] = {}
    for dataset in DATASETS:
        rows, metadata = _member_index_rows(dataset)
        index_rows_by_dataset[dataset] = rows
        index_metadata[dataset] = metadata
    write_json({
        "kind": "v25_shared_g_anchor_member_index_manifest",
        "status": "fixed_before_retrieval_or_victim_calls",
        "source_unit": "source_document",
        "source_plan_sha256": sha256_file(SOURCE_PLAN),
        "query_plan_sha256": sha256_file(QUERY_PLAN),
        "datasets": index_metadata,
        "index_source_count_total": sum(len(rows) for rows in index_rows_by_dataset.values()),
        "index_source_keys_sha256": sha256_obj({dataset: [row["source_key"] for row in rows] for dataset, rows in index_rows_by_dataset.items()}),
    }, INDEX_MANIFEST)
    _write_fixed_config(index_metadata)
    print(json.dumps({
        "stage": "prepare",
        "sources": len(sources),
        "index_sources": {dataset: len(rows) for dataset, rows in index_rows_by_dataset.items()},
        "designated_members": {dataset: metadata["designated_member_count"] for dataset, metadata in index_metadata.items()},
        "query_plan_sha256": sha256_file(QUERY_PLAN),
        "index_manifest_sha256": sha256_file(INDEX_MANIFEST),
        "external_calls": 0,
    }, ensure_ascii=False))


def _load_index_rows() -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(INDEX_MANIFEST.read_text(encoding="utf-8"))
    result: dict[str, list[dict[str, Any]]] = {}
    for dataset in DATASETS:
        keys = payload["datasets"][dataset]["selected_source_keys"]
        paths = source_pool_paths(ROOT, PILOT.V25_CONFIG, dataset)
        placeholders = ",".join("?" for _ in keys)
        with sqlite3.connect(paths["database"]) as connection:
            fetched = connection.execute(
                "SELECT source_key, dataset, document_id, source_order_rank, source_hash, "
                "normalized_text_hash, full_text FROM sources WHERE source_key IN (" + placeholders + ")",
                keys,
            ).fetchall()
        by_key = {
            str(row[0]): {
                "source_key": str(row[0]), "dataset": str(row[1]), "document_id": str(row[2]),
                "source_order_rank": str(row[3]), "source_hash": str(row[4]),
                "normalized_text_hash": str(row[5]), "full_text": str(row[6]),
            }
            for row in fetched
        }
        if set(by_key) != set(keys):
            raise RuntimeError(f"fixed_index_manifest_source_drift:{dataset}")
        result[dataset] = [by_key[key] for key in keys]
    return result


def retrieve() -> None:
    if not INDEX_MANIFEST.is_file() or not QUERY_FREEZE.is_file():
        raise RuntimeError("prepare_and_freeze_input_required")
    index_rows = _load_index_rows()
    _install_context(index_rows)
    PILOT.retrieve()
    rows = _read_rows(RETRIEVAL)
    if len(rows) != EXPECTED_QUERY_COUNT:
        raise RuntimeError(f"fixed_retrieval_count:{len(rows)}")
    allowed = {dataset: {row["source_key"] for row in source_rows} for dataset, source_rows in index_rows.items()}
    for row in rows:
        if any(chunk["source_key"] not in allowed[row["dataset"]] for chunk in row["retrieved_chunks"]):
            raise RuntimeError(f"retrieval_nonmember_chunk:{row['query_id']}")
        for chunk in row["retrieved_chunks"]:
            if sha256_text(chunk["text"]) == "":
                raise RuntimeError("impossible_chunk_hash")
    print(json.dumps({
        "stage": "retrieve",
        "queries": len(rows),
        "retrieval_sha256": sha256_file(RETRIEVAL),
        "index_manifest_sha256": sha256_file(INDEX_MANIFEST),
    }, ensure_ascii=False))


def run_initial(max_new: int) -> None:
    index_rows = _load_index_rows()
    _install_context(index_rows)
    COMBINED.run_initial(max_new)


def run_followup(max_new: int) -> None:
    index_rows = _load_index_rows()
    _install_context(index_rows)
    COMBINED.run_followup(max_new)


def report() -> None:
    index_rows = _load_index_rows()
    _install_context(index_rows)
    COMBINED.report()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--retrieve", action="store_true")
    modes.add_argument("--run-initial", action="store_true")
    modes.add_argument("--run-followup", action="store_true")
    modes.add_argument("--report", action="store_true")
    parser.add_argument("--max-new", type=int, default=0)
    args = parser.parse_args()
    if args.run_initial or args.run_followup:
        if args.max_new < 1:
            parser.error("victim calls require --max-new >= 1")
    elif args.max_new:
        parser.error("--max-new only applies to victim calls")
    if args.prepare:
        prepare()
    elif args.retrieve:
        retrieve()
    elif args.run_initial:
        run_initial(args.max_new)
    elif args.run_followup:
        run_followup(args.max_new)
    else:
        report()


if __name__ == "__main__":
    main()
