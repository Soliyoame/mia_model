"""Attackability-first routing, counterfactual construction, and selection.

This module is intentionally independent from the v21 semantic hard-veto path.
Semantic models provide routing evidence only; all final scores are derived from
the source text, the factual sentence, and the constructed counterfactual.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence

from .entity_extractor import GENERIC_ENTITY_VALUES, RELATION_CUE_RE
from .entity_type_policy import SEMANTIC_REPLACEMENT_CANDIDATES
from .perturbation_generator import perturb_entity_value
from .semantic_entity_resolver import semantic_subtype
from ..utils.hash import sha256_text


SELECTOR_VERSION = "pcv-attackability-first-v22"
MAIN_ENTITY_TYPES = frozenset(
    {"CONTRACT_TERM", "LOCATION", "ORG", "PERSON", "PRODUCT"}
)
STRUCTURED_EXTENSION_TYPES = frozenset(
    {"DATE", "MONEY", "EMAIL", "PHONE", "IDENTIFIER"}
)
DIAGNOSTIC_ENTITY_TYPES = frozenset({"PROJECT_NAME"})
ROUTER_TYPES = MAIN_ENTITY_TYPES | DIAGNOSTIC_ENTITY_TYPES
FORBIDDEN_SELECTION_FIELDS = frozenset(
    {
        "membership",
        "membership_label",
        "member_label",
        "group",
        "split",
        "victim_response",
        "victim_answer",
        "attack_score",
        "attack_auc",
        "auc",
    }
)
UTILITY_COMPONENTS = (
    "grounded_fact_stability",
    "corpus_specificity",
    "counterfactual_naturalness",
    "verification_discriminativeness",
    "lexical_anchor_strength",
    "parser_friendliness",
)
DEFAULT_UTILITY_WEIGHTS: dict[str, float] = {
    "grounded_fact_stability": 0.25,
    "corpus_specificity": 0.20,
    "counterfactual_naturalness": 0.20,
    "verification_discriminativeness": 0.15,
    "lexical_anchor_strength": 0.10,
    "parser_friendliness": 0.10,
}

_ROLE_OR_GENERIC_RE = re.compile(
    r"^(?:president|director|manager|officer|author|employee|customer|"
    r"company|department|team|group|system|service|product|agreement)$",
    re.IGNORECASE,
)
_MAIL_HEADER_RE = re.compile(
    r"^\s*(?:from|to|cc|bcc|subject|sent|date|message-id|content-type)\s*:",
    re.IGNORECASE,
)
_PERSON_SURFACE_RE = re.compile(
    r"^(?:(?:Dr|Mr|Mrs|Ms|Prof)\.?\s+)?"
    r"[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3}$"
)
_ORG_SURFACE_RE = re.compile(
    r"^[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,7}"
    r"(?:\s+(?:Inc|Corp|Corporation|LLC|Ltd|Limited|University|Institute|"
    r"Hospital|Agency|Commission|Department|Authority|Group|Partners))?\.?$"
)
_PRODUCT_SURFACE_RE = re.compile(
    r"^[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,7}$"
)
_CONTRACT_CONTEXT_RE = re.compile(
    r"\b(?:agreement|contract|lease|license|clause|covenant|party|"
    r"borrower|lender|warranty|indemnif|non-disclosure|governing law|"
    r"effective date|termination|renewal)\b",
    re.IGNORECASE,
)
_ORG_SUFFIX_RE = re.compile(
    r"\b(?:Inc|Corp|Corporation|LLC|Ltd|Limited|University|Institute|"
    r"Hospital|Agency|Commission|Department|Authority|Group|Partners)\.?$",
    re.IGNORECASE,
)
_PRODUCT_SUFFIX_RE = re.compile(
    r"\b(?:Platform|System|Product|Service|Drug|Device|Software|Suite|"
    r"Toolkit|Console|Engine)\b$",
    re.IGNORECASE,
)
_LOCATION_RULE_VALUES = frozenset(
    {
        "new york",
        "california",
        "texas",
        "london",
        "paris",
        "china",
        "japan",
        "germany",
        "canada",
        "europe",
        "asia",
        "united states",
        "u.s.",
    }
)


def _clamp(value: float) -> float:
    return round(min(1.0, max(0.0, float(value))), 6)


def _normalised_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _span_overlap_ratio(left: tuple[int, int], right: tuple[int, int]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    denominator = max(1, min(left[1] - left[0], right[1] - right[0]))
    return intersection / denominator


def assert_selection_payload_is_label_free(value: Any, *, path: str = "root") -> None:
    """Fail closed if selection input contains labels or downstream outcomes."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).casefold()
            if key in FORBIDDEN_SELECTION_FIELDS:
                raise ValueError(f"forbidden_selection_field:{path}.{raw_key}")
            assert_selection_payload_is_label_free(item, path=f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_selection_payload_is_label_free(item, path=f"{path}[{index}]")


@dataclass(frozen=True)
class RouteDecision:
    declared_type: str
    effective_type: str | None
    status: str
    route_source: str
    votes: dict[str, int]
    supporting_roles: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_type": self.declared_type,
            "effective_type": self.effective_type,
            "status": self.status,
            "route_source": self.route_source,
            "votes": dict(self.votes),
            "supporting_roles": list(self.supporting_roles),
        }


