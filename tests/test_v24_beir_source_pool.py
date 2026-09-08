from __future__ import annotations

import json
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "v24_beir_builder", Path(__file__).resolve().parents[1] / "scripts/54_build_v24_beir_source_pools.py"
)
assert _SPEC and _SPEC.loader
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)


class V24BeirSourcePoolBuilderTests(unittest.TestCase):
    def _corpus(self, root: Path, rows: list[dict[str, object]]) -> Path:
        path = root / "corpus.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_uniform_mapping_and_single_chunk_without_queries_or_qrels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            corpus = self._corpus(root, [{"_id": "d2", "title": "Title", "text": "Body"},
                                        {"_id": "d1", "title": "", "text": "Only body"}])
            with patch.object(builder, "V24_SOURCE_POOL_MINIMUM", 1):
                result = builder.build_source_pool("nfcorpus", corpus, root / "out")
            self.assertEqual(result["frozen_source_count"], 2)
            self.assertFalse((root / "out/nfcorpus/queries.jsonl").exists())
            connection = sqlite3.connect(root / "out/nfcorpus/source_pool.sqlite3")
            try:
                rows = connection.execute("SELECT document_id, full_text FROM sources ORDER BY document_id").fetchall()
                chunks = connection.execute("SELECT chunk_rank FROM chunks").fetchall()
            finally:
                connection.close()
            self.assertEqual(rows, [("d1", "Only body"), ("d2", "Title\n\nBody")])
            self.assertEqual(chunks, [(0,), (0,)])

    def test_duplicate_document_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            corpus = self._corpus(root, [{"_id": "d1", "title": "A", "text": "B"},
                                        {"_id": "d1", "title": "C", "text": "D"}])
            with self.assertRaisesRegex(ValueError, "duplicate_document_id"):
                builder.build_source_pool("scidocs", corpus, root / "out")

    def test_duplicate_normalized_text_keeps_first_in_document_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            corpus = self._corpus(root, [{"_id": "d2", "title": "Same", "text": "Text"},
                                        {"_id": "d1", "title": "Same", "text": "Text"}])
            with patch.object(builder, "V24_SOURCE_POOL_MINIMUM", 1):
                result = builder.build_source_pool("trec-covid", corpus, root / "out")
            self.assertEqual(result["duplicate_text_count"], 1)
            self.assertEqual(result["frozen_source_count"], 1)
            self.assertEqual(result["development_exclusions"][0]["document_id"], "d1")

    def test_capacity_gate_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            corpus = self._corpus(root, [{"_id": "d1", "title": "A", "text": "B"}])
            with patch.object(builder, "V24_SOURCE_POOL_MINIMUM", 2):
                with self.assertRaisesRegex(RuntimeError, "insufficient_source_pool_capacity"):
                    builder.build_source_pool("nfcorpus", corpus, root / "out")


if __name__ == "__main__":
    unittest.main()
