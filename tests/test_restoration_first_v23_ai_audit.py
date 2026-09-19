from __future__ import annotations

import unittest

from src.prepare.restoration_first_v23_ai_audit import _label_rows


class V23AiAuditTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "kind": "v23_blind_audit_packet",
            "opaque_audit_source_id": "a" * 32,
            "packet_order_key": "b" * 64,
            "pair_id": "pair-1",
            "pair_order": 0,
            "complete_source_text": "Alice filed the report.",
            "supporting_sentence": "Alice filed the report.",
            "true_claim": "Alice filed the report.",
            "counterfactual_claim": "Bob filed the report.",
            "original_entity": "Alice",
            "counterfactual_entity": "Bob",
            "effective_type": "PERSON",
        }
        row.update(overrides)
        return row

    def _rows(self, **overrides):
        return [
            self._row(pair_id=f"pair-{pair_order + 1}", pair_order=pair_order, **overrides)
            for pair_order in range(3)
        ]

    def test_structural_pass_is_assistant_only(self):
        labels, counts = _label_rows(self._rows())
        self.assertEqual(counts, {"pass": 3, "fail": 0, "uncertain": 0})
        self.assertEqual(labels[0]["reviewer_role"], "assistant")
        self.assertFalse(labels[0]["human_validation_performed"])

    def test_non_replacement_is_uncertain(self):
        labels, counts = _label_rows(
            self._rows(counterfactual_claim="Bob submitted the report.")
        )
        self.assertEqual(counts, {"pass": 0, "fail": 0, "uncertain": 3})
        self.assertIn("not_exact_single_slot_replacement", labels[0]["reasons"])

    def test_schema_error_is_fail(self):
        labels, counts = _label_rows(self._rows(original_entity="Missing"))
        self.assertEqual(counts, {"pass": 0, "fail": 3, "uncertain": 0})
        self.assertIn("original_entity_absent", labels[0]["reasons"])


if __name__ == "__main__":
    unittest.main()
