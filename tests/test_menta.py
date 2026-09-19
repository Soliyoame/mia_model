"""Network-free contract tests for the source-level adapted MEntA baseline."""

from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.baselines.menta import (
    MENTA_NLI_MODEL_ID,
    MENTA_NLI_REVISION,
    MENTA_PROTOCOL_VERSION,
    MENTA_QUERY_COUNT,
    MENTA_QUERY_PROMPT_VERSION,
    MENTA_REFUSAL_HYPOTHESES,
    MEntAQueryBundle,
    MEntARuntime,
    build_menta_query,
    is_entailment,
    load_menta_query_bundle,
    query_row_hash,
    split_atomic_claims,
    validate_menta_query_row,
    validate_nli_snapshot,
)
from src.baselines.victim_harness import Services, run_one_baseline
from src.utils.hash import sha256_file, sha256_obj, sha256_text
from src.utils.io import read_jsonl, write_json, write_jsonl


def _sibling_identity(model: str = "pcv-qwen3-4b:q4km-8k") -> dict:
    identity = {
        "profile_name": "ollama_qwen3_4b",
        "provider": "openai_compatible",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": model,
        "model_version": "ollama:test-digest",
        "request_interval_seconds": 0,
        "requests_per_minute": 0,
        "extra_body": {"reasoning_effort": "none", "seed": 42},
    }
    return {**identity, "profile_hash": sha256_obj(identity)}


def _query_row(
    *,
    dataset: str = "enron",
    doc_id: str = "doc-c0001",
    source_key: str = "source-1",
    group: str = "KB_Member",
    text: str = "Candidate text.",
) -> dict:
    summary = "a concise candidate topic"
    questions = [f"What distinct fact number {index} is described?" for index in range(5)]
    sibling_identity_hash = _sibling_identity()["profile_hash"]
    return {
        "protocol_version": MENTA_PROTOCOL_VERSION,
        "query_prompt_version": MENTA_QUERY_PROMPT_VERSION,
        "dataset": dataset,
        "doc_id": doc_id,
        "source_id": source_key,
        "source_key": source_key,
        "group": group,
        "representative_text_hash": sha256_text(text),
        "summary": summary,
        "questions": questions,
        "queries": [build_menta_query(summary, question) for question in questions],
        "sibling_identity_hash": sibling_identity_hash,
    }


def _write_query_bundle(
    root: Path,
    rows: list[dict],
    *,
    representative_hash: str = "representative-hash",
    sibling_profile: dict | None = None,
) -> Path:
    sibling_profile = dict(sibling_profile or _sibling_identity())
    sibling_identity_hash = str(sibling_profile["profile_hash"])
    query_path = root / "enron_menta_queries.jsonl"
    frozen_rows = []
    for row in rows:
        frozen = dict(row)
        frozen["row_hash"] = query_row_hash(frozen)
        frozen_rows.append(frozen)
    write_jsonl(frozen_rows, query_path)
    write_json(
        {
            "protocol_version": MENTA_PROTOCOL_VERSION,
            "query_prompt_version": MENTA_QUERY_PROMPT_VERSION,
            "dataset": "enron",
            "queries_per_source": MENTA_QUERY_COUNT,
            "source_count": len(frozen_rows),
            "representative_chunk_manifest_hash": representative_hash,
            "sibling_profile": sibling_profile,
            "sibling_identity_hash": sibling_identity_hash,
            "row_binding_hash": sha256_obj(
                [
                    {
                        "doc_id": row["doc_id"],
                        "source_key": row["source_key"],
                        "row_hash": row["row_hash"],
                    }
                    for row in frozen_rows
                ]
            ),
            "output_sha256": sha256_file(query_path),
        },
        query_path.with_suffix(".manifest.json"),
    )
    return query_path


