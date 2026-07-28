from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.attack.semantic_entity_resolver import (
    PRECISION_CASCADE_MODE,
    SEMANTIC_RESOLVER_PROTOCOL,
    SEMANTIC_SCHEMA_SHA256,
    SemanticResolverMetadata,
    SemanticResolverProtocolError,
    resolve_semantic_runtime,
)
from src.paired_claims.claim_generator import load_complete_source_lookup
from src.paired_claims.claim_generator import generate_paired_claims_file
from src.fact_extraction.fact_extractor import extract_facts_file
from src.prepare.eligibility_scan import (
    ATTACK_FIRST_RC2_RELEASE_QUERY_ELIGIBILITY_PROTOCOL,
    ATTACK_FIRST_RC2_RELEASE_SCAN_PROTOCOL,
    BUDGET6_RELEASE_QUERY_ELIGIBILITY_PROTOCOL,
    BUDGET6_RELEASE_SCAN_PROTOCOL,
    QUERY_ELIGIBILITY_PROTOCOL,
    SCAN_PROTOCOL,
    V4_QUERY_ELIGIBILITY_PROTOCOL,
    V4_SCAN_PROTOCOL,
    _iter_wave_rows,
    _promote_staged_file,
    _validate_scan_config,
    configured_release_protocol,
    execute_wave_schedule,
    freeze_candidate_pool_prefix,
    freeze_source_plan,
    load_latest_checkpoint,
    rank_source_universe_by_local_quality,
    validate_fixed_budget_query_rows,
    validate_formal_eligibility_manifest,
    write_checkpoint,
)
from src.prepare.splitter import deduplicate_complete_sources
from src.utils.hash import sha256_file, sha256_obj
from src.utils.io import read_json, write_json, write_jsonl


def _processed_row(
    source_id: str,
    doc_id: str,
    text: str,
    text_hash: str,
    *,
    group: str = "ignored",
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_path": "",
        "doc_id": doc_id,
        "text": text,
        "text_hash": text_hash,
        "group": group,
        "metadata": {"entity_count": 3},
    }


