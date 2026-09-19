"""Deterministic local validation for PCV-MIA claim and query pairs.

The hard gate in this module is intentionally dependency-free.  It must not
call an LLM, an API, or a retriever: canonical pairs are accepted only when
their entity span, one-slot substitution, type, and surface completeness can
be verified from the generated text itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from ..attack.entity_extractor import (
    CONTRACT_TERM_RE,
    DATE_RE,
    DURATION_RE,
    EMAIL_RE,
    IDENTIFIER_RE,
    MEDICAL_VALUE_RE,
    MONEY_RE,
    PERCENT_RE,
    PHONE_RE,
    PROJECT_NAME_RE,
    SECTION_ID_RE,
    TIME_RE,
    URL_RE,
    entity_context_failure_reasons,
    is_likely_bad_identifier,
    is_likely_bad_person,
    is_likely_bad_project_name,
    sentence_semantic_failure_reasons,
)
from ..attack.perturbation_generator import (
    infer_attack_subtype,
    requires_definite_article,
)
from ..attack.entity_type_policy import (
    ENTITY_TYPE_POLICY_SHA256,
    ENTITY_TYPE_POLICY_VERSION,
    SEMANTIC_TARGET_TYPES,
    entity_type_policy,
)
from ..attack.semantic_entity_resolver import (
    SEMANTIC_RESOLVER_PROTOCOL,
    SEMANTIC_SCHEMA_SHA256,
    semantic_format_compatible,
)


VALIDATOR_VERSION = "local_claim_pair_v21_entity_policy_r1"

_TRAILING_FRAGMENT_RE = re.compile(
    r"(?:[,;:]|\b(?:and|or|but|because|which|that|of|the|to|in|with|as|for|be|been|being))\s*$",
    re.IGNORECASE,
)
_STRUCTURED_PATTERNS: dict[str, re.Pattern[str]] = {
    "MONEY": MONEY_RE,
    "DATE": DATE_RE,
    "PERCENT": PERCENT_RE,
    "EMAIL": EMAIL_RE,
    "MEDICAL_VALUE": MEDICAL_VALUE_RE,
    "CONTRACT_TERM": CONTRACT_TERM_RE,
    "TIME": TIME_RE,
    "DURATION": DURATION_RE,
    "URL": URL_RE,
    "PHONE": PHONE_RE,
    "SECTION_ID": SECTION_ID_RE,
    "IDENTIFIER": IDENTIFIER_RE,
    "PROJECT_NAME": PROJECT_NAME_RE,
}
_NAMED_TYPES = {"PERSON", "ORG", "LOCATION", "PRODUCT"}
_PERSON_LEADING_STOPWORDS = {
    "A",
    "An",
    "And",
    "As",
    "At",
    "By",
    "For",
    "From",
    "If",
    "In",
    "Of",
    "On",
    "Or",
    "The",
    "To",
    "Under",
    "When",
    "While",
    "With",
}
_DURATION_VALUE_RE = re.compile(
    r"(?:(?:for|within|over|after|before|during)\s+)?"
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>minutes?|hours?|days?|weeks?|months?|years?|quarters?)",
    re.IGNORECASE,
)
_COUNT_UNIT_VALUE_RE = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>minutes?|hours?|days?|weeks?|months?|years?|quarters?|"
    r"cases?|patients?|subjects?|participants?)",
    re.IGNORECASE,
)
_ORG_CORPORATE_DESIGNATOR_RE = re.compile(
    r"(?:Inc|Corp|Corporation|LLC|Ltd|Limited|Company|Co|PLC)\.?",
    re.IGNORECASE,
)
_ORG_PREFIX_CONNECTOR_RE = re.compile(r"(?:&|/)\s*$")
_ORG_SUFFIX_CONNECTOR_RE = re.compile(r"^\s+of\b", re.IGNORECASE)
_CHEMICAL_SYMBOL_RE = re.compile(r"[A-Z][a-z]?")
_TABULAR_COLUMN_HEADER_RE = re.compile(
    r"\b(?:topic|positive mentions|negative mentions)\s*:",
    re.IGNORECASE,
)
_TABULAR_PERCENT_CELL_RE = re.compile(r"\b\d+(?:\.\d+)?%")
_TABULAR_SLASHED_CELL_RE = re.compile(
    r"\b[A-Za-z0-9][A-Za-z0-9.-]*/[A-Za-z0-9][A-Za-z0-9.-]*\b"
)
_TABULAR_CATEGORY_RE = re.compile(
    r"\b(?:inactivated|live attenuated|deoptimized|recombinant|protein subunit|"
    r"phase\s+[IVX]+(?:/[IVX]+)?)\b",
    re.IGNORECASE,
)
_NAMED_ENTITY_TRAILING_BOUNDARY_RE = re.compile(r"[,/:;]\s*$")
_NAMED_ENTITY_ENCODING_RE = re.compile(r"(?:=\d{2}|\?{2,}|[\x00-\x08\x0b\x0c\x0e-\x1f])")
_PERSON_CONTEXT_BEFORE_RE = re.compile(
    r"\b(?:by|founded by|controlled by|authored by|written by|such as|"
    r"researcher|professor|doctor|dr\.?|mr\.?|mrs\.?|ms\.?)\s+$",
    re.IGNORECASE,
)
_PERSON_CONTEXT_AFTER_RE = re.compile(
    r"^\s*(?:,\s*(?:a|an|the|CEO|CFO|president|director|professor|researcher|"
    r"founder|author)\b|(?:et al\.?|and (?:colleagues|coauthors))\b|"
    r"(?:was|is|has|had|proposed|reported|developed|founded|served|controlled)\b)",
    re.IGNORECASE,
)
_PERSON_COLLECTIVE_CUE_RE = re.compile(
    r"\b(?:authors?' contributions?|had major roles?|designed the study|"
    r"contributed to|approved the manuscript)\b",
    re.IGNORECASE,
)
_ORG_STRONG_TOKEN_RE = re.compile(
    r"\b(?:Inc|Corp|Corporation|LLC|Ltd|Limited|Company|Co|PLC|Bank|University|"
    r"Ministry|Association|Department|Commission|Service|Services|Institute|"
    r"Institution|Hospital|Healthcare|Laboratories|Foundation|Administration|"
    r"Agency|Authority|Council|Center|Centre|College|School|Group|Holdings|"
    r"Partners|Industries|Technologies|Systems)\b",
    re.IGNORECASE,
)
_ORG_TECHNICAL_TOKEN_RE = re.compile(
    r"^(?:[A-Z]{2,}\d*(?:-\d+)?|\d+D|[A-Za-z]+\d+[A-Za-z0-9-]*|"
    r"[A-Za-z]+ase|w/w|v/v)$"
)
_ORG_GENERIC_OR_TECHNICAL_PHRASE_RE = re.compile(
    r"\b(?:statements?|policies|units?|regulation|covid|tsunamis|glycosylation|"
    r"survival estimates?|technique|activity|transcriptome|molecule|inhibitor|"
    r"acyl|formula|ratio|method|model)\b",
    re.IGNORECASE,
)
_ORG_CONTEXT_CUE_RE = re.compile(
    r"\b(?:announced|issued|reported|filed|operates|maintains|provides|"
    r"headquartered|employs|acquired|subsidiar(?:y|ies)|department|company|"
    r"organization|institution)\b",
    re.IGNORECASE,
)
_LOCATION_TECHNICAL_SURFACE_RE = re.compile(
    r"^(?:[A-Z]{2,}\d+[A-Za-z0-9-]*|T\d+|.*\b(?:Phase\s+\d+|Scale|System|"
    r"Model|Method|Study|Daltonics|Scholes)\b.*)$",
    re.IGNORECASE,
)
_LOCATION_CONTEXT_BEFORE_RE = re.compile(
    r"\b(?:in|at|from|to|throughout|within|near|across|outside|located in|"
    r"based in|region of|country of|state of|county of|city of)\s+(?:the\s+)?$",
    re.IGNORECASE,
)
_LOCATION_CONTEXT_AFTER_RE = re.compile(
    r"^\s*(?:,\s*(?:[A-Z]{2}|USA|U\.S\.A\.|United States|Germany|Japan|"
    r"China|Canada)\b|\b(?:county|province|region|area|city|state|country|"
    r"limited liability company)\b)",
    re.IGNORECASE,
)
_LOCATION_NONLOCATION_SUFFIX_RE = re.compile(
    r"^\s+(?:option pricing model|clinical study|interbank offered rate|"
    r"expression|signal|sequence|software|scale|model|method|system)\b",
    re.IGNORECASE,
)
_LOCATION_ORG_OR_METHOD_CONTEXT_RE = re.compile(
    r"\b(?:paid the affiliate|tendered for filing|financial interest|"
    r"consolidates?|expression status|option pricing|clinical study|"
    r"survival estimates?|software|methodological quality)\b",
    re.IGNORECASE,
)
_PERSON_NONHUMAN_SUFFIX_RE = re.compile(
    r"^\s+(?:facility|system|method|model|analysis|style|form|kit|software|"
    r"bank|department|framework)\b",
    re.IGNORECASE,
)
_STRICT_CONTRACT_CUE_RE = re.compile(
    r"\b(?:agreement|contract|lease|license|licence|bylaws?|certificate of "
    r"incorporation|party|parties|clause|provision|covenant|legal obligation|"
    r"terms and conditions|representation and warranty)\b",
    re.IGNORECASE,
)
_OBVIOUS_GENERIC_ORG_RE = re.compile(
    r"^(?:the\s+)?(?:company|corporation|organization|institution|"
    r"target company|commercial partners?|limited liability companies?|"
    r"business organizations?|third-party financial institutions?)$",
    re.IGNORECASE,
)
_OBVIOUS_GENERIC_PRODUCT_RE = re.compile(
    r"^(?:the\s+)?(?:water services|service lines?|product lines?|"
    r"commercial products?|consumer products?)$",
    re.IGNORECASE,
)
_OBVIOUS_NUMERIC_OF_FRAGMENT_RE = re.compile(
    r"^\d+(?:\.\d+)?\s+(?:hundred|thousand|million|billion)?\s*of\b",
    re.IGNORECASE,
)
_OBVIOUS_DETACHED_INFINITIVE_RE = re.compile(
    r"^[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3},\s+to\s+[a-z]+\b",
)
_OBVIOUS_COPYRIGHT_FRAGMENT_RE = re.compile(
    r"^(?:\([Cc]\)|©)\s+[^.!?]{2,100}\s+\d{4}\.$"
)
_OBVIOUS_PROMOTIONAL_HEADLINE_RE = re.compile(
    r"^[^.!?]{2,120}\s+-\s+[A-Z][A-Z\s+&/-]*(?:OFFER|REBATE|SALE)[A-Z\s+&/-]*[.!?]$"
)
_OBVIOUS_ROUTE_FRAGMENT_RE = re.compile(
    r"^[A-Z][^.!?]{1,100}\s+to\s+[A-Z][^.!?]*\band onward to\b[^.!?]*[.!?]$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ValidationResult:
    """Result returned by a local hard-gate check."""

    valid: bool
    reasons: tuple[str, ...]
    original_span: tuple[int, int] | None = None
    counterfactual_span: tuple[int, int] | None = None

    @property
    def failure_reason(self) -> str | None:
        """Return the stable primary failure reason used in error artifacts."""

        return self.reasons[0] if self.reasons else None


def _normalise(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _entity_pattern(entity: str) -> re.Pattern[str] | None:
    compact = " ".join((entity or "").split())
    if not compact:
        return None
    body = r"\s+".join(re.escape(part) for part in compact.split(" "))
    # Both guards are deliberate.  A value such as ``37`` must not be
    # accepted by matching the middle of ``137``.
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def find_entity_spans(text: str, entity: str) -> list[tuple[int, int]]:
    """Find boundary-safe entity occurrences, allowing whitespace variance."""

    pattern = _entity_pattern(entity)
    if pattern is None:
        return []
    return [(match.start(), match.end()) for match in pattern.finditer(text or "")]


def find_entity_span(text: str, entity: str) -> tuple[int, int] | None:
    """Return the first boundary-safe entity span, or ``None``."""

    spans = find_entity_spans(text, entity)
    return spans[0] if spans else None


def _aligned_substitution_spans(
    true_text: str,
    counterfactual_text: str,
    original_entity: str,
    counterfactual_entity: str,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Locate the unique changed slot by matching identical prefix/suffix."""

    for original_span in find_entity_spans(true_text, original_entity):
        for counterfactual_span in find_entity_spans(counterfactual_text, counterfactual_entity):
            if true_text[: original_span[0]] != counterfactual_text[: counterfactual_span[0]]:
                continue
            if true_text[original_span[1] :] != counterfactual_text[counterfactual_span[1] :]:
                continue
            return original_span, counterfactual_span
    return None


