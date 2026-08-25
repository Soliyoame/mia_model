"""Frozen-r2 preparation runner for the v23 blind fresh audit.

The freeze and status paths read only manifests and reservation metadata.  The
dataset and packet paths require an explicit, self-hashed run authorization;
they are deliberately not invoked by the preparation freeze workflow.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..attack.restoration_first_v23 import (
    canonical_json,
    canonical_sha256,
    normalized_text_sha256,
    text_sha256,
    validate_selector_source_input,
)
from ..attack.restoration_first_v23_fact_layer import (
    FACT_LAYER_SPECIFICATION_VERSION,
    extract_fact_candidates,
    validate_fact_row,
)
from ..attack.restoration_first_v23_fact_layer_selection_r2 import (
    SELECTION_R2_SPECIFICATION_VERSION,
    select_pairs_from_r1_facts,
)
from ..attack.semantic_entity_resolver import (
    ALL_SEMANTIC_SCHEMA,
    SemanticPredictionBackend,
    _load_backend,
)
from ..utils.hash import sha256_file
from ..utils.io import load_yaml


CONFIG_PATH = Path("configs/restoration_first_v23_fresh_audit_preparation_r1.yaml")
FREEZE_MANIFEST_PATH = Path(
    "configs/restoration_first_v23_fresh_audit_preparation_r1_fix2.freeze.json"
)
RUNNER_REVISION = "r1-fix2"
DESIGN_CONFIG_PATH = Path("configs/restoration_first_v23.yaml")
MODEL_LOCK_PATH = Path("configs/semantic_entity_models_v6_3.lock.yaml")
DATASETS = ("edgar", "enron", "pubmed")
R2_MANIFEST_KEYS = ("fact_manifest", "selection_manifest", "pilot_manifest")
RUN_AUTH_KIND = "v23_fresh_audit_preparation_run_authorization"
RUN_AUTH_ALLOWED_STAGES = {"dataset_preparation", "packet_preparation"}
PACKET_VISIBLE_FIELDS = {
    "kind",
    "opaque_audit_source_id",
    "packet_order_key",
    "pair_id",
    "pair_order",
    "complete_source_text",
    "supporting_sentence",
    "true_claim",
    "counterfactual_claim",
    "original_entity",
    "counterfactual_entity",
    "effective_type",
}
PACKET_HIDDEN_FIELDS = {
    "dataset",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "membership",
    "group",
    "rank_features",
    "victim_response",
    "llm_only_response",
    "retriever_output",
    "attack_score",
    "auc",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _resolve(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"path_outside_project:{path}") from error
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"json_object_required:{path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise RuntimeError(f"jsonl_partial:{path}")
    rows: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"json_object_required:{path}")
        rows.append(value)
    return rows


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        temporary.unlink()
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise RuntimeError(f"artifact_already_exists:{path}")
    _atomic_write(path, (canonical_json(dict(value)) + "\n").encode("utf-8"))


def _write_or_validate_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    expected = "".join(canonical_json(dict(row)) + "\n" for row in rows).encode("utf-8")
    if path.exists():
        if path.read_bytes() != expected:
            raise RuntimeError(f"artifact_identity_drift:{path}")
        return
    _atomic_write(path, expected)


def load_preparation_config(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_yaml(_resolve(CONFIG_PATH, root))
    if not isinstance(config, Mapping):
        raise RuntimeError("fresh_audit_preparation_config_invalid")
    expected = {
        "protocol_version": "pcv-mia-v23",
        "method_version": "pcv-restoration-first-v23-fresh-audit-preparation",
        "specification_version": "pcv-restoration-first-v23-fresh-audit-preparation-r1",
        "selection_specification_version": SELECTION_R2_SPECIFICATION_VERSION,
        "fact_specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "external_calls_performed": 0,
    }
    if any(config.get(key) != value for key, value in expected.items()):
        raise RuntimeError("fresh_audit_preparation_config_identity_drift")
    if tuple(config.get("reserve_group", {}).get("dataset_order", ())) != DATASETS:
        raise RuntimeError("fresh_audit_dataset_order_drift")
    forbidden = config.get("forbidden_inputs")
    if set(forbidden or ()) != {
        "membership",
        "victim_response",
        "llm_only_response",
        "retriever_output",
        "auc",
        "formal_labels",
    }:
        raise RuntimeError("fresh_audit_forbidden_input_contract_drift")
    return dict(config)


def _config_sha256(root: Path) -> str:
    return sha256_file(_resolve(CONFIG_PATH, root))


def _implementation_files() -> tuple[Path, ...]:
    return (
        Path("src/attack/restoration_first_v23.py"),
        Path("src/attack/restoration_first_v23_fact_layer.py"),
        Path("src/attack/restoration_first_v23_fact_layer_selection_r2.py"),
        Path("src/prepare/restoration_first_v23_fresh_audit_preparation.py"),
        Path("scripts/43_prepare_v23_fresh_audit.py"),
    )


def _file_hashes(root: Path, paths: Sequence[Path]) -> dict[str, str]:
    output: dict[str, str] = {}
    for path in paths:
        resolved = _resolve(path, root)
        if not resolved.is_file():
            raise RuntimeError(f"fresh_audit_implementation_missing:{path}")
        output[path.as_posix()] = sha256_file(resolved)
    return output


def _bound_hash(root: Path, path_value: str, expected: str | None = None) -> str:
    path = _resolve(path_value, root)
    if not path.is_file():
        raise RuntimeError(f"fresh_audit_bound_file_missing:{path_value}")
    actual = sha256_file(path)
    if expected is not None and actual != expected:
        raise RuntimeError(f"fresh_audit_bound_file_drift:{path_value}")
    return actual


def _validate_r2_manifest(root: Path, dataset: str, binding: Mapping[str, Any]) -> dict[str, Any]:
    manifests: dict[str, dict[str, Any]] = {}
    for key in R2_MANIFEST_KEYS:
        path_key = f"{key}_path"
        expected_hash = str(binding[f"{key}_sha256"])
        path = _resolve(str(binding[path_key]), root)
        _bound_hash(root, str(binding[path_key]), expected_hash)
        manifest = _read_json(path)
        if manifest.get("status") != "passed" or manifest.get("dataset") != dataset:
            raise RuntimeError(f"fresh_audit_r2_manifest_not_passed:{dataset}:{key}")
        if manifest.get("external_calls_performed") != 0:
            raise RuntimeError(f"fresh_audit_r2_manifest_external_call:{dataset}:{key}")
        manifests[key] = manifest
    if manifests["selection_manifest"].get("selection_attempt_id") != binding["selection_attempt_id"]:
        raise RuntimeError(f"fresh_audit_selection_attempt_drift:{dataset}")
    if manifests["selection_manifest"].get("source_fact_attempt_id") != binding["fact_attempt_id"]:
        raise RuntimeError(f"fresh_audit_fact_attempt_drift:{dataset}")
    if manifests["pilot_manifest"].get("selection_manifest_sha256") != binding["selection_manifest_sha256"]:
        raise RuntimeError(f"fresh_audit_pilot_selection_hash_drift:{dataset}")
    return manifests


def _validate_reserve_metadata(root: Path, config: Mapping[str, Any], dataset: str) -> dict[str, Any]:
    group = config["reserve_group"]
    revision = str(config["execution_reservation_revision"])
    prior_path = _resolve(str(group["prior_snapshot_path"]), root)
    completion_path = _resolve(str(group["group_completion_path"]), root)
    prior = _read_json(prior_path)
    completion = _read_json(completion_path)
    if prior.get("kind") != "v23_revision_reservation_prior_snapshot" or prior.get("protocol_revision_id") != revision:
        raise RuntimeError("fresh_audit_prior_snapshot_drift")
    if completion.get("kind") != "v23_revision_reservation_group_complete" or completion.get("protocol_revision_id") != revision:
        raise RuntimeError("fresh_audit_group_completion_drift")
    reserve_dir = str(group["reserve_plan_directory"])
    plan_path = _resolve(Path(reserve_dir) / f"{dataset}.json", root)
    snapshot_path = _resolve(str(config["datasets"][dataset]["reserve_snapshot_path"]), root)
    plan = _read_json(plan_path)
    snapshot = _read_json(snapshot_path)
    expected_count = int(group["reserve_source_count_per_dataset"])
    rows = plan.get("ordered_source_identity_objects")
    ordered = snapshot.get("ordered_sources")
    if (
        plan.get("kind") != "v23_reservation_plan"
        or plan.get("role") != "fresh_audit_reserve"
        or plan.get("dataset") != dataset
        or not isinstance(rows, list)
        or len(rows) != expected_count
        or snapshot.get("kind") != "v23_fresh_audit_reserve_snapshot"
        or snapshot.get("dataset") != dataset
        or not isinstance(ordered, list)
        or len(ordered) != expected_count
    ):
        raise RuntimeError(f"fresh_audit_reserve_metadata_drift:{dataset}")
    if any(not isinstance(item, Mapping) for item in rows) or any(
        not isinstance(item, Mapping) for item in ordered
    ):
        raise RuntimeError(f"fresh_audit_reserve_identity_schema_drift:{dataset}")
    plan_keys = [str(item["source_key"]) for item in rows]
    snapshot_keys = [str(item["source_key"]) for item in ordered]
    if len(set(plan_keys)) != expected_count or plan_keys != snapshot_keys:
        raise RuntimeError(f"fresh_audit_reserve_order_drift:{dataset}")
    for item, snapshot_item in zip(rows, ordered):
        if (
            not _is_sha256(item.get("source_hash"))
            or not _is_sha256(item.get("normalized_text_hash"))
            or not isinstance(snapshot_item.get("source_order_index"), int)
            or isinstance(snapshot_item.get("source_order_index"), bool)
        ):
            raise RuntimeError(f"fresh_audit_reserve_identity_schema_drift:{dataset}")
    return {
        "plan_path": plan_path,
        "plan_sha256": sha256_file(plan_path),
        "snapshot_path": snapshot_path,
        "snapshot_sha256": sha256_file(snapshot_path),
        "source_count": expected_count,
        "source_keys": tuple(plan_keys),
        "prior_snapshot_sha256": sha256_file(prior_path),
        "group_completion_sha256": sha256_file(completion_path),
    }


def build_preparation_freeze_manifest(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_preparation_config(root)
    design_path = _resolve(str(config["design_config_path"]), root)
    design_manifest_path = _resolve(str(config["design_manifest_path"]), root)
    selection_config_path = _resolve(str(config["selection_config_path"]), root)
    model_lock_path = _resolve(str(config["model_lock_path"]), root)
    for path in (design_path, design_manifest_path, selection_config_path, model_lock_path):
        if not path.is_file():
            raise RuntimeError(f"fresh_audit_freeze_bound_file_missing:{path}")
    datasets: dict[str, Any] = {}
    reserve_group_metadata: dict[str, Any] | None = None
    for dataset in DATASETS:
        binding = config["datasets"][dataset]
        manifests = _validate_r2_manifest(root, dataset, binding)
        reserve = _validate_reserve_metadata(root, config, dataset)
        if reserve_group_metadata is None:
            reserve_group_metadata = reserve
        elif (
            reserve["prior_snapshot_sha256"] != reserve_group_metadata["prior_snapshot_sha256"]
            or reserve["group_completion_sha256"] != reserve_group_metadata["group_completion_sha256"]
        ):
            raise RuntimeError("fresh_audit_reserve_group_metadata_drift")
        datasets[dataset] = {
            "fact_attempt_id": binding["fact_attempt_id"],
            "fact_manifest_sha256": binding["fact_manifest_sha256"],
            "selection_attempt_id": binding["selection_attempt_id"],
            "selection_manifest_sha256": binding["selection_manifest_sha256"],
            "pilot_manifest_sha256": binding["pilot_manifest_sha256"],
            "fact_manifest_file_sha256": sha256_file(_resolve(str(binding["fact_manifest_path"]), root)),
            "selection_manifest_file_sha256": sha256_file(_resolve(str(binding["selection_manifest_path"]), root)),
            "pilot_manifest_file_sha256": sha256_file(_resolve(str(binding["pilot_manifest_path"]), root)),
            "reserve_plan_sha256": reserve["plan_sha256"],
            "reserve_snapshot_sha256": reserve["snapshot_sha256"],
            "reserve_source_count": reserve["source_count"],
            "selection_status": manifests["selection_manifest"]["status"],
            "pilot_status": manifests["pilot_manifest"]["status"],
        }
    payload = {
        "kind": "v23_fresh_audit_preparation_freeze_manifest",
        "runner_revision": RUNNER_REVISION,
        "specification_version": config["specification_version"],
        "selection_specification_version": config["selection_specification_version"],
        "fact_specification_version": config["fact_specification_version"],
        "execution_reservation_revision": config["execution_reservation_revision"],
        "config_sha256": _config_sha256(root),
        "design_config_sha256": sha256_file(design_path),
        "design_manifest_sha256": sha256_file(design_manifest_path),
        "selection_config_sha256": sha256_file(selection_config_path),
        "model_lock_sha256": sha256_file(model_lock_path),
        "implementation_file_sha256": _file_hashes(root, _implementation_files()),
        "reserve_group": {
            "prior_snapshot_sha256": reserve_group_metadata["prior_snapshot_sha256"],
            "group_completion_sha256": reserve_group_metadata["group_completion_sha256"],
            "dataset_order": list(DATASETS),
            "reserve_source_count_per_dataset": int(config["reserve_group"]["reserve_source_count_per_dataset"]),
            "selected_source_count_per_dataset": int(config["reserve_group"]["selected_source_count_per_dataset"]),
            "pairs_per_source": int(config["reserve_group"]["pairs_per_source"]),
            "total_packet_rows": int(config["reserve_group"]["total_packet_rows"]),
        },
        "datasets": datasets,
        "external_calls_performed": 0,
        "source_content_read_by_freeze": False,
        "created_at": _utc_now(),
    }
    payload["freeze_identity_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "created_at"}
    )
    return payload


def freeze_preparation(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    manifest = build_preparation_freeze_manifest(root)
    path = _resolve(FREEZE_MANIFEST_PATH, root)
    if path.exists():
        actual = _read_json(path)
        if {key: value for key, value in actual.items() if key != "created_at"} != {
            key: value for key, value in manifest.items() if key != "created_at"
        }:
            raise RuntimeError("fresh_audit_freeze_manifest_drift")
    else:
        _write_new_json(path, manifest)
    return {
        "status": "passed",
        "kind": manifest["kind"],
        "freeze_identity_sha256": manifest["freeze_identity_sha256"],
        "freeze_manifest_path": path.relative_to(root).as_posix(),
        "source_content_read": False,
        "external_calls_performed": 0,
    }


def validate_preparation_freeze(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = _resolve(FREEZE_MANIFEST_PATH, root)
    if not path.is_file():
        raise RuntimeError("fresh_audit_freeze_manifest_missing")
    expected = build_preparation_freeze_manifest(root)
    actual = _read_json(path)
    if {key: value for key, value in actual.items() if key != "created_at"} != {
        key: value for key, value in expected.items() if key != "created_at"
    }:
        raise RuntimeError("fresh_audit_freeze_manifest_drift")
    return {
        "status": "passed",
        "freeze_identity_sha256": actual["freeze_identity_sha256"],
        "freeze_manifest_sha256": sha256_file(path),
        "datasets": list(DATASETS),
        "source_content_read": False,
        "external_calls_performed": 0,
    }


def _audit_root(root: Path, identity: str) -> Path:
    return _resolve(Path("artifacts/v23/audit") / identity, root)


def _reserve_rows(root: Path, config: Mapping[str, Any], dataset: str) -> list[dict[str, Any]]:
    reserve = _validate_reserve_metadata(root, config, dataset)
    plan = _read_json(reserve["plan_path"])
    snapshot = _read_json(reserve["snapshot_path"])
    snapshot_by_key = {item["source_key"]: item for item in snapshot["ordered_sources"]}
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(plan["ordered_source_identity_objects"]):
        source_key = str(item["source_key"])
        source_order_index = snapshot_by_key[source_key].get("source_order_index")
        if not isinstance(source_order_index, int):
            raise RuntimeError(f"fresh_audit_source_order_index_invalid:{dataset}")
        rows.append({
            "dataset": dataset,
            "role": "fresh_audit_reserve",
            "reserve_index": index,
            "source_order_index": source_order_index,
            "source_key": source_key,
            "source_hash": item["source_hash"],
            "normalized_text_hash": item["normalized_text_hash"],
        })
    return rows


def _load_design_config(root: Path) -> dict[str, Any]:
    config = load_yaml(_resolve(DESIGN_CONFIG_PATH, root))
    if not isinstance(config, Mapping):
        raise RuntimeError("fresh_audit_design_config_invalid")
    pools = config.get("frozen_v22_bindings", {}).get("source_pools", {})
    if not isinstance(pools, Mapping):
        raise RuntimeError("fresh_audit_source_pool_bindings_missing")
    return dict(config)


def _load_model_emitter(root: Path) -> Callable[[str, str], Sequence[Mapping[str, Any]]]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("fresh_audit_cuda_required")
    lock = load_yaml(_resolve(MODEL_LOCK_PATH, root))
    models = lock.get("models") if isinstance(lock, Mapping) else None
    matches = [
        item for item in models or ()
        if isinstance(item, Mapping) and item.get("role") == "gliner2_base"
    ]
    if len(matches) != 1:
        raise RuntimeError("fresh_audit_gliner2_base_lock_missing")
    model = dict(matches[0])
    local_path = _resolve(str(model.get("local_path", "")), root)
    files = model.get("files_sha256")
    if not local_path.is_dir() or not isinstance(files, Mapping) or not files:
        raise RuntimeError("fresh_audit_model_snapshot_missing")
    for relative_name, expected_hash in files.items():
        path = local_path / str(relative_name)
        if not path.is_file() or sha256_file(path) != str(expected_hash):
            raise RuntimeError(f"fresh_audit_model_snapshot_drift:{relative_name}")
    backend: SemanticPredictionBackend = _load_backend(
        model, local_path, runtime_device="cuda", use_fp16=True
    )

    def emit(text: str, _dataset: str) -> Sequence[Mapping[str, Any]]:
        return [
            {
                "label": prediction.label,
                "text": prediction.text,
                "start": prediction.start,
                "end": prediction.end,
                "score": prediction.score,
            }
            for prediction in backend.predict(text, ALL_SEMANTIC_SCHEMA)
        ]

    return emit


def _validate_source_order_identity(
    source_order: Sequence[str], row: Mapping[str, Any]
) -> None:
    source_order_index = row.get("source_order_index")
    if (
        isinstance(source_order_index, bool)
        or not isinstance(source_order_index, int)
        or source_order_index < 0
        or source_order_index >= len(source_order)
        or source_order[source_order_index] != row.get("source_key")
    ):
        raise RuntimeError("fresh_audit_source_order_identity_drift")


class _FreshAuditSourceReader:
    """Read only reserve rows after the caller has validated their identity."""

    _SOURCE_COLUMNS = ("source_key", "source_order_rank", "full_text", "input_row_count")
    _CHUNK_COLUMNS = ("source_key", "chunk_rank", "selection_hash", "row_json")

    def __init__(self, root: Path, dataset: str, pool: Mapping[str, Any]) -> None:
        self.dataset = dataset
        self.database_path = _resolve(str(pool["database_path"]), root)
        order_path = _resolve(str(pool["source_order_path"]), root)
        manifest_path = _resolve(str(pool["manifest_path"]), root)
        if (
            not self.database_path.is_file()
            or not order_path.is_file()
            or not manifest_path.is_file()
            or sha256_file(self.database_path) != str(pool["database_sha256"])
            or sha256_file(order_path) != str(pool["source_order_file_sha256"])
            or sha256_file(manifest_path) != str(pool["manifest_sha256"])
        ):
            raise RuntimeError("fresh_audit_source_pool_binding_drift")
        order_payload = _read_json(order_path)
        order = order_payload.get("source_order")
        expected_count = int(pool["source_count"])
        if (
            order_payload.get("dataset") != dataset
            or not isinstance(order, list)
            or len(order) != expected_count
            or len(set(order)) != expected_count
            or not all(isinstance(item, str) and item for item in order)
        ):
            raise RuntimeError("fresh_audit_source_order_binding_drift")
        self.source_order = tuple(order)
        self.connection = sqlite3.connect(
            self.database_path.as_uri() + "?mode=ro&immutable=1", uri=True
        )
        self.connection.row_factory = sqlite3.Row
        source_columns = tuple(row[1] for row in self.connection.execute("PRAGMA table_info(sources)"))
        chunk_columns = tuple(row[1] for row in self.connection.execute("PRAGMA table_info(chunks)"))
        if source_columns != self._SOURCE_COLUMNS or chunk_columns != self._CHUNK_COLUMNS:
            raise RuntimeError("fresh_audit_source_pool_schema_drift")
        count = int(self.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        if count != expected_count:
            raise RuntimeError("fresh_audit_source_pool_count_drift")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "_FreshAuditSourceReader":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        self.close()
        return False

    def read(self, row: Mapping[str, Any]) -> dict[str, Any]:
        _validate_source_order_identity(self.source_order, row)
        source = self.connection.execute(
            "SELECT source_key, source_order_rank, full_text, input_row_count FROM sources WHERE source_key = ?",
            (row["source_key"],),
        ).fetchone()
        if source is None:
            raise RuntimeError("fresh_audit_source_missing")
        chunks = self.connection.execute(
            "SELECT source_key, chunk_rank, selection_hash, row_json FROM chunks WHERE source_key = ? ORDER BY chunk_rank ASC",
            (row["source_key"],),
        ).fetchall()
        source_value = validate_selector_source_input({
            "dataset": self.dataset,
            "source_key": source["source_key"],
            "source_order_rank": source["source_order_rank"],
            "full_text": source["full_text"],
            "input_row_count": source["input_row_count"],
            "chunks": [
                {
                    "source_key": item["source_key"],
                    "chunk_rank": item["chunk_rank"],
                    "selection_hash": item["selection_hash"],
                    "row": json.loads(item["row_json"]),
                }
                for item in chunks
            ],
        })
        if text_sha256(source_value["full_text"]) != row["source_hash"] or normalized_text_sha256(source_value["full_text"]) != row["normalized_text_hash"]:
            raise RuntimeError("fresh_audit_source_content_identity_drift")
        return source_value


def select_first_eligible_sources(
    reserve_results: Sequence[Mapping[str, Any]],
    *,
    required_source_count: int = 100,
) -> list[dict[str, Any]]:
    if required_source_count <= 0:
        raise ValueError("required_source_count_invalid")
    selected = [dict(row) for row in reserve_results if row.get("eligible") is True]
    if len(selected) < required_source_count:
        raise RuntimeError("fresh_audit_reserve_eligible_shortfall")
    return selected[:required_source_count]


def _hmac_hex(secret: bytes, payload: Mapping[str, Any]) -> str:
    return hmac.new(secret, canonical_json(dict(payload)).encode("utf-8"), hashlib.sha256).hexdigest()


def build_blind_packet_rows(
    selected_sources: Sequence[Mapping[str, Any]],
    *,
    protocol_revision_id: str,
    reserve_snapshot_sha256: str,
    audit_secret: bytes,
) -> list[dict[str, Any]]:
    if len(audit_secret) != 32:
        raise ValueError("fresh_audit_secret_length_invalid")
    rows: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for source in selected_sources:
        opaque_id = _hmac_hex(audit_secret, {
            "kind": "v23_opaque_audit_source",
            "protocol_revision_id": protocol_revision_id,
            "reserve_snapshot_sha256": reserve_snapshot_sha256,
            "dataset": source["dataset"],
            "source_key": source["source_key"],
        })[:32]
        if opaque_id in seen_sources:
            raise RuntimeError("fresh_audit_opaque_source_id_collision")
        seen_sources.add(opaque_id)
        pairs = source.get("selected_pairs")
        if not isinstance(pairs, list) or len(pairs) != 3:
            raise RuntimeError("fresh_audit_packet_source_pair_count_invalid")
        seen_pairs: set[str] = set()
        for pair in pairs:
            if pair["pair_id"] in seen_pairs:
                raise RuntimeError("fresh_audit_packet_pair_id_collision")
            seen_pairs.add(pair["pair_id"])
            packet_key = _hmac_hex(audit_secret, {
                "kind": "v23_audit_packet_order",
                "protocol_revision_id": protocol_revision_id,
                "opaque_audit_source_id": opaque_id,
                "pair_id": pair["pair_id"],
            })
            row = {
                "kind": "v23_blind_audit_packet",
                "opaque_audit_source_id": opaque_id,
                "packet_order_key": packet_key,
                "pair_id": pair["pair_id"],
                "pair_order": pair["pair_order"],
                "complete_source_text": source["full_text"],
                "supporting_sentence": pair["true_claim"],
                "true_claim": pair["true_claim"],
                "counterfactual_claim": pair["counterfactual_claim"],
                "original_entity": pair["original_entity"],
                "counterfactual_entity": pair["counterfactual_entity"],
                "effective_type": pair["effective_type"],
            }
            if set(row) != PACKET_VISIBLE_FIELDS or PACKET_HIDDEN_FIELDS.intersection(row):
                raise RuntimeError("fresh_audit_packet_schema_drift")
            rows.append(row)
    rows.sort(key=lambda row: (row["packet_order_key"], row["pair_id"]))
    return rows


def _source_result_hash(row: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in row.items() if key not in {"created_at", "source_result_sha256"}}
    )


def _source_results_identity(rows: Sequence[Mapping[str, Any]]) -> str:
    """Bind the complete, ordered source-result set to one canonical hash."""

    return canonical_sha256([
        {
            "reserve_index": row["reserve_index"],
            "source_key": row["source_key"],
            "source_result_sha256": row["source_result_sha256"],
        }
        for row in rows
    ])


def _dataset_audit_root(root: Path, freeze_identity: str, dataset: str) -> Path:
    return _audit_root(root, freeze_identity) / "datasets" / dataset


def _dataset_identity(
    *,
    freeze_identity: str,
    dataset: str,
    reserve: Mapping[str, Any],
) -> str:
    return canonical_sha256(
        {
            "kind": "v23_fresh_audit_dataset_preparation",
            "specification_version": "pcv-restoration-first-v23-fresh-audit-preparation-r1",
            "freeze_identity_sha256": freeze_identity,
            "dataset": dataset,
            "reserve_plan_sha256": reserve["plan_sha256"],
            "reserve_snapshot_sha256": reserve["snapshot_sha256"],
        }
    )


def _validate_existing_source_result(
    row: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    dataset_identity: str | None = None,
    freeze_identity: str | None = None,
) -> dict[str, Any]:
    if (
        row.get("kind") != "v23_fresh_audit_source_result"
        or row.get("dataset") != expected["dataset"]
        or row.get("reserve_index") != expected["reserve_index"]
        or row.get("source_key") != expected["source_key"]
        or row.get("source_order_index") != expected["source_order_index"]
        or row.get("source_hash") != expected["source_hash"]
        or row.get("normalized_text_hash") != expected["normalized_text_hash"]
        or row.get("source_result_sha256") != _source_result_hash(row)
        or row.get("external_calls_performed") != 0
        or (dataset_identity is not None and row.get("dataset_identity_sha256") != dataset_identity)
        or (freeze_identity is not None and row.get("freeze_identity_sha256") != freeze_identity)
    ):
        raise RuntimeError("fresh_audit_source_result_drift")
    if row.get("eligible") is not True and row.get("eligible") is not False:
        raise RuntimeError("fresh_audit_source_result_eligibility_invalid")
    if not isinstance(row.get("full_text"), str):
        raise RuntimeError("fresh_audit_source_result_text_missing")
    pairs = row.get("selected_pairs")
    if not isinstance(pairs, list) or len(pairs) not in {0, 3}:
        raise RuntimeError("fresh_audit_source_result_pair_count_invalid")
    if (row.get("eligible") is True and len(pairs) != 3) or (
        row.get("eligible") is False and len(pairs) != 0
    ):
        raise RuntimeError("fresh_audit_source_result_eligibility_shape_drift")
    return dict(row)


def _load_contiguous_source_results(
    result_directory: Path,
    reserve_rows: Sequence[Mapping[str, Any]],
    *,
    dataset_identity: str,
    freeze_identity: str,
) -> list[dict[str, Any]]:
    """Load only an immutable contiguous prefix; reject gaps or stray files."""

    files = [path for path in result_directory.glob("*.json") if path.is_file()]
    for path in files:
        if len(path.stem) != 6 or not path.stem.isdigit():
            raise RuntimeError("fresh_audit_source_result_filename_drift")
    results: list[dict[str, Any]] = []
    for expected in reserve_rows:
        path = result_directory / f"{expected['reserve_index']:06d}.json"
        if not path.is_file():
            break
        results.append(
            _validate_existing_source_result(
                _read_json(path),
                expected=expected,
                dataset_identity=dataset_identity,
                freeze_identity=freeze_identity,
            )
        )
    expected_names = {f"{row['reserve_index']:06d}.json" for row in reserve_rows[: len(results)]}
    if {path.name for path in files} != expected_names:
        raise RuntimeError("fresh_audit_source_result_prefix_drift")
    return results


def prepare_dataset(
    *,
    project_root: str | Path = ".",
    dataset: str,
    authorization_path: str | Path,
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Consume only the authorized reserve prefix and freeze dataset results."""

    root = Path(project_root).resolve()
    if dataset not in DATASETS:
        raise ValueError("fresh_audit_dataset_invalid")
    freeze = validate_preparation_freeze(root)
    authorization = validate_run_authorization(
        project_root=root,
        authorization_path=authorization_path,
        stage="dataset_preparation",
        dataset=dataset,
    )
    config = load_preparation_config(root)
    reserve = _validate_reserve_metadata(root, config, dataset)
    identity = _dataset_identity(
        freeze_identity=freeze["freeze_identity_sha256"],
        dataset=dataset,
        reserve=reserve,
    )
    output = _dataset_audit_root(root, freeze["freeze_identity_sha256"], dataset)
    result_directory = output / "source_results"
    result_directory.mkdir(parents=True, exist_ok=True)
    reserve_rows = _reserve_rows(root, config, dataset)
    design = _load_design_config(root)
    pool = design["frozen_v22_bindings"]["source_pools"][dataset]
    entity_policy_path = _resolve(
        str(design["frozen_v22_bindings"]["extraction_rule_bindings"]["entity_type_policy_path"]),
        root,
    )
    selection_config = load_yaml(_resolve(str(config["selection_config_path"]), root))
    if not isinstance(selection_config, Mapping):
        raise RuntimeError("fresh_audit_selection_config_invalid")
    source_results = _load_contiguous_source_results(
        result_directory,
        reserve_rows,
        dataset_identity=identity,
        freeze_identity=freeze["freeze_identity_sha256"],
    )
    selected_source_count = int(config["reserve_group"]["selected_source_count_per_dataset"])
    if len([row for row in source_results if row["eligible"] is True]) < selected_source_count:
        emitter = model_emitter or _load_model_emitter(root)
        with _FreshAuditSourceReader(root, dataset, pool) as reader:
            for expected in reserve_rows[len(source_results):]:
                source = reader.read(expected)
                first = extract_fact_candidates(
                    source,
                    model_emitter=emitter,
                    entity_policy_path=str(entity_policy_path),
                    token_df=None,
                    source_count=int(pool["source_count"]),
                )
                second = extract_fact_candidates(
                    source,
                    model_emitter=emitter,
                    entity_policy_path=str(entity_policy_path),
                    token_df=None,
                    source_count=int(pool["source_count"]),
                )
                if canonical_sha256(first) != canonical_sha256(second):
                    raise RuntimeError("fresh_audit_fact_nondeterministic")
                selection = select_pairs_from_r1_facts(
                    first["facts"],
                    dataset=dataset,
                    selection_identity_sha256=freeze["freeze_identity_sha256"],
                    config=selection_config,
                )
                selected_pairs = selection["selected"]
                if len(selected_pairs) not in {0, int(config["reserve_group"]["pairs_per_source"])}:
                    raise RuntimeError("fresh_audit_source_result_pair_count_invalid")
                for fact in first["facts"]:
                    validate_fact_row(fact)
                result = {
                    "kind": "v23_fresh_audit_source_result",
                    "specification_version": config["specification_version"],
                    "dataset": dataset,
                    "freeze_identity_sha256": freeze["freeze_identity_sha256"],
                    "dataset_identity_sha256": identity,
                    "reserve_index": expected["reserve_index"],
                    "source_order_index": expected["source_order_index"],
                    "source_key": expected["source_key"],
                    "source_hash": expected["source_hash"],
                    "normalized_text_hash": expected["normalized_text_hash"],
                    "full_text": source["full_text"],
                    "eligible": len(selected_pairs) == int(config["reserve_group"]["pairs_per_source"]),
                    "selected_pairs": selected_pairs,
                    "fact_count": first["fact_count"] if "fact_count" in first else len(first["facts"]),
                    "candidate_count": first["candidate_count"],
                    "selection_candidate_pair_count": selection["candidate_pair_count"],
                    "rejection_reason_counts": selection["rejection_reason_counts"],
                    "external_calls_performed": 0,
                    "created_at": _utc_now(),
                }
                result["source_result_sha256"] = _source_result_hash(result)
                _write_new_json(result_directory / f"{expected['reserve_index']:06d}.json", result)
                source_results.append(result)
                if len([row for row in source_results if row["eligible"] is True]) >= selected_source_count:
                    break
    selected = select_first_eligible_sources(
        source_results,
        required_source_count=int(config["reserve_group"]["selected_source_count_per_dataset"]),
    )
    selected_pairs = [pair for source in selected for pair in source["selected_pairs"]]
    manifest = {
        "kind": "v23_fresh_audit_dataset_manifest",
        "specification_version": config["specification_version"],
        "dataset": dataset,
        "freeze_identity_sha256": freeze["freeze_identity_sha256"],
        "dataset_identity_sha256": identity,
        "reserve_plan_sha256": reserve["plan_sha256"],
        "reserve_snapshot_sha256": reserve["snapshot_sha256"],
        "evaluated_source_count": len(source_results),
        "eligible_source_count": sum(row["eligible"] is True for row in source_results),
        "selected_source_count": len(selected),
        "selected_pair_count": len(selected_pairs),
        "source_results_identity_sha256": _source_results_identity(source_results),
        "external_calls_performed": 0,
        "status": "passed",
        "created_at": _utc_now(),
    }
    manifest_path = output / "dataset_manifest.json"
    if manifest_path.exists():
        actual = _read_json(manifest_path)
        if {key: value for key, value in actual.items() if key != "created_at"} != {key: value for key, value in manifest.items() if key != "created_at"}:
            raise RuntimeError("fresh_audit_dataset_manifest_drift")
    else:
        _write_new_json(manifest_path, manifest)
    _write_or_validate_jsonl(output / "selected_pairs.jsonl", selected_pairs)
    return {
        "status": "passed",
        "dataset": dataset,
        "dataset_identity_sha256": identity,
        "evaluated_source_count": len(source_results),
        "selected_source_count": len(selected),
        "selected_pair_count": len(selected_pairs),
        "authorization_id": authorization["authorization_id"],
        "external_calls_performed": 0,
    }


