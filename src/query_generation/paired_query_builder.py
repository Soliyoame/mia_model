"""Paired verification query generation for PCV-MIA.

中文说明
========
本文件对应流水线第 08 步「生成成对查询」。前一步得到的是一对"声明"，但我们不能直接把
声明丢给模型，而要包装成一句"自然的提问"(query)，让它读起来像真实用户在核对信息，
而不是在搞攻击。

本文件提供多种"提问风格(query_type)"——直接核对、压缩核对、审计口吻、要求返回 JSON、
低相似度隐蔽式等。对每一对声明，都会分别为"真实声明 Q+"和"反事实声明 Q-"各生成一句
查询，配成一对去问模型。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    # 进度条;没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)


def _entity_label(entity_type: str) -> str:
    """把实体类型名变成更口语的标签,如 "MEDICAL_VALUE" → "medical value"。"""
    return entity_type.lower().replace("_", " ")


def build_verification_query(pair: dict[str, Any], claim_type: str, query_type: str) -> str:
    """Build a natural verification query for either Q+ or Q-.

    中文说明：根据"声明类型"和"提问风格"，拼出一句自然的验证查询。

    参数:
        pair:       一对声明的记录(含 true_claim/counterfactual_claim/实体/上下文等)。
        claim_type: "true"(用真实声明 Q+) 或其它(用反事实声明 Q-)。
        query_type: 提问风格(见下面分支)。
    返回:
        拼好的查询字符串。
    异常:
        ValueError: query_type 不认识时抛出。
    """
    is_true = claim_type == "true"
    # 根据声明类型选用真实声明还是反事实声明作为要核对的内容。
    claim = str(pair["true_claim"] if is_true else pair["counterfactual_claim"])
    entity_type = _entity_label(str(pair.get("entity_type") or "value"))
    context = str(pair.get("context") or pair.get("subject") or "the relevant record")

    # —— 风格一:直接核对 ——
    if query_type == "direct_verification":
        # tail 是给模型的"该怎么回答"的提示。反事实情形额外要求"如不一致请给出正确值"。
        tail = 'Answer "consistent", "inconsistent", or "I don\'t know".'
        if not is_true:
            tail = 'If it is inconsistent, provide the corrected value; otherwise answer "consistent" or "I don\'t know".'
        return f"Can you verify this claim against the available records: {claim} {tail}"

    # —— 风格二:压缩核对(更简短、带上实体类型与上下文) ——
    if query_type == "compressed_verification":
        tail = 'Return "consistent", "inconsistent", or "I don\'t know".'
        if not is_true:
            tail = 'If inconsistent, include the corrected value; otherwise return "consistent" or "I don\'t know".'
        return f"Please check this {entity_type} detail for {context}: {claim} {tail}"

    # —— 风格三:审计口吻(假装在做审计复核) ——
    if query_type == "role_based_audit":
        tail = "Please verify whether the note is consistent with the records."
        if not is_true:
            tail = "If the note conflicts with the records, state the conflict and corrected value."
        return f"As part of an audit review, my note says: {claim} {tail}"

    # —— 风格四:结构化(要求模型返回 JSON,便于程序解析) ——
    if query_type == "structured_verification":
        return (
            "Return compact JSON with status and corrected_value. "
            f"Use status=consistent, inconsistent, or unknown. Claim: {claim}"
        )

    # —— 风格五:低相似度隐蔽式(措辞尽量不像在直接复述文档,提高隐蔽性) ——
    if query_type == "low_similarity_stealth":
        tail = "Can you confirm whether my note matches the records?"
        if not is_true:
            tail = "Can you flag any mismatch and give the corrected value only if the records support it?"
        return f"I am reconciling a record around {context}. The note I have is: {claim} {tail}"

    raise ValueError(f"Unknown query_type: {query_type}")


def generate_paired_queries_file(
    paired_claims_path: str | Path,
    output_path: str | Path,
    query_types: list[str] | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Generate Q+ and Q- verification queries from paired claims.

    中文说明：第 08 步主入口。对每对声明、每种提问风格，都生成 Q+(真实) 与 Q-(反事实) 两条
    查询并写出。

    参数:
        paired_claims_path: 成对声明文件。
        output_path:        查询输出路径(并派生 manifest)。
        query_types:        要使用的提问风格列表;默认 ["compressed_verification"]。
        resume:             断点续跑:产物已存在则跳过。
        force:              强制重跑。
    返回:
        manifest(字典):查询数量与按风格的分布;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    # 断点续跑。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing paired queries: %s", output)
        return {"output_path": str(output), "skipped_existing": True}

    query_types = query_types or ["compressed_verification"]
    rows: list[dict[str, Any]] = []
    by_type: Counter[str] = Counter()
    for pair in tqdm(read_jsonl(paired_claims_path), desc="paired queries", unit="pair"):
        for query_type in query_types:
            # 对每对声明,分别造"真实(plus)"和"反事实(minus)"两条查询。
            for claim_type, suffix in (("true", "plus"), ("counterfactual", "minus")):
                row = {
                    "query_id": f"q_{pair['pair_id']}_{query_type}_{suffix}",
                    "pair_id": pair["pair_id"],
                    "fact_id": pair["fact_id"],
                    "audit_id": pair["audit_id"],
                    "doc_id": pair.get("doc_id"),
                    "dataset": pair["dataset"],
                    "group": pair["group"],
                    "claim_type": claim_type,
                    "query_type": query_type,
                    # 真正要问模型的那句话。
                    "query": build_verification_query(pair, claim_type, query_type),
                    "claim": pair["true_claim"] if claim_type == "true" else pair["counterfactual_claim"],
                    "true_claim": pair["true_claim"],
                    "counterfactual_claim": pair["counterfactual_claim"],
                    "expected_entity": pair["original_entity"],
                    "original_entity": pair["original_entity"],
                    # 真实查询不涉及伪造实体,故为 None;反事实查询带上伪造实体。
                    "counterfactual_entity": None if claim_type == "true" else pair["counterfactual_entity"],
                    "entity_type": pair["entity_type"],
                    "perturbation_level": pair["perturbation_level"],
                    "source_text": pair["true_claim"],
                }
                rows.append(row)
                by_type[query_type] += 1

    write_jsonl(rows, output)
    manifest = {
        "output_path": str(output),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "queries": len(rows),
        "query_types": query_types,
        "queries_by_type": dict(by_type),
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Generated paired queries: %s", len(rows))
    return manifest
