"""v24 pre-split eligibility checks and bounded development canaries.

The canary is deliberately membership blind.  It may call only the configured
Luna sibling model; Retriever, victim, membership and AUC are never loaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v24 import (  # noqa: E402
    DATASET_ORDER,
    _query_input_quality_reasons,
    _reject_forbidden,
    _source_identity,
    CandidateFactPoolReader,
    LunaCandidateProvider,
    LunaDirectCandidateProvider,
    build_candidate_fact_pool,
    build_luna_candidate_provider,
    build_v24_semantic_similarity,
    collect_development_identities,
    enumerate_candidate_facts,
    get_max_candidate_facts_per_source,
    iter_frozen_source_pool,
    load_v24_config,
    load_candidate_fact_pools,
    reference_fact_view,
    summarize_fact_ablation,
    scan_until_target,
    screen_source,
    select_luna_direct_pairs,
    source_pool_bindings,
    validate_eligibility_manifest,
    validate_split_manifest,
    validate_luna_direct_source,
)
from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import (  # noqa: E402
    append_jsonl_record,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
    write_jsonl_atomic,
)


CANARY_OUTPUT_DIR = Path("artifacts/v24/development/query_quality_canary_r1")
CAPACITY_OUTPUT_DIR = Path("artifacts/v24/development/capacity_check_r1")
FRESH_CANARY_OUTPUT_DIR = Path(
    "artifacts/v24/development/query_quality_canary_r3_fresh_preflight"
)
LUNA_ONLY_AB_OUTPUT_DIR = Path(
    "artifacts/v24/development/luna_only_ab_fresh30"
)
TWO_STAGE_ATTEMPTS = (
    "fact_construction", "fact_verification", "initial", "initial_verification",
    "semantic_correction", "semantic_correction_verification",
)


# 这些词只用于选择 development-only canary fixture，不是 v24 scientific gate。
_FRESH_CANARY_LOW_INFORMATION_ENTITIES = frozenset(
    {
        "a",
        "an",
        "after",
        "and",
        "another",
        "as",
        "at",
        "but",
        "by",
        "dear editors",
        "every december",
        "for",
        "from",
        "he",
        "her",
        "if",
        "i",
        "i've",
        "in",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "please",
        "privacy",
        "reports",
        "she",
        "supporting information",
        "there",
        "attached",
        "the",
        "them",
        "they",
        "this",
        "those",
        "these",
        "to",
        "we",
        "you",
        "your",
        "the company",
        "what i",
        "assignment",
    }
)
_FRESH_CANARY_CONNECTOR_WORDS = frozenset(
    {
        "although",
        "as",
        "at",
        "during",
        "for",
        "from",
        "if",
        "in",
        "on",
        "or",
        "since",
        "to",
    }
)
_FRESH_CANARY_HEADING_PREFIX_RE = re.compile(
    r"(?i)^(?:item\s+\d+|common\s+name|discussion(?:\s+damage)?|"
    r"conclusion(?:\s+this)?|introduction(?:\s+more)?|methods|results|"
    r"background|images?|figure|fig\.?|purpose|case\s+presentation|"
    r"measurements\s+questionnaire|supplementary|table\b|the\s+role\s+of\b|"
    r"non[- ]gaussian\s+models\b)"
)
_FRESH_CANARY_METADATA_PREFIX_RE = re.compile(
    r"(?i)^(?:start\s+date\s*:|subject\s*:|sent\s+from\b|"
    r"attaching\s+the\b|regards\b|thanks\b)"
)
_FRESH_CANARY_TABLE_FRAGMENT_RE = re.compile(
    r"(?i)\b(?:common\s+name|species\s+family|maximum\s+length|"
    r"vast\s+age\s+classes|trawls\s+per\s+year)\b"
)
_FRESH_CANARY_TRUNCATED_TAIL_RE = re.compile(
    r"(?i)(?:[$€£]\d+|\(\s*\d+\.|\b(?:the|a|an|of|to|in|on|at|for|from|and|or|u|s)\s*)\.$"
)
_FRESH_CANARY_TITLE_GLUE_RE = re.compile(
    r"^(?:(?i:government\s+contract\s+matters\s*[-–])|"
    r"(?i:financial\s+markets\s+today\s*[-–])|"
    r"(?:[A-Z][a-z0-9-]*(?:\s+[A-Z][a-z0-9-]+){2,}\s+(?:In|The|This)\b))"
)
_FRESH_CANARY_HEADING_SENTENCE_GLUE_RE = re.compile(
    r"\b(?:[A-Za-z]{3,}|[A-Z][a-z]{3,})\s+[A-Z][a-z]{2,}\s+"
    r"(?:were|was|are|is|all|analyses|the|a|an|this|these)\b"
)
_FRESH_CANARY_HEADING_TRANSITION_RE = re.compile(
    r"\b(?!(?:The|This|A|An)\b)(?:[A-Za-z]{3,}|[A-Z][a-z]{3,})\s+"
    r"[A-Z][A-Za-z0-9-]{1,}\s+(?:were|was|are|is|all|analyses|animal|"
    r"cells|ligand|model|system|the|a|an|this|these|A)\b"
)
_FRESH_CANARY_VERB_ENTITY_RE = re.compile(
    r"(?i)^(?:applying|assessing|considering|describing|determining|"
    r"examining|identifying|measuring|reporting|studying|using)\b"
)
_FRESH_CANARY_RELATION_RE = re.compile(
    r"(?i)\b(?:is|are|was|were|has|have|had|received|signed|acquired|served|"
    r"incorporated|located|treated|measured|identified|formed|issued|held|"
    r"reported|increased|decreased|showed|indicated|caused|contains|asked|"
    r"sent|filed|requires|provides|includes|occurred|observed|used|defined|"
    r"determined|recorded|owned|entered|obtained|compared|analyzed|evaluated|"
    r"found|demonstrated|consists|remains|became|made|conducted)\b"
)


def _historical_canary_sources(
    root: Path, *, exclude_directory: Path | None = None,
) -> set[tuple[str, str]]:
    """Collect prior canary source identities only for fresh-fixture exclusion."""

    seen: set[tuple[str, str]] = set()
    patterns = (
        "artifacts/v*/development/**/canary_inputs.jsonl",
        "artifacts/v*/development/**/canary_results.jsonl",
        "artifacts/v24/development/**/reference_facts.jsonl",
    )
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if exclude_directory is not None and path.resolve().is_relative_to(exclude_directory.resolve()):
                continue
            try:
                rows = read_jsonl(path)
            except (OSError, ValueError, TypeError):
                continue
            def visit(value: object, inherited_dataset: str = "") -> None:
                if isinstance(value, Mapping):
                    dataset = str(value.get("dataset") or inherited_dataset)
                    source_key = value.get("source_key") or value.get("source_id")
                    if dataset and isinstance(source_key, str) and source_key:
                        seen.add((dataset, source_key))
                    for nested in value.values():
                        if isinstance(nested, (Mapping, list)):
                            visit(nested, dataset)
                elif isinstance(value, list):
                    for nested in value:
                        visit(nested, inherited_dataset)
            visit(rows)
    return seen




def _fresh_fact_preflight(
    fact: Mapping[str, object], source: Mapping[str, object]
) -> tuple[bool, list[str]]:
    """复用构造阶段的输入质量检查，并校验原文和实体 span。"""

    source_text = str(source.get("full_text") or "")
    claim = str(fact.get("true_claim") or "").strip()
    original = str(fact.get("original_entity") or "").strip()
    reasons = list(_query_input_quality_reasons(fact))
    if not claim or not original:
        reasons.append("v24_canary_fact_missing_claim_or_entity")
        return False, sorted(set(reasons))
    proposition_span = fact.get("proposition_span")
    original_span = fact.get("original_span")
    if (
        not isinstance(proposition_span, (list, tuple))
        or len(proposition_span) != 2
        or not isinstance(original_span, (list, tuple))
        or len(original_span) != 2
    ):
        reasons.append("v24_canary_fact_span_schema")
        return False, sorted(set(reasons))
    try:
        proposition_start, proposition_end = int(proposition_span[0]), int(proposition_span[1])
        original_start, original_end = int(original_span[0]), int(original_span[1])
    except (TypeError, ValueError):
        reasons.append("v24_canary_fact_span_schema")
        return False, sorted(set(reasons))
    if (
        proposition_start < 0
        or proposition_end <= proposition_start
        or source_text[proposition_start:proposition_end] != claim
    ):
        reasons.append("v24_canary_fact_claim_not_source_grounded")
    if (
        original_start < proposition_start
        or original_end <= original_start
        or source_text[original_start:original_end] != original
        or not (proposition_start <= original_start < original_end <= proposition_end)
    ):
        reasons.append("v24_canary_fact_original_span_invalid")
    if reasons:
        return False, sorted(set(reasons))
    return True, []


def _fresh_canary_fact_selection_score(fact: Mapping[str, object]) -> int:
    """Rank already-valid facts for a development-only canary fixture.

    This is a fixture suitability preference, not a v24 scientific gate.  It
    keeps obvious tokenizer/entity-extractor artifacts out of the Luna review
    set while leaving formal fact enumeration and screening unchanged.
    """

    claim = str(fact.get("true_claim") or "").strip()
    entity = str(fact.get("original_entity") or "").strip()
    normalized_entity = " ".join(entity.casefold().split())
    words = re.findall(r"[A-Za-z]+", claim)
    score = 0
    if normalized_entity in _FRESH_CANARY_LOW_INFORMATION_ENTITIES:
        score -= 1000
    if len(entity) <= 2:
        score -= 180
    if not re.search(r"[A-Za-z]", entity):
        score -= 500
    if re.fullmatch(r"[0-9$%.,:/() -]+", entity):
        score -= 500
    if _FRESH_CANARY_HEADING_PREFIX_RE.search(claim):
        score -= 300
    if _FRESH_CANARY_METADATA_PREFIX_RE.search(claim):
        score -= 240
    if _FRESH_CANARY_TABLE_FRAGMENT_RE.search(claim):
        score -= 220
    if _FRESH_CANARY_TRUNCATED_TAIL_RE.search(claim):
        score -= 220
    if _FRESH_CANARY_TITLE_GLUE_RE.search(claim):
        score -= 300
    if _FRESH_CANARY_HEADING_SENTENCE_GLUE_RE.search(claim):
        score -= 300
    if _FRESH_CANARY_HEADING_TRANSITION_RE.search(claim):
        score -= 300
    if _FRESH_CANARY_VERB_ENTITY_RE.search(entity):
        score -= 260
    if claim and not claim[0].isupper():
        score -= 280
    if entity[:1].islower():
        score -= 100
    if entity.casefold().endswith((
        " if",
        " and",
        " or",
        " of",
        " the",
        " a",
        " an",
        " in",
        " at",
        " on",
        " for",
    )) or normalized_entity in {"a", "an", "the", "let", "there", "within"}:
        score -= 180
    if entity.endswith(("'s", "’s")):
        score -= 80
    if len(words) < 5:
        score -= 80
    elif len(words) < 8:
        score -= 20
    if normalized_entity.split()[:1] and normalized_entity.split()[0] in _FRESH_CANARY_CONNECTOR_WORDS:
        score -= 120
    if len(entity) >= 4:
        score += min(len(entity), 30)
    if len(entity.split()) >= 2:
        score += 30
    if entity[:1].isupper():
        score += 10
    if claim.endswith((".", "?", "!")):
        score += 10
    if _FRESH_CANARY_RELATION_RE.search(claim):
        score += 25
    else:
        score -= 220
    if any(marker in claim for marker in ("�", "��")):
        score -= 15
    return score


def _fresh_canary_fact_is_suitable(fact: Mapping[str, object]) -> bool:
    """Return whether a fact is suitable for the new development fixture."""

    return _fresh_canary_fact_selection_score(fact) >= 0


def _fresh_canary_input_from_fact(
    fact: Mapping[str, object], *, dataset: str, canary_pair_index: int
) -> dict[str, object]:
    """Project one enumerated fact to the minimal fresh canary input schema."""

    return {
        "kind": "v24_query_quality_canary_input",
        "dataset": dataset,
        "canary_pair_index": canary_pair_index,
        "source_key": str(fact.get("source_key") or ""),
        "pair_id": str(fact.get("upstream_pair_id") or ""),
        "true_claim": str(fact.get("true_claim") or ""),
        "original_entity": str(fact.get("original_entity") or ""),
        "original_span": list(fact.get("original_span") or []),
        "proposition_span": list(fact.get("proposition_span") or []),
        "fact_order": int(fact.get("fact_order", 0) or 0),
        "source_hash": str(fact.get("source_hash") or ""),
        "normalized_text_hash": str(fact.get("normalized_text_hash") or ""),
    }


def _load_canary_candidate_pools(
    root: Path, config: Mapping[str, object], paths: Sequence[str | Path],
) -> dict[tuple[str, str], CandidateFactPoolReader]:
    """仅 canary 允许同数据集的互不重叠开发补充池，保留各自 hash。"""
    if not paths:
        raise ValueError("v24_candidate_pool_required")
    pools: dict[tuple[str, str], CandidateFactPoolReader] = {}
    seen_sources: dict[str, set[str]] = {}
    for path in paths:
        reader = next(iter(load_candidate_fact_pools(root, config, [path]).values()))
        key = (reader.dataset, reader.manifest["pool_sha256"])
        if key in pools:
            raise ValueError("v24_canary_duplicate_candidate_pool")
        previous = [pool for pool in pools.values() if pool.dataset == reader.dataset]
        if previous and any(pool.manifest["scope"] != "development_subset" for pool in [*previous, reader]):
            raise ValueError("v24_canary_supplement_requires_development_pool")
        seen = seen_sources.setdefault(reader.dataset, set())
        if seen.intersection(reader.offsets):
            raise ValueError("v24_canary_candidate_pool_source_overlap")
        seen.update(reader.offsets)
        pools[key] = reader
    return pools


def prepare_fresh_canary(
    root: Path,
    *,
    per_dataset: int = 10,
    output_dir: str | Path = FRESH_CANARY_OUTPUT_DIR,
    candidate_pools: Sequence[str | Path] = (),
    allow_legacy_facts: bool = False,
) -> dict[str, object]:
    """Build a fresh 30-row canary fixture and run only offline preflight."""

    if per_dataset <= 0:
        raise ValueError("v24_fresh_canary_per_dataset_invalid")
    config = load_v24_config(root)
    pools = {} if allow_legacy_facts else _load_canary_candidate_pools(root, config, candidate_pools)
    if not allow_legacy_facts and {key[0] for key in pools} != set(DATASET_ORDER):
        raise ValueError("v24_canary_requires_three_candidate_pools")
    zero_policy = config.get("development", {}).get(
        "canary_zero_candidate_policy", "skip_and_replace_in_frozen_order",
    )
    if zero_policy != "skip_and_replace_in_frozen_order":
        raise ValueError("v24_canary_zero_candidate_policy_invalid")
    output = Path(output_dir)
    if not output.is_absolute():
        output = root / output
    summary_path = output / "preflight_summary.json"
    if summary_path.exists():
        raise RuntimeError("v24_fresh_canary_output_exists")

    historical = _historical_canary_sources(root)
    inputs: list[dict[str, object]] = []
    preflight_rows: list[dict[str, object]] = []
    rejection_counts: dict[str, int] = {}
    screened_source_count = 0
    candidate_fact_count = 0
    passed_fact_count = 0
    dataset_counts: dict[str, dict[str, int]] = {}
    shortfalls: dict[str, int] = {}

    for dataset in DATASET_ORDER:
        selected = 0
        dataset_screened = 0
        dataset_facts = 0
        dataset_zero_candidates = 0
        dataset_replacements = 0
        source_readers = {
            key: pool for pool in pools.values() if pool.dataset == dataset for key in pool.offsets
        }
        for source in iter_frozen_source_pool(root, dataset):
            reader = source_readers.get(str(source["source_key"]))
            if not allow_legacy_facts and reader is None:
                continue
            dataset_screened += 1
            screened_source_count += 1
            source_key = str(source.get("source_key") or "")
            if (dataset, source_key) in historical:
                if not allow_legacy_facts:
                    raise ValueError("v24_canary_pool_source_not_fresh")
                continue
            facts = list(enumerate_candidate_facts(source) if allow_legacy_facts else reader.facts_for_source(source))
            dataset_facts += len(facts)
            candidate_fact_count += len(facts)
            if not facts and not allow_legacy_facts:
                # 只跳过已完成且校验通过的零候选记录，读取失败不转换成零候选。
                dataset_zero_candidates += 1
                preflight_rows.append({
                    **_source_identity(source),
                    "document_id": source.get("document_id"),
                    "status": "skipped_zero_candidates",
                    "candidate_fact_count": 0,
                    "candidate_pool_sha256": reader.manifest["pool_sha256"],
                    "rejection_reasons": ["zero_candidate_source"],
                })
                continue
            passed_facts: list[dict[str, object]] = []
            for fact in facts:
                ok, reasons = _fresh_fact_preflight(fact, source)
                if not ok:
                    for reason in reasons:
                        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                    continue
                passed_fact_count += 1
                passed_facts.append(dict(fact))
            suitable_facts = [
                fact for fact in passed_facts if _fresh_canary_fact_is_suitable(fact)
            ] if allow_legacy_facts else [fact for fact in passed_facts if int(fact["fact_order"]) < get_max_candidate_facts_per_source(config)]
            if not suitable_facts:
                if not allow_legacy_facts:
                    raise ValueError("v24_canary_nonempty_source_failed_preflight")
                if passed_facts:
                    rejection_counts["fresh_fixture_no_suitable_fact"] = (
                        rejection_counts.get("fresh_fixture_no_suitable_fact", 0) + 1
                    )
                continue
            fact = max(
                suitable_facts,
                key=lambda item: (
                    _fresh_canary_fact_selection_score(item),
                    -int(item.get("fact_order", 0) or 0),
                    str(item.get("upstream_pair_id") or ""),
                ),
            ) if allow_legacy_facts else suitable_facts[0]
            row = _fresh_canary_input_from_fact(
                fact, dataset=dataset, canary_pair_index=len(inputs)
            )
            if not allow_legacy_facts:
                row["candidate_pool_sha256"] = reader.manifest["pool_sha256"]
            inputs.append(row)
            preflight_rows.append(
                {
                    **_source_identity(source),
                    "document_id": source.get("document_id"),
                    "canary_pair_index": row["canary_pair_index"],
                    "dataset": dataset,
                    "source_key": source_key,
                    "pair_id": row["pair_id"],
                    "status": "passed",
                    "selection_score": _fresh_canary_fact_selection_score(fact) if allow_legacy_facts else None,
                    "selection_mode": "development_fixture_preference" if allow_legacy_facts else "frozen_pool_first_fact_within_budget",
                    "rejection_reasons": [],
                    "replacement_source": not allow_legacy_facts and dataset_screened > per_dataset,
                }
            )
            dataset_replacements += int(not allow_legacy_facts and dataset_screened > per_dataset)
            selected += 1
            if selected >= per_dataset:
                break
        dataset_counts[dataset] = {
            "screened_source_count": dataset_screened,
            "candidate_fact_count": dataset_facts,
            "selected_input_count": selected,
            "zero_candidate_source_count": dataset_zero_candidates,
            "replacement_source_count": dataset_replacements,
        }
        if selected != per_dataset:
            shortfalls[dataset] = per_dataset - selected

    if not shortfalls and len(inputs) != per_dataset * 3:
        raise RuntimeError("v24_fresh_canary_input_count_invalid")
    if len({(str(row["dataset"]), str(row["source_key"])) for row in inputs}) != len(inputs):
        raise RuntimeError("v24_fresh_canary_source_overlap")

    bindings = source_pool_bindings(root)
    manifest = {
        "kind": "v24_fresh_query_quality_canary_manifest",
        "protocol_version": config["protocol_version"],
        "purpose": "development_only_membership_blind_input_preflight",
        "status": "insufficient_candidate_sources" if shortfalls else "passed",
        "input_count": len(inputs),
        "per_dataset": per_dataset,
        "datasets": list(DATASET_ORDER),
        "historical_source_exclusion_count": len(historical),
        "screened_source_count": screened_source_count,
        "candidate_fact_count": candidate_fact_count,
        "preflight_pass_count": passed_fact_count,
        "preflight_rejection_reason_distribution": dict(sorted(rejection_counts.items())),
        "dataset_counts": dataset_counts,
        "zero_candidate_source_policy": zero_policy,
        "zero_candidate_source_count": sum(row["zero_candidate_source_count"] for row in dataset_counts.values()),
        "source_shortfalls": shortfalls,
        "source_pool_bindings": bindings,
        "candidate_fact_pools": [pools[key].binding() for key in sorted(pools)],
        "max_candidate_facts_per_source": get_max_candidate_facts_per_source(config),
        "external_calls_performed": 0,
        "retriever_calls_performed": 0,
        "victim_calls_performed": 0,
        "membership_read": False,
        "input_sha256": sha256_obj(inputs),
    }
    manifest["manifest_sha256"] = sha256_obj(manifest)
    # 缺口时仅保存筛选证据，避免未完成 fixture 被当作已使用的 canary 输入。
    if not shortfalls:
        write_jsonl(inputs, output / "canary_inputs.jsonl")
    write_jsonl(preflight_rows, output / "preflight_results.jsonl")
    write_json(manifest, output / "fresh_canary_manifest.json")
    summary = {
        **manifest,
        "status": "insufficient_candidate_sources" if shortfalls else "passed",
        "inputs_path": _display_path(root, output / "canary_inputs.jsonl") if not shortfalls else None,
        "preflight_results_path": _display_path(root, output / "preflight_results.jsonl"),
        "manifest_path": _display_path(root, output / "fresh_canary_manifest.json"),
        "manifest_file_sha256": sha256_file(output / "fresh_canary_manifest.json"),
        "input_file_sha256": sha256_file(output / "canary_inputs.jsonl") if not shortfalls else None,
        "preflight_results_sha256": sha256_file(output / "preflight_results.jsonl"),
    }
    write_json(summary, summary_path)
    if shortfalls:
        details = ",".join(f"{dataset}:{per_dataset - count}/{per_dataset}" for dataset, count in shortfalls.items())
        raise RuntimeError(f"v24_fresh_canary_source_shortfall:{details}")
    return summary


def _luna_ab_settings(config: Mapping[str, object]) -> dict[str, object]:
    settings = dict(config.get("development", {}).get("luna_only_ab", {}))
    if (settings.get("stage_a_max_facts") != 8
            or settings.get("screening_sources_per_dataset") != 10
            or type(settings.get("repeatability_runs")) is not int
            or settings["repeatability_runs"] not in (1, 2)
            or settings.get("promotion_thresholds") is not None):
        raise ValueError("v24_luna_ab_settings_invalid")
    return settings


def _luna_ab_development_path(root: Path, path: str | Path) -> Path:
    resolved = (root / path).resolve()
    if not resolved.is_relative_to((root / "artifacts/v24/development").resolve()):
        raise ValueError("v24_luna_ab_development_path_required")
    return resolved


def run_luna_only_smoke(
    root: Path, *, input_path: str | Path, output_dir: str | Path,
    preview_only: bool = False, resume: bool = False, show_progress: bool = True,
) -> dict[str, object]:
    """一次 source/一次请求的开发 smoke；复用响应保存，不启动模型核验或下游实验。"""
    config = load_v24_config(root)
    settings = config.get("development", {}).get("luna_only_direct", {})
    if settings != {"adapter": "luna_direct_paired_candidates", "max_candidates_per_source": 8,
                    "max_counters_per_slot": 3, "pairs_per_source": 3, "smoke_max_sources": 8}:
        raise ValueError("luna_direct_settings_invalid")
    input_file = _luna_ab_development_path(root, input_path)
    sources = list(read_jsonl(input_file))
    if not 1 <= len(sources) <= settings["smoke_max_sources"]:
        raise ValueError("luna_direct_smoke_source_budget")
    identities = [validate_luna_direct_source(source) for source in sources]
    if (len({row["source_key"] for row in identities}) != len(sources)
            or len({row["chunk_sha256"] for row in identities}) != len(sources)):
        raise ValueError("luna_direct_duplicate_source")
    profile = _canary_llm_identity(config)
    if profile["model"] != "gpt-5.6-luna":
        raise ValueError("luna_direct_model_must_be_luna")
    context = {
        "run_kind": "luna_only_direct_smoke", "protocol_version": config["protocol_version"],
        "source_count": len(sources), "sources": identities, "settings": settings, "candidate_unit": "factual_slot",
        "input_sha256": sha256_file(input_file), "config_sha256": sha256_obj(config), "llm_profile": profile,
        "code_sha256": sha256_obj({"runner": sha256_file(__file__),
                                    "screening": sha256_file(PROJECT_ROOT / "src/prepare/restoration_first_v24.py")}),
        "transport_override": {"max_retries": 0, "retry_until_success": False},
        "maximum_logical_api_calls": len(sources), "capacity_sample_allowed": False,
        "formal_switch_allowed": False, "retriever_calls_performed": 0, "victim_calls_performed": 0,
        "membership_read": False, "semantic_quality_review_completed": False,
    }
    fingerprint = sha256_obj(context)
    if preview_only:
        return {**context, "run_fingerprint": fingerprint, "status": "prepared_diagnostic"}
    output = _luna_ab_development_path(root, output_dir)
    result_path, summary_path = output / "smoke_results.jsonl", output / "smoke_summary.json"
    rows: list[dict[str, object]] = []
    active: dict[str, object] | None = None
    if resume:
        saved = read_json(summary_path)
        rows = list(read_jsonl(result_path))
        if (saved.get("run_fingerprint") != fingerprint
                or saved.get("content_sha256") != sha256_obj({k: v for k, v in saved.items() if k != "content_sha256"})
                or not saved["completed_sources"] <= len(rows) <= saved["completed_sources"] + 1
                or saved["results_sha256"] != sha256_obj(rows[:saved["completed_sources"]])):
            raise ValueError("luna_direct_checkpoint_drift")
        for i, row in enumerate(rows):
            if (i >= len(sources) or row.get("source_index") != i or row.get("source") != identities[i]
                    or row.get("result_sha256") != sha256_obj({k: v for k, v in row.items() if k != "result_sha256"})):
                raise ValueError("luna_direct_result_drift")
        active = saved.get("active_request") if len(rows) == saved["completed_sources"] else None
        if active is not None and active.get("source_index") != len(rows):
            raise ValueError("luna_direct_active_request_drift")
        if len(rows) == len(sources) and saved["status"] == "completed_diagnostic":
            return saved
    elif output.exists() and any(output.iterdir()):
        raise ValueError("luna_direct_output_exists_use_resume")
    else:
        write_jsonl_atomic([], result_path)

    def save(status: str) -> dict[str, object]:
        responses = [row["response"] for row in rows if row.get("response") is not None]
        rejections: Counter[str] = Counter()
        for row in rows:
            rejections.update((row.get("construction") or {}).get("rejection_reason_counts", {}))
        payload = {
            **context, "run_fingerprint": fingerprint, "status": status, "completed_sources": len(rows),
            "results_sha256": sha256_obj(rows), "active_request": active,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_count": sum(len(row.get("candidates") or []) for row in rows),
            "counter_candidate_count": sum((row.get("construction") or {}).get("counter_candidate_count", 0) for row in rows),
            "valid_slot_count": sum((row.get("construction") or {}).get("valid_slot_count", 0) for row in rows),
            "valid_pair_count": sum((row.get("construction") or {}).get("valid_pair_count", 0) for row in rows),
            "selected_pair_count": sum((row.get("construction") or {}).get("selected_pair_count", 0) for row in rows),
            "eligible_source_count": sum(bool((row.get("construction") or {}).get("eligible")) for row in rows),
            "execution_incomplete_count": sum(row.get("status") == "execution_incomplete" for row in rows),
            "invalid_output_count": sum(row.get("status") == "invalid_output" for row in rows),
            "rejection_reason_counts": dict(rejections),
            "provider": {
                "logical_api_calls": len(rows) + int(active is not None),
                "physical_attempts": sum(1 + int(r.get("transport_retry_count") or 0) for r in responses),
                "transport_retry_count": sum(int(r.get("transport_retry_count") or 0) for r in responses),
                "external_call_counts_complete": len(responses) == len(rows) and active is None,
                "provider_model_ids": sorted({r["provider_model_id"] for r in responses if r.get("provider_model_id")}),
                **{key: sum(r[key] for r in responses) if all(type(r.get(key)) in (int, float) for r in responses) else None
                   for key in ("input_tokens", "output_tokens", "latency_seconds")},
            },
        }
        payload["content_sha256"] = sha256_obj(payload)
        write_json(payload, summary_path)
        return payload

    provider: LunaDirectCandidateProvider | None = None
    save("running")
    for index in range(len(rows), len(sources)):
        resumed_request = active is not None
        if not resumed_request:
            active = {"source_index": index, "status": "started", "response": None}
            save("running")
        assert active is not None
        row = {"source_index": index, "source": identities[index], "status": "completed",
               "response": None, "candidates": None, "construction": None, "error": None}

        def observe(response: Mapping[str, object]) -> None:
            active.update(status="response_received", response=dict(response))
            # 落盘失败终止执行，不能变成候选质量拒绝。
            try:
                save("running")
            except Exception as exc:
                raise LunaABPersistenceError("luna_direct_response_save_failed") from exc

        try:
            if resumed_request and active.get("response") is None:
                row.update(status="execution_incomplete", error="response_unavailable_after_interruption")
            else:
                if provider is None:
                    provider = build_luna_candidate_provider(root, direct_pairs=True)
                    # 只限制本次 smoke 的传输尝试，不改变历史 profile 或 comparator。
                    provider.client.max_retries = 0
                    provider.client.retry_until_success = False
                provider.response_observer = observe
                if resumed_request:
                    candidates = provider.parse_response(active["response"])
                else:
                    candidates = provider.construct_paired_candidates(sources[index])
                if active["response"].get("provider_model_id") != "gpt-5.6-luna":
                    raise ValueError("luna_direct_returned_model_mismatch")
                row["candidates"] = candidates
                row["construction"] = select_luna_direct_pairs(sources[index], candidates)
        except LunaABPersistenceError:
            raise
        except Exception as exc:
            row.update(status="invalid_output" if active.get("response") is not None else "execution_incomplete",
                       error=str(exc) if isinstance(exc, ValueError) and str(exc).startswith("luna_direct_") else type(exc).__name__)
        row["response"] = active.get("response")
        row["result_sha256"] = sha256_obj(row)
        write_jsonl_atomic([*rows, row], result_path)
        rows.append(row)
        active = None
        save("running")
        if show_progress:
            print(f"Luna direct smoke: {index + 1}/{len(sources)} {row['status']} pairs={(row.get('construction') or {}).get('selected_pair_count', 0)}", flush=True)
    return save("completed_diagnostic")


def prepare_luna_only_ab(
    root: Path, *, output_dir: str | Path = LUNA_ONLY_AB_OUTPUT_DIR,
    per_dataset: int = 10, candidate_pools: Sequence[str | Path] = (),
) -> dict[str, object]:
    """先冻结 source 身份，再由同一输入构建 comparator；零候选不得换样。"""
    config = load_v24_config(root)
    settings = _luna_ab_settings(config)
    if candidate_pools or per_dataset != settings["screening_sources_per_dataset"]:
        raise ValueError("v24_luna_ab_select_sources_before_extraction")
    output = _luna_ab_development_path(root, output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("v24_luna_ab_output_exists")
    exclusions = [
        row for dataset in DATASET_ORDER
        for row in collect_development_identities(root, config, dataset)
    ]
    seen_keys = {(row["dataset"], row["source_key"]) for row in exclusions if row.get("source_key")}
    seen_hashes = {row[key] for row in exclusions for key in ("source_hash", "normalized_text_hash") if row.get(key)}
    selected = []
    for dataset in DATASET_ORDER:
        count = 0
        for source in iter_frozen_source_pool(root, dataset):
            identity = _source_identity(source)
            if ((dataset, identity["source_key"]) in seen_keys
                    or identity["source_hash"] in seen_hashes or identity["normalized_text_hash"] in seen_hashes):
                continue
            selected.append(identity)
            seen_keys.add((dataset, identity["source_key"]))
            seen_hashes.update((identity["source_hash"], identity["normalized_text_hash"]))
            count += 1
            if count == per_dataset:
                break
        if count != per_dataset:
            raise ValueError("v24_luna_ab_fresh_source_shortfall:" + dataset)
    manifest = {
        "kind": "v24_luna_only_ab_inputs", "protocol_version": config["protocol_version"],
        "sources": selected, "source_count": len(selected), "per_dataset": per_dataset,
        "selection": "frozen_source_order_before_extraction_keep_zero_candidates",
        "source_pool_bindings": source_pool_bindings(root),
        "development_exclusions": exclusions, "settings": settings,
        "selection_seed": config["selection_seed"], "source_order_sha256": sha256_obj(selected),
        "external_calls_performed": 0, "membership_read": False,
    }
    manifest["content_sha256"] = sha256_obj(manifest)
    path = output / "luna_only_ab_inputs.json"
    write_json(manifest, path)
    return {"status": "prepared_diagnostic", "source_count": len(selected),
            "inputs_path": _display_path(root, path), "input_file_sha256": sha256_file(path),
            "external_calls_performed": 0}


def _load_luna_ab_inputs(root: Path, input_path: str | Path) -> tuple[dict, dict]:
    path = _luna_ab_development_path(root, input_path)
    manifest = read_json(path)
    if (manifest.get("kind") != "v24_luna_only_ab_inputs"
            or manifest.get("content_sha256") != sha256_obj({k: v for k, v in manifest.items() if k != "content_sha256"})):
        raise ValueError("v24_luna_ab_input_hash")
    rows = manifest.get("sources", [])
    _reject_forbidden(rows)
    if (len(rows) != 30 or manifest.get("source_count") != 30
            or manifest.get("per_dataset") != 10
            or [row.get("dataset") for row in rows] != [ds for ds in DATASET_ORDER for _ in range(10)]
            or manifest.get("source_order_sha256") != sha256_obj(rows)):
        raise ValueError("v24_luna_ab_input_order_or_count")
    for key in ("source_hash", "normalized_text_hash"):
        if len({row[key] for row in rows}) != len(rows):
            raise ValueError("v24_luna_ab_text_overlap")
    keys = {(row["dataset"], row["source_key"]) for row in rows}
    if len(keys) != len(rows):
        raise ValueError("v24_luna_ab_source_overlap")
    sources = _source_lookup(root, set(DATASET_ORDER), keys)
    excluded = manifest.get("development_exclusions", [])
    for row in rows:
        if _source_identity(sources[(row["dataset"], row["source_key"])]) != row:
            raise ValueError("v24_luna_ab_source_identity_drift")
        if any((item.get("dataset"), item.get("source_key")) == (row["dataset"], row["source_key"])
               or item.get("source_hash") == row["source_hash"]
               or item.get("normalized_text_hash") == row["normalized_text_hash"] for item in excluded):
            raise ValueError("v24_luna_ab_historical_overlap")
    if source_pool_bindings(root) != manifest["source_pool_bindings"]:
        raise ValueError("v24_luna_ab_source_pool_drift")
    return manifest, sources


def _luna_ab_jobs(manifest: Mapping[str, object]) -> list[dict[str, object]]:
    jobs = []
    for repeat in range(manifest["settings"]["repeatability_runs"]):
        for index, source in enumerate(manifest["sources"]):
            # 两臂 source 顺序完全相同，先执行哪一臂按 source 交替。
            arms = ("GLiNER2+Luna", "Luna-only") if (index + repeat) % 2 == 0 else ("Luna-only", "GLiNER2+Luna")
            for arm in arms:
                jobs.append({**source, "arm": arm, "repeat": repeat, "input_index": index})
    return jobs


def _luna_ab_overlap(left: Mapping[str, object], right: Mapping[str, object]) -> dict[str, object]:
    def candidates(row):
        stage_a = row.get("stage_a") or {}
        return stage_a.get("grounded_facts", [item["raw_fact"] for item in row.get("fact_evidence", [])])

    def overlap(a, b):
        return len(a & b) / len(a | b) if a or b else None

    a, b = candidates(left), candidates(right)
    return {
        "candidate_exact_overlap": overlap(
            {(x["true_claim"], x["original_entity"], x.get("fixed_canonical_template")) for x in a},
            {(x["true_claim"], x["original_entity"], x.get("fixed_canonical_template")) for x in b}),
        "normalized_entity_overlap": overlap(
            {" ".join(x["original_entity"].casefold().split()) for x in a},
            {" ".join(x["original_entity"].casefold().split()) for x in b}),
        "claim_overlap": overlap({x["true_claim"] for x in a}, {x["true_claim"] for x in b}),
    }


def _luna_ab_usage(drafts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    responses = [row["response"] for row in drafts if "response" in row]
    result = {
        "logical_api_calls": len(drafts),
        "physical_attempts": sum(1 + int(row.get("transport_retry_count") or 0) for row in responses),
        "transport_retry_count": sum(int(row.get("transport_retry_count") or 0) for row in responses),
        "external_call_counts_complete": len(responses) == len(drafts),
        "provider_model_ids": sorted({str(row["provider_model_id"]) for row in responses if row.get("provider_model_id")}),
    }
    for field in ("input_tokens", "output_tokens", "latency_seconds"):
        values = [row.get(field) for row in responses]
        result[field] = sum(values) if all(type(value) in (int, float) for value in values) else None
    return result


def _luna_ab_summary(rows: Sequence[Mapping[str, object]], *, manifest: Mapping[str, object]) -> dict[str, object]:
    repeats = manifest["settings"]["repeatability_runs"]
    metrics = ("source_has_ge_1_usable_fact", "source_has_ge_3_usable_facts", "source_has_ge_3_eligible_pairs")
    indexed = {(r["arm"], r["repeat"], r["dataset"], r["source_key"]): r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError("v24_luna_ab_duplicate_result")
    by_arm = {}
    for arm in ("GLiNER2+Luna", "Luna-only"):
        distributions = []
        stability = []
        for repeat in range(repeats):
            by_dataset = {}
            for dataset in DATASET_ORDER:
                subset = [r for r in rows if r["arm"] == arm and r["repeat"] == repeat and r["dataset"] == dataset]
                complete = [r for r in subset if not r["execution_incomplete"]]
                facts = [r["screen_result"] for r in complete if isinstance(r.get("screen_result"), Mapping)]
                stage_a_reasons, stage_b_reasons = Counter(), Counter()
                for fact in facts:
                    stage_a_reasons.update((fact.get("stage_a") or {}).get("rejection_reason_counts", {}))
                    for evidence in fact.get("fact_evidence", []):
                        stage_a_reasons.update(evidence.get("rejection_reasons", []))
                    for evidence in fact.get("candidate_evidence", []):
                        stage_b_reasons.update(evidence.get("rejection_reasons", []))
                by_dataset[dataset] = {
                    "expected_source_count": 10, "completed_source_count": len(complete),
                    "missing_source_count": 10 - len(complete),
                    "usable_fact_counts": [int(f.get("usable_fact_count") or 0) for f in facts],
                    "eligible_pair_counts": [int(f.get("eligible_pair_count") or 0) for f in facts],
                    "stage_a_failure_reasons": dict(stage_a_reasons),
                    "stage_b_failure_reasons": dict(stage_b_reasons),
                    **{metric: {"count": sum(bool(f.get(metric)) for f in facts),
                                "rate": sum(bool(f.get(metric)) for f in facts) / 10 if len(complete) == 10 and len(facts) == 10 else None}
                       for metric in metrics},
                }
            distributions.append({"repeat": repeat, "by_dataset": by_dataset,
                                  "macro": {metric: sum(by_dataset[ds][metric]["rate"] for ds in DATASET_ORDER) / 3
                                            if all(by_dataset[ds][metric]["rate"] is not None for ds in DATASET_ORDER) else None
                                            for metric in metrics}})
        if repeats >= 2:
            for source in manifest["sources"]:
                current = [indexed.get((arm, rep, source["dataset"], source["source_key"])) for rep in range(repeats)]
                complete = all(row is not None and not row["execution_incomplete"] for row in current)
                stability.append({**source, "complete": complete,
                                  **{metric: {"stable": len({bool(r["screen_result"].get(metric)) for r in current}) == 1,
                                              "usable_in_all_runs": all(bool(r["screen_result"].get(metric)) for r in current)}
                                     if complete else None for metric in metrics},
                                  "overlap_diagnostic": _luna_ab_overlap(current[0]["screen_result"], current[1]["screen_result"])
                                  if complete else None})
        by_arm[arm] = {"per_repeat": distributions, "source_repeatability": stability,
                       "stability_rates": {metric: sum(row[metric]["stable"] for row in stability) / 30
                                           if len(stability) == 30 and all(row["complete"] for row in stability) else None
                                           for metric in metrics}}
    paired = []
    for repeat in range(repeats):
        for source in manifest["sources"]:
            a = indexed.get(("GLiNER2+Luna", repeat, source["dataset"], source["source_key"]))
            b = indexed.get(("Luna-only", repeat, source["dataset"], source["source_key"]))
            complete = a is not None and b is not None and not (a["execution_incomplete"] or b["execution_incomplete"])
            paired.append({**source, "repeat": repeat, "complete": complete,
                           "luna_minus_comparator": {metric: int(bool(b["screen_result"].get(metric))) - int(bool(a["screen_result"].get(metric)))
                                                    for metric in metrics} if complete else None})
    all_drafts = [draft for row in rows for draft in row.get("generation_drafts", [])]
    return {
        "status": "completed_diagnostic" if len(rows) == len(_luna_ab_jobs(manifest)) else "partial_diagnostic",
        "source_count": 30, "condition_count": len(rows), "arms": by_arm, "paired_sources": paired,
        "execution_incomplete_count": sum(row["execution_incomplete"] for row in rows),
        "provider": _luna_ab_usage(all_drafts), "candidate_overlap_is_hard_gate": False,
        "promotion_thresholds": None, "formal_switch_allowed": False, "capacity_sample_allowed": False,
        "semantic_quality_review_completed": False, "human_review_performed": False,
        "pairs_per_source": 3, "queries_per_source": 6,
        "retriever_calls_performed": 0, "victim_calls_performed": 0, "membership_read": False,
    }


class LunaABPersistenceError(RuntimeError):
    pass


def run_luna_only_ab(
    root: Path, *, input_path: str | Path, candidate_pools: Sequence[str | Path],
    output_dir: str | Path, resume: bool = False, preview_only: bool = False,
    repeatability_runs: int | None = None, show_progress: bool = True,
) -> dict[str, object]:
    """逐 source/arm 保存阶段响应；恢复只复用已保存请求，不重抽失败响应。"""
    config = load_v24_config(root)
    settings = _luna_ab_settings(config)
    manifest, sources = _load_luna_ab_inputs(root, input_path)
    if manifest["settings"] != settings or repeatability_runs not in (None, settings["repeatability_runs"]):
        raise ValueError("v24_luna_ab_settings_drift")
    pools = _load_canary_candidate_pools(root, config, candidate_pools)
    if any(reader.manifest["scope"] != "development_subset" for reader in pools.values()):
        raise ValueError("v24_luna_ab_development_pool_required")
    frozen_facts = {}
    for source in manifest["sources"]:
        key = (source["dataset"], source["source_key"])
        matches = [reader for reader in pools.values() if reader.dataset == key[0] and key[1] in reader.offsets]
        if len(matches) != 1:
            raise ValueError("v24_luna_ab_comparator_source_missing_or_duplicate")
        frozen_facts[key] = matches[0].facts_for_source(sources[key])[:8]
    profile = _canary_llm_identity(config)
    if profile["model"] != "gpt-5.6-luna":
        raise ValueError("v24_luna_ab_model_must_be_luna")
    jobs = _luna_ab_jobs(manifest)
    context = {
        "run_kind": "luna_only_fresh30_ab", "inputs": manifest, "config_sha256": sha256_obj(config),
        "input_file_sha256": sha256_file(root / input_path), "llm_profile": profile,
        "candidate_pools": [pools[key].binding() for key in sorted(pools)],
        "code_sha256": sha256_obj({"runner": sha256_file(__file__),
                                  "screening": sha256_file(Path(__file__).resolve().parents[1] / "src/prepare/restoration_first_v24.py")}),
        "facts_sha256": sha256_obj(list(frozen_facts.values())), "condition_count": len(jobs),
        "maximum_logical_api_calls": 30 * settings["repeatability_runs"] * (8 * 6 + 1 + 8 * 5),
        "promotion_thresholds": None, "capacity_sample_allowed": False,
    }
    fingerprint = sha256_obj(context)
    if preview_only:
        return {**context, "run_fingerprint": fingerprint, "status": "prepared_diagnostic", "external_calls_performed": 0}
    output = _luna_ab_development_path(root, output_dir)
    result_path, summary_path = output / "luna_only_ab_results.jsonl", output / "luna_only_ab_summary.json"
    if not resume and output.exists() and any(output.iterdir()):
        raise ValueError("v24_luna_ab_output_exists")
    rows, progress = [], {}
    if resume:
        progress = read_json(summary_path)
        rows = list(read_jsonl(result_path))
        if (progress.get("run_fingerprint") != fingerprint
                or progress.get("content_sha256") != sha256_obj({k: v for k, v in progress.items() if k != "content_sha256"})
                or not progress["completed_conditions"] <= len(rows) <= progress["completed_conditions"] + 1
                or progress.get("results_sha256") != sha256_obj(rows[:progress["completed_conditions"]])):
            raise ValueError("v24_luna_ab_checkpoint_drift")
        for index, row in enumerate(rows):
            if (index >= len(jobs) or row.get("job") != jobs[index] or row.get("run_fingerprint") != fingerprint
                    or row.get("result_content_sha256") != sha256_obj({k: v for k, v in row.items() if k != "result_content_sha256"})):
                raise ValueError("v24_luna_ab_result_drift")
        active = progress.get("active_index")
        if active is not None and (type(active) is not int or active not in {len(rows), len(rows) - 1}):
            raise ValueError("v24_luna_ab_active_job_drift")
        if len(rows) == len(jobs) and progress.get("status") == "completed_diagnostic":
            return progress
    else:
        write_jsonl_atomic([], result_path)
    active_index = progress.get("active_index")
    drafts = progress.get("active_generation", [])
    semantic_identity = progress.get("semantic_similarity")

    def save(status):
        payload = {**context, "run_fingerprint": fingerprint, "status": status,
                   "completed_conditions": len(rows), "results_sha256": sha256_obj(rows),
                   "active_index": active_index, "active_generation": drafts, "semantic_similarity": semantic_identity}
        if status == "completed_diagnostic":
            payload["report"] = _luna_ab_summary(rows, manifest=manifest)
        payload["content_sha256"] = sha256_obj(payload)
        try:
            write_json(payload, summary_path)
        except Exception as exc:
            raise LunaABPersistenceError("v24_luna_ab_save_failed") from exc
        return payload

    if len(rows) == len(jobs):
        active_index, drafts = None, []
        return save("completed_diagnostic")
    save("running")
    scorer = build_v24_semantic_similarity(root)
    try:
        if semantic_identity is not None and semantic_identity != scorer.identity():
            raise ValueError("v24_luna_ab_semantic_identity_drift")
        semantic_identity = scorer.identity()
        provider = build_luna_candidate_provider(root)
        if provider.profile.get("model") != profile["model"]:
            raise LunaABPersistenceError("v24_luna_ab_runtime_model_drift")

        class RecordedProvider:
            def __init__(self):
                self.cursor = 0

            def request(self, method, *args):
                position = self.cursor
                self.cursor += 1
                identity = sha256_obj({"method": method, "input": args})
                if position < len(drafts):
                    stage = drafts[position]
                    if stage["request_sha256"] != identity or stage["method"] != method:
                        raise LunaABPersistenceError("v24_luna_ab_request_drift")
                    if stage["status"] == "completed":
                        return stage["candidates"]
                    if stage["status"] != "response_received":
                        raise ValueError("v24_luna_ab_saved_request_unavailable")
                else:
                    stage = {"method": method, "request_sha256": identity, "status": "started", "candidates": []}
                    drafts.append(stage)
                    save("running")

                def observe(response):
                    stage.update(status="response_received", response=dict(response))
                    save("running")

                previous_observer = provider.response_observer
                provider.response_observer = observe
                try:
                    if "response" in stage:
                        candidates = list(provider.parse_response(
                            stage["response"], max_candidates=8 if method == "construct_factual_slots" else 3,
                            allow_empty=method == "construct_factual_slots"))
                    else:
                        candidates = list(getattr(provider, method)(*args))
                    observed = stage.get("response", {}).get("provider_model_id")
                    if observed and observed != "gpt-5.6-luna":
                        raise LunaABPersistenceError("v24_luna_ab_observed_model_drift")
                    stage.update(status="completed", candidates=candidates)
                    save("running")
                    return candidates
                except LunaABPersistenceError:
                    raise
                except Exception as exc:
                    stage.update(status="response_invalid" if "response" in stage else "request_failed",
                                 error_type=type(exc).__name__)
                    save("running")
                    raise
                finally:
                    provider.response_observer = previous_observer

            def __call__(self, fact):
                return self.request("__call__", fact)

            def __getattr__(self, method):
                if method not in ("construct_factual_slots", "construct_fact", "verify_fact", "verify_queries", "correct"):
                    raise AttributeError(method)
                return lambda *args: self.request(method, *args)

        for index in range(len(rows), len(jobs)):
            job = jobs[index]
            if active_index != index:
                drafts = []
            active_index = index
            save("running")
            key = (job["dataset"], job["source_key"])
            try:
                screened = screen_source(
                    sources[key], candidate_provider=RecordedProvider(),
                    facts=frozen_facts[key] if job["arm"] == "GLiNER2+Luna" else None,
                    minimum_pairs=3, allow_surface_fallback=False, similarity_fn=scorer,
                    semantic_correction_retries=1, include_candidate_evidence=True, include_full_candidate_evidence=True,
                    max_candidate_facts_per_source=8, two_stage=True, luna_only=job["arm"] == "Luna-only",
                    exhaustive_diagnostic=True)
                error = None
            except LunaABPersistenceError:
                raise
            except Exception as exc:
                screened, error = None, type(exc).__name__
            result = {**job, "job": job, "run_fingerprint": fingerprint, "screen_result": screened,
                      "execution_incomplete": error is not None, "execution_error": error,
                      "generation_drafts": drafts, "provider_usage": _luna_ab_usage(drafts)}
            result["result_content_sha256"] = sha256_obj(result)
            write_jsonl_atomic([*rows, result], result_path)
            rows.append(result)
            active_index, drafts = None, []
            save("running")
            if show_progress:
                print(f"Luna A/B: {index + 1}/{len(jobs)} {job['arm']} {job['dataset']} execution_incomplete={error is not None}", flush=True)
    except BaseException:
        try:
            saved_rows = list(read_jsonl(result_path))
            if len(saved_rows) == len(rows) + 1 and saved_rows[-1].get("job") == jobs[len(rows)]:
                rows = saved_rows
                active_index, drafts = None, []
            save("interrupted")
        except (OSError, ValueError, LunaABPersistenceError):
            pass
        raise
    finally:
        scorer.close()
    return save("completed_diagnostic")


def summarize_luna_only_ab(root: Path, result_path: str | Path) -> dict[str, object]:
    path = _luna_ab_development_path(root, result_path)
    summary = read_json(path.parent / "luna_only_ab_summary.json")
    rows = list(read_jsonl(path))
    if (summary.get("content_sha256") != sha256_obj({k: v for k, v in summary.items() if k != "content_sha256"})
            or summary.get("results_sha256") != sha256_obj(rows)):
        raise ValueError("v24_luna_ab_summary_drift")
    jobs = _luna_ab_jobs(summary["inputs"])
    for index, row in enumerate(rows):
        if (index >= len(jobs) or row["job"] != jobs[index]
                or row["run_fingerprint"] != summary["run_fingerprint"]
                or row["result_content_sha256"] != sha256_obj({k: v for k, v in row.items() if k != "result_content_sha256"})):
            raise ValueError("v24_luna_ab_result_drift")
    return _luna_ab_summary(rows, manifest=summary["inputs"])


def _membership_blind_fact(row: Mapping[str, object], source: Mapping[str, object]) -> dict[str, object]:
    """Project an old canary row onto the minimal v24 fact contract."""

    forbidden = {
        "effective_type",
        "counterfactual_entity",
        "counterfactual_claim",
        "membership",
        "membership_label",
        "group",
        "retriever_output",
        "retrieval_score",
        "victim_response",
        "attack_score",
        "attack_auc",
        "auc",
    }
    if forbidden.intersection(row):
        # These fields are intentionally ignored rather than copied.  The
        # source canary is legacy-shaped, but the v24 construction input is not.
        pass
    source_text = str(source.get("full_text") or "")
    claim = str(row.get("true_claim") or "").strip()
    original = str(row.get("original_entity") or "").strip()
    if not claim or not original or source_text.find(claim) < 0:
        raise ValueError("v24_canary_fact_not_source_grounded")
    claim_offset = source_text.find(claim)
    provided_span = row.get("original_span")
    local_offset: int | None = None
    if isinstance(provided_span, (list, tuple)) and len(provided_span) == 2:
        try:
            span_start, span_end = int(provided_span[0]), int(provided_span[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("v24_canary_original_span_invalid") from exc
        if (
            span_start < claim_offset
            or span_end <= span_start
            or span_end > claim_offset + len(claim)
            or source_text[span_start:span_end] != original
        ):
            raise ValueError("v24_canary_original_span_invalid")
        local_offset = span_start - claim_offset
    else:
        local_offset = claim.find(original)
    if local_offset < 0 or claim[local_offset:local_offset + len(original)] != original:
        raise ValueError("v24_canary_original_not_in_true_claim")
    identity = {
        "dataset": str(source.get("dataset") or row.get("dataset") or ""),
        "source_key": str(source.get("source_key") or row.get("source_key") or ""),
        "source_order_rank": str(source.get("source_order_rank") or ""),
        "full_text": source_text,
    }
    from src.prepare.restoration_first_v24 import _source_identity, _mask_entity_mentions

    source_identity = _source_identity(identity)
    return {
        **source_identity,
        "upstream_pair_id": str(row.get("upstream_pair_id") or row.get("pair_id") or sha256_obj({
            "dataset": identity["dataset"],
            "source_key": identity["source_key"],
            "claim": claim,
            "original": original,
        })),
        "true_claim": claim,
        "original_entity": original,
        "original_span": [claim_offset + local_offset, claim_offset + local_offset + len(original)],
        "proposition_span": list(
            row.get("proposition_span") or [claim_offset, claim_offset + len(claim)]
        ),
        "slotted_true_claim": _mask_entity_mentions(claim, original),
        "fact_order": int(row.get("fact_order", row.get("canary_pair_index", 0)) or 0),
    }


def _load_canary_inputs(root: Path, path: str | Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for row in read_jsonl(root / path):
        # Explicit projection makes legacy fields impossible to enter the Luna prompt.
        records.append({
            key: row[key]
            for key in (
                "source_key",
                "dataset",
                "true_claim",
                "original_entity",
                "original_span",
                "proposition_span",
                "pair_id",
                "canary_pair_index",
                "fact_order",
                "candidate_pool_sha256",
            )
            if key in row
        })
    return records


def _source_lookup(root: Path, datasets: set[str], source_keys: set[tuple[str, str]]) -> dict[tuple[str, str], dict[str, object]]:
    found: dict[tuple[str, str], dict[str, object]] = {}
    for dataset in sorted(datasets):
        for source in iter_frozen_source_pool(root, dataset):
            key = (dataset, str(source.get("source_key") or ""))
            if key in source_keys:
                found[key] = source
                if len(found) == len(source_keys):
                    return found
    missing = sorted(source_keys - set(found))
    if missing:
        raise RuntimeError(f"v24_canary_source_missing:{missing[:3]}")
    return found


def _canary_llm_identity(config: dict[str, object]) -> dict[str, object]:
    """只解析有效配置，不创建客户端；不保存 endpoint 或凭据。"""
    from src.llm.factory import load_llm_profiles, llm_profile_identity, resolve_effective_llm_profile

    profile = resolve_effective_llm_profile(
        load_llm_profiles(config), "sibling",
        profile_name=str(config.get("llm", {}).get("profile") or "luna_query_generator"),
    )
    identity = llm_profile_identity(profile)
    return {key: identity.get(key) for key in ("profile_name", "model", "model_version", "profile_hash")}


def _canary_provider_totals(
    previous: Mapping[str, object], current: Mapping[str, object],
) -> dict[str, object]:
    """合并已保存调用与当前进程统计，异常仅保留类型以免回显敏感响应。"""
    result: dict[str, object] = {
        key: current.get(key) or previous.get(key)
        for key in ("profile_name", "configured_model")
    }
    for key in ("logical_api_calls", "physical_attempts", "transport_retry_count"):
        result[key] = int(previous.get(key) or 0) + int(current.get(key) or 0)
    result["provider_model_ids"] = sorted({
        str(value) for stats in (previous, current) for value in stats.get("provider_model_ids") or []
    })
    result["failures"] = [
        str(value).split(":", 1)[0] if re.fullmatch(r"\w+", str(value).split(":", 1)[0]) else "provider_error"
        for stats in (previous, current) for value in stats.get("failures") or []
    ]
    return result


def _prepare_fact_ablation(
    root: Path, input_path: str | Path, config: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object] | None], dict, dict, dict]:
    """复用已见开发池，核对参考证据并展开固定的 A/B 条件。"""
    references = list(read_jsonl(root / input_path))
    _reject_forbidden(references)
    if not references or any(row.get("kind") != "v24_fact_ablation_reference" for row in references):
        raise ValueError("v24_ablation_reference_schema")
    allowed_strata = {"context_failure", "positive_control", "rejection_control"}
    if any(row.get("stratum") not in allowed_strata for row in references):
        raise ValueError("v24_ablation_stratum")
    if len({row.get("sample_id") for row in references}) != len(references) or any(
        not str(row.get("sample_id") or "").strip() for row in references
    ):
        raise ValueError("v24_ablation_sample_id")
    raw_inputs = [row["raw_fact"] for row in references]
    for key in ("source_key", "source_hash", "normalized_text_hash"):
        if len({row.get(key) for row in raw_inputs}) != len(raw_inputs) or any(not row.get(key) for row in raw_inputs):
            raise ValueError(f"v24_ablation_duplicate_or_missing_{key}")
    main = [row for row in references if row["stratum"] != "rejection_control"]
    if len(main) != 18 or any(
        sum(row["raw_fact"]["dataset"] == dataset and row["stratum"] == stratum for row in main) != count
        for dataset in DATASET_ORDER for stratum, count in (("context_failure", 4), ("positive_control", 2))
    ):
        raise ValueError("v24_ablation_requires_18_stratified_sources")
    paths = sorted({str(row["candidate_pool"]) for row in references})
    pools = _load_canary_candidate_pools(root, config, paths)
    if any(reader.manifest["scope"] != "development_subset" for reader in pools.values()):
        raise ValueError("v24_ablation_development_pool_required")
    sources = _source_lookup(root, {row["dataset"] for row in raw_inputs},
                             {(row["dataset"], row["source_key"]) for row in raw_inputs})
    inputs, facts, controls = [], [], []
    budget = get_max_candidate_facts_per_source(config)
    source_index = 0
    for record, row in zip(references, raw_inputs, strict=True):
        source = sources[(row["dataset"], row["source_key"])]
        reader = pools.get((row["dataset"], row.get("candidate_pool_sha256")))
        if reader is None:
            raise ValueError("v24_canary_candidate_pool_drift")
        matches = [fact for fact in reader.facts_for_source(source)[:budget]
                   if fact["upstream_pair_id"] == row.get("pair_id")]
        if len(matches) != 1 or any(matches[0].get(key) != row.get(key) for key in (
            "true_claim", "original_entity", "original_span", "proposition_span", "fact_order",
            "source_hash", "normalized_text_hash",
        )):
            raise ValueError("v24_canary_fact_not_in_candidate_pool")
        raw_fact = matches[0]
        reference = record["reference_fact"]
        completed_fact = reference_fact_view(raw_fact, reference, str(source["full_text"]))
        metadata = {key: record[key] for key in ("sample_id", "stratum", "reference_fact")}
        metadata["raw_fact"] = row
        if record["stratum"] == "rejection_control":
            if completed_fact is not None:
                raise ValueError("v24_ablation_rejection_control_requires_unusable")
            reasons = _query_input_quality_reasons(raw_fact)
            controls.append({**metadata, "automatic_rejection_reasons": reasons,
                             "automatically_rejected": bool(reasons), "external_calls_performed": 0})
            continue
        if record["stratum"] == "positive_control" and reference["status"] != "as_is":
            raise ValueError("v24_ablation_positive_control_must_be_unchanged")
        # 在相邻条件内配对，按 source 交替 A/B 顺序；每数据集各有三次 A 在先。
        conditions = ("A", "B") if source_index % 2 == 0 else ("B", "A")
        for condition in conditions:
            view = raw_fact if condition == "A" else completed_fact
            inputs.append({**row, **metadata, "condition": condition,
                           "canary_pair_index": len(inputs),
                           "generation_claim": view["true_claim"] if view else None})
            facts.append(view)
        source_index += 1
    return inputs, facts, sources, pools, {
        "run_kind": "fact_context_ablation", "diagnostic_only": True,
        "source_count": len(main), "condition_count": len(inputs),
        "reference_annotation_type": "assistant_reference",
        "independent_blind_review_performed": False, "human_review_performed": False,
        "maximum_logical_generation_calls": 2 * len(inputs),
        "reference_unusable_source_count": sum(row["reference_fact"]["status"] == "unusable" for row in main),
        "offline_rejection_controls": controls, "capacity_sample_allowed": False,
    }


def _load_canary_checkpoint(
    output: Path, *, run_fingerprint: str, inputs: list[dict[str, object]], diagnostic: bool = False,
    two_stage: bool = False,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """校验已保存前缀；只允许结果比汇总领先一条的原子写入窗口。"""
    summary_path, results_path = output / "canary_summary.json", output / "canary_results.jsonl"
    if not summary_path.is_file() or not results_path.is_file():
        raise RuntimeError("v24_canary_checkpoint_missing")
    try:
        summary = read_json(summary_path)
        raw_lines = results_path.read_bytes().splitlines(keepends=True)
        rows = list(read_jsonl(results_path))
    except (OSError, ValueError) as exc:
        raise RuntimeError("v24_canary_checkpoint_unreadable") from exc
    if not isinstance(summary, dict) or summary.get("run_fingerprint") != run_fingerprint:
        raise RuntimeError("v24_canary_checkpoint_identity_drift")
    if diagnostic or two_stage:
        stages = summary.get("active_generation", [])
        attempts = TWO_STAGE_ATTEMPTS if two_stage else ("initial", "semantic_correction")
        if not isinstance(stages, list) or len(stages) > len(attempts):
            raise RuntimeError("v24_ablation_checkpoint_drafts_invalid")
        for index, stage in enumerate(stages):
            if (
                not isinstance(stage, dict)
                or stage.get("attempt") != attempts[index]
                or stage.get("status") not in {
                    "started", "completed", "response_received", "response_invalid", "request_failed",
                    "response_unavailable_after_interruption",
                }
                or (stage.get("status") in {"response_received", "response_invalid"} and (
                    not isinstance(stage.get("response"), dict)
                    or not isinstance(stage["response"].get("content"), str)
                ))
                or not isinstance(stage.get("candidates"), list) or len(stage["candidates"]) > 3
                or stage.get("content_sha256") != sha256_obj({key: value for key, value in stage.items() if key != "content_sha256"})
            ):
                raise RuntimeError("v24_ablation_checkpoint_drafts_invalid")
    saved_count = summary.get("completed_pair_count")
    if (
        type(saved_count) is not int or not 0 <= saved_count <= len(inputs)
        or not saved_count <= len(rows) <= min(saved_count + 1, len(inputs))
        or len(raw_lines) != len(rows)
    ):
        raise RuntimeError("v24_canary_checkpoint_row_count_drift")
    if hashlib.sha256(b"".join(raw_lines[:saved_count])).hexdigest() != summary.get("result_sha256"):
        raise RuntimeError("v24_canary_checkpoint_hash_drift")
    for index, row in enumerate(rows):
        original = inputs[index]
        if row.get("result_content_sha256") != sha256_obj({
            key: value for key, value in row.items() if key != "result_content_sha256"
        }):
            raise RuntimeError("v24_canary_checkpoint_hash_drift")
        if row.get("run_fingerprint") != run_fingerprint:
            raise RuntimeError("v24_canary_checkpoint_identity_drift")
        if row.get("input_index") != index or any(
            row.get(key) != original.get(input_key)
            for key, input_key in (
                ("canary_pair_index", "canary_pair_index"), ("dataset", "dataset"),
                ("source_key", "source_key"), ("upstream_pair_id", "pair_id"),
            )
        ):
            raise RuntimeError("v24_canary_checkpoint_order_drift")
        if diagnostic and any(row.get(key) != original.get(key) for key in ("sample_id", "condition", "generation_claim")):
            raise RuntimeError("v24_ablation_checkpoint_condition_drift")
        if (
            type(row.get("eligible")) is not bool
            or not isinstance(row.get("candidate_evidence"), list)
            or not isinstance(row.get("rejection_reason_counts"), dict)
            or (row["eligible"] and not isinstance(row.get("selected_pair"), dict))
            or (not row["eligible"] and row.get("selected_pair") is not None)
        ):
            raise RuntimeError("v24_canary_checkpoint_result_invalid")
    for state in [summary, *rows]:
        usage = state.get("provider")
        if not isinstance(usage, dict) or any(
            type(usage.get(key)) is not int or usage[key] < 0
            for key in ("logical_api_calls", "physical_attempts", "transport_retry_count")
        ) or type(state.get("external_call_counts_complete")) is not bool:
            raise RuntimeError("v24_canary_checkpoint_usage_invalid")
    final_states = ({"completed_two_stage_diagnostic"} if two_stage else
                    {"completed_diagnostic"} if diagnostic else {"passed", "failed_hard_gates"})
    if summary.get("status") not in {"running", "interrupted", *final_states}:
        raise RuntimeError("v24_canary_checkpoint_status_invalid")
    if summary.get("status") in final_states:
        passed = sum(row["eligible"] for row in rows)
        expected_status = ("completed_two_stage_diagnostic" if two_stage else
                           "completed_diagnostic" if diagnostic else
                           "passed" if passed == len(inputs) else "failed_hard_gates")
        if saved_count != len(inputs) or summary.get("passed_pair_count") != passed or summary["status"] != expected_status:
            raise RuntimeError("v24_canary_checkpoint_final_status_drift")
    return summary, rows


def run_canary(
    root: Path, *, input_path: str | Path, output_dir: str | Path,
    candidate_pools: Sequence[str | Path] = (), resume: bool = False,
    show_progress: bool = True,
    fact_ablation: bool = False, preview_only: bool = False, two_stage: bool = False,
) -> dict[str, object]:
    if fact_ablation and two_stage:
        raise ValueError("v24_ablation_must_keep_original_generation")
    record_stages = fact_ablation or two_stage
    config = load_v24_config(root)
    correction_retries = int(config.get("eligibility", {}).get("semantic_correction_retries", 1))
    fact_budget = get_max_candidate_facts_per_source(config)
    if fact_ablation:
        inputs, frozen_facts, sources, pools, diagnostic_context = _prepare_fact_ablation(root, input_path, config)
        expected = len(inputs)
    else:
        if preview_only and not two_stage:
            raise ValueError("v24_preview_requires_fact_ablation")
        diagnostic_context = {}
        pools = _load_canary_candidate_pools(root, config, candidate_pools)
        if two_stage and any(reader.manifest["scope"] != "development_subset" for reader in pools.values()):
            raise ValueError("v24_two_stage_development_pool_required")
        inputs = _load_canary_inputs(root, input_path)
        expected = int(config.get("development", {}).get("canary_pair_count", 30))
        if len(inputs) != expected:
            raise ValueError(f"v24_canary_input_count:{len(inputs)}:{expected}")
        if len({(row["dataset"], row["source_key"]) for row in inputs}) != len(inputs):
            raise ValueError("v24_canary_duplicate_source")
        sources = _source_lookup(root, {str(row.get("dataset") or "") for row in inputs},
                                 {(str(row["dataset"]), str(row["source_key"])) for row in inputs})
        frozen_facts = []
        for row in inputs:
            dataset = str(row["dataset"])
            reader = pools.get((dataset, str(row.get("candidate_pool_sha256") or "")))
            if reader is None:
                raise ValueError("v24_canary_candidate_pool_drift")
            facts = reader.facts_for_source(sources[(dataset, str(row["source_key"]))])
            matching = [fact for fact in facts[:fact_budget] if fact["upstream_pair_id"] == row.get("pair_id")]
            if len(matching) != 1 or any(matching[0][key] != row.get(key) for key in (
                "true_claim", "original_entity", "original_span", "proposition_span", "fact_order",
            )):
                raise ValueError("v24_canary_fact_not_in_candidate_pool")
            frozen_facts.append(matching[0])
        if two_stage:
            diagnostic_context = {
                "run_kind": "two_stage_fact_query_canary", "diagnostic_only": True,
                "source_count": expected, "capacity_sample_allowed": False,
                "fact_construction": "source_evidence_then_separate_llm_review",
                "query_construction": "fixed_canonical_shared_question_template",
                "review_method": "separate_llm_requests_same_model",
                "independent_blind_review_performed": False, "human_review_performed": False,
                "maximum_logical_api_calls": expected * (4 + 2 * correction_retries),
                "request_stages": list(TWO_STAGE_ATTEMPTS[:4 + 2 * correction_retries]),
            }
    output = root / output_dir
    if not preview_only and not resume and output.exists() and any(output.iterdir()):
        raise ValueError("v24_canary_output_exists")
    code_root = Path(__file__).resolve().parents[1]
    context = {
        **diagnostic_context,
        "protocol_version": config["protocol_version"],
        "canary_pair_count": expected,
        "fallback_pair_count": 0,
        "fallback_allowed": False,
        "semantic_correction_retries": correction_retries,
        "max_candidate_facts_per_source": fact_budget,
        "config_sha256": sha256_obj(config),
        "candidate_fact_pools": [pools[key].binding() for key in sorted(pools)],
        "input_sha256": sha256_file(root / input_path),
        "facts_sha256": sha256_obj(frozen_facts),
        "llm_profile": _canary_llm_identity(config),
        "code_sha256": sha256_obj({
            "runner": sha256_file(__file__),
            "screening": sha256_file(code_root / "src/prepare/restoration_first_v24.py"),
        }),
    }
    if preview_only:
        return {**context, "status": "prepared_diagnostic", "external_calls_performed": 0,
                "conditions": [{key: row[key] for key in (
                    "sample_id", "dataset", "source_key", "stratum", "condition", "generation_claim",
                ) if key in row} for row in inputs]}
    run_fingerprint = sha256_obj(context)
    results_path = output / "canary_results.jsonl"
    summary_path = output / "canary_summary.json"
    results: list[dict[str, object]] = []
    summary: dict[str, object] = {}
    previous_usage: dict[str, object] = {}
    semantic_identity = None
    counts_complete = True
    if resume:
        summary, results = _load_canary_checkpoint(
            output, run_fingerprint=run_fingerprint, inputs=inputs, diagnostic=fact_ablation, two_stage=two_stage,
        )
        if summary["status"] in {"passed", "failed_hard_gates", "completed_diagnostic", "completed_two_stage_diagnostic"}:
            if summary["status"] == "failed_hard_gates":
                raise RuntimeError(f"v24_canary_hard_gate_failed:{summary['passed_pair_count']}/{expected}")
            return summary
        latest = results[-1] if len(results) > summary["completed_pair_count"] else summary
        previous_usage = dict(latest["provider"])
        counts_complete = bool(latest["external_call_counts_complete"])
        active = summary.get("active_input_index")
        if active is not None and active >= len(results):
            # 在途请求可能已被服务端处理；恢复不声称知道其实际调用/重试次数。
            counts_complete = False
        semantic_identity = summary.get("semantic_similarity")
    else:
        write_jsonl_atomic([], results_path)

    provider = None
    active_input_index = None
    active_generation = list(summary.get("active_generation", [])) if record_stages else []
    cached_input_index = summary.get("active_input_index")

    def save_progress(status: str, *, interruption_type: str | None = None) -> dict[str, object]:
        usage = _canary_provider_totals(previous_usage, provider.stats() if provider is not None else {})
        progress = {
            **context, "run_fingerprint": run_fingerprint, "status": status,
            "completed_pair_count": len(results),
            "passed_pair_count": sum(bool(row["eligible"]) for row in results),
            "active_input_index": active_input_index,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "resumed": resume, "provider": usage, "semantic_similarity": semantic_identity,
            "result_sha256": sha256_file(results_path),
            "external_calls_performed": usage["physical_attempts"],
            "external_call_counts_complete": counts_complete and active_input_index is None,
            "retriever_calls_performed": 0, "victim_calls_performed": 0, "membership_read": False,
        }
        if interruption_type:
            progress["interruption_type"] = interruption_type
        if record_stages:
            progress["active_generation"] = active_generation
        if two_stage:
            progress.update(
                automatic_quality_pass=len(results) == expected and all(row["eligible"] for row in results),
                assistant_review_completed=False,
                execution_incomplete_source_count=sum(bool(row.get("execution_incomplete")) for row in results),
            )
        write_json(progress, summary_path)
        return progress

    class CanaryPersistenceError(RuntimeError):
        """响应落盘失败必须中止运行，不能转成候选质量拒绝。"""

    def request_recorded_candidates(
        attempt: str, request: Callable[[], Sequence[Mapping[str, object]]],
    ) -> Sequence[Mapping[str, object]]:
        """在既有 summary 中保存当前响应，恢复时不重复消耗已尝试的生成轮次。"""
        nonlocal counts_complete
        cached = next((stage for stage in active_generation if stage["attempt"] == attempt), None)

        def persist_stage() -> None:
            stage["content_sha256"] = sha256_obj({key: value for key, value in stage.items() if key != "content_sha256"})
            try:
                save_progress("running")
            except Exception as exc:
                raise CanaryPersistenceError("v24_canary_response_save_failed") from exc

        if cached is not None and cached["status"] != "response_received":
            if cached["status"] == "completed":
                return cached["candidates"]
            if cached["status"] in {"response_invalid", "request_failed"}:
                if cached["status"] == "request_failed":
                    counts_complete = False
                raise ValueError("v24_canary_saved_response_failure")
            # 已发起但没有持久响应的轮次不能免费重抽；保留缺失证据并继续固定预算。
            counts_complete = False
            cached["status"] = "response_unavailable_after_interruption"
            stage = cached
            persist_stage()
            if two_stage:
                raise RuntimeError("v24_two_stage_response_unavailable_after_interruption")
            return []
        stage = cached if cached is not None else {"attempt": attempt, "status": "started", "candidates": []}
        if cached is None:
            active_generation.append(stage)
            persist_stage()

        def record_response(evidence: Mapping[str, object]) -> None:
            stage.update(status="response_received", response=dict(evidence))
            persist_stage()

        observing = isinstance(provider, LunaCandidateProvider)
        previous_observer = provider.response_observer if observing else None
        if observing:
            provider.response_observer = record_response
        try:
            packages = list(provider.parse_response(stage["response"]) if cached is not None else request())
        except CanaryPersistenceError:
            raise
        except Exception as exc:
            stage.update(status="response_invalid" if "response" in stage else "request_failed", error_type=type(exc).__name__)
            persist_stage()
            raise
        finally:
            if observing:
                provider.response_observer = previous_observer
        stage.update(status="completed", candidates=packages)
        persist_stage()
        return packages

    class RecordedProvider:
        def __init__(self) -> None:
            self.correcting = False

        def __call__(self, fact: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
            return request_recorded_candidates("initial", lambda: provider(fact))

        def correct(self, fact: Mapping[str, object], rejected: Sequence[Mapping[str, object]]) -> Sequence[Mapping[str, object]]:
            self.correcting = True
            return request_recorded_candidates("semantic_correction", lambda: provider.correct(fact, rejected))

        def construct_fact(self, fact: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
            return request_recorded_candidates("fact_construction", lambda: provider.construct_fact(fact))

        def verify_fact(self, fact: Mapping[str, object], construction: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
            return request_recorded_candidates("fact_verification", lambda: provider.verify_fact(fact, construction))

        def verify_queries(self, fact: Mapping[str, object], packages: Sequence[Mapping[str, object]]) -> Sequence[Mapping[str, object]]:
            attempt = "semantic_correction_verification" if self.correcting else "initial_verification"
            return request_recorded_candidates(attempt, lambda: provider.verify_queries(fact, packages))

    def final_status() -> str:
        if two_stage:
            return "completed_two_stage_diagnostic"
        if fact_ablation:
            return "completed_diagnostic"
        return "passed" if all(row["eligible"] for row in results) else "failed_hard_gates"

    if len(results) == expected:
        summary = save_progress(final_status())
        if summary["status"] == "failed_hard_gates":
            raise RuntimeError(f"v24_canary_hard_gate_failed:{summary['passed_pair_count']}/{expected}")
        return summary
    if not resume:
        save_progress("running")
    if show_progress:
        print(f"Canary: 已保存 {len(results)}/{expected} 条结果", flush=True)
    semantic_scorer = build_v24_semantic_similarity(root)
    try:
        if semantic_identity is not None and semantic_identity != semantic_scorer.identity():
            raise RuntimeError("v24_canary_semantic_identity_drift")
        semantic_identity = semantic_scorer.identity()
        provider = build_luna_candidate_provider(root)
        try:
            for index in range(len(results), expected):
                row, fact = inputs[index], frozen_facts[index]
                active_input_index = index
                if index != cached_input_index:
                    active_generation = []
                save_progress("running")
                if show_progress:
                    print(f"Canary: 正在处理 {index + 1}/{expected} {row['dataset']} {row['source_key']}", flush=True)
                result = {
                    "run_fingerprint": run_fingerprint, "input_index": index,
                    "canary_pair_index": row.get("canary_pair_index"),
                    "dataset": row["dataset"],
                    "source_key": row["source_key"],
                    "upstream_pair_id": row["pair_id"],
                    "source_hash": fact.get("source_hash") if fact else row.get("source_hash"),
                    "normalized_text_hash": fact.get("normalized_text_hash") if fact else row.get("normalized_text_hash"),
                }
                if fact_ablation:
                    result.update({key: row[key] for key in (
                        "sample_id", "condition", "stratum", "raw_fact", "reference_fact", "generation_claim",
                    )})
                try:
                    screened = screen_source(
                        sources[(str(row["dataset"]), str(row["source_key"]))],
                        candidate_provider=RecordedProvider() if record_stages else provider,
                        facts=[fact], minimum_pairs=1,
                        allow_surface_fallback=False, similarity_fn=semantic_scorer,
                        semantic_correction_retries=correction_retries, include_candidate_evidence=True,
                        max_candidate_facts_per_source=fact_budget,
                        **({"include_full_candidate_evidence": True} if record_stages else {}),
                        **({"two_stage": True} if two_stage else {}),
                    ) if fact is not None else {
                        "eligible": False, "rejection_reason_counts": {"reference_fact_unusable": 1},
                    }
                    selected = screened.get("selected_pairs") or []
                    result.update({
                        "eligible": bool(screened.get("eligible")),
                        "selected_pair": selected[0] if selected else None,
                        "rejection_reason_counts": screened.get("rejection_reason_counts", {}),
                        "candidate_evidence": screened.get("candidate_evidence", []),
                    })
                    if two_stage:
                        result.update(fact_evidence=screened.get("fact_evidence", []), execution_incomplete=False)
                except CanaryPersistenceError:
                    raise
                except Exception as exc:
                    if not (record_stages and active_generation and active_generation[-1]["status"] == "response_invalid"):
                        counts_complete = False
                    result.update({
                        "eligible": False, "selected_pair": None, "candidate_evidence": [],
                        "rejection_reason_counts": {f"execution_error:{type(exc).__name__}": 1},
                    })
                    if two_stage:
                        result.update(fact_evidence=[], execution_incomplete=True)
                result["provider"] = _canary_provider_totals(previous_usage, provider.stats())
                if record_stages:
                    result["generation_drafts"] = list(active_generation)
                result["external_call_counts_complete"] = counts_complete
                result["result_content_sha256"] = sha256_obj(result)
                # 只在原子替换成功后推进内存位置；磁盘错误不得变成科学门禁失败。
                write_jsonl_atomic([*results, result], results_path)
                results.append(result)
                active_input_index = None
                active_generation = []
                summary = save_progress(final_status() if len(results) == expected else "running")
                if show_progress:
                    print(f"Canary: 已保存 {len(results)}/{expected}，通过 {summary['passed_pair_count']}", flush=True)
        except BaseException as exc:
            try:
                # 中断可能发生在 replace 成功、内存 append 之前，先以磁盘为准。
                _, results = _load_canary_checkpoint(
                    output, run_fingerprint=run_fingerprint, inputs=inputs, diagnostic=fact_ablation, two_stage=two_stage,
                )
                if active_input_index is not None and active_input_index < len(results):
                    active_input_index = None
                    active_generation = []
                counts_complete = counts_complete and active_input_index is None
                save_progress("interrupted", interruption_type=type(exc).__name__)
            except (OSError, RuntimeError):
                # 保留原始中断；前一次原子保存的结果和汇总仍可用于恢复。
                pass
            raise
    finally:
        semantic_scorer.close()
    if summary["status"] == "failed_hard_gates":
        raise RuntimeError(f"v24_canary_hard_gate_failed:{summary['passed_pair_count']}/{expected}")
    return summary


def _capacity_paths(
    root: Path,
    output_dir: str | Path,
    *,
    dataset: str,
    use_luna: bool,
) -> tuple[Path, Path]:
    output = Path(output_dir)
    if not output.is_absolute():
        output = root / output
    mode = "luna_sample" if use_luna else "offline_estimate"
    return (
        output / f"{dataset}.{mode}.json",
        output / f"{dataset}.{mode}.checkpoint.jsonl",
    )


def _capacity_source_reference(source: Mapping[str, object]) -> dict[str, object]:
    return {
        "dataset": str(source.get("dataset") or ""),
        "source_key": str(source.get("source_key") or ""),
        "source_order_rank": str(source.get("source_order_rank") or ""),
        "source_hash": str(source.get("source_hash") or ""),
        "normalized_text_hash": str(source.get("normalized_text_hash") or ""),
    }


def _capacity_provider_usage(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, object]:
    failures_before = list(before.get("failures") or [])
    failures_after = list(after.get("failures") or [])
    return {
        "logical_api_calls": int(after.get("logical_api_calls") or 0)
        - int(before.get("logical_api_calls") or 0),
        "physical_attempts": int(after.get("physical_attempts") or 0)
        - int(before.get("physical_attempts") or 0),
        "transport_retry_count": int(after.get("transport_retry_count") or 0)
        - int(before.get("transport_retry_count") or 0),
        "provider_model_ids": sorted(str(value) for value in after.get("provider_model_ids") or []),
        "profile_name": after.get("profile_name"),
        "configured_model": after.get("configured_model"),
        "failures": [str(value) for value in failures_after[len(failures_before):]],
    }


def _validate_capacity_checkpoint(
    rows: list[dict[str, object]],
    *,
    run_fingerprint: str,
    selected_sources: list[dict[str, object]],
) -> None:
    if len(rows) > len(selected_sources):
        raise RuntimeError("v24_capacity_checkpoint_row_count_drift")
    for source_index, row in enumerate(rows):
        if row.get("run_fingerprint") != run_fingerprint:
            raise RuntimeError("v24_capacity_checkpoint_identity_drift")
        if row.get("status") != "completed" or row.get("source_index") != source_index:
            raise RuntimeError("v24_capacity_checkpoint_order_drift")
        if row.get("source") != _capacity_source_reference(selected_sources[source_index]):
            raise RuntimeError("v24_capacity_checkpoint_source_drift")
        if not isinstance(row.get("screen_result"), Mapping):
            raise RuntimeError("v24_capacity_checkpoint_result_invalid")


def _capacity_provider_summary(
    rows: list[dict[str, object]],
    provider: object,
) -> dict[str, object]:
    current = dict(provider.stats())  # type: ignore[attr-defined]
    model_ids: set[str] = set()
    failures: list[str] = []
    logical_api_calls = 0
    physical_attempts = 0
    transport_retry_count = 0
    for row in rows:
        usage = row.get("provider_usage")
        if not isinstance(usage, Mapping):
            raise RuntimeError("v24_capacity_checkpoint_provider_usage_invalid")
        logical_api_calls += int(usage.get("logical_api_calls") or 0)
        physical_attempts += int(usage.get("physical_attempts") or 0)
        transport_retry_count += int(usage.get("transport_retry_count") or 0)
        model_ids.update(str(value) for value in usage.get("provider_model_ids") or [])
        failures.extend(str(value) for value in usage.get("failures") or [])
    return {
        **current,
        "logical_api_calls": logical_api_calls,
        "physical_attempts": physical_attempts,
        "transport_retry_count": transport_retry_count,
        "provider_model_ids": sorted(model_ids),
        "failures": failures,
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def run_capacity_check(
    root: Path,
    *,
    dataset: str,
    sample_sources: int,
    use_luna: bool,
    output_dir: str | Path = CAPACITY_OUTPUT_DIR,
    resume: bool = False,
    show_progress: bool = True,
    candidate_pools: Sequence[str | Path] = (),
    allow_legacy_facts: bool = False,
) -> dict[str, object]:
    if sample_sources <= 0:
        raise ValueError("v24_capacity_sample_invalid")
    config = load_v24_config(root)
    pools = {} if allow_legacy_facts else load_candidate_fact_pools(root, config, candidate_pools)
    if not allow_legacy_facts and dataset not in pools:
        raise ValueError("v24_capacity_candidate_pool_dataset_missing")
    candidate_pool_binding = pools[dataset].binding() if not allow_legacy_facts else None
    correction_retries = int(config.get("eligibility", {}).get("semantic_correction_retries", 1))
    fact_budget = get_max_candidate_facts_per_source(config)
    selected_sources: list[dict[str, object]] = []
    source_iter = iter_frozen_source_pool(root, dataset)
    for source in source_iter:
        if not allow_legacy_facts and str(source["source_key"]) not in pools[dataset].offsets:
            continue
        selected_sources.append(source)
        if len(selected_sources) >= sample_sources:
            break
    if len(selected_sources) != sample_sources:
        raise RuntimeError("v24_capacity_sample_source_shortfall")
    source_references = [_capacity_source_reference(source) for source in selected_sources]
    config_sha256 = sha256_obj(config)
    source_selection_sha256 = sha256_obj(source_references)
    run_fingerprint = sha256_obj({
        "protocol_version": config.get("protocol_version"),
        "dataset": dataset,
        "mode": "luna_sample" if use_luna else "offline_fact_capacity_estimate",
        "sample_sources": sample_sources,
        "max_candidate_facts_per_source": fact_budget,
        "semantic_correction_retries": correction_retries,
        "config_sha256": config_sha256,
        "source_selection_sha256": source_selection_sha256,
        "candidate_fact_pool": candidate_pool_binding,
    })
    summary_path, checkpoint_path = _capacity_paths(
        root, output_dir, dataset=dataset, use_luna=use_luna
    )
    if summary_path.exists():
        existing = read_json(summary_path)
        if existing.get("run_fingerprint") != run_fingerprint:
            raise RuntimeError("v24_capacity_summary_identity_drift")
        if use_luna and (
            not checkpoint_path.is_file()
            or existing.get("checkpoint_sha256") != sha256_file(checkpoint_path)
        ):
            raise RuntimeError("v24_capacity_checkpoint_hash_drift")
        if not resume:
            raise RuntimeError("v24_capacity_summary_exists_use_resume")
        return dict(existing)
    if checkpoint_path.exists() and not resume:
        raise RuntimeError("v24_capacity_checkpoint_exists_use_resume")

    checkpoint_rows = list(read_jsonl(checkpoint_path)) if checkpoint_path.exists() else []
    _validate_capacity_checkpoint(
        checkpoint_rows,
        run_fingerprint=run_fingerprint,
        selected_sources=selected_sources,
    )
    resumed = bool(checkpoint_rows)
    screen_results: list[dict[str, object]] = [
        dict(row["screen_result"])  # type: ignore[arg-type]
        for row in checkpoint_rows
    ]
    semantic_scorer = build_v24_semantic_similarity(root) if use_luna else None
    provider = build_luna_candidate_provider(root) if use_luna else None
    if use_luna:
        if semantic_scorer is None or provider is None:
            raise RuntimeError("v24_capacity_luna_runtime_missing")
        if show_progress:
            print(
                f"Capacity sample {dataset}: completed "
                f"{len(checkpoint_rows)}/{len(selected_sources)} sources",
                flush=True,
            )
        try:
            for source_index in range(len(checkpoint_rows), len(selected_sources)):
                source = selected_sources[source_index]
                if show_progress:
                    print(
                        f"Processing {dataset} source "
                        f"{source_index + 1}/{len(selected_sources)}",
                        flush=True,
                    )
                provider_before = provider.stats()
                screened = screen_source(
                    source,
                    candidate_provider=provider,
                    facts=None if allow_legacy_facts else pools[dataset].facts_for_source(source),
                    allow_legacy_facts=allow_legacy_facts,
                    minimum_pairs=3,
                    allow_surface_fallback=False,
                    similarity_fn=semantic_scorer,
                    semantic_correction_retries=correction_retries,
                    max_candidate_facts_per_source=fact_budget,
                )
                checkpoint_row = {
                    "kind": "v24_capacity_source_checkpoint",
                    "status": "completed",
                    "run_fingerprint": run_fingerprint,
                    "source_index": source_index,
                    "source": source_references[source_index],
                    "screen_result": dict(screened),
                    "provider_usage": _capacity_provider_usage(
                        provider_before, provider.stats()
                    ),
                }
                append_jsonl_record(checkpoint_row, checkpoint_path)
                checkpoint_rows.append(checkpoint_row)
                screen_results.append(dict(screened))
                if show_progress:
                    print(
                        f"Completed {dataset} source "
                        f"{source_index + 1}/{len(selected_sources)} "
                        f"eligible={bool(screened.get('eligible'))}",
                        flush=True,
                    )
        finally:
            semantic_scorer.close()
    else:
        for source in selected_sources:
            fact_count = len(enumerate_candidate_facts(source) if allow_legacy_facts else pools[dataset].facts_for_source(source))
            screen_results.append({
                "eligible": None,
                "candidate_fact_count": fact_count,
                "processed_fact_count": 0,
                "unprocessed_fact_count": fact_count,
                "candidate_package_count": 0,
                "early_stop_triggered": False,
                "original_entity_diversity": 0,
            })

    screened_count = len(screen_results)
    candidate_fact_count = sum(int(row.get("candidate_fact_count") or 0) for row in screen_results)
    processed_fact_count = sum(int(row.get("processed_fact_count") or 0) for row in screen_results)
    unprocessed_fact_count = sum(int(row.get("unprocessed_fact_count") or 0) for row in screen_results)
    candidate_package_count = sum(int(row.get("candidate_package_count") or 0) for row in screen_results)
    raw_fact_budget_feasible_count = sum(
        min(int(row.get("candidate_fact_count") or 0), fact_budget) >= 3
        for row in screen_results
    )
    raw_fact_budget_feasible_rate = raw_fact_budget_feasible_count / max(1, screened_count)
    eligible_count = sum(row.get("eligible") is True for row in screen_results) if use_luna else 0
    eligible_rate = eligible_count / max(1, screened_count) if use_luna else None
    early_stop_source_count = sum(bool(row.get("early_stop_triggered")) for row in screen_results)
    diversity_counts = {str(value): 0 for value in range(1, 4)}
    if use_luna:
        for row in screen_results:
            diversity = str(int(row.get("original_entity_diversity") or 0))
            if row.get("eligible") is True and diversity in diversity_counts:
                diversity_counts[diversity] += 1
    target = int(config.get("eligibility", {}).get("target_sources", 2250))
    expected_source_count = int(
        config.get("source_pool", {}).get("expected_source_counts", {}).get(dataset, 0)
        or 0
    )
    provider_summary = (
        _capacity_provider_summary(checkpoint_rows, provider)
        if provider is not None
        else None
    )
    projected_eligible_source_count = (
        int(round(float(eligible_rate) * expected_source_count))
        if eligible_rate is not None
        else None
    )
    if not use_luna:
        capacity_status = "estimate_only"
    elif int(projected_eligible_source_count or 0) >= target:
        capacity_status = "sample_projection_at_or_above_target"
    else:
        capacity_status = "sample_projection_below_target"
    result = {
        "status": "completed",
        "dataset": dataset,
        "mode": "luna_sample" if use_luna else "offline_fact_capacity_estimate",
        "candidate_source_count": screened_count,
        "candidate_fact_count": candidate_fact_count,
        "processed_fact_count": processed_fact_count,
        "unprocessed_fact_count": unprocessed_fact_count,
        "candidate_package_count": candidate_package_count,
        "raw_fact_budget_feasible_source_count": raw_fact_budget_feasible_count,
        "raw_fact_budget_feasible_source_rate": raw_fact_budget_feasible_rate,
        "projected_raw_fact_budget_feasible_source_count": int(
            round(raw_fact_budget_feasible_rate * expected_source_count)
        ),
        "observed_eligible_source_count": eligible_count if use_luna else None,
        "observed_eligible_source_rate": eligible_rate,
        "projected_eligible_source_count": projected_eligible_source_count,
        "target_eligible_source_count": target,
        "max_candidate_facts_per_source": fact_budget,
        "early_stop_source_count": early_stop_source_count,
        "entity_diversity_1_source_count": diversity_counts["1"],
        "entity_diversity_2_source_count": diversity_counts["2"],
        "entity_diversity_3_source_count": diversity_counts["3"],
        "mean_original_entity_diversity": (
            sum(int(key) * value for key, value in diversity_counts.items())
            / max(1, eligible_count)
        ),
        "capacity_status": capacity_status,
        "run_fingerprint": run_fingerprint,
        "config_sha256": config_sha256,
        "source_selection_sha256": source_selection_sha256,
        "resumed": resumed,
        "checkpoint_path": _display_path(root, checkpoint_path) if use_luna else None,
        "checkpoint_sha256": sha256_file(checkpoint_path) if use_luna else None,
        "provider": provider_summary,
        "semantic_similarity": semantic_scorer.identity() if semantic_scorer is not None else None,
        "external_calls_performed": (
            int(provider_summary.get("physical_attempts") or 0)
            if provider_summary is not None
            else 0
        ),
        "retriever_calls_performed": 0,
        "victim_calls_performed": 0,
        "membership_read": False,
        "candidate_fact_pool": candidate_pool_binding,
        "development_sources": source_references,
        "proposed_fact_count": (
            sum(pools[dataset].record(str(source["source_key"]))["proposed_fact_count"] for source in selected_sources)
            if not allow_legacy_facts else None
        ),
    }
    write_json(result, summary_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="v24 offline pre-split eligibility checks")
    parser.add_argument(
        "command",
        choices=(
            "validate-config",
            "source-pools",
            "validate-eligibility",
            "validate-split",
            "prepare-fresh-canary",
            "prepare-luna-only-ab",
            "run-canary",
            "run-luna-only-ab",
            "preview-luna-only-ab",
            "preview-luna-only-smoke",
            "run-luna-only-smoke",
            "preview-fact-ablation",
            "run-fact-ablation",
            "preview-two-stage-canary",
            "run-two-stage-canary",
            "summarize-fact-ablation",
            "summarize-luna-only-ab",
            "run-capacity-check",
            "build-candidate-pool",
            "validate-candidate-pool",
        ),
    )
    parser.add_argument("--manifest", help="普通 v24 manifest 路径（仅 validate-* 命令使用）")
    parser.add_argument("--dataset", choices=DATASET_ORDER)
    parser.add_argument("--input", dest="input_path", help="membership-blind canary input JSONL")
    parser.add_argument("--review", help="Assistant-only 候选级复核 JSONL（summarize-fact-ablation 使用）")
    parser.add_argument("--output-dir")
    parser.add_argument("--sample-sources", type=int)
    parser.add_argument("--per-dataset", type=int, default=10)
    parser.add_argument("--use-luna", action="store_true")
    parser.add_argument("--resume", action="store_true", help="恢复 canary、capacity 或 candidate pool 的已有结果")
    parser.add_argument("--candidate-pool", action="append", default=[], help="v24 pool_manifest.json；可重复提供，canary 还允许同数据集的互不重叠开发补充池")
    args = parser.parse_args()
    if args.command == "validate-config":
        config = load_v24_config(PROJECT_ROOT)
        adapter = config["candidate_fact_adapter"]
        adapter_kind = str(adapter.get("kind") or "")
        if adapter_kind == "gliner2_entity_value_span":
            candidate_model_bound = all(
                bool(adapter.get(key))
                for key in ("model", "model_revision", "local_path", "model_lock_path")
            )
            candidate_binding = {
                "kind": adapter_kind,
                "model": adapter.get("model"),
                "model_revision": adapter.get("model_revision"),
                "local_path_bound": bool(adapter.get("local_path")),
                "model_lock_bound": bool(adapter.get("model_lock_path")),
            }
        else:
            candidate_model_bound = False
            candidate_binding = {"kind": adapter_kind}
        print(json.dumps({"status": "passed", "protocol_version": config["protocol_version"],
                          "candidate_model_bound": candidate_model_bound,
                          "candidate_binding": candidate_binding,
                          "external_calls_performed": 0}, ensure_ascii=False))
    elif args.command == "build-candidate-pool":
        if not args.dataset:
            parser.error("build-candidate-pool requires --dataset")
        fixed = None
        if args.input_path:
            inputs, _ = _load_luna_ab_inputs(PROJECT_ROOT, args.input_path)
            fixed = [row for row in inputs["sources"] if row["dataset"] == args.dataset]
            if args.sample_sources not in (None, len(fixed)):
                parser.error("--sample-sources must match the fixed A/B inputs")
            args.sample_sources = len(fixed)
        output_dir = args.output_dir or (
            f"artifacts/v24/development/candidate_fact_pool/{args.dataset}" if args.sample_sources is not None
            else f"artifacts/v24/candidate_fact_pools/{args.dataset}"
        )
        result = build_candidate_fact_pool(PROJECT_ROOT, dataset=args.dataset, output_dir=output_dir,
                                           sample_sources=args.sample_sources, resume=args.resume,
                                           **({"fixed_source_identities": fixed} if fixed is not None else {}))
        print(json.dumps({key: result[key] for key in (
            "status", "dataset", "scope", "completed_source_count", "proposed_fact_count", "candidate_fact_count", "pool_sha256", "usage",
        )}, ensure_ascii=False))
    elif args.command == "validate-candidate-pool":
        if not args.manifest:
            parser.error("validate-candidate-pool requires --manifest")
        config = load_v24_config(PROJECT_ROOT)
        reader = CandidateFactPoolReader(PROJECT_ROOT / args.manifest, config=config)
        reader.validate_environment(PROJECT_ROOT, config)
        reader.validate_sources(PROJECT_ROOT)
        print(json.dumps({"status": "passed", "dataset": reader.dataset,
                          "completed_source_count": len(reader.offsets), "pool_sha256": reader.manifest["pool_sha256"],
                          "external_calls_performed": 0}, ensure_ascii=False))
    elif args.command == "source-pools":
        print(json.dumps({"status": "passed", "source_pools": source_pool_bindings(PROJECT_ROOT), "external_calls_performed": 0}, ensure_ascii=False))
    elif args.command in {"validate-eligibility", "validate-split"}:
        if not args.manifest:
            parser.error("validate-* requires --manifest")
        payload = read_json(Path(args.manifest))
        validator = validate_eligibility_manifest if args.command == "validate-eligibility" else validate_split_manifest
        result = validator(payload)
        print(json.dumps({**result, "external_calls_performed": 0}, ensure_ascii=False))
    elif args.command == "prepare-fresh-canary":
        if args.output_dir:
            output_dir = args.output_dir
        else:
            output_dir = str(FRESH_CANARY_OUTPUT_DIR)
        print(json.dumps(
            prepare_fresh_canary(
                PROJECT_ROOT,
                per_dataset=args.per_dataset,
                output_dir=output_dir,
                candidate_pools=args.candidate_pool,
            ),
            ensure_ascii=False,
        ))
    elif args.command == "prepare-luna-only-ab":
        print(json.dumps(
            prepare_luna_only_ab(
                PROJECT_ROOT,
                per_dataset=args.per_dataset,
                output_dir=args.output_dir or str(LUNA_ONLY_AB_OUTPUT_DIR),
            ),
            ensure_ascii=False,
        ))
    elif args.command == "run-canary":
        input_path = args.input_path or load_v24_config(PROJECT_ROOT).get("development", {}).get("canary_input_path")
        if not input_path:
            parser.error("run-canary requires --input or development.canary_input_path")
        output_dir = args.output_dir or str(CANARY_OUTPUT_DIR)
        print(json.dumps(run_canary(PROJECT_ROOT, input_path=input_path, output_dir=output_dir,
                                   candidate_pools=args.candidate_pool, resume=args.resume), ensure_ascii=False))
    elif args.command in {"run-luna-only-smoke", "preview-luna-only-smoke"}:
        if not args.input_path:
            parser.error("luna-only-smoke requires --input frozen chunk JSONL")
        if args.command == "run-luna-only-smoke" and not args.output_dir:
            parser.error("run-luna-only-smoke requires a new --output-dir")
        print(json.dumps(run_luna_only_smoke(
            PROJECT_ROOT, input_path=args.input_path, output_dir=args.output_dir or ".",
            preview_only=args.command == "preview-luna-only-smoke", resume=args.resume,
        ), ensure_ascii=False))
    elif args.command in {"run-luna-only-ab", "preview-luna-only-ab"}:
        if not args.input_path:
            parser.error("luna-only-ab requires --input luna_only_ab_inputs.json")
        if not args.candidate_pool:
            parser.error("run-luna-only-ab requires --candidate-pool for all datasets")
        if args.command == "run-luna-only-ab" and not args.output_dir:
            parser.error("run-luna-only-ab requires a new --output-dir")
        print(json.dumps(run_luna_only_ab(
            PROJECT_ROOT,
            input_path=args.input_path,
            candidate_pools=args.candidate_pool,
            output_dir=args.output_dir or str(LUNA_ONLY_AB_OUTPUT_DIR),
            resume=args.resume, preview_only=args.command == "preview-luna-only-ab",
        ), ensure_ascii=False))
    elif args.command in {"preview-two-stage-canary", "run-two-stage-canary"}:
        if not args.input_path:
            parser.error("two-stage-canary requires --input with development canary facts")
        if args.command == "run-two-stage-canary" and not args.output_dir:
            parser.error("run-two-stage-canary requires a new --output-dir")
        print(json.dumps(run_canary(
            PROJECT_ROOT, input_path=args.input_path, output_dir=args.output_dir or ".",
            candidate_pools=args.candidate_pool, resume=args.resume, two_stage=True,
            preview_only=args.command == "preview-two-stage-canary",
        ), ensure_ascii=False))
    elif args.command in {"preview-fact-ablation", "run-fact-ablation"}:
        if not args.input_path:
            parser.error("fact-ablation requires --input with Assistant reference facts")
        if args.command == "run-fact-ablation" and not args.output_dir:
            parser.error("run-fact-ablation requires a new --output-dir")
        print(json.dumps(run_canary(
            PROJECT_ROOT, input_path=args.input_path, output_dir=args.output_dir or ".",
            resume=args.resume, fact_ablation=True, preview_only=args.command == "preview-fact-ablation",
        ), ensure_ascii=False))
    elif args.command == "summarize-fact-ablation":
        if not args.input_path:
            parser.error("summarize-fact-ablation requires --input canary_results.jsonl")
        result_path = PROJECT_ROOT / args.input_path
        summary = read_json(result_path.parent / "canary_summary.json")
        if (summary.get("run_kind") != "fact_context_ablation"
                or summary.get("status") != "completed_diagnostic"
                or summary.get("result_sha256") != sha256_file(result_path)):
            raise ValueError("v24_ablation_summary_result_mismatch")
        results = list(read_jsonl(result_path))
        if len(results) != summary.get("condition_count") or any(row.get("run_fingerprint") != summary.get("run_fingerprint") for row in results):
            raise ValueError("v24_ablation_summary_result_mismatch")
        report = summarize_fact_ablation(results, list(read_jsonl(PROJECT_ROOT / args.review)) if args.review else [])
        report.update(result_sha256=sha256_file(result_path), review_sha256=sha256_file(PROJECT_ROOT / args.review) if args.review else None)
        if args.output_dir:
            report_path = PROJECT_ROOT / args.output_dir / "fact_ablation_report.json"
            if report_path.exists() and read_json(report_path) != report:
                raise ValueError("v24_ablation_report_exists")
            if not report_path.exists():
                write_json(report, report_path)
        print(json.dumps(report, ensure_ascii=False))
    elif args.command == "summarize-luna-only-ab":
        if not args.input_path:
            parser.error("summarize-luna-only-ab requires --input luna_only_ab_results.jsonl")
        print(json.dumps(summarize_luna_only_ab(PROJECT_ROOT, args.input_path), ensure_ascii=False))
    else:
        if not args.dataset:
            parser.error("run-capacity-check requires --dataset")
        config = load_v24_config(PROJECT_ROOT)
        sample_sources = args.sample_sources or int(config.get("development", {}).get("capacity_sample_sources", 30))
        output_dir = args.output_dir or str(CAPACITY_OUTPUT_DIR)
        print(json.dumps(run_capacity_check(
            PROJECT_ROOT,
            dataset=args.dataset,
            sample_sources=sample_sources,
            use_luna=args.use_luna,
            output_dir=output_dir,
            resume=args.resume,
            candidate_pools=args.candidate_pool,
        ), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
