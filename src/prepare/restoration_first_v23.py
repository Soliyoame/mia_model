"""Fail-closed governance and runtime guards for PCV-MIA v23."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence, TypeVar

from ..attack.restoration_first_v23 import (
    METHOD_VERSION,
    PROTOCOL_VERSION,
    SPECIFICATION_VERSION,
    aggregate_document_frequency,
    build_pair_candidates,
    canonical_json,
    canonical_sha256,
    fresh_extract_candidates,
    normalized_text_sha256,
    reject_forbidden_selection_fields,
    segment_propositions,
    select_top_three,
    text_sha256,
    validate_selector_source_input,
)
from ..attack.semantic_entity_resolver import (
    ALL_SEMANTIC_SCHEMA,
    SemanticPredictionBackend,
    _load_backend,
    _verify_model_lock,
)
from ..utils.hash import sha256_file
from ..utils.io import load_yaml
from ..utils.stage_identity import (
    affected_stages as resolve_affected_stages,
    compute_stage_dependency_fingerprint,
    load_stage_dependency_contract,
    stage_execution_identity,
)


DESIGN_CONFIG = Path("configs/restoration_first_v23.yaml")
DESIGN_MANIFEST = Path("configs/restoration_first_v23.design_manifest.json")
DESIGN_MANIFEST_SHA256 = "6a7163830f36b65247b7d6222f5adecfb18c85695a885cc0384128c81ffbd6fe"
EXECUTION_ERRATUM = Path("configs/restoration_first_v23.execution_erratum_e1.yaml")
EXECUTION_ERRATUM_SHA256 = "4245105e0058a3f8e326f7f1e57175665a2199a1e9ca82bc82402c477b08c279"
EXECUTION_REVISION = "pcv-restoration-first-v23-design-r6-execution-e1"
DEVELOPMENT_RECOVERY_CONTRACT = Path(
    "configs/restoration_first_v23.development_recovery_r1.yaml"
)
DEVELOPMENT_RECOVERY_CONTRACT_SHA256 = (
    "8b57250c66413352afc9707dfa0b582dbc6be2fa3e3816927994f4e2d22056ef"
)
DEVELOPMENT_RECOVERY_REVISION = (
    "pcv-restoration-first-v23-design-r6-execution-e1-development-recovery-r1"
)
IMPLEMENTATION_STAGE = "runtime_implementation_and_tests"
ZERO_SHA256 = "0" * 64
GENESIS_SENTINEL = "genesis_sentinel"
DATASET_ORDER = ("edgar", "enron", "pubmed")
RUNTIME_BUNDLE_FILES = (
    "configs/entity_type_policy_v21_r1.yaml",
    "configs/restoration_first_v23.design_manifest.json",
    "configs/restoration_first_v23.development_recovery_r1.yaml",
    "configs/restoration_first_v23.execution_erratum_e1.yaml",
    "configs/restoration_first_v23.yaml",
    "configs/semantic_entity_models_v6_3.lock.yaml",
    "requirements.txt",
    "scripts/42_run_v23_restoration_first.py",
    "src/attack/attackability_selector.py",
    "src/attack/entity_extractor.py",
    "src/attack/entity_type_policy.py",
    "src/attack/perturbation_generator.py",
    "src/attack/restoration_first_v23.py",
    "src/attack/semantic_entity_resolver.py",
    "src/data/filter.py",
    "src/evaluation/restoration_first_v23.py",
    "src/prepare/restoration_first_v23.py",
    "src/utils/hash.py",
    "src/utils/io.py",
    "src/utils/logger.py",
    "src/utils/stage_identity.py",
    "\u7814\u7a76\u8bb0\u5f55/PCV-MIA_v23_Restoration-First_\u534f\u8bae\u9884\u6ce8\u518c_20260812.md",
)
ARTIFACT_ROOT = Path("artifacts/v23")
BOOTSTRAP_REGISTRY = ARTIFACT_ROOT / "governance/bootstrap_attempt_registry.jsonl"
BOOTSTRAP_AUTH_DIRECTORY = ARTIFACT_ROOT / "governance/runtime_bootstrap_authorizations"
RUNTIME_BUNDLE_DIRECTORY = ARTIFACT_ROOT / "protocol/runtime_bundles"
PROTOCOL_REVISION_DIRECTORY = ARTIFACT_ROOT / "protocol/revisions"
CONSUMPTION_LEDGER = ARTIFACT_ROOT / "governance/consumed_source_ledger.jsonl"
LEDGER_ANCHOR_DIRECTORY = ARTIFACT_ROOT / "governance/ledger_anchors"
BOOTSTRAP_CHECKPOINT_DIRECTORY = ARTIFACT_ROOT / "checkpoints/bootstrap"
BUDGET_DIRECTORY = ARTIFACT_ROOT / "governance/authorization_budgets"
ATTEMPT_REGISTRY = ARTIFACT_ROOT / "governance/attempt_registry.jsonl"
RUN_AUTH_DIRECTORY = ARTIFACT_ROOT / "governance/run_authorizations"
AGGREGATE_DF_DIRECTORY = ARTIFACT_ROOT / "aggregate_df"
STAGE_COMPATIBILITY_DIRECTORY = ARTIFACT_ROOT / "protocol/stage_compatibility"
STAGE_COMPATIBILITY_AUTH_DIRECTORY = (
    ARTIFACT_ROOT / "governance/stage_compatibility_authorizations"
)
REVISION_RESERVATION_DIRECTORY = ARTIFACT_ROOT / "governance/revision_reservations"
DEVELOPMENT_SELECTION_DIRECTORY = ARTIFACT_ROOT / "selection/development"
DEVELOPMENT_GATE_DIRECTORY = ARTIFACT_ROOT / "selection/development_gate"
DEVELOPMENT_RECOVERY_DIRECTORY = (
    ARTIFACT_ROOT / "governance/development_pilot_recoveries"
)
STAGE_CARRY_FORWARD = "stage_artifact_carry_forward"
STAGE_COMPATIBILITY_AUTH_FIELDS = {
    "kind",
    "authorization_id",
    "user_authorization_record",
    "authorized_stage",
    "execution_unit",
    "stage",
    "from_runtime_bundle_sha256",
    "from_protocol_revision_id",
    "to_runtime_bundle_sha256",
    "to_protocol_revision_id",
    "stage_dependency_fingerprint",
    "issued_at",
    "expires_at_or_null",
    "design_manifest_sha256",
    "execution_revision",
    "execution_erratum_sha256",
    "source_pool_contents_read_allowed",
    "ledger_mutation_allowed",
    "external_calls_allowed",
}
STAGE_COMPATIBILITY_FIELDS = {
    "kind",
    "attestation_id",
    "authorization_id",
    "stage",
    "execution_revision",
    "execution_erratum_sha256",
    "from_runtime_bundle_sha256",
    "from_protocol_revision_id",
    "from_stage_execution_identity",
    "to_runtime_bundle_sha256",
    "to_protocol_revision_id",
    "to_stage_execution_identity",
    "stage_dependency_fingerprint",
    "datasets",
    "ledger_tip_sha256",
    "ledger_tip_anchor_sha256",
    "source_pool_contents_read",
    "ledger_mutation",
    "external_calls_performed",
    "created_at",
}
STAGE_COMPATIBILITY_DATASET_FIELDS = {
    "dataset",
    "authorization_id",
    "attempt_id",
    "source_count",
    "token_count",
    "token_df_rows_file_sha256",
    "df_manifest_file_sha256",
    "run_authorization_file_sha256",
    "budget_journal_file_sha256",
    "checkpoint_file_sha256",
}
SUCCESSOR_FREEZE_AUTH_DIRECTORY = (
    ARTIFACT_ROOT / "governance/runtime_successor_freeze_authorizations"
)
SUCCESSOR_FREEZE_CHECKPOINT_DIRECTORY = ARTIFACT_ROOT / "checkpoints/runtime_freeze"
MODEL_LOCK_PATH = Path("configs/semantic_entity_models_v6_3.lock.yaml")
DEPENDENCY_LOCK_PATH = Path("requirements.txt")
FROZEN_V22_PROTOCOL_IDENTITY_SHA256 = (
    "a488372a733977543f345fa46ed82b6dcc154c32f758595417d5d96c898f1044"
)
FROZEN_SOURCE_ORDER_FILE_SHA256_BY_DATASET = {
    "edgar": "fed738286427549d4d9550166c57c7ec11ee24894be42a08f126e24bfa79073f",
    "enron": "2fdf86050e74cf152c3676c5a97156c3307effbc674155ad15feb609d59eab8c",
    "pubmed": "9db36023cd78672353ff468af57a81343793c66cbb51bd9db93deb9a13f5e432",
}
BOOTSTRAP_REGISTRY_FIELDS = {
    "kind",
    "sequence",
    "bootstrap_attempt_ordinal",
    "bootstrap_attempt_id",
    "previous_row_sha256",
    "row_sha256",
    "allocated_at",
}
BOOTSTRAP_CHECKPOINT_FIELDS = {
    "kind",
    "design_manifest_sha256",
    "bootstrap_attempt_id",
    "authorization_id",
    "status",
    "new_runtime_bundle_sha256",
    "new_protocol_revision_id",
    "genesis_row_sha256",
    "genesis_anchor_sha256",
    "code_commit",
    "completed_at",
}
RUNTIME_BUNDLE_FIELDS = {
    "kind",
    "protocol_version",
    "method_version",
    "specification_version",
    "runtime_bundle_id",
    "design_manifest_sha256",
    "code_commit",
    "python_executable",
    "python_version",
    "dependency_lock_path",
    "dependency_lock_sha256",
    "numpy_version",
    "pcg64_state_golden_sha256",
    "gliner_runtime_identity",
    "files",
    "created_at",
}
SUCCESSOR_FREEZE_AUTH_FIELDS = {
    "kind",
    "authorization_id",
    "user_authorization_record",
    "authorized_stage",
    "execution_unit",
    "expected_prior_runtime_bundle_sha256",
    "expected_prior_protocol_revision_id",
    "expected_prior_ledger_tip_sha256",
    "new_code_commit",
    "new_runtime_bundle_sha256",
    "new_protocol_revision_id",
    "new_revision_ordinal",
    "issued_at",
    "expires_at_or_null",
    "design_manifest_sha256",
    "external_calls_allowed",
}
SUCCESSOR_FREEZE_CHECKPOINT_FIELDS = {
    "kind",
    "authorization_id",
    "status",
    "prior_runtime_bundle_sha256",
    "prior_protocol_revision_id",
    "new_runtime_bundle_sha256",
    "new_protocol_revision_id",
    "new_revision_ordinal",
    "ledger_tip_sha256",
    "code_commit",
    "completed_at",
}
PROTOCOL_REVISION_FIELDS = {
    "kind",
    "specification_version",
    "design_manifest_sha256",
    "runtime_bundle_sha256",
    "revision_ordinal",
    "protocol_revision_id",
}
GENESIS_ANCHOR_FIELDS = {
    "kind",
    "protocol_revision_id",
    "ledger_tip_sha256",
    "genesis_row_sha256",
    "created_at",
}
CHECKPOINT_STATUSES = frozenset({"passed", "failed", "partial", "superseded"})
STAGE_CHECKPOINT_FIELDS = {
    "kind",
    "protocol_revision_id",
    "attempt_id",
    "stage",
    "execution_unit",
    "status",
    "input_ledger_tip_sha256",
    "input_tip_anchor_sha256",
    "output_ledger_tip_sha256",
    "output_tip_anchor_sha256",
    "ledger_mutation",
    "authorization_id",
    "authorization_budget_journal_tip_sha256",
    "runtime_bundle_sha256",
    "output_manifest_sha256",
    "completed_at",
}
RESERVATION_STAGE = "revision_audit_reserve_snapshot_and_write_ahead_registration"
DEVELOPMENT_PILOT_STAGE = "development_pilot_and_capacity_gate"
RESERVE_SNAPSHOT_FIELDS = {
    "kind",
    "specification_version",
    "protocol_revision_id",
    "dataset",
    "prior_ledger_tip_sha256",
    "source_order_file_sha256",
    "ordered_sources",
}
RESERVATION_PRIOR_SNAPSHOT_FIELDS = {
    "kind",
    "protocol_revision_id",
    "common_prior_ledger_tip_sha256",
    "common_prior_tip_anchor_sha256",
    "dataset_order",
    "ordered_reserve_snapshot_sha256",
}
RESERVATION_PLAN_FIELDS = {
    "kind",
    "protocol_revision_id",
    "attempt_id",
    "role",
    "dataset",
    "expected_prior_ledger_tip_sha256",
    "ordered_source_identity_objects",
}
RESERVATION_GROUP_COMPLETION_FIELDS = {
    "kind",
    "protocol_revision_id",
    "common_prior_snapshot_sha256",
    "ordered_reservation_batch_ids",
    "final_ledger_tip_sha256",
    "final_tip_anchor_sha256",
    "created_at",
}
DEVELOPMENT_SOURCE_RESULT_FIELDS = {
    "kind",
    "protocol_revision_id",
    "runtime_bundle_sha256",
    "attempt_id",
    "dataset",
    "source_order_index",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "eligible",
    "selected_pairs",
    "rejection_reasons",
    "candidate_count",
    "pair_candidate_count",
    "hard_gate_violation_count",
    "deterministic_rerun_hash_match",
    "source_result_sha256",
    "completed_at",
}
SELECTED_PAIR_FIELDS = {
    "kind",
    "specification_version",
    "protocol_revision_id",
    "dataset",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "source_order_rank",
    "pair_order",
    "pair_id",
    "fact_signature",
    "relation_signature",
    "supporting_sentence",
    "original_span",
    "original_entity",
    "counterfactual_entity",
    "effective_type",
    "semantic_subtype",
    "true_claim",
    "counterfactual_claim",
    "rank_tuple",
}
DEVELOPMENT_PILOT_MANIFEST_FIELDS = {
    "kind",
    "protocol_revision_id",
    "runtime_bundle_sha256",
    "authorization_id",
    "attempt_id",
    "dataset",
    "reservation_group_completion_sha256",
    "development_batch_anchor_sha256",
    "aggregate_df_manifest_sha256",
    "aggregate_df_rows_sha256",
    "model_runtime_identity",
    "source_count",
    "eligible_source_count",
    "selected_pair_count",
    "selected_pairs_path",
    "selected_pairs_file_sha256",
    "source_result_directory",
    "source_result_group_sha256",
    "rejection_reasons",
    "deterministic_rerun_hash_match",
    "hard_gate_violation_count",
    "capacity_decision",
    "status",
    "external_calls_performed",
    "completed_at",
}
DEVELOPMENT_RECOVERY_ATTESTATION_FIELDS = {
    "kind",
    "recovery_id",
    "recovery_revision",
    "recovery_contract_sha256",
    "dataset",
    "new_authorization_id",
    "new_protocol_revision_id",
    "new_runtime_bundle_sha256",
    "new_attempt_id",
    "reservation_validation_mode",
    "prior_reservation_protocol_revision_id",
    "prior_reservation_runtime_bundle_sha256",
    "prior_reservation_authorization_id",
    "prior_reservation_attempt_id",
    "prior_reservation_group_completion_path",
    "prior_reservation_group_completion_file_sha256",
    "prior_reservation_checkpoint_file_sha256",
    "prior_reservation_final_ledger_tip_sha256",
    "prior_partial_attempt_or_null",
    "created_at",
    "external_calls_performed",
}
DEVELOPMENT_RECOVERY_PARTIAL_FIELDS = {
    "authorization_id",
    "protocol_revision_id",
    "runtime_bundle_sha256",
    "attempt_id",
    "authorization_file_sha256",
    "budget_journal_file_sha256",
    "budget_charge_count",
    "source_result_directory",
    "source_result_count",
    "checkpoint_present",
    "canonical_selected_pairs_present",
    "canonical_pilot_manifest_present",
}
DEVELOPMENT_GATE_MANIFEST_FIELDS = {
    "kind",
    "protocol_revision_id",
    "runtime_bundle_sha256",
    "dataset_order",
    "pilot_manifest_sha256_by_dataset",
    "selected_pairs_file_sha256_by_dataset",
    "cross_dataset_source_hash_overlap",
    "cross_dataset_normalized_text_hash_overlap",
    "status",
    "created_at",
}
LEDGER_ROLES = frozenset(
    {"development", "fresh_audit_reserve", "human_viewed", "diagnostic_viewed", "formal_scan_viewed"}
)
RESERVATION_ROLES_BY_STAGE = {
    "revision_audit_reserve_snapshot_and_write_ahead_registration": frozenset(
        {"development", "fresh_audit_reserve"}
    ),
    "formal_source_scan": frozenset({"formal_scan_viewed"}),
}
STAGE_BUDGETS = {
    "aggregate_df_precomputation": ("sources", "one_dataset"),
    "revision_audit_reserve_snapshot_and_write_ahead_registration": (
        "sources",
        "all_datasets_group",
    ),
    "development_pilot_and_capacity_gate": ("sources", "one_dataset"),
    "fresh_blind_audit": ("sources", "one_dataset"),
    "formal_source_scan": ("sources", "one_dataset"),
    "source_exclusive_split": ("none", "one_dataset"),
    "reserve_only_shadow_gate": ("calls", "one_dataset_one_backend"),
    "release_finalize": ("none", "global"),
    "luna_query_generation": ("calls", "one_dataset"),
    "main_index_build_and_retriever_matrix": ("calls", "one_dataset_one_backend"),
    "matched_rag_and_llm_only_victim_runs": ("calls", "one_dataset_one_victim_cell"),
    "parsing_scoring_and_source_level_evaluation": ("none", "one_metric_cell"),
}

_T = TypeVar("_T")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _resolve(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _assert_exact_fields(value: Mapping[str, Any], expected: set[str], *, kind: str) -> None:
    actual = set(value)
    if actual != expected:
        raise RuntimeError(
            f"{kind}_schema_drift:missing={sorted(expected - actual)}:unknown={sorted(actual - expected)}"
        )


def _read_json_exact(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate_json_key:{key}")
            result[key] = value
        return result

    raw = path.read_text(encoding="utf-8")
    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise RuntimeError(f"json_root_not_object:{path}")
    return value


def _write_canonical_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(value))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_new_canonical_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(value))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_new_atomic_canonical_json(
    path: Path, value: Mapping[str, Any]
) -> None:
    expected = (canonical_json(value) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != expected:
            raise RuntimeError(f"existing_artifact_identity_drift:{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(expected).hexdigest()[:16]
    temporary = path.with_name(f"{path.name}.{digest}.tmp")
    if temporary.exists():
        if temporary.read_bytes() == expected:
            os.replace(temporary, path)
            return
        temporary = path.with_name(f"{path.name}.{digest}.{time.time_ns()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(expected)
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists():
        if path.read_bytes() != expected:
            raise RuntimeError(f"existing_artifact_identity_drift:{path}")
        return
    os.replace(temporary, path)


@contextmanager
def exclusive_lock(path: Path, *, timeout_seconds: float = 5.0) -> Iterator[None]:
    """Use an explicit lock file so append-only operations are process exclusive."""

    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"exclusive_lock_timeout:{path}")
            time.sleep(0.02)
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


def load_design_config(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_yaml(_resolve(DESIGN_CONFIG, root))
    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "method_version": METHOD_VERSION,
        "specification_version": SPECIFICATION_VERSION,
        "status": "design_preregistered_runtime_not_implemented",
        "artifact_root": "artifacts/v23",
    }
    for key, value in expected.items():
        if config.get(key) != value:
            raise RuntimeError(f"v23_design_config_drift:{key}")
    return config


def load_execution_erratum(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = _resolve(EXECUTION_ERRATUM, root)
    if not path.is_file() or sha256_file(path) != EXECUTION_ERRATUM_SHA256:
        raise RuntimeError("v23_execution_erratum_hash_drift")
    contract = load_stage_dependency_contract(path)
    if contract["execution_revision"] != EXECUTION_REVISION:
        raise RuntimeError("v23_execution_erratum_identity_drift")
    return contract


def load_development_recovery_contract(
    project_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = _resolve(DEVELOPMENT_RECOVERY_CONTRACT, root)
    if (
        not path.is_file()
        or sha256_file(path) != DEVELOPMENT_RECOVERY_CONTRACT_SHA256
    ):
        raise RuntimeError("development_recovery_contract_hash_drift")
    contract = load_yaml(path)
    expected = {
        "kind": "pcv_v23_development_pilot_recovery_contract",
        "recovery_revision": DEVELOPMENT_RECOVERY_REVISION,
        "base_execution_revision": EXECUTION_REVISION,
        "scope": (
            "zero_source_result_operational_failure_before_canonical_"
            "development_output"
        ),
        "allowed_datasets": list(DATASET_ORDER),
        "reservation_prerequisite": {
            "validation_mode": "latest_prior_passed_revision_development_only",
            "active_revision_reservation_must_be_absent": True,
            "current_ledger_tip_must_equal_prior_reservation_final_tip": True,
            "development_batch_identity_must_remain_exact": True,
            "fresh_audit_reserve_reuse_authorized": False,
        },
        "partial_attempt_recovery": {
            "prior_protocol_revision_must_differ": True,
            "prior_authorization_must_validate": True,
            "prior_budget_journal_must_validate": True,
            "minimum_prior_budget_charge_count": 1,
            "prior_source_result_count": 0,
            "prior_checkpoint_must_be_absent": True,
            "canonical_selected_pairs_must_be_absent": True,
            "canonical_pilot_manifest_must_be_absent": True,
            "unexpected_legacy_entries_rejected": True,
        },
        "artifact_layout": {
            "source_results_path_pattern": (
                "artifacts/v23/selection/development/<dataset>/attempts/"
                "<attempt_id>/source_results"
            ),
            "canonical_selected_pairs_path_pattern": (
                "artifacts/v23/selection/development/<dataset>/selected_pairs.jsonl"
            ),
            "canonical_pilot_manifest_path_pattern": (
                "artifacts/v23/selection/development/<dataset>/pilot_manifest.json"
            ),
            "recovery_attestation_path_pattern": (
                "artifacts/v23/governance/development_pilot_recoveries/"
                "<authorization_id>.json"
            ),
        },
        "invariants": {
            "old_authorization_budget_and_partial_artifacts_immutable": True,
            "recovery_attestation_required_before_new_source_visibility": True,
            "membership_victim_llm_only_retriever_auc_visible": False,
            "external_calls_allowed": False,
            "failed_or_nonempty_prior_attempt_auto_recovery": False,
        },
    }
    if contract != expected:
        raise RuntimeError("development_recovery_contract_identity_drift")
    return contract


def stage_change_impact(
    change_class: str, project_root: str | Path = "."
) -> list[str]:
    return resolve_affected_stages(load_execution_erratum(project_root), change_class)


def validate_design_bindings(project_root: str | Path = ".") -> dict[str, Any]:
    """Validate the immutable design manifest and all 23 frozen upstream hashes."""

    root = Path(project_root).resolve()
    manifest_path = _resolve(DESIGN_MANIFEST, root)
    if sha256_file(manifest_path) != DESIGN_MANIFEST_SHA256:
        raise RuntimeError("v23_design_manifest_hash_drift")
    manifest = _read_json_exact(manifest_path)
    if manifest.get("runtime_implemented") is not False or manifest.get("external_calls_performed") != 0:
        raise RuntimeError("v23_design_manifest_capability_drift")
    frozen = manifest.get("frozen_upstream_files")
    if not isinstance(frozen, list) or len(frozen) != 23:
        raise RuntimeError("v23_frozen_upstream_count_drift")
    paths = [item.get("path") for item in frozen if isinstance(item, Mapping)]
    if paths != sorted(paths) or len(set(paths)) != 23:
        raise RuntimeError("v23_frozen_upstream_order_drift")
    mismatches: list[str] = []
    for item in frozen:
        if set(item) != {"path", "sha256"}:
            raise RuntimeError("v23_frozen_upstream_schema_drift")
        path = _resolve(item["path"], root)
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            mismatches.append(item["path"])
    if mismatches:
        raise RuntimeError(f"v23_frozen_upstream_hash_drift:{mismatches}")
    return {
        "status": "passed",
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "frozen_upstream_file_count": 23,
        "mismatches": [],
        "external_calls_performed": 0,
    }


def validate_bootstrap_design_identity(project_root: str | Path = ".") -> dict[str, Any]:
    """Validate the design without opening any frozen source-pool artifact."""

    root = Path(project_root).resolve()
    manifest_path = _resolve(DESIGN_MANIFEST, root)
    if not manifest_path.is_file() or sha256_file(manifest_path) != DESIGN_MANIFEST_SHA256:
        raise RuntimeError("v23_design_manifest_hash_drift")
    manifest = _read_json_exact(manifest_path)
    if (
        manifest.get("kind") != "pcv_v23_restoration_first_design_manifest"
        or manifest.get("protocol_version") != PROTOCOL_VERSION
        or manifest.get("method_version") != METHOD_VERSION
        or manifest.get("specification_version") != SPECIFICATION_VERSION
        or manifest.get("runtime_implemented") is not False
        or manifest.get("external_calls_performed") != 0
    ):
        raise RuntimeError("v23_design_manifest_capability_drift")
    frozen = manifest.get("frozen_upstream_files")
    if not isinstance(frozen, list) or len(frozen) != 23:
        raise RuntimeError("v23_frozen_upstream_count_drift")
    by_path = {
        item.get("path"): item.get("sha256")
        for item in frozen
        if isinstance(item, Mapping) and set(item) == {"path", "sha256"}
    }
    expected_orders = {
        f"artifacts/v22/source_pools/{dataset}/source_order.json": digest
        for dataset, digest in FROZEN_SOURCE_ORDER_FILE_SHA256_BY_DATASET.items()
    }
    if any(by_path.get(path) != digest for path, digest in expected_orders.items()):
        raise RuntimeError("v23_design_source_order_binding_drift")
    config = load_design_config(root)
    frozen_v22 = config.get("frozen_v22_bindings")
    if not isinstance(frozen_v22, Mapping):
        raise RuntimeError("v23_design_v22_binding_missing")
    if frozen_v22.get("protocol_identity_sha256") != FROZEN_V22_PROTOCOL_IDENTITY_SHA256:
        raise RuntimeError("v23_design_v22_protocol_identity_drift")
    pools = frozen_v22.get("source_pools")
    if not isinstance(pools, Mapping) or any(
        not isinstance(pools.get(dataset), Mapping)
        or pools[dataset].get("source_order_file_sha256") != digest
        for dataset, digest in FROZEN_SOURCE_ORDER_FILE_SHA256_BY_DATASET.items()
    ):
        raise RuntimeError("v23_design_source_order_config_drift")
    return {
        "status": "passed",
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "frozen_upstream_file_count": 23,
        "source_pool_contents_read": False,
        "external_calls_performed": 0,
    }


def _git_output(root: Path, *arguments: str, text_output: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=text_output,
        encoding="utf-8" if text_output else None,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() if text_output else completed.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"runtime_git_command_failed:{arguments[0]}:{stderr}")
    return completed.stdout


def validate_runtime_commit(
    project_root: str | Path,
    *,
    runtime_files: Sequence[str] | None = None,
) -> str:
    """Require every runtime-closure path to be tracked and clean at HEAD."""

    root = Path(project_root).resolve()
    runtime_files = RUNTIME_BUNDLE_FILES if runtime_files is None else runtime_files
    if str(_git_output(root, "rev-parse", "--show-prefix")).strip():
        raise RuntimeError("runtime_git_root_mismatch")
    head = str(_git_output(root, "rev-parse", "HEAD")).strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        raise RuntimeError("runtime_git_head_invalid")
    normalized = list(runtime_files)
    if normalized != sorted(normalized) or len(normalized) != len(set(normalized)):
        raise RuntimeError("runtime_file_closure_not_canonical")
    dirty = str(
        _git_output(
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *normalized,
        )
    ).strip()
    if dirty:
        raise RuntimeError(f"runtime_file_closure_not_clean:{dirty}")
    for path in normalized:
        candidate = _resolve(path, root)
        if not candidate.is_file():
            raise RuntimeError(f"runtime_file_missing:{path}")
        committed_object = str(_git_output(root, "rev-parse", f"HEAD:{path}")).strip()
        working_object = str(_git_output(root, "hash-object", f"--path={path}", path)).strip()
        if committed_object != working_object:
            raise RuntimeError(f"runtime_file_commit_drift:{path}")
    return head


IMPLEMENTATION_AUTH_FIELDS = {
    "kind",
    "authorization_id",
    "user_authorization_record",
    "authorized_stage",
    "allowed_repository_paths",
    "issued_at",
    "expires_at_or_null",
    "design_manifest_sha256",
    "external_calls_allowed",
}


def validate_implementation_authorization(
    path: str | Path,
    *,
    requested_paths: Sequence[str] = (),
    project_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    authorization = _read_json_exact(_resolve(path, root))
    _assert_exact_fields(authorization, IMPLEMENTATION_AUTH_FIELDS, kind="implementation_authorization")
    if authorization["kind"] != "v23_implementation_authorization":
        raise RuntimeError("implementation_authorization_kind_invalid")
    if authorization["authorized_stage"] != IMPLEMENTATION_STAGE:
        raise RuntimeError("implementation_authorization_stage_invalid")
    if authorization["external_calls_allowed"] is not False:
        raise RuntimeError("implementation_authorization_external_calls_invalid")
    if authorization["design_manifest_sha256"] != DESIGN_MANIFEST_SHA256:
        raise RuntimeError("implementation_authorization_design_drift")
    allowed = authorization["allowed_repository_paths"]
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise RuntimeError("implementation_authorization_paths_invalid")
    if allowed != sorted(allowed) or len(allowed) != len(set(allowed)):
        raise RuntimeError("implementation_authorization_paths_not_canonical")
    if any(Path(item).is_absolute() or ".." in Path(item).parts or "\\" in item for item in allowed):
        raise RuntimeError("implementation_authorization_path_escape")
    if not set(requested_paths).issubset(set(allowed)):
        raise RuntimeError("implementation_authorization_path_not_allowed")
    claimed = authorization["authorization_id"]
    payload = {key: value for key, value in authorization.items() if key != "authorization_id"}
    if not _is_sha256(claimed) or canonical_sha256(payload) != claimed:
        raise RuntimeError("implementation_authorization_identity_drift")
    if authorization["expires_at_or_null"] is not None:
        expiry = datetime.fromisoformat(str(authorization["expires_at_or_null"]).replace("Z", "+00:00"))
        if expiry <= datetime.now(timezone.utc):
            raise RuntimeError("implementation_authorization_expired")
    return authorization


RUN_AUTH_FIELDS = {
    "kind",
    "authorization_id",
    "user_authorization_record",
    "protocol_revision_id",
    "attempt_id",
    "authorized_stage",
    "execution_unit",
    "expected_prior_ledger_tip_sha256",
    "datasets",
    "run_roles",
    "model_or_retriever_cells",
    "budget_kind",
    "budget_limit",
    "issued_at",
    "expires_at_or_null",
    "design_manifest_sha256",
    "runtime_bundle_sha256",
}

BOOTSTRAP_AUTH_FIELDS = {
    "kind",
    "authorization_id",
    "user_authorization_record",
    "authorized_stage",
    "execution_unit",
    "bootstrap_attempt_id",
    "expected_prior_ledger_tip_sha256",
    "issued_at",
    "expires_at_or_null",
    "design_manifest_sha256",
    "external_calls_allowed",
}


def bootstrap_attempt_id(*, bootstrap_attempt_ordinal: int) -> str:
    if isinstance(bootstrap_attempt_ordinal, bool) or bootstrap_attempt_ordinal < 0:
        raise ValueError("bootstrap_attempt_ordinal_invalid")
    return canonical_sha256(
        {
            "kind": "v23_runtime_bootstrap_attempt",
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "stage": "runtime_bundle_and_commit_freeze",
            "execution_unit": "global",
            "bootstrap_attempt_ordinal": bootstrap_attempt_ordinal,
        }
    )


def validate_runtime_bootstrap_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    authorization = dict(value)
    _assert_exact_fields(
        authorization, BOOTSTRAP_AUTH_FIELDS, kind="runtime_bootstrap_authorization"
    )
    constants = {
        "kind": "v23_runtime_bootstrap_authorization",
        "authorized_stage": "runtime_bundle_and_commit_freeze",
        "execution_unit": "global",
        "expected_prior_ledger_tip_sha256": GENESIS_SENTINEL,
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "external_calls_allowed": False,
    }
    if any(authorization[key] != expected for key, expected in constants.items()):
        raise RuntimeError("runtime_bootstrap_authorization_constant_drift")
    if not _is_sha256(authorization["bootstrap_attempt_id"]):
        raise RuntimeError("runtime_bootstrap_attempt_id_invalid")
    claimed = authorization["authorization_id"]
    if not _is_sha256(claimed) or canonical_sha256(
        {key: item for key, item in authorization.items() if key != "authorization_id"}
    ) != claimed:
        raise RuntimeError("runtime_bootstrap_authorization_identity_drift")
    if authorization["expires_at_or_null"] is not None:
        expiry = datetime.fromisoformat(
            str(authorization["expires_at_or_null"]).replace("Z", "+00:00")
        )
        if expiry <= datetime.now(timezone.utc):
            raise RuntimeError("runtime_bootstrap_authorization_expired")
    return authorization


def validate_run_authorization(
    value: Mapping[str, Any],
    *,
    stage: str,
    execution_unit: str,
    attempt_registry_row: Mapping[str, Any],
    dataset: str | None = None,
) -> dict[str, Any]:
    authorization = dict(value)
    _assert_exact_fields(authorization, RUN_AUTH_FIELDS, kind="run_authorization")
    if authorization["kind"] != "v23_run_authorization":
        raise RuntimeError("run_authorization_kind_invalid")
    if authorization["authorized_stage"] != stage or authorization["execution_unit"] != execution_unit:
        raise RuntimeError("run_authorization_scope_mismatch")
    if stage not in STAGE_BUDGETS:
        raise RuntimeError("run_authorization_stage_unknown")
    expected_budget, expected_unit = STAGE_BUDGETS[stage]
    if execution_unit != expected_unit or authorization["budget_kind"] != expected_budget:
        raise RuntimeError("run_authorization_budget_mapping_mismatch")
    budget_limit = authorization["budget_limit"]
    if isinstance(budget_limit, bool) or not isinstance(budget_limit, int) or budget_limit < 0:
        raise RuntimeError("run_authorization_budget_invalid")
    if expected_budget == "none" and budget_limit != 0:
        raise RuntimeError("run_authorization_none_budget_nonzero")
    for key in ("datasets", "run_roles", "model_or_retriever_cells"):
        values = authorization[key]
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise RuntimeError(f"run_authorization_list_invalid:{key}")
        if values != sorted(values) or len(values) != len(set(values)):
            raise RuntimeError(f"run_authorization_list_not_canonical:{key}")
    if dataset is not None and dataset not in authorization["datasets"]:
        raise RuntimeError("run_authorization_dataset_not_allowed")
    for key in ("authorization_id", "protocol_revision_id", "attempt_id", "runtime_bundle_sha256"):
        if not _is_sha256(authorization[key]):
            raise RuntimeError(f"run_authorization_sha256_invalid:{key}")
    if authorization["design_manifest_sha256"] != DESIGN_MANIFEST_SHA256:
        raise RuntimeError("run_authorization_design_drift")
    _assert_exact_fields(
        attempt_registry_row, ATTEMPT_REGISTRY_FIELDS, kind="attempt_registry"
    )
    if attempt_registry_row["kind"] != "v23_attempt_registry_row":
        raise RuntimeError("run_authorization_attempt_registry_kind_invalid")
    if (
        isinstance(attempt_registry_row["sequence"], bool)
        or not isinstance(attempt_registry_row["sequence"], int)
        or attempt_registry_row["sequence"] < 0
        or isinstance(attempt_registry_row["attempt_ordinal"], bool)
        or not isinstance(attempt_registry_row["attempt_ordinal"], int)
        or attempt_registry_row["attempt_ordinal"] < 0
        or not _is_sha256(attempt_registry_row["previous_row_sha256"])
        or not _is_sha256(attempt_registry_row["row_sha256"])
    ):
        raise RuntimeError("run_authorization_attempt_registry_value_invalid")
    if canonical_sha256(
        {
            key: item
            for key, item in attempt_registry_row.items()
            if key != "row_sha256"
        }
    ) != attempt_registry_row["row_sha256"]:
        raise RuntimeError("run_authorization_attempt_registry_row_hash_drift")
    for authorization_key, registry_key in (
        ("protocol_revision_id", "protocol_revision_id"),
        ("attempt_id", "attempt_id"),
        ("authorized_stage", "stage"),
        ("execution_unit", "execution_unit"),
        ("expected_prior_ledger_tip_sha256", "expected_prior_ledger_tip_sha256"),
    ):
        if authorization[authorization_key] != attempt_registry_row[registry_key]:
            raise RuntimeError("run_authorization_attempt_registry_mismatch")
    expected_attempt = attempt_id(
        protocol_revision=attempt_registry_row["protocol_revision_id"],
        stage=attempt_registry_row["stage"],
        execution_unit=attempt_registry_row["execution_unit"],
        attempt_ordinal=attempt_registry_row["attempt_ordinal"],
        expected_prior_ledger_tip_sha256=attempt_registry_row[
            "expected_prior_ledger_tip_sha256"
        ],
    )
    if expected_attempt != authorization["attempt_id"]:
        raise RuntimeError("run_authorization_attempt_identity_drift")
    claimed = authorization["authorization_id"]
    if canonical_sha256({key: item for key, item in authorization.items() if key != "authorization_id"}) != claimed:
        raise RuntimeError("run_authorization_identity_drift")
    if authorization["expires_at_or_null"] is not None:
        expiry = datetime.fromisoformat(
            str(authorization["expires_at_or_null"]).replace("Z", "+00:00")
        )
        if expiry <= datetime.now(timezone.utc):
            raise RuntimeError("run_authorization_expired")
    return authorization


def protocol_revision_id(runtime_bundle_sha256: str, revision_ordinal: int) -> str:
    if not _is_sha256(runtime_bundle_sha256) or revision_ordinal < 0:
        raise ValueError("protocol_revision_identity_invalid")
    return canonical_sha256(
        {
            "kind": "v23_protocol_revision",
            "specification_version": SPECIFICATION_VERSION,
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "runtime_bundle_sha256": runtime_bundle_sha256,
            "revision_ordinal": revision_ordinal,
        }
    )


def attempt_id(
    *,
    protocol_revision: str,
    stage: str,
    execution_unit: str,
    attempt_ordinal: int,
    expected_prior_ledger_tip_sha256: str,
) -> str:
    if not _is_sha256(protocol_revision) or attempt_ordinal < 0:
        raise ValueError("attempt_identity_invalid")
    if expected_prior_ledger_tip_sha256 != GENESIS_SENTINEL and not _is_sha256(expected_prior_ledger_tip_sha256):
        raise ValueError("attempt_prior_tip_invalid")
    return canonical_sha256(
        {
            "kind": "v23_stage_attempt",
            "protocol_revision_id": protocol_revision,
            "stage": stage,
            "execution_unit": execution_unit,
            "attempt_ordinal": attempt_ordinal,
            "expected_prior_ledger_tip_sha256": expected_prior_ledger_tip_sha256,
        }
    )


ATTEMPT_REGISTRY_FIELDS = {
    "kind",
    "sequence",
    "protocol_revision_id",
    "stage",
    "execution_unit",
    "attempt_ordinal",
    "expected_prior_ledger_tip_sha256",
    "attempt_id",
    "previous_row_sha256",
    "row_sha256",
    "allocated_at",
}


def allocate_attempt(
    *,
    registry_path: str | Path,
    protocol_revision: str,
    stage: str,
    execution_unit: str,
    expected_prior_ledger_tip_sha256: str,
) -> dict[str, Any]:
    """Durably allocate the next gap-free ordinal for one exact execution unit."""

    if stage not in STAGE_BUDGETS or not _is_sha256(protocol_revision):
        raise ValueError("attempt_registry_scope_invalid")
    path = Path(registry_path)
    with exclusive_lock(path.with_suffix(path.suffix + ".lock")):
        prior_rows = _read_attempt_registry(path)
        previous = prior_rows[-1]["row_sha256"] if prior_rows else ZERO_SHA256
        matching_ordinals = [
            row["attempt_ordinal"]
            for row in prior_rows
            if row["protocol_revision_id"] == protocol_revision
            and row["stage"] == stage
            and row["execution_unit"] == execution_unit
        ]
        if matching_ordinals != list(range(len(matching_ordinals))):
            raise RuntimeError("attempt_registry_duplicate_or_gap")
        ordinal = len(matching_ordinals)
        identity = attempt_id(
            protocol_revision=protocol_revision,
            stage=stage,
            execution_unit=execution_unit,
            attempt_ordinal=ordinal,
            expected_prior_ledger_tip_sha256=expected_prior_ledger_tip_sha256,
        )
        row = {
            "kind": "v23_attempt_registry_row",
            "sequence": len(prior_rows),
            "protocol_revision_id": protocol_revision,
            "stage": stage,
            "execution_unit": execution_unit,
            "attempt_ordinal": ordinal,
            "expected_prior_ledger_tip_sha256": expected_prior_ledger_tip_sha256,
            "attempt_id": identity,
            "previous_row_sha256": previous,
            "allocated_at": utc_now(),
        }
        row["row_sha256"] = canonical_sha256(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return row


def _read_attempt_registry(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise RuntimeError("attempt_registry_partial_trailing_line")
    rows: list[dict[str, Any]] = []
    previous = ZERO_SHA256
    for sequence, line in enumerate(raw.decode("utf-8").splitlines()):
        row = json.loads(line)
        _assert_exact_fields(row, ATTEMPT_REGISTRY_FIELDS, kind="attempt_registry")
        if row["sequence"] != sequence or row["previous_row_sha256"] != previous:
            raise RuntimeError("attempt_registry_chain_drift")
        if canonical_sha256(
            {key: item for key, item in row.items() if key != "row_sha256"}
        ) != row["row_sha256"]:
            raise RuntimeError("attempt_registry_row_hash_drift")
        if row["attempt_id"] != attempt_id(
            protocol_revision=row["protocol_revision_id"],
            stage=row["stage"],
            execution_unit=row["execution_unit"],
            attempt_ordinal=row["attempt_ordinal"],
            expected_prior_ledger_tip_sha256=row["expected_prior_ledger_tip_sha256"],
        ):
            raise RuntimeError("attempt_registry_identity_drift")
        rows.append(row)
        previous = row["row_sha256"]
    return rows


def runtime_bundle_identity(
    *,
    code_commit: str,
    dependency_lock_sha256: str,
    files: Sequence[Mapping[str, str]],
) -> str:
    ordered = [dict(item) for item in files]
    if ordered != sorted(ordered, key=lambda item: item.get("path", "")):
        raise ValueError("runtime_bundle_files_not_sorted")
    if len({item.get("path") for item in ordered}) != len(ordered):
        raise ValueError("runtime_bundle_duplicate_file")
    for item in ordered:
        if set(item) != {"path", "sha256"} or not _is_sha256(item["sha256"]):
            raise ValueError("runtime_bundle_file_invalid")
    if not _is_sha256(dependency_lock_sha256) or not code_commit:
        raise ValueError("runtime_bundle_identity_input_invalid")
    return canonical_sha256(
        {
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "code_commit": code_commit,
            "dependency_lock_sha256": dependency_lock_sha256,
            "files": ordered,
        }
    )


def build_runtime_bundle_manifest(
    *,
    project_root: str | Path,
    runtime_files: Sequence[str],
    dependency_lock_path: str,
    code_commit: str,
    numpy_version: str,
    pcg64_state_golden_sha256: str,
    gliner_runtime_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Build but do not persist the first bundle manifest."""

    root = Path(project_root).resolve()
    dependency_path = _resolve(dependency_lock_path, root)
    if not dependency_path.is_file():
        raise RuntimeError("runtime_dependency_lock_missing")
    files: list[dict[str, str]] = []
    normalized_paths = sorted(runtime_files)
    if len(normalized_paths) != len(set(normalized_paths)):
        raise RuntimeError("runtime_file_list_duplicate")
    for raw in normalized_paths:
        candidate = _resolve(raw, root)
        if not candidate.is_file():
            raise RuntimeError(f"runtime_file_missing:{raw}")
        files.append({"path": _relative(candidate, root), "sha256": sha256_file(candidate)})
    required_gliner = {
        "model_id",
        "model_revision",
        "model_snapshot_sha256",
        "transformers_version",
        "torch_version",
        "gliner_library_version",
        "tokenizer_or_processor_sha256",
        "device_type",
        "precision",
        "deterministic_algorithms",
        "inference_batch_size",
    }
    if set(gliner_runtime_identity) != required_gliner:
        raise RuntimeError("runtime_gliner_identity_schema_invalid")
    if (
        gliner_runtime_identity["device_type"] != "cuda"
        or gliner_runtime_identity["deterministic_algorithms"] is not True
    ):
        raise RuntimeError("runtime_gliner_identity_required_value_invalid")
    dependency_sha = sha256_file(dependency_path)
    bundle_id = runtime_bundle_identity(
        code_commit=code_commit,
        dependency_lock_sha256=dependency_sha,
        files=files,
    )
    return {
        "kind": "v23_runtime_bundle_manifest",
        "protocol_version": PROTOCOL_VERSION,
        "method_version": METHOD_VERSION,
        "specification_version": SPECIFICATION_VERSION,
        "runtime_bundle_id": bundle_id,
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "code_commit": code_commit,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "dependency_lock_path": _relative(dependency_path, root),
        "dependency_lock_sha256": dependency_sha,
        "numpy_version": numpy_version,
        "pcg64_state_golden_sha256": pcg64_state_golden_sha256,
        "gliner_runtime_identity": dict(gliner_runtime_identity),
        "files": files,
        "created_at": utc_now(),
    }


