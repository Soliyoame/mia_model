from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.rag.index_builder import build_rag_index
from src.rag.retriever import RagRetriever
from src.utils.io import read_json, write_jsonl


class Bm25RetrieverTests(unittest.TestCase):
    def test_bm25_index_retrieves_rare_matching_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kb_path = root / "kb_member.jsonl"
            index_dir = root / "bm25"
            write_jsonl(
                [
                    {
                        "doc_id": "d-alpha",
                        "group": "KB_Member",
                        "text": "The annual filing discusses ordinary revenue and operating costs.",
                        "text_hash": "h-alpha",
                    },
                    {
                        "doc_id": "d-rare",
                        "group": "KB_Member",
                        "text": "The clinical report records a zephyrbiomarker response in the cohort.",
                        "text_hash": "h-rare",
                    },
                ],
                kb_path,
            )

            manifest = build_rag_index(
                "toy",
                kb_path,
                index_dir,
                retriever_backend="bm25",
                resume=False,
                force=True,
            )
            retriever = RagRetriever(index_dir)
            results = retriever.retrieve("Which report contains zephyrbiomarker?", top_k=1)

            self.assertEqual(manifest["retriever_backend"], "bm25")
            self.assertEqual(manifest["retriever_id"], "bm25")
            self.assertTrue((index_dir / "bm25.index.json").is_file())
            self.assertEqual(results[0].doc_id, "d-rare")

    def test_bm25_preserves_kb_member_only_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_path = root / "bad.jsonl"
            write_jsonl(
                [{"doc_id": "d1", "group": "True_Non_Member", "text": "private record", "text_hash": "h1"}],
                bad_path,
            )
            with self.assertRaises(RuntimeError):
                build_rag_index(
                    "toy",
                    bad_path,
                    root / "index",
                    retriever_backend="bm25",
                    resume=False,
                    force=True,
                )

    def test_dense_and_bm25_manifests_have_distinct_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kb_path = root / "kb.jsonl"
            write_jsonl(
                [{"doc_id": "d1", "group": "KB_Member", "text": "alpha beta gamma delta", "text_hash": "h1"}],
                kb_path,
            )
            build_rag_index(
                "toy",
                kb_path,
                root / "bm25",
                retriever_backend="bm25",
                resume=False,
                force=True,
            )
            manifest = read_json(root / "bm25" / "index_manifest.json")
            self.assertIsNone(manifest["embedding_model"])
            self.assertEqual(manifest["index_filename"], "bm25.index.json")

    def test_resume_rejects_index_protocol_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kb_path = root / "kb.jsonl"
            index_dir = root / "bm25"
            write_jsonl(
                [{"doc_id": "d1", "group": "KB_Member", "text": "alpha beta", "text_hash": "h1"}],
                kb_path,
            )
            build_rag_index(
                "toy",
                kb_path,
                index_dir,
                retriever_backend="bm25",
                chunk_size=10,
                resume=False,
                force=True,
            )
            resumed = build_rag_index(
                "toy",
                kb_path,
                index_dir,
                retriever_backend="bm25",
                chunk_size=10,
                resume=True,
                force=False,
            )
            self.assertTrue(resumed["skipped_existing"])
            self.assertEqual(resumed["retriever_id"], "bm25")
            with self.assertRaisesRegex(RuntimeError, "index protocol does not match"):
                build_rag_index(
                    "toy",
                    kb_path,
                    index_dir,
                    retriever_backend="bm25",
                    chunk_size=11,
                    resume=True,
                    force=False,
                )

    def test_retriever_rejects_tampered_index_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kb_path = root / "kb.jsonl"
            index_dir = root / "bm25"
            write_jsonl(
                [{"doc_id": "d1", "group": "KB_Member", "text": "alpha beta", "text_hash": "h1"}],
                kb_path,
            )
            build_rag_index(
                "toy",
                kb_path,
                index_dir,
                retriever_backend="bm25",
                resume=False,
                force=True,
            )
            (index_dir / "bm25.index.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "index hash"):
                RagRetriever(index_dir)

            with self.assertRaisesRegex(RuntimeError, "index protocol does not match"):
                build_rag_index(
                    "toy",
                    kb_path,
                    index_dir,
                    retriever_backend="bm25",
                    resume=True,
                    force=False,
                )


if __name__ == "__main__":
    unittest.main()
