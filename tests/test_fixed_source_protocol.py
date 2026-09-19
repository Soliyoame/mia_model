from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.prepare.splitter import GROUP_FILENAMES, split_dataset_pcv_mia
from src.query_generation.stealth_filter import (
    _score_query_batch_with_embedder,
    _score_query_with_embedder,
    filter_stealth_queries,
    select_fixed_pairs_per_source,
)
from src.rag.runner import validate_fixed_query_budget
from src.utils.io import read_jsonl, write_json, write_jsonl


def _query_row(source: str, pair_index: int, claim_type: str, quality: float = 0.8) -> dict:
    return {
        "query_id": f"q-{source}-{pair_index}-{claim_type}",
        "pair_id": f"p-{source}-{pair_index}",
        "query_type": "compressed_verification",
        "source_key": source,
        "source_id": source,
        "group": "KB_Member",
        "claim_type": claim_type,
        "query": f"query {source} {pair_index} {claim_type}",
        "quality_weight": quality,
        "naturalness_score": 0.9,
        "query_doc_similarity": 0.5,
        "accepted": True,
    }


class SourceLevelSplitTests(unittest.TestCase):
    @staticmethod
    def _source_rows(source_count: int = 4) -> list[dict]:
        return [
            {
                "doc_id": f"d-{source_index}",
                "source_id": f"source-{source_index}",
                "source_path": f"corpus/source-{source_index}.txt",
                "text": f"source {source_index}",
                "text_hash": f"hash-{source_index}",
            }
            for source_index in range(source_count)
        ]

    def test_resume_accepts_zero_target_file_and_rejects_protocol_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = root / "processed.jsonl"
            write_jsonl(self._source_rows(), processed)
            kwargs = {
                "dataset": "toy",
                "processed_path": processed,
                "output_dir": root / "splits",
                "kb_member": 1,
                "true_non_member": 1,
                "spoof_seed": 0,
                "reserve": 1,
                "source_exclusive": True,
                "target_unit": "sources",
                "membership_unit": "document",
                "split_scale": "formal",
                "seed": 42,
            }
            split_dataset_pcv_mia(**kwargs, resume=False, force=True)
            self.assertEqual((root / "splits" / "spoof_seed.jsonl").stat().st_size, 0)

            resumed = split_dataset_pcv_mia(**kwargs, resume=True, force=False)
            self.assertTrue(resumed["skipped_existing"])
            with self.assertRaisesRegex(RuntimeError, "protocol does not match"):
                split_dataset_pcv_mia(
                    **{**kwargs, "split_scale": "pilot"},
                    resume=True,
                    force=False,
                )
            with self.assertRaisesRegex(RuntimeError, "protocol does not match"):
                split_dataset_pcv_mia(
                    **{**kwargs, "per_source_cap": 3},
                    resume=True,
                    force=False,
                )

    def test_formal_targets_count_complete_sources_not_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = root / "processed.jsonl"
            rows = []
            for source_index in range(8):
                for chunk_index in range(3):
                    rows.append(
                        {
                            "doc_id": f"d-{source_index}-{chunk_index}",
                            "source_id": f"source-{source_index}",
                            "source_path": f"corpus/source-{source_index}.txt",
                            "text": f"source {source_index} chunk {chunk_index}",
                            "text_hash": f"hash-{source_index}-{chunk_index}",
                        }
                    )
            write_jsonl(rows, processed)

            manifest = split_dataset_pcv_mia(
                "toy",
                processed,
                root / "splits",
                kb_member=2,
                true_non_member=2,
                spoof_seed=2,
                reserve=2,
                source_exclusive=True,
                target_unit="sources",
                seed=11,
                resume=False,
                force=True,
            )

            self.assertEqual(manifest["target_unit"], "sources")
            self.assertEqual(set(manifest["source_counts"].values()), {2})
            self.assertEqual(set(manifest["counts"].values()), {6})
            for filename in GROUP_FILENAMES.values():
                group_rows = list(read_jsonl(root / "splits" / filename))
                counts: dict[str, int] = {}
                for row in group_rows:
                    source = str(row["metadata"]["source_key"])
                    counts[source] = counts.get(source, 0) + 1
                self.assertEqual(set(counts.values()), {3})

    def test_source_deduplication_drops_whole_conflicting_membership_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = root / "processed.jsonl"
            rows = [
                {"doc_id": "a1", "source_id": "a", "source_path": "p", "text": "shared", "text_hash": "shared"},
                {"doc_id": "a2", "source_id": "a", "source_path": "p", "text": "a-only", "text_hash": "a-only"},
                {"doc_id": "b1", "source_id": "b", "source_path": "p", "text": "shared", "text_hash": "shared"},
                {"doc_id": "b2", "source_id": "b", "source_path": "p", "text": "b-only", "text_hash": "b-only"},
                {"doc_id": "c1", "source_id": "c", "source_path": "p", "text": "c-one", "text_hash": "c-one"},
                {"doc_id": "c2", "source_id": "c", "source_path": "p", "text": "c-two", "text_hash": "c-two"},
            ]
            write_jsonl(rows, processed)
            manifest = split_dataset_pcv_mia(
                "toy",
                processed,
                root / "splits",
                kb_member=1,
                true_non_member=1,
                spoof_seed=0,
                reserve=0,
                target_unit="sources",
                force=True,
            )
            output_rows = []
            for filename in GROUP_FILENAMES.values():
                output_rows.extend(read_jsonl(root / "splits" / filename))
            self.assertEqual({row["source_id"] for row in output_rows}, {"a", "c"})
            self.assertEqual(len(output_rows), 4)
            self.assertEqual(
                manifest["deduplication"]["dropped_cross_source_duplicates"],
                1,
            )


