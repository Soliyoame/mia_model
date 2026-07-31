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
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    # tqdm 用来显示进度条；没装就用一个"什么都不做"的替身，保证不影响主流程。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

import numpy as np

from .embeddings import (
    DEFAULT_BGE_QUERY_INSTRUCTION,
    DEFAULT_EMBEDDING_MODEL,
    build_embedding_model,
)
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import ensure_dir, read_json, read_jsonl, write_json, write_jsonl
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


def chunk_for_rag_tokens(
    text: str,
    tokenizer: Any,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """使用冻结 retriever tokenizer 按真实 token 滑窗切块。"""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must satisfy 0 <= overlap < chunk_size")
    token_ids = list(tokenizer.encode(text or "", add_special_tokens=False))
    if not token_ids:
        return []
    step = chunk_size - chunk_overlap
    chunks: list[str] = []
    for start in range(0, len(token_ids), step):
        token_window = token_ids[start : start + chunk_size]
        if not token_window:
            break
        chunk = str(
            tokenizer.decode(
                token_window,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
        ).strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(token_ids):
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


def _bm25_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", (text or "").casefold())


def _write_bm25_index(index_path: Path, docstore: list[dict[str, Any]]) -> str:
    """Write a deterministic inverted BM25 index without external services."""

    postings: dict[str, list[list[int]]] = defaultdict(list)
    doc_lengths: list[int] = []
    for doc_index, row in enumerate(docstore):
        counts = Counter(_bm25_tokens(str(row.get("text") or "")))
        doc_lengths.append(sum(counts.values()))
        for term, frequency in sorted(counts.items()):
            postings[term].append([doc_index, int(frequency)])
    payload = {
        "backend": "bm25",
        "version": "bm25_v1",
        "k1": 1.5,
        "b": 0.75,
        "num_docs": len(docstore),
        "avg_doc_length": sum(doc_lengths) / max(1, len(doc_lengths)),
        "doc_lengths": doc_lengths,
        "postings": dict(sorted(postings.items())),
    }
    tmp_path = index_path.parent / (index_path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(index_path)
    return "bm25_inverted_index_v1"


def build_rag_index(
    dataset: str,
    kb_member_path: str | Path,
    output_dir: str | Path,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    embedding_backend: str = "auto",
    embedding_local_files_only: bool = False,
    embedding_dim: int = 384,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    resume: bool = True,
    force: bool = False,
    config_snapshot: dict[str, Any] | None = None,
    allowed_group: str = "KB_Member",
    retriever_backend: str = "dense",
    embedding_revision: str | None = None,
    query_instruction: str = DEFAULT_BGE_QUERY_INSTRUCTION,
    chunking_unit: str = "words",
    tokenizer_model: str | None = None,
    tokenizer_revision: str | None = None,
    tokenizer_local_files_only: bool | None = None,
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
    if allowed_group != "KB_Member" and any(
        part.casefold() == "indexes" for part in out_dir.parts
    ):
        raise RuntimeError(
            f"{allowed_group} dev/shadow data cannot be written under a formal 'indexes' directory: "
            f"{out_dir}"
        )
    backend_name = str(retriever_backend or "dense").strip().lower()
    if backend_name in {"minilm", "vector", "faiss"}:
        backend_name = "dense"
    if backend_name not in {"dense", "bm25"}:
        raise ValueError(f"Unknown retriever_backend: {retriever_backend!r}")
    normalized_chunking_unit = str(chunking_unit or "words").strip().casefold()
    if normalized_chunking_unit not in {"words", "tokens"}:
        raise ValueError(f"Unknown chunking_unit: {chunking_unit!r}")
    if (
        allowed_group == "KB_Member"
        and backend_name == "dense"
        and "minilm" in str(embedding_model).casefold()
    ):
        raise ValueError(
            "MiniLM is retired from formal PCV-MIA indexes. "
            "Use BAAI/bge-base-en-v1.5 or archive the run as legacy."
        )
    index_path = out_dir / ("faiss.index" if backend_name == "dense" else "bm25.index.json")
    docstore_path = out_dir / "docstore.jsonl"
    manifest_path = out_dir / "index_manifest.json"
    kb_hash = sha256_file(kb_member_path)
    # 断点续跑只能复用协议完全一致的索引；否则必须显式 --force 重建。
    if resume and not force and index_path.exists() and docstore_path.exists() and manifest_path.exists():
        existing_manifest = read_json(manifest_path)
        expected_protocol = {
            "dataset": dataset,
            "retriever_backend": backend_name,
            "requested_embedding_model": embedding_model if backend_name == "dense" else None,
            "embedding_revision": embedding_revision if backend_name == "dense" else None,
            "chunk_size": int(chunk_size),
            "chunk_overlap": int(chunk_overlap),
            "chunking_unit": normalized_chunking_unit,
            "tokenizer_model": (
                str(tokenizer_model or embedding_model)
                if normalized_chunking_unit == "tokens"
                else None
            ),
            "tokenizer_revision": (
                tokenizer_revision or embedding_revision
                if normalized_chunking_unit == "tokens"
                else None
            ),
            "kb_hash": kb_hash,
        }
        mismatches = {
            key: {"expected": expected, "actual": existing_manifest.get(key)}
            for key, expected in expected_protocol.items()
            if existing_manifest.get(key) != expected
        }
        actual_allowed = (
            existing_manifest.get("security_boundary", {}).get("allowed_groups") or []
        )
        if actual_allowed != [allowed_group]:
            mismatches["allowed_groups"] = {
                "expected": [allowed_group],
                "actual": actual_allowed,
            }
        for artifact_name, artifact_path, manifest_key in (
            ("docstore", docstore_path, "docstore_hash"),
            ("index", index_path, "index_hash"),
        ):
            expected_hash = str(existing_manifest.get(manifest_key) or "")
            actual_hash = sha256_file(artifact_path)
            if not expected_hash or actual_hash != expected_hash:
                mismatches[f"{artifact_name}_hash"] = {
                    "expected": expected_hash or None,
                    "actual": actual_hash,
                }
        if mismatches:
            raise RuntimeError(
                f"Existing {dataset}/{backend_name} index protocol does not match the requested run: "
                f"{mismatches}. Rebuild Step 03 with --force."
            )
        LOGGER.info("Skipping existing RAG index for %s: %s", dataset, out_dir)
        return {
            **existing_manifest,
            "output_dir": str(out_dir),
            "skipped_existing": True,
        }

    rows = list(read_jsonl(kb_member_path))
    # 安全闸门：只要发现任何一条 group 不等于 allowed_group，立即报错。
    # 主库 allowed_group="KB_Member"，绝不让非成员污染；shadow 显式传 "Reserve"。
    if any(row.get("group") != allowed_group for row in rows):
        # 挑出前 5 条违规文档的 id 放进报错信息，方便定位问题。
        bad = [row.get("doc_id") for row in rows if row.get("group") != allowed_group][:5]
        raise RuntimeError(f"RAG index can only be built from {allowed_group}. Bad rows: {bad}")

    embedder = None
    tokenizer = None
    if backend_name == "dense":
        embedder = build_embedding_model(
            embedding_model,
            backend=embedding_backend,
            dim=embedding_dim,
            local_files_only=bool(embedding_local_files_only),
            revision=embedding_revision,
            query_instruction=query_instruction,
        )
        tokenizer = getattr(embedder, "tokenizer", None)
    if normalized_chunking_unit == "tokens" and tokenizer is None:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_model or embedding_model,
            revision=tokenizer_revision or embedding_revision,
            local_files_only=(
                bool(embedding_local_files_only)
                if tokenizer_local_files_only is None
                else bool(tokenizer_local_files_only)
            ),
        )

    docstore: list[dict[str, Any]] = []
    # 逐篇文档切块，并为每个块构造一条记录存进 docstore。
    for row in tqdm(rows, desc=f"chunk index {dataset}", unit="doc"):
        # 优先用 doc_id，没有就退而用 sample_id 作为文档标识。
        doc_id = str(row.get("doc_id") or row.get("sample_id"))
        chunks = (
            chunk_for_rag_tokens(
                row["text"],
                tokenizer,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            if normalized_chunking_unit == "tokens"
            else chunk_for_rag(
                row["text"],
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        )
        for chunk_idx, chunk in enumerate(chunks):
            docstore.append(
                {
                    # 块编号 = 文档id + "_c" + 两位序号，保证全局唯一。
                    "chunk_id": f"{doc_id}_c{chunk_idx:02d}",
                    "doc_id": doc_id,
                    "dataset": dataset,
                    "group": allowed_group,
                    "source_id": row.get("source_id") or doc_id,
                    "source_key": row.get("source_key") or row.get("source_id") or doc_id,
                    "text": chunk,
                    # 记录文本 hash，便于校验与追踪。
                    "text_hash": sha256_text(chunk),
                    "metadata": {
                        "chunk_index": chunk_idx,
                        "source_doc_id": doc_id,
                        "source_id": row.get("source_id") or doc_id,
                        "source_key": row.get("source_key") or row.get("source_id") or doc_id,
                        "source_text_hash": row.get("text_hash"),
                    },
                }
            )

    # 一个块都没切出来，说明输入有问题，直接报错。
    if not docstore:
        raise RuntimeError(f"No chunks were generated for {dataset}: {kb_member_path}")

    embedder_name: str | None = None
    actual_embedding_dim: int | None = None
    if backend_name == "dense":
        assert embedder is not None
        encode_documents = getattr(embedder, "encode_documents", embedder.encode)
        vectors = encode_documents(
            [row["text"] for row in tqdm(docstore, desc=f"embed {dataset}", unit="chunk")]
        )
        storage_backend = _write_index(index_path, vectors)
        embedder_name = embedder.name
        actual_embedding_dim = int(vectors.shape[1])
        retriever_id = str(embedding_model)
        close = getattr(embedder, "close", None)
        if callable(close):
            close()
    else:
        storage_backend = _write_bm25_index(index_path, docstore)
        retriever_id = "bm25"
    # 写 docstore(所有块的清单)。
    write_jsonl(docstore, docstore_path)
    # 记录创建时间(UTC，带时区)。
    created_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "dataset": dataset,
        "retriever_backend": backend_name,
        "retriever_id": retriever_id,
        "index_filename": index_path.name,
        "embedding_model": embedder_name,
        "requested_embedding_model": embedding_model if backend_name == "dense" else None,
        "embedding_revision": embedding_revision if backend_name == "dense" else None,
        "query_instruction": query_instruction if backend_name == "dense" else None,
        "embedding_backend": storage_backend if backend_name == "dense" else None,
        "embedding_local_files_only": bool(embedding_local_files_only) if backend_name == "dense" else None,
        "embedding_dim": actual_embedding_dim,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "chunking_unit": normalized_chunking_unit,
        "tokenizer_model": (
            str(tokenizer_model or embedding_model)
            if normalized_chunking_unit == "tokens"
            else None
        ),
        "tokenizer_revision": (
            tokenizer_revision or embedding_revision
            if normalized_chunking_unit == "tokens"
            else None
        ),
        "num_docs": len(rows),
        "num_chunks": len(docstore),
        # 对关键文件算 hash，写进 manifest，用于实验复现与完整性校验。
        "kb_hash": kb_hash,
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
    LOGGER.info("Built RAG index for %s: docs=%s chunks=%s backend=%s", dataset, len(rows), len(docstore), backend_name)
    return manifest