def build_packets(
    *,
    project_root: str | Path = ".",
    authorization_path: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    freeze = validate_preparation_freeze(root)
    authorization = validate_run_authorization(
        project_root=root,
        authorization_path=authorization_path,
        stage="packet_preparation",
        dataset=None,
    )
    config = load_preparation_config(root)
    selected_sources: list[dict[str, Any]] = []
    dataset_manifest_hashes: dict[str, str] = {}
    for dataset in DATASETS:
        reserve = _validate_reserve_metadata(root, config, dataset)
        identity = _dataset_identity(
            freeze_identity=freeze["freeze_identity_sha256"],
            dataset=dataset,
            reserve=reserve,
        )
        output = _dataset_audit_root(root, freeze["freeze_identity_sha256"], dataset)
        manifest_path = output / "dataset_manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(f"fresh_audit_dataset_manifest_missing:{dataset}")
        manifest = _read_json(manifest_path)
        if manifest.get("status") != "passed" or manifest.get("selected_source_count") != int(config["reserve_group"]["selected_source_count_per_dataset"]):
            raise RuntimeError(f"fresh_audit_dataset_not_ready:{dataset}")
        reserve_rows = _reserve_rows(root, config, dataset)
        source_results = _load_contiguous_source_results(
            output / "source_results",
            reserve_rows,
            dataset_identity=identity,
            freeze_identity=freeze["freeze_identity_sha256"],
        )
        selected = select_first_eligible_sources(
            source_results,
            required_source_count=int(config["reserve_group"]["selected_source_count_per_dataset"]),
        )
        expected_source_identity = _source_results_identity(source_results)
        if (
            manifest.get("dataset_identity_sha256") != identity
            or manifest.get("evaluated_source_count") != len(source_results)
            or manifest.get("eligible_source_count") != sum(row["eligible"] is True for row in source_results)
            or manifest.get("selected_pair_count") != sum(len(row["selected_pairs"]) for row in selected)
            or manifest.get("source_results_identity_sha256") != expected_source_identity
        ):
            raise RuntimeError(f"fresh_audit_dataset_manifest_drift:{dataset}")
        selected_pairs_path = output / "selected_pairs.jsonl"
        if not selected_pairs_path.is_file():
            raise RuntimeError(f"fresh_audit_selected_pairs_missing:{dataset}")
        expected_pairs = [pair for source in selected for pair in source["selected_pairs"]]
        if _read_jsonl(selected_pairs_path) != expected_pairs:
            raise RuntimeError(f"fresh_audit_selected_pairs_drift:{dataset}")
        dataset_manifest_hashes[dataset] = sha256_file(manifest_path)
        selected_sources.extend(selected)
    secret_path = _audit_root(root, freeze["freeze_identity_sha256"]) / "private" / "audit_secret.bin"
    if secret_path.exists():
        secret = secret_path.read_bytes()
        if len(secret) != 32:
            raise RuntimeError("fresh_audit_secret_length_invalid")
    else:
        secret = os.urandom(32)
        _atomic_write(secret_path, secret)
    freeze_manifest_path = _resolve(FREEZE_MANIFEST_PATH, root)
    freeze_manifest = _read_json(freeze_manifest_path)
    if (
        freeze_manifest.get("freeze_identity_sha256")
        != freeze["freeze_identity_sha256"]
        or not isinstance(freeze_manifest.get("datasets"), Mapping)
    ):
        raise RuntimeError("fresh_audit_packet_freeze_manifest_invalid")
    reserve_snapshot_binding = canonical_sha256(
        [
            freeze_manifest["datasets"][dataset]["reserve_snapshot_sha256"]
            for dataset in DATASETS
        ]
    )
    rows = build_blind_packet_rows(
        selected_sources,
        protocol_revision_id=config["execution_reservation_revision"],
        reserve_snapshot_sha256=reserve_snapshot_binding,
        audit_secret=secret,
    )
    expected_rows = int(config["reserve_group"]["total_packet_rows"])
    if len(rows) != expected_rows:
        raise RuntimeError("fresh_audit_packet_row_count_invalid")
    audit_root = _audit_root(root, freeze["freeze_identity_sha256"])
    packet_path = audit_root / "blind_packets.jsonl"
    _write_or_validate_jsonl(packet_path, rows)
    manifest = {
        "kind": "v23_blind_audit_packet_manifest",
        "specification_version": config["specification_version"],
        "freeze_identity_sha256": freeze["freeze_identity_sha256"],
        "reserve_group_completion_sha256": freeze["reserve_group"]["group_completion_sha256"],
        "reserve_snapshot_binding_sha256": reserve_snapshot_binding,
        "selected_dataset_manifest_sha256": dataset_manifest_hashes,
        "packet_path": packet_path.relative_to(root).as_posix(),
        "packet_file_sha256": sha256_file(packet_path),
        "packet_row_count": len(rows),
        "audit_secret_commitment_sha256": hashlib.sha256(secret).hexdigest(),
        "external_calls_performed": 0,
        "status": "prepared_for_human_blind_review",
        "created_at": _utc_now(),
    }
    manifest_path = audit_root / "blind_packet_manifest.json"
    if manifest_path.exists():
        actual = _read_json(manifest_path)
        if {key: value for key, value in actual.items() if key != "created_at"} != {key: value for key, value in manifest.items() if key != "created_at"}:
            raise RuntimeError("fresh_audit_packet_manifest_drift")
    else:
        _write_new_json(manifest_path, manifest)
    return {
        "status": "passed",
        "packet_row_count": len(rows),
        "packet_manifest_sha256": sha256_file(manifest_path),
        "authorization_id": authorization["authorization_id"],
        "external_calls_performed": 0,
    }


def prepare_run_authorization(
    *,
    project_root: str | Path = ".",
    stage: str,
    dataset: str | None = None,
    user_authorization_record: str,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    freeze = validate_preparation_freeze(root)
    if stage not in RUN_AUTH_ALLOWED_STAGES:
        raise ValueError("fresh_audit_authorization_stage_invalid")
    if stage == "dataset_preparation" and dataset not in DATASETS:
        raise ValueError("fresh_audit_authorization_dataset_required")
    if stage == "packet_preparation" and dataset is not None:
        raise ValueError("fresh_audit_packet_authorization_dataset_forbidden")
    if not isinstance(user_authorization_record, str) or not user_authorization_record.strip():
        raise ValueError("fresh_audit_user_authorization_record_required")
    config = load_preparation_config(root)
    payload = {
        "kind": RUN_AUTH_KIND,
        "specification_version": config["specification_version"],
        "stage": stage,
        "dataset": dataset,
        "freeze_identity_sha256": freeze["freeze_identity_sha256"],
        "budget_maximum_source_reads": 250 if stage == "dataset_preparation" else 0,
        "external_calls_allowed": False,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "formal_experiment_allowed": False,
        "user_authorization_record": user_authorization_record.strip(),
        "created_at": _utc_now(),
    }
    payload["authorization_id"] = canonical_sha256(payload)
    path = _resolve(Path("artifacts/v23/governance/run_authorizations") / f"{payload['authorization_id']}.json", root)
    if path.exists():
        actual = _read_json(path)
        if {key: value for key, value in actual.items() if key != "created_at"} != {key: value for key, value in payload.items() if key != "created_at"}:
            raise RuntimeError("fresh_audit_authorization_drift")
    else:
        _write_new_json(path, payload)
    return {**payload, "authorization_path": path.relative_to(root).as_posix(), "external_calls_performed": 0}


def validate_run_authorization(
    *,
    project_root: str | Path,
    authorization_path: str | Path,
    stage: str,
    dataset: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    freeze = validate_preparation_freeze(root)
    auth = _read_json(_resolve(authorization_path, root))
    if auth.get("kind") != RUN_AUTH_KIND or auth.get("stage") != stage or auth.get("freeze_identity_sha256") != freeze["freeze_identity_sha256"]:
        raise RuntimeError("fresh_audit_authorization_identity_drift")
    required_false_scope = (
        "external_calls_allowed",
        "api_allowed",
        "victim_allowed",
        "retriever_allowed",
        "formal_experiment_allowed",
    )
    if auth.get("dataset") != dataset or any(
        auth.get(key) is not False for key in required_false_scope
    ):
        raise RuntimeError("fresh_audit_authorization_scope_drift")
    # authorization_id covers the complete immutable payload except its own id.
    payload = {key: value for key, value in auth.items() if key != "authorization_id"}
    if auth.get("authorization_id") != canonical_sha256(payload):
        raise RuntimeError("fresh_audit_authorization_hash_drift")
    return auth


def status(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    freeze = validate_preparation_freeze(root)
    audit_dir = _audit_root(root, freeze["freeze_identity_sha256"])
    return {
        "kind": "v23_frozen_r2_fresh_audit_preparation_status",
        "status": "frozen_preparation_downstream_blocked",
        "freeze_identity_sha256": freeze["freeze_identity_sha256"],
        "audit_directory_present": audit_dir.is_dir(),
        "source_content_read": False,
        "external_calls_performed": 0,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "formal_experiment_allowed": False,
    }
