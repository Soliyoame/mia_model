from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prepare_single_cell_pilot.py"
SPEC = importlib.util.spec_from_file_location("prepare_single_cell_pilot", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _pair_rows(source: str, pair_index: int) -> list[dict]:
    return [
        {
            "query_id": f"q-{source}-{pair_index}-{claim_type}",
            "pair_id": f"p-{source}-{pair_index}",
            "query_type": "compressed_verification",
            "source_key": source,
            "source_id": source,
            "group": "KB_Member",
            "claim_type": claim_type,
            "query": f"query {source} {pair_index} {claim_type}",
        }
        for claim_type in ("true", "counterfactual")
    ]


class PilotFixedBudgetTests(unittest.TestCase):
    def test_formal_cell_reference_uses_budget6(self) -> None:
        reference = MODULE.formal_cell_reference(3)
        self.assertEqual(reference["rag_calls_including_reserve"], 7_500)
        self.assertEqual(
            reference["matched_llm_only_calls_including_reserve"],
            7_500,
        )
        self.assertEqual(reference["member_nonmember_rag_calls"], 6_000)

    def test_rejects_duplicate_query_text_with_unique_ids(self) -> None:
        rows = [row for index in range(4) for row in _pair_rows("source-1", index)]
        rows[-1]["query"] = rows[0]["query"]

        with self.assertRaisesRegex(RuntimeError, "text-unique queries"):
            MODULE._validate_fixed_source_rows("source-1", rows, pairs_per_source=4)

    def test_accepts_eight_text_unique_queries(self) -> None:
        rows = [row for index in range(4) for row in _pair_rows("source-1", index)]
        MODULE._validate_fixed_source_rows("source-1", rows, pairs_per_source=4)

    def test_selector_skips_source_with_cross_source_duplicate_text(self) -> None:
        first = [row for index in range(4) for row in _pair_rows("source-1", index)]
        duplicate = [row for index in range(4) for row in _pair_rows("source-2", index)]
        duplicate[0]["query"] = first[0]["query"]
        fallback = [row for index in range(4) for row in _pair_rows("source-3", index)]
        rows = first + duplicate + fallback

        with patch.object(MODULE, "_stable_source_rank", side_effect=lambda source, group, seed: source):
            selected, sources = MODULE.select_pilot_queries(
                rows,
                {"KB_Member": 2},
                seed=42,
                pairs_per_source=4,
            )

        self.assertEqual(sources["KB_Member"], ["source-1", "source-3"])
        self.assertEqual(len(selected), 16)
        self.assertEqual(len({row["query"] for row in selected}), 16)


if __name__ == "__main__":
    unittest.main()