class SourceEligibilityTests(unittest.TestCase):
    def test_claim_whitelist_runs_before_random_group_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = root / "processed.jsonl"
            write_jsonl(
                [
                    {
                        "doc_id": f"doc-{index}",
                        "source_id": f"source-{index}",
                        "source_path": f"source-{index}.txt",
                        "text": f"unique text {index}",
                        "text_hash": f"hash-{index}",
                        "metadata": {"entity_count": 1},
                    }
                    for index in range(5)
                ],
                processed,
            )
            snapshot = {"whitelist_hash": "frozen", "minimum_valid_claims": 3}
            manifest = split_dataset_pcv_mia(
                dataset="enron",
                processed_path=processed,
                output_dir=root / "splits",
                kb_member=1,
                true_non_member=1,
                spoof_seed=0,
                reserve=1,
                target_unit="sources",
                membership_unit="complete_email",
                eligible_source_keys={
                    "source-0.txt::source-0",
                    "source-3.txt::source-3",
                    "source-4.txt::source-4",
                },
                claim_eligibility_snapshot=snapshot,
                force=True,
            )

            selected = {
                row["source_id"]
                for filename in GROUP_FILENAMES.values()
                for row in read_jsonl(root / "splits" / filename)
            }
            self.assertEqual(selected, {"source-0", "source-3", "source-4"})
            self.assertEqual(manifest["claim_eligibility"], snapshot)
            self.assertEqual(manifest["source_eligibility"]["sources_after_claim_whitelist"], 3)

    def test_source_entity_gate_runs_before_random_group_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = root / "processed.jsonl"
            write_jsonl(
                [
                    {
                        "doc_id": f"doc-{index}",
                        "source_id": f"source-{index}",
                        "source_path": f"source-{index}.txt",
                        "text": f"unique text {index}",
                        "text_hash": f"hash-{index}",
                        "metadata": {"entity_count": index + 1},
                    }
                    for index in range(5)
                ],
                processed,
            )
            manifest = split_dataset_pcv_mia(
                dataset="enron",
                processed_path=processed,
                output_dir=root / "splits",
                kb_member=1,
                true_non_member=1,
                spoof_seed=0,
                reserve=1,
                target_unit="sources",
                membership_unit="complete_email",
                min_entities_per_source=3,
                force=True,
            )

            selected = {
                row["source_id"]
                for filename in GROUP_FILENAMES.values()
                for row in read_jsonl(root / "splits" / filename)
            }
            self.assertEqual(selected, {"source-2", "source-3", "source-4"})
            self.assertEqual(manifest["source_eligibility"]["sources_before"], 5)
            self.assertEqual(manifest["source_eligibility"]["sources_eligible"], 3)
            self.assertEqual(manifest["source_eligibility"]["sources_excluded"], 2)


