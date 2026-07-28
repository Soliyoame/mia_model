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
    parser.add_argument("--retriever-backend", choices=["dense", "bm25"], default=None)
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
    index_dir = ensure_dir(resolve_path(config["paths"]["indexes_dir"]) / args.dataset / retriever_backend)
    manifest = build_rag_index(
        dataset=args.dataset,
        # 只喂 kb_member.jsonl:知识库里只有成员,这是成员推理攻击的前提。
        kb_member_path=split_dir / "kb_member.jsonl",
        output_dir=index_dir,
        embedding_model=str(config["embedding"].get("model", DEFAULT_EMBEDDING_MODEL)),
        embedding_backend=str(config["embedding"].get("backend", "auto")),
        embedding_local_files_only=bool(config["embedding"].get("local_files_only", False)),
        embedding_dim=int(config["embedding"].get("dim", 384)),
        # 切块参数:每块字符数与相邻块的重叠量。
        chunk_size=int(config["chunking"].get("chunk_size", 500)),
        chunk_overlap=int(config["chunking"].get("chunk_overlap", 50)),
        resume=not args.no_resume,
        force=args.force,
        config_snapshot=config,
        retriever_backend=retriever_backend,
    )
    logger.info("Step 03 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
