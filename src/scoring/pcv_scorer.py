"""PCV-MIA scoring.

This module computes the Paired Verification Score (PVS) used by PCV-MIA.

CVG = SupportScore(Q+) + CorrectionScore(Q-) - FalseAcceptancePenalty(Q-)
The operational black-box attack uses CVG_RAG directly. CVG_LLM and
CG-CVG = CVG_RAG - CVG_LLM are retained as experimental controls.

中文说明
========
本文件对应流水线第 11 步的"打分"部分，是把"模型的态度"换算成"成员可能性分数"的
核心算法。理解三个公式就理解了整个攻击的判定逻辑：

- 对每个事实，我们准备一对问题：Q+(真实声明) 和 Q-(反事实/伪造声明)。
- CVG(反事实验证差距) = 支持分(对Q+) + 纠正分(对Q-) - 误受惩罚(对Q-)。
  直觉：一个"真懂这份文档"的系统，应该【支持真实声明】并且【纠正伪造声明】；
  如果它把伪造声明也当真接受了，就要扣分。
- 同一套打分分别在两种模式下算一遍：CVG_RAG(带检索) 和 CVG_LLM(纯模型)。
- CG-CVG = CVG_RAG - CVG_LLM，即"检索到底带来了多少额外能力"。这个差值越大，
  说明该文档越可能真的躺在 RAG 知识库里(成员)。

输入：第 11 步前半段解析出的"态度(stance)"记录(每行一个 模式×声明类型 的结果)。
输出：pair、audit/chunk 与 source document 三个层级的分数文件 + manifest；论文主评估读 source 层。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

try:
    # 进度条；没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def support_score(row: dict[str, Any], unknown_lambda: float, refusal_penalty: float) -> float:
    """计算「支持分」：模型对【真实声明 Q+】的态度打分。

    参数:
        row: 一条解析后的态度记录,里面是各种布尔标记(是否支持/反对/不知道...)。
        unknown_lambda: 模型答「不知道」时要扣的分(惩罚系数)。
        refusal_penalty: 模型「拒绝回答」时要扣的分。
    返回:
        分数,大致在 -1.0 ~ 1.0,越高说明模型越支持这条真实声明。
    """
    # 模型明确支持真实声明 → 给满分 1.0
    if row.get("supports_true_claim"):
        return 1.0
    # 模型反对真实声明 → 给 -1.0
    if row.get("rejects_true_claim"):
        return -1.0
    # 模型说「不知道」→ 按 unknown_lambda 扣分
    if row.get("says_unknown"):
        return -float(unknown_lambda)
    # 模型拒绝回答 → 按 refusal_penalty 扣分
    if row.get("refuses"):
        return -float(refusal_penalty)
    # 以上都不是(答非所问/无关)→ 0 分
    return 0.0


def correction_score(row: dict[str, Any], unknown_lambda: float, refusal_penalty: float) -> float:
    """计算「纠正分」：模型对【反事实声明 Q-】的态度打分。

    反事实声明是我们故意伪造的(把真实实体换成假的)。一个真懂文档的系统应该能
    识破并纠正它，所以："纠正回原始实体"得分最高，"识破但没说出正确答案"次之，
    "把伪造的也当真接受"则要扣分。

    参数:
        row: 一条针对反事实声明的态度记录。
        unknown_lambda: 答「不知道」的惩罚系数。
        refusal_penalty: 「拒绝回答」的惩罚系数。
    返回:
        分数(约 -1.0 ~ 1.0),越高说明模型越能识破/纠正伪造声明。
    """
    # 直接把伪造实体纠正回正确的原始实体 → 最强信号,给 1.0
    if row.get("corrects_to_original_entity"):
        return 1.0
    # 识破并否定了伪造声明(但没给出正确值)→ 给 0.5
    if row.get("rejects_counterfactual"):
        return 0.5
    # 把伪造声明当真接受了 → 说明它没真懂,给 -1.0
    if row.get("accepts_counterfactual"):
        return -1.0
    # 说「不知道」→ 按系数扣分
    if row.get("says_unknown"):
        return -float(unknown_lambda)
    # 拒绝回答 → 按系数扣分
    if row.get("refuses"):
        return -float(refusal_penalty)
    # 其它(无关回答)→ 0 分
    return 0.0


def false_acceptance_penalty(row: dict[str, Any], penalty: float) -> float:
    """计算「误受惩罚」：如果模型把伪造声明当真接受了,额外扣的分。

    参数:
        row: 针对反事实声明的态度记录。
        penalty: 误受时扣的分值。
    返回:
        接受了伪造声明则返回 penalty,否则返回 0.0。
    """
    # 仅当模型"接受了反事实(伪造)声明"时才施加这个惩罚。
    return float(penalty) if row.get("accepts_counterfactual") else 0.0


def score_pair(
    plus: dict[str, Any] | None,
    minus: dict[str, Any] | None,
    *,
    unknown_lambda: float,
    refusal_penalty: float,
    false_acceptance_penalty_value: float,
) -> dict[str, Any]:
    """把"一对(Q+ 与 Q-)"的态度合成为这一对的 CVG 分数。

    参数:
        plus:  针对真实声明 Q+ 的态度记录(可能为 None,表示缺这条)。
        minus: 针对反事实声明 Q- 的态度记录(可能为 None)。
        unknown_lambda:                "不知道"的惩罚系数。
        refusal_penalty:               "拒绝"的惩罚系数。
        false_acceptance_penalty_value:"误受伪造"的惩罚分值。
    返回:
        含 support_score / correction_score / false_acceptance_penalty / cvg 的字典。
        其中 cvg = 支持分 + 纠正分 - 误受惩罚。
    """
    # 缺哪一边就给 0 分,保证缺数据时也能稳健计算。
    support = support_score(plus or {}, unknown_lambda, refusal_penalty) if plus else 0.0
    correction = correction_score(minus or {}, unknown_lambda, refusal_penalty) if minus else 0.0
    false_penalty = false_acceptance_penalty(minus or {}, false_acceptance_penalty_value) if minus else 0.0
    return {
        "support_score": support,
        "correction_score": correction,
        "false_acceptance_penalty": false_penalty,
        # 这一对的 CVG = 支持分 + 纠正分 - 误受惩罚。
        "cvg": support + correction - false_penalty,
    }


def compute_pcv_scores(
    dataset: str,
    parsed_stance_path: str | Path,
    output_path: str | Path,
    unknown_lambda: float = 0.5,
    refusal_penalty: float = 0.5,
    false_acceptance_penalty_value: float = 0.0,  # 默认关闭误受项(消融:干净集 AUC≈0.525 无判别力);设 >0 可恢复
    thresholds: list[float] | None = None,
    facts_path: str | Path | None = None,
    benchmark_path: str | Path | None = None,
    queries_path: str | Path | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Aggregate parsed stance rows into document-level PCV scores.

    中文说明：本函数是打分的主入口。它把"逐条态度记录"一步步聚合：
        态度记录 → 按 pair 归拢(把同一对的 RAG/LLM × 真/假 4 条凑齐) → 算每对的 CVG
        → 按 audit_id 聚合出 chunk/audit 诊断分 → 再按 source_key 聚合出论文主分。

    方案 D 的质量加权在这一步生效：每个 fact 带 quality_weight(=可攻击性分)，文档级分数
    输出三个口径，便于交叉验证"加权是否真的有用"：
        pcv_score           RAG-only PVS 简单平均(主分)。
        cg_cvg              RAG - LLM-only 的旧 context-gain 诊断口径。
        pcv_score_context_gain_weighted 旧质量加权 context-gain 诊断口径。
        pcv_score_primary   仅 primary fact 的旧 context-gain 诊断口径。
    若未提供 facts_path，则所有 fact 权重退化为 1.0、tier 视为 primary，三口径都等于简单平均
    ``pcv_score`` 始终是 RAG-only PVS；旧 context-gain 口径仅保留在显式诊断字段中。

    参数:
        dataset:            数据集名。
        parsed_stance_path: 上一步解析出的态度记录文件(jsonl)。
        output_path:        文档级分数的输出路径;同时会派生出 *_pair_scores.jsonl 和 manifest。
        unknown_lambda:     "不知道"的惩罚系数。
        refusal_penalty:    "拒绝"的惩罚系数。
        false_acceptance_penalty_value: "误受伪造"的惩罚分值。
        thresholds:         判定阈值列表;pcv_score 高于阈值则判为成员。默认 [0.3,0.5,0.7,1.0]。
        facts_path:         第 06 步的 facts.jsonl;用于按 fact_id 取 quality_weight/selection_tier。
                            为 None 时退化为不加权(等价旧行为)。
        resume:             断点续跑:结果已存在则跳过。
        force:              强制重算。
    返回:
        manifest(字典):统计信息与产物路径;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    # 成对分数的输出路径(在主输出名后加 _pair_scores)。
    pair_output = output.with_name(output.stem + "_pair_scores.jsonl")
    source_output = output.with_name(output.stem + "_source_scores.jsonl")
    coverage_output = output.with_name(output.stem + "_source_coverage.jsonl")
    # 断点续跑:结果文件非空且 manifest 存在,就跳过不重算。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing PCV scores: %s", output)
        return {"dataset": dataset, "output_path": str(output), "skipped_existing": True}

    # 没给阈值就用一组默认阈值。
    thresholds = thresholds or [0.3, 0.5, 0.7, 1.0]
    # fact_id → (quality_weight, selection_tier)。缺省权重 1.0、tier=primary(等价不加权)。
    fact_weight: dict[str, float] = {}
    fact_tier: dict[str, str] = {}
    fact_source: dict[str, tuple[str, str, str]] = {}
    if facts_path is not None and Path(facts_path).exists():
        for f in read_jsonl(facts_path):
            fid = str(f.get("fact_id"))
            fact_weight[fid] = float(f.get("quality_weight") or 1.0)
            fact_tier[fid] = str(f.get("selection_tier") or "primary")
            fact_source[fid] = (
                str(f.get("source_id") or f.get("doc_id") or f.get("audit_id") or ""),
                str(f.get("source_key") or f.get("source_id") or f.get("doc_id") or f.get("audit_id") or ""),
                str(f.get("doc_id") or ""),
            )
    benchmark_sources: dict[str, dict[str, Any]] = {}
    if benchmark_path is not None and Path(benchmark_path).exists():
        for row in read_jsonl(benchmark_path):
            source_key = str(row.get("source_key") or row.get("source_id") or row.get("audit_id"))
            item = benchmark_sources.setdefault(source_key, {
                "source_key": source_key,
                "source_id": row.get("source_id") or source_key,
                "group": row.get("group"),
                "audit_ids": set(),
            })
            item["audit_ids"].add(str(row.get("audit_id")))

    planned_pairs: dict[str, dict[str, Any]] = {}
    if queries_path is not None and Path(queries_path).exists():
        for row in read_jsonl(queries_path):
            if not row.get("accepted", True):
                continue
            pair_id = str(row.get("pair_id"))
            query_type = str(row.get("query_type") or "default")
            logical_id = f"{pair_id}::{query_type}"
            plan = planned_pairs.setdefault(logical_id, {
                "pair_id": pair_id,
                "query_type": query_type,
                "source_key": str(row.get("source_key") or row.get("source_id") or row.get("audit_id")),
                "source_id": row.get("source_id") or row.get("doc_id"),
                "audit_id": row.get("audit_id"),
                "doc_id": row.get("doc_id"),
                "fact_id": row.get("fact_id"),
                "dataset": row.get("dataset"),
                "group": row.get("group"),
                "claim_types": [],
            })
            plan["claim_types"].append(str(row.get("claim_type")))

    # by_pair: logical pair → { "模式:声明类型" → 态度记录 }；query_type 是 pair 身份的一部分。
    by_pair: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    # pair_meta: 记录每个 pair 的元信息(属于哪份文档、哪个数据集等)。
    pair_meta: dict[str, dict[str, Any]] = {}
    for row in tqdm(read_jsonl(parsed_stance_path), desc="score pcv", unit="stance"):
        pair_id = str(row.get("pair_id"))
        query_type = str(row.get("query_type") or "default")
        logical_id = f"{pair_id}::{query_type}"
        mode = str(row.get("mode"))            # rag 或 llm_only
        claim_type = str(row.get("claim_type"))  # true(真实) 或 counterfactual(反事实)
        # 用"模式:声明类型"作为键,例如 "rag:true"、"llm_only:counterfactual"。
        key = f"{mode}:{claim_type}"
        if key in by_pair[logical_id]:
            raise RuntimeError(f"Duplicate stance cell: logical_pair={logical_id} cell={key}")
        by_pair[logical_id][key] = row
        fid = str(row.get("fact_id"))
        fallback_source = fact_source.get(fid, ("", "", ""))
        pair_meta[logical_id] = {
            "pair_id": pair_id,
            "logical_pair_id": logical_id,
            "query_type": query_type,
            "audit_id": row.get("audit_id"),
            "fact_id": row.get("fact_id"),
            "doc_id": row.get("doc_id") or fallback_source[2],
            "source_id": row.get("source_id") or fallback_source[0] or row.get("doc_id") or row.get("audit_id"),
            "source_key": row.get("source_key") or fallback_source[1] or row.get("source_id") or row.get("doc_id") or row.get("audit_id"),
            "dataset": row.get("dataset"),
            "group": row.get("group"),
            "entity_type": row.get("entity_type"),
        }

    pair_rows: list[dict[str, Any]] = []
    # by_audit: audit_id → 该文档下所有 pair 的分数行,后面用于聚合。
    by_audit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # 逐个 pair 计算 RAG 与 LLM-only 两套 CVG,以及它们的差 CG-CVG。
    complete_pair_ids: set[str] = set()
    all_pair_ids = sorted(set(by_pair) | set(planned_pairs))
    for logical_id in all_pair_ids:
        rows = by_pair.get(logical_id, {})
        meta = pair_meta.get(logical_id) or planned_pairs[logical_id]
        planned_claims = planned_pairs.get(logical_id, {}).get("claim_types", ["true", "counterfactual"])
        plan_complete = sorted(planned_claims) == ["counterfactual", "true"]
        rag_complete = plan_complete and "rag:true" in rows and "rag:counterfactual" in rows
        llm_complete = "llm_only:true" in rows and "llm_only:counterfactual" in rows
        if not rag_complete:
            pair_rows.append({
                **meta,
                "complete_rag_pair": False,
                "complete_llm_pair": llm_complete,
                "status": "incomplete_rag_pair" if plan_complete else "invalid_query_pair",
                "cvg_rag": None,
                "cvg_llm": None,
                "cg_cvg": None,
            })
            continue
        # RAG 模式:用 rag:true(真实) 和 rag:counterfactual(反事实) 两条算 CVG。
        rag = score_pair(
            rows.get("rag:true"),
            rows.get("rag:counterfactual"),
            unknown_lambda=unknown_lambda,
            refusal_penalty=refusal_penalty,
            false_acceptance_penalty_value=false_acceptance_penalty_value,
        )
        # LLM-only 模式:同理用纯模型的两条记录。
        llm = score_pair(
            rows.get("llm_only:true") if llm_complete else None,
            rows.get("llm_only:counterfactual") if llm_complete else None,
            unknown_lambda=unknown_lambda,
            refusal_penalty=refusal_penalty,
            false_acceptance_penalty_value=false_acceptance_penalty_value,
        )
        fid = str(meta.get("fact_id"))
        out = {
            **meta,
            "complete_rag_pair": True,
            "complete_llm_pair": llm_complete,
            "status": "complete",
            "cvg_rag": rag["cvg"],
            "cvg_llm": llm["cvg"],
            # 核心信号:检索带来的增益 = RAG 的 CVG 减去纯模型的 CVG。
            "cg_cvg": rag["cvg"] - llm["cvg"],
            # 这一对所属 fact 的质量权重与分层(方案 D)。
            "quality_weight": fact_weight.get(fid, 1.0),
            "selection_tier": fact_tier.get(fid, "primary"),
            "support_score_rag": rag["support_score"],
            "correction_score_rag": rag["correction_score"],
            "false_acceptance_penalty_rag": rag["false_acceptance_penalty"],
            "support_score_llm": llm["support_score"],
            "correction_score_llm": llm["correction_score"],
            "false_acceptance_penalty_llm": llm["false_acceptance_penalty"],
            # 下面这些布尔字段用于后续"机制分析",记录关键事件是否发生。
            "support_true_rag": bool(rows.get("rag:true", {}).get("supports_true_claim")),
            "correct_counterfactual_rag": bool(rows.get("rag:counterfactual", {}).get("corrects_to_original_entity")),
            "accept_false_rag": bool(rows.get("rag:counterfactual", {}).get("accepts_counterfactual")),
            "unknown_rag": bool(rows.get("rag:true", {}).get("says_unknown")) or bool(rows.get("rag:counterfactual", {}).get("says_unknown")),
            "unknown_llm": bool(rows.get("llm_only:true", {}).get("says_unknown")) or bool(rows.get("llm_only:counterfactual", {}).get("says_unknown")),
        }
        pair_rows.append(out)
        complete_pair_ids.add(logical_id)
        # 把这对的结果挂到它所属的文档(audit_id)名下。
        by_audit[str(meta["audit_id"])].append(out)

    score_rows: list[dict[str, Any]] = []
    # 把同一份文档下的多对分数聚合,得到该文档的最终成员分(三口径)。
    for audit_id, rows in sorted(by_audit.items()):
        # 不加权简单平均(旧口径,保留)。
        cvg_rag = mean([float(r["cvg_rag"]) for r in rows]) if rows else 0.0
        cvg_llm = mean([float(r["cvg_llm"]) for r in rows]) if rows else 0.0
        cg_list = [float(r["cg_cvg"]) for r in rows]
        cg_cvg = mean(cg_list) if cg_list else 0.0
        # 旧质量加权 context-gain 口径，保留用于消融，不再作为 P0 主分。
        weights = [max(0.0, float(r.get("quality_weight", 1.0))) for r in rows]
        wsum = sum(weights)
        pcv_score_context_gain_weighted = (
            sum(w * c for w, c in zip(weights, cg_list)) / wsum
        ) if wsum > 0 else cg_cvg
        # 仅 primary 口径:只用高质量 fact;没有 primary 则退回全体简单平均。
        primary_cg = [c for r, c in zip(rows, cg_list) if str(r.get("selection_tier")) == "primary"]
        pcv_score_primary = mean(primary_cg) if primary_cg else cg_cvg
        num_primary = sum(1 for r in rows if str(r.get("selection_tier")) == "primary")
        # per-term 去偏 + 门控信号(消融发现先验泄漏只在 correction 项,support 几乎不漏):
        #   correction_llm = LLM-only 对反事实的纠正程度,是"该样本是否已被 LLM 知道"的污染门控信号。
        #   cvg_debiased = sup_rag + (cor_rag - cor_llm):只扣有泄漏的 correction 项、不动干净的 support,
        #   比整体减 cg_cvg 去偏更准(详见消融)。cvg_rag 本身不变,这是旁加的新终分。
        correction_llm = mean([float(r.get("correction_score_llm", 0.0)) for r in rows]) if rows else 0.0
        cvg_debiased = mean(
            [
                float(r.get("support_score_rag", 0.0))
                + float(r.get("correction_score_rag", 0.0))
                - float(r.get("correction_score_llm", 0.0))
                for r in rows
            ]
        ) if rows else 0.0
        row = {
            "audit_id": audit_id,
            "doc_id": rows[0].get("doc_id"),
            "source_id": rows[0].get("source_id") or rows[0].get("doc_id") or audit_id,
            "source_key": rows[0].get("source_key") or rows[0].get("source_id") or rows[0].get("doc_id") or audit_id,
            "dataset": rows[0].get("dataset"),
            "group": rows[0].get("group"),
            "num_pairs": len(rows),
            "num_primary_pairs": num_primary,
            "cvg_rag": cvg_rag,
            "cvg_llm": cvg_llm,
            "correction_llm": correction_llm,    # 门控信号:LLM-only 对反事实的纠正(污染/先验指标)
            "cg_cvg": cg_cvg,
            "cvg_debiased": cvg_debiased,         # per-term 去偏终分:sup_rag+(cor_rag-cor_llm)
            # P0 主分：严格黑盒 RAG-only Paired Verification Score。
            "pvs_rag": cvg_rag,
            "pcv_score": cvg_rag,
            # P0 前的质量加权 context-gain 分数，显式保留为诊断字段。
            "pcv_score_context_gain_weighted": pcv_score_context_gain_weighted,
            # 仅用 primary(高质量)fact 的口径,用于交叉验证 fallback 是否在害结果。
            "pcv_score_primary": pcv_score_primary,
            # 统计该文档中各类关键事件发生的次数/比例,供机制分析使用。
            "support_true_count_rag": sum(1 for r in rows if r.get("support_true_rag")),
            "correct_counterfactual_count_rag": sum(1 for r in rows if r.get("correct_counterfactual_rag")),
            "accept_false_count_rag": sum(1 for r in rows if r.get("accept_false_rag")),
            # 比例 = 次数 / 总对数;用 max(1, ...) 防止除以 0。
            "unknown_rate_rag": sum(1 for r in rows if r.get("unknown_rag")) / max(1, len(rows)),
            "unknown_rate_llm": sum(1 for r in rows if r.get("unknown_llm")) / max(1, len(rows)),
        }
        # 对每个阈值记录 RAG-only 主分的历史固定阈值判断，仅供诊断。
        for threshold in thresholds:
            row[f"predicted_member_t{threshold}"] = bool(cvg_rag >= threshold)
        score_rows.append(row)

    # P0-2：同一 source 的多个 audit/chunk 先各自等权，再聚合为一篇 source 一行的论文主分。
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in score_rows:
        by_source[str(row.get("source_key") or row.get("source_id") or row.get("audit_id"))].append(row)
    facts_sources = {source[1] for source in fact_source.values() if source[1]}
    if not benchmark_sources:
        for source_key, rows in by_source.items():
            benchmark_sources[source_key] = {
                "source_key": source_key,
                "source_id": rows[0].get("source_id") or source_key,
                "group": rows[0].get("group"),
                "audit_ids": {str(r.get("audit_id")) for r in rows},
            }
    planned_by_source: dict[str, set[str]] = defaultdict(set)
    for logical_id, plan in planned_pairs.items():
        planned_by_source[str(plan.get("source_key"))].add(logical_id)
    if not planned_pairs:
        for logical_id, meta in pair_meta.items():
            planned_by_source[str(meta.get("source_key"))].add(logical_id)

    coverage_rows: list[dict[str, Any]] = []
    eligible_sources: set[str] = set()
    for source_key, meta in sorted(benchmark_sources.items()):
        planned = planned_by_source.get(source_key, set())
        complete = planned & complete_pair_ids
        reasons: list[str] = []
        if facts_path is not None and source_key not in facts_sources:
            reasons.append("no_fact")
        if not planned:
            reasons.append("no_accepted_pair")
        attack_eligible = bool(planned) and not (facts_path is not None and source_key not in facts_sources)
        execution_complete = not attack_eligible or len(complete) == len(planned)
        if attack_eligible and not execution_complete:
            reasons.append("incomplete_rag_pair")
        eligible = attack_eligible and execution_complete
        if eligible:
            eligible_sources.add(source_key)
        coverage_rows.append({
            "source_key": source_key,
            "source_id": meta.get("source_id") or source_key,
            "dataset": dataset,
            "group": meta.get("group"),
            "planned_chunks": len(meta.get("audit_ids") or []),
            "planned_pairs": len(planned),
            "complete_rag_pairs": len(complete),
            "attack_eligible": attack_eligible,
            "execution_complete": execution_complete,
            "evaluation_eligible": eligible,
            "status": "complete" if eligible else "excluded",
            "reasons": reasons,
        })

    source_rows: list[dict[str, Any]] = []
    for source_key, rows in sorted(by_source.items()):
        if source_key not in eligible_sources:
            continue
        groups = {str(r.get("group")) for r in rows}
        if len(groups) != 1:
            raise RuntimeError(f"Source crosses score groups: source_key={source_key} groups={sorted(groups)}")
        source_row = {
            "source_key": source_key,
            "source_id": rows[0].get("source_id") or source_key,
            "dataset": rows[0].get("dataset"),
            "group": rows[0].get("group"),
            "num_chunks": len(rows),
            "num_pairs": sum(int(r.get("num_pairs", 0)) for r in rows),
            "audit_ids": [r.get("audit_id") for r in rows],
            "doc_ids": [r.get("doc_id") for r in rows],
            "pvs_rag": mean(float(r.get("pvs_rag", r.get("cvg_rag", 0.0))) for r in rows),
            "pcv_score": mean(float(r.get("pcv_score", r.get("cvg_rag", 0.0))) for r in rows),
            "cvg_rag": mean(float(r.get("cvg_rag", 0.0)) for r in rows),
            "cvg_llm": mean(float(r.get("cvg_llm", 0.0)) for r in rows),
            "cg_cvg": mean(float(r.get("cg_cvg", 0.0)) for r in rows),
            "pcv_score_context_gain_weighted": mean(
                float(r.get("pcv_score_context_gain_weighted", r.get("cg_cvg", 0.0))) for r in rows
            ),
        }
        for threshold in thresholds:
            source_row[f"predicted_member_t{threshold}"] = bool(source_row["pcv_score"] >= threshold)
        source_rows.append(source_row)

    # 写出成对分数与文档级分数两个文件。
    write_jsonl(pair_rows, pair_output)
    write_jsonl(score_rows, output)
    write_jsonl(source_rows, source_output)
    write_jsonl(coverage_rows, coverage_output)
    manifest = {
        "dataset": dataset,
        "output_path": str(output),
        "pair_scores_path": str(pair_output),
        "source_scores_path": str(source_output),
        "source_coverage_path": str(coverage_output),
        "pairs": len(pair_rows),
        "scored_samples": len(score_rows),
        "scored_sources": len(source_rows),
        "planned_sources": len(coverage_rows),
        "incomplete_pairs": sum(1 for row in pair_rows if not row.get("complete_rag_pair")),
        "excluded_sources": sum(1 for row in coverage_rows if not row.get("evaluation_eligible")),
        "coverage_by_group": {
            group: {
                "planned": sum(1 for row in coverage_rows if row.get("group") == group),
                "attack_eligible": sum(1 for row in coverage_rows if row.get("group") == group and row.get("attack_eligible")),
                "eligible": sum(1 for row in coverage_rows if row.get("group") == group and row.get("evaluation_eligible")),
            }
            for group in sorted({str(row.get("group")) for row in coverage_rows})
        },
        "source_counts_by_group": {
            group: sum(1 for row in source_rows if row.get("group") == group)
            for group in sorted({str(row.get("group")) for row in source_rows})
        },
        "main_score_key": "pcv_score",
        "main_score_definition": "source mean of RAG-only paired verification score",
        "weighted": bool(fact_weight),
        "facts_path": str(facts_path) if facts_path is not None else None,
        "unknown_lambda": unknown_lambda,
        "refusal_penalty": refusal_penalty,
        "false_acceptance_penalty": false_acceptance_penalty_value,
        "thresholds": thresholds,
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Computed PCV scores: samples=%s pairs=%s weighted=%s", len(score_rows), len(pair_rows), bool(fact_weight))
    return manifest
