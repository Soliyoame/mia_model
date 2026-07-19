from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.evaluation.mechanism_analysis import run_mechanism_analysis
from src.utils.io import write_jsonl


class MechanismAnalysisTests(unittest.TestCase):
    def test_main_report_uses_rag_only_pvs_not_legacy_context_gain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.jsonl"
            responses = root / "responses.jsonl"
            parsed = root / "parsed.jsonl"
            scores = root / "scores.jsonl"
            docstore = root / "docstore.jsonl"
            output = root / "mechanism.json"
            write_jsonl([{
                "query_id": "q1",
                "expected_entity": "Alice",
                "query_doc_similarity": 0.5,
            }], queries)
            write_jsonl([{
                "query_id": "q1",
                "retrieved_doc_ids": ["d1"],
                "target_doc_retrieved": True,
            }], responses)
            write_jsonl([{
                "query_id": "q1",
                "mode": "rag",
                "group": "KB_Member",
                "claim_type": "true",
                "supports_true_claim": True,
            }], parsed)
            write_jsonl([{
                "group": "KB_Member",
                "pcv_score": 1.25,
                "cg_cvg": -9.0,
            }], scores)
            write_jsonl([{"doc_id": "d1", "text": "Alice"}], docstore)

            report = run_mechanism_analysis(
                "toy",
                queries,
                responses,
                parsed,
                scores,
                docstore,
                output,
                resume=False,
                force=True,
            )

            self.assertNotIn("Context Gain", report)
            self.assertEqual(report["RAG-only PVS"]["score_key"], "pcv_score")
            self.assertEqual(report["RAG-only PVS"]["overall_avg"], 1.25)
            self.assertEqual(report["RAG-only PVS"]["by_group"]["KB_Member"], 1.25)


if __name__ == "__main__":
    unittest.main()