def _validate_historical_runtime_bundle(
    root: Path,
    bundle_path: Path,
) -> dict[str, Any]:
    bundle = _read_json_exact(bundle_path)
    _assert_exact_fields(bundle, RUNTIME_BUNDLE_FIELDS, kind="runtime_bundle_manifest")
    if (
        bundle["kind"] != "v23_runtime_bundle_manifest"
        or bundle["protocol_version"] != PROTOCOL_VERSION
        or bundle["method_version"] != METHOD_VERSION
        or bundle["specification_version"] != SPECIFICATION_VERSION
        or bundle["design_manifest_sha256"] != DESIGN_MANIFEST_SHA256
        or bundle_path.parent.name != bundle["runtime_bundle_id"]
    ):
        raise RuntimeError("runtime_bundle_manifest_identity_drift")
    files = bundle["files"]
    if not isinstance(files, list) or files != sorted(
        files, key=lambda item: item.get("path", "") if isinstance(item, Mapping) else ""
    ):
        raise RuntimeError("runtime_bundle_file_list_drift")
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
            raise RuntimeError("runtime_bundle_file_schema_drift")
        raw = _git_output(
            root,
            "show",
            f"{bundle['code_commit']}:{item['path']}",
            text_output=False,
        )
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise RuntimeError(f"runtime_bundle_commit_file_drift:{item['path']}")
    expected_bundle_id = runtime_bundle_identity(
        code_commit=bundle["code_commit"],
        dependency_lock_sha256=bundle["dependency_lock_sha256"],
        files=files,
    )
    if bundle["runtime_bundle_id"] != expected_bundle_id:
        raise RuntimeError("runtime_bundle_identity_drift")
    return bundle


def _load_runtime_lineage(root: Path) -> dict[str, Any]:
    bundle_paths = sorted(
        _resolve(RUNTIME_BUNDLE_DIRECTORY, root).glob("*/runtime_bundle_manifest.json")
    )
    revision_paths = sorted(_resolve(PROTOCOL_REVISION_DIRECTORY, root).glob("*.json"))
    if not bundle_paths or not revision_paths:
        raise RuntimeError("runtime_lineage_missing")
    bundles = {
        bundle["runtime_bundle_id"]: bundle
        for bundle in (
            _validate_historical_runtime_bundle(root, path) for path in bundle_paths
        )
    }
    if len(bundles) != len(bundle_paths):
        raise RuntimeError("runtime_lineage_duplicate_bundle")
    revisions: list[dict[str, Any]] = []
    for path in revision_paths:
        revision = _read_json_exact(path)
        _assert_exact_fields(revision, PROTOCOL_REVISION_FIELDS, kind="protocol_revision")
        bundle_id = revision["runtime_bundle_sha256"]
        ordinal = revision["revision_ordinal"]
        if (
            revision["kind"] != "v23_protocol_revision"
            or revision["specification_version"] != SPECIFICATION_VERSION
            or revision["design_manifest_sha256"] != DESIGN_MANIFEST_SHA256
            or bundle_id not in bundles
            or isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal < 0
            or revision["protocol_revision_id"]
            != protocol_revision_id(bundle_id, ordinal)
            or path.stem != revision["protocol_revision_id"]
        ):
            raise RuntimeError("runtime_protocol_revision_drift")
        revisions.append(revision)
    revisions.sort(key=lambda item: item["revision_ordinal"])
    if [item["revision_ordinal"] for item in revisions] != list(range(len(revisions))):
        raise RuntimeError("runtime_revision_ordinal_gap")
    if len({item["runtime_bundle_sha256"] for item in revisions}) != len(revisions):
        raise RuntimeError("runtime_revision_bundle_reuse")
    return {
        "bundles": bundles,
        "revisions": revisions,
        "active_revision": revisions[-1],
        "active_bundle": bundles[revisions[-1]["runtime_bundle_sha256"]],
    }


def _stage_identity_for_bundle(
    root: Path,
    *,
    stage: str,
    runtime_bundle_sha256: str,
) -> dict[str, Any]:
    lineage = _load_runtime_lineage(root)
    bundle = lineage["bundles"].get(runtime_bundle_sha256)
    if bundle is None:
        raise RuntimeError("stage_identity_runtime_bundle_unknown")
    revisions = [
        item
        for item in lineage["revisions"]
        if item["runtime_bundle_sha256"] == runtime_bundle_sha256
    ]
    if len(revisions) != 1:
        raise RuntimeError("stage_identity_protocol_revision_ambiguous")
    contract = load_execution_erratum(root)

    def load_committed_text(path: str) -> str:
        raw = _git_output(
            root,
            "show",
            f"{bundle['code_commit']}:{path}",
            text_output=False,
        )
        return bytes(raw).decode("utf-8")

    def load_exact_bytes(path: str) -> bytes:
        candidate = _resolve(path, root)
        if not candidate.is_file():
            raise RuntimeError(f"stage_dependency_file_missing:{path}")
        return candidate.read_bytes()

    fingerprint = compute_stage_dependency_fingerprint(
        contract,
        stage,
        python_source_loader=load_committed_text,
        config_source_loader=load_committed_text,
        file_bytes_loader=load_exact_bytes,
        runtime_manifest=bundle,
    )
    revision = revisions[0]
    return {
        **fingerprint,
        "execution_revision": EXECUTION_REVISION,
        "execution_erratum_sha256": EXECUTION_ERRATUM_SHA256,
        "runtime_bundle_sha256": runtime_bundle_sha256,
        "protocol_revision_id": revision["protocol_revision_id"],
        "stage_execution_identity": stage_execution_identity(
            stage=stage,
            stage_dependency_fingerprint=fingerprint[
                "stage_dependency_fingerprint"
            ],
            runtime_bundle_sha256=runtime_bundle_sha256,
            protocol_revision_id=revision["protocol_revision_id"],
        ),
    }


