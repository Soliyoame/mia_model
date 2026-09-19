"""Enron v21_r2 角色与容量研究协议。

该协议只冻结决策，不提供执行入口。容量研究即使通过，也不能改写 v21_r1
cohort A 的 applicability gate 失败结论。
"""

from __future__ import annotations

from copy import deepcopy
from math import floor
from pathlib import Path
from typing import Any, Mapping

from ..attack.entity_type_policy import (
    ENTITY_TYPE_POLICY_SHA256,
    ENTITY_TYPE_POLICY_VERSION,
)
from ..utils.hash import sha256_obj
from ..utils.io import load_yaml, read_json
from .formal_evidence_scope import (
    LEGACY_FORMAL_EVIDENCE_SCOPE_SHA256,
    LEGACY_FORMAL_EVIDENCE_SCOPE_VERSION,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENRON_CAPACITY_ROLE_PATH = (
    PROJECT_ROOT / "configs" / "enron_capacity_role_v21_r2.yaml"
)
ENRON_CAPACITY_ROLE_VERSION = "pcv_enron_capacity_role_v21_r2"
ENRON_CAPACITY_STUDY_PROTOCOL = "v21_enron_capacity_study_fixed_pool_r2"


def _mapping(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Enron capacity protocol {field} must be a mapping")
    return dict(value)


def validate_enron_capacity_role_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """校验角色、旧失败结论和新容量研究边界。"""

    normalized = deepcopy(dict(payload))
    if normalized.get("protocol_version") != ENRON_CAPACITY_ROLE_VERSION:
        raise RuntimeError("Unexpected Enron capacity role protocol version")
    if normalized.get("dataset") != "enron":
        raise RuntimeError("Enron capacity role protocol must bind dataset=enron")

    entity_policy = _mapping(normalized, "entity_policy")
    if entity_policy != {
        "version": ENTITY_TYPE_POLICY_VERSION,
        "sha256": ENTITY_TYPE_POLICY_SHA256,
    }:
        raise RuntimeError("Enron capacity role entity-policy identity mismatch")

    scope = _mapping(normalized, "formal_evidence_scope")
    if scope != {
        "version": LEGACY_FORMAL_EVIDENCE_SCOPE_VERSION,
        "sha256": LEGACY_FORMAL_EVIDENCE_SCOPE_SHA256,
    }:
        raise RuntimeError("Enron capacity role formal-scope identity mismatch")

    role = _mapping(normalized, "role")
    if role != {
        "formal_role": "boundary_stress_test",
        "primary_canonical": False,
        "capacity_pass_effect": "permits_boundary_evaluation_only",
        "capacity_failure_effect": "stop_enron_downstream_work",
    }:
        raise RuntimeError("Enron capacity role decision drift")

    prior = _mapping(normalized, "prior_applicability")
    gates = _mapping(prior, "gates")
    required_prior = {
        "protocol": "v21_entity_policy_pilot_v1",
        "cohort": "A",
        "status": "failed",
        "report_path": (
            "artifacts/v21/entity_policy_r1/pilots/cohort_A/enron/"
            "pilot_report.json"
        ),
        "report_identity_sha256": (
            "dcb1322cbd0ee4726dc4ba5bed596e20aebfff195854b74d1a4227b1dea2607e"
        ),
        "scanned_sources": 500,
        "eligible_sources": 49,
        "eligible_rate": 0.098,
        "wilson_95_lower": 0.07492354740061162,
        "conclusion_immutable": True,
    }
    if any(prior.get(key) != value for key, value in required_prior.items()):
        raise RuntimeError("Enron v21_r1 applicability conclusion drift")
    if gates != {
        "minimum_eligible_sources": 50,
        "minimum_eligible_rate": 0.10,
        "minimum_wilson_95_lower": 0.075,
    }:
        raise RuntimeError("Enron v21_r1 applicability gate drift")
    if not (
        int(prior["eligible_sources"]) < int(gates["minimum_eligible_sources"])
        and float(prior["eligible_rate"])
        < float(gates["minimum_eligible_rate"])
        and float(prior["wilson_95_lower"])
        < float(gates["minimum_wilson_95_lower"])
    ):
        raise RuntimeError("Enron v21_r1 failure must remain explicit")

    capacity = _mapping(normalized, "capacity_study")
    expected_capacity = {
        "protocol": ENRON_CAPACITY_STUDY_PROTOCOL,
        "purpose": "source_capacity_feasibility",
        "selection_seed": 42,
        "selection_method": "sha256(seed,dataset,canonical_source_key)",
        "candidate_pool_target_sources": 35000,
        "candidate_pool_shortfall_policy": "fail",
        "scan_full_candidate_pool": True,
        "exact_target_stop": False,
        "required_eligible_sources": 2250,
        "max_chunks_per_source": 5,
        "fallback_chunk_caps": [],
        "minimum_valid_claims": 3,
        "minimum_stealth_pairs": 3,
        "conservative_rate_basis": "pilot_wilson_95_lower",
        "applicability_gate_disposition": "report_prior_failure_unchanged",
    }
    if capacity != expected_capacity:
        raise RuntimeError("Enron capacity study decision drift")
    conservative_capacity = floor(
        int(capacity["candidate_pool_target_sources"])
        * float(prior["wilson_95_lower"])
    )
    if conservative_capacity < int(capacity["required_eligible_sources"]):
        raise RuntimeError("Enron conservative capacity is below the fixed target")

    execution = _mapping(normalized, "execution")
    if execution != {
        "enabled": False,
        "long_task_owner": "user",
        "agent_may_execute_long_task": False,
        "api_calls_allowed": False,
        "victim_calls_allowed": False,
        "retriever_runs_allowed": False,
    }:
        raise RuntimeError("Enron capacity execution boundary drift")
    return normalized


_ENRON_CAPACITY_ROLE_PAYLOAD = validate_enron_capacity_role_payload(
    load_yaml(ENRON_CAPACITY_ROLE_PATH)
)
ENRON_CAPACITY_ROLE_SHA256 = sha256_obj(_ENRON_CAPACITY_ROLE_PAYLOAD)


def enron_capacity_role_payload() -> dict[str, Any]:
    """返回协议原始内容的副本，供离线校验和测试使用。"""

    return deepcopy(_ENRON_CAPACITY_ROLE_PAYLOAD)


def enron_capacity_role_metadata() -> dict[str, Any]:
    """返回可绑定到后续 plan/report 的不可变协议身份。"""

    prior = _mapping(_ENRON_CAPACITY_ROLE_PAYLOAD, "prior_applicability")
    capacity = _mapping(_ENRON_CAPACITY_ROLE_PAYLOAD, "capacity_study")
    conservative_capacity = floor(
        int(capacity["candidate_pool_target_sources"])
        * float(prior["wilson_95_lower"])
    )
    return {
        "protocol_version": ENRON_CAPACITY_ROLE_VERSION,
        "protocol_sha256": ENRON_CAPACITY_ROLE_SHA256,
        "protocol_path": str(ENRON_CAPACITY_ROLE_PATH),
        "dataset": "enron",
        "formal_role": "boundary_stress_test",
        "primary_canonical": False,
        "prior_applicability_status": "failed",
        "prior_pilot_report_identity_sha256": prior[
            "report_identity_sha256"
        ],
        "capacity_study_protocol": ENRON_CAPACITY_STUDY_PROTOCOL,
        "candidate_pool_target_sources": capacity[
            "candidate_pool_target_sources"
        ],
        "required_eligible_sources": capacity["required_eligible_sources"],
        "conservative_expected_eligible_sources": conservative_capacity,
        "long_task_owner": "user",
        "execution_enabled": False,
    }


def validate_enron_capacity_role_metadata(
    payload: Mapping[str, Any] | None,
) -> None:
    """拒绝由其他 Enron 角色或容量协议生成的 artifact。"""

    if dict(payload or {}) != enron_capacity_role_metadata():
        raise RuntimeError("Enron capacity role identity mismatch")


def validate_bound_enron_pilot_report(
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """只读验证配置绑定的 v21_r1 pilot 失败证据。"""

    prior = _mapping(_ENRON_CAPACITY_ROLE_PAYLOAD, "prior_applicability")
    path = (
        Path(report_path)
        if report_path is not None
        else PROJECT_ROOT / str(prior["report_path"])
    )
    report = read_json(path)
    identity = {
        key: value
        for key, value in report.items()
        if key not in {"created_at", "report_identity_sha256"}
    }
    if (
        sha256_obj(identity) != report.get("report_identity_sha256")
        or report.get("report_identity_sha256")
        != prior["report_identity_sha256"]
    ):
        raise RuntimeError("Bound Enron pilot report identity drift")
    source_gate = _mapping(report, "source_gate")
    if (
        report.get("protocol") != prior["protocol"]
        or report.get("dataset") != "enron"
        or report.get("status") != "failed"
        or source_gate.get("scanned_sources") != prior["scanned_sources"]
        or source_gate.get("eligible_sources") != prior["eligible_sources"]
        or source_gate.get("eligible_rate") != prior["eligible_rate"]
        or source_gate.get("wilson_95_lower") != prior["wilson_95_lower"]
        or source_gate.get("gate_passed") is not False
    ):
        raise RuntimeError("Bound Enron pilot report conclusion drift")
    if report.get("api_calls_performed") != 0 or report.get("retriever_runs") != 0:
        raise RuntimeError("Bound Enron pilot report execution boundary drift")
    return report
