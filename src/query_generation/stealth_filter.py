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
DANGEROUS_PATTERNS = [
    r"repeat context",
    r"hidden document",
    r"system prompt",
    r"\bdatabase\b",
    r"\bindexed\b",
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
    # 词数在 18~90 之间最自然;偏离 45 越远分越低(最低 0.2)。
    length_score = 1.0 if 18 <= length <= 90 else max(0.2, 1.0 - abs(length - 45) / 100)
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

    中文说明：第 09 步主入口。逐条给查询打分，按一串阈值判定"接受"或"拒绝"，分别写到
    accepted 和 rejected 两个文件。被拒绝的会记下原因。

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
        manifest(字典):通过/拒绝数量与隐蔽检测率;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    # 没指定拒绝文件路径就自动命名。
    rejected = Path(rejected_path) if rejected_path else output.with_name(output.stem + "_rejected.jsonl")
    manifest_path = output.with_suffix(".manifest.json")
    # 断点续跑。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing stealth filtered queries: %s", output)
        return {"output_path": str(output), "skipped_existing": True}

    accepted_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    # 只加载一次向量模型,后面所有查询复用它。
    embedder = build_embedding_model(embedding_model, backend="auto")
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
        # 依次检查各拒绝条件,命中第一个就给出拒绝原因(短路,优先级从高到低)。
        reject_reason = None
        if scores["dangerous_hits"]:
            reject_reason = "dangerous_terms:" + ",".join(scores["dangerous_hits"])
        elif scores["prompt_injection_score"] > max_prompt_injection:
            reject_reason = "prompt_injection"
        elif scores["context_probe_score"] > max_context_probe:
            reject_reason = "context_probe"
        elif scores["naturalness_score"] < min_naturalness:
            reject_reason = "low_naturalness"
        elif scores["query_doc_similarity"] < min_similarity:
            reject_reason = "too_dissimilar"
        elif scores["query_doc_similarity"] > max_similarity:
            reject_reason = "too_similar"

        # 把分数和判定结果并进原记录。
        out = {
            **row,
            "naturalness_score": scores["naturalness_score"],
            "context_probe_score": scores["context_probe_score"],
            "prompt_injection_score": scores["prompt_injection_score"],
            "query_doc_similarity": scores["query_doc_similarity"],
            "accepted": reject_reason is None,
            "reject_reason": reject_reason,
        }
        # 没有拒绝原因 → 通过;否则 → 拒绝。
        if reject_reason is None:
            accepted_rows.append(out)
        else:
            rejected_rows.append(out)

    write_jsonl(accepted_rows, output)
    write_jsonl(rejected_rows, rejected)
    manifest = {
        "output_path": str(output),
        "rejected_path": str(rejected),
        "accepted": len(accepted_rows),
        "rejected": len(rejected_rows),
        # 隐蔽检测率 = 被拒绝数 / 总数(衡量原始查询有多容易被识破)。
        "stealth_detection_rate": len(rejected_rows) / max(1, len(accepted_rows) + len(rejected_rows)),
    }
    write_json(manifest, output.with_suffix(".manifest.json"))
    LOGGER.info("Stealth filter accepted=%s rejected=%s", len(accepted_rows), len(rejected_rows))
    return manifest
