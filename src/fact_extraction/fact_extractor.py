"""Fact extraction for PCV-MIA.

The extractor upgrades the old entity-only attack signal into verifiable fact
units. It keeps the implementation dependency-light: rules find high-value
entities, sentence context turns them into claims, and the output schema is
ready for a future Sibling LLM extractor/judge.

中文说明
========
本文件对应流水线第 06 步「抽取事实」。它把上一阶段的"只有实体"升级成"可验证的事实
单元(fact)"——不光知道一个关键实体(如某个金额)，还把它所在的句子拆解成
"主语(subject) + 关系(relation) + 实体(object)"，并附上上下文。这样后面才能据此造出
一对"真实声明 / 反事实声明"。
- 实现刻意保持轻量(只用正则 + 句子上下文)，不强依赖大模型;但输出结构预留了字段，
  方便将来换成"用兄弟模型抽取/裁判"。
- 复用了 attack.entity_extractor 来找高价值实体,本文件在其基础上补"句子级的事实结构"。
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    # 进度条;没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..attack.entity_extractor import EntityExtractor
from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger


LOGGER = get_logger(__name__)

# 句子切分正则(同 chunker:在句末标点处断句)。
SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]|$)")
# 大写词组:用于从句子里抽"主语"候选(往往是专名/机构)。
CAPITAL_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.,'-]*(?:\s+[A-Z][A-Za-z0-9&.,'-]*){0,5}\b")
# 日期正则:用于在上下文里找日期,作为事实的时间背景。
DATE_CONTEXT_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{2,4}\b|"
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    """把文本切成句子列表(去掉空句)。"""
    return [match.group(0).strip() for match in SENTENCE_RE.finditer(text or "") if match.group(0).strip()]


def _sentence_for_span(text: str, start: int, end: int) -> str:
    """找出包含 [start,end) 这处实体的那句话。

    参数:
        text:       全文。
        start, end: 实体在全文中的起止位置。
    返回:
        包含该实体的句子;找不到时退回第一句或全文前 300 字符。
    """
    for sentence in _sentences(text):
        # 用 find 定位句子在全文的位置,判断实体是否落在这句话范围内。
        pos = text.find(sentence)
        if pos <= start and end <= pos + len(sentence):
            return sentence
    sentences = _sentences(text)
    return sentences[0] if sentences else (text or "").strip()[:300]


def _subject_from_sentence(sentence: str, entity: str) -> str:
    """从句子里猜"主语"(谁/什么)——通常取实体前面的最后一个大写专名短语。

    参数:
        sentence: 实体所在句子。
        entity:   目标实体文本。
    返回:
        猜出的主语(最长 120 字符);猜不到则用前几个词,再不行用 "the record"。
    """
    # 取实体之前的部分(实体往往是宾语,主语在它前面)。
    before = sentence.split(entity, 1)[0] if entity in sentence else sentence
    # 在前半句里找大写专名短语,取最后一个当主语。
    phrases = [p.strip(" ,;:") for p in CAPITAL_PHRASE_RE.findall(before) if len(p.strip()) > 1]
    if phrases:
        return phrases[-1][:120]
    # 没有专名:退而取前 6 个词;实在没有就用占位 "the record"。
    words = [w.strip(" ,;:") for w in before.split() if w.strip(" ,;:")]
    return " ".join(words[:6])[:120] or "the record"


def _relation_from_sentence(sentence: str, entity: str, entity_type: str) -> str:
    """从句子里猜"关系"(主语和实体之间是什么关系)——取实体前后各若干词拼起来。

    参数:
        sentence:    实体所在句子。
        entity:      目标实体。
        entity_type: 实体类型(没猜出关系时用作兜底描述)。
    返回:
        关系短语(最长 160 字符);猜不出则用 "contains <类型> value" 兜底。
    """
    compact = " ".join(sentence.split())
    if entity and entity in compact:
        # 以实体为界切成前后两段,各取靠近实体的若干词作为关系线索。
        before, _, after = compact.partition(entity)
        relation_words = [w.strip(" ,;:") for w in before.split()[-8:] + after.split()[:8]]
        relation = " ".join(w for w in relation_words if w)
        return relation[:160] or f"contains {entity_type.lower()} value"
    return f"contains {entity_type.lower()} value"


def _context_from_sentence(sentence: str, entity: str) -> str:
    """提取事实的"上下文"——优先用句中的日期,否则取实体周围的词。

    参数:
        sentence: 实体所在句子。
        entity:   目标实体。
    返回:
        一段上下文文本(最长 200 字符)。
    """
    # 优先收集句中(非目标实体本身的)日期,作为时间背景。
    dates = [m.group(0) for m in DATE_CONTEXT_RE.finditer(sentence) if m.group(0) != entity]
    if dates:
        return "; ".join(dates[:2])
    # 没有日期:取实体前后各若干词。
    compact = " ".join(sentence.split())
    if entity and entity in compact:
        before, _, after = compact.partition(entity)
        return " ".join((before.split()[-8:] + after.split()[:8]))[:200]
    return compact[:200]


def _is_generic_fact(sentence: str, entity_type: str) -> bool:
    """判断这条"事实"是否太泛(应丢弃):命中套话，或裸数字且句子太短。

    参数:
        sentence:    事实所在句子。
        entity_type: 实体类型。
    返回:
        太泛返回 True。
    """
    lowered = sentence.lower()
    # 一批常见套话/免责声明,命中即视为无价值。
    generic_terms = {
        "all rights reserved",
        "for informational purposes",
        "further studies are needed",
        "this communication may contain",
        "copyright",
    }
    if any(term in lowered for term in generic_terms):
        return True
    # 光秃秃一个数字、句子又很短,缺乏可验证语境。
    if entity_type == "NUMERIC_VALUE" and len(sentence.split()) < 8:
        return True
    return False


def extract_facts_file(
    benchmark_path: str | Path,
    output_path: str | Path,
    max_facts_per_doc: int = 2,
    max_entities_per_doc: int = 8,
    max_samples: int | None = None,
    min_importance: float = 0.6,
    min_replaceability: float = 0.6,
    min_privacy_specificity: float = 0.5,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Extract verifiable fact units from an attack benchmark JSONL.

    中文说明：第 06 步主入口。对基准里的每篇文档抽实体、按阈值筛掉低质量的，再把合格实体
    包装成"事实单元"(含主语/关系/实体/上下文/支撑句)写出。

    参数:
        benchmark_path:          攻击基准文件。
        output_path:             事实输出路径(并派生 .manifest/.errors)。
        max_facts_per_doc:       每篇文档最多产出几条事实。
        max_entities_per_doc:    每篇文档最多抽几个候选实体。
        max_samples:             最多处理多少篇文档;None 不限。
        min_importance:          实体重要性下限(低于则跳过)。
        min_replaceability:      实体可替换性下限。
        min_privacy_specificity: 实体隐私特异性下限。
        resume:                  断点续跑:产物已存在则跳过。
        force:                   强制重跑。
    返回:
        manifest(字典):事实数量与分布统计;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    error_path = output.with_suffix(".errors.jsonl")
    # 断点续跑。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing facts: %s", output)
        return {"output_path": str(output), "skipped_existing": True}

    extractor = EntityExtractor()
    facts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    samples = 0
    by_group: Counter[str] = Counter()   # 按分组统计事实数
    by_type: Counter[str] = Counter()    # 按实体类型统计事实数

    for row in tqdm(read_jsonl(benchmark_path), desc="extract facts", unit="doc"):
        # 到达样本上限就停。
        if max_samples is not None and samples >= max_samples:
            break
        samples += 1
        try:
            text = str(row.get("text") or "")
            # 先抽候选实体。
            entities = extractor.extract(text, max_entities=max_entities_per_doc)
            kept_for_doc = 0
            for ent in entities:
                # 本文档已凑够事实数就停。
                if kept_for_doc >= max_facts_per_doc:
                    break
                importance = float(ent.get("importance", 0.0))
                replaceability = float(ent.get("replaceability", 0.0))
                privacy_specificity = float(ent.get("privacy_specificity", 0.0))
                # 三项分数任一不达标就跳过这个实体。
                if importance < min_importance or replaceability < min_replaceability or privacy_specificity < min_privacy_specificity:
                    continue
                entity_text = str(ent.get("text") or "")
                sentence = _sentence_for_span(text, int(ent.get("start", 0)), int(ent.get("end", 0)))
                # 实体必须真的出现在所定位的句子里,且该句不能太泛。
                if not entity_text or entity_text not in sentence or _is_generic_fact(sentence, str(ent.get("type"))):
                    continue
                # 生成事实 id 并组装事实单元。
                fact_id = f"fact_{row['audit_id']}_{kept_for_doc + 1:02d}"
                fact = {
                    "fact_id": fact_id,
                    "audit_id": row["audit_id"],
                    "doc_id": row.get("doc_id"),
                    "dataset": row["dataset"],
                    "group": row["group"],
                    "subject": _subject_from_sentence(sentence, entity_text),
                    "relation": _relation_from_sentence(sentence, entity_text, str(ent.get("type"))),
                    "object_entity": entity_text,
                    "entity_type": ent.get("type"),
                    "context": _context_from_sentence(sentence, entity_text),
                    "supporting_sentence": sentence,
                    # factual_claim 暂时直接用支撑句(将来可换成更规范的声明)。
                    "factual_claim": sentence,
                    "importance": importance,
                    "replaceability": replaceability,
                    "privacy_specificity": privacy_specificity,
                    "entity_metadata": ent,
                }
                facts.append(fact)
                kept_for_doc += 1
                by_group[str(row["group"])] += 1
                by_type[str(ent.get("type"))] += 1
        except Exception as exc:  # keep bad examples auditable without aborting a long run
            # 单篇出错不中断整体:记下错误,继续下一篇。
            errors.append({"audit_id": row.get("audit_id"), "error": str(exc)})

    write_jsonl(facts, output)
    write_jsonl(errors, error_path)
    manifest = {
        "output_path": str(output),
        "error_path": str(error_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "samples_seen": samples,
        "facts": len(facts),
        "facts_by_group": dict(by_group),
        "facts_by_entity_type": dict(by_type),
        "max_facts_per_doc": max_facts_per_doc,
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Extracted facts: samples=%s facts=%s errors=%s", samples, len(facts), len(errors))
    return manifest
