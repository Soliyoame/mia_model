"""Pure, label-free selector primitives for PCV-MIA v23 Restoration-First."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from decimal import Decimal, ROUND_HALF_EVEN
from collections.abc import Callable
from typing import Any, Iterable, Mapping, Sequence

from .attackability_selector import machine_format_compatible, route_effective_type
from .entity_extractor import EntityExtractor
from .semantic_entity_resolver import semantic_subtype
from ..utils.io import load_yaml


PROTOCOL_VERSION = "pcv-mia-v23"
METHOD_VERSION = "pcv-restoration-first-v23"
SPECIFICATION_VERSION = "pcv-restoration-first-v23-design-r6"
FORMAL_TYPES = frozenset({"PERSON", "ORG", "LOCATION", "PRODUCT", "CONTRACT_TERM"})
ENTITY_SLOT = "ENTITY_SLOT"

FORBIDDEN_SELECTION_FIELDS = frozenset(
    {
        "membership",
        "membership_label",
        "member_label",
        "split",
        "group",
        "victim_response",
        "victim_answer",
        "rag_response",
        "llm_only_response",
        "llm_only_answer",
        "retriever_output",
        "retrieval_rank",
        "retrieval_score",
        "retrieved_documents",
        "attack_score",
        "attack_auc",
        "auc",
        "v22_calibration_label",
        "v22_calibration_threshold",
    }
)

SOURCE_FIELDS = {
    "dataset": str,
    "source_key": str,
    "source_order_rank": str,
    "full_text": str,
    "input_row_count": int,
    "chunks": list,
}
CHUNK_FIELDS = {
    "source_key": str,
    "chunk_rank": int,
    "selection_hash": str,
    "row": dict,
}
ROW_FIELDS: dict[str, type | tuple[type, ...]] = {
    "audit_id": str,
    "doc_id": str,
    "source_id": str,
    "source_path": str,
    "source_key": str,
    "dataset": str,
    "text": str,
    "text_hash": str,
    "chunk_index": (int, type(None)),
}

STOPWORDS = frozenset(
    "a an and are as at be been being but by can could did do does for from had has "
    "have he her here him his how i if in into is it its may might more most no not of "
    "on or our shall she should than that the their them then there these they this those "
    "to was we were what when where which who why will with would you your".split()
)
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
PROPOSITION_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
RELATION_CUE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|will|would|shall|should|can|"
    r"could|received|paid|sent|met|meet|discussed|signed|reported|increased|decreased|"
    r"acquired|sold|filed|approved|required|requires|expires|begins|ends|contains|"
    r"assigned|located|treated|measured|observed|compared)\b",
    re.IGNORECASE | re.UNICODE,
)
MAIL_HEADER_RE = re.compile(
    r"^\s*(?:from|to|cc|bcc|subject|sent|date|message-id|content-type)\s*:",
    re.IGNORECASE | re.UNICODE,
)
UNRESOLVED_REFERENCE_RE = re.compile(
    r"\b(?:this|that|these|those|here|there|above|below|aforementioned|former|latter|"
    r"he|she|it|they)\b",
    re.IGNORECASE | re.UNICODE,
)
GENERIC_ROLE_RE = re.compile(
    r"^(?:president|director|manager|officer|author|employee|customer|company|department|"
    r"team|group|system|service|product|agreement)$",
    re.IGNORECASE | re.UNICODE,
)
ARTICLE_FRAME_RE = re.compile(r"\b(a|an)\s+$", re.IGNORECASE | re.UNICODE)


def canonical_json(value: Any) -> str:
    """Return the exact v23 canonical JSON representation."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def normalized_text_sha256(value: str) -> str:
    return text_sha256(normalize_text(value))


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def reject_forbidden_selection_fields(value: Any, *, path: str = "root") -> None:
    """Reject forbidden downstream signals anywhere in a serialized payload."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError(f"selector_key_not_string:{path}")
            if key.casefold() in FORBIDDEN_SELECTION_FIELDS:
                raise ValueError(f"forbidden_selection_field:{path}.{key}")
            reject_forbidden_selection_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            reject_forbidden_selection_fields(nested, path=f"{path}[{index}]")


def _validate_exact_object(
    value: Any,
    schema: Mapping[str, type | tuple[type, ...]],
    *,
    path: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"selector_type_error:{path}:object")
    actual = set(value)
    expected = set(schema)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"selector_schema_error:{path}:missing={missing}:unknown={unknown}")
    for field, expected_type in schema.items():
        item = value[field]
        if expected_type is int and isinstance(item, bool):
            raise ValueError(f"selector_type_error:{path}.{field}:int")
        if not isinstance(item, expected_type):
            raise ValueError(f"selector_type_error:{path}.{field}")
    return value


def validate_selector_source_input(value: Any) -> dict[str, Any]:
    """Enforce the recursive exact serialized selector input contract."""

    reject_forbidden_selection_fields(value)
    source = _validate_exact_object(value, SOURCE_FIELDS, path="root")
    if source["dataset"] not in {"edgar", "enron", "pubmed"}:
        raise ValueError("selector_dataset_invalid")
    if not source["source_key"] or not source["full_text"]:
        raise ValueError("selector_source_empty")
    if source["input_row_count"] < 1:
        raise ValueError("selector_input_row_count_invalid")
    validated_chunks: list[dict[str, Any]] = []
    for index, raw_chunk in enumerate(source["chunks"]):
        chunk = _validate_exact_object(raw_chunk, CHUNK_FIELDS, path=f"root.chunks[{index}]")
        if not _is_sha256(chunk["selection_hash"]):
            raise ValueError(f"selector_sha256_invalid:root.chunks[{index}].selection_hash")
        row = _validate_exact_object(
            chunk["row"], ROW_FIELDS, path=f"root.chunks[{index}].row"
        )
        if not _is_sha256(row["text_hash"]):
            raise ValueError(f"selector_sha256_invalid:root.chunks[{index}].row.text_hash")
        if chunk["source_key"] != source["source_key"] or row["source_key"] != source["source_key"]:
            raise ValueError("selector_source_key_mismatch")
        if row["dataset"] != source["dataset"]:
            raise ValueError("selector_dataset_mismatch")
        validated_chunks.append({**chunk, "row": dict(row)})
    if len(validated_chunks) > 5:
        raise ValueError("selector_chunk_limit_exceeded")
    return {**source, "chunks": validated_chunks}


def segment_propositions(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in PROPOSITION_RE.finditer(text):
        raw = match.group(0)
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right <= left:
            continue
        start = match.start() + left
        end = match.start() + right
        rows.append({"start": start, "end": end, "text": text[start:end]})
    return rows


def content_tokens(value: str) -> list[str]:
    tokens = TOKEN_RE.findall(normalize_text(value))
    return [
        token
        for token in tokens
        if len(token) >= 3 and not token.isdigit() and token not in STOPWORDS
    ]


def bounded_occurrence_count(text: str, value: str) -> int:
    haystack = normalize_text(text)
    needle = normalize_text(value)
    if not needle:
        return 0
    count = 0
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return count
        end = index + len(needle)
        left_ok = index == 0 or not haystack[index - 1].isalnum()
        right_ok = end == len(haystack) or not haystack[end].isalnum()
        if left_ok and right_ok:
            count += 1
        start = index + 1


def _literal_occurrence_count(text: str, value: str) -> int:
    if not value:
        return 0
    return sum(1 for _ in re.finditer(re.escape(value), text))


def _balanced_delimiters(value: str) -> bool:
    opening = {"(": ")", "[": "]", "{": "}"}
    closing = {item: key for key, item in opening.items()}
    stack: list[str] = []
    for character in value:
        if character in opening:
            stack.append(character)
        elif character in closing:
            if not stack or stack.pop() != closing[character]:
                return False
    return not stack


def _article_compatible(prefix: str, candidate: str) -> bool:
    match = ARTICLE_FRAME_RE.search(prefix)
    if match is None:
        return True
    first = next((character.casefold() for character in candidate if character.isascii() and character.isalpha()), None)
    if first is None:
        return False
    starts_with_vowel = first in "aeiou"
    return starts_with_vowel if match.group(1).casefold() == "an" else not starts_with_vowel


def _mask_sentence(sentence: str, span: Sequence[int]) -> str:
    start, end = int(span[0]), int(span[1])
    return f"{sentence[:start]}{ENTITY_SLOT}{sentence[end:]}"


def relation_signature(
    *, dataset: str, source_key: str, effective_type: str, masked_sentence: str
) -> str:
    return canonical_sha256(
        {
            "kind": "v23_relation_signature",
            "dataset": dataset,
            "source_key": source_key,
            "effective_type": effective_type,
            "masked_sentence_normalized": normalize_text(masked_sentence),
        }
    )


def fact_signature(*, dataset: str, source_key: str, sentence: str) -> str:
    return canonical_sha256(
        {
            "kind": "v23_fact_signature",
            "dataset": dataset,
            "source_key": source_key,
            "sentence_hash": text_sha256(sentence.strip()),
        }
    )


def _remove_entity_spans(text: str, spans: Iterable[Sequence[int]]) -> str:
    clipped: list[tuple[int, int]] = []
    for span in spans:
        if len(span) != 2:
            continue
        start = max(0, min(len(text), int(span[0])))
        end = max(start, min(len(text), int(span[1])))
        if end > start:
            clipped.append((start, end))
    clipped.sort(key=lambda item: (item[0], -item[1]))
    merged: list[list[int]] = []
    for start, end in clipped:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    output: list[str] = []
    cursor = 0
    for start, end in merged:
        output.extend((text[cursor:start], " "))
        cursor = end
    output.append(text[cursor:])
    return "".join(output)


def _counterfactual_identity(candidate: Mapping[str, Any], replacement: str) -> str:
    return canonical_sha256(
        {
            "kind": "v23_counterfactual",
            "specification_version": SPECIFICATION_VERSION,
            "dataset": candidate["dataset"],
            "source_key": candidate["source_key"],
            "sentence_hash": text_sha256(candidate["supporting_sentence"].strip()),
            "original_span": list(candidate["original_span"]),
            "effective_type": candidate["effective_type"],
            "semantic_subtype": candidate["semantic_subtype"],
            "counterfactual_normalized": normalize_text(replacement),
        }
    )


def _pair_identity(
    *, fact_id: str, original: str, replacement: str, counterfactual_id: str
) -> str:
    return canonical_sha256(
        {
            "kind": "v23_pair",
            "specification_version": SPECIFICATION_VERSION,
            "fact_signature": fact_id,
            "original_entity_normalized": normalize_text(original),
            "counterfactual_normalized": normalize_text(replacement),
            "counterfactual_id": counterfactual_id,
        }
    )


def _filler_inventory(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = candidate.get("filler_inventory")
    if not isinstance(raw, list):
        raise ValueError("candidate_filler_inventory_invalid")
    inventory: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"candidate_filler_invalid:{index}")
        required = {
            "surface",
            "effective_type",
            "relation_signature",
            "proposition_raw_start",
            "proposition_raw_end",
            "filler_span",
        }
        if set(item) != required:
            raise ValueError(f"candidate_filler_schema_invalid:{index}")
        if not all(
            isinstance(item[key], str)
            for key in ("surface", "effective_type", "relation_signature")
        ):
            raise ValueError(f"candidate_filler_type_invalid:{index}")
        if (
            isinstance(item["proposition_raw_start"], bool)
            or not isinstance(item["proposition_raw_start"], int)
            or isinstance(item["proposition_raw_end"], bool)
            or not isinstance(item["proposition_raw_end"], int)
            or not isinstance(item["filler_span"], list)
            or len(item["filler_span"]) != 2
            or not all(isinstance(value, int) and not isinstance(value, bool) for value in item["filler_span"])
        ):
            raise ValueError(f"candidate_filler_coordinate_invalid:{index}")
        inventory.append(dict(item))
    return inventory


def _candidate_base_reasons(candidate: Mapping[str, Any], source_text: str) -> list[str]:
    required = {
        "dataset",
        "source_key",
        "source_order_rank",
        "supporting_sentence",
        "original_entity",
        "original_span",
        "effective_type",
        "semantic_subtype",
        "entity_spans",
        "filler_inventory",
        "counterfactual_pool",
    }
    missing = sorted(required - set(candidate))
    if missing:
        raise ValueError(f"candidate_missing_fields:{missing}")
    reject_forbidden_selection_fields(candidate, path="candidate")
    sentence = candidate["supporting_sentence"]
    original = candidate["original_entity"]
    span = candidate["original_span"]
    reasons: list[str] = []
    if not isinstance(sentence, str) or not isinstance(original, str):
        raise ValueError("candidate_string_type_invalid")
    if not (
        isinstance(span, (list, tuple))
        and len(span) == 2
        and all(isinstance(value, int) and not isinstance(value, bool) for value in span)
    ):
        raise ValueError("candidate_span_invalid")
    start, end = span
    if start < 0 or end <= start or end > len(sentence) or sentence[start:end] != original:
        reasons.append("exact_original_span")
    if candidate["effective_type"] not in FORMAL_TYPES:
        reasons.append("formal_type")
    if not original.strip() or GENERIC_ROLE_RE.fullmatch(normalize_text(original)):
        reasons.append("generic_original_entity")
    if _literal_occurrence_count(source_text, sentence.strip()) < 1:
        reasons.append("original_sentence_absent")
    if MAIL_HEADER_RE.match(sentence):
        reasons.append("mail_header")
    if UNRESOLVED_REFERENCE_RE.search(sentence):
        reasons.append("unresolved_reference")
    if not sentence.rstrip().endswith((".", ";")):
        reasons.append("non_declarative_terminal")
    word_count = len(re.findall(r"[A-Za-z0-9]+", sentence))
    if not 8 <= word_count <= 80:
        reasons.append("fact_token_count")
    cue_matches = list(RELATION_CUE_RE.finditer(sentence))
    if not cue_matches:
        reasons.append("relation_cue_missing")
    masked = _mask_sentence(sentence, span) if not reasons or "exact_original_span" not in reasons else ""
    if masked.count(ENTITY_SLOT) != 1:
        reasons.append("entity_slot_count")
    masked_cues = list(RELATION_CUE_RE.finditer(masked))
    if masked_cues:
        before = content_tokens(masked[: masked_cues[0].start()])
        if not before:
            reasons.append("explicit_subject_missing")
    return list(dict.fromkeys(reasons))


def build_pair_candidates(
    source: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    token_df: Mapping[str, int],
    source_count: int,
    token_df_prevalidated: bool = False,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Recompute all v23 hard gates and rank features for one fact candidate."""

    validated_source = validate_selector_source_input(source)
    source_text = validated_source["full_text"]
    if candidate.get("dataset") != validated_source["dataset"] or candidate.get("source_key") != validated_source["source_key"]:
        raise ValueError("candidate_source_identity_mismatch")
    if candidate.get("source_order_rank") != validated_source["source_order_rank"]:
        raise ValueError("candidate_source_order_rank_mismatch")
    if source_count <= 0:
        raise ValueError("source_count_invalid")
    if not token_df_prevalidated and any(
        not isinstance(token, str)
        or isinstance(df, bool)
        or not isinstance(df, int)
        or df < 1
        or df > source_count
        for token, df in token_df.items()
    ):
        raise ValueError("token_df_invalid")
    base_reasons = _candidate_base_reasons(candidate, source_text)
    if base_reasons:
        return [], tuple(base_reasons)

    sentence = candidate["supporting_sentence"]
    original = candidate["original_entity"]
    start, end = candidate["original_span"]
    effective_type = candidate["effective_type"]
    masked = _mask_sentence(sentence, (start, end))
    target_relation = relation_signature(
        dataset=candidate["dataset"],
        source_key=candidate["source_key"],
        effective_type=effective_type,
        masked_sentence=masked,
    )
    inventory = _filler_inventory(candidate)
    matching = [item for item in inventory if item["relation_signature"] == target_relation]
    matching_propositions = {
        (item["proposition_raw_start"], item["proposition_raw_end"])
        for item in matching
    }
    matching_original = {
        normalize_text(item["surface"])
        for item in matching
        if normalize_text(item["surface"]) == normalize_text(original)
    }
    competing = {
        normalize_text(item["surface"])
        for item in matching
        if item["effective_type"] == effective_type
        and normalize_text(item["surface"]) != normalize_text(original)
    }
    recovery_reasons: list[str] = []
    if len(matching_propositions) != 1:
        recovery_reasons.append("matching_supporting_proposition_count")
    if matching_original != {normalize_text(original)}:
        recovery_reasons.append("original_relation_not_uniquely_recoverable")
    if competing:
        recovery_reasons.append("competing_relation_filler")
    original_occurrences = bounded_occurrence_count(source_text, original)
    if original_occurrences < 1:
        recovery_reasons.append("original_entity_absent")

    entity_spans = candidate["entity_spans"]
    if not isinstance(entity_spans, list):
        raise ValueError("candidate_entity_spans_invalid")
    anchor_text = _remove_entity_spans(sentence, entity_spans)
    distinct_tokens = sorted(set(content_tokens(anchor_text)))
    source_specific = [
        token for token in distinct_tokens if token in token_df and token_df[token] * 100 <= source_count
    ]
    if len(distinct_tokens) < 4:
        recovery_reasons.append("insufficient_content_tokens")
    if len(source_specific) < 1:
        recovery_reasons.append("source_specific_anchor_missing")
    if recovery_reasons:
        return [], tuple(recovery_reasons)

    idf_sum = sum(math.log((source_count + 1) / (token_df[token] + 1)) for token in source_specific)
    rounded_idf = float(Decimal(str(idf_sum)).quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN))
    relation_cue_count = len(list(RELATION_CUE_RE.finditer(sentence)))
    sentence_occurrences = _literal_occurrence_count(source_text, sentence.strip())
    same_type_fillers = {
        normalize_text(item["surface"])
        for item in inventory
        if item["effective_type"] == effective_type
    }
    cue = next(RELATION_CUE_RE.finditer(masked))
    explicit_arguments = len(set(content_tokens(masked[: cue.start()]))) + len(
        set(content_tokens(masked[masked.index(ENTITY_SLOT) + len(ENTITY_SLOT) :]))
    )
    unresolved_count = len(list(UNRESOLVED_REFERENCE_RE.finditer(sentence)))
    fact_id = fact_signature(
        dataset=candidate["dataset"], source_key=candidate["source_key"], sentence=sentence
    )

    raw_pool = candidate["counterfactual_pool"]
    if not isinstance(raw_pool, list) or not all(isinstance(value, str) for value in raw_pool):
        raise ValueError("candidate_counterfactual_pool_invalid")
    deduplicated: dict[str, tuple[int, str]] = {}
    for index, replacement in enumerate(raw_pool):
        normalized = normalize_text(replacement)
        if not normalized:
            continue
        prior = deduplicated.get(normalized)
        item = (index, replacement)
        if prior is None or item < prior:
            deduplicated[normalized] = item

    pairs: list[dict[str, Any]] = []
    for _, replacement in deduplicated.values():
        normalized_replacement = normalize_text(replacement)
        if normalized_replacement == normalize_text(original):
            continue
        if bounded_occurrence_count(source_text, replacement) > 0:
            continue
        if GENERIC_ROLE_RE.fullmatch(normalized_replacement):
            continue
        if not machine_format_compatible(original, replacement, effective_type):
            continue
        if not _article_compatible(sentence[:start], replacement):
            continue
        counterfactual_claim = f"{sentence[:start]}{replacement}{sentence[end:]}"
        if not _balanced_delimiters(counterfactual_claim):
            continue
        counterfactual_id = _counterfactual_identity(candidate, replacement)
        pair_id = _pair_identity(
            fact_id=fact_id,
            original=original,
            replacement=replacement,
            counterfactual_id=counterfactual_id,
        )
        rank_tuple = [
            -relation_cue_count,
            sentence_occurrences,
            -int(sentence.rstrip().endswith((".", ";"))),
            -min(40, len(distinct_tokens)),
            original_occurrences,
            len(same_type_fillers),
            -len(source_specific),
            -rounded_idf,
            -len(distinct_tokens),
            len(competing),
            len({normalize_text(item["surface"]) for item in matching}),
            -explicit_arguments,
            unresolved_count,
            fact_id,
            start,
            normalized_replacement,
            pair_id,
        ]
        pairs.append(
            {
                "kind": "v23_pair_candidate",
                "specification_version": SPECIFICATION_VERSION,
                "dataset": candidate["dataset"],
                "source_key": candidate["source_key"],
                "source_hash": text_sha256(source_text),
                "normalized_text_hash": normalized_text_sha256(source_text),
                "source_order_rank": int(candidate["source_order_rank"]),
                "pair_id": pair_id,
                "counterfactual_id": counterfactual_id,
                "fact_signature": fact_id,
                "relation_signature": target_relation,
                "supporting_sentence": sentence,
                "original_span": [start, end],
                "original_entity": original,
                "counterfactual_entity": replacement,
                "effective_type": effective_type,
                "semantic_subtype": candidate["semantic_subtype"],
                "true_claim": sentence,
                "counterfactual_claim": counterfactual_claim,
                "rank_tuple": rank_tuple,
                "external_calls_performed": 0,
            }
        )
    pairs.sort(
        key=lambda item: (
            item["counterfactual_id"],
            normalize_text(item["counterfactual_entity"]),
        )
    )
    return pairs[:3], () if pairs else ("no_valid_counterfactual",)


