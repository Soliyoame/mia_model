from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_v6_3_budget6_release_inputs import (
    ATTACK_FIRST_RC2_RELEASE_INPUT_PROTOCOL,
    collect_selected_facts,
    validate_selected_plan,
)
from src.paired_claims.validator import VALIDATOR_VERSION
from src.utils.io import write_jsonl


def _claim(source: str, index: int) -> dict[str, object]:
    return {
        "dataset": "enron",
        "group": "Eligibility_Candidate",
        "source_key": source,
        "pair_id": f"{source}_pair_{index}",
        "fact_id": f"{source}_fact_{index}",
        "original_entity": "Alice",
        "counterfactual_entity": "Carol",
        "claim_validator_version": VALIDATOR_VERSION,
    }


def _queries(claim: dict[str, object]) -> list[dict[str, object]]:
    common = {
        "dataset": "enron",
        "group": "Eligibility_Candidate",
        "source_key": claim["source_key"],
        "pair_id": claim["pair_id"],
        "fact_id": claim["fact_id"],
        "accepted": True,
        "claim_validator_version": VALIDATOR_VERSION,
    }
    pair_id = str(claim["pair_id"])
    return [
        {
            **common,
            "query_id": f"{pair_id}_true",
            "claim_type": "true",
            "query": f"Please verify that Alice signed agreement {pair_id}.",
        },
        {
            **common,
            "query_id": f"{pair_id}_counterfactual",
            "claim_type": "counterfactual",
            "query": f"Please verify that Carol signed agreement {pair_id}.",
        },
    ]


class Budget6ReleaseInputTests(unittest.TestCase):
    def test_attack_first_rc2_protocol_is_isolated_from_rc1(self) -> None:
        self.assertEqual(
            "v6_3_attack_first_rc2_budget6_release_input_v1",
            ATTACK_FIRST_RC2_RELEASE_INPUT_PROTOCOL,
        )

    def test_validate_selected_plan_requires_exact_three_pairs(self) -> None:
        claims = [_claim("s1", index) for index in range(3)]
        queries = [
            row
            for claim in claims
            for row in _queries(claim)
        ]
        result = validate_selected_plan(claims, queries, dataset="enron")
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["pair_count"], 3)
        self.assertEqual(result["query_count"], 6)

        with self.assertRaisesRegex(RuntimeError, "expected three"):
            validate_selected_plan(
                claims[:2],
                queries[:4],
                dataset="enron",
            )

    def test_validate_selected_plan_rejects_duplicate_query_text(self) -> None:
        claims = [_claim("s1", index) for index in range(3)]
        queries = [
            row
            for claim in claims
            for row in _queries(claim)
        ]
        queries[1]["query"] = queries[0]["query"]
        with self.assertRaisesRegex(RuntimeError, "Duplicate query text"):
            validate_selected_plan(claims, queries, dataset="enron")

    def test_collect_selected_facts_rejects_conflicting_duplicates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.jsonl"
            second = Path(tmp) / "second.jsonl"
            write_jsonl([{"fact_id": "f1", "value": 1}], first)
            write_jsonl([{"fact_id": "f1", "value": 2}], second)
            with self.assertRaisesRegex(RuntimeError, "Conflicting"):
                collect_selected_facts([first, second], {"f1"})


if __name__ == "__main__":
    unittest.main()
