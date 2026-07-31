"""13: 生成 PCV-MIA 机理分析报告。

中文说明
========
本文件对应流水线第 13 步「机理分析」。它把前面各阶段的中间结果(配对查询、RAG 回答、
解析后的立场、PCV 分数,以及索引里的 docstore)一并喂给
`src.evaluation.mechanism_analysis.run_mechanism_analysis`,从"为什么这个攻击能奏效"
的角度做拆解分析,产出 `{dataset}_mechanism_report.json`,供最后出报告时引用。

本脚本只负责装配输入输出路径、配好日志,真正的统计与归因逻辑都在 evaluation 模块里。
注意这一步不走配置文件,各路径直接按约定目录拼出。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.mechanism_analysis import run_mechanism_analysis
from src.llm.generator_registry import resolve_generator_from_pipeline_config
from src.rag.paths import retriever_id_from_config, retriever_index_dir
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.logger import setup_logging
from src.utils.run_context import experiment_scoped_dir


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、force、no_resume。
    """
    parser = argparse.ArgumentParser(description="Run PCV-MIA mechanism analysis.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--rag-config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--attack-config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--retriever-backend", choices=["dense", "bm25", "hybrid"], default=None)
    parser.add_argument("--generator-family", choices=["gemini", "qwen", "gpt", "llama"], default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """脚本入口:汇总各阶段中间结果做机理分析并写盘。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    rag_config = load_yaml(args.rag_config)
    attack_config = load_yaml(args.attack_config)
    retriever_backend = args.retriever_backend or str(
        rag_config.get("retrieval", {}).get("backend", "dense")
    )
    generator_identity, _ = resolve_generator_from_pipeline_config(
        rag_config,
        family=args.generator_family,
    )
    scope = {
        "generator_family": generator_identity.generator_family,
        "concrete_model": generator_identity.concrete_model,
        "retriever_id": retriever_id_from_config(rag_config, retriever_backend),
    }
    logger = setup_logging("pcv_mia", log_file=resolve_path("artifacts/v20/logs/mechanism.log"), level="INFO")
    out_dir = ensure_dir(
        experiment_scoped_dir("artifacts/v20/mechanisms", args.dataset, **scope)
    )
    docstore_backend = "dense" if retriever_backend == "hybrid" else retriever_backend
    report = run_mechanism_analysis(
        dataset=args.dataset,
        queries_path=resolve_path(attack_config["paths"]["stealth_filtered_queries_dir"]) / f"{args.dataset}_paired_queries.jsonl",
        rag_responses_path=experiment_scoped_dir(rag_config["paths"]["rag_responses_dir"], args.dataset, **scope) / f"{args.dataset}_rag_responses.jsonl",
        parsed_path=experiment_scoped_dir(attack_config["paths"]["parsed_stance_dir"], args.dataset, **scope) / f"{args.dataset}_parsed_stance.jsonl",
        scores_path=experiment_scoped_dir(attack_config["paths"]["scores_dir"], args.dataset, **scope) / f"{args.dataset}_pcv_scores.jsonl",
        docstore_path=retriever_index_dir(rag_config, args.dataset, docstore_backend) / "docstore.jsonl",
        output_path=out_dir / f"{args.dataset}_mechanism_report.json",
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info("Step 13 finished: %s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
