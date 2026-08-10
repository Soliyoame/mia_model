from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from src.prepare.eligibility_scan import (
    ENRON_CAPACITY_QUERY_ELIGIBILITY_PROTOCOL,
    ENRON_CAPACITY_SCAN_PROTOCOL,
    SCAN_PROTOCOL,
    _enron_capacity_artifact_identity,
    _enron_capacity_role_identity,
    _enron_capacity_upstream_identity,
    _validate_capacity_cli_overrides,
    _validate_finalization_manifest,
    _validate_scan_config,
    validate_formal_eligibility_manifest,
    write_checkpoint,
)
from src.prepare.enron_capacity_role import enron_capacity_role_metadata
from src.utils.hash import sha256_file, sha256_obj
from src.utils.io import load_yaml, read_json, write_json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPACITY_SCAN_CONFIG = (
    PROJECT_ROOT / "configs" / "eligibility_scan_v21_enron_capacity_r2.yaml"
)


def _capacity_scan_config() -> dict[str, object]:
    payload = load_yaml(CAPACITY_SCAN_CONFIG)
    return dict(payload["eligibility_scan"])


def _capacity_plan() -> dict[str, object]:
    return {
        "protocol": ENRON_CAPACITY_SCAN_PROTOCOL,
        "scan_plan_sha256": "capacity-plan",
        "dataset": "enron",
        "source_order_sha256": "source-order",
        "wave_size": 250,
        "target_query_eligible_sources": 2250,
        "required_formal_sources": 2250,
        "candidate_pool_target_sources": 35000,
        "effective_candidate_pool_source_count": 35000,
        "scan_full_candidate_pool": True,
        "enron_capacity_role": enron_capacity_role_metadata(),
        "enron_capacity_manual_execution_acknowledged": True,
    }


