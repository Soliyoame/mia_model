"""Fail-closed identity checks for the v21 entity-policy release gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..attack.entity_type_policy import (
    ENTITY_TYPE_POLICY_SHA256,
    ENTITY_TYPE_POLICY_VERSION,
)
from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import read_json, read_jsonl
from .formal_dataset_role_scope import (
    ENRON_CAPACITY_PROMOTION_PROTOCOL,
    MAIN_TABLE_DATASETS,
    evaluate_dataset_report_roles,
    validate_audit_dataset,
    validate_capacity_qualification_evidence_metadata,
    validate_formal_dataset_role_scope_metadata,
)
from .formal_evidence_scope import (
    FORMAL_MINIMUM_GLOBAL_VALID_PAIRS,
    FORMAL_MINIMUM_DATASET_TYPE_VALID_PAIRS,
    FORMAL_SEMANTIC_ENTITY_TYPES,
    validate_formal_evidence_scope_metadata,
)


RELEASE_GATE_PROTOCOL = (
    "v21_entity_policy_release_gate_v4_capacity_qualified_primary_r1"
)
FORMAL_SCAN_PROTOCOL = (
    "v21_entity_policy_full_rescan_v3_capacity_qualified_primary_r1"
)


def _validate_file_identity(path: Path, expected_sha256: object) -> None:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise RuntimeError(f"Release gate evidence drift: {path}")


def _validate_inventory_contents(path: Path) -> None:
    inventory = read_json(path)
    identity = {
        key: value
        for key, value in inventory.items()
        if key not in {"created_at", "inventory_identity_sha256"}
    }
    if sha256_obj(identity) != inventory.get("inventory_identity_sha256"):
        raise RuntimeError("Release gate inventory identity drift")
    for row in (inventory.get("datasets") or {}).values():
        for path_key, hash_key in (
            ("scan_plan_path", "scan_plan_sha256"),
            ("source_order_path", "source_order_file_sha256"),
            ("candidate_benchmark_path", "candidate_benchmark_sha256"),
            ("latest_checkpoint_path", "latest_checkpoint_sha256"),
        ):
            _validate_file_identity(
                Path(str(row.get(path_key) or "")),
                row.get(hash_key),
            )
        for wave in row.get("completed_waves") or []:
            _validate_file_identity(
                Path(str(wave.get("wave_manifest_path") or "")),
                wave.get("wave_manifest_sha256"),
            )
            for output in (wave.get("outputs") or {}).values():
                _validate_file_identity(
                    Path(str(output.get("path") or "")),
                    output.get("sha256"),
                )


def _validate_dataset_report_contents(path: Path) -> None:
    report = read_json(path)
    identity = {
        key: value
        for key, value in report.items()
        if key not in {"created_at", "report_identity_sha256"}
    }
    if sha256_obj(identity) != report.get("report_identity_sha256"):
        raise RuntimeError("Release gate dataset report identity drift")
    for path_key, hash_key in (
        ("stage_plan_path", "stage_plan_sha256"),
        ("stage_checkpoint_path", "stage_checkpoint_sha256"),
    ):
        _validate_file_identity(
            Path(str(report.get(path_key) or "")),
            report.get(hash_key),
        )
    checkpoint = read_json(report["stage_checkpoint_path"])
    for record in checkpoint.get("completed_waves") or []:
        manifest_path = Path(str(record.get("wave_manifest_path") or ""))
        _validate_file_identity(manifest_path, record.get("wave_manifest_sha256"))
        manifest = read_json(manifest_path)
        manifest_identity = {
            key: value
            for key, value in manifest.items()
            if key not in {"created_at", "wave_identity_sha256"}
        }
        if sha256_obj(manifest_identity) != manifest.get("wave_identity_sha256"):
            raise RuntimeError("Release gate wave identity drift")
        for output in (manifest.get("outputs") or {}).values():
            _validate_file_identity(
                Path(str(output.get("path") or "")),
                output.get("sha256"),
            )
    for record in checkpoint.get("fact_replay") or []:
        for path_key, hash_key in (
            ("claims_path", "claims_sha256"),
            ("manifest_path", "manifest_sha256"),
        ):
            _validate_file_identity(
                Path(str(record.get(path_key) or "")),
                record.get(hash_key),
            )


def _validate_audit_contents(audit_report: dict[str, Any]) -> None:
    validate_formal_evidence_scope_metadata(
        audit_report.get("formal_evidence_scope")
    )
    validate_formal_dataset_role_scope_metadata(
        audit_report.get("formal_dataset_role_scope")
    )
    for path_key, hash_key in (
        ("audit_manifest_path", "audit_manifest_sha256"),
        ("assistant_labels_path", "assistant_labels_sha256"),
        ("user_review_path", "user_review_sha256"),
    ):
        _validate_file_identity(
            Path(str(audit_report.get(path_key) or "")),
            audit_report.get(hash_key),
        )
    manifest = read_json(audit_report["audit_manifest_path"])
    identity = {
        key: value
        for key, value in manifest.items()
        if key not in {"created_at", "audit_identity_sha256"}
    }
    if sha256_obj(identity) != manifest.get("audit_identity_sha256"):
        raise RuntimeError("Release gate audit manifest identity drift")
    validate_formal_evidence_scope_metadata(manifest.get("formal_evidence_scope"))
    validate_formal_dataset_role_scope_metadata(
        manifest.get("formal_dataset_role_scope")
    )
    for path_key, hash_key in (
        ("blinded_path", "blinded_sha256"),
        ("key_path", "key_sha256"),
    ):
        _validate_file_identity(
            Path(str(manifest.get(path_key) or "")),
            manifest.get(hash_key),
        )
    for row in read_jsonl(manifest["blinded_path"]):
        validate_audit_dataset(str(row.get("dataset") or ""))


def runtime_tree_sha256(project_root: str | Path) -> str:
    """Hash every Python/config input that can alter the formal scan."""

    root = Path(project_root).resolve()
    paths: list[Path] = []
    for directory, suffixes in (
        (root / "src", {".py"}),
        (root / "scripts", {".py"}),
        (root / "configs", {".yaml", ".yml"}),
    ):
        paths.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.casefold() in suffixes
        )
    return sha256_obj(
        [
            {
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha256_file(path),
            }
            for path in sorted(paths)
        ]
    )


def validate_release_gate(
    path: str | Path,
    *,
    project_root: str | Path | None = None,
    require_current_runtime: bool = False,
) -> dict[str, Any]:
    """Validate the gate, all retained evidence, policy, and runtime identity."""

    gate_path = Path(path).resolve()
    if not gate_path.is_file():
        raise FileNotFoundError(gate_path)
    payload = read_json(gate_path)
    if payload.get("protocol") != RELEASE_GATE_PROTOCOL:
        raise RuntimeError("Entity policy release gate protocol mismatch")
    identity = {
        key: value
        for key, value in payload.items()
        if key not in {"created_at", "release_gate_identity_sha256"}
    }
    if sha256_obj(identity) != payload.get("release_gate_identity_sha256"):
        raise RuntimeError("Entity policy release gate identity mismatch")
    if payload.get("status") != "passed":
        raise RuntimeError(
            "Entity policy release gate is not passed: "
            f"{payload.get('failure_reasons')}"
        )
    if payload.get("formal_scan_identity") != FORMAL_SCAN_PROTOCOL:
        raise RuntimeError("Entity policy formal scan identity mismatch")
    validate_formal_evidence_scope_metadata(payload.get("formal_evidence_scope"))
    validate_formal_dataset_role_scope_metadata(
        payload.get("formal_dataset_role_scope")
    )
    validate_capacity_qualification_evidence_metadata(
        payload.get("capacity_qualification_evidence")
    )
    if (
        payload.get("enron_capacity_promotion_identity")
        != ENRON_CAPACITY_PROMOTION_PROTOCOL
    ):
        raise RuntimeError("Enron capacity promotion identity mismatch")
    policy = payload.get("entity_policy") or {}
    if (
        policy.get("policy_version") != ENTITY_TYPE_POLICY_VERSION
        or policy.get("policy_sha256") != ENTITY_TYPE_POLICY_SHA256
    ):
        raise RuntimeError("Entity policy release gate drift")
    formal_pairs = payload.get("formal_semantic_valid_pairs") or {}
    for entity_type in FORMAL_SEMANTIC_ENTITY_TYPES:
        if int(formal_pairs.get(entity_type, 0)) < FORMAL_MINIMUM_GLOBAL_VALID_PAIRS:
            raise RuntimeError(
                f"Release gate formal scope coverage failed: {entity_type}"
            )
    by_dataset = payload.get("formal_semantic_valid_pairs_by_dataset") or {}
    if set(by_dataset) != set(MAIN_TABLE_DATASETS):
        raise RuntimeError("Release gate per-dataset coverage mismatch")
    for dataset in sorted(MAIN_TABLE_DATASETS):
        counts = by_dataset.get(dataset) or {}
        for entity_type in FORMAL_SEMANTIC_ENTITY_TYPES:
            if int(counts.get(entity_type, 0)) < FORMAL_MINIMUM_DATASET_TYPE_VALID_PAIRS:
                raise RuntimeError(
                    "Release gate dataset/type coverage failed: "
                    f"{dataset}/{entity_type}"
                )

    evidence = [
        {
            "path": payload.get("inventory_path"),
            "sha256": payload.get("inventory_sha256"),
        },
        *(payload.get("replay_reports") or []),
        *(payload.get("pilot_reports") or []),
    ]
    for row in evidence:
        evidence_path = Path(str(row.get("path") or ""))
        _validate_file_identity(evidence_path, row.get("sha256"))
    inventory_path = Path(str(payload.get("inventory_path") or ""))
    _validate_inventory_contents(inventory_path)
    report_rows = [
        *(payload.get("replay_reports") or []),
        *(payload.get("pilot_reports") or []),
    ]
    for row in report_rows:
        _validate_dataset_report_contents(Path(str(row["path"])))
    replay_reports = [
        read_json(Path(str(row["path"])))
        for row in payload.get("replay_reports") or []
    ]
    pilot_reports = [
        read_json(Path(str(row["path"])))
        for row in payload.get("pilot_reports") or []
    ]
    role_failures = evaluate_dataset_report_roles(
        replay_reports,
        pilot_reports,
    )
    if role_failures:
        raise RuntimeError(
            "Entity policy dataset role evidence mismatch: "
            f"{role_failures}"
        )
    _validate_audit_contents(dict(payload.get("audit_report") or {}))

    if require_current_runtime:
        if project_root is None:
            raise ValueError("project_root is required for runtime validation")
        actual_runtime = runtime_tree_sha256(project_root)
        if actual_runtime != payload.get("runtime_tree_sha256"):
            raise RuntimeError(
                "Entity policy release runtime tree drift: "
                f"expected={payload.get('runtime_tree_sha256')} "
                f"actual={actual_runtime}"
            )
    return payload
