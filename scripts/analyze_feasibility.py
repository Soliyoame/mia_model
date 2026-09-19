"""可行性验证入口脚本(辅助脚本,不在 01-15 主流水线)。

中文说明
========
读取打分/基准/切分产物,跑 src.evaluation.feasibility 的三块分析,在控制台打印一张
方向性判据表;并把本次结果**按时间戳归档**(不覆盖历次)+ 生成一张**综合可视化图**:
  - 固定名 latest:  outputs/reports/{dataset}_feasibility.json
  - 带时间戳快照:   outputs/runs/{dataset}/{run_id}/{dataset}_feasibility_{run_id}.json + .png
  - 历次总表追加:   outputs/runs/{dataset}/index.jsonl
  - 历次 AUC 趋势:  outputs/runs/{dataset}/trend_feasibility.png

用法:
    python scripts/analyze_feasibility.py --dataset enron
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.feasibility import analyze_feasibility
from src.evaluation.plots import plot_feasibility, plot_run_trend
from src.scoring.calibration import (
    CALIBRATION_SOURCE_KEY,
    PERCENTILE_KEY,
    PRIMARY_CALIBRATED_KEY,
    ZSCORE_KEY,
    calibrate_membership_scores,
)
from src.utils.io import ensure_dir, load_yaml, read_jsonl, resolve_path, write_json
from src.utils.dataset_paths import resolve_dataset_dir
from src.utils.logger import setup_logging
from src.utils.run_context import append_index, current_run_id, index_path, local_timestamp, model_scoped_dir, run_dir


def parse_args() -> argparse.Namespace:
    """解析命令行参数(仅需 --dataset)。"""
    parser = argparse.ArgumentParser(
        description="PCV-MIA feasibility analysis: signal decomposition + shortcut baseline + source-overlap check."
    )
    parser.add_argument("--dataset", required=True)
    return parser.parse_args()


def _fmt(value: float | None) -> str:
    """AUC 等可能为 None,统一格式化。"""
    return "n/a" if value is None else f"{value:.3f}"


def _read_scale() -> str:
    """从 data_config.yaml 读当前 split.scale(读不到留空,不阻塞)。"""
    try:
        cfg = load_yaml(resolve_path("configs/data_config.yaml"))
        return str(cfg.get("split", {}).get("scale", ""))
    except Exception:
        return ""


def main() -> int:
    """脚本入口:跑可行性分析,打印判据表,并按时间戳归档 + 出综合图。"""
    # 强制 UTF-8 输出,避免 Windows 控制台默认 GBK 打印中文/特殊符号时报错。
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = parse_args()
    data_config = load_yaml(resolve_path("configs/data_config.yaml"))
    setup_logging("pcv_mia", log_file=resolve_path("datasets/logs/feasibility.log"), level="INFO")
    out_dir = ensure_dir(model_scoped_dir("outputs/reports", args.dataset))
    scores_dir = model_scoped_dir("outputs/scores", args.dataset)
    source_scores_path = scores_dir / f"{args.dataset}_pcv_scores_source_scores.jsonl"
    scores_path = source_scores_path if source_scores_path.exists() else scores_dir / f"{args.dataset}_pcv_scores.jsonl"
    report = analyze_feasibility(
        dataset=args.dataset,
        scores_path=scores_path,
        benchmark_path=resolve_path("datasets/benchmarks") / f"{args.dataset}_attack_benchmark.jsonl",
        splits_dir=resolve_dataset_dir(data_config, "splits_dir", args.dataset),
        output_path=out_dir / f"{args.dataset}_feasibility.json",  # 固定名 latest(兼容)
    )

    sig = report["signal_decomposition"]
    print(f"\n===== PCV-MIA 可行性验证: {args.dataset} (scored={report['scored_samples']}, eval={report.get('eval_samples')}) =====\n")
    print("[1] 信号拆解 AUC (正类=KB_Member,已排除 Reserve 校准组):")
    for key in ["cvg_rag", "cvg_llm", "cg_cvg", "pcv_score", ZSCORE_KEY, PERCENTILE_KEY]:
        print(f"    {key:22s} AUC = {_fmt(sig['auc'].get(key))}")
    print("\n    分组均值:")
    for group, m in sig["group_means"].items():
        print(
            f"    {group:16s} n={m['count']:3d}  "
            f"cvg_rag={_fmt(m['cvg_rag'])}  cvg_llm={_fmt(m['cvg_llm'])}  "
            f"cg_cvg={_fmt(m['cg_cvg'])}"
        )

    # [1.5] L1 群体校准对比(重点看 TPR@1%FPR,校准收益主要在低 FPR 区)
    calib = report.get("calibration", {})
    cmp = calib.get("comparison", {})
    print(
        f"\n[1.5] L1 群体校准 (零分布=Reserve, n={calib.get('reference_count')}, "
        f"μ={_fmt(calib.get('mu'))}, σ={_fmt(calib.get('sigma'))}):"
    )
    if calib.get("degenerate"):
        print("    [!] 零分布退化(Reserve 太少或 cvg_rag 全相同)——校准分不可靠,建议增大 split 的 reserve 目标。")
    print(f"    {'终分':22s} {'AUC':>8s} {'Acc':>7s} {'TPR@1%FPR':>11s} {'TPR@5%FPR':>11s}")
    for label, key in [
        ("cvg_rag(原始不扣)", CALIBRATION_SOURCE_KEY),
        ("z-score(L1主,推荐)", ZSCORE_KEY),
        ("经验百分位(L1辅)", PERCENTILE_KEY),
        ("cg_cvg(减法)", "cg_cvg"),
    ]:
        row = cmp.get(key, {})
        print(f"    {label:22s} {_fmt(row.get('AUC')):>8s} {_fmt(row.get('Accuracy')):>7s} {_fmt(row.get('TPR@1%FPR')):>11s} {_fmt(row.get('TPR@5%FPR')):>11s}")

    # [1.6] 阈值-指标关系表(默认分 cvg_rag):看阈值如何 trade-off FPR/TPR,及 AUC/TPR@x%FPR 的来源
    tt = report.get("threshold_table", {})
    print()
    print(f"[1.6] 阈值-指标关系表 (分={tt.get('score_key')}): "
          f"AUC={_fmt(tt.get('AUC'))} Accuracy={_fmt(tt.get('Accuracy@best'))} TPR@1%FPR={_fmt(tt.get('TPR@1%FPR'))} TPR@5%FPR={_fmt(tt.get('TPR@5%FPR'))}")
    print(f"    {'阈值':>8s} {'FPR':>7s} {'TPR':>7s} {'Acc':>7s}  低FPR区")
    for tr in tt.get("curve", []):
        fpr = float(tr.get("FPR", 0.0))
        mark = "<=1%FPR" if fpr <= 0.01 else ("<=5%FPR" if fpr <= 0.05 else "")
        print(f"    {float(tr['threshold']):>8.3f} {fpr:>7.3f} {float(tr['TPR']):>7.3f} {float(tr['Accuracy']):>7.3f}  {mark}")

    print("\n[2] shortcut baseline(文本统计特征可分性,越逼近 cvg_rag 越危险):")
    for key, value in report["shortcut_baseline"].items():
        if value is None:
            print(f"    {key:16s} n/a")
        else:
            print(f"    {key:16s} AUC={value['auc']:.3f}  可分性={value['separability']:.3f}")

    ov = report["source_overlap"]
    print("\n[3] 同源泄漏检查:")
    print(
        f"    KB={ov['kb_member_count']}  True_Non={ov['true_non_member_count']}  "
        f"source_key 交集={ov['source_key_overlap']}  退化率={ov['degraded_rate']:.1%}"
    )

    verdict = report["verdict"]
    print(f"\n===== 方向性判定: {verdict['direction']} =====")
    for reason in verdict["reasons"]:
        print(f"    {reason}")

    # ---- 按时间戳归档 + 可视化(每次运行不覆盖历次)----
    run_id = current_run_id()
    generated_at = local_timestamp()
    rdir = run_dir(args.dataset, run_id)
    score_rows = list(read_jsonl(scores_path))
    # 画图与判据表同口径:排除 Reserve 校准组、并带上校准分(供 ROC/AUC 子图)。
    plot_rows = calibrate_membership_scores(score_rows)["eval_rows"]

    snap = f"{args.dataset}_feasibility_{run_id}"  # 快照文件名带时间戳,单看文件名即知何时/何集
    write_json(report, rdir / f"{snap}.json")  # 本次快照
    png = plot_feasibility(
        report,
        plot_rows,
        rdir / f"{snap}.png",
        dataset=args.dataset,
        run_id=run_id,
        generated_at=generated_at,
    )
    auc = sig.get("auc", {})
    cmp = report.get("calibration", {}).get("comparison", {})
    append_index(
        args.dataset,
        {
            "run_id": run_id,
            "generated_at": generated_at,
            "kind": "feasibility",
            "dataset": args.dataset,
            "scale": _read_scale(),
            "victim_model": os.environ.get("PCV_VICTIM_MODEL", ""),
            "scored_samples": report.get("scored_samples"),
            "eval_samples": report.get("eval_samples"),
            "auc_cvg_rag": auc.get("cvg_rag"),
            "auc_cvg_llm": auc.get("cvg_llm"),
            "auc_pcv": auc.get("pcv_score"),
            "auc_calibrated": auc.get(PRIMARY_CALIBRATED_KEY),
            "auc_calibrated_pct": auc.get(PERCENTILE_KEY),
            "tpr1_cg_cvg": cmp.get("cg_cvg", {}).get("TPR@1%FPR"),
            "tpr1_calibrated": cmp.get(PRIMARY_CALIBRATED_KEY, {}).get("TPR@1%FPR"),
            "reserve_count": report.get("calibration", {}).get("reference_count"),
            "verdict": verdict.get("direction"),
        },
    )
    # 历次趋势图(只取 feasibility 行)
    hist = [r for r in read_jsonl(index_path(args.dataset)) if r.get("kind") == "feasibility"]
    trend = plot_run_trend(
        hist, index_path(args.dataset).parent / "trend_feasibility.png", dataset=args.dataset
    )

    print(f"\n[归档] run_id={run_id}  生成时间={generated_at}")
    print(f"    最新(latest): {out_dir / f'{args.dataset}_feasibility.json'}")
    print(f"    本次快照:     {rdir}")
    if png:
        print(f"    可视化图:     {png}")
    else:
        print("    可视化图:     (未生成 — 未安装 matplotlib,pip install matplotlib 后即可)")
    print(f"    历次总表:     {index_path(args.dataset)}")
    if trend:
        print(f"    趋势图:       {trend}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
