"""Fail-closed schema for the entity-policy blinded audit boundary."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from ..utils.hash import sha256_obj


AUDIT_PROTOCOL = "v21_entity_policy_audit_v5_blind_subtype_redaction_r1"
BLINDED_AUDIT_SCHEMA_VERSION = (
    "v21_entity_policy_audit_blinded_v2_no_machine_subtype"
)

BLINDED_AUDIT_ALLOWED_FIELDS = frozenset(
    {
        "audit_id",
        "dataset",
        "source_key",
        "entity_type",
        "true_claim",
        "counterfactual_claim",
        "original_entity",
        "counterfactual_entity",
        "model_judgment",
        "type_correct",
        "original_supported",
        "single_slot_counterfactual",
        "subtype_preserved",
        "reason_codes",
        "evidence",
    }
)
BLINDED_AUDIT_REDACTED_FIELDS = frozenset(
    {
        "semantic_subtype",
        "original_semantic_resolution",
        "counterfactual_semantic_resolution",
        "audit_hard_negative_reason",
        "hard_negative_reason",
        "expected_policy_decision",
        "source_path",
        "pair_id",
        "fact_id",
        "audit_bucket",
    }
)
BLINDED_AUDIT_EMPTY_STRING_FIELDS = frozenset(
    {
        "model_judgment",
        "type_correct",
        "original_supported",
        "single_slot_counterfactual",
        "subtype_preserved",
        "evidence",
    }
)
BLINDED_AUDIT_FORBIDDEN_VALUES = frozenset({"mismatched_donor_type"})


def blinded_audit_schema_metadata() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": BLINDED_AUDIT_SCHEMA_VERSION,
        "allowed_fields": sorted(BLINDED_AUDIT_ALLOWED_FIELDS),
        "redacted_fields": sorted(BLINDED_AUDIT_REDACTED_FIELDS),
        "empty_string_fields": sorted(BLINDED_AUDIT_EMPTY_STRING_FIELDS),
        "forbidden_values": sorted(BLINDED_AUDIT_FORBIDDEN_VALUES),
    }
    payload["schema_sha256"] = sha256_obj(payload)
    return payload


def validate_blinded_audit_schema_metadata(
    payload: Mapping[str, Any] | None,
) -> None:
    if dict(payload or {}) != blinded_audit_schema_metadata():
        raise RuntimeError("Blinded audit schema identity mismatch")


def validate_blinded_audit_rows(
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """Reject hidden labels, internal subtypes, and prefilled judgments."""

    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        fields = frozenset(str(field) for field in row)
        if fields != BLINDED_AUDIT_ALLOWED_FIELDS:
            leaked = sorted(fields & BLINDED_AUDIT_REDACTED_FIELDS)
            missing = sorted(BLINDED_AUDIT_ALLOWED_FIELDS - fields)
            unexpected = sorted(fields - BLINDED_AUDIT_ALLOWED_FIELDS)
            raise RuntimeError(
                "Blinded audit schema violation at row "
                f"{index}: leaked={leaked}, missing={missing}, "
                f"unexpected={unexpected}"
            )
        audit_id = str(row.get("audit_id") or "")
        if not audit_id or audit_id in seen_ids:
            raise RuntimeError(
                f"Blinded audit ID missing or duplicated at row {index}"
            )
        seen_ids.add(audit_id)
        for field in BLINDED_AUDIT_EMPTY_STRING_FIELDS:
            if row.get(field) != "":
                raise RuntimeError(
                    "Blinded audit contains a prefilled judgment at row "
                    f"{index}: {field}"
                )
        if row.get("reason_codes") != []:
            raise RuntimeError(
                f"Blinded audit contains prefilled reason codes at row {index}"
            )
        forbidden = sorted(
            value
            for value in BLINDED_AUDIT_FORBIDDEN_VALUES
            if any(item == value for item in row.values())
        )
        if forbidden:
            raise RuntimeError(
                "Blinded audit contains an internal sentinel at row "
                f"{index}: {forbidden}"
            )
