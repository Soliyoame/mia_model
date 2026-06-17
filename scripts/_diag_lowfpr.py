"""低 FPR 区诊断(临时,纯离线无 API):解释 L1 经验百分位为何 TPR@1%FPR=n/a。

读 outputs/scores/<ds>_pcv_scores.jsonl，做 L1 校准（加 percentile / z-score），
对 cvg_rag / cg_cvg / pcv_score / L1-percentile / L1-zscore 五个终分分别算
AUC + TPR@1%FPR + TPR@5%FPR，并打印"顶端坍缩"诊断：
  - True_Non 负样本数 n_neg、1/n_neg（看 1%FPR 是否实际等价于"零误报"）
  - 有多少 KB / True_Non 的经验百分位顶到 1.0（顶端并列封顶 → 无法零误报）

用法： python scripts/_diag_lowfpr.py --dataset edgar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import summarize_membership_scores
from src.scoring.calibration import (
    PERCENTILE_KEY,
    ZSCORE_KEY,
    CALIBRATION_SOURCE_KEY,
    CALIBRATION_GROUP,
    calibrate_membership_scores,
)
from src.utils.io import read_jsonl


def _fmt(v):
    return "n/a" if v is None else f"{v:.3f}"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="edgar")
    args = ap.parse_args()
    ds = args.dataset

    scores_path = PROJECT_ROOT / "outputs" / "scores" / f"{ds}_pcv_scores.jsonl"
    rows = list(read_jsonl(scores_path))

    calib = calibrate_membership_scores(rows)  # 加 percentile + z，并剔除 Reserve
    eval_rows = calib["eval_rows"]

    n_kb = sum(1 for r in eval_rows if r.get("group") == "KB_Member")
    n_neg = sum(1 for r in eval_rows if r.get("group") != "KB_Member")
    reserve_vals = [
        float(r.get(CALIBRATION_SOURCE_KEY, 0.0))
        for r in rows if str(r.get("group")) == CALIBRATION_GROUP
    ]
    reserve_max = max(reserve_vals) if reserve_vals else float("nan")

    print(f"\n===== 低 FPR 诊断: {ds} =====")
    print(f"eval: KB_Member={n_kb}, 负类(True_Non)={n_neg}, "
          f"Reserve(零分布)={calib['reference_count']}")
    print(f"1%FPR 的最小可分辨步长 = 1/{n_neg} = {1.0/n_neg:.4f}"
          f"  → {'1%FPR 实际等价“零误报”（1/n_neg>1%）' if 1.0/n_neg > 0.01 else '可取到真正的 1%'}")
    print(f"Reserve cvg_rag 最大值 = {reserve_max:+.4f}")

    # 顶端坍缩:有多少样本 cvg_rag 超过 Reserve 上界 → 经验百分位全=1.0(并列封顶)。
    kb_capped = sum(1 for r in eval_rows
                    if r.get("group") == "KB_Member" and abs(float(r.get(PERCENTILE_KEY, 0)) - 1.0) < 1e-9)
    neg_capped = sum(1 for r in eval_rows
                     if r.get("group") != "KB_Member" and abs(float(r.get(PERCENTILE_KEY, 0)) - 1.0) < 1e-9)
    print(f"\n[顶端坍缩] 经验百分位=1.0（cvg_rag>Reserve上界，并列封顶）的样本：")
    print(f"    KB_Member   {kb_capped}/{n_kb}")
    print(f"    True_Non    {neg_capped}/{n_neg}   "
          f"← 只要这里>0，零误报就够不到顶段 → L1 百分位 TPR@1%FPR=n/a")

    print(f"\n  {'终分':28s} {'AUC':>8s} {'TPR@1%FPR':>11s} {'TPR@5%FPR':>11s}")
    for label, key in [
        ("cvg_rag(原始检索信号)", CALIBRATION_SOURCE_KEY),
        ("cg_cvg(减法,当前主分)", "cg_cvg"),
        ("pcv_score(质量加权)", "pcv_score"),
        ("L1 经验百分位", PERCENTILE_KEY),
        ("L1 z-score", ZSCORE_KEY),
    ]:
        s = summarize_membership_scores(eval_rows, score_key=key)
        print(f"  {label:28s} {_fmt(s['AUC']):>8s} "
              f"{_fmt(s['TPR@1%FPR']):>11s} {_fmt(s['TPR@5%FPR']):>11s}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
