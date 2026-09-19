"""Oracle and matched Random context controls for v20 mechanism experiments."""

from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .index_builder import chunk_for_rag_tokens
from .retriever import RetrievedChunk
from ..evaluation.v20_release_controls import five_word_shingles, source_key
from ..utils.hash import sha256_obj
from ..utils.io import read_jsonl


class GroundTruthContextController:
    """Build Oracle/Random contexts without reading targets from the KB docstore."""

    def __init__(
        self,
        *,
        source_store_path: str | Path,
        dense_retriever: Any,
        chunk_size: int = 128,
        chunk_overlap: int = 32,
        max_chunks: int = 5,
        random_token_tolerance: float = 0.05,
        minhash_jaccard_exclusion: float = 0.85,
        dense_cosine_exclusion: float = 0.85,
    ):
        self.source_store_path = Path(source_store_path)
        self.sources = {
            source_key(row): row for row in read_jsonl(self.source_store_path)
        }
        if not self.sources:
            raise RuntimeError("ground_truth_source_store is empty")
        self.retriever = dense_retriever
        self.embedder = getattr(dense_retriever, "embedder", None)
        if self.embedder is None:
            raise RuntimeError("Oracle/Random controls require the frozen BGE embedder")
        self.tokenizer = getattr(self.embedder, "tokenizer", None)
        if self.tokenizer is None:
            raise RuntimeError("Oracle/Random controls require the frozen BGE tokenizer")
        self.docstore = list(getattr(dense_retriever, "docstore", []))
        if not self.docstore:
            raise RuntimeError("Random control requires the formal KB docstore")
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)
        self.max_chunks = int(max_chunks)
        self.random_token_tolerance = float(random_token_tolerance)
        self.minhash_jaccard_exclusion = float(minhash_jaccard_exclusion)
        self.dense_cosine_exclusion = float(dense_cosine_exclusion)
        self._source_vectors: dict[str, np.ndarray] | None = None
        self._eligible_cache: dict[str, set[str]] = {}

    def _chunks(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        key = source_key(row)
        texts = chunk_for_rag_tokens(
            str(row.get("text") or ""),
            self.tokenizer,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        return [
            {
                "chunk_id": f"{key}_gt_c{index:04d}",
                "doc_id": str(row.get("doc_id") or row.get("source_id") or key),
                "source_key": key,
                "text": text,
                "token_count": len(
                    self.tokenizer.encode(text, add_special_tokens=False)
                ),
            }
            for index, text in enumerate(texts)
        ]

    def oracle(self, query: str, target_source_key: str) -> list[RetrievedChunk]:
        target = self.sources.get(target_source_key)
        if target is None:
            raise RuntimeError(
                f"Target source is missing from ground_truth_source_store: "
                f"{target_source_key}"
            )
        chunks = self._chunks(target)
        if not chunks:
            raise RuntimeError(f"Oracle target has no chunks: {target_source_key}")
        encode_queries = getattr(
            self.embedder, "encode_queries", self.embedder.encode
        )
        query_vector = np.asarray(encode_queries([query]), dtype="float32")[0]
        chunk_vectors = np.asarray(
            self.embedder.encode([row["text"] for row in chunks]),
            dtype="float32",
        )
        scores = chunk_vectors @ query_vector
        order = sorted(
            range(len(chunks)),
            key=lambda index: (-float(scores[index]), str(chunks[index]["chunk_id"])),
        )[: self.max_chunks]
        return [
            RetrievedChunk(
                chunk_id=str(chunks[index]["chunk_id"]),
                doc_id=str(chunks[index]["doc_id"]),
                text=str(chunks[index]["text"]),
                score=float(scores[index]),
                metadata={
                    "source_key": target_source_key,
                    "context_control": "oracle",
                    "token_count": int(chunks[index]["token_count"]),
                },
            )
            for index in order
        ]

    def _source_embedding_map(self) -> dict[str, np.ndarray]:
        if self._source_vectors is not None:
            return self._source_vectors
        rows = list(self.sources.values())
        vectors = np.asarray(
            self.embedder.encode([str(row.get("text") or "") for row in rows]),
            dtype="float32",
        )
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-12)
        self._source_vectors = {
            source_key(row): vectors[index] for index, row in enumerate(rows)
        }
        return self._source_vectors

    def _eligible_random_sources(self, target_source_key: str) -> set[str]:
        cached = self._eligible_cache.get(target_source_key)
        if cached is not None:
            return cached
        target = self.sources[target_source_key]
        target_hash = str(target.get("text_hash") or "")
        target_shingles = five_word_shingles(str(target.get("text") or ""))
        vectors = self._source_embedding_map()
        target_vector = vectors[target_source_key]
        candidate_keys = {
            str(row.get("source_key") or (row.get("metadata") or {}).get("source_key"))
            for row in self.docstore
        }
        eligible: set[str] = set()
        for key in sorted(candidate_keys):
            candidate = self.sources.get(key)
            if candidate is None or key == target_source_key:
                continue
            if target_hash and str(candidate.get("text_hash") or "") == target_hash:
                continue
            candidate_shingles = five_word_shingles(str(candidate.get("text") or ""))
            union = target_shingles | candidate_shingles
            jaccard = (
                len(target_shingles & candidate_shingles) / len(union)
                if union
                else 1.0
            )
            if jaccard >= self.minhash_jaccard_exclusion:
                continue
            cosine = float(target_vector @ vectors[key])
            if cosine >= self.dense_cosine_exclusion:
                continue
            eligible.add(key)
        if not eligible:
            raise RuntimeError(f"No eligible Random distractors for {target_source_key}")
        self._eligible_cache[target_source_key] = eligible
        return eligible

    def random_matched(
        self,
        *,
        query_id: str,
        target_source_key: str,
        oracle_chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Select an equal-count Random context within 5% of Oracle tokens."""

        if not oracle_chunks:
            raise RuntimeError("Random matching requires non-empty Oracle chunks")
        eligible_sources = self._eligible_random_sources(target_source_key)
        candidates = [
            row
            for row in self.docstore
            if str(row.get("source_key") or (row.get("metadata") or {}).get("source_key"))
            in eligible_sources
        ]
        rng = random.Random(
            int(
                sha256_obj(
                    {"query_id": query_id, "target_source_key": target_source_key}
                )[:16],
                16,
            )
        )
        rng.shuffle(candidates)
        target_counts = sorted(
            [
                int(
                    chunk.metadata.get("token_count")
                    or len(
                        self.tokenizer.encode(
                            chunk.text, add_special_tokens=False
                        )
                    )
                )
                for chunk in oracle_chunks
            ],
            reverse=True,
        )
        chosen: list[dict[str, Any]] = []
        remaining = list(candidates)
        for target_count in target_counts:
            if not remaining:
                raise RuntimeError("Insufficient Random distractor chunks")
            best_index = min(
                range(len(remaining)),
                key=lambda index: (
                    abs(
                        len(
                            self.tokenizer.encode(
                                str(remaining[index].get("text") or ""),
                                add_special_tokens=False,
                            )
                        )
                        - target_count
                    ),
                    str(remaining[index].get("chunk_id")),
                ),
            )
            chosen.append(remaining.pop(best_index))
        oracle_tokens = sum(target_counts)
        random_tokens = sum(
            len(
                self.tokenizer.encode(
                    str(row.get("text") or ""), add_special_tokens=False
                )
            )
            for row in chosen
        )
        relative_gap = abs(random_tokens - oracle_tokens) / max(1, oracle_tokens)
        if relative_gap > self.random_token_tolerance:
            raise RuntimeError(
                f"Random token budget differs from Oracle by {relative_gap:.3%}"
            )
        return [
            RetrievedChunk(
                chunk_id=str(row["chunk_id"]),
                doc_id=str(row["doc_id"]),
                text=str(row["text"]),
                score=0.0,
                metadata={
                    **(row.get("metadata") or {}),
                    "source_key": row.get("source_key"),
                    "context_control": "random",
                    "oracle_token_count": oracle_tokens,
                    "random_token_count": random_tokens,
                    "token_relative_gap": relative_gap,
                },
            )
            for row in chosen
        ]
