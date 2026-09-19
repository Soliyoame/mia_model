from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_query_control.py"
SPEC = importlib.util.spec_from_file_location("analyze_query_control", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QueryControlAnalysisTests(unittest.TestCase):
    def test_comparison_uses_matching_common_eval_sources_only(self) -> None:
        main = [
            {"source_key": "m", "group": "KB_Member", "pcv_score": 2.0},
            {"source_key": "n", "group": "True_Non_Member", "pcv_score": 0.0},
            {"source_key": "reserve", "group": "Reserve", "pcv_score": 10.0},
            {"source_key": "main_only", "group": "KB_Member", "pcv_score": 1.0},
        ]
        control = [
            {"source_key": "m", "group": "KB_Member", "pcv_score": 1.0},
            {"source_key": "n", "group": "True_Non_Member", "pcv_score": 1.5},
            {"source_key": "control_only", "group": "True_Non_Member", "pcv_score": 0.0},
        ]
        report = MODULE.build_query_control_report(
            main,
            control,
            variant_id="random_same_type_counterfactual",
            query_budget=4,
            n_bootstrap=20,
            seed=42,
        )
        self.assertEqual(report["common_source_count"], 2)
        self.assertEqual(report["positive_sources"], 1)
        self.assertEqual(report["negative_sources"], 1)
        self.assertEqual(report["excluded_main_only"], 1)
        self.assertEqual(report["excluded_control_only"], 1)
        self.assertEqual(report["full_pvs"]["metrics"]["AUC"], 1.0)
        self.assertEqual(report["control"]["metrics"]["AUC"], 0.0)
        self.assertEqual(
            report["paired_delta_full_pvs_minus_control"]["estimate"]["AUC"],
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
