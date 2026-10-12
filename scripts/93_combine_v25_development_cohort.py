"""Combine compatible v25 generation batches and register legacy hard controls."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.hash import sha256_file  # noqa: E402
from src.utils.io import read_jsonl, write_json, write_jsonl_atomic  # noqa: E402


def _load_v25() -> Any:
    path = ROOT / "scripts/92_run_v25_gated_followup_pilot.py"
    spec = importlib.util.spec_from_file_location("v25_combine_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v25_runner_import_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v25 = _load_v25()
OUT = ROOT / "artifacts/v25/development/gated_followup_combined_20260929"
LEGACY_PLAN = ROOT / "artifacts/v24/development/near_clean_far_expansion_20260927/plan.json"
LEGACY_REPORT = ROOT / "artifacts/v24/development/near_clean_far_expansion_20260927/report.json"

SOURCE_PLANS = [
    ROOT / "artifacts/v25/development/gated_followup_pilot_expand6_20260929/source_plan.json",
    ROOT / "artifacts/v25/development/gated_followup_pilot_expand6_r2_20260929/source_plan.json",
]
GENERATIONS = [plan.parent / "query_generation.jsonl" for plan in SOURCE_PLANS]

# Current V25 expansion mode uses only V25 source/query/review artifacts. The
# older default mode below remains available for historical compatibility.
CURRENT_COHORT = ROOT / "artifacts/v25/development/gated_followup_cross_batch_cohort_r1_20261001"
EXPANSION_BATCHES = [
    ROOT / "artifacts/v25/development/gated_followup_two_phase_joint_8sample_r8_20261001",
    ROOT / "artifacts/v25/development/gated_followup_two_phase_joint_8sample_r9_20261001",
]
EXPANDED_OUT = ROOT / "artifacts/v25/development/gated_followup_cross_batch_cohort_r2_20261001"
R3_CURRENT_COHORT = ROOT / "artifacts/v25/development/gated_followup_cross_batch_cohort_r2_20261001"
R3_EXPANSION_BATCHES = [
    ROOT / "artifacts/v25/development/gated_followup_two_phase_joint_12sample_r10_20261001",
]
R3_EXPANDED_OUT = ROOT / "artifacts/v25/development/gated_followup_cross_batch_cohort_r3_20261001"

# One balanced pair per dataset keeps all v25 calls within the remaining pilot budget.
KEEP = {
    "nfcorpus": {"KB_Member", "True_Non_Member"},
    "scidocs": {"KB_Member", "True_Non_Member"},
    "trec-covid": {"KB_Member", "True_Non_Member"},
}


def _load_rows(path: Path) -> list[dict[str, Any]]:
    return list(read_jsonl(path)) if path.suffix == ".jsonl" else json.loads(path.read_text(encoding="utf-8"))


def _legacy_controls() -> list[dict[str, Any]]:
    payload = json.loads(LEGACY_PLAN.read_text(encoding="utf-8"))
    if not isinstance(payload.get("cases"), list):
        raise RuntimeError("legacy_plan_schema")
    rows = [
        {
            "source_key": row["source_key"],
            "dataset": row["dataset"],
            "group": row["group"],
            "cohort": row.get("cohort"),
            "legacy_protocol": "near_clean_far_expansion_A_B_joint",
            "legacy_plan_sha256": sha256_file(LEGACY_PLAN),
            "legacy_report_sha256": sha256_file(LEGACY_REPORT),
            "source_hash": row["source_hash"],
            "a_entity": row.get("a_entity"),
            "b_entity": row.get("b_entity"),
            "query_ids": row.get("query_ids", {}),
        }
        for row in payload["cases"]
        if row.get("group") == "True_Non_Member"
    ]
    if len(rows) != 9 or len({row["source_key"] for row in rows}) != 9:
        raise RuntimeError("legacy_hard_control_count_drift")
    return rows


def _load_reviewed_batch(
    directory: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    """Load one V25 batch after rechecking its source/generation/review hashes."""
    v25._set_output_dir(directory.resolve())
    plan = json.loads(v25.PLAN.read_text(encoding="utf-8"))
    sources, _ = v25._fixed_inputs(allow_report_runtime_drift=True)
    accepted = v25._reviewed_generation(sources)
    review = json.loads(v25.QUERY_REVIEW.read_text(encoding="utf-8"))
    raw_generation = {row["source_key"]: row for row in read_jsonl(v25.GENERATION)}
    return plan, accepted, review, raw_generation


def combine_expanded(
    current_cohort: Path = CURRENT_COHORT,
    expansion_batches: list[Path] | None = None,
    expanded_out: Path = EXPANDED_OUT,
) -> None:
    """Build the current V25 cross-batch cohort from complete accepted pairs."""
    batches = [current_cohort, *(expansion_batches or EXPANSION_BATCHES)]
    source_plan_inputs: list[str] = []
    generation_inputs: list[str] = []
    review_inputs: list[str] = []
    pairs: list[dict[str, Any]] = []
    generation_by_key: dict[str, dict[str, Any]] = {}
    review_by_key: dict[str, dict[str, Any]] = {}
    source_by_key: dict[str, dict[str, Any]] = {}

    for directory in batches:
        plan, accepted, review, raw_generation = _load_reviewed_batch(directory)
        source_plan_path = directory / "source_plan.json"
        generation_path = directory / "query_generation.jsonl"
        review_path = directory / "query_review.json"
        source_plan_inputs.append(sha256_file(source_plan_path))
        generation_inputs.append(sha256_file(generation_path))
        review_inputs.append(sha256_file(review_path))
        plan_sources = {
            source["source_key"]: source
            for pair in plan["pairs"]
            for source in pair["sources"]
        }
        for pair in plan["pairs"]:
            keys = [source["source_key"] for source in pair["sources"]]
            if not all(key in accepted for key in keys):
                continue
            if any(key in source_by_key for key in keys):
                raise RuntimeError("expanded_v25_source_collision")
            selected_sources = [plan_sources[key] for key in keys]
            dataset = str(pair["dataset"])
            pairs.append({
                "dataset": dataset,
                "pair_index": len(pairs) + 1,
                "selection": "complete_accepted_pair_from_fixed_v25_batch",
                "source_plan_sha256": sha256_file(source_plan_path),
                "sources": selected_sources,
            })
            for key in keys:
                source_by_key[key] = plan_sources[key]
                generation_by_key[key] = raw_generation[key]
                review_by_key[key] = review["sources"][key]

    if not pairs or len(source_by_key) != 2 * len(pairs):
        raise RuntimeError("expanded_v25_cohort_empty_or_unpaired")
    if len({source["source_hash"] for source in source_by_key.values()}) != len(source_by_key):
        raise RuntimeError("expanded_v25_source_hash_collision")
    if not {pair["dataset"] for pair in pairs} >= set(v25.DATASETS):
        raise RuntimeError("expanded_v25_dataset_pair_missing")

    ordered_sources = [source for pair in pairs for source in pair["sources"]]
    ordered_keys = [source["source_key"] for source in ordered_sources]
    generation_rows = [generation_by_key[key] for key in ordered_keys]
    plan = {
        "kind": "v25_expanded_cross_batch_development_cohort",
        "status": "fixed_before_new_retrieval_or_victim_calls",
        "development_only": True,
        "source_unit": "source_document",
        "selection": "complete_accepted_member_nonmember_pairs_only",
        "source_plan_inputs": source_plan_inputs,
        "generation_inputs": generation_inputs,
        "review_inputs": review_inputs,
        "input_sha256": v25._input_hashes(),
        "pairs": pairs,
        "source_count": len(ordered_sources),
        "pair_counts": {dataset: sum(pair["dataset"] == dataset for pair in pairs) for dataset in v25.DATASETS},
        "source_keys_sha256": v25.sha256_obj(ordered_keys),
    }
    v25._sources(plan)
    out = expanded_out.resolve()
    v25._set_output_dir(out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(plan, v25.PLAN)
    write_jsonl_atomic(ordered_sources, out / "source_manifest.jsonl")
    write_json({
        "kind": "v25_expanded_source_exclusive_split",
        "source_plan_sha256": sha256_file(v25.PLAN),
        "source_count": len(ordered_sources),
        "pair_counts": plan["pair_counts"],
        "membership_labels_read": False,
        "source_unit": "source_document",
    }, out / "source_split.json")
    write_jsonl_atomic(generation_rows, v25.GENERATION)
    review = {
        "kind": "v25_expanded_cross_batch_nonblind_development_review",
        "status": "development_only_expanded_before_new_retrieval_or_victim",
        "reviewer": "assistant_nonblind_development_review",
        "semantic_review_performed": True,
        "blind": False,
        "source_plan_sha256": sha256_file(v25.PLAN),
        "generation_sha256": sha256_file(v25.GENERATION),
        "generation_runner_sha256": v25.sha256_file(Path(v25.__file__)),
        "source_plan_inputs": source_plan_inputs,
        "generation_inputs": generation_inputs,
        "review_inputs": review_inputs,
        "sources": review_by_key,
        "accepted_sources": len(ordered_sources),
        "structural_passed_sources": len(ordered_sources),
        "accepted_by_dataset_and_group": {
            dataset: {
                group: sum(source["dataset"] == dataset and source["group"] == group for source in ordered_sources)
                for group in v25.GROUPS
            }
            for dataset in v25.DATASETS
        },
        "matched_accepted_member_nonmember_same_dataset": True,
        "matched_datasets": sorted({pair["dataset"] for pair in pairs}),
        "formal_or_victim_ready": False,
        "interpretation_limit": "Assistant nonblind development review only; not independent human annotation, not a semantic gold set, and not a formal result. Retriever, victim, GPU, and formal execution remain outside this combine step.",
    }
    write_json(review, v25.QUERY_REVIEW)
    v25._write_run_config(plan)
    config = json.loads(v25.CONFIG.read_text(encoding="utf-8"))
    config.update({
        "cohort_kind": "expanded_v25_cross_batch_complete_accepted_pairs",
        "cohort_source_plan_inputs": source_plan_inputs,
        "cohort_generation_inputs": generation_inputs,
        "cohort_review_inputs": review_inputs,
        "new_luna_calls_for_cohort": 0,
        "new_victim_calls_for_cohort": 0,
    })
    write_json(config, v25.CONFIG)
    print(json.dumps({
        "stage": "combine_expanded",
        "v25_sources": len(ordered_sources),
        "v25_pairs": len(pairs),
        "pair_counts": plan["pair_counts"],
        "new_luna_calls": 0,
        "new_victim_calls": 0,
        "source_plan_sha256": sha256_file(v25.PLAN),
        "generation_sha256": sha256_file(v25.GENERATION),
    }))


def main() -> None:
    out = OUT.resolve()
    v25._set_output_dir(out)
    source_rows: list[dict[str, Any]] = []
    generation_rows: list[dict[str, Any]] = []
    for plan_path, generation_path in zip(SOURCE_PLANS, GENERATIONS):
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        generation = {row["source_key"]: row for row in _load_rows(generation_path)}
        for pair in plan["pairs"]:
            by_group = {row["group"]: row for row in pair["sources"]}
            if set(by_group) != set(v25.GROUPS):
                raise RuntimeError("source_plan_group_drift")
            if pair["dataset"] not in KEEP:
                continue
            for group in v25.GROUPS:
                source = by_group[group]
                if source["group"] not in KEEP[pair["dataset"]]:
                    continue
                attempt = generation.get(source["source_key"])
                if attempt is None or attempt.get("status") != "passed":
                    continue
                source_rows.append(source)
                generation_rows.append(attempt)

    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for source in source_rows:
        key = (source["dataset"], source["group"])
        if key in selected:
            continue
        selected[key] = source
    source_rows = [selected[key] for key in sorted(selected)]
    if len(source_rows) != 6 or {row["dataset"] for row in source_rows} != set(v25.DATASETS):
        raise RuntimeError("combined_v25_cohort_incomplete")
    if {row["group"] for row in source_rows} != set(v25.GROUPS):
        raise RuntimeError("combined_v25_group_incomplete")
    if len({row["source_key"] for row in source_rows}) != 6:
        raise RuntimeError("combined_v25_source_collision")
    source_keys = {row["source_key"] for row in source_rows}
    generation_by_key = {row["source_key"]: row for row in generation_rows}
    if not source_keys <= set(generation_by_key):
        raise RuntimeError("combined_v25_generation_incomplete")
    generation_rows = [generation_by_key[key] for key in sorted(source_keys)]
    generation_by_key = {row["source_key"]: row for row in generation_rows}

    pairs = []
    for dataset in v25.DATASETS:
        pairs.append({
            "dataset": dataset,
            "pair_index": len(pairs) + 1,
            "selection": "compatible_passed_generation_from_two_development_batches",
            "sources": [row for row in source_rows if row["dataset"] == dataset],
        })
    plan = {
        "kind": "v25_combined_development_cohort",
        "status": "fixed_before_new_retrieval_or_victim_calls",
        "development_only": True,
        "source_unit": "source_document",
        "source_plans": [sha256_file(path) for path in SOURCE_PLANS],
        "input_sha256": v25._input_hashes(),
        "pairs": pairs,
        "legacy_hard_nonmember_controls": _legacy_controls(),
        "legacy_compatibility": "diagnostic_only; legacy A/B or three-slot protocol is not merged into v25 query statistics",
    }
    v25._sources(plan)
    out.mkdir(parents=True, exist_ok=True)
    write_json(plan, v25.PLAN)
    write_jsonl_atomic(generation_rows, v25.GENERATION)
    review = {
        "kind": "v25_combined_nonblind_development_review",
        "status": "fixed_before_retrieval_or_victim",
        "semantic_review": "assistant_nonblind_development_review; no question or answer edits",
        "generation_sha256": v25.sha256_file(v25.GENERATION),
        "sources": {
            source["source_key"]: {
                "accepted": True,
                "reason": "structurally passed in source batch; combined without editing facts or questions",
                "aliases": {fact["slot"]: [] for rows in attempt["records"].values() for fact in rows},
            }
            for source in source_rows
            for attempt in [generation_by_key[source["source_key"]]]
        },
        "legacy_controls": "listed separately and excluded from v25 query_plan.jsonl",
    }
    write_json(review, v25.QUERY_REVIEW)
    v25._write_run_config(plan)
    config = json.loads(v25.CONFIG.read_text(encoding="utf-8"))
    config["cohort_kind"] = "combined_v25_passed_pairs_plus_legacy_hard_controls"
    config["legacy_control_plan_sha256"] = sha256_file(LEGACY_PLAN)
    config["legacy_control_report_sha256"] = sha256_file(LEGACY_REPORT)
    config["maximum_calls"] = {"luna": 0, "victim": 36}
    write_json(config, v25.CONFIG)
    print(json.dumps({
        "stage": "combine",
        "v25_sources": len(source_rows),
        "v25_pairs": len(pairs),
        "legacy_hard_controls": 9,
        "new_luna_calls": 0,
        "new_victim_calls": 0,
        "source_plan_sha256": sha256_file(v25.PLAN),
        "generation_sha256": sha256_file(v25.GENERATION),
    }))


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--expanded":
        combine_expanded()
    elif len(sys.argv) == 2 and sys.argv[1] == "--expanded-r3":
        combine_expanded(R3_CURRENT_COHORT, R3_EXPANSION_BATCHES, R3_EXPANDED_OUT)
    else:
        main()