def _fullmatch(pattern: re.Pattern[str], value: str) -> bool:
    return pattern.fullmatch((value or "").strip()) is not None


def _looks_like_named_entity(value: str) -> bool:
    compact = " ".join((value or "").split())
    if not compact or len(compact) > 120 or not re.search(r"[A-Za-z]", compact):
        return False
    if any(_fullmatch(pattern, compact) for pattern in _STRUCTURED_PATTERNS.values()):
        return False
    return not bool(re.fullmatch(r"[\W\d_]+", compact))


def _duration_number_agrees(value: str) -> bool:
    match = _DURATION_VALUE_RE.fullmatch(" ".join((value or "").split()))
    if match is None:
        return False
    number = float(match.group("number"))
    unit = match.group("unit").casefold()
    return (number == 1.0 and not unit.endswith("s")) or (number != 1.0 and unit.endswith("s"))


def _count_unit_number_agrees(value: str) -> bool:
    match = _COUNT_UNIT_VALUE_RE.fullmatch(" ".join((value or "").split()))
    if match is None:
        return True
    number = float(match.group("number"))
    unit = match.group("unit").casefold()
    return (number == 1.0 and not unit.endswith("s")) or (
        number != 1.0 and unit.endswith("s")
    )


def _valid_date_surface(value: str) -> bool:
    """只接受真实日历日期，拒绝形似日期的等级或范围。"""

    compact = " ".join((value or "").split())
    formats = (
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y",
        "%B %d, %y",
        "%b %d, %y",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%m/%d/%y",
        "%d/%m/%y",
        "%m-%d-%Y",
        "%d-%m-%Y",
        "%m-%d-%y",
        "%d-%m-%y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    )
    for date_format in formats:
        try:
            datetime.strptime(compact, date_format)
            return True
        except ValueError:
            continue
    return False


def _valid_url_surface(value: str) -> bool:
    """Require a parseable host and reject unmatched bracket artifacts."""

    compact = (value or "").strip()
    has_scheme = re.match(r"^[a-z][a-z0-9+.-]*://", compact, re.IGNORECASE)
    try:
        parsed = urlsplit(compact if has_scheme else f"https://{compact}")
        hostname = parsed.hostname
    except ValueError:
        return False
    return bool(hostname) and not any(character.isspace() for character in hostname)


def _requires_definite_article(value: str) -> bool:
    return requires_definite_article(value)


def _obvious_generic_entity(value: str, entity_type: str, claim: str) -> bool:
    """Reject only certain non-referential surfaces that weaken membership signal."""

    compact = " ".join((value or "").split())
    kind = (entity_type or "").upper()
    if kind == "ORG":
        return _OBVIOUS_GENERIC_ORG_RE.fullmatch(compact) is not None
    if kind == "PRODUCT":
        if _OBVIOUS_GENERIC_PRODUCT_RE.fullmatch(compact) is not None:
            return True
        return bool(
            re.fullmatch(r"[A-Z][A-Za-z&/-]*\s+Services", compact)
            and re.search(r"\bservice lines?\b", claim, re.IGNORECASE)
        )
    return False


def _attack_subtype_failure_reasons(
    original_entity: str,
    counterfactual_entity: str,
    entity_type: str,
    true_claim: str,
    counterfactual_claim: str,
) -> tuple[str, ...]:
    """Reject only coarse semantic conflicts that make Q− visibly implausible."""

    kind = (entity_type or "").upper()
    if kind not in {"LOCATION", "PRODUCT"}:
        return ()
    original_subtype = infer_attack_subtype(
        original_entity,
        kind,
        context=true_claim,
    )
    counterfactual_subtype = infer_attack_subtype(
        counterfactual_entity,
        kind,
        context=counterfactual_claim,
    )
    if (
        original_subtype is not None
        and counterfactual_subtype is not None
        and original_subtype != counterfactual_subtype
    ):
        return (f"counterfactual_{kind.casefold()}_attack_subtype_mismatch",)
    return ()


def _indefinite_article_mismatch(
    claim: str,
    span: tuple[int, int] | None,
    entity: str,
) -> bool:
    """Detect only the deterministic ``a``/``an`` initial-letter mismatch."""

    if span is None:
        return False
    prefix = claim[: span[0]]
    match = re.search(r"\b(a|an)\s+$", prefix, re.IGNORECASE)
    first_letter = next(
        (character.casefold() for character in entity if character.isalpha()),
        "",
    )
    if match is None or not first_letter:
        return False
    vowel_initial = first_letter in {"a", "e", "i", "o", "u"}
    article = match.group(1).casefold()
    return (article == "an" and not vowel_initial) or (
        article == "a" and vowel_initial
    )


def _org_span_has_incomplete_boundary(text: str, span: tuple[int, int]) -> bool:
    """Detect an ORG slot that covers a tail, connector, or comma-separated list."""

    start, end = span
    value = " ".join(text[start:end].split())
    # A symbol connector is part of a compound legal name (``A & B, Inc``),
    # whereas grammatical ``of/and <ORG>`` may legitimately introduce a
    # complete entity and must not be rejected from left context alone.
    if _ORG_PREFIX_CONNECTOR_RE.search(text[:start]):
        return True
    # A following ``of`` exposes a truncated entity such as ``University`` in
    # ``University of Ghana``.  ``and/or`` may simply separate two complete
    # entities, so those words are intentionally not treated as failures.
    if _ORG_SUFFIX_CONNECTOR_RE.search(text[end:]):
        return True
    if "," not in value:
        return False
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2 or not all(parts):
        return True
    if all(_CHEMICAL_SYMBOL_RE.fullmatch(part) for part in parts):
        return True
    return _ORG_CORPORATE_DESIGNATOR_RE.fullmatch(parts[1]) is None


def _accepted_semantic_resolution(
    resolution: object,
    entity_type: str,
) -> bool:
    """仅允许完整绑定的新策略 semantic 结果覆盖旧表面 heuristic。"""

    kind = str(entity_type or "").upper()
    if kind not in SEMANTIC_TARGET_TYPES or not isinstance(resolution, dict):
        return False
    policy = entity_type_policy(kind)
    subtype = str(resolution.get("subtype") or "")
    return bool(
        resolution.get("accepted")
        and resolution.get("protocol") == SEMANTIC_RESOLVER_PROTOCOL
        and resolution.get("schema_sha256") == SEMANTIC_SCHEMA_SHA256
        and resolution.get("entity_policy_version")
        in {None, ENTITY_TYPE_POLICY_VERSION}
        and resolution.get("entity_policy_sha256")
        in {None, ENTITY_TYPE_POLICY_SHA256}
        and str(resolution.get("entity_type") or "").upper() == kind
        and subtype in policy.allowed_subtypes
    )


def _semantic_surface_is_complete(value: str) -> bool:
    compact = " ".join((value or "").split())
    return bool(
        compact
        and re.search(r"[A-Za-z0-9]", compact)
        and not _NAMED_ENTITY_TRAILING_BOUNDARY_RE.search(compact)
        and not _NAMED_ENTITY_ENCODING_RE.search(compact)
    )


def _surface_matches_type(
    value: str,
    entity_type: str,
    *,
    semantic_resolution: object = None,
) -> bool:
    compact = " ".join((value or "").split())
    kind = (entity_type or "").upper()
    if not compact:
        return False
    if _accepted_semantic_resolution(semantic_resolution, kind):
        return _semantic_surface_is_complete(compact)
    if kind == "NUMERIC_VALUE":
        return re.fullmatch(r"\d+(?:,\d{3})*(?:\.\d+)?", compact) is not None
    if kind in _STRUCTURED_PATTERNS:
        if not _fullmatch(_STRUCTURED_PATTERNS[kind], compact):
            return False
        if kind == "DATE":
            return _valid_date_surface(compact)
        if kind == "DURATION":
            return _duration_number_agrees(compact)
        if kind == "MEDICAL_VALUE":
            return _count_unit_number_agrees(compact)
        if kind == "URL":
            return _valid_url_surface(compact)
        if kind == "PROJECT_NAME":
            return not is_likely_bad_project_name(compact)
        if kind == "IDENTIFIER":
            return not is_likely_bad_identifier(compact)
        return True
    if kind in _NAMED_TYPES:
        if not _looks_like_named_entity(compact):
            return False
        if kind == "PERSON":
            words = compact.replace(".", "").split()
            if words and words[0] in _PERSON_LEADING_STOPWORDS:
                return False
            return not is_likely_bad_person(compact)
        return True
    # Unknown legacy types are allowed only as non-empty textual values.  This
    # keeps the validator backward compatible while still rejecting a
    # structured value masquerading as a named/domain entity.
    return bool(re.search(r"[A-Za-z0-9]", compact))


def _looks_like_tabular_fragment(compact: str) -> bool:
    """Reject flattened table rows while preserving ordinary long prose."""

    words = compact.split()
    if (
        len(words) >= 20
        and _TABULAR_COLUMN_HEADER_RE.search(compact)
        and len(_TABULAR_PERCENT_CELL_RE.findall(compact)) >= 6
    ):
        return True
    if len(words) < 35:
        return False
    category_cells = len(_TABULAR_CATEGORY_RE.findall(compact))
    slashed_cells = len(_TABULAR_SLASHED_CELL_RE.findall(compact))
    sparse_sentence_punctuation = compact.count(",") + compact.count(";") <= 3
    return category_cells >= 4 and slashed_cells >= 3 and sparse_sentence_punctuation


def _claim_completeness_reasons(claim: str, max_claim_chars: int) -> list[str]:
    compact = " ".join((claim or "").split())
    reasons: list[str] = []
    if not compact:
        return ["claim_empty"]
    if len(compact) > max_claim_chars:
        reasons.append("claim_too_long")
    if len(compact.split()) < 4:
        reasons.append("claim_too_short")
    semantic_reasons = sentence_semantic_failure_reasons(claim)
    semantic_reason_map = {
        "supporting_sentence_incomplete": "claim_truncated",
        "supporting_sentence_truncated_ending": "claim_truncated",
        "supporting_sentence_lowercase_fragment": "claim_fragment_surface",
        "supporting_sentence_email_list": "claim_email_list",
        "supporting_sentence_unbalanced_quote": "claim_unbalanced_quote",
        "supporting_sentence_unbalanced_delimiters": "claim_unbalanced_delimiters",
        "supporting_sentence_numeric_table": "claim_tabular_fragment",
        "supporting_sentence_email_metadata": "claim_email_metadata",
        "supporting_sentence_encoding_or_mailbox_artifact": "claim_encoding_or_mailbox_artifact",
        "supporting_sentence_markup_artifact": "claim_markup_artifact",
        "supporting_sentence_fragment_surface": "claim_fragment_surface",
        "supporting_sentence_internal_address_list": "claim_abnormal_multiline_structure",
        "supporting_sentence_excessive_multiline_structure": "claim_abnormal_multiline_structure",
        "supporting_sentence_truncated_enumeration": "claim_truncated",
        "supporting_sentence_repeated_link_list": "claim_abnormal_link_list",
        "supporting_sentence_heading_prefix": "claim_heading_prefix",
        "supporting_sentence_nominal_fragment": "claim_fragment_surface",
    }
    reasons.extend(semantic_reason_map[reason] for reason in semantic_reasons if reason in semantic_reason_map)
    if _TRAILING_FRAGMENT_RE.search(compact):
        reasons.append("claim_truncated")
    if compact.count("(") != compact.count(")") or compact.count("[") != compact.count("]"):
        reasons.append("claim_unbalanced_delimiters")
    if compact.count("{") != compact.count("}"):
        reasons.append("claim_unbalanced_delimiters")
    if re.search(r"\b([A-Za-z]{2,})\s+\1\b", compact, re.IGNORECASE):
        reasons.append("claim_repeated_token")
    if _looks_like_tabular_fragment(compact):
        reasons.append("claim_tabular_fragment")
    if (
        _OBVIOUS_NUMERIC_OF_FRAGMENT_RE.search(compact)
        or _OBVIOUS_DETACHED_INFINITIVE_RE.search(compact)
        or _OBVIOUS_COPYRIGHT_FRAGMENT_RE.search(compact)
        or _OBVIOUS_PROMOTIONAL_HEADLINE_RE.search(compact)
        or _OBVIOUS_ROUTE_FRAGMENT_RE.search(compact)
    ):
        reasons.append("claim_obvious_fragment")
    return reasons


def _metadata_semantic_failure_reasons(
    value: str,
    entity_type: str,
    claim: str,
    span: tuple[int, int] | None,
    entity_metadata: dict[str, object],
) -> tuple[str, ...]:
    """Reject domain-semantic false positives that a general NER model accepts."""

    compact = " ".join((value or "").split())
    kind = (entity_type or "").upper()
    reasons: list[str] = []
    semantic_authoritative = _accepted_semantic_resolution(
        entity_metadata.get("semantic_resolution"),
        kind,
    )
    if kind in _NAMED_TYPES:
        if _NAMED_ENTITY_TRAILING_BOUNDARY_RE.search(compact):
            reasons.append("named_entity_trailing_boundary")
        if _NAMED_ENTITY_ENCODING_RE.search(compact):
            reasons.append("named_entity_encoding_artifact")

    if span is None:
        return tuple(dict.fromkeys(reasons))
    start, end = span
    before = claim[max(0, start - 120) : start]
    after = claim[end : min(len(claim), end + 120)]
    window = claim[max(0, start - 180) : min(len(claim), end + 180)]

    if semantic_authoritative:
        sources = {
            str(item).casefold()
            for item in (entity_metadata.get("candidate_sources") or [])
        }
        if not sources:
            reasons.append("semantic_entity_missing_extractor_provenance")
        return tuple(dict.fromkeys(reasons))

    if kind == "PERSON":
        if _PERSON_NONHUMAN_SUFFIX_RE.match(after):
            reasons.append("person_nonhuman_context")

    if kind == "ORG":
        strong_surface = _ORG_STRONG_TOKEN_RE.search(compact) is not None
        exact_types = {
            str(item).upper()
            for item in (entity_metadata.get("ner_exact_types") or [])
        }
        technical_surface = bool(
            _ORG_TECHNICAL_TOKEN_RE.fullmatch(compact)
            or _ORG_GENERIC_OR_TECHNICAL_PHRASE_RE.search(compact)
        )
        if not strong_surface and technical_surface:
            reasons.append("org_technical_or_biological_token")
        titlecase_surface = compact[:1].isupper() and compact.casefold() != compact
        if (
            not technical_surface
            and not strong_surface
            and "ORG" not in exact_types
            and not (titlecase_surface and _ORG_CONTEXT_CUE_RE.search(window))
        ):
            reasons.append("org_missing_organization_context")

    if kind == "LOCATION":
        if _LOCATION_TECHNICAL_SURFACE_RE.fullmatch(compact):
            reasons.append("location_technical_or_named_method")
        if _LOCATION_NONLOCATION_SUFFIX_RE.match(after):
            reasons.append("location_nonlocation_suffix")
        if _LOCATION_ORG_OR_METHOD_CONTEXT_RE.search(window):
            reasons.append("location_organization_or_method_context")
        exact_types = {
            str(item).upper()
            for item in (entity_metadata.get("ner_exact_types") or [])
        }
        context_supported = bool(
            "LOCATION" in exact_types
            or _LOCATION_CONTEXT_BEFORE_RE.search(before)
            or _LOCATION_CONTEXT_AFTER_RE.search(after)
        )
        if not context_supported:
            reasons.append("location_missing_geographic_context")

    if kind == "CONTRACT_TERM" and not _STRICT_CONTRACT_CUE_RE.search(window):
        reasons.append("contract_term_missing_strict_contract_context")

    # The metadata is part of the protocol binding even when surface/context
    # rules make the decision.  A formal named entity must originate from the
    # frozen local extractor rather than an untracked caller.
    if kind in SEMANTIC_TARGET_TYPES:
        sources = {
            str(item).casefold()
            for item in (entity_metadata.get("candidate_sources") or [])
        }
        if not sources:
            reasons.append("semantic_entity_missing_extractor_provenance")
    return tuple(dict.fromkeys(reasons))


def _semantic_resolution_failure_reasons(
    entity_type: str,
    entity_metadata: dict[str, object],
    counterfactual_resolution: dict[str, object] | None,
    *,
    required: bool,
) -> tuple[str, ...]:
    """Bind both slots to the same frozen v6.3 semantic protocol."""

    kind = (entity_type or "").upper()
    if kind not in SEMANTIC_TARGET_TYPES:
        return ()
    reasons: list[str] = []
    policy = entity_type_policy(kind)
    original_resolution = entity_metadata.get("semantic_resolution")
    if not isinstance(original_resolution, dict):
        if required:
            reasons.append("original_semantic_resolution_missing")
        return tuple(reasons)

    if original_resolution.get("protocol") != SEMANTIC_RESOLVER_PROTOCOL:
        reasons.append("original_semantic_protocol_mismatch")
    if original_resolution.get("schema_sha256") != SEMANTIC_SCHEMA_SHA256:
        reasons.append("original_semantic_schema_mismatch")
    if not bool(original_resolution.get("accepted")):
        reasons.append("original_semantic_resolution_rejected")
    if str(original_resolution.get("entity_type") or "").upper() != kind:
        reasons.append("original_semantic_type_mismatch")
    if str(original_resolution.get("subtype") or "") not in policy.allowed_subtypes:
        reasons.append("original_semantic_subtype_not_allowed")
    if original_resolution.get("entity_policy_version") not in {
        None,
        ENTITY_TYPE_POLICY_VERSION,
    }:
        reasons.append("original_semantic_entity_policy_version_mismatch")
    if original_resolution.get("entity_policy_sha256") not in {
        None,
        ENTITY_TYPE_POLICY_SHA256,
    }:
        reasons.append("original_semantic_entity_policy_hash_mismatch")

    if not isinstance(counterfactual_resolution, dict):
        if required:
            reasons.append("counterfactual_semantic_resolution_missing")
        return tuple(dict.fromkeys(reasons))
    if counterfactual_resolution.get("protocol") != SEMANTIC_RESOLVER_PROTOCOL:
        reasons.append("counterfactual_semantic_protocol_mismatch")
    if counterfactual_resolution.get("schema_sha256") != SEMANTIC_SCHEMA_SHA256:
        reasons.append("counterfactual_semantic_schema_mismatch")
    if not bool(counterfactual_resolution.get("accepted")):
        reasons.append("counterfactual_semantic_resolution_rejected")
        resolution_failures = counterfactual_resolution.get("failure_reasons")
        if isinstance(resolution_failures, (list, tuple)):
            reasons.extend(
                f"counterfactual_{reason}"
                for reason in resolution_failures
            )
    if str(counterfactual_resolution.get("entity_type") or "").upper() != kind:
        reasons.append("counterfactual_semantic_type_mismatch")
    if (
        str(counterfactual_resolution.get("subtype") or "")
        not in policy.allowed_subtypes
    ):
        reasons.append("counterfactual_semantic_subtype_not_allowed")
    if counterfactual_resolution.get("entity_policy_version") not in {
        None,
        ENTITY_TYPE_POLICY_VERSION,
    }:
        reasons.append("counterfactual_semantic_entity_policy_version_mismatch")
    if counterfactual_resolution.get("entity_policy_sha256") not in {
        None,
        ENTITY_TYPE_POLICY_SHA256,
    }:
        reasons.append("counterfactual_semantic_entity_policy_hash_mismatch")
    if (
        original_resolution.get("subtype")
        != counterfactual_resolution.get("subtype")
    ):
        reasons.append("counterfactual_semantic_subtype_mismatch")
    original_format = original_resolution.get("format_signature")
    counterfactual_format = counterfactual_resolution.get("format_signature")
    if not (
        isinstance(original_format, dict)
        and isinstance(counterfactual_format, dict)
        and semantic_format_compatible(
            original_format,
            counterfactual_format,
            kind,
        )
    ):
        reasons.append("counterfactual_semantic_format_mismatch")
    return tuple(dict.fromkeys(reasons))


def validate_claim_pair(
    true_claim: str,
    counterfactual_claim: str,
    original_entity: str,
    counterfactual_entity: str,
    entity_type: str,
    *,
    max_claim_chars: int = 1200,
    entity_metadata: dict[str, object] | None = None,
    counterfactual_semantic_resolution: dict[str, object] | None = None,
    semantic_resolution_required: bool = False,
) -> ValidationResult:
    """Apply every canonical claim-pair hard gate locally."""

    reasons: list[str] = []
    kind = (entity_type or "").upper()
    original_resolution = (
        entity_metadata.get("semantic_resolution")
        if isinstance(entity_metadata, dict)
        else None
    )
    original_semantic_authoritative = _accepted_semantic_resolution(
        original_resolution,
        kind,
    )
    counterfactual_semantic_authoritative = _accepted_semantic_resolution(
        counterfactual_semantic_resolution,
        kind,
    )
    semantic_pair_authoritative = bool(
        original_semantic_authoritative
        and counterfactual_semantic_authoritative
    )
    true_spans = find_entity_spans(true_claim, original_entity)
    counterfactual_spans = find_entity_spans(counterfactual_claim, counterfactual_entity)
    if not true_spans:
        reasons.append("original_entity_boundary_not_found")
    if not counterfactual_spans:
        reasons.append("counterfactual_entity_boundary_not_found")
    if _normalise(original_entity) == _normalise(counterfactual_entity):
        reasons.append("counterfactual_entity_unchanged")
    if not _surface_matches_type(
        original_entity,
        entity_type,
        semantic_resolution=original_resolution,
    ):
        reasons.append("original_entity_type_mismatch")
    if not _surface_matches_type(
        counterfactual_entity,
        entity_type,
        semantic_resolution=counterfactual_semantic_resolution,
    ):
        reasons.append("counterfactual_entity_type_mismatch")

    aligned = _aligned_substitution_spans(
        true_claim,
        counterfactual_claim,
        original_entity,
        counterfactual_entity,
    )
    if aligned is None:
        reasons.append("not_single_slot_substitution")

    if kind == "ORG":
        original_spans = [aligned[0]] if aligned else true_spans
        counterfactual_org_spans = [aligned[1]] if aligned else counterfactual_spans
        if original_spans and all(_org_span_has_incomplete_boundary(true_claim, span) for span in original_spans):
            reasons.append("original_entity_context_boundary_mismatch")
        if counterfactual_org_spans and all(
            _org_span_has_incomplete_boundary(counterfactual_claim, span)
            for span in counterfactual_org_spans
        ):
            reasons.append("counterfactual_entity_context_boundary_mismatch")
    original_context_spans = [aligned[0]] if aligned else true_spans
    counterfactual_context_spans = [aligned[1]] if aligned else counterfactual_spans
    if original_context_spans and not original_semantic_authoritative:
        original_failures = [
            entity_context_failure_reasons(true_claim, span, kind)
            for span in original_context_spans
        ]
        if all(original_failures):
            reasons.append("original_entity_context_mismatch")
            reasons.extend(f"original_{reason}" for reason in original_failures[0])
    if counterfactual_context_spans and not counterfactual_semantic_authoritative:
        counterfactual_failures = [
            entity_context_failure_reasons(counterfactual_claim, span, kind)
            for span in counterfactual_context_spans
        ]
        if all(counterfactual_failures):
            reasons.append("counterfactual_entity_context_mismatch")
            reasons.extend(f"counterfactual_{reason}" for reason in counterfactual_failures[0])
    if kind == "NUMERIC_VALUE" and re.fullmatch(r"(?:19|20)\d{2}", (original_entity or "").strip()):
        if re.fullmatch(r"(?:19|20)\d{2}", (counterfactual_entity or "").strip()) is None:
            reasons.append("counterfactual_year_subtype_mismatch")
    if kind == "DURATION" and not _duration_number_agrees(counterfactual_entity):
        reasons.append("counterfactual_duration_number_agreement")
    if (
        kind == "LOCATION"
        and not semantic_pair_authoritative
        and _requires_definite_article(original_entity)
        != _requires_definite_article(counterfactual_entity)
    ):
        reasons.append("counterfactual_location_article_class_mismatch")
    if not semantic_pair_authoritative:
        reasons.extend(
            _attack_subtype_failure_reasons(
                original_entity,
                counterfactual_entity,
                kind,
                true_claim,
                counterfactual_claim,
            )
        )
    if (
        not original_semantic_authoritative
        and _obvious_generic_entity(original_entity, kind, true_claim)
    ):
        reasons.append("original_entity_obvious_generic")
    if _indefinite_article_mismatch(
        counterfactual_claim,
        aligned[1] if aligned else (
            counterfactual_spans[0] if counterfactual_spans else None
        ),
        counterfactual_entity,
    ):
        reasons.append("counterfactual_indefinite_article_mismatch")
    if entity_metadata is not None:
        metadata_reasons = _metadata_semantic_failure_reasons(
            original_entity,
            kind,
            true_claim,
            aligned[0] if aligned else (true_spans[0] if true_spans else None),
            entity_metadata,
        )
        if metadata_reasons:
            reasons.append("original_entity_metadata_semantic_mismatch")
            reasons.extend(f"original_{reason}" for reason in metadata_reasons)
    semantic_reasons = _semantic_resolution_failure_reasons(
        kind,
        entity_metadata or {},
        counterfactual_semantic_resolution,
        required=semantic_resolution_required,
    )
    reasons.extend(semantic_reasons)

    for reason in _claim_completeness_reasons(true_claim, max_claim_chars):
        reasons.append(f"true_{reason}")
    for reason in _claim_completeness_reasons(counterfactual_claim, max_claim_chars):
        reasons.append(f"counterfactual_{reason}")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return ValidationResult(
        valid=not unique_reasons,
        reasons=unique_reasons,
        original_span=aligned[0] if aligned else (true_spans[0] if true_spans else None),
        counterfactual_span=aligned[1] if aligned else (counterfactual_spans[0] if counterfactual_spans else None),
    )


def validate_query_pair(
    positive_query: str,
    negative_query: str,
    original_entity: str,
    counterfactual_entity: str,
) -> ValidationResult:
    """Require Q+ and Q- to be byte-identical outside the entity slot."""

    aligned = _aligned_substitution_spans(
        positive_query,
        negative_query,
        original_entity,
        counterfactual_entity,
    )
    reasons: list[str] = []
    if not find_entity_spans(positive_query, original_entity):
        reasons.append("qplus_entity_boundary_not_found")
    if not find_entity_spans(negative_query, counterfactual_entity):
        reasons.append("qminus_entity_boundary_not_found")
    if aligned is None:
        reasons.append("query_pair_differs_outside_entity")
    return ValidationResult(
        valid=not reasons,
        reasons=tuple(reasons),
        original_span=aligned[0] if aligned else None,
        counterfactual_span=aligned[1] if aligned else None,
    )
