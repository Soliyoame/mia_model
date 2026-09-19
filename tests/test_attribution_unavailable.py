from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.evaluation.metrics import summarize_membership_scores
from src.scoring.pcv_scorer import compute_pcv_scores
from src.utils.io import read_json, read_jsonl, write_jsonl


class AttributionUnavailableTests(unittest.TestCase):
    def test_missing_llm_only_stays_unavailable_instead_of_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = root / "parsed.jsonl"
            queries = root / "queries.jsonl"
            scores = root / "scores.jsonl"
            base = {
                "audit_id": "a1",
                "source_id": "s1",
                "source_key": "s1",
                "dataset": "toy",
                "group": "KB_Member",
                "pair_id": "p1",
                "fact_id": "f1",
                "query_type": "compressed_verification",
            }
            write_jsonl(
                [
                    {**base, "mode": "rag", "claim_type": "true", "supports_true_claim": True},
                    {**base, "mode": "rag", "claim_type": "counterfactual", "corrects_to_original_entity": True},
                ],
                parsed,
            )
            write_jsonl(
                [
                    {**base, "query_id": "q-plus", "claim_type": "true", "accepted": True},
                    {**base, "query_id": "q-minus", "claim_type": "counterfactual", "accepted": True},
                ],
                queries,
            )

            manifest = compute_pcv_scores(
                "toy",
                parsed,
                scores,
                queries_path=queries,
                force=True,
            )
            audit = list(read_jsonl(scores))[0]
            pair = list(read_jsonl(root / "scores_pair_scores.jsonl"))[0]
            source = list(read_jsonl(root / "scores_source_scores.jsonl"))[0]

            self.assertEqual(audit["pcv_score"], 2.0)
            self.assertIsNone(audit["cvg_llm"])
            self.assertIsNone(audit["cg_cvg"])
            self.assertEqual(audit["attribution_status"], "unavailable")
            self.assertIsNone(pair["cvg_llm"])
            self.assertIsNone(source["cg_cvg"])
            self.assertEqual(manifest["attribution_status"], "unavailable")
            self.assertEqual(read_json(scores.with_suffix(".manifest.json"))["attribution_status"], "unavailable")

            metrics = summarize_membership_scores(
                [
                    {"group": "KB_Member", "cg_cvg": None},
                    {"group": "True_Non_Member", "cg_cvg": None},
                ],
                score_key="cg_cvg",
            )
            self.assertEqual(metrics["status"], "unavailable")
            self.assertIsNone(metrics["AUC"])
            self.assertEqual(metrics["threshold_curve"], [])


if __name__ == "__main__":
    unittest.main()
