"""Resumable zero-API workflow for PCV-MIA v22 attackability selection."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..attack.attackability_selector import (
    DEFAULT_UTILITY_WEIGHTS,
    DIAGNOSTIC_ENTITY_TYPES,
    MAIN_ENTITY_TYPES,
    SELECTOR_VERSION,
    STRUCTURED_EXTENSION_TYPES,
    assert_selection_payload_is_label_free,
    build_pair_candidates,
    route_effective_type,
    select_structured_extension_pairs,
    select_top_pairs,
)
from ..attack.entity_extractor import EntityExtractor, TYPE_DEFAULTS
from ..attack.entity_type_policy import (
    ENTITY_TYPE_POLICY_SHA256,
    ENTITY_TYPE_POLICY_VERSION,
)
from ..attack.semantic_entity_resolver import (
    ALL_SEMANTIC_SCHEMA,
    SEMANTIC_SCHEMA_SHA256,
    SemanticPredictionBackend,
    SemanticResolverProtocolError,
    _load_backend,
    _verify_model_lock,
)
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import load_yaml, read_json, read_jsonl, write_json, write_jsonl_atomic


PROTOCOL_VERSION = "pcv-mia-v22"
METHOD_VERSION = "pcv-attackability-first-v22"
PROTOCOL_MANIFEST_VERSION = "pcv_v22_protocol_manifest_r1"
SOURCE_POOL_PROTOCOL = "pcv_v22_frozen_source_pool_r1"
SOURCE_POOL_CHECKPOINT_PROTOCOL = "pcv_v22_source_pool_checkpoint_r1"
SCAN_PLAN_PROTOCOL = "pcv_v22_attackability_scan_plan_r1"
SCAN_CHECKPOINT_PROTOCOL = "pcv_v22_attackability_scan_checkpoint_r1"
WAVE_MANIFEST_PROTOCOL = "pcv_v22_attackability_wave_r1"
CALIBRATION_PLAN_PROTOCOL = "pcv_v22_attackability_calibration_r1"
LABEL_SCHEMA_VERSION = "pcv_v22_attackability_review_labels_r1"
THRESHOLD_MANIFEST_PROTOCOL = "pcv_v22_attackability_threshold_r1"
FRESH_AUDIT_PROTOCOL = "pcv_v22_attackability_fresh_audit_r1"
SPLIT_MANIFEST_PROTOCOL = "pcv_v22_post_selection_split_r1"
SHADOW_GATE_PROTOCOL = "pcv_v22_attackability_shadow_gate_r1"
RELEASE_PROTOCOL = "pcv_v22_attackability_release_r1"
SHADOW_ARTIFACT_PROTOCOLS = {
    "index": "pcv_v22_reserve_shadow_index_manifest_r1",
    "query": "pcv_v22_reserve_shadow_query_manifest_r1",
    "benchmark": "pcv_v22_reserve_shadow_benchmark_manifest_r1",
}
OLD_SHADOW_BASELINE_PROTOCOL = "pcv_v22_old_semantic_purity_shadow_baseline_r1"

REVIEW_FIELDS = (
    "grounded_specific_fact",
    "natural_counterfactual",
    "verification_discriminative",
    "queryable_self_contained",
    "attack_usable",
)
REVIEW_VALUES = frozenset({"yes", "no", "uncertain"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve(path: str | Path, root: Path) -> Path:
    result = Path(path)
    return result.resolve() if result.is_absolute() else (root / result).resolve()


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _identity(payload: Mapping[str, Any], *excluded: str) -> str:
    ignored = set(excluded)
    return sha256_obj({key: value for key, value in payload.items() if key not in ignored})


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _canonical_source_key(row: Mapping[str, Any]) -> str:
    source_id = str(row.get("source_id") or row.get("doc_id") or "").strip()
    source_path = str(row.get("source_path") or "").strip()
    if source_id or source_path:
        return f"{source_path}::{source_id}"
    return str(row.get("text_hash") or "").strip()


def _candidate_row(row: Mapping[str, Any], dataset: str, source_key: str) -> dict[str, Any]:
    doc_id = str(row.get("doc_id") or row.get("id") or "").strip()
    text_value = str(row.get("text") or "")
    text_hash = str(row.get("text_hash") or sha256_text(text_value))
    stable_id = sha256_text("\0".join((dataset, source_key, doc_id, text_hash)))[:24]
    return {
        "audit_id": f"v22_{dataset}_{stable_id}",
        "doc_id": doc_id or f"{dataset}_{stable_id}",
        "source_id": row.get("source_id") or doc_id,
        "source_path": row.get("source_path"),
        "source_key": source_key,
        "dataset": dataset,
        "text": text_value,
        "text_hash": text_hash,
        "chunk_index": row.get("chunk_index"),
    }


def load_v22_config(config_path: str | Path) -> dict[str, Any]:
    config = load_yaml(config_path)
    if config.get("protocol_version") != PROTOCOL_VERSION:
        raise RuntimeError("v22 protocol_version drift")
    if config.get("method_version") != METHOD_VERSION:
        raise RuntimeError("v22 method_version drift")
    routing = config.get("routing") or {}
    if routing.get("strategy") != "high_precision_rule_then_single_model":
        raise RuntimeError("v22 single-model routing strategy drift")
    if routing.get("single_model_role") != "gliner2_base":
        raise RuntimeError("v22 router role drift")
    if routing.get("single_model_id") != "fastino/gliner2-base-v1":
        raise RuntimeError("v22 router model drift")
    if routing.get("single_model_revision") != (
        "f5b2ecedebe4381b088c1cf276f5bf72a52cac54"
    ):
        raise RuntimeError("v22 router revision drift")
    if routing.get("no_prediction_policy") != (
        "high_precision_rule_else_declared_type_fallback"
    ):
        raise RuntimeError("v22 no-prediction policy drift")
    if bool(routing.get("model_miss_is_not_a_veto")) is not True:
        raise RuntimeError("v22 model miss must not be a veto")
    weights = dict((config.get("utility") or {}).get("weights") or {})
    if weights != DEFAULT_UTILITY_WEIGHTS:
        raise RuntimeError("v22 utility weights drift")
    scope = config.get("scope") or {}
    if set(scope.get("formal_entity_types") or ()) != set(MAIN_ENTITY_TYPES):
        raise RuntimeError("v22 formal entity type drift")
    if set(scope.get("structured_high_signal_types") or ()) != set(
        STRUCTURED_EXTENSION_TYPES
    ):
        raise RuntimeError("v22 structured extension type drift")
    if set(scope.get("diagnostic_only_types") or ()) != set(DIAGNOSTIC_ENTITY_TYPES):
        raise RuntimeError("v22 diagnostic type drift")
    if int((config.get("execution") or {}).get("external_calls_expected", -1)) != 0:
        raise RuntimeError("v22 external call budget must be zero")
    return config


def _runtime_bundle(config: Mapping[str, Any], root: Path) -> list[dict[str, str]]:
    bundle: list[dict[str, str]] = []
    for raw_path in config.get("runtime_files") or ():
        path = _resolve(str(raw_path), root)
        if not path.is_file():
            raise RuntimeError(f"v22 runtime file missing: {path}")
        bundle.append({"path": _relative(path, root), "sha256": sha256_file(path)})
    return bundle


def _git_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = completed.stdout.strip()
    if len(commit) != 40:
        raise RuntimeError("v22 code commit identity is unavailable")
    return commit


def _assert_frozen_inputs_committed(
    config: Mapping[str, Any], root: Path
) -> None:
    paths = [
        *(_resolve(str(item), root) for item in config.get("runtime_files") or ()),
        _resolve(str(config["routing"]["model_lock_path"]), root),
    ]
    relative_paths = [_relative(path, root) for path in paths]
    for relative_path in relative_paths:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative_path],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if tracked.returncode != 0:
            raise RuntimeError(
                f"v22 frozen input is not committed: {relative_path}"
            )
    changed = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *relative_paths],
        cwd=root,
    )
    if changed.returncode == 1:
        raise RuntimeError("v22 frozen inputs have uncommitted changes")
    if changed.returncode != 0:
        raise RuntimeError("v22 frozen input git identity check failed")


def freeze_protocol(
    config_path: str | Path,
    *,
    resume: bool,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_v22_config(config_file)
    _assert_frozen_inputs_committed(config, root)
    output_root = _resolve(str(config["output_root"]), root)
    output_root.mkdir(parents=True, exist_ok=True)
    routing = config["routing"]
    model_lock = _resolve(str(routing["model_lock_path"]), root)
    entity_policy_path = _resolve("configs/entity_type_policy_v21_r1.yaml", root)
    if sha256_file(model_lock) != str(routing["model_lock_sha256"]):
        raise RuntimeError("v22 model lock hash drift")
    if str(routing["semantic_schema_sha256"]) != SEMANTIC_SCHEMA_SHA256:
        raise RuntimeError("v22 semantic schema drift")
    for dataset, source_config in (config.get("source_pools") or {}).items():
        processed = _resolve(str(source_config["processed_path"]), root)
        if not processed.is_file():
            raise RuntimeError(f"v22 processed pool missing: {dataset}: {processed}")
        frozen_order_value = source_config.get("frozen_order_path") or source_config.get(
            "frozen_prefix_path"
        )
        frozen_hash_value = source_config.get("frozen_order_sha256") or source_config.get(
            "frozen_prefix_sha256"
        )
        frozen_path = _resolve(str(frozen_order_value), root)
        if not frozen_path.is_file() or sha256_file(frozen_path) != str(frozen_hash_value):
            raise RuntimeError(f"v22 frozen source order drift: {dataset}")
    manifest: dict[str, Any] = {
        "protocol": PROTOCOL_MANIFEST_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "method_version": METHOD_VERSION,
        "status": "frozen_zero_external_calls",
        "created_at": _utc_now(),
        "config_path": _relative(config_file, root),
        "config_sha256": sha256_file(config_file),
        "runtime_bundle": _runtime_bundle(config, root),
        "code_commit": _git_commit(root),
        "single_router_model": {
            "role": routing["single_model_role"],
            "model_id": routing["single_model_id"],
            "revision": routing["single_model_revision"],
            "model_lock_path": _relative(model_lock, root),
            "model_lock_sha256": sha256_file(model_lock),
        },
        "entity_type_policy": {
            "version": ENTITY_TYPE_POLICY_VERSION,
            "policy_sha256": ENTITY_TYPE_POLICY_SHA256,
            "path": _relative(entity_policy_path, root),
            "file_sha256": sha256_file(entity_policy_path),
        },
        "forbidden_selection_inputs": [
            "membership",
            "victim_response",
            "attack_score",
            "attack_auc",
        ],
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs": 0,
    }
    manifest["protocol_identity_sha256"] = _identity(
        manifest, "created_at", "protocol_identity_sha256"
    )
    path = output_root / "protocol_manifest.json"
    if path.exists():
        if not resume:
            raise RuntimeError(f"v22 protocol already frozen: {path}")
        existing = read_json(path)
        manifest["created_at"] = existing.get("created_at")
        if existing != manifest:
            raise RuntimeError(f"v22 protocol identity drift: {path}")
    else:
        write_json(manifest, path)
    superseded = {
        "protocol": "pcv_v22_superseded_goal_mismatch_r1",
        "status": "superseded_goal_mismatch",
        "reason": "v21/r4 reviewed ontology correctness instead of attack applicability",
        "artifacts": list(config.get("superseded_goal_mismatch") or ()),
        "consumed_by_v22": False,
    }
    superseded["identity_sha256"] = sha256_obj(superseded)
    superseded_path = output_root / "superseded_goal_mismatch.json"
    if superseded_path.exists() and read_json(superseded_path) != superseded:
        raise RuntimeError("v22 superseded-goal manifest drift")
    if not superseded_path.exists():
        write_json(superseded, superseded_path)
    return {
        "status": "frozen",
        "manifest": str(path),
        "protocol_identity_sha256": manifest["protocol_identity_sha256"],
        "single_router_model": manifest["single_router_model"],
        "external_calls": 0,
    }


def _load_protocol_manifest(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve(str(config["output_root"]), root) / "protocol_manifest.json"
    if not path.is_file():
        raise RuntimeError("v22 protocol is not frozen")
    manifest = read_json(path)
    if manifest.get("protocol") != PROTOCOL_MANIFEST_VERSION:
        raise RuntimeError("v22 protocol manifest version drift")
    if manifest.get("protocol_identity_sha256") != _identity(
        manifest, "created_at", "protocol_identity_sha256"
    ):
        raise RuntimeError("v22 protocol manifest identity drift")
    config_path = _resolve(str(manifest["config_path"]), root)
    if not config_path.is_file() or sha256_file(config_path) != manifest["config_sha256"]:
        raise RuntimeError("v22 protocol config drift")
    if manifest.get("runtime_bundle") != _runtime_bundle(config, root):
        raise RuntimeError("v22 protocol runtime bundle drift")
    if manifest.get("code_commit") != _git_commit(root):
        raise RuntimeError("v22 protocol code commit drift")
    frozen_router = manifest.get("single_router_model")
    if not isinstance(frozen_router, Mapping):
        raise RuntimeError("v22 frozen router identity missing")
    lock_path = _resolve(str(frozen_router.get("model_lock_path") or ""), root)
    frozen_lock_hash = str(frozen_router.get("model_lock_sha256") or "")
    if (
        not lock_path.is_file()
        or sha256_file(lock_path) != frozen_lock_hash
        or frozen_lock_hash != str(config["routing"]["model_lock_sha256"])
    ):
        raise RuntimeError("v22 frozen model lock drift")
    if (
        frozen_router.get("model_id") != config["routing"]["single_model_id"]
        or frozen_router.get("revision")
        != config["routing"]["single_model_revision"]
    ):
        raise RuntimeError("v22 frozen router model drift")
    frozen_policy = manifest.get("entity_type_policy")
    if not isinstance(frozen_policy, Mapping):
        raise RuntimeError("v22 frozen entity policy identity missing")
    policy_path = _resolve(str(frozen_policy.get("path") or ""), root)
    if (
        frozen_policy.get("version") != ENTITY_TYPE_POLICY_VERSION
        or frozen_policy.get("policy_sha256") != ENTITY_TYPE_POLICY_SHA256
        or not policy_path.is_file()
        or sha256_file(policy_path) != frozen_policy.get("file_sha256")
    ):
        raise RuntimeError("v22 frozen entity policy drift")
    return manifest


def _source_pool_paths(config: Mapping[str, Any], dataset: str, root: Path) -> dict[str, Path]:
    base = _resolve(str(config["output_root"]), root) / "source_pools" / dataset
    return {
        "base": base,
        "database": base / "source_pool.sqlite3",
        "checkpoint": base / "source_pool_checkpoint.json",
        "source_order": base / "source_order.json",
        "manifest": base / "source_pool_manifest.json",
    }


def _source_pool_checkpoint_identity(payload: Mapping[str, Any]) -> str:
    return _identity(payload, "updated_at", "checkpoint_identity_sha256")


def _write_source_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    checkpoint["updated_at"] = _utc_now()
    checkpoint["checkpoint_identity_sha256"] = _source_pool_checkpoint_identity(checkpoint)
    write_json(checkpoint, path)


def _open_source_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources(
            source_key TEXT PRIMARY KEY,
            source_order_rank TEXT NOT NULL,
            full_text TEXT NOT NULL,
            input_row_count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks(
            source_key TEXT NOT NULL,
            chunk_rank INTEGER NOT NULL,
            selection_hash TEXT NOT NULL,
            row_json TEXT NOT NULL,
            PRIMARY KEY(source_key, chunk_rank),
            FOREIGN KEY(source_key) REFERENCES sources(source_key)
        );
        CREATE TABLE IF NOT EXISTS source_pool_state(
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            state_json TEXT NOT NULL
        );
        """
    )
    return connection


def _source_database_state_identity(payload: Mapping[str, Any]) -> str:
    return _identity(payload, "state_identity_sha256")