def select_top_three(pair_candidates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Apply the frozen 17-field ordering and stable greedy diversity rule."""

    rows = [dict(row) for row in pair_candidates]
    for row in rows:
        reject_forbidden_selection_fields(row)
        rank = row.get("rank_tuple")
        if not isinstance(rank, list) or len(rank) != 17:
            raise ValueError("rank_tuple_invalid")
    rows.sort(key=lambda row: tuple(row["rank_tuple"]))
    selected: list[dict[str, Any]] = []
    seen_facts: set[str] = set()
    entity_counts: Counter[str] = Counter()
    for row in rows:
        fact_id = str(row["fact_signature"])
        entity = normalize_text(str(row["original_entity"]))
        if fact_id in seen_facts or entity_counts[entity] >= 2:
            continue
        accepted = dict(row)
        accepted["kind"] = "v23_selected_pair"
        accepted["pair_order"] = len(selected)
        accepted.pop("external_calls_performed", None)
        accepted.pop("counterfactual_id", None)
        selected.append(accepted)
        seen_facts.add(fact_id)
        entity_counts[entity] += 1
        if len(selected) == 3:
            return selected
    return []


def aggregate_document_frequency(source_texts: Iterable[str]) -> tuple[dict[str, int], int]:
    """Compute dataset-level boolean token DF without retaining source mappings."""

    counts: Counter[str] = Counter()
    source_count = 0
    for text in source_texts:
        if not isinstance(text, str) or not text:
            raise ValueError("aggregate_df_source_invalid")
        counts.update(set(content_tokens(text)))
        source_count += 1
    return dict(sorted(counts.items())), source_count


def load_replacement_policy(path: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Load the frozen subtype parent mapping and exact replacement pools."""

    policy = load_yaml(path)
    raw_types = policy.get("types")
    raw_pools = policy.get("semantic_replacement_candidates")
    if not isinstance(raw_types, Mapping) or not isinstance(raw_pools, Mapping):
        raise RuntimeError("replacement_policy_schema_invalid")
    parent_by_subtype: dict[str, str] = {}
    for parent, raw in raw_types.items():
        if str(parent) not in FORMAL_TYPES or not isinstance(raw, Mapping):
            continue
        subtypes = raw.get("allowed_subtypes")
        if not isinstance(subtypes, list) or not all(isinstance(item, str) for item in subtypes):
            raise RuntimeError(f"replacement_policy_subtypes_invalid:{parent}")
        for subtype in subtypes:
            if subtype in parent_by_subtype:
                raise RuntimeError(f"replacement_policy_duplicate_subtype:{subtype}")
            parent_by_subtype[subtype] = str(parent)
    pools: dict[str, list[str]] = {}
    for subtype, raw_pool in raw_pools.items():
        if subtype not in parent_by_subtype:
            continue
        if not isinstance(raw_pool, list) or not all(isinstance(item, str) for item in raw_pool):
            raise RuntimeError(f"replacement_policy_pool_invalid:{subtype}")
        if not raw_pool:
            raise RuntimeError(f"replacement_policy_pool_empty:{subtype}")
        pools[str(subtype)] = list(raw_pool)
    if set(parent_by_subtype) != set(pools):
        raise RuntimeError("replacement_policy_pool_coverage_invalid")
    return parent_by_subtype, pools


def _prediction_row(value: Mapping[str, Any], *, text: str) -> dict[str, Any] | None:
    allowed = {"label", "start", "end", "score", "text"}
    if not set(value).issubset(allowed):
        raise ValueError(f"internal_model_prediction_unknown_fields:{sorted(set(value) - allowed)}")
    label = str(value.get("label") or "").upper()
    start = value.get("start")
    end = value.get("end")
    score = value.get("score")
    if label not in FORMAL_TYPES:
        return None
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or not isinstance(score, (int, float))
        or isinstance(score, bool)
    ):
        raise ValueError("internal_model_prediction_type_invalid")
    if score < 0.65:
        return None
    if start < 0 or end <= start or end > len(text):
        raise ValueError("internal_model_prediction_span_invalid")
    surface = text[start:end]
    if "text" in value and value["text"] != surface:
        raise ValueError("internal_model_prediction_text_drift")
    return {
        "label": label,
        "start": start,
        "end": end,
        "score": float(score),
        "text": surface,
    }


