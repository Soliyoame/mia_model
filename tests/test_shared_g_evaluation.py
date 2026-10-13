"""来源级统计与完整 mock 流程验收。"""

import json
import unittest
import copy
from unittest.mock import Mock, patch

from test_shared_g_execution import ExecutionFixture
from src.shared_g.artifacts import read_json, read_rows, request_records, write_json_atomic, write_once, read_response_adjudications
from src.shared_g.evaluation import coverage, metrics, paired_macro_auc_delta, report
from src.shared_g.construction import generate, generation_records
from src.shared_g.queries import freeze
from test_shared_g_sources import sample_payload
from src.shared_g.scoring import LEGACY_MATCHER, REPAIRED_MATCHER, repaired_judgment, response_label, answer_judgment, answer_label, gated_queries
from src.shared_g.victim import run_victim
from src.utils.hash import sha256_file, sha256_obj, sha256_text


def response_decision(query, response, label, source_hash="source-hash", review_status="resolved"):
    return {"query_id": query["query_id"], "source_key": query["source_key"], "source_hash": source_hash,
            "query_sha256": sha256_obj(query), "response_sha256": sha256_text(response["response"]),
            "label": label, "review_status": review_status, "reason": "测试用逐项语义复核理由"}


class BoundResponseReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.query = {"query_id": "q", "source_key": "s", "question": "How many subjects?", "answer": "51 subjects"}
        self.response = {"query_id": "q", "source_key": "s", "status": "completed", "response": "51"}
        self.decisions = {"q": response_decision(self.query, self.response, "correct")}

    def test_explicit_review_records_automatic_and_final_labels(self) -> None:
        result = answer_judgment(self.response, self.query, matcher=REPAIRED_MATCHER, adjudications=self.decisions)
        self.assertEqual(result["automatic_label"], "incorrect")
        self.assertEqual(result["label"], "correct")
        self.assertEqual(result["label_source"], "assistant_post_response")
        self.assertEqual(answer_label(self.response, self.query, matcher=REPAIRED_MATCHER), "incorrect")

    def test_review_is_not_reused_for_a_changed_question_or_answer(self) -> None:
        for field in ("question", "answer", "source_key"):
            query = {**self.query, field: "changed"}
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "identity_drift"):
                answer_label(self.response, query, matcher=REPAIRED_MATCHER, adjudications=self.decisions)
        for field in ("response", "query_id", "source_key"):
            response = {**self.response, field: "changed"}
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "identity_drift"):
                answer_label(response, self.query, matcher=REPAIRED_MATCHER, adjudications=self.decisions)

    def test_invalid_response_cannot_be_rescued_by_review(self) -> None:
        for changed in ({"status": "attempt_started"}, {"response": ""}, {"response": "HTTP 503 Service Unavailable"}):
            response = {**self.response, **changed}
            self.assertEqual(answer_label(response, self.query, matcher=REPAIRED_MATCHER,
                                           adjudications=self.decisions), "invalid")

    def test_uncertainty_remains_ambiguous_and_invalid_decisions_fail(self) -> None:
        decision = {**self.decisions["q"], "label": "ambiguous", "review_status": "uncertain"}
        self.assertEqual(answer_label(self.response, self.query, matcher=REPAIRED_MATCHER,
                                       adjudications={"q": decision}), "ambiguous")
        for change in ({"label": "correct"}, {"review_status": "human_pass"}, {"reason": ""}, {"reason": None}, {"label": "invalid"}):
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, "invalid_response_adjudication"):
                answer_label(self.response, self.query, matcher=REPAIRED_MATCHER,
                             adjudications={"q": {**decision, **change}})

    def test_review_can_reject_wrong_object_despite_surface_match(self) -> None:
        query = {**self.query, "question": "What happened to marker A?", "answer": "no change"}
        response = {**self.response, "response": "Marker B showed no change."}
        self.assertEqual(answer_label(response, query, matcher=REPAIRED_MATCHER), "correct")
        decision = response_decision(query, response, "incorrect")
        self.assertEqual(answer_label(response, query, matcher=REPAIRED_MATCHER,
                                       adjudications={"q": decision}), "incorrect")


class RepairedAnswerMatcherTests(unittest.TestCase):
    def label(self, response: str, answer: str, question: str = "") -> str:
        return response_label(response, answer, matcher=REPAIRED_MATCHER, question=question)

    def test_punctuation_keeps_word_boundaries(self) -> None:
        for response, answer in (
            ("The rating scale (RS) improved.", "rating scale (RS)"),
            ("Approximately 42% of participants responded.", "42%"),
            ("A range of 14% to 23% was observed.", "14% to 23%"),
            ("Dose (2, 8, and 24 mg) was fixed.", "Dose (2, 8, and 24 mg)"),
            ("Score: 61.2 + / - 4.3 % of baseline.", "61.2 +/- 4.3%"),
            ("P = 0.0041", "P=0.0041"),
            ("0. 041 (0. 02 - 0. 06)", "0.041 (0.02-0.06)"),
            ("The blue, green and red groups.", "blue, green and red"),
        ):
            with self.subTest(response=response):
                self.assertEqual(self.label(response, answer), "correct")

    def test_valid_thousands_grouping_only(self) -> None:
        for response in ("24 681", "24,681", "24, 681", "24681"):
            self.assertEqual(self.label(response, "24,681"), "correct")
        for response, answer in (("1, 2, 3", "123"), ("6 8", "68"), ("1,23", "123")):
            self.assertEqual(self.label(response, answer), "incorrect")

    def test_numeric_and_word_substrings_are_not_answers(self) -> None:
        for response, answer in (
            ("142", "42"), ("42.7", "42"), ("-42", "42"), ("42%", "42"),
            ("2/42", "42"), ("42/50", "42"), ("42-50", "42"), (">42", "42"),
            ("B42", "42"), ("42nd", "42"), ("42.71", "42.7"),
            ("predrug", "drug"), ("caféine", "café"),
        ):
            with self.subTest(response=response):
                self.assertEqual(self.label(response, answer), "incorrect")

    def test_negative_fact_is_not_an_abstention(self) -> None:
        for response, answer in (
            ("The agents do not suppress growth.", "do not suppress"),
            ("The observations do not support the hypothesis.", "do not support"),
            ("The barrier cannot prevent diffusion.", "cannot prevent"),
            ("There was no significant improvement.", "no significant improvement"),
        ):
            self.assertEqual(self.label(response, answer), "correct")

    def test_refusal_quoting_answer_is_not_correct(self) -> None:
        for response in (
            "The provided text does not contain information about the dosage.",
            "I cannot determine the dosage.", "The dosage is not specified.",
            "There is no information about the dosage.", "I do not know the dosage.",
        ):
            self.assertEqual(self.label(response, "dosage"), "ambiguous")

    def test_direct_negation_outside_answer_is_blocked(self) -> None:
        for response in ("It was not 42 days.", "It didn't last 42 days.", "It never lasted 42 days."):
            self.assertEqual(self.label(response, "42 days"), "ambiguous")
        self.assertEqual(self.label("They did not report withdrawals, but duration was 42 days.", "42 days"), "correct")

    def test_uncertainty_as_question_subject_and_as_refusal(self) -> None:
        self.assertEqual(self.label("The transport mechanism remains unclear.", "transport mechanism",
                                    "What remained unclear?"), "correct")
        self.assertEqual(self.label("The transport mechanism is unclear.", "transport mechanism"), "ambiguous")
        self.assertEqual(self.label("I cannot determine the transport mechanism.", "transport mechanism",
                                    "What remained unclear?"), "ambiguous")
        self.assertEqual(self.label("Unknown.", "transport mechanism"), "ambiguous")

    def test_question_negation_and_other_attributes_do_not_negate_answer(self) -> None:
        for response, answer, question in (
            ("The score was not associated with age.", "age", "What was the score not associated with?"),
            ("The extract had no effect on growth.", "extract", "Which agent had no effect on growth?"),
            ("Healthy adults without known risk factors.", "Healthy adults", "Who was enrolled?"),
            ("It predicts not absorption but available iron.", "available iron", "What does it predict?"),
            ("Neither A nor B has been shown to damage DNA.", "damage DNA", "What have neither A nor B been shown to do?"),
        ):
            self.assertEqual(self.label(response, answer, question), "correct")
        self.assertEqual(self.label("It was not aspirin.", "aspirin", "Which drug did not reduce fever?"), "ambiguous")

    def test_status_and_api_errors_remain_invalid(self) -> None:
        for text in ("", "API error: 503 service unavailable"):
            self.assertEqual(self.label(text, "503"), "invalid")
        self.assertEqual(response_label("42", "42", "attempt_started", matcher=REPAIRED_MATCHER), "invalid")

    def test_no_response_dependent_alias_or_semantic_relaxation(self) -> None:
        self.assertEqual(self.label("One month.", "1 month"), "incorrect")
        self.assertEqual(self.label("drug A", "drug A and drug B"), "incorrect")
        self.assertEqual(self.label("45", "45.3"), "incorrect")
        self.assertEqual(self.label("GFD", "gluten-free diet"), "incorrect")
        self.assertEqual(response_label("GFD", "gluten-free diet", answer_aliases=["GFD"],
                                        matcher=REPAIRED_MATCHER), "correct")

    def test_legacy_default_and_explicit_version_are_preserved(self) -> None:
        self.assertEqual(response_label("The agents do not suppress growth.", "do not suppress"), "ambiguous")
        self.assertEqual(response_label("A scale (RS) improved.", "scale (RS)", matcher=LEGACY_MATCHER), "incorrect")
        with self.assertRaisesRegex(ValueError, "unknown_answer_matcher"):
            response_label("42", "42", matcher="typo")
        self.assertEqual(repaired_judgment("The dose is unknown.", "dose")["reason"], "uncertainty_outside_answer")