def _high_precision_rule_type(
    value: str,
    declared_type: str,
    sentence: str,
) -> str | None:
    compact = " ".join(value.split())
    declared = declared_type.upper()
    if declared in STRUCTURED_EXTENSION_TYPES:
        return declared
    if declared == "PERSON" and _PERSON_SURFACE_RE.fullmatch(compact):
        return "PERSON"
    if declared == "ORG" and _ORG_SUFFIX_RE.search(compact):
        return "ORG"
    if declared == "LOCATION" and compact.casefold() in _LOCATION_RULE_VALUES:
        return "LOCATION"
    if declared == "PRODUCT" and _PRODUCT_SUFFIX_RE.search(compact):
        return "PRODUCT"
    if declared == "CONTRACT_TERM" and _CONTRACT_CONTEXT_RE.search(sentence):
        return "CONTRACT_TERM"
    return None


def route_effective_type(
    candidate: Mapping[str, Any],
    predictions_by_role: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    required_roles: Sequence[str],
    minimum_votes: int = 1,
    overlap_threshold: float = 0.80,
    minimum_prediction_score: float = 0.50,
) -> RouteDecision:
    """Route by high-precision rules first, then one or more model roles.

    v22 的默认正式配置只传入 GLiNER2-base 一个角色。模型漏检不是否决：规则已经
    明确的实体会直接通过；只有规则无法路由时才采用单模型预测。
    """

    declared = str(candidate.get("type") or "").upper()
    value = str(candidate.get("text") or "")
    sentence = str(candidate.get("supporting_sentence") or "")
    if declared in STRUCTURED_EXTENSION_TYPES:
        return RouteDecision(
            declared, declared, "accepted", "structured_rule", {declared: 1}, ()
        )
    if declared in DIAGNOSTIC_ENTITY_TYPES:
        return RouteDecision(
            declared, declared, "accepted", "diagnostic_only", {}, ()
        )
    rule_type = _high_precision_rule_type(value, declared, sentence)
    if rule_type is not None:
        return RouteDecision(
            declared,
            rule_type,
            "accepted",
            "high_precision_rule",
            {},
            (),
        )
    candidate_span = (int(candidate.get("start", -1)), int(candidate.get("end", -1)))
    votes: Counter[str] = Counter()
    roles_by_label: defaultdict[str, list[str]] = defaultdict(list)
    for role in required_roles:
        relevant: list[Mapping[str, Any]] = []
        for prediction in predictions_by_role.get(str(role), ()):  # one vote per role
            label = str(prediction.get("label") or "").upper()
            if label not in MAIN_ENTITY_TYPES:
                continue
            span = (int(prediction.get("start", -1)), int(prediction.get("end", -1)))
            score = float(prediction.get("score", 0.0))
            if score < minimum_prediction_score:
                continue
            if _span_overlap_ratio(candidate_span, span) < overlap_threshold:
                continue
            relevant.append(prediction)
        if not relevant:
            continue
        best = sorted(
            relevant,
            key=lambda item: (
                -float(item.get("score", 0.0)),
                str(item.get("label") or ""),
                int(item.get("start", -1)),
            ),
        )[0]
        label = str(best.get("label") or "").upper()
        votes[label] += 1
        roles_by_label[label].append(str(role))
    winners = sorted(
        (label for label, count in votes.items() if count >= minimum_votes),
        key=lambda label: (-votes[label], label),
    )
    if winners:
        effective = winners[0]
        status = "accepted" if effective == declared else "rerouted"
        return RouteDecision(
            declared,
            effective,
            status,
            "single_router_model" if len(required_roles) == 1 else "router_consensus",
            dict(votes),
            tuple(sorted(roles_by_label[effective])),
        )
    if declared in ROUTER_TYPES:
        return RouteDecision(
            declared,
            declared,
            "accepted",
            "declared_type_fallback",
            dict(votes),
            (),
        )
    return RouteDecision(
        declared,
        None,
        "route_ambiguous",
        "unsupported_declared_type",
        dict(votes),
        (),
    )


