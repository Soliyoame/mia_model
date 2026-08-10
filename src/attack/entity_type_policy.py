"""冻结且可哈希的实体类型策略。

该模块是 extractor、semantic resolver、扰动器和 validator 的共同类型来源。
配置漂移必须改变 ``ENTITY_TYPE_POLICY_SHA256``，从而使旧 checkpoint 拒绝续跑。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..utils.hash import sha256_obj
from ..utils.io import load_yaml


ENTITY_TYPE_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "entity_type_policy_v21_r1.yaml"
)
EXPECTED_ENTITY_TYPES = frozenset(
    {
        "URL",
        "EMAIL",
        "PHONE",
        "SECTION_ID",
        "IDENTIFIER",
        "MONEY",
        "MEDICAL_VALUE",
        "PERCENT",
        "NUMERIC_VALUE",
        "DATE",
        "TIME",
        "DURATION",
        "PERSON",
        "ORG",
        "LOCATION",
        "PRODUCT",
        "PROJECT_NAME",
        "CONTRACT_TERM",
    }
)


@dataclass(frozen=True)
class EntityTypePolicy:
    """单个实体类型的冻结行为描述。"""

    entity_type: str
    family: str
    semantic_required: bool
    allowed_subtypes: tuple[str, ...]
    surface_rule: str
    context_rule: str
    replacement_strategy: str
    format_rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "family": self.family,
            "semantic_required": self.semantic_required,
            "allowed_subtypes": list(self.allowed_subtypes),
            "surface_rule": self.surface_rule,
            "context_rule": self.context_rule,
            "replacement_strategy": self.replacement_strategy,
            "format_rule": self.format_rule,
        }


def _string_mapping(value: object, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise RuntimeError(f"Entity policy {field} must be a non-empty mapping")
    rows = {str(key): str(item) for key, item in value.items()}
    if any(not key or not item for key, item in rows.items()):
        raise RuntimeError(f"Entity policy {field} contains an empty entry")
    return rows


def _load_policy(path: Path) -> tuple[
    str,
    Mapping[str, EntityTypePolicy],
    Mapping[str, str],
    Mapping[str, str],
    Mapping[str, tuple[str, ...]],
    str,
]:
    payload = load_yaml(path)
    version = str(payload.get("policy_version") or "").strip()
    if version != "pcv_entity_policy_v21_r1":
        raise RuntimeError(f"Unexpected entity policy version: {version!r}")

    raw_types = payload.get("types")
    if not isinstance(raw_types, dict):
        raise RuntimeError("Entity policy types must be a mapping")
    actual_types = {str(key).upper() for key in raw_types}
    if actual_types != EXPECTED_ENTITY_TYPES:
        raise RuntimeError(
            "Entity policy type coverage mismatch: "
            f"missing={sorted(EXPECTED_ENTITY_TYPES - actual_types)} "
            f"extra={sorted(actual_types - EXPECTED_ENTITY_TYPES)}"
        )

    policies: dict[str, EntityTypePolicy] = {}
    for raw_name, raw_policy in raw_types.items():
        name = str(raw_name).upper()
        if not isinstance(raw_policy, dict):
            raise RuntimeError(f"Entity policy {name} must be a mapping")
        allowed = raw_policy.get("allowed_subtypes") or []
        if not isinstance(allowed, list):
            raise RuntimeError(f"Entity policy {name} allowed_subtypes must be a list")
        policy = EntityTypePolicy(
            entity_type=name,
            family=str(raw_policy.get("family") or ""),
            semantic_required=bool(raw_policy.get("semantic_required")),
            allowed_subtypes=tuple(str(item) for item in allowed),
            surface_rule=str(raw_policy.get("surface_rule") or ""),
            context_rule=str(raw_policy.get("context_rule") or ""),
            replacement_strategy=str(raw_policy.get("replacement_strategy") or ""),
            format_rule=str(raw_policy.get("format_rule") or ""),
        )
        required = (
            policy.family,
            policy.surface_rule,
            policy.context_rule,
            policy.replacement_strategy,
            policy.format_rule,
        )
        if any(not value for value in required):
            raise RuntimeError(f"Entity policy {name} is incomplete")
        if policy.semantic_required and not policy.allowed_subtypes:
            raise RuntimeError(f"Semantic entity policy {name} has no subtypes")
        policies[name] = policy

    schema = payload.get("semantic_schema")
    if not isinstance(schema, dict):
        raise RuntimeError("Entity policy semantic_schema must be a mapping")
    target_types = _string_mapping(schema.get("target_types"), "target_types")
    target_subtypes = _string_mapping(
        schema.get("target_subtypes"),
        "target_subtypes",
    )
    semantic_types = {
        name for name, policy in policies.items() if policy.semantic_required
    }
    if set(target_types) != semantic_types:
        raise RuntimeError("Semantic schema and policy type sets do not match")

    raw_candidates = payload.get("semantic_replacement_candidates")
    if not isinstance(raw_candidates, dict):
        raise RuntimeError("Entity policy replacement candidates must be a mapping")
    candidates: dict[str, tuple[str, ...]] = {}
    for subtype, raw_values in raw_candidates.items():
        if not isinstance(raw_values, list) or len(raw_values) < 2:
            raise RuntimeError(
                f"Semantic replacement pool {subtype!r} needs at least two values"
            )
        values = tuple(str(item).strip() for item in raw_values)
        if any(not value for value in values) or len(set(values)) != len(values):
            raise RuntimeError(f"Semantic replacement pool {subtype!r} is invalid")
        candidates[str(subtype)] = values
    expected_subtypes = {
        subtype
        for policy in policies.values()
        for subtype in policy.allowed_subtypes
    }
    if set(candidates) != expected_subtypes:
        raise RuntimeError(
            "Semantic replacement subtype coverage mismatch: "
            f"missing={sorted(expected_subtypes - set(candidates))} "
            f"extra={sorted(set(candidates) - expected_subtypes)}"
        )

    return (
        version,
        MappingProxyType(policies),
        MappingProxyType(target_types),
        MappingProxyType(target_subtypes),
        MappingProxyType(candidates),
        sha256_obj(payload),
    )


(
    ENTITY_TYPE_POLICY_VERSION,
    ENTITY_TYPE_POLICIES,
    TARGET_TYPE_SCHEMA,
    TARGET_SUBTYPE_SCHEMA,
    SEMANTIC_REPLACEMENT_CANDIDATES,
    ENTITY_TYPE_POLICY_SHA256,
) = _load_policy(ENTITY_TYPE_POLICY_PATH)

SUPPORTED_ENTITY_TYPES = frozenset(ENTITY_TYPE_POLICIES)
SEMANTIC_TARGET_TYPES = frozenset(
    name
    for name, policy in ENTITY_TYPE_POLICIES.items()
    if policy.semantic_required
)


def entity_type_policy(entity_type: str) -> EntityTypePolicy:
    """返回指定类型的冻结策略；未知类型 fail closed。"""

    kind = str(entity_type or "").upper()
    try:
        return ENTITY_TYPE_POLICIES[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported entity type: {entity_type!r}") from exc


def entity_policy_metadata() -> dict[str, Any]:
    """返回可写入 manifest/checkpoint 的策略身份。"""

    return {
        "policy_version": ENTITY_TYPE_POLICY_VERSION,
        "policy_sha256": ENTITY_TYPE_POLICY_SHA256,
        "policy_path": str(ENTITY_TYPE_POLICY_PATH),
        "supported_entity_types": sorted(SUPPORTED_ENTITY_TYPES),
        "semantic_entity_types": sorted(SEMANTIC_TARGET_TYPES),
    }
