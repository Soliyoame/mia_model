from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.attack.attackability_selector import (
    DEFAULT_UTILITY_WEIGHTS,
    RouteDecision,
    assert_selection_payload_is_label_free,
    build_pair_candidates,
    machine_format_compatible,
    route_effective_type,
    select_structured_extension_pairs,
    select_top_pairs,
    utility_score,
    validate_pair_hard_gates,
)
from src.prepare.attackability_v22 import (
    FRESH_AUDIT_PROTOCOL,
    OLD_SHADOW_BASELINE_PROTOCOL,
    SHADOW_ARTIFACT_PROTOCOLS,
    SHADOW_GATE_PROTOCOL,
    THRESHOLD_MANIFEST_PROTOCOL,
    _checkpoint_identity,
    _identity,
    _load_fresh_audit_plan,
    _load_bound_shadow_artifact,
    _load_frozen_threshold,
    _load_passed_shadow_gate,
    _load_scan_checkpoint,
    _write_source_checkpoint,
    _write_scan_checkpoint,
    evaluate_calibration,
    evaluate_shadow_gate,
    load_v22_config,
    prepare_source_pool,
    prepare_user_review,
)
from src.utils.hash import sha256_file, sha256_obj


def _candidate(**overrides):
    sentence = "Atlas System was installed by the operations team in 2024."
    start = sentence.index("Atlas System")
    value = {
        "source_key": "source-1",
        "audit_id": "audit-1",
        "text": "Atlas System",
        "type": "PRODUCT",
        "start": start,
        "end": start + len("Atlas System"),
        "supporting_sentence": sentence,
        "entity_sentence_span": [start, start + len("Atlas System")],
        "context_quality": 0.9,
        "specificity": 0.9,
        "retrieval_anchor_strength": 0.8,
        "parser_friendliness": 0.9,
    }
    value.update(overrides)
    return value


def _pair_row(
    pair_id: str,
    score: float,
    fact: str,
    entity: str,
    *,
    entity_type: str = "PERSON",
):
    return {
        "pair_id": pair_id,
        "source_key": "source-1",
        "effective_type": entity_type,
        "original_entity": entity,
        "fact_signature": fact,
        "utility_score": score,
        "hard_gate_passed": True,
    }


