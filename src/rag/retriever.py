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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .embeddings import DEFAULT_EMBEDDING_MODEL, build_embedding_model
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
        # docstore(文档库)：所有文本块的列表，顺序与向量一一对应。
        self.docstore = list(read_jsonl(self.index_dir / "docstore.jsonl"))
        # 按建索引时用的同一个向量模型来创建编码器(检索和建库必须用同一模型)。
        self.embedder = build_embedding_model(
            str(self.manifest.get("requested_embedding_model") or self.manifest.get("embedding_model") or DEFAULT_EMBEDDING_MODEL),
            backend="auto",
            dim=int(self.manifest.get("embedding_dim", 384)),
        )
        # 记录后端类型(faiss 还是 json 兜底)，决定下面用哪种方式加载/检索。
        self.backend = str(self.manifest.get("embedding_backend", ""))
        self._faiss_index = None
        self._vectors: np.ndarray | None = None
        # 真正把向量索引加载进来。
        self._load_index()

    def _load_index(self) -> None:
        """加载向量索引：优先用 FAISS；FAISS 不可用时回退到 JSON 里的原始向量。"""
        index_path = self.index_dir / "faiss.index"
        # 如果建索引时用的是 FAISS，就尝试用 FAISS 读回来(检索更快)。
        if self.backend.startswith("faiss"):
            try:
                import faiss  # type: ignore

                self._faiss_index = faiss.read_index(str(index_path))
                return
            except Exception:
                # FAISS 读取失败就降级，继续走下面的 JSON 兜底分支。
                self._faiss_index = None
        # 兜底：索引文件其实是 JSON，里面直接存了所有向量，读出来转成 numpy 矩阵。
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        self._vectors = np.asarray(payload["vectors"], dtype="float32")

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """返回 top-k chunk。

        中文说明：把查询编码成向量，找出与之最相似的 top_k 个文本块并返回。

        参数:
            query: 用户查询文本。
            top_k: 返回多少个最相关的块，默认 5。
        返回:
            按相似度从高到低排好序的 RetrievedChunk 列表。
        """
        # 把查询文本编码成 (1, 维度) 的向量，类型转成 float32 以匹配索引。
        q = self.embedder.encode([query]).astype("float32")
        if self._faiss_index is not None:
            # 用 FAISS 直接搜出最相似的 top_k：返回相似度分数和对应的行号(索引)。
            scores, indices = self._faiss_index.search(q, int(top_k))
            # 过滤掉无效行号(-1 表示没找到)，并把分数/行号配对。
            pairs = [(int(idx), float(score)) for idx, score in zip(indices[0], scores[0]) if int(idx) >= 0]
        else:
            # 没有 FAISS 时，用纯 numpy 手工算相似度。
            if self._vectors is None:
                return []
            # 向量都已归一化，矩阵乘以查询向量即得到每个块与查询的相似度(点积=余弦)。
            sims = self._vectors @ q[0]
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
                    metadata=row.get("metadata", {}),
                )
            )
        return results
