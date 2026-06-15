"""机制分析模块。

中文说明
========
本文件负责对一次攻击运行做"机制层面"的统计复盘:在 RAG 检索是否命中目标文档、检索内容里
是否真的出现原始实体、模型是否据此纠正反事实声明等环节上,逐项算出比率,并按实体类型/查询类型
分桶,辅以 Context Gain、查询-文档相似度等指标。它读入查询、RAG 响应、解析结果、打分与文档库,
汇总成一份机制分析报告(json),用于解释攻击为何成功或失败,而非给出攻击判定本身。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from ..utils.io import read_jsonl, write_json
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def run_mechanism_analysis(
    dataset: str,
    queries_path: str | Path,
    rag_responses_path: str | Path,
    parsed_path: str | Path,
    scores_path: str | Path,
    docstore_path: str | Path,
    output_path: str | Path,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """统计攻击成功和失败的机制因素。

    参数:
        dataset:            数据集名。
        queries_path:       查询文件(jsonl),按 query_id 索引。
        rag_responses_path: RAG 响应文件(jsonl),含检索命中信息。
        parsed_path:        立场解析结果(jsonl),只取 mode=="rag" 的部分。
        scores_path:        打分结果(jsonl),用于 Context Gain 等统计。
        docstore_path:      文档库(jsonl),按 doc_id 聚合正文,用于实体证据判定。
        output_path:        机制报告输出路径(json)。
        resume:             断点续跑:报告已存在且非空则跳过。
        force:              强制重算。
    返回:
        机制分析报告(字典);若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    if resume and not force and output.exists() and output.stat().st_size > 0:
        LOGGER.info("Skipping existing mechanism analysis: %s", output)
        return {"dataset": dataset, "output_path": str(output), "skipped_existing": True}

    queries = {row["query_id"]: row for row in read_jsonl(queries_path)}
    # 只分析 RAG(带检索)模式的解析结果,纯 LLM 模式不计入机制统计。
    parsed = [row for row in read_jsonl(parsed_path) if row.get("mode") == "rag"]
    parsed_by_query = {row["query_id"]: row for row in parsed}
    scores = list(read_jsonl(scores_path))
    docstore_by_doc: dict[str, list[str]] = defaultdict(list)
    for row in read_jsonl(docstore_path):
        docstore_by_doc[str(row["doc_id"])].append(str(row["text"]))

    exposure_rows = []
    evidence_rows = []
    override_rows = []
    similarity_values = []
    for rag in read_jsonl(rag_responses_path):
        query = queries.get(rag["query_id"], {})
        parsed_row = parsed_by_query.get(rag["query_id"], {})
        retrieved_doc_ids = [str(doc_id) for doc_id in rag.get("retrieved_doc_ids", [])]
        original = str(query.get("expected_entity") or query.get("original_entity") or "")
        # 实体证据:检索回来的任一文档片段里是否真的出现了原始实体字符串。
        evidence = any(original and original in chunk for doc_id in retrieved_doc_ids for chunk in docstore_by_doc.get(doc_id, []))
        exposure_rows.append(bool(rag.get("target_doc_retrieved")))
        evidence_rows.append(evidence)
        # 仅在确有实体证据时,才统计模型是否被该证据"带"着提到原始实体(覆盖率分母)。
        if evidence:
            override_rows.append(bool(parsed_row.get("mentions_original_entity")))
        if "query_doc_similarity" in query:
            similarity_values.append(float(query["query_doc_similarity"]))

    # 按实体类型/查询类型分桶统计恢复率(成功纠正到原实体或支持真声明记为命中)。
    entity_type_stats = _rate_by_key(parsed, "entity_type", lambda row: bool(row.get("corrects_to_original_entity") or row.get("supports_true_claim")))
    query_type_stats = _rate_by_key(parsed, "query_type", lambda row: bool(row.get("corrects_to_original_entity") or row.get("supports_true_claim")))
    # Context Gain 字段:cg_cvg 是当前 pcv_scorer 产出的真实 context-gain 字段;score_key 缺
    # pcv_score 时退回 cg_cvg。原 fallback 名 cg_cms 经查全历史从未被产出过,是死兜底,已清除。
    group_cg = _mean_by_key(scores, "group", "cg_cvg")
    score_key = "pcv_score" if scores and "pcv_score" in scores[0] else "cg_cvg"

    report = {
        "dataset": dataset,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # 检索曝光率:目标文档被检索命中的比例。
        "Retrieval Exposure Rate": _mean_bool(exposure_rows),
        # 实体证据率:检索内容中真实出现原始实体的比例。
        "Entity Evidence Rate": _mean_bool(evidence_rows),
        "True Claim Support Rate": _mean_bool([bool(row.get("supports_true_claim")) for row in parsed if row.get("claim_type") == "true"]),
        "Counterfactual Rejection Rate": _mean_bool([bool(row.get("rejects_counterfactual")) for row in parsed if row.get("claim_type") == "counterfactual"]),
        "Counterfactual Correction Rate": _mean_bool([bool(row.get("corrects_to_original_entity")) for row in parsed if row.get("claim_type") == "counterfactual"]),
        "False Acceptance Rate": _mean_bool([bool(row.get("accepts_counterfactual")) for row in parsed if row.get("claim_type") == "counterfactual"]),
        # 证据覆盖率:在确有实体证据的样本中,模型最终提到原始实体的比例。
        "Entity Evidence Override Rate": _mean_bool(override_rows),
        "Context Gain": {
            "overall_avg": mean([float(row.get(score_key, 0.0)) for row in scores]) if scores else 0.0,
            "by_group": group_cg,
        },
        "Query-Document Similarity": {
            "avg": mean(similarity_values) if similarity_values else 0.0,
            "min": min(similarity_values) if similarity_values else 0.0,
            "max": max(similarity_values) if similarity_values else 0.0,
        },
        "Nearest-Neighbor Similarity": {
            "status": "reserved",
            "note": "Requires storing non-member nearest KB similarity during retrieval or a separate embedding pass.",
        },
        "Entity Type Sensitivity": entity_type_stats,
        "Query Rewriting Robustness": query_type_stats,
        "Top-k Sensitivity": {
            "status": "single_run",
            "note": "Run script 10 with different top_k values and compare reports for full ablation.",
        },
        "Control Group False Positive Analysis": {
            "True_Non_Member_avg_context_gain": group_cg.get("True_Non_Member", 0.0),
            "Spoofed_Non_Member_avg_context_gain": group_cg.get("Spoofed_Non_Member", 0.0),
            "Spoofed_Non_Member_role": "experimental_control_group_only",
            "note": "False positives should be inspected against nearest KB chunks in future ablation.",
        },
    }
    write_json(report, output)
    LOGGER.info("Mechanism report written: %s", output)
    return report


