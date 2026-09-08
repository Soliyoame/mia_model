from __future__ import annotations

import importlib.util
import copy
import io
import json
import re
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from src.prepare import restoration_first_v24 as v24

from src.prepare.restoration_first_v24 import (
    SemanticSimilarityScorer,
    build_candidate_prompt,
    build_correction_prompt,
    build_eligibility_manifest,
    build_split_manifest,
    deterministic_correction_eligibility_judge,
    deterministic_role_judge,
    deterministic_split,
    evaluate_candidate,
    fallback_queries,
    get_max_candidate_facts_per_source,
    scan_frozen_source_pool,
    scan_until_target,
    screen_source,
    load_v24_config,
    rank_candidates,
    validate_formal_integrity,
    validate_eligibility_manifest,
    validate_fallback_rate,
    build_query_manifest,
    validate_query_manifest,
    validate_query_semantics,
    _query_manifest_hash,
    _integrity_row_hash,
    _canonical_proposition_quality_reasons,
    stealth_diagnostics,
)
from src.utils.hash import sha256_file, sha256_obj, sha256_text
from src.utils.io import append_jsonl_record, read_json, read_jsonl, write_json, write_jsonl


def _load_v24_capacity_runner():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "53_run_v24_pre_split_eligibility.py"
    )
    spec = importlib.util.spec_from_file_location("v24_capacity_runner_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v24_capacity_runner_import_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _semantic_similarity(_left: str, _right: str) -> float:
    """Deterministic semantic-score mock for offline protocol tests."""

    return 0.95


class _FakeEmbedder:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[list[str]] = []
        self.closed = False

    def encode(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        return np.asarray([self.vectors[text] for text in texts], dtype="float32")

    def close(self) -> None:
        self.closed = True


def _fact(claim: str, original: str = "Alice") -> dict[str, object]:
    return {
        "dataset": "nfcorpus",
        "source_key": "source-1",
        "source_hash": "a" * 64,
        "normalized_text_hash": "b" * 64,
        "upstream_pair_id": "fact-1",
        "true_claim": claim,
        "original_entity": original,
        "original_span": [claim.index(original), claim.index(original) + len(original)],
    }


def _package(replacement: str, template: str, q_plus: str, q_minus: str, *, nli: str = "neutral") -> dict[str, object]:
    return {
        "replacement_entity": replacement,
        "canonical_proposition_template": template,
        "q_plus_text": q_plus,
        "q_minus_text": q_minus,
        "retrieval_anchors": [],
        "true_grounding": {"entailment_probability": 0.95, "top_label": "entailment"},
        "canonical_pair_nli_relation": nli,
    }


def _selection_fact(index: int, original: str) -> dict[str, object]:
    claim = f"The record identifies {original} as the designated representative."
    fact = _fact(claim, original)
    fact.update({
        "upstream_pair_id": f"selection-fact-{index}",
        "fact_order": index,
    })
    return fact


def _selection_source(facts: list[dict[str, object]], source_key: str = "selection-source") -> dict[str, object]:
    return {
        "dataset": "nfcorpus",
        "source_key": source_key,
        "source_order_rank": "0",
        "full_text": " ".join(str(fact["true_claim"]) for fact in facts),
    }


def _selection_package(fact: dict[str, object], index: int) -> dict[str, object]:
    original = str(fact["original_entity"])
    replacement = f"Alternative{index}"
    template = "The record identifies {ENTITY} as the designated representative."
    return _package(
        replacement,
        template,
        f"Does the record identify {original} as the designated representative?",
        f"Does the record identify {replacement} as the designated representative?",
    )


class V24EligibilityTests(unittest.TestCase):
    def test_config_removes_nli_contradiction_gate(self):
        config = load_v24_config()
        self.assertFalse(config["eligibility"]["nli_contradiction_required"])
        self.assertFalse(config["stealth_diagnostics"]["hard_gate"])
        self.assertEqual(config["eligibility"]["semantic_correction_retries"], 1)

    def test_candidate_prompt_states_structural_query_constraints(self):
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        fact["slotted_true_claim"] = "The company is incorporated in {ENTITY}."
        prompt = build_candidate_prompt(fact)
        self.assertIn("exactly one literal {ENTITY} token", prompt)
        self.assertIn("Preserve every factual number", prompt)
        self.assertIn("Do not introduce or remove a modal", prompt)
        self.assertIn("never use unresolved pronouns", prompt)
        self.assertIn("never substitute the bare phrase 'the company'", prompt)
        self.assertIn("Do not merge a heading with a sentence", prompt)
        self.assertIn("bibliography citation inside the target entity slot", prompt)
        self.assertIn("replace every first-person or document-bound occurrence", prompt)
        self.assertIn("never write 'Will ... and should ...'", prompt)
        self.assertIn("prefer a direct polar question using the appropriate auxiliary", prompt)
        self.assertIn("Do not use the fixed frame merely for convenience", prompt)

    def test_correction_prompt_contains_only_fixed_feedback_contract(self):
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        fact["slotted_true_claim"] = "The company is incorporated in {ENTITY}."
        prompt = build_correction_prompt(
            fact,
            [{
                "candidate": _package(
                    "Nevada",
                    "The company is incorporated in {ENTITY}.",
                    "Is it incorporated in Delaware?",
                    "Is it incorporated in Nevada?",
                ),
                "rejection_reasons": ["q_plus_unresolved_reference"],
            }],
        )
        self.assertIn("one allowed semantic correction retry", prompt)
        self.assertIn("q_plus_unresolved_reference", prompt)
        self.assertIn("replace every occurrence consistently", prompt)
        self.assertIn("rewrite the whole question", prompt)
        self.assertIn("never repeat forms such as 'Will ... and should '", prompt)
        self.assertIn("first try a direct auxiliary question", prompt)
        self.assertNotIn("membership_label", prompt)

    def test_open_world_attendance_rejected(self):
        payload = {
            "true_claim": "Alice attended the conference.",
            "original_entity": "Alice",
            "replacement_entity": "Bob",
            "canonical_true": "Alice attended the conference.",
            "canonical_counterfactual": "Bob attended the conference.",
        }
        self.assertFalse(deterministic_correction_eligibility_judge(payload)["correction_eligible"])

    def test_record_specific_role_allowed(self):
        payload = {
            "true_claim": "The meeting record identifies Alice as Company A's designated voting representative.",
            "original_entity": "Alice",
            "replacement_entity": "Bob",
            "canonical_true": "The meeting record identifies Alice as Company A's designated voting representative.",
            "canonical_counterfactual": "The meeting record identifies Bob as Company A's designated voting representative.",
        }
        self.assertTrue(deterministic_correction_eligibility_judge(payload)["correction_eligible"])

    def test_inconsistent_high_ambiguity_judge_is_rejected(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        package = _package(
            "Nevada",
            "Acme Corporation is incorporated in {ENTITY}.",
            "Is Acme Corporation incorporated in Delaware?",
            "Is Acme Corporation incorporated in Nevada?",
        )
        result = evaluate_candidate(
            fact,
            fact["true_claim"],
            package,
            similarity_fn=_semantic_similarity,
            eligibility_judge=lambda _payload: {
                "correction_eligible": True,
                "slot_determinacy": "strong",
                "open_world_ambiguity": "high",
            },
        )
        self.assertIn("correction_eligibility", result["rejection_reasons"])

    def test_contextual_role_is_distinct_from_eligibility(self):
        role = deterministic_role_judge({
            "true_claim": "Microsoft acquired GitHub.",
            "replacement_entity": "Google",
            "canonical_counterfactual": "Google acquired GitHub.",
        })
        self.assertTrue(role["compatible"])
        self.assertFalse(deterministic_role_judge({
            "true_claim": "Microsoft acquired GitHub.",
            "replacement_entity": "Paris",
            "canonical_counterfactual": "Paris acquired GitHub.",
        })["compatible"])
        self.assertTrue(role["proxy_only"])

    def test_neutral_nli_candidate_passes_scientific_gates(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        package = _package(
            "Nevada",
            "Acme Corporation is incorporated in {ENTITY}.",
            "Is Acme Corporation incorporated in Delaware?",
            "Is Acme Corporation incorporated in Nevada?",
        )
        result = evaluate_candidate(
            fact,
            "Acme Corporation is incorporated in Delaware.",
            package,
            similarity_fn=_semantic_similarity,
        )
        self.assertTrue(result["accepted"], result)
        self.assertEqual(result["pair"]["canonical_pair_nli_relation"], "neutral")

    def test_old_fields_are_rejected_even_if_membership_changes(self):
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        fact["effective_type"] = "LOCATION"
        with self.assertRaisesRegex(ValueError, "forbidden_input_field"):
            evaluate_candidate(fact, "The company is incorporated in Delaware.", _package(
                "Nevada", "The company is incorporated in {ENTITY}.",
                "Is the company incorporated in Delaware?", "Is the company incorporated in Nevada?"
            ))

    def test_query_semantics_requires_explicit_semantic_scorer(self):
        with self.assertRaisesRegex(RuntimeError, "semantic_similarity_required"):
            validate_query_semantics(
                true_claim="The company is incorporated in Delaware.",
                original_entity="Delaware",
                replacement_entity="Nevada",
                canonical_true="The company is incorporated in Delaware.",
                canonical_counterfactual="The company is incorporated in Nevada.",
                q_plus="Is the company incorporated in Delaware?",
                q_minus="Is the company incorporated in Nevada?",
            )

    def test_stealth_similarity_has_no_lexical_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "semantic_similarity_required"):
            stealth_diagnostics(
                source_text="The company is incorporated in Delaware.",
                q_plus="Is the company incorporated in Delaware?",
                q_minus="Is the company incorporated in Nevada?",
                original_entity="Delaware",
                replacement_entity="Nevada",
            )

    def test_semantic_similarity_scorer_uses_embedding_cosine(self):
        embedder = _FakeEmbedder({
            "left": [1.0, 0.0],
            "right": [0.6, 0.8],
        })
        scorer = SemanticSimilarityScorer(
            embedder=embedder,
            model_name="BAAI/bge-base-en-v1.5",
            revision="test-revision",
            backend="auto",
            local_files_only=True,
        )
        self.assertAlmostEqual(scorer("left", "right"), 0.6, places=6)
        self.assertAlmostEqual(scorer("left", "right"), 0.6, places=6)
        self.assertEqual(embedder.calls, [["left"], ["right"]])
        scorer.close()
        self.assertTrue(embedder.closed)

    def test_semantic_similarity_identity_records_model_and_revision(self):
        scorer = SemanticSimilarityScorer(
            embedder=_FakeEmbedder({"left": [1.0], "right": [1.0]}),
            model_name="BAAI/bge-base-en-v1.5",
            revision="a5beb1e3e68b9ab74eb54cfd186867f64f240e1a",
            backend="sentence_transformers",
            local_files_only=True,
        )
        self.assertEqual(
            scorer.identity(),
            {
                "kind": "sentence_transformers_cosine",
                "backend": "sentence_transformers",
                "model": "BAAI/bge-base-en-v1.5",
                "revision": "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a",
                "local_files_only": True,
                "threshold": 0.80,
            },
        )

    def test_semantic_similarity_scorer_rejects_invalid_embedding_shape(self):
        class InvalidEmbedder:
            def encode(self, _texts: list[str]) -> np.ndarray:
                return np.asarray([1.0, 0.0], dtype="float32")

        scorer = SemanticSimilarityScorer(
            embedder=InvalidEmbedder(),
            model_name="BAAI/bge-base-en-v1.5",
            revision="test-revision",
            backend="auto",
            local_files_only=True,
        )
        with self.assertRaisesRegex(RuntimeError, "invalid_embedding_shape"):
            scorer("left", "right")

    def test_ranking_uses_max_min_binding_score(self):
        base = {
            "accepted": True,
            "pair": {
                "binding_score": 0.0,
                "semantic_metrics": {"q_plus_similarity": 0.0, "q_minus_similarity": 0.0},
                "true_grounding": {"entailment_probability": 0.0},
                "contextual_role_compatibility": {"plausibility": "acceptable"},
                "upstream_pair_id": "b",
                "true_claim": "A record identifies Alice.",
                "q_plus_text": "Is Alice identified?",
                "q_minus_text": "Is Bob identified?",
            },
        }
        high = {"accepted": True, "pair": {**base["pair"], "semantic_metrics": {"q_plus_similarity": 0.92, "q_minus_similarity": 0.91}, "true_grounding": {"entailment_probability": 0.93}, "upstream_pair_id": "a"}}
        low = {"accepted": True, "pair": {**base["pair"], "semantic_metrics": {"q_plus_similarity": 0.81, "q_minus_similarity": 0.82}, "true_grounding": {"entailment_probability": 0.83}, "upstream_pair_id": "z"}}
        self.assertEqual(rank_candidates([low, high])[0]["pair"]["upstream_pair_id"], "a")

    def test_ranking_uses_copying_tiebreak_within_tolerance(self):
        def candidate(pair_id: str, score: float, copying: float) -> dict[str, object]:
            return {
                "accepted": True,
                "pair": {
                    "binding_score": score,
                    "semantic_metrics": {"q_plus_similarity": score, "q_minus_similarity": score},
                    "true_grounding": {"entailment_probability": score},
                    "contextual_role_compatibility": {"plausibility": "acceptable"},
                    "candidate_index": 0 if pair_id == "copy-low" else 1,
                    "pair_id": pair_id,
                    "upstream_pair_id": pair_id,
                    "true_claim": "A record identifies Alice.",
                    "q_plus_text": "Is Alice identified?" + (" record" * int(copying * 10)),
                    "q_minus_text": "Is Bob identified?",
                },
            }

        ranked = rank_candidates([candidate("copy-high", 0.99, 0.1), candidate("copy-low", 1.0, 0.0)])
        self.assertEqual(ranked[0]["pair"]["pair_id"], "copy-low")

    def test_stealth_metrics_do_not_reject_semantically_valid_query(self):
        reasons, metrics = validate_query_semantics(
            true_claim="Acme Corporation is incorporated in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="Acme Corporation is incorporated in Delaware.",
            canonical_counterfactual="Acme Corporation is incorporated in Nevada.",
            q_plus="Is it correct that Acme Corporation is incorporated in Delaware?",
            q_minus="Is it correct that Acme Corporation is incorporated in Nevada?",
            similarity_fn=lambda _a, _b: 0.95,
        )
        self.assertEqual(reasons, [])
        self.assertEqual(metrics["reverse_similarity"], 0.95)

    def test_stealth_diagnostics_are_recorded_without_being_hard_gates(self):
        metrics = stealth_diagnostics(
            source_text="The company is incorporated in Delaware.",
            q_plus="Is it correct that the company is incorporated in Delaware?",
            q_minus="Is it correct that the company is incorporated in Nevada?",
            original_entity="Delaware",
            replacement_entity="Nevada",
            similarity_fn=lambda _left, _right: 0.95,
        )
        self.assertEqual(metrics["entity_masked_similarity"], 0.95)
        self.assertIn("query_source_5gram_containment", metrics)
        self.assertIn("distinct_2", metrics)

    def test_fallback_keeps_same_canonical_pair(self):
        self.assertEqual(fallback_queries("Alice is CFO.", "Bob is CFO."), (
            "Is it correct that Alice is CFO?", "Is it correct that Bob is CFO?"
        ))

    def test_split_requires_exact_2250_and_exact_counts(self):
        sources = [
            {
                "eligible": True,
                "source_key": f"s-{i}",
                "source_hash": f"{i:064x}",
                "normalized_text_hash": f"{i + 10000:064x}",
                "selected_pairs": [{"pair_id": f"p-{i}-{j}"} for j in range(3)],
            }
            for i in range(2250)
        ]
        rows = deterministic_split(sources, dataset="nfcorpus")
        self.assertEqual(len(rows), 2250)
        self.assertEqual({row["group"] for row in rows}, {"KB_Member", "True_Non_Member", "Reserve"})
        with self.assertRaisesRegex(ValueError, "exactly_2250"):
            deterministic_split(sources[:-1], dataset="nfcorpus")

    def test_split_rejects_membership_fields_in_eligible_source(self):
        sources = [
            {
                "eligible": True,
                "source_key": f"s-{i}",
                "source_hash": f"{i:064x}",
                "normalized_text_hash": f"{i + 10000:064x}",
                "selected_pairs": [{"pair_id": f"p-{i}-{j}"} for j in range(3)],
            }
            for i in range(2250)
        ]
        sources[0]["membership_label"] = "KB_Member"
        with self.assertRaisesRegex(ValueError, "forbidden_input_field"):
            deterministic_split(sources, dataset="nfcorpus")

    def test_scan_stops_at_exact_target_without_reading_later_sources(self):
        seen: list[str] = []

        def sources():
            for index in range(3000):
                key = f"s-{index}"
                seen.append(key)
                yield {"dataset": "nfcorpus", "source_key": key, "source_order_rank": str(index), "full_text": "Alice is incorporated in Delaware."}

        fact_template = _fact("Alice is incorporated in Delaware.", "Delaware")

        def provider(fact):
            return [_package("Nevada", "Alice is incorporated in {ENTITY}.", "Is Alice incorporated in Delaware?", "Is Alice incorporated in Nevada?")]

        result = scan_until_target(
            sources(),
            candidate_provider=provider,
            target_sources=2250,
            minimum_pairs=1,
            facts=[fact_template],
            similarity_fn=_semantic_similarity,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["eligible_source_count"], 2250)
        self.assertEqual(len(seen), 2250)

    def test_scan_reports_insufficient_capacity(self):
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        result = scan_until_target(
            ({"dataset": "nfcorpus", "source_key": f"s-{i}", "source_order_rank": str(i), "full_text": "The company is incorporated in Delaware."} for i in range(2)),
            candidate_provider=lambda _fact: [],
            target_sources=3,
            facts=[fact],
            similarity_fn=_semantic_similarity,
        )
        self.assertEqual(result["status"], "insufficient_eligible_capacity")
        self.assertEqual(result["eligible_source_count"], 0)

    def test_membership_fields_cannot_change_pre_split_result(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        package = _package("Nevada", "Acme Corporation is incorporated in {ENTITY}.", "Is Acme Corporation incorporated in Delaware?", "Is Acme Corporation incorporated in Nevada?")
        source = {"dataset": "nfcorpus", "source_key": "s", "source_order_rank": "0", "full_text": "Acme Corporation is incorporated in Delaware."}
        first = scan_until_target(
            [source],
            candidate_provider=lambda _fact: [package],
            target_sources=1,
            minimum_pairs=1,
            facts=[fact],
            similarity_fn=_semantic_similarity,
        )
        altered = dict(fact, membership_label="KB_Member")
        with self.assertRaisesRegex(ValueError, "forbidden_input_field"):
            scan_until_target(
                [source],
                candidate_provider=lambda _fact: [package],
                target_sources=1,
                minimum_pairs=1,
                facts=[altered],
                similarity_fn=_semantic_similarity,
            )
        self.assertEqual(first["eligible_source_count"], 1)

    def test_candidate_fact_contains_masked_claim_and_absolute_spans(self):
        from src.prepare.restoration_first_v24 import enumerate_candidate_facts

        source = {
            "dataset": "nfcorpus",
            "source_key": "s",
            "source_order_rank": "0",
            "full_text": "Alice is incorporated in Delaware. Alice is incorporated in Nevada.",
        }
        facts = enumerate_candidate_facts(source)
        self.assertTrue(facts)
        fact = next(row for row in facts if row["original_entity"] == "Delaware")
        self.assertEqual(fact["slotted_true_claim"], "Alice is incorporated in {ENTITY}.")
        start, end = fact["original_span"]
        self.assertEqual(source["full_text"][start:end], "Delaware")

    def test_adapter_rejects_heading_sentence_glue_and_citation_entity_slots(self):
        from src.prepare.restoration_first_v24 import enumerate_candidate_facts

        heading_glue = {
            "dataset": "trec-covid",
            "source_key": "heading-glue",
            "source_order_rank": "0",
            "full_text": "Breed Some animals were assigned to Delaware.",
        }
        self.assertEqual(enumerate_candidate_facts(heading_glue), [])

        citation_slot = {
            "dataset": "trec-covid",
            "source_key": "citation-slot",
            "source_order_rank": "1",
            "full_text": (
                "Bilateral plating corrected nonunion after HTO [ 16 ], whereas "
                "mechanical stability was not investigated."
            ),
        }
        facts = enumerate_candidate_facts(citation_slot)
        self.assertFalse(any("[" in str(fact["original_entity"]) for fact in facts))

    def test_invalid_fact_is_rejected_before_provider_processing(self):
        claim = "Citizens unable to attend the Nov."
        fact = _fact(claim, "Citizens")
        source = {
            "dataset": "scidocs",
            "source_key": "fragment",
            "source_order_rank": "0",
            "full_text": claim,
        }

        def provider(_fact: object) -> list[dict[str, object]]:
            raise AssertionError("invalid_fact_must_not_reach_provider")

        result = screen_source(
            source,
            candidate_provider=provider,
            facts=[fact],
            minimum_pairs=1,
            similarity_fn=_semantic_similarity,
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["candidate_fact_count"], 1)
        self.assertEqual(result["processed_fact_count"], 0)
        self.assertEqual(result["unprocessed_fact_count"], 1)
        self.assertEqual(result["candidate_package_count"], 0)
        self.assertEqual(
            result["rejection_reason_counts"][
                "candidate_fact_incomplete_temporal_reference"
            ],
            1,
        )

    def test_formal_integrity_rejects_pair_drift(self):
        pairs = []
        for index in range(3):
            pair = {
                "pair_id": f"p-{index}",
                "original_entity": "Alice",
                "replacement_entity": "Bob",
                "canonical_proposition_template": "{ENTITY} is CFO.",
                "canonical_true": "Alice is CFO.",
                "canonical_counterfactual": "Bob is CFO.",
                "q_plus_text": "Is Alice CFO?",
                "q_minus_text": "Is Bob CFO?",
                "generation_mode": "luna_naturalized",
            }
            pair["query_manifest_hash"] = _query_manifest_hash(pair)
            pairs.append(pair)
        frozen = [{
            "dataset": "nfcorpus",
            "source_key": "s",
            "source_order_rank": "0",
            "source_hash": "a" * 64,
            "normalized_text_hash": "b" * 64,
            "max_candidate_facts_per_source": 8,
            "selected_pairs": pairs,
            "query_count": 6,
        }]
        frozen[0]["integrity_hash"] = _integrity_row_hash(frozen[0])
        drifted_pairs = [dict(pair) for pair in pairs]
        drifted_pairs[-1]["q_minus_text"] = "Is Carol CFO?"
        drifted_pairs[-1]["query_manifest_hash"] = _query_manifest_hash(drifted_pairs[-1])
        current = [{**frozen[0], "selected_pairs": drifted_pairs}]
        current[0]["integrity_hash"] = _integrity_row_hash(current[0])
        with self.assertRaisesRegex(ValueError, "integrity_drift"):
            validate_formal_integrity(current, expected_source_count=1, frozen_rows=frozen)

    def test_fallback_rate_is_checked_against_fixed_denominator(self):
        pair = {"generation_mode": "deterministic_fallback"}
        rows = [{"selected_pairs": [pair] + [{"generation_mode": "luna_naturalized"}] * 2}]
        self.assertEqual(validate_fallback_rate(rows, maximum=0.5, denominator=3)["fallback_pair_rate"], 1 / 3)
        with self.assertRaisesRegex(ValueError, "fallback_pair_rate_exceeded"):
            validate_fallback_rate(rows, maximum=0.2, denominator=3)

    def test_manifest_contains_coverage_and_split_hash(self):
        source = {
            "eligible": True,
            "dataset": "nfcorpus",
            "source_key": "s",
            "source_order_rank": "0",
            "source_hash": "a" * 64,
            "normalized_text_hash": "b" * 64,
            "selected_pairs": [
                {
                    "pair_id": f"p-{i}",
                    "generation_mode": "luna_naturalized",
                    "q_plus_text": "Is the company incorporated in Delaware?",
                    "q_minus_text": "Is the company incorporated in Nevada?",
                    "query_manifest_hash": "placeholder",
                }
                for i in range(3)
            ],
        }
        for pair in source["selected_pairs"]:
            pair["query_manifest_hash"] = _query_manifest_hash(pair)
        scan = {"status": "passed", "screened_source_count": 1, "eligible_source_count": 1, "eligible_source_rate": 1.0, "candidate_pair_count": 1, "candidate_package_count": 3, "contextual_role_pass_count": 3, "correction_eligibility_pass_count": 3, "rejection_reason_distribution": {}, "eligible_sources": [source]}
        config = {"eligibility": {"target_sources": 1}, "formal": {"fallback_pair_rate_maximum": 0.5}}
        manifest = build_eligibility_manifest(scan, dataset="nfcorpus", config=config, source_pool={"source_count": 1})
        self.assertEqual(manifest["contextual_role_pass_rate"], 1.0)
        self.assertEqual(manifest["fallback_pair_count"], 0)
        self.assertTrue(manifest["manifest_sha256"])
        self.assertEqual(validate_eligibility_manifest(manifest)["status"], "passed")
        query_manifest = build_query_manifest(manifest)
        self.assertEqual(query_manifest["query_count"], 6)
        self.assertEqual(validate_query_manifest(query_manifest)["status"], "passed")
        # split requires the protocol's fixed 2250 contract; small mock pools
        # are intentionally rejected rather than silently changing the split.
        with self.assertRaisesRegex(ValueError, "exactly_2250"):
            build_split_manifest(manifest, dataset="nfcorpus")

    def test_build_split_manifest_revalidates_eligibility_hash(self):
        source = {
            "eligible": True,
            "dataset": "nfcorpus",
            "source_key": "s",
            "source_order_rank": "0",
            "source_hash": "a" * 64,
            "normalized_text_hash": "b" * 64,
            "selected_pairs": [{"pair_id": f"p-{i}"} for i in range(3)],
        }
        scan = {
            "status": "passed",
            "screened_source_count": 1,
            "eligible_source_count": 1,
            "eligible_source_rate": 1.0,
            "candidate_pair_count": 1,
            "candidate_package_count": 3,
            "contextual_role_pass_count": 3,
            "correction_eligibility_pass_count": 3,
            "rejection_reason_distribution": {},
            "eligible_sources": [source],
        }
        config = {"eligibility": {"target_sources": 1}, "formal": {"fallback_pair_rate_maximum": 0.5}}
        manifest = build_eligibility_manifest(scan, dataset="nfcorpus", config=config, source_pool={"source_count": 1})
        manifest["sources"][0]["selected_pairs"][0]["pair_id"] = "drifted"
        with self.assertRaisesRegex(ValueError, "manifest_hash_invalid"):
            build_split_manifest(manifest, dataset="nfcorpus")

    def test_semantic_modality_drift_is_hard_failure(self):
        reasons, _ = validate_query_semantics(
            true_claim="The device can operate in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="The device can operate in Delaware.",
            canonical_counterfactual="The device can operate in Nevada.",
            q_plus="Is it correct that the device will operate in Delaware?",
            q_minus="Is it correct that the device can operate in Nevada?",
            similarity_fn=lambda _a, _b: 0.95,
        )
        self.assertIn("q_plus_modality_drift", reasons)

    def test_non_temporal_preposition_rewrite_does_not_trigger_temporal_drift(self):
        reasons, _ = validate_query_semantics(
            true_claim="The device operates in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="The device operates in Delaware.",
            canonical_counterfactual="The device operates in Nevada.",
            q_plus="Does the device operate within Delaware?",
            q_minus="Does the device operate within Nevada?",
            similarity_fn=_semantic_similarity,
        )
        self.assertNotIn("q_plus_temporal_drift", reasons)
        self.assertNotIn("q_minus_temporal_drift", reasons)

    def test_explicit_temporal_relation_change_remains_a_hard_failure(self):
        reasons, _ = validate_query_semantics(
            true_claim="Before 2024, the company operated in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="Before 2024, the company operated in Delaware.",
            canonical_counterfactual="Before 2024, the company operated in Nevada.",
            q_plus="After 2024, did the company operate in Delaware?",
            q_minus="Before 2024, did the company operate in Nevada?",
            similarity_fn=_semantic_similarity,
        )
        self.assertIn("q_plus_temporal_drift", reasons)
        self.assertNotIn("q_minus_temporal_drift", reasons)

    def test_bibliography_citation_is_not_a_factual_numeric_marker(self):
        reasons, _ = validate_query_semantics(
            true_claim="Twitter updates [5] identified Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="Twitter updates [5] identified Delaware.",
            canonical_counterfactual="Twitter updates [5] identified Nevada.",
            q_plus="Did Twitter updates identify Delaware?",
            q_minus="Did Twitter updates identify Nevada?",
            similarity_fn=_semantic_similarity,
        )
        self.assertNotIn("q_plus_numeric_drift", reasons)
        self.assertNotIn("q_minus_numeric_drift", reasons)

    def test_factual_number_omission_remains_a_hard_failure(self):
        reasons, _ = validate_query_semantics(
            true_claim="The GC group was assessed at 6 weeks in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="The GC group was assessed at 6 weeks in Delaware.",
            canonical_counterfactual="The GC group was assessed at 6 weeks in Nevada.",
            q_plus="Was the GC group assessed in Delaware?",
            q_minus="Was the GC group assessed in Nevada?",
            similarity_fn=_semantic_similarity,
        )
        self.assertIn("q_plus_numeric_drift", reasons)
        self.assertIn("q_minus_numeric_drift", reasons)

    def test_modal_auxiliaries_are_valid_polar_question_starts(self):
        reasons, _ = validate_query_semantics(
            true_claim="scidocs shall file notice in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="scidocs shall file notice in Delaware.",
            canonical_counterfactual="scidocs shall file notice in Nevada.",
            q_plus="Shall scidocs file notice in Delaware?",
            q_minus="Shall scidocs file notice in Nevada?",
            similarity_fn=_semantic_similarity,
        )
        self.assertNotIn("q_plus_not_polar_question", reasons)
        self.assertNotIn("q_minus_not_polar_question", reasons)
        self.assertNotIn("q_plus_new_factual_entity", reasons)
        self.assertNotIn("q_minus_new_factual_entity", reasons)

    def test_direct_polar_forms_are_accepted_for_simple_propositions(self):
        cases = (
            (
                "Acme Corporation operates in Delaware.",
                "Acme Corporation operates in Nevada.",
                "Does Acme Corporation operate in Delaware?",
                "Does Acme Corporation operate in Nevada?",
            ),
            (
                "The ACCORD study was approved in Delaware.",
                "The ACCORD study was approved in Nevada.",
                "Was the ACCORD study approved in Delaware?",
                "Was the ACCORD study approved in Nevada?",
            ),
            (
                "The device can operate in Delaware.",
                "The device can operate in Nevada.",
                "Can the device operate in Delaware?",
                "Can the device operate in Nevada?",
            ),
            (
                "The committee will meet in Delaware.",
                "The committee will meet in Nevada.",
                "Will the committee meet in Delaware?",
                "Will the committee meet in Nevada?",
            ),
        )
        for canonical_true, canonical_counterfactual, q_plus, q_minus in cases:
            with self.subTest(q_plus=q_plus):
                reasons, _ = validate_query_semantics(
                    true_claim=canonical_true,
                    original_entity="Delaware",
                    replacement_entity="Nevada",
                    canonical_true=canonical_true,
                    canonical_counterfactual=canonical_counterfactual,
                    q_plus=q_plus,
                    q_minus=q_minus,
                    similarity_fn=_semantic_similarity,
                )
                self.assertEqual(reasons, [])

    def test_query_rejects_first_person_and_document_bound_references(self):
        cases = (
            ("Is our office incorporated in Delaware?", "q_plus_unresolved_reference"),
            ("Is the policy set forth herein for Delaware?", "q_plus_unresolved_reference"),
            ("Does the Company operate in Delaware?", "q_plus_unresolved_reference"),
            ("Do the following rules apply in Delaware?", "q_plus_unresolved_reference"),
            ("Was the period extended in Delaware?", "q_plus_unresolved_reference"),
        )
        for q_plus, expected in cases:
            with self.subTest(q_plus=q_plus):
                reasons, _ = validate_query_semantics(
                    true_claim="The organization operates in Delaware.",
                    original_entity="Delaware",
                    replacement_entity="Nevada",
                    canonical_true="The organization operates in Delaware.",
                    canonical_counterfactual="The organization operates in Nevada.",
                    q_plus=q_plus,
                    q_minus="Does the organization operate in Nevada?",
                    similarity_fn=_semantic_similarity,
                )
                self.assertIn(expected, reasons)

    def test_locally_resolved_their_and_named_company_remain_valid(self):
        reasons, _ = validate_query_semantics(
            true_claim="The companies recorded their results in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="The companies recorded their results in Delaware.",
            canonical_counterfactual="The companies recorded their results in Nevada.",
            q_plus="Did the companies record their results in Delaware?",
            q_minus="Did the companies record their results in Nevada?",
            similarity_fn=_semantic_similarity,
        )
        self.assertNotIn("q_plus_unresolved_reference", reasons)
        self.assertNotIn("q_minus_unresolved_reference", reasons)

        company_reasons, _ = validate_query_semantics(
            true_claim="Acme Corporation is incorporated in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="Acme Corporation is incorporated in Delaware.",
            canonical_counterfactual="Acme Corporation is incorporated in Nevada.",
            q_plus="Is Acme Corporation incorporated in Delaware?",
            q_minus="Is Acme Corporation incorporated in Nevada?",
            similarity_fn=_semantic_similarity,
        )
        self.assertNotIn("q_plus_unresolved_reference", company_reasons)
        self.assertNotIn("q_minus_unresolved_reference", company_reasons)

    def test_first_person_claim_requires_explicit_source_grounded_role(self):
        fact = _fact("We are incorporated in Delaware.", "Delaware")
        bare = _package(
            "Nevada",
            "The company is incorporated in {ENTITY}.",
            "Is the company incorporated in Delaware?",
            "Is the company incorporated in Nevada?",
        )
        rejected = evaluate_candidate(
            fact,
            fact["true_claim"],
            bare,
            similarity_fn=_semantic_similarity,
        )
        self.assertFalse(rejected["accepted"])
        self.assertIn("canonical_unresolved_reference", rejected["rejection_reasons"])

        explicit = _package(
            "Nevada",
            "Acme Corporation is incorporated in {ENTITY}.",
            "Is Acme Corporation incorporated in Delaware?",
            "Is Acme Corporation incorporated in Nevada?",
        )
        explicit["contextual_role_compatibility"] = {
            "compatible": True,
            "plausibility": "strong",
        }
        explicit["correction_eligibility"] = {
            "correction_eligible": True,
            "slot_determinacy": "strong",
            "open_world_ambiguity": "low",
        }
        accepted = evaluate_candidate(
            fact,
            "Acme Corporation reports: " + str(fact["true_claim"]),
            explicit,
            similarity_fn=_semantic_similarity,
        )
        self.assertTrue(accepted["accepted"], accepted)

    def test_locally_defined_first_person_aliases_are_not_unresolved(self):
        claim = (
            'Vulcan Materials Company (the "Company," "we," "our"), a Delaware '
            "corporation, supplies construction aggregates."
        )
        fact = _fact(claim, "Delaware")
        package = _package(
            "Nevada",
            'Vulcan Materials Company (the "Company," "we," "our"), a {ENTITY} '
            "corporation, supplies construction aggregates.",
            "Is Vulcan Materials Company, a Delaware corporation, a supplier of "
            "construction aggregates?",
            "Is Vulcan Materials Company, a Nevada corporation, a supplier of "
            "construction aggregates?",
        )
        package["contextual_role_compatibility"] = {
            "compatible": True,
            "plausibility": "strong",
        }
        package["correction_eligibility"] = {
            "correction_eligible": True,
            "slot_determinacy": "strong",
            "open_world_ambiguity": "low",
        }
        result = evaluate_candidate(
            fact,
            fact["true_claim"],
            package,
            similarity_fn=_semantic_similarity,
        )
        self.assertTrue(result["accepted"], result)

    def test_canonical_document_reference_is_reconstruction_failure(self):
        fact = _fact("The shares are adjusted under the agreement in Delaware.", "Delaware")
        package = _package(
            "Nevada",
            "The shares are adjusted as set forth herein in {ENTITY}.",
            "Are the shares adjusted as set forth herein in Delaware?",
            "Are the shares adjusted as set forth herein in Nevada?",
        )
        result = evaluate_candidate(
            fact,
            fact["true_claim"],
            package,
            similarity_fn=_semantic_similarity,
        )
        self.assertFalse(result["accepted"])
        self.assertIn("canonical_unresolved_reference", result["rejection_reasons"])

    def test_canonical_reference_check_allows_local_aliases_and_complementizer(self):
        locally_defined = (
            'Vulcan Materials Company (the "Company," "we," "our") is incorporated '
            "in Delaware."
        )
        self.assertEqual(
            _canonical_proposition_quality_reasons(locally_defined, locally_defined),
            [],
        )
        complementizer = "The record states that Alice is designated in Delaware."
        self.assertNotIn(
            "canonical_unresolved_reference",
            _canonical_proposition_quality_reasons(complementizer, complementizer),
        )

    def test_query_rejects_observed_malformed_surface_patterns(self):
        cases = (
            "Will Alice work in Delaware and should be able to present?",
            "Do investors disfavor Delaware or are unwilling to invest?",
            "Did the company acquire Delaware, VentureWire has learned?",
            "Is it correct that In December the company operated in Delaware?",
            "Is it correct that citizens unable to attend the Nov.?",
            "Did Breed Some animals originate in Delaware?",
        )
        for q_plus in cases:
            with self.subTest(q_plus=q_plus):
                reasons, _ = validate_query_semantics(
                    true_claim="The company operated in Delaware.",
                    original_entity="Delaware",
                    replacement_entity="Nevada",
                    canonical_true="The company operated in Delaware.",
                    canonical_counterfactual="The company operated in Nevada.",
                    q_plus=q_plus,
                    q_minus="Did the company operate in Nevada?",
                    similarity_fn=_semantic_similarity,
                )
                self.assertIn("q_plus_not_natural_question", reasons)
        fragment_reasons, _ = validate_query_semantics(
            true_claim="Citizens were unable to attend in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="Citizens were unable to attend in Delaware.",
            canonical_counterfactual="Citizens were unable to attend in Nevada.",
            q_plus="Is it correct that citizens unable to attend the Nov.?",
            q_minus="Were citizens unable to attend in Nevada?",
            similarity_fn=_semantic_similarity,
        )
        self.assertIn("q_plus_not_polar_question", fragment_reasons)

    def test_fixed_verification_frame_allows_modal_clauses_inside_proposition(self):
        reasons, _ = validate_query_semantics(
            true_claim=(
                "The sender will have a Blackberry unit and should be able to receive "
                "emails in Colorado."
            ),
            original_entity="Colorado",
            replacement_entity="Utah",
            canonical_true=(
                "The sender will have a Blackberry unit and should be able to receive "
                "emails in Colorado."
            ),
            canonical_counterfactual=(
                "The sender will have a Blackberry unit and should be able to receive "
                "emails in Utah."
            ),
            q_plus=(
                "Is it correct that the sender will have a Blackberry unit and should be "
                "able to receive emails in Colorado?"
            ),
            q_minus=(
                "Is it correct that the sender will have a Blackberry unit and should be "
                "able to receive emails in Utah?"
            ),
            similarity_fn=_semantic_similarity,
        )
        self.assertNotIn("q_plus_not_natural_question", reasons)
        self.assertNotIn("q_minus_not_natural_question", reasons)

    def test_semantic_correction_retry_runs_once_and_preserves_evidence(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        source = {
            "dataset": "nfcorpus",
            "source_key": "source-1",
            "source_order_rank": "0",
            "full_text": fact["true_claim"],
        }
        initial = _package(
            "Nevada",
            "Acme Corporation is incorporated in {ENTITY}.",
            "Is it incorporated in Delaware?",
            "Is it incorporated in Nevada?",
        )
        corrected = _package(
            "Nevada",
            "Acme Corporation is incorporated in {ENTITY}.",
            "Is Acme Corporation incorporated in Delaware?",
            "Is Acme Corporation incorporated in Nevada?",
        )

        class Provider:
            def __init__(self) -> None:
                self.initial_calls = 0
                self.correction_calls = 0

            def __call__(self, _fact: object) -> list[dict[str, object]]:
                self.initial_calls += 1
                return [initial]

            def correct(
                self,
                _fact: object,
                rejected: object,
            ) -> list[dict[str, object]]:
                self.correction_calls += 1
                self.assert_rejected = rejected
                return [corrected]

        provider = Provider()
        result = screen_source(
            source,
            candidate_provider=provider,
            facts=[fact],
            minimum_pairs=1,
            allow_surface_fallback=False,
            similarity_fn=_semantic_similarity,
            semantic_correction_retries=1,
            include_candidate_evidence=True,
        )
        self.assertTrue(result["eligible"], result)
        self.assertEqual(provider.initial_calls, 1)
        self.assertEqual(provider.correction_calls, 1)
        self.assertEqual(result["candidate_package_count"], 2)
        self.assertEqual(
            [item["generation_attempt"] for item in result["candidate_evidence"]],
            ["initial", "semantic_correction"],
        )
        self.assertIn(
            "q_plus_unresolved_reference",
            result["candidate_evidence"][0]["rejection_reasons"],
        )
        self.assertTrue(result["candidate_evidence"][1]["accepted"])

    def test_initial_success_skips_semantic_correction(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        source = {
            "dataset": "nfcorpus",
            "source_key": "source-1",
            "source_order_rank": "0",
            "full_text": fact["true_claim"],
        }
        valid = _package(
            "Nevada",
            "Acme Corporation is incorporated in {ENTITY}.",
            "Is Acme Corporation incorporated in Delaware?",
            "Is Acme Corporation incorporated in Nevada?",
        )

        class Provider:
            def __init__(self) -> None:
                self.correction_calls = 0

            def __call__(self, _fact: object) -> list[dict[str, object]]:
                return [valid]

            def correct(
                self,
                _fact: object,
                _rejected: object,
            ) -> list[dict[str, object]]:
                self.correction_calls += 1
                return []

        provider = Provider()
        result = screen_source(
            source,
            candidate_provider=provider,
            facts=[fact],
            minimum_pairs=1,
            similarity_fn=_semantic_similarity,
            semantic_correction_retries=1,
        )
        self.assertTrue(result["eligible"], result)
        self.assertEqual(provider.correction_calls, 0)

    def test_failed_semantic_correction_does_not_retry_again(self):
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        source = {
            "dataset": "nfcorpus",
            "source_key": "source-1",
            "source_order_rank": "0",
            "full_text": fact["true_claim"],
        }
        invalid = _package(
            "Nevada",
            "The company is incorporated in {ENTITY}.",
            "Is it incorporated in Delaware?",
            "Is it incorporated in Nevada?",
        )

        class Provider:
            def __init__(self) -> None:
                self.initial_calls = 0
                self.correction_calls = 0

            def __call__(self, _fact: object) -> list[dict[str, object]]:
                self.initial_calls += 1
                return [invalid]

            def correct(
                self,
                _fact: object,
                _rejected: object,
            ) -> list[dict[str, object]]:
                self.correction_calls += 1
                return [invalid]

        provider = Provider()
        result = screen_source(
            source,
            candidate_provider=provider,
            facts=[fact],
            minimum_pairs=1,
            allow_surface_fallback=False,
            similarity_fn=_semantic_similarity,
            semantic_correction_retries=1,
            include_candidate_evidence=True,
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(provider.initial_calls, 1)
        self.assertEqual(provider.correction_calls, 1)
        self.assertEqual(len(result["candidate_evidence"]), 2)
        self.assertFalse(any(item["accepted"] for item in result["candidate_evidence"]))

    def test_invalid_anchor_is_diagnostic_only_and_anchor_is_not_appended(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        valid = _package("Nevada", "Acme Corporation is incorporated in {ENTITY}.", "Is Acme Corporation incorporated in Delaware?", "Is Acme Corporation incorporated in Nevada?")
        valid["retrieval_anchors"] = ["Acme Corporation"]
        accepted = evaluate_candidate(
            fact,
            fact["true_claim"],
            valid,
            similarity_fn=_semantic_similarity,
        )
        self.assertTrue(accepted["accepted"])
        invalid = dict(valid, retrieval_anchors=["not in source"])
        result = evaluate_candidate(
            fact,
            fact["true_claim"],
            invalid,
            similarity_fn=_semantic_similarity,
        )
        self.assertTrue(result["accepted"], result)
        self.assertNotIn("retrieval_anchor_not_source_grounded", result["rejection_reasons"])
        self.assertIn(
            "retrieval_anchor_not_source_grounded",
            result["pair"]["retrieval_anchor_diagnostics"]["reasons"],
        )
        self.assertEqual(result["pair"]["retrieval_anchors"], ["not in source"])

    def test_anchor_diagnostics_do_not_change_candidate_ranking(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        package = _package(
            "Nevada",
            "Acme Corporation is incorporated in {ENTITY}.",
            "Is Acme Corporation incorporated in Delaware?",
            "Is Acme Corporation incorporated in Nevada?",
        )
        clean = evaluate_candidate(
            fact,
            fact["true_claim"],
            package,
            similarity_fn=_semantic_similarity,
        )
        noisy = evaluate_candidate(
            fact,
            fact["true_claim"],
            dict(package, retrieval_anchors=["not in source"]),
            similarity_fn=_semantic_similarity,
        )
        self.assertTrue(clean["accepted"], clean)
        self.assertTrue(noisy["accepted"], noisy)
        self.assertEqual(
            rank_candidates([clean, noisy])[0]["pair"]["pair_id"],
            clean["pair"]["pair_id"],
        )

    def test_anchor_diagnostics_are_carried_to_query_manifest_without_budget_change(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        package = _package(
            "Nevada",
            "Acme Corporation is incorporated in {ENTITY}.",
            "Is Acme Corporation incorporated in Delaware?",
            "Is Acme Corporation incorporated in Nevada?",
        )
        package["retrieval_anchors"] = ["not in source"]
        pair = evaluate_candidate(
            fact,
            fact["true_claim"],
            package,
            similarity_fn=_semantic_similarity,
        )["pair"]
        source = {
            "eligible": True,
            "dataset": "nfcorpus",
            "source_key": "s",
            "source_order_rank": "0",
            "source_hash": "a" * 64,
            "normalized_text_hash": "b" * 64,
            "selected_pairs": [dict(pair), dict(pair), dict(pair)],
        }
        for index, selected in enumerate(source["selected_pairs"]):
            selected["pair_id"] = f"p-{index}"
            selected["query_manifest_hash"] = _query_manifest_hash(selected)
        scan = {
            "status": "passed",
            "screened_source_count": 1,
            "eligible_source_count": 1,
            "eligible_source_rate": 1.0,
            "candidate_pair_count": 1,
            "candidate_package_count": 3,
            "contextual_role_pass_count": 3,
            "correction_eligibility_pass_count": 3,
            "rejection_reason_distribution": {},
            "eligible_sources": [source],
        }
        manifest = build_eligibility_manifest(
            scan,
            dataset="nfcorpus",
            config={
                "eligibility": {"target_sources": 1},
                "formal": {"fallback_pair_rate_maximum": 0.5},
            },
            source_pool={"source_count": 1},
        )
        query_manifest = build_query_manifest(manifest)
        self.assertEqual(query_manifest["query_count"], 6)
        self.assertTrue(
            all("retrieval_anchor_diagnostics" in row for row in query_manifest["rows"])
        )

    def test_fallback_recomputes_query_manifest_hash(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        package = _package("Nevada", "Acme Corporation is incorporated in {ENTITY}.", "", "")
        result = evaluate_candidate(
            fact,
            fact["true_claim"],
            package,
            allow_surface_fallback=True,
            similarity_fn=_semantic_similarity,
        )
        pair = result["pair"]
        self.assertEqual(pair["query_manifest_hash"], _query_manifest_hash(pair))

    def test_query_manifest_rejects_source_or_pair_count_drift(self):
        source = {
            "eligible": True,
            "dataset": "nfcorpus",
            "source_key": "s",
            "source_order_rank": "0",
            "source_hash": "a" * 64,
            "normalized_text_hash": "b" * 64,
            "selected_pairs": [],
        }
        # Reuse the full-manifest fixture to obtain valid pair/query hashes.
        pairs = []
        for i in range(3):
            pair = {
                "pair_id": f"p-{i}",
                "q_plus_text": "Is the company incorporated in Delaware?",
                "q_minus_text": "Is the company incorporated in Nevada?",
                "generation_mode": "luna_naturalized",
                "query_manifest_hash": "",
            }
            pair["query_manifest_hash"] = _query_manifest_hash(pair)
            pairs.append(pair)
        source["selected_pairs"] = pairs
        scan = {
            "status": "passed",
            "screened_source_count": 1,
            "eligible_source_count": 1,
            "eligible_source_rate": 1.0,
            "candidate_pair_count": 1,
            "candidate_package_count": 3,
            "contextual_role_pass_count": 3,
            "correction_eligibility_pass_count": 3,
            "rejection_reason_distribution": {},
            "eligible_sources": [source],
        }
        config = {"eligibility": {"target_sources": 1}, "formal": {"fallback_pair_rate_maximum": 0.5}}
        manifest = build_eligibility_manifest(scan, dataset="nfcorpus", config=config, source_pool={"source_count": 1})
        query_manifest = build_query_manifest(manifest)
        self.assertEqual(validate_query_manifest(query_manifest)["query_count"], 6)
        query_manifest["rows"] = query_manifest["rows"][:-1]
        query_manifest["query_count"] -= 1
        query_manifest["manifest_sha256"] = sha256_obj(
            {key: value for key, value in query_manifest.items() if key != "manifest_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "source_query_count|source_count"):
            validate_query_manifest(query_manifest)

    def test_query_manifest_rejects_pair_hash_drift(self):
        source = {
            "eligible": True,
            "dataset": "nfcorpus",
            "source_key": "s",
            "source_order_rank": "0",
            "source_hash": "a" * 64,
            "normalized_text_hash": "b" * 64,
            "selected_pairs": [{"pair_id": f"p-{index}"} for index in range(3)],
        }
        pairs = []
        for i in range(3):
            pair = {
                "pair_id": f"p-{i}",
                "q_plus_text": "Is the company incorporated in Delaware?",
                "q_minus_text": "Is the company incorporated in Nevada?",
                "generation_mode": "luna_naturalized",
            }
            pair["query_manifest_hash"] = _query_manifest_hash(pair)
            pairs.append(pair)
        source["selected_pairs"] = pairs
        scan = {
            "status": "passed",
            "screened_source_count": 1,
            "eligible_source_count": 1,
            "eligible_source_rate": 1.0,
            "candidate_pair_count": 1,
            "candidate_package_count": 3,
            "contextual_role_pass_count": 3,
            "correction_eligibility_pass_count": 3,
            "rejection_reason_distribution": {},
            "eligible_sources": [source],
        }
        config = {"eligibility": {"target_sources": 1}, "formal": {"fallback_pair_rate_maximum": 0.5}}
        manifest = build_eligibility_manifest(scan, dataset="nfcorpus", config=config, source_pool={"source_count": 1})
        query_manifest = build_query_manifest(manifest)
        query_manifest["rows"][0]["query_manifest_hash"] = "0" * 64
        query_manifest["manifest_sha256"] = sha256_obj(
            {key: value for key, value in query_manifest.items() if key != "manifest_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "pair_hash"):
            validate_query_manifest(query_manifest)

    def test_query_manifest_rejects_cross_polarity_entity_binding_drift(self):
        source = {
            "eligible": True,
            "dataset": "nfcorpus",
            "source_key": "s",
            "source_order_rank": "0",
            "source_hash": "a" * 64,
            "normalized_text_hash": "b" * 64,
            "selected_pairs": [],
        }
        pairs = []
        for i in range(3):
            pair = {
                "pair_id": f"p-{i}",
                "q_plus_text": "Is the company incorporated in Delaware?",
                "q_minus_text": "Is the company incorporated in Nevada?",
                "generation_mode": "luna_naturalized",
            }
            pair["query_manifest_hash"] = _query_manifest_hash(pair)
            pairs.append(pair)
        source["selected_pairs"] = pairs
        scan = {
            "status": "passed",
            "screened_source_count": 1,
            "eligible_source_count": 1,
            "eligible_source_rate": 1.0,
            "candidate_pair_count": 1,
            "candidate_package_count": 3,
            "contextual_role_pass_count": 3,
            "correction_eligibility_pass_count": 3,
            "rejection_reason_distribution": {},
            "eligible_sources": [source],
        }
        config = {"eligibility": {"target_sources": 1}, "formal": {"fallback_pair_rate_maximum": 0.5}}
        manifest = build_eligibility_manifest(scan, dataset="nfcorpus", config=config, source_pool={"source_count": 1})
        query_manifest = build_query_manifest(manifest)
        query_manifest["rows"][1]["original_entity"] = "Carol"
        query_manifest["manifest_sha256"] = sha256_obj(
            {key: value for key, value in query_manifest.items() if key != "manifest_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "pair_binding"):
            validate_query_manifest(query_manifest)

    def test_surface_failure_uses_same_reconstruction_fallback(self):
        fact = _fact("Acme Corporation is incorporated in Delaware.", "Delaware")
        package = _package("Nevada", "Acme Corporation is incorporated in {ENTITY}.", "", "")
        result = evaluate_candidate(
            fact,
            fact["true_claim"],
            package,
            allow_surface_fallback=True,
            similarity_fn=_semantic_similarity,
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["pair"]["generation_mode"], "deterministic_fallback")
        self.assertEqual(result["pair"]["replacement_entity"], "Nevada")

    def test_source_early_stop_uses_completed_distinct_eligible_pairs(self):
        originals = ["Microsoft", "Microsoft", "GitHub", "Delaware"] + [f"Entity{i}" for i in range(16)]
        facts = [_selection_fact(index, original) for index, original in enumerate(originals)]
        source = _selection_source(facts)

        class Provider:
            def __init__(self) -> None:
                self.calls: list[int] = []

            def __call__(self, fact: object) -> list[dict[str, object]]:
                row = dict(fact)  # type: ignore[arg-type]
                index = int(row["fact_order"])
                self.calls.append(index)
                return [_selection_package(row, index)]

        provider = Provider()
        result = screen_source(
            source,
            candidate_provider=provider,
            facts=facts,
            similarity_fn=_semantic_similarity,
            max_candidate_facts_per_source=8,
        )
        self.assertTrue(result["eligible"], result)
        self.assertEqual(provider.calls, [0, 1, 2, 3])
        self.assertEqual(result["candidate_fact_count"], 20)
        self.assertEqual(result["processed_fact_count"], 4)
        self.assertEqual(result["unprocessed_fact_count"], 16)
        self.assertEqual(result["candidate_package_count"], 4)
        self.assertTrue(result["early_stop_triggered"])
        self.assertEqual(result["third_eligible_pair_fact_position"], 3)
        self.assertEqual(result["third_distinct_eligible_pair_fact_position"], 4)
        self.assertEqual(result["original_entity_diversity"], 3)
        self.assertEqual(result["repeated_original_entity_pair_count"], 0)
        self.assertEqual(
            [pair["original_entity"] for pair in result["selected_pairs"]],
            ["Microsoft", "GitHub", "Delaware"],
        )

    def test_source_continues_after_only_two_eligible_pairs(self):
        originals = ["Microsoft", "GitHub", "Entity2", "Entity3", "Delaware", "Entity5"]
        facts = [_selection_fact(index, original) for index, original in enumerate(originals)]
        source = _selection_source(facts, source_key="two-then-three")

        class Provider:
            def __init__(self) -> None:
                self.calls: list[int] = []

            def __call__(self, fact: object) -> list[dict[str, object]]:
                row = dict(fact)  # type: ignore[arg-type]
                index = int(row["fact_order"])
                self.calls.append(index)
                return [_selection_package(row, index)] if index in {0, 1, 4} else []

        provider = Provider()
        result = screen_source(
            source,
            candidate_provider=provider,
            facts=facts,
            similarity_fn=_semantic_similarity,
            max_candidate_facts_per_source=8,
        )
        self.assertTrue(result["eligible"], result)
        self.assertEqual(provider.calls, [0, 1, 2, 3, 4])
        self.assertEqual(result["processed_fact_count"], 5)
        self.assertEqual(result["unprocessed_fact_count"], 1)

    def test_source_budget_caps_duplicate_entity_search_and_fallback(self):
        facts = [_selection_fact(index, "Microsoft") for index in range(10)]
        source = _selection_source(facts, source_key="duplicate-budget")

        class Provider:
            def __init__(self) -> None:
                self.calls: list[int] = []

            def __call__(self, fact: object) -> list[dict[str, object]]:
                row = dict(fact)  # type: ignore[arg-type]
                index = int(row["fact_order"])
                self.calls.append(index)
                return [_selection_package(row, index)]

        provider = Provider()
        result = screen_source(
            source,
            candidate_provider=provider,
            facts=facts,
            similarity_fn=_semantic_similarity,
            max_candidate_facts_per_source=8,
        )
        self.assertTrue(result["eligible"], result)
        self.assertEqual(provider.calls, list(range(8)))
        self.assertEqual(result["candidate_fact_count"], 10)
        self.assertEqual(result["processed_fact_count"], 8)
        self.assertEqual(result["unprocessed_fact_count"], 2)
        self.assertFalse(result["early_stop_triggered"])
        self.assertEqual(result["original_entity_diversity"], 1)
        self.assertEqual(result["repeated_original_entity_pair_count"], 2)

    def test_source_diversity_does_not_change_scientific_pair_validity(self):
        facts = [_selection_fact(index, "Microsoft") for index in range(3)]
        source = _selection_source(facts, source_key="same-entity")
        result = screen_source(
            source,
            candidate_provider=lambda fact: [_selection_package(dict(fact), int(fact["fact_order"]))],
            facts=facts,
            similarity_fn=_semantic_similarity,
            max_candidate_facts_per_source=8,
        )
        self.assertTrue(result["eligible"], result)
        self.assertEqual(len(result["selected_pairs"]), 3)
        self.assertEqual(result["original_entity_diversity"], 1)

    def test_source_selection_is_deterministic(self):
        facts = [_selection_fact(index, original) for index, original in enumerate(["Microsoft", "Microsoft", "GitHub", "Delaware"])]
        source = _selection_source(facts, source_key="deterministic")

        def run() -> dict[str, object]:
            return screen_source(
                source,
                candidate_provider=lambda fact: [_selection_package(dict(fact), int(fact["fact_order"]))],
                facts=facts,
                similarity_fn=_semantic_similarity,
                max_candidate_facts_per_source=8,
            )

        first = run()
        second = run()
        self.assertEqual(
            [pair["pair_id"] for pair in first["selected_pairs"]],
            [pair["pair_id"] for pair in second["selected_pairs"]],
        )

    def test_configured_fact_budget_is_eight(self):
        self.assertEqual(get_max_candidate_facts_per_source(load_v24_config()), 8)

    def test_formal_integrity_rejects_fact_budget_drift(self):
        row = {
            "dataset": "nfcorpus",
            "source_key": "budget-drift",
            "source_order_rank": "0",
            "source_hash": "a" * 64,
            "normalized_text_hash": "b" * 64,
            "max_candidate_facts_per_source": 9,
            "query_count": 6,
            "selected_pairs": [{"pair_id": f"p-{index}"} for index in range(3)],
        }
        with self.assertRaisesRegex(ValueError, "formal_pair_count|formal_fact_budget"):
            validate_formal_integrity([row], expected_source_count=1)

    def test_eligibility_manifest_rejects_non_frozen_fact_budget(self):
        source = {
            "eligible": True,
            "dataset": "nfcorpus",
            "source_key": "s-budget",
            "source_order_rank": "0",
            "source_hash": "a" * 64,
            "normalized_text_hash": "b" * 64,
            "selected_pairs": [{"pair_id": f"p-{i}"} for i in range(3)],
        }
        scan = {
            "status": "passed",
            "screened_source_count": 1,
            "eligible_source_count": 1,
            "eligible_source_rate": 1.0,
            "candidate_pair_count": 3,
            "candidate_package_count": 3,
            "candidate_fact_count": 3,
            "processed_fact_count": 3,
            "unprocessed_fact_count": 0,
            "contextual_role_pass_count": 3,
            "correction_eligibility_pass_count": 3,
            "rejection_reason_distribution": {},
            "eligible_sources": [source],
            "max_candidate_facts_per_source": 9,
        }
        config = {
            "eligibility": {
                "target_sources": 1,
                "max_candidate_facts_per_source": 9,
            },
            "formal": {"fallback_pair_rate_maximum": 0.5},
        }
        manifest = build_eligibility_manifest(
            scan,
            dataset="nfcorpus",
            config=config,
            source_pool={"source_count": 1},
        )
        with self.assertRaisesRegex(ValueError, "fact_budget_not_frozen"):
            validate_eligibility_manifest(manifest)

    def test_frozen_scan_rejects_budget_override_before_source_read(self):
        config = {"eligibility": {"max_candidate_facts_per_source": 8}}
        with patch(
            "src.prepare.restoration_first_v24.load_v24_config",
            return_value=config,
        ), patch(
            "src.prepare.restoration_first_v24.iter_frozen_source_pool",
            side_effect=AssertionError("source_pool_must_not_be_read"),
        ):
            with self.assertRaisesRegex(ValueError, "frozen_scan_fact_budget_mismatch"):
                scan_frozen_source_pool(
                    ".",
                    "nfcorpus",
                    candidate_provider=lambda _fact: [],
                    max_candidate_facts_per_source=9,
                )

    def test_scan_reports_entity_diversity_and_processing_coverage(self):
        source_rows = [
            {"dataset": "nfcorpus", "source_key": f"scan-{index}", "source_order_rank": str(index)}
            for index in range(3)
        ]
        fake_results = [
            {
                "eligible": True,
                "candidate_pair_count": 3,
                "candidate_fact_count": 10,
                "processed_fact_count": 3,
                "unprocessed_fact_count": 7,
                "candidate_package_count": 9,
                "eligible_pair_count": 3,
                "contextual_role_pass_count": 3,
                "correction_eligibility_pass_count": 3,
                "query_feasible_pair_count": 3,
                "fallback_pair_count": 0,
                "early_stop_triggered": True,
                "original_entity_diversity": 1,
                "rejection_reason_counts": {},
            },
            {
                "eligible": True,
                "candidate_pair_count": 3,
                "candidate_fact_count": 10,
                "processed_fact_count": 4,
                "unprocessed_fact_count": 6,
                "candidate_package_count": 12,
                "eligible_pair_count": 3,
                "contextual_role_pass_count": 3,
                "correction_eligibility_pass_count": 3,
                "query_feasible_pair_count": 3,
                "fallback_pair_count": 1,
                "early_stop_triggered": False,
                "original_entity_diversity": 2,
                "rejection_reason_counts": {},
            },
            {
                "eligible": True,
                "candidate_pair_count": 3,
                "candidate_fact_count": 10,
                "processed_fact_count": 4,
                "unprocessed_fact_count": 6,
                "candidate_package_count": 12,
                "eligible_pair_count": 3,
                "contextual_role_pass_count": 3,
                "correction_eligibility_pass_count": 3,
                "query_feasible_pair_count": 3,
                "fallback_pair_count": 0,
                "early_stop_triggered": True,
                "original_entity_diversity": 3,
                "rejection_reason_counts": {},
            },
        ]
        with patch(
            "src.prepare.restoration_first_v24.screen_source",
            side_effect=fake_results,
        ) as mocked:
            result = scan_until_target(
                source_rows,
                candidate_provider=lambda _fact: [],
                target_sources=3,
                max_candidate_facts_per_source=8,
            )
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(result["candidate_fact_count"], 30)
        self.assertEqual(result["processed_fact_count"], 11)
        self.assertEqual(result["unprocessed_fact_count"], 19)
        self.assertEqual(result["early_stop_source_count"], 2)
        self.assertEqual(result["entity_diversity_1_source_count"], 1)
        self.assertEqual(result["entity_diversity_2_source_count"], 1)
        self.assertEqual(result["entity_diversity_3_source_count"], 1)
        self.assertEqual(result["mean_original_entity_diversity"], 2.0)


class V24QueryQualityTests(unittest.TestCase):
    def _query_reasons(
        self, claim: str, q_plus: str, *, original: str = "Delaware",
        replacement: str = "Nevada", source_text: str = "",
    ) -> list[str]:
        reasons, _ = validate_query_semantics(
            true_claim=claim, original_entity=original, replacement_entity=replacement,
            canonical_true=claim, canonical_counterfactual=claim.replace(original, replacement),
            q_plus=q_plus, q_minus=q_plus.replace(original, replacement),
            source_text=source_text, similarity_fn=_semantic_similarity,
        )
        return reasons

    def test_generic_research_references_are_not_resolved_by_renaming(self):
        for subject in (
            "the present meta-analysis", "the authors", "the research team", "the company",
            "the research project", "the reporting source", "the reporting company",
            "the paper", "the study", "the researchers", "the primary outcome",
        ):
            with self.subTest(subject=subject):
                claim = f"{subject.capitalize()} was recorded in Delaware."
                self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, f"Was {subject} recorded in Delaware?"))

    def test_named_or_qualified_research_references_remain_valid(self):
        for subject in ("the ACCORD study", "the study by Smith", "the paper on neural parsing", "Acme Corporation"):
            with self.subTest(subject=subject):
                claim = f"{subject} was registered in Delaware."
                self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(claim, f"Was {subject} registered in Delaware?"))

    def test_unspecified_quantified_sets_need_scope(self):
        for subject in ("all applicable randomized-controlled trials", "the various medications", "all scheduled examinations", "most scales"):
            with self.subTest(subject=subject):
                claim = f"{subject.capitalize()} were recorded in Delaware."
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, f"Were {subject} recorded in Delaware?"))
        claim = "The scales for depression were validated in Delaware."
        self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(claim, "Were the scales for depression validated in Delaware?"))

    def test_explicit_study_context_resolves_local_outcome_and_examination_sets(self):
        for claim, query in (
            ("In the ACCORD trial, the primary outcome was recorded in Delaware.", "Was the primary outcome recorded in Delaware in the ACCORD trial?"),
            ("In the ACCORD trial, all scheduled examinations were recorded in Delaware.", "Were all scheduled examinations recorded in Delaware in the ACCORD trial?"),
        ):
            with self.subTest(query=query):
                self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(claim, query))
        claim = "In the ACCORD trial, the reporting company was located in Delaware."
        self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))

    def test_patient_counts_and_significance_tests_need_a_population_context(self):
        for claim, query in (
            ("Between 2004 and June 2011, 181 patients underwent hernia repair.", "Did 181 patients undergo hernia repair between 2004 and June 2011?"),
            ("Delayed treatment increased conversion rates from 11.9% to 27.9% (P < 0.001).", "Did delayed treatment increase conversion rates from 11.9% to 27.9% (P < 0.001)?"),
        ):
            with self.subTest(query=query):
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, query, original="2004" if "2004" in claim else "11.9%", replacement="2003" if "2004" in claim else "10.9%"))
        claim = "In the Helsinki Hospital cohort, 181 patients underwent hernia repair."
        self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(claim, "Is it correct that in the Helsinki Hospital cohort, 181 patients underwent hernia repair?", original="181", replacement="182"))

    def test_source_defined_abbreviations_must_be_explained_in_each_query(self):
        for abbreviation, expansion in (("CEL", "celecoxib"), ("ORS", "ovarian remnant syndrome"), ("LC", "laparoscopic cholecystectomy")):
            with self.subTest(abbreviation=abbreviation):
                claim = f"{abbreviation} was evaluated in Delaware."
                source = f"{expansion} ({abbreviation}) was evaluated in Delaware."
                reasons = self._query_reasons(claim, f"Was {abbreviation} evaluated in Delaware?", source_text=source)
                self.assertIn("q_plus_unresolved_abbreviation", reasons)
                self.assertIn("q_minus_unresolved_abbreviation", reasons)
                expanded_claim = f"{expansion} ({abbreviation}) was evaluated in Delaware."
                expanded = self._query_reasons(expanded_claim, f"Was {expansion} ({abbreviation}) evaluated in Delaware?", source_text=source)
                self.assertNotIn("q_plus_unresolved_abbreviation", expanded)

    def test_uppercase_product_names_are_not_blanket_rejected_as_abbreviations(self):
        claim = "The KYPO cyber range was installed in Delaware."
        reasons = self._query_reasons(claim, "Was the KYPO cyber range installed in Delaware?", source_text=claim)
        self.assertNotIn("q_plus_unresolved_abbreviation", reasons)

    def test_fallback_cannot_bypass_source_abbreviation_check(self):
        fact = _fact("CEL is manufactured in Delaware.", "Delaware")
        package = _package("Nevada", "CEL is manufactured in {ENTITY}.", "", "")
        package["contextual_role_compatibility"] = {"compatible": True, "plausibility": "strong"}
        package["correction_eligibility"] = {"correction_eligible": True, "slot_determinacy": "strong", "open_world_ambiguity": "low"}
        result = evaluate_candidate(fact, "Celecoxib (CEL) is manufactured in Delaware.", package, similarity_fn=_semantic_similarity, allow_surface_fallback=True)
        self.assertFalse(result["accepted"])
        self.assertNotEqual(result["pair"]["generation_mode"], "deterministic_fallback")

    def test_counterfactual_expansion_retaining_acronym_is_not_a_new_truth_gate(self):
        reasons, _ = validate_query_semantics(
            true_claim="In Wire Arc Additive Manufacturing (WAAM), objects are welded.",
            original_entity="Wire Arc Additive Manufacturing", replacement_entity="Arc-Wire Metal Additive Manufacturing",
            canonical_true="In Wire Arc Additive Manufacturing (WAAM), objects are welded.",
            canonical_counterfactual="In Arc-Wire Metal Additive Manufacturing (WAAM), objects are welded.",
            q_plus="Are objects welded in Wire Arc Additive Manufacturing (WAAM)?",
            q_minus="Are objects welded in Arc-Wire Metal Additive Manufacturing (WAAM)?",
            source_text="In Wire Arc Additive Manufacturing (WAAM), objects are welded.", similarity_fn=_semantic_similarity,
        )
        self.assertNotIn("q_minus_unresolved_abbreviation", reasons)

    def test_original_fact_alias_is_allowed_only_on_the_true_side(self):
        claim = "The outcome was the IBS Global Improvement Scale (IBS-GIS)."
        arguments = dict(
            true_claim=claim, original_entity="IBS Global Improvement Scale", replacement_entity="Relief Scale",
            canonical_true="The outcome was the IBS Global Improvement Scale.",
            canonical_counterfactual="The outcome was the Relief Scale.",
            q_plus="Was the outcome the IBS Global Improvement Scale (IBS-GIS)?",
            q_minus="Was the outcome the Relief Scale?", similarity_fn=_semantic_similarity,
        )
        reasons, _ = validate_query_semantics(**arguments)
        self.assertNotIn("q_plus_new_factual_entity", reasons)
        reasons, _ = validate_query_semantics(**{**arguments, "q_plus": arguments["q_plus"].replace("IBS-GIS", "UNSEEN")})
        self.assertIn("q_plus_new_factual_entity", reasons)
        reasons, _ = validate_query_semantics(**{**arguments, "q_minus": "Was the outcome the Relief Scale (IBS-GIS)?"})
        self.assertIn("q_minus_new_factual_entity", reasons)

    def test_source_context_resolves_a_subject_but_does_not_license_invention(self):
        fact = _fact("We are incorporated in Delaware.", "Delaware")
        source = "Acme Corporation reports: We are incorporated in Delaware."
        package = _package("Nevada", "Acme Corporation is incorporated in {ENTITY}.", "Is Acme Corporation incorporated in Delaware?", "Is Acme Corporation incorporated in Nevada?")
        package["contextual_role_compatibility"] = {"compatible": True, "plausibility": "strong"}
        result = evaluate_candidate(fact, source, package, similarity_fn=_semantic_similarity)
        self.assertTrue(result["accepted"], result)
        invented = {key: value.replace("Acme Corporation", "Invented Corporation") if isinstance(value, str) else value for key, value in package.items()}
        result = evaluate_candidate(fact, source, invented, similarity_fn=_semantic_similarity)
        self.assertFalse(result["accepted"])
        self.assertIn("canonical_new_factual_entity", result["rejection_reasons"])

    def test_screening_projects_only_source_text_to_initial_and_correction_prompts(self):
        fact = _fact("We are incorporated in Delaware.", "Delaware")
        before = copy.deepcopy(fact)
        source = {"dataset": "nfcorpus", "source_key": "source-1", "source_order_rank": "0", "full_text": "Acme Corporation reports: We are incorporated in Delaware.", "unrelated_metadata": "not_for_prompt"}
        bad = _package("Nevada", "The reporting company is incorporated in {ENTITY}.", "Is the reporting company incorporated in Delaware?", "Is the reporting company incorporated in Nevada?")
        good = _package("Nevada", "Acme Corporation is incorporated in {ENTITY}.", "Is Acme Corporation incorporated in Delaware?", "Is Acme Corporation incorporated in Nevada?")
        good["contextual_role_compatibility"] = {"compatible": True, "plausibility": "strong"}
        provider = Mock(return_value=[bad])
        provider.correct = Mock(return_value=[good])
        result = screen_source(source, facts=[fact], candidate_provider=provider, minimum_pairs=1, allow_surface_fallback=False, similarity_fn=_semantic_similarity)
        self.assertTrue(result["eligible"], result)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(provider.correct.call_count, 1)
        for payload in (provider.call_args.args[0], provider.correct.call_args.args[0]):
            self.assertEqual(payload["source_context"], source["full_text"])
            self.assertNotIn("membership_label", payload)
            self.assertNotIn("victim_response", payload)
            self.assertNotIn("unrelated_metadata", payload)
            prompt = build_candidate_prompt(payload)
            self.assertIn("Acme Corporation reports", prompt)
            self.assertNotIn("membership_label", prompt)
        self.assertEqual(fact, before)
        provider.reset_mock()
        with self.assertRaisesRegex(ValueError, "forbidden_input_field"):
            screen_source({**source, "membership_label": "hidden"}, facts=[fact], candidate_provider=provider, minimum_pairs=1, similarity_fn=_semantic_similarity)
        provider.assert_not_called()

    def test_copyright_and_corrupt_units_stop_before_model_calls(self):
        cases = (("Copyright 2010 Elsevier Ltd.", "2010"), ("The processor reaches 30% frameshecond.", "30%"))
        for claim, entity in cases:
            with self.subTest(claim=claim):
                fact = _fact(claim, entity)
                provider = Mock(side_effect=AssertionError("unexpected_model_call"))
                result = screen_source(_selection_source([fact]), facts=[fact], candidate_provider=provider, minimum_pairs=1, similarity_fn=_semantic_similarity)
                provider.assert_not_called()
                self.assertFalse(result["eligible"])
                self.assertTrue(any(key.startswith("query_input_") for key in result["rejection_reason_counts"]))

    def test_noise_rejections_do_not_refill_beyond_first_eight_or_mutate_pool_facts(self):
        facts = [_fact(f"Copyright {2000 + i} Example Press.", str(2000 + i)) for i in range(8)]
        facts.append(_selection_fact(8, "Alice"))
        for index, fact in enumerate(facts):
            fact["fact_order"] = index
        before = copy.deepcopy(facts)
        provider = Mock(side_effect=AssertionError("ninth_fact_must_not_be_processed"))
        result = screen_source(_selection_source(facts), facts=facts, candidate_provider=provider, minimum_pairs=1, similarity_fn=_semantic_similarity)
        provider.assert_not_called()
        self.assertFalse(result["eligible"])
        self.assertEqual(result["candidate_fact_count"], 9)
        self.assertEqual(result["rejection_reason_counts"]["query_input_non_proposition"], 8)
        self.assertEqual(facts, before)

    def test_copyright_fragments_are_not_made_polar_by_a_fixed_prefix(self):
        reasons = self._query_reasons("Copyright 2010 Elsevier Ltd.", "Is it correct that Copyright 2010 Elsevier Ltd.?", original="2010", replacement="2011")
        self.assertIn("q_plus_not_polar_question", reasons)
        self.assertIn("q_plus_not_natural_question", reasons)
        claim = "Copyright law applies in Delaware."
        self.assertNotIn("q_plus_not_polar_question", self._query_reasons(claim, "Does copyright law apply in Delaware?"))

    def test_fresh_canary_preflight_shares_runtime_noise_rejection(self):
        runner = _load_v24_capacity_runner()
        for claim in ("Copyright 2010 Elsevier Ltd.", "The processor reaches 2010 frameshecond."):
            with self.subTest(claim=claim):
                fact = _fact(claim, "2010")
                fact["proposition_span"] = [0, len(claim)]
                valid, reasons = runner._fresh_fact_preflight(fact, {"full_text": claim})
                self.assertFalse(valid)
                self.assertTrue(any(reason.startswith("query_input_") for reason in reasons))

    def test_ordinary_frame_rate_and_complete_age_wording_remain_valid(self):
        incomplete = "Do marine sponges represent metazoans dating to 700 million years?"
        self.assertIn("q_plus_not_natural_question", self._query_reasons(incomplete[:-1] + ".", incomplete, original="700", replacement="900"))
        for claim, query, entity, replacement in (
            ("The sensor runs at 30 frames/second.", "Does the sensor run at 30 frames/second?", "30", "40"),
            ("Marine sponges date to 700 million years ago.", "Do marine sponges date to 700 million years ago?", "700", "900"),
        ):
            with self.subTest(query=query):
                self.assertNotIn("q_plus_not_natural_question", self._query_reasons(claim, query, original=entity, replacement=replacement))

    def test_existential_there_and_complementizer_that_are_not_external_references(self):
        for claim, query in (
            ("There are licensed clinics in Delaware.", "Are there licensed clinics in Delaware?"),
            ("There may be licensed clinics in Delaware.", "May there be licensed clinics in Delaware?"),
            ("There are licensed clinics in Delaware.", "Is it correct that there are licensed clinics in Delaware?"),
            ("The record states that Alice is registered in Delaware.", "Does the record state that Alice is registered in Delaware?"),
            ("The record suggests that a treatment is available in Delaware.", "Does the record suggest that a treatment is available in Delaware?"),
            ("The device uses a guide so that the learner develops skills in Delaware.", "Does the device use a guide so that the learner develops skills in Delaware?"),
            ("Acme supplies a device that reduces noise in Delaware.", "Does Acme supply a device that reduces noise in Delaware?"),
        ):
            with self.subTest(query=query):
                reasons = self._query_reasons(claim, query)
                self.assertNotIn("q_plus_unresolved_reference", reasons)
                self.assertNotIn("q_minus_unresolved_reference", reasons)
        for query in (
            "Was Alice registered there in Delaware?",
            "Does the record report that study in Delaware?",
            "Does Alice endorse that Delaware policy?",
            "Did they register in Delaware?",
        ):
            with self.subTest(query=query):
                self.assertIn("q_plus_unresolved_reference", self._query_reasons("Alice registered in Delaware.", query))

    def test_explicit_titles_require_a_grounded_title_or_meaningful_title_prefix(self):
        for title, heading in (
            ('"Varicose Veins, Deep Vein Thrombosis, and Haemorrhoids: Epidemiology and Suggested Aetiology"',
             "Varicose Veins, Deep Vein Thrombosis, and Haemorrhoids: Epidemiology and Suggested Aetiology"),
            ("Toward Meta-cognitive Tutoring", "Toward Meta-cognitive Tutoring: A Model of Help Seeking with a Cognitive Tutor"),
            ("'An active volumetric model'", "An active volumetric model for 3D reconstruction"),
            ('"Why we learn"', "Why we learn"),
        ):
            with self.subTest(title=title):
                claim = f"The paper titled {title} reports that a method is registered in Delaware."
                query = f"Does the paper titled {title} report that a method is registered in Delaware?"
                source = heading + "\n\n" + claim
                self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim, source_text=source))
                self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(claim, query, source_text=source))
        heading = "Toward Meta-cognitive Tutoring: A Model of Help Seeking with a Cognitive Tutor"
        claim = "The paper titled Toward Meta-cognitive Tutoring uses a guide so that the learner develops skills in Delaware."
        query = "Does the paper titled Toward Meta-cognitive Tutoring use a guide so that the learner develops skills in Delaware?"
        source = heading + "\n\n" + claim
        self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim, source_text=source))
        self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(claim, query, source_text=source))
        source = "An active volumetric model for 3D reconstruction\n\nA physically motivated model is described."
        for title in ("'an invented volumetric model'", "'An active'", "'A physically motivated model'"):
            with self.subTest(title=title):
                claim = f"The article titled {title} was registered in Delaware."
                query = f"Was the article titled {title} registered in Delaware?"
                self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim, source_text=source))
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, query, source_text=source))

    def test_counterfactual_title_slot_does_not_require_a_real_counterfactual_document(self):
        title = "Corporations in Delaware: Formation rules"
        claim = f"The paper titled '{title}' reports filing requirements."
        fact = _fact(claim, "Delaware")
        package = _package(
            "Nevada", claim.replace("Delaware", "{ENTITY}"),
            f"Does the paper titled '{title}' report filing requirements?",
            f"Does the paper titled '{title.replace('Delaware', 'Nevada')}' report filing requirements?",
        )
        result = evaluate_candidate(
            fact, title + "\n\n" + claim, package, similarity_fn=_semantic_similarity,
            eligibility_judge=lambda _: {"correction_eligible": True},
            role_judge=lambda _: {"compatible": True, "plausibility": "strong"},
        )
        self.assertTrue(result["accepted"], result)

    def test_grounded_derivation_allows_hyphens_and_regular_plural_but_not_new_names_or_numbers(self):
        fact = _fact("This invariance is tested on the MPEG-7 CE-Shape-1 dataset.", "MPEG-7 CE-Shape-1")
        source = "Moment invariants based on Jacobi polynomials are tested on the MPEG-7 CE-Shape-1 dataset."
        for phrase, supported in (
            ("Jacobi-polynomial-based", True), ("Jacobi-polynomials-based", True),
            ("Jacoby-polynomial-based", False), ("Jacobi-polynomial-7-based", False),
        ):
            with self.subTest(phrase=phrase):
                template = f"The invariance of the {phrase} moment invariants is tested on the {{ENTITY}} dataset."
                package = _package(
                    "Kimia-99", template,
                    f"Is the invariance of the {phrase} moment invariants tested on the MPEG-7 CE-Shape-1 dataset?",
                    f"Is the invariance of the {phrase} moment invariants tested on the Kimia-99 dataset?",
                )
                result = evaluate_candidate(
                    fact, source, package, similarity_fn=_semantic_similarity,
                    eligibility_judge=lambda _: {"correction_eligible": True},
                    role_judge=lambda _: {"compatible": True, "plausibility": "strong"},
                )
                self.assertEqual("canonical_new_factual_entity" not in result["rejection_reasons"], supported, result)
                self.assertEqual(result["accepted"], supported, result)
                if supported:
                    result = evaluate_candidate(fact, source + " Kimia-99 is also listed.", package, similarity_fn=_semantic_similarity)
                    self.assertIn("source_absence", result["rejection_reasons"])

    def test_title_fragments_stop_before_generation_and_cannot_be_wrapped_as_facts(self):
        for claim, entity in (
            ("Primary constipation: an underlying mechanism.", "Primary constipation"),
            ("Caring for the Vaccine Hesitant Family: Evidence-Based Alternatives to Dismissal", "Vaccine Hesitant Family"),
            ("A Joint Position Paper of the Heart Failure Association.", "Heart Failure Association"),
            ("Methods for Improving Signal Recovery: A Tutorial", "Signal Recovery"),
            ("The response of the colon to eating.", "colon"),
            ("A brief journey into medical care and disease in ancient Egypt.", "ancient Egypt"),
            ("Dietary fiber and personality factors as determinants of stool output.", "Dietary fiber"),
        ):
            with self.subTest(claim=claim):
                fact = _fact(claim, entity)
                provider = Mock(side_effect=AssertionError("title_fragment_must_not_call_model"))
                result = screen_source(_selection_source([fact]), facts=[fact], candidate_provider=provider, minimum_pairs=1, similarity_fn=_semantic_similarity)
                provider.assert_not_called()
                self.assertIn("query_input_non_proposition", result["rejection_reason_counts"])
                reasons = self._query_reasons(claim, "Is it correct that " + claim.rstrip(".") + "?", original=entity, replacement="Alternative")
                self.assertIn("q_plus_not_polar_question", reasons)
                self.assertIn("canonical_incomplete_proposition", _canonical_proposition_quality_reasons(claim, claim))

    def test_declarative_titles_and_section_labels_with_predicates_remain_valid(self):
        for claim, entity in (
            ("Oxygen injection site affects FIO2 during noninvasive ventilation.", "FIO2"),
            ("Purpose: Research on clinical outcomes is limited in Delaware.", "Delaware"),
            ("Caring for vaccine-hesitant families improves vaccination uptake.", "vaccination uptake"),
        ):
            with self.subTest(claim=claim):
                self.assertNotIn("query_input_non_proposition", v24._query_input_quality_reasons(_fact(claim, entity)))
                self.assertNotIn("canonical_incomplete_proposition", _canonical_proposition_quality_reasons(claim, claim))

    def test_heading_topic_cannot_be_promoted_to_the_reporting_agent(self):
        for topic in ("DNACPR notices", "Hospital access"):
            with self.subTest(topic=topic):
                claim = f"{topic}: a campaigner says the government has misunderstood the demands."
                invented = f"{topic} report that a campaigner says the government has misunderstood the demands."
                self.assertIn("canonical_title_relation_invention", _canonical_proposition_quality_reasons(invented, claim))
                topical = f"Regarding {topic}, a campaigner says the government has misunderstood the demands."
                self.assertNotIn("canonical_title_relation_invention", _canonical_proposition_quality_reasons(topical, claim))

    def test_formula_encoding_fragments_fail_input_preflight_and_output_checks(self):
        runner = _load_v24_capacity_runner()
        for claim in (
            "The signal has a /spl lscr//sub 1/ norm of 2.",
            "The probability is 1-O(N/sup -M/) with 2 samples.",
            "The squared norm is x<sup>2</sup>.",
        ):
            with self.subTest(claim=claim):
                fact = _fact(claim, "2")
                fact["proposition_span"] = [0, len(claim)]
                valid, reasons = runner._fresh_fact_preflight(fact, {"full_text": claim})
                self.assertFalse(valid)
                self.assertIn("query_input_corrupt_text", reasons)
                self.assertIn("canonical_corrupt_text", _canonical_proposition_quality_reasons(claim, claim))
                self.assertIn("q_plus_not_natural_question", self._query_reasons(claim, "Is it correct that " + claim.rstrip(".") + "?", original="2", replacement="3"))

    def test_local_context_must_identify_the_object_document_or_experimental_procedure(self):
        for claim, query in (
            ("The mathematical description is a double-exponential function with parameter E0.", "Is the mathematical description a double-exponential function with parameter E0?"),
            ("The joint position paper is by the Heart Failure Association.", "Is the joint position paper by the Heart Failure Association?"),
            ("The 2010 Elsevier Ltd. article describes the E0 model.", "Does the 2010 Elsevier Ltd. article describe the E0 model?"),
            ("The 2022 Example Press article describes the E0 model.", "Does the 2022 Example Press article describe the E0 model?"),
            ("During straining (phase II), pressure fell by 11% from control values.", "Did pressure fall by 11% from control values during straining (phase II)?"),
        ):
            with self.subTest(query=query):
                self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, query))
        for claim, query in (
            ("The mathematical description of double-exponential pulses uses E0.", "Does the mathematical description of double-exponential pulses use E0?"),
            ("The joint position paper on heart failure with COVID-19 is by the Heart Failure Association.", "Is the joint position paper on heart failure with COVID-19 by the Heart Failure Association?"),
            ("During phase II of the Valsalva maneuver, pressure fell by 11% from control values.", "Did pressure fall by 11% from control values during phase II of the Valsalva maneuver?"),
            ("In the ACCORD trial, pressure fell by 11% from control values.", "Did pressure fall by 11% from control values in the ACCORD trial?"),
        ):
            with self.subTest(query=query):
                self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(claim, query))

    def test_free_mathematical_variables_need_local_definitions_without_rejecting_standard_terms(self):
        claim = "With probability at least 1-O(N^-M), f can be reconstructed exactly."
        query = "Can f be reconstructed exactly with probability at least 1-O(N^-M)?"
        self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, query, original="1", replacement="2"))
        defined = "For a signal f with N samples and a positive constant M, f can be reconstructed with probability at least 1-O(N^-M)."
        self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(defined, "Is it correct that " + defined[0].lower() + defined[1:-1] + "?", original="1", replacement="2"))
        for claim, query in (
            ("Oxygen injection site affects FIO2 during noninvasive ventilation.", "Does oxygen injection site affect FIO2 during noninvasive ventilation?"),
            ("The transformer supplies DC power in Delaware.", "Does the transformer supply DC power in Delaware?"),
        ):
            with self.subTest(query=query):
                self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(claim, query))

    def test_us_country_abbreviation_is_distinct_from_first_person_us(self):
        claim = "More US labs could provide diagnostic tests."
        self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
        self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(
            claim, "Could more US labs provide diagnostic tests?", original="US", replacement="Canadian",
        ))
        self.assertTrue(deterministic_role_judge({
            "true_claim": claim, "replacement_entity": "Canadian",
            "canonical_counterfactual": claim.replace("US", "Canadian"),
        })["compatible"])
        for claim, query in (
            ("The record identifies us in Delaware.", "Does the record identify us in Delaware?"),
            ("Us and Alice registered in Delaware.", "Did Us and Alice register in Delaware?"),
            ("We work in US labs in Delaware.", "Do we work in US labs in Delaware?"),
        ):
            with self.subTest(query=query):
                self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, query))

    def test_grounded_title_punctuation_and_bound_reflexive_remain_valid(self):
        title = "Walking on Water : Biolocomotion at the Interface"
        original = "We consider the hydrodynamics of creatures capable of sustaining themselves on the water surface."
        source = title + "\n\n" + original
        for quoted in ("Walking on Water: Biolocomotion at the Interface", '"Walking on Water: Biolocomotion at the Interface"'):
            with self.subTest(title=quoted):
                claim = f"The article titled {quoted} considers the hydrodynamics of creatures capable of sustaining themselves on the water surface."
                query = f"Does the article titled {quoted} consider the hydrodynamics of creatures capable of sustaining themselves on the water surface?"
                self.assertEqual(_canonical_proposition_quality_reasons(claim, original, source_text=source), [])
                self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(
                    claim, query, original="water surface", replacement="ice surface", source_text=source,
                ))
        self.assertTrue(v24._has_unresolved_reference("Can they sustain themselves on the water surface?"))
        self.assertTrue(v24._has_unresolved_reference("Is sustaining themselves possible on the water surface?"))

    def test_inverted_goal_question_accepts_complete_title_before_infinitive(self):
        title = "A Topological Data Analysis Approach on Predicting Phenotypes from Gene Expression Data"
        claim = f"The goal of the study titled {title} was to investigate if RNA sequencing supports phenotype prediction."
        source = title + "\n\n" + claim
        query = f"Was the goal of the study titled {title} to investigate if RNA sequencing supports phenotype prediction?"
        self.assertNotIn("q_plus_unresolved_reference", self._query_reasons(
            claim, query, original="RNA sequencing", replacement="microarray profiling", source_text=source,
        ))
        for wrong_title in (title + " Handbook", "A Topological Data Analysis Approach", "A Topological Data Analysis Approach on Unrelated Data"):
            with self.subTest(wrong_title=wrong_title):
                bad = query.replace(title, wrong_title)
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(
                    claim, bad, original="RNA sequencing", replacement="microarray profiling", source_text=source,
                ))

    def test_nominal_title_cannot_be_promoted_to_an_unidentified_actor(self):
        original = "A brief journey into medical care and disease in ancient Egypt."
        invented = "A brief journey explores medical care and disease in ancient Egypt."
        self.assertIn("canonical_title_relation_invention", _canonical_proposition_quality_reasons(invented, original))
        self.assertEqual(_canonical_proposition_quality_reasons(
            "Gastroenterology was a subject in ancient Egypt.", "Gastroenterology in ancient Egypt.",
            source_text="Gastroenterology in ancient Egypt.\n\nGastroenterology was a medical specialty in ancient Egypt.",
        ), [])

    def test_nominal_title_check_preserves_clear_predicates_and_grounded_titles(self):
        for claim in (
            "The surgeon operated on the patient in Delaware.",
            "The cell responds to light in Delaware.",
            "The response of the colon increases after eating.",
            "Dietary fiber and personality factors were evaluated in Delaware.",
        ):
            with self.subTest(claim=claim):
                self.assertFalse(v24._is_title_fragment(claim))
        title = "Methods for Measuring Flows: A Tutorial"
        claim = f'The article titled "{title}" characterizes fluid motion in Delaware.'
        self.assertNotIn("canonical_incomplete_proposition", _canonical_proposition_quality_reasons(
            claim, claim, source_text=title + "\n\n" + claim,
        ))

    def test_spelled_counts_and_counted_subsets_need_an_identified_population(self):
        for claim in (
            "Eleven patients had experienced one episode in Delaware.",
            "One hundred and twenty patients recovered in Delaware.",
            "Nineteen of 29 reptiles had renal inflammation in Delaware.",
            "Three of twelve specimens were positive in Delaware.",
        ):
            with self.subTest(claim=claim):
                self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, "Is it correct that " + claim[:-1] + "?"))
        for claim in (
            "In the Helsinki Hospital cohort, eleven patients recovered in Delaware.",
            "Among 29 reptiles with renal flagellate infection, nineteen had nephritis in Delaware.",
            "Three of twelve specimens from the Helsinki Hospital cohort were positive in Delaware.",
        ):
            with self.subTest(claim=claim):
                self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))

    def test_clinical_outcomes_and_participating_units_need_scope(self):
        cases = (
            "Cognitive behavioral therapy led to complete remission of symptoms in Delaware.",
            "Data collected in Delaware were retrieved from the digital databases of participating units.",
            "There were no viral infections or operation-related complications in Delaware.",
        )
        for claim in cases:
            with self.subTest(claim=claim):
                self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, "Is it correct that " + claim[:-1] + "?"))
                scoped = "In the Helsinki Hospital cohort, " + claim[0].lower() + claim[1:]
                self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(scoped, claim))
        defined = "Cognitive behavioral therapy led to remission of symptoms of bowel obsession syndrome in a patient with chronic constipation."
        self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(defined, defined))
        self.assertFalse(v24._has_unresolved_document_reference("No infections were observed among patients with renal disease."))

    def test_named_study_does_not_resolve_missing_comparison_or_experimental_details(self):
        for claim in (
            "In the ACCORD study in Delaware, a similar sequence was identified.",
            "In the ACCORD study in 2019 in Delaware, a similar sequence was shown to form a helix.",
            "In the ACCORD study in Delaware, a similar protein was isolated from tissue.",
            "In the ACCORD study in Delaware, weight changes were similar in all groups.",
            "In the ACCORD study in Delaware, weight loss was observed relative to day 0.",
        ):
            with self.subTest(claim=claim):
                self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, "Is it correct that " + claim[:-1] + "?"))
        for claim in (
            "A sequence similar to the N-terminal sequence of protein 2C was identified in Delaware.",
            "In Delaware, weight changes were similar in both groups receiving chitosan or placebo.",
            "In Delaware, weight loss was observed relative to pretreatment day 0.",
            "In Delaware, weight loss was observed relative to day 0 of treatment.",
            "In Delaware, weight loss was observed relative to day 0, when treatment started.",
            "In Delaware, treatment began on day 0 and weight loss was observed on day 7.",
            "In Delaware, a similar sequence to the protein 2C sequence was identified.",
            "Two similar sequences were identified in Delaware.",
        ):
            with self.subTest(claim=claim):
                self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))

    def test_named_study_cannot_replace_source_analysis_subgroup(self):
        original = "Seventy-seven percent of all stools were normal."
        source = (
            "The Popcol study\n\n268 subjects completed diaries. "
            "124 subjects had no organic gastrointestinal abnormality, IBS, or relevant medication. " + original
        )
        underspecified = "In the Popcol study, seventy-seven percent of all stools were normal."
        self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(
            underspecified, original, source_text=source,
        ))
        query = "Were seventy-seven percent of all stools in the Popcol study normal?"
        self.assertIn("unresolved_reference", v24._query_surface_reasons(query, original, source_text=source))
        for scope in (
            "Among 124 subjects without organic gastrointestinal abnormality, IBS, or relevant medication",
            "Among 124 subjects with no organic gastrointestinal abnormality, IBS, or relevant medication",
            "Among subjects free of organic gastrointestinal abnormality, IBS, or relevant medication",
        ):
            with self.subTest(scope=scope):
                complete = scope + ", seventy-seven percent of all stools were normal."
                self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(complete, original, source_text=source))
                self.assertNotIn("unresolved_reference", v24._query_surface_reasons("Is it correct that " + complete[:-1] + "?", original, source_text=source))
        unrelated = "No organic disease was identified in a different study.\n\nAll participants completed diaries. " + original
        self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(underspecified, original, source_text=unrelated))

    def test_relative_time_needs_an_explicit_time_anchor(self):
        for claim in (
            "Cross-domain mapping has been active in recent years in Delaware.",
            "A protein structure was recently identified in Delaware.",
        ):
            with self.subTest(claim=claim):
                self.assertIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))
                self.assertIn("q_plus_unresolved_reference", self._query_reasons(claim, "Is it correct that " + claim[:-1] + "?"))
                anchored = "As reported in 2019, " + claim[0].lower() + claim[1:]
                self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(anchored, anchored))
        claim = "Robot manipulators traditionally use serial links in Delaware."
        self.assertNotIn("canonical_unresolved_reference", _canonical_proposition_quality_reasons(claim, claim))

    def test_ambiguous_protection_role_is_not_preserved_as_natural_wording(self):
        claim = "The Google Chrome browser protects malicious websites from damaging the browser system."
        query = "Does the Google Chrome browser protect malicious websites from damaging the browser system?"
        self.assertIn("q_plus_not_natural_question", self._query_reasons(
            claim, query, original="Google Chrome browser", replacement="Mozilla Firefox browser",
        ))
        for claim, query in (
            ("The browser prevents malicious websites from damaging the system in Delaware.", "Does the browser prevent malicious websites from damaging the system in Delaware?"),
            ("The browser protects websites from malicious scripts in Delaware.", "Does the browser protect websites from malicious scripts in Delaware?"),
            ("Therapy protects patients from harming themselves in Delaware.", "Does therapy protect patients from harming themselves in Delaware?"),
        ):
            with self.subTest(query=query):
                self.assertNotIn("q_plus_not_natural_question", self._query_reasons(claim, query))

    def test_both_queries_must_preserve_resolved_clinical_scope(self):
        claim = "Eleven patients had had one episode and nine had experienced multiple episodes."
        fact = _fact(claim, "Eleven")
        source = "Defecation syncope.\n\nTwenty patients with defecation syncope were evaluated. " + claim
        scope = "in the study of patients with defecation syncope, "
        package = _package(
            "Fifteen", scope + claim.replace("Eleven", "{ENTITY}"),
            "Is it correct that " + scope + claim[:-1] + "?",
            "Is it correct that " + scope + claim.replace("Eleven", "Fifteen")[:-1] + "?",
        )
        kwargs = dict(similarity_fn=_semantic_similarity, eligibility_judge=lambda _: {"correction_eligible": True},
                      role_judge=lambda _: {"compatible": True, "plausibility": "strong"})
        self.assertTrue(evaluate_candidate(fact, source, package, **kwargs)["accepted"])
        package["q_minus_text"] = "Is it correct that " + claim.replace("Eleven", "Fifteen")[:-1] + "?"
        result = evaluate_candidate(fact, source, package, **kwargs)
        self.assertFalse(result["accepted"])
        self.assertIn("q_minus_unresolved_reference", result["rejection_reasons"])


