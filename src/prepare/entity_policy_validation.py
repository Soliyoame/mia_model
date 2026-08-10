"""v21 实体类型修复的只读证据、pilot 与 release 门禁。"""

from __future__ import annotations

import hashlib
import heapq
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..attack.entity_type_policy import (
    ENTITY_TYPE_POLICY_SHA256,
    ENTITY_TYPE_POLICY_VERSION,
    SEMANTIC_TARGET_TYPES,
    SUPPORTED_ENTITY_TYPES,
    entity_policy_metadata,
)
from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import ensure_dir, read_json, read_jsonl, write_json, write_jsonl
from .entity_policy_release import (
    FORMAL_SCAN_PROTOCOL,
    RELEASE_GATE_PROTOCOL,
    validate_release_gate,
)
from .formal_evidence_scope import (
    DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES,
    FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE,
    FORMAL_AUDIT_ACCEPTED_PER_TYPE,
    FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE,
    FORMAL_AUDIT_HARD_NEGATIVES_PER_TYPE,
    FORMAL_AUDIT_MIN_ACCEPTED_PASSES_PER_DATASET_TYPE,
    FORMAL_AUDIT_MIN_ACCEPTED_PASSES_PER_TYPE,
    FORMAL_AUDIT_MIN_ACCEPTED_RATE_PER_DATASET_TYPE,
    FORMAL_AUDIT_MIN_ACCEPTED_RATE_PER_TYPE,
    FORMAL_AUDIT_MIN_WILSON_PER_DATASET_TYPE,
    FORMAL_AUDIT_MIN_WILSON_PER_TYPE,
    FORMAL_AUDIT_ROWS_PER_DATASET,
    FORMAL_AUDIT_ROWS_PER_DATASET_TYPE,
    FORMAL_AUDIT_ROWS_PER_TYPE,
    FORMAL_AUDIT_TOTAL_ROWS,
    FORMAL_AUDIT_USER_REVIEW_PER_DATASET_TYPE,
    FORMAL_AUDIT_USER_REVIEW_SAMPLE_SIZE,
    FORMAL_MINIMUM_DATASET_TYPE_VALID_PAIRS,
    FORMAL_MINIMUM_GLOBAL_VALID_PAIRS,
    FORMAL_SEMANTIC_ENTITY_TYPES,
    formal_evidence_scope_metadata,
    validate_formal_evidence_scope_metadata,
)
from .formal_dataset_role_scope import (
    CAPACITY_QUALIFIED_PRIMARY_DATASETS,
    ENRON_CAPACITY_PROMOTION_PROTOCOL,
    MAIN_TABLE_DATASETS,
    STANDARD_PRIMARY_DATASETS,
    evaluate_dataset_report_roles,
    formal_dataset_role_scope_metadata,
    validate_audit_dataset,
    validate_capacity_qualification_evidence,
    validate_formal_dataset_role_scope_metadata,
)
from .eligibility_scan import (
    canonical_source_key,
    freeze_source_plan,
    load_latest_checkpoint,
    validate_completed_wave,
)


ENTITY_POLICY_VALIDATION_PROTOCOL = "v21_entity_policy_validation_v1"
HISTORICAL_REPLAY_PROTOCOL = "v21_entity_policy_historical_replay_v1"
PILOT_PROTOCOL = "v21_entity_policy_pilot_v1"
AUDIT_PROTOCOL = "v21_entity_policy_audit_v4_dataset_stratified_r1"
PILOT_SALT = "pcv-v21-entity-policy-pilot-20260805"
PILOT_COHORTS = ("A", "B", "C")
PILOT_SOURCES_PER_DATASET = 500

