"""Construct a fixed seven-source shared-G replacement cohort.

This development-only runner selects the next unused TREC-COVID sources in the
frozen source-pool order after auditing historical V25 source plans/manifests.
It keeps a 3 KB_Member / 4 True_Non_Member quota and reuses the shared-G
construction prompt and structural validator from the r3 runner.  It performs
only Luna construction calls; Retriever and victim stages are intentionally
absent.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.prepare.restoration_first_v25 import source_pool_paths  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj, sha256_text  # noqa: E402
from src.utils.io import read_jsonl, write_json, write_jsonl_atomic  # noqa: E402


PILOT_PATH = ROOT / "scripts/95_run_v25_shared_g_pilot.py"
PILOT_SPEC = importlib.util.spec_from_file_location("v25_shared_g_pilot_replacement", PILOT_PATH)
if PILOT_SPEC is None or PILOT_SPEC.loader is None:
    raise RuntimeError("shared_g_pilot_import_spec_unavailable")
PILOT = importlib.util.module_from_spec(PILOT_SPEC)
PILOT_SPEC.loader.exec_module(PILOT)

DATASET = "trec-covid"
OUT = ROOT / "artifacts/v25/development/shared_g_anchor_replacement_7_20261002"
SOURCE_PLAN = OUT / "source_plan.json"
SOURCE_MANIFEST = OUT / "source_manifest.jsonl"
RUN_CONFIG = OUT / "run_config.json"
GENERATION = OUT / "generation.jsonl"
CONSTRUCTION_REPORT = OUT / "construction_report.json"

SEED = "v25-shared-g-anchor-replacement-7-20261002"
SOURCE_COUNT = 7
GROUP_QUOTAS = {"KB_Member": 3, "True_Non_Member": 4}
QUERIES_PER_SOURCE = 9


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    return list(read_jsonl(path)) if path.is_file() else []


def _source_keys(rows: Iterable[dict[str, Any]]) -> list[str]:
    return [str(row.get("source_key")) for row in rows]


def _walk_source_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        if value.get("source_key"):
            keys.add(str(value["source_key"]))
        for child in value.values():
            keys.update(_walk_source_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_source_keys(child))
    return keys


def _history_files() -> list[Path]:
    paths: list[Path] = []
    artifact_root = ROOT / "artifacts/v25"
    for path in sorted(artifact_root.rglob("source_plan.json")):
        if path.parent == OUT:
            continue
        paths.append(path)
    for path in sorted(artifact_root.rglob("source_manifest.jsonl")):
        if path.parent == OUT:
            continue
        paths.append(path)
    return paths


def _historical_source_keys() -> tuple[set[str], list[str]]:
    used: set[str] = set()
    files: list[str] = []
    for path in _history_files():
        try:
            if path.name == "source_plan.json":
                used.update(_walk_source_keys(json.loads(path.read_text(encoding="utf-8"))))
            else:
                used.update(
                    str(row["source_key"])
                    for row in _read_manifest(path)
                    if row.get("source_key")
                )
            files.append(str(path.relative_to(ROOT)))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            # Historical diagnostic files are evidence, but a malformed unrelated
            # file must not silently influence the replacement selection.
            raise RuntimeError(f"historical_source_artifact_unreadable:{path}")
    return used, files


def _pool_candidates() -> tuple[list[str], dict[str, Any]]:
    paths = source_pool_paths(ROOT, PILOT.V25_CONFIG, DATASET)
    order_payload = json.loads(paths["source_order"].read_text(encoding="utf-8"))
    exclusion_payload = json.loads(paths["development_exclusions"].read_text(encoding="utf-8"))
    order = [str(key) for key in order_payload["source_order"]]
    excluded = {
        str(row["source_key"])
        for row in exclusion_payload.get("exclusions", [])
        if row.get("source_key")
    }
    candidates = [key for key in order if key not in excluded]
    return candidates, {
        "source_order_path": str(paths["source_order"].relative_to(ROOT)),
        "source_order_sha256": sha256_file(paths["source_order"]),
        "development_exclusions_path": str(paths["development_exclusions"].relative_to(ROOT)),
        "development_exclusions_sha256": sha256_file(paths["development_exclusions"]),
        "excluded_source_count": len(excluded),
        "candidate_count": len(candidates),
        "candidate_order_sha256": sha256_obj(candidates),
    }


def _select_sources() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    historical_keys, history_files = _historical_source_keys()
    candidates, pool_meta = _pool_candidates()
    unused = [key for key in candidates if key not in historical_keys]
    if len(unused) < SOURCE_COUNT:
        raise RuntimeError("insufficient_unused_trec_candidates")

    selected: list[tuple[int, str, str]] = []
    counts = Counter()
    for candidate_index, source_key in enumerate(unused):
        group = "KB_Member" if candidate_index % 2 == 0 else "True_Non_Member"
        if counts[group] >= GROUP_QUOTAS[group]:
            continue
        selected.append((candidate_index, source_key, group))
        counts[group] += 1
        if counts == Counter(GROUP_QUOTAS):
            break
    if len(selected) != SOURCE_COUNT or counts != Counter(GROUP_QUOTAS):
        raise RuntimeError(f"replacement_quota_selection_failed:{dict(counts)}")

    paths = source_pool_paths(ROOT, PILOT.V25_CONFIG, DATASET)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(paths["database"]) as connection:
        for candidate_index, source_key, group in selected:
            row = connection.execute(
                "SELECT source_key, dataset, document_id, source_order_rank, source_hash, "
                "normalized_text_hash, full_text FROM sources WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"replacement_source_missing:{source_key}")
            source_row = {
                "source_key": str(row[0]),
                "dataset": str(row[1]),
                "document_id": str(row[2]),
                "source_order_rank": str(row[3]),
                "source_hash": str(row[4]),
                "normalized_text_hash": str(row[5]),
                "group": group,
                "selection_basis": "source_order_without_prior_v25_source_use_fixed_group_quota",
                "replacement_candidate_index": candidate_index,
            }
            source_text = PILOT._source_text(source_row)
            if sha256_text(source_text) != source_row["source_hash"]:
                raise RuntimeError(f"replacement_source_hash_drift:{source_key}")
            rows.append(source_row)

    selection_meta = {
        "selection_rule": "first_unused_source_pool_order_after_historical_v25_audit",
        "membership_labels_read_during_selection": False,
        "victim_visible_during_selection": False,
        "luna_visible_during_selection": False,
        "historical_source_artifact_count": len(history_files),
        "historical_source_artifacts": history_files,
        "historical_source_key_count": len(historical_keys),
        "historical_source_keys_sha256": sha256_obj(sorted(historical_keys)),
        "unused_candidate_count": len(unused),
        "unused_candidate_keys_sha256": sha256_obj(unused),
        "selected_candidate_indices": [item[0] for item in selected],
        "selected_source_order_ranks": [int(row["source_order_rank"]) for row in rows],
        "selected_source_keys": _source_keys(rows),
        "selected_source_keys_sha256": sha256_obj(_source_keys(rows)),
        "group_quotas": dict(GROUP_QUOTAS),
        "group_counts": dict(Counter(row["group"] for row in rows)),
        "pool": pool_meta,
    }
    return rows, selection_meta


def _patch_pilot_paths() -> None:
    PILOT.OUT = OUT
    PILOT.SOURCE_PLAN = SOURCE_PLAN
    PILOT.SOURCE_MANIFEST = SOURCE_MANIFEST
    PILOT.RUN_CONFIG = RUN_CONFIG
    PILOT.GENERATION = GENERATION
    PILOT.SEED = SEED


def _load_source_rows() -> list[dict[str, Any]]:
    if not SOURCE_PLAN.is_file() or not SOURCE_MANIFEST.is_file():
        raise RuntimeError("prepare_required")
    plan = json.loads(SOURCE_PLAN.read_text(encoding="utf-8"))
    rows = _read_manifest(SOURCE_MANIFEST)
    if plan.get("source_count") != SOURCE_COUNT or len(rows) != SOURCE_COUNT:
        raise RuntimeError("replacement_source_count_drift")
    if Counter(str(row.get("group")) for row in rows) != Counter(GROUP_QUOTAS):
        raise RuntimeError("replacement_group_quota_drift")
    if len(set(_source_keys(rows))) != SOURCE_COUNT:
        raise RuntimeError("replacement_source_collision")
    if plan.get("selected_source_keys_sha256") != sha256_obj(_source_keys(rows)):
        raise RuntimeError("replacement_source_keys_hash_drift")
    for row in rows:
        if sha256_text(PILOT._source_text(row)) != str(row.get("source_hash")):
            raise RuntimeError(f"replacement_source_hash_drift:{row.get('source_key')}")
    return rows


def _install_generator_context() -> None:
    _patch_pilot_paths()
    PILOT._load_source_rows = _load_source_rows


def prepare() -> None:
    rows, selection_meta = _select_sources()
    OUT.mkdir(parents=True, exist_ok=True)
    write_jsonl_atomic(rows, SOURCE_MANIFEST)
    plan = {
        "kind": "v25_shared_g_anchor_replacement_source_plan",
        "status": "selected_before_new_luna_retrieval_or_victim_calls",
        "development_only": True,
        "protocol": "three_local_facts_plus_one_shared_remote_target",
        "source_unit": "source_document",
        "source_count": SOURCE_COUNT,
        "dataset": DATASET,
        "membership_labels_read": False,
        "selection": selection_meta,
        "selected_source_keys_sha256": sha256_obj(_source_keys(rows)),
        "input_sha256": {
            "configs\\restoration_first_v25.yaml": sha256_file(ROOT / "configs/restoration_first_v25.yaml"),
            "configs\\llm_profiles.yaml": sha256_file(ROOT / "configs/llm_profiles.yaml"),
            "scripts\\95_run_v25_shared_g_pilot.py": sha256_file(PILOT_PATH),
            "artifacts\\v24\\source_pools\\trec-covid\\source_pool.sqlite3": sha256_file(
                ROOT / "artifacts/v24/source_pools/trec-covid/source_pool.sqlite3"
            ),
        },
        "seed": SEED,
    }
    write_json(plan, SOURCE_PLAN)
    profiles = PILOT.load_llm_profiles({"llm_profiles_path": PILOT.V25_CONFIG["runtime"]["llm_profiles_path"]})
    effective_luna = PILOT.resolve_effective_llm_profile(
        profiles, "sibling", profile_name="luna_query_generator"
    )
    if effective_luna.get("model") != "gpt-6-luna" or not effective_luna.get("base_url"):
        raise RuntimeError(f"luna_profile_drift:{effective_luna.get('model')}:{bool(effective_luna.get('base_url'))}")
    run_config = {
        "kind": "v25_shared_g_anchor_replacement_7_config",
        "status": "fixed_before_new_luna_retrieval_or_victim_calls",
        "development_only": True,
        "protocol_parent": "pcv-mia-v25",
        "method": "three_local_facts_plus_one_shared_remote_target",
        "source_unit": "source_document",
        "source_count": SOURCE_COUNT,
        "dataset": DATASET,
        "group_counts": dict(Counter(row["group"] for row in rows)),
        "source_plan_sha256": sha256_file(SOURCE_PLAN),
        "source_manifest_sha256": sha256_file(SOURCE_MANIFEST),
        "models": {
            "query_generator_configured": "gpt-6-luna",
            "query_generator_effective": effective_luna.get("model"),
            "victim_configured": PILOT.V25_CONFIG["runtime"]["concrete_model"],
            "retriever": f"{PILOT.V25_CONFIG['runtime']['retrieval']['retriever_id']}@{PILOT.V25_CONFIG['runtime']['retrieval']['revision']}",
        },
        "generation": {
            "prompt_sha256": sha256_text(PILOT.GENERATION_PROMPT),
            "runner_sha256": sha256_file(Path(__file__)),
            "pilot_runner_sha256": sha256_file(PILOT_PATH),
            "max_initial_calls": SOURCE_COUNT,
            "repair_mode": "predefined_retry_failed_only",
        },
        "query_protocol": {
            "initial": 3,
            "anchored_followup": 3,
            "no_anchor_control": 3,
            "total_frozen_queries_per_passed_source": QUERIES_PER_SOURCE,
            "remote_region": "preferred_different_region_not_hard_gate",
        },
        "downstream_calls": {"retriever": 0, "victim": 0},
        "seed": SEED,
    }
    write_json(run_config, RUN_CONFIG)
    print(json.dumps({
        "stage": "prepare",
        "sources": SOURCE_COUNT,
        "groups": dict(Counter(row["group"] for row in rows)),
        "source_keys": _source_keys(rows),
        "source_order_ranks": [row["source_order_rank"] for row in rows],
        "historical_source_key_count": selection_meta["historical_source_key_count"],
        "luna_model": effective_luna.get("model"),
        "external_calls": 0,
    }, ensure_ascii=False))


def generate(max_new: int, retry_failed: bool) -> None:
    _install_generator_context()
    if not SOURCE_PLAN.is_file() or not SOURCE_MANIFEST.is_file() or not RUN_CONFIG.is_file():
        raise RuntimeError("prepare_required")
    if max_new < 1 or max_new > SOURCE_COUNT:
        raise ValueError(f"max_new_must_be_between_1_and_{SOURCE_COUNT}")
    PILOT.generate(max_new, retry_failed=retry_failed)


def report() -> None:
    _install_generator_context()
    rows = _load_source_rows()
    generated = list(read_jsonl(GENERATION)) if GENERATION.is_file() else []
    by_key = {str(row.get("source_key")): row for row in generated}
    if len(by_key) != len(generated):
        raise RuntimeError("generation_source_collision")
    statuses = Counter(str(by_key.get(key, {}).get("status", "missing")) for key in _source_keys(rows))
    passed = [by_key[key] for key in _source_keys(rows) if by_key.get(key, {}).get("status") == "passed"]
    reasons = Counter(reason for row in generated for reason in (row.get("quality_reasons") or []))
    by_group: dict[str, dict[str, Any]] = {}
    for group in GROUP_QUOTAS:
        keys = [str(row["source_key"]) for row in rows if str(row["group"]) == group]
        group_passed = sum(by_key.get(key, {}).get("status") == "passed" for key in keys)
        by_group[group] = {
            "sources": len(keys),
            "passed_sources": group_passed,
            "source_pass_rate": group_passed / len(keys) if keys else None,
            "frozen_queries_from_passed_sources": group_passed * QUERIES_PER_SOURCE,
        }
    result = {
        "kind": "v25_shared_g_anchor_replacement_7_construction_report",
        "status": "development_only",
        "no_formal_test_claim": True,
        "source_unit": "source_document",
        "source_count": len(rows),
        "dataset": DATASET,
        "group_counts": dict(Counter(str(row["group"]) for row in rows)),
        "generation": {
            "observed_sources": len(generated),
            "statuses": dict(statuses),
            "quality_reasons": dict(reasons),
            "passed_sources": len(passed),
            "source_pass_rate": len(passed) / len(rows) if rows else None,
            "frozen_query_capacity_if_all_pass": len(rows) * QUERIES_PER_SOURCE,
            "frozen_queries_from_passed_sources": len(passed) * QUERIES_PER_SOURCE,
            "initial_query_capacity_from_passed_sources": len(passed) * 3,
            "anchored_followup_capacity_from_passed_sources": len(passed) * 3,
            "no_anchor_capacity_from_passed_sources": len(passed) * 3,
        },
        "by_group": by_group,
        "selected_sources": [
            {
                "source_key": row["source_key"],
                "group": row["group"],
                "source_order_rank": row["source_order_rank"],
            }
            for row in rows
        ],
        "artifacts": {
            "source_plan_sha256": sha256_file(SOURCE_PLAN),
            "source_manifest_sha256": sha256_file(SOURCE_MANIFEST),
            "run_config_sha256": sha256_file(RUN_CONFIG),
            "generation_sha256": sha256_file(GENERATION) if GENERATION.is_file() else None,
        },
        "interpretation": {
            "construction_definition": "A source contributes nine frozen queries only when shared-G generation status is passed by the structural/source-span validator.",
            "semantic_limitation": "The shared-G structural validator and assistant review do not establish independent human semantic agreement or victim answerability.",
            "downstream_not_run": True,
            "replacement_is_separate_identity": True,
        },
    }
    write_json(result, CONSTRUCTION_REPORT)
    print(json.dumps({
        "stage": "report",
        "observed_sources": len(generated),
        "statuses": dict(statuses),
        "passed_sources": len(passed),
        "frozen_queries_from_passed_sources": len(passed) * QUERIES_PER_SOURCE,
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--generate", action="store_true")
    modes.add_argument("--retry-failed", action="store_true")
    modes.add_argument("--report", action="store_true")
    parser.add_argument("--max-new", type=int, default=0)
    args = parser.parse_args()
    if args.generate or args.retry_failed:
        if args.max_new < 1 or args.max_new > SOURCE_COUNT:
            parser.error(f"external calls require --max-new between 1 and {SOURCE_COUNT}")
    elif args.max_new:
        parser.error("--max-new only applies to external calls")
    if args.prepare:
        prepare()
    elif args.generate:
        generate(args.max_new, retry_failed=False)
    elif args.retry_failed:
        generate(args.max_new, retry_failed=True)
    else:
        report()


if __name__ == "__main__":
    main()
