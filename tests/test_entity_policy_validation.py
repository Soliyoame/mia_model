from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.attack.entity_type_policy import (
    SEMANTIC_TARGET_TYPES,
    entity_policy_metadata,
)
from src.prepare.eligibility_scan import (
    ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
    V21_SCAN_PROTOCOL,
    _entity_policy_release_identity,
    _validate_scan_config,
)
from src.prepare.entity_policy_release import (
    FORMAL_SCAN_PROTOCOL,
    RELEASE_GATE_PROTOCOL,
    validate_release_gate,
)
from src.prepare.entity_policy_audit_schema import (
    blinded_audit_schema_metadata,
)
from src.prepare.formal_evidence_scope import (
    DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES,
    FORMAL_AUDIT_TOTAL_ROWS,
    FORMAL_SEMANTIC_ENTITY_TYPES,
    formal_evidence_scope_metadata,
)
from src.prepare.formal_dataset_role_scope import (
    CAPACITY_QUALIFIED_PRIMARY_DATASETS,
    ENRON_CAPACITY_PROMOTION_PROTOCOL,
    MAIN_TABLE_DATASETS,
    STANDARD_PRIMARY_DATASETS,
    evaluate_dataset_report_roles,
    expected_report_identity,
    formal_dataset_role_scope_metadata,
)
from src.prepare.entity_policy_validation import (
    AUDIT_PROTOCOL,
    evaluate_audit,
    evaluate_source_gate,
    evaluate_type_coverage,
    prepare_blinded_audit,
)
from src.utils.hash import sha256_file, sha256_obj
from src.utils.io import read_json, read_jsonl, write_json, write_jsonl


