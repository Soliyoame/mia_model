from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.prepare import restoration_first_v23_fresh_audit_preparation_r2 as runner


class FreshAuditExpandedPreparationTests(unittest.TestCase):
    def test_expanded_reserve_counts_are_versioned(self):
        config = runner.load_preparation_config(".")
        self.assertEqual(
            config["reserve_group"]["reserve_source_count_by_dataset"],
            {"edgar": 250, "enron": 1000, "pubmed": 250},
        )
        self.assertEqual(
            config["execution_reservation_revision"],
            "f004bc7511305c17066c0e869c708b828aa58d13f3a7ccc0d94a59f034f4934b",
        )

    def test_policy_freeze_is_read_only_and_bound(self):
        result = runner.validate_policy_freeze(".")
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["source_content_read"])
        self.assertFalse(result["ledger_mutation"])
        self.assertEqual(
            result["policy_freeze_identity_sha256"],
            "20b0972141748e0b8f7b6ed1565df3294a3215dc1b49f5ffaccc4b41975dcc72",
        )

    def test_compatibility_only_drift_does_not_change_freeze_identity(self):
        root = Path(".").resolve()
        manifest = runner._read_json(
            root / "configs/restoration_first_v23_fresh_audit_preparation_r2.freeze.json"
        )
        current = runner._file_hashes(root, runner._implementation_files())
        current["src/prepare/restoration_first_v23_fresh_audit_preparation_r2.py"] = "0" * 64
        with mock.patch.object(runner, "_file_hashes", return_value=current):
            result = runner._validate_implementation_binding(root, manifest)
        self.assertEqual(result["status"], "compatibility_only")
        self.assertEqual(
            manifest["freeze_identity_sha256"],
            "4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19",
        )

    def test_scientific_implementation_drift_fails_closed(self):
        root = Path(".").resolve()
        manifest = runner._read_json(
            root / "configs/restoration_first_v23_fresh_audit_preparation_r2.freeze.json"
        )
        current = runner._file_hashes(root, runner._implementation_files())
        current["src/attack/restoration_first_v23_fact_layer_selection_r2.py"] = "0" * 64
        with mock.patch.object(runner, "_file_hashes", return_value=current):
            with self.assertRaisesRegex(RuntimeError, "scientific_implementation_drift"):
                runner._validate_implementation_binding(root, manifest)

    def test_status_does_not_treat_unregistered_group_as_ready(self):
        result = runner.status(".")
        self.assertEqual(result["policy_freeze_status"], "passed")
        self.assertEqual(result["reservation_group_status"], "not_started")
        self.assertEqual(result["preparation_freeze_status"], "not_started")
        self.assertFalse(result["source_content_read"])

    def test_reservation_batch_is_hash_chained_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.jsonl"
            anchors = root / "anchors"
            anchors.mkdir()
            genesis = {
                "kind": "v23_consumption_ledger_genesis",
                "sequence": 0,
                "protocol_revision_id": "a" * 64,
                "role": "genesis",
                "dataset": "__all__",
                "source_key": "__genesis__",
                "source_hash": "__not_applicable__",
                "normalized_text_hash": "__not_applicable__",
                "consumed_at": "2026-08-20T00:00:00Z",
                "reason": "test",
                "previous_row_sha256": runner.ZERO_SHA256,
                "design_manifest_sha256": "b" * 64,
                "frozen_v22_protocol_identity_sha256": "c" * 64,
                "source_order_file_sha256_by_dataset": {
                    "edgar": "d" * 64,
                    "enron": "e" * 64,
                    "pubmed": "f" * 64,
                },
            }
            genesis["row_sha256"] = runner.canonical_sha256(genesis)
            ledger.write_text(
                runner.canonical_json(genesis) + "\n", encoding="utf-8"
            )
            anchor = {
                "kind": "v23_ledger_genesis_anchor",
                "ledger_tip_sha256": genesis["row_sha256"],
            }
            (anchors / "genesis.json").write_text(
                json.dumps(anchor), encoding="utf-8"
            )
            config = {
                "execution_reservation_revision": "1" * 64,
                "reserve_group": {
                    "ledger_path": "ledger.jsonl",
                    "ledger_anchor_directory": "anchors",
                },
            }
            authorization = {
                "authorization_id": "2" * 64,
                "budget_maximum_identity_reads": 2,
            }
            identities = [
                {
                    "source_key": "source-0",
                    "source_hash": "3" * 64,
                    "normalized_text_hash": "4" * 64,
                },
                {
                    "source_key": "source-1",
                    "source_hash": "5" * 64,
                    "normalized_text_hash": "6" * 64,
                },
            ]
            plan_path = root / "plans" / "enron.json"
            first = runner._append_batch(
                root,
                config,
                authorization,
                dataset="enron",
                identities=identities,
                expected_prior_tip=genesis["row_sha256"],
                plan_path=plan_path,
            )
            second = runner._append_batch(
                root,
                config,
                authorization,
                dataset="enron",
                identities=identities,
                expected_prior_tip=genesis["row_sha256"],
                plan_path=plan_path,
            )
            self.assertEqual(first["ledger_tip_sha256"], second["ledger_tip_sha256"])
            self.assertEqual(len(runner._read_ledger(ledger)), 3)
            budget = root / "artifacts/v23/governance/authorization_budgets" / (
                f"{authorization['authorization_id']}.jsonl"
            )
            self.assertEqual(len(runner._read_budget(budget, authorization)[0]), 2)


if __name__ == "__main__":
    unittest.main()