class PrecisionCascadeSourcePlanTests(unittest.TestCase):
    def test_release_protocol_overrides_scan_protocol(self) -> None:
        self.assertEqual(
            configured_release_protocol(
                {
                    "protocol": "upstream-v3",
                    "release_protocol": "release-v1",
                }
            ),
            "release-v1",
        )
        self.assertEqual(
            configured_release_protocol({"protocol": "upstream-v3"}),
            "upstream-v3",
        )

    def test_source_dedup_order_and_probe_ignore_labels_and_input_order(
        self,
    ) -> None:
        rows = [
            _processed_row("A", "a1", "alpha", "shared", group="KB_Member"),
            _processed_row("B", "b1", "beta", "shared", group="Reserve"),
            _processed_row("C", "c1", "gamma", "unique", group="Other"),
        ]
        deduplicated, stats = deduplicate_complete_sources(rows)
        self.assertEqual(stats["dropped_cross_source_duplicates"], 1)

        order_a, candidates_a, _ = freeze_source_plan(
            deduplicated,
            "edgar",
            selection_seed=42,
            max_chunks_per_source=5,
        )
        relabelled = [
            {**row, "group": "adversarial_label"}
            for row in reversed(rows)
        ]
        deduplicated_b, _ = deduplicate_complete_sources(relabelled)
        order_b, candidates_b, _ = freeze_source_plan(
            deduplicated_b,
            "edgar",
            selection_seed=42,
            max_chunks_per_source=5,
        )

        self.assertEqual(order_a, order_b)
        self.assertEqual(
            [row["audit_id"] for row in candidates_a],
            [row["audit_id"] for row in candidates_b],
        )
        self.assertNotIn("::B", order_a)
        self.assertTrue(all(row["group"] == "Eligibility_Candidate" for row in candidates_a))

    def test_scan_config_accepts_only_preregistered_caps(self) -> None:
        config = {
            "protocol": SCAN_PROTOCOL,
            "selection_seed": 42,
            "wave_size": 250,
            "candidate_pool_multiplier": 2,
            "candidate_pool_target_sources": 2500,
            "candidate_pool_shortfall_policy": (
                "use_complete_source_universe"
            ),
            "scan_full_candidate_pool": True,
            "target_query_eligible_sources": 1250,
            "required_formal_sources": 1250,
            "max_chunks_per_source": 5,
            "fallback_chunk_caps": [8, 12],
            "minimum_valid_claims": 3,
            "minimum_stealth_pairs": 3,
            "deduplicate_complete_sources": True,
        }
        selected = _validate_scan_config(config, selected_cap=8)
        self.assertEqual(selected["selected_chunk_cap"], 8)
        self.assertEqual(selected["preregistered_chunk_caps"], [5, 8, 12])
        with self.assertRaisesRegex(RuntimeError, "not preregistered"):
            _validate_scan_config(config, selected_cap=6)

    def test_v4_scan_config_preserves_independent_paths(self) -> None:
        config = {
            "protocol": V4_SCAN_PROTOCOL,
            "output_dir": "artifacts/v4",
            "selection_seed": 42,
            "wave_size": 250,
            "candidate_pool_multiplier": 2,
            "candidate_pool_target_sources": 2500,
            "initial_priority_source_count": 2500,
            "extension_source_count": 250,
            "candidate_pool_shortfall_policy": (
                "scan_complete_ranked_universe"
            ),
            "scan_full_candidate_pool": False,
            "exact_target_stop": True,
            "target_query_eligible_sources": 1250,
            "required_formal_sources": 1250,
            "max_chunks_per_source": 5,
            "fallback_chunk_caps": [],
            "minimum_valid_claims": 3,
            "minimum_stealth_pairs": 3,
            "deduplicate_complete_sources": True,
            "ranking": {
                "method": "local_rule_quality_lexicographic_v1",
                "metrics": [
                    "potential_fact_count",
                    "high_quality_candidate_count",
                    "entity_type_diversity",
                    "effective_text_length",
                    "sha256_tie_break",
                ],
                "max_entities_per_chunk": 12,
                "guarantee_min_entities_per_chunk": 8,
                "high_quality_attackability_threshold": 0.6,
            },
            "historical_replay": {
                "top_k": 2500,
                "minimum_eligible_covered": 254,
                "minimum_eligible_recall": 0.965,
            },
            "historical_replay_source_order_path": "old-order.json",
            "historical_replay_eligibility_path": "old-eligibility.json",
        }
        validated = _validate_scan_config(config, selected_cap=5)
        self.assertEqual(validated["output_dir"], "artifacts/v4")
        self.assertTrue(validated["exact_target_stop"])
        with self.assertRaisesRegex(
            RuntimeError,
            "not preregistered|cap=5",
        ):
            _validate_scan_config(config, selected_cap=8)

    def test_fixed_pool_uses_prefix_or_complete_short_universe(
        self,
    ) -> None:
        source_order = ["a", "b", "c"]
        candidates = [
            {"source_key": key, "row": index}
            for index, key in enumerate(source_order)
        ]
        prefix, prefix_rows, prefix_stats = freeze_candidate_pool_prefix(
            source_order,
            candidates,
            candidate_pool_target_sources=2,
        )
        self.assertEqual(prefix, ["a", "b"])
        self.assertEqual(
            [row["source_key"] for row in prefix_rows],
            ["a", "b"],
        )
        self.assertEqual(
            prefix_stats["effective_candidate_pool_source_count"],
            2,
        )
        self.assertFalse(
            prefix_stats["candidate_pool_uses_complete_source_universe"]
        )

        complete, complete_rows, complete_stats = (
            freeze_candidate_pool_prefix(
                source_order,
                candidates,
                candidate_pool_target_sources=5,
            )
        )
        self.assertEqual(complete, source_order)
        self.assertEqual(len(complete_rows), 3)
        self.assertEqual(
            complete_stats["candidate_pool_shortfall_count"],
            2,
        )
        self.assertTrue(
            complete_stats["candidate_pool_uses_complete_source_universe"]
        )

    def test_ranked_quality_order_ignores_input_order_and_group_label(
        self,
    ) -> None:
        rows = [
            _processed_row(
                "A",
                "a1",
                "Contract AB-1234 was valued at $50 million on January 2, 2020.",
                "ha",
                group="KB_Member",
            ),
            _processed_row(
                "B",
                "b1",
                "The meeting happened yesterday without a numbered record.",
                "hb",
                group="Reserve",
            ),
        ]

        def ranked(input_rows):
            source_order, candidates, _ = freeze_source_plan(
                input_rows,
                "enron",
                selection_seed=42,
                max_chunks_per_source=5,
            )
            return rank_source_universe_by_local_quality(
                source_order,
                candidates,
                dataset="enron",
                max_entities_per_chunk=12,
                guarantee_min_entities_per_chunk=8,
                high_quality_attackability_threshold=0.6,
            )

        order_a, candidates_a, scores_a = ranked(rows)
        order_b, candidates_b, scores_b = ranked(
            [
                {**row, "group": "adversarial"}
                for row in reversed(rows)
            ]
        )
        self.assertEqual(order_a, order_b)
        self.assertEqual(scores_a, scores_b)
        self.assertEqual(
            [row["audit_id"] for row in candidates_a],
            [row["audit_id"] for row in candidates_b],
        )


