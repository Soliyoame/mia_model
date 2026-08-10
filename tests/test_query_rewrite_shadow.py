from __future__ import annotations

import unittest

from src.evaluation.query_rewrite_shadow import (
    LEGACY_VARIANT,
    NEW_VARIANT,
    binary_auc,
    evaluate_query_rewrite_shadow,
    validate_shadow_sources,
)


class QueryRewriteShadowTests(unittest.TestCase):
    def test_binary_auc_handles_ties(self) -> None:
        self.assertEqual(binary_auc([1, 0], [0.5, 0.5]), 0.5)
        self.assertEqual(binary_auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]), 1.0)

    def test_shadow_source_plan_rejects_canonical_or_near_duplicate_rows(self) -> None:
        rows = [
            {
                "dataset": "toy",
                "source_key": "m1",
                "label": 1,
                "text_hash": "a",
                "entered_canonical": False,
                "near_duplicate_of_formal": False,
            },
            {
                "dataset": "toy",
                "source_key": "n1",
                "label": 0,
                "text_hash": "b",
                "entered_canonical": False,
                "near_duplicate_of_formal": False,
            },
        ]
        summary = validate_shadow_sources(
            rows,
            datasets=["toy"],
            members_per_dataset=1,
            non_members_per_dataset=1,
        )
        self.assertEqual(summary["sources"], 2)
        rows[1]["near_duplicate_of_formal"] = True
        with self.assertRaisesRegex(RuntimeError, "near-duplicate"):
            validate_shadow_sources(
                rows,
                datasets=["toy"],
                members_per_dataset=1,
                non_members_per_dataset=1,
            )

    def test_promotion_gate_passes_noninferior_rewrite(self) -> None:
        datasets = ["d1", "d2", "d3"]
        scores = []
        retrieval = []
        lexical = []
        for dataset in datasets:
            for index in range(20):
                label = 1 if index < 10 else 0
                source_key = f"{dataset}-{index}"
                legacy_score = 0.8 - index * 0.01 if label else 0.2 + (index - 10) * 0.01
                new_score = legacy_score + (0.01 if label else -0.01)
                scores.extend(
                    [
                        {"variant": LEGACY_VARIANT, "dataset": dataset, "source_key": source_key, "label": label, "score": legacy_score},
                        {"variant": NEW_VARIANT, "dataset": dataset, "source_key": source_key, "label": label, "score": new_score},
                    ]
                )
                for retriever in ("BGE", "BM25", "hybrid"):
                    retrieval.extend(
                        [
                            {"variant": LEGACY_VARIANT, "dataset": dataset, "retriever": retriever, "target_hit_at_5": 1.0},
                            {"variant": NEW_VARIANT, "dataset": dataset, "retriever": retriever, "target_hit_at_5": 1.0},
                        ]
                    )
            lexical.extend(
                [
                    {"variant": LEGACY_VARIANT, "five_gram_containment": 0.8},
                    {"variant": NEW_VARIANT, "five_gram_containment": 0.3},
                ]
            )
        audit = {
            "fixed_budget_pass": True,
            "structure_gate_pass": True,
            "naturalness_gate_pass": True,
            "semantic_gate_pass": True,
            "diversity_gate_pass": True,
            "formal_near_duplicate_exclusion_pass": True,
            "logical_victim_calls": 7200,
            "victim_generator": "meta/llama-3.1-70b-instruct",
            "rag_retriever": "BGE",
            "variants": [LEGACY_VARIANT, NEW_VARIANT],
            "retrievers": ["BGE", "BM25", "hybrid"],
            "neutral_prompt_robustness_cell": False,
        }
        result = evaluate_query_rewrite_shadow(
            score_rows=scores,
            retrieval_rows=retrieval,
            lexical_rows=lexical,
            audit=audit,
            datasets=datasets,
            bootstrap_iterations=200,
        )
        self.assertTrue(result["passed"])
        self.assertGreaterEqual(result["auc_noninferiority"]["macro_difference_ci95"][0], -0.01)
        self.assertGreaterEqual(result["lexical"]["relative_reduction"], 0.5)

    def test_promotion_gate_rejects_retrieval_drop_and_neutral_cell(self) -> None:
        datasets = ["d1"]
        scores = []
        retrieval = []
        for index in range(10):
            label = 1 if index < 5 else 0
            score = 1.0 if label else 0.0
            for variant in (LEGACY_VARIANT, NEW_VARIANT):
                scores.append(
                    {"variant": variant, "dataset": "d1", "source_key": str(index), "label": label, "score": score}
                )
            for retriever in ("BGE", "BM25", "hybrid"):
                retrieval.extend(
                    [
                        {"variant": LEGACY_VARIANT, "dataset": "d1", "retriever": retriever, "target_hit_at_5": 1.0},
                        {"variant": NEW_VARIANT, "dataset": "d1", "retriever": retriever, "target_hit_at_5": 0.0},
                    ]
                )
        audit = {
            "fixed_budget_pass": True,
            "structure_gate_pass": True,
            "naturalness_gate_pass": True,
            "semantic_gate_pass": True,
            "diversity_gate_pass": True,
            "formal_near_duplicate_exclusion_pass": True,
            "logical_victim_calls": 7200,
            "victim_generator": "wrong-generator",
            "rag_retriever": "BGE",
            "variants": [LEGACY_VARIANT, NEW_VARIANT],
            "retrievers": ["BGE", "BM25", "hybrid"],
            "neutral_prompt_robustness_cell": True,
        }
        result = evaluate_query_rewrite_shadow(
            score_rows=scores,
            retrieval_rows=retrieval,
            lexical_rows=[
                {"variant": LEGACY_VARIANT, "five_gram_containment": 0.8},
                {"variant": NEW_VARIANT, "five_gram_containment": 0.3},
            ],
            audit=audit,
            datasets=datasets,
            bootstrap_iterations=100,
        )
        self.assertFalse(result["passed"])
        self.assertTrue(any(reason.startswith("recall_at_5_drop") for reason in result["failures"]))
        self.assertIn("audit:victim_generator", result["failures"])
        self.assertIn("audit:neutral_prompt_robustness_cell_forbidden", result["failures"])


if __name__ == "__main__":
    unittest.main()
