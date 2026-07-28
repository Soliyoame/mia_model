"""Generate paired true and counterfactual claims for PCV-MIA.

中文说明
========
本文件对应流水线第 07 步「生成成对声明」。它读入上一步抽出的"事实"，为每条事实造出
一对声明：
    - 真实声明(true_claim)：就是原文里的那句事实(与文档一致)。
    - 反事实声明(counterfactual_claim)：把句子里的关键实体替换成"同类型假值"
      (替换逻辑来自 attack.perturbation_generator)，得到一句"看起来很像真的、其实是
      错的"声明。
这一对声明就是后面去问模型、用来判断"它是不是真懂这份文档"的探针。
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

from ..attack.perturbation_generator import (
    ATTACK_FIRST_GENERATION_PROTOCOL,
    infer_attack_subtype,
    perturb_entity_value,
)
from ..attack.semantic_entity_resolver import (
    SEMANTIC_TARGET_TYPES,
    SemanticResolverRuntime,
    load_semantic_entity_resolver,
    resolve_semantic_runtime,
)
from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import read_json, read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger
from .validator import VALIDATOR_VERSION, find_entity_span, validate_claim_pair


LOGGER = get_logger(__name__)


def _canonical_source_key(row: dict[str, Any]) -> str:
    source_id = str(row.get("source_id") or row.get("doc_id") or "").strip()
    source_path = str(row.get("source_path") or "").strip()
    source_key = str(row.get("source_key") or "").strip()
    if source_key:
        return source_key
    if source_id or source_path:
        return f"{source_path}::{source_id}"
    return str(row.get("text_hash") or "").strip()


def load_complete_source_lookup(
    corpus_path: str | Path,
    *,
    source_key_allowlist: set[str] | None = None,
) -> dict[str, str]:
    """只把允许的完整 source 聚合进内存，并校验覆盖完整。"""

    allowlist = (
        {str(value) for value in source_key_allowlist}
        if source_key_allowlist is not None
        else None
    )
    text_by_source: dict[str, list[str]] = {}
    audit_to_source: dict[str, str] = {}
    for row in read_jsonl(corpus_path):
        source_key = _canonical_source_key(row)
        if allowlist is not None and source_key not in allowlist:
            continue
        text_by_source.setdefault(source_key, []).append(
            str(row.get("text") or "")
        )
        audit_id = str(row.get("audit_id") or "").strip()
        if audit_id:
            audit_to_source[audit_id] = source_key
    if allowlist is not None:
        missing_sources = sorted(allowlist - set(text_by_source))
        if missing_sources:
            raise RuntimeError(
                "Complete source corpus is missing allowlisted sources: "
                f"{missing_sources[:5]}"
            )
    lookup = {
        source_key: "\n".join(parts)
        for source_key, parts in text_by_source.items()
    }
    for audit_id, source_key in audit_to_source.items():
        lookup[audit_id] = lookup[source_key]
    return lookup


def _find_entity_span(text: str, entity: str) -> tuple[int, int] | None:
    """在 text 中定位 entity 的首次出现,返回 (start, end);找不到返回 None。

    依次尝试三种匹配,容忍事实抽取的实体与原句之间常见的细微差异,减少"明明在句里却
    匹配不上而整条事实被丢弃"的情况(这种丢弃若与分组相关,会引入 selection bias):
      1) 精确子串;
      2) 大小写不敏感;
      3) 空白容忍——把 entity 内部的连续空白当作 \\s+,匹配跨换行/多空格的写法。
    用 (start, end) 而非字符串替换,便于在原句精确位置做一次切片替换,不误伤其它相同字样。
    """
    if not entity:
        return None
    # 1) 精确子串。
    idx = text.find(entity)
    if idx >= 0:
        return idx, idx + len(entity)
    # 2) 大小写不敏感。
    low_idx = text.lower().find(entity.lower())
    if low_idx >= 0:
        return low_idx, low_idx + len(entity)
    # 3) 空白容忍:实体内部空白放宽成 \s+,其余字符按字面转义。
    tokens = entity.split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(tok) for tok in tokens)
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.start(), match.end()
    return None


def generate_paired_claims_file(
    facts_path: str | Path,
    output_path: str | Path,
    benchmark_path: str | Path | None = None,
    source_corpus_path: str | Path | None = None,
    perturbation_levels: list[str] | None = None,
    max_pairs_per_fact: int = 1,
    semantic_resolver_config: dict[str, Any] | None = None,
    semantic_resolver_runtime: SemanticResolverRuntime | None = None,
    enforce_original_metadata_semantics: bool = True,
    source_key_allowlist: set[str] | None = None,
    dataset: str | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Generate one or more true/counterfactual claim pairs per fact.

    中文说明：第 07 步主入口。对每条事实，按指定的扰动强度生成若干对(真实/反事实)声明。
    会跳过那些"实体不在声明里"或"扰动后没产生变化"的异常情况，并记录到错误文件。

    参数:
        facts_path:          上一步产出的事实文件。
        output_path:         成对声明输出路径(并派生 .manifest/.errors)。
        benchmark_path:      原 benchmark；用于验证反事实未在完整 source 中出现。
        source_corpus_path:   可选完整 source 语料；eligibility cap 只抽部分 chunk 时必须提供。
        perturbation_levels: 扰动强度列表(如 ["light"]、["light","medium"])。
        max_pairs_per_fact:  每条事实最多造几对声明。
        semantic_resolver_config:v6.3 本地 precision cascade 与模型锁配置。
        dataset:             数据集名；启用 resolver 时必须提供。
        resume:              断点续跑:产物已存在则跳过。
        force:               强制重跑。
    返回:
        manifest(字典):声明对数量与分布统计;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    error_path = output.with_suffix(".errors.jsonl")
    levels = perturbation_levels or ["light"]
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
    facts_hash = sha256_file(facts_path)
    benchmark_hash = sha256_file(benchmark_path) if benchmark_path is not None else None
    source_corpus_hash = (
        sha256_file(source_corpus_path) if source_corpus_path is not None else benchmark_hash
    )
    semantic_config_hash = sha256_obj(semantic_cfg)
    source_allowlist = (
        {str(value) for value in source_key_allowlist}
        if source_key_allowlist is not None
        else None
    )
    source_allowlist_hash = (
        sha256_obj(sorted(source_allowlist))
        if source_allowlist is not None
        else None
    )
    # 断点续跑。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        existing = read_json(manifest_path)
        expected = {
            "claim_validator_version": VALIDATOR_VERSION,
            "perturbation_levels": levels,
            "max_pairs_per_fact": int(max_pairs_per_fact),
            "semantic_resolver_enabled": semantic_enabled,
            "enforce_original_metadata_semantics": bool(
                enforce_original_metadata_semantics
            ),
        }
        if semantic_enabled:
            expected.update(
                {
                    "input_facts_hash": facts_hash,
                    "input_benchmark_hash": benchmark_hash,
                    "input_source_corpus_hash": source_corpus_hash,
                    "semantic_resolver_config_hash": semantic_config_hash,
                    "semantic_entity_resolver": semantic_metadata.to_dict(),
                    "source_key_allowlist_hash": source_allowlist_hash,
                    "dataset": str(dataset),
                }
            )
        mismatches = {
            key: {"expected": value, "actual": existing.get(key)}
            for key, value in expected.items()
            if existing.get(key) != value
        }
        if mismatches:
            raise RuntimeError(
                f"Existing paired claims do not match the v19 validation protocol: {mismatches}. "
                "Rebuild Step 07 with --force."
            )
        LOGGER.info("Skipping existing paired claims: %s", output)
        return {**existing, "output_path": str(output), "skipped_existing": True}

    source_lookup: dict[str, str] = {}
    if semantic_enabled:
        if benchmark_path is None:
            raise ValueError(
                "v6.3 semantic counterfactual validation requires benchmark_path"
            )
        corpus_path = source_corpus_path or benchmark_path
        source_lookup = load_complete_source_lookup(
            corpus_path,
            source_key_allowlist=source_allowlist,
        )

    # 默认只用 light 强度。
    pairs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_group: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    by_validation_failure: Counter[str] = Counter()
    pending_semantic: list[dict[str, Any]] = []

    for fact in tqdm(read_jsonl(facts_path), desc="paired claims", unit="fact"):
        made = 0
        original = str(fact.get("object_entity") or "")        # 真实实体
        # 真实声明:优先用 factual_claim,没有就用支撑句。
        true_claim = str(fact.get("factual_claim") or fact.get("supporting_sentence") or "")
        entity_type = str(fact.get("entity_type") or "")
        is_semantic_fact = (
            semantic_enabled and entity_type.upper() in SEMANTIC_TARGET_TYPES
        )
        entity_metadata = (
            fact.get("entity_metadata")
            if isinstance(fact.get("entity_metadata"), dict)
            else {}
        )
        original_semantic_resolution = (
            entity_metadata.get("semantic_resolution")
            if isinstance(entity_metadata.get("semantic_resolution"), dict)
            else None
        )
        # 真实实体必须能在真实声明里定位到(精确→大小写不敏感→空白容忍),否则没法做替换。
        # span 只依赖 true_claim 与 original,与扰动强度无关,故在 level 循环外算一次。
        stored_span = fact.get("claim_entity_span")
        span: tuple[int, int] | None = None
        if (
            isinstance(stored_span, list)
            and len(stored_span) == 2
            and all(isinstance(item, int) for item in stored_span)
        ):
            candidate_span = (int(stored_span[0]), int(stored_span[1]))
            if (
                0 <= candidate_span[0] < candidate_span[1] <= len(true_claim)
                and " ".join(true_claim[candidate_span[0] : candidate_span[1]].casefold().split())
                == " ".join(original.casefold().split())
            ):
                span = candidate_span
        if span is None:
            span = find_entity_span(true_claim, original) if original else None
        if span is None:
            reason = "original_entity_boundary_not_found"
            errors.append(
                {
                    "fact_id": fact.get("fact_id"),
                    "error": "claim_validation_failed",
                    "validation_failure_reason": reason,
                    "validation_failure_reasons": [reason],
                    "claim_validator_version": VALIDATOR_VERSION,
                }
            )
            by_validation_failure[reason] += 1
            continue
        for level in levels:
            # 凑够这条事实的对数就停。
            if (not is_semantic_fact and made >= max_pairs_per_fact) or (
                is_semantic_fact and max_pairs_per_fact <= 0
            ):
                break
            # 生成同类型的假值。
            try:
                counterfactual = perturb_entity_value(
                    original,
                    entity_type,
                    level=level,
                    semantic_subtype_name=(
                        str(original_semantic_resolution.get("subtype") or "")
                        if original_semantic_resolution is not None
                        else None
                    ),
                    context=true_claim,
                )
            except (TypeError, ValueError, OverflowError) as exc:
                reason = "counterfactual_generation_error"
                errors.append(
                    {
                        "fact_id": fact.get("fact_id"),
                        "error": "claim_validation_failed",
                        "level": level,
                        "validation_failure_reason": reason,
                        "validation_failure_reasons": [reason],
                        "error_detail": f"{type(exc).__name__}: {exc}",
                        "claim_validator_version": VALIDATOR_VERSION,
                    }
                )
                by_validation_failure[reason] += 1
                continue
            # 扰动没产生变化(假值=真值)就跳过并记录。
            if not counterfactual or counterfactual == original:
                reason = "counterfactual_entity_unchanged"
                errors.append(
                    {
                        "fact_id": fact.get("fact_id"),
                        "error": "claim_validation_failed",
                        "level": level,
                        "validation_failure_reason": reason,
                        "validation_failure_reasons": [reason],
                        "claim_validator_version": VALIDATOR_VERSION,
                    }
                )
                by_validation_failure[reason] += 1
                continue
            if semantic_enabled and entity_type.upper() in SEMANTIC_TARGET_TYPES:
                source_text = source_lookup.get(str(fact.get("source_key") or ""))
                if source_text is None:
                    source_text = source_lookup.get(str(fact.get("audit_id") or ""))
                if source_text is None:
                    reason = "source_text_missing_for_counterfactual_check"
                    errors.append(
                        {
                            "fact_id": fact.get("fact_id"),
                            "error": "claim_validation_failed",
                            "level": level,
                            "validation_failure_reason": reason,
                            "validation_failure_reasons": [reason],
                            "claim_validator_version": VALIDATOR_VERSION,
                        }
                    )
                    by_validation_failure[reason] += 1
                    continue
                if find_entity_span(source_text, counterfactual) is not None:
                    reason = "counterfactual_entity_present_in_source"
                    errors.append(
                        {
                            "fact_id": fact.get("fact_id"),
                            "error": "claim_validation_failed",
                            "level": level,
                            "validation_failure_reason": reason,
                            "validation_failure_reasons": [reason],
                            "claim_validator_version": VALIDATOR_VERSION,
                        }
                    )
                    by_validation_failure[reason] += 1
                    continue
            # 在定位到的 span 处把实体换成假值(切片替换,容忍大小写/空白差异)。
            counterfactual_claim = true_claim[: span[0]] + counterfactual + true_claim[span[1] :]
            # 替换若没生效(声明没变),也跳过并记录。
            if counterfactual_claim == true_claim:
                reason = "not_single_slot_substitution"
                errors.append(
                    {
                        "fact_id": fact.get("fact_id"),
                        "error": "claim_validation_failed",
                        "level": level,
                        "validation_failure_reason": reason,
                        "validation_failure_reasons": [reason],
                        "claim_validator_version": VALIDATOR_VERSION,
                    }
                )
                by_validation_failure[reason] += 1
                continue
            if is_semantic_fact:
                pending_semantic.append(
                    {
                        "fact": fact,
                        "level": level,
                        "true_claim": true_claim,
                        "counterfactual_claim": counterfactual_claim,
                        "original": original,
                        "counterfactual": counterfactual,
                        "entity_type": entity_type,
                        "entity_metadata": entity_metadata,
                        "original_semantic_resolution": original_semantic_resolution,
                        "original_attack_subtype": infer_attack_subtype(
                            original,
                            entity_type,
                            context=true_claim,
                        ),
                        "candidate": {
                            "text": counterfactual,
                            "type": entity_type,
                            "start": span[0],
                            "end": span[0] + len(counterfactual),
                        },
                    }
                )
                continue
            counterfactual_semantic_resolution: dict[str, Any] | None = None
            validation = validate_claim_pair(
                true_claim,
                counterfactual_claim,
                original,
                counterfactual,
                entity_type,
                entity_metadata=(
                    entity_metadata
                    if enforce_original_metadata_semantics
                    else None
                ),
                counterfactual_semantic_resolution=counterfactual_semantic_resolution,
                semantic_resolution_required=semantic_enabled,
            )
            if not validation.valid:
                errors.append(
                    {
                        "fact_id": fact.get("fact_id"),
                        "error": "claim_validation_failed",
                        "level": level,
                        "validation_failure_reason": validation.failure_reason,
                        "validation_failure_reasons": list(validation.reasons),
                        "claim_validator_version": VALIDATOR_VERSION,
                    }
                )
                by_validation_failure.update(validation.reasons)
                continue
            # 组装这一对声明。
            pair_id = f"pair_{fact['audit_id']}_{len(pairs):06d}"
            pairs.append(
                {
                    "pair_id": pair_id,
                    "fact_id": fact["fact_id"],
                    "audit_id": fact["audit_id"],
                    "doc_id": fact.get("doc_id"),
                    "source_id": fact.get("source_id") or fact.get("doc_id"),
                    "source_key": fact.get("source_key") or fact.get("source_id") or fact.get("doc_id"),
                    "dataset": fact["dataset"],
                    "group": fact["group"],
                    "true_claim": true_claim,
                    "counterfactual_claim": counterfactual_claim,
                    "original_entity": original,
                    "counterfactual_entity": counterfactual,
                    "entity_type": entity_type,
                    "perturbation_level": level,
                    "subject": fact.get("subject"),
                    "relation": fact.get("relation"),
                    "context": fact.get("context"),
                    "selection_tier": fact.get("selection_tier"),
                    "quality_weight": fact.get("quality_weight"),
                    "claim_validation_status": "passed",
                    "claim_validator_version": VALIDATOR_VERSION,
                    "original_semantic_resolution": original_semantic_resolution,
                    "counterfactual_semantic_resolution": counterfactual_semantic_resolution,
                    "counterfactual_generation_protocol": (
                        ATTACK_FIRST_GENERATION_PROTOCOL
                    ),
                    "original_attack_subtype": infer_attack_subtype(
                        original,
                        entity_type,
                        context=true_claim,
                    ),
                    "counterfactual_attack_subtype": infer_attack_subtype(
                        counterfactual,
                        entity_type,
                        context=counterfactual_claim,
                    ),
                }
            )
            made += 1
            by_group[str(fact["group"])] += 1
            by_type[entity_type] += 1

    if pending_semantic:
        assert semantic_resolver is not None
        semantic_batch_size = max(1, int(semantic_metadata.batch_size))
        window_size = semantic_batch_size * 16
        accepted_by_fact: Counter[str] = Counter()
        for offset in tqdm(
            range(0, len(pending_semantic), window_size),
            desc="semantic counterfactual replay",
            unit="batch",
        ):
            pending_batch = pending_semantic[offset : offset + window_size]
            precomputed_batch = semantic_resolver.predict_batch(
                [str(item["counterfactual_claim"]) for item in pending_batch],
                dataset=str(dataset or ""),
                batch_size=semantic_batch_size,
                trace_contexts=[
                    {
                        "dataset": str(dataset or ""),
                        "source_key": str(
                            item["fact"].get("source_key")
                            or item["fact"].get("source_id")
                            or item["fact"].get("doc_id")
                            or ""
                        ),
                    }
                    for item in pending_batch
                ],
            )
            for item, precomputed in zip(
                pending_batch,
                precomputed_batch,
                strict=True,
            ):
                fact = item["fact"]
                fact_key = str(fact.get("fact_id") or fact.get("audit_id") or "")
                if accepted_by_fact[fact_key] >= max_pairs_per_fact:
                    continue
                resolved = semantic_resolver.resolve_candidate(
                    str(item["counterfactual_claim"]),
                    item["candidate"],
                    dataset=str(dataset or fact.get("dataset") or ""),
                    precomputed_predictions=precomputed,
                )
                counterfactual_semantic_resolution = resolved.to_dict()
                validation = validate_claim_pair(
                    str(item["true_claim"]),
                    str(item["counterfactual_claim"]),
                    str(item["original"]),
                    str(item["counterfactual"]),
                    str(item["entity_type"]),
                    entity_metadata=(
                        item["entity_metadata"]
                        if enforce_original_metadata_semantics
                        else None
                    ),
                    counterfactual_semantic_resolution=(
                        counterfactual_semantic_resolution
                    ),
                    semantic_resolution_required=True,
                )
                if not validation.valid:
                    errors.append(
                        {
                            "fact_id": fact.get("fact_id"),
                            "error": "claim_validation_failed",
                            "level": item["level"],
                            "validation_failure_reason": validation.failure_reason,
                            "validation_failure_reasons": list(validation.reasons),
                            "claim_validator_version": VALIDATOR_VERSION,
                        }
                    )
                    by_validation_failure.update(validation.reasons)
                    continue
                pair_id = f"pair_{fact['audit_id']}_{len(pairs):06d}"
                pairs.append(
                    {
                        "pair_id": pair_id,
                        "fact_id": fact["fact_id"],
                        "audit_id": fact["audit_id"],
                        "doc_id": fact.get("doc_id"),
                        "source_id": fact.get("source_id") or fact.get("doc_id"),
                        "source_key": (
                            fact.get("source_key")
                            or fact.get("source_id")
                            or fact.get("doc_id")
                        ),
                        "dataset": fact["dataset"],
                        "group": fact["group"],
                        "true_claim": item["true_claim"],
                        "counterfactual_claim": item["counterfactual_claim"],
                        "original_entity": item["original"],
                        "counterfactual_entity": item["counterfactual"],
                        "entity_type": item["entity_type"],
                        "perturbation_level": item["level"],
                        "subject": fact.get("subject"),
                        "relation": fact.get("relation"),
                        "context": fact.get("context"),
                        "selection_tier": fact.get("selection_tier"),
                        "quality_weight": fact.get("quality_weight"),
                        "claim_validation_status": "passed",
                        "claim_validator_version": VALIDATOR_VERSION,
                        "original_semantic_resolution": item[
                            "original_semantic_resolution"
                        ],
                        "counterfactual_semantic_resolution": (
                            counterfactual_semantic_resolution
                        ),
                        "counterfactual_generation_protocol": (
                            ATTACK_FIRST_GENERATION_PROTOCOL
                        ),
                        "original_attack_subtype": item[
                            "original_attack_subtype"
                        ],
                        "counterfactual_attack_subtype": infer_attack_subtype(
                            str(item["counterfactual"]),
                            str(item["entity_type"]),
                            context=str(item["counterfactual_claim"]),
                        ),
                    }
                )
                accepted_by_fact[fact_key] += 1
                by_group[str(fact["group"])] += 1
                by_type[str(item["entity_type"])] += 1

    write_jsonl(pairs, output)
    write_jsonl(errors, error_path)
    manifest = {
        "output_path": str(output),
        "error_path": str(error_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pairs": len(pairs),
        "errors": len(errors),
        "pairs_by_group": dict(by_group),
        "pairs_by_entity_type": dict(by_type),
        "validation_failures_by_reason": dict(by_validation_failure),
        "claim_validator_version": VALIDATOR_VERSION,
        "counterfactual_generation_protocol": ATTACK_FIRST_GENERATION_PROTOCOL,
        "perturbation_levels": levels,
        "max_pairs_per_fact": int(max_pairs_per_fact),
        "dataset": str(dataset or ""),
        "input_facts_hash": facts_hash,
        "input_benchmark_hash": benchmark_hash,
        "input_source_corpus_hash": source_corpus_hash,
        "semantic_resolver_config_hash": semantic_config_hash,
        "semantic_resolver_enabled": semantic_metadata.enabled,
        "enforce_original_metadata_semantics": bool(
            enforce_original_metadata_semantics
        ),
        "semantic_entity_resolver": semantic_metadata.to_dict(),
        "source_key_allowlist_hash": source_allowlist_hash,
    }
    write_json(manifest, manifest_path)
    LOGGER.info("Generated paired claims: pairs=%s errors=%s", len(pairs), len(errors))
    return manifest