class AttackabilityV22RoutingTests(unittest.TestCase):
    def test_single_model_reroutes_and_regenerates_from_effective_type(self):
        candidate = _candidate(
            text="Acme Holdings",
            type="LOCATION",
            start=0,
            end=len("Acme Holdings"),
            supporting_sentence="Acme Holdings acquired the regional facility in 2024.",
            entity_sentence_span=[0, len("Acme Holdings")],
        )
        predictions = {
            "gliner2_base": [
                {
                    "label": "ORG",
                    "start": 0,
                    "end": len("Acme Holdings"),
                    "score": 0.91,
                }
            ]
        }
        route = route_effective_type(
            candidate,
            predictions,
            required_roles=["gliner2_base"],
            minimum_votes=1,
            minimum_prediction_score=0.65,
        )
        self.assertEqual(route.status, "rerouted")
        self.assertEqual(route.effective_type, "ORG")
        self.assertEqual(route.route_source, "single_router_model")
        pairs = build_pair_candidates(
            candidate,
            candidate["supporting_sentence"],
            route,
        )
        self.assertEqual(len(pairs), 3)
        self.assertTrue(all(row["effective_type"] == "ORG" for row in pairs))
        self.assertTrue(all(row["declared_type"] == "LOCATION" for row in pairs))

    def test_single_model_cannot_veto_high_precision_rule(self):
        candidate = _candidate()
        predictions = {
            "gliner2_base": [
                {
                    "label": "ORG",
                    "start": 0,
                    "end": len("Atlas System"),
                    "score": 0.99,
                }
            ]
        }
        route = route_effective_type(
            candidate,
            predictions,
            required_roles=["gliner2_base"],
            minimum_votes=1,
        )
        self.assertEqual(route.effective_type, "PRODUCT")
        self.assertEqual(route.route_source, "high_precision_rule")
        self.assertEqual(route.votes, {})

    def test_model_miss_falls_back_to_declared_type_without_veto(self):
        candidate = _candidate(
            text="North Basin",
            type="LOCATION",
            start=0,
            end=len("North Basin"),
            supporting_sentence="North Basin contained the sampled facility in the report.",
            entity_sentence_span=[0, len("North Basin")],
        )
        route = route_effective_type(
            candidate,
            {"gliner2_base": []},
            required_roles=["gliner2_base"],
        )
        self.assertEqual(route.status, "accepted")
        self.assertEqual(route.effective_type, "LOCATION")
        self.assertEqual(route.route_source, "declared_type_fallback")

    def test_diagnostic_prediction_cannot_veto_main_candidate(self):
        candidate = _candidate(
            text="North Basin",
            type="LOCATION",
            start=0,
            end=len("North Basin"),
            supporting_sentence="North Basin contained the sampled facility in the report.",
            entity_sentence_span=[0, len("North Basin")],
        )
        route = route_effective_type(
            candidate,
            {
                "gliner2_base": [
                    {
                        "label": "PROJECT_NAME",
                        "start": 0,
                        "end": len("North Basin"),
                        "score": 0.99,
                    }
                ]
            },
            required_roles=["gliner2_base"],
        )
        self.assertEqual(route.effective_type, "LOCATION")
        self.assertEqual(route.route_source, "declared_type_fallback")

    def test_diagnostic_candidate_cannot_be_promoted_to_main(self):
        candidate = _candidate(type="PROJECT_NAME")
        route = route_effective_type(
            candidate,
            {
                "gliner2_base": [
                    {
                        "label": "PRODUCT",
                        "start": candidate["start"],
                        "end": candidate["end"],
                        "score": 0.99,
                    }
                ]
            },
            required_roles=["gliner2_base"],
        )
        self.assertEqual(route.effective_type, "PROJECT_NAME")
        self.assertEqual(route.route_source, "diagnostic_only")


class AttackabilityV22GateTests(unittest.TestCase):
    def test_president_to_person_name_is_not_rejected_by_manual_subtype(self):
        self.assertTrue(
            machine_format_compatible("President Trump", "Dakota Reyes", "PERSON")
        )

    def test_single_slot_source_absence_and_format_gates(self):
        candidate = _candidate()
        pair, reasons = validate_pair_hard_gates(
            candidate,
            "Beacon Platform",
            candidate["supporting_sentence"],
            effective_type="PRODUCT",
        )
        self.assertEqual(reasons, ())
        self.assertEqual(
            pair["counterfactual_claim"],
            "Beacon Platform was installed by the operations team in 2024.",
        )
        _, present_reasons = validate_pair_hard_gates(
            candidate,
            "operations team",
            candidate["supporting_sentence"],
            effective_type="PRODUCT",
        )
        self.assertIn("counterfactual_entity_present_in_source", present_reasons)

    def test_utility_score_is_monotonic_in_each_component(self):
        base = {name: 0.5 for name in DEFAULT_UTILITY_WEIGHTS}
        baseline = utility_score(base)
        for component in DEFAULT_UTILITY_WEIGHTS:
            improved = dict(base)
            improved[component] = 0.7
            self.assertGreater(utility_score(improved), baseline)

    def test_selection_is_deterministic_distinct_and_entity_bounded(self):
        rows = [
            _pair_row("p1", 0.90, "f1", "Alice Smith"),
            _pair_row("p2", 0.89, "f1", "Alice Smith"),
            _pair_row("p3", 0.88, "f2", "Alice Smith"),
            _pair_row("p4", 0.87, "f3", "Alice Smith"),
            _pair_row("p5", 0.86, "f4", "Bob Jones"),
        ]
        first = select_top_pairs(rows, threshold=0.5)
        second = select_top_pairs(list(reversed(rows)), threshold=0.5)
        self.assertEqual([row["pair_id"] for row in first], ["p1", "p3", "p5"])
        self.assertEqual(first, second)
        self.assertEqual(len({row["fact_signature"] for row in first}), 3)

    def test_structured_extension_does_not_change_main_selection(self):
        main = [
            _pair_row("m1", 0.9, "f1", "Alice Smith"),
            _pair_row("m2", 0.8, "f2", "Bob Jones"),
            _pair_row("m3", 0.7, "f3", "Carol Brown"),
        ]
        structured = _pair_row(
            "s1", 0.99, "sf1", "$100", entity_type="MONEY"
        )
        before = select_top_pairs(main, threshold=0.5)
        after = select_top_pairs([*main, structured], threshold=0.5)
        extension = select_structured_extension_pairs(
            [*main, structured], threshold=0.5
        )
        self.assertEqual(before, after)
        self.assertEqual([row["pair_id"] for row in extension], ["s1"])

    def test_membership_victim_and_auc_fields_are_forbidden(self):
        for field in ("membership", "group", "victim_response", "attack_auc"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "forbidden_selection_field"):
                    assert_selection_payload_is_label_free({"text": "x", field: "secret"})


