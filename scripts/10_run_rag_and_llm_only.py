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
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.factory import build_victim_client, load_llm_profiles, resolve_llm_profile_name
from src.rag.runner import run_rag_and_llm_only
from src.utils.io import ensure_dir, load_yaml, read_jsonl, resolve_path
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
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
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
    # RAG 回答与纯 LLM 回答分目录存放,便于后续对比。
    rag_dir = ensure_dir(resolve_path(config["paths"]["rag_responses_dir"]))
    llm_dir = ensure_dir(resolve_path(config["paths"]["llm_only_responses_dir"]))

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
        queries_path=resolve_path(config["paths"]["queries_dir"]) / f"{args.dataset}_paired_queries.jsonl",
        benchmark_path=resolve_path(config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        index_dir=resolve_path(config["paths"]["indexes_dir"]) / args.dataset,
        rag_output_path=rag_dir / f"{args.dataset}_rag_responses.jsonl",
        llm_output_path=llm_dir / f"{args.dataset}_llm_only_responses.jsonl",
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
        request_interval_seconds=float(gen_cfg.get("request_interval_seconds", 0.0)),
        max_workers=int(gen_cfg.get("max_workers", 1)),
        requests_per_minute=float(gen_cfg.get("requests_per_minute", 0.0)),
        allowed_fact_ids=allowed_fact_ids,
        resume=not args.no_resume,
        force=args.force,
        # 把实际用到的 victim profile 一并写进配置快照,方便结果追溯。
        config_snapshot={**config, "victim_profile_used": profile},
    )
    logger.info("Step 10 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
