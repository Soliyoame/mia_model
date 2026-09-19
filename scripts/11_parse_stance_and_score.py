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
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.parsing.stance_parser import parse_stance_files
from src.llm.generator_registry import resolve_generator_from_pipeline_config
from src.rag.paths import retriever_id_from_config
from src.scoring.pcv_scorer import compute_pcv_scores, run_hybrid_pvs_scoring
from src.utils.io import ensure_dir, load_yaml, resolve_path
from src.utils.run_context import experiment_scoped_dir
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,含 dataset、config、force、no_resume。
    """
    parser = argparse.ArgumentParser(description="Parse PCV-MIA stances and compute scores.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", help="经典或显式 V24 模式对应的评分配置")
    parser.add_argument("--v24-hybrid", action="store_true", help="仅运行 V24 stance + semantic restoration 离线评分")
    parser.add_argument("--pairs", help="V24 已选 pair JSONL 或现有 smoke_results.jsonl")
    parser.add_argument("--responses", help="单个 dataset/Generator/Retriever cell 的原始 RAG 回答 JSONL")
    parser.add_argument("--output-dir", help="V24 评分的新输出目录，不覆盖已有结果")
    parser.add_argument("--dry-run", action="store_true", help="V24 输入预检；不加载模型、不写分数")
    parser.add_argument("--rag-config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--retriever-backend", choices=["dense", "bm25", "hybrid"], default=None)
    parser.add_argument("--generator-family", choices=["gemini", "qwen", "gpt", "llama"], default=None)
    parser.add_argument(
        "--skip-llm-only",
        action="store_true",
        help="Parse only RAG responses; canonical main runs use an independent matched control.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    if args.v24_hybrid:
        if not args.pairs:
            parser.error("--v24-hybrid requires --pairs")
        if not args.dry_run and (not args.responses or not args.output_dir):
            parser.error("V24 scoring requires --responses and a new --output-dir, or --dry-run")
        if (args.force or args.no_resume or args.skip_llm_only or args.generator_family or args.retriever_backend
                or args.rag_config != str(PROJECT_ROOT / "configs" / "rag_config.yaml")):
            parser.error("V24 mode does not accept legacy override/resume flags; cell identity comes from responses")
        args.config = args.config or str(PROJECT_ROOT / "configs" / "restoration_first_v24.yaml")
    else:
        if args.pairs or args.responses or args.output_dir or args.dry_run:
            parser.error("--pairs/--responses/--output-dir/--dry-run require --v24-hybrid")
        args.config = args.config or str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml")
    return args


def main() -> int:
    """脚本入口:先做立场解析,再算 PCV 分数并写盘。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    if args.v24_hybrid:
        summary = run_hybrid_pvs_scoring(
            dataset=args.dataset, config_path=args.config, pairs_path=args.pairs,
            responses_path=args.responses, output_dir=args.output_dir,
            project_root=PROJECT_ROOT, dry_run=args.dry_run,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2 if summary["status"] == "incomplete" else 0
    config = load_yaml(args.config)
    if config.get("protocol_version") == "pcv-mia-v24" or config.get("scoring", {}).get("kind") == "stance_semantic_restoration":
        raise ValueError("V24 hybrid scoring requires explicit --v24-hybrid; legacy scoring is not a fallback")
    rag_config = load_yaml(args.rag_config)
    retriever_backend = args.retriever_backend or str(
        rag_config.get("retrieval", {}).get("backend", "dense")
    )
    generator_identity, _ = resolve_generator_from_pipeline_config(
        rag_config,
        family=args.generator_family,
    )
    retriever_id = retriever_id_from_config(rag_config, retriever_backend)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    scope = {
        "generator_family": generator_identity.generator_family,
        "concrete_model": generator_identity.concrete_model,
        "retriever_id": retriever_id,
    }
    parsed_dir = ensure_dir(
        experiment_scoped_dir(config["paths"]["parsed_stance_dir"], args.dataset, **scope)
    )
    scores_dir = ensure_dir(
        experiment_scoped_dir(config["paths"]["scores_dir"], args.dataset, **scope)
    )
    parsed_path = parsed_dir / f"{args.dataset}_parsed_stance.jsonl"
    # 第一步:解析两套回答的立场,产出 parsed_stance.jsonl。
    parse_manifest = parse_stance_files(
        dataset=args.dataset,
        queries_path=resolve_path(config["paths"]["stealth_filtered_queries_dir"]) / f"{args.dataset}_paired_queries.jsonl",
        rag_responses_path=experiment_scoped_dir(
            rag_config["paths"]["rag_responses_dir"],
            args.dataset,
            **scope,
        )
        / f"{args.dataset}_rag_responses.jsonl",
        llm_responses_path=(
            None
            if args.skip_llm_only
            else experiment_scoped_dir(
                rag_config["paths"]["llm_only_responses_dir"],
                args.dataset,
                generator_family=generator_identity.generator_family,
                concrete_model=generator_identity.concrete_model,
                retriever_id="none",
            )
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
