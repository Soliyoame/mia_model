from __future__ import annotations

import unittest
from collections import Counter
from types import SimpleNamespace

from scripts.run_pipeline import (
    build_steps,
    canonical_analysis_commands,
    selected_steps,
)
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
        config = load_yaml("configs/canonical_suite_v20_llama.yaml")
        cells = list(config["cells"])
        self.assertEqual(config["protocol"]["pairs_per_source"], 3)
        self.assertEqual(config["protocol"]["queries_per_source_per_cell"], 6)
        counts = Counter(str(cell["run_role"]) for cell in cells)
        self.assertEqual(len(cells), 12)
        self.assertEqual(counts, {"main": 9, "matched_control": 3})
        self.assertEqual({cell["dataset"] for cell in cells}, {"edgar", "enron", "pubmed"})

        main = [cell for cell in cells if cell["run_role"] == "main"]
        matched = [cell for cell in cells if cell["run_role"] == "matched_control"]
        self.assertEqual({cell["retriever_backend"] for cell in main}, {"dense", "bm25", "hybrid"})
        self.assertEqual({cell["retriever_backend"] for cell in matched}, {"none"})
        self.assertEqual(len({cell["victim_model"] for cell in cells}), 1)
        self.assertEqual(len({(cell["dataset"], cell["victim_model"], cell["retriever_backend"], cell["run_role"]) for cell in cells}), 12)

    def test_retriever_identity_changes_experiment_cell(self) -> None:
        base = {
            "dataset": "edgar",
            "run_role": "main",
            "split_seed": 42,
            "scale": "formal",
            "generator_family": "llama",
            "concrete_model": "meta/llama-3.1-70b-instruct",
            "victim_model": "meta/llama-3.1-70b-instruct",
            "generator_version": "meta/llama-3.1-70b-instruct",
            "benchmark": {"benchmark_hash": "benchmark"},
            "configs": {},
            "protocol": {},
            "git": {"commit": "commit"},
        }
        dense = build_experiment_identity(
            {**base, "retriever_backend": "dense", "retriever_id": "BAAI/bge-base-en-v1.5", "index_manifest_hash": "dense-hash"},
            "sources",
        )
        bm25 = build_experiment_identity(
            {**base, "retriever_backend": "bm25", "retriever_id": "bm25", "index_manifest_hash": "bm25-hash"},
            "sources",
        )
        self.assertNotEqual(dense, bm25)

    def test_baseline_and_defense_policies_match_v20_plan(self) -> None:
        self.assertEqual(
            canonical_baseline_methods("meta/llama-3.1-70b-instruct"),
            ("RAG-MIA", "S2MIA", "MBA", "IA", "DCMI", "MEntA"),
        )
        self.assertEqual(canonical_baseline_methods("qwen/qwen3.5-397b-a17b"), ())
        self.assertTrue(
            canonical_defense_required("pubmed", "meta/llama-3.1-70b-instruct", "dense")
        )
        self.assertFalse(
            canonical_defense_required("pubmed", "meta/llama-3.1-70b-instruct", "bm25")
        )

    def test_pipeline_forwards_one_retriever_to_baselines(self) -> None:
        args = SimpleNamespace(
            dataset="pubmed",
            baseline_config="configs/baseline_config.yaml",
            rag_config="configs/rag_config.yaml",
            retriever_backend="bm25",
            baseline_methods=None,
            generator_family=None,
            force=False,
            no_resume=False,
        )
        step = next(item for item in build_steps() if item.number == 12)
        built = step.build_args(args)
        self.assertEqual(built.count("--retriever-backend"), 1)
        self.assertIn("bm25", built)
        self.assertEqual(built[built.index("--rag-config") + 1], args.rag_config)

    def test_canonical_analysis_uses_frozen_concrete_model(self) -> None:
        args = SimpleNamespace(
            dataset="edgar",
            concrete_model="meta/llama-3.1-70b-instruct",
            generator_family="llama",
            victim_profile=None,
            retriever_backend="dense",
            rag_config="configs/rag_config.yaml",
            pcv_config="configs/pcv_attack_config.yaml",
            force=False,
        )
        commands = canonical_analysis_commands(args)
        self.assertTrue(commands)
        for _, command in commands:
            if "--model" in command:
                self.assertEqual(
                    command[command.index("--model") + 1],
                    "llama-3.1-70b-instruct",
                )
        online_commands = [
            command for name, command in commands if name.startswith("run_query_control:")
        ]
        self.assertTrue(online_commands)
        self.assertTrue(all("--generator-family" in command for command in online_commands))
        self.assertTrue(all("--retriever-backend" in command for command in online_commands))

    def test_non_dense_default_pipeline_skips_dense_representative_steps(self) -> None:
        args = SimpleNamespace(
            run_role="main",
            retriever_backend="bm25",
            from_step=1,
            to_step=15,
            only_steps="",
            skip_steps="",
        )
        selected = selected_steps(args, {})
        self.assertFalse({12, 13, 14} & {step.number for step in selected})

        args.only_steps = "13"
        selected = selected_steps(args, {})
        self.assertEqual([step.number for step in selected], [13])


if __name__ == "__main__":
    unittest.main()
