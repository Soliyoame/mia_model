from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src.attack.restoration_first_v23 import (
    SPECIFICATION_VERSION,
    canonical_json,
    canonical_sha256,
    normalized_text_sha256,
    text_sha256,
)
from src.prepare.restoration_first_v23 import (
    DEVELOPMENT_RESERVATION_REVISION,
    SCIENTIFIC_IMPLEMENTATION_FILES,
    _read_json,
    development_attempt_identity,
    exclusive_lock,
    run_development_pilot,
    validate_development_pilot,
)
from src.utils.hash import sha256_file


MODEL_IDENTITY = {
    "model_id": "synthetic/gliner",
    "model_revision": "test",
    "package_version": "1",
    "device": "cuda",
}


class LightweightFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.dataset = "edgar"
        self.sources = [self._source(index) for index in range(2)]
        self.config_path = root / "configs/restoration_first_v23.yaml"
        self.reservation_path = (
            root
            / "artifacts/v23/governance/revision_reservations"
            / DEVELOPMENT_RESERVATION_REVISION
            / "plans/development/edgar.json"
        )
        self.aggregate_rows_path = root / "artifacts/v23/aggregate_df/edgar/token_df.jsonl"
        self.aggregate_manifest_path = (
            root / "artifacts/v23/aggregate_df/edgar/df_manifest.json"
        )
        self._write_project()

    def _source(self, index: int) -> dict:
        text = f"Alice signed agreement number {index} with Northstar Corporation."
        source_key = f"source-{index}"
        row = {
            "audit_id": f"audit-{index}",
            "doc_id": f"doc-{index}",
            "source_id": f"id-{index}",
            "source_path": f"source-{index}.txt",
            "source_key": source_key,
            "dataset": "edgar",
            "text": text,
            "text_hash": text_sha256(text),
            "chunk_index": 0,
        }
        return {
            "dataset": "edgar",
            "source_key": source_key,
            "source_order_rank": format(index + 1, "064x"),
            "full_text": text,
            "input_row_count": 1,
            "chunks": [
                {
                    "source_key": source_key,
                    "chunk_rank": 0,
                    "selection_hash": canonical_sha256(row),
                    "row": row,
                }
            ],
        }

    def _write_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(value) + "\n", encoding="utf-8")

    def _write_project(self) -> None:
        (self.root / "configs").mkdir(parents=True)
        (self.root / "configs/restoration_first_v23.design_manifest.json").write_text(
            '{"kind":"synthetic-v23-design"}\n', encoding="utf-8"
        )
        (self.root / "configs/entity_type_policy_v21_r1.yaml").write_text(
            "policy: synthetic\n", encoding="utf-8"
        )
        for relative in SCIENTIFIC_IMPLEMENTATION_FILES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {relative.as_posix()}\n", encoding="utf-8")
        prepare_path = self.root / "src/prepare/restoration_first_v23.py"
        prepare_path.parent.mkdir(parents=True, exist_ok=True)
        prepare_path.write_text("# governance v1\n", encoding="utf-8")

        pool_directory = self.root / "pool"
        pool_directory.mkdir()
        order_path = pool_directory / "source_order.json"
        self._write_json(
            order_path,
            {
                "dataset": "edgar",
                "source_order": [source["source_key"] for source in self.sources],
            },
        )
        pool_manifest_path = pool_directory / "manifest.json"
        self._write_json(pool_manifest_path, {"kind": "synthetic-pool"})
        database_path = pool_directory / "source_pool.sqlite3"
        connection = sqlite3.connect(database_path)
        connection.execute(
            "CREATE TABLE sources (source_key TEXT, source_order_rank TEXT, "
            "full_text TEXT, input_row_count INTEGER)"
        )
        connection.execute(
            "CREATE TABLE chunks (source_key TEXT, chunk_rank INTEGER, "
            "selection_hash TEXT, row_json TEXT)"
        )
        for source in self.sources:
            connection.execute(
                "INSERT INTO sources VALUES (?, ?, ?, ?)",
                (
                    source["source_key"],
                    source["source_order_rank"],
                    source["full_text"],
                    source["input_row_count"],
                ),
            )
            chunk = source["chunks"][0]
            connection.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                (
                    chunk["source_key"],
                    chunk["chunk_rank"],
                    chunk["selection_hash"],
                    canonical_json(chunk["row"]),
                ),
            )
        connection.commit()
        connection.close()

        config = {
            "protocol_version": "pcv-mia-v23",
            "specification_version": SPECIFICATION_VERSION,
            "frozen_v22_bindings": {
                "source_pools": {
                    "edgar": {
                        "manifest_path": "pool/manifest.json",
                        "manifest_sha256": sha256_file(pool_manifest_path),
                        "database_path": "pool/source_pool.sqlite3",
                        "database_sha256": sha256_file(database_path),
                        "source_order_path": "pool/source_order.json",
                        "source_order_file_sha256": sha256_file(order_path),
                        "source_count": 2,
                    }
                },
                "entity_router": {"role": "gliner2_base"},
                "extraction_rule_bindings": {
                    "entity_type_policy_path": "configs/entity_type_policy_v21_r1.yaml"
                },
            },
            "selector_primitives": {
                "text_normalization": {"unicode": "NFC"},
                "tokenization": {"pattern": "synthetic"},
            },
            "development_gate": {
                "source_count_per_dataset": 2,
                "expected_pair_count_per_eligible_source": 3,
            },
            "fresh_audit": {"reserve_source_count_per_dataset": 1},
            "forbidden_selection_inputs": ["membership", "victim_response", "auc"],
        }
        self.config_path.write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )

        reservation = {
            "kind": "v23_reservation_plan",
            "attempt_id": "a" * 64,
            "dataset": "edgar",
            "role": "development",
            "ordered_source_identity_objects": [
                {
                    "source_key": source["source_key"],
                    "source_hash": text_sha256(source["full_text"]),
                    "normalized_text_hash": normalized_text_sha256(
                        source["full_text"]
                    ),
                }
                for source in self.sources
            ],
        }
        self._write_json(self.reservation_path, reservation)
        self.write_aggregate(frequency=2)

    def write_aggregate(self, *, frequency: int) -> None:
        self.aggregate_rows_path.parent.mkdir(parents=True, exist_ok=True)
        self.aggregate_rows_path.write_text(
            canonical_json(
                {
                    "kind": "v23_token_document_frequency",
                    "token": "agreement",
                    "document_frequency": frequency,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        tokenization_contract = {
            "normalization": config["selector_primitives"]["text_normalization"],
            "tokenization": config["selector_primitives"]["tokenization"],
        }
        self._write_json(
            self.aggregate_manifest_path,
            {
                "kind": "v23_lightweight_aggregate_document_frequency",
                "dataset": "edgar",
                "source_count": 2,
                "token_count": 1,
                "token_df_rows_file_sha256": sha256_file(self.aggregate_rows_path),
                "tokenization_contract_sha256": canonical_sha256(
                    tokenization_contract
                ),
                "external_calls_performed": 0,
            },
        )


def empty_selector(source: dict, **_: object) -> dict:
    return {
        "selected_pairs": [],
        "rejection_reasons": [f"not_eligible:{source['source_key']}"],
        "candidate_count": 0,
        "pair_candidate_count": 0,
        "hard_gate_violation_count": 0,
    }


class V23LightweightDevelopmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = LightweightFixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def identity(self, **overrides: object) -> dict:
        return development_attempt_identity(
            project_root=self.root,
            dataset="edgar",
            model_runtime_identity=overrides or MODEL_IDENTITY,
        )

    def test_attempt_identity_ignores_governance_and_binds_science(self):
        first = self.identity()["attempt_id"]
        prepare_path = self.root / "src/prepare/restoration_first_v23.py"
        prepare_path.write_text("# governance v2\n", encoding="utf-8")
        self.assertEqual(self.identity()["attempt_id"], first)

        scientific_path = self.root / SCIENTIFIC_IMPLEMENTATION_FILES[0]
        scientific_path.write_text("# scientific change\n", encoding="utf-8")
        self.assertNotEqual(self.identity()["attempt_id"], first)

    def test_model_config_reservation_and_df_change_attempt_identity(self):
        first = self.identity()["attempt_id"]
        self.assertNotEqual(
            self.identity(model_id="synthetic/gliner", model_revision="new")[
                "attempt_id"
            ],
            first,
        )
        config = yaml.safe_load(self.fixture.config_path.read_text(encoding="utf-8"))
        config["development_gate"]["scientific_knob"] = "changed"
        self.fixture.config_path.write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        self.assertNotEqual(self.identity()["attempt_id"], first)

        config["development_gate"].pop("scientific_knob")
        self.fixture.config_path.write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        reservation = _read_json(self.fixture.reservation_path)
        reservation["ordered_source_identity_objects"][0]["source_hash"] = "b" * 64
        self.fixture._write_json(self.fixture.reservation_path, reservation)
        self.assertNotEqual(self.identity()["attempt_id"], first)

        reservation["ordered_source_identity_objects"][0]["source_hash"] = text_sha256(
            self.fixture.sources[0]["full_text"]
        )
        self.fixture._write_json(self.fixture.reservation_path, reservation)
        self.fixture.write_aggregate(frequency=1)
        self.assertNotEqual(self.identity()["attempt_id"], first)

    def test_interrupted_run_resumes_without_overwriting_completed_source(self):
        def interrupted(source: dict, **kwargs: object) -> dict:
            if source["source_key"] == "source-1":
                raise RuntimeError("synthetic_interrupt")
            return empty_selector(source, **kwargs)

        with self.assertRaisesRegex(RuntimeError, "synthetic_interrupt"):
            run_development_pilot(
                project_root=self.root,
                dataset="edgar",
                model_runtime_identity=MODEL_IDENTITY,
                source_selector=interrupted,
            )
        identity = self.identity()
        result_path = (
            self.root
            / "artifacts/v23/selection/development/edgar/attempts"
            / identity["attempt_id"]
            / "source_results/000000.json"
        )
        original = result_path.read_bytes()
        result = run_development_pilot(
            project_root=self.root,
            dataset="edgar",
            model_runtime_identity=MODEL_IDENTITY,
            source_selector=empty_selector,
        )
        self.assertEqual(result["status"], "failed_capacity_shortfall")
        self.assertEqual(result_path.read_bytes(), original)
        self.assertEqual(result["completed_source_count"], 2)
        self.assertEqual(result["eligible_source_count"], 0)
        self.assertEqual(list(self.root.rglob("*budget*")), [])

        repeated = run_development_pilot(
            project_root=self.root,
            dataset="edgar",
            model_runtime_identity=MODEL_IDENTITY,
            source_selector=empty_selector,
        )
        self.assertEqual(repeated, result)
        self.assertEqual(
            validate_development_pilot(
                project_root=self.root,
                dataset="edgar",
                model_runtime_identity=MODEL_IDENTITY,
            ),
            result,
        )

    def test_forbidden_selector_input_fails_closed(self):
        def forbidden(source: dict, **_: object) -> dict:
            return {"selected_pairs": [], "membership": source["source_key"]}

        with self.assertRaisesRegex(ValueError, "forbidden_selection_field"):
            run_development_pilot(
                project_root=self.root,
                dataset="edgar",
                model_runtime_identity=MODEL_IDENTITY,
                source_selector=forbidden,
            )

    def test_active_lock_rejected_and_dead_pid_recovered(self):
        lock = self.root / "attempt.lock"
        lock.write_text(
            canonical_json({"pid": os.getpid(), "kind": "test"}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "active_process_lock"):
            with exclusive_lock(lock):
                pass
        lock.write_text(
            canonical_json({"pid": 2_000_000_000, "kind": "test"}) + "\n",
            encoding="utf-8",
        )
        with exclusive_lock(lock):
            self.assertTrue(lock.exists())
        self.assertFalse(lock.exists())

    def test_identity_reads_only_edgar_reservation_and_no_git_history(self):
        paths: list[str] = []

        def recording_read(path: Path) -> dict:
            paths.append(path.as_posix())
            return _read_json(path)

        with patch(
            "src.prepare.restoration_first_v23._read_json",
            side_effect=recording_read,
        ), patch("src.prepare.restoration_first_v23.subprocess.run") as run:
            run.return_value.stdout = "c" * 40 + "\n"
            self.identity()
        self.assertTrue(any("plans/development/edgar.json" in path for path in paths))
        self.assertFalse(any("enron" in path or "pubmed" in path for path in paths))
        self.assertFalse(any("fresh_audit" in path for path in paths))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["git", "rev-parse", "HEAD"])


class V23LightweightCliTests(unittest.TestCase):
    def test_cli_exposes_only_lightweight_commands(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "scripts/42_run_v23_restoration_first.py").read_text(
            encoding="utf-8"
        )
        for command in (
            "status",
            "aggregate-df",
            "validate-aggregate-df",
            "run-development-pilot",
            "validate-development-pilot",
            "validate-development-pilot-group",
        ):
            self.assertIn(f'"{command}"', script)
        for removed in (
            "authorization",
            "successor",
            "carry-forward",
            "revision-reservation",
            "bootstrap",
        ):
            self.assertNotIn(removed, script)


if __name__ == "__main__":
    unittest.main()
