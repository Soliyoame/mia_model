from __future__ import annotations

import unittest

from src.attack.entity_extractor import EntityExtractor


class _FakeEntity:
    def __init__(self, text: str, label: str, start: int) -> None:
        self.text = text
        self.label_ = label
        self.start_char = start
        self.end_char = start + len(text)
        self.score = 1.0


class _FakeSentence:
    def __init__(self, text: str, start: int, end: int) -> None:
        self.text = text[start:end]
        self.start_char = start
        self.end_char = end


class _FakeDoc:
    def __init__(self, text: str, labels: dict[str, str]) -> None:
        self.ents = [
            _FakeEntity(value, label, text.index(value))
            for value, label in labels.items()
            if value in text
        ]
        self.sents = [_FakeSentence(text, 0, len(text))]


class _FakeLocalNer:
    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = labels

    def __call__(self, text: str) -> _FakeDoc:
        return _FakeDoc(text, self.labels)


class LocalNerEntityExtractorTests(unittest.TestCase):
    def test_exact_org_evidence_corrects_person_regex_candidate(self) -> None:
        extractor = EntityExtractor(
            ner_model=_FakeLocalNer({"Internal Control": "ORG"}),
            ner_model_name="fake-local-ner",
        )
        entities = extractor.extract(
            "Internal Control was evaluated under the reporting framework.",
            max_entities=5,
            guarantee_min=0,
        )
        self.assertFalse(
            any(row["type"] == "PERSON" and row["text"] == "Internal Control" for row in entities)
        )

    def test_covering_org_evidence_rejects_location_subspan(self) -> None:
        extractor = EntityExtractor(
            ner_model=_FakeLocalNer({"Texas Instruments": "ORG"}),
            ner_model_name="fake-local-ner",
        )
        entities = extractor.extract(
            "Texas Instruments reported revenue for the quarter.",
            max_entities=5,
            guarantee_min=0,
        )
        self.assertFalse(any(row["type"] == "LOCATION" and row["text"] == "Texas" for row in entities))

    def test_person_requires_exact_local_ner_support(self) -> None:
        supported = EntityExtractor(
            ner_model=_FakeLocalNer({"Gary Spraggins": "PERSON"}),
            ner_model_name="fake-local-ner",
        ).extract(
            "Gary Spraggins signed the agreement for the company.",
            max_entities=5,
            guarantee_min=0,
        )
        unsupported = EntityExtractor(
            ner_model=_FakeLocalNer({}),
            ner_model_name="fake-local-ner",
        ).extract(
            "Average Rgyration was reported in the analysis.",
            max_entities=5,
            guarantee_min=0,
        )
        self.assertTrue(any(row["type"] == "PERSON" and row["text"] == "Gary Spraggins" for row in supported))
        self.assertFalse(any(row["type"] == "PERSON" for row in unsupported))

    def test_broader_local_ner_span_replaces_incomplete_regex_entity(self) -> None:
        extractor = EntityExtractor(
            ner_model=_FakeLocalNer(
                {"São Paulo State Epidemiological Health Department": "ORG"}
            ),
            ner_model_name="fake-local-ner",
        )
        entities = extractor.extract(
            "São Paulo State Epidemiological Health Department received the notification.",
            max_entities=5,
            guarantee_min=0,
        )
        self.assertTrue(
            any(
                row["type"] == "ORG"
                and row["text"] == "São Paulo State Epidemiological Health Department"
                for row in entities
            )
        )
        self.assertFalse(
            any(
                row["text"] == "Paulo State Epidemiological Health Department"
                for row in entities
            )
        )

    def test_local_ner_does_not_create_domain_entities(self) -> None:
        extractor = EntityExtractor(
            ner_model=_FakeLocalNer({"-7.25": "PRODUCT", "Table 1": "LAW"}),
            ner_model_name="fake-local-ner",
        )
        entities = extractor.extract(
            "The binding energy was -7.25 kcal/mol and the result appears in Table 1.",
            max_entities=5,
            guarantee_min=0,
        )
        self.assertFalse(any(row["type"] in {"PRODUCT", "CONTRACT_TERM"} for row in entities))

    def test_precomputed_ner_output_matches_per_document_call(self) -> None:
        text = "Gary Spraggins signed the agreement for Texas Instruments."
        model = _FakeLocalNer(
            {
                "Gary Spraggins": "PERSON",
                "Texas Instruments": "ORG",
            }
        )
        extractor = EntityExtractor(
            ner_model=model,
            ner_model_name="fake-local-ner",
        )

        per_document = extractor.extract(text, max_entities=5, guarantee_min=0)
        precomputed = extractor.extract(
            text,
            max_entities=5,
            guarantee_min=0,
            ner_output=model(text),
        )

        self.assertEqual(per_document, precomputed)


if __name__ == "__main__":
    unittest.main()
