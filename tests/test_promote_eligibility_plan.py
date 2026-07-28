from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from src.paired_claims.validator import VALIDATOR_VERSION


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "promote_eligibility_plan.py"
SPEC = importlib.util.spec_from_file_location("promote_eligibility_plan", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _fixture_rows() -> dict[str, list[dict]]:
    source_key = "source::one"
    benchmark = []
    facts = []
    claims = []
    queries = []
    for index in range(3):
        doc_id = f"doc_{index}"
        audit_id = f"audit_{index}"
        fact_id = f"fact_{index}"
        pair_id = f"pair_{index}"
        benchmark.append(
            {
                "audit_id": audit_id,
                "doc_id": doc_id,
                "source_key": source_key,
                "group": "KB_Member",
            }
        )
        facts.append(
            {
                "fact_id": fact_id,
                "audit_id": f"eligibility_{index}",
                "doc_id": doc_id,
                "source_key": source_key,
                "group": "Eligibility_Candidate",
                "entity_type": "ORG",
                "selection_tier": "primary",
            }
        )
        claims.append(
            {
                "pair_id": pair_id,
                "fact_id": fact_id,
                "audit_id": f"eligibility_{index}",
                "doc_id": doc_id,
                "source_key": source_key,
                "group": "Eligibility_Candidate",
                "true_claim": f"Alpha {index} filed the report.",
                "counterfactual_claim": f"Beta {index} filed the report.",
                "original_entity": f"Alpha {index}",
                "counterfactual_entity": f"Beta {index}",
                "entity_type": "ORG",
                "claim_validator_version": VALIDATOR_VERSION,
            }
        )
        for claim_type, entity, suffix in (
            ("true", f"Alpha {index}", "plus"),
            ("counterfactual", f"Beta {index}", "minus"),
        ):
            queries.append(
                {
                    "query_id": f"q_{pair_id}_{suffix}",
                    "pair_id": pair_id,
                    "fact_id": fact_id,
                    "audit_id": f"eligibility_{index}",
                    "doc_id": doc_id,
                    "source_key": source_key,
                    "group": "Eligibility_Candidate",
                    "claim_type": claim_type,
                    "query_type": "compressed_verification",
                    "query": f"Please verify that {entity} filed the report.",
                    "claim_validator_version": VALIDATOR_VERSION,
                    "accepted": True,
                    "fixed_budget_pair_rank": index + 1,
                }
            )
    return {
        "benchmark": benchmark,
        "facts": facts,
        "claims": claims,
        "queries": queries,
    }


class PromoteEligibilityPlanTests(unittest.TestCase):
    def test_promotes_exact_fixed_budget_and_formal_labels(self) -> None:
        rows = _fixture_rows()
        result = MODULE.promote_fixed_plan_rows(
            benchmark_rows=rows["benchmark"],
            candidate_facts=rows["facts"],
            candidate_claims=rows["claims"],
            candidate_queries=rows["queries"],
        )

        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["pair_count"], 3)
        self.assertEqual(result["query_count"], 6)
        self.assertEqual(result["pair_counts_by_group"], {"KB_Member": 3})
        self.assertTrue(
            all(row["group"] == "KB_Member" for row in result["queries"])
        )
        self.assertEqual(
            {row["audit_id"] for row in result["claims"]},
            {f"audit_{index}" for index in range(3)},
        )

    def test_rejects_duplicate_query_text_within_source(self) -> None:
        rows = _fixture_rows()
        rows["queries"][1]["query"] = rows["queries"][0]["query"]

        with self.assertRaisesRegex(RuntimeError, "Duplicate frozen query text"):
            MODULE.promote_fixed_plan_rows(
                benchmark_rows=rows["benchmark"],
                candidate_facts=rows["facts"],
                candidate_claims=rows["claims"],
                candidate_queries=rows["queries"],
            )

    def test_rejects_doc_source_binding_drift(self) -> None:
        rows = _fixture_rows()
        rows["claims"][0]["source_key"] = "source::other"

        with self.assertRaisesRegex(RuntimeError, "source_key drift"):
            MODULE.promote_fixed_plan_rows(
                benchmark_rows=rows["benchmark"],
                candidate_facts=rows["facts"],
                candidate_claims=rows["claims"],
                candidate_queries=rows["queries"],
            )


if __name__ == "__main__":
    unittest.main()
