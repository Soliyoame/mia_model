"""PCV-MIA v21 正式数据集角色与边界证据作用域。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..utils.hash import sha256_file, sha256_obj
from ..utils.io import load_yaml, read_json
from .enron_capacity_role import (
    ENRON_CAPACITY_ROLE_SHA256,
    ENRON_CAPACITY_ROLE_VERSION,
    ENRON_CAPACITY_STUDY_PROTOCOL,
    enron_capacity_role_metadata,
    validate_bound_enron_pilot_report,
    validate_enron_capacity_role_metadata,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORMAL_DATASET_ROLE_SCOPE_PATH = (
    PROJECT_ROOT / "configs" / "formal_dataset_role_scope_v21_r2.yaml"
)
FORMAL_DATASET_ROLE_SCOPE_VERSION = (
    "pcv_formal_dataset_role_scope_v21_r2_capacity_qualified_primary"
)
ALL_DATASETS = frozenset({"edgar", "enron", "pubmed"})


def _mapping(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Formal dataset role scope {field} must be a mapping")
    return dict(value)


def _dataset_set(payload: Mapping[str, Any], field: str) -> frozenset[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"Formal dataset role scope {field} must be a list")
    normalized = frozenset(str(item).casefold() for item in value)
    if len(normalized) != len(value):
        raise RuntimeError(f"Formal dataset role scope {field} has duplicates")
    return normalized


def validate_formal_dataset_role_scope_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """校验 primary/boundary 分区和所有预冻结证据身份。"""

    normalized = deepcopy(dict(payload))
    if (
        normalized.get("formal_dataset_role_scope_version")
        != FORMAL_DATASET_ROLE_SCOPE_VERSION
    ):
        raise RuntimeError("Unexpected formal dataset role scope version")
    standard = _dataset_set(normalized, "standard_primary_datasets")
    capacity = _dataset_set(
        normalized,
        "capacity_qualified_primary_datasets",
    )
    main_table = _dataset_set(normalized, "main_table_datasets")
    if (
        standard != frozenset({"edgar", "pubmed"})
        or capacity != frozenset({"enron"})
        or standard & capacity
        or standard | capacity != ALL_DATASETS
        or main_table != ALL_DATASETS
    ):
        raise RuntimeError("Formal dataset primary role partition drift")
    if _dataset_set(normalized, "audit_allowed_datasets") != main_table:
        raise RuntimeError("Formal audit dataset role drift")
    if (
        _dataset_set(normalized, "fresh_formal_scan_allowed_datasets")
        != standard
    ):
        raise RuntimeError("Fresh formal scan dataset role drift")
    if (
        _dataset_set(normalized, "capacity_promotion_allowed_datasets")
        != capacity
    ):
        raise RuntimeError("Capacity promotion dataset role drift")

    identities = _mapping(normalized, "report_identities")
    statuses = _mapping(normalized, "required_status_by_role")
    for stage in ("replay", "pilot"):
        stage_ids = _mapping(identities, stage)
        if set(stage_ids) != ALL_DATASETS or any(
            not str(value).strip() for value in stage_ids.values()
        ):
            raise RuntimeError(f"Formal dataset role {stage} identity coverage drift")
        stage_statuses = _mapping(statuses, stage)
        expected_statuses = (
            {
                "standard_primary": "passed",
                "capacity_qualified_primary": "passed",
            }
            if stage == "replay"
            else {
                "standard_primary": "passed",
                "capacity_qualified_primary": "failed",
            }
        )
        if stage_statuses != expected_statuses:
            raise RuntimeError(f"Formal dataset role {stage} status drift")

    qualification_evidence = _mapping(
        normalized,
        "capacity_qualification_evidence",
    )
    if set(qualification_evidence) != {"enron"}:
        raise RuntimeError("Capacity qualification evidence coverage drift")
    enron = _mapping(qualification_evidence, "enron")
    required_exact = {
        "source_artifact_role": "boundary_stress_test",
        "promoted_role": "capacity_qualified_primary",
        "main_table_disclosure_required": True,
        "prior_pilot_status": "failed",
        "role_protocol_version": ENRON_CAPACITY_ROLE_VERSION,
        "role_protocol_sha256": ENRON_CAPACITY_ROLE_SHA256,
        "pilot_report_identity_sha256": identities["pilot"]["enron"],
        "capacity_protocol": ENRON_CAPACITY_STUDY_PROTOCOL,
        "capacity_status": "passed",
        "scanned_source_count": 35000,
        "eligible_source_count": 3786,
        "required_source_count": 2250,
    }
    if any(enron.get(key) != value for key, value in required_exact.items()):
        raise RuntimeError("Formal dataset Enron qualification identity drift")
    required_strings = {
        "pilot_report_path",
        "capacity_finalization_manifest_path",
        "capacity_finalization_manifest_sha256",
        "capacity_finalization_identity_sha256",
        "capacity_scan_plan_sha256",
        "capacity_checkpoint_path",
        "capacity_checkpoint_sha256",
        "query_eligibility_sha256",
    }
    if any(not str(enron.get(key) or "").strip() for key in required_strings):
        raise RuntimeError("Formal dataset Enron boundary evidence is incomplete")
    output_names = enron.get("required_output_names")
    if not isinstance(output_names, list) or set(output_names) != {
        "benchmark",
        "facts",
        "claims",
        "queries",
        "stealth",
        "stealth_rejected",
        "claim_eligibility",
        "query_eligibility",
        "stealth_manifest",
    }:
        raise RuntimeError("Formal dataset Enron output coverage drift")

    promotion = _mapping(normalized, "capacity_promotion")
    expected_promotion = {
        "protocol": "v21_enron_capacity_qualified_primary_promotion_v1",
        "dataset": "enron",
        "selection_seed": 42,
        "selection_method": (
            "sha256(scope_version,selection_seed,dataset,source_key)"
        ),
        "required_formal_sources": 2250,
        "output_path": (
            "artifacts/v21/entity_policy_r2/enron_capacity_promotion/"
            "enron_capacity_qualified_primary_manifest.json"
        ),
    }
    if promotion != expected_promotion:
        raise RuntimeError("Enron capacity promotion config drift")

    reporting = _mapping(normalized, "main_table_reporting")
    if (
        set(reporting.get("datasets") or []) != ALL_DATASETS
        or reporting.get("report_per_dataset_results") is not True
        or reporting.get("report_all_three_macro") is not True
        or reporting.get("report_standard_primary_sensitivity") is not True
        or reporting.get("disclose_enron_failed_pilot") is not True
        or reporting.get("disclose_enron_eligibility_yield") is not True
    ):
        raise RuntimeError("Main-table reporting policy drift")
    return normalized


_FORMAL_DATASET_ROLE_SCOPE_PAYLOAD = (
    validate_formal_dataset_role_scope_payload(
        load_yaml(FORMAL_DATASET_ROLE_SCOPE_PATH)
    )
)
FORMAL_DATASET_ROLE_SCOPE_SHA256 = sha256_obj(
    _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD
)
STANDARD_PRIMARY_DATASETS = frozenset(
    _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD["standard_primary_datasets"]
)
CAPACITY_QUALIFIED_PRIMARY_DATASETS = frozenset(
    _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD[
        "capacity_qualified_primary_datasets"
    ]
)
MAIN_TABLE_DATASETS = frozenset(
    _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD["main_table_datasets"]
)
AUDIT_ALLOWED_DATASETS = frozenset(
    _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD["audit_allowed_datasets"]
)
FRESH_FORMAL_SCAN_ALLOWED_DATASETS = frozenset(
    _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD[
        "fresh_formal_scan_allowed_datasets"
    ]
)
CAPACITY_PROMOTION_ALLOWED_DATASETS = frozenset(
    _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD[
        "capacity_promotion_allowed_datasets"
    ]
)
FORMAL_SCAN_ALLOWED_DATASETS = FRESH_FORMAL_SCAN_ALLOWED_DATASETS
ENRON_CAPACITY_PROMOTION_PROTOCOL = str(
    _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD["capacity_promotion"]["protocol"]
)


def formal_dataset_role_scope_payload() -> dict[str, Any]:
    return deepcopy(_FORMAL_DATASET_ROLE_SCOPE_PAYLOAD)


def formal_dataset_role_scope_metadata() -> dict[str, Any]:
    evidence = _mapping(
        _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD[
            "capacity_qualification_evidence"
        ],
        "enron",
    )
    return {
        "scope_version": FORMAL_DATASET_ROLE_SCOPE_VERSION,
        "scope_sha256": FORMAL_DATASET_ROLE_SCOPE_SHA256,
        "scope_path": str(FORMAL_DATASET_ROLE_SCOPE_PATH),
        "standard_primary_datasets": sorted(STANDARD_PRIMARY_DATASETS),
        "capacity_qualified_primary_datasets": sorted(
            CAPACITY_QUALIFIED_PRIMARY_DATASETS
        ),
        "main_table_datasets": sorted(MAIN_TABLE_DATASETS),
        "audit_allowed_datasets": sorted(AUDIT_ALLOWED_DATASETS),
        "fresh_formal_scan_allowed_datasets": sorted(
            FRESH_FORMAL_SCAN_ALLOWED_DATASETS
        ),
        "capacity_promotion_allowed_datasets": sorted(
            CAPACITY_PROMOTION_ALLOWED_DATASETS
        ),
        "capacity_qualification_evidence": {
            "enron": {
                "source_artifact_role": evidence["source_artifact_role"],
                "promoted_role": evidence["promoted_role"],
                "role_protocol_version": evidence["role_protocol_version"],
                "role_protocol_sha256": evidence["role_protocol_sha256"],
                "pilot_report_identity_sha256": evidence[
                    "pilot_report_identity_sha256"
                ],
                "capacity_finalization_identity_sha256": evidence[
                    "capacity_finalization_identity_sha256"
                ],
                "capacity_status": evidence["capacity_status"],
                "main_table_disclosure_required": True,
            }
        },
        "capacity_promotion_protocol": ENRON_CAPACITY_PROMOTION_PROTOCOL,
    }


def validate_formal_dataset_role_scope_metadata(
    payload: Mapping[str, Any] | None,
) -> None:
    if dict(payload or {}) != formal_dataset_role_scope_metadata():
        raise RuntimeError("Formal dataset role scope identity mismatch")


def dataset_role(dataset: str) -> str:
    normalized = str(dataset).casefold()
    if normalized in STANDARD_PRIMARY_DATASETS:
        return "standard_primary"
    if normalized in CAPACITY_QUALIFIED_PRIMARY_DATASETS:
        return "capacity_qualified_primary"
    raise RuntimeError(f"Dataset is outside the formal role scope: {dataset!r}")


def validate_primary_formal_dataset(dataset: str) -> None:
    if str(dataset).casefold() not in FORMAL_SCAN_ALLOWED_DATASETS:
        raise RuntimeError(
            f"Dataset requires capacity promotion, not fresh formal scan: {dataset!r}"
        )


def validate_audit_dataset(dataset: str) -> None:
    if str(dataset).casefold() not in AUDIT_ALLOWED_DATASETS:
        raise RuntimeError(
            f"Dataset is outside the main-table audit scope: {dataset!r}"
        )


def validate_capacity_promotion_dataset(dataset: str) -> None:
    if str(dataset).casefold() not in CAPACITY_PROMOTION_ALLOWED_DATASETS:
        raise RuntimeError(
            f"Dataset is not capacity-promotion qualified: {dataset!r}"
        )


def capacity_promotion_config() -> dict[str, Any]:
    return deepcopy(dict(_FORMAL_DATASET_ROLE_SCOPE_PAYLOAD["capacity_promotion"]))


def expected_report_identity(stage: str, dataset: str) -> str:
    identities = _mapping(
        _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD, "report_identities"
    )
    stage_ids = _mapping(identities, stage)
    normalized = str(dataset).casefold()
    if normalized not in stage_ids:
        raise RuntimeError(f"Unexpected report identity request: {stage}/{dataset}")
    return str(stage_ids[normalized])


def validate_audit_report_role(report: Mapping[str, Any]) -> None:
    dataset = str(report.get("dataset") or "").casefold()
    stage = str(report.get("stage") or "").casefold()
    validate_audit_dataset(dataset)
    if stage not in {"replay", "pilot"}:
        raise RuntimeError(f"Unsupported audit report stage: {stage!r}")
    role = dataset_role(dataset)
    statuses = _mapping(
        _mapping(
            _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD,
            "required_status_by_role",
        ),
        stage,
    )
    if report.get("status") != statuses[role]:
        raise RuntimeError(
            f"Audit report role/status mismatch: {stage}/{dataset}/{role}"
        )
    if report.get("report_identity_sha256") != expected_report_identity(
        stage,
        dataset,
    ):
        raise RuntimeError(f"Audit report identity mismatch: {stage}/{dataset}")
    if stage == "pilot" and report.get("pilot_cohort") != "A":
        raise RuntimeError(f"Audit pilot cohort mismatch: {dataset}")


def evaluate_dataset_report_roles(
    replay_reports: Sequence[Mapping[str, Any]],
    pilot_reports: Sequence[Mapping[str, Any]],
) -> list[str]:
    """返回 role/status/identity 失败原因，不改写任何 report。"""

    failures: list[str] = []
    status_config = _mapping(
        _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD, "required_status_by_role"
    )
    for stage, reports in (("replay", replay_reports), ("pilot", pilot_reports)):
        by_dataset = {
            str(report.get("dataset") or "").casefold(): report
            for report in reports
        }
        if len(by_dataset) != len(reports) or set(by_dataset) != ALL_DATASETS:
            failures.append(f"{stage}_dataset_role_coverage_mismatch")
        stage_statuses = _mapping(status_config, stage)
        for dataset in sorted(ALL_DATASETS):
            report = by_dataset.get(dataset)
            if report is None:
                continue
            role = dataset_role(dataset)
            if report.get("stage") != stage:
                failures.append(f"{stage}_{dataset}_stage_mismatch")
            if report.get("status") != stage_statuses[role]:
                failures.append(f"{stage}_{dataset}_{role}_status_mismatch")
            if (
                report.get("report_identity_sha256")
                != expected_report_identity(stage, dataset)
            ):
                failures.append(f"{stage}_{dataset}_identity_mismatch")
            if (
                report.get("api_calls_performed") != 0
                or report.get("retriever_runs") != 0
            ):
                failures.append(f"{stage}_{dataset}_execution_boundary_drift")
            if stage == "pilot" and report.get("pilot_cohort") != "A":
                failures.append(f"pilot_{dataset}_cohort_mismatch")
    return failures


def _resolve_evidence_path(value: object) -> Path:
    path = Path(str(value or ""))
    resolved = (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise RuntimeError(f"Boundary evidence escapes project root: {resolved}") from exc
    return resolved


def validate_capacity_qualification_evidence() -> dict[str, Any]:
    """验证 Enron failed pilot 与 capacity-qualified primary 的来源证据。"""

    evidence = _mapping(
        _FORMAL_DATASET_ROLE_SCOPE_PAYLOAD[
            "capacity_qualification_evidence"
        ],
        "enron",
    )
    pilot_path = _resolve_evidence_path(evidence["pilot_report_path"])
    pilot = validate_bound_enron_pilot_report(pilot_path)

    finalization_path = _resolve_evidence_path(
        evidence["capacity_finalization_manifest_path"]
    )
    if (
        not finalization_path.is_file()
        or sha256_file(finalization_path)
        != evidence["capacity_finalization_manifest_sha256"]
    ):
        raise RuntimeError("Enron capacity finalization file drift")
    finalization = read_json(finalization_path)
    identity = {
        key: value
        for key, value in finalization.items()
        if key not in {"created_at", "finalization_identity_sha256"}
    }
    if (
        sha256_obj(identity) != finalization.get("finalization_identity_sha256")
        or finalization.get("finalization_identity_sha256")
        != evidence["capacity_finalization_identity_sha256"]
        or finalization.get("protocol") != evidence["capacity_protocol"]
        or finalization.get("scan_plan_sha256")
        != evidence["capacity_scan_plan_sha256"]
    ):
        raise RuntimeError("Enron capacity finalization identity drift")
    validate_enron_capacity_role_metadata(
        finalization.get("enron_capacity_role")
    )
    if (
        finalization.get("formal_role") != "boundary_stress_test"
        or finalization.get("primary_canonical") is not False
        or finalization.get("capacity_pass_effect")
        != "permits_boundary_evaluation_only"
        or finalization.get("prior_applicability_status") != "failed"
        or finalization.get("api_calls_performed") != 0
        or finalization.get("retriever_runs") != 0
    ):
        raise RuntimeError("Enron capacity finalization role drift")

    checkpoint_path = _resolve_evidence_path(
        evidence["capacity_checkpoint_path"]
    )
    if (
        not checkpoint_path.is_file()
        or sha256_file(checkpoint_path)
        != evidence["capacity_checkpoint_sha256"]
        or finalization.get("scan_checkpoint_sha256")
        != evidence["capacity_checkpoint_sha256"]
    ):
        raise RuntimeError("Enron capacity checkpoint drift")

    outputs = _mapping(finalization, "outputs")
    if set(outputs) != set(evidence["required_output_names"]):
        raise RuntimeError("Enron capacity finalized output coverage drift")
    for name in outputs:
        row = _mapping(outputs, name)
        path = _resolve_evidence_path(row.get("path"))
        if not path.is_file() or sha256_file(path) != row.get("sha256"):
            raise RuntimeError(f"Enron capacity finalized output drift: {name}")

    query_row = _mapping(outputs, "query_eligibility")
    if query_row.get("sha256") != evidence["query_eligibility_sha256"]:
        raise RuntimeError("Enron capacity query eligibility hash drift")
    query_path = _resolve_evidence_path(query_row["path"])
    query = read_json(query_path)
    validate_enron_capacity_role_metadata(query.get("enron_capacity_role"))
    required_query = {
        "capacity_status": evidence["capacity_status"],
        "scanned_source_count": evidence["scanned_source_count"],
        "source_count": evidence["scanned_source_count"],
        "eligible_source_count": evidence["eligible_source_count"],
        "required_source_count": evidence["required_source_count"],
        "formal_role": "boundary_stress_test",
        "primary_canonical": False,
        "capacity_pass_effect": "permits_boundary_evaluation_only",
        "prior_applicability_status": "failed",
        "api_calls_performed": 0,
        "retriever_runs": 0,
    }
    if any(query.get(key) != value for key, value in required_query.items()):
        raise RuntimeError("Enron capacity query eligibility role drift")
    eligible_source_keys = [
        str(item) for item in query.get("eligible_source_keys") or []
    ]
    if (
        len(eligible_source_keys) != evidence["eligible_source_count"]
        or len(set(eligible_source_keys)) != len(eligible_source_keys)
    ):
        raise RuntimeError("Enron capacity eligible source identity drift")

    return {
        "enron": {
            "role": enron_capacity_role_metadata(),
            "pilot_report_path": str(pilot_path),
            "pilot_report_sha256": sha256_file(pilot_path),
            "pilot_report_identity_sha256": pilot[
                "report_identity_sha256"
            ],
            "capacity_finalization_manifest_path": str(finalization_path),
            "capacity_finalization_manifest_sha256": sha256_file(
                finalization_path
            ),
            "capacity_finalization_identity_sha256": finalization[
                "finalization_identity_sha256"
            ],
            "capacity_checkpoint_path": str(checkpoint_path),
            "capacity_checkpoint_sha256": sha256_file(checkpoint_path),
            "query_eligibility_path": str(query_path),
            "query_eligibility_sha256": sha256_file(query_path),
            "capacity_status": query["capacity_status"],
            "scanned_source_count": query["scanned_source_count"],
            "eligible_source_count": query["eligible_source_count"],
            "eligible_source_keys_sha256": sha256_obj(eligible_source_keys),
            "source_artifact_role": query["formal_role"],
            "source_artifact_primary_canonical": query["primary_canonical"],
            "source_artifact_capacity_pass_effect": query[
                "capacity_pass_effect"
            ],
            "promoted_role": "capacity_qualified_primary",
            "main_table_eligible": True,
            "main_table_disclosure_required": True,
            "prior_pilot_status": "failed",
            "capacity_promotion_protocol": ENRON_CAPACITY_PROMOTION_PROTOCOL,
        }
    }


def validate_capacity_qualification_evidence_metadata(
    payload: Mapping[str, Any] | None,
) -> None:
    if dict(payload or {}) != validate_capacity_qualification_evidence():
        raise RuntimeError(
            "Formal dataset capacity qualification evidence identity mismatch"
        )
