"""12: 跑 RAG-MIA baseline 对照实验(真实受害查询版)。

中文说明
========
对应流水线第 12 步「跑 baseline 对照」。本版**真正执行**各 baseline 的受害查询:
对同一批目标 chunk(kb_member=成员 / true_non_member=非成员)、同一个 KB 索引、同一个
victim 模型、同一套指标,逐个跑 RAG-MIA / S2MIA(s) / MBA / IA / DCMI,并把 PCV-MIA
(从第 11 步分数读)一并拉进同一张对照表。

infra(索引/切分/profile/生成参数)读 rag_config.yaml;方法列表/阈值/输出目录读 baseline_config.yaml。
IA / DCMI 需要 attacker LLM(sibling profile);其余三个纯靠 victim。

成本提示(每目标 victim 调用):RAG-MIA/S2MIA/MBA=1,DCMI=2,IA≈top_k(默认5)。
提速(对齐第 10 步):rag_config 的 generation.requests_per_minute>0 时启用【全局令牌桶+并发】
(max_workers 跨目标并行,抗端点间歇卡顿);=0 时回退旧的固定间隔(--request-interval)。
试跑用 --max-targets 限目标数。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.baselines.victim_harness import (
    BASELINES,
    Services,
    balanced_sample,
    build_attacker_chat,
    load_targets,
    run_one_baseline,
)
from src.evaluation.metrics import paired_bootstrap_metric_delta, summarize_membership_scores
from src.llm.factory import build_victim_client, load_llm_profiles, resolve_llm_profile_name
from src.rag.retriever import RagRetriever
from src.rag.runner import TokenBucket
from src.utils.io import ensure_dir, load_yaml, read_jsonl, resolve_path, write_json, write_jsonl
from src.utils.run_context import model_scoped_dir
from src.utils.logger import setup_logging
from src.utils.seed import set_seed_from_config


def _filter_sources(rows: list[dict], sources: set[str]) -> list[dict]:
    return [row for row in rows if str(row.get("source_key") or row.get("source_id")) in sources]


def _pcv_budget_rows(pair_rows: list[dict], budget: int) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in pair_rows:
        if row.get("complete_rag_pair") is False or row.get("cvg_rag") is None:
            continue
        buckets[str(row.get("source_key") or row.get("source_id"))].append(row)
    out = []
    pair_budget = budget // 2
    for source_key, rows in sorted(buckets.items()):
        chosen = sorted(rows, key=lambda row: str(row.get("logical_pair_id") or row.get("pair_id")))[:pair_budget]
        if not chosen:
            continue
        out.append({
            "source_key": source_key,
            "group": chosen[0].get("group"),
            "pcv_score": mean(float(row["cvg_rag"]) for row in chosen),
            "victim_calls": 2 * len(chosen),
        })
    return out


def _baseline_budget_rows(chunk_rows: list[dict], budget: int) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in chunk_rows:
        if row.get("score") is None or row.get("error"):
            continue
        buckets[str(row.get("source_key") or row.get("source_id") or row.get("doc_id"))].append(row)
    out = []
    for source_key, rows in sorted(buckets.items()):
        chosen: list[dict] = []
        used = 0
        for row in sorted(rows, key=lambda item: str(item.get("doc_id"))):
            calls = int(row.get("victim_calls", 0))
            if calls <= 0 or used + calls > budget:
                continue
            chosen.append(row)
            used += calls
        if chosen:
            out.append({
                "source_key": source_key,
                "group": chosen[0].get("group"),
                "score": mean(float(row["score"]) for row in chosen),
                "victim_calls": used,
            })
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RAG-MIA baselines (real victim queries).")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "baseline_config.yaml"))
    # infra(索引/切分/profile/生成参数)来自 rag_config。
    parser.add_argument("--rag-config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--methods", default="RAG-MIA,S2MIA,MBA,IA,DCMI",
                        help="逗号分隔,可选:" + ",".join(BASELINES))
    parser.add_argument("--max-targets", type=int, default=None, help="只跑前 N 个目标(两类均衡,省 API 试跑)")
    parser.add_argument("--request-interval", type=float, default=None, help="每次 victim 调用后睡眠秒数(限速)")
    parser.add_argument("--victim-profile", default=None)
    parser.add_argument("--sibling-profile", default=None)
    parser.add_argument("--attacker", choices=["sibling", "victim"], default="sibling",
                        help="IA/DCMI 的 attacker 用哪个模型:sibling(默认,需 PCV_SIBLING_API_KEY)或 victim(复用受害模型,免配 sibling key)")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_yaml(args.config)          # baseline_config:methods/threshold/输出目录
    rag_config = load_yaml(args.rag_config)  # infra:索引/切分/profile/生成参数
    set_seed_from_config(config)
    logger = setup_logging("pcv_mia", log_file=resolve_path(config["logging"]["file"]), level=config["logging"].get("level", "INFO"))

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown = [m for m in methods if m not in BASELINES]
    if unknown:
        raise ValueError(f"未知 baseline:{unknown};可选 {list(BASELINES)}")

    # —— 基础设施:profiles / victim / (按需)attacker / retriever ——
    profiles = load_llm_profiles(rag_config)
    gen_cfg = rag_config.get("generation", {})
    victim_name = resolve_llm_profile_name("victim", cli_profile=args.victim_profile, config_profile=gen_cfg.get("victim_profile"))
    victim, victim_profile = build_victim_client(profiles, profile_name=victim_name)

    need_attacker = any(BASELINES[m].needs_attacker for m in methods)
    attacker_chat = None
    if need_attacker:
        if args.attacker == "victim":
            # 复用 victim profile 当 attacker(免配 sibling key);attacker 侧离线生成用什么模型都行。
            from src.baselines.victim_harness import _chat_fn_from_profile
            attacker_chat = _chat_fn_from_profile(
                victim_profile,
                timeout=float(gen_cfg.get("timeout", 60.0)),
                max_tokens=int(gen_cfg.get("max_tokens", 512)),
            )
            logger.info("Attacker 使用 victim 模型(--attacker victim)")
        else:
            attacker_chat = build_attacker_chat(
                profiles, args.sibling_profile,
                timeout=float(gen_cfg.get("timeout", 60.0)),
                max_tokens=int(gen_cfg.get("max_tokens", 512)),
            )

    index_dir = resolve_path(rag_config["paths"]["indexes_dir"]) / args.dataset
    retriever = RagRetriever(index_dir)
    splits_dir = resolve_path(rag_config["paths"]["splits_dir"]) / args.dataset
    targets = load_targets(splits_dir)
    if args.max_targets:
        targets = balanced_sample(targets, args.max_targets)
    n_kb = sum(t["group"] == "KB_Member" for t in targets)
    n_tn = sum(t["group"] == "True_Non_Member" for t in targets)
    logger.info("Baseline targets: total=%s KB=%s TN=%s", len(targets), n_kb, n_tn)

    interval = args.request_interval if args.request_interval is not None else float(gen_cfg.get("request_interval_seconds", 0.0))
    threshold = float(config.get("baseline", {}).get("threshold", 0.3))
    out_dir = ensure_dir(model_scoped_dir(config["paths"]["baselines_dir"], args.dataset))

    # —— 限速:令牌桶(抗端点卡顿)+ 并发(跨目标),对齐第 10 步 runner ——
    # requests_per_minute>0 启用全局令牌桶(全局速率恒 ≤ RPM);配合 max_workers>1,某目标卡在
    # 慢 victim 调用时别的目标继续发,把 RPM 管道填满。=0 时回退 request_interval_seconds 固定 sleep。
    rpm = float(gen_cfg.get("requests_per_minute", 0.0))
    # sibling(attacker)是另一把 key/端点 → 用它自己的 RPM 独立限速;未配则回退成与 victim 同 RPM。
    sibling_rpm = float(gen_cfg.get("sibling_requests_per_minute", 0.0)) or rpm
    max_workers = int(gen_cfg.get("max_workers", 1))
    victim_bucket = TokenBucket(rpm) if rpm > 0 else None
    if args.attacker == "victim":
        # attacker 复用 victim 端点/同一个 key → 共用【同一只】桶,两路调用合并计入该 key 的 RPM。
        attacker_bucket = victim_bucket
    else:
        # attacker 走 sibling(另一把 key)→ 【自己一只桶】按 sibling_rpm 独立放行,不与 victim 抢速率。
        attacker_bucket = TokenBucket(sibling_rpm) if sibling_rpm > 0 else None
    rate_mode = "token_bucket" if victim_bucket is not None else "fixed_interval"
    bucket_share = "none" if victim_bucket is None else ("shared" if attacker_bucket is victim_bucket else "separate")
    logger.info("限速模式=%s victim_rpm=%s sibling_rpm=%s max_workers=%s attacker=%s(bucket=%s)",
                rate_mode, rpm, sibling_rpm, max_workers, args.attacker, bucket_share)

    # —— 逐个 baseline 跑 ——
    comparison: list[dict] = []
    results_by_method: dict[str, dict] = {}
    for name in methods:
        svc = Services(
            retriever=retriever, victim=victim, attacker_chat=attacker_chat,
            top_k=int(rag_config.get("retrieval", {}).get("top_k", 5)),
            temperature=float(gen_cfg.get("temperature", 0.0)),
            max_tokens=int(gen_cfg.get("max_tokens", 512)),
            timeout=float(gen_cfg.get("timeout", 60.0)),
            request_interval_seconds=interval,
            # 重试退避:吸收瞬时 HTTP 524/5xx(对齐第 10 步 runner)。
            retries=int(gen_cfg.get("retries", 3)),
            retry_backoff_base=float(gen_cfg.get("retry_backoff_base", 2.0)),
            retry_backoff_max=float(gen_cfg.get("retry_backoff_max", 30.0)),
            # 短重试耗尽后,API/网络错误长冷却并重试同一请求,直到成功。
            retry_until_success=bool(gen_cfg.get("retry_until_success", True)),
            retry_cooldown_seconds=float(gen_cfg.get("retry_cooldown_seconds", 300.0)),
            # 令牌桶(抗卡顿):rpm=0 时为 None,自动回退到 request_interval_seconds 固定 sleep。
            victim_bucket=victim_bucket,
            attacker_bucket=attacker_bucket,
        )
        res = run_one_baseline(
            name, targets, svc,
            output_path=out_dir / f"{args.dataset}_{name.replace('/', '_')}_scores.jsonl",
            threshold=threshold, resume=not args.no_resume, force=args.force,
            max_workers=max_workers,
        )
        results_by_method[name] = res
        comparison.append(_table_row(name, res))
        logger.info("[%s] scored=%s failed=%s victim=%s attacker=%s AUC=%s",
                    name, res["scored"], res["failed"], res["victim_calls"], res["attacker_calls"],
                    res["metrics"].get("AUC"))

    # —— 把 PCV-MIA(本项目方法)从第 11 步分数拉进同一张表 ——
    # P0-2:chunk 是查询/检索单位，但统计单位固定为 source。PCV 与 baseline 都只在
    # 本次 target 覆盖的同一批 source 上评估；--max-targets 仅用于试跑，canonical 不应使用。
    scores_dir = model_scoped_dir(config["paths"]["scores_dir"], args.dataset)
    pcv_path = scores_dir / f"{args.dataset}_pcv_scores_source_scores.jsonl"
    budget_rows: list[dict] = []
    if pcv_path.exists():
        target_sources = {
            str(t.get("source_key") or t.get("source_id") or t.get("doc_id"))
            for t in targets
        }
        all_pcv = list(read_jsonl(pcv_path))
        pcv_rows = [
            row for row in all_pcv
            if str(row.get("source_key") or row.get("source_id") or row.get("audit_id")) in target_sources
        ]
        logger.info("PCV-MIA source 对齐:%s/%s 命中(target sources=%s)", len(pcv_rows), len(all_pcv), len(target_sources))
        if not pcv_rows:
            logger.warning("PCV source 分数与 baseline 目标无交集,跳过 PCV-MIA 并表")
        if pcv_rows:
            source_rows_by_method = {
                name: list(read_jsonl(Path(results_by_method[name]["source_output_path"])))
                for name in methods
            }
            common_sources = {str(row.get("source_key")) for row in pcv_rows}
            for rows in source_rows_by_method.values():
                common_sources &= {str(row.get("source_key")) for row in rows}
            if not common_sources:
                raise RuntimeError("PCV 与所有 baseline 没有共同成功 source，不能生成公平对照")
            pcv_common = _filter_sources(pcv_rows, common_sources)
            comparison = []
            for name in methods:
                baseline_common = _filter_sources(source_rows_by_method[name], common_sources)
                metrics = summarize_membership_scores(baseline_common, score_key="score", threshold=threshold)
                row = _table_row(name, {**results_by_method[name], "scored": len(baseline_common), "metrics": metrics})
                row["common_source_whitelist_size"] = len(common_sources)
                row["paired_vs_pcv"] = paired_bootstrap_metric_delta(
                    pcv_common,
                    baseline_common,
                    left_score_key="pcv_score",
                    right_score_key="score",
                )
                comparison.append(row)
            for key, label in (("pcv_score", "PCV-MIA"), ("cg_cvg", "PCV-MIA (context-gain control)")):
                if key in pcv_common[0]:
                    m = summarize_membership_scores(pcv_common, score_key=key, threshold=threshold)
                    pairs = sum(int(row.get("num_pairs", 0)) for row in pcv_common)
                    calls_per_pair = 2 if key == "pcv_score" else 4
                    item = _table_row(label, {
                        "scored": len(pcv_common),
                        "victim_calls": pairs * calls_per_pair,
                        "attacker_calls": 0,
                        "metrics": m,
                    })
                    item["common_source_whitelist_size"] = len(common_sources)
                    comparison.append(item)

            pair_path = scores_dir / f"{args.dataset}_pcv_scores_pair_scores.jsonl"
            pair_rows = list(read_jsonl(pair_path)) if pair_path.exists() else []
            for name in methods:
                chunk_rows = list(read_jsonl(results_by_method[name]["output_path"]))
                for budget in (2, 4, 6, 8):
                    pcv_budget = _pcv_budget_rows(pair_rows, budget)
                    baseline_budget = _baseline_budget_rows(chunk_rows, budget)
                    common_budget = {
                        str(row.get("source_key")) for row in pcv_budget
                    } & {str(row.get("source_key")) for row in baseline_budget}
                    pcv_budget = _filter_sources(pcv_budget, common_budget)
                    baseline_budget = _filter_sources(baseline_budget, common_budget)
                    if not pcv_budget or not baseline_budget:
                        continue
                    budget_rows.append({
                        "baseline": name,
                        "victim_call_budget": budget,
                        "common_sources": len(common_budget),
                        "pcv_metrics": summarize_membership_scores(pcv_budget, score_key="pcv_score"),
                        "baseline_metrics": summarize_membership_scores(baseline_budget, score_key="score"),
                        "paired_delta": paired_bootstrap_metric_delta(
                            pcv_budget,
                            baseline_budget,
                            left_score_key="pcv_score",
                            right_score_key="score",
                        ),
                    })
    else:
        logger.warning("PCV source-level 分数不存在,对照表不含 PCV-MIA:%s", pcv_path)

    # —— 写对照表 + manifest ——
    table_path = out_dir / f"{args.dataset}_baseline_comparison.jsonl"
    write_jsonl(comparison, table_path)
    budget_path = out_dir / f"{args.dataset}_baseline_budget_matched.json"
    write_json({"dataset": args.dataset, "budgets": [2, 4, 6, 8], "results": budget_rows}, budget_path)
    manifest = {
        "dataset": args.dataset,
        "methods": methods,
        "targets": {"total": len(targets), "KB_Member": n_kb, "True_Non_Member": n_tn},
        "target_sources": len({str(t.get("source_key") or t.get("source_id") or t.get("doc_id")) for t in targets}),
        "evaluation_unit": "source",
        "request_interval_seconds": interval,
        # 限速快照(抗卡顿):令牌桶 RPM / 并发数 / 模式,便于复现与排查。
        "requests_per_minute": rpm,
        "max_workers": max_workers,
        "rate_limit_mode": rate_mode,
        "attacker_bucket": bucket_share,
        "comparison_path": str(table_path),
        "budget_matched_path": str(budget_path),
        "victim_profile_used": victim_profile,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(manifest, table_path.with_suffix(".manifest.json"))
    logger.info("Step 12 finished: %s", table_path)
    # 控制台打印一张精简对照表
    print(f"\n=== Baseline 对照({args.dataset},KB={n_kb}/TN={n_tn}) ===")
    print(f"{'method':22s} {'AUC':>7} {'Acc@best':>9} {'TPR@1%':>8} {'TPR@5%':>8} {'victim':>7}")
    for r in comparison:
        print(f"{r['baseline']:22s} {_f(r['AUC']):>7} {_f(r['Accuracy@best']):>9} "
              f"{_f(r['TPR@1%FPR']):>8} {_f(r['TPR@5%FPR']):>8} {str(r['victim_calls'] or '-'):>7}")
    return 0


def _table_row(name: str, res: dict) -> dict:
    m = res.get("metrics", {})
    return {
        "baseline": name,
        "AUC": m.get("AUC"),
        "Accuracy@best": m.get("Accuracy@best"),
        "TPR@1%FPR": m.get("TPR@1%FPR"),
        "TPR@5%FPR": m.get("TPR@5%FPR"),
        "scored": res.get("scored"),
        "victim_calls": res.get("victim_calls"),
        "attacker_calls": res.get("attacker_calls"),
        "evaluation_unit": "source",
    }


def _f(x) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else "n/a"


if __name__ == "__main__":
    raise SystemExit(main())
