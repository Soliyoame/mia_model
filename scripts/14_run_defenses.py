"""14: 跑 PCV-MIA 防御实验骨架。

中文说明
========
本文件对应流水线第 14 步「防御实验」。读入第 11 步产出的 PCV 分数,交给
`src.defenses.runner.run_defense_experiments`,在不同防御设定下重新评估攻击效果,
看防御措施能把攻击的检出能力压低到什么程度,产出 `{dataset}_defense_results.json`。
目前是实验骨架,把接口和输出结构先搭好、日后逐步填实防御策略。

本脚本只负责读配置、设种子、拼输出路径并把判定阈值 threshold 传进去。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.defenses.runner import run_defense_experiments
from src.llm.generator_registry import resolve_generator_from_pipeline_config
from src.rag.paths import retriever_id_from_config
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.run_context import experiment_scoped_dir
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、force、no_resume。
    """
    parser = argparse.ArgumentParser(description="Run PCV-MIA defense experiments.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "defense_config.yaml"))
    parser.add_argument("--rag-config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--retriever-backend", choices=["dense", "bm25", "hybrid"], default=None)
    parser.add_argument("--generator-family", choices=["gemini", "qwen", "gpt", "llama"], default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """脚本入口:在各防御设定下重评攻击效果并写盘。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    rag_config = load_yaml(args.rag_config)
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
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    out_dir = ensure_dir(
        experiment_scoped_dir(config["paths"]["defenses_dir"], args.dataset, **scope)
    )
    report = run_defense_experiments(
        dataset=args.dataset,
        queries_path=resolve_path(config["paths"]["queries_dir"]) / f"{args.dataset}_paired_queries.jsonl",
        rag_responses_path=experiment_scoped_dir(
            config["paths"]["rag_responses_dir"], args.dataset, **scope
        ) / f"{args.dataset}_rag_responses.jsonl",
        benchmark_path=resolve_path(rag_config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        reserve_roles_path=resolve_path(config["paths"]["reserve_roles_dir"]) / f"{args.dataset}_reserve_roles.json",
        facts_path=resolve_path(rag_config["paths"]["facts_dir"]) / f"{args.dataset}_facts.jsonl",
        output_path=out_dir / f"{args.dataset}_defense_results.json",
        # 判定成员/非成员的阈值,默认 0.5。
        threshold=float(config.get("defense", {}).get("threshold", 0.5)),
        score_key=str(config.get("defense", {}).get("score_key", "pcv_score")),
        bootstrap=int(config.get("defense", {}).get("bootstrap", 2000)),
        seed=int(config.get("defense", {}).get("seed", 42)),
        conformal_alphas=[
            float(value)
            for value in config.get("defense", {}).get("conformal_alphas", [0.01, 0.05])
        ],
        policies=[
            str(name)
            for name, enabled in config.get("defense", {}).get("policies", {}).items()
            if enabled
        ],
        resume=not args.no_resume,
        force=args.force,
        # 整份配置作为快照写进结果,便于复现。
        config_snapshot=config,
    )
    logger.info("Step 14 finished: %s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
