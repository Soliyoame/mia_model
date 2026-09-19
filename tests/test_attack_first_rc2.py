from __future__ import annotations

import unittest

from src.attack.perturbation_generator import (
    ATTACK_FIRST_GENERATION_PROTOCOL,
    infer_attack_subtype,
    perturb_entity_value,
    requires_definite_article,
)
from src.paired_claims.validator import (
    VALIDATOR_VERSION,
    validate_claim_pair,
)


class AttackFirstCounterfactualTests(unittest.TestCase):
    def test_protocol_versions_are_frozen_as_entity_policy_r1(self) -> None:
        self.assertEqual(
            "v21_entity_policy_counterfactual_r1",
            ATTACK_FIRST_GENERATION_PROTOCOL,
        )
        self.assertEqual(
            "local_claim_pair_v21_entity_policy_r1",
            VALIDATOR_VERSION,
        )

    def test_location_generation_preserves_country_and_article_class(self) -> None:
        true_claim = (
            "The statements follow principles accepted in the "
            "United States of America."
        )
        replacement = perturb_entity_value(
            "United States of America",
            "LOCATION",
            semantic_subtype_name="named_geographic_location",
            context=true_claim,
        )
        self.assertEqual(
            "country",
            infer_attack_subtype(replacement, "LOCATION"),
        )
        self.assertTrue(requires_definite_article(replacement))
        counterfactual_claim = true_claim.replace(
            "United States of America",
            replacement,
        )
        result = validate_claim_pair(
            true_claim,
            counterfactual_claim,
            "United States of America",
            replacement,
            "LOCATION",
        )
        self.assertTrue(result.valid, result.reasons)

    def test_location_validator_rejects_state_to_city(self) -> None:
        result = validate_claim_pair(
            "The policy applies to customers in California.",
            "The policy applies to customers in Tokyo.",
            "California",
            "Tokyo",
            "LOCATION",
        )
        self.assertIn(
            "counterfactual_location_attack_subtype_mismatch",
            result.reasons,
        )

    def test_location_validator_rejects_external_article_mismatch(self) -> None:
        result = validate_claim_pair(
            "The statements use standards accepted in the United States of America.",
            "The statements use standards accepted in the Dublin.",
            "United States of America",
            "Dublin",
            "LOCATION",
        )
        self.assertIn(
            "counterfactual_location_article_class_mismatch",
            result.reasons,
        )

    def test_product_generation_preserves_drug_class(self) -> None:
        true_claim = (
            "The leading product is Somatrogon, a once-weekly human growth "
            "hormone in development."
        )
        replacement = perturb_entity_value(
            "Somatrogon",
            "PRODUCT",
            semantic_subtype_name="named_product",
            context=true_claim,
        )
        counterfactual_claim = true_claim.replace("Somatrogon", replacement)
        self.assertEqual(
            "drug_or_biologic",
            infer_attack_subtype(
                replacement,
                "PRODUCT",
                context=counterfactual_claim,
            ),
        )
        result = validate_claim_pair(
            true_claim,
            counterfactual_claim,
            "Somatrogon",
            replacement,
            "PRODUCT",
        )
        self.assertTrue(result.valid, result.reasons)

    def test_product_validator_rejects_drug_to_toolkit(self) -> None:
        result = validate_claim_pair(
            (
                "The leading product is Somatrogon, a once-weekly human "
                "growth hormone in development."
            ),
            (
                "The leading product is Lumen Toolkit, a once-weekly human "
                "growth hormone in development."
            ),
            "Somatrogon",
            "Lumen Toolkit",
            "PRODUCT",
        )
        self.assertIn(
            "counterfactual_product_attack_subtype_mismatch",
            result.reasons,
        )

    def test_generator_preserves_external_indefinite_article(self) -> None:
        true_claim = "An Atlas Platform instance processed the report."
        replacement = perturb_entity_value(
            "Atlas Platform",
            "PRODUCT",
            context=true_claim,
        )
        self.assertIn(replacement[0].casefold(), {"a", "e", "i", "o", "u"})
        result = validate_claim_pair(
            true_claim,
            true_claim.replace("Atlas Platform", replacement),
            "Atlas Platform",
            replacement,
            "PRODUCT",
        )
        self.assertTrue(result.valid, result.reasons)


