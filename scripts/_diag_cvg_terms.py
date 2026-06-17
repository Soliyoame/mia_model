"""拆解 cvg 三项各自的判别力(临时诊断,纯离线无 API)。

读 pair_scores，按 audit 聚合 support/correction/false_accept 分项(RAG 与 LLM 先验),
排除 Reserve，算每项 + 完整 cvg 的 AUC 和信噪比 d'(KB vs True_Non)。
目的:看 cvg 的判别力主要来自哪一项、先验泄漏藏在哪一项，为"公式优化"提供数据依据。

用法: python scripts/_diag_cvg_terms.py --dataset edgar
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import roc_auc
from src.utils.io import read_jsonl


def dprime(rows, key):
    kb = [float(r[key]) for r in rows if r.get("group") == "KB_Member"]
    tn = [float(r[key]) for r in rows if r.get("group") == "True_Non_Member"]
    if not kb or not tn:
        return None
    mk, mt = mean(kb), mean(tn)
    ss = sum((x - mk) ** 2 for x in kb) + sum((x - mt) ** 2 for x in tn)
    pooled = math.sqrt(ss / (len(kb) + len(tn)))
    return (mk - mt) / pooled if pooled else 0.0


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

    # 按 audit 聚合各分项均值(文档级才是评估单位)。
    by = defaultdict(list)
    for r in pairs:
        by[str(r.get("audit_id"))].append(r)
    keys = ["support_score_rag", "correction_score_rag", "false_acceptance_penalty_rag",
            "support_score_llm", "correction_score_llm", "cvg_rag", "cvg_llm"]
    docs = []
    for aid, rs in by.items():
        d = {"audit_id": aid, "group": rs[0].get("group")}
        for k in keys:
            vals = [float(x.get(k, 0.0)) for x in rs]
            d[k] = mean(vals) if vals else 0.0
        docs.append(d)
    docs = [d for d in docs if d["group"] != "Reserve"]
    nkb = sum(1 for d in docs if d["group"] == "KB_Member")
    ntn = sum(1 for d in docs if d["group"] == "True_Non_Member")

    print(f"\n=== cvg 分项判别力: {a.dataset} (KB={nkb}, TN={ntn}) ===")
    print("   (AUC 离 0.5 越远越能分;<0.5 表示该项 KB 反而更低=反向信号)\n")
    print(f"  {'项':30s} {'AUC':>7s} {'可分性':>7s} {'dprime':>8s}")
    labels = [
        ("support(Q+,RAG)", "support_score_rag"),
        ("correction(Q-,RAG)", "correction_score_rag"),
        ("false_accept(Q-,RAG)", "false_acceptance_penalty_rag"),
        ("support(Q+,LLM先验)", "support_score_llm"),
        ("correction(Q-,LLM先验)", "correction_score_llm"),
        ("cvg_rag(完整)", "cvg_rag"),
        ("cvg_llm(完整先验)", "cvg_llm"),
    ]
    for lab, k in labels:
        au = roc_auc(docs, score_key=k, positive_group="KB_Member")
        dp = dprime(docs, k)
        sep = "n/a" if au is None else f"{max(au, 1 - au):.3f}"
        aus = "n/a" if au is None else f"{au:.3f}"
        dps = "n/a" if dp is None else f"{dp:+.3f}"
        print(f"  {lab:30s} {aus:>7s} {sep:>7s} {dps:>8s}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