def _mean_bool(values: list[bool]) -> float:
    """计算布尔列表中 True 的占比(空列表按分母 1 处理,返回 0.0)。

    参数:
        values: 布尔值列表。
    返回:
        True 的比例;列表为空时返回 0.0。
    """
    return sum(1 for value in values if value) / max(1, len(values))


def _rate_by_key(rows: list[dict[str, Any]], key: str, pred) -> dict[str, Any]:
    """按某个字段分桶,统计每桶的样本数和"命中率"。

    参数:
        rows: 记录列表。
        key:  分桶字段名(取值缺失时归入 "unknown")。
        pred: 判定单条记录是否命中的谓词函数。
    返回:
        {桶名: {"count": 样本数, "recovery_rate": 命中率}}。
    """
    counts = Counter(str(row.get(key, "unknown")) for row in rows)
    hits: Counter[str] = Counter()
    for row in rows:
        if pred(row):
            hits[str(row.get(key, "unknown"))] += 1
    return {name: {"count": counts[name], "recovery_rate": hits[name] / max(1, counts[name])} for name in counts}


def _mean_by_key(rows: list[dict[str, Any]], key: str, value_key: str) -> dict[str, float]:
    """按某个字段分桶,求另一数值字段在每桶内的平均值。

    参数:
        rows:      记录列表。
        key:       分桶字段名(取值缺失时归入 "unknown")。
        value_key: 要取平均的数值字段名(缺失按 0.0)。
    返回:
        {桶名: 该桶 value_key 的平均值};空桶返回 0.0。
    """
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key, "unknown"))].append(float(row.get(value_key, 0.0)))
    return {name: mean(values) if values else 0.0 for name, values in buckets.items()}
