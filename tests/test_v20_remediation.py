from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.defenses.runner import (
    answer_without_correction,
    target_entity_redaction,
)
from src.evaluation.metrics import (
    conformal_nonmember_p_value,
    summarize_membership_scores,
)
from src.evaluation.v20_release_controls import (
    build_reserve_role_manifest,
    calibration_source_keys,
    near_duplicate_audit,
)
from src.utils.hash import sha256_obj
from src.utils.io import read_json, write_json, write_jsonl
from src.utils.run_context import require_clean_release_commit


class V20RemediationTests(unittest.TestCase):
    def test_api_launch_requires_clean_release_commit(self) -> None:
        self.assertEqual(
            require_clean_release_commit({"commit": "abc123", "dirty": False}),
            "abc123",
        )
        with self.assertRaisesRegex(RuntimeError, "clean worktree"):
            require_clean_release_commit({"commit": "abc123", "dirty": True})
        with self.assertRaisesRegex(RuntimeError, "frozen git commit"):
            require_clean_release_commit({"commit": "", "dirty": False})

    def test_conformal_minimum_p_is_one_over_246(self) -> None:
        self.assertEqual(
            conformal_nonmember_p_value(2.0, [1.0] * 245),
            1.0 / 246.0,
        )

    def test_v20_metrics_do_not_emit_numeric_point_one_percent_fpr(self) -> None:
        rows = [
            {"group": "KB_Member", "pcv_score": 1.0},
            {"group": "True_Non_Member", "pcv_score": 0.0},
        ]
        metrics = summarize_membership_scores(rows)
        self.assertNotIn("Oracle TPR@0.1%FPR", metrics)
        self.assertNotIn("TPR@0.1%FPR", metrics)

    def test_reserve_role_manifest_is_exact_disjoint_5_245(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reserve = root / "reserve.jsonl"
            budget = root / "budget.json"
            output = root / "roles.json"
            write_jsonl(
                [
                    {
                        "group": "Reserve",
                        "source_key": f"reserve-{index:03d}",
                        "text": f"reserve source text {index}",
                    }
                    for index in range(250)
                ],
                reserve,
            )
            write_json(
                {
                    "selected_source_keys": {
                        "Reserve": [
                            f"reserve-{index:03d}" for index in range(5)
                        ]
                    }
                },
                budget,
            )
            manifest = build_reserve_role_manifest(
                dataset="toy",
                reserve_path=reserve,
                pilot_budget_path=budget,
                output_path=output,
            )
            self.assertEqual(manifest["pilot_diagnostic_count"], 5)
            self.assertEqual(manifest["conformal_calibration_count"], 245)
            self.assertEqual(len(calibration_source_keys(output)), 245)

    def test_near_duplicate_audit_rejects_cross_group_overlap(self) -> None:
        text = "one two three four five six seven eight nine ten"
        audit = near_duplicate_audit(
            [
                {
                    "source_key": "member",
                    "group": "KB_Member",
                    "text": text,
                },
                {
                    "source_key": "nonmember",
                    "group": "True_Non_Member",
                    "text": text,
                },
            ]
        )
        self.assertFalse(audit["passed"])
        self.assertGreaterEqual(audit["cross_group_pair_count"], 1)

    def test_offline_defenses_transform_saved_response_without_api(self) -> None:
        query = {
            "query_id": "q1",
            "claim_type": "counterfactual",
            "expected_entity": "Alice",
            "counterfactual_entity": "Bob",
        }
        response = {
            "query_id": "q1",
            "response": "Inconsistent: Alice, not Bob.",
        }
        no_correction = answer_without_correction(response, query)
        self.assertEqual(no_correction["response"], "Inconsistent")
        redacted = target_entity_redaction(response, query)
        self.assertNotIn("Alice", redacted["response"])
        self.assertNotIn("Bob", redacted["response"])
        self.assertEqual(redacted["response"].count("[REDACTED]"), 2)

    def test_canonical_configuration_freezes_new_protocol_fields(self) -> None:
        # YAML is deliberately loaded through the project loader in production;
        # this assertion keeps the test independent of optional PyYAML internals.
        from src.utils.io import load_yaml

        config = load_yaml("configs/canonical_suite_v20_llama.yaml")
        protocol = config["protocol"]
        self.assertEqual(
            protocol["dataset_status"],
            "facts_claims_splits_indexes_frozen_queries_unfrozen",
        )
        self.assertEqual(config["status"], "query_protocol_rebuild_required")
        self.assertEqual(protocol["query_type"], "diverse_slotted_verification")
        self.assertFalse(protocol["neutral_prompt_robustness_cell"])
        self.assertEqual(
            protocol["metrics_version"],
            "source-conformal-bootstrap-v2",
        )
        self.assertEqual(protocol["conformal_source_count"], 245)
        self.assertEqual(protocol["execution"], "source_block_interleaved")
        self.assertEqual(
            sha256_obj(sorted(protocol["conformal_alphas"])),
            sha256_obj([0.01, 0.05]),
        )


if __name__ == "__main__":
    unittest.main()
