"""Independent v23 fact-layer extraction primitives.

This module deliberately does not reuse the r6 pair eligibility gates.  It
reuses only label-free candidate emission and source identity helpers, then
records fact validity, replacement availability, and retrieval diagnostics as
separate fields.  The module never accepts membership, response, Retriever,
or AUC fields.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from .attackability_selector import machine_format_compatible
from .entity_extractor import EntityExtractor
from .restoration_first_v23 import (
    ENTITY_SLOT,
    FORMAL_TYPES,
    _article_compatible,
    _balanced_delimiters,
    _mask_sentence,
    _remove_entity_spans,
    bounded_occurrence_count,
    canonical_sha256,
    content_tokens,
    fresh_extract_candidates,
    normalize_text,
    relation_signature,
    segment_propositions,
    text_sha256,
)
from ..utils.io import load_yaml


FACT_LAYER_SPECIFICATION_VERSION = "pcv-restoration-first-v23-fact-layer-r1"
STRUCTURED_TYPES = frozenset(
    {"DATE", "MONEY", "PERCENT", "NUMERIC_VALUE", "IDENTIFIER", "SECTION_ID"}
)
FORMAL_FACT_TYPES = frozenset(FORMAL_TYPES)

MAIL_HEADER_RE = re.compile(
    r"^\s*(?:from|to|cc|bcc|subject|sent|date|message-id|content-type)\s*:",
    re.IGNORECASE | re.UNICODE,
)
UNRESOLVED_REFERENCE_RE = re.compile(
    r"\b(?:this|that|these|those|here|there|above|below|aforementioned|former|"
    r"latter|he|she|it|they)\b",
    re.IGNORECASE | re.UNICODE,
)
GENERIC_ROLE_RE = re.compile(
    r"^(?:president|director|manager|officer|author|employee|customer|company|"
    r"department|team|group|system|service|product|agreement)$",
    re.IGNORECASE | re.UNICODE,
)
RELATION_CUE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|will|would|shall|should|"
    r"can|could|received|paid|sent|met|meet|discussed|signed|reported|increased|"
    r"decreased|acquired|sold|filed|approved|required|requires|expires|begins|"
    r"ends|contains|assigned|located|treated|measured|observed|compared)\b",
    re.IGNORECASE | re.UNICODE,
)
VERBISH_RE = re.compile(
    r"\b(?:[A-Za-z]+(?:ed|ing)|is|are|was|were|be|been|being|has|have|had|"
    r"will|would|shall|should|can|could|may|might|must)\b",
    re.IGNORECASE,
)
COMMON_PREDICATE_RE = re.compile(
    r"\b(?:remain(?:s|ed|ing)?|become(?:s|came|coming)?|appear(?:s|ed|ing)?|"
    r"include(?:s|d|ing)?|provide(?:s|d|ing)?|cover(?:s|ed|ing)?|state(?:s|d|ing)?|"
    r"define(?:s|d|ing)?|hold(?:s|held|ing)?|show(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)
MEASUREMENT_RE = re.compile(
    r"(?:[:=]\s*[-+]?\$?\d[\d,]*(?:\.\d+)?\s*[%A-Za-z$-]*|"
    r"\b[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|million|billion|thousand|"
    r"dollars?|years?|months?|days?|hours?)\b)",
    re.IGNORECASE,
)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def fact_signature(
    *,
    dataset: str,
    source_key: str,
    sentence: str,
    original_span: Sequence[int],
    effective_type: str,
) -> str:
    """Return a slot-aware fact identity for the fact-layer revision."""

    if len(original_span) != 2:
        raise ValueError("fact_layer_original_span_invalid")
    return canonical_sha256(
        {
            "kind": "v23_fact_layer_fact_signature",
            "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
            "dataset": dataset,
            "source_key": source_key,
            "sentence_hash": text_sha256(sentence.strip()),
            "original_span": [int(original_span[0]), int(original_span[1])],
            "effective_type": effective_type,
        }
    )


def predicate_kind(sentence: str) -> str:
    """Classify proposition shape without making the old cue list mandatory."""

    stripped = sentence.strip()
    if not stripped or MAIL_HEADER_RE.match(stripped):
        return "fragment_or_nominal"
    if MEASUREMENT_RE.search(stripped):
        return "measurement_assertion"
    if RELATION_CUE_RE.search(stripped):
        return "relational_assertion"
    if VERBISH_RE.search(stripped) or COMMON_PREDICATE_RE.search(stripped):
        return "relational_assertion"
    return "fragment_or_nominal"


def _valid_span(candidate: Mapping[str, Any], sentence: str) -> bool:
    span = candidate.get("original_span")
    original = candidate.get("original_entity")
    return (
        isinstance(span, (list, tuple))
        and len(span) == 2
        and all(isinstance(value, int) and not isinstance(value, bool) for value in span)
        and isinstance(original, str)
        and 0 <= span[0] < span[1] <= len(sentence)
        and sentence[span[0] : span[1]] == original
    )


def _dedupe_replacements(
    source_text: str,
    sentence: str,
    original: str,
    start: int,
    raw_pool: Any,
    effective_type: str,
) -> list[str]:
    if not isinstance(raw_pool, list) or not all(isinstance(value, str) for value in raw_pool):
        return []
    values: dict[str, str] = {}
    for replacement in raw_pool:
        normalized = normalize_text(replacement)
        if not normalized or normalized == normalize_text(original):
            continue
        if bounded_occurrence_count(source_text, replacement) > 0:
            continue
        if not machine_format_compatible(original, replacement, effective_type):
            continue
        if not _article_compatible(sentence[:start], replacement):
            continue
        claim = f"{sentence[:start]}{replacement}{sentence[start + len(original):]}"
        if not _balanced_delimiters(claim):
            continue
        values.setdefault(normalized, replacement)
    return [values[key] for key in sorted(values)]


def _matching_recoverability(
    candidate: Mapping[str, Any],
    *,
    source_text: str,
    sentence: str,
    original: str,
    effective_type: str,
) -> tuple[list[str], list[str], str]:
    """Return recovery errors, matching filler surfaces, and relation identity."""

    span = candidate.get("original_span")
    if not _valid_span(candidate, sentence):
        return ["exact_original_span"], [], ""
    masked = _mask_sentence(sentence, span)
    target_relation = relation_signature(
        dataset=str(candidate["dataset"]),
        source_key=str(candidate["source_key"]),
        effective_type=effective_type,
        masked_sentence=masked,
    )
    raw_inventory = candidate.get("filler_inventory")
    inventory = raw_inventory if isinstance(raw_inventory, list) else []
    matching = [
        item
        for item in inventory
        if isinstance(item, Mapping) and item.get("relation_signature") == target_relation
    ]
    propositions = {
        (item.get("proposition_raw_start"), item.get("proposition_raw_end"))
        for item in matching
    }
    original_matches = {
        normalize_text(str(item.get("surface", "")))
        for item in matching
        if normalize_text(str(item.get("surface", ""))) == normalize_text(original)
    }
    competing = {
        normalize_text(str(item.get("surface", "")))
        for item in matching
        if item.get("effective_type") == effective_type
        and normalize_text(str(item.get("surface", ""))) != normalize_text(original)
    }
    reasons: list[str] = []
    if len(propositions) != 1:
        reasons.append("matching_supporting_proposition_count")
    if original_matches != {normalize_text(original)}:
        reasons.append("original_relation_not_uniquely_recoverable")
    if competing:
        reasons.append("competing_relation_filler")
    if bounded_occurrence_count(source_text, original) < 1:
        reasons.append("original_entity_absent")
    return reasons, sorted(original_matches | competing), target_relation


def _source_specific_anchor_count(
    sentence: str,
    candidate: Mapping[str, Any],
    token_df: Mapping[str, int] | None,
    source_count: int | None,
) -> int | None:
    if token_df is None or not isinstance(source_count, int) or source_count <= 0:
        return None
    spans = candidate.get("entity_spans")
    if not isinstance(spans, list):
        spans = []
    anchor_text = _remove_entity_spans(sentence, spans)
    tokens = set(content_tokens(anchor_text))
    return sum(
        1
        for token in tokens
        if token in token_df and int(token_df[token]) * 100 <= source_count
    )


def evaluate_fact_candidate(
    source: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    token_df: Mapping[str, int] | None = None,
    source_count: int | None = None,
) -> dict[str, Any]:
    """Evaluate one candidate while keeping fact and retrieval diagnostics separate."""

    sentence = str(candidate.get("supporting_sentence") or "")
    original = str(candidate.get("original_entity") or "")
    effective_type = str(candidate.get("effective_type") or "")
    reasons: list[str] = []
    if not sentence or sentence.strip() not in str(source.get("full_text") or ""):
        reasons.append("original_sentence_absent")
    if not _valid_span(candidate, sentence):
        reasons.append("exact_original_span")
    if not original.strip() or GENERIC_ROLE_RE.fullmatch(normalize_text(original)):
        reasons.append("generic_original_entity")
    if MAIL_HEADER_RE.match(sentence):
        reasons.append("mail_header")
    if UNRESOLVED_REFERENCE_RE.search(sentence):
        reasons.append("unresolved_reference")
    token_count = len(re.findall(r"[A-Za-z0-9]+", sentence))
    if not 8 <= token_count <= 80:
        reasons.append("fact_token_count")
    kind = predicate_kind(sentence)
    if kind == "fragment_or_nominal":
        reasons.append("fragment_or_nominal")

    relation_id = ""
    matching_surfaces: list[str] = []
    if not reasons or reasons == ["generic_original_entity"]:
        recovery_reasons, matching_surfaces, relation_id = _matching_recoverability(
            candidate,
            source_text=str(source["full_text"]),
            sentence=sentence,
            original=original,
            effective_type=effective_type,
        )
        reasons.extend(recovery_reasons)
    else:
        relation_id = ""

    replacement_candidates = _dedupe_replacements(
        str(source["full_text"]),
        sentence,
        original,
        int(candidate.get("original_span", [0, 0])[0])
        if isinstance(candidate.get("original_span"), (list, tuple))
        and candidate.get("original_span")
        else 0,
        candidate.get("counterfactual_pool", []),
        effective_type,
    )
    if not replacement_candidates and effective_type in FORMAL_FACT_TYPES:
        reasons.append("no_valid_counterfactual")

    masked = _mask_sentence(sentence, candidate.get("original_span", [0, 0])) if _valid_span(candidate, sentence) else ""
    # Entity spans are expressed in the original sentence coordinates.  Do
    # not apply them after inserting ENTITY_SLOT, whose length changes offsets.
    anchor_text = _remove_entity_spans(sentence, candidate.get("entity_spans", [])) if masked else ""
    masked_tokens = sorted(set(content_tokens(anchor_text))) if masked else []
    anchor_count = _source_specific_anchor_count(sentence, candidate, token_df, source_count)
    relation_cue_present = bool(RELATION_CUE_RE.search(sentence))
    retrieval_usable = bool(kind != "fragment_or_nominal" and len(masked_tokens) >= 4)
    fact_valid = not any(
        reason
        in {
            "original_sentence_absent",
            "exact_original_span",
            "generic_original_entity",
            "mail_header",
            "unresolved_reference",
            "fact_token_count",
            "fragment_or_nominal",
            "matching_supporting_proposition_count",
            "original_relation_not_uniquely_recoverable",
            "competing_relation_filler",
            "original_entity_absent",
        }
        for reason in reasons
    )
    p0_ready = bool(
        effective_type in FORMAL_FACT_TYPES
        and fact_valid
        and retrieval_usable
        and replacement_candidates
    )
    row = {
        "kind": "v23_fact_layer_candidate",
        "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "dataset": str(source["dataset"]),
        "source_key": str(source["source_key"]),
        "source_order_rank": str(source.get("source_order_rank", "")),
        "source_hash": text_sha256(str(source["full_text"])),
        "normalized_text_hash": text_sha256(normalize_text(str(source["full_text"]))),
        "proposition_text": sentence,
        "proposition_span": [
            int(candidate.get("proposition_raw_start", 0)),
            int(candidate.get("proposition_raw_end", 0)),
        ],
        "sentence_hash": text_sha256(sentence.strip()),
        "original_value": original,
        "original_span": list(candidate.get("original_span", [0, 0])),
        "effective_type": effective_type,
        "semantic_subtype": str(candidate.get("semantic_subtype") or ""),
        "fact_signature": fact_signature(
            dataset=str(source["dataset"]),
            source_key=str(source["source_key"]),
            sentence=sentence,
            original_span=candidate.get("original_span", [0, 0]),
            effective_type=effective_type,
        )
        if _valid_span(candidate, sentence)
        else "",
        "relation_signature": relation_id,
        "predicate_kind": kind,
        "fact_valid": fact_valid,
        "retrieval_usable": retrieval_usable,
        "p0_ready": p0_ready,
        "replacement_valid": bool(replacement_candidates),
        "replacement_candidates": replacement_candidates,
        "matching_filler_surfaces": matching_surfaces,
        "content_token_count_after_mask": len(masked_tokens),
        "source_specific_anchor_count": anchor_count,
        "relation_cue_present": relation_cue_present,
        "rejection_codes": sorted(set(reasons)),
        "external_calls_performed": 0,
    }
    return row


def _structured_candidates(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    extractor = EntityExtractor(enable_ner=False)
    output: list[dict[str, Any]] = []
    for proposition in segment_propositions(str(source["full_text"])):
        sentence = proposition["text"]
        for spec in extractor.pattern_registry:
            if spec.entity_type not in STRUCTURED_TYPES:
                continue
            for match in spec.pattern.finditer(sentence):
                raw = match.group(0)
                leading = len(raw) - len(raw.lstrip())
                surface = raw.strip()
                start = match.start() + leading
                end = start + len(surface)
                if not surface or not extractor._valid_surface(surface, spec.entity_type):
                    continue
                output.append(
                    {
                        "dataset": source["dataset"],
                        "source_key": source["source_key"],
                        "source_order_rank": str(source.get("source_order_rank", "")),
                        "supporting_sentence": sentence,
                        "original_entity": surface,
                        "original_span": [start, end],
                        "effective_type": spec.entity_type,
                        "semantic_subtype": spec.entity_type.casefold(),
                        "entity_spans": [[start, end]],
                        "filler_inventory": [],
                        "counterfactual_pool": [],
                        "proposition_raw_start": proposition["start"],
                        "proposition_raw_end": proposition["end"],
                    }
                )
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in output:
        key = (
            text_sha256(str(item["supporting_sentence"]).strip()),
            tuple(item["original_span"]),
            normalize_text(str(item["original_entity"])),
            item["effective_type"],
        )
        seen.setdefault(key, item)
    return [seen[key] for key in sorted(seen)]


def extract_fact_candidates(
    source: Mapping[str, Any],
    *,
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]],
    entity_policy_path: str,
    token_df: Mapping[str, int] | None = None,
    source_count: int | None = None,
) -> dict[str, Any]:
    """Emit and evaluate formal plus structured diagnostic candidates."""

    formal = fresh_extract_candidates(
        source,
        model_emitter=model_emitter,
        entity_policy_path=entity_policy_path,
    )
    candidates = [*formal, *_structured_candidates(source)]
    rows = [
        evaluate_fact_candidate(
            source,
            candidate,
            token_df=token_df,
            source_count=source_count,
        )
        for candidate in candidates
    ]
    rows.sort(
        key=lambda row: (
            row["source_key"],
            tuple(row["proposition_span"]),
            tuple(row["original_span"]),
            row["effective_type"],
            row["original_value"],
        )
    )
    valid = [row for row in rows if row["fact_valid"]]
    return {
        "facts": valid,
        "diagnostics": rows,
        "candidate_count": len(rows),
        "fact_valid_count": sum(bool(row["fact_valid"]) for row in rows),
        "p0_ready_count": sum(bool(row["p0_ready"]) for row in rows),
        "structured_diagnostic_count": sum(
            row["effective_type"] in STRUCTURED_TYPES for row in rows
        ),
        "rejection_reason_counts": {
            reason: sum(reason in row["rejection_codes"] for row in rows)
            for reason in sorted({reason for row in rows for reason in row["rejection_codes"]})
        },
        "external_calls_performed": 0,
    }


def validate_fact_row(row: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "kind",
        "specification_version",
        "dataset",
        "source_key",
        "source_order_rank",
        "source_hash",
        "normalized_text_hash",
        "proposition_text",
        "proposition_span",
        "sentence_hash",
        "original_value",
        "original_span",
        "effective_type",
        "semantic_subtype",
        "fact_signature",
        "relation_signature",
        "predicate_kind",
        "fact_valid",
        "retrieval_usable",
        "p0_ready",
        "replacement_valid",
        "replacement_candidates",
        "matching_filler_surfaces",
        "content_token_count_after_mask",
        "source_specific_anchor_count",
        "relation_cue_present",
        "rejection_codes",
        "external_calls_performed",
    }
    if set(row) != required:
        raise ValueError("fact_layer_row_schema_drift")
    if (
        row["kind"] != "v23_fact_layer_candidate"
        or row["specification_version"] != FACT_LAYER_SPECIFICATION_VERSION
        or row["dataset"] not in {"edgar", "enron", "pubmed"}
        or not all(_is_sha256(row[key]) for key in ("source_hash", "normalized_text_hash", "sentence_hash"))
        or (row["fact_signature"] and not _is_sha256(row["fact_signature"]))
        or (row["relation_signature"] and not _is_sha256(row["relation_signature"]))
        or not isinstance(row["fact_valid"], bool)
        or not isinstance(row["retrieval_usable"], bool)
        or not isinstance(row["p0_ready"], bool)
        or not isinstance(row["replacement_valid"], bool)
        or not isinstance(row["replacement_candidates"], list)
        or not isinstance(row["matching_filler_surfaces"], list)
        or not isinstance(row["rejection_codes"], list)
        or row["external_calls_performed"] != 0
    ):
        raise ValueError("fact_layer_row_value_drift")
    return dict(row)
