"""v20 Retriever 身份与索引目录解析。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils.io import resolve_path
from ..utils.run_context import model_slug


def retriever_id_from_config(config: dict[str, Any], backend: str) -> str:
    """把逻辑 backend 解析为论文中使用的稳定 Retriever ID。"""

    backend_name = str(backend or "").strip().casefold()
    retrieval = config.get("retrieval") or {}
    configured = (retrieval.get("retriever_ids") or {}).get(backend_name)
    if configured:
        return str(configured)
    if backend_name == "dense":
        return str((config.get("embedding") or {}).get("model") or "")
    if backend_name == "bm25":
        return "bm25"
    if backend_name == "hybrid":
        return "bge+bm25+rrf+bge-reranker"
    if backend_name == "none":
        return "none"
    raise ValueError(f"Unknown retriever backend: {backend!r}")


def retriever_slug(config: dict[str, Any], backend: str) -> str:
    return model_slug(retriever_id_from_config(config, backend))


def retriever_index_dir(
    config: dict[str, Any],
    dataset: str,
    backend: str,
) -> Path:
    """返回 dense/BM25 的独立正式索引目录；hybrid 没有第三份索引。"""

    backend_name = str(backend or "").strip().casefold()
    if backend_name not in {"dense", "bm25"}:
        raise ValueError(f"{backend_name!r} has no standalone index directory")
    return (
        resolve_path(config["paths"]["indexes_dir"])
        / dataset
        / retriever_slug(config, backend_name)
    )
