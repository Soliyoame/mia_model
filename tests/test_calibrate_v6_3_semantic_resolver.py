from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from src.attack.semantic_entity_resolver import (
    SEMANTIC_TARGET_TYPES,
    semantic_thresholds_sha256,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "calibrate_v6_3_semantic_resolver.py"
)
SPEC = importlib.util.spec_from_file_location(
    "calibrate_v6_3_semantic_resolver",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _row(
    entity_type: str,
    label: str,
    score: float | None,
) -> dict:
    text = f"{entity_type} example"
    predictions = []
    if score is not None:
        predictions.append(
            {
                "model_id": "large",
                "role": "gliner2_large",
                "label": entity_type,
                "text": text,
                "start": 0,
                "end": len(text),
                "score": score,
            }
        )
    return {
        "audit_id": f"{entity_type}_{label}",
        "dataset": "edgar",
        "entity_type": entity_type,
        "entity": text,
        "text": text,
        "start": 0,
        "end": len(text),
        "semantic_label": label,
        "voter_predictions": {"large": predictions},
        "biomedical_predictions": [],
    }


class PerEntityTypeCalibrationTests(unittest.TestCase):
    def test_per_entity_type_policy_resolves_global_threshold_conflict(self):
        rows = []
        for entity_type in sorted(SEMANTIC_TARGET_TYPES):
            if entity_type == "PRODUCT":
                pass_score, fail_score = 0.70, 0.65
            elif entity_type == "PROJECT_NAME":
                pass_score, fail_score = 0.98, 0.90
            else:
                pass_score, fail_score = 0.98, 0.40
            rows.extend(
                [
                    _row(entity_type, "pass", pass_score),
                    _row(entity_type, "fail", fail_score),
                ]
            )

        selected, scalar_grid, policy_candidates = MODULE._select_thresholds(
            rows
        )

        self.assertEqual(540, len(scalar_grid))
        self.assertEqual(6, len(policy_candidates))
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertTrue(selected["gate_passed"])
        self.assertEqual(1.0, selected["overall"]["precision"])
        self.assertEqual(6, selected["overall"]["true_accepts"])
        self.assertEqual(0, selected["overall"]["false_accepts"])
        thresholds_by_type = selected["thresholds"][
            "thresholds_by_entity_type"
        ]
        self.assertEqual(
            0.70,
            thresholds_by_type["PRODUCT"]["min_target_confidence"],
        )
        self.assertEqual(
            0.95,
            thresholds_by_type["PROJECT_NAME"]["min_target_confidence"],
        )
        self.assertEqual(
            selected["thresholds_sha256"],
            semantic_thresholds_sha256(**selected["thresholds"]),
        )


if __name__ == "__main__":
    unittest.main()
