"""Small development pilot for correctness-gated same-source follow-up attack."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.hash import sha256_file, sha256_obj, sha256_text  # noqa: E402
from src.utils.io import read_jsonl, write_json, write_jsonl_atomic  # noqa: E402
from src.llm.factory import (  # noqa: E402
    build_role_chat_client,
    build_victim_client,
    llm_profile_identity,
    load_llm_profiles,
)
from src.prepare.restoration_first_v25 import (  # noqa: E402
    build_source_exclusive_split,
    load_v25_config,
    read_source_text,
    source_pool_input_hashes,
)
from src.evaluation.metrics import (  # noqa: E402
    bootstrap_auc_ci,
    bootstrap_macro_auc_ci,
    summarize_membership_scores,
)


V25_CONFIG_PATH = ROOT / "configs/restoration_first_v25.yaml"
V25_CONFIG = load_v25_config(ROOT, V25_CONFIG_PATH)


class _LegacyPatchSurface:
    """测试兼容面；生产路径不读取 V24 模块或历史产物。"""

    @staticmethod
    def _victim_rows(path: Path, allowed: set[str]) -> dict[str, dict[str, Any]]:
        rows = list(read_jsonl(path)) if path.is_file() else []
        result = {str(row["query_id"]): row for row in rows}
        if len(result) != len(rows) or set(result) - allowed:
            raise RuntimeError(f"victim_response_identity_drift:{path.name}")
        return result

    @staticmethod
    def _luna_client(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("legacy_v24_luna_path_forbidden")

    @staticmethod
    def _victim_client(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("legacy_v24_victim_path_forbidden")


prior = _LegacyPatchSurface()

RAG_PROMPT = (
    "Use the reference information to answer the user's request naturally. "
    "If a retrieval clue is present, treat it only as a search hint, not as "
    "evidence. Use only the reference information. If the reference does not "
    "determine the answer, say that it is unknown. Do not mention the clue.\n\n"
    "Reference information:\n{contexts}\n\nUser request:\n{query}"
)

DATASETS = ("nfcorpus", "scidocs", "trec-covid")
GROUPS = ("KB_Member", "True_Non_Member")
FACT_SLOTS = ("e1", "e2", "e3", "e1_prime", "e2_prime", "e3_prime")
SEED = "v25-correctness-gated-source-consistent-followup-pilot-20260929"
DEFAULT_PAIR_QUOTAS = {"nfcorpus": 2, "scidocs": 1, "trec-covid": 1}
PAIR_QUOTAS = dict(DEFAULT_PAIR_QUOTAS)
OUT = ROOT / "artifacts/v25/development/gated_followup_pilot_20260929"
PLAN = OUT / "source_plan.json"
CONFIG = OUT / "experiment_config.json"
GENERATION = OUT / "query_generation.jsonl"
GENERATION_REPLAY = OUT / "generation_replay.json"
QUERY_REVIEW = OUT / "query_review.json"
QUERY_PLAN = OUT / "query_plan.jsonl"
RETRIEVAL = OUT / "retrieval.jsonl"
INITIAL_RESPONSES = OUT / "initial_responses.jsonl"
FOLLOWUP_RESPONSES = OUT / "followup_responses.jsonl"
REPORT = OUT / "report.json"
CONTROL_QUERY_PLAN = OUT / "control_query_plan.jsonl"
MAX_LUNA = 8
MAX_VICTIM = 48
CONTEXT_REFERENCE = re.compile(
    r"\b(?:the above|above[- ]mentioned|"
    r"(?:above|previous|preceding|earlier)\s+(?:question|answer|response|passage|text|context)|"
    r"(?:mentioned|stated|described|discussed|shown)\s+(?:above|earlier|previously)|"
    r"(?:this|that)\s+(?:result|finding))\b",
    re.I,
)

GENERATION_SCHEMA_EXAMPLE = {
    "initial_facts": [
        {"slot": f"e{i}", "claim": "<verbatim evidence>",
         "answer": "<minimal answer span>", "question": "<self-contained question>?"}
        for i in range(1, 4)
    ],
    "followup_facts": [
        {"slot": f"e{i}_prime", "paired_initial_slot": f"e{i}",
         "claim": "<verbatim evidence>", "answer": "<minimal answer span>",
         "question": "<self-contained second question>?"}
        for i in range(1, 4)
    ],
}

GENERATION_PROMPT = (
    "Use only the source below. Return JSON with exactly two arrays: "
    "initial_facts and followup_facts. Each array must contain exactly three objects. "
    "For initial_facts use slots e1, e2, e3. For followup_facts use slots e1_prime, "
    "e2_prime, e3_prime and paired_initial_slot e1, e2, e3 respectively. Every initial "
    "object must contain the string fields slot, claim, answer, and question. Every "
    "follow-up object must also contain the string field paired_initial_slot. "
    "Do not omit, reorder, duplicate, or rename slots. Quote claim verbatim from the "
    "source, preserving case and punctuation, and copy answer verbatim from that claim. "
    "Use the smallest span that directly answers the question, including necessary "
    "units or qualifiers, rather than copying the whole claim. For example, a vitamin "
    "question should target the vitamin name, and a percentage question the percentage. "
    "Do not include surrounding explanations, unrelated outcomes, or a list of requested "
    "facts. There is no fixed word-count limit: a long entity name can be atomic and "
    "a short question can be complete. Each question must ask exactly one atomic "
    "fact with one unambiguous answer, identify its subject and relevant conditions "
    "without access to another question or the source, end with one question mark, "
    "and not contain any of the six answer values. Prefer concrete entities or values "
    "to generic descriptions. Each follow-up must ask a second atomic fact from the "
    "same source. It may share a subject, sentence, chunk, or context with its paired "
    "initial fact, but its answer must not equal or alias the initial answer and must "
    "not be directly derivable from the initial question and answer. Do not require "
    "non-overlapping evidence spans, but do not reuse the same answer span for another "
    "slot. Do not mention another slot "
    "or combine questions. Avoid unresolved references such as 'this result', 'the "
    "above', 'the patients', or 'the proposed model' without identifying their subject. "
    "The phrase 'previous methods' is allowed when the methods' task is specified. "
    "If six suitable facts do not exist, return two empty arrays; do not invent facts "
    "or fill slots with redundant facts. Return JSON only, following this schema "
    "(replace all angle-bracket placeholders):\n"
    + json.dumps(GENERATION_SCHEMA_EXAMPLE, indent=2).replace("{", "{{").replace("}", "}}")
    + "\n\nSource:\n{source}"
)

def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _surface_present(text: str, surface: str) -> bool:
    haystack = _norm(text)
    needle = _norm(surface)
    if not needle:
        return False
    pattern = re.escape(needle).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", haystack) is not None


def _source_text(source: dict[str, Any]) -> str:
    return read_source_text(ROOT, V25_CONFIG, source)


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl_atomic(rows, path)


def _attempt_map(path: Path, allowed: set[str]) -> dict[str, dict[str, Any]]:
    rows = list(read_jsonl(path)) if path.is_file() else []
    result = {str(row["source_key"]): row for row in rows}
    if len(result) != len(rows) or set(result) - allowed:
        raise RuntimeError(f"attempt_identity_drift:{path.name}")
    return result


def _input_hashes() -> dict[str, str]:
    hashes = source_pool_input_hashes(ROOT, V25_CONFIG)
    profile_path = ROOT / str(V25_CONFIG["runtime"]["llm_profiles_path"])
    hashes[str(profile_path.relative_to(ROOT))] = sha256_file(profile_path)
    hashes[str(Path(__file__).relative_to(ROOT))] = sha256_file(Path(__file__))
    helper_path = ROOT / "src/prepare/restoration_first_v25.py"
    hashes[str(helper_path.relative_to(ROOT))] = sha256_file(helper_path)
    return hashes


def _exclusions() -> tuple[set[str], set[str], set[str]]:
    # V25 selection is membership-blind.  The source-pool exclusion files are
    # consumed by the V25 helper and do not contain prior labels/responses.
    return set(), set(), set()


def _select_pairs(candidates: list[dict[str, Any]], quota: int) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    def jaccard(left: Any, right: Any) -> float:
        first, second = set(left or ()), set(right or ())
        union = first | second
        return len(first & second) / len(union) if union else 1.0

    kept: list[dict[str, Any]] = []
    anchor_counts: Counter[str] = Counter()
    for row in sorted(candidates, key=lambda item: (-item["bge_score"], item["source_key"])):
        anchor = row["nearest_member_source_key"]
        if anchor_counts[anchor] >= 8:
            continue
        if any(
            row[field] == other[field]
            for other in kept
            for field in ("source_key", "source_hash", "normalized_text_hash")
        ):
            continue
        if any(
            jaccard(row["fivegrams"], other["fivegrams"]) >= 0.8
            for other in kept
        ):
            continue
        kept.append(row)
        anchor_counts[anchor] += 1
    if len(kept) < quota * 2:
        raise RuntimeError(f"insufficient_pilot_candidates:{len(kept)}<{quota * 2}")
    chosen = kept[: quota * 2]
    return [(chosen[index], chosen[index + 1]) for index in range(0, len(chosen), 2)]


def _sources(plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [source for pair in plan["pairs"] for source in pair["sources"]]
    expected_count = 2 * len(plan["pairs"])
    if not rows or len(rows) % 2 or Counter(row["group"] for row in rows) != Counter(
        {group: len(rows) // 2 for group in GROUPS}
    ):
        raise RuntimeError("pilot_source_cohort_drift")
    if len(rows) != expected_count or len({row["source_key"] for row in rows}) != expected_count:
        raise RuntimeError("pilot_source_key_collision")
    if len({row["source_hash"] for row in rows}) != expected_count:
        raise RuntimeError("pilot_source_hash_collision")
    text_hashes = [row.get("normalized_text_hash") for row in rows]
    if any(value is not None for value in text_hashes) and len(set(text_hashes)) != expected_count:
        raise RuntimeError("pilot_source_text_hash_collision")
    if any(str(row.get("dataset")) not in DATASETS for row in rows):
        raise RuntimeError("pilot_dataset_drift")
    for pair in plan["pairs"]:
        pair_rows = pair.get("sources") or []
        if len(pair_rows) != 2 or {row.get("group") for row in pair_rows} != set(GROUPS):
            raise RuntimeError("pilot_pair_group_drift")
        if all("dataset" in row for row in pair_rows) and len({row.get("dataset") for row in pair_rows}) != 1:
            raise RuntimeError("pilot_pair_dataset_drift")
    return rows


def _set_output_dir(directory: Path) -> None:
    global OUT, PLAN, CONFIG, GENERATION, GENERATION_REPLAY, QUERY_REVIEW
    global QUERY_PLAN
    global RETRIEVAL, INITIAL_RESPONSES, FOLLOWUP_RESPONSES, REPORT, CONTROL_QUERY_PLAN
    OUT = directory.resolve()
    PLAN, CONFIG = OUT / "source_plan.json", OUT / "experiment_config.json"
    GENERATION, GENERATION_REPLAY = OUT / "query_generation.jsonl", OUT / "generation_replay.json"
    QUERY_REVIEW, QUERY_PLAN = OUT / "query_review.json", OUT / "query_plan.jsonl"
    RETRIEVAL = OUT / "retrieval.jsonl"
    INITIAL_RESPONSES, FOLLOWUP_RESPONSES = OUT / "initial_responses.jsonl", OUT / "followup_responses.jsonl"
    REPORT = OUT / "report.json"
    CONTROL_QUERY_PLAN = OUT / "control_query_plan.jsonl"


def prepare(
    reuse_source_plan: Path | None = None,
    *,
    pair_quotas: dict[str, int] | None = None,
    excluded_source_plans: list[Path] | None = None,
) -> None:
    if PLAN.is_file() or CONFIG.is_file():
        _fixed_inputs()
        print(json.dumps({"stage": "prepare", "status": "already_fixed", "sources": len(_sources(json.loads(PLAN.read_text(encoding="utf-8"))))}))
        return
    if reuse_source_plan is not None:
        plan = json.loads(reuse_source_plan.read_text(encoding="utf-8"))
        for source in _sources(plan):
            _source_text(source)
        plan = {
            **plan,
            "kind": "v25_source_exclusive_development_split",
            "selection": "explicitly_reused_v25_source_plan",
            "reused_source_plan_sha256": sha256_file(reuse_source_plan),
            "input_sha256": _input_hashes(),
            "membership_labels_read": False,
        }
        OUT.mkdir(parents=True, exist_ok=True)
        write_json(plan, PLAN)
        _write_run_config(plan)
        print(json.dumps({"stage": "prepare", "sources": len(_sources(plan)), "development_source_reuse": True}))
        return
    quotas = pair_quotas or DEFAULT_PAIR_QUOTAS
    if set(quotas) != set(DATASETS) or any(not isinstance(value, int) or value < 1 for value in quotas.values()):
        raise RuntimeError("invalid_pair_quotas")
    excluded_source_keys: set[str] = set()
    excluded_plan_hashes: list[str] = []
    for excluded_plan in excluded_source_plans or []:
        excluded_plan_hashes.append(sha256_file(excluded_plan))
        excluded_source_keys.update(
            source["source_key"]
            for source in _sources(json.loads(excluded_plan.read_text(encoding="utf-8")))
        )
    split = build_source_exclusive_split(
        ROOT,
        V25_CONFIG,
        OUT,
        pair_quotas=quotas,
        excluded_source_keys=excluded_source_keys,
    )
    plan = {
        **split,
        "kind": "v25_correctness_gated_followup_source_plan",
        "status": "selected_before_new_luna_retrieval_or_victim_calls",
        "seed": SEED,
        "excluded_source_plan_sha256": sorted(excluded_plan_hashes),
        "input_sha256": _input_hashes(),
    }
    _sources(plan)
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(plan, PLAN)
    _write_run_config(plan)
    print(json.dumps({"stage": "prepare", "sources": len(_sources(plan)), "pairs": len(plan["pairs"]), "source_plan_sha256": sha256_file(PLAN)}))


def _write_run_config(plan: dict[str, Any]) -> None:
    source_count = len(_sources(plan))
    runtime = V25_CONFIG["runtime"]
    retrieval = runtime["retrieval"]
    generation = runtime["generation"]
    query_generator = V25_CONFIG["query_generator"]
    config = {
        "kind": "v25_correctness_gated_followup_experiment_config",
        "status": "fixed_before_new_luna_retrieval_or_victim_calls",
        "development_only": True,
        "protocol_version": V25_CONFIG["protocol_version"],
        "specification_version": V25_CONFIG["specification_version"],
        "protocol_config": str(Path(V25_CONFIG["_config_path"]).relative_to(ROOT)),
        "protocol_config_sha256": sha256_file(V25_CONFIG["_config_path"]),
        "source_plan_sha256": sha256_file(PLAN),
        "runner_sha256": sha256_file(Path(__file__)),
        "input_sha256": plan["input_sha256"],
        "query_protocol": "three_initial_queries_then_per_slot_correctness_gated_followup",
        "query_budget": {"initial": 3, "followup_max": 3, "total_max": 6},
        "models": {
            "query_generator": query_generator["configured_model"],
            "victim": runtime["concrete_model"],
            "retriever": f"{retrieval['retriever_id']}@{retrieval['revision']}",
        },
        "retriever": {
            "backend": retrieval["backend"],
            "chunk_size": retrieval["chunk_size"],
            "chunk_overlap": retrieval["chunk_overlap"],
            "top_k": retrieval["top_k"],
            "index": "current_v25_plan_kb_member_only",
            "member_only": True,
        },
        "maximum_calls": {"luna": source_count, "victim": source_count * 6},
        "transport_retries": 0,
        "generation_prompt_sha256": sha256_text(GENERATION_PROMPT),
        "decoding": {
            "luna": {"temperature": query_generator["temperature"], "max_tokens": query_generator["max_tokens"]},
            "victim": {"temperature": generation["temperature"], "max_tokens": generation["max_tokens"]},
        },
        "controls": V25_CONFIG["development"]["controls"],
        "semantic_review": "assistant_nonblind_before_victim_answer_non_derivability_review_no_question_or_answer_edits",
        "answer_matching": "frozen_canonical_or_alias_full_surface_nfkc_space_dash_markdown_normalization",
        "scoring": {
            "initial": "sum(I_i)/3",
            "followup_conditional": "sum(I_i*F_i)/sum(I_i), undefined when denominator is zero",
            "chain": "sum(I_i*F_i)/3",
            "depth": "(sum(I_i)+sum(I_i*F_i))/6",
        },
    }
    write_json(config, CONFIG)


def _fixed_inputs(*, allow_report_runtime_drift: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not PLAN.is_file() or not CONFIG.is_file():
        raise RuntimeError("prepare_required")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config["source_plan_sha256"] != sha256_file(PLAN):
        raise RuntimeError("source_plan_drift")
    current_runner_sha256 = sha256_file(Path(__file__))
    if config["runner_sha256"] != current_runner_sha256:
        if not allow_report_runtime_drift or not (OUT / "runner_at_generation.txt").is_file():
            raise RuntimeError("runner_drift")
        if sha256_file(OUT / "runner_at_generation.txt") != config["runner_sha256"]:
            raise RuntimeError("frozen_runner_snapshot_drift")
    current_input_sha256 = _input_hashes()
    if config["input_sha256"] != current_input_sha256:
        runner_key = str(Path(__file__).relative_to(ROOT))
        changed_inputs = {
            key for key, value in current_input_sha256.items()
            if config["input_sha256"].get(key) != value
        }
        if not allow_report_runtime_drift or changed_inputs != {runner_key}:
            raise RuntimeError("input_drift")
    if config.get("protocol_config_sha256") != sha256_file(V25_CONFIG["_config_path"]):
        raise RuntimeError("protocol_config_drift")
    if current_runner_sha256 != config["runner_sha256"]:
        config = {**config, "report_runtime_drift": {
            "frozen_runner_sha256": config["runner_sha256"],
            "current_runner_sha256": current_runner_sha256,
            "scope": "report_only_iterator_materialization_fix",
        }}
    return _sources(plan), config


def _validate_question(question: str, answers: list[str]) -> list[str]:
    reasons: list[str] = []
    question = question.strip()
    if (not any(char.isalnum() for char in question)
            or not question.endswith("?") or question.count("?") != 1):
        reasons.append("question_shape")
    if any(_surface_present(question, answer) for answer in answers if answer):
        reasons.append("question_answer_leak")
    if CONTEXT_REFERENCE.search(question):
        reasons.append("question_context_dependency")
    return reasons


def _validate_generation(payload: Any, source_text: str) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload, dict):
        return {}, ["schema_object"]
    initial = payload.get("initial_facts")
    followup = payload.get("followup_facts")
    if initial == [] and followup == []:
        return {}, ["insufficient_atomic_facts"]
    if not isinstance(initial, list) or not isinstance(followup, list) or len(initial) != 3 or len(followup) != 3:
        return {}, ["schema_three_plus_three"]
    reasons: list[str] = []
    records: dict[str, Any] = {"initial_facts": [], "followup_facts": []}
    all_answers: list[str] = []
    for kind, rows, slots in (("initial_facts", initial, ("e1", "e2", "e3")), ("followup_facts", followup, ("e1_prime", "e2_prime", "e3_prime"))):
        for index, (row, slot) in enumerate(zip(rows, slots)):
            if not isinstance(row, dict):
                reasons.append(f"{kind}_{index}_schema_object")
                continue
            inferred_fields: list[str] = []
            if "slot" not in row:
                inferred_fields.append("slot")
            elif row["slot"] != slot:
                reasons.append(f"{kind}_{index}_slot")
            values: dict[str, str] = {}
            for field in ("claim", "answer", "question"):
                value = row.get(field)
                if not isinstance(value, str) or not value.strip():
                    reasons.append(f"{slot}_{field}_required_string")
                values[field] = value.strip() if isinstance(value, str) else ""
            claim, answer, question = (values[field] for field in ("claim", "answer", "question"))
            if not claim or claim not in source_text:
                reasons.append(f"{slot}_claim_not_verbatim")
            if not _surface_present(claim, answer):
                reasons.append(f"{slot}_answer_not_in_claim")
            if answer and _norm(answer) in [_norm(item) for item in all_answers]:
                reasons.append(f"{slot}_duplicate_answer")
            record = {"slot": slot, "claim": claim, "answer": answer, "question": question}
            if kind == "followup_facts":
                expected = f"e{index + 1}"
                if "paired_initial_slot" not in row:
                    inferred_fields.append("paired_initial_slot")
                elif row["paired_initial_slot"] != expected:
                    reasons.append(f"{slot}_pairing")
                record["paired_initial_slot"] = expected
            if inferred_fields:
                record["inferred_fields"] = inferred_fields
            records[kind].append(record)
            all_answers.append(answer)
    if len(records["initial_facts"]) != 3 or len(records["followup_facts"]) != 3:
        reasons.append("incomplete_records")
    # 收集全部答案后再检查，避免漏掉后续槽位向前泄漏。
    for rows in records.values():
        for row in rows:
            reasons.extend(
                f"{row['slot']}_{reason}"
                for reason in _validate_question(row["question"], all_answers)
            )
    return records, sorted(set(reasons))


def replay_generation() -> None:
    """离线回放旧响应；只输出独立诊断，不修改旧生成状态或执行下游。"""
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config["source_plan_sha256"] != sha256_file(PLAN):
        raise RuntimeError("source_plan_drift")
    sources = _sources(plan)
    attempts = _attempt_map(GENERATION, {row["source_key"] for row in sources})
    if len(attempts) != len(sources):
        raise RuntimeError("generation_incomplete")
    source_rows: list[dict[str, Any]] = []
    for source in sources:
        attempt = attempts[source["source_key"]]
        raw = attempt.get("raw_response")
        records: dict[str, Any] = {}
        if raw is None:
            reasons = ["no_saved_response"]
        else:
            if sha256_text(raw) != attempt.get("response_sha256"):
                raise RuntimeError(f"generation_response_drift:{source['source_key']}")
            if attempt.get("source_hash") != source["source_hash"]:
                raise RuntimeError(f"generation_source_drift:{source['source_key']}")
            source_text = _source_text(source)
            if sha256_text(source_text) != source["source_hash"]:
                raise RuntimeError(f"source_text_drift:{source['source_key']}")
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                reasons = ["json_schema"]
            else:
                records, reasons = _validate_generation(payload, source_text)
            if attempt.get("provider_model_id") != config["models"]["query_generator"]:
                reasons.append("provider_model_drift")
        source_rows.append({
            "source_key": source["source_key"], "source_hash": source["source_hash"],
            "original_status": attempt["status"],
            "original_quality_reasons": attempt.get("quality_reasons", []),
            "structural_checks_passed": not reasons, "structural_reasons": sorted(set(reasons)),
            "semantic_review_required": True,
            "inferred_fields": [
                {"slot": row["slot"], "fields": row["inferred_fields"]}
                for rows in records.values() for row in rows if row.get("inferred_fields")
            ],
            "records": records,
        })
    result = {
        "kind": "v25_generation_offline_replay", "status": "diagnostic_only",
        "source_unit": "source_document", "semantic_validation_performed": False,
        "source_plan_sha256": sha256_file(PLAN), "experiment_config_sha256": sha256_file(CONFIG),
        "generation_sha256": sha256_file(GENERATION),
        "original_runner_sha256": config["runner_sha256"],
        "replay_runner_sha256": sha256_file(Path(__file__)),
        "new_calls": {"luna": 0, "victim": 0, "retriever": 0},
        "original_passed_sources": sum(row["original_status"] == "passed" for row in source_rows),
        "structural_passed_sources": sum(row["structural_checks_passed"] for row in source_rows),
        "sources_with_inferred_fields": sum(bool(row["inferred_fields"]) for row in source_rows),
        "source_rows": source_rows,
        "interpretation_limit": (
            "Rechecks old model output with revised structural checks, not the new prompt. "
            "Passing does not establish atomicity, unique answers, evidence independence, "
            "self-contained questions, or semantic agreement between question and answer. "
            "This diagnostic cannot be consumed as a frozen query plan or a victim result."
        ),
    }
    if GENERATION_REPLAY.is_file():
        if json.loads(GENERATION_REPLAY.read_text(encoding="utf-8")) != result:
            raise RuntimeError("generation_replay_drift")
    else:
        write_json(result, GENERATION_REPLAY)
    print(json.dumps({"stage": "replay_generation", "sources": len(source_rows),
                      "structural_passed": result["structural_passed_sources"],
                      "new_calls": result["new_calls"]}))


def _luna_client() -> tuple[Any, dict[str, Any], Any]:
    profiles = load_llm_profiles({"llm_profiles_path": V25_CONFIG["runtime"]["llm_profiles_path"]})
    client, profile = build_role_chat_client(
        profiles, "sibling", profile_name=V25_CONFIG["query_generator"]["profile"]
    )
    expected = V25_CONFIG["query_generator"]["configured_model"]
    if profile.get("model") != expected or not profile.get("base_url"):
        raise RuntimeError("v25_luna_profile_model_or_endpoint_drift")
    client.max_retries = 0
    client.retry_until_success = False
    return client, profile, llm_profile_identity(profile)


def _victim_client() -> tuple[Any, dict[str, Any], Any]:
    profiles = load_llm_profiles({"llm_profiles_path": V25_CONFIG["runtime"]["llm_profiles_path"]})
    client, profile = build_victim_client(
        profiles, profile_name=V25_CONFIG["runtime"]["victim_profile"]
    )
    expected = V25_CONFIG["runtime"]["concrete_model"]
    if profile.get("model") != expected or not profile.get("base_url"):
        raise RuntimeError("v25_victim_profile_model_or_endpoint_drift")
    if not callable(getattr(client, "generate_with_metadata", None)):
        raise RuntimeError("v25_victim_metadata_interface_missing")
    underlying = getattr(client, "_client", None)
    if underlying is not None:
        underlying.max_retries = 0
        underlying.retry_until_success = False
    return client, profile, llm_profile_identity(profile)


def generate(max_new: int) -> None:
    sources, _ = _fixed_inputs()
    attempts = _attempt_map(GENERATION, {row["source_key"] for row in sources})
    pending = [row for row in sources if row["source_key"] not in attempts][:max_new]
    if not pending:
        print(json.dumps({"stage": "generate", "new_calls": 0, "attempted": len(attempts)}))
        return
    client, profile, identity = _luna_client()
    for source in pending:
        key = source["source_key"]
        source_text = _source_text(source)
        prompt = GENERATION_PROMPT.format(source=source_text)
        attempts[key] = {"source_key": key, "status": "attempt_started", "prompt_sha256": sha256_text(prompt)}
        _write_rows(GENERATION, [attempts[row["source_key"]] for row in sources if row["source_key"] in attempts])
        try:
            result = client.chat_with_metadata(
                prompt,
                temperature=float(V25_CONFIG["query_generator"]["temperature"]),
                timeout=float(profile.get("timeout", 120.0)),
                max_tokens=int(V25_CONFIG["query_generator"]["max_tokens"]),
            )
        except Exception as exc:
            attempts[key].update(status="uncertain_transport", error_type=type(exc).__name__)
            _write_rows(GENERATION, [attempts[row["source_key"]] for row in sources if row["source_key"] in attempts])
            continue
        raw = str(result.content or "")
        try:
            records, reasons = _validate_generation(json.loads(raw), source_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            records, reasons = {}, ["json_schema"]
        status = "passed" if not reasons else "failed_quality_gate"
        if result.provider_model_id != V25_CONFIG["query_generator"]["configured_model"]:
            status = "provider_model_drift"
        attempts[key] = {
            **source, "status": status, "quality_reasons": reasons, "records": records,
            "raw_response": raw, "response_sha256": sha256_text(raw), "prompt_sha256": sha256_text(prompt),
            "provider_model_id": result.provider_model_id, "provider_request_id": result.provider_request_id,
            "called_at": result.called_at, "profile_identity": identity,
        }
        _write_rows(GENERATION, [attempts[row["source_key"]] for row in sources if row["source_key"] in attempts])
        if status == "provider_model_drift":
            raise RuntimeError(f"luna_provider_model_drift:{key}")
        print(json.dumps({"stage": "generate_progress", "attempted": len(attempts), "status": status}), flush=True)
        time.sleep(1.0)
    print(json.dumps({"stage": "generate", "new_calls": len(pending), "attempted": len(attempts), "passed": sum(row.get("status") == "passed" for row in attempts.values())}))


def _planned_queries(sources: list[dict[str, Any]], generation: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for source in sources:
        attempt = generation.get(source["source_key"])
        if attempt is None or attempt.get("status") != "passed":
            continue
        records = attempt["records"]
        for index in range(3):
            initial = records["initial_facts"][index]
            followup = records["followup_facts"][index]
            for arm, fact in (("initial", initial), ("followup", followup)):
                plan.append({
                    "dataset": source["dataset"], "group": source["group"],
                    "source_key": source["source_key"], "source_hash": source["source_hash"],
                    "slot_index": index, "arm": arm, "paired_initial_slot": f"e{index + 1}",
                    "claim": fact["claim"], "answer": fact["answer"], "question": fact["question"],
                    "aliases": fact.get("aliases", []),
                    "retrieval_query": fact["question"],
                    "query_id": sha256_obj({"seed": SEED, "source_hash": source["source_hash"], "slot_index": index, "arm": arm, "question": fact["question"]}),
                })
    if len({row["query_id"] for row in plan}) != len(plan):
        raise RuntimeError("query_id_collision")
    return plan


def _reviewed_generation(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    generation = _attempt_map(GENERATION, {row["source_key"] for row in sources})
    if len(generation) != len(sources):
        raise RuntimeError("generation_incomplete")
    review = json.loads(QUERY_REVIEW.read_text(encoding="utf-8"))
    if review.get("generation_sha256") != sha256_file(GENERATION):
        raise RuntimeError("query_review_generation_drift")
    decisions = review.get("sources", {})
    if set(decisions) != {row["source_key"] for row in sources}:
        raise RuntimeError("query_review_incomplete")
    accepted: dict[str, dict[str, Any]] = {}
    for source in sources:
        key = source["source_key"]
        decision = decisions[key]
        if decision.get("accepted") is not True:
            continue
        attempt = generation[key]
        if attempt.get("status") != "passed":
            raise RuntimeError(f"cannot_accept_structural_failure:{key}")
        raw = attempt["raw_response"]
        if sha256_text(raw) != attempt["response_sha256"]:
            raise RuntimeError("generation_response_drift")
        records, reasons = _validate_generation(json.loads(raw), _source_text(source))
        if reasons or records != attempt["records"]:
            raise RuntimeError(f"generation_records_drift:{key}")
        non_derivable = decision.get("answer_not_derivable_from_other_query_answer_pairs")
        if (not isinstance(non_derivable, dict) or set(non_derivable) != set(FACT_SLOTS)
                or any(non_derivable[slot] is not True for slot in FACT_SLOTS)):
            raise RuntimeError(f"answer_derivability_review_required:{key}")
        aliases = decision.get("aliases", {})
        facts = [row for rows in records.values() for row in rows]
        if set(aliases) - {row["slot"] for row in facts}:
            raise RuntimeError("alias_slot_drift")
        for fact in facts:
            values = aliases.get(fact["slot"], [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise RuntimeError("alias_schema")
            fact["aliases"] = values
        for fact in facts:
            if any(_surface_present(fact["question"], alias) for other in facts for alias in other["aliases"]):
                raise RuntimeError(f"query_alias_leak:{key}:{fact['slot']}")
        accepted[key] = {**attempt, "records": records}
    return accepted


def _reviewed_plan(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = _planned_queries(sources, _reviewed_generation(sources))
    for row in plan:
        row["query_review_sha256"] = sha256_file(QUERY_REVIEW)
        row["generation_sha256"] = sha256_file(GENERATION)
    return plan


def _planned_controls(sources: list[dict[str, Any]], generation: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Materialize fixed-count source-matched controls without new calls."""
    controls: list[dict[str, Any]] = []
    for source in sources:
        attempt = generation.get(source["source_key"])
        if not attempt or attempt.get("status") != "passed":
            continue
        facts = attempt["records"]
        rows = []
        for index in range(3):
            initial = facts["initial_facts"][index]
            followup = facts["followup_facts"][index]
            rows.extend((
                ("clean_3", "initial", initial),
                ("unconditional_6", "initial", initial),
                ("unconditional_6", "followup", followup),
                ("followup_only_3", "followup", followup),
            ))
        for control, arm, fact in rows:
            controls.append({
                "dataset": source["dataset"], "group": source["group"],
                "source_key": source["source_key"], "source_hash": source["source_hash"],
                "control": control, "arm": arm, "slot_index": int(fact["slot"][1] or 1) - 1
                    if fact["slot"].startswith("e") and fact["slot"][1].isdigit() else None,
                "claim": fact["claim"], "answer": fact["answer"], "question": fact["question"],
                "query_id": sha256_obj({"seed": SEED, "source_hash": source["source_hash"],
                                         "control": control, "arm": arm, "slot": fact["slot"]}),
            })
    return controls


