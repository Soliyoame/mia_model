from __future__ import annotations

import unittest

from scripts.claim_pair_audit import (
    blind_claim_rows,
    cohen_kappa,
    evaluate_double_annotations,
    filter_audit_exclusions,
    stratified_source_sample,
)


class ClaimPairAuditTests(unittest.TestCase):
    def test_blind_template_omits_automatic_validation_fields(self) -> None:
        row = {
            "dataset": "pubmed",
            "source_key": "PMC1",
            "true_claim": "TP53 was measured in 20 patients.",
            "counterfactual_claim": "TP53 was measured in 30 patients.",
            "original_entity": "20",
            "counterfactual_entity": "30",
            "entity_type": "numeric",
            "claim_validator_version": "local_claim_pair_v1",
        }
        blinded = blind_claim_rows([row], "A")[0]
        self.assertNotIn("claim_validator_version", blinded)
        self.assertEqual(blinded["human_pair_valid"], "")

    def test_sampling_prefers_distinct_sources(self) -> None:
        rows = [
            {
                "source_key": f"source-{index}",
                "group": "KB_Member" if index % 2 else "True_Non_Member",
                "entity_type": "date" if index % 3 else "numeric",
            }
            for index in range(20)
        ]
        sampled = stratified_source_sample(rows, 12, 42)
        self.assertEqual(len(sampled), 12)
        self.assertEqual(len({row["source_key"] for row in sampled}), 12)

    def test_annotators_receive_same_sample_in_different_orders(self) -> None:
        rows = [
            {
                "pair_id": f"pair-{index}",
                "source_key": f"source-{index}",
                "true_claim": f"Claim {index}",
                "counterfactual_claim": f"Counterfactual {index}",
            }
            for index in range(20)
        ]
        rows_a = blind_claim_rows(rows, "A", shuffle_seed=1043)
        rows_b = blind_claim_rows(rows, "B", shuffle_seed=2044)
        ids_a = [row["audit_id"] for row in rows_a]
        ids_b = [row["audit_id"] for row in rows_b]
        self.assertEqual(set(ids_a), set(ids_b))
        self.assertNotEqual(ids_a, ids_b)

    def test_multiple_prior_audit_exclusions_remove_union_of_source_and_pair_overlap(self) -> None:
        rows = [
            {"pair_id": "old-pair-a", "source_key": "new-source-a"},
            {"pair_id": "new-pair-a", "source_key": "old-source-a"},
            {"pair_id": "old-pair-b", "source_key": "new-source-b"},
            {"pair_id": "new-pair-b", "source_key": "old-source-b"},
            {"pair_id": "keep-pair", "source_key": "keep-source"},
        ]
        filtered = filter_audit_exclusions(
            rows,
            source_keys={"old-source-a", "old-source-b"},
            audit_ids={"old-pair-a", "old-pair-b"},
        )
        self.assertEqual(filtered, [{"pair_id": "keep-pair", "source_key": "keep-source"}])

    def test_quality_gate_requires_double_pass_rate_and_kappa(self) -> None:
        rows_a = [
            {"audit_id": str(index), "human_pair_valid": "pass" if index < 19 else "fail"}
            for index in range(20)
        ]
        rows_b = [dict(row) for row in rows_a]
        report = evaluate_double_annotations(
            rows_a,
            rows_b,
            minimum_labeled=20,
            minimum_pass_rate=0.90,
            minimum_kappa=0.80,
        )
        self.assertTrue(report["quality_gate_passed"])
        self.assertEqual(report["double_pass_rate"], 0.95)
        self.assertEqual(report["cohen_kappa"], 1.0)

    def test_kappa_penalizes_chance_agreement(self) -> None:
        self.assertLess(cohen_kappa(["pass", "pass", "fail", "fail"], ["pass", "fail", "pass", "fail"]), 0.8)

    def test_kappa_is_undefined_when_both_annotators_use_one_label(self) -> None:
        self.assertIsNone(cohen_kappa(["pass", "pass"], ["pass", "pass"]))


if __name__ == "__main__":
    unittest.main()
