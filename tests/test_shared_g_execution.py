"""逐槽门控、响应恢复与模型/检索身份的 mock 验证。"""

import copy
import yaml
from unittest.mock import Mock, patch
from types import SimpleNamespace

from test_shared_g_sources import FormalFixture
from src.shared_g.artifacts import read_rows, request_records, retry_local_write, write_rows
from src.shared_g.artifacts import ArtifactStore
from src.shared_g.config import load_config
from src.shared_g.sources import prepare
from src.shared_g.retrieval import rag_prompt, retrieve, validate_retrieval
from src.shared_g.scoring import gated_queries, source_scores
from src.shared_g.victim import run_victim, validate_cell_order
from src.utils.hash import sha256_file, sha256_obj, sha256_text


class ExecutionFixture(FormalFixture):
    def prepare_new_generator(self, *, dry_run: bool = False) -> dict:
        original = self.config.output.relative_to(self.root).as_posix()
        data = copy.deepcopy(self.config.data)
        data.update(experiment_id="fixed_inputs_llama", output_dir=original + "_llama")
        model = "llama-3.1-8b-instruct"
        data["runtime"].update(victim_profile="llama31_8b_server", concrete_model=model, generator_version=model)
        data["answer_policy"].pop("response_adjudications", None)
        data["source_selection"]["unused_preparations"] = []
        data["reused_inputs"] = {"source_dir": original,
                                 "retrieval_dirs": {dataset: original for dataset in self.config.datasets}}
        self.config_path = self.root / "llama.yaml"
        self.config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self.config = load_config(self.config_path, self.root)
        self.store = ArtifactStore(self.config)
        self.profiles["victim"] = {**self.profiles["victim"], "model": model, "model_version": model}
        return prepare(self.config, self.store, dry_run)

    def install_retrieval(self, dataset: str) -> None:
        member = next(r for r in read_rows(self.store.path("index_manifest.jsonl")) if r["dataset"] == dataset)
        chunks = [{"chunk_id": f"{member['source_key']}_c{i}", "source_key": member["source_key"],
                   "source_hash": member["source_hash"], "text": f"Reference chunk {i}", "score": 1.0} for i in range(5)]
        rows = []
        for query in [q for q in read_rows(self.store.path("query_plan.jsonl")) if q["dataset"] == dataset]:
            context, prompt = rag_prompt(self.config, query, chunks)
            row = {"query_id": query["query_id"], "dataset": dataset,
                   "query_plan_sha256": sha256_file(self.store.path("query_plan.jsonl")),
                   "index_identity": self.store.index_identity(dataset), "retriever": self.config.data["runtime"]["retrieval"],
                   "retrieved_chunks": chunks, "context_sha256": sha256_text(context), "prompt_sha256": sha256_text(prompt)}
            row["record_sha256"] = sha256_obj(row)
            rows.append(row)
        write_rows(self.store.path("retrieval.jsonl", dataset), rows)

    def victim_client(self) -> Mock:
        answers = {q["question"]: q["answer"] for q in read_rows(self.store.path("query_plan.jsonl"))}
        client = Mock()
        client.generate_with_metadata.side_effect = lambda prompt, **kwargs: self.result(
            answers[prompt.split("User request:\n", 1)[1]], "victim")
        return client

    def complete_cell(self, dataset: str) -> Mock:
        self.install_retrieval(dataset)
        client = self.victim_client()
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            run_victim(self.config, self.store, dataset, False)
            run_victim(self.config, self.store, dataset, True)
        return client


