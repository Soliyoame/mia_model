"""Network-free contracts for the PCV-MIA v21 protocol."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.baselines.ia_shadow import (
    IA_CANDIDATE_COUNT,
    load_source_bundle,
    normalize_shadow_answer,
    parse_exact_questions,
    prepare_source_bundle,
    write_source_bundle,
)
from src.baselines.victim_harness import BASELINES, Services, score_ia
from src.evaluation.metrics import tpr_at_fpr_details
from src.llm.huggingface_local import HuggingFaceLocalVictimClient
from src.llm.openai_compatible import ChatResult
from src.llm.response_validation import strict_response_metadata_error


def _result(content: str, model: str, request_id: str = "req-1") -> ChatResult:
    return ChatResult(
        content=content,
        provider_model_id=model,
        provider_request_id=request_id,
        system_fingerprint=None,
        called_at="2026-08-03T00:00:00+00:00",
        retry_count=0,
    )


class StrictResponseTests(unittest.TestCase):
    def test_rejects_api_text_identity_and_missing_audit_metadata(self) -> None:
        self.assertIn(
            "api_error_text",
            strict_response_metadata_error(
                "HTTP 429 rate limit exceeded",
                provider_model_id="gpt-5.6-luna",
                provider_request_id="req",
                called_at="now",
                expected_model_id="gpt-5.6-luna",
                configured_model_version="snapshot",
            )
            or "",
        )
        self.assertIn(
            "identity_drift",
            strict_response_metadata_error(
                "valid",
                provider_model_id="wrong",
                provider_request_id="req",
                called_at="now",
                expected_model_id="gpt-5.6-luna",
                configured_model_version="snapshot",
            )
            or "",
        )
        self.assertEqual(
            strict_response_metadata_error(
                "valid",
                provider_model_id="gpt-5.6-luna",
                provider_request_id=None,
                called_at="now",
                expected_model_id="gpt-5.6-luna",
                configured_model_version="snapshot",
            ),
            "provider_request_id_missing",
        )


class IAShadowTests(unittest.TestCase):
    def _bundle(self) -> dict:
        questions = [f"Is fact number {index} present?" for index in range(30)]
        luna_results = iter(
            [
                _result("topic summary", "gpt-5.6-luna", "luna-summary"),
                _result(
                    json.dumps({"questions": questions}),
                    "gpt-5.6-luna",
                    "luna-questions",
                ),
            ]
        )
        shadow_answers = iter(["I don't know", "Yes", "Yes", "Yes", "Yes", "Yes"])
        return prepare_source_bundle(
            {
                "doc_id": "doc-1",
                "source_key": "source-1",
                "group": "KB_Member",
                "text": "A candidate document with six verifiable facts.",
            },
            dataset="enron",
            query_call=lambda _prompt: next(luna_results),
            shadow_call=lambda _prompt: _result(
                next(shadow_answers),
                "pcv-qwen3-4b:q4km-8k",
                "shadow-request",
            ),
            relevance_scores=lambda qs, _text: [float(len(qs) - i) for i in range(len(qs))],
            query_model_id="gpt-5.6-luna",
            query_model_version="luna-snapshot",
            shadow_model_id="pcv-qwen3-4b:q4km-8k",
            shadow_model_version="ollama:39297c75a309",
        )

    def test_exact_question_and_answer_schema(self) -> None:
        questions = [f"Is fact {index} true?" for index in range(IA_CANDIDATE_COUNT)]
        self.assertEqual(
            len(parse_exact_questions(json.dumps({"questions": questions}))),
            30,
        )
        with self.assertRaisesRegex(ValueError, "exactly 30"):
            parse_exact_questions(json.dumps({"questions": questions[:29]}))
        self.assertEqual(normalize_shadow_answer("Yes."), "Yes")
        self.assertEqual(normalize_shadow_answer("I don't know"), "I don't know")
        self.assertIsNone(normalize_shadow_answer("Probably"))

    def test_freezes_five_non_idk_pairs_before_victim(self) -> None:
        bundle = self._bundle()
        self.assertEqual(bundle["status"], "ready")
        self.assertEqual(len(bundle["selected_pairs"]), 5)
        self.assertEqual(len(bundle["shadow_attempts"]), 6)
        self.assertEqual(bundle["call_ledger"]["luna_logical_calls"], 2)
        self.assertEqual(bundle["call_ledger"]["qwen_shadow_logical_calls"], 6)

    def test_runtime_uses_frozen_bundle_and_exactly_five_victim_calls(self) -> None:
        bundle = self._bundle()
        target = {
            "doc_id": "doc-1",
            "source_key": "source-1",
            "group": "KB_Member",
            "text": "A candidate document with six verifiable facts.",
        }

        class Retriever:
            embedder = None

            def retrieve(self, query: str, top_k: int = 5):
                del query, top_k
                return [SimpleNamespace(text="context")]

        class Victim:
            def generate(self, prompt: str, **kwargs) -> str:
                del prompt, kwargs
                return "Yes"

        with tempfile.TemporaryDirectory() as tmp:
            write_source_bundle(bundle, tmp)
            loaded = load_source_bundle(tmp, "enron", target)
            self.assertEqual(loaded["bundle_hash"], bundle["bundle_hash"])
            services = Services(
                retriever=Retriever(),
                victim=Victim(),
                dataset="enron",
                ia_shadow_manifest_dir=tmp,
            )
            services.begin_scope(target)
            self.assertEqual(score_ia(target["text"], services), 1.0)
            self.assertEqual(services.scope_counts(), (5, 0))
        self.assertFalse(BASELINES["IA"].needs_attacker)


class MetricAndLocalVictimTests(unittest.TestCase):
    def test_half_percent_fpr_is_empirical_and_not_interpolated(self) -> None:
        details = tpr_at_fpr_details(
            [
                {"TPR": 0.2, "FPR": 0.0, "threshold": 0.9, "false_positive_count": 0, "negative_count": 1000},
                {"TPR": 0.6, "FPR": 0.005, "threshold": 0.8, "false_positive_count": 5, "negative_count": 1000},
                {"TPR": 0.9, "FPR": 0.006, "threshold": 0.7, "false_positive_count": 6, "negative_count": 1000},
            ],
            0.005,
        )
        assert details is not None
        self.assertEqual(details["TPR"], 0.6)
        self.assertEqual(details["false_positive_count"], 5)
        self.assertFalse(details["interpolation"])

    def test_local_victim_rejects_cpu_quantization_and_unfrozen_revision(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "device=cuda"):
            HuggingFaceLocalVictimClient("model", "revision", device="cpu")
        with self.assertRaisesRegex(RuntimeError, "forbids quantization"):
            HuggingFaceLocalVictimClient("model", "revision", quantization="4bit")
        with self.assertRaisesRegex(ValueError, "revision"):
            HuggingFaceLocalVictimClient("model", "")


if __name__ == "__main__":
    unittest.main()
