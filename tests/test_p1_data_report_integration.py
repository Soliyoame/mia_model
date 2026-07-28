"""P1 数据隔离与最终报告集成回归测试。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.evaluation.report_builder import generate_final_report
from src.prepare.benchmark_builder import build_pcv_attack_benchmark
from src.prepare.splitter import GROUP_FILENAMES, split_dataset_pcv_mia
from src.utils.io import read_json, read_jsonl, write_json, write_jsonl
from src.utils.hash import sha256_file, sha256_obj


class DataIsolationIntegrationTests(unittest.TestCase):
    def test_source_exclusive_split_is_reproducible_and_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "processed.jsonl"
            rows = []
            for source_idx in range(4):
                for chunk_idx in range(2):
                    rows.append({
                        "doc_id": f"d-{source_idx}-{chunk_idx}",
                        "source_id": f"source-{source_idx}",
                        "source_path": f"corpus/source-{source_idx}.txt",
                        "text": f"source {source_idx} chunk {chunk_idx}",
                        "text_hash": f"hash-{source_idx}-{chunk_idx}",
                    })
            write_jsonl(rows, processed)

            manifests = []
            source_sets_by_run = []
            for name in ("split-a", "split-b"):
                out = root / name
                manifests.append(split_dataset_pcv_mia(
                    "toy", processed, out,
                    kb_member=2, true_non_member=2, spoof_seed=2, reserve=2,
                    seed=17, source_exclusive=True, per_source_cap=2,
                    resume=False, force=True,
                ))
                source_sets = {}
                hash_sets = {}
                for group, filename in GROUP_FILENAMES.items():
                    group_rows = list(read_jsonl(out / filename))
                    source_sets[group] = {row["metadata"]["source_key"] for row in group_rows}
                    hash_sets[group] = {row["text_hash"] for row in group_rows}
                    if group == "KB_Member":
                        self.assertTrue(all(row["metadata"]["in_knowledge_base"] for row in group_rows))
                    else:
                        self.assertTrue(all(not row["metadata"]["in_knowledge_base"] for row in group_rows))
                for i, left in enumerate(GROUP_FILENAMES):
                    for right in list(GROUP_FILENAMES)[i + 1:]:
                        self.assertFalse(source_sets[left] & source_sets[right])
                        self.assertFalse(hash_sets[left] & hash_sets[right])
                source_sets_by_run.append(source_sets)

            self.assertEqual(manifests[0]["hash_summary"], manifests[1]["hash_summary"])
            self.assertEqual(source_sets_by_run[0], source_sets_by_run[1])

    def test_benchmark_rejects_nonmember_marked_as_kb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb.jsonl"
            nonmember = root / "tn.jsonl"
            reserve = root / "reserve.jsonl"
            write_jsonl([{"doc_id": "k", "source_id": "ks", "text": "member", "text_hash": "kh"}], kb)
            write_jsonl([{
                "doc_id": "n", "source_id": "ns", "text": "nonmember", "text_hash": "nh",
                "in_knowledge_base": True,
            }], nonmember)
            write_jsonl([{"doc_id": "r", "source_id": "rs", "text": "reserve", "text_hash": "rh"}], reserve)
            with self.assertRaises(RuntimeError):
                build_pcv_attack_benchmark(
                    "toy", kb, nonmember, None, root / "benchmark.jsonl",
                    include_spoofed_nonmember=False, reserve_path=reserve,
                    include_reserve=True, resume=False, force=True,
                )

    def test_benchmark_resume_is_bound_to_split_protocol_and_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb.jsonl"
            nonmember = root / "tn.jsonl"
            reserve = root / "reserve.jsonl"
            split_manifest = root / "split_manifest.json"
            write_jsonl([{"doc_id": "k", "source_id": "ks", "text": "member", "text_hash": "kh"}], kb)
            write_jsonl([{"doc_id": "n", "source_id": "ns", "text": "nonmember", "text_hash": "nh"}], nonmember)
            write_jsonl([{"doc_id": "r", "source_id": "rs", "text": "reserve", "text_hash": "rh"}], reserve)
            write_json({"target_unit": "sources", "seed": 42}, split_manifest)
            kwargs = {
                "dataset": "toy",
                "kb_member_path": kb,
                "true_non_member_path": nonmember,
                "spoofed_non_member_path": None,
                "output_path": root / "toy_attack_benchmark.jsonl",
                "include_spoofed_nonmember": False,
                "reserve_path": reserve,
                "include_reserve": True,
                "config_snapshot": {"protocol": "v19"},
                "split_manifest_path": split_manifest,
                "split_protocol_snapshot": {"target_unit": "sources", "seed": 42},
            }
            build_pcv_attack_benchmark(**kwargs, resume=False, force=True)
            resumed = build_pcv_attack_benchmark(**kwargs, resume=True, force=False)
            self.assertTrue(resumed["skipped_existing"])
            with self.assertRaisesRegex(RuntimeError, "split/config protocol"):
                build_pcv_attack_benchmark(
                    **{**kwargs, "split_protocol_snapshot": {"target_unit": "records", "seed": 42}},
                    resume=True,
                    force=False,
                )


class ReportIntegrationTests(unittest.TestCase):
    def test_final_report_integrates_source_scores_and_auxiliary_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark = root / "benchmark.jsonl"
            scores = root / "scores_source_scores.jsonl"
            baseline = root / "baseline_comparison.jsonl"
            mechanism = root / "mechanism.json"
            defense = root / "defense.json"
            report_json = root / "final_report.json"
            report_md = root / "summary.md"

            write_jsonl([
                {"audit_id": "a1", "source_key": "m1", "group": "KB_Member"},
                {"audit_id": "a2", "source_key": "n1", "group": "True_Non_Member"},
                {"audit_id": "a3", "source_key": "r1", "group": "Reserve"},
            ], benchmark)
            write_jsonl([
                {"source_key": "m1", "group": "KB_Member", "pcv_score": 1.0, "cvg_rag": 1.0},
                {"source_key": "n1", "group": "True_Non_Member", "pcv_score": 0.0, "cvg_rag": 0.0},
                {"source_key": "r1", "group": "Reserve", "pcv_score": 0.1, "cvg_rag": 0.1},
            ], scores)
            baseline_row = {"baseline": "MBA", "AUC": 0.75, "evaluation_unit": "source"}
            write_jsonl([baseline_row], baseline)
            write_json({"retrieval_hit_rate": 0.8}, mechanism)
            write_json({"defense": "paraphrase", "AUC": 0.6}, defense)

            generate_final_report(
                "toy", benchmark, scores,
                root / "missing_stealth.json", root / "missing_index.json",
                baseline, mechanism, defense,
                report_json, report_md,
                threshold=0.5, resume=False, force=True,
            )
            report = read_json(report_json)
            self.assertEqual(report["main_score_key"], "pcv_score")
            self.assertEqual(report["evaluation_unit"], "source")
            self.assertEqual(report["source_whitelist_hash"], sha256_obj(["m1", "n1"]))
            self.assertEqual(report["input_provenance"]["source_scores"]["sha256"], sha256_file(scores))
            self.assertEqual(report["data_statistics"]["num_scored_sources"], 3)
            self.assertEqual(report["baseline_comparison"], [baseline_row])
            self.assertEqual(report["mechanism_analysis"]["retrieval_hit_rate"], 0.8)
            self.assertEqual(report["defense_privacy_utility_tradeoff"]["defense"], "paraphrase")
            self.assertEqual(report["main_attack_results"]["AUC"], 1.0)
            self.assertEqual(report["calibrated_attack_results"]["alpha_0.01"]["reserve_count"], 1)
            self.assertIn("Oracle TPR@1%FPR", report_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
