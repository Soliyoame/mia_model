"""正式 split、来源隔离与配置的本地回归。"""

from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from src.llm.openai_compatible import ChatResult
from src.shared_g.artifacts import ArtifactStore, read_json, read_rows, write_json_atomic
from src.shared_g.config import load_config
from src.shared_g.sources import load_pool, prepare, order_blind_candidates, select_qualified_sources, validate_isolation
from src.utils.hash import sha256_text
from src.utils.io import load_yaml

ROOT = Path(__file__).resolve().parents[1]


def sample_payload() -> dict:
    return {"initial_facts": [
        {"slot": "e1", "claim": "The study enrolled 230 adult patients with IBS.", "answer": "230",
         "question": "How many adult patients with IBS did the study enroll?"},
        {"slot": "e2", "claim": "Participants received vitamin B6 treatment.", "answer": "vitamin B6",
         "question": "Which treatment did participants receive?"},
        {"slot": "e3", "claim": "Follow-up lasted 12 weeks.", "answer": "12 weeks",
         "question": "How many weeks did follow-up last?"}],
        "remote_target": {"claim": "After vitamin B6 treatment, 18 patients reported fewer vomiting episodes.",
                          "answer": "18", "question": "How many patients reported fewer vomiting episodes after vitamin B6 treatment?",
                          "region_hint": "Results"}}


def sample_text(payload: dict | None = None) -> str:
    payload = payload or sample_payload()
    return "\n".join([*(row["claim"] for row in payload["initial_facts"]), payload["remote_target"]["claim"]])


class FormalFixture(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="shared_g_test_")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        data = copy.deepcopy(load_yaml(ROOT / "configs/v25_shared_g_formal.yaml"))
        data["source_selection"].update(minimum_words=1, history_roots=[], explicit_development_inputs=[],
                                        prior_v24_identity_inputs=[], unused_preparations=[])
        for dataset in data["datasets"]:
            data["source_selection"]["counts"][dataset] = {"KB_Member": 2, "True_Non_Member": 2}
            data["index"]["member_sources_per_dataset"][dataset] = 2
            paths = {name: self.root / pattern.format(dataset=dataset) for name, pattern in data["source_pool"]["paths"].items()}
            paths["database"].parent.mkdir(parents=True)
            with closing(sqlite3.connect(paths["database"])) as connection, connection:
                connection.execute("CREATE TABLE sources(source_key TEXT,dataset TEXT,document_id TEXT,source_order_rank INTEGER,source_hash TEXT,normalized_text_hash TEXT,full_text TEXT)")
                for index in range(4):
                    text = f"Unique description {dataset}-{index}.\n" + sample_text()
                    connection.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", (
                        f"{dataset}::{index}", dataset, str(index), index, sha256_text(text), sha256_text("normalized:" + text), text))
            write_json_atomic(paths["source_order"], {"source_order": [f"{dataset}::{i}" for i in range(4)]})
            write_json_atomic(paths["development_exclusions"], {"exclusions": []})
            write_json_atomic(paths["source_pool_manifest"], {"dataset": dataset, "count": 4})
        data["evaluation"]["bootstrap_samples"] = 20
        data["runtime"]["generation"]["request_interval_seconds"] = 0
        self.config_path = self.root / "config.yaml"
        self.config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        profile_path = self.root / data["runtime"]["llm_profiles_path"]
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text("active: {}\nsibling: {profiles: {}}\nvictim: {profiles: {}}\n", encoding="utf-8")
        self.config = load_config(self.config_path, self.root)
        self.profiles = {role: {"provider": "openai_compatible", "model": model, "model_version": model,
                               "base_url": "https://mock.invalid/v1", "timeout": 60,
                               "system_prompt": "Use the source.", "system_prompt_as_user": role == "victim"}
                         for role, model in (("sibling", "gpt-6-luna"), ("victim", data["runtime"]["concrete_model"]))}
        for target, kwargs in (("src.shared_g.artifacts.code_hashes", {"return_value": {"fixture": "hash"}}),
                               ("src.shared_g.sources.code_hashes", {"return_value": {"fixture": "hash"}}),
                               ("src.shared_g.artifacts.ArtifactStore.git_commit", {"return_value": "0" * 40}),
                               ("src.shared_g.config.ExperimentConfig.profiles", {"return_value": self.profiles})):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store = ArtifactStore(self.config)

    def result(self, content: str, role: str = "sibling", **overrides) -> ChatResult:
        fields = {"content": content, "provider_model_id": self.profiles[role]["model"],
                  "provider_request_id": "mock-request", "system_fingerprint": role + "-fingerprint",
                  "called_at": "2026-10-04T00:00:00Z", "input_tokens": 10, "output_tokens": 5,
                  "latency_ms": 1.0}
        fields.update(overrides)
        return ChatResult(**fields)

    def add_candidate(self, dataset: str, index: int) -> None:
        paths = self.config.pool_paths(dataset)
        text = f"Unique description {dataset}-{index}.\n" + sample_text()
        with closing(sqlite3.connect(paths["database"])) as connection, connection:
            connection.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", (
                f"{dataset}::{index}", dataset, str(index), index, sha256_text(text), sha256_text("normalized:" + text), text))
        order = read_json(paths["source_order"])
        order["source_order"].append(f"{dataset}::{index}")
        write_json_atomic(paths["source_order"], order)
        write_json_atomic(paths["source_pool_manifest"], {"dataset": dataset, "count": len(order["source_order"])})

    def reload_config(self, data: dict) -> None:
        self.config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self.config = load_config(self.config_path, self.root)
        self.store = ArtifactStore(self.config)

    def construct_all(self) -> Mock:
        from src.shared_g.construction import generate
        prepare(self.config, self.store)
        client = Mock()
        client.chat_with_metadata.return_value = self.result(json.dumps(sample_payload()))
        with patch("src.shared_g.construction.build_role_chat_client", return_value=(client, self.profiles["sibling"])):
            for dataset in self.config.datasets:
                generate(self.config, self.store, dataset)
        return client

    def write_review(self, rejected: dict[str, str] | None = None) -> None:
        from src.shared_g.construction import generation_records, save_review
        rejected = rejected or {}
        save_review(self.config, self.store, {
            key: {"generation_record_sha256": row["record_sha256"], "accepted": key not in rejected,
                  "reason": rejected.get(key, "")} for key, row in generation_records(self.store).items() if row["status"] == "passed"})

    def freeze_all(self) -> None:
        from src.shared_g.queries import freeze
        self.construct_all()
        self.write_review()
        freeze(self.config, self.store)


