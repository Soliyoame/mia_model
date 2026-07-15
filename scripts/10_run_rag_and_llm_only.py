"""10: 对通过筛选的配对查询,分别跑 RAG 与"纯 LLM"两种生成。

中文说明
========
本文件对应流水线第 10 步:读入第 09 步过滤后的配对查询,把每条查询发给受害者模型
(victim)两次——一次带 RAG 检索上下文(`{dataset}_rag_responses.jsonl`),
一次不挂任何知识库、只靠模型自身参数记忆回答(`{dataset}_llm_only_responses.jsonl`)。
两套回答的对比是后续判定成员关系的关键:若某文档真在 RAG 库里,带检索时的回答会
明显不同于纯 LLM 时的回答。

实际的检索 + 调用 + 并发 + 重试逻辑都在 `src.rag.runner.run_rag_and_llm_only` 里,
本脚本只负责:读配置、设种子、按命令行/配置挑选 victim 模型 profile 并建好客户端,
再把检索条数 top_k、温度、超时、重试退避、请求间隔、并发数等参数一并传进去。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.factory import build_victim_client, load_llm_profiles, resolve_llm_profile_name
from src.rag.runner import run_rag_and_llm_only
from src.utils.io import ensure_dir, load_yaml, read_jsonl, resolve_path
from src.utils.run_context import model_scoped_dir
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回:
        argparse.Namespace,除常规的 dataset、config、force、no_resume 外,
        还含 victim_profile:命令行显式指定受害者模型 profile,优先级高于配置。
    """
    parser = argparse.ArgumentParser(description="Run PCV-MIA RAG and LLM-only responses.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--victim-profile", default=None)
    parser.add_argument(
        "--variant-id",
        default="full_pvs",
        help="实验变体标识；非 full_pvs 时输入/输出使用隔离的 query-control 目录",
    )
    parser.add_argument(
        "--queries-path",
        default=None,
        help="显式查询计划 JSONL；省略时按 variant-id 从配置目录解析",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--llm-only",
        action="store_true",
        help="显式启用可选的 LLM-only 归因对照；默认仅运行 RAG",
    )
    parser.add_argument(
        "--skip-rag",
        action="store_true",
        help="不运行 RAG 路；仅供独立 matched-control 与 --llm-only 联用",
    )
    # 提速开关(RPM 受限时用)：
    #   --primary-only  只跑 selection_tier=primary 的高质量 fact,同时砍 RAG 与 LLM-only 两路调用数。
    parser.add_argument("--primary-only", action="store_true",
                        help="只处理 selection_tier=primary 的 fact 对应的 query")
    return parser.parse_args()