class SharedGEvaluationTests(ExecutionFixture):
    def install_response_reviews(self, decisions) -> None:
        data = copy.deepcopy(self.config.data)
        data["answer_policy"]["response_adjudications"] = "response_adjudications.json"
        self.reload_config(data)
        packet = {"reviewer_type": "assistant_post_response", "independent_human_annotation": False,
                  "scope": "reviewed_responses_only", "decisions": decisions}
        write_json_atomic(self.store.path("response_adjudications.json"), packet)
        run = read_json(self.store.path("run_config.json"))
        run.update(config=data, config_sha256=sha256_file(self.config.path), status="scoring_corrected_after_initial",
                   scoring_correction={"kind": "assistant_response_adjudication"})
        run["frozen_artifacts"]["response_adjudications.json"] = sha256_file(self.store.path("response_adjudications.json"))
        write_json_atomic(self.store.path("run_config.json"), run)

    def test_response_review_drives_gate_followup_score_and_report(self) -> None:
        data = copy.deepcopy(self.config.data)
        data["answer_policy"]["matcher"] = REPAIRED_MATCHER
        self.reload_config(data)
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        client = self.victim_client()
        exact_answer = client.generate_with_metadata.side_effect
        def respond(prompt, **kwargs):
            result = exact_answer(prompt, **kwargs)
            value = {"230": "two hundred and thirty", "vitamin B6": "The other group received vitamin B6."}.get(result.content)
            return self.result(value, "victim") if value else result
        client.generate_with_metadata.side_effect = respond
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            run_victim(self.config, self.store, "nfcorpus", False)
        queries = {q["query_id"]: q for q in read_rows(self.store.path("query_plan.jsonl")) if q["dataset"] == "nfcorpus"}
        sources = {s["source_key"]: s for s in read_rows(self.store.path("source_manifest.jsonl"))}
        initial = request_records(self.store.path("initial_responses.jsonl", "nfcorpus"))
        decisions = [response_decision(queries[r["query_id"]], r, "correct" if r["slot_index"] == 0 else "incorrect",
                                      sources[r["source_key"]]["source_hash"]) for r in initial if r["slot_index"] in (0, 1)]
        self.install_response_reviews(decisions)
        loaded = read_response_adjudications(self.store)
        expected = gated_queries(list(queries.values()), initial, matcher=REPAIRED_MATCHER, adjudications=loaded)
        self.assertEqual({q["slot_index"] for q in expected}, {0, 2})
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            self.assertEqual(run_victim(self.config, self.store, "nfcorpus", True)["new_calls"], 16)
            self.assertEqual(run_victim(self.config, self.store, "nfcorpus", False)["new_calls"], 0)
        followup = request_records(self.store.path("followup_responses.jsonl", "nfcorpus"))[0]
        decisions.append(response_decision(queries[followup["query_id"]], followup, "ambiguous",
                                           sources[followup["source_key"]]["source_hash"], "uncertain"))
        self.install_response_reviews(decisions)
        output = report(self.config, self.store, "nfcorpus")
        self.assertEqual(output["response_label_sources"]["initial"]["changed_from_automatic"], 8)
        self.assertEqual(output["response_label_sources"]["initial"]["automatic"], 4)
        self.assertEqual(output["response_label_sources"]["followup"]["assistant_post_response"], 1)
        self.assertEqual(output["response_label_sources"]["followup"]["unresolved"], 1)
        scores = read_rows(self.store.path("scores.jsonl", "nfcorpus"))
        self.assertEqual(sum(s[followup["arm"]] for s in scores), 15)
        self.assertEqual(output, report(self.config, self.store, "nfcorpus"))

    def test_response_review_requires_bound_file_and_source(self) -> None:
        data = copy.deepcopy(self.config.data)
        data["answer_policy"]["matcher"] = REPAIRED_MATCHER
        self.reload_config(data)
        self.freeze_all()
        self.complete_cell("nfcorpus")
        query = next(q for q in read_rows(self.store.path("query_plan.jsonl")) if q["dataset"] == "nfcorpus")
        response = next(r for r in request_records(self.store.path("initial_responses.jsonl", "nfcorpus")) if r["query_id"] == query["query_id"])
        self.install_response_reviews([response_decision(query, response, "correct", "wrong-source-hash")])
        with self.assertRaisesRegex(RuntimeError, "source_or_response_drift"):
            read_response_adjudications(self.store)
        self.store.path("response_adjudications.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "not_bound"):
            read_response_adjudications(self.store)

    def test_repaired_matcher_is_used_by_gate_followup_and_report(self) -> None:
        data = self.config.data
        data["answer_policy"]["matcher"] = REPAIRED_MATCHER
        self.reload_config(data)
        self.freeze_all()
        run = read_json(self.store.path("run_config.json"))
        run["status"] = "scoring_corrected_after_initial"
        run["scoring_correction"] = {"status": "post_response_scoring_correction"}
        write_json_atomic(self.store.path("run_config.json"), run)
        for dataset in self.config.datasets:
            self.install_retrieval(dataset)
            client = self.victim_client()
            exact_answer = client.generate_with_metadata.side_effect
            def respond(prompt, **kwargs):
                result = exact_answer(prompt, **kwargs)
                if result.content in {"12 weeks", "18"}:
                    return self.result(f"It was not {result.content}.", "victim")
                return result
            client.generate_with_metadata.side_effect = respond
            with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
                self.assertEqual(run_victim(self.config, self.store, dataset, False)["new_calls"], 12)
                self.assertEqual(run_victim(self.config, self.store, dataset, True)["new_calls"], 16)
                self.assertEqual(run_victim(self.config, self.store, dataset, True)["new_calls"], 0)
        output = report(self.config, self.store)
        self.assertFalse(output["interpretation"]["no_posthoc_tuning"])
        self.assertEqual(output["status"], "scoring_corrected_evaluation_complete")
        self.assertEqual(output["answer_policy"]["matcher"], REPAIRED_MATCHER)
        for dataset in self.config.datasets:
            self.assertEqual(output["per_dataset"][dataset]["gate_audit"]["expected_followups"], 16)
            self.assertTrue(all(row["correct_anchor"] == 2 for row in read_rows(self.store.path("scores.jsonl", dataset))))

    def test_complete_mock_workflow_and_idempotent_report(self) -> None:
        self.freeze_all()
        for dataset in self.config.datasets:
            self.assertEqual(self.complete_cell(dataset).generate_with_metadata.call_count, 36)
        output = report(self.config, self.store)
        self.assertEqual(output["status"], "formal_evaluation_complete")
        self.assertEqual(output["qualified_source_count"], 12)
        self.assertEqual(output["candidate_source_count"], 12)
        self.assertEqual(output["qualification"]["nfcorpus"]["semantic_accepted"], 4)
        self.assertEqual(output["query_usable_sources"], 12)
        self.assertEqual(output["cost"]["construction_calls"], 12)
        self.assertEqual(output["cost"]["victim_calls"], 108)
        self.assertEqual(output["macro_auc"]["correct_anchor"]["estimate"], 0.5)
        self.assertEqual(output["paired_macro_auc_deltas"]["correct_anchor_vs_local_only"]["ci95"], [0.0, 0.0])
        self.assertEqual(output, report(self.config, self.store))
        json.dumps(output, allow_nan=False)

    def test_macro_is_equal_weight_and_preserves_pairing(self) -> None:
        def pair(prefix, good):
            return [{"source_key": prefix + "m", "group": "KB_Member", "correct_anchor": int(good), "local_only": 0.5},
                    {"source_key": prefix + "n", "group": "True_Non_Member", "correct_anchor": int(not good), "local_only": 0.5}]
        grouped = {"small": pair("a", True), "large": [row for i in range(20) for row in pair(str(i), False)]}
        delta = paired_macro_auc_delta(grouped, "correct_anchor", "local_only", 30, 45)
        self.assertEqual(delta["estimate"], 0.0)
        self.assertEqual(delta["ci95"], [0.0, 0.0])
        self.assertEqual(delta["common_sources"], 42)

    def test_missing_class_makes_primary_unavailable(self) -> None:
        grouped = {"one": [{"source_key": "m", "group": "KB_Member", "correct_anchor": 5, "local_only": 3}]}
        value = paired_macro_auc_delta(grouped, "correct_anchor", "local_only", 20, 45)
        self.assertIsNone(value["estimate"])
        self.assertEqual(value["bootstrap"], 0)

    def test_zero_false_positives_have_positive_confidence_upper_bound(self) -> None:
        rows = [{"source_key": str(i), "group": "KB_Member" if i < 10 else "True_Non_Member",
                 "local_only": 3 if i < 10 else 0, "correct_anchor": 6 if i < 10 else 0,
                 "remote_only": 6 if i < 10 else 0} for i in range(20)]
        result = metrics(self.config, rows)
        fixed = result["correct_anchor"]["fixed_cutoff"]
        self.assertEqual(fixed["fpr"], 0)
        self.assertGreater(fixed["fpr_ci95"][1], 0)
        self.assertEqual(fixed["cutoff"], 2)
        self.assertFalse(result["correct_anchor"]["low_fpr"]["0.01"]["interpolation"])

    def test_cohort_coverage_does_not_create_fake_auc_scores(self) -> None:
        sources = [{"source_key": str(i), "group": "KB_Member"} for i in range(4)]
        usable = [{"source_key": "0", "group": "KB_Member", "local_only": 3, "correct_anchor": 6, "remote_only": 6}]
        generations = {str(i): {"status": "passed" if i == 0 else "failed_quality_gate"} for i in range(4)}
        value = coverage(sources, usable, generations, 2)["KB_Member"]
        self.assertEqual(value["cohort_alert_rate"]["correct_anchor"], 0.25)
        self.assertEqual(value["coverage"], 0.25)
        self.assertEqual(value["abstained"], 3)
        self.assertEqual(len(usable), 1)

    def test_report_includes_discarded_candidate_cost_without_membership(self) -> None:
        self.add_candidate("nfcorpus", 4)
        self.construct_all()
        rejected = next(iter(generation_records(self.store)))
        self.write_review({rejected: "答案不能回答问题"})
        client = Mock()
        client.chat_with_metadata.return_value = self.result(json.dumps(sample_payload()))
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            generate(self.config, self.store, "nfcorpus")
        self.write_review({rejected: "答案不能回答问题"})
        freeze(self.config, self.store)
        for dataset in self.config.datasets:
            self.complete_cell(dataset)
        output = report(self.config, self.store)
        self.assertEqual(output["qualified_source_count"], 12)
        self.assertEqual(output["cost"]["construction_calls"], 13)
        self.assertEqual(output["per_dataset"]["nfcorpus"]["cost"]["construction_calls"], 5)
        self.assertEqual(output["qualification"]["nfcorpus"]["semantic_rejected"], 1)
        self.assertNotIn(rejected, {row["source_key"] for row in read_rows(self.store.path("source_manifest.jsonl"))})

    def test_report_is_not_available_before_all_responses_complete(self) -> None:
        self.freeze_all()
        with self.assertRaises(RuntimeError):
            report(self.config, self.store)
        self.assertFalse(self.store.path("report.json").exists())

    def test_completed_report_cannot_be_overwritten(self) -> None:
        self.freeze_all()
        write_once(self.store.path("report.json"), {"result": "old"})
        with self.assertRaisesRegex(RuntimeError, "refuse_artifact_overwrite"):
            write_once(self.store.path("report.json"), {"result": "different"})


class BinaryAnswerJudgmentTests(unittest.TestCase):
    """新模块的反例与定案边界；旧测试及旧接口的期望保持不变。"""

    def judge(self, response: str, answer: str, question: str = "What was the duration?", claim: str = "") -> dict:
        from src.evaluation.answer_judgment import judge_answer
        query = {"query_id": "q", "source_key": "s", "question": question, "answer": answer, "claim": claim}
        observed = {"query_id": "q", "source_key": "s", "status": "completed", "response": response}
        return judge_answer(observed, query)

    def test_number_words_decimal_and_scientific_notation(self) -> None:
        cases = [
            ("19", "Nineteen", "How many studies were included?"),
            ("One hundred and five", "105", "How many patients were enrolled?"),
            ("2", "two spatial dimensions", "Along how many spatial dimensions were pixels predicted?"),
            ("Five", "five consecutive frame", "For how many consecutive frames must eyes be closed?"),
            ("3.52 × 10^5", "352000", "How many infections were projected?"),
            ("3.52e5", "352,000", "How many infections were projected?"),
            ("negative zero point five", "-0.5", "What was the coefficient?"),
            ("12.44", "12·44", "What was the odds ratio?"),
            ("1,300", "1300", "How many participants were included?"),
            ("0. 05 mg / kg twice daily", "0.05 mg/kg twice daily", "What was the dose?"),
        ]
        for response, answer, question in cases:
            with self.subTest(response=response, answer=answer):
                result = self.judge(response, answer, question)
                self.assertEqual((result["label"], result["status"], result["score"]), ("correct", "resolved", 1))

    def test_unit_conversion_is_exact_and_dimension_aware(self) -> None:
        for response, answer in (
            ("48 hours", "2 days"), ("1000 mg", "1 g"), ("0.5 liters", "500 mL"),
            ("1 m^2", "10000 cm²"), ("10000 cm<sup>2</sup>", "1 m(2)"),
            ("50 ug/kg twice daily", "0.05 mg/kg twice daily"), ("273.15 K", "0 °C"),
            ("32 °F", "0 degrees Celsius"), ("24 months", "2 years"),
        ):
            with self.subTest(response=response, answer=answer):
                self.assertEqual(self.judge(response, answer)["label"], "correct")

    def test_units_can_be_omitted_only_when_question_specifies_them(self) -> None:
        self.assertEqual(self.judge("42", "42 days", "What was the duration in days?")["label"], "correct")
        self.assertEqual(self.judge("42", "42%", "What percentage responded?")["label"], "correct")
        self.assertEqual(self.judge("42", "42 days")["status"], "needs_review")
        self.assertNotEqual(self.judge("0.42", "42%", "What percentage responded?")["label"], "correct")

    def test_months_are_not_thirty_days(self) -> None:
        result = self.judge("30 days", "1 month")
        self.assertEqual((result["status"], result["score"]), ("needs_review", None))
        self.assertEqual(result["reason"], "calendar_conversion_undefined")

    def test_wrong_values_units_and_numeric_boundaries_do_not_pass(self) -> None:
        for response, answer in (
            ("142", "42"), ("42.7", "42"), ("-42", "42"), ("42%", "42"),
            ("42/50", "42"), ("42-50", "42"), (">42", "42"), ("B42", "42"),
            ("2 mg", "2 mL"), ("1 m", "1 M"), ("1 Mg", "1 mg"), ("1 MG", "1 mg"),
            ("12.45", "12.44"), ("one two", "12"), ("1, 2, 3", "123"),
            ("0.05 mg/kg", "0.05 mg/kg twice daily"),
        ):
            with self.subTest(response=response, answer=answer):
                self.assertNotEqual(self.judge(response, answer, "What was the result?")["label"], "correct")
        self.assertEqual(self.judge("8 days", "42 days")["label"], "not_correct")
        self.assertEqual(self.judge("2 mg", "2 mL", "What was the dose?")["reason"], "wrong_unit")

    def test_ranges_comparators_and_spreads_preserve_information(self) -> None:
        for response, answer in (
            ("30 to 31 days", "30–31 days"), ("12%-38%", "between 12% and 38%"),
            ("at least 1 g", ">=1000 mg"), ("less than 42 days", "<42 days"),
            ("61.2 +/- 4.3%", "61.2 ± 4.3%"), ("[1, 5]", "1 to 5"),
            ("1 day to 48 hours", "24 to 48 hours"),
        ):
            with self.subTest(response=response, answer=answer):
                self.assertEqual(self.judge(response, answer, "What was the reported range?")["label"], "correct")
        for response, answer in ((">42", ">=42"), ("42", "42-50"), ("[1,5)", "[1,5]"), ("61.2%", "61.2 ± 4.3%")):
            self.assertNotEqual(self.judge(response, answer, "What was the result?")["label"], "correct")

    def test_abbreviation_requires_frozen_definition_and_keeps_modifiers(self) -> None:
        for response, answer, claim in (
            ("GFD", "gluten-free diet (GFD)", "The diet was a gluten-free diet (GFD)."),
            ("GFD", "gluten-free diet", "The gluten-free diet (GFD) was used."),
            ("gluten-free diet", "GFD", "The gluten-free diet (GFD) was used."),
            ("term frequency inverse document frequency", "term frequency-inverse document frequency (TF-IDF)", ""),
        ):
            with self.subTest(response=response, answer=answer):
                self.assertEqual(self.judge(response, answer, "Which method was used?", claim)["label"], "correct")
        self.assertEqual(self.judge("GFD", "gluten-free diet", "Which diet was used?")["status"], "needs_review")
        self.assertNotEqual(self.judge("DRA", "rectangular dielectric resonator antenna (DRA)", "Which antenna was used?")["label"], "correct")

    def test_arbitrary_aliases_are_not_semantic_evidence(self) -> None:
        from src.evaluation.answer_judgment import judge_answer
        query = {"query_id": "q", "source_key": "s", "question": "Which diet was used?", "answer": "gluten-free diet", "answer_aliases": ["GFD"]}
        response = {"query_id": "q", "source_key": "s", "status": "completed", "response": "GFD"}
        self.assertEqual(judge_answer(response, query)["status"], "needs_review")

    def test_complete_lists_allow_only_unordered_permutations(self) -> None:
        answer = "aspirin, ibuprofen, and naproxen"
        self.assertEqual(self.judge("naproxen, aspirin and ibuprofen", answer, "List all required drugs.")["label"], "correct")
        self.assertEqual(self.judge("aspirin and naproxen", answer, "List all required drugs.")["reason"], "missing_required_item")
        self.assertEqual(self.judge("naproxen, aspirin and ibuprofen", answer, "List all required drugs in order.")["label"], "not_correct")
        self.assertNotEqual(self.judge("aspirin, ibuprofen, naproxen and Drug Z", answer, "List all required drugs.")["label"], "correct")
        self.assertEqual(self.judge("ibuprofen and ibuprofen", answer, "List all required drugs.")["label"], "not_correct")

    def test_conjunction_inside_a_name_does_not_create_a_list(self) -> None:
        result = self.judge("Development and Research", "Research and Development", "What was the department called?")
        self.assertEqual(result["status"], "needs_review")

    def test_object_mismatch_is_not_rescued_by_a_matching_span(self) -> None:
        result = self.judge("Marker B showed no change.", "no change", "What happened to marker A?", "Marker A showed no change.")
        self.assertEqual((result["label"], result["reason"]), ("not_correct", "wrong_object"))
        self.assertEqual(self.judge("Marker A showed no change.", "no change", "What happened to marker A?", "Marker A showed no change.")["label"], "correct")
        self.assertNotEqual(self.judge("The varistor was flexible.", "flexible", "How flexible were the ECG electrodes?", "The ECG electrodes were flexible.")["label"], "correct")

    def test_negation_and_retracted_answers_do_not_pass(self) -> None:
        self.assertEqual(self.judge("It was not 42 days.", "42 days")["label"], "not_correct")
        self.assertEqual(self.judge("It was not aspirin.", "aspirin", "Which drug did not reduce fever?")["label"], "not_correct")
        self.assertEqual(self.judge("change", "no change", "What happened?")["reason"], "negation_reversed")
        self.assertEqual(self.judge("Yes", "No", "Did it work?")["label"], "not_correct")
        result = self.judge("42 days. Actually, 8 days.", "42 days")
        self.assertEqual((result["label"], result["reason"]), ("not_correct", "answer_retracted"))
        self.assertEqual(self.judge("42 days. 8 days.", "42 days")["status"], "needs_review")
        self.assertNotEqual(self.judge("42 days. I retract that answer.", "42 days")["label"], "correct")

    def test_genuine_refusal_is_resolved_zero_with_reason(self) -> None:
        for text in (
            "Unknown.", "I cannot determine the duration.", "The duration is not specified.",
            "The provided text does not describe the duration.", "There is no information about the duration.",
            "This document does not contain the answer to your question.", "I cannot list the required drugs.",
            "Cannot determine the duration.",
        ):
            with self.subTest(text=text):
                result = self.judge(text, "42 days")
                self.assertEqual((result["label"], result["status"], result["score"], result["reason"]),
                                 ("not_correct", "resolved", 0, "refused"))

    def test_no_in_names_and_negative_facts_are_not_refusals(self) -> None:
        for response, answer, question, claim in (
            ("No Free Lunch", "No Free Lunch", "Which theorem was cited?", "The No Free Lunch theorem was cited."),
            ("Little to no manual effort.", "little to no manual effort", "How much effort was required?", ""),
            ("The test showed no equivocal results.", "no equivocal results", "What did the test show?", "The test showed no equivocal results."),
            ("The transport mechanism remains unclear.", "transport mechanism", "What remains unclear?", "The transport mechanism remains unclear."),
            ("The study did not include controls.", "did not include controls", "What did the study omit?", "The study did not include controls."),
        ):
            with self.subTest(response=response):
                result = self.judge(response, answer, question, claim)
                self.assertEqual(result["label"], "correct")
                self.assertNotEqual(result["reason"], "refused")

    def test_other_attributes_unknown_do_not_cancel_target_answer(self) -> None:
        result = self.judge("42 days. The author is unknown.", "42 days")
        self.assertEqual(result["label"], "correct")
        self.assertEqual(len(result["evidence"]["supplementary_text"]), 1)
        self.assertNotEqual(self.judge("The author is unknown.", "42 days")["reason"], "refused")

    def test_ambiguous_relation_and_reference_conflict_require_review(self) -> None:
        for response, answer, question, claim in (
            ("Perhaps 42 days.", "42 days", "What was the duration?", ""),
            ("cobalamin", "vitamin B12", "Which treatment was used?", ""),
            ("aspirin", "aspirin", "Which treatment was used?", "It was not aspirin."),
            ("Blue", "blue", "Interpret this.", ""),
        ):
            with self.subTest(response=response):
                result = self.judge(response, answer, question, claim)
                self.assertEqual((result["label"], result["status"], result["score"]), (None, "needs_review", None))

    def test_anchor_is_not_a_source_of_an_omitted_target_unit(self) -> None:
        from src.evaluation.answer_judgment import judge_answer
        from src.shared_g.queries import anchored_question
        anchor = "The dose was expressed in mg."
        query = {"query_id": "q", "source_key": "s", "question": anchored_question(anchor, "What was the duration?"),
                 "anchor_claim": anchor, "answer": "42 days"}
        response = {"query_id": "q", "source_key": "s", "status": "completed", "response": "42"}
        result = judge_answer(response, query)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["evidence"]["question"], "What was the duration?")

    def test_known_question_forms_do_not_require_semantic_guessing(self) -> None:
        for response, answer, question, claim in (
            ("7", "seven men", "How many men participated in the study?", "Subjects were seven men."),
            ("Humans", "humans", "Whom did the model beat?", "The model beat humans."),
            ("42", "42", "According to the study, what was the total?", "The total was 42."),
            ("Every instant of time", "at every instant of time", "When were frames captured?", "Frames were captured at every instant of time."),
            ("variational inference", "in variational inference", "In what area was it optimized?", "It was optimized in variational inference."),
            ("A visual analog scale was used to assess appetite.", "a visual analog scale", "What was used to assess appetite?", "Appetite was assessed using a visual analog scale."),
            ("explicit and implicit", "explicit (e.g., equations) and implicit (e.g., solutions) supervision signals", "What types of supervision signals does the method use?", "The method uses explicit (e.g., equations) and implicit (e.g., solutions) supervision signals."),
        ):
            with self.subTest(response=response):
                self.assertEqual(self.judge(response, answer, question, claim)["label"], "correct")
        self.assertEqual(self.judge("8", "seven men", "How many men participated in the study?")["label"], "not_correct")

    def test_target_change_is_not_hidden_by_an_author_supplement(self) -> None:
        self.assertNotEqual(self.judge("42 days. The author says it was 8 days.", "42 days")["label"], "correct")
        self.assertEqual(self.judge("I cannot determine the author, but the duration was 42 days.", "42 days")["label"], "correct")

    def test_other_object_supplement_does_not_override_an_explicit_target_answer(self) -> None:
        result = self.judge("Marker A showed no change. Marker B increased.", "no change", "What happened to marker A?", "Marker A showed no change.")
        self.assertEqual(result["label"], "correct")
        self.assertEqual(result["evidence"]["supplementary_text"], ["Marker B increased."])

    def test_opposite_direction_and_numeric_reference_conflict(self) -> None:
        self.assertEqual(self.judge("increased", "decreased", "What happened?")["label"], "not_correct")
        self.assertEqual(self.judge("Marker A increased.", "decreased", "What happened to marker A?", "Marker A decreased.")["reason"], "wrong_direction")
        self.assertEqual(self.judge("42 days", "42 days", "What was the duration?", "The duration was 8 days.")["status"], "needs_review")
        self.assertEqual(self.judge("1000 mg", "1 g", "What was the dose?", "The dose was 1000 mg.")["label"], "correct")

    def test_p_value_comparator_is_preserved(self) -> None:
        self.assertEqual(self.judge("less than 0.001", "P<0.001", "What was the p-value?")["label"], "correct")
        self.assertEqual(self.judge("1e-3", "P=0.001", "What was the p-value?")["label"], "correct")
        self.assertNotEqual(self.judge("0.001", "P<0.001", "What was the p-value?")["label"], "correct")
        self.assertNotEqual(self.judge("1e99999999", "1", "What was the result?")["label"], "correct")

    def test_question_about_missing_information_is_not_itself_refusal(self) -> None:
        result = self.judge("The document does not provide dosage information.", "dosage information",
                            "What information does the document not provide?", "The document does not provide dosage information.")
        self.assertEqual(result["label"], "correct")
        self.assertNotEqual(result["reason"], "refused")
        result = self.judge("I cannot determine what is missing.", "dosage information",
                            "What information does the document not provide?", "The document does not provide dosage information.")
        self.assertEqual(result["reason"], "refused")

    def test_refusal_word_as_reference_and_other_attribute_are_not_forced_zero(self) -> None:
        result = self.judge("Unknown", "unknown", "Which category was selected?", "The selected category was unknown.")
        self.assertEqual((result["status"], result["score"]), ("needs_review", None))
        result = self.judge("42 years. The author is unknown.", "42 years", "How long did the author live?")
        self.assertEqual(result["label"], "correct")

    def test_age_format_and_unknown_numeric_unit_are_not_name_matching(self) -> None:
        self.assertEqual(self.judge("57 years old", "57-y-old", "How old was the man?")["label"], "correct")
        self.assertEqual(self.judge("57 months old", "57-y-old", "How old was the man?")["label"], "not_correct")
        self.assertEqual(self.judge("42 mg", "42 MG", "What was the dose of drug A?")["status"], "needs_review")


class BinaryAnswerReviewAndGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.query = {"query_id": "q", "source_key": "s", "question": "What was the duration?", "answer": "42 days", "arm": "initial", "slot_index": 0}
        self.response = {"query_id": "q", "source_key": "s", "status": "completed", "response": "six weeks"}

    def review(self, **changes) -> dict:
        result = {"query_id": "q", "source_key": "s", "source_hash": "hash", "query_sha256": sha256_obj(self.query),
                  "response_sha256": sha256_text(self.response["response"]), "label": "correct", "status": "resolved",
                  "reason": "target_equivalent", "evidence": ["six weeks = 42 days"],
                  "reviewer_type": "assistant", "independent_human_annotation": False}
        return {**result, **changes}

    def plan(self) -> list[dict]:
        return [self.query, *[{**self.query, "query_id": arm, "arm": arm} for arm in ("correct_anchor", "remote_only")]]

    def test_review_preserves_automatic_result_and_provenance(self) -> None:
        from src.evaluation.answer_judgment import judge_answer
        result = judge_answer(self.response, self.query, review=self.review(), source_hash="hash")
        self.assertEqual(result["label_source"], "assistant_review")
        self.assertEqual(result["automatic"]["label_source"], "rule")
        self.assertFalse(result["independent_human_annotation"])
        self.assertEqual(result["score"], 1)

    def test_review_requires_exact_source_query_and_response_binding(self) -> None:
        from src.evaluation.answer_judgment import judge_answer
        for field in ("query_id", "source_key", "source_hash", "query_sha256", "response_sha256"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "identity_drift"):
                judge_answer(self.response, self.query, review=self.review(**{field: "wrong"}), source_hash="hash")
        with self.assertRaisesRegex(ValueError, "identity_drift"):
            judge_answer(self.response, self.query, review=self.review())
        for field in ("question", "answer", "claim", "answer_aliases", "group"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "identity_drift"):
                judge_answer(self.response, {**self.query, field: "changed"}, review=self.review(), source_hash="hash")

    def test_disputed_review_remains_pending_and_illegal_combinations_fail(self) -> None:
        from src.evaluation.answer_judgment import judge_answer
        review = self.review(label=None, status="needs_review", reason="reference_uncertain")
        result = judge_answer(self.response, self.query, review=review, source_hash="hash")
        self.assertEqual((result["label"], result["status"], result["score"]), (None, "needs_review", None))
        for changes in ({"label": "ambiguous"}, {"status": "invalid"}, {"status": "needs_review"}, {"label": None},
                        {"reason": "refused"}, {"reason": ""}, {"evidence": []}, {"reviewer_type": "human"}, {"independent_human_annotation": True}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "invalid_answer_review"):
                judge_answer(self.response, self.query, review=self.review(**changes), source_hash="hash")

    def test_invalid_cannot_be_rescued_by_any_review(self) -> None:
        from src.evaluation.answer_judgment import judge_answer
        for changes in ({"status": "failed"}, {"error": "timeout"}, {"response": ""}, {"response": None},
                        {"response": "HTTP 503 Service Unavailable"}, {"response": '{"error":{"code":503}}'},
                        {"query_id": "other"}, {"source_key": "other"}, {"response_sha256": "wrong"}, {"source_hash": "other"}):
            with self.subTest(changes=changes):
                result = judge_answer({**self.response, **changes}, self.query, review=self.review(), source_hash="hash")
                self.assertEqual((result["label"], result["status"], result["score"]), (None, "invalid", None))
                self.assertEqual(result["label_source"], "rule")

    def test_unresolved_or_invalid_blocks_final_scores_and_gate(self) -> None:
        from src.evaluation.answer_judgment import IncompleteJudgmentError, resolved_scores, gated_queries as binary_gate
        for text in ("Maybe six weeks.", "", "HTTP 503 Service Unavailable"):
            observed = {**self.response, "response": text}
            for action in (lambda: resolved_scores([self.query], [observed]), lambda: binary_gate(self.plan(), [observed])):
                with self.subTest(text=text), self.assertRaises(IncompleteJudgmentError) as caught:
                    action()
                self.assertEqual(caught.exception.unresolved[0]["query_id"], "q")
                self.assertFalse(hasattr(caught.exception, "scores"))

    def test_refusal_scores_zero_and_does_not_trigger(self) -> None:
        from src.evaluation.answer_judgment import resolved_scores, gated_queries as binary_gate
        response = {**self.response, "response": "I cannot determine the duration."}
        self.assertEqual(resolved_scores([self.query], [response]), {"q": 0})
        self.assertEqual(binary_gate(self.plan(), [response]), [])
        self.assertEqual({q["arm"] for q in binary_gate(self.plan(), [self.response])}, {"correct_anchor", "remote_only"})

    def test_bound_dispute_blocks_gate_even_if_rule_was_correct(self) -> None:
        from src.evaluation.answer_judgment import IncompleteJudgmentError, gated_queries as binary_gate
        reviews = {"q": self.review(label=None, status="needs_review", reason="reference_uncertain")}
        with self.assertRaises(IncompleteJudgmentError):
            binary_gate(self.plan(), [self.response], reviews=reviews, source_hashes={"s": "hash"})

    def test_missing_duplicate_extra_and_incomplete_gate_plans_fail(self) -> None:
        from src.evaluation.answer_judgment import resolved_scores, gated_queries as binary_gate
        for responses in ([], [self.response, self.response], [self.response, {**self.response, "query_id": "extra"}]):
            with self.subTest(responses=len(responses)), self.assertRaises(ValueError):
                resolved_scores([self.query], responses)
        with self.assertRaises(ValueError):
            resolved_scores([self.query, self.query], [self.response])
        with self.assertRaises(ValueError):
            resolved_scores([self.query], [self.response], reviews={"extra": self.review()})
        for plan in (self.plan()[:-1], self.plan() + [self.plan()[1]],
                     self.plan() + [{**self.query, "query_id": "extra"}]):
            with self.subTest(plan=len(plan)), self.assertRaises(ValueError):
                binary_gate(plan, [self.response])

    def test_membership_is_not_used_by_automatic_judgment(self) -> None:
        from src.evaluation.answer_judgment import judge_answer
        first = judge_answer(self.response, {**self.query, "group": "KB_Member"})
        second = judge_answer(self.response, {**self.query, "group": "True_Non_Member"})
        self.assertEqual(first, second)