def _replacement_pool(value: str, effective_type: str) -> list[str]:
    subtype = semantic_subtype(value, effective_type)
    return list(SEMANTIC_REPLACEMENT_CANDIDATES.get(subtype, ()))


def _stable_pool_order(value: str, effective_type: str, pool: Iterable[str]) -> list[str]:
    original = _normalised_text(value)
    unique = {
        " ".join(str(item).split())
        for item in pool
        if _normalised_text(str(item)) != original
    }
    return sorted(
        unique,
        key=lambda item: (
            sha256_text("\0".join((SELECTOR_VERSION, effective_type, value, item))),
            item,
        ),
    )


def _structured_fallbacks(value: str, effective_type: str) -> list[str]:
    kind = effective_type.upper()
    if kind == "EMAIL" and "@" in value:
        _, domain = value.split("@", 1)
        return [f"{local}@{domain}" for local in ("alternate.contact", "verified.contact", "archive.contact")]
    candidates: list[str] = []
    current = value
    for index in range(8):
        level = "medium" if index % 2 else "light"
        current = perturb_entity_value(current, kind, level=level, context=current)
        if _normalised_text(current) != _normalised_text(value):
            candidates.append(current)
    return candidates


def generate_counterfactual_candidates(
    original: str,
    effective_type: str,
    sentence: str,
    *,
    count: int = 3,
) -> list[str]:
    """Generate exactly ``count`` distinct deterministic candidates when possible."""

    if count < 1:
        raise ValueError("counterfactual candidate count must be positive")
    pool = _replacement_pool(original, effective_type)
    if not pool:
        pool = _structured_fallbacks(original, effective_type)
    ordered = _stable_pool_order(original, effective_type, pool)
    if len(ordered) < count:
        ordered = _stable_pool_order(
            original,
            effective_type,
            [*ordered, *_structured_fallbacks(original, effective_type)],
        )
    return ordered[:count]


def _surface_shape(value: str) -> dict[str, Any]:
    compact = " ".join(value.split())
    letters = "".join(character for character in compact if character.isalpha())
    return {
        "has_digit": bool(re.search(r"\d", compact)),
        "has_period": "." in compact,
        "has_comma": "," in compact,
        "has_at": "@" in compact,
        "has_currency": bool(re.search(r"[$€£¥]", compact)),
        "token_count": len(compact.split()),
        "title_like": bool(letters) and not letters.islower(),
    }


