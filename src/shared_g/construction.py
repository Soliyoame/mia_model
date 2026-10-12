"""Luna 事实构造、结构门禁和 membership-blind 预审材料。"""

from __future__ import annotations

import json
import http.client
import logging
import re
import urllib.error
from typing import Any

from src.llm.factory import build_role_chat_client, llm_profile_identity, load_llm_profiles
from src.llm.openai_compatible import OpenAICompatibleChatClient
from src.llm.response_validation import generator_response_error
from src.utils.hash import sha256_file, sha256_obj, sha256_text
from .artifacts import (ArtifactStore, append_request, read_json, read_rows, request_records,
                        unique_map, write_json_atomic)
from .config import ExperimentConfig
from .queries import anchored_question as _anchored_question
from .scoring import normalize as _norm, surface_present as _surface_present
from .sources import read_source_text

GENERATION_PROMPT = r"""
Use only the source below. Return JSON only with exactly these keys:
initial_facts, remote_target.

initial_facts must contain exactly e1, e2, e3. Each item has slot, claim, answer,
and question. Each claim must be one complete, contiguous, source-supported
sentence or clause. Choose a minimal exact answer span that answers only what the
question asks; do not add counts, percentages, confidence intervals, units, or
qualifiers that the question does not request. Write the question around that
answer span. The question must stand alone and must not contain its answer.

remote_target is one source-grounded fact G with claim, answer, question, and
region_hint. G must be atomic, have a short, checkable answer, and be a specific
fact rather than a broad conclusion. Prefer evidence from a different
sentence/paragraph/region than all three local claims; this is a preference, not
a reason to invent a fact. All four facts must refer to the same focal study,
cohort, intervention, or source-level subject. If the source describes separate
studies, do not mix local facts from one study with G from another. If no such
set is supported, return the insufficient-facts shape below.

The G question is the one canonical wording reused by both follow-up arms. It
may include a source-supported population, intervention, disease, or other
condition needed to identify exactly which G fact is requested, even when that
condition overlaps a local answer. It must not contain G's answer. G must not be
directly answerable or entailed by the three local claims alone. Make the answer
granularity exact: a count question gets only the count; a question asking for
two values gets both values and no unrelated statistic; when asking what was
used, include both items if the claim names two measures joined by "and". Ask
for a complete list only when the source makes the list exhaustive.

Do not generate anchored or remote-only follow-up questions. The runner freezes
them from this one G question: remote-only reuses it verbatim; each anchored
question quotes its paired local claim as source context and then reuses the
same G question verbatim. Thus the target predicate and requested answer cannot
drift across slots or arms. The local claim is a retrieval locator, not a
logical premise for deriving G.

Questions must be understandable independently, with their referent named in
the question itself. Do not rely on another question, answer, source paragraph,
or conversation turn. Avoid unresolved demonstratives/pronouns such as "this
perception", "these pathogens", "their response times", "the phenomenon", "the
other review", and "the two teas"; name the relevant entity, condition, and
comparison instead. Avoid putting any part of the requested answer in the
question. Keep answers short (at most 12 words), exact, source-grounded, and
non-duplicated across the three local slots and G.

Claims and canonical answers must be copied verbatim from the source. Do not
invent, normalize, or repair text. Every question ends with exactly one question
mark. Return {{"initial_facts": [], "remote_target": null}} only if the source
cannot support three atomic local facts and one atomic remote target.

Required shape:
{
  "initial_facts": [
    {"slot":"e1","claim":"...","answer":"...","question":"...?"},
    {"slot":"e2","claim":"...","answer":"...","question":"...?"},
    {"slot":"e3","claim":"...","answer":"...","question":"...?"}
  ],
  "remote_target": {"claim":"...","answer":"...","question":"...?","region_hint":"..."}
}

Source:
{source}
""".strip()


REPAIR_SUFFIX = r"""

This is a construction repair. Return exactly the two-key schema
initial_facts, remote_target. Copy each claim and answer as a complete contiguous
source span, including source punctuation. Recheck that every question is
self-contained, asks for exactly its canonical answer, and contains no answer
leak. Keep local facts and G tied to the same focal study or cohort. Do not
generate follow-up questions; the runner derives both arms from the one canonical
G question. Do not invent facts or broaden a specific target into a summary.

Previous validator feedback to fix:
{validation_feedback}
""".strip()


