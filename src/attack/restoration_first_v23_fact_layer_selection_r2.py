"""Deterministic quality filtering and pair selection over immutable r1 facts."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .restoration_first_v23 import (
    canonical_sha256,
    normalize_text,
    reject_forbidden_selection_fields,
)
from .restoration_first_v23_fact_layer import FACT_LAYER_SPECIFICATION_VERSION


SELECTION_R2_SPECIFICATION_VERSION = (
    "pcv-restoration-first-v23-fact-layer-selection-r2"
)
FORMAL_ENTITY_TYPES = frozenset(
    {"CONTRACT_TERM", "LOCATION", "ORG", "PERSON", "PRODUCT"}
)
_LETTER_RE = re.compile(r"[A-Za-z]")
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\b", re.IGNORECASE)
_TIMESTAMP_TO_RE = re.compile(
    r"\b\d{1,2}:\d{2}(?:\s*[AP]M)?\s+to\s*:", re.IGNORECASE
)
_STRUCTURED_NUMERIC_SURFACE_RE = re.compile(
    r"^\s*[-+]?[$€£]?\d[\d,]*(?:\.\d+)?"
    r"(?:\s*(?:%|acres?|days?|years?|months?|hours?|minutes?|seconds?|"
    r"mg|kg|g|ml|l|cm|mm|km))?\s*$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z]+")


def _required_list(config: Mapping[str, Any], key: str) -> list[str]:
    value = config.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"selection_r2_config_list_invalid:{key}")
    return value


def _header_pattern(labels: Sequence[str]) -> re.Pattern[str]:
    alternatives = [re.escape(label).replace(r"\ ", r"\s+") for label in labels]
    if not alternatives:
        raise RuntimeError("selection_r2_mail_header_labels_empty")
    return re.compile(
        rf"(?<![A-Za-z0-9])(?:{'|'.join(alternatives)})\s*:",
        re.IGNORECASE,
    )


def _starts_with_header(claim: str, labels: Sequence[str]) -> bool:
    alternatives = [re.escape(label).replace(r"\ ", r"\s+") for label in labels]
    return bool(
        re.match(
            rf"^\s*(?:{'|'.join(alternatives)})\s*:",
            claim,
            re.IGNORECASE,
        )
    )


def quality_rejection_codes(
    fact: Mapping[str, Any], config: Mapping[str, Any]
) -> list[str]:
    """Return high-confidence r2 rejection reasons without changing r1 facts."""

    quality = config.get("quality_filters")
    if not isinstance(quality, Mapping):
        raise RuntimeError("selection_r2_quality_filters_invalid")
    original = str(fact.get("original_value") or "").strip()
    normalized = normalize_text(original)
    claim = str(fact.get("proposition_text") or "").strip()
    effective_type = str(fact.get("effective_type") or "").upper()
    reasons: list[str] = []

    generic_values = {
        normalize_text(value)
        for value in _required_list(quality, "generic_original_values")
    }
    if normalized in generic_values:
        reasons.append("generic_original_entity")

    if (
        quality.get("reject_structured_numeric_formal_entities") is True
        and effective_type in FORMAL_ENTITY_TYPES
        and bool(_STRUCTURED_NUMERIC_SURFACE_RE.fullmatch(original))
    ):
        reasons.append("structured_numeric_formal_entity")

    if quality.get("reject_mail_metadata") is True:
        labels = _required_list(quality, "mail_header_labels")
        always_embedded = _required_list(
            quality, "always_embedded_mail_header_labels"
        )
        header_matches = _header_pattern(labels).findall(claim)
        minimum = quality.get("minimum_embedded_mail_header_count")
        if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
            raise RuntimeError("selection_r2_mail_header_minimum_invalid")
        if (
            _starts_with_header(claim, labels)
            or _header_pattern(always_embedded).search(claim)
            or len(header_matches) >= minimum
            or bool(_TIMESTAMP_TO_RE.search(claim))
            or (bool(_EMAIL_RE.search(claim)) and bool(header_matches))
        ):
            reasons.append("mail_metadata")

    prefixes = tuple(
        normalize_text(value)
        for value in _required_list(quality, "reject_metadata_prefixes")
    )
    normalized_claim = normalize_text(claim)
    if any(
        normalized_claim == prefix or normalized_claim.startswith(f"{prefix} ")
        for prefix in prefixes
    ):
        reasons.append("document_metadata_or_table")

    if effective_type == "PERSON":
        letters = "".join(_LETTER_RE.findall(original))
        if (
            quality.get("reject_all_caps_person_surfaces") is True
            and len(letters) >= 3
            and letters.isupper()
        ):
            reasons.append("person_surface_role_incompatible")
        incompatible_exact = {
            normalize_text(value)
            for value in _required_list(quality, "person_incompatible_exact_values")
        }
        incompatible_terms = {
            normalize_text(value)
            for value in _required_list(quality, "person_incompatible_terms")
        }
        original_terms = {normalize_text(value) for value in _WORD_RE.findall(original)}
        if normalized in incompatible_exact or original_terms.intersection(incompatible_terms):
            reasons.append("person_surface_role_incompatible")

    return sorted(set(reasons))


def select_pairs_from_r1_facts(
    facts: Sequence[Mapping[str, Any]],
    *,
    dataset: str,
    selection_identity_sha256: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter r1 P0 facts, build r2 pairs, and select exactly three per source."""

    required = config.get("required_pairs_per_source")
    maximum_per_entity = config.get("maximum_pairs_per_original_entity")
    if (
        not isinstance(required, int)
        or isinstance(required, bool)
        or required <= 0
        or not isinstance(maximum_per_entity, int)
        or isinstance(maximum_per_entity, bool)
        or maximum_per_entity <= 0
    ):
        raise RuntimeError("selection_r2_pair_budget_invalid")
    if config.get("require_distinct_fact_signatures") is not True:
        raise RuntimeError("selection_r2_distinct_fact_requirement_invalid")

    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    raw_candidate_pair_count = 0
    for fact in facts:
        reject_forbidden_selection_fields(fact, path="selection_r2_source_fact")
        if not fact.get("p0_ready"):
            continue
        replacements = fact.get("replacement_candidates")
        if not isinstance(replacements, list) or not all(
            isinstance(value, str) for value in replacements
        ):
            raise RuntimeError("selection_r2_replacement_candidates_invalid")
        raw_candidate_pair_count += len(replacements)
        reasons = quality_rejection_codes(fact, config)
        if reasons:
            rejection_counts.update(reasons)
            diagnostics.append(
                {
                    "kind": "v23_fact_layer_selection_r2_rejection",
                    "specification_version": SELECTION_R2_SPECIFICATION_VERSION,
                    "source_fact_specification_version": (
                        FACT_LAYER_SPECIFICATION_VERSION
                    ),
                    "dataset": dataset,
                    "source_key": fact["source_key"],
                    "source_order_rank": fact["source_order_rank"],
                    "fact_signature": fact["fact_signature"],
                    "original_value": fact["original_value"],
                    "effective_type": fact["effective_type"],
                    "rejection_codes": reasons,
                }
            )
            continue
        start, end = fact["original_span"]
        for replacement in replacements:
            counterfactual_claim = (
                fact["proposition_text"][:start]
                + replacement
                + fact["proposition_text"][end:]
            )
            pair_id = canonical_sha256(
                {
                    "kind": "v23_fact_layer_selection_r2_pair",
                    "specification_version": SELECTION_R2_SPECIFICATION_VERSION,
                    "selection_identity_sha256": selection_identity_sha256,
                    "fact_signature": fact["fact_signature"],
                    "original_value": normalize_text(fact["original_value"]),
                    "counterfactual_value": normalize_text(replacement),
                }
            )
            candidates.append(
                {
                    "kind": "v23_fact_layer_selection_r2_pair",
                    "specification_version": SELECTION_R2_SPECIFICATION_VERSION,
                    "source_fact_specification_version": (
                        FACT_LAYER_SPECIFICATION_VERSION
                    ),
                    "selection_identity_sha256": selection_identity_sha256,
                    "dataset": dataset,
                    "source_key": fact["source_key"],
                    "source_order_rank": fact["source_order_rank"],
                    "source_hash": fact["source_hash"],
                    "normalized_text_hash": fact["normalized_text_hash"],
                    "fact_signature": fact["fact_signature"],
                    "relation_signature": fact["relation_signature"],
                    "pair_id": pair_id,
                    "original_span": list(fact["original_span"]),
                    "original_entity": fact["original_value"],
                    "counterfactual_entity": replacement,
                    "effective_type": fact["effective_type"],
                    "semantic_subtype": fact["semantic_subtype"],
                    "true_claim": fact["proposition_text"],
                    "counterfactual_claim": counterfactual_claim,
                }
            )

    def sort_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(row["source_order_rank"]),
            str(row["source_key"]),
            str(row["fact_signature"]),
            str(row.get("pair_id") or ""),
        )

    candidates.sort(key=sort_key)
    diagnostics.sort(key=sort_key)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_source.setdefault(str(row["source_key"]), []).append(row)
    selected: list[dict[str, Any]] = []
    for source_key in sorted(
        by_source,
        key=lambda key: (str(by_source[key][0]["source_order_rank"]), key),
    ):
        seen_facts: set[str] = set()
        entity_counts: Counter[str] = Counter()
        accepted: list[dict[str, Any]] = []
        for row in by_source[source_key]:
            entity = normalize_text(row["original_entity"])
            if (
                row["fact_signature"] in seen_facts
                or entity_counts[entity] >= maximum_per_entity
            ):
                continue
            item = dict(row)
            item["pair_order"] = len(accepted)
            accepted.append(item)
            seen_facts.add(str(row["fact_signature"]))
            entity_counts[entity] += 1
            if len(accepted) == required:
                break
        if len(accepted) == required:
            selected.extend(accepted)

    return {
        "selected": selected,
        "diagnostics": diagnostics,
        "candidate_pair_count": len(candidates),
        "raw_candidate_pair_count": raw_candidate_pair_count,
        "eligible_source_count": len(selected) // required,
        "quality_rejected_fact_count": len(diagnostics),
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
    }
