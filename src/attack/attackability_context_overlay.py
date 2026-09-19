"""Context-aware attackability overlay for the final v22 calibration revision."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

from .attackability_selector import MAIN_ENTITY_TYPES
from .perturbation_generator import requires_definite_article


OVERLAY_VERSION = "pcv-attackability-context-overlay-r3"
OVERLAY_COMPONENTS = (
    "grounded_fact_stability",
    "corpus_specificity",
    "context_slot_compatibility",
    "queryability",
    "verification_discriminativeness",
    "lexical_anchor_strength",
)
DEFAULT_OVERLAY_WEIGHTS: dict[str, float] = {
    "grounded_fact_stability": 0.15,
    "corpus_specificity": 0.10,
    "context_slot_compatibility": 0.30,
    "queryability": 0.25,
    "verification_discriminativeness": 0.10,
    "lexical_anchor_strength": 0.10,
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_PERSON_RE = re.compile(
    r"^(?:(?:Dr|Mr|Mrs|Ms|Prof)\.?\s+)?"
    r"[A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){1,3}$"
)
_SINGLE_PERSON_CONTEXT_RE = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Prof|by|from|to|with|contact|author|investigator|"
    r"officer|director|president|said|asked|told|named)\s+$",
    re.IGNORECASE,
)
_ORG_SUFFIX_RE = re.compile(
    r"\b(?:Inc|Corp|Corporation|LLC|Ltd|Limited|University|Institute|"
    r"Hospital|Agency|Commission|Department|Authority|Group|Partners|"
    r"Bank|Company|Systems?|Technologies|Laboratories)\.?$",
    re.IGNORECASE,
)
_ORG_CONTEXT_RE = re.compile(
    r"\b(?:company|corporation|bank|university|institute|hospital|agency|"
    r"commission|authority|firm|vendor|supplier|distributor|manufacturer|"
    r"customer|partner|subsidiary|employer|organization|organisation)\b",
    re.IGNORECASE,
)
_LOCATION_CONTEXT_RE = re.compile(
    r"\b(?:in|at|from|to|near|across|within|outside|throughout|around|"
    r"located in|based in|operations in|residents of|market in)\s+$",
    re.IGNORECASE,
)
_CONTRACT_CONTEXT_RE = re.compile(
    r"\b(?:agreement|contract|lease|license|clause|covenant|amendment|"
    r"order|notice|option|assignment|termination|renewal|guarantee|"
    r"warranty|indemnif|governing law|effective date|party|borrower|"
    r"lender|instrument|policy|plan|exchange|consent)\b",
    re.IGNORECASE,
)
_PRODUCT_CONTEXT_RE = re.compile(
    r"\b(?:product|platform|system|software|service|suite|toolkit|console|"
    r"device|instrument|microscope|sequencer|sensor|kit|assay|reagent|"
    r"vaccine|drug|medication|therapy|model|version|installed|manufactured|"
    r"developed|marketed|sold|used|using)\b",
    re.IGNORECASE,
)
_VERB_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|will|would|can|"
    r"could|may|might|must|shall|should|does|do|did|includes?|included|"
    r"provides?|provided|uses?|used|contains?|contained|reported|found|"
    r"showed|received|entered|issued|located|operates?|accounted|sold|"
    r"acquired|developed|approved|signed|agreed|paid|holds?|owns?|serves?)\b",
    re.IGNORECASE,
)
_MAIL_OR_WEB_RE = re.compile(
    r"(?:\b(?:from|to|cc|bcc|subject|sent|message-id)\s*:|https?://|www\.|"
    r"\b[A-Z][A-Za-z]+/[A-Z]{2,}/[A-Z]+@)",
    re.IGNORECASE,
)
_ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9&.-]{1,11}$")
_GENERIC_NOMINAL_RE = re.compile(
    r"^(?:company|court|school|hospital systems?|university|plan|turbine|"
    r"system|service|product|agreement|license|assignment|termination|"
    r"computer systems?|proprietary products?|special holiday offers?)$",
    re.IGNORECASE,
)
_FOLLOWING_NOUN_EXEMPTIONS = frozenset(
    {
        "branch",
        "business",
        "company",
        "facility",
        "fund",
        "market",
        "office",
        "operations",
        "region",
        "school",
        "team",
        "unit",
    }
)


def _normalise(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _clamp(value: float) -> float:
    return round(min(1.0, max(0.0, float(value))), 6)


def _span(row: Mapping[str, Any]) -> tuple[int, int] | None:
    value = row.get("original_span")
    if not (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(item, int) for item in value)
    ):
        return None
    return int(value[0]), int(value[1])


def _slot_context(row: Mapping[str, Any]) -> tuple[str, str]:
    claim = str(row.get("true_claim") or "")
    span = _span(row)
    if span is None:
        return "", ""
    start, end = span
    if not (0 <= start < end <= len(claim)):
        return "", ""
    return claim[max(0, start - 80) : start], claim[end : end + 80]


def _replacement_integrity_reasons(row: Mapping[str, Any]) -> list[str]:
    claim = str(row.get("true_claim") or "")
    counterfactual_claim = str(row.get("counterfactual_claim") or "")
    original = str(row.get("original_entity") or "")
    counterfactual = str(row.get("counterfactual_entity") or "")
    span = _span(row)
    reasons: list[str] = []
    if span is None:
        return ["r3_original_span_missing"]
    start, end = span
    if not (0 <= start < end <= len(claim)) or claim[start:end] != original:
        return ["r3_original_span_mismatch"]
    expected = claim[:start] + counterfactual + claim[end:]
    if expected != counterfactual_claim:
        reasons.append("r3_not_exact_single_slot_substitution")
    if start > 0 and claim[start - 1].isalnum():
        reasons.append("r3_left_token_boundary_incomplete")
    if end < len(claim) and claim[end].isalnum():
        reasons.append("r3_right_token_boundary_incomplete")
    if _normalise(claim).count(_normalise(original)) != 1:
        reasons.append("r3_original_entity_not_unique_in_claim")
    if _normalise(original) in _normalise(counterfactual_claim):
        reasons.append("r3_original_entity_survives_counterfactual")
    return reasons


def _article_and_alias_reasons(row: Mapping[str, Any]) -> list[str]:
    original = str(row.get("original_entity") or "")
    counterfactual = str(row.get("counterfactual_entity") or "")
    kind = str(row.get("effective_type") or "").upper()
    before, after = _slot_context(row)
    reasons: list[str] = []
    before_word = re.search(r"(?:^|\s)(the|a|an)\s*$", before, re.IGNORECASE)
    following = _TOKEN_RE.search(after)
    following_word = following.group(0).casefold() if following else ""
    if before_word and before_word.group(1).casefold() == "the" and kind == "LOCATION":
        if (
            not requires_definite_article(counterfactual)
            and following_word not in _FOLLOWING_NOUN_EXEMPTIONS
        ):
            reasons.append("r3_definite_article_location_mismatch")
    if before_word and before_word.group(1).casefold() in {"a", "an"}:
        vowel = bool(re.match(r"[AEIOUaeiou]", counterfactual))
        if (before_word.group(1).casefold() == "an") != vowel:
            reasons.append("r3_indefinite_article_mismatch")
    if after.startswith("'s") and counterfactual.rstrip(".").casefold().endswith("s"):
        reasons.append("r3_possessive_surface_mismatch")
    alias = re.match(r"\s*\(([A-Z][A-Z0-9&.-]{1,11})\)", after)
    if alias and _normalise(alias.group(1)) not in _normalise(counterfactual):
        reasons.append("r3_stale_parenthetical_alias")
    if kind == "LOCATION" and following:
        token = following.group(0)
        if token[:1].isupper() and token.casefold() not in _FOLLOWING_NOUN_EXEMPTIONS:
            if not _LOCATION_CONTEXT_RE.search(before):
                reasons.append("r3_partial_named_location_span")
    if not original.strip() or not counterfactual.strip():
        reasons.append("r3_empty_entity")
    return reasons


def _surface_role_score(row: Mapping[str, Any]) -> tuple[float, list[str]]:
    claim = str(row.get("true_claim") or "")
    original = str(row.get("original_entity") or "").strip()
    kind = str(row.get("effective_type") or "").upper()
    before, _ = _slot_context(row)
    reasons: list[str] = []
    if kind not in MAIN_ENTITY_TYPES:
        return 0.0, ["r3_non_main_entity_type"]
    if kind == "PERSON":
        person_like = bool(_PERSON_RE.fullmatch(original))
        single_name = bool(re.fullmatch(r"[A-Z][A-Za-z.'’-]{2,}", original))
        if not person_like and not (single_name and _SINGLE_PERSON_CONTEXT_RE.search(before)):
            reasons.append("r3_person_surface_role_incompatible")
        return (1.0 if not reasons else 0.0), reasons
    if kind == "ORG":
        acronym = bool(_ACRONYM_RE.fullmatch(original))
        organisation = bool(_ORG_SUFFIX_RE.search(original) or _ORG_CONTEXT_RE.search(claim))
        person_only = bool(_PERSON_RE.fullmatch(original)) and not organisation
        if person_only or not (acronym or organisation or original.casefold() == "the company"):
            reasons.append("r3_organization_surface_role_incompatible")
        return (1.0 if not reasons else 0.0), reasons
    if kind == "LOCATION":
        locative = bool(_LOCATION_CONTEXT_RE.search(before))
        proper = bool(re.fullmatch(r"[A-Z][A-Za-z.'’-]*(?:[ ,.-]+[A-Z][A-Za-z.'’-]*){0,4}", original))
        if not (locative or proper):
            reasons.append("r3_location_surface_role_incompatible")
        return (1.0 if not reasons else 0.0), reasons
    if kind == "CONTRACT_TERM":
        if not _CONTRACT_CONTEXT_RE.search(claim):
            reasons.append("r3_contract_slot_without_contract_context")
        return (1.0 if not reasons else 0.0), reasons
    product_signal = bool(_PRODUCT_CONTEXT_RE.search(claim))
    branded = bool(
        re.fullmatch(r"[A-Z][A-Za-z0-9&.'’-]*(?:\s+[A-Z0-9][A-Za-z0-9&.'’-]*){0,5}", original)
    )
    if not (product_signal or branded):
        reasons.append("r3_product_surface_role_incompatible")
    return (1.0 if not reasons else 0.0), reasons


def _queryability(row: Mapping[str, Any]) -> tuple[float, list[str]]:
    claim = str(row.get("true_claim") or "").strip()
    words = _TOKEN_RE.findall(claim)
    reasons: list[str] = []
    if len(words) < 8:
        reasons.append("r3_claim_too_short_for_verification")
    if len(words) > 120:
        reasons.append("r3_claim_too_long_for_verification")
    if _MAIL_OR_WEB_RE.search(claim):
        reasons.append("r3_mail_or_web_fragment")
    if claim.count(",") >= 10 or claim.count("@") >= 2:
        reasons.append("r3_list_or_header_dump")
    verb = bool(_VERB_RE.search(claim))
    if not verb:
        reasons.append("r3_no_predicate_for_verification")
    terminal = claim.endswith((".", "?", "!", '"', "'", ")"))
    length_score = 1.0 if 10 <= len(words) <= 80 else 0.65 if 8 <= len(words) <= 120 else 0.0
    score = _clamp(
        0.35 * (1.0 if verb else 0.0)
        + 0.25 * length_score
        + 0.20 * (1.0 if terminal else 0.45)
        + 0.20 * (1.0 if not _MAIL_OR_WEB_RE.search(claim) and claim.count(",") < 10 else 0.0)
    )
    return score, reasons


def overlay_pair(
    row: Mapping[str, Any],
    *,
    weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Return an immutable-derived r3 view without changing the base pair."""

    selected_weights = dict(weights or DEFAULT_OVERLAY_WEIGHTS)
    if set(selected_weights) != set(OVERLAY_COMPONENTS) or not math.isclose(
        sum(selected_weights.values()), 1.0, abs_tol=1e-9
    ):
        raise ValueError("r3 overlay weights drift")
    base_components = dict(row.get("utility_components") or {})
    integrity = _replacement_integrity_reasons(row)
    article = _article_and_alias_reasons(row)
    role_score, role_reasons = _surface_role_score(row)
    query_score, query_reasons = _queryability(row)
    original = str(row.get("original_entity") or "")
    generic_penalty = 0.55 if _GENERIC_NOMINAL_RE.fullmatch(original.strip()) else 1.0
    context_score = _clamp(role_score * generic_penalty)
    components = {
        "grounded_fact_stability": _clamp(float(base_components.get("grounded_fact_stability", 0.0))),
        "corpus_specificity": _clamp(float(base_components.get("corpus_specificity", 0.0))),
        "context_slot_compatibility": context_score,
        "queryability": query_score,
        "verification_discriminativeness": _clamp(float(base_components.get("verification_discriminativeness", 0.0))),
        "lexical_anchor_strength": _clamp(float(base_components.get("lexical_anchor_strength", 0.0))),
    }
    base_hard_reasons = list(row.get("hard_gate_failure_reasons") or ())
    hard_reasons = list(
        dict.fromkeys(
            str(reason) for reason in (*base_hard_reasons, *integrity, *article)
        )
    )
    soft_reasons = list(
        dict.fromkeys(str(reason) for reason in (*role_reasons, *query_reasons))
    )
    score = round(
        sum(components[name] * selected_weights[name] for name in OVERLAY_COMPONENTS),
        6,
    )
    output = dict(row)
    output.update(
        {
            "r3_hard_gate_passed": not hard_reasons,
            "r3_hard_gate_failure_reasons": hard_reasons,
            "r3_soft_penalty_reasons": soft_reasons,
            "r3_utility_components": components,
            "r3_utility_score": score,
            "r3_overlay_version": OVERLAY_VERSION,
        }
    )
    return output


def r3_pair_is_eligible(row: Mapping[str, Any], threshold: float) -> bool:
    return (
        bool(row.get("r3_hard_gate_passed"))
        and float(row.get("r3_utility_score", 0.0)) >= float(threshold)
        and str(row.get("effective_type") or "") in MAIN_ENTITY_TYPES
    )