def _build_construction_prompt(
    source_text: str,
    prompt_template: str = GENERATION_PROMPT,
    previous_attempt: dict[str, Any] | None = None,
) -> str:
    prompt = prompt_template
    if previous_attempt is not None:
        feedback = previous_attempt.get("quality_reasons") or [
            previous_attempt.get("error_type") or previous_attempt.get("status") or "previous_attempt_failed"
        ]
        feedback_text = ", ".join(sorted({str(item) for item in feedback if str(item)}))
        repair = REPAIR_SUFFIX.replace("{validation_feedback}", feedback_text)
        prompt = f"{prompt}\n\n{repair}"
    return prompt.replace("{source}", source_text)


def _omits_coordinated_used_item(claim: str, answer: str, question: str) -> bool:
    if not re.search(r"\bwhat\b.*\bused\b", question, re.I | re.S):
        return False
    match = re.search(
        r"(?P<first>[^.!?;]+?)\s+and\s+(?P<second>[^.!?;]+?)\s+"
        r"(?:have|were|are)\s+(?:been\s+)?used\b",
        claim,
        re.I,
    )
    if not match:
        return False
    included = (
        _surface_present(answer, match.group("first").strip()),
        _surface_present(answer, match.group("second").strip()),
    )
    return sum(included) == 1


def _remove_trailing_commas(text: str) -> tuple[str, int]:
    output: list[str] = []
    in_string = False
    escaped = False
    removed = 0
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "]}":
                removed += 1
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output), removed


def _parse_json_with_diagnostics(content: str) -> tuple[Any, list[str]]:
    text = str(content or "").strip()
    diagnostics: list[str] = []
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        diagnostics.append("code_fence_removed")
    try:
        return json.loads(text), diagnostics
    except json.JSONDecodeError:
        repaired, count = _remove_trailing_commas(text)
        if not count:
            raise
        payload = json.loads(repaired)
        diagnostics.append(f"trailing_commas_removed:{count}")
        return payload, diagnostics


def _validate_question(question: Any, forbidden: list[str]) -> list[str]:
    reasons: list[str] = []
    text = str(question or "").strip()
    if not text or text.count("?") != 1 or not text.endswith("?"):
        reasons.append("question_shape")
    if any(answer and _surface_present(text, answer) for answer in forbidden):
        reasons.append("question_answer_leak")
    if re.search(
        r"\b(?:the above|above[- ]mentioned|previous (?:question|answer|response|passage|text|context)|"
        r"preceding (?:question|answer|response|passage|text|context)|earlier (?:question|answer|response|passage|text|context)|"
        r"this result|that result|mentioned above|described above|this perception|these pathogens|"
        r"these parameters|these types of|these two RATs?|this case|this time frame|this infection|"
        r"this particular application|this scourge|those included|the phenomenon|the other|the former|the latter|"
        r"one of (?:the )?two|the two (?:teas|reviews|RATs?|radio access technologies|models|groups)|"
        r"their behavioral response times)\b",
        text,
        re.I,
    ):
        reasons.append("question_unresolved_reference")
    return reasons


def _region_index(source_text: str, claim: str) -> int | None:
    start = source_text.find(claim)
    if start < 0:
        return None
    # 以句子与段落边界记录区域诊断。
    return len(re.findall(r"[.!?\n]{1,2}", source_text[:start]))


