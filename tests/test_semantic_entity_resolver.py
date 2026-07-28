from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.attack.semantic_entity_resolver import (
    AUDIT_CONSENSUS_MODE,
    LEGACY_CONSENSUS_PROTOCOL,
    PRECISION_CASCADE_MODE,
    SEMANTIC_RESOLVER_PROTOCOL,
    SEMANTIC_SCHEMA_SHA256,
    SEMANTIC_TARGET_TYPES,
    SemanticEntityResolver,
    SemanticPrediction,
    SemanticResolverProtocolError,
    _release_cuda_cache,
    load_semantic_entity_resolver,
    semantic_thresholds_sha256,
)


class FakeBackend:
    def __init__(
        self,
        model_id: str,
        role: str,
        predictions: list[tuple[str, int, int, float]],
    ) -> None:
        self.model_id = model_id
        self.role = role
        self._predictions = predictions
        self.calls = 0
        self.texts: list[str] = []

    def predict(self, text, schema):
        self.calls += 1
        self.texts.append(text)
        return [
            SemanticPrediction(
                model_id=self.model_id,
                role=self.role,
                label=label,
                text=text[start:end],
                start=start,
                end=end,
                score=score,
            )
            for label, start, end, score in self._predictions
            if label in schema
        ]


class AdaptiveOOMBackend:
    def __init__(
        self,
        *,
        maximum_batch_size: int,
        always_oom: bool = False,
    ) -> None:
        self.model_id = "large"
        self.role = "gliner2_large"
        self.maximum_batch_size = maximum_batch_size
        self.always_oom = always_oom
        self.batch_sizes: list[int] = []

    def predict(self, text, schema):
        raise AssertionError("batch backend should not use predict")

    def predict_batch(self, texts, schema, *, batch_size):
        self.batch_sizes.append(len(texts))
        if self.always_oom or len(texts) > self.maximum_batch_size:
            raise RuntimeError("CUDA out of memory")
        return [[] for _ in texts]


def _candidate(text: str, entity_type: str, start: int = 0, end: int | None = None):
    end = len(text) if end is None else end
    return {
        "text": text[start:end],
        "type": entity_type,
        "start": start,
        "end": end,
    }


def _complete_type_thresholds(
    target: float = 0.70,
    margin: float = 0.15,
):
    return {
        entity_type: {
            "min_target_confidence": target,
            "min_confidence_margin": margin,
        }
        for entity_type in sorted(SEMANTIC_TARGET_TYPES)
    }


