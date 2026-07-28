import unittest

from scripts.adjudicate_claim_pair_audit import (
    DATASETS,
    MACHINE_FIELDS,
    build_adjudication_rows,
    failure_decisions,
)


def _row(dataset: str, audit_id: str, role: str) -> dict[str, str]:
    row = {
        "audit_id": audit_id,
        "dataset": dataset,
        "source_key": f"source-{audit_id}",
        "entity_type": "PERSON",
        "original_entity": "Original",
        "counterfactual_entity": "Replacement",
        "true_claim": "Original appears here.",
        "counterfactual_claim": "Replacement appears here.",
        "annotator_role": role,
        "human_pair_valid": "pass",
        "human_failure_reason": "",
        "audit_notes": "",
    }
    assert all(field in row for field in MACHINE_FIELDS)
    return row


class AiAdjudicationTest(unittest.TestCase):
    def test_failure_decisions_have_no_duplicate_ids(self) -> None:
        expected_counts = {"edgar": 100, "enron": 112, "pubmed": 89}
        for dataset in DATASETS:
            decisions = failure_decisions(dataset)
            self.assertEqual(len(decisions), len(set(decisions)))
            self.assertEqual(len(decisions), expected_counts[dataset])
            self.assertTrue(
                all(audit_id.startswith(f"pair_{dataset}_audit_") for audit_id in decisions)
            )

    def test_rejects_incomplete_dataset(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected 200 rows"):
            build_adjudication_rows(
                "edgar",
                [_row("edgar", "one", "A")],
                [_row("edgar", "one", "B")],
                {},
            )

    def test_rejects_machine_field_difference(self) -> None:
        audit_ids = [f"pair_edgar_audit_demo_{index:03d}" for index in range(200)]
        rows_a = [_row("edgar", audit_id, "A") for audit_id in audit_ids]
        rows_b = [_row("edgar", audit_id, "B") for audit_id in audit_ids]
        rows_b[0]["true_claim"] = "Different machine field."
        with self.assertRaisesRegex(ValueError, "machine field"):
            build_adjudication_rows("edgar", rows_a, rows_b, {})


if __name__ == "__main__":
    unittest.main()
