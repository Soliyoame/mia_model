"""阈值 → FPR/TPR/Accuracy 关系表 + 全局 AUC/TPR@1%FPR(离线无 API)。

固定一个【分】(默认 cvg_rag),扫所有判定【阈值】,每个阈值给一组 FPR/TPR/Accuracy;
表头给【指标】AUC、TPR@1%FPR、TPR@5%FPR(阈值无关的全局量),厘清三者关系:
  AUC        = 整条 (FPR,TPR) 曲线下面积
  TPR@x%FPR  = FPR 压到 x% 时(那一段阈值里)能达到的最高 TPR
低 FPR 区的阈值行用 <=1%/<=5% 标出,便于看 TPR@1%FPR 来自哪些阈值。

用法: python scripts/_diag_threshold_table.py --dataset edgar --score cvg_rag
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import summarize_membership_scores
from src.utils.io import read_jsonl


def fmt(v):
    return "n/a" if v is None else f"{v:.3f}"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="edgar")
    ap.add_argument("--score", default="cvg_rag")
    a = ap.parse_args()

    rows = list(read_jsonl(PROJECT_ROOT / "outputs" / "scores" / f"{a.dataset}_pcv_scores.jsonl"))
    rows = [r for r in rows if r.get("group") != "Reserve"]   # 排除校准组
    nkb = sum(1 for r in rows if r.get("group") == "KB_Member")
    ntn = sum(1 for r in rows if r.get("group") == "True_Non_Member")

    s = summarize_membership_scores(rows, score_key=a.score)
    print(f"\n=== 阈值-指标关系: {a.dataset} / 分={a.score} (KB={nkb}, TN={ntn}) ===")
    print(f"FPR 最小可分辨步长 = 1/{ntn} = {1.0/ntn:.4f}（决定 1%FPR 是否=零误报）")
    print(f"全局指标(阈值无关): AUC={fmt(s['AUC'])}  TPR@1%FPR={fmt(s['TPR@1%FPR'])}  TPR@5%FPR={fmt(s['TPR@5%FPR'])}\n")
    print(f"  {'阈值':>8s} {'FPR':>7s} {'TPR':>7s} {'Accuracy':>9s}  低FPR区")
    for r in sorted(s["threshold_curve"], key=lambda x: x["threshold"]):
        mark = "<=1%FPR" if r["FPR"] <= 0.01 else ("<=5%FPR" if r["FPR"] <= 0.05 else "")
        print(f"  {r['threshold']:>8.3f} {r['FPR']:>7.3f} {r['TPR']:>7.3f} {r['Accuracy']:>9.3f}  {mark}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
