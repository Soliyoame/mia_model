from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.attack.entity_extractor import EntityExtractor, IDENTIFIER_RE, URL_RE
from src.attack.perturbation_generator import perturb_entity_value
from src.paired_claims.claim_generator import generate_paired_claims_file
from src.paired_claims.validator import (
    VALIDATOR_VERSION,
    find_entity_span,
    validate_claim_pair,
    validate_query_pair,
)
from src.query_generation.paired_query_builder import generate_paired_queries_file
from src.utils.io import read_jsonl, write_jsonl


class ClaimValidatorTests(unittest.TestCase):
    def test_entity_span_respects_token_boundary(self) -> None:
        self.assertIsNone(find_entity_span("The total was 137 dollars.", "37"))
        self.assertEqual(find_entity_span("The total was 37 dollars.", "37"), (14, 16))

    def test_valid_money_pair_changes_one_slot(self) -> None:
        result = validate_claim_pair(
            "Delta Logistics paid $48,720 on March 12, 2022.",
            "Delta Logistics paid $51,156 on March 12, 2022.",
            "$48,720",
            "$51,156",
            "MONEY",
        )
        self.assertTrue(result.valid, result.reasons)

    def test_currency_prefix_is_part_of_money_span(self) -> None:
        result = validate_claim_pair(
            "The placement raised C$165,000 for the company.",
            "The placement raised C$173,250 for the company.",
            "C$165,000",
            "C$173,250",
            "MONEY",
        )
        self.assertTrue(result.valid, result.reasons)

    def test_second_edit_is_rejected(self) -> None:
        result = validate_claim_pair(
            "Delta Logistics paid $48,720 on March 12, 2022.",
            "Orion Logistics paid $51,156 on March 12, 2022.",
            "$48,720",
            "$51,156",
            "MONEY",
        )
        self.assertFalse(result.valid)
        self.assertIn("not_single_slot_substitution", result.reasons)

    def test_wrong_counterfactual_type_is_rejected(self) -> None:
        result = validate_claim_pair(
            "Delta Logistics paid $48,720 for the service.",
            "Delta Logistics paid March 12, 2022 for the service.",
            "$48,720",
            "March 12, 2022",
            "MONEY",
        )
        self.assertFalse(result.valid)
        self.assertIn("counterfactual_entity_type_mismatch", result.reasons)

    def test_truncated_claim_is_rejected(self) -> None:
        result = validate_claim_pair(
            "Delta Logistics paid $48,720 to the",
            "Delta Logistics paid $51,156 to the",
            "$48,720",
            "$51,156",
            "MONEY",
        )
        self.assertIn("true_claim_truncated", result.reasons)
        self.assertIn("counterfactual_claim_truncated", result.reasons)

    def test_rc1_rejects_leading_and_terminal_sentence_fragments(self) -> None:
        cases = (
            (
                "lso operates Sutton Data Services in Prague, Czech Republic.",
                "lso operates Sutton Data Services in Tokyo, Czech Republic.",
                "Prague",
                "Tokyo",
                "LOCATION",
            ),
            (
                "The Company recorded a right of use asset of $14.",
                "Cedarline Partners recorded a right of use asset of $14.",
                "Company",
                "Cedarline Partners",
                "ORG",
            ),
            (
                "National Review's Jay Nordlinger http://www.",
                "National Review's Dakota Reyes http://www.",
                "Jay Nordlinger",
                "Dakota Reyes",
                "PERSON",
            ),
            (
                "Project GEM (Global Enron Migration) for the rollout of Windows 2000.",
                "Project Vertex (Global Enron Migration) for the rollout of Windows 2000.",
                "Project GEM",
                "Project Vertex",
                "PROJECT_NAME",
            ),
        )
        for true_claim, counterfactual_claim, original, counterfactual, entity_type in cases:
            with self.subTest(true_claim=true_claim):
                result = validate_claim_pair(
                    true_claim,
                    counterfactual_claim,
                    original,
                    counterfactual,
                    entity_type,
                )
                self.assertTrue(
                    any("claim_" in reason for reason in result.reasons),
                    result.reasons,
                )

    def test_rc1_keeps_complete_money_and_numeric_unit_claims(self) -> None:
        complete_money = validate_claim_pair(
            "The account had an average balance of $136,000.",
            "The account had an average balance of $142,800.",
            "$136,000",
            "$142,800",
            "MONEY",
        )
        numeric_unit = validate_claim_pair(
            "The company completed a 350-kilometre pipeline.",
            "The company completed a 368-kilometre pipeline.",
            "350",
            "368",
            "NUMERIC_VALUE",
        )
        self.assertTrue(complete_money.valid, complete_money.reasons)
        self.assertTrue(numeric_unit.valid, numeric_unit.reasons)

    def test_rc1_rejects_mail_and_heading_contamination(self) -> None:
        cases = (
            (
                ">From: Work Abroad News >To: user@example.com >Subject: Update "
                ">Date: Wed, 28 Nov 2001 >Visit http://international.monster.com/.",
                "http://international.monster.com/",
                "http://international.monster.com/archive",
                "URL",
            ),
            (
                "The free newsletter for Fin= ance Members asks users to send mail to "
                "cancel-Quote@mailbox.lycos.com.",
                "cancel-Quote@mailbox.lycos.com",
                "alternate.contact@mailbox.lycos.com",
                "EMAIL",
            ),
            (
                "Methods All procedures were approved by Lund University.",
                "Lund University",
                "Northbridge University",
                "ORG",
            ),
        )
        for true_claim, original, counterfactual, entity_type in cases:
            counterfactual_claim = true_claim.replace(original, counterfactual, 1)
            with self.subTest(true_claim=true_claim):
                result = validate_claim_pair(
                    true_claim,
                    counterfactual_claim,
                    original,
                    counterfactual,
                    entity_type,
                )
                self.assertTrue(
                    any("claim_" in reason for reason in result.reasons),
                    result.reasons,
                )

    def test_rc1_rejects_structured_entity_context_confusions(self) -> None:
        cases = (
            (
                "COVID-19 spread throughout the world.",
                "COVID-20 spread throughout the world.",
                "19",
                "20",
                "NUMERIC_VALUE",
            ),
            (
                "Previous studies [ 14 , 15 ] reported this effect.",
                "Previous studies [ 15 , 15 ] reported this effect.",
                "14",
                "15",
                "NUMERIC_VALUE",
            ),
            (
                "The meeting runs from Wednesday, July 26 through Friday, July 28.",
                "The meeting runs from Wednesday, July 26 through Friday, July 29.",
                "28",
                "29",
                "NUMERIC_VALUE",
            ),
            (
                "The sample used AC 16B PMB 25/55-60 containing modified bitumen.",
                "The sample used AC 16B PMB 26/55-60 containing modified bitumen.",
                "25/55-60",
                "26/55-60",
                "DATE",
            ),
            (
                "Antibodies were applied at 1:20, 1:1000, and 1:250 dilutions.",
                "Antibodies were applied at 01:50, 1:1000, and 1:250 dilutions.",
                "1:20",
                "01:50",
                "TIME",
            ),
            (
                "The animals were exposed to a 12:12 h light:dark cycle.",
                "The animals were exposed to a 12:42 h light:dark cycle.",
                "12:12",
                "12:42",
                "TIME",
            ),
            (
                "The agents contract COVID-19 or another contagious disease.",
                "The agents contract COVID-26 or another contagious disease.",
                "contract COVID-19",
                "contract COVID-26",
                "IDENTIFIER",
            ),
            (
                "Trading during the Chapter 11 Case remains speculative.",
                "Trading during the Chapter 12 Case remains speculative.",
                "11 Case",
                "12 Case",
                "MEDICAL_VALUE",
            ),
            (
                "Only 1 Day remains.",
                "Only 2 Day remains.",
                "1 Day",
                "2 Day",
                "MEDICAL_VALUE",
            ),
        )
        for true_claim, counterfactual_claim, original, counterfactual, entity_type in cases:
            with self.subTest(entity_type=entity_type, original=original):
                result = validate_claim_pair(
                    true_claim,
                    counterfactual_claim,
                    original,
                    counterfactual,
                    entity_type,
                )
                self.assertTrue(
                    any("context_mismatch" in reason or "type_mismatch" in reason for reason in result.reasons),
                    result.reasons,
                )

    def test_rc1_rejects_generic_or_competing_semantic_surfaces(self) -> None:
        cases = (
            (
                "We will remain an emerging growth company for the foreseeable future.",
                "We will remain Vanta Industries for the foreseeable future.",
                "emerging growth company",
                "Vanta Industries",
                "ORG",
            ),
            (
                "We no longer have a company Enron Liquids.",
                "We no longer have a company Nova Device.",
                "Enron Liquids",
                "Nova Device",
                "PRODUCT",
            ),
            (
                "The sample was treated with DNaseI to remove genomic DNA.",
                "The sample was treated with Vertex Console to remove genomic DNA.",
                "DNaseI",
                "Vertex Console",
                "PRODUCT",
            ),
            (
                "The TaSi 2 -TaC-SiC-SiC nanowire powders were analyzed.",
                "The Meridian 7 powders were analyzed.",
                "TaSi 2 -TaC-SiC-SiC nanowire",
                "Meridian 7",
                "PRODUCT",
            ),
        )
        for true_claim, counterfactual_claim, original, counterfactual, entity_type in cases:
            with self.subTest(original=original):
                result = validate_claim_pair(
                    true_claim,
                    counterfactual_claim,
                    original,
                    counterfactual,
                    entity_type,
                )
                self.assertIn("original_entity_context_mismatch", result.reasons)

    def test_bad_person_boundary_is_rejected(self) -> None:
        result = validate_claim_pair(
            "If Arcosa approves the request, processing will begin.",
            "Taylor Morgan approves the request, processing will begin.",
            "If Arcosa",
            "Taylor Morgan",
            "PERSON",
        )
        self.assertIn("original_entity_type_mismatch", result.reasons)

    def test_role_and_section_phrases_are_not_people(self) -> None:
        for entity in (
            "Background Colon",
            "Conclusions In",
            "General Partner",
            "Public Offering",
            "Revenue Recognition",
            "Supplementary Figure",
        ):
            with self.subTest(entity=entity):
                true_claim = f"{entity} was discussed in the report."
                result = validate_claim_pair(
                    true_claim,
                    true_claim.replace(entity, "Taylor Morgan", 1),
                    entity,
                    "Taylor Morgan",
                    "PERSON",
                )
                self.assertIn("original_entity_type_mismatch", result.reasons)

    def test_generic_project_connector_is_rejected(self) -> None:
        invalid = validate_claim_pair(
            "The intervention was described as Program At in the report.",
            "The intervention was described as Initiative Nova in the report.",
            "Program At",
            "Initiative Nova",
            "PROJECT_NAME",
        )
        valid = validate_claim_pair(
            "The intervention was described as Program Atlas in the report.",
            "The intervention was described as Initiative Nova in the report.",
            "Program Atlas",
            "Initiative Nova",
            "PROJECT_NAME",
        )
        self.assertIn("original_entity_type_mismatch", invalid.reasons)
        self.assertTrue(valid.valid, valid.reasons)

    def test_identifier_requires_bounded_prefix_and_numeric_payload(self) -> None:
        self.assertIsNone(IDENTIFIER_RE.search("The contract assets were identified yesterday."))
        self.assertEqual(IDENTIFIER_RE.search("Contract AB-1234 was signed.").group(0), "Contract AB-1234")
        result = validate_claim_pair(
            "Contract Assets were reported in the statement.",
            "Contract AssetsB were reported in the statement.",
            "Contract Assets",
            "Contract AssetsB",
            "IDENTIFIER",
        )
        self.assertIn("original_entity_type_mismatch", result.reasons)

    def test_quantity_phrase_is_not_an_identifier_but_domain_ids_remain_valid(self) -> None:
        invalid = validate_claim_pair(
            "We order 6shots of tequila and three beers.",
            "We order 13shots of tequila and three beers.",
            "order 6shots",
            "order 13shots",
            "IDENTIFIER",
        )
        self.assertIn("original_entity_type_mismatch", invalid.reasons)
        self.assertIn("counterfactual_entity_type_mismatch", invalid.reasons)

        valid_pairs = (
            ("The structure used PDB ID: 3EIG in the assay.", "ID: 3EIG", "ID: 10EIG"),
            ("The filing cites case number 20CV0234 in Ohio.", "number 20CV0234", "number 20CV0241"),
            (
                "The reagent has product number W383902-100G-K in the catalog.",
                "number W383902-100G-K",
                "number W383902-107G-K",
            ),
            ("The ethics file number: 232_14B was approved.", "number: 232_14B", "number: 232_21B"),
        )
        for true_claim, original, counterfactual in valid_pairs:
            with self.subTest(original=original):
                counterfactual_claim = true_claim.replace(original, counterfactual, 1)
                result = validate_claim_pair(
                    true_claim,
                    counterfactual_claim,
                    original,
                    counterfactual,
                    "IDENTIFIER",
                )
                self.assertTrue(result.valid, result.reasons)

    def test_org_slot_must_cover_one_complete_entity(self) -> None:
        incomplete = validate_claim_pair(
            "Bellows/Piping Technology & Products, Inc. supplied the component.",
            "Bellows/Piping Technology & Vanta Industries. supplied the component.",
            "Products, Inc",
            "Vanta Industries",
            "ORG",
        )
        org_list = validate_claim_pair(
            "Participants came from China-Japan Friendship Hospital, Beijing Hospital, Longhua Hospital.",
            "Participants came from Vanta Industries.",
            "China-Japan Friendship Hospital, Beijing Hospital, Longhua Hospital",
            "Vanta Industries",
            "ORG",
        )
        valid = validate_claim_pair(
            "Entity EPMIE is Enron Power Marketing, Inc.",
            "Entity EPMIE is Ironwood Associates.",
            "Enron Power Marketing, Inc",
            "Ironwood Associates",
            "ORG",
        )
        valid_after_preposition = validate_claim_pair(
            "The report was signed on behalf of Revlon Consumer Products Corporation.",
            "The report was signed on behalf of Brightpeak Holdings.",
            "Revlon Consumer Products Corporation",
            "Brightpeak Holdings",
            "ORG",
        )
        valid_before_conjunction = validate_claim_pair(
            "Enron Corp and El Paso Corp were discussed.",
            "Cedarline Partners and El Paso Corp were discussed.",
            "Enron Corp",
            "Cedarline Partners",
            "ORG",
        )
        self.assertIn("original_entity_context_boundary_mismatch", incomplete.reasons)
        self.assertIn("original_entity_context_boundary_mismatch", org_list.reasons)
        self.assertTrue(valid.valid, valid.reasons)
        self.assertTrue(valid_after_preposition.valid, valid_after_preposition.reasons)
        self.assertTrue(valid_before_conjunction.valid, valid_before_conjunction.reasons)

    def test_leading_list_quote_or_punctuation_fragment_is_rejected(self) -> None:
        claims = (
            "• Allows entities to deduct 25% of charitable contributions.",
            ", case number 20CV0234 was filed in Ohio.",
            "> > > We order 6shots of tequila and three beers.",
        )
        entities = ("25%", "number 20CV0234", "order 6shots")
        counterfactuals = ("26%", "number 20CV0241", "order 13shots")
        types = ("PERCENT", "IDENTIFIER", "IDENTIFIER")
        for claim, original, counterfactual, entity_type in zip(
            claims, entities, counterfactuals, types, strict=True
        ):
            with self.subTest(claim=claim):
                result = validate_claim_pair(
                    claim,
                    claim.replace(original, counterfactual, 1),
                    original,
                    counterfactual,
                    entity_type,
                )
                self.assertIn("true_claim_fragment_surface", result.reasons)

    def test_flattened_table_rows_are_rejected(self) -> None:
        vaccine_table = (
            "Inactivated Research Institute for Biological Safety Problems, Rep of Kazakhstan "
            "Live attenuated virus Codagenix/Serum Institute of India Deoptimized live attenuated "
            "vaccines Pre-clinical Indian Immunologicals Limited/Griffith University Codon "
            "de-optimization of live attenuated vaccine UMC Utrecht/Radboud University Recombinant "
            "BCG technology Protein subunit Novavax Phase I/II Clover Biopharmaceuticals Inc."
        )
        vaccine_result = validate_claim_pair(
            vaccine_table,
            vaccine_table.replace("Pre-clinical Indian Immunologicals Limited", "Ironwood Associates", 1),
            "Pre-clinical Indian Immunologicals Limited",
            "Ironwood Associates",
            "ORG",
        )
        statistics_table = (
            "Most prevalent terms from July 1, 2017 to September 15, 2019 Topic: Positive mentions "
            "Negative mentions Fairs 9% Out 7% Fun 7% Show 5% Livestock 12% Chicken 9% Hogs 8%."
        )
        statistics_result = validate_claim_pair(
            statistics_table,
            statistics_table.replace("July 1, 2017", "July 04, 2017", 1),
            "July 1, 2017",
            "July 04, 2017",
            "DATE",
        )
        self.assertIn("true_claim_tabular_fragment", vaccine_result.reasons)
        self.assertIn("counterfactual_claim_tabular_fragment", vaccine_result.reasons)
        self.assertIn("true_claim_tabular_fragment", statistics_result.reasons)
        self.assertIn("counterfactual_claim_tabular_fragment", statistics_result.reasons)

    def test_long_complete_prose_is_not_a_tabular_fragment(self) -> None:
        true_claim = (
            "Also effective January 1, 2020, the Conflicts Committee of the Board and the audit "
            "committee of CVR Energy approved, and the parties entered into the Corporate MSA "
            "between CVR Services and certain affiliates, including CVR Energy, CVR GP and the "
            "Partnership, on substantially equivalent terms for the reporting period."
        )
        result = validate_claim_pair(
            true_claim,
            true_claim.replace("January 1, 2020", "January 04, 2020", 1),
            "January 1, 2020",
            "January 04, 2020",
            "DATE",
        )
        self.assertTrue(result.valid, result.reasons)

    def test_url_extractor_excludes_terminal_punctuation(self) -> None:
        matches = [match.group(0) for match in URL_RE.finditer("Visit www.example.com, then https://example.org/path.")]
        self.assertEqual(matches, ["www.example.com", "https://example.org/path"])

    def test_invalid_bracketed_url_surface_is_rejected(self) -> None:
        result = validate_claim_pair(
            "The placeholder website is http://www.[company in this template.",
            "The placeholder website is http://www.[company/archive in this template.",
            "http://www.[company",
            "http://www.[company/archive",
            "URL",
        )
        self.assertIn("original_entity_type_mismatch", result.reasons)
        self.assertIn("counterfactual_entity_type_mismatch", result.reasons)

    def test_mail_metadata_and_encoding_artifacts_are_rejected(self) -> None:
        result = validate_claim_pair(
            "The payment was $48,720. Content-Transfer-Encoding: quoted-printable.",
            "The payment was $51,156. Content-Transfer-Encoding: quoted-printable.",
            "$48,720",
            "$51,156",
            "MONEY",
        )
        self.assertIn("true_claim_email_metadata", result.reasons)
        self.assertIn("true_claim_encoding_or_mailbox_artifact", result.reasons)

    def test_missing_terminal_punctuation_is_truncated(self) -> None:
        result = validate_claim_pair(
            "The company paid $48,720 for the service",
            "The company paid $51,156 for the service",
            "$48,720",
            "$51,156",
            "MONEY",
        )
        self.assertIn("true_claim_truncated", result.reasons)

    def test_year_perturbation_preserves_year_subtype(self) -> None:
        counterfactual = perturb_entity_value("2019", "NUMERIC_VALUE")
        self.assertEqual(counterfactual, "2020")
        result = validate_claim_pair(
            "The study was completed in 2019.",
            f"The study was completed in {counterfactual}.",
            "2019",
            counterfactual,
            "NUMERIC_VALUE",
        )
        self.assertTrue(result.valid, result.reasons)
        bad = validate_claim_pair(
            "The study was completed in 2019.",
            "The study was completed in 2,120.",
            "2019",
            "2,120",
            "NUMERIC_VALUE",
        )
        self.assertIn("counterfactual_year_subtype_mismatch", bad.reasons)

    def test_duration_perturbation_preserves_number_agreement(self) -> None:
        counterfactual = perturb_entity_value("1 hour", "DURATION")
        self.assertEqual(counterfactual, "2 hours")
        valid = validate_claim_pair(
            "The procedure lasted 1 hour in total.",
            "The procedure lasted 2 hours in total.",
            "1 hour",
            "2 hours",
            "DURATION",
        )
        self.assertTrue(valid.valid, valid.reasons)
        invalid = validate_claim_pair(
            "The procedure lasted 1 hour in total.",
            "The procedure lasted 2 hour in total.",
            "1 hour",
            "2 hour",
            "DURATION",
        )
        self.assertIn("counterfactual_duration_number_agreement", invalid.reasons)

    def test_context_gate_rejects_nonfinancial_money_and_partial_magnitude(self) -> None:
        population = validate_claim_pair(
            "There are 145 million active mobile connections in the country.",
            "There are 152 million active mobile connections in the country.",
            "145 million",
            "152 million",
            "MONEY",
        )
        partial = validate_claim_pair(
            "The project costs between $1 million and $10 million.",
            "The project costs between $2 million and $10 million.",
            "$1",
            "$2",
            "MONEY",
        )
        valid = validate_claim_pair(
            "The company sought claims of up to dlrs 5 billion on Friday.",
            "The company sought claims of up to dlrs 6 billion on Friday.",
            "5 billion",
            "6 billion",
            "MONEY",
        )
        self.assertIn("original_entity_context_mismatch", population.reasons)
        self.assertIn("original_entity_context_mismatch", partial.reasons)
        self.assertTrue(valid.valid, valid.reasons)

    def test_context_gate_distinguishes_clock_time_from_ratio(self) -> None:
        ratio = validate_claim_pair(
            "The solution was prepared at a 1:10 v/v ratio before incubation.",
            "The solution was prepared at a 01:40 v/v ratio before incubation.",
            "1:10",
            "01:40",
            "TIME",
        )
        clock = validate_claim_pair(
            "The meeting begins at 10:30 AM in the main office.",
            "The meeting begins at 11:00 AM in the main office.",
            "10:30 AM",
            "11:00 AM",
            "TIME",
        )
        self.assertIn("original_entity_context_mismatch", ratio.reasons)
        self.assertTrue(clock.valid, clock.reasons)

    def test_contract_terms_require_contract_context_and_preserve_subtype(self) -> None:
        noncontract = validate_claim_pair(
            "The blinded assessor recorded each patient's treatment assignment.",
            "The blinded assessor recorded each patient's treatment delegation.",
            "assignment",
            "delegation",
            "CONTRACT_TERM",
        )
        replacement = perturb_entity_value("liability", "CONTRACT_TERM")
        valid = validate_claim_pair(
            "Under the credit agreement, liability is limited by this provision.",
            f"Under the credit agreement, {replacement} is limited by this provision.",
            "liability",
            replacement,
            "CONTRACT_TERM",
        )
        self.assertEqual(replacement, "indemnity")
        self.assertIn("original_entity_context_mismatch", noncontract.reasons)
        self.assertTrue(valid.valid, valid.reasons)

    def test_context_gate_rejects_partial_project_duration_and_numeric_component(self) -> None:
        cases = (
            (
                "Project Be Ready was consolidated in January.",
                "Project Atlas Ready was consolidated in January.",
                "Project Be",
                "Project Atlas",
                "PROJECT_NAME",
            ),
            (
                "After 6-8 hours, the culture medium was replaced.",
                "After 6-10 hours, the culture medium was replaced.",
                "8 hours",
                "10 hours",
                "DURATION",
            ),
            (
                "The company adopted update 2016-02 during the year.",
                "The company adopted update 2016-3 during the year.",
                "02",
                "3",
                "NUMERIC_VALUE",
            ),
        )
        for true_claim, counterfactual_claim, original, counterfactual, entity_type in cases:
            with self.subTest(entity_type=entity_type):
                result = validate_claim_pair(
                    true_claim,
                    counterfactual_claim,
                    original,
                    counterfactual,
                    entity_type,
                )
                self.assertIn("original_entity_context_mismatch", result.reasons)

    def test_completeness_gate_rejects_lowercase_fragment_email_list_and_quote(self) -> None:
        cases = (
            (
                "and Enron sought dlrs 5 billion on Friday.",
                "and Enron sought dlrs 6 billion on Friday.",
                "5 billion",
                "6 billion",
                "MONEY",
                "true_claim_fragment_surface",
            ),
            (
                "a@x.com, b@y.com, c@z.com received the $48 payment.",
                "a@x.com, b@y.com, c@z.com received the $50 payment.",
                "$48",
                "$50",
                "MONEY",
                "true_claim_email_list",
            ),
            (
                '"The office telephone number is 206-448-0884.',
                '"The office telephone number is 206-448-0913.',
                "206-448-0884",
                "206-448-0913",
                "PHONE",
                "true_claim_unbalanced_quote",
            ),
        )
        for true_claim, counterfactual_claim, original, counterfactual, entity_type, expected in cases:
            with self.subTest(expected=expected):
                result = validate_claim_pair(
                    true_claim,
                    counterfactual_claim,
                    original,
                    counterfactual,
                    entity_type,
                )
                self.assertIn(expected, result.reasons)

    def test_location_perturbation_preserves_article_class(self) -> None:
        counterfactual = perturb_entity_value("United States", "LOCATION")
        self.assertIn(counterfactual, {"United Kingdom", "United Arab Emirates", "Netherlands", "Philippines"})
        result = validate_claim_pair(
            "The company operates in the United States.",
            f"The company operates in the {counterfactual}.",
            "United States",
            counterfactual,
            "LOCATION",
        )
        self.assertTrue(result.valid, result.reasons)

    def test_semantic_gate_cannot_be_bypassed_by_coverage_fallback(self) -> None:
        extractor = EntityExtractor()
        incomplete = extractor.extract(
            "The company operates in the United States and plans to announ",
            max_entities=5,
            guarantee_min=1,
        )
        complete = extractor.extract(
            "The company operates in the United States and remains active.",
            max_entities=5,
            guarantee_min=1,
        )
        contaminated = extractor.extract(
            "Content-Transfer-Encoding: quoted-printable The payment was $48,720.",
            max_entities=5,
            guarantee_min=1,
        )
        self.assertEqual(incomplete, [])
        self.assertEqual(contaminated, [])
        self.assertTrue(complete)

    def test_extractor_rejects_version_number_nonfinancial_million_and_bad_delimiters(self) -> None:
        extractor = EntityExtractor()
        cases = (
            ("The analysis used R 3.4.2 for all statistical tests.", "3.4.2"),
            ("A maximum of 4.9 million shares may be issued under the plan.", "4.9 million"),
            ("The complaint (alleged damages of $48,720.", "$48,720"),
        )
        for text, rejected in cases:
            with self.subTest(rejected=rejected):
                entities = extractor.extract(text, max_entities=8, guarantee_min=0)
                self.assertFalse(any(row["text"] == rejected for row in entities))

    def test_query_pair_must_be_identical_outside_entity(self) -> None:
        valid = validate_query_pair(
            "Please verify that Delta paid $48,720 today.",
            "Please verify that Delta paid $51,156 today.",
            "$48,720",
            "$51,156",
        )
        invalid = validate_query_pair(
            "Please verify that Delta paid $48,720 today.",
            "Please urgently verify that Delta paid $51,156 today.",
            "$48,720",
            "$51,156",
        )
        self.assertTrue(valid.valid, valid.reasons)
        self.assertIn("query_pair_differs_outside_entity", invalid.reasons)

    def test_metadata_semantic_gate_rejects_domain_named_entity_false_positives(self) -> None:
        cases = (
            (
                "Related Transactions are described in Note 4.",
                "Morgan Lee are described in Note 4.",
                "Related Transactions",
                "Morgan Lee",
                "PERSON",
                "original_entity_type_mismatch",
            ),
            (
                "IGF-1 was measured after treatment.",
                "Ironwood Associates was measured after treatment.",
                "IGF-1",
                "Ironwood Associates",
                "ORG",
                "original_org_technical_or_biological_token",
            ),
            (
                "HMGB1 expression increased after treatment.",
                "New York expression increased after treatment.",
                "HMGB1",
                "New York",
                "LOCATION",
                "original_location_technical_or_named_method",
            ),
            (
                "The Newcastle-Ottawa Scale was used for assessment.",
                "The Paris was used for assessment.",
                "Newcastle-Ottawa Scale",
                "Paris",
                "LOCATION",
                "original_location_technical_or_named_method",
            ),
        )
        for true_claim, false_claim, original, counterfactual, kind, expected in cases:
            with self.subTest(original=original):
                result = validate_claim_pair(
                    true_claim,
                    false_claim,
                    original,
                    counterfactual,
                    kind,
                    entity_metadata={"candidate_sources": ["ner"]},
                )
                self.assertIn(expected, result.reasons)

    def test_metadata_semantic_gate_preserves_supported_named_entities(self) -> None:
        cases = (
            (
                "BOA was founded by Gary Hammerslag, a snowboarder and entrepreneur.",
                "BOA was founded by Dakota Reyes, a snowboarder and entrepreneur.",
                "Gary Hammerslag",
                "Dakota Reyes",
                "PERSON",
            ),
            (
                "The Italian Ministry of Health issued the guidance.",
                "The Cedarline Partners issued the guidance.",
                "Italian Ministry of Health",
                "Cedarline Partners",
                "ORG",
            ),
            (
                "The instrument was manufactured in San Diego, CA.",
                "The instrument was manufactured in Germany, CA.",
                "San Diego",
                "Germany",
                "LOCATION",
            ),
        )
        for true_claim, false_claim, original, counterfactual, kind in cases:
            with self.subTest(original=original):
                result = validate_claim_pair(
                    true_claim,
                    false_claim,
                    original,
                    counterfactual,
                    kind,
                    entity_metadata={"candidate_sources": ["ner"]},
                )
                self.assertTrue(result.valid, result.reasons)

    def test_metadata_semantic_gate_rejects_noncontract_assignment_context(self) -> None:
        result = validate_claim_pair(
            "The analysis required assignment of assets to reporting units.",
            "The analysis required delegation of assets to reporting units.",
            "assignment",
            "delegation",
            "CONTRACT_TERM",
            entity_metadata={"candidate_sources": ["regex"]},
        )
        self.assertIn(
            "original_contract_term_missing_strict_contract_context",
            result.reasons,
        )

    def test_completeness_gate_rejects_multiline_mail_and_truncated_enumeration(self) -> None:
        mail = "\n".join(
            [
                "Bret Scholtes@ENRON",
                "Boudreaux/HOU/ECT@ECT",
                "Benitez/Corp/Enron@Enron",
                "Curry/HOU/ECT@ECT",
                "Cash/HOU/ECT@ECT",
                "Poole/HOU/ECT@ECT",
                "The meeting about Project Crane is scheduled.",
                "Additional routing information follows.",
                "One",
                "Two",
                "Three",
                "Four",
                "Five.",
            ]
        )
        mail_result = validate_claim_pair(
            mail,
            mail.replace("Project Crane", "Program Meridian"),
            "Project Crane",
            "Program Meridian",
            "PROJECT_NAME",
        )
        enum_result = validate_claim_pair(
            "The weekly specials include November 20, 2001.\n\n1.",
            "The weekly specials include November 23, 2001.\n\n1.",
            "November 20, 2001",
            "November 23, 2001",
            "DATE",
        )
        self.assertIn("true_claim_abnormal_multiline_structure", mail_result.reasons)
        self.assertIn("true_claim_truncated", enum_result.reasons)