class AttackFirstValidatorTests(unittest.TestCase):
    def test_rejects_only_obvious_generic_organization_surfaces(self) -> None:
        cases = (
            "commercial partners",
            "Corporation",
            "target company",
            "limited liability companies",
        )
        for original in cases:
            with self.subTest(original=original):
                result = validate_claim_pair(
                    f"The agreement refers to {original} in this section.",
                    "The agreement refers to Harborview Group in this section.",
                    original,
                    "Harborview Group",
                    "ORG",
                )
                self.assertIn(
                    "original_entity_obvious_generic",
                    result.reasons,
                )

    def test_rejects_generic_product_service_line(self) -> None:
        result = validate_claim_pair(
            "The Company's Water Services service lines grew during the year.",
            "The Company's Meridian Water Services service lines grew during the year.",
            "Water Services",
            "Meridian Water Services",
            "PRODUCT",
        )
        self.assertIn("original_entity_obvious_generic", result.reasons)

    def test_rejects_obvious_numeric_and_infinitive_fragments(self) -> None:
        numeric = validate_claim_pair(
            "3 million of underwriting loss from wildfires in California.",
            "3 million of underwriting loss from wildfires in Texas.",
            "California",
            "Texas",
            "LOCATION",
        )
        infinitive = validate_claim_pair(
            "Song Bo, to earn mineral rights located in British Columbia.",
            "Song Bo, to earn mineral rights located in Ontario.",
            "British Columbia",
            "Ontario",
            "LOCATION",
        )
        self.assertIn("true_claim_obvious_fragment", numeric.reasons)
        self.assertIn("true_claim_obvious_fragment", infinitive.reasons)

    def test_rejects_copyright_and_promotional_headline_fragments(self) -> None:
        copyright_row = validate_claim_pair(
            "(C) Reuters Limited 2001.",
            "(C) Northstar Logistics LLC 2001.",
            "Reuters Limited",
            "Northstar Logistics LLC",
            "ORG",
        )
        promotion = validate_claim_pair(
            "Compaq Presario Notebook - GREAT OFFER + REBATE AVAILABLE!",
            "Axion SP7 - GREAT OFFER + REBATE AVAILABLE!",
            "Compaq Presario Notebook",
            "Axion SP7",
            "PRODUCT",
        )
        self.assertIn("true_claim_obvious_fragment", copyright_row.reasons)
        self.assertIn("true_claim_obvious_fragment", promotion.reasons)

    def test_allows_org_subtype_ambiguity_and_email_ellipsis(self) -> None:
        org = validate_claim_pair(
            "The Bank of New York Mellon served as trustee.",
            "Vanta Industries served as trustee.",
            "The Bank of New York Mellon",
            "Vanta Industries",
            "ORG",
        )
        person = validate_claim_pair(
            "Bryon Hoskins but need confirmation by you.",
            "Alex Carter but need confirmation by you.",
            "Bryon Hoskins",
            "Alex Carter",
            "PERSON",
        )
        self.assertTrue(org.valid, org.reasons)
        self.assertTrue(person.valid, person.reasons)

    def test_allows_named_health_plan_with_matching_replacement(self) -> None:
        true_claim = "Medicare Advantage premium revenues were adjusted by CMS."
        replacement = perturb_entity_value(
            "Medicare Advantage",
            "PRODUCT",
            context=true_claim,
        )
        counterfactual_claim = true_claim.replace(
            "Medicare Advantage",
            replacement,
        )
        result = validate_claim_pair(
            true_claim,
            counterfactual_claim,
            "Medicare Advantage",
            replacement,
            "PRODUCT",
        )
        self.assertTrue(result.valid, result.reasons)


if __name__ == "__main__":
    unittest.main()
