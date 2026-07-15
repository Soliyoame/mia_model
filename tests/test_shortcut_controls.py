from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_shortcut_controls.py"
SPEC = importlib.util.spec_from_file_location("analyze_shortcut_controls", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _FakeEmbedding:
    name = "fake"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray([
            [float("alpha" in text.lower()), float("beta" in text.lower())]
            for text in texts
        ], dtype="float32")


class ShortcutControlTests(unittest.TestCase):
    def test_features_use_equal_chunk_mean_and_retrieval_metadata(self) -> None:
        queries = [
            {"query_id": "q1", "audit_id": "a1", "source_key": "s1", "source_id": "s1", "group": "KB_Member", "query": "alpha 123", "accepted": True},
            {"query_id": "q2", "audit_id": "a1", "source_key": "s1", "source_id": "s1", "group": "KB_Member", "query": "alpha", "accepted": True},
            {"query_id": "q3", "audit_id": "a2", "source_key": "s1", "source_id": "s1", "group": "KB_Member", "query": "beta", "accepted": True},
        ]
        benchmark = [
            {"audit_id": "a1", "text": "alpha text"},
            {"audit_id": "a2", "text": "beta text"},
        ]
        responses = [
            {"query_id": "q1", "response": "ok", "error": None, "target_doc_retrieved": True, "retrieval_scores": [0.8]},
            {"query_id": "q2", "response": "ok", "error": None, "target_doc_retrieved": False, "retrieval_scores": [0.4]},
            {"query_id": "q3", "response": "ok", "error": None, "target_doc_retrieved": True, "retrieval_scores": [0.6]},
        ]
        rows = MODULE.build_source_shortcut_features(queries, benchmark, responses, _FakeEmbedding())
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["retrieval_target_hit_rate"], 0.75)
        self.assertAlmostEqual(rows[0]["retrieval_max_score"], 0.6)
        self.assertAlmostEqual(rows[0]["embedding_query_document_cosine"], 1.0)

    def test_report_excludes_reserve_and_uses_common_sources(self) -> None:
        main = [
            {"source_key": "m", "group": "KB_Member", "pcv_score": 2.0},
            {"source_key": "n", "group": "True_Non_Member", "pcv_score": 0.0},
            {"source_key": "r", "group": "Reserve", "pcv_score": 2.0},
        ]
        feature_rows = [
            {"source_key": "m", "group": "KB_Member", **{key: 1.0 for key in MODULE.FEATURE_ACCESS}},
            {"source_key": "n", "group": "True_Non_Member", **{key: 0.0 for key in MODULE.FEATURE_ACCESS}},
            {"source_key": "r", "group": "Reserve", **{key: 1.0 for key in MODULE.FEATURE_ACCESS}},
        ]
        report = MODULE.build_shortcut_report(main, feature_rows, n_bootstrap=10, seed=42)
        for value in report.values():
            self.assertEqual(value["source_count"], 2)
            self.assertEqual(value["metrics"]["AUC"], 1.0)


if __name__ == "__main__":
    unittest.main()