class AttackabilityV22IdentityTests(unittest.TestCase):
    def test_config_freezes_single_gliner2_base(self):
        config = load_v22_config("configs/attackability_first_v22.yaml")
        self.assertEqual(config["routing"]["single_model_id"], "fastino/gliner2-base-v1")
        self.assertEqual(
            config["routing"]["single_model_revision"],
            "f5b2ecedebe4381b088c1cf276f5bf72a52cac54",
        )
        self.assertNotIn("required_model_roles", config["routing"])
        self.assertIn("configs/entity_type_policy_v21_r1.yaml", config["runtime_files"])
        self.assertIn("src/data/filter.py", config["runtime_files"])

    def test_checkpoint_resume_rejects_identity_drift(self):
        plan = {"scan_plan_identity_sha256": "plan-1"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            checkpoint = _load_scan_checkpoint(path, plan)
            _write_scan_checkpoint(path, checkpoint)
            loaded = _load_scan_checkpoint(path, plan)
            self.assertEqual(
                loaded["checkpoint_identity_sha256"], _checkpoint_identity(loaded)
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["eligible_source_keys"] = ["tampered"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "checkpoint identity drift"):
                _load_scan_checkpoint(path, plan)

    def test_user_review_freeze_is_resumable_with_identical_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calibration_dir = root / "artifacts" / "v22" / "calibration"
            calibration_dir.mkdir(parents=True)
            blinded_path = calibration_dir / "calibration_blinded.jsonl"
            blinded_path.write_text(
                json.dumps({"review_id": "review-1", "candidate": "x"}) + "\n",
                encoding="utf-8",
            )
            assistant_path = root / "assistant_labels.jsonl"
            assistant_path.write_text(
                json.dumps(
                    {
                        "review_id": "review-1",
                        "grounded_specific_fact": "yes",
                        "natural_counterfactual": "yes",
                        "verification_discriminative": "yes",
                        "queryable_self_contained": "yes",
                        "attack_usable": "yes",
                        "reason_codes": [],
                        "evidence": "The pair is grounded and directly verifiable.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            config = {"output_root": "artifacts/v22"}
            plan = {
                "calibration_plan_identity_sha256": "calibration-plan-1",
                "artifacts": {
                    "blinded": {
                        "path": str(blinded_path.relative_to(root)),
                    }
                },
                "base_user_review_ids": ["review-1"],
            }
            with (
                patch(
                    "src.prepare.attackability_v22.load_v22_config",
                    return_value=config,
                ),
                patch(
                    "src.prepare.attackability_v22._load_calibration_plan",
                    return_value=plan,
                ),
            ):
                first = prepare_user_review(
                    root / "config.yaml",
                    assistant_path,
                    resume=False,
                    project_root=root,
                )
                resumed = prepare_user_review(
                    root / "config.yaml",
                    assistant_path,
                    resume=True,
                    project_root=root,
                )
            self.assertEqual(first, resumed)
            manifest = json.loads(Path(first["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["review_ids"], ["review-1"])

    def test_source_pool_resume_recovers_from_database_state_ahead_of_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("protocol: synthetic\n", encoding="utf-8")
            processed_path = root / "processed.jsonl"
            source_rows = [
                {"doc_id": "a1", "source_id": "a", "text": "Alpha one."},
                {"doc_id": "a2", "source_id": "a", "text": "Alpha two."},
                {"doc_id": "b1", "source_id": "b", "text": "Beta one."},
                {"doc_id": "c1", "source_id": "c", "text": "Gamma one."},
            ]
            processed_path.write_text(
                "".join(json.dumps(row) + "\n" for row in source_rows),
                encoding="utf-8",
            )
            prefix_path = root / "prefix.json"
            prefix_path.write_text(
                json.dumps({"source_order": []}), encoding="utf-8"
            )
            config = {
                "output_root": "artifacts/v22",
                "selection_seed": 42,
                "candidate_extraction": {"max_chunks_per_source": 2},
                "execution": {"source_pool_checkpoint_interval_rows": 1},
                "source_pools": {
                    "edgar": {
                        "processed_path": str(processed_path),
                        "processed_sha256": sha256_file(processed_path),
                        "order_mode": "derive_complete_and_verify_v21_prefix",
                        "frozen_prefix_path": str(prefix_path),
                        "expected_processed_source_count": 3,
                        "declared_raw_capacity": 3,
                    }
                },
            }
            with (
                patch(
                    "src.prepare.attackability_v22.load_v22_config",
                    return_value=config,
                ),
                patch(
                    "src.prepare.attackability_v22._load_protocol_manifest",
                    return_value={"protocol_identity_sha256": "protocol-1"},
                ),
            ):
                paused = prepare_source_pool(
                    config_path,
                    dataset="edgar",
                    resume=True,
                    max_new_rows=1,
                    project_root=root,
                )
                self.assertEqual(paused["status"], "paused")
                checkpoint_path = Path(paused["checkpoint"])
                stale = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                stale.update(
                    {
                        "byte_offset": 0,
                        "input_rows_seen": 0,
                        "source_groups_seen": 0,
                        "sources_retained": 0,
                    }
                )
                _write_source_checkpoint(checkpoint_path, stale)
                completed = prepare_source_pool(
                    config_path,
                    dataset="edgar",
                    resume=True,
                    max_new_rows=100,
                    project_root=root,
                )
                self.assertEqual(completed["status"], "passed")
                validated = prepare_source_pool(
                    config_path,
                    dataset="edgar",
                    resume=True,
                    max_new_rows=100,
                    project_root=root,
                )
                self.assertEqual(validated["source_count"], 3)

    def test_calibration_rejects_assistant_labels_not_used_for_user_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_path = root / "calibration_key.jsonl"
            private_path.write_text(
                json.dumps(
                    {
                        "review_id": "review-1",
                        "row_kind": "real_candidate",
                        "pair_id": "pair-1",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            assistant_path = root / "assistant.jsonl"
            assistant_path.write_text("{}\n", encoding="utf-8")
            plan = {
                "artifacts": {"private_key": {"path": str(private_path)}},
            }
            user_manifest = {
                "assistant_labels_sha256": "0" * 64,
            }
            with (
                patch(
                    "src.prepare.attackability_v22.load_v22_config",
                    return_value={"output_root": "artifacts/v22"},
                ),
                patch(
                    "src.prepare.attackability_v22._load_calibration_plan",
                    return_value=plan,
                ),
                patch(
                    "src.prepare.attackability_v22._load_user_review_manifest",
                    return_value=user_manifest,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "frozen user-review input"):
                    evaluate_calibration(
                        root / "config.yaml",
                        assistant_path,
                        root / "unused_user_labels.jsonl",
                        project_root=root,
                    )

    def test_threshold_loader_rejects_stale_calibration_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "artifacts" / "v22" / "calibration"
            output.mkdir(parents=True)
            report = {
                "protocol": "pcv_v22_calibration_evaluation_r1",
                "status": "passed",
                "created_at": "frozen",
                "selected_threshold": 0.6,
            }
            report["evaluation_identity_sha256"] = _identity(
                report, "created_at", "evaluation_identity_sha256"
            )
            report_path = output / "calibration_evaluation.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            threshold = {
                "protocol": THRESHOLD_MANIFEST_PROTOCOL,
                "status": "passed",
                "created_at": "frozen",
                "config_sha256": "config-1",
                "calibration_evaluation_sha256": sha256_file(report_path),
                "calibration_evaluation_identity_sha256": report[
                    "evaluation_identity_sha256"
                ],
                "selected_threshold": 0.6,
            }
            threshold["threshold_identity_sha256"] = _identity(
                threshold, "created_at", "threshold_identity_sha256"
            )
            (output / "threshold_manifest.json").write_text(
                json.dumps(threshold), encoding="utf-8"
            )
            report["status"] = "failed_new_protocol_identity_required"
            report["evaluation_identity_sha256"] = _identity(
                report, "created_at", "evaluation_identity_sha256"
            )
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with patch(
                "src.prepare.attackability_v22._load_protocol_manifest",
                return_value={"config_sha256": "config-1"},
            ):
                with self.assertRaisesRegex(RuntimeError, "report drift"):
                    _load_frozen_threshold(
                        {"output_root": "artifacts/v22"}, root
                    )

    def test_fresh_audit_loader_rejects_calibration_source_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "artifacts" / "v22" / "fresh_audit"
            private_dir = output / "private"
            private_dir.mkdir(parents=True)
            fresh_private = private_dir / "fresh.jsonl"
            fresh_private.write_text(
                json.dumps(
                    {
                        "review_id": "fresh-1",
                        "source_key": "source-1",
                        "fact_signature": "fact-2",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            plan = {
                "protocol": FRESH_AUDIT_PROTOCOL,
                "status": "frozen_before_labels",
                "created_at": "frozen",
                "threshold_identity_sha256": "threshold-1",
                "artifacts": {
                    "private_key": {
                        "path": str(fresh_private),
                        "sha256": sha256_file(fresh_private),
                    }
                },
            }
            plan["fresh_audit_identity_sha256"] = _identity(
                plan, "created_at", "fresh_audit_identity_sha256"
            )
            (output / "fresh_audit_plan.json").write_text(
                json.dumps(plan), encoding="utf-8"
            )
            calibration_private = root / "calibration_private.jsonl"
            calibration_private.write_text(
                json.dumps(
                    {
                        "source_key": "source-1",
                        "fact_signature": "fact-1",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            calibration_plan = {
                "artifacts": {
                    "private_key": {"path": str(calibration_private)}
                }
            }
            with (
                patch(
                    "src.prepare.attackability_v22._load_frozen_threshold",
                    return_value=(0.6, {"threshold_identity_sha256": "threshold-1"}),
                ),
                patch(
                    "src.prepare.attackability_v22._load_calibration_plan",
                    return_value=calibration_plan,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "overlaps calibration sources"):
                    _load_fresh_audit_plan(
                        {"output_root": "artifacts/v22"}, root
                    )

    def test_shadow_report_missing_reserve_only_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "shadow.json"
            report_path.write_text(
                json.dumps(
                    {
                        "protocol": "pcv_v22_reserve_shadow_report_r1",
                        "per_source_selection_performed": False,
                        "datasets": {},
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch(
                    "src.prepare.attackability_v22.load_v22_config",
                    return_value={"source_pools": {}, "output_root": "artifacts/v22"},
                ),
                patch(
                    "src.prepare.attackability_v22._load_protocol_manifest",
                    return_value={"protocol_identity_sha256": "protocol-1"},
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "Reserve-only"):
                    evaluate_shadow_gate(
                        root / "config.yaml",
                        report_path,
                        project_root=root,
                    )

    def test_shadow_artifact_hash_is_backed_by_a_bound_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload_path = root / "index.bin"
            payload_path.write_bytes(b"frozen-index")
            manifest = {
                "protocol": SHADOW_ARTIFACT_PROTOCOLS["index"],
                "status": "passed",
                "created_at": "frozen",
                "dataset": "edgar",
                "split_identity_sha256": "split-1",
                "source_keys": ["source-1"],
                "source_keys_sha256": sha256_obj(["source-1"]),
                "source_count": 1,
                "reserve_source_set_sha256": sha256_obj(["source-1"]),
                "retriever": "bge",
                "forbidden_group_overlap": 0,
                "payload_path": str(payload_path),
                "payload_sha256": sha256_file(payload_path),
            }
            manifest["manifest_identity_sha256"] = _identity(
                manifest, "created_at", "manifest_identity_sha256"
            )
            manifest_path = root / "index_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            loaded = _load_bound_shadow_artifact(
                root=root,
                manifest_path_value=manifest_path,
                manifest_hash=sha256_file(manifest_path),
                kind="index",
                dataset="edgar",
                split_identity_sha256="split-1",
                reserve_keys=["source-1"],
                retriever="bge",
            )
            self.assertEqual(loaded["payload_sha256"], sha256_file(payload_path))
            payload_path.write_bytes(b"tampered-index")
            with self.assertRaisesRegex(RuntimeError, "payload drift"):
                _load_bound_shadow_artifact(
                    root=root,
                    manifest_path_value=manifest_path,
                    manifest_hash=sha256_file(manifest_path),
                    kind="index",
                    dataset="edgar",
                    split_identity_sha256="split-1",
                    reserve_keys=["source-1"],
                    retriever="bge",
                )

    def test_passed_shadow_gate_revalidates_payloads_at_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shadow_dir = root / "artifacts" / "v22" / "shadow"
            shadow_dir.mkdir(parents=True)
            source_keys = ["source-1"]
            reserve_hash = sha256_obj(source_keys)

            def freeze_artifact(kind: str, *, retriever: str | None = None):
                payload_path = root / f"{kind}_{retriever or 'shared'}.bin"
                payload_path.write_bytes(f"{kind}-payload".encode())
                manifest = {
                    "protocol": SHADOW_ARTIFACT_PROTOCOLS[kind],
                    "status": "passed",
                    "created_at": "frozen",
                    "dataset": "edgar",
                    "split_identity_sha256": "split-1",
                    "source_keys": source_keys,
                    "source_keys_sha256": reserve_hash,
                    "source_count": 1,
                    "reserve_source_set_sha256": reserve_hash,
                    "payload_path": str(payload_path),
                    "payload_sha256": sha256_file(payload_path),
                }
                if kind == "index":
                    manifest.update(
                        {"retriever": retriever, "forbidden_group_overlap": 0}
                    )
                else:
                    manifest["retriever_scope"] = "shared"
                manifest["manifest_identity_sha256"] = _identity(
                    manifest, "created_at", "manifest_identity_sha256"
                )
                manifest_path = root / f"{kind}_{retriever or 'shared'}_manifest.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                return manifest_path, payload_path

            index_manifest, index_payload = freeze_artifact(
                "index", retriever="bge"
            )
            query_manifest, _ = freeze_artifact("query")
            benchmark_manifest, _ = freeze_artifact("benchmark")
            metrics = {
                "index_manifest_path": str(index_manifest),
                "index_manifest_hash": sha256_file(index_manifest),
                "query_manifest_path": str(query_manifest),
                "query_hash": sha256_file(query_manifest),
                "benchmark_manifest_path": str(benchmark_manifest),
                "benchmark_hash": sha256_file(benchmark_manifest),
                "evaluated_source_count": 1,
                "recall_at_5": 0.8,
                "recall_at_10": 0.9,
                "zero_hit_rate": 0.0,
            }
            baseline = {
                "protocol": OLD_SHADOW_BASELINE_PROTOCOL,
                "status": "passed",
                "created_at": "frozen",
                "dataset": "edgar",
                "split_identity_sha256": "split-1",
                "source_keys": source_keys,
                "source_keys_sha256": reserve_hash,
                "source_count": 1,
                "reserve_source_set_sha256": reserve_hash,
                "retrievers": {"bge": {**metrics, "recall_at_5": 0.8}},
            }
            baseline["manifest_identity_sha256"] = _identity(
                baseline, "created_at", "manifest_identity_sha256"
            )
            baseline_path = root / "old_baseline.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            report = {
                "protocol": "pcv_v22_reserve_shadow_report_r1",
                "reserve_only": True,
                "per_source_selection_performed": False,
                "datasets": {
                    "edgar": {
                        "split_identity_sha256": "split-1",
                        "reserve_source_count": 1,
                        "reserve_source_set_sha256": reserve_hash,
                        "old_semantic_purity_manifest_path": str(baseline_path),
                        "old_semantic_purity_manifest_hash": sha256_file(
                            baseline_path
                        ),
                        "bge": metrics,
                    }
                },
            }
            report_path = root / "shadow_report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            gate_dataset = {
                "split_identity_sha256": "split-1",
                "reserve_source_count": 1,
                "reserve_source_set_sha256": reserve_hash,
                "old_semantic_purity_manifest_hash": sha256_file(baseline_path),
                "old_semantic_purity_manifest_identity_sha256": baseline[
                    "manifest_identity_sha256"
                ],
                "old_semantic_purity_recall_at_5": {"bge": 0.8},
                "retrievers": {
                    "bge": {"metrics": metrics, "gates": {}, "passed": True}
                },
                "passed": True,
            }
            gate = {
                "protocol": SHADOW_GATE_PROTOCOL,
                "status": "passed",
                "created_at": "frozen",
                "input_report_path": str(report_path),
                "input_report_sha256": sha256_file(report_path),
                "protocol_identity_sha256": "protocol-1",
                "reserve_only": True,
                "per_source_selection_performed": False,
                "datasets": {"edgar": gate_dataset},
            }
            gate["shadow_gate_identity_sha256"] = _identity(
                gate, "created_at", "shadow_gate_identity_sha256"
            )
            (shadow_dir / "shadow_gate.json").write_text(
                json.dumps(gate), encoding="utf-8"
            )
            config = {
                "output_root": "artifacts/v22",
                "source_pools": {"edgar": {}},
                "shadow_validation": {"retrievers": ["bge"]},
            }
            with (
                patch(
                    "src.prepare.attackability_v22._load_protocol_manifest",
                    return_value={"protocol_identity_sha256": "protocol-1"},
                ),
                patch(
                    "src.prepare.attackability_v22._load_frozen_split",
                    return_value=(
                        {"split_identity_sha256": "split-1"},
                        [{"source_key": "source-1", "group": "Reserve"}],
                    ),
                ),
            ):
                loaded = _load_passed_shadow_gate(config, root)
                self.assertEqual(loaded["status"], "passed")
                index_payload.write_bytes(b"tampered")
                with self.assertRaisesRegex(RuntimeError, "payload drift"):
                    _load_passed_shadow_gate(config, root)


if __name__ == "__main__":
    unittest.main()