DEFAULT_SCAN_ROOTS: Mapping[str, str] = {
    "edgar": "artifacts/v21/eligibility/cap_5/edgar",
    "enron": "artifacts/v21/enron_full/eligibility/cap_5/enron",
    "pubmed": "artifacts/v21/eligibility/cap_5/pubmed",
}
MINIMUM_REPLAY_SOURCES: Mapping[str, int] = {
    "edgar": 3500,
    "enron": 1250,
    "pubmed": 1000,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _hash_rank(salt: str, dataset: str, source_key: str) -> str:
    payload = f"{salt}\0{dataset}\0{source_key}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    """返回二项比例的双侧 95% Wilson 下界。"""

    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("Invalid successes/total for Wilson interval")
    proportion = successes / total
    denominator = 1.0 + (z * z / total)
    centre = proportion + z * z / (2.0 * total)
    radius = z * math.sqrt(
        proportion * (1.0 - proportion) / total
        + z * z / (4.0 * total * total)
    )
    return (centre - radius) / denominator


def _checkpoint_inventory(
    project_root: Path,
    dataset: str,
    scan_root: Path,
) -> dict[str, Any]:
    plan_path = scan_root / "scan_plan.json"
    order_path = scan_root / "scan_source_order.json"
    if not plan_path.is_file() or not order_path.is_file():
        raise RuntimeError(f"Missing old scan plan/source order: {scan_root}")
    plan = read_json(plan_path)
    checkpoint, checkpoint_path = load_latest_checkpoint(scan_root, plan)
    if checkpoint is None or checkpoint_path is None:
        raise RuntimeError(f"No completed checkpoint for {dataset}: {scan_root}")
    scanned = int(checkpoint.get("scanned_source_count", 0))
    minimum = int(MINIMUM_REPLAY_SOURCES[dataset])
    if scanned < minimum:
        raise RuntimeError(
            f"{dataset}: historical replay needs at least {minimum} sources, "
            f"found {scanned}"
        )

    completed_waves: list[dict[str, Any]] = []
    scanned_source_keys: list[str] = []
    for record in checkpoint.get("completed_waves") or []:
        manifest = validate_completed_wave(dict(record), plan)
        keys = [str(item) for item in manifest.get("wave_source_keys") or []]
        scanned_source_keys.extend(keys)
        completed_waves.append(
            {
                "wave_index": int(manifest["wave_index"]),
                "source_start": int(manifest["source_start"]),
                "source_end": int(manifest["source_end"]),
                "source_keys": keys,
                "source_keys_sha256": sha256_obj(keys),
                "wave_manifest_path": str(Path(record["wave_manifest_path"]).resolve()),
                "wave_manifest_sha256": str(record["wave_manifest_sha256"]),
                "wave_identity_sha256": str(record["wave_identity_sha256"]),
                "outputs": manifest["outputs"],
                "old_eligible_source_count": int(
                    manifest.get("eligible_source_count", 0)
                ),
            }
        )
    if len(scanned_source_keys) != scanned or len(set(scanned_source_keys)) != scanned:
        raise RuntimeError(f"{dataset}: completed wave source coverage is inconsistent")

    order_payload = read_json(order_path)
    source_order = [str(item) for item in order_payload.get("source_order") or []]
    if source_order[:scanned] != scanned_source_keys:
        raise RuntimeError(f"{dataset}: checkpoint is not an exact source-order prefix")

    old_eligible = int(checkpoint.get("eligible_source_count", 0))
    return {
        "dataset": dataset,
        "scan_root": str(scan_root.resolve()),
        "scan_plan_path": str(plan_path.resolve()),
        "scan_plan_sha256": sha256_file(plan_path),
        "source_order_path": str(order_path.resolve()),
        "source_order_file_sha256": sha256_file(order_path),
        "source_order_sha256": sha256_obj(source_order),
        "source_order_count": len(source_order),
        "candidate_benchmark_path": str(
            (scan_root / "scan_candidate_benchmark.jsonl").resolve()
        ),
        "candidate_benchmark_sha256": sha256_file(
            scan_root / "scan_candidate_benchmark.jsonl"
        ),
        "latest_checkpoint_path": str(checkpoint_path.resolve()),
        "latest_checkpoint_sha256": sha256_file(checkpoint_path),
        "scanned_source_count": scanned,
        "scanned_source_keys": scanned_source_keys,
        "scanned_source_keys_sha256": sha256_obj(scanned_source_keys),
        "old_eligible_source_count": old_eligible,
        "old_eligible_rate": old_eligible / scanned,
        "completed_waves": completed_waves,
    }


def build_historical_inventory(
    project_root: str | Path,
    output_path: str | Path,
    *,
    scan_roots: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """验证旧 checkpoint 链并冻结所有完整 wave。"""

    frozen_path = Path(output_path).resolve()
    if frozen_path.is_file():
        return validate_historical_inventory(frozen_path)
    root = Path(project_root).resolve()
    configured = scan_roots or DEFAULT_SCAN_ROOTS
    datasets = {
        dataset: _checkpoint_inventory(
            root,
            dataset,
            _resolve(root, configured[dataset]),
        )
        for dataset in ("edgar", "enron", "pubmed")
    }
    payload: dict[str, Any] = {
        "protocol": ENTITY_POLICY_VALIDATION_PROTOCOL,
        "status": "frozen",
        "created_at": _utc_now(),
        "entity_policy": entity_policy_metadata(),
        "datasets": datasets,
        "api_calls_performed": 0,
        "retriever_runs": 0,
    }
    payload["inventory_identity_sha256"] = sha256_obj(
        {key: value for key, value in payload.items() if key != "created_at"}
    )
    write_json(payload, output_path)
    return payload


def validate_historical_inventory(
    inventory_path: str | Path,
) -> dict[str, Any]:
    payload = read_json(inventory_path)
    if payload.get("protocol") != ENTITY_POLICY_VALIDATION_PROTOCOL:
        raise RuntimeError("Historical inventory protocol mismatch")
    identity = {
        key: value
        for key, value in payload.items()
        if key not in {"created_at", "inventory_identity_sha256"}
    }
    if sha256_obj(identity) != payload.get("inventory_identity_sha256"):
        raise RuntimeError("Historical inventory identity mismatch")
    policy = payload.get("entity_policy") or {}
    if (
        policy.get("policy_version") != ENTITY_TYPE_POLICY_VERSION
        or policy.get("policy_sha256") != ENTITY_TYPE_POLICY_SHA256
    ):
        raise RuntimeError("Historical inventory entity policy drift")
    for dataset, row in (payload.get("datasets") or {}).items():
        for path_key, hash_key in (
            ("scan_plan_path", "scan_plan_sha256"),
            ("source_order_path", "source_order_file_sha256"),
            ("candidate_benchmark_path", "candidate_benchmark_sha256"),
            ("latest_checkpoint_path", "latest_checkpoint_sha256"),
        ):
            path = Path(str(row.get(path_key) or ""))
            if not path.is_file() or sha256_file(path) != row.get(hash_key):
                raise RuntimeError(f"{dataset}: historical inventory file drift: {path}")
        for wave in row.get("completed_waves") or []:
            path = Path(str(wave.get("wave_manifest_path") or ""))
            if not path.is_file() or sha256_file(path) != wave.get(
                "wave_manifest_sha256"
            ):
                raise RuntimeError(f"{dataset}: historical wave drift: {path}")
    return payload


def freeze_pilot_cohorts(
    inventory_path: str | Path,
    output_path: str | Path,
    *,
    salt: str = PILOT_SALT,
    sources_per_dataset: int = PILOT_SOURCES_PER_DATASET,
) -> dict[str, Any]:
    """在完整 processed universe 中预冻结三个互斥未回放 cohort。"""

    frozen_path = Path(output_path).resolve()
    if frozen_path.is_file():
        return validate_pilot_plan(frozen_path)
    inventory = validate_historical_inventory(inventory_path)
    required = len(PILOT_COHORTS) * sources_per_dataset
    cohorts: dict[str, dict[str, list[str]]] = {
        cohort: {} for cohort in PILOT_COHORTS
    }
    source_order_hashes: dict[str, str] = {}
    candidate_benchmarks: dict[str, dict[str, Any]] = {}
    output_root = ensure_dir(Path(output_path).resolve().parent)
    candidate_root = ensure_dir(output_root / "pilot_candidates")
    for dataset, row in inventory["datasets"].items():
        old_plan = read_json(row["scan_plan_path"])
        processed_path = Path(str(old_plan.get("processed_path") or ""))
        if (
            not processed_path.is_file()
            or sha256_file(processed_path) != old_plan.get("processed_sha256")
        ):
            raise RuntimeError(f"{dataset}: processed universe drift")
        excluded = set(str(item) for item in row["scanned_source_keys"])
        seen: set[str] = set()
        available: set[str] = set()
        selected_rows: dict[str, list[dict[str, Any]]] = {}
        heap: list[tuple[int, str]] = []
        for item in read_jsonl(processed_path):
            source_key = canonical_source_key(item)
            if not source_key or source_key in excluded:
                continue
            available.add(source_key)
            if source_key in selected_rows:
                selected_rows[source_key].append(dict(item))
                continue
            if source_key in seen:
                continue
            seen.add(source_key)
            rank_value = int(_hash_rank(salt, dataset, source_key), 16)
            if len(heap) < required:
                heapq.heappush(heap, (-rank_value, source_key))
                selected_rows[source_key] = [dict(item)]
                continue
            worst_rank = -heap[0][0]
            if rank_value < worst_rank:
                _, evicted_key = heapq.heapreplace(
                    heap,
                    (-rank_value, source_key),
                )
                selected_rows.pop(evicted_key, None)
                selected_rows[source_key] = [dict(item)]
        if len(available) < required:
            raise RuntimeError(
                f"{dataset}: need {required} unseen pilot sources, "
                f"found {len(available)}"
            )
        chosen = sorted(
            selected_rows,
            key=lambda item: (_hash_rank(salt, dataset, item), item),
        )
        if len(chosen) != required:
            raise RuntimeError(f"{dataset}: pilot heap selection drift")
        for index, cohort in enumerate(PILOT_COHORTS):
            start = index * sources_per_dataset
            cohorts[cohort][dataset] = chosen[start : start + sources_per_dataset]
        source_order_hashes[dataset] = sha256_obj(sorted(available))

        selected = set(chosen)
        _, candidates, _ = freeze_source_plan(
            [
                item
                for source_key in chosen
                for item in selected_rows[source_key]
            ],
            dataset,
            selection_seed=42,
            max_chunks_per_source=5,
        )
        candidate_sources = {
            str(item.get("source_key") or "") for item in candidates
        }
        if candidate_sources != selected:
            missing = sorted(selected - candidate_sources)[:5]
            raise RuntimeError(
                f"{dataset}: pilot candidate coverage drift: {missing}"
            )
        candidate_path = candidate_root / f"{dataset}.jsonl"
        write_jsonl(candidates, candidate_path)
        candidate_benchmarks[dataset] = {
            "path": str(candidate_path.resolve()),
            "sha256": sha256_file(candidate_path),
            "rows": len(candidates),
            "source_count": len(candidate_sources),
            "processed_path": str(processed_path.resolve()),
            "processed_sha256": sha256_file(processed_path),
        }

    all_keys = [
        key
        for cohort in PILOT_COHORTS
        for dataset in ("edgar", "enron", "pubmed")
        for key in cohorts[cohort][dataset]
    ]
    if len(all_keys) != len(set(all_keys)):
        raise RuntimeError("Pilot cohorts overlap across cohort/dataset")
    payload: dict[str, Any] = {
        "protocol": PILOT_PROTOCOL,
        "status": "frozen",
        "created_at": _utc_now(),
        "salt": salt,
        "sources_per_dataset": sources_per_dataset,
        "inventory_path": str(Path(inventory_path).resolve()),
        "inventory_sha256": sha256_file(inventory_path),
        "entity_policy": entity_policy_metadata(),
        "source_order_hashes": source_order_hashes,
        "candidate_benchmarks": candidate_benchmarks,
        "cohorts": cohorts,
        "cohort_hashes": {
            cohort: sha256_obj(cohorts[cohort]) for cohort in PILOT_COHORTS
        },
    }
    payload["pilot_plan_identity_sha256"] = sha256_obj(
        {key: value for key, value in payload.items() if key != "created_at"}
    )
    write_json(payload, output_path)
    return payload


def validate_pilot_plan(path: str | Path) -> dict[str, Any]:
    payload = read_json(path)
    if payload.get("protocol") != PILOT_PROTOCOL:
        raise RuntimeError("Pilot plan protocol mismatch")
    identity = {
        key: value
        for key, value in payload.items()
        if key not in {"created_at", "pilot_plan_identity_sha256"}
    }
    if sha256_obj(identity) != payload.get("pilot_plan_identity_sha256"):
        raise RuntimeError("Pilot plan identity mismatch")
    if sha256_file(payload["inventory_path"]) != payload.get("inventory_sha256"):
        raise RuntimeError("Pilot plan inventory drift")
    policy = payload.get("entity_policy") or {}
    if policy.get("policy_sha256") != ENTITY_TYPE_POLICY_SHA256:
        raise RuntimeError("Pilot plan entity policy drift")
    sources_per_dataset = int(payload.get("sources_per_dataset", 0))
    all_keys: list[str] = []
    for cohort in PILOT_COHORTS:
        rows = payload.get("cohorts", {}).get(cohort, {})
        for dataset in ("edgar", "enron", "pubmed"):
            keys = [str(item) for item in rows.get(dataset) or []]
            if len(keys) != sources_per_dataset or len(set(keys)) != len(keys):
                raise RuntimeError(f"Invalid pilot cohort {cohort}/{dataset}")
            all_keys.extend(keys)
    if len(all_keys) != len(set(all_keys)):
        raise RuntimeError("Pilot cohort overlap detected")
    for dataset in ("edgar", "enron", "pubmed"):
        candidate = (payload.get("candidate_benchmarks") or {}).get(dataset) or {}
        path_value = Path(str(candidate.get("path") or ""))
        candidate_sources = {
            str(row.get("source_key") or "") for row in read_jsonl(path_value)
        } if path_value.is_file() else set()
        expected_sources = {
            key
            for cohort in PILOT_COHORTS
            for key in payload["cohorts"][cohort][dataset]
        }
        if (
            not path_value.is_file()
            or sha256_file(path_value) != candidate.get("sha256")
            or int(candidate.get("source_count", -1))
            != sources_per_dataset * len(PILOT_COHORTS)
            or candidate_sources != expected_sources
        ):
            raise RuntimeError(f"Invalid pilot candidate benchmark: {dataset}")
    expected_cohort_hashes = {
        cohort: sha256_obj(payload["cohorts"][cohort])
        for cohort in PILOT_COHORTS
    }
    if payload.get("cohort_hashes") != expected_cohort_hashes:
        raise RuntimeError("Pilot cohort hash drift")
    return payload


def evaluate_source_gate(
    dataset: str,
    scanned_sources: int,
    eligible_sources: int,
    *,
    stage: str,
    old_eligible_rate: float | None = None,
) -> dict[str, Any]:
    rate = eligible_sources / scanned_sources if scanned_sources else 0.0
    lower = wilson_lower_bound(eligible_sources, scanned_sources)
    reasons: list[str] = []
    if dataset == "enron":
        minimum_rate = 0.10
        minimum_lower = 0.08 if stage == "replay" else 0.075
        minimum_count = 125 if stage == "replay" else 50
        if eligible_sources < minimum_count:
            reasons.append("enron_eligible_count_below_gate")
        if rate < minimum_rate:
            reasons.append("enron_eligible_rate_below_gate")
        if lower < minimum_lower:
            reasons.append("enron_wilson_lower_bound_below_gate")
    else:
        minimum_rate = 0.75
        minimum_lower = 0.70 if stage == "pilot" else 0.0
        if old_eligible_rate is not None:
            minimum_rate = max(minimum_rate, old_eligible_rate - 0.02)
        if rate < minimum_rate:
            reasons.append(f"{dataset}_eligible_rate_below_gate")
        if stage == "pilot" and eligible_sources < 375:
            reasons.append(f"{dataset}_eligible_count_below_gate")
        if stage == "pilot" and lower < minimum_lower:
            reasons.append(f"{dataset}_wilson_lower_bound_below_gate")
    return {
        "dataset": dataset,
        "stage": stage,
        "scanned_sources": scanned_sources,
        "eligible_sources": eligible_sources,
        "eligible_rate": rate,
        "wilson_95_lower": lower,
        "old_eligible_rate": old_eligible_rate,
        "gate_passed": not reasons,
        "failure_reasons": reasons,
    }


def evaluate_type_coverage(
    opportunities: Mapping[str, int],
    valid_pairs: Mapping[str, int],
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    failures: list[str] = []
    for entity_type in sorted(SUPPORTED_ENTITY_TYPES):
        count = int(opportunities.get(entity_type, 0))
        pairs = int(valid_pairs.get(entity_type, 0))
        minimum = 0
        coverage_gate_required = (
            entity_type not in DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES
        )
        if count >= 20 and coverage_gate_required:
            minimum = min(20, max(3, math.ceil(0.02 * count)))
            if pairs < minimum:
                failures.append(f"{entity_type}:valid_pairs_below_coverage_gate")
        rows[entity_type] = {
            "opportunities": count,
            "valid_pairs": pairs,
            "minimum_valid_pairs": minimum,
            "coverage_gate_required": coverage_gate_required,
            "gate_passed": pairs >= minimum,
        }
    return {
        "by_entity_type": rows,
        "gate_passed": not failures,
        "failure_reasons": failures,
    }


def build_dataset_report(
    *,
    dataset: str,
    stage: str,
    source_keys: Sequence[str],
    eligible_source_keys: Iterable[str],
    fact_paths: Sequence[str | Path],
    claim_paths: Sequence[str | Path],
    old_eligible_rate: float | None = None,
) -> dict[str, Any]:
    opportunities: Counter[str] = Counter()
    valid_pairs: Counter[str] = Counter()
    for path in fact_paths:
        opportunities.update(
            str(row.get("entity_type") or "").upper()
            for row in read_jsonl(path)
            if str(row.get("entity_type") or "").upper() in SUPPORTED_ENTITY_TYPES
        )
    for path in claim_paths:
        valid_pairs.update(
            str(row.get("entity_type") or "").upper()
            for row in read_jsonl(path)
            if str(row.get("entity_type") or "").upper() in SUPPORTED_ENTITY_TYPES
        )
    eligible = sorted(set(str(item) for item in eligible_source_keys))
    source_gate = evaluate_source_gate(
        dataset,
        len(source_keys),
        len(eligible),
        stage=stage,
        old_eligible_rate=old_eligible_rate,
    )
    type_gate = evaluate_type_coverage(opportunities, valid_pairs)
    return {
        "protocol": (
            HISTORICAL_REPLAY_PROTOCOL if stage == "replay" else PILOT_PROTOCOL
        ),
        "status": "passed"
        if source_gate["gate_passed"] and type_gate["gate_passed"]
        else "failed",
        "created_at": _utc_now(),
        "dataset": dataset,
        "stage": stage,
        "entity_policy": entity_policy_metadata(),
        "formal_evidence_scope": formal_evidence_scope_metadata(),
        "source_keys_sha256": sha256_obj(list(source_keys)),
        "eligible_source_keys": eligible,
        "eligible_source_keys_sha256": sha256_obj(eligible),
        "source_gate": source_gate,
        "type_gate": type_gate,
        "facts_by_entity_type": dict(opportunities),
        "pairs_by_entity_type": dict(valid_pairs),
        "api_calls_performed": 0,
        "retriever_runs": 0,
    }


def validate_dataset_report(path: str | Path) -> dict[str, Any]:
    """Validate a replay/pilot report before it can enter the release gate."""

    payload = read_json(path)
    if payload.get("protocol") not in {
        HISTORICAL_REPLAY_PROTOCOL,
        PILOT_PROTOCOL,
    }:
        raise RuntimeError("Entity-policy dataset report protocol mismatch")
    identity = {
        key: value
        for key, value in payload.items()
        if key not in {"created_at", "report_identity_sha256"}
    }
    if sha256_obj(identity) != payload.get("report_identity_sha256"):
        raise RuntimeError("Entity-policy dataset report identity mismatch")
    policy = payload.get("entity_policy") or {}
    if (
        policy.get("policy_version") != ENTITY_TYPE_POLICY_VERSION
        or policy.get("policy_sha256") != ENTITY_TYPE_POLICY_SHA256
    ):
        raise RuntimeError("Entity-policy dataset report policy drift")
    if payload.get("formal_evidence_scope") is not None:
        validate_formal_evidence_scope_metadata(
            payload["formal_evidence_scope"],
            allow_legacy_v1=True,
        )
    for path_key, hash_key in (
        ("stage_plan_path", "stage_plan_sha256"),
        ("stage_checkpoint_path", "stage_checkpoint_sha256"),
    ):
        evidence_path = Path(str(payload.get(path_key) or ""))
        if (
            not evidence_path.is_file()
            or sha256_file(evidence_path) != payload.get(hash_key)
        ):
            raise RuntimeError(f"Dataset report evidence drift: {evidence_path}")
    return payload


def prepare_blinded_audit(
    accepted_claim_paths: Sequence[str | Path],
    hard_negative_paths: Sequence[str | Path],
    output_dir: str | Path,
) -> dict[str, Any]:
    """按正式 semantic 类型冻结 accepted 与 hard negative 盲审集。"""

    audit_datasets = sorted(MAIN_TABLE_DATASETS)
    semantic_types = sorted(FORMAL_SEMANTIC_ENTITY_TYPES)
    audit_cells = [
        (dataset, entity_type)
        for dataset in audit_datasets
        for entity_type in semantic_types
    ]
    accepted: dict[tuple[str, str], list[dict[str, Any]]] = {
        cell: [] for cell in audit_cells
    }
    negatives: dict[tuple[str, str], list[dict[str, Any]]] = {
        cell: [] for cell in audit_cells
    }
    for path in accepted_claim_paths:
        for row in read_jsonl(path):
            dataset = str(row.get("dataset") or "").casefold()
            validate_audit_dataset(dataset)
            entity_type = str(row.get("entity_type") or "").upper()
            cell = (dataset, entity_type)
            if cell in accepted:
                accepted[cell].append(dict(row))
    for path in hard_negative_paths:
        for row in read_jsonl(path):
            dataset = str(row.get("dataset") or "").casefold()
            validate_audit_dataset(dataset)
            entity_type = str(row.get("entity_type") or "").upper()
            cell = (dataset, entity_type)
            if cell in negatives:
                negatives[cell].append(dict(row))

    for dataset, entity_type in audit_cells:
        cell = (dataset, entity_type)
        missing = max(
            0,
            FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE - len(negatives[cell]),
        )
        if not missing:
            continue
        same_type = sorted(
            accepted[cell],
            key=lambda row: sha256_obj(
                [
                    AUDIT_PROTOCOL,
                    "synthetic-negative",
                    dataset,
                    entity_type,
                    row,
                ]
            ),
        )
        type_index = semantic_types.index(entity_type)
        donor_type = semantic_types[(type_index + 1) % len(semantic_types)]
        other_type = sorted(
            accepted[(dataset, donor_type)],
            key=lambda row: sha256_obj(
                [
                    AUDIT_PROTOCOL,
                    "wrong-type",
                    dataset,
                    entity_type,
                    row,
                ]
            ),
        )
        half = FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE // 2
        if len(same_type) < half or len(other_type) < missing - half:
            raise RuntimeError(
                f"{dataset}/{entity_type}: insufficient rows for hard negatives"
            )
        generated: list[dict[str, Any]] = []
        for row in same_type[:half]:
            negative = dict(row)
            negative["counterfactual_claim"] = row.get("true_claim")
            negative["audit_hard_negative_reason"] = (
                "counterfactual_equals_true_claim"
            )
            generated.append(negative)
        for row in other_type[: max(0, missing - half)]:
            negative = dict(row)
            negative["entity_type"] = entity_type
            negative.pop("original_semantic_resolution", None)
            negative.pop("counterfactual_semantic_resolution", None)
            negative["semantic_subtype"] = "mismatched_donor_type"
            negative["audit_hard_negative_reason"] = (
                f"declared_{entity_type.casefold()}_contains_{donor_type.casefold()}"
            )
            generated.append(negative)
        negatives[cell].extend(generated[:missing])

    blinded: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for dataset, entity_type in audit_cells:
        cell = (dataset, entity_type)
        accepted_rows = sorted(
            accepted[cell],
            key=lambda row: sha256_obj(
                [
                    AUDIT_PROTOCOL,
                    dataset,
                    entity_type,
                    row.get("source_key"),
                    row.get("pair_id"),
                    row.get("true_claim"),
                ]
            ),
        )
        negative_rows = sorted(
            negatives[cell],
            key=lambda row: sha256_obj(
                [
                    AUDIT_PROTOCOL,
                    dataset,
                    entity_type,
                    row.get("source_key"),
                    row.get("fact_id"),
                    row.get("true_claim"),
                ]
            ),
        )
        if (
            len(accepted_rows) < FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE
            or len(negative_rows)
            < FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE
        ):
            raise RuntimeError(
                f"{dataset}/{entity_type}: audit needs "
                f"{FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE} accepted/"
                f"{FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE} negative, found "
                f"{len(accepted_rows)}/{len(negative_rows)}"
            )
        selected = [
            ("accepted", row)
            for row in accepted_rows[:FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE]
        ] + [
            ("hard_negative", row)
            for row in negative_rows[
                :FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE
            ]
        ]
        for bucket, row in selected:
            audit_id = sha256_obj(
                [
                    AUDIT_PROTOCOL,
                    dataset,
                    entity_type,
                    bucket,
                    row.get("source_key"),
                    row.get("pair_id") or row.get("fact_id"),
                    row.get("true_claim"),
                    row.get("counterfactual_claim"),
                ]
            )[:24]
            blinded.append(
                {
                    "audit_id": audit_id,
                    "dataset": dataset,
                    "source_key": row.get("source_key"),
                    "entity_type": entity_type,
                    "semantic_subtype": (
                        (row.get("original_semantic_resolution") or {}).get("subtype")
                        if isinstance(row.get("original_semantic_resolution"), dict)
                        else row.get("semantic_subtype")
                    ),
                    "true_claim": row.get("true_claim"),
                    "counterfactual_claim": row.get("counterfactual_claim"),
                    "original_entity": row.get("original_entity"),
                    "counterfactual_entity": row.get("counterfactual_entity"),
                    "model_judgment": "",
                    "type_correct": "",
                    "original_supported": "",
                    "single_slot_counterfactual": "",
                    "subtype_preserved": "",
                    "reason_codes": [],
                    "evidence": "",
                }
            )
            key_rows.append(
                {
                    "audit_id": audit_id,
                    "dataset": dataset,
                    "entity_type": entity_type,
                    "expected_policy_decision": bucket,
                    "hard_negative_reason": row.get(
                        "audit_hard_negative_reason"
                    ),
                    "source_path": str(row.get("source_path") or ""),
                    "pair_id": row.get("pair_id"),
                    "fact_id": row.get("fact_id"),
                }
            )

    blinded.sort(key=lambda row: sha256_obj([AUDIT_PROTOCOL, row["audit_id"]]))
    key_rows.sort(key=lambda row: row["audit_id"])
    output = ensure_dir(output_dir)
    blinded_path = output / "entity_policy_audit_blinded.jsonl"
    key_path = output / "entity_policy_audit_key.jsonl"
    write_jsonl(blinded, blinded_path)
    write_jsonl(key_rows, key_path)
    required_user_review_ids: list[str] = []
    for dataset, entity_type in audit_cells:
        cell_ids = [
            str(row["audit_id"])
            for row in key_rows
            if row["dataset"] == dataset
            and row["entity_type"] == entity_type
        ]
        required_user_review_ids.extend(
            sorted(
                cell_ids,
                key=lambda audit_id: sha256_obj(
                    [
                        AUDIT_PROTOCOL,
                        "required-user-review",
                        dataset,
                        entity_type,
                        audit_id,
                    ]
                ),
            )[:FORMAL_AUDIT_USER_REVIEW_PER_DATASET_TYPE]
        )
    required_user_review_ids.sort()
    manifest = {
        "protocol": AUDIT_PROTOCOL,
        "status": "prepared",
        "created_at": _utc_now(),
        "rows": len(blinded),
        "datasets": audit_datasets,
        "rows_per_dataset": FORMAL_AUDIT_ROWS_PER_DATASET,
        "rows_per_dataset_type": FORMAL_AUDIT_ROWS_PER_DATASET_TYPE,
        "accepted_per_dataset_type": FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE,
        "hard_negatives_per_dataset_type": (
            FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE
        ),
        "user_review_per_dataset_type": (
            FORMAL_AUDIT_USER_REVIEW_PER_DATASET_TYPE
        ),
        "rows_per_semantic_type": FORMAL_AUDIT_ROWS_PER_TYPE,
        "accepted_per_semantic_type": FORMAL_AUDIT_ACCEPTED_PER_TYPE,
        "hard_negatives_per_semantic_type": FORMAL_AUDIT_HARD_NEGATIVES_PER_TYPE,
        "formal_evidence_scope": formal_evidence_scope_metadata(),
        "formal_dataset_role_scope": formal_dataset_role_scope_metadata(),
        "blinded_path": str(blinded_path.resolve()),
        "blinded_sha256": sha256_file(blinded_path),
        "key_path": str(key_path.resolve()),
        "key_sha256": sha256_file(key_path),
        "required_user_review_ids": required_user_review_ids,
        "required_user_review_ids_sha256": sha256_obj(
            required_user_review_ids
        ),
        "entity_policy": entity_policy_metadata(),
    }
    manifest["audit_identity_sha256"] = sha256_obj(
        {key: value for key, value in manifest.items() if key != "created_at"}
    )
    write_json(manifest, output / "entity_policy_audit_manifest.json")
    return manifest


def evaluate_audit(
    audit_manifest_path: str | Path,
    assistant_labels_path: str | Path,
    user_review_path: str | Path,
) -> dict[str, Any]:
    manifest = read_json(audit_manifest_path)
    if manifest.get("protocol") != AUDIT_PROTOCOL:
        raise RuntimeError("Audit manifest protocol mismatch")
    validate_formal_evidence_scope_metadata(manifest.get("formal_evidence_scope"))
    validate_formal_dataset_role_scope_metadata(
        manifest.get("formal_dataset_role_scope")
    )
    manifest_identity = {
        key: value
        for key, value in manifest.items()
        if key not in {"created_at", "audit_identity_sha256"}
    }
    if sha256_obj(manifest_identity) != manifest.get("audit_identity_sha256"):
        raise RuntimeError("Audit manifest identity drift")
    for path_key, hash_key in (
        ("blinded_path", "blinded_sha256"),
        ("key_path", "key_sha256"),
    ):
        if sha256_file(manifest[path_key]) != manifest.get(hash_key):
            raise RuntimeError(f"Audit evidence drift: {path_key}")
    for row in read_jsonl(manifest["blinded_path"]):
        validate_audit_dataset(str(row.get("dataset") or ""))
    key = {str(row["audit_id"]): row for row in read_jsonl(manifest["key_path"])}
    for row in key.values():
        validate_audit_dataset(str(row.get("dataset") or ""))
    assistant = {
        str(row["audit_id"]): row for row in read_jsonl(assistant_labels_path)
    }
    if set(assistant) != set(key) or len(assistant) != FORMAL_AUDIT_TOTAL_ROWS:
        raise RuntimeError(
            "Assistant audit must label the exact "
            f"{FORMAL_AUDIT_TOTAL_ROWS} frozen rows"
        )
    invalid_assistant = {
        audit_id: row.get("model_judgment")
        for audit_id, row in assistant.items()
        if str(row.get("model_judgment") or "").casefold()
        not in {"pass", "fail", "uncertain"}
    }
    if invalid_assistant:
        raise RuntimeError(
            f"Invalid assistant model_judgment: {list(invalid_assistant.items())[:5]}"
        )
    user_rows = list(read_jsonl(user_review_path))
    user = {str(row["audit_id"]): row for row in user_rows}
    required_user_rows = [
        str(item) for item in manifest.get("required_user_review_ids") or []
    ]
    required_user = set(required_user_rows)
    if (
        len(required_user) != FORMAL_AUDIT_USER_REVIEW_SAMPLE_SIZE
        or sha256_obj(required_user_rows)
        != manifest.get("required_user_review_ids_sha256")
    ):
        raise RuntimeError("Frozen user-review sample drift")
    for dataset in sorted(MAIN_TABLE_DATASETS):
        for entity_type in sorted(FORMAL_SEMANTIC_ENTITY_TYPES):
            cell_review_count = sum(
                audit_id in required_user
                and str(row.get("dataset") or "").casefold() == dataset
                and str(row.get("entity_type") or "").upper() == entity_type
                for audit_id, row in key.items()
            )
            if cell_review_count != FORMAL_AUDIT_USER_REVIEW_PER_DATASET_TYPE:
                raise RuntimeError(
                    "Frozen user-review dataset/type coverage drift: "
                    f"{dataset}/{entity_type}"
                )
    if (
        len(user) < FORMAL_AUDIT_USER_REVIEW_SAMPLE_SIZE
        or not set(user).issubset(key)
        or not required_user.issubset(user)
    ):
        raise RuntimeError(
            "User review must contain at least "
            f"{FORMAL_AUDIT_USER_REVIEW_SAMPLE_SIZE} frozen audit rows"
        )

    by_dataset_entity_type: dict[str, dict[str, Any]] = {}
    by_type: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    agreements = 0
    compared = 0
    for dataset in sorted(MAIN_TABLE_DATASETS):
        for entity_type in sorted(FORMAL_SEMANTIC_ENTITY_TYPES):
            ids = [
                audit_id
                for audit_id, row in key.items()
                if str(row.get("dataset") or "").casefold() == dataset
                and str(row.get("entity_type") or "").upper() == entity_type
            ]
            accepted_ids = [
                audit_id
                for audit_id in ids
                if key[audit_id]["expected_policy_decision"] == "accepted"
            ]
            negative_ids = [
                audit_id
                for audit_id in ids
                if key[audit_id]["expected_policy_decision"] == "hard_negative"
            ]
            if (
                len(accepted_ids) != FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE
                or len(negative_ids)
                != FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE
            ):
                raise RuntimeError(
                    f"{dataset}/{entity_type}: audit bucket count mismatch"
                )
            accepted_passes = sum(
                str(assistant[audit_id].get("model_judgment") or "").casefold()
                == "pass"
                for audit_id in accepted_ids
            )
            negative_passes = sum(
                str(assistant[audit_id].get("model_judgment") or "").casefold()
                == "fail"
                for audit_id in negative_ids
            )
            accepted_rate = (
                accepted_passes / FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE
            )
            lower = wilson_lower_bound(
                accepted_passes,
                FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE,
            )
            cell_reasons: list[str] = []
            if (
                accepted_passes
                < FORMAL_AUDIT_MIN_ACCEPTED_PASSES_PER_DATASET_TYPE
                or accepted_rate
                < FORMAL_AUDIT_MIN_ACCEPTED_RATE_PER_DATASET_TYPE
                or lower < FORMAL_AUDIT_MIN_WILSON_PER_DATASET_TYPE
            ):
                cell_reasons.append("accepted_precision_gate_failed")
            if (
                negative_passes
                != FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE
            ):
                cell_reasons.append("hard_negative_specificity_gate_failed")
            uncertain_ids = [
                audit_id
                for audit_id in ids
                if str(
                    assistant[audit_id].get("model_judgment") or ""
                ).casefold()
                == "uncertain"
            ]
            if any(audit_id not in user for audit_id in uncertain_ids):
                cell_reasons.append("uncertain_rows_not_fully_reviewed")
            failures.extend(
                f"{dataset}/{entity_type}:{reason}"
                for reason in cell_reasons
            )
            by_dataset_entity_type[f"{dataset}/{entity_type}"] = {
                "dataset": dataset,
                "entity_type": entity_type,
                "accepted_passes": accepted_passes,
                "accepted_rate": accepted_rate,
                "accepted_wilson_95_lower": lower,
                "hard_negative_correct_rejections": negative_passes,
                "uncertain_rows": len(uncertain_ids),
                "gate_passed": not cell_reasons,
                "failure_reasons": cell_reasons,
            }

    for entity_type in sorted(FORMAL_SEMANTIC_ENTITY_TYPES):
        ids = [
            audit_id
            for audit_id, row in key.items()
            if str(row.get("entity_type") or "").upper() == entity_type
        ]
        accepted_ids = [
            audit_id
            for audit_id in ids
            if key[audit_id]["expected_policy_decision"] == "accepted"
        ]
        negative_ids = [
            audit_id
            for audit_id in ids
            if key[audit_id]["expected_policy_decision"] == "hard_negative"
        ]
        if (
            len(accepted_ids) != FORMAL_AUDIT_ACCEPTED_PER_TYPE
            or len(negative_ids) != FORMAL_AUDIT_HARD_NEGATIVES_PER_TYPE
        ):
            raise RuntimeError(f"{entity_type}: audit bucket count mismatch")
        accepted_passes = sum(
            str(assistant[audit_id].get("model_judgment") or "").casefold()
            == "pass"
            for audit_id in accepted_ids
        )
        negative_passes = sum(
            str(assistant[audit_id].get("model_judgment") or "").casefold()
            == "fail"
            for audit_id in negative_ids
        )
        accepted_rate = accepted_passes / FORMAL_AUDIT_ACCEPTED_PER_TYPE
        lower = wilson_lower_bound(
            accepted_passes, FORMAL_AUDIT_ACCEPTED_PER_TYPE
        )
        type_reasons: list[str] = []
        if (
            accepted_passes < FORMAL_AUDIT_MIN_ACCEPTED_PASSES_PER_TYPE
            or accepted_rate < FORMAL_AUDIT_MIN_ACCEPTED_RATE_PER_TYPE
            or lower < FORMAL_AUDIT_MIN_WILSON_PER_TYPE
        ):
            type_reasons.append("accepted_precision_gate_failed")
        if negative_passes != FORMAL_AUDIT_HARD_NEGATIVES_PER_TYPE:
            type_reasons.append("hard_negative_specificity_gate_failed")
        uncertain_ids = [
            audit_id
            for audit_id in ids
            if str(assistant[audit_id].get("model_judgment") or "").casefold()
            == "uncertain"
        ]
        if any(audit_id not in user for audit_id in uncertain_ids):
            type_reasons.append("uncertain_rows_not_fully_reviewed")
        failures.extend(f"{entity_type}:{reason}" for reason in type_reasons)
        by_type[entity_type] = {
            "accepted_passes": accepted_passes,
            "accepted_rate": accepted_rate,
            "accepted_wilson_95_lower": lower,
            "hard_negative_correct_rejections": negative_passes,
            "uncertain_rows": len(uncertain_ids),
            "gate_passed": not type_reasons,
            "failure_reasons": type_reasons,
        }

    for audit_id, row in user.items():
        assistant_label = str(
            assistant[audit_id].get("model_judgment") or ""
        ).casefold()
        user_label = str(row.get("human_judgment") or "").casefold()
        if user_label not in {"pass", "fail"}:
            raise RuntimeError(f"Invalid human_judgment for {audit_id}")
        if assistant_label in {"pass", "fail"}:
            compared += 1
            agreements += int(assistant_label == user_label)
    agreement = agreements / compared if compared else 0.0
    if agreement < 0.90:
        failures.append("assistant_human_agreement_below_gate")
    return {
        "protocol": AUDIT_PROTOCOL,
        "status": "passed" if not failures else "failed",
        "created_at": _utc_now(),
        "formal_evidence_scope": formal_evidence_scope_metadata(),
        "formal_dataset_role_scope": formal_dataset_role_scope_metadata(),
        "by_dataset_entity_type": by_dataset_entity_type,
        "by_entity_type": by_type,
        "human_review_rows": len(user),
        "assistant_human_compared_rows": compared,
        "assistant_human_agreement": agreement,
        "failure_reasons": failures,
        "assistant_labels_path": str(Path(assistant_labels_path).resolve()),
        "assistant_labels_sha256": sha256_file(assistant_labels_path),
        "user_review_path": str(Path(user_review_path).resolve()),
        "user_review_sha256": sha256_file(user_review_path),
        "audit_manifest_path": str(Path(audit_manifest_path).resolve()),
        "audit_manifest_sha256": sha256_file(audit_manifest_path),
    }


def freeze_release_gate(
    output_path: str | Path,
    *,
    inventory_path: str | Path,
    replay_report_paths: Sequence[str | Path],
    pilot_report_paths: Sequence[str | Path],
    audit_report: Mapping[str, Any],
    code_commit: str,
    runtime_tree_sha256: str,
) -> dict[str, Any]:
    """全部离线证据通过后冻结唯一正式 release gate。"""

    inventory = validate_historical_inventory(inventory_path)
    replay_reports = [validate_dataset_report(path) for path in replay_report_paths]
    pilot_reports = [validate_dataset_report(path) for path in pilot_report_paths]
    failures = evaluate_dataset_report_roles(replay_reports, pilot_reports)
    for prefix, reports in (("replay", replay_reports), ("pilot", pilot_reports)):
        for report in reports:
            policy = report.get("entity_policy") or {}
            if policy.get("policy_sha256") != ENTITY_TYPE_POLICY_SHA256:
                failures.append(f"{prefix}_{report.get('dataset')}_policy_drift")
    capacity_qualification_evidence: dict[str, Any] = {}
    try:
        capacity_qualification_evidence = (
            validate_capacity_qualification_evidence()
        )
    except RuntimeError as exc:
        failures.append(f"capacity_qualification_evidence_failed:{exc}")
    semantic_totals = Counter()
    standard_primary_semantic_totals = Counter()
    capacity_qualified_semantic_totals = Counter()
    semantic_by_dataset = {
        dataset: Counter() for dataset in MAIN_TABLE_DATASETS
    }
    for report in replay_reports + pilot_reports:
        dataset = str(report.get("dataset") or "").casefold()
        counts = {
            key: int(value)
            for key, value in (report.get("pairs_by_entity_type") or {}).items()
            if key in SEMANTIC_TARGET_TYPES
        }
        semantic_totals.update(counts)
        semantic_by_dataset[dataset].update(counts)
        if dataset in STANDARD_PRIMARY_DATASETS:
            standard_primary_semantic_totals.update(counts)
        elif dataset in CAPACITY_QUALIFIED_PRIMARY_DATASETS:
            capacity_qualified_semantic_totals.update(counts)
        else:
            raise RuntimeError(f"Unexpected formal report dataset: {dataset}")
    formal_semantic_totals = Counter(
        {
            entity_type: semantic_totals[entity_type]
            for entity_type in FORMAL_SEMANTIC_ENTITY_TYPES
        }
    )
    formal_semantic_by_dataset = {
        dataset: {
            entity_type: semantic_by_dataset[dataset][entity_type]
            for entity_type in FORMAL_SEMANTIC_ENTITY_TYPES
        }
        for dataset in sorted(MAIN_TABLE_DATASETS)
    }
    diagnostic_semantic_totals = Counter(
        {
            entity_type: semantic_totals[entity_type]
            for entity_type in DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES
        }
    )
    for entity_type in sorted(FORMAL_SEMANTIC_ENTITY_TYPES):
        if formal_semantic_totals[entity_type] < FORMAL_MINIMUM_GLOBAL_VALID_PAIRS:
            failures.append(
                f"{entity_type}:global_semantic_pair_count_below_"
                f"{FORMAL_MINIMUM_GLOBAL_VALID_PAIRS}"
            )
    for dataset, counts in formal_semantic_by_dataset.items():
        for entity_type, count in counts.items():
            if count < FORMAL_MINIMUM_DATASET_TYPE_VALID_PAIRS:
                failures.append(
                    f"{dataset}/{entity_type}:semantic_pair_count_below_"
                    f"{FORMAL_MINIMUM_DATASET_TYPE_VALID_PAIRS}"
                )
    if audit_report.get("status") != "passed":
        failures.append("audit_failed")
    try:
        validate_formal_evidence_scope_metadata(
            audit_report.get("formal_evidence_scope")
        )
    except RuntimeError:
        failures.append("audit_formal_evidence_scope_mismatch")
    try:
        validate_formal_dataset_role_scope_metadata(
            audit_report.get("formal_dataset_role_scope")
        )
    except RuntimeError:
        failures.append("audit_formal_dataset_role_scope_mismatch")
    if not code_commit.strip() or not runtime_tree_sha256.strip():
        failures.append("code_identity_missing")

    payload = {
        "protocol": RELEASE_GATE_PROTOCOL,
        "status": "passed" if not failures else "failed",
        "created_at": _utc_now(),
        "entity_policy": entity_policy_metadata(),
        "formal_evidence_scope": formal_evidence_scope_metadata(),
        "formal_dataset_role_scope": formal_dataset_role_scope_metadata(),
        "capacity_qualification_evidence": (
            capacity_qualification_evidence
        ),
        "inventory_path": str(Path(inventory_path).resolve()),
        "inventory_sha256": sha256_file(inventory_path),
        "inventory_identity_sha256": inventory["inventory_identity_sha256"],
        "replay_reports": [
            {"path": str(Path(path).resolve()), "sha256": sha256_file(path)}
            for path in replay_report_paths
        ],
        "pilot_reports": [
            {"path": str(Path(path).resolve()), "sha256": sha256_file(path)}
            for path in pilot_report_paths
        ],
        "audit_report": dict(audit_report),
        "semantic_valid_pairs": dict(semantic_totals),
        "standard_primary_semantic_valid_pairs": dict(
            standard_primary_semantic_totals
        ),
        "capacity_qualified_semantic_valid_pairs": dict(
            capacity_qualified_semantic_totals
        ),
        "formal_semantic_valid_pairs": dict(formal_semantic_totals),
        "formal_semantic_valid_pairs_by_dataset": (
            formal_semantic_by_dataset
        ),
        "diagnostic_semantic_valid_pairs": dict(diagnostic_semantic_totals),
        "code_commit": code_commit,
        "runtime_tree_sha256": runtime_tree_sha256,
        "failure_reasons": failures,
        "formal_scan_identity": FORMAL_SCAN_PROTOCOL,
        "enron_capacity_promotion_identity": (
            ENRON_CAPACITY_PROMOTION_PROTOCOL
        ),
    }
    payload["release_gate_identity_sha256"] = sha256_obj(
        {key: value for key, value in payload.items() if key != "created_at"}
    )
    write_json(payload, output_path)
    return payload
