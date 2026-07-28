"""思路 v16 中 P0 研究协议的回归测试。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.baselines.victim_harness import aggregate_baseline_source_scores
from src.evaluation.metrics import (
    clopper_pearson_interval,
    conformal_nonmember_p_value,
    summarize_conformal_membership,
    summarize_membership_scores,
)
from src.utils.io import read_json, write_json, write_jsonl
from src.utils.run_context import (
    CANONICAL_SELECTION_RULE,
    P0_PROTOCOL,
    artifact_inventory,
    build_experiment_identity,
    canonical_eligibility,
    register_canonical_run,
    resolve_suite_run,
)
from src.utils.hash import sha256_file, sha256_obj


class P0MetricsTests(unittest.TestCase):
    def test_clopper_pearson_handles_zero_false_positives(self) -> None:
        lower, upper = clopper_pearson_interval(0, 200)
        self.assertEqual(lower, 0.0)
        self.assertIsNotNone(upper)
        self.assertGreater(upper, 0.0)
        self.assertLess(upper, 0.03)

    def test_low_fpr_curve_has_zero_fpr_endpoint(self) -> None:
        rows = [
            {"group": "KB_Member", "pcv_score": 1.0},
            {"group": "True_Non_Member", "pcv_score": 0.0},
        ]
        metrics = summarize_membership_scores(rows)
        self.assertIsNotNone(metrics["Oracle TPR@1%FPR"])
        self.assertTrue(any(point["FPR"] == 0.0 for point in metrics["threshold_curve"]))

    def test_conformal_ties_are_conservative_and_reserve_is_not_test_data(self) -> None:
        self.assertEqual(conformal_nonmember_p_value(1.0, [1.0, 1.0]), 1.0)
        rows = [
            {"group": "Reserve", "pcv_score": 0.2},
            {"group": "Reserve", "pcv_score": 0.3},
            {"group": "KB_Member", "pcv_score": 1.0},
            {"group": "True_Non_Member", "pcv_score": 0.1},
        ]
        metric = summarize_conformal_membership(rows, alpha=0.5)
        self.assertEqual(metric["reserve_count"], 2)
        self.assertEqual(metric["eval_count"], 2)
        self.assertEqual(metric["positive_count"], 1)
        self.assertEqual(metric["negative_count"], 1)


class P0SourceUnitTests(unittest.TestCase):
    def test_main_query_budget_is_three_pairs_and_six_calls(self) -> None:
        self.assertEqual(P0_PROTOCOL["pairs_per_source"], 3)
        self.assertEqual(P0_PROTOCOL["queries_per_source_per_cell"], 6)

    def test_baseline_scores_aggregate_by_source(self) -> None:
        rows = [
            {"baseline": "MBA", "doc_id": "d1", "source_key": "s1", "group": "KB_Member", "score": 0.2},
            {"baseline": "MBA", "doc_id": "d2", "source_key": "s1", "group": "KB_Member", "score": 0.8},
        ]
        source_rows = aggregate_baseline_source_scores(rows)
        self.assertEqual(len(source_rows), 1)
        self.assertEqual(source_rows[0]["score"], 0.5)
        self.assertEqual(source_rows[0]["num_chunks"], 2)

    def test_baseline_rejects_source_crossing_groups(self) -> None:
        rows = [
            {"doc_id": "d1", "source_key": "s1", "group": "KB_Member", "score": 0.2},
            {"doc_id": "d2", "source_key": "s1", "group": "True_Non_Member", "score": 0.8},
        ]
        with self.assertRaises(RuntimeError):
            aggregate_baseline_source_scores(rows)


class P0CanonicalRunTests(unittest.TestCase):
    def _eligible_fixture(self, root: Path) -> dict:
        (root / "scores").mkdir(parents=True)
        (root / "reports").mkdir(parents=True)
        (root / "baselines").mkdir(parents=True)
        (root / "stealth_filtered_queries").mkdir(parents=True)
        (root / "rag_responses").mkdir(parents=True)
        (root / "llm_only_responses").mkdir(parents=True)
        score_path = root / "scores" / "toy_pcv_scores_source_scores.jsonl"
        write_jsonl([{"source_key": "s1", "group": "KB_Member", "pcv_score": 1.0}], score_path)
        write_jsonl([{"source_key": "s1", "group": "KB_Member", "evaluation_eligible": True}],
                    root / "scores" / "toy_pcv_scores_source_coverage.jsonl")
        write_jsonl([{"query_id": "q1", "accepted": True}], root / "stealth_filtered_queries" / "toy.jsonl")
        response = {"query_id": "q1", "response": "Consistent", "error": None}
        write_jsonl([response], root / "rag_responses" / "toy.jsonl")
        write_jsonl([response], root / "llm_only_responses" / "toy.jsonl")
        whitelist_hash = sha256_obj(["s1"])
        write_json({
            "dataset": "toy",
            "evaluation_unit": "source",
            "source_whitelist_hash": whitelist_hash,
            "input_provenance": {"source_scores": {"sha256": sha256_file(score_path)}},
        }, root / "reports" / "toy_final_report.json")
        write_jsonl([{"baseline": "MBA", "evaluation_unit": "source"}],
                    root / "baselines" / "toy_baseline_comparison.jsonl")
        write_jsonl([{"baseline": "MBA", "source_key": "s1", "group": "KB_Member", "score": 0.5}],
                    root / "baselines" / "toy_MBA_scores_source_scores.jsonl")
        (root / "provenance").mkdir()
        (root / "provenance" / "000_data.yaml").write_text("seed: 42\n", encoding="utf-8")
        inventory = artifact_inventory(root)
        manifest = {
            "run_id": "run-1",
            "dataset": "toy",
            "run_role": "main",
            "status": "candidate",
            "source": "pipeline (run_pipeline.py)",
            "victim_model": "victim-model",
            "victim_provider": "openai_compatible",
            "victim_endpoint": "https://example.invalid/v1",
            "generator_id": "victim-model",
            "generator_version": "victim-model-v1",
            "retriever_backend": "dense",
            "retriever_id": "sentence-transformers/all-MiniLM-L6-v2",
            "index_manifest_hash": "index-hash",
            "scale": "formal",
            "split_seed": 42,
            "git": {"commit": "abc123", "dirty": False},
            "steps_failed": None,
            "steps_selected": [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
            "steps_run": [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
            "benchmark": {"benchmark_hash": "fixed-hash", "hash_matches": True},
            "configs": {"data": {"sha256": "config-hash"}},
            "preregistration": {
                "sha256": "preregistered-hash",
                "suite_id": "submission",
                "selection_rule": CANONICAL_SELECTION_RULE,
                "cell": {
                    "dataset": "toy",
                    "victim_model": "victim-model",
                    "run_role": "main",
                    "retriever_backend": "dense",
                    "scale": "formal",
                    "seed": 42,
                },
            },
            "input_provenance": [{"exists": True, "sha256": "input-hash"}],
            "archive": {
                "inventory": inventory,
                "inventory_hash": sha256_obj(inventory),
                "provenance_files": [{
                    "path": "provenance/000_data.yaml",
                    "source_path": "data.yaml",
                    "sha256": sha256_file(root / "provenance" / "000_data.yaml"),
                }],
            },
            "protocol": P0_PROTOCOL,
            "run_llm_only": False,
            "canonical_analyses_completed": [
                "offline_ablation",
                "shortcut_controls",
                "query_control:random_same_type_counterfactual",
                "query_control:independent_unpaired_query",
                "query_control:no_stealth_filter",
            ],
        }
        manifest["experiment_identity"] = build_experiment_identity(manifest, whitelist_hash)
        return manifest

    def _matched_fixture(self, root: Path) -> dict:
        (root / "stealth_filtered_queries").mkdir(parents=True)
        (root / "llm_only_responses").mkdir(parents=True)
        query_path = root / "stealth_filtered_queries" / "toy_paired_queries.jsonl"
        write_jsonl([{
            "query_id": "q1",
            "source_key": "s1",
            "group": "KB_Member",
            "accepted": True,
        }], query_path)
        write_jsonl([{
            "query_id": "q1",
            "response": "Consistent",
            "error": None,
        }], root / "llm_only_responses" / "toy_llm_only_responses.jsonl")
        whitelist_hash = sha256_obj(["s1"])
        write_json({
            "run_rag": False,
            "run_llm_only": True,
            "queries_hash": sha256_file(query_path),
            "source_whitelist_hash": whitelist_hash,
        }, root / "llm_only_responses" / "toy_llm_only_responses.manifest.json")
        (root / "provenance").mkdir()
        (root / "provenance" / "000_data.yaml").write_text("seed: 42\n", encoding="utf-8")
        inventory = artifact_inventory(root)
        manifest = {
            "run_id": "matched-1",
            "dataset": "toy",
            "run_role": "matched_control",
            "status": "candidate",
            "source": "pipeline (run_pipeline.py)",
            "victim_model": "victim-model",
            "victim_provider": "openai_compatible",
            "victim_endpoint": "https://example.invalid/v1",
            "generator_id": "victim-model",
            "generator_version": "victim-model-v1",
            "retriever_backend": None,
            "retriever_id": None,
            "index_manifest_hash": None,
            "scale": "formal",
            "split_seed": 42,
            "git": {"commit": "abc123", "dirty": False},
            "steps_failed": None,
            "steps_selected": [10],
            "steps_run": [10],
            "benchmark": {"benchmark_hash": "fixed-hash", "hash_matches": True},
            "configs": {"data": {"sha256": "config-hash"}},
            "preregistration": {
                "sha256": "preregistered-hash",
                "suite_id": "submission",
                "selection_rule": CANONICAL_SELECTION_RULE,
                "cell": {
                    "dataset": "toy",
                    "victim_model": "victim-model",
                    "run_role": "matched_control",
                    "retriever_backend": "none",
                    "scale": "formal",
                    "seed": 42,
                },
            },
            "input_provenance": [{"exists": True, "sha256": "input-hash"}],
            "archive": {
                "inventory": inventory,
                "inventory_hash": sha256_obj(inventory),
                "provenance_files": [{
                    "path": "provenance/000_data.yaml",
                    "source_path": "data.yaml",
                    "sha256": sha256_file(root / "provenance" / "000_data.yaml"),
                }],
            },
            "protocol": P0_PROTOCOL,
            "run_llm_only": True,
        }
        manifest["experiment_identity"] = build_experiment_identity(manifest, whitelist_hash)
        return manifest

    def test_canonical_gate_requires_clean_reproducible_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._eligible_fixture(root)
            self.assertTrue(canonical_eligibility(manifest, root)["eligible"])
            manifest["git"]["dirty"] = True
            result = canonical_eligibility(manifest, root)
            self.assertFalse(result["eligible"])
            self.assertIn("git_worktree_dirty", result["reasons"])

    def test_rag_only_candidate_does_not_require_llm_only_responses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._eligible_fixture(root)
            for path in (root / "llm_only_responses").glob("*"):
                path.unlink()
            inventory = artifact_inventory(root)
            manifest["archive"]["inventory"] = inventory
            manifest["archive"]["inventory_hash"] = sha256_obj(inventory)
            self.assertTrue(canonical_eligibility(manifest, root)["eligible"])

    def test_main_candidate_rejects_llm_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._eligible_fixture(root)
            manifest["run_llm_only"] = True
            result = canonical_eligibility(manifest, root)
            self.assertFalse(result["eligible"])
            self.assertIn("main_run_must_be_rag_only", result["reasons"])

    def test_matched_control_is_response_only_and_does_not_require_rag_scores_or_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._matched_fixture(root)
            result = canonical_eligibility(manifest, root)
            self.assertTrue(result["eligible"], result["reasons"])
            self.assertEqual(result["integrity"]["source_whitelist"]["source_count"], 1)

    def test_matched_control_requires_complete_llm_only_responses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._matched_fixture(root)
            (root / "llm_only_responses" / "toy_llm_only_responses.jsonl").unlink()
            inventory = artifact_inventory(root)
            manifest["archive"]["inventory"] = inventory
            manifest["archive"]["inventory_hash"] = sha256_obj(inventory)
            result = canonical_eligibility(manifest, root)
            self.assertFalse(result["eligible"])
            self.assertIn("llm_only_responses_incomplete", result["reasons"])

    def test_matched_control_rejects_a_manifest_that_ran_rag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._matched_fixture(root)
            response_manifest_path = (
                root / "llm_only_responses" / "toy_llm_only_responses.manifest.json"
            )
            response_manifest = read_json(response_manifest_path)
            response_manifest["run_rag"] = True
            write_json(response_manifest, response_manifest_path)
            inventory = artifact_inventory(root)
            manifest["archive"]["inventory"] = inventory
            manifest["archive"]["inventory_hash"] = sha256_obj(inventory)
            result = canonical_eligibility(manifest, root)
            self.assertFalse(result["eligible"])
            self.assertIn("matched_control_provenance_invalid", result["reasons"])

    def test_suite_allows_only_one_canonical_per_cell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._eligible_fixture(root / "run")
            manifest_path = root / "run" / "run_manifest.json"
            manifest["status"] = "canonical"
            write_json(manifest, manifest_path)
            with patch("src.utils.run_context.resolve_path", side_effect=lambda value: root / str(value)):
                suite_path = register_canonical_run("submission", manifest, manifest_path)
                suite = read_json(suite_path)
                self.assertEqual(len(suite["cells"]), 1)
                self.assertEqual(suite["status"], "canonical")
                other = {**manifest, "run_id": "run-2"}
                with self.assertRaises(RuntimeError):
                    register_canonical_run("submission", other, manifest_path)

    def test_incomplete_preregistered_suite_cannot_drive_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._eligible_fixture(root / "run")
            manifest["status"] = "canonical"
            manifest["preregistration"]["expected_cells"] = [
                manifest["preregistration"]["cell"],
                {
                    **manifest["preregistration"]["cell"],
                    "dataset": "other",
                },
            ]
            manifest["preregistration"]["expected_cells_hash"] = sha256_obj(
                manifest["preregistration"]["expected_cells"]
            )
            manifest_path = root / "run" / "run_manifest.json"
            write_json(manifest, manifest_path)
            with patch("src.utils.run_context.resolve_path", side_effect=lambda value: root / str(value)):
                suite_path = register_canonical_run("submission", manifest, manifest_path)
                self.assertEqual(read_json(suite_path)["status"], "candidate")
                with self.assertRaises(RuntimeError):
                    resolve_suite_run("submission", dataset="toy", run_role="main")


if __name__ == "__main__":
    unittest.main()
