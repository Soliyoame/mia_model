from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.prepare.enron_capacity_promotion import (
    _selected_source_keys,
    build_enron_capacity_promotion,
    validate_enron_capacity_promotion,
)
from src.prepare.eligibility_scan import validate_formal_eligibility_manifest
from src.utils.hash import sha256_file, sha256_obj
from src.utils.io import write_json


class EnronCapacityPromotionTests(unittest.TestCase):
    def test_selection_is_deterministic_and_rejects_duplicates(self) -> None:
        keys = ["source-c", "source-a", "source-b"]
        self.assertEqual(
            _selected_source_keys(keys, 2),
            _selected_source_keys(list(reversed(keys)), 2),
        )
        with self.assertRaisesRegex(RuntimeError, "duplicates"):
            _selected_source_keys(["source-a", "source-a"], 1)

    def test_build_and_validate_capacity_qualified_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_path = root / "gate.json"
            query_path = root / "query.json"
            checkpoint_path = root / "checkpoint.json"
            output_path = root / "promotion.json"
            write_json({"fixture": True}, gate_path)
            write_json({"fixture": "checkpoint"}, checkpoint_path)
            eligible = ["source-a", "source-b", "source-c", "source-d"]
            write_json({"eligible_source_keys": eligible}, query_path)
            evidence = {
                "query_eligibility_path": str(query_path),
                "query_eligibility_sha256": "bound-by-validator",
                "eligible_source_keys_sha256": sha256_obj(eligible),
                "eligible_source_count": len(eligible),
                "capacity_checkpoint_path": str(checkpoint_path),
                "capacity_checkpoint_sha256": sha256_file(checkpoint_path),
                "promoted_role": "capacity_qualified_primary",
                "prior_pilot_status": "failed",
            }
            config = {
                "protocol": (
                    "v21_enron_capacity_qualified_primary_promotion_v1"
                ),
                "dataset": "enron",
                "selection_seed": 42,
                "selection_method": (
                    "sha256(scope_version,selection_seed,dataset,source_key)"
                ),
                "required_formal_sources": 3,
                "output_path": str(output_path),
            }
            gate = {
                "release_gate_identity_sha256": "gate-id",
                "runtime_tree_sha256": "runtime-id",
            }
            patches = (
                patch(
                    "src.prepare.enron_capacity_promotion.PROJECT_ROOT",
                    root,
                ),
                patch(
                    "src.prepare.enron_capacity_promotion."
                    "capacity_promotion_config",
                    return_value=config,
                ),
                patch(
                    "src.prepare.enron_capacity_promotion."
                    "validate_capacity_qualification_evidence",
                    return_value={"enron": evidence},
                ),
                patch(
                    "src.prepare.enron_capacity_promotion.validate_release_gate",
                    return_value=gate,
                ),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                payload = build_enron_capacity_promotion(
                    gate_path,
                    output_path,
                )
                self.assertEqual(payload["dataset_role"], "capacity_qualified_primary")
                self.assertEqual(payload["prior_pilot_status"], "failed")
                self.assertEqual(len(payload["selected_source_keys"]), 3)
                self.assertEqual(
                    len(
                        validate_formal_eligibility_manifest(
                            payload,
                            dataset="enron",
                            required_sources=3,
                        )
                    ),
                    3,
                )
                self.assertEqual(
                    validate_enron_capacity_promotion(
                        output_path,
                        require_current_runtime=False,
                    )["status"],
                    "passed",
                )

            write_json({"eligible_source_keys": ["changed"]}, query_path)
            with patches[0], patches[1], patches[2], patches[3]:
                with self.assertRaisesRegex(RuntimeError, "query eligibility drift"):
                    validate_enron_capacity_promotion(
                        output_path,
                        require_current_runtime=False,
                    )


if __name__ == "__main__":
    unittest.main()
