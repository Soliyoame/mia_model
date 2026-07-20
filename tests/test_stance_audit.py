from __future__ import annotations

import unittest

from scripts.stance_audit import (
    attach_parser_predictions,
    blind_annotation_rows,
    evaluate_annotations,
    parser_prediction_hash,
    stratified_sample,
)


class StanceAuditTests(unittest.TestCase):
    def test_annotation_template_hides_parser_prediction(self) -> None:
        rows = [{
            "dataset": "edgar",
            "query_id": "q1",
            "stance": "supports_true_claim",
            "human_stance": "",
        }]
        blinded = blind_annotation_rows(rows)
        self.assertNotIn("stance", blinded[0])
        self.assertIn("stance", rows[0])

    def test_frozen_parser_prediction_is_restored_for_evaluation(self) -> None:
        rows = [{"dataset": "edgar", "query_id": "q1", "human_stance": "unknown"}]
        joined = attach_parser_predictions(rows, {("edgar", "q1"): "unknown"})
        self.assertEqual(joined[0]["stance"], "unknown")
        self.assertEqual(
            parser_prediction_hash(joined),
            parser_prediction_hash([{**rows[0], "stance": "unknown"}]),
        )

    def test_stratified_sample_covers_available_strata(self) -> None:
        rows = [
            {"group": "KB_Member", "claim_type": "true", "query_id": "a"},
            {"group": "KB_Member", "claim_type": "counterfactual", "query_id": "b"},
            {"group": "True_Non_Member", "claim_type": "true", "query_id": "c"},
            {"group": "True_Non_Member", "claim_type": "counterfactual", "query_id": "d"},
        ]
        sampled = stratified_sample(rows, 4, 42)
        self.assertEqual(len(sampled), 4)
        self.assertEqual(len({(row["group"], row["claim_type"]) for row in sampled}), 4)

    def test_evaluation_reports_accuracy_macro_f1_and_confusion(self) -> None:
        rows = [
            {"stance": "supports_true_claim", "human_stance": "supports_true_claim"},
            {"stance": "unknown", "human_stance": "supports_true_claim"},
        ]
        result = evaluate_annotations(rows)
        self.assertEqual(result["labeled_rows"], 2)
        self.assertEqual(result["accuracy"], 0.5)
        self.assertIn("supports_true_claim", result["confusion_matrix"])

    def test_joint_sampling_stratifies_by_dataset_too(self) -> None:
        rows = [
            {"dataset": dataset, "group": group, "claim_type": claim, "query_id": f"{dataset}-{group}-{claim}"}
            for dataset in ("edgar", "enron")
            for group in ("KB_Member", "True_Non_Member")
            for claim in ("true", "counterfactual")
        ]
        sampled = stratified_sample(rows, 8, 42)
        self.assertEqual(len(sampled), 8)
        self.assertEqual(
            len({(row["dataset"], row["group"], row["claim_type"]) for row in sampled}),
            8,
        )

    def test_invalid_human_label_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_annotations([{"stance": "unknown", "human_stance": "maybe"}])


if __name__ == "__main__":
    unittest.main()
