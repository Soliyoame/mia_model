"""Build immutable v24-local source pools from a local BEIR corpus.jsonl."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v24 import (  # noqa: E402
    DATASET_ORDER,
    V24_SOURCE_POOL_MINIMUM,
    _norm,
    sha256_file,
    sha256_obj,
    sha256_text,
)
from src.utils.io import write_json  # noqa: E402


def _read_corpus(path: Path, dataset: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    counts = {
        "raw_document_count": 0,
        "empty_document_count": 0,
        "duplicate_document_id_count": 0,
        "duplicate_text_count": 0,
    }
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        counts["raw_document_count"] += 1
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid_corpus_json:{line_number}") from exc
        if not isinstance(value, dict) or "_id" not in value:
            raise ValueError(f"beir_row_schema:{line_number}")
        document_id = str(value["_id"])
        if not document_id:
            raise ValueError(f"empty_document_id:{line_number}")
        if document_id in seen_ids:
            counts["duplicate_document_id_count"] += 1
            raise ValueError("duplicate_document_id")
        seen_ids.add(document_id)
        title = str(value.get("title") or "").strip()
        text = str(value.get("text") or "").strip()
        full_text = f"{title}\n\n{text}".strip()
        if not full_text:
            counts["empty_document_count"] += 1
            continue
        rows.append({"dataset": dataset, "document_id": document_id, "title": title, "text": text, "full_text": full_text})
    return rows, counts


def build_source_pool(dataset: str, corpus: str | Path, output_root: str | Path) -> dict[str, Any]:
    if dataset not in DATASET_ORDER:
        raise ValueError("v24_source_pool_dataset_invalid")
    corpus_path = Path(corpus).resolve()
    if not corpus_path.is_file() or corpus_path.name != "corpus.jsonl":
        raise ValueError("v24_beir_corpus_jsonl_required")
    output = Path(output_root).resolve() / dataset
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("v24_source_pool_output_exists")
    output.mkdir(parents=True, exist_ok=True)
    rows, counts = _read_corpus(corpus_path, dataset)
    rows.sort(key=lambda row: row["document_id"])
    seen_text: set[str] = set()
    retained: list[dict[str, Any]] = []
    for row in rows:
        normalized_hash = sha256_text(_norm(row["full_text"]))
        if normalized_hash in seen_text:
            counts["duplicate_text_count"] += 1
            continue
        seen_text.add(normalized_hash)
        retained.append(row)
    if len(retained) < V24_SOURCE_POOL_MINIMUM:
        raise RuntimeError("insufficient_source_pool_capacity")

    source_order: list[str] = []
    identities: list[dict[str, str]] = []
    database_path = output / "source_pool.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            "CREATE TABLE sources (source_key TEXT PRIMARY KEY, dataset TEXT NOT NULL, document_id TEXT NOT NULL, "
            "source_order_rank TEXT NOT NULL, source_hash TEXT NOT NULL, normalized_text_hash TEXT NOT NULL, "
            "full_text TEXT NOT NULL, input_row_count INTEGER NOT NULL);"
            "CREATE TABLE chunks (source_key TEXT NOT NULL, chunk_rank INTEGER NOT NULL, selection_hash TEXT NOT NULL, "
            "row_json TEXT NOT NULL, PRIMARY KEY (source_key, chunk_rank));"
        )
        for index, row in enumerate(retained):
            source_key = f"{dataset}::{row['document_id']}"
            source_hash = sha256_text(row["full_text"])
            normalized_hash = sha256_text(_norm(row["full_text"]))
            rank = str(index)
            chunk_row = {"source_key": source_key, "document_id": row["document_id"], "text": row["full_text"]}
            selection_hash = sha256_obj(chunk_row)
            connection.execute(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (source_key, dataset, row["document_id"], rank, source_hash, normalized_hash, row["full_text"], 1),
            )
            connection.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                (source_key, 0, selection_hash, json.dumps(chunk_row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
            )
            source_order.append(source_key)
            identities.append({"dataset": dataset, "source_key": source_key, "document_id": row["document_id"],
                               "source_hash": source_hash, "normalized_text_hash": normalized_hash, "source_order_rank": rank})
        connection.commit()
    finally:
        connection.close()

    order_payload = {
        "kind": "v24_beir_source_order", "dataset": dataset, "source_order": source_order,
        "source_order_content_sha256": sha256_obj(source_order),
    }
    order_path = output / "source_order.json"
    write_json(order_payload, order_path)
    exclusions = identities[:10]
    for row in exclusions:
        row["reason"] = "development"
    write_json({"kind": "v24_development_exclusions", "dataset": dataset, "exclusions": exclusions}, output / "development_exclusions.json")
    manifest_payload = {
        "kind": "v24_beir_source_pool", "protocol_version": "pcv-mia-v24", "dataset": dataset,
        "corpus_input_path": str(corpus_path), "corpus_input_sha256": sha256_file(corpus_path),
        **counts, "frozen_source_count": len(retained), "minimum_source_count": V24_SOURCE_POOL_MINIMUM,
        "source_order_content_sha256": order_payload["source_order_content_sha256"],
        "source_order_sha256": sha256_file(order_path), "database_sha256": sha256_file(database_path),
        "source_pool_identity_sha256": sha256_obj(identities),
        "normalization_rule": "v24._norm", "input_row_count": 1,
        "membership_labels_read": [], "queries_read": False, "qrels_read": False,
        "development_exclusions": exclusions,
    }
    manifest_payload["manifest_content_sha256"] = sha256_obj(manifest_payload)
    write_json(manifest_payload, output / "source_pool_manifest.json")
    manifest_payload["manifest_sha256"] = sha256_file(output / "source_pool_manifest.json")
    return manifest_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a v24-local BEIR source pool")
    parser.add_argument("--dataset", choices=DATASET_ORDER, required=True)
    parser.add_argument("--corpus", required=True, help="local BEIR corpus.jsonl")
    parser.add_argument("--output-root", default="artifacts/v24/source_pools")
    args = parser.parse_args()
    result = build_source_pool(args.dataset, args.corpus, args.output_root)
    print(json.dumps({"status": "completed", "dataset": args.dataset, "frozen_source_count": result["frozen_source_count"],
                      "development_exclusion_count": len(result["development_exclusions"]),
                      "manifest_path": f"{args.output_root}/{args.dataset}/source_pool_manifest.json"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
