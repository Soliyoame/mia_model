"""Run the query-usable 100-source shared-G development cohort.

This runner combines only sources that passed the independently frozen shared-G
construction validator, freezes 900 queries (100 sources x 9 arms), and then
reuses the shared-G pilot retrieval/victim implementation.  The combined
identity is separate from every construction batch; no source is regenerated
here and no query is changed after retrieval or victim responses exist.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.metrics import bootstrap_auc_ci, summarize_membership_scores  # noqa: E402
from src.utils.hash import sha256_file, sha256_obj, sha256_text  # noqa: E402
from src.utils.io import read_jsonl, write_json, write_jsonl_atomic  # noqa: E402


PILOT_PATH = ROOT / "scripts/95_run_v25_shared_g_pilot.py"
PILOT_SPEC = importlib.util.spec_from_file_location("v25_shared_g_combined_pilot", PILOT_PATH)
if PILOT_SPEC is None or PILOT_SPEC.loader is None:
    raise RuntimeError("shared_g_pilot_import_spec_unavailable")
PILOT = importlib.util.module_from_spec(PILOT_SPEC)
PILOT_SPEC.loader.exec_module(PILOT)

OUT = ROOT / "artifacts/v25/development/shared_g_anchor_cohort_query_usable_100sample_50plus50_20261002"
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

BATCH_DIRS = [
    ROOT / "artifacts/v25/development/shared_g_anchor_cohort_100sample_50plus50_20261002",
    ROOT / "artifacts/v25/development/shared_g_anchor_replacement_7_20261002",
    ROOT / "artifacts/v25/development/shared_g_anchor_replacement_2_20261002",
    ROOT / "artifacts/v25/development/shared_g_anchor_replacement_1_nonmember_20261002",
]
SEED = "v25-shared-g-anchor-query-usable-100sample-50plus50-20261002"
EXPECTED_SOURCE_COUNT = 100
EXPECTED_QUERY_COUNT = 900
GROUPS = ("KB_Member", "True_Non_Member")
DATASETS = ("nfcorpus", "scidocs", "trec-covid")
DATASET_ORDER = {name: index for index, name in enumerate(DATASETS)}


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    return list(read_jsonl(path)) if path.is_file() else []


def _source_keys(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row["source_key"]) for row in rows]


def _batch_rows(batch: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest_path = batch / "source_manifest.jsonl"
    generation_path = batch / "generation.jsonl"
    if not manifest_path.is_file() or not generation_path.is_file():
        raise FileNotFoundError(f"batch_artifact_missing:{batch}")
    manifest = _read_manifest(manifest_path)
    generation = _read_manifest(generation_path)
    by_key = {str(row["source_key"]): row for row in generation}
    if len(by_key) != len(generation):
        raise RuntimeError(f"generation_source_collision:{batch}")
    passed_sources: list[dict[str, Any]] = []
    passed_generation: list[dict[str, Any]] = []
    for source in manifest:
        key = str(source["source_key"])
        attempt = by_key.get(key)
        if attempt is None:
            raise RuntimeError(f"generation_missing:{batch}:{key}")
        if attempt.get("source_hash") != source.get("source_hash"):
            raise RuntimeError(f"generation_source_hash_drift:{batch}:{key}")
        if attempt.get("status") != "passed":
            continue
        records = attempt.get("records") or {}
        if not all(
            isinstance(records.get(name), list)
            for name in ("initial_facts", "anchored_followups", "no_anchor_followups")
        ) or not isinstance(records.get("remote_target"), dict):
            raise RuntimeError(f"passed_generation_record_incomplete:{batch}:{key}")
        passed_sources.append(source)
        passed_generation.append(attempt)
    return passed_sources, passed_generation


def _sort_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            DATASET_ORDER.get(str(row.get("dataset")), 999),
            int(str(row.get("source_order_rank", "0"))),
            str(row.get("source_key")),
        ),
    )


def _validate_combined_sources(rows: list[dict[str, Any]], generation: list[dict[str, Any]]) -> None:
    if len(rows) != EXPECTED_SOURCE_COUNT:
        raise RuntimeError(f"combined_source_count:{len(rows)}")
    if len(generation) != EXPECTED_SOURCE_COUNT:
        raise RuntimeError(f"combined_generation_count:{len(generation)}")
    if len(set(_source_keys(rows))) != EXPECTED_SOURCE_COUNT:
        raise RuntimeError("combined_source_collision")
    groups = Counter(str(row.get("group")) for row in rows)
    if groups != Counter({"KB_Member": 50, "True_Non_Member": 50}):
        raise RuntimeError(f"combined_group_balance:{dict(groups)}")
    datasets = Counter(str(row.get("dataset")) for row in rows)
    if datasets != Counter({"nfcorpus": 34, "scidocs": 34, "trec-covid": 32}):
        raise RuntimeError(f"combined_dataset_balance:{dict(datasets)}")
    generation_keys = {str(row["source_key"]) for row in generation}
    if generation_keys != set(_source_keys(rows)):
        raise RuntimeError("combined_generation_source_set_drift")
    for row in rows:
        source_text = PILOT._source_text(row)
        if sha256_text(source_text) != str(row.get("source_hash")):
            raise RuntimeError(f"combined_source_hash_drift:{row.get('source_key')}")


def _load_combined() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not SOURCE_MANIFEST.is_file() or not GENERATION.is_file():
        raise RuntimeError("prepare_required")
    rows = _read_manifest(SOURCE_MANIFEST)
    generation = _read_manifest(GENERATION)
    _validate_combined_sources(rows, generation)
    return rows, generation


def _patch_pilot_paths() -> None:
    PILOT.OUT = OUT
    PILOT.SOURCE_PLAN = SOURCE_PLAN
    PILOT.SOURCE_MANIFEST = SOURCE_MANIFEST
    PILOT.RUN_CONFIG = RUN_CONFIG
    PILOT.GENERATION = GENERATION
    PILOT.QUERY_PLAN = QUERY_PLAN
    PILOT.RETRIEVAL = RETRIEVAL
    PILOT.INITIAL_RESPONSES = INITIAL_RESPONSES
    PILOT.FOLLOWUP_RESPONSES = FOLLOWUP_RESPONSES
    PILOT.REPORT = REPORT
    PILOT.SEED = SEED


def _install_pilot_context() -> None:
    _patch_pilot_paths()

    def fixed_queries() -> list[dict[str, Any]]:
        rows = _read_manifest(QUERY_PLAN)
        if len(rows) != EXPECTED_QUERY_COUNT or len({str(row["query_id"]) for row in rows}) != EXPECTED_QUERY_COUNT:
            raise RuntimeError("combined_query_plan_incomplete")
        return rows

    def retrieval_map() -> dict[str, dict[str, Any]]:
        rows = _read_manifest(RETRIEVAL)
        result = {str(row["query_id"]): row for row in rows}
        if len(result) != EXPECTED_QUERY_COUNT:
            raise RuntimeError("combined_retrieval_incomplete")
        return result

    PILOT._load_source_rows = lambda: _load_combined()[0]
    PILOT._fixed_queries = fixed_queries
    PILOT._retrieval_map = retrieval_map


def prepare() -> None:
    source_rows: list[dict[str, Any]] = []
    generation_rows: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for batch in BATCH_DIRS:
        batch_sources, batch_generation = _batch_rows(batch)
        source_rows.extend(batch_sources)
        generation_rows.extend(batch_generation)
        provenance.append({
            "path": str(batch.relative_to(ROOT)),
            "source_manifest_sha256": sha256_file(batch / "source_manifest.jsonl"),
            "generation_sha256": sha256_file(batch / "generation.jsonl"),
            "passed_sources": len(batch_sources),
        })
    by_key = {str(row["source_key"]): row for row in source_rows}
    gen_by_key = {str(row["source_key"]): row for row in generation_rows}
    if len(by_key) != len(source_rows) or len(gen_by_key) != len(generation_rows):
        raise RuntimeError("combined_input_source_collision")
    source_rows = _sort_sources(list(by_key.values()))
    generation_rows = [gen_by_key[key] for key in _source_keys(source_rows)]
    _validate_combined_sources(source_rows, generation_rows)

    OUT.mkdir(parents=True, exist_ok=True)
    write_jsonl_atomic(source_rows, SOURCE_MANIFEST)
    write_jsonl_atomic(generation_rows, GENERATION)
    plan = {
        "kind": "v25_shared_g_anchor_query_usable_combined_source_plan",
        "status": "fixed_before_retrieval_or_victim_calls",
        "development_only": True,
        "protocol": "three_local_facts_plus_one_shared_remote_target",
        "source_unit": "source_document",
        "source_count": EXPECTED_SOURCE_COUNT,
        "query_usable_source_count": EXPECTED_SOURCE_COUNT,
        "membership_labels_read_during_replacement_selection": False,
        "selection": "union_of_passed_sources_from_previously_fixed_membership_blind_construction_batches",
        "batch_provenance": provenance,
        "source_keys_sha256": sha256_obj(_source_keys(source_rows)),
        "group_counts": dict(Counter(row["group"] for row in source_rows)),
        "dataset_counts": dict(Counter(row["dataset"] for row in source_rows)),
        "input_sha256": {
            "configs\\restoration_first_v25.yaml": sha256_file(ROOT / "configs/restoration_first_v25.yaml"),
            "configs\\llm_profiles.yaml": sha256_file(ROOT / "configs/llm_profiles.yaml"),
            "scripts\\95_run_v25_shared_g_pilot.py": sha256_file(PILOT_PATH),
        },
        "seed": SEED,
    }
    write_json(plan, SOURCE_PLAN)
    profiles = PILOT.load_llm_profiles({"llm_profiles_path": PILOT.V25_CONFIG["runtime"]["llm_profiles_path"]})
    effective_luna = PILOT.resolve_effective_llm_profile(
        profiles, "sibling", profile_name="luna_query_generator"
    )
    config = {
        "kind": "v25_shared_g_anchor_query_usable_combined_config",
        "status": "fixed_before_retrieval_or_victim_calls",
        "development_only": True,
        "protocol_parent": "pcv-mia-v25",
        "method": "three_local_facts_plus_one_shared_remote_target",
        "source_unit": "source_document",
        "source_count": EXPECTED_SOURCE_COUNT,
        "query_count": EXPECTED_QUERY_COUNT,
        "group_counts": dict(Counter(row["group"] for row in source_rows)),
        "dataset_counts": dict(Counter(row["dataset"] for row in source_rows)),
        "source_plan_sha256": sha256_file(SOURCE_PLAN),
        "source_manifest_sha256": sha256_file(SOURCE_MANIFEST),
        "generation_sha256": sha256_file(GENERATION),
        "models": {
            "query_generator_configured": "gpt-6-luna",
            "query_generator_effective": effective_luna.get("model"),
            "victim_configured": PILOT.V25_CONFIG["runtime"]["concrete_model"],
            "retriever": f"{PILOT.V25_CONFIG['runtime']['retrieval']['retriever_id']}@{PILOT.V25_CONFIG['runtime']['retrieval']['revision']}",
        },
        "query_protocol": {
            "initial": 3,
            "anchored_followup": 3,
            "no_anchor_control": 3,
            "frozen_queries_per_source": 9,
            "remote_region": "preferred_different_region_not_hard_gate",
            "followup_gate": "initial_response_is_correct_per_slot",
        },
        "downstream_budget": {
            "retrieval_queries": EXPECTED_QUERY_COUNT,
            "victim_initial_max": 300,
            "victim_followup_max": 600,
        },
        "downstream_calls": {"retriever": 0, "victim": 0},
        "seed": SEED,
    }
    write_json(config, RUN_CONFIG)
    report = {
        "kind": "v25_shared_g_anchor_query_usable_combined_construction_report",
        "status": "development_only",
        "no_formal_test_claim": True,
        "source_unit": "source_document",
        "source_count": EXPECTED_SOURCE_COUNT,
        "query_capacity": EXPECTED_QUERY_COUNT,
        "group_counts": dict(Counter(row["group"] for row in source_rows)),
        "dataset_counts": dict(Counter(row["dataset"] for row in source_rows)),
        "passed_construction_sources": EXPECTED_SOURCE_COUNT,
        "failed_construction_sources_excluded": 10,
        "batch_provenance": provenance,
        "interpretation": {
            "construction_definition": "Only passed shared-G structural/source-span records enter the combined identity.",
            "semantic_limitation": "No independent blind human semantic annotation or victim answerability claim is made at construction time.",
            "downstream_not_run_at_prepare": True,
        },
    }
    write_json(report, CONSTRUCTION_REPORT)
    print(json.dumps({
        "stage": "prepare",
        "sources": EXPECTED_SOURCE_COUNT,
        "queries_if_frozen": EXPECTED_QUERY_COUNT,
        "groups": dict(Counter(row["group"] for row in source_rows)),
        "datasets": dict(Counter(row["dataset"] for row in source_rows)),
        "luna_model": effective_luna.get("model"),
        "external_calls": 0,
    }, ensure_ascii=False))


def _query_id(source: dict[str, Any], arm: str, slot_index: int) -> str:
    return sha256_obj({
        "seed": SEED,
        "source_hash": source["source_hash"],
        "arm": arm,
        "slot_index": slot_index,
    })


def freeze() -> None:
    _install_pilot_context()
    sources, generation = _load_combined()
    gen_by_key = {str(row["source_key"]): row for row in generation}
    plan_rows: list[dict[str, Any]] = []
    for source in sources:
        records = gen_by_key[str(source["source_key"])] ["records"]
        target = records["remote_target"]
        for index, fact in enumerate(records["initial_facts"]):
            plan_rows.append({
                "query_id": _query_id(source, "initial", index),
                "source_key": source["source_key"],
                "dataset": source["dataset"],
                "group": source["group"],
                "arm": "initial",
                "slot_index": index,
                "question": fact["question"],
                "answer": fact["answer"],
                "answer_role": "local",
                "claim": fact["claim"],
                "remote_target_answer": target["answer"],
                "retrieval_query": fact["question"],
            })
        for arm_name, record_key in (("anchored", "anchored_followups"), ("no_anchor", "no_anchor_followups")):
            for index, followup in enumerate(records[record_key]):
                plan_rows.append({
                    "query_id": _query_id(source, arm_name, index),
                    "source_key": source["source_key"],
                    "dataset": source["dataset"],
                    "group": source["group"],
                    "arm": arm_name,
                    "slot_index": index,
                    "question": followup["question"],
                    "answer": target["answer"],
                    "answer_role": "shared_remote_target_G",
                    "claim": target["claim"],
                    "remote_target_answer": target["answer"],
                    "anchor": followup.get("anchor"),
                    "retrieval_query": followup["question"],
                    "region_diagnostics": records.get("region_diagnostics"),
                })
    if len(plan_rows) != EXPECTED_QUERY_COUNT or len({row["query_id"] for row in plan_rows}) != EXPECTED_QUERY_COUNT:
        raise RuntimeError("combined_query_count_or_id_drift")
    write_jsonl_atomic(plan_rows, QUERY_PLAN)
    freeze = {
        "kind": "v25_shared_g_anchor_query_freeze",
        "status": "frozen_before_retrieval_or_victim_calls",
        "source_count": EXPECTED_SOURCE_COUNT,
        "query_count": len(plan_rows),
        "initial_count": sum(row["arm"] == "initial" for row in plan_rows),
        "anchored_count": sum(row["arm"] == "anchored" for row in plan_rows),
        "no_anchor_count": sum(row["arm"] == "no_anchor" for row in plan_rows),
        "source_plan_sha256": sha256_file(SOURCE_PLAN),
        "generation_sha256": sha256_file(GENERATION),
        "query_plan_sha256": sha256_file(QUERY_PLAN),
        "query_construction": "copied from passed shared-G generation records without edits",
        "followup_policy": "runtime conditional trigger only; question construction is frozen",
        "semantic_limitation": "Structural/source-span freeze is not independent blind semantic annotation.",
    }
    write_json(freeze, QUERY_FREEZE)
    print(json.dumps({
        "stage": "freeze",
        "queries": len(plan_rows),
        "initial": freeze["initial_count"],
        "anchored": freeze["anchored_count"],
        "no_anchor": freeze["no_anchor_count"],
        "sha256": sha256_file(QUERY_PLAN),
    }, ensure_ascii=False))


def retrieve() -> None:
    _install_pilot_context()
    if not QUERY_FREEZE.is_file() or not QUERY_PLAN.is_file():
        raise RuntimeError("freeze_required")
    PILOT.retrieve()


def run_initial(max_new: int) -> None:
    _install_pilot_context()
    queries = [row for row in _read_manifest(QUERY_PLAN) if row["arm"] == "initial"]
    if len(queries) != 300:
        raise RuntimeError("combined_initial_query_count_drift")
    PILOT._run_victim(queries, INITIAL_RESPONSES, max_new)


def run_followup(max_new: int) -> None:
    _install_pilot_context()
    queries = _read_manifest(QUERY_PLAN)
    initial_queries = {row["query_id"]: row for row in queries if row["arm"] == "initial"}
    initial_rows = {row["query_id"]: row for row in _read_manifest(INITIAL_RESPONSES)}
    if set(initial_rows) != set(initial_queries):
        raise RuntimeError("combined_initial_responses_incomplete")
    initial_ok = {
        (row["source_key"], row["slot_index"]): PILOT._response_label(
            initial_rows[row["query_id"]].get("response", ""),
            row["answer"],
            initial_rows[row["query_id"]].get("status", "invalid"),
            row.get("answer_aliases"),
        ) == "correct"
        for row in initial_queries.values()
    }
    planned = [
        row for row in queries
        if row["arm"] in {"anchored", "no_anchor"}
        and initial_ok[(row["source_key"], row["slot_index"])]
    ]
    PILOT._run_victim(planned, FOLLOWUP_RESPONSES, max_new)


def _retrieval_stats() -> dict[str, Any]:
    rows = _read_manifest(RETRIEVAL)
    if not rows:
        return {"available": False}
    query_by_id = {str(row["query_id"]): row for row in _read_manifest(QUERY_PLAN)}
    target_hits = Counter()
    answer_surface_hits = Counter()
    for row in rows:
        query = query_by_id.get(str(row["query_id"]))
        if query is None:
            raise RuntimeError(f"retrieval_query_plan_missing:{row['query_id']}")
        key = (str(query["group"]), str(row["arm"]))
        target_hits[key] += bool(row.get("target_source_chunk_ranks"))
        answer_surface_hits[key] += bool(row.get("answer_surface_chunk_ranks"))
    return {
        "available": len(rows) == EXPECTED_QUERY_COUNT,
        "rows": len(rows),
        "target_source_hit_counts": {f"{g}:{a}": target_hits[(g, a)] for g in GROUPS for a in ("initial", "anchored", "no_anchor")},
        "answer_surface_hit_counts": {f"{g}:{a}": answer_surface_hits[(g, a)] for g in GROUPS for a in ("initial", "anchored", "no_anchor")},
        "retrieval_sha256": sha256_file(RETRIEVAL),
    }


def _victim_stats() -> dict[str, Any]:
    initial = _read_manifest(INITIAL_RESPONSES)
    followup = _read_manifest(FOLLOWUP_RESPONSES)
    if not initial and not followup:
        return {"available": False}
    query_by_id = {row["query_id"]: row for row in _read_manifest(QUERY_PLAN)}
    initial_labels = Counter()
    followup_labels = Counter()
    for response in initial:
        query = query_by_id[response["query_id"]]
        label = PILOT._response_label(
            response.get("response", ""), query["answer"], response.get("status", "invalid"),
            query.get("answer_aliases"),
        )
        initial_labels[(query["group"], label)] += 1
    for response in followup:
        query = query_by_id[response["query_id"]]
        label = PILOT._response_label(
            response.get("response", ""), query["answer"], response.get("status", "invalid"),
            query.get("answer_aliases"),
        )
        followup_labels[(query["group"], query["arm"], label)] += 1
    return {
        "available": len(initial) == 300,
        "initial_rows": len(initial),
        "followup_rows": len(followup),
        "initial_labels": {f"{g}:{label}": initial_labels[(g, label)] for g in GROUPS for label in ("correct", "incorrect", "ambiguous", "invalid")},
        "followup_labels": {f"{g}:{arm}:{label}": followup_labels[(g, arm, label)] for g in GROUPS for arm in ("anchored", "no_anchor") for label in ("correct", "incorrect", "ambiguous", "invalid")},
        "initial_response_sha256": sha256_file(INITIAL_RESPONSES) if INITIAL_RESPONSES.is_file() else None,
        "followup_response_sha256": sha256_file(FOLLOWUP_RESPONSES) if FOLLOWUP_RESPONSES.is_file() else None,
    }


def _source_scores() -> list[dict[str, Any]]:
    queries = _read_manifest(QUERY_PLAN)
    initial = {row["query_id"]: row for row in _read_manifest(INITIAL_RESPONSES)}
    followup = {row["query_id"]: row for row in _read_manifest(FOLLOWUP_RESPONSES)}
    if len(initial) != 300:
        return []
    by_source: dict[str, dict[str, Any]] = defaultdict(dict)
    for query in queries:
        if query["arm"] == "initial":
            response = initial.get(query["query_id"], {})
            by_source[query["source_key"]].setdefault("initial", {})[query["slot_index"]] = PILOT._response_label(
                response.get("response", ""), query["answer"], response.get("status", "invalid"),
                query.get("answer_aliases"),
            ) == "correct"
        else:
            response = followup.get(query["query_id"], {})
            by_source[query["source_key"]].setdefault(query["arm"], {})[query["slot_index"]] = PILOT._response_label(
                response.get("response", ""), query["answer"], response.get("status", "invalid"),
                query.get("answer_aliases"),
            ) == "correct"
    rows: list[dict[str, Any]] = []
    for source_key, values in by_source.items():
        initial_bits = [int(values.get("initial", {}).get(i, False)) for i in range(3)]
        anchored_bits = [int(values.get("anchored", {}).get(i, False)) for i in range(3)]
        no_anchor_bits = [int(values.get("no_anchor", {}).get(i, False)) for i in range(3)]
        rows.append({
            "source_key": source_key,
            "group": next(row["group"] for row in queries if row["source_key"] == source_key),
            "dataset": next(row["dataset"] for row in queries if row["source_key"] == source_key),
            "initial_score": sum(initial_bits) / 3,
            "anchored_chain_score": sum(i * a for i, a in zip(initial_bits, anchored_bits)) / 3,
            "no_anchor_chain_score": sum(i * n for i, n in zip(initial_bits, no_anchor_bits)) / 3,
            "initial_bits": initial_bits,
            "anchored_bits": anchored_bits,
            "no_anchor_bits": no_anchor_bits,
        })
    return rows


def report() -> None:
    _install_pilot_context()
    sources, _ = _load_combined()
    result: dict[str, Any] = {
        "kind": "v25_shared_g_anchor_query_usable_combined_report",
        "status": "development_only",
        "no_formal_test_claim": True,
        "source_unit": "source_document",
        "source_count": len(sources),
        "group_counts": dict(Counter(row["group"] for row in sources)),
        "dataset_counts": dict(Counter(row["dataset"] for row in sources)),
        "source_plan_sha256": sha256_file(SOURCE_PLAN),
        "generation_sha256": sha256_file(GENERATION),
        "query_freeze_sha256": sha256_file(QUERY_FREEZE) if QUERY_FREEZE.is_file() else None,
        "query_plan_sha256": sha256_file(QUERY_PLAN) if QUERY_PLAN.is_file() else None,
        "retrieval": _retrieval_stats(),
        "victim": _victim_stats(),
        "interpretation": {
            "followup_gate": "Only slots labeled correct in initial responses are eligible for anchored/no-anchor victim calls.",
            "semantic_limitation": "Answer labels use the frozen answer-surface matcher; no independent blind human annotation is claimed.",
            "downstream_status": "development_only",
        },
    }
    scores = _source_scores()
    if scores:
        result["source_scores"] = scores
        metric_rows = [{
            "group": row["group"],
            "membership": 1 if row["group"] == "KB_Member" else 0,
            "score_anchored": row["anchored_chain_score"],
            "score_no_anchor": row["no_anchor_chain_score"],
            "score_initial": row["initial_score"],
        } for row in scores]
        result["metrics"] = {
            "initial": summarize_membership_scores(metric_rows, score_key="score_initial"),
            "anchored_chain": summarize_membership_scores(metric_rows, score_key="score_anchored"),
            "no_anchor_chain": summarize_membership_scores(metric_rows, score_key="score_no_anchor"),
            "anchored_chain_auc_ci95": bootstrap_auc_ci(metric_rows, score_key="score_anchored", seed=42).get("ci95"),
            "no_anchor_chain_auc_ci95": bootstrap_auc_ci(metric_rows, score_key="score_no_anchor", seed=42).get("ci95"),
        }
    write_json(result, REPORT)
    print(json.dumps({
        "stage": "report",
        "sources": len(sources),
        "retrieval_rows": result["retrieval"].get("rows", 0),
        "initial_rows": result["victim"].get("initial_rows", 0),
        "followup_rows": result["victim"].get("followup_rows", 0),
        "report_sha256": sha256_file(REPORT),
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--freeze", action="store_true")
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
    elif args.freeze:
        freeze()
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