class SharedGExecutionTests(ExecutionFixture):
    def test_new_generator_reuses_inputs_but_never_old_responses(self) -> None:
        self.freeze_all()
        for dataset in self.config.datasets:
            self.install_retrieval(dataset)
        self.complete_cell("nfcorpus")
        original = {path: sha256_file(path) for path in self.config.output.rglob("*") if path.is_file()}
        source_path, query_path = self.store.path("source_manifest.jsonl"), self.store.path("query_plan.jsonl")
        summary = self.prepare_new_generator()
        self.assertEqual(summary["new_victim_calls"], 0)
        self.assertEqual(self.store.path("source_manifest.jsonl"), source_path)
        self.assertEqual(self.store.path("query_plan.jsonl"), query_path)
        self.assertEqual(request_records(self.store.path("initial_responses.jsonl", "nfcorpus")), [])
        self.assertEqual(self.store.validate(frozen=True)["model_profiles"]["victim"]["model"], "llama-3.1-8b-instruct")
        self.assertEqual(prepare(self.config, self.store)["status"], "already_prepared")
        self.assertEqual(original, {path: sha256_file(path) for path in original})

    def test_reused_inputs_dry_run_writes_no_run_and_rejects_question_drift(self) -> None:
        self.freeze_all()
        for dataset in self.config.datasets:
            self.install_retrieval(dataset)
        summary = self.prepare_new_generator(dry_run=True)
        self.assertEqual(summary["status"], "dry_run")
        self.assertFalse(self.config.output.exists())
        queries = read_rows(self.store.path("query_plan.jsonl"))
        queries[0]["question"] = "Changed question"
        write_rows(self.store.path("query_plan.jsonl"), queries)
        with self.assertRaisesRegex(RuntimeError, "reused_frozen_input_drift"):
            prepare(self.config, self.store, True)

    def test_reused_input_resume_rejects_cache_drift_and_nonmember_context(self) -> None:
        self.freeze_all()
        for dataset in self.config.datasets:
            self.install_retrieval(dataset)
        self.prepare_new_generator()
        path = self.store.path("retrieval.jsonl", "nfcorpus")
        rows = read_rows(path)
        nonmember = next(row for row in read_rows(self.store.path("source_manifest.jsonl"))
                         if row["group"] == "True_Non_Member")
        rows[0]["retrieved_chunks"][0]["source_key"] = nonmember["source_key"]
        write_rows(path, rows)
        with self.assertRaisesRegex(RuntimeError, "input_drift"):
            self.store.validate(frozen=True)
        with self.assertRaisesRegex(RuntimeError, "nonmember"):
            validate_retrieval(self.config, self.store, "nfcorpus")

    def test_zero_one_three_correct_slots_trigger_zero_two_six_followups(self) -> None:
        self.freeze_all()
        all_queries = read_rows(self.store.path("query_plan.jsonl"))
        source = read_rows(self.store.path("source_manifest.jsonl"))[0]
        queries = [q for q in all_queries if q["source_key"] == source["source_key"]]
        initials = [q for q in queries if q["arm"] == "initial"]
        for count in (0, 1, 3):
            responses = [{"query_id": q["query_id"], "status": "completed", "response": q["answer"] if i < count else "unknown"}
                         for i, q in enumerate(initials)]
            planned = gated_queries(queries, responses)
            self.assertEqual(len(planned), 2 * count)
            followups = [{"query_id": q["query_id"], "status": "completed", "response": q["answer"]} for q in planned]
            rows = source_scores([source], queries, responses, followups, 1.0)
            self.assertEqual(rows[0]["correct_anchor"], 2 * count)
            with self.assertRaises(RuntimeError):
                source_scores([source], queries, responses + responses[:1], followups, 1.0)

    def test_missing_extra_and_empty_response_are_rejected(self) -> None:
        self.freeze_all()
        queries = read_rows(self.store.path("query_plan.jsonl"))[:9]
        initials = [q for q in queries if q["arm"] == "initial"]
        responses = [{"query_id": q["query_id"], "status": "completed", "response": q["answer"]} for q in initials]
        with self.assertRaises(RuntimeError):
            gated_queries(queries, responses[:-1])
        responses[0]["response"] = ""
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            gated_queries(queries, responses)

    def test_completed_requests_resume_without_duplicate_calls(self) -> None:
        self.freeze_all()
        dataset = "nfcorpus"
        self.install_retrieval(dataset)
        client = self.victim_client()
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            first = run_victim(self.config, self.store, dataset, False, 2)
            self.assertFalse(first["complete"])
            self.assertTrue(run_victim(self.config, self.store, dataset, False)["complete"])
            self.assertEqual(run_victim(self.config, self.store, dataset, False)["new_calls"], 0)
            self.assertTrue(run_victim(self.config, self.store, dataset, True)["complete"])
        self.assertEqual(client.generate_with_metadata.call_count, 36)

    def test_transport_uncertainty_is_preserved_and_never_resent(self) -> None:
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        client = Mock()
        client.generate_with_metadata.side_effect = ConnectionError("sensitive text must not be logged")
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            with self.assertRaises(RuntimeError):
                run_victim(self.config, self.store, "nfcorpus", False)
            with self.assertRaises(RuntimeError):
                run_victim(self.config, self.store, "nfcorpus", False)
        self.assertEqual(client.generate_with_metadata.call_count, 1)
        row = request_records(self.store.path("initial_responses.jsonl", "nfcorpus"))[0]
        self.assertEqual(row["status"], "uncertain_transport")
        self.assertNotIn("sensitive text", str(row))

    def test_fingerprint_drift_stops(self) -> None:
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        client = Mock()
        client.generate_with_metadata.side_effect = [self.result("230", "victim"), self.result("18", "victim", system_fingerprint="different")]
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            with self.assertRaisesRegex(RuntimeError, "invalid_response"):
                run_victim(self.config, self.store, "nfcorpus", False)
        self.assertEqual(client.generate_with_metadata.call_count, 2)
        self.assertEqual(request_records(self.store.path("initial_responses.jsonl", "nfcorpus"))[-1]["status"], "invalid_provider_response")

    def test_empty_answer_stops_without_entering_scores(self) -> None:
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        client = Mock()
        client.generate_with_metadata.return_value = self.result("", "victim")
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            with self.assertRaisesRegex(RuntimeError, "invalid_response"):
                run_victim(self.config, self.store, "nfcorpus", False)
        self.assertEqual(client.generate_with_metadata.call_count, 1)

    def test_wrong_provider_model_stops(self) -> None:
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        client = Mock()
        client.generate_with_metadata.return_value = self.result("230", "victim", provider_model_id="other-model")
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            with self.assertRaisesRegex(RuntimeError, "invalid_response"):
                run_victim(self.config, self.store, "nfcorpus", False)
        self.assertEqual(client.generate_with_metadata.call_count, 1)

    def test_retrieval_nonmember_and_record_drift_are_rejected(self) -> None:
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        validate_retrieval(self.config, self.store, "nfcorpus")
        rows = read_rows(self.store.path("retrieval.jsonl", "nfcorpus"))
        nonmember = next(s for s in read_rows(self.store.path("source_manifest.jsonl")) if s["group"] == "True_Non_Member")
        rows[0]["retrieved_chunks"][0]["source_key"] = nonmember["source_key"]
        write_rows(self.store.path("retrieval.jsonl", "nfcorpus"), rows)
        with self.assertRaisesRegex(RuntimeError, "nonmember"):
            validate_retrieval(self.config, self.store, "nfcorpus")

    def test_dataset_cell_order_requires_previous_cell_completion(self) -> None:
        self.freeze_all()
        with self.assertRaises(RuntimeError):
            validate_cell_order(self.config, self.store, "scidocs")
        self.complete_cell("nfcorpus")
        validate_cell_order(self.config, self.store, "scidocs")

    def test_cuda_failure_precedes_model_load(self) -> None:
        self.freeze_all()
        with patch("torch.cuda.is_available", return_value=False), patch("src.rag.embeddings.build_embedding_model") as builder:
            with self.assertRaisesRegex(RuntimeError, "cuda_required"):
                retrieve(self.config, self.store, "nfcorpus")
            builder.assert_not_called()

    def test_local_write_retries_do_not_retry_model_requests(self) -> None:
        action = Mock(side_effect=[PermissionError(), PermissionError(), 7])
        with patch("src.shared_g.artifacts.time.sleep") as sleep:
            self.assertEqual(retry_local_write(action), 7)
        self.assertEqual(action.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        with patch("src.shared_g.artifacts.time.sleep"), self.assertRaises(PermissionError):
            retry_local_write(Mock(side_effect=PermissionError()))

    def test_mock_retrieval_reuses_index_and_preserves_stable_ties(self) -> None:
        import numpy as np

        self.freeze_all()
        embedder = Mock()
        embedder._model = SimpleNamespace(device="cuda:0")
        embedder.encode_documents.side_effect = lambda texts: np.array([[1.0, 0.0]] * len(texts))
        embedder.encode_queries.side_effect = lambda texts: np.array([[1.0, 0.0]] * len(texts))
        with patch("torch.cuda.is_available", return_value=True), \
             patch("src.rag.embeddings.build_embedding_model", return_value=embedder), \
             patch("src.rag.index_builder.chunk_for_rag_tokens", side_effect=lambda text, tokenizer, **kwargs: [text] * 3):
            first = retrieve(self.config, self.store, "nfcorpus", 2)
            self.assertFalse(first["complete"])
            self.assertTrue(retrieve(self.config, self.store, "nfcorpus")["complete"])
            self.assertEqual(retrieve(self.config, self.store, "nfcorpus")["new_queries"], 0)
        self.assertEqual(embedder.encode_documents.call_count, 1)
        row = read_rows(self.store.path("retrieval.jsonl", "nfcorpus"))[0]
        self.assertTrue(row["retrieved_chunks"][0]["chunk_id"].endswith("_c00"))
        self.assertTrue(row["retrieved_chunks"][1]["chunk_id"].endswith("_c01"))
