from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "precheck_claim_pair_audit.py"
SPEC = importlib.util.spec_from_file_location("precheck_claim_pair_audit", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _row(**updates: str) -> dict:
    row = {
        "true_claim": "Alice Smith leads the project.",
        "counterfactual_claim": "Jordan Ellis leads the project.",
        "original_entity": "Alice Smith",
        "counterfactual_entity": "Jordan Ellis",
        "entity_type": "PERSON",
    }
    row.update(updates)
    return row


class AssistantClaimPrecheckTests(unittest.TestCase):
    def test_loader_accepts_explicit_rc_sample_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audit_dir = Path(temporary_directory)
            rows = [
                {
                    "audit_id": f"audit_{index}",
                    "human_pair_valid": "",
                }
                for index in range(3)
            ]
            for role, ordered_rows in (
                ("a", rows),
                ("b", list(reversed(rows))),
            ):
                path = audit_dir / f"edgar_claim_pair_audit_annotator_{role}.jsonl"
                path.write_text(
                    "".join(json.dumps(row) + "\n" for row in ordered_rows),
                    encoding="utf-8",
                )

            loaded, hashes = MODULE._load_unique_samples(audit_dir, "edgar", 3)

        self.assertEqual(len(loaded), 3)
        self.assertTrue(hashes["annotator_a_hash"])
        self.assertTrue(hashes["annotator_b_hash"])

    def test_loader_rejects_wrong_explicit_sample_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audit_dir = Path(temporary_directory)
            row = {"audit_id": "audit_0", "human_pair_valid": ""}
            for role in ("a", "b"):
                path = audit_dir / f"edgar_claim_pair_audit_annotator_{role}.jsonl"
                path.write_text(json.dumps(row) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "expected 2 rows"):
                MODULE._load_unique_samples(audit_dir, "edgar", 2)

    def test_semantic_entity_type_requires_review(self) -> None:
        tier, signals = MODULE.precheck_signals(_row())
        self.assertEqual(tier, "needs_review")
        self.assertIn("semantic_entity_type_requires_manual_review", signals)

    def test_structured_money_pair_can_be_low_risk(self) -> None:
        tier, signals = MODULE.precheck_signals(
            _row(
                true_claim="The transaction price was 4.5 million.",
                counterfactual_claim="The transaction price was 7.2 million.",
                original_entity="4.5 million",
                counterfactual_entity="7.2 million",
                entity_type="MONEY",
            )
        )
        self.assertEqual(tier, "low_risk")
        self.assertEqual(signals, [])

    def test_section_heading_person_is_high_risk(self) -> None:
        tier, signals = MODULE.precheck_signals(
            _row(
                true_claim="Conclusions In this work, the method was evaluated.",
                counterfactual_claim="Jordan Ellis this work, the method was evaluated.",
                original_entity="Conclusions In",
            )
        )
        self.assertEqual(tier, "high_risk")
        self.assertIn("person_entity_contains_section_heading", signals)
        self.assertIn("person_entity_ends_with_connector", signals)

    def test_truncated_email_payload_is_high_risk(self) -> None:
        tier, signals = MODULE.precheck_signals(
            _row(
                true_claim="X-From: Alice Smith We are pleased to announ",
                counterfactual_claim="X-From: Jordan Ellis We are pleased to announ",
            )
        )
        self.assertEqual(tier, "high_risk")
        self.assertIn("email_metadata_with_truncated_body", signals)
        self.assertIn("possible_mid_word_or_sentence_truncation", signals)

    def test_plain_word_is_not_an_identifier(self) -> None:
        tier, signals = MODULE.precheck_signals(
            _row(
                true_claim="The study can identify relevant factors.",
                counterfactual_claim="The study can identifyB relevant factors.",
                original_entity="identify",
                counterfactual_entity="identifyB",
                entity_type="IDENTIFIER",
            )
        )
        self.assertEqual(tier, "high_risk")
        self.assertIn("identifier_has_no_identifier_shape", signals)

    def test_valid_alphanumeric_identifier_is_review_not_high_risk(self) -> None:
        tier, signals = MODULE.precheck_signals(
            _row(
                true_claim="The structure used PDB ID: 3EIG in the assay.",
                counterfactual_claim="The structure used PDB ID: 10EIG in the assay.",
                original_entity="ID: 3EIG",
                counterfactual_entity="ID: 10EIG",
                entity_type="IDENTIFIER",
            )
        )
        self.assertEqual(tier, "needs_review")
        self.assertIn("identifier_has_alphanumeric_payload", signals)

    def test_quantity_phrase_identifier_is_high_risk(self) -> None:
        tier, signals = MODULE.precheck_signals(
            _row(
                true_claim="We order 6shots of tequila and three beers.",
                counterfactual_claim="We order 13shots of tequila and three beers.",
                original_entity="order 6shots",
                counterfactual_entity="order 13shots",
                entity_type="IDENTIFIER",
            )
        )
        self.assertEqual(tier, "high_risk")
        self.assertIn("identifier_looks_like_quantity_phrase", signals)

    def test_url_must_not_capture_sentence_punctuation(self) -> None:
        tier, signals = MODULE.precheck_signals(
            _row(
                true_claim="The website is www.example.com, and it is public.",
                counterfactual_claim="The website is www.example.com,/archive and it is public.",
                original_entity="www.example.com,",
                counterfactual_entity="www.example.com,/archive",
                entity_type="URL",
            )
        )
        self.assertEqual(tier, "high_risk")
        self.assertIn("url_entity_captures_trailing_punctuation", signals)

    def test_year_must_keep_numeric_subtype(self) -> None:
        tier, signals = MODULE.precheck_signals(
            _row(
                true_claim="The report covers 2019 results.",
                counterfactual_claim="The report covers 2,120 results.",
                original_entity="2019",
                counterfactual_entity="2,120",
                entity_type="NUMERIC_VALUE",
            )
        )
        self.assertEqual(tier, "high_risk")
        self.assertIn("year_changed_as_generic_numeric_value", signals)


if __name__ == "__main__":
    unittest.main()
