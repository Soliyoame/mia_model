"""Build v6.3 source eligibility from a frozen double-size candidate pool.

The default invocation only freezes the label-independent scan plan.  A later
explicit ``--resume --execute`` invocation runs complete
fact -> claim -> paired-query -> stealth waves over the entire frozen pool.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.attack.entity_extractor import (  # noqa: E402
    EXTRACTOR_VERSION,
    EntityExtractor,
)
from src.attack.entity_type_policy import (  # noqa: E402
    ENTITY_TYPE_POLICY_SHA256,
    ENTITY_TYPE_POLICY_VERSION,
)
from src.attack.semantic_entity_resolver import (  # noqa: E402
    SEMANTIC_RESOLVER_PROTOCOL,
    SEMANTIC_SCHEMA_SHA256,
    SemanticResolverRuntime,
    resolve_semantic_runtime,
    semantic_thresholds_sha256,
)
from src.fact_extraction.fact_extractor import extract_facts_file  # noqa: E402
from src.paired_claims.claim_generator import (  # noqa: E402
    generate_paired_claims_file,
)
from src.paired_claims.validator import VALIDATOR_VERSION  # noqa: E402
from src.query_generation.paired_query_builder import (  # noqa: E402
    generate_paired_queries_file,
)
from src.query_generation.stealth_filter import (  # noqa: E402
    filter_stealth_queries,
)
from src.utils.hash import sha256_file, sha256_obj, sha256_text  # noqa: E402
from src.prepare.splitter import deduplicate_complete_sources  # noqa: E402
from src.prepare.entity_policy_release import (  # noqa: E402
    FORMAL_SCAN_PROTOCOL as ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
    validate_release_gate as validate_entity_policy_release_gate,
)
from src.prepare.formal_evidence_scope import (  # noqa: E402
    FORMAL_EVIDENCE_SCOPE_SHA256,
    FORMAL_EVIDENCE_SCOPE_VERSION,
)
from src.prepare.formal_dataset_role_scope import (  # noqa: E402
    ENRON_CAPACITY_PROMOTION_PROTOCOL,
    FORMAL_DATASET_ROLE_SCOPE_SHA256,
    FORMAL_DATASET_ROLE_SCOPE_VERSION,
    FORMAL_SCAN_ALLOWED_DATASETS,
    validate_primary_formal_dataset,
)
from src.prepare.enron_capacity_role import (  # noqa: E402
    ENRON_CAPACITY_ROLE_SHA256,
    ENRON_CAPACITY_ROLE_VERSION,
    ENRON_CAPACITY_STUDY_PROTOCOL,
    enron_capacity_role_metadata,
    enron_capacity_role_payload,
    validate_bound_enron_pilot_report,
    validate_enron_capacity_role_metadata,
)
from src.utils.io import (  # noqa: E402
    ensure_dir,
    load_yaml,
    read_json,
    read_jsonl,
    resolve_path,
    write_json,
    write_jsonl,
    write_jsonl_atomic,
)


V3_SCAN_PROTOCOL = "v6_3_precision_cascade_fixed_double_pool_v3"
V4_SCAN_PROTOCOL = "v6_3_precision_cascade_ranked_expandable_pool_v4"
V21_SCAN_PROTOCOL = "v21_full_rescan"
V21_ENRON_FULL_SCAN_PROTOCOL = "v21_enron_full_corpus_fixed_pool_v1"
ENRON_CAPACITY_SCAN_PROTOCOL = ENRON_CAPACITY_STUDY_PROTOCOL
BUDGET6_RELEASE_SCAN_PROTOCOL = "v6_3_rc1_budget6_release_v1"
ATTACK_FIRST_RC2_RELEASE_SCAN_PROTOCOL = (
    "v6_3_attack_first_rc2_budget6_release_v1"
)
ENTITY_POLICY_FORMAL_CLAIM_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_claim_eligibility_v21_entity_policy_r1"
)
ENTITY_POLICY_FORMAL_QUERY_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_query_eligibility_v21_entity_policy_r1_"
    "unique_query_text"
)
SCAN_PROTOCOL = V3_SCAN_PROTOCOL
V3_CLAIM_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_claim_eligibility_v6_3_precision_cascade_"
    "fixed_double_pool_v3"
)
V3_QUERY_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_query_eligibility_v6_3_precision_cascade_"
    "fixed_double_pool_v3_unique_query_text"
)
V4_CLAIM_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_claim_eligibility_v6_3_precision_cascade_"
    "ranked_expandable_pool_v4"
)
V4_QUERY_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_query_eligibility_v6_3_precision_cascade_"
    "ranked_expandable_pool_v4_unique_query_text"
)
V21_CLAIM_ELIGIBILITY_PROTOCOL = "pre_split_local_claim_eligibility_v21"
V21_QUERY_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_query_eligibility_v21_unique_query_text"
)
V21_ENRON_FULL_CLAIM_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_claim_eligibility_v21_enron_full_fixed_pool_v1"
)
V21_ENRON_FULL_QUERY_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_query_eligibility_v21_enron_full_"
    "fixed_pool_v1_unique_query_text"
)
ENRON_CAPACITY_CLAIM_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_claim_eligibility_v21_enron_capacity_fixed_pool_r2"
)
ENRON_CAPACITY_QUERY_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_query_eligibility_v21_enron_capacity_"
    "fixed_pool_r2_unique_query_text"
)
BUDGET6_RELEASE_CLAIM_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_claim_eligibility_v6_3_rc1_budget6_release_v1"
)
BUDGET6_RELEASE_QUERY_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_query_eligibility_v6_3_rc1_budget6_"
    "release_v1_unique_query_text"
)
ATTACK_FIRST_RC2_RELEASE_CLAIM_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_claim_eligibility_v6_3_attack_first_rc2_"
    "budget6_release_v1"
)
ATTACK_FIRST_RC2_RELEASE_QUERY_ELIGIBILITY_PROTOCOL = (
    "pre_split_local_query_eligibility_v6_3_attack_first_rc2_"
    "budget6_release_v1_unique_query_text"
)
CLAIM_ELIGIBILITY_PROTOCOL = V3_CLAIM_ELIGIBILITY_PROTOCOL
QUERY_ELIGIBILITY_PROTOCOL = V3_QUERY_ELIGIBILITY_PROTOCOL
FORMAL_GROUP = "Eligibility_Candidate"
SAFE_METADATA_FIELDS = frozenset(
    {
        "entity_count",
        "entity_counts",
        "entity_density",
        "has_contract_term",
        "has_date",
        "has_medical_value",
        "has_money",
        "has_org",
        "has_percent",
        "length",
    }
)


def configured_release_protocol(config: dict[str, Any]) -> str:
    """Return the promoted release protocol while preserving old configs."""

    return str(
        config.get("release_protocol")
        or config.get("protocol")
        or ""
    )


def _eligibility_protocols(scan_protocol: str) -> tuple[str, str]:
    if scan_protocol == V3_SCAN_PROTOCOL:
        return (
            V3_CLAIM_ELIGIBILITY_PROTOCOL,
            V3_QUERY_ELIGIBILITY_PROTOCOL,
        )
    if scan_protocol == V4_SCAN_PROTOCOL:
        return (
            V4_CLAIM_ELIGIBILITY_PROTOCOL,
            V4_QUERY_ELIGIBILITY_PROTOCOL,
        )
    if scan_protocol == V21_SCAN_PROTOCOL:
        return (
            V21_CLAIM_ELIGIBILITY_PROTOCOL,
            V21_QUERY_ELIGIBILITY_PROTOCOL,
        )
    if scan_protocol == V21_ENRON_FULL_SCAN_PROTOCOL:
        return (
            V21_ENRON_FULL_CLAIM_ELIGIBILITY_PROTOCOL,
            V21_ENRON_FULL_QUERY_ELIGIBILITY_PROTOCOL,
        )
    if scan_protocol == ENRON_CAPACITY_SCAN_PROTOCOL:
        return (
            ENRON_CAPACITY_CLAIM_ELIGIBILITY_PROTOCOL,
            ENRON_CAPACITY_QUERY_ELIGIBILITY_PROTOCOL,
        )
    if scan_protocol == BUDGET6_RELEASE_SCAN_PROTOCOL:
        return (
            BUDGET6_RELEASE_CLAIM_ELIGIBILITY_PROTOCOL,
            BUDGET6_RELEASE_QUERY_ELIGIBILITY_PROTOCOL,
        )
    if scan_protocol == ATTACK_FIRST_RC2_RELEASE_SCAN_PROTOCOL:
        return (
            ATTACK_FIRST_RC2_RELEASE_CLAIM_ELIGIBILITY_PROTOCOL,
            ATTACK_FIRST_RC2_RELEASE_QUERY_ELIGIBILITY_PROTOCOL,
        )
    if scan_protocol == ENTITY_POLICY_FORMAL_SCAN_PROTOCOL:
        return (
            ENTITY_POLICY_FORMAL_CLAIM_ELIGIBILITY_PROTOCOL,
            ENTITY_POLICY_FORMAL_QUERY_ELIGIBILITY_PROTOCOL,
        )
    if scan_protocol == ENRON_CAPACITY_PROMOTION_PROTOCOL:
        return (
            ENRON_CAPACITY_PROMOTION_PROTOCOL,
            ENRON_CAPACITY_PROMOTION_PROTOCOL,
        )
    raise RuntimeError(f"Unsupported eligibility scan protocol: {scan_protocol}")


def _validate_dataset_protocol(dataset: str, scan_protocol: str) -> None:
    allowed = {
        V3_SCAN_PROTOCOL: {"edgar", "pubmed"},
        V4_SCAN_PROTOCOL: {"enron"},
        V21_SCAN_PROTOCOL: {"edgar", "enron", "pubmed"},
        V21_ENRON_FULL_SCAN_PROTOCOL: {"enron"},
        ENRON_CAPACITY_SCAN_PROTOCOL: {"enron"},
        BUDGET6_RELEASE_SCAN_PROTOCOL: {"edgar", "enron", "pubmed"},
        ATTACK_FIRST_RC2_RELEASE_SCAN_PROTOCOL: {
            "edgar",
            "enron",
            "pubmed",
        },
        ENTITY_POLICY_FORMAL_SCAN_PROTOCOL: set(FORMAL_SCAN_ALLOWED_DATASETS),
        ENRON_CAPACITY_PROMOTION_PROTOCOL: {"enron"},
    }
    if dataset not in allowed.get(scan_protocol, set()):
        raise RuntimeError(
            "Eligibility scan protocol/dataset mismatch: "
            f"dataset={dataset!r} protocol={scan_protocol!r}"
        )


def validate_formal_eligibility_manifest(
    manifest: dict[str, Any],
    *,
    dataset: str,
    required_sources: int = 1250,
    checkpoint_hash_validator: Callable[[Path], str] = sha256_file,
) -> set[str]:
    """验证正式 split/promotion 共同依赖的容量与完整性门禁。"""

    if manifest.get("dataset") != dataset:
        raise RuntimeError("Eligibility dataset mismatch")
    scan_protocol = str(manifest.get("scan_protocol") or "")
    if scan_protocol == ENRON_CAPACITY_SCAN_PROTOCOL:
        raise RuntimeError(
            "Enron capacity boundary evidence cannot enter formal promotion"
        )
    _validate_dataset_protocol(dataset, scan_protocol)
    _, query_protocol = _eligibility_protocols(scan_protocol)
    if manifest.get("protocol") != query_protocol:
        raise RuntimeError("Eligibility protocol mismatch")
    if (
        manifest.get("capacity_status") != "passed"
        or manifest.get("stop_status") != "target_reached"
        or manifest.get("deduplicate_complete_sources") is not True
    ):
        raise RuntimeError(
            "Eligibility capacity/deduplication gate failed"
        )
    eligible_values = [
        str(value) for value in manifest.get("eligible_source_keys", [])
    ]
    eligible = set(eligible_values)
    if (
        len(eligible) < required_sources
        or len(eligible_values) != len(eligible)
        or int(manifest.get("eligible_source_count", -1)) != len(eligible)
        or sha256_obj(sorted(eligible)) != manifest.get("whitelist_hash")
    ):
        raise RuntimeError("Eligibility whitelist integrity/capacity failed")
    if scan_protocol == ENRON_CAPACITY_PROMOTION_PROTOCOL:
        if (
            manifest.get("dataset_role") != "capacity_qualified_primary"
            or manifest.get("main_table_eligible") is not True
            or manifest.get("main_table_disclosure_required") is not True
            or manifest.get("prior_pilot_status") != "failed"
            or int(manifest.get("capacity_eligible_source_count", -1))
            < required_sources
            or len(eligible) != required_sources
        ):
            raise RuntimeError("Enron capacity promotion role gate failed")
    elif scan_protocol in {
        V3_SCAN_PROTOCOL,
        V21_SCAN_PROTOCOL,
        V21_ENRON_FULL_SCAN_PROTOCOL,
        BUDGET6_RELEASE_SCAN_PROTOCOL,
        ATTACK_FIRST_RC2_RELEASE_SCAN_PROTOCOL,
    }:
        if (
            manifest.get("scan_full_candidate_pool") is not True
            or int(manifest.get("scanned_source_count", -1))
            != int(
                manifest.get(
                    "effective_candidate_pool_source_count",
                    -2,
                )
            )
        ):
            raise RuntimeError("Eligibility fixed-pool gate failed")
    else:
        if (
            manifest.get("scan_full_candidate_pool") is not False
            or manifest.get("exact_target_stop") is not True
            or len(eligible) != required_sources
            or int(manifest.get("target_query_eligible_sources", -1))
            != required_sources
            or int(manifest.get("retained_source_end", -1))
            != int(manifest.get("scanned_source_count", -2))
            or int(manifest.get("processed_source_count", -1))
            < int(manifest.get("retained_source_end", -2))
            or not manifest.get("retained_prefix_source_keys_hash")
        ):
            raise RuntimeError(
                "Eligibility exact retained-prefix gate failed"
            )
    if (
        int(manifest.get("minimum_stealth_pairs", 0)) != 3
        or int(manifest.get("queries_per_source", 0)) != 6
        or manifest.get("query_text_uniqueness_enforced") is not True
    ):
        raise RuntimeError("Eligibility fixed query budget failed")
    checkpoint_path = Path(
        str(manifest.get("scan_checkpoint_path") or "")
    )
    if (
        not checkpoint_path.is_file()
        or checkpoint_hash_validator(checkpoint_path)
        != manifest.get("scan_checkpoint_sha256")
    ):
        raise RuntimeError("Eligibility checkpoint hash drift")
    return eligible


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze or execute the preregistered v6.3 precision-cascade "
            "eligibility wave scan."
        )
    )
    parser.add_argument(
        "--dataset",
        choices=["edgar", "enron", "pubmed"],
        required=True,
    )
    parser.add_argument(
        "--data-config",
        default=str(PROJECT_ROOT / "configs" / "data_v6_3.yaml"),
    )
    parser.add_argument(
        "--attack-config",
        default=str(PROJECT_ROOT / "configs" / "pcv_attack_v6_3.yaml"),
    )
    parser.add_argument(
        "--scan-config",
        default=None,
        help=(
            "独立 eligibility scan YAML；用于 Enron v4，避免修改 "
            "data_v6_3.yaml 及 PubMed checkpoint 身份。"
        ),
    )
    parser.add_argument("--processed-path", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--release-gate",
        default=None,
        help=(
            "Passed v21 entity-policy release gate. Required only by "
            f"{ENTITY_POLICY_FORMAL_SCAN_PROTOCOL}."
        ),
    )
    parser.add_argument(
        "--cap",
        type=int,
        choices=[5, 8, 12],
        default=5,
        help="每个 source 的确定性 chunk 上限；只能按预注册的 5/8/12 顺序使用。",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Validate and continue an already frozen scan plan.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Run local wave pipelines. Without this flag the command only "
            "freezes or validates the scan plan."
        ),
    )
    parser.add_argument(
        "--max-new-waves",
        type=int,
        default=None,
        help=(
            "Operational pause after this many newly completed waves; resume "
            "continues the same preregistered prefix."
        ),
    )
    parser.add_argument(
        "--manual-user-owned-capacity-run",
        action="store_true",
        help=(
            "Explicitly acknowledge that a v21_r2 Enron capacity command is "
            "a user-owned local long task."
        ),
    )
    return parser.parse_args()


def canonical_source_key(row: dict[str, Any]) -> str:
    """Return the membership-unit identity without consulting any label."""

    source_id = str(row.get("source_id") or row.get("doc_id") or "").strip()
    source_path = str(row.get("source_path") or "").strip()
    if source_id or source_path:
        return f"{source_path}::{source_id}"
    return str(row.get("text_hash") or "").strip()


def _candidate_row(
    row: dict[str, Any],
    dataset: str,
    source_key: str,
) -> dict[str, Any]:
    doc_id = str(row.get("doc_id") or row.get("id") or "").strip()
    text = str(row.get("text") or "")
    text_hash = str(row.get("text_hash") or sha256_text(text))
    stable_id = sha256_text(
        "\0".join((dataset, source_key, doc_id, text_hash))
    )[:24]
    metadata = row.get("metadata")
    safe_metadata = (
        {
            str(key): value
            for key, value in metadata.items()
            if str(key) in SAFE_METADATA_FIELDS
        }
        if isinstance(metadata, dict)
        else {}
    )
    return {
        "audit_id": f"eligibility_{dataset}_{stable_id}",
        "doc_id": doc_id or f"{dataset}_{stable_id}",
        "source_id": row.get("source_id") or doc_id,
        "source_path": row.get("source_path"),
        "source_key": source_key,
        "dataset": dataset,
        "group": FORMAL_GROUP,
        "text": text,
        "text_hash": text_hash,
        "chunk_index": row.get("chunk_index"),
        "membership_unit": row.get("membership_unit"),
        "metadata": safe_metadata,
    }


def freeze_source_plan(
    rows: Iterable[dict[str, Any]],
    dataset: str,
    *,
    selection_seed: int,
    max_chunks_per_source: int,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Freeze stable source order and stable within-source chunk probes."""

    if max_chunks_per_source < 1:
        raise ValueError("max_chunks_per_source must be positive")
    buckets: dict[
        str,
        list[tuple[str, str, str, dict[str, Any]]],
    ] = {}
    input_rows = 0
    for row in rows:
        input_rows += 1
        source_key = canonical_source_key(row)
        if not source_key:
            raise RuntimeError("Processed row has no stable source identity")
        candidate = _candidate_row(row, dataset, source_key)
        chunk_rank = sha256_text(
            "\0".join(
                (
                    str(selection_seed),
                    dataset,
                    source_key,
                    str(candidate["doc_id"]),
                    str(candidate["text_hash"]),
                    str(candidate["text"]),
                )
            )
        )
        buckets.setdefault(source_key, []).append(
            (
                chunk_rank,
                str(candidate["doc_id"]),
                str(candidate["text_hash"]),
                candidate,
            )
        )

    source_order = sorted(
        buckets,
        key=lambda source_key: (
            sha256_text(
                "\0".join(
                    (str(selection_seed), dataset, source_key)
                )
            ),
            source_key,
        ),
    )
    candidates: list[dict[str, Any]] = []
    seen_audit_ids: set[str] = set()
    for source_key in source_order:
        ranked = sorted(buckets[source_key])
        for _, _, _, candidate in ranked[:max_chunks_per_source]:
            audit_id = str(candidate["audit_id"])
            if audit_id in seen_audit_ids:
                raise RuntimeError(
                    f"Duplicate deterministic candidate audit_id: {audit_id}"
                )
            seen_audit_ids.add(audit_id)
            candidates.append(candidate)
    return source_order, candidates, {
        "input_row_count": input_rows,
        "source_count": len(source_order),
        "probe_row_count": len(candidates),
        "probe_source_count": len(source_order),
    }


