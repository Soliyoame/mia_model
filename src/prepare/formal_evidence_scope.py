"""PCV-MIA v21 正式证据范围与数据集分层审计配额。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from ..attack.entity_type_policy import SEMANTIC_TARGET_TYPES
from ..utils.hash import sha256_obj
from ..utils.io import load_yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORMAL_EVIDENCE_SCOPE_PATH = (
    PROJECT_ROOT / "configs" / "formal_evidence_scope_v21_r2.yaml"
)
LEGACY_FORMAL_EVIDENCE_SCOPE_PATH = (
    PROJECT_ROOT / "configs" / "formal_evidence_scope_v21_r1.yaml"
)
FORMAL_EVIDENCE_SCOPE_VERSION = (
    "pcv_formal_evidence_scope_v21_r2_dataset_stratified"
)
LEGACY_FORMAL_EVIDENCE_SCOPE_VERSION = "pcv_formal_evidence_scope_v21_r1"


def _type_set(payload: Mapping[str, Any], field: str) -> frozenset[str]:
    raw = payload.get(field)
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(
            f"Formal evidence scope {field} must be a non-empty list"
        )
    values = frozenset(str(item).upper() for item in raw)
    if len(values) != len(raw):
        raise RuntimeError(f"Formal evidence scope {field} contains duplicates")
    return values


def _load_scope(path: Path, expected_version: str) -> dict[str, Any]:
    payload = load_yaml(path)
    version = str(payload.get("formal_evidence_scope_version") or "").strip()
    if version != expected_version:
        raise RuntimeError(f"Unexpected formal evidence scope version: {version!r}")
    formal = _type_set(payload, "formal_semantic_entity_types")
    diagnostic = _type_set(payload, "diagnostic_only_semantic_entity_types")
    if formal & diagnostic or formal | diagnostic != SEMANTIC_TARGET_TYPES:
        raise RuntimeError(
            "Formal evidence scope must partition the semantic entity types"
        )
    if int(payload.get("minimum_global_valid_pairs") or 0) <= 0:
        raise RuntimeError("Formal evidence scope minimum must be positive")
    if not isinstance(payload.get("audit"), Mapping):
        raise RuntimeError("Formal evidence scope audit must be a mapping")
    return deepcopy(dict(payload))


def _scope_metadata(payload: Mapping[str, Any], path: Path) -> dict[str, Any]:
    metadata = {
        "scope_version": payload["formal_evidence_scope_version"],
        "scope_sha256": sha256_obj(payload),
        "scope_path": str(path),
        "formal_semantic_entity_types": sorted(
            _type_set(payload, "formal_semantic_entity_types")
        ),
        "diagnostic_only_semantic_entity_types": sorted(
            _type_set(payload, "diagnostic_only_semantic_entity_types")
        ),
        "minimum_global_valid_pairs": int(
            payload["minimum_global_valid_pairs"]
        ),
        "audit": deepcopy(dict(payload["audit"])),
    }
    if "minimum_valid_pairs_per_dataset_type" in payload:
        metadata["minimum_valid_pairs_per_dataset_type"] = int(
            payload["minimum_valid_pairs_per_dataset_type"]
        )
    return metadata


_FORMAL_EVIDENCE_SCOPE_PAYLOAD = _load_scope(
    FORMAL_EVIDENCE_SCOPE_PATH,
    FORMAL_EVIDENCE_SCOPE_VERSION,
)
_LEGACY_FORMAL_EVIDENCE_SCOPE_PAYLOAD = _load_scope(
    LEGACY_FORMAL_EVIDENCE_SCOPE_PATH,
    LEGACY_FORMAL_EVIDENCE_SCOPE_VERSION,
)
LEGACY_FORMAL_EVIDENCE_SCOPE_SHA256 = sha256_obj(
    _LEGACY_FORMAL_EVIDENCE_SCOPE_PAYLOAD
)

FORMAL_SEMANTIC_ENTITY_TYPES = _type_set(
    _FORMAL_EVIDENCE_SCOPE_PAYLOAD,
    "formal_semantic_entity_types",
)
DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES = _type_set(
    _FORMAL_EVIDENCE_SCOPE_PAYLOAD,
    "diagnostic_only_semantic_entity_types",
)
FORMAL_EVIDENCE_SCOPE_SHA256 = sha256_obj(_FORMAL_EVIDENCE_SCOPE_PAYLOAD)
FORMAL_MINIMUM_GLOBAL_VALID_PAIRS = int(
    _FORMAL_EVIDENCE_SCOPE_PAYLOAD["minimum_global_valid_pairs"]
)
FORMAL_MINIMUM_DATASET_TYPE_VALID_PAIRS = int(
    _FORMAL_EVIDENCE_SCOPE_PAYLOAD["minimum_valid_pairs_per_dataset_type"]
)

_AUDIT = dict(_FORMAL_EVIDENCE_SCOPE_PAYLOAD["audit"])
_EXPECTED_AUDIT = {
    "dataset_stratified": True,
    "datasets_per_type": 3,
    "accepted_per_dataset_type": 36,
    "hard_negatives_per_dataset_type": 4,
    "user_review_per_dataset_type": 4,
    "accepted_per_type": 108,
    "hard_negatives_per_type": 12,
    "user_review_sample_size": 60,
    "minimum_accepted_passes_per_dataset_type": 35,
    "minimum_accepted_rate_per_dataset_type": 0.96,
    "minimum_wilson_95_lower_per_dataset_type": 0.85,
    "minimum_accepted_passes_per_type": 104,
    "minimum_accepted_rate_per_type": 0.96,
    "minimum_wilson_95_lower_per_type": 0.90,
}
if _AUDIT != _EXPECTED_AUDIT:
    raise RuntimeError("Formal dataset-stratified audit scope drift")

FORMAL_AUDIT_DATASETS_PER_TYPE = int(_AUDIT["datasets_per_type"])
FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE = int(
    _AUDIT["accepted_per_dataset_type"]
)
FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE = int(
    _AUDIT["hard_negatives_per_dataset_type"]
)
FORMAL_AUDIT_USER_REVIEW_PER_DATASET_TYPE = int(
    _AUDIT["user_review_per_dataset_type"]
)
FORMAL_AUDIT_ACCEPTED_PER_TYPE = int(_AUDIT["accepted_per_type"])
FORMAL_AUDIT_HARD_NEGATIVES_PER_TYPE = int(
    _AUDIT["hard_negatives_per_type"]
)
FORMAL_AUDIT_USER_REVIEW_SAMPLE_SIZE = int(
    _AUDIT["user_review_sample_size"]
)
FORMAL_AUDIT_MIN_ACCEPTED_PASSES_PER_DATASET_TYPE = int(
    _AUDIT["minimum_accepted_passes_per_dataset_type"]
)
FORMAL_AUDIT_MIN_ACCEPTED_RATE_PER_DATASET_TYPE = float(
    _AUDIT["minimum_accepted_rate_per_dataset_type"]
)
FORMAL_AUDIT_MIN_WILSON_PER_DATASET_TYPE = float(
    _AUDIT["minimum_wilson_95_lower_per_dataset_type"]
)
FORMAL_AUDIT_MIN_ACCEPTED_PASSES_PER_TYPE = int(
    _AUDIT["minimum_accepted_passes_per_type"]
)
FORMAL_AUDIT_MIN_ACCEPTED_RATE_PER_TYPE = float(
    _AUDIT["minimum_accepted_rate_per_type"]
)
FORMAL_AUDIT_MIN_WILSON_PER_TYPE = float(
    _AUDIT["minimum_wilson_95_lower_per_type"]
)

FORMAL_AUDIT_ROWS_PER_DATASET_TYPE = (
    FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE
    + FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE
)
FORMAL_AUDIT_ROWS_PER_TYPE = (
    FORMAL_AUDIT_ACCEPTED_PER_TYPE + FORMAL_AUDIT_HARD_NEGATIVES_PER_TYPE
)
FORMAL_AUDIT_ROWS_PER_DATASET = (
    len(FORMAL_SEMANTIC_ENTITY_TYPES) * FORMAL_AUDIT_ROWS_PER_DATASET_TYPE
)
FORMAL_AUDIT_TOTAL_ROWS = (
    len(FORMAL_SEMANTIC_ENTITY_TYPES) * FORMAL_AUDIT_ROWS_PER_TYPE
)

if (
    FORMAL_AUDIT_ACCEPTED_PER_TYPE
    != FORMAL_AUDIT_DATASETS_PER_TYPE
    * FORMAL_AUDIT_ACCEPTED_PER_DATASET_TYPE
    or FORMAL_AUDIT_HARD_NEGATIVES_PER_TYPE
    != FORMAL_AUDIT_DATASETS_PER_TYPE
    * FORMAL_AUDIT_HARD_NEGATIVES_PER_DATASET_TYPE
    or FORMAL_AUDIT_USER_REVIEW_SAMPLE_SIZE
    != FORMAL_AUDIT_DATASETS_PER_TYPE
    * len(FORMAL_SEMANTIC_ENTITY_TYPES)
    * FORMAL_AUDIT_USER_REVIEW_PER_DATASET_TYPE
):
    raise RuntimeError("Formal audit aggregate quotas are inconsistent")


def formal_evidence_scope_metadata() -> dict[str, Any]:
    return _scope_metadata(
        _FORMAL_EVIDENCE_SCOPE_PAYLOAD,
        FORMAL_EVIDENCE_SCOPE_PATH,
    )


def legacy_formal_evidence_scope_metadata() -> dict[str, Any]:
    return _scope_metadata(
        _LEGACY_FORMAL_EVIDENCE_SCOPE_PAYLOAD,
        LEGACY_FORMAL_EVIDENCE_SCOPE_PATH,
    )


def validate_formal_evidence_scope_metadata(
    payload: Mapping[str, Any] | None,
    *,
    allow_legacy_v1: bool = False,
) -> None:
    actual = dict(payload or {})
    if actual == formal_evidence_scope_metadata():
        return
    if allow_legacy_v1 and actual == legacy_formal_evidence_scope_metadata():
        return
    raise RuntimeError("Formal evidence scope identity mismatch")
