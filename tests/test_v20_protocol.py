from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.evaluation.retrieval_gate import apply_dense_gate, rank_passing_chunk_configs
from src.llm.generator_registry import (
    load_generator_registry,
    resolve_frozen_generator,
)
from src.llm.openai_compatible import OpenAICompatibleChatClient
from src.rag.index_builder import chunk_for_rag_tokens
from src.rag.retriever import HybridRagRetriever, RetrievedChunk
from src.rag.runner import run_rag_and_llm_only
from src.utils.io import load_yaml, write_jsonl
from src.utils.run_context import P0_PROTOCOL, experiment_scoped_dir


class FakeTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        del add_special_tokens
        return [ord(char) for char in text]

    def decode(
        self,
        token_ids: list[int],
        skip_special_tokens: bool = True,
        clean_up_tokenization_spaces: bool = False,
    ) -> str:
        del skip_special_tokens, clean_up_tokenization_spaces
        return "".join(chr(value) for value in token_ids)


class FakeRetriever:
    def __init__(self, backend: str, rows: list[RetrievedChunk]):
        self.retriever_backend = backend
        self.rows = rows
        self.docstore = []
        self.manifest = {
            "retriever_backend": backend,
            "retriever_id": "bge" if backend == "dense" else "bm25",
            "docstore_hash": "same",
            "embedding_revision": "snapshot" if backend == "dense" else None,
        }

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        del query
        return self.rows[:top_k]


class FakeReranker:
    def predict(self, pairs: list[list[str]]) -> np.ndarray:
        return np.asarray(
            [2.0 if "shared" in text else 1.0 for _, text in pairs],
            dtype=float,
        )


