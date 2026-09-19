from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.prepare.attackability_calibration_r2 import (
    R2_EVALUATION_PROTOCOL,
    _anonymous_review_id,
    _available_rows,
    _r2_blinded_review_row,
    _r1_exclusions,
    _source_evidence_excerpt,
    evaluate_calibration_r2,
    load_r2_config,
)
from src.prepare.attackability_v22 import REVIEW_FIELDS, _identity
from src.utils.hash import sha256_file, sha256_obj


def _label(review_id: str, value: str) -> dict[str, object]:
    return {
        "review_id": review_id,
        **{field: value for field in REVIEW_FIELDS},
        "reason_codes": [],
        "evidence": "blind assistant decision",
    }


class AttackabilityCalibrationR2Tests(unittest.TestCase):
    def test_config_explicitly_disallows_human_validation_claim(self):
        config = load_r2_config("configs/attackability_calibration_r2.yaml")
        self.assertEqual(
            config["review"]["mode"], "assistant_only_no_human_validation"
        )
        self.assertFalse(config["review"]["human_review_required"])
        self.assertFalse(config["review"]["human_validation_claim_allowed"])
        self.assertFalse(config["superseded_r1"]["reuse_labels"])

    def test_review_ids_do_not_reveal_dataset_type_or_control(self):
        review_id = _anonymous_review_id(
            "control", "pubmed", "PERSON", "generic_nominal_fragment", "pair-1"
        )
        self.assertTrue(review_id.startswith("v22_c2_"))
        for leaked in ("pubmed", "PERSON", "control", "generic"):
            self.assertNotIn(leaked, review_id)

    def test_blinded_rows_hide_dataset_type_and_control_metadata(self):
        row = _r2_blinded_review_row(
            "v22_c2_abc",
            {
                "dataset": "pubmed",
                "effective_type": "PERSON",
                "true_claim": "Ada led the study.",
                "counterfactual_claim": "Grace led the study.",
                "original_entity": "Ada",
                "counterfactual_entity": "Grace",
            },
            source_evidence_excerpt="Context Ada led the study. More context.",
        )
        self.assertNotIn("dataset", row)
        self.assertNotIn("effective_type", row)
        self.assertNotIn("row_kind", row)
        self.assertNotIn("control_reason", row)
        self.assertEqual(
            row["source_evidence_excerpt"],
            "Context Ada led the study. More context.",
        )

    def test_r1_exclusion_removes_pair_source_and_fact_overlap(self):
        exclusions = _r1_exclusions(
            [
                {
                    "pair_id": "p1",
                    "source_key": "s1",
                    "fact_signature": "f1",
                }
            ]
        )
        rows = [
            {
                "pair_id": "p1",
                "source_key": "s2",
                "fact_signature": "f2",
                "effective_type": "PERSON",
                "hard_gate_passed": True,
            },
            {
                "pair_id": "p2",
                "source_key": "s1",
                "fact_signature": "f2",
                "effective_type": "PERSON",
                "hard_gate_passed": True,
            },
            {
                "pair_id": "p3",
                "source_key": "s3",
                "fact_signature": "f1",
                "effective_type": "PERSON",
                "hard_gate_passed": True,
            },
            {
                "pair_id": "p4",
                "source_key": "s4",
                "fact_signature": "f4",
                "effective_type": "PERSON",
                "hard_gate_passed": True,
            },
        ]
        self.assertEqual(
            [row["pair_id"] for row in _available_rows(rows, exclusions)], ["p4"]
        )

    def test_source_evidence_excerpt_comes_from_frozen_source_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE sources (source_key TEXT PRIMARY KEY, full_text TEXT)"
            )
            connection.execute(
                "INSERT INTO sources VALUES (?, ?)",
                ("s1", "Before context. Ada led the study. After context."),
            )
            connection.commit()
            connection.close()
            excerpt = _source_evidence_excerpt(
                {"database_path": str(database)},
                {"source_key": "s1", "true_claim": "Ada led the study."},
                root,
                context_chars=8,
            )
            self.assertIn("Ada led the study.", excerpt)

    def test_evaluator_uses_assistant_labels_without_user_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "artifacts" / "v22" / "calibration_r2"
            private_dir = output / "private"
            private_dir.mkdir(parents=True)
            private_rows = [
                {
                    "review_id": "real-1",
                    "row_kind": "real_candidate",
                    "pair_id": "pair-1",
                    "utility_score": 0.8,
                },
                {
                    "review_id": "control-1",
                    "row_kind": "structural_control",
                    "expected_attack_usable": "no",
                },
            ]
            private_path = private_dir / "calibration_key.jsonl"
            private_path.write_text(
                "".join(json.dumps(row) + "\n" for row in private_rows),
                encoding="utf-8",
            )
            labels_path = private_dir / "assistant_labels.jsonl"
            labels = [_label("real-1", "yes"), _label("control-1", "no")]
            labels_path.write_text(
                "".join(json.dumps(row) + "\n" for row in labels),
                encoding="utf-8",
            )
            plan = {
                "calibration_plan_identity_sha256": "plan-1",
                "base_protocol_identity_sha256": "base-1",
                "artifacts": {"private_key": {"path": str(private_path)}},
            }
            receipt = {
                "protocol": "pcv_v22_attackability_assistant_labels_r2",
                "status": "validated",
                "calibration_plan_identity_sha256": "plan-1",
                "labels_sha256": sha256_file(labels_path),
            }
            receipt["receipt_identity_sha256"] = sha256_obj(receipt)
            (private_dir / "assistant_labels_receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )
            config = {
                "output_root": str(output),
                "method_version": "pcv-attackability-first-v22",
                "calibration": {
                    "threshold_grid": [0.5],
                    "threshold_selection": "test",
                    "gates": {
                        "structural_negative_rejection_rate": 1.0,
                        "maximum_real_uncertain_rate": 0.05,
                        "threshold_minimum_assistant_judged_usability_rate": 0.9,
                        "minimum_labelled_real_candidates_per_threshold": 1,
                        "minimum_projected_eligible_sources_per_dataset": 1,
                    },
                },
            }
            config_path = root / "config.yaml"
            config_path.write_text("protocol: test\n", encoding="utf-8")
            base_config = {
                "source_pools": {"edgar": {}},
                "calibration": {"projection_sources_per_dataset": 1},
            }
            pilot = [
                {
                    "pair_id": "pair-1",
                    "effective_type": "PERSON",
                    "utility_score": 0.8,
                    "hard_gate_passed": True,
                }
            ]
            with (
                patch(
                    "src.prepare.attackability_calibration_r2.load_r2_config",
                    return_value=config,
                ),
                patch(
                    "src.prepare.attackability_calibration_r2._load_r2_plan",
                    return_value=plan,
                ),
                patch(
                    "src.prepare.attackability_calibration_r2._load_base_and_r1",
                    return_value=(base_config, {}, [], {}),
                ),
                patch(
                    "src.prepare.attackability_calibration_r2._pilot_rows",
                    return_value=(pilot, {}),
                ),
                patch(
                    "src.prepare.attackability_calibration_r2._projection_by_threshold_r2",
                    return_value={
                        "edgar": {"projected_eligible_sources": 10}
                    },
                ),
            ):
                result = evaluate_calibration_r2(
                    config_path, labels_path, project_root=root
                )
                result_again = evaluate_calibration_r2(
                    config_path, labels_path, project_root=root
                )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result_again, result)
            report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
            self.assertEqual(report["protocol"], R2_EVALUATION_PROTOCOL)
            self.assertFalse(report["human_review_performed"])
            self.assertFalse(report["human_validation_claim_allowed"])
            self.assertFalse(report["precision_against_human_gold_available"])
            self.assertNotIn("user_labels_sha256", report)
            threshold = json.loads(
                (output / "threshold_manifest.json").read_text(encoding="utf-8")
            )
            self.assertFalse(threshold["human_validation_claim_allowed"])


if __name__ == "__main__":
    unittest.main()
