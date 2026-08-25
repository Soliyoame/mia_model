"""AI-only, blind-packet structural audit for the frozen v23 fresh audit.

This stage deliberately does not open the private audit secret or any source
mapping. It audits only the visible packet rows and writes a separate,
assistant-only diagnostic artifact. It is not a human annotation or a formal
semantic validity gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..attack.restoration_first_v23 import canonical_json, canonical_sha256
from ..utils.hash import sha256_file
from . import restoration_first_v23_fresh_audit_preparation as legacy_preparation
from . import restoration_first_v23_fresh_audit_preparation_r2 as preparation


AI_AUDIT_SPECIFICATION_VERSION = "pcv-restoration-first-v23-ai-audit-r1"
AI_AUDIT_AUTH_KIND = "v23_fresh_audit_ai_audit_authorization"
AI_AUDIT_LABEL_KIND = "v23_ai_audit_label"
AI_AUDIT_MANIFEST_KIND = "v23_ai_audit_manifest"
AI_AUDIT_STAGE = "ai_audit"
AI_AUDIT_REVIEW_MODE = "assistant_only_structural_review"
AI_AUDIT_STATUS = "completed_ai_only_diagnostic"
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
DATASETS = ("edgar", "enron", "pubmed")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve(path: str | Path, root: Path) -> Path:
    return preparation._resolve(path, root)


def _read_json(path: Path) -> dict[str, Any]:
    return preparation._read_json(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise RuntimeError("v23_ai_audit_packet_jsonl_missing_or_partial")
    rows: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError("v23_ai_audit_packet_row_invalid")
        rows.append(value)
    return rows


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise RuntimeError(f"v23_ai_audit_artifact_already_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (canonical_json(dict(value)) + "\n").encode("utf-8")
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_new_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    if path.exists():
        raise RuntimeError(f"v23_ai_audit_artifact_already_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(canonical_json(dict(row)) + "\n" for row in rows).encode("utf-8")
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_or_validate_json(path: Path, value: Mapping[str, Any]) -> None:
    if not path.exists():
        _write_new_json(path, value)
        return
    actual = _read_json(path)
    expected = dict(value)
    if {key: item for key, item in actual.items() if key != "created_at"} != {
        key: item for key, item in expected.items() if key != "created_at"
    }:
        raise RuntimeError(f"v23_ai_audit_artifact_drift:{path}")


def _write_or_validate_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    expected = [dict(row) for row in rows]
    if not path.exists():
        _write_new_jsonl(path, expected)
        return
    actual = _read_jsonl(path)
    if actual != expected:
        raise RuntimeError(f"v23_ai_audit_labels_drift:{path}")


def _audit_root(root: Path, freeze_identity: str) -> Path:
    return _resolve(Path("artifacts/v23/audit") / freeze_identity, root)


def _ai_audit_root(root: Path, freeze_identity: str) -> Path:
    return _audit_root(root, freeze_identity) / "ai_audit"


def _packet_inputs(root: Path) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    freeze = preparation.validate_preparation_freeze(root)
    audit_root = _audit_root(root, freeze["freeze_identity_sha256"])
    manifest_path = audit_root / "blind_packet_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("v23_ai_audit_packet_manifest_missing")
    manifest = _read_json(manifest_path)
    packet_path = _resolve(str(manifest.get("packet_path")), root)
    if (
        manifest.get("kind") != "v23_blind_audit_packet_manifest"
        or manifest.get("freeze_identity_sha256") != freeze["freeze_identity_sha256"]
        or manifest.get("status") != "prepared_for_human_blind_review"
        or not isinstance(manifest.get("packet_row_count"), int)
        or manifest.get("packet_file_sha256") != sha256_file(packet_path)
    ):
        raise RuntimeError("v23_ai_audit_packet_manifest_drift")
    rows = _read_jsonl(packet_path)
    if len(rows) != manifest["packet_row_count"]:
        raise RuntimeError("v23_ai_audit_packet_row_count_drift")
    return manifest, packet_path, rows


def prepare_ai_audit_authorization(
    *, project_root: str | Path = ".", user_authorization_record: str
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    freeze = preparation.validate_preparation_freeze(root)
    manifest, packet_path, rows = _packet_inputs(root)
    if not isinstance(user_authorization_record, str) or not user_authorization_record.strip():
        raise ValueError("v23_ai_audit_authorization_record_required")
    payload: dict[str, Any] = {
        "kind": AI_AUDIT_AUTH_KIND,
        "specification_version": AI_AUDIT_SPECIFICATION_VERSION,
        "stage": AI_AUDIT_STAGE,
        "freeze_identity_sha256": freeze["freeze_identity_sha256"],
        "packet_manifest_sha256": sha256_file(
            _audit_root(root, freeze["freeze_identity_sha256"])
            / "blind_packet_manifest.json"
        ),
        "packet_file_sha256": sha256_file(packet_path),
        "packet_row_count": len(rows),
        "budget_maximum_packet_rows": len(rows),
        "ai_audit_allowed": True,
        "human_audit_allowed": False,
        "private_key_access_allowed": False,
        "membership_access_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "api_allowed": False,
        "formal_experiment_allowed": False,
        "external_calls_allowed": False,
        "source_content_persistence_allowed": False,
        "user_authorization_record": user_authorization_record.strip(),
        "created_at": _utc_now(),
    }
    payload["authorization_id"] = canonical_sha256(payload)
    path = _resolve(
        Path("artifacts/v23/governance/run_authorizations")
        / f"{payload['authorization_id']}.json",
        root,
    )
    _write_or_validate_json(path, payload)
    return {
        **payload,
        "authorization_path": path.relative_to(root).as_posix(),
        "external_calls_performed": 0,
    }


def validate_ai_audit_authorization(
    *, project_root: str | Path = ".", authorization_path: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    freeze = preparation.validate_preparation_freeze(root)
    manifest, packet_path, rows = _packet_inputs(root)
    path = _resolve(authorization_path, root)
    auth = _read_json(path)
    expected_path = _resolve(
        Path("artifacts/v23/governance/run_authorizations")
        / f"{auth.get('authorization_id')}.json",
        root,
    )
    required_false = (
        "human_audit_allowed",
        "private_key_access_allowed",
        "membership_access_allowed",
        "victim_allowed",
        "retriever_allowed",
        "api_allowed",
        "formal_experiment_allowed",
        "external_calls_allowed",
        "source_content_persistence_allowed",
    )
    if (
        path != expected_path
        or auth.get("kind") != AI_AUDIT_AUTH_KIND
        or auth.get("specification_version") != AI_AUDIT_SPECIFICATION_VERSION
        or auth.get("stage") != AI_AUDIT_STAGE
        or auth.get("freeze_identity_sha256") != freeze["freeze_identity_sha256"]
        or auth.get("packet_manifest_sha256")
        != sha256_file(
            _audit_root(root, freeze["freeze_identity_sha256"])
            / "blind_packet_manifest.json"
        )
        or auth.get("packet_file_sha256") != sha256_file(packet_path)
        or auth.get("packet_row_count") != len(rows)
        or auth.get("ai_audit_allowed") is not True
        or any(auth.get(key) is not False for key in required_false)
    ):
        raise RuntimeError("v23_ai_audit_authorization_scope_drift")
    payload = {key: value for key, value in auth.items() if key != "authorization_id"}
    if auth.get("authorization_id") != canonical_sha256(payload):
        raise RuntimeError("v23_ai_audit_authorization_hash_drift")
    del manifest
    return auth


def _hard_checks(row: Mapping[str, Any], seen_pairs: set[str]) -> list[str]:
    reasons: list[str] = []
    if set(row) != legacy_preparation.PACKET_VISIBLE_FIELDS:
        reasons.append("packet_schema")
    if row.get("kind") != "v23_blind_audit_packet":
        reasons.append("kind_invalid")
    if not HEX32_RE.fullmatch(str(row.get("opaque_audit_source_id") or "")):
        reasons.append("opaque_source_id_invalid")
    if not HEX64_RE.fullmatch(str(row.get("packet_order_key") or "")):
        reasons.append("packet_order_key_invalid")
    pair_id = str(row.get("pair_id") or "")
    if not pair_id or pair_id in seen_pairs:
        reasons.append("pair_id_duplicate_or_empty")
    if isinstance(row.get("pair_order"), bool) or not isinstance(row.get("pair_order"), int) or not 0 <= row.get("pair_order") <= 2:
        reasons.append("pair_order_invalid")
    text_fields = (
        "complete_source_text",
        "supporting_sentence",
        "true_claim",
        "counterfactual_claim",
        "original_entity",
        "counterfactual_entity",
        "effective_type",
    )
    if any(not isinstance(row.get(key), str) or not row.get(key).strip() for key in text_fields):
        reasons.append("text_field_empty_or_invalid")
    if row.get("supporting_sentence") != row.get("true_claim"):
        reasons.append("supporting_sentence_mismatch")
    if row.get("original_entity") == row.get("counterfactual_entity"):
        reasons.append("entities_identical")
    if row.get("true_claim") == row.get("counterfactual_claim"):
        reasons.append("claims_identical")
    if isinstance(row.get("true_claim"), str) and row.get("original_entity") not in row.get("true_claim"):
        reasons.append("original_entity_absent")
    if isinstance(row.get("counterfactual_claim"), str) and row.get("counterfactual_entity") not in row.get("counterfactual_claim"):
        reasons.append("counterfactual_entity_absent")
    return reasons


def _uncertain_checks(row: Mapping[str, Any]) -> list[str]:
    if any(not isinstance(row.get(key), str) for key in ("complete_source_text", "true_claim", "counterfactual_claim", "original_entity", "counterfactual_entity")):
        return []
    reasons: list[str] = []
    if row["supporting_sentence"] not in row["complete_source_text"]:
        reasons.append("supporting_sentence_not_found_in_source")
    true_claim = row["true_claim"]
    counterfactual_claim = row["counterfactual_claim"]
    original = row["original_entity"]
    replacement = row["counterfactual_entity"]
    if true_claim.replace(original, replacement, 1) != counterfactual_claim:
        reasons.append("not_exact_single_slot_replacement")
    return reasons


def _label_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    seen_pairs: set[str] = set()
    source_counts: dict[str, int] = {}
    labels: list[dict[str, Any]] = []
    for row in rows:
        source_id = str(row.get("opaque_audit_source_id") or "")
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
        hard = _hard_checks(row, seen_pairs)
        seen_pairs.add(str(row.get("pair_id") or ""))
        uncertain = [] if hard else _uncertain_checks(row)
        judgment = "fail" if hard else ("uncertain" if uncertain else "pass")
        reasons = hard + uncertain
        labels.append(
            {
                "kind": AI_AUDIT_LABEL_KIND,
                "opaque_audit_source_id": source_id,
                "pair_id": str(row.get("pair_id") or ""),
                "packet_row_sha256": canonical_sha256(row),
                "judgment": judgment,
                "reasons": reasons,
                "reviewer_role": "assistant",
                "review_mode": AI_AUDIT_REVIEW_MODE,
                "human_validation_performed": False,
            }
        )
    for source_id, count in source_counts.items():
        if count != 3:
            for label in labels:
                if label["opaque_audit_source_id"] == source_id and label["judgment"] == "pass":
                    label["judgment"] = "fail"
                    label["reasons"] = [*label["reasons"], "source_pair_count_invalid"]
    counts = {"pass": 0, "fail": 0, "uncertain": 0}
    for label in labels:
        counts[label["judgment"]] += 1
    return labels, counts


def run_ai_audit(
    *, project_root: str | Path = ".", authorization_path: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    authorization = validate_ai_audit_authorization(
        project_root=root, authorization_path=authorization_path
    )
    manifest, packet_path, rows = _packet_inputs(root)
    labels, counts = _label_rows(rows)
    freeze_identity = authorization["freeze_identity_sha256"]
    output = _ai_audit_root(root, freeze_identity)
    labels_path = output / "ai_audit_labels.jsonl"
    _write_or_validate_jsonl(labels_path, labels)
    audit_manifest = {
        "kind": AI_AUDIT_MANIFEST_KIND,
        "specification_version": AI_AUDIT_SPECIFICATION_VERSION,
        "freeze_identity_sha256": freeze_identity,
        "packet_manifest_sha256": sha256_file(
            _audit_root(root, freeze_identity) / "blind_packet_manifest.json"
        ),
        "packet_file_sha256": sha256_file(packet_path),
        "packet_row_count": len(rows),
        "labels_path": labels_path.relative_to(root).as_posix(),
        "labels_file_sha256": sha256_file(labels_path),
        "label_counts": counts,
        "reviewer_role": "assistant",
        "review_mode": AI_AUDIT_REVIEW_MODE,
        "human_validation_performed": False,
        "human_audit_requested": False,
        "private_key_read": False,
        "membership_read": False,
        "victim_response_read": False,
        "retriever_output_read": False,
        "auc_read": False,
        "external_calls_performed": 0,
        "source_content_read": True,
        "formal_experiment_allowed": False,
        "diagnostic_only": True,
        "status": AI_AUDIT_STATUS,
        "created_at": _utc_now(),
    }
    audit_manifest["audit_identity_sha256"] = canonical_sha256(
        {key: value for key, value in audit_manifest.items() if key != "created_at"}
    )
    manifest_path = output / "ai_audit_manifest.json"
    _write_or_validate_json(manifest_path, audit_manifest)
    del manifest
    return {
        "status": audit_manifest["status"],
        "audit_identity_sha256": audit_manifest["audit_identity_sha256"],
        "label_counts": counts,
        "packet_row_count": len(rows),
        "ai_audit_manifest_sha256": sha256_file(manifest_path),
        "authorization_id": authorization["authorization_id"],
        "external_calls_performed": 0,
    }