def _write_source_database_state(
    connection: sqlite3.Connection, checkpoint: Mapping[str, Any]
) -> dict[str, Any]:
    state = {
        key: checkpoint[key]
        for key in (
            "protocol",
            "dataset",
            "config_sha256",
            "processed_sha256",
            "byte_offset",
            "input_rows_seen",
            "source_groups_seen",
            "sources_retained",
            "api_calls_performed",
            "victim_calls_performed",
            "retriever_runs",
        )
    }
    state["state_identity_sha256"] = _source_database_state_identity(state)
    connection.execute(
        "INSERT INTO source_pool_state(singleton,state_json) VALUES(1,?) "
        "ON CONFLICT(singleton) DO UPDATE SET state_json=excluded.state_json",
        (json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")),),
    )
    return state


def _load_source_database_state(
    connection: sqlite3.Connection,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT state_json FROM source_pool_state WHERE singleton = 1"
    ).fetchone()
    if row is None:
        return None
    state = json.loads(str(row[0]))
    if state.get("state_identity_sha256") != _source_database_state_identity(state):
        raise RuntimeError("v22 source database state identity drift")
    return state


def _finalize_source_group(
    connection: sqlite3.Connection,
    *,
    source_key: str,
    rows: Sequence[Mapping[str, Any]],
    dataset: str,
    selection_seed: int,
    max_chunks_per_source: int,
    keep_source: bool,
) -> bool:
    if not keep_source:
        return False
    if connection.execute(
        "SELECT 1 FROM sources WHERE source_key = ?", (source_key,)
    ).fetchone():
        raise RuntimeError(f"processed source rows are not contiguous: {source_key}")
    ranked: list[tuple[str, str, str, dict[str, Any]]] = []
    texts: list[str] = []
    for row in rows:
        candidate = _candidate_row(row, dataset, source_key)
        texts.append(str(candidate["text"]))
        selection_hash = sha256_text(
            "\0".join(
                (
                    str(selection_seed),
                    dataset,
                    source_key,
                    str(candidate["doc_id"]),
                    str(candidate["text_hash"]),
                    str(candidate["text"]),
                )
            )
        )
        ranked.append(
            (selection_hash, str(candidate["doc_id"]), str(candidate["text_hash"]), candidate)
        )
    source_rank = sha256_text("\0".join((str(selection_seed), dataset, source_key)))
    connection.execute(
        "INSERT INTO sources(source_key,source_order_rank,full_text,input_row_count) VALUES(?,?,?,?)",
        (source_key, source_rank, "\n".join(texts), len(rows)),
    )
    for chunk_index, (selection_hash, _, _, candidate) in enumerate(
        sorted(ranked)[:max_chunks_per_source]
    ):
        connection.execute(
            "INSERT INTO chunks(source_key,chunk_rank,selection_hash,row_json) VALUES(?,?,?,?)",
            (
                source_key,
                chunk_index,
                selection_hash,
                json.dumps(candidate, ensure_ascii=False, separators=(",", ":")),
            ),
        )
    return True


def prepare_source_pool(
    config_path: str | Path,
    *,
    dataset: str,
    resume: bool,
    max_new_rows: int | None,
    project_root: str | Path,
) -> dict[str, Any]:
    """Build a resumable SQLite source pool without reading any labels."""

    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_v22_config(config_file)
    protocol_manifest = _load_protocol_manifest(config, root)
    source_config = dict((config.get("source_pools") or {}).get(dataset) or {})
    if not source_config:
        raise ValueError(f"unsupported v22 dataset: {dataset}")
    paths = _source_pool_paths(config, dataset, root)
    paths["base"].mkdir(parents=True, exist_ok=True)
    if paths["manifest"].is_file():
        if not resume:
            raise RuntimeError(f"v22 source pool already complete: {paths['manifest']}")
        manifest = _validate_source_pool(config, dataset, root)
        return {
            "status": "passed",
            "dataset": dataset,
            "source_count": manifest["source_count"],
            "manifest": str(paths["manifest"]),
            "resumed": True,
        }
    processed_path = _resolve(str(source_config["processed_path"]), root)
    if sha256_file(processed_path) != str(source_config["processed_sha256"]):
        raise RuntimeError(f"v22 processed pool hash drift: {dataset}")
    exact_order: list[str] | None = None
    exact_allowlist: set[str] | None = None
    if source_config["order_mode"] == "exact_existing_order":
        order_path = _resolve(str(source_config["frozen_order_path"]), root)
        order_payload = read_json(order_path)
        exact_order = [str(item) for item in order_payload.get("source_order") or ()]
        exact_allowlist = set(exact_order)
        if len(exact_order) != len(exact_allowlist):
            raise RuntimeError("v22 exact source order contains duplicates")
    checkpoint: dict[str, Any]
    if paths["checkpoint"].is_file():
        if not resume:
            raise RuntimeError(f"v22 partial source pool exists: {paths['base']}")
        checkpoint = read_json(paths["checkpoint"])
        if checkpoint.get("protocol") != SOURCE_POOL_CHECKPOINT_PROTOCOL:
            raise RuntimeError("v22 source pool checkpoint protocol drift")
        if checkpoint.get("config_sha256") != sha256_file(config_file):
            raise RuntimeError("v22 source pool checkpoint config drift")
        if checkpoint.get("checkpoint_identity_sha256") != _source_pool_checkpoint_identity(
            checkpoint
        ):
            raise RuntimeError("v22 source pool checkpoint identity drift")
    else:
        if paths["database"].exists():
            raise RuntimeError("v22 source database exists without checkpoint")
        checkpoint = {
            "protocol": SOURCE_POOL_CHECKPOINT_PROTOCOL,
            "dataset": dataset,
            "config_sha256": sha256_file(config_file),
            "processed_sha256": source_config["processed_sha256"],
            "status": "paused",
            "byte_offset": 0,
            "input_rows_seen": 0,
            "source_groups_seen": 0,
            "sources_retained": 0,
            "api_calls_performed": 0,
            "victim_calls_performed": 0,
            "retriever_runs": 0,
        }
        _write_source_checkpoint(paths["checkpoint"], checkpoint)
    connection = _open_source_database(paths["database"])
    selection_seed = int(config["selection_seed"])
    max_chunks = int(config["candidate_extraction"]["max_chunks_per_source"])
    checkpoint_interval_rows = int(
        config["execution"]["source_pool_checkpoint_interval_rows"]
    )
    database_state = _load_source_database_state(connection)
    if database_state is None:
        existing_sources = int(
            connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        )
        if existing_sources or int(checkpoint["byte_offset"]) != 0:
            connection.close()
            raise RuntimeError("v22 source database has no recoverable state")
        _write_source_database_state(connection, checkpoint)
        connection.commit()
    else:
        for identity_field in (
            "protocol",
            "dataset",
            "config_sha256",
            "processed_sha256",
        ):
            if database_state.get(identity_field) != checkpoint.get(identity_field):
                connection.close()
                raise RuntimeError(
                    f"v22 source database state drift: {identity_field}"
                )
        for progress_field in (
            "byte_offset",
            "input_rows_seen",
            "source_groups_seen",
            "sources_retained",
            "api_calls_performed",
            "victim_calls_performed",
            "retriever_runs",
        ):
            checkpoint[progress_field] = database_state[progress_field]
    start_offset = int(checkpoint["byte_offset"])
    last_json_checkpoint_rows = int(checkpoint["input_rows_seen"])
    new_rows = 0
    current_key: str | None = None
    current_rows: list[dict[str, Any]] = []
    pause_offset: int | None = None
    completed = False
    try:
        with processed_path.open("rb") as handle:
            handle.seek(start_offset)
            while True:
                line_start = handle.tell()
                raw_line = handle.readline()
                if not raw_line:
                    if current_key is not None:
                        kept = _finalize_source_group(
                            connection,
                            source_key=current_key,
                            rows=current_rows,
                            dataset=dataset,
                            selection_seed=selection_seed,
                            max_chunks_per_source=max_chunks,
                            keep_source=exact_allowlist is None or current_key in exact_allowlist,
                        )
                        checkpoint["source_groups_seen"] += 1
                        checkpoint["sources_retained"] += int(kept)
                    checkpoint["byte_offset"] = handle.tell()
                    _write_source_database_state(connection, checkpoint)
                    connection.commit()
                    completed = True
                    break
                if not raw_line.strip():
                    continue
                row = json.loads(raw_line.decode("utf-8"))
                if not isinstance(row, dict):
                    raise RuntimeError("processed JSONL row must be an object")
                key = _canonical_source_key(row)
                if not key:
                    raise RuntimeError("processed row has no stable source key")
                if current_key is None:
                    current_key = key
                elif key != current_key:
                    kept = _finalize_source_group(
                        connection,
                        source_key=current_key,
                        rows=current_rows,
                        dataset=dataset,
                        selection_seed=selection_seed,
                        max_chunks_per_source=max_chunks,
                        keep_source=exact_allowlist is None or current_key in exact_allowlist,
                    )
                    checkpoint["source_groups_seen"] += 1
                    checkpoint["sources_retained"] += int(kept)
                    checkpoint["byte_offset"] = line_start
                    _write_source_database_state(connection, checkpoint)
                    connection.commit()
                    if (
                        int(checkpoint["input_rows_seen"])
                        - last_json_checkpoint_rows
                        >= checkpoint_interval_rows
                    ):
                        _write_source_checkpoint(paths["checkpoint"], checkpoint)
                        last_json_checkpoint_rows = int(
                            checkpoint["input_rows_seen"]
                        )
                    if max_new_rows is not None and new_rows >= max_new_rows:
                        pause_offset = line_start
                        current_key = None
                        current_rows = []
                        break
                    current_key = key
                    current_rows = []
                current_rows.append(row)
                checkpoint["input_rows_seen"] += 1
                new_rows += 1
            if pause_offset is not None:
                checkpoint["byte_offset"] = pause_offset
    finally:
        connection.close()
    if not completed:
        checkpoint["status"] = "paused"
        _write_source_checkpoint(paths["checkpoint"], checkpoint)
        return {
            "status": "paused",
            "dataset": dataset,
            "new_rows": new_rows,
            "input_rows_seen": checkpoint["input_rows_seen"],
            "sources_retained": checkpoint["sources_retained"],
            "checkpoint": str(paths["checkpoint"]),
        }

    connection = sqlite3.connect(paths["database"])
    try:
        rows = connection.execute(
            "SELECT source_key,source_order_rank FROM sources"
        ).fetchall()
        retained_sources = {str(item[0]) for item in rows}
        if exact_order is not None:
            if retained_sources != set(exact_order):
                missing = sorted(set(exact_order) - retained_sources)[:5]
                extra = sorted(retained_sources - set(exact_order))[:5]
                raise RuntimeError(
                    f"v22 exact source pool mismatch: missing={missing} extra={extra}"
                )
            source_order = exact_order
        else:
            source_order = [
                str(item[0]) for item in sorted(rows, key=lambda item: (str(item[1]), str(item[0])))
            ]
        expected_count = int(source_config["expected_processed_source_count"])
        if len(source_order) != expected_count:
            raise RuntimeError(
                f"v22 processed source count drift: expected={expected_count} actual={len(source_order)}"
            )
        if source_config["order_mode"] == "derive_complete_and_verify_v21_prefix":
            prefix_path = _resolve(str(source_config["frozen_prefix_path"]), root)
            old_prefix = [str(item) for item in read_json(prefix_path).get("source_order") or ()]
            if source_order[: len(old_prefix)] != old_prefix:
                raise RuntimeError(f"v22 reconstructed source prefix drift: {dataset}")
    finally:
        connection.close()
    order_payload = {
        "protocol": SOURCE_POOL_PROTOCOL,
        "dataset": dataset,
        "selection_seed": selection_seed,
        "source_order": source_order,
        "source_order_sha256": sha256_obj(source_order),
        "label_fields_read": [],
    }
    write_json(order_payload, paths["source_order"])
    checkpoint["status"] = "passed"
    _write_source_checkpoint(paths["checkpoint"], checkpoint)
    manifest: dict[str, Any] = {
        "protocol": SOURCE_POOL_PROTOCOL,
        "status": "passed",
        "created_at": _utc_now(),
        "dataset": dataset,
        "config_path": _relative(config_file, root),
        "config_sha256": sha256_file(config_file),
        "protocol_identity_sha256": protocol_manifest[
            "protocol_identity_sha256"
        ],
        "processed_path": _relative(processed_path, root),
        "processed_sha256": sha256_file(processed_path),
        "database_path": _relative(paths["database"], root),
        "database_sha256": sha256_file(paths["database"]),
        "source_order_path": _relative(paths["source_order"], root),
        "source_order_file_sha256": sha256_file(paths["source_order"]),
        "source_order_sha256": sha256_obj(source_order),
        "source_count": len(source_order),
        "declared_raw_capacity": int(source_config["declared_raw_capacity"]),
        "processed_pool_capacity": len(source_order),
        "order_mode": source_config["order_mode"],
        "max_chunks_per_source": max_chunks,
        "label_fields_read": [],
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs": 0,
    }
    manifest["source_pool_identity_sha256"] = _identity(
        manifest, "created_at", "source_pool_identity_sha256"
    )
    write_json(manifest, paths["manifest"])
    return {
        "status": "passed",
        "dataset": dataset,
        "source_count": len(source_order),
        "manifest": str(paths["manifest"]),
        "source_pool_identity_sha256": manifest["source_pool_identity_sha256"],
    }


def _validate_source_pool(
    config: Mapping[str, Any], dataset: str, root: Path
) -> dict[str, Any]:
    protocol_manifest = _load_protocol_manifest(config, root)
    paths = _source_pool_paths(config, dataset, root)
    manifest = read_json(paths["manifest"])
    if manifest.get("protocol") != SOURCE_POOL_PROTOCOL or manifest.get("status") != "passed":
        raise RuntimeError(f"v22 source pool not passed: {dataset}")
    if manifest.get("source_pool_identity_sha256") != _identity(
        manifest, "created_at", "source_pool_identity_sha256"
    ):
        raise RuntimeError(f"v22 source pool identity drift: {dataset}")
    if manifest.get("protocol_identity_sha256") != protocol_manifest.get(
        "protocol_identity_sha256"
    ):
        raise RuntimeError(f"v22 source pool protocol identity drift: {dataset}")
    for path_key, hash_key in (
        ("database_path", "database_sha256"),
        ("source_order_path", "source_order_file_sha256"),
        ("processed_path", "processed_sha256"),
    ):
        path = _resolve(str(manifest[path_key]), root)
        if not path.is_file() or sha256_file(path) != manifest[hash_key]:
            raise RuntimeError(f"v22 source pool artifact drift: {dataset}: {path_key}")
    return manifest


def load_single_router(
    config: Mapping[str, Any],
    *,
    root: Path,
    injected_backend: SemanticPredictionBackend | None = None,
) -> tuple[SemanticPredictionBackend, dict[str, Any]]:
    """Load only the frozen GLiNER2-base entry from the shared model lock."""

    routing = dict(config["routing"])
    runtime = dict(config["semantic_runtime"])
    lock_path = _resolve(str(routing["model_lock_path"]), root)
    locked = load_yaml(lock_path)
    model_entries = [
        dict(item)
        for item in locked.get("models") or ()
        if isinstance(item, Mapping)
        and str(item.get("role") or "") == str(routing["single_model_role"])
    ]
    if len(model_entries) != 1:
        raise SemanticResolverProtocolError(
            "v22_single_router_lock_ambiguous", str(routing["single_model_role"])
        )
    model_config = model_entries[0]
    if str(model_config.get("model_id") or "") != str(routing["single_model_id"]):
        raise SemanticResolverProtocolError("v22_single_router_model_drift", str(model_config))
    if str(model_config.get("revision") or "") != str(routing["single_model_revision"]):
        raise SemanticResolverProtocolError("v22_single_router_revision_drift", str(model_config))
    device = str(runtime.get("device") or "cuda").casefold()
    if device == "cuda":
        import torch

        if not torch.cuda.is_available():
            raise SemanticResolverProtocolError(
                "semantic_runtime_device_unavailable", "v22 single router requires CUDA"
            )
    if injected_backend is None:
        local_path, metadata = _verify_model_lock(model_config, workspace_root=root)
        backend = _load_backend(
            model_config,
            local_path,
            runtime_device=device,
            use_fp16=bool(runtime.get("use_fp16", True)),
        )
    else:
        backend = injected_backend
        metadata = {
            "model_id": routing["single_model_id"],
            "role": routing["single_model_role"],
            "revision": routing["single_model_revision"],
            "local_path": "injected-test-backend",
            "files_sha256": {"injected": "test-only"},
        }
    metadata = {
        **metadata,
        "protocol": runtime["protocol"],
        "runtime_device": device,
        "runtime_precision": "fp16" if bool(runtime.get("use_fp16", True)) else "fp32",
        "batch_size": int(runtime.get("batch_size", 8)),
        "model_lock_sha256": sha256_file(lock_path),
    }
    return backend, metadata


def _predict_single_router_batch(
    backend: SemanticPredictionBackend,
    texts: Sequence[str],
    *,
    batch_size: int,
) -> list[list[dict[str, Any]]]:
    if hasattr(backend, "predict_batch"):
        raw = backend.predict_batch(  # type: ignore[attr-defined]
            texts, ALL_SEMANTIC_SCHEMA, batch_size=batch_size
        )
    else:
        raw = [backend.predict(text, ALL_SEMANTIC_SCHEMA) for text in texts]
    return [[asdict(item) for item in predictions] for predictions in raw]


def _extract_chunk_candidates(
    extractor: EntityExtractor,
    row: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    text_value = str(row.get("text") or "")
    raw = extractor._regex_candidates(text_value)
    minimum_score = float(config["routing"]["minimum_prediction_score"])
    for prediction in predictions:
        label = str(prediction.get("label") or "").upper()
        if label not in MAIN_ENTITY_TYPES or float(prediction.get("score", 0.0)) < minimum_score:
            continue
        start, end = int(prediction.get("start", -1)), int(prediction.get("end", -1))
        if not (0 <= start < end <= len(text_value)):
            continue
        family, base_scores, priority = TYPE_DEFAULTS[label]
        raw.append(
            {
                "text": text_value[start:end],
                "type": label,
                "entity_family": family,
                "start": start,
                "end": end,
                "span": [start, end],
                "candidate_sources": ["v22_single_router_model"],
                "base_scores": dict(base_scores),
                "priority": priority,
                "router_model_score": float(prediction.get("score", 0.0)),
            }
        )
    merged = extractor._merge_candidates(raw)
    scored: list[dict[str, Any]] = []
    role = str(config["routing"]["single_model_role"])
    for candidate in merged:
        value = extractor._score_candidate(text_value, candidate)
        value.update(
            {
                "source_key": str(row.get("source_key") or ""),
                "audit_id": str(row.get("audit_id") or ""),
                "doc_id": str(row.get("doc_id") or ""),
                "dataset": str(row.get("dataset") or ""),
            }
        )
        route = route_effective_type(
            value,
            {role: predictions},
            required_roles=[role],
            minimum_votes=1,
            overlap_threshold=float(config["routing"]["overlap_threshold"]),
            minimum_prediction_score=minimum_score,
        )
        value["route_decision"] = route.to_dict()
        scored.append(value)
    return scored


def process_source(
    *,
    source_key: str,
    full_source_text: str,
    chunk_rows: Sequence[Mapping[str, Any]],
    chunk_predictions: Sequence[Sequence[Mapping[str, Any]]],
    config: Mapping[str, Any],
    threshold: float,
) -> dict[str, Any]:
    """Process one source without labels, victim outputs, retrieval, or AUC."""

    if len(chunk_rows) != len(chunk_predictions):
        raise RuntimeError("v22 chunk/prediction count drift")
    for row in chunk_rows:
        assert_selection_payload_is_label_free(row)
    extractor = EntityExtractor(
        enable_ner=False,
        semantic_resolver=None,
        require_semantic_resolver=False,
    )
    candidates: list[dict[str, Any]] = []
    for row, predictions in zip(chunk_rows, chunk_predictions, strict=True):
        candidates.extend(_extract_chunk_candidates(extractor, row, predictions, config))
    candidates = sorted(
        candidates,
        key=lambda item: (
            -float(item.get("attackability_score", 0.0)),
            str(item.get("audit_id") or ""),
            int(item.get("start", -1)),
            str(item.get("type") or ""),
        ),
    )[: int(config["candidate_extraction"]["max_candidates_per_source"])]
    pair_rows: list[dict[str, Any]] = []
    route_rejections: Counter[str] = Counter()
    for candidate in candidates:
        decision = candidate["route_decision"]
        if decision.get("effective_type") is None:
            route_rejections[str(decision.get("status") or "route_ambiguous")] += 1
            continue
        from ..attack.attackability_selector import RouteDecision

        route = RouteDecision(
            declared_type=str(decision["declared_type"]),
            effective_type=str(decision["effective_type"]),
            status=str(decision["status"]),
            route_source=str(decision["route_source"]),
            votes={str(key): int(value) for key, value in (decision.get("votes") or {}).items()},
            supporting_roles=tuple(str(item) for item in decision.get("supporting_roles") or ()),
        )
        clean_candidate = {
            key: value for key, value in candidate.items() if key != "route_decision"
        }
        pair_rows.extend(
            build_pair_candidates(
                clean_candidate,
                full_source_text,
                route,
                counterfactual_count=int(
                    config["candidate_extraction"]["counterfactual_candidates_per_entity"]
                ),
                weights=config["utility"]["weights"],
            )
        )
    main_selected = select_top_pairs(
        pair_rows,
        threshold=threshold,
        required_pairs=int(config["candidate_extraction"]["required_pairs_per_source"]),
        max_pairs_per_original_entity=int(
            config["candidate_extraction"]["maximum_pairs_per_original_entity"]
        ),
    )
    structured_selected = select_structured_extension_pairs(
        pair_rows, threshold=threshold
    )
    return {
        "source_key": source_key,
        "candidate_count": len(candidates),
        "pair_candidate_count": len(pair_rows),
        "route_rejections": dict(route_rejections),
        "eligible": len(main_selected)
        == int(config["candidate_extraction"]["required_pairs_per_source"]),
        "selected_pair_ids": [str(row["pair_id"]) for row in main_selected],
        "structured_extension_pair_ids": [
            str(row["pair_id"]) for row in structured_selected
        ],
        "pair_rows": pair_rows,
        "main_selected": main_selected,
        "structured_selected": structured_selected,
    }


def _scan_paths(
    config: Mapping[str, Any], dataset: str, stage: str, root: Path
) -> dict[str, Path]:
    base = _resolve(str(config["output_root"]), root) / stage / dataset
    return {
        "base": base,
        "plan": base / "scan_plan.json",
        "checkpoint": base / "scan_checkpoint.json",
        "waves": base / "waves",
        "final_manifest": base / "dataset_scan_manifest.json",
        "eligible_sources": base / "query_eligible_sources.json",
        "selected_pairs": base / "selected_pairs.jsonl",
        "structured_pairs": base / "structured_extension_pairs.jsonl",
    }


def _load_source_order(manifest: Mapping[str, Any], root: Path) -> list[str]:
    path = _resolve(str(manifest["source_order_path"]), root)
    payload = read_json(path)
    source_order = [str(item) for item in payload.get("source_order") or ()]
    if sha256_obj(source_order) != manifest.get("source_order_sha256"):
        raise RuntimeError("v22 source order object hash drift")
    return source_order


def _load_frozen_threshold(config: Mapping[str, Any], root: Path) -> tuple[float, dict[str, Any]]:
    path = _resolve(str(config["output_root"]), root) / "calibration" / "threshold_manifest.json"
    if not path.is_file():
        raise RuntimeError("v22 utility threshold is not frozen")
    manifest = read_json(path)
    if manifest.get("protocol") != THRESHOLD_MANIFEST_PROTOCOL or manifest.get("status") != "passed":
        raise RuntimeError("v22 threshold manifest is not passed")
    if manifest.get("threshold_identity_sha256") != _identity(
        manifest, "created_at", "threshold_identity_sha256"
    ):
        raise RuntimeError("v22 threshold manifest identity drift")
    protocol_manifest = _load_protocol_manifest(config, root)
    if manifest.get("config_sha256") != protocol_manifest.get("config_sha256"):
        raise RuntimeError("v22 threshold config identity drift")
    report_path = path.parent / "calibration_evaluation.json"
    if not report_path.is_file() or sha256_file(report_path) != manifest.get(
        "calibration_evaluation_sha256"
    ):
        raise RuntimeError("v22 threshold calibration report drift")
    report = read_json(report_path)
    if (
        report.get("status") != "passed"
        or report.get("evaluation_identity_sha256")
        != _identity(report, "created_at", "evaluation_identity_sha256")
        or report.get("evaluation_identity_sha256")
        != manifest.get("calibration_evaluation_identity_sha256")
        or report.get("selected_threshold") != manifest.get("selected_threshold")
    ):
        raise RuntimeError("v22 threshold is not bound to a passed calibration")
    return float(manifest["selected_threshold"]), manifest


def _scan_plan_identity(plan: Mapping[str, Any]) -> str:
    return _identity(plan, "created_at", "scan_plan_identity_sha256")


def _checkpoint_identity(payload: Mapping[str, Any]) -> str:
    return _identity(payload, "updated_at", "checkpoint_identity_sha256")


def _wave_manifest_identity(payload: Mapping[str, Any]) -> str:
    return _identity(payload, "completed_at", "wave_manifest_identity_sha256")


def _load_scan_checkpoint(path: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        checkpoint: dict[str, Any] = {
            "protocol": SCAN_CHECKPOINT_PROTOCOL,
            "status": "paused",
            "updated_at": _utc_now(),
            "scan_plan_identity_sha256": plan["scan_plan_identity_sha256"],
            "completed_waves": [],
            "wave_manifests": [],
            "scanned_source_count": 0,
            "eligible_source_keys": [],
            "api_calls_performed": 0,
            "victim_calls_performed": 0,
            "retriever_runs": 0,
        }
        checkpoint["checkpoint_identity_sha256"] = _checkpoint_identity(checkpoint)
        return checkpoint
    checkpoint = read_json(path)
    if checkpoint.get("protocol") != SCAN_CHECKPOINT_PROTOCOL:
        raise RuntimeError("v22 scan checkpoint protocol drift")
    if checkpoint.get("scan_plan_identity_sha256") != plan.get(
        "scan_plan_identity_sha256"
    ):
        raise RuntimeError("v22 scan checkpoint plan drift")
    if checkpoint.get("checkpoint_identity_sha256") != _checkpoint_identity(checkpoint):
        raise RuntimeError("v22 scan checkpoint identity drift")
    return checkpoint


def _write_scan_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    checkpoint["updated_at"] = _utc_now()
    checkpoint["checkpoint_identity_sha256"] = _checkpoint_identity(checkpoint)
    write_json(checkpoint, path)


def _read_source_batch(
    database_path: Path, source_keys: Sequence[str]
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    connection = sqlite3.connect(database_path)
    output: list[tuple[str, str, list[dict[str, Any]]]] = []
    try:
        for source_key in source_keys:
            source_row = connection.execute(
                "SELECT full_text FROM sources WHERE source_key = ?", (source_key,)
            ).fetchone()
            if source_row is None:
                raise RuntimeError(f"v22 source missing from database: {source_key}")
            chunk_rows = [
                json.loads(item[0])
                for item in connection.execute(
                    "SELECT row_json FROM chunks WHERE source_key = ? ORDER BY chunk_rank",
                    (source_key,),
                ).fetchall()
            ]
            if not chunk_rows:
                raise RuntimeError(f"v22 source has no candidate chunks: {source_key}")
            output.append((source_key, str(source_row[0]), chunk_rows))
    finally:
        connection.close()
    return output


def _validate_wave_manifest(
    path: Path, plan: Mapping[str, Any], root: Path
) -> dict[str, Any]:
    manifest = read_json(path)
    if manifest.get("protocol") != WAVE_MANIFEST_PROTOCOL:
        raise RuntimeError(f"v22 wave protocol drift: {path}")
    if manifest.get("scan_plan_identity_sha256") != plan.get(
        "scan_plan_identity_sha256"
    ):
        raise RuntimeError(f"v22 wave plan identity drift: {path}")
    if manifest.get("wave_manifest_identity_sha256") != _wave_manifest_identity(manifest):
        raise RuntimeError(f"v22 wave identity drift: {path}")
    for artifact in (manifest.get("outputs") or {}).values():
        artifact_path = _resolve(str(artifact["path"]), root)
        if not artifact_path.is_file() or sha256_file(artifact_path) != artifact["sha256"]:
            raise RuntimeError(f"v22 wave artifact drift: {artifact_path}")
    return manifest


def _build_scan_plan(
    *,
    config: Mapping[str, Any],
    config_path: Path,
    source_manifest: Mapping[str, Any],
    router_metadata: Mapping[str, Any],
    dataset: str,
    stage: str,
    threshold: float,
    threshold_manifest: Mapping[str, Any] | None,
    fresh_audit_report: Mapping[str, Any] | None,
    root: Path,
) -> dict[str, Any]:
    stage_limit = (
        int(config["calibration"]["projection_sources_per_dataset"])
        if stage == "pilot"
        else int(source_manifest["source_count"])
    )
    plan: dict[str, Any] = {
        "protocol": SCAN_PLAN_PROTOCOL,
        "protocol_version": PROTOCOL_VERSION,
        "method_version": METHOD_VERSION,
        "stage": stage,
        "dataset": dataset,
        "created_at": _utc_now(),
        "config_path": _relative(config_path, root),
        "config_sha256": sha256_file(config_path),
        "source_pool_identity_sha256": source_manifest[
            "source_pool_identity_sha256"
        ],
        "source_order_sha256": source_manifest["source_order_sha256"],
        "source_count": source_manifest["source_count"],
        "stage_source_limit": min(stage_limit, int(source_manifest["source_count"])),
        "wave_size": int(config["execution"]["wave_size"]),
        "target_formal_sources": int(config["scope"]["target_formal_sources"]),
        "single_router_model": dict(router_metadata),
        "selector_version": SELECTOR_VERSION,
        "utility_weights": dict(config["utility"]["weights"]),
        "utility_threshold": threshold,
        "threshold_identity_sha256": (
            threshold_manifest.get("threshold_identity_sha256")
            if threshold_manifest is not None
            else None
        ),
        "fresh_audit_evaluation_identity_sha256": (
            fresh_audit_report.get("evaluation_identity_sha256")
            if fresh_audit_report is not None
            else None
        ),
        "candidate_policy": dict(config["candidate_extraction"]),
        "label_fields_read": [],
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs": 0,
    }
    plan["scan_plan_identity_sha256"] = _scan_plan_identity(plan)
    return plan


def _write_wave_outputs(
    wave_dir: Path,
    *,
    source_results: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    main_rows: Sequence[Mapping[str, Any]],
    structured_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    artifacts = {
        "source_results": (wave_dir / "source_results.jsonl", source_results),
        "pair_candidates": (wave_dir / "pair_candidates.jsonl", pair_rows),
        "selected_main_pairs": (wave_dir / "selected_main_pairs.jsonl", main_rows),
        "structured_extension_pairs": (
            wave_dir / "structured_extension_pairs.jsonl",
            structured_rows,
        ),
    }
    outputs: dict[str, dict[str, Any]] = {}
    for name, (path, rows) in artifacts.items():
        write_jsonl_atomic((dict(row) for row in rows), path)
        outputs[name] = {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "rows": len(rows),
        }
    return outputs


def run_scan(
    config_path: str | Path,
    *,
    dataset: str,
    stage: str,
    resume: bool,
    max_new_waves: int,
    project_root: str | Path,
    injected_backend: SemanticPredictionBackend | None = None,
) -> dict[str, Any]:
    """Run pilot or formal selection in immutable resumable waves."""

    if not resume:
        raise RuntimeError("v22 scan requires --resume")
    if stage not in {"pilot", "formal_scan"}:
        raise ValueError("v22 scan stage must be pilot or formal_scan")
    if max_new_waves < 1:
        raise ValueError("max_new_waves must be positive")
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_v22_config(config_file)
    source_manifest = _validate_source_pool(config, dataset, root)
    source_order = _load_source_order(source_manifest, root)
    if stage == "formal_scan":
        threshold, threshold_manifest = _load_frozen_threshold(config, root)
        fresh_audit_report = _load_passed_fresh_audit(config, root)
    else:
        threshold = min(float(item) for item in config["utility"]["threshold_grid"])
        threshold_manifest = None
        fresh_audit_report = None
    backend, router_metadata = load_single_router(
        config, root=root, injected_backend=injected_backend
    )
    paths = _scan_paths(config, dataset, stage, root)
    paths["waves"].mkdir(parents=True, exist_ok=True)
    expected_plan = _build_scan_plan(
        config=config,
        config_path=config_file,
        source_manifest=source_manifest,
        router_metadata=router_metadata,
        dataset=dataset,
        stage=stage,
        threshold=threshold,
        threshold_manifest=threshold_manifest,
        fresh_audit_report=fresh_audit_report,
        root=root,
    )
    if paths["plan"].exists():
        existing_plan = read_json(paths["plan"])
        expected_plan["created_at"] = existing_plan.get("created_at")
        expected_plan["scan_plan_identity_sha256"] = _scan_plan_identity(expected_plan)
        if existing_plan != expected_plan:
            raise RuntimeError(f"v22 scan plan identity drift: {paths['plan']}")
        plan = existing_plan
    else:
        write_json(expected_plan, paths["plan"])
        plan = expected_plan
    checkpoint = _load_scan_checkpoint(paths["checkpoint"], plan)
    completed = [int(item) for item in checkpoint.get("completed_waves") or ()]
    for record in checkpoint.get("wave_manifests") or ():
        manifest_path = _resolve(str(record["path"]), root)
        if sha256_file(manifest_path) != record["sha256"]:
            raise RuntimeError("v22 checkpoint wave hash drift")
        _validate_wave_manifest(manifest_path, plan, root)
    source_limit = int(plan["stage_source_limit"])
    wave_size = int(plan["wave_size"])
    target = int(plan["target_formal_sources"])
    new_waves = 0
    database_path = _resolve(str(source_manifest["database_path"]), root)
    while new_waves < max_new_waves:
        start = int(checkpoint["scanned_source_count"])
        if start >= source_limit:
            break
        if stage == "formal_scan" and len(checkpoint["eligible_source_keys"]) >= target:
            break
        end = min(source_limit, start + wave_size)
        requested_keys = source_order[start:end]
        source_batch = _read_source_batch(database_path, requested_keys)
        flat_texts: list[str] = []
        chunk_counts: list[int] = []
        for _, _, chunk_rows in source_batch:
            chunk_counts.append(len(chunk_rows))
            flat_texts.extend(str(row["text"]) for row in chunk_rows)
        flat_predictions = _predict_single_router_batch(
            backend,
            flat_texts,
            batch_size=int(config["semantic_runtime"]["batch_size"]),
        )
        prediction_cursor = 0
        source_results: list[dict[str, Any]] = []
        pair_rows: list[dict[str, Any]] = []
        main_rows: list[dict[str, Any]] = []
        structured_rows: list[dict[str, Any]] = []
        retained_keys: list[str] = []
        newly_eligible: list[str] = []
        for (source_key, full_text, chunk_rows), chunk_count in zip(
            source_batch, chunk_counts, strict=True
        ):
            predictions = flat_predictions[
                prediction_cursor : prediction_cursor + chunk_count
            ]
            prediction_cursor += chunk_count
            result = process_source(
                source_key=source_key,
                full_source_text=full_text,
                chunk_rows=chunk_rows,
                chunk_predictions=predictions,
                config=config,
                threshold=threshold,
            )
            retained_keys.append(source_key)
            pair_rows.extend(result.pop("pair_rows"))
            main_selected = result.pop("main_selected")
            structured_selected = result.pop("structured_selected")
            main_rows.extend(main_selected)
            structured_rows.extend(structured_selected)
            source_results.append(result)
            if bool(result["eligible"]):
                newly_eligible.append(source_key)
            if (
                stage == "formal_scan"
                and len(checkpoint["eligible_source_keys"]) + len(newly_eligible) >= target
            ):
                break
        if not retained_keys:
            raise RuntimeError("v22 scan wave retained no sources")
        wave_index = len(completed) + 1
        wave_dir = paths["waves"] / f"wave_{wave_index:04d}"
        if wave_dir.exists() and any(wave_dir.iterdir()):
            raise RuntimeError(f"v22 partial wave exists: {wave_dir}")
        wave_dir.mkdir(parents=True, exist_ok=True)
        outputs = _write_wave_outputs(
            wave_dir,
            source_results=source_results,
            pair_rows=pair_rows,
            main_rows=main_rows,
            structured_rows=structured_rows,
        )
        failure_counts: Counter[str] = Counter()
        type_counts: Counter[str] = Counter()
        rerouted = 0
        for row in pair_rows:
            failure_counts.update(row.get("hard_gate_failure_reasons") or ())
            type_counts[str(row.get("effective_type") or "")] += 1
            rerouted += int(row.get("route_status") == "rerouted")
        manifest: dict[str, Any] = {
            "protocol": WAVE_MANIFEST_PROTOCOL,
            "status": "complete",
            "completed_at": _utc_now(),
            "scan_plan_identity_sha256": plan["scan_plan_identity_sha256"],
            "dataset": dataset,
            "stage": stage,
            "wave_index": wave_index,
            "source_start": start,
            "source_end": start + len(retained_keys),
            "source_keys": retained_keys,
            "source_keys_sha256": sha256_obj(retained_keys),
            "eligible_source_keys": newly_eligible,
            "eligible_source_count": len(newly_eligible),
            "pair_candidate_count": len(pair_rows),
            "rerouted_pair_candidate_count": rerouted,
            "pair_candidates_by_effective_type": dict(type_counts),
            "hard_gate_failures_by_reason": dict(failure_counts),
            "single_router_model": dict(router_metadata),
            "outputs": outputs,
            "api_calls_performed": 0,
            "victim_calls_performed": 0,
            "retriever_runs": 0,
        }
        manifest["wave_manifest_identity_sha256"] = _wave_manifest_identity(manifest)
        manifest_path = wave_dir / "wave_manifest.json"
        write_json(manifest, manifest_path)
        checkpoint["completed_waves"].append(wave_index)
        checkpoint["wave_manifests"].append(
            {
                "wave_index": wave_index,
                "path": _relative(manifest_path, root),
                "sha256": sha256_file(manifest_path),
                "identity_sha256": manifest["wave_manifest_identity_sha256"],
            }
        )
        checkpoint["scanned_source_count"] = start + len(retained_keys)
        checkpoint["eligible_source_keys"].extend(newly_eligible)
        if len(checkpoint["eligible_source_keys"]) > target and stage == "formal_scan":
            raise RuntimeError("v22 exact eligible target overflow")
        complete = (
            len(checkpoint["eligible_source_keys"]) == target
            if stage == "formal_scan"
            else int(checkpoint["scanned_source_count"]) == source_limit
        )
        exhausted = int(checkpoint["scanned_source_count"]) == source_limit
        checkpoint["status"] = (
            "passed"
            if complete
            else "failed_capacity_shortfall"
            if exhausted and stage == "formal_scan"
            else "paused"
        )
        _write_scan_checkpoint(paths["checkpoint"], checkpoint)
        completed.append(wave_index)
        new_waves += 1
        if checkpoint["status"] != "paused":
            break
    if checkpoint["status"] == "passed" and stage == "formal_scan":
        _finalize_dataset_scan(config, dataset, plan, checkpoint, root)
    return {
        "status": checkpoint["status"],
        "dataset": dataset,
        "stage": stage,
        "completed_waves": len(checkpoint["completed_waves"]),
        "new_waves": new_waves,
        "scanned_source_count": checkpoint["scanned_source_count"],
        "eligible_source_count": len(checkpoint["eligible_source_keys"]),
        "checkpoint": str(paths["checkpoint"]),
        "single_router_model": {
            "model_id": router_metadata["model_id"],
            "revision": router_metadata["revision"],
        },
    }


def _finalize_dataset_scan(
    config: Mapping[str, Any],
    dataset: str,
    plan: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    root: Path,
) -> dict[str, Any]:
    paths = _scan_paths(config, dataset, "formal_scan", root)
    eligible_order = [str(item) for item in checkpoint["eligible_source_keys"]]
    target = int(config["scope"]["target_formal_sources"])
    if len(eligible_order) != target or len(set(eligible_order)) != target:
        raise RuntimeError("v22 formal whitelist must contain exactly 2250 unique sources")
    pair_lookup: dict[str, dict[str, Any]] = {}
    structured_lookup: dict[str, dict[str, Any]] = {}
    for record in checkpoint.get("wave_manifests") or ():
        manifest = _validate_wave_manifest(_resolve(str(record["path"]), root), plan, root)
        for row in read_jsonl(_resolve(str(manifest["outputs"]["selected_main_pairs"]["path"]), root)):
            pair_lookup[str(row["pair_id"])] = row
        for row in read_jsonl(
            _resolve(str(manifest["outputs"]["structured_extension_pairs"]["path"]), root)
        ):
            structured_lookup[str(row["pair_id"])] = row
    eligible_set = set(eligible_order)
    selected_pairs = sorted(
        (row for row in pair_lookup.values() if str(row["source_key"]) in eligible_set),
        key=lambda row: (
            eligible_order.index(str(row["source_key"])),
            -float(row["utility_score"]),
            str(row["pair_id"]),
        ),
    )
    counts = Counter(str(row["source_key"]) for row in selected_pairs)
    if set(counts) != eligible_set or set(counts.values()) != {
        int(config["candidate_extraction"]["required_pairs_per_source"])
    }:
        raise RuntimeError("v22 selected pair fixed budget drift")
    structured_pairs = sorted(
        (row for row in structured_lookup.values() if str(row["source_key"]) in eligible_set),
        key=lambda row: (str(row["source_key"]), -float(row["utility_score"]), str(row["pair_id"])),
    )
    whitelist = {
        "protocol": "pcv_v22_attackability_whitelist_r1",
        "dataset": dataset,
        "source_keys": eligible_order,
        "source_keys_sha256": sha256_obj(eligible_order),
        "source_count": len(eligible_order),
        "selection_seed": int(config["selection_seed"]),
        "membership_assigned": False,
        "label_fields_read": [],
    }
    write_json(whitelist, paths["eligible_sources"])
    write_jsonl_atomic(selected_pairs, paths["selected_pairs"])
    write_jsonl_atomic(structured_pairs, paths["structured_pairs"])
    manifest: dict[str, Any] = {
        "protocol": "pcv_v22_dataset_scan_manifest_r1",
        "status": "passed_pending_fresh_audit_and_shadow",
        "created_at": _utc_now(),
        "dataset": dataset,
        "scan_plan_identity_sha256": plan["scan_plan_identity_sha256"],
        "checkpoint_identity_sha256": checkpoint["checkpoint_identity_sha256"],
        "source_count": len(eligible_order),
        "pair_count": len(selected_pairs),
        "structured_extension_pair_count": len(structured_pairs),
        "whitelist_path": _relative(paths["eligible_sources"], root),
        "whitelist_sha256": sha256_file(paths["eligible_sources"]),
        "selected_pairs_path": _relative(paths["selected_pairs"], root),
        "selected_pairs_sha256": sha256_file(paths["selected_pairs"]),
        "structured_pairs_path": _relative(paths["structured_pairs"], root),
        "structured_pairs_sha256": sha256_file(paths["structured_pairs"]),
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs": 0,
    }
    manifest["dataset_scan_identity_sha256"] = _identity(
        manifest, "created_at", "dataset_scan_identity_sha256"
    )
    if paths["final_manifest"].exists():
        existing = read_json(paths["final_manifest"])
        manifest["created_at"] = existing.get("created_at")
        manifest["dataset_scan_identity_sha256"] = _identity(
            manifest, "created_at", "dataset_scan_identity_sha256"
        )
        if existing != manifest:
            raise RuntimeError("v22 dataset scan finalization drift")
    else:
        write_json(manifest, paths["final_manifest"])
    return manifest


def _load_completed_scan(
    config: Mapping[str, Any], dataset: str, stage: str, root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = _scan_paths(config, dataset, stage, root)
    if not paths["plan"].is_file() or not paths["checkpoint"].is_file():
        raise RuntimeError(f"v22 {stage} scan missing: {dataset}")
    plan = read_json(paths["plan"])
    if (
        plan.get("protocol") != SCAN_PLAN_PROTOCOL
        or plan.get("dataset") != dataset
        or plan.get("stage") != stage
        or plan.get("scan_plan_identity_sha256") != _scan_plan_identity(plan)
    ):
        raise RuntimeError(f"v22 {stage} scan plan drift: {dataset}")
    checkpoint = _load_scan_checkpoint(paths["checkpoint"], plan)
    if checkpoint.get("status") != "passed":
        raise RuntimeError(f"v22 {stage} scan not passed: {dataset}")
    for record in checkpoint.get("wave_manifests") or ():
        path = _resolve(str(record["path"]), root)
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"v22 {stage} wave record drift: {dataset}")
        _validate_wave_manifest(path, plan, root)
    return plan, checkpoint


def _load_final_scan(
    config: Mapping[str, Any], dataset: str, root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan, checkpoint = _load_completed_scan(config, dataset, "formal_scan", root)
    paths = _scan_paths(config, dataset, "formal_scan", root)
    if not paths["final_manifest"].is_file():
        raise RuntimeError(f"v22 formal scan final manifest missing: {dataset}")
    manifest = read_json(paths["final_manifest"])
    if (
        manifest.get("protocol") != "pcv_v22_dataset_scan_manifest_r1"
        or manifest.get("status") != "passed_pending_fresh_audit_and_shadow"
        or manifest.get("dataset") != dataset
        or manifest.get("dataset_scan_identity_sha256")
        != _identity(manifest, "created_at", "dataset_scan_identity_sha256")
        or manifest.get("scan_plan_identity_sha256")
        != plan.get("scan_plan_identity_sha256")
        or manifest.get("checkpoint_identity_sha256")
        != checkpoint.get("checkpoint_identity_sha256")
    ):
        raise RuntimeError(f"v22 formal scan manifest drift: {dataset}")
    for path_key, hash_key in (
        ("whitelist_path", "whitelist_sha256"),
        ("selected_pairs_path", "selected_pairs_sha256"),
        ("structured_pairs_path", "structured_pairs_sha256"),
    ):
        artifact = _resolve(str(manifest.get(path_key) or ""), root)
        if not artifact.is_file() or sha256_file(artifact) != manifest.get(hash_key):
            raise RuntimeError(f"v22 formal scan artifact drift: {dataset}/{path_key}")
    whitelist = read_json(_resolve(str(manifest["whitelist_path"]), root))
    source_keys = [str(item) for item in whitelist.get("source_keys") or ()]
    target = int(config["scope"]["target_formal_sources"])
    if (
        whitelist.get("protocol") != "pcv_v22_attackability_whitelist_r1"
        or whitelist.get("dataset") != dataset
        or bool(whitelist.get("membership_assigned"))
        or whitelist.get("label_fields_read") != []
        or len(source_keys) != target
        or len(set(source_keys)) != target
        or whitelist.get("source_keys_sha256") != sha256_obj(source_keys)
        or source_keys != [str(item) for item in checkpoint["eligible_source_keys"]]
        or int(manifest.get("source_count", -1)) != target
    ):
        raise RuntimeError(f"v22 formal whitelist drift: {dataset}")
    selected_rows = list(
        read_jsonl(_resolve(str(manifest["selected_pairs_path"]), root))
    )
    required_pairs = int(config["candidate_extraction"]["required_pairs_per_source"])
    counts = Counter(str(row.get("source_key") or "") for row in selected_rows)
    pair_ids = [str(row.get("pair_id") or "") for row in selected_rows]
    if (
        len(selected_rows) != target * required_pairs
        or set(counts) != set(source_keys)
        or set(counts.values()) != {required_pairs}
        or not all(pair_ids)
        or len(set(pair_ids)) != len(pair_ids)
        or int(manifest.get("pair_count", -1)) != len(selected_rows)
    ):
        raise RuntimeError(f"v22 formal selected-pair budget drift: {dataset}")
    structured_rows = list(
        read_jsonl(_resolve(str(manifest["structured_pairs_path"]), root))
    )
    if (
        any(str(row.get("source_key") or "") not in set(source_keys) for row in structured_rows)
        or int(manifest.get("structured_extension_pair_count", -1))
        != len(structured_rows)
    ):
        raise RuntimeError(f"v22 structured extension scope drift: {dataset}")
    return manifest, whitelist


def _pilot_rows(
    config: Mapping[str, Any], root: Path
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    checkpoints: dict[str, dict[str, Any]] = {}
    for dataset in sorted(config["source_pools"]):
        plan, checkpoint = _load_completed_scan(config, dataset, "pilot", root)
        expected = int(config["calibration"]["projection_sources_per_dataset"])
        if int(checkpoint["scanned_source_count"]) != min(
            expected, int(plan["source_count"])
        ):
            raise RuntimeError(f"v22 pilot source count drift: {dataset}")
        checkpoints[dataset] = checkpoint
        for record in checkpoint["wave_manifests"]:
            manifest = _validate_wave_manifest(
                _resolve(str(record["path"]), root), plan, root
            )
            rows.extend(
                read_jsonl(
                    _resolve(
                        str(manifest["outputs"]["pair_candidates"]["path"]), root
                    )
                )
            )
    return rows, checkpoints


def _score_strata(rows: Sequence[Mapping[str, Any]], count: int) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        signature = str(row.get("fact_signature") or row.get("pair_id") or "")
        current = unique.get(signature)
        if current is None or float(row.get("utility_score", 0.0)) > float(
            current.get("utility_score", 0.0)
        ):
            unique[signature] = dict(row)
    ordered = sorted(
        unique.values(),
        key=lambda row: (float(row.get("utility_score", 0.0)), str(row.get("pair_id") or "")),
    )
    if len(ordered) < count:
        raise RuntimeError(
            f"v22 calibration cell shortfall: required={count} available={len(ordered)}"
        )
    strata = 4
    per_stratum = count // strata
    selected: list[dict[str, Any]] = []
    for stratum in range(strata):
        start = len(ordered) * stratum // strata
        end = len(ordered) * (stratum + 1) // strata
        bucket = sorted(
            ordered[start:end],
            key=lambda row: (
                sha256_text(
                    "\0".join(
                        (
                            PROTOCOL_VERSION,
                            "calibration",
                            str(stratum),
                            str(row.get("pair_id") or ""),
                        )
                    )
                ),
                str(row.get("pair_id") or ""),
            ),
        )
        selected.extend(bucket[:per_stratum])
    if len(selected) != count:
        raise RuntimeError("v22 calibration score-strata allocation drift")
    return selected


def _blinded_review_row(calibration_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "review_id": calibration_id,
        "dataset": str(row["dataset"]),
        "effective_type": str(row["effective_type"]),
        "true_claim": str(row["true_claim"]),
        "counterfactual_claim": str(row["counterfactual_claim"]),
        "original_entity": str(row["original_entity"]),
        "counterfactual_entity": str(row["counterfactual_entity"]),
        "source_evidence_excerpt": str(row["true_claim"]),
    }


def _structural_controls(
    dataset: str, entity_type: str, seeds: Sequence[Mapping[str, Any]]
) -> list[tuple[dict[str, Any], str]]:
    if len(seeds) < 4:
        raise RuntimeError("v22 structural controls require four seed rows")
    controls: list[tuple[dict[str, Any], str]] = []
    first = dict(seeds[0])
    first["counterfactual_entity"] = first["original_entity"]
    first["counterfactual_claim"] = first["true_claim"]
    controls.append((first, "counterfactual_present_in_source"))
    second = dict(seeds[1])
    second["counterfactual_claim"] = (
        str(second["counterfactual_claim"]).rstrip(". ") + " and an unrelated amount changed."
    )
    controls.append((second, "not_single_slot_substitution"))
    third = dict(seeds[2])
    third.update(
        {
            "true_claim": "The system.",
            "counterfactual_claim": "The service.",
            "original_entity": "system",
            "counterfactual_entity": "service",
        }
    )
    controls.append((third, "generic_nominal_fragment"))
    fourth = dict(seeds[3])
    fourth["source_evidence_excerpt"] = "Evidence does not contain the claimed entity."
    controls.append((fourth, "source_span_or_grounding_mismatch"))
    return controls


def _review_template(review_id: str) -> dict[str, Any]:
    return {
        "review_id": review_id,
        **{field: None for field in REVIEW_FIELDS},
        "reason_codes": [],
        "evidence": "",
    }


def freeze_calibration(
    config_path: str | Path,
    *,
    resume: bool,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_v22_config(config_file)
    output = _resolve(str(config["output_root"]), root) / "calibration"
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "calibration_plan.json"
    if plan_path.exists():
        if not resume:
            raise RuntimeError("v22 calibration is already frozen")
        plan = read_json(plan_path)
        if plan.get("calibration_plan_identity_sha256") != _identity(
            plan, "created_at", "calibration_plan_identity_sha256"
        ):
            raise RuntimeError("v22 calibration plan identity drift")
        for artifact in plan["artifacts"].values():
            path = _resolve(str(artifact["path"]), root)
            if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                raise RuntimeError(f"v22 calibration artifact drift: {path}")
        return {
            "status": "frozen",
            "rows": plan["row_count"],
            "plan": str(plan_path),
            "resumed": True,
        }
    pilot_rows, checkpoints = _pilot_rows(config, root)
    real_per_cell = int(config["calibration"]["real_rows_per_cell"])
    controls_per_cell = int(config["calibration"]["structural_controls_per_cell"])
    review_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    assistant_template: list[dict[str, Any]] = []
    base_user_ids: list[str] = []
    calibration_pair_ids: list[str] = []
    for dataset in sorted(config["source_pools"]):
        for entity_type in sorted(MAIN_ENTITY_TYPES):
            cell_rows = [
                row
                for row in pilot_rows
                if str(row.get("dataset") or "") == dataset
                and str(row.get("effective_type") or "") == entity_type
                and bool(row.get("hard_gate_passed"))
            ]
            selected = _score_strata(cell_rows, real_per_cell)
            cell_private: list[dict[str, Any]] = []
            for index, row in enumerate(selected):
                review_id = f"v22_cal_{dataset}_{entity_type}_{index:02d}"
                blinded = _blinded_review_row(review_id, row)
                review_rows.append(blinded)
                assistant_template.append(_review_template(review_id))
                private = {
                    "review_id": review_id,
                    "dataset": dataset,
                    "effective_type": entity_type,
                    "row_kind": "real_candidate",
                    "pair_id": row["pair_id"],
                    "source_key": row["source_key"],
                    "fact_signature": row["fact_signature"],
                    "utility_score": row["utility_score"],
                    "expected_attack_usable": None,
                }
                private_rows.append(private)
                cell_private.append(private)
                calibration_pair_ids.append(str(row["pair_id"]))
            controls = _structural_controls(dataset, entity_type, selected[:controls_per_cell])
            control_ids: list[str] = []
            for control_index, (row, reason) in enumerate(controls):
                review_id = f"v22_cal_{dataset}_{entity_type}_control_{control_index:02d}"
                blinded = _blinded_review_row(review_id, row)
                if reason == "source_span_or_grounding_mismatch":
                    blinded["source_evidence_excerpt"] = str(row["source_evidence_excerpt"])
                review_rows.append(blinded)
                assistant_template.append(_review_template(review_id))
                private_rows.append(
                    {
                        "review_id": review_id,
                        "dataset": dataset,
                        "effective_type": entity_type,
                        "row_kind": "structural_control",
                        "control_reason": reason,
                        "pair_id": None,
                        "source_key": None,
                        "utility_score": None,
                        "expected_attack_usable": "no",
                    }
                )
                control_ids.append(review_id)
            real_user_id = sorted(
                (item["review_id"] for item in cell_private),
                key=lambda value: sha256_text(
                    "\0".join((PROTOCOL_VERSION, "user_base", value))
                ),
            )[0]
            base_user_ids.extend([*control_ids, real_user_id])
    expected_total = int(config["calibration"]["total_rows"])
    if len(review_rows) != expected_total or len(private_rows) != expected_total:
        raise RuntimeError("v22 calibration total row drift")
    review_rows = sorted(review_rows, key=lambda row: str(row["review_id"]))
    private_rows = sorted(private_rows, key=lambda row: str(row["review_id"]))
    assistant_template = sorted(assistant_template, key=lambda row: str(row["review_id"]))
    blinded_path = output / "calibration_blinded.jsonl"
    private_path = output / "private" / "calibration_key.jsonl"
    assistant_path = output / "private" / "assistant_labels.template.jsonl"
    write_jsonl_atomic(review_rows, blinded_path)
    write_jsonl_atomic(private_rows, private_path)
    write_jsonl_atomic(assistant_template, assistant_path)
    plan: dict[str, Any] = {
        "protocol": CALIBRATION_PLAN_PROTOCOL,
        "status": "frozen_before_labels",
        "created_at": _utc_now(),
        "config_path": _relative(config_file, root),
        "config_sha256": sha256_file(config_file),
        "row_count": len(review_rows),
        "cell_count": int(config["calibration"]["cells"]),
        "base_user_review_ids": sorted(base_user_ids),
        "base_user_review_ids_sha256": sha256_obj(sorted(base_user_ids)),
        "calibration_pair_ids_sha256": sha256_obj(sorted(calibration_pair_ids)),
        "pilot_checkpoint_identities": {
            dataset: checkpoint["checkpoint_identity_sha256"]
            for dataset, checkpoint in sorted(checkpoints.items())
        },
        "review_schema": {
            "version": LABEL_SCHEMA_VERSION,
            "fields": list(REVIEW_FIELDS),
            "allowed_values": sorted(REVIEW_VALUES),
        },
        "artifacts": {
            "blinded": {
                "path": _relative(blinded_path, root),
                "sha256": sha256_file(blinded_path),
            },
            "private_key": {
                "path": _relative(private_path, root),
                "sha256": sha256_file(private_path),
            },
            "assistant_template": {
                "path": _relative(assistant_path, root),
                "sha256": sha256_file(assistant_path),
            },
        },
        "attack_auc_visible": False,
        "victim_responses_visible": False,
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs": 0,
    }
    plan["calibration_plan_identity_sha256"] = _identity(
        plan, "created_at", "calibration_plan_identity_sha256"
    )
    write_json(plan, plan_path)
    return {
        "status": "frozen",
        "rows": len(review_rows),
        "base_user_review_rows": len(base_user_ids),
        "plan": str(plan_path),
        "assistant_template": str(assistant_path),
        "resumed": False,
    }


def _load_calibration_plan(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve(str(config["output_root"]), root) / "calibration" / "calibration_plan.json"
    if not path.is_file():
        raise RuntimeError("v22 calibration is not frozen")
    plan = read_json(path)
    if plan.get("protocol") != CALIBRATION_PLAN_PROTOCOL:
        raise RuntimeError("v22 calibration protocol drift")
    if plan.get("calibration_plan_identity_sha256") != _identity(
        plan, "created_at", "calibration_plan_identity_sha256"
    ):
        raise RuntimeError("v22 calibration plan identity drift")
    protocol_manifest = _load_protocol_manifest(config, root)
    if plan.get("config_sha256") != protocol_manifest.get("config_sha256"):
        raise RuntimeError("v22 calibration config identity drift")
    for artifact in plan["artifacts"].values():
        artifact_path = _resolve(str(artifact["path"]), root)
        if not artifact_path.is_file() or sha256_file(artifact_path) != artifact["sha256"]:
            raise RuntimeError(f"v22 calibration artifact drift: {artifact_path}")
    return plan


def _validate_label_rows(
    labels_path: Path,
    *,
    expected_ids: set[str],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(labels_path):
        review_id = str(row.get("review_id") or "")
        if not review_id or review_id in rows:
            raise RuntimeError("v22 review labels contain missing/duplicate review_id")
        for field in REVIEW_FIELDS:
            if str(row.get(field) or "") not in REVIEW_VALUES:
                raise RuntimeError(f"v22 invalid review label: {review_id}:{field}")
        if not isinstance(row.get("reason_codes"), list):
            raise RuntimeError(f"v22 reason_codes must be a list: {review_id}")
        if not isinstance(row.get("evidence"), str):
            raise RuntimeError(f"v22 evidence must be a string: {review_id}")
        rows[review_id] = row
    if set(rows) != expected_ids:
        missing = sorted(expected_ids - set(rows))[:5]
        extra = sorted(set(rows) - expected_ids)[:5]
        raise RuntimeError(f"v22 review label identity mismatch: missing={missing} extra={extra}")
    return rows


def validate_assistant_labels(
    config_path: str | Path,
    labels_path: str | Path,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_v22_config(Path(config_path).resolve())
    plan = _load_calibration_plan(config, root)
    blinded = list(read_jsonl(_resolve(str(plan["artifacts"]["blinded"]["path"]), root)))
    expected = {str(row["review_id"]) for row in blinded}
    labels_file = Path(labels_path).resolve()
    labels = _validate_label_rows(labels_file, expected_ids=expected)
    counts = Counter(str(row["attack_usable"]) for row in labels.values())
    receipt: dict[str, Any] = {
        "protocol": LABEL_SCHEMA_VERSION,
        "reviewer_role": "assistant",
        "status": "validated",
        "calibration_plan_identity_sha256": plan["calibration_plan_identity_sha256"],
        "labels_path": _relative(labels_file, root),
        "labels_sha256": sha256_file(labels_file),
        "rows": len(labels),
        "attack_usable_counts": dict(counts),
    }
    receipt["receipt_identity_sha256"] = sha256_obj(receipt)
    receipt_path = _resolve(str(config["output_root"]), root) / "calibration" / "private" / "assistant_labels_receipt.json"
    if receipt_path.exists() and read_json(receipt_path) != receipt:
        raise RuntimeError("v22 assistant label receipt drift")
    if not receipt_path.exists():
        write_json(receipt, receipt_path)
    return {"status": "validated", "rows": len(labels), "counts": dict(counts), "receipt": str(receipt_path)}


def prepare_user_review(
    config_path: str | Path,
    assistant_labels_path: str | Path,
    *,
    resume: bool,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_v22_config(Path(config_path).resolve())
    plan = _load_calibration_plan(config, root)
    blinded_rows = list(
        read_jsonl(_resolve(str(plan["artifacts"]["blinded"]["path"]), root))
    )
    blinded_by_id = {str(row["review_id"]): row for row in blinded_rows}
    assistant_path = Path(assistant_labels_path).resolve()
    assistant = _validate_label_rows(
        assistant_path, expected_ids=set(blinded_by_id)
    )
    review_ids = set(str(item) for item in plan["base_user_review_ids"])
    review_ids.update(
        review_id
        for review_id, row in assistant.items()
        if str(row["attack_usable"]) == "uncertain"
        or any(str(row[field]) == "uncertain" for field in REVIEW_FIELDS)
    )
    ordered_review_ids = sorted(review_ids)
    user_rows = [blinded_by_id[review_id] for review_id in ordered_review_ids]
    template = [_review_template(review_id) for review_id in ordered_review_ids]
    output = _resolve(str(config["output_root"]), root) / "calibration"
    blinded_path = output / "user_review_blinded.jsonl"
    template_path = output / "user_review_labels.template.jsonl"
    manifest_path = output / "user_review_manifest.json"
    payload: dict[str, Any] = {
        "protocol": "pcv_v22_user_review_manifest_r1",
        "status": "frozen",
        "calibration_plan_identity_sha256": plan["calibration_plan_identity_sha256"],
        "assistant_labels_sha256": sha256_file(assistant_path),
        "review_ids": ordered_review_ids,
        "review_ids_sha256": sha256_obj(ordered_review_ids),
        "base_review_rows": len(plan["base_user_review_ids"]),
        "assistant_uncertain_extra_rows": len(review_ids - set(plan["base_user_review_ids"])),
        "total_rows": len(review_ids),
        "assistant_labels_visible": False,
        "sampling_reason_visible": False,
    }
    if manifest_path.exists():
        if not resume:
            raise RuntimeError("v22 user review is already frozen")
        payload["blinded_path"] = _relative(blinded_path, root)
        payload["blinded_sha256"] = sha256_file(blinded_path)
        payload["template_path"] = _relative(template_path, root)
        payload["template_sha256"] = sha256_file(template_path)
        payload["manifest_identity_sha256"] = _identity(
            payload, "manifest_identity_sha256"
        )
        if read_json(manifest_path) != payload:
            raise RuntimeError("v22 user review manifest drift")
    else:
        write_jsonl_atomic(user_rows, blinded_path)
        write_jsonl_atomic(template, template_path)
        payload["blinded_path"] = _relative(blinded_path, root)
        payload["blinded_sha256"] = sha256_file(blinded_path)
        payload["template_path"] = _relative(template_path, root)
        payload["template_sha256"] = sha256_file(template_path)
        payload["manifest_identity_sha256"] = _identity(
            payload, "manifest_identity_sha256"
        )
        write_json(payload, manifest_path)
    return {
        "status": "frozen",
        "rows": len(review_ids),
        "blinded": str(blinded_path),
        "template": str(template_path),
        "manifest": str(manifest_path),
    }


def _load_user_review_manifest(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve(str(config["output_root"]), root) / "calibration" / "user_review_manifest.json"
    if not path.is_file():
        raise RuntimeError("v22 user review is not frozen")
    manifest = read_json(path)
    if manifest.get("manifest_identity_sha256") != _identity(
        manifest, "manifest_identity_sha256"
    ):
        raise RuntimeError("v22 user review manifest identity drift")
    calibration_plan = _load_calibration_plan(config, root)
    if manifest.get("calibration_plan_identity_sha256") != calibration_plan.get(
        "calibration_plan_identity_sha256"
    ):
        raise RuntimeError("v22 user review calibration identity drift")
    for path_key, hash_key in (
        ("blinded_path", "blinded_sha256"),
        ("template_path", "template_sha256"),
    ):
        artifact = _resolve(str(manifest[path_key]), root)
        if not artifact.is_file() or sha256_file(artifact) != manifest[hash_key]:
            raise RuntimeError("v22 user review artifact drift")
    return manifest


def _projection_by_threshold(
    config: Mapping[str, Any],
    pilot_rows: Sequence[Mapping[str, Any]],
    threshold: float,
    root: Path,
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for dataset in sorted(config["source_pools"]):
        by_source: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in pilot_rows:
            if str(row.get("dataset") or "") == dataset:
                by_source[str(row["source_key"])].append(row)
        eligible = sum(
            1
            for rows in by_source.values()
            if len(
                select_top_pairs(
                    rows,
                    threshold=threshold,
                    required_pairs=int(config["candidate_extraction"]["required_pairs_per_source"]),
                    max_pairs_per_original_entity=int(
                        config["candidate_extraction"]["maximum_pairs_per_original_entity"]
                    ),
                )
            )
            == int(config["candidate_extraction"]["required_pairs_per_source"])
        )
        scanned = int(config["calibration"]["projection_sources_per_dataset"])
        source_manifest = _validate_source_pool(config, dataset, root)
        projected = eligible / max(1, scanned) * int(source_manifest["source_count"])
        result[dataset] = {
            "pilot_sources": scanned,
            "eligible_sources": eligible,
            "eligible_rate": eligible / max(1, scanned),
            "processed_pool_sources": int(source_manifest["source_count"]),
            "projected_eligible_sources": projected,
        }
    return result


def evaluate_calibration(
    config_path: str | Path,
    assistant_labels_path: str | Path,
    user_labels_path: str | Path,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_v22_config(config_file)
    plan = _load_calibration_plan(config, root)
    user_manifest = _load_user_review_manifest(config, root)
    private_rows = list(
        read_jsonl(_resolve(str(plan["artifacts"]["private_key"]["path"]), root))
    )
    private_by_id = {str(row["review_id"]): row for row in private_rows}
    assistant_path = Path(assistant_labels_path).resolve()
    if sha256_file(assistant_path) != user_manifest.get("assistant_labels_sha256"):
        raise RuntimeError("v22 assistant labels differ from the frozen user-review input")
    assistant = _validate_label_rows(
        assistant_path, expected_ids=set(private_by_id)
    )
    user_expected = set(
        str(row["review_id"])
        for row in read_jsonl(_resolve(str(user_manifest["blinded_path"]), root))
    )
    user_path = Path(user_labels_path).resolve()
    user = _validate_label_rows(user_path, expected_ids=user_expected)
    control_ids = {
        review_id
        for review_id, row in private_by_id.items()
        if row["row_kind"] == "structural_control"
    }
    control_rejected = sum(
        1
        for review_id in control_ids
        if assistant[review_id]["attack_usable"] == "no"
        and user.get(review_id, {}).get("attack_usable") == "no"
    )
    control_rate = control_rejected / max(1, len(control_ids))
    agreements = sum(
        1
        for review_id, row in user.items()
        if row["attack_usable"] == assistant[review_id]["attack_usable"]
    )
    agreement_rate = agreements / max(1, len(user))
    assistant_positive_reviewed = [
        review_id
        for review_id in user
        if private_by_id[review_id]["row_kind"] == "real_candidate"
        and assistant[review_id]["attack_usable"] == "yes"
        and user[review_id]["attack_usable"] in {"yes", "no"}
    ]
    user_precision = sum(
        user[review_id]["attack_usable"] == "yes"
        for review_id in assistant_positive_reviewed
    ) / max(1, len(assistant_positive_reviewed))
    label_by_pair: dict[str, str] = {}
    for review_id, private in private_by_id.items():
        if private["row_kind"] != "real_candidate":
            continue
        selected_label = (
            user[review_id]["attack_usable"]
            if review_id in user
            else assistant[review_id]["attack_usable"]
        )
        label_by_pair[str(private["pair_id"])] = str(selected_label)
    pilot_rows, _ = _pilot_rows(config, root)
    grid_results: list[dict[str, Any]] = []
    for raw_threshold in config["utility"]["threshold_grid"]:
        threshold = float(raw_threshold)
        labelled = [
            private
            for private in private_rows
            if private["row_kind"] == "real_candidate"
            and float(private["utility_score"]) >= threshold
            and label_by_pair.get(str(private["pair_id"])) in {"yes", "no"}
        ]
        positives = sum(
            label_by_pair[str(private["pair_id"])] == "yes" for private in labelled
        )
        precision = positives / max(1, len(labelled))
        retained_candidates = sum(
            bool(row.get("hard_gate_passed"))
            and float(row.get("utility_score", 0.0)) >= threshold
            and str(row.get("effective_type") or "") in MAIN_ENTITY_TYPES
            for row in pilot_rows
        )
        projection = _projection_by_threshold(config, pilot_rows, threshold, root)
        projected_gate = all(
            values["projected_eligible_sources"]
            >= float(config["calibration"]["gates"]["minimum_projected_eligible_sources_per_dataset"])
            for values in projection.values()
        )
        grid_results.append(
            {
                "threshold": threshold,
                "labelled_candidates": len(labelled),
                "precision": precision,
                "retained_pilot_candidates": retained_candidates,
                "projection": projection,
                "precision_gate_passed": precision
                >= float(config["calibration"]["gates"]["threshold_minimum_precision"]),
                "projection_gate_passed": projected_gate,
            }
        )
    admissible = [
        row
        for row in grid_results
        if row["precision_gate_passed"] and row["projection_gate_passed"]
    ]
    gates = {
        "structural_negative_rejection": control_rate
        >= float(config["calibration"]["gates"]["structural_negative_rejection_rate"]),
        "assistant_user_agreement": agreement_rate
        >= float(config["calibration"]["gates"]["minimum_assistant_user_agreement"]),
        "user_attack_usable_precision": user_precision
        >= float(config["calibration"]["gates"]["minimum_user_attack_usable_precision"]),
        "threshold_available": bool(admissible),
    }
    passed = all(gates.values())
    selected = (
        sorted(
            admissible,
            key=lambda row: (-int(row["retained_pilot_candidates"]), float(row["threshold"])),
        )[0]
        if admissible
        else None
    )
    output = _resolve(str(config["output_root"]), root) / "calibration"
    report: dict[str, Any] = {
        "protocol": "pcv_v22_calibration_evaluation_r1",
        "status": "passed" if passed else "failed_new_protocol_identity_required",
        "created_at": _utc_now(),
        "calibration_plan_identity_sha256": plan["calibration_plan_identity_sha256"],
        "assistant_labels_sha256": sha256_file(assistant_path),
        "user_labels_sha256": sha256_file(user_path),
        "structural_negative_rejection_rate": control_rate,
        "assistant_user_agreement": agreement_rate,
        "user_attack_usable_precision": user_precision,
        "gates": gates,
        "threshold_grid": grid_results,
        "selected_threshold": selected["threshold"] if selected else None,
        "attack_auc_accessed": False,
        "victim_responses_accessed": False,
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs": 0,
    }
    report["evaluation_identity_sha256"] = _identity(
        report, "created_at", "evaluation_identity_sha256"
    )
    report_path = output / "calibration_evaluation.json"
    if report_path.exists():
        existing_report = read_json(report_path)
        report["created_at"] = existing_report.get("created_at")
        report["evaluation_identity_sha256"] = _identity(
            report, "created_at", "evaluation_identity_sha256"
        )
        if existing_report != report:
            raise RuntimeError(
                "v22 calibration evaluation is immutable; create a new protocol identity"
            )
        report = existing_report
    else:
        write_json(report, report_path)
    if passed and selected is not None:
        threshold_manifest: dict[str, Any] = {
            "protocol": THRESHOLD_MANIFEST_PROTOCOL,
            "status": "passed",
            "created_at": _utc_now(),
            "protocol_version": PROTOCOL_VERSION,
            "method_version": METHOD_VERSION,
            "config_sha256": sha256_file(config_file),
            "calibration_evaluation_sha256": sha256_file(report_path),
            "calibration_evaluation_identity_sha256": report[
                "evaluation_identity_sha256"
            ],
            "selected_threshold": selected["threshold"],
            "utility_weights": dict(config["utility"]["weights"]),
            "threshold_grid": list(config["utility"]["threshold_grid"]),
            "selection_rule": config["utility"]["threshold_selection"],
            "selected_projection": selected["projection"],
            "attack_auc_accessed": False,
            "victim_responses_accessed": False,
        }
        threshold_manifest["threshold_identity_sha256"] = _identity(
            threshold_manifest, "created_at", "threshold_identity_sha256"
        )
        threshold_path = output / "threshold_manifest.json"
        if threshold_path.exists():
            existing_threshold = read_json(threshold_path)
            threshold_manifest["created_at"] = existing_threshold.get("created_at")
            threshold_manifest["threshold_identity_sha256"] = _identity(
                threshold_manifest, "created_at", "threshold_identity_sha256"
            )
            if existing_threshold != threshold_manifest:
                raise RuntimeError("v22 frozen threshold identity drift")
        else:
            write_json(threshold_manifest, threshold_path)
    elif (output / "threshold_manifest.json").exists():
        raise RuntimeError("v22 failed calibration cannot coexist with a frozen threshold")
    return {
        "status": report["status"],
        "selected_threshold": report["selected_threshold"],
        "gates": gates,
        "report": str(report_path),
    }


def freeze_fresh_audit(
    config_path: str | Path,
    *,
    resume: bool,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_v22_config(Path(config_path).resolve())
    threshold, threshold_manifest = _load_frozen_threshold(config, root)
    calibration_plan = _load_calibration_plan(config, root)
    calibration_key = list(
        read_jsonl(
            _resolve(
                str(calibration_plan["artifacts"]["private_key"]["path"]), root
            )
        )
    )
    excluded_pair_ids = {
        str(row["pair_id"])
        for row in calibration_key
        if row.get("pair_id") is not None
    }
    excluded_source_keys = {
        str(row["source_key"])
        for row in calibration_key
        if row.get("source_key") is not None
    }
    excluded_fact_signatures = {
        str(row["fact_signature"])
        for row in calibration_key
        if row.get("fact_signature") is not None
    }
    pilot_rows, _ = _pilot_rows(config, root)
    rows_per_cell = int(config["fresh_audit"]["rows_per_dataset_type"])
    blinded: list[dict[str, Any]] = []
    private: list[dict[str, Any]] = []
    templates: list[dict[str, Any]] = []
    for dataset in sorted(config["source_pools"]):
        for entity_type in sorted(MAIN_ENTITY_TYPES):
            candidates = {
                "\0".join((str(row["source_key"]), str(row["fact_signature"]))): dict(row)
                for row in pilot_rows
                if str(row.get("dataset") or "") == dataset
                and str(row.get("effective_type") or "") == entity_type
                and bool(row.get("hard_gate_passed"))
                and float(row.get("utility_score", 0.0)) >= threshold
                and str(row.get("pair_id") or "") not in excluded_pair_ids
                and str(row.get("source_key") or "") not in excluded_source_keys
                and str(row.get("fact_signature") or "")
                not in excluded_fact_signatures
            }
            ordered = sorted(
                candidates.values(),
                key=lambda row: (
                    sha256_text(
                        "\0".join(
                            (
                                PROTOCOL_VERSION,
                                "fresh_audit",
                                dataset,
                                entity_type,
                                str(row["pair_id"]),
                            )
                        )
                    ),
                    str(row["pair_id"]),
                ),
            )
            if len(ordered) < rows_per_cell:
                raise RuntimeError(
                    f"v22 fresh audit cell shortfall: {dataset}/{entity_type}"
                )
            for index, row in enumerate(ordered[:rows_per_cell]):
                review_id = f"v22_audit_{dataset}_{entity_type}_{index:02d}"
                blinded.append(_blinded_review_row(review_id, row))
                templates.append(_review_template(review_id))
                private.append(
                    {
                        "review_id": review_id,
                        "dataset": dataset,
                        "effective_type": entity_type,
                        "pair_id": row["pair_id"],
                        "source_key": row["source_key"],
                        "fact_signature": row["fact_signature"],
                        "utility_score": row["utility_score"],
                    }
                )
    if len(blinded) != int(config["fresh_audit"]["total_rows"]):
        raise RuntimeError("v22 fresh audit total row drift")
    output = _resolve(str(config["output_root"]), root) / "fresh_audit"
    output.mkdir(parents=True, exist_ok=True)
    blinded_path = output / "fresh_audit_blinded.jsonl"
    private_path = output / "private" / "fresh_audit_key.jsonl"
    template_path = output / "fresh_audit_labels.template.jsonl"
    plan_path = output / "fresh_audit_plan.json"
    write_payloads = {
        "blinded": (blinded_path, sorted(blinded, key=lambda row: str(row["review_id"]))),
        "private_key": (private_path, sorted(private, key=lambda row: str(row["review_id"]))),
        "label_template": (template_path, sorted(templates, key=lambda row: str(row["review_id"]))),
    }
    if plan_path.exists():
        if not resume:
            raise RuntimeError("v22 fresh audit already frozen")
        plan = read_json(plan_path)
        if plan.get("fresh_audit_identity_sha256") != _identity(
            plan, "created_at", "fresh_audit_identity_sha256"
        ):
            raise RuntimeError("v22 fresh audit plan drift")
        for artifact in plan["artifacts"].values():
            path = _resolve(str(artifact["path"]), root)
            if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                raise RuntimeError("v22 fresh audit artifact drift")
        return {"status": "frozen", "rows": plan["row_count"], "plan": str(plan_path), "resumed": True}
    for _, (path, rows) in write_payloads.items():
        write_jsonl_atomic(rows, path)
    plan: dict[str, Any] = {
        "protocol": FRESH_AUDIT_PROTOCOL,
        "status": "frozen_before_labels",
        "created_at": _utc_now(),
        "threshold_identity_sha256": threshold_manifest["threshold_identity_sha256"],
        "selected_threshold": threshold,
        "calibration_pair_ids_sha256": calibration_plan[
            "calibration_pair_ids_sha256"
        ],
        "excluded_calibration_source_keys_sha256": sha256_obj(
            sorted(excluded_source_keys)
        ),
        "excluded_calibration_fact_signatures_sha256": sha256_obj(
            sorted(excluded_fact_signatures)
        ),
        "calibration_source_overlap": 0,
        "calibration_fact_signature_overlap": 0,
        "row_count": len(blinded),
        "artifacts": {
            name: {"path": _relative(path, root), "sha256": sha256_file(path)}
            for name, (path, _) in write_payloads.items()
        },
        "attack_auc_visible": False,
        "victim_responses_visible": False,
    }
    plan["fresh_audit_identity_sha256"] = _identity(
        plan, "created_at", "fresh_audit_identity_sha256"
    )
    write_json(plan, plan_path)
    return {"status": "frozen", "rows": len(blinded), "plan": str(plan_path), "template": str(template_path), "resumed": False}


def _load_fresh_audit_plan(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve(str(config["output_root"]), root) / "fresh_audit" / "fresh_audit_plan.json"
    if not path.is_file():
        raise RuntimeError("v22 fresh audit not frozen")
    plan = read_json(path)
    if plan.get("protocol") != FRESH_AUDIT_PROTOCOL or plan.get(
        "fresh_audit_identity_sha256"
    ) != _identity(plan, "created_at", "fresh_audit_identity_sha256"):
        raise RuntimeError("v22 fresh audit plan drift")
    _, threshold_manifest = _load_frozen_threshold(config, root)
    if plan.get("threshold_identity_sha256") != threshold_manifest.get(
        "threshold_identity_sha256"
    ):
        raise RuntimeError("v22 fresh audit threshold identity drift")
    for artifact in plan["artifacts"].values():
        artifact_path = _resolve(str(artifact["path"]), root)
        if not artifact_path.is_file() or sha256_file(artifact_path) != artifact["sha256"]:
            raise RuntimeError("v22 fresh audit artifact drift")
    calibration_plan = _load_calibration_plan(config, root)
    calibration_rows = list(
        read_jsonl(
            _resolve(str(calibration_plan["artifacts"]["private_key"]["path"]), root)
        )
    )
    fresh_rows = list(
        read_jsonl(_resolve(str(plan["artifacts"]["private_key"]["path"]), root))
    )
    calibration_sources = {
        str(row["source_key"])
        for row in calibration_rows
        if row.get("source_key") is not None
    }
    calibration_facts = {
        str(row["fact_signature"])
        for row in calibration_rows
        if row.get("fact_signature") is not None
    }
    if calibration_sources & {str(row["source_key"]) for row in fresh_rows}:
        raise RuntimeError("v22 fresh audit overlaps calibration sources")
    if calibration_facts & {str(row["fact_signature"]) for row in fresh_rows}:
        raise RuntimeError("v22 fresh audit overlaps calibration facts")
    return plan


def evaluate_fresh_audit(
    config_path: str | Path,
    labels_path: str | Path,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_v22_config(Path(config_path).resolve())
    plan = _load_fresh_audit_plan(config, root)
    private = list(
        read_jsonl(_resolve(str(plan["artifacts"]["private_key"]["path"]), root))
    )
    expected_ids = {str(row["review_id"]) for row in private}
    labels_file = Path(labels_path).resolve()
    labels = _validate_label_rows(labels_file, expected_ids=expected_ids)
    counts = Counter(str(row["attack_usable"]) for row in labels.values())
    usable_rate = counts["yes"] / max(1, len(labels))
    uncertain_rate = counts["uncertain"] / max(1, len(labels))
    gates = {
        "minimum_attack_usable_rate": usable_rate
        >= float(config["fresh_audit"]["minimum_attack_usable_rate"]),
        "maximum_uncertain_rate": uncertain_rate
        <= float(config["fresh_audit"]["maximum_uncertain_rate"]),
    }
    report: dict[str, Any] = {
        "protocol": "pcv_v22_fresh_audit_evaluation_r1",
        "status": "passed" if all(gates.values()) else "failed_new_protocol_identity_required",
        "created_at": _utc_now(),
        "fresh_audit_identity_sha256": plan["fresh_audit_identity_sha256"],
        "labels_path": _relative(labels_file, root),
        "labels_sha256": sha256_file(labels_file),
        "row_count": len(labels),
        "attack_usable_counts": dict(counts),
        "attack_usable_rate": usable_rate,
        "uncertain_rate": uncertain_rate,
        "gates": gates,
        "attack_auc_accessed": False,
        "victim_responses_accessed": False,
    }
    report["evaluation_identity_sha256"] = _identity(
        report, "created_at", "evaluation_identity_sha256"
    )
    report_path = _resolve(str(config["output_root"]), root) / "fresh_audit" / "fresh_audit_evaluation.json"
    if report_path.exists():
        existing = read_json(report_path)
        report["created_at"] = existing.get("created_at")
        report["evaluation_identity_sha256"] = _identity(
            report, "created_at", "evaluation_identity_sha256"
        )
        if existing != report:
            raise RuntimeError(
                "v22 fresh audit evaluation is immutable; create a new protocol identity"
            )
        report = existing
    else:
        write_json(report, report_path)
    return {"status": report["status"], "gates": gates, "report": str(report_path)}


def _load_passed_fresh_audit(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve(str(config["output_root"]), root) / "fresh_audit" / "fresh_audit_evaluation.json"
    if not path.is_file():
        raise RuntimeError("v22 fresh audit evaluation missing")
    report = read_json(path)
    if report.get("status") != "passed" or report.get(
        "evaluation_identity_sha256"
    ) != _identity(report, "created_at", "evaluation_identity_sha256"):
        raise RuntimeError("v22 fresh audit is not passed")
    plan = _load_fresh_audit_plan(config, root)
    if report.get("fresh_audit_identity_sha256") != plan.get(
        "fresh_audit_identity_sha256"
    ):
        raise RuntimeError("v22 fresh audit evaluation plan drift")
    labels_path = _resolve(str(report.get("labels_path") or ""), root)
    if not labels_path.is_file() or sha256_file(labels_path) != report.get(
        "labels_sha256"
    ):
        raise RuntimeError("v22 fresh audit labels drift")
    return report


def freeze_splits(
    config_path: str | Path,
    *,
    resume: bool,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_v22_config(config_file)
    protocol_manifest = _load_protocol_manifest(config, root)
    threshold, threshold_manifest = _load_frozen_threshold(config, root)
    fresh_audit = _load_passed_fresh_audit(config, root)
    output = _resolve(str(config["output_root"]), root) / "splits"
    output.mkdir(parents=True, exist_ok=True)
    counts = dict(config["scope"]["split_counts"])
    manifests: dict[str, dict[str, Any]] = {}
    for dataset in sorted(config["source_pools"]):
        scan_manifest, whitelist = _load_final_scan(config, dataset, root)
        source_keys = [str(item) for item in whitelist["source_keys"]]
        ordered = sorted(
            source_keys,
            key=lambda source_key: (
                sha256_text(
                    "\0".join(
                        (str(config["selection_seed"]), dataset, "split", source_key)
                    )
                ),
                source_key,
            ),
        )
        member_end = int(counts["KB_Member"])
        nonmember_end = member_end + int(counts["True_Non_Member"])
        reserve_end = nonmember_end + int(counts["Reserve"])
        if reserve_end != len(ordered):
            raise RuntimeError("v22 split counts do not cover the selected source set")
        assignments = [
            {
                "dataset": dataset,
                "source_key": source_key,
                "group": (
                    "KB_Member"
                    if index < member_end
                    else "True_Non_Member"
                    if index < nonmember_end
                    else "Reserve"
                ),
            }
            for index, source_key in enumerate(ordered)
        ]
        split_path = output / f"{dataset}_split.jsonl"
        manifest_path = output / f"{dataset}_split_manifest.json"
        expected_manifest: dict[str, Any] = {
            "protocol": SPLIT_MANIFEST_PROTOCOL,
            "status": "frozen_pending_shadow",
            "created_at": _utc_now(),
            "dataset": dataset,
            "config_sha256": sha256_file(config_file),
            "threshold_identity_sha256": threshold_manifest[
                "threshold_identity_sha256"
            ],
            "fresh_audit_evaluation_identity_sha256": fresh_audit[
                "evaluation_identity_sha256"
            ],
            "dataset_scan_identity_sha256": scan_manifest[
                "dataset_scan_identity_sha256"
            ],
            "whitelist_sha256": scan_manifest["whitelist_sha256"],
            "split_counts": counts,
            "selection_seed": int(config["selection_seed"]),
            "split_path": _relative(split_path, root),
            "split_sha256": None,
            "membership_read_during_entity_selection": False,
            "kb_index_allowed_groups": ["KB_Member"],
        }
        if manifest_path.exists():
            if not resume:
                raise RuntimeError(f"v22 split already frozen: {dataset}")
            existing = read_json(manifest_path)
            expected_manifest["created_at"] = existing.get("created_at")
            expected_manifest["split_sha256"] = sha256_file(split_path)
            expected_manifest["split_identity_sha256"] = _identity(
                expected_manifest, "created_at", "split_identity_sha256"
            )
            if existing != expected_manifest:
                raise RuntimeError(f"v22 split identity drift: {dataset}")
            manifests[dataset] = existing
            continue
        write_jsonl_atomic(assignments, split_path)
        expected_manifest["split_sha256"] = sha256_file(split_path)
        expected_manifest["split_identity_sha256"] = _identity(
            expected_manifest, "created_at", "split_identity_sha256"
        )
        write_json(expected_manifest, manifest_path)
        manifests[dataset] = expected_manifest
    return {
        "status": "frozen_pending_shadow",
        "selected_threshold": threshold,
        "datasets": {
            dataset: manifest["split_identity_sha256"]
            for dataset, manifest in manifests.items()
        },
    }


def _load_frozen_split(
    config: Mapping[str, Any], dataset: str, root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    output = _resolve(str(config["output_root"]), root) / "splits"
    manifest_path = output / f"{dataset}_split_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"v22 split manifest missing: {dataset}")
    manifest = read_json(manifest_path)
    if (
        manifest.get("protocol") != SPLIT_MANIFEST_PROTOCOL
        or manifest.get("status") != "frozen_pending_shadow"
        or manifest.get("dataset") != dataset
        or manifest.get("split_identity_sha256")
        != _identity(manifest, "created_at", "split_identity_sha256")
    ):
        raise RuntimeError(f"v22 split manifest drift: {dataset}")
    protocol_manifest = _load_protocol_manifest(config, root)
    threshold, threshold_manifest = _load_frozen_threshold(config, root)
    fresh = _load_passed_fresh_audit(config, root)
    scan, whitelist = _load_final_scan(config, dataset, root)
    if (
        manifest.get("config_sha256") != protocol_manifest.get("config_sha256")
        or manifest.get("threshold_identity_sha256")
        != threshold_manifest.get("threshold_identity_sha256")
        or manifest.get("fresh_audit_evaluation_identity_sha256")
        != fresh.get("evaluation_identity_sha256")
        or manifest.get("dataset_scan_identity_sha256")
        != scan.get("dataset_scan_identity_sha256")
        or manifest.get("whitelist_sha256") != scan.get("whitelist_sha256")
    ):
        raise RuntimeError(f"v22 split upstream identity drift: {dataset}")
    split_path = _resolve(str(manifest.get("split_path") or ""), root)
    if not split_path.is_file() or sha256_file(split_path) != manifest.get(
        "split_sha256"
    ):
        raise RuntimeError(f"v22 split artifact drift: {dataset}")
    rows = list(read_jsonl(split_path))
    expected_keys = set(str(item) for item in whitelist["source_keys"])
    observed_keys = [str(row.get("source_key") or "") for row in rows]
    expected_counts = {
        str(group): int(count)
        for group, count in config["scope"]["split_counts"].items()
    }
    observed_counts = Counter(str(row.get("group") or "") for row in rows)
    if (
        len(rows) != len(expected_keys)
        or len(set(observed_keys)) != len(observed_keys)
        or set(observed_keys) != expected_keys
        or dict(observed_counts) != expected_counts
        or any(str(row.get("dataset") or "") != dataset for row in rows)
        or float(threshold) != float(threshold_manifest["selected_threshold"])
    ):
        raise RuntimeError(f"v22 split content drift: {dataset}")
    return manifest, rows


def _load_bound_shadow_artifact(
    *,
    root: Path,
    manifest_path_value: Any,
    manifest_hash: Any,
    kind: str,
    dataset: str,
    split_identity_sha256: str,
    reserve_keys: Sequence[str],
    retriever: str | None,
) -> dict[str, Any]:
    if kind not in SHADOW_ARTIFACT_PROTOCOLS or not _is_sha256(manifest_hash):
        raise RuntimeError(f"v22 shadow artifact identity invalid: {dataset}/{kind}")
    path = _resolve(str(manifest_path_value or ""), root)
    if not path.is_file() or sha256_file(path) != str(manifest_hash):
        raise RuntimeError(f"v22 shadow artifact manifest drift: {dataset}/{kind}")
    manifest = read_json(path)
    expected_keys = sorted(str(item) for item in reserve_keys)
    observed_keys = [str(item) for item in manifest.get("source_keys") or ()]
    if (
        manifest.get("protocol") != SHADOW_ARTIFACT_PROTOCOLS[kind]
        or manifest.get("status") not in {"frozen", "passed"}
        or manifest.get("manifest_identity_sha256")
        != _identity(manifest, "created_at", "manifest_identity_sha256")
        or manifest.get("dataset") != dataset
        or manifest.get("split_identity_sha256") != split_identity_sha256
        or observed_keys != expected_keys
        or manifest.get("source_keys_sha256") != sha256_obj(observed_keys)
        or int(manifest.get("source_count", -1)) != len(expected_keys)
        or manifest.get("reserve_source_set_sha256") != sha256_obj(expected_keys)
    ):
        raise RuntimeError(f"v22 shadow artifact binding drift: {dataset}/{kind}")
    if kind == "index":
        if (
            manifest.get("retriever") != retriever
            or int(manifest.get("forbidden_group_overlap", -1)) != 0
        ):
            raise RuntimeError(f"v22 shadow index scope drift: {dataset}/{retriever}")
    elif manifest.get("retriever_scope") != "shared":
        raise RuntimeError(f"v22 shadow shared artifact scope drift: {dataset}/{kind}")
    payload_path = _resolve(str(manifest.get("payload_path") or ""), root)
    payload_hash = manifest.get("payload_sha256")
    if (
        not _is_sha256(payload_hash)
        or not payload_path.is_file()
        or sha256_file(payload_path) != payload_hash
    ):
        raise RuntimeError(f"v22 shadow artifact payload drift: {dataset}/{kind}")
    return manifest


def _load_old_shadow_baseline(
    *,
    root: Path,
    payload: Mapping[str, Any],
    dataset: str,
    split_identity_sha256: str,
    reserve_keys: Sequence[str],
    retrievers: Sequence[str],
) -> tuple[dict[str, float], dict[str, Any]]:
    path = _resolve(str(payload.get("old_semantic_purity_manifest_path") or ""), root)
    expected_hash = payload.get("old_semantic_purity_manifest_hash")
    if (
        not _is_sha256(expected_hash)
        or not path.is_file()
        or sha256_file(path) != expected_hash
    ):
        raise RuntimeError(f"v22 old shadow baseline artifact drift: {dataset}")
    manifest = read_json(path)
    expected_keys = sorted(str(item) for item in reserve_keys)
    observed_keys = [str(item) for item in manifest.get("source_keys") or ()]
    if (
        manifest.get("protocol") != OLD_SHADOW_BASELINE_PROTOCOL
        or manifest.get("status") != "passed"
        or manifest.get("manifest_identity_sha256")
        != _identity(manifest, "created_at", "manifest_identity_sha256")
        or manifest.get("dataset") != dataset
        or manifest.get("split_identity_sha256") != split_identity_sha256
        or observed_keys != expected_keys
        or manifest.get("source_keys_sha256") != sha256_obj(observed_keys)
        or int(manifest.get("source_count", -1)) != len(expected_keys)
        or manifest.get("reserve_source_set_sha256") != sha256_obj(expected_keys)
    ):
        raise RuntimeError(f"v22 old shadow baseline binding drift: {dataset}")
    evidence = manifest.get("retrievers")
    if not isinstance(evidence, Mapping) or set(evidence) != set(retrievers):
        raise RuntimeError(f"v22 old shadow baseline retriever scope drift: {dataset}")
    recalls: dict[str, float] = {}
    for retriever in retrievers:
        metrics = evidence.get(retriever)
        if not isinstance(metrics, Mapping):
            raise RuntimeError(f"v22 old shadow baseline metrics missing: {dataset}/{retriever}")
        recall = float(metrics.get("recall_at_5", -1.0))
        if not 0.0 <= recall <= 1.0:
            raise RuntimeError(f"v22 old shadow baseline metric invalid: {dataset}/{retriever}")
        for kind, hash_key in (
            ("index", "index_manifest_hash"),
            ("query", "query_hash"),
            ("benchmark", "benchmark_hash"),
        ):
            _load_bound_shadow_artifact(
                root=root,
                manifest_path_value=metrics.get(f"{kind}_manifest_path"),
                manifest_hash=metrics.get(hash_key),
                kind=kind,
                dataset=dataset,
                split_identity_sha256=split_identity_sha256,
                reserve_keys=expected_keys,
                retriever=retriever if kind == "index" else None,
            )
        recalls[retriever] = recall
    return recalls, manifest


def evaluate_shadow_gate(
    config_path: str | Path,
    shadow_report_path: str | Path,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    """Validate externally produced offline Retriever reports at aggregate level."""

    root = Path(project_root).resolve()
    config = load_v22_config(Path(config_path).resolve())
    protocol_manifest = _load_protocol_manifest(config, root)
    report_path = Path(shadow_report_path).resolve()
    report = read_json(report_path)
    if report.get("protocol") != "pcv_v22_reserve_shadow_report_r1":
        raise RuntimeError("v22 shadow report protocol drift")
    if report.get("reserve_only") is not True:
        raise RuntimeError("v22 shadow report must be Reserve-only")
    if report.get("per_source_selection_performed") is not False:
        raise RuntimeError("v22 shadow report used forbidden per-source selection")
    datasets = report.get("datasets")
    if not isinstance(datasets, Mapping):
        raise RuntimeError("v22 shadow report datasets missing")
    if set(str(item) for item in datasets) != set(config["source_pools"]):
        raise RuntimeError("v22 shadow report dataset scope drift")
    gate_config = config["shadow_validation"]
    results: dict[str, Any] = {}
    all_passed = True
    for dataset in sorted(config["source_pools"]):
        payload = datasets.get(dataset)
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"v22 shadow dataset missing: {dataset}")
        split_manifest, split_rows = _load_frozen_split(config, dataset, root)
        if payload.get("split_identity_sha256") != split_manifest.get(
            "split_identity_sha256"
        ):
            raise RuntimeError(f"v22 shadow split identity drift: {dataset}")
        reserve_keys = sorted(
            str(row["source_key"])
            for row in split_rows
            if str(row["group"]) == "Reserve"
        )
        reserve_hash = sha256_obj(reserve_keys)
        if (
            int(payload.get("reserve_source_count", -1)) != len(reserve_keys)
            or payload.get("reserve_source_set_sha256") != reserve_hash
        ):
            raise RuntimeError(f"v22 shadow Reserve identity drift: {dataset}")
        retrievers = [str(item) for item in gate_config["retrievers"]]
        old_recalls, old_manifest = _load_old_shadow_baseline(
            root=root,
            payload=payload,
            dataset=dataset,
            split_identity_sha256=str(split_manifest["split_identity_sha256"]),
            reserve_keys=reserve_keys,
            retrievers=retrievers,
        )
        retriever_results: dict[str, Any] = {}
        dataset_passed = True
        common_query_hash: str | None = None
        common_benchmark_hash: str | None = None
        for retriever in gate_config["retrievers"]:
            metrics = payload.get(retriever)
            if not isinstance(metrics, Mapping):
                raise RuntimeError(f"v22 shadow retriever missing: {dataset}/{retriever}")
            for identity_field in ("index_manifest_hash", "query_hash", "benchmark_hash"):
                if not _is_sha256(metrics.get(identity_field)):
                    raise RuntimeError(
                        f"v22 shadow identity missing: {dataset}/{retriever}/{identity_field}"
                    )
            for kind, hash_key in (
                ("index", "index_manifest_hash"),
                ("query", "query_hash"),
                ("benchmark", "benchmark_hash"),
            ):
                _load_bound_shadow_artifact(
                    root=root,
                    manifest_path_value=metrics.get(f"{kind}_manifest_path"),
                    manifest_hash=metrics.get(hash_key),
                    kind=kind,
                    dataset=dataset,
                    split_identity_sha256=str(
                        split_manifest["split_identity_sha256"]
                    ),
                    reserve_keys=reserve_keys,
                    retriever=str(retriever) if kind == "index" else None,
                )
            if int(metrics.get("evaluated_source_count", -1)) != len(reserve_keys):
                raise RuntimeError(
                    f"v22 shadow source-count drift: {dataset}/{retriever}"
                )
            query_hash = str(metrics["query_hash"])
            benchmark_hash = str(metrics["benchmark_hash"])
            common_query_hash = common_query_hash or query_hash
            common_benchmark_hash = common_benchmark_hash or benchmark_hash
            if query_hash != common_query_hash or benchmark_hash != common_benchmark_hash:
                raise RuntimeError(
                    f"v22 shadow cross-retriever benchmark drift: {dataset}"
                )
            recall5 = float(metrics.get("recall_at_5", -1.0))
            recall10 = float(metrics.get("recall_at_10", -1.0))
            zero_hit = float(metrics.get("zero_hit_rate", 2.0))
            if not all(0.0 <= value <= 1.0 for value in (recall5, recall10, zero_hit)):
                raise RuntimeError(
                    f"v22 shadow metric out of range: {dataset}/{retriever}"
                )
            gates = {
                "recall_at_5": recall5
                >= float(gate_config["recall_at_5_minimum"]),
                "recall_at_10": recall10
                >= float(gate_config["recall_at_10_minimum"]),
                "zero_hit_rate": zero_hit
                <= float(gate_config["zero_hit_rate_maximum"]),
                "semantic_purity_noninferiority": recall5
                >= old_recalls[str(retriever)]
                - float(gate_config["recall_at_5_noninferiority_margin"]),
            }
            passed = all(gates.values())
            dataset_passed = dataset_passed and passed
            retriever_results[str(retriever)] = {
                "metrics": dict(metrics),
                "gates": gates,
                "passed": passed,
            }
        results[dataset] = {
            "split_identity_sha256": split_manifest["split_identity_sha256"],
            "reserve_source_count": len(reserve_keys),
            "reserve_source_set_sha256": reserve_hash,
            "old_semantic_purity_manifest_hash": payload[
                "old_semantic_purity_manifest_hash"
            ],
            "old_semantic_purity_manifest_identity_sha256": old_manifest[
                "manifest_identity_sha256"
            ],
            "old_semantic_purity_recall_at_5": old_recalls,
            "retrievers": retriever_results,
            "passed": dataset_passed,
        }
        all_passed = all_passed and dataset_passed
    gate: dict[str, Any] = {
        "protocol": SHADOW_GATE_PROTOCOL,
        "status": "passed" if all_passed else "failed_global_query_revision_required",
        "created_at": _utc_now(),
        "input_report_path": _relative(report_path, root),
        "input_report_sha256": sha256_file(report_path),
        "protocol_identity_sha256": protocol_manifest["protocol_identity_sha256"],
        "reserve_only": True,
        "per_source_selection_performed": False,
        "datasets": results,
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs_recorded_not_executed_by_gate": True,
    }
    gate["shadow_gate_identity_sha256"] = _identity(
        gate, "created_at", "shadow_gate_identity_sha256"
    )
    output = _resolve(str(config["output_root"]), root) / "shadow"
    output.mkdir(parents=True, exist_ok=True)
    output_path = output / "shadow_gate.json"
    if output_path.exists():
        existing = read_json(output_path)
        gate["created_at"] = existing.get("created_at")
        gate["shadow_gate_identity_sha256"] = _identity(
            gate, "created_at", "shadow_gate_identity_sha256"
        )
        if existing != gate:
            raise RuntimeError(
                "v22 shadow gate is immutable; create a new query/protocol identity"
            )
        gate = existing
    else:
        write_json(gate, output_path)
    return {"status": gate["status"], "datasets": results, "gate": str(output_path)}


def _load_passed_shadow_gate(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve(str(config["output_root"]), root) / "shadow" / "shadow_gate.json"
    if not path.is_file():
        raise RuntimeError("v22 shadow gate missing")
    gate = read_json(path)
    if gate.get("status") != "passed" or gate.get(
        "shadow_gate_identity_sha256"
    ) != _identity(gate, "created_at", "shadow_gate_identity_sha256"):
        raise RuntimeError("v22 shadow gate is not passed")
    protocol_manifest = _load_protocol_manifest(config, root)
    if (
        gate.get("protocol") != SHADOW_GATE_PROTOCOL
        or gate.get("protocol_identity_sha256")
        != protocol_manifest.get("protocol_identity_sha256")
        or gate.get("reserve_only") is not True
        or gate.get("per_source_selection_performed") is not False
    ):
        raise RuntimeError("v22 shadow gate protocol identity drift")
    report_path = _resolve(str(gate.get("input_report_path") or ""), root)
    if not report_path.is_file() or sha256_file(report_path) != gate.get(
        "input_report_sha256"
    ):
        raise RuntimeError("v22 shadow input report drift")
    report = read_json(report_path)
    report_datasets = report.get("datasets")
    if (
        report.get("protocol") != "pcv_v22_reserve_shadow_report_r1"
        or report.get("reserve_only") is not True
        or report.get("per_source_selection_performed") is not False
        or not isinstance(report_datasets, Mapping)
        or set(report_datasets) != set(config["source_pools"])
    ):
        raise RuntimeError("v22 shadow input report protocol drift")
    retrievers = [str(item) for item in config["shadow_validation"]["retrievers"]]
    for dataset in sorted(config["source_pools"]):
        split, rows = _load_frozen_split(config, dataset, root)
        payload = (gate.get("datasets") or {}).get(dataset)
        report_payload = report_datasets.get(dataset)
        reserve_keys = sorted(
            str(row["source_key"])
            for row in rows
            if str(row["group"]) == "Reserve"
        )
        if (
            not isinstance(payload, Mapping)
            or payload.get("passed") is not True
            or payload.get("split_identity_sha256")
            != split.get("split_identity_sha256")
            or int(payload.get("reserve_source_count", -1)) != len(reserve_keys)
            or payload.get("reserve_source_set_sha256") != sha256_obj(reserve_keys)
            or not isinstance(report_payload, Mapping)
            or report_payload.get("split_identity_sha256")
            != split.get("split_identity_sha256")
            or int(report_payload.get("reserve_source_count", -1))
            != len(reserve_keys)
            or report_payload.get("reserve_source_set_sha256")
            != sha256_obj(reserve_keys)
        ):
            raise RuntimeError(f"v22 shadow gate dataset identity drift: {dataset}")
        old_recalls, old_manifest = _load_old_shadow_baseline(
            root=root,
            payload=report_payload,
            dataset=dataset,
            split_identity_sha256=str(split["split_identity_sha256"]),
            reserve_keys=reserve_keys,
            retrievers=retrievers,
        )
        if (
            payload.get("old_semantic_purity_manifest_hash")
            != report_payload.get("old_semantic_purity_manifest_hash")
            or payload.get("old_semantic_purity_manifest_identity_sha256")
            != old_manifest.get("manifest_identity_sha256")
            or payload.get("old_semantic_purity_recall_at_5") != old_recalls
        ):
            raise RuntimeError(f"v22 shadow old baseline evidence drift: {dataset}")
        for retriever in retrievers:
            metrics = report_payload.get(retriever)
            frozen_metrics = (
                (payload.get("retrievers") or {}).get(retriever) or {}
            ).get("metrics")
            if not isinstance(metrics, Mapping) or dict(metrics) != frozen_metrics:
                raise RuntimeError(
                    f"v22 shadow retriever evidence drift: {dataset}/{retriever}"
                )
            for kind, hash_key in (
                ("index", "index_manifest_hash"),
                ("query", "query_hash"),
                ("benchmark", "benchmark_hash"),
            ):
                _load_bound_shadow_artifact(
                    root=root,
                    manifest_path_value=metrics.get(f"{kind}_manifest_path"),
                    manifest_hash=metrics.get(hash_key),
                    kind=kind,
                    dataset=dataset,
                    split_identity_sha256=str(split["split_identity_sha256"]),
                    reserve_keys=reserve_keys,
                    retriever=retriever if kind == "index" else None,
                )
    return gate


def finalize_release(
    config_path: str | Path,
    *,
    resume: bool,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_v22_config(config_file)
    protocol_manifest = _load_protocol_manifest(config, root)
    threshold, threshold_manifest = _load_frozen_threshold(config, root)
    fresh = _load_passed_fresh_audit(config, root)
    shadow = _load_passed_shadow_gate(config, root)
    datasets: dict[str, Any] = {}
    for dataset in sorted(config["source_pools"]):
        scan, _ = _load_final_scan(config, dataset, root)
        split, split_rows = _load_frozen_split(config, dataset, root)
        if int(scan.get("source_count", -1)) != int(
            config["scope"]["target_formal_sources"]
        ):
            raise RuntimeError(f"v22 release source count drift: {dataset}")
        shadow_dataset = (shadow.get("datasets") or {}).get(dataset)
        if (
            not isinstance(shadow_dataset, Mapping)
            or shadow_dataset.get("passed") is not True
            or shadow_dataset.get("split_identity_sha256")
            != split.get("split_identity_sha256")
        ):
            raise RuntimeError(f"v22 release shadow/split drift: {dataset}")
        split_counts = Counter(str(row["group"]) for row in split_rows)
        datasets[dataset] = {
            "dataset_scan_identity_sha256": scan["dataset_scan_identity_sha256"],
            "whitelist_sha256": scan["whitelist_sha256"],
            "selected_pairs_sha256": scan["selected_pairs_sha256"],
            "structured_pairs_sha256": scan["structured_pairs_sha256"],
            "split_identity_sha256": split["split_identity_sha256"],
            "source_count": scan["source_count"],
            "pair_count": scan["pair_count"],
            "split_counts": dict(split_counts),
        }
    release: dict[str, Any] = {
        "protocol": RELEASE_PROTOCOL,
        "status": "passed_ready_to_rebind_queries_retrievers_and_victim",
        "created_at": _utc_now(),
        "protocol_version": PROTOCOL_VERSION,
        "method_version": METHOD_VERSION,
        "config_path": _relative(config_file, root),
        "config_sha256": sha256_file(config_file),
        "protocol_identity_sha256": protocol_manifest[
            "protocol_identity_sha256"
        ],
        "single_router_model": {
            "model_id": config["routing"]["single_model_id"],
            "revision": config["routing"]["single_model_revision"],
            "model_lock_sha256": config["routing"]["model_lock_sha256"],
        },
        "selected_threshold": threshold,
        "threshold_identity_sha256": threshold_manifest[
            "threshold_identity_sha256"
        ],
        "fresh_audit_identity_sha256": fresh["evaluation_identity_sha256"],
        "shadow_gate_identity_sha256": shadow["shadow_gate_identity_sha256"],
        "datasets": datasets,
        "ablation_selection_strategies": [
            "random_eligible_entities",
            "old_semantic_purity_selection",
            "attackability_first_selection",
            "without_corpus_specificity",
            "without_counterfactual_naturalness",
            "without_verification_discriminativeness",
        ],
        "query_generator": "unchanged_luna_rebind_required",
        "victim_generator": "unchanged_gemma_rebind_required",
        "retriever_matrix": "unchanged_rebind_required",
        "formal_queries_generated": False,
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
    }
    release["release_identity_sha256"] = _identity(
        release, "created_at", "release_identity_sha256"
    )
    output = _resolve(str(config["output_root"]), root) / "release"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "release_manifest.json"
    if path.exists():
        if not resume:
            raise RuntimeError("v22 release already finalized")
        existing = read_json(path)
        release["created_at"] = existing.get("created_at")
        release["release_identity_sha256"] = _identity(
            release, "created_at", "release_identity_sha256"
        )
        if existing != release:
            raise RuntimeError("v22 release identity drift")
    else:
        write_json(release, path)
    return {
        "status": release["status"],
        "release": str(path),
        "release_identity_sha256": release["release_identity_sha256"],
    }


def v22_status(
    config_path: str | Path, *, project_root: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_v22_config(Path(config_path).resolve())
    output = _resolve(str(config["output_root"]), root)
    status: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "method_version": METHOD_VERSION,
        "single_router_model": {
            "model_id": config["routing"]["single_model_id"],
            "revision": config["routing"]["single_model_revision"],
        },
        "protocol_frozen": (output / "protocol_manifest.json").is_file(),
        "source_pools": {},
        "pilot": {},
        "formal_scan": {},
        "calibration_threshold_frozen": (
            output / "calibration" / "threshold_manifest.json"
        ).is_file(),
        "fresh_audit_passed": False,
        "shadow_gate_passed": False,
        "release_finalized": (output / "release" / "release_manifest.json").is_file(),
    }
    for dataset in sorted(config["source_pools"]):
        source_paths = _source_pool_paths(config, dataset, root)
        status["source_pools"][dataset] = (
            read_json(source_paths["checkpoint"]).get("status")
            if source_paths["checkpoint"].is_file()
            else "not_started"
        )
        for stage in ("pilot", "formal_scan"):
            scan_paths = _scan_paths(config, dataset, stage, root)
            status[stage][dataset] = (
                read_json(scan_paths["checkpoint"]).get("status")
                if scan_paths["checkpoint"].is_file()
                else "not_started"
            )
    fresh_path = output / "fresh_audit" / "fresh_audit_evaluation.json"
    if fresh_path.is_file():
        status["fresh_audit_passed"] = read_json(fresh_path).get("status") == "passed"
    shadow_path = output / "shadow" / "shadow_gate.json"
    if shadow_path.is_file():
        status["shadow_gate_passed"] = read_json(shadow_path).get("status") == "passed"
    return status
