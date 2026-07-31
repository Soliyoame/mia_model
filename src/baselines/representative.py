"""Frozen representative-chunk selection shared by all v20 baselines."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ..evaluation.v20_release_controls import aggregate_split_sources, source_key
from ..rag.index_builder import chunk_for_rag_tokens
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import read_jsonl, write_json, write_jsonl


def build_representative_chunk_manifest(
    *,
    dataset: str,
    splits_dir: str | Path,
    queries_path: str | Path,
    dense_retriever: Any,
    output_path: str | Path,
    chunk_size: int = 128,
    chunk_overlap: int = 32,
) -> dict[str, Any]:
    """Select one chunk/source by maximum BGE cosine over six frozen queries."""

    tokenizer = getattr(dense_retriever, "tokenizer", None) or getattr(
        getattr(dense_retriever, "embedder", None), "tokenizer", None
    )
    embedder = getattr(dense_retriever, "embedder", None)
    if tokenizer is None or embedder is None:
        raise RuntimeError("Representative chunk selection requires frozen BGE")
    queries_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(queries_path):
        if row.get("accepted", True):
            queries_by_source[source_key(row)].append(row)
    selected: list[dict[str, Any]] = []
    input_hashes: dict[str, str] = {"queries": sha256_file(queries_path)}
    for filename, expected_group in (
        ("kb_member.jsonl", "KB_Member"),
        ("true_non_member.jsonl", "True_Non_Member"),
    ):
        path = Path(splits_dir) / filename
        input_hashes[expected_group] = sha256_file(path)
        for source in aggregate_split_sources(read_jsonl(path)):
            key = source_key(source)
            queries = sorted(
                queries_by_source.get(key, []),
                key=lambda row: str(row.get("query_id")),
            )
            if len(queries) != 6:
                raise RuntimeError(
                    f"{dataset}/{key}: representative selection requires six queries"
                )
            chunks = chunk_for_rag_tokens(
                str(source.get("text") or ""),
                tokenizer,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            if not chunks:
                raise RuntimeError(f"{dataset}/{key}: source has no chunks")
            encode_queries = getattr(embedder, "encode_queries", embedder.encode)
            query_vectors = np.asarray(
                encode_queries([str(row["query"]) for row in queries]),
                dtype="float32",
            )
            chunk_vectors = np.asarray(embedder.encode(chunks), dtype="float32")
            maxima = (chunk_vectors @ query_vectors.T).max(axis=1)
            chunk_ids = [
                f"{source.get('doc_id')}_c{index:04d}"
                for index in range(len(chunks))
            ]
            winner = min(
                range(len(chunks)),
                key=lambda index: (-float(maxima[index]), chunk_ids[index]),
            )
            selected.append(
                {
                    "dataset": dataset,
                    "group": expected_group,
                    "source_key": key,
                    "source_id": source.get("source_id") or source.get("doc_id"),
                    "doc_id": chunk_ids[winner],
                    "source_doc_id": source.get("doc_id"),
                    "chunk_id": chunk_ids[winner],
                    "text": chunks[winner],
                    "text_hash": sha256_text(chunks[winner]),
                    "selection_score": float(maxima[winner]),
                    "selection_rule": "max_bge_cosine_over_six_frozen_queries",
                    "tie_break": "chunk_id_lexicographic",
                }
            )
    if len(selected) != 1000 or len({row["source_key"] for row in selected}) != 1000:
        raise RuntimeError(f"{dataset}: expected exactly one chunk for 1,000 sources")
    ordered = sorted(selected, key=lambda row: str(row["source_key"]))
    write_jsonl(ordered, output_path)
    manifest = {
        "protocol_version": "pcv-mia-v20",
        "dataset": dataset,
        "retriever_backend": "dense",
        "retriever_id": str(
            getattr(dense_retriever, "manifest", {}).get("retriever_id")
            or "BAAI/bge-base-en-v1.5"
        ),
        "index_manifest_hash": str(
            getattr(dense_retriever, "index_manifest_hash", "")
            or sha256_obj(getattr(dense_retriever, "manifest", {}))
        ),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "selection": "max_bge_cosine_over_six_frozen_queries",
        "tie_break": "chunk_id_lexicographic",
        "shared_across_methods": True,
        "source_count": len(ordered),
        "input_hashes": input_hashes,
        "representative_chunk_manifest_hash": sha256_file(output_path),
        "source_chunk_binding_hash": sha256_obj(
            [
                {
                    "source_key": row["source_key"],
                    "chunk_id": row["chunk_id"],
                    "text_hash": row["text_hash"],
                }
                for row in ordered
            ]
        ),
        "api_calls_made": 0,
    }
    write_json(manifest, Path(output_path).with_suffix(".manifest.json"))
    return manifest


def load_representative_targets(
    path: str | Path,
    manifest_path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load and fail-closed validate the one-row-per-source baseline targets."""

    from ..utils.io import read_json

    target_path = Path(path)
    manifest_file = (
        Path(manifest_path)
        if manifest_path is not None
        else target_path.with_suffix(".manifest.json")
    )
    manifest = read_json(manifest_file)
    if sha256_file(target_path) != str(
        manifest.get("representative_chunk_manifest_hash") or ""
    ):
        raise RuntimeError("Representative chunk manifest hash mismatch")
    targets = list(read_jsonl(target_path))
    if (
        len(targets) != 1000
        or len({source_key(row) for row in targets}) != 1000
        or any(not row.get("chunk_id") or not row.get("text_hash") for row in targets)
    ):
        raise RuntimeError("Representative targets are incomplete or duplicated")
    return targets, manifest