def freeze_candidate_pool_prefix(
    source_universe_order: list[str],
    universe_candidates: list[dict[str, Any]],
    *,
    candidate_pool_target_sources: int,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Freeze the first min(universe, target) sources without duplication."""

    if candidate_pool_target_sources < 1:
        raise ValueError("candidate_pool_target_sources must be positive")
    if len(source_universe_order) != len(set(source_universe_order)):
        raise RuntimeError("Source universe order contains duplicates")
    source_order = source_universe_order[:candidate_pool_target_sources]
    source_pool = set(source_order)
    candidates = [
        row
        for row in universe_candidates
        if str(row.get("source_key") or "") in source_pool
    ]
    candidate_sources = {
        str(row.get("source_key") or "") for row in candidates
    }
    if candidate_sources != source_pool:
        raise RuntimeError("Candidate pool is missing a frozen source")
    return source_order, candidates, {
        "source_universe_count": len(source_universe_order),
        "source_universe_probe_row_count": len(universe_candidates),
        "effective_candidate_pool_source_count": len(source_order),
        "candidate_pool_shortfall_count": max(
            0,
            candidate_pool_target_sources - len(source_order),
        ),
        "candidate_pool_uses_complete_source_universe": (
            len(source_order) < candidate_pool_target_sources
        ),
    }


def rank_source_universe_by_local_quality(
    source_universe_order: list[str],
    universe_candidates: list[dict[str, Any]],
    *,
    dataset: str,
    max_entities_per_chunk: int,
    guarantee_min_entities_per_chunk: int,
    high_quality_attackability_threshold: float,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """只用确定性规则候选排序 source，不运行模型或读取标签。"""

    if dataset != "enron":
        raise RuntimeError("Ranked expandable pool is Enron-only")
    if len(source_universe_order) != len(set(source_universe_order)):
        raise RuntimeError("Source universe order contains duplicates")
    if max_entities_per_chunk < 1:
        raise ValueError("max_entities_per_chunk must be positive")
    if guarantee_min_entities_per_chunk < 1:
        raise ValueError(
            "guarantee_min_entities_per_chunk must be positive"
        )
    if not 0.0 <= high_quality_attackability_threshold <= 1.0:
        raise ValueError(
            "high_quality_attackability_threshold must be in [0, 1]"
        )

    candidates_by_source: dict[str, list[dict[str, Any]]] = {
        source_key: [] for source_key in source_universe_order
    }
    for row in universe_candidates:
        source_key = str(row.get("source_key") or "")
        if source_key not in candidates_by_source:
            raise RuntimeError(
                "Quality-ranking candidate is outside source universe"
            )
        candidates_by_source[source_key].append(row)
    if any(not rows for rows in candidates_by_source.values()):
        raise RuntimeError("Quality ranking is missing a source candidate")

    extractor = EntityExtractor(enable_ner=False)
    quality_rows: list[dict[str, Any]] = []
    for source_key in source_universe_order:
        unique_facts: set[tuple[str, str, str]] = set()
        high_quality_facts: set[tuple[str, str, str]] = set()
        entity_types: set[str] = set()
        effective_text_length = 0
        for row in candidates_by_source[source_key]:
            text = str(row.get("text") or "")
            effective_text_length += len("".join(text.split()))
            entities = extractor.extract(
                text,
                max_entities=max_entities_per_chunk,
                guarantee_min=guarantee_min_entities_per_chunk,
            )
            for entity in entities:
                key = (
                    str(entity.get("type") or ""),
                    " ".join(
                        str(entity.get("text") or "").casefold().split()
                    ),
                    " ".join(
                        str(entity.get("sentence") or "").casefold().split()
                    ),
                )
                if not key[0] or not key[1]:
                    continue
                unique_facts.add(key)
                entity_types.add(key[0])
                if (
                    float(entity.get("attackability_score", 0.0))
                    >= high_quality_attackability_threshold
                ):
                    high_quality_facts.add(key)
        tie_break_sha256 = sha256_text(
            "\0".join((dataset, source_key))
        )
        quality_rows.append(
            {
                "source_key": source_key,
                "potential_fact_count": len(unique_facts),
                "high_quality_candidate_count": len(
                    high_quality_facts
                ),
                "entity_type_diversity": len(entity_types),
                "effective_text_length": effective_text_length,
                "tie_break_sha256": tie_break_sha256,
            }
        )

    quality_rows.sort(
        key=lambda row: (
            -int(row["potential_fact_count"]),
            -int(row["high_quality_candidate_count"]),
            -int(row["entity_type_diversity"]),
            -int(row["effective_text_length"]),
            str(row["tie_break_sha256"]),
            str(row["source_key"]),
        )
    )
    ranked_order = [str(row["source_key"]) for row in quality_rows]
    ranked_candidates = [
        row
        for source_key in ranked_order
        for row in candidates_by_source[source_key]
    ]
    return ranked_order, ranked_candidates, quality_rows


def validate_historical_rank_replay(
    ranked_source_order: list[str],
    *,
    source_order_path: Path,
    query_eligibility_path: Path,
    top_k: int,
    minimum_eligible_covered: int,
    minimum_eligible_recall: float,
) -> dict[str, Any]:
    """回放旧随机池只作为排序门禁，不参与任何 source 的排序得分。"""

    old_order_payload = read_json(source_order_path)
    old_order = {
        str(value)
        for value in old_order_payload.get("source_order", [])
    }
    old_eligibility = read_json(query_eligibility_path)
    old_eligible = {
        str(value)
        for value in old_eligibility.get("eligible_source_keys", [])
    }
    if not old_eligible or not old_eligible.issubset(old_order):
        raise RuntimeError("Historical rank replay input is inconsistent")
    ranked_prefix = set(ranked_source_order[:top_k])
    overlap = ranked_prefix & old_order
    covered = len(ranked_prefix & old_eligible)
    recall = covered / len(old_eligible)
    if (
        covered < minimum_eligible_covered
        or recall < minimum_eligible_recall
    ):
        raise RuntimeError(
            "Historical rank replay gate failed: "
            f"covered={covered}/{len(old_eligible)} recall={recall:.6f}"
        )
    return {
        "source_order_path": str(source_order_path.resolve()),
        "source_order_sha256": sha256_file(source_order_path),
        "query_eligibility_path": str(query_eligibility_path.resolve()),
        "query_eligibility_sha256": sha256_file(query_eligibility_path),
        "top_k": top_k,
        "ranked_random_pool_overlap": len(overlap),
        "historical_eligible_source_count": len(old_eligible),
        "historical_eligible_covered": covered,
        "historical_eligible_recall": round(recall, 8),
        "minimum_eligible_covered": minimum_eligible_covered,
        "minimum_eligible_recall": minimum_eligible_recall,
        "status": "passed",
    }


def wave_slices(source_count: int, wave_size: int) -> list[tuple[int, int]]:
    if wave_size < 1:
        raise ValueError("wave_size must be positive")
    return [
        (start, min(source_count, start + wave_size))
        for start in range(0, source_count, wave_size)
    ]


def validate_fixed_budget_query_rows(
    rows: Iterable[dict[str, Any]],
    *,
    allowed_source_keys: set[str],
    required_pairs: int,
) -> tuple[list[str], dict[str, Any]]:
    """Require the configured complete-pair and unique-query budget per source."""

    if required_pairs < 1:
        raise ValueError("required_pairs must be positive")
    by_source: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        source_key = str(row.get("source_key") or "")
        if source_key not in allowed_source_keys:
            raise RuntimeError(
                f"Stealth query references a source outside its wave: {source_key!r}"
            )
        if str(row.get("group") or "") != FORMAL_GROUP:
            raise RuntimeError(
                "Wave eligibility must run before membership-group assignment"
            )
        pair_id = str(row.get("pair_id") or "")
        query_type = str(row.get("query_type") or "default")
        if not pair_id:
            raise RuntimeError("Stealth query is missing pair_id")
        by_source.setdefault(source_key, {}).setdefault(
            f"{pair_id}::{query_type}",
            [],
        ).append(row)

    query_counts: Counter[int] = Counter()
    eligible: list[str] = []
    selected_pair_ids: list[str] = []
    for source_key, pairs in sorted(by_source.items()):
        if len(pairs) != required_pairs:
            raise RuntimeError(
                f"Fixed-budget source {source_key!r} has {len(pairs)} "
                f"pairs; expected exactly {required_pairs}"
            )
        query_texts: list[str] = []
        for pair_key, members in sorted(pairs.items()):
            if len(members) != 2:
                raise RuntimeError(
                    f"Fixed-budget pair {pair_key!r} is not two-sided"
                )
            if sorted(str(item.get("claim_type")) for item in members) != [
                "counterfactual",
                "true",
            ]:
                raise RuntimeError(
                    f"Fixed-budget pair {pair_key!r} lacks Q+/Q- sides"
                )
            pair_queries = [str(item.get("query") or "") for item in members]
            if len(set(pair_queries)) != 2 or not all(pair_queries):
                raise RuntimeError(
                    f"Fixed-budget pair {pair_key!r} has duplicate/empty query text"
                )
            query_texts.extend(pair_queries)
            selected_pair_ids.append(f"{source_key}::{pair_key}")
        expected_queries = required_pairs * 2
        if (
            len(query_texts) != expected_queries
            or len(set(query_texts)) != expected_queries
        ):
            raise RuntimeError(
                f"Fixed-budget source {source_key!r} does not have "
                f"{expected_queries} unique query texts"
            )
        query_counts[len(query_texts)] += 1
        eligible.append(source_key)
    return eligible, {
        "pairs_per_source": required_pairs,
        "queries_per_source": required_pairs * 2,
        "eligible_sources": len(eligible),
        "selected_pairs": len(selected_pair_ids),
        "query_text_uniqueness_enforced": True,
        "query_count_distribution": dict(sorted(query_counts.items())),
        "fixed_budget_plan_hash": sha256_obj(sorted(selected_pair_ids)),
    }


WaveProcessor = Callable[
    [int, list[str], int, int],
    dict[str, Any],
]
WaveCompletionHook = Callable[[dict[str, Any]], None]


def _record_wave_retained_boundary(
    result: dict[str, Any],
    *,
    processed_source_end: int,
    retained_source_end: int,
    processed_wave_source_keys: list[str],
    retained_wave_source_keys: list[str],
    processed_eligible_source_keys: list[str],
    retained_eligible_source_keys: list[str],
) -> dict[str, Any]:
    """在 checkpoint 前冻结 terminal wave 的 processed/retained 边界。"""

    updated = dict(result)
    manifest_value = updated.get("wave_manifest_path")
    if manifest_value:
        manifest_path = Path(str(manifest_value))
        if (
            not manifest_path.is_file()
            or sha256_file(manifest_path)
            != updated.get("wave_manifest_sha256")
        ):
            raise RuntimeError(
                "Wave manifest drift before retained-boundary freeze"
            )
        manifest = read_json(manifest_path)
        retained_source_set = set(retained_wave_source_keys)
        processed_claim_eligible = [
            str(value)
            for value in manifest.get(
                "claim_eligible_source_keys",
                [],
            )
        ]
        retained_claim_eligible = sorted(
            set(processed_claim_eligible) & retained_source_set
        )
        processed_fixed_budget = dict(
            manifest.get("fixed_budget") or {}
        )
        retained_fixed_budget = processed_fixed_budget
        stealth_output = (
            manifest.get("outputs", {}).get("stealth", {})
        )
        stealth_path_value = stealth_output.get("path")
        required_pairs = int(
            processed_fixed_budget.get("pairs_per_source", 0)
        )
        if stealth_path_value and required_pairs > 0:
            retained_stealth_rows = (
                row
                for row in read_jsonl(Path(str(stealth_path_value)))
                if str(row.get("source_key") or "")
                in retained_source_set
            )
            _, retained_fixed_budget = validate_fixed_budget_query_rows(
                retained_stealth_rows,
                allowed_source_keys=retained_source_set,
                required_pairs=required_pairs,
            )
        manifest.update(
            {
                "processed_source_end": processed_source_end,
                "retained_source_end": retained_source_end,
                "processed_wave_source_keys": processed_wave_source_keys,
                "processed_wave_source_keys_hash": sha256_obj(
                    processed_wave_source_keys
                ),
                "retained_wave_source_keys": retained_wave_source_keys,
                "retained_wave_source_keys_hash": sha256_obj(
                    retained_wave_source_keys
                ),
                "processed_eligible_source_keys": (
                    processed_eligible_source_keys
                ),
                "processed_eligible_source_count": len(
                    processed_eligible_source_keys
                ),
                "processed_claim_eligible_source_keys": (
                    processed_claim_eligible
                ),
                "processed_claim_eligible_source_count": len(
                    processed_claim_eligible
                ),
                "claim_eligible_source_keys": retained_claim_eligible,
                "claim_eligible_source_count": len(
                    retained_claim_eligible
                ),
                "processed_fixed_budget": processed_fixed_budget,
                "fixed_budget": retained_fixed_budget,
                "eligible_source_keys": retained_eligible_source_keys,
                "eligible_source_count": len(
                    retained_eligible_source_keys
                ),
            }
        )
        identity = {
            key: value
            for key, value in manifest.items()
            if key not in {"created_at", "wave_identity_sha256"}
        }
        manifest["wave_identity_sha256"] = sha256_obj(identity)
        write_json(manifest, manifest_path)
        updated["wave_manifest_sha256"] = sha256_file(manifest_path)
        updated["wave_identity_sha256"] = manifest[
            "wave_identity_sha256"
        ]
    return updated


def execute_wave_schedule(
    source_order: list[str],
    *,
    wave_size: int,
    target_query_eligible_sources: int,
    required_formal_sources: int,
    process_wave: WaveProcessor,
    completed_waves: Iterable[dict[str, Any]] = (),
    on_wave_complete: WaveCompletionHook | None = None,
    max_new_waves: int | None = None,
    scan_full_candidate_pool: bool = False,
    exact_target_stop: bool = False,
) -> dict[str, Any]:
    """执行连续 source 前缀；v4 在第 N 个合格 source 处精确截断。"""

    if wave_size < 1:
        raise ValueError("wave_size must be positive")
    if target_query_eligible_sources < 1:
        raise ValueError("target_query_eligible_sources must be positive")
    if required_formal_sources < 1:
        raise ValueError("required_formal_sources must be positive")
    if target_query_eligible_sources < required_formal_sources:
        raise ValueError("target must cover required formal sources")
    if max_new_waves is not None and max_new_waves < 1:
        raise ValueError("max_new_waves must be positive")

    completed_records = [dict(record) for record in completed_waves]
    records: list[dict[str, Any]] = []
    eligible: set[str] = set()
    scanned_end = 0
    processed_end = 0
    for expected_index, raw_record in enumerate(completed_records):
        record = dict(raw_record)
        start = int(record.get("source_start", -1))
        retained_end = int(
            record.get("retained_source_end", record.get("source_end", -1))
        )
        current_processed_end = int(
            record.get("processed_source_end", record.get("source_end", -1))
        )
        if (
            int(record.get("wave_index", -1)) != expected_index
            or start != scanned_end
            or retained_end <= start
            or current_processed_end < retained_end
            or current_processed_end > len(source_order)
        ):
            raise RuntimeError("Completed wave checkpoint is not contiguous")
        expected_processed_hash = sha256_obj(
            source_order[start:current_processed_end]
        )
        actual_processed_hash = record.get(
            "processed_wave_source_keys_hash",
            record.get("wave_source_keys_hash"),
        )
        if actual_processed_hash != expected_processed_hash:
            raise RuntimeError("Completed wave source-prefix hash drift")
        expected_retained_hash = sha256_obj(
            source_order[start:retained_end]
        )
        actual_retained_hash = record.get(
            "retained_wave_source_keys_hash",
            record.get("wave_source_keys_hash"),
        )
        if actual_retained_hash != expected_retained_hash:
            raise RuntimeError("Completed wave retained-prefix hash drift")
        wave_eligible = {
            str(value) for value in record.get("eligible_source_keys", [])
        }
        if not wave_eligible.issubset(
            set(source_order[start:retained_end])
        ):
            raise RuntimeError("Completed wave contains out-of-wave eligibility")
        if current_processed_end > retained_end and (
            expected_index != len(completed_records) - 1
        ):
            raise RuntimeError(
                "A truncated terminal wave cannot have a successor"
            )
        eligible.update(wave_eligible)
        records.append(record)
        scanned_end = retained_end
        processed_end = current_processed_end

    def state(status: str, reason: str) -> dict[str, Any]:
        payload = {
            "stop_status": status,
            "stop_reason": reason,
            "completed_waves": list(records),
            "scanned_source_count": scanned_end,
            "scanned_prefix_source_keys_hash": sha256_obj(
                source_order[:scanned_end]
            ),
            "eligible_source_keys": sorted(eligible),
            "eligible_source_count": len(eligible),
            "target_query_eligible_sources": (
                target_query_eligible_sources
            ),
            "required_formal_sources": required_formal_sources,
            "scan_full_candidate_pool": scan_full_candidate_pool,
        }
        if exact_target_stop:
            payload.update(
                {
                    "exact_target_stop": True,
                    "processed_source_count": processed_end,
                    "processed_prefix_source_keys_hash": sha256_obj(
                        source_order[:processed_end]
                    ),
                    "retained_source_end": scanned_end,
                    "retained_prefix_source_keys_hash": sha256_obj(
                        source_order[:scanned_end]
                    ),
                }
            )
        return payload

    if (
        exact_target_stop
        and len(eligible) == target_query_eligible_sources
    ):
        return state(
            "target_reached",
            "exact_target_reached_at_retained_source_boundary",
        )
    if (
        not exact_target_stop
        and not scan_full_candidate_pool
        and len(eligible) >= target_query_eligible_sources
    ):
        return state(
            "target_reached",
            "target_reached_after_complete_wave",
        )
    if scanned_end == len(source_order):
        status = (
            "target_reached"
            if len(eligible) >= required_formal_sources
            else "insufficient"
        )
        return state(
            status,
            (
                "fixed_candidate_pool_exhausted_with_required_capacity"
                if status == "target_reached"
                else "fixed_candidate_pool_exhausted_below_required_capacity"
            ),
        )

    new_waves = 0
    slices = wave_slices(len(source_order), wave_size)
    next_wave_index = len(records)
    for wave_index in range(next_wave_index, len(slices)):
        start, end = slices[wave_index]
        if start != scanned_end:
            raise RuntimeError("Wave schedule does not match checkpoint prefix")
        wave_keys = source_order[start:end]
        result = dict(process_wave(wave_index, wave_keys, start, end))
        processed_wave_eligible = {
            str(value) for value in result.get("eligible_source_keys", [])
        }
        if not processed_wave_eligible.issubset(set(wave_keys)):
            raise RuntimeError("Wave processor returned out-of-wave source")
        retained_end = end
        retained_wave_keys = list(wave_keys)
        wave_eligible = set(processed_wave_eligible)
        if (
            exact_target_stop
            and len(eligible) + len(processed_wave_eligible)
            >= target_query_eligible_sources
        ):
            remaining = target_query_eligible_sources - len(eligible)
            ordered_wave_eligible = [
                source_key
                for source_key in wave_keys
                if source_key in processed_wave_eligible
            ]
            if remaining < 1 or remaining > len(ordered_wave_eligible):
                raise RuntimeError(
                    "Exact eligibility boundary cannot be located"
                )
            boundary_source = ordered_wave_eligible[remaining - 1]
            retained_end = start + wave_keys.index(boundary_source) + 1
            retained_wave_keys = source_order[start:retained_end]
            wave_eligible = processed_wave_eligible & set(
                retained_wave_keys
            )
            if len(wave_eligible) != remaining:
                raise RuntimeError(
                    "Exact eligibility boundary retained wrong count"
                )
        if exact_target_stop:
            result = _record_wave_retained_boundary(
                result,
                processed_source_end=end,
                retained_source_end=retained_end,
                processed_wave_source_keys=list(wave_keys),
                retained_wave_source_keys=list(retained_wave_keys),
                processed_eligible_source_keys=sorted(
                    processed_wave_eligible
                ),
                retained_eligible_source_keys=sorted(wave_eligible),
            )
            result["eligible_source_keys"] = sorted(wave_eligible)
        reserved = {
            "wave_index": wave_index,
            "source_start": start,
            "source_end": retained_end,
            "wave_source_keys_hash": sha256_obj(retained_wave_keys),
            "eligible_source_keys": sorted(wave_eligible),
        }
        if exact_target_stop:
            reserved.update(
                {
                    "processed_source_end": end,
                    "retained_source_end": retained_end,
                    "processed_wave_source_keys_hash": sha256_obj(
                        wave_keys
                    ),
                    "retained_wave_source_keys_hash": sha256_obj(
                        retained_wave_keys
                    ),
                }
            )
        for key, expected in reserved.items():
            if key in result and result[key] != expected:
                raise RuntimeError(
                    f"Wave processor drifted reserved field {key!r}"
                )
        record = {**result, **reserved}
        records.append(record)
        eligible.update(wave_eligible)
        scanned_end = retained_end
        processed_end = end
        new_waves += 1

        if (
            exact_target_stop
            and len(eligible) == target_query_eligible_sources
        ):
            current = state(
                "target_reached",
                "exact_target_reached_at_retained_source_boundary",
            )
        elif (
            not exact_target_stop
            and not scan_full_candidate_pool
            and len(eligible) >= target_query_eligible_sources
        ):
            current = state(
                "target_reached",
                "target_reached_after_complete_wave",
            )
        elif scanned_end == len(source_order):
            if len(eligible) >= required_formal_sources:
                current = state(
                    "target_reached",
                    (
                        "fixed_candidate_pool_exhausted_with_"
                        "required_capacity"
                    ),
                )
            else:
                current = state(
                    "insufficient",
                    (
                        "fixed_candidate_pool_exhausted_below_"
                        "required_capacity"
                    ),
                )
        elif max_new_waves is not None and new_waves >= max_new_waves:
            current = state(
                "paused",
                "operational_pause_after_complete_wave",
            )
        else:
            current = state("in_progress", "continue_next_wave")

        if on_wave_complete is not None:
            on_wave_complete(current)
        if current["stop_status"] != "in_progress":
            return current

    raise RuntimeError("Wave schedule ended without a terminal state")


def _validate_scan_config(
    config: dict[str, Any],
    *,
    selected_cap: int,
) -> dict[str, Any]:
    protocol = str(config.get("protocol") or "")
    if protocol == V3_SCAN_PROTOCOL:
        required = {
            "protocol": V3_SCAN_PROTOCOL,
            "selection_seed": 42,
            "wave_size": 250,
            "candidate_pool_multiplier": 2,
            "candidate_pool_target_sources": 2500,
            "candidate_pool_shortfall_policy": (
                "use_complete_source_universe"
            ),
            "scan_full_candidate_pool": True,
            "target_query_eligible_sources": 1250,
            "required_formal_sources": 1250,
            "max_chunks_per_source": 5,
            "fallback_chunk_caps": [8, 12],
            "minimum_valid_claims": 3,
            "minimum_stealth_pairs": 3,
            "deduplicate_complete_sources": True,
        }
    elif protocol == V21_SCAN_PROTOCOL:
        required = {
            "protocol": V21_SCAN_PROTOCOL,
            "selection_seed": 42,
            "wave_size": 250,
            "candidate_pool_multiplier": 2,
            "candidate_pool_target_sources": 4500,
            "candidate_pool_shortfall_policy": "fail",
            "scan_full_candidate_pool": True,
            "target_query_eligible_sources": 2250,
            "required_formal_sources": 2250,
            "max_chunks_per_source": 5,
            "fallback_chunk_caps": [8, 12],
            "minimum_valid_claims": 3,
            "minimum_stealth_pairs": 3,
            "deduplicate_complete_sources": True,
        }
    elif protocol == V21_ENRON_FULL_SCAN_PROTOCOL:
        required = {
            "protocol": V21_ENRON_FULL_SCAN_PROTOCOL,
            "selection_seed": 42,
            "wave_size": 250,
            "candidate_pool_multiplier": None,
            "candidate_pool_target_sources": 30000,
            "candidate_pool_shortfall_policy": "fail",
            "scan_full_candidate_pool": True,
            "target_query_eligible_sources": 2250,
            "required_formal_sources": 2250,
            "max_chunks_per_source": 5,
            "fallback_chunk_caps": [],
            "minimum_valid_claims": 3,
            "minimum_stealth_pairs": 3,
            "deduplicate_complete_sources": True,
            "sampling_manifest_path": (
                "artifacts/v21/enron_full/sampling/"
                "enron_sampling_manifest.json"
            ),
        }
    elif protocol == ENRON_CAPACITY_SCAN_PROTOCOL:
        required = {
            "protocol": ENRON_CAPACITY_SCAN_PROTOCOL,
            "dataset": "enron",
            "capacity_role_protocol_version": ENRON_CAPACITY_ROLE_VERSION,
            "capacity_role_protocol_sha256": ENRON_CAPACITY_ROLE_SHA256,
            "manual_execution_mode": "user_owned_long_task",
            "manual_execution_acknowledgement_required": True,
            "selection_seed": 42,
            "wave_size": 250,
            "candidate_pool_multiplier": None,
            "candidate_pool_target_sources": 35000,
            "candidate_pool_shortfall_policy": "fail",
            "scan_full_candidate_pool": True,
            "exact_target_stop": False,
            "target_query_eligible_sources": 2250,
            "required_formal_sources": 2250,
            "max_chunks_per_source": 5,
            "fallback_chunk_caps": [],
            "minimum_valid_claims": 3,
            "minimum_stealth_pairs": 3,
            "deduplicate_complete_sources": True,
            "sampling_manifest_path": (
                "artifacts/v21/enron_full/sampling/"
                "enron_sampling_manifest.json"
            ),
            "output_dir": (
                "artifacts/v21/enron_capacity_r2/eligibility/"
                "cap_5/enron"
            ),
            "upstream_processed": {
                "path": "artifacts/v21/enron_full/processed/enron.jsonl",
                "sha256": (
                    "47ef7d2fee45d519618dddc9a1be4be6aafcf69d862cd64f35a109081419a19e"
                ),
                "manifest_path": (
                    "artifacts/v21/enron_full/processed/"
                    "enron.manifest.json"
                ),
                "manifest_sha256": (
                    "d4dbecb2c7c842485b230c9ecb50a8f297413292d48e00754080ee0854079aa6"
                ),
                "unique_source_count": 62384,
            },
        }
    elif protocol == ENTITY_POLICY_FORMAL_SCAN_PROTOCOL:
        dataset = str(config.get("dataset") or "")
        validate_primary_formal_dataset(dataset)
        required = {
            "protocol": ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
            "dataset": dataset,
            "selection_seed": 42,
            "wave_size": 250,
            "candidate_pool_multiplier": None,
            "candidate_pool_target_sources": 4500,
            "candidate_pool_shortfall_policy": "fail",
            "scan_full_candidate_pool": False,
            "exact_target_stop": True,
            "target_query_eligible_sources": 2250,
            "required_formal_sources": 2250,
            "max_chunks_per_source": 5,
            "fallback_chunk_caps": [],
            "minimum_valid_claims": 3,
            "minimum_stealth_pairs": 3,
            "deduplicate_complete_sources": True,
            "sampling_manifest_path": None,
            "output_dir": (
                "artifacts/v21/formal_entity_policy_r2/eligibility/"
                f"cap_5/{dataset}"
            ),
        }
    elif protocol == V4_SCAN_PROTOCOL:
        required = {
            "protocol": V4_SCAN_PROTOCOL,
            "selection_seed": 42,
            "wave_size": 250,
            "candidate_pool_multiplier": 2,
            "candidate_pool_target_sources": 2500,
            "initial_priority_source_count": 2500,
            "extension_source_count": 250,
            "candidate_pool_shortfall_policy": "scan_complete_ranked_universe",
            "scan_full_candidate_pool": False,
            "exact_target_stop": True,
            "target_query_eligible_sources": 1250,
            "required_formal_sources": 1250,
            "max_chunks_per_source": 5,
            "fallback_chunk_caps": [],
            "minimum_valid_claims": 3,
            "minimum_stealth_pairs": 3,
            "deduplicate_complete_sources": True,
            "ranking": {
                "method": "local_rule_quality_lexicographic_v1",
                "metrics": [
                    "potential_fact_count",
                    "high_quality_candidate_count",
                    "entity_type_diversity",
                    "effective_text_length",
                    "sha256_tie_break",
                ],
                "max_entities_per_chunk": 12,
                "guarantee_min_entities_per_chunk": 8,
                "high_quality_attackability_threshold": 0.6,
            },
            "historical_replay": {
                "top_k": 2500,
                "minimum_eligible_covered": 254,
                "minimum_eligible_recall": 0.965,
            },
        }
    else:
        raise RuntimeError(
            f"Unsupported v6.3 eligibility scan protocol: {protocol!r}"
        )
    actual = {key: config.get(key) for key in required}
    if actual != required:
        raise RuntimeError(
            f"v6.3 eligibility scan preregistration mismatch: "
            f"expected={required!r} actual={actual!r}"
        )
    allowed_caps = [
        int(actual["max_chunks_per_source"]),
        *[int(value) for value in actual["fallback_chunk_caps"]],
    ]
    if selected_cap not in allowed_caps:
        raise RuntimeError(
            f"Chunk cap {selected_cap} is not preregistered: {allowed_caps}"
        )
    if (
        int(actual["required_formal_sources"])
        != int(actual["target_query_eligible_sources"])
    ):
        raise RuntimeError(
            "Deduplicated eligibility target must equal formal source count"
        )
    if (
        protocol
        not in {
            V21_ENRON_FULL_SCAN_PROTOCOL,
            ENRON_CAPACITY_SCAN_PROTOCOL,
            ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
        }
        and int(actual["candidate_pool_target_sources"])
        != int(actual["candidate_pool_multiplier"])
        * int(actual["required_formal_sources"])
    ):
        raise RuntimeError(
            "Candidate pool target must equal multiplier times formal sources"
        )
    if (
        protocol
        in {
            V4_SCAN_PROTOCOL,
            V21_ENRON_FULL_SCAN_PROTOCOL,
            ENRON_CAPACITY_SCAN_PROTOCOL,
            ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
        }
        and selected_cap != 5
    ):
        raise RuntimeError(
            "This Enron protocol fixes max_chunks_per_source to cap=5"
        )
    validated = {
        **actual,
        "max_chunks_per_source": int(selected_cap),
        "selected_chunk_cap": int(selected_cap),
        "preregistered_chunk_caps": allowed_caps,
    }
    if protocol == V4_SCAN_PROTOCOL:
        for field in (
            "output_dir",
            "historical_replay_source_order_path",
            "historical_replay_eligibility_path",
        ):
            value = str(config.get(field) or "").strip()
            if not value:
                raise RuntimeError(f"Enron v4 scan config is missing {field}")
            validated[field] = value
    if protocol in {
        ENRON_CAPACITY_SCAN_PROTOCOL,
        ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
    }:
        validated["output_dir"] = str(actual["output_dir"])
    return validated


def _sampling_frame_identity(
    scan_config: dict[str, Any],
) -> dict[str, Any]:
    """Validate and bind the frozen Enron sampling-frame artifact."""

    protocol = scan_config.get("protocol")
    is_enron_full = protocol == V21_ENRON_FULL_SCAN_PROTOCOL
    is_enron_capacity = protocol == ENRON_CAPACITY_SCAN_PROTOCOL
    if not (is_enron_full or is_enron_capacity):
        return {}
    manifest_path = resolve_path(scan_config["sampling_manifest_path"])
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = read_json(manifest_path)
    required = {
        "status": "passed",
        "protocol": "enron_full_csv_hash_sample_v1",
        "selection_seed": 42,
        "expected_raw_records": 517401,
        "raw_record_count": 517401,
        "expected_mailbox_users": 150,
        "raw_mailbox_user_count": 150,
        "raw_screening_target_sources": 150000,
        "selected_source_count": 150000,
        "selection_method": "sha256(seed,dataset,message_sha256)",
        "exact_message_deduplication": True,
    }
    actual = {key: manifest.get(key) for key in required}
    if actual != required:
        raise RuntimeError(
            "Enron sampling-frame manifest gate failed: "
            f"expected={required!r} actual={actual!r}"
        )
    sampled_path = Path(str(manifest.get("selected_jsonl_path") or ""))
    if not sampled_path.is_file():
        raise FileNotFoundError(sampled_path)
    sampled_sha256 = sha256_file(sampled_path)
    if sampled_sha256 != manifest.get("selected_jsonl_sha256"):
        raise RuntimeError("Enron sampled JSONL hash drift")
    return {
        "sampling_frame_manifest_path": str(manifest_path.resolve()),
        "sampling_frame_manifest_sha256": sha256_file(manifest_path),
        "sampling_frame_selected_jsonl_path": str(sampled_path.resolve()),
        "sampling_frame_selected_jsonl_sha256": sampled_sha256,
        "sampling_frame_raw_csv_sha256": manifest.get("raw_csv_sha256"),
        "sampling_frame_raw_mailbox_user_count": 150,
        "sampling_frame_selected_mailbox_user_count": int(
            manifest.get("selected_mailbox_user_count", -1)
        ),
    }


def _calibration_identity(
    attack_config: dict[str, Any],
) -> dict[str, Any]:
    semantic = (
        attack_config.get("fact_extraction", {})
        .get("semantic_resolver", {})
    )
    if semantic.get("protocol") != SEMANTIC_RESOLVER_PROTOCOL:
        raise RuntimeError("Attack config semantic protocol mismatch")
    if semantic.get("schema_sha256") not in {None, SEMANTIC_SCHEMA_SHA256}:
        raise RuntimeError("Attack config semantic schema mismatch")
    if semantic.get("thresholds_frozen") is not True:
        raise RuntimeError("Semantic thresholds are not frozen")
    actual_thresholds_hash = semantic_thresholds_sha256(
        min_target_confidence=float(
            semantic.get("min_target_confidence", 0.0)
        ),
        min_confidence_margin=float(
            semantic.get("min_confidence_margin", 0.0)
        ),
        min_consensus_votes=int(semantic.get("min_consensus_votes", 0)),
        min_boundary_votes=int(semantic.get("min_boundary_votes", 0)),
        biomedical_veto_threshold=float(
            semantic.get("biomedical_veto_threshold", 0.0)
        ),
        overlap_threshold=float(semantic.get("overlap_threshold", 0.0)),
        thresholds_by_entity_type=semantic.get(
            "thresholds_by_entity_type"
        ),
    )
    if actual_thresholds_hash != semantic.get("thresholds_sha256"):
        raise RuntimeError("Semantic threshold decision-surface hash drift")
    summary_path = resolve_path(semantic.get("calibration_summary_path"))
    if not summary_path.is_file():
        return _recovered_calibration_identity(semantic)
    summary = read_json(summary_path)
    selected = summary.get("selected") or {}
    if (
        summary.get("status") != "passed"
        or int(summary.get("rows", 0)) != 206
        or selected.get("gate_passed") is not True
        or int((selected.get("overall") or {}).get("false_accepts", -1))
        != 0
        or (selected.get("overall") or {}).get("precision") is None
        or float((selected.get("overall") or {})["precision"]) < 0.97
        or summary.get("selected_thresholds_sha256")
        != semantic.get("thresholds_sha256")
    ):
        raise RuntimeError("Passed 206-row calibration identity is missing")
    by_type = selected.get("by_entity_type") or {}
    if set(by_type) != {
        "PERSON",
        "ORG",
        "LOCATION",
        "PRODUCT",
        "PROJECT_NAME",
        "CONTRACT_TERM",
    }:
        raise RuntimeError("Calibration does not cover all semantic types")
    if any(
        metrics.get("precision") is None
        or float(metrics["precision"]) < 0.95
        for metrics in by_type.values()
    ):
        raise RuntimeError("Calibration per-type precision gate drift")
    model_lock_path = resolve_path(semantic.get("model_lock_path"))
    return {
        "semantic_protocol": semantic["protocol"],
        "semantic_schema_sha256": SEMANTIC_SCHEMA_SHA256,
        "semantic_thresholds_sha256": semantic["thresholds_sha256"],
        "calibration_summary_path": str(summary_path),
        "calibration_summary_sha256": sha256_file(summary_path),
        "model_lock_path": str(model_lock_path),
        "model_lock_sha256": sha256_file(model_lock_path),
    }


def _recovered_calibration_identity(
    semantic: dict[str, Any],
) -> dict[str, Any]:
    """Validate the explicit v21 recovery record for a deleted v20 summary.

    Recovery is permitted only for the named v21 mode.  The record itself is
    hash-frozen by config and must independently match the retained cleanup
    inventory, the exact research evidence excerpt, threshold surface, and
    semantic model lock.  It never pretends that the deleted summary exists.
    """

    if semantic.get("calibration_identity_mode") != "v21_inventory_recovery":
        raise FileNotFoundError(
            f"Calibration summary is missing: {semantic.get('calibration_summary_path')}"
        )
    provenance_path = resolve_path(semantic.get("calibration_provenance_path"))
    expected_provenance_hash = str(
        semantic.get("calibration_provenance_sha256") or ""
    )
    if not provenance_path.is_file():
        raise FileNotFoundError(
            f"Calibration provenance recovery is missing: {provenance_path}"
        )
    if expected_provenance_hash in {"", "pending_after_recovery"}:
        raise RuntimeError("Calibration provenance recovery hash is not frozen")
    actual_provenance_hash = sha256_file(provenance_path)
    if actual_provenance_hash != expected_provenance_hash:
        raise RuntimeError("Calibration provenance recovery hash drift")

    record = read_json(provenance_path)
    if (
        record.get("protocol")
        != "pcv_mia_v21_calibration_provenance_recovery_v1"
        or record.get("status")
        != "verified_from_immutable_inventory_and_research_record"
    ):
        raise RuntimeError("Calibration provenance recovery status mismatch")
    legacy = record.get("legacy_calibration") or {}
    expected_legacy_path = Path(
        str(semantic.get("calibration_summary_path"))
    ).as_posix()
    if legacy.get("path") != expected_legacy_path:
        raise RuntimeError("Recovered legacy calibration path mismatch")

    inventory_path = resolve_path(legacy.get("inventory_path"))
    inventory_hash = sha256_file(inventory_path)
    if inventory_hash != legacy.get("inventory_sha256"):
        raise RuntimeError("Recovered calibration inventory hash drift")
    inventory_matches: list[dict[str, Any]] = []
    for row in read_jsonl(inventory_path):
        if row.get("path") == expected_legacy_path:
            inventory_matches.append(row)
    if len(inventory_matches) != 1:
        raise RuntimeError("Recovered calibration inventory identity is ambiguous")
    inventory_entry = inventory_matches[0]
    if (
        inventory_entry.get("sha256") != legacy.get("sha256")
        or int(inventory_entry.get("size", -1)) != int(legacy.get("size", -2))
    ):
        raise RuntimeError("Recovered legacy calibration inventory entry drift")

    evidence = record.get("research_evidence") or {}
    excerpt = str(evidence.get("excerpt") or "")
    if not excerpt or sha256_text(excerpt) != evidence.get("excerpt_sha256"):
        raise RuntimeError("Recovered calibration research excerpt hash drift")
    notes_path = resolve_path(evidence.get("path"))
    if excerpt not in notes_path.read_text(encoding="utf-8"):
        raise RuntimeError("Recovered calibration research excerpt is no longer present")

    selected = record.get("selected") or {}
    overall = selected.get("overall") or {}
    if (
        selected.get("gate_passed") is not True
        or int(selected.get("rows", 0)) != 206
        or int(overall.get("false_accepts", -1)) != 0
        or overall.get("precision") is None
        or float(overall["precision"]) < 0.97
        or record.get("semantic_thresholds_sha256")
        != semantic.get("thresholds_sha256")
    ):
        raise RuntimeError("Recovered 206-row calibration gate is invalid")
    by_type = selected.get("by_entity_type") or {}
    required_types = {
        "PERSON",
        "ORG",
        "LOCATION",
        "PRODUCT",
        "PROJECT_NAME",
        "CONTRACT_TERM",
    }
    if set(by_type) != required_types or any(
        metrics.get("precision") is None
        or float(metrics["precision"]) < 0.95
        for metrics in by_type.values()
    ):
        raise RuntimeError("Recovered calibration per-type gate is invalid")

    model_lock_path = resolve_path(semantic.get("model_lock_path"))
    model_lock = record.get("model_lock") or {}
    if (
        model_lock.get("path") != model_lock_path.relative_to(PROJECT_ROOT).as_posix()
        or model_lock.get("sha256") != sha256_file(model_lock_path)
    ):
        raise RuntimeError("Recovered calibration model lock drift")
    return {
        "semantic_protocol": semantic["protocol"],
        "semantic_schema_sha256": SEMANTIC_SCHEMA_SHA256,
        "semantic_thresholds_sha256": semantic["thresholds_sha256"],
        "calibration_identity_mode": "v21_inventory_recovery",
        "calibration_summary_path": str(provenance_path),
        "calibration_summary_sha256": actual_provenance_hash,
        "legacy_calibration_summary_path": expected_legacy_path,
        "legacy_calibration_summary_sha256": legacy["sha256"],
        "model_lock_path": str(model_lock_path),
        "model_lock_sha256": sha256_file(model_lock_path),
    }


def _plan_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "plan": output_dir / "scan_plan.json",
        "source_order": output_dir / "scan_source_order.json",
        "candidates": output_dir / "scan_candidate_benchmark.jsonl",
        "quality_ranking": output_dir / "scan_source_quality.jsonl",
    }


def _enforce_candidate_pool_capacity(
    scan_protocol: str,
    pool_stats: dict[str, Any],
    *,
    candidate_pool_target_sources: int,
) -> None:
    """Fail before plan creation when the Enron full pool is undersized."""

    if (
        scan_protocol
        in {
            V21_ENRON_FULL_SCAN_PROTOCOL,
            ENRON_CAPACITY_SCAN_PROTOCOL,
            ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
        }
        and int(pool_stats["effective_candidate_pool_source_count"])
        != int(candidate_pool_target_sources)
    ):
        raise RuntimeError(
            "Processed source universe is below the preregistered "
            f"{candidate_pool_target_sources:,}-source candidate pool; "
            "do not create a reduced plan"
        )


def _attack_entity_policy_identity(
    attack_config: dict[str, Any],
) -> dict[str, Any]:
    configured_policy = (
        attack_config.get("fact_extraction", {}).get(
            "entity_type_policy",
            {},
        )
    )
    expected_policy = {
        "protocol": ENTITY_TYPE_POLICY_VERSION,
        "config_path": "configs/entity_type_policy_v21_r1.yaml",
        "sha256": ENTITY_TYPE_POLICY_SHA256,
    }
    actual_policy = {
        key: configured_policy.get(key) for key in expected_policy
    }
    if actual_policy != expected_policy:
        raise RuntimeError(
            "Attack config entity policy mismatch: "
            f"expected={expected_policy!r} actual={actual_policy!r}"
        )
    return {
        "entity_type_policy_version": ENTITY_TYPE_POLICY_VERSION,
        "entity_type_policy_sha256": ENTITY_TYPE_POLICY_SHA256,
        "formal_evidence_scope_version": FORMAL_EVIDENCE_SCOPE_VERSION,
        "formal_evidence_scope_sha256": FORMAL_EVIDENCE_SCOPE_SHA256,
    }


def _enron_capacity_role_identity(
    *,
    scan_config: dict[str, Any],
    attack_config: dict[str, Any],
    manual_execution_acknowledged: bool,
) -> dict[str, Any]:
    """绑定边界角色、失败 pilot 和用户手动执行确认。"""

    protocol = str(scan_config.get("protocol") or "")
    if protocol != ENRON_CAPACITY_SCAN_PROTOCOL:
        if manual_execution_acknowledged:
            raise RuntimeError(
                "--manual-user-owned-capacity-run is capacity-study only"
            )
        return {}
    if not manual_execution_acknowledged:
        raise RuntimeError(
            "Enron capacity study requires "
            "--manual-user-owned-capacity-run"
        )
    if (
        scan_config.get("capacity_role_protocol_version")
        != ENRON_CAPACITY_ROLE_VERSION
        or scan_config.get("capacity_role_protocol_sha256")
        != ENRON_CAPACITY_ROLE_SHA256
    ):
        raise RuntimeError("Enron capacity role binding drift")

    role_metadata = enron_capacity_role_metadata()
    role_payload = enron_capacity_role_payload()
    prior = dict(role_payload["prior_applicability"])
    report_path = PROJECT_ROOT / str(prior["report_path"])
    validate_bound_enron_pilot_report(report_path)
    return {
        **_attack_entity_policy_identity(attack_config),
        "enron_capacity_role": role_metadata,
        "enron_capacity_prior_pilot_report_path": str(
            report_path.resolve()
        ),
        "enron_capacity_prior_pilot_report_sha256": sha256_file(
            report_path
        ),
        "enron_capacity_manual_execution_acknowledged": True,
    }


def _enron_capacity_artifact_identity(
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Return the immutable boundary-only identity for capacity artifacts."""

    if plan.get("protocol") != ENRON_CAPACITY_SCAN_PROTOCOL:
        return {}
    validate_enron_capacity_role_metadata(
        plan.get("enron_capacity_role")
    )
    if plan.get("enron_capacity_manual_execution_acknowledged") is not True:
        raise RuntimeError(
            "Enron capacity plan is missing manual execution acknowledgement"
        )
    return {
        "enron_capacity_role": plan["enron_capacity_role"],
        "formal_role": "boundary_stress_test",
        "primary_canonical": False,
        "capacity_pass_effect": "permits_boundary_evaluation_only",
        "prior_applicability_status": "failed",
    }


def _validate_capacity_cli_overrides(
    scan_config: dict[str, Any],
    *,
    processed_path_override: str | None,
    output_dir_override: str | None,
) -> None:
    """Keep the capacity study on its frozen input and isolated output."""

    if (
        scan_config.get("protocol") == ENRON_CAPACITY_SCAN_PROTOCOL
        and (processed_path_override or output_dir_override)
    ):
        raise RuntimeError(
            "Enron capacity study forbids processed/output path overrides"
        )


def _enron_capacity_upstream_identity(
    *,
    scan_config: dict[str, Any],
    data_config: dict[str, Any],
    processed_path: Path,
    processed_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """验证只读 processed 上游和隔离输出目录。"""

    if scan_config.get("protocol") != ENRON_CAPACITY_SCAN_PROTOCOL:
        return {}
    binding = dict(scan_config["upstream_processed"])
    expected_processed = resolve_path(binding["path"])
    expected_manifest = resolve_path(binding["manifest_path"])
    expected_output = resolve_path(scan_config["output_dir"])
    configured_output = resolve_path(
        data_config["datasets"]["enron"]["source_eligibility_path"]
    ).parent
    if (
        processed_path.resolve() != expected_processed.resolve()
        or processed_manifest_path.resolve() != expected_manifest.resolve()
        or output_dir.resolve() != expected_output.resolve()
        or configured_output.resolve() != expected_output.resolve()
        or data_config["datasets"]["enron"].get("membership_unit")
        != "complete_email"
    ):
        raise RuntimeError("Enron capacity runtime path isolation drift")
    processed_hash = sha256_file(processed_path)
    manifest_hash = sha256_file(processed_manifest_path)
    if (
        processed_hash != binding["sha256"]
        or manifest_hash != binding["manifest_sha256"]
    ):
        raise RuntimeError("Enron capacity processed upstream hash drift")
    manifest = read_json(processed_manifest_path)
    required_manifest = {
        "dataset": "enron",
        "membership_unit": "complete_email",
        "cleaner_version": "enron_cleaner_v2_preserve_forwarded_body",
        "chunk_limit": None,
        "source_limit": None,
        "raw_unique_source_count": 150000,
        "unique_source_count": int(binding["unique_source_count"]),
    }
    actual_manifest = {
        key: manifest.get(key) for key in required_manifest
    }
    if actual_manifest != required_manifest:
        raise RuntimeError("Enron capacity processed manifest drift")
    if int(binding["unique_source_count"]) < int(
        scan_config["candidate_pool_target_sources"]
    ):
        raise RuntimeError("Enron capacity processed universe is below 35k")
    return {
        "enron_capacity_upstream_processed_path": str(
            processed_path.resolve()
        ),
        "enron_capacity_upstream_processed_sha256": processed_hash,
        "enron_capacity_upstream_manifest_path": str(
            processed_manifest_path.resolve()
        ),
        "enron_capacity_upstream_manifest_sha256": manifest_hash,
        "enron_capacity_upstream_unique_source_count": int(
            binding["unique_source_count"]
        ),
        "enron_capacity_output_dir": str(output_dir.resolve()),
    }


def _entity_policy_release_identity(
    *,
    scan_config: dict[str, Any],
    attack_config: dict[str, Any],
    release_gate_path: str | None,
) -> dict[str, Any]:
    """Require and bind the audited release gate for the new formal protocol."""

    protocol = str(scan_config.get("protocol") or "")
    if protocol != ENTITY_POLICY_FORMAL_SCAN_PROTOCOL:
        if release_gate_path:
            raise RuntimeError(
                "--release-gate is only valid for the entity-policy formal scan"
            )
        return {}
    if not release_gate_path:
        raise RuntimeError(
            "Entity-policy formal scan requires --release-gate; "
            "replay, pilot, and audit must pass first"
        )
    dataset = str(scan_config.get("dataset") or "")
    validate_primary_formal_dataset(dataset)
    gate_path = Path(release_gate_path).resolve()
    gate = validate_entity_policy_release_gate(
        gate_path,
        project_root=PROJECT_ROOT,
        require_current_runtime=True,
    )
    return {
        **_attack_entity_policy_identity(attack_config),
        "entity_policy_release_gate_path": str(gate_path),
        "entity_policy_release_gate_sha256": sha256_file(gate_path),
        "entity_policy_release_gate_identity_sha256": gate[
            "release_gate_identity_sha256"
        ],
        "entity_policy_release_runtime_tree_sha256": gate[
            "runtime_tree_sha256"
        ],
        "formal_dataset_role_scope_version": (
            FORMAL_DATASET_ROLE_SCOPE_VERSION
        ),
        "formal_dataset_role_scope_sha256": (
            FORMAL_DATASET_ROLE_SCOPE_SHA256
        ),
        "formal_dataset_role": "standard_primary",
    }


def create_scan_plan(
    *,
    dataset: str,
    processed_path: Path,
    processed_manifest_path: Path,
    data_config_path: Path,
    attack_config_path: Path,
    output_dir: Path,
    scan_config: dict[str, Any],
    calibration_identity: dict[str, Any],
    scan_config_path: Path | None = None,
) -> dict[str, Any]:
    """Create immutable plan files; refuse to mix with any existing output."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(
            f"Eligibility output directory is not empty: {output_dir}"
        )
    ensure_dir(output_dir)
    paths = _plan_paths(output_dir)
    scan_protocol = str(scan_config["protocol"])
    _validate_dataset_protocol(dataset, scan_protocol)
    processed_rows = list(read_jsonl(processed_path))
    deduplicated_rows, deduplication = deduplicate_complete_sources(
        processed_rows
    )
    source_universe_order, universe_candidates, universe_stats = (
        freeze_source_plan(
        deduplicated_rows,
        dataset,
        selection_seed=int(scan_config["selection_seed"]),
        max_chunks_per_source=int(
            scan_config["max_chunks_per_source"]
        ),
        )
    )
    ranking_identity: dict[str, Any] = {}
    if scan_protocol == V4_SCAN_PROTOCOL:
        ranking = dict(scan_config["ranking"])
        source_order, candidates, quality_rows = (
            rank_source_universe_by_local_quality(
                source_universe_order,
                universe_candidates,
                dataset=dataset,
                max_entities_per_chunk=int(
                    ranking["max_entities_per_chunk"]
                ),
                guarantee_min_entities_per_chunk=int(
                    ranking["guarantee_min_entities_per_chunk"]
                ),
                high_quality_attackability_threshold=float(
                    ranking[
                        "high_quality_attackability_threshold"
                    ]
                ),
            )
        )
        write_jsonl_atomic(quality_rows, paths["quality_ranking"])
        replay_source_order_path = resolve_path(
            scan_config.get("historical_replay_source_order_path")
        )
        replay_eligibility_path = resolve_path(
            scan_config.get("historical_replay_eligibility_path")
        )
        for replay_path in (
            replay_source_order_path,
            replay_eligibility_path,
        ):
            if not replay_path.is_file():
                raise FileNotFoundError(replay_path)
        replay_cfg = dict(scan_config["historical_replay"])
        replay = validate_historical_rank_replay(
            source_order,
            source_order_path=replay_source_order_path,
            query_eligibility_path=replay_eligibility_path,
            top_k=int(replay_cfg["top_k"]),
            minimum_eligible_covered=int(
                replay_cfg["minimum_eligible_covered"]
            ),
            minimum_eligible_recall=float(
                replay_cfg["minimum_eligible_recall"]
            ),
        )
        pool_stats = {
            "source_universe_count": len(source_order),
            "source_universe_probe_row_count": len(candidates),
            "effective_candidate_pool_source_count": len(source_order),
            "candidate_pool_shortfall_count": 0,
            "candidate_pool_uses_complete_source_universe": True,
        }
        ranking_identity = {
            "quality_ranking_path": str(
                paths["quality_ranking"].resolve()
            ),
            "quality_ranking_sha256": sha256_file(
                paths["quality_ranking"]
            ),
            "quality_ranking_rows": len(quality_rows),
            "historical_rank_replay": replay,
        }
    else:
        source_order, candidates, pool_stats = (
            freeze_candidate_pool_prefix(
                source_universe_order,
                universe_candidates,
                candidate_pool_target_sources=int(
                    scan_config["candidate_pool_target_sources"]
                ),
            )
        )
    _enforce_candidate_pool_capacity(
        scan_protocol,
        pool_stats,
        candidate_pool_target_sources=int(
            scan_config["candidate_pool_target_sources"]
        ),
    )
    stats = {
        "input_row_count": universe_stats["input_row_count"],
        "source_count": len(source_order),
        "probe_row_count": len(candidates),
        "probe_source_count": len(source_order),
        **pool_stats,
    }
    write_json(
        {
            "dataset": dataset,
            "selection_seed": scan_config["selection_seed"],
            "source_order": source_order,
        },
        paths["source_order"],
    )
    write_jsonl_atomic(candidates, paths["candidates"])

    identity = {
        "protocol": scan_protocol,
        "dataset": dataset,
        "selection_method": (
            "local_rule_quality_lexicographic_v1"
            if scan_protocol == V4_SCAN_PROTOCOL
            else "sha256(seed,dataset,canonical_source_key)"
        ),
        "chunk_selection_method": (
            "sha256(seed,dataset,source,doc_id,text_hash,text)"
        ),
        "label_fields_read": [],
        **scan_config,
        **calibration_identity,
        **ranking_identity,
        "extractor_version": EXTRACTOR_VERSION,
        "claim_validator_version": VALIDATOR_VERSION,
        "processed_path": str(processed_path.resolve()),
        "processed_sha256": sha256_file(processed_path),
        "processed_manifest_path": str(
            processed_manifest_path.resolve()
        ),
        "processed_manifest_sha256": sha256_file(
            processed_manifest_path
        ),
        "data_config_path": str(data_config_path.resolve()),
        "data_config_sha256": sha256_file(data_config_path),
        "attack_config_path": str(attack_config_path.resolve()),
        "attack_config_sha256": sha256_file(attack_config_path),
        "output_dir": str(output_dir.resolve()),
        "source_order_path": str(paths["source_order"].resolve()),
        "source_order_file_sha256": sha256_file(
            paths["source_order"]
        ),
        "source_order_sha256": sha256_obj(source_order),
        "candidate_benchmark_path": str(paths["candidates"].resolve()),
        "candidate_benchmark_sha256": sha256_file(
            paths["candidates"]
        ),
        **stats,
        "raw_input_row_count": len(processed_rows),
        "deduplicated_input_row_count": len(deduplicated_rows),
        "source_deduplication": deduplication,
    }
    if scan_protocol in {
        V4_SCAN_PROTOCOL,
        ENRON_CAPACITY_SCAN_PROTOCOL,
        ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
    }:
        if scan_config_path is None:
            raise RuntimeError(
                "This scan protocol requires an independent scan config"
            )
        identity.update(
            {
                "scan_config_path": str(scan_config_path.resolve()),
                "scan_config_sha256": sha256_file(scan_config_path),
            }
        )
    plan = {
        **identity,
        "scan_plan_sha256": sha256_obj(identity),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "initial_status": "preregistered_not_executed",
        "api_calls_performed": 0,
        "retriever_runs": 0,
    }
    write_json(plan, paths["plan"])
    return plan


def validate_scan_plan(
    plan: dict[str, Any],
    *,
    dataset: str,
    processed_path: Path,
    processed_manifest_path: Path,
    data_config_path: Path,
    attack_config_path: Path,
    output_dir: Path,
    scan_config: dict[str, Any],
    calibration_identity: dict[str, Any],
    scan_config_path: Path | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Fail closed on every input/config/hash drift before resume."""

    source_order_path = Path(str(plan.get("source_order_path") or ""))
    candidate_path = Path(
        str(plan.get("candidate_benchmark_path") or "")
    )
    source_payload = read_json(source_order_path)
    source_order = [
        str(value) for value in source_payload.get("source_order", [])
    ]
    candidates = list(read_jsonl(candidate_path))
    scan_protocol = str(scan_config["protocol"])
    _validate_dataset_protocol(dataset, scan_protocol)
    current = {
        **scan_config,
        **calibration_identity,
        "dataset": dataset,
        "processed_path": str(processed_path.resolve()),
        "processed_sha256": sha256_file(processed_path),
        "processed_manifest_path": str(
            processed_manifest_path.resolve()
        ),
        "processed_manifest_sha256": sha256_file(
            processed_manifest_path
        ),
        "data_config_path": str(data_config_path.resolve()),
        "data_config_sha256": sha256_file(data_config_path),
        "attack_config_path": str(attack_config_path.resolve()),
        "attack_config_sha256": sha256_file(attack_config_path),
        "output_dir": str(output_dir.resolve()),
        "source_order_file_sha256": sha256_file(source_order_path),
        "source_order_sha256": sha256_obj(source_order),
        "candidate_benchmark_sha256": sha256_file(candidate_path),
    }
    if scan_protocol in {
        V4_SCAN_PROTOCOL,
        ENRON_CAPACITY_SCAN_PROTOCOL,
        ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
    }:
        if scan_config_path is None:
            raise RuntimeError(
                "This scan protocol requires an independent scan config"
            )
        current.update(
            {
                "scan_config_path": str(scan_config_path.resolve()),
                "scan_config_sha256": sha256_file(scan_config_path),
            }
        )
    if scan_protocol == V4_SCAN_PROTOCOL:
        quality_path = Path(str(plan.get("quality_ranking_path") or ""))
        current["quality_ranking_sha256"] = sha256_file(quality_path)
    mismatches = {
        key: {"expected": plan.get(key), "actual": value}
        for key, value in current.items()
        if plan.get(key) != value
    }
    identity = {
        key: value
        for key, value in plan.items()
        if key
        not in {
            "scan_plan_sha256",
            "created_at",
            "initial_status",
            "api_calls_performed",
            "retriever_runs",
        }
    }
    if sha256_obj(identity) != plan.get("scan_plan_sha256"):
        mismatches["scan_plan_sha256"] = {
            "expected": plan.get("scan_plan_sha256"),
            "actual": sha256_obj(identity),
        }
    if mismatches:
        raise RuntimeError(f"Eligibility scan plan drift: {mismatches}")
    candidate_sources = {str(row.get("source_key")) for row in candidates}
    if candidate_sources != set(source_order):
        raise RuntimeError("Candidate benchmark/source order coverage drift")
    if scan_protocol == V4_SCAN_PROTOCOL:
        candidate_source_order = list(
            dict.fromkeys(str(row.get("source_key")) for row in candidates)
        )
        if candidate_source_order != source_order:
            raise RuntimeError(
                "Ranked candidate benchmark/source order drift"
            )
    return source_order, candidates


def _wave_output_paths(
    attempt_dir: Path,
    dataset: str,
) -> dict[str, Path]:
    prefix = attempt_dir / f"{dataset}_candidate"
    return {
        "benchmark": prefix.with_name(prefix.name + "_benchmark.jsonl"),
        "facts": prefix.with_name(prefix.name + "_facts.jsonl"),
        "claims": prefix.with_name(prefix.name + "_claims.jsonl"),
        "queries": prefix.with_name(prefix.name + "_queries.jsonl"),
        "stealth": prefix.with_name(
            prefix.name + "_stealth_queries.jsonl"
        ),
        "stealth_rejected": prefix.with_name(
            prefix.name + "_stealth_queries_rejected.jsonl"
        ),
    }


def _next_wave_attempt(output_dir: Path, wave_index: int) -> Path:
    waves_dir = ensure_dir(output_dir / "waves")
    existing = sorted(
        waves_dir.glob(f"wave_{wave_index:04d}_attempt_*")
    )
    attempt = 0
    if existing:
        attempt = max(
            int(path.name.rsplit("_", 1)[-1]) for path in existing
        ) + 1
    path = waves_dir / (
        f"wave_{wave_index:04d}_attempt_{attempt:03d}"
    )
    path.mkdir(parents=False, exist_ok=False)
    return path


def run_pipeline_wave(
    *,
    wave_index: int,
    wave_source_keys: list[str],
    source_start: int,
    source_end: int,
    candidates_by_source: dict[str, list[dict[str, Any]]],
    dataset: str,
    processed_path: Path,
    output_dir: Path,
    attack_config: dict[str, Any],
    plan: dict[str, Any],
    semantic_resolver_runtime: SemanticResolverRuntime,
) -> dict[str, Any]:
    """Run one complete local wave in a new immutable attempt directory."""

    started_at = perf_counter()
    try:
        import torch
    except ImportError:  # pragma: no cover - formal CUDA 环境包含 torch
        torch = None
    if torch is not None and torch.cuda.is_available():
        # 上一 wave 的一次性 stealth embedder 已关闭；在重置峰值前归还缓存，
        # 避免长进程中的 CUDA 碎片让正常短文本在 batch=1 仍 OOM。
        gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            # 异步 CUDA 错误由正式 resolver 的 fail-closed 路径处理。
            pass
        torch.cuda.reset_peak_memory_stats()

    attempt_dir = _next_wave_attempt(output_dir, wave_index)
    paths = _wave_output_paths(attempt_dir, dataset)
    benchmark_rows = [
        row
        for source_key in wave_source_keys
        for row in candidates_by_source[source_key]
    ]
    write_jsonl(benchmark_rows, paths["benchmark"])

    fact_cfg = dict(attack_config.get("fact_extraction", {}))
    overrides = dict(fact_cfg.pop("dataset_overrides", {}) or {})
    fact_cfg.update(dict(overrides.get(dataset, {}) or {}))
    fact_manifest = extract_facts_file(
        benchmark_path=paths["benchmark"],
        output_path=paths["facts"],
        max_facts_per_doc=int(fact_cfg.get("max_facts_per_doc", 4)),
        max_entities_per_doc=int(
            fact_cfg.get("max_entities_per_doc", 8)
        ),
        max_samples=fact_cfg.get("max_samples"),
        min_importance=float(fact_cfg.get("min_importance", 0.6)),
        min_replaceability=float(
            fact_cfg.get("min_replaceability", 0.6)
        ),
        min_privacy_specificity=float(
            fact_cfg.get("min_privacy_specificity", 0.5)
        ),
        guarantee_min_facts=int(
            fact_cfg.get("guarantee_min_facts", 1)
        ),
        ner_config=dict(fact_cfg.get("ner", {})),
        semantic_resolver_config=dict(
            fact_cfg.get("semantic_resolver", {})
        ),
        semantic_resolver_runtime=semantic_resolver_runtime,
        dataset=dataset,
        resume=False,
        force=False,
    )
    semantic_metadata = fact_manifest.get("semantic_entity_resolver") or {}
    if (
        semantic_metadata.get("protocol")
        != plan["semantic_protocol"]
        or semantic_metadata.get("schema_sha256")
        != plan["semantic_schema_sha256"]
        or semantic_metadata.get("thresholds_sha256")
        != plan["semantic_thresholds_sha256"]
    ):
        raise RuntimeError("Wave semantic resolver identity drift")

    claim_cfg = dict(attack_config.get("paired_claims", {}))
    claim_manifest = generate_paired_claims_file(
        facts_path=paths["facts"],
        output_path=paths["claims"],
        benchmark_path=paths["benchmark"],
        source_corpus_path=processed_path,
        perturbation_levels=claim_cfg.get(
            "perturbation_levels",
            ["light"],
        ),
        max_pairs_per_fact=int(
            claim_cfg.get("max_pairs_per_fact", 1)
        ),
        semantic_resolver_config=dict(
            fact_cfg.get("semantic_resolver", {})
        ),
        semantic_resolver_runtime=semantic_resolver_runtime,
        source_key_allowlist=set(wave_source_keys),
        dataset=dataset,
        resume=False,
        force=False,
    )
    query_cfg = dict(attack_config.get("paired_queries", {}))
    query_manifest = generate_paired_queries_file(
        paired_claims_path=paths["claims"],
        output_path=paths["queries"],
        # Eligibility 只做零 API 结构容量探针；正式 query protocol 在冻结 source 后由 Step 08 生成。
        query_types=["compressed_verification"],
        resume=False,
        force=False,
    )
    stealth_cfg = dict(attack_config.get("stealth_filter", {}))
    stealth_manifest = filter_stealth_queries(
        queries_path=paths["queries"],
        output_path=paths["stealth"],
        rejected_path=paths["stealth_rejected"],
        embedding_model=str(stealth_cfg.get("embedding_model")),
        embedding_local_files_only=bool(
            stealth_cfg.get("embedding_local_files_only", False)
        ),
        embedding_batch_size=int(
            stealth_cfg.get("embedding_batch_size", 256)
        ),
        min_naturalness=float(
            stealth_cfg.get("min_naturalness", 0.55)
        ),
        max_context_probe=float(
            stealth_cfg.get("max_context_probe", 0.5)
        ),
        max_prompt_injection=float(
            stealth_cfg.get("max_prompt_injection", 0.5)
        ),
        # 结构容量探针使用旧零 API 查询，不执行正式字面复制门禁。
        max_five_gram_containment=1.0,
        max_longest_common_token_run=1_000_000,
        max_dataset_duplicate_template_rate=1.0,
        max_dataset_opening_4gram_rate=1.0,
        pairs_per_source=int(plan["minimum_stealth_pairs"]),
        resume=False,
        force=False,
    )

    claim_counts = Counter(
        str(
            row.get("source_key")
            or row.get("source_id")
            or row.get("doc_id")
        )
        for row in read_jsonl(paths["claims"])
    )
    claim_eligible = sorted(
        source_key
        for source_key, count in claim_counts.items()
        if count >= int(plan["minimum_valid_claims"])
    )
    eligible, fixed_budget = validate_fixed_budget_query_rows(
        read_jsonl(paths["stealth"]),
        allowed_source_keys=set(wave_source_keys),
        required_pairs=int(plan["minimum_stealth_pairs"]),
    )
    upstream_fixed = stealth_manifest.get("fixed_budget") or {}
    if (
        upstream_fixed.get("query_text_uniqueness_enforced") is not True
        or upstream_fixed.get("fixed_budget_plan_hash")
        != fixed_budget["fixed_budget_plan_hash"]
        or int(upstream_fixed.get("eligible_sources", -1))
        != len(eligible)
    ):
        raise RuntimeError("Wave fixed-budget manifest drift")

    outputs: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        outputs[name] = {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "rows": sum(1 for _ in read_jsonl(path)),
        }
    for name, path in (
        ("facts_manifest", paths["facts"].with_suffix(".manifest.json")),
        ("claims_manifest", paths["claims"].with_suffix(".manifest.json")),
        ("queries_manifest", paths["queries"].with_suffix(".manifest.json")),
        ("stealth_manifest", paths["stealth"].with_suffix(".manifest.json")),
    ):
        outputs[name] = {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
        }

    manifest = {
        "status": "complete",
        "protocol": plan["protocol"],
        "scan_plan_sha256": plan["scan_plan_sha256"],
        "entity_type_policy_version": (
            plan.get("entity_type_policy_version")
            or plan.get("entity_policy_version")
        ),
        "entity_type_policy_sha256": (
            plan.get("entity_type_policy_sha256")
            or plan.get("entity_policy_sha256")
        ),
        "entity_policy_release_gate_identity_sha256": plan.get(
            "entity_policy_release_gate_identity_sha256"
        ),
        "dataset": dataset,
        "wave_index": wave_index,
        "source_start": source_start,
        "source_end": source_end,
        "wave_source_keys": wave_source_keys,
        "wave_source_keys_hash": sha256_obj(wave_source_keys),
        "candidate_row_count": len(benchmark_rows),
        "claim_eligible_source_keys": claim_eligible,
        "claim_eligible_source_count": len(claim_eligible),
        "eligible_source_keys": eligible,
        "eligible_source_count": len(eligible),
        "fixed_budget": fixed_budget,
        "semantic_entity_resolver": semantic_metadata,
        "local_ner": fact_manifest.get("local_ner"),
        "query_types": query_manifest.get("query_types"),
        "embedding_model": stealth_manifest.get("embedding_model"),
        "embedding_local_files_only": stealth_manifest.get(
            "embedding_local_files_only"
        ),
        "outputs": outputs,
        "fact_manifest_summary": {
            "facts": fact_manifest.get("facts"),
            "samples_seen": fact_manifest.get("samples_seen"),
        },
        "claim_manifest_summary": {
            "pairs": claim_manifest.get("pairs"),
        },
        "semantic_prediction_runtime": (
            semantic_resolver_runtime[0].prediction_runtime_stats()
            if semantic_resolver_runtime[0] is not None
            else {}
        ),
        "elapsed_seconds": round(perf_counter() - started_at, 6),
        "peak_cuda_memory_bytes": (
            int(torch.cuda.max_memory_allocated())
            if torch is not None and torch.cuda.is_available()
            else 0
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "api_calls_performed": 0,
        "retriever_runs": 0,
    }
    manifest["wave_identity_sha256"] = sha256_obj(
        {
            key: value
            for key, value in manifest.items()
            if key not in {"created_at", "wave_identity_sha256"}
        }
    )
    manifest_path = attempt_dir / "wave_manifest.json"
    write_json(manifest, manifest_path)
    return {
        "wave_manifest_path": str(manifest_path.resolve()),
        "wave_manifest_sha256": sha256_file(manifest_path),
        "wave_identity_sha256": manifest["wave_identity_sha256"],
        "eligible_source_keys": eligible,
    }


def validate_completed_wave(
    record: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    manifest_path = Path(str(record.get("wave_manifest_path") or ""))
    if sha256_file(manifest_path) != record.get("wave_manifest_sha256"):
        raise RuntimeError("Completed wave manifest hash drift")
    manifest = read_json(manifest_path)
    if (
        manifest.get("status") != "complete"
        or manifest.get("protocol") != plan.get("protocol", SCAN_PROTOCOL)
        or manifest.get("scan_plan_sha256")
        != plan.get("scan_plan_sha256")
        or manifest.get("wave_identity_sha256")
        != record.get("wave_identity_sha256")
    ):
        raise RuntimeError("Completed wave identity drift")
    for output in (manifest.get("outputs") or {}).values():
        path = Path(str(output.get("path") or ""))
        if sha256_file(path) != output.get("sha256"):
            raise RuntimeError(f"Completed wave output hash drift: {path}")
    return manifest


def _checkpoint_paths(output_dir: Path) -> list[Path]:
    checkpoint_dir = output_dir / "checkpoints"
    if not checkpoint_dir.is_dir():
        return []
    return sorted(checkpoint_dir.glob("checkpoint_*.json"))


def load_latest_checkpoint(
    output_dir: Path,
    plan: dict[str, Any],
) -> tuple[dict[str, Any] | None, Path | None]:
    paths = _checkpoint_paths(output_dir)
    if not paths:
        return None, None
    previous_path: Path | None = None
    previous_hash: str | None = None
    latest_payload: dict[str, Any] | None = None
    for expected_index, path in enumerate(paths, start=1):
        if path.name != f"checkpoint_{expected_index:04d}.json":
            raise RuntimeError("Eligibility checkpoint sequence is not contiguous")
        payload = read_json(path)
        identity = {
            key: value
            for key, value in payload.items()
            if key not in {"created_at", "checkpoint_identity_sha256"}
        }
        if (
            payload.get("scan_plan_sha256")
            != plan.get("scan_plan_sha256")
            or payload.get("protocol")
            != plan.get("protocol", SCAN_PROTOCOL)
            or sha256_obj(identity)
            != payload.get("checkpoint_identity_sha256")
            or len(payload.get("completed_waves", [])) != expected_index
        ):
            raise RuntimeError(
                f"Eligibility checkpoint identity drift: {path}"
            )
        capacity_identity = _enron_capacity_artifact_identity(plan)
        if any(
            payload.get(key) != value
            for key, value in capacity_identity.items()
        ):
            raise RuntimeError(
                f"Enron capacity checkpoint role identity drift: {path}"
            )
        expected_previous_path = (
            str(previous_path.resolve())
            if previous_path is not None
            else None
        )
        if (
            payload.get("previous_checkpoint_path")
            != expected_previous_path
            or payload.get("previous_checkpoint_sha256")
            != previous_hash
        ):
            raise RuntimeError("Eligibility checkpoint chain drift")
        previous_path = path
        previous_hash = sha256_file(path)
        latest_payload = payload
    return latest_payload, paths[-1]


def write_checkpoint(
    output_dir: Path,
    plan: dict[str, Any],
    state: dict[str, Any],
) -> Path:
    checkpoint_dir = ensure_dir(output_dir / "checkpoints")
    path = checkpoint_dir / (
        f"checkpoint_{len(state['completed_waves']):04d}.json"
    )
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite checkpoint: {path}")
    previous_paths = _checkpoint_paths(output_dir)
    previous = previous_paths[-1] if previous_paths else None
    if len(previous_paths) != len(state["completed_waves"]) - 1:
        raise RuntimeError("Eligibility checkpoint count is not contiguous")
    identity = {
        "protocol": plan.get("protocol", SCAN_PROTOCOL),
        "scan_plan_sha256": plan["scan_plan_sha256"],
        "dataset": plan["dataset"],
        "source_order_sha256": plan["source_order_sha256"],
        "wave_size": plan["wave_size"],
        "target_query_eligible_sources": plan[
            "target_query_eligible_sources"
        ],
        "required_formal_sources": plan["required_formal_sources"],
        "candidate_pool_target_sources": plan[
            "candidate_pool_target_sources"
        ],
        "effective_candidate_pool_source_count": plan[
            "effective_candidate_pool_source_count"
        ],
        "scan_full_candidate_pool": plan[
            "scan_full_candidate_pool"
        ],
        "stop_status": state["stop_status"],
        "stop_reason": state["stop_reason"],
        "completed_waves": state["completed_waves"],
        "scanned_source_count": state["scanned_source_count"],
        "scanned_prefix_source_keys_hash": state[
            "scanned_prefix_source_keys_hash"
        ],
        "eligible_source_keys": state["eligible_source_keys"],
        "eligible_source_count": state["eligible_source_count"],
        "eligible_source_keys_hash": sha256_obj(
            state["eligible_source_keys"]
        ),
        "previous_checkpoint_path": (
            str(previous.resolve()) if previous is not None else None
        ),
        "previous_checkpoint_sha256": (
            sha256_file(previous) if previous is not None else None
        ),
        "api_calls_performed": 0,
        "retriever_runs": 0,
    }
    identity.update(_enron_capacity_artifact_identity(plan))
    if bool(plan.get("exact_target_stop", False)):
        identity.update(
            {
                "exact_target_stop": True,
                "processed_source_count": state[
                    "processed_source_count"
                ],
                "processed_prefix_source_keys_hash": state[
                    "processed_prefix_source_keys_hash"
                ],
                "retained_source_end": state["retained_source_end"],
                "retained_prefix_source_keys_hash": state[
                    "retained_prefix_source_keys_hash"
                ],
            }
        )
    payload = {
        **identity,
        "checkpoint_identity_sha256": sha256_obj(identity),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(payload, path)
    return path


def _iter_wave_rows(
    manifests: Iterable[dict[str, Any]],
    output_name: str,
    *,
    allowed_source_keys: set[str] | None = None,
) -> Iterator[dict[str, Any]]:
    for manifest in manifests:
        path = Path(manifest["outputs"][output_name]["path"])
        for row in read_jsonl(path):
            source_key = str(row.get("source_key") or "")
            if allowed_source_keys is not None:
                if not source_key:
                    raise RuntimeError(
                        f"{output_name} row lacks source_key during retained-prefix finalization"
                    )
                if source_key not in allowed_source_keys:
                    continue
            yield row


def _final_output_paths(output_dir: Path, dataset: str) -> dict[str, Path]:
    return {
        "benchmark": output_dir / f"{dataset}_candidate_benchmark.jsonl",
        "facts": output_dir / f"{dataset}_candidate_facts.jsonl",
        "claims": output_dir / f"{dataset}_candidate_claims.jsonl",
        "queries": output_dir / f"{dataset}_candidate_queries.jsonl",
        "stealth": (
            output_dir / f"{dataset}_candidate_stealth_queries.jsonl"
        ),
        "stealth_rejected": (
            output_dir
            / f"{dataset}_candidate_stealth_queries_rejected.jsonl"
        ),
        "claim_eligibility": (
            output_dir / f"{dataset}_claim_eligible_sources.json"
        ),
        "query_eligibility": (
            output_dir / f"{dataset}_query_eligible_sources.json"
        ),
        "stealth_manifest": (
            output_dir
            / f"{dataset}_candidate_stealth_queries.manifest.json"
        ),
        "finalization_manifest": (
            output_dir / f"{dataset}_finalization_manifest.json"
        ),
    }


def _next_finalization_attempt(output_dir: Path) -> Path:
    attempts_dir = ensure_dir(output_dir / "finalization_attempts")
    existing = sorted(attempts_dir.glob("attempt_*"))
    attempt = (
        max(int(path.name.rsplit("_", 1)[-1]) for path in existing) + 1
        if existing
        else 0
    )
    path = attempts_dir / f"attempt_{attempt:03d}"
    path.mkdir(parents=False, exist_ok=False)
    return path


def _validate_finalization_manifest(
    manifest_path: Path,
    *,
    plan: dict[str, Any],
    checkpoint_path: Path,
) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    identity = {
        key: value
        for key, value in manifest.items()
        if key not in {"created_at", "finalization_identity_sha256"}
    }
    if (
        manifest.get("protocol") != plan.get("protocol", SCAN_PROTOCOL)
        or manifest.get("scan_plan_sha256") != plan["scan_plan_sha256"]
        or manifest.get("scan_checkpoint_sha256")
        != sha256_file(checkpoint_path)
        or sha256_obj(identity)
        != manifest.get("finalization_identity_sha256")
    ):
        raise RuntimeError("Existing finalization manifest identity drift")
    capacity_identity = _enron_capacity_artifact_identity(plan)
    if any(
        manifest.get(key) != value
        for key, value in capacity_identity.items()
    ):
        raise RuntimeError(
            "Enron capacity finalization role identity drift"
        )
    for output in (manifest.get("outputs") or {}).values():
        path = Path(str(output.get("path") or ""))
        if sha256_file(path) != output.get("sha256"):
            raise RuntimeError(f"Finalized output hash drift: {path}")
    query_path = Path(
        str(manifest["outputs"]["query_eligibility"]["path"])
    )
    return read_json(query_path)


def _promote_staged_file(staged: Path, target: Path) -> None:
    if target.exists():
        if sha256_file(target) != sha256_file(staged):
            raise RuntimeError(f"Partial final output hash drift: {target}")
        return
    staged.replace(target)


def _cleanup_prediction_caches(output_dir: Path) -> None:
    """只清理当前 eligibility 目录下已完成 wave 的 SQLite 临时缓存。"""

    cache_dir = (output_dir / "prediction_cache").resolve()
    if cache_dir.parent != output_dir.resolve() or not cache_dir.is_dir():
        return
    for path in cache_dir.iterdir():
        if (
            path.is_file()
            and path.name.startswith("wave_")
            and ".sqlite3" in path.name
        ):
            path.unlink()
    if any(cache_dir.iterdir()):
        raise RuntimeError(
            f"Prediction cache directory contains unexpected files: {cache_dir}"
        )
    cache_dir.rmdir()


def finalize_scan(
    *,
    state: dict[str, Any],
    plan: dict[str, Any],
    checkpoint_path: Path,
    output_dir: Path,
    attack_config: dict[str, Any],
) -> dict[str, Any]:
    """Materialize only the terminal scanned prefix for downstream promotion."""

    canonical_paths = _final_output_paths(
        output_dir,
        str(plan["dataset"]),
    )
    if canonical_paths["finalization_manifest"].is_file():
        finalized = _validate_finalization_manifest(
            canonical_paths["finalization_manifest"],
            plan=plan,
            checkpoint_path=checkpoint_path,
        )
        _cleanup_prediction_caches(output_dir)
        return finalized
    attempt_dir = _next_finalization_attempt(output_dir)
    paths = _final_output_paths(attempt_dir, str(plan["dataset"]))

    wave_manifests = [
        validate_completed_wave(record, plan)
        for record in state["completed_waves"]
    ]
    source_payload = read_json(plan["source_order_path"])
    source_order = [
        str(value) for value in source_payload.get("source_order", [])
    ]
    if sha256_obj(source_order) != plan["source_order_sha256"]:
        raise RuntimeError("Finalization source order hash drift")
    retained_source_end = int(state["scanned_source_count"])
    if not 0 < retained_source_end <= len(source_order):
        raise RuntimeError("Finalization retained source boundary is invalid")
    retained_sources = set(source_order[:retained_source_end])
    for name in (
        "benchmark",
        "facts",
        "claims",
        "queries",
        "stealth",
        "stealth_rejected",
    ):
        write_jsonl_atomic(
            _iter_wave_rows(
                wave_manifests,
                name,
                allowed_source_keys=retained_sources,
            ),
            paths[name],
        )

    allowed_sources = retained_sources
    eligible, fixed_budget = validate_fixed_budget_query_rows(
        read_jsonl(paths["stealth"]),
        allowed_source_keys=allowed_sources,
        required_pairs=int(plan["minimum_stealth_pairs"]),
    )
    if eligible != state["eligible_source_keys"]:
        raise RuntimeError("Final eligible source set differs from checkpoint")
    if (
        bool(plan.get("exact_target_stop", False))
        and len(eligible)
        != int(plan["target_query_eligible_sources"])
    ):
        raise RuntimeError(
            "Exact-stop final eligibility is not exactly the target"
        )

    semantic_values = {
        sha256_obj(manifest["semantic_entity_resolver"])
        for manifest in wave_manifests
    }
    if len(semantic_values) != 1:
        raise RuntimeError("Semantic resolver metadata drifted across waves")
    semantic_metadata = wave_manifests[0]["semantic_entity_resolver"]
    local_ner = wave_manifests[0].get("local_ner")
    if any(manifest.get("local_ner") != local_ner for manifest in wave_manifests):
        raise RuntimeError("Local NER metadata drifted across waves")

    claim_counts = Counter(
        str(
            row.get("source_key")
            or row.get("source_id")
            or row.get("doc_id")
        )
        for row in read_jsonl(paths["claims"])
    )
    claim_eligible = sorted(
        source_key
        for source_key, count in claim_counts.items()
        if count >= int(plan["minimum_valid_claims"])
    )
    scanned_source_count = int(state["scanned_source_count"])
    checkpoint_hash = sha256_file(checkpoint_path)
    common_scan = {
        "scan_protocol": plan["protocol"],
        "scan_plan_sha256": plan["scan_plan_sha256"],
        "entity_type_policy_version": plan.get(
            "entity_type_policy_version"
        ),
        "entity_type_policy_sha256": plan.get(
            "entity_type_policy_sha256"
        ),
        "entity_policy_release_gate_identity_sha256": plan.get(
            "entity_policy_release_gate_identity_sha256"
        ),
        "scan_checkpoint_path": str(checkpoint_path.resolve()),
        "scan_checkpoint_sha256": checkpoint_hash,
        "source_order_sha256": plan["source_order_sha256"],
        "scanned_source_count": scanned_source_count,
        "scanned_prefix_source_keys_hash": state[
            "scanned_prefix_source_keys_hash"
        ],
        "wave_size": plan["wave_size"],
        "completed_wave_count": len(state["completed_waves"]),
        "stop_status": state["stop_status"],
        "stop_reason": state["stop_reason"],
        "target_query_eligible_sources": plan[
            "target_query_eligible_sources"
        ],
        "required_formal_sources": plan["required_formal_sources"],
        "candidate_pool_multiplier": plan[
            "candidate_pool_multiplier"
        ],
        "candidate_pool_target_sources": plan[
            "candidate_pool_target_sources"
        ],
        "effective_candidate_pool_source_count": plan[
            "effective_candidate_pool_source_count"
        ],
        "candidate_pool_shortfall_count": plan[
            "candidate_pool_shortfall_count"
        ],
        "candidate_pool_uses_complete_source_universe": plan[
            "candidate_pool_uses_complete_source_universe"
        ],
        "source_universe_count": plan["source_universe_count"],
        "scan_full_candidate_pool": plan[
            "scan_full_candidate_pool"
        ],
        "selected_chunk_cap": plan["selected_chunk_cap"],
        "preregistered_chunk_caps": plan["preregistered_chunk_caps"],
        "deduplicate_complete_sources": plan[
            "deduplicate_complete_sources"
        ],
        "source_deduplication": plan["source_deduplication"],
        "data_config_sha256": plan["data_config_sha256"],
        "attack_config_sha256": plan["attack_config_sha256"],
        "model_lock_sha256": plan["model_lock_sha256"],
        "calibration_summary_sha256": plan[
            "calibration_summary_sha256"
        ],
        "semantic_schema_sha256": plan["semantic_schema_sha256"],
        "semantic_thresholds_sha256": plan[
            "semantic_thresholds_sha256"
        ],
        "api_calls_performed": 0,
        "retriever_runs": 0,
    }
    common_scan.update(_enron_capacity_artifact_identity(plan))
    if bool(plan.get("exact_target_stop", False)):
        common_scan.update(
            {
                "exact_target_stop": True,
                "processed_source_count": state[
                    "processed_source_count"
                ],
                "processed_prefix_source_keys_hash": state[
                    "processed_prefix_source_keys_hash"
                ],
                "retained_source_end": state["retained_source_end"],
                "retained_prefix_source_keys_hash": state[
                    "retained_prefix_source_keys_hash"
                ],
                "initial_priority_source_count": plan[
                    "initial_priority_source_count"
                ],
                "extension_source_count": plan[
                    "extension_source_count"
                ],
                "quality_ranking_sha256": plan[
                    "quality_ranking_sha256"
                ],
            }
        )
    claim_protocol, query_protocol = _eligibility_protocols(
        str(plan["protocol"])
    )
    claim_manifest = {
        "dataset": plan["dataset"],
        "protocol": claim_protocol,
        **common_scan,
        "minimum_valid_claims": plan["minimum_valid_claims"],
        "eligibility_probe": {
            "selection_method": plan["selection_method"],
            "selection_seed": plan["selection_seed"],
            "max_chunks_per_source": plan["max_chunks_per_source"],
            "wave_size": plan["wave_size"],
            "input_row_count": plan["input_row_count"],
            "source_count": plan["source_count"],
            "probe_row_count": plan["probe_row_count"],
        },
        "extractor_version": EXTRACTOR_VERSION,
        "claim_validator_version": VALIDATOR_VERSION,
        "processed_path": plan["processed_path"],
        "processed_hash": plan["processed_sha256"],
        "candidate_benchmark_hash": sha256_file(paths["benchmark"]),
        "candidate_facts_hash": sha256_file(paths["facts"]),
        "candidate_claims_hash": sha256_file(paths["claims"]),
        "local_ner": local_ner,
        "semantic_entity_resolver": semantic_metadata,
        "source_count": scanned_source_count,
        "eligible_source_count": len(claim_eligible),
        "excluded_source_count": scanned_source_count
        - len(claim_eligible),
        "claim_count_distribution": dict(
            sorted(Counter(claim_counts.values()).items())
        ),
        "eligible_source_keys": claim_eligible,
        "whitelist_hash": sha256_obj(claim_eligible),
    }
    write_json(claim_manifest, paths["claim_eligibility"])

    rejected_rows = list(read_jsonl(paths["stealth_rejected"]))
    rejected_count = len(rejected_rows)
    rejected_pairs = len(
        {
            str(row.get("pair_id") or "")
            for row in rejected_rows
            if str(row.get("pair_id") or "")
        }
    )
    insufficient_sources: dict[str, int] = {}
    duplicate_query_text_pairs = 0
    for manifest in wave_manifests:
        upstream = read_json(
            manifest["outputs"]["stealth_manifest"]["path"]
        ).get("fixed_budget") or {}
        insufficient_sources.update(
            {
                str(key): int(value)
                for key, value in (
                    upstream.get("insufficient_sources") or {}
                ).items()
                if str(key) in retained_sources
            }
        )
        if not bool(plan.get("exact_target_stop", False)):
            duplicate_query_text_pairs += int(
                upstream.get("duplicate_query_text_pairs", 0)
            )
    stealth_manifest = {
        "output_path": str(canonical_paths["stealth"].resolve()),
        "rejected_path": str(
            canonical_paths["stealth_rejected"].resolve()
        ),
        "accepted": fixed_budget["eligible_sources"]
        * fixed_budget["queries_per_source"],
        "rejected": rejected_count,
        "accepted_pairs": fixed_budget["selected_pairs"],
        "rejected_pairs": rejected_pairs,
        "fixed_budget": {
            **fixed_budget,
            "insufficient_sources": insufficient_sources,
            "duplicate_query_text_pairs": duplicate_query_text_pairs,
            "enabled": True,
        },
        "embedding_model": (
            attack_config.get("stealth_filter", {}).get(
                "embedding_model"
            )
        ),
        "embedding_local_files_only": bool(
            attack_config.get("stealth_filter", {}).get(
                "embedding_local_files_only",
                False,
            )
        ),
        "embedding_batch_size": int(
            attack_config.get("stealth_filter", {}).get(
                "embedding_batch_size",
                256,
            )
        ),
        **common_scan,
    }
    write_json(
        stealth_manifest,
        paths["stealth_manifest"],
    )

    capacity_status = (
        "passed"
        if state["stop_status"] == "target_reached"
        else "buffer_shortfall_requires_protocol_decision"
        if state["stop_status"] == "buffer_shortfall"
        else "insufficient"
    )
    query_cfg = dict(attack_config.get("paired_queries", {}))
    stealth_cfg = dict(attack_config.get("stealth_filter", {}))
    query_manifest = {
        "dataset": plan["dataset"],
        "protocol": query_protocol,
        "claim_eligibility_protocol": claim_protocol,
        "claim_eligibility_hash": sha256_file(
            paths["claim_eligibility"]
        ),
        **common_scan,
        "eligibility_probe": claim_manifest["eligibility_probe"],
        "minimum_valid_claims": plan["minimum_valid_claims"],
        "minimum_stealth_pairs": plan["minimum_stealth_pairs"],
        "queries_per_source": int(plan["minimum_stealth_pairs"]) * 2,
        "query_text_uniqueness_enforced": True,
        "claim_validator_version": VALIDATOR_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "query_types": ["compressed_verification"],
        "formal_query_types": query_cfg.get(
            "query_types",
            ["diverse_slotted_verification"],
        ),
        "embedding_model": stealth_cfg.get("embedding_model"),
        "embedding_local_files_only": bool(
            stealth_cfg.get("embedding_local_files_only", False)
        ),
        "stealth_thresholds": {
            "min_naturalness": float(
                stealth_cfg.get("min_naturalness", 0.55)
            ),
            "max_context_probe": float(
                stealth_cfg.get("max_context_probe", 0.5)
            ),
            "max_prompt_injection": float(
                stealth_cfg.get("max_prompt_injection", 0.5)
            ),
            "max_five_gram_containment": float(
                stealth_cfg.get("max_five_gram_containment", 0.35)
            ),
            "max_longest_common_token_run": int(
                stealth_cfg.get("max_longest_common_token_run", 8)
            ),
        },
        "processed_path": plan["processed_path"],
        "processed_hash": plan["processed_sha256"],
        "candidate_claims_hash": sha256_file(paths["claims"]),
        "candidate_queries_hash": sha256_file(paths["queries"]),
        "candidate_stealth_queries_hash": sha256_file(
            paths["stealth"]
        ),
        "semantic_entity_resolver": semantic_metadata,
        "required_source_count": plan["required_formal_sources"],
        "capacity_status": capacity_status,
        "source_count": scanned_source_count,
        "claim_eligible_source_count": len(claim_eligible),
        "eligible_source_count": len(eligible),
        "excluded_source_count": scanned_source_count - len(eligible),
        "stealth_pair_count_distribution": {
            int(plan["minimum_stealth_pairs"]): len(eligible)
        },
        "eligible_source_keys": eligible,
        "whitelist_hash": sha256_obj(eligible),
        "fixed_budget_plan_hash": fixed_budget[
            "fixed_budget_plan_hash"
        ],
    }
    write_json(query_manifest, paths["query_eligibility"])

    promoted_names = (
        "benchmark",
        "facts",
        "claims",
        "queries",
        "stealth",
        "stealth_rejected",
        "claim_eligibility",
        "query_eligibility",
        "stealth_manifest",
    )
    for name in promoted_names:
        _promote_staged_file(paths[name], canonical_paths[name])

    finalization_identity = {
        "protocol": plan["protocol"],
        "scan_plan_sha256": plan["scan_plan_sha256"],
        "scan_checkpoint_sha256": sha256_file(checkpoint_path),
        "retained_source_end": retained_source_end,
        **_enron_capacity_artifact_identity(plan),
        "outputs": {
            name: {
                "path": str(canonical_paths[name].resolve()),
                "sha256": sha256_file(canonical_paths[name]),
            }
            for name in promoted_names
        },
        "api_calls_performed": 0,
        "retriever_runs": 0,
    }
    finalization_manifest = {
        **finalization_identity,
        "finalization_identity_sha256": sha256_obj(
            finalization_identity
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(finalization_manifest, paths["finalization_manifest"])
    _promote_staged_file(
        paths["finalization_manifest"],
        canonical_paths["finalization_manifest"],
    )
    finalized = _validate_finalization_manifest(
        canonical_paths["finalization_manifest"],
        plan=plan,
        checkpoint_path=checkpoint_path,
    )
    _cleanup_prediction_caches(output_dir)
    return finalized


def _resolve_runtime_paths(
    args: argparse.Namespace,
    data_config: dict[str, Any],
    scan_config: dict[str, Any],
) -> tuple[Path, Path, Path]:
    processed_path = (
        resolve_path(args.processed_path)
        if args.processed_path
        else resolve_path(data_config["paths"]["processed_dir"])
        / f"{args.dataset}.jsonl"
    )
    processed_manifest = processed_path.with_suffix(".manifest.json")
    configured_eligibility = resolve_path(
        data_config["datasets"][args.dataset][
            "source_eligibility_path"
        ]
    )
    if args.output_dir:
        output_dir = resolve_path(args.output_dir)
    elif scan_config.get("output_dir"):
        output_dir = resolve_path(scan_config["output_dir"])
    else:
        configured_dir = configured_eligibility.parent
        configured_cap_dir = configured_dir.parent
        if configured_cap_dir.name != "cap_5":
            raise RuntimeError(
                "Configured v6.3 eligibility path must live under cap_5"
            )
        output_dir = (
            configured_dir
            if int(args.cap) == 5
            else configured_cap_dir.parent
            / f"cap_{int(args.cap)}"
            / args.dataset
        )
    return processed_path, processed_manifest, output_dir


def main() -> int:
    args = parse_args()
    if args.execute and not args.resume:
        raise RuntimeError(
            "Execution requires a separately frozen plan: run once without "
            "--execute, then use --resume --execute."
        )
    if args.max_new_waves is not None and not args.execute:
        raise ValueError("--max-new-waves requires --execute")

    data_config_path = Path(args.data_config).resolve()
    attack_config_path = Path(args.attack_config).resolve()
    data_config = load_yaml(data_config_path)
    attack_config = load_yaml(attack_config_path)
    scan_config_path = (
        Path(args.scan_config).resolve()
        if args.scan_config
        else None
    )
    if scan_config_path is not None:
        if not scan_config_path.is_file():
            raise FileNotFoundError(scan_config_path)
        scan_payload = load_yaml(scan_config_path)
        raw_scan_config = (
            scan_payload.get("eligibility_scan", scan_payload)
            if isinstance(scan_payload, dict)
            else {}
        )
    else:
        raw_scan_config = data_config.get("eligibility_scan", {})
    scan_config = _validate_scan_config(
        dict(raw_scan_config),
        selected_cap=int(args.cap),
    )
    if (
        scan_config.get("dataset") is not None
        and scan_config.get("dataset") != args.dataset
    ):
        raise RuntimeError(
            "Eligibility scan config/dataset mismatch: "
            f"config={scan_config.get('dataset')!r} "
            f"cli={args.dataset!r}"
        )
    _validate_capacity_cli_overrides(
        scan_config,
        processed_path_override=args.processed_path,
        output_dir_override=args.output_dir,
    )
    calibration = {
        **_calibration_identity(attack_config),
        **_sampling_frame_identity(scan_config),
        **_enron_capacity_role_identity(
            scan_config=scan_config,
            attack_config=attack_config,
            manual_execution_acknowledged=bool(
                args.manual_user_owned_capacity_run
            ),
        ),
        **_entity_policy_release_identity(
            scan_config=scan_config,
            attack_config=attack_config,
            release_gate_path=args.release_gate,
        ),
    }
    processed_path, processed_manifest, output_dir = (
        _resolve_runtime_paths(args, data_config, scan_config)
    )
    for required_path in (
        processed_path,
        processed_manifest,
        data_config_path,
        attack_config_path,
    ):
        if not required_path.is_file():
            raise FileNotFoundError(required_path)
    calibration.update(
        _enron_capacity_upstream_identity(
            scan_config=scan_config,
            data_config=data_config,
            processed_path=processed_path,
            processed_manifest_path=processed_manifest,
            output_dir=output_dir,
        )
    )
    plan_path = _plan_paths(output_dir)["plan"]

    if args.resume:
        if not plan_path.is_file():
            raise FileNotFoundError(
                f"Frozen scan plan is missing: {plan_path}"
            )
        plan = read_json(plan_path)
        source_order, candidates = validate_scan_plan(
            plan,
            dataset=args.dataset,
            processed_path=processed_path,
            processed_manifest_path=processed_manifest,
            data_config_path=data_config_path,
            attack_config_path=attack_config_path,
            output_dir=output_dir,
            scan_config=scan_config,
            calibration_identity=calibration,
            scan_config_path=scan_config_path,
        )
    else:
        plan = create_scan_plan(
            dataset=args.dataset,
            processed_path=processed_path,
            processed_manifest_path=processed_manifest,
            data_config_path=data_config_path,
            attack_config_path=attack_config_path,
            output_dir=output_dir,
            scan_config=scan_config,
            calibration_identity=calibration,
            scan_config_path=scan_config_path,
        )
        source_payload = read_json(plan["source_order_path"])
        source_order = [
            str(value)
            for value in source_payload["source_order"]
        ]
        candidates = list(read_jsonl(plan["candidate_benchmark_path"]))

    if not args.execute:
        print(
            json.dumps(
                {
                    "status": (
                        "preregistered_not_executed"
                        if not args.resume
                        else "preregistered_validated_not_executed"
                    ),
                    "dataset": args.dataset,
                    "scan_plan_sha256": plan["scan_plan_sha256"],
                    "source_count": len(source_order),
                    "source_universe_count": plan[
                        "source_universe_count"
                    ],
                    "candidate_pool_target_sources": plan[
                        "candidate_pool_target_sources"
                    ],
                    "candidate_pool_shortfall_count": plan[
                        "candidate_pool_shortfall_count"
                    ],
                    "wave_size": plan["wave_size"],
                    "target_query_eligible_sources": plan[
                        "target_query_eligible_sources"
                    ],
                    "api_calls_performed": 0,
                    "retriever_runs": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0

    latest_checkpoint, latest_checkpoint_path = load_latest_checkpoint(
        output_dir,
        plan,
    )
    completed = (
        latest_checkpoint.get("completed_waves", [])
        if latest_checkpoint
        else []
    )
    for record in completed:
        validate_completed_wave(record, plan)

    semantic_runtime = resolve_semantic_runtime(
        dict(
            attack_config.get("fact_extraction", {}).get(
                "semantic_resolver",
                {},
            )
        ),
        dataset=args.dataset,
    )

    candidates_by_source: dict[str, list[dict[str, Any]]] = {
        source_key: [] for source_key in source_order
    }
    for row in candidates:
        candidates_by_source[str(row["source_key"])].append(row)

    def process_wave(
        wave_index: int,
        wave_keys: list[str],
        start: int,
        end: int,
    ) -> dict[str, Any]:
        resolver, metadata = semantic_runtime
        if resolver is None:
            raise RuntimeError("Formal eligibility requires semantic resolver")
        cache_path = (
            output_dir
            / "prediction_cache"
            / f"wave_{wave_index:04d}.sqlite3"
        )
        resolver.configure_prediction_cache(
            cache_path,
            identity={
                "dataset": args.dataset,
                "scan_protocol": plan["protocol"],
                "scan_plan_sha256": plan["scan_plan_sha256"],
                "wave_index": wave_index,
                "wave_source_keys_hash": sha256_obj(wave_keys),
                "model_lock_sha256": plan["model_lock_sha256"],
                "model_runtime_sha256": sha256_obj(metadata.models),
                "semantic_schema_sha256": plan[
                    "semantic_schema_sha256"
                ],
                "semantic_thresholds_sha256": plan[
                    "semantic_thresholds_sha256"
                ],
                "runtime_device": metadata.runtime_device,
                "runtime_precision": (
                    "fp16" if metadata.use_fp16 else "fp32"
                ),
                "requested_batch_size": metadata.batch_size,
            },
        )
        try:
            return run_pipeline_wave(
                wave_index=wave_index,
                wave_source_keys=wave_keys,
                source_start=start,
                source_end=end,
                candidates_by_source=candidates_by_source,
                dataset=args.dataset,
                processed_path=processed_path,
                output_dir=output_dir,
                attack_config=attack_config,
                plan=plan,
                semantic_resolver_runtime=semantic_runtime,
            )
        finally:
            resolver.close_prediction_cache()

    checkpoint_holder: list[Path] = []

    def on_wave_complete(state: dict[str, Any]) -> None:
        checkpoint_holder.append(
            write_checkpoint(output_dir, plan, state)
        )

    state = execute_wave_schedule(
        source_order,
        wave_size=int(plan["wave_size"]),
        target_query_eligible_sources=int(
            plan["target_query_eligible_sources"]
        ),
        required_formal_sources=int(plan["required_formal_sources"]),
        process_wave=process_wave,
        completed_waves=completed,
        on_wave_complete=on_wave_complete,
        max_new_waves=args.max_new_waves,
        scan_full_candidate_pool=bool(
            plan["scan_full_candidate_pool"]
        ),
        exact_target_stop=bool(plan.get("exact_target_stop", False)),
    )
    if checkpoint_holder:
        latest_checkpoint_path = checkpoint_holder[-1]
    if state["stop_status"] == "paused":
        print(
            json.dumps(
                {
                    "status": "paused",
                    "checkpoint": str(latest_checkpoint_path),
                    "scanned_source_count": state[
                        "scanned_source_count"
                    ],
                    "eligible_source_count": state[
                        "eligible_source_count"
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0
    if latest_checkpoint_path is None:
        raise RuntimeError("Terminal scan has no checkpoint")

    final = finalize_scan(
        state=state,
        plan=plan,
        checkpoint_path=latest_checkpoint_path,
        output_dir=output_dir,
        attack_config=attack_config,
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in final.items()
                if key != "eligible_source_keys"
            },
            ensure_ascii=False,
        )
    )
    if state["stop_status"] == "target_reached":
        return 0
    if state["stop_status"] == "buffer_shortfall":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
