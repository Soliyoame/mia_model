"""临时诊断:定位 cvg_llm=0.606 阴性对照失败的根因(只读现有产物,不调 LLM)。"""
import sys, json, statistics
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np

def rd(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

scores = rd("outputs/scores/enron_pcv_scores.jsonl")
stance = rd("outputs/parsed_stance/enron_parsed_stance.jsonl")
facts  = rd("outputs/facts/enron_facts.jsonl")
bench  = rd("datasets/benchmarks/enron_attack_benchmark.jsonl")
GROUPS = ("KB_Member", "True_Non_Member")

def fast_auc(pos, neg):
    """平均秩 AUC,正确处理 ties。"""
    allv = np.concatenate([pos, neg]); lab = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
    order = np.argsort(allv, kind="mergesort"); av = allv[order]; lb = lab[order]
    ranks = np.empty(len(av)); i = 0
    while i < len(av):
        j = i
        while j < len(av) and av[j] == av[i]: j += 1
        ranks[i:j] = (i + 1 + j) / 2.0; i = j
    rp = ranks[lb == 1].sum()
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))

ev = [r for r in scores if r["group"] in GROUPS]
print("eval n =", len(ev), dict(Counter(r["group"] for r in ev)))

# ===== 1) bootstrap CI:确认 cvg_llm 是否真显著 > 0.5 =====
print("\n[1] Bootstrap 95% CI (3000 重采样, 正类=KB_Member)")
for key in ("cvg_rag", "cvg_llm", "cg_cvg"):
    pos = np.array([float(r[key]) for r in ev if r["group"] == "KB_Member"])
    neg = np.array([float(r[key]) for r in ev if r["group"] == "True_Non_Member"])
    base = fast_auc(pos, neg)
    rng = np.random.default_rng(0); a = []
    for _ in range(3000):
        a.append(fast_auc(rng.choice(pos, len(pos)), rng.choice(neg, len(neg))))
    lo, hi = np.percentile(a, [2.5, 97.5])
    flag = "  <-- CI 下界>0.5,先验泄漏确凿" if (key == "cvg_llm" and lo > 0.5) else ""
    print(f"    {key:9s} AUC={base:.3f}  CI=[{lo:.3f}, {hi:.3f}]{flag}")

# ===== 2) LLM-only 下两组的 stance 行为分解(找哪个行为驱动 cvg_llm 偏高) =====
print("\n[2] LLM-only(无检索)两组行为率 —— 看 KB 是否'不看文档也更懂'")
llm = [r for r in stance if r["mode"] == "llm_only"]
for ct in ("true", "counterfactual"):
    print(f"  -- claim_type = {ct}")
    for g in GROUPS:
        sub = [r for r in llm if r["group"] == g and r["claim_type"] == ct]
        n = len(sub) or 1
        rate = lambda k: sum(1 for r in sub if r.get(k)) / n
        if ct == "true":
            print(f"    {g:16s} n={len(sub):3d}  support={rate('supports_true_claim'):.2f} "
                  f"reject={rate('rejects_true_claim'):.2f} unknown={rate('says_unknown'):.2f} refuse={rate('refuses'):.2f}")
        else:
            print(f"    {g:16s} n={len(sub):3d}  correct={rate('corrects_to_original_entity'):.2f} "
                  f"reject_cf={rate('rejects_counterfactual'):.2f} accept_cf={rate('accepts_counterfactual'):.2f} unknown={rate('says_unknown'):.2f}")

# ===== 3) RAG 模式同样分解(对照:检索后差异应放大) =====
print("\n[3] RAG(有检索)两组行为率 —— 与[2]对比看检索净增益")
rag = [r for r in stance if r["mode"] == "rag"]
for ct in ("true", "counterfactual"):
    print(f"  -- claim_type = {ct}")
    for g in GROUPS:
        sub = [r for r in rag if r["group"] == g and r["claim_type"] == ct]
        n = len(sub) or 1
        rate = lambda k: sum(1 for r in sub if r.get(k)) / n
        if ct == "true":
            print(f"    {g:16s} n={len(sub):3d}  support={rate('supports_true_claim'):.2f} "
                  f"reject={rate('rejects_true_claim'):.2f} unknown={rate('says_unknown'):.2f}")
        else:
            print(f"    {g:16s} n={len(sub):3d}  correct={rate('corrects_to_original_entity'):.2f} "
                  f"reject_cf={rate('rejects_counterfactual'):.2f} accept_cf={rate('accepts_counterfactual'):.2f}")

# ===== 4) fact 的 entity_type 分布两组对比(类型不平衡会造成先验差异) =====
print("\n[4] fact entity_type 分布(归一化占比)")
for g in GROUPS:
    fs = [f for f in facts if f["group"] == g]
    c = Counter(f["entity_type"] for f in fs); tot = sum(c.values()) or 1
    top = ", ".join(f"{k}={v/tot:.0%}" for k, v in c.most_common(8))
    print(f"    {g:16s} facts={len(fs):4d}  {top}")

# ===== 5) fact 难度指标两组对比 =====
print("\n[5] fact 难度均值(importance/replaceability/privacy/attackability)")
for g in GROUPS:
    fs = [f for f in facts if f["group"] == g]
    def m(k): return statistics.mean([float(f.get(k, 0)) for f in fs]) if fs else 0
    def ma(k): return statistics.mean([float(f.get("entity_metadata", {}).get(k, 0)) for f in fs]) if fs else 0
    print(f"    {g:16s} imp={m('importance'):.3f} repl={m('replaceability'):.3f} "
          f"priv={m('privacy_specificity'):.3f} attack={ma('attackability_score'):.3f} spec={ma('specificity'):.3f}")

# ===== 6) 文本统计两组对比(长度/实体) =====
print("\n[6] 文本统计均值(来自 benchmark metadata)")
bya = {b["audit_id"]: b for b in bench}
for g in GROUPS:
    rows = [bya[r["audit_id"]] for r in ev if r["group"] == g and r["audit_id"] in bya]
    def sm(fn): vals=[fn(b) for b in rows if fn(b) is not None]; return statistics.mean(vals) if vals else 0
    L  = sm(lambda b: float(len(b.get("text", ""))))
    sm_meta = lambda k: sm(lambda b: float((b.get("metadata", {}).get("source_metadata", {}) or {}).get(k) or 0))
    print(f"    {g:16s} n={len(rows):3d}  char_len={L:.0f} entity_count={sm_meta('entity_count'):.2f} entity_density={sm_meta('entity_density'):.4f}")
