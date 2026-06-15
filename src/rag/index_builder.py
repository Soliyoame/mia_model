"""RAG 知识库构建模块。

安全边界非常重要：本模块只接受 KB_Member split 作为输入，并在写入 docstore 前
再次校验 group 字段。True_Non_Member、Spoof_Seed、Spoofed_Non_Member、Reserve
都不能从这里进入向量库。

中文说明
========
本文件对应流水线第 03 步「建 RAG 索引」。它把"成员文档"切成小块、编码成向量、
存成一个可检索的索引库(docstore + 向量索引 + manifest 清单)。
- 为什么强调安全边界：本项目的目标是判断"某文档是否在知识库里"。如果不小心把
  非成员文档也放进了索引，整个实验就被污染、结论作废。所以这里反复校验：只有
  group == "KB_Member" 的文档才允许进库，发现别的分组立刻报错。
- 名词：chunk(文本块)=把长文档切成的小段；docstore=所有文本块的清单；
  manifest=记录"这个索引是怎么建的"的元信息(模型、参数、各种 hash)。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    # tqdm 用来显示进度条；没装就用一个"什么都不做"的替身，保证不影响主流程。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

import numpy as np

from .embeddings import DEFAULT_EMBEDDING_MODEL, build_embedding_model
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import ensure_dir, read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def chunk_for_rag(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """按 token 粗略切 chunk。

    这里不用复杂 tokenizer，是为了让框架不绑定某个 LLM。正式实验可以把这里替换成
    目标 generator 对应 tokenizer，但输出格式和 manifest 不需要变化。

    中文说明：把一段长文本切成若干"小块"，便于建索引和检索。这里图简单，直接按
    "空格分词"把文本拆成词，再按固定窗口大小滑动切块。相邻块之间会重叠一部分
    (overlap)，避免把一句话从中间切断、导致语义丢失。

    参数:
        text:          要切分的原始文本。
        chunk_size:    每块最多多少个"词"(近似当作 token)。
        chunk_overlap: 相邻两块重叠多少个词，用于保留上下文连贯性。
    返回:
        切好的文本块列表；空文本返回空列表。
    """
    # 按空白把文本拆成词列表；text 为 None 时用空串兜底，避免报错。
    words = (text or "").split()
    # 没有任何词，直接返回空列表。
    if not words:
        return []
    # 词数没超过一块的容量，那整段就是一块。
    if len(words) <= chunk_size:
        return [" ".join(words)]
    # 每次窗口前进的步长 = 块大小 - 重叠量；至少前进 1，防止死循环。
    step = max(1, chunk_size - chunk_overlap)
    chunks = []
    # 从头开始，每隔 step 个词取一个长度为 chunk_size 的窗口作为一块。
    for start in range(0, len(words), step):
        part = words[start : start + chunk_size]
        # 取空了说明到末尾了，结束。
        if not part:
            break
        chunks.append(" ".join(part))
        # 这一块已经覆盖到文本结尾，就不用再往后切了。
        if start + chunk_size >= len(words):
            break
    return chunks


def _write_index(index_path: Path, vectors: np.ndarray) -> str:
    """写入向量索引，优先 FAISS，失败则写 JSON fallback。

    中文说明：把所有文本块的向量保存成可检索的索引文件。

    参数:
        index_path: 索引文件要写到的路径(如 .../faiss.index)。
        vectors:    形状 (块数, 维度) 的向量矩阵。
    返回:
        实际使用的后端名字字符串："faiss.IndexFlatIP" 或 "json_vector_fallback"。
    """
    try:
        import faiss  # type: ignore

        # IndexFlatIP：用"内积(Inner Product)"做相似度的最简单 FAISS 索引；因为向量
        # 已归一化，内积等价于余弦相似度。
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors.astype("float32"))
        faiss.write_index(index, str(index_path))
        return "faiss.IndexFlatIP"
    except Exception as exc:
        # 没装 FAISS 或写入失败时，退而求其次：把向量直接存成 JSON。
        LOGGER.warning("FAISS unavailable, using JSON vector fallback: %s", exc)
        payload = {
            "backend": "json_vector_fallback",
            "shape": list(vectors.shape),
            "vectors": vectors.astype("float32").tolist(),
        }
        # 原子写：先写临时文件再 rename，避免大向量序列化中途崩溃留下半截的损坏索引
        # （resume 只检查文件是否存在，损坏文件会被误当成可用索引）。
        tmp_path = index_path.parent / (index_path.name + ".tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(index_path)
        return "json_vector_fallback"


def build_rag_index(
    dataset: str,
    kb_member_path: str | Path,
    output_dir: str | Path,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    embedding_backend: str = "auto",
    embedding_dim: int = 384,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    resume: bool = True,
    force: bool = False,
    config_snapshot: dict[str, Any] | None = None,
    allowed_group: str = "KB_Member",
) -> dict[str, Any]:
    """构建 RAG index（默认只允许 KB_Member；L2 shadow 模式可指定 Reserve）。

    中文说明：本函数是第 03 步的主入口。流程是：读入文档 → 严格校验它们的 group
    都等于 allowed_group → 逐篇切块 → 把所有块编码成向量 → 写索引、docstore、manifest。

    安全边界：主知识库 allowed_group 固定为 "KB_Member"（成员推理的前提，绝不能松动）。
    唯一的例外是 L2 的 shadow 索引——它用 Reserve（同分布、非成员、与评估组 source 互斥）
    构建，用来估计"非成员零分布"，因此调用方需显式传 allowed_group="Reserve"。shadow
    索引绝不参与"判定某文档是否成员"的 victim 检索，只服务于 per-example 先验校准。

    参数:
        dataset:           数据集名字(如 "enron")，仅用于记录与日志。
        kb_member_path:    要建索引的文档 jsonl 路径(主库=KB_Member；shadow=Reserve 子集)。
        output_dir:        索引输出目录。
        embedding_model:   使用的向量模型名。
        embedding_backend: 向量后端("auto" 表示自动选真实模型)。
        embedding_dim:     兼容用的维度参数(实际维度以模型为准)。
        chunk_size:        切块大小(词数)。
        chunk_overlap:     相邻块重叠词数。
        resume:            为 True 时，若索引已存在则跳过(断点续跑)。
        force:             为 True 时强制重建，忽略已存在的结果。
        config_snapshot:   本次运行的配置快照，写进 manifest 便于复现实验。
        allowed_group:     唯一允许入库的 group(默认 "KB_Member"；L2 shadow 传 "Reserve")。
    返回:
        manifest(字典)：记录本次建库的全部元信息；若跳过则返回带 skipped_existing 的字典。
    异常:
        RuntimeError: 当输入混入了非 allowed_group 文档、或没切出任何块时抛出。
    """
    # 确保输出目录存在(不存在则创建)。
    out_dir = ensure_dir(output_dir)
    index_path = out_dir / "faiss.index"
    docstore_path = out_dir / "docstore.jsonl"
    manifest_path = out_dir / "index_manifest.json"
    # 断点续跑：开启 resume、未强制 force，且三个产物文件都在，就直接跳过不重建。
    if resume and not force and index_path.exists() and docstore_path.exists() and manifest_path.exists():
        LOGGER.info("Skipping existing RAG index for %s: %s", dataset, out_dir)
        return {"dataset": dataset, "output_dir": str(out_dir), "skipped_existing": True}

    rows = list(read_jsonl(kb_member_path))
    # 安全闸门：只要发现任何一条 group 不等于 allowed_group，立即报错。
    # 主库 allowed_group="KB_Member"，绝不让非成员污染；shadow 显式传 "Reserve"。
    if any(row.get("group") != allowed_group for row in rows):
        # 挑出前 5 条违规文档的 id 放进报错信息，方便定位问题。
        bad = [row.get("doc_id") for row in rows if row.get("group") != allowed_group][:5]
        raise RuntimeError(f"RAG index can only be built from {allowed_group}. Bad rows: {bad}")

    docstore: list[dict[str, Any]] = []
    # 逐篇文档切块，并为每个块构造一条记录存进 docstore。
    for row in tqdm(rows, desc=f"chunk index {dataset}", unit="doc"):
        # 优先用 doc_id，没有就退而用 sample_id 作为文档标识。
        doc_id = str(row.get("doc_id") or row.get("sample_id"))
        for chunk_idx, chunk in enumerate(chunk_for_rag(row["text"], chunk_size=chunk_size, chunk_overlap=chunk_overlap)):
            docstore.append(
                {
                    # 块编号 = 文档id + "_c" + 两位序号，保证全局唯一。
                    "chunk_id": f"{doc_id}_c{chunk_idx:02d}",
                    "doc_id": doc_id,
                    "dataset": dataset,
                    "group": allowed_group,
                    "text": chunk,
                    # 记录文本 hash，便于校验与追踪。
                    "text_hash": sha256_text(chunk),
                    "metadata": {
                        "chunk_index": chunk_idx,
                        "source_doc_id": doc_id,
                        "source_text_hash": row.get("text_hash"),
                    },
                }
            )

    # 一个块都没切出来，说明输入有问题，直接报错。
    if not docstore:
        raise RuntimeError(f"No chunks were generated for {dataset}: {kb_member_path}")

    # 创建向量模型，并把每个块的文本批量编码成向量矩阵。
    embedder = build_embedding_model(embedding_model, backend=embedding_backend, dim=embedding_dim)
    vectors = embedder.encode([row["text"] for row in tqdm(docstore, desc=f"embed {dataset}", unit="chunk")])
    # 写向量索引(faiss 或 json 兜底)，拿到实际使用的后端名。
    backend = _write_index(index_path, vectors)
    # 写 docstore(所有块的清单)。
    write_jsonl(docstore, docstore_path)
    # 记录创建时间(UTC，带时区)。
    created_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "dataset": dataset,
        "embedding_model": embedder.name,
        "requested_embedding_model": embedding_model,
        "embedding_backend": backend,
        "embedding_dim": int(vectors.shape[1]),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "num_docs": len(rows),
        "num_chunks": len(docstore),
        # 对关键文件算 hash，写进 manifest，用于实验复现与完整性校验。
        "kb_hash": sha256_file(kb_member_path),
        "docstore_hash": sha256_file(docstore_path),
        "index_hash": sha256_file(index_path),
        "created_at": created_at,
        "config_hash": sha256_obj(config_snapshot or {}),
        "config_snapshot": config_snapshot or {},
        # 把"安全边界"也写进 manifest，明确声明只允许哪个 group。
        "security_boundary": {
            "allowed_groups": [allowed_group],
            "forbidden_groups": [g for g in ["KB_Member", "True_Non_Member", "Spoof_Seed", "Spoofed_Non_Member", "Reserve"] if g != allowed_group],
            "is_shadow_index": allowed_group != "KB_Member",
        },
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Built RAG index for %s: docs=%s chunks=%s backend=%s", dataset, len(rows), len(docstore), backend)
    return manifest
