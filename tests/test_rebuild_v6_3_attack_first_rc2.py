from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "rebuild_v6_3_attack_first_rc2.py"
)
SPEC = importlib.util.spec_from_file_location(
    "rebuild_v6_3_attack_first_rc2",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AttackFirstRc2RebuildTests(unittest.TestCase):
    def test_protocol_uses_frozen_original_entity_gate(self) -> None:
        self.assertEqual(
            "v6_3_attack_first_counterfactual_rc2_rebuild_v1",
            MODULE.PROTOCOL,
        )

    def test_canonicalize_deduplicates_and_uses_frozen_order(self) -> None:
        rows = [
            {
                "source_key": "source-b",
                "fact_id": "old-1",
                "object_entity": "Paris",
                "entity_type": "LOCATION",
                "factual_claim": "The office is in Paris.",
                "claim_entity_span": [17, 22],
                "quality_weight": 0.7,
            },
            {
                "source_key": "source-a",
                "fact_id": "old-2",
                "object_entity": "Berlin",
                "entity_type": "LOCATION",
                "factual_claim": "The office is in Berlin.",
                "claim_entity_span": [17, 23],
                "quality_weight": 0.8,
            },
            {
                "source_key": "source-b",
                "fact_id": "different-old-id",
                "object_entity": "Paris",
                "entity_type": "LOCATION",
                "factual_claim": "The office is in Paris.",
                "claim_entity_span": [17, 22],
                "quality_weight": 0.7,
            },
        ]
        facts, stats = MODULE.canonicalize_fact_rows(
            rows,
            ["source-a", "source-b"],
        )
        self.assertEqual(["source-a", "source-b"], [row["source_key"] for row in facts])
        self.assertEqual(2, stats["unique_facts"])
        self.assertEqual(1, stats["duplicate_facts_removed"])
        self.assertTrue(all(row["fact_id"].startswith("fact_rc2_") for row in facts))

    def test_counterfactual_source_absence_is_boundary_safe(self) -> None:
        claims = [
            {
                "pair_id": "p1",
                "source_key": "s1",
                "counterfactual_entity": "Paris",
            },
            {
                "pair_id": "p2",
                "source_key": "s2",
                "counterfactual_entity": "Paris",
            },
        ]
        accepted, rejected, reasons = MODULE.filter_counterfactual_absence(
            claims,
            {
                "s1": "The source mentions Paris.",
                "s2": "The source mentions comparison only.",
            },
        )
        self.assertEqual(["p2"], [row["pair_id"] for row in accepted])
        self.assertEqual(["p1"], [row["pair_id"] for row in rejected])
        self.assertEqual(
            {"counterfactual_entity_present_in_source": 1},
            reasons,
        )

    def test_retain_target_sources_cuts_after_target(self) -> None:
        claims = {}
        facts = {}
        queries = []
        for source_index, source_key in enumerate(("s2", "s1", "s3")):
            for pair_index in range(3):
                pair_id = f"{source_key}-p{pair_index}"
                fact_id = f"{source_key}-f{pair_index}"
                claims[pair_id] = {
                    "pair_id": pair_id,
                    "fact_id": fact_id,
                    "source_key": source_key,
                }
                facts[fact_id] = {
                    "fact_id": fact_id,
                    "source_key": source_key,
                }
                for claim_type in ("true", "counterfactual"):
                    queries.append(
                        {
                            "query_id": f"{pair_id}-{claim_type}",
                            "pair_id": pair_id,
                            "source_key": source_key,
                            "claim_type": claim_type,
                            "query": f"{pair_id} {claim_type}",
                            "fixed_budget_pair_rank": pair_index + 1,
                        }
                    )
        kept_facts, kept_claims, kept_queries, kept_sources = (
            MODULE.retain_target_sources(
                queries,
                claims,
                facts,
                ["s1", "s2", "s3"],
                target_sources=2,
                pairs_per_source=3,
            )
        )
        self.assertEqual(["s1", "s2"], kept_sources)
        self.assertEqual(6, len(kept_facts))
        self.assertEqual(6, len(kept_claims))
        self.assertEqual(12, len(kept_queries))
        self.assertNotIn(
            "s3",
            {row["source_key"] for row in (*kept_facts, *kept_claims, *kept_queries)},
        )


if __name__ == "__main__":
    unittest.main()
