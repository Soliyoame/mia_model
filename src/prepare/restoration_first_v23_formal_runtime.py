"""PCV-MIA v23 formal runtime 的离线冻结与 fail-closed 守卫。"""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..utils.hash import sha256_file
from ..utils.io import load_yaml


FORMAL_RUNTIME_CONFIG_PATH = Path(
    "configs/restoration_first_v23_formal_runtime_r1.yaml"
)
FORMAL_RUNTIME_FREEZE_PATH = Path(
    "configs/restoration_first_v23_formal_runtime_r1.freeze.json"
)
FORMAL_RUNTIME_SPECIFICATION_VERSION = (
    "pcv-restoration-first-v23-formal-runtime-r1"
)
DATASET_ORDER = ("edgar", "enron", "pubmed")
BACKEND_ORDER = ("dense", "bm25", "hybrid")
GROUP_COUNTS = {"KB_Member": 1_000, "True_Non_Member": 1_000, "Reserve": 250}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_SELECTION_KEYS = frozenset(
    {
        "membership",
        "membership_label",
        "split",
        "group",
        "victim_response",
        "llm_only_response",
        "retriever_output",
        "retrieval_rank",
        "retrieval_score",
        "attack_score",
        "attack_auc",
        "auc",
    }
)

_CONFIG_FIELDS = {
    "protocol_version",
    "method_version",
    "specification_version",
    "status",
    "design",
    "frozen_r2",
    "formal_contract",
    "runtime_bundle",
    "authorization_boundary",
}
_FREEZE_FIELDS = {
    "kind",
    "protocol_version",
    "method_version",
    "specification_version",
    "status",
    "created_at",
    "formal_runtime_identity_sha256",
    "runtime_bundle_sha256",
    "config",
    "design",
    "code_commit",
    "runtime_snapshot",
    "environment",
    "scientific_upstream",
    "diagnostic_evidence",
    "verification_gate",
    "formal_contract",
    "authorization_boundary",
    "runtime_implemented",
    "runtime_frozen",
    "formal_test_started",
    "source_content_interpreted",
    "private_audit_key_read",
    "membership_read",
    "victim_or_llm_only_response_read",
    "retriever_output_read",
    "auc_read",
    "fresh_reserve_consumed",
    "packet_rebuilt",
    "external_calls_performed",
}
_SELECTED_SOURCE_FIELDS = {
    "kind",
    "selection_index",
    "dataset",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "source_order_rank",
    "ordered_pair_ids",
}
_SPLIT_ROW_FIELDS = {
    "kind",
    "dataset",
    "split_index",
    "split_key",
    "group",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "source_order_rank",
    "ordered_pair_ids",
}
_AUTHORIZATION_FIELDS = {
    "kind",
    "authorization_id",
    "formal_runtime_identity_sha256",
    "authorized_stage",
    "dataset",
    "backend",
    "run_role",
    "budget_kind",
    "budget_limit",
    "formal_test_allowed",
    "gpu_allowed",
    "api_allowed",
    "victim_allowed",
    "retriever_allowed",
    "external_calls_allowed",
    "user_authorization_record",
    "protocol_revision_id",
    "expected_prior_ledger_tip_sha256",
    "expected_prior_tip_anchor_sha256",
    "target_selected_source_count",
    "issued_at",
}
_FORMAL_SCAN_BUDGET_FIELDS = {
    "kind",
    "sequence",
    "authorization_id",
    "stage",
    "dataset",
    "operation_identity_sha256",
    "source_order_index",
    "source_key",
    "previous_row_sha256",
    "row_sha256",
    "charged_at",
}
_FORMAL_SCAN_RESULT_FIELDS = {
    "kind",
    "specification_version",
    "protocol_revision_id",
    "formal_runtime_identity_sha256",
    "authorization_id",
    "dataset",
    "scan_index",
    "source_order_rank",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "eligible",
    "selected_pairs",
    "fact_count",
    "candidate_count",
    "selection_candidate_pair_count",
    "rejection_reason_counts",
    "deterministic_rerun_hash_match",
    "external_calls_performed",
    "created_at",
    "source_result_sha256",
}
_FORMAL_PAIR_FIELDS = {
    "kind",
    "specification_version",
    "source_fact_specification_version",
    "selection_identity_sha256",
    "dataset",
    "source_key",
    "source_order_rank",
    "source_hash",
    "normalized_text_hash",
    "fact_signature",
    "relation_signature",
    "pair_id",
    "original_span",
    "original_entity",
    "counterfactual_entity",
    "effective_type",
    "semantic_subtype",
    "true_claim",
    "counterfactual_claim",
    "pair_order",
}
_STAGE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "formal_source_scan": {
        "budget_kind": "sources",
        "scope": "dataset",
        "backend": False,
        "run_role": "selector",
        "gpu_allowed": True,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "external_calls_allowed": False,
    },
    "source_exclusive_split": {
        "budget_kind": "none",
        "scope": "dataset",
        "backend": False,
        "run_role": "split",
        "gpu_allowed": False,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "external_calls_allowed": False,
    },
    "reserve_only_shadow_gate": {
        "budget_kind": "calls",
        "scope": "dataset",
        "backend": True,
        "run_role": "shadow_retrieval",
        "gpu_allowed": True,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": True,
        "external_calls_allowed": False,
    },
    "release_finalize": {
        "budget_kind": "none",
        "scope": "global",
        "backend": False,
        "run_role": "release",
        "gpu_allowed": False,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "external_calls_allowed": False,
    },
    "luna_query_generation": {
        "budget_kind": "calls",
        "scope": "dataset",
        "backend": False,
        "run_role": "query_generation",
        "gpu_allowed": False,
        "api_allowed": True,
        "victim_allowed": False,
        "retriever_allowed": False,
        "external_calls_allowed": True,
    },
    "main_index_build_and_retriever_matrix": {
        "budget_kind": "calls",
        "scope": "dataset",
        "backend": True,
        "run_role": "main_retrieval",
        "gpu_allowed": True,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": True,
        "external_calls_allowed": False,
    },
    "matched_rag_and_llm_only_victim_runs": {
        "budget_kind": "calls",
        "scope": "dataset",
        "backend": False,
        "run_role": "victim_generation",
        "gpu_allowed": True,
        "api_allowed": False,
        "victim_allowed": True,
        "retriever_allowed": False,
        "external_calls_allowed": False,
    },
    "parsing_scoring_and_source_level_evaluation": {
        "budget_kind": "none",
        "scope": "global",
        "backend": True,
        "run_role": "evaluation",
        "gpu_allowed": False,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "external_calls_allowed": False,
    },
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64_RE.fullmatch(value))


def _assert_exact_fields(
    value: Mapping[str, Any], expected: set[str], *, kind: str
) -> None:
    if set(value) != expected:
        raise RuntimeError(f"{kind}_schema_drift")


