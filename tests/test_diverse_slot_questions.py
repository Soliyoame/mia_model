from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.query_generation.diverse_slot_questions import (
    Candidate,
    _static_candidate_reasons,
    generate_diverse_paired_queries_file,
    parse_generation_response,
    score_source_candidates,
    select_diverse_source_candidates,
    slotted_claim,
)
from src.query_generation.lexical_overlap import (
    diversity_statistics,
    lexical_copy_scores,
)
from src.query_generation.stealth_filter import filter_stealth_queries
from src.utils.hash import sha256_obj, sha256_text
from src.utils.io import read_jsonl, write_jsonl


class _EntailingNLI:
    def __init__(self) -> None:
        self.calls = 0
        self.last_batch_size = 0

    def probabilities(self, pairs):
        self.calls += 1
        self.last_batch_size = len(pairs)
        return [
            {"entailment": 0.96, "neutral": 0.03, "contradiction": 0.01}
            for _ in pairs
        ]


class _ConstantEmbedder:
    def __init__(self) -> None:
        self.closed = False
        self.calls = 0
        self.last_batch_size = 0

    def encode(self, texts):
        self.calls += 1
        self.last_batch_size = len(texts)
        return np.asarray([[1.0, 0.0] for _ in texts], dtype="float32")

    def close(self) -> None:
        self.closed = True


def _pairs() -> list[dict]:
    return [
        {
            "pair_id": "p1",
            "fact_id": "f1",
            "audit_id": "a1",
            "source_key": "s1",
            "source_id": "s1",
            "doc_id": "d1",
            "dataset": "toy",
            "group": "KB_Member",
            "true_claim": "The reported investment in FHLBB stock was $24 million as of December 31, 2020.",
            "counterfactual_claim": "The reported investment in FHLBB stock was $31 million as of December 31, 2020.",
            "original_entity": "$24 million",
            "counterfactual_entity": "$31 million",
            "entity_type": "MONEY",
            "perturbation_level": "light",
        },
        {
            "pair_id": "p2",
            "fact_id": "f2",
            "audit_id": "a2",
            "source_key": "s1",
            "source_id": "s1",
            "doc_id": "d1",
            "dataset": "toy",
            "group": "KB_Member",
            "true_claim": "Arcosa, Inc. is headquartered in Dallas.",
            "counterfactual_claim": "Arcosa, Inc. is headquartered in Austin.",
            "original_entity": "Dallas",
            "counterfactual_entity": "Austin",
            "entity_type": "LOCATION",
            "perturbation_level": "light",
        },
        {
            "pair_id": "p3",
            "fact_id": "f3",
            "audit_id": "a3",
            "source_key": "s1",
            "source_id": "s1",
            "doc_id": "d1",
            "dataset": "toy",
            "group": "KB_Member",
            "true_claim": "The agreement expires on June 30, 2025.",
            "counterfactual_claim": "The agreement expires on July 31, 2025.",
            "original_entity": "June 30, 2025",
            "counterfactual_entity": "July 31, 2025",
            "entity_type": "DATE",
            "perturbation_level": "light",
        },
    ]


def _candidate_map() -> dict[str, list[Candidate]]:
    rows = {
        "p1": Candidate(
            "p1",
            "Was the reported investment in FHLBB stock {ENTITY} as of December 31, 2020?",
            "The reported investment in FHLBB stock was {ENTITY} as of December 31, 2020.",
            ("FHLBB stock", "December 31, 2020"),
        ),
        "p2": Candidate(
            "p2",
            "Did Arcosa, Inc. report that it is headquartered in {ENTITY}?",
            "Arcosa, Inc. is headquartered in {ENTITY}.",
            ("Arcosa", "headquartered"),
        ),
        "p3": Candidate(
            "p3",
            "Can it be confirmed that the agreement expires on {ENTITY}?",
            "The agreement expires on {ENTITY}.",
            ("agreement", "expires"),
        ),
    }
    return {pair_id: [candidate, candidate, candidate] for pair_id, candidate in rows.items()}


def _response_json() -> str:
    candidates = _candidate_map()
    return json.dumps(
        {
            "pairs": [
                {
                    "pair_id": pair_id,
                    "candidates": [
                        {
                            "question_template": candidate.question_template,
                            "proposition_template": candidate.proposition_template,
                            "anchors": list(candidate.anchors),
                        }
                        for candidate in rows
                    ],
                }
                for pair_id, rows in candidates.items()
            ]
        }
    )


