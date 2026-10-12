"""Construct a 100-source shared-G development cohort.

This runner reuses the already fixed 50-member/50-non-member source frame from
V25's earlier source-plan artifact, but regenerates queries with the shared
remote-target protocol.  It intentionally does not run retrieval or victim
calls.  The r3 six-source runner remains unchanged so its artifact identity is
preserved.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.hash import sha256_file, sha256_obj, sha256_text  # noqa: E402
from src.utils.io import read_jsonl, write_json, write_jsonl_atomic  # noqa: E402


PILOT_PATH = ROOT / "scripts/95_run_v25_shared_g_pilot.py"
PILOT_SPEC = importlib.util.spec_from_file_location("v25_shared_g_pilot", PILOT_PATH)
if PILOT_SPEC is None or PILOT_SPEC.loader is None:
    raise RuntimeError("shared_g_pilot_import_spec_unavailable")
PILOT = importlib.util.module_from_spec(PILOT_SPEC)
PILOT_SPEC.loader.exec_module(PILOT)

INPUT_DIR = ROOT / "artifacts/v25/development/gated_followup_two_phase_joint_100sample_50plus50_20261002"
INPUT_SOURCE_PLAN = INPUT_DIR / "source_plan.json"
INPUT_SOURCE_MANIFEST = INPUT_DIR / "source_manifest.jsonl"
OUT = ROOT / "artifacts/v25/development/shared_g_anchor_cohort_100sample_50plus50_20261002"
SOURCE_PLAN = OUT / "source_plan.json"
SOURCE_MANIFEST = OUT / "source_manifest.jsonl"
RUN_CONFIG = OUT / "run_config.json"
GENERATION = OUT / "generation.jsonl"
CONSTRUCTION_REPORT = OUT / "construction_report.json"

R3_MANIFEST = ROOT / "artifacts/v25/development/shared_g_anchor_pilot_r3_20261002/source_manifest.jsonl"
SEED = "v25-shared-g-anchor-cohort-100sample-50plus50-20261002"
SOURCE_COUNT = 100
PER_GROUP = 50
QUERIES_PER_SOURCE = 9


def _patch_pilot_paths() -> None:
    """Point the reusable shared-G generator at this cohort's artifact paths."""
    PILOT.OUT = OUT
    PILOT.SOURCE_PLAN = SOURCE_PLAN
    PILOT.SOURCE_MANIFEST = SOURCE_MANIFEST
    PILOT.RUN_CONFIG = RUN_CONFIG
    PILOT.GENERATION = GENERATION


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    return list(read_jsonl(path)) if path.is_file() else []


def _source_keys(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row.get("source_key")) for row in rows]


def _validate_input_frame() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not INPUT_SOURCE_PLAN.is_file() or not INPUT_SOURCE_MANIFEST.is_file():
        raise FileNotFoundError("fixed_100_source_frame_missing")
    plan = json.loads(INPUT_SOURCE_PLAN.read_text(encoding="utf-8"))
    rows = _read_manifest(INPUT_SOURCE_MANIFEST)
    if plan.get("status") != "selected_before_new_luna_retrieval_or_victim_calls":
        raise RuntimeError("fixed_100_source_frame_status_invalid")
    if plan.get("membership_labels_read") is not False:
        raise RuntimeError("fixed_100_source_frame_not_membership_blind")
    if plan.get("source_count") != SOURCE_COUNT or len(rows) != SOURCE_COUNT:
        raise RuntimeError("fixed_100_source_frame_count_drift")
    if len(set(_source_keys(rows))) != SOURCE_COUNT:
        raise RuntimeError("fixed_100_source_frame_source_collision")
    groups = Counter(str(row.get("group")) for row in rows)
    if groups != Counter({"KB_Member": PER_GROUP, "True_Non_Member": PER_GROUP}):
        raise RuntimeError(f"fixed_100_source_frame_group_drift:{dict(groups)}")
    if plan.get("source_keys_sha256") != sha256_obj(_source_keys(rows)):
        raise RuntimeError("fixed_100_source_frame_hash_drift")
    if not R3_MANIFEST.is_file():
        raise FileNotFoundError("r3_manifest_missing_for_overlap_check")
    r3_rows = _read_manifest(R3_MANIFEST)
    overlap = sorted(set(_source_keys(rows)) & set(_source_keys(r3_rows)))
    if overlap:
        raise RuntimeError(f"fixed_100_source_frame_overlaps_r3:{overlap}")
    for row in rows:
        source_text = PILOT._source_text(row)
        if sha256_text(source_text) != str(row.get("source_hash")):
            raise RuntimeError(f"source_text_hash_drift:{row.get('source_key')}")
    return plan, rows


def _load_source_rows() -> list[dict[str, Any]]:
    """Load and validate the 100-source manifest for the reused generator."""
    if not SOURCE_PLAN.is_file() or not SOURCE_MANIFEST.is_file():
        raise RuntimeError("prepare_required")
    plan = json.loads(SOURCE_PLAN.read_text(encoding="utf-8"))
    rows = _read_manifest(SOURCE_MANIFEST)
    if len(rows) != SOURCE_COUNT:
        raise RuntimeError("shared_g_cohort_manifest_count_drift")
    if Counter(str(row.get("group")) for row in rows) != Counter({"KB_Member": PER_GROUP, "True_Non_Member": PER_GROUP}):
        raise RuntimeError("shared_g_cohort_group_balance_drift")
    if len(set(_source_keys(rows))) != SOURCE_COUNT:
        raise RuntimeError("shared_g_cohort_source_collision")
    if plan.get("source_keys_sha256") != sha256_obj(_source_keys(rows)):
        raise RuntimeError("shared_g_cohort_source_keys_hash_drift")
    return rows