class QueryManifestTests(unittest.TestCase):
    def test_loads_exactly_five_unique_frozen_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_query_bundle(Path(tmp), [_query_row()])
            bundle = load_menta_query_bundle(
                path,
                dataset="enron",
                representative_manifest_hash="representative-hash",
            )
            self.assertEqual(len(bundle.rows_by_doc_id), 1)
            self.assertEqual(
                len(bundle.rows_by_doc_id["doc-c0001"]["queries"]),
                5,
            )

    def test_rejects_duplicate_or_wrong_query_count(self) -> None:
        row = _query_row()
        row["questions"][4] = row["questions"][0]
        row["queries"] = [
            build_menta_query(row["summary"], question)
            for question in row["questions"]
        ]
        with self.assertRaisesRegex(RuntimeError, "unique"):
            validate_menta_query_row(row, "enron")

        row = _query_row()
        row["questions"] = row["questions"][:4]
        row["queries"] = row["queries"][:4]
        with self.assertRaisesRegex(RuntimeError, "exactly five"):
            validate_menta_query_row(row, "enron")

    def test_rejects_query_artifact_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_query_bundle(Path(tmp), [_query_row()])
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                load_menta_query_bundle(
                    path,
                    dataset="enron",
                    representative_manifest_hash="representative-hash",
                )

    def test_rejects_sibling_profile_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_query_bundle(Path(tmp), [_query_row()])
            manifest_path = path.with_suffix(".manifest.json")
            from src.utils.io import read_json

            manifest = read_json(manifest_path)
            manifest["sibling_profile"]["model"] = "drifted-model"
            write_json(manifest, manifest_path)
            with self.assertRaisesRegex(RuntimeError, "identity hash mismatch"):
                load_menta_query_bundle(
                    path,
                    dataset="enron",
                    representative_manifest_hash="representative-hash",
                )

    def test_rejects_row_protocol_and_prompt_version_drift(self) -> None:
        row = _query_row()
        row["protocol_version"] = "drift"
        with self.assertRaisesRegex(RuntimeError, "protocol version mismatch"):
            validate_menta_query_row(row, "enron")

        row = _query_row()
        row["query_prompt_version"] = "drift"
        with self.assertRaisesRegex(RuntimeError, "prompt version mismatch"):
            validate_menta_query_row(row, "enron")


class ClaimAndScoringTests(unittest.TestCase):
    def test_atomic_claim_split_handles_bullets_newlines_and_empty_text(self) -> None:
        self.assertEqual(split_atomic_claims(""), [])
        self.assertEqual(
            split_atomic_claims(
                "- First supported fact. Second fact?\n2. Third fact!"
            ),
            [
                "First supported fact.",
                "Second fact?",
                "Third fact!",
            ],
        )
        self.assertEqual(
            split_atomic_claims("First fact. second fact."),
            ["First fact.", "second fact."],
        )

    def test_entailment_requires_strict_argmax(self) -> None:
        self.assertTrue(
            is_entailment(
                {"entailment": 0.51, "neutral": 0.49, "contradiction": 0.0}
            )
        )
        self.assertFalse(
            is_entailment(
                {"entailment": 0.5, "neutral": 0.5, "contradiction": 0.0}
            )
        )


class _FakePredictor:
    def probabilities(self, pairs):
        rows = []
        for premise, hypothesis in pairs:
            if (
                "cannot answer" in premise.casefold()
                and hypothesis in MENTA_REFUSAL_HYPOTHESES
            ):
                rows.append(
                    {"entailment": 0.8, "neutral": 0.1, "contradiction": 0.1}
                )
            elif "supported" in hypothesis.casefold():
                rows.append(
                    {"entailment": 0.8, "neutral": 0.1, "contradiction": 0.1}
                )
            else:
                rows.append(
                    {"entailment": 0.1, "neutral": 0.8, "contradiction": 0.1}
                )
        return rows


class _FakeRetriever:
    def retrieve(self, query: str, top_k: int = 5):
        del query, top_k
        return [SimpleNamespace(text="retrieved context")]


class _FakeVictim:
    def __init__(self, answers: list[str] | None = None) -> None:
        self.answers = list(answers or [])
        self.prompts: list[str] = []

    def generate(self, prompt: str, **kwargs) -> str:
        del kwargs
        self.prompts.append(prompt)
        if self.answers:
            return self.answers.pop(0)
        return "A supported fact."