class SemanticEntityResolverTests(unittest.TestCase):
    def _resolver(
        self,
        predictions_a,
        predictions_b,
        predictions_c=(),
        *,
        biomedical_predictions=(),
    ):
        return SemanticEntityResolver(
            [
                FakeBackend("base", "gliner2_base", list(predictions_a)),
                FakeBackend("large", "gliner2_large", list(predictions_b)),
                FakeBackend("trf", "spacy_transformer", list(predictions_c)),
            ],
            biomedical_veto=FakeBackend(
                "biomed",
                "biomedical_veto",
                list(biomedical_predictions),
            ),
            min_target_confidence=0.70,
            min_confidence_margin=0.15,
            min_consensus_votes=2,
            min_boundary_votes=2,
            biomedical_veto_threshold=0.70,
            execution_mode=AUDIT_CONSENSUS_MODE,
            protocol=LEGACY_CONSENSUS_PROTOCOL,
        )

    def _cascade(
        self,
        predictions,
        *,
        biomedical_predictions=(),
    ):
        large = FakeBackend(
            "large",
            "gliner2_large",
            list(predictions),
        )
        biomed = FakeBackend(
            "biomed",
            "biomedical_veto",
            list(biomedical_predictions),
        )
        resolver = SemanticEntityResolver(
            [large],
            biomedical_veto=biomed,
            min_target_confidence=0.70,
            min_confidence_margin=0.15,
            min_consensus_votes=1,
            min_boundary_votes=1,
            biomedical_veto_threshold=0.70,
            execution_mode=PRECISION_CASCADE_MODE,
            protocol=SEMANTIC_RESOLVER_PROTOCOL,
        )
        return resolver, large, biomed

    def test_precision_cascade_accepts_one_large_prediction(self):
        text = "Acme Corp filed the report."
        end = len("Acme Corp")
        resolver, large, biomed = self._cascade(
            [("ORG", 0, end, 0.94)]
        )

        resolution = resolver.resolve_candidate(
            text,
            _candidate(text, "ORG", 0, end),
            dataset="edgar",
        )

        self.assertTrue(resolution.accepted)
        self.assertEqual(1, resolution.target_votes)
        self.assertEqual(1, large.calls)
        self.assertEqual(0, biomed.calls)

    def test_precision_cascade_uses_entity_type_thresholds(self):
        text = "Widget launched Project Alpha."
        product_end = len("Widget")
        project_start = text.index("Project Alpha")
        project_end = project_start + len("Project Alpha")
        large = FakeBackend(
            "large",
            "gliner2_large",
            [
                ("PRODUCT", 0, product_end, 0.70),
                ("PROJECT_NAME", project_start, project_end, 0.90),
            ],
        )
        resolver = SemanticEntityResolver(
            [large],
            min_target_confidence=0.95,
            min_confidence_margin=0.40,
            thresholds_by_entity_type={
                "PRODUCT": {
                    "min_target_confidence": 0.60,
                    "min_confidence_margin": 0.40,
                },
                "PROJECT_NAME": {
                    "min_target_confidence": 0.95,
                    "min_confidence_margin": 0.40,
                },
            },
        )

        product, project = resolver.resolve_candidates(
            text,
            [
                _candidate(text, "PRODUCT", 0, product_end),
                _candidate(
                    text,
                    "PROJECT_NAME",
                    project_start,
                    project_end,
                ),
            ],
            dataset="edgar",
        )

        self.assertTrue(product and product.accepted)
        self.assertFalse(project and project.accepted)

    def test_pubmed_biomedical_veto_only_receives_candidate_sentence(self):
        text = "Unrelated introduction. HEK cells expressed DC-SIGNR. Final note."
        start = text.index("HEK")
        end = start + len("HEK")
        resolver, _, biomed = self._cascade(
            [("ORG", start, end, 0.94)],
            biomedical_predictions=[
                ("CELL_LINE_OR_PROTEIN", 1, 4, 0.97)
            ],
        )

        resolution = resolver.resolve_candidate(
            text,
            _candidate(text, "ORG", start, end),
            dataset="pubmed",
        )

        self.assertFalse(resolution.accepted)
        self.assertEqual(1, biomed.calls)
        self.assertEqual([" HEK cells expressed DC-SIGNR."], biomed.texts)
        self.assertIn(
            "semantic_pubmed_biomedical_veto",
            resolution.failure_reasons,
        )

    def test_pubmed_precomputed_large_predictions_still_run_candidate_veto(self):
        text = "Unrelated introduction. HEK cells expressed DC-SIGNR. Final note."
        start = text.index("HEK")
        end = start + len("HEK")
        resolver, large, biomed = self._cascade(
            [("ORG", start, end, 0.94)],
            biomedical_predictions=[
                ("CELL_LINE_OR_PROTEIN", 1, 4, 0.97)
            ],
        )
        precomputed = resolver.predict_batch(
            [text],
            dataset="pubmed",
            batch_size=1,
        )[0]

        _, resolutions = resolver.resolve_and_propose(
            text,
            [_candidate(text, "ORG", start, end)],
            dataset="pubmed",
            precomputed_predictions=precomputed,
        )

        self.assertEqual(1, large.calls)
        self.assertEqual(1, biomed.calls)
        self.assertFalse(resolutions[0] and resolutions[0].accepted)
        self.assertEqual([" HEK cells expressed DC-SIGNR."], biomed.texts)

    def test_pubmed_without_semantic_candidate_does_not_call_biomed(self):
        text = "The value was $42."
        resolver, _, biomed = self._cascade([])

        candidates, resolutions = resolver.resolve_and_propose(
            text,
            [_candidate(text, "MONEY", text.index("$42"), text.index("$42") + 3)],
            dataset="pubmed",
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual([None], resolutions)
        self.assertEqual(0, biomed.calls)

    def test_all_six_semantic_types_remain_eligible(self):
        text = "Alpha Beta"
        for entity_type in sorted(SEMANTIC_TARGET_TYPES):
            with self.subTest(entity_type=entity_type):
                predictions = [(entity_type, 0, len(text), 0.92)]
                resolution = self._resolver(predictions, predictions).resolve_candidate(
                    text,
                    _candidate(text, entity_type),
                    dataset="enron",
                )
                self.assertTrue(resolution.accepted)
                self.assertEqual(entity_type, resolution.entity_type)

    def test_consensus_corrects_short_boundary(self):
        text = "Worlds Online announced a new service."
        full_end = len("Worlds Online")
        predictions = [("ORG", 0, full_end, 0.94)]
        resolution = self._resolver(predictions, predictions).resolve_candidate(
            text,
            _candidate(text, "ORG", start=len("Worlds "), end=full_end),
            dataset="enron",
        )
        self.assertTrue(resolution.accepted)
        self.assertEqual("Worlds Online", resolution.text)
        self.assertEqual((0, full_end), (resolution.start, resolution.end))
        self.assertEqual(2, resolution.boundary_votes)

    def test_strong_competing_type_rejects_known_bad_org(self):
        text = "Black-Scholes was used to value the options."
        end = len("Black-Scholes")
        base = [
            ("ORG", 0, end, 0.88),
            ("METHOD_OR_ALGORITHM", 0, end, 0.94),
        ]
        large = [("ORG", 0, end, 0.90)]
        resolution = self._resolver(base, large).resolve_candidate(
            text,
            _candidate(text, "ORG", 0, end),
            dataset="edgar",
        )
        self.assertFalse(resolution.accepted)
        self.assertIn(
            "semantic_competing_type_detected",
            resolution.failure_reasons,
        )

    def test_pubmed_biomedical_prediction_is_a_hard_veto(self):
        text = "HEK cells expressed DC-SIGNR."
        end = len("HEK")
        target = [("ORG", 0, end, 0.90)]
        resolution = self._resolver(
            target,
            target,
            biomedical_predictions=[("CELL_LINE_OR_PROTEIN", 0, end, 0.97)],
        ).resolve_candidate(
            text,
            _candidate(text, "ORG", 0, end),
            dataset="pubmed",
        )
        self.assertFalse(resolution.accepted)
        self.assertIn(
            "semantic_pubmed_biomedical_veto",
            resolution.failure_reasons,
        )

    def test_one_vote_cannot_enter_formal_claims(self):
        text = "Acme Corp filed the report."
        end = len("Acme Corp")
        resolution = self._resolver(
            [("ORG", 0, end, 0.95)],
            [],
        ).resolve_candidate(
            text,
            _candidate(text, "ORG", 0, end),
            dataset="edgar",
        )
        self.assertFalse(resolution.accepted)
        self.assertIn(
            "semantic_target_consensus_missing",
            resolution.failure_reasons,
        )
        self.assertIn(
            "semantic_boundary_consensus_missing",
            resolution.failure_reasons,
        )

    def test_each_model_runs_once_for_multiple_candidates(self):
        text = "Alice joined Acme Corp."
        base = FakeBackend(
            "base",
            "gliner2_base",
            [("PERSON", 0, 5, 0.92), ("ORG", 13, 22, 0.93)],
        )
        large = FakeBackend(
            "large",
            "gliner2_large",
            [("PERSON", 0, 5, 0.91), ("ORG", 13, 22, 0.94)],
        )
        trf = FakeBackend("trf", "spacy_transformer", [])
        resolver = SemanticEntityResolver(
            [base, large, trf],
            min_consensus_votes=2,
            min_boundary_votes=2,
            execution_mode=AUDIT_CONSENSUS_MODE,
            protocol=LEGACY_CONSENSUS_PROTOCOL,
        )
        results = resolver.resolve_candidates(
            text,
            [
                _candidate(text, "PERSON", 0, 5),
                _candidate(text, "ORG", 13, 22),
            ],
            dataset="enron",
        )
        self.assertTrue(all(result and result.accepted for result in results))
        self.assertEqual(1, base.calls)
        self.assertEqual(1, large.calls)
        self.assertEqual(1, trf.calls)

    def test_consensus_predictions_can_propose_new_candidate(self):
        text = "The PEP System is available through the portal."
        start = text.index("PEP System")
        end = start + len("PEP System")
        target = [("PRODUCT", start, end, 0.91)]
        resolver = self._resolver(target, target)
        candidates, resolutions = resolver.resolve_and_propose(
            text,
            [],
            dataset="enron",
        )
        self.assertEqual(1, len(candidates))
        self.assertTrue(candidates[0]["semantic_proposal"])
        self.assertEqual("PRODUCT", candidates[0]["type"])
        self.assertTrue(resolutions[0] and resolutions[0].accepted)

    def test_batch_predictions_are_reused_without_extra_model_calls(self):
        text = "Acme Corp"
        end = len(text)
        base = FakeBackend(
            "base",
            "gliner2_base",
            [("ORG", 0, end, 0.92)],
        )
        large = FakeBackend(
            "large",
            "gliner2_large",
            [("ORG", 0, end, 0.93)],
        )
        trf = FakeBackend("trf", "spacy_transformer", [])
        resolver = SemanticEntityResolver(
            [base, large, trf],
            min_consensus_votes=2,
            min_boundary_votes=2,
            execution_mode=AUDIT_CONSENSUS_MODE,
            protocol=LEGACY_CONSENSUS_PROTOCOL,
        )
        predictions = resolver.predict_batch(
            [text, text],
            dataset="enron",
            batch_size=2,
        )
        outputs = [
            resolver.resolve_and_propose(
                text,
                [],
                dataset="enron",
                precomputed_predictions=item,
            )
            for item in predictions
        ]
        self.assertTrue(
            all(resolutions[0] and resolutions[0].accepted for _, resolutions in outputs)
        )
        self.assertEqual(2, base.calls)
        self.assertEqual(2, large.calls)
        self.assertEqual(2, trf.calls)

    def test_counterfactual_candidate_reuses_precomputed_batch_predictions(self):
        text = "Acme Corp"
        end = len(text)
        base = FakeBackend(
            "base",
            "gliner2_base",
            [("ORG", 0, end, 0.92)],
        )
        large = FakeBackend(
            "large",
            "gliner2_large",
            [("ORG", 0, end, 0.93)],
        )
        trf = FakeBackend("trf", "spacy_transformer", [])
        resolver = SemanticEntityResolver(
            [base, large, trf],
            min_consensus_votes=2,
            min_boundary_votes=2,
            execution_mode=AUDIT_CONSENSUS_MODE,
            protocol=LEGACY_CONSENSUS_PROTOCOL,
        )
        precomputed = resolver.predict_batch(
            [text],
            dataset="enron",
            batch_size=1,
        )[0]
        resolution = resolver.resolve_candidate(
            text,
            _candidate(text, "ORG"),
            dataset="enron",
            precomputed_predictions=precomputed,
        )
        self.assertTrue(resolution.accepted)
        self.assertEqual(1, base.calls)
        self.assertEqual(1, large.calls)
        self.assertEqual(1, trf.calls)

    def test_cuda_oom_recursively_splits_8_to_4_to_2_to_1(self):
        backend = AdaptiveOOMBackend(maximum_batch_size=1)
        resolver = SemanticEntityResolver(
            [backend],
            execution_mode=PRECISION_CASCADE_MODE,
        )
        outputs = resolver.predict_batch(
            [f"text-{index}" for index in range(8)],
            dataset="enron",
            batch_size=8,
        )
        self.assertEqual(len(outputs), 8)
        self.assertTrue({8, 4, 2, 1}.issubset(backend.batch_sizes))
        stats = resolver.prediction_runtime_stats()
        self.assertGreater(stats["oom_retry_count"], 0)
        self.assertEqual(stats["successful_batch_sizes"], {"1": 8})

    def test_batch_one_cuda_oom_fails_closed(self):
        backend = AdaptiveOOMBackend(
            maximum_batch_size=1,
            always_oom=True,
        )
        resolver = SemanticEntityResolver(
            [backend],
            execution_mode=PRECISION_CASCADE_MODE,
        )
        with self.assertRaisesRegex(
            SemanticResolverProtocolError,
            "semantic_cuda_oom_batch_one",
        ):
            resolver.predict_batch(
                ["only-text"],
                dataset="enron",
                batch_size=8,
            )

    def test_cuda_cache_cleanup_error_does_not_mask_oom_retry(self):
        from unittest.mock import patch

        with (
            patch("torch.cuda.is_available", return_value=True),
            patch(
                "torch.cuda.empty_cache",
                side_effect=RuntimeError("asynchronous CUDA OOM"),
            ),
        ):
            _release_cuda_cache()

    def test_prediction_cache_restores_order_and_rejects_identity_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "wave.sqlite3"
            identity = {
                "dataset": "enron",
                "model_lock_sha256": "model-a",
                "schema_sha256": "schema-a",
                "thresholds_sha256": "threshold-a",
                "precision": "fp16",
            }
            backend = AdaptiveOOMBackend(maximum_batch_size=8)
            resolver = SemanticEntityResolver(
                [backend],
                execution_mode=PRECISION_CASCADE_MODE,
            )
            resolver.configure_prediction_cache(
                cache_path,
                identity=identity,
            )
            texts = ["first", "second", "first"]
            first = resolver.predict_batch(
                texts,
                dataset="enron",
                batch_size=8,
            )
            resolver.close_prediction_cache()
            self.assertEqual(len(first), 3)
            self.assertEqual(backend.batch_sizes, [2])

            cached_backend = AdaptiveOOMBackend(
                maximum_batch_size=0,
                always_oom=True,
            )
            cached_resolver = SemanticEntityResolver(
                [cached_backend],
                execution_mode=PRECISION_CASCADE_MODE,
            )
            cached_resolver.configure_prediction_cache(
                cache_path,
                identity=identity,
            )
            restored = cached_resolver.predict_batch(
                texts,
                dataset="enron",
                batch_size=8,
            )
            self.assertEqual(restored, first)
            self.assertEqual(cached_backend.batch_sizes, [])
            cached_resolver.close_prediction_cache()

            drifted = SemanticEntityResolver(
                [backend],
                execution_mode=PRECISION_CASCADE_MODE,
            )
            with self.assertRaisesRegex(
                SemanticResolverProtocolError,
                "semantic_prediction_cache_identity_mismatch",
            ):
                drifted.configure_prediction_cache(
                    cache_path,
                    identity={**identity, "thresholds_sha256": "drift"},
                )

    def test_prediction_cache_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "corrupt.sqlite3"
            cache_path.write_bytes(b"not a sqlite database")
            resolver = SemanticEntityResolver(
                [AdaptiveOOMBackend(maximum_batch_size=8)],
                execution_mode=PRECISION_CASCADE_MODE,
            )
            with self.assertRaisesRegex(
                SemanticResolverProtocolError,
                "semantic_prediction_cache_corrupt",
            ):
                resolver.configure_prediction_cache(
                    cache_path,
                    identity={"dataset": "enron"},
                )


class SemanticResolverLoaderTests(unittest.TestCase):
    def _config(
        self,
        include_biomed: bool = False,
        *,
        audit_mode: bool = False,
    ):
        models = [
            {"model_id": "base", "backend": "injected", "role": "gliner2_base"},
            {"model_id": "large", "backend": "injected", "role": "gliner2_large"},
            {"model_id": "trf", "backend": "injected", "role": "spacy_transformer"},
        ]
        if include_biomed:
            models.append(
                {
                    "model_id": "biomed",
                    "backend": "injected",
                    "role": "biomedical_veto",
                }
            )
        return {
            "enabled": True,
            "protocol": (
                LEGACY_CONSENSUS_PROTOCOL
                if audit_mode
                else SEMANTIC_RESOLVER_PROTOCOL
            ),
            "execution_mode": (
                AUDIT_CONSENSUS_MODE
                if audit_mode
                else PRECISION_CASCADE_MODE
            ),
            "primary_model_role": "gliner2_large",
            "biomedical_candidate_only": not audit_mode,
            "calibration_mode": not audit_mode,
            "schema_sha256": SEMANTIC_SCHEMA_SHA256,
            "local_files_only": True,
            "models": models,
        }

    def _injected(self, include_biomed: bool = False):
        backends = {
            "base": FakeBackend("base", "gliner2_base", []),
            "large": FakeBackend("large", "gliner2_large", []),
            "trf": FakeBackend("trf", "spacy_transformer", []),
        }
        if include_biomed:
            backends["biomed"] = FakeBackend(
                "biomed",
                "biomedical_veto",
                [],
            )
        return backends

    def test_loader_accepts_complete_injected_lock_for_tests(self):
        backends = self._injected()
        resolver, metadata = load_semantic_entity_resolver(
            self._config(),
            dataset="enron",
            injected_backends=backends,
        )
        self.assertIsNotNone(resolver)
        self.assertTrue(metadata.enabled)
        self.assertEqual(SEMANTIC_SCHEMA_SHA256, metadata.schema_sha256)
        self.assertEqual(["gliner2_large"], [model["role"] for model in metadata.models])
        self.assertEqual(
            ("gliner2_base", "spacy_transformer"),
            metadata.skipped_model_roles,
        )
        assert resolver is not None
        resolver.resolve_candidates(
            "Acme Corp filed the report.",
            [_candidate("Acme Corp filed the report.", "ORG", 0, 9)],
            dataset="enron",
        )
        self.assertEqual(0, backends["base"].calls)
        self.assertEqual(1, backends["large"].calls)
        self.assertEqual(0, backends["trf"].calls)

    def test_loader_fails_closed_on_schema_drift(self):
        config = self._config()
        config["schema_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            SemanticResolverProtocolError,
            "semantic_schema_hash_mismatch",
        ):
            load_semantic_entity_resolver(
                config,
                dataset="enron",
                injected_backends=self._injected(),
            )

    def test_loader_fails_closed_on_model_hash_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "model"
            model_dir.mkdir()
            (model_dir / "weights.bin").write_bytes(b"actual model bytes")
            config = self._config()
            for model in config["models"]:
                model.update(
                    {
                        "backend": "gliner2",
                        "local_path": "model",
                        "files_sha256": {"weights.bin": "0" * 64},
                    }
                )
            with self.assertRaisesRegex(
                SemanticResolverProtocolError,
                "semantic_model_hash_mismatch",
            ):
                load_semantic_entity_resolver(
                    config,
                    dataset="enron",
                    workspace_root=root,
                )

    def test_pubmed_loader_requires_biomedical_veto(self):
        with self.assertRaisesRegex(
            SemanticResolverProtocolError,
            "semantic_biomedical_veto_missing",
        ):
            load_semantic_entity_resolver(
                self._config(),
                dataset="pubmed",
                injected_backends=self._injected(),
            )

    def test_pubmed_loader_accepts_biomedical_veto(self):
        resolver, metadata = load_semantic_entity_resolver(
            self._config(include_biomed=True),
            dataset="pubmed",
            injected_backends=self._injected(include_biomed=True),
        )
        self.assertIsNotNone(resolver)
        self.assertEqual(
            ["gliner2_large", "biomedical_veto"],
            [model["role"] for model in metadata.models],
        )

    def test_audit_mode_explicitly_loads_all_three_voters(self):
        backends = self._injected()
        resolver, metadata = load_semantic_entity_resolver(
            self._config(audit_mode=True),
            dataset="enron",
            injected_backends=backends,
        )

        self.assertIsNotNone(resolver)
        self.assertEqual(AUDIT_CONSENSUS_MODE, metadata.execution_mode)
        self.assertEqual(
            ["gliner2_base", "gliner2_large", "spacy_transformer"],
            [model["role"] for model in metadata.models],
        )

    def test_formal_threshold_hash_drift_fails_closed(self):
        config = self._config()
        config.pop("calibration_mode")
        config["thresholds_frozen"] = True
        config["thresholds_by_entity_type"] = _complete_type_thresholds()
        config["thresholds_sha256"] = "0" * 64

        with self.assertRaisesRegex(
            SemanticResolverProtocolError,
            "semantic_thresholds_hash_mismatch",
        ):
            load_semantic_entity_resolver(
                config,
                dataset="enron",
                injected_backends=self._injected(),
            )

    def test_formal_threshold_hash_accepts_exact_decision_surface(self):
        config = self._config()
        config.pop("calibration_mode")
        config["thresholds_frozen"] = True
        config["thresholds_by_entity_type"] = _complete_type_thresholds()
        config["thresholds_sha256"] = semantic_thresholds_sha256(
            min_target_confidence=0.70,
            min_confidence_margin=0.15,
            min_consensus_votes=1,
            min_boundary_votes=1,
            biomedical_veto_threshold=0.70,
            overlap_threshold=0.80,
            thresholds_by_entity_type=config["thresholds_by_entity_type"],
        )

        resolver, metadata = load_semantic_entity_resolver(
            config,
            dataset="enron",
            injected_backends=self._injected(),
        )

        self.assertIsNotNone(resolver)
        self.assertEqual(config["thresholds_sha256"], metadata.thresholds_sha256)
        self.assertEqual(
            config["thresholds_by_entity_type"],
            metadata.thresholds_by_entity_type,
        )

    def test_formal_entity_type_thresholds_must_cover_all_six_types(self):
        config = self._config()
        config.pop("calibration_mode")
        config["thresholds_frozen"] = True
        config["thresholds_by_entity_type"] = {
            "PRODUCT": {
                "min_target_confidence": 0.60,
                "min_confidence_margin": 0.40,
            }
        }
        config["thresholds_sha256"] = semantic_thresholds_sha256(
            min_target_confidence=0.70,
            min_confidence_margin=0.15,
            min_consensus_votes=1,
            min_boundary_votes=1,
            biomedical_veto_threshold=0.70,
            overlap_threshold=0.80,
            thresholds_by_entity_type=config["thresholds_by_entity_type"],
        )

        with self.assertRaisesRegex(
            SemanticResolverProtocolError,
            "semantic_entity_type_thresholds_incomplete",
        ):
            load_semantic_entity_resolver(
                config,
                dataset="enron",
                injected_backends=self._injected(),
            )


if __name__ == "__main__":
    unittest.main()
