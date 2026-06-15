"""只读诊断：验证"方案 D"的两块基石(不调用 LLM、不改任何产物)。

检验1 — selection bias：当前"产不出 fact 就丢整篇样本"是否泄漏组别？
        用"该文档能否产出 >=1 条 fact"这个 0/1 特征，算 KB_Member vs True_Non_Member 的 AUC。
        AUC≈0.5 => 丢弃无偏，方案 D 的"消 bias"卖点不成立；
        AUC>0.55 => 可抽取性本身就是 shortcut，当前结果混了 selection 泄漏。

检验2 — attackability 是否预测信号信噪比(逆方差加权的前提)？
        把每个 fact 的 cg_cvg 按其 attackability_score 分桶，看每桶 cg_cvg 的
        KB vs True_Non 可分性(AUC)。高桶 AUC 明显更高 => 按 attackability 加权有据；
        各桶无差别 => 加权退化成简单平均(无害)，但该换权重变量。

用法：python scripts/_diag_selection_quality.py
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "datasets/benchmarks/enron_attack_benchmark.jsonl"
FACTS = ROOT / "outputs/facts/enron_facts.jsonl"
QUERIES = ROOT / "outputs/paired_queries/enron_paired_queries.jsonl"
PAIR_SCORES = ROOT / "outputs/scores/enron_pcv_scores_pair_scores.jsonl"

POS, NEG = "KB_Member", "True_Non_Member"


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def auc(pos_vals: list[float], neg_vals: list[float]) -> float | None:
    """Mann-Whitney AUC，ties 计 0.5(与项目 roc_auc 口径一致)。"""
    if not pos_vals or not neg_vals:
        return None
    wins = 0.0
    for p in pos_vals:
        for n in neg_vals:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(pos_vals) * len(neg_vals))


def main() -> None:
    # ---------- 检验1：selection bias ----------
    fact_audits = {str(r["audit_id"]) for r in read_jsonl(FACTS)}
    cover = {POS: [], NEG: []}
    doc_counts = {POS: 0, NEG: 0}
    for r in read_jsonl(BENCH):
        g = str(r.get("group"))
        if g in cover:
            doc_counts[g] += 1
            cover[g].append(1.0 if str(r["audit_id"]) in fact_audits else 0.0)

    print("=" * 70)
    print("[检验1] selection bias：'能否产出>=1条fact' 对 KB vs True_Non 的可分性")
    print("-" * 70)
    for g in (POS, NEG):
        n = doc_counts[g]
        k = int(sum(cover[g]))
        print(f"  {g:16s}: {k}/{n} 篇产出fact  覆盖率={k/n:.3f}" if n else f"  {g}: 无文档")
    a1 = auc(cover[POS], cover[NEG])
    print(f"\n  覆盖率特征 AUC(KB为正类) = {a1:.4f}" if a1 is not None else "  AUC 无法计算")
    if a1 is not None:
        gap = abs(a1 - 0.5)
        if gap < 0.03:
            print("  => AUC≈0.5：丢弃基本无偏，方案D的'消bias'动机弱。")
        elif a1 > 0.5:
            print(f"  => AUC={a1:.3f}>0.5：KB更容易产出fact，'可抽取性'泄漏组别(selection shortcut)。")
        else:
            print(f"  => AUC={a1:.3f}<0.5：True_Non更容易产出fact(反向泄漏)。")

    # ---------- 检验2：attackability 是否预测信噪比 ----------
    # pair_id -> fact_id
    pair2fact = {str(r["pair_id"]): str(r["fact_id"]) for r in read_jsonl(QUERIES) if r.get("pair_id") and r.get("fact_id")}
    # fact_id -> attackability
    fact2att = {}
    for r in read_jsonl(FACTS):
        em = r.get("entity_metadata") or {}
        fact2att[str(r["fact_id"])] = float(em.get("attackability_score") or 0.0)

    # 每个评估 pair：(group, cg_cvg, attackability)
    rows = []
    for r in read_jsonl(PAIR_SCORES):
        g = str(r.get("group"))
        if g not in (POS, NEG):
            continue
        fid = pair2fact.get(str(r.get("pair_id")))
        att = fact2att.get(fid) if fid else None
        if att is None:
            continue
        rows.append((g, float(r.get("cg_cvg") or 0.0), att))

    print()
    print("=" * 70)
    print("[检验2] attackability 是否预测 cg_cvg 的信号质量")
    print("-" * 70)
    print(f"  可join的评估pair数 = {len(rows)}")
    atts = sorted(r[2] for r in rows)
    if rows:
        # 全体基线 AUC
        base = auc([c for g, c, a in rows if g == POS], [c for g, c, a in rows if g == NEG])
        print(f"  全体 cg_cvg AUC = {base:.4f}" if base is not None else "  全体AUC NA")
        print(f"  attackability 分布: min={atts[0]:.3f} 中位={atts[len(atts)//2]:.3f} max={atts[-1]:.3f}")
        # 三分位分桶
        n = len(atts)
        q1, q2 = atts[n // 3], atts[2 * n // 3]
        buckets = {"low": [], "mid": [], "high": []}
        for g, c, a in rows:
            b = "low" if a <= q1 else ("mid" if a <= q2 else "high")
            buckets[b].append((g, c))
        print(f"\n  按 attackability 三分桶(切点 {q1:.3f} / {q2:.3f}):")
        print(f"  {'bucket':8s} {'n':>4s} {'KB均值':>9s} {'TN均值':>9s} {'cg_cvg AUC':>11s}")
        for b in ("low", "mid", "high"):
            bp = [c for g, c in buckets[b] if g == POS]
            bn = [c for g, c in buckets[b] if g == NEG]
            ab = auc(bp, bn)
            mp = mean(bp) if bp else 0.0
            mn = mean(bn) if bn else 0.0
            astr = f"{ab:.4f}" if ab is not None else "NA"
            print(f"  {b:8s} {len(buckets[b]):>4d} {mp:>9.3f} {mn:>9.3f} {astr:>11s}")
        print("\n  => high桶AUC明显>low桶 => attackability预测信号质量，加权有据；")
        print("     各桶无差别 => 加权≈简单平均(无害)，但该换权重变量。")


if __name__ == "__main__":
    main()
