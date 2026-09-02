from __future__ import annotations

import unittest

import numpy as np

from src.prepare.restoration_first_v24 import (
    SemanticSimilarityScorer,
    build_eligibility_manifest,
    build_split_manifest,
    deterministic_correction_eligibility_judge,
    deterministic_role_judge,
    deterministic_split,
    evaluate_candidate,
    fallback_queries,
    scan_until_target,
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


class V24EligibilityTests(unittest.TestCase):
    def test_config_removes_nli_contradiction_gate(self):
        self.assertFalse(load_v24_config()["eligibility"]["nli_contradiction_required"])
        self.assertFalse(load_v24_config()["stealth_diagnostics"]["hard_gate"])

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


if __name__ == "__main__":
    unittest.main()
