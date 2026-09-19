from __future__ import annotations

import unittest

from src.attack.entity_extractor import PATTERN_REGISTRY
from src.attack.entity_type_policy import (
    ENTITY_TYPE_POLICIES,
    ENTITY_TYPE_POLICY_SHA256,
    ENTITY_TYPE_POLICY_VERSION,
    SEMANTIC_REPLACEMENT_CANDIDATES,
    SEMANTIC_TARGET_TYPES,
    SUPPORTED_ENTITY_TYPES,
)
from src.attack.semantic_entity_resolver import (
    SEMANTIC_RESOLVER_PROTOCOL,
    SEMANTIC_SCHEMA_SHA256,
    semantic_format_signature,
)
from src.paired_claims.validator import validate_claim_pair
from src.prepare.formal_evidence_scope import (
    DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES,
    FORMAL_EVIDENCE_SCOPE_SHA256,
    FORMAL_SEMANTIC_ENTITY_TYPES,
)


def _resolution(
    value: str,
    entity_type: str,
    subtype: str,
    *,
    accepted: bool = True,
) -> dict[str, object]:
    return {
        "accepted": accepted,
        "entity_type": entity_type,
        "text": value,
        "subtype": subtype,
        "format_signature": semantic_format_signature(value, entity_type),
        "failure_reasons": [] if accepted else ["semantic_competing_type_detected"],
        "protocol": SEMANTIC_RESOLVER_PROTOCOL,
        "schema_sha256": SEMANTIC_SCHEMA_SHA256,
        "entity_policy_version": ENTITY_TYPE_POLICY_VERSION,
        "entity_policy_sha256": ENTITY_TYPE_POLICY_SHA256,
    }


