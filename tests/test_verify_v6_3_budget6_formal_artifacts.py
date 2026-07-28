from __future__ import annotations

import unittest

from scripts.verify_v6_3_budget6_formal_artifacts import (
    verify_promoted_relations,
)
from src.paired_claims.validator import VALIDATOR_VERSION


class Budget6FormalIntegrityTests(unittest.TestCase):
    def test_promoted_relations_require_one_fact_per_pair(self) -> None:
        facts = []
        claims = []
        queries = []
        for index in range(3):
            fact_id = f"fact_{index}"
            pair_id = f"pair_{index}"
            common = {
                "source_key": "source",
                "group": "KB_Member",
                "promotion_protocol": "promotion",
            }
            facts.append({**common, "fact_id": fact_id})
            claims.append(
                {
                    **common,
                    "fact_id": fact_id,
                    "pair_id": pair_id,
                    "claim_validator_version": VALIDATOR_VERSION,
                }
            )
            for claim_type in ("true", "counterfactual"):
                queries.append(
                    {
                        **common,
                        "query_id": f"{pair_id}_{claim_type}",
                        "pair_id": pair_id,
                        "claim_type": claim_type,
                        "claim_validator_version": VALIDATOR_VERSION,
                    }
                )

        result = verify_promoted_relations(
            "edgar",
            facts,
            claims,
            queries,
            expected_sources=1,
        )
        self.assertEqual(result["fact_count"], 3)
        self.assertEqual(result["pair_count"], 3)
        self.assertEqual(result["query_count"], 6)

        claims[1]["fact_id"] = "fact_0"
        with self.assertRaisesRegex(RuntimeError, "reference set mismatch"):
            verify_promoted_relations(
                "edgar",
                facts,
                claims,
                queries,
                expected_sources=1,
            )


if __name__ == "__main__":
    unittest.main()