class SharedGSourcesTests(FormalFixture):
    def test_selection_is_deterministic_and_discards_prior_labels(self) -> None:
        pool = load_pool(self.config, "nfcorpus")
        first = order_blind_candidates(pool, 45, 1, set(), set())
        for row in pool:
            row.update(group="Spoofed_Non_Member", membership=True, eligible=False)
        self.assertEqual(first, order_blind_candidates(pool, 45, 1, set(), set()))
        self.assertTrue(all("group" not in row for row in first))
        self.assertNotIn("eligible", first[0])

    def test_empty_selection_needs_no_index_fill(self) -> None:
        self.assertEqual(order_blind_candidates([], 45, 80, set(), set()), [])

    def test_key_and_normalized_hash_exclusions_apply(self) -> None:
        pool = load_pool(self.config, "nfcorpus")
        selected = order_blind_candidates(pool, 45, 1, {pool[0]["source_key"]}, {pool[1]["normalized_text_hash"]})
        self.assertEqual({r["source_key"] for r in selected}, {pool[2]["source_key"], pool[3]["source_key"]})

    def test_nonmember_and_cross_dataset_text_overlap_are_rejected(self) -> None:
        rows = order_blind_candidates(load_pool(self.config, "nfcorpus"), 45, 1, set(), set())
        for index, row in enumerate(rows):
            row["group"] = ("KB_Member", "True_Non_Member")[index % 2]
        members = [row for row in rows if row["group"] == "KB_Member"]
        validate_isolation(rows, members)
        with self.assertRaises(RuntimeError):
            validate_isolation(rows, members + [rows[1]])
        rows[1]["normalized_text_hash"] = rows[0]["source_hash"]
        with self.assertRaises(RuntimeError):
            validate_isolation(rows, members)

    def test_prepare_is_idempotent_and_detects_input_drift(self) -> None:
        self.assertEqual(prepare(self.config, self.store)["candidate_count"], 12)
        self.assertEqual(prepare(self.config, self.store)["status"], "already_prepared")
        self.assertFalse(self.store.path("index_manifest.jsonl").exists())
        self.assertFalse(self.store.path("source_manifest.jsonl").exists())
        self.config.pool_paths("nfcorpus")["source_order"].write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "input_drift"):
            self.store.validate()

    def test_dry_run_writes_no_artifacts(self) -> None:
        summary = prepare(self.config, self.store, True)
        self.assertEqual(summary["candidate_count"], 12)
        self.assertEqual(summary["source_count"], 0)
        self.assertEqual(summary["target_source_count"], 12)
        self.assertFalse(self.config.output.exists())

    def test_config_drift_and_development_config_are_rejected(self) -> None:
        prepare(self.config, self.store)
        self.config_path.write_text(self.config_path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "code_or_config_drift"):
            self.store.validate()
        with self.assertRaises(ValueError):
            load_config(ROOT / "configs/v25_shared_g_query_stability_claim_anchor_fresh_100source_r2.yaml", ROOT)

    def test_source_text_drift_is_detected(self) -> None:
        with closing(sqlite3.connect(self.config.pool_paths("nfcorpus")["database"])) as connection, connection:
            connection.execute("UPDATE sources SET full_text='changed' WHERE source_key='nfcorpus::0'")
        with self.assertRaisesRegex(RuntimeError, "raw_source_identity_drift"):
            load_pool(self.config, "nfcorpus")

    def test_membership_requires_exact_qualified_quota(self) -> None:
        prepare(self.config, self.store)
        candidates = read_rows(self.store.path("candidate_manifest.jsonl"))
        keys = {row["source_key"] for row in candidates}
        first = select_qualified_sources(self.config, candidates, keys)
        self.assertEqual(first, select_qualified_sources(self.config, candidates, keys))
        for dataset in self.config.datasets:
            self.assertEqual(sum(row["dataset"] == dataset and row["group"] == "KB_Member" for row in first), 2)
        with self.assertRaisesRegex(RuntimeError, "quota_not_exact"):
            select_qualified_sources(self.config, candidates, keys - {first[0]["source_key"]})

    def test_history_raw_reuse_does_not_reuse_old_labels(self) -> None:
        from src.shared_g.artifacts import write_rows
        data = copy.deepcopy(self.config.data)
        data["source_selection"]["history_roots"] = ["history"]
        write_rows(self.root / "history/source_manifest.jsonl", [{"source_key": "nfcorpus::0",
                   "source_hash": load_pool(self.config, "nfcorpus")[0]["source_hash"], "group": "Spoofed_Non_Member"}])
        self.reload_config(data)
        prepare(self.config, self.store)
        candidates = read_rows(self.store.path("candidate_manifest.jsonl"))
        reused = next(row for row in candidates if row["source_key"] == "nfcorpus::0")
        self.assertTrue(reused["history_raw_document_reused"])
        self.assertTrue(all("group" not in row and "membership" not in row for row in candidates))
        self.assertFalse(self.store.path("generation.jsonl").exists())

    def test_unused_preparation_cannot_acquire_execution_artifacts(self) -> None:
        from src.shared_g.artifacts import write_rows
        data = copy.deepcopy(self.config.data)
        data["source_selection"]["unused_preparations"] = ["unused"]
        write_json_atomic(self.root / "unused/run_config.json", {"status": "prepared_before_construction"})
        write_rows(self.root / "unused/source_manifest.jsonl", [])
        write_rows(self.root / "unused/index_manifest.jsonl", [])
        self.reload_config(data)
        prepare(self.config, self.store)
        (self.root / "unused/generation.jsonl").write_text("", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unused_preparation_has_execution"):
            self.store.validate()


class A2CapacityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("capacity_audit_review", ROOT / "scripts/102_review_v25_shared_g_mechanism.py")
        cls.review = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.review)

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="capacity_audit_test_")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.sources = {f"nfcorpus::{i}": {
            "source_key": f"nfcorpus::{i}", "dataset": "nfcorpus", "document_id": str(i),
            "source_hash": sha256_text(f"raw-{i}"), "normalized_text_hash": sha256_text(f"norm-{i}"),
            "word_count": 80} for i in range(6)}
        self.aliases = {key: key for key in self.sources}
        self.hashes = {digest: {key} for key, row in self.sources.items()
                       for digest in (row["source_hash"], row["normalized_text_hash"])}
        self.documents = {row["document_id"]: {key} for key, row in self.sources.items()}

    def write_rows(self, name: str, rows: list[dict]) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def scan(self):
        return self.review.capacity_scan_history(self.root, self.root / "artifacts/v25/diagnostics/recheck_source_capacity_a2_test",
                                                 self.sources, self.aliases, self.hashes, self.documents)

    def test_whole_pool_candidate_enumeration_is_not_contact(self) -> None:
        from src.utils.hash import sha256_file
        path = self.write_rows("artifacts/v25/formal/a/candidate_manifest.jsonl", list(self.sources.values()))
        before = sha256_file(path)
        events, inventory, unresolved, missing = self.scan()
        self.assertFalse(events)
        rows, counts = self.review.capacity_classify_sources(self.sources, events, 80)
        self.assertEqual(counts["nfcorpus"]["no_record_candidate"], 6)
        self.assertEqual(inventory[0]["category"], "candidate_catalogue")
        self.assertEqual(sha256_file(path), before)
        self.assertFalse(unresolved or missing)

    def test_index_background_plain_key_lists_are_contact(self) -> None:
        write_json_atomic(self.root / "artifacts/v25/development/a/index_manifest.json", {
            "datasets": {"nfcorpus": {"selected_source_keys": ["nfcorpus::0", "nfcorpus::1", "nfcorpus::2"]}}})
        self.write_rows("artifacts/v25/development/a/retrieval.jsonl", [{"source_key": "nfcorpus::0"}])
        events, _, _, _ = self.scan()
        self.assertIn("index_contact", events["nfcorpus::2"])
        _, counts = self.review.capacity_classify_sources(self.sources, events, 80)
        self.assertEqual(counts["nfcorpus"]["known_contact"], 3)

    def test_failed_attempts_uncertain_allocation_and_preparation_are_separate(self) -> None:
        self.write_rows("artifacts/v25/development/failure/generation.jsonl", [{"source_key": "nfcorpus::0", "status": "failed"}])
        self.write_rows("artifacts/v25/development/unknown/source_manifest.jsonl", [{"source_key": "nfcorpus::1"}])
        write_json_atomic(self.root / "artifacts/v25/development/prepared/run_config.json", {"status": "fixed_before_new_calls"})
        self.write_rows("artifacts/v25/development/prepared/source_manifest.jsonl", [{"source_key": "nfcorpus::2"}])
        write_json_atomic(self.root / "artifacts/v25/development/prepared/index_manifest.json", {"sources": [{"source_key": "nfcorpus::2"}]})
        self.write_rows("artifacts/v25/diagnostics/recheck_source_capacity_a2_old/source_audit.jsonl", list(self.sources.values()))
        events, _, _, _ = self.scan()
        rows, counts = self.review.capacity_classify_sources(self.sources, events, 80)
        states = {row["source_key"]: row["status"] for row in rows}
        self.assertEqual(states["nfcorpus::0"], "known_contact")
        self.assertEqual(states["nfcorpus::1"], "history_uncertain")
        self.assertEqual(states["nfcorpus::2"], "no_record_candidate")
        self.assertEqual(counts["nfcorpus"]["preparation_only_candidate"], 1)
        self.assertEqual(counts["nfcorpus"]["no_record_candidate"], 4)

    def test_duplicate_alias_and_normalized_hash_contact_propagate(self) -> None:
        self.aliases["nfcorpus::removed-duplicate"] = "nfcorpus::0"
        self.write_rows("artifacts/v25/development/a/query_generation.jsonl", [
            {"source_key": "nfcorpus::removed-duplicate"}, {"normalized_text_hash": self.sources["nfcorpus::1"]["normalized_text_hash"]}])
        events, _, unresolved, _ = self.scan()
        self.assertIn("operational_contact", events["nfcorpus::0"])
        self.assertIn("operational_contact", events["nfcorpus::1"])
        self.assertFalse(unresolved)
        self.assertEqual(self.review.capacity_normalize(" A\tStraße\nB "), "a strasse b")

    def test_ambiguous_bare_id_and_exclusion_references_do_not_claim_calls(self) -> None:
        self.documents["0"].add("nfcorpus::1")
        self.write_rows("artifacts/v25/development/a/report.jsonl", [
            {"document_id": "0"}, {"excluded_source_keys": ["nfcorpus::2"], "membership": True, "eligible": False, "score": 999}])
        events, _, _, _ = self.scan()
        _, counts = self.review.capacity_classify_sources(self.sources, events, 80)
        self.assertEqual(counts["nfcorpus"]["history_uncertain"], 3)
        self.assertEqual(counts["nfcorpus"]["known_contact"], 0)

    def test_source_only_contact_excludes_cross_dataset_text_copy(self) -> None:
        key = "scidocs::copy"
        self.sources[key] = dict(self.sources["nfcorpus::0"], source_key=key, dataset="scidocs", document_id="copy")
        self.aliases[key] = key
        for field in ("source_hash", "normalized_text_hash"):
            self.hashes[self.sources[key][field]].add(key)
        self.write_rows("artifacts/v25/development/a/initial_responses.jsonl", [
            {"source_key": "nfcorpus::0", "slot_index": 0}, {"source_key": "nfcorpus::0", "slot_index": 1}])
        events, _, _, _ = self.scan()
        _, counts = self.review.capacity_classify_sources(self.sources, events, 80)
        self.assertEqual(counts["nfcorpus"]["known_contact"], 1)
        self.assertEqual(counts["scidocs"]["known_contact"], 1)

    def test_abbreviated_and_bare_research_ids_are_held_out(self) -> None:
        key = "scidocs::1672a134e0cebfef817c0c832eea1e54ffb094b0"
        self.sources[key] = dict(self.sources["nfcorpus::0"], source_key=key, dataset="scidocs", document_id=key.split('::')[1],
                                 source_hash=sha256_text(key), normalized_text_hash=sha256_text(key + "norm"))
        self.aliases[key] = key
        self.documents["MED-0"] = {"nfcorpus::0"}
        path = self.root / "研究记录/history.md"
        path.parent.mkdir(parents=True)
        path.write_text("已见 scidocs::1672a...；另有 MED-0。", encoding="utf-8")
        events, _, unresolved, _ = self.scan()
        self.assertIn("allocation_uncertain", events[key])
        self.assertIn("reference_only", events["nfcorpus::0"])
        self.assertFalse(unresolved)

    def test_minimum_words_and_cross_dataset_duplicates_bound_capacity(self) -> None:
        self.sources["nfcorpus::0"]["word_count"] = 79
        self.sources["scidocs::copy"] = dict(self.sources["nfcorpus::1"], source_key="scidocs::copy", dataset="scidocs", document_id="copy")
        rows, counts = self.review.capacity_classify_sources(self.sources, {}, 80)
        self.assertEqual(counts["nfcorpus"]["no_record_candidate"], 5)
        self.assertEqual(counts["nfcorpus"]["below_minimum_words"], 1)
        self.assertEqual(counts["scidocs"]["cross_dataset_duplicate"], 1)
        self.assertEqual(sum(sum(c.values()) for c in counts.values()), len(rows))

    def test_pool_raw_normalized_hash_order_and_duplicate_aliases_are_verified(self) -> None:
        from src.utils.hash import sha256_file, sha256_obj
        pool = self.root / "artifacts/v24/source_pools/nfcorpus"
        pool.mkdir(parents=True)
        corpus = self.write_rows("datasets/corpus.jsonl", [{"_id": "a", "text": "A document"},
                                {"_id": "b", "text": "a  DOCUMENT"}, {"_id": "empty", "text": ""}])
        database = pool / "source_pool.sqlite3"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("CREATE TABLE sources(source_key TEXT,dataset TEXT,document_id TEXT,source_hash TEXT,normalized_text_hash TEXT,full_text TEXT,input_row_count INTEGER)")
            connection.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", ("nfcorpus::a", "nfcorpus", "a",
                               sha256_text("A document"), sha256_text("a document"), "A document", 1))
        order = ["nfcorpus::a"]
        write_json_atomic(pool / "source_order.json", {"source_order": order})
        manifest = {"corpus_input_path": str(corpus), "corpus_input_sha256": sha256_file(corpus),
                    "database_sha256": sha256_file(database), "source_order_sha256": sha256_file(pool / "source_order.json"),
                    "source_order_content_sha256": sha256_obj(order), "frozen_source_count": 1,
                    "raw_document_count": 3, "empty_document_count": 1, "duplicate_text_count": 1}
        write_json_atomic(pool / "source_pool_manifest.json", manifest)
        config = [{"name": "nfcorpus", "source_pool": {"database": database, "manifest": pool / "source_pool_manifest.json",
                                                          "source_order": pool / "source_order.json"}}]
        before = {path: sha256_file(path) for path in self.root.rglob("*") if path.is_file()}
        sources, aliases, _, _, pools, _ = self.review.capacity_load_pools(self.root, config)
        self.assertEqual(aliases["nfcorpus::b"], "nfcorpus::a")
        self.assertEqual(pools["nfcorpus"]["duplicate_text_count"], 1)
        self.assertEqual(before, {path: sha256_file(path) for path in before})
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE sources SET normalized_text_hash=?", (sha256_text("wrong"),))
        manifest["database_sha256"] = sha256_file(database)
        write_json_atomic(pool / "source_pool_manifest.json", manifest)
        with self.assertRaisesRegex(RuntimeError, "source_identity_drift"):
            self.review.capacity_load_pools(self.root, config)