class AutomaticNLIJudgmentTests(unittest.TestCase):
    class Backend:
        identity = {"model_id": "mock_nli", "revision": "test"}

        def __init__(self, probabilities=None):
            self.values = probabilities or {"entailment": 0.94, "neutral": 0.04, "contradiction": 0.02}
            self.pairs = []

        def windows(self, question, response, hypothesis):
            return [{"premise": f"Question: {question}\nAnswer: {response}", "hypothesis": hypothesis,
                     "char_start": 0, "char_end": len(response), "input_tokens": 20}]

        def probabilities(self, pairs):
            self.pairs.extend(pairs)
            return [dict(self.values) for _ in pairs]

    def item(self, text="The therapy lowered the chance of recurrence.", answer="decreased",
             question="What happened to recurrence risk?", claim="The recurrence risk decreased."):
        query = {"query_id": "q", "source_key": "s", "dataset": "nfcorpus", "slot_index": 0,
                 "arm": "initial", "question": question, "answer": answer, "claim": claim}
        response = {"query_id": "q", "source_key": "s", "status": "completed", "response": text}
        return {"query": query, "response": response}

    def judge(self, item, backend=None, **kwargs):
        from src.evaluation.answer_judgment import judge_answers_auto, NLIConfig
        return judge_answers_auto([item], config=NLIConfig(classify_refusals=False, **kwargs),
                                  backend=backend or self.Backend())[0]

    def test_equivalent_numbers_units_and_full_lists_do_not_use_model(self) -> None:
        for text, answer, question, claim in (
            ("six weeks", "42 days", "What was the duration?", ""),
            ("1e-3", "0.001", "What was the p-value?", ""),
            ("0.75 grams", "750 mg", "What was the dose?", ""),
            ("minus five", "-5", "What was the score?", ""),
            ("73", "seventy-three volunteers", "How many volunteers completed the trial?", ""),
            ("GFD", "gluten-free diet", "Which diet was used?", "The gluten-free diet (GFD) was used."),
            ("copper, zinc and iron", "iron, zinc, and copper", "List all measured minerals.", ""),
            ("No Free Lunch", "No Free Lunch", "Which theorem was cited?", "The No Free Lunch theorem was cited."),
        ):
            with self.subTest(text=text):
                backend = self.Backend()
                result = self.judge(self.item(text, answer, question, claim), backend)
                self.assertEqual((result["label"], result["label_source"], result["status"]), ("correct", "rule", "resolved"))
                self.assertEqual(backend.pairs, [])

    def test_wrong_values_units_bounds_and_missing_list_items_are_rules(self) -> None:
        for text, answer, question in (
            ("750 g", "750 mg", "What was the dose?"),
            ("37", "73", "How many volunteers completed the trial?"),
            ("iron and zinc", "iron, zinc and copper", "List all measured minerals."),
            ("zinc, iron and copper", "iron, zinc and copper", "List all measured minerals in order."),
            ("less than 20 days", "at most 20 days", "What was the duration limit?"),
            ("It was not 42 days.", "42 days", "What was the duration?"),
            ("42 days. Actually, 8 days.", "42 days", "What was the duration?"),
            ("42 days. I retract that answer.", "42 days", "What was the duration?"),
            ("Yes", "No", "Did it work?"),
            ("change", "no change", "What happened?"),
        ):
            with self.subTest(text=text):
                backend = self.Backend()
                result = self.judge(self.item(text, answer, question, ""), backend)
                self.assertEqual((result["label"], result["label_source"], result["score"]), ("not_correct", "rule", 0))
                self.assertEqual(backend.pairs, [])

    def test_explicit_final_correction_can_replace_old_wrong_value(self) -> None:
        result = self.judge(self.item("8 days. Correction: 42 days.", "42 days", "What was the duration?", ""))
        self.assertEqual((result["label"], result["reason"]), ("correct", "answer_corrected"))

    def test_plain_paraphrase_is_nli_with_probabilities_and_identity(self) -> None:
        backend = self.Backend()
        result = self.judge(self.item(), backend)
        self.assertEqual((result["label"], result["label_source"]), ("correct", "nli"))
        self.assertAlmostEqual(result["nli_score"], 0.92)
        self.assertEqual(result["model"], backend.identity)
        self.assertEqual(set(result["evidence"]["windows"][0]["probabilities"]), {"entailment", "neutral", "contradiction"})

    def test_reference_is_only_in_hypothesis_and_not_actual_premise(self) -> None:
        for mode in ("qa_pair", "target_claim"):
            backend = self.Backend()
            self.judge(self.item(), backend, input_mode=mode)
            premise, hypothesis = backend.pairs[0]
            self.assertNotIn("decreased", premise)
            self.assertIn("decreased", hypothesis)
            self.assertIn("lowered", premise)
            self.assertNotIn("lowered", hypothesis)

    def test_target_claim_keeps_condition_negation_and_unique_clause(self) -> None:
        from src.evaluation.answer_judgment import nli_hypothesis
        query = self.item(claim="In untreated patients the risk did not decrease; in treated patients it decreased.")["query"]
        hypothesis, mode = nli_hypothesis(query, "target_claim")
        self.assertEqual(mode, "target_claim")
        self.assertIn("untreated", hypothesis)
        self.assertIn("did not", hypothesis)
        query["claim"] = "Risk decreased. Mortality also decreased."
        hypothesis, mode = nli_hypothesis(query, "target_claim")
        self.assertEqual(mode, "qa_pair")
        self.assertTrue(hypothesis.startswith("Question:"))

    def test_keyword_hit_with_wrong_object_or_condition_goes_to_nli(self) -> None:
        for text in ("Marker B showed no change.", "Marker A showed no change only before treatment.",
                     "Marker A increased; marker B showed no change."):
            backend = self.Backend({"entailment": 0.02, "neutral": 0.08, "contradiction": 0.90})
            result = self.judge(self.item(text, "no change", "What happened to marker A after treatment?",
                                         "Marker A showed no change after treatment."), backend)
            self.assertEqual((result["label"], result["label_source"]), ("not_correct", "nli"))
            self.assertTrue(backend.pairs)

    def test_factual_negation_other_unknown_attributes_and_no_terms_are_not_refusal_rules(self) -> None:
        for text, answer, question, claim in (
            ("The test showed no equivocal results.", "no equivocal results", "What did the test show?", "The test showed no equivocal results."),
            ("42 days. The author is unknown.", "42 days", "What was the duration?", "The duration was 42 days."),
            ("The transport mechanism remains unclear.", "transport mechanism", "What remains unclear?", "The transport mechanism remains unclear."),
        ):
            result = self.judge(self.item(text, answer, question, claim))
            self.assertEqual(result["label"], "correct")
            self.assertNotEqual(result["reason"], "refused")

    def test_genuine_refusal_is_rule_zero(self) -> None:
        for text in ("Unknown.", "I cannot determine the duration.", "This document does not contain the answer to your question."):
            result = self.judge(self.item(text, "42 days", "What was the duration?", ""))
            self.assertEqual((result["label"], result["reason"], result["label_source"]), ("not_correct", "refused", "rule"))

    def test_neutral_is_binary_not_review_or_refusal(self) -> None:
        result = self.judge(self.item(), self.Backend({"entailment": 0.34, "neutral": 0.35, "contradiction": 0.31}))
        self.assertEqual((result["label"], result["status"], result["score"]), ("not_correct", "resolved", 0))
        self.assertNotEqual(result["reason"], "refused")

    def test_model_failures_nan_and_bad_counts_are_invalid_not_zero(self) -> None:
        from src.evaluation.answer_judgment import judge_answers_auto
        for action in (RuntimeError("GPU error"), [], [{"entailment": float("nan"), "neutral": 0.1, "contradiction": 0.1}]):
            backend = self.Backend()
            backend.probabilities = Mock(side_effect=action) if isinstance(action, Exception) else Mock(return_value=action)
            result = judge_answers_auto([self.item()], backend=backend)[0]
            self.assertEqual((result["label"], result["status"], result["score"], result["reason"]),
                             (None, "invalid", None, "nli_model_failure"))
        with patch("src.evaluation.answer_judgment.LocalNLIPredictor", side_effect=RuntimeError("CUDA unavailable")):
            result = judge_answers_auto([self.item()])[0]
        self.assertEqual(result["status"], "invalid")

    def test_empty_api_error_and_drift_stay_invalid_without_model(self) -> None:
        for changes in ({"response": ""}, {"response": "HTTP 503 Service Unavailable"}, {"status": "failed"},
                        {"query_id": "other"}, {"response_sha256": "wrong"}):
            item = self.item()
            item["response"].update(changes)
            backend = self.Backend()
            result = self.judge(item, backend)
            self.assertEqual((result["status"], result["score"]), ("invalid", None))
            self.assertEqual(backend.pairs, [])

    def test_paired_question_removes_anchor_and_retains_full_original_binding(self) -> None:
        item = self.item("The trial enrolled 42 patients.", "seven weeks", "What was the treatment duration?",
                         "Treatment lasted seven weeks.")
        original = item["query"]
        paired = {**original, "query_id": "remote", "arm": "remote_only"}
        original.update(arm="correct_anchor", question="The trial enrolled 42 patients. What was the treatment duration?")
        item["paired_query"] = paired
        snapshot = copy.deepcopy(item)
        backend = self.Backend({"entailment": 0.01, "neutral": 0.98, "contradiction": 0.01})
        result = self.judge(item, backend)
        self.assertEqual(result["label"], "not_correct")
        self.assertNotIn("42 patients", backend.pairs[0][1])
        self.assertEqual(backend.pairs[0][0].split("\n")[0], "Question: What was the treatment duration?")
        self.assertEqual(result["binding"]["original_query_sha256"], sha256_obj(original))
        self.assertEqual(result["binding"]["paired_query_sha256"], sha256_obj(paired))
        self.assertEqual(item, snapshot)

    def test_missing_or_mismatched_anchor_pair_is_invalid(self) -> None:
        item = self.item()
        item["query"]["arm"] = "correct_anchor"
        self.assertEqual(self.judge(item)["status"], "invalid")
        item["paired_query"] = {**item["query"], "arm": "remote_only", "query_id": "other", "source_key": "other"}
        self.assertEqual(self.judge(item)["status"], "invalid")

    def test_initial_never_uses_extra_remote_target_answer(self) -> None:
        item = self.item("42 days", "42 days", "What was the duration?", "")
        item["query"]["remote_target_answer"] = "no change"
        self.assertEqual(self.judge(item)["label"], "correct")

    def test_assistant_annotation_and_membership_cannot_override_automatic_result(self) -> None:
        first = self.item()
        second = copy.deepcopy(first)
        second.update(annotation={"label": "not_correct"}, review={"label": "not_correct"})
        second["query"].update(group="KB_Member", previous_label="incorrect")
        a, b = self.judge(first), self.judge(second)
        self.assertEqual({k: v for k, v in a.items() if k != "binding"}, {k: v for k, v in b.items() if k != "binding"})

    def test_windows_preserve_tail_overlap_and_strongest_contradiction(self) -> None:
        from src.evaluation.answer_judgment import response_windows
        import re

        class Tokenizer:
            def __call__(self, text, pair=None, **kwargs):
                matches = list(re.finditer(r"\S+", text))
                result = {"input_ids": list(range(len(matches) + (len(pair.split()) + 3 if pair is not None else 0)))}
                if kwargs.get("return_offsets_mapping"):
                    result["offset_mapping"] = [(m.start(), m.end()) for m in matches]
                return result

        response = " ".join(f"word{i}" for i in range(120)) + " actually the risk increased"
        windows = response_windows(Tokenizer(), "What happened?", response, "Risk decreased.", max_length=40, overlap=5)
        self.assertGreater(len(windows), 1)
        self.assertTrue(all(w["input_tokens"] <= 40 for w in windows))
        self.assertEqual(windows[0]["char_start"], 0)
        self.assertEqual(windows[-1]["char_end"], len(response))
        self.assertTrue(all(a["char_end"] > b["char_start"] for a, b in zip(windows, windows[1:])))
        self.assertIn("risk increased", windows[-1]["premise"])
        backend = self.Backend()
        backend.windows = Mock(return_value=windows[:2])
        backend.probabilities = Mock(return_value=[
            {"entailment": 0.98, "neutral": 0.01, "contradiction": 0.01},
            {"entailment": 0.01, "neutral": 0.01, "contradiction": 0.98}])
        result = self.judge(self.item(), backend)
        self.assertEqual(result["label"], "not_correct")
        self.assertAlmostEqual(result["nli_score"], 0.0)
        self.assertEqual(result["evidence"]["strongest_contradiction_window"], 1)

    def test_gate_v2_accepts_resolved_nli_and_still_blocks_invalid(self) -> None:
        from src.evaluation.answer_judgment import AUTOMATIC_JUDGMENT_VERSION, IncompleteJudgmentError
        from src.evaluation.answer_judgment import gated_queries as gate, resolved_scores
        item = self.item()
        plan = [item["query"], *[{**item["query"], "arm": arm, "query_id": arm} for arm in ("correct_anchor", "remote_only")]]
        backend = self.Backend()
        self.assertEqual(len(gate(plan, [item["response"]], judgment_version=AUTOMATIC_JUDGMENT_VERSION, nli_backend=backend)), 2)
        self.assertEqual(resolved_scores([item["query"]], [item["response"]], judgment_version=AUTOMATIC_JUDGMENT_VERSION,
                                        nli_backend=self.Backend({"entailment": 0.3, "neutral": 0.4, "contradiction": 0.3})), {"q": 0})
        backend.probabilities = Mock(side_effect=RuntimeError("failed"))
        with self.assertRaises(IncompleteJudgmentError):
            gate(plan, [item["response"]], judgment_version=AUTOMATIC_JUDGMENT_VERSION, nli_backend=backend)
        with self.assertRaises(ValueError):
            resolved_scores([item["query"]], [item["response"]], judgment_version=AUTOMATIC_JUDGMENT_VERSION,
                            reviews={"q": {"label": "correct"}})

    def test_refusal_model_neutral_does_not_imply_refusal(self) -> None:
        from src.evaluation.answer_judgment import judge_answers_auto
        backend = self.Backend({"entailment": 0.01, "neutral": 0.98, "contradiction": 0.01})
        item = self.item("The author is unknown.", "42 days", "What was the duration?", "")
        result = judge_answers_auto([item], backend=backend)[0]
        self.assertEqual((result["label"], result["reason"]), ("not_correct", "nli_target_not_established"))
        self.assertIn("refusal_probabilities", result["evidence"])

    def test_source_folds_tie_breaking_and_disputes_are_not_dropped(self) -> None:
        from src.evaluation.answer_judgment import calibrate_nli, source_folds, classification_summary
        items = []
        for i in range(10):
            item = self.item()
            item["query"].update(query_id=str(i), source_key=str(i // 2))
            item["annotation"] = {"label": "correct" if i % 2 else "not_correct", "reason": "target"}
            items.append(item)
        folds = source_folds(items, seed=20261008, folds=5)
        self.assertEqual(folds, source_folds(items, seed=20261008, folds=5))
        self.assertEqual(len(folds), 5)
        predictions = [{"status": "resolved", "label": item["annotation"]["label"], "reason": "target", "label_source": "rule"} for item in items]
        result = calibrate_nli(items, {"qa_pair": predictions, "target_claim": predictions}, seed=20261008, folds=5,
                               thresholds=[0.1, 0.5, 0.95])
        self.assertEqual((result["selected_input_mode"], result["selected_threshold"]), ("qa_pair", 0.95))
        annotations = [{"label": None, "reason": "reference_uncertain"}, {"label": "correct", "reason": "target"}]
        summary = classification_summary(annotations, [{"status": "resolved", "label": "correct"},
                                                       {"status": "invalid", "label": None}])
        self.assertEqual((summary["error_upper_bound_count"], summary["invalid"]), (2, 1))
        self.assertFalse(summary["final_metrics_available"])

    def test_comparison_reports_old_binary_v1_coverage_and_source_intervals(self) -> None:
        from src.evaluation.answer_judgment import compare_judgments
        items, predictions = [], []
        for i in range(5):
            item = self.item("42 days", "42 days", "What was the duration?", "")
            item.update(stage="initial", cohort="test", source_hash=str(i))
            item["query"].update(source_key=str(i), query_id=str(i))
            item["response"].update(source_key=str(i), query_id=str(i))
            item["annotation"] = {"label": "correct", "reason": "target"}
            items.append(item)
            predictions.append(self.judge(item))
        report = compare_judgments(items, predictions, seed=20261008)
        self.assertEqual(report["summaries"]["legacy"]["known_errors"], 0)
        self.assertEqual(report["summaries"]["v2"]["automatic_coverage"], 1.0)
        self.assertEqual(report["source_cluster_intervals"]["v2"]["sources"], 5)
        self.assertEqual(report["per_stage"]["initial"]["v2"]["known_errors"], 0)


class TargetedNLIJudgmentTests(unittest.TestCase):
    Backend = AutomaticNLIJudgmentTests.Backend

    def item(self, *args, **kwargs):
        return AutomaticNLIJudgmentTests().item(*args, **kwargs)

    def judge(self, item, backend=None, **kwargs):
        from src.evaluation.answer_judgment import judge_answers_auto, NLIConfig, TARGETED_JUDGMENT_VERSION
        return judge_answers_auto([item], config=NLIConfig(classify_refusals=False, **kwargs),
                                  backend=backend or self.Backend(), judgment_version=TARGETED_JUDGMENT_VERSION)[0]

    def test_ranges_ranks_and_question_quantity_prefixes_are_rule_equivalent(self) -> None:
        for actual, reference, question, claim in (
            ("100.57 % to 108.46 %", "100.57% and 108.46%", "What recovery range was obtained?", "Recoveries ranged between 100.57% and 108.46%."),
            ("15", "15 out of 73", "What was the rank of the best system?", "The best system ranks 15 out of 73."),
            ("mrs scores of 0 - 2.", "mRS scores of 0-2", "Which mRS scores defined a favorable outcome?", "Favorable outcome was defined as mRS scores of 0-2."),
            ("An increased daily intake of 150 - 300 kcal has occurred.", "150-300 kcal (for different age-sex groups)",
             "What increased daily intake has occurred?", "An increased daily intake of 150-300 kcal (for different age-sex groups) has occurred."),
            ("5 nm", "5 nM", "What was the dissociation constant?", "The dissociation constant was 5 nM."),
            ("0. 05 - 50 μm", "0.05–50 μM", "What linear range was obtained?", "The linear range was 0.05–50 μM."),
        ):
            with self.subTest(actual=actual):
                backend = self.Backend()
                result = self.judge(self.item(actual, reference, question, claim), backend)
                self.assertEqual((result["label"], result["label_source"]), ("correct", "rule"), result)
                self.assertFalse(backend.pairs)

    def test_numeric_counterexamples_cannot_be_rescued_by_high_nli(self) -> None:
        for actual, reference, question in (
            ("100.57% to 118.46%", "100.57% and 108.46%", "What recovery range was obtained?"),
            ("100.57%", "100.57% and 108.46%", "What recovery range was obtained?"),
            ("16", "15 out of 73", "What was the rank of the best system?"),
            ("mrs scores of 0 - 3", "mRS scores of 0-2", "Which mRS scores defined a favorable outcome?"),
            ("5 µM", "5 nM", "What was the dissociation constant?"),
            ("0.75 kilograms", "750 mg", "What was the dose?"),
            ("4.184 kJ", "1000 kcal", "What was the energy intake?"),
        ):
            with self.subTest(actual=actual):
                backend = self.Backend()
                result = self.judge(self.item(actual, reference, question, ""), backend)
                self.assertEqual((result["label"], result["label_source"]), ("not_correct", "rule"), result)
                self.assertFalse(backend.pairs)

    def test_ordered_values_bind_each_object_and_allow_reordered_sentences(self) -> None:
        question = "What were the median operative times for single-port and conventional procedures, respectively?"
        answer = "85 minutes vs 114 minutes"
        claim = "Median operative times for single-port and conventional procedures were 85 minutes vs 114 minutes."
        for text, label in (
            ("85 minutes vs 114 minutes", "correct"),
            ("Median operative time for single-port procedures was 85 minutes, and the median operative time for conventional procedures was 114 minutes.", "correct"),
            ("Conventional procedures were 114 minutes, and single-port procedures were 85 minutes.", "correct"),
            ("Single-port procedures were 114 minutes, and conventional procedures were 85 minutes.", "not_correct"),
            ("114 minutes vs 85 minutes", "not_correct"),
            ("85 minutes", "not_correct"),
        ):
            with self.subTest(text=text):
                result = self.judge(self.item(text, answer, question, claim))
                self.assertEqual((result["label"], result["label_source"]), (label, "rule"), result)

    def test_target_reduction_does_not_pick_unrelated_population_percentage(self) -> None:
        question = "What reduction in paraprotein levels did some patients have?"
        answer = "a 12% to 30% reduction"
        claim = "Fifty percent of these patients had a 12% to 30% reduction in their paraprotein levels."
        for text, label in (
            ("Fifty percent (5 of 10) of these patients had a 12% to 30% reduction in their paraprotein levels.", "correct"),
            ("Fifty percent (5 of 10) of these patients had a 12% to 40% reduction in their paraprotein levels.", "not_correct"),
            ("These patients had a 50% reduction; 12% to 30% of patients had nausea.", "not_correct"),
        ):
            with self.subTest(text=text):
                result = self.judge(self.item(text, answer, question, claim))
                self.assertEqual((result["label"], result["label_source"]), (label, "rule"), result)

    def test_complete_named_lists_accept_only_claim_supported_category_prefixes(self) -> None:
        question = "In cells infected with which CoVs was abundant viral RNA synthesis associated with DMVs?"
        answer = "MERS-CoV and SARS-CoV, and the gamma-CoV infectious bronchitis virus"
        claim = "abundant viral RNA synthesis associated with DMVs in cells infected with the beta-CoVs MERS-CoV and SARS-CoV, and the gamma-CoV infectious bronchitis virus"
        for text, label in (
            ("Abundant viral RNA synthesis was associated with DMVs in cells infected with the beta - covs mers - cov and sars - cov, and the gamma - cov infectious bronchitis virus.", "correct"),
            ("Abundant viral RNA synthesis associated with DMVs was found in cells infected with the beta - CoVs mers - cov and sars - cov, and the gamma - cov infectious bronchitis virus.", "correct"),
            ("SARS-CoV, MERS-CoV, and the gamma-CoV infectious bronchitis virus", "correct"),
            ("MERS-CoV and SARS-CoV", "not_correct"),
            ("MERS-CoV, MERS-CoV and SARS-CoV", "not_correct"),
        ):
            with self.subTest(text=text):
                result = self.judge(self.item(text, answer, question, claim))
                self.assertEqual((result["label"], result["label_source"]), (label, "rule"), result)

    def test_wrong_named_identifiers_and_conditions_override_model(self) -> None:
        for text, answer, question, claim in (
            ("High-titer stocks of recombinant FIPV.", "high-titer stocks of recombinant FECVs",
             "What can the reverse genetics system produce?", "The system can produce high-titer stocks of recombinant FECVs."),
            ("Bovine respiratory syncytial virus (BRSV)", "Respiratory Syncytial virus (RSV)",
             "Which virus was the main aetiological agent?", "Respiratory Syncytial virus (RSV) was the main aetiological agent."),
            ("Marker B showed no change.", "no change", "What happened to marker A after treatment?", "Marker A showed no change after treatment."),
            ("Marker A showed no change before treatment.", "no change", "What happened to marker A after treatment?", "Marker A showed no change after treatment."),
        ):
            with self.subTest(text=text):
                backend = self.Backend()
                result = self.judge(self.item(text, answer, question, claim), backend)
                self.assertEqual((result["label"], result["label_source"]), ("not_correct", "rule"), result)
                self.assertFalse(backend.pairs)

    def test_negative_question_is_not_refusal_and_polarity_reversal_is_wrong(self) -> None:
        for text, expected in (
            ("Serotype I field viruses cannot be grown in vitro.", "correct"),
            ("Serotype I field viruses can be grown in vitro.", "not_correct"),
        ):
            result = self.judge(self.item(text, "in vitro", "Where can serotype I field viruses not be grown?", "These viruses cannot be grown in vitro."))
            self.assertEqual((result["label"], result["label_source"]), (expected, "rule"), result)
            self.assertNotEqual(result["reason"], "refused")

    def test_identifier_case_and_another_attribute_do_not_create_object_conflict(self) -> None:
        result = self.judge(self.item(
            "The evaluated primer-probe sets were designed to detect the hemagglutinin (ha) or neuraminidase (na) gene of the pandemic influenza A/H1N1 2009 virus.",
            "the hemagglutinin (HA) or the neuraminidase (NA) gene",
            "Which genes were the evaluated primer-probe sets designed to detect?",
            "The evaluated primer-probe sets were designed to detect the hemagglutinin (HA) or the neuraminidase (NA) gene."))
        self.assertEqual(result["label"], "correct")
        self.assertNotEqual(result["reason"], "different_named_identifier")

    def test_withdrawal_correction_and_conflicting_values(self) -> None:
        for text, expected in (
            ("42 days. I retract that answer.", "not_correct"),
            ("42 days. Actually, 8 days.", "not_correct"),
            ("8 days. Correction: 42 days.", "correct"),
            ("42 days. 8 days.", "not_correct"),
        ):
            result = self.judge(self.item(text, "42 days", "What was the duration?", "The duration was 42 days."))
            self.assertEqual(result["label"], expected, result)

    def test_unknown_parenthetical_condition_is_not_removed(self) -> None:
        backend = self.Backend({"entailment": 0.01, "neutral": 0.04, "contradiction": 0.95})
        result = self.judge(self.item("150-300 kcal", "150-300 kcal (only after treatment)",
                                     "What was the daily intake?", ""), backend)
        self.assertEqual(result["label"], "not_correct")

    def test_statement_input_uses_question_without_reference_leakage(self) -> None:
        item = self.item("The passage says the problems were made available in the CALMA project.",
                         "during the CALMA project", "When were the GRAPH instances generated?",
                         "The GRAPH instances were generated during the CALMA project.")
        backend = self.Backend()
        result = self.judge(item, backend, input_mode="target_statement")
        premise, hypothesis = backend.pairs[0]
        actual = premise.split("\nAnswer: ", 1)[1]
        self.assertIn("Question: When were the GRAPH instances generated?", premise)
        self.assertNotIn("GRAPH", actual)
        self.assertNotIn("generated", actual)
        self.assertIn("GRAPH", hypothesis)
        self.assertIn("generated", hypothesis)
        self.assertEqual(result["evidence"]["premise_origin"], "question_and_response_only")

    def test_future_prediction_does_not_replace_observed_outcome(self) -> None:
        result = self.judge(self.item(
            "Discharged to a facility where they will eventually die.", "died",
            "What was the patient's ultimate outcome?", "The patient died."))
        self.assertEqual((result["label"], result["reason"]),
                         ("not_correct", "future_event_not_observed_outcome"))

    def test_active_subject_question_is_not_reversed_into_bad_statement(self) -> None:
        from src.evaluation.answer_judgment import _v3_nli_input
        query = self.item("Coronavirus", "SARS-CoV-2",
                          "Which pathogen's exposure are healthcare professionals seeking to reduce?", "")["query"]
        question, actual, hypothesis, evidence = _v3_nli_input(query, "Coronavirus", "target_statement")
        self.assertEqual(evidence["input_mode"], "qa_pair")
        self.assertIn("Question:", hypothesis)
        self.assertEqual(actual, "Coronavirus")

    def test_unparseable_statement_falls_back_and_low_confidence_stays_binary(self) -> None:
        backend = self.Backend({"entailment": 0.3, "neutral": 0.4, "contradiction": 0.3})
        result = self.judge(self.item(), backend, input_mode="target_statement")
        self.assertEqual(result["evidence"]["input_mode"], "qa_pair")
        self.assertEqual((result["label"], result["status"], result["score"]), ("not_correct", "resolved", 0))

    def test_v3_does_not_use_reviews_and_invalid_still_blocks_gate(self) -> None:
        from src.evaluation.answer_judgment import TARGETED_JUDGMENT_VERSION, IncompleteJudgmentError, resolved_scores
        item = self.item()
        item["annotation"] = {"label": "correct"}
        backend = self.Backend()
        backend.probabilities = Mock(side_effect=RuntimeError("GPU failure"))
        result = self.judge(item, backend)
        self.assertEqual((result["status"], result["label"], result["score"]), ("invalid", None, None))
        with self.assertRaises(IncompleteJudgmentError):
            resolved_scores([item["query"]], [item["response"]], judgment_version=TARGETED_JUDGMENT_VERSION, nli_backend=backend)
        item["response"]["response"] = "HTTP 503 Service Unavailable"
        self.assertEqual(self.judge(item)["status"], "invalid")

    def test_default_automatic_version_and_legacy_rule_entry_are_unchanged(self) -> None:
        from src.evaluation.answer_judgment import judge_answers_auto, AUTOMATIC_JUDGMENT_VERSION
        item = self.item("15", "15 out of 73", "What was the rank of the best system?", "The best system ranks 15 out of 73.")
        result = judge_answers_auto([item], backend=self.Backend())[0]
        self.assertEqual(result["version"], AUTOMATIC_JUDGMENT_VERSION)
        self.assertEqual(result["label_source"], "nli")


class FormalNLIIntegrationTests(ExecutionFixture):
    def test_new_generator_runs_own_gate_and_signed_scores_without_old_responses(self):
        from pathlib import Path
        import yaml
        from src.evaluation.source_scoring import evaluate, load_scoring_config

        self.freeze_all()
        for dataset in self.config.datasets:
            self.install_retrieval(dataset)
        self.complete_cell("nfcorpus")
        original = {path: sha256_file(path) for path in self.config.output.rglob("*") if path.is_file()}
        self.prepare_new_generator()
        run, backend = self.activate_nli()
        self.assertFalse(run.metadata["post_response_correction"])
        self.assertEqual(run.metadata["status"], "frozen_before_victim")
        self.assertEqual(run.responses("nfcorpus", False), [])
        copied_module = self.root / "src/evaluation/answer_judgment.py"
        copied_module.parent.mkdir(parents=True)
        copied_module.write_bytes((Path(__file__).resolve().parents[1] / "src/evaluation/answer_judgment.py").read_bytes())
        scoring_path = self.root / "signed.yaml"
        scoring = {
            "version": "signed_correct_refused_v1", "output_dir": "artifacts/v25/scoring/llama", "seed": 45,
            "inputs": {dataset: run.config.output.relative_to(self.root).as_posix() for dataset in self.config.datasets},
            "scoring": {"primary": "S_lambda", "formula": "(C - U) + lambda * (R - V)", "normalized": False,
                        "lambda": 1.0, "operational_cutoff": 2.0, "parameter_source": "previous_defaults",
                        "parameter_validation": "pending_ablation", "statistical_unit": "source_document"},
            "evaluation": {"bootstrap_samples": 20, "confidence": 0.95, "low_fpr_targets": [0.01, 0.05]}}
        scoring_path.write_text(yaml.safe_dump(scoring), encoding="utf-8")
        load_scoring_config(scoring_path, project_root=self.root)
        for dataset in self.config.datasets:
            client = self.victim_client()
            if dataset == "nfcorpus":
                normal = client.generate_with_metadata.side_effect
                def answer(prompt, **kwargs):
                    if client.generate_with_metadata.call_count == 1:
                        return self.result("I do not know.", "victim")
                    return normal(prompt, **kwargs)
                client.generate_with_metadata.side_effect = answer
            with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])):
                run.run_victim(dataset, False, 2)
                self.assertTrue(run.run_victim(dataset, False)["complete"])
                self.assertEqual(run.run_victim(dataset, False)["new_calls"], 0)
                self.assertTrue(run.run_victim(dataset, True)["complete"])
            self.assertTrue(run.report(dataset)["complete"])
            result = evaluate(scoring_path, dataset, project_root=self.root)
            self.assertEqual(result["source_count"], 4)
            self.assertEqual(result["evaluation_role"], "prospective_generator_on_existing_cohort")
            self.assertEqual(set(result["metadata"]["provider_model_ids"]), {"llama-3.1-8b-instruct"})
            self.assertFalse(result["metadata"]["post_response_correction"])
            if dataset == "nfcorpus":
                self.assertEqual(result["metadata"]["followup_responses"], 22)
            with patch("src.llm.factory.build_victim_client", side_effect=AssertionError("no repeated calls")):
                self.assertTrue(run.status(dataset)["complete"])
                self.assertEqual(evaluate(scoring_path, dataset, project_root=self.root), result)
        self.assertEqual(original, {path: sha256_file(path) for path in original})

    def activate_nli(self, datasets=None):
        from dataclasses import asdict
        import yaml
        from src.evaluation.answer_judgment import FormalJudgmentRun, NLIConfig, TARGETED_JUDGMENT_VERSION

        nli = NLIConfig(threshold=0.2, snapshot_dir="models/test_nli")
        write_json_atomic(self.root / nli.snapshot_dir / "pcv_snapshot_manifest.json",
                          {"repo_id": nli.model_id, "revision": nli.revision, "files": {}})
        write_json_atomic(self.root / "calibration.json", {"version": TARGETED_JUDGMENT_VERSION, "selected_config": asdict(nli)})
        write_json_atomic(self.root / "development.json", {"acceptance": {"numerical_target_met": False}})
        path = self.root / "nli.yaml"
        specification = {
            "version": TARGETED_JUDGMENT_VERSION, "base_config": self.config_path.relative_to(self.root).as_posix(),
            "output_dir": "artifacts/v25/formal/nli_v3", "calibration": "calibration.json",
            "development_report": "development.json", "adoption_reason": "user_requested_adoption_without_additional_validation",
            "scoring_datasets": list(self.config.datasets) if datasets is None else datasets,
        }
        if (self.root / "primary_scoring.yaml").is_file():
            specification["primary_scoring_config"] = "primary_scoring.yaml"
        path.write_text(yaml.safe_dump(specification), encoding="utf-8")
        backend = AutomaticNLIJudgmentTests.Backend()
        backend.identity = {"model_id": nli.model_id, "revision": nli.revision}
        run = FormalJudgmentRun(path, self.root, backend=backend)
        run.activate()
        return run, backend

    def test_primary_scoring_config_is_bound_before_new_generator_responses(self):
        from pathlib import Path
        import yaml

        self.freeze_all()
        for dataset in self.config.datasets:
            self.install_retrieval(dataset)
        self.prepare_new_generator()
        primary = {
            "version": "signed_correct_refused_v1", "output_dir": "artifacts/v25/scoring/primary", "seed": 45,
            "inputs": {dataset: "artifacts/v25/formal/nli_v3" for dataset in self.config.datasets},
            "scoring": {"primary": "S_lambda", "formula": "(C - U) + lambda * (R - V)", "normalized": False,
                        "lambda": 1.0, "operational_cutoff": 2.0, "parameter_source": "previous_defaults",
                        "parameter_validation": "pending_ablation", "statistical_unit": "source_document"},
            "evaluation": {"bootstrap_samples": 20, "confidence": 0.95, "low_fpr_targets": [0.01, 0.05]}}
        path = self.root / "primary_scoring.yaml"
        path.write_text(yaml.safe_dump(primary), encoding="utf-8")
        module = self.root / "src/evaluation/source_scoring.py"
        module.parent.mkdir(parents=True)
        module.write_bytes((Path(__file__).resolve().parents[1] / "src/evaluation/source_scoring.py").read_bytes())
        run, backend = self.activate_nli()
        self.assertIn("primary_scoring.yaml", run.metadata["input_hashes"])
        self.assertFalse(run.metadata["post_response_correction"])
        primary["scoring"]["lambda"] = 2.0
        path.write_text(yaml.safe_dump(primary), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "formal_scoring_input_drift"):
            run.status("nfcorpus")

    def prepare_legacy(self, numeric_answer="230", followup=True):
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        client = self.victim_client()
        original = client.generate_with_metadata.side_effect

        def answer(prompt, **kwargs):
            result = original(prompt, **kwargs)
            return self.result(numeric_answer, "victim") if result.content == "230" else result

        client.generate_with_metadata.side_effect = answer
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            run_victim(self.config, self.store, "nfcorpus", False)
            if followup:
                run_victim(self.config, self.store, "nfcorpus", True)

    def test_new_gate_backfills_only_missing_requests_and_preserves_parent(self) -> None:
        self.prepare_legacy("two hundred thirty")
        original = {p: sha256_file(p) for p in self.config.output.rglob("*") if p.is_file()}
        run, backend = self.activate_nli()
        with patch("src.shared_g.artifacts.read_response_adjudications", side_effect=AssertionError("no review lookup")):
            state = run.score("nfcorpus")
        self.assertEqual(state["initial"]["labels"], {"correct": 12})
        self.assertEqual(state["followup"]["planned"], 24)
        self.assertEqual(state["followup"]["missing_responses"], 8)
        self.assertFalse(state["final_metrics_available"])
        self.assertIsNone(run.report("nfcorpus")["metrics"])
        self.assertFalse(run.path("report.json", "nfcorpus").exists())
        initial_resume = run.run_victim("nfcorpus", False)
        self.assertTrue(initial_resume["complete"])
        self.assertFalse(initial_resume["cell_complete"])
        client = self.victim_client()
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])):
            first = run.run_victim("nfcorpus", True, 3)
            self.assertEqual(first["new_calls"], 3)
            self.assertEqual(first["followup"]["missing_responses"], 5)
            self.assertTrue(run.run_victim("nfcorpus", True)["complete"])
            self.assertEqual(run.run_victim("nfcorpus", True)["new_calls"], 0)
        self.assertEqual(client.generate_with_metadata.call_count, 8)
        self.assertEqual(len(request_records(run.path("followup_responses.jsonl", "nfcorpus"))), 8)
        report1 = run.report("nfcorpus")
        self.assertEqual(report1, run.report("nfcorpus"))
        self.assertTrue(report1["post_response_correction"])
        self.assertFalse(report1["one_percent_acceptance_passed"])
        self.assertEqual(report1["metrics"]["correct_anchor"]["fixed_cutoff"]["accuracy"], 0.5)
        self.assertEqual([r["correct_anchor"] for r in read_rows(run.path("scores.jsonl", "nfcorpus"))], [6.0] * 4)
        self.assertEqual(backend.pairs, [])
        self.assertEqual(original, {p: sha256_file(p) for p in original})
        self.store.validate(frozen=True)

    def test_historical_followups_outside_new_gate_are_preserved_but_not_scored_as_required(self) -> None:
        self.prepare_legacy("230. Correction: 231.")
        old_hash = sha256_file(self.store.path("followup_responses.jsonl", "nfcorpus"))
        run, _ = self.activate_nli()
        state = run.score("nfcorpus")
        self.assertEqual(state["initial"]["labels"], {"correct": 8, "not_correct": 4})
        self.assertEqual(state["followup"]["historical_outside_gate"], 8)
        self.assertEqual(state["followup"]["planned"], 16)
        self.assertTrue(state["complete"])
        run.report("nfcorpus")
        self.assertEqual([r["correct_anchor"] for r in read_rows(run.path("scores.jsonl", "nfcorpus"))], [4.0] * 4)
        self.assertEqual(old_hash, sha256_file(self.store.path("followup_responses.jsonl", "nfcorpus")))

    def test_scoring_resume_reuses_bound_predictions_without_model_or_victim(self) -> None:
        self.prepare_legacy()
        run, backend = self.activate_nli()
        self.assertFalse(run.score("nfcorpus", 2)["complete"])
        self.assertTrue(run.score("nfcorpus")["complete"])
        backend.probabilities = Mock(side_effect=AssertionError("no repeat inference"))
        self.assertEqual(run.score("nfcorpus")["new_judgments"], 0)
        self.assertEqual(run.retrieve("nfcorpus")["new_queries"], 0)
        self.assertEqual(run.activate()["version"], "binary_target_rules_nli_v3")
        with patch("src.llm.factory.build_victim_client", side_effect=AssertionError("no repeated victim")):
            self.assertEqual(run.run_victim("nfcorpus", False)["new_calls"], 0)

    def test_model_failure_is_invalid_and_never_creates_a_gate_or_final_metrics(self) -> None:
        self.prepare_legacy("The enrolled population was substantial.", followup=False)
        run, backend = self.activate_nli()
        backend.probabilities = Mock(side_effect=RuntimeError("GPU failure"))
        state = run.score("nfcorpus")
        self.assertEqual(state["status"], "invalid")
        self.assertGreater(state["initial"]["invalid"], 0)
        self.assertIsNone(state["followup"]["planned"])
        self.assertFalse(run.path("followup_gate.json", "nfcorpus").exists())
        self.assertIsNone(run.report("nfcorpus")["metrics"])
        with self.assertRaisesRegex(RuntimeError, "initial_judgments_incomplete"):
            run.run_victim("nfcorpus", True)

    def test_transport_failure_remains_invalid_and_is_not_resent(self) -> None:
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        run, _ = self.activate_nli()
        client = Mock()
        client.generate_with_metadata.side_effect = ConnectionError("sensitive transport message")
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])):
            with self.assertRaisesRegex(RuntimeError, "invalid_response"):
                run.run_victim("nfcorpus", False, 1)
            with self.assertRaisesRegex(RuntimeError, "invalid_victim_response"):
                run.run_victim("nfcorpus", False, 1)
        self.assertEqual(client.generate_with_metadata.call_count, 1)
        state = run.status("nfcorpus")
        self.assertEqual(state["initial"]["invalid"], 1)
        self.assertFalse(state["complete"])
        self.assertNotIn("sensitive transport message", run.path("initial_responses.jsonl", "nfcorpus").read_text())

    def test_next_cell_waits_for_new_gate_completeness(self) -> None:
        self.prepare_legacy("two hundred thirty")
        self.install_retrieval("scidocs")
        run, _ = self.activate_nli()
        run.score("nfcorpus")
        with patch("src.llm.factory.build_victim_client", side_effect=AssertionError("no early victim")):
            with self.assertRaisesRegex(RuntimeError, "previous_dataset_incomplete:nfcorpus"):
                run.run_victim("scidocs", False)
        with self.assertRaisesRegex(RuntimeError, "previous_dataset_incomplete:nfcorpus"):
            run.retrieve("scidocs")
        self.assertEqual(run.status("trec-covid")["initial"]["missing_responses"], 12)

    def test_prediction_and_gate_drift_are_rejected(self) -> None:
        self.prepare_legacy()
        run, _ = self.activate_nli()
        run.score("nfcorpus")
        path = run.path("initial_judgments.jsonl", "nfcorpus")
        values = read_rows(path)
        values[0]["input_sha256"] = "changed"
        from src.shared_g.artifacts import write_rows
        write_rows(path, values)
        with self.assertRaisesRegex(RuntimeError, "formal_judgment_binding_drift"):
            run.status("nfcorpus")

    def test_calibration_drift_is_not_reinterpreted_as_a_new_threshold(self) -> None:
        self.prepare_legacy()
        run, _ = self.activate_nli()
        calibration = read_json(self.root / "calibration.json")
        calibration["selected_config"]["threshold"] = 0.3
        write_json_atomic(self.root / "calibration.json", calibration)
        with self.assertRaisesRegex(RuntimeError, "formal_scoring_input_drift"):
            run.score("nfcorpus")

    def test_inherited_response_drift_and_mismatched_model_are_rejected(self) -> None:
        self.prepare_legacy()
        run, backend = self.activate_nli()
        backend.identity = {"model_id": "another-model", "revision": "other"}
        with self.assertRaisesRegex(RuntimeError, "nli_backend_identity_drift"):
            run.score("nfcorpus")
        with self.store.path("initial_responses.jsonl", "nfcorpus").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(RuntimeError, "formal_scoring_input_drift"):
            run.status("nfcorpus")

    def test_complete_suite_reports_source_macro_and_preserves_old_results(self) -> None:
        self.freeze_all()
        for dataset in self.config.datasets:
            self.complete_cell(dataset)
        run, _ = self.activate_nli()
        self.assertIsNone(run.report_suite()["macro_auc"])
        for dataset in self.config.datasets:
            self.assertTrue(run.score(dataset)["complete"])
        result = run.report_suite()
        self.assertTrue(result["complete"])
        self.assertEqual(result["statistical_unit"], "source_document")
        self.assertEqual(set(result["macro_auc"]), {"local_only", "correct_anchor", "remote_only"})
        self.assertEqual(result, run.report_suite())

    def test_zero_triggered_slots_is_a_complete_binary_cell(self) -> None:
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        client = Mock()
        client.generate_with_metadata.return_value = self.result("I do not know the answer.", "victim")
        with patch("src.shared_g.victim.build_victim_client", return_value=(client, self.profiles["victim"])):
            run_victim(self.config, self.store, "nfcorpus", False)
        run, _ = self.activate_nli()
        state = run.score("nfcorpus")
        self.assertEqual(state["followup"]["planned"], 0)
        self.assertEqual(state["initial"]["labels"], {"not_correct": 12})
        self.assertTrue(state["complete"])
        run.report("nfcorpus")
        self.assertEqual([r["correct_anchor"] for r in read_rows(run.path("scores.jsonl", "nfcorpus"))], [0.0] * 4)

    def test_formal_semantic_path_uses_calibrated_threshold_and_no_membership(self) -> None:
        self.prepare_legacy("A broad sample of adults with the condition participated.", followup=False)
        run, backend = self.activate_nli()
        backend.values = {"entailment": 0.55, "neutral": 0.3, "contradiction": 0.15}
        state = run.score("nfcorpus")
        self.assertEqual(state["initial"]["label_sources"].get("nli"), 4)
        self.assertEqual(state["initial"]["labels"], {"correct": 12})
        self.assertEqual(state["followup"]["planned"], 24)
        for premise, hypothesis in backend.pairs:
            self.assertNotIn("KB_Member", premise + hypothesis)
            self.assertNotIn("True_Non_Member", premise + hypothesis)

    def test_changed_frozen_gate_is_rejected_before_any_new_request(self) -> None:
        self.prepare_legacy()
        run, _ = self.activate_nli()
        run.score("nfcorpus")
        path = run.path("followup_gate.json", "nfcorpus")
        gate = read_json(path)
        gate["query_ids"] = []
        write_json_atomic(path, gate)
        with self.assertRaisesRegex(RuntimeError, "frozen_followup_gate_drift"):
            run.run_victim("nfcorpus", True)

    def test_partial_inherited_retrieval_is_copied_before_continuation(self) -> None:
        from src.shared_g.artifacts import write_rows

        self.freeze_all()
        self.install_retrieval("nfcorpus")
        original = self.store.path("retrieval.jsonl", "nfcorpus")
        full = read_rows(original)
        write_rows(original, full[:5])
        before = sha256_file(original)
        run, _ = self.activate_nli()

        def finish(config, store, dataset, max_new):
            self.assertNotEqual(store.path("retrieval.jsonl", dataset), original)
            write_rows(store.path("retrieval.jsonl", dataset), full)
            return {"complete": True, "new_queries": len(full) - 5}

        with patch("src.shared_g.retrieval.retrieve", side_effect=finish):
            self.assertTrue(run.retrieve("nfcorpus")["complete"])
        self.assertEqual(before, sha256_file(original))
        run.validate(frozen=True)

    def test_scidocs_only_keeps_nfcorpus_legacy_completion_without_new_labels(self) -> None:
        self.freeze_all()
        self.complete_cell("nfcorpus")
        self.install_retrieval("scidocs")
        before = {p: sha256_file(p) for p in self.config.output.rglob("*") if p.is_file()}
        run, _ = self.activate_nli(["scidocs"])
        with self.assertRaisesRegex(ValueError, "dataset_not_enabled"):
            run.score("nfcorpus")
        client = self.victim_client()
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])):
            initial = run.run_victim("scidocs", False)
            self.assertTrue(initial["complete"])
            self.assertFalse(initial["cell_complete"])
            self.assertTrue(run.run_victim("scidocs", True)["complete"])
        self.assertFalse((run.config.output / "nfcorpus").exists())
        self.assertEqual(before, {p: sha256_file(p) for p in before})
        result = run.report_suite()
        self.assertEqual(set(result["per_dataset"]), {"scidocs"})
        self.assertFalse(result["full_suite_metrics_available"])
        self.assertIsNone(result["macro_auc"])

    def test_signed_diagnostic_loads_complete_v3_without_writing_formal_report(self) -> None:
        from pathlib import Path
        from src.evaluation.answer_judgment import FormalJudgmentRun

        self.prepare_legacy()
        run, _ = self.activate_nli()
        self.assertTrue(run.score("nfcorpus")["complete"])
        SignedDevelopmentScoreTests.setUpClass()
        review = SignedDevelopmentScoreTests.review
        module = self.root / "src/evaluation/answer_judgment.py"
        module.parent.mkdir(parents=True)
        module.write_bytes((review.ROOT / "src/evaluation/answer_judgment.py").read_bytes())
        before = {p: sha256_file(p) for p in self.root.rglob("*") if p.is_file()}
        with patch.object(review, "ROOT", self.root), \
                patch.object(FormalJudgmentRun, "score", side_effect=AssertionError("no scoring calls")), \
                patch.object(FormalJudgmentRun, "report", side_effect=AssertionError("no formal writes")), \
                patch("src.evaluation.answer_judgment.LocalNLIPredictor", side_effect=AssertionError("no NLI")), \
                patch("src.llm.factory.build_victim_client", side_effect=AssertionError("no victim")):
            rows, metadata, hashes = review.load_signed_formal(run.config.output, "nfcorpus", project_root=self.root)
        self.assertEqual(len(rows), 4)
        self.assertEqual(metadata["baseline_origin"], "reconstructed_from_saved_v3_judgments")
        self.assertFalse(metadata["original_complete_report_available"])
        self.assertIsNone(metadata["original_scores_reproduced_exactly"])
        self.assertEqual(metadata["original_metrics"]["correct_anchor"]["auc"]["estimate"], 0.5)
        self.assertEqual(before, {p: sha256_file(p) for p in self.root.rglob("*") if p.is_file()})
        self.assertTrue(all(sha256_file(Path(path)) == digest for path, digest in hashes.items()))


    def test_mainline_rescores_v3_end_to_end_without_model_or_old_report(self) -> None:
        import yaml
        from src.evaluation import source_scoring
        from src.evaluation.answer_judgment import FormalJudgmentRun

        self.prepare_legacy()
        run, _ = self.activate_nli()
        self.assertTrue(run.score("nfcorpus")["complete"])
        module = self.root / "src/evaluation/answer_judgment.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_bytes((source_scoring.ROOT / "src/evaluation/answer_judgment.py").read_bytes())
        spec = yaml.safe_load((source_scoring.ROOT / "configs/v25_signed_scoring.yaml").read_text(encoding="utf-8"))
        spec.update(inputs={"nfcorpus": str(run.config.output)}, output_dir="artifacts/v25/scoring/signed")
        spec["evaluation"]["bootstrap_samples"] = 20
        path = self.root / "signed.yaml"
        path.write_text(yaml.safe_dump(spec), encoding="utf-8")
        before = {p: sha256_file(p) for p in self.root.rglob("*") if p.is_file()}
        with patch.object(FormalJudgmentRun, "score", side_effect=AssertionError("no new judgment")), \
                patch.object(FormalJudgmentRun, "report", side_effect=AssertionError("no old score report")), \
                patch("src.evaluation.answer_judgment.LocalNLIPredictor", side_effect=AssertionError("no NLI")), \
                patch("src.llm.factory.build_victim_client", side_effect=AssertionError("no victim")), \
                patch("src.shared_g.retrieval.retrieve", side_effect=AssertionError("no retrieval")):
            result = source_scoring.evaluate(path, "nfcorpus", project_root=self.root)
        self.assertEqual(result["status"], "mainline_scoring_complete")
        self.assertEqual(result["source_count"], 4)
        self.assertFalse(result["metadata"]["original_complete_report_available"])
        self.assertEqual(result["new_calls"], {"api": 0, "victim": 0, "retriever": 0, "nli": 0})
        self.assertEqual(before, {p: sha256_file(p) for p in before})
        self.assertFalse((run.config.output / "nfcorpus/scores.jsonl").exists())
        self.assertFalse((run.config.output / "nfcorpus/report.json").exists())
        self.assertTrue((self.root / spec["output_dir"] / "nfcorpus/report.json").is_file())


class SignedDevelopmentScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "signed_development_review", Path(__file__).resolve().parents[1] / "scripts/102_review_v25_shared_g_mechanism.py")
        cls.review = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.review)

    def fixture(self, missing=False, missing_arm="remote_only"):
        sources, plans, responses, items, predictions = [], [], [], [], []
        for number, group in enumerate(("KB_Member", "True_Non_Member")):
            key = f"source-{number}"
            source = {"source_key": key, "dataset": "scidocs", "group": group,
                      "source_hash": sha256_text(key), "normalized_text_hash": sha256_text(key + "-normalized")}
            sources.append(source)
            initial = [1, -1, 0] if number == 0 else [0, 0, -1]
            for arm in ("initial", *self.review.SIGNED_ARMS):
                for slot in range(3):
                    query = {"query_id": f"{key}-{arm}-{slot}", "source_key": key,
                             "dataset": "scidocs", "group": group, "arm": arm, "slot_index": slot,
                             "question": f"Question {slot}?", "answer": "Answer"}
                    plans.append(query)
                    if arm != "initial" and (number != 0 or slot == 2 or (missing and arm == missing_arm and slot == 0)):
                        continue
                    outcome = initial[slot] if arm == "initial" else 1
                    response = {field: query[field] for field in ("query_id", "source_key", "arm", "slot_index")}
                    response.update(status="completed", response="Answer" if outcome == 1 else "Other")
                    responses.append(response)
                    items.append({"query": query, "response": response, "source_hash": source["source_hash"],
                                  "query_sha256": sha256_obj(query), "response_sha256": sha256_text(response["response"]),
                                  "cohort": "development"})
                    judgment = {"label": "correct" if outcome == 1 else "not_correct", "status": "resolved",
                                "score": int(outcome == 1), "reason": "refused" if outcome == -1 else "rule",
                                "binding": {"query_id": query["query_id"], "source_key": key, "source_hash": source["source_hash"],
                                            "original_query_sha256": sha256_obj(query), "response_sha256": sha256_text(response["response"])}}
                    predictions.append({"query_id": query["query_id"], "judgment": judgment})
        remote = {(query['source_key'], query['slot_index']): query for query in plans if query['arm'] == 'remote_only'}
        by_id = {row['query_id']: row['judgment'] for row in predictions}
        for item in items:
            query = item['query']
            if query['arm'] == 'correct_anchor':
                paired = remote[query['source_key'], query['slot_index']]
                item.update(paired_query=paired, paired_query_sha256=sha256_obj(paired))
                by_id[query['query_id']]['binding'].update(paired_query_id=paired['query_id'], paired_query_sha256=sha256_obj(paired))
        return items, predictions, plans, responses, sources, [], "development"

    def test_refusal_is_minus_one_but_never_opens_a_gate(self) -> None:
        rows = self.review.signed_source_features(*self.fixture())
        member = rows[0]
        self.assertEqual(member["initial_outcomes"], [1, -1, 0])
        self.assertTrue(member["complete"])
        for arm in self.review.SIGNED_ARMS:
            self.assertEqual(member["arms"][arm]["correct"], 1)
            self.assertEqual(len(member["arms"][arm]["historical_outside_gate"]), 1)
            self.assertEqual(self.review.signed_score_bounds(member, arm, 1, "old"), (2, 2))
            self.assertEqual(self.review.signed_score_bounds(member, arm, 1, "new"), (1, 1))

    def test_missing_response_has_bounds_and_lambda_zero_is_exact(self) -> None:
        member = self.review.signed_source_features(*self.fixture(missing=True))[0]
        self.assertFalse(member["complete"])
        self.assertEqual(self.review.signed_score_bounds(member, "remote_only", 2, "old"), (1, 3))
        self.assertEqual(self.review.signed_score_bounds(member, "remote_only", 2, "new"), (-2, 2))
        self.assertEqual(self.review.signed_score_bounds(member, "remote_only", 0, "new"), (0, 0))
        with self.assertRaisesRegex(ValueError, "no_point_score"):
            self.review.paired_signed_grid([member], [0, 1], 20, 1)

    def test_missing_judgment_is_not_a_missing_victim_response(self) -> None:
        fixture = list(self.fixture())
        query_id = "source-0-remote_only-0"
        fixture[0] = [row for row in fixture[0] if row["query"]["query_id"] != query_id]
        features = self.review.signed_source_features(*fixture)
        self.assertEqual(features[0]["arms"]["remote_only"]["missing_queries"][0]["reason"], "missing_saved_judgment")

    def test_duplicate_slots_and_incomplete_initials_are_rejected(self) -> None:
        fixture = list(self.fixture())
        extra = {**fixture[2][0], "query_id": "duplicate-slot"}
        fixture[2] = [*fixture[2], extra]
        with self.assertRaisesRegex(ValueError, "duplicate_source_slots"):
            self.review.signed_source_features(*fixture)
        fixture = list(self.fixture())
        fixture[0] = fixture[0][1:]
        with self.assertRaisesRegex(ValueError, "incomplete_initial_source"):
            self.review.signed_source_features(*fixture)

    def test_input_binding_and_formal_identity_overlap_fail_closed(self) -> None:
        fixture = list(self.fixture())
        fixture[1][0]["judgment"]["binding"]["response_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "identity_drift"):
            self.review.signed_source_features(*fixture)
        for field in ("source_key", "source_hash", "normalized_text_hash"):
            fixture = list(self.fixture())
            formal = {"source_key": "formal", "source_hash": "formal-hash", "normalized_text_hash": "formal-normalized"}
            formal[field] = fixture[4][0]["normalized_text_hash"] if field == "source_hash" else fixture[4][0][field]
            fixture[5] = [formal]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "formal_source_overlap"):
                self.review.signed_source_features(*fixture)

    def test_invalid_judgments_and_invalid_weights_do_not_become_zero(self) -> None:
        good = {"status": "resolved", "label": "correct", "score": 1, "reason": "rule"}
        for change in ({"status": "invalid"}, {"score": -1}, {"reason": "refused"}, {"label": None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.review.signed_outcome({**good, **change})
        for weight in (-1, float("nan"), float("inf")):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                self.review.validate_signed_lambdas([weight])

    def test_missing_or_changed_paired_target_fails_before_scoring(self) -> None:
        fixture = list(self.fixture())
        item = next(row for row in fixture[0] if row['query']['arm'] == 'correct_anchor')
        item.pop('paired_query')
        with self.assertRaisesRegex(ValueError, 'paired_target_binding_drift'):
            self.review.signed_source_features(*fixture)
        fixture = list(self.fixture())
        fixture[1][0]['judgment'] = {'label': None, 'score': None, 'status': 'invalid', 'reason': 'missing_paired_target_question'}
        with self.assertRaisesRegex(ValueError, 'invalid_or_inconsistent'):
            self.review.signed_source_features(*fixture)

    def statistical_rows(self):
        base = self.review.signed_source_features(*self.fixture())
        rows = []
        for dataset in ("one", "two"):
            for group_row in base:
                for i in range(2):
                    row = copy.deepcopy(group_row)
                    row.update(dataset=dataset, source_key=f"{dataset}-{group_row['source_key']}-{i}")
                    rows.append(row)
        return rows

    def test_source_paired_statistics_are_deterministic_and_identical_methods_have_zero_delta(self) -> None:
        rows = self.statistical_rows()
        for row in rows:
            row["initial_refused"] = 0
        first = self.review.paired_signed_grid(rows, [0, 1, 2], 40, 8)
        self.assertEqual(first, self.review.paired_signed_grid(list(reversed(rows)), [2, 1, 0], 40, 8))
        for entry in first:
            self.assertEqual(entry["macro"]["delta_auc"], 0)
            self.assertEqual(entry["macro"]["delta_ci95"], [0, 0])
            if "primary_test" in entry:
                self.assertEqual(entry["primary_test"]["p_holm_two_arms"], 1)

    def test_auc_missing_bounds_contain_each_possible_completion(self) -> None:
        from itertools import product

        rows = self.statistical_rows()
        rows = [row for row in rows if row["dataset"] == "one"]
        for row in rows[::2]:
            row["arms"]["remote_only"].update(correct=0, refused=0, missing=1)
        bounds = next(row for row in self.review.signed_auc_bounds(rows, [1]) if row["arm"] == "remote_only")["macro"]
        for values in product((-1, 0, 1), repeat=2):
            full = copy.deepcopy(rows)
            for row, value in zip(full[::2], values):
                row["arms"]["remote_only"].update(correct=int(value == 1), refused=int(value == -1), missing=0)
            point = next(row for row in self.review.signed_auc_bounds(full, [1]) if row["arm"] == "remote_only")["macro"]
            for method in ("old", "new"):
                self.assertLessEqual(bounds[method][0], point[method][0])
                self.assertGreaterEqual(bounds[method][1], point[method][1])

    def backfill_fixture(self, directory, missing_arm="remote_only"):
        import ast
        from pathlib import Path

        fixture = self.fixture(missing=True, missing_arm=missing_arm)
        features = self.review.signed_source_features(*fixture)
        cohort, output = directory / "cohort", directory / "backfill"
        cohort.mkdir()
        template_tree = ast.parse((self.review.ROOT / "scripts/95_run_v25_shared_g_pilot.py").read_text(encoding="utf-8"))
        template = next(ast.literal_eval(node.value) for node in template_tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "RAG_PROMPT" for t in node.targets))
        plans, sources = fixture[2], fixture[4]
        plan_path = cohort / "query_plan.jsonl"
        plan_path.write_text("".join(json.dumps(row) + "\n" for row in plans), encoding="utf-8")
        index_sources = [sources[0]]
        retrievals = []
        for query in plans:
            prompt = template.format(contexts="Context", query=query["question"])
            retrievals.append({**{field: query[field] for field in ("query_id", "source_key", "dataset", "arm", "slot_index")},
                               "query_plan_sha256": sha256_file(plan_path),
                               "index_identity": sha256_obj([(sources[0]["source_key"], sources[0]["source_hash"])]),
                               "retrieved_chunks": [{"source_key": sources[0]["source_key"], "source_hash": sources[0]["source_hash"], "text": "Context"}],
                               "context_sha256": sha256_text("Context"), "prompt_sha256": sha256_text(prompt)})
        (cohort / "retrieval.jsonl").write_text("".join(json.dumps(row) + "\n" for row in retrievals), encoding="utf-8")
        (cohort / "index_manifest.json").write_text(json.dumps({"sources": index_sources}), encoding="utf-8")
        profile = {"model": "test-model"}
        run = {"prompts": {"rag_sha256": sha256_text(template)}, "model_profiles": {"victim": profile},
               "runtime": {"llm_profiles_path": "unused.yaml", "victim_profile": "test",
                           "generation": {"temperature": 0, "max_tokens": 512, "request_interval_seconds": 0}}}
        (cohort / "run_config.json").write_text(json.dumps(run), encoding="utf-8")
        predictions = directory / "predictions.json"
        predictions.write_text(json.dumps(fixture[1]), encoding="utf-8")
        return cohort, predictions, features, output, profile, template, fixture[2], retrievals, index_sources

    def test_cached_prompt_and_nonmember_context_are_rejected_before_calls(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            cohort, _, features, _, _, template, plans, retrievals, members = self.backfill_fixture(Path(directory))
            query_id = features[0]["arms"]["remote_only"]["missing_queries"][0]["query_id"]
            row = next(row for row in retrievals if row["query_id"] == query_id)
            row["prompt_sha256"] = "changed"
            with self.assertRaisesRegex(ValueError, "prompt_or_context_drift"):
                self.review.cached_missing_requests(features, plans, retrievals, members, sha256_file(cohort / "query_plan.jsonl"), template)
            row["retrieved_chunks"][0]["source_key"] = "nonmember"
            with self.assertRaisesRegex(ValueError, "nonmember_or_hash_drift"):
                self.review.cached_missing_requests(features, plans, retrievals, members, sha256_file(cohort / "query_plan.jsonl"), template)

    def test_backfill_sends_only_missing_queries_and_resumes_without_calls(self) -> None:
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            cohort, predictions, features, output, profile, *_ = self.backfill_fixture(Path(directory), missing_arm="correct_anchor")
            baseline = {path: sha256_file(path) for path in cohort.iterdir()}
            client = Mock()
            client.generate_with_metadata.return_value = SimpleNamespace(
                content="Answer", provider_model_id="test-model", provider_request_id="request",
                called_at="2026-10-09T00:00:00Z", system_fingerprint=None)
            with patch("src.llm.factory.load_llm_profiles", return_value={}), \
                    patch("src.llm.factory.build_victim_client", return_value=(client, {**profile, "timeout": 60})), \
                    patch("src.llm.factory.llm_profile_identity", return_value=profile):
                result = self.review.run_missing_development(cohort, predictions, features, output, "scidocs", 1)
            self.assertEqual(result["new_calls"], 1)
            self.assertEqual(client.generate_with_metadata.call_count, 1)
            with patch("src.llm.factory.build_victim_client", side_effect=AssertionError("no repeated call")):
                self.assertEqual(self.review.run_missing_development(cohort, predictions, features, output, "scidocs", 1)["new_calls"], 0)
            self.assertEqual(baseline, {path: sha256_file(path) for path in baseline})
            self.assertEqual(len(read_rows(output / "judgment_inputs.jsonl")), 1)
            item = read_rows(output / "judgment_inputs.jsonl")[0]
            self.assertEqual(item['query']['arm'], 'correct_anchor')
            self.assertEqual(item['paired_query']['arm'], 'remote_only')
            self.assertEqual(item['paired_query_sha256'], sha256_obj(item['paired_query']))

    def test_failed_backfill_preserves_evidence_and_never_retries_silently(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            cohort, predictions, features, output, profile, *_ = self.backfill_fixture(Path(directory))
            client = Mock()
            client.generate_with_metadata.side_effect = ConnectionError("private transport detail")
            with patch("src.llm.factory.load_llm_profiles", return_value={}), \
                    patch("src.llm.factory.build_victim_client", return_value=(client, {**profile, "timeout": 60})), \
                    patch("src.llm.factory.llm_profile_identity", return_value=profile), \
                    self.assertRaisesRegex(RuntimeError, "without_automatic_resend"):
                self.review.run_missing_development(cohort, predictions, features, output, "scidocs", 1)
            self.assertNotIn("private transport detail", (output / "followup_responses.jsonl").read_text())
            with patch("src.llm.factory.build_victim_client", side_effect=AssertionError("no retry")), \
                    self.assertRaisesRegex(ValueError, "uncertain_response"):
                self.review.run_missing_development(cohort, predictions, features, output, "scidocs", 1)


class OfflineReCheckAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SignedDevelopmentScoreTests.setUpClass()
        cls.review = SignedDevelopmentScoreTests.review

    def rows(self):
        result = []
        initials = ([1, 1, 0], [1, 0, 0], [1, 1, 1], [0, -1, 0])
        for group in self.review.SIGNED_GROUPS:
            for i, initial in enumerate(initials):
                key = f"{group}-{i}"
                k = initial.count(1)
                correct, refused = ((0, 1), (1, 0), (k, 0), (0, 0))[i]
                row = dict(source_key=key, dataset="trec-covid", group=group,
                           source_hash=sha256_text(key), normalized_text_hash=sha256_text(key + "-text"),
                           initial_outcomes=list(initial), initial_correct=k,
                           initial_refused=initial.count(-1), initial_wrong=initial.count(0),
                           initial_query_ids=[f"{key}-initial-{slot}" for slot in range(3)],
                           complete=True, arms={})
                for arm in self.review.SIGNED_ARMS:
                    r, v = (correct, refused) if arm == "correct_anchor" else (0, 0)
                    row["arms"][arm] = dict(correct=r, refused=v, wrong=k-r-v, missing=0,
                                            missing_queries=[], historical_outside_gate=[],
                                            gated_query_ids=[f"{key}-{arm}-{slot}" for slot in range(k)])
                result.append(row)
        return self.review.offline_source_rows(result)

    def test_source_transitions_distinguish_correction_new_false_positive_and_member_loss(self) -> None:
        rows = self.rows()
        # 非成员K=3的一篇仍然误报，其余一篇纠正、一篇新增、一篇保持拒绝。
        entry = next(row for row in rows if row["source_key"] == "True_Non_Member-2")
        entry["arms"]["correct_anchor"].update(correct=1, refused=1, wrong=1)
        rows = self.review.offline_source_rows(rows)
        transitions = self.review.offline_transitions(rows, 100, 8)
        for group in self.review.SIGNED_GROUPS:
            t = next(t for t in transitions if t["group"] == group and t["arm"] == "correct_anchor")
            self.assertEqual(t["cells"], dict(negative_negative=1, negative_positive=1,
                                             positive_negative=1, positive_positive=1))
            self.assertEqual(t["positive_retention"]["estimate"], .5)
            self.assertEqual(t["positive_loss"]["estimate"], .5)
            self.assertEqual(t["new_positive"]["estimate"], .5)
            self.assertEqual(t["delta_positive_rate"], 0)
            self.assertEqual(t["paired_test"]["p_raw"], 1)
        self.assertEqual(transitions, self.review.offline_transitions(list(reversed(rows)), 100, 8))

    def test_costs_count_shared_initials_once_and_keep_K_zero_sources(self) -> None:
        cost = self.review.offline_costs(self.rows(), 60, 7)
        total = next(e for e in cost["summary"] if e["group"] == "All")
        self.assertEqual(total["sources"], 8)
        self.assertEqual(total["initial_calls"], 24)
        self.assertEqual(total["main_logical_calls"], 36)
        self.assertEqual(total["both_arms_logical_calls"], 48)
        self.assertEqual(total["mean"], 4.5)
        self.assertEqual(total["distribution"], {"3": 2, "4": 2, "5": 2, "6": 2})
        for entry in cost["by_membership_and_K"]:
            if entry["K"] == 0:
                self.assertEqual(entry["sources"], 1)
                self.assertEqual(entry["main_calls_per_source"], 3)
                self.assertIsNone(entry["arms"]["correct_anchor"]["followup_rates_source_bootstrap"]["correct"]["estimate"])
        self.assertIsNone(self.review.offline_binomial_rate(0, 0)["ci95"])
        self.assertGreater(self.review.offline_binomial_rate(0, 1000)["ci95"][1], 0)

    def test_slot_correlations_use_source_bootstrap_for_followup_rate(self) -> None:
        rows = [row for row in self.rows() if row["initial_correct"] == 3]
        for row in list(rows):
            clone = copy.deepcopy(row)
            clone.update(source_key=row["source_key"] + "-clone")
            clone["arms"]["correct_anchor"].update(correct=0, refused=3, wrong=0)
            rows.append(clone)
        costs = self.review.offline_costs(rows, 200, 9)
        for entry in costs["by_membership_and_K"]:
            if entry["K"] == 3:
                rates = entry["arms"]["correct_anchor"]["followup_rates_source_bootstrap"]
                self.assertEqual(entry["sources"], 2)
                self.assertEqual(rates["correct"]["estimate"], .5)
                self.assertEqual(rates["correct"]["ci95"], [0, 1])

    def test_all_tied_scores_and_low_fpr_are_valid_and_deterministic(self) -> None:
        rows = self.rows()
        entries, draws = self.review.offline_paired_metrics(rows, {"tie": [0.] * len(rows)}, 50, 3)
        self.assertEqual(entries["tie"]["auc"], {"estimate": .5, "ci95": [.5, .5]})
        self.assertEqual(entries["tie"]["average_precision"]["estimate"], .5)
        point = entries["tie"]["low_fpr"][2]
        self.assertEqual(point["TPR"], 0)
        self.assertEqual(point["threshold"], float("inf"))
        self.assertEqual(point["TPR_source_bootstrap_ci95_reselecting_roc_point"], [0, 0])
        self.assertEqual(entries, self.review.offline_paired_metrics(rows, {"tie": [0.] * len(rows)}, 50, 3)[0])
        self.assertEqual(draws["tie/auc"].shape, (50,))

    def test_corrupted_counts_duplicate_source_hash_and_incomplete_gate_fail_closed(self) -> None:
        rows = self.rows()
        rows[0]["initial_correct"] += 1
        with self.assertRaises(ValueError):
            self.review.offline_source_rows(rows)
        rows = self.rows()
        rows[1]["source_hash"] = rows[0]["normalized_text_hash"]
        with self.assertRaisesRegex(ValueError, "duplicate_offline_source_identity"):
            self.review.offline_source_rows(rows)
        rows = self.rows()
        rows[0]["arms"]["correct_anchor"]["missing"] = 1
        rows[0]["complete"] = False
        with self.assertRaises(ValueError):
            self.review.offline_source_rows(rows)
        with self.assertRaisesRegex(ValueError, "source_score_vector_length_mismatch"):
            self.review.offline_paired_metrics(self.rows(), {"bad": [1.]}, 50, 3)

    def test_zero_refusal_penalties_give_identical_paired_component_effects(self) -> None:
        rows = self.rows()
        for row in rows:
            row["initial_outcomes"] = [max(0, value) for value in row["initial_outcomes"]]
            row["initial_wrong"] += row["initial_refused"]
            row["initial_refused"] = 0
            for arm in self.review.SIGNED_ARMS:
                row["arms"][arm]["wrong"] += row["arms"][arm]["refused"]
                row["arms"][arm]["refused"] = 0
        report = self.review.offline_components(self.review.offline_source_rows(rows), 40, 6)
        self.assertEqual(len(report["entries"]), 11)
        for effect in report["paired_contrasts"]:
            if effect["before"] != "C_minus_U":
                self.assertEqual(effect["delta"], 0)
                self.assertEqual(effect["ci95"], [0, 0])


class SignedFormalScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SignedDevelopmentScoreTests.setUpClass()
        cls.review = SignedDevelopmentScoreTests.review

    def fixture(self):
        from src.shared_g.scoring import REPAIRED_MATCHER

        sources, plans, initial, followups, saved = [], [], [], [], []
        for number, group in enumerate(self.review.SIGNED_GROUPS):
            key = f"formal-{number}"
            sources.append({"source_key": key, "dataset": "nfcorpus", "group": group,
                            "source_hash": sha256_text(key), "normalized_text_hash": sha256_text(key + "-text")})
            values = ["Paris", "Unknown", "Rome"] if number == 0 else ["Unknown", "Rome", "Rome"]
            for arm in ("initial", *self.review.SIGNED_ARMS):
                for slot in range(3):
                    query = {"query_id": f"{key}-{arm}-{slot}", "source_key": key, "dataset": "nfcorpus",
                             "arm": arm, "slot_index": slot, "question": "Which city is the capital of France?",
                             "answer": "Paris", "answer_aliases": []}
                    plans.append(query)
                    if arm != "initial" and (number != 0 or slot != 0):
                        continue
                    response = {field: query[field] for field in ("query_id", "source_key", "arm", "slot_index")}
                    response.update(status="completed", response=values[slot] if arm == "initial" else
                                    ("Paris" if arm == "correct_anchor" else "Unknown"))
                    (initial if arm == "initial" else followups).append(response)
            bits = [1, 0, 0] if number == 0 else [0, 0, 0]
            saved.append({"source_key": key, "dataset": "nfcorpus", "group": group, "initial_bits": bits,
                          "local_only": sum(bits), "correct_anchor_bits": bits, "correct_anchor": 2.0 * sum(bits),
                          "remote_only_bits": [0, 0, 0], "remote_only": float(sum(bits))})
        return sources, plans, initial, followups, {}, saved, REPAIRED_MATCHER

    def test_ambiguous_refusal_dispute_and_negation_are_distinguished(self) -> None:
        cases = [
            ({"label": "ambiguous"}, "abstention_without_answer", -1),
            ({"label": "ambiguous"}, "explicit_abstention_outside_answer", -1),
            ({"label": "ambiguous"}, "negation_before_answer_not_aligned_with_question", 0),
            ({"label": "ambiguous", "review_status": "uncertain"}, "abstention_without_answer", 0),
            ({"label": "correct", "review_status": "resolved"}, "abstention_without_answer", 1),
            ({"label": "incorrect"}, "numeric_boundary_conflict", 0),
        ]
        for judgment, reason, expected in cases:
            with self.subTest(judgment=judgment, reason=reason):
                self.assertEqual(self.review.signed_formal_outcome(judgment, reason), expected)
        with self.assertRaisesRegex(ValueError, "invalid_formal_judgment"):
            self.review.signed_formal_outcome({"label": "invalid"}, "invalid_response")

    def test_same_formal_gate_and_scores_are_preserved(self) -> None:
        rows, counts = self.review.signed_formal_features(*self.fixture())
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row["count"] for row in counts), 8)
        member = rows[0]
        self.assertEqual(member["initial_outcomes"], [1, -1, 0])
        self.assertEqual(self.review.signed_score_bounds(member, "correct_anchor", 1, "old"), (2, 2))
        self.assertEqual(self.review.signed_score_bounds(member, "correct_anchor", 1, "new"), (1, 1))
        self.assertEqual(self.review.signed_score_bounds(member, "remote_only", 1, "new"), (-1, -1))
        for row in rows:
            for arm in self.review.SIGNED_ARMS:
                self.assertEqual(len(row["arms"][arm]["gated_query_ids"]), row["initial_correct"])

    def test_changed_saved_original_score_is_rejected(self) -> None:
        fixture = self.fixture()
        fixture[5][0]["correct_anchor"] = 3.0
        with self.assertRaisesRegex(ValueError, "original_scores_differ"):
            self.review.signed_formal_features(*fixture)

    def test_missing_or_refusal_triggered_followup_is_rejected(self) -> None:
        fixture = self.fixture()
        fixture[3].pop()
        with self.assertRaisesRegex(RuntimeError, "followup_gate_missing_or_extra"):
            self.review.signed_formal_features(*fixture)
        fixture = self.fixture()
        extra = dict(fixture[3][0], query_id="formal-0-correct_anchor-1", slot_index=1)
        fixture[3].append(extra)
        with self.assertRaisesRegex(RuntimeError, "followup_gate_missing_or_extra"):
            self.review.signed_formal_features(*fixture)

    def test_formal_source_hash_and_query_bindings_fail_closed(self) -> None:
        fixture = self.fixture()
        fixture[0][1]["normalized_text_hash"] = fixture[0][0]["source_hash"]
        with self.assertRaisesRegex(ValueError, "duplicate_source_identity"):
            self.review.signed_formal_features(*fixture)
        fixture = self.fixture()
        fixture[2][0]["source_key"] = "formal-1"
        with self.assertRaisesRegex(ValueError, "response_query_identity_drift"):
            self.review.signed_formal_features(*fixture)
        fixture = self.fixture()
        fixture[1].append(dict(fixture[1][0], query_id="duplicated-slot"))
        with self.assertRaisesRegex(ValueError, "duplicate_source_slots"):
            self.review.signed_formal_features(*fixture)

    def test_failed_formal_response_is_not_scored_as_zero(self) -> None:
        fixture = self.fixture()
        fixture[2][0]["status"] = "failed"
        with self.assertRaisesRegex(RuntimeError, "initial_response_invalid"):
            self.review.signed_formal_features(*fixture)

    def test_compressed_bootstrap_uses_source_counts_not_type_counts(self) -> None:
        base = self.review.signed_formal_features(*self.fixture())[0][0]
        rows = []
        for group, scores in (("KB_Member", [3, 3, 3, 0]), ("True_Non_Member", [2, 2, 0, 0, 0, 0])):
            for number, score in enumerate(scores):
                row = copy.deepcopy(base)
                row.update(source_key=f"{group}-{number}", group=group, initial_correct=score, initial_refused=0)
                for arm in self.review.SIGNED_ARMS:
                    row["arms"][arm].update(correct=0, refused=0, missing=0)
                rows.append(row)
        rng = Mock(wraps=self.review.np.random.default_rng(13))
        with patch.object(self.review.np.random, "default_rng", return_value=rng):
            result = self.review.paired_signed_grid(rows, [0, 1], 100, 13)
        draws = rng.multinomial.call_args_list
        self.assertEqual([call.args[0] for call in draws], [4, 6])
        self.review.np.testing.assert_allclose(draws[0].args[1], [0.25, 0.75])
        self.review.np.testing.assert_allclose(draws[1].args[1], [4 / 6, 2 / 6])
        for entry in result:
            self.assertAlmostEqual(entry["macro"]["old"]["auc"], 5 / 6)
            self.assertEqual(entry["macro"]["delta_ci95"], [0, 0])

    def nli_fixture(self):
        from src.evaluation.answer_judgment import TARGETED_JUDGMENT_VERSION, automatic_target, paired_targets

        sources, plans, initial, followups, *_ = self.fixture()
        sby, pby = ({row[key]: row for row in rows} for rows, key in ((sources, "source_key"), (plans, "query_id")))
        paired, items, entries = paired_targets(plans), {}, {}
        for response in initial + followups:
            qid = response["query_id"]
            query, source = pby[qid], sby[response["source_key"]]
            item = {"query": query, "response": response, "paired_query": paired.get(qid), "source_hash": source["source_hash"]}
            _, binding = automatic_target(query, paired.get(qid))
            binding.update(query_id=qid, source_key=query["source_key"], source_hash=source["source_hash"],
                           response_sha256=sha256_text(response["response"]))
            correct, refused = response["response"] == "Paris", response["response"] == "Unknown"
            judgment = {"version": TARGETED_JUDGMENT_VERSION, "status": "resolved", "score": int(correct),
                        "label": "correct" if correct else "not_correct", "reason": "refused" if refused else "rule",
                        "label_source": "rule", "binding": binding}
            entry = {"query_id": qid, "input_sha256": sha256_obj(item), "judgment": judgment}
            entry["record_sha256"] = sha256_obj(entry)
            items[qid], entries[qid] = item, entry
        return sources, plans, items, entries

    def test_saved_v3_refusal_penalty_preserves_correctness_gate(self) -> None:
        rows, counts = self.review.signed_nli_formal_features(*self.nli_fixture())
        self.assertEqual(rows[0]["initial_outcomes"], [1, -1, 0])
        self.assertEqual(rows[1]["initial_outcomes"], [-1, 0, 0])
        self.assertEqual(sum(row["count"] for row in counts), 8)
        self.assertEqual(self.review.signed_score_bounds(rows[0], "correct_anchor", 1, "old"), (2, 2))
        self.assertEqual(self.review.signed_score_bounds(rows[0], "correct_anchor", 1, "new"), (1, 1))
        self.assertEqual(self.review.signed_score_bounds(rows[0], "remote_only", 1, "new"), (-1, -1))
        self.assertEqual(rows[1]["arms"]["correct_anchor"]["gated_query_ids"], [])

    def test_saved_v3_missing_initial_followup_or_judgment_is_rejected(self) -> None:
        for phase, error in (("initial", "incomplete_saved_nli_initial"), ("remote_only", "incomplete_saved_nli_followup")):
            fixture = self.nli_fixture()
            key = next(key for key, item in fixture[2].items() if item["query"]["arm"] == phase)
            fixture[2].pop(key)
            fixture[3].pop(key)
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, error):
                self.review.signed_nli_formal_features(*fixture)
        fixture = self.nli_fixture()
        fixture[3].pop(next(iter(fixture[3])))
        with self.assertRaisesRegex(ValueError, "missing_or_unexpected"):
            self.review.signed_nli_formal_features(*fixture)

    def test_saved_v3_rejects_identity_pair_version_and_invalid_judgment_drift(self) -> None:
        for change, error in (("paired_binding", "target_binding_drift"), ("version", "version_drift"),
                              ("invalid", "invalid_or_inconsistent"), ("response", "input_or_version_drift"),
                              ("source", "duplicate_source_identity")):
            fixture = self.nli_fixture()
            qid = next(key for key, item in fixture[2].items() if item["query"]["arm"] == "correct_anchor")
            entry = fixture[3][qid]
            if change == "paired_binding":
                entry["judgment"]["binding"]["paired_query_sha256"] = "changed"
            elif change == "version":
                entry["judgment"]["version"] = "binary_rules_nli_v2"
            elif change == "invalid":
                entry["judgment"].update(status="invalid", label=None, score=None)
            elif change == "response":
                fixture[2][qid]["response"]["source_key"] = "formal-1"
            else:
                fixture[0][1]["normalized_text_hash"] = fixture[0][0]["source_hash"]
            entry["record_sha256"] = sha256_obj({k: v for k, v in entry.items() if k != "record_sha256"})
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, error):
                self.review.signed_nli_formal_features(*fixture)

    def test_secondary_metrics_match_independent_sklearn_and_real_roc_points(self) -> None:
        from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score,
                                     f1_score, matthews_corrcoef, precision_score, recall_score)

        base = self.review.signed_nli_formal_features(*self.nli_fixture())[0][0]
        rows = []
        examples = {"KB_Member": [(2, 1, 2, 0, 1, 1), (1, 0, 0, 1, 1, 0), (0, 2, 0, 0, 0, 0)],
                    "True_Non_Member": [(2, 0, 1, 1, 0, 2), (1, 2, 1, 0, 0, 1), (0, 1, 0, 0, 0, 0), (0, 3, 0, 0, 0, 0)]}
        for group, vectors in examples.items():
            for i, (correct, refused, anchor, anchor_refused, remote, remote_refused) in enumerate(vectors):
                row = copy.deepcopy(base)
                row.update(source_key=f"{group}-{i}", group=group, initial_correct=correct, initial_refused=refused)
                for arm, r, v in (("correct_anchor", anchor, anchor_refused), ("remote_only", remote, remote_refused)):
                    row["arms"][arm].update(correct=r, refused=v, missing=0)
                rows.append(row)
        result = self.review.signed_secondary_metrics(rows, 60, 8)
        self.assertEqual(result, self.review.signed_secondary_metrics(list(reversed(rows)), 60, 8))
        labels = [row["group"] == "KB_Member" for row in rows]
        for entry in result["entries"]:
            values = [self.review.signed_score_bounds(row, entry["arm"], 1, entry["method"])[0] for row in rows]
            predictions = [value >= 2 for value in values]
            expected = {"accuracy": accuracy_score(labels, predictions), "balanced_accuracy": balanced_accuracy_score(labels, predictions),
                        "precision": precision_score(labels, predictions, zero_division=0), "recall": recall_score(labels, predictions),
                        "f1": f1_score(labels, predictions), "mcc": matthews_corrcoef(labels, predictions),
                        "average_precision": average_precision_score(labels, values)}
            for name, point in expected.items():
                self.assertAlmostEqual(entry["metrics"][name]["estimate"], point)
            for point in entry["low_fpr"]:
                candidates = []
                for threshold in {float("inf"), *values}:
                    tp = sum(label and value >= threshold for label, value in zip(labels, values))
                    fp = sum(not label and value >= threshold for label, value in zip(labels, values))
                    if fp / 4 <= point["target_fpr"]:
                        candidates.append((tp / 3, -fp / 4, threshold, tp, fp))
                best = max(candidates)
                self.assertEqual((point["TPR"], -point["achieved_FPR"], point["threshold"], point["true_positive_count"], point["false_positive_count"]), best)

    def test_secondary_metrics_never_fill_missing_followup_with_zero(self) -> None:
        rows = self.review.signed_nli_formal_features(*self.nli_fixture())[0]
        rows[0]["arms"]["remote_only"]["missing"] = 1
        with self.assertRaisesRegex(ValueError, "missing_followup_has_no_point_score"):
            self.review.signed_secondary_metrics(rows, 20, 8)


class SignedMainlineScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from src.evaluation import source_scoring

        SignedFormalScoreTests.setUpClass()
        cls.scoring = source_scoring

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        import yaml

        directory = tempfile.TemporaryDirectory(prefix="signed_mainline_test_")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "scoring.yaml"
        self.config = yaml.safe_load((self.scoring.ROOT / "configs/v25_signed_scoring.yaml").read_text(encoding="utf-8"))
        self.config.update(inputs={"nfcorpus": "input"}, output_dir="artifacts/v25/scoring/test")
        self.config["evaluation"]["bootstrap_samples"] = 20
        self.save_config()
        fixture = SignedFormalScoreTests()
        self.features = self.scoring.signed_nli_formal_features(*fixture.nli_fixture())[0]
        self.input_file = self.root / "input.txt"
        self.input_file.write_text("fixed responses", encoding="utf-8")
        self.hashes = {str(self.input_file): sha256_file(self.input_file)}
        self.metadata = {"provider_model_ids": {"mock-victim": 8}, "system_fingerprints": {"mock-fingerprint": 8},
                         "initial_responses": 6, "followup_responses": 2}

    def save_config(self) -> None:
        import yaml

        self.path.write_text(yaml.safe_dump(self.config, sort_keys=False), encoding="utf-8")

    def run_evaluation(self, dry_run=False):
        with patch.object(self.scoring, "load_signed_formal", return_value=(self.features, self.metadata, dict(self.hashes))):
            return self.scoring.evaluate(self.path, "nfcorpus", project_root=self.root, dry_run=dry_run)

    def test_mainline_and_diagnostic_use_same_scoring_implementation(self) -> None:
        self.assertIs(SignedDevelopmentScoreTests.review.signed_score_bounds, self.scoring.signed_score_bounds)
        self.assertIs(SignedDevelopmentScoreTests.review.signed_nli_formal_features, self.scoring.signed_nli_formal_features)

    def test_inherited_defaults_are_explicitly_pending_ablation(self) -> None:
        config = self.scoring.load_scoring_config(self.path, project_root=self.root)
        self.assertEqual(config["scoring"]["lambda"], 1)
        self.assertEqual(config["scoring"]["operational_cutoff"], 2)
        self.assertEqual(config["scoring"]["parameter_source"], "inherited_previous_mainline_defaults")
        self.assertEqual(config["scoring"]["parameter_validation"], "pending_ablation")
        self.assertFalse(config["scoring"]["normalized"])

    def test_all_gated_three_slot_outcomes_match_direct_question_sum(self) -> None:
        import itertools

        # 单槽共有拒答、其他回答，以及答对后追问的三种结果。
        states = ((-1, None), (0, None), (1, -1), (1, 0), (1, 1))
        for slots in itertools.product(states, repeat=3):
            row = copy.deepcopy(self.features[0])
            initial = [value for value, _ in slots]
            followup = [value for _, value in slots if value is not None]
            row.update(initial_outcomes=initial, initial_correct=initial.count(1),
                       initial_refused=initial.count(-1), initial_wrong=initial.count(0))
            for arm in self.scoring.SIGNED_ARMS:
                row["arms"][arm].update(correct=followup.count(1), refused=followup.count(-1), wrong=followup.count(0),
                                         gated_query_ids=[f"{arm}-{index}" for index, (value, _) in enumerate(slots) if value == 1])
            for weight in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0):
                result = self.scoring.source_scores([row], weight)[0]
                self.assertEqual(result["local_only"], initial.count(1))
                self.assertEqual(result["signed_initial"], sum(initial))
                for arm in self.scoring.SIGNED_ARMS:
                    self.assertEqual(result[arm], sum(initial) + weight * sum(followup))

    def test_refused_followup_can_outweigh_correct_initial_when_lambda_exceeds_one(self) -> None:
        self.assertEqual(self.scoring.signed_value(1, 0, 0, 1, 0.5), 0.5)
        self.assertEqual(self.scoring.signed_value(1, 0, 0, 1, 1), 0)
        self.assertEqual(self.scoring.signed_value(1, 0, 0, 1, 2), -1)
        self.assertEqual(self.scoring.signed_value(3, 0, 3, 0, 1), 6)
        self.assertEqual(self.scoring.signed_value(0, 3, 0, 0, 1), -3)

    def test_missing_followup_is_rejected_even_for_zero_lambda(self) -> None:
        rows = copy.deepcopy(self.features)
        rows[0]["arms"]["remote_only"]["missing"] = 1
        with self.assertRaisesRegex(ValueError, "missing_followup"):
            self.scoring.source_scores(rows, 0)

    def test_inconsistent_counts_and_duplicate_sources_are_rejected(self) -> None:
        for mutation in ("initial", "followup", "gate", "incomplete", "duplicate"):
            rows = copy.deepcopy(self.features)
            if mutation == "initial":
                rows[0]["initial_correct"] = 3
            elif mutation == "followup":
                rows[0]["arms"]["remote_only"]["wrong"] += 1
            elif mutation == "gate":
                rows[0]["arms"]["remote_only"]["gated_query_ids"] = []
            elif mutation == "incomplete":
                rows[0]["complete"] = False
            else:
                rows.append(rows[0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.scoring.source_scores(rows, 1)

    def test_invalid_weight_cutoff_and_formula_do_not_fall_back(self) -> None:
        original = copy.deepcopy(self.config)
        changes = [("lambda", value) for value in (-1, float("nan"), float("inf"), None, True, "1")]
        changes += [("operational_cutoff", value) for value in (float("nan"), float("inf"), None, False, "2")]
        changes += [("formula", "C + lambda * R"), ("normalized", True), ("parameter_source", None)]
        for field, value in changes:
            self.config = copy.deepcopy(original)
            self.config["scoring"][field] = value
            self.save_config()
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.scoring.load_scoring_config(self.path, project_root=self.root)

    def test_output_cannot_replace_or_contain_original_inputs(self) -> None:
        for input_path, output_path in (("artifacts/v25/original", "artifacts/v25/original"),
                                        ("artifacts/v25/original", "artifacts/v25/original/new"),
                                        ("artifacts/v25/original/cell", "artifacts/v25/original")):
            self.config.update(inputs={"nfcorpus": input_path}, output_dir=output_path)
            self.save_config()
            with self.subTest(output=output_path), self.assertRaisesRegex(ValueError, "overlaps_input"):
                self.scoring.load_scoring_config(self.path, project_root=self.root)

    def test_dry_run_is_read_only_and_does_not_compute_metrics(self) -> None:
        before = {path: sha256_file(path) for path in self.root.rglob("*") if path.is_file()}
        with patch.object(self.scoring, "score_metrics", side_effect=AssertionError("no metrics")):
            result = self.run_evaluation(dry_run=True)
        self.assertEqual(result["status"], "mainline_scoring_preflight_passed")
        self.assertIsNone(result["metrics"])
        self.assertEqual(before, {path: sha256_file(path) for path in self.root.rglob("*") if path.is_file()})

    def test_new_scores_metrics_and_exact_resume_preserve_original_input(self) -> None:
        result = self.run_evaluation()
        output = self.root / self.config["output_dir"] / "nfcorpus"
        rows = read_rows(output / "scores.jsonl")
        self.assertEqual([row["correct_anchor"] for row in rows], [1.0, -1.0])
        self.assertEqual([row["remote_only"] for row in rows], [-1.0, -1.0])
        self.assertEqual(result["metrics"]["correct_anchor"]["auc"]["estimate"], 1.0)
        self.assertEqual(result["metrics"]["remote_only"]["auc"]["estimate"], 0.5)
        self.assertEqual(result["metrics"]["correct_anchor"]["fixed_cutoff"]["cutoff"], 2)
        self.assertFalse(result["used_for_parameter_selection"])
        self.assertFalse(result["formal_release_allowed"])
        self.assertIsNone(result["macro_auc"])
        before = {path: sha256_file(path) for path in self.root.rglob("*") if path.is_file()}
        with patch.object(self.scoring, "score_metrics", side_effect=AssertionError("no repeated metrics")):
            self.assertEqual(self.run_evaluation(), result)
        self.assertEqual(before, {path: sha256_file(path) for path in self.root.rglob("*") if path.is_file()})

    def test_changed_parameters_require_new_output_without_overwriting(self) -> None:
        self.run_evaluation()
        output = self.root / self.config["output_dir"] / "nfcorpus"
        before = {path: sha256_file(path) for path in output.iterdir()}
        original = copy.deepcopy(self.config["scoring"])
        for field, value in (("lambda", 0.5), ("operational_cutoff", 3)):
            self.config["scoring"] = {**original, field: value}
            self.save_config()
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "scoring_code_or_config_drift"):
                self.run_evaluation()
            self.assertEqual(before, {path: sha256_file(path) for path in output.iterdir()})

    def test_modified_input_or_saved_scores_reject_resume(self) -> None:
        self.run_evaluation()
        self.input_file.write_text("changed response", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "input_changed"):
            self.run_evaluation()
        self.input_file.write_text("fixed responses", encoding="utf-8")
        scores = self.root / self.config["output_dir"] / "nfcorpus/scores.jsonl"
        scores.write_text("[]\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "saved_source_scores_drift"):
            self.run_evaluation()

    def test_partial_output_is_preserved_and_not_completed_with_guessed_settings(self) -> None:
        output = self.root / self.config["output_dir"] / "nfcorpus"
        output.mkdir(parents=True)
        partial = output / "scores.jsonl.tmp"
        partial.write_text("partial", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "partial_scoring_output"):
            self.run_evaluation()
        self.assertEqual(partial.read_text(encoding="utf-8"), "partial")

    def test_unconfigured_dataset_and_mixed_provider_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "dataset_not_configured"):
            self.scoring.evaluate(self.path, "scidocs", project_root=self.root)
        self.metadata["provider_model_ids"]["other-model"] = 1
        with self.assertRaisesRegex(ValueError, "mixed_victim_identity"):
            self.run_evaluation()

class AllDatasetNLIEntryTests(ExecutionFixture):
    def entry(self):
        import importlib.util
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "scripts/105_run_v25_shared_g_nli.py"
        spec = importlib.util.spec_from_file_location("all_dataset_nli_entry", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_new_generator_reconnects_and_preserves_existing_answers_without_completed_cache(self):
        from src.shared_g.artifacts import ArtifactStore

        self.freeze_all()
        for dataset in self.config.datasets:
            self.install_retrieval(dataset)
        self.complete_cell("nfcorpus")
        original = {path: sha256_file(path) for path in self.config.output.rglob("*") if path.is_file()}
        self.prepare_new_generator()
        existing, backend = FormalNLIIntegrationTests.activate_nli(self)
        with patch("src.llm.factory.build_victim_client", return_value=(self.victim_client(), self.profiles["victim"])):
            existing.run_victim("nfcorpus", False, 2)
        path = ArtifactStore.path(existing, "initial_responses.jsonl", "nfcorpus")
        previous_bytes = path.read_bytes()
        previous_rows = request_records(path)
        frozen = {run.config.output / "run_config.json": sha256_file(run.config.output / "run_config.json")
                  for run in (existing, existing.parent)}
        run = self.entry().AllDatasetJudgmentRun(existing.spec_path, self.root / "missing_completed.yaml",
                                                self.root, backend=backend)
        self.assertIsNone(run.completed_run)
        self.assertEqual(run.activate(), existing.metadata)
        client = Mock()
        failure = RuntimeError("private-api-key")
        failure.__cause__ = TimeoutError("private-api-key")
        client.generate_with_metadata.side_effect = [failure, self.result("12 weeks", "victim")]
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])), \
                patch("time.sleep") as sleep, self.assertLogs("all_dataset_nli_entry", level="WARNING") as logs:
            result = run.run_victim("nfcorpus", False, 1)
        self.assertEqual(result["new_calls"], 1)
        self.assertEqual(client.generate_with_metadata.call_count, 2)
        self.assertEqual(client.generate_with_metadata.call_args_list[0], client.generate_with_metadata.call_args_list[1])
        self.assertEqual(sleep.call_args_list[0].args, (2.0,))
        self.assertTrue(path.read_bytes().startswith(previous_bytes))
        rows = request_records(path)
        self.assertEqual(rows[:2], previous_rows)
        self.assertEqual((rows[-1]["status"], rows[-1]["client_attempts"], rows[-1]["network_retry_count"]),
                         ("completed", 2, 1))
        self.assertNotIn("private-api-key", json.dumps(rows[-1]) + " ".join(logs.output))
        self.assertEqual(run.status("nfcorpus")["initial"]["invalid"], 0)
        with self.assertRaisesRegex(RuntimeError, "previous_dataset_incomplete:nfcorpus"):
            run._require_previous_cells("scidocs")
        self.assertEqual(original, {path: sha256_file(path) for path in original})
        self.assertEqual(frozen, {path: sha256_file(path) for path in frozen})

    def test_new_generator_entry_requires_all_datasets(self):
        self.freeze_all()
        for dataset in self.config.datasets:
            self.install_retrieval(dataset)
        self.prepare_new_generator()
        existing, backend = FormalNLIIntegrationTests.activate_nli(self, ["nfcorpus"])
        with self.assertRaisesRegex(ValueError, "all_dataset_scope_required"):
            self.entry().AllDatasetJudgmentRun(existing.spec_path, self.root / "missing_completed.yaml",
                                               self.root, backend=backend)

    def test_request_timeout_override_applies_to_reconnect_without_changing_frozen_config(self):
        from src.shared_g.artifacts import ArtifactStore

        self.freeze_all()
        for dataset in self.config.datasets:
            self.install_retrieval(dataset)
        self.prepare_new_generator()
        existing, backend = FormalNLIIntegrationTests.activate_nli(self)
        run = self.entry().AllDatasetJudgmentRun(existing.spec_path, self.root / "missing_completed.yaml",
                                                self.root, backend=backend)
        original_policy = copy.deepcopy(run.config.data["runtime"]["generation"])
        frozen = {path: sha256_file(path) for path in (run.spec_path, run.parent.config.path,
                  run.config.output / "run_config.json", run.parent.config.output / "run_config.json")}
        client = Mock()
        client.generate_with_metadata.side_effect = [TimeoutError("private-api-key"), self.result("230", "victim")]
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])), \
                patch("time.sleep"), self.assertLogs("all_dataset_nli_entry", level="WARNING"):
            run.run_victim("nfcorpus", False, 1, request_timeout=120)
        self.assertEqual(client.generate_with_metadata.call_count, 2)
        for call in client.generate_with_metadata.call_args_list:
            self.assertEqual(call.kwargs, {"temperature": original_policy["temperature"],
                                          "max_tokens": original_policy["max_tokens"], "timeout": 120})
        self.assertEqual(client.generate_with_metadata.call_args_list[0], client.generate_with_metadata.call_args_list[1])
        records = read_rows(ArtifactStore.path(run, "initial_responses.jsonl", "nfcorpus"))
        self.assertEqual([row["request_timeout_seconds"] for row in records], [120, 120])
        self.assertEqual(run.config.data["runtime"]["generation"], original_policy)
        self.assertEqual(frozen, {path: sha256_file(path) for path in frozen})

    def test_request_timeout_rejects_nonpositive_and_nonfinite_values_before_requests(self):
        run = self.network_run()
        with patch("src.llm.factory.build_victim_client") as build:
            for timeout in (0, -1, float("nan"), float("inf")):
                with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "positive_finite_request_timeout_required"):
                    run.run_victim("nfcorpus", False, 1, request_timeout=timeout)
            build.assert_not_called()

    def test_cli_forwards_request_timeout_to_initial_and_followup(self):
        import io

        for stage, followup in (("run-initial", False), ("run-followup", True)):
            with self.subTest(stage=stage):
                entry = self.entry()
                run = Mock()
                run.run_victim.return_value = {"status": "incomplete"}
                arguments = ["105_run_v25_shared_g_nli.py", stage, "--dataset", "nfcorpus", "--max-new", "6000",
                             "--network-retries", "3", "--request-timeout", "120"]
                with patch.object(entry, "AllDatasetJudgmentRun", return_value=run), \
                        patch("sys.argv", arguments), patch.object(entry.logging, "basicConfig"), \
                        patch("sys.stdout", new_callable=io.StringIO):
                    entry.main()
                run.run_victim.assert_called_once_with("nfcorpus", followup, 6000,
                                                       network_retries=3, request_timeout=120.0)

    def make_all(self, completed):
        import yaml
        path = self.root / "nli_all.yaml"
        value = {**completed.spec, "scoring_datasets": list(self.config.datasets),
                 "output_dir": "artifacts/v25/formal/nli_all"}
        path.write_text(yaml.safe_dump(value), encoding="utf-8")
        return self.entry().AllDatasetJudgmentRun(path, completed.spec_path, self.root)

    def test_completed_cache_is_reused_and_trec_can_start_without_rejudging_nfcorpus(self):
        from src.shared_g.artifacts import ArtifactStore
        self.freeze_all()
        self.complete_cell("nfcorpus")
        self.install_retrieval("scidocs")
        with patch("src.shared_g.victim.build_victim_client", return_value=(self.victim_client(), self.profiles["victim"])):
            run_victim(self.config, self.store, "scidocs", False)
        completed, _ = FormalNLIIntegrationTests.activate_nli(self, ["scidocs"])
        completed.score("scidocs")
        with patch("src.llm.factory.build_victim_client", return_value=(self.victim_client(), self.profiles["victim"])):
            self.assertTrue(completed.run_victim("scidocs", True)["cell_complete"])
        before = {p: sha256_file(p) for root in (self.config.output, completed.config.output)
                  for p in root.rglob("*") if p.is_file()}
        run = self.make_all(completed)
        run.activate()
        with patch("src.evaluation.answer_judgment._offline_backend", side_effect=AssertionError("no NLI calls")):
            self.assertTrue(run.score("scidocs")["complete"])
            run._require_previous_cells("trec-covid")
            run.activate()
        self.assertEqual({p: sha256_file(p) for p in before}, before)
        self.assertEqual(run.scoring_datasets, self.config.datasets)
        self.assertFalse(ArtifactStore.path(run, "initial_judgments.jsonl", "nfcorpus").exists())

    def test_incomplete_legacy_cell_still_blocks_trec(self):
        FormalNLIIntegrationTests.prepare_legacy(self, followup=False)
        completed, _ = FormalNLIIntegrationTests.activate_nli(self, ["scidocs"])
        run = self.make_all(completed)
        run.activate()
        with self.assertRaises(RuntimeError):
            run._require_previous_cells("trec-covid")

    def test_partial_new_nli_cell_cannot_fall_back_to_completed_legacy(self):
        self.freeze_all()
        self.complete_cell("nfcorpus")
        completed, backend = FormalNLIIntegrationTests.activate_nli(self, ["scidocs"])
        run = self.make_all(completed)
        run.backend = backend
        run.activate()
        self.assertFalse(run.score("nfcorpus", 1)["complete"])
        with self.assertRaisesRegex(RuntimeError, "previous_dataset_incomplete:nfcorpus"):
            run._require_previous_cells("trec-covid")

    def test_changed_nli_parameters_cannot_reuse_previous_cache(self):
        self.freeze_all()
        completed, _ = FormalNLIIntegrationTests.activate_nli(self, ["scidocs"])
        import yaml
        run = self.make_all(completed)
        calibration = json.loads(completed.calibration_path.read_text(encoding="utf-8"))
        calibration["selected_config"]["threshold"] = 0.3
        write_json_atomic(self.root / "changed_calibration.json", calibration)
        value = {**run.spec, "calibration": "changed_calibration.json"}
        run.spec_path.write_text(yaml.safe_dump(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "cache_identity_mismatch"):
            self.entry().AllDatasetJudgmentRun(run.spec_path, completed.spec_path, self.root)

    def network_run(self):
        self.freeze_all()
        self.install_retrieval("nfcorpus")
        completed, backend = FormalNLIIntegrationTests.activate_nli(self, ["scidocs"])
        run = self.make_all(completed)
        run.backend = backend
        run.activate()
        return run

    def test_network_reconnect_reuses_identical_prompt_and_preserves_resume(self):
        import urllib.error
        from src.shared_g.artifacts import ArtifactStore

        run = self.network_run()
        parent_before = {p: sha256_file(p) for p in self.config.output.rglob("*") if p.is_file()}
        client = Mock()
        wrapped = RuntimeError("private-api-key")
        wrapped.__cause__ = urllib.error.URLError(TimeoutError("private-api-key"))
        client.generate_with_metadata.side_effect = [wrapped, ConnectionResetError("private-api-key"),
                                                    self.result("230", "victim")]
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])), \
                patch("time.sleep") as sleep, self.assertLogs("all_dataset_nli_entry", level="WARNING") as logs:
            result = run.run_victim("nfcorpus", False, 1)
        self.assertEqual(client.generate_with_metadata.call_count, 3)
        self.assertEqual(client.generate_with_metadata.call_args_list[0], client.generate_with_metadata.call_args_list[1])
        self.assertEqual(client.generate_with_metadata.call_args_list[1], client.generate_with_metadata.call_args_list[2])
        self.assertEqual([call.args[0] for call in sleep.call_args_list[:2]], [2.0, 4.0])
        self.assertNotIn("private-api-key", " ".join(logs.output))
        self.assertEqual(result["new_calls"], 1)
        self.assertEqual(result["initial"]["invalid"], 0)
        path = ArtifactStore.path(run, "initial_responses.jsonl", "nfcorpus")
        row = request_records(path)[0]
        self.assertEqual((row["client_attempts"], row["network_retry_count"], row["retry_count"]), (3, 2, 0))
        self.assertEqual(len(row["request_errors"]), 2)
        self.assertNotIn("private-api-key", json.dumps(row))
        remaining_client = self.victim_client()
        with patch("src.llm.factory.build_victim_client", return_value=(remaining_client, self.profiles["victim"])), patch("time.sleep"):
            self.assertTrue(run.run_victim("nfcorpus", False)["complete"])
        self.assertEqual(remaining_client.generate_with_metadata.call_count, 11)
        saved = request_records(path)
        self.assertEqual(len(saved), 12)
        self.assertEqual(len({item["query_id"] for item in saved}), 12)
        self.assertEqual(next(item for item in saved if item["query_id"] == row["query_id"]), row)
        before = sha256_file(path)
        with patch("src.llm.factory.build_victim_client", side_effect=AssertionError("no repeated calls")):
            self.assertEqual(run.run_victim("nfcorpus", False)["new_calls"], 0)
        self.assertEqual(sha256_file(path), before)
        self.assertEqual(parent_before, {p: sha256_file(p) for p in parent_before})

    def test_network_retry_exhaustion_preserves_failure_and_blocks_blind_resume(self):
        from src.shared_g.artifacts import ArtifactStore

        run = self.network_run()
        client = Mock()
        client.generate_with_metadata.side_effect = TimeoutError("private-api-key")
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])), \
                patch("time.sleep") as sleep, self.assertLogs("all_dataset_nli_entry", level="WARNING") as logs:
            with self.assertRaisesRegex(RuntimeError, "victim_invalid_response_stop_preserve_evidence"):
                run.run_victim("nfcorpus", False, 1)
        self.assertEqual(client.generate_with_metadata.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2.0, 4.0, 8.0])
        self.assertNotIn("private-api-key", " ".join(logs.output))
        path = ArtifactStore.path(run, "initial_responses.jsonl", "nfcorpus")
        row = request_records(path)[0]
        self.assertEqual((row["status"], row["client_attempts"], row["network_retry_count"]), ("uncertain_transport", 4, 3))
        self.assertEqual(len(row["request_errors"]), 4)
        self.assertEqual(run.status("nfcorpus")["initial"]["invalid"], 1)
        before = sha256_file(path)
        with patch("src.llm.factory.build_victim_client", side_effect=AssertionError("no blind resume")):
            with self.assertRaisesRegex(RuntimeError, "unresolved_or_invalid_victim_response_preserved"):
                run.run_victim("nfcorpus", False, 1)
        self.assertEqual(sha256_file(path), before)

    def test_http_and_format_errors_do_not_trigger_network_reconnect(self):
        import urllib.error
        import ssl

        entry = self.entry()
        for code in (400, 401, 429, 500, 503):
            error = RuntimeError("private-api-key")
            error.__cause__ = urllib.error.HTTPError("https://invalid/?key=private-api-key", code, "private-api-key", {}, None)
            with self.subTest(http_status=code):
                details, retryable = entry.request_error_details(error)
                self.assertFalse(retryable)
                self.assertEqual(details["http_status"], code)
                self.assertNotIn("private-api-key", json.dumps(details))
        for error in (RuntimeError("Unexpected OpenAI-compatible response: private-api-key"),
                      RuntimeError("OpenAI-compatible API error response: private-api-key"),
                      ValueError("private-api-key"), PermissionError("private-api-key"),
                      ssl.SSLCertVerificationError("private-api-key")):
            with self.subTest(error_type=type(error).__name__):
                details, retryable = entry.request_error_details(error)
                self.assertFalse(retryable)
                self.assertNotIn("private-api-key", json.dumps(details))
        run = self.network_run()
        client = Mock()
        client.generate_with_metadata.side_effect = RuntimeError("Unexpected OpenAI-compatible response: private-api-key")
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])), \
                patch("time.sleep") as sleep, self.assertLogs("all_dataset_nli_entry", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "victim_invalid_response_stop_preserve_evidence"):
                run.run_victim("nfcorpus", False, 1)
        self.assertEqual(client.generate_with_metadata.call_count, 1)
        sleep.assert_not_called()

    def test_network_retry_does_not_accept_model_drift_or_hide_client_retries(self):
        from dataclasses import replace
        from src.shared_g.artifacts import ArtifactStore

        run = self.network_run()
        client = Mock()
        client.generate_with_metadata.return_value = replace(self.result("230", "victim"), provider_model_id="wrong-model", retry_count=1)
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])), patch("time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "victim_invalid_response_stop_preserve_evidence"):
                run.run_victim("nfcorpus", False, 1)
        row = request_records(ArtifactStore.path(run, "initial_responses.jsonl", "nfcorpus"))[0]
        self.assertEqual(row["status"], "invalid_provider_response")
        self.assertEqual(row["retry_count"], 1)
        self.assertEqual(row["network_retry_count"], 0)
        self.assertEqual(client.generate_with_metadata.call_count, 1)

    def test_network_retry_can_be_disabled_and_invalid_budget_is_rejected(self):
        run = self.network_run()
        client = Mock()
        client.generate_with_metadata.side_effect = ConnectionError("private-api-key")
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])) as build, \
                patch("time.sleep") as sleep, self.assertLogs("all_dataset_nli_entry", level="WARNING"):
            with self.assertRaisesRegex(ValueError, "nonnegative_network_retries_required"):
                run.run_victim("nfcorpus", False, 1, network_retries=-1)
            build.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "victim_invalid_response_stop_preserve_evidence"):
                run.run_victim("nfcorpus", False, 1, network_retries=0)
        self.assertEqual(client.generate_with_metadata.call_count, 1)
        sleep.assert_not_called()

    def test_network_exception_classification_follows_wrapped_causes(self):
        import errno
        import http.client
        import socket
        import ssl
        import urllib.error

        entry = self.entry()
        for cause in (TimeoutError("private-api-key"), ConnectionResetError("private-api-key"),
                      http.client.IncompleteRead(b"private-api-key", 100), ssl.SSLEOFError("private-api-key"),
                      socket.gaierror(-3, "private-api-key"), OSError(errno.ENETUNREACH, "private-api-key")):
            error = RuntimeError("private-api-key")
            error.__cause__ = urllib.error.URLError(cause)
            with self.subTest(cause=type(cause).__name__):
                details, retryable = entry.request_error_details(error)
                self.assertTrue(retryable)
                self.assertEqual(details["exception_types"][-1], type(cause).__name__)
                self.assertNotIn("private-api-key", json.dumps(details))
        error = RuntimeError("private-api-key")
        error.__cause__ = error
        self.assertFalse(entry.request_error_details(error)[1])

    def test_followup_network_reconnect_keeps_frozen_gate_and_initial_responses(self):
        from src.shared_g.artifacts import ArtifactStore

        run = self.network_run()
        with patch("src.llm.factory.build_victim_client", return_value=(self.victim_client(), self.profiles["victim"])), patch("time.sleep"):
            self.assertTrue(run.run_victim("nfcorpus", False)["complete"])
        initial = ArtifactStore.path(run, "initial_responses.jsonl", "nfcorpus")
        gate = ArtifactStore.path(run, "followup_gate.json", "nfcorpus")
        before = {p: sha256_file(p) for p in (initial, gate)}
        client = Mock()
        client.generate_with_metadata.side_effect = [ConnectionResetError("private-api-key"), self.result("230", "victim")]
        with patch("src.llm.factory.build_victim_client", return_value=(client, self.profiles["victim"])), \
                patch("time.sleep"), self.assertLogs("all_dataset_nli_entry", level="WARNING"):
            result = run.run_victim("nfcorpus", True, 1)
        self.assertEqual(result["new_calls"], 1)
        self.assertEqual(result["followup"]["invalid"], 0)
        row = request_records(ArtifactStore.path(run, "followup_responses.jsonl", "nfcorpus"))[0]
        self.assertEqual((row["status"], row["client_attempts"], row["network_retry_count"]), ("completed", 2, 1))
        self.assertIn(row["query_id"], read_json(gate)["query_ids"])
        self.assertEqual(before, {p: sha256_file(p) for p in before})