class FixedBudgetTests(unittest.TestCase):
    def test_batched_stealth_scores_match_single_row_scoring(self) -> None:
        class FakeEmbedder:
            def __init__(self) -> None:
                self.call_sizes: list[int] = []

            def encode(self, texts: list[str]) -> np.ndarray:
                self.call_sizes.append(len(texts))
                return np.asarray(
                    [
                        [float(len(text) + 1), float(sum(map(ord, text)) % 97 + 1)]
                        for text in texts
                    ],
                    dtype="float32",
                )

        pairs = [
            ("Please check this value: alpha.", "The source states alpha."),
            ("Please check this value: beta.", "The source states beta."),
            ("Please check this value: gamma.", "The source states gamma."),
        ]
        batch_embedder = FakeEmbedder()
        single_embedder = FakeEmbedder()
        batched = _score_query_batch_with_embedder(pairs, batch_embedder)
        singles = [
            _score_query_with_embedder(query, reference, single_embedder)
            for query, reference in pairs
        ]

        self.assertEqual(batch_embedder.call_sizes, [6])
        self.assertEqual(single_embedder.call_sizes, [2, 2, 2])
        for batch_score, single_score in zip(batched, singles, strict=True):
            self.assertEqual(batch_score["naturalness_score"], single_score["naturalness_score"])
            self.assertEqual(batch_score["context_probe_score"], single_score["context_probe_score"])
            self.assertEqual(batch_score["prompt_injection_score"], single_score["prompt_injection_score"])
            self.assertEqual(batch_score["dangerous_hits"], single_score["dangerous_hits"])
            self.assertAlmostEqual(
                batch_score["query_doc_similarity"],
                single_score["query_doc_similarity"],
                places=7,
            )

    def test_stealth_resume_rejects_old_pair_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "accepted.jsonl"
            write_jsonl([_query_row("s1", 0, "true")], output)
            write_json(
                {"fixed_budget": {"enabled": True, "pairs_per_source": 3}},
                output.with_suffix(".manifest.json"),
            )
            with self.assertRaisesRegex(RuntimeError, "fixed source budget"):
                filter_stealth_queries(
                    root / "queries.jsonl",
                    output,
                    pairs_per_source=4,
                    resume=True,
                )

    def test_stealth_resume_rejects_plan_without_query_text_uniqueness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "accepted.jsonl"
            write_jsonl([_query_row("s1", 0, "true")], output)
            write_json(
                {"fixed_budget": {"enabled": True, "pairs_per_source": 4}},
                output.with_suffix(".manifest.json"),
            )
            with self.assertRaisesRegex(RuntimeError, "unique query text"):
                filter_stealth_queries(
                    root / "queries.jsonl",
                    output,
                    pairs_per_source=4,
                    resume=True,
                )

    def test_stealth_filter_releases_one_shot_embedding_runtime(
        self,
    ) -> None:
        class FakeEmbedder:
            def __init__(self) -> None:
                self.closed = False

            def encode(self, texts: list[str]) -> np.ndarray:
                return np.asarray(
                    [[float(index + 1), 1.0] for index, _ in enumerate(texts)],
                    dtype="float32",
                )

            def close(self) -> None:
                self.closed = True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queries = root / "queries.jsonl"
            output = root / "accepted.jsonl"
            write_jsonl(
                [
                    _query_row("s1", 0, claim_type)
                    for claim_type in ("true", "counterfactual")
                ],
                queries,
            )
            embedder = FakeEmbedder()
            with patch(
                "src.query_generation.stealth_filter.build_embedding_model",
                return_value=embedder,
            ):
                filter_stealth_queries(
                    queries,
                    output,
                    min_naturalness=0.0,
                    min_similarity=-1.0,
                    max_similarity=2.0,
                    resume=False,
                )
            self.assertTrue(embedder.closed)

    def test_selector_keeps_exactly_four_pairs_and_rejects_extras(self) -> None:
        rows = [
            _query_row("s1", pair_index, claim_type, quality=1.0 - pair_index / 10)
            for pair_index in range(6)
            for claim_type in ("true", "counterfactual")
        ]
        selected, rejected, stats = select_fixed_pairs_per_source(rows, [], 4)

        self.assertEqual(len(selected), 8)
        self.assertEqual(len(rejected), 4)
        self.assertEqual(stats["queries_per_source"], 8)
        self.assertEqual(stats["eligible_sources"], 1)
        self.assertEqual({row["fixed_budget_pair_rank"] for row in selected}, {1, 2, 3, 4})

    def test_selector_drops_source_with_fewer_than_four_pairs(self) -> None:
        rows = [
            _query_row("s1", pair_index, claim_type)
            for pair_index in range(3)
            for claim_type in ("true", "counterfactual")
        ]
        selected, rejected, stats = select_fixed_pairs_per_source(rows, [], 4)

        self.assertFalse(selected)
        self.assertEqual(len(rejected), 6)
        self.assertEqual(stats["insufficient_sources"], {"s1": 3})

    def test_selector_uses_backup_pairs_to_keep_query_texts_unique(self) -> None:
        rows = [
            _query_row("s1", pair_index, claim_type, quality=1.0 - pair_index / 10)
            for pair_index in range(5)
            for claim_type in ("true", "counterfactual")
        ]
        rows[2]["query"] = rows[0]["query"]
        rows[3]["query"] = rows[1]["query"]

        selected, _, stats = select_fixed_pairs_per_source(rows, [], 4)

        self.assertEqual(len(selected), 8)
        self.assertEqual(len({row["query"] for row in selected}), 8)
        self.assertNotIn("p-s1-1", {row["pair_id"] for row in selected})
        self.assertTrue(stats["query_text_uniqueness_enforced"])

    def test_runner_gate_rejects_duplicate_query_texts(self) -> None:
        rows = [
            _query_row("s1", pair_index, claim_type)
            for pair_index in range(4)
            for claim_type in ("true", "counterfactual")
        ]
        rows[-1]["query"] = rows[0]["query"]

        with self.assertRaisesRegex(RuntimeError, "duplicate_query_text"):
            validate_fixed_query_budget(rows, 4)

    def test_runner_gate_requires_exactly_eight_queries_per_source(self) -> None:
        valid_rows = [
            _query_row(source, pair_index, claim_type)
            for source in ("s1", "s2")
            for pair_index in range(4)
            for claim_type in ("true", "counterfactual")
        ]
        stats = validate_fixed_query_budget(valid_rows, 4)
        self.assertEqual(stats["source_count"], 2)
        self.assertEqual(stats["planned_queries"], 16)

        with self.assertRaises(RuntimeError):
            validate_fixed_query_budget(valid_rows[:-1], 4)

        with self.assertRaisesRegex(RuntimeError, "no_sources"):
            validate_fixed_query_budget([], 4)

        with self.assertRaisesRegex(RuntimeError, "missing_sources"):
            validate_fixed_query_budget(
                valid_rows,
                4,
                expected_source_keys={"s1", "s2", "s3"},
            )


if __name__ == "__main__":
    unittest.main()
