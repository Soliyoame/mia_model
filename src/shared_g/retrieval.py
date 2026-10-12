"""固定 Member-only BGE index 和可恢复的 dense 检索。"""

from __future__ import annotations

import logging
from typing import Any

from src.utils.hash import sha256_file, sha256_obj, sha256_text

from .artifacts import ArtifactStore, append_request, read_json, read_rows, retry_local_write, unique_map, write_once
from .config import ExperimentConfig
from .sources import read_source_text, validate_isolation
from .types import QueryRecord


def rag_prompt(config: ExperimentConfig, query: QueryRecord, chunks: list[dict[str, Any]]) -> tuple[str, str]:
    context = "\n\n---\n\n".join(chunk["text"] for chunk in chunks)
    return context, config.data["runtime"]["rag_prompt"].format(contexts=context, query=query["question"])


def validate_retrieval(config: ExperimentConfig, store: ArtifactStore, dataset: str,
                       complete: bool = True) -> dict[str, dict[str, Any]]:
    queries = unique_map([q for q in read_rows(store.path("query_plan.jsonl")) if q["dataset"] == dataset], "query_id")
    rows = read_rows(store.path("retrieval.jsonl", dataset))
    result = unique_map(rows, "query_id")
    if set(result) - set(queries) or (complete and set(result) != set(queries)):
        raise RuntimeError("retrieval_query_set_incomplete_or_extra")
    members = unique_map([r for r in read_rows(store.path("index_manifest.jsonl")) if r["dataset"] == dataset], "source_key")
    plan_hash = sha256_file(store.path("query_plan.jsonl"))
    identity = store.index_identity(dataset)
    for key, row in result.items():
        if (row["dataset"] != dataset or row["query_plan_sha256"] != plan_hash
                or row["index_identity"] != identity or row["retriever"] != config.data["runtime"]["retrieval"]):
            raise RuntimeError("retrieval_identity_drift")
        chunks = row["retrieved_chunks"]
        if len(chunks) != config.data["runtime"]["retrieval"]["top_k"]:
            raise RuntimeError("retrieval_top_k_drift")
        for chunk in chunks:
            member = members.get(chunk["source_key"])
            if not member or member["group"] != "KB_Member" or chunk["source_hash"] != member["source_hash"]:
                raise RuntimeError("retrieval_nonmember_or_hash_drift")
        context, prompt = rag_prompt(config, queries[key], chunks)
        if row["context_sha256"] != sha256_text(context) or row["prompt_sha256"] != sha256_text(prompt):
            raise RuntimeError("retrieval_context_or_prompt_drift")
        if row["record_sha256"] != sha256_obj({k: v for k, v in row.items() if k != "record_sha256"}):
            raise RuntimeError("retrieval_record_drift")
    return result


def load_or_build_index(config: ExperimentConfig, store: ArtifactStore, dataset: str,
                        embedder: Any) -> tuple[list[dict[str, Any]], Any]:
    import numpy as np
    from src.rag.index_builder import chunk_for_rag_tokens

    directory = store.path("index", dataset)
    metadata_path = directory / "index.json"
    chunks_path, vectors_path = directory / "chunks.jsonl", directory / "embeddings.npy"
    retrieval = config.data["runtime"]["retrieval"]
    expected = {"index_identity": store.index_identity(dataset), "retriever": retrieval}
    if metadata_path.exists():
        metadata = read_json(metadata_path)
        if any(metadata[key] != value for key, value in expected.items()):
            raise RuntimeError("dense_index_identity_drift")
        for path in (chunks_path, vectors_path):
            if sha256_file(path) != metadata["artifacts"][path.name]:
                raise RuntimeError("dense_index_artifact_drift")
        return read_rows(chunks_path), np.load(vectors_path, allow_pickle=False, mmap_mode="r")
    if directory.exists() and any(directory.iterdir()):
        raise RuntimeError("partial_dense_index_preserved")
    sources = read_rows(store.path("source_manifest.jsonl"))
    members = read_rows(store.path("index_manifest.jsonl"))
    validate_isolation(sources, members)
    chunks: list[dict[str, Any]] = []
    for member in (row for row in members if row["dataset"] == dataset):
        for index, text in enumerate(chunk_for_rag_tokens(read_source_text(config, member), embedder.tokenizer,
                                                        chunk_size=retrieval["chunk_size"], chunk_overlap=retrieval["chunk_overlap"])):
            chunks.append({"chunk_id": f"{member['source_key']}_c{index:02d}", "source_key": member["source_key"],
                           "source_hash": member["source_hash"], "text": text})
    if len(chunks) < retrieval["top_k"]:
        raise RuntimeError("insufficient_index_chunks")
    vectors = np.asarray(embedder.encode_documents([row["text"] for row in chunks]), dtype="float32")
    if vectors.ndim != 2 or len(vectors) != len(chunks) or not np.isfinite(vectors).all():
        raise RuntimeError("invalid_document_embeddings")
    write_once(chunks_path, chunks)
    temporary = vectors_path.with_suffix(".npy.tmp")
    with temporary.open("wb") as handle:
        np.save(handle, vectors, allow_pickle=False)
    retry_local_write(lambda: temporary.replace(vectors_path))
    write_once(metadata_path, {**expected, "chunk_count": len(chunks),
                              "artifacts": {p.name: sha256_file(p) for p in (chunks_path, vectors_path)}})
    logging.getLogger(__name__).info("index dataset=%s chunks=%d", dataset, len(chunks))
    return chunks, vectors


