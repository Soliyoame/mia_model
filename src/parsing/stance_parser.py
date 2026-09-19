"""Parse RAG/LLM responses into claim-verification stances.

中文说明
========
本文件对应流水线第 11 步的前半段：把大模型那些"自由发挥的文字回答"翻译成一组
结构化的"立场(stance)"布尔标记，供后面的打分(pcv_scorer)使用。

为什么需要它：模型回答是大白话，比如"这个金额不对，应该是 12000 美元"。计算机没法
直接拿这种话打分。本文件用【关键词正则匹配】+【尝试解析 JSON 结构化回答】两条路，
判断模型到底是：支持/反对真实声明、接受/识破/纠正伪造声明、还是说不知道/拒绝回答。
判断结果以一堆 True/False 字段输出，喂给打分公式。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    # 进度条;没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger
from ..rag.runner import compact_response_rows, response_is_success


LOGGER = get_logger(__name__)


def parse_hybrid_response(
    response: str | bytes | None,
    *,
    generator_error: bool = False,
) -> dict[str, Any]:
    """为 V24 混合评分读取明确立场，不用实体出现或关键词片段推断支持。"""
    result: dict[str, Any] = {
        "raw_response": response if isinstance(response, str) else None,
        "parse_status": "invalid",
        "stance": None,
        "correction_entity": None,
    }
    if generator_error:
        return {**result, "parse_status": "generator_error"}
    if isinstance(response, bytes):
        try:
            response = response.decode("utf-8")
        except UnicodeDecodeError:
            return result
        result["raw_response"] = response
    if response is None or (isinstance(response, str) and not response.strip()):
        return {**result, "parse_status": "missing"}
    if not isinstance(response, str):
        return result
    text = response.strip()

    def unique_fields(items: list[tuple[str, Any]]) -> dict[str, Any]:
        fields = dict(items)
        if len(fields) != len(items):
            raise ValueError("duplicate_response_field")
        return fields

    if text.startswith("{"):
        try:
            value = json.loads(text, object_pairs_hook=unique_fields)
        except (ValueError, TypeError):
            return result
        if not isinstance(value, dict) or set(value) != {"stance", "correction_entity"}:
            return result
        stance, correction = value["stance"], value["correction_entity"]
        if not isinstance(stance, str) or stance not in {"supported", "contradicted", "insufficient"}:
            return result
        if correction is not None and not isinstance(correction, str):
            return result
        correction = (correction.strip() or None) if isinstance(correction, str) else None
        if stance != "contradicted" and correction is not None:
            return result
    else:
        token = text.casefold().replace("’", "'").rstrip(".!").strip()
        correction = None
        if token in {"yes", "consistent"}:
            stance = "supported"
        elif token in {"no", "inconsistent"}:
            stance = "contradicted"
        elif token in {"i don't know", "i do not know"}:
            stance = "insufficient"
        else:
            match = re.fullmatch(r"inconsistent\s*:\s*(.*)", text, flags=re.IGNORECASE | re.DOTALL)
            if match is None:
                return result
            stance, correction = "contradicted", match.group(1).strip() or None
    # 否定但没有更正值是合法行为，由评分层给零恢复分。
    return {**result, "parse_status": "parsed", "stance": stance, "correction_entity": correction}

# 下面四个正则用来从回答文字里"嗅探"模型的态度。re.IGNORECASE 表示不区分大小写。
# UNKNOWN_RE: 命中表示模型说"我不知道/无法核实/信息不足"。
UNKNOWN_RE = re.compile(r"\b(?:i do not know|i don't know|don't know|cannot verify|can't verify|unknown|insufficient information|not enough information)\b", re.IGNORECASE)
# REFUSAL_RE: 命中表示模型"拒绝回答"(以隐私/保密/受限为由)。
REFUSAL_RE = re.compile(r"\b(?:cannot disclose|can't disclose|not allowed|unable to provide|privacy|confidential|restricted)\b", re.IGNORECASE)
# CONSISTENT_RE: 命中表示模型认为声明"一致/被支持/正确"。
CONSISTENT_RE = re.compile(r"\b(?:consistent|supported|verified|matches|correct|accurate|yes)\b", re.IGNORECASE)
# INCONSISTENT_RE: 命中表示模型认为声明"不一致/错误/需更正"。
INCONSISTENT_RE = re.compile(r"\b(?:inconsistent|unsupported|incorrect|wrong|false|conflict|conflicting|mismatch|does not match|not consistent|corrected|should be|instead)\b", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """把文本规范化，便于做"是否包含某实体"的宽松匹配。

    做两件事:(1) 多个空白压成一个、去首尾空格、转小写;(2) 去掉逗号。去逗号是为了
    让 "12,000" 和 "12000" 这种金额/数字在不同写法下也能匹配上。

    参数:
        text: 原始文本。
    返回:
        规范化后的文本。
    """
    text = re.sub(r"\s+", " ", text or "").strip().lower()
    # Match money/numeric entities across comma formatting differences.
    return text.replace(",", "")


def contains_normalized(haystack: str, needle: str) -> bool:
    """判断 needle(待找的实体) 是否出现在 haystack(回答文本) 中(规范化后比较)。

    参数:
        haystack: 被搜索的大段文本。
        needle:   要查找的实体字符串。
    返回:
        找到返回 True;needle 为空则返回 False。
    """
    if not needle:
        return False
    # 两边都规范化后再判断包含关系,容忍大小写/空格/逗号差异。
    return normalize_text(needle) in normalize_text(haystack)


def _flatten_json_values(obj: Any) -> str:
    """把一个(可能嵌套的)JSON 对象里所有的值拼成一个大字符串,方便整体做关键词搜索。

    参数:
        obj: 任意 JSON 值(字典/列表/标量)。
    返回:
        把所有叶子值用空格连接而成的字符串。
    """
    # 字典:递归拼接所有"值"。
    if isinstance(obj, dict):
        return " ".join(_flatten_json_values(v) for v in obj.values())
    # 列表:递归拼接每个元素。
    if isinstance(obj, list):
        return " ".join(_flatten_json_values(v) for v in obj)
    # 标量:直接转成字符串。
    return str(obj)


def _structured_status(response: str) -> tuple[str | None, str]:
    """尝试把回答当作 JSON 解析,取出其中的结构化状态字段。

    有些模型会按要求返回 JSON(如 {"status": "inconsistent", ...})。能解析成功时,
    我们既拿到明确的 status,又把所有值拼成可搜索文本;解析失败就退回用原始回答。

    参数:
        response: 模型回答字符串。
    返回:
        (status, searchable):status 是规范化后的状态字符串(没有则为 None);
        searchable 是用于关键词匹配的文本。
    """
    try:
        obj = json.loads(response)
    except Exception:
        # 不是合法 JSON:返回 None 和原始回答。
        return None, response
    # 解析出来不是字典(比如是个数字/列表),也按非结构化处理。
    if not isinstance(obj, dict):
        return None, response
    # 优先取 status 字段,没有就取 verdict;都没有则为 None。统一小写去空格。
    status = str(obj.get("status") or obj.get("verdict") or "").strip().lower() or None
    searchable = _flatten_json_values(obj)
    return status, searchable


def parse_stance_response(response_row: dict[str, Any], query_row: dict[str, Any]) -> dict[str, Any]:
    """Parse one response against the corresponding verification query.

    中文说明：解析"单条回答"相对于"它对应的那条查询"的立场。这是本文件的核心:
    根据声明类型(真实/反事实),结合关键词命中与是否提到原始/伪造实体,综合判断模型
    到底持什么态度,并输出一整套布尔标记。

    参数:
        response_row: 一条模型回答记录(含 response 文本、mode、各种 id 等)。
        query_row:    与之对应的查询记录(含真实实体、伪造实体、声明类型等)。
    返回:
        一个字典:除了透传各种 id/元信息,还包含 supports_true_claim、
        accepts_counterfactual、says_unknown、stance(综合立场标签) 等判定结果。
    """
    response = str(response_row.get("response") or "")
    # 声明类型:true(真实声明) 或 counterfactual(反事实声明);两处都可能有,优先用 query 的。
    claim_type = str(query_row.get("claim_type") or response_row.get("claim_type") or "")
    # original: 真实的原始实体;counterfactual: 我们伪造替换上去的假实体。
    original = str(query_row.get("expected_entity") or query_row.get("original_entity") or response_row.get("expected_entity") or "")
    counterfactual = str(query_row.get("counterfactual_entity") or response_row.get("counterfactual_entity") or "")
    status, searchable = _structured_status(response)

    # —— 综合"正则命中"与"结构化 status"来判断各种基础态度 ——
    # 是否说"不知道":关键词命中,或结构化状态属于这几种。
    says_unknown = bool(UNKNOWN_RE.search(response)) or status in {"unknown", "dont_know", "do_not_know", "cannot_verify"}
    # 是否"拒绝回答"。
    refuses = bool(REFUSAL_RE.search(response)) or status in {"refused", "refusal"}
    # 回答里是否提到了原始(真实)实体 / 伪造实体。
    mentions_original = contains_normalized(searchable, original)
    mentions_counterfactual = contains_normalized(searchable, counterfactual)
    # 是否表达"不一致/需更正" / "一致/被支持"。
    inconsistent = bool(INCONSISTENT_RE.search(response)) or status in {"inconsistent", "unsupported", "incorrect", "false", "conflict"}
    consistent = bool(CONSISTENT_RE.search(response)) or status in {"consistent", "supported", "verified", "true"}
    # 解析状态:如果这条回答本身在生成阶段就报错了,标记为 generator_error。
    parse_status = "generator_error" if response_row.get("error") else "success"

    # 先把所有"结论性"标记初始化为 False,下面按声明类型分别填。
    supports_true_claim = False
    rejects_true_claim = False
    accepts_counterfactual = False
    rejects_counterfactual = False
    corrects_to_original = False

    if claim_type == "true":
        # —— 针对"真实声明 Q+"的判定 ——
        # 支持:没说不知道/不拒绝,且(表示一致 或 提到了真实实体),且没有表示不一致。
        supports_true_claim = bool(not says_unknown and not refuses and (consistent or mentions_original) and not inconsistent)
        # 反对:没说不知道/不拒绝,但表示了不一致。
        rejects_true_claim = bool(not says_unknown and not refuses and inconsistent)
        # 无关:上面几种情况都不沾边。
        unrelated = not any([supports_true_claim, rejects_true_claim, says_unknown, refuses, mentions_original])
        # 归纳出一个总的立场标签(便于阅读/统计)。
        if supports_true_claim:
            stance = "supports_true_claim"
        elif rejects_true_claim:
            stance = "rejects_true_claim"
        elif says_unknown:
            stance = "unknown"
        elif refuses:
            stance = "refuses"
        else:
            stance = "unrelated"
    else:
        # —— 针对"反事实声明 Q-"的判定 ——
        # 纠正回原始实体:没说不知道/不拒绝,提到了真实实体,且表示不一致(即指出错误并给出正确值)。
        corrects_to_original = bool(not says_unknown and not refuses and mentions_original and inconsistent)
        # 识破并否定伪造声明(未必给出正确值)。
        rejects_counterfactual = bool(not says_unknown and not refuses and inconsistent)
        # 接受了伪造声明:没说不知道/不拒绝,表示一致,且没有不一致信号。
        accepts_counterfactual = bool(not says_unknown and not refuses and consistent and not inconsistent)
        # 补充规则:若回答里照搬了伪造实体,且既没否定也没纠正,则也视为"接受了伪造"。
        if (
            mentions_counterfactual
            and not says_unknown
            and not refuses
            and not rejects_counterfactual
            and not corrects_to_original
        ):
            accepts_counterfactual = True
        unrelated = not any([accepts_counterfactual, rejects_counterfactual, corrects_to_original, says_unknown, refuses, mentions_original, mentions_counterfactual])
        # 反事实情形的总立场标签(注意:能纠正比单纯否定更强,优先判定)。
        if corrects_to_original:
            stance = "corrects_counterfactual"
        elif rejects_counterfactual:
            stance = "rejects_counterfactual"
        elif accepts_counterfactual:
            stance = "accepts_counterfactual"
        elif says_unknown:
            stance = "unknown"
        elif refuses:
            stance = "refuses"
        else:
            stance = "unrelated"

    # 把所有判定结果连同各种 id/元信息打包返回(供打分与机制分析使用)。
    return {
        "request_id": response_row.get("request_id"),
        "mode": response_row.get("mode"),
        "query_id": response_row.get("query_id"),
        "pair_id": query_row.get("pair_id") or response_row.get("pair_id"),
        "fact_id": query_row.get("fact_id") or response_row.get("fact_id"),
        "audit_id": response_row.get("audit_id") or query_row.get("audit_id"),
        "doc_id": response_row.get("doc_id") or query_row.get("doc_id"),
        "source_id": response_row.get("source_id") or query_row.get("source_id") or query_row.get("doc_id"),
        "source_key": response_row.get("source_key") or query_row.get("source_key") or query_row.get("source_id") or query_row.get("doc_id"),
        "dataset": response_row.get("dataset") or query_row.get("dataset"),
        "group": response_row.get("group") or query_row.get("group"),
        "claim_type": claim_type,
        "query_type": query_row.get("query_type"),
        "variant_id": query_row.get("variant_id") or response_row.get("variant_id") or "full_pvs",
        "entity_type": query_row.get("entity_type") or response_row.get("entity_type"),
        "expected_entity": original,
        "counterfactual_entity": counterfactual,
        "supports_true_claim": supports_true_claim,
        "rejects_true_claim": rejects_true_claim,
        "accepts_counterfactual": accepts_counterfactual,
        "rejects_counterfactual": rejects_counterfactual,
        "corrects_to_original_entity": corrects_to_original,
        "mentions_original_entity": mentions_original,
        "mentions_counterfactual_entity": mentions_counterfactual,
        "says_unknown": says_unknown,
        "refuses": refuses,
        "unrelated": unrelated,
        "stance": stance,
        "parse_status": parse_status,
    }


def parse_stance_files(
    dataset: str,
    queries_path: str | Path,
    rag_responses_path: str | Path,
    llm_responses_path: str | Path | None,
    output_path: str | Path,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Parse all RAG and LLM-only responses into stance JSONL.

    中文说明：本函数是第 11 步前半段的主入口。它把 RAG 和 LLM-only 两个回答文件里的
    每一条回答,都用 parse_stance_response 解析成立场记录,汇总写到一个 jsonl。

    参数:
        dataset:             数据集名。
        queries_path:        查询文件,用来按 query_id 找到每条回答对应的查询。
        rag_responses_path:  RAG 模式回答文件。
        llm_responses_path:  LLM-only 模式回答文件；为 None 时只解析 RAG。
        output_path:         立场记录的输出路径(并派生 manifest)。
        resume:              断点续跑:结果已存在则跳过。
        force:               强制重跑。
    返回:
        manifest(字典);若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    # 断点续跑:结果非空且 manifest 存在则跳过。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing parsed stance: %s", output)
        return {"dataset": dataset, "output_path": str(output), "skipped_existing": True}

    # 把查询读成"query_id → 查询行"的字典,便于快速配对。
    query_rows = list(read_jsonl(queries_path))
    queries = {str(row["query_id"]): row for row in query_rows}
    rows: list[dict[str, Any]] = []
    integrity: dict[str, Any] = {}
    # main canonical run 显式传 None，只解析 RAG；旧调用仍可同时解析两套回答。
    response_sources: list[tuple[str, str | Path]] = [("rag", rag_responses_path)]
    if llm_responses_path is not None:
        response_sources.append(("llm_only", llm_responses_path))
    for mode, path in response_sources:
        response_path = Path(path)
        raw = list(read_jsonl(response_path)) if response_path.exists() else []
        compacted, stats = compact_response_rows(raw)
        valid_ids: set[str] = set()
        unknown_query_ids = 0
        for response_row in tqdm(compacted, desc=f"parse stance {Path(path).name}", unit="resp"):
            if not response_is_success(response_row):
                continue
            # 用 query_id 找到这条回答对应的查询;找不到就跳过(数据不完整)。
            query_id = str(response_row.get("query_id") or "")
            query_row = queries.get(query_id)
            if not query_row:
                unknown_query_ids += 1
                continue
            valid_ids.add(query_id)
            rows.append(parse_stance_response(response_row, query_row))
        expected = set(queries)
        integrity[mode] = {
            **stats,
            "parsed": len(valid_ids),
            "missing": len(expected - valid_ids),
            "unknown_query_ids": unknown_query_ids,
        }

    write_jsonl(rows, output)
    manifest = {
        "dataset": dataset,
        "output_path": str(output),
        "planned_queries": len(queries),
        "query_duplicates": len(query_rows) - len(queries),
        "parsed_responses": len(rows),
        "integrity": integrity,
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Parsed stance rows: %s", len(rows))
    return manifest