class V24CanaryResumeTests(unittest.TestCase):
    def setUp(self):
        self.runner = _load_v24_capacity_runner()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "canary"
        self.input_path = self.root / "canary_inputs.jsonl"
        self.config = load_v24_config(Path(__file__).resolve().parents[1])
        self.config["development"]["canary_pair_count"] = 3
        self.profile = {"profile_name": "mock", "model": "mock-luna", "temperature": 0,
                        "max_tokens": 2048, "timeout": 120, "extra_body": {"seed": 42}}
        self.binding = {"dataset": "nfcorpus", "pool_sha256": "mock-pool"}
        self.facts = {}
        sources = {}
        inputs = []
        for index in range(3):
            fact = _selection_fact(0, f"Person{index}")
            source = _selection_source([fact], source_key=f"source-{index}")
            fact.update(v24._source_identity(source))
            fact.update({"upstream_pair_id": f"pair-{index}",
                         "proposition_span": [0, len(fact["true_claim"])]})
            self.facts[source["source_key"]] = fact
            sources[("nfcorpus", source["source_key"])] = source
            inputs.append({**fact, "pair_id": fact["upstream_pair_id"],
                           "canary_pair_index": index + 1, "candidate_pool_sha256": "mock-pool"})
        write_jsonl(inputs, self.input_path)
        reader = Mock()
        reader.binding.side_effect = lambda: copy.deepcopy(self.binding)
        reader.facts_for_source.side_effect = lambda source: [self.facts[source["source_key"]]]
        self.scorer = Mock(side_effect=_semantic_similarity)
        self.scorer.identity.return_value = {"kind": "mock", "revision": "embedding-r1"}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, replacement in (
            ("load_v24_config", self.config),
            ("_load_canary_candidate_pools", {("nfcorpus", "mock-pool"): reader}),
            ("_source_lookup", sources),
        ):
            self.stack.enter_context(patch.object(self.runner, target, return_value=replacement))
        self.provider_builder = self.stack.enter_context(patch.object(self.runner, "build_luna_candidate_provider"))
        self.scorer_builder = self.stack.enter_context(patch.object(
            self.runner, "build_v24_semantic_similarity", return_value=self.scorer,
        ))
        self.stack.enter_context(patch("src.llm.factory.load_llm_profiles", return_value={}))
        self.stack.enter_context(patch("src.llm.factory.resolve_effective_llm_profile", return_value=self.profile))
        self.stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("no_network")))

    def _provider(self, *, interrupt_key=None, fail_key=None):
        counts = {"logical_api_calls": 0, "physical_attempts": 0, "transport_retry_count": 0}

        def provide(fact):
            counts["logical_api_calls"] += 1
            if fact["source_key"] == interrupt_key:
                raise KeyboardInterrupt()
            counts["physical_attempts"] += 2
            counts["transport_retry_count"] += 1
            if fact["source_key"] == fail_key:
                raise ValueError("private-response-must-not-be-logged")
            return [_selection_package(fact, 0)]

        provider = Mock(side_effect=provide)
        provider.profile = self.profile
        provider.stats.side_effect = lambda: {
            **counts, "provider_model_ids": ["mock-luna"] if counts["physical_attempts"] else [],
            "profile_name": "mock", "configured_model": "mock-luna", "failures": [],
        }
        self.provider_builder.return_value = provider
        return provider

    def _run(self, *, resume=False, show_progress=False):
        return self.runner.run_canary(
            self.root, input_path=self.input_path, output_dir=self.output,
            candidate_pools=["mock"], resume=resume, show_progress=show_progress,
        )

    def _interrupt(self, *, key="source-1", fail_key=None):
        provider = self._provider(interrupt_key=key, fail_key=fail_key)
        with self.assertRaises(KeyboardInterrupt):
            self._run()
        return provider

    def test_interruption_saves_results_and_resume_skips_completed_sources(self):
        self._interrupt()
        result_path = self.output / "canary_results.jsonl"
        saved = list(read_jsonl(result_path))
        self.assertEqual([row["source_key"] for row in saved], ["source-0"])
        progress = read_json(self.output / "canary_summary.json")
        self.assertEqual(progress["status"], "interrupted")
        self.assertEqual(progress["completed_pair_count"], 1)
        self.assertEqual(progress["active_input_index"], 1)
        self.assertFalse(progress["external_call_counts_complete"])
        self.scorer.close.assert_called_once()
        provider = self._provider()
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            summary = self._run(resume=True, show_progress=True)
        self.assertEqual([call.args[0]["source_key"] for call in provider.call_args_list],
                         ["source-1", "source-2"])
        self.assertEqual(list(read_jsonl(result_path))[0], saved[0])
        self.assertEqual(summary["completed_pair_count"], 3)
        self.assertEqual(summary["passed_pair_count"], 3)
        self.assertEqual(summary["provider"]["logical_api_calls"], 4)
        self.assertEqual(summary["external_calls_performed"], 6)
        self.assertFalse(summary["external_call_counts_complete"])
        self.assertIn("1/3", output.getvalue())
        self.assertIn("3/3", output.getvalue())
        self.assertEqual(summary["result_sha256"], sha256_file(result_path))

    def test_first_source_interruption_still_has_a_resumable_identity(self):
        self._interrupt(key="source-0")
        self.assertEqual(list(read_jsonl(self.output / "canary_results.jsonl")), [])
        self.assertEqual(read_json(self.output / "canary_summary.json")["completed_pair_count"], 0)
        provider = self._provider()
        self.assertEqual(self._run(resume=True)["passed_pair_count"], 3)
        self.assertEqual(provider.call_count, 3)

    def test_progress_is_saved_before_each_request_and_marks_inflight_counts(self):
        provider = self._provider()
        provide = provider.side_effect
        snapshots = []

        def inspect_progress(fact):
            snapshots.append(read_json(self.output / "canary_summary.json"))
            return provide(fact)

        provider.side_effect = inspect_progress
        self._run()
        self.assertEqual([row["completed_pair_count"] for row in snapshots], [0, 1, 2])
        self.assertEqual([row["active_input_index"] for row in snapshots], [0, 1, 2])
        self.assertTrue(all(row["status"] == "running" for row in snapshots))
        self.assertTrue(all(not row["external_call_counts_complete"] for row in snapshots))

    def test_completed_resume_is_offline_and_does_not_rewrite_results(self):
        self._provider()
        summary = self._run()
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        self.provider_builder.side_effect = AssertionError("no_provider_on_completed_resume")
        self.scorer_builder.side_effect = AssertionError("no_gpu_on_completed_resume")
        self.assertEqual(self._run(resume=True), summary)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_failed_rows_are_retained_and_completed_failure_stays_failed(self):
        self._interrupt(key="source-2", fail_key="source-0")
        saved = list(read_jsonl(self.output / "canary_results.jsonl"))
        self.assertFalse(saved[0]["eligible"])
        self.assertNotIn("private-response", json.dumps(saved))
        provider = self._provider()
        with self.assertRaisesRegex(RuntimeError, "hard_gate_failed:2/3"):
            self._run(resume=True)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(list(read_jsonl(self.output / "canary_results.jsonl"))[:2], saved)
        self.provider_builder.side_effect = AssertionError("failed_rows_must_not_be_retried")
        self.scorer_builder.side_effect = AssertionError("no_gpu")
        with self.assertRaisesRegex(RuntimeError, "hard_gate_failed:2/3"):
            self._run(resume=True)

    def test_existing_output_requires_explicit_resume(self):
        self._interrupt()
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        self.provider_builder.side_effect = AssertionError("no_overwrite")
        with self.assertRaisesRegex(ValueError, "output_exists"):
            self._run()
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_resume_rejects_input_config_pool_fact_and_model_drift_before_runtime(self):
        self._interrupt()
        original_input = self.input_path.read_bytes()
        original_config = copy.deepcopy(self.config)
        original_binding = copy.deepcopy(self.binding)
        original_facts = copy.deepcopy(self.facts)
        original_profile = copy.deepcopy(self.profile)
        self.provider_builder.side_effect = AssertionError("drift_must_precede_provider")
        self.scorer_builder.side_effect = AssertionError("drift_must_precede_gpu")
        for kind in ("input", "config", "pool", "fact", "model"):
            with self.subTest(kind=kind):
                if kind == "input":
                    write_jsonl(list(reversed(list(read_jsonl(self.input_path)))), self.input_path)
                elif kind == "config":
                    self.config["selection_seed"] += 1
                elif kind == "pool":
                    self.binding["pool_sha256"] = "changed"
                elif kind == "fact":
                    self.facts["source-0"]["source_hash"] = "changed"
                else:
                    self.profile["model"] = "different-luna"
                with self.assertRaisesRegex(RuntimeError, "identity_drift"):
                    self._run(resume=True)
                self.input_path.write_bytes(original_input)
                for target, original in ((self.config, original_config), (self.binding, original_binding),
                                         (self.facts, original_facts), (self.profile, original_profile)):
                    target.clear()
                    target.update(copy.deepcopy(original))

    def test_resume_rejects_tampered_or_truncated_results_before_runtime(self):
        self._interrupt()
        path = self.output / "canary_results.jsonl"
        original = path.read_bytes()
        self.provider_builder.side_effect = AssertionError("no_provider_for_corrupt_checkpoint")
        self.scorer_builder.side_effect = AssertionError("no_gpu_for_corrupt_checkpoint")
        for corruption in ("changed", "truncated", "removed"):
            with self.subTest(corruption=corruption):
                path.write_bytes(original)
                if corruption == "changed":
                    rows = list(read_jsonl(path))
                    rows[0]["selected_pair"]["q_plus_text"] = "Tampered query?"
                    write_jsonl(rows, path)
                else:
                    path.write_bytes(original[:-9] if corruption == "truncated" else b"")
                with self.assertRaisesRegex(RuntimeError, "checkpoint"):
                    self._run(resume=True)
        path.write_bytes(original)

    def test_results_ahead_of_summary_resume_without_repeating_saved_source(self):
        self._provider()
        write = self.runner.write_json

        def fail_summary(payload, path, **kwargs):
            if payload.get("completed_pair_count") == 1:
                raise OSError("simulated_summary_write_failure")
            return write(payload, path, **kwargs)

        with patch.object(self.runner, "write_json", side_effect=fail_summary):
            with self.assertRaises(OSError):
                self._run()
        self.assertEqual(len(list(read_jsonl(self.output / "canary_results.jsonl"))), 1)
        self.assertEqual(read_json(self.output / "canary_summary.json")["completed_pair_count"], 0)
        provider = self._provider()
        summary = self._run(resume=True)
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(summary["external_calls_performed"], 6)

    def test_interrupt_after_atomic_replace_keeps_disk_result_recoverable(self):
        self._provider()
        write = self.runner.write_jsonl_atomic

        def interrupt_after_replace(rows, path):
            count = write(rows, path)
            if len(rows) == 1:
                raise KeyboardInterrupt()
            return count

        with patch.object(self.runner, "write_jsonl_atomic", side_effect=interrupt_after_replace):
            with self.assertRaises(KeyboardInterrupt):
                self._run()
        provider = self._provider()
        self.assertEqual(self._run(resume=True)["passed_pair_count"], 3)
        self.assertEqual(provider.call_count, 2)

    def test_partial_temporary_write_does_not_destroy_completed_results(self):
        self._provider()
        write = self.runner.write_jsonl_atomic

        def fail_before_replace(rows, path):
            if len(rows) == 2:
                path.with_suffix(path.suffix + ".tmp").write_text('{"incomplete":', encoding="utf-8")
                raise OSError("simulated_result_write_failure")
            return write(rows, path)

        with patch.object(self.runner, "write_jsonl_atomic", side_effect=fail_before_replace):
            with self.assertRaises(OSError):
                self._run()
        saved = list(read_jsonl(self.output / "canary_results.jsonl"))
        self.assertEqual(len(saved), 1)
        provider = self._provider()
        self.assertEqual(self._run(resume=True)["passed_pair_count"], 3)
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(list(read_jsonl(self.output / "canary_results.jsonl"))[0], saved[0])
        self.assertFalse((self.output / "canary_results.jsonl.tmp").exists())

    def test_unacknowledged_result_corruption_is_rejected(self):
        self._provider()
        write = self.runner.write_json

        def fail_summary(payload, path, **kwargs):
            if payload.get("completed_pair_count") == 1:
                raise OSError("summary_not_updated")
            return write(payload, path, **kwargs)

        with patch.object(self.runner, "write_json", side_effect=fail_summary):
            with self.assertRaises(OSError):
                self._run()
        path = self.output / "canary_results.jsonl"
        rows = list(read_jsonl(path))
        rows[-1]["selected_pair"]["q_plus_text"] = "Changed after the write?"
        write_jsonl(rows, path)
        self.provider_builder.side_effect = AssertionError("no_calls_for_corrupt_unacknowledged_row")
        self.scorer_builder.side_effect = AssertionError("no_gpu_for_corrupt_unacknowledged_row")
        with self.assertRaisesRegex(RuntimeError, "checkpoint_hash_drift"):
            self._run(resume=True)

    def test_all_results_saved_before_final_summary_can_finish_offline(self):
        self._provider()
        write = self.runner.write_json

        def fail_final_summary(payload, path, **kwargs):
            if payload.get("completed_pair_count") == 3:
                raise OSError("simulated_final_summary_write_failure")
            return write(payload, path, **kwargs)

        with patch.object(self.runner, "write_json", side_effect=fail_final_summary):
            with self.assertRaises(OSError):
                self._run()
        self.provider_builder.side_effect = AssertionError("all_sources_already_saved")
        self.scorer_builder.side_effect = AssertionError("no_gpu_needed")
        self.assertEqual(self._run(resume=True)["status"], "passed")

    def test_cli_passes_resume_to_canary(self):
        with patch.object(self.runner, "run_canary", return_value={"status": "passed"}) as run, patch(
            "sys.argv", ["runner", "run-canary", "--input", str(self.input_path),
                         "--output-dir", str(self.output), "--candidate-pool", "mock", "--resume"],
        ), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(self.runner.main(), 0)
        self.assertTrue(run.call_args.kwargs["resume"])


