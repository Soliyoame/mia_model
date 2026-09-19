from __future__ import annotations

import unittest

from src.attack.restoration_first_v23_fact_layer_selection_r2 import (
    SELECTION_R2_SPECIFICATION_VERSION,
    quality_rejection_codes,
    select_pairs_from_r1_facts,
)


CONFIG = {
    "required_pairs_per_source": 3,
    "maximum_pairs_per_original_entity": 2,
    "require_distinct_fact_signatures": True,
    "quality_filters": {
        "reject_mail_metadata": True,
        "mail_header_labels": [
            "from",
            "to",
            "cc",
            "bcc",
            "subject",
            "sent",
            "date",
            "message-id",
            "content-type",
            "start date",
        ],
        "always_embedded_mail_header_labels": [
            "subject",
            "message-id",
            "content-type",
        ],
        "minimum_embedded_mail_header_count": 2,
        "reject_metadata_prefixes": ["author contributions", "table"],
        "reject_structured_numeric_formal_entities": True,
        "generic_original_values": [
            "company",
            "the company",
            "organization",
            "the organization",
        ],
        "reject_all_caps_person_surfaces": True,
        "person_incompatible_terms": [
            "characteristics",
            "hand",
            "information",
            "median",
            "mice",
        ],
        "person_incompatible_exact_values": [
            "middle eastern",
            "thermo fisher",
            "united states",
        ],
    },
}


def _fact(
    signature: str,
    original: str,
    *,
    effective_type: str = "ORG",
    sentence: str | None = None,
    source_key: str = "source-1",
) -> dict:
    claim = sentence or f"{original} signed the agreement with Harborview Partners."
    start = claim.index(original)
    return {
        "p0_ready": True,
        "source_key": source_key,
        "source_order_rank": "01",
        "source_hash": "a" * 64,
        "normalized_text_hash": "b" * 64,
        "fact_signature": signature,
        "relation_signature": "c" * 64,
        "original_span": [start, start + len(original)],
        "original_value": original,
        "effective_type": effective_type,
        "semantic_subtype": "named_organization",
        "proposition_text": claim,
        "replacement_candidates": ["Vanta Industries"],
    }


class SelectionR2QualityTests(unittest.TestCase):
    def test_rejects_mail_metadata_anywhere_with_header_evidence(self):
        row = _fact(
            "1" * 64,
            "PLOS ONE",
            effective_type="PERSON",
            sentence=(
                '8 Aug 2020 Date: Jul 29 2020 08:52AM To: "PLOS ONE" '
                "plosone@plos."
            ),
        )
        self.assertIn("mail_metadata", quality_rejection_codes(row, CONFIG))

    def test_rejects_numeric_formal_slots_and_generic_placeholders(self):
        numeric = _fact(
            "2" * 64,
            "2 acres",
            effective_type="LOCATION",
            sentence="2 acres on which the injection wells are located.",
        )
        generic = _fact("3" * 64, "The Company")
        self.assertIn(
            "structured_numeric_formal_entity",
            quality_rejection_codes(numeric, CONFIG),
        )
        self.assertIn(
            "generic_original_entity", quality_rejection_codes(generic, CONFIG)
        )

    def test_rejects_clear_person_surface_mismatch(self):
        row = _fact(
            "4" * 64,
            "human hand",
            effective_type="PERSON",
            sentence="The system reproduces the synergies of the human hand.",
        )
        self.assertIn(
            "person_surface_role_incompatible",
            quality_rejection_codes(row, CONFIG),
        )

    def test_keeps_awkward_but_type_compatible_probe(self):
        row = _fact(
            "5" * 64,
            "Acme Holdings",
            sentence="Acme Holdings did not recognize interest or penalties.",
        )
        self.assertEqual(quality_rejection_codes(row, CONFIG), [])

    def test_selection_refills_from_existing_r1_facts(self):
        facts = [
            _fact("1" * 64, "The Company"),
            _fact("2" * 64, "Acme Holdings"),
            _fact("3" * 64, "Austin", effective_type="LOCATION"),
            _fact("4" * 64, "Northstar Agreement", effective_type="CONTRACT_TERM"),
        ]
        result = select_pairs_from_r1_facts(
            facts,
            dataset="edgar",
            selection_identity_sha256="d" * 64,
            config=CONFIG,
        )
        self.assertEqual(result["eligible_source_count"], 1)
        self.assertEqual(len(result["selected"]), 3)
        self.assertEqual(result["quality_rejected_fact_count"], 1)
        self.assertTrue(
            all(
                row["specification_version"] == SELECTION_R2_SPECIFICATION_VERSION
                for row in result["selected"]
            )
        )

    def test_forbidden_downstream_fields_remain_fail_closed(self):
        row = _fact("6" * 64, "Acme Holdings")
        row["membership"] = "member"
        with self.assertRaisesRegex(ValueError, "forbidden_selection_field"):
            select_pairs_from_r1_facts(
                [row],
                dataset="edgar",
                selection_identity_sha256="d" * 64,
                config=CONFIG,
            )


if __name__ == "__main__":
    unittest.main()
