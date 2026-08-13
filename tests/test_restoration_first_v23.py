from __future__ import annotations

import json
import math
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.attack.restoration_first_v23 import (
    SPECIFICATION_VERSION,
    aggregate_document_frequency,
    build_pair_candidates,
    canonical_json,
    canonical_sha256,
    fresh_extract_candidates,
    normalize_text,
    relation_signature,
    select_top_three,
    text_sha256,
    validate_selector_source_input,
)
from src.evaluation.restoration_first_v23 import (
    bm25_scores,
    bootstrap_index_tensor,
    build_source_scores,
    empirical_tpr_at_fpr,
    frozen_cell_score,
    parse_response,
    strict_json_object,
    tie_aware_auc,
    type7_quantile,
    validate_artifact_hash_chain,
    validate_query_output,
)
from src.prepare.restoration_first_v23 import (
    DESIGN_MANIFEST_SHA256,
    FrozenSourcePoolReader,
    GENESIS_SENTINEL,
    IMPLEMENTATION_STAGE,
    ZERO_SHA256,
    append_reservation_batch,
    allocate_bootstrap_attempt,
    allocate_attempt,
    attempt_id,
    bootstrap_attempt_id,
    build_runtime_bundle_manifest,
    capacity_decision,
    canonical_sha256 as governance_canonical_sha256,
    charge_authorization_budget,
    prepare_aggregate_df_authorization,
    prepare_runtime_bootstrap_authorization,
    prepare_runtime_successor_freeze_authorization,
    protocol_revision_id,
    require_passed_checkpoint,
    run_aggregate_df,
    run_runtime_bootstrap,
    run_runtime_successor_freeze,
    validate_active_runtime,
    validate_aggregate_df,
    validate_implementation_authorization,
    validate_ledger,
    validate_index_allowlist,
    validate_run_authorization,
    validate_runtime_bootstrap_authorization,
    validate_runtime_bootstrap,
    validate_runtime_successor_freeze,
    v23_status,
    evaluate_blind_audit,
    freeze_source_exclusive_split,
    write_stage_checkpoint,
)
from src.utils.hash import sha256_file