def _validate_generation(payload: Any, source_text: str) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload, dict):
        return {}, ["schema_object"]
    initial = payload.get("initial_facts")
    target = payload.get("remote_target")
    if initial == [] and target is None:
        return {}, ["insufficient_atomic_facts"]
    if not isinstance(initial, list) or len(initial) != 3:
        return {}, ["initial_size"]
    if not isinstance(target, dict):
        return {}, ["shared_g_schema"]
    reasons: list[str] = []
    initial_records: list[dict[str, str]] = []
    answers: list[str] = []
    for index, row in enumerate(initial, 1):
        if not isinstance(row, dict):
            reasons.append(f"e{index}_schema")
            initial_records.append({"slot": f"e{index}", "claim": "", "answer": "", "question": ""})
            answers.append("")
            continue
        for field in ("claim", "answer", "question"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                reasons.append(f"e{index}_{field}_required_string")
        slot = str(row.get("slot") or "")
        claim, answer, question = (str(row.get(field) or "").strip() for field in ("claim", "answer", "question"))
        if slot != f"e{index}":
            reasons.append(f"e{index}_slot")
        if not claim or claim not in source_text:
            reasons.append(f"e{index}_claim_not_verbatim")
        if not _surface_present(claim, answer):
            reasons.append(f"e{index}_answer_not_in_claim")
        reasons.extend(f"e{index}_{item}" for item in _validate_question(question, [answer]))
        initial_records.append({"slot": f"e{index}", "claim": claim, "answer": answer, "question": question})
        answers.append(answer)
    for field in ("claim", "answer", "question"):
        if not isinstance(target.get(field), str) or not target[field].strip():
            reasons.append(f"G_{field}_required_string")
    target_claim = str(target.get("claim") or "").strip()
    target_answer = str(target.get("answer") or "").strip()
    target_question = str(target.get("question") or "").strip()
    if not target_claim or target_claim not in source_text:
        reasons.append("G_claim_not_verbatim")
    if not _surface_present(target_claim, target_answer):
        reasons.append("G_answer_not_in_claim")
    if _omits_coordinated_used_item(target_claim, target_answer, target_question):
        reasons.append("G_answer_incomplete_coordinated_items")
    if _norm(target_answer) in {_norm(answer) for answer in answers}:
        reasons.append("G_duplicate_local_answer")
    # 必要的源文条件可以重叠 local answer；canonical G 问句禁止透露 G 答案。
    reasons.extend(f"G_{item}" for item in _validate_question(target_question, [target_answer]))
    if len(target_answer) < 2:
        reasons.append("G_answer_too_short")
    target_record = {
        "claim": target_claim,
        "answer": target_answer,
        "question": target_question,
        "region_hint": str(target.get("region_hint") or "").strip(),
    }
    anchored_records = []
    no_anchor_records = []
    for index, fact in enumerate(initial_records, 1):
        slot = f"e{index}_prime"
        anchor = fact["answer"]
        anchor_claim = fact["claim"]
        question = _anchored_question(anchor_claim, target_question)
        if not _surface_present(anchor_claim, anchor):
            reasons.append(f"{slot}_anchor_not_in_question")
        for other_index, other_answer in enumerate(answers, 1):
            if other_index != index and _surface_present(anchor_claim, other_answer):
                reasons.append(f"{slot}_anchor_cross_slot_answer_leak")
        reasons.extend(f"{slot}_{item}" for item in _validate_question(question, [target_answer]))
        anchored_records.append({
            "slot": slot,
            "paired_initial_slot": f"e{index}",
            "anchor": anchor,
            "anchor_claim": anchor_claim,
            "question": question,
        })
        no_anchor_records.append({
            "slot": slot,
            "paired_initial_slot": f"e{index}",
            "question": target_question,
        })
    # 跨区域是偏好，记录诊断而不作为硬门禁。
    target_region = _region_index(source_text, target_claim)
    local_regions = [_region_index(source_text, row["claim"]) for row in initial_records]
    if target_region is None:
        reasons.append("G_region_unknown")
    records = {
        "initial_facts": initial_records,
        "remote_target": target_record,
        "anchored_followups": anchored_records,
        "no_anchor_followups": no_anchor_records,
        "region_diagnostics": {
            "local_regions": local_regions,
            "remote_region": target_region,
            "different_region_count": sum(
                int(target_region is not None and region is not None and target_region != region)
                for region in local_regions
            ),
            "relation": "different_preferred" if target_region is not None else "unknown",
        },
    }
    return records, sorted(set(reasons))


def validate_construction(
    payload: Any, source_text: str, maximum_answer_words: int,
) -> tuple[dict[str, Any], list[str]]:
    records, reasons = _validate_generation(payload, source_text)
    if not records:
        return records, reasons
    answers = [fact["answer"] for fact in records["initial_facts"]]
    target_answer = records["remote_target"]["answer"]
    if any(len(answer.split()) > maximum_answer_words for answer in [*answers, target_answer]):
        reasons.append("answer_too_long")
    if any(_surface_present(fact["claim"], target_answer)
           for fact in records["initial_facts"]):
        reasons.append("G_answer_in_local_claim")
    return records, sorted(set(reasons))


def generation_records(store: ArtifactStore) -> dict[str, dict[str, Any]]:
    rows = request_records(store.path("generation.jsonl"))
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["source_key"]
        previous = latest.get(key)
        expected = 1 if previous is None else previous["attempt"] + 1
        if row["attempt"] != expected or expected > 2:
            raise RuntimeError("construction_attempt_order_or_budget_drift")
        if previous is not None and previous["status"] != "failed_quality_gate":
            raise RuntimeError("construction_retry_not_structural_failure")
        if row.get("raw_response") is not None and row["response_sha256"] != sha256_text(row["raw_response"]):
            raise RuntimeError("generation_response_hash_drift")
        if row["status"] != "attempt_started" and row.get("record_sha256") != sha256_obj(
                {key: value for key, value in row.items() if key != "record_sha256"}):
            raise RuntimeError("generation_record_drift")
        latest[key] = row
    return latest


def _request_error_details(exc: Exception) -> dict[str, Any]:
    """只记录异常类型和 HTTP 状态，不保存可能包含凭据的异常原文。"""
    cause = exc.__cause__ or exc
    details = {"error_type": type(exc).__name__, "cause_type": type(cause).__name__,
               "transient_error": isinstance(cause, (urllib.error.URLError, OSError, http.client.HTTPException))}
    if isinstance(cause, urllib.error.HTTPError):
        details.update(http_status=cause.code,
                       transient_error=cause.code in OpenAICompatibleChatClient._RETRYABLE_STATUS)
    return details


class _WireRequestBudget:
    """沿用总调用上限，每次实际 HTTP 发送前更新一个普通计数字段。"""

    def __init__(self, store: ArtifactStore, limiter: Any, limit: int, previous_calls: int,
                 counter_key: str = "construction_wire_calls"):
        self.store, self.limiter, self.limit = store, limiter, limit
        self.calls = previous_calls
        if counter_key not in ("construction_wire_calls", "semantic_review_wire_calls"):
            raise ValueError("unknown_wire_counter")
        self.counter_key = counter_key
        self.other_key = ("semantic_review_wire_calls" if counter_key == "construction_wire_calls"
                          else "construction_wire_calls")
        other_file = ("semantic_review_requests.jsonl" if counter_key == "construction_wire_calls"
                      else "generation.jsonl")
        run = read_json(store.path("run_config.json"))
        self.other_calls = run.get(self.other_key)
        if self.other_calls is None:
            self.other_calls = sum(row.get("transport_request_count", 1 + row.get("retry_count", 0))
                                   for row in request_records(store.path(other_file)))

    @property
    def total_calls(self) -> int:
        return self.calls + self.other_calls

    def acquire(self) -> None:
        if self.total_calls >= self.limit:
            raise RuntimeError("construction_call_budget_exhausted")
        if self.limiter is not None:
            self.limiter.acquire()
        run = read_json(self.store.path("run_config.json"))
        if (run.get(self.counter_key, self.calls) != self.calls
                or run.get(self.other_key, self.other_calls) != self.other_calls):
            raise RuntimeError("concurrent_construction_writer_forbidden")
        run[self.counter_key] = self.calls + 1
        write_json_atomic(self.store.path("run_config.json"), run)
        self.calls += 1
        logging.getLogger(__name__).info("%s=%d total_calls=%d", self.counter_key, self.calls,
                                        self.total_calls)


def _reviewer_type(decisions: dict[str, dict[str, Any]]) -> str:
    kinds = {decision.get("reviewer_type", "assistant_membership_blind")
             for decision in decisions.values()}
    if not kinds:
        return "assistant_membership_blind"
    return next(iter(kinds)) if len(kinds) == 1 else "mixed_membership_blind"


def _validate_review_decisions(store: ArtifactStore, saved: dict[str, dict[str, Any]],
                               decisions: dict[str, dict[str, Any]]) -> None:
    base = {"generation_record_sha256", "accepted", "reason"}
    for key, decision in decisions.items():
        row = saved.get(key)
        fields = set(decision)
        if (row is None or row["status"] != "passed"
                or fields not in (base, base | {"reviewer_type", "review_request_key"})
                or decision["generation_record_sha256"] != row["record_sha256"]
                or type(decision["accepted"]) is not bool
                or not isinstance(decision["reason"], str)
                or (not decision["accepted"] and not decision["reason"].strip())
                or (fields != base and decision.get("reviewer_type") != "ai_membership_blind")):
            raise RuntimeError("semantic_review_generation_record_drift")
    if any(decision.get("reviewer_type") == "ai_membership_blind" for decision in decisions.values()):
        from .review import validate_ai_review_decisions
        validate_ai_review_decisions(store, saved, decisions)


def review_decisions(store: ArtifactStore, generations: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    path = store.path("semantic_review.json")
    if not path.exists():
        return {}
    review = read_json(path)
    if review.get("reviewer_type") not in (
            "assistant_membership_blind", "ai_membership_blind", "mixed_membership_blind"):
        raise RuntimeError("semantic_review_identity_drift")
    saved = generation_records(store) if generations is None else generations
    decisions = review.get("decisions")
    if not isinstance(decisions, dict):
        raise RuntimeError("semantic_review_decision_schema_invalid")
    _validate_review_decisions(store, saved, decisions)
    adjudications = review.get("assistant_adjudications", {})
    if (not isinstance(adjudications, dict) or any(
            key not in decisions or decisions[key].get("reviewer_type") != "ai_membership_blind"
            or decisions[key]["accepted"] or not isinstance(value, dict)
            or set(value) != {"generation_record_sha256", "accepted", "reason"}
            or not isinstance(value["reason"], str) or not value["reason"].strip()
            for key, value in adjudications.items())):
        raise RuntimeError("assistant_adjudication_schema_invalid")
    _validate_review_decisions(store, saved, adjudications)
    resolved = {**decisions, **adjudications}
    if review["reviewer_type"] != _reviewer_type(resolved):
        raise RuntimeError("semantic_review_identity_drift")
    return resolved


def save_review(config: ExperimentConfig, store: ArtifactStore,
                decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run = store.validate()
    if run.get("frozen_artifacts"):
        raise RuntimeError("semantic_review_already_frozen")
    saved = generation_records(store)
    review_decisions(store, saved)
    path = store.path("semantic_review.json")
    review = read_json(path) if path.exists() else {"decisions": {}}
    previous = review["decisions"]
    for key, decision in decisions.items():
        if key in previous and previous[key] != decision:
            raise RuntimeError("refuse_semantic_review_decision_overwrite")
    _validate_review_decisions(store, saved, decisions)
    combined = {**previous, **decisions}
    adjudications = review.get("assistant_adjudications", {})
    review.update(reviewer_type=_reviewer_type({**combined, **adjudications}), decisions=combined)
    write_json_atomic(path, review)
    return {"stage": "review", "reviewed_sources": len(previous.keys() | decisions.keys())}


def save_assistant_adjudication(config: ExperimentConfig, store: ArtifactStore,
                               decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """追加 Assistant 对 AI 退回来源的复核；AI 原判及原始响应始终保留。"""
    run = store.validate()
    if run.get("frozen_artifacts"):
        raise RuntimeError("semantic_review_already_frozen")
    saved = generation_records(store)
    previous = review_decisions(store, saved)
    review = read_json(store.path("semantic_review.json"))
    adjudications = review.get("assistant_adjudications", {})
    for key, decision in decisions.items():
        original = review["decisions"].get(key)
        if (original is None or original.get("reviewer_type") != "ai_membership_blind"
                or original["accepted"] or set(decision) != {"generation_record_sha256", "accepted", "reason"}
                or not isinstance(decision["reason"], str) or not decision["reason"].strip()):
            raise RuntimeError("assistant_adjudication_requires_ai_rejection")
        if key in adjudications and adjudications[key] != decision:
            raise RuntimeError("refuse_assistant_adjudication_overwrite")
    _validate_review_decisions(store, saved, decisions)
    resolved = {**previous, **decisions}
    for dataset in config.datasets:
        provisional = sum(row["dataset"] == dataset and row["status"] == "passed"
                          for row in saved.values()) - sum(
                              saved[key]["dataset"] == dataset and not decision["accepted"]
                              for key, decision in resolved.items())
        if provisional > sum(config.data["source_selection"]["counts"][dataset].values()):
            raise RuntimeError("assistant_adjudication_quota_exceeded")
    review.update(assistant_adjudications={**adjudications, **decisions}, reviewer_type=_reviewer_type(resolved))
    write_json_atomic(store.path("semantic_review.json"), review)
    return {"stage": "review-adjudication", "assistant_adjudicated_sources": len(review["assistant_adjudications"])}


def validate_candidate_generations(candidates: list[dict[str, Any]], saved: dict[str, dict[str, Any]],
                                   profile_identity: dict[str, Any]) -> None:
    by_key = unique_map(candidates, "source_key")
    if any("group" in row for row in candidates) or set(saved) - set(by_key):
        raise RuntimeError("generation_candidate_pool_drift")
    for key, row in saved.items():
        if row["source_hash"] != by_key[key]["source_hash"] or row["profile_identity"] != profile_identity:
            raise RuntimeError("generation_identity_drift")
        if row["status"] not in ("passed", "failed_quality_gate", "uncertain_transport"):
            raise RuntimeError("unresolved_construction_request_preserved")
        if row["status"] == "uncertain_transport" and not row.get("error_type"):
            raise RuntimeError("construction_error_record_incomplete")
    for dataset in {row["dataset"] for row in candidates}:
        rows = [row for row in candidates if row["dataset"] == dataset]
        if [row["candidate_rank"] for row in rows] != list(range(len(rows))):
            raise RuntimeError("candidate_order_drift")
        attempted = {row["source_key"] for row in rows if row["source_key"] in saved}
        if attempted != {row["source_key"] for row in rows[:len(attempted)]}:
            raise RuntimeError("construction_skipped_candidate_order")


def qualification_progress(config: ExperimentConfig, store: ArtifactStore) -> dict[str, Any]:
    candidates = read_rows(store.path("candidate_manifest.jsonl"))
    saved = generation_records(store)
    validate_candidate_generations(candidates, saved, llm_profile_identity(config.profiles()["sibling"]))
    decisions = review_decisions(store, saved)
    adjudications = (read_json(store.path("semantic_review.json")).get("assistant_adjudications", {})
                    if store.path("semantic_review.json").exists() else {})
    result: dict[str, Any] = {}
    for dataset in config.datasets:
        rows = [row for row in candidates if row["dataset"] == dataset]
        keys = {row["source_key"] for row in rows}
        attempted = keys & saved.keys()
        passed = {key for key in attempted if saved[key]["status"] == "passed"}
        accepted = {key for key in keys & decisions.keys() if decisions[key]["accepted"]}
        rejected = (keys & decisions.keys()) - accepted
        target = sum(config.data["source_selection"]["counts"][dataset].values())
        result[dataset] = {"candidate_sources": len(rows), "attempted_sources": len(attempted),
                           "structural_pass": len(passed), "semantic_accepted": len(accepted),
                           "semantic_rejected": len(rejected), "review_pending": len(passed - decisions.keys()),
                           "assistant_adjudicated_sources": len(keys & adjudications.keys()),
                           "reviewer_counts": {kind: sum(
                               decisions[key].get("reviewer_type", "assistant_membership_blind") == kind
                               for key in keys & decisions.keys())
                               for kind in ("assistant_membership_blind", "ai_membership_blind")},
                           "structural_failures": sum(saved[key]["status"] == "failed_quality_gate"
                                                      and saved[key]["attempt"] == 2 for key in attempted),
                           "uncertain_call_sources": sum(saved[key]["status"] == "uncertain_transport" for key in attempted),
                           "target_qualified_sources": target,
                           "qualified_fraction_of_attempted": len(accepted) / len(attempted) if attempted else None,
                           "membership_assigned_after_qualification": True}
    return result


def generate(config: ExperimentConfig, store: ArtifactStore, dataset: str,
             max_new: int = 200) -> dict[str, Any]:
    run = store.validate()
    if run.get("frozen_artifacts"):
        raise RuntimeError("construction_already_frozen")
    candidates = read_rows(store.path("candidate_manifest.jsonl"))
    sources = [s for s in candidates if s["dataset"] == dataset]
    if dataset not in config.datasets or not 1 <= max_new <= 200:
        raise ValueError("invalid_dataset_or_wave_budget")
    saved = generation_records(store)
    profile = config.profiles()["sibling"]
    identity = llm_profile_identity(profile)
    validate_candidate_generations(candidates, saved, identity)
    decisions = review_decisions(store, saved)
    target = sum(config.data["source_selection"]["counts"][dataset].values())
    dataset_keys = {source["source_key"] for source in sources}
    rejected = {key for key in dataset_keys & decisions.keys() if not decisions[key]["accepted"]}
    provisional = sum(saved[key]["status"] == "passed" for key in dataset_keys & saved.keys()) - len(rejected)
    qualified = sum(decisions[key]["accepted"] for key in dataset_keys & decisions.keys())
    if provisional > target:
        raise RuntimeError("qualified_source_quota_exceeded")
    pending = [source for source in sources if source["source_key"] not in saved or
               (saved[source["source_key"]]["status"] == "failed_quality_gate"
                and saved[source["source_key"]]["attempt"] < 2)]
    policy = config.data["construction"]
    attempts = request_records(store.path("generation.jsonl"))
    total_calls = run.get("construction_wire_calls", sum(row.get("transport_request_count", 1 + row.get("retry_count", 0)) for row in attempts))
    review_calls = run.get("semantic_review_wire_calls", 0)
    max_new = min(max_new, max(0, policy["maximum_total_calls"] - total_calls - review_calls))
    if provisional == target or not pending or not max_new:
        status = ("qualified_complete" if qualified == target else "awaiting_semantic_review" if provisional == target
                  else "candidate_pool_exhausted" if not pending else "construction_call_budget_exhausted")
        return {"stage": "generate", "dataset": dataset, "new_calls": 0, "status": status,
                "qualified_sources": qualified, "review_pending": provisional - qualified,
                "target_qualified_sources": target, "total_calls": total_calls}
    profiles = load_llm_profiles({"llm_profiles_path": str(config.resolve(config.data["runtime"]["llm_profiles_path"]))})
    client, actual_profile = build_role_chat_client(profiles, "sibling", profile_name=config.data["query_generator"]["profile"])
    if llm_profile_identity(actual_profile) != identity:
        raise RuntimeError("construction_client_profile_drift")
    client.max_retries, client.retry_until_success = 0, True
    budget = _WireRequestBudget(store, client.request_rate_limiter, policy["maximum_total_calls"], total_calls)
    client.request_rate_limiter = budget
    template = GENERATION_PROMPT + "\n\n" + policy["prompt_appendix"]
    calls = 0
    fingerprints = {row.get("system_fingerprint") for row in attempts
                    if row.get("provider_model_id")}
    for source in pending:
        if provisional >= target or budget.total_calls >= policy["maximum_total_calls"]:
            break
        previous = saved.get(source["source_key"])
        while (calls < max_new and budget.total_calls < policy["maximum_total_calls"]
               and (previous is None or previous["attempt"] < 2)):
            text = read_source_text(config, source)
            prompt = _build_construction_prompt(text, template, previous)
            attempt = 1 if previous is None else previous["attempt"] + 1
            row = {"request_key": f"{source['source_key']}:construction:{attempt}",
                   "source_key": source["source_key"], "source_hash": source["source_hash"],
                   "dataset": dataset,
                   "attempt": attempt, "status": "attempt_started", "prompt_sha256": sha256_text(prompt),
                   "profile_identity": identity}
            append_request(store.path("generation.jsonl"), row)
            calls += 1
            calls_before_request = budget.calls
            try:
                result = client.chat_with_metadata(prompt, temperature=policy["temperature"],
                                                   max_tokens=policy["max_tokens"], timeout=profile["timeout"])
                row.update({"raw_response": result.content, "response_sha256": sha256_text(result.content),
                            "provider_model_id": result.provider_model_id, "provider_request_id": result.provider_request_id,
                            "system_fingerprint": result.system_fingerprint, "called_at": result.called_at,
                            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                            "latency_ms": result.latency_ms, "retry_count": result.retry_count})
                error = generator_response_error(result.content, provider_model_id=result.provider_model_id,
                                                 expected_model_id=profile["model"], require_provider_model_id=True)
                if error or (fingerprints and result.system_fingerprint not in fingerprints):
                    row.update(status="invalid_provider_response", error_type="ProviderResponseInvalid",
                               validation_code=error.split(":", 1)[0] if error else "fingerprint_drift")
                else:
                    fingerprints.add(result.system_fingerprint)
                    try:
                        payload, diagnostics = _parse_json_with_diagnostics(result.content)
                        records, reasons = validate_construction(payload, text, policy["maximum_answer_words"])
                    except (json.JSONDecodeError, TypeError, ValueError):
                        records, reasons, diagnostics = {}, ["invalid_json"], []
                    row.update(records=records, quality_reasons=reasons, parse_diagnostics=diagnostics,
                               status="failed_quality_gate" if reasons else "passed")
            except Exception as exc:
                row.update(status="uncertain_transport", **_request_error_details(exc))
            row["transport_request_count"] = budget.calls - calls_before_request
            if not row["transport_request_count"] and row.get("provider_model_id"):
                # 兼容不经过 HTTP transport 的 mock 客户端；生产客户端始终先 acquire。
                row["transport_request_count"] = 1 + row.get("retry_count", 0)
            row["record_sha256"] = sha256_obj(row)
            append_request(store.path("generation.jsonl"), row)
            saved[source["source_key"]] = previous = row
            logging.getLogger(__name__).info("construction dataset=%s wave_calls=%d status=%s", dataset, calls, row["status"])
            if row["status"] == "uncertain_transport":
                logging.getLogger(__name__).warning("construction terminal error cause=%s http_status=%s",
                    row.get("cause_type"), row.get("http_status"))
                raise RuntimeError("construction_api_error_stop_preserve_evidence")
            if row["status"] not in ("passed", "failed_quality_gate"):
                raise RuntimeError("construction_invalid_response_stop_preserve_evidence")
            if row["status"] == "passed":
                provisional += 1
                break
        if calls >= max_new:
            break
    return {"stage": "generate", "dataset": dataset, "new_calls": calls,
            "status": "awaiting_semantic_review" if provisional == target else "construction_in_progress",
            "qualified_sources": qualified, "review_pending": provisional - qualified,
            "target_qualified_sources": target, "total_calls": max(budget.calls, total_calls + calls)}


def review_packet(config: ExperimentConfig, store: ArtifactStore, start: int = 0,
                  count: int = 20, dataset: str | None = None) -> dict[str, Any]:
    store.validate()
    if start < 0 or count < 1 or (dataset is not None and dataset not in config.datasets):
        raise ValueError("invalid_review_slice")
    candidates = read_rows(store.path("candidate_manifest.jsonl"))
    sources = unique_map(candidates, "source_key")
    generations = generation_records(store)
    validate_candidate_generations(candidates, generations, llm_profile_identity(config.profiles()["sibling"]))
    decisions = review_decisions(store, generations)
    passed = [generations[row["source_key"]] for row in candidates
              if row["source_key"] in generations and generations[row["source_key"]]["status"] == "passed"
              and row["source_key"] not in decisions and (dataset is None or row["dataset"] == dataset)]
    return {"generation_sha256": sha256_file(store.path("generation.jsonl")),
            "reviewer_type": "assistant_membership_blind", "passed": len(passed),
            "criteria": "答案有源文依据且能正确回答问题；其他同样成立的答案不单独导致拒绝。",
            "records": [{"source_key": row["source_key"], "dataset": sources[row["source_key"]]["dataset"],
                         "generation_record_sha256": row["record_sha256"], "records": row["records"],
                         "source_text": read_source_text(config, sources[row["source_key"]])}
                        for row in passed[start:start + count]]}
