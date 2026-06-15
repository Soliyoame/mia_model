"""L2 shadow per-example 校准入口(辅助脚本,不在 01-15 主流水线)。

中文说明
========
建 K 个 Reserve-shadow 索引、在其上跑评估 query 的 RAG、估计每个目标的非成员零分布,
再做 per-example 校准(z-score / offline LiRA Φ(z)),并打印 cg_cvg / L1 / L2 三方对比。

L2 解决 L1(全局单调变换、AUC≡cvg_rag)扣不掉的 per-example 先验泄漏(诊断 enron formal:
cvg_llm AUC=0.606)。go/no-go:L2 分应使 True_Non 的 Φ(z)≈0.5(先验扣净)、KB→1,
且 AUC 超过 cg_cvg。

用法(先小 K 试跑):
    python scripts/run_l2_shadow.py --dataset enron --num-shadows 4

成本提示:对评估 query 跑 K 遍 RAG(LLM-only 复用主 run,不重跑)。建议 resume。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import summarize_membership_scores
from src.llm.factory import build_victim_client, load_llm_profiles, resolve_llm_profile_name
from src.rag.shadow_runner import run_l2_shadows
from src.scoring.calibration import (
    L2_KEY,
    PERCENTILE_KEY,
    calibrate_l2_shadow,
    calibrate_membership_scores,
)
from src.utils.io import ensure_dir, load_yaml, read_jsonl, resolve_path, write_json
from src.utils.logger import setup_logging
from src.utils.run_context import append_index, current_run_id, local_timestamp, run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PCV-MIA L2 shadow per-example calibration.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--rag-config", default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"))
    parser.add_argument("--attack-config", default=str(PROJECT_ROOT / "configs" / "pcv_attack_config.yaml"))
    parser.add_argument("--victim-profile", default=None)
    parser.add_argument("--num-shadows", type=int, default=4)
    parser.add_argument("--sample-ratio", type=float, default=0.8)
    parser.add_argument("--shadow-size", type=int, default=None)
    parser.add_argument("--eval-audit-limit", type=int, default=None,
                        help="只在随机采样的这么多个评估 audit 上跑 shadow(小规模探路，大降 API 调用)。")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-workers", type=int, default=None,
                        help="覆盖 rag_config 的 generation.max_workers(并发 victim 请求数)；"
                             "shadow 要跑 K 倍 RAG，确认 API 限额后调高(如 4~8)可大幅缩短墙钟。")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = parse_args()
    ds = args.dataset
    rag_cfg = load_yaml(args.rag_config)
    attack_cfg = load_yaml(args.attack_config)
    setup_logging("pcv_mia", log_file=resolve_path(rag_cfg["logging"]["file"]), level="INFO")

    paths = rag_cfg["paths"]
    gen = rag_cfg.get("generation", {})
    scoring = attack_cfg.get("scoring", {})

    # victim 客户端(shadow generator 必须与 victim 同款)。
    profiles = load_llm_profiles(rag_cfg)
    profile_name = resolve_llm_profile_name("victim", cli_profile=args.victim_profile, config_profile=gen.get("victim_profile"))
    client, profile = build_victim_client(profiles, profile_name=profile_name)

    main_scores_path = resolve_path("outputs/scores") / f"{ds}_pcv_scores.jsonl"

    # ---- 建 shadow + 跑 RAG + 算每个 shadow 的 cvg ----
    shadow_manifest = run_l2_shadows(
        dataset=ds,
        reserve_path=resolve_path(paths["splits_dir"]) / ds / "reserve.jsonl",
        queries_path=resolve_path(paths["queries_dir"]) / f"{ds}_paired_queries.jsonl",
        benchmark_path=resolve_path(paths["benchmark_dir"]) / f"{ds}_attack_benchmark.jsonl",
        main_llm_responses_path=resolve_path(paths["llm_only_responses_dir"]) / f"{ds}_llm_only_responses.jsonl",
        shadow_index_root=resolve_path(paths["indexes_dir"]) / f"{ds}_shadows",
        shadow_output_root=resolve_path("outputs/shadow") / ds,
        client=client,
        num_shadows=args.num_shadows,
        sample_ratio=args.sample_ratio,
        shadow_size=args.shadow_size,
        eval_audit_limit=args.eval_audit_limit,
        seed=args.seed,
        embedding_model=str(rag_cfg["embedding"].get("model")),
        embedding_backend=str(rag_cfg["embedding"].get("backend", "auto")),
        embedding_dim=int(rag_cfg["embedding"].get("dim", 384)),
        chunk_size=int(rag_cfg["chunking"].get("chunk_size", 500)),
        chunk_overlap=int(rag_cfg["chunking"].get("chunk_overlap", 50)),
        top_k=int(rag_cfg.get("retrieval", {}).get("top_k", 5)),
        temperature=float(gen.get("temperature", 0.0)),
        max_tokens=int(gen.get("max_tokens", 512)),
        timeout=float(gen.get("timeout", 60)),
        retries=int(gen.get("retries", 2)),
        retry_backoff_base=float(gen.get("retry_backoff_base", 2.0)),
        retry_backoff_max=float(gen.get("retry_backoff_max", 60.0)),
        request_interval_seconds=float(gen.get("request_interval_seconds", 0.0)),
        max_workers=int(args.max_workers if args.max_workers is not None else gen.get("max_workers", 1)),
        unknown_lambda=float(scoring.get("unknown_lambda", 0.5)),
        refusal_penalty=float(scoring.get("refusal_penalty", 0.5)),
        false_acceptance_penalty_value=float(scoring.get("false_acceptance_penalty", 1.0)),
        thresholds=[float(x) for x in scoring.get("thresholds", [0.3, 0.5, 0.7, 1.0])],
        resume=not args.no_resume,
        force=args.force,
    )

    # ---- L1(全局)与 L2(per-example)校准,合并到同一批 eval_rows 对比 ----
    # 探路采样时:L1 仍需全部 Reserve 估零分布,但评估目标只保留白名单 audit。
    whitelist = set(shadow_manifest.get("eval_audit_whitelist") or [])
    main_rows = list(read_jsonl(main_scores_path))
    if whitelist:
        main_rows = [r for r in main_rows if r.get("group") == "Reserve" or str(r.get("audit_id")) in whitelist]
    l1 = calibrate_membership_scores(main_rows)
    l1_rows = l1["eval_rows"]  # 含 group / cg_cvg / pcv_score_calibrated
    shadow_rows_list = [list(read_jsonl(p)) for p in shadow_manifest["shadow_score_paths"]]
    l2 = calibrate_l2_shadow(main_rows, shadow_rows_list)
    l2_by_aid = {str(r.get("audit_id")): r for r in l2["eval_rows"]}
    # 把 L2 分按 audit_id 并入 L1 eval_rows。
    merged = []
    for r in l1_rows:
        aid = str(r.get("audit_id"))
        if aid in l2_by_aid:
            row = dict(r)
            row[L2_KEY] = l2_by_aid[aid][L2_KEY]
            row["pcv_score_l2_z"] = l2_by_aid[aid].get("pcv_score_l2_z")
            merged.append(row)

    # ---- 三方对比表 ----
    def metrics(key):
        s = summarize_membership_scores(merged, score_key=key)
        return s["AUC"], s["TPR@1%FPR"], s["TPR@5%FPR"]

    print(f"\n===== PCV-MIA L2 shadow 校准: {ds} (eval={len(merged)}, K={l2['num_shadows']}) =====\n")
    print(f"shadow_size={shadow_manifest['shadow_size']}/{shadow_manifest['reserve_total']}  "
          f"σ_floor={_fmt(l2['sigma_floor'])}  用兜底σ的样本={l2['degenerate_examples']}")
    print(f"\n  {'终分':22s} {'AUC':>8s} {'TPR@1%FPR':>11s} {'TPR@5%FPR':>11s}")
    rows_for = [("cg_cvg(旧:减法)", "cg_cvg"), ("L1(Reserve群体)", PERCENTILE_KEY), ("L2(shadow逐样本)", L2_KEY)]
    table = {}
    for label, key in rows_for:
        auc, t1, t5 = metrics(key)
        table[key] = {"AUC": auc, "TPR@1%FPR": t1, "TPR@5%FPR": t5}
        print(f"  {label:22s} {_fmt(auc):>8s} {_fmt(t1):>11s} {_fmt(t5):>11s}")

    # ---- L2 阴性对照:扣先验后 True_Non 的 Φ(z) 应≈0.5、KB→1 ----
    def grp_mean(key, g):
        vals = [float(r.get(key, 0.0)) for r in merged if r.get("group") == g]
        return mean(vals) if vals else float("nan")
    print("\n[L2 阴性对照] Φ(z) 组均值(True_Non 越接近 0.5 越好=先验扣净;KB 越接近 1 越好):")
    print(f"    KB_Member       Φ(z)={grp_mean(L2_KEY,'KB_Member'):.3f}  z={grp_mean('pcv_score_l2_z','KB_Member'):+.3f}")
    print(f"    True_Non_Member Φ(z)={grp_mean(L2_KEY,'True_Non_Member'):.3f}  z={grp_mean('pcv_score_l2_z','True_Non_Member'):+.3f}")
    cg_auc = table["cg_cvg"]["AUC"]
    l2_auc = table[L2_KEY]["AUC"]
    print(f"\n[go/no-go] L2 AUC={_fmt(l2_auc)} vs cg_cvg={_fmt(cg_auc)}: "
          + ("L2 胜出,扣先验有效" if (l2_auc and cg_auc and l2_auc > cg_auc) else "L2 未超过 cg_cvg,需查 shadow 多样性/数量"))

    # ---- 归档 ----
    run_id = current_run_id()
    generated_at = local_timestamp()
    rdir = run_dir(ds, run_id)
    report = {
        "dataset": ds, "kind": "l2_shadow", "run_id": run_id, "generated_at": generated_at,
        "eval_samples": len(merged), "shadow_manifest": shadow_manifest,
        "sigma_floor": l2["sigma_floor"], "degenerate_examples": l2["degenerate_examples"],
        "comparison": table,
        "l2_negative_control": {
            "phi_z_kb": grp_mean(L2_KEY, "KB_Member"), "phi_z_true_non": grp_mean(L2_KEY, "True_Non_Member"),
        },
        "victim_profile_used": profile,
    }
    write_json(report, rdir / f"{ds}_l2_shadow_{run_id}.json")
    append_index(ds, {
        "run_id": run_id, "generated_at": generated_at, "kind": "l2_shadow", "dataset": ds,
        "victim_model": os.environ.get("PCV_VICTIM_MODEL", ""), "num_shadows": l2["num_shadows"],
        "eval_samples": len(merged),
        "auc_cg_cvg": cg_auc, "auc_l1": table[PERCENTILE_KEY]["AUC"], "auc_l2": l2_auc,
        "tpr1_cg_cvg": table["cg_cvg"]["TPR@1%FPR"], "tpr1_l2": table[L2_KEY]["TPR@1%FPR"],
    })
    print(f"\n[归档] run_id={run_id}  本次报告: {rdir / f'{ds}_l2_shadow_{run_id}.json'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
