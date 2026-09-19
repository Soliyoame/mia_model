from __future__ import annotations

import unittest

from src.attack.restoration_first_v23 import relation_signature
from src.attack.restoration_first_v23_fact_layer import (
    FACT_LAYER_SPECIFICATION_VERSION,
    evaluate_fact_candidate,
    fact_signature,
    predicate_kind,
    validate_fact_row,
)


class FactLayerPrimitiveTests(unittest.TestCase):
    def _candidate(self, sentence: str, original: str, effective_type: str = "CONTRACT_TERM") -> tuple[dict, dict]:
        start = sentence.index(original)
        end = start + len(original)
        source = {
            "dataset": "edgar",
            "source_key": "source-1",
            "full_text": sentence,
        }
        candidate = {
            "dataset": "edgar",
            "source_key": "source-1",
            "supporting_sentence": sentence,
            "original_entity": original,
            "original_span": [start, end],
            "effective_type": effective_type,
            "semantic_subtype": "named_agreement",
            "entity_spans": [[start, end]],
            "filler_inventory": [],
            "counterfactual_pool": ["Harborview License Agreement"],
            "proposition_raw_start": 0,
            "proposition_raw_end": len(sentence),
        }
        masked = sentence[:start] + "ENTITY_SLOT" + sentence[end:]
        candidate["filler_inventory"] = [
            {
                "surface": original,
                "effective_type": effective_type,
                "relation_signature": relation_signature(
                    dataset="edgar",
                    source_key="source-1",
                    effective_type=effective_type,
                    masked_sentence=masked,
                ),
                "proposition_raw_start": 0,
                "proposition_raw_end": len(sentence),
                "filler_span": [start, end],
            }
        ]
        return source, candidate

    def test_fact_signature_distinguishes_two_slots_in_one_sentence(self):
        sentence = "Acme Holdings acquired Northstar Services Agreement in Austin."
        left = fact_signature(
            dataset="edgar",
            source_key="source-1",
            sentence=sentence,
            original_span=[0, 12],
            effective_type="ORG",
        )
        right = fact_signature(
            dataset="edgar",
            source_key="source-1",
            sentence=sentence,
            original_span=[25, 52],
            effective_type="CONTRACT_TERM",
        )
        self.assertNotEqual(left, right)

    def test_predicate_classifier_does_not_require_old_relation_cue(self):
        self.assertEqual(
            predicate_kind("Revenue for 2024: $10 million."),
            "measurement_assertion",
        )
        self.assertEqual(
            predicate_kind("The agreement remains active."),
            "relational_assertion",
        )
        self.assertEqual(predicate_kind("Annual Revenue"), "fragment_or_nominal")

    def test_valid_fact_is_p0_ready_without_source_specific_anchor(self):
        source, candidate = self._candidate(
            "Acme Holdings acquired Northstar Services Agreement in Austin, Texas in 2024.",
            "Northstar Services Agreement",
        )
        row = evaluate_fact_candidate(source, candidate, token_df={}, source_count=100)
        self.assertTrue(row["fact_valid"])
        self.assertTrue(row["retrieval_usable"])
        self.assertTrue(row["p0_ready"])
        self.assertEqual(row["source_specific_anchor_count"], 0)
        self.assertEqual(row["rejection_codes"], [])
        validate_fact_row(row)

    def test_entity_inside_relation_cue_is_not_an_exception(self):
        source, candidate = self._candidate(
            "Will the Northstar Services Agreement with Harborview Partners expire.",
            "Will",
        )
        candidate["effective_type"] = "CONTRACT_TERM"
        candidate["semantic_subtype"] = "named_agreement"
        row = evaluate_fact_candidate(source, candidate)
        self.assertIsInstance(row["rejection_codes"], list)
        self.assertNotIn("StopIteration", row["rejection_codes"])

    def test_unresolved_reference_remains_a_fact_failure(self):
        source, candidate = self._candidate(
            "This agreement acquired Northstar Services Agreement in Austin, Texas.",
            "Northstar Services Agreement",
        )
        row = evaluate_fact_candidate(source, candidate)
        self.assertFalse(row["fact_valid"])
        self.assertIn("unresolved_reference", row["rejection_codes"])
        self.assertEqual(row["external_calls_performed"], 0)


if __name__ == "__main__":
    unittest.main()

