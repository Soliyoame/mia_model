"""03: 只用 KB_Member 构建 RAG 知识库。

中文说明
========
本文件对应流水线第 3 步:仅用第 2 步切出的 KB_Member 子集构建 RAG 检索索引(只放成员,
非成员绝不入库,这是 MIA 设定的关键)。切块/向量化/建索引的实现在 src.rag.index_builder,
这里只做命令行入口:读 rag_config.yaml,按配置选 embedding 模型/后端/维度与切块参数,
调用 build_rag_index,把索引文件与 index manifest 写到 indexes_dir/<dataset> 下。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.embeddings import DEFAULT_EMBEDDING_MODEL
from src.rag.index_builder import build_rag_index
from src.rag.paths import retriever_index_dir
from src.utils.dataset_paths import resolve_dataset_dir
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、force、no_resume 等字段。
    """
    parser = argparse.ArgumentParser(description="Build RAG index from KB_Member only.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--retriever-backend", choices=["dense", "bm25", "hybrid"], default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """流水线第 3 步入口:仅用 KB_Member 构建 RAG 索引。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    split_dir = resolve_dataset_dir(config, "splits_dir", args.dataset)
    retriever_backend = args.retriever_backend or str(config.get("retrieval", {}).get("backend", "dense"))
    backends = ("dense", "bm25") if retriever_backend == "hybrid" else (retriever_backend,)
    manifests = {}
    for backend in backends:
        index_dir = ensure_dir(retriever_index_dir(config, args.dataset, backend))
        manifests[backend] = build_rag_index(
            dataset=args.dataset,
            # 只喂 kb_member.jsonl:知识库里只有成员,这是成员推理攻击的前提。
            kb_member_path=split_dir / "kb_member.jsonl",
            output_dir=index_dir,
            embedding_model=str(config["embedding"].get("model", DEFAULT_EMBEDDING_MODEL)),
            embedding_backend=str(config["embedding"].get("backend", "auto")),
            embedding_local_files_only=bool(config["embedding"].get("local_files_only", False)),
            embedding_revision=config["embedding"].get("revision"),
            query_instruction=str(config["embedding"].get("query_instruction", "")),
            embedding_dim=int(config["embedding"].get("dim", 384)),
            # v20 正式索引按 BGE tokenizer 的真实 token 数切块。
            chunk_size=int(config["chunking"].get("chunk_size", 500)),
            chunk_overlap=int(config["chunking"].get("chunk_overlap", 50)),
            chunking_unit=str(config["chunking"].get("unit", "tokens")),
            tokenizer_model=str(
                config["chunking"].get("tokenizer_model")
                or config["embedding"].get("model", DEFAULT_EMBEDDING_MODEL)
            ),
            tokenizer_revision=(
                config["chunking"].get("tokenizer_revision")
                or config["embedding"].get("revision")
            ),
            tokenizer_local_files_only=bool(
                config["chunking"].get(
                    "tokenizer_local_files_only",
                    config["embedding"].get("local_files_only", False),
                )
            ),
            resume=not args.no_resume,
            force=args.force,
            config_snapshot=config,
            retriever_backend=backend,
        )
    logger.info("Step 03 finished: %s", manifests)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