def retrieve(config: ExperimentConfig, store: ArtifactStore, dataset: str,
             max_new: int = 200) -> dict[str, Any]:
    import numpy as np
    import torch
    from src.rag.embeddings import build_embedding_model

    store.validate(frozen=True)
    if dataset not in config.datasets or max_new < 1:
        raise ValueError("invalid_dataset_or_wave_budget")
    saved = validate_retrieval(config, store, dataset, complete=False)
    queries = [q for q in read_rows(store.path("query_plan.jsonl")) if q["dataset"] == dataset]
    pending = [q for q in queries if q["query_id"] not in saved][:max_new]
    if not pending:
        return {"stage": "retrieve", "dataset": dataset, "new_queries": 0, "complete": True}
    if not torch.cuda.is_available():
        raise RuntimeError("cuda_required_for_bge_retrieval")
    retrieval = config.data["runtime"]["retrieval"]
    embedder = build_embedding_model(retrieval["retriever_id"], backend="sentence_transformers", local_files_only=True,
                                    revision=retrieval["revision"], query_instruction=retrieval["query_instruction"])
    try:
        if not str(embedder._model.device).startswith("cuda"):
            raise RuntimeError("bge_cpu_fallback_forbidden")
        chunks, vectors = load_or_build_index(config, store, dataset, embedder)
        query_vectors = np.asarray(embedder.encode_queries([q["retrieval_query"] for q in pending]), dtype="float32")
        if (query_vectors.ndim != 2 or len(query_vectors) != len(pending)
                or query_vectors.shape[1] != vectors.shape[1] or not np.isfinite(query_vectors).all()):
            raise RuntimeError("invalid_query_embeddings")
        plan_hash = sha256_file(store.path("query_plan.jsonl"))
        index_identity = store.index_identity(dataset)
        for query, scores in zip(pending, query_vectors @ vectors.T):
            indices = np.argsort(-scores, kind="stable")[:retrieval["top_k"]]
            found = [{**chunks[int(index)], "score": float(scores[int(index)])} for index in indices]
            context, prompt = rag_prompt(config, query, found)
            row = {"query_id": query["query_id"], "source_key": query["source_key"], "dataset": dataset,
                   "arm": query["arm"], "slot_index": query["slot_index"], "retrieved_chunks": found,
                   "query_plan_sha256": plan_hash,
                   "index_identity": index_identity, "retriever": retrieval,
                   "context_sha256": sha256_text(context), "prompt_sha256": sha256_text(prompt),
                   "target_source_chunk_ranks": [i + 1 for i, chunk in enumerate(found) if chunk["source_key"] == query["source_key"]]}
            row["record_sha256"] = sha256_obj(row)
            append_request(store.path("retrieval.jsonl", dataset), row)
    finally:
        embedder.close()
    observed = validate_retrieval(config, store, dataset, complete=False)
    return {"stage": "retrieve", "dataset": dataset, "new_queries": len(pending),
            "completed_queries": len(observed), "planned_queries": len(queries), "complete": len(observed) == len(queries)}
