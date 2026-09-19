from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src.prepare.restoration_first_v23_formal_runtime import (
    _authorization_identity,
    _charge_formal_scan_budget,
    _ensure_formal_reservation,
    _require_bound_file,
    assert_budget_available,
    build_formal_runtime_freeze,
    canonical_sha256,
    formal_runtime_identity,
    freeze_source_exclusive_split,
    load_formal_runtime_config,
    reject_forbidden_formal_inputs,
    validate_formal_stage_authorization,
    validate_frozen_r2_evidence,
    validate_index_allowlist,
    validate_split_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _selected_sources(dataset: str = "edgar") -> list[dict]:
    rows = []
    for index in range(2_250):
        rows.append(
            {
                "kind": "v23_formal_selected_source",
                "selection_index": index,
                "dataset": dataset,
                "source_key": f"{dataset}-source-{index:04d}",
                "source_hash": canonical_sha256([dataset, "source", index]),
                "normalized_text_hash": canonical_sha256(
                    [dataset, "normalized", index]
                ),
                "source_order_rank": index,
                "ordered_pair_ids": [
                    canonical_sha256([dataset, index, pair_order])
                    for pair_order in range(3)
                ],
            }
        )
    return rows


def _authorization(
    runtime_identity: str,
    *,
    stage: str = "formal_source_scan",
    dataset: str | None = "edgar",
    backend: str | None = None,
    budget_kind: str = "sources",
    budget_limit: int = 2_500,
    run_role: str = "selector",
    gpu_allowed: bool = True,
    api_allowed: bool = False,
    victim_allowed: bool = False,
    retriever_allowed: bool = False,
    external_calls_allowed: bool = False,
) -> dict:
    value = {
        "kind": "v23_formal_stage_authorization",
        "authorization_id": "",
        "formal_runtime_identity_sha256": runtime_identity,
        "authorized_stage": stage,
        "dataset": dataset,
        "backend": backend,
        "run_role": run_role,
        "budget_kind": budget_kind,
        "budget_limit": budget_limit,
        "formal_test_allowed": True,
        "gpu_allowed": gpu_allowed,
        "api_allowed": api_allowed,
        "victim_allowed": victim_allowed,
        "retriever_allowed": retriever_allowed,
        "external_calls_allowed": external_calls_allowed,
        "user_authorization_record": "unit_test_authorization",
        "protocol_revision_id": runtime_identity,
        "expected_prior_ledger_tip_sha256": "d" * 64,
        "expected_prior_tip_anchor_sha256": "e" * 64,
        "target_selected_source_count": 2_250 if stage == "formal_source_scan" else 0,
        "issued_at": "2026-08-24T00:00:00Z",
    }
    value["authorization_id"] = _authorization_identity(value)
    return value


class FormalRuntimeFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_formal_runtime_config(PROJECT_ROOT)
        cls.evidence = validate_frozen_r2_evidence(PROJECT_ROOT, config=cls.config)
        cls.manifest = build_formal_runtime_freeze(
            PROJECT_ROOT,
            code_commit="a" * 40,
            created_at="2026-08-24T00:00:00Z",
        )

    def test_frozen_r2_packet_and_ai_diagnostic_are_bound_to_combined_gate(self):
        self.assertEqual(
            self.evidence["preparation_freeze_identity_sha256"],
            "4b90c510e7108c767f515ad6f2c13c068ceca7e778ba5c09f142dd66c8cb5b19",
        )
        self.assertEqual(self.evidence["packet_row_count"], 900)
        self.assertEqual(
            self.evidence["ai_label_counts"],
            {"pass": 875, "uncertain": 25, "fail": 0},
        )
        self.assertTrue(self.evidence["ai_diagnostic_only"])
        self.assertFalse(self.evidence["ai_evidence_accepted_as_formal_gate"])
        gate = self.manifest["verification_gate"]
        self.assertEqual(gate["status"], "passed")
        self.assertTrue(gate["project_owner_human_verification_performed"])
        self.assertFalse(gate["independent_human_blind_audit_performed"])
        self.assertFalse(gate["cohen_kappa_claim_allowed"])
        self.assertTrue(gate["combined_gate_accepted"])
        self.assertFalse(self.evidence["packet_rows_parsed"])
        self.assertFalse(self.evidence["ai_label_rows_parsed"])

    def test_runtime_identity_is_independent_of_timestamp(self):
        changed = copy.deepcopy(self.manifest)
        changed["created_at"] = "2026-08-25T00:00:00Z"
        self.assertEqual(
            formal_runtime_identity(self.manifest),
            formal_runtime_identity(changed),
        )

    def test_bound_file_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "bound.txt"
            path.write_text("frozen", encoding="utf-8")
            expected = canonical_sha256("not-the-file-byte-hash")
            with self.assertRaisesRegex(RuntimeError, "bound_file_drift"):
                _require_bound_file(root, "bound.txt", expected)

    def test_combined_gate_tamper_fails_closed(self):
        mutations = {
            "binding": ("ai_labels_sha256", "0" * 64, "binding_drift"),
            "attestation": (
                "project_owner_human_verification_performed",
                False,
                "verification_gate_drift",
            ),
        }
        for name, (field, value, error) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = copy.deepcopy(self.config)
                config["formal_contract"]["formal_scan_gate"][field] = value
                path = root / "runtime.yaml"
                path.write_text(
                    yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, error):
                    load_formal_runtime_config(root, config_path="runtime.yaml")

    def test_formal_source_scan_budget_contract_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = copy.deepcopy(self.config)
            config["formal_contract"]["formal_source_scan"][
                "first_dataset_maximum_source_reads"
            ] = 3_709
            path = root / "runtime.yaml"
            path.write_text(
                yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "source_scan_contract_drift"):
                load_formal_runtime_config(root, config_path="runtime.yaml")

    def test_manifest_records_no_downstream_execution(self):
        self.assertTrue(self.manifest["runtime_implemented"])
        self.assertTrue(self.manifest["runtime_frozen"])
        self.assertFalse(self.manifest["formal_test_started"])
        self.assertFalse(self.manifest["membership_read"])
        self.assertFalse(self.manifest["fresh_reserve_consumed"])
        self.assertEqual(self.manifest["external_calls_performed"], 0)
        self.assertEqual(
            self.manifest["status"],
            "formal_runtime_frozen_gate_passed_awaiting_formal_test_authorization",
        )


class FormalRuntimeGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.selected = _selected_sources()
        cls.split_rows = freeze_source_exclusive_split(
            cls.selected, dataset="edgar"
        )

    def test_split_is_deterministic_and_source_exclusive(self):
        rerun = freeze_source_exclusive_split(self.selected, dataset="edgar")
        self.assertEqual(rerun, self.split_rows)
        self.assertEqual(
            {group: sum(row["group"] == group for row in self.split_rows) for group in ("KB_Member", "True_Non_Member", "Reserve")},
            {"KB_Member": 1_000, "True_Non_Member": 1_000, "Reserve": 250},
        )
        self.assertEqual(len({row["source_key"] for row in self.split_rows}), 2_250)
        self.assertEqual(len({row["source_hash"] for row in self.split_rows}), 2_250)

    def test_split_rejects_duplicate_normalized_source(self):
        rows = copy.deepcopy(self.selected)
        rows[1]["normalized_text_hash"] = rows[0]["normalized_text_hash"]
        with self.assertRaisesRegex(RuntimeError, "source_or_pair_overlap"):
            freeze_source_exclusive_split(rows, dataset="edgar")

    def test_split_validator_rejects_membership_assignment_tamper(self):
        rows = copy.deepcopy(self.split_rows)
        rows[0]["group"] = "True_Non_Member"
        with self.assertRaisesRegex(RuntimeError, "split_row_invalid"):
            validate_split_rows(rows, dataset="edgar")

    def test_main_index_rejects_nonmember_contamination(self):
        members = [row for row in self.split_rows if row["group"] == "KB_Member"]
        result = validate_index_allowlist(members, allowed_group="KB_Member")
        self.assertTrue(result["main_index"])
        contaminated = copy.deepcopy(members)
        contaminated[-1] = next(
            row for row in self.split_rows if row["group"] == "True_Non_Member"
        )
        with self.assertRaisesRegex(RuntimeError, "group_contamination"):
            validate_index_allowlist(contaminated, allowed_group="KB_Member")

    def test_forbidden_membership_is_rejected_recursively(self):
        with self.assertRaisesRegex(RuntimeError, "forbidden_field"):
            reject_forbidden_formal_inputs({"safe": [{"membership": "member"}]})

    def test_stage_authorization_and_budget_fail_closed(self):
        runtime_identity = "b" * 64
        authorization = _authorization(runtime_identity)
        validated = validate_formal_stage_authorization(
            authorization,
            formal_runtime_identity_sha256=runtime_identity,
            stage="formal_source_scan",
            dataset="edgar",
            backend=None,
        )
        self.assertEqual(
            assert_budget_available(
                validated, charges_already_recorded=2_499, charge_amount=1
            ),
            {"charges_after": 2_500, "remaining": 0},
        )
        with self.assertRaisesRegex(RuntimeError, "budget_exhausted_before_operation"):
            assert_budget_available(
                validated, charges_already_recorded=2_500, charge_amount=1
            )

    def test_stage_authorization_cannot_smuggle_api_permission(self):
        runtime_identity = "c" * 64
        authorization = _authorization(runtime_identity, api_allowed=True)
        with self.assertRaisesRegex(RuntimeError, "capability_drift:api_allowed"):
            validate_formal_stage_authorization(
                authorization,
                formal_runtime_identity_sha256=runtime_identity,
                stage="formal_source_scan",
                dataset="edgar",
                backend=None,
            )

    def test_formal_scan_budget_precedes_idempotent_single_source_reservation(self):
        from src.prepare import (
            restoration_first_v23_fresh_audit_preparation_r2 as governance,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_formal_runtime_config(PROJECT_ROOT)
            ledger_path = root / config["formal_contract"]["formal_source_scan"][
                "consumption_ledger_path"
            ]
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            genesis = {
                "kind": "v23_consumption_ledger_genesis",
                "sequence": 0,
                "protocol_revision_id": "a" * 64,
                "role": "genesis",
                "dataset": "__all__",
                "source_key": "__genesis__",
                "source_hash": "__not_applicable__",
                "normalized_text_hash": "__not_applicable__",
                "consumed_at": "2026-08-24T00:00:00Z",
                "reason": "unit_test",
                "previous_row_sha256": "0" * 64,
                "design_manifest_sha256": "b" * 64,
                "frozen_v22_protocol_identity_sha256": "c" * 64,
                "source_order_file_sha256_by_dataset": {
                    "edgar": "d" * 64,
                    "enron": "e" * 64,
                    "pubmed": "f" * 64,
                },
            }
            genesis["row_sha256"] = canonical_sha256(genesis)
            ledger_path.write_text(
                __import__("json").dumps(
                    genesis,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            authorization = _authorization("9" * 64)
            authorization["expected_prior_ledger_tip_sha256"] = genesis[
                "row_sha256"
            ]
            authorization["authorization_id"] = _authorization_identity(
                authorization
            )
            identity = {
                "source_key": "edgar-source-0001",
                "source_hash": "1" * 64,
                "normalized_text_hash": "2" * 64,
            }
            budget_path = root / "budget.jsonl"
            _charge_formal_scan_budget(
                budget_path,
                authorization,
                source_order_index=1_500,
                source_key=identity["source_key"],
            )

            def governance_state(_root, _config):
                return (
                    governance,
                    {},
                    ledger_path,
                    governance._read_ledger(ledger_path),
                )

            plan_path = root / "plan.json"
            with patch(
                "src.prepare.restoration_first_v23_formal_runtime._governance_state",
                side_effect=governance_state,
            ):
                first = _ensure_formal_reservation(
                    root,
                    config,
                    authorization=authorization,
                    scan_index=0,
                    source_order_index=1_500,
                    identity=identity,
                    plan_path=plan_path,
                )
                second = _ensure_formal_reservation(
                    root,
                    config,
                    authorization=authorization,
                    scan_index=0,
                    source_order_index=1_500,
                    identity=identity,
                    plan_path=plan_path,
                )
            self.assertEqual(first, second)
            self.assertEqual(len(governance._read_ledger(ledger_path)), 2)
            self.assertEqual(
                len(list((root / "artifacts/v23/governance/ledger_anchors").glob("*.json"))),
                1,
            )


if __name__ == "__main__":
    unittest.main()
