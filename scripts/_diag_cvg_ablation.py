"""cvg 公式成分消融(离线无 API)。

方法学声明:这是【消融分析】,展示公式各成分对判别力的贡献,**不是**在测试集上挑最优;
任何最终公式选择都须在独立数据集/验证集再确认,以免 data snooping。
流程:先复现已知 V0=cvg_rag、P1=cg_cvg 作 sanity check,再看新变体。

评估口径统一:正类=KB_Member,排除 Reserve,报 AUC(+95% bootstrap CI)/ d'(信噪比)/ TPR@1%FPR / TPR@5%FPR。

变体:
  V0 base   sup + cor - fap         (= cvg_rag,sanity)
  V1 no_fap sup + cor               (去误受项:实证它 AUC≈0.5 是死重)
  V2 sup    sup                     (仅 support)
  V3 cor    cor                     (仅 correction)
  P1 sub_all (sup+cor-fap) - (LLM同式)   (= cg_cvg,sanity:整体减先验)
  P2 sub_cor sup + (cor - cor_llm) - fap (只扣 correction 的 LLM 先验,support 不动)
  P3 sub_cor_no_fap sup + (cor - cor_llm)(P2 再去误受)

用法: python scripts/_diag_cvg_ablation.py --dataset edgar
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


def dprime(docs, key):
    kb = [float(d[key]) for d in docs if d.get("group") == POS]
    tn = [float(d[key]) for d in docs if d.get("group") == "True_Non_Member"]
    if not kb or not tn:
        return None
    mk, mt = mean(kb), mean(tn)
    ss = sum((x - mk) ** 2 for x in kb) + sum((x - mt) ** 2 for x in tn)
    pooled = math.sqrt(ss / (len(kb) + len(tn)))
    return (mk - mt) / pooled if pooled else 0.0


def boot_auc_ci(docs, key, n=1000, seed=42):
    rng = random.Random(seed)
    m = len(docs)
    aucs = []
    for _ in range(n):
        sample = [docs[rng.randrange(m)] for _ in range(m)]
        a = roc_auc(sample, score_key=key, positive_group=POS)
        if a is not None:
            aucs.append(a)
    if not aucs:
        return None, None
    aucs.sort()
    return aucs[int(0.025 * len(aucs))], aucs[int(0.975 * len(aucs))]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="edgar")
    a = ap.parse_args()

    pair_path = PROJECT_ROOT / "outputs" / "scores" / f"{a.dataset}_pcv_scores_pair_scores.jsonl"
    pairs = list(read_jsonl(pair_path))

    by = defaultdict(list)
    for r in pairs:
        by[str(r.get("audit_id"))].append(r)

    docs = []
    for aid, rs in by.items():
        g = rs[0].get("group")
        def avg(k):
            return mean([float(x.get(k, 0.0)) for x in rs]) if rs else 0.0
        sr, cr, fr = avg("support_score_rag"), avg("correction_score_rag"), avg("false_acceptance_penalty_rag")
        sl, cl, fl = avg("support_score_llm"), avg("correction_score_llm"), avg("false_acceptance_penalty_llm")
        d = {"audit_id": aid, "group": g}
        d["V0_base"] = sr + cr - fr           # = cvg_rag
        d["V1_no_fap"] = sr + cr
        d["V2_sup"] = sr
        d["V3_cor"] = cr
        d["P1_sub_all"] = (sr + cr - fr) - (sl + cl - fl)   # = cg_cvg
        d["P2_sub_cor"] = sr + (cr - cl) - fr
        d["P3_sub_cor_no_fap"] = sr + (cr - cl)
        docs.append(d)

    docs = [d for d in docs if d["group"] != "Reserve"]
    nkb = sum(1 for d in docs if d["group"] == POS)
    ntn = sum(1 for d in docs if d["group"] == "True_Non_Member")

    print(f"\n=== cvg 公式成分消融: {a.dataset} (KB={nkb}, TN={ntn}, 1%FPR≈零误报 since 1/{ntn}>1%) ===")
    print("    [消融分析,非测试集选优;最终选择须独立集确认]\n")
    variants = [
        ("V0 base  sup+cor-fap (=cvg_rag)", "V0_base"),
        ("V1 no_fap sup+cor", "V1_no_fap"),
        ("V2 sup-only", "V2_sup"),
        ("V3 cor-only", "V3_cor"),
        ("P1 sub_all (=cg_cvg)", "P1_sub_all"),
        ("P2 sub_cor (只扣cor先验)", "P2_sub_cor"),
        ("P3 sub_cor+no_fap", "P3_sub_cor_no_fap"),
    ]
    print(f"  {'变体':34s} {'AUC':>6s} {'95%CI':>15s} {'dprime':>7s} {'TPR@1%':>7s} {'TPR@5%':>7s}")
    for lab, k in variants:
        s = summarize_membership_scores(docs, score_key=k)
        au = s["AUC"]
        lo, hi = boot_auc_ci(docs, k)
        dp = dprime(docs, k)
        t1, t5 = s["TPR@1%FPR"], s["TPR@5%FPR"]
        ci = f"[{lo:.3f},{hi:.3f}]" if lo is not None else "n/a"
        print(f"  {lab:34s} {au:>6.3f} {ci:>15s} {dp:>+7.3f} "
              f"{('n/a' if t1 is None else f'{t1:.3f}'):>7s} {('n/a' if t5 is None else f'{t5:.3f}'):>7s}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
