from __future__ import annotations

import unittest

from scripts.check_quality_gates import evaluate_quality_reports


class QualityGateTests(unittest.TestCase):
    def test_requires_every_dataset_generator_report_exactly_once(self) -> None:
        config = {
            "claim_pair_audit": {
                "datasets": ["edgar", "pubmed"],
                "pairs_per_dataset": 200,
                "minimum_double_pass_rate": 0.90,
                "minimum_cohen_kappa": 0.80,
            },
            "stance_parser_audit": {
                "datasets": ["edgar", "pubmed"],
                "generators": ["g1", "g2"],
                "responses_per_dataset_generator": 100,
                "expected_total_responses": 400,
                "minimum_macro_f1": 0.95,
            },
        }
        claims = [
            {
                "dataset": dataset,
                "quality_gate_passed": True,
                "double_labeled_rows": 200,
                "double_pass_rate": 0.95,
                "cohen_kappa": 0.90,
            }
            for dataset in ("edgar", "pubmed")
        ]
        stances = [
            {
                "dataset": dataset,
                "model": model,
                "quality_gate_passed": True,
                "labeled_rows": 100,
                "macro_f1": 0.97,
            }
            for dataset in ("edgar", "pubmed")
            for model in ("g1", "g2")
        ]
        self.assertTrue(evaluate_quality_reports(config, claims, stances)["quality_gate_passed"])
        self.assertFalse(evaluate_quality_reports(config, claims, stances[:-1])["quality_gate_passed"])

    def test_rejects_failed_or_duplicate_report(self) -> None:
        config = {
            "claim_pair_audit": {"datasets": ["edgar"]},
            "stance_parser_audit": {
                "datasets": ["edgar"],
                "generators": ["g1"],
                "expected_total_responses": 100,
            },
        }
        claims = [{"dataset": "edgar", "quality_gate_passed": False}]
        stance = {"dataset": "edgar", "model": "g1", "quality_gate_passed": True}
        report = evaluate_quality_reports(config, claims, [stance, dict(stance)])
        self.assertFalse(report["quality_gate_passed"])
        self.assertEqual(report["failed_claim_pair_reports"], ["edgar"])
        self.assertEqual(report["duplicate_stance_reports"], ["edgar::g1"])

    def test_recomputes_frozen_sample_size_and_rejects_unexpected_report(self) -> None:
        config = {
            "claim_pair_audit": {
                "datasets": ["edgar"],
                "pairs_per_dataset": 200,
                "minimum_double_pass_rate": 0.90,
                "minimum_cohen_kappa": 0.80,
            },
            "stance_parser_audit": {
                "datasets": ["edgar"],
                "generators": ["g1"],
                "responses_per_dataset_generator": 100,
                "expected_total_responses": 100,
                "minimum_macro_f1": 0.95,
            },
        }
        claims = [
            {
                "dataset": "edgar",
                "quality_gate_passed": True,
                "double_labeled_rows": 1,
                "double_pass_rate": 1.0,
                "cohen_kappa": 1.0,
            },
            {"dataset": "stale", "quality_gate_passed": True},
        ]
        stances = [
            {
                "dataset": "edgar",
                "model": "g1",
                "quality_gate_passed": True,
                "labeled_rows": 100,
                "macro_f1": 0.96,
            }
        ]
        report = evaluate_quality_reports(config, claims, stances)
        self.assertFalse(report["quality_gate_passed"])
        self.assertIn("edgar", report["failed_claim_pair_reports"])
        self.assertEqual(report["unexpected_claim_pair_reports"], ["stale"])


if __name__ == "__main__":
    unittest.main()
