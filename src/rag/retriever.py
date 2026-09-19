"""RAG 检索模块。

中文说明
========
本文件负责 RAG 流程里的「检索」这一步(对应流水线第 10 步运行时)：
给定一个用户查询(query)，到事先建好的向量索引里找出最相似的若干文本块(chunk)。
- 输入：一个 query 字符串 + 索引目录(里面有 index_manifest.json、docstore.jsonl、
  faiss.index 三个文件)。
- 输出：top-k 个最相关的文本块(RetrievedChunk 列表)，供后续拼进 prompt 喂给大模型。
- 上游：src/rag/index_builder.py 负责把这些索引文件建好。
- 下游：src/rag/runner.py 拿到检索结果后构造 prompt 并调用 LLM。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .embeddings import (
    DEFAULT_BGE_QUERY_INSTRUCTION,
    DEFAULT_EMBEDDING_MODEL,
    build_embedding_model,
    enforce_hf_offline,
    resolve_hf_model_source,
)
from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import read_json, read_jsonl


@dataclass
class RetrievedChunk:
    """单条检索结果。

    中文说明：用一个小数据类把"检索到的一个文本块"的信息打包在一起，方便传递。
    字段含义：
        chunk_id: 文本块的唯一编号(一个文档会被切成多块)。
        doc_id:   这个块属于哪篇原始文档。
        text:     这个块的实际文字内容。
        score:    这个块与查询的相似度得分(越高越相关)。
        metadata: 其它附加信息(比如这是第几块、原文 hash 等)。
    """

    chunk_id: str
    doc_id: str
    text: str
    score: float
    metadata: dict[str, Any]


class RagRetriever:
    """加载 index_manifest、docstore 和向量索引并执行 top-k 检索。

    中文说明：这个类就是"检索器"。创建它时会把索引相关的文件都加载进来；之后
    反复调用 retrieve() 就能对不同查询做检索。
    """

    def __init__(self, index_dir: str | Path):
        """构造检索器：把索引目录里的清单、文档库、向量索引都读进内存。

        参数:
            index_dir: 索引目录路径(由 index_builder 生成)，里面应包含
                       index_manifest.json / docstore.jsonl / faiss.index。
        """
        self.index_dir = Path(index_dir)
        # manifest(清单)：记录这个索引是用什么模型、什么参数建的。
        self.manifest = read_json(self.index_dir / "index_manifest.json")
        docstore_path = self.index_dir / "docstore.jsonl"
        expected_docstore_hash = str(self.manifest.get("docstore_hash") or "")
        if not expected_docstore_hash or sha256_file(docstore_path) != expected_docstore_hash:
            raise RuntimeError("RAG docstore hash does not match index_manifest.json")
        # docstore(文档库)：所有文本块的列表，顺序与向量一一对应。
        self.docstore = list(read_jsonl(docstore_path))
        self.retriever_backend = str(self.manifest.get("retriever_backend") or "dense").lower()
        if self.retriever_backend not in {"dense", "bm25"}:
            raise RuntimeError(
                f"Unsupported retriever backend in manifest: {self.retriever_backend!r}"
            )
        self.embedder = None
        if self.retriever_backend == "dense":
            self.embedder = build_embedding_model(
                str(self.manifest.get("requested_embedding_model") or self.manifest.get("embedding_model") or DEFAULT_EMBEDDING_MODEL),
                backend="auto",
                dim=int(self.manifest.get("embedding_dim") or 384),
                local_files_only=bool(self.manifest.get("embedding_local_files_only", False)),
                revision=self.manifest.get("embedding_revision"),
                query_instruction=str(
                    self.manifest.get("query_instruction")
                    or DEFAULT_BGE_QUERY_INSTRUCTION
                ),
            )
        # 记录后端类型(faiss 还是 json 兜底)，决定下面用哪种方式加载/检索。
        self.backend = str(self.manifest.get("embedding_backend", ""))
        self._faiss_index = None
        self._vectors: np.ndarray | None = None
        self._bm25_payload: dict[str, Any] | None = None
        # 真正把向量索引加载进来。
        self._load_index()

    def _load_index(self) -> None:
        """加载向量索引：优先用 FAISS；FAISS 不可用时回退到 JSON 里的原始向量。"""
        index_path = self.index_dir / str(
            self.manifest.get("index_filename")
            or ("bm25.index.json" if self.retriever_backend == "bm25" else "faiss.index")
        )
        expected_index_hash = str(self.manifest.get("index_hash") or "")
        if not expected_index_hash or sha256_file(index_path) != expected_index_hash:
            raise RuntimeError("RAG index hash does not match index_manifest.json")
        if self.retriever_backend == "bm25":
            self._bm25_payload = json.loads(index_path.read_text(encoding="utf-8"))
            if self._bm25_payload.get("backend") != "bm25":
                raise RuntimeError(f"Invalid BM25 index payload: {index_path}")
            if int(self._bm25_payload.get("num_docs", -1)) != len(self.docstore):
                raise RuntimeError("BM25 index/docstore size mismatch")
            return
        # 如果建索引时用的是 FAISS，就尝试用 FAISS 读回来(检索更快)。
        if self.backend.startswith("faiss"):
            try:
                import faiss  # type: ignore

                self._faiss_index = faiss.read_index(str(index_path))
            except Exception as exc:
                raise RuntimeError(f"Unable to load FAISS index: {index_path}") from exc
            if int(self._faiss_index.ntotal) != len(self.docstore):
                raise RuntimeError("Dense index/docstore size mismatch")
            return
        # 兜底：索引文件其实是 JSON，里面直接存了所有向量，读出来转成 numpy 矩阵。
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        self._vectors = np.asarray(payload["vectors"], dtype="float32")
        if self._vectors.shape[0] != len(self.docstore):
            raise RuntimeError("Dense index/docstore size mismatch")

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """返回 top-k chunk。

        中文说明：把查询编码成向量，找出与之最相似的 top_k 个文本块并返回。

        参数:
            query: 用户查询文本。
            top_k: 返回多少个最相关的块，默认 5。
        返回:
            按相似度从高到低排好序的 RetrievedChunk 列表。
        """
        if self.retriever_backend == "bm25":
            pairs = self._retrieve_bm25(query, top_k)
        else:
            if self.embedder is None:
                return []
            # 把查询文本编码成 (1, 维度) 的向量，类型转成 float32 以匹配索引。
            encode_queries = getattr(self.embedder, "encode_queries", self.embedder.encode)
            q = encode_queries([query]).astype("float32")
            pairs = self._retrieve_dense(q, top_k)

        results = []
        # 根据上面得到的(行号, 分数)，去 docstore 里取出对应文本块，组装成返回对象。
        for idx, score in pairs:
            # 行号越界(理论上不该发生)就跳过，保护程序不崩。
            if idx >= len(self.docstore):
                continue
            row = self.docstore[idx]
            results.append(
                RetrievedChunk(
                    chunk_id=str(row["chunk_id"]),
                    doc_id=str(row["doc_id"]),
                    text=str(row["text"]),
                    score=score,
                    metadata={
                        **(row.get("metadata") or {}),
                        "source_id": row.get("source_id"),
                        "source_key": row.get("source_key"),
                    },
                )
            )
        return results

    def _retrieve_dense(self, query_vector: np.ndarray, top_k: int) -> list[tuple[int, float]]:
        if self._faiss_index is not None:
            # 用 FAISS 直接搜出最相似的 top_k：返回相似度分数和对应的行号(索引)。
            scores, indices = self._faiss_index.search(query_vector, int(top_k))
            # 过滤掉无效行号(-1 表示没找到)，并把分数/行号配对。
            pairs = [(int(idx), float(score)) for idx, score in zip(indices[0], scores[0]) if int(idx) >= 0]
        else:
            # 没有 FAISS 时，用纯 numpy 手工算相似度。
            if self._vectors is None:
                return []
            # 向量都已归一化，矩阵乘以查询向量即得到每个块与查询的相似度(点积=余弦)。
            sims = self._vectors @ query_vector[0]
            # 实际能取的数量不能超过库里块的总数。
            k = min(int(top_k), sims.shape[0])
            if k <= 0:
                pairs = []
            else:
                # argpartition 取最大的 k 个（O(n)），再对这 k 个排序（O(k log k)），
                # 整体 O(n + k log k)，优于对全部 n 个 argsort 的 O(n log n)。
                part = np.argpartition(-sims, k - 1)[:k]
                top_indices = part[np.argsort(-sims[part])]
                pairs = [(int(idx), float(sims[idx])) for idx in top_indices]

        return pairs

    def _retrieve_bm25(self, query: str, top_k: int) -> list[tuple[int, float]]:
        payload = self._bm25_payload or {}
        postings = payload.get("postings") or {}
        doc_lengths = [int(value) for value in payload.get("doc_lengths") or []]
        num_docs = int(payload.get("num_docs") or len(doc_lengths))
        avg_doc_length = float(payload.get("avg_doc_length") or 1.0)
        k1 = float(payload.get("k1") or 1.5)
        b = float(payload.get("b") or 0.75)
        scores: dict[int, float] = {}
        query_terms = set(re.findall(r"[A-Za-z0-9]+", (query or "").casefold()))
        for term in query_terms:
            term_postings = postings.get(term) or []
            document_frequency = len(term_postings)
            if not document_frequency:
                continue
            idf = math.log(1.0 + (num_docs - document_frequency + 0.5) / (document_frequency + 0.5))
            for doc_index, term_frequency in term_postings:
                idx = int(doc_index)
                tf = float(term_frequency)
                length = doc_lengths[idx] if idx < len(doc_lengths) else avg_doc_length
                denominator = tf + k1 * (1.0 - b + b * length / max(avg_doc_length, 1e-12))
                scores[idx] = scores.get(idx, 0.0) + idf * (tf * (k1 + 1.0)) / denominator
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [(idx, float(score)) for idx, score in ranked[: max(0, int(top_k))]]


class HybridRagRetriever:
    """BGE dense + BM25 + RRF + BGE cross-encoder reranker。"""

    retriever_backend = "hybrid"

    def __init__(
        self,
        dense_index_dir: str | Path,
        bm25_index_dir: str | Path,
        *,
        dense_candidate_top_k: int = 20,
        bm25_candidate_top_k: int = 20,
        rrf_k: int = 60,
        fusion_top_k: int = 20,
        final_top_k: int = 5,
        reranker_model: str = "BAAI/bge-reranker-base",
        reranker_revision: str | None = None,
        reranker_local_files_only: bool = False,
        reranker: Any | None = None,
    ):
        self.dense = RagRetriever(dense_index_dir)
        self.bm25 = RagRetriever(bm25_index_dir)
        if self.dense.retriever_backend != "dense":
            raise RuntimeError("Hybrid dense_index_dir does not contain a dense index")
        if self.bm25.retriever_backend != "bm25":
            raise RuntimeError("Hybrid bm25_index_dir does not contain a BM25 index")
        dense_docstore_hash = str(self.dense.manifest.get("docstore_hash") or "")
        bm25_docstore_hash = str(self.bm25.manifest.get("docstore_hash") or "")
        if dense_docstore_hash != bm25_docstore_hash:
            raise RuntimeError(
                "Hybrid indexes must share an identical token-aware docstore"
            )
        self.dense_candidate_top_k = int(dense_candidate_top_k)
        self.bm25_candidate_top_k = int(bm25_candidate_top_k)
        self.rrf_k = int(rrf_k)
        self.fusion_top_k = int(fusion_top_k)
        self.final_top_k = int(final_top_k)
        if min(
            self.dense_candidate_top_k,
            self.bm25_candidate_top_k,
            self.rrf_k,
            self.fusion_top_k,
            self.final_top_k,
        ) <= 0:
            raise ValueError("Hybrid retrieval parameters must all be positive")
        self.reranker_model = str(reranker_model)
        self.reranker_revision = reranker_revision
        if reranker is None:
            enforce_hf_offline(bool(reranker_local_files_only))
            reranker_source = resolve_hf_model_source(
                self.reranker_model,
                revision=self.reranker_revision,
                local_files_only=bool(reranker_local_files_only),
            )
            from sentence_transformers import CrossEncoder

            reranker = CrossEncoder(
                reranker_source,
                revision=(
                    None
                    if reranker_source != self.reranker_model
                    else self.reranker_revision
                ),
                local_files_only=bool(reranker_local_files_only),
            )
        self.reranker = reranker
        dense_id = str(self.dense.manifest.get("retriever_id") or "dense")
        self.manifest = {
            "retriever_backend": "hybrid",
            "retriever_id": f"{dense_id}+bm25+rrf+bge-reranker",
            "dense_retriever_id": dense_id,
            "dense_embedding_revision": self.dense.manifest.get(
                "embedding_revision"
            ),
            "sparse_retriever_id": str(
                self.bm25.manifest.get("retriever_id") or "bm25"
            ),
            "reranker_model": self.reranker_model,
            "reranker_revision": self.reranker_revision,
            "dense_candidate_top_k": self.dense_candidate_top_k,
            "bm25_candidate_top_k": self.bm25_candidate_top_k,
            "rrf_k": self.rrf_k,
            "fusion_top_k": self.fusion_top_k,
            "final_top_k": self.final_top_k,
            "dense_index_manifest_hash": sha256_obj(self.dense.manifest),
            "bm25_index_manifest_hash": sha256_obj(self.bm25.manifest),
        }
        self.index_manifest_hash = sha256_obj(self.manifest)

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        """执行两路召回、RRF 融合、交叉编码器重排。"""

        dense_rows = self.dense.retrieve(query, top_k=self.dense_candidate_top_k)
        bm25_rows = self.bm25.retrieve(query, top_k=self.bm25_candidate_top_k)
        candidates: dict[str, dict[str, Any]] = {}
        for stage, rows in (("dense", dense_rows), ("bm25", bm25_rows)):
            for rank, row in enumerate(rows, start=1):
                state = candidates.setdefault(
                    row.chunk_id,
                    {
                        "chunk": row,
                        "rrf_score": 0.0,
                        "dense_score": None,
                        "bm25_score": None,
                        "dense_rank": None,
                        "bm25_rank": None,
                    },
                )
                state["rrf_score"] += 1.0 / (self.rrf_k + rank)
                state[f"{stage}_score"] = row.score
                state[f"{stage}_rank"] = rank
        fused = sorted(
            candidates.values(),
            key=lambda row: (
                -float(row["rrf_score"]),
                str(row["chunk"].chunk_id),
            ),
        )[: self.fusion_top_k]
        if not fused:
            return []
        reranker_scores = self.reranker.predict(
            [[query, state["chunk"].text] for state in fused]
        )
        reranked: list[RetrievedChunk] = []
        for state, reranker_score in zip(fused, reranker_scores):
            chunk = state["chunk"]
            stage_scores = {
                "dense_score": state["dense_score"],
                "dense_rank": state["dense_rank"],
                "bm25_score": state["bm25_score"],
                "bm25_rank": state["bm25_rank"],
                "rrf_score": float(state["rrf_score"]),
                "reranker_score": float(reranker_score),
            }
            reranked.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    score=float(reranker_score),
                    metadata={
                        **chunk.metadata,
                        "retrieval_stage_scores": stage_scores,
                    },
                )
            )
        reranked.sort(key=lambda row: (-row.score, row.chunk_id))
        requested_top_k = self.final_top_k if top_k is None else int(top_k)
        return reranked[: min(requested_top_k, self.final_top_k)]
