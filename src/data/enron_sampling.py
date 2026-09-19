"""Freeze an unbiased, exact-deduplicated Enron screening pool.

The complete CSV is the sampling frame.  Selection is label-independent and
uses the lowest deterministic hashes of unique complete-email contents.  The
large selected JSONL is written atomically; the pass-1 index is reusable after
an interruption so the expensive CSV scan does not have to be repeated.
"""

from __future__ import annotations

import csv
import heapq
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .reader import MAX_CSV_FIELD_CHARS
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import (
    ensure_parent,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl_atomic,
)


SAMPLING_PROTOCOL = "enron_full_csv_hash_sample_v1"
SELECTION_METHOD = "sha256(seed,dataset,message_sha256)"
MIN_RAW_SCREENING_TARGET = 30000


def mailbox_user(file_value: str) -> str:
    """Return the top-level mailbox name from the Enron ``file`` column."""

    normalized = str(file_value or "").strip().replace("\\", "/")
    return normalized.split("/", 1)[0].strip()


def _csv_rows(path: Path):
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(max(previous_limit, MAX_CSV_FIELD_CHARS))
    try:
        with path.open(
            "r",
            encoding="utf-8",
            errors="replace",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["file", "message"]:
                raise RuntimeError(
                    "Unexpected Enron CSV schema: "
                    f"{reader.fieldnames!r}"
                )
            for row_index, row in enumerate(reader):
                yield row_index, str(row.get("file") or ""), str(
                    row.get("message") or ""
                )
    finally:
        csv.field_size_limit(previous_limit)


def _selection_score(seed: int, message_sha256: str) -> str:
    return sha256_text(f"{seed}\0enron\0{message_sha256}")


def _validate_pass1(
    *,
    index_path: Path,
    pass_manifest_path: Path,
    raw_csv_sha256: str,
    target_sources: int,
) -> dict[str, Any]:
    manifest = read_json(pass_manifest_path)
    if (
        manifest.get("protocol") != SAMPLING_PROTOCOL
        or manifest.get("status") != "pass1_complete"
        or manifest.get("raw_csv_sha256") != raw_csv_sha256
        or int(manifest.get("selected_source_count", -1))
        != target_sources
        or sha256_file(index_path)
        != manifest.get("selection_index_sha256")
    ):
        raise RuntimeError("Enron pass-1 selection checkpoint drift")
    return manifest


def freeze_enron_sampling_frame(
    *,
    raw_csv_path: str | Path,
    selected_jsonl_path: str | Path,
    selection_index_path: str | Path,
    pass_manifest_path: str | Path,
    final_manifest_path: str | Path,
    selection_seed: int,
    expected_raw_records: int,
    expected_mailbox_users: int,
    raw_screening_target_sources: int,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Scan the full CSV, freeze a hash sample, and materialize selected mail."""

    raw_csv = Path(raw_csv_path).resolve()
    selected_jsonl = Path(selected_jsonl_path).resolve()
    selection_index = Path(selection_index_path).resolve()
    pass_manifest = Path(pass_manifest_path).resolve()
    final_manifest = Path(final_manifest_path).resolve()
    if not raw_csv.is_file():
        raise FileNotFoundError(raw_csv)
    if selection_seed != 42:
        raise RuntimeError("The Enron full-corpus selection seed must be 42")
    if raw_screening_target_sources < MIN_RAW_SCREENING_TARGET:
        raise RuntimeError("Raw screening pool cannot be smaller than 30,000")

    raw_csv_sha256 = sha256_file(raw_csv)
    if final_manifest.is_file() and selected_jsonl.is_file() and resume and not force:
        existing = read_json(final_manifest)
        if (
            existing.get("status") != "passed"
            or existing.get("protocol") != SAMPLING_PROTOCOL
            or existing.get("raw_csv_sha256") != raw_csv_sha256
            or int(existing.get("selected_source_count", -1))
            != raw_screening_target_sources
            or sha256_file(selected_jsonl)
            != existing.get("selected_jsonl_sha256")
        ):
            raise RuntimeError("Existing Enron sampling artifact drift")
        return {**existing, "skipped_existing": True}

    if (
        not force
        and not resume
        and (selected_jsonl.exists() or final_manifest.exists())
    ):
        raise RuntimeError(
            "Partial/final sampling outputs already exist; use --resume to "
            "validate them or --force to rebuild"
        )

    pass1: dict[str, Any]
    if (
        resume
        and not force
        and selection_index.is_file()
        and pass_manifest.is_file()
    ):
        pass1 = _validate_pass1(
            index_path=selection_index,
            pass_manifest_path=pass_manifest,
            raw_csv_sha256=raw_csv_sha256,
            target_sources=raw_screening_target_sources,
        )
    else:
        seen_message_hashes: set[str] = set()
        raw_users: set[str] = set()
        counters: Counter[str] = Counter()
        # Max heap encoded with negative integers; it retains the lowest K
        # deterministic content scores without holding all message bodies.
        heap: list[tuple[int, str, int, str, str]] = []
        for row_index, file_value, message in _csv_rows(raw_csv):
            counters["raw_records"] += 1
            user = mailbox_user(file_value)
            if user:
                raw_users.add(user)
            if not message.strip():
                counters["blank_messages"] += 1
                continue
            message_sha = sha256_text(message)
            if message_sha in seen_message_hashes:
                counters["exact_duplicate_messages"] += 1
                continue
            seen_message_hashes.add(message_sha)
            counters["unique_nonblank_messages"] += 1
            score = _selection_score(selection_seed, message_sha)
            item = (-int(score, 16), message_sha, row_index, file_value, user)
            if len(heap) < raw_screening_target_sources:
                heapq.heappush(heap, item)
            elif item[0] > heap[0][0]:
                heapq.heapreplace(heap, item)

        if counters["raw_records"] != expected_raw_records:
            raise RuntimeError(
                "Enron raw-record gate failed: "
                f"expected={expected_raw_records} "
                f"actual={counters['raw_records']}"
            )
        if len(raw_users) != expected_mailbox_users:
            raise RuntimeError(
                "Enron mailbox-user gate failed: "
                f"expected={expected_mailbox_users} actual={len(raw_users)}"
            )
        if len(heap) != raw_screening_target_sources:
            raise RuntimeError("Enron unique source universe is below target")

        selection_rows = sorted(
            (
                {
                    "raw_row_index": row_index,
                    "file": file_value,
                    "mailbox_user": user,
                    "message_sha256": message_sha,
                    "selection_score": _selection_score(
                        selection_seed, message_sha
                    ),
                }
                for _, message_sha, row_index, file_value, user in heap
            ),
            key=lambda row: int(row["raw_row_index"]),
        )
        write_jsonl_atomic(selection_rows, selection_index)
        pass1 = {
            "status": "pass1_complete",
            "protocol": SAMPLING_PROTOCOL,
            "selection_seed": selection_seed,
            "selection_method": SELECTION_METHOD,
            "exact_message_deduplication": True,
            "raw_csv_path": str(raw_csv),
            "raw_csv_sha256": raw_csv_sha256,
            "expected_raw_records": expected_raw_records,
            "raw_record_count": counters["raw_records"],
            "expected_mailbox_users": expected_mailbox_users,
            "raw_mailbox_user_count": len(raw_users),
            "raw_mailbox_users_hash": sha256_obj(sorted(raw_users)),
            "raw_screening_target_sources": raw_screening_target_sources,
            "selected_source_count": len(selection_rows),
            "selection_index_path": str(selection_index),
            "selection_index_sha256": sha256_file(selection_index),
            **dict(counters),
        }
        write_json(pass1, pass_manifest)

    selected_by_hash = {
        str(row["message_sha256"]): row
        for row in read_jsonl(selection_index)
    }
    if len(selected_by_hash) != raw_screening_target_sources:
        raise RuntimeError("Enron selection index cardinality drift")

    ensure_parent(selected_jsonl)
    tmp = selected_jsonl.with_suffix(selected_jsonl.suffix + ".tmp")
    written_hashes: set[str] = set()
    selected_users: set[str] = set()
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for row_index, file_value, message in _csv_rows(raw_csv):
            message_sha = sha256_text(message)
            selected = selected_by_hash.get(message_sha)
            if selected is None or message_sha in written_hashes:
                continue
            if row_index != int(selected["raw_row_index"]):
                continue
            user = mailbox_user(file_value)
            record = {
                "id": f"enron_msg_{message_sha[:24]}",
                "text": message,
                "raw_row_index": row_index,
                "file": file_value,
                "mailbox_user": user,
                "raw_message_sha256": message_sha,
                "selection_score": selected["selection_score"],
            }
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
            written_hashes.add(message_sha)
            if user:
                selected_users.add(user)
    if len(written_hashes) != raw_screening_target_sources:
        raise RuntimeError(
            "Enron pass-2 materialization was incomplete: "
            f"expected={raw_screening_target_sources} actual={len(written_hashes)}"
        )
    tmp.replace(selected_jsonl)

    result = {
        **pass1,
        "status": "passed",
        "selected_jsonl_path": str(selected_jsonl),
        "selected_jsonl_sha256": sha256_file(selected_jsonl),
        "selected_mailbox_user_count": len(selected_users),
        "selected_mailbox_users_hash": sha256_obj(sorted(selected_users)),
        "sampling_identity_hash": sha256_obj(
            {
                "protocol": SAMPLING_PROTOCOL,
                "raw_csv_sha256": raw_csv_sha256,
                "selection_seed": selection_seed,
                "selection_method": SELECTION_METHOD,
                "selected_source_count": raw_screening_target_sources,
                "selection_index_sha256": pass1["selection_index_sha256"],
                "selected_jsonl_sha256": sha256_file(selected_jsonl),
            }
        ),
    }
    write_json(result, final_manifest)
    return result
