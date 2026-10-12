import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v25_shared_g_query_construction", ROOT / "scripts/95_run_v25_shared_g_pilot.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
SUCCESSOR_SPEC = importlib.util.spec_from_file_location(
    "v25_shared_g_query_stability_successor",
    ROOT / "scripts/103_run_v25_shared_g_successor.py",
)
SUCCESSOR = importlib.util.module_from_spec(SUCCESSOR_SPEC)
assert SUCCESSOR_SPEC is not None and SUCCESSOR_SPEC.loader is not None
SUCCESSOR_SPEC.loader.exec_module(SUCCESSOR)


class SharedGQueryConstructionTests(unittest.TestCase):
    def _payload(self):
        return {
            "initial_facts": [
                {
                    "slot": "e1",
                    "claim": "The study enrolled 230 adult patients with IBS.",
                    "answer": "230",
                    "question": "How many adult patients with IBS did the study enroll?",
                },
                {
                    "slot": "e2",
                    "claim": "Participants received vitamin B6 treatment.",
                    "answer": "vitamin B6",
                    "question": "Which treatment did participants receive?",
                },
                {
                    "slot": "e3",
                    "claim": "Follow-up lasted 12 weeks.",
                    "answer": "12 weeks",
                    "question": "How many weeks did follow-up last?",
                },
            ],
            "remote_target": {
                "claim": "After vitamin B6 treatment, 18 patients reported fewer vomiting episodes.",
                "answer": "18",
                "question": "How many patients reported fewer vomiting episodes after vitamin B6 treatment?",
                "region_hint": "Results",
            },
        }

    def _source(self, payload):
        claims = [row["claim"] for row in payload["initial_facts"]]
        claims.append(payload["remote_target"]["claim"])
        return "\n".join(claims)

    def test_prompt_requests_only_local_facts_and_one_shared_target(self):
        prompt = MODULE.GENERATION_PROMPT.replace("{source}", "Example source.")
        self.assertIn("initial_facts, remote_target.", prompt)
        self.assertIn("Do not generate anchored or remote-only follow-up questions.", prompt)
        self.assertIn("same focal study", prompt)
        self.assertIn("quotes its paired local claim", prompt)
        self.assertNotIn('"anchored_followups": [', prompt)
        self.assertNotIn('"no_anchor_followups": [', prompt)

    def test_followups_are_derived_with_one_identical_g_question(self):
        payload = self._payload()
        records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertEqual(reasons, [])
        target_question = records["remote_target"]["question"]
        self.assertEqual(
            [row["question"] for row in records["no_anchor_followups"]],
            [target_question] * 3,
        )
        for index, followup in enumerate(records["anchored_followups"]):
            self.assertEqual(followup["anchor"], records["initial_facts"][index]["answer"])
            self.assertEqual(followup["anchor_claim"], records["initial_facts"][index]["claim"])
            self.assertEqual(
                followup["question"],
                MODULE._anchored_question(followup["anchor_claim"], target_question),
            )
            self.assertEqual(followup["slot"], f"e{index + 1}_prime")

    def test_anchor_query_uses_local_claim_context_and_exact_g_question(self):
        payload = self._payload()
        records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertEqual(reasons, [])
        self.assertEqual(
            records["anchored_followups"][0]["question"],
            "The source reports: “The study enrolled 230 adult patients with IBS.” "
            "How many patients reported fewer vomiting episodes after vitamin B6 treatment?",
        )

    def test_anchor_context_adds_sentence_punctuation_to_a_source_fragment(self):
        self.assertEqual(
            MODULE._anchored_question("vitamin B6 treatment", "Which outcome was reported?"),
            "The source reports: “vitamin B6 treatment.” Which outcome was reported?",
        )

    def test_anchor_claim_cannot_leak_another_local_slot_answer(self):
        payload = self._payload()
        payload["initial_facts"][0]["claim"] = (
            "The study enrolled 230 adult patients with IBS and follow-up lasted 12 weeks."
        )
        _records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertIn("e1_prime_anchor_cross_slot_answer_leak", reasons)

    def test_anchor_claim_cannot_leak_the_shared_g_answer(self):
        payload = self._payload()
        payload["initial_facts"][1]["claim"] = (
            "Participants received vitamin B6 treatment and 18 reported fewer episodes."
        )
        _records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertIn("e2_prime_question_answer_leak", reasons)

    def test_g_question_can_include_a_necessary_local_condition(self):
        payload = self._payload()
        payload["remote_target"]["question"] = (
            "How many patients reported fewer vomiting episodes after vitamin B6 treatment?"
        )
        _records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertEqual(reasons, [])

    def test_g_answer_is_still_forbidden_in_target_question(self):
        payload = self._payload()
        payload["remote_target"]["question"] = "Did 18 patients report fewer vomiting episodes?"
        _records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertIn("G_question_answer_leak", reasons)

    def test_g_answer_must_include_both_coordinated_measures_when_asked_what_was_used(self):
        payload = self._payload()
        payload["remote_target"] = {
            "claim": (
                "Careful examination of the risks and extensive testing of the raw "
                "materials have been used in place of product testing."
            ),
            "answer": "extensive testing of the raw materials",
            "question": "What has been used in place of product testing?",
            "region_hint": "Results",
        }
        _records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertIn("G_answer_incomplete_coordinated_items", reasons)

    def test_complete_coordinated_g_answer_passes(self):
        payload = self._payload()
        payload["remote_target"] = {
            "claim": (
                "Careful examination of the risks and extensive testing of the raw "
                "materials have been used in place of product testing."
            ),
            "answer": (
                "Careful examination of the risks and extensive testing of the raw materials"
            ),
            "question": "What has been used in place of product testing?",
            "region_hint": "Results",
        }
        _records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertNotIn("G_answer_incomplete_coordinated_items", reasons)

    def test_unresolved_reference_patterns_are_rejected(self):
        for question in (
            "Since when has this perception remained unchanged?",
            "What are these pathogens associated with?",
            "What was learned from this case?",
            "Which enzyme is named in the phenomenon?",
            "What happened in the other review?",
            "Which method did the two teas use?",
            "According to what can orientation candidates be defined for these types of models?",
            "When was the first case of this infection diagnosed?",
            "How were their behavioral response times measured?",
        ):
            with self.subTest(question=question):
                self.assertIn(
                    "question_unresolved_reference",
                    MODULE._validate_question(question, []),
                )
        self.assertEqual(
            MODULE._validate_question("Which treatment did participants receive?", []),
            [],
        )
        for question in (
            "What was the grant number under which this work was supported?",
            "What type of system do we propose in this project?",
        ):
            self.assertEqual(MODULE._validate_question(question, []), [])

    def test_trailing_comma_repair_is_limited_and_recorded(self):
        content = '{"text": "literal , } stays", "items": [1, 2,],}'
        payload, diagnostics = MODULE._parse_json_with_diagnostics(content)
        self.assertEqual(payload, {"text": "literal , } stays", "items": [1, 2]})
        self.assertEqual(diagnostics, ["trailing_commas_removed:2"])
        with self.assertRaises(json.JSONDecodeError):
            MODULE._parse_json_with_diagnostics('{"text": "unterminated,}')

    def test_formatting_aliases_are_deterministic_and_narrow(self):
        quoted = MODULE._formatting_answer_aliases('the "Middle East,"')
        self.assertIn("the Middle East", quoted)
        self.assertNotIn("Middle East", quoted)
        percent = MODULE._formatting_answer_aliases(r"approximately $$5\,\%$$ 5 %")
        self.assertIn("approximately 5%", percent)
        self.assertEqual(MODULE._formatting_answer_aliases("vitamin B6"), [])
        self.assertEqual(
            MODULE._response_label("the Middle East", 'the "Middle East,"'),
            "incorrect",
        )
        self.assertEqual(
            MODULE._response_label("the Middle East", 'the "Middle East,"', answer_aliases=quoted),
            "correct",
        )
        self.assertEqual(MODULE._response_label("Middle East", 'the "Middle East,"', answer_aliases=quoted), "incorrect")
        self.assertEqual(MODULE._formatting_answer_aliases("O'Neill"), [])
        self.assertEqual(MODULE._response_label("ONeill", "O'Neill"), "incorrect")

    def test_successor_uses_aliases_frozen_in_the_query(self):
        answer = 'the "Middle East,"'
        query = {
            "answer": answer,
            "answer_aliases": MODULE._formatting_answer_aliases(answer),
        }
        response = {"status": "completed", "response": "the Middle East"}
        self.assertEqual(SUCCESSOR.answer_label(response, query), "correct")
        self.assertEqual(
            SUCCESSOR.answer_label(
                {"status": "completed", "response": "the Middle East"},
                {"answer": answer, "answer_aliases": []},
            ),
            "incorrect",
        )

    def test_stability_config_loads_into_a_fresh_successor_identity(self):
        self.assertEqual(
            SUCCESSOR.DEFAULT_CONFIG,
            ROOT / "configs/v25_shared_g_query_stability.yaml",
        )
        runner = SUCCESSOR.Successor(ROOT / "configs/v25_shared_g_query_stability.yaml")
        self.assertEqual(
            runner.out,
            ROOT / "artifacts/v25/development/shared_g_query_stability_claim_anchor_fresh_100source_20261003",
        )
        self.assertEqual(
            runner.config["experiment_id"],
            "v25_shared_g_query_stability_claim_anchor_fresh_100source_20261003",
        )
        self.assertEqual(runner.config["answer_policy"]["matcher"], "canonical_surface_v2_frozen_format_aliases")
        self.assertNotIn("minimum_initial_false_positive_sources", runner.config["evaluation"])

    def test_retry_prompt_names_failed_gates_and_never_constructs_from_response(self):
        text = "A source statement."
        first = MODULE._build_construction_prompt(text)
        retry = MODULE._build_construction_prompt(
            text,
            previous_attempt={
                "quality_reasons": ["question_unresolved_reference", "e2_answer_not_in_claim"],
                "raw_response": "do not copy answer 230 into the retry prompt",
            },
        )
        self.assertIn(text, first)
        self.assertNotIn("Previous validator feedback", first)
        self.assertIn("e2_answer_not_in_claim, question_unresolved_reference", retry)
        self.assertNotIn("230", retry)

    def test_frozen_query_plan_reuses_one_g_and_pairs_each_anchor(self):
        payload = self._payload()
        records, reasons = MODULE._validate_generation(payload, self._source(payload))
        self.assertEqual(reasons, [])
        source = {
            "source_key": "nfcorpus::fixture",
            "source_hash": "source-hash",
            "dataset": "nfcorpus",
            "group": "KB_Member",
        }
        queries = SUCCESSOR.build_frozen_queries_for_source(source, records, "stability-fixture")
        self.assertEqual(len(queries), 9)
        by_arm = {
            arm: [row for row in queries if row["arm"] == arm]
            for arm in ("initial", "correct_anchor", "remote_only")
        }
        self.assertEqual([len(rows) for rows in by_arm.values()], [3, 3, 3])
        target_question = records["remote_target"]["question"]
        self.assertEqual([row["question"] for row in by_arm["remote_only"]], [target_question] * 3)
        for index, row in enumerate(by_arm["correct_anchor"]):
            self.assertEqual(row["anchor"], records["initial_facts"][index]["answer"])
            self.assertEqual(row["anchor_claim"], records["initial_facts"][index]["claim"])
            self.assertEqual(
                row["question"],
                MODULE._anchored_question(row["anchor_claim"], target_question),
            )
            self.assertEqual(row["answer"], records["remote_target"]["answer"])


if __name__ == "__main__":
    unittest.main()
