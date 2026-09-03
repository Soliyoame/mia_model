from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

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
    stealth_diagnostics,
)
from src.utils.hash import sha256_obj


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
        "dataset": "edgar",
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
        "dataset": "edgar",
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
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        package = _package(
            "Nevada",
            "The company is incorporated in {ENTITY}.",
            "Is the company incorporated in Delaware?",
            "Is the company incorporated in Nevada?",
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
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        package = _package(
            "Nevada",
            "The company is incorporated in {ENTITY}.",
            "Is the company incorporated in Delaware?",
            "Is the company incorporated in Nevada?",
        )
        result = evaluate_candidate(
            fact,
            "The company is incorporated in Delaware.",
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
            true_claim="The company is incorporated in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="The company is incorporated in Delaware.",
            canonical_counterfactual="The company is incorporated in Nevada.",
            q_plus="Is it correct that the company is incorporated in Delaware?",
            q_minus="Is it correct that the company is incorporated in Nevada?",
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
        rows = deterministic_split(sources, dataset="edgar")
        self.assertEqual(len(rows), 2250)
        self.assertEqual({row["group"] for row in rows}, {"KB_Member", "True_Non_Member", "Reserve"})
        with self.assertRaisesRegex(ValueError, "exactly_2250"):
            deterministic_split(sources[:-1], dataset="edgar")

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
            deterministic_split(sources, dataset="edgar")

    def test_scan_stops_at_exact_target_without_reading_later_sources(self):
        seen: list[str] = []

        def sources():
            for index in range(3000):
                key = f"s-{index}"
                seen.append(key)
                yield {"dataset": "edgar", "source_key": key, "source_order_rank": str(index), "full_text": "Alice is incorporated in Delaware."}

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
            ({"dataset": "edgar", "source_key": f"s-{i}", "source_order_rank": str(i), "full_text": "The company is incorporated in Delaware."} for i in range(2)),
            candidate_provider=lambda _fact: [],
            target_sources=3,
            facts=[fact],
            similarity_fn=_semantic_similarity,
        )
        self.assertEqual(result["status"], "insufficient_eligible_capacity")
        self.assertEqual(result["eligible_source_count"], 0)

    def test_membership_fields_cannot_change_pre_split_result(self):
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        package = _package("Nevada", "The company is incorporated in {ENTITY}.", "Is the company incorporated in Delaware?", "Is the company incorporated in Nevada?")
        source = {"dataset": "edgar", "source_key": "s", "source_order_rank": "0", "full_text": "The company is incorporated in Delaware."}
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
            "dataset": "edgar",
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
            "dataset": "edgar",
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
            "dataset": "edgar",
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
        manifest = build_eligibility_manifest(scan, dataset="edgar", config=config, source_pool={"source_count": 1})
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
            build_split_manifest(manifest, dataset="edgar")

    def test_build_split_manifest_revalidates_eligibility_hash(self):
        source = {
            "eligible": True,
            "dataset": "edgar",
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
        manifest = build_eligibility_manifest(scan, dataset="edgar", config=config, source_pool={"source_count": 1})
        manifest["sources"][0]["selected_pairs"][0]["pair_id"] = "drifted"
        with self.assertRaisesRegex(ValueError, "manifest_hash_invalid"):
            build_split_manifest(manifest, dataset="edgar")

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
            true_claim="Enron shall file notice in Delaware.",
            original_entity="Delaware",
            replacement_entity="Nevada",
            canonical_true="Enron shall file notice in Delaware.",
            canonical_counterfactual="Enron shall file notice in Nevada.",
            q_plus="Shall Enron file notice in Delaware?",
            q_minus="Shall Enron file notice in Nevada?",
            similarity_fn=_semantic_similarity,
        )
        self.assertNotIn("q_plus_not_polar_question", reasons)
        self.assertNotIn("q_minus_not_polar_question", reasons)
        self.assertNotIn("q_plus_new_factual_entity", reasons)
        self.assertNotIn("q_minus_new_factual_entity", reasons)

    def test_semantic_correction_retry_runs_once_and_preserves_evidence(self):
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        source = {
            "dataset": "edgar",
            "source_key": "source-1",
            "source_order_rank": "0",
            "full_text": fact["true_claim"],
        }
        initial = _package(
            "Nevada",
            "The company is incorporated in {ENTITY}.",
            "Is it incorporated in Delaware?",
            "Is it incorporated in Nevada?",
        )
        corrected = _package(
            "Nevada",
            "The company is incorporated in {ENTITY}.",
            "Is the company incorporated in Delaware?",
            "Is the company incorporated in Nevada?",
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
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        source = {
            "dataset": "edgar",
            "source_key": "source-1",
            "source_order_rank": "0",
            "full_text": fact["true_claim"],
        }
        valid = _package(
            "Nevada",
            "The company is incorporated in {ENTITY}.",
            "Is the company incorporated in Delaware?",
            "Is the company incorporated in Nevada?",
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
            "dataset": "edgar",
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
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        valid = _package("Nevada", "The company is incorporated in {ENTITY}.", "Is the company incorporated in Delaware?", "Is the company incorporated in Nevada?")
        valid["retrieval_anchors"] = ["company"]
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
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        package = _package(
            "Nevada",
            "The company is incorporated in {ENTITY}.",
            "Is the company incorporated in Delaware?",
            "Is the company incorporated in Nevada?",
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
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        package = _package(
            "Nevada",
            "The company is incorporated in {ENTITY}.",
            "Is the company incorporated in Delaware?",
            "Is the company incorporated in Nevada?",
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
            "dataset": "edgar",
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
            dataset="edgar",
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
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        package = _package("Nevada", "The company is incorporated in {ENTITY}.", "", "")
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
            "dataset": "edgar",
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
        manifest = build_eligibility_manifest(scan, dataset="edgar", config=config, source_pool={"source_count": 1})
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
            "dataset": "edgar",
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
        manifest = build_eligibility_manifest(scan, dataset="edgar", config=config, source_pool={"source_count": 1})
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
            "dataset": "edgar",
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
        manifest = build_eligibility_manifest(scan, dataset="edgar", config=config, source_pool={"source_count": 1})
        query_manifest = build_query_manifest(manifest)
        query_manifest["rows"][1]["original_entity"] = "Carol"
        query_manifest["manifest_sha256"] = sha256_obj(
            {key: value for key, value in query_manifest.items() if key != "manifest_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "pair_binding"):
            validate_query_manifest(query_manifest)

    def test_surface_failure_uses_same_reconstruction_fallback(self):
        fact = _fact("The company is incorporated in Delaware.", "Delaware")
        package = _package("Nevada", "The company is incorporated in {ENTITY}.", "", "")
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
            "dataset": "edgar",
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
            "dataset": "edgar",
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
            dataset="edgar",
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
                    "edgar",
                    candidate_provider=lambda _fact: [],
                    max_candidate_facts_per_source=9,
                )

    def test_scan_reports_entity_diversity_and_processing_coverage(self):
        source_rows = [
            {"dataset": "edgar", "source_key": f"scan-{index}", "source_order_rank": str(index)}
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


if __name__ == "__main__":
    unittest.main()