class DiverseSlotQuestionTests(unittest.TestCase):
    def test_slotted_claim_and_pair_selection_preserve_one_slot(self) -> None:
        pairs = _pairs()
        self.assertEqual(slotted_claim(pairs[0]).count("{ENTITY}"), 1)
        source_text = " ".join(pair["true_claim"] for pair in pairs)
        nli = _EntailingNLI()
        embedder = _ConstantEmbedder()
        scored, failures = score_source_candidates(
            pairs,
            _candidate_map(),
            source_text=source_text,
            nli_predictor=nli,
            embedder=embedder,
            max_five_gram_containment=1.0,
            max_longest_common_token_run=99,
        )
        self.assertFalse(failures)
        self.assertEqual((nli.calls, nli.last_batch_size), (1, 18))
        self.assertEqual((embedder.calls, embedder.last_batch_size), (1, 54))
        selected, selection_failures = select_diverse_source_candidates(pairs, scored)
        self.assertFalse(selection_failures)
        self.assertEqual(len(selected or []), 3)
        self.assertEqual(
            {item.opening_auxiliary for item in selected or []},
            {"was", "did", "can"},
        )

    def test_structured_literal_hallucination_is_rejected(self) -> None:
        pair = _pairs()[1]
        candidate = Candidate(
            "p2",
            "Did Arcosa report in 2035 that its headquarters was located in {ENTITY}?",
            "Arcosa reported in 2035 that its headquarters was in {ENTITY}.",
            ("Arcosa", "headquarters"),
        )
        reasons = _static_candidate_reasons(candidate, pair)
        self.assertTrue(any(reason.startswith("introduced_structured_literal") for reason in reasons))

    def test_literal_copy_metrics_mask_target_entity(self) -> None:
        source = "The board reported that the FHLBB stock investment was $24 million as of December 31, 2020."
        copied = lexical_copy_scores(
            "The board reported that the FHLBB stock investment was {ENTITY} as of December 31, 2020?",
            source,
            entity_values=("$24 million", "$31 million"),
        )
        paraphrased = lexical_copy_scores(
            "Was {ENTITY} the year-end value assigned to the FHLBB stock investment?",
            source,
            entity_values=("$24 million", "$31 million"),
        )
        self.assertGreater(copied["five_gram_containment"], paraphrased["five_gram_containment"])
        self.assertGreater(copied["longest_common_token_run"], 8)

    def test_parse_requires_three_candidates_for_every_pair(self) -> None:
        parsed = parse_generation_response(_response_json(), ["p1", "p2", "p3"])
        self.assertEqual({key: len(value) for key, value in parsed.items()}, {"p1": 3, "p2": 3, "p3": 3})
        with self.assertRaisesRegex(ValueError, "exactly three"):
            parse_generation_response(
                json.dumps({"pairs": [{"pair_id": "p1", "candidates": []}]}),
                ["p1"],
            )

    def test_diversity_statistics_report_duplicate_and_opening_rates(self) -> None:
        stats = diversity_statistics(
            [
                "Was the value {ENTITY}?",
                "Was the value {ENTITY}?",
                "Did the filing report {ENTITY}?",
            ]
        )
        self.assertAlmostEqual(stats["duplicate_template_rate"], 1 / 3)
        self.assertGreater(stats["distinct_2"], 0.0)
        self.assertGreater(stats["distinct_3"], 0.0)

    def test_generation_retries_validation_failure_and_freezes_model_identity(self) -> None:
        class FakeChat:
            def __init__(self, model: str = "strong-model") -> None:
                self.model = model
                self.calls = 0

            def chat_with_metadata(self, *_args, **_kwargs):
                self.calls += 1
                return SimpleNamespace(
                    content="{}" if self.calls == 1 else _response_json(),
                    provider_model_id=self.model,
                    provider_request_id=f"r{self.calls}",
                    system_fingerprint="fp",
                    called_at="2026-08-01T00:00:00+00:00",
                    input_tokens=100,
                    output_tokens=100,
                    finish_reason="stop",
                    latency_ms=1.0,
                    retry_count=0,
                )

        profile_body = {"provider": "openai_compatible", "model": "strong-model"}
        profile = {**profile_body, "profile_hash": sha256_obj(profile_body)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims = root / "claims.jsonl"
            benchmark = root / "benchmark.jsonl"
            output = root / "queries.jsonl"
            pairs = _pairs()
            source_text = " ".join(pair["true_claim"] for pair in pairs)
            write_jsonl(pairs, claims)
            write_jsonl([{"source_key": "s1", "text": source_text}], benchmark)
            chat = FakeChat()
            manifest = generate_diverse_paired_queries_file(
                paired_claims_path=claims,
                benchmark_path=benchmark,
                output_path=output,
                chat_client=chat,
                sibling_profile_identity=profile,
                nli_predictor=_EntailingNLI(),
                nli_identity={"model": "fake-nli"},
                embedder=_ConstantEmbedder(),
                expected_provider_model_id="strong-model",
                correction_retries=1,
                max_five_gram_containment=1.0,
                max_longest_common_token_run=99,
                max_dataset_duplicate_template_rate=1.0,
                max_dataset_opening_4gram_rate=1.0,
            )
            self.assertEqual(chat.calls, 2)
            self.assertEqual(manifest["queries"], 6)
            rows = list(read_jsonl(output))
            self.assertEqual({row["query_type"] for row in rows}, {"diverse_slotted_verification"})
            self.assertTrue(all(row["true_claim"] in source_text for row in rows))
            self.assertEqual(
                {row["reference_chunk_hash"] for row in rows},
                {sha256_text(source_text)},
            )

    def test_generation_rejects_provider_model_drift(self) -> None:
        profile_body = {"provider": "openai_compatible", "model": "strong-model"}
        profile = {**profile_body, "profile_hash": sha256_obj(profile_body)}

        class DriftChat:
            def chat_with_metadata(self, *_args, **_kwargs):
                return SimpleNamespace(
                    content=_response_json(),
                    provider_model_id="different-model",
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims = root / "claims.jsonl"
            benchmark = root / "benchmark.jsonl"
            write_jsonl(_pairs(), claims)
            write_jsonl([{"source_key": "s1", "text": " ".join(p["true_claim"] for p in _pairs())}], benchmark)
            with self.assertRaisesRegex(RuntimeError, "identity drift"):
                generate_diverse_paired_queries_file(
                    paired_claims_path=claims,
                    benchmark_path=benchmark,
                    output_path=root / "queries.jsonl",
                    chat_client=DriftChat(),
                    sibling_profile_identity=profile,
                    nli_predictor=_EntailingNLI(),
                    nli_identity={"model": "fake-nli"},
                    embedder=_ConstantEmbedder(),
                    expected_provider_model_id="strong-model",
                    max_dataset_duplicate_template_rate=1.0,
                    max_dataset_opening_4gram_rate=1.0,
                )

    def test_step09_rejects_literal_copy_against_benchmark_chunk_as_a_pair(self) -> None:
        source_text = "The board reported that the FHLBB stock investment was $24 million as of December 31, 2020."
        template = "The board reported that the FHLBB stock investment was {ENTITY} as of December 31, 2020?"
        common = {
            "pair_id": "p1",
            "query_type": "diverse_slotted_verification",
            "source_key": "s1",
            "source_id": "s1",
            "group": "KB_Member",
            "true_claim": source_text,
            "original_entity": "$24 million",
            "paired_counterfactual_entity": "$31 million",
            "question_template": template,
        }
        rows = [
            {**common, "query_id": "q+", "claim_type": "true", "query": template.replace("{ENTITY}", "$24 million")},
            {**common, "query_id": "q-", "claim_type": "counterfactual", "query": template.replace("{ENTITY}", "$31 million")},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queries = root / "queries.jsonl"
            benchmark = root / "benchmark.jsonl"
            output = root / "accepted.jsonl"
            write_jsonl(rows, queries)
            write_jsonl([{"source_key": "s1", "text": source_text}], benchmark)
            embedder = _ConstantEmbedder()
            with patch(
                "src.query_generation.stealth_filter.build_embedding_model",
                return_value=embedder,
            ):
                manifest = filter_stealth_queries(
                    queries,
                    output,
                    benchmark_path=benchmark,
                    min_naturalness=0.0,
                    max_dataset_duplicate_template_rate=1.0,
                    max_dataset_opening_4gram_rate=1.0,
                    resume=False,
                )
            self.assertEqual(manifest["accepted"], 0)
            self.assertEqual(manifest["rejected"], 2)
            self.assertNotIn("too_similar", manifest["reject_reason_counts"])
            self.assertTrue(embedder.closed)

    def test_step09_fails_closed_instead_of_dropping_a_diverse_source(self) -> None:
        source_text = "The board reported that the FHLBB stock investment was $24 million as of December 31, 2020."
        template = "The board reported that the FHLBB stock investment was {ENTITY} as of December 31, 2020?"
        common = {
            "pair_id": "p1",
            "query_type": "diverse_slotted_verification",
            "source_key": "s1",
            "source_id": "s1",
            "group": "KB_Member",
            "true_claim": source_text,
            "original_entity": "$24 million",
            "paired_counterfactual_entity": "$31 million",
            "question_template": template,
        }
        rows = [
            {**common, "query_id": "q+", "claim_type": "true", "query": template.replace("{ENTITY}", "$24 million")},
            {**common, "query_id": "q-", "claim_type": "counterfactual", "query": template.replace("{ENTITY}", "$31 million")},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queries = root / "queries.jsonl"
            benchmark = root / "benchmark.jsonl"
            output = root / "accepted.jsonl"
            write_jsonl(rows, queries)
            write_jsonl([{"source_key": "s1", "text": source_text}], benchmark)
            with patch(
                "src.query_generation.stealth_filter.build_embedding_model",
                return_value=_ConstantEmbedder(),
            ):
                with self.assertRaisesRegex(RuntimeError, "failed closed"):
                    filter_stealth_queries(
                        queries,
                        output,
                        benchmark_path=benchmark,
                        pairs_per_source=1,
                        min_naturalness=0.0,
                        max_dataset_duplicate_template_rate=1.0,
                        max_dataset_opening_4gram_rate=1.0,
                        resume=False,
                    )
            self.assertFalse(output.exists())
            self.assertTrue(output.with_suffix(".manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
