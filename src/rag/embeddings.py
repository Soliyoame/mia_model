"""Embedding abstraction for RAG retrieval.

PCV-MIA retrieval metrics must be computed with a real embedding model. The
previous deterministic hashing fallback is intentionally unsupported so missing
dependencies or unavailable model files fail loudly instead of changing the
experiment semantics.

中文说明
========
本文件负责「文本 → 向量(embedding)」这一步，是整个 RAG 检索的地基。
- 什么是 embedding(向量)：把一段文字变成一串浮点数(例如 384 个数字)。语义相近
  的文字，它们的向量在空间里也"挨得近"。这样我们才能用数学(算距离/夹角)来衡量
  "用户的查询"和"知识库里的某段文字"到底有多像。
- 为什么禁用"哈希凑数"的假向量：过去有一种用哈希函数硬凑向量的省事做法
  (hashing fallback)。它算得快但毫无语义，会让检索结果失真、实验结论不可信。
  所以这里【故意不支持】它——一旦缺少真正的向量模型，就直接报错(fail loudly)，
  逼你去配置一个真实模型，而不是悄悄用假向量把实验跑"通"。
- 谁在用本文件：src/rag/index_builder.py(建索引时把每个文本块编码成向量)、
  src/rag/retriever.py(检索时把查询编码成向量再找最相似的块)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np


# 默认使用的句向量模型名(来自 HuggingFace 上的 sentence-transformers 系列)。
# all-MiniLM-L6-v2 是个又小又快、效果还不错的常用模型，输出 384 维向量。
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingModel(Protocol):
    """Minimal interface required by embedding backends.

    中文说明：这是一个"协议(Protocol)"，相当于一份接口契约/规格说明，而不是真正
    干活的类。它规定了：任何想当"向量模型"用的对象，都必须具备下面这些东西：
        name: 模型名字(字符串)。
        dim:  向量维度(整数，比如 384)。
        encode(texts): 把一批文本编码成向量矩阵。
    只要某个类满足这份契约，就能被本项目当作向量模型使用(这叫"鸭子类型")。
    """

    name: str
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray:
        # 输入一批文本，返回它们的向量(每行一个文本的向量)。这里只是声明签名，无实现。
        ...


@dataclass
class SentenceTransformerEmbeddingModel:
    """sentence-transformers backend.

    中文说明：用 sentence-transformers 这个第三方库来真正加载并运行向量模型，
    是上面 EmbeddingModel 契约的一个具体实现。
    """

    # 要加载的模型名称(来自 configs 配置或默认值)。
    model_name: str
    local_files_only: bool = False

    def __post_init__(self) -> None:
        """dataclass 初始化后自动调用：在这里真正把模型加载进内存。

        作用：
            - 延迟到此处才 import sentence_transformers，避免没装这个库时一导入
              本文件就崩溃(用到时才报错，更友好)。
            - 读取模型的向量维度并存到 self.dim。
        """
        # 仅在真正需要时才导入重型依赖(sentence-transformers)。
        from sentence_transformers import SentenceTransformer

        # 按名字下载/加载模型(第一次会联网下载，之后用本地缓存)。
        self._model = SentenceTransformer(
            self.model_name,
            local_files_only=self.local_files_only,
        )
        self.name = self.model_name
        # 询问模型它输出的向量是多少维。
        dim = self._model.get_sentence_embedding_dimension()
        # 拿不到维度时兜底用 768(很多 BERT 类模型的常见维度)。
        self.dim = int(dim) if dim else 768

    def encode(self, texts: list[str]) -> np.ndarray:
        """把一批文本编码成向量矩阵。

        参数:
            texts: 文本列表，例如多个文档块或一个查询。
        返回:
            形状为 (文本数, 维度) 的 float32 矩阵，每一行是一个文本的向量。
        """
        # normalize_embeddings=True：把每个向量缩放成单位长度(模为1)。这样之后用
        # "点积"就等价于"余弦相似度"，计算更简单。show_progress_bar 关掉进度条。
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        # 统一转成 float32 的 numpy 数组(省内存，且 FAISS 索引要求 float32)。
        return np.asarray(vectors, dtype="float32")


def build_embedding_model(
    model_name: str | None,
    backend: str = "auto",
    dim: int = 384,
    *,
    local_files_only: bool = False,
) -> EmbeddingModel:
    """Create the configured embedding model.

    ``dim`` is retained for backward-compatible call sites, but real embedding
    dimensions come from the loaded model. ``hashing`` is rejected explicitly to
    avoid accidental benchmark runs with the old fallback.

    中文说明：这是一个"工厂函数"——根据配置创建并返回一个向量模型对象。

    参数:
        model_name: 模型名字；传 None 时用默认模型 DEFAULT_EMBEDDING_MODEL。
        backend:    后端类型。"auto" / "sentence_transformers" 都表示用真实模型；
                    "hash" / "hashing" 会被直接拒绝(报错)。
        dim:        仅为兼容旧调用而保留，实际维度以加载的模型为准，这里不再使用。
    返回:
        一个满足 EmbeddingModel 契约的向量模型对象。
    异常:
        ValueError: 当试图使用被禁用的哈希后端，或后端名不被支持时抛出。
    """
    # 显式丢弃 dim：保留这个参数只是为了不破坏老的调用点，真实维度由模型决定。
    del dim
    # 没给模型名就用默认模型。
    model_name = model_name or DEFAULT_EMBEDDING_MODEL
    # 把后端名统一成小写，方便后面比较。
    normalized_backend = (backend or "auto").lower()
    # 守门：只要沾上"哈希假向量"，一律报错，杜绝用假向量跑实验。
    if normalized_backend in {"hash", "hashing"} or model_name.lower() == "hashing":
        raise ValueError("Hashing embedding is disabled. Configure a real sentence-transformers model.")
    # 这几种写法都表示"用 sentence-transformers 真实模型"。
    if normalized_backend in {"auto", "sentence_transformers", "sentence-transformer"}:
        return SentenceTransformerEmbeddingModel(model_name, local_files_only=local_files_only)
    # 其它后端名都不认识，报错提示。
    raise ValueError(f"Unsupported embedding backend: {backend}")


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """Compute cosine similarity for two one-dimensional vectors.

    中文说明：计算两个向量的"余弦相似度"——看它们方向有多接近，范围约 -1~1，
    越接近 1 表示两段文字语义越像。公式：点积 ÷ (左模长 × 右模长)。

    参数:
        left:  第一个一维向量。
        right: 第二个一维向量。
    返回:
        余弦相似度(float)；只要有一方是零向量，就返回 0.0(避免除以 0)。
    """
    # 分别求两个向量的模长(长度)。
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    # 任一向量长度约等于 0(零向量)时，相似度没有意义，直接返回 0，避免除零错误。
    if math.isclose(left_norm, 0.0) or math.isclose(right_norm, 0.0):
        return 0.0
    # 点积除以两者模长之积，就是余弦相似度。
    return float(np.dot(left, right) / (left_norm * right_norm))
