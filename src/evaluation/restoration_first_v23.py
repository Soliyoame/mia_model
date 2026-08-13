"""Deterministic downstream contracts and source-level metrics for PCV-MIA v23."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..attack.restoration_first_v23 import (
    RELATION_CUE_RE,
    UNRESOLVED_REFERENCE_RE,
    canonical_sha256,
    content_tokens,
    normalize_text,
    text_sha256,
)
from ..utils.hash import sha256_file


BACKEND_ORDER = ("dense", "bm25", "hybrid")
DATASET_ORDER = ("edgar", "enron", "pubmed")
GROUP_ORDER = ("KB_Member", "True_Non_Member")
QUERY_POLARITIES = ("Q_plus", "Q_minus")
STANCE_VALUES = frozenset({"supported", "contradicted", "insufficient"})
BM25_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def strict_json_object(value: str | bytes) -> dict[str, Any]:
    """Parse one complete RFC8259 object and reject duplicate keys/nonfinite values."""

    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid_utf8") from exc
    elif isinstance(value, str):
        text = value
    else:
        raise ValueError("response_not_text")

    def reject_constant(_: str) -> None:
        raise ValueError("nonfinite_json_value")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, item in pairs:
            if key in output:
                raise ValueError(f"duplicate_json_key:{key}")
            output[key] = item
        return output

    try:
        parsed = json.loads(
            text.strip(),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json_object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("json_root_not_object")
    return parsed


def parse_response(value: str | bytes | None) -> dict[str, Any]:
    if value is None:
        return {"parse_status": "missing", "stance": None, "correction_entity": None}
    try:
        parsed = strict_json_object(value)
    except ValueError:
        return {"parse_status": "invalid", "stance": None, "correction_entity": None}
    if set(parsed) != {"stance", "correction_entity"}:
        return {"parse_status": "invalid", "stance": None, "correction_entity": None}
    stance = parsed["stance"]
    correction = parsed["correction_entity"]
    if not isinstance(stance, str) or stance not in STANCE_VALUES:
        return {"parse_status": "invalid", "stance": None, "correction_entity": None}
    if stance in {"supported", "insufficient"}:
        if correction is not None:
            return {"parse_status": "invalid", "stance": None, "correction_entity": None}
    elif not isinstance(correction, str) or not normalize_text(correction):
        return {"parse_status": "invalid", "stance": None, "correction_entity": None}
    return {"parse_status": "parsed", "stance": stance, "correction_entity": correction}


def frozen_cell_score(
    *,
    query_polarity: str,
    parsed: Mapping[str, Any],
    original_entity: str,
) -> float:
    if query_polarity not in QUERY_POLARITIES:
        raise ValueError("query_polarity_invalid")
    if parsed.get("parse_status") != "parsed":
        return -0.5
    stance = parsed.get("stance")
    if query_polarity == "Q_plus":
        return {"supported": 1.0, "contradicted": -1.0, "insufficient": -0.5}.get(
            str(stance), -0.5
        )
    if stance == "contradicted":
        return (
            1.0
            if normalize_text(str(parsed.get("correction_entity") or ""))
            == normalize_text(original_entity)
            else 0.5
        )
    if stance == "supported":
        return -1.0
    return -0.5


def validate_query_output(
    value: str | bytes,
    *,
    pair_id: str,
    query_polarity: str,
    claim: str,
    allowed_entity_surfaces: Iterable[str],
    query_entity_surfaces: Iterable[str],
) -> dict[str, Any]:
    parsed = strict_json_object(value)
    if set(parsed) != {"kind", "pair_id", "query_polarity", "query_text"}:
        raise ValueError("query_output_schema_invalid")
    if parsed["kind"] != "v23_frozen_query":
        raise ValueError("query_output_kind_invalid")
    if parsed["pair_id"] != pair_id or parsed["query_polarity"] != query_polarity:
        raise ValueError("query_output_identity_mismatch")
    query = parsed["query_text"]
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query_text_empty")
    if query.strip().count("?") != 1 or not query.strip().endswith("?"):
        raise ValueError("query_question_mark_invalid")
    if "ENTITY_SLOT" in query:
        raise ValueError("query_entity_slot_leak")
    cue = RELATION_CUE_RE.search(query)
    if cue is None:
        raise ValueError("query_relation_cue_missing")
    if UNRESOLVED_REFERENCE_RE.search(query):
        raise ValueError("query_unresolved_reference")
    claim_tokens = set(content_tokens(claim))
    if not claim_tokens.intersection(content_tokens(query[: cue.start()])):
        raise ValueError("query_explicit_subject_missing")
    allowed = {normalize_text(item) for item in allowed_entity_surfaces}
    emitted = {normalize_text(item) for item in query_entity_surfaces}
    if emitted - allowed:
        raise ValueError("query_new_entity_surface")
    return dict(parsed)


def build_source_scores(
    parsed_rows: Iterable[Mapping[str, Any]],
    *,
    release_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Require six cells per backend/source and average exactly three pair PVS values."""

    release_bindings: dict[tuple[str, str, str, int, str], str] = {}
    for row in release_rows:
        key = (
            str(row.get("dataset")),
            str(row.get("group")),
            str(row.get("source_key")),
            int(row.get("pair_order", -1)),
            str(row.get("pair_id")),
        )
        if key in release_bindings:
            raise ValueError("release_row_duplicate_pair_identity")
        original = row.get("original_entity")
        if (
            key[0] not in DATASET_ORDER
            or key[1] not in GROUP_ORDER
            or key[3] not in {0, 1, 2}
            or not isinstance(original, str)
            or not original
        ):
            raise ValueError("release_row_identity_invalid")
        release_bindings[key] = original

    grouped: dict[tuple[str, str, str, str, int], dict[str, Mapping[str, Any]]] = defaultdict(dict)
    pair_ids: dict[tuple[str, str, str, str, int], str] = {}
    split_indexes: dict[tuple[str, str, str, str], int] = {}
    for row in parsed_rows:
        dataset = str(row.get("dataset"))
        backend = str(row.get("backend"))
        group = str(row.get("group"))
        source_key = str(row.get("source_key"))
        pair_order = row.get("pair_order")
        polarity = str(row.get("query_polarity"))
        if dataset not in DATASET_ORDER or backend not in BACKEND_ORDER or group not in GROUP_ORDER:
            raise ValueError("parsed_row_scope_invalid")
        if isinstance(pair_order, bool) or pair_order not in {0, 1, 2} or polarity not in QUERY_POLARITIES:
            raise ValueError("parsed_row_pair_cell_invalid")
        pair_id = str(row.get("pair_id"))
        release_key = (dataset, group, source_key, int(pair_order), pair_id)
        if release_key not in release_bindings:
            raise ValueError("parsed_row_pair_not_bound_to_release")
        key = (backend, dataset, group, source_key, int(pair_order))
        if polarity in grouped[key]:
            raise ValueError("parsed_row_duplicate_cell")
        grouped[key][polarity] = row
        pair_ids[key] = pair_id
        split_key = (backend, dataset, group, source_key)
        split_index = row.get("split_index")
        if isinstance(split_index, bool) or not isinstance(split_index, int):
            raise ValueError("parsed_row_split_index_invalid")
        if split_key in split_indexes and split_indexes[split_key] != split_index:
            raise ValueError("parsed_row_split_index_drift")
        split_indexes[split_key] = split_index

    sources: dict[tuple[str, str, str, str], list[tuple[int, str, float]]] = defaultdict(list)
    for key, cells in grouped.items():
        if set(cells) != set(QUERY_POLARITIES):
            raise ValueError("parsed_row_missing_cell")
        plus = cells["Q_plus"]
        minus = cells["Q_minus"]
        backend, dataset, group, source_key, pair_order = key
        bound_pair_id = pair_ids[key]
        if str(plus.get("pair_id")) != bound_pair_id or str(minus.get("pair_id")) != bound_pair_id:
            raise ValueError("parsed_row_pair_id_drift_within_pair")
        original_entity = release_bindings[
            (dataset, group, source_key, pair_order, bound_pair_id)
        ]
        score = frozen_cell_score(
            query_polarity="Q_plus",
            parsed=plus,
            original_entity=original_entity,
        ) + frozen_cell_score(
            query_polarity="Q_minus",
            parsed=minus,
            original_entity=original_entity,
        )
        sources[(backend, dataset, group, source_key)].append(
            (pair_order, bound_pair_id, score)
        )

    output: list[dict[str, Any]] = []
    for source_key, pairs in sources.items():
        pairs.sort(key=lambda item: item[0])
        if [item[0] for item in pairs] != [0, 1, 2]:
            raise ValueError("source_pair_orders_incomplete")
        backend, dataset, group, key = source_key
        pair_scores = [item[2] for item in pairs]
        output.append(
            {
                "kind": "v23_source_score",
                "dataset": dataset,
                "backend": backend,
                "group": group,
                "source_key": key,
                "split_index": split_indexes[source_key],
                "ordered_pair_ids": [item[1] for item in pairs],
                "pair_pvs": pair_scores,
                "source_pvs": sum(pair_scores) / 3.0,
            }
        )
    output.sort(
        key=lambda row: (
            BACKEND_ORDER.index(row["backend"]),
            DATASET_ORDER.index(row["dataset"]),
            GROUP_ORDER.index(row["group"]),
            row["source_key"],
        )
    )
    return output