def _run_git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _bootstrap_fixture(root: Path) -> dict[str, object]:
    repository_root = Path(__file__).resolve().parents[1]
    (root / "configs").mkdir(parents=True)
    shutil.copy2(
        repository_root / "configs/restoration_first_v23.yaml",
        root / "configs/restoration_first_v23.yaml",
    )
    shutil.copy2(
        repository_root / "configs/restoration_first_v23.design_manifest.json",
        root / "configs/restoration_first_v23.design_manifest.json",
    )
    runtime_path = root / "runtime.py"
    runtime_path.write_text("VALUE = 1\n", encoding="utf-8")
    requirements_path = root / "requirements.txt"
    requirements_path.write_text("numpy==2.4.4\n", encoding="utf-8")
    model_root = root / "models/gliner2-base-v1"
    model_root.mkdir(parents=True)
    tokenizer_path = model_root / "tokenizer_config.json"
    tokenizer_path.write_text('{"model_max_length":512}\n', encoding="utf-8")
    tokenizer_sha256 = sha256_file(tokenizer_path)
    lock_path = root / "model_lock.yaml"
    lock_path.write_text(
        "\n".join(
            [
                "models:",
                "- model_id: fastino/gliner2-base-v1",
                "  backend: gliner2",
                "  role: gliner2_base",
                "  local_path: models/gliner2-base-v1",
                "  revision: f5b2ecedebe4381b088c1cf276f5bf72a52cac54",
                "  package: gliner2",
                "  package_version: 1.3.2",
                "  files_sha256:",
                f"    tokenizer_config.json: {tokenizer_sha256}",
                f"    model.safetensors: {'a' * 64}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _run_git(root, "init", "--quiet")
    _run_git(root, "config", "core.autocrlf", "false")
    _run_git(root, "config", "user.email", "v23-test@example.invalid")
    _run_git(root, "config", "user.name", "V23 Test")
    _run_git(root, "add", "runtime.py", "requirements.txt")
    _run_git(root, "commit", "--quiet", "-m", "test: freeze runtime")
    return {
        "runtime_files": ["requirements.txt", "runtime.py"],
        "dependency_lock_path": "requirements.txt",
        "model_lock_path": "model_lock.yaml",
        "runtime_path": runtime_path,
        "tokenizer_path": tokenizer_path,
    }


def _synthetic_aggregate_contracts(
    root: Path,
    *,
    dataset: str = "edgar",
    source_texts: tuple[str, ...] = ("Alpha alpha beta", "Beta gamma"),
) -> dict[str, object]:
    pool_root = root / "synthetic_pool" / dataset
    pool_root.mkdir(parents=True)
    database = pool_root / "source_pool.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE sources (source_key TEXT PRIMARY KEY, source_order_rank TEXT NOT NULL, full_text TEXT NOT NULL, input_row_count INTEGER NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE chunks (source_key TEXT NOT NULL, chunk_rank INTEGER NOT NULL, selection_hash TEXT NOT NULL, row_json TEXT NOT NULL, PRIMARY KEY (source_key, chunk_rank))"
    )
    source_order: list[str] = []
    for index, text in enumerate(source_texts):
        source_key = f"source-{index + 1}"
        source_order.append(source_key)
        rank = f"{index:06d}"
        connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?)",
            (source_key, rank, text, 1),
        )
        row = {
            "audit_id": f"audit-{index + 1}",
            "doc_id": f"doc-{index + 1}",
            "source_id": source_key,
            "source_path": "synthetic.jsonl",
            "source_key": source_key,
            "dataset": dataset,
            "text": text,
            "text_hash": text_sha256(text),
            "chunk_index": 0,
        }
        connection.execute(
            "INSERT INTO chunks VALUES (?, ?, ?, ?)",
            (source_key, 0, str(index + 1) * 64, json.dumps(row)),
        )
    connection.commit()
    connection.close()
    order = pool_root / "source_order.json"
    order.write_text(
        json.dumps(
            {
                "protocol": "synthetic",
                "dataset": dataset,
                "selection_seed": 42,
                "source_order": source_order,
                "source_order_sha256": "a" * 64,
                "label_fields_read": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = pool_root / "source_pool_manifest.json"
    manifest.write_text('{"kind":"synthetic_source_pool"}\n', encoding="utf-8")
    return {
        "pool": {
            "manifest_path": str(manifest.relative_to(root)),
            "manifest_sha256": sha256_file(manifest),
            "database_path": str(database.relative_to(root)),
            "database_sha256": sha256_file(database),
            "source_order_path": str(order.relative_to(root)),
            "source_order_file_sha256": sha256_file(order),
            "source_count": len(source_texts),
        },
        "normalization_version": "synthetic_normalization",
        "tokenization_contract": {
            "normalization": {"name": "synthetic_normalization"},
            "tokenization": {"name": "selector_content_tokens"},
        },
    }


def _bootstrap_synthetic_runtime(root: Path) -> tuple[dict[str, object], bytes]:
    fixture = _bootstrap_fixture(root)
    authorization = prepare_runtime_bootstrap_authorization(
        project_root=root,
        user_authorization_record="test bootstrap",
    )
    run_runtime_bootstrap(
        project_root=root,
        authorization_path=authorization["authorization_path"],
        runtime_files=fixture["runtime_files"],
        dependency_lock_path=fixture["dependency_lock_path"],
        model_lock_path=fixture["model_lock_path"],
    )
    ledger = root / "artifacts/v23/governance/consumed_source_ledger.jsonl"
    return fixture, ledger.read_bytes()


def _source(*, extra_row: dict | None = None) -> dict:
    sentence = "Alice signed the Northstar Services Agreement with Harborview Partners in Cedar City."
    row = {
        "audit_id": "audit-1",
        "doc_id": "doc-1",
        "source_id": "source-1",
        "source_path": "synthetic.jsonl",
        "source_key": "source-1",
        "dataset": "edgar",
        "text": sentence,
        "text_hash": text_sha256(sentence),
        "chunk_index": 0,
    }
    if extra_row:
        row.update(extra_row)
    return {
        "dataset": "edgar",
        "source_key": "source-1",
        "source_order_rank": "000001",
        "full_text": sentence,
        "input_row_count": 1,
        "chunks": [
            {
                "source_key": "source-1",
                "chunk_rank": 0,
                "selection_hash": "a" * 64,
                "row": row,
            }
        ],
    }


def _candidate(
    *,
    sentence: str | None = None,
    original: str = "Alice",
    counterfactual_pool: list[str] | None = None,
    effective_type: str = "PERSON",
    semantic_subtype: str = "single_person_name",
) -> dict:
    sentence = sentence or _source()["full_text"]
    start = sentence.index(original)
    masked = sentence[:start] + "ENTITY_SLOT" + sentence[start + len(original) :]
    signature = relation_signature(
        dataset="edgar",
        source_key="source-1",
        effective_type=effective_type,
        masked_sentence=masked,
    )
    return {
        "dataset": "edgar",
        "source_key": "source-1",
        "source_order_rank": "000001",
        "supporting_sentence": sentence,
        "original_entity": original,
        "original_span": [start, start + len(original)],
        "effective_type": effective_type,
        "semantic_subtype": semantic_subtype,
        "entity_spans": [[start, start + len(original)]],
        "filler_inventory": [
            {
                "surface": original,
                "effective_type": effective_type,
                "relation_signature": signature,
                "proposition_raw_start": 0,
                "proposition_raw_end": len(sentence),
                "filler_span": [start, start + len(original)],
            }
        ],
        "counterfactual_pool": counterfactual_pool
        or ["Jordan Ellis", "Taylor Morgan", "Morgan Lee"],
    }


def _token_df(source: dict) -> dict[str, int]:
    token_df, _ = aggregate_document_frequency([source["full_text"]] + ["generic text"] * 99)
    return token_df


def _genesis_row(protocol_revision: str) -> dict:
    row = {
        "kind": "v23_consumption_ledger_genesis",
        "sequence": 0,
        "protocol_revision_id": protocol_revision,
        "role": "genesis",
        "dataset": "__all__",
        "source_key": "__genesis__",
        "source_hash": "__not_applicable__",
        "normalized_text_hash": "__not_applicable__",
        "consumed_at": "2026-08-13T00:00:00Z",
        "reason": "runtime bootstrap",
        "previous_row_sha256": ZERO_SHA256,
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "frozen_v22_protocol_identity_sha256": "b" * 64,
        "source_order_file_sha256_by_dataset": {
            "edgar": "c" * 64,
            "enron": "d" * 64,
            "pubmed": "e" * 64,
        },
    }
    row["row_sha256"] = canonical_sha256(row)
    return row


def _attempt_registry_row(
    *,
    protocol_revision: str,
    stage: str,
    execution_unit: str,
    attempt_ordinal: int,
    expected_prior_tip: str,
    sequence: int = 0,
) -> dict:
    identity = attempt_id(
        protocol_revision=protocol_revision,
        stage=stage,
        execution_unit=execution_unit,
        attempt_ordinal=attempt_ordinal,
        expected_prior_ledger_tip_sha256=expected_prior_tip,
    )
    row = {
        "kind": "v23_attempt_registry_row",
        "sequence": sequence,
        "protocol_revision_id": protocol_revision,
        "stage": stage,
        "execution_unit": execution_unit,
        "attempt_ordinal": attempt_ordinal,
        "expected_prior_ledger_tip_sha256": expected_prior_tip,
        "attempt_id": identity,
        "previous_row_sha256": ZERO_SHA256,
        "allocated_at": "2026-08-13T00:00:00Z",
    }
    row["row_sha256"] = canonical_sha256(row)
    return row


def _run_authorization(
    *,
    runtime_hash: str,
    registry_row: dict,
    datasets: list[str],
    run_roles: list[str],
    budget_limit: int,
) -> dict:
    payload = {
        "kind": "v23_run_authorization",
        "user_authorization_record": "test",
        "protocol_revision_id": registry_row["protocol_revision_id"],
        "attempt_id": registry_row["attempt_id"],
        "authorized_stage": registry_row["stage"],
        "execution_unit": registry_row["execution_unit"],
        "expected_prior_ledger_tip_sha256": registry_row[
            "expected_prior_ledger_tip_sha256"
        ],
        "datasets": sorted(datasets),
        "run_roles": sorted(run_roles),
        "model_or_retriever_cells": [],
        "budget_kind": "sources",
        "budget_limit": budget_limit,
        "issued_at": "2026-08-13T00:00:00Z",
        "expires_at_or_null": None,
        "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
        "runtime_bundle_sha256": runtime_hash,
    }
    payload["authorization_id"] = canonical_sha256(payload)
    return payload


class V23PrimitiveTests(unittest.TestCase):
    def test_normalization_and_canonical_json_golden_vectors(self):
        self.assertEqual(normalize_text("  Cafe\u0301\tACME  "), "café acme")
        payload = {
            "kind": "v23_fact_signature",
            "dataset": "edgar",
            "source_key": "source-1",
            "sentence_hash": "a" * 64,
        }
        self.assertEqual(
            canonical_json(payload),
            '{"dataset":"edgar","kind":"v23_fact_signature","sentence_hash":"'
            + "a" * 64
            + '","source_key":"source-1"}',
        )
        self.assertEqual(
            canonical_sha256(payload),
            "5cb640436a1aaf6aa1f07e20aaba9e3f7f4fa9f3f3c43f42044beb0b0264e74b",
        )

    def test_recursive_allowlist_rejects_unknown_and_downstream_fields(self):
        validated = validate_selector_source_input(_source())
        self.assertEqual(validated["source_key"], "source-1")
        with self.assertRaisesRegex(ValueError, "selector_schema_error"):
            validate_selector_source_input(_source(extra_row={"unknown": 1}))
        with self.assertRaisesRegex(ValueError, "forbidden_selection_field"):
            validate_selector_source_input(
                _source(extra_row={"victim_response": {"stance": "supported"}})
            )
        with self.assertRaisesRegex(ValueError, "forbidden_selection_field"):
            validate_selector_source_input(
                _source(extra_row={"metadata": {"attack_auc": 0.99}})
            )

    def test_aggregate_df_is_boolean_and_has_no_source_mapping(self):
        rows, count = aggregate_document_frequency(["Alpha alpha beta", "Beta gamma"])
        self.assertEqual(count, 2)
        self.assertEqual(rows, {"alpha": 1, "beta": 2, "gamma": 1})
        self.assertNotIn("source_key", rows)


class V23SelectorTests(unittest.TestCase):
    def test_fresh_extraction_uses_internal_emitter_and_frozen_pool(self):
        source = _source()

        def emitter(text: str, dataset: str) -> list[dict]:
            self.assertEqual(dataset, "edgar")
            output = []
            for surface, label in (
                ("Alice", "PERSON"),
                ("Northstar Services Agreement", "CONTRACT_TERM"),
                ("Harborview Partners", "ORG"),
                ("Cedar City", "LOCATION"),
            ):
                if surface in text:
                    start = text.index(surface)
                    output.append(
                        {
                            "label": label,
                            "start": start,
                            "end": start + len(surface),
                            "score": 0.95,
                            "text": surface,
                        }
                    )
            return output

        rows = fresh_extract_candidates(
            source,
            model_emitter=emitter,
            entity_policy_path="configs/entity_type_policy_v21_r1.yaml",
        )
        alice = next(row for row in rows if row["original_entity"] == "Alice")
        self.assertEqual(alice["semantic_subtype"], "single_person_name")
        self.assertEqual(
            alice["counterfactual_pool"][:2], ["Jordan", "Taylor"]
        )
        self.assertTrue(
            all("score" not in item for item in alice["filler_inventory"])
        )
        self.assertTrue(
            all(
                set(item)
                == {
                    "surface",
                    "effective_type",
                    "relation_signature",
                    "proposition_raw_start",
                    "proposition_raw_end",
                    "filler_span",
                }
                for item in alice["filler_inventory"]
            )
        )

    def test_hard_gates_and_pair_generation_are_deterministic(self):
        source = _source()
        candidate = _candidate()
        first, reasons = build_pair_candidates(
            source, candidate, token_df=_token_df(source), source_count=100
        )
        second, second_reasons = build_pair_candidates(
            source,
            {**candidate, "counterfactual_pool": list(reversed(candidate["counterfactual_pool"]))},
            token_df=_token_df(source),
            source_count=100,
        )
        self.assertEqual(reasons, ())
        self.assertEqual(second_reasons, ())
        self.assertEqual([row["pair_id"] for row in first], [row["pair_id"] for row in second])
        self.assertTrue(all(len(row["rank_tuple"]) == 17 for row in first))
        self.assertTrue(all(row["true_claim"] == source["full_text"] for row in first))

    def test_source_present_counterfactual_and_competing_filler_fail_closed(self):
        source = _source()
        candidate = _candidate(
            counterfactual_pool=["Harborview Partners", "Jordan Ellis"]
        )
        pairs, reasons = build_pair_candidates(
            source, candidate, token_df=_token_df(source), source_count=100
        )
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["counterfactual_entity"], "Jordan Ellis")
        relation = candidate["filler_inventory"][0]["relation_signature"]
        candidate["filler_inventory"].append(
            {
                "surface": "Bob",
                "effective_type": "PERSON",
                "relation_signature": relation,
                "proposition_raw_start": 0,
                "proposition_raw_end": len(source["full_text"]),
                "filler_span": [0, 3],
            }
        )
        rejected, reasons = build_pair_candidates(
            source, candidate, token_df=_token_df(source), source_count=100
        )
        self.assertEqual(rejected, [])
        self.assertIn("competing_relation_filler", reasons)

    def test_duplicate_matching_propositions_fail_recoverability(self):
        source = _source()
        candidate = _candidate()
        duplicate = dict(candidate["filler_inventory"][0])
        duplicate["proposition_raw_start"] = len(source["full_text"]) + 1
        duplicate["proposition_raw_end"] = duplicate["proposition_raw_start"] + len(
            source["full_text"]
        )
        candidate["filler_inventory"].append(duplicate)
        pairs, reasons = build_pair_candidates(
            source, candidate, token_df=_token_df(source), source_count=100
        )
        self.assertEqual(pairs, [])
        self.assertIn("matching_supporting_proposition_count", reasons)

    def test_stable_greedy_requires_three_distinct_facts_and_entity_cap(self):
        rows = []
        for index, (fact, entity) in enumerate(
            [("f1", "Alice"), ("f2", "Alice"), ("f3", "Alice"), ("f4", "Bob")]
        ):
            rows.append(
                {
                    "kind": "v23_pair_candidate",
                    "rank_tuple": [0] * 13 + [fact, index, f"counter-{index}", f"pair-{index}"],
                    "fact_signature": fact,
                    "original_entity": entity,
                    "pair_id": f"pair-{index}",
                }
            )
        selected = select_top_three(rows)
        self.assertEqual([row["fact_signature"] for row in selected], ["f1", "f2", "f4"])
        self.assertEqual([row["pair_order"] for row in selected], [0, 1, 2])
        self.assertEqual(select_top_three(rows[:2]), [])


class V23GovernanceTests(unittest.TestCase):
    def test_frozen_source_pool_reader_enforces_hash_schema_and_read_only_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "pool.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE sources (source_key TEXT PRIMARY KEY, source_order_rank TEXT NOT NULL, full_text TEXT NOT NULL, input_row_count INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE chunks (source_key TEXT NOT NULL, chunk_rank INTEGER NOT NULL, selection_hash TEXT NOT NULL, row_json TEXT NOT NULL, PRIMARY KEY (source_key, chunk_rank))"
            )
            source = _source()
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
                    json.dumps(chunk["row"]),
                ),
            )
            connection.commit()
            connection.close()
            order = root / "source_order.json"
            order.write_text(
                json.dumps(
                    {
                        "protocol": "synthetic",
                        "dataset": "edgar",
                        "selection_seed": 42,
                        "source_order": ["source-1"],
                        "source_order_sha256": "a" * 64,
                        "label_fields_read": [],
                    }
                ),
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text("{}\n", encoding="utf-8")
            runtime_hash = "f" * 64
            revision = protocol_revision_id(runtime_hash, 0)
            registry = _attempt_registry_row(
                protocol_revision=revision,
                stage="aggregate_df_precomputation",
                execution_unit="one_dataset",
                attempt_ordinal=0,
                expected_prior_tip=GENESIS_SENTINEL,
            )
            authorization = _run_authorization(
                runtime_hash=runtime_hash,
                registry_row=registry,
                datasets=["edgar"],
                run_roles=[],
                budget_limit=1,
            )
            with FrozenSourcePoolReader(
                project_root=root,
                dataset="edgar",
                database_path="pool.sqlite3",
                database_sha256=sha256_file(database),
                source_order_path="source_order.json",
                source_order_file_sha256=sha256_file(order),
                source_pool_manifest_path="manifest.json",
                source_pool_manifest_sha256=sha256_file(manifest),
                expected_source_count=1,
            ) as reader:
                with self.assertRaisesRegex(RuntimeError, "unguarded_source_read_forbidden"):
                    reader.read_source("source-1")
                loaded = reader.read_source_for_aggregate_df(
                    "source-1",
                    authorization=authorization,
                    attempt_registry_row=registry,
                    budget_journal_path=root / "aggregate_df_budget.jsonl",
                )
                self.assertEqual(loaded["full_text"], source["full_text"])
                with self.assertRaisesRegex(RuntimeError, "operation_already_charged"):
                    reader.read_source_for_aggregate_df(
                        "source-1",
                        authorization=authorization,
                        attempt_registry_row=registry,
                        budget_journal_path=root / "aggregate_df_budget.jsonl",
                    )
                with self.assertRaises(sqlite3.OperationalError):
                    reader._connection.execute(
                        "INSERT INTO sources VALUES ('x', 'x', 'x', 1)"
                    )

    def test_bootstrap_authorization_runtime_bundle_and_attempt_registry(self):
        bootstrap_id = bootstrap_attempt_id(bootstrap_attempt_ordinal=0)
        authorization = {
            "kind": "v23_runtime_bootstrap_authorization",
            "user_authorization_record": "test",
            "authorized_stage": "runtime_bundle_and_commit_freeze",
            "execution_unit": "global",
            "bootstrap_attempt_id": bootstrap_id,
            "expected_prior_ledger_tip_sha256": GENESIS_SENTINEL,
            "issued_at": "2026-08-13T00:00:00Z",
            "expires_at_or_null": None,
            "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
            "external_calls_allowed": False,
        }
        authorization["authorization_id"] = canonical_sha256(authorization)
        self.assertEqual(
            validate_runtime_bootstrap_authorization(authorization)[
                "bootstrap_attempt_id"
            ],
            bootstrap_id,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "requirements.txt").write_text("numpy==1\n", encoding="utf-8")
            (root / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
            manifest = build_runtime_bundle_manifest(
                project_root=root,
                runtime_files=["runtime.py"],
                dependency_lock_path="requirements.txt",
                code_commit="test-commit",
                numpy_version="2.0.0",
                pcg64_state_golden_sha256="a" * 64,
                gliner_runtime_identity={
                    "model_id": "fastino/gliner2-base-v1",
                    "model_revision": "revision",
                    "model_snapshot_sha256": "b" * 64,
                    "transformers_version": "1",
                    "torch_version": "1",
                    "gliner_library_version": "1",
                    "tokenizer_or_processor_sha256": "c" * 64,
                    "device_type": "cuda",
                    "precision": "float16",
                    "deterministic_algorithms": True,
                    "inference_batch_size": 1,
                },
            )
            self.assertEqual(manifest["kind"], "v23_runtime_bundle_manifest")
            revision = protocol_revision_id("f" * 64, 0)
            first = allocate_attempt(
                registry_path=root / "attempts.jsonl",
                protocol_revision=revision,
                stage="aggregate_df_precomputation",
                execution_unit="one_dataset",
                expected_prior_ledger_tip_sha256=GENESIS_SENTINEL,
            )
            second = allocate_attempt(
                registry_path=root / "attempts.jsonl",
                protocol_revision=revision,
                stage="aggregate_df_precomputation",
                execution_unit="one_dataset",
                expected_prior_ledger_tip_sha256=GENESIS_SENTINEL,
            )
            self.assertEqual((first["attempt_ordinal"], second["attempt_ordinal"]), (0, 1))

    def test_runtime_bootstrap_success_closes_all_identity_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _bootstrap_fixture(root)
            authorization = prepare_runtime_bootstrap_authorization(
                project_root=root,
                user_authorization_record="开始吧",
            )
            result = run_runtime_bootstrap(
                project_root=root,
                authorization_path=authorization["authorization_path"],
                runtime_files=fixture["runtime_files"],
                dependency_lock_path=fixture["dependency_lock_path"],
                model_lock_path=fixture["model_lock_path"],
            )
            self.assertTrue(result["runtime_bundle_frozen"])
            self.assertFalse(result["source_pool_contents_read"])
            self.assertEqual(result["external_calls_performed"], 0)
            self.assertEqual(
                validate_ledger(
                    root / "artifacts/v23/governance/consumed_source_ledger.jsonl"
                )["row_count"],
                1,
            )

    def test_runtime_bootstrap_rejects_missing_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _bootstrap_fixture(root)
            with self.assertRaises(FileNotFoundError):
                run_runtime_bootstrap(
                    project_root=root,
                    authorization_path="artifacts/v23/governance/runtime_bootstrap_authorizations/missing.json",
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )

    def test_runtime_bootstrap_rejects_second_preparation_and_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _bootstrap_fixture(root)
            authorization = prepare_runtime_bootstrap_authorization(
                project_root=root,
                user_authorization_record="开始吧",
            )
            with self.assertRaisesRegex(RuntimeError, "preparation_already_exists"):
                prepare_runtime_bootstrap_authorization(
                    project_root=root,
                    user_authorization_record="开始吧",
                )
            run_runtime_bootstrap(
                project_root=root,
                authorization_path=authorization["authorization_path"],
                runtime_files=fixture["runtime_files"],
                dependency_lock_path=fixture["dependency_lock_path"],
                model_lock_path=fixture["model_lock_path"],
            )
            with self.assertRaisesRegex(RuntimeError, "existing_or_partial_artifact"):
                run_runtime_bootstrap(
                    project_root=root,
                    authorization_path=authorization["authorization_path"],
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )

    def test_runtime_bootstrap_rejects_code_commit_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _bootstrap_fixture(root)
            authorization = prepare_runtime_bootstrap_authorization(
                project_root=root,
                user_authorization_record="开始吧",
            )
            fixture["runtime_path"].write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "runtime_file_closure_not_clean"):
                run_runtime_bootstrap(
                    project_root=root,
                    authorization_path=authorization["authorization_path"],
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )

    def test_runtime_bootstrap_rejects_model_lock_file_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _bootstrap_fixture(root)
            authorization = prepare_runtime_bootstrap_authorization(
                project_root=root,
                user_authorization_record="开始吧",
            )
            fixture["tokenizer_path"].write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "model_file_hash_drift"):
                run_runtime_bootstrap(
                    project_root=root,
                    authorization_path=authorization["authorization_path"],
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )

    def test_runtime_bootstrap_rejects_partial_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _bootstrap_fixture(root)
            authorization = prepare_runtime_bootstrap_authorization(
                project_root=root,
                user_authorization_record="开始吧",
            )
            ledger = root / "artifacts/v23/governance/consumed_source_ledger.jsonl"
            ledger.write_text("partial", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "existing_or_partial_artifact"):
                run_runtime_bootstrap(
                    project_root=root,
                    authorization_path=authorization["authorization_path"],
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )

    def test_runtime_bootstrap_post_validation_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _bootstrap_fixture(root)
            authorization = prepare_runtime_bootstrap_authorization(
                project_root=root,
                user_authorization_record="开始吧",
            )
            run_runtime_bootstrap(
                project_root=root,
                authorization_path=authorization["authorization_path"],
                runtime_files=fixture["runtime_files"],
                dependency_lock_path=fixture["dependency_lock_path"],
                model_lock_path=fixture["model_lock_path"],
            )
            ledger = root / "artifacts/v23/governance/consumed_source_ledger.jsonl"
            genesis = json.loads(ledger.read_text(encoding="utf-8"))
            genesis["reason"] = "tampered"
            ledger.write_text(canonical_json(genesis) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "row_hash_drift"):
                validate_runtime_bootstrap(
                    root,
                    authorization_path=authorization["authorization_path"],
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )

    def test_successor_runtime_freeze_preserves_revision_zero_and_genesis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, ledger_before = _bootstrap_synthetic_runtime(root)
            fixture["runtime_path"].write_text("VALUE = 2\n", encoding="utf-8")
            _run_git(root, "add", "runtime.py")
            _run_git(root, "commit", "--quiet", "-m", "test: successor runtime")
            authorization = prepare_runtime_successor_freeze_authorization(
                project_root=root,
                user_authorization_record="test successor freeze",
                runtime_files=fixture["runtime_files"],
                dependency_lock_path=fixture["dependency_lock_path"],
                model_lock_path=fixture["model_lock_path"],
            )
            result = run_runtime_successor_freeze(
                project_root=root,
                authorization_path=authorization["authorization_path"],
                runtime_files=fixture["runtime_files"],
                dependency_lock_path=fixture["dependency_lock_path"],
                model_lock_path=fixture["model_lock_path"],
            )
            self.assertEqual(result["revision_ordinal"], 1)
            self.assertEqual(
                validate_runtime_successor_freeze(
                    project_root=root,
                    authorization_path=authorization["authorization_path"],
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )["protocol_revision_id"],
                authorization["new_protocol_revision_id"],
            )
            revisions = list((root / "artifacts/v23/protocol/revisions").glob("*.json"))
            bundles = list(
                (root / "artifacts/v23/protocol/runtime_bundles").glob(
                    "*/runtime_bundle_manifest.json"
                )
            )
            self.assertEqual((len(revisions), len(bundles)), (2, 2))
            self.assertEqual(
                (root / "artifacts/v23/governance/consumed_source_ledger.jsonl").read_bytes(),
                ledger_before,
            )

    def test_status_reports_active_successor_runtime_identity(self):
        bootstrap = {
            "runtime_bundle_frozen": True,
            "runtime_bundle_sha256": "a" * 64,
            "protocol_revision_id": "b" * 64,
        }
        active = {
            "runtime_bundle_sha256": "c" * 64,
            "protocol_revision_id": "d" * 64,
        }
        with patch(
            "src.prepare.restoration_first_v23.validate_bootstrap_design_identity",
            return_value={"design_manifest_sha256": DESIGN_MANIFEST_SHA256},
        ), patch(
            "src.prepare.restoration_first_v23._directory_has_entries",
            return_value=True,
        ), patch(
            "src.prepare.restoration_first_v23.validate_runtime_bootstrap",
            return_value=bootstrap,
        ), patch(
            "src.prepare.restoration_first_v23.validate_active_runtime",
            return_value=active,
        ):
            status = v23_status(project_root=Path("."))
        self.assertEqual(status["status"], "runtime_frozen_downstream_blocked")
        self.assertTrue(status["runtime_bundle_frozen"])
        self.assertEqual(status["runtime_bundle_sha256"], active["runtime_bundle_sha256"])
        self.assertEqual(status["protocol_revision_id"], active["protocol_revision_id"])

    def test_aggregate_df_runner_success_is_boolean_private_and_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, ledger_before = _bootstrap_synthetic_runtime(root)
            contracts = _synthetic_aggregate_contracts(root)
            with patch(
                "src.prepare.restoration_first_v23._aggregate_df_contracts",
                return_value=contracts,
            ):
                authorization = prepare_aggregate_df_authorization(
                    project_root=root,
                    dataset="edgar",
                    user_authorization_record="test aggregate df",
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )
                with self.assertRaisesRegex(
                    RuntimeError, "attempt_or_artifact_already_exists"
                ):
                    prepare_aggregate_df_authorization(
                        project_root=root,
                        dataset="edgar",
                        user_authorization_record="duplicate",
                        runtime_files=fixture["runtime_files"],
                        dependency_lock_path=fixture["dependency_lock_path"],
                        model_lock_path=fixture["model_lock_path"],
                    )
                result = run_aggregate_df(
                    project_root=root,
                    dataset="edgar",
                    authorization_path=authorization["authorization_path"],
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )
                validated = validate_aggregate_df(
                    project_root=root,
                    dataset="edgar",
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )
                self.assertEqual(result, validated)
                self.assertEqual(result["budget_charge_count"], 2)
                self.assertFalse(result["ledger_mutation"])
                self.assertEqual(result["external_calls_performed"], 0)
                with self.assertRaisesRegex(
                    RuntimeError, "output_or_checkpoint_already_exists"
                ):
                    run_aggregate_df(
                        project_root=root,
                        dataset="edgar",
                        authorization_path=authorization["authorization_path"],
                        runtime_files=fixture["runtime_files"],
                        dependency_lock_path=fixture["dependency_lock_path"],
                        model_lock_path=fixture["model_lock_path"],
                    )
            rows_path = root / "artifacts/v23/aggregate_df/edgar/token_df.jsonl"
            rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                [(row["token"], row["document_frequency"]) for row in rows],
                [("alpha", 1), ("beta", 2), ("gamma", 1)],
            )
            self.assertTrue(
                all(set(row) == {"kind", "token", "document_frequency"} for row in rows)
            )
            manifest = json.loads(
                (root / "artifacts/v23/aggregate_df/edgar/df_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["token_df_rows_path"],
                "artifacts/v23/aggregate_df/edgar/token_df.jsonl",
            )
            self.assertEqual(
                (root / "artifacts/v23/governance/consumed_source_ledger.jsonl").read_bytes(),
                ledger_before,
            )

    def test_aggregate_df_rejects_wrong_scope_and_dataset_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, _ = _bootstrap_synthetic_runtime(root)
            contracts = _synthetic_aggregate_contracts(root)
            with patch(
                "src.prepare.restoration_first_v23._aggregate_df_contracts",
                return_value=contracts,
            ):
                authorization = prepare_aggregate_df_authorization(
                    project_root=root,
                    dataset="edgar",
                    user_authorization_record="test aggregate df",
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )
                with self.assertRaisesRegex(RuntimeError, "dataset_not_allowed"):
                    run_aggregate_df(
                        project_root=root,
                        dataset="enron",
                        authorization_path=authorization["authorization_path"],
                        runtime_files=fixture["runtime_files"],
                        dependency_lock_path=fixture["dependency_lock_path"],
                        model_lock_path=fixture["model_lock_path"],
                    )
            second_root = root / "second"
            fixture, _ = _bootstrap_synthetic_runtime(second_root)
            enron_contracts = _synthetic_aggregate_contracts(
                second_root, dataset="enron"
            )
            with patch(
                "src.prepare.restoration_first_v23._aggregate_df_contracts",
                return_value=enron_contracts,
            ):
                with self.assertRaisesRegex(RuntimeError, "aggregate_df_artifact_missing"):
                    prepare_aggregate_df_authorization(
                        project_root=second_root,
                        dataset="enron",
                        user_authorization_record="out of order",
                        runtime_files=fixture["runtime_files"],
                        dependency_lock_path=fixture["dependency_lock_path"],
                        model_lock_path=fixture["model_lock_path"],
                    )

    def test_aggregate_df_rejects_runtime_and_pool_hash_drift_before_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, _ = _bootstrap_synthetic_runtime(root)
            contracts = _synthetic_aggregate_contracts(root)
            with patch(
                "src.prepare.restoration_first_v23._aggregate_df_contracts",
                return_value=contracts,
            ):
                authorization = prepare_aggregate_df_authorization(
                    project_root=root,
                    dataset="edgar",
                    user_authorization_record="test runtime drift",
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )
                authorization_path = root / authorization["authorization_path"]
                drifted = dict(authorization)
                drifted.pop("authorization_path")
                drifted.pop("source_pool_contents_read")
                drifted.pop("external_calls_performed")
                drifted["runtime_bundle_sha256"] = "f" * 64
                drifted["authorization_id"] = canonical_sha256(
                    {
                        key: value
                        for key, value in drifted.items()
                        if key != "authorization_id"
                    }
                )
                drifted_path = authorization_path.with_name(
                    drifted["authorization_id"] + ".json"
                )
                drifted_path.write_text(
                    canonical_json(drifted) + "\n", encoding="utf-8"
                )
                authorization_path.unlink()
                with self.assertRaisesRegex(
                    RuntimeError, "authorization_active_runtime_drift"
                ):
                    run_aggregate_df(
                        project_root=root,
                        dataset="edgar",
                        authorization_path=drifted_path,
                        runtime_files=fixture["runtime_files"],
                        dependency_lock_path=fixture["dependency_lock_path"],
                        model_lock_path=fixture["model_lock_path"],
                    )
                self.assertFalse(
                    (root / "artifacts/v23/governance/authorization_budgets").exists()
                )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, _ = _bootstrap_synthetic_runtime(root)
            contracts = _synthetic_aggregate_contracts(root)
            contracts["pool"]["database_sha256"] = "f" * 64
            with patch(
                "src.prepare.restoration_first_v23._aggregate_df_contracts",
                return_value=contracts,
            ), self.assertRaisesRegex(RuntimeError, "bound_file_hash_drift"):
                prepare_aggregate_df_authorization(
                    project_root=root,
                    dataset="edgar",
                    user_authorization_record="test pool hash drift",
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )
            self.assertFalse(
                (root / "artifacts/v23/governance/attempt_registry.jsonl").exists()
            )

    def test_aggregate_df_interruption_is_failed_and_not_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, ledger_before = _bootstrap_synthetic_runtime(root)
            contracts = _synthetic_aggregate_contracts(root)
            original_read = FrozenSourcePoolReader._read_source_unchecked

            def fail_second(reader: FrozenSourcePoolReader, source_key: str) -> dict:
                if source_key == "source-2":
                    raise KeyboardInterrupt("synthetic interruption")
                return original_read(reader, source_key)

            with patch(
                "src.prepare.restoration_first_v23._aggregate_df_contracts",
                return_value=contracts,
            ):
                authorization = prepare_aggregate_df_authorization(
                    project_root=root,
                    dataset="edgar",
                    user_authorization_record="test interruption",
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )
                with patch.object(
                    FrozenSourcePoolReader,
                    "_read_source_unchecked",
                    new=fail_second,
                ), self.assertRaises(KeyboardInterrupt):
                    run_aggregate_df(
                        project_root=root,
                        dataset="edgar",
                        authorization_path=authorization["authorization_path"],
                        runtime_files=fixture["runtime_files"],
                        dependency_lock_path=fixture["dependency_lock_path"],
                        model_lock_path=fixture["model_lock_path"],
                    )
                checkpoints = list(
                    (root / "artifacts/v23/checkpoints/aggregate_df_precomputation/edgar").glob(
                        "*.json"
                    )
                )
                self.assertEqual(len(checkpoints), 1)
                self.assertEqual(
                    json.loads(checkpoints[0].read_text(encoding="utf-8"))["status"],
                    "failed",
                )
                budget = root / "artifacts/v23/governance/authorization_budgets" / (
                    authorization["authorization_id"] + ".jsonl"
                )
                self.assertEqual(len(budget.read_text(encoding="utf-8").splitlines()), 2)
                with self.assertRaisesRegex(
                    RuntimeError, "output_or_checkpoint_already_exists"
                ):
                    run_aggregate_df(
                        project_root=root,
                        dataset="edgar",
                        authorization_path=authorization["authorization_path"],
                        runtime_files=fixture["runtime_files"],
                        dependency_lock_path=fixture["dependency_lock_path"],
                        model_lock_path=fixture["model_lock_path"],
                    )
            self.assertEqual(
                (root / "artifacts/v23/governance/consumed_source_ledger.jsonl").read_bytes(),
                ledger_before,
            )

    def test_aggregate_df_validation_rejects_artifact_and_budget_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, _ = _bootstrap_synthetic_runtime(root)
            contracts = _synthetic_aggregate_contracts(root)
            with patch(
                "src.prepare.restoration_first_v23._aggregate_df_contracts",
                return_value=contracts,
            ):
                authorization = prepare_aggregate_df_authorization(
                    project_root=root,
                    dataset="edgar",
                    user_authorization_record="test tampering",
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )
                run_aggregate_df(
                    project_root=root,
                    dataset="edgar",
                    authorization_path=authorization["authorization_path"],
                    runtime_files=fixture["runtime_files"],
                    dependency_lock_path=fixture["dependency_lock_path"],
                    model_lock_path=fixture["model_lock_path"],
                )
                paths = {
                    "rows": root / "artifacts/v23/aggregate_df/edgar/token_df.jsonl",
                    "manifest": root / "artifacts/v23/aggregate_df/edgar/df_manifest.json",
                    "checkpoint": next(
                        (root / "artifacts/v23/checkpoints/aggregate_df_precomputation/edgar").glob(
                            "*.json"
                        )
                    ),
                    "budget": root
                    / "artifacts/v23/governance/authorization_budgets"
                    / (authorization["authorization_id"] + ".jsonl"),
                }
                originals = {name: path.read_bytes() for name, path in paths.items()}
                for name, path in paths.items():
                    with self.subTest(artifact=name):
                        if name == "rows":
                            path.write_bytes(originals[name] + b'{"kind":"extra"}\n')
                        elif name == "manifest":
                            payload = json.loads(originals[name])
                            payload["token_count"] += 1
                            path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
                        elif name == "checkpoint":
                            payload = json.loads(originals[name])
                            payload["authorization_id"] = "f" * 64
                            path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
                        else:
                            payload = json.loads(originals[name].decode("utf-8").splitlines()[0])
                            payload["operation_identity_sha256"] = "f" * 64
                            remaining = originals[name].decode("utf-8").splitlines()[1:]
                            path.write_text(
                                canonical_json(payload) + "\n" + "\n".join(remaining) + "\n",
                                encoding="utf-8",
                            )
                        with self.assertRaises((RuntimeError, ValueError, json.JSONDecodeError)):
                            validate_aggregate_df(
                                project_root=root,
                                dataset="edgar",
                                runtime_files=fixture["runtime_files"],
                                dependency_lock_path=fixture["dependency_lock_path"],
                                model_lock_path=fixture["model_lock_path"],
                            )
                        path.write_bytes(originals[name])

    def test_capacity_golden_boundaries_and_consumption_monotonicity(self):
        cases = {
            "edgar": (5210, 623, 3125, 2252),
            "enron": (35000, 89, 2618, 2279),
            "pubmed": (47950, 66, 2574, 2258),
        }
        for dataset, (population, observed, expected_lower, expected_formal) in cases.items():
            with self.subTest(dataset=dataset):
                decision = capacity_decision(
                    population=population,
                    sample=1000,
                    observed_eligible=observed,
                    consumed_non_development=250,
                )
                self.assertEqual(decision["total_eligible_lower_K_L"], expected_lower)
                self.assertEqual(decision["formal_eligible_lower"], expected_formal)
                self.assertEqual(decision["status"], "passed")
                consumed_more = capacity_decision(
                    population=population,
                    sample=1000,
                    observed_eligible=observed,
                    consumed_non_development=260,
                )
                self.assertLess(
                    consumed_more["formal_eligible_lower"],
                    decision["formal_eligible_lower"],
                )

    def test_blind_audit_requires_complete_labels_and_applies_all_gates(self):
        packets = []
        reviewer_a = []
        reviewer_b = []
        for dataset in ("edgar", "enron", "pubmed"):
            for source_index in range(10):
                for pair_index in range(3):
                    key = f"{dataset}-{source_index}"
                    pair_id = text_sha256(f"{key}-{pair_index}")
                    packets.append(
                        {
                            "opaque_audit_source_id": key,
                            "pair_id": pair_id,
                        }
                    )
                    label = {
                        "opaque_audit_source_id": key,
                        "pair_id": pair_id,
                        **{field: "pass" for field in (
                            "grounded_fact_stability",
                            "original_entity_recoverability",
                            "minimum_construction_validity",
                            "non_entity_retrieval_anchor",
                            "verification_discriminativeness",
                            "query_self_containment",
                        )},
                        "overall_label": "pass",
                    }
                    reviewer_a.append(dict(label))
                    reviewer_b.append(dict(label))
        # A non-degenerate but fully agreeing label distribution keeps kappa defined.
        for rows in (reviewer_a, reviewer_b):
            rows[-1].update(
                {
                    "grounded_fact_stability": "fail",
                    "overall_label": "fail",
                }
            )
        result = evaluate_blind_audit(
            packet_rows=packets,
            reviewer_a_rows=reviewer_a,
            reviewer_b_rows=reviewer_b,
            adjudicator_rows=[],
            private_dataset_by_source_id={
                f"{dataset}-{source_index}": dataset
                for dataset in ("edgar", "enron", "pubmed")
                for source_index in range(10)
            },
            expected_pair_count=90,
        )
        self.assertEqual(result["raw_agreement"], 1.0)
        self.assertEqual(result["cohen_kappa"], 1.0)
        self.assertEqual(result["status"], "passed")
        with self.assertRaisesRegex(RuntimeError, "label_count_invalid"):
            evaluate_blind_audit(
                packet_rows=packets,
                reviewer_a_rows=reviewer_a[:-1],
                reviewer_b_rows=reviewer_b,
                adjudicator_rows=[],
                private_dataset_by_source_id={
                    f"{dataset}-{source_index}": dataset
                    for dataset in ("edgar", "enron", "pubmed")
                    for source_index in range(10)
                },
                expected_pair_count=90,
            )

    def test_split_is_membership_independent_and_index_allowlist_is_strict(self):
        selected = [
            {
                "source_key": f"source-{index:04d}",
                "source_hash": text_sha256(f"raw-{index}"),
                "normalized_text_hash": text_sha256(f"normalized-{index}"),
            }
            for index in range(12)
        ]
        rows = freeze_source_exclusive_split(
            selected_sources=selected,
            dataset="edgar",
            expected_count=12,
        )
        # Small synthetic sets use the canonical fixed cut points, hence all are members.
        self.assertTrue(all(row["group"] == "KB_Member" for row in rows))
        with self.assertRaisesRegex(RuntimeError, "index_group_contamination"):
            validate_index_allowlist(rows, allowed_group="KB_Member")
        full_selected = [
            {
                "source_key": f"formal-{index:04d}",
                "source_hash": text_sha256(f"formal-raw-{index}"),
                "normalized_text_hash": text_sha256(f"formal-normalized-{index}"),
            }
            for index in range(2250)
        ]
        full_rows = freeze_source_exclusive_split(
            selected_sources=full_selected,
            dataset="edgar",
        )
        members = [row for row in full_rows if row["group"] == "KB_Member"]
        nonmembers = [row for row in full_rows if row["group"] == "True_Non_Member"]
        reserve = [row for row in full_rows if row["group"] == "Reserve"]
        self.assertEqual((len(members), len(nonmembers), len(reserve)), (1000, 1000, 250))
        validate_index_allowlist(members, allowed_group="KB_Member")
        validate_index_allowlist(reserve, allowed_group="Reserve")
        with self.assertRaisesRegex(RuntimeError, "index_group_contamination"):
            validate_index_allowlist([*members[:-1], nonmembers[0]], allowed_group="KB_Member")

    def test_implementation_authorization_is_self_hashed_and_scope_limited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "authorization.json"
            payload = {
                "kind": "v23_implementation_authorization",
                "user_authorization_record": "test authorization",
                "authorized_stage": IMPLEMENTATION_STAGE,
                "allowed_repository_paths": ["tests/test_restoration_first_v23.py"],
                "issued_at": "2026-08-13T00:00:00Z",
                "expires_at_or_null": None,
                "design_manifest_sha256": DESIGN_MANIFEST_SHA256,
                "external_calls_allowed": False,
            }
            payload["authorization_id"] = canonical_sha256(payload)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            loaded = validate_implementation_authorization(
                path,
                requested_paths=["tests/test_restoration_first_v23.py"],
                project_root=root,
            )
            self.assertFalse(loaded["external_calls_allowed"])
            with self.assertRaisesRegex(RuntimeError, "path_not_allowed"):
                validate_implementation_authorization(
                    path, requested_paths=["scripts/pilot.py"], project_root=root
                )

    def test_run_authorization_enforces_stage_budget_and_identity(self):
        runtime_hash = "f" * 64
        revision = protocol_revision_id(runtime_hash, 0)
        registry = _attempt_registry_row(
            protocol_revision=revision,
            stage="aggregate_df_precomputation",
            execution_unit="one_dataset",
            attempt_ordinal=0,
            expected_prior_tip=GENESIS_SENTINEL,
        )
        payload = _run_authorization(
            runtime_hash=runtime_hash,
            registry_row=registry,
            datasets=["edgar"],
            run_roles=[],
            budget_limit=2,
        )
        validated = validate_run_authorization(
            payload,
            stage="aggregate_df_precomputation",
            execution_unit="one_dataset",
            attempt_registry_row=registry,
            dataset="edgar",
        )
        self.assertEqual(validated["budget_limit"], 2)
        tampered_registry = dict(registry)
        tampered_registry["allocated_at"] = "2026-08-13T00:00:01Z"
        with self.assertRaisesRegex(RuntimeError, "registry_row_hash_drift"):
            validate_run_authorization(
                payload,
                stage="aggregate_df_precomputation",
                execution_unit="one_dataset",
                attempt_registry_row=tampered_registry,
                dataset="edgar",
            )
        drifted = dict(payload)
        drifted["budget_kind"] = "calls"
        drifted["authorization_id"] = canonical_sha256(
            {key: value for key, value in drifted.items() if key != "authorization_id"}
        )
        with self.assertRaisesRegex(RuntimeError, "budget_mapping_mismatch"):
            validate_run_authorization(
                drifted,
                stage="aggregate_df_precomputation",
                execution_unit="one_dataset",
                attempt_registry_row=registry,
            )

    def test_ledger_append_hash_chain_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.jsonl"
            revision = protocol_revision_id("f" * 64, 0)
            genesis = _genesis_row(revision)
            ledger.write_text(canonical_json(genesis) + "\n", encoding="utf-8")
            registry = _attempt_registry_row(
                protocol_revision=revision,
                stage="formal_source_scan",
                execution_unit="one_dataset",
                attempt_ordinal=0,
                expected_prior_tip=genesis["row_sha256"],
            )
            authorization = _run_authorization(
                runtime_hash="f" * 64,
                registry_row=registry,
                datasets=["edgar"],
                run_roles=["formal_scan_viewed"],
                budget_limit=1,
            )
            result = append_reservation_batch(
                ledger_path=ledger,
                anchor_directory=root / "anchors",
                protocol_revision=revision,
                attempt=registry["attempt_id"],
                role="formal_scan_viewed",
                dataset="edgar",
                identities=[
                    {
                        "source_key": "source-1",
                        "source_hash": "1" * 64,
                        "normalized_text_hash": "2" * 64,
                    }
                ],
                expected_prior_tip=genesis["row_sha256"],
                reason="test",
                authorization=authorization,
                attempt_registry_row=registry,
                budget_journal_path=root / "budget.jsonl",
            )
            self.assertEqual(validate_ledger(ledger)["tip_sha256"], result["ledger_tip_sha256"])
            lines = ledger.read_text(encoding="utf-8").splitlines()
            tampered = json.loads(lines[1])
            tampered["source_key"] = "tampered"
            ledger.write_text(lines[0] + "\n" + canonical_json(tampered) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "row_hash_drift"):
                validate_ledger(ledger)

    def test_reservation_budget_shortfall_fails_before_ledger_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.jsonl"
            revision = protocol_revision_id("f" * 64, 0)
            genesis = _genesis_row(revision)
            ledger.write_text(canonical_json(genesis) + "\n", encoding="utf-8")
            registry = _attempt_registry_row(
                protocol_revision=revision,
                stage="formal_source_scan",
                execution_unit="one_dataset",
                attempt_ordinal=0,
                expected_prior_tip=genesis["row_sha256"],
            )
            authorization = _run_authorization(
                runtime_hash="f" * 64,
                registry_row=registry,
                datasets=["edgar"],
                run_roles=["formal_scan_viewed"],
                budget_limit=1,
            )
            with self.assertRaisesRegex(RuntimeError, "budget_exhausted"):
                append_reservation_batch(
                    ledger_path=ledger,
                    anchor_directory=root / "anchors",
                    protocol_revision=revision,
                    attempt=registry["attempt_id"],
                    role="formal_scan_viewed",
                    dataset="edgar",
                    identities=[
                        {
                            "source_key": f"source-{index}",
                            "source_hash": str(index + 1) * 64,
                            "normalized_text_hash": str(index + 3) * 64,
                        }
                        for index in range(2)
                    ],
                    expected_prior_tip=genesis["row_sha256"],
                    reason="test",
                    authorization=authorization,
                    attempt_registry_row=registry,
                    budget_journal_path=root / "budget.jsonl",
                )
            self.assertEqual(validate_ledger(ledger)["row_count"], 1)
            self.assertFalse((root / "budget.jsonl").exists())

    def test_budget_is_charged_before_operation_and_exhaustion_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.jsonl"
            authorization = {
                "authorization_id": "a" * 64,
                "attempt_id": "b" * 64,
                "authorized_stage": "aggregate_df_precomputation",
                "execution_unit": "one_dataset",
                "budget_kind": "sources",
                "budget_limit": 1,
            }
            first = charge_authorization_budget(
                authorization,
                journal_path=path,
                operation_identity_sha256="c" * 64,
            )
            self.assertEqual(first["sequence"], 0)
            with self.assertRaisesRegex(RuntimeError, "budget_exhausted"):
                charge_authorization_budget(
                    authorization,
                    journal_path=path,
                    operation_identity_sha256="d" * 64,
                )

    def test_no_mutation_checkpoint_rejects_tip_drift(self):
        checkpoint = {
            "kind": "v23_stage_checkpoint",
            "protocol_revision_id": "a" * 64,
            "attempt_id": "b" * 64,
            "stage": "source_exclusive_split",
            "execution_unit": "one_dataset",
            "status": "passed",
            "input_ledger_tip_sha256": "c" * 64,
            "input_tip_anchor_sha256": "d" * 64,
            "output_ledger_tip_sha256": "e" * 64,
            "output_tip_anchor_sha256": "d" * 64,
            "ledger_mutation": False,
            "authorization_id": "f" * 64,
            "authorization_budget_journal_tip_sha256": ZERO_SHA256,
            "runtime_bundle_sha256": "1" * 64,
            "output_manifest_sha256": None,
            "completed_at": "2026-08-13T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "no_mutation_tip_drift"):
                write_stage_checkpoint(Path(directory) / "checkpoint.json", checkpoint)


class V23EvaluationTests(unittest.TestCase):
    def test_response_parser_golden_vectors_and_conservative_scores(self):
        supported = parse_response('{"stance":"supported","correction_entity":null}')
        contradicted = parse_response(
            '{"stance":"contradicted","correction_entity":"Alice"}'
        )
        self.assertEqual(frozen_cell_score(query_polarity="Q_plus", parsed=supported, original_entity="Alice"), 1.0)
        self.assertEqual(frozen_cell_score(query_polarity="Q_minus", parsed=contradicted, original_entity=" alice "), 1.0)
        for invalid in (
            '{"stance":"supported","correction_entity":null,"confidence":1}',
            '{"stance":"contradicted","correction_entity":null}',
            '```json\n{"stance":"supported","correction_entity":null}\n```',
            '{"stance":"supported","stance":"contradicted","correction_entity":null}',
        ):
            with self.subTest(invalid=invalid):
                parsed = parse_response(invalid)
                self.assertEqual(parsed["parse_status"], "invalid")
                self.assertEqual(frozen_cell_score(query_polarity="Q_plus", parsed=parsed, original_entity="Alice"), -0.5)

    def test_query_validator_rejects_new_entity_and_schema_drift(self):
        pair_id = "a" * 64
        valid = json.dumps(
            {
                "kind": "v23_frozen_query",
                "pair_id": pair_id,
                "query_polarity": "Q_plus",
                "query_text": "Alice signed the Northstar Services Agreement?",
            }
        )
        parsed = validate_query_output(
            valid,
            pair_id=pair_id,
            query_polarity="Q_plus",
            claim="Alice signed the Northstar Services Agreement.",
            allowed_entity_surfaces=["Alice", "Northstar Services Agreement"],
            query_entity_surfaces=["Alice", "Northstar Services Agreement"],
        )
        self.assertEqual(parsed["pair_id"], pair_id)
        with self.assertRaisesRegex(ValueError, "new_entity_surface"):
            validate_query_output(
                valid,
                pair_id=pair_id,
                query_polarity="Q_plus",
                claim="Alice signed the Northstar Services Agreement.",
                allowed_entity_surfaces=["Alice"],
                query_entity_surfaces=["Alice", "Northstar Services Agreement"],
            )

    def test_source_scores_are_backend_local_and_require_six_cells(self):
        rows = []
        for backend in ("dense", "bm25"):
            for pair_order in range(3):
                rows.extend(
                    [
                        {
                            "backend": backend,
                            "dataset": "edgar",
                            "group": "KB_Member",
                            "source_key": "source-1",
                            "split_index": 0,
                            "pair_order": pair_order,
                            "pair_id": str(pair_order) * 64,
                            "query_polarity": "Q_plus",
                            "parse_status": "parsed",
                            "stance": "supported" if backend == "dense" else "insufficient",
                            "correction_entity": None,
                        },
                        {
                            "backend": backend,
                            "dataset": "edgar",
                            "group": "KB_Member",
                            "source_key": "source-1",
                            "split_index": 0,
                            "pair_order": pair_order,
                            "pair_id": str(pair_order) * 64,
                            "query_polarity": "Q_minus",
                            "parse_status": "parsed",
                            "stance": "contradicted",
                            "correction_entity": "Alice",
                        },
                    ]
                )
        release_rows = [
            {
                "dataset": "edgar",
                "group": "KB_Member",
                "source_key": "source-1",
                "pair_order": pair_order,
                "pair_id": str(pair_order) * 64,
                "original_entity": "Alice",
            }
            for pair_order in range(3)
        ]
        scores = build_source_scores(rows, release_rows=release_rows)
        self.assertEqual(len(scores), 2)
        self.assertEqual(scores[0]["backend"], "dense")
        self.assertEqual(scores[0]["source_pvs"], 2.0)
        self.assertEqual(scores[1]["backend"], "bm25")
        self.assertEqual(scores[1]["source_pvs"], 0.5)
        with self.assertRaisesRegex(ValueError, "missing_cell"):
            build_source_scores(
                rows[:-1], release_rows=release_rows
            )

    def test_auc_low_fpr_rng_quantile_and_bm25_golden_behaviour(self):
        self.assertEqual(tie_aware_auc([1.0, 0.0], [0.0, -1.0]), 0.875)
        low = empirical_tpr_at_fpr([1.0, 0.5], [0.4, 0.1], 0.0)
        self.assertEqual(low["tpr"], 1.0)
        indices = bootstrap_index_tensor(repetitions=1, cells=1, source_count=1000)
        self.assertEqual(
            indices[0, 0, :10].tolist(),
            [89, 773, 654, 438, 433, 858, 85, 697, 201, 94],
        )
        self.assertEqual(type7_quantile([0, 1, 2, 3, 4], 0.025), 0.1)
        self.assertEqual(type7_quantile([0, 1, 2, 3, 4], 0.975), 3.9)
        first = bm25_scores(["alpha beta", "beta gamma"], "beta alpha beta")
        second = bm25_scores(["alpha beta", "beta gamma"], "alpha beta")
        self.assertEqual(first, second)

    def test_artifact_hash_chain_rejects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = root / "rows.jsonl"
            rows.write_text("{}\n", encoding="utf-8")
            manifest = {"rows_path": "rows.jsonl", "rows_sha256": sha256_file(rows)}
            validate_artifact_hash_chain(
                manifest,
                project_root=root,
                path_hash_fields=[("rows_path", "rows_sha256")],
            )
            rows.write_text('{"tampered":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "artifact_hash_chain_drift"):
                validate_artifact_hash_chain(
                    manifest,
                    project_root=root,
                    path_hash_fields=[("rows_path", "rows_sha256")],
                )


if __name__ == "__main__":
    unittest.main()