class PrecisionCascadeWaveTests(unittest.TestCase):
    def test_schedule_stops_only_after_a_complete_wave(self) -> None:
        source_order = [f"source-{index}" for index in range(600)]
        calls: list[tuple[int, int]] = []

        def process_wave(
            _wave_index: int,
            wave_keys: list[str],
            start: int,
            end: int,
        ) -> dict[str, object]:
            calls.append((start, end))
            return {"eligible_source_keys": sorted(wave_keys)}

        state = execute_wave_schedule(
            source_order,
            wave_size=250,
            target_query_eligible_sources=300,
            required_formal_sources=300,
            process_wave=process_wave,
        )
        self.assertEqual(calls, [(0, 250), (250, 500)])
        self.assertEqual(state["scanned_source_count"], 500)
        self.assertEqual(state["eligible_source_count"], 500)
        self.assertEqual(state["stop_status"], "target_reached")

    def test_fixed_pool_scans_all_sources_before_capacity_decision(
        self,
    ) -> None:
        source_order = [f"source-{index}" for index in range(600)]
        calls: list[tuple[int, int]] = []

        def process_wave(
            _wave_index: int,
            wave_keys: list[str],
            start: int,
            end: int,
        ) -> dict[str, object]:
            calls.append((start, end))
            return {"eligible_source_keys": sorted(wave_keys)}

        state = execute_wave_schedule(
            source_order,
            wave_size=250,
            target_query_eligible_sources=300,
            required_formal_sources=300,
            process_wave=process_wave,
            scan_full_candidate_pool=True,
        )
        self.assertEqual(
            calls,
            [(0, 250), (250, 500), (500, 600)],
        )
        self.assertEqual(state["scanned_source_count"], 600)
        self.assertEqual(state["eligible_source_count"], 600)
        self.assertEqual(state["stop_status"], "target_reached")
        self.assertEqual(
            state["stop_reason"],
            "fixed_candidate_pool_exhausted_with_required_capacity",
        )

    def test_exact_stop_retains_only_through_target_source(self) -> None:
        source_order = [f"source-{index}" for index in range(8)]
        calls: list[tuple[int, int]] = []

        def process_wave(
            _wave_index: int,
            wave_keys: list[str],
            start: int,
            end: int,
        ) -> dict[str, object]:
            calls.append((start, end))
            return {"eligible_source_keys": sorted(wave_keys)}

        state = execute_wave_schedule(
            source_order,
            wave_size=5,
            target_query_eligible_sources=3,
            required_formal_sources=3,
            process_wave=process_wave,
            exact_target_stop=True,
        )
        self.assertEqual(calls, [(0, 5)])
        self.assertEqual(state["processed_source_count"], 5)
        self.assertEqual(state["retained_source_end"], 3)
        self.assertEqual(state["scanned_source_count"], 3)
        self.assertEqual(state["eligible_source_count"], 3)
        record = state["completed_waves"][0]
        self.assertEqual(record["processed_source_end"], 5)
        self.assertEqual(record["retained_source_end"], 3)
        self.assertEqual(
            set(record["eligible_source_keys"]),
            set(source_order[:3]),
        )

        resumed_calls: list[object] = []
        resumed = execute_wave_schedule(
            source_order,
            wave_size=5,
            target_query_eligible_sources=3,
            required_formal_sources=3,
            process_wave=lambda *args: resumed_calls.append(args) or {},
            completed_waves=state["completed_waves"],
            exact_target_stop=True,
        )
        self.assertEqual(resumed_calls, [])
        self.assertEqual(resumed["eligible_source_count"], 3)

    def test_retained_prefix_filter_excludes_prefetched_sources_from_all_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = {}
            for output_name in (
                "benchmark",
                "facts",
                "claims",
                "queries",
                "stealth",
                "stealth_rejected",
            ):
                path = root / f"{output_name}.jsonl"
                write_jsonl(
                    [
                        {"source_key": "keep", "kind": output_name},
                        {"source_key": "discard", "kind": output_name},
                    ],
                    path,
                )
                outputs[output_name] = {"path": str(path)}
            manifests = [{"outputs": outputs}]
            for output_name in outputs:
                rows = list(
                    _iter_wave_rows(
                        manifests,
                        output_name,
                        allowed_source_keys={"keep"},
                    )
                )
                self.assertEqual(
                    {row["source_key"] for row in rows},
                    {"keep"},
                )

    def test_resume_rejects_noncontiguous_completed_wave(self) -> None:
        source_order = [f"s{index}" for index in range(10)]
        bad_record = {
            "wave_index": 1,
            "source_start": 0,
            "source_end": 5,
            "wave_source_keys_hash": sha256_obj(source_order[:5]),
            "eligible_source_keys": [],
        }
        with self.assertRaisesRegex(RuntimeError, "not contiguous"):
            execute_wave_schedule(
                source_order,
                wave_size=5,
                target_query_eligible_sources=8,
                required_formal_sources=8,
                process_wave=lambda *_: {},
                completed_waves=[bad_record],
            )

    def test_fixed_budget_requires_three_pairs_and_six_unique_queries(
        self,
    ) -> None:
        rows = []
        for pair_index in range(3):
            for claim_type in ("true", "counterfactual"):
                rows.append(
                    {
                        "source_key": "source",
                        "group": "Eligibility_Candidate",
                        "pair_id": f"pair-{pair_index}",
                        "query_type": "compressed_verification",
                        "claim_type": claim_type,
                        "query": f"query-{pair_index}-{claim_type}",
                    }
                )
        eligible, stats = validate_fixed_budget_query_rows(
            rows,
            allowed_source_keys={"source"},
            required_pairs=3,
        )
        self.assertEqual(eligible, ["source"])
        self.assertEqual(stats["queries_per_source"], 6)

        rows[-1]["query"] = rows[-2]["query"]
        with self.assertRaisesRegex(RuntimeError, "duplicate/empty"):
            validate_fixed_budget_query_rows(
                rows,
                allowed_source_keys={"source"},
                required_pairs=3,
            )