def _resolve(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    if ".." in candidate.parts:
        raise RuntimeError("formal_runtime_path_traversal")
    return (root / candidate).resolve()


def _relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError(f"formal_runtime_path_invalid:{field}")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"formal_runtime_path_invalid:{field}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"formal_runtime_json_root_invalid:{path}")
    return value


def _require_bound_file(root: Path, path_value: Any, expected_sha256: Any) -> Path:
    path = _resolve(_relative_path(path_value, field="bound_file"), root)
    if not _is_sha256(expected_sha256):
        raise RuntimeError(f"formal_runtime_bound_hash_invalid:{path_value}")
    if not path.is_file():
        raise RuntimeError(f"formal_runtime_bound_file_missing:{path_value}")
    if sha256_file(path) != expected_sha256:
        raise RuntimeError(f"formal_runtime_bound_file_drift:{path_value}")
    return path


def load_formal_runtime_config(
    project_root: str | Path = ".",
    *,
    config_path: str | Path = FORMAL_RUNTIME_CONFIG_PATH,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = _resolve(config_path, root)
    config = load_yaml(path)
    if not isinstance(config, Mapping):
        raise RuntimeError("formal_runtime_config_root_invalid")
    _assert_exact_fields(config, _CONFIG_FIELDS, kind="formal_runtime_config")
    if (
        config.get("protocol_version") != "pcv-mia-v23"
        or config.get("method_version")
        != "pcv-restoration-first-v23-formal-runtime"
        or config.get("specification_version")
        != FORMAL_RUNTIME_SPECIFICATION_VERSION
        or config.get("status") != "implementation_authorized_freeze_only"
    ):
        raise RuntimeError("formal_runtime_config_identity_drift")

    runtime = config.get("runtime_bundle")
    if not isinstance(runtime, Mapping):
        raise RuntimeError("formal_runtime_bundle_config_invalid")
    files = runtime.get("implementation_files")
    if (
        not isinstance(files, list)
        or not all(isinstance(item, str) and item for item in files)
        or files != sorted(files)
        or len(files) != len(set(files))
    ):
        raise RuntimeError("formal_runtime_file_closure_not_canonical")
    for index, item in enumerate(files):
        _relative_path(item, field=f"implementation_files.{index}")
    if runtime.get("snapshot_mode") != "exact_worktree_file_sha256_closure":
        raise RuntimeError("formal_runtime_snapshot_mode_drift")
    if runtime.get("clean_worktree_required") is not False:
        raise RuntimeError("formal_runtime_dirty_worktree_policy_drift")
    expected_python = runtime.get("expected_python_executable")
    if not isinstance(expected_python, str) or not expected_python:
        raise RuntimeError("formal_runtime_python_executable_missing")

    boundary = config.get("authorization_boundary")
    if not isinstance(boundary, Mapping):
        raise RuntimeError("formal_runtime_authorization_boundary_invalid")
    denied = (
        "formal_test_allowed",
        "gpu_long_task_allowed",
        "api_allowed",
        "victim_allowed",
        "llm_only_allowed",
        "retriever_allowed",
        "paid_calls_allowed",
        "membership_access_allowed",
        "victim_response_access_allowed",
        "retriever_output_access_allowed",
        "auc_access_allowed",
        "fresh_reserve_access_allowed",
        "packet_rebuild_allowed",
    )
    if any(boundary.get(field) is not False for field in denied):
        raise RuntimeError("formal_runtime_authorization_scope_expanded")
    if (
        boundary.get("local_offline_validation_allowed") is not True
        or boundary.get("external_calls_performed") != 0
    ):
        raise RuntimeError("formal_runtime_authorization_boundary_drift")

    contract = config.get("formal_contract")
    if not isinstance(contract, Mapping):
        raise RuntimeError("formal_runtime_contract_invalid")
    if (
        contract.get("dataset_order") != list(DATASET_ORDER)
        or contract.get("target_eligible_sources_per_dataset") != 2_250
        or contract.get("selected_pairs_per_source") != 3
        or contract.get("queries_per_pair") != 2
        or contract.get("rag_backends") != list(BACKEND_ORDER)
        or contract.get("split_counts") != GROUP_COUNTS
        or contract.get("main_index_allowed_group") != "KB_Member"
        or contract.get("shadow_index_allowed_group") != "Reserve"
        or contract.get("formal_scan_requires_canonical_human_blind_audit")
        is not False
        or contract.get("ai_diagnostic_may_satisfy_human_gate") is not False
    ):
        raise RuntimeError("formal_runtime_contract_drift")
    gate = contract.get("formal_scan_gate")
    expected_gate_fields = {
        "kind",
        "status",
        "packet_manifest_sha256",
        "ai_audit_identity_sha256",
        "ai_manifest_sha256",
        "ai_labels_sha256",
        "ai_diagnostic_remains_diagnostic_only",
        "ai_diagnostic_alone_accepted_as_formal_gate",
        "project_owner_human_verification_performed",
        "project_owner_human_verification_result",
        "project_owner_human_verification_attestation",
        "independent_human_blind_audit_performed",
        "separate_human_label_artifact_available",
        "cohen_kappa_claim_allowed",
        "combined_gate_accepted",
    }
    if not isinstance(gate, Mapping):
        raise RuntimeError("formal_runtime_verification_gate_invalid")
    _assert_exact_fields(gate, expected_gate_fields, kind="formal_runtime_gate")
    if (
        gate.get("kind")
        != "v23_ai_audit_plus_project_owner_human_verification_gate"
        or gate.get("status") != "passed"
        or gate.get("ai_diagnostic_remains_diagnostic_only") is not True
        or gate.get("ai_diagnostic_alone_accepted_as_formal_gate") is not False
        or gate.get("project_owner_human_verification_performed") is not True
        or gate.get("project_owner_human_verification_result")
        != "matches_bound_ai_audit_result"
        or gate.get("project_owner_human_verification_attestation")
        != "user_instruction_2026_08_24"
        or gate.get("independent_human_blind_audit_performed") is not False
        or gate.get("separate_human_label_artifact_available") is not False
        or gate.get("cohen_kappa_claim_allowed") is not False
        or gate.get("combined_gate_accepted") is not True
    ):
        raise RuntimeError("formal_runtime_verification_gate_drift")
    diagnostic = config["frozen_r2"]["ai_diagnostic"]
    packet = config["frozen_r2"]["blind_packet"]
    if (
        gate.get("packet_manifest_sha256") != packet["manifest_sha256"]
        or gate.get("ai_audit_identity_sha256")
        != diagnostic["audit_identity_sha256"]
        or gate.get("ai_manifest_sha256") != diagnostic["manifest_sha256"]
        or gate.get("ai_labels_sha256") != diagnostic["labels_sha256"]
    ):
        raise RuntimeError("formal_runtime_verification_gate_binding_drift")
    scan = contract.get("formal_source_scan")
    expected_scan = {
        "authorization_directory": "artifacts/v23/governance/run_authorizations",
        "budget_directory": "artifacts/v23/governance/authorization_budgets",
        "consumption_ledger_path": (
            "artifacts/v23/governance/consumed_source_ledger.jsonl"
        ),
        "ledger_anchor_directory": "artifacts/v23/governance/ledger_anchors",
        "formal_output_root": "artifacts/v23/formal",
        "formal_pair_output_root": "artifacts/v23/selection/formal",
        "reservation_batch_size": 1,
        "target_selected_source_count": 2_250,
        "pairs_per_selected_source": 3,
        "protocol_revision_namespace": "formal_runtime_identity_sha256",
        "first_dataset": "edgar",
        "first_dataset_maximum_source_reads": 3_710,
        "source_content_read_requires_durable_ledger_anchor": True,
        "stop_immediately_at_target": True,
    }
    if not isinstance(scan, Mapping) or dict(scan) != expected_scan:
        raise RuntimeError("formal_runtime_source_scan_contract_drift")
    return copy.deepcopy(dict(config))


def _logical_identity(value: Mapping[str, Any], field: str, expected: str) -> None:
    if value.get(field) != expected or not _is_sha256(expected):
        raise RuntimeError(f"formal_runtime_logical_identity_drift:{field}")


def validate_frozen_r2_evidence(
    project_root: str | Path = ".",
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """只核验公开 manifest/hash；不解析 packet 行或 AI label 内容。"""

    root = Path(project_root).resolve()
    loaded = dict(config) if config is not None else load_formal_runtime_config(root)
    frozen = loaded["frozen_r2"]

    preparation_binding = frozen["preparation_freeze"]
    preparation_path = _require_bound_file(
        root,
        preparation_binding["path"],
        preparation_binding["file_sha256"],
    )
    preparation = _read_json(preparation_path)
    _logical_identity(
        preparation,
        "freeze_identity_sha256",
        preparation_binding["identity_sha256"],
    )
    _logical_identity(
        preparation,
        "policy_freeze_identity_sha256",
        preparation_binding["policy_identity_sha256"],
    )
    if (
        preparation.get("execution_reservation_revision")
        != preparation_binding["execution_reservation_revision"]
        or preparation.get("external_calls_performed") != 0
    ):
        raise RuntimeError("formal_runtime_preparation_freeze_drift")

    compatibility_binding = frozen["compatibility_envelope"]
    compatibility_path = _require_bound_file(
        root,
        compatibility_binding["path"],
        compatibility_binding["file_sha256"],
    )
    compatibility = _read_json(compatibility_path)
    _logical_identity(
        compatibility,
        "compatibility_identity_sha256",
        compatibility_binding["identity_sha256"],
    )
    if (
        compatibility.get("freeze_identity_sha256")
        != preparation_binding["identity_sha256"]
        or compatibility.get("external_calls_performed") != 0
    ):
        raise RuntimeError("formal_runtime_compatibility_envelope_drift")

    dataset_summary: dict[str, Any] = {}
    for dataset in DATASET_ORDER:
        binding = frozen["datasets"][dataset]
        manifest_path = _require_bound_file(
            root, binding["manifest_path"], binding["manifest_sha256"]
        )
        manifest = _read_json(manifest_path)
        _logical_identity(
            manifest,
            "dataset_identity_sha256",
            binding["dataset_identity_sha256"],
        )
        expected_counts = {
            "evaluated_source_count": binding["evaluated_source_count"],
            "selected_source_count": binding["selected_source_count"],
            "selected_pair_count": binding["selected_pair_count"],
        }
        if (
            manifest.get("dataset") != dataset
            or manifest.get("freeze_identity_sha256")
            != preparation_binding["identity_sha256"]
            or manifest.get("status") != "passed"
            or manifest.get("external_calls_performed") != 0
            or any(manifest.get(key) != value for key, value in expected_counts.items())
        ):
            raise RuntimeError(f"formal_runtime_dataset_manifest_drift:{dataset}")
        dataset_summary[dataset] = {
            "manifest_sha256": binding["manifest_sha256"],
            "dataset_identity_sha256": binding["dataset_identity_sha256"],
            **expected_counts,
        }

    packet_binding = frozen["blind_packet"]
    packet_manifest_path = _require_bound_file(
        root, packet_binding["manifest_path"], packet_binding["manifest_sha256"]
    )
    packet_path = _require_bound_file(
        root, packet_binding["packet_path"], packet_binding["packet_sha256"]
    )
    packet_manifest = _read_json(packet_manifest_path)
    if (
        packet_manifest.get("kind") != "v23_blind_audit_packet_manifest"
        or packet_manifest.get("freeze_identity_sha256")
        != preparation_binding["identity_sha256"]
        or packet_manifest.get("packet_path") != packet_binding["packet_path"]
        or packet_manifest.get("packet_file_sha256")
        != packet_binding["packet_sha256"]
        or packet_manifest.get("packet_row_count") != packet_binding["row_count"]
        or packet_manifest.get("external_calls_performed") != 0
    ):
        raise RuntimeError("formal_runtime_packet_manifest_drift")
    if packet_path.stat().st_size <= 0:
        raise RuntimeError("formal_runtime_packet_empty")

    diagnostic_binding = frozen["ai_diagnostic"]
    authorization_path = _require_bound_file(
        root,
        diagnostic_binding["authorization_path"],
        diagnostic_binding["authorization_file_sha256"],
    )
    authorization = _read_json(authorization_path)
    _logical_identity(
        authorization,
        "authorization_id",
        diagnostic_binding["authorization_id"],
    )
    denied_auth_fields = (
        "human_audit_allowed",
        "private_key_access_allowed",
        "membership_access_allowed",
        "victim_allowed",
        "retriever_allowed",
        "api_allowed",
        "formal_experiment_allowed",
        "external_calls_allowed",
    )
    if (
        authorization.get("ai_audit_allowed") is not True
        or any(authorization.get(field) is not False for field in denied_auth_fields)
    ):
        raise RuntimeError("formal_runtime_ai_authorization_scope_drift")

    diagnostic_manifest_path = _require_bound_file(
        root,
        diagnostic_binding["manifest_path"],
        diagnostic_binding["manifest_sha256"],
    )
    _require_bound_file(
        root,
        diagnostic_binding["labels_path"],
        diagnostic_binding["labels_sha256"],
    )
    diagnostic = _read_json(diagnostic_manifest_path)
    _logical_identity(
        diagnostic,
        "audit_identity_sha256",
        diagnostic_binding["audit_identity_sha256"],
    )
    expected_label_counts = {
        "pass": diagnostic_binding["pass_count"],
        "uncertain": diagnostic_binding["uncertain_count"],
        "fail": diagnostic_binding["fail_count"],
    }
    diagnostic_denied = (
        "human_validation_performed",
        "human_audit_requested",
        "private_key_read",
        "membership_read",
        "victim_response_read",
        "retriever_output_read",
        "auc_read",
        "formal_experiment_allowed",
    )
    if (
        diagnostic.get("status") != diagnostic_binding["status"]
        or diagnostic.get("diagnostic_only") is not True
        or any(diagnostic.get(field) is not False for field in diagnostic_denied)
        or diagnostic.get("label_counts") != expected_label_counts
        or diagnostic.get("packet_manifest_sha256")
        != packet_binding["manifest_sha256"]
        or diagnostic.get("packet_file_sha256") != packet_binding["packet_sha256"]
        or diagnostic.get("labels_file_sha256")
        != diagnostic_binding["labels_sha256"]
        or diagnostic.get("external_calls_performed") != 0
        or diagnostic_binding.get("accepted_as_human_validation") is not False
        or diagnostic_binding.get("accepted_as_formal_gate") is not False
    ):
        raise RuntimeError("formal_runtime_ai_diagnostic_drift")

    return {
        "preparation_freeze_identity_sha256": preparation_binding["identity_sha256"],
        "preparation_freeze_manifest_sha256": preparation_binding["file_sha256"],
        "policy_freeze_identity_sha256": preparation_binding["policy_identity_sha256"],
        "execution_reservation_revision": preparation_binding[
            "execution_reservation_revision"
        ],
        "compatibility_identity_sha256": compatibility_binding["identity_sha256"],
        "datasets": dataset_summary,
        "packet_manifest_sha256": packet_binding["manifest_sha256"],
        "packet_file_sha256": packet_binding["packet_sha256"],
        "packet_row_count": packet_binding["row_count"],
        "ai_authorization_id": diagnostic_binding["authorization_id"],
        "ai_audit_identity_sha256": diagnostic_binding["audit_identity_sha256"],
        "ai_manifest_sha256": diagnostic_binding["manifest_sha256"],
        "ai_labels_sha256": diagnostic_binding["labels_sha256"],
        "ai_label_counts": expected_label_counts,
        "ai_diagnostic_only": True,
        "human_validation_performed": False,
        "ai_evidence_accepted_as_formal_gate": False,
        "packet_rows_parsed": False,
        "ai_label_rows_parsed": False,
        "external_calls_performed": 0,
    }


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip().lower()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RuntimeError("formal_runtime_git_head_unavailable")
    return value


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def _runtime_files(root: Path, config: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in config["runtime_bundle"]["implementation_files"]:
        path = _resolve(value, root)
        if not path.is_file():
            raise RuntimeError(f"formal_runtime_implementation_file_missing:{value}")
        rows.append({"path": value, "sha256": sha256_file(path)})
    return rows


def _runtime_bundle_identity(
    *,
    design_manifest_sha256: str,
    code_commit: str,
    dependency_lock_sha256: str,
    files: Sequence[Mapping[str, str]],
) -> str:
    return canonical_sha256(
        {
            "kind": "v23_formal_runtime_bundle",
            "specification_version": FORMAL_RUNTIME_SPECIFICATION_VERSION,
            "design_manifest_sha256": design_manifest_sha256,
            "code_commit": code_commit,
            "dependency_lock_sha256": dependency_lock_sha256,
            "files": list(files),
        }
    )


def formal_runtime_identity(manifest: Mapping[str, Any]) -> str:
    payload = {
        key: copy.deepcopy(value)
        for key, value in manifest.items()
        if key not in {"created_at", "formal_runtime_identity_sha256"}
    }
    return canonical_sha256(payload)


def build_formal_runtime_freeze(
    project_root: str | Path = ".",
    *,
    code_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_formal_runtime_config(root)
    config_path = _resolve(FORMAL_RUNTIME_CONFIG_PATH, root)
    config_sha256 = sha256_file(config_path)
    design = config["design"]
    _require_bound_file(root, design["config_path"], design["config_sha256"])
    design_manifest_path = _require_bound_file(
        root, design["manifest_path"], design["manifest_sha256"]
    )
    preregistration_path = _require_bound_file(
        root,
        design["preregistration_path"],
        design["preregistration_sha256"],
    )
    design_manifest = _read_json(design_manifest_path)
    if (
        design_manifest.get("specification_version")
        != design["specification_version"]
        or design_manifest.get("config", {}).get("sha256")
        != design["config_sha256"]
        or design_manifest.get("preregistration", {}).get("sha256")
        != design["preregistration_sha256"]
    ):
        raise RuntimeError("formal_runtime_design_manifest_drift")

    evidence = validate_frozen_r2_evidence(root, config=config)
    files = _runtime_files(root, config)
    dependency_lock_path = config["runtime_bundle"]["dependency_lock_path"]
    dependency_lock_sha256 = sha256_file(_resolve(dependency_lock_path, root))
    model_lock_path = config["runtime_bundle"]["model_lock_path"]
    model_lock_sha256 = sha256_file(_resolve(model_lock_path, root))
    expected_python = Path(
        config["runtime_bundle"]["expected_python_executable"]
    ).resolve()
    actual_python = Path(sys.executable).resolve()
    if str(actual_python).casefold() != str(expected_python).casefold():
        raise RuntimeError("formal_runtime_python_executable_drift")
    commit = code_commit or _git_head(root)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("formal_runtime_code_commit_invalid")
    runtime_bundle_sha256 = _runtime_bundle_identity(
        design_manifest_sha256=design["manifest_sha256"],
        code_commit=commit,
        dependency_lock_sha256=dependency_lock_sha256,
        files=files,
    )

    scientific_upstream = {
        key: copy.deepcopy(value)
        for key, value in evidence.items()
        if not key.startswith("ai_")
        and key not in {"human_validation_performed", "ai_label_rows_parsed"}
    }
    diagnostic_evidence = {
        "kind": "v23_ai_only_diagnostic_evidence_binding",
        "authorization_id": evidence["ai_authorization_id"],
        "audit_identity_sha256": evidence["ai_audit_identity_sha256"],
        "manifest_sha256": evidence["ai_manifest_sha256"],
        "labels_sha256": evidence["ai_labels_sha256"],
        "label_counts": evidence["ai_label_counts"],
        "diagnostic_only": True,
        "human_validation_performed": False,
        "accepted_as_formal_gate": False,
    }
    verification_gate = copy.deepcopy(config["formal_contract"]["formal_scan_gate"])
    manifest: dict[str, Any] = {
        "kind": "v23_formal_runtime_freeze",
        "protocol_version": config["protocol_version"],
        "method_version": config["method_version"],
        "specification_version": config["specification_version"],
        "status": "formal_runtime_frozen_gate_passed_awaiting_formal_test_authorization",
        "created_at": created_at or _utc_now(),
        "formal_runtime_identity_sha256": "",
        "runtime_bundle_sha256": runtime_bundle_sha256,
        "config": {
            "path": FORMAL_RUNTIME_CONFIG_PATH.as_posix(),
            "sha256": config_sha256,
        },
        "design": {
            "config_path": design["config_path"],
            "config_sha256": design["config_sha256"],
            "manifest_path": design["manifest_path"],
            "manifest_sha256": design["manifest_sha256"],
            "specification_version": design["specification_version"],
            "preregistration_path": str(preregistration_path.relative_to(root)).replace(
                "\\", "/"
            ),
            "preregistration_sha256": design["preregistration_sha256"],
        },
        "code_commit": commit,
        "runtime_snapshot": {
            "mode": config["runtime_bundle"]["snapshot_mode"],
            "code_commit_role": config["runtime_bundle"]["code_commit_role"],
            "clean_worktree_required": False,
            "files": files,
        },
        "environment": {
            "python_executable": str(Path(sys.executable).resolve()).replace("\\", "/"),
            "python_version": platform.python_version(),
            "dependency_lock_path": dependency_lock_path,
            "dependency_lock_sha256": dependency_lock_sha256,
            "model_lock_path": model_lock_path,
            "model_lock_sha256": model_lock_sha256,
            "numpy_version": _package_version("numpy"),
            "gpu_runtime_loaded": False,
            "model_runtime_loaded": False,
        },
        "scientific_upstream": scientific_upstream,
        "diagnostic_evidence": diagnostic_evidence,
        "verification_gate": verification_gate,
        "formal_contract": copy.deepcopy(config["formal_contract"]),
        "authorization_boundary": copy.deepcopy(config["authorization_boundary"]),
        "runtime_implemented": True,
        "runtime_frozen": True,
        "formal_test_started": False,
        "source_content_interpreted": False,
        "private_audit_key_read": False,
        "membership_read": False,
        "victim_or_llm_only_response_read": False,
        "retriever_output_read": False,
        "auc_read": False,
        "fresh_reserve_consumed": False,
        "packet_rebuilt": False,
        "external_calls_performed": 0,
    }
    manifest["formal_runtime_identity_sha256"] = formal_runtime_identity(manifest)
    _assert_exact_fields(manifest, _FREEZE_FIELDS, kind="formal_runtime_freeze")
    return manifest


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(value).encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RuntimeError(f"formal_runtime_freeze_exists:{path}") from exc


def freeze_formal_runtime(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_formal_runtime_config(root)
    freeze_path = _resolve(config["runtime_bundle"]["freeze_path"], root)
    if freeze_path.exists():
        return validate_formal_runtime_freeze(root)
    manifest = build_formal_runtime_freeze(root)
    _write_new_json(freeze_path, manifest)
    return validate_formal_runtime_freeze(root)


def validate_formal_runtime_freeze(
    project_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_formal_runtime_config(root)
    freeze_path = _resolve(config["runtime_bundle"]["freeze_path"], root)
    if not freeze_path.is_file():
        raise RuntimeError("formal_runtime_freeze_missing")
    manifest = _read_json(freeze_path)
    _assert_exact_fields(manifest, _FREEZE_FIELDS, kind="formal_runtime_freeze")
    if (
        manifest.get("kind") != "v23_formal_runtime_freeze"
        or manifest.get("specification_version")
        != FORMAL_RUNTIME_SPECIFICATION_VERSION
        or manifest.get("status")
        != "formal_runtime_frozen_gate_passed_awaiting_formal_test_authorization"
        or manifest.get("runtime_implemented") is not True
        or manifest.get("runtime_frozen") is not True
        or manifest.get("formal_test_started") is not False
        or manifest.get("external_calls_performed") != 0
    ):
        raise RuntimeError("formal_runtime_freeze_state_drift")
    identity = manifest.get("formal_runtime_identity_sha256")
    if not _is_sha256(identity) or formal_runtime_identity(manifest) != identity:
        raise RuntimeError("formal_runtime_freeze_identity_drift")
    current = build_formal_runtime_freeze(
        root,
        code_commit=manifest["code_commit"],
        created_at=manifest["created_at"],
    )
    if current != manifest:
        raise RuntimeError("formal_runtime_current_binding_drift")
    return {
        "status": "passed",
        "formal_runtime_identity_sha256": identity,
        "runtime_bundle_sha256": manifest["runtime_bundle_sha256"],
        "freeze_manifest_sha256": sha256_file(freeze_path),
        "freeze_path": str(freeze_path.relative_to(root)).replace("\\", "/"),
        "runtime_file_count": len(manifest["runtime_snapshot"]["files"]),
        "formal_test_started": False,
        "human_blind_audit_gate_required": False,
        "ai_diagnostic_accepted_as_formal_gate": False,
        "ai_plus_project_owner_verification_gate_passed": True,
        "cohen_kappa_claim_allowed": False,
        "source_content_interpreted": False,
        "external_calls_performed": 0,
    }


def _formal_scan_gate(config: Mapping[str, Any]) -> dict[str, Any]:
    gate = copy.deepcopy(config["formal_contract"]["formal_scan_gate"])
    return {
        "status": gate["status"],
        "satisfied": gate["combined_gate_accepted"],
        "kind": gate["kind"],
        "ai_diagnostic_remains_diagnostic_only": gate[
            "ai_diagnostic_remains_diagnostic_only"
        ],
        "project_owner_human_verification_performed": gate[
            "project_owner_human_verification_performed"
        ],
        "independent_human_blind_audit_performed": gate[
            "independent_human_blind_audit_performed"
        ],
        "cohen_kappa_claim_allowed": gate["cohen_kappa_claim_allowed"],
    }


def status(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_formal_runtime_config(root)
    freeze_path = _resolve(config["runtime_bundle"]["freeze_path"], root)
    if not freeze_path.is_file():
        return {
            "status": "formal_runtime_not_frozen",
            "formal_runtime_frozen": False,
            "formal_test_started": False,
            "external_calls_performed": 0,
        }
    validation = validate_formal_runtime_freeze(root)
    formal_scan_gate = _formal_scan_gate(config)
    scan = formal_source_scan_status(root, dataset="edgar")
    if scan["completed"]:
        runtime_status = "formal_source_scan_edgar_passed_awaiting_next_authorization"
    elif scan["started"]:
        runtime_status = "formal_source_scan_edgar_running_or_resumable"
    else:
        runtime_status = (
            "formal_runtime_frozen_gate_passed_awaiting_formal_test_authorization"
        )
    return {
        "status": runtime_status,
        "formal_runtime_frozen": True,
        "formal_runtime_identity_sha256": validation[
            "formal_runtime_identity_sha256"
        ],
        "runtime_bundle_sha256": validation["runtime_bundle_sha256"],
        "freeze_manifest_sha256": validation["freeze_manifest_sha256"],
        "formal_scan_gate": formal_scan_gate,
        "human_blind_audit_gate_required": False,
        "ai_diagnostic_accepted_as_formal_gate": False,
        "ai_plus_project_owner_verification_gate_passed": True,
        "cohen_kappa_claim_allowed": False,
        "formal_source_scan": scan,
        "formal_test_started": scan["started"],
        "gpu_long_task_started": False,
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_calls_performed": 0,
        "external_calls_performed": 0,
    }


def reject_forbidden_formal_inputs(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeError(f"formal_input_non_string_key:{path}")
            normalized = key.casefold()
            if normalized in FORBIDDEN_SELECTION_KEYS:
                raise RuntimeError(f"formal_input_forbidden_field:{path}.{key}")
            reject_forbidden_formal_inputs(item, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            reject_forbidden_formal_inputs(item, path=f"{path}[{index}]")


def _validate_selected_source(row: Mapping[str, Any], dataset: str) -> None:
    _assert_exact_fields(row, _SELECTED_SOURCE_FIELDS, kind="formal_selected_source")
    reject_forbidden_formal_inputs(row)
    pair_ids = row.get("ordered_pair_ids")
    if (
        row.get("kind") != "v23_formal_selected_source"
        or row.get("dataset") != dataset
        or isinstance(row.get("selection_index"), bool)
        or not isinstance(row.get("selection_index"), int)
        or isinstance(row.get("source_order_rank"), bool)
        or not isinstance(row.get("source_order_rank"), int)
        or not isinstance(row.get("source_key"), str)
        or not row.get("source_key")
        or not _is_sha256(row.get("source_hash"))
        or not _is_sha256(row.get("normalized_text_hash"))
        or not isinstance(pair_ids, list)
        or len(pair_ids) != 3
        or len(set(pair_ids)) != 3
        or not all(_is_sha256(item) for item in pair_ids)
    ):
        raise RuntimeError("formal_selected_source_row_invalid")


def _split_key(row: Mapping[str, Any], *, selection_seed: int) -> str:
    return canonical_sha256(
        {
            "kind": "v23_formal_split",
            "specification_version": "pcv-restoration-first-v23-design-r6",
            "selection_seed": selection_seed,
            "dataset": row["dataset"],
            "source_key": row["source_key"],
            "source_hash": row["source_hash"],
            "normalized_text_hash": row["normalized_text_hash"],
        }
    )


def freeze_source_exclusive_split(
    selected_sources: Sequence[Mapping[str, Any]],
    *,
    dataset: str,
    selection_seed: int = 42,
) -> list[dict[str, Any]]:
    if dataset not in DATASET_ORDER or selection_seed != 42:
        raise RuntimeError("formal_split_scope_invalid")
    if len(selected_sources) != 2_250:
        raise RuntimeError("formal_split_source_count_invalid")
    source_keys: set[str] = set()
    source_hashes: set[str] = set()
    normalized_hashes: set[str] = set()
    pair_ids: set[str] = set()
    keyed: list[tuple[str, Mapping[str, Any]]] = []
    for expected_index, row in enumerate(selected_sources):
        _validate_selected_source(row, dataset)
        if row["selection_index"] != expected_index:
            raise RuntimeError("formal_selected_source_order_invalid")
        if (
            row["source_key"] in source_keys
            or row["source_hash"] in source_hashes
            or row["normalized_text_hash"] in normalized_hashes
            or pair_ids.intersection(row["ordered_pair_ids"])
        ):
            raise RuntimeError("formal_split_source_or_pair_overlap")
        source_keys.add(row["source_key"])
        source_hashes.add(row["source_hash"])
        normalized_hashes.add(row["normalized_text_hash"])
        pair_ids.update(row["ordered_pair_ids"])
        keyed.append((_split_key(row, selection_seed=selection_seed), row))
    keyed.sort(key=lambda item: (item[0], item[1]["source_key"]))

    output: list[dict[str, Any]] = []
    for split_index, (split_key, source) in enumerate(keyed):
        group = (
            "KB_Member"
            if split_index < 1_000
            else "True_Non_Member"
            if split_index < 2_000
            else "Reserve"
        )
        output.append(
            {
                "kind": "v23_source_split_row",
                "dataset": dataset,
                "split_index": split_index,
                "split_key": split_key,
                "group": group,
                "source_key": source["source_key"],
                "source_hash": source["source_hash"],
                "normalized_text_hash": source["normalized_text_hash"],
                "source_order_rank": source["source_order_rank"],
                "ordered_pair_ids": list(source["ordered_pair_ids"]),
            }
        )
    validate_split_rows(output, dataset=dataset)
    return output


def validate_split_rows(
    rows: Sequence[Mapping[str, Any]], *, dataset: str
) -> dict[str, Any]:
    if len(rows) != 2_250 or dataset not in DATASET_ORDER:
        raise RuntimeError("formal_split_rows_count_invalid")
    group_counts = {group: 0 for group in GROUP_COUNTS}
    seen = {"source_key": set(), "source_hash": set(), "normalized_text_hash": set()}
    previous_order_key: tuple[str, str] | None = None
    for index, row in enumerate(rows):
        _assert_exact_fields(row, _SPLIT_ROW_FIELDS, kind="formal_split_row")
        expected_group = (
            "KB_Member"
            if index < 1_000
            else "True_Non_Member"
            if index < 2_000
            else "Reserve"
        )
        expected_split_key = _split_key(row, selection_seed=42)
        order_key = (str(row.get("split_key")), str(row.get("source_key")))
        if (
            row.get("kind") != "v23_source_split_row"
            or row.get("dataset") != dataset
            or row.get("split_index") != index
            or not _is_sha256(row.get("split_key"))
            or row.get("split_key") != expected_split_key
            or row.get("group") != expected_group
        ):
            raise RuntimeError("formal_split_row_invalid")
        if previous_order_key is not None and order_key < previous_order_key:
            raise RuntimeError("formal_split_order_invalid")
        previous_order_key = order_key
        for field in seen:
            value = row.get(field)
            if value in seen[field]:
                raise RuntimeError(f"formal_split_overlap:{field}")
            seen[field].add(value)
        group_counts[row["group"]] += 1
    if group_counts != GROUP_COUNTS:
        raise RuntimeError("formal_split_group_counts_invalid")
    return {
        "status": "passed",
        "dataset": dataset,
        "source_count": 2_250,
        "group_counts": group_counts,
        "source_exclusive": True,
    }


def validate_cross_dataset_source_exclusivity(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    if set(rows_by_dataset) != set(DATASET_ORDER):
        raise RuntimeError("formal_cross_dataset_scope_invalid")
    seen_source_hashes: set[str] = set()
    seen_normalized_hashes: set[str] = set()
    for dataset in DATASET_ORDER:
        validate_split_rows(rows_by_dataset[dataset], dataset=dataset)
        source_hashes = {str(row["source_hash"]) for row in rows_by_dataset[dataset]}
        normalized_hashes = {
            str(row["normalized_text_hash"]) for row in rows_by_dataset[dataset]
        }
        if seen_source_hashes.intersection(source_hashes):
            raise RuntimeError("formal_cross_dataset_source_hash_overlap")
        if seen_normalized_hashes.intersection(normalized_hashes):
            raise RuntimeError("formal_cross_dataset_normalized_text_hash_overlap")
        seen_source_hashes.update(source_hashes)
        seen_normalized_hashes.update(normalized_hashes)


def validate_index_allowlist(
    split_rows: Sequence[Mapping[str, Any]], *, allowed_group: str
) -> dict[str, Any]:
    if allowed_group not in {"KB_Member", "Reserve"}:
        raise RuntimeError("formal_index_allowed_group_invalid")
    expected = GROUP_COUNTS[allowed_group]
    if len(split_rows) != expected:
        raise RuntimeError("formal_index_source_count_invalid")
    seen: set[str] = set()
    for row in split_rows:
        _assert_exact_fields(row, _SPLIT_ROW_FIELDS, kind="formal_index_split_row")
        if row.get("group") != allowed_group:
            raise RuntimeError("formal_index_group_contamination")
        source_key = row.get("source_key")
        if not isinstance(source_key, str) or not source_key or source_key in seen:
            raise RuntimeError("formal_index_source_identity_invalid")
        seen.add(source_key)
    return {
        "status": "passed",
        "allowed_group": allowed_group,
        "source_count": expected,
        "main_index": allowed_group == "KB_Member",
        "shadow_index": allowed_group == "Reserve",
    }


def _authorization_identity(value: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: copy.deepcopy(item) for key, item in value.items() if key != "authorization_id"}
    )


def validate_formal_stage_authorization(
    value: Mapping[str, Any],
    *,
    formal_runtime_identity_sha256: str,
    stage: str,
    dataset: str | None,
    backend: str | None,
) -> dict[str, Any]:
    _assert_exact_fields(value, _AUTHORIZATION_FIELDS, kind="formal_stage_authorization")
    requirement = _STAGE_REQUIREMENTS.get(stage)
    if requirement is None:
        raise RuntimeError("formal_stage_not_supported")
    if (
        value.get("kind") != "v23_formal_stage_authorization"
        or value.get("formal_runtime_identity_sha256")
        != formal_runtime_identity_sha256
        or value.get("protocol_revision_id") != formal_runtime_identity_sha256
        or value.get("authorized_stage") != stage
        or value.get("formal_test_allowed") is not True
        or not isinstance(value.get("user_authorization_record"), str)
        or not value.get("user_authorization_record")
        or not _is_sha256(value.get("expected_prior_ledger_tip_sha256"))
        or not _is_sha256(value.get("expected_prior_tip_anchor_sha256"))
        or not _is_sha256(value.get("authorization_id"))
        or _authorization_identity(value) != value.get("authorization_id")
    ):
        raise RuntimeError("formal_stage_authorization_identity_drift")
    expected_dataset = dataset if requirement["scope"] == "dataset" else None
    expected_backend = backend if requirement["backend"] else None
    if requirement["scope"] == "dataset" and dataset not in DATASET_ORDER:
        raise RuntimeError("formal_stage_authorization_dataset_invalid")
    if requirement["backend"] and backend not in BACKEND_ORDER:
        raise RuntimeError("formal_stage_authorization_backend_invalid")
    if value.get("dataset") != expected_dataset or value.get("backend") != expected_backend:
        raise RuntimeError("formal_stage_authorization_scope_drift")
    for field in (
        "run_role",
        "budget_kind",
        "gpu_allowed",
        "api_allowed",
        "victim_allowed",
        "retriever_allowed",
        "external_calls_allowed",
    ):
        if value.get(field) != requirement[field]:
            raise RuntimeError(f"formal_stage_authorization_capability_drift:{field}")
    budget_limit = value.get("budget_limit")
    if isinstance(budget_limit, bool) or not isinstance(budget_limit, int):
        raise RuntimeError("formal_stage_authorization_budget_invalid")
    if requirement["budget_kind"] == "none":
        if budget_limit != 0:
            raise RuntimeError("formal_stage_authorization_none_budget_nonzero")
    elif budget_limit <= 0:
        raise RuntimeError("formal_stage_authorization_budget_not_positive")
    target = value.get("target_selected_source_count")
    if stage == "formal_source_scan":
        if target != 2_250:
            raise RuntimeError("formal_stage_authorization_target_drift")
    elif target != 0:
        raise RuntimeError("formal_stage_authorization_non_scan_target_nonzero")
    return copy.deepcopy(dict(value))


def assert_budget_available(
    authorization: Mapping[str, Any],
    *,
    charges_already_recorded: int,
    charge_amount: int = 1,
) -> dict[str, int]:
    limit = authorization.get("budget_limit")
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or isinstance(charges_already_recorded, bool)
        or not isinstance(charges_already_recorded, int)
        or isinstance(charge_amount, bool)
        or not isinstance(charge_amount, int)
        or charges_already_recorded < 0
        or charge_amount <= 0
    ):
        raise RuntimeError("formal_budget_state_invalid")
    if authorization.get("budget_kind") == "none":
        raise RuntimeError("formal_budget_charge_forbidden")
    if charges_already_recorded + charge_amount > limit:
        raise RuntimeError("formal_budget_exhausted_before_operation")
    return {
        "charges_after": charges_already_recorded + charge_amount,
        "remaining": limit - charges_already_recorded - charge_amount,
    }


def _formal_scan_contract(config: Mapping[str, Any]) -> Mapping[str, Any]:
    value = config["formal_contract"]["formal_source_scan"]
    if not isinstance(value, Mapping):
        raise RuntimeError("formal_source_scan_contract_missing")
    return value


def _write_or_validate_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.is_file():
        if _read_json(path) != dict(value):
            raise RuntimeError(f"formal_artifact_identity_drift:{path}")
        return
    _write_new_json(path, value)


def _write_or_validate_jsonl(
    path: Path, rows: Sequence[Mapping[str, Any]]
) -> None:
    payload = "".join(canonical_json(dict(row)) + "\n" for row in rows).encode(
        "utf-8"
    )
    if path.is_file():
        if path.read_bytes() != payload:
            raise RuntimeError(f"formal_artifact_identity_drift:{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _formal_scan_paths(
    root: Path,
    config: Mapping[str, Any],
    *,
    protocol_revision_id: str,
    dataset: str,
) -> dict[str, Path]:
    contract = _formal_scan_contract(config)
    directory = _resolve(
        Path(str(contract["formal_output_root"])) / protocol_revision_id / dataset,
        root,
    )
    pair_directory = _resolve(
        Path(str(contract["formal_pair_output_root"]))
        / protocol_revision_id
        / dataset,
        root,
    )
    return {
        "directory": directory,
        "lock": directory / ".formal-source-scan.lock",
        "exclusion_snapshot": directory / "formal_exclusion_snapshot.json",
        "source_results": directory / "source_results",
        "reservation_plans": directory / "reservation_plans",
        "selected_sources": directory / "selected_sources.jsonl",
        "selected_manifest": directory / "selected_source_set_manifest.json",
        "selected_pairs": pair_directory / "selected_pairs.jsonl",
    }


def _governance_state(
    root: Path, config: Mapping[str, Any]
) -> tuple[Any, dict[str, Any], Path, list[dict[str, Any]]]:
    from . import restoration_first_v23_fresh_audit_preparation_r2 as governance

    governance_config = governance.load_preparation_config(root)
    contract = _formal_scan_contract(config)
    ledger_path = _resolve(str(contract["consumption_ledger_path"]), root)
    configured_ledger = _resolve(
        str(governance_config["reserve_group"]["ledger_path"]), root
    )
    configured_anchors = _resolve(
        str(governance_config["reserve_group"]["ledger_anchor_directory"]), root
    )
    if (
        ledger_path != configured_ledger
        or _resolve(str(contract["ledger_anchor_directory"]), root)
        != configured_anchors
    ):
        raise RuntimeError("formal_source_scan_governance_path_drift")
    rows = governance._read_ledger(ledger_path)
    return governance, governance_config, ledger_path, rows


def _ledger_anchor(
    root: Path,
    governance: Any,
    governance_config: Mapping[str, Any],
    tip: str,
) -> tuple[Path, str]:
    path = governance._find_anchor(root, governance_config, tip)
    value = _read_json(path)
    if value.get("ledger_tip_sha256") != tip:
        raise RuntimeError("formal_source_scan_ledger_anchor_drift")
    return path, sha256_file(path)


def prepare_formal_source_scan_authorization(
    *,
    project_root: str | Path = ".",
    dataset: str,
    budget_limit: int,
    user_authorization_record: str,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_formal_runtime_config(root)
    freeze = validate_formal_runtime_freeze(root)
    gate = _formal_scan_gate(config)
    contract = _formal_scan_contract(config)
    if gate["satisfied"] is not True:
        raise RuntimeError("formal_source_scan_gate_not_satisfied")
    if dataset != contract["first_dataset"] or dataset != DATASET_ORDER[0]:
        raise RuntimeError("formal_source_scan_first_dataset_required")
    if (
        isinstance(budget_limit, bool)
        or not isinstance(budget_limit, int)
        or budget_limit != contract["first_dataset_maximum_source_reads"]
    ):
        raise RuntimeError("formal_source_scan_budget_must_equal_frozen_maximum")
    if not isinstance(user_authorization_record, str) or not user_authorization_record:
        raise RuntimeError("formal_source_scan_user_authorization_missing")

    governance, governance_config, _ledger_path, rows = _governance_state(
        root, config
    )
    if any(row.get("role") == "formal_scan_viewed" for row in rows[1:]):
        raise RuntimeError("formal_source_scan_prior_attempt_exists")
    prior_tip = str(rows[-1]["row_sha256"])
    _anchor_path, anchor_sha256 = _ledger_anchor(
        root, governance, governance_config, prior_tip
    )

    from . import restoration_first_v23 as development

    design = development.load_design_config(root)
    pool = development._pool_contract(design, dataset)
    consumed_keys = {
        str(row["source_key"])
        for row in rows[1:]
        if row.get("dataset") == dataset
    }
    available = int(pool["source_count"]) - len(consumed_keys)
    if available != budget_limit:
        raise RuntimeError("formal_source_scan_available_budget_drift")

    runtime_identity = freeze["formal_runtime_identity_sha256"]
    authorization: dict[str, Any] = {
        "kind": "v23_formal_stage_authorization",
        "authorization_id": "",
        "formal_runtime_identity_sha256": runtime_identity,
        "protocol_revision_id": runtime_identity,
        "authorized_stage": "formal_source_scan",
        "dataset": dataset,
        "backend": None,
        "run_role": "selector",
        "budget_kind": "sources",
        "budget_limit": budget_limit,
        "target_selected_source_count": contract["target_selected_source_count"],
        "formal_test_allowed": True,
        "gpu_allowed": True,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "external_calls_allowed": False,
        "user_authorization_record": user_authorization_record,
        "expected_prior_ledger_tip_sha256": prior_tip,
        "expected_prior_tip_anchor_sha256": anchor_sha256,
        "issued_at": _utc_now(),
    }
    authorization["authorization_id"] = _authorization_identity(authorization)
    validate_formal_stage_authorization(
        authorization,
        formal_runtime_identity_sha256=runtime_identity,
        stage="formal_source_scan",
        dataset=dataset,
        backend=None,
    )
    directory = _resolve(str(contract["authorization_directory"]), root)
    path = directory / f"{authorization['authorization_id']}.json"
    _write_new_json(path, authorization)
    return {
        "status": "passed",
        "authorization_id": authorization["authorization_id"],
        "authorization_path": str(path.relative_to(root)).replace("\\", "/"),
        "formal_runtime_identity_sha256": runtime_identity,
        "dataset": dataset,
        "budget_limit": budget_limit,
        "gpu_allowed": True,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "external_calls_allowed": False,
    }


def validate_formal_source_scan_authorization(
    *,
    project_root: str | Path = ".",
    authorization_path: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_formal_runtime_config(root)
    freeze = validate_formal_runtime_freeze(root)
    contract = _formal_scan_contract(config)
    path = _resolve(authorization_path, root)
    directory = _resolve(str(contract["authorization_directory"]), root)
    try:
        path.relative_to(directory)
    except ValueError as error:
        raise RuntimeError("formal_source_scan_authorization_path_invalid") from error
    authorization = _read_json(path)
    dataset = authorization.get("dataset")
    validated = validate_formal_stage_authorization(
        authorization,
        formal_runtime_identity_sha256=freeze["formal_runtime_identity_sha256"],
        stage="formal_source_scan",
        dataset=str(dataset),
        backend=None,
    )
    if (
        path.name != f"{validated['authorization_id']}.json"
        or dataset != contract["first_dataset"]
        or validated["budget_limit"]
        != contract["first_dataset_maximum_source_reads"]
    ):
        raise RuntimeError("formal_source_scan_authorization_binding_drift")

    governance, governance_config, _ledger_path, rows = _governance_state(
        root, config
    )
    prior_matches = [
        index
        for index, row in enumerate(rows)
        if row.get("row_sha256")
        == validated["expected_prior_ledger_tip_sha256"]
    ]
    if len(prior_matches) != 1:
        raise RuntimeError("formal_source_scan_authorization_prior_tip_missing")
    _anchor_path, anchor_sha256 = _ledger_anchor(
        root,
        governance,
        governance_config,
        validated["expected_prior_ledger_tip_sha256"],
    )
    if anchor_sha256 != validated["expected_prior_tip_anchor_sha256"]:
        raise RuntimeError("formal_source_scan_authorization_anchor_drift")
    for row in rows[prior_matches[0] + 1 :]:
        if (
            row.get("role") != "formal_scan_viewed"
            or row.get("attempt_id") != validated["authorization_id"]
            or row.get("protocol_revision_id")
            != validated["protocol_revision_id"]
            or row.get("dataset") != dataset
        ):
            raise RuntimeError("formal_source_scan_authorization_unexpected_ledger_tail")
    return {
        "status": "passed",
        "authorization_id": validated["authorization_id"],
        "authorization_path": str(path.relative_to(root)).replace("\\", "/"),
        "formal_runtime_identity_sha256": validated[
            "formal_runtime_identity_sha256"
        ],
        "dataset": dataset,
        "budget_limit": validated["budget_limit"],
        "target_selected_source_count": validated["target_selected_source_count"],
        "gpu_allowed": True,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "external_calls_allowed": False,
    }


def _formal_budget_path(
    root: Path, config: Mapping[str, Any], authorization_id: str
) -> Path:
    return _resolve(
        Path(str(_formal_scan_contract(config)["budget_directory"]))
        / f"{authorization_id}.jsonl",
        root,
    )


def _read_formal_scan_budget(
    path: Path, authorization: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not path.exists():
        return [], {}
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise RuntimeError("formal_source_scan_budget_partial")
    rows: list[dict[str, Any]] = []
    operations: dict[str, dict[str, Any]] = {}
    previous = "0" * 64
    for sequence, line in enumerate(raw.decode("utf-8").splitlines()):
        row = json.loads(line)
        if not isinstance(row, Mapping):
            raise RuntimeError("formal_source_scan_budget_row_invalid")
        _assert_exact_fields(
            row, _FORMAL_SCAN_BUDGET_FIELDS, kind="formal_source_scan_budget"
        )
        operation = row.get("operation_identity_sha256")
        if (
            row.get("kind") != "v23_formal_source_scan_budget_charge"
            or row.get("sequence") != sequence
            or row.get("authorization_id") != authorization["authorization_id"]
            or row.get("stage") != "formal_source_scan"
            or row.get("dataset") != authorization["dataset"]
            or row.get("previous_row_sha256") != previous
            or row.get("row_sha256")
            != canonical_sha256(
                {key: item for key, item in row.items() if key != "row_sha256"}
            )
            or not _is_sha256(operation)
            or operation in operations
        ):
            raise RuntimeError("formal_source_scan_budget_drift")
        rows.append(dict(row))
        operations[str(operation)] = dict(row)
        previous = str(row["row_sha256"])
    if len(rows) > int(authorization["budget_limit"]):
        raise RuntimeError("formal_source_scan_budget_limit_exceeded")
    return rows, operations


def _source_read_operation(
    authorization: Mapping[str, Any], *, source_order_index: int, source_key: str
) -> str:
    return canonical_sha256(
        {
            "kind": "v23_formal_source_scan_source_read",
            "authorization_id": authorization["authorization_id"],
            "dataset": authorization["dataset"],
            "source_order_index": source_order_index,
            "source_key": source_key,
        }
    )


def _charge_formal_scan_budget(
    path: Path,
    authorization: Mapping[str, Any],
    *,
    source_order_index: int,
    source_key: str,
) -> dict[str, Any]:
    operation = _source_read_operation(
        authorization,
        source_order_index=source_order_index,
        source_key=source_key,
    )
    rows, operations = _read_formal_scan_budget(path, authorization)
    prior = operations.get(operation)
    if prior is not None:
        if (
            prior.get("source_order_index") != source_order_index
            or prior.get("source_key") != source_key
        ):
            raise RuntimeError("formal_source_scan_budget_operation_drift")
        return prior
    assert_budget_available(
        authorization, charges_already_recorded=len(rows), charge_amount=1
    )
    previous = rows[-1]["row_sha256"] if rows else "0" * 64
    row = {
        "kind": "v23_formal_source_scan_budget_charge",
        "sequence": len(rows),
        "authorization_id": authorization["authorization_id"],
        "stage": "formal_source_scan",
        "dataset": authorization["dataset"],
        "operation_identity_sha256": operation,
        "source_order_index": source_order_index,
        "source_key": source_key,
        "previous_row_sha256": previous,
        "charged_at": _utc_now(),
    }
    row["row_sha256"] = canonical_sha256(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return row


def _formal_tail_rows(
    rows: Sequence[Mapping[str, Any]], authorization: Mapping[str, Any]
) -> list[dict[str, Any]]:
    prior = authorization["expected_prior_ledger_tip_sha256"]
    matches = [index for index, row in enumerate(rows) if row.get("row_sha256") == prior]
    if len(matches) != 1:
        raise RuntimeError("formal_source_scan_prior_tip_missing")
    tail = [dict(row) for row in rows[matches[0] + 1 :]]
    for row in tail:
        if (
            row.get("role") != "formal_scan_viewed"
            or row.get("attempt_id") != authorization["authorization_id"]
            or row.get("protocol_revision_id")
            != authorization["protocol_revision_id"]
            or row.get("dataset") != authorization["dataset"]
            or row.get("reservation_batch_size") != 1
            or row.get("reservation_batch_index") != 0
            or row.get("reason") != "v23_formal_source_scan_write_ahead"
        ):
            raise RuntimeError("formal_source_scan_ledger_tail_drift")
    return tail


def _formal_batch_id(
    authorization: Mapping[str, Any],
    *,
    identity: Mapping[str, str],
    expected_prior_tip: str,
) -> str:
    return canonical_sha256(
        {
            "kind": "v23_reservation_batch",
            "protocol_revision_id": authorization["protocol_revision_id"],
            "attempt_id": authorization["authorization_id"],
            "role": "formal_scan_viewed",
            "dataset": authorization["dataset"],
            "expected_batch_size": 1,
            "ordered_source_identity_sha256": canonical_sha256([dict(identity)]),
            "expected_prior_ledger_tip_sha256": expected_prior_tip,
        }
    )


def _ensure_formal_anchor(
    root: Path,
    config: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    row: Mapping[str, Any],
    expected_prior_tip: str,
) -> str:
    directory = _resolve(
        str(_formal_scan_contract(config)["ledger_anchor_directory"]), root
    )
    matches: list[Path] = []
    for path in sorted(directory.glob("*.json")):
        value = _read_json(path)
        if value.get("ledger_tip_sha256") == row["row_sha256"]:
            matches.append(path)
    expected_without_time = {
        "kind": "v23_ledger_tip_anchor",
        "protocol_revision_id": authorization["protocol_revision_id"],
        "attempt_id": authorization["authorization_id"],
        "reservation_batch_id": row["reservation_batch_id"],
        "first_sequence": row["sequence"],
        "last_sequence": row["sequence"],
        "batch_size": 1,
        "prior_ledger_tip_sha256": expected_prior_tip,
        "ledger_tip_sha256": row["row_sha256"],
    }
    if matches:
        if len(matches) != 1:
            raise RuntimeError("formal_source_scan_ledger_anchor_duplicate")
        actual = _read_json(matches[0])
        if {
            key: value for key, value in actual.items() if key != "created_at"
        } != expected_without_time:
            raise RuntimeError("formal_source_scan_ledger_anchor_drift")
        return sha256_file(matches[0])
    anchor = {**expected_without_time, "created_at": _utc_now()}
    path = directory / f"{row['sequence']:012d}_{row['row_sha256']}.json"
    _write_new_json(path, anchor)
    return sha256_file(path)


def _ensure_formal_reservation(
    root: Path,
    config: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    scan_index: int,
    source_order_index: int,
    identity: Mapping[str, str],
    plan_path: Path,
) -> dict[str, Any]:
    governance, _governance_config, ledger_path, _rows = _governance_state(
        root, config
    )
    with governance._exclusive_lock(
        ledger_path.with_suffix(ledger_path.suffix + ".lock")
    ):
        rows = governance._read_ledger(ledger_path)
        tail = _formal_tail_rows(rows, authorization)
        if scan_index < len(tail):
            row = tail[scan_index]
            if (
                row.get("source_key") != identity["source_key"]
                or row.get("source_hash") != identity["source_hash"]
                or row.get("normalized_text_hash")
                != identity["normalized_text_hash"]
            ):
                raise RuntimeError("formal_source_scan_existing_reservation_drift")
            prior_tip = (
                authorization["expected_prior_ledger_tip_sha256"]
                if scan_index == 0
                else tail[scan_index - 1]["row_sha256"]
            )
            _ensure_formal_anchor(
                root,
                config,
                authorization=authorization,
                row=row,
                expected_prior_tip=prior_tip,
            )
            return row
        if scan_index != len(tail):
            raise RuntimeError("formal_source_scan_reservation_order_gap")
        prior_tip = (
            tail[-1]["row_sha256"]
            if tail
            else authorization["expected_prior_ledger_tip_sha256"]
        )
        batch_id = _formal_batch_id(
            authorization, identity=identity, expected_prior_tip=prior_tip
        )
        plan = {
            "kind": "v23_reservation_plan",
            "protocol_revision_id": authorization["protocol_revision_id"],
            "attempt_id": authorization["authorization_id"],
            "role": "formal_scan_viewed",
            "dataset": authorization["dataset"],
            "expected_prior_ledger_tip_sha256": prior_tip,
            "ordered_source_identity_objects": [dict(identity)],
        }
        _write_or_validate_json(plan_path, plan)
        row = {
            "kind": "v23_consumed_source",
            "sequence": len(rows),
            "protocol_revision_id": authorization["protocol_revision_id"],
            "attempt_id": authorization["authorization_id"],
            "reservation_batch_id": batch_id,
            "reservation_batch_index": 0,
            "reservation_batch_size": 1,
            "role": "formal_scan_viewed",
            "dataset": authorization["dataset"],
            "source_key": identity["source_key"],
            "source_hash": identity["source_hash"],
            "normalized_text_hash": identity["normalized_text_hash"],
            "consumed_at": _utc_now(),
            "reason": "v23_formal_source_scan_write_ahead",
            "previous_row_sha256": prior_tip,
        }
        row["row_sha256"] = canonical_sha256(row)
        with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _ensure_formal_anchor(
            root,
            config,
            authorization=authorization,
            row=row,
            expected_prior_tip=prior_tip,
        )
        return row


def _formal_result_hash(row: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            key: copy.deepcopy(value)
            for key, value in row.items()
            if key not in {"created_at", "source_result_sha256"}
        }
    )


def _validate_formal_pair(
    pair: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    ledger_row: Mapping[str, Any],
    pair_order: int,
) -> dict[str, Any]:
    _assert_exact_fields(pair, _FORMAL_PAIR_FIELDS, kind="formal_selected_pair")
    reject_forbidden_formal_inputs(pair)
    if (
        pair.get("kind") != "v23_fact_layer_selection_r2_pair"
        or pair.get("specification_version")
        != "pcv-restoration-first-v23-fact-layer-selection-r2"
        or pair.get("source_fact_specification_version")
        != "pcv-restoration-first-v23-fact-layer-r1"
        or pair.get("selection_identity_sha256")
        != authorization["protocol_revision_id"]
        or pair.get("dataset") != authorization["dataset"]
        or pair.get("source_key") != ledger_row["source_key"]
        or pair.get("source_hash") != ledger_row["source_hash"]
        or pair.get("normalized_text_hash")
        != ledger_row["normalized_text_hash"]
        or pair.get("pair_order") != pair_order
        or not _is_sha256(pair.get("pair_id"))
        or not _is_sha256(pair.get("fact_signature"))
        or not _is_sha256(pair.get("relation_signature"))
    ):
        raise RuntimeError("formal_selected_pair_drift")
    return copy.deepcopy(dict(pair))


def _validate_formal_scan_result(
    row: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    ledger_row: Mapping[str, Any],
    scan_index: int,
    source_order_index: int,
) -> dict[str, Any]:
    _assert_exact_fields(
        row, _FORMAL_SCAN_RESULT_FIELDS, kind="formal_source_scan_result"
    )
    reject_forbidden_formal_inputs(row)
    pairs = row.get("selected_pairs")
    if not isinstance(pairs, list) or len(pairs) not in {0, 3}:
        raise RuntimeError("formal_source_scan_result_pairs_invalid")
    if (
        row.get("kind") != "v23_formal_source_scan_result"
        or row.get("specification_version") != FORMAL_RUNTIME_SPECIFICATION_VERSION
        or row.get("protocol_revision_id")
        != authorization["protocol_revision_id"]
        or row.get("formal_runtime_identity_sha256")
        != authorization["formal_runtime_identity_sha256"]
        or row.get("authorization_id") != authorization["authorization_id"]
        or row.get("dataset") != authorization["dataset"]
        or row.get("scan_index") != scan_index
        or row.get("source_order_rank") != source_order_index
        or row.get("source_key") != ledger_row["source_key"]
        or row.get("source_hash") != ledger_row["source_hash"]
        or row.get("normalized_text_hash")
        != ledger_row["normalized_text_hash"]
        or row.get("eligible") != (len(pairs) == 3)
        or row.get("deterministic_rerun_hash_match") is not True
        or row.get("external_calls_performed") != 0
        or row.get("source_result_sha256") != _formal_result_hash(row)
    ):
        raise RuntimeError("formal_source_scan_result_drift")
    for field in ("fact_count", "candidate_count", "selection_candidate_pair_count"):
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError("formal_source_scan_result_count_invalid")
    if not isinstance(row.get("rejection_reason_counts"), Mapping):
        raise RuntimeError("formal_source_scan_rejection_counts_invalid")
    for index, pair in enumerate(pairs):
        _validate_formal_pair(
            pair,
            authorization=authorization,
            ledger_row=ledger_row,
            pair_order=index,
        )
    return copy.deepcopy(dict(row))


def _load_formal_scan_results(
    directory: Path,
    *,
    authorization: Mapping[str, Any],
    ledger_rows: Sequence[Mapping[str, Any]],
    source_order: Sequence[str],
) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.json"))
    if len(files) > len(ledger_rows):
        raise RuntimeError("formal_source_scan_result_without_reservation")
    results: list[dict[str, Any]] = []
    for scan_index, path in enumerate(files):
        if path.name != f"{scan_index:06d}.json":
            raise RuntimeError("formal_source_scan_result_prefix_drift")
        ledger_row = ledger_rows[scan_index]
        source_key = str(ledger_row["source_key"])
        try:
            source_order_index = source_order.index(source_key)
        except ValueError as error:
            raise RuntimeError("formal_source_scan_result_source_order_missing") from error
        results.append(
            _validate_formal_scan_result(
                _read_json(path),
                authorization=authorization,
                ledger_row=ledger_row,
                scan_index=scan_index,
                source_order_index=source_order_index,
            )
        )
    return results


def _evaluate_formal_source(
    source: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]],
    entity_policy_path: str,
    token_df: Mapping[str, int],
    source_count: int,
    selection_config: Mapping[str, Any],
) -> dict[str, Any]:
    from ..attack.restoration_first_v23_fact_layer import (
        extract_fact_candidates,
        validate_fact_row,
    )
    from ..attack.restoration_first_v23_fact_layer_selection_r2 import (
        select_pairs_from_r1_facts,
    )

    first = extract_fact_candidates(
        source,
        model_emitter=model_emitter,
        entity_policy_path=entity_policy_path,
        token_df=token_df,
        source_count=source_count,
    )
    second = extract_fact_candidates(
        source,
        model_emitter=model_emitter,
        entity_policy_path=entity_policy_path,
        token_df=token_df,
        source_count=source_count,
    )
    if canonical_sha256(first) != canonical_sha256(second):
        raise RuntimeError("formal_source_scan_fact_nondeterministic")
    for fact in first["facts"]:
        validate_fact_row(fact)
    selection = select_pairs_from_r1_facts(
        first["facts"],
        dataset=str(authorization["dataset"]),
        selection_identity_sha256=str(authorization["protocol_revision_id"]),
        config=selection_config,
    )
    pairs = selection["selected"]
    if len(pairs) not in {0, 3}:
        raise RuntimeError("formal_source_scan_pair_count_invalid")
    return {
        "eligible": len(pairs) == 3,
        "selected_pairs": pairs,
        "fact_count": len(first["facts"]),
        "candidate_count": int(first["candidate_count"]),
        "selection_candidate_pair_count": int(selection["candidate_pair_count"]),
        "rejection_reason_counts": dict(selection["rejection_reason_counts"]),
    }


def _finalize_formal_source_scan(
    root: Path,
    config: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    ledger_rows: Sequence[Mapping[str, Any]],
    paths: Mapping[str, Path],
    aggregate_df_manifest_sha256: str,
    exclusion_snapshot_sha256: str,
) -> dict[str, Any]:
    selected_results = [row for row in results if row["eligible"]]
    target = int(authorization["target_selected_source_count"])
    if len(selected_results) != target or len(results) != len(ledger_rows):
        raise RuntimeError("formal_source_scan_not_ready_to_finalize")
    selected_sources: list[dict[str, Any]] = []
    selected_pairs: list[dict[str, Any]] = []
    seen_pair_ids: set[str] = set()
    for selection_index, result in enumerate(selected_results):
        pair_ids = [str(pair["pair_id"]) for pair in result["selected_pairs"]]
        if len(set(pair_ids)) != 3 or seen_pair_ids.intersection(pair_ids):
            raise RuntimeError("formal_source_scan_pair_identity_overlap")
        seen_pair_ids.update(pair_ids)
        selected_pairs.extend(copy.deepcopy(result["selected_pairs"]))
        selected_sources.append(
            {
                "kind": "v23_formal_selected_source",
                "selection_index": selection_index,
                "dataset": authorization["dataset"],
                "source_key": result["source_key"],
                "source_hash": result["source_hash"],
                "normalized_text_hash": result["normalized_text_hash"],
                "source_order_rank": result["source_order_rank"],
                "ordered_pair_ids": pair_ids,
            }
        )
    for row in selected_sources:
        _validate_selected_source(row, str(authorization["dataset"]))
    if len(selected_pairs) != target * 3:
        raise RuntimeError("formal_source_scan_selected_pair_count_drift")
    _write_or_validate_jsonl(paths["selected_sources"], selected_sources)
    _write_or_validate_jsonl(paths["selected_pairs"], selected_pairs)

    freeze_path = _resolve(config["runtime_bundle"]["freeze_path"], root)
    freeze = _read_json(freeze_path)
    governance, governance_config, _ledger_path, current_rows = _governance_state(
        root, config
    )
    current_tail = _formal_tail_rows(current_rows, authorization)
    if current_tail != [dict(row) for row in ledger_rows]:
        raise RuntimeError("formal_source_scan_final_ledger_drift")
    _anchor_path, final_anchor_sha256 = _ledger_anchor(
        root, governance, governance_config, current_tail[-1]["row_sha256"]
    )
    manifest = {
        "kind": "v23_formal_selected_source_set",
        "specification_version": FORMAL_RUNTIME_SPECIFICATION_VERSION,
        "protocol_revision_id": authorization["protocol_revision_id"],
        "dataset": authorization["dataset"],
        "design_manifest_sha256": config["design"]["manifest_sha256"],
        "runtime_bundle_sha256": freeze["runtime_bundle_sha256"],
        "code_commit": freeze["code_commit"],
        "aggregate_df_manifest_sha256": aggregate_df_manifest_sha256,
        "formal_exclusion_snapshot_sha256": exclusion_snapshot_sha256,
        "ordered_selected_source_identity_sha256": sha256_file(
            paths["selected_sources"]
        ),
        "selected_source_count": target,
        "scan_viewed_source_count": len(results),
        "final_consumption_ledger_tip_sha256": current_tail[-1]["row_sha256"],
        "final_tip_anchor_sha256": final_anchor_sha256,
        "status": "passed",
        "external_calls_performed": 0,
    }
    _write_or_validate_json(paths["selected_manifest"], manifest)
    return {
        "status": "passed",
        "dataset": authorization["dataset"],
        "authorization_id": authorization["authorization_id"],
        "protocol_revision_id": authorization["protocol_revision_id"],
        "selected_source_count": target,
        "selected_pair_count": len(selected_pairs),
        "scan_viewed_source_count": len(results),
        "selected_source_set_manifest_sha256": sha256_file(
            paths["selected_manifest"]
        ),
        "selected_sources_file_sha256": sha256_file(paths["selected_sources"]),
        "selected_pairs_file_sha256": sha256_file(paths["selected_pairs"]),
        "final_consumption_ledger_tip_sha256": current_tail[-1]["row_sha256"],
        "formal_test_started": True,
        "gpu_used": True,
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_calls_performed": 0,
        "external_calls_performed": 0,
    }


def run_formal_source_scan(
    *,
    project_root: str | Path = ".",
    authorization_path: str | Path,
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_formal_runtime_config(root)
    validation = validate_formal_source_scan_authorization(
        project_root=root, authorization_path=authorization_path
    )
    authorization = _read_json(_resolve(authorization_path, root))
    dataset = str(validation["dataset"])
    paths = _formal_scan_paths(
        root,
        config,
        protocol_revision_id=str(authorization["protocol_revision_id"]),
        dataset=dataset,
    )
    paths["source_results"].mkdir(parents=True, exist_ok=True)
    paths["reservation_plans"].mkdir(parents=True, exist_ok=True)

    from . import restoration_first_v23 as development
    from . import restoration_first_v23_fresh_audit_preparation as legacy
    from . import restoration_first_v23_fresh_audit_preparation_r2 as governance

    design = development.load_design_config(root)
    pool = development._pool_contract(design, dataset)
    aggregate = development.validate_aggregate_df(project_root=root, dataset=dataset)
    token_df = development._load_token_df(
        development._aggregate_paths(root, dataset)["rows"],
        source_count=int(pool["source_count"]),
    )
    selection_config = load_yaml(
        _resolve("configs/restoration_first_v23_fact_layer_selection_r2.yaml", root)
    )
    if not isinstance(selection_config, Mapping):
        raise RuntimeError("formal_source_scan_selection_config_invalid")
    entity_policy_path = _resolve(
        str(
            design["frozen_v22_bindings"]["extraction_rule_bindings"][
                "entity_type_policy_path"
            ]
        ),
        root,
    )

    with governance._exclusive_lock(paths["lock"]):
        _governance, governance_config, _ledger_path, all_rows = _governance_state(
            root, config
        )
        tail = _formal_tail_rows(all_rows, authorization)
        prior_index = next(
            index
            for index, row in enumerate(all_rows)
            if row["row_sha256"]
            == authorization["expected_prior_ledger_tip_sha256"]
        )
        prior_rows = all_rows[: prior_index + 1]
        excluded_keys = {
            str(row["source_key"])
            for row in prior_rows[1:]
            if row.get("dataset") == dataset
        }
        excluded_hashes = {
            str(row["source_hash"]) for row in prior_rows[1:]
        }
        excluded_normalized = {
            str(row["normalized_text_hash"]) for row in prior_rows[1:]
        }
        pool_order_sha256 = str(pool["source_order_file_sha256"])
        snapshot = {
            "kind": "v23_formal_exclusion_snapshot",
            "specification_version": FORMAL_RUNTIME_SPECIFICATION_VERSION,
            "protocol_revision_id": authorization["protocol_revision_id"],
            "dataset": dataset,
            "prior_ledger_tip_sha256": authorization[
                "expected_prior_ledger_tip_sha256"
            ],
            "prior_tip_anchor_sha256": authorization[
                "expected_prior_tip_anchor_sha256"
            ],
            "excluded_source_keys_sha256": canonical_sha256(sorted(excluded_keys)),
            "source_order_file_sha256": pool_order_sha256,
        }
        _write_or_validate_json(paths["exclusion_snapshot"], snapshot)
        snapshot_sha256 = sha256_file(paths["exclusion_snapshot"])
        budget_path = _formal_budget_path(
            root, config, str(authorization["authorization_id"])
        )

        with legacy._FreshAuditSourceReader(root, dataset, pool) as reader:
            results = _load_formal_scan_results(
                paths["source_results"],
                authorization=authorization,
                ledger_rows=tail,
                source_order=reader.source_order,
            )
            selected_count = sum(bool(row["eligible"]) for row in results)
            target = int(authorization["target_selected_source_count"])
            print(
                f"Resuming formal_source_scan/{dataset}: "
                f"viewed={len(results)}, selected={selected_count}/{target}",
                flush=True,
            )
            emitter = model_emitter
            if selected_count < target and emitter is None:
                print("Loading frozen GLiNER2 snapshot on CUDA...", flush=True)
                emitter = legacy._load_model_emitter(root)
            started_at = time.monotonic()
            scan_index = 0
            for source_order_index, source_key in enumerate(reader.source_order):
                if source_key in excluded_keys:
                    continue
                if scan_index < len(results):
                    result = results[scan_index]
                    if result["source_key"] != source_key:
                        raise RuntimeError("formal_source_scan_resume_order_drift")
                    ledger_row = tail[scan_index]
                    excluded_hashes.add(str(ledger_row["source_hash"]))
                    excluded_normalized.add(
                        str(ledger_row["normalized_text_hash"])
                    )
                    scan_index += 1
                    if selected_count >= target:
                        break
                    continue

                budget_row = _charge_formal_scan_budget(
                    budget_path,
                    authorization,
                    source_order_index=source_order_index,
                    source_key=source_key,
                )
                if scan_index < len(tail):
                    ledger_row = tail[scan_index]
                    if ledger_row["source_key"] != source_key:
                        raise RuntimeError("formal_source_scan_reserved_order_drift")
                    budget_rows, budget_operations = _read_formal_scan_budget(
                        budget_path, authorization
                    )
                    if (
                        budget_row["operation_identity_sha256"]
                        not in budget_operations
                        or len(budget_rows) < scan_index + 1
                    ):
                        raise RuntimeError("formal_source_scan_reservation_without_budget")
                    identity = {
                        "source_key": source_key,
                        "source_hash": str(ledger_row["source_hash"]),
                        "normalized_text_hash": str(
                            ledger_row["normalized_text_hash"]
                        ),
                    }
                    _ensure_formal_reservation(
                        root,
                        config,
                        authorization=authorization,
                        scan_index=scan_index,
                        source_order_index=source_order_index,
                        identity=identity,
                        plan_path=paths["reservation_plans"]
                        / f"{scan_index:06d}.json",
                    )
                else:
                    identity = governance._registration_identity(reader, source_key)
                    ledger_row = _ensure_formal_reservation(
                        root,
                        config,
                        authorization=authorization,
                        scan_index=scan_index,
                        source_order_index=source_order_index,
                        identity=identity,
                        plan_path=paths["reservation_plans"]
                        / f"{scan_index:06d}.json",
                    )
                    tail.append(ledger_row)

                duplicate_identity = (
                    identity["source_hash"] in excluded_hashes
                    or identity["normalized_text_hash"] in excluded_normalized
                )
                if duplicate_identity:
                    selection = {
                        "eligible": False,
                        "selected_pairs": [],
                        "fact_count": 0,
                        "candidate_count": 0,
                        "selection_candidate_pair_count": 0,
                        "rejection_reason_counts": {
                            "prior_consumption_identity_overlap": 1
                        },
                    }
                else:
                    source = reader.read(
                        {
                            "source_order_index": source_order_index,
                            "source_key": source_key,
                            "source_hash": identity["source_hash"],
                            "normalized_text_hash": identity[
                                "normalized_text_hash"
                            ],
                        }
                    )
                    if emitter is None:
                        raise RuntimeError("formal_source_scan_model_emitter_missing")
                    selection = _evaluate_formal_source(
                        source,
                        authorization=authorization,
                        model_emitter=emitter,
                        entity_policy_path=str(entity_policy_path),
                        token_df=token_df,
                        source_count=int(pool["source_count"]),
                        selection_config=selection_config,
                    )
                result: dict[str, Any] = {
                    "kind": "v23_formal_source_scan_result",
                    "specification_version": FORMAL_RUNTIME_SPECIFICATION_VERSION,
                    "protocol_revision_id": authorization["protocol_revision_id"],
                    "formal_runtime_identity_sha256": authorization[
                        "formal_runtime_identity_sha256"
                    ],
                    "authorization_id": authorization["authorization_id"],
                    "dataset": dataset,
                    "scan_index": scan_index,
                    "source_order_rank": source_order_index,
                    "source_key": source_key,
                    "source_hash": identity["source_hash"],
                    "normalized_text_hash": identity["normalized_text_hash"],
                    **selection,
                    "deterministic_rerun_hash_match": True,
                    "external_calls_performed": 0,
                    "created_at": _utc_now(),
                }
                result["source_result_sha256"] = _formal_result_hash(result)
                _validate_formal_scan_result(
                    result,
                    authorization=authorization,
                    ledger_row=ledger_row,
                    scan_index=scan_index,
                    source_order_index=source_order_index,
                )
                _write_new_json(
                    paths["source_results"] / f"{scan_index:06d}.json", result
                )
                results.append(result)
                excluded_hashes.add(identity["source_hash"])
                excluded_normalized.add(identity["normalized_text_hash"])
                scan_index += 1
                if result["eligible"]:
                    selected_count += 1
                if scan_index % 10 == 0 or selected_count == target:
                    elapsed = max(0.0, time.monotonic() - started_at)
                    print(
                        f"formal_source_scan/{dataset}: viewed={scan_index}, "
                        f"selected={selected_count}/{target}, elapsed={elapsed:.1f}s",
                        flush=True,
                    )
                if selected_count == target:
                    break

            if selected_count != target:
                raise RuntimeError(
                    f"formal_source_scan_capacity_shortfall:{dataset}:"
                    f"{selected_count}/{target}"
                )
            _governance, _governance_config, _ledger_path, final_rows = (
                _governance_state(root, config)
            )
            final_tail = _formal_tail_rows(final_rows, authorization)
            return _finalize_formal_source_scan(
                root,
                config,
                authorization=authorization,
                results=results,
                ledger_rows=final_tail,
                paths=paths,
                aggregate_df_manifest_sha256=aggregate[
                    "df_manifest_file_sha256"
                ],
                exclusion_snapshot_sha256=snapshot_sha256,
            )


def validate_formal_source_scan(
    *,
    project_root: str | Path = ".",
    authorization_path: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_formal_runtime_config(root)
    validate_formal_source_scan_authorization(
        project_root=root, authorization_path=authorization_path
    )
    authorization = _read_json(_resolve(authorization_path, root))
    paths = _formal_scan_paths(
        root,
        config,
        protocol_revision_id=str(authorization["protocol_revision_id"]),
        dataset=str(authorization["dataset"]),
    )
    if not paths["selected_manifest"].is_file():
        raise RuntimeError("formal_source_scan_manifest_missing")
    manifest = _read_json(paths["selected_manifest"])
    expected_manifest_fields = {
        "kind",
        "specification_version",
        "protocol_revision_id",
        "dataset",
        "design_manifest_sha256",
        "runtime_bundle_sha256",
        "code_commit",
        "aggregate_df_manifest_sha256",
        "formal_exclusion_snapshot_sha256",
        "ordered_selected_source_identity_sha256",
        "selected_source_count",
        "scan_viewed_source_count",
        "final_consumption_ledger_tip_sha256",
        "final_tip_anchor_sha256",
        "status",
        "external_calls_performed",
    }
    _assert_exact_fields(
        manifest, expected_manifest_fields, kind="formal_selected_source_set"
    )
    freeze = _read_json(_resolve(config["runtime_bundle"]["freeze_path"], root))
    if (
        manifest.get("kind") != "v23_formal_selected_source_set"
        or manifest.get("specification_version")
        != FORMAL_RUNTIME_SPECIFICATION_VERSION
        or manifest.get("protocol_revision_id")
        != authorization["protocol_revision_id"]
        or manifest.get("dataset") != authorization["dataset"]
        or manifest.get("design_manifest_sha256")
        != config["design"]["manifest_sha256"]
        or manifest.get("runtime_bundle_sha256") != freeze["runtime_bundle_sha256"]
        or manifest.get("code_commit") != freeze["code_commit"]
        or manifest.get("formal_exclusion_snapshot_sha256")
        != sha256_file(paths["exclusion_snapshot"])
        or manifest.get("ordered_selected_source_identity_sha256")
        != sha256_file(paths["selected_sources"])
        or manifest.get("selected_source_count") != 2_250
        or manifest.get("status") != "passed"
        or manifest.get("external_calls_performed") != 0
    ):
        raise RuntimeError("formal_source_scan_manifest_drift")
    selected_sources = [
        json.loads(line)
        for line in paths["selected_sources"].read_text(encoding="utf-8").splitlines()
    ]
    for index, row in enumerate(selected_sources):
        _validate_selected_source(row, str(authorization["dataset"]))
        if row["selection_index"] != index:
            raise RuntimeError("formal_source_scan_selected_source_order_drift")
    pairs = [
        json.loads(line)
        for line in paths["selected_pairs"].read_text(encoding="utf-8").splitlines()
    ]
    if len(pairs) != 6_750:
        raise RuntimeError("formal_source_scan_selected_pair_count_drift")
    pair_ids_by_source: dict[str, list[str]] = {}
    for pair in pairs:
        pair_ids_by_source.setdefault(str(pair["source_key"]), []).append(
            str(pair["pair_id"])
        )
    if any(
        pair_ids_by_source.get(str(row["source_key"])) != row["ordered_pair_ids"]
        for row in selected_sources
    ):
        raise RuntimeError("formal_source_scan_pair_binding_drift")
    governance, governance_config, _ledger_path, rows = _governance_state(
        root, config
    )
    tail = _formal_tail_rows(rows, authorization)
    if len(tail) != manifest["scan_viewed_source_count"]:
        raise RuntimeError("formal_source_scan_viewed_count_drift")
    _anchor_path, anchor_sha256 = _ledger_anchor(
        root,
        governance,
        governance_config,
        manifest["final_consumption_ledger_tip_sha256"],
    )
    if anchor_sha256 != manifest["final_tip_anchor_sha256"]:
        raise RuntimeError("formal_source_scan_final_anchor_drift")
    return {
        "status": "passed",
        "dataset": authorization["dataset"],
        "authorization_id": authorization["authorization_id"],
        "protocol_revision_id": authorization["protocol_revision_id"],
        "selected_source_count": len(selected_sources),
        "selected_pair_count": len(pairs),
        "scan_viewed_source_count": len(tail),
        "selected_source_set_manifest_sha256": sha256_file(
            paths["selected_manifest"]
        ),
        "selected_sources_file_sha256": sha256_file(paths["selected_sources"]),
        "selected_pairs_file_sha256": sha256_file(paths["selected_pairs"]),
        "formal_test_started": True,
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_calls_performed": 0,
        "external_calls_performed": 0,
    }


def formal_source_scan_status(
    project_root: str | Path = ".", *, dataset: str = "edgar"
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_formal_runtime_config(root)
    freeze = _read_json(_resolve(config["runtime_bundle"]["freeze_path"], root))
    paths = _formal_scan_paths(
        root,
        config,
        protocol_revision_id=str(freeze["formal_runtime_identity_sha256"]),
        dataset=dataset,
    )
    if paths["selected_manifest"].is_file():
        manifest = _read_json(paths["selected_manifest"])
        return {
            "status": str(manifest.get("status")),
            "started": True,
            "completed": manifest.get("status") == "passed",
            "scan_viewed_source_count": manifest.get("scan_viewed_source_count"),
            "selected_source_count": manifest.get("selected_source_count"),
        }
    result_count = (
        len(list(paths["source_results"].glob("*.json")))
        if paths["source_results"].is_dir()
        else 0
    )
    return {
        "status": "running_or_resumable" if result_count else "not_started",
        "started": result_count > 0,
        "completed": False,
        "scan_viewed_source_count": result_count,
        "selected_source_count": None,
    }
