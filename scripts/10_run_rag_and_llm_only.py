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
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.factory import build_victim_client, load_llm_profiles, resolve_llm_profile_name
from src.llm.generator_registry import (
    load_and_resolve_frozen_generator,
    record_first_formal_call,
)
from src.rag.paths import retriever_id_from_config, retriever_index_dir
from src.rag.retriever import HybridRagRetriever
from src.rag.runner import run_rag_and_llm_only
from src.utils.io import ensure_dir, load_yaml, read_json, read_jsonl, resolve_path, write_json
from src.utils.run_context import (
    experiment_scoped_dir,
    git_snapshot,
    require_clean_release_commit,
)
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
        "--retriever-backend",
        choices=["dense", "bm25", "hybrid"],
        default=None,
    )
    parser.add_argument(
        "--generator-family",
        choices=["gemini", "qwen", "gpt", "llama"],
        default=None,
    )
    parser.add_argument(
        "--context-control",
        choices=["retrieved", "oracle", "random"],
        default="retrieved",
        help="真实检索、Oracle target context 或确定性 Random distractor。",
    )
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
    parser.add_argument(
        "--suite-id",
        default=None,
        help="Pilot/extension 的隔离 suite ID；省略时写正式 v20 目录。",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=200,
        help="每累计多少条响应写盘一次；必须为正整数，默认 200",
    )
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
    if (
        args.suite_id is None
        and os.getenv("PCV_ALLOW_SINGLE_CELL_FORMAL", "").strip().lower()
        not in {"1", "true", "yes"}
    ):
        raise RuntimeError(
            "Direct one-cell formal execution is disabled by v20. "
            "Use scripts/22_run_interleaved_v20.py so all four conditions "
            "follow the frozen source-block schedule."
        )
    if args.skip_rag and not args.llm_only:
        raise ValueError("--skip-rag requires --llm-only")
    if args.llm_only and not args.skip_rag:
        raise ValueError(
            "v20 matched LLM-only must run as a separate cell: use --llm-only --skip-rag."
        )
    if args.checkpoint_every < 1:
        raise ValueError("--checkpoint-every must be a positive integer")
    config = load_yaml(args.config)
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))
    profiles = load_llm_profiles(config)
    gen_cfg = config.get("generation", {})
    if bool(gen_cfg.get("run_llm_only", False)) and not args.skip_rag:
        raise ValueError(
            "generation.run_llm_only cannot be combined with a RAG cell in v20."
        )
    # 受害者模型 profile:命令行 --victim-profile 优先,其次取配置里的 victim_profile。
    profile_name = resolve_llm_profile_name(
        "victim",
        cli_profile=args.victim_profile,
        config_profile=gen_cfg.get("victim_profile"),
    )
    client, profile = build_victim_client(profiles, profile_name=profile_name)
    retriever_backend = args.retriever_backend or str(config.get("retrieval", {}).get("backend", "dense"))
    generator_family = args.generator_family or str(config.get("generator_family") or "")
    generator_identity = load_and_resolve_frozen_generator(
        family=generator_family,
        concrete_model=str(profile.get("model") or ""),
        provider=str(profile.get("provider") or ""),
        generator_version=profile.get("model_version"),
        path=str(
            config.get(
                "generator_registry_path",
                "configs/generator_families.yaml",
            )
        ),
        allow_pilot_candidate=bool(args.suite_id),
    )
    selected_retriever_id = (
        retriever_id_from_config(config, retriever_backend)
        if args.context_control == "retrieved"
        else {
            "oracle": "oracle-context",
            "random": "random-distractor",
        }[args.context_control]
    )
    if args.suite_id:
        suite_id = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            str(args.suite_id).strip(),
        ).strip("-")
        if not suite_id:
            raise ValueError("--suite-id must contain at least one safe character")
        suite_root = resolve_path(
            config["paths"].get("pilots_dir", "artifacts/v20/pilots")
        ) / suite_id
        rag_responses_base = suite_root / "rag_responses"
        llm_only_responses_base = suite_root / "llm_only_responses"
    else:
        rag_responses_base = config["paths"]["rag_responses_dir"]
        llm_only_responses_base = config["paths"]["llm_only_responses_dir"]
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
        rag_dir = ensure_dir(
            experiment_scoped_dir(
                rag_responses_base,
                args.dataset,
                generator_family=generator_identity.generator_family,
                concrete_model=generator_identity.concrete_model,
                retriever_id=selected_retriever_id,
            )
        )
        llm_dir = ensure_dir(
            experiment_scoped_dir(
                llm_only_responses_base,
                args.dataset,
                generator_family=generator_identity.generator_family,
                concrete_model=generator_identity.concrete_model,
                retriever_id="none",
            )
        )
        rag_output_path = rag_dir / f"{args.dataset}_rag_responses.jsonl"
        llm_output_path = llm_dir / f"{args.dataset}_llm_only_responses.jsonl"
    else:
        control_queries_dir = resolve_path(
            config["paths"].get("query_controls_dir", "outputs/query_controls")
        )
        default_queries_path = control_queries_dir / args.dataset / variant_id / "queries.jsonl"
        control_dir = ensure_dir(
            experiment_scoped_dir(
                config["paths"].get(
                    "query_control_responses_dir",
                    "outputs/query_control_responses",
                ),
                args.dataset,
                generator_family=generator_identity.generator_family,
                concrete_model=generator_identity.concrete_model,
                retriever_id=selected_retriever_id,
            )
            / variant_id
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

    retriever_override = None
    if (
        retriever_backend == "hybrid"
        and args.context_control == "retrieved"
        and not args.skip_rag
    ):
        hybrid_cfg = config.get("retrieval", {}).get("hybrid", {})
        retriever_override = HybridRagRetriever(
            retriever_index_dir(config, args.dataset, "dense"),
            retriever_index_dir(config, args.dataset, "bm25"),
            dense_candidate_top_k=int(
                hybrid_cfg.get("dense_candidate_top_k", 20)
            ),
            bm25_candidate_top_k=int(
                hybrid_cfg.get("bm25_candidate_top_k", 20)
            ),
            rrf_k=int(hybrid_cfg.get("rrf_k", 60)),
            fusion_top_k=int(hybrid_cfg.get("fusion_top_k", 20)),
            final_top_k=int(hybrid_cfg.get("final_top_k", 5)),
            reranker_model=str(
                hybrid_cfg.get("reranker_model", "BAAI/bge-reranker-base")
            ),
            reranker_revision=hybrid_cfg.get("reranker_revision"),
            reranker_local_files_only=bool(
                hybrid_cfg.get("reranker_local_files_only", True)
            ),
        )
        index_dir = resolve_path(config["paths"]["indexes_dir"]) / args.dataset
    elif not args.skip_rag:
        underlying_backend = (
            retriever_backend
            if args.context_control == "retrieved"
            else "dense"
        )
        index_dir = retriever_index_dir(config, args.dataset, underlying_backend)
    else:
        index_dir = resolve_path(config["paths"]["indexes_dir"]) / args.dataset
    if not args.skip_rag:
        active_retriever = retriever_override
        if active_retriever is None:
            from src.rag.retriever import RagRetriever

            active_retriever = RagRetriever(index_dir)
            retriever_override = active_retriever
        active_manifest = getattr(active_retriever, "manifest", {})
        snapshot_backend = (
            retriever_backend
            if args.context_control == "retrieved"
            else "dense"
        )
        if snapshot_backend == "dense" and not active_manifest.get(
            "embedding_revision"
        ):
            raise RuntimeError(
                "Dense Retriever snapshot is not frozen. Set embedding.revision "
                "to an exact commit and rebuild the index before API calls."
            )
        if snapshot_backend == "bm25" and not active_manifest.get(
            "tokenizer_revision"
        ):
            raise RuntimeError(
                "BM25 tokenizer snapshot is not frozen. Set tokenizer_revision "
                "to an exact commit and rebuild the index before API calls."
            )
        if snapshot_backend == "hybrid":
            if not active_manifest.get("dense_embedding_revision"):
                raise RuntimeError("Hybrid dense snapshot is not frozen.")
            if not active_manifest.get("reranker_revision"):
                raise RuntimeError("Hybrid reranker snapshot is not frozen.")
    code_commit = require_clean_release_commit(git_snapshot())
    schedule_path = None
    schedule_hash = None
    schedule_cell = None
    if args.suite_id is None and args.context_control == "retrieved":
        schedule_path = resolve_path(config["paths"]["execution_schedule_path"])
        schedule_manifest_path = resolve_path(
            config["paths"]["execution_schedule_manifest_path"]
        )
        if not schedule_path.is_file() or not schedule_manifest_path.is_file():
            raise FileNotFoundError(
                "Formal v20 execution requires the frozen execution schedule; "
                "run scripts/21_prepare_v20_release_controls.py first."
            )
        schedule_manifest = read_json(schedule_manifest_path)
        schedule_hash = str(schedule_manifest.get("schedule_hash") or "")
        schedule_cell = "none" if args.skip_rag else retriever_backend

    manifest = run_rag_and_llm_only(
        dataset=args.dataset,
        queries_path=queries_path,
        benchmark_path=resolve_path(config["paths"]["benchmark_dir"]) / f"{args.dataset}_attack_benchmark.jsonl",
        index_dir=index_dir,
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
        config_snapshot={
            **config,
            "victim_profile_used": profile,
            "generator_identity": generator_identity.to_dict(),
            "suite_id": args.suite_id,
        },
        variant_id=variant_id,
        checkpoint_every=args.checkpoint_every,
        generator_family=generator_identity.generator_family,
        concrete_model=generator_identity.concrete_model,
        generator_id=generator_identity.concrete_model,
        generator_version=generator_identity.generator_version,
        code_commit=code_commit,
        retriever_override=retriever_override,
        context_control=args.context_control,
        retriever_identity_override=selected_retriever_id,
        pairs_per_source=(
            int(config.get("experiment_protocol", {}).get("pairs_per_source"))
            if config.get("experiment_protocol", {}).get("pairs_per_source") is not None
            else None
        ),
        ground_truth_source_store_path=(
            resolve_path(config["paths"]["ground_truth_source_store_dir"])
            / f"{args.dataset}_sources.jsonl"
            if args.context_control != "retrieved"
            else None
        ),
        schedule_path=schedule_path,
        schedule_hash=schedule_hash,
        schedule_cell=schedule_cell,
    )
    first_call_at = (
        manifest.get("provider_response_metadata") or {}
    ).get("first_call_at")
    if args.suite_id is None and first_call_at:
        freeze_state = record_first_formal_call(
            generator_identity,
            called_at=str(first_call_at),
            state_root=config["paths"].get(
                "generator_registry_state_dir",
                "artifacts/v20/generator_registry_state",
            ),
        )
        manifest["generator_freeze_state_path"] = str(freeze_state)
        if not args.skip_rag:
            write_json(manifest, rag_output_path.with_suffix(".manifest.json"))
        if bool(args.llm_only or gen_cfg.get("run_llm_only", False)):
            write_json(manifest, llm_output_path.with_suffix(".manifest.json"))
    logger.info("Step 10 finished: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