def machine_format_compatible(original: str, counterfactual: str, effective_type: str) -> bool:
    """Apply coarse surface constraints without imposing a human ontology."""

    if not original.strip() or not counterfactual.strip():
        return False
    kind = effective_type.upper()
    left = _surface_shape(original)
    right = _surface_shape(counterfactual)
    if kind == "PERSON":
        return bool(_PERSON_SURFACE_RE.fullmatch(counterfactual)) and left["has_period"] == right["has_period"]
    if kind == "ORG":
        return bool(_ORG_SURFACE_RE.fullmatch(counterfactual)) and left["has_comma"] == right["has_comma"]
    if kind == "LOCATION":
        return left["has_comma"] == right["has_comma"]
    if kind == "PRODUCT":
        return bool(_PRODUCT_SURFACE_RE.fullmatch(counterfactual)) and left["has_digit"] == right["has_digit"]
    if kind == "CONTRACT_TERM":
        return 1 <= right["token_count"] <= 6
    if kind == "EMAIL":
        return left["has_at"] and right["has_at"]
    if kind == "MONEY":
        return left["has_currency"] == right["has_currency"]
    if kind in {"PHONE", "IDENTIFIER"}:
        return left["has_digit"] and right["has_digit"]
    if kind == "DATE":
        return right["has_digit"] or bool(re.search(r"[A-Za-z]", counterfactual))
    return True


def _stable_fact_reasons(candidate: Mapping[str, Any]) -> list[str]:
    value = str(candidate.get("text") or "").strip()
    sentence = str(candidate.get("supporting_sentence") or "").strip()
    reasons: list[str] = []
    if not value or _normalised_text(value) not in _normalised_text(sentence):
        reasons.append("entity_missing_from_supporting_sentence")
    if _normalised_text(value) in GENERIC_ENTITY_VALUES or _ROLE_OR_GENERIC_RE.fullmatch(value):
        reasons.append("generic_or_role_entity")
    if _MAIL_HEADER_RE.match(sentence):
        reasons.append("mail_header_fragment")
    word_count = len(re.findall(r"[A-Za-z0-9]+", sentence))
    if word_count < 6:
        reasons.append("fact_too_short")
    if word_count <= 12 and not RELATION_CUE_RE.search(sentence):
        reasons.append("heading_or_nominal_fragment")
    if len(sentence) > 600:
        reasons.append("fact_too_long")
    return list(dict.fromkeys(reasons))


