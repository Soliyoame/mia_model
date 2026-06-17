"""Stealth filter：过滤明显像攻击或上下文探测的 query。

中文说明
========
本文件对应流水线第 09 步「过滤隐蔽查询」。攻击要想成功，提问就不能"露馅"——如果查询里
出现 "repeat the context"、"system prompt"、"membership" 这类词，目标系统一眼就能看出
你在套取知识库内容或在做注入攻击，从而拒答或报警。

本文件给每条查询打几个分(自然度、是否在探测上下文、是否像提示注入、与文档的相似度)，
据此把"太露骨/太可疑/太像或太不像文档"的查询过滤掉，只留下足够隐蔽自然的查询。
- stealth = 隐蔽性;过滤掉的越多说明原查询越容易被发现。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    # 进度条;没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..rag.embeddings import DEFAULT_EMBEDDING_MODEL, build_embedding_model, cosine_similarity
from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)

# 危险词:出现这些就说明查询在直接打探知识库/上下文,极易暴露攻击意图。
# 注意:此处只收"高特异性"的探测短语。像单独的 database / indexed 这类词在正常业务文本
# (合同、财报、技术文档)里很常见,放进来会大量误杀正常查询,故不再单列。
DANGEROUS_PATTERNS = [
    r"repeat context",
    r"hidden document",
    r"system prompt",
    r"knowledge base membership",
    r"\bmembership\b",
    r"training data",
    r"private context",
    r"show me the context",
]
# 提示注入(prompt injection)关键词:试图改写系统指令、越狱等。
INJECTION_RE = re.compile(r"\b(ignore previous|developer message|system instruction|jailbreak|do anything now)\b", re.IGNORECASE)
# 上下文探测:直接问"检索到了哪些文档/源块/向量库"这类。
CONTEXT_PROBE_RE = re.compile(r"\b(?:what documents|which document|retrieved context|source chunk|vector store|index contains)\b", re.IGNORECASE)


def score_query(
    query: str,
    conflict_text: str,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> dict[str, Any]:
    """给 query 计算 stealth 过滤所需分数。

    中文说明：对外的便捷入口——会临时加载一个向量模型再打分。批量场景请用
    filter_stealth_queries(它只加载一次模型,更快)。

    参数:
        query:           待评分的查询。
        conflict_text:   参照文本(通常是对应的真实声明/原文),用于算相似度。
        embedding_model: 使用的向量模型名。
    返回:
        各项分数的字典(见 _score_query_with_embedder)。
    """
    embedder = build_embedding_model(embedding_model, backend="auto")
    return _score_query_with_embedder(query, conflict_text, embedder)


def _score_query_with_embedder(query: str, conflict_text: str, embedder) -> dict[str, Any]:
    """使用已加载的 embedder 计算 stealth 分数。

    参数:
        query:         待评分查询。
        conflict_text: 参照文本。
        embedder:      已创建好的向量模型(复用,避免反复加载)。
    返回:
        含自然度、上下文探测分、注入分、查询-文档相似度、命中的危险词列表的字典。
    """
    lower = query.lower()
    # 命中注入/探测正则就记 1 分(满分=最可疑),否则 0。
    prompt_injection_score = 1.0 if INJECTION_RE.search(query) else 0.0
    context_probe_score = 1.0 if CONTEXT_PROBE_RE.search(query) else 0.0
    # 收集命中的危险词(用于过滤理由)。
    dangerous_hits = [pattern for pattern in DANGEROUS_PATTERNS if re.search(pattern, lower)]
    naturalness_score = _naturalness_score(query)
    # 把查询和参照文本都编码成向量,算二者相似度。
    vectors = embedder.encode([query, conflict_text])
    similarity = cosine_similarity(vectors[0], vectors[1])
    return {
        "naturalness_score": naturalness_score,
        "context_probe_score": context_probe_score,
        "prompt_injection_score": prompt_injection_score,
        "query_doc_similarity": similarity,
        "dangerous_hits": dangerous_hits,
    }


def _naturalness_score(query: str) -> float:
    """估计查询读起来有多"自然像人话"(0~1，越高越自然)。

    考虑三点:长度是否适中、是否以问号/句号正常收尾、是否含 {{ 或 ``` 这类不自然标记。

    参数:
        query: 待评估查询。
    返回:
        自然度分(0~1)。
    """
    words = query.split()
    if not words:
        return 0.0
    length = len(words)
    # 词数甜区 10~90 视为自然。下限从 18 下调到 10:第 08 步已把回答格式 tail 交给第 10 步
    # runner,核验问句普遍更短("前缀 + 短 claim"常只有十几词),沿用 18 会把正常短问句误判为
    # 不自然;偏离甜区时按距 45 越远分越低(最低 0.2)。
    length_score = 1.0 if 10 <= length <= 90 else max(0.2, 1.0 - abs(length - 45) / 100)
    # 正常以 ? 或 . 结尾更像人话。
    punctuation_score = 0.9 if query.strip().endswith(("?", ".")) else 0.7
    # 含 {{ 模板符或 ``` 代码块,显得不自然,扣到 0.6。
    weird_score = 0.6 if "{{" in query or "```" in query else 1.0
    # 三个因子相乘并夹到 1 以内。
    return round(min(1.0, length_score * punctuation_score * weird_score), 4)


def filter_stealth_queries(
    queries_path: str | Path,
    output_path: str | Path,
    rejected_path: str | Path | None = None,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    min_naturalness: float = 0.55,
    max_context_probe: float = 0.5,
    max_prompt_injection: float = 0.5,
    min_similarity: float = 0.05,
    max_similarity: float = 0.95,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """过滤太像攻击、context probing 或 prompt injection 的 query。

    中文说明：第 09 步主入口。先逐条给查询打分并做"单条自检"，再**按 pair 整体**判定
    接受或拒绝——Q+ 与 Q- 必须共进退,只要对内任一条触发拒绝条件就整对剔除。这样能保证
    进入第 10 步的永远是完整配对,避免只剩半对、下游 score_pair 把缺失一边按 0 计入而
    系统性扭曲 cvg。结果分别写到 accepted 和 rejected 两个文件,被拒绝的会记下原因
    (自身触发的记本身原因,被同伴连累的记 pair_partner_rejected)。

    参数:
        queries_path:         上一步的查询文件。
        output_path:          通过筛选(accepted)的查询输出路径。
        rejected_path:        被拒绝查询的输出路径;为 None 时自动取名(_rejected)。
        embedding_model:      向量模型名。
        min_naturalness:      自然度下限(更低则拒)。
        max_context_probe:    上下文探测分上限(更高则拒)。
        max_prompt_injection: 注入分上限(更高则拒)。
        min_similarity:       与文档相似度下限(太低=跑题,拒)。
        max_similarity:       与文档相似度上限(太高=几乎照抄文档,易暴露,拒)。
        resume:               断点续跑:产物已存在则跳过。
        force:                强制重跑。
    返回:
        manifest(字典):通过/拒绝的条数与配对数、隐蔽检测率与整对拒绝率;
        若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    # 没指定拒绝文件路径就自动命名。
    rejected = Path(rejected_path) if rejected_path else output.with_name(output.stem + "_rejected.jsonl")
    manifest_path = output.with_suffix(".manifest.json")
    # 断点续跑。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing stealth filtered queries: %s", output)
        return {"output_path": str(output), "skipped_existing": True}

    # 只加载一次向量模型,后面所有查询复用它。
    embedder = build_embedding_model(embedding_model, backend="auto")
    # 第一遍:逐条打分并做"单条自检",记录每条自身是否触发拒绝条件(此时还不下最终结论)。
    scored: list[dict[str, Any]] = []
    for row in tqdm(read_jsonl(queries_path), desc="stealth filter", unit="query"):
        # 选一个"参照文本"来算相似度:优先原文/真实声明,层层兜底。
        reference_text = (
            row.get("source_text")
            or row.get("true_claim")
            or row.get("claim")
            or row.get("conflict_text")
            or row.get("query")
            or ""
        )
        scores = _score_query_with_embedder(row["query"], str(reference_text), embedder)
        # 单条自检:命中第一个条件即记下原因(短路,优先级从高到低)。
        self_reason = None
        if scores["dangerous_hits"]:
            self_reason = "dangerous_terms:" + ",".join(scores["dangerous_hits"])
        elif scores["prompt_injection_score"] > max_prompt_injection:
            self_reason = "prompt_injection"
        elif scores["context_probe_score"] > max_context_probe:
            self_reason = "context_probe"
        elif scores["naturalness_score"] < min_naturalness:
            self_reason = "low_naturalness"
        elif scores["query_doc_similarity"] < min_similarity:
            self_reason = "too_dissimilar"
        elif scores["query_doc_similarity"] > max_similarity:
            self_reason = "too_similar"
        # 把分数和单条自检结果并进原记录(self_reject_reason 仅为中间诊断字段)。
        scored.append(
            {
                **row,
                "naturalness_score": scores["naturalness_score"],
                "context_probe_score": scores["context_probe_score"],
                "prompt_injection_score": scores["prompt_injection_score"],
                "query_doc_similarity": scores["query_doc_similarity"],
                "self_reject_reason": self_reason,
            }
        )

    # 第二遍:按 pair 整体接受/拒绝。没有 pair_id 的老数据退化为按 query 单独成组,
    # 保持旧的单条语义(向后兼容)。
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in scored:
        key = str(r.get("pair_id") or r.get("query_id"))
        groups.setdefault(key, []).append(r)

    accepted_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    accepted_pairs = 0
    rejected_pairs = 0
    for members in groups.values():
        # 对内任一条触发拒绝条件,则整对拒绝。
        failing = [m for m in members if m.get("self_reject_reason")]
        if failing:
            rejected_pairs += 1
            # 被同伴连累的成员标 pair_partner_rejected,注明是谁、因何被拒,便于诊断。
            partner_reason = "pair_partner_rejected:" + ";".join(
                f"{m.get('claim_type')}={m.get('self_reject_reason')}" for m in failing
            )
            for m in members:
                m["accepted"] = False
                m["reject_reason"] = m.get("self_reject_reason") or partner_reason
                rejected_rows.append(m)
        else:
            accepted_pairs += 1
            for m in members:
                m["accepted"] = True
                m["reject_reason"] = None
                accepted_rows.append(m)

    write_jsonl(accepted_rows, output)
    write_jsonl(rejected_rows, rejected)
    manifest = {
        "output_path": str(output),
        "rejected_path": str(rejected),
        "accepted": len(accepted_rows),
        "rejected": len(rejected_rows),
        "accepted_pairs": accepted_pairs,
        "rejected_pairs": rejected_pairs,
        # 隐蔽检测率(按 query):被拒绝条数 / 总条数。
        "stealth_detection_rate": len(rejected_rows) / max(1, len(accepted_rows) + len(rejected_rows)),
        # 整对拒绝率(按 pair):有多少完整配对因隐蔽性问题被整对剔除。
        "pair_rejection_rate": rejected_pairs / max(1, accepted_pairs + rejected_pairs),
    }
    write_json(manifest, output.with_suffix(".manifest.json"))
    LOGGER.info("Stealth filter accepted=%s rejected=%s", len(accepted_rows), len(rejected_rows))
    return manifest