def stage_identity(
    *,
    project_root: str | Path,
    stage: str,
    runtime_bundle_sha256: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    lineage = _load_runtime_lineage(root)
    bundle_id = runtime_bundle_sha256 or lineage["active_revision"][
        "runtime_bundle_sha256"
    ]
    return _stage_identity_for_bundle(
        root, stage=stage, runtime_bundle_sha256=bundle_id
    )


def validate_active_runtime(
    project_root: str | Path = ".",
    *,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    runtime_files = RUNTIME_BUNDLE_FILES if runtime_files is None else tuple(runtime_files)
    validate_bootstrap_design_identity(root)
    lineage = _load_runtime_lineage(root)
    active_bundle = lineage["active_bundle"]
    if validate_runtime_commit(root, runtime_files=runtime_files) != active_bundle["code_commit"]:
        raise RuntimeError("active_runtime_commit_drift")
    current_files = [
        {"path": path, "sha256": sha256_file(_resolve(path, root))}
        for path in sorted(runtime_files)
    ]
    if active_bundle["files"] != current_files:
        raise RuntimeError("active_runtime_file_hash_drift")
    if active_bundle["dependency_lock_sha256"] != sha256_file(
        _resolve(dependency_lock_path, root)
    ):
        raise RuntimeError("active_runtime_dependency_drift")
    gliner_identity = build_gliner_runtime_identity(
        root, model_lock_path=model_lock_path
    )
    numpy_version, pcg64_sha256 = pcg64_runtime_identity()
    if (
        active_bundle["gliner_runtime_identity"] != gliner_identity
        or active_bundle["numpy_version"] != numpy_version
        or active_bundle["pcg64_state_golden_sha256"] != pcg64_sha256
        or active_bundle["python_executable"] != sys.executable
        or active_bundle["python_version"] != platform.python_version()
    ):
        raise RuntimeError("active_runtime_environment_identity_drift")
    return {
        "status": "passed",
        "runtime_bundle_sha256": active_bundle["runtime_bundle_id"],
        "protocol_revision_id": lineage["active_revision"]["protocol_revision_id"],
        "revision_ordinal": lineage["active_revision"]["revision_ordinal"],
        "code_commit": active_bundle["code_commit"],
    }


def validate_runtime_successor_freeze_authorization(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    authorization = dict(value)
    _assert_exact_fields(
        authorization,
        SUCCESSOR_FREEZE_AUTH_FIELDS,
        kind="runtime_successor_freeze_authorization",
    )
    constants = {
        "kind": "v23_runtime_successor_freeze_authorization",
        "authorized_stage": "runtime_bundle_and_commit_freeze",
        "execution_unit": "global",
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "external_calls_allowed": False,
    }
    if any(authorization[key] != expected for key, expected in constants.items()):
        raise RuntimeError("runtime_successor_freeze_authorization_constant_drift")
    for key in (
        "authorization_id",
        "expected_prior_runtime_bundle_sha256",
        "expected_prior_protocol_revision_id",
        "expected_prior_ledger_tip_sha256",
        "new_runtime_bundle_sha256",
        "new_protocol_revision_id",
    ):
        if not _is_sha256(authorization[key]):
            raise RuntimeError(f"runtime_successor_freeze_authorization_hash_invalid:{key}")
    if (
        isinstance(authorization["new_revision_ordinal"], bool)
        or not isinstance(authorization["new_revision_ordinal"], int)
        or authorization["new_revision_ordinal"] < 1
        or not authorization["user_authorization_record"].strip()
        or not authorization["new_code_commit"]
    ):
        raise RuntimeError("runtime_successor_freeze_authorization_value_invalid")
    if canonical_sha256(
        {key: item for key, item in authorization.items() if key != "authorization_id"}
    ) != authorization["authorization_id"]:
        raise RuntimeError("runtime_successor_freeze_authorization_identity_drift")
    if authorization["expires_at_or_null"] is not None:
        expiry = datetime.fromisoformat(
            str(authorization["expires_at_or_null"]).replace("Z", "+00:00")
        )
        if expiry <= datetime.now(timezone.utc):
            raise RuntimeError("runtime_successor_freeze_authorization_expired")
    return authorization


def prepare_runtime_successor_freeze_authorization(
    *,
    project_root: str | Path,
    user_authorization_record: str,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    if not user_authorization_record.strip():
        raise ValueError("runtime_successor_freeze_user_authorization_empty")
    root = Path(project_root).resolve()
    runtime_files = RUNTIME_BUNDLE_FILES if runtime_files is None else tuple(runtime_files)
    validate_runtime_bootstrap(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    lineage = _load_runtime_lineage(root)
    ledger = validate_ledger(_resolve(CONSUMPTION_LEDGER, root))
    code_commit = validate_runtime_commit(root, runtime_files=runtime_files)
    gliner_identity = build_gliner_runtime_identity(
        root, model_lock_path=model_lock_path
    )
    numpy_version, pcg64_sha256 = pcg64_runtime_identity()
    bundle = build_runtime_bundle_manifest(
        project_root=root,
        runtime_files=runtime_files,
        dependency_lock_path=str(dependency_lock_path),
        code_commit=code_commit,
        numpy_version=numpy_version,
        pcg64_state_golden_sha256=pcg64_sha256,
        gliner_runtime_identity=gliner_identity,
    )
    active_revision = lineage["active_revision"]
    if bundle["runtime_bundle_id"] == active_revision["runtime_bundle_sha256"]:
        raise RuntimeError("runtime_successor_freeze_no_runtime_change")
    ordinal = active_revision["revision_ordinal"] + 1
    revision_id = protocol_revision_id(bundle["runtime_bundle_id"], ordinal)
    authorization = {
        "kind": "v23_runtime_successor_freeze_authorization",
        "user_authorization_record": user_authorization_record,
        "authorized_stage": "runtime_bundle_and_commit_freeze",
        "execution_unit": "global",
        "expected_prior_runtime_bundle_sha256": active_revision[
            "runtime_bundle_sha256"
        ],
        "expected_prior_protocol_revision_id": active_revision[
            "protocol_revision_id"
        ],
        "expected_prior_ledger_tip_sha256": ledger["tip_sha256"],
        "new_code_commit": code_commit,
        "new_runtime_bundle_sha256": bundle["runtime_bundle_id"],
        "new_protocol_revision_id": revision_id,
        "new_revision_ordinal": ordinal,
        "issued_at": utc_now(),
        "expires_at_or_null": None,
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "external_calls_allowed": False,
    }
    authorization["authorization_id"] = canonical_sha256(authorization)
    path = _resolve(
        SUCCESSOR_FREEZE_AUTH_DIRECTORY / f"{authorization['authorization_id']}.json",
        root,
    )
    _write_new_canonical_json(path, authorization)
    return {**authorization, "authorization_path": _relative(path, root)}


def run_runtime_successor_freeze(
    *,
    project_root: str | Path,
    authorization_path: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    runtime_files = RUNTIME_BUNDLE_FILES if runtime_files is None else tuple(runtime_files)
    path = _resolve(authorization_path, root)
    authorization = validate_runtime_successor_freeze_authorization(
        _read_json_exact(path)
    )
    expected_path = _resolve(
        SUCCESSOR_FREEZE_AUTH_DIRECTORY / f"{authorization['authorization_id']}.json",
        root,
    )
    if path != expected_path:
        raise RuntimeError("runtime_successor_freeze_authorization_path_drift")
    lock_path = _resolve(ARTIFACT_ROOT / "governance/runtime_successor_freeze.lock", root)
    with exclusive_lock(lock_path):
        validate_runtime_bootstrap(
            root,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        lineage = _load_runtime_lineage(root)
        active_revision = lineage["active_revision"]
        ledger = validate_ledger(_resolve(CONSUMPTION_LEDGER, root))
        if (
            active_revision["runtime_bundle_sha256"]
            != authorization["expected_prior_runtime_bundle_sha256"]
            or active_revision["protocol_revision_id"]
            != authorization["expected_prior_protocol_revision_id"]
            or ledger["tip_sha256"]
            != authorization["expected_prior_ledger_tip_sha256"]
            or active_revision["revision_ordinal"] + 1
            != authorization["new_revision_ordinal"]
        ):
            raise RuntimeError("runtime_successor_freeze_prior_identity_drift")
        code_commit = validate_runtime_commit(root, runtime_files=runtime_files)
        gliner_identity = build_gliner_runtime_identity(
            root, model_lock_path=model_lock_path
        )
        numpy_version, pcg64_sha256 = pcg64_runtime_identity()
        bundle = build_runtime_bundle_manifest(
            project_root=root,
            runtime_files=runtime_files,
            dependency_lock_path=str(dependency_lock_path),
            code_commit=code_commit,
            numpy_version=numpy_version,
            pcg64_state_golden_sha256=pcg64_sha256,
            gliner_runtime_identity=gliner_identity,
        )
        revision = {
            "kind": "v23_protocol_revision",
            "specification_version": SPECIFICATION_VERSION,
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "runtime_bundle_sha256": bundle["runtime_bundle_id"],
            "revision_ordinal": authorization["new_revision_ordinal"],
            "protocol_revision_id": protocol_revision_id(
                bundle["runtime_bundle_id"], authorization["new_revision_ordinal"]
            ),
        }
        if (
            code_commit != authorization["new_code_commit"]
            or bundle["runtime_bundle_id"]
            != authorization["new_runtime_bundle_sha256"]
            or revision["protocol_revision_id"]
            != authorization["new_protocol_revision_id"]
        ):
            raise RuntimeError("runtime_successor_freeze_target_identity_drift")
        bundle_path = _resolve(
            RUNTIME_BUNDLE_DIRECTORY
            / bundle["runtime_bundle_id"]
            / "runtime_bundle_manifest.json",
            root,
        )
        revision_path = _resolve(
            PROTOCOL_REVISION_DIRECTORY / f"{revision['protocol_revision_id']}.json",
            root,
        )
        checkpoint_path = _resolve(
            SUCCESSOR_FREEZE_CHECKPOINT_DIRECTORY
            / f"{authorization['authorization_id']}.json",
            root,
        )
        if bundle_path.exists() or revision_path.exists() or checkpoint_path.exists():
            raise RuntimeError("runtime_successor_freeze_existing_artifact")
        _write_new_canonical_json(bundle_path, bundle)
        _write_new_canonical_json(revision_path, revision)
        checkpoint = {
            "kind": "v23_runtime_successor_freeze_checkpoint",
            "authorization_id": authorization["authorization_id"],
            "status": "passed",
            "prior_runtime_bundle_sha256": authorization[
                "expected_prior_runtime_bundle_sha256"
            ],
            "prior_protocol_revision_id": authorization[
                "expected_prior_protocol_revision_id"
            ],
            "new_runtime_bundle_sha256": bundle["runtime_bundle_id"],
            "new_protocol_revision_id": revision["protocol_revision_id"],
            "new_revision_ordinal": revision["revision_ordinal"],
            "ledger_tip_sha256": ledger["tip_sha256"],
            "code_commit": code_commit,
            "completed_at": utc_now(),
        }
        _write_new_canonical_json(checkpoint_path, checkpoint)
    return validate_runtime_successor_freeze(
        project_root=root,
        authorization_path=path,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )


def validate_runtime_successor_freeze(
    *,
    project_root: str | Path,
    authorization_path: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = _resolve(authorization_path, root)
    authorization = validate_runtime_successor_freeze_authorization(
        _read_json_exact(path)
    )
    checkpoint_path = _resolve(
        SUCCESSOR_FREEZE_CHECKPOINT_DIRECTORY
        / f"{authorization['authorization_id']}.json",
        root,
    )
    checkpoint = _read_json_exact(checkpoint_path)
    _assert_exact_fields(
        checkpoint,
        SUCCESSOR_FREEZE_CHECKPOINT_FIELDS,
        kind="runtime_successor_freeze_checkpoint",
    )
    active = validate_active_runtime(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    ledger = validate_ledger(_resolve(CONSUMPTION_LEDGER, root))
    expected = {
        "kind": "v23_runtime_successor_freeze_checkpoint",
        "authorization_id": authorization["authorization_id"],
        "status": "passed",
        "prior_runtime_bundle_sha256": authorization[
            "expected_prior_runtime_bundle_sha256"
        ],
        "prior_protocol_revision_id": authorization[
            "expected_prior_protocol_revision_id"
        ],
        "new_runtime_bundle_sha256": authorization["new_runtime_bundle_sha256"],
        "new_protocol_revision_id": authorization["new_protocol_revision_id"],
        "new_revision_ordinal": authorization["new_revision_ordinal"],
        "ledger_tip_sha256": authorization["expected_prior_ledger_tip_sha256"],
        "code_commit": authorization["new_code_commit"],
    }
    if any(checkpoint[key] != value for key, value in expected.items()):
        raise RuntimeError("runtime_successor_freeze_checkpoint_drift")
    if (
        active["runtime_bundle_sha256"] != authorization["new_runtime_bundle_sha256"]
        or active["protocol_revision_id"] != authorization["new_protocol_revision_id"]
        or ledger["tip_sha256"] != checkpoint["ledger_tip_sha256"]
    ):
        raise RuntimeError("runtime_successor_freeze_active_identity_drift")
    return {
        "status": "passed",
        "authorization_id": authorization["authorization_id"],
        **active,
        "ledger_tip_sha256": ledger["tip_sha256"],
        "external_calls_performed": 0,
    }


def _read_bootstrap_registry(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise RuntimeError("bootstrap_attempt_registry_partial_trailing_line")
    rows: list[dict[str, Any]] = []
    previous = ZERO_SHA256
    for sequence, line in enumerate(raw.decode("utf-8").splitlines()):
        row = json.loads(line)
        _assert_exact_fields(row, BOOTSTRAP_REGISTRY_FIELDS, kind="bootstrap_attempt_registry")
        if (
            row["kind"] != "v23_runtime_bootstrap_attempt_registry_row"
            or row["sequence"] != sequence
            or row["bootstrap_attempt_ordinal"] != sequence
            or row["previous_row_sha256"] != previous
            or row["bootstrap_attempt_id"]
            != bootstrap_attempt_id(bootstrap_attempt_ordinal=sequence)
        ):
            raise RuntimeError("bootstrap_attempt_registry_chain_drift")
        calculated = canonical_sha256(
            {key: value for key, value in row.items() if key != "row_sha256"}
        )
        if row["row_sha256"] != calculated:
            raise RuntimeError("bootstrap_attempt_registry_row_hash_drift")
        rows.append(row)
        previous = row["row_sha256"]
    return rows


def allocate_bootstrap_attempt(registry_path: str | Path) -> dict[str, Any]:
    path = Path(registry_path)
    with exclusive_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _read_bootstrap_registry(path)
        ordinal = len(rows)
        row = {
            "kind": "v23_runtime_bootstrap_attempt_registry_row",
            "sequence": ordinal,
            "bootstrap_attempt_ordinal": ordinal,
            "bootstrap_attempt_id": bootstrap_attempt_id(
                bootstrap_attempt_ordinal=ordinal
            ),
            "previous_row_sha256": rows[-1]["row_sha256"] if rows else ZERO_SHA256,
            "allocated_at": utc_now(),
        }
        row["row_sha256"] = canonical_sha256(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return row


def _directory_has_entries(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _assert_bootstrap_not_started(root: Path, *, include_preparation: bool) -> None:
    disallowed_files = [CONSUMPTION_LEDGER]
    disallowed_directories = [
        RUNTIME_BUNDLE_DIRECTORY,
        PROTOCOL_REVISION_DIRECTORY,
        LEDGER_ANCHOR_DIRECTORY,
        BOOTSTRAP_CHECKPOINT_DIRECTORY,
        BUDGET_DIRECTORY,
    ]
    if any(_resolve(path, root).exists() for path in disallowed_files) or any(
        _directory_has_entries(_resolve(path, root)) for path in disallowed_directories
    ):
        raise RuntimeError("runtime_bootstrap_existing_or_partial_artifact")
    if include_preparation and (
        _resolve(BOOTSTRAP_REGISTRY, root).exists()
        or _directory_has_entries(_resolve(BOOTSTRAP_AUTH_DIRECTORY, root))
    ):
        raise RuntimeError("runtime_bootstrap_preparation_already_exists")


def prepare_runtime_bootstrap_authorization(
    *,
    project_root: str | Path,
    user_authorization_record: str,
) -> dict[str, Any]:
    """Persist one self-hashed authorization for the zero-call bootstrap only."""

    if not user_authorization_record.strip():
        raise ValueError("runtime_bootstrap_user_authorization_empty")
    root = Path(project_root).resolve()
    validate_bootstrap_design_identity(root)
    lock_path = _resolve(ARTIFACT_ROOT / "governance/runtime_bootstrap.lock", root)
    with exclusive_lock(lock_path):
        _assert_bootstrap_not_started(root, include_preparation=True)
        registry_row = allocate_bootstrap_attempt(_resolve(BOOTSTRAP_REGISTRY, root))
        authorization = {
            "kind": "v23_runtime_bootstrap_authorization",
            "user_authorization_record": user_authorization_record,
            "authorized_stage": "runtime_bundle_and_commit_freeze",
            "execution_unit": "global",
            "bootstrap_attempt_id": registry_row["bootstrap_attempt_id"],
            "expected_prior_ledger_tip_sha256": GENESIS_SENTINEL,
            "issued_at": utc_now(),
            "expires_at_or_null": None,
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "external_calls_allowed": False,
        }
        authorization["authorization_id"] = canonical_sha256(authorization)
        path = _resolve(
            BOOTSTRAP_AUTH_DIRECTORY / f"{authorization['authorization_id']}.json",
            root,
        )
        _write_new_canonical_json(path, authorization)
    return {**authorization, "authorization_path": _relative(path, root)}


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(f"runtime_package_missing:{distribution}") from error


def build_gliner_runtime_identity(
    project_root: str | Path,
    *,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    """Bind GLiNER2 base from its lock without importing or loading the model."""

    root = Path(project_root).resolve()
    lock = load_yaml(_resolve(model_lock_path, root))
    models = lock.get("models") if isinstance(lock, Mapping) else None
    matches = [
        item
        for item in models or []
        if isinstance(item, Mapping) and item.get("role") == "gliner2_base"
    ]
    if len(matches) != 1:
        raise RuntimeError("runtime_gliner2_base_lock_missing")
    model = matches[0]
    constants = {
        "model_id": "fastino/gliner2-base-v1",
        "revision": "f5b2ecedebe4381b088c1cf276f5bf72a52cac54",
        "package": "gliner2",
        "package_version": "1.3.2",
    }
    if any(model.get(key) != value for key, value in constants.items()):
        raise RuntimeError("runtime_gliner2_base_lock_identity_drift")
    files = model.get("files_sha256")
    if not isinstance(files, Mapping) or not files:
        raise RuntimeError("runtime_gliner2_base_file_lock_invalid")
    ordered_files = [
        {"path": str(path), "sha256": str(digest)}
        for path, digest in sorted(files.items())
    ]
    if any(not _is_sha256(item["sha256"]) for item in ordered_files):
        raise RuntimeError("runtime_gliner2_base_file_hash_invalid")
    model_root = _resolve(str(model.get("local_path", "")), root)
    weight_names = {"model.safetensors", "pytorch_model.bin"}
    for item in ordered_files:
        if Path(item["path"]).name in weight_names:
            continue
        candidate = _resolve(item["path"], model_root)
        if not candidate.is_file() or sha256_file(candidate) != item["sha256"]:
            raise RuntimeError(f"runtime_gliner_model_file_hash_drift:{item['path']}")
    tokenizer_names = {
        "added_tokens.json",
        "special_tokens_map.json",
        "spm.model",
        "tokenizer.json",
        "tokenizer_config.json",
    }
    tokenizer_files = [
        item for item in ordered_files if Path(item["path"]).name in tokenizer_names
    ]
    if not tokenizer_files:
        raise RuntimeError("runtime_gliner_tokenizer_lock_missing")
    return {
        "model_id": model["model_id"],
        "model_revision": model["revision"],
        "model_snapshot_sha256": canonical_sha256(
            {
                "model_id": model["model_id"],
                "model_revision": model["revision"],
                "files_sha256": ordered_files,
            }
        ),
        "transformers_version": _package_version("transformers"),
        "torch_version": _package_version("torch"),
        "gliner_library_version": _package_version("gliner2"),
        "tokenizer_or_processor_sha256": canonical_sha256(tokenizer_files),
        "device_type": "cuda",
        "precision": "float16",
        "deterministic_algorithms": True,
        "inference_batch_size": 8,
    }


def pcg64_runtime_identity() -> tuple[str, str]:
    import numpy as np

    state = np.random.PCG64(42).state
    return np.__version__, canonical_sha256(state)


def _validate_bootstrap_authorization_file(
    root: Path,
    authorization_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _resolve(authorization_path, root)
    authorization = validate_runtime_bootstrap_authorization(_read_json_exact(path))
    expected_path = _resolve(
        BOOTSTRAP_AUTH_DIRECTORY / f"{authorization['authorization_id']}.json",
        root,
    )
    if path != expected_path:
        raise RuntimeError("runtime_bootstrap_authorization_path_drift")
    rows = _read_bootstrap_registry(_resolve(BOOTSTRAP_REGISTRY, root))
    if len(rows) != 1 or rows[0]["bootstrap_attempt_ordinal"] != 0:
        raise RuntimeError("runtime_bootstrap_registry_count_invalid")
    matches = [
        row
        for row in rows
        if row["bootstrap_attempt_id"] == authorization["bootstrap_attempt_id"]
    ]
    if len(matches) != 1:
        raise RuntimeError("runtime_bootstrap_authorization_registry_mismatch")
    return authorization, matches[0]


def _write_genesis_ledger(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def run_runtime_bootstrap(
    *,
    project_root: str | Path,
    authorization_path: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    """Freeze the first runtime bundle and ledger genesis with zero external calls."""

    root = Path(project_root).resolve()
    runtime_files = RUNTIME_BUNDLE_FILES if runtime_files is None else tuple(runtime_files)
    lock_path = _resolve(ARTIFACT_ROOT / "governance/runtime_bootstrap.lock", root)
    with exclusive_lock(lock_path):
        validate_bootstrap_design_identity(root)
        authorization, _ = _validate_bootstrap_authorization_file(root, authorization_path)
        authorization_paths = sorted(
            _resolve(BOOTSTRAP_AUTH_DIRECTORY, root).glob("*.json")
        )
        if len(authorization_paths) != 1:
            raise RuntimeError("runtime_bootstrap_authorization_count_invalid")
        _assert_bootstrap_not_started(root, include_preparation=False)
        if _resolve(
            BUDGET_DIRECTORY / f"{authorization['authorization_id']}.jsonl", root
        ).exists():
            raise RuntimeError("runtime_bootstrap_authorization_already_used")
        code_commit = validate_runtime_commit(root, runtime_files=runtime_files)
        gliner_identity = build_gliner_runtime_identity(
            root, model_lock_path=model_lock_path
        )
        numpy_version, pcg64_sha256 = pcg64_runtime_identity()
        bundle = build_runtime_bundle_manifest(
            project_root=root,
            runtime_files=runtime_files,
            dependency_lock_path=str(dependency_lock_path),
            code_commit=code_commit,
            numpy_version=numpy_version,
            pcg64_state_golden_sha256=pcg64_sha256,
            gliner_runtime_identity=gliner_identity,
        )
        bundle_id = bundle["runtime_bundle_id"]
        revision_id = protocol_revision_id(bundle_id, 0)
        revision = {
            "kind": "v23_protocol_revision",
            "specification_version": SPECIFICATION_VERSION,
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "runtime_bundle_sha256": bundle_id,
            "revision_ordinal": 0,
            "protocol_revision_id": revision_id,
        }
        genesis = {
            "kind": "v23_consumption_ledger_genesis",
            "sequence": 0,
            "protocol_revision_id": revision_id,
            "role": "genesis",
            "dataset": "__all__",
            "source_key": "__genesis__",
            "source_hash": "__not_applicable__",
            "normalized_text_hash": "__not_applicable__",
            "consumed_at": utc_now(),
            "reason": "first_v23_runtime_bundle_freeze",
            "previous_row_sha256": ZERO_SHA256,
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "frozen_v22_protocol_identity_sha256": FROZEN_V22_PROTOCOL_IDENTITY_SHA256,
            "source_order_file_sha256_by_dataset": dict(
                FROZEN_SOURCE_ORDER_FILE_SHA256_BY_DATASET
            ),
        }
        genesis["row_sha256"] = canonical_sha256(genesis)
        anchor = {
            "kind": "v23_ledger_genesis_anchor",
            "protocol_revision_id": revision_id,
            "ledger_tip_sha256": genesis["row_sha256"],
            "genesis_row_sha256": genesis["row_sha256"],
            "created_at": utc_now(),
        }
        bundle_path = _resolve(
            RUNTIME_BUNDLE_DIRECTORY / bundle_id / "runtime_bundle_manifest.json", root
        )
        revision_path = _resolve(PROTOCOL_REVISION_DIRECTORY / f"{revision_id}.json", root)
        ledger_path = _resolve(CONSUMPTION_LEDGER, root)
        anchor_path = _resolve(
            LEDGER_ANCHOR_DIRECTORY
            / f"000000000000_genesis_{genesis['row_sha256']}.json",
            root,
        )
        checkpoint_path = _resolve(
            BOOTSTRAP_CHECKPOINT_DIRECTORY
            / f"{authorization['bootstrap_attempt_id']}.json",
            root,
        )
        _write_new_canonical_json(bundle_path, bundle)
        _write_new_canonical_json(revision_path, revision)
        _write_genesis_ledger(ledger_path, genesis)
        _write_new_canonical_json(anchor_path, anchor)
        checkpoint = {
            "kind": "v23_runtime_bootstrap_checkpoint",
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "bootstrap_attempt_id": authorization["bootstrap_attempt_id"],
            "authorization_id": authorization["authorization_id"],
            "status": "passed",
            "new_runtime_bundle_sha256": bundle_id,
            "new_protocol_revision_id": revision_id,
            "genesis_row_sha256": genesis["row_sha256"],
            "genesis_anchor_sha256": sha256_file(anchor_path),
            "code_commit": code_commit,
            "completed_at": utc_now(),
        }
        _write_new_canonical_json(checkpoint_path, checkpoint)
        validated = validate_runtime_bootstrap(
            root,
            authorization_path=authorization_path,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
    return validated


def validate_runtime_bootstrap(
    project_root: str | Path = ".",
    *,
    authorization_path: str | Path | None = None,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    """Validate the complete bundle/revision/genesis/anchor/checkpoint closure."""

    root = Path(project_root).resolve()
    runtime_files = RUNTIME_BUNDLE_FILES if runtime_files is None else tuple(runtime_files)
    validate_bootstrap_design_identity(root)
    if authorization_path is None:
        authorization_paths = sorted(_resolve(BOOTSTRAP_AUTH_DIRECTORY, root).glob("*.json"))
        if len(authorization_paths) != 1:
            raise RuntimeError("runtime_bootstrap_authorization_count_invalid")
        authorization_path = authorization_paths[0]
    authorization, _ = _validate_bootstrap_authorization_file(root, authorization_path)
    checkpoints = sorted(_resolve(BOOTSTRAP_CHECKPOINT_DIRECTORY, root).glob("*.json"))
    if len(checkpoints) != 1:
        raise RuntimeError("runtime_bootstrap_checkpoint_count_invalid")
    checkpoint = _read_json_exact(checkpoints[0])
    _assert_exact_fields(checkpoint, BOOTSTRAP_CHECKPOINT_FIELDS, kind="runtime_bootstrap_checkpoint")
    if (
        checkpoint["kind"] != "v23_runtime_bootstrap_checkpoint"
        or checkpoint["status"] != "passed"
        or checkpoint["design_manifest_sha256"] != DESIGN_MANIFEST_SHA256
        or checkpoint["bootstrap_attempt_id"] != authorization["bootstrap_attempt_id"]
        or checkpoint["authorization_id"] != authorization["authorization_id"]
        or checkpoints[0].stem != authorization["bootstrap_attempt_id"]
    ):
        raise RuntimeError("runtime_bootstrap_checkpoint_identity_drift")
    bundle_id = checkpoint["new_runtime_bundle_sha256"]
    revision_id = checkpoint["new_protocol_revision_id"]
    if not _is_sha256(bundle_id) or not _is_sha256(revision_id):
        raise RuntimeError("runtime_bootstrap_checkpoint_hash_invalid")
    bundle_path = _resolve(
        RUNTIME_BUNDLE_DIRECTORY / bundle_id / "runtime_bundle_manifest.json", root
    )
    revision_path = _resolve(PROTOCOL_REVISION_DIRECTORY / f"{revision_id}.json", root)
    if not bundle_path.is_file() or not revision_path.is_file():
        raise RuntimeError("runtime_bootstrap_protocol_artifact_missing")
    bundle = _validate_historical_runtime_bundle(root, bundle_path)
    if (
        bundle["runtime_bundle_id"] != bundle_id
        or checkpoint["code_commit"] != bundle["code_commit"]
    ):
        raise RuntimeError("runtime_bundle_manifest_identity_drift")
    if bundle["dependency_lock_path"] != _relative(
        _resolve(dependency_lock_path, root), root
    ):
        raise RuntimeError("runtime_bundle_dependency_path_drift")
    revision = _read_json_exact(revision_path)
    _assert_exact_fields(revision, PROTOCOL_REVISION_FIELDS, kind="protocol_revision")
    expected_revision_id = protocol_revision_id(bundle_id, 0)
    expected_revision = {
        "kind": "v23_protocol_revision",
        "specification_version": SPECIFICATION_VERSION,
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "runtime_bundle_sha256": bundle_id,
        "revision_ordinal": 0,
        "protocol_revision_id": expected_revision_id,
    }
    if revision != expected_revision or revision_path.stem != expected_revision_id:
        raise RuntimeError("runtime_protocol_revision_drift")
    ledger_path = _resolve(CONSUMPTION_LEDGER, root)
    validate_ledger(ledger_path)
    ledger_lines = ledger_path.read_text(encoding="utf-8").splitlines()
    genesis = json.loads(ledger_lines[0])
    if (
        genesis["protocol_revision_id"] != expected_revision_id
        or genesis["design_manifest_sha256"] != DESIGN_MANIFEST_SHA256
        or genesis["frozen_v22_protocol_identity_sha256"]
        != FROZEN_V22_PROTOCOL_IDENTITY_SHA256
        or genesis["source_order_file_sha256_by_dataset"]
        != FROZEN_SOURCE_ORDER_FILE_SHA256_BY_DATASET
        or genesis["row_sha256"] != checkpoint["genesis_row_sha256"]
    ):
        raise RuntimeError("runtime_bootstrap_genesis_binding_drift")
    anchor_path = _resolve(
        LEDGER_ANCHOR_DIRECTORY
        / f"000000000000_genesis_{genesis['row_sha256']}.json",
        root,
    )
    if not anchor_path.is_file():
        raise RuntimeError("runtime_bootstrap_genesis_anchor_missing")
    anchor = _read_json_exact(anchor_path)
    _assert_exact_fields(anchor, GENESIS_ANCHOR_FIELDS, kind="genesis_anchor")
    expected_anchor_name = f"000000000000_genesis_{genesis['row_sha256']}.json"
    if (
        anchor["kind"] != "v23_ledger_genesis_anchor"
        or anchor["protocol_revision_id"] != expected_revision_id
        or anchor["ledger_tip_sha256"] != genesis["row_sha256"]
        or anchor["genesis_row_sha256"] != genesis["row_sha256"]
        or anchor_path.name != expected_anchor_name
        or sha256_file(anchor_path) != checkpoint["genesis_anchor_sha256"]
    ):
        raise RuntimeError("runtime_bootstrap_genesis_anchor_drift")
    if (
        checkpoint["new_protocol_revision_id"] != expected_revision_id
        or checkpoint["new_runtime_bundle_sha256"] != bundle_id
        or checkpoint["code_commit"] != bundle["code_commit"]
    ):
        raise RuntimeError("runtime_bootstrap_checkpoint_binding_drift")
    return {
        "status": "passed",
        "runtime_bundle_frozen": True,
        "runtime_bundle_sha256": bundle_id,
        "runtime_bundle_manifest_file_sha256": sha256_file(bundle_path),
        "protocol_revision_id": expected_revision_id,
        "genesis_row_sha256": genesis["row_sha256"],
        "genesis_anchor_sha256": sha256_file(anchor_path),
        "bootstrap_attempt_id": authorization["bootstrap_attempt_id"],
        "authorization_id": authorization["authorization_id"],
        "code_commit": bundle["code_commit"],
        "source_pool_contents_read": False,
        "pilot_started": False,
        "external_calls_performed": 0,
    }


GENESIS_FIELDS = {
    "kind",
    "sequence",
    "protocol_revision_id",
    "role",
    "dataset",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "consumed_at",
    "reason",
    "previous_row_sha256",
    "design_manifest_sha256",
    "frozen_v22_protocol_identity_sha256",
    "source_order_file_sha256_by_dataset",
    "row_sha256",
}
SOURCE_LEDGER_FIELDS = {
    "kind",
    "sequence",
    "protocol_revision_id",
    "attempt_id",
    "reservation_batch_id",
    "reservation_batch_index",
    "reservation_batch_size",
    "role",
    "dataset",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "consumed_at",
    "reason",
    "previous_row_sha256",
    "row_sha256",
}


def validate_ledger(path: str | Path) -> dict[str, Any]:
    ledger = Path(path)
    if not ledger.is_file():
        raise RuntimeError("consumption_ledger_missing")
    raw = ledger.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise RuntimeError("consumption_ledger_partial_trailing_line")
    previous = ZERO_SHA256
    count = 0
    for sequence, line in enumerate(raw.decode("utf-8").splitlines()):
        if not line:
            raise RuntimeError("consumption_ledger_empty_line")
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RuntimeError("consumption_ledger_row_not_object")
        expected = GENESIS_FIELDS if sequence == 0 else SOURCE_LEDGER_FIELDS
        _assert_exact_fields(row, expected, kind="consumption_ledger_row")
        if row["sequence"] != sequence or row["previous_row_sha256"] != previous:
            raise RuntimeError("consumption_ledger_chain_drift")
        if sequence == 0:
            constants = {
                "kind": "v23_consumption_ledger_genesis",
                "role": "genesis",
                "dataset": "__all__",
                "source_key": "__genesis__",
                "source_hash": "__not_applicable__",
                "normalized_text_hash": "__not_applicable__",
                "previous_row_sha256": ZERO_SHA256,
            }
            if any(row[key] != value for key, value in constants.items()):
                raise RuntimeError("consumption_ledger_genesis_drift")
        else:
            if row["kind"] != "v23_consumed_source" or row["role"] not in LEDGER_ROLES:
                raise RuntimeError("consumption_ledger_source_constant_drift")
            if row["reservation_batch_index"] < 0 or row["reservation_batch_index"] >= row["reservation_batch_size"]:
                raise RuntimeError("consumption_ledger_batch_index_invalid")
        claimed = row["row_sha256"]
        calculated = canonical_sha256({key: value for key, value in row.items() if key != "row_sha256"})
        if claimed != calculated:
            raise RuntimeError("consumption_ledger_row_hash_drift")
        previous = claimed
        count += 1
    return {"row_count": count, "tip_sha256": previous}


def _ledger_tip_anchor(root: Path, ledger_tip_sha256: str) -> Path:
    if not _is_sha256(ledger_tip_sha256):
        raise RuntimeError("ledger_tip_anchor_hash_invalid")
    matches: list[Path] = []
    for path in sorted(_resolve(LEDGER_ANCHOR_DIRECTORY, root).glob("*.json")):
        value = _read_json_exact(path)
        if value.get("ledger_tip_sha256") != ledger_tip_sha256:
            continue
        if value.get("kind") == "v23_ledger_genesis_anchor":
            _assert_exact_fields(value, GENESIS_ANCHOR_FIELDS, kind="genesis_anchor")
        elif value.get("kind") == "v23_ledger_tip_anchor":
            expected = {
                "kind",
                "protocol_revision_id",
                "attempt_id",
                "reservation_batch_id",
                "first_sequence",
                "last_sequence",
                "batch_size",
                "prior_ledger_tip_sha256",
                "ledger_tip_sha256",
                "created_at",
            }
            _assert_exact_fields(value, expected, kind="ledger_tip_anchor")
        else:
            raise RuntimeError("ledger_tip_anchor_kind_invalid")
        matches.append(path)
    if len(matches) != 1:
        raise RuntimeError("ledger_tip_anchor_count_invalid")
    return matches[0]


def _require_aggregate_df_genesis_ledger(root: Path) -> dict[str, Any]:
    state = validate_ledger(_resolve(CONSUMPTION_LEDGER, root))
    if state["row_count"] != 1:
        raise RuntimeError("aggregate_df_must_precede_source_reservation")
    return state


def append_reservation_batch(
    *,
    ledger_path: str | Path,
    anchor_directory: str | Path,
    protocol_revision: str,
    attempt: str,
    role: str,
    dataset: str,
    identities: Sequence[Mapping[str, str]],
    expected_prior_tip: str,
    reason: str,
    authorization: Mapping[str, Any],
    attempt_registry_row: Mapping[str, Any],
    budget_journal_path: str | Path,
) -> dict[str, Any]:
    """Append precomputed source identities before any source content becomes visible."""

    ledger = Path(ledger_path)
    if role not in LEDGER_ROLES or dataset not in DATASET_ORDER or not identities:
        raise ValueError("reservation_batch_scope_invalid")
    ordered = []
    for item in identities:
        if set(item) != {"source_key", "source_hash", "normalized_text_hash"}:
            raise ValueError("reservation_identity_schema_invalid")
        if not _is_sha256(item["source_hash"]) or not _is_sha256(item["normalized_text_hash"]):
            raise ValueError("reservation_identity_hash_invalid")
        ordered.append(dict(item))
    validated_authorization = validate_run_authorization(
        authorization,
        stage=str(authorization.get("authorized_stage")),
        execution_unit=str(authorization.get("execution_unit")),
        attempt_registry_row=attempt_registry_row,
        dataset=dataset,
    )
    if validated_authorization["budget_kind"] != "sources":
        raise RuntimeError("reservation_authorization_budget_kind_invalid")
    allowed_roles = RESERVATION_ROLES_BY_STAGE.get(
        validated_authorization["authorized_stage"], frozenset()
    )
    grouped_reservation = (
        validated_authorization["authorized_stage"] == RESERVATION_STAGE
        and validated_authorization["execution_unit"] == "all_datasets_group"
    )
    if (
        validated_authorization["protocol_revision_id"] != protocol_revision
        or validated_authorization["attempt_id"] != attempt
        or not grouped_reservation
        and validated_authorization["expected_prior_ledger_tip_sha256"]
        != expected_prior_tip
        or role not in allowed_roles
        or role not in validated_authorization["run_roles"]
    ):
        raise RuntimeError("reservation_authorization_scope_mismatch")
    identity_hash = canonical_sha256(ordered)
    batch_payload = {
        "kind": "v23_reservation_batch",
        "protocol_revision_id": protocol_revision,
        "attempt_id": attempt,
        "role": role,
        "dataset": dataset,
        "expected_batch_size": len(ordered),
        "ordered_source_identity_sha256": identity_hash,
        "expected_prior_ledger_tip_sha256": expected_prior_tip,
    }
    batch_id = canonical_sha256(batch_payload)
    with exclusive_lock(ledger.with_suffix(ledger.suffix + ".lock")):
        state = validate_ledger(ledger)
        ledger_rows = [
            json.loads(line)
            for line in ledger.read_text(encoding="utf-8").splitlines()
        ]
        prior_sequences = [
            index
            for index, row in enumerate(ledger_rows)
            if row["row_sha256"] == expected_prior_tip
        ]
        if len(prior_sequences) != 1:
            raise RuntimeError("reservation_prior_ledger_tip_missing")
        if grouped_reservation:
            authorization_prior_sequences = [
                index
                for index, row in enumerate(ledger_rows)
                if row["row_sha256"]
                == validated_authorization["expected_prior_ledger_tip_sha256"]
            ]
            if (
                len(authorization_prior_sequences) != 1
                or authorization_prior_sequences[0] > prior_sequences[0]
            ):
                raise RuntimeError("reservation_group_prior_ledger_tip_drift")
        first_sequence = prior_sequences[0] + 1
        prefix = ledger_rows[first_sequence:]
        if len(prefix) > len(ordered):
            raise RuntimeError("reservation_interrupted_prefix_too_long")
        for index, (row, identity) in enumerate(zip(prefix, ordered)):
            expected_values = {
                "kind": "v23_consumed_source",
                "sequence": first_sequence + index,
                "protocol_revision_id": protocol_revision,
                "attempt_id": attempt,
                "reservation_batch_id": batch_id,
                "reservation_batch_index": index,
                "reservation_batch_size": len(ordered),
                "role": role,
                "dataset": dataset,
                **identity,
                "reason": reason,
            }
            if any(row.get(key) != value for key, value in expected_values.items()):
                raise RuntimeError("reservation_interrupted_prefix_drift")
        if not prefix and state["tip_sha256"] != expected_prior_tip:
            raise RuntimeError("reservation_prior_ledger_tip_mismatch")
        charged_count, _, charged_operations = _read_budget_state(
            Path(budget_journal_path), validated_authorization
        )
        if charged_count < len(prefix):
            raise RuntimeError("reservation_durable_row_without_budget_charge")
        for index, identity in enumerate(ordered[: len(prefix)]):
            operation_identity = canonical_sha256(
                {
                    "kind": "v23_source_reservation",
                    "reservation_batch_id": batch_id,
                    "reservation_batch_index": index,
                    "source_key": identity["source_key"],
                }
            )
            if operation_identity not in charged_operations:
                raise RuntimeError("reservation_durable_row_without_matching_charge")
        missing_count = len(ordered) - len(prefix)
        if charged_count + missing_count > validated_authorization["budget_limit"]:
            raise RuntimeError("authorization_budget_exhausted")
        previous = prefix[-1]["row_sha256"] if prefix else expected_prior_tip
        with ledger.open("a", encoding="utf-8", newline="\n") as handle:
            for index in range(len(prefix), len(ordered)):
                identity = ordered[index]
                operation_identity = canonical_sha256(
                    {
                        "kind": "v23_source_reservation",
                        "reservation_batch_id": batch_id,
                        "reservation_batch_index": index,
                        "source_key": identity["source_key"],
                    }
                )
                if operation_identity in charged_operations:
                    raise RuntimeError("reservation_budget_charge_without_durable_row")
                charge_authorization_budget(
                    validated_authorization,
                    journal_path=budget_journal_path,
                    operation_identity_sha256=operation_identity,
                )
                row = {
                    "kind": "v23_consumed_source",
                    "sequence": first_sequence + index,
                    "protocol_revision_id": protocol_revision,
                    "attempt_id": attempt,
                    "reservation_batch_id": batch_id,
                    "reservation_batch_index": index,
                    "reservation_batch_size": len(ordered),
                    "role": role,
                    "dataset": dataset,
                    **identity,
                    "consumed_at": utc_now(),
                    "reason": reason,
                    "previous_row_sha256": previous,
                }
                row["row_sha256"] = canonical_sha256(row)
                handle.write(canonical_json(row) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                previous = row["row_sha256"]
        anchor = {
            "kind": "v23_ledger_tip_anchor",
            "protocol_revision_id": protocol_revision,
            "attempt_id": attempt,
            "reservation_batch_id": batch_id,
            "first_sequence": first_sequence,
            "last_sequence": first_sequence + len(ordered) - 1,
            "batch_size": len(ordered),
            "prior_ledger_tip_sha256": expected_prior_tip,
            "ledger_tip_sha256": previous,
            "created_at": utc_now(),
        }
        anchor_path = Path(anchor_directory) / f"{anchor['last_sequence']:012d}_{previous}.json"
        if anchor_path.exists():
            existing_anchor = _read_json_exact(anchor_path)
            if any(
                existing_anchor.get(key) != value
                for key, value in anchor.items()
                if key != "created_at"
            ):
                raise RuntimeError("ledger_tip_anchor_identity_drift")
        else:
            _write_canonical_json(anchor_path, anchor)
    return {
        "reservation_batch_id": batch_id,
        "ledger_tip_sha256": previous,
        "anchor_path": str(anchor_path),
        "anchor_sha256": sha256_file(anchor_path),
    }


BUDGET_FIELDS = {
    "kind",
    "sequence",
    "authorization_id",
    "attempt_id",
    "stage",
    "execution_unit",
    "charge_ordinal",
    "charge_kind",
    "charge_amount",
    "operation_identity_sha256",
    "previous_row_sha256",
    "row_sha256",
    "charged_at",
}


def _read_budget_state(path: Path, authorization: Mapping[str, Any]) -> tuple[int, str, set[str]]:
    if not path.exists():
        return 0, ZERO_SHA256, set()
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise RuntimeError("authorization_budget_partial_trailing_line")
    previous = ZERO_SHA256
    operations: set[str] = set()
    count = 0
    for sequence, line in enumerate(raw.decode("utf-8").splitlines()):
        row = json.loads(line)
        _assert_exact_fields(row, BUDGET_FIELDS, kind="authorization_budget")
        if row["sequence"] != sequence or row["charge_ordinal"] != sequence:
            raise RuntimeError("authorization_budget_sequence_drift")
        if row["previous_row_sha256"] != previous or row["charge_amount"] != 1:
            raise RuntimeError("authorization_budget_chain_drift")
        for key in ("authorization_id", "attempt_id", "stage", "execution_unit"):
            if row[key] != authorization[key if key != "stage" else "authorized_stage"]:
                raise RuntimeError("authorization_budget_scope_drift")
        if canonical_sha256({key: value for key, value in row.items() if key != "row_sha256"}) != row["row_sha256"]:
            raise RuntimeError("authorization_budget_row_hash_drift")
        if row["operation_identity_sha256"] in operations:
            raise RuntimeError("authorization_budget_duplicate_operation")
        operations.add(row["operation_identity_sha256"])
        previous = row["row_sha256"]
        count += 1
    return count, previous, operations


def charge_authorization_budget(
    authorization: Mapping[str, Any],
    *,
    journal_path: str | Path,
    operation_identity_sha256: str,
) -> dict[str, Any]:
    if authorization["budget_kind"] == "none":
        raise RuntimeError("authorization_budget_charge_for_none")
    if not _is_sha256(operation_identity_sha256):
        raise ValueError("authorization_operation_identity_invalid")
    path = Path(journal_path)
    with exclusive_lock(path.with_suffix(path.suffix + ".lock")):
        count, previous, operations = _read_budget_state(path, authorization)
        if operation_identity_sha256 in operations:
            raise RuntimeError("authorization_operation_already_charged")
        if count >= authorization["budget_limit"]:
            raise RuntimeError("authorization_budget_exhausted")
        row = {
            "kind": "v23_authorization_budget_charge",
            "sequence": count,
            "authorization_id": authorization["authorization_id"],
            "attempt_id": authorization["attempt_id"],
            "stage": authorization["authorized_stage"],
            "execution_unit": authorization["execution_unit"],
            "charge_ordinal": count,
            "charge_kind": authorization["budget_kind"],
            "charge_amount": 1,
            "operation_identity_sha256": operation_identity_sha256,
            "previous_row_sha256": previous,
            "charged_at": utc_now(),
        }
        row["row_sha256"] = canonical_sha256(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return row


def authorized_operation(
    authorization: Mapping[str, Any],
    *,
    journal_path: str | Path,
    operation_payload: Mapping[str, Any],
    operation: Callable[[], _T],
) -> _T:
    operation_identity = canonical_sha256(operation_payload)
    charge_authorization_budget(
        authorization,
        journal_path=journal_path,
        operation_identity_sha256=operation_identity,
    )
    return operation()


def write_stage_checkpoint(path: str | Path, checkpoint: Mapping[str, Any]) -> None:
    row = dict(checkpoint)
    _assert_exact_fields(row, STAGE_CHECKPOINT_FIELDS, kind="stage_checkpoint")
    if row["kind"] != "v23_stage_checkpoint" or row["status"] not in CHECKPOINT_STATUSES:
        raise RuntimeError("stage_checkpoint_constant_invalid")
    if not row["ledger_mutation"] and (
        row["input_ledger_tip_sha256"] != row["output_ledger_tip_sha256"]
        or row["input_tip_anchor_sha256"] != row["output_tip_anchor_sha256"]
    ):
        raise RuntimeError("stage_checkpoint_no_mutation_tip_drift")
    _write_new_atomic_canonical_json(Path(path), row)


def require_passed_checkpoint(path: str | Path, *, stage: str | None = None) -> dict[str, Any]:
    checkpoint = _read_json_exact(Path(path))
    _assert_exact_fields(
        checkpoint, STAGE_CHECKPOINT_FIELDS, kind="stage_checkpoint"
    )
    if checkpoint.get("kind") != "v23_stage_checkpoint" or checkpoint.get("status") != "passed":
        raise RuntimeError("required_stage_checkpoint_not_passed")
    if stage is not None and checkpoint.get("stage") != stage:
        raise RuntimeError("required_stage_checkpoint_stage_mismatch")
    return checkpoint


def verify_bound_file(path: str | Path, expected_sha256: str) -> None:
    candidate = Path(path)
    if not candidate.is_file() or sha256_file(candidate) != expected_sha256:
        raise RuntimeError(f"bound_file_hash_drift:{candidate}")


class FrozenSourcePoolReader:
    """Read one bound v22 source at a time through an immutable SQLite connection."""

    _SOURCE_COLUMNS = ("source_key", "source_order_rank", "full_text", "input_row_count")
    _CHUNK_COLUMNS = ("source_key", "chunk_rank", "selection_hash", "row_json")

    def __init__(
        self,
        *,
        project_root: str | Path,
        dataset: str,
        database_path: str,
        database_sha256: str,
        source_order_path: str,
        source_order_file_sha256: str,
        source_pool_manifest_path: str,
        source_pool_manifest_sha256: str,
        expected_source_count: int,
    ) -> None:
        if dataset not in DATASET_ORDER:
            raise ValueError("source_pool_dataset_invalid")
        self.root = Path(project_root).resolve()
        self.dataset = dataset
        self.database_path = _resolve(database_path, self.root)
        self.source_order_path = _resolve(source_order_path, self.root)
        self.manifest_path = _resolve(source_pool_manifest_path, self.root)
        verify_bound_file(self.database_path, database_sha256)
        verify_bound_file(self.source_order_path, source_order_file_sha256)
        verify_bound_file(self.manifest_path, source_pool_manifest_sha256)
        order_payload = _read_json_exact(self.source_order_path)
        if set(order_payload) != {
            "protocol",
            "dataset",
            "selection_seed",
            "source_order",
            "source_order_sha256",
            "label_fields_read",
        }:
            raise RuntimeError("source_order_schema_drift")
        order = order_payload["source_order"]
        if (
            order_payload["dataset"] != dataset
            or not isinstance(order, list)
            or len(order) != expected_source_count
            or len(set(order)) != len(order)
            or not all(isinstance(item, str) and item for item in order)
        ):
            raise RuntimeError("source_order_identity_drift")
        self.source_order = tuple(order)
        self.source_count = expected_source_count
        uri = self.database_path.as_uri() + "?mode=ro&immutable=1"
        self._connection = sqlite3.connect(uri, uri=True)
        self._connection.row_factory = sqlite3.Row
        self._validate_schema()

    def _validate_schema(self) -> None:
        source_columns = tuple(
            row[1] for row in self._connection.execute("PRAGMA table_info(sources)").fetchall()
        )
        chunk_columns = tuple(
            row[1] for row in self._connection.execute("PRAGMA table_info(chunks)").fetchall()
        )
        if source_columns != self._SOURCE_COLUMNS or chunk_columns != self._CHUNK_COLUMNS:
            raise RuntimeError("source_pool_database_schema_drift")
        source_count = self._connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        if source_count != self.source_count:
            raise RuntimeError("source_pool_database_count_drift")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "FrozenSourcePoolReader":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def source_identity(self, source_order_index: int) -> dict[str, Any]:
        if not 0 <= source_order_index < self.source_count:
            raise IndexError("source_order_index_out_of_range")
        return {
            "source_order_index": source_order_index,
            "source_key": self.source_order[source_order_index],
        }

    def registration_identity(self, source_key: str) -> dict[str, str]:
        """Return only trusted write-ahead hashes, never source content or features."""

        if source_key not in self.source_order:
            raise KeyError(f"source_order_key_missing:{source_key}")
        row = self._connection.execute(
            "SELECT full_text FROM sources WHERE source_key = ?", (source_key,)
        ).fetchone()
        if row is None:
            raise KeyError(f"source_pool_source_missing:{source_key}")
        full_text = row["full_text"]
        if not isinstance(full_text, str) or not full_text:
            raise RuntimeError("source_pool_registration_text_invalid")
        return {
            "source_key": source_key,
            "source_hash": text_sha256(full_text),
            "normalized_text_hash": normalized_text_sha256(full_text),
        }

    def read_source(self, source_key: str) -> dict[str, Any]:
        raise RuntimeError("unguarded_source_read_forbidden")

    def _read_source_unchecked(self, source_key: str) -> dict[str, Any]:

        source = self._connection.execute(
            "SELECT source_key, source_order_rank, full_text, input_row_count "
            "FROM sources WHERE source_key = ?",
            (source_key,),
        ).fetchone()
        if source is None:
            raise KeyError(f"source_pool_source_missing:{source_key}")
        chunks = self._connection.execute(
            "SELECT source_key, chunk_rank, selection_hash, row_json "
            "FROM chunks WHERE source_key = ? ORDER BY chunk_rank ASC",
            (source_key,),
        ).fetchall()
        payload = {
            "dataset": self.dataset,
            "source_key": source["source_key"],
            "source_order_rank": source["source_order_rank"],
            "full_text": source["full_text"],
            "input_row_count": source["input_row_count"],
            "chunks": [
                {
                    "source_key": row["source_key"],
                    "chunk_rank": row["chunk_rank"],
                    "selection_hash": row["selection_hash"],
                    "row": json.loads(row["row_json"]),
                }
                for row in chunks
            ],
        }
        return validate_selector_source_input(payload)

    def read_source_for_aggregate_df(
        self,
        source_key: str,
        *,
        authorization: Mapping[str, Any],
        attempt_registry_row: Mapping[str, Any],
        budget_journal_path: str | Path,
    ) -> dict[str, Any]:
        validate_run_authorization(
            authorization,
            stage="aggregate_df_precomputation",
            execution_unit="one_dataset",
            attempt_registry_row=attempt_registry_row,
            dataset=self.dataset,
        )
        if source_key not in self.source_order:
            raise KeyError(f"source_order_key_missing:{source_key}")
        operation = canonical_sha256(
            {
                "kind": "v23_aggregate_df_source_read",
                "authorization_id": authorization["authorization_id"],
                "dataset": self.dataset,
                "source_key": source_key,
            }
        )
        charge_authorization_budget(
            authorization,
            journal_path=budget_journal_path,
            operation_identity_sha256=operation,
        )
        return self._read_source_unchecked(source_key)

    def read_reserved_source(
        self,
        source_key: str,
        *,
        ledger_path: str | Path,
        anchor_path: str | Path,
        authorization: Mapping[str, Any],
        attempt_registry_row: Mapping[str, Any],
        budget_journal_path: str | Path,
        resume_existing_charge: bool = False,
    ) -> dict[str, Any]:
        validated_authorization = validate_run_authorization(
            authorization,
            stage=str(authorization.get("authorized_stage")),
            execution_unit=str(authorization.get("execution_unit")),
            attempt_registry_row=attempt_registry_row,
            dataset=self.dataset,
        )
        stage = validated_authorization["authorized_stage"]
        role_by_stage = {
            "development_pilot_and_capacity_gate": "development",
            "fresh_blind_audit": "fresh_audit_reserve",
            "formal_source_scan": "formal_scan_viewed",
        }
        required_role = role_by_stage.get(stage)
        if required_role is None or required_role not in validated_authorization["run_roles"]:
            raise RuntimeError("reserved_source_authorization_scope_mismatch")
        state = validate_ledger(ledger_path)
        anchor = _read_json_exact(Path(anchor_path))
        expected_anchor_fields = {
            "kind",
            "protocol_revision_id",
            "attempt_id",
            "reservation_batch_id",
            "first_sequence",
            "last_sequence",
            "batch_size",
            "prior_ledger_tip_sha256",
            "ledger_tip_sha256",
            "created_at",
        }
        _assert_exact_fields(anchor, expected_anchor_fields, kind="reserved_source_anchor")
        anchor_revision_matches = (
            anchor["protocol_revision_id"]
            == validated_authorization["protocol_revision_id"]
            or required_role == "development"
            and _is_sha256(anchor["protocol_revision_id"])
        )
        if (
            anchor["kind"] != "v23_ledger_tip_anchor"
            or not anchor_revision_matches
            or not _is_sha256(anchor["attempt_id"])
            or not _is_sha256(anchor["reservation_batch_id"])
            or not _is_sha256(anchor["prior_ledger_tip_sha256"])
            or not _is_sha256(anchor["ledger_tip_sha256"])
            or isinstance(anchor["first_sequence"], bool)
            or not isinstance(anchor["first_sequence"], int)
            or anchor["first_sequence"] < 1
            or isinstance(anchor["last_sequence"], bool)
            or not isinstance(anchor["last_sequence"], int)
            or isinstance(anchor["batch_size"], bool)
            or not isinstance(anchor["batch_size"], int)
            or anchor["batch_size"] < 1
            or anchor["last_sequence"] - anchor["first_sequence"] + 1
            != anchor["batch_size"]
        ):
            raise RuntimeError("reserved_source_anchor_identity_drift")
        ledger_rows = [
            json.loads(line)
            for line in Path(ledger_path).read_text(encoding="utf-8").splitlines()
        ]
        if (
            anchor["last_sequence"] >= state["row_count"]
            or ledger_rows[anchor["last_sequence"]]["row_sha256"]
            != anchor["ledger_tip_sha256"]
        ):
            raise RuntimeError("reserved_source_anchor_not_in_ledger_chain")
        batch_rows = ledger_rows[
            anchor["first_sequence"] : anchor["last_sequence"] + 1
        ]
        if any(
            row.get("reservation_batch_id") != anchor["reservation_batch_id"]
            or row.get("reservation_batch_index") != index
            or row.get("reservation_batch_size") != anchor["batch_size"]
            for index, row in enumerate(batch_rows)
        ):
            raise RuntimeError("reserved_source_anchor_batch_drift")
        found_row: Mapping[str, Any] | None = None
        for row in batch_rows:
            row_revision_matches = (
                row.get("protocol_revision_id") == anchor["protocol_revision_id"]
                if required_role == "development"
                else row.get("protocol_revision_id")
                == validated_authorization["protocol_revision_id"]
            )
            if (
                row.get("source_key") == source_key
                and row_revision_matches
                and row.get("role") == required_role
            ):
                if (
                    stage == "formal_source_scan"
                    and row.get("attempt_id") != validated_authorization["attempt_id"]
                ):
                    raise RuntimeError("reserved_source_formal_attempt_drift")
                found_row = row
                break
        if found_row is None:
            raise RuntimeError("reserved_source_not_in_durable_batch")
        if source_key not in self.source_order:
            raise RuntimeError("reserved_source_not_in_frozen_order")
        if stage in {"development_pilot_and_capacity_gate", "fresh_blind_audit"}:
            operation_identity = canonical_sha256(
                {
                    "kind": "v23_reserved_source_selector_read",
                    "authorization_id": validated_authorization["authorization_id"],
                    "dataset": self.dataset,
                    "source_key": source_key,
                    "reservation_batch_id": anchor["reservation_batch_id"],
                }
            )
            if resume_existing_charge:
                _, _, charged_operations = _read_budget_state(
                    Path(budget_journal_path), validated_authorization
                )
                if operation_identity not in charged_operations:
                    raise RuntimeError("reserved_source_resume_charge_missing")
            else:
                charge_authorization_budget(
                    validated_authorization,
                    journal_path=budget_journal_path,
                    operation_identity_sha256=operation_identity,
                )
        source = self._read_source_unchecked(source_key)
        if (
            text_sha256(source["full_text"]) != found_row["source_hash"]
            or normalized_text_sha256(source["full_text"])
            != found_row["normalized_text_hash"]
        ):
            raise RuntimeError("reserved_source_content_identity_drift")
        return source


def write_aggregate_df_artifacts(
    *,
    source_texts: Iterable[str],
    rows_path: str | Path,
    manifest_path: str | Path,
    dataset: str,
    protocol_revision: str,
    input_identity_sha256: str,
    tokenization_contract_sha256: str,
    token_df_rows_path: str,
) -> dict[str, Any]:
    """Write only aggregate token DF; authorization charging must wrap each source read."""

    if dataset not in DATASET_ORDER:
        raise ValueError("aggregate_df_dataset_invalid")
    rows = Path(rows_path)
    manifest_file = Path(manifest_path)
    rows.parent.mkdir(parents=True, exist_ok=True)
    temporary = rows.with_suffix(rows.suffix + ".tmp")
    if rows.exists() or manifest_file.exists() or temporary.exists():
        raise RuntimeError("aggregate_df_existing_or_partial_artifact")
    token_df, source_count = aggregate_document_frequency(source_texts)
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        for token in sorted(token_df):
            handle.write(
                canonical_json(
                    {
                        "kind": "v23_token_document_frequency",
                        "token": token,
                        "document_frequency": token_df[token],
                    }
                )
                + "\n"
            )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, rows)
    manifest = {
        "kind": "v23_aggregate_document_frequency",
        "protocol_revision_id": protocol_revision,
        "dataset": dataset,
        "input_identity_sha256": input_identity_sha256,
        "source_count": source_count,
        "token_count": len(token_df),
        "token_df_rows_path": token_df_rows_path,
        "token_df_rows_file_sha256": sha256_file(rows),
        "tokenization_contract_sha256": tokenization_contract_sha256,
        "created_at": utc_now(),
        "external_calls_performed": 0,
    }
    _write_new_canonical_json(manifest_file, manifest)
    return manifest


def _aggregate_df_contracts(config: Mapping[str, Any], dataset: str) -> dict[str, Any]:
    pools = config.get("frozen_v22_bindings", {}).get("source_pools", {})
    pool = pools.get(dataset) if isinstance(pools, Mapping) else None
    selector = config.get("selector_primitives")
    if not isinstance(pool, Mapping) or not isinstance(selector, Mapping):
        raise RuntimeError("aggregate_df_config_binding_missing")
    required = {
        "manifest_path",
        "manifest_sha256",
        "database_path",
        "database_sha256",
        "source_order_path",
        "source_order_file_sha256",
        "source_count",
    }
    if not required.issubset(pool):
        raise RuntimeError("aggregate_df_source_pool_binding_incomplete")
    tokenization = selector.get("tokenization")
    normalization = selector.get("text_normalization")
    if not isinstance(tokenization, Mapping) or not isinstance(normalization, Mapping):
        raise RuntimeError("aggregate_df_tokenization_binding_missing")
    return {
        "pool": dict(pool),
        "normalization_version": normalization.get("name"),
        "tokenization_contract": {
            "normalization": dict(normalization),
            "tokenization": dict(tokenization),
        },
    }


def _aggregate_df_input_identity(
    *,
    runtime_bundle_sha256: str,
    dataset: str,
    contracts: Mapping[str, Any],
) -> tuple[str, str]:
    pool = contracts["pool"]
    tokenization_sha256 = canonical_sha256(contracts["tokenization_contract"])
    identity = canonical_sha256(
        {
            "kind": "v23_aggregate_df_input_identity",
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "runtime_bundle_sha256": runtime_bundle_sha256,
            "dataset": dataset,
            "source_pool_manifest_sha256": pool["manifest_sha256"],
            "database_sha256": pool["database_sha256"],
            "source_order_file_sha256": pool["source_order_file_sha256"],
            "exact_bound_source_count": pool["source_count"],
            "normalization_version": contracts["normalization_version"],
            "tokenization_contract_sha256": tokenization_sha256,
        }
    )
    return identity, tokenization_sha256


def _verify_aggregate_df_pool_bindings(
    root: Path, pool: Mapping[str, Any]
) -> None:
    for path_key, hash_key in (
        ("manifest_path", "manifest_sha256"),
        ("database_path", "database_sha256"),
        ("source_order_path", "source_order_file_sha256"),
    ):
        verify_bound_file(_resolve(pool[path_key], root), pool[hash_key])


def _aggregate_df_paths(root: Path, dataset: str, attempt: str) -> dict[str, Path]:
    return {
        "rows": _resolve(AGGREGATE_DF_DIRECTORY / dataset / "token_df.jsonl", root),
        "manifest": _resolve(AGGREGATE_DF_DIRECTORY / dataset / "df_manifest.json", root),
        "checkpoint": _resolve(
            ARTIFACT_ROOT
            / "checkpoints"
            / "aggregate_df_precomputation"
            / dataset
            / f"{attempt}.json",
            root,
        ),
    }


def _load_run_authorization_file(
    *,
    root: Path,
    authorization_path: str | Path,
    dataset: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _resolve(authorization_path, root)
    authorization = _read_json_exact(path)
    expected_path = _resolve(
        RUN_AUTH_DIRECTORY / f"{authorization.get('authorization_id')}.json", root
    )
    if path != expected_path:
        raise RuntimeError("run_authorization_path_drift")
    rows = _read_attempt_registry(_resolve(ATTEMPT_REGISTRY, root))
    matches = [row for row in rows if row["attempt_id"] == authorization.get("attempt_id")]
    if len(matches) != 1:
        raise RuntimeError("run_authorization_attempt_registry_missing")
    validated = validate_run_authorization(
        authorization,
        stage="aggregate_df_precomputation",
        execution_unit="one_dataset",
        attempt_registry_row=matches[0],
        dataset=dataset,
    )
    return validated, matches[0]


def prepare_aggregate_df_authorization(
    *,
    project_root: str | Path,
    dataset: str,
    user_authorization_record: str,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    lock_path = _resolve(
        ARTIFACT_ROOT / "governance" / "aggregate_df_preparation.lock", root
    )
    with exclusive_lock(lock_path):
        return _prepare_aggregate_df_authorization_unlocked(
            project_root=root,
            dataset=dataset,
            user_authorization_record=user_authorization_record,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )


def _prepare_aggregate_df_authorization_unlocked(
    *,
    project_root: str | Path,
    dataset: str,
    user_authorization_record: str,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    if dataset not in DATASET_ORDER or not user_authorization_record.strip():
        raise ValueError("aggregate_df_authorization_scope_invalid")
    root = Path(project_root).resolve()
    active = validate_active_runtime(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    config = load_design_config(root)
    for prior_dataset in DATASET_ORDER[: DATASET_ORDER.index(dataset)]:
        validate_aggregate_df(
            project_root=root,
            dataset=prior_dataset,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
    contracts = _aggregate_df_contracts(config, dataset)
    pool = contracts["pool"]
    if (
        isinstance(pool["source_count"], bool)
        or not isinstance(pool["source_count"], int)
        or pool["source_count"] < 1
    ):
        raise RuntimeError("aggregate_df_source_count_invalid")
    _verify_aggregate_df_pool_bindings(root, pool)
    rows_path = _resolve(AGGREGATE_DF_DIRECTORY / dataset / "token_df.jsonl", root)
    manifest_path = _resolve(AGGREGATE_DF_DIRECTORY / dataset / "df_manifest.json", root)
    checkpoints = list(
        _resolve(
            ARTIFACT_ROOT / "checkpoints/aggregate_df_precomputation" / dataset,
            root,
        ).glob("*.json")
    )
    existing_authorizations = []
    auth_dir = _resolve(RUN_AUTH_DIRECTORY, root)
    if auth_dir.exists():
        for path in auth_dir.glob("*.json"):
            candidate = _read_json_exact(path)
            if (
                candidate.get("authorized_stage") == "aggregate_df_precomputation"
                and candidate.get("runtime_bundle_sha256")
                == active["runtime_bundle_sha256"]
                and candidate.get("datasets") == [dataset]
            ):
                existing_authorizations.append(path)
    if rows_path.exists() or manifest_path.exists() or checkpoints or existing_authorizations:
        raise RuntimeError("aggregate_df_attempt_or_artifact_already_exists")
    ledger = _require_aggregate_df_genesis_ledger(root)
    registry = allocate_attempt(
        registry_path=_resolve(ATTEMPT_REGISTRY, root),
        protocol_revision=active["protocol_revision_id"],
        stage="aggregate_df_precomputation",
        execution_unit="one_dataset",
        expected_prior_ledger_tip_sha256=ledger["tip_sha256"],
    )
    authorization = {
        "kind": "v23_run_authorization",
        "user_authorization_record": user_authorization_record,
        "protocol_revision_id": active["protocol_revision_id"],
        "attempt_id": registry["attempt_id"],
        "authorized_stage": "aggregate_df_precomputation",
        "execution_unit": "one_dataset",
        "expected_prior_ledger_tip_sha256": ledger["tip_sha256"],
        "datasets": [dataset],
        "run_roles": [],
        "model_or_retriever_cells": [],
        "budget_kind": "sources",
        "budget_limit": pool["source_count"],
        "issued_at": utc_now(),
        "expires_at_or_null": None,
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "runtime_bundle_sha256": active["runtime_bundle_sha256"],
    }
    authorization["authorization_id"] = canonical_sha256(authorization)
    path = _resolve(
        RUN_AUTH_DIRECTORY / f"{authorization['authorization_id']}.json", root
    )
    _write_new_canonical_json(path, authorization)
    return {
        **authorization,
        "authorization_path": _relative(path, root),
        "source_pool_contents_read": False,
        "external_calls_performed": 0,
    }


def run_aggregate_df(
    *,
    project_root: str | Path,
    dataset: str,
    authorization_path: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    lock_path = _resolve(
        ARTIFACT_ROOT
        / "governance"
        / "aggregate_df_precomputation.lock",
        root,
    )
    with exclusive_lock(lock_path):
        return _run_aggregate_df_unlocked(
            project_root=root,
            dataset=dataset,
            authorization_path=authorization_path,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )


def _run_aggregate_df_unlocked(
    *,
    project_root: str | Path,
    dataset: str,
    authorization_path: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    if dataset not in DATASET_ORDER:
        raise ValueError("aggregate_df_dataset_invalid")
    root = Path(project_root).resolve()
    active = validate_active_runtime(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    authorization, registry = _load_run_authorization_file(
        root=root, authorization_path=authorization_path, dataset=dataset
    )
    if (
        authorization["runtime_bundle_sha256"] != active["runtime_bundle_sha256"]
        or authorization["protocol_revision_id"] != active["protocol_revision_id"]
    ):
        raise RuntimeError("aggregate_df_authorization_active_runtime_drift")
    config = load_design_config(root)
    for prior_dataset in DATASET_ORDER[: DATASET_ORDER.index(dataset)]:
        validate_aggregate_df(
            project_root=root,
            dataset=prior_dataset,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
    contracts = _aggregate_df_contracts(config, dataset)
    pool = contracts["pool"]
    _verify_aggregate_df_pool_bindings(root, pool)
    identity, tokenization_sha256 = _aggregate_df_input_identity(
        runtime_bundle_sha256=active["runtime_bundle_sha256"],
        dataset=dataset,
        contracts=contracts,
    )
    paths = _aggregate_df_paths(root, dataset, authorization["attempt_id"])
    budget_path = _resolve(
        BUDGET_DIRECTORY / f"{authorization['authorization_id']}.jsonl", root
    )
    if paths["rows"].exists() or paths["manifest"].exists() or paths["checkpoint"].exists():
        raise RuntimeError("aggregate_df_output_or_checkpoint_already_exists")
    ledger = _require_aggregate_df_genesis_ledger(root)
    if ledger["tip_sha256"] != authorization["expected_prior_ledger_tip_sha256"]:
        raise RuntimeError("aggregate_df_ledger_tip_drift")
    input_anchor = _ledger_tip_anchor(root, ledger["tip_sha256"])
    input_anchor_sha256 = sha256_file(input_anchor)
    try:
        with FrozenSourcePoolReader(
            project_root=root,
            dataset=dataset,
            database_path=pool["database_path"],
            database_sha256=pool["database_sha256"],
            source_order_path=pool["source_order_path"],
            source_order_file_sha256=pool["source_order_file_sha256"],
            source_pool_manifest_path=pool["manifest_path"],
            source_pool_manifest_sha256=pool["manifest_sha256"],
            expected_source_count=pool["source_count"],
        ) as reader:
            def iter_source_texts() -> Iterator[str]:
                for source_key in reader.source_order:
                    source = reader.read_source_for_aggregate_df(
                        source_key,
                        authorization=authorization,
                        attempt_registry_row=registry,
                        budget_journal_path=budget_path,
                    )
                    yield source["full_text"]

            manifest = write_aggregate_df_artifacts(
                source_texts=iter_source_texts(),
                rows_path=paths["rows"],
                manifest_path=paths["manifest"],
                dataset=dataset,
                protocol_revision=active["protocol_revision_id"],
                input_identity_sha256=identity,
                tokenization_contract_sha256=tokenization_sha256,
                token_df_rows_path=_relative(paths["rows"], root),
            )
        charged_count, budget_tip, _ = _read_budget_state(budget_path, authorization)
        if charged_count != pool["source_count"]:
            raise RuntimeError("aggregate_df_budget_count_incomplete")
        checkpoint = {
            "kind": "v23_stage_checkpoint",
            "protocol_revision_id": active["protocol_revision_id"],
            "attempt_id": authorization["attempt_id"],
            "stage": "aggregate_df_precomputation",
            "execution_unit": "one_dataset",
            "status": "passed",
            "input_ledger_tip_sha256": ledger["tip_sha256"],
            "input_tip_anchor_sha256": input_anchor_sha256,
            "output_ledger_tip_sha256": ledger["tip_sha256"],
            "output_tip_anchor_sha256": input_anchor_sha256,
            "ledger_mutation": False,
            "authorization_id": authorization["authorization_id"],
            "authorization_budget_journal_tip_sha256": budget_tip,
            "runtime_bundle_sha256": active["runtime_bundle_sha256"],
            "output_manifest_sha256": sha256_file(paths["manifest"]),
            "completed_at": utc_now(),
        }
        write_stage_checkpoint(paths["checkpoint"], checkpoint)
    except BaseException:
        charged_count, budget_tip, _ = _read_budget_state(budget_path, authorization)
        if not paths["checkpoint"].exists():
            checkpoint = {
                "kind": "v23_stage_checkpoint",
                "protocol_revision_id": active["protocol_revision_id"],
                "attempt_id": authorization["attempt_id"],
                "stage": "aggregate_df_precomputation",
                "execution_unit": "one_dataset",
                "status": "failed",
                "input_ledger_tip_sha256": ledger["tip_sha256"],
                "input_tip_anchor_sha256": input_anchor_sha256,
                "output_ledger_tip_sha256": ledger["tip_sha256"],
                "output_tip_anchor_sha256": input_anchor_sha256,
                "ledger_mutation": False,
                "authorization_id": authorization["authorization_id"],
                "authorization_budget_journal_tip_sha256": budget_tip,
                "runtime_bundle_sha256": active["runtime_bundle_sha256"],
                "output_manifest_sha256": None,
                "completed_at": utc_now(),
            }
            write_stage_checkpoint(paths["checkpoint"], checkpoint)
        raise
    return validate_aggregate_df(
        project_root=root,
        dataset=dataset,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )


def _validate_aggregate_df_for_producer(
    *,
    project_root: str | Path,
    dataset: str,
    producer_runtime_bundle_sha256: str,
    producer_protocol_revision_id: str,
) -> dict[str, Any]:
    if dataset not in DATASET_ORDER:
        raise ValueError("aggregate_df_dataset_invalid")
    root = Path(project_root).resolve()
    config = load_design_config(root)
    contracts = _aggregate_df_contracts(config, dataset)
    pool = contracts["pool"]
    identity, tokenization_sha256 = _aggregate_df_input_identity(
        runtime_bundle_sha256=producer_runtime_bundle_sha256,
        dataset=dataset,
        contracts=contracts,
    )
    rows_path = _resolve(AGGREGATE_DF_DIRECTORY / dataset / "token_df.jsonl", root)
    manifest_path = _resolve(AGGREGATE_DF_DIRECTORY / dataset / "df_manifest.json", root)
    if not rows_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("aggregate_df_artifact_missing")
    manifest = _read_json_exact(manifest_path)
    expected_manifest_fields = {
        "kind",
        "protocol_revision_id",
        "dataset",
        "input_identity_sha256",
        "source_count",
        "token_count",
        "token_df_rows_path",
        "token_df_rows_file_sha256",
        "tokenization_contract_sha256",
        "created_at",
        "external_calls_performed",
    }
    _assert_exact_fields(manifest, expected_manifest_fields, kind="aggregate_df_manifest")
    expected_constants = {
        "kind": "v23_aggregate_document_frequency",
        "protocol_revision_id": producer_protocol_revision_id,
        "dataset": dataset,
        "input_identity_sha256": identity,
        "source_count": pool["source_count"],
        "token_df_rows_path": _relative(rows_path, root),
        "token_df_rows_file_sha256": sha256_file(rows_path),
        "tokenization_contract_sha256": tokenization_sha256,
        "external_calls_performed": 0,
    }
    if any(manifest[key] != value for key, value in expected_constants.items()):
        raise RuntimeError("aggregate_df_manifest_identity_drift")
    raw = rows_path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise RuntimeError("aggregate_df_rows_partial")
    previous_token: str | None = None
    token_count = 0
    for line in raw.decode("utf-8").splitlines():
        row = json.loads(line)
        if set(row) != {"kind", "token", "document_frequency"}:
            raise RuntimeError("aggregate_df_row_schema_drift")
        token = row["token"]
        frequency = row["document_frequency"]
        if (
            row["kind"] != "v23_token_document_frequency"
            or not isinstance(token, str)
            or not token
            or previous_token is not None
            and token <= previous_token
            or isinstance(frequency, bool)
            or not isinstance(frequency, int)
            or not 1 <= frequency <= pool["source_count"]
        ):
            raise RuntimeError("aggregate_df_row_value_drift")
        previous_token = token
        token_count += 1
    if manifest["token_count"] != token_count:
        raise RuntimeError("aggregate_df_token_count_drift")
    authorization_paths = []
    auth_dir = _resolve(RUN_AUTH_DIRECTORY, root)
    for path in auth_dir.glob("*.json") if auth_dir.exists() else ():
        candidate = _read_json_exact(path)
        if (
            candidate.get("authorized_stage") == "aggregate_df_precomputation"
            and candidate.get("runtime_bundle_sha256")
            == producer_runtime_bundle_sha256
            and candidate.get("datasets") == [dataset]
        ):
            authorization_paths.append(path)
    if len(authorization_paths) != 1:
        raise RuntimeError("aggregate_df_authorization_count_invalid")
    authorization, _ = _load_run_authorization_file(
        root=root, authorization_path=authorization_paths[0], dataset=dataset
    )
    checkpoint_path = _aggregate_df_paths(
        root, dataset, authorization["attempt_id"]
    )["checkpoint"]
    checkpoint = require_passed_checkpoint(
        checkpoint_path, stage="aggregate_df_precomputation"
    )
    budget_path = _resolve(
        BUDGET_DIRECTORY / f"{authorization['authorization_id']}.jsonl", root
    )
    charged_count, budget_tip, _ = _read_budget_state(budget_path, authorization)
    ledger_path = _resolve(CONSUMPTION_LEDGER, root)
    validate_ledger(ledger_path)
    ledger_tip_hashes = {
        json.loads(line)["row_sha256"]
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    }
    checkpoint_tip = checkpoint["input_ledger_tip_sha256"]
    checkpoint_anchor = _ledger_tip_anchor(root, checkpoint_tip)
    checkpoint_anchor_sha256 = sha256_file(checkpoint_anchor)
    if (
        authorization["budget_limit"] != pool["source_count"]
        or charged_count != pool["source_count"]
        or checkpoint["protocol_revision_id"] != producer_protocol_revision_id
        or checkpoint["attempt_id"] != authorization["attempt_id"]
        or checkpoint["execution_unit"] != "one_dataset"
        or checkpoint["authorization_id"] != authorization["authorization_id"]
        or checkpoint["authorization_budget_journal_tip_sha256"] != budget_tip
        or checkpoint["output_manifest_sha256"] != sha256_file(manifest_path)
        or checkpoint["runtime_bundle_sha256"]
        != producer_runtime_bundle_sha256
        or checkpoint_tip != authorization["expected_prior_ledger_tip_sha256"]
        or checkpoint_tip not in ledger_tip_hashes
        or checkpoint["output_ledger_tip_sha256"] != checkpoint_tip
        or checkpoint["input_tip_anchor_sha256"] != checkpoint_anchor_sha256
        or checkpoint["output_tip_anchor_sha256"] != checkpoint_anchor_sha256
        or checkpoint["ledger_mutation"] is not False
    ):
        raise RuntimeError("aggregate_df_checkpoint_or_budget_drift")
    return {
        "status": "passed",
        "dataset": dataset,
        "runtime_bundle_sha256": producer_runtime_bundle_sha256,
        "protocol_revision_id": producer_protocol_revision_id,
        "authorization_id": authorization["authorization_id"],
        "attempt_id": authorization["attempt_id"],
        "source_count": pool["source_count"],
        "token_count": token_count,
        "token_df_rows_file_sha256": manifest["token_df_rows_file_sha256"],
        "df_manifest_file_sha256": sha256_file(manifest_path),
        "budget_charge_count": charged_count,
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }


def validate_aggregate_df(
    *,
    project_root: str | Path,
    dataset: str,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    if dataset not in DATASET_ORDER:
        raise ValueError("aggregate_df_dataset_invalid")
    root = Path(project_root).resolve()
    active = validate_active_runtime(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    manifest_path = _resolve(
        AGGREGATE_DF_DIRECTORY / dataset / "df_manifest.json", root
    )
    if not manifest_path.is_file():
        raise RuntimeError("aggregate_df_artifact_missing")
    manifest = _read_json_exact(manifest_path)
    producer_revision_id = manifest.get("protocol_revision_id")
    lineage = _load_runtime_lineage(root)
    revisions = [
        item
        for item in lineage["revisions"]
        if item["protocol_revision_id"] == producer_revision_id
    ]
    if len(revisions) != 1:
        raise RuntimeError("aggregate_df_producer_revision_unknown")
    producer_revision = revisions[0]
    producer_bundle_id = producer_revision["runtime_bundle_sha256"]
    result = _validate_aggregate_df_for_producer(
        project_root=root,
        dataset=dataset,
        producer_runtime_bundle_sha256=producer_bundle_id,
        producer_protocol_revision_id=producer_revision_id,
    )
    validation_mode = "native"
    compatibility_sha256: str | None = None
    if (
        producer_bundle_id != active["runtime_bundle_sha256"]
        or producer_revision_id != active["protocol_revision_id"]
    ):
        compatibility = validate_stage_carry_forward(
            project_root=root,
            stage="aggregate_df_precomputation",
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        dataset_rows = {
            item["dataset"]: item for item in compatibility["datasets"]
        }
        if (
            dataset not in dataset_rows
            or dataset_rows[dataset]["df_manifest_file_sha256"]
            != result["df_manifest_file_sha256"]
            or dataset_rows[dataset]["token_df_rows_file_sha256"]
            != result["token_df_rows_file_sha256"]
        ):
            raise RuntimeError("aggregate_df_carry_forward_dataset_drift")
        validation_mode = "carried_forward"
        compatibility_sha256 = compatibility["attestation_file_sha256"]
    return {
        **result,
        "runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "protocol_revision_id": active["protocol_revision_id"],
        "artifact_runtime_bundle_sha256": producer_bundle_id,
        "artifact_protocol_revision_id": producer_revision_id,
        "validation_mode": validation_mode,
        "stage_compatibility_file_sha256": compatibility_sha256,
    }


def _aggregate_df_producer_identity(root: Path) -> tuple[str, str]:
    revision_ids: set[str] = set()
    for dataset in DATASET_ORDER:
        path = _resolve(
            AGGREGATE_DF_DIRECTORY / dataset / "df_manifest.json", root
        )
        if not path.is_file():
            raise RuntimeError("aggregate_df_artifact_missing")
        revision_id = _read_json_exact(path).get("protocol_revision_id")
        if not _is_sha256(revision_id):
            raise RuntimeError("aggregate_df_producer_revision_invalid")
        revision_ids.add(revision_id)
    if len(revision_ids) != 1:
        raise RuntimeError("aggregate_df_producer_revision_mixed")
    revision_id = next(iter(revision_ids))
    lineage = _load_runtime_lineage(root)
    revisions = [
        item
        for item in lineage["revisions"]
        if item["protocol_revision_id"] == revision_id
    ]
    if len(revisions) != 1:
        raise RuntimeError("aggregate_df_producer_revision_unknown")
    return revisions[0]["runtime_bundle_sha256"], revision_id


def _aggregate_df_evidence(
    root: Path,
    *,
    dataset: str,
    producer_runtime_bundle_sha256: str,
    producer_protocol_revision_id: str,
) -> dict[str, Any]:
    result = _validate_aggregate_df_for_producer(
        project_root=root,
        dataset=dataset,
        producer_runtime_bundle_sha256=producer_runtime_bundle_sha256,
        producer_protocol_revision_id=producer_protocol_revision_id,
    )
    authorization_path = _resolve(
        RUN_AUTH_DIRECTORY / f"{result['authorization_id']}.json", root
    )
    budget_path = _resolve(
        BUDGET_DIRECTORY / f"{result['authorization_id']}.jsonl", root
    )
    checkpoint_path = _aggregate_df_paths(
        root, dataset, result["attempt_id"]
    )["checkpoint"]
    return {
        "dataset": dataset,
        "authorization_id": result["authorization_id"],
        "attempt_id": result["attempt_id"],
        "source_count": result["source_count"],
        "token_count": result["token_count"],
        "token_df_rows_file_sha256": result["token_df_rows_file_sha256"],
        "df_manifest_file_sha256": result["df_manifest_file_sha256"],
        "run_authorization_file_sha256": sha256_file(authorization_path),
        "budget_journal_file_sha256": sha256_file(budget_path),
        "checkpoint_file_sha256": sha256_file(checkpoint_path),
    }


def _validate_stage_compatibility_authorization(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    authorization = dict(value)
    _assert_exact_fields(
        authorization,
        STAGE_COMPATIBILITY_AUTH_FIELDS,
        kind="stage_compatibility_authorization",
    )
    constants = {
        "kind": "v23_stage_compatibility_authorization",
        "authorized_stage": STAGE_CARRY_FORWARD,
        "execution_unit": "all_datasets_group",
        "stage": "aggregate_df_precomputation",
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "execution_revision": EXECUTION_REVISION,
        "execution_erratum_sha256": EXECUTION_ERRATUM_SHA256,
        "source_pool_contents_read_allowed": False,
        "ledger_mutation_allowed": False,
        "external_calls_allowed": False,
    }
    if any(authorization[key] != expected for key, expected in constants.items()):
        raise RuntimeError("stage_compatibility_authorization_constant_drift")
    for key in (
        "authorization_id",
        "from_runtime_bundle_sha256",
        "from_protocol_revision_id",
        "to_runtime_bundle_sha256",
        "to_protocol_revision_id",
        "stage_dependency_fingerprint",
    ):
        if not _is_sha256(authorization[key]):
            raise RuntimeError(f"stage_compatibility_authorization_hash_invalid:{key}")
    if not str(authorization["user_authorization_record"]).strip():
        raise RuntimeError("stage_compatibility_user_authorization_empty")
    claimed = authorization["authorization_id"]
    if claimed != canonical_sha256(
        {key: item for key, item in authorization.items() if key != "authorization_id"}
    ):
        raise RuntimeError("stage_compatibility_authorization_identity_drift")
    if authorization["expires_at_or_null"] is not None:
        expiry = datetime.fromisoformat(
            str(authorization["expires_at_or_null"]).replace("Z", "+00:00")
        )
        if expiry <= datetime.now(timezone.utc):
            raise RuntimeError("stage_compatibility_authorization_expired")
    return authorization


def _stage_compatibility_path(root: Path, protocol_revision_id: str) -> Path:
    return _resolve(
        STAGE_COMPATIBILITY_DIRECTORY
        / protocol_revision_id
        / "aggregate_df_precomputation.json",
        root,
    )


def prepare_stage_carry_forward_authorization(
    *,
    project_root: str | Path,
    stage: str,
    user_authorization_record: str,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    if stage != "aggregate_df_precomputation" or not user_authorization_record.strip():
        raise ValueError("stage_carry_forward_scope_invalid")
    root = Path(project_root).resolve()
    active = validate_active_runtime(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    producer_bundle, producer_revision = _aggregate_df_producer_identity(root)
    if (
        producer_bundle == active["runtime_bundle_sha256"]
        or producer_revision == active["protocol_revision_id"]
    ):
        raise RuntimeError("stage_carry_forward_transition_missing")
    from_identity = _stage_identity_for_bundle(
        root, stage=stage, runtime_bundle_sha256=producer_bundle
    )
    to_identity = _stage_identity_for_bundle(
        root, stage=stage, runtime_bundle_sha256=active["runtime_bundle_sha256"]
    )
    if (
        from_identity["stage_dependency_fingerprint"]
        != to_identity["stage_dependency_fingerprint"]
    ):
        raise RuntimeError("stage_carry_forward_dependency_drift")
    for dataset in DATASET_ORDER:
        _aggregate_df_evidence(
            root,
            dataset=dataset,
            producer_runtime_bundle_sha256=producer_bundle,
            producer_protocol_revision_id=producer_revision,
        )
    target_path = _stage_compatibility_path(root, active["protocol_revision_id"])
    if target_path.exists():
        raise RuntimeError("stage_carry_forward_attestation_already_exists")
    existing = []
    auth_dir = _resolve(STAGE_COMPATIBILITY_AUTH_DIRECTORY, root)
    if auth_dir.exists():
        for path in auth_dir.glob("*.json"):
            candidate = _read_json_exact(path)
            if (
                candidate.get("stage") == stage
                and candidate.get("to_protocol_revision_id")
                == active["protocol_revision_id"]
            ):
                existing.append(path)
    if existing:
        raise RuntimeError("stage_carry_forward_authorization_already_exists")
    authorization = {
        "kind": "v23_stage_compatibility_authorization",
        "user_authorization_record": user_authorization_record,
        "authorized_stage": STAGE_CARRY_FORWARD,
        "execution_unit": "all_datasets_group",
        "stage": stage,
        "from_runtime_bundle_sha256": producer_bundle,
        "from_protocol_revision_id": producer_revision,
        "to_runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "to_protocol_revision_id": active["protocol_revision_id"],
        "stage_dependency_fingerprint": from_identity[
            "stage_dependency_fingerprint"
        ],
        "issued_at": utc_now(),
        "expires_at_or_null": None,
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "execution_revision": EXECUTION_REVISION,
        "execution_erratum_sha256": EXECUTION_ERRATUM_SHA256,
        "source_pool_contents_read_allowed": False,
        "ledger_mutation_allowed": False,
        "external_calls_allowed": False,
    }
    authorization["authorization_id"] = canonical_sha256(authorization)
    path = _resolve(
        STAGE_COMPATIBILITY_AUTH_DIRECTORY
        / f"{authorization['authorization_id']}.json",
        root,
    )
    _write_new_canonical_json(path, authorization)
    return {
        **authorization,
        "authorization_path": _relative(path, root),
        "source_pool_contents_read": False,
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }


def _load_stage_compatibility_authorization(
    root: Path, authorization_path: str | Path
) -> dict[str, Any]:
    path = _resolve(authorization_path, root)
    authorization = _validate_stage_compatibility_authorization(
        _read_json_exact(path)
    )
    expected = _resolve(
        STAGE_COMPATIBILITY_AUTH_DIRECTORY
        / f"{authorization['authorization_id']}.json",
        root,
    )
    if path != expected:
        raise RuntimeError("stage_compatibility_authorization_path_drift")
    return authorization


def run_stage_carry_forward(
    *,
    project_root: str | Path,
    stage: str,
    authorization_path: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    if stage != "aggregate_df_precomputation":
        raise ValueError("stage_carry_forward_scope_invalid")
    root = Path(project_root).resolve()
    authorization = _load_stage_compatibility_authorization(
        root, authorization_path
    )
    lock_path = _resolve(
        ARTIFACT_ROOT / "governance/stage_compatibility.lock", root
    )
    with exclusive_lock(lock_path):
        active = validate_active_runtime(
            root,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        producer_bundle, producer_revision = _aggregate_df_producer_identity(root)
        if (
            authorization["stage"] != stage
            or authorization["from_runtime_bundle_sha256"] != producer_bundle
            or authorization["from_protocol_revision_id"] != producer_revision
            or authorization["to_runtime_bundle_sha256"]
            != active["runtime_bundle_sha256"]
            or authorization["to_protocol_revision_id"]
            != active["protocol_revision_id"]
        ):
            raise RuntimeError("stage_carry_forward_authorization_runtime_drift")
        from_identity = _stage_identity_for_bundle(
            root, stage=stage, runtime_bundle_sha256=producer_bundle
        )
        to_identity = _stage_identity_for_bundle(
            root,
            stage=stage,
            runtime_bundle_sha256=active["runtime_bundle_sha256"],
        )
        fingerprints = {
            authorization["stage_dependency_fingerprint"],
            from_identity["stage_dependency_fingerprint"],
            to_identity["stage_dependency_fingerprint"],
        }
        if len(fingerprints) != 1:
            raise RuntimeError("stage_carry_forward_dependency_drift")
        evidence = [
            _aggregate_df_evidence(
                root,
                dataset=dataset,
                producer_runtime_bundle_sha256=producer_bundle,
                producer_protocol_revision_id=producer_revision,
            )
            for dataset in DATASET_ORDER
        ]
        ledger = validate_ledger(_resolve(CONSUMPTION_LEDGER, root))
        ledger_anchor = _ledger_tip_anchor(root, ledger["tip_sha256"])
        attestation = {
            "kind": "v23_stage_carry_forward_attestation",
            "authorization_id": authorization["authorization_id"],
            "stage": stage,
            "execution_revision": EXECUTION_REVISION,
            "execution_erratum_sha256": EXECUTION_ERRATUM_SHA256,
            "from_runtime_bundle_sha256": producer_bundle,
            "from_protocol_revision_id": producer_revision,
            "from_stage_execution_identity": from_identity[
                "stage_execution_identity"
            ],
            "to_runtime_bundle_sha256": active["runtime_bundle_sha256"],
            "to_protocol_revision_id": active["protocol_revision_id"],
            "to_stage_execution_identity": to_identity[
                "stage_execution_identity"
            ],
            "stage_dependency_fingerprint": from_identity[
                "stage_dependency_fingerprint"
            ],
            "datasets": evidence,
            "ledger_tip_sha256": ledger["tip_sha256"],
            "ledger_tip_anchor_sha256": sha256_file(ledger_anchor),
            "source_pool_contents_read": False,
            "ledger_mutation": False,
            "external_calls_performed": 0,
            "created_at": utc_now(),
        }
        attestation["attestation_id"] = canonical_sha256(attestation)
        path = _stage_compatibility_path(root, active["protocol_revision_id"])
        _write_new_canonical_json(path, attestation)
    return validate_stage_carry_forward(
        project_root=root,
        stage=stage,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )


def _assert_aggregate_evidence_files(
    root: Path, evidence: Mapping[str, Any]
) -> None:
    _assert_exact_fields(
        evidence,
        STAGE_COMPATIBILITY_DATASET_FIELDS,
        kind="stage_compatibility_dataset",
    )
    dataset = evidence["dataset"]
    if dataset not in DATASET_ORDER:
        raise RuntimeError("stage_compatibility_dataset_invalid")
    paths = {
        "token_df_rows_file_sha256": _resolve(
            AGGREGATE_DF_DIRECTORY / dataset / "token_df.jsonl", root
        ),
        "df_manifest_file_sha256": _resolve(
            AGGREGATE_DF_DIRECTORY / dataset / "df_manifest.json", root
        ),
        "run_authorization_file_sha256": _resolve(
            RUN_AUTH_DIRECTORY / f"{evidence['authorization_id']}.json", root
        ),
        "budget_journal_file_sha256": _resolve(
            BUDGET_DIRECTORY / f"{evidence['authorization_id']}.jsonl", root
        ),
        "checkpoint_file_sha256": _aggregate_df_paths(
            root, dataset, evidence["attempt_id"]
        )["checkpoint"],
    }
    for field, path in paths.items():
        if not path.is_file() or sha256_file(path) != evidence[field]:
            raise RuntimeError(f"stage_compatibility_evidence_drift:{dataset}:{field}")


def validate_stage_carry_forward(
    *,
    project_root: str | Path,
    stage: str,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    if stage != "aggregate_df_precomputation":
        raise ValueError("stage_carry_forward_scope_invalid")
    root = Path(project_root).resolve()
    active = validate_active_runtime(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    path = _stage_compatibility_path(root, active["protocol_revision_id"])
    if not path.is_file():
        raise RuntimeError("stage_carry_forward_attestation_missing")
    attestation = _read_json_exact(path)
    _assert_exact_fields(
        attestation,
        STAGE_COMPATIBILITY_FIELDS,
        kind="stage_compatibility_attestation",
    )
    claimed_attestation_id = attestation["attestation_id"]
    if (
        not _is_sha256(claimed_attestation_id)
        or claimed_attestation_id
        != canonical_sha256(
            {
                key: value
                for key, value in attestation.items()
                if key != "attestation_id"
            }
        )
    ):
        raise RuntimeError("stage_carry_forward_attestation_hash_drift")
    authorization_path = _resolve(
        STAGE_COMPATIBILITY_AUTH_DIRECTORY
        / f"{attestation['authorization_id']}.json",
        root,
    )
    authorization = _load_stage_compatibility_authorization(
        root, authorization_path
    )
    producer_bundle, producer_revision = _aggregate_df_producer_identity(root)
    constants = {
        "kind": "v23_stage_carry_forward_attestation",
        "authorization_id": authorization["authorization_id"],
        "stage": stage,
        "execution_revision": EXECUTION_REVISION,
        "execution_erratum_sha256": EXECUTION_ERRATUM_SHA256,
        "from_runtime_bundle_sha256": producer_bundle,
        "from_protocol_revision_id": producer_revision,
        "to_runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "to_protocol_revision_id": active["protocol_revision_id"],
        "source_pool_contents_read": False,
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }
    if any(attestation[key] != expected for key, expected in constants.items()):
        raise RuntimeError("stage_carry_forward_attestation_identity_drift")
    from_identity = _stage_identity_for_bundle(
        root, stage=stage, runtime_bundle_sha256=producer_bundle
    )
    to_identity = _stage_identity_for_bundle(
        root, stage=stage, runtime_bundle_sha256=active["runtime_bundle_sha256"]
    )
    expected_identity = {
        "stage_dependency_fingerprint": from_identity[
            "stage_dependency_fingerprint"
        ],
        "from_stage_execution_identity": from_identity[
            "stage_execution_identity"
        ],
        "to_stage_execution_identity": to_identity["stage_execution_identity"],
    }
    if (
        from_identity["stage_dependency_fingerprint"]
        != to_identity["stage_dependency_fingerprint"]
        or any(
            attestation[key] != expected
            for key, expected in expected_identity.items()
        )
        or authorization["stage_dependency_fingerprint"]
        != from_identity["stage_dependency_fingerprint"]
    ):
        raise RuntimeError("stage_carry_forward_dependency_drift")
    datasets = attestation["datasets"]
    if (
        not isinstance(datasets, list)
        or [item.get("dataset") for item in datasets if isinstance(item, Mapping)]
        != list(DATASET_ORDER)
    ):
        raise RuntimeError("stage_carry_forward_dataset_group_incomplete")
    for evidence in datasets:
        if not isinstance(evidence, Mapping):
            raise RuntimeError("stage_compatibility_dataset_schema_drift")
        _assert_aggregate_evidence_files(root, evidence)
    ledger_path = _resolve(CONSUMPTION_LEDGER, root)
    validate_ledger(ledger_path)
    ledger_hashes = {
        json.loads(line)["row_sha256"]
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    }
    if attestation["ledger_tip_sha256"] not in ledger_hashes:
        raise RuntimeError("stage_carry_forward_ledger_tip_not_ancestor")
    anchor = _ledger_tip_anchor(root, attestation["ledger_tip_sha256"])
    if sha256_file(anchor) != attestation["ledger_tip_anchor_sha256"]:
        raise RuntimeError("stage_carry_forward_ledger_anchor_drift")
    return {
        "status": "passed",
        "stage": stage,
        "validation_mode": "carried_forward",
        "execution_revision": EXECUTION_REVISION,
        "execution_erratum_sha256": EXECUTION_ERRATUM_SHA256,
        "from_runtime_bundle_sha256": producer_bundle,
        "from_protocol_revision_id": producer_revision,
        "to_runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "to_protocol_revision_id": active["protocol_revision_id"],
        "stage_dependency_fingerprint": attestation[
            "stage_dependency_fingerprint"
        ],
        "datasets": datasets,
        "attestation_file_sha256": sha256_file(path),
        "attestation_id": claimed_attestation_id,
        "source_pool_contents_read": False,
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }


def _load_stage_run_authorization_file(
    *,
    root: Path,
    authorization_path: str | Path,
    stage: str,
    execution_unit: str,
    datasets: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _resolve(authorization_path, root)
    authorization = _read_json_exact(path)
    expected_path = _resolve(
        RUN_AUTH_DIRECTORY / f"{authorization.get('authorization_id')}.json", root
    )
    if path != expected_path:
        raise RuntimeError("run_authorization_path_drift")
    rows = _read_attempt_registry(_resolve(ATTEMPT_REGISTRY, root))
    matches = [
        row for row in rows if row["attempt_id"] == authorization.get("attempt_id")
    ]
    if len(matches) != 1:
        raise RuntimeError("run_authorization_attempt_registry_missing")
    validated = validate_run_authorization(
        authorization,
        stage=stage,
        execution_unit=execution_unit,
        attempt_registry_row=matches[0],
    )
    expected_datasets = sorted(datasets)
    if validated["datasets"] != expected_datasets:
        raise RuntimeError("run_authorization_dataset_group_drift")
    return validated, matches[0]


def _stage_authorization_paths(
    root: Path,
    *,
    stage: str,
    runtime_bundle_sha256: str,
    datasets: Sequence[str] | None = None,
) -> list[Path]:
    expected_datasets = sorted(datasets) if datasets is not None else None
    directory = _resolve(RUN_AUTH_DIRECTORY, root)
    matches: list[Path] = []
    for path in directory.glob("*.json") if directory.exists() else ():
        value = _read_json_exact(path)
        if (
            value.get("authorized_stage") == stage
            and value.get("runtime_bundle_sha256") == runtime_bundle_sha256
            and (expected_datasets is None or value.get("datasets") == expected_datasets)
        ):
            matches.append(path)
    return sorted(matches)


def _bound_source_order(
    root: Path, *, dataset: str, pool: Mapping[str, Any]
) -> tuple[str, ...]:
    verify_bound_file(
        _resolve(pool["source_order_path"], root),
        str(pool["source_order_file_sha256"]),
    )
    value = _read_json_exact(_resolve(pool["source_order_path"], root))
    if set(value) != {
        "protocol",
        "dataset",
        "selection_seed",
        "source_order",
        "source_order_sha256",
        "label_fields_read",
    }:
        raise RuntimeError("source_order_schema_drift")
    order = value["source_order"]
    if (
        value["dataset"] != dataset
        or not isinstance(order, list)
        or len(order) != pool["source_count"]
        or len(set(order)) != len(order)
        or not all(isinstance(item, str) and item for item in order)
    ):
        raise RuntimeError("source_order_identity_drift")
    return tuple(order)


def _reservation_counts(config: Mapping[str, Any]) -> tuple[int, int]:
    evidence = config.get("evidence_partition")
    development = config.get("development_gate")
    if not isinstance(evidence, Mapping) or not isinstance(development, Mapping):
        raise RuntimeError("reservation_count_config_missing")
    development_count = evidence.get("v22_pilot_source_count_per_dataset")
    reserve_count = evidence.get("fresh_audit_reserve_source_count_per_dataset")
    if (
        isinstance(development_count, bool)
        or not isinstance(development_count, int)
        or development_count < 1
        or development.get("source_count_per_dataset") != development_count
        or isinstance(reserve_count, bool)
        or not isinstance(reserve_count, int)
        or reserve_count < 1
    ):
        raise RuntimeError("reservation_count_config_drift")
    return development_count, reserve_count


def _reservation_directory(root: Path, protocol_revision: str) -> Path:
    return _resolve(REVISION_RESERVATION_DIRECTORY / protocol_revision, root)


def _reservation_checkpoint_path(
    root: Path, *, protocol_revision: str, attempt: str
) -> Path:
    return _resolve(
        ARTIFACT_ROOT
        / "checkpoints"
        / protocol_revision
        / RESERVATION_STAGE
        / f"{attempt}.json",
        root,
    )


def _reservation_batch_id(
    *,
    protocol_revision: str,
    attempt: str,
    role: str,
    dataset: str,
    identities: Sequence[Mapping[str, str]],
    expected_prior_tip: str,
) -> str:
    return canonical_sha256(
        {
            "kind": "v23_reservation_batch",
            "protocol_revision_id": protocol_revision,
            "attempt_id": attempt,
            "role": role,
            "dataset": dataset,
            "expected_batch_size": len(identities),
            "ordered_source_identity_sha256": canonical_sha256(
                [dict(item) for item in identities]
            ),
            "expected_prior_ledger_tip_sha256": expected_prior_tip,
        }
    )


def _write_or_validate_canonical(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        if _read_json_exact(path) != dict(value):
            raise RuntimeError(f"existing_artifact_identity_drift:{path}")
        return
    _write_new_atomic_canonical_json(path, value)


def _reservation_plan_path(
    root: Path, *, protocol_revision: str, role: str, dataset: str
) -> Path:
    return _reservation_directory(root, protocol_revision) / "plans" / role / f"{dataset}.json"


def _completed_reservation_batch(
    root: Path,
    *,
    batch_id: str,
    identities: Sequence[Mapping[str, str]],
) -> dict[str, Any] | None:
    ledger_path = _resolve(CONSUMPTION_LEDGER, root)
    rows = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    batch_rows = [row for row in rows if row.get("reservation_batch_id") == batch_id]
    if not batch_rows:
        return None
    if len(batch_rows) != len(identities):
        return None
    batch_rows.sort(key=lambda row: row["reservation_batch_index"])
    if any(
        row["reservation_batch_index"] != index
        or row["reservation_batch_size"] != len(identities)
        or any(row.get(key) != value for key, value in identity.items())
        for index, (row, identity) in enumerate(zip(batch_rows, identities, strict=True))
    ):
        raise RuntimeError("reservation_completed_batch_drift")
    for left, right in zip(batch_rows, batch_rows[1:]):
        if right["sequence"] != left["sequence"] + 1 or right[
            "previous_row_sha256"
        ] != left["row_sha256"]:
            raise RuntimeError("reservation_completed_batch_chain_drift")
    tip = batch_rows[-1]["row_sha256"]
    try:
        anchor = _ledger_tip_anchor(root, tip)
    except RuntimeError as error:
        if str(error) == "ledger_tip_anchor_count_invalid":
            return None
        raise
    return {
        "reservation_batch_id": batch_id,
        "ledger_tip_sha256": tip,
        "anchor_path": str(anchor),
        "anchor_sha256": sha256_file(anchor),
    }


def _validate_aggregate_group(
    root: Path,
    *,
    runtime_files: Sequence[str] | None,
    dependency_lock_path: str | Path,
    model_lock_path: str | Path,
) -> list[dict[str, Any]]:
    return [
        validate_aggregate_df(
            project_root=root,
            dataset=dataset,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        for dataset in DATASET_ORDER
    ]


def prepare_revision_reservation_authorization(
    *,
    project_root: str | Path,
    user_authorization_record: str,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    if not user_authorization_record.strip():
        raise ValueError("revision_reservation_user_authorization_empty")
    root = Path(project_root).resolve()
    lock = _resolve(
        ARTIFACT_ROOT / "governance/revision_reservation_preparation.lock", root
    )
    with exclusive_lock(lock):
        active = validate_active_runtime(
            root,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        _validate_aggregate_group(
            root,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        if _stage_authorization_paths(
            root,
            stage=RESERVATION_STAGE,
            runtime_bundle_sha256=active["runtime_bundle_sha256"],
        ) or _reservation_directory(root, active["protocol_revision_id"]).exists():
            raise RuntimeError("revision_reservation_attempt_or_artifact_already_exists")
        config = load_design_config(root)
        development_count, reserve_count = _reservation_counts(config)
        ledger_path = _resolve(CONSUMPTION_LEDGER, root)
        ledger = validate_ledger(ledger_path)
        rows = [
            json.loads(line)
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
        ]
        development_counts = {
            dataset: sum(
                row.get("role") == "development" and row.get("dataset") == dataset
                for row in rows[1:]
            )
            for dataset in DATASET_ORDER
        }
        if any(count not in {0, development_count} for count in development_counts.values()) or len(
            set(development_counts.values())
        ) != 1:
            raise RuntimeError("revision_reservation_development_prefix_incomplete")
        development_required = next(iter(development_counts.values())) == 0
        budget_limit = len(DATASET_ORDER) * (
            reserve_count + (development_count if development_required else 0)
        )
        registry = allocate_attempt(
            registry_path=_resolve(ATTEMPT_REGISTRY, root),
            protocol_revision=active["protocol_revision_id"],
            stage=RESERVATION_STAGE,
            execution_unit="all_datasets_group",
            expected_prior_ledger_tip_sha256=ledger["tip_sha256"],
        )
        authorization = {
            "kind": "v23_run_authorization",
            "user_authorization_record": user_authorization_record,
            "protocol_revision_id": active["protocol_revision_id"],
            "attempt_id": registry["attempt_id"],
            "authorized_stage": RESERVATION_STAGE,
            "execution_unit": "all_datasets_group",
            "expected_prior_ledger_tip_sha256": ledger["tip_sha256"],
            "datasets": sorted(DATASET_ORDER),
            "run_roles": ["development", "fresh_audit_reserve"],
            "model_or_retriever_cells": [],
            "budget_kind": "sources",
            "budget_limit": budget_limit,
            "issued_at": utc_now(),
            "expires_at_or_null": None,
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "runtime_bundle_sha256": active["runtime_bundle_sha256"],
        }
        authorization["authorization_id"] = canonical_sha256(authorization)
        path = _resolve(
            RUN_AUTH_DIRECTORY / f"{authorization['authorization_id']}.json", root
        )
        _write_new_canonical_json(path, authorization)
    return {
        **authorization,
        "authorization_path": _relative(path, root),
        "source_pool_contents_read": False,
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }


def _collect_registration_identities(
    *,
    root: Path,
    config: Mapping[str, Any],
    prior_rows: Sequence[Mapping[str, Any]],
    development_count: int,
    reserve_count: int,
) -> tuple[
    dict[str, list[dict[str, str]]],
    dict[str, list[dict[str, str]]],
    dict[str, list[dict[str, Any]]],
]:
    prior_keys = {
        dataset: {
            str(row["source_key"])
            for row in prior_rows
            if row.get("dataset") == dataset and row.get("role") != "genesis"
        }
        for dataset in DATASET_ORDER
    }
    excluded_hashes = {
        str(row["source_hash"])
        for row in prior_rows
        if row.get("role") != "genesis"
    }
    excluded_normalized = {
        str(row["normalized_text_hash"])
        for row in prior_rows
        if row.get("role") != "genesis"
    }
    existing_development = {
        dataset: [
            dict(row)
            for row in prior_rows
            if row.get("dataset") == dataset and row.get("role") == "development"
        ]
        for dataset in DATASET_ORDER
    }
    development: dict[str, list[dict[str, str]]] = {}
    reserves: dict[str, list[dict[str, str]]] = {}
    snapshots: dict[str, list[dict[str, Any]]] = {}
    for dataset in DATASET_ORDER:
        pool = _aggregate_df_contracts(config, dataset)["pool"]
        order = _bound_source_order(root, dataset=dataset, pool=pool)
        if development_count + reserve_count > len(order):
            raise RuntimeError("revision_reservation_source_pool_too_small")
        with FrozenSourcePoolReader(
            project_root=root,
            dataset=dataset,
            database_path=pool["database_path"],
            database_sha256=pool["database_sha256"],
            source_order_path=pool["source_order_path"],
            source_order_file_sha256=pool["source_order_file_sha256"],
            source_pool_manifest_path=pool["manifest_path"],
            source_pool_manifest_sha256=pool["manifest_sha256"],
            expected_source_count=pool["source_count"],
        ) as reader:
            calculated_development = [
                reader.registration_identity(source_key)
                for source_key in order[:development_count]
            ]
            prior_development = existing_development[dataset]
            if prior_development:
                prior_development.sort(key=lambda row: row["reservation_batch_index"])
                expected = [
                    {
                        "source_key": row["source_key"],
                        "source_hash": row["source_hash"],
                        "normalized_text_hash": row["normalized_text_hash"],
                    }
                    for row in prior_development
                ]
                if expected != calculated_development:
                    raise RuntimeError("revision_reservation_development_identity_drift")
                development[dataset] = []
            else:
                development[dataset] = calculated_development
            for identity in calculated_development:
                excluded_hashes.add(identity["source_hash"])
                excluded_normalized.add(identity["normalized_text_hash"])
            selected: list[dict[str, str]] = []
            snapshot: list[dict[str, Any]] = []
            for index in range(development_count, len(order)):
                source_key = order[index]
                if source_key in prior_keys[dataset]:
                    continue
                identity = reader.registration_identity(source_key)
                if (
                    identity["source_hash"] in excluded_hashes
                    or identity["normalized_text_hash"] in excluded_normalized
                ):
                    continue
                selected.append(identity)
                snapshot.append(
                    {"source_order_index": index, "source_key": source_key}
                )
                excluded_hashes.add(identity["source_hash"])
                excluded_normalized.add(identity["normalized_text_hash"])
                if len(selected) == reserve_count:
                    break
            if len(selected) != reserve_count:
                raise RuntimeError("revision_reservation_capacity_shortfall")
            reserves[dataset] = selected
            snapshots[dataset] = snapshot
    return development, reserves, snapshots


def _append_or_resume_reservation_plan(
    *,
    root: Path,
    authorization: Mapping[str, Any],
    registry: Mapping[str, Any],
    role: str,
    dataset: str,
    identities: Sequence[Mapping[str, str]],
    expected_prior_tip: str,
    budget_path: Path,
) -> dict[str, Any]:
    plan_path = _reservation_plan_path(
        root,
        protocol_revision=authorization["protocol_revision_id"],
        role=role,
        dataset=dataset,
    )
    plan = {
        "kind": "v23_reservation_plan",
        "protocol_revision_id": authorization["protocol_revision_id"],
        "attempt_id": authorization["attempt_id"],
        "role": role,
        "dataset": dataset,
        "expected_prior_ledger_tip_sha256": expected_prior_tip,
        "ordered_source_identity_objects": [dict(item) for item in identities],
    }
    _write_or_validate_canonical(plan_path, plan)
    batch_id = _reservation_batch_id(
        protocol_revision=authorization["protocol_revision_id"],
        attempt=authorization["attempt_id"],
        role=role,
        dataset=dataset,
        identities=identities,
        expected_prior_tip=expected_prior_tip,
    )
    completed = _completed_reservation_batch(
        root, batch_id=batch_id, identities=identities
    )
    if completed is not None:
        return completed
    return append_reservation_batch(
        ledger_path=_resolve(CONSUMPTION_LEDGER, root),
        anchor_directory=_resolve(LEDGER_ANCHOR_DIRECTORY, root),
        protocol_revision=authorization["protocol_revision_id"],
        attempt=authorization["attempt_id"],
        role=role,
        dataset=dataset,
        identities=identities,
        expected_prior_tip=expected_prior_tip,
        reason=(
            "v23_development_write_ahead_registration"
            if role == "development"
            else "v23_revision_fresh_audit_reserve_registration"
        ),
        authorization=authorization,
        attempt_registry_row=registry,
        budget_journal_path=budget_path,
    )


def _ledger_rows(root: Path) -> list[dict[str, Any]]:
    ledger_path = _resolve(CONSUMPTION_LEDGER, root)
    validate_ledger(ledger_path)
    return [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]


def _ledger_sequence_for_tip(
    rows: Sequence[Mapping[str, Any]], ledger_tip_sha256: str
) -> int:
    matches = [
        index
        for index, row in enumerate(rows)
        if row.get("row_sha256") == ledger_tip_sha256
    ]
    if len(matches) != 1:
        raise RuntimeError("revision_reservation_prior_tip_not_in_ledger")
    return matches[0]


def _validate_reservation_plan_batch(
    *,
    root: Path,
    plan: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    _assert_exact_fields(plan, RESERVATION_PLAN_FIELDS, kind="reservation_plan")
    identities = plan["ordered_source_identity_objects"]
    if (
        plan["kind"] != "v23_reservation_plan"
        or plan["protocol_revision_id"] != authorization["protocol_revision_id"]
        or plan["attempt_id"] != authorization["attempt_id"]
        or plan["role"] not in {"development", "fresh_audit_reserve"}
        or plan["dataset"] not in DATASET_ORDER
        or not _is_sha256(plan["expected_prior_ledger_tip_sha256"])
        or not isinstance(identities, list)
        or not identities
    ):
        raise RuntimeError("revision_reservation_plan_identity_drift")
    for identity in identities:
        if (
            not isinstance(identity, Mapping)
            or set(identity)
            != {"source_key", "source_hash", "normalized_text_hash"}
            or not isinstance(identity["source_key"], str)
            or not identity["source_key"]
            or not _is_sha256(identity["source_hash"])
            or not _is_sha256(identity["normalized_text_hash"])
        ):
            raise RuntimeError("revision_reservation_plan_source_identity_drift")
    batch_id = _reservation_batch_id(
        protocol_revision=str(plan["protocol_revision_id"]),
        attempt=str(plan["attempt_id"]),
        role=str(plan["role"]),
        dataset=str(plan["dataset"]),
        identities=identities,
        expected_prior_tip=str(plan["expected_prior_ledger_tip_sha256"]),
    )
    batch_rows = [
        row for row in rows if row.get("reservation_batch_id") == batch_id
    ]
    if len(batch_rows) != len(identities):
        raise RuntimeError("revision_reservation_batch_incomplete")
    batch_rows.sort(key=lambda row: row["reservation_batch_index"])
    prior_sequence = _ledger_sequence_for_tip(
        rows, str(plan["expected_prior_ledger_tip_sha256"])
    )
    for index, (row, identity) in enumerate(
        zip(batch_rows, identities, strict=True)
    ):
        expected = {
            "sequence": prior_sequence + index + 1,
            "protocol_revision_id": authorization["protocol_revision_id"],
            "attempt_id": authorization["attempt_id"],
            "reservation_batch_id": batch_id,
            "reservation_batch_index": index,
            "reservation_batch_size": len(identities),
            "role": plan["role"],
            "dataset": plan["dataset"],
            **dict(identity),
        }
        if any(row.get(key) != value for key, value in expected.items()):
            raise RuntimeError("revision_reservation_batch_identity_drift")
        expected_previous = (
            plan["expected_prior_ledger_tip_sha256"]
            if index == 0
            else batch_rows[index - 1]["row_sha256"]
        )
        if row["previous_row_sha256"] != expected_previous:
            raise RuntimeError("revision_reservation_batch_chain_drift")
    anchor_path = _ledger_tip_anchor(root, batch_rows[-1]["row_sha256"])
    anchor = _read_json_exact(anchor_path)
    if (
        anchor.get("kind") != "v23_ledger_tip_anchor"
        or anchor.get("reservation_batch_id") != batch_id
        or anchor.get("prior_ledger_tip_sha256")
        != plan["expected_prior_ledger_tip_sha256"]
        or anchor.get("first_sequence") != prior_sequence + 1
        or anchor.get("last_sequence") != prior_sequence + len(identities)
        or anchor.get("batch_size") != len(identities)
    ):
        raise RuntimeError("revision_reservation_batch_anchor_drift")
    return {
        "batch_id": batch_id,
        "role": plan["role"],
        "dataset": plan["dataset"],
        "identities": [dict(item) for item in identities],
        "prior_tip_sha256": plan["expected_prior_ledger_tip_sha256"],
        "tip_sha256": batch_rows[-1]["row_sha256"],
        "anchor_sha256": sha256_file(anchor_path),
    }


def run_revision_reservation(
    *,
    project_root: str | Path,
    authorization_path: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    lock = _resolve(ARTIFACT_ROOT / "governance/revision_reservation.lock", root)
    with exclusive_lock(lock):
        active = validate_active_runtime(
            root,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        authorization, registry = _load_stage_run_authorization_file(
            root=root,
            authorization_path=authorization_path,
            stage=RESERVATION_STAGE,
            execution_unit="all_datasets_group",
            datasets=DATASET_ORDER,
        )
        if (
            authorization["runtime_bundle_sha256"]
            != active["runtime_bundle_sha256"]
            or authorization["protocol_revision_id"]
            != active["protocol_revision_id"]
        ):
            raise RuntimeError("revision_reservation_active_runtime_drift")
        _validate_aggregate_group(
            root,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        directory = _reservation_directory(root, active["protocol_revision_id"])
        checkpoint_path = _reservation_checkpoint_path(
            root,
            protocol_revision=active["protocol_revision_id"],
            attempt=authorization["attempt_id"],
        )
        completion_path = directory / "group_completion.json"
        if checkpoint_path.exists():
            return validate_revision_reservation(
                project_root=root,
                runtime_files=runtime_files,
                dependency_lock_path=dependency_lock_path,
                model_lock_path=model_lock_path,
            )
        ledger_path = _resolve(CONSUMPTION_LEDGER, root)
        ledger = validate_ledger(ledger_path)
        all_rows = [
            json.loads(line)
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
        ]
        prior_sequence = _ledger_sequence_for_tip(
            all_rows, authorization["expected_prior_ledger_tip_sha256"]
        )
        prior_rows = all_rows[: prior_sequence + 1]
        input_anchor = _ledger_tip_anchor(
            root, authorization["expected_prior_ledger_tip_sha256"]
        )
        input_anchor_sha256 = sha256_file(input_anchor)
        config = load_design_config(root)
        development_count, reserve_count = _reservation_counts(config)
        development, reserves, snapshots = _collect_registration_identities(
            root=root,
            config=config,
            prior_rows=prior_rows,
            development_count=development_count,
            reserve_count=reserve_count,
        )
        reserve_snapshot_hashes: list[str] = []
        for dataset in DATASET_ORDER:
            pool = _aggregate_df_contracts(config, dataset)["pool"]
            snapshot = {
                "kind": "v23_fresh_audit_reserve_snapshot",
                "specification_version": SPECIFICATION_VERSION,
                "protocol_revision_id": active["protocol_revision_id"],
                "dataset": dataset,
                "prior_ledger_tip_sha256": authorization[
                    "expected_prior_ledger_tip_sha256"
                ],
                "source_order_file_sha256": pool["source_order_file_sha256"],
                "ordered_sources": snapshots[dataset],
            }
            path = directory / f"{dataset}_reserve_snapshot.json"
            _write_or_validate_canonical(path, snapshot)
            reserve_snapshot_hashes.append(sha256_file(path))
        prior_snapshot = {
            "kind": "v23_revision_reservation_prior_snapshot",
            "protocol_revision_id": active["protocol_revision_id"],
            "common_prior_ledger_tip_sha256": authorization[
                "expected_prior_ledger_tip_sha256"
            ],
            "common_prior_tip_anchor_sha256": input_anchor_sha256,
            "dataset_order": list(DATASET_ORDER),
            "ordered_reserve_snapshot_sha256": reserve_snapshot_hashes,
        }
        prior_snapshot_path = directory / "prior_snapshot.json"
        _write_or_validate_canonical(prior_snapshot_path, prior_snapshot)
        budget_path = _resolve(
            BUDGET_DIRECTORY / f"{authorization['authorization_id']}.jsonl", root
        )
        current_tip = authorization["expected_prior_ledger_tip_sha256"]
        for dataset in DATASET_ORDER:
            if development[dataset]:
                result = _append_or_resume_reservation_plan(
                    root=root,
                    authorization=authorization,
                    registry=registry,
                    role="development",
                    dataset=dataset,
                    identities=development[dataset],
                    expected_prior_tip=current_tip,
                    budget_path=budget_path,
                )
                current_tip = result["ledger_tip_sha256"]
        reserve_batch_ids: list[str] = []
        for dataset in DATASET_ORDER:
            result = _append_or_resume_reservation_plan(
                root=root,
                authorization=authorization,
                registry=registry,
                role="fresh_audit_reserve",
                dataset=dataset,
                identities=reserves[dataset],
                expected_prior_tip=current_tip,
                budget_path=budget_path,
            )
            current_tip = result["ledger_tip_sha256"]
            reserve_batch_ids.append(result["reservation_batch_id"])
        output_anchor = _ledger_tip_anchor(root, current_tip)
        completion_created_at = utc_now()
        if completion_path.exists():
            completion_created_at = str(
                _read_json_exact(completion_path).get("created_at")
            )
        completion = {
            "kind": "v23_revision_reservation_group_complete",
            "protocol_revision_id": active["protocol_revision_id"],
            "common_prior_snapshot_sha256": sha256_file(prior_snapshot_path),
            "ordered_reservation_batch_ids": reserve_batch_ids,
            "final_ledger_tip_sha256": current_tip,
            "final_tip_anchor_sha256": sha256_file(output_anchor),
            "created_at": completion_created_at,
        }
        _write_or_validate_canonical(completion_path, completion)
        charged_count, budget_tip, _ = _read_budget_state(
            budget_path, authorization
        )
        if charged_count != authorization["budget_limit"]:
            raise RuntimeError("revision_reservation_budget_count_incomplete")
        checkpoint = {
            "kind": "v23_stage_checkpoint",
            "protocol_revision_id": active["protocol_revision_id"],
            "attempt_id": authorization["attempt_id"],
            "stage": RESERVATION_STAGE,
            "execution_unit": "all_datasets_group",
            "status": "passed",
            "input_ledger_tip_sha256": authorization[
                "expected_prior_ledger_tip_sha256"
            ],
            "input_tip_anchor_sha256": input_anchor_sha256,
            "output_ledger_tip_sha256": current_tip,
            "output_tip_anchor_sha256": sha256_file(output_anchor),
            "ledger_mutation": True,
            "authorization_id": authorization["authorization_id"],
            "authorization_budget_journal_tip_sha256": budget_tip,
            "runtime_bundle_sha256": active["runtime_bundle_sha256"],
            "output_manifest_sha256": sha256_file(completion_path),
            "completed_at": utc_now(),
        }
        write_stage_checkpoint(checkpoint_path, checkpoint)
    return validate_revision_reservation(
        project_root=root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )


def validate_revision_reservation(
    *,
    project_root: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
    _target_protocol_revision_id: str | None = None,
    _target_runtime_bundle_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate the reservation transaction without reading source contents."""

    root = Path(project_root).resolve()
    current_active = validate_active_runtime(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    _validate_aggregate_group(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    if (_target_protocol_revision_id is None) != (
        _target_runtime_bundle_sha256 is None
    ):
        raise ValueError("revision_reservation_target_identity_incomplete")
    active = current_active
    if _target_protocol_revision_id is not None:
        lineage = _load_runtime_lineage(root)
        matches = [
            revision
            for revision in lineage["revisions"]
            if revision["protocol_revision_id"]
            == _target_protocol_revision_id
            and revision["runtime_bundle_sha256"]
            == _target_runtime_bundle_sha256
        ]
        if len(matches) != 1:
            raise RuntimeError("revision_reservation_target_identity_unknown")
        active = {
            "protocol_revision_id": _target_protocol_revision_id,
            "runtime_bundle_sha256": _target_runtime_bundle_sha256,
        }
    authorization_paths = _stage_authorization_paths(
        root,
        stage=RESERVATION_STAGE,
        runtime_bundle_sha256=active["runtime_bundle_sha256"],
        datasets=DATASET_ORDER,
    )
    if len(authorization_paths) != 1:
        raise RuntimeError("revision_reservation_authorization_count_invalid")
    authorization, _ = _load_stage_run_authorization_file(
        root=root,
        authorization_path=authorization_paths[0],
        stage=RESERVATION_STAGE,
        execution_unit="all_datasets_group",
        datasets=DATASET_ORDER,
    )
    if (
        authorization["protocol_revision_id"] != active["protocol_revision_id"]
        or authorization["run_roles"]
        != ["development", "fresh_audit_reserve"]
    ):
        raise RuntimeError("revision_reservation_authorization_identity_drift")
    rows = _ledger_rows(root)
    prior_sequence = _ledger_sequence_for_tip(
        rows, authorization["expected_prior_ledger_tip_sha256"]
    )
    directory = _reservation_directory(root, active["protocol_revision_id"])
    prior_snapshot_path = directory / "prior_snapshot.json"
    completion_path = directory / "group_completion.json"
    prior_snapshot = _read_json_exact(prior_snapshot_path)
    completion = _read_json_exact(completion_path)
    _assert_exact_fields(
        prior_snapshot,
        RESERVATION_PRIOR_SNAPSHOT_FIELDS,
        kind="reservation_prior_snapshot",
    )
    _assert_exact_fields(
        completion,
        RESERVATION_GROUP_COMPLETION_FIELDS,
        kind="reservation_group_completion",
    )
    prior_anchor = _ledger_tip_anchor(
        root, authorization["expected_prior_ledger_tip_sha256"]
    )
    if (
        prior_snapshot["kind"]
        != "v23_revision_reservation_prior_snapshot"
        or prior_snapshot["protocol_revision_id"]
        != active["protocol_revision_id"]
        or prior_snapshot["common_prior_ledger_tip_sha256"]
        != authorization["expected_prior_ledger_tip_sha256"]
        or prior_snapshot["common_prior_tip_anchor_sha256"]
        != sha256_file(prior_anchor)
        or prior_snapshot["dataset_order"] != list(DATASET_ORDER)
        or not isinstance(prior_snapshot["ordered_reserve_snapshot_sha256"], list)
        or len(prior_snapshot["ordered_reserve_snapshot_sha256"])
        != len(DATASET_ORDER)
    ):
        raise RuntimeError("revision_reservation_prior_snapshot_drift")
    config = load_design_config(root)
    development_count, reserve_count = _reservation_counts(config)
    snapshot_hashes: list[str] = []
    reserve_snapshot_by_dataset: dict[str, dict[str, Any]] = {}
    for dataset in DATASET_ORDER:
        path = directory / f"{dataset}_reserve_snapshot.json"
        snapshot = _read_json_exact(path)
        _assert_exact_fields(
            snapshot, RESERVE_SNAPSHOT_FIELDS, kind="reserve_snapshot"
        )
        pool = _aggregate_df_contracts(config, dataset)["pool"]
        order = _bound_source_order(root, dataset=dataset, pool=pool)
        ordered_sources = snapshot["ordered_sources"]
        if (
            snapshot["kind"] != "v23_fresh_audit_reserve_snapshot"
            or snapshot["specification_version"] != SPECIFICATION_VERSION
            or snapshot["protocol_revision_id"]
            != active["protocol_revision_id"]
            or snapshot["dataset"] != dataset
            or snapshot["prior_ledger_tip_sha256"]
            != authorization["expected_prior_ledger_tip_sha256"]
            or snapshot["source_order_file_sha256"]
            != pool["source_order_file_sha256"]
            or not isinstance(ordered_sources, list)
            or len(ordered_sources) != reserve_count
        ):
            raise RuntimeError("revision_reservation_snapshot_identity_drift")
        previous_index = development_count - 1
        for item in ordered_sources:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"source_order_index", "source_key"}
                or isinstance(item["source_order_index"], bool)
                or not isinstance(item["source_order_index"], int)
                or item["source_order_index"] <= previous_index
                or item["source_order_index"] >= len(order)
                or order[item["source_order_index"]] != item["source_key"]
            ):
                raise RuntimeError("revision_reservation_snapshot_order_drift")
            previous_index = item["source_order_index"]
        snapshot_hashes.append(sha256_file(path))
        reserve_snapshot_by_dataset[dataset] = snapshot
    if prior_snapshot["ordered_reserve_snapshot_sha256"] != snapshot_hashes:
        raise RuntimeError("revision_reservation_snapshot_hash_drift")

    plan_results: list[dict[str, Any]] = []
    for role in ("development", "fresh_audit_reserve"):
        for dataset in DATASET_ORDER:
            path = _reservation_plan_path(
                root,
                protocol_revision=active["protocol_revision_id"],
                role=role,
                dataset=dataset,
            )
            if role == "development" and not path.is_file():
                continue
            if not path.is_file():
                raise RuntimeError("revision_reservation_plan_missing")
            plan_results.append(
                _validate_reservation_plan_batch(
                    root=root,
                    plan=_read_json_exact(path),
                    rows=rows,
                    authorization=authorization,
                )
            )
    current_rows = [
        row
        for row in rows[prior_sequence + 1 :]
        if row.get("attempt_id") == authorization["attempt_id"]
    ]
    if len(current_rows) != authorization["budget_limit"]:
        raise RuntimeError("revision_reservation_current_row_count_drift")
    if sum(len(item["identities"]) for item in plan_results) != len(current_rows):
        raise RuntimeError("revision_reservation_plan_row_count_drift")
    expected_order = [
        (role, dataset)
        for role in ("development", "fresh_audit_reserve")
        for dataset in DATASET_ORDER
        if any(
            item["role"] == role and item["dataset"] == dataset
            for item in plan_results
        )
    ]
    actual_order: list[tuple[str, str]] = []
    for row in current_rows:
        key = (str(row["role"]), str(row["dataset"]))
        if not actual_order or key != actual_order[-1]:
            actual_order.append(key)
    if actual_order != expected_order:
        raise RuntimeError("revision_reservation_batch_order_drift")

    development_rows = [
        row for row in rows if row.get("role") == "development"
    ]
    prior_consumed = rows[1 : prior_sequence + 1]
    all_excluded_hashes = {
        row["source_hash"] for row in [*prior_consumed, *development_rows]
    }
    all_excluded_normalized = {
        row["normalized_text_hash"]
        for row in [*prior_consumed, *development_rows]
    }
    reserve_results = [
        item for item in plan_results if item["role"] == "fresh_audit_reserve"
    ]
    if [item["dataset"] for item in reserve_results] != list(DATASET_ORDER):
        raise RuntimeError("revision_reservation_reserve_group_incomplete")
    seen_reserve_hashes: set[str] = set()
    seen_reserve_normalized: set[str] = set()
    for result in reserve_results:
        snapshot_keys = [
            item["source_key"]
            for item in reserve_snapshot_by_dataset[result["dataset"]][
                "ordered_sources"
            ]
        ]
        if (
            len(result["identities"]) != reserve_count
            or [item["source_key"] for item in result["identities"]]
            != snapshot_keys
        ):
            raise RuntimeError("revision_reservation_snapshot_plan_drift")
        for identity in result["identities"]:
            if (
                identity["source_hash"] in all_excluded_hashes
                or identity["normalized_text_hash"] in all_excluded_normalized
                or identity["source_hash"] in seen_reserve_hashes
                or identity["normalized_text_hash"] in seen_reserve_normalized
            ):
                raise RuntimeError("revision_reservation_source_overlap")
            seen_reserve_hashes.add(identity["source_hash"])
            seen_reserve_normalized.add(identity["normalized_text_hash"])
    development_by_dataset = {
        dataset: [
            row
            for row in development_rows
            if row["dataset"] == dataset
        ]
        for dataset in DATASET_ORDER
    }
    for dataset, dataset_rows in development_by_dataset.items():
        dataset_rows.sort(key=lambda row: row["reservation_batch_index"])
        order = _bound_source_order(
            root,
            dataset=dataset,
            pool=_aggregate_df_contracts(config, dataset)["pool"],
        )
        if (
            len(dataset_rows) != development_count
            or [row["source_key"] for row in dataset_rows]
            != list(order[:development_count])
        ):
            raise RuntimeError("revision_reservation_development_identity_drift")

    budget_path = _resolve(
        BUDGET_DIRECTORY / f"{authorization['authorization_id']}.jsonl", root
    )
    charged_count, budget_tip, charged_operations = _read_budget_state(
        budget_path, authorization
    )
    expected_operations = {
        canonical_sha256(
            {
                "kind": "v23_source_reservation",
                "reservation_batch_id": row["reservation_batch_id"],
                "reservation_batch_index": row["reservation_batch_index"],
                "source_key": row["source_key"],
            }
        )
        for row in current_rows
    }
    if (
        charged_count != authorization["budget_limit"]
        or charged_operations != expected_operations
    ):
        raise RuntimeError("revision_reservation_budget_drift")
    final_tip = reserve_results[-1]["tip_sha256"]
    final_anchor = _ledger_tip_anchor(root, final_tip)
    if (
        completion["kind"] != "v23_revision_reservation_group_complete"
        or completion["protocol_revision_id"] != active["protocol_revision_id"]
        or completion["common_prior_snapshot_sha256"]
        != sha256_file(prior_snapshot_path)
        or completion["ordered_reservation_batch_ids"]
        != [item["batch_id"] for item in reserve_results]
        or completion["final_ledger_tip_sha256"] != final_tip
        or completion["final_tip_anchor_sha256"] != sha256_file(final_anchor)
    ):
        raise RuntimeError("revision_reservation_group_completion_drift")
    checkpoint_path = _reservation_checkpoint_path(
        root,
        protocol_revision=active["protocol_revision_id"],
        attempt=authorization["attempt_id"],
    )
    checkpoint = require_passed_checkpoint(
        checkpoint_path, stage=RESERVATION_STAGE
    )
    if (
        checkpoint["protocol_revision_id"] != active["protocol_revision_id"]
        or checkpoint["attempt_id"] != authorization["attempt_id"]
        or checkpoint["execution_unit"] != "all_datasets_group"
        or checkpoint["input_ledger_tip_sha256"]
        != authorization["expected_prior_ledger_tip_sha256"]
        or checkpoint["input_tip_anchor_sha256"] != sha256_file(prior_anchor)
        or checkpoint["output_ledger_tip_sha256"] != final_tip
        or checkpoint["output_tip_anchor_sha256"] != sha256_file(final_anchor)
        or checkpoint["ledger_mutation"] is not True
        or checkpoint["authorization_id"] != authorization["authorization_id"]
        or checkpoint["authorization_budget_journal_tip_sha256"] != budget_tip
        or checkpoint["runtime_bundle_sha256"]
        != active["runtime_bundle_sha256"]
        or checkpoint["output_manifest_sha256"] != sha256_file(completion_path)
    ):
        raise RuntimeError("revision_reservation_checkpoint_drift")
    return {
        "status": "passed",
        "runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "protocol_revision_id": active["protocol_revision_id"],
        "authorization_id": authorization["authorization_id"],
        "attempt_id": authorization["attempt_id"],
        "development_source_count_by_dataset": {
            dataset: len(rows) for dataset, rows in development_by_dataset.items()
        },
        "reserve_source_count_by_dataset": {
            item["dataset"]: len(item["identities"])
            for item in reserve_results
        },
        "common_prior_ledger_tip_sha256": authorization[
            "expected_prior_ledger_tip_sha256"
        ],
        "final_ledger_tip_sha256": final_tip,
        "group_completion_file_sha256": sha256_file(completion_path),
        "checkpoint_file_sha256": sha256_file(checkpoint_path),
        "budget_charge_count": charged_count,
        "source_pool_contents_read": False,
        "ledger_mutation_validated": True,
        "external_calls_performed": 0,
    }


def _log_combination(n: int, k: int) -> float:
    if k < 0 or k > n:
        return -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def hypergeometric_survival(
    *, population: int, eligible: int, sample: int, observed_at_least: int
) -> float:
    """Return P(X >= observed_at_least) for sampling without replacement."""

    if not 0 <= eligible <= population or not 0 <= sample <= population:
        raise ValueError("hypergeometric_parameters_invalid")
    lower = max(observed_at_least, 0, sample - (population - eligible))
    upper = min(sample, eligible)
    if lower > upper:
        return 0.0
    denominator = _log_combination(population, sample)
    logs = [
        _log_combination(eligible, value)
        + _log_combination(population - eligible, sample - value)
        - denominator
        for value in range(lower, upper + 1)
    ]
    maximum = max(logs)
    return math.exp(maximum) * math.fsum(math.exp(value - maximum) for value in logs)


def hypergeometric_eligible_lower_bound(
    *, population: int, sample: int, observed: int, alpha: float = 0.05
) -> int:
    """Find the smallest K whose hypergeometric survival at x reaches alpha."""

    if not 0.0 < alpha < 1.0 or not 0 <= observed <= sample <= population:
        raise ValueError("hypergeometric_boundary_input_invalid")
    low = observed
    high = population - sample + observed
    while low < high:
        middle = (low + high) // 2
        probability = hypergeometric_survival(
            population=population,
            eligible=middle,
            sample=sample,
            observed_at_least=observed,
        )
        if probability >= alpha:
            high = middle
        else:
            low = middle + 1
    return low


def capacity_decision(
    *,
    population: int,
    sample: int,
    observed_eligible: int,
    consumed_non_development: int,
    required_formal: int = 2_250,
) -> dict[str, Any]:
    if consumed_non_development < 0:
        raise ValueError("consumed_non_development_invalid")
    lower = hypergeometric_eligible_lower_bound(
        population=population,
        sample=sample,
        observed=observed_eligible,
    )
    formal_lower = max(0, lower - observed_eligible - consumed_non_development)
    return {
        "population_N": population,
        "sample_n": sample,
        "observed_x": observed_eligible,
        "total_eligible_lower_K_L": lower,
        "consumed_non_development_c": consumed_non_development,
        "formal_eligible_lower": formal_lower,
        "required_formal": required_formal,
        "status": "passed" if formal_lower >= required_formal else "failed_capacity_shortfall",
    }


def _development_pilot_paths(
    root: Path, *, dataset: str, attempt: str
) -> dict[str, Path]:
    directory = _resolve(DEVELOPMENT_SELECTION_DIRECTORY / dataset, root)
    return {
        "directory": directory,
        "source_results": directory / "attempts" / attempt / "source_results",
        "selected_pairs": directory / "selected_pairs.jsonl",
        "manifest": directory / "pilot_manifest.json",
        "checkpoint": _resolve(
            ARTIFACT_ROOT
            / "checkpoints"
            / DEVELOPMENT_PILOT_STAGE
            / dataset
            / f"{attempt}.json",
            root,
        ),
    }


def _development_gate_manifest_path(root: Path, protocol_revision: str) -> Path:
    return _resolve(
        DEVELOPMENT_GATE_DIRECTORY / protocol_revision / "group_manifest.json",
        root,
    )


def _development_batch_evidence(
    root: Path, *, dataset: str, expected_count: int
) -> dict[str, Any]:
    rows = _ledger_rows(root)
    batch_rows = [
        row
        for row in rows
        if row.get("role") == "development" and row.get("dataset") == dataset
    ]
    if len(batch_rows) != expected_count:
        raise RuntimeError("development_batch_count_drift")
    batch_ids = {row["reservation_batch_id"] for row in batch_rows}
    if len(batch_ids) != 1:
        raise RuntimeError("development_batch_identity_mixed")
    batch_rows.sort(key=lambda row: row["reservation_batch_index"])
    if any(
        row["reservation_batch_index"] != index
        or row["reservation_batch_size"] != expected_count
        for index, row in enumerate(batch_rows)
    ):
        raise RuntimeError("development_batch_order_drift")
    anchor_path = _ledger_tip_anchor(root, batch_rows[-1]["row_sha256"])
    anchor = _read_json_exact(anchor_path)
    if (
        anchor.get("kind") != "v23_ledger_tip_anchor"
        or anchor.get("reservation_batch_id") != next(iter(batch_ids))
        or anchor.get("batch_size") != expected_count
    ):
        raise RuntimeError("development_batch_anchor_drift")
    return {
        "rows": batch_rows,
        "anchor_path": anchor_path,
        "anchor_sha256": sha256_file(anchor_path),
        "reservation_batch_id": next(iter(batch_ids)),
    }


def _latest_prior_reservation_for_development(
    root: Path,
    *,
    active: Mapping[str, Any],
    runtime_files: Sequence[str] | None,
    dependency_lock_path: str | Path,
    model_lock_path: str | Path,
) -> dict[str, Any]:
    load_development_recovery_contract(root)
    if _stage_authorization_paths(
        root,
        stage=RESERVATION_STAGE,
        runtime_bundle_sha256=str(active["runtime_bundle_sha256"]),
        datasets=DATASET_ORDER,
    ) or _reservation_directory(
        root, str(active["protocol_revision_id"])
    ).exists():
        raise RuntimeError("development_recovery_active_reservation_started")
    lineage = _load_runtime_lineage(root)
    candidates: list[dict[str, Any]] = []
    for revision in lineage["revisions"]:
        if revision["protocol_revision_id"] == active["protocol_revision_id"]:
            continue
        authorization_paths = _stage_authorization_paths(
            root,
            stage=RESERVATION_STAGE,
            runtime_bundle_sha256=revision["runtime_bundle_sha256"],
            datasets=DATASET_ORDER,
        )
        completion_path = (
            _reservation_directory(root, revision["protocol_revision_id"])
            / "group_completion.json"
        )
        if len(authorization_paths) == 1 and completion_path.is_file():
            candidates.append(revision)
    if not candidates:
        raise RuntimeError("development_recovery_prior_reservation_missing")
    prior_revision = max(
        candidates, key=lambda item: int(item["revision_ordinal"])
    )
    validated = validate_revision_reservation(
        project_root=root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
        _target_protocol_revision_id=prior_revision["protocol_revision_id"],
        _target_runtime_bundle_sha256=prior_revision[
            "runtime_bundle_sha256"
        ],
    )
    ledger = validate_ledger(_resolve(CONSUMPTION_LEDGER, root))
    if ledger["tip_sha256"] != validated["final_ledger_tip_sha256"]:
        raise RuntimeError("development_recovery_ledger_advanced")
    completion_path = (
        _reservation_directory(root, prior_revision["protocol_revision_id"])
        / "group_completion.json"
    )
    checkpoint_path = _reservation_checkpoint_path(
        root,
        protocol_revision=prior_revision["protocol_revision_id"],
        attempt=validated["attempt_id"],
    )
    return {
        **validated,
        "validation_mode": "prior_revision_development_recovery",
        "group_completion_path": completion_path,
        "checkpoint_path": checkpoint_path,
    }


def _development_reservation_prerequisite(
    root: Path,
    *,
    active: Mapping[str, Any],
    runtime_files: Sequence[str] | None,
    dependency_lock_path: str | Path,
    model_lock_path: str | Path,
) -> dict[str, Any]:
    try:
        validated = validate_revision_reservation(
            project_root=root,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
    except RuntimeError as exc:
        if str(exc) != "revision_reservation_authorization_count_invalid":
            raise
        return _latest_prior_reservation_for_development(
            root,
            active=active,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
    return {
        **validated,
        "validation_mode": "native",
        "group_completion_path": (
            _reservation_directory(root, active["protocol_revision_id"])
            / "group_completion.json"
        ),
        "checkpoint_path": _reservation_checkpoint_path(
            root,
            protocol_revision=active["protocol_revision_id"],
            attempt=validated["attempt_id"],
        ),
    }


def _legacy_development_partial_evidence(
    root: Path, *, dataset: str, active: Mapping[str, Any]
) -> dict[str, Any] | None:
    directory = _resolve(DEVELOPMENT_SELECTION_DIRECTORY / dataset, root)
    if not directory.exists():
        return None
    selected_pairs = directory / "selected_pairs.jsonl"
    manifest = directory / "pilot_manifest.json"
    if selected_pairs.exists() or manifest.exists():
        raise RuntimeError("development_recovery_canonical_output_present")
    entries = sorted(path.name for path in directory.iterdir())
    if entries != ["source_results"]:
        raise RuntimeError("development_recovery_legacy_entries_invalid")
    source_results = directory / "source_results"
    if not source_results.is_dir() or any(source_results.iterdir()):
        raise RuntimeError("development_recovery_source_results_present")
    checkpoint_directory = _resolve(
        ARTIFACT_ROOT / "checkpoints" / DEVELOPMENT_PILOT_STAGE / dataset,
        root,
    )
    if _directory_has_entries(checkpoint_directory):
        raise RuntimeError("development_recovery_prior_checkpoint_present")
    prior_paths: list[Path] = []
    authorization_directory = _resolve(RUN_AUTH_DIRECTORY, root)
    for path in (
        authorization_directory.glob("*.json")
        if authorization_directory.exists()
        else ()
    ):
        value = _read_json_exact(path)
        if (
            value.get("authorized_stage") == DEVELOPMENT_PILOT_STAGE
            and value.get("datasets") == [dataset]
            and value.get("runtime_bundle_sha256")
            != active["runtime_bundle_sha256"]
        ):
            prior_paths.append(path)
    if len(prior_paths) != 1:
        raise RuntimeError("development_recovery_prior_authorization_ambiguous")
    prior, _ = _load_stage_run_authorization_file(
        root=root,
        authorization_path=prior_paths[0],
        stage=DEVELOPMENT_PILOT_STAGE,
        execution_unit="one_dataset",
        datasets=[dataset],
    )
    if prior["protocol_revision_id"] == active["protocol_revision_id"]:
        raise RuntimeError("development_recovery_prior_revision_not_distinct")
    budget_path = _resolve(
        BUDGET_DIRECTORY / f"{prior['authorization_id']}.jsonl", root
    )
    charged_count, _, _ = _read_budget_state(budget_path, prior)
    if (
        not budget_path.is_file()
        or charged_count < 1
        or charged_count >= prior["budget_limit"]
    ):
        raise RuntimeError("development_recovery_prior_budget_invalid")
    checkpoint = _development_pilot_paths(
        root, dataset=dataset, attempt=prior["attempt_id"]
    )["checkpoint"]
    if checkpoint.exists():
        raise RuntimeError("development_recovery_prior_checkpoint_present")
    return {
        "authorization_id": prior["authorization_id"],
        "protocol_revision_id": prior["protocol_revision_id"],
        "runtime_bundle_sha256": prior["runtime_bundle_sha256"],
        "attempt_id": prior["attempt_id"],
        "authorization_file_sha256": sha256_file(prior_paths[0]),
        "budget_journal_file_sha256": sha256_file(budget_path),
        "budget_charge_count": charged_count,
        "source_result_directory": _relative(source_results, root),
        "source_result_count": 0,
        "checkpoint_present": False,
        "canonical_selected_pairs_present": False,
        "canonical_pilot_manifest_present": False,
    }


def _write_development_recovery_attestation(
    root: Path,
    *,
    active: Mapping[str, Any],
    dataset: str,
    authorization: Mapping[str, Any],
    reservation: Mapping[str, Any],
    prior_partial: Mapping[str, Any] | None,
) -> Path | None:
    if reservation["validation_mode"] == "native" and prior_partial is None:
        return None
    attestation = {
        "kind": "v23_development_pilot_recovery_attestation",
        "recovery_revision": DEVELOPMENT_RECOVERY_REVISION,
        "recovery_contract_sha256": DEVELOPMENT_RECOVERY_CONTRACT_SHA256,
        "dataset": dataset,
        "new_authorization_id": authorization["authorization_id"],
        "new_protocol_revision_id": active["protocol_revision_id"],
        "new_runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "new_attempt_id": authorization["attempt_id"],
        "reservation_validation_mode": reservation["validation_mode"],
        "prior_reservation_protocol_revision_id": reservation[
            "protocol_revision_id"
        ],
        "prior_reservation_runtime_bundle_sha256": reservation[
            "runtime_bundle_sha256"
        ],
        "prior_reservation_authorization_id": reservation["authorization_id"],
        "prior_reservation_attempt_id": reservation["attempt_id"],
        "prior_reservation_group_completion_path": _relative(
            Path(reservation["group_completion_path"]), root
        ),
        "prior_reservation_group_completion_file_sha256": reservation[
            "group_completion_file_sha256"
        ],
        "prior_reservation_checkpoint_file_sha256": reservation[
            "checkpoint_file_sha256"
        ],
        "prior_reservation_final_ledger_tip_sha256": reservation[
            "final_ledger_tip_sha256"
        ],
        "prior_partial_attempt_or_null": (
            dict(prior_partial) if prior_partial is not None else None
        ),
        "created_at": utc_now(),
        "external_calls_performed": 0,
    }
    attestation["recovery_id"] = canonical_sha256(attestation)
    path = _resolve(
        DEVELOPMENT_RECOVERY_DIRECTORY
        / f"{authorization['authorization_id']}.json",
        root,
    )
    _write_new_canonical_json(path, attestation)
    return path


def _validate_development_recovery_attestation(
    root: Path,
    *,
    dataset: str,
    authorization: Mapping[str, Any],
    reservation: Mapping[str, Any],
) -> dict[str, Any] | None:
    load_development_recovery_contract(root)
    path = _resolve(
        DEVELOPMENT_RECOVERY_DIRECTORY
        / f"{authorization['authorization_id']}.json",
        root,
    )
    legacy_results = _resolve(
        DEVELOPMENT_SELECTION_DIRECTORY / dataset / "source_results", root
    )
    required = (
        reservation["validation_mode"] != "native" or legacy_results.exists()
    )
    if not path.is_file():
        if required:
            raise RuntimeError("development_recovery_attestation_missing")
        return None
    attestation = _read_json_exact(path)
    _assert_exact_fields(
        attestation,
        DEVELOPMENT_RECOVERY_ATTESTATION_FIELDS,
        kind="development_recovery_attestation",
    )
    claimed = attestation["recovery_id"]
    if (
        canonical_sha256(
            {
                key: value
                for key, value in attestation.items()
                if key != "recovery_id"
            }
        )
        != claimed
        or attestation["kind"]
        != "v23_development_pilot_recovery_attestation"
        or attestation["recovery_revision"] != DEVELOPMENT_RECOVERY_REVISION
        or attestation["recovery_contract_sha256"]
        != DEVELOPMENT_RECOVERY_CONTRACT_SHA256
        or attestation["dataset"] != dataset
        or attestation["new_authorization_id"]
        != authorization["authorization_id"]
        or attestation["new_protocol_revision_id"]
        != authorization["protocol_revision_id"]
        or attestation["new_runtime_bundle_sha256"]
        != authorization["runtime_bundle_sha256"]
        or attestation["new_attempt_id"] != authorization["attempt_id"]
        or attestation["reservation_validation_mode"]
        != reservation["validation_mode"]
        or attestation["prior_reservation_protocol_revision_id"]
        != reservation["protocol_revision_id"]
        or attestation["prior_reservation_runtime_bundle_sha256"]
        != reservation["runtime_bundle_sha256"]
        or attestation["prior_reservation_authorization_id"]
        != reservation["authorization_id"]
        or attestation["prior_reservation_attempt_id"]
        != reservation["attempt_id"]
        or attestation["prior_reservation_group_completion_file_sha256"]
        != reservation["group_completion_file_sha256"]
        or attestation["prior_reservation_checkpoint_file_sha256"]
        != reservation["checkpoint_file_sha256"]
        or attestation["prior_reservation_final_ledger_tip_sha256"]
        != reservation["final_ledger_tip_sha256"]
        or attestation["external_calls_performed"] != 0
    ):
        raise RuntimeError("development_recovery_attestation_drift")
    completion_path = _resolve(
        attestation["prior_reservation_group_completion_path"], root
    )
    if (
        completion_path != Path(reservation["group_completion_path"])
        or sha256_file(completion_path)
        != attestation["prior_reservation_group_completion_file_sha256"]
        or validate_ledger(_resolve(CONSUMPTION_LEDGER, root))["tip_sha256"]
        != attestation["prior_reservation_final_ledger_tip_sha256"]
    ):
        raise RuntimeError("development_recovery_reservation_evidence_drift")
    partial = attestation["prior_partial_attempt_or_null"]
    if partial is not None:
        if not isinstance(partial, Mapping):
            raise RuntimeError("development_recovery_partial_schema_drift")
        _assert_exact_fields(
            partial,
            DEVELOPMENT_RECOVERY_PARTIAL_FIELDS,
            kind="development_recovery_partial",
        )
        prior_path = _resolve(
            RUN_AUTH_DIRECTORY / f"{partial['authorization_id']}.json", root
        )
        prior, _ = _load_stage_run_authorization_file(
            root=root,
            authorization_path=prior_path,
            stage=DEVELOPMENT_PILOT_STAGE,
            execution_unit="one_dataset",
            datasets=[dataset],
        )
        budget_path = _resolve(
            BUDGET_DIRECTORY / f"{partial['authorization_id']}.jsonl", root
        )
        charged_count, _, _ = _read_budget_state(budget_path, prior)
        source_results = _resolve(partial["source_result_directory"], root)
        checkpoint = _development_pilot_paths(
            root, dataset=dataset, attempt=partial["attempt_id"]
        )["checkpoint"]
        if (
            set(partial) != DEVELOPMENT_RECOVERY_PARTIAL_FIELDS
            or prior["protocol_revision_id"] != partial["protocol_revision_id"]
            or prior["runtime_bundle_sha256"]
            != partial["runtime_bundle_sha256"]
            or prior["attempt_id"] != partial["attempt_id"]
            or sha256_file(prior_path) != partial["authorization_file_sha256"]
            or sha256_file(budget_path)
            != partial["budget_journal_file_sha256"]
            or charged_count != partial["budget_charge_count"]
            or not source_results.is_dir()
            or any(source_results.iterdir())
            or partial["source_result_count"] != 0
            or checkpoint.exists()
            or partial["checkpoint_present"] is not False
            or partial["canonical_selected_pairs_present"] is not False
            or partial["canonical_pilot_manifest_present"] is not False
        ):
            raise RuntimeError("development_recovery_partial_evidence_drift")
    return attestation


def prepare_development_pilot_authorization(
    *,
    project_root: str | Path,
    dataset: str,
    user_authorization_record: str,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    if dataset not in DATASET_ORDER or not user_authorization_record.strip():
        raise ValueError("development_pilot_authorization_scope_invalid")
    root = Path(project_root).resolve()
    lock = _resolve(
        ARTIFACT_ROOT / "governance/development_pilot_preparation.lock", root
    )
    with exclusive_lock(lock):
        active = validate_active_runtime(
            root,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        reservation = _development_reservation_prerequisite(
            root,
            active=active,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        validate_aggregate_df(
            project_root=root,
            dataset=dataset,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        for prior_dataset in DATASET_ORDER[: DATASET_ORDER.index(dataset)]:
            prior = validate_development_pilot(
                project_root=root,
                dataset=prior_dataset,
                runtime_files=runtime_files,
                dependency_lock_path=dependency_lock_path,
                model_lock_path=model_lock_path,
            )
            if prior["status"] != "passed":
                raise RuntimeError("development_pilot_prior_dataset_not_passed")
        config = load_design_config(root)
        development_count, _ = _reservation_counts(config)
        _development_batch_evidence(
            root, dataset=dataset, expected_count=development_count
        )
        existing = _stage_authorization_paths(
            root,
            stage=DEVELOPMENT_PILOT_STAGE,
            runtime_bundle_sha256=active["runtime_bundle_sha256"],
            datasets=[dataset],
        )
        directory = _resolve(DEVELOPMENT_SELECTION_DIRECTORY / dataset, root)
        checkpoint_directory = _resolve(
            ARTIFACT_ROOT / "checkpoints" / DEVELOPMENT_PILOT_STAGE / dataset,
            root,
        )
        prior_partial = _legacy_development_partial_evidence(
            root, dataset=dataset, active=active
        )
        if (
            existing
            or (directory.exists() and prior_partial is None)
            or _directory_has_entries(checkpoint_directory)
        ):
            raise RuntimeError("development_pilot_attempt_or_artifact_already_exists")
        ledger = validate_ledger(_resolve(CONSUMPTION_LEDGER, root))
        registry = allocate_attempt(
            registry_path=_resolve(ATTEMPT_REGISTRY, root),
            protocol_revision=active["protocol_revision_id"],
            stage=DEVELOPMENT_PILOT_STAGE,
            execution_unit="one_dataset",
            expected_prior_ledger_tip_sha256=ledger["tip_sha256"],
        )
        authorization = {
            "kind": "v23_run_authorization",
            "user_authorization_record": user_authorization_record,
            "protocol_revision_id": active["protocol_revision_id"],
            "attempt_id": registry["attempt_id"],
            "authorized_stage": DEVELOPMENT_PILOT_STAGE,
            "execution_unit": "one_dataset",
            "expected_prior_ledger_tip_sha256": ledger["tip_sha256"],
            "datasets": [dataset],
            "run_roles": ["development"],
            "model_or_retriever_cells": [],
            "budget_kind": "sources",
            "budget_limit": development_count,
            "issued_at": utc_now(),
            "expires_at_or_null": None,
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "runtime_bundle_sha256": active["runtime_bundle_sha256"],
        }
        authorization["authorization_id"] = canonical_sha256(authorization)
        path = _resolve(
            RUN_AUTH_DIRECTORY / f"{authorization['authorization_id']}.json", root
        )
        _write_new_canonical_json(path, authorization)
        recovery_attestation_path = _write_development_recovery_attestation(
            root,
            active=active,
            dataset=dataset,
            authorization=authorization,
            reservation=reservation,
            prior_partial=prior_partial,
        )
    return {
        **authorization,
        "authorization_path": _relative(path, root),
        "reservation_validation_mode": reservation["validation_mode"],
        "recovery_attestation_path": (
            _relative(recovery_attestation_path, root)
            if recovery_attestation_path is not None
            else None
        ),
        "source_pool_contents_read": False,
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }


def _load_validated_token_df(
    root: Path, *, dataset: str, source_count: int
) -> dict[str, int]:
    path = _resolve(AGGREGATE_DF_DIRECTORY / dataset / "token_df.jsonl", root)
    token_df: dict[str, int] = {}
    previous: str | None = None
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise RuntimeError("development_pilot_token_df_partial")
    for line in raw.decode("utf-8").splitlines():
        row = json.loads(line)
        if set(row) != {"kind", "token", "document_frequency"}:
            raise RuntimeError("development_pilot_token_df_schema_drift")
        token = row["token"]
        frequency = row["document_frequency"]
        if (
            row["kind"] != "v23_token_document_frequency"
            or not isinstance(token, str)
            or not token
            or previous is not None
            and token <= previous
            or isinstance(frequency, bool)
            or not isinstance(frequency, int)
            or not 1 <= frequency <= source_count
        ):
            raise RuntimeError("development_pilot_token_df_value_drift")
        token_df[token] = frequency
        previous = token
    return token_df


def _load_development_model_emitter(
    root: Path, *, model_lock_path: str | Path
) -> Callable[[str, str], Sequence[Mapping[str, Any]]]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("development_pilot_cuda_required")
    torch.use_deterministic_algorithms(True)
    lock = load_yaml(_resolve(model_lock_path, root))
    models = lock.get("models") if isinstance(lock, Mapping) else None
    matches = [
        item
        for item in models or []
        if isinstance(item, Mapping) and item.get("role") == "gliner2_base"
    ]
    if len(matches) != 1:
        raise RuntimeError("development_pilot_gliner2_base_lock_missing")
    local_path, _ = _verify_model_lock(matches[0], workspace_root=root)
    backend: SemanticPredictionBackend = _load_backend(
        matches[0],
        local_path,
        runtime_device="cuda",
        use_fp16=True,
    )

    def emit(text: str, _dataset: str) -> Sequence[Mapping[str, Any]]:
        return [
            {
                "label": prediction.label,
                "text": prediction.text,
                "start": prediction.start,
                "end": prediction.end,
                "score": prediction.score,
            }
            for prediction in backend.predict(text, ALL_SEMANTIC_SCHEMA)
        ]

    return emit


def _default_source_selection(
    *,
    source: Mapping[str, Any],
    token_df: Mapping[str, int],
    source_count: int,
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]],
    entity_policy_path: str,
) -> dict[str, Any]:
    candidates = fresh_extract_candidates(
        source,
        model_emitter=model_emitter,
        entity_policy_path=entity_policy_path,
    )
    pair_candidates: list[dict[str, Any]] = []
    rejection_reasons: Counter[str] = Counter()
    for candidate in candidates:
        pairs, reasons = build_pair_candidates(
            source,
            candidate,
            token_df=token_df,
            source_count=source_count,
            token_df_prevalidated=True,
        )
        pair_candidates.extend(pairs)
        rejection_reasons.update(reasons)
    selected = select_top_three(pair_candidates)
    if len(selected) != 3:
        selected = []
        rejection_reasons.update(["fewer_than_three_selected_pairs"])
    return {
        "selected_pairs": selected,
        "rejection_reasons": sorted(rejection_reasons),
        "candidate_count": len(candidates),
        "pair_candidate_count": len(pair_candidates),
        "hard_gate_violation_count": 0,
    }


def _validate_selected_pair(
    pair: Mapping[str, Any],
    *,
    protocol_revision: str,
    dataset: str,
    source_key: str,
    source_hash: str,
    normalized_text_hash: str,
    pair_order: int,
) -> dict[str, Any]:
    value = dict(pair)
    value.setdefault("protocol_revision_id", protocol_revision)
    _assert_exact_fields(value, SELECTED_PAIR_FIELDS, kind="selected_pair")
    reject_forbidden_selection_fields(value, path="selected_pair")
    string_fields = (
        "dataset",
        "source_key",
        "source_hash",
        "normalized_text_hash",
        "pair_id",
        "fact_signature",
        "relation_signature",
        "supporting_sentence",
        "original_entity",
        "counterfactual_entity",
        "effective_type",
        "semantic_subtype",
        "true_claim",
        "counterfactual_claim",
    )
    if (
        value["kind"] != "v23_selected_pair"
        or value["specification_version"] != SPECIFICATION_VERSION
        or value["protocol_revision_id"] != protocol_revision
        or value["dataset"] != dataset
        or value["source_key"] != source_key
        or value["source_hash"] != source_hash
        or value["normalized_text_hash"] != normalized_text_hash
        or value["pair_order"] != pair_order
        or not _is_sha256(value["pair_id"])
        or not _is_sha256(value["fact_signature"])
        or not _is_sha256(value["relation_signature"])
        or any(not isinstance(value[key], str) for key in string_fields)
        or isinstance(value["source_order_rank"], bool)
        or not isinstance(value["source_order_rank"], int)
        or isinstance(value["pair_order"], bool)
        or not isinstance(value["pair_order"], int)
        or not isinstance(value["original_span"], list)
        or len(value["original_span"]) != 2
        or not all(
            isinstance(item, int) and not isinstance(item, bool)
            for item in value["original_span"]
        )
        or not isinstance(value["rank_tuple"], list)
        or len(value["rank_tuple"]) != 17
    ):
        raise RuntimeError("development_pilot_selected_pair_drift")
    return value


def _normalize_source_selection(
    raw: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    source: Mapping[str, Any],
    protocol_revision: str,
) -> dict[str, Any]:
    reject_forbidden_selection_fields(raw, path="selector_output")
    if isinstance(raw, Mapping):
        expected = {
            "selected_pairs",
            "rejection_reasons",
            "candidate_count",
            "pair_candidate_count",
            "hard_gate_violation_count",
        }
        if set(raw) != expected:
            raise RuntimeError("development_pilot_selector_output_schema_drift")
        selected_pairs = raw["selected_pairs"]
        rejection_reasons = raw["rejection_reasons"]
        candidate_count = raw["candidate_count"]
        pair_candidate_count = raw["pair_candidate_count"]
        hard_gate_violation_count = raw["hard_gate_violation_count"]
    else:
        selected_pairs = list(raw)
        rejection_reasons = []
        candidate_count = len(selected_pairs)
        pair_candidate_count = len(selected_pairs)
        hard_gate_violation_count = 0
    if (
        not isinstance(selected_pairs, list)
        or not isinstance(rejection_reasons, list)
        or not all(isinstance(item, str) for item in rejection_reasons)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (
                candidate_count,
                pair_candidate_count,
                hard_gate_violation_count,
            )
        )
    ):
        raise RuntimeError("development_pilot_selector_output_value_drift")
    if rejection_reasons != sorted(set(rejection_reasons)):
        raise RuntimeError("development_pilot_selector_output_value_drift")
    source_hash = text_sha256(str(source["full_text"]))
    normalized_hash = normalized_text_sha256(str(source["full_text"]))
    validated_pairs = [
        _validate_selected_pair(
            item,
            protocol_revision=protocol_revision,
            dataset=str(source["dataset"]),
            source_key=str(source["source_key"]),
            source_hash=source_hash,
            normalized_text_hash=normalized_hash,
            pair_order=index,
        )
        for index, item in enumerate(selected_pairs)
    ]
    if len(validated_pairs) not in {0, 3}:
        validated_pairs = []
        rejection_reasons = sorted(
            {*rejection_reasons, "fewer_than_three_selected_pairs"}
        )
    return {
        "selected_pairs": validated_pairs,
        "rejection_reasons": rejection_reasons,
        "candidate_count": candidate_count,
        "pair_candidate_count": pair_candidate_count,
        "hard_gate_violation_count": hard_gate_violation_count,
    }


def _validate_development_source_result(
    value: Mapping[str, Any],
    *,
    protocol_revision: str,
    runtime_bundle_sha256: str,
    attempt: str,
    dataset: str,
) -> dict[str, Any]:
    row = dict(value)
    _assert_exact_fields(
        row, DEVELOPMENT_SOURCE_RESULT_FIELDS, kind="development_source_result"
    )
    reject_forbidden_selection_fields(row, path="development_source_result")
    claimed = row["source_result_sha256"]
    if (
        row["kind"] != "v23_development_source_result"
        or row["protocol_revision_id"] != protocol_revision
        or row["runtime_bundle_sha256"] != runtime_bundle_sha256
        or row["attempt_id"] != attempt
        or row["dataset"] != dataset
        or not _is_sha256(row["source_hash"])
        or not _is_sha256(row["normalized_text_hash"])
        or not _is_sha256(claimed)
        or canonical_sha256(
            {key: item for key, item in row.items() if key != "source_result_sha256"}
        )
        != claimed
        or not isinstance(row["eligible"], bool)
        or row["eligible"] != (len(row["selected_pairs"]) == 3)
        or not isinstance(row["deterministic_rerun_hash_match"], bool)
    ):
        raise RuntimeError("development_source_result_identity_drift")
    for key in (
        "source_order_index",
        "candidate_count",
        "pair_candidate_count",
        "hard_gate_violation_count",
    ):
        if isinstance(row[key], bool) or not isinstance(row[key], int) or row[key] < 0:
            raise RuntimeError("development_source_result_count_drift")
    if not isinstance(row["rejection_reasons"], list) or not all(
        isinstance(item, str) for item in row["rejection_reasons"]
    ):
        raise RuntimeError("development_source_result_reasons_drift")
    if row["rejection_reasons"] != sorted(set(row["rejection_reasons"])):
        raise RuntimeError("development_source_result_reasons_drift")
    validated_pairs = [
        _validate_selected_pair(
            item,
            protocol_revision=protocol_revision,
            dataset=dataset,
            source_key=str(row["source_key"]),
            source_hash=str(row["source_hash"]),
            normalized_text_hash=str(row["normalized_text_hash"]),
            pair_order=index,
        )
        for index, item in enumerate(row["selected_pairs"])
    ]
    if validated_pairs != row["selected_pairs"]:
        raise RuntimeError("development_source_result_pair_drift")
    return row


def _write_or_validate_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    expected = "".join(canonical_json(dict(row)) + "\n" for row in rows).encode(
        "utf-8"
    )
    if path.exists():
        if path.read_bytes() != expected:
            raise RuntimeError(f"existing_artifact_identity_drift:{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(expected).hexdigest()[:16]
    temporary = path.with_name(f"{path.name}.{digest}.tmp")
    if temporary.exists():
        if temporary.read_bytes() == expected:
            os.replace(temporary, path)
            return
        temporary = path.with_name(
            f"{path.name}.{digest}.{time.time_ns()}.tmp"
        )
    with temporary.open("xb") as handle:
        handle.write(expected)
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists():
        if path.read_bytes() != expected:
            raise RuntimeError(f"existing_artifact_identity_drift:{path}")
        return
    os.replace(temporary, path)


def _pilot_authorization(
    root: Path, *, dataset: str, active: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    paths = _stage_authorization_paths(
        root,
        stage=DEVELOPMENT_PILOT_STAGE,
        runtime_bundle_sha256=str(active["runtime_bundle_sha256"]),
        datasets=[dataset],
    )
    if len(paths) != 1:
        raise RuntimeError("development_pilot_authorization_count_invalid")
    authorization, registry = _load_stage_run_authorization_file(
        root=root,
        authorization_path=paths[0],
        stage=DEVELOPMENT_PILOT_STAGE,
        execution_unit="one_dataset",
        datasets=[dataset],
    )
    if (
        authorization["protocol_revision_id"] != active["protocol_revision_id"]
        or authorization["run_roles"] != ["development"]
    ):
        raise RuntimeError("development_pilot_authorization_identity_drift")
    return authorization, registry, paths[0]


def run_development_pilot(
    *,
    project_root: str | Path,
    dataset: str,
    authorization_path: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
    selector: Callable[
        [Mapping[str, Any], Mapping[str, int], int],
        Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ]
    | None = None,
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]] | None = None,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if dataset not in DATASET_ORDER:
        raise ValueError("development_pilot_dataset_invalid")
    root = Path(project_root).resolve()
    lock = _resolve(
        ARTIFACT_ROOT / "governance" / f"development_pilot_{dataset}.lock", root
    )
    with exclusive_lock(lock):
        active = validate_active_runtime(
            root,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        authorization, registry = _load_stage_run_authorization_file(
            root=root,
            authorization_path=authorization_path,
            stage=DEVELOPMENT_PILOT_STAGE,
            execution_unit="one_dataset",
            datasets=[dataset],
        )
        if (
            authorization["runtime_bundle_sha256"]
            != active["runtime_bundle_sha256"]
            or authorization["protocol_revision_id"]
            != active["protocol_revision_id"]
            or authorization["run_roles"] != ["development"]
        ):
            raise RuntimeError("development_pilot_active_runtime_drift")
        reservation = _development_reservation_prerequisite(
            root,
            active=active,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        aggregate = validate_aggregate_df(
            project_root=root,
            dataset=dataset,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        config = load_design_config(root)
        development_count, _ = _reservation_counts(config)
        if authorization["budget_limit"] != development_count:
            raise RuntimeError("development_pilot_budget_limit_drift")
        paths = _development_pilot_paths(
            root, dataset=dataset, attempt=authorization["attempt_id"]
        )
        _validate_development_recovery_attestation(
            root,
            dataset=dataset,
            authorization=authorization,
            reservation=reservation,
        )
        if paths["checkpoint"].exists():
            completed = validate_development_pilot(
                project_root=root,
                dataset=dataset,
                runtime_files=runtime_files,
                dependency_lock_path=dependency_lock_path,
                model_lock_path=model_lock_path,
            )
            if (
                dataset == DATASET_ORDER[-1]
                and completed["status"] == "passed"
                and not _development_gate_manifest_path(
                    root, active["protocol_revision_id"]
                ).exists()
            ):
                _write_development_gate_manifest(
                    root,
                    active=active,
                    runtime_files=runtime_files,
                    dependency_lock_path=dependency_lock_path,
                    model_lock_path=model_lock_path,
                )
            return completed
        ledger_path = _resolve(CONSUMPTION_LEDGER, root)
        ledger = validate_ledger(ledger_path)
        ledger_rows = _ledger_rows(root)
        prior_sequence = _ledger_sequence_for_tip(
            ledger_rows, authorization["expected_prior_ledger_tip_sha256"]
        )
        input_anchor = _ledger_tip_anchor(
            root, authorization["expected_prior_ledger_tip_sha256"]
        )
        development = _development_batch_evidence(
            root, dataset=dataset, expected_count=development_count
        )
        reservation_completion = Path(reservation["group_completion_path"])
        reservation_completion_sha256 = sha256_file(reservation_completion)
        pool = _aggregate_df_contracts(config, dataset)["pool"]
        token_df = _load_validated_token_df(
            root, dataset=dataset, source_count=pool["source_count"]
        )
        if selector is None and model_emitter is None:
            model_emitter = _load_development_model_emitter(
                root, model_lock_path=model_lock_path
            )
        if selector is None and model_emitter is None:
            raise RuntimeError("development_pilot_model_emitter_missing")
        if model_runtime_identity is not None and selector is None:
            raise RuntimeError("development_pilot_injected_identity_without_selector")
        runtime_identity = (
            dict(model_runtime_identity)
            if model_runtime_identity is not None
            else dict(_load_runtime_lineage(root)["active_bundle"]["gliner_runtime_identity"])
        )
        reject_forbidden_selection_fields(
            runtime_identity, path="model_runtime_identity"
        )
        entity_policy_path = str(
            _resolve(
                config["frozen_v22_bindings"]["extraction_rule_bindings"][
                    "entity_type_policy_path"
                ],
                root,
            )
        )
        budget_path = _resolve(
            BUDGET_DIRECTORY / f"{authorization['authorization_id']}.jsonl", root
        )
        charged_count, _, charged_operations = _read_budget_state(
            budget_path, authorization
        )
        paths["source_results"].mkdir(parents=True, exist_ok=True)
        with FrozenSourcePoolReader(
            project_root=root,
            dataset=dataset,
            database_path=pool["database_path"],
            database_sha256=pool["database_sha256"],
            source_order_path=pool["source_order_path"],
            source_order_file_sha256=pool["source_order_file_sha256"],
            source_pool_manifest_path=pool["manifest_path"],
            source_pool_manifest_sha256=pool["manifest_sha256"],
            expected_source_count=pool["source_count"],
        ) as reader:
            for source_order_index, ledger_row in enumerate(development["rows"]):
                result_path = (
                    paths["source_results"] / f"{source_order_index:06d}.json"
                )
                operation_identity = canonical_sha256(
                    {
                        "kind": "v23_reserved_source_selector_read",
                        "authorization_id": authorization["authorization_id"],
                        "dataset": dataset,
                        "source_key": ledger_row["source_key"],
                        "reservation_batch_id": development[
                            "reservation_batch_id"
                        ],
                    }
                )
                if result_path.exists():
                    existing = _validate_development_source_result(
                        _read_json_exact(result_path),
                        protocol_revision=active["protocol_revision_id"],
                        runtime_bundle_sha256=active["runtime_bundle_sha256"],
                        attempt=authorization["attempt_id"],
                        dataset=dataset,
                    )
                    if (
                        existing["source_order_index"] != source_order_index
                        or existing["source_key"] != ledger_row["source_key"]
                        or operation_identity not in charged_operations
                    ):
                        raise RuntimeError("development_pilot_resume_identity_drift")
                    continue
                source = reader.read_reserved_source(
                    str(ledger_row["source_key"]),
                    ledger_path=ledger_path,
                    anchor_path=development["anchor_path"],
                    authorization=authorization,
                    attempt_registry_row=registry,
                    budget_journal_path=budget_path,
                    resume_existing_charge=(operation_identity in charged_operations),
                )

                def evaluate_once() -> dict[str, Any]:
                    raw = (
                        selector(source, token_df, int(pool["source_count"]))
                        if selector is not None
                        else _default_source_selection(
                            source=source,
                            token_df=token_df,
                            source_count=int(pool["source_count"]),
                            model_emitter=model_emitter,
                            entity_policy_path=entity_policy_path,
                        )
                    )
                    return _normalize_source_selection(
                        raw,
                        source=source,
                        protocol_revision=active["protocol_revision_id"],
                    )

                first = evaluate_once()
                second = evaluate_once()
                deterministic = canonical_sha256(first) == canonical_sha256(second)
                source_result = {
                    "kind": "v23_development_source_result",
                    "protocol_revision_id": active["protocol_revision_id"],
                    "runtime_bundle_sha256": active["runtime_bundle_sha256"],
                    "attempt_id": authorization["attempt_id"],
                    "dataset": dataset,
                    "source_order_index": source_order_index,
                    "source_key": source["source_key"],
                    "source_hash": text_sha256(source["full_text"]),
                    "normalized_text_hash": normalized_text_sha256(
                        source["full_text"]
                    ),
                    "eligible": len(first["selected_pairs"]) == 3,
                    "selected_pairs": first["selected_pairs"],
                    "rejection_reasons": first["rejection_reasons"],
                    "candidate_count": first["candidate_count"],
                    "pair_candidate_count": first["pair_candidate_count"],
                    "hard_gate_violation_count": first[
                        "hard_gate_violation_count"
                    ],
                    "deterministic_rerun_hash_match": deterministic,
                    "completed_at": utc_now(),
                }
                source_result["source_result_sha256"] = canonical_sha256(
                    source_result
                )
                _write_new_atomic_canonical_json(result_path, source_result)
                charged_operations.add(operation_identity)
                charged_count += 1
        source_results = [
            _validate_development_source_result(
                _read_json_exact(
                    paths["source_results"] / f"{index:06d}.json"
                ),
                protocol_revision=active["protocol_revision_id"],
                runtime_bundle_sha256=active["runtime_bundle_sha256"],
                attempt=authorization["attempt_id"],
                dataset=dataset,
            )
            for index in range(development_count)
        ]
        charged_count, budget_tip, _ = _read_budget_state(
            budget_path, authorization
        )
        if charged_count != development_count:
            raise RuntimeError("development_pilot_budget_count_incomplete")
        selected_pairs = [
            pair
            for result in source_results
            for pair in result["selected_pairs"]
        ]
        _write_or_validate_jsonl(paths["selected_pairs"], selected_pairs)
        consumed_non_development = len(
            {
                row["source_key"]
                for row in ledger_rows[1 : prior_sequence + 1]
                if row.get("dataset") == dataset
                and row.get("role") != "development"
            }
        )
        eligible_count = sum(result["eligible"] for result in source_results)
        capacity = capacity_decision(
            population=int(pool["source_count"]),
            sample=development_count,
            observed_eligible=eligible_count,
            consumed_non_development=consumed_non_development,
        )
        rejection_counts: Counter[str] = Counter(
            reason
            for result in source_results
            for reason in result["rejection_reasons"]
        )
        deterministic = all(
            result["deterministic_rerun_hash_match"] for result in source_results
        )
        hard_gate_violations = sum(
            result["hard_gate_violation_count"] for result in source_results
        )
        manifest_status = (
            "passed"
            if deterministic
            and hard_gate_violations == 0
            and capacity["status"] == "passed"
            else "failed_development_gate"
        )
        manifest_completed_at = utc_now()
        if paths["manifest"].exists():
            manifest_completed_at = str(
                _read_json_exact(paths["manifest"]).get("completed_at")
            )
        manifest = {
            "kind": "v23_development_pilot_manifest",
            "protocol_revision_id": active["protocol_revision_id"],
            "runtime_bundle_sha256": active["runtime_bundle_sha256"],
            "authorization_id": authorization["authorization_id"],
            "attempt_id": authorization["attempt_id"],
            "dataset": dataset,
            "reservation_group_completion_sha256": reservation_completion_sha256,
            "development_batch_anchor_sha256": development["anchor_sha256"],
            "aggregate_df_manifest_sha256": aggregate[
                "df_manifest_file_sha256"
            ],
            "aggregate_df_rows_sha256": aggregate[
                "token_df_rows_file_sha256"
            ],
            "model_runtime_identity": runtime_identity,
            "source_count": development_count,
            "eligible_source_count": eligible_count,
            "selected_pair_count": len(selected_pairs),
            "selected_pairs_path": _relative(paths["selected_pairs"], root),
            "selected_pairs_file_sha256": sha256_file(paths["selected_pairs"]),
            "source_result_directory": _relative(paths["source_results"], root),
            "source_result_group_sha256": canonical_sha256(
                [result["source_result_sha256"] for result in source_results]
            ),
            "rejection_reasons": dict(sorted(rejection_counts.items())),
            "deterministic_rerun_hash_match": deterministic,
            "hard_gate_violation_count": hard_gate_violations,
            "capacity_decision": capacity,
            "status": manifest_status,
            "external_calls_performed": 0,
            "completed_at": manifest_completed_at,
        }
        _write_or_validate_canonical(paths["manifest"], manifest)
        checkpoint = {
            "kind": "v23_stage_checkpoint",
            "protocol_revision_id": active["protocol_revision_id"],
            "attempt_id": authorization["attempt_id"],
            "stage": DEVELOPMENT_PILOT_STAGE,
            "execution_unit": "one_dataset",
            "status": "passed" if manifest_status == "passed" else "failed",
            "input_ledger_tip_sha256": authorization[
                "expected_prior_ledger_tip_sha256"
            ],
            "input_tip_anchor_sha256": sha256_file(input_anchor),
            "output_ledger_tip_sha256": authorization[
                "expected_prior_ledger_tip_sha256"
            ],
            "output_tip_anchor_sha256": sha256_file(input_anchor),
            "ledger_mutation": False,
            "authorization_id": authorization["authorization_id"],
            "authorization_budget_journal_tip_sha256": budget_tip,
            "runtime_bundle_sha256": active["runtime_bundle_sha256"],
            "output_manifest_sha256": sha256_file(paths["manifest"]),
            "completed_at": utc_now(),
        }
        write_stage_checkpoint(paths["checkpoint"], checkpoint)
        if dataset == DATASET_ORDER[-1] and manifest_status == "passed":
            _write_development_gate_manifest(
                root,
                active=active,
                runtime_files=runtime_files,
                dependency_lock_path=dependency_lock_path,
                model_lock_path=model_lock_path,
            )
    return validate_development_pilot(
        project_root=root,
        dataset=dataset,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )


def _read_development_source_results(
    root: Path,
    *,
    active: Mapping[str, Any],
    authorization: Mapping[str, Any],
    dataset: str,
    expected_count: int,
) -> list[dict[str, Any]]:
    paths = _development_pilot_paths(
        root, dataset=dataset, attempt=str(authorization["attempt_id"])
    )
    actual_paths = sorted(paths["source_results"].glob("*.json"))
    expected_paths = [
        paths["source_results"] / f"{index:06d}.json"
        for index in range(expected_count)
    ]
    if actual_paths != expected_paths:
        raise RuntimeError("development_pilot_source_result_set_drift")
    return [
        _validate_development_source_result(
            _read_json_exact(path),
            protocol_revision=str(active["protocol_revision_id"]),
            runtime_bundle_sha256=str(active["runtime_bundle_sha256"]),
            attempt=str(authorization["attempt_id"]),
            dataset=dataset,
        )
        for path in expected_paths
    ]


def validate_development_pilot(
    *,
    project_root: str | Path,
    dataset: str,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    """Validate a pilot artifact using only durable rows and registered hashes."""

    if dataset not in DATASET_ORDER:
        raise ValueError("development_pilot_dataset_invalid")
    root = Path(project_root).resolve()
    active = validate_active_runtime(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    reservation = _development_reservation_prerequisite(
        root,
        active=active,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    aggregate = validate_aggregate_df(
        project_root=root,
        dataset=dataset,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    authorization, _, authorization_path = _pilot_authorization(
        root, dataset=dataset, active=active
    )
    config = load_design_config(root)
    development_count, _ = _reservation_counts(config)
    if authorization["budget_limit"] != development_count:
        raise RuntimeError("development_pilot_budget_limit_drift")
    development = _development_batch_evidence(
        root, dataset=dataset, expected_count=development_count
    )
    paths = _development_pilot_paths(
        root, dataset=dataset, attempt=authorization["attempt_id"]
    )
    _validate_development_recovery_attestation(
        root,
        dataset=dataset,
        authorization=authorization,
        reservation=reservation,
    )
    manifest = _read_json_exact(paths["manifest"])
    _assert_exact_fields(
        manifest, DEVELOPMENT_PILOT_MANIFEST_FIELDS, kind="development_pilot_manifest"
    )
    reject_forbidden_selection_fields(manifest, path="development_pilot_manifest")
    source_results = _read_development_source_results(
        root,
        active=active,
        authorization=authorization,
        dataset=dataset,
        expected_count=development_count,
    )
    for index, (result, ledger_row) in enumerate(
        zip(source_results, development["rows"], strict=True)
    ):
        if (
            result["source_order_index"] != index
            or result["source_key"] != ledger_row["source_key"]
            or result["source_hash"] != ledger_row["source_hash"]
            or result["normalized_text_hash"]
            != ledger_row["normalized_text_hash"]
        ):
            raise RuntimeError("development_pilot_source_identity_drift")
    selected_pairs = [
        pair
        for result in source_results
        for pair in result["selected_pairs"]
    ]
    raw_selected = paths["selected_pairs"].read_bytes()
    expected_selected = "".join(
        canonical_json(pair) + "\n" for pair in selected_pairs
    ).encode("utf-8")
    if raw_selected != expected_selected:
        raise RuntimeError("development_pilot_selected_pairs_file_drift")
    eligible_count = sum(result["eligible"] for result in source_results)
    rejection_counts: Counter[str] = Counter(
        reason
        for result in source_results
        for reason in result["rejection_reasons"]
    )
    deterministic = all(
        result["deterministic_rerun_hash_match"] for result in source_results
    )
    hard_gate_violations = sum(
        result["hard_gate_violation_count"] for result in source_results
    )
    ledger_rows = _ledger_rows(root)
    prior_sequence = _ledger_sequence_for_tip(
        ledger_rows, authorization["expected_prior_ledger_tip_sha256"]
    )
    consumed_non_development = len(
        {
            row["source_key"]
            for row in ledger_rows[1 : prior_sequence + 1]
            if row.get("dataset") == dataset
            and row.get("role") != "development"
        }
    )
    pool = _aggregate_df_contracts(config, dataset)["pool"]
    capacity = capacity_decision(
        population=int(pool["source_count"]),
        sample=development_count,
        observed_eligible=eligible_count,
        consumed_non_development=consumed_non_development,
    )
    expected_status = (
        "passed"
        if deterministic
        and hard_gate_violations == 0
        and capacity["status"] == "passed"
        else "failed_development_gate"
    )
    reservation_completion_path = Path(reservation["group_completion_path"])
    if (
        manifest["kind"] != "v23_development_pilot_manifest"
        or manifest["protocol_revision_id"] != active["protocol_revision_id"]
        or manifest["runtime_bundle_sha256"]
        != active["runtime_bundle_sha256"]
        or manifest["authorization_id"] != authorization["authorization_id"]
        or manifest["attempt_id"] != authorization["attempt_id"]
        or manifest["dataset"] != dataset
        or manifest["reservation_group_completion_sha256"]
        != sha256_file(reservation_completion_path)
        or manifest["reservation_group_completion_sha256"]
        != reservation["group_completion_file_sha256"]
        or manifest["development_batch_anchor_sha256"]
        != development["anchor_sha256"]
        or manifest["aggregate_df_manifest_sha256"]
        != aggregate["df_manifest_file_sha256"]
        or manifest["aggregate_df_rows_sha256"]
        != aggregate["token_df_rows_file_sha256"]
        or not isinstance(manifest["model_runtime_identity"], Mapping)
        or not manifest["model_runtime_identity"]
        or manifest["source_count"] != development_count
        or manifest["eligible_source_count"] != eligible_count
        or manifest["selected_pair_count"] != len(selected_pairs)
        or manifest["selected_pairs_path"]
        != _relative(paths["selected_pairs"], root)
        or manifest["selected_pairs_file_sha256"]
        != sha256_file(paths["selected_pairs"])
        or manifest["source_result_directory"]
        != _relative(paths["source_results"], root)
        or manifest["source_result_group_sha256"]
        != canonical_sha256(
            [result["source_result_sha256"] for result in source_results]
        )
        or manifest["rejection_reasons"]
        != dict(sorted(rejection_counts.items()))
        or manifest["deterministic_rerun_hash_match"] != deterministic
        or manifest["hard_gate_violation_count"] != hard_gate_violations
        or manifest["capacity_decision"] != capacity
        or manifest["status"] != expected_status
        or manifest["external_calls_performed"] != 0
    ):
        raise RuntimeError("development_pilot_manifest_drift")
    budget_path = _resolve(
        BUDGET_DIRECTORY / f"{authorization['authorization_id']}.jsonl", root
    )
    charged_count, budget_tip, charged_operations = _read_budget_state(
        budget_path, authorization
    )
    expected_operations = {
        canonical_sha256(
            {
                "kind": "v23_reserved_source_selector_read",
                "authorization_id": authorization["authorization_id"],
                "dataset": dataset,
                "source_key": row["source_key"],
                "reservation_batch_id": development["reservation_batch_id"],
            }
        )
        for row in development["rows"]
    }
    if (
        charged_count != development_count
        or charged_operations != expected_operations
    ):
        raise RuntimeError("development_pilot_budget_drift")
    checkpoint = _read_json_exact(paths["checkpoint"])
    _assert_exact_fields(checkpoint, STAGE_CHECKPOINT_FIELDS, kind="stage_checkpoint")
    input_anchor = _ledger_tip_anchor(
        root, authorization["expected_prior_ledger_tip_sha256"]
    )
    expected_checkpoint_status = "passed" if expected_status == "passed" else "failed"
    if (
        checkpoint["kind"] != "v23_stage_checkpoint"
        or checkpoint["protocol_revision_id"] != active["protocol_revision_id"]
        or checkpoint["attempt_id"] != authorization["attempt_id"]
        or checkpoint["stage"] != DEVELOPMENT_PILOT_STAGE
        or checkpoint["execution_unit"] != "one_dataset"
        or checkpoint["status"] != expected_checkpoint_status
        or checkpoint["input_ledger_tip_sha256"]
        != authorization["expected_prior_ledger_tip_sha256"]
        or checkpoint["output_ledger_tip_sha256"]
        != authorization["expected_prior_ledger_tip_sha256"]
        or checkpoint["input_tip_anchor_sha256"] != sha256_file(input_anchor)
        or checkpoint["output_tip_anchor_sha256"] != sha256_file(input_anchor)
        or checkpoint["ledger_mutation"] is not False
        or checkpoint["authorization_id"] != authorization["authorization_id"]
        or checkpoint["authorization_budget_journal_tip_sha256"] != budget_tip
        or checkpoint["runtime_bundle_sha256"]
        != active["runtime_bundle_sha256"]
        or checkpoint["output_manifest_sha256"] != sha256_file(paths["manifest"])
    ):
        raise RuntimeError("development_pilot_checkpoint_drift")
    return {
        "status": expected_status,
        "dataset": dataset,
        "runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "protocol_revision_id": active["protocol_revision_id"],
        "authorization_id": authorization["authorization_id"],
        "authorization_file_sha256": sha256_file(authorization_path),
        "attempt_id": authorization["attempt_id"],
        "reservation_validation_mode": reservation["validation_mode"],
        "source_count": development_count,
        "eligible_source_count": eligible_count,
        "selected_pair_count": len(selected_pairs),
        "capacity_decision": capacity,
        "pilot_manifest_file_sha256": sha256_file(paths["manifest"]),
        "selected_pairs_file_sha256": sha256_file(paths["selected_pairs"]),
        "source_result_group_sha256": manifest["source_result_group_sha256"],
        "budget_charge_count": charged_count,
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }


def _development_cross_dataset_overlap(
    source_results_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]]
) -> tuple[int, int]:
    source_hashes: set[str] = set()
    normalized_hashes: set[str] = set()
    source_overlap = 0
    normalized_overlap = 0
    for dataset in DATASET_ORDER:
        for row in source_results_by_dataset[dataset]:
            if row["source_hash"] in source_hashes:
                source_overlap += 1
            if row["normalized_text_hash"] in normalized_hashes:
                normalized_overlap += 1
            source_hashes.add(str(row["source_hash"]))
            normalized_hashes.add(str(row["normalized_text_hash"]))
    return source_overlap, normalized_overlap


def _development_group_evidence(
    root: Path,
    *,
    active: Mapping[str, Any],
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    validations: dict[str, dict[str, Any]] = {}
    results: dict[str, list[dict[str, Any]]] = {}
    config = load_design_config(root)
    development_count, _ = _reservation_counts(config)
    for dataset in DATASET_ORDER:
        validation = validate_development_pilot(
            project_root=root,
            dataset=dataset,
            runtime_files=runtime_files,
            dependency_lock_path=dependency_lock_path,
            model_lock_path=model_lock_path,
        )
        if validation["status"] != "passed":
            raise RuntimeError("development_pilot_group_dataset_not_passed")
        authorization, _, _ = _pilot_authorization(
            root, dataset=dataset, active=active
        )
        validations[dataset] = validation
        results[dataset] = _read_development_source_results(
            root,
            active=active,
            authorization=authorization,
            dataset=dataset,
            expected_count=development_count,
        )
    return validations, results


def _write_development_gate_manifest(
    root: Path,
    *,
    active: Mapping[str, Any],
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    validations, results = _development_group_evidence(
        root,
        active=active,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    source_overlap, normalized_overlap = _development_cross_dataset_overlap(results)
    status = (
        "passed"
        if source_overlap == 0 and normalized_overlap == 0
        else "failed_cross_dataset_overlap"
    )
    path = _development_gate_manifest_path(
        root, str(active["protocol_revision_id"])
    )
    manifest = {
        "kind": "v23_development_gate_manifest",
        "protocol_revision_id": active["protocol_revision_id"],
        "runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "dataset_order": list(DATASET_ORDER),
        "pilot_manifest_sha256_by_dataset": {
            dataset: validations[dataset]["pilot_manifest_file_sha256"]
            for dataset in DATASET_ORDER
        },
        "selected_pairs_file_sha256_by_dataset": {
            dataset: validations[dataset]["selected_pairs_file_sha256"]
            for dataset in DATASET_ORDER
        },
        "cross_dataset_source_hash_overlap": source_overlap,
        "cross_dataset_normalized_text_hash_overlap": normalized_overlap,
        "status": status,
        "created_at": (
            str(_read_json_exact(path).get("created_at"))
            if path.exists()
            else utc_now()
        ),
    }
    _write_or_validate_canonical(path, manifest)
    if status != "passed":
        raise RuntimeError("development_pilot_group_cross_dataset_overlap")
    return manifest


def validate_development_pilot_group(
    *,
    project_root: str | Path,
    runtime_files: Sequence[str] | None = None,
    dependency_lock_path: str | Path = DEPENDENCY_LOCK_PATH,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    active = validate_active_runtime(
        root,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    validations, results = _development_group_evidence(
        root,
        active=active,
        runtime_files=runtime_files,
        dependency_lock_path=dependency_lock_path,
        model_lock_path=model_lock_path,
    )
    source_overlap, normalized_overlap = _development_cross_dataset_overlap(results)
    path = _development_gate_manifest_path(
        root, active["protocol_revision_id"]
    )
    manifest = _read_json_exact(path)
    _assert_exact_fields(
        manifest, DEVELOPMENT_GATE_MANIFEST_FIELDS, kind="development_gate_manifest"
    )
    if (
        manifest["kind"] != "v23_development_gate_manifest"
        or manifest["protocol_revision_id"] != active["protocol_revision_id"]
        or manifest["runtime_bundle_sha256"]
        != active["runtime_bundle_sha256"]
        or manifest["dataset_order"] != list(DATASET_ORDER)
        or manifest["pilot_manifest_sha256_by_dataset"]
        != {
            dataset: validations[dataset]["pilot_manifest_file_sha256"]
            for dataset in DATASET_ORDER
        }
        or manifest["selected_pairs_file_sha256_by_dataset"]
        != {
            dataset: validations[dataset]["selected_pairs_file_sha256"]
            for dataset in DATASET_ORDER
        }
        or manifest["cross_dataset_source_hash_overlap"] != source_overlap
        or manifest["cross_dataset_normalized_text_hash_overlap"]
        != normalized_overlap
        or manifest["status"] != "passed"
        or source_overlap != 0
        or normalized_overlap != 0
    ):
        raise RuntimeError("development_pilot_group_manifest_drift")
    return {
        "status": "passed",
        "runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "protocol_revision_id": active["protocol_revision_id"],
        "dataset_order": list(DATASET_ORDER),
        "pilot_manifest_sha256_by_dataset": manifest[
            "pilot_manifest_sha256_by_dataset"
        ],
        "selected_pairs_file_sha256_by_dataset": manifest[
            "selected_pairs_file_sha256_by_dataset"
        ],
        "cross_dataset_source_hash_overlap": 0,
        "cross_dataset_normalized_text_hash_overlap": 0,
        "group_manifest_file_sha256": sha256_file(path),
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }


AUDIT_DIMENSIONS = (
    "grounded_fact_stability",
    "original_entity_recoverability",
    "minimum_construction_validity",
    "non_entity_retrieval_anchor",
    "verification_discriminativeness",
    "query_self_containment",
)
AUDIT_VALUES = frozenset({"pass", "fail", "uncertain"})


def _audit_overall(row: Mapping[str, Any]) -> str:
    values = [row.get(field) for field in AUDIT_DIMENSIONS]
    if not all(value in AUDIT_VALUES for value in values):
        raise ValueError("audit_dimension_invalid")
    calculated = "fail" if "fail" in values else "pass" if all(value == "pass" for value in values) else "uncertain"
    if row.get("overall_label") != calculated:
        raise ValueError("audit_overall_label_drift")
    return calculated


def _cohen_kappa(labels_a: Sequence[str], labels_b: Sequence[str]) -> float:
    if len(labels_a) != len(labels_b) or not labels_a:
        raise ValueError("audit_kappa_input_invalid")
    observed = sum(left == right for left, right in zip(labels_a, labels_b)) / len(labels_a)
    categories = ("pass", "fail", "uncertain")
    expected = math.fsum(
        (labels_a.count(category) / len(labels_a))
        * (labels_b.count(category) / len(labels_b))
        for category in categories
    )
    if math.isclose(expected, 1.0):
        raise RuntimeError("audit_kappa_zero_denominator")
    return (observed - expected) / (1.0 - expected)


def evaluate_blind_audit(
    *,
    packet_rows: Sequence[Mapping[str, Any]],
    reviewer_a_rows: Sequence[Mapping[str, Any]],
    reviewer_b_rows: Sequence[Mapping[str, Any]],
    adjudicator_rows: Sequence[Mapping[str, Any]],
    private_dataset_by_source_id: Mapping[str, str],
    expected_pair_count: int = 900,
) -> dict[str, Any]:
    """Validate complete independent labels, adjudicate disagreements, and apply all gates."""

    if len(packet_rows) != expected_pair_count:
        raise RuntimeError("audit_packet_count_invalid")
    packet_keys = [(row.get("opaque_audit_source_id"), row.get("pair_id")) for row in packet_rows]
    if len(set(packet_keys)) != expected_pair_count:
        raise RuntimeError("audit_packet_duplicate_identity")

    def index_labels(rows: Sequence[Mapping[str, Any]], role: str) -> dict[tuple[Any, Any], Mapping[str, Any]]:
        if len(rows) != expected_pair_count:
            raise RuntimeError(f"audit_{role}_label_count_invalid")
        indexed: dict[tuple[Any, Any], Mapping[str, Any]] = {}
        for row in rows:
            key = (row.get("opaque_audit_source_id"), row.get("pair_id"))
            if key in indexed or key not in set(packet_keys):
                raise RuntimeError(f"audit_{role}_label_identity_invalid")
            _audit_overall(row)
            indexed[key] = row
        return indexed

    reviewer_a = index_labels(reviewer_a_rows, "reviewer_a")
    reviewer_b = index_labels(reviewer_b_rows, "reviewer_b")
    labels_a = [_audit_overall(reviewer_a[key]) for key in packet_keys]
    labels_b = [_audit_overall(reviewer_b[key]) for key in packet_keys]
    adjudication_scope = [
        key
        for key, left, right in zip(packet_keys, labels_a, labels_b)
        if left != right or left == "uncertain" or right == "uncertain"
    ]
    adjudicator: dict[tuple[Any, Any], Mapping[str, Any]] = {}
    for row in adjudicator_rows:
        key = (row.get("opaque_audit_source_id"), row.get("pair_id"))
        if key in adjudicator or key not in set(adjudication_scope):
            raise RuntimeError("audit_adjudicator_scope_invalid")
        _audit_overall(row)
        adjudicator[key] = row
    if set(adjudicator) != set(adjudication_scope):
        raise RuntimeError("audit_adjudicator_labels_incomplete")

    final_labels: list[str] = []
    by_dataset_pair: dict[str, list[str]] = {dataset: [] for dataset in DATASET_ORDER}
    by_dataset_source: dict[str, dict[str, list[str]]] = {
        dataset: {} for dataset in DATASET_ORDER
    }
    for packet, key, left, right in zip(packet_rows, packet_keys, labels_a, labels_b):
        final = left if left == right and left != "uncertain" else _audit_overall(adjudicator[key])
        final_labels.append(final)
        source_id = str(packet.get("opaque_audit_source_id"))
        dataset = private_dataset_by_source_id.get(source_id)
        if dataset not in DATASET_ORDER:
            raise RuntimeError("audit_private_dataset_binding_invalid")
        by_dataset_pair[dataset].append(final)
        by_dataset_source[dataset].setdefault(source_id, []).append(final)

    raw_agreement = sum(left == right for left, right in zip(labels_a, labels_b)) / expected_pair_count
    kappa = _cohen_kappa(labels_a, labels_b)
    overall_acceptance = final_labels.count("pass") / expected_pair_count
    uncertain_rate = final_labels.count("uncertain") / expected_pair_count
    dataset_pair_acceptance = {
        dataset: labels.count("pass") / len(labels) if labels else 0.0
        for dataset, labels in by_dataset_pair.items()
    }
    dataset_source_all_three = {
        dataset: (
            sum(len(labels) == 3 and all(label == "pass" for label in labels) for labels in sources.values())
            / len(sources)
            if sources
            else 0.0
        )
        for dataset, sources in by_dataset_source.items()
    }
    gates = {
        "minimum_pair_acceptance_rate": overall_acceptance >= 0.90,
        "maximum_uncertain_rate": uncertain_rate <= 0.05,
        "minimum_dataset_pair_acceptance_rate": all(value >= 0.85 for value in dataset_pair_acceptance.values()),
        "minimum_each_dataset_source_all_three_pairs_pass_rate": all(value >= 0.80 for value in dataset_source_all_three.values()),
        "minimum_pre_adjudication_raw_agreement": raw_agreement >= 0.90,
        "minimum_cohen_kappa": kappa >= 0.80,
    }
    return {
        "raw_agreement": raw_agreement,
        "cohen_kappa": kappa,
        "final_overall_acceptance": overall_acceptance,
        "final_uncertain": uncertain_rate,
        "dataset_pair_acceptance": dataset_pair_acceptance,
        "dataset_source_all_three_pairs_pass": dataset_source_all_three,
        "adjudication_scope_count": len(adjudication_scope),
        "gates": gates,
        "status": "passed" if all(gates.values()) else "failed_fresh_blind_audit",
    }


def freeze_source_exclusive_split(
    *,
    selected_sources: Sequence[Mapping[str, Any]],
    dataset: str,
    split_seed: int = 42,
    expected_count: int = 2_250,
) -> list[dict[str, Any]]:
    """Freeze the complete selected set before assigning membership-independent groups."""

    if dataset not in DATASET_ORDER or len(selected_sources) != expected_count:
        raise RuntimeError("formal_selected_source_count_invalid")
    seen_keys: set[str] = set()
    seen_source_hashes: set[str] = set()
    seen_text_hashes: set[str] = set()
    keyed: list[tuple[str, Mapping[str, Any]]] = []
    for row in selected_sources:
        required = {"source_key", "source_hash", "normalized_text_hash"}
        if set(row) != required:
            raise RuntimeError("formal_selected_source_schema_invalid")
        source_key = str(row["source_key"])
        source_hash = str(row["source_hash"])
        text_hash = str(row["normalized_text_hash"])
        if source_key in seen_keys or source_hash in seen_source_hashes or text_hash in seen_text_hashes:
            raise RuntimeError("formal_selected_source_overlap")
        seen_keys.add(source_key)
        seen_source_hashes.add(source_hash)
        seen_text_hashes.add(text_hash)
        split_key = canonical_sha256(
            {
                "kind": "v23_formal_split",
                "specification_version": SPECIFICATION_VERSION,
                "selection_seed": split_seed,
                "dataset": dataset,
                "source_key": source_key,
                "source_hash": source_hash,
                "normalized_text_hash": text_hash,
            }
        )
        keyed.append((split_key, row))
    keyed.sort(key=lambda item: (item[0], item[1]["source_key"]))
    output: list[dict[str, Any]] = []
    for index, (split_key, row) in enumerate(keyed):
        group = "KB_Member" if index < 1_000 else "True_Non_Member" if index < 2_000 else "Reserve"
        output.append(
            {
                "kind": "v23_source_split",
                "dataset": dataset,
                **row,
                "split_key_sha256": split_key,
                "split_index": index,
                "group": group,
            }
        )
    return output


def validate_index_allowlist(split_rows: Sequence[Mapping[str, Any]], *, allowed_group: str) -> None:
    if allowed_group not in {"KB_Member", "Reserve"}:
        raise RuntimeError("index_allowed_group_invalid")
    expected_count = 1_000 if allowed_group == "KB_Member" else 250
    if len(split_rows) != expected_count or any(row.get("group") != allowed_group for row in split_rows):
        raise RuntimeError("index_group_contamination")


def stage_status(
    project_root: str | Path = ".", *, stage: str | None = None
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    contract = load_execution_erratum(root)
    stages = contract["stage_order"]
    if stage is not None and stage not in stages:
        raise ValueError("stage_status_stage_invalid")
    active = validate_active_runtime(root)
    requested = [stage] if stage is not None else list(stages)
    rows: list[dict[str, Any]] = []
    for name in requested:
        if name == RESERVATION_STAGE:
            completion = (
                _reservation_directory(root, active["protocol_revision_id"])
                / "group_completion.json"
            )
            if not completion.is_file():
                rows.append(
                    {
                        "stage": name,
                        "status": "not_started",
                        "reason": "revision_reservation_group_missing",
                    }
                )
                continue
            try:
                validate_revision_reservation(project_root=root)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                rows.append({"stage": name, "status": "stale", "reason": str(error)})
            else:
                rows.append(
                    {
                        "stage": name,
                        "status": "native",
                        "reason": None,
                    }
                )
            continue
        if name == DEVELOPMENT_PILOT_STAGE:
            group_path = _development_gate_manifest_path(
                root, active["protocol_revision_id"]
            )
            if not group_path.is_file():
                started = [
                    dataset
                    for dataset in DATASET_ORDER
                    if (_resolve(DEVELOPMENT_SELECTION_DIRECTORY / dataset, root)
                        / "pilot_manifest.json").is_file()
                ]
                rows.append(
                    {
                        "stage": name,
                        "status": "not_started",
                        "reason": (
                            "development_pilot_group_incomplete:"
                            + ",".join(started)
                            if started
                            else "development_pilot_group_missing"
                        ),
                    }
                )
                continue
            try:
                validate_development_pilot_group(project_root=root)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                rows.append({"stage": name, "status": "stale", "reason": str(error)})
            else:
                rows.append(
                    {
                        "stage": name,
                        "status": "native",
                        "reason": None,
                    }
                )
            continue
        if name != "aggregate_df_precomputation":
            rows.append(
                {
                    "stage": name,
                    "status": "not_started",
                    "reason": "canonical_stage_artifact_missing",
                }
            )
            continue
        if any(
            not _resolve(
                AGGREGATE_DF_DIRECTORY / dataset / "df_manifest.json", root
            ).is_file()
            for dataset in DATASET_ORDER
        ):
            rows.append(
                {
                    "stage": name,
                    "status": "not_started",
                    "reason": "aggregate_df_group_incomplete",
                }
            )
            continue
        try:
            validations = [
                validate_aggregate_df(project_root=root, dataset=dataset)
                for dataset in DATASET_ORDER
            ]
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            rows.append(
                {"stage": name, "status": "stale", "reason": str(error)}
            )
        else:
            modes = {item["validation_mode"] for item in validations}
            if len(modes) != 1:
                raise RuntimeError("stage_status_aggregate_validation_mode_mixed")
            rows.append(
                {
                    "stage": name,
                    "status": modes.pop(),
                    "reason": None,
                    "stage_dependency_fingerprint": stage_identity(
                        project_root=root,
                        stage=name,
                        runtime_bundle_sha256=active["runtime_bundle_sha256"],
                    )["stage_dependency_fingerprint"],
                }
            )
    return {
        "status": "passed",
        "execution_revision": EXECUTION_REVISION,
        "execution_erratum_sha256": EXECUTION_ERRATUM_SHA256,
        "runtime_bundle_sha256": active["runtime_bundle_sha256"],
        "protocol_revision_id": active["protocol_revision_id"],
        "stages": rows,
        "source_pool_contents_read": False,
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }


def v23_status(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    bindings = validate_bootstrap_design_identity(root)
    load_execution_erratum(root)
    implementation_files = [
        "src/attack/restoration_first_v23.py",
        "src/prepare/restoration_first_v23.py",
        "src/utils/stage_identity.py",
        "src/evaluation/restoration_first_v23.py",
        "scripts/42_run_v23_restoration_first.py",
        "tests/test_restoration_first_v23.py",
    ]
    present = {path: _resolve(path, root).is_file() for path in implementation_files}
    bootstrap_artifacts_exist = any(
        (
            _resolve(path, root).exists()
            if path.suffix
            else _directory_has_entries(_resolve(path, root))
        )
        for path in (
            CONSUMPTION_LEDGER,
            RUNTIME_BUNDLE_DIRECTORY,
            PROTOCOL_REVISION_DIRECTORY,
            LEDGER_ANCHOR_DIRECTORY,
            BOOTSTRAP_CHECKPOINT_DIRECTORY,
        )
    )
    bootstrap: dict[str, Any] | None = None
    active: dict[str, Any] | None = None
    bootstrap_error: str | None = None
    if bootstrap_artifacts_exist:
        try:
            bootstrap = validate_runtime_bootstrap(root)
            active = validate_active_runtime(root)
        except (OSError, RuntimeError, ValueError) as error:
            bootstrap_error = str(error)
    frozen = active is not None
    runtime_identity = active or bootstrap or {}
    blocked = [
        "aggregate_df_precomputation",
        "revision_audit_reserve_snapshot_and_write_ahead_registration",
        "development_pilot_and_capacity_gate",
        "fresh_blind_audit",
        "formal_source_scan",
        "source_exclusive_split",
        "reserve_only_shadow_gate",
        "release_finalize",
        "luna_query_generation",
        "main_index_build_and_retriever_matrix",
        "matched_rag_and_llm_only_victim_runs",
        "parsing_scoring_and_source_level_evaluation",
    ]
    if not frozen:
        blocked.insert(0, "runtime_bundle_and_commit_freeze")
    elif active is not None:
        try:
            scoped = stage_status(root)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            pass
        else:
            blocked = [
                row["stage"]
                for row in scoped["stages"]
                if row["status"] not in {"native", "carried_forward"}
            ]
    pilot_started = _directory_has_entries(
        _resolve(DEVELOPMENT_SELECTION_DIRECTORY, root)
    ) or bool(
        active
        and _stage_authorization_paths(
            root,
            stage=DEVELOPMENT_PILOT_STAGE,
            runtime_bundle_sha256=active["runtime_bundle_sha256"],
        )
    )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "method_version": METHOD_VERSION,
        "specification_version": SPECIFICATION_VERSION,
        "execution_revision": EXECUTION_REVISION,
        "execution_erratum_sha256": EXECUTION_ERRATUM_SHA256,
        "status": (
            "runtime_frozen_downstream_blocked"
            if frozen
            else "runtime_bootstrap_partial_fail_closed"
            if bootstrap_error
            else "runtime_implemented_unfrozen"
            if all(present.values())
            else "runtime_implementation_partial"
        ),
        "design_manifest_sha256": bindings["design_manifest_sha256"],
        "implementation_files_present": present,
        "runtime_bundle_frozen": frozen,
        "runtime_bundle_sha256": runtime_identity.get("runtime_bundle_sha256"),
        "protocol_revision_id": runtime_identity.get("protocol_revision_id"),
        "bootstrap_validation_error": bootstrap_error,
        "pilot_started": pilot_started,
        "external_calls_performed": 0,
        "blocked_stages": blocked,
    }
