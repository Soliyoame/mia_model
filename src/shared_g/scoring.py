"""答案表面匹配、逐槽门控和 source-level 赋分。"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from src.llm.response_validation import detect_api_error_text
from src.utils.hash import sha256_obj, sha256_text
from .types import ARMS, QueryRecord, ResponseRecord, ScoreRecord, SourceRecord

LEGACY_MATCHER = "canonical_surface_v2_frozen_format_aliases"
REPAIRED_MATCHER = "canonical_surface_v3_token_boundaries_scoped_abstention"

def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def surface_present(text: str, surface: str) -> bool:
    haystack = normalize(text)
    needle = normalize(surface)
    if not needle:
        return False
    pattern = re.escape(needle).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", haystack) is not None


def formatting_answer_aliases(answer: str) -> list[str]:
    """生成保守、与响应无关的格式 alias。"""
    text = unicodedata.normalize("NFKC", str(answer or "")).strip()
    text = text.replace("$$", " ").replace("$", " ")
    text = re.sub(r"\\(?:,|;|:|!|quad|qquad)\s*", " ", text)
    text = text.replace(r"\%", "%")
    text = re.sub(r"\\(?:text|mathrm|mathbf)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\([_{}])", r"\1", text)
    text = text.translate(str.maketrans({
        "–": "-", "—": "-", "−": "-", "×": "x",
        "‘": "'", "’": "'", "“": '"', "”": '"',
    }))
    text = re.sub(r"[*_`]", "", text)
    text = re.sub(r'(?<![a-z0-9])"([^"\r\n]+)"(?![a-z0-9])', r"\1", text, flags=re.I)
    text = re.sub(r"\s*([.,%/():\-])\s*", r"\1", text)
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    text = re.sub(r"(\d+(?:\.\d+)?%)\1(?=\s|$)", r"\1", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n,.;:")
    aliases = [text] if text and normalize(text) != normalize(answer) else []
    return aliases


def _legacy_response_label(
    response: str,
    answer: str,
    status: str = "completed",
    answer_aliases: list[str] | None = None,
) -> str:
    if status != "completed" or not str(response or "").strip() or detect_api_error_text(response):
        return "invalid"
    translation = str.maketrans({"–": "-", "—": "-", "−": "-", "×": "x"})
    text = unicodedata.normalize("NFKC", str(response)).translate(translation).casefold()
    text = re.sub(r"[*_`]", "", text)
    text = re.sub(r"\s*([.,%/():\-])\s*", r"\1", text)
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    if re.search(
        r"\b(?:unknown|cannot|can't|not sure|unclear|don['’]t know|does not|doesn't|"
        r"do not|don't|not contain|not specify|not provide|no information)\b",
        text,
        re.I,
    ):
        return "ambiguous"
    for candidate in [answer, *(answer_aliases or [])]:
        target = unicodedata.normalize("NFKC", str(candidate)).translate(translation).casefold()
        target = re.sub(r"[*_`]", "", target)
        target = re.sub(r"\s*([.,%/():\-])\s*", r"\1", target)
        target = re.sub(r"(?<=\d)\s+(?=\d)", "", target)
        pattern = re.escape(re.sub(r"\s+", " ", target).strip()).replace(r"\ ", r"\s+")
        if pattern and re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text):
            return "correct"
    return "incorrect"


def _answer_tokens(value: str) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.translate(str.maketrans({
        "–": "-", "—": "-", "−": "-", "‑": "-", "×": "x", "’": "'", "±": "+/-",
    }))
    text = re.sub(r"[*_`]", "", text)
    text = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", text)
    # 仅合并合法千位分组；不把列表、任意相邻数字或小数拆成局部答案。
    text = re.sub(r"(?<![\w.,])\d{1,3}(?:(?:,\s*| )\d{3})+(?![\w,])",
                  lambda match: re.sub(r"[ ,]", "", match.group()), text)
    return re.findall(r"\d+(?:\.\d+)+(?:e[+-]?\d+)?|\w+(?:'\w+)*|[^\w\s]", text)


_ABSTENTION = re.compile(
    r"\b(?:i|we) (?:do not know|don't know|am not sure|are not sure|am unsure|are unsure)\b|"
    r"\b(?:cannot|can't|could not|unable to) (?:determine|tell|answer|find|identify|confirm|infer)\b|"
    r"\b(?:does not|doesn't|do not|don't|did not|didn't) "
    r"(?:(?:explicitly|directly|clearly) )?(?:contain|provide|specify|state|mention|include|give)\b|"
    r"\b(?:not (?:specified|provided|stated|mentioned|reported)|"
    r"(?:no|insufficient|not enough) (?:relevant |specific )?(?:information|evidence|context|details))\b"
)
_UNCERTAINTY = re.compile(r"\b(?:unknown|unclear|uncertain|not sure|don't know|do not know)\b")
_NEGATION = re.compile(r"\b(?:not|no|never|neither|without|cannot|can't|doesn't|don't|didn't)\b")


def repaired_judgment(
    response: str, answer: str, status: str = "completed",
    answer_aliases: list[str] | None = None, *, question: str = "",
) -> dict[str, str | None]:
    """保守表面匹配修复；不承担同义改写、对象一致性或列表完备性的语义审查。"""
    def result(label: str, reason: str, matched: str | None = None) -> dict[str, str | None]:
        return {"label": label, "reason": reason, "matched_answer": matched}

    if status != "completed" or not str(response or "").strip() or detect_api_error_text(response):
        return result("invalid", "invalid_response")
    tokens = _answer_tokens(response)
    text = " ".join(tokens)
    question_text = " ".join(_answer_tokens(question))
    asks_uncertainty = bool(_UNCERTAINTY.search(question_text))
    blocked: str | None = None
    for candidate in [answer, *(answer_aliases or [])]:
        target = _answer_tokens(candidate)
        if not target:
            continue
        for start in range(len(tokens) - len(target) + 1):
            end = start + len(target)
            if tokens[start:end] != target:
                continue
            # 数字答案不能命中带反号、百分比、范围或分数中的局部数字。
            numeric_start = bool(re.fullmatch(r"\d+(?:\.\d+)?", target[0]))
            numeric_end = bool(re.fullmatch(r"\d+(?:\.\d+)?", target[-1]))
            if ((numeric_start and start and tokens[start - 1] in {"-", "+", "/", ".", "<", ">", "≤", "≥"})
                    or (numeric_end and end < len(tokens) and tokens[end] in {"%", "/", "-", "+", "<", ">", "≤", "≥"})):
                blocked = "numeric_boundary_conflict"
                continue
            remainder = " ".join([*tokens[:start], "ANSWER", *tokens[end:]])
            if _ABSTENTION.search(remainder):
                blocked = "explicit_abstention_outside_answer"
                continue
            if _UNCERTAINTY.search(remainder) and not asks_uncertainty:
                blocked = "uncertainty_outside_answer"
                continue
            left = start
            while left and tokens[left - 1] not in {".", ";", ",", "!", "?"}:
                left -= 1
            prefix = tokens[left:start]
            if "but" in prefix:
                prefix = prefix[len(prefix) - prefix[::-1].index("but"):]
            # 答案后的否定可能修饰另一属性；问题中同样的否定谓词也不否定答案槽。
            prefix_text = " ".join(prefix)
            unaligned_negation = False
            for negation in _NEGATION.finditer(prefix_text):
                tail = prefix_text[negation.end():].strip().split()
                predicate = negation.group() + " " + " ".join(tail[:2])
                if not tail or predicate not in question_text:
                    unaligned_negation = True
            if unaligned_negation:
                blocked = "negation_before_answer_not_aligned_with_question"
                continue
            return result("correct", "canonical_or_frozen_alias_token_match", candidate)
    if blocked:
        return result("ambiguous" if blocked != "numeric_boundary_conflict" else "incorrect", blocked)
    if _ABSTENTION.search(text) or (_UNCERTAINTY.search(text) and not asks_uncertainty):
        return result("ambiguous", "abstention_without_answer")
    return result("incorrect", "no_canonical_or_frozen_alias_match")


def response_label(
    response: str, answer: str, status: str = "completed",
    answer_aliases: list[str] | None = None, *, matcher: str = LEGACY_MATCHER, question: str = "",
) -> str:
    if matcher == LEGACY_MATCHER:
        return _legacy_response_label(response, answer, status, answer_aliases)
    if matcher == REPAIRED_MATCHER:
        return str(repaired_judgment(response, answer, status, answer_aliases, question=question)["label"])
    raise ValueError("unknown_answer_matcher")


def answer_judgment(
    response: ResponseRecord, query: QueryRecord, *, matcher: str = LEGACY_MATCHER,
    adjudications: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    automatic = response_label(response.get("response", ""), query["answer"], response.get("status", "invalid"),
                               query.get("answer_aliases"), matcher=matcher, question=query.get("question", ""))
    result = {"label": automatic, "automatic_label": automatic, "label_source": "automatic",
              "review_status": None, "reason": matcher}
    decision = (adjudications or {}).get(query.get("query_id", ""))
    if decision is None or automatic == "invalid":
        return result
    if (decision.get("query_id") != query["query_id"]
            or response.get("query_id") != query["query_id"]
            or response.get("source_key") != query["source_key"]
            or decision.get("source_key") != query["source_key"]
            or decision.get("query_sha256") != sha256_obj(query)
            or decision.get("response_sha256") != sha256_text(response.get("response", ""))):
        raise RuntimeError("response_adjudication_identity_drift")
    if (decision.get("label") not in {"correct", "incorrect", "ambiguous"}
            or decision.get("review_status") not in {"resolved", "uncertain"}
            or (decision.get("review_status") == "uncertain" and decision.get("label") != "ambiguous")
            or not isinstance(decision.get("reason"), str) or not decision["reason"].strip()):
        raise RuntimeError("invalid_response_adjudication")
    return {"label": decision["label"], "automatic_label": automatic,
            "label_source": "assistant_post_response", "review_status": decision["review_status"],
            "reason": decision["reason"]}


def answer_label(
    response: ResponseRecord, query: QueryRecord, *, matcher: str = LEGACY_MATCHER,
    adjudications: dict[str, dict[str, Any]] | None = None,
) -> str:
    return str(answer_judgment(response, query, matcher=matcher, adjudications=adjudications)["label"])


def gated_queries(
    queries: list[QueryRecord], initial: list[ResponseRecord], *, matcher: str = LEGACY_MATCHER,
    adjudications: dict[str, dict[str, Any]] | None = None,
) -> list[QueryRecord]:
    planned = {row["query_id"]: row for row in queries if row["arm"] == "initial"}
    observed = {row["query_id"]: row for row in initial}
    if set(planned) != set(observed) or len(observed) != len(initial):
        raise RuntimeError("initial_response_set_incomplete")
    if any(row.get("status") != "completed" for row in initial) or any(answer_label(observed[key], query, matcher=matcher, adjudications=adjudications) == "invalid" for key, query in planned.items()):
        raise RuntimeError("initial_response_invalid_run_incomplete")
    triggered = {(query["source_key"], query["slot_index"]) for key, query in planned.items()
                 if answer_label(observed[key], query, matcher=matcher, adjudications=adjudications) == "correct"}
    return [row for row in queries if row["arm"] in ARMS
            and (row["source_key"], row["slot_index"]) in triggered]


def source_scores(
    sources: list[SourceRecord], queries: list[QueryRecord],
    initial: list[ResponseRecord], followup: list[ResponseRecord], weight: float, *, matcher: str = LEGACY_MATCHER,
    adjudications: dict[str, dict[str, Any]] | None = None,
) -> list[ScoreRecord]:
    expected = gated_queries(queries, initial, matcher=matcher, adjudications=adjudications)
    if {row["query_id"] for row in expected} != {row["query_id"] for row in followup}:
        raise RuntimeError("followup_gate_missing_or_extra")
    responses = {row["query_id"]: row for row in initial + followup}
    if len(responses) != len(initial) + len(followup):
        raise RuntimeError("response_id_collision")
    query_map = {row["query_id"]: row for row in queries}
    if any(row.get("status") != "completed" or answer_label(row, query_map[key], matcher=matcher, adjudications=adjudications) == "invalid"
           for key, row in responses.items()):
        raise RuntimeError("invalid_response_run_incomplete")
    lookup = {(row["source_key"], row["arm"], row["slot_index"]): row for row in queries}
    rows = []
    for source in sources:
        key = source["source_key"]
        local = [int(answer_label(responses[lookup[key, "initial", i]["query_id"]],
                                  lookup[key, "initial", i], matcher=matcher, adjudications=adjudications) == "correct") for i in range(3)]
        record = {"source_key": key, "dataset": source["dataset"], "group": source["group"],
                  "initial_bits": local, "local_only": sum(local)}
        for arm in ARMS:
            bits = [int(local[i] and answer_label(
                responses[lookup[key, arm, i]["query_id"]], lookup[key, arm, i], matcher=matcher, adjudications=adjudications) == "correct")
                    for i in range(3)]
            record[f"{arm}_bits"] = bits
            record[arm] = sum(local) + weight * sum(bits)
        rows.append(record)
    return rows