def _runtime_for_rows(rows: list[dict]) -> MEntARuntime:
    bundle = MEntAQueryBundle(
        dataset="enron",
        query_path=Path("queries.jsonl"),
        manifest_path=Path("queries.manifest.json"),
        rows_by_doc_id={str(row["doc_id"]): row for row in rows},
        manifest={},
        identity={"protocol_version": MENTA_PROTOCOL_VERSION},
    )
    return MEntARuntime(
        bundle=bundle,
        predictor=_FakePredictor(),
        nli_identity={"model_id": "fake"},
    )


class RuntimeTests(unittest.TestCase):
    def test_query_scores_are_mean_of_entailment_minus_refusal(self) -> None:
        text = "Candidate text."
        row = _query_row(text=text)
        runtime = _runtime_for_rows([row])
        victim = _FakeVictim(
            [
                "A supported fact.",
                "I cannot answer this question.",
                "An unrelated statement.",
                "Another supported fact.",
                "Another unrelated statement.",
            ]
        )
        services = Services(
            retriever=_FakeRetriever(),
            victim=victim,
            menta_runtime=runtime,
        )
        services.begin_scope(
            {
                "doc_id": row["doc_id"],
                "source_key": row["source_key"],
                "group": row["group"],
                "text": text,
            }
        )

        score = runtime.score_target(text, services)

        self.assertAlmostEqual(score, 0.2)
        self.assertEqual(services.scope_counts()[0], 5)
        diagnostics = services.scope_diagnostics()["menta"]
        self.assertEqual(diagnostics["query_scores"], [1, -1, 0, 1, 0])
        self.assertEqual(diagnostics["entailment_hits"], 2)
        self.assertEqual(diagnostics["refusal_hits"], 1)
        self.assertTrue(all("Topic summary:" in prompt for prompt in victim.prompts))

    def test_harness_records_exactly_five_calls_per_target_without_api(self) -> None:
        member_text = "Member candidate."
        nonmember_text = "Nonmember candidate."
        rows = [
            _query_row(text=member_text),
            _query_row(
                doc_id="doc-c0002",
                source_key="source-2",
                group="True_Non_Member",
                text=nonmember_text,
            ),
        ]
        runtime = _runtime_for_rows(rows)
        targets = [
            {
                "doc_id": rows[0]["doc_id"],
                "source_key": rows[0]["source_key"],
                "source_id": rows[0]["source_id"],
                "group": rows[0]["group"],
                "text": member_text,
            },
            {
                "doc_id": rows[1]["doc_id"],
                "source_key": rows[1]["source_key"],
                "source_id": rows[1]["source_id"],
                "group": rows[1]["group"],
                "text": nonmember_text,
            },
        ]
        runtime.validate_targets(targets)
        services = Services(
            retriever=_FakeRetriever(),
            victim=_FakeVictim(),
            menta_runtime=runtime,
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "menta_scores.jsonl"
            result = run_one_baseline(
                "MEntA",
                targets,
                services,
                output,
                max_workers=2,
            )
            scored_rows = list(read_jsonl(output))

        self.assertEqual(result["victim_calls"], 10)
        self.assertEqual([row["victim_calls"] for row in scored_rows], [5, 5])
        self.assertTrue(all(row["diagnostics"]["menta"] for row in scored_rows))

    def test_target_binding_rejects_doc_source_and_text_drift(self) -> None:
        row = _query_row(text="Frozen text.")
        runtime = _runtime_for_rows([row])
        with self.assertRaisesRegex(RuntimeError, "missing for target"):
            runtime.validate_targets(
                [
                    {
                        "doc_id": "different-doc",
                        "source_key": row["source_key"],
                        "group": row["group"],
                        "text": "Frozen text.",
                    }
                ]
            )
        with self.assertRaisesRegex(RuntimeError, "source binding mismatch"):
            runtime.validate_targets(
                [
                    {
                        "doc_id": row["doc_id"],
                        "source_key": "different-source",
                        "group": row["group"],
                        "text": "Frozen text.",
                    }
                ]
            )
        with self.assertRaisesRegex(RuntimeError, "text hash mismatch"):
            runtime.validate_targets(
                [
                    {
                        "doc_id": row["doc_id"],
                        "source_key": row["source_key"],
                        "group": row["group"],
                        "text": "Changed text.",
                    }
                ]
            )

    def test_formal_config_rejects_cpu_before_model_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_query_bundle(root, [_query_row()])
            config = {
                "query_manifest_dir": str(root),
                "queries_per_source": MENTA_QUERY_COUNT,
                "nli": {
                    "model_id": MENTA_NLI_MODEL_ID,
                    "revision": MENTA_NLI_REVISION,
                    "snapshot_dir": str(root / "snapshot"),
                    "local_files_only": True,
                    "device": "cpu",
                    "require_cuda": False,
                },
            }
            with self.assertRaisesRegex(RuntimeError, "require a CUDA device"):
                MEntARuntime.from_config(
                    dataset="enron",
                    config=config,
                    representative_manifest_hash="representative-hash",
                )


class SnapshotTests(unittest.TestCase):
    def test_snapshot_hash_verification_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            filenames = (
                "config.json",
                "model.safetensors",
                "spm.model",
                "tokenizer.json",
                "tokenizer_config.json",
            )
            for filename in filenames:
                (root / filename).write_bytes(f"content:{filename}".encode("ascii"))
            write_json(
                {
                    "repo_id": "tasksource/deberta-base-long-nli",
                    "revision": "04dcf11f844b07bc57015169fca2b7d6df8299d5",
                    "files": {
                        filename: {
                            "size": (root / filename).stat().st_size,
                            "sha256": sha256_file(root / filename),
                        }
                        for filename in filenames
                    },
                },
                root / "pcv_snapshot_manifest.json",
            )
            identity = validate_nli_snapshot(root)
            self.assertEqual(
                identity["revision"],
                "04dcf11f844b07bc57015169fca2b7d6df8299d5",
            )

            (root / "config.json").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "verification failed"):
                validate_nli_snapshot(root)

    def test_snapshot_manifest_rejects_extra_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            filenames = (
                "config.json",
                "model.safetensors",
                "spm.model",
                "tokenizer.json",
                "tokenizer_config.json",
            )
            for filename in filenames:
                (root / filename).write_bytes(f"content:{filename}".encode("ascii"))
            write_json(
                {
                    "repo_id": MENTA_NLI_MODEL_ID,
                    "revision": MENTA_NLI_REVISION,
                    "files": {
                        filename: {
                            "size": (root / filename).stat().st_size,
                            "sha256": sha256_file(root / filename),
                        }
                        for filename in filenames
                    },
                },
                root / "pcv_snapshot_manifest.json",
            )
            (root / "unexpected.bin").write_bytes(b"unexpected")
            with self.assertRaisesRegex(RuntimeError, "file list mismatch"):
                validate_nli_snapshot(root)

    def test_snapshot_manifest_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(
                {
                    "repo_id": "tasksource/deberta-base-long-nli",
                    "revision": "04dcf11f844b07bc57015169fca2b7d6df8299d5",
                    "files": {
                        "../model.safetensors": {"size": 1, "sha256": "0" * 64},
                        "config.json": {"size": 1, "sha256": "0" * 64},
                        "model.safetensors": {"size": 1, "sha256": "0" * 64},
                        "spm.model": {"size": 1, "sha256": "0" * 64},
                        "tokenizer.json": {"size": 1, "sha256": "0" * 64},
                        "tokenizer_config.json": {"size": 1, "sha256": "0" * 64},
                    },
                },
                root / "pcv_snapshot_manifest.json",
            )
            with self.assertRaisesRegex(RuntimeError, "Unsafe"):
                validate_nli_snapshot(root)


class ResumeIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        runner_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "12_run_baselines.py"
        )
        cls.assert_resume_identity = staticmethod(
            runpy.run_path(str(runner_path))["_assert_baseline_resume_identity"]
        )
        prepare_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "27_prepare_menta_inputs.py"
        )
        prepare_namespace = runpy.run_path(str(prepare_path))
        cls.load_partial_rows = staticmethod(prepare_namespace["_load_partial_rows"])
        cls.validate_sibling_response = staticmethod(
            prepare_namespace["_validate_sibling_response"]
        )
        cls.resolve_run_mode = staticmethod(prepare_namespace["_resolve_run_mode"])
        cls.nearest_rank_percentile = staticmethod(
            prepare_namespace["_nearest_rank_percentile"]
        )

    def test_query_nli_and_protocol_identity_drift_refuse_resume(self) -> None:
        existing = {
            "dataset": "enron",
            "method_identities": {
                "MEntA": {
                    "protocol_hash": "protocol-a",
                    "query_sha256": "query-a",
                    "nli": {"revision": MENTA_NLI_REVISION},
                }
            },
        }
        drifts = (
            {
                **existing,
                "method_identities": {
                    "MEntA": {
                        **existing["method_identities"]["MEntA"],
                        "query_sha256": "query-b",
                    }
                },
            },
            {
                **existing,
                "method_identities": {
                    "MEntA": {
                        **existing["method_identities"]["MEntA"],
                        "nli": {"revision": "revision-b"},
                    }
                },
            },
            {
                **existing,
                "method_identities": {
                    "MEntA": {
                        **existing["method_identities"]["MEntA"],
                        "protocol_hash": "protocol-b",
                    }
                },
            },
        )
        for current in drifts:
            with self.subTest(current=current):
                with self.assertRaisesRegex(RuntimeError, "resume refused"):
                    self.assert_resume_identity(existing, current)

    def test_partial_resume_rejects_sibling_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "partial.jsonl"
            row = _query_row()
            row["row_hash"] = query_row_hash(row)
            write_jsonl([row], output_path)
            targets = {
                row["doc_id"]: {
                    "doc_id": row["doc_id"],
                    "source_key": row["source_key"],
                    "group": row["group"],
                    "text": "Candidate text.",
                }
            }
            with self.assertRaisesRegex(RuntimeError, "sibling identity drift"):
                self.load_partial_rows(
                    output_path,
                    dataset="enron",
                    targets_by_doc_id=targets,
                    sibling_identity_hash=_sibling_identity("drifted-model")[
                        "profile_hash"
                    ],
                )

    def test_sibling_response_rejects_model_drift_and_thinking_leakage(self) -> None:
        content = (
            '{"summary":"topic","questions":'
            '["q1?","q2?","q3?","q4?","q5?"]}'
        )
        with self.assertRaisesRegex(RuntimeError, "provider_model_identity_drift"):
            self.validate_sibling_response(
                content,
                provider_model_id="cloud-model",
                expected_model_id="pcv-qwen3-4b:q4km-8k",
            )
        with self.assertRaisesRegex(RuntimeError, "leaked thinking content"):
            self.validate_sibling_response(
                f"<think>hidden</think>{content}",
                provider_model_id="pcv-qwen3-4b:q4km-8k",
                expected_model_id="pcv-qwen3-4b:q4km-8k",
            )

    def test_diagnostic_mode_requires_isolated_output_and_computes_p95(self) -> None:
        with self.assertRaisesRegex(ValueError, "isolated --output-dir"):
            self.resolve_run_mode(
                configured_output_dir="formal",
                output_dir=None,
                max_targets=10,
                max_p95_seconds=30,
            )
        path, mode = self.resolve_run_mode(
            configured_output_dir="formal",
            output_dir="artifacts/v20/local_sibling_gate",
            max_targets=10,
            max_p95_seconds=30,
        )
        self.assertEqual(mode, "diagnostic")
        self.assertTrue(str(path).endswith("artifacts\\v20\\local_sibling_gate"))
        self.assertEqual(
            self.nearest_rank_percentile([1, 2, 3, 4, 100], 0.95),
            100,
        )


if __name__ == "__main__":
    unittest.main()
