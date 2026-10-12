"""构造语义、盲预审与冻结的回归。"""

import importlib.util
import json
import io
import urllib.error
from unittest.mock import MagicMock, Mock, patch

from test_shared_g_sources import FormalFixture, ROOT, sample_payload, sample_text
from src.shared_g.artifacts import read_json, read_rows, write_json_atomic
from src.shared_g.construction import (GENERATION_PROMPT, _build_construction_prompt, generate,
                                      generation_records, review_packet, save_review, validate_construction,
                                      validate_candidate_generations, _request_error_details,
                                      review_decisions, qualification_progress, save_assistant_adjudication)
from src.shared_g.queries import build_frozen_queries_for_source, freeze
from src.shared_g.scoring import formatting_answer_aliases, response_label
from src.shared_g.review import REVIEW_PROMPT, ai_review_records, parse_review_response, review_ai, review_all


class SharedGConstructionTests(FormalFixture):
    def test_current_method_matches_legacy_pure_functions(self) -> None:
        spec = importlib.util.spec_from_file_location("shared_g_legacy_parity", ROOT / "scripts/103_run_v25_shared_g_successor.py")
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        payload = sample_payload()
        records, reasons = validate_construction(payload, sample_text(), 12)
        self.assertEqual((records, reasons), legacy.validate_construction(payload, sample_text(), 12))
        source = {"source_key": "nfcorpus::example", "source_hash": "hash", "dataset": "nfcorpus", "group": "KB_Member"}
        old = legacy.build_frozen_queries_for_source(source, records, "fixture")
        new = build_frozen_queries_for_source(source, records, "fixture")
        self.assertEqual(new, [{k: v for k, v in row.items() if k != "group"} for row in old])
        self.assertEqual(GENERATION_PROMPT, legacy.PILOT.GENERATION_PROMPT)
        for answer in ("$5.9\\%$", "Vitamin B6", "90—100", "the patient's response"):
            self.assertEqual(formatting_answer_aliases(answer), legacy.PILOT._formatting_answer_aliases(answer))
            for response in (answer, "unknown", "Other answer", "", "I cannot determine it."):
                self.assertEqual(response_label(response, answer), legacy.PILOT._response_label(response, answer))

    def test_single_target_and_no_membership_in_queries(self) -> None:
        records, reasons = validate_construction(sample_payload(), sample_text(), 12)
        self.assertEqual(reasons, [])
        source = {"source_key": "a", "dataset": "nfcorpus", "source_hash": "hash", "group": "KB_Member"}
        queries = build_frozen_queries_for_source(source, records, "test")
        self.assertEqual(len({q["query_id"] for q in queries}), 9)
        self.assertTrue(all("group" not in q for q in queries))
        self.assertEqual(len({q["question"] for q in queries if q["arm"] == "remote_only"}), 1)

    def test_cross_slot_and_g_answer_leaks_are_rejected(self) -> None:
        payload = sample_payload()
        payload["initial_facts"][0]["claim"] += " vitamin B6"
        _, reasons = validate_construction(payload, sample_text(payload), 12)
        self.assertIn("e1_prime_anchor_cross_slot_answer_leak", reasons)
        payload = sample_payload()
        payload["initial_facts"][0]["claim"] += " 18"
        self.assertIn("G_answer_in_local_claim", validate_construction(payload, sample_text(payload), 12)[1])

    def test_repair_is_limited_to_two_and_keeps_both_attempts(self) -> None:
        from src.shared_g.sources import prepare
        prepare(self.config, self.store)
        client = Mock()
        client.chat_with_metadata.side_effect = [self.result("invalid JSON"), self.result(json.dumps(sample_payload()))]
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            self.assertEqual(generate(self.config, self.store, "nfcorpus", 2)["new_calls"], 2)
        saved = generation_records(self.store)
        self.assertEqual(len(saved), 1)
        self.assertEqual(next(iter(saved.values()))["attempt"], 2)
        self.assertEqual(client.call_count, 0)
        self.assertEqual(client.chat_with_metadata.call_count, 2)
        self.assertIn("invalid_json", client.chat_with_metadata.call_args_list[1].args[0])
        self.assertEqual(len(read_rows(self.store.path("generation.jsonl"))), 4)

    def test_repair_feedback_does_not_include_old_raw_response(self) -> None:
        prompt = _build_construction_prompt("SOURCE", GENERATION_PROMPT,
                                            {"quality_reasons": ["question_shape"], "raw_response": "SECRET_OLD_RESPONSE"})
        self.assertIn("question_shape", prompt)
        self.assertNotIn("SECRET_OLD_RESPONSE", prompt)

    def test_review_packet_is_blind_and_has_original_text(self) -> None:
        self.construct_all()
        packet = review_packet(self.config, self.store, 0, 2)
        self.assertEqual(packet["reviewer_type"], "assistant_membership_blind")
        self.assertIn("source_text", packet["records"][0])
        self.assertNotIn("KB_Member", json.dumps(packet))
        self.assertNotIn("True_Non_Member", json.dumps(packet))

    def test_freeze_requires_complete_bound_assistant_review(self) -> None:
        self.construct_all()
        self.write_review()
        review = read_json(self.store.path("semantic_review.json"))
        review["decisions"].pop(next(iter(review["decisions"])))
        write_json_atomic(self.store.path("semantic_review.json"), review)
        with self.assertRaisesRegex(RuntimeError, "coverage_incomplete"):
            freeze(self.config, self.store)
        review["reviewer_type"] = "independent_human"
        write_json_atomic(self.store.path("semantic_review.json"), review)
        with self.assertRaisesRegex(RuntimeError, "review_identity_drift"):
            freeze(self.config, self.store)

    def test_semantic_rejection_is_replaced_before_membership(self) -> None:
        self.add_candidate("nfcorpus", 4)
        self.construct_all()
        rejected = next(iter(generation_records(self.store)))
        self.write_review({rejected: "答案不能回答问题"})
        self.assertFalse(self.store.path("index_manifest.jsonl").exists())
        with self.assertRaisesRegex(RuntimeError, "quota_not_exact"):
            freeze(self.config, self.store)
        client = Mock()
        client.chat_with_metadata.return_value = self.result(json.dumps(sample_payload()))
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            self.assertEqual(generate(self.config, self.store, "nfcorpus")["new_calls"], 1)
        self.write_review({rejected: "答案不能回答问题"})
        self.assertEqual(freeze(self.config, self.store)["queries"], 108)
        self.assertEqual(len(read_rows(self.store.path("source_manifest.jsonl"))), 12)
        self.assertEqual(len(read_rows(self.store.path("index_manifest.jsonl"))), 6)
        self.assertNotIn(rejected, {r["source_key"] for r in read_rows(self.store.path("source_manifest.jsonl"))})
        self.assertNotIn(rejected, {r["source_key"] for r in read_rows(self.store.path("query_plan.jsonl"))})
        self.assertEqual(freeze(self.config, self.store)["status"], "already_frozen")
        with self.assertRaisesRegex(RuntimeError, "already_frozen"):
            generate(self.config, self.store, "nfcorpus")

    def test_structural_failures_advance_fixed_order_until_exact_quota(self) -> None:
        self.add_candidate("nfcorpus", 4)
        self.add_candidate("nfcorpus", 5)
        from src.shared_g.sources import prepare
        prepare(self.config, self.store)
        client = Mock()
        client.chat_with_metadata.side_effect = [self.result("invalid JSON"), self.result("invalid JSON")] + [self.result(json.dumps(sample_payload()))] * 12
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            summary = generate(self.config, self.store, "nfcorpus")
            self.assertEqual(summary["new_calls"], 6)
            self.assertEqual(summary["review_pending"], 4)
            for dataset in self.config.datasets[1:]:
                generate(self.config, self.store, dataset)
        self.write_review()
        freeze(self.config, self.store)
        run = read_json(self.store.path("run_config.json"))
        self.assertEqual(run["qualification"]["nfcorpus"]["attempted_sources"], 5)
        self.assertEqual(run["qualification"]["nfcorpus"]["structural_failures"], 1)
        self.assertEqual(run["source_count"], 12)
        self.assertEqual(client.chat_with_metadata.call_count, 14)

    def test_provisional_quota_waits_for_review_without_new_calls(self) -> None:
        self.construct_all()
        with patch("src.shared_g.construction.build_role_chat_client") as builder:
            summary = generate(self.config, self.store, "nfcorpus")
            self.assertEqual(summary["new_calls"], 0)
            self.assertEqual(summary["status"], "awaiting_semantic_review")
            builder.assert_not_called()
        self.write_review()
        self.assertEqual(generate(self.config, self.store, "nfcorpus")["status"], "qualified_complete")

    def test_review_is_bound_to_exact_generation_and_not_overwritten(self) -> None:
        self.construct_all()
        saved = generation_records(self.store)
        key, row = next(iter(saved.items()))
        decision = {"generation_record_sha256": "wrong", "accepted": True, "reason": ""}
        with self.assertRaisesRegex(RuntimeError, "generation_record_drift"):
            save_review(self.config, self.store, {key: decision})
        decision["generation_record_sha256"] = row["record_sha256"]
        save_review(self.config, self.store, {key: decision})
        decision["accepted"], decision["reason"] = False, "changed verdict"
        with self.assertRaisesRegex(RuntimeError, "decision_overwrite"):
            save_review(self.config, self.store, {key: decision})

    def test_global_call_budget_stops_before_another_request(self) -> None:
        import copy
        from src.shared_g.sources import prepare
        data = copy.deepcopy(self.config.data)
        data["construction"]["maximum_total_calls"] = 2
        self.reload_config(data)
        prepare(self.config, self.store)
        client = Mock()
        client.chat_with_metadata.return_value = self.result(json.dumps(sample_payload()))
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            self.assertEqual(generate(self.config, self.store, "nfcorpus")["new_calls"], 2)
            summary = generate(self.config, self.store, "nfcorpus")
        self.assertEqual(summary["status"], "construction_call_budget_exhausted")
        self.assertEqual(summary["new_calls"], 0)
        self.assertEqual(client.chat_with_metadata.call_count, 2)

    def test_source_order_skips_are_rejected(self) -> None:
        from src.shared_g.sources import prepare
        from src.llm.factory import llm_profile_identity
        prepare(self.config, self.store)
        candidates = read_rows(self.store.path("candidate_manifest.jsonl"))
        row = candidates[1]
        identity = llm_profile_identity(self.profiles["sibling"])
        with self.assertRaisesRegex(RuntimeError, "skipped_candidate_order"):
            validate_candidate_generations(candidates, {row["source_key"]: {
                "source_key": row["source_key"], "source_hash": row["source_hash"],
                "profile_identity": identity, "status": "passed"}}, identity)

    def test_legacy_terminal_uncertainty_is_preserved_skipped_and_never_resent(self) -> None:
        self.add_candidate("nfcorpus", 4)
        from src.shared_g.sources import prepare
        prepare(self.config, self.store)
        client = Mock()
        client.chat_with_metadata.side_effect = [RuntimeError("secret must not be stored")] + [self.result(json.dumps(sample_payload()))] * 12
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            with self.assertRaisesRegex(RuntimeError, "api_error_stop"):
                generate(self.config, self.store, "nfcorpus", 1)
            self.assertEqual(generate(self.config, self.store, "nfcorpus")["new_calls"], 4)
            self.assertEqual(generate(self.config, self.store, "nfcorpus")["new_calls"], 0)
            for dataset in self.config.datasets[1:]:
                generate(self.config, self.store, dataset)
        saved = generation_records(self.store)
        failed = next(row for row in saved.values() if row["status"] == "uncertain_transport")
        self.assertEqual(failed["attempt"], 1)
        self.assertNotIn("secret", json.dumps(failed))
        self.write_review()
        freeze(self.config, self.store)
        self.assertEqual(read_json(self.store.path("run_config.json"))["qualification"]["nfcorpus"]["uncertain_call_sources"], 1)
        self.assertNotIn(failed["source_key"], {r["source_key"] for r in read_rows(self.store.path("source_manifest.jsonl"))})
        self.assertEqual(client.chat_with_metadata.call_count, 13)

    def test_http_error_diagnostics_are_safe_and_auth_errors_stop(self) -> None:
        cause = urllib.error.HTTPError("https://secret.invalid/?token=SECRET", 503, "SECRET", {}, None)
        exc = RuntimeError("SECRET")
        exc.__cause__ = cause
        details = _request_error_details(exc)
        self.assertEqual(details["http_status"], 503)
        self.assertTrue(details["transient_error"])
        self.assertNotIn("SECRET", json.dumps(details))
        exc.__cause__ = urllib.error.HTTPError("https://mock.invalid", 401, "SECRET", {}, None)
        from src.shared_g.sources import prepare
        prepare(self.config, self.store)
        client = Mock()
        client.chat_with_metadata.side_effect = exc
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            with self.assertRaisesRegex(RuntimeError, "api_error_stop"):
                generate(self.config, self.store, "nfcorpus")
        self.assertEqual(client.chat_with_metadata.call_count, 1)
        self.assertEqual(next(iter(generation_records(self.store).values()))["http_status"], 401)

    def test_network_errors_reconnect_until_success_on_same_logical_request(self) -> None:
        from src.llm.openai_compatible import OpenAICompatibleChatClient
        from src.shared_g.sources import prepare
        prepare(self.config, self.store)
        client = OpenAICompatibleChatClient(base_url="https://mock.invalid/v1", model="gpt-6-luna")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"id": "mock-request", "model": "gpt-6-luna",
            "system_fingerprint": "sibling-fingerprint", "choices": [{"message": {"content": json.dumps(sample_payload())}}]}).encode()
        errors = [TimeoutError("SECRET"), urllib.error.HTTPError("https://mock.invalid", 429, "SECRET", {}, io.BytesIO(b"")),
                  urllib.error.URLError("SECRET"), urllib.error.HTTPError("https://mock.invalid", 503, "SECRET", {}, io.BytesIO(b"")),
                  TimeoutError("SECRET")]
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])), \
             patch("src.llm.openai_compatible.urllib.request.urlopen", side_effect=[*errors, response]) as sender, \
             patch.object(client, "_sleep_backoff") as backoff:
            result = generate(self.config, self.store, "nfcorpus", 1)
        self.assertTrue(client.retry_until_success)
        self.assertEqual(sender.call_count, 6)
        self.assertEqual(backoff.call_count, 5)
        self.assertTrue(all(call.args[0] is sender.call_args_list[0].args[0] for call in sender.call_args_list))
        self.assertEqual(result["new_calls"], 1)
        self.assertEqual(result["total_calls"], 6)
        saved = next(iter(generation_records(self.store).values()))
        self.assertEqual(saved["status"], "passed")
        self.assertEqual(saved["attempt"], 1)
        self.assertEqual(saved["retry_count"], 5)
        self.assertEqual(saved["transport_request_count"], 6)
        self.assertEqual(read_json(self.store.path("run_config.json"))["construction_wire_calls"], 6)
        self.assertNotIn("SECRET", json.dumps(saved))

    def test_unlimited_reconnect_still_respects_total_wire_budget(self) -> None:
        import copy
        from src.llm.openai_compatible import OpenAICompatibleChatClient
        from src.shared_g.sources import prepare
        data = copy.deepcopy(self.config.data)
        data["construction"]["maximum_total_calls"] = 2
        self.reload_config(data)
        prepare(self.config, self.store)
        client = OpenAICompatibleChatClient(base_url="https://mock.invalid/v1", model="gpt-6-luna")
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])), \
             patch("src.llm.openai_compatible.urllib.request.urlopen", side_effect=TimeoutError("SECRET")) as sender, \
             patch.object(client, "_sleep_backoff"):
            with self.assertRaisesRegex(RuntimeError, "api_error_stop"):
                generate(self.config, self.store, "nfcorpus")
        self.assertEqual(sender.call_count, 2)
        self.assertEqual(read_json(self.store.path("run_config.json"))["construction_wire_calls"], 2)
        self.assertEqual(next(iter(generation_records(self.store).values()))["transport_request_count"], 2)
        self.assertEqual(generate(self.config, self.store, "nfcorpus")["status"], "construction_call_budget_exhausted")

    def _fake_review_client(self, rejected: set[str] | None = None, **overrides) -> Mock:
        client = Mock()

        def respond(prompt: str, **kwargs):
            client.request_rate_limiter.acquire()
            inputs = json.loads(prompt.split("INPUT SOURCES:\n", 1)[1])
            aliases = read_rows(self.store.path("semantic_review_requests.jsonl"))[-1].get("source_aliases", {})
            verdicts = [{"source_key": row["source_key"],
                         "accepted": aliases.get(row["source_key"], row["source_key"]) not in (rejected or set()),
                         "reason": "mock: G明显不受支持" if aliases.get(row["source_key"], row["source_key"]) in (rejected or set())
                         else "mock: 三初问与G有原文依据"} for row in inputs]
            return self.result(json.dumps({"decisions": verdicts}), **overrides)

        client.chat_with_metadata.side_effect = respond
        return client

    def test_ai_review_keeps_assistant_decisions_and_blind_inputs(self) -> None:
        self.construct_all()
        key, row = next(iter(generation_records(self.store).items()))
        manual = {"generation_record_sha256": row["record_sha256"], "accepted": True, "reason": "原Assistant决定"}
        save_review(self.config, self.store, {key: manual})
        client = self._fake_review_client()
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            summary = review_ai(self.config, self.store, "nfcorpus", 1)
        review = read_json(self.store.path("semantic_review.json"))
        self.assertEqual(review["decisions"][key], manual)
        self.assertEqual(review["reviewer_type"], "mixed_membership_blind")
        self.assertEqual(summary["progress"]["semantic_accepted"], 4)
        self.assertEqual(summary["progress"]["reviewer_counts"]["ai_membership_blind"], 3)
        self.assertTrue(client.retry_until_success)
        prompt = client.chat_with_metadata.call_args.args[0]
        self.assertNotIn("KB_Member", prompt)
        self.assertNotIn("True_Non_Member", prompt)
        self.assertNotIn('"group"', prompt)
        self.assertIn("Unique description", prompt)
        self.assertIn("Reject ONLY for a clear factual error", REVIEW_PROMPT)
        self.assertEqual(read_json(self.store.path("run_config.json"))["semantic_review_wire_calls"], 1)

    def test_ai_review_requires_exact_coverage_and_boolean_verdicts(self) -> None:
        binding = {"a": "hash"}
        for items in ([], [{"source_key": "b", "accepted": True, "reason": "x"}],
                      [{"source_key": "a", "accepted": 1, "reason": "x"}],
                      [{"source_key": "a", "accepted": True, "reason": ""}],
                      [{"source_key": "a", "accepted": True, "reason": "x"}] * 2):
            with self.assertRaises(ValueError):
                parse_review_response(json.dumps({"decisions": items}), binding, "req")

    def test_ai_review_short_ids_restore_exact_full_source_identity(self) -> None:
        full_key = "scidocs::44726d8c654f3cc21e7e6bbc01b4f2bd74cd658e"
        bindings = {full_key: "record-hash"}
        aliases = {"s1": full_key}
        content = json.dumps({"decisions": [{"source_key": "s1", "accepted": True, "reason": "原文支持"}]})
        decision = parse_review_response(content, bindings, "request", aliases)
        self.assertEqual(set(decision), {full_key})
        self.assertEqual(decision[full_key]["generation_record_sha256"], "record-hash")
        for malformed in ({"s1": "different-source"}, {"s1": full_key, "s2": full_key}, {}):
            with self.assertRaisesRegex(ValueError, "source_aliases_invalid"):
                parse_review_response(content, bindings, "request", malformed)
        for incorrect_key in ("s2", full_key[:-1]):
            wrong = json.dumps({"decisions": [{"source_key": incorrect_key, "accepted": True, "reason": "原文支持"}]})
            with self.assertRaisesRegex(ValueError, "decision_schema_invalid"):
                parse_review_response(wrong, bindings, "request", aliases)

    def test_ai_review_logs_short_id_mapping_and_rejects_mapping_drift(self) -> None:
        from src.shared_g.artifacts import write_rows
        self.construct_all()
        client = self._fake_review_client()
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            review_ai(self.config, self.store, "nfcorpus", 1)
        prompt = client.chat_with_metadata.call_args.args[0]
        inputs = json.loads(prompt.split("INPUT SOURCES:\n", 1)[1])
        self.assertEqual([r["source_key"] for r in inputs], ["s1", "s2", "s3", "s4"])
        self.assertNotIn("nfcorpus::", prompt)
        record = ai_review_records(self.store, generation_records(self.store))[0]
        self.assertEqual(set(record["source_aliases"].values()), set(record["source_bindings"]))
        self.assertEqual(set(record["decisions"]), set(record["source_bindings"]))
        rows = read_rows(self.store.path("semantic_review_requests.jsonl"))
        rows[-1]["source_aliases"]["s1"] = "another-source"
        write_rows(self.store.path("semantic_review_requests.jsonl"), rows)
        with self.assertRaisesRegex(RuntimeError, "request_identity_drift"):
            ai_review_records(self.store, generation_records(self.store))

    def test_ai_review_legacy_full_id_response_recovers_without_resending(self) -> None:
        from src.llm.factory import llm_profile_identity
        from src.shared_g.artifacts import append_request
        from src.utils.hash import sha256_obj, sha256_text
        self.construct_all()
        bindings = {key: row["record_sha256"] for key, row in generation_records(self.store).items()
                    if row["dataset"] == "nfcorpus"}
        content = json.dumps({"decisions": [{"source_key": key, "accepted": True, "reason": "旧格式原文支持"}
                                            for key in bindings]})
        row = {"request_key": "legacy-review", "dataset": "nfcorpus", "source_bindings": bindings,
               "prompt_sha256": "legacy-prompt", "profile_identity": llm_profile_identity(self.profiles["sibling"]),
               "status": "attempt_started"}
        append_request(self.store.path("semantic_review_requests.jsonl"), row)
        row.update(status="passed", raw_response=content, response_sha256=sha256_text(content),
                   provider_model_id="gpt-6-luna", system_fingerprint="sibling-fingerprint",
                   transport_request_count=1, decisions=parse_review_response(content, bindings, "legacy-review"))
        row["record_sha256"] = sha256_obj(row)
        append_request(self.store.path("semantic_review_requests.jsonl"), row)
        with patch("src.shared_g.review.build_role_chat_client") as builder:
            summary = review_ai(self.config, self.store, "nfcorpus", 1)
        builder.assert_not_called()
        self.assertEqual(summary["progress"]["semantic_accepted"], 4)
        self.assertEqual(set(review_decisions(self.store)), set(bindings))

    def test_ai_review_cached_response_recovers_without_resending(self) -> None:
        self.construct_all()
        client = self._fake_review_client()
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])), \
             patch("src.shared_g.review.save_review", side_effect=RuntimeError("local_merge_interrupted")):
            with self.assertRaisesRegex(RuntimeError, "local_merge_interrupted"):
                review_ai(self.config, self.store, "nfcorpus", 1)
        self.assertEqual(ai_review_records(self.store, generation_records(self.store))[0]["status"], "passed")
        with patch("src.shared_g.review.build_role_chat_client") as builder:
            summary = review_ai(self.config, self.store, "nfcorpus", 1)
        builder.assert_not_called()
        self.assertEqual(summary["progress"]["semantic_accepted"], 4)
        self.assertEqual(client.chat_with_metadata.call_count, 1)

    def test_ai_review_model_drift_preserves_response_and_no_verdict(self) -> None:
        self.construct_all()
        client = self._fake_review_client(provider_model_id="wrong-model")
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            with self.assertRaisesRegex(RuntimeError, "ai_review_error_stop"):
                review_ai(self.config, self.store, "nfcorpus", 1)
        self.assertFalse(self.store.path("semantic_review.json").exists())
        rows = read_rows(self.store.path("semantic_review_requests.jsonl"))
        self.assertEqual(rows[-1]["status"], "invalid_provider_response")
        self.assertIn("raw_response", rows[-1])

    def test_ai_review_rejection_is_not_repaired_and_replacements_are_reviewed(self) -> None:
        self.add_candidate("nfcorpus", 4)
        generator = self.construct_all()
        rejected = next(iter(generation_records(self.store)))
        with patch("src.shared_g.review.build_role_chat_client",
                   side_effect=lambda *args, **kwargs: (self._fake_review_client({rejected}), self.profiles["sibling"])), \
             patch("src.shared_g.construction.build_role_chat_client", return_value=(generator, self.profiles["sibling"])):
            summary = review_all(self.config, self.store)
        self.assertEqual(summary["status"], "qualified6000_ready_for_freeze")
        self.assertEqual(summary["progress"]["nfcorpus"]["semantic_accepted"], 4)
        self.assertEqual(summary["progress"]["nfcorpus"]["semantic_rejected"], 1)
        self.assertEqual(generation_records(self.store)[rejected]["attempt"], 1)
        frozen = freeze(self.config, self.store)
        self.assertEqual(frozen["accepted_sources"], 12)
        self.assertNotIn(rejected, {r["source_key"] for r in read_rows(self.store.path("source_manifest.jsonl"))})
        self.assertIn("semantic_review_requests.jsonl", read_json(self.store.path("run_config.json"))["frozen_artifacts"])
        with self.assertRaisesRegex(RuntimeError, "already_frozen"):
            review_ai(self.config, self.store, "nfcorpus", 1)

    def test_ai_review_and_construction_share_physical_send_ceiling(self) -> None:
        self.construct_all()
        run = read_json(self.store.path("run_config.json"))
        run["construction_wire_calls"] = self.config.data["construction"]["maximum_total_calls"] - 1
        write_json_atomic(self.store.path("run_config.json"), run)
        client = self._fake_review_client()
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            review_ai(self.config, self.store, "nfcorpus", 1)
        with patch("src.shared_g.review.build_role_chat_client") as builder:
            summary = review_ai(self.config, self.store, "scidocs", 1)
        builder.assert_not_called()
        self.assertEqual(summary["status"], "total_call_budget_exhausted")
        self.assertEqual(summary["construction_and_review_wire_calls"],
                         self.config.data["construction"]["maximum_total_calls"])

    def test_ai_review_reconnects_on_same_batch_with_shared_budget(self) -> None:
        from src.llm.openai_compatible import OpenAICompatibleChatClient
        self.construct_all()
        client = OpenAICompatibleChatClient(base_url="https://mock.invalid/v1", model="gpt-6-luna")
        keys = [key for key, row in generation_records(self.store).items() if row["dataset"] == "nfcorpus"]
        content = json.dumps({"decisions": [{"source_key": f"s{index}", "accepted": True, "reason": "原文支持"}
                                            for index, key in enumerate(keys, 1)]})
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "id": "mock-review", "model": "gpt-6-luna", "system_fingerprint": "review-fingerprint",
            "choices": [{"message": {"content": content}}]}).encode()
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])), \
             patch("src.llm.openai_compatible.urllib.request.urlopen",
                   side_effect=[TimeoutError("SECRET"), response]) as sender, \
             patch.object(client, "_sleep_backoff"):
            summary = review_ai(self.config, self.store, "nfcorpus", 1)
        self.assertEqual(sender.call_count, 2)
        self.assertIs(sender.call_args_list[0].args[0], sender.call_args_list[1].args[0])
        self.assertEqual(summary["construction_and_review_wire_calls"], 14)
        self.assertEqual(read_json(self.store.path("run_config.json"))["semantic_review_wire_calls"], 2)
        self.assertNotIn("SECRET", json.dumps(ai_review_records(self.store, generation_records(self.store))))

    def test_ai_review_incomplete_batch_keeps_response_without_partial_acceptance(self) -> None:
        self.construct_all()
        client = Mock()

        def respond(prompt: str, **kwargs):
            client.request_rate_limiter.acquire()
            inputs = json.loads(prompt.split("INPUT SOURCES:\n", 1)[1])
            return self.result(json.dumps({"decisions": [
                {"source_key": row["source_key"], "accepted": True, "reason": "原文支持"}
                for row in inputs[:-1]]}))

        client.chat_with_metadata.side_effect = respond
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            summary = review_ai(self.config, self.store, "nfcorpus", 1)
        self.assertEqual(summary["status"], "review_in_progress")
        self.assertEqual(summary["progress"]["review_pending"], 4)
        self.assertFalse(self.store.path("semantic_review.json").exists())
        self.assertEqual(read_rows(self.store.path("semantic_review_requests.jsonl"))[-1]["status"],
                         "invalid_review_response")

    def test_ai_review_malformed_json_retries_same_batch_until_valid(self) -> None:
        self.construct_all()
        original_generation = self.store.path("generation.jsonl").read_bytes()
        client = self._fake_review_client()
        successful_response = client.chat_with_metadata.side_effect
        attempts = 0

        def respond(prompt: str, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                client.request_rate_limiter.acquire()
                return self.result('{"decisions": [')
            return successful_response(prompt, **kwargs)

        client.chat_with_metadata.side_effect = respond
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            summary = review_ai(self.config, self.store, "nfcorpus", 3)
        rows = ai_review_records(self.store, generation_records(self.store))
        self.assertEqual([row["status"] for row in rows],
                         ["invalid_review_response", "invalid_review_response", "passed"])
        self.assertEqual(len({row["request_key"] for row in rows}), 3)
        self.assertEqual(rows[1]["prompt_sha256"], rows[2]["prompt_sha256"])
        self.assertIn("JSON format retry", client.chat_with_metadata.call_args_list[1].args[0])
        inputs = [json.loads(call.args[0].split("INPUT SOURCES:\n", 1)[1])
                  for call in client.chat_with_metadata.call_args_list]
        self.assertTrue(all(source_inputs == inputs[0] for source_inputs in inputs))
        self.assertTrue(all(row["source_bindings"] == rows[0]["source_bindings"] for row in rows))
        self.assertEqual([row["raw_response"] for row in rows[:2]], ['{"decisions": ['] * 2)
        self.assertTrue(all("decisions" not in row for row in rows[:2]))
        self.assertEqual(summary["progress"]["semantic_accepted"], 4)
        self.assertEqual(summary["new_batches"], 3)
        self.assertEqual(read_json(self.store.path("run_config.json"))["semantic_review_wire_calls"], 3)
        self.assertEqual(self.store.path("generation.jsonl").read_bytes(), original_generation)

    def test_ai_review_persistent_malformed_json_stops_at_shared_send_limit(self) -> None:
        self.construct_all()
        run = read_json(self.store.path("run_config.json"))
        run["construction_wire_calls"] = self.config.data["construction"]["maximum_total_calls"] - 2
        write_json_atomic(self.store.path("run_config.json"), run)
        client = Mock()

        def respond(prompt: str, **kwargs):
            client.request_rate_limiter.acquire()
            return self.result('{"decisions": [')

        client.chat_with_metadata.side_effect = respond
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            summary = review_ai(self.config, self.store, "nfcorpus", 200)
        self.assertEqual(summary["status"], "total_call_budget_exhausted")
        self.assertEqual(client.chat_with_metadata.call_count, 2)
        self.assertEqual(summary["construction_and_review_wire_calls"],
                         self.config.data["construction"]["maximum_total_calls"])
        self.assertFalse(self.store.path("semantic_review.json").exists())
        with patch("src.shared_g.review.build_role_chat_client") as builder:
            self.assertEqual(review_ai(self.config, self.store, "nfcorpus")["status"],
                             "total_call_budget_exhausted")
        builder.assert_not_called()

    def test_ai_review_canonical_verdict_tampering_is_rejected(self) -> None:
        from src.shared_g.construction import review_decisions
        self.construct_all()
        client = self._fake_review_client()
        with patch("src.shared_g.review.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            review_ai(self.config, self.store, "nfcorpus", 1)
        review = read_json(self.store.path("semantic_review.json"))
        next(iter(review["decisions"].values()))["reason"] = "未经模型返回的理由"
        write_json_atomic(self.store.path("semantic_review.json"), review)
        with self.assertRaisesRegex(RuntimeError, "decision_binding_drift"):
            review_decisions(self.store)

    def test_assistant_adjudication_preserves_ai_verdict_and_later_merges(self) -> None:
        self.construct_all()
        key, row = next(iter(generation_records(self.store).items()))
        with patch("src.shared_g.review.build_role_chat_client",
                   side_effect=lambda *a, **k: (self._fake_review_client({key}), self.profiles["sibling"])):
            review_ai(self.config, self.store, "nfcorpus", 1)
        original = read_json(self.store.path("semantic_review.json"))["decisions"][key]
        original_log = self.store.path("semantic_review_requests.jsonl").read_bytes()
        decision = {"generation_record_sha256": row["record_sha256"], "accepted": True,
                    "reason": "Assistant复核：自然语境下答案有原文依据，AI误判范围。"}
        save_assistant_adjudication(self.config, self.store, {key: decision})
        self.assertEqual(review_decisions(self.store)[key], decision)
        self.assertEqual(read_json(self.store.path("semantic_review.json"))["decisions"][key], original)
        self.assertEqual(self.store.path("semantic_review_requests.jsonl").read_bytes(), original_log)
        self.assertEqual(qualification_progress(self.config, self.store)["nfcorpus"]["semantic_accepted"], 4)
        self.assertEqual(qualification_progress(self.config, self.store)["nfcorpus"]["assistant_adjudicated_sources"], 1)
        with patch("src.shared_g.review.build_role_chat_client",
                   side_effect=lambda *a, **k: (self._fake_review_client(), self.profiles["sibling"])):
            review_ai(self.config, self.store, "scidocs", 1)
            review_ai(self.config, self.store, "trec-covid", 1)
        self.assertEqual(review_decisions(self.store)[key], decision)
        self.assertEqual(freeze(self.config, self.store)["accepted_sources"], 12)
        with self.assertRaisesRegex(RuntimeError, "already_frozen"):
            save_assistant_adjudication(self.config, self.store, {key: decision})

    def test_assistant_adjudication_rejects_unbound_and_overwritten_decisions(self) -> None:
        self.construct_all()
        key, row = next(iter(generation_records(self.store).items()))
        with patch("src.shared_g.review.build_role_chat_client",
                   return_value=(self._fake_review_client({key}), self.profiles["sibling"])):
            review_ai(self.config, self.store, "nfcorpus", 1)
        decision = {"generation_record_sha256": row["record_sha256"], "accepted": True, "reason": "原文支持"}
        accepted_key = next(k for k, v in review_decisions(self.store).items() if v["accepted"])
        with self.assertRaisesRegex(RuntimeError, "requires_ai_rejection"):
            save_assistant_adjudication(self.config, self.store, {accepted_key: decision})
        with self.assertRaisesRegex(RuntimeError, "record_drift"):
            save_assistant_adjudication(self.config, self.store, {key: {**decision, "generation_record_sha256": "wrong"}})
        save_assistant_adjudication(self.config, self.store, {key: decision})
        with self.assertRaisesRegex(RuntimeError, "refuse_assistant_adjudication_overwrite"):
            save_assistant_adjudication(self.config, self.store, {key: {**decision, "reason": "changed"}})
        with self.assertRaisesRegex(RuntimeError, "refuse_semantic_review_decision_overwrite"):
            save_review(self.config, self.store, {key: decision})

    def test_assistant_adjudication_cannot_exceed_qualified_quota(self) -> None:
        self.add_candidate("nfcorpus", 4)
        generator = self.construct_all()
        key, row = next(iter(generation_records(self.store).items()))
        with patch("src.shared_g.review.build_role_chat_client",
                   return_value=(self._fake_review_client({key}), self.profiles["sibling"])):
            review_ai(self.config, self.store, "nfcorpus", 1)
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(generator, self.profiles["sibling"])):
            generate(self.config, self.store, "nfcorpus", 1)
        with self.assertRaisesRegex(RuntimeError, "adjudication_quota_exceeded"):
            save_assistant_adjudication(self.config, self.store, {key: {
                "generation_record_sha256": row["record_sha256"], "accepted": True, "reason": "原文支持"}})
