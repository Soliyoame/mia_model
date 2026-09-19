"""将冻结 Enron capacity 证据提升为主表专用 formal source manifest。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import ensure_dir, read_json, write_json
from .entity_policy_release import runtime_tree_sha256, validate_release_gate
from .formal_dataset_role_scope import (
    ENRON_CAPACITY_PROMOTION_PROTOCOL,
    FORMAL_DATASET_ROLE_SCOPE_VERSION,
    capacity_promotion_config,
    formal_dataset_role_scope_metadata,
    validate_capacity_promotion_dataset,
    validate_capacity_qualification_evidence,
    validate_formal_dataset_role_scope_metadata,
)
from .formal_evidence_scope import (
    formal_evidence_scope_metadata,
    validate_formal_evidence_scope_metadata,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise RuntimeError(f"Promotion path escapes project root: {resolved}") from exc
    return resolved


def _selection_rank(source_key: str) -> str:
    selection_seed = int(capacity_promotion_config()["selection_seed"])
    payload = (
        f"{FORMAL_DATASET_ROLE_SCOPE_VERSION}\0{selection_seed}\0"
        f"enron\0{source_key}"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _selected_source_keys(
    eligible_source_keys: list[str],
    required_sources: int,
) -> list[str]:
    if len(set(eligible_source_keys)) != len(eligible_source_keys):
        raise RuntimeError("Enron eligible source keys contain duplicates")
    if len(eligible_source_keys) < required_sources:
        raise RuntimeError("Enron capacity is below the promotion target")
    return sorted(
        eligible_source_keys,
        key=lambda source_key: (_selection_rank(source_key), source_key),
    )[:required_sources]


def build_enron_capacity_promotion(
    release_gate_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """冻结零 API、零 Retriever 的 Enron capacity promotion manifest。"""

    config = capacity_promotion_config()
    validate_capacity_promotion_dataset(str(config["dataset"]))
    gate_path = _resolve_project_path(release_gate_path)
    gate = validate_release_gate(
        gate_path,
        project_root=PROJECT_ROOT,
        require_current_runtime=True,
    )
    evidence = validate_capacity_qualification_evidence()["enron"]
    query_path = _resolve_project_path(evidence["query_eligibility_path"])
    query = read_json(query_path)
    eligible_source_keys = [
        str(item) for item in query.get("eligible_source_keys") or []
    ]
    if sha256_obj(eligible_source_keys) != evidence["eligible_source_keys_sha256"]:
        raise RuntimeError("Enron promotion eligible source identity drift")
    required_sources = int(config["required_formal_sources"])
    selected_source_keys = _selected_source_keys(
        eligible_source_keys,
        required_sources,
    )
    output = _resolve_project_path(output_path or config["output_path"])
    ensure_dir(output.parent)
    identity = {
        "protocol": ENRON_CAPACITY_PROMOTION_PROTOCOL,
        "scan_protocol": ENRON_CAPACITY_PROMOTION_PROTOCOL,
        "status": "passed",
        "dataset": "enron",
        "dataset_role": "capacity_qualified_primary",
        "main_table_eligible": True,
        "main_table_disclosure_required": True,
        "prior_pilot_status": "failed",
        "formal_evidence_scope": formal_evidence_scope_metadata(),
        "formal_dataset_role_scope": formal_dataset_role_scope_metadata(),
        "release_gate_path": str(gate_path),
        "release_gate_sha256": sha256_file(gate_path),
        "release_gate_identity_sha256": gate[
            "release_gate_identity_sha256"
        ],
        "runtime_tree_sha256": gate["runtime_tree_sha256"],
        "capacity_qualification_evidence": evidence,
        "query_eligibility_path": str(query_path),
        "query_eligibility_sha256": sha256_file(query_path),
        "capacity_status": "passed",
        "stop_status": "target_reached",
        "deduplicate_complete_sources": True,
        "capacity_eligible_source_count": len(eligible_source_keys),
        "capacity_eligible_source_keys_sha256": sha256_obj(
            eligible_source_keys
        ),
        "required_formal_sources": required_sources,
        "selection_seed": int(config["selection_seed"]),
        "selection_method": str(config["selection_method"]),
        "selected_source_keys": selected_source_keys,
        "selected_source_keys_sha256": sha256_obj(selected_source_keys),
        "eligible_source_count": len(selected_source_keys),
        "eligible_source_keys": selected_source_keys,
        "whitelist_hash": sha256_obj(sorted(selected_source_keys)),
        "target_query_eligible_sources": required_sources,
        "minimum_valid_claims": 3,
        "minimum_stealth_pairs": 3,
        "queries_per_source": 6,
        "query_text_uniqueness_enforced": True,
        "scan_checkpoint_path": evidence["capacity_checkpoint_path"],
        "scan_checkpoint_sha256": evidence["capacity_checkpoint_sha256"],
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs": 0,
    }
    payload = {
        **identity,
        "promotion_identity_sha256": sha256_obj(identity),
        "created_at": _utc_now(),
    }
    write_json(payload, output)
    return payload


def validate_enron_capacity_promotion(
    path: str | Path,
    *,
    require_current_runtime: bool = True,
) -> dict[str, Any]:
    promotion_path = _resolve_project_path(path)
    payload = read_json(promotion_path)
    identity = {
        key: value
        for key, value in payload.items()
        if key not in {"promotion_identity_sha256", "created_at"}
    }
    if sha256_obj(identity) != payload.get("promotion_identity_sha256"):
        raise RuntimeError("Enron capacity promotion identity drift")
    if (
        payload.get("protocol") != ENRON_CAPACITY_PROMOTION_PROTOCOL
        or payload.get("scan_protocol") != ENRON_CAPACITY_PROMOTION_PROTOCOL
        or payload.get("status") != "passed"
        or payload.get("dataset") != "enron"
        or payload.get("dataset_role") != "capacity_qualified_primary"
        or payload.get("main_table_eligible") is not True
        or payload.get("main_table_disclosure_required") is not True
        or payload.get("prior_pilot_status") != "failed"
        or payload.get("capacity_status") != "passed"
        or payload.get("stop_status") != "target_reached"
        or payload.get("deduplicate_complete_sources") is not True
        or payload.get("minimum_valid_claims") != 3
        or payload.get("minimum_stealth_pairs") != 3
        or payload.get("queries_per_source") != 6
        or payload.get("query_text_uniqueness_enforced") is not True
        or payload.get("api_calls_performed") != 0
        or payload.get("victim_calls_performed") != 0
        or payload.get("retriever_runs") != 0
    ):
        raise RuntimeError("Enron capacity promotion role drift")
    validate_formal_evidence_scope_metadata(
        payload.get("formal_evidence_scope")
    )
    validate_formal_dataset_role_scope_metadata(
        payload.get("formal_dataset_role_scope")
    )
    evidence = validate_capacity_qualification_evidence()["enron"]
    if payload.get("capacity_qualification_evidence") != evidence:
        raise RuntimeError("Enron capacity promotion evidence drift")
    gate_path = _resolve_project_path(payload.get("release_gate_path") or "")
    if sha256_file(gate_path) != payload.get("release_gate_sha256"):
        raise RuntimeError("Enron capacity promotion release gate drift")
    gate = validate_release_gate(
        gate_path,
        project_root=PROJECT_ROOT,
        require_current_runtime=require_current_runtime,
    )
    if (
        gate.get("release_gate_identity_sha256")
        != payload.get("release_gate_identity_sha256")
        or gate.get("runtime_tree_sha256")
        != payload.get("runtime_tree_sha256")
    ):
        raise RuntimeError("Enron capacity promotion release identity drift")
    query_path = _resolve_project_path(payload.get("query_eligibility_path") or "")
    if sha256_file(query_path) != payload.get("query_eligibility_sha256"):
        raise RuntimeError("Enron promotion query eligibility drift")
    query = read_json(query_path)
    eligible_source_keys = [
        str(item) for item in query.get("eligible_source_keys") or []
    ]
    config = capacity_promotion_config()
    required_sources = int(config["required_formal_sources"])
    selected_source_keys = _selected_source_keys(
        eligible_source_keys,
        required_sources,
    )
    if (
        len(eligible_source_keys)
        != payload.get("capacity_eligible_source_count")
        or sha256_obj(eligible_source_keys)
        != payload.get("capacity_eligible_source_keys_sha256")
        or payload.get("required_formal_sources") != required_sources
        or payload.get("selection_seed") != config["selection_seed"]
        or payload.get("selection_method") != config["selection_method"]
        or payload.get("selected_source_keys") != selected_source_keys
        or sha256_obj(selected_source_keys)
        != payload.get("selected_source_keys_sha256")
        or payload.get("eligible_source_keys") != selected_source_keys
        or payload.get("eligible_source_count") != required_sources
        or payload.get("whitelist_hash")
        != sha256_obj(sorted(selected_source_keys))
        or payload.get("scan_checkpoint_path")
        != evidence["capacity_checkpoint_path"]
        or payload.get("scan_checkpoint_sha256")
        != evidence["capacity_checkpoint_sha256"]
    ):
        raise RuntimeError("Enron capacity promotion selection drift")
    return payload
