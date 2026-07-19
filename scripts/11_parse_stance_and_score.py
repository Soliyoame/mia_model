"""11: 解析回答立场并计算 PCV-MIA 分数。

中文说明
========
本文件对应流水线第 11 步:把第 10 步生成的两套回答(RAG 回答与纯 LLM 回答)做立场
解析,再据此算出每份文档的成员推理分数。分两步走:
1. `parse_stance_files` 读入配对查询、RAG 回答、纯 LLM 回答,逐条判断模型对每个核验
   断言的立场(支持/反对/未知/拒答),产出 `{dataset}_parsed_stance.jsonl`。
2. `compute_pcv_scores` 再把解析出的立场聚合成 PCV 分数,写出
   `{dataset}_pcv_scores.jsonl`,供后续 baseline 对照、机理分析、出报告使用。

本脚本只负责读配置、设种子、拼好输入输出路径并把打分超参(unknown_lambda、拒答惩罚、
误判惩罚、阈值列表等)传进去;真正的解析与打分逻辑在 src.parsing / src.scoring 里。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.parsing.stance_parser import parse_stance_files
from src.scoring.pcv_scorer import compute_pcv_scores
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.run_context import model_scoped_dir
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、force、no_resume。
    """
    parser = argparse.ArgumentParser(description="Parse PCV-MIA stances and compute scores.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument(
        "--skip-llm-only",
        action="store_true",
        help="Parse only RAG responses; canonical main runs use an independent matched control.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    """脚本入口:先做立场解析,再算 PCV 分数并写盘。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    parsed_dir = ensure_dir(model_scoped_dir(config["paths"]["parsed_stance_dir"], args.dataset))
    scores_dir = ensure_dir(model_scoped_dir(config["paths"]["scores_dir"], args.dataset))
    parsed_path = parsed_dir / f"{args.dataset}_parsed_stance.jsonl"
    # 第一步:解析两套回答的立场,产出 parsed_stance.jsonl。
    parse_manifest = parse_stance_files(
        dataset=args.dataset,
        queries_path=resolve_path(config["paths"]["stealth_filtered_queries_dir"]) / f"{args.dataset}_paired_queries.jsonl",
        rag_responses_path=model_scoped_dir("outputs/rag_responses", args.dataset) / f"{args.dataset}_rag_responses.jsonl",
        llm_responses_path=(
            None
            if args.skip_llm_only
            else model_scoped_dir("outputs/llm_only_responses", args.dataset)
            / f"{args.dataset}_llm_only_responses.jsonl"
        ),
        output_path=parsed_path,
        resume=not args.no_resume,
        force=args.force,
    )
    scoring = config.get("scoring", {})
    # 第二步:把立场聚合成 PCV 分数;打分超参从配置 scoring 段取,缺省给经验默认值。
    # facts_path 用于按 fact_id 取 quality_weight/selection_tier,启用方案 D 的质量加权聚合。
    score_manifest = compute_pcv_scores(
        dataset=args.dataset,
        parsed_stance_path=parsed_path,
        output_path=scores_dir / f"{args.dataset}_pcv_scores.jsonl",
        unknown_lambda=float(scoring.get("unknown_lambda", 0.5)),
        refusal_penalty=float(scoring.get("refusal_penalty", 0.5)),
        false_acceptance_penalty_value=float(scoring.get("false_acceptance_penalty", 0.0)),
        thresholds=[float(x) for x in scoring.get("thresholds", [0.3, 0.5, 0.7, 1.0])],
        facts_path=resolve_path(config["paths"]["facts_dir"]) / f"{args.dataset}_facts.jsonl",
        benchmark_path=resolve_path(config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        queries_path=resolve_path(config["paths"]["stealth_filtered_queries_dir"]) / f"{args.dataset}_paired_queries.jsonl",
        resume=not args.no_resume,
        force=args.force,
    )
    logger.info("Step 11 finished: parse=%s score=%s", parse_manifest, score_manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
