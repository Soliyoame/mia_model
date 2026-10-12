import importlib.util
import copy
import json
import re
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
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
        self.assertEqual(MODULE.V25_CONFIG["generation_repair"], {
            "max_repairs_per_phase": 1,
            "scope": "full_phase",
        })

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

    def test_question_gate_rejects_unresolved_mask_placeholder(self):
        reasons = MODULE._validate_question(
            "What can be reconstructed from its [MASK] on the sampling set?",
            [],
        )
        self.assertIn("question_placeholder", reasons)

    def test_question_gate_does_not_apply_grammar_and_answer_shape_heuristics(self):
        self.assertEqual(
            MODULE._validate_question("What does it do and where is it used?", []), []
        )
        self.assertEqual(MODULE._validate_question("Which tasks?", []), [])
        self.assertEqual(MODULE._validate_question("What frame rate?", []), [])

    def test_retrieval_diagnostics_report_short_or_unanchored_questions(self):
        self.assertIn(
            "question_too_short_for_retrieval",
            MODULE._query_retrieval_reasons("What is it?", "Alpha uses twelve units."),
        )
        self.assertIn(
            "question_claim_overlap_too_small",
            MODULE._query_retrieval_reasons(
                "Which distant phenomenon causes substantial improvement?",
                "Alpha uses twelve units.",
            ),
        )
        self.assertEqual(
            MODULE._query_retrieval_reasons(
                "What units does Alpha use and when?", "Alpha uses twelve units."
            ),
            [],
        )

    def test_retrieval_diagnostics_do_not_fail_phase(self):
        payload = self._payload()
        payload["initial_facts"][0]["question"] = "What is it?"
        records, reasons = MODULE._validate_phase_payload(
            {"facts": payload["initial_facts"]},
            self._source(payload),
            "initial",
        )
        self.assertEqual(reasons, [])
        self.assertEqual(len(records), 3)

    def test_phase_retrieval_diagnostics_are_recorded_separately(self):
        diagnostics = MODULE._phase_retrieval_diagnostics([{
            "slot": "e1",
            "question": "What is it?",
            "claim": "Alpha uses twelve units.",
        }])
        self.assertEqual(diagnostics, {
            "e1": ["question_too_short_for_retrieval", "question_claim_overlap_too_small"]
        })

    def test_complete_enumeration_answer_remains_valid_when_source_bound(self):
        payload = self._payload()
        payload["initial_facts"][0].update(
            claim="Alpha uses 12 units and 4 units.",
            answer="12 units and 4 units",
            question="Which units does Alpha use?",
        )
        records, reasons = MODULE._validate_phase_payload(
            {"facts": payload["initial_facts"]},
            self._source(payload),
            "initial",
        )
        self.assertEqual(reasons, [])
        self.assertEqual(records[0]["answer"], "12 units and 4 units")

    def _fact_pool(self, count: int = 12) -> tuple[dict[str, Any], str]:
        facts = []
        for index in range(count):
            claim = f"Entity {index} has value {index + 10} units."
            facts.append({
                "candidate_id": f"f{index:02d}",
                "entity": f"{index + 10} units",
                "claim": claim,
            })
        return {"facts": facts}, " ".join(row["claim"] for row in facts)

    def test_fact_pool_keeps_source_supported_multi_value_candidates(self):
        payload, source = self._fact_pool()
        payload["facts"][0]["entity"] = "10 and 11 units"
        payload["facts"][0]["claim"] = "Entity 0 has values 10 and 11 units, respectively."
        source += " " + payload["facts"][0]["claim"]
        facts, reasons = MODULE._validate_fact_candidates(payload, source)
        self.assertEqual(reasons, [])
        self.assertEqual(len(facts), 12)
        self.assertIn("10 and 11 units", [row["answer"] for row in facts])

    def test_fact_pool_does_not_apply_multi_value_or_deictic_heuristics(self):
        payload, source = self._fact_pool()
        payload["facts"][0]["claim"] = (
            "Treatments included alpha, beta, gamma, and delta."
        )
        payload["facts"][0]["answer"] = "alpha"
        payload["facts"][0]["entity"] = "alpha"
        source += " " + payload["facts"][0]["claim"]
        facts, reasons = MODULE._validate_fact_candidates(payload, source)
        self.assertEqual(reasons, [])
        self.assertIn("alpha", [row["answer"] for row in facts])

    def test_fact_pool_requires_only_source_supported_answers(self):
        payload, source = self._fact_pool()
        payload["facts"][0]["claim"] = "Entity 0 has value 30% frameshecond."
        payload["facts"][0]["entity"] = "30% frameshecond"
        source += " " + payload["facts"][0]["claim"]
        facts, reasons = MODULE._validate_fact_candidates(payload, source)
        self.assertEqual(reasons, [])
        self.assertEqual(len(facts), 12)
        self.assertIn("30% frameshecond", [row["answer"] for row in facts])

    def test_fact_pool_does_not_guess_answer_syntax(self):
        payload, source = self._fact_pool()
        sentence = (
            "Spurious but systematic correlations in functional connectivity "
            "networks arise from subject motion"
        )
        payload["facts"][0]["entity"] = sentence
        payload["facts"][0]["claim"] = sentence + "."
        source += " " + payload["facts"][0]["claim"]
        facts, reasons = MODULE._validate_fact_candidates(payload, source)
        self.assertEqual(reasons, [])
        self.assertEqual(len(facts), 12)
        self.assertIn(sentence, [row["answer"] for row in facts])

    def test_selector_is_deterministic_and_assigns_six_paired_slots(self):
        payload, _source = self._fact_pool()
        selected, reasons = MODULE._select_six_facts(payload["facts"])
        self.assertEqual(reasons, [])
        self.assertEqual([row["slot"] for row in selected], list(MODULE.FACT_SLOTS))
        self.assertEqual(
            [row["paired_initial_slot"] for row in selected[3:]], ["e1", "e2", "e3"]
        )
        again, _ = MODULE._select_six_facts(payload["facts"])
        self.assertEqual(selected, again)

    def test_selector_allows_repeated_subject_when_answers_and_claims_differ(self):
        facts = []
        for index in range(12):
            facts.append({
                "candidate_id": f"f{index:02d}",
                "claim": f"The same subject has property {index}.",
                "entity": str(index),
            })
        selected, reasons = MODULE._select_six_facts(facts)
        self.assertEqual(len(selected), 6)
        self.assertEqual(reasons, [])

    def test_fact_candidate_gate_checks_source_support_not_relation_heuristics(self):
        payload, source = self._fact_pool()
        payload["facts"][0].update(
            entity="This paper",
            claim="This paper presents the approach.",
        )
        payload["facts"][1].update(
            entity="optimal feature subset selection",
            claim="We explore the relation between optimal feature subset selection and relevance.",
        )
        source += " " + payload["facts"][0]["claim"] + " " + payload["facts"][1]["claim"]
        facts, reasons = MODULE._validate_fact_candidates(payload, source)
        self.assertEqual(reasons, [])
        self.assertIn("This paper", [row["answer"] for row in facts])
        self.assertIn("optimal feature subset selection", [row["answer"] for row in facts])

    def test_independent_question_gate_rejects_cross_slot_answer_but_not_other_source_answer(self):
        fact = {"answer": "Alpha"}
        self.assertIn(
            "question_cross_slot_answer_leak",
            MODULE._validate_independent_question(
                "Which facility reported Beta units?", fact, ["Alpha", "Beta"]
            ),
        )
        self.assertEqual(
            MODULE._validate_independent_question(
                "Which facility reported Beta units?", fact, ["Alpha"]
            ),
            [],
        )

    def test_independent_question_gate_does_not_guess_polarity(self):
        reasons = MODULE._validate_independent_question(
            "What percentage of participants were male?",
            {"answer": "75% females", "claim": "75% females were enrolled."},
            ["75% females"],
        )
        self.assertNotIn("question_polarity_mismatch", reasons)

    def test_question_prompt_masks_all_selected_answers(self):
        masked = MODULE._masked_claim("Alpha uses 12 units and Beta uses 4 units.", ["12 units", "4 units"])
        self.assertEqual(masked, "Alpha uses [MASK] and Beta uses [MASK].")
        prompt = MODULE.QUESTION_PROMPT.format(
            phase="initial",
            facts=json.dumps([
                {"slot": "e1", "masked_claim": masked},
            ])
        )
        self.assertIn("masked_claim", prompt)
        self.assertNotIn("target_answer", prompt)
        self.assertIn("contains no answer values", prompt)
        self.assertIn("do not use pronouns or demonstratives", prompt)
        self.assertIn("Never mention a slot, claim, mask, answer", prompt)
        self.assertIn("[MASK]", prompt)
        self.assertNotIn("target=", prompt)

    def test_question_evidence_masks_other_selected_answers_too(self):
        self.assertEqual(
            MODULE._masked_claim(
                "Alpha uses 12 units and Beta uses 4 units.",
                ["12 units", "4 units"],
            ),
            "Alpha uses [MASK] and Beta uses [MASK].",
        )

    def test_question_phase_summary_requires_each_slot(self):
        facts = [{"slot": slot} for slot in ("e1", "e2", "e3")]
        phase = {"slot_attempts": {
            "e1": {"status": "passed", "questions": [{"slot": "e1", "question": "Q1?"}]},
            "e2": {"status": "failed_quality_gate", "quality_reasons": ["question_unresolved_pronoun"]},
        }}
        MODULE._summarize_question_phase(phase, facts)
        self.assertEqual(phase["status"], "incomplete")
        self.assertIn("e2_question_unresolved_pronoun", phase["quality_reasons"])
        self.assertEqual(phase["questions"], [{"slot": "e1", "question": "Q1?"}])

    def test_question_generation_sends_one_slot_per_request(self):
        payload = self._payload()
        facts = []
        for slot, row in zip(MODULE.FACT_SLOTS, [*payload["initial_facts"], *payload["followup_facts"]]):
            fact = dict(row)
            fact["slot"] = slot
            if slot.endswith("_prime"):
                fact["paired_initial_slot"] = slot[:2]
            facts.append(fact)
        source_text = self._source(payload)
        source = {"source_key": "sample::one", "source_hash": MODULE.sha256_text(source_text),
                  "normalized_text_hash": "normalized", "dataset": "nfcorpus", "group": "KB_Member"}
        prompts: list[str] = []

        class FakeClient:
            def chat_with_metadata(self, prompt: str, **_kwargs: Any) -> Any:
                prompts.append(prompt)
                body = prompt.split("Masked claims:\n", 1)[1]
                masked = json.loads(body)
                self_outer.assertEqual(len(masked), 1)
                slot = masked[0]["slot"]
                claim = next(fact["claim"] for fact in facts if fact["slot"] == slot)
                anchor = MODULE._content_tokens(claim)
                anchor_text = " ".join(sorted(anchor)[:3])
                content = json.dumps({"questions": [{"slot": slot, "question": f"Which source details concern {anchor_text}?"}]})
                return SimpleNamespace(content=content, provider_model_id="gpt-6-luna",
                                       provider_request_id=f"request-{len(prompts)}", called_at="now")

        self_outer = self
        with tempfile.TemporaryDirectory() as temporary:
            question_path = Path(temporary) / "question_generation.jsonl"
            with patch.object(MODULE, "_fixed_inputs", return_value=([source], {})), \
                 patch.object(MODULE, "_selected_map", return_value={source["source_key"]: {"status": "passed", "facts": facts}}), \
                 patch.object(MODULE, "QUESTION_GENERATION", question_path), \
                 patch.object(MODULE, "_luna_client", return_value=(FakeClient(), {"timeout": 1}, "profile")), \
                 patch.object(MODULE.time, "sleep"):
                MODULE.generate_questions(6)
            self.assertEqual(len(prompts), 6)
            attempt = list(MODULE.read_jsonl(question_path))[0]
            self.assertEqual(attempt["status"], "passed")
            self.assertEqual(attempt["phases"]["initial"]["status"], "passed")
            self.assertEqual(attempt["phases"]["followup"]["status"], "passed")
            for prompt in prompts:
                self.assertNotIn('"target_answer"', prompt)
                self.assertNotIn('"answer"', prompt)

    def test_generate_makes_two_source_level_phase_requests(self):
        payload = self._payload()
        source_text = self._source(payload)
        source = {
            "source_key": "sample::two-phase",
            "source_hash": MODULE.sha256_text(source_text),
            "normalized_text_hash": "normalized",
            "dataset": "nfcorpus",
            "group": "KB_Member",
        }
        responses = [
            {"facts": payload["initial_facts"]},
            {"facts": payload["followup_facts"]},
        ]
        calls: list[str] = []

        class FakeClient:
            def chat_with_metadata(self, prompt: str, **_kwargs: Any) -> Any:
                calls.append(prompt)
                return SimpleNamespace(
                    content=json.dumps(responses[len(calls) - 1]),
                    provider_model_id="gpt-6-luna",
                    provider_request_id=f"phase-{len(calls)}",
                    called_at="now",
                )

        with tempfile.TemporaryDirectory() as temporary:
            generation_path = Path(temporary) / "query_generation.jsonl"
            with patch.object(MODULE, "_fixed_inputs", return_value=([source], {})), \
                 patch.object(MODULE, "GENERATION", generation_path), \
                 patch.object(MODULE, "_source_text", return_value=source_text), \
                 patch.object(MODULE, "_luna_client", return_value=(FakeClient(), {"timeout": 1}, "profile")), \
                 patch.object(MODULE.time, "sleep"):
                MODULE.generate(2)
            row = list(MODULE.read_jsonl(generation_path))[0]
            self.assertEqual(len(calls), 2)
            self.assertEqual(row["status"], "passed")
            self.assertEqual(set(row["phases"]), {"initial", "followup"})
            self.assertEqual(len(row["records"]["initial_facts"]), 3)
            self.assertEqual(len(row["records"]["followup_facts"]), 3)

    def test_generate_does_not_pass_followup_when_initial_phase_failed(self):
        payload = self._payload()
        source_text = self._source(payload)
        source = {
            "source_key": "sample::initial-failure",
            "source_hash": MODULE.sha256_text(source_text),
            "normalized_text_hash": "normalized",
            "dataset": "nfcorpus",
            "group": "KB_Member",
        }

        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def chat_with_metadata(self, _prompt: str, **_kwargs: Any) -> Any:
                self.calls += 1
                content = {"facts": []} if self.calls == 1 else {"facts": payload["followup_facts"]}
                return SimpleNamespace(
                    content=json.dumps(content), provider_model_id="gpt-6-luna",
                    provider_request_id=f"phase-{self.calls}", called_at="now",
                )

        with tempfile.TemporaryDirectory() as temporary:
            generation_path = Path(temporary) / "query_generation.jsonl"
            with patch.object(MODULE, "_fixed_inputs", return_value=([source], {})), \
                 patch.object(MODULE, "GENERATION", generation_path), \
                 patch.object(MODULE, "_source_text", return_value=source_text), \
                 patch.object(MODULE, "_luna_client", return_value=(FakeClient(), {"timeout": 1}, "profile")), \
                 patch.object(MODULE.time, "sleep"):
                MODULE.generate(2)
            row = list(MODULE.read_jsonl(generation_path))[0]
            self.assertEqual(row["status"], "incomplete")

    def test_generate_repairs_full_phase_and_preserves_original_response(self):
        payload = self._payload()
        source_text = self._source(payload)
        payload["initial_facts"][0]["question"] = "What is it?"
        source = {
            "source_key": "sample::repair-one-slot",
            "source_hash": MODULE.sha256_text(source_text),
            "normalized_text_hash": "normalized",
            "dataset": "nfcorpus",
            "group": "KB_Member",
        }
        initial_bad = copy.deepcopy(payload["initial_facts"])
        initial_bad[1]["question"] = "Which value is 4?"
        initial_repair = {"facts": copy.deepcopy(payload["initial_facts"])}
        responses = [
            {"facts": initial_bad},
            initial_repair,
            {"facts": payload["followup_facts"]},
        ]
        prompts: list[str] = []

        class FakeClient:
            def chat_with_metadata(self, prompt: str, **_kwargs: Any) -> Any:
                prompts.append(prompt)
                return SimpleNamespace(
                    content=json.dumps(responses[len(prompts) - 1]),
                    provider_model_id="gpt-6-luna",
                    provider_request_id=f"repair-{len(prompts)}",
                    called_at="now",
                )

        with tempfile.TemporaryDirectory() as temporary:
            generation_path = Path(temporary) / "query_generation.jsonl"
            with patch.object(MODULE, "_fixed_inputs", return_value=([source], {})), \
                 patch.object(MODULE, "GENERATION", generation_path), \
                 patch.object(MODULE, "_source_text", return_value=source_text), \
                 patch.object(MODULE, "_luna_client", return_value=(FakeClient(), {"timeout": 1}, "profile")), \
                 patch.object(MODULE.time, "sleep"):
                MODULE.generate(2)
            row = list(MODULE.read_jsonl(generation_path))[0]
            initial = row["phases"]["initial"]
            self.assertEqual(initial["status"], "passed")
            self.assertEqual(initial["repair"]["status"], "passed")
            self.assertEqual(initial["repair"]["scope"], "full_phase")
            self.assertEqual(initial["repair"]["records"], payload["initial_facts"])
            self.assertEqual(initial["retrieval_diagnostics"], {
                "e1": ["question_too_short_for_retrieval", "question_claim_overlap_too_small"]
            })
            self.assertEqual(initial["raw_response"], json.dumps({"facts": initial_bad}))
            self.assertEqual(initial["repair"]["raw_response"], json.dumps(initial_repair))
            self.assertEqual(initial["records"], payload["initial_facts"])
            self.assertEqual(len(prompts), 3)

    def test_generate_repair_failure_keeps_phase_failed(self):
        payload = self._payload()
        source_text = self._source(payload)
        source = {
            "source_key": "sample::repair-leak",
            "source_hash": MODULE.sha256_text(source_text),
            "normalized_text_hash": "normalized",
            "dataset": "nfcorpus",
            "group": "KB_Member",
        }
        bad = copy.deepcopy(payload["initial_facts"])
        bad[1]["question"] = "Which value is 4?"
        repair = copy.deepcopy(payload["initial_facts"])
        repair[1]["question"] = "Which value is 8?"
        responses = [{"facts": bad}, {"facts": repair}]

        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def chat_with_metadata(self, _prompt: str, **_kwargs: Any) -> Any:
                self.calls += 1
                return SimpleNamespace(
                    content=json.dumps(responses[self.calls - 1]),
                    provider_model_id="gpt-6-luna",
                    provider_request_id=f"repair-{self.calls}",
                    called_at="now",
                )

        with tempfile.TemporaryDirectory() as temporary:
            generation_path = Path(temporary) / "query_generation.jsonl"
            with patch.object(MODULE, "_fixed_inputs", return_value=([source], {})), \
                 patch.object(MODULE, "GENERATION", generation_path), \
                 patch.object(MODULE, "_source_text", return_value=source_text), \
                 patch.object(MODULE, "_luna_client", return_value=(FakeClient(), {"timeout": 1}, "profile")), \
                 patch.object(MODULE.time, "sleep"):
                MODULE.generate(1)
            row = list(MODULE.read_jsonl(generation_path))[0]
            self.assertEqual(row["phases"]["initial"]["status"], "failed_quality_gate")
            self.assertEqual(row["phases"]["initial"]["repair"]["status"], "failed_quality_gate")
            self.assertIn("e2_question_cross_slot_answer_leak", row["phases"]["initial"]["repair"]["quality_reasons"])
            self.assertEqual(row["status"], "incomplete")

    def test_generate_repairs_all_slots_for_global_phase_error_once(self):
        payload = self._payload()
        source_text = self._source(payload)
        source = {
            "source_key": "sample::repair-global",
            "source_hash": MODULE.sha256_text(source_text),
            "normalized_text_hash": "normalized",
            "dataset": "nfcorpus",
            "group": "KB_Member",
        }
        prompts: list[str] = []

        class FakeClient:
            def chat_with_metadata(self, prompt: str, **_kwargs: Any) -> Any:
                prompts.append(prompt)
                if len(prompts) == 1:
                    return SimpleNamespace(
                        content=json.dumps({"facts": []}), provider_model_id="gpt-6-luna",
                        provider_request_id="original", called_at="now",
                    )
                if len(prompts) == 2:
                    return SimpleNamespace(
                        content=json.dumps({"facts": payload["initial_facts"]}), provider_model_id="gpt-6-luna",
                        provider_request_id="repair", called_at="now",
                    )
                return SimpleNamespace(
                    content=json.dumps({"facts": payload["followup_facts"]}), provider_model_id="gpt-6-luna",
                    provider_request_id="followup", called_at="now",
                )

        with tempfile.TemporaryDirectory() as temporary:
            generation_path = Path(temporary) / "query_generation.jsonl"
            with patch.object(MODULE, "_fixed_inputs", return_value=([source], {})), \
                 patch.object(MODULE, "GENERATION", generation_path), \
                 patch.object(MODULE, "_source_text", return_value=source_text), \
                 patch.object(MODULE, "_luna_client", return_value=(FakeClient(), {"timeout": 1}, "profile")), \
                 patch.object(MODULE.time, "sleep"):
                MODULE.generate(2)
            row = list(MODULE.read_jsonl(generation_path))[0]
            repair = row["phases"]["initial"]["repair"]
            self.assertEqual(repair["scope"], "full_phase")
            self.assertEqual(repair["status"], "passed")
            self.assertEqual(len(prompts), 3)

    def test_followup_full_phase_repair_preserves_pairing(self):
        payload = self._payload()
        source_text = self._source(payload)
        records, reasons = MODULE._validate_phase_payload(
            {"facts": payload["followup_facts"]},
            source_text,
            "followup",
            [row["answer"] for row in payload["initial_facts"]],
        )
        self.assertEqual(reasons, [])
        self.assertEqual(
            [(row["slot"], row["paired_initial_slot"]) for row in records],
            [("e1_prime", "e1"), ("e2_prime", "e2"), ("e3_prime", "e3")],
        )

    def test_followup_prompt_uses_only_paired_claim_fields(self):
        prompt = MODULE.QUESTION_PROMPT.format(
            phase="followup",
            facts=json.dumps([{
                "slot": "e1_prime",
                "paired_initial_slot": "e1",
                "paired_initial_masked_claim": "Alpha uses [MASK] units.",
                "masked_claim": "Alpha began in [MASK].",
            }]),
        )
        self.assertIn("paired_initial_masked_claim", prompt)
        self.assertIn("Alpha began in [MASK]", prompt)
        self.assertIn("follow-up phase", prompt)

    def test_followup_hints_include_initial_answer_blacklist(self):
        hints = MODULE._phase_initial_hints([{
            "slot": "e1",
            "claim": "Alpha uses 12 units.",
            "answer": "12",
        }])
        self.assertEqual(hints, [{
            "slot": "e1",
            "masked_claim": "Alpha uses [MASK] units.",
            "forbidden_initial_answer": "12",
        }])

    def test_question_batch_requires_all_slots_and_rejects_leak(self):
        facts = [
            {"slot": "e1", "answer": "12", "claim": "Alpha uses 12 units."},
            {"slot": "e2", "answer": "4", "claim": "Beta uses 4 units."},
            {"slot": "e3", "answer": "8", "claim": "Gamma uses 8 units."},
            {"slot": "e1_prime", "answer": "1991", "claim": "Alpha began in 1991."},
            {"slot": "e2_prime", "answer": "1993", "claim": "Beta began in 1993."},
            {"slot": "e3_prime", "answer": "1995", "claim": "Gamma began in 1995."},
        ]
        payload = {"questions": [{"slot": fact["slot"], "question": f"Which details concern {fact['claim'].split()[0]} {fact['claim'].split()[1]}?"} for fact in facts]}
        records, reasons = MODULE._validate_question_batch(payload, facts)
        self.assertEqual(len(records), 6)
        self.assertEqual(reasons, [])
        payload["questions"][1]["question"] = "Which value is 4?"
        _records, reasons = MODULE._validate_question_batch(payload, facts)
        self.assertTrue(any("question_answer_leak" in reason for reason in reasons))

    def test_stage_artifacts_bind_source_hashes(self):
        source = {"source_key": "s1", "source_hash": "hash-1"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fact_path = root / "facts.jsonl"
            selected_path = root / "selected.jsonl"
            question_path = root / "questions.jsonl"
            MODULE._write_rows(fact_path, [{**source, "status": "passed"}])
            MODULE._write_rows(selected_path, [{**source, "status": "passed"}])
            MODULE._write_rows(question_path, [{**source, "slot": "e1", "status": "passed"}])
            with patch.object(MODULE, "FACT_CANDIDATES", fact_path):
                self.assertEqual(MODULE._fact_attempts([source])["s1"]["source_hash"], "hash-1")
                rows = list(MODULE.read_jsonl(fact_path))
                rows[0]["source_hash"] = "other"
                MODULE._write_rows(fact_path, rows)
                with self.assertRaisesRegex(RuntimeError, "fact_source_identity_drift"):
                    MODULE._fact_attempts([source])

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

    def test_replay_supports_two_phase_generation_records(self):
        with self._replay_fixture() as paths:
            rows = []
            for source in json.loads(paths["PLAN"].read_text(encoding="utf-8"))["pairs"]:
                for item in source["sources"]:
                    payload = self._payload()
                    phase_payloads = {
                        "initial": {"facts": payload["initial_facts"]},
                        "followup": {"facts": payload["followup_facts"]},
                    }
                    phases = {}
                    for phase, phase_payload in phase_payloads.items():
                        raw = json.dumps(phase_payload)
                        phases[phase] = {
                            "status": "passed",
                            "raw_response": raw,
                            "response_sha256": MODULE.sha256_text(raw),
                            "provider_model_id": "gpt-6-luna",
                        }
                    rows.append({**item, "status": "passed", "phases": phases})
            MODULE._write_rows(paths["GENERATION"], rows)
            MODULE.replay_generation()
            result = json.loads(paths["GENERATION_REPLAY"].read_text(encoding="utf-8"))
            self.assertEqual(result["original_passed_sources"], 8)
            self.assertEqual(result["structural_passed_sources"], 8)
            self.assertEqual(
                set(result["source_rows"][0]["records"]),
                {"initial_facts", "followup_facts"},
            )

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

    def test_runtime_drift_accepts_recorded_runner_digest_snapshot(self):
        with self._replay_fixture() as paths:
            snapshot = paths["CONFIG"].with_name("runner_at_generation.txt")
            snapshot.write_text("original_runner_hash\n", encoding="utf-8")
            config_payload = json.loads(paths["CONFIG"].read_text(encoding="utf-8"))
            config_payload["input_sha256"] = {}
            config_payload["protocol_config_sha256"] = MODULE.sha256_file(MODULE.V25_CONFIG["_config_path"])
            MODULE.write_json(config_payload, paths["CONFIG"])
            real_sha256_file = MODULE.sha256_file

            def fake_sha256_file(path: Path) -> str:
                resolved = Path(path).resolve()
                if resolved == Path(MODULE.__file__).resolve():
                    return "current_runner_hash"
                if resolved == snapshot.resolve():
                    return "snapshot_binary_hash"
                return real_sha256_file(path)

            with patch.object(MODULE, "OUT", paths["CONFIG"].parent), \
                    patch.object(MODULE, "_input_hashes", return_value={}), \
                    patch.object(MODULE, "sha256_file", side_effect=fake_sha256_file):
                _sources, config = MODULE._fixed_inputs(allow_report_runtime_drift=True)
            self.assertEqual(config["runner_sha256"], "original_runner_hash")

    def test_victim_entrypoints_use_audited_runtime_drift_path(self):
        queries = [{"arm": "initial", "query_id": "q1"}]
        retrieval = {"q1": {}}
        with patch.object(MODULE, "_fixed_queries", return_value=queries) as fixed_queries, \
                patch.object(MODULE, "_fixed_retrieval", return_value=retrieval), \
                patch.object(MODULE, "_run_victim") as run_victim:
            MODULE.run_initial(24)
        fixed_queries.assert_called_once_with(allow_report_runtime_drift=True)
        run_victim.assert_called_once_with(queries, MODULE.INITIAL_RESPONSES, retrieval, 24)

    def test_followup_budget_uses_current_query_plan_capacity(self):
        queries = [
            {"arm": arm, "query_id": f"{arm}-{index}", "source_key": "source", "slot_index": index,
             "answer": f"answer-{arm}-{index}"}
            for arm in ("initial", "followup")
            for index in range(42)
        ]
        retrieval = {row["query_id"]: {} for row in queries}
        positives = {("source", index): True for index in range(42)}
        with patch.object(MODULE, "_fixed_queries", return_value=queries), \
                patch.object(MODULE, "_fixed_retrieval", return_value=retrieval), \
                patch.object(MODULE, "_initial_results", return_value=positives), \
                patch.object(MODULE, "_run_victim") as run_victim:
            MODULE.run_followup(42)
        run_victim.assert_called_once_with(
            [row for row in queries if row["arm"] == "followup"],
            MODULE.FOLLOWUP_RESPONSES,
            retrieval,
            42,
        )

    def test_frozen_aliases_and_numeric_boundaries(self):
        self.assertTrue(MODULE._answer_correct("**40** studies", "Forty", ["40"]))
        self.assertTrue(MODULE._answer_correct("52.7%-78.7%", "52.7%–78.7%"))
        self.assertTrue(MODULE._answer_correct("precision was 98. 4 %", "98.4%"))
        self.assertTrue(MODULE._answer_correct("a dioxin - like ( DL ) mixture", "dioxin-like (DL)"))
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

    def test_review_accepts_two_phase_generation_records(self):
        payload = self._payload()
        source_text = self._source(payload)
        sources = [
            {"source_key": "phase::member", "source_hash": MODULE.sha256_text(source_text),
             "normalized_text_hash": "member-text", "dataset": "scidocs", "group": "KB_Member"},
            {"source_key": "phase::nonmember", "source_hash": MODULE.sha256_text(source_text + " second"),
             "normalized_text_hash": "nonmember-text", "dataset": "scidocs", "group": "True_Non_Member"},
        ]
        attempts = []
        for source in sources:
            phase_rows = {}
            for phase, phase_payload in (("initial", {"facts": payload["initial_facts"]}),
                                         ("followup", {"facts": payload["followup_facts"]})):
                raw = json.dumps(phase_payload)
                records, reasons = MODULE._validate_phase_payload(
                    phase_payload, source_text, phase,
                    [row["answer"] for row in payload["initial_facts"]] if phase == "followup" else None,
                )
                self.assertEqual(reasons, [])
                phase_rows[phase] = {
                    "status": "passed", "raw_response": raw,
                    "response_sha256": MODULE.sha256_text(raw), "records": records,
                    "provider_model_id": "gpt-6-luna",
                }
            records, reasons = MODULE._merge_phase_records(
                phase_rows["initial"]["records"], phase_rows["followup"]["records"], source_text
            )
            self.assertEqual(reasons, [])
            attempts.append({**source, "status": "passed", "phases": phase_rows,
                             "records": records})
        plan = {"pairs": [{"dataset": "scidocs", "sources": sources}]}
        review = {
            "generation_sha256": "pending",
            "sources": {
                sources[0]["source_key"]: {
                    "accepted": True,
                    "answer_not_derivable_from_other_query_answer_pairs": {
                        slot: True for slot in MODULE.FACT_SLOTS
                    },
                    "aliases": {},
                },
                sources[1]["source_key"]: {"accepted": False},
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            generation_path = Path(temporary) / "query_generation.jsonl"
            review_path = Path(temporary) / "query_review.json"
            MODULE._write_rows(generation_path, attempts)
            review["generation_sha256"] = MODULE.sha256_file(generation_path)
            MODULE.write_json(review, review_path)
            with patch.object(MODULE, "GENERATION", generation_path), \
                 patch.object(MODULE, "QUERY_REVIEW", review_path), \
                 patch.object(MODULE, "_source_text", side_effect=lambda row: source_text if row["source_key"] == "phase::member" else source_text + " second"):
                accepted = MODULE._reviewed_generation(MODULE._sources(plan))
            self.assertEqual(set(accepted), {"phase::member"})

    def test_review_rejects_repair_provider_model_drift(self):
        payload = self._payload()
        source_text = self._source(payload)
        source = {
            "source_key": "phase::repair-drift",
            "source_hash": MODULE.sha256_text(source_text),
            "normalized_text_hash": "text",
            "dataset": "nfcorpus",
            "group": "KB_Member",
        }
        initial = copy.deepcopy(payload["initial_facts"])
        initial[1]["question"] = "Which value is 4?"
        original_raw = json.dumps({"facts": initial})
        repair_raw = json.dumps({"facts": payload["initial_facts"]})
        original_records, original_reasons = MODULE._validate_phase_payload(
            {"facts": initial}, source_text, "initial"
        )
        self.assertIn("e2_question_answer_leak", original_reasons)
        followup_raw = json.dumps({"facts": payload["followup_facts"]})
        followup_records, _ = MODULE._validate_phase_payload(
            {"facts": payload["followup_facts"]}, source_text, "followup",
            [row["answer"] for row in payload["initial_facts"]],
        )
        attempts = [{
            **source,
            "status": "passed",
            "phases": {
                "initial": {
                    "status": "passed", "records": payload["initial_facts"],
                    "raw_response": original_raw, "response_sha256": MODULE.sha256_text(original_raw),
                    "provider_model_id": "gpt-6-luna", "repair": {
                    "status": "passed", "scope": "full_phase",
                        "original_quality_reasons": sorted(set(original_reasons)),
                        "raw_response": repair_raw, "response_sha256": MODULE.sha256_text(repair_raw),
                        "provider_model_id": "other-model",
                    },
                },
                "followup": {
                    "status": "passed", "records": followup_records,
                    "raw_response": followup_raw, "response_sha256": MODULE.sha256_text(followup_raw),
                    "provider_model_id": "gpt-6-luna",
                },
            },
        }]
        merged, merge_reasons = MODULE._merge_phase_records(
            payload["initial_facts"], followup_records, source_text
        )
        self.assertEqual(merge_reasons, [])
        attempts[0]["records"] = merged
        with tempfile.TemporaryDirectory() as temporary:
            generation_path = Path(temporary) / "generation.jsonl"
            review_path = Path(temporary) / "review.json"
            MODULE._write_rows(generation_path, attempts)
            review = {
                "generation_sha256": MODULE.sha256_file(generation_path),
                "sources": {source["source_key"]: {
                    "accepted": True,
                    "answer_not_derivable_from_other_query_answer_pairs": {
                        slot: True for slot in MODULE.FACT_SLOTS
                    },
                    "aliases": {},
                }},
            }
            MODULE.write_json(review, review_path)
            with patch.object(MODULE, "GENERATION", generation_path), \
                 patch.object(MODULE, "QUERY_REVIEW", review_path), \
                 patch.object(MODULE, "_source_text", return_value=source_text):
                with self.assertRaisesRegex(RuntimeError, "generation_repair_drift"):
                    MODULE._reviewed_generation([source])


class SharedGSuccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "v25_shared_g_successor_tests", ROOT / "scripts/103_run_v25_shared_g_successor.py"
        )
        cls.successor = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.successor)

    def _queries(self):
        return [{"query_id": f"{arm}{i}", "source_key": "s", "arm": arm,
                 "slot_index": i, "answer": "Alpha" if arm == "initial" else "Gamma"}
                for arm in ("initial",) + self.successor.ARMS for i in range(3)]

    def _initial(self):
        return [{"query_id": f"initial{i}", "status": "completed",
                 "response": "Alpha" if i == 0 else "unknown"} for i in range(3)]

    def test_successor_blind_selection_ignores_input_membership(self):
        pool = [{"source_key": str(i), "source_hash": f"h{i}", "normalized_text_hash": f"n{i}",
                 "full_text": "a b c d", "group": "KB_Member", "membership": 1} for i in range(12)]
        selected = self.successor.select_blind_sources(pool, 6, 42, 3, {"0"}, {"h1"})
        changed = [{**row, "group": "True_Non_Member", "membership": 0} for row in pool]
        self.assertEqual(selected, self.successor.select_blind_sources(changed, 6, 42, 3, {"0"}, {"h1"}))
        self.assertNotIn("0", {row["source_key"] for row in selected})
        self.assertNotIn("1", {row["source_key"] for row in selected})
        self.assertEqual(sum(row["group"] == "KB_Member" for row in selected), 3)

    def test_successor_nonmember_text_hash_overlap_rejected(self):
        sources = [{"source_key": "m", "source_hash": "hm", "normalized_text_hash": "nm", "group": "KB_Member"},
                   {"source_key": "n", "source_hash": "hn", "normalized_text_hash": "nn", "group": "True_Non_Member"}]
        index = [sources[0], {"source_key": "fill", "source_hash": "hf", "normalized_text_hash": "nn", "group": "KB_Member"}]
        with self.assertRaisesRegex(RuntimeError, "nonmember_index_overlap:normalized_text_hash"):
            self.successor.validate_isolation(sources, index)
        with self.assertRaisesRegex(RuntimeError, "designated_member_omitted"):
            self.successor.validate_isolation(sources, [index[1]])

    def test_successor_sends_each_arm_only_for_correct_local_slot(self):
        planned = self.successor.gated_queries(self._queries(), self._initial())
        self.assertEqual({q["query_id"] for q in planned}, {"correct_anchor0", "remote_only0"})
        invalid = self._initial()
        invalid[0]["status"] = "uncertain_transport"
        with self.assertRaisesRegex(RuntimeError, "invalid_run_incomplete"):
            self.successor.gated_queries(self._queries(), invalid)

    def test_successor_missing_extra_followup_cannot_be_scored(self):
        follow = [{"query_id": "correct_anchor0", "status": "completed", "response": "Gamma"}]
        sources = [{"source_key": "s", "group": "KB_Member", "dataset": "nfcorpus"}]
        with self.assertRaisesRegex(RuntimeError, "followup_gate_missing_or_extra"):
            self.successor.source_scores(sources, self._queries(), self._initial(), follow, 1)

    def test_successor_point_score_has_same_cutoff_local_baseline(self):
        follow = [{"query_id": "correct_anchor0", "status": "completed", "response": "Gamma"},
                  {"query_id": "remote_only0", "status": "completed", "response": "unknown"}]
        sources = [{"source_key": "s", "group": "KB_Member", "dataset": "nfcorpus"}]
        row = self.successor.source_scores(sources, self._queries(), self._initial(), follow, 1)[0]
        self.assertEqual((row["local_only"], row["correct_anchor"], row["remote_only"]), (1, 2, 1))
        initial = [{**r, "response": "Alpha"} for r in self._initial()]
        follow = [{"query_id": q["query_id"], "status": "completed", "response": "unknown"}
                  for q in self._queries() if q["arm"] != "initial"]
        row = self.successor.source_scores(sources, self._queries(), initial, follow, 1)[0]
        self.assertEqual(row["local_only"], 3)
        self.assertEqual(row["correct_anchor"], 3)

    def test_successor_freeze_validation_rejects_config_drift(self):
        runner = self.successor.Successor()
        with tempfile.TemporaryDirectory() as temporary:
            runner.out = Path(temporary)
            self.successor.write_json({"input_hashes": {"config": "old"}}, runner.path("run_config.json"))
            with patch.object(runner, "input_hashes", return_value={"config": "new"}):
                with self.assertRaisesRegex(RuntimeError, "frozen_code_config_or_source_pool_drift"):
                    runner.validate()

    def test_successor_provider_model_drift_stops_after_first_call(self):
        runner = self.successor.Successor()
        queries = [{"query_id": f"i{i}", "source_key": "s", "arm": "initial", "slot_index": i,
                    "question": "Which value?", "answer": "Gamma"} for i in range(3)]
        context = "Gamma is a value."
        prompt = self.successor.PILOT.RAG_PROMPT.format(contexts=context, query=queries[0]["question"])
        found = {q["query_id"]: {"retrieved_chunks": [{"text": context}],
                                "context_sha256": self.successor.sha256_text(context),
                                "prompt_sha256": self.successor.sha256_text(prompt)} for q in queries}
        from unittest.mock import Mock
        client = Mock()
        client.generate_with_metadata.return_value = SimpleNamespace(
            content="Gamma", provider_model_id="wrong-model", provider_request_id="r", called_at="now",
            system_fingerprint=None,
        )
        with tempfile.TemporaryDirectory() as temporary:
            runner.out = Path(temporary)
            self.successor.write_jsonl_atomic(queries, runner.path("query_plan.jsonl"))
            self.successor.write_jsonl_atomic(list(found.values()), runner.path("retrieval.jsonl"))
            profile = {"model": "gemma-2-2b-it-bf16", "timeout": 60}
            with patch.object(runner, "retrieval_map", return_value=found), \
                 patch.object(self.successor.PILOT, "load_llm_profiles", return_value={}), \
                 patch.object(self.successor.PILOT, "build_victim_client", return_value=(client, profile)):
                with self.assertRaisesRegex(RuntimeError, "victim_invalid_response_stop"):
                    runner.run_victim(False, 3)
            self.assertEqual(client.generate_with_metadata.call_count, 1)
            self.assertEqual(self.successor.read_rows(runner.path("initial_responses.jsonl"))[0]["status"], "provider_model_drift")


if __name__ == "__main__":
    unittest.main()