class V20ProtocolTests(unittest.TestCase):
    def test_protocol_retires_minilm_and_uses_bge(self) -> None:
        self.assertEqual(P0_PROTOCOL["protocol_version"], "pcv-mia-v20")
        self.assertEqual(P0_PROTOCOL["dense_retriever_model"], "BAAI/bge-base-en-v1.5")
        self.assertEqual(P0_PROTOCOL["primary_generator_family"], "llama")
        self.assertEqual(
            P0_PROTOCOL["primary_generator_model"],
            "meta/llama-3.1-70b-instruct",
        )
        self.assertNotIn("MiniLM", P0_PROTOCOL["dense_retriever_model"])

    def test_primary_pilot_call_budget_matches_declared_systems(self) -> None:
        plan = load_yaml(Path("configs/experiment_plan_v20.yaml"))
        pilot = plan["primary_generator_pilot"]
        expected = (
            len(plan["retrieval_offline_gate"]["datasets"])
            * len(pilot["systems"])
            * int(pilot["queries_per_dataset"])
        )
        self.assertEqual(expected, 2_700)
        self.assertEqual(pilot["estimated_total_calls"], expected)

    def test_generator_registry_freezes_llama_and_rejects_drift(self) -> None:
        registry = load_generator_registry()
        identity = resolve_frozen_generator(
            registry,
            family="llama",
            concrete_model="meta/llama-3.1-70b-instruct",
            provider="openai_compatible",
        )
        self.assertEqual(identity.generator_family, "llama")
        self.assertEqual(identity.concrete_model, "meta/llama-3.1-70b-instruct")
        with self.assertRaisesRegex(RuntimeError, "Generator drift"):
            resolve_frozen_generator(
                registry,
                family="llama",
                concrete_model="meta/llama-3.3-70b-instruct",
                provider="openai_compatible",
            )
        with self.assertRaisesRegex(RuntimeError, "pending"):
            resolve_frozen_generator(
                registry,
                family="qwen",
                concrete_model="qwen3",
                provider="openai_compatible",
            )
        with self.assertRaisesRegex(RuntimeError, "pending"):
            resolve_frozen_generator(
                registry,
                family="gemini",
                concrete_model="gemini-2.0-flash",
                provider="openai_compatible",
            )

    def test_experiment_path_contains_family_model_and_retriever(self) -> None:
        path = experiment_scoped_dir(
            "artifacts/v20/scores",
            "enron",
            generator_family="llama",
            concrete_model="meta/llama-3.1-70b-instruct",
            retriever_id="BAAI/bge-base-en-v1.5",
        )
        self.assertEqual(
            path.parts[-4:],
            ("enron", "llama", "llama-3.1-70b-instruct", "bge-base-en-v1.5"),
        )

    def test_token_chunking_uses_exact_token_windows(self) -> None:
        chunks = chunk_for_rag_tokens(
            "abcdefghij",
            FakeTokenizer(),
            chunk_size=4,
            chunk_overlap=1,
        )
        self.assertEqual(chunks, ["abcd", "defg", "ghij"])

    def test_hybrid_uses_rrf_then_reranker_and_preserves_stage_scores(self) -> None:
        shared = RetrievedChunk("c-shared", "d-shared", "shared evidence", 0.7, {})
        dense_only = RetrievedChunk("c-dense", "d-dense", "dense evidence", 0.9, {})
        bm25_only = RetrievedChunk("c-bm25", "d-bm25", "sparse evidence", 4.0, {})
        dense = FakeRetriever("dense", [dense_only, shared])
        bm25 = FakeRetriever("bm25", [bm25_only, shared])
        with patch("src.rag.retriever.RagRetriever", side_effect=[dense, bm25]):
            hybrid = HybridRagRetriever(
                "dense",
                "bm25",
                reranker=FakeReranker(),
                final_top_k=2,
            )
        results = hybrid.retrieve("query", top_k=2)
        self.assertEqual(results[0].chunk_id, "c-shared")
        scores = results[0].metadata["retrieval_stage_scores"]
        self.assertEqual(scores["dense_rank"], 2)
        self.assertEqual(scores["bm25_rank"], 2)
        self.assertIn("rrf_score", scores)
        self.assertIn("reranker_score", scores)

    def test_offline_gate_and_tie_break_do_not_use_auc(self) -> None:
        metrics = {
            "target_doc_recall_at_5": 0.75,
            "target_doc_recall_at_10": 0.85,
            "zero_hit_source_rate": 0.04,
            "mrr": 0.6,
            "latency_ms_p95": 10.0,
        }
        gate = apply_dense_gate(
            metrics,
            {"wrong_group_chunks": 0, "forbidden_source_overlap": 0},
        )
        self.assertTrue(gate["passed"])
        ranked = rank_passing_chunk_configs(
            {
                "slow": {"enron": {**metrics, "gate": gate}},
                "fast": {
                    "enron": {
                        **metrics,
                        "latency_ms_p95": 5.0,
                        "gate": gate,
                    }
                },
            }
        )
        self.assertEqual(ranked[0]["chunk_config_id"], "fast")
        self.assertNotIn("auc", ranked[0])

    def test_openai_compatible_response_metadata_is_preserved(self) -> None:
        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="gemini-2.0-flash",
        )
        payload = (
            '{"id":"request-1","model":"gemini-2.0-flash",'
            '"system_fingerprint":"fp-1",'
            '"usage":{"prompt_tokens":12,"completion_tokens":3},'
            '"choices":[{"finish_reason":"stop",'
            '"message":{"content":"Consistent"}}]}'
        )
        with patch.object(client, "_urlopen_with_retries", return_value=payload):
            result = client.chat_with_metadata("query")
        self.assertEqual(result.content, "Consistent")
        self.assertEqual(result.provider_model_id, "gemini-2.0-flash")
        self.assertEqual(result.provider_request_id, "request-1")
        self.assertEqual(result.system_fingerprint, "fp-1")
        self.assertEqual(result.input_tokens, 12)
        self.assertEqual(result.output_tokens, 3)
        self.assertEqual(result.finish_reason, "stop")
        self.assertIsNotNone(result.latency_ms)
        self.assertEqual(result.retry_count, 0)
        self.assertTrue(result.called_at)

    def test_openai_compatible_rejects_api_error_payload_and_error_content(self) -> None:
        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="gemini-2.0-flash",
        )
        payloads = (
            '{"error":{"code":401,"status":"UNAUTHENTICATED",'
            '"message":"API key not valid"}}',
            '{"id":"request-1","model":"gemini-2.0-flash",'
            '"choices":[{"message":{"content":"HTTP 429: rate limit exceeded"}}]}',
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with patch.object(client, "_urlopen_with_retries", return_value=payload):
                    with self.assertRaisesRegex(RuntimeError, "API error response"):
                        client.chat_with_metadata("query")

    def test_streaming_metadata_uses_provider_model_not_requested_model(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return iter([
                    (
                        b'data: {"id":"request-stream","model":"gemini-2.0-flash-001",'
                        b'"system_fingerprint":"fp-stream",'
                        b'"choices":[{"delta":{"content":"Consistent"}}]}\n'
                    ),
                    b"data: [DONE]\n",
                ])

        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="gemini-2.0-flash",
            stream=True,
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = client.chat_with_metadata("query")
        self.assertEqual(result.content, "Consistent")
        self.assertEqual(result.provider_model_id, "gemini-2.0-flash-001")
        self.assertEqual(result.provider_request_id, "request-stream")
        self.assertEqual(result.system_fingerprint, "fp-stream")

    def test_resume_rejects_generator_version_drift_before_calls(self) -> None:
        class Client:
            def generate(self, prompt: str, **kwargs) -> str:
                del prompt, kwargs
                return "Consistent"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queries = root / "queries.jsonl"
            benchmark = root / "benchmark.jsonl"
            output = root / "llm.jsonl"
            write_jsonl(
                [{
                    "query_id": "q1",
                    "audit_id": "a1",
                    "group": "KB_Member",
                    "query": "check",
                    "accepted": True,
                }],
                queries,
            )
            write_jsonl(
                [{
                    "audit_id": "a1",
                    "doc_id": "d1",
                    "source_key": "s1",
                }],
                benchmark,
            )
            common = {
                "dataset": "toy",
                "queries_path": queries,
                "benchmark_path": benchmark,
                "index_dir": root / "unused",
                "rag_output_path": root / "rag.jsonl",
                "llm_output_path": output,
                "client": Client(),
                "run_rag": False,
                "run_llm_only": True,
                "generator_family": "gemini",
                "concrete_model": "gemini-2.0-flash",
                "generator_id": "gemini-2.0-flash",
                "code_commit": "commit-a",
            }
            run_rag_and_llm_only(
                **common,
                generator_version="gemini-2.0-flash",
                resume=False,
                force=True,
            )
            with self.assertRaisesRegex(RuntimeError, "Experiment identity mismatch"):
                run_rag_and_llm_only(
                    **common,
                    generator_version="gemini-2.0-flash-002",
                    resume=True,
                    force=False,
                )


if __name__ == "__main__":
    unittest.main()
