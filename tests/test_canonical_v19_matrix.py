from __future__ import annotations

import unittest
from collections import Counter
from types import SimpleNamespace

from scripts.run_pipeline import build_steps
from src.utils.io import load_yaml
from src.utils.run_context import (
    build_experiment_identity,
    canonical_baseline_methods,
    canonical_defense_required,
    model_scoped_dir,
)


class CanonicalV19MatrixTests(unittest.TestCase):
    def test_full_generator_id_maps_to_one_model_directory(self) -> None:
        path = model_scoped_dir(
            "outputs/test",
            "pubmed",
            model="qwen/qwen3.5-397b-a17b",
        )
        self.assertEqual(path.name, "qwen3.5-397b-a17b")

    def test_registry_contains_exactly_24_main_and_12_matched_cells(self) -> None:
        config = load_yaml("configs/canonical_suite.yaml")
        cells = list(config["cells"])
        self.assertEqual(config["protocol"]["pairs_per_source"], 3)
        self.assertEqual(config["protocol"]["queries_per_source_per_cell"], 6)
        counts = Counter(str(cell["run_role"]) for cell in cells)
        self.assertEqual(len(cells), 36)
        self.assertEqual(counts, {"main": 24, "matched_control": 12})
        self.assertEqual({cell["dataset"] for cell in cells}, {"edgar", "enron", "pubmed"})

        main = [cell for cell in cells if cell["run_role"] == "main"]
        matched = [cell for cell in cells if cell["run_role"] == "matched_control"]
        self.assertEqual({cell["retriever_backend"] for cell in main}, {"dense", "bm25"})
        self.assertEqual({cell["retriever_backend"] for cell in matched}, {"none"})
        self.assertEqual(len({cell["victim_model"] for cell in cells}), 4)
        self.assertEqual(len({(cell["dataset"], cell["victim_model"], cell["retriever_backend"], cell["run_role"]) for cell in cells}), 36)

    def test_retriever_identity_changes_experiment_cell(self) -> None:
        base = {
            "dataset": "edgar",
            "run_role": "main",
            "split_seed": 42,
            "scale": "formal",
            "victim_model": "gpt-4.1-mini",
            "generator_version": "gpt-4.1-mini",
            "benchmark": {"benchmark_hash": "benchmark"},
            "configs": {},
            "protocol": {},
            "git": {"commit": "commit"},
        }
        dense = build_experiment_identity(
            {**base, "retriever_backend": "dense", "retriever_id": "sentence-transformers/all-MiniLM-L6-v2", "index_manifest_hash": "dense-hash"},
            "sources",
        )
        bm25 = build_experiment_identity(
            {**base, "retriever_backend": "bm25", "retriever_id": "bm25", "index_manifest_hash": "bm25-hash"},
            "sources",
        )
        self.assertNotEqual(dense, bm25)

    def test_baseline_and_defense_policies_match_v19_plan(self) -> None:
        self.assertEqual(
            canonical_baseline_methods("qwen/qwen3.5-397b-a17b"),
            ("RAG-MIA", "S2MIA", "MBA", "IA", "DCMI"),
        )
        self.assertEqual(canonical_baseline_methods("gpt-4.1-mini"), ("IA", "DCMI"))
        self.assertTrue(
            canonical_defense_required("pubmed", "qwen/qwen3.5-397b-a17b", "dense")
        )
        self.assertFalse(
            canonical_defense_required("pubmed", "qwen/qwen3.5-397b-a17b", "bm25")
        )

    def test_pipeline_forwards_one_retriever_to_baselines(self) -> None:
        args = SimpleNamespace(
            dataset="pubmed",
            baseline_config="configs/baseline_config.yaml",
            rag_config="configs/rag_config.yaml",
            retriever_backend="bm25",
            baseline_methods=None,
            force=False,
            no_resume=False,
        )
        step = next(item for item in build_steps() if item.number == 12)
        built = step.build_args(args)
        self.assertEqual(built.count("--retriever-backend"), 1)
        self.assertIn("bm25", built)
        self.assertEqual(built[built.index("--rag-config") + 1], args.rag_config)


if __name__ == "__main__":
    unittest.main()
