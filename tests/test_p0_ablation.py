from __future__ import annotations

import unittest

from scripts.analyze_p0_ablation import (
    NOT_APPLICABLE_VARIANTS,
    build_budget_curves,
    build_source_variants,
)


def pair(source: str, group: str, index: int, support: float, correction: float) -> dict:
    return {
        "source_key": source,
        "group": group,
        "logical_pair_id": f"{source}-{index}",
        "audit_id": f"{source}-chunk-{index // 2}",
        "complete_rag_pair": True,
        "cvg_rag": support + correction,
        "support_score_rag": support,
        "correction_score_rag": correction,
        "correct_counterfactual_rag": correction == 1.0,
        "quality_weight": 1.0 + index,
        "selection_tier": "primary" if index == 0 else "fallback",
    }


class P0AblationTests(unittest.TestCase):
    def test_variants_aggregate_by_source(self) -> None:
        rows = [
            pair("member", "KB_Member", 0, 1.0, 1.0),
            pair("member", "KB_Member", 1, 1.0, 0.0),
            pair("nonmember", "True_Non_Member", 0, 0.0, 0.0),
        ]
        variants = build_source_variants(rows)
        self.assertEqual(len(variants["full_pvs"]), 2)
        member = next(row for row in variants["qplus_only"] if row["source_key"] == "member")
        self.assertEqual(member["score"], 1.0)

    def test_budget_curve_uses_complete_pair_prefixes(self) -> None:
        rows = [
            pair("member", "KB_Member", 0, 1.0, 1.0),
            pair("member", "KB_Member", 1, 1.0, 0.0),
            pair("nonmember", "True_Non_Member", 0, 0.0, 0.0),
            pair("nonmember", "True_Non_Member", 1, 0.0, 0.0),
        ]
        result = build_budget_curves(rows, query_budgets=(2, 4))
        curves = result["curves"]
        self.assertEqual(result["common_source_count"], 2)
        self.assertEqual(curves["2"]["source_count"], 2)
        self.assertEqual(curves["4"]["source_count"], 2)
        self.assertIn("qplus_only", curves["2"]["variants"])

    def test_full_pvs_uses_equal_chunk_weights(self) -> None:
        rows = [
            pair("member", "KB_Member", 0, 1.0, 1.0),
            pair("member", "KB_Member", 1, 1.0, 1.0),
            pair("member", "KB_Member", 2, 0.0, 0.0),
        ]
        score = build_source_variants(rows)["full_pvs"][0]["score"]
        self.assertEqual(score, 1.0)
        self.assertNotEqual(score, 4.0 / 3.0)

    def test_unweighted_is_explicitly_not_applicable(self) -> None:
        self.assertIn("unweighted", NOT_APPLICABLE_VARIANTS)
        with self.assertRaises(ValueError):
            build_source_variants(
                [pair("member", "KB_Member", 0, 1.0, 1.0)],
                variants=("unweighted",),
            )


if __name__ == "__main__":
    unittest.main()