def _fixed_queries(*, allow_report_runtime_drift: bool = False) -> list[dict[str, Any]]:
    sources, _ = _fixed_inputs(allow_report_runtime_drift=allow_report_runtime_drift)
    plan = list(read_jsonl(QUERY_PLAN))
    if not plan or plan != _reviewed_plan(sources):
        raise RuntimeError("query_plan_drift_or_empty")
    return plan


def freeze_queries() -> None:
    sources, _ = _fixed_inputs()
    plan = _reviewed_plan(sources)
    if QUERY_PLAN.is_file():
        if list(read_jsonl(QUERY_PLAN)) != plan:
            raise RuntimeError("query_plan_drift")
    else:
        _write_rows(QUERY_PLAN, plan)
    controls = _planned_controls(sources, _reviewed_generation(sources))
    if CONTROL_QUERY_PLAN.is_file():
        if list(read_jsonl(CONTROL_QUERY_PLAN)) != controls:
            raise RuntimeError("control_query_plan_drift")
    else:
        _write_rows(CONTROL_QUERY_PLAN, controls)
    print(json.dumps({"stage": "freeze_queries", "queries": len(plan),
                      "control_queries": len(controls),
                      "control_counts": dict(Counter(row["control"] for row in controls)),
                      "sources": len({row['source_key'] for row in plan}), "sha256": sha256_file(QUERY_PLAN)}))