class V24CapacityRunnerTests(unittest.TestCase):
    @staticmethod
    def _config() -> dict[str, object]:
        return {
            "protocol_version": "pcv-mia-v24",
            "development": {"capacity_sample_sources": 3},
            "eligibility": {
                "target_sources": 2250,
                "semantic_correction_retries": 1,
                "max_candidate_facts_per_source": 8,
            },
            "source_pool": {"expected_source_counts": {"nfcorpus": 5210}},
        }

    @staticmethod
    def _sources(count: int = 3) -> list[dict[str, object]]:
        return [
            {
                "dataset": "nfcorpus",
                "source_key": f"source-{index}",
                "source_order_rank": str(index),
                "source_hash": f"{index + 1:064x}",
                "normalized_text_hash": f"{index + 11:064x}",
                "full_text": f"Source {index}.",
            }
            for index in range(count)
        ]

    @staticmethod
    def _screen_result(*, eligible: bool, diversity: int = 3) -> dict[str, object]:
        return {
            "eligible": eligible,
            "candidate_fact_count": 10,
            "processed_fact_count": 4,
            "unprocessed_fact_count": 6,
            "candidate_package_count": 12,
            "early_stop_triggered": diversity == 3,
            "original_entity_diversity": diversity,
        }

    def test_offline_capacity_reports_raw_fact_feasibility_only(self):
        runner = _load_v24_capacity_runner()
        sources = self._sources(2)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(runner, "load_v24_config", return_value=self._config()), patch.object(
                runner, "iter_frozen_source_pool", side_effect=lambda _root, _dataset: iter(sources)
            ), patch.object(
                runner,
                "enumerate_candidate_facts",
                side_effect=lambda source: [object()] * (
                    4 if source["source_key"] == "source-0" else 2
                ),
            ), patch.object(
                runner,
                "build_luna_candidate_provider",
                side_effect=AssertionError("offline_capacity_must_not_build_provider"),
            ):
                result = runner.run_capacity_check(
                    root,
                    dataset="nfcorpus",
                    sample_sources=2,
                    use_luna=False,
                    output_dir="attempt-offline",
                    allow_legacy_facts=True,
                    resume=False,
                    show_progress=False,
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["capacity_status"], "estimate_only")
            self.assertEqual(result["raw_fact_budget_feasible_source_count"], 1)
            self.assertEqual(result["raw_fact_budget_feasible_source_rate"], 0.5)
            self.assertEqual(result["projected_raw_fact_budget_feasible_source_count"], 2605)
            self.assertIsNone(result["observed_eligible_source_rate"])
            self.assertIsNone(result["projected_eligible_source_count"])
            self.assertEqual(result["processed_fact_count"], 0)
            self.assertEqual(result["unprocessed_fact_count"], 6)
            self.assertTrue(
                (root / "attempt-offline" / "nfcorpus.offline_estimate.json").is_file()
            )

    def test_luna_capacity_checkpoint_resumes_only_unfinished_sources(self):
        runner = _load_v24_capacity_runner()
        sources = self._sources(3)

        class FakeProvider:
            def __init__(self) -> None:
                self.logical_api_calls = 0
                self.physical_attempts = 0
                self.transport_retry_count = 0

            def record(self) -> None:
                self.logical_api_calls += 1
                self.physical_attempts += 2
                self.transport_retry_count += 1

            def stats(self) -> dict[str, object]:
                return {
                    "logical_api_calls": self.logical_api_calls,
                    "physical_attempts": self.physical_attempts,
                    "transport_retry_count": self.transport_retry_count,
                    "provider_model_ids": ["mock-luna"],
                    "profile_name": "mock",
                    "configured_model": "mock-luna",
                    "failures": [],
                }

        class FakeScorer:
            def close(self) -> None:
                return None

            def identity(self) -> dict[str, object]:
                return {"kind": "mock_semantic_cosine", "threshold": 0.8}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = Path("attempt-luna")
            first_provider = FakeProvider()

            def first_screen(source: dict[str, object], **_kwargs: object) -> dict[str, object]:
                if source["source_key"] == "source-1":
                    raise KeyboardInterrupt()
                first_provider.record()
                return self._screen_result(eligible=True)

            common_patches = (
                patch.object(runner, "load_v24_config", return_value=self._config()),
                patch.object(runner, "iter_frozen_source_pool", return_value=iter(sources)),
                patch.object(runner, "build_luna_candidate_provider", return_value=first_provider),
                patch.object(runner, "build_v24_semantic_similarity", return_value=FakeScorer()),
            )
            with common_patches[0], common_patches[1], common_patches[2], common_patches[3], patch.object(
                runner,
                "screen_source",
                side_effect=first_screen,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    runner.run_capacity_check(
                        root,
                        dataset="nfcorpus",
                        sample_sources=3,
                        use_luna=True,
                        output_dir=output_dir,
                        resume=False,
                        allow_legacy_facts=True,
                        show_progress=False,
                    )

            checkpoint = root / output_dir / "nfcorpus.luna_sample.checkpoint.jsonl"
            checkpoint_rows = list(read_jsonl(checkpoint))
            self.assertEqual(len(checkpoint_rows), 1)
            self.assertEqual(checkpoint_rows[0]["source_index"], 0)

            second_provider = FakeProvider()

            def resumed_screen(source: dict[str, object], **_kwargs: object) -> dict[str, object]:
                second_provider.record()
                if source["source_key"] == "source-1":
                    return self._screen_result(eligible=False, diversity=1)
                return self._screen_result(eligible=True)

            with patch.object(runner, "load_v24_config", return_value=self._config()), patch.object(
                runner,
                "iter_frozen_source_pool",
                side_effect=lambda _root, _dataset: iter(sources),
            ), patch.object(
                runner, "build_luna_candidate_provider", return_value=second_provider
            ), patch.object(
                runner, "build_v24_semantic_similarity", return_value=FakeScorer()
            ), patch.object(
                runner,
                "screen_source",
                side_effect=resumed_screen,
            ) as screen_mock:
                result = runner.run_capacity_check(
                    root,
                    dataset="nfcorpus",
                    sample_sources=3,
                    use_luna=True,
                    output_dir=output_dir,
                    resume=True,
                    allow_legacy_facts=True,
                    show_progress=False,
                )

            self.assertEqual(screen_mock.call_count, 2)
            self.assertTrue(result["resumed"])
            self.assertEqual(result["candidate_source_count"], 3)
            self.assertAlmostEqual(result["observed_eligible_source_rate"], 2 / 3)
            self.assertEqual(result["raw_fact_budget_feasible_source_count"], 3)
            self.assertEqual(result["capacity_status"], "sample_projection_at_or_above_target")
            self.assertEqual(result["provider"]["logical_api_calls"], 3)
            self.assertEqual(result["external_calls_performed"], 6)
            self.assertEqual(len(list(read_jsonl(checkpoint))), 3)
            self.assertTrue(
                (root / output_dir / "nfcorpus.luna_sample.json").is_file()
            )

            with patch.object(runner, "load_v24_config", return_value=self._config()), patch.object(
                runner,
                "iter_frozen_source_pool",
                side_effect=lambda _root, _dataset: iter(sources),
            ), patch.object(
                runner,
                "build_luna_candidate_provider",
                side_effect=AssertionError("completed_resume_must_not_build_provider"),
            ):
                cached = runner.run_capacity_check(
                    root,
                    dataset="nfcorpus",
                    sample_sources=3,
                    use_luna=True,
                    output_dir=output_dir,
                    resume=True,
                    allow_legacy_facts=True,
                    show_progress=False,
                )
            self.assertEqual(cached["run_fingerprint"], result["run_fingerprint"])

            append_jsonl_record({"tampered": True}, checkpoint)
            with patch.object(runner, "load_v24_config", return_value=self._config()), patch.object(
                runner,
                "iter_frozen_source_pool",
                side_effect=lambda _root, _dataset: iter(sources),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "v24_capacity_checkpoint_hash_drift"
                ):
                    runner.run_capacity_check(
                        root,
                        dataset="nfcorpus",
                        sample_sources=3,
                        use_luna=True,
                        output_dir=output_dir,
                        resume=True,
                        allow_legacy_facts=True,
                        show_progress=False,
                    )

    def test_capacity_attempt_refuses_implicit_overwrite(self):
        runner = _load_v24_capacity_runner()
        sources = self._sources(1)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(runner, "load_v24_config", return_value=self._config()), patch.object(
                runner,
                "iter_frozen_source_pool",
                side_effect=lambda _root, _dataset: iter(sources),
            ), patch.object(
                runner, "enumerate_candidate_facts", return_value=[object()] * 3
            ):
                runner.run_capacity_check(
                    root,
                    dataset="nfcorpus",
                    sample_sources=1,
                    use_luna=False,
                    output_dir="attempt",
                    resume=False,
                    allow_legacy_facts=True,
                    show_progress=False,
                )
                with self.assertRaisesRegex(
                    RuntimeError, "v24_capacity_summary_exists_use_resume"
                ):
                    runner.run_capacity_check(
                        root,
                        dataset="nfcorpus",
                        sample_sources=1,
                        use_luna=False,
                        output_dir="attempt",
                        resume=False,
                        allow_legacy_facts=True,
                        show_progress=False,
                    )

    def test_fresh_canary_preflight_reuses_existing_fact_quality_gate(self):
        runner = _load_v24_capacity_runner()
        source = {
            "dataset": "scidocs",
            "source_key": "fresh-source",
            "full_text": "Citizens were unable to attend the Nov.",
        }
        bad_fact = {
            "true_claim": source["full_text"],
            "original_entity": "Citizens",
            "proposition_span": [0, len(source["full_text"])],
            "original_span": [0, 8],
        }
        passed, reasons = runner._fresh_fact_preflight(bad_fact, source)
        self.assertFalse(passed)
        self.assertIn("candidate_fact_incomplete_temporal_reference", reasons)

        valid_source = {
            "dataset": "nfcorpus",
            "source_key": "fresh-valid",
            "full_text": "The company is incorporated in Delaware.",
        }
        valid_fact = {
            "true_claim": valid_source["full_text"],
            "original_entity": "Delaware",
            "proposition_span": [0, len(valid_source["full_text"])],
            "original_span": [31, 39],
        }
        passed, reasons = runner._fresh_fact_preflight(valid_fact, valid_source)
        self.assertTrue(passed, reasons)

    def test_fresh_canary_fixture_preference_avoids_function_word_spans(self):
        runner = _load_v24_capacity_runner()
        valid_fact = {
            "true_claim": "The company is incorporated in Delaware.",
            "original_entity": "Delaware",
        }
        noisy_fact = {
            "true_claim": (
                "For the years ended December 31, 2020 and 2019, gross interest "
                "income was recorded."
            ),
            "original_entity": "For",
        }
        heading_glue_fact = {
            "true_claim": (
                "Chromatographic and mass spectrometric analysis Samples were analysed "
                "using an LTQ-Orbitrap mass spectrometer."
            ),
            "original_entity": "Thermo Fisher Scientific",
        }
        discourse_entity_fact = {
            "true_claim": "Attached is the final notification report for January, 2002.",
            "original_entity": "Attached",
        }
        self.assertTrue(runner._fresh_canary_fact_is_suitable(valid_fact))
        self.assertFalse(runner._fresh_canary_fact_is_suitable(noisy_fact))
        self.assertFalse(runner._fresh_canary_fact_is_suitable(heading_glue_fact))
        self.assertFalse(runner._fresh_canary_fact_is_suitable(discourse_entity_fact))
        self.assertGreater(
            runner._fresh_canary_fact_selection_score(valid_fact),
            runner._fresh_canary_fact_selection_score(noisy_fact),
        )

    def test_prepare_fresh_canary_is_membership_blind_and_excludes_history(self):
        runner = _load_v24_capacity_runner()
        sources = {
            dataset: {
                "dataset": dataset,
                "source_key": f"fresh-{dataset}",
                "source_order_rank": "0",
                "full_text": "The company is incorporated in Delaware.",
            }
            for dataset in ("nfcorpus", "scidocs", "trec-covid")
        }
        facts = {
            dataset: [{
                "dataset": dataset,
                "source_key": source["source_key"],
                "upstream_pair_id": f"fact-{dataset}",
                "true_claim": source["full_text"],
                "original_entity": "Delaware",
                "original_span": [31, 39],
                "proposition_span": [0, len(source["full_text"])],
                "fact_order": 0,
            }]
            for dataset, source in sources.items()
        }
        config = {
            "protocol_version": "pcv-mia-v24",
            "eligibility": {"max_candidate_facts_per_source": 8},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            historical = {
                "kind": "v24_query_quality_canary_input",
                "dataset": "nfcorpus",
                "source_key": "historical-source",
            }
            historical_path = root / "artifacts/v24/development/old/canary_inputs.jsonl"
            historical_path.parent.mkdir(parents=True)
            from src.utils.io import write_jsonl as _write_jsonl

            _write_jsonl([historical], historical_path)
            with patch.object(runner, "load_v24_config", return_value=config), patch.object(
                runner,
                "iter_frozen_source_pool",
                side_effect=lambda _root, dataset: iter([sources[dataset]]),
            ), patch.object(
                runner,
                "enumerate_candidate_facts",
                side_effect=lambda source: facts[str(source["dataset"])],
            ), patch.object(
                runner,
                "source_pool_bindings",
                return_value={"nfcorpus": {}, "scidocs": {}, "trec-covid": {}},
            ):
                result = runner.prepare_fresh_canary(
                    root,
                    per_dataset=1,
                    output_dir="fresh-canary",
                    allow_legacy_facts=True,
                )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["input_count"], 3)
            self.assertEqual(result["preflight_pass_count"], 3)
            self.assertEqual(result["external_calls_performed"], 0)
            rows = list(read_jsonl(root / "fresh-canary/canary_inputs.jsonl"))
            self.assertEqual({row["dataset"] for row in rows}, {"nfcorpus", "scidocs", "trec-covid"})
            forbidden = {
                "effective_type",
                "counterfactual_entity",
                "counterfactual_claim",
                "membership",
                "retriever_output",
                "victim_response",
                "auc",
            }
            self.assertTrue(all(not forbidden.intersection(row) for row in rows))


class V24CandidateFactPoolTests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.create_connection", side_effect=AssertionError("mock_tests_require_no_network"))
        network.start()
        self.addCleanup(network.stop)

    @staticmethod
    def _config():
        config = load_v24_config(Path(__file__).resolve().parents[1])
        config["candidate_fact_adapter"].update({
            "development_identity_patterns": [], "legacy_development_prefix_manifests": [],
        })
        return config

    @staticmethod
    def _source(index=0, *, dataset="nfcorpus", text=None, chunks=None):
        text = text or f"The record identifies Person{index} as the designated representative."
        return {"dataset": dataset, "source_key": f"s{index}", "source_order_rank": str(index),
                "full_text": text, "chunks": [
                    {"chunk_rank": rank, "row": {"text": chunk}}
                    for rank, chunk in enumerate(chunks or [text])
                ]}

    @staticmethod
    def _proposal(claim, entity):
        return {"true_claim": claim, "original_entity": entity}

    def _extractor(self, effects):
        effects = iter(effects)
        extractor = Mock()
        counts = {"inference_attempts": 0}

        def extract(_text):
            counts["inference_attempts"] += 1
            item = next(effects)
            if isinstance(item, BaseException):
                raise item
            enriched = []
            for proposal in item:
                row = dict(proposal)
                claim, entity = str(row["true_claim"]), str(row["original_entity"])
                start = claim.find(entity)
                if start >= 0 and claim.find(entity, start + 1) < 0:
                    row.update({"entity_label": "OTHER", "entity_span": [start, start + len(entity)],
                                "entity_word_count": len(re.findall(r"\S+", entity))})
                enriched.append(row)
            return {"proposals": enriched, "evidence": {
                "kind": "gliner2_span_detection", "spans": enriched,
            }}

        extractor.side_effect = extract
        extractor.stats.side_effect = lambda: dict(counts)
        extractor.preflight.return_value = {
            "model": "fastino/gliner2-base-v1", "model_revision": "f5b2ecedebe4381b088c1cf276f5bf72a52cac54",
            "backend": "gliner2", "device": "cuda", "use_fp16": True,
            "entity_schema_sha256": v24.sha256_obj(v24.ENTITY_SPAN_SCHEMA),
        }
        return extractor

    def _build(self, root, sources, extractor, *, config=None, output="artifacts/v24/candidate_fact_pools/nfcorpus",
               sample=None, resume=False, fixed_source_identities=None):
        config = config or self._config()
        with patch.object(v24, "load_v24_config", return_value=config), patch.object(
            v24, "source_pool_bindings", return_value={"nfcorpus": {"source_count": len(sources)}}
        ), patch.object(v24, "iter_frozen_source_pool", side_effect=lambda *a, **kw: iter(sources)), patch.object(
            v24, "GLiNER2SpanExtractor", return_value=extractor
        ), patch.object(v24, "_candidate_pool_code_version", return_value={"git_commit": "mock", "module_sha256": "b" * 64}):
            return v24.build_candidate_fact_pool(root, dataset="nfcorpus", output_dir=output,
                                                sample_sources=sample, resume=resume,
                                                fixed_source_identities=fixed_source_identities)

    def test_fixed_development_source_identities_are_bound_and_hash_checked(self):
        sources = [self._source(0), self._source(2)]
        identities = [v24._source_identity(sources[1]), v24._source_identity(sources[0])]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pool = self._build(
                root, sources, self._extractor([[], []]),
                output="artifacts/v24/development/fixed/nfcorpus", sample=2,
                fixed_source_identities=identities,
            )
            self.assertEqual(pool["fixed_source_identities"], [
                {"dataset": "nfcorpus", "source_key": "s0", "source_hash": identities[1]["source_hash"],
                 "normalized_text_hash": identities[1]["normalized_text_hash"]},
                {"dataset": "nfcorpus", "source_key": "s2", "source_hash": identities[0]["source_hash"],
                 "normalized_text_hash": identities[0]["normalized_text_hash"]},
            ])
            self.assertEqual(pool["completed_source_count"], 2)
            self.assertEqual(pool["excluded_source_count"], 0)
            changed = dict(identities[0], source_hash="0" * 64)
            with self.assertRaisesRegex(ValueError, "fixed_source_drift"):
                self._build(
                    root, sources, self._extractor([[], []]),
                    output="artifacts/v24/development/fixed-drift/nfcorpus", sample=2,
                    fixed_source_identities=[identities[1], changed],
                )

    def test_fixed_development_sources_cannot_target_formal_pool(self):
        source = self._source(0)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "fixed_sources_scope_invalid"):
                self._build(
                    Path(temp), [source], self._extractor([[]]),
                    output="artifacts/v24/candidate_fact_pools/nfcorpus", sample=1,
                    fixed_source_identities=[v24._source_identity(source)],
                )

    @unittest.skip("legacy Qwen adapter removed")
    def test_static_unbound_config_and_fixed_adapter_options(self):
        config = self._config()
        config["candidate_fact_adapter"]["model_digest"] = None
        with patch.object(v24.urllib.request, "build_opener", side_effect=AssertionError("no_network")):
            self.assertIsNone(v24.candidate_adapter_identity(config)["config"]["model_digest"])
            with self.assertRaisesRegex(v24.CandidateExtractionError, "digest_unbound"):
                v24.GLiNER2SpanExtractor(config)
        for key, value in [("kind", "gliner"), ("model", "luna"), ("think", True), ("stream", True),
                           ("base_url", "https://remote.example:11434"), ("num_ctx", 4096),
                           ("model_digest", "a" * 12), ("concurrency", 2), ("quantization", "Q8_0"),
                           ("num_predict", 1024)]:
            with self.subTest(key=key):
                changed = self._config()
                changed["candidate_fact_adapter"][key] = value
                with self.assertRaises(ValueError):
                    v24.candidate_adapter_identity(changed)

    @unittest.skip("legacy Qwen adapter removed")
    def test_strict_json_allows_empty_but_rejects_extra_duplicate_or_partial_output(self):
        self.assertEqual(v24.parse_candidate_fact_output('{"facts":[]}'), [])
        for content in ['{"facts":[', '{"facts":[],"facts":[]}', '{"facts":[],"score":1}',
                        '{"facts":[{"true_claim":"A","original_entity":"A","type":"PER"}]}',
                        '{"facts":[{"true_claim":"A","original_entity":null}]}',
                        '{"facts":NaN}', '```json\n{"facts":[]}\n```']:
            with self.subTest(content=content), self.assertRaises(v24.CandidateExtractionError):
                v24.parse_candidate_fact_output(content)

    @unittest.skip("legacy Qwen adapter removed")
    def test_native_chat_freezes_options_and_does_not_inherit_provider_environment(self):
        extractor = v24.GLiNER2SpanExtractor(self._config())
        extractor._identity = {"device": "gpu"}
        with patch.dict("os.environ", {"PCV_SIBLING_BASE_URL": "https://unused.example", "PCV_VICTIM_MODEL": "unused"}), patch.object(
            extractor, "verify_resident"
        ) as resident, patch.object(extractor, "_request", return_value=self._response([])) as request:
            self.assertEqual(extractor("No relevant fact.")["proposals"], [])
        path, body = request.call_args.args
        self.assertEqual(path, "/api/chat")
        self.assertEqual(body["model"], "qwen3.5:4b")
        self.assertIs(body["think"], False)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["format"], v24.CANDIDATE_FACT_SCHEMA)
        self.assertEqual(body["options"], {"num_ctx": 8192, "num_predict": 4096, "temperature": 0, "seed": 42})
        self.assertEqual(resident.call_count, 2)
        request.assert_called_once()

    @unittest.skip("legacy Qwen adapter removed")
    def test_preflight_rejects_digest_quantization_and_gpu_drift(self):
        config = self._config()
        model = {"name": "qwen3.5:4b", "digest": "sha256:" + "a" * 64,
                 "size": 100, "size_vram": 100, "context_length": 8192}
        for failure in (None, "bare_digest", "digest", "quantization", "gpu", "context"):
            with self.subTest(failure=failure):
                extractor = v24.GLiNER2SpanExtractor(config)
                tag, resident = dict(model), dict(model)
                if failure == "digest":
                    tag["digest"] = "sha256:" + "b" * 64
                if failure == "bare_digest":
                    tag["digest"] = resident["digest"] = "a" * 64
                if failure == "gpu":
                    resident["size_vram"] = 50
                if failure == "context":
                    resident["context_length"] = 2048
                responses = {"/api/version": {"version": "mock"}, "/api/tags": {"models": [tag]},
                             "/api/show": {"details": {"quantization_level": "Q8" if failure == "quantization" else "Q4_K_M"}},
                             "/api/generate": {"done": True}, "/api/ps": {"models": [resident]}}
                with patch.object(extractor, "_request", side_effect=lambda path, *a, **kw: responses[path]) as request:
                    if failure not in {None, "bare_digest"}:
                        with self.assertRaises(v24.CandidateExtractionError):
                            extractor.preflight()
                    else:
                        self.assertEqual(extractor.preflight()["device"], "gpu")
                    self.assertNotIn("/api/pull", [call.args[0] for call in request.call_args_list])

    @unittest.skip("legacy Qwen adapter removed")
    def test_chat_failure_rejects_entire_output_and_preserves_evidence(self):
        for failure in ("truncated", "unfinished", "thinking", "invalid_json", "model", "post_gpu"):
            with self.subTest(failure=failure):
                extractor = v24.GLiNER2SpanExtractor(self._config())
                extractor._identity = {"device": "gpu"}
                response = self._response([])
                if failure == "truncated":
                    response["done_reason"] = "length"
                elif failure == "unfinished":
                    response["done"] = False
                elif failure == "thinking":
                    response["message"]["thinking"] = "not allowed"
                elif failure == "invalid_json":
                    response["message"]["content"] = '{"facts":['
                elif failure == "model":
                    response["model"] = "luna"
                with patch.object(extractor, "_request", return_value=response) as request, patch.object(
                    extractor, "verify_resident", side_effect=[None, v24.CandidateExtractionError("gpu_drift")]
                    if failure == "post_gpu" else None
                ):
                    with self.assertRaises(v24.CandidateExtractionError) as caught:
                        extractor("The record identifies Alice as representative.")
                self.assertEqual(caught.exception.evidence["response"], response)
                request.assert_called_once()

    @unittest.skip("legacy Qwen adapter removed")
    def test_context_limit_stops_before_call_without_truncation(self):
        extractor = v24.GLiNER2SpanExtractor(self._config())
        extractor._identity = {"device": "gpu"}
        with patch.object(extractor, "_request", side_effect=AssertionError("no_request")):
            with self.assertRaisesRegex(v24.CandidateExtractionError, "context_limit"):
                extractor("x" * 12000)

    @unittest.skip("legacy Qwen adapter removed")
    def test_transport_timeout_retries_once_and_counts_physical_calls(self):
        for succeed in (True, False):
            with self.subTest(succeed=succeed):
                extractor = v24.GLiNER2SpanExtractor(self._config())
                opener = Mock()
                opener.open.side_effect = [TimeoutError(), io.BytesIO(b'{"ok":true}') if succeed else TimeoutError()]
                with patch.object(v24.urllib.request, "build_opener", return_value=opener), patch.object(v24.time, "sleep"):
                    if succeed:
                        self.assertEqual(extractor._request("/api/chat", {}, inference=True), {"ok": True})
                    else:
                        with self.assertRaisesRegex(v24.CandidateExtractionError, "transport_failed"):
                            extractor._request("/api/chat", {}, inference=True)
                self.assertEqual(extractor.stats(), {"http_attempts": 2, "inference_attempts": 2, "transport_retries": 1})
                self.assertEqual(opener.open.call_count, 2)

    @unittest.skip("legacy Qwen adapter removed")
    def test_invalid_http_json_and_redirect_do_not_retry(self):
        extractor = v24.GLiNER2SpanExtractor(self._config())
        opener = Mock()
        opener.open.return_value = io.BytesIO(b'{"broken":')
        with patch.object(v24.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(v24.CandidateExtractionError, "invalid_http_json"):
                extractor._request("/api/chat", {}, inference=True)
        self.assertEqual(extractor.inference_attempts, 1)
        self.assertEqual(extractor.transport_retries, 0)
        with self.assertRaisesRegex(v24.CandidateExtractionError, "redirect_forbidden"):
            v24._LocalOnlyRedirect().redirect_request(None, None, 302, "redirect", {}, "https://remote.example")

    def test_grounding_deduplicates_overlapping_chunks_and_sorts_global_slots(self):
        first = "The record identifies Alice as the designated representative."
        second = "The register lists Alice as the authorized officer."
        source = self._source(text=first + " " + second, chunks=[first + " " + second, second])
        extractor = self._extractor([[self._proposal(second, "Alice"), self._proposal(first, "Alice")],
                                     [self._proposal(second, "Alice")]])
        with patch.object(v24, "enumerate_candidate_facts", side_effect=AssertionError("no_regex")), patch.object(
            v24, "segment_propositions", side_effect=AssertionError("no_sentence_segmentation")
        ):
            record = v24.extract_source_candidate_facts(source, extractor)
        self.assertEqual(record["proposed_fact_count"], 3)
        self.assertEqual(record["candidate_fact_count"], 2)
        self.assertEqual(record["rejected_fact_count"], 1)
        self.assertEqual(record["rejection_reason_counts"], {"candidate_fact_duplicate_slot": 1})
        self.assertEqual([fact["true_claim"] for fact in record["facts"]], [first, second])
        self.assertEqual([fact["fact_order"] for fact in record["facts"]], [0, 1])
        for fact in record["facts"]:
            start, end = fact["original_span"]
            self.assertEqual(source["full_text"][start:end], "Alice")
            self.assertEqual(fact["slotted_true_claim"].count("{ENTITY}"), 1)
        extractor.assert_any_call(second)
        self.assertEqual(extractor.call_count, 2)

    def test_grounding_rejects_nonverbatim_fragments_mentions_and_ambiguous_offsets(self):
        cases = [
            ("The record identifies Alice as representative.", "The record appoints Alice as representative.", "Alice", "claim_not_unique"),
            ("The record identifies Alice as representative.", None, "Alic", "entity_boundary"),
            ("The record identifies Alice_Smith as representative.", None, "Alice", "entity_boundary"),
            ("Alice appointed Alice as representative.", None, "Alice", "entity_not_unique"),
            ("Citizens were unable to attend the Nov.", None, "Citizens", "incomplete_temporal"),
            ("Study The treatment improved survival.", None, "treatment", "heading_sentence_glue"),
            ("The paper identifies XYZ [12] as a marker.", None, "XYZ [12]", "entity_contains_citation"),
        ]
        for text, claim, entity, reason in cases:
            with self.subTest(reason=reason):
                record = v24.extract_source_candidate_facts(self._source(text=text),
                    self._extractor([[self._proposal(claim or text, entity)]]))
                self.assertEqual(record["candidate_fact_count"], 0)
                self.assertTrue(any(reason in key for key in record["rejection_reason_counts"]))
        claim = "The record identifies Alice as representative."
        for chunks, reason in [([claim], "chunk_offset_ambiguous"), ([claim + " " + claim], "claim_not_unique")]:
            record = v24.extract_source_candidate_facts(self._source(text=claim + " " + claim, chunks=chunks),
                self._extractor([[self._proposal(claim, "Alice")]]))
            self.assertEqual(record["facts"], [])
            self.assertTrue(any(reason in key for key in record["rejection_reason_counts"]))

    def test_structure_rejects_fragments_before_pool_acceptance(self):
        cases = [
            ("The funding (from Alice was approved.", "Alice", "unbalanced_delimiters"),
            ('The report calls Alice "the designated officer.', "Alice", "unbalanced_delimiters"),
            ("The report calls Alice 'the designated officer.", "Alice", "unbalanced_delimiters"),
            ("Alice was appointed,", "Alice", "trailing_fragment"),
            ("Alice was appointed;", "Alice", "trailing_fragment"),
            ("Alice was appointed:", "Alice", "trailing_fragment"),
            ("Alice was appointed-", "Alice", "trailing_fragment"),
            ("- changes in customer mix", "customer", "list_fragment"),
            ("Kay and Rusty:", "Kay and Rusty:", "entity_consumes_proposition"),
            ("alice@example.com", "alice@example.com", "entity_consumes_proposition"),
            ("They appointed Alice as director.", "They", "pronoun_entity"),
            ("Methods\nAlice performed the analysis.", "Alice", "heading_sentence_glue"),
        ]
        for claim, entity, reason in cases:
            with self.subTest(claim=claim):
                record = v24.extract_source_candidate_facts(self._source(text=claim),
                    self._extractor([[self._proposal(claim, entity)]]))
                self.assertEqual(record["facts"], [])
                self.assertEqual(record["status"], "completed")
                self.assertEqual(record["proposed_fact_count"], 1)
                self.assertEqual(record["rejected_fact_count"], 1)
                self.assertTrue(any(reason in key for key in record["rejection_reason_counts"]))

    def test_structure_rejects_sentence_like_original_entity_slots(self):
        cases = [
            ("The company is a market leader.", "company is a market leader"),
        ]
        for claim, entity in cases:
            with self.subTest(entity=entity):
                record = v24.extract_source_candidate_facts(
                    self._source(text=claim), self._extractor([[self._proposal(claim, entity)]])
                )
                self.assertEqual(record["facts"], [])
                self.assertIn("candidate_fact_entity_not_compact", record["rejection_reason_counts"])

    def test_gliner2_span_adapter_detects_multiple_entity_value_slots(self):
        claim = "Microsoft acquired GitHub for $7.5 billion in 2018."
        spans = [
            {"text": value, "label": label, "start": claim.index(value), "end": claim.index(value) + len(value)}
            for value, label in (("Microsoft", "ORG"), ("GitHub", "ORG"), ("$7.5 billion", "MONEY"), ("2018", "DATE"))
        ]
        backend = Mock()
        backend.predict.return_value = spans
        extractor = v24.GLiNER2SpanExtractor(load_v24_config(Path(__file__).resolve().parents[1]), backend=backend)
        extractor.preflight()
        record = v24.extract_source_candidate_facts(self._source(text=claim), extractor)
        self.assertEqual(record["candidate_fact_count"], 4, record["rejection_reason_counts"])
        self.assertEqual([f["original_entity"] for f in record["facts"]], ["GitHub", "$7.5 billion", "2018", "Microsoft"])
        self.assertEqual([f["fact_order"] for f in record["facts"]], [0, 1, 2, 3])
        self.assertEqual(backend.predict.call_count, 1)
        self.assertTrue(all("entity_label" in fact for fact in record["facts"]))

    def test_entity_ranking_prefers_specific_slots_without_using_label_as_truth(self):
        ace2 = v24._entity_quality_metadata("ACE2", "GENE")
        research = v24._entity_quality_metadata("research", "OTHER")
        self.assertLess(tuple(ace2["entity_rank_tuple"]), tuple(research["entity_rank_tuple"]))
        oldest = v24._entity_quality_metadata("oldest", "DATE")
        year = v24._entity_quality_metadata("2020", "DATE")
        self.assertGreater(tuple(oldest["entity_rank_tuple"]), tuple(year["entity_rank_tuple"]))

    def test_entity_ranking_downweights_generic_person_and_modifier_surfaces(self):
        named = v24._entity_quality_metadata("John Smith", "PERSON")
        for entity in ("patients", "Patients", "children", "participants", "young", "elderly"):
            generic = v24._entity_quality_metadata(entity, "PERSON")
            self.assertGreater(tuple(generic["entity_rank_tuple"]), tuple(named["entity_rank_tuple"]))
        for entity in ("physical", "observational", "ineffective", "recently"):
            with self.subTest(entity=entity):
                metadata = v24._entity_quality_metadata(entity, "OTHER")
                self.assertEqual(metadata["entity_quality_tier"], 2)
                self.assertIn("modifier_like_surface", metadata["entity_ranking_reasons"])

    def test_entity_ranking_keeps_other_domain_terms_but_marks_them_low(self):
        generic = v24._entity_quality_metadata("research", "OTHER")
        domain = v24._entity_quality_metadata("ACE2", "OTHER")
        self.assertGreater(tuple(generic["entity_rank_tuple"]), tuple(domain["entity_rank_tuple"]))
        self.assertTrue(set(generic["entity_ranking_reasons"]) & {"other_label_default_low_tier", "generic_noun_span"})

    def test_source_order_round_robins_claims_after_within_claim_ranking(self):
        rows = []
        for claim_start, claim, entities in (
            (0, "Claim A", [("generic", [0, 7]), ("ACE2", [8, 12])]),
            (20, "Claim B", [("2020", [20, 24]), ("research", [25, 33])]),
            (40, "Claim C", [("GitHub", [40, 46])]),
        ):
            for entity, span in entities:
                rows.append({"proposition_span": [claim_start, claim_start + len(claim)], "original_span": span,
                             "original_entity": entity, "true_claim": claim, "upstream_pair_id": f"{claim_start}-{entity}"})
        ordered = v24._order_candidates_claim_round_robin(rows)
        self.assertEqual([row["original_entity"] for row in ordered], ["ACE2", "2020", "GitHub", "generic", "research"])

    def test_source_order_prefers_unique_normalized_entities_without_deleting_duplicates(self):
        rows = []
        for start, entity in ((0, "SD"), (30, "SD"), (60, "antidepressants"), (90, "Cochrane"), (120, "SD")):
            claim = f"The report identifies {entity}."
            rows.append({"proposition_span": [start, start + len(claim)], "original_span": [start + 24, start + 24 + len(entity)],
                         "original_entity": entity, "true_claim": claim, "entity_label": "OTHER",
                         "upstream_pair_id": f"pair-{start}"})
        ordered = v24._order_candidates_claim_round_robin(rows)
        self.assertEqual(len(ordered), 5)
        self.assertEqual([row["original_entity"] for row in ordered[:4]], ["SD", "antidepressants", "Cochrane", "SD"])
        self.assertEqual(sum(row["original_entity"] == "SD" for row in ordered), 3)
        self.assertEqual(len({row["entity_normalized_key"] for row in ordered[:3]}), 3)

    def test_source_order_uses_duplicates_only_after_unique_entities_are_exhausted(self):
        rows = []
        for start, entity in enumerate(("A", "A", "B", "B")):
            claim = f"The record names {entity}."
            rows.append({"proposition_span": [start * 20, start * 20 + len(claim)],
                         "original_span": [start * 20 + 16, start * 20 + 17],
                         "original_entity": entity, "true_claim": claim, "entity_label": "OTHER",
                         "upstream_pair_id": f"fallback-{start}"})
        ordered = v24._order_candidates_claim_round_robin(rows)
        self.assertEqual(len(ordered), 4)
        self.assertEqual([row["original_entity"] for row in ordered], ["A", "B", "A", "B"])

    def test_bare_numeric_literals_are_lower_than_typed_values_but_remain_valid(self):
        typed = v24._entity_quality_metadata("181 patients", "NUMBER")
        bare = v24._entity_quality_metadata("181", "NUMBER")
        self.assertLess(tuple(typed["entity_rank_tuple"]), tuple(bare["entity_rank_tuple"]))
        self.assertIn("bare_numeric_literal", bare["entity_ranking_reasons"])
        self.assertNotIn("label_surface_mismatch", typed["entity_ranking_reasons"])

    def test_proposition_filter_rejects_question_and_publication_fragment(self):
        for text in ("Does treatment improve survival?", "Karger AG, Basel.", "gov NCT01010191"):
            with self.subTest(text=text):
                self.assertEqual(v24.segment_propositions(text), [])

    def test_obvious_adjective_fragments_are_hard_rejected_as_slots(self):
        for entity in ("physical", "observational", "ineffective", "oldest", "slightly greater"):
            claim = f"The study describes {entity}."
            record = v24.extract_source_candidate_facts(
                self._source(text=claim), self._extractor([[self._proposal(claim, entity)]])
            )
            with self.subTest(entity=entity):
                self.assertEqual(record["facts"], [])
                self.assertIn("candidate_fact_adjective_fragment", record["rejection_reason_counts"])

    def test_candidate_pool_keeps_complete_count_separate_from_processing_order(self):
        claim = "ACE2 binds research targets in 2020."
        spans = [
            {"text": value, "label": label, "start": claim.index(value), "end": claim.index(value) + len(value)}
            for value, label in (("ACE2", "GENE"), ("research", "OTHER"), ("2020", "DATE"))
        ]
        backend = Mock()
        backend.predict.return_value = spans
        extractor = v24.GLiNER2SpanExtractor(load_v24_config(Path(__file__).resolve().parents[1]), backend=backend)
        extractor.preflight()
        record = v24.extract_source_candidate_facts(self._source(text=claim), extractor)
        self.assertEqual(record["candidate_fact_count"], 3)
        self.assertEqual([f["original_entity"] for f in record["facts"]], ["ACE2", "2020", "research"])
        self.assertEqual(len(record["facts"]), record["candidate_fact_count"])
        self.assertEqual(record["candidate_processing_order"], [f["upstream_pair_id"] for f in record["facts"]])
        self.assertEqual([f["entity_rank_within_claim"] for f in record["facts"]], [0, 1, 2])

    def test_entity_ranking_rejects_attack_signals_even_in_nested_input(self):
        fact = {**_fact("ACE2 binds the receptor.", "ACE2"), "proposition_span": [0, 24]}
        forbidden = ("membership", "membership_label", "Retriever", "retriever_output", "victim", "victim_response",
                     "PVS", "AUC", "Luna", "luna_output", "replacement_entity")
        for key in forbidden:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "forbidden_input_field"):
                v24._order_candidates_claim_round_robin([{**fact, "diagnostic": {key: "unseen"}}])
        self.assertNotIn("dataset", v24._entity_quality_metadata("ACE2", "GENE"))

    def test_label_surface_support_is_required_for_values_and_names(self):
        for entity, label in (("oldest", "DATE"), ("resources", "MONEY"), ("support vectors", "NUMBER"), ("recent", "DATE")):
            with self.subTest(entity=entity):
                meta = v24._entity_quality_metadata(entity, label)
                self.assertEqual(meta["entity_quality_tier"], 2)
                self.assertIn("label_surface_mismatch", meta["entity_ranking_reasons"])
        for entity in ("181 patients", "$7.5 billion", "30%", "40 mg/kg", "June 2011", "one or two", "five or more times", "700-800 million years"):
            with self.subTest(value=entity):
                self.assertEqual(v24._entity_quality_metadata(entity, "OTHER")["entity_quality_tier"], 0)
        for entity in ("181", "0.02", "Three"):
            with self.subTest(value=entity):
                self.assertEqual(v24._entity_quality_metadata(entity, "OTHER")["entity_quality_tier"], 1)
        for entity in ("irritable bowel syndrome", "support vector algorithms", "rifaximin", "acetylsalicylic acid"):
            label = "DRUG" if entity == "rifaximin" else "OTHER"
            self.assertEqual(v24._entity_quality_metadata(entity, label)["entity_quality_tier"], 1)

    def _multi_claim_ranking_fixture(self):
        claims = [f"The registry lists {', '.join(f'{letter}{i}' for i in range(count))} as approved codes."
                  for letter, count in (("A", 6), ("B", 3), ("C", 3))]
        proposals = [self._proposal(claim, f"{letter}{i}") for claim, letter, count in zip(claims, "ABC", (6, 3, 3)) for i in range(count)]
        source = self._source(text=" ".join(claims))
        return source, proposals

    def test_ranking_first_eight_covers_claims_and_never_refills_after_failure(self):
        source, proposals = self._multi_claim_ranking_fixture()
        record = v24.extract_source_candidate_facts(source, self._extractor([proposals]))
        entities = [f["original_entity"] for f in record["facts"]]
        self.assertEqual(entities, ["A0", "B0", "C0", "A1", "B1", "C1", "A2", "B2", "C2", "A3", "A4", "A5"])
        provider = Mock(return_value=[])
        result = screen_source(source, facts=record["facts"], candidate_provider=provider,
                               similarity_fn=_semantic_similarity, semantic_correction_retries=0)
        self.assertEqual([call.args[0]["original_entity"] for call in provider.call_args_list], entities[:8])
        self.assertEqual(result["candidate_fact_count"], 12)
        self.assertEqual(result["processed_fact_count"], 8)
        self.assertEqual(result["unprocessed_fact_count"], 4)
        self.assertEqual(len(record["candidate_processing_order"]), 12)

    def test_ranking_rerun_and_detection_permutation_have_identical_fact_order(self):
        source, proposals = self._multi_claim_ranking_fixture()
        first = v24.extract_source_candidate_facts(source, self._extractor([proposals]))
        second = v24.extract_source_candidate_facts(source, self._extractor([proposals]))
        permuted = v24.extract_source_candidate_facts(source, self._extractor([list(reversed(proposals))]))
        self.assertEqual(sha256_obj(first), sha256_obj(second))
        self.assertEqual(first["facts"], permuted["facts"])
        self.assertEqual(first["candidate_processing_order"], permuted["candidate_processing_order"])

    def test_domain_claim_coverage_precedes_second_named_slot_and_generic_claim(self):
        rows = []
        for offset, entities in ((0, ["A0", "A1", "A2"]), (100, ["nicotinic acid", "sodium chloride"]),
                                 (200, ["research"])):
            for i, entity in enumerate(entities):
                rows.append({"true_claim": f"The record describes {entity}.", "original_entity": entity,
                             "entity_label": "OTHER", "proposition_span": [offset, offset + 80],
                             "original_span": [offset + i * 20, offset + i * 20 + len(entity)], "upstream_pair_id": entity})
        ordered = v24._order_candidates_claim_round_robin(rows)
        self.assertEqual([f["original_entity"] for f in ordered],
                         ["A0", "nicotinic acid", "A1", "sodium chloride", "A2", "research"])

    def test_pool_reader_reuses_configured_preferred_length_and_rejects_old_policy(self):
        claim = "The registry names the National Institute for Advanced Biomedical Research and Clinical Translation as sponsor."
        entity = "National Institute for Advanced Biomedical Research and Clinical Translation"
        source = self._source(text=claim)
        config = self._config()
        config["candidate_fact_adapter"]["entity_span"]["preferred_max_words"] = 8
        extractor = self._extractor([[self._proposal(claim, entity)]])
        extractor.adapter = config["candidate_fact_adapter"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._build(root, [source], extractor, config=config)
            path = root / "artifacts/v24/candidate_fact_pools/nfcorpus/pool_manifest.json"
            reader = v24.CandidateFactPoolReader(path, config=config)
            self.assertEqual(reader.facts_for_source(source)[0]["entity_rank_tuple"][-1], 1)
            manifest = read_json(path)
            del manifest["adapter"]["config"]["entity_ranking"]
            v24._candidate_pool_seal(manifest, path)
            with self.assertRaisesRegex(ValueError, "entity_ranking_config_invalid"):
                v24.CandidateFactPoolReader(path)

    def test_ranking_validator_rejects_reordered_or_relabelled_pool(self):
        source, proposals = self._multi_claim_ranking_fixture()
        record = v24.extract_source_candidate_facts(source, self._extractor([proposals]))
        v24._validate_candidate_pool_record(record, "nfcorpus")
        for field in ("entity_rank_tuple", "entity_rank_within_claim", "entity_ranking_reasons", "candidate_processing_order"):
            tampered = copy.deepcopy(record)
            if field == "candidate_processing_order":
                tampered[field].reverse()
            else:
                tampered["facts"][0][field] = -1
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "(processing_order|entity_ranking)_drift"):
                v24._validate_candidate_pool_record(tampered, "nfcorpus")
        tampered = copy.deepcopy(record)
        tampered["facts"].reverse()
        for i, fact in enumerate(tampered["facts"]):
            fact["fact_order"] = i
        tampered["candidate_processing_order"] = [f["upstream_pair_id"] for f in tampered["facts"]]
        with self.assertRaisesRegex(ValueError, "entity_ranking_drift"):
            v24._validate_candidate_pool_record(tampered, "nfcorpus")

    def test_ranking_diagnostics_do_not_enter_luna_prompt(self):
        fact = _fact("Microsoft acquired GitHub.", "GitHub")
        fact["slotted_true_claim"] = "Microsoft acquired {ENTITY}."
        diagnostic = {"entity_label": "private_label", "entity_quality_tier": 2,
                      "entity_rank_tuple": [2, 1, 1, 0], "entity_ranking_reasons": ["private_reason"],
                      "entity_rank_within_claim": 3}
        self.assertEqual(build_candidate_prompt(fact), build_candidate_prompt({**fact, **diagnostic}))
        self.assertEqual(build_correction_prompt(fact, []), build_correction_prompt({**fact, **diagnostic}, []))

    def test_ranked_pool_identity_invalidates_old_ordering_without_model_calls(self):
        config = self._config()
        del config["candidate_fact_adapter"]["entity_ranking"]
        with self.assertRaisesRegex(ValueError, "entity_ranking_config_invalid"):
            v24.candidate_adapter_identity(config)

    def test_proposition_questions_and_section_glue_never_reach_detector(self):
        for claim in ("Does this treatment reduce mortality?", "OBJECTIVE Celecoxib reduces pain.",
                      "Background Placebo treatment improved symptoms."):
            backend = Mock(side_effect=AssertionError("invalid_proposition_must_not_reach_detector"))
            extractor = v24.GLiNER2SpanExtractor(self._config(), backend=backend)
            extractor.preflight()
            record = v24.extract_source_candidate_facts(self._source(text=claim), extractor)
            with self.subTest(claim=claim):
                self.assertEqual(record["facts"], [])
                backend.predict.assert_not_called()
                self.assertTrue(record["proposition_rejection_counts"])
        for claim in ("ACE2 binds research targets in 2020.", "Background noise increased.", "Results were consistent."):
            self.assertEqual(v24.segment_propositions(claim), [{"text": claim, "start": 0, "end": len(claim)}])

    def test_structural_slot_rejections_do_not_use_broad_adjective_suffixes(self):
        for original in ("chemical", "nicotinic acid", "one or two", "Complementary and alternative medicines"):
            claim = f"The report identifies {original} as a term."
            self.assertEqual(v24._entity_slot_rejection_reasons(claim, original), [])
        for claim, entity in (("The observational study measured mortality.", "observational"),
                              ("The physical measure was recorded.", "physical"),
                              ("The treatment was slightly greater than control.", "slightly greater"),
                              ("Alice and Bob signed the report.", "Alice and Bob")):
            self.assertTrue(v24._entity_slot_rejection_reasons(claim, entity))
        collective = "Complementary and alternative medicines"
        meta = v24._entity_quality_metadata(collective, "DRUG", claim=f"{collective} (CAM) improved symptoms.")
        self.assertEqual(meta["entity_quality_tier"], 1)
        meta = v24._entity_quality_metadata("functioning and quality of life", "OTHER")
        self.assertEqual(meta["entity_quality_tier"], 2)

    def test_gliner2_allows_long_domain_entity_but_rejects_over_hard_limit(self):
        claim = "The study measured Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda levels."
        long_entity = "Alpha beta gamma delta epsilon zeta eta theta iota"
        backend = Mock()
        backend.predict.return_value = [{"text": long_entity, "label": "PATHWAY", "start": claim.index(long_entity), "end": claim.index(long_entity) + len(long_entity)}]
        extractor = v24.GLiNER2SpanExtractor(load_v24_config(Path(__file__).resolve().parents[1]), backend=backend)
        extractor.preflight()
        accepted = v24.extract_source_candidate_facts(self._source(text=claim), extractor)
        self.assertEqual(accepted["candidate_fact_count"], 1)
        self.assertEqual(accepted["facts"][0]["entity_word_count"], 9)
        too_long = "one two three four five six seven eight nine ten eleven twelve thirteen"
        rejected = v24.extract_source_candidate_facts(
            self._source(text=f"The report lists {too_long} as a term."),
            self._extractor([[self._proposal(f"The report lists {too_long} as a term.", too_long)]])
        )
        self.assertTrue(any("not_compact" in key for key in rejected["rejection_reason_counts"]))

    def test_proposition_segmentation_filters_obvious_non_factual_structures(self):
        cases = {
            "Heading\n": "heading",
            "By Carla Drysdale, columnist.": "byline",
            "Subject: Quarterly update.": "header",
            "TIE_POINT: FCORNR_5_PSUEDO.": "key_value",
            "See \"Part I-Item 1\".": "cross_reference",
            "Please send the report.": "imperative",
            "Alice was appointed,": "incomplete",
        }
        for text, reason in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(v24.segment_propositions(text), [])
                counts = v24.proposition_rejection_counts(text)
                self.assertTrue(any(reason in key for key in counts), counts)

    def test_production_adapter_is_gliner2_detection_only(self):
        config = load_v24_config(Path(__file__).resolve().parents[1])
        identity = v24.candidate_adapter_identity(config)
        self.assertEqual(identity["config"]["kind"], "gliner2_entity_value_span")
        self.assertEqual(identity["config"]["backend"], "gliner2")
        self.assertEqual(identity["config"]["entity_span"], {"preferred_max_words": 6, "hard_max_words": 12})
        self.assertNotIn("replaceability_score", identity["config"])
        self.assertNotIn("counterfactual_suitability", identity["config"])

    def test_structure_uses_source_edges_instead_of_chunk_or_regex_sentences(self):
        cases = [
            ("In 2020, Alice signed the contract.", "Alice signed the contract.", "starts_inside_sentence"),
            ("Alice signed the contract only after approval.", "Alice signed the contract", "ends_inside_sentence"),
        ]
        for text, claim, reason in cases:
            with self.subTest(reason=reason), patch.object(v24, "segment_propositions", side_effect=AssertionError("no_regex")):
                record = v24.extract_source_candidate_facts(self._source(text=text, chunks=[claim]),
                    self._extractor([[self._proposal(claim, "Alice")]]))
                self.assertEqual(record["facts"], [])
                self.assertTrue(any(reason in key for key in record["rejection_reason_counts"]))

    def test_structure_preserves_apostrophes_units_quotes_and_lowercase_subjects(self):
        cases = [
            ("O'Connor signed the contract.", "O'Connor"),
            ("The directors' report identifies Alice as representative.", "Alice"),
            ('The report calls Alice "the designated officer".', "Alice"),
            ("The report calls Alice 'the designated officer'.", "Alice"),
            ('The board measured 12" in width.', '12"'),
            ("Alice's fee (including tax) was $50.", "$50"),
            ("eBay acquired the company in 2020.", "2020"),
            ("p53 regulates cell growth.", "p53"),
        ]
        for claim, entity in cases:
            with self.subTest(claim=claim):
                record = v24.extract_source_candidate_facts(self._source(text=claim),
                    self._extractor([[self._proposal(claim, entity)]]))
                self.assertEqual(record["candidate_fact_count"], 1, record["rejection_reason_counts"])
                self.assertEqual(record["facts"][0]["true_claim"], claim)

    @unittest.skip("legacy Qwen adapter removed")
    def test_context_precheck_reserves_all_4096_output_tokens(self):
        extractor = v24.OllamaFactExtractor(self._config())
        extractor._identity = {"device": "gpu"}
        messages = [{"role": "system", "content": v24.CANDIDATE_FACT_PROMPT}, {"role": "user", "content": ""}]
        overhead = len(json.dumps({"messages": messages, "format": v24.CANDIDATE_FACT_SCHEMA}, ensure_ascii=False).encode("utf-8")) + 256
        fitting = "x" * (8192 - 4096 - overhead)
        with patch.object(extractor, "verify_resident"), patch.object(extractor, "_request", return_value=self._response([])) as request:
            extractor(fitting)
            with self.assertRaisesRegex(v24.CandidateExtractionError, "context_limit"):
                extractor(fitting + "x")
            request.assert_called_once()

    def test_pool_hash_is_stable_and_downstream_config_does_not_invalidate_extraction(self):
        sources = [self._source(0), self._source(1)]
        effects = [[self._proposal(sources[0]["full_text"], "Person0")], []]
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = self._build(Path(first), sources, self._extractor(effects))
            two = self._build(Path(second), sources, self._extractor(effects))
            self.assertEqual(one["records_sha256"], two["records_sha256"])
            self.assertEqual(one["pool_sha256"], two["pool_sha256"])
            self.assertEqual(one["completed_source_count"], 2)
            config = self._config()
            config["llm"]["max_tokens"] += 10
            path = Path(first) / "artifacts/v24/candidate_fact_pools/nfcorpus/pool_manifest.json"
            with patch.object(v24, "GLiNER2SpanExtractor", side_effect=AssertionError("no_inference_on_read")):
                reader = v24.CandidateFactPoolReader(path, config=config, require_formal=True)
                self.assertEqual(reader.facts_for_source(sources[1]), [])
                self.assertEqual(len(reader.facts_for_source(sources[0])), 1)
            with self.assertRaisesRegex(ValueError, "exists_use_resume"):
                self._build(Path(first), sources, self._extractor(effects))

    def test_incomplete_pool_retains_failures_and_resumes_completed_sources_only(self):
        sources = [self._source(0), self._source(1)]
        for failure in (v24.CandidateExtractionError("v24_candidate_transport_failed"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with self.assertRaises(type(failure)):
                    self._build(root, sources, self._extractor([[], failure]))
                path = root / "artifacts/v24/candidate_fact_pools/nfcorpus/pool_manifest.json"
                manifest = read_json(path)
                self.assertEqual(manifest["completed_source_count"], 1)
                self.assertEqual(len(manifest["failures"]), 1)
                self.assertEqual(manifest["failures"][0]["source"]["source_key"], "s1")
                with self.assertRaisesRegex(ValueError, "not_completed"):
                    v24.CandidateFactPoolReader(path)
                remaining = self._extractor([[]])
                completed = self._build(root, sources, remaining, resume=True)
                remaining.assert_called_once_with(sources[1]["full_text"])
                self.assertEqual(completed["usage"]["inference_attempts"], 3)
                self.assertEqual(len(completed["failures"]), 1)
                no_calls = self._extractor([])
                cached = self._build(root, sources, no_calls, resume=True)
                no_calls.preflight.assert_not_called()
                self.assertEqual(completed["pool_sha256"], cached["pool_sha256"])

    def test_interrupted_chunk_evidence_survives_without_partial_source_acceptance(self):
        source = self._source(text="First text. Second text.", chunks=["First text.", "Second text."])
        with self.assertRaises(KeyboardInterrupt) as caught:
            v24.extract_source_candidate_facts(source, self._extractor([[], KeyboardInterrupt()]))
        self.assertEqual(len(caught.exception.evidence["completed_chunks"]), 1)

    def test_pool_rejects_drift_missing_sources_partial_records_and_grounding_changes(self):
        source = self._source()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._build(root, [source], self._extractor([[self._proposal(source["full_text"], "Person0")]]))
            path = root / "artifacts/v24/candidate_fact_pools/nfcorpus/pool_manifest.json"
            reader = v24.CandidateFactPoolReader(path, config=self._config())
            with self.assertRaisesRegex(ValueError, "source_missing"):
                reader.record("absent")
            changed = copy.deepcopy(source)
            changed["full_text"] += " drift"
            with self.assertRaisesRegex(ValueError, "source_drift"):
                reader.facts_for_source(changed)
            row = reader.record("s0")
            row["facts"][0]["original_span"][0] += 1
            write_jsonl([row], reader.records_path)
            with self.assertRaisesRegex(ValueError, "record_drift"):
                reader.record("s0")
            with self.assertRaisesRegex(ValueError, "records_hash"):
                v24.CandidateFactPoolReader(path)
            manifest = read_json(path)
            manifest["records_sha256"] = sha256_file(reader.records_path)
            v24._candidate_pool_seal(manifest, path)
            changed_reader = v24.CandidateFactPoolReader(path)
            with patch.object(v24, "iter_frozen_source_pool", return_value=iter([source])):
                with self.assertRaisesRegex(ValueError, "grounding_drift"):
                    changed_reader.validate_sources(root)
            with reader.records_path.open("ab") as stream:
                stream.write(b'{"unfinished":')
            manifest["records_sha256"] = sha256_file(reader.records_path)
            v24._candidate_pool_seal(manifest, path)
            with self.assertRaisesRegex(ValueError, "partial_record"):
                v24.CandidateFactPoolReader(path)

    def test_development_scope_and_identity_hash_exclusion(self):
        sources = [self._source(0), self._source(1), self._source(2)]
        sources[1] = self._source(1, text=sources[0]["full_text"])
        exclusions = [v24._source_identity(sources[0])]
        exclusions[0].pop("source_order_rank")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(v24, "collect_development_identities", return_value=exclusions):
                pool = self._build(root, sources, self._extractor([[]]))
            self.assertEqual(pool["excluded_source_count"], 2)
            self.assertEqual(pool["completed_source_count"], 1)
            path = root / "artifacts/v24/candidate_fact_pools/nfcorpus/pool_manifest.json"
            self.assertEqual(list(v24.CandidateFactPoolReader(path).offsets), ["s2"])
            output = "artifacts/v24/development/extraction/nfcorpus"
            self._build(root, sources, self._extractor([[]]), output=output, sample=1)
            with self.assertRaisesRegex(ValueError, "development_not_formal"):
                v24.CandidateFactPoolReader(root / output / "pool_manifest.json", require_formal=True)

    def test_development_projection_uses_only_identities_and_recovers_legacy_prefix(self):
        config = self._config()
        config["candidate_fact_adapter"].update({
            "development_identity_patterns": ["artifacts/v24/development/**/*.jsonl"],
            "legacy_development_prefix_manifests": ["artifacts/v24/development/capacity_check_r1/{dataset}.json"],
        })
        sources = [self._source(0), self._source(1)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_jsonl([{"dataset": "nfcorpus", "source_key": "s1", "membership": 1, "auc": 0.9,
                          "counterfactual_entity": "ignored"}], root / "artifacts/v24/development/old/inputs.jsonl")
            write_json({"dataset": "nfcorpus", "mode": "offline_fact_capacity_estimate", "candidate_source_count": 1},
                       root / "artifacts/v24/development/capacity_check_r1/nfcorpus.json")
            with patch.object(v24, "iter_frozen_source_pool", return_value=iter(sources)) as read_sources:
                rows = v24.collect_development_identities(root, config, "nfcorpus")
            self.assertEqual(read_sources.call_args.kwargs, {"source_keys": {"s1"}, "first_sources": 1})
            self.assertEqual({row["source_key"] for row in rows}, {"s0", "s1"})
            self.assertTrue(all(set(row) <= {"dataset", "source_key", "source_hash", "normalized_text_hash"} for row in rows))
            self.assertTrue(any(row.get("source_hash") == sha256_text(sources[0]["full_text"]) for row in rows))

    def test_capacity_and_frozen_scanner_share_pool_keep_zero_denominator_and_eight_budget(self):
        runner = _load_v24_capacity_runner()
        claims = [f"The record identifies Person{i} as the designated representative." for i in range(10)]
        sources = [self._source(0, text="No supported candidate."), self._source(1, text=" ".join(claims))]
        proposals = [self._proposal(claim, f"Person{i}") for i, claim in enumerate(claims)]
        config = self._config()
        config["eligibility"]["target_sources"] = 1
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._build(root, sources, self._extractor([[], proposals]), config=config)
            path = root / "artifacts/v24/candidate_fact_pools/nfcorpus/pool_manifest.json"
            with ExitStack() as stack:
                for module in (v24, runner):
                    stack.enter_context(patch.object(module, "load_v24_config", return_value=config))
                    stack.enter_context(patch.object(module, "source_pool_bindings", return_value={"nfcorpus": {"source_count": 2}}))
                    stack.enter_context(patch.object(module, "iter_frozen_source_pool", side_effect=lambda *a, **kw: iter(sources)))
                    stack.enter_context(patch.object(module, "enumerate_candidate_facts", side_effect=AssertionError("no_legacy_extraction")))
                stack.enter_context(patch.object(v24, "GLiNER2SpanExtractor", side_effect=AssertionError("no_model_on_read")))
                stack.enter_context(patch.object(runner, "build_luna_candidate_provider", side_effect=AssertionError("offline_capacity")))
                capacity = runner.run_capacity_check(root, dataset="nfcorpus", sample_sources=2, use_luna=False,
                    candidate_pools=[path], output_dir="artifacts/v24/development/capacity", show_progress=False)
                self.assertEqual(capacity["candidate_source_count"], 2)
                self.assertEqual(capacity["candidate_fact_count"], 10)
                self.assertEqual(capacity["raw_fact_budget_feasible_source_rate"], 0.5)
                calls = []

                def provider(fact):
                    calls.append(fact["fact_order"])
                    return [_selection_package(fact, fact["fact_order"])] if fact["fact_order"] in {0, 1, 8} else []

                scan = v24.scan_frozen_source_pool(root, "nfcorpus", candidate_pool=path, candidate_provider=provider,
                    target_sources=1, similarity_fn=_semantic_similarity, semantic_correction_retries=0)
                self.assertEqual(scan["screened_source_count"], 2)
                self.assertEqual(scan["candidate_fact_count"], 10)
                self.assertEqual(scan["processed_fact_count"], 8)
                self.assertEqual(scan["unprocessed_fact_count"], 2)
                self.assertEqual(calls, list(range(8)))
                self.assertEqual(scan["status"], "insufficient_eligible_capacity")
                self.assertEqual(scan["candidate_fact_pool"], capacity["candidate_fact_pool"])
                accepted = v24.scan_frozen_source_pool(root, "nfcorpus", candidate_pool=path,
                    candidate_provider=lambda fact: [_selection_package(fact, fact["fact_order"])],
                    target_sources=1, similarity_fn=_semantic_similarity)
                self.assertEqual(accepted["processed_fact_count"], 3)
                self.assertEqual(accepted["eligible_source_rate"], 0.5)
                manifest = v24.build_eligibility_manifest(accepted, dataset="nfcorpus", config=config, source_pool={"source_count": 2})
                v24.validate_eligibility_manifest(manifest, expected_source_count=1)
                self.assertEqual(v24.build_query_manifest(manifest)["query_count"], 6)
                self.assertEqual(manifest["candidate_fact_pool"], capacity["candidate_fact_pool"])
                accepted.pop("candidate_fact_pool")
                with self.assertRaisesRegex(ValueError, "candidate_pool_required"):
                    v24.build_eligibility_manifest(accepted, dataset="nfcorpus", config=config, source_pool={"source_count": 2})
                pool_manifest = read_json(path)
                pool_manifest["code_version"]["git_commit"] = "other_mock_commit"
                v24._candidate_pool_seal(pool_manifest, path)
                with self.assertRaisesRegex(RuntimeError, "summary_identity_drift"):
                    runner.run_capacity_check(root, dataset="nfcorpus", sample_sources=2, use_luna=False,
                        candidate_pools=[path], output_dir="artifacts/v24/development/capacity", resume=True, show_progress=False)

    def test_canary_uses_bound_pool_fact_and_rejects_tampering_before_provider(self):
        runner = _load_v24_capacity_runner()
        config = self._config()
        config["development"]["canary_pair_count"] = 3
        sources = {dataset: [self._source(0, dataset=dataset)] for dataset in v24.DATASET_ORDER}
        bindings = {dataset: {"source_count": 1} for dataset in sources}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = []
            for dataset in v24.DATASET_ORDER:
                with patch.object(v24, "load_v24_config", return_value=config), patch.object(
                    v24, "source_pool_bindings", return_value=bindings
                ), patch.object(v24, "iter_frozen_source_pool", side_effect=lambda _root, ds, **kw: iter(sources[ds])), patch.object(
                    v24, "GLiNER2SpanExtractor", return_value=self._extractor([[self._proposal(sources[dataset][0]["full_text"], "Person0")]])
                ), patch.object(v24, "_candidate_pool_code_version", return_value={"git_commit": "mock"}):
                    v24.build_candidate_fact_pool(root, dataset=dataset, sample_sources=1,
                        output_dir=f"artifacts/v24/development/pool/{dataset}")
                paths.append(root / f"artifacts/v24/development/pool/{dataset}/pool_manifest.json")
            with ExitStack() as stack:
                for module in (runner, v24):
                    stack.enter_context(patch.object(module, "load_v24_config", return_value=config))
                    stack.enter_context(patch.object(module, "source_pool_bindings", return_value=bindings))
                    stack.enter_context(patch.object(module, "iter_frozen_source_pool", side_effect=lambda _root, ds, **kw: iter(sources[ds])))
                    stack.enter_context(patch.object(module, "enumerate_candidate_facts", side_effect=AssertionError("no_regex")))
                stack.enter_context(patch.object(v24, "GLiNER2SpanExtractor", side_effect=AssertionError("no_extractor")))
                fixture = runner.prepare_fresh_canary(root, per_dataset=1,
                    candidate_pools=paths, output_dir="artifacts/v24/development/fresh")
                self.assertEqual(fixture["input_count"], 3)
                self.assertEqual(len(fixture["candidate_fact_pools"]), 3)
                provider = Mock(side_effect=lambda fact: [_selection_package(fact, fact["fact_order"])])
                provider.physical_attempts = 3
                provider.stats.return_value = {"physical_attempts": 3}
                scorer = Mock(side_effect=_semantic_similarity)
                scorer.identity.return_value = {"kind": "mock"}
                with patch.object(runner, "build_luna_candidate_provider", return_value=provider), patch.object(
                    runner, "build_v24_semantic_similarity", return_value=scorer
                ):
                    result = runner.run_canary(root, input_path=fixture["inputs_path"], candidate_pools=paths,
                        output_dir="artifacts/v24/development/canary")
                self.assertEqual(result["passed_pair_count"], 3)
                self.assertEqual(provider.call_count, 3)
                self.assertEqual({call.args[0]["dataset"] for call in provider.call_args_list}, set(v24.DATASET_ORDER))
                inputs = list(read_jsonl(root / fixture["inputs_path"]))
                inputs[0]["true_claim"] = "This claim did not come from the pool."
                write_jsonl(inputs, root / "tampered.jsonl")
                with patch.object(runner, "build_luna_candidate_provider", side_effect=AssertionError("no_Luna_before_validation")):
                    with self.assertRaisesRegex(ValueError, "fact_not_in_candidate_pool"):
                        runner.run_canary(root, input_path="tampered.jsonl", candidate_pools=paths,
                            output_dir="artifacts/v24/development/tampered")

    def test_canary_replaces_zero_sources_in_frozen_order_and_preserves_evidence(self):
        runner = _load_v24_capacity_runner()
        config = self._config()
        config["development"]["canary_pair_count"] = 6
        sources = {ds: [self._source(i, dataset=ds) for i in range(5)] for ds in v24.DATASET_ORDER}
        bindings = {ds: {"source_count": 5} for ds in sources}
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            root = Path(temp)
            for module in (runner, v24):
                stack.enter_context(patch.object(module, "load_v24_config", return_value=config))
                stack.enter_context(patch.object(module, "source_pool_bindings", return_value=bindings))
                stack.enter_context(patch.object(module, "iter_frozen_source_pool", side_effect=lambda _root, ds, **kw: iter(
                    s for s in sources[ds] if not kw.get("source_keys") or s["source_key"] in kw["source_keys"]
                )))
                stack.enter_context(patch.object(module, "enumerate_candidate_facts", side_effect=AssertionError("no_regex")))
            stack.enter_context(patch.object(v24, "_candidate_pool_code_version", return_value={"git_commit": "mock"}))
            paths = []
            primary_paths = []
            for ds in v24.DATASET_ORDER:
                for name, subset in (("primary", sources[ds][:2]), ("supplement", sources[ds][2:])):
                    effects = [[] if s["source_key"] in {"s0", "s2"} else [self._proposal(
                        s["full_text"], f"Person{s['source_order_rank']}",
                    )] for s in subset]
                    output = f"artifacts/v24/development/{name}/{ds}"
                    with patch.object(v24, "GLiNER2SpanExtractor", return_value=self._extractor(effects)):
                        v24.build_candidate_fact_pool(root, dataset=ds, output_dir=output, sample_sources=len(subset),
                            fixed_source_identities=[v24._source_identity(s) for s in subset])
                    paths.append(root / output / "pool_manifest.json")
                    if name == "primary":
                        primary_paths.append(paths[-1])
            protected = {p: sha256_file(p) for path in paths for p in (path, path.parent / "source_records.jsonl")}
            stack.enter_context(patch.object(v24, "GLiNER2SpanExtractor", side_effect=AssertionError("no_extractor")))
            with self.assertRaisesRegex(RuntimeError, "source_shortfall"):
                runner.prepare_fresh_canary(root, per_dataset=2, candidate_pools=primary_paths,
                    output_dir="artifacts/v24/development/shortfall")
            shortage = read_json(root / "artifacts/v24/development/shortfall/preflight_summary.json")
            self.assertEqual(shortage["status"], "insufficient_candidate_sources")
            self.assertEqual(shortage["source_shortfalls"], dict.fromkeys(v24.DATASET_ORDER, 1))
            self.assertEqual(shortage["zero_candidate_source_count"], 3)
            self.assertIsNone(shortage["inputs_path"])
            self.assertFalse((root / "artifacts/v24/development/shortfall/canary_inputs.jsonl").exists())
            fixture = runner.prepare_fresh_canary(root, per_dataset=2, candidate_pools=list(reversed(paths)),
                output_dir="artifacts/v24/development/fresh_supplemented")
            self.assertEqual(fixture["screened_source_count"], 12)
            self.assertEqual(fixture["zero_candidate_source_count"], 6)
            self.assertEqual(fixture["input_count"], 6)
            self.assertEqual(fixture["external_calls_performed"], 0)
            inputs = list(read_jsonl(root / fixture["inputs_path"]))
            self.assertEqual([(r["dataset"], r["source_key"]) for r in inputs],
                [(ds, key) for ds in v24.DATASET_ORDER for key in ("s1", "s3")])
            self.assertTrue(all(r["fact_order"] == 0 for r in inputs))
            decisions = list(read_jsonl(root / fixture["preflight_results_path"]))
            for ds in v24.DATASET_ORDER:
                self.assertEqual(fixture["dataset_counts"][ds]["replacement_source_count"], 1)
                skipped = [r for r in decisions if r["dataset"] == ds and r["status"] == "skipped_zero_candidates"]
                self.assertEqual([r["source_key"] for r in skipped], ["s0", "s2"])
                self.assertTrue(all(r["source_hash"] and r["normalized_text_hash"] for r in skipped))
            # 仅从 preflight 证据也能排除原零候选与新补入身份。
            exclusion_config = copy.deepcopy(config)
            exclusion_config["candidate_fact_adapter"]["development_identity_patterns"] = [
                "artifacts/v24/development/**/preflight_results.jsonl",
            ]
            for ds in v24.DATASET_ORDER:
                exclusions = v24.collect_development_identities(root, exclusion_config, ds)
                remaining = [s["source_key"] for s in sources[ds]
                             if not v24._development_excluded(v24._source_identity(s), exclusions)]
                self.assertEqual(remaining, ["s4"])
            with patch.object(runner, "_historical_canary_sources", return_value=set()):
                repeated = runner.prepare_fresh_canary(root, per_dataset=2, candidate_pools=paths,
                    output_dir="artifacts/v24/development/same_order")
                self.assertEqual(fixture["input_sha256"], repeated["input_sha256"])
            provider = Mock(side_effect=lambda fact: [_selection_package(fact, fact["fact_order"])])
            provider.physical_attempts = 6
            provider.stats.return_value = {"physical_attempts": 6}
            scorer = Mock(side_effect=_semantic_similarity)
            scorer.identity.return_value = {"kind": "mock"}
            with patch.object(runner, "build_luna_candidate_provider", return_value=provider), patch.object(
                runner, "build_v24_semantic_similarity", return_value=scorer,
            ):
                result = runner.run_canary(root, input_path=fixture["inputs_path"], candidate_pools=paths,
                    output_dir="artifacts/v24/development/canary_supplemented")
                self.assertEqual(result["passed_pair_count"], 6)
                self.assertEqual(provider.call_count, 6)
                provider.reset_mock(side_effect=True)
                provider.return_value = []
                with self.assertRaisesRegex(RuntimeError, "hard_gate_failed:0/6"):
                    runner.run_canary(root, input_path=fixture["inputs_path"], candidate_pools=paths,
                        output_dir="artifacts/v24/development/canary_failed")
                self.assertEqual(provider.call_count, 6)
                self.assertEqual({call.args[0]["source_key"] for call in provider.call_args_list}, {"s1", "s3"})
            self.assertEqual(protected, {p: sha256_file(p) for p in protected})

    def test_canary_supplement_rejects_duplicate_pools_and_overlapping_sources(self):
        runner = _load_v24_capacity_runner()
        first = Mock(dataset="nfcorpus", manifest={"pool_sha256": "first", "scope": "development_subset"}, offsets={"s0": 0})
        second = Mock(dataset="nfcorpus", manifest={"pool_sha256": "second", "scope": "development_subset"}, offsets={"s0": 0})
        for readers, error in (([first, first], "duplicate_candidate_pool"), ([first, second], "source_overlap")):
            with self.subTest(error=error), patch.object(runner, "load_candidate_fact_pools",
                    side_effect=[{"nfcorpus": r} for r in readers]):
                with self.assertRaisesRegex(ValueError, error):
                    runner._load_canary_candidate_pools(Path("."), self._config(), ["a", "b"])
        second.offsets = {"s1": 0}
        second.manifest["scope"] = "formal_full_pool"
        with patch.object(runner, "load_candidate_fact_pools", side_effect=[{"nfcorpus": first}, {"nfcorpus": second}]):
            with self.assertRaisesRegex(ValueError, "supplement_requires_development_pool"):
                runner._load_canary_candidate_pools(Path("."), self._config(), ["a", "b"])

    def test_canary_does_not_replace_corrupt_missing_or_nonempty_invalid_sources(self):
        runner = _load_v24_capacity_runner()
        source = self._source()
        readers = {(ds, ds): Mock(dataset=ds, offsets={"s0": 0}) for ds in v24.DATASET_ORDER}
        first = readers[("nfcorpus", "nfcorpus")]
        with patch.object(runner, "load_v24_config", return_value=self._config()), patch.object(
            runner, "_load_canary_candidate_pools", return_value=readers,
        ), patch.object(runner, "iter_frozen_source_pool", return_value=iter([source])), patch.object(
            runner, "_historical_canary_sources", return_value=set(),
        ), patch.object(runner, "build_luna_candidate_provider", side_effect=AssertionError("no_Luna")), tempfile.TemporaryDirectory() as temp:
            for reason in ("v24_candidate_pool_record_drift", "v24_candidate_pool_source_missing", "v24_candidate_pool_not_completed"):
                with self.subTest(reason=reason), patch.object(runner, "iter_frozen_source_pool", return_value=iter([source])):
                    first.facts_for_source.side_effect = ValueError(reason)
                    with self.assertRaisesRegex(ValueError, reason):
                        runner.prepare_fresh_canary(Path(temp), candidate_pools=["mock"])
            first.facts_for_source.side_effect = None
            first.facts_for_source.return_value = [{"fact_order": 8}]
            with patch.object(runner, "iter_frozen_source_pool", return_value=iter([source])), patch.object(
                runner, "_fresh_fact_preflight", return_value=(True, []),
            ):
                with self.assertRaisesRegex(ValueError, "nonempty_source_failed_preflight"):
                    runner.prepare_fresh_canary(Path(temp), candidate_pools=["mock"])

    def test_production_consumers_reject_missing_pool_without_legacy_or_model_calls(self):
        runner = _load_v24_capacity_runner()
        with patch.object(v24, "enumerate_candidate_facts", side_effect=AssertionError("no_legacy")), patch.object(
            runner, "build_luna_candidate_provider", side_effect=AssertionError("no_Luna")
        ), patch.object(runner, "load_v24_config", return_value=self._config()), patch.object(
            v24, "load_v24_config", return_value=self._config()
        ):
            for call in (
                lambda: v24.screen_source(self._source(), candidate_provider=lambda fact: [], similarity_fn=_semantic_similarity),
                lambda: v24.scan_frozen_source_pool(Path("."), "nfcorpus", candidate_provider=lambda fact: []),
                lambda: runner.prepare_fresh_canary(Path(".")),
                lambda: runner.run_capacity_check(Path("."), dataset="nfcorpus", sample_sources=1, use_luna=False),
                lambda: runner.run_canary(Path("."), input_path="absent", output_dir="absent"),
            ):
                with self.subTest(call=call), self.assertRaisesRegex(ValueError, "(pool_required|facts_required)"):
                    call()

    def test_pool_binding_rejects_dataset_duplicate_upstream_and_new_development_exposure(self):
        source = self._source()
        config = self._config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._build(root, [source], self._extractor([[]]))
            path = root / "artifacts/v24/candidate_fact_pools/nfcorpus/pool_manifest.json"
            reader = v24.CandidateFactPoolReader(path, config=config)
            with patch.object(v24, "source_pool_bindings", return_value={"nfcorpus": {"source_count": 9}}):
                with self.assertRaisesRegex(ValueError, "upstream_drift"):
                    reader.validate_environment(root, config)
            with patch.object(v24, "source_pool_bindings", return_value={"nfcorpus": {"source_count": 1}}):
                with self.assertRaisesRegex(ValueError, "duplicate_dataset"):
                    v24.load_candidate_fact_pools(root, config, [path, path])
                with patch.object(v24, "collect_development_identities", return_value=[v24._source_identity(source)]):
                    with self.assertRaisesRegex(ValueError, "development_exclusions_drift"):
                        reader.validate_environment(root, config)
            changed = copy.deepcopy(config)
            changed["candidate_fact_adapter"]["model_digest"] = "sha256:" + "b" * 64
            with self.assertRaisesRegex(ValueError, "adapter_drift"):
                v24.CandidateFactPoolReader(path, config=changed)

    @unittest.skip("legacy Qwen adapter removed")
    def test_unbound_real_build_stops_before_output_or_http(self):
        config = self._config()
        config["candidate_fact_adapter"]["model_digest"] = None
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(v24, "load_v24_config", return_value=config), patch.object(
                v24, "source_pool_bindings", return_value={"nfcorpus": {"source_count": 1}}
            ), patch.object(v24.urllib.request, "build_opener", side_effect=AssertionError("no_http")):
                with self.assertRaisesRegex(v24.CandidateExtractionError, "digest_unbound"):
                    v24.build_candidate_fact_pool(root, dataset="nfcorpus", sample_sources=1,
                        output_dir="artifacts/v24/development/unbound")
            self.assertEqual(list(root.iterdir()), [])

    def test_candidate_pool_binding_checks_actual_frozen_database_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pool_root = root / "artifacts/v24/source_pools/nfcorpus"
            small = pool_root / "source_pool_manifest.json"
            order = pool_root / "source_order.json"
            database = pool_root / "source_pool.sqlite3"
            write_json({"dataset": "nfcorpus", "source_order": [], "source_order_content_sha256": "x"}, order)
            manifest = {"kind": "v24_beir_source_pool", "dataset": "nfcorpus", "frozen_source_count": 2250,
                        "source_order_content_sha256": "x", "source_order_sha256": sha256_file(order),
                        "database_sha256": "0" * 64, "membership_labels_read": [], "queries_read": False,
                        "qrels_read": False}
            manifest["manifest_content_sha256"] = sha256_obj(manifest)
            write_json(manifest, small)
            database.touch()
            with patch.object(v24, "DATASET_ORDER", ("nfcorpus",)), patch.object(v24, "V24SourcePoolReader"):
                with self.assertRaisesRegex(RuntimeError, "source_pool_database_drift:nfcorpus"):
                    v24.source_pool_bindings(root, verify_database_dataset="nfcorpus")
                manifest["database_sha256"] = sha256_file(database)
                manifest.pop("manifest_content_sha256")
                manifest["manifest_content_sha256"] = sha256_obj(manifest)
                write_json(manifest, small)
                binding = v24.source_pool_bindings(root, verify_database_dataset="nfcorpus")
                self.assertEqual(binding["nfcorpus"]["database_sha256"], sha256_file(database))
    def test_resume_rejects_corrupted_record_without_model_start(self):
        sources = [self._source(0), self._source(1)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(v24.CandidateExtractionError):
                self._build(root, sources, self._extractor([[], v24.CandidateExtractionError("failed")]))
            records_path = root / "artifacts/v24/candidate_fact_pools/nfcorpus/source_records.jsonl"
            append_jsonl_record({"corrupted": True}, records_path)
            extractor = self._extractor([])
            with self.assertRaisesRegex(ValueError, "records_hash"):
                self._build(root, sources, extractor, resume=True)
            extractor.preflight.assert_not_called()

    def test_pool_cli_validate_is_offline_and_accepts_repeated_dataset_paths(self):
        runner = _load_v24_capacity_runner()
        source = self._source()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._build(root, [source], self._extractor([[]]))
            path = root / "artifacts/v24/candidate_fact_pools/nfcorpus/pool_manifest.json"
            with patch.object(runner, "PROJECT_ROOT", root), patch.object(runner, "load_v24_config", return_value=self._config()), patch.object(
                v24, "source_pool_bindings", return_value={"nfcorpus": {"source_count": 1}}
            ), patch.object(v24, "iter_frozen_source_pool", return_value=iter([source])), patch.object(
                v24, "GLiNER2SpanExtractor", side_effect=AssertionError("no_model")
            ), patch("sys.argv", ["runner", "validate-candidate-pool", "--manifest", str(path)]), patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(runner.main(), 0)
                self.assertEqual(json.loads(output.getvalue())["completed_source_count"], 1)
            with patch.object(runner, "run_capacity_check", return_value={"status": "mock"}) as capacity, patch.object(
                runner, "load_v24_config", return_value=self._config()
            ), patch("sys.argv", ["runner", "run-capacity-check", "--dataset", "nfcorpus", "--sample-sources", "1",
                                  "--candidate-pool", "nfcorpus.json", "--candidate-pool", "trec-covid.json"]), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(runner.main(), 0)
                self.assertEqual(capacity.call_args.kwargs["candidate_pools"], ["nfcorpus.json", "trec-covid.json"])


if __name__ == "__main__":
    unittest.main()