def tie_aware_auc(positive_scores: Sequence[float], negative_scores: Sequence[float]) -> float:
    if not positive_scores or not negative_scores:
        raise ValueError("auc_requires_both_classes")
    combined = sorted(
        [(float(score), 1) for score in positive_scores]
        + [(float(score), 0) for score in negative_scores],
        key=lambda item: item[0],
    )
    rank_sum_positive = 0.0
    index = 0
    while index < len(combined):
        end = index + 1
        while end < len(combined) and combined[end][0] == combined[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        rank_sum_positive += average_rank * sum(
            label for _, label in combined[index:end]
        )
        index = end
    positive_count = len(positive_scores)
    negative_count = len(negative_scores)
    mann_whitney_u = (
        rank_sum_positive - positive_count * (positive_count + 1) / 2.0
    )
    return mann_whitney_u / (positive_count * negative_count)


def empirical_tpr_at_fpr(
    positive_scores: Sequence[float], negative_scores: Sequence[float], target_fpr: float
) -> dict[str, float]:
    if not positive_scores or not negative_scores or not 0.0 <= target_fpr <= 1.0:
        raise ValueError("low_fpr_input_invalid")
    thresholds = sorted(set([math.inf, *positive_scores, *negative_scores, -math.inf]), reverse=True)
    feasible: list[tuple[float, float, float]] = []
    for threshold in thresholds:
        fpr = sum(score >= threshold for score in negative_scores) / len(negative_scores)
        tpr = sum(score >= threshold for score in positive_scores) / len(positive_scores)
        if fpr <= target_fpr:
            feasible.append((tpr, threshold, fpr))
    best = max(feasible, key=lambda item: (item[0], item[1]))
    return {"tpr": best[0], "threshold": best[1], "fpr": best[2]}


def bootstrap_index_tensor(
    *, repetitions: int = 10_000, cells: int = 6, source_count: int = 1_000
) -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy_required_for_v23_bootstrap") from exc
    generator = np.random.Generator(np.random.PCG64(42))
    return generator.integers(
        0,
        source_count,
        size=(repetitions, cells, source_count),
        dtype=np.dtype("<i8"),
    )


def type7_quantile(values: Sequence[float], probability: float) -> float:
    if not values or not 0.0 <= probability <= 1.0:
        raise ValueError("quantile_input_invalid")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def bm25_scores(
    documents: Sequence[str],
    query: str,
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Compute BM25 while accumulating sorted unique query terms deterministically."""

    tokenized = [BM25_TOKEN_RE.findall(document.casefold()) for document in documents]
    query_terms = sorted(set(BM25_TOKEN_RE.findall(query.casefold())))
    document_count = len(tokenized)
    if document_count == 0:
        return []
    average_length = max(sum(map(len, tokenized)) / document_count, 1e-12)
    frequencies = Counter(term for tokens in tokenized for term in set(tokens))
    scores = [0.0] * document_count
    for term in query_terms:
        document_frequency = frequencies.get(term, 0)
        if document_frequency == 0:
            continue
        idf = math.log(1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
        for index, tokens in enumerate(tokenized):
            term_frequency = tokens.count(term)
            if term_frequency == 0:
                continue
            denominator = term_frequency + k1 * (
                1.0 - b + b * len(tokens) / average_length
            )
            scores[index] += idf * term_frequency * (k1 + 1.0) / denominator
    return scores


def validate_artifact_hash_chain(
    manifest: Mapping[str, Any],
    *,
    project_root: str | Path = ".",
    path_hash_fields: Sequence[tuple[str, str]],
) -> None:
    """Require every declared data path to match its complete-file SHA-256 binding."""

    root = Path(project_root).resolve()
    for path_field, hash_field in path_hash_fields:
        path = manifest.get(path_field)
        expected = manifest.get(hash_field)
        if not isinstance(path, str) or not isinstance(expected, str):
            raise RuntimeError(f"artifact_hash_chain_field_missing:{path_field}:{hash_field}")
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = root / resolved
        if not resolved.is_file() or sha256_file(resolved) != expected:
            raise RuntimeError(f"artifact_hash_chain_drift:{path_field}")


def response_row(
    *,
    raw_response: str | bytes | None,
    query_polarity: str,
    original_entity: str,
) -> dict[str, Any]:
    parsed = parse_response(raw_response)
    return {
        **parsed,
        "raw_response_sha256": None
        if raw_response is None
        else text_sha256(raw_response.decode("utf-8") if isinstance(raw_response, bytes) else raw_response),
        "frozen_cell_score": frozen_cell_score(
            query_polarity=query_polarity,
            parsed=parsed,
            original_entity=original_entity,
        ),
    }