class EnronCapacityRunnerTests(unittest.TestCase):
    def test_capacity_config_freezes_actual_processed_sha(self) -> None:
        config = _capacity_scan_config()
        self.assertEqual(
            config["upstream_processed"]["sha256"],
            "47ef7d2fee45d519618dddc9a1be4be6aafcf69d862cd64f35a109081419a19e",
        )
        self.assertEqual(
            config["upstream_processed"]["manifest_sha256"],
            "d4dbecb2c7c842485b230c9ecb50a8f297413292d48e00754080ee0854079aa6",
        )

    def test_capacity_config_accepts_exact_35k_and_rejects_drift(self) -> None:
        config = _capacity_scan_config()
        validated = _validate_scan_config(config, selected_cap=5)
        self.assertEqual(validated["candidate_pool_target_sources"], 35000)
        self.assertTrue(validated["scan_full_candidate_pool"])
        self.assertFalse(validated["exact_target_stop"])

        for field, value in (
            ("candidate_pool_target_sources", 30000),
            ("scan_full_candidate_pool", False),
            ("dataset", "pubmed"),
        ):
            drifted = deepcopy(config)
            drifted[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(RuntimeError, "preregistration mismatch"):
                    _validate_scan_config(drifted, selected_cap=5)

    def test_capacity_requires_manual_flag_and_rejects_flag_elsewhere(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "requires.*manual"):
            _enron_capacity_role_identity(
                scan_config=_capacity_scan_config(),
                attack_config={},
                manual_execution_acknowledged=False,
            )
        with self.assertRaisesRegex(RuntimeError, "capacity-study only"):
            _enron_capacity_role_identity(
                scan_config={"protocol": SCAN_PROTOCOL},
                attack_config={},
                manual_execution_acknowledged=True,
            )

    def test_capacity_rejects_processed_and_output_overrides(self) -> None:
        config = _capacity_scan_config()
        for processed, output in (
            ("other.jsonl", None),
            (None, "other-output"),
        ):
            with self.subTest(processed=processed, output=output):
                with self.assertRaisesRegex(RuntimeError, "forbids.*overrides"):
                    _validate_capacity_cli_overrides(
                        config,
                        processed_path_override=processed,
                        output_dir_override=output,
                    )

        _validate_capacity_cli_overrides(
            {"protocol": SCAN_PROTOCOL},
            processed_path_override="allowed-for-legacy.jsonl",
            output_dir_override=None,
        )

    def test_capacity_manifest_cannot_enter_formal_promotion(self) -> None:
        manifest = {
            "dataset": "enron",
            "protocol": ENRON_CAPACITY_QUERY_ELIGIBILITY_PROTOCOL,
            "scan_protocol": ENRON_CAPACITY_SCAN_PROTOCOL,
        }
        with self.assertRaisesRegex(RuntimeError, "cannot enter formal promotion"):
            validate_formal_eligibility_manifest(
                manifest,
                dataset="enron",
            )

    def test_capacity_upstream_hash_and_output_path_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "enron.jsonl"
            processed.write_text('{"source_id":"one"}\n', encoding="utf-8")
            manifest = root / "enron.manifest.json"
            write_json(
                {
                    "dataset": "enron",
                    "membership_unit": "complete_email",
                    "cleaner_version": (
                        "enron_cleaner_v2_preserve_forwarded_body"
                    ),
                    "chunk_limit": None,
                    "source_limit": None,
                    "raw_unique_source_count": 150000,
                    "unique_source_count": 62384,
                },
                manifest,
            )
            output_dir = root / "capacity-output"
            scan_config = {
                "protocol": ENRON_CAPACITY_SCAN_PROTOCOL,
                "candidate_pool_target_sources": 35000,
                "output_dir": str(output_dir),
                "upstream_processed": {
                    "path": str(processed),
                    "sha256": sha256_file(processed),
                    "manifest_path": str(manifest),
                    "manifest_sha256": sha256_file(manifest),
                    "unique_source_count": 62384,
                },
            }
            data_config = {
                "datasets": {
                    "enron": {
                        "source_eligibility_path": str(
                            output_dir / "enron_query_eligible_sources.json"
                        ),
                        "membership_unit": "complete_email",
                    }
                }
            }
            identity = _enron_capacity_upstream_identity(
                scan_config=scan_config,
                data_config=data_config,
                processed_path=processed,
                processed_manifest_path=manifest,
                output_dir=output_dir,
            )
            self.assertEqual(
                identity["enron_capacity_upstream_unique_source_count"],
                62384,
            )

            bad_hash = deepcopy(scan_config)
            bad_hash["upstream_processed"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "hash drift"):
                _enron_capacity_upstream_identity(
                    scan_config=bad_hash,
                    data_config=data_config,
                    processed_path=processed,
                    processed_manifest_path=manifest,
                    output_dir=output_dir,
                )

            with self.assertRaisesRegex(RuntimeError, "path isolation drift"):
                _enron_capacity_upstream_identity(
                    scan_config=scan_config,
                    data_config=data_config,
                    processed_path=processed,
                    processed_manifest_path=manifest,
                    output_dir=root / "wrong-output",
                )

    def test_capacity_checkpoint_binds_boundary_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = _capacity_plan()
            state = {
                "stop_status": "in_progress",
                "stop_reason": "operational_pause_after_complete_wave",
                "completed_waves": [{"wave_index": 0}],
                "scanned_source_count": 250,
                "scanned_prefix_source_keys_hash": "prefix",
                "eligible_source_keys": [],
                "eligible_source_count": 0,
            }
            payload = read_json(
                write_checkpoint(Path(tmp), plan, state)
            )
            expected = _enron_capacity_artifact_identity(plan)
            for key, value in expected.items():
                self.assertEqual(payload[key], value)

    def test_capacity_finalization_requires_boundary_role_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text("checkpoint", encoding="utf-8")
            query = root / "query.json"
            write_json({"status": "capacity-only"}, query)
            plan = _capacity_plan()
            identity = {
                "protocol": ENRON_CAPACITY_SCAN_PROTOCOL,
                "scan_plan_sha256": plan["scan_plan_sha256"],
                "scan_checkpoint_sha256": sha256_file(checkpoint),
                "retained_source_end": 35000,
                "outputs": {
                    "query_eligibility": {
                        "path": str(query),
                        "sha256": sha256_file(query),
                    }
                },
                "api_calls_performed": 0,
                "retriever_runs": 0,
            }
            manifest_path = root / "finalization.json"
            write_json(
                {
                    **identity,
                    "finalization_identity_sha256": sha256_obj(identity),
                },
                manifest_path,
            )
            with self.assertRaisesRegex(RuntimeError, "role identity drift"):
                _validate_finalization_manifest(
                    manifest_path,
                    plan=plan,
                    checkpoint_path=checkpoint,
                )

            complete_identity = {
                **identity,
                **_enron_capacity_artifact_identity(plan),
            }
            write_json(
                {
                    **complete_identity,
                    "finalization_identity_sha256": sha256_obj(
                        complete_identity
                    ),
                },
                manifest_path,
            )
            result = _validate_finalization_manifest(
                manifest_path,
                plan=plan,
                checkpoint_path=checkpoint,
            )
            self.assertEqual(result["status"], "capacity-only")


if __name__ == "__main__":
    unittest.main()