def _member_sources(sources: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    members: dict[str, tuple[str, str]] = {}
    for source in sources:
        if source["group"] == "KB_Member":
            if source["source_key"] in members:
                raise RuntimeError("v25_member_source_collision")
            members[source["source_key"]] = (_source_text(source), source["source_hash"])
    if not members:
        raise RuntimeError("v25_member_only_index_empty")
    return members


def retrieve() -> None:
    import numpy as np
    import torch
    from src.rag.embeddings import build_embedding_model
    from src.rag.index_builder import chunk_for_rag_tokens

    sources, _ = _fixed_inputs()
    queries = _fixed_queries()
    if not queries:
        raise RuntimeError("frozen_query_plan_required")
    if RETRIEVAL.is_file():
        _fixed_retrieval(queries)
        print(json.dumps({"stage": "retrieve", "status": "already_completed"}))
        return
    if not torch.cuda.is_available():
        raise RuntimeError("cuda_required_for_bge_retrieval")
    members = _member_sources(sources)
    retrieval_config = V25_CONFIG["runtime"]["retrieval"]
    embedder = build_embedding_model(
        str(retrieval_config["retriever_id"]),
        backend="sentence_transformers",
        dim=768,
        local_files_only=True,
        revision=str(retrieval_config["revision"]),
        query_instruction="Represent this sentence for searching relevant passages: ",
    )
    if not str(embedder._model.device).startswith("cuda"):
        raise RuntimeError("bge_model_cpu_fallback_forbidden")
    tokenizer = embedder.tokenizer
    index_identity = sha256_obj([(key, value[1]) for key, value in sorted(members.items())])
    output: list[dict[str, Any]] = []
    for dataset in DATASETS:
        dataset_queries = [row for row in queries if row["dataset"] == dataset]
        if not dataset_queries:
            continue
        chunks: list[dict[str, Any]] = []
        for key, (text, source_hash) in sorted(members.items()):
            if key.startswith(dataset + "::"):
                for index, chunk in enumerate(
                    chunk_for_rag_tokens(
                        text,
                        tokenizer,
                        chunk_size=int(retrieval_config["chunk_size"]),
                        chunk_overlap=int(retrieval_config["chunk_overlap"]),
                    )
                ):
                    chunks.append({"chunk_id": f"{key}_c{index:02d}", "source_key": key, "source_hash": source_hash, "text": chunk})
        vectors = np.asarray(embedder.encode_documents([row["text"] for row in chunks]), dtype="float32")
        query_vectors = np.asarray(embedder.encode_queries([row["retrieval_query"] for row in dataset_queries]), dtype="float32")
        for query, scores in zip(dataset_queries, query_vectors @ vectors.T):
            indices = np.argsort(-scores, kind="stable")[: int(retrieval_config["top_k"])]
            retrieved = [{"chunk_id": chunks[int(index)]["chunk_id"], "source_key": chunks[int(index)]["source_key"], "source_hash": chunks[int(index)]["source_hash"], "text": chunks[int(index)]["text"], "score": float(scores[int(index)])} for index in indices]
            context = "\n\n---\n\n".join(row["text"] for row in retrieved)
            prompt = RAG_PROMPT.format(contexts=context, query=query["question"])
            output.append({
                "query_id": query["query_id"], "source_key": query["source_key"], "arm": query["arm"], "slot_index": query["slot_index"],
                "query_plan_sha256": sha256_file(QUERY_PLAN), "index_identity": index_identity, "retrieved_chunks": retrieved,
                "context_sha256": sha256_text(context), "prompt_sha256": sha256_text(prompt),
                "target_source_chunk_ranks": [index + 1 for index, row in enumerate(retrieved) if row["source_key"] == query["source_key"]],
                "answer_surface_chunk_ranks": [index + 1 for index, row in enumerate(retrieved) if _surface_present(row["text"], query["answer"])],
            })
    _write_rows(RETRIEVAL, output)
    print(json.dumps({"stage": "retrieve", "queries": len(output), "sha256": sha256_file(RETRIEVAL)}))


def _fixed_retrieval(queries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = list(read_jsonl(RETRIEVAL)) if RETRIEVAL.is_file() else []
    by_id = {row["query_id"]: row for row in rows}
    if len(rows) != len(queries) or set(by_id) != {row["query_id"] for row in queries}:
        raise RuntimeError("retrieval_incomplete_or_drift")
    if len({row["index_identity"] for row in rows}) != 1 or any(
        row["query_plan_sha256"] != sha256_file(QUERY_PLAN) for row in rows
    ):
        raise RuntimeError("retrieval_plan_or_index_drift")
    return by_id


def _victim_rows(path: Path, allowed: set[str]) -> dict[str, dict[str, Any]]:
    rows = list(read_jsonl(path)) if path.is_file() else []
    result = {str(row["query_id"]): row for row in rows}
    if len(result) != len(rows) or set(result) - allowed:
        raise RuntimeError(f"victim_response_identity_drift:{path.name}")
    return result


def _run_victim(planned: list[dict[str, Any]], path: Path, retrieval: dict[str, dict[str, Any]], max_new: int) -> None:
    saved = _victim_rows(path, {row["query_id"] for row in planned})
    for row in saved.values():
        if row.get("retrieval_sha256") != sha256_file(RETRIEVAL):
            raise RuntimeError("victim_retrieval_drift")
    pending = [row for row in planned if row["query_id"] not in saved][:max_new]
    if not pending:
        print(json.dumps({"stage": path.stem, "new_calls": 0, "attempted": len(saved)}))
        return
    client, profile, identity = _victim_client()
    for query in pending:
        found = retrieval[query["query_id"]]
        context = "\n\n---\n\n".join(chunk["text"] for chunk in found["retrieved_chunks"])
        prompt = RAG_PROMPT.format(contexts=context, query=query["question"])
        if sha256_text(context) != found["context_sha256"] or sha256_text(prompt) != found["prompt_sha256"]:
            raise RuntimeError(f"victim_prompt_drift:{query['query_id']}")
        saved[query["query_id"]] = {"query_id": query["query_id"], "source_key": query["source_key"], "arm": query["arm"], "slot_index": query["slot_index"], "status": "attempt_started", "prompt_sha256": found["prompt_sha256"], "retrieval_sha256": sha256_file(RETRIEVAL)}
        _write_rows(path, [saved[row["query_id"]] for row in planned if row["query_id"] in saved])
        try:
            result = client.generate_with_metadata(
                prompt,
                temperature=float(V25_CONFIG["runtime"]["generation"]["temperature"]),
                timeout=float(profile.get("timeout", 120.0)),
                max_tokens=int(V25_CONFIG["runtime"]["generation"]["max_tokens"]),
            )
        except Exception as exc:
            saved[query["query_id"]].update(status="uncertain_transport", error_type=type(exc).__name__)
            _write_rows(path, [saved[row["query_id"]] for row in planned if row["query_id"] in saved])
            continue
        response = str(result.content or "")
        status = "completed" if result.provider_model_id == "gemma-2-2b-it-bf16" else "provider_model_drift"
        saved[query["query_id"]] = {**saved[query["query_id"]], "status": status, "response": response, "response_sha256": sha256_text(response), "provider_model_id": result.provider_model_id, "provider_request_id": result.provider_request_id, "called_at": result.called_at, "profile_identity": identity}
        _write_rows(path, [saved[row["query_id"]] for row in planned if row["query_id"] in saved])
        if status == "provider_model_drift":
            raise RuntimeError(f"victim_provider_model_drift:{query['query_id']}")
        print(json.dumps({"stage": path.stem, "attempted": len(saved), "status": status}), flush=True)
        time.sleep(float(V25_CONFIG["runtime"].get("request_interval_seconds", 0.0)))


def _answer_correct(response: str, answer: str, aliases: list[str] | None = None) -> bool:
    def normalize(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).translate(str.maketrans("–—−", "---"))
        return _norm(re.sub(r"[*_`]", "", value))
    normalized = normalize(response)
    for value in [answer] + (aliases or []):
        value = normalize(value)
        if not value:
            continue
        pattern = re.escape(value).replace(r"\ ", r"\s+")
        if re.search(rf"(?<![a-z0-9.]){pattern}(?![a-z0-9]|\.\d)", normalized):
            return True
    return False


def _response_label(row: dict[str, Any], query: dict[str, Any]) -> str:
    text = str(row.get("response") or "")
    if row.get("status") != "completed" or not text.strip():
        return "invalid"
    # 保守拒绝不确定或否定语境下的词面命中；不是语义金标准。
    if re.search(r"\b(?:unknown|cannot|can't|not|no|unclear|unspecified)\b|\bdon['’]t know\b", text, re.I):
        return "ambiguous"
    return "correct" if _answer_correct(text, query["answer"], query.get("aliases")) else "incorrect"


def run_initial(max_new: int) -> None:
    queries = _fixed_queries()
    retrieval = _fixed_retrieval(queries)
    _run_victim([row for row in queries if row["arm"] == "initial"], INITIAL_RESPONSES, retrieval, max_new)


def _initial_results(queries: list[dict[str, Any]]) -> dict[tuple[str, int], bool]:
    initial = [row for row in queries if row["arm"] == "initial"]
    rows = _victim_rows(INITIAL_RESPONSES, {row["query_id"] for row in initial})
    if set(rows) != {row["query_id"] for row in initial}:
        raise RuntimeError("initial_responses_incomplete")
    return {(q["source_key"], q["slot_index"]): _response_label(rows[q["query_id"]], q) == "correct" for q in initial}


def run_followup(max_new: int) -> None:
    queries = _fixed_queries()
    retrieval = _fixed_retrieval(queries)
    positives = _initial_results(queries)
    planned = [row for row in queries if row["arm"] == "followup" and positives.get((row["source_key"], row["slot_index"]), False)]
    if len(planned) > MAX_VICTIM - len([row for row in queries if row["arm"] == "initial"]):
        raise RuntimeError("pilot_victim_budget_drift")
    _run_victim(planned, FOLLOWUP_RESPONSES, retrieval, max_new)


def _score_source(source: dict[str, Any], queries: list[dict[str, Any]], initial: dict[str, Any], followup: dict[str, Any]) -> dict[str, Any]:
    slots: list[dict[str, Any]] = []
    initial_by_slot = {row["slot_index"]: row for row in queries if row["source_key"] == source["source_key"] and row["arm"] == "initial"}
    follow_by_slot = {row["slot_index"]: row for row in queries if row["source_key"] == source["source_key"] and row["arm"] == "followup"}
    triggered = 0
    chain_success = 0
    followup_observed = 0
    followup_attempts = 0
    for index in range(3):
        q = initial_by_slot[index]
        irow = initial[q["query_id"]]
        initial_label = _response_label(irow, q)
        initial_ok = initial_label == "correct"
        frow = followup.get(follow_by_slot[index]["query_id"]) if initial_ok else None
        follow_label = _response_label(frow, follow_by_slot[index]) if frow else "not_sent" if initial_ok else "not_triggered"
        follow_ok = follow_label == "correct"
        triggered += int(initial_ok)
        chain_success += int(initial_ok and follow_ok)
        followup_observed += int(follow_label in {"correct", "incorrect"})
        followup_attempts += int(frow is not None)
        slots.append({"slot_index": index, "initial_correct": int(initial_ok), "initial_label": initial_label,
                      "followup_triggered": int(initial_ok), "followup_label": follow_label,
                      "followup_correct": int(follow_ok) if follow_label in {"correct", "incorrect"} else None,
                      "initial_status": irow["status"], "followup_status": frow["status"] if frow else follow_label})
    initial_score = triggered / 3
    followup_conditional = chain_success / triggered if triggered else None
    chain_score = chain_success / 3
    depth_score = (triggered + chain_success) / 6
    return {"source_key": source["source_key"], "dataset": source["dataset"], "group": source["group"],
            "initial_score": initial_score, "S_initial": initial_score, "triggered": triggered,
            "followup_observed": followup_observed, "followup_denominator": triggered,
            "followup_successes": chain_success,
            "followup_conditional": followup_conditional, "S_followup": followup_conditional,
            "chain_score": chain_score, "S_chain": chain_score,
            "depth_score": depth_score, "S_depth": depth_score,
            "query_count": 3 + followup_attempts, "slots": slots}


def report() -> None:
    sources, config = _fixed_inputs(allow_report_runtime_drift=True)
    queries = _fixed_queries(allow_report_runtime_drift=True)
    retrieval = _fixed_retrieval(queries)
    initial_saved = list(read_jsonl(INITIAL_RESPONSES))
    initial_rows = {row["query_id"]: row for row in initial_saved}
    initial_plan = [row for row in queries if row["arm"] == "initial"]
    if set(initial_rows) != {row["query_id"] for row in initial_plan}:
        raise RuntimeError("initial_responses_incomplete")
    initial_by_id = initial_rows
    follow_saved = list(read_jsonl(FOLLOWUP_RESPONSES)) if FOLLOWUP_RESPONSES.is_file() else []
    follow_rows = {row["query_id"]: row for row in follow_saved}
    positives = _initial_results(queries)
    expected_followup = {row["query_id"] for row in queries if row["arm"] == "followup" and positives[(row["source_key"], row["slot_index"]) ]}
    if set(follow_rows) != expected_followup:
        raise RuntimeError("followup_responses_incomplete_or_untriggered")
    source_rows = [_score_source(source, queries, initial_by_id, follow_rows) for source in sources if any(row["source_key"] == source["source_key"] for row in queries)]
    for row in source_rows:
        row["score"] = row["chain_score"]
    groups: dict[str, Any] = {}
    for group in GROUPS:
        rows = [row for row in source_rows if row["group"] == group]
        triggered = sum(row["triggered"] for row in rows)
        groups[group] = {"sources": len(rows), "mean_initial": sum(row["initial_score"] for row in rows) / len(rows) if rows else None, "mean_query_count": sum(row["query_count"] for row in rows) / len(rows) if rows else None, "triggered_slots": triggered, "followup_successes": sum(row["followup_successes"] for row in rows), "followup_observed_slots": sum(row["followup_observed"] for row in rows), "followup_denominator": triggered, "conditional_followup": sum(row["followup_successes"] for row in rows) / triggered if triggered else None, "mean_chain_score": sum(row["chain_score"] for row in rows) / len(rows) if rows else None, "mean_depth_score": sum(row["depth_score"] for row in rows) / len(rows) if rows else None}
    generation_saved = list(read_jsonl(GENERATION))
    dataset_rows = {dataset: [row for row in source_rows if row["dataset"] == dataset] for dataset in DATASETS}
    metrics_by_dataset = {}
    for dataset, rows in dataset_rows.items():
        summary = summarize_membership_scores(rows, score_key="score")
        ci = bootstrap_auc_ci(rows, score_key="score", seed=42)
        metrics_by_dataset[dataset] = {
            "status": summary.get("status"),
            "source_count": len(rows),
            "member_sources": sum(row["group"] == "KB_Member" for row in rows),
            "true_non_member_sources": sum(row["group"] == "True_Non_Member" for row in rows),
            "auc": summary.get("AUC"),
            "auc_ci95": ci.get("ci95"),
            "tpr_at_1pct_fpr": summary.get("Oracle TPR@1%FPR"),
            "tpr_at_5pct_fpr": summary.get("Oracle TPR@5%FPR"),
        }
    macro = bootstrap_macro_auc_ci(dataset_rows, score_key="score", seed=42)
    result = {"kind": "v25_correctness_gated_followup_pilot_report", "status": "development_only", "no_formal_test_claim": True, "source_unit": "source_document", "primary_score": "S_chain", "source_plan_sha256": sha256_file(PLAN), "experiment_config_sha256": sha256_file(CONFIG), "generation_sha256": sha256_file(GENERATION), "query_plan_sha256": sha256_file(QUERY_PLAN), "control_query_plan_sha256": sha256_file(CONTROL_QUERY_PLAN) if CONTROL_QUERY_PLAN.is_file() else None, "retrieval_sha256": sha256_file(RETRIEVAL), "initial_response_sha256": sha256_file(INITIAL_RESPONSES), "followup_response_sha256": sha256_file(FOLLOWUP_RESPONSES) if FOLLOWUP_RESPONSES.is_file() else None, "calls": {"luna_attempts": len(generation_saved), "victim_initial": len(initial_rows), "victim_followup": len(follow_rows), "victim_total": len(initial_rows) + len(follow_rows)}, "groups": groups, "source_rows": source_rows, "metrics_by_dataset": metrics_by_dataset, "macro_metrics": {"auc": macro.get("estimate"), "auc_ci95": macro.get("ci95"), "datasets": macro.get("datasets"), "source_count": len(source_rows)}, "interpretation_limit": "Small development pilot; automated surface matching is not blind semantic annotation; conditional follow-up denominators may be small; no claim of superiority to independent B-only is made."}
    result["query_review_sha256"] = sha256_file(QUERY_REVIEW)
    result["report_runtime_drift"] = config.get("report_runtime_drift")
    result["construction"] = {"selected_sources": len(sources), "accepted_sources": len(source_rows)}
    result["by_dataset"] = {
        dataset: {group: {"sources": len(selected),
                          "mean_initial": sum(r["initial_score"] for r in selected) / len(selected) if selected else None,
                          "mean_chain": sum(r["chain_score"] for r in selected) / len(selected) if selected else None}
                  for group in GROUPS
                  for selected in [[r for r in source_rows if r["dataset"] == dataset and r["group"] == group]]}
        for dataset in DATASETS
    }
    result["label_counts"] = {arm: dict(Counter(slot[f"{arm}_label"] for r in source_rows for slot in r["slots"])) for arm in ("initial", "followup")}
    result["statistical_limit"] = (
        f"At most {len(sources) // 2} sources per group; no reliable low-FPR or superiority claim."
    )
    if REPORT.is_file() and json.loads(REPORT.read_text(encoding="utf-8")) != result:
        raise RuntimeError("report_drift")
    if not REPORT.is_file():
        write_json(result, REPORT)
    print(json.dumps({"stage": "report", "sources": len(source_rows), "calls": result["calls"], "groups": groups, "report_sha256": sha256_file(REPORT)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "generate", "replay-generation", "freeze-queries", "retrieve", "run-initial", "run-followup", "report"):
        modes.add_argument("--" + name, action="store_true")
    parser.add_argument("--max-new", type=int, default=0)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--reuse-source-plan", type=Path)
    parser.add_argument("--pairs-per-dataset", type=int)
    parser.add_argument("--exclude-source-plan", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.output_dir is not None:
        _set_output_dir(args.output_dir)
    if args.reuse_source_plan is not None and not args.prepare:
        parser.error("--reuse-source-plan requires --prepare")
    external = args.generate or args.run_initial or args.run_followup
    if external and not 1 <= args.max_new <= MAX_VICTIM:
        parser.error(f"external calls require --max-new in [1, {MAX_VICTIM}]")
    if args.generate and args.max_new > MAX_LUNA:
        parser.error(f"Luna pilot budget is {MAX_LUNA}")
    if not external and args.max_new:
        parser.error("--max-new only applies to external calls")
    if args.prepare:
        pair_quotas = (
            {dataset: args.pairs_per_dataset for dataset in DATASETS}
            if args.pairs_per_dataset is not None
            else None
        )
        prepare(
            args.reuse_source_plan,
            pair_quotas=pair_quotas,
            excluded_source_plans=args.exclude_source_plan,
        )
    elif args.replay_generation:
        replay_generation()
    elif args.generate:
        if args.max_new > MAX_LUNA:
            parser.error(f"Luna pilot budget is {MAX_LUNA}")
        generate(args.max_new)
    elif args.freeze_queries:
        freeze_queries()
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