class PrecisionCascadeCheckpointTests(unittest.TestCase):
    def test_checkpoint_chain_validates_every_predecessor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "scan_plan_sha256": "plan-hash",
                "dataset": "edgar",
                "source_order_sha256": "order-hash",
                "wave_size": 2,
                "target_query_eligible_sources": 4,
                "required_formal_sources": 4,
                "candidate_pool_target_sources": 4,
                "effective_candidate_pool_source_count": 4,
                "scan_full_candidate_pool": True,
            }
            first_record = {
                "wave_index": 0,
                "source_start": 0,
                "source_end": 2,
                "wave_source_keys_hash": "wave-0",
                "eligible_source_keys": ["a", "b"],
            }
            first_state = {
                "stop_status": "in_progress",
                "stop_reason": "continue_next_wave",
                "completed_waves": [first_record],
                "scanned_source_count": 2,
                "scanned_prefix_source_keys_hash": "prefix-0",
                "eligible_source_keys": ["a", "b"],
                "eligible_source_count": 2,
            }
            first_path = write_checkpoint(root, plan, first_state)
            second_record = {
                "wave_index": 1,
                "source_start": 2,
                "source_end": 4,
                "wave_source_keys_hash": "wave-1",
                "eligible_source_keys": ["c", "d"],
            }
            second_state = {
                **first_state,
                "stop_status": "target_reached",
                "stop_reason": "target_reached_after_complete_wave",
                "completed_waves": [first_record, second_record],
                "scanned_source_count": 4,
                "scanned_prefix_source_keys_hash": "prefix-1",
                "eligible_source_keys": ["a", "b", "c", "d"],
                "eligible_source_count": 4,
            }
            write_checkpoint(root, plan, second_state)
            latest, _ = load_latest_checkpoint(root, plan)
            self.assertEqual(len(latest["completed_waves"]), 2)

            tampered = read_json(first_path)
            tampered["stop_reason"] = "tampered"
            write_json(tampered, first_path)
            with self.assertRaisesRegex(RuntimeError, "identity drift"):
                load_latest_checkpoint(root, plan)

    def test_staged_final_file_is_idempotent_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.jsonl"
            staged = root / "staged.jsonl"
            staged.write_text("same\n", encoding="utf-8")
            _promote_staged_file(staged, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "same\n")

            same = root / "same.jsonl"
            same.write_text("same\n", encoding="utf-8")
            _promote_staged_file(same, target)

            different = root / "different.jsonl"
            different.write_text("different\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "hash drift"):
                _promote_staged_file(different, target)

    def test_exact_checkpoint_preserves_processed_and_retained_boundaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "protocol": V4_SCAN_PROTOCOL,
                "scan_plan_sha256": "v4-plan",
                "dataset": "enron",
                "source_order_sha256": "order",
                "wave_size": 5,
                "target_query_eligible_sources": 3,
                "required_formal_sources": 3,
                "candidate_pool_target_sources": 6,
                "effective_candidate_pool_source_count": 8,
                "scan_full_candidate_pool": False,
                "exact_target_stop": True,
            }
            record = {
                "wave_index": 0,
                "source_start": 0,
                "source_end": 3,
                "processed_source_end": 5,
                "retained_source_end": 3,
                "wave_source_keys_hash": "retained-wave",
                "processed_wave_source_keys_hash": "processed-wave",
                "retained_wave_source_keys_hash": "retained-wave",
                "eligible_source_keys": ["a", "b", "c"],
            }
            state = {
                "stop_status": "target_reached",
                "stop_reason": (
                    "exact_target_reached_at_retained_source_boundary"
                ),
                "completed_waves": [record],
                "scanned_source_count": 3,
                "scanned_prefix_source_keys_hash": "retained-prefix",
                "eligible_source_keys": ["a", "b", "c"],
                "eligible_source_count": 3,
                "processed_source_count": 5,
                "processed_prefix_source_keys_hash": "processed-prefix",
                "retained_source_end": 3,
                "retained_prefix_source_keys_hash": "retained-prefix",
            }
            path = write_checkpoint(root, plan, state)
            payload = read_json(path)
            self.assertEqual(payload["processed_source_count"], 5)
            self.assertEqual(payload["retained_source_end"], 3)
            latest, _ = load_latest_checkpoint(root, plan)
            self.assertEqual(latest["eligible_source_count"], 3)


