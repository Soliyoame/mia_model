import importlib.util
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v25_pilot", ROOT / "scripts/92_run_v25_gated_followup_pilot.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class GatedFollowupPilotTests(unittest.TestCase):
    def _payload(self) -> dict[str, Any]:
        return {
            "initial_facts": [
                {"slot": "e1", "claim": "Alpha uses 12 units.", "answer": "12", "question": "How many units does Alpha use?"},
                {"slot": "e2", "claim": "Beta uses 4 units.", "answer": "4", "question": "How many units does Beta use?"},
                {"slot": "e3", "claim": "Gamma uses 8 units.", "answer": "8", "question": "How many units does Gamma use?"},
            ],
            "followup_facts": [
                {"slot": "e1_prime", "paired_initial_slot": "e1", "claim": "Alpha began in 1991.", "answer": "1991", "question": "In what year did Alpha begin operations?"},
                {"slot": "e2_prime", "paired_initial_slot": "e2", "claim": "Beta began in 1993.", "answer": "1993", "question": "In what year did Beta begin operations?"},
                {"slot": "e3_prime", "paired_initial_slot": "e3", "claim": "Gamma began in 1995.", "answer": "1995", "question": "In what year did Gamma begin operations?"},
            ],
        }

    def _source(self, payload: dict[str, Any]) -> str:
        return " ".join(row["claim"] for rows in payload.values() for row in rows)

    def test_v25_runtime_matches_shared_menta_conditions(self):
        runtime = MODULE.V25_CONFIG["runtime"]
        self.assertEqual(runtime["concrete_model"], "gemma-2-2b-it-bf16")
        self.assertEqual(runtime["retrieval"]["backend"], "dense")
        self.assertEqual(runtime["retrieval"]["retriever_id"], "BAAI/bge-base-en-v1.5")
        self.assertEqual(runtime["retrieval"]["revision"], "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a")
        self.assertEqual(runtime["retrieval"]["chunk_size"], 128)
        self.assertEqual(runtime["retrieval"]["chunk_overlap"], 32)
        self.assertEqual(runtime["retrieval"]["top_k"], 5)
        self.assertEqual(runtime["generation"]["temperature"], 0.0)
        self.assertEqual(runtime["generation"]["max_tokens"], 512)
        self.assertEqual(MODULE.V25_CONFIG["scoring"]["primary"], "S_chain")
        self.assertEqual(MODULE.V25_CONFIG["query_generator"]["configured_model"], "gpt-6-luna")

    def test_prepare_completion_uses_v25_plan_pair_count(self):
        source = {"source_key": "x", "source_hash": "h", "normalized_text_hash": "nh",
                  "dataset": "nfcorpus", "group": "KB_Member"}
        plan = {"pairs": [{"dataset": "nfcorpus", "sources": [source, {**source, "source_key": "y", "source_hash": "hy", "normalized_text_hash": "ny", "group": "True_Non_Member"}]}]}
        self.assertEqual(len(plan["pairs"]), 1)
        self.assertEqual(len(MODULE._sources(plan)), 2)

    def test_controls_have_clean_three_unconditional_six_and_followup_three(self):
        source = {"source_key": "x", "source_hash": "h", "dataset": "nfcorpus", "group": "KB_Member"}
        payload = self._payload()
        controls = MODULE._planned_controls(
            [source], {"x": {"status": "passed", "records": payload}}
        )
        self.assertEqual(
            {name: sum(row["control"] == name for row in controls)
             for name in ("clean_3", "unconditional_6", "followup_only_3")},
            {"clean_3": 3, "unconditional_6": 6, "followup_only_3": 3},
        )
        self.assertEqual(sum(row["control"] == "followup_only_3" and row["arm"] == "followup" for row in controls), 3)

    def test_member_only_index_uses_current_plan_sources(self):
        sources = [
            {"source_key": "m", "source_hash": "mh", "dataset": "nfcorpus", "group": "KB_Member"},
            {"source_key": "n", "source_hash": "nh", "dataset": "nfcorpus", "group": "True_Non_Member"},
        ]
        with patch.object(MODULE, "_source_text", side_effect=lambda row: row["source_key"]):
            self.assertEqual(MODULE._member_sources(sources), {"m": ("m", "mh")})

    def test_source_level_metrics_use_s_chain_and_macro_is_dataset_equal(self):
        rows = [
            {"source_key": "a", "dataset": "nfcorpus", "group": "KB_Member", "score": 1.0},
            {"source_key": "b", "dataset": "nfcorpus", "group": "True_Non_Member", "score": 0.0},
            {"source_key": "c", "dataset": "scidocs", "group": "KB_Member", "score": 0.0},
            {"source_key": "d", "dataset": "scidocs", "group": "True_Non_Member", "score": 1.0},
        ]
        self.assertEqual(MODULE.summarize_membership_scores(rows[:2], score_key="score")["AUC"], 1.0)
        macro = MODULE.bootstrap_macro_auc_ci(
            {"nfcorpus": rows[:2], "scidocs": rows[2:]}, score_key="score", n_bootstrap=20
        )
        self.assertEqual(macro["estimate"], 0.5)
        self.assertEqual(macro["datasets"], ["nfcorpus", "scidocs"])

    def test_followup_conditional_is_undefined_with_zero_observed_denominator(self):
        source = {"source_key": "x", "dataset": "nfcorpus", "group": "KB_Member"}
        queries = []
        initial = {}
        for index in range(3):
            query = {"source_key": "x", "slot_index": index, "arm": "initial", "query_id": f"i{index}", "answer": f"a{index}"}
            queries.append(query)
            initial[query["query_id"]] = {"status": "completed", "response": "wrong"}
            queries.append({"source_key": "x", "slot_index": index, "arm": "followup", "query_id": f"f{index}", "answer": f"b{index}"})
        row = MODULE._score_source(source, queries, initial, {})
        self.assertEqual(row["S_chain"], 0.0)
        self.assertIsNone(row["S_followup"])

    def test_source_split_is_deterministic_and_source_hash_exclusive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = copy.deepcopy(MODULE.V25_CONFIG)
            config_path = root / "configs/restoration_first_v25.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("protocol_version: pcv-mia-v25\n", encoding="utf-8")
            config["_config_path"] = str(config_path)
            for dataset in MODULE.DATASETS:
                folder = root / "artifacts/v24/source_pools" / dataset
                folder.mkdir(parents=True)
                rows = []
                order = []
                for index in range(2):
                    key = f"{dataset}::source-{index}"
                    text = f"Document {dataset} {index}."
                    source_hash = MODULE.sha256_text(text)
                    rows.append((key, dataset, f"doc-{index}", str(index), source_hash, source_hash, text))
                    order.append(key)
                connection = sqlite3.connect(folder / "source_pool.sqlite3")
                try:
                    connection.execute("CREATE TABLE sources (source_key TEXT, dataset TEXT, document_id TEXT, source_order_rank TEXT, source_hash TEXT, normalized_text_hash TEXT, full_text TEXT)")
                    connection.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
                    connection.commit()
                finally:
                    connection.close()
                (folder / "source_order.json").write_text(json.dumps({"source_order": order}), encoding="utf-8")
                (folder / "development_exclusions.json").write_text(json.dumps({"exclusions": []}), encoding="utf-8")
                (folder / "source_pool_manifest.json").write_text("{}", encoding="utf-8")
            first = MODULE.build_source_exclusive_split(root, config, root / "out", pair_quotas={name: 1 for name in MODULE.DATASETS})
            second = MODULE.build_source_exclusive_split(root, config, root / "out2", pair_quotas={name: 1 for name in MODULE.DATASETS})
            self.assertEqual(first["source_keys_sha256"], second["source_keys_sha256"])
            keys = [source["source_key"] for pair in first["pairs"] for source in pair["sources"]]
            hashes = [source["source_hash"] for pair in first["pairs"] for source in pair["sources"]]
            self.assertEqual(len(keys), len(set(keys)))
            self.assertEqual(len(hashes), len(set(hashes)))
            self.assertFalse(first["membership_labels_read"])

    def test_generation_requires_three_initial_and_followup_slots(self):
        payload = self._payload()
        records, reasons = MODULE._validate_generation(payload, " ".join(row["claim"] for rows in payload.values() for row in rows))
        self.assertEqual(reasons, [])
        self.assertEqual(len(records["initial_facts"]), 3)
        self.assertEqual(len(records["followup_facts"]), 3)

    def test_generation_rejects_answer_leak_and_duplicate_answer(self):
        payload = {
            "initial_facts": [
                {"slot": "e1", "claim": "Alpha uses 12 units.", "answer": "12", "question": "How many units does Alpha use?"},
                {"slot": "e2", "claim": "Alpha uses 12 units.", "answer": "12", "question": "How many units does Beta use?"},
                {"slot": "e3", "claim": "Gamma uses 8 units.", "answer": "8", "question": "How many units does Gamma use?"},
            ],
            "followup_facts": [
                {"slot": "e1_prime", "paired_initial_slot": "e1", "claim": "Alpha began in 1991.", "answer": "1991", "question": "In what year did Alpha begin operations?"},
                {"slot": "e2_prime", "paired_initial_slot": "e2", "claim": "Beta began in 1993.", "answer": "1993", "question": "In what year did Beta begin operations?"},
                {"slot": "e3_prime", "paired_initial_slot": "e3", "claim": "Gamma began in 1995.", "answer": "1995", "question": "In what year did Gamma begin operations?"},
            ],
        }
        _records, reasons = MODULE._validate_generation(payload, " ".join(row["claim"] for rows in payload.values() for row in rows))
        self.assertTrue(any("duplicate_answer" in reason for reason in reasons))

    def test_paired_claims_may_overlap_when_answers_are_distinct(self):
        payload = self._payload()
        shared_claim = "Alpha uses 12 units and began in 1991."
        payload["initial_facts"][0].update(
            claim=shared_claim,
            answer="12",
            question="How many units does Alpha use?",
        )
        payload["followup_facts"][0].update(
            claim=shared_claim,
            answer="1991",
            question="In what year did Alpha begin operations?",
        )
        records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertEqual(reasons, [])
        self.assertEqual(records["initial_facts"][0]["claim"], shared_claim)
        self.assertEqual(records["followup_facts"][0]["answer"], "1991")

    def test_source_score_gates_followup_per_slot(self):
        source = {"source_key": "x", "dataset": "nfcorpus", "group": "KB_Member"}
        queries = []
        initial = {}
        followup = {}
        for index, (initial_ok, follow_ok) in enumerate(((True, True), (True, False), (False, False))):
            iq = {"source_key": "x", "slot_index": index, "arm": "initial", "query_id": f"i{index}", "answer": f"a{index}"}
            fq = {"source_key": "x", "slot_index": index, "arm": "followup", "query_id": f"f{index}", "answer": f"b{index}"}
            queries.extend((iq, fq))
            initial[f"i{index}"] = {"status": "completed", "response": f"a{index}" if initial_ok else "wrong"}
            followup[f"f{index}"] = {"status": "completed", "response": f"b{index}" if follow_ok else "wrong"}
        result = MODULE._score_source(source, queries, initial, followup)
        self.assertEqual(result["triggered"], 2)
        self.assertEqual(result["followup_successes"], 1)
        self.assertEqual(result["query_count"], 5)
        self.assertAlmostEqual(result["followup_conditional"], 0.5)
        self.assertAlmostEqual(result["chain_score"], 1 / 3)

    def test_query_budget_never_exceeds_six(self):
        for triggered in range(4):
            self.assertLessEqual(3 + triggered, 6)

    def test_answer_matching_uses_normalized_complete_surface(self):
        self.assertTrue(MODULE._answer_correct("The result was  North Ridge.", "North Ridge"))
        self.assertFalse(MODULE._answer_correct("The result was North Ridgeline.", "North Ridge"))

    def test_question_gate_rejects_answer_surface(self):
        reasons = MODULE._validate_question("Which site was identified as North Ridge?", ["North Ridge"])
        self.assertIn("question_answer_leak", reasons)

    def test_prompt_contains_complete_renderable_schema(self):
        source = "The literal {source} is not a format placeholder in this input."
        prompt = MODULE.GENERATION_PROMPT.format(source=source)
        schema = json.loads(prompt.split("placeholders):\n", 1)[1].split("\n\nSource:\n", 1)[0])
        self.assertEqual(schema, MODULE.GENERATION_SCHEMA_EXAMPLE)
        self.assertEqual(len(schema["initial_facts"]), 3)
        self.assertEqual(len(schema["followup_facts"]), 3)
        for index, row in enumerate(schema["followup_facts"], start=1):
            self.assertEqual(row["slot"], f"e{index}_prime")
            self.assertEqual(row["paired_initial_slot"], f"e{index}")
        self.assertTrue(prompt.endswith(source))

    def test_prompt_allows_shared_evidence_when_answers_are_not_derivable(self):
        prompt = MODULE.GENERATION_PROMPT.format(source="Source text.")
        self.assertIn("share a subject, sentence, chunk, or context", prompt)
        self.assertIn("not be directly derivable", prompt)
        self.assertNotIn("Use distinct, non-overlapping evidence spans.", prompt)

    def test_missing_identity_fields_are_inferred_without_mutating_payload(self):
        payload = self._payload()
        source = self._source(payload)
        for rows in payload.values():
            for row in rows:
                del row["slot"]
                row.pop("paired_initial_slot", None)
        original = copy.deepcopy(payload)
        records, reasons = MODULE._validate_generation(payload, source)
        self.assertEqual(reasons, [])
        self.assertEqual(payload, original)
        for index, row in enumerate(records["initial_facts"], start=1):
            self.assertEqual(row["slot"], f"e{index}")
            self.assertEqual(row["inferred_fields"], ["slot"])
        for index, row in enumerate(records["followup_facts"], start=1):
            self.assertEqual(row["paired_initial_slot"], f"e{index}")
            self.assertEqual(row["inferred_fields"], ["slot", "paired_initial_slot"])

    def test_explicit_wrong_or_null_identity_is_rejected(self):
        for field, value in (("slot", "e3_prime"), ("slot", None),
                             ("paired_initial_slot", "e2"), ("paired_initial_slot", None)):
            with self.subTest(field=field, value=value):
                payload = self._payload()
                payload["followup_facts"][0][field] = value
                _records, reasons = MODULE._validate_generation(payload, self._source(payload))
                self.assertTrue(any("slot" in reason or "pairing" in reason for reason in reasons))

    def test_missing_slots_do_not_skip_content_validation(self):
        payload = self._payload()
        source = self._source(payload)
        del payload["initial_facts"][0]["slot"]
        payload["initial_facts"][0]["claim"] = "An invented unsupported claim."
        _records, reasons = MODULE._validate_generation(payload, source)
        self.assertIn("e1_claim_not_verbatim", reasons)
        self.assertIn("e1_answer_not_in_claim", reasons)

    def test_partial_arrays_and_non_string_fields_are_rejected(self):
        payload = self._payload()
        payload["initial_facts"].pop()
        self.assertEqual(MODULE._validate_generation(payload, "")[1], ["schema_three_plus_three"])
        for value in (None, 12, ["12"], ""):
            payload = self._payload()
            source = self._source(payload)
            payload["initial_facts"][0]["answer"] = value
            self.assertIn("e1_answer_required_string", MODULE._validate_generation(payload, source)[1])
        self.assertEqual(
            MODULE._validate_generation({"initial_facts": [], "followup_facts": []}, "")[1],
            ["insufficient_atomic_facts"],
        )

    def test_short_questions_and_long_entity_names_are_not_length_rejected(self):
        self.assertEqual(MODULE._validate_question("What virus causes COVID-19?", ["SARS-CoV-2"]), [])
        self.assertIn("question_shape", MODULE._validate_question("?", []))
        payload = self._payload()
        row = payload["initial_facts"][0]
        row.update(answer="Institute for the Study of Ancient Languages and Early Civilizations",
                   question="Which institute sponsored Project Aurora?")
        row["claim"] = f"Project Aurora was sponsored by the {row['answer']}."
        self.assertEqual(MODULE._validate_generation(payload, self._source(payload))[1], [])

    def test_context_gate_distinguishes_prior_work_from_conversation_references(self):
        for question in ("What features do previous methods for image classification fuse?",
                         "Which measurements were above the normal threshold?"):
            self.assertEqual(MODULE._validate_question(question, []), [])
        for question in ("Which values were mentioned above?", "What explains this result?",
                         "What did the previous answer identify?", "Which method is in the above passage?"):
            self.assertIn("question_context_dependency", MODULE._validate_question(question, []))

    def test_cross_slot_leakage_is_checked_in_both_directions(self):
        for kind, index, leaked_kind, leaked_index in (
            ("initial_facts", 0, "followup_facts", 2),
            ("followup_facts", 0, "followup_facts", 2),
            ("followup_facts", 2, "initial_facts", 0),
        ):
            with self.subTest(kind=kind, index=index, leaked_kind=leaked_kind):
                payload = self._payload()
                row = payload[kind][index]
                answer = payload[leaked_kind][leaked_index]["answer"]
                row["question"] = f"Which facility reported {answer} units?"
                _records, reasons = MODULE._validate_generation(payload, self._source(payload))
                self.assertIn(f"{row['slot']}_question_answer_leak", reasons)

    def test_original_evidence_and_full_answer_boundaries_remain_required(self):
        payload = self._payload()
        source = self._source(payload)
        payload["initial_facts"][0]["claim"] = "ALPHA uses 12 units."
        self.assertIn("e1_claim_not_verbatim", MODULE._validate_generation(payload, source)[1])
        payload = self._payload()
        payload["initial_facts"][0]["claim"] = "Alpha uses 312 units."
        self.assertIn("e1_answer_not_in_claim", MODULE._validate_generation(payload, self._source(payload))[1])

    @contextmanager
    def _replay_fixture(self) -> Iterator[dict[str, Path]]:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            paths = {name: folder / filename for name, filename in (
                ("PLAN", "source_plan.json"), ("CONFIG", "experiment_config.json"),
                ("GENERATION", "query_generation.jsonl"), ("GENERATION_REPLAY", "generation_replay.json"),
            )}
            sources, attempts, texts = [], [], {}
            for index in range(8):
                payload = self._payload()
                text = self._source(payload) + f" Source {index}."
                source = {"source_key": f"sample::{index}", "source_hash": MODULE.sha256_text(text),
                          "group": MODULE.GROUPS[index % 2], "dataset": "nfcorpus"}
                texts[source["source_key"]] = text
                sources.append(source)
                del payload["initial_facts"][0]["slot"]
                raw = json.dumps(payload)
                attempts.append({**source, "raw_response": raw, "response_sha256": MODULE.sha256_text(raw),
                                 "status": "failed_quality_gate", "quality_reasons": ["initial_facts_0_slot"],
                                 "provider_model_id": "gpt-6-luna"})
            MODULE.write_json({"pairs": [{"sources": sources[i:i+2]} for i in range(0, 8, 2)]}, paths["PLAN"])
            MODULE.write_json({"source_plan_sha256": MODULE.sha256_file(paths["PLAN"]),
                               "runner_sha256": "original_runner_hash",
                               "models": {"query_generator": "gpt-6-luna"}}, paths["CONFIG"])
            MODULE._write_rows(paths["GENERATION"], attempts)
            with patch.multiple(MODULE, **paths), patch.object(
                MODULE, "_source_text", side_effect=lambda row: texts[row["source_key"]]
            ), patch.object(MODULE.prior, "_luna_client", side_effect=AssertionError("unexpected_api")), patch.object(
                MODULE.prior, "_victim_client", side_effect=AssertionError("unexpected_victim")
            ):
                yield paths

    def test_replay_is_deterministic_and_preserves_original_artifacts(self):
        with self._replay_fixture() as paths:
            originals = {key: path.read_bytes() for key, path in paths.items() if key != "GENERATION_REPLAY"}
            MODULE.replay_generation()
            first = paths["GENERATION_REPLAY"].read_bytes()
            MODULE.replay_generation()
            self.assertEqual(paths["GENERATION_REPLAY"].read_bytes(), first)
            for key, contents in originals.items():
                self.assertEqual(paths[key].read_bytes(), contents)
            result = json.loads(first)
            self.assertEqual(result["original_passed_sources"], 0)
            self.assertEqual(result["structural_passed_sources"], 8)
            self.assertFalse(result["semantic_validation_performed"])
            self.assertEqual(result["new_calls"], {"luna": 0, "victim": 0, "retriever": 0})
            self.assertTrue(all(row["semantic_review_required"] for row in result["source_rows"]))

    def test_replay_rejects_response_and_source_identity_drift(self):
        for field in ("raw_response", "source_hash"):
            with self.subTest(field=field), self._replay_fixture() as paths:
                rows = list(MODULE.read_jsonl(paths["GENERATION"]))
                rows[0][field] += "changed"
                MODULE._write_rows(paths["GENERATION"], rows)
                with self.assertRaisesRegex(RuntimeError, "generation_(response|source)_drift"):
                    MODULE.replay_generation()
                self.assertFalse(paths["GENERATION_REPLAY"].exists())

    def test_replay_rejects_plan_drift_and_changed_report(self):
        with self._replay_fixture() as paths:
            paths["PLAN"].write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "source_plan_drift"):
                MODULE.replay_generation()
        with self._replay_fixture() as paths:
            MODULE.replay_generation()
            paths["GENERATION_REPLAY"].write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "generation_replay_drift"):
                MODULE.replay_generation()

    def test_offline_replay_does_not_relax_live_runner_binding(self):
        with self._replay_fixture():
            with self.assertRaisesRegex(RuntimeError, "runner_drift"):
                MODULE._fixed_inputs()

    def test_frozen_aliases_and_numeric_boundaries(self):
        self.assertTrue(MODULE._answer_correct("**40** studies", "Forty", ["40"]))
        self.assertTrue(MODULE._answer_correct("52.7%-78.7%", "52.7%–78.7%"))
        self.assertFalse(MODULE._answer_correct("0.6", "6"))
        self.assertFalse(MODULE._answer_correct("65.6", "65"))
        self.assertFalse(MODULE._answer_correct("40", "Forty"))

    def test_ambiguous_and_invalid_answers_do_not_trigger(self):
        query = {"answer": "London", "aliases": []}
        for response in ("Not London.", "The answer is unknown, possibly London."):
            self.assertEqual(MODULE._response_label({"status": "completed", "response": response}, query), "ambiguous")
        self.assertEqual(MODULE._response_label({"status": "uncertain_transport"}, query), "invalid")
        self.assertEqual(MODULE._response_label({"status": "completed", "response": ""}, query), "invalid")

    def test_missing_failed_and_untriggered_followups_are_distinct(self):
        source = {"source_key": "x", "dataset": "nfcorpus", "group": "KB_Member"}
        queries = [{"source_key": "x", "slot_index": i, "arm": arm, "query_id": f"{arm}{i}", "answer": f"value{i}"}
                   for i in range(3) for arm in ("initial", "followup")]
        initial = {f"initial{i}": {"status": "completed", "response": "value0" if i == 0 else "wrong"} for i in range(3)}
        row = MODULE._score_source(source, queries, initial, {})
        self.assertEqual(row["slots"][0]["followup_label"], "not_sent")
        self.assertEqual(row["slots"][1]["followup_label"], "not_triggered")
        self.assertEqual(row["query_count"], 3)
        failed = {"followup0": {"status": "uncertain_transport"}}
        row = MODULE._score_source(source, queries, initial, failed)
        self.assertEqual(row["query_count"], 4)
        self.assertEqual(row["followup_observed"], 0)
        self.assertEqual(row["followup_denominator"], 1)
        self.assertEqual(row["followup_conditional"], 0.0)
        self.assertIsNone(row["slots"][0]["followup_correct"])

    def test_review_cannot_accept_failed_generation_or_leaking_alias(self):
        with self._replay_fixture() as paths:
            review_path = paths["PLAN"].parent / "query_review.json"
            sources = MODULE._sources(json.loads(paths["PLAN"].read_text()))
            decisions = {s["source_key"]: {"accepted": False} for s in sources}
            decisions[sources[0]["source_key"]] = {
                "accepted": True,
                "aliases": {"e1": ["Alpha"]},
                "answer_not_derivable_from_other_query_answer_pairs": {
                    slot: True for slot in MODULE.FACT_SLOTS
                },
            }
            review = {"generation_sha256": MODULE.sha256_file(paths["GENERATION"]), "sources": decisions}
            MODULE.write_json(review, review_path)
            with patch.object(MODULE, "QUERY_REVIEW", review_path):
                with self.assertRaisesRegex(RuntimeError, "cannot_accept_structural_failure"):
                    MODULE._reviewed_generation(sources)
                rows = list(MODULE.read_jsonl(paths["GENERATION"]))
                rows[0]["status"] = "passed"
                rows[0]["records"] = MODULE._validate_generation(json.loads(rows[0]["raw_response"]), MODULE._source_text(sources[0]))[0]
                MODULE._write_rows(paths["GENERATION"], rows)
                review["generation_sha256"] = MODULE.sha256_file(paths["GENERATION"])
                for review_value in (
                    {},
                    {**{slot: True for slot in MODULE.FACT_SLOTS}, "e2": False},
                ):
                    decisions[sources[0]["source_key"]]["answer_not_derivable_from_other_query_answer_pairs"] = review_value
                    MODULE.write_json(review, review_path)
                    with self.assertRaisesRegex(RuntimeError, "answer_derivability_review_required"):
                        MODULE._reviewed_generation(sources)
                decisions[sources[0]["source_key"]]["answer_not_derivable_from_other_query_answer_pairs"] = {
                    slot: True for slot in MODULE.FACT_SLOTS
                }
                MODULE.write_json(review, review_path)
                with self.assertRaisesRegex(RuntimeError, "query_alias_leak"):
                    MODULE._reviewed_generation(sources)
                decisions[sources[0]["source_key"]]["aliases"] = {"e1": ["twelve"]}
                MODULE.write_json(review, review_path)
                approved = MODULE._reviewed_generation(sources)
                self.assertEqual(len(approved), 1)
                plan = MODULE._planned_queries(sources, approved)
                self.assertEqual(len(plan), 6)
                self.assertEqual(sum(q["arm"] == "initial" for q in plan), 3)
                self.assertEqual(plan[0]["aliases"], ["twelve"])


if __name__ == "__main__":
    unittest.main()
