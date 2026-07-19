"""P2：响应、完整 pair、coverage 与配对统计契约。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.evaluation.metrics import paired_bootstrap_metric_delta
from src.baselines.victim_harness import aggregate_baseline_source_scores
from src.rag.runner import _call_generator, compact_response_rows
from src.parsing.stance_parser import parse_stance_files
from src.scoring.pcv_scorer import compute_pcv_scores
from src.utils.io import read_jsonl, write_jsonl


class ResponseIntegrityTests(unittest.TestCase):
    def test_empty_response_is_retried(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, *_args, **_kwargs) -> str:
                self.calls += 1
                return "   " if self.calls == 1 else "Consistent"

        client = Client()
        response, error = _call_generator(
            client, "prompt", temperature=0.0, timeout=1.0, max_tokens=8,
            retries=1, retry_backoff_base=0.0, retry_backoff_max=0.0,
        )
        self.assertEqual(response, "Consistent")
        self.assertIsNone(error)
        self.assertEqual(client.calls, 2)

    def test_compaction_prefers_success_over_later_failure(self) -> None:
        rows = [
            {"query_id": "q1", "response": "", "error": "timeout"},
            {"query_id": "q1", "response": "Consistent", "error": None},
            {"query_id": "q1", "response": "", "error": "timeout-again"},
        ]
        compacted, stats = compact_response_rows(rows)
        self.assertEqual(len(compacted), 1)
        self.assertEqual(compacted[0]["response"], "Consistent")
        self.assertEqual(stats["duplicates_removed"], 2)

    def test_rag_only_parse_allows_missing_llm_control_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.jsonl"
            rag = root / "rag.jsonl"
            output = root / "stance.jsonl"
            write_jsonl([{
                "query_id": "q1", "pair_id": "p1", "audit_id": "a1", "group": "KB_Member",
                "dataset": "toy", "claim_type": "true", "query_type": "compressed",
            }], queries)
            write_jsonl([{"query_id": "q1", "response": "Consistent", "error": None}], rag)
            manifest = parse_stance_files(
                "toy", queries, rag, root / "missing_llm.jsonl", output,
                resume=False, force=True,
            )
            self.assertEqual(manifest["integrity"]["rag"]["parsed"], 1)
            self.assertEqual(manifest["integrity"]["llm_only"]["parsed"], 0)
            self.assertEqual(manifest["integrity"]["llm_only"]["missing"], 1)

    def test_rag_only_parse_can_exclude_existing_llm_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.jsonl"
            rag = root / "rag.jsonl"
            llm = root / "llm.jsonl"
            output = root / "stance.jsonl"
            query = {
                "query_id": "q1",
                "pair_id": "p1",
                "audit_id": "a1",
                "group": "KB_Member",
                "dataset": "toy",
                "claim_type": "true",
                "query_type": "compressed",
            }
            write_jsonl([query], queries)
            write_jsonl([{**query, "mode": "rag", "response": "Consistent", "error": None}], rag)
            write_jsonl([{**query, "mode": "llm_only", "response": "Unknown", "error": None}], llm)
            manifest = parse_stance_files(
                "toy", queries, rag, None, output, resume=False, force=True,
            )
            self.assertEqual(set(manifest["integrity"]), {"rag"})
            self.assertEqual(manifest["parsed_responses"], 1)
            self.assertEqual([row["mode"] for row in read_jsonl(output)], ["rag"])


class CoverageContractTests(unittest.TestCase):
    def test_incomplete_pair_excludes_entire_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark = root / "benchmark.jsonl"
            queries = root / "queries.jsonl"
            facts = root / "facts.jsonl"
            stance = root / "stance.jsonl"
            output = root / "toy_pcv_scores.jsonl"
            write_jsonl([
                {"audit_id": "a1", "source_key": "s1", "source_id": "s1", "group": "KB_Member"},
                {"audit_id": "a2", "source_key": "s2", "source_id": "s2", "group": "True_Non_Member"},
            ], benchmark)
            write_jsonl([
                {"query_id": f"q-{audit}-{claim}", "pair_id": f"p-{audit}", "query_type": "compressed",
                 "claim_type": claim, "audit_id": audit, "source_key": source, "source_id": source,
                 "fact_id": f"f-{audit}", "group": group, "dataset": "toy", "accepted": True}
                for audit, source, group in (("a1", "s1", "KB_Member"), ("a2", "s2", "True_Non_Member"))
                for claim in ("true", "counterfactual")
            ], queries)
            write_jsonl([
                {"fact_id": "f-a1", "audit_id": "a1", "source_key": "s1", "source_id": "s1", "group": "KB_Member"},
                {"fact_id": "f-a2", "audit_id": "a2", "source_key": "s2", "source_id": "s2", "group": "True_Non_Member"},
            ], facts)
            base = {"dataset": "toy", "query_type": "compressed"}
            write_jsonl([
                {**base, "pair_id": "p-a1", "fact_id": "f-a1", "audit_id": "a1", "source_key": "s1",
                 "source_id": "s1", "group": "KB_Member", "mode": "rag", "claim_type": "true",
                 "supports_true_claim": True},
                {**base, "pair_id": "p-a1", "fact_id": "f-a1", "audit_id": "a1", "source_key": "s1",
                 "source_id": "s1", "group": "KB_Member", "mode": "rag", "claim_type": "counterfactual",
                 "rejects_counterfactual": True},
                {**base, "pair_id": "p-a2", "fact_id": "f-a2", "audit_id": "a2", "source_key": "s2",
                 "source_id": "s2", "group": "True_Non_Member", "mode": "rag", "claim_type": "true",
                 "supports_true_claim": True},
            ], stance)
            manifest = compute_pcv_scores(
                "toy", stance, output, facts_path=facts, benchmark_path=benchmark, queries_path=queries,
                resume=False, force=True,
            )
            source_rows = list(read_jsonl(root / "toy_pcv_scores_source_scores.jsonl"))
            coverage = {row["source_key"]: row for row in read_jsonl(root / "toy_pcv_scores_source_coverage.jsonl")}
            self.assertEqual([row["source_key"] for row in source_rows], ["s1"])
            self.assertTrue(coverage["s1"]["evaluation_eligible"])
            self.assertFalse(coverage["s2"]["evaluation_eligible"])
            self.assertIn("incomplete_rag_pair", coverage["s2"]["reasons"])
            self.assertEqual(manifest["excluded_sources"], 1)


class PairedStatisticsTests(unittest.TestCase):
    def test_baseline_source_aggregation_preserves_actual_call_budget(self) -> None:
        rows = [
            {"baseline": "X", "doc_id": "d1", "source_key": "s", "group": "KB_Member",
             "score": 0.2, "victim_calls": 1, "attacker_calls": 0},
            {"baseline": "X", "doc_id": "d2", "source_key": "s", "group": "KB_Member",
             "score": 0.8, "victim_calls": 2, "attacker_calls": 1},
        ]
        source = aggregate_baseline_source_scores(rows)[0]
        self.assertEqual(source["victim_calls"], 3)
        self.assertEqual(source["attacker_calls"], 1)

    def test_paired_bootstrap_uses_common_sources(self) -> None:
        left = [
            {"source_key": "m", "group": "KB_Member", "score": 1.0},
            {"source_key": "n", "group": "True_Non_Member", "score": 0.0},
            {"source_key": "left-only", "group": "KB_Member", "score": 1.0},
        ]
        right = [
            {"source_key": "m", "group": "KB_Member", "score": 0.5},
            {"source_key": "n", "group": "True_Non_Member", "score": 0.5},
        ]
        result = paired_bootstrap_metric_delta(
            left, right, left_score_key="score", right_score_key="score", n_bootstrap=20,
        )
        self.assertEqual(result["common_sources"], 2)
        self.assertEqual(result["estimate"]["AUC"], 0.5)


if __name__ == "__main__":
    unittest.main()
