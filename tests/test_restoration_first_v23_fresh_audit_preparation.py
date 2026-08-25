from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.prepare import restoration_first_v23_fresh_audit_preparation as runner


class FreshAuditPreparationTests(unittest.TestCase):
    def test_select_first_eligible_sources_preserves_reserve_order(self):
        rows = [
            {"reserve_index": 0, "eligible": False},
            {"reserve_index": 1, "eligible": True},
            {"reserve_index": 2, "eligible": True},
            {"reserve_index": 3, "eligible": True},
        ]
        selected = runner.select_first_eligible_sources(rows, required_source_count=2)
        self.assertEqual([row["reserve_index"] for row in selected], [1, 2])

    def test_source_reader_context_manager_closes_connection(self):
        reader = object.__new__(runner._FreshAuditSourceReader)
        reader.connection = mock.Mock()
        with reader as entered:
            self.assertIs(entered, reader)
        reader.connection.close.assert_called_once_with()

    def test_source_order_identity_uses_frozen_order_index(self):
        source_order = ("source-0", "source-1")
        runner._validate_source_order_identity(
            source_order,
            {"source_order_index": 1, "source_key": "source-1"},
        )
        with self.assertRaisesRegex(RuntimeError, "source_order_identity_drift"):
            runner._validate_source_order_identity(
                source_order,
                {"source_order_index": 1, "source_key": "hash-like-rank"},
            )

    def test_select_first_eligible_sources_fails_on_shortfall(self):
        with self.assertRaisesRegex(RuntimeError, "eligible_shortfall"):
            runner.select_first_eligible_sources(
                [{"reserve_index": 0, "eligible": True}],
                required_source_count=2,
            )

    def test_packet_rows_are_blind_and_deterministic(self):
        pair = {
            "pair_id": "pair-1",
            "pair_order": 0,
            "true_claim": "Alice filed the report.",
            "counterfactual_claim": "Bob filed the report.",
            "original_entity": "Alice",
            "counterfactual_entity": "Bob",
            "effective_type": "PERSON",
        }
        pairs = [
            pair,
            {**pair, "pair_id": "pair-2", "pair_order": 1},
            {**pair, "pair_id": "pair-3", "pair_order": 2},
        ]
        selected = [
            {"dataset": "enron", "source_key": "s-2", "full_text": "text 2", "selected_pairs": pairs},
            {"dataset": "edgar", "source_key": "s-1", "full_text": "text 1", "selected_pairs": pairs},
        ]
        kwargs = {
            "protocol_revision_id": "a" * 64,
            "reserve_snapshot_sha256": "b" * 64,
            "audit_secret": b"c" * 32,
        }
        first = runner.build_blind_packet_rows(selected, **kwargs)
        second = runner.build_blind_packet_rows(list(reversed(selected)), **kwargs)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 6)
        for row in first:
            self.assertEqual(set(row), runner.PACKET_VISIBLE_FIELDS)
            self.assertFalse(runner.PACKET_HIDDEN_FIELDS.intersection(row))
            self.assertNotIn("dataset", row)
            self.assertNotIn("source_key", row)

    def test_source_result_prefix_rejects_gap(self):
        expected = [
            {
                "dataset": "edgar",
                "reserve_index": 0,
                "source_order_index": 1000,
                "source_key": "source-0",
                "source_hash": "a" * 64,
                "normalized_text_hash": "b" * 64,
            },
            {
                "dataset": "edgar",
                "reserve_index": 1,
                "source_order_index": 1001,
                "source_key": "source-1",
                "source_hash": "c" * 64,
                "normalized_text_hash": "d" * 64,
            },
        ]
        row = {
            "kind": "v23_fresh_audit_source_result",
            "specification_version": "pcv-restoration-first-v23-fresh-audit-preparation-r1",
            "dataset": "edgar",
            "freeze_identity_sha256": "e" * 64,
            "dataset_identity_sha256": "f" * 64,
            "reserve_index": 1,
            "source_order_index": 1001,
            "source_key": "source-1",
            "source_hash": "c" * 64,
            "normalized_text_hash": "d" * 64,
            "full_text": "text",
            "eligible": False,
            "selected_pairs": [],
            "fact_count": 0,
            "candidate_count": 0,
            "selection_candidate_pair_count": 0,
            "rejection_reason_counts": {},
            "external_calls_performed": 0,
            "created_at": "2026-01-01T00:00:00Z",
        }
        row["source_result_sha256"] = runner._source_result_hash(row)
        with tempfile.TemporaryDirectory() as directory:
            result_directory = Path(directory)
            (result_directory / "000001.json").write_text(
                json.dumps(row), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "source_result_prefix_drift"):
                runner._load_contiguous_source_results(
                    result_directory,
                    expected,
                    dataset_identity="f" * 64,
                    freeze_identity="e" * 64,
                )

    def test_r2_manifest_file_hash_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = {
                "fact_manifest": {"status": "passed", "dataset": "edgar", "external_calls_performed": 0},
                "selection_manifest": {
                    "status": "passed",
                    "dataset": "edgar",
                    "external_calls_performed": 0,
                    "selection_attempt_id": "selection",
                    "source_fact_attempt_id": "fact",
                },
                "pilot_manifest": {
                    "status": "passed",
                    "dataset": "edgar",
                    "external_calls_performed": 0,
                    "selection_manifest_sha256": "selection-file",
                },
            }
            binding = {
                "fact_attempt_id": "fact",
                "selection_attempt_id": "selection",
                "selection_manifest_sha256": "selection-file",
            }
            for key, value in manifests.items():
                path = root / f"{key}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                binding[f"{key}_path"] = path.relative_to(root).as_posix()
                binding[f"{key}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            # The pilot binds the complete selection-manifest file hash.
            selection_hash = binding["selection_manifest_sha256"]
            pilot = {**manifests["pilot_manifest"], "selection_manifest_sha256": selection_hash}
            pilot_path = root / "pilot_manifest.json"
            pilot_path.write_text(json.dumps(pilot), encoding="utf-8")
            binding["pilot_manifest_sha256"] = hashlib.sha256(pilot_path.read_bytes()).hexdigest()
            runner._validate_r2_manifest(root, "edgar", binding)
            (root / "pilot_manifest.json").write_text(
                json.dumps({**manifests["pilot_manifest"], "status": "failed"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "bound_file_drift"):
                runner._validate_r2_manifest(root, "edgar", binding)

    def test_reserve_metadata_order_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            revision = "1" * 64
            reserve_dir = root / "plans"
            reserve_dir.mkdir()
            plan_path = reserve_dir / "edgar.json"
            snapshot_path = root / "snapshot.json"
            prior_path = root / "prior.json"
            completion_path = root / "completion.json"
            rows = [
                {"source_key": "s0", "source_hash": "a" * 64, "normalized_text_hash": "b" * 64},
                {"source_key": "s1", "source_hash": "c" * 64, "normalized_text_hash": "d" * 64},
            ]
            plan_path.write_text(json.dumps({
                "kind": "v23_reservation_plan",
                "role": "fresh_audit_reserve",
                "dataset": "edgar",
                "ordered_source_identity_objects": rows,
            }), encoding="utf-8")
            snapshot_path.write_text(json.dumps({
                "kind": "v23_fresh_audit_reserve_snapshot",
                "dataset": "edgar",
                "ordered_sources": [
                    {"source_key": "s0", "source_order_index": 1000},
                    {"source_key": "s1", "source_order_index": 1001},
                ],
            }), encoding="utf-8")
            prior_path.write_text(json.dumps({
                "kind": "v23_revision_reservation_prior_snapshot",
                "protocol_revision_id": revision,
            }), encoding="utf-8")
            completion_path.write_text(json.dumps({
                "kind": "v23_revision_reservation_group_complete",
                "protocol_revision_id": revision,
            }), encoding="utf-8")
            config = {
                "execution_reservation_revision": revision,
                "reserve_group": {
                    "prior_snapshot_path": "prior.json",
                    "group_completion_path": "completion.json",
                    "reserve_plan_directory": "plans",
                    "reserve_source_count_per_dataset": 2,
                },
                "datasets": {"edgar": {"reserve_snapshot_path": "snapshot.json"}},
            }
            runner._validate_reserve_metadata(root, config, "edgar")
            snapshot_path.write_text(json.dumps({
                "kind": "v23_fresh_audit_reserve_snapshot",
                "dataset": "edgar",
                "ordered_sources": [
                    {"source_key": "s1", "source_order_index": 1001},
                    {"source_key": "s0", "source_order_index": 1000},
                ],
            }), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "reserve_order_drift"):
                runner._validate_reserve_metadata(root, config, "edgar")

    def test_authorization_id_and_scope_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "kind": runner.RUN_AUTH_KIND,
                "specification_version": "pcv-restoration-first-v23-fresh-audit-preparation-r1",
                "stage": "dataset_preparation",
                "dataset": "edgar",
                "freeze_identity_sha256": "a" * 64,
                "budget_maximum_source_reads": 250,
                "external_calls_allowed": False,
                "api_allowed": False,
                "victim_allowed": False,
                "retriever_allowed": False,
                "formal_experiment_allowed": False,
                "user_authorization_record": "explicit preparation authorization",
                "created_at": "2026-01-01T00:00:00Z",
            }
            payload["authorization_id"] = runner.canonical_sha256(payload)
            path = root / "authorization.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(
                runner,
                "validate_preparation_freeze",
                return_value={"freeze_identity_sha256": "a" * 64},
            ):
                validated = runner.validate_run_authorization(
                    project_root=root,
                    authorization_path=path,
                    stage="dataset_preparation",
                    dataset="edgar",
                )
                self.assertEqual(validated["authorization_id"], payload["authorization_id"])
                payload["user_authorization_record"] = "tampered"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "authorization_hash_drift"):
                    runner.validate_run_authorization(
                        project_root=root,
                        authorization_path=path,
                        stage="dataset_preparation",
                        dataset="edgar",
                    )

    def test_freeze_manifest_is_idempotent(self):
        manifest = {
            "kind": "v23_fresh_audit_preparation_freeze_manifest",
            "freeze_identity_sha256": "a" * 64,
            "created_at": "2026-01-01T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(runner, "build_preparation_freeze_manifest", return_value=manifest):
                first = runner.freeze_preparation(root)
                second = runner.freeze_preparation(root)
            self.assertEqual(first["freeze_identity_sha256"], second["freeze_identity_sha256"])
            self.assertEqual(first["source_content_read"], False)


if __name__ == "__main__":
    unittest.main()