class PrecisionCascadeIntegrationGateTests(unittest.TestCase):
    @staticmethod
    def _fake_runtime() -> tuple[object, SemanticResolverMetadata]:
        class FakeResolver:
            def predict_batch(
                self,
                texts: list[str],
                **_kwargs: object,
            ) -> list[list[object]]:
                return [[] for _ in texts]

        metadata = SemanticResolverMetadata(
            enabled=True,
            protocol=SEMANTIC_RESOLVER_PROTOCOL,
            schema_sha256=SEMANTIC_SCHEMA_SHA256,
            models=({"role": "gliner2_large"},),
            min_target_confidence=0.95,
            min_confidence_margin=0.4,
            min_consensus_votes=1,
            min_boundary_votes=1,
            biomedical_veto_threshold=0.9,
            batch_size=8,
            execution_mode=PRECISION_CASCADE_MODE,
            primary_model_role="gliner2_large",
            thresholds_sha256="threshold-hash",
        )
        return FakeResolver(), metadata

    @staticmethod
    def _fake_runtime_config() -> dict[str, object]:
        return {
            "enabled": True,
            "protocol": SEMANTIC_RESOLVER_PROTOCOL,
            "execution_mode": PRECISION_CASCADE_MODE,
            "primary_model_role": "gliner2_large",
            "thresholds_sha256": "threshold-hash",
            "batch_size": 8,
        }

    def test_source_lookup_only_materializes_current_wave(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus.jsonl"
            write_jsonl(
                [
                    _processed_row("A", "a1", "first", "h1"),
                    _processed_row("A", "a2", "second", "h2"),
                    _processed_row("B", "b1", "other", "h3"),
                ],
                corpus,
            )
            lookup = load_complete_source_lookup(
                corpus,
                source_key_allowlist={"::A"},
            )
            self.assertEqual(lookup, {"::A": "first\nsecond"})
            with self.assertRaisesRegex(RuntimeError, "missing allowlisted"):
                load_complete_source_lookup(
                    corpus,
                    source_key_allowlist={"::missing"},
                )

    def test_reused_runtime_is_bound_to_formal_model_roles(self) -> None:
        runtime = self._fake_runtime()
        config = self._fake_runtime_config()
        self.assertIs(
            resolve_semantic_runtime(
                config,
                dataset="enron",
                runtime=runtime,
            ),
            runtime,
        )
        with self.assertRaisesRegex(
            SemanticResolverProtocolError,
            "semantic_runtime_model_roles_mismatch",
        ):
            resolve_semantic_runtime(
                config,
                dataset="pubmed",
                runtime=runtime,
            )

    def test_fact_and_claim_stages_reuse_runtime_without_reloading(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark = root / "benchmark.jsonl"
            facts = root / "facts.jsonl"
            claims = root / "claims.jsonl"
            write_jsonl(
                [
                    {
                        **_processed_row(
                            "A",
                            "a1",
                            "The amount was $10 million.",
                            "h1",
                        ),
                        "source_key": "::A",
                        "audit_id": "a1",
                        "group": "Eligibility_Candidate",
                    }
                ],
                benchmark,
            )
            runtime = self._fake_runtime()
            config = self._fake_runtime_config()
            with (
                patch(
                    "src.fact_extraction.fact_extractor."
                    "load_semantic_entity_resolver",
                    side_effect=AssertionError("unexpected reload"),
                ),
                patch(
                    "src.paired_claims.claim_generator."
                    "load_semantic_entity_resolver",
                    side_effect=AssertionError("unexpected reload"),
                ),
            ):
                extract_facts_file(
                    benchmark,
                    facts,
                    semantic_resolver_config=config,
                    semantic_resolver_runtime=runtime,
                    ner_config={"enabled": False},
                    dataset="enron",
                    resume=False,
                )
                generate_paired_claims_file(
                    facts,
                    claims,
                    benchmark_path=benchmark,
                    source_corpus_path=benchmark,
                    semantic_resolver_config=config,
                    semantic_resolver_runtime=runtime,
                    source_key_allowlist={"::A"},
                    dataset="enron",
                    resume=False,
                )

    def test_formal_manifest_requires_passed_capacity_and_checkpoint(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "checkpoint.json"
            checkpoint.write_text("checkpoint", encoding="utf-8")
            eligible = [f"s{index}" for index in range(1250)]
            manifest = {
                "dataset": "edgar",
                "protocol": QUERY_ELIGIBILITY_PROTOCOL,
                "scan_protocol": SCAN_PROTOCOL,
                "capacity_status": "passed",
                "stop_status": "target_reached",
                "deduplicate_complete_sources": True,
                "scan_full_candidate_pool": True,
                "scanned_source_count": 2500,
                "effective_candidate_pool_source_count": 2500,
                "eligible_source_keys": eligible,
                "eligible_source_count": len(eligible),
                "whitelist_hash": sha256_obj(sorted(eligible)),
                "minimum_stealth_pairs": 3,
                "queries_per_source": 6,
                "query_text_uniqueness_enforced": True,
                "scan_checkpoint_path": str(checkpoint),
                "scan_checkpoint_sha256": sha256_file(checkpoint),
            }
            self.assertEqual(
                len(
                    validate_formal_eligibility_manifest(
                        manifest,
                        dataset="edgar",
                    )
                ),
                1250,
            )
            failed = deepcopy(manifest)
            failed["capacity_status"] = "insufficient"
            with self.assertRaisesRegex(RuntimeError, "capacity"):
                validate_formal_eligibility_manifest(
                    failed,
                    dataset="edgar",
                )

    def test_formal_v4_manifest_requires_exact_1250_and_enron(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "checkpoint.json"
            checkpoint.write_text("checkpoint", encoding="utf-8")
            eligible = [f"s{index}" for index in range(1250)]
            manifest = {
                "dataset": "enron",
                "protocol": V4_QUERY_ELIGIBILITY_PROTOCOL,
                "scan_protocol": V4_SCAN_PROTOCOL,
                "capacity_status": "passed",
                "stop_status": "target_reached",
                "deduplicate_complete_sources": True,
                "scan_full_candidate_pool": False,
                "exact_target_stop": True,
                "target_query_eligible_sources": 1250,
                "scanned_source_count": 1412,
                "processed_source_count": 1500,
                "retained_source_end": 1412,
                "retained_prefix_source_keys_hash": "retained",
                "eligible_source_keys": eligible,
                "eligible_source_count": 1250,
                "whitelist_hash": sha256_obj(sorted(eligible)),
                "minimum_stealth_pairs": 3,
                "queries_per_source": 6,
                "query_text_uniqueness_enforced": True,
                "scan_checkpoint_path": str(checkpoint),
                "scan_checkpoint_sha256": sha256_file(checkpoint),
            }
            self.assertEqual(
                len(
                    validate_formal_eligibility_manifest(
                        manifest,
                        dataset="enron",
                    )
                ),
                1250,
            )
            excessive = deepcopy(manifest)
            excessive["eligible_source_keys"] = [
                *eligible,
                "extra",
            ]
            excessive["eligible_source_count"] = 1251
            excessive["whitelist_hash"] = sha256_obj(
                sorted(excessive["eligible_source_keys"])
            )
            with self.assertRaisesRegex(RuntimeError, "exact"):
                validate_formal_eligibility_manifest(
                    excessive,
                    dataset="enron",
                )
            with self.assertRaisesRegex(
                RuntimeError,
                "protocol/dataset mismatch",
            ):
                wrong_dataset_protocol = deepcopy(manifest)
                wrong_dataset_protocol["dataset"] = "edgar"
                validate_formal_eligibility_manifest(
                    wrong_dataset_protocol,
                    dataset="edgar",
                )

    def test_formal_budget6_release_manifest_supports_all_datasets(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "checkpoint.json"
            checkpoint.write_text("checkpoint", encoding="utf-8")
            eligible = [f"s{index}" for index in range(1250)]
            protocols = (
                (
                    BUDGET6_RELEASE_QUERY_ELIGIBILITY_PROTOCOL,
                    BUDGET6_RELEASE_SCAN_PROTOCOL,
                ),
                (
                    ATTACK_FIRST_RC2_RELEASE_QUERY_ELIGIBILITY_PROTOCOL,
                    ATTACK_FIRST_RC2_RELEASE_SCAN_PROTOCOL,
                ),
            )
            for dataset in ("edgar", "enron", "pubmed"):
                for query_protocol, scan_protocol in protocols:
                    manifest = {
                        "dataset": dataset,
                        "protocol": query_protocol,
                        "scan_protocol": scan_protocol,
                        "capacity_status": "passed",
                        "stop_status": "target_reached",
                        "deduplicate_complete_sources": True,
                        "scan_full_candidate_pool": True,
                        "scanned_source_count": 1250,
                        "effective_candidate_pool_source_count": 1250,
                        "eligible_source_keys": eligible,
                        "eligible_source_count": 1250,
                        "whitelist_hash": sha256_obj(sorted(eligible)),
                        "minimum_stealth_pairs": 3,
                        "queries_per_source": 6,
                        "query_text_uniqueness_enforced": True,
                        "scan_checkpoint_path": str(checkpoint),
                        "scan_checkpoint_sha256": sha256_file(checkpoint),
                    }
                    self.assertEqual(
                        len(
                            validate_formal_eligibility_manifest(
                                manifest,
                                dataset=dataset,
                            )
                        ),
                        1250,
                    )


if __name__ == "__main__":
    unittest.main()