class ValidatorIntegrationTests(unittest.TestCase):
    def test_v6_3_rejects_counterfactual_found_in_another_source_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facts = root / "facts.jsonl"
            benchmark = root / "benchmark.jsonl"
            source_corpus = root / "processed.jsonl"
            output = root / "claims.jsonl"
            source_key = "mailbox::message-1"
            write_jsonl(
                [
                    {
                        "fact_id": "fact-1",
                        "audit_id": "audit-1",
                        "doc_id": "chunk-1",
                        "source_id": "message-1",
                        "source_key": source_key,
                        "dataset": "enron",
                        "group": "Eligibility_Candidate",
                        "object_entity": "Alice",
                        "entity_type": "PERSON",
                        "factual_claim": "Alice approved the plan.",
                        "supporting_sentence": "Alice approved the plan.",
                        "claim_entity_span": [0, 5],
                        "entity_metadata": {},
                    }
                ],
                facts,
            )
            write_jsonl(
                [
                    {
                        "audit_id": "audit-1",
                        "source_id": "message-1",
                        "source_path": "mailbox",
                        "source_key": source_key,
                        "text": "Alice approved the plan.",
                    }
                ],
                benchmark,
            )
            write_jsonl(
                [
                    {
                        "source_id": "message-1",
                        "source_path": "mailbox",
                        "source_key": source_key,
                        "text": "Alice approved the plan.",
                    },
                    {
                        "source_id": "message-1",
                        "source_path": "mailbox",
                        "source_key": source_key,
                        "text": "Bob joined the project later.",
                    },
                ],
                source_corpus,
            )
            metadata = SimpleNamespace(
                enabled=True,
                to_dict=lambda: {
                    "enabled": True,
                    "protocol": "test",
                    "models": [],
                },
            )
            with (
                patch(
                    "src.paired_claims.claim_generator.load_semantic_entity_resolver",
                    return_value=(object(), metadata),
                ),
                patch(
                    "src.paired_claims.claim_generator.perturb_entity_value",
                    return_value="Bob",
                ),
            ):
                manifest = generate_paired_claims_file(
                    facts,
                    output,
                    benchmark_path=benchmark,
                    source_corpus_path=source_corpus,
                    semantic_resolver_config={"enabled": True},
                    dataset="enron",
                    force=True,
                )
            self.assertEqual(0, manifest["pairs"])
            errors = list(read_jsonl(output.with_suffix(".errors.jsonl")))
            self.assertEqual(
                "counterfactual_entity_present_in_source",
                errors[0]["validation_failure_reason"],
            )

    def test_claim_generator_persists_validation_metadata_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            facts_path = root / "facts.jsonl"
            output_path = root / "claims.jsonl"
            write_jsonl(
                [
                    {
                        "fact_id": "f-good",
                        "audit_id": "a-good",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "object_entity": "$48,720",
                        "entity_type": "MONEY",
                        "factual_claim": "Delta Logistics paid $48,720 for the service.",
                    },
                    {
                        "fact_id": "f-bad",
                        "audit_id": "a-bad",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "object_entity": "If Arcosa",
                        "entity_type": "PERSON",
                        "factual_claim": "If Arcosa approves the request, processing will begin.",
                    },
                ],
                facts_path,
            )

            manifest = generate_paired_claims_file(facts_path, output_path, force=True)
            claims = list(read_jsonl(output_path))
            errors = list(read_jsonl(output_path.with_suffix(".errors.jsonl")))

            self.assertEqual(manifest["pairs"], 1)
            self.assertEqual(claims[0]["claim_validation_status"], "passed")
            self.assertEqual(claims[0]["claim_validator_version"], VALIDATOR_VERSION)
            self.assertEqual(errors[0]["validation_failure_reason"], "original_entity_type_mismatch")
            resumed = generate_paired_claims_file(facts_path, output_path, resume=True)
            self.assertTrue(resumed["skipped_existing"])
            with self.assertRaisesRegex(RuntimeError, "v19 validation protocol"):
                generate_paired_claims_file(
                    facts_path,
                    output_path,
                    max_pairs_per_fact=2,
                    resume=True,
                )

    def test_claim_generator_records_invalid_url_perturbation_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            facts_path = root / "facts.jsonl"
            output_path = root / "claims.jsonl"
            write_jsonl(
                [
                    {
                        "fact_id": "f-invalid-url",
                        "audit_id": "a-invalid-url",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "object_entity": "http://www.[company",
                        "entity_type": "URL",
                        "factual_claim": (
                            "The placeholder website is http://www.[company "
                            "in this template."
                        ),
                    }
                ],
                facts_path,
            )

            manifest = generate_paired_claims_file(
                facts_path,
                output_path,
                force=True,
            )
            errors = list(read_jsonl(output_path.with_suffix(".errors.jsonl")))

            self.assertEqual(manifest["pairs"], 0)
            self.assertEqual(manifest["errors"], 1)
            self.assertEqual(
                errors[0]["validation_failure_reason"],
                "counterfactual_generation_error",
            )

    def test_query_generator_writes_two_locally_validated_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims_path = root / "claims.jsonl"
            output_path = root / "queries.jsonl"
            write_jsonl(
                [
                    {
                        "pair_id": "p1",
                        "fact_id": "f1",
                        "audit_id": "a1",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "true_claim": "Delta Logistics paid $48,720 for the service.",
                        "counterfactual_claim": "Delta Logistics paid $51,156 for the service.",
                        "original_entity": "$48,720",
                        "counterfactual_entity": "$51,156",
                        "entity_type": "MONEY",
                        "perturbation_level": "light",
                        "context": "the service payment",
                    }
                ],
                claims_path,
            )

            manifest = generate_paired_queries_file(claims_path, output_path, force=True)
            rows = list(read_jsonl(output_path))

            self.assertEqual(manifest["queries"], 2)
            self.assertEqual(manifest["errors"], 0)
            self.assertTrue(all(row["query_pair_validation_status"] == "passed" for row in rows))
            self.assertTrue(all(" for for " not in row["query"] for row in rows))
            resumed = generate_paired_queries_file(claims_path, output_path, resume=True)
            self.assertTrue(resumed["skipped_existing"])
            with self.assertRaisesRegex(RuntimeError, "v19 validation protocol"):
                generate_paired_queries_file(
                    claims_path,
                    output_path,
                    query_types=["direct_verification"],
                    resume=True,
                )

    def test_claim_generator_uses_persisted_entity_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            facts_path = root / "facts.jsonl"
            output_path = root / "claims.jsonl"
            claim = "Update 2016-02 was adopted, and the review concluded in 2019."
            target_start = claim.rindex("2019")
            write_jsonl(
                [
                    {
                        "fact_id": "f-occurrence",
                        "audit_id": "a-occurrence",
                        "dataset": "toy",
                        "group": "KB_Member",
                        "object_entity": "2019",
                        "entity_type": "NUMERIC_VALUE",
                        "factual_claim": claim,
                        "claim_entity_span": [target_start, target_start + 4],
                    }
                ],
                facts_path,
            )
            manifest = generate_paired_claims_file(facts_path, output_path, force=True)
            row = list(read_jsonl(output_path))[0]
            self.assertEqual(manifest["pairs"], 1)
            self.assertIn("Update 2016-02 was adopted", row["counterfactual_claim"])
            self.assertIn("concluded in 2020", row["counterfactual_claim"])


if __name__ == "__main__":
    unittest.main()