class EntityTypePolicyTests(unittest.TestCase):
    def test_policy_covers_exactly_all_extractor_types(self) -> None:
        extractor_types = {spec.entity_type for spec in PATTERN_REGISTRY}
        self.assertEqual(18, len(SUPPORTED_ENTITY_TYPES))
        self.assertEqual(SUPPORTED_ENTITY_TYPES, extractor_types)
        self.assertEqual(
            {
                "PERSON",
                "ORG",
                "LOCATION",
                "PRODUCT",
                "PROJECT_NAME",
                "CONTRACT_TERM",
            },
            set(SEMANTIC_TARGET_TYPES),
        )

    def test_policy_hash_and_semantic_schema_are_frozen(self) -> None:
        self.assertEqual("pcv_entity_policy_v21_r1", ENTITY_TYPE_POLICY_VERSION)
        self.assertEqual(64, len(ENTITY_TYPE_POLICY_SHA256))
        self.assertEqual(
            "1e50ffc451e01f85d64e5013bf4e76de5e462c5ca6ed0e445fccdb8bd9e1ffeb",
            SEMANTIC_SCHEMA_SHA256,
        )

    def test_formal_scope_partitions_semantic_types(self) -> None:
        self.assertEqual(
            set(FORMAL_SEMANTIC_ENTITY_TYPES)
            | set(DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES),
            set(SEMANTIC_TARGET_TYPES),
        )
        self.assertTrue(
            set(FORMAL_SEMANTIC_ENTITY_TYPES).isdisjoint(
                DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES
            )
        )
        self.assertNotIn("PROJECT_NAME", FORMAL_SEMANTIC_ENTITY_TYPES)
        self.assertIn("PROJECT_NAME", DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES)
        self.assertEqual(64, len(FORMAL_EVIDENCE_SCOPE_SHA256))

    def test_every_semantic_subtype_has_one_shared_replacement_pool(self) -> None:
        expected = {
            subtype
            for policy in ENTITY_TYPE_POLICIES.values()
            for subtype in policy.allowed_subtypes
        }
        self.assertEqual(expected, set(SEMANTIC_REPLACEMENT_CANDIDATES))
        self.assertTrue(
            all(len(values) >= 2 for values in SEMANTIC_REPLACEMENT_CANDIDATES.values())
        )

    def test_frozen_semantic_org_accepts_real_acronym_without_heuristic_veto(self) -> None:
        original = "ENA"
        replacement = "Vanta Industries"
        result = validate_claim_pair(
            "ENA issued the annual report to its counterparties.",
            "Vanta Industries issued the annual report to its counterparties.",
            original,
            replacement,
            "ORG",
            entity_metadata={
                "candidate_sources": ["gliner2_large"],
                "semantic_resolution": _resolution(
                    original,
                    "ORG",
                    "named_organization",
                ),
            },
            counterfactual_semantic_resolution=_resolution(
                replacement,
                "ORG",
                "named_organization",
            ),
            semantic_resolution_required=True,
        )
        self.assertTrue(result.valid, result.reasons)

    def test_frozen_semantic_contract_accepts_named_agreement(self) -> None:
        original = "Confidentiality Agreement"
        replacement = "Northstar Services Agreement"
        result = validate_claim_pair(
            "Under the Confidentiality Agreement, the parties shall preserve records.",
            "Under the Northstar Services Agreement, the parties shall preserve records.",
            original,
            replacement,
            "CONTRACT_TERM",
            entity_metadata={
                "candidate_sources": ["gliner2_large"],
                "semantic_resolution": _resolution(
                    original,
                    "CONTRACT_TERM",
                    "named_agreement",
                ),
            },
            counterfactual_semantic_resolution=_resolution(
                replacement,
                "CONTRACT_TERM",
                "named_agreement",
            ),
            semantic_resolution_required=True,
        )
        self.assertTrue(result.valid, result.reasons)

    def test_rejected_semantic_org_cannot_bypass_technical_veto(self) -> None:
        result = validate_claim_pair(
            "HEK expression increased after treatment.",
            "Vanta Industries expression increased after treatment.",
            "HEK",
            "Vanta Industries",
            "ORG",
            entity_metadata={
                "candidate_sources": ["gliner2_large"],
                "semantic_resolution": _resolution(
                    "HEK",
                    "ORG",
                    "named_organization",
                    accepted=False,
                ),
            },
            counterfactual_semantic_resolution=_resolution(
                "Vanta Industries",
                "ORG",
                "named_organization",
            ),
            semantic_resolution_required=True,
        )
        self.assertFalse(result.valid)
        self.assertIn("original_semantic_resolution_rejected", result.reasons)
        self.assertIn(
            "original_org_technical_or_biological_token",
            result.reasons,
        )

    def test_semantic_policy_or_subtype_drift_fails_closed(self) -> None:
        original = _resolution("ENA", "ORG", "named_organization")
        counterfactual = _resolution(
            "Orion Services Inc",
            "ORG",
            "named_organization",
        )
        counterfactual["entity_policy_sha256"] = "drifted"
        result = validate_claim_pair(
            "ENA approved the filing.",
            "Orion Services Inc approved the filing.",
            "ENA",
            "Orion Services Inc",
            "ORG",
            entity_metadata={
                "candidate_sources": ["gliner2_large"],
                "semantic_resolution": original,
            },
            counterfactual_semantic_resolution=counterfactual,
            semantic_resolution_required=True,
        )
        self.assertFalse(result.valid)
        self.assertIn(
            "counterfactual_semantic_entity_policy_hash_mismatch",
            result.reasons,
        )

        counterfactual = _resolution(
            "Orion Services Inc",
            "ORG",
            "not_an_allowed_subtype",
        )
        result = validate_claim_pair(
            "ENA approved the filing.",
            "Orion Services Inc approved the filing.",
            "ENA",
            "Orion Services Inc",
            "ORG",
            entity_metadata={
                "candidate_sources": ["gliner2_large"],
                "semantic_resolution": original,
            },
            counterfactual_semantic_resolution=counterfactual,
            semantic_resolution_required=True,
        )
        self.assertFalse(result.valid)
        self.assertIn(
            "counterfactual_semantic_subtype_not_allowed",
            result.reasons,
        )


if __name__ == "__main__":
    unittest.main()
