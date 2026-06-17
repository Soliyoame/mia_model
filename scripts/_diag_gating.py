"""LLM-Knowledge Gating(先验分层评估)+ per-term 去偏对比(离线无 API)。

用 correction_llm 当"该样本是否已被 LLM 知道"的门控信号;用 Reserve 的 cor_llm P-分位定阈 τ
(源外、防 data snooping),把评估样本分 LLM_unknown / LLM_known 两层。在 全集/两层 上评估
cvg_rag 与 cvg_debiased(per-term)的 AUC(+bootstrap CI)/TPR@1%/TPR@5% + 层内 n + 门控比例。

为让 edgar(penalty=0)与 enron(penalty=1.0 旧)对称,统一从 pair 分项现算【去误受版】:
  cvg_rag        = mean(sup_rag + cor_rag)
  cvg_debiased   = mean(sup_rag + cor_rag - cor_llm)   # per-term:只扣 correction 先验
  correction_llm = mean(cor_llm)                        # 门控信号

用法: python scripts/_diag_gating.py --dataset edgar [--tau-quantile 0.90]
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import roc_auc, summarize_membership_scores
from src.utils.io import read_jsonl

POS = "KB_Member"
EVAL = ("KB_Member", "True_Non_Member")


def quantile(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    i = q * (len(s) - 1)
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (i - lo)


def boot_ci(docs, key, n=1000, seed=42):
    rng = random.Random(seed)
    m = len(docs)
    aucs = []
    for _ in range(n):
        samp = [docs[rng.randrange(m)] for _ in range(m)]
        a = roc_auc(samp, score_key=key, positive_group=POS)
        if a is not None:
            aucs.append(a)
    if not aucs:
        return None, None
    aucs.sort()
    return aucs[int(0.025 * len(aucs))], aucs[int(0.975 * len(aucs))]


def fmt(v):
    return "n/a" if v is None else f"{v:.3f}"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="edgar")
    ap.add_argument("--tau-quantile", type=float, default=0.90)
    a = ap.parse_args()
    ds = a.dataset

    pairs = list(read_jsonl(PROJECT_ROOT / "outputs" / "scores" / f"{ds}_pcv_scores_pair_scores.jsonl"))
    by = defaultdict(list)
    for r in pairs:
        by[str(r.get("audit_id"))].append(r)

    docs = []
    for aid, rs in by.items():
        def avg(k):
            return mean([float(x.get(k, 0.0)) for x in rs]) if rs else 0.0
        sr, cr, cl = avg("support_score_rag"), avg("correction_score_rag"), avg("correction_score_llm")
        docs.append({"audit_id": aid, "group": rs[0].get("group"),
                     "cvg_rag": sr + cr, "cvg_debiased": sr + cr - cl, "correction_llm": cl})

    res = [d["correction_llm"] for d in docs if d["group"] == "Reserve"]
    tau = quantile(res, a.tau_quantile)
    ev = [d for d in docs if d["group"] in EVAL]
    for d in ev:
        d["layer"] = "known" if d["correction_llm"] > tau else "unknown"
    known = [d for d in ev if d["layer"] == "known"]
    unknown = [d for d in ev if d["layer"] == "unknown"]

    def nkbtn(g):
        return f"{sum(1 for d in g if d['group']==POS)}/{sum(1 for d in g if d['group']=='True_Non_Member')}"

    print(f"\n=== LLM-Knowledge Gating + per-term: {ds} ===")
    print(f"门控信号=correction_llm  τ=Reserve P{int(a.tau_quantile*100)}={tau:+.3f} (Reserve n={len(res)})")
    print(f"门控比例(L_已知占比)= {len(known)}/{len(ev)} = {len(known)/max(1,len(ev)):.1%}\n")
    print(f"  {'层':8s} {'终分':14s} {'n(KB/TN)':>9s} {'AUC':>6s} {'95%CI':>15s} {'T@1%':>6s} {'T@5%':>6s}")
    for name, g in [("全集", ev), ("L_未知", unknown), ("L_已知", known)]:
        valid = bool(g) and any(d["group"] == POS for d in g) and any(d["group"] == "True_Non_Member" for d in g)
        for key in ["cvg_rag", "cvg_debiased"]:
            if not valid:
                print(f"  {name:8s} {key:14s} {nkbtn(g):>9s}  (层内缺正/负类,跳过)")
                continue
            s = summarize_membership_scores(g, score_key=key)
            lo, hi = boot_ci(g, key)
            ci = f"[{lo:.3f},{hi:.3f}]" if lo is not None else "n/a"
            print(f"  {name:8s} {key:14s} {nkbtn(g):>9s} {fmt(s['AUC']):>6s} {ci:>15s} "
                  f"{fmt(s['TPR@1%FPR']):>6s} {fmt(s['TPR@5%FPR']):>6s}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