def main() -> int:
    """脚本入口:跑 RAG 与纯 LLM 两套生成并写盘。

    返回:
        进程退出码,正常结束返回 0。
    """
    args = parse_args()
    if args.skip_rag and not args.llm_only:
        raise ValueError("--skip-rag requires --llm-only")
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    profiles = load_llm_profiles(config)
    gen_cfg = config.get("generation", {})
    # 受害者模型 profile:命令行 --victim-profile 优先,其次取配置里的 victim_profile。
    profile_name = resolve_llm_profile_name(
        "victim",
        cli_profile=args.victim_profile,
        config_profile=gen_cfg.get("victim_profile"),
    )
    client, profile = build_victim_client(profiles, profile_name=profile_name)
    variant_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(args.variant_id).strip()).strip("-")
    if not variant_id or variant_id != str(args.variant_id).strip():
        logger.error("非法 --variant-id: %r", args.variant_id)
        return 2
    # RAG 回答与纯 LLM 回答分目录存放,便于后续对比。按 {数据集}/{模型}/ 分,换模型不覆盖。
    if variant_id == "full_pvs":
        default_queries_path = (
            resolve_path(config["paths"]["queries_dir"])
            / f"{args.dataset}_paired_queries.jsonl"
        )
        rag_dir = ensure_dir(model_scoped_dir(config["paths"]["rag_responses_dir"], args.dataset))
        llm_dir = ensure_dir(model_scoped_dir(config["paths"]["llm_only_responses_dir"], args.dataset))
        rag_output_path = rag_dir / f"{args.dataset}_rag_responses.jsonl"
        llm_output_path = llm_dir / f"{args.dataset}_llm_only_responses.jsonl"
    else:
        control_queries_dir = resolve_path(
            config["paths"].get("query_controls_dir", "outputs/query_controls")
        )
        default_queries_path = control_queries_dir / args.dataset / variant_id / "queries.jsonl"
        control_dir = ensure_dir(
            model_scoped_dir(
                config["paths"].get(
                    "query_control_responses_dir",
                    "outputs/query_control_responses",
                ),
                args.dataset,
            ) / variant_id
        )
        rag_output_path = control_dir / "rag_responses.jsonl"
        llm_output_path = control_dir / "llm_only_responses.jsonl"
    queries_path = resolve_path(args.queries_path) if args.queries_path else default_queries_path
    if not queries_path.exists():
        logger.error("查询计划不存在: %s", queries_path)
        return 1

    # --primary-only:读 facts,取 selection_tier=primary 的 fact_id 白名单,砍掉低质量 fact 的 query。
    allowed_fact_ids: set[str] | None = None
    if args.primary_only:
        facts_dir = resolve_path(config.get("paths", {}).get("facts_dir", "outputs/facts"))
        facts_path = facts_dir / f"{args.dataset}_facts.jsonl"
        if not facts_path.exists():
            logger.error("--primary-only 需要 facts 文件,但不存在: %s", facts_path)
            return 1
        allowed_fact_ids = {
            str(f.get("fact_id"))
            for f in read_jsonl(facts_path)
            if str(f.get("selection_tier") or "primary") == "primary"
        }
        logger.info("primary-only 生效: %s 个 primary fact 进入本次运行", len(allowed_fact_ids))

    manifest = run_rag_and_llm_only(
        dataset=args.dataset,
        queries_path=queries_path,
        benchmark_path=resolve_path(config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        index_dir=resolve_path(config["paths"]["indexes_dir"]) / args.dataset,
        rag_output_path=rag_output_path,
        llm_output_path=llm_output_path,
        client=client,
        top_k=int(config.get("retrieval", {}).get("top_k", 5)),
        # temperature 默认 0 走贪心解码,保证可复现。
        temperature=float(gen_cfg.get("temperature", 0.0)),
        max_tokens=int(gen_cfg.get("max_tokens", 512)),
        timeout=float(gen_cfg.get("timeout", 60)),
        # 下面几项控制失败重试的指数退避与请求节流,避免触发限流。
        retries=int(gen_cfg.get("retries", 2)),
        retry_backoff_base=float(gen_cfg.get("retry_backoff_base", 2.0)),
        retry_backoff_max=float(gen_cfg.get("retry_backoff_max", 60.0)),
        retry_until_success=bool(gen_cfg.get("retry_until_success", True)),
        retry_cooldown_seconds=float(gen_cfg.get("retry_cooldown_seconds", 300.0)),
        request_interval_seconds=float(gen_cfg.get("request_interval_seconds", 0.0)),
        max_workers=int(gen_cfg.get("max_workers", 1)),
        requests_per_minute=float(gen_cfg.get("requests_per_minute", 0.0)),
        run_rag=not args.skip_rag,
        run_llm_only=bool(args.llm_only or gen_cfg.get("run_llm_only", False)),
        allowed_fact_ids=allowed_fact_ids,
        resume=not args.no_resume,
        force=args.force,
        # 把实际用到的 victim profile 一并写进配置快照,方便结果追溯。
        config_snapshot={**config, "victim_profile_used": profile},
        variant_id=variant_id,
    )
    logger.info("Step 10 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
