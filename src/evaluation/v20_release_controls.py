"""Fail-closed release controls for the PCV-MIA v20 experiment."""

from __future__ import annotations

import hashlib
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import read_json, read_jsonl, write_json, write_jsonl


DATASETS = ("edgar", "enron", "pubmed")
GROUP_FILES = {
    "KB_Member": "kb_member.jsonl",
    "True_Non_Member": "true_non_member.jsonl",
    "Reserve": "reserve.jsonl",
}
MAIN_CELLS = ("dense", "bm25", "hybrid", "none")


def source_key(row: dict[str, Any]) -> str:
    """Return the frozen source identity used across v20 artifacts."""

    return str(
        row.get("source_key")
        or (row.get("metadata") or {}).get("source_key")
        or row.get("source_id")
        or row.get("doc_id")
        or ""
    )


def aggregate_split_sources(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate a split JSONL's many document rows into frozen sources."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = source_key(row)
        if not key:
            raise RuntimeError("Split row is missing source identity")
        grouped[key].append(row)
    sources: list[dict[str, Any]] = []
    for key, source_rows in sorted(grouped.items()):
        groups = {str(row.get("group")) for row in source_rows}
        if len(groups) != 1:
            raise RuntimeError(f"Source crosses groups inside split: {key}")
        ordered = sorted(
            source_rows,
            key=lambda row: (
                str(row.get("doc_id") or ""),
                str(row.get("sample_id") or ""),
            ),
        )
        texts: list[str] = []
        seen_hashes: set[str] = set()
        for row in ordered:
            text = str(row.get("text") or "").strip()
            text_hash = str(row.get("text_hash") or sha256_text(text))
            if text and text_hash not in seen_hashes:
                texts.append(text)
                seen_hashes.add(text_hash)
        combined = "\n\n".join(texts)
        if not combined:
            raise RuntimeError(f"Source has no text: {key}")
        first = ordered[0]
        sources.append(
            {
                "dataset": first.get("dataset"),
                "group": next(iter(groups)),
                "source_key": key,
                "source_id": first.get("source_id") or key,
                "doc_id": first.get("doc_id") or first.get("source_id") or key,
                "record_count": len(ordered),
                "text": combined,
                "text_hash": sha256_text(combined),
                "record_text_hashes_hash": sha256_obj(sorted(seen_hashes)),
            }
        )
    return sources


def build_reserve_role_manifest(
    *,
    dataset: str,
    reserve_path: str | Path,
    pilot_budget_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Freeze the 5 Pilot Reserve and remaining 245 conformal sources."""

    reserve_rows = aggregate_split_sources(read_jsonl(reserve_path))
    reserve_keys = [source_key(row) for row in reserve_rows]
    if len(reserve_keys) != 250 or len(set(reserve_keys)) != 250:
        raise RuntimeError(
            f"{dataset}: expected 250 unique Reserve sources, got "
            f"{len(reserve_keys)}/{len(set(reserve_keys))}"
        )
    budget = read_json(pilot_budget_path)
    pilot_keys = [
        str(value)
        for value in (budget.get("selected_source_keys") or {}).get("Reserve", [])
    ]
    if len(pilot_keys) != 5 or len(set(pilot_keys)) != 5:
        raise RuntimeError(f"{dataset}: Pilot must freeze exactly 5 Reserve sources")
    unknown = sorted(set(pilot_keys) - set(reserve_keys))
    if unknown:
        raise RuntimeError(f"{dataset}: Pilot Reserve not in split: {unknown[:3]}")
    pilot_set = set(pilot_keys)
    calibration_keys = sorted(key for key in reserve_keys if key not in pilot_set)
    if len(calibration_keys) != 245:
        raise RuntimeError(f"{dataset}: conformal Reserve count is not 245")
    rows = [
        {
            "dataset": dataset,
            "source_key": key,
            "reserve_role": (
                "pilot_diagnostic" if key in pilot_set else "conformal_calibration"
            ),
        }
        for key in sorted(reserve_keys)
    ]
    manifest = {
        "protocol_version": "pcv-mia-v20",
        "dataset": dataset,
        "reserve_role": "retriever_dev_and_conformal",
        "reserve_count": 250,
        "pilot_diagnostic_count": 5,
        "conformal_calibration_count": 245,
        "pilot_reserve_excluded_from_calibration": True,
        "calibration_scope": "post_retriever_frozen_nonmember_calibration",
        "retriever_selection_used_reserve_recall": True,
        "retriever_selection_used_attack_scores": False,
        "reserve_split_hash": sha256_file(reserve_path),
        "pilot_budget_hash": sha256_file(pilot_budget_path),
        "pilot_source_keys_hash": sha256_obj(sorted(pilot_keys)),
        "calibration_source_keys_hash": sha256_obj(calibration_keys),
        "roles_hash": sha256_obj(rows),
        "roles": rows,
    }
    write_json(manifest, output_path)
    return manifest


def calibration_source_keys(role_manifest_path: str | Path) -> set[str]:
    """Load and validate the frozen set of 245 calibration source IDs."""

    manifest = read_json(role_manifest_path)
    rows = list(manifest.get("roles") or [])
    if sha256_obj(rows) != str(manifest.get("roles_hash") or ""):
        raise RuntimeError("Reserve role manifest hash mismatch")
    keys = {
        str(row["source_key"])
        for row in rows
        if row.get("reserve_role") == "conformal_calibration"
    }
    if len(keys) != 245:
        raise RuntimeError(f"Expected 245 conformal Reserve sources, got {len(keys)}")
    pilot = {
        str(row["source_key"])
        for row in rows
        if row.get("reserve_role") == "pilot_diagnostic"
    }
    if len(pilot) != 5 or keys & pilot:
        raise RuntimeError("Pilot/calibration Reserve roles are not a 5/245 partition")
    return keys


def build_ground_truth_source_store(
    *,
    dataset: str,
    split_dir: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Build a read-only source store covering all three canonical groups."""

    root = Path(split_dir)
    rows: list[dict[str, Any]] = []
    input_hashes: dict[str, str] = {}
    for group, filename in GROUP_FILES.items():
        path = root / filename
        input_hashes[group] = sha256_file(path)
        for row in aggregate_split_sources(read_jsonl(path)):
            if str(row.get("group")) != group:
                raise RuntimeError(f"{dataset}: wrong group in {path}: {row.get('group')}")
            key = source_key(row)
            if not key or not str(row.get("text") or "").strip():
                raise RuntimeError(f"{dataset}: source without identity/text in {path}")
            rows.append(
                {
                    "dataset": dataset,
                    "group": group,
                    "source_key": key,
                    "source_id": row.get("source_id") or row.get("doc_id"),
                    "doc_id": row.get("doc_id"),
                    "text": row.get("text"),
                    "text_hash": row.get("text_hash")
                    or sha256_text(str(row.get("text") or "")),
                }
            )
    counts = Counter(str(row["group"]) for row in rows)
    if counts != Counter({"KB_Member": 500, "True_Non_Member": 500, "Reserve": 250}):
        raise RuntimeError(f"{dataset}: invalid source counts: {dict(counts)}")
    keys = [str(row["source_key"]) for row in rows]
    if len(set(keys)) != 1250:
        raise RuntimeError(f"{dataset}: source identities are not unique")
    ordered = sorted(rows, key=lambda row: str(row["source_key"]))
    write_jsonl(ordered, output_path)
    manifest = {
        "protocol_version": "pcv-mia-v20",
        "dataset": dataset,
        "status": "read_only_ground_truth_source_store",
        "group_counts": dict(sorted(counts.items())),
        "source_count": len(ordered),
        "input_hashes": input_hashes,
        "source_keys_hash": sha256_obj(sorted(keys)),
        "store_hash": sha256_file(output_path),
    }
    write_json(manifest, Path(output_path).with_suffix(".manifest.json"))
    return manifest


def _normalize_source_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def five_word_shingles(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _normalize_source_text(text))
    if len(words) < 5:
        return {" ".join(words)} if words else set()
    return {" ".join(words[index : index + 5]) for index in range(len(words) - 4)}


def minhash_signature(shingles: set[str], *, permutations: int = 64) -> tuple[int, ...]:
    """Return a deterministic bottom-k MinHash sketch."""

    if not shingles:
        return tuple(0 for _ in range(permutations))
    values = sorted(
        int.from_bytes(
            hashlib.sha256(shingle.encode("utf-8")).digest()[:8],
            "big",
        )
        for shingle in shingles
    )[:permutations]
    if len(values) < permutations:
        values.extend([values[-1]] * (permutations - len(values)))
    return tuple(values)


def near_duplicate_audit(
    rows: Iterable[dict[str, Any]],
    *,
    jaccard_threshold: float = 0.85,
    permutations: int = 64,
    bands: int = 8,
) -> dict[str, Any]:
    """Audit exact normalized hashes and high-Jaccard MinHash candidates."""

    materialized = list(rows)
    if permutations % bands:
        raise ValueError("permutations must be divisible by bands")
    exact: dict[str, list[int]] = defaultdict(list)
    signatures: list[tuple[int, ...]] = []
    normalized_texts: list[str] = []
    for index, row in enumerate(materialized):
        normalized = _normalize_source_text(str(row.get("text") or ""))
        normalized_texts.append(normalized)
        exact[sha256_text(normalized)].append(index)
        row_shingles = five_word_shingles(normalized)
        signatures.append(
            minhash_signature(row_shingles, permutations=permutations)
        )
    candidates: set[tuple[int, int]] = set()
    band_width = permutations // bands
    for band in range(bands):
        buckets: dict[tuple[int, ...], list[int]] = defaultdict(list)
        start = band * band_width
        for index, signature in enumerate(signatures):
            buckets[signature[start : start + band_width]].append(index)
        for bucket in buckets.values():
            for left_index, left in enumerate(bucket):
                for right in bucket[left_index + 1 :]:
                    candidates.add((min(left, right), max(left, right)))
    duplicate_pairs: set[tuple[int, int, str, float]] = set()
    for indexes in exact.values():
        for offset, left in enumerate(indexes):
            for right in indexes[offset + 1 :]:
                duplicate_pairs.add((left, right, "exact_normalized_hash", 1.0))
    for left, right in candidates:
        left_shingles = five_word_shingles(normalized_texts[left])
        right_shingles = five_word_shingles(normalized_texts[right])
        union = left_shingles | right_shingles
        similarity = (
            len(left_shingles & right_shingles) / len(union) if union else 1.0
        )
        if similarity >= jaccard_threshold:
            duplicate_pairs.add((left, right, "minhash_candidate_jaccard", similarity))
    pair_rows = []
    cross_group = []
    for left, right, method, similarity in sorted(duplicate_pairs):
        left_row = materialized[left]
        right_row = materialized[right]
        record = {
            "left_source_key": source_key(left_row),
            "left_group": left_row.get("group"),
            "right_source_key": source_key(right_row),
            "right_group": right_row.get("group"),
            "method": method,
            "jaccard": round(float(similarity), 8),
        }
        pair_rows.append(record)
        if record["left_group"] != record["right_group"]:
            cross_group.append(record)
    return {
        "source_count": len(materialized),
        "normalized_exact_hash_groups": sum(
            1 for indexes in exact.values() if len(indexes) > 1
        ),
        "candidate_pair_count": len(candidates),
        "near_duplicate_pair_count": len(pair_rows),
        "cross_group_pair_count": len(cross_group),
        "cross_group_overlap": cross_group,
        "pairs": pair_rows,
        "jaccard_threshold": jaccard_threshold,
        "minhash_permutations": permutations,
        "minhash_bands": bands,
        "passed": not cross_group,
    }


def build_execution_schedule(
    query_paths: dict[str, str | Path],
    *,
    output_path: str | Path,
    seed: int = 42,
) -> dict[str, Any]:
    """Freeze 90,000 source-block-interleaved requests with Latin-square cells."""

    by_dataset: dict[str, dict[str, list[dict[str, Any]]]] = {}
    query_hashes: dict[str, str] = {}
    for dataset in DATASETS:
        path = Path(query_paths[dataset])
        query_hashes[dataset] = sha256_file(path)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in read_jsonl(path):
            key = source_key(row)
            grouped[key].append(row)
        if len(grouped) != 1250 or any(len(rows) != 6 for rows in grouped.values()):
            raise RuntimeError(f"{dataset}: schedule requires 1,250 sources x 6 queries")
        by_dataset[dataset] = grouped
    ordered_sources: dict[str, list[str]] = {}
    for dataset_index, dataset in enumerate(DATASETS):
        keys = sorted(by_dataset[dataset])
        random.Random(seed + dataset_index).shuffle(keys)
        ordered_sources[dataset] = keys
    schedule: list[dict[str, Any]] = []
    ordinal = 0
    for round_index in range(1250):
        dataset_order = [
            DATASETS[(round_index + offset) % len(DATASETS)]
            for offset in range(len(DATASETS))
        ]
        for dataset_offset, dataset in enumerate(dataset_order):
            key = ordered_sources[dataset][round_index]
            query_rows = sorted(
                by_dataset[dataset][key],
                key=lambda row: str(row.get("query_id")),
            )
            block_id = f"{round_index:04d}:{dataset}:{key}"
            latin_offset = (round_index + dataset_offset) % len(MAIN_CELLS)
            cell_order = [
                MAIN_CELLS[(latin_offset + offset) % len(MAIN_CELLS)]
                for offset in range(len(MAIN_CELLS))
            ]
            for cell in cell_order:
                for query_row in query_rows:
                    schedule.append(
                        {
                            "ordinal": ordinal,
                            "block_id": block_id,
                            "round": round_index,
                            "dataset": dataset,
                            "source_key": key,
                            "query_id": str(query_row.get("query_id")),
                            "cell": cell,
                        }
                    )
                    ordinal += 1
    if len(schedule) != 90_000:
        raise RuntimeError(f"Expected 90,000 scheduled requests, got {len(schedule)}")
    identities = {
        (row["dataset"], row["query_id"], row["cell"]) for row in schedule
    }
    if len(identities) != len(schedule):
        raise RuntimeError("Execution schedule contains duplicate request identities")
    write_jsonl(schedule, output_path)
    manifest = {
        "protocol_version": "pcv-mia-v20",
        "method_version": "pcv-rag-only-source-v20",
        "execution": "source_block_interleaved",
        "seed": seed,
        "datasets": list(DATASETS),
        "cells": list(MAIN_CELLS),
        "request_count": len(schedule),
        "source_block_request_count": 24,
        "query_hashes": query_hashes,
        "schedule_hash": sha256_file(output_path),
        "identity_hash": sha256_obj(sorted(identities)),
    }
    write_json(manifest, Path(output_path).with_suffix(".manifest.json"))
    return manifest


def validate_schedule_binding(
    schedule_manifest_path: str | Path,
    *,
    expected_hash: str | None = None,
) -> dict[str, Any]:
    manifest = read_json(schedule_manifest_path)
    manifest_path = Path(schedule_manifest_path)
    if not manifest_path.name.endswith(".manifest.json"):
        raise ValueError("Schedule manifest must end with .manifest.json")
    schedule_path = manifest_path.with_name(
        manifest_path.name[: -len(".manifest.json")] + ".jsonl"
    )
    actual_hash = sha256_file(schedule_path)
    if actual_hash != str(manifest.get("schedule_hash") or ""):
        raise RuntimeError("Execution schedule hash mismatch")
    if expected_hash and actual_hash != expected_hash:
        raise RuntimeError("Execution schedule identity drift")
    if int(manifest.get("request_count") or 0) != 90_000:
        raise RuntimeError("Canonical schedule must contain 90,000 requests")
    return manifest