class EntityPolicyValidationTests(unittest.TestCase):
    def test_source_gates_are_fail_closed(self) -> None:
        self.assertTrue(
            evaluate_source_gate(
                "enron", 500, 50, stage="pilot"
            )["gate_passed"]
        )
        self.assertFalse(
            evaluate_source_gate(
                "enron", 500, 49, stage="pilot"
            )["gate_passed"]
        )
        self.assertTrue(
            evaluate_source_gate(
                "edgar", 500, 390, stage="pilot"
            )["gate_passed"]
        )
        self.assertFalse(
            evaluate_source_gate(
                "pubmed", 500, 374, stage="pilot"
            )["gate_passed"]
        )

    def test_entity_type_opportunity_cannot_silently_disappear(self) -> None:
        report = evaluate_type_coverage(
            {"ORG": 100, "CONTRACT_TERM": 20},
            {"ORG": 2, "CONTRACT_TERM": 3},
        )
        self.assertFalse(report["gate_passed"])
        self.assertIn(
            "ORG:valid_pairs_below_coverage_gate",
            report["failure_reasons"],
        )

    def test_diagnostic_type_is_counted_but_does_not_gate(self) -> None:
        report = evaluate_type_coverage(
            {"PROJECT_NAME": 100},
            {"PROJECT_NAME": 1},
        )
        row = report["by_entity_type"]["PROJECT_NAME"]
        self.assertTrue(report["gate_passed"])
        self.assertEqual(row["opportunities"], 100)
        self.assertEqual(row["valid_pairs"], 1)
        self.assertEqual(row["minimum_valid_pairs"], 0)
        self.assertFalse(row["coverage_gate_required"])

    def test_formal_scan_config_and_release_gate_are_mandatory(self) -> None:
        config = {
            "protocol": ENTITY_POLICY_FORMAL_SCAN_PROTOCOL,
            "dataset": "edgar",
            "selection_seed": 42,
            "wave_size": 250,
            "candidate_pool_multiplier": None,
            "candidate_pool_target_sources": 4500,
            "candidate_pool_shortfall_policy": "fail",
            "scan_full_candidate_pool": False,
            "exact_target_stop": True,
            "target_query_eligible_sources": 2250,
            "required_formal_sources": 2250,
            "max_chunks_per_source": 5,
            "fallback_chunk_caps": [],
            "minimum_valid_claims": 3,
            "minimum_stealth_pairs": 3,
            "deduplicate_complete_sources": True,
            "sampling_manifest_path": None,
            "output_dir": (
                "artifacts/v21/formal_entity_policy_r2/eligibility/"
                "cap_5/edgar"
            ),
        }
        validated = _validate_scan_config(config, selected_cap=5)
        self.assertEqual(validated["dataset"], "edgar")
        enron_config = {
            **config,
            "dataset": "enron",
            "output_dir": (
                "artifacts/v21/formal_entity_policy_r2/eligibility/"
                "cap_5/enron"
            ),
        }
        with self.assertRaisesRegex(RuntimeError, "requires capacity promotion"):
            _validate_scan_config(enron_config, selected_cap=5)
        with self.assertRaisesRegex(RuntimeError, "requires --release-gate"):
            _entity_policy_release_identity(
                scan_config=validated,
                attack_config={},
                release_gate_path=None,
            )
        with self.assertRaisesRegex(RuntimeError, "only valid"):
            _entity_policy_release_identity(
                scan_config={"protocol": V21_SCAN_PROTOCOL},
                attack_config={},
                release_gate_path="unused.json",
            )

    def test_release_gate_validates_retained_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "inventory.json"
            inventory = {
                "protocol": "fixture",
                "status": "frozen",
                "created_at": "frozen",
                "datasets": {},
            }
            inventory["inventory_identity_sha256"] = sha256_obj(
                {
                    key: value
                    for key, value in inventory.items()
                    if key != "created_at"
                }
            )
            write_json(inventory, evidence)
            blinded = root / "blinded.jsonl"
            key_path = root / "key.jsonl"
            assistant = root / "assistant.jsonl"
            user = root / "user.jsonl"
            for path in (blinded, key_path, assistant, user):
                write_jsonl([], path)
            audit_manifest = {
                "protocol": AUDIT_PROTOCOL,
                "status": "prepared",
                "created_at": "frozen",
                "formal_evidence_scope": formal_evidence_scope_metadata(),
                "formal_dataset_role_scope": (
                    formal_dataset_role_scope_metadata()
                ),
                "blinded_schema": blinded_audit_schema_metadata(),
                "blinded_path": str(blinded.resolve()),
                "blinded_sha256": sha256_file(blinded),
                "key_path": str(key_path.resolve()),
                "key_sha256": sha256_file(key_path),
            }
            audit_manifest["audit_identity_sha256"] = sha256_obj(
                {
                    key: value
                    for key, value in audit_manifest.items()
                    if key != "created_at"
                }
            )
            audit_manifest_path = root / "audit_manifest.json"
            write_json(audit_manifest, audit_manifest_path)
            audit_report = {
                "protocol": AUDIT_PROTOCOL,
                "status": "passed",
                "formal_evidence_scope": formal_evidence_scope_metadata(),
                "formal_dataset_role_scope": (
                    formal_dataset_role_scope_metadata()
                ),
                "audit_manifest_path": str(audit_manifest_path.resolve()),
                "audit_manifest_sha256": sha256_file(audit_manifest_path),
                "assistant_labels_path": str(assistant.resolve()),
                "assistant_labels_sha256": sha256_file(assistant),
                "user_review_path": str(user.resolve()),
                "user_review_sha256": sha256_file(user),
            }
            payload = {
                "protocol": RELEASE_GATE_PROTOCOL,
                "status": "passed",
                "created_at": "frozen",
                "entity_policy": entity_policy_metadata(),
                "inventory_path": str(evidence.resolve()),
                "inventory_sha256": sha256_file(evidence),
                "inventory_identity_sha256": "inventory-id",
                "replay_reports": [],
                "pilot_reports": [],
                "formal_evidence_scope": formal_evidence_scope_metadata(),
                "formal_dataset_role_scope": (
                    formal_dataset_role_scope_metadata()
                ),
                "capacity_qualification_evidence": {
                    "fixture": "patched"
                },
                "audit_report": audit_report,
                "semantic_valid_pairs": {
                    **{entity_type: 90 for entity_type in FORMAL_SEMANTIC_ENTITY_TYPES},
                    "PROJECT_NAME": 1,
                },
                "formal_semantic_valid_pairs": {
                    entity_type: 90 for entity_type in FORMAL_SEMANTIC_ENTITY_TYPES
                },
                "formal_semantic_valid_pairs_by_dataset": {
                    dataset: {
                        entity_type: 36
                        for entity_type in FORMAL_SEMANTIC_ENTITY_TYPES
                    }
                    for dataset in MAIN_TABLE_DATASETS
                },
                "diagnostic_semantic_valid_pairs": {
                    entity_type: 1
                    for entity_type in DIAGNOSTIC_ONLY_SEMANTIC_ENTITY_TYPES
                },
                "code_commit": "commit",
                "runtime_tree_sha256": "runtime",
                "failure_reasons": [],
                "formal_scan_identity": FORMAL_SCAN_PROTOCOL,
                "enron_capacity_promotion_identity": (
                    ENRON_CAPACITY_PROMOTION_PROTOCOL
                ),
            }
            payload["release_gate_identity_sha256"] = sha256_obj(
                {key: value for key, value in payload.items() if key != "created_at"}
            )
            gate = root / "gate.json"
            write_json(payload, gate)
            with (
                patch(
                    "src.prepare.entity_policy_release."
                    "validate_capacity_qualification_evidence_metadata"
                ),
                patch(
                    "src.prepare.entity_policy_release."
                    "evaluate_dataset_report_roles",
                    return_value=[],
                ),
            ):
                self.assertEqual(validate_release_gate(gate)["status"], "passed")
            write_json({"status": "changed"}, evidence)
            with (
                patch(
                    "src.prepare.entity_policy_release."
                    "validate_capacity_qualification_evidence_metadata"
                ),
                patch(
                    "src.prepare.entity_policy_release."
                    "evaluate_dataset_report_roles",
                    return_value=[],
                ),
                self.assertRaisesRegex(RuntimeError, "evidence drift"),
            ):
                validate_release_gate(gate)

    def test_dataset_role_scope_accepts_only_frozen_role_outcomes(self) -> None:
        self.assertEqual(STANDARD_PRIMARY_DATASETS, {"edgar", "pubmed"})
        self.assertEqual(CAPACITY_QUALIFIED_PRIMARY_DATASETS, {"enron"})
        self.assertEqual(MAIN_TABLE_DATASETS, {"edgar", "enron", "pubmed"})
        replay = [
            {
                "dataset": dataset,
                "stage": "replay",
                "status": "passed",
                "report_identity_sha256": expected_report_identity(
                    "replay", dataset
                ),
                "api_calls_performed": 0,
                "retriever_runs": 0,
            }
            for dataset in ("edgar", "enron", "pubmed")
        ]
        pilot = [
            {
                "dataset": dataset,
                "stage": "pilot",
                "status": "failed" if dataset == "enron" else "passed",
                "pilot_cohort": "A",
                "report_identity_sha256": expected_report_identity(
                    "pilot", dataset
                ),
                "api_calls_performed": 0,
                "retriever_runs": 0,
            }
            for dataset in ("edgar", "enron", "pubmed")
        ]
        self.assertEqual(evaluate_dataset_report_roles(replay, pilot), [])
        pilot[1]["status"] = "passed"
        self.assertIn(
            "pilot_enron_capacity_qualified_primary_status_mismatch",
            evaluate_dataset_report_roles(replay, pilot),
        )

    def test_blinded_audit_rejects_dataset_outside_main_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accepted_path = root / "accepted.jsonl"
            write_jsonl(
                [
                    {
                        "dataset": "fixture",
                        "entity_type": "ORG",
                    }
                ],
                accepted_path,
            )
            with self.assertRaisesRegex(RuntimeError, "outside the main-table"):
                prepare_blinded_audit([accepted_path], [], root / "audit")

    def test_blinded_audit_freezes_formal_rows_and_excludes_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accepted_path = root / "accepted.jsonl"
            accepted = []
            for dataset in sorted(MAIN_TABLE_DATASETS):
                for entity_type in sorted(SEMANTIC_TARGET_TYPES):
                    for index in range(36):
                        accepted.append(
                            {
                                "dataset": dataset,
                                "source_key": (
                                    f"{dataset}-{entity_type}-{index}"
                                ),
                                "source_path": (
                                    f"/{dataset}/{entity_type}/{index}"
                                ),
                                "pair_id": (
                                    f"pair-{dataset}-{entity_type}-{index}"
                                ),
                                "fact_id": (
                                    f"fact-{dataset}-{entity_type}-{index}"
                                ),
                                "entity_type": entity_type,
                                "semantic_subtype": "fixture",
                                "true_claim": (
                                    f"{dataset} {entity_type} fact {index}"
                                ),
                                "counterfactual_claim": (
                                    f"{dataset} {entity_type} "
                                    f"counterfactual {index}"
                                ),
                                "original_entity": f"original-{index}",
                                "counterfactual_entity": f"replacement-{index}",
                            }
                        )
            write_jsonl(accepted, accepted_path)
            audit_dir = root / "audit"
            manifest = prepare_blinded_audit(
                [accepted_path],
                [],
                audit_dir,
            )
            self.assertEqual(manifest["protocol"], AUDIT_PROTOCOL)
            self.assertEqual(
                manifest["blinded_schema"],
                blinded_audit_schema_metadata(),
            )
            self.assertEqual(
                manifest["formal_dataset_role_scope"],
                formal_dataset_role_scope_metadata(),
            )
            self.assertEqual(manifest["rows"], FORMAL_AUDIT_TOTAL_ROWS)
            self.assertEqual(FORMAL_AUDIT_TOTAL_ROWS, 600)
            self.assertEqual(
                set(FORMAL_SEMANTIC_ENTITY_TYPES),
                {
                    row["entity_type"] for row in read_jsonl(manifest["key_path"])
                } - {"PROJECT_NAME"},
            )
            self.assertNotIn(
                "PROJECT_NAME",
                {row["entity_type"] for row in read_jsonl(manifest["key_path"])},
            )
            self.assertEqual(len(manifest["required_user_review_ids"]), 60)
            self.assertEqual(
                {
                    dataset: sum(
                        row["dataset"] == dataset
                        for row in read_jsonl(manifest["key_path"])
                    )
                    for dataset in MAIN_TABLE_DATASETS
                },
                {"edgar": 200, "enron": 200, "pubmed": 200},
            )

            key = list(read_jsonl(manifest["key_path"]))
            labels = []
            expected = {}
            for row in key:
                judgment = (
                    "pass"
                    if row["expected_policy_decision"] == "accepted"
                    else "fail"
                )
                expected[row["audit_id"]] = judgment
                labels.append(
                    {
                        "audit_id": row["audit_id"],
                        "entity_type": "WRONG_ON_PURPOSE",
                        "model_judgment": judgment,
                    }
                )
            labels_path = root / "assistant.jsonl"
            write_jsonl(labels, labels_path)
            reviews_path = root / "reviews.jsonl"
            write_jsonl(
                [
                    {
                        "audit_id": audit_id,
                        "human_judgment": expected[audit_id],
                    }
                    for audit_id in manifest["required_user_review_ids"]
                ],
                reviews_path,
            )
            report = evaluate_audit(
                audit_dir / "entity_policy_audit_manifest.json",
                labels_path,
                reviews_path,
            )
            self.assertEqual(report["status"], "passed")

            blinded_rows = list(read_jsonl(manifest["blinded_path"]))
            self.assertTrue(
                all("semantic_subtype" not in row for row in blinded_rows)
            )
            self.assertFalse(
                any(
                    value == "mismatched_donor_type"
                    for row in blinded_rows
                    for value in row.values()
                )
            )

            blinded_rows[0]["semantic_subtype"] = "mismatched_donor_type"
            write_jsonl(blinded_rows, manifest["blinded_path"])
            manifest_path = audit_dir / "entity_policy_audit_manifest.json"
            leaked_manifest = read_json(manifest_path)
            leaked_manifest["blinded_sha256"] = sha256_file(
                manifest["blinded_path"]
            )
            leaked_manifest["audit_identity_sha256"] = sha256_obj(
                {
                    key: value
                    for key, value in leaked_manifest.items()
                    if key not in {"created_at", "audit_identity_sha256"}
                }
            )
            write_json(leaked_manifest, manifest_path)
            with self.assertRaisesRegex(
                RuntimeError, "Blinded audit schema violation"
            ):
                evaluate_audit(manifest_path, labels_path, reviews_path)

            blinded_rows[0].pop("semantic_subtype")
            blinded_rows[0]["dataset"] = "fixture"
            write_jsonl(blinded_rows, manifest["blinded_path"])
            drifted_manifest = read_json(manifest_path)
            drifted_manifest["blinded_sha256"] = sha256_file(
                manifest["blinded_path"]
            )
            drifted_manifest["audit_identity_sha256"] = sha256_obj(
                {
                    key: value
                    for key, value in drifted_manifest.items()
                    if key not in {"created_at", "audit_identity_sha256"}
                }
            )
            write_json(drifted_manifest, manifest_path)
            with self.assertRaisesRegex(RuntimeError, "outside the main-table"):
                evaluate_audit(manifest_path, labels_path, reviews_path)


if __name__ == "__main__":
    unittest.main()