def prepare() -> None:
    input_plan, rows = _validate_input_frame()
    OUT.mkdir(parents=True, exist_ok=True)
    output_plan = dict(input_plan)
    output_plan.update({
        "kind": "v25_shared_g_anchor_cohort_source_plan",
        "protocol": "three_local_facts_plus_one_shared_remote_target",
        "input_source_plan": str(INPUT_SOURCE_PLAN.relative_to(ROOT)),
        "input_source_plan_sha256": sha256_file(INPUT_SOURCE_PLAN),
        "r3_overlap_checked": True,
        "r3_manifest_sha256": sha256_file(R3_MANIFEST),
        "source_manifest_sha256": sha256_file(INPUT_SOURCE_MANIFEST),
        "seed": SEED,
    })
    write_json(output_plan, SOURCE_PLAN)
    write_jsonl_atomic(rows, SOURCE_MANIFEST)
    profiles = PILOT.load_llm_profiles({"llm_profiles_path": PILOT.V25_CONFIG["runtime"]["llm_profiles_path"]})
    effective_luna = PILOT.resolve_effective_llm_profile(
        profiles, "sibling", profile_name="luna_query_generator"
    )
    if effective_luna.get("model") != "gpt-6-luna" or not effective_luna.get("base_url"):
        raise RuntimeError(f"luna_profile_drift:{effective_luna.get('model')}:{bool(effective_luna.get('base_url'))}")
    config = {
        "kind": "v25_shared_g_anchor_cohort_100sample_config",
        "status": "fixed_before_new_luna_retrieval_or_victim_calls",
        "development_only": True,
        "protocol_parent": "pcv-mia-v25",
        "method": "three_local_facts_plus_one_shared_remote_target",
        "source_unit": "source_document",
        "source_count": SOURCE_COUNT,
        "group_counts": {"KB_Member": PER_GROUP, "True_Non_Member": PER_GROUP},
        "source_plan_sha256": sha256_file(SOURCE_PLAN),
        "source_manifest_sha256": sha256_file(SOURCE_MANIFEST),
        "input_source_plan_sha256": sha256_file(INPUT_SOURCE_PLAN),
        "input_sha256": input_plan.get("input_sha256", {}),
        "models": {
            "query_generator_configured": "gpt-6-luna",
            "query_generator_effective": effective_luna.get("model"),
            "victim_configured": PILOT.V25_CONFIG["runtime"]["concrete_model"],
            "retriever": f"{PILOT.V25_CONFIG['runtime']['retrieval']['retriever_id']}@{PILOT.V25_CONFIG['runtime']['retrieval']['revision']}",
        },
        "generation": {
            "prompt_sha256": sha256_text(PILOT.GENERATION_PROMPT),
            "runner_sha256": sha256_file(PILOT_PATH),
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
    write_json(config, RUN_CONFIG)
    print(json.dumps({
        "stage": "prepare",
        "sources": SOURCE_COUNT,
        "groups": dict(Counter(row["group"] for row in rows)),
        "datasets": dict(Counter(row["dataset"] for row in rows)),
        "luna_model": effective_luna.get("model"),
        "external_calls": 0,
    }, ensure_ascii=False))


def _install_generator_context() -> None:
    _patch_pilot_paths()
    PILOT._load_source_rows = _load_source_rows


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
    reasons = Counter(
        reason for row in generated for reason in (row.get("quality_reasons") or [])
    )
    by_group: dict[str, dict[str, Any]] = {}
    by_dataset: dict[str, dict[str, Any]] = {}
    for dimension, values in (
        ("group", sorted({str(row["group"]) for row in rows})),
        ("dataset", sorted({str(row["dataset"]) for row in rows})),
    ):
        target = by_group if dimension == "group" else by_dataset
        for value in values:
            keys = [str(row["source_key"]) for row in rows if str(row[dimension]) == value]
            source_passed = sum(by_key.get(key, {}).get("status") == "passed" for key in keys)
            target[value] = {
                "sources": len(keys),
                "passed_sources": source_passed,
                "source_pass_rate": source_passed / len(keys) if keys else None,
                "frozen_queries_if_passed": source_passed * QUERIES_PER_SOURCE,
                "frozen_query_capacity": len(keys) * QUERIES_PER_SOURCE,
            }
    result = {
        "kind": "v25_shared_g_anchor_cohort_100sample_construction_report",
        "status": "development_only",
        "no_formal_test_claim": True,
        "source_unit": "source_document",
        "source_count": len(rows),
        "group_counts": dict(Counter(str(row["group"]) for row in rows)),
        "dataset_counts": dict(Counter(str(row["dataset"]) for row in rows)),
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
        "by_dataset": by_dataset,
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
