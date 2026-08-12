from __future__ import annotations

import unittest

from src.attack.attackability_context_overlay import overlay_pair
from src.prepare.attackability_calibration_r3 import (
    _anonymous_review_id,
    _available_overlay_rows,
    _prediction_match,
    load_r3_config,
)


def _pair(**updates):
    original = "Ada Lovelace"
    counterfactual = "Grace Hopper"
    claim = "The study was led by Ada Lovelace in 2020."
    start = claim.index(original)
    row = {
        "pair_id": "p1",
        "source_key": "s1",
        "fact_signature": "f1",
        "dataset": "pubmed",
        "effective_type": "PERSON",
        "hard_gate_passed": True,
        "hard_gate_failure_reasons": [],
        "true_claim": claim,
        "counterfactual_claim": claim[:start] + counterfactual + claim[start + len(original) :],
        "original_entity": original,
        "counterfactual_entity": counterfactual,
        "original_span": [start, start + len(original)],
        "counterfactual_span": [start, start + len(counterfactual)],
        "utility_components": {
            "grounded_fact_stability": 0.9,
            "corpus_specificity": 0.8,
            "verification_discriminativeness": 0.8,
            "lexical_anchor_strength": 0.8,
        },
    }
    row.update(updates)
    return row


class AttackabilityCalibrationR3Tests(unittest.TestCase):
    def test_config_freezes_one_existing_router(self):
        config = load_r3_config("configs/attackability_calibration_r3.yaml")
        router = config["single_router_validation"]
        self.assertEqual(router["model_id"], "fastino/gliner2-base-v1")
        self.assertEqual(
            router["model_revision"],
            "f5b2ecedebe4381b088c1cf276f5bf72a52cac54",
        )
        self.assertEqual(config["review"]["mode"], "assistant_only_no_human_validation")

    def test_overlay_rejects_partial_entity_span(self):
        row = _pair()
        row["original_span"] = [row["original_span"][0] + 1, row["original_span"][1]]
        result = overlay_pair(row)
        self.assertFalse(result["r3_hard_gate_passed"])
        self.assertIn("r3_original_span_mismatch", result["r3_hard_gate_failure_reasons"])

    def test_overlay_keeps_role_uncertainty_as_soft_penalty(self):
        row = _pair(
            effective_type="ORG",
            original_entity="Ada Lovelace",
            counterfactual_entity="Harborview Group",
        )
        start = row["true_claim"].index("Ada Lovelace")
        row["counterfactual_claim"] = row["true_claim"][:start] + "Harborview Group" + row["true_claim"][start + len("Ada Lovelace") :]
        row["counterfactual_span"] = [start, start + len("Harborview Group")]
        result = overlay_pair(row)
        self.assertTrue(result["r3_hard_gate_passed"])
        self.assertIn("r3_organization_surface_role_incompatible", result["r3_soft_penalty_reasons"])
        self.assertEqual(result["r3_utility_components"]["context_slot_compatibility"], 0.0)

    def test_prediction_match_requires_same_type_exact_slot_and_confidence(self):
        row = overlay_pair(_pair())
        start, end = row["counterfactual_span"]
        good = {"label": "PERSON", "start": start, "end": end, "score": 0.91}
        self.assertTrue(_prediction_match(row, good, 0.65))
        self.assertFalse(_prediction_match(row, {**good, "label": "ORG"}, 0.65))
        self.assertFalse(_prediction_match(row, {**good, "start": start + 1}, 0.65))
        self.assertFalse(_prediction_match(row, {**good, "score": 0.64}, 0.65))

    def test_prediction_match_rejects_partial_overlap_even_for_same_type(self):
        row = overlay_pair(_pair())
        start, end = row["counterfactual_span"]
        partial = {
            "label": "PERSON",
            "start": start,
            "end": end - 1,
            "score": 0.99,
        }
        self.assertFalse(_prediction_match(row, partial, 0.65))

    def test_available_rows_exclude_all_earlier_identities(self):
        rows = [_pair(), _pair(pair_id="p2", source_key="s2", fact_signature="f2")]
        exclusions = {"pair_ids": {"p1"}, "source_keys": set(), "fact_signatures": set()}
        selected = _available_overlay_rows(rows, exclusions)
        self.assertEqual([row["pair_id"] for row in selected], ["p2"])

    def test_overlay_does_not_read_downstream_outcomes(self):
        base = overlay_pair(_pair())
        changed = overlay_pair(
            _pair(
                membership_label="KB_Member",
                victim_response="yes",
                attack_auc=1.0,
            )
        )
        for field in (
            "r3_hard_gate_passed",
            "r3_hard_gate_failure_reasons",
            "r3_soft_penalty_reasons",
            "r3_utility_components",
            "r3_utility_score",
        ):
            self.assertEqual(base[field], changed[field])

    def test_anonymous_review_id_hides_cell_and_kind(self):
        review_id = _anonymous_review_id("control", "pubmed", "PERSON", "p1")
        self.assertTrue(review_id.startswith("v22_c3_"))
        for value in ("control", "pubmed", "PERSON"):
            self.assertNotIn(value, review_id)


if __name__ == "__main__":
    unittest.main()