def validate_pair_hard_gates(
    candidate: Mapping[str, Any],
    counterfactual_entity: str,
    source_text: str,
    *,
    effective_type: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Build a one-slot pair and return fail-closed structural reasons."""

    sentence = str(candidate.get("supporting_sentence") or "")
    original = str(candidate.get("text") or "")
    span = candidate.get("entity_sentence_span")
    reasons = _stable_fact_reasons(candidate)
    if not (
        isinstance(span, (list, tuple))
        and len(span) == 2
        and all(isinstance(item, int) for item in span)
    ):
        reasons.append("original_entity_span_missing")
        start, end = -1, -1
    else:
        start, end = int(span[0]), int(span[1])
        if not (0 <= start < end <= len(sentence)) or sentence[start:end] != original:
            reasons.append("original_entity_span_mismatch")
    if _normalised_text(counterfactual_entity) in _normalised_text(source_text):
        reasons.append("counterfactual_entity_present_in_source")
    if not machine_format_compatible(original, counterfactual_entity, effective_type):
        reasons.append("machine_format_incompatible")
    if 0 <= start < end <= len(sentence):
        counterfactual_claim = sentence[:start] + counterfactual_entity + sentence[end:]
        suffix = sentence[end:]
        if not counterfactual_claim.startswith(sentence[:start]) or not counterfactual_claim.endswith(suffix):
            reasons.append("not_single_slot_substitution")
    else:
        counterfactual_claim = ""
    pair = {
        "true_claim": sentence,
        "counterfactual_claim": counterfactual_claim,
        "original_entity": original,
        "counterfactual_entity": counterfactual_entity,
        "effective_type": effective_type,
        "original_span": [start, end],
        "counterfactual_span": [start, start + len(counterfactual_entity)] if start >= 0 else None,
    }
    return pair, tuple(dict.fromkeys(reasons))


def utility_components(
    candidate: Mapping[str, Any],
    pair: Mapping[str, Any],
    *,
    source_text: str,
) -> dict[str, float]:
    """Compute the six preregistered document-intrinsic utility features."""

    sentence = str(pair.get("true_claim") or "")
    original = str(pair.get("original_entity") or "")
    counterfactual = str(pair.get("counterfactual_entity") or "")
    relation = 1.0 if RELATION_CUE_RE.search(sentence) else 0.0
    occurrence_count = max(1, _normalised_text(source_text).count(_normalised_text(original)))
    occurrence_stability = 1.0 / math.sqrt(occurrence_count)
    grounded = _clamp(
        0.50 * float(candidate.get("context_quality", 0.0))
        + 0.25 * relation
        + 0.15 * occurrence_stability
        + 0.10 * (1.0 if sentence.rstrip().endswith((".", "!", "?")) else 0.5)
    )
    specificity = _clamp(float(candidate.get("specificity", 0.0)))
    left_shape = _surface_shape(original)
    right_shape = _surface_shape(counterfactual)
    token_ratio = min(left_shape["token_count"], right_shape["token_count"]) / max(
        1, max(left_shape["token_count"], right_shape["token_count"])
    )
    length_ratio = min(len(original), len(counterfactual)) / max(1, max(len(original), len(counterfactual)))
    naturalness = _clamp(
        0.45 * (1.0 if machine_format_compatible(original, counterfactual, str(pair.get("effective_type") or "")) else 0.0)
        + 0.30 * token_ratio
        + 0.25 * length_ratio
    )
    similarity = SequenceMatcher(None, _normalised_text(original), _normalised_text(counterfactual)).ratio()
    lexical_change = 1.0 - similarity
    token_overlap = len(set(_normalised_text(original).split()) & set(_normalised_text(counterfactual).split()))
    token_union = max(1, len(set(_normalised_text(original).split()) | set(_normalised_text(counterfactual).split())))
    discriminative = _clamp(
        0.55 * lexical_change
        + 0.25 * (1.0 - token_overlap / token_union)
        + 0.20 * (1.0 if _normalised_text(counterfactual) not in _normalised_text(source_text) else 0.0)
    )
    return {
        "grounded_fact_stability": grounded,
        "corpus_specificity": specificity,
        "counterfactual_naturalness": naturalness,
        "verification_discriminativeness": discriminative,
        "lexical_anchor_strength": _clamp(float(candidate.get("retrieval_anchor_strength", 0.0))),
        "parser_friendliness": _clamp(float(candidate.get("parser_friendliness", 0.0))),
    }


def utility_score(
    components: Mapping[str, float],
    weights: Mapping[str, float] | None = None,
) -> float:
    selected_weights = dict(weights or DEFAULT_UTILITY_WEIGHTS)
    if set(selected_weights) != set(UTILITY_COMPONENTS):
        raise ValueError("utility weight components drift")
    if not math.isclose(sum(selected_weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("utility weights must sum to 1")
    return round(
        sum(_clamp(float(components[name])) * float(selected_weights[name]) for name in UTILITY_COMPONENTS),
        6,
    )


def build_pair_candidates(
    candidate: Mapping[str, Any],
    source_text: str,
    route: RouteDecision,
    *,
    counterfactual_count: int = 3,
    weights: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Discard any old counterfactual and regenerate from ``effective_type``."""

    assert_selection_payload_is_label_free(candidate)
    if route.effective_type is None:
        return []
    sentence = str(candidate.get("supporting_sentence") or "")
    original = str(candidate.get("text") or "")
    counterfactuals = generate_counterfactual_candidates(
        original,
        route.effective_type,
        sentence,
        count=counterfactual_count,
    )
    rows: list[dict[str, Any]] = []
    for index, counterfactual in enumerate(counterfactuals, start=1):
        pair, reasons = validate_pair_hard_gates(
            candidate,
            counterfactual,
            source_text,
            effective_type=route.effective_type,
        )
        components = utility_components(candidate, pair, source_text=source_text)
        score = utility_score(components, weights)
        fact_signature = sha256_text(
            "\0".join(
                (
                    _normalised_text(str(candidate.get("supporting_sentence") or "")),
                    _normalised_text(str(candidate.get("text") or "")),
                    str(route.effective_type),
                )
            )
        )
        pair_id = sha256_text(
            "\0".join(
                (
                    SELECTOR_VERSION,
                    str(candidate.get("source_key") or ""),
                    str(candidate.get("audit_id") or ""),
                    str(candidate.get("start") or ""),
                    str(route.effective_type),
                    counterfactual,
                )
            )
        )
        rows.append(
            {
                "pair_id": f"v22_{pair_id[:24]}",
                "source_key": str(candidate.get("source_key") or ""),
                "audit_id": str(candidate.get("audit_id") or ""),
                "doc_id": str(candidate.get("doc_id") or ""),
                "dataset": str(candidate.get("dataset") or ""),
                "declared_type": route.declared_type,
                "effective_type": route.effective_type,
                "route_status": route.status,
                "route_source": route.route_source,
                "route_votes": route.votes,
                "route_supporting_roles": list(route.supporting_roles),
                "candidate_index": index,
                "fact_signature": fact_signature,
                **pair,
                "hard_gate_passed": not reasons,
                "hard_gate_failure_reasons": list(reasons),
                "utility_components": components,
                "utility_score": score,
                "selector_version": SELECTOR_VERSION,
            }
        )
    return rows


def select_top_pairs(
    rows: Sequence[Mapping[str, Any]],
    *,
    threshold: float,
    required_pairs: int = 3,
    max_pairs_per_original_entity: int = 2,
) -> list[dict[str, Any]]:
    """Select deterministic top pairs with fact and entity deduplication."""

    ordered = sorted(
        (
            dict(row)
            for row in rows
            if bool(row.get("hard_gate_passed"))
            and float(row.get("utility_score", 0.0)) >= threshold
            and str(row.get("effective_type") or "") in MAIN_ENTITY_TYPES
        ),
        key=lambda row: (
            -float(row["utility_score"]),
            str(row.get("fact_signature") or ""),
            str(row.get("pair_id") or ""),
        ),
    )
    selected: list[dict[str, Any]] = []
    seen_facts: set[str] = set()
    entity_counts: Counter[str] = Counter()
    for row in ordered:
        fact_signature = str(row.get("fact_signature") or "")
        entity_key = _normalised_text(str(row.get("original_entity") or ""))
        if fact_signature in seen_facts:
            continue
        if entity_counts[entity_key] >= max_pairs_per_original_entity:
            continue
        selected.append(row)
        seen_facts.add(fact_signature)
        entity_counts[entity_key] += 1
        if len(selected) == required_pairs:
            break
    return selected


def select_structured_extension_pairs(
    rows: Sequence[Mapping[str, Any]],
    *,
    threshold: float,
    maximum_pairs: int = 3,
) -> list[dict[str, Any]]:
    """Select a matched extension without changing main-table eligibility."""

    ordered = sorted(
        (
            dict(row)
            for row in rows
            if bool(row.get("hard_gate_passed"))
            and float(row.get("utility_score", 0.0)) >= threshold
            and str(row.get("effective_type") or "") in STRUCTURED_EXTENSION_TYPES
        ),
        key=lambda row: (-float(row["utility_score"]), str(row.get("pair_id") or "")),
    )
    selected: list[dict[str, Any]] = []
    seen_facts: set[str] = set()
    for row in ordered:
        signature = str(row.get("fact_signature") or "")
        if signature in seen_facts:
            continue
        selected.append(row)
        seen_facts.add(signature)
        if len(selected) >= maximum_pairs:
            break
    return selected
