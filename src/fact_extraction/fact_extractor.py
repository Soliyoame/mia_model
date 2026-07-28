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
from itertools import islice
from pathlib import Path
from typing import Any

try:
    # 进度条;没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

from ..attack.entity_extractor import EXTRACTOR_VERSION, EntityExtractor
from ..attack.local_ner import load_local_ner_model
from ..attack.semantic_entity_resolver import (
    SemanticResolverRuntime,
    SemanticResolverProtocolError,
    load_semantic_entity_resolver,
    resolve_semantic_runtime,
)
from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import read_json, read_jsonl, write_json, write_jsonl
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
    guarantee_min_facts: int = 1,
    ner_config: dict[str, Any] | None = None,
    semantic_resolver_config: dict[str, Any] | None = None,
    semantic_resolver_runtime: SemanticResolverRuntime | None = None,
    dataset: str | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Extract verifiable fact units from an attack benchmark JSONL.

    中文说明：第 06 步主入口(方案 D：保覆盖 + 质量加权)。对每篇文档抽实体、把合格实体包装成
    "事实单元"。**三道阈值与 _is_generic_fact 不再是淘汰线，而是"优选标准"**：先选满足阈值的
    高质量事实(primary)，若某文档不足 guarantee_min_facts，则从未达标的事实里按可攻击性补齐
    (fallback)。每条事实写入 quality_weight(=attackability_score) 与 selection_tier，质量控制
    下放到第 11 步的加权聚合：低质量事实权重小、贡献被自动压低，而不再被整篇丢弃。

    参数:
        benchmark_path:          攻击基准文件。
        output_path:             事实输出路径(并派生 .manifest/.errors)。
        max_facts_per_doc:       每篇文档最多产出几条事实(优选上限)。
        max_entities_per_doc:    每篇文档最多抽几个候选实体。
        max_samples:             最多处理多少篇文档;None 不限。
        min_importance:          实体重要性优选阈值(不达标降级为 fallback，不再丢弃)。
        min_replaceability:      实体可替换性优选阈值。
        min_privacy_specificity: 实体隐私特异性优选阈值。
        guarantee_min_facts:     每篇文档保底产出几条(只要有可成句的实体)；用于消除
                                 "可抽取性=组别"的 selection bias 并保证评估覆盖率。
        semantic_resolver_config:v6.3 本地 precision cascade 与模型锁配置。
        dataset:                 数据集名；启用 resolver 时必须提供。
        resume:                  断点续跑:产物已存在则跳过。
        force:                   强制重跑。
    返回:
        manifest(字典):事实数量、按 tier/组/类型的分布、覆盖率、零候选文档数;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    error_path = output.with_suffix(".errors.jsonl")
    semantic_cfg = dict(semantic_resolver_config or {})
    semantic_enabled = bool(semantic_cfg.get("enabled", False))
    if semantic_enabled and not dataset:
        raise ValueError("Enabled v6.3 semantic resolver requires an explicit dataset")
    semantic_resolver, semantic_metadata = (
        load_semantic_entity_resolver(
            semantic_cfg,
            dataset=str(dataset or ""),
        )
        if semantic_resolver_runtime is None
        else resolve_semantic_runtime(
            semantic_cfg,
            dataset=str(dataset or ""),
            runtime=semantic_resolver_runtime,
        )
    )
    benchmark_hash = sha256_file(benchmark_path)
    semantic_config_hash = sha256_obj(semantic_cfg)
    # 断点续跑。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        existing = read_json(manifest_path)
        if existing.get("extractor_version") != EXTRACTOR_VERSION:
            raise RuntimeError(
                "Existing facts do not match the v19 extractor protocol: "
                f"expected extractor_version={EXTRACTOR_VERSION!r}, "
                f"actual={existing.get('extractor_version')!r}. Rebuild Step 06 with --force."
            )
        if semantic_enabled:
            expected = {
                "input_benchmark_hash": benchmark_hash,
                "semantic_resolver_config_hash": semantic_config_hash,
                "semantic_entity_resolver": semantic_metadata.to_dict(),
                "dataset": str(dataset),
            }
            mismatches = {
                key: {"expected": value, "actual": existing.get(key)}
                for key, value in expected.items()
                if existing.get(key) != value
            }
            if mismatches:
                raise RuntimeError(
                    "Existing v6.3 facts are not bound to the current benchmark/"
                    f"semantic model lock: {mismatches}. Rebuild Step 06 with --force."
                )
        LOGGER.info("Skipping existing facts: %s", output)
        return {**existing, "output_path": str(output), "skipped_existing": True}

    ner_model, ner_metadata = load_local_ner_model(ner_config)
    ner_cfg = dict(ner_config or {})
    ner_batch_size = max(1, int(ner_cfg.get("batch_size", 32)))
    semantic_batch_size = max(1, int(semantic_cfg.get("batch_size", 8)))
    if semantic_metadata.enabled and ner_metadata.enabled:
        raise ValueError(
            "v6.3 semantic resolver already includes transformer NER; "
            "legacy fact_extraction.ner must be disabled"
        )
    extractor = EntityExtractor(
        ner_model=ner_model,
        ner_model_name=ner_metadata.model,
        enable_ner=ner_metadata.enabled,
        ner_confidence_threshold=float(ner_cfg.get("confidence_threshold", 0.75)),
        semantic_resolver=semantic_resolver,
        require_semantic_resolver=semantic_metadata.enabled,
    )
    facts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    samples = 0
    by_group: Counter[str] = Counter()   # 按分组统计事实数
    by_type: Counter[str] = Counter()    # 按实体类型统计事实数
    by_tier: Counter[str] = Counter()    # 按 primary/fallback 统计事实数
    docs_with_fact: Counter[str] = Counter()   # 每组"产出>=1条事实"的文档数
    docs_total: Counter[str] = Counter()       # 每组文档总数
    zero_candidate_docs = 0                    # 连一个可成句实体都没有的文档数(不可约)

    row_iter = read_jsonl(benchmark_path)
    if max_samples is not None:
        row_iter = islice(row_iter, max_samples)

    if semantic_metadata.enabled:
        assert semantic_resolver is not None

        def semantic_rows():
            while True:
                batch = list(islice(row_iter, semantic_batch_size))
                if not batch:
                    return
                texts = [str(row.get("text") or "") for row in batch]
                predictions = semantic_resolver.predict_batch(
                    texts,
                    dataset=str(dataset or ""),
                    batch_size=semantic_batch_size,
                    trace_contexts=[
                        {
                            "dataset": str(dataset or ""),
                            "source_key": str(
                                row.get("source_key")
                                or row.get("source_id")
                                or row.get("doc_id")
                                or ""
                            ),
                        }
                        for row in batch
                    ],
                )
                for row, semantic_predictions in zip(
                    batch,
                    predictions,
                    strict=True,
                ):
                    yield row, None, semantic_predictions

        processed_rows = semantic_rows()
        ner_processing_mode = "disabled_for_semantic_precision_cascade"
        semantic_processing_mode = "batch"
    elif ner_metadata.enabled and ner_model is not None and hasattr(ner_model, "pipe"):
        text_rows = ((str(row.get("text") or ""), row) for row in row_iter)
        processed_rows = (
            (row, ner_output, None)
            for ner_output, row in ner_model.pipe(
                text_rows,
                as_tuples=True,
                batch_size=ner_batch_size,
            )
        )
        ner_processing_mode = "batch_pipe"
        semantic_processing_mode = "disabled"
    else:
        processed_rows = ((row, None, None) for row in row_iter)
        ner_processing_mode = "per_document"
        semantic_processing_mode = "disabled"

    for row, ner_output, semantic_predictions in tqdm(
        processed_rows,
        desc="extract facts",
        unit="doc",
    ):
        samples += 1
        group = str(row["group"])
        docs_total[group] += 1
        try:
            text = str(row.get("text") or "")
            # 抽候选实体(保底覆盖:即便都不过门槛，也会返回最好的若干个)。
            entities = extractor.extract(
                text,
                max_entities=max_entities_per_doc,
                guarantee_min=max(1, guarantee_min_facts),
                ner_output=ner_output,
                dataset=str(row.get("dataset") or dataset or ""),
                semantic_predictions=semantic_predictions,
            )
            # 先把所有能"成句"的实体做成候选事实，并标好 tier，再统一挑选。
            candidate_facts: list[dict[str, Any]] = []
            for ent in entities:
                entity_text = str(ent.get("text") or "")
                # 复用 entity_extractor 已用正确 finditer 偏移算好的支撑句;它定位准确。
                # (不要用 _sentence_for_span 基于 text.find 重算——邮件头等重复短行会令 find
                #  返回错误位置，把实体误配到无关句子，从而被下面的"实体在句中"检查误杀。)
                sentence = str(
                    ent.get("supporting_sentence")
                    or _sentence_for_span(text, int(ent.get("start", 0)), int(ent.get("end", 0)))
                )
                # 结构性硬要求:实体必须真出现在所定位句子里(否则无法构造可替换的声明)。
                if not entity_text or entity_text not in sentence:
                    continue
                importance = float(ent.get("importance", 0.0))
                replaceability = float(ent.get("replaceability", 0.0))
                privacy_specificity = float(ent.get("privacy_specificity", 0.0))
                # 优选条件:过实体硬门槛 + 三道阈值 + 句子不太泛。任一不满足 → 降级为 fallback。
                meets_threshold = (
                    importance >= min_importance
                    and replaceability >= min_replaceability
                    and privacy_specificity >= min_privacy_specificity
                )
                gate_passed = bool(ent.get("gate_passed", True))
                is_generic = _is_generic_fact(sentence, str(ent.get("type")))
                tier = "primary" if (gate_passed and meets_threshold and not is_generic) else "fallback"
                em = ent.get("entity_metadata") if isinstance(ent.get("entity_metadata"), dict) else ent
                # 质量权重 = 可攻击性分(检验2 证明它预测信号信噪比)；兜底用三项均值。
                quality_weight = float(
                    ent.get("attackability_score")
                    or (em.get("attackability_score") if isinstance(em, dict) else None)
                    or ((importance + replaceability + privacy_specificity) / 3.0)
                )
                candidate_facts.append(
                    {
                        "entity": ent,
                        "entity_text": entity_text,
                        "sentence": sentence,
                        "importance": importance,
                        "replaceability": replaceability,
                        "privacy_specificity": privacy_specificity,
                        "tier": tier,
                        "quality_weight": round(quality_weight, 4),
                    }
                )

            if not candidate_facts:
                # 连一个可成句的候选都没有:这是方案 D 也无法挽救的不可约样本。
                zero_candidate_docs += 1
                continue

            # 挑选:primary 优先(按可攻击性降序)，最多 max_facts_per_doc；
            # 若不足 guarantee_min_facts，再从 fallback 按可攻击性降序补齐到保底数。
            primary = sorted(
                [c for c in candidate_facts if c["tier"] == "primary"],
                key=lambda c: -c["quality_weight"],
            )
            fallback = sorted(
                [c for c in candidate_facts if c["tier"] == "fallback"],
                key=lambda c: -c["quality_weight"],
            )
            chosen = primary[:max_facts_per_doc]
            if len(chosen) < max(1, guarantee_min_facts):
                need = max(1, guarantee_min_facts) - len(chosen)
                chosen = chosen + fallback[:need]

            for idx, cf in enumerate(chosen, start=1):
                ent = cf["entity"]
                entity_text = cf["entity_text"]
                sentence = cf["sentence"]
                fact_id = f"fact_{row['audit_id']}_{idx:02d}"
                fact = {
                    "fact_id": fact_id,
                    "audit_id": row["audit_id"],
                    "doc_id": row.get("doc_id"),
                    "source_id": row.get("source_id") or row.get("doc_id"),
                    "source_key": row.get("source_key") or row.get("source_id") or row.get("doc_id"),
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
                    # 绑定实体在 factual_claim 中的确切 occurrence，避免同一句出现相同
                    # 数值/名称时 Step 07 总是误替换第一次出现。
                    "claim_entity_span": ent.get("entity_sentence_span"),
                    "importance": cf["importance"],
                    "replaceability": cf["replaceability"],
                    "privacy_specificity": cf["privacy_specificity"],
                    # 方案 D 新增:质量权重(供第 11 步加权聚合)与质量分层标记(供三口径对比)。
                    "quality_weight": cf["quality_weight"],
                    "selection_tier": cf["tier"],
                    "entity_metadata": ent,
                    "extractor_version": EXTRACTOR_VERSION,
                }
                facts.append(fact)
                by_group[group] += 1
                by_type[str(ent.get("type"))] += 1
                by_tier[cf["tier"]] += 1
            if chosen:
                docs_with_fact[group] += 1
        except SemanticResolverProtocolError:
            # 模型/锁/schema/推理异常是正式协议错误，不能被当作单篇坏样本吞掉。
            raise
        except Exception as exc:  # keep bad examples auditable without aborting a long run
            # 单篇出错不中断整体:记下错误,继续下一篇。
            errors.append({"audit_id": row.get("audit_id"), "error": str(exc)})

    write_jsonl(facts, output)
    write_jsonl(errors, error_path)
    # 每组覆盖率(产出>=1条事实的文档占比)，用于核验 selection bias 是否已被消除。
    coverage = {g: (docs_with_fact[g] / docs_total[g] if docs_total[g] else 0.0) for g in docs_total}
    manifest = {
        "output_path": str(output),
        "error_path": str(error_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "samples_seen": samples,
        "facts": len(facts),
        "facts_by_group": dict(by_group),
        "facts_by_entity_type": dict(by_type),
        "facts_by_tier": dict(by_tier),
        "docs_with_fact_by_group": dict(docs_with_fact),
        "docs_total_by_group": dict(docs_total),
        "coverage_by_group": coverage,
        "zero_candidate_docs": zero_candidate_docs,
        "max_facts_per_doc": max_facts_per_doc,
        "guarantee_min_facts": guarantee_min_facts,
        "extractor_version": EXTRACTOR_VERSION,
        "dataset": str(dataset or ""),
        "input_benchmark_hash": benchmark_hash,
        "semantic_resolver_config_hash": semantic_config_hash,
        "local_ner": {
            **ner_metadata.to_dict(),
            "processing_mode": ner_processing_mode,
            "batch_size": ner_batch_size,
        },
        "semantic_entity_resolver": semantic_metadata.to_dict(),
        "semantic_processing_mode": semantic_processing_mode,
        "semantic_batch_size": semantic_batch_size,
    }
    write_json(manifest, manifest_path)
    LOGGER.info(
        "Extracted facts: samples=%s facts=%s (primary=%s fallback=%s) zero_candidate_docs=%s errors=%s",
        samples, len(facts), by_tier.get("primary", 0), by_tier.get("fallback", 0), zero_candidate_docs, len(errors),
    )
    return manifest
