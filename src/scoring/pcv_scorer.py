"""PCV-MIA scoring.

This module computes the Context-Gain Counterfactual Verification Gap:

CVG = SupportScore(Q+) + CorrectionScore(Q-) - FalseAcceptancePenalty(Q-)
CG-CVG = CVG_RAG - CVG_LLM

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
输出：聚合到 pair(成对) 和 audit(每份待测文档) 两个层级的分数文件 + manifest。
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
    false_acceptance_penalty_value: float = 1.0,
    thresholds: list[float] | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Aggregate parsed stance rows into document-level PCV scores.

    中文说明：本函数是打分的主入口。它把"逐条态度记录"一步步聚合：
        态度记录 → 按 pair 归拢(把同一对的 RAG/LLM × 真/假 4 条凑齐) → 算每对的 CVG
        → 再按 audit_id(每份待测文档) 求平均 → 得到每份文档的 CG-CVG(即成员分)。

    参数:
        dataset:            数据集名。
        parsed_stance_path: 上一步解析出的态度记录文件(jsonl)。
        output_path:        文档级分数的输出路径;同时会派生出 *_pair_scores.jsonl 和 manifest。
        unknown_lambda:     "不知道"的惩罚系数。
        refusal_penalty:    "拒绝"的惩罚系数。
        false_acceptance_penalty_value: "误受伪造"的惩罚分值。
        thresholds:         判定阈值列表;CG-CVG 高于阈值则判为成员。默认 [0.3,0.5,0.7,1.0]。
        resume:             断点续跑:结果已存在则跳过。
        force:              强制重算。
    返回:
        manifest(字典):统计信息与产物路径;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    # 成对分数的输出路径(在主输出名后加 _pair_scores)。
    pair_output = output.with_name(output.stem + "_pair_scores.jsonl")
    # 断点续跑:结果文件非空且 manifest 存在,就跳过不重算。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing PCV scores: %s", output)
        return {"dataset": dataset, "output_path": str(output), "skipped_existing": True}

    # 没给阈值就用一组默认阈值。
    thresholds = thresholds or [0.3, 0.5, 0.7, 1.0]
    # by_pair: pair_id → { "模式:声明类型" → 态度记录 },把同一对的多条记录聚到一起。
    by_pair: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    # pair_meta: 记录每个 pair 的元信息(属于哪份文档、哪个数据集等)。
    pair_meta: dict[str, dict[str, Any]] = {}
    for row in tqdm(read_jsonl(parsed_stance_path), desc="score pcv", unit="stance"):
        pair_id = str(row.get("pair_id"))
        mode = str(row.get("mode"))            # rag 或 llm_only
        claim_type = str(row.get("claim_type"))  # true(真实) 或 counterfactual(反事实)
        # 用"模式:声明类型"作为键,例如 "rag:true"、"llm_only:counterfactual"。
        key = f"{mode}:{claim_type}"
        by_pair[pair_id][key] = row
        pair_meta[pair_id] = {
            "pair_id": pair_id,
            "audit_id": row.get("audit_id"),
            "dataset": row.get("dataset"),
            "group": row.get("group"),
            "entity_type": row.get("entity_type"),
        }

    pair_rows: list[dict[str, Any]] = []
    # by_audit: audit_id → 该文档下所有 pair 的分数行,后面用于求文档级平均。
    by_audit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # 逐个 pair 计算 RAG 与 LLM-only 两套 CVG,以及它们的差 CG-CVG。
    for pair_id, rows in sorted(by_pair.items()):
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
            rows.get("llm_only:true"),
            rows.get("llm_only:counterfactual"),
            unknown_lambda=unknown_lambda,
            refusal_penalty=refusal_penalty,
            false_acceptance_penalty_value=false_acceptance_penalty_value,
        )
        meta = pair_meta[pair_id]
        out = {
            **meta,
            "cvg_rag": rag["cvg"],
            "cvg_llm": llm["cvg"],
            # 核心信号:检索带来的增益 = RAG 的 CVG 减去纯模型的 CVG。
            "cg_cvg": rag["cvg"] - llm["cvg"],
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
        # 把这对的结果挂到它所属的文档(audit_id)名下。
        by_audit[str(meta["audit_id"])].append(out)

    score_rows: list[dict[str, Any]] = []
    # 把同一份文档下的多对分数求平均,得到该文档的最终成员分。
    for audit_id, rows in sorted(by_audit.items()):
        # 对该文档所有 pair 的 CVG/CG-CVG 求平均(没有数据则记 0)。
        cvg_rag = mean([float(r["cvg_rag"]) for r in rows]) if rows else 0.0
        cvg_llm = mean([float(r["cvg_llm"]) for r in rows]) if rows else 0.0
        cg_cvg = mean([float(r["cg_cvg"]) for r in rows]) if rows else 0.0
        row = {
            "audit_id": audit_id,
            "dataset": rows[0].get("dataset"),
            "group": rows[0].get("group"),
            "num_pairs": len(rows),
            "cvg_rag": cvg_rag,
            "cvg_llm": cvg_llm,
            "cg_cvg": cg_cvg,
            # pcv_score 就是 cg_cvg,作为这份文档"是成员"的最终打分。
            "pcv_score": cg_cvg,
            # 统计该文档中各类关键事件发生的次数/比例,供机制分析使用。
            "support_true_count_rag": sum(1 for r in rows if r.get("support_true_rag")),
            "correct_counterfactual_count_rag": sum(1 for r in rows if r.get("correct_counterfactual_rag")),
            "accept_false_count_rag": sum(1 for r in rows if r.get("accept_false_rag")),
            # 比例 = 次数 / 总对数;用 max(1, ...) 防止除以 0。
            "unknown_rate_rag": sum(1 for r in rows if r.get("unknown_rag")) / max(1, len(rows)),
            "unknown_rate_llm": sum(1 for r in rows if r.get("unknown_llm")) / max(1, len(rows)),
        }
        # 对每个阈值,记录"这份文档是否会被判为成员"(分数 ≥ 阈值即判为成员)。
        for threshold in thresholds:
            row[f"predicted_member_t{threshold}"] = bool(cg_cvg >= threshold)
        score_rows.append(row)

    # 写出成对分数与文档级分数两个文件。
    write_jsonl(pair_rows, pair_output)
    write_jsonl(score_rows, output)
    manifest = {
        "dataset": dataset,
        "output_path": str(output),
        "pair_scores_path": str(pair_output),
        "pairs": len(pair_rows),
        "scored_samples": len(score_rows),
        "unknown_lambda": unknown_lambda,
        "refusal_penalty": refusal_penalty,
        "false_acceptance_penalty": false_acceptance_penalty_value,
        "thresholds": thresholds,
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Computed PCV scores: samples=%s pairs=%s", len(score_rows), len(pair_rows))
    return manifest