def _emit_proposition_entities(
    proposition: str,
    *,
    extractor: EntityExtractor,
    model_predictions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Emit all pre-score rule/model P0 candidates in the frozen traversal order."""

    rule_rows: list[dict[str, Any]] = []
    for registry_index, spec in enumerate(extractor.pattern_registry):
        if spec.entity_type not in FORMAL_TYPES:
            continue
        for match in spec.pattern.finditer(proposition):
            raw_value = match.group(0)
            leading = len(raw_value) - len(raw_value.lstrip())
            surface = raw_value.strip()
            start = match.start() + leading
            end = start + len(surface)
            if spec.entity_type == "ORG" and surface.endswith("."):
                surface = surface[:-1]
                end -= 1
            if not surface or not extractor._valid_surface(surface, spec.entity_type):
                continue
            rule_rows.append(
                {
                    "surface": surface,
                    "declared_type": spec.entity_type,
                    "start": start,
                    "end": end,
                    "source_priority": 0,
                    "emitter_registry_index": registry_index,
                    "model_score": 0.0,
                }
            )

    filtered_predictions: list[dict[str, Any]] = []
    for prediction in model_predictions:
        normalized = _prediction_row(prediction, text=proposition)
        if normalized is not None:
            filtered_predictions.append(normalized)
    filtered_predictions.sort(
        key=lambda item: (
            -item["score"],
            item["label"],
            item["start"],
            item["end"],
            item["text"],
        )
    )
    model_rows = [
        {
            "surface": item["text"],
            "declared_type": item["label"],
            "start": item["start"],
            "end": item["end"],
            "source_priority": 1,
            "emitter_registry_index": 2_147_483_647,
            "model_score": item["score"],
        }
        for item in filtered_predictions
    ]
    predictions_by_role = {"gliner2_base": filtered_predictions}
    routed: list[dict[str, Any]] = []
    for item in [*rule_rows, *model_rows]:
        route = route_effective_type(
            {
                "text": item["surface"],
                "type": item["declared_type"],
                "start": item["start"],
                "end": item["end"],
                "supporting_sentence": proposition,
            },
            predictions_by_role,
            required_roles=["gliner2_base"],
            minimum_votes=1,
            overlap_threshold=0.80,
            minimum_prediction_score=0.65,
        )
        if route.effective_type not in FORMAL_TYPES:
            continue
        subtype = semantic_subtype(item["surface"], route.effective_type)
        if not subtype:
            continue
        routed.append(
            {
                **item,
                "effective_type": route.effective_type,
                "semantic_subtype": subtype,
            }
        )

    survivors: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in routed:
        key = (
            item["start"],
            item["end"],
            normalize_text(item["surface"]),
            item["effective_type"],
            item["semantic_subtype"],
        )
        survivor_key = (
            item["source_priority"],
            item["emitter_registry_index"],
            -item["model_score"],
            item["declared_type"],
            item["surface"].encode("utf-8"),
        )
        prior = survivors.get(key)
        if prior is None or survivor_key < prior["survivor_key"]:
            survivors[key] = {**item, "survivor_key": survivor_key}
    output = [dict(item) for item in survivors.values()]
    for item in output:
        item.pop("survivor_key", None)
    output.sort(
        key=lambda item: (
            item["start"],
            item["end"],
            item["source_priority"],
            item["emitter_registry_index"],
            -item["model_score"],
            item["declared_type"],
            item["surface"],
        )
    )
    return output


def fresh_extract_candidates(
    source: Mapping[str, Any],
    *,
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]],
    entity_policy_path: str,
    extractor: EntityExtractor | None = None,
) -> list[dict[str, Any]]:
    """Freshly reconstruct v23 candidates without accepting serialized model outputs."""

    validated = validate_selector_source_input(source)
    extractor = extractor or EntityExtractor(enable_ner=False)
    parent_by_subtype, replacement_pools = load_replacement_policy(entity_policy_path)
    dataset = validated["dataset"]
    source_key = validated["source_key"]

    inventory: list[dict[str, Any]] = []
    for proposition in segment_propositions(validated["full_text"]):
        predictions = model_emitter(proposition["text"], dataset)
        for item in _emit_proposition_entities(
            proposition["text"], extractor=extractor, model_predictions=predictions
        ):
            masked = _mask_sentence(proposition["text"], (item["start"], item["end"]))
            inventory.append(
                {
                    "surface": item["surface"],
                    "effective_type": item["effective_type"],
                    "relation_signature": relation_signature(
                        dataset=dataset,
                        source_key=source_key,
                        effective_type=item["effective_type"],
                        masked_sentence=masked,
                    ),
                    "proposition_raw_start": proposition["start"],
                    "proposition_raw_end": proposition["end"],
                    "filler_span": [item["start"], item["end"]],
                }
            )
    inventory_by_key = {
        (
            normalize_text(item["surface"]),
            item["effective_type"],
            item["relation_signature"],
            item["proposition_raw_start"],
            item["proposition_raw_end"],
            tuple(item["filler_span"]),
        ): item
        for item in inventory
    }
    frozen_inventory = [inventory_by_key[key] for key in sorted(inventory_by_key)]

    candidates: list[dict[str, Any]] = []
    for chunk in sorted(validated["chunks"], key=lambda item: item["chunk_rank"]):
        chunk_text = chunk["row"]["text"]
        for proposition in segment_propositions(chunk_text):
            predictions = model_emitter(proposition["text"], dataset)
            emitted = _emit_proposition_entities(
                proposition["text"], extractor=extractor, model_predictions=predictions
            )
            entity_spans = [[item["start"], item["end"]] for item in emitted]
            for item in emitted:
                subtype = item["semantic_subtype"]
                if parent_by_subtype.get(subtype) != item["effective_type"]:
                    continue
                candidates.append(
                    {
                        "dataset": dataset,
                        "source_key": source_key,
                        "source_order_rank": validated["source_order_rank"],
                        "supporting_sentence": proposition["text"],
                        "original_entity": item["surface"],
                        "original_span": [item["start"], item["end"]],
                        "effective_type": item["effective_type"],
                        "semantic_subtype": subtype,
                        "entity_spans": entity_spans,
                        "filler_inventory": frozen_inventory,
                        "counterfactual_pool": list(replacement_pools[subtype]),
                        "chunk_rank": chunk["chunk_rank"],
                        "proposition_raw_start": proposition["start"],
                        "emitter_registry_index": item["emitter_registry_index"],
                        "source_priority": item["source_priority"],
                        "model_score": item["model_score"],
                    }
                )
    deduplicated: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in candidates:
        sentence_hash = text_sha256(item["supporting_sentence"].strip())
        key = (
            sentence_hash,
            tuple(item["original_span"]),
            normalize_text(item["original_entity"]),
            item["effective_type"],
            item["semantic_subtype"],
        )
        survivor_key = (
            item["source_priority"],
            item["emitter_registry_index"],
            -item["model_score"],
            item["effective_type"],
            item["original_entity"].encode("utf-8"),
        )
        prior = deduplicated.get(key)
        if prior is None or survivor_key < prior["survivor_key"]:
            deduplicated[key] = {**item, "survivor_key": survivor_key}
    output = [dict(item) for item in deduplicated.values()]
    for item in output:
        item.pop("survivor_key", None)
    output.sort(
        key=lambda item: (
            item["chunk_rank"],
            item["proposition_raw_start"],
            item["emitter_registry_index"],
            item["original_span"],
            item["original_entity"],
        )
    )
    return output
