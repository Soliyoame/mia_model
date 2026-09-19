from __future__ import annotations

import unittest

from scripts.build_query_controls import build_control_query_rows, build_random_same_type_pairs


def control_pair(pair_id: str, source: str, entity: str) -> dict:
    return {
        "pair_id": pair_id,
        "fact_id": f"f-{pair_id}",
        "audit_id": f"a-{pair_id}",
        "source_id": source,
        "source_key": source,
        "dataset": "toy",
        "group": "KB_Member",
        "true_claim": f"Alice paid {entity} dollars.",
        "counterfactual_claim": f"Alice paid {entity}0 dollars.",
        "original_entity": entity,
        "counterfactual_entity": f"{entity}0",
        "entity_type": "MONEY",
        "perturbation_level": "light",
        "context": "payment",
    }


class QueryControlTests(unittest.TestCase):
    def test_random_counterfactual_comes_from_other_source_same_type(self) -> None:
        pairs = [control_pair("p1", "s1", "10"), control_pair("p2", "s2", "20")]
        randomized, errors = build_random_same_type_pairs(pairs, seed=42)
        self.assertFalse(errors)
        self.assertEqual(randomized[0]["counterfactual_entity"], "20")
        self.assertEqual(randomized[1]["counterfactual_entity"], "10")

    def test_independent_queries_keep_logical_pair_but_use_different_wording(self) -> None:
        rows, errors = build_control_query_rows(
            [control_pair("p1", "s1", "10")], "independent_unpaired_query"
        )
        self.assertFalse(errors)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["query_type"] for row in rows}, {"independent_unpaired_query"})
        self.assertNotEqual(rows[0]["query"].split(":", 1)[0], rows[1]["query"].split(":", 1)[0])
        self.assertTrue(all(row["variant_id"] == "independent_unpaired_query" for row in rows))


if __name__ == "__main__":
    unittest.main()
