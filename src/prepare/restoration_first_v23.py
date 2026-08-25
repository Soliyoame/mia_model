"""Lightweight development runner for the PCV-MIA v23 selector."""

from __future__ import annotations

import importlib.metadata
import inspect
import json
import math
import os
import platform
import sqlite3
import subprocess
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from ..attack.restoration_first_v23 import (
    SPECIFICATION_VERSION,
    aggregate_document_frequency,
    build_pair_candidates,
    canonical_json,
    canonical_sha256,
    fresh_extract_candidates,
    normalized_text_sha256,
    reject_forbidden_selection_fields,
    select_top_three,
    text_sha256,
    validate_selector_source_input,
)
from ..attack.semantic_entity_resolver import (
    ALL_SEMANTIC_SCHEMA,
    SemanticPredictionBackend,
    _load_backend,
)
from ..utils.hash import sha256_file
from ..utils.io import load_yaml


DESIGN_CONFIG = Path("configs/restoration_first_v23.yaml")
DESIGN_MANIFEST = Path("configs/restoration_first_v23.design_manifest.json")
MODEL_LOCK_PATH = Path("configs/semantic_entity_models_v6_3.lock.yaml")
ARTIFACT_ROOT = Path("artifacts/v23")
AGGREGATE_DF_DIRECTORY = ARTIFACT_ROOT / "aggregate_df"
DEVELOPMENT_DIRECTORY = ARTIFACT_ROOT / "selection/development"
DEVELOPMENT_RESERVATION_REVISION = (
    "71e862b7591b2ac9bd1a1759b3784fc3b0e4b7286b96098d4997f0f173b78043"
)
DATASET_ORDER = ("edgar", "enron", "pubmed")
LIGHTWEIGHT_EXECUTION_REVISION = "pcv-restoration-first-v23-lightweight-dev-r1"
SCIENTIFIC_IMPLEMENTATION_FILES = (
    Path("src/attack/attackability_selector.py"),
    Path("src/attack/entity_extractor.py"),
    Path("src/attack/entity_type_policy.py"),
    Path("src/attack/perturbation_generator.py"),
    Path("src/attack/restoration_first_v23.py"),
    Path("src/attack/semantic_entity_resolver.py"),
)
# 仅允许本次“异常转拒绝”的精确兼容，不把历史结果伪装成新算法输出。
CRASH_ONLY_SCIENTIFIC_HASH_COMPATIBILITY = {
    "src/attack/restoration_first_v23.py": {
        "3fb1947d9047806f30410ef230cc0f39571d1d7462ea0fa408f4a9ff69a802a1":
        "9bddeac01b25877758aa3f409d3819deae10033113c6eb523caa621c31210f37",
    }
}

SELECTED_PAIR_FIELDS = {
    "kind", "specification_version", "protocol_revision_id", "dataset",
    "source_key", "source_hash", "normalized_text_hash", "source_order_rank",
    "pair_order", "pair_id", "fact_signature", "relation_signature",
    "supporting_sentence", "original_span", "original_entity",
    "counterfactual_entity", "effective_type", "semantic_subtype", "true_claim",
    "counterfactual_claim", "rank_tuple",
}
SOURCE_RESULT_FIELDS = {
    "kind", "design_manifest_sha256", "scientific_identity_sha256", "attempt_id",
    "dataset", "source_order_index", "source_key", "source_hash",
    "normalized_text_hash", "eligible", "selected_pairs", "rejection_reasons",
    "candidate_count", "pair_candidate_count", "hard_gate_violation_count",
    "deterministic_rerun_hash_match", "source_result_sha256", "completed_at",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _resolve(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"path_outside_project:{path}") from error
    return resolved


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"json_object_required:{path}")
    return value


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
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
    _atomic_write_bytes(path, (canonical_json(dict(value)) + "\n").encode("utf-8"))


def _write_or_validate_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    expected = "".join(canonical_json(dict(row)) + "\n" for row in rows).encode("utf-8")
    if path.exists():
        if path.read_bytes() != expected:
            raise RuntimeError(f"artifact_identity_drift:{path}")
        return
    _atomic_write_bytes(path, expected)


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_lock_pid(path: Path) -> int | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pid = value.get("pid") if isinstance(value, Mapping) else None
    return pid if isinstance(pid, int) and not isinstance(pid, bool) else None


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Acquire one PID lock and automatically recover a dead owner."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        owner = _read_lock_pid(path)
        if owner is not None and _pid_running(owner):
            raise RuntimeError(f"active_process_lock:{path}:pid={owner}")
        path.unlink()
    payload = {
        "kind": "v23_lightweight_process_lock",
        "pid": os.getpid(),
        "created_at": utc_now(),
    }
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(descriptor, (canonical_json(payload) + "\n").encode("utf-8"))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        yield
    except FileExistsError as error:
        raise RuntimeError(
            f"active_process_lock:{path}:pid={_read_lock_pid(path)}"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if path.exists() and _read_lock_pid(path) == os.getpid():
            path.unlink()


def load_design_config(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_yaml(_resolve(DESIGN_CONFIG, root))
    if not isinstance(config, Mapping):
        raise RuntimeError("v23_design_config_invalid")
    if (
        config.get("protocol_version") != "pcv-mia-v23"
        or config.get("specification_version") != SPECIFICATION_VERSION
    ):
        raise RuntimeError("v23_design_identity_drift")
    return dict(config)


def _design_manifest_sha256(root: Path) -> str:
    path = _resolve(DESIGN_MANIFEST, root)
    if not path.is_file():
        raise RuntimeError("v23_design_manifest_missing")
    return sha256_file(path)


def _pool_contract(config: Mapping[str, Any], dataset: str) -> dict[str, Any]:
    if dataset not in DATASET_ORDER:
        raise ValueError("dataset_invalid")
    pools = config.get("frozen_v22_bindings", {}).get("source_pools", {})
    pool = pools.get(dataset) if isinstance(pools, Mapping) else None
    required = {
        "manifest_path", "manifest_sha256", "database_path", "database_sha256",
        "source_order_path", "source_order_file_sha256", "source_count",
    }
    if not isinstance(pool, Mapping) or not required.issubset(pool):
        raise RuntimeError(f"source_pool_binding_incomplete:{dataset}")
    return dict(pool)


def _development_count(config: Mapping[str, Any]) -> int:
    value = config.get("development_gate", {}).get("source_count_per_dataset")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError("development_source_count_invalid")
    return value


def _fresh_reserve_count(config: Mapping[str, Any]) -> int:
    value = config.get("fresh_audit", {}).get("reserve_source_count_per_dataset")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError("fresh_reserve_source_count_invalid")
    return value


class FrozenSourcePoolReader:
    """Read only explicitly permitted sources from the frozen v22 pool."""

    _SOURCE_COLUMNS = ("source_key", "source_order_rank", "full_text", "input_row_count")
    _CHUNK_COLUMNS = ("source_key", "chunk_rank", "selection_hash", "row_json")

    def __init__(
        self,
        *,
        project_root: str | Path,
        dataset: str,
        pool: Mapping[str, Any],
    ) -> None:
        root = Path(project_root).resolve()
        self.dataset = dataset
        self.database_path = _resolve(str(pool["database_path"]), root)
        order_path = _resolve(str(pool["source_order_path"]), root)
        manifest_path = _resolve(str(pool["manifest_path"]), root)
        if not self.database_path.is_file():
            raise RuntimeError("source_pool_database_missing")
        for path, expected in (
            (order_path, str(pool["source_order_file_sha256"])),
            (manifest_path, str(pool["manifest_sha256"])),
        ):
            if not path.is_file() or sha256_file(path) != expected:
                raise RuntimeError(f"source_pool_small_binding_drift:{path}")
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
            raise RuntimeError("source_order_identity_drift")
        self.source_order = tuple(order)
        self.source_keys = frozenset(order)
        self.source_count = expected_count
        uri = self.database_path.as_uri() + "?mode=ro&immutable=1"
        self._connection = sqlite3.connect(uri, uri=True)
        self._connection.row_factory = sqlite3.Row
        self._validate_schema()

    def _validate_schema(self) -> None:
        source_columns = tuple(
            row[1] for row in self._connection.execute("PRAGMA table_info(sources)")
        )
        chunk_columns = tuple(
            row[1] for row in self._connection.execute("PRAGMA table_info(chunks)")
        )
        if source_columns != self._SOURCE_COLUMNS or chunk_columns != self._CHUNK_COLUMNS:
            raise RuntimeError("source_pool_database_schema_drift")
        count = int(self._connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        if count != self.source_count:
            raise RuntimeError("source_pool_database_count_drift")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "FrozenSourcePoolReader":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def read_source(self, _source_key: str) -> dict[str, Any]:
        raise RuntimeError("unguarded_source_read_forbidden")

    def _read_source(self, source_key: str) -> dict[str, Any]:
        if source_key not in self.source_keys:
            raise RuntimeError("source_not_in_frozen_order")
        source = self._connection.execute(
            "SELECT source_key, source_order_rank, full_text, input_row_count "
            "FROM sources WHERE source_key = ?",
            (source_key,),
        ).fetchone()
        if source is None:
            raise RuntimeError("source_pool_source_missing")
        chunks = self._connection.execute(
            "SELECT source_key, chunk_rank, selection_hash, row_json "
            "FROM chunks WHERE source_key = ? ORDER BY chunk_rank ASC",
            (source_key,),
        ).fetchall()
        return validate_selector_source_input(
            {
                "dataset": self.dataset,
                "source_key": source["source_key"],
                "source_order_rank": source["source_order_rank"],
                "full_text": source["full_text"],
                "input_row_count": source["input_row_count"],
                "chunks": [
                    {
                        "source_key": row["source_key"],
                        "chunk_rank": row["chunk_rank"],
                        "selection_hash": row["selection_hash"],
                        "row": json.loads(row["row_json"]),
                    }
                    for row in chunks
                ],
            }
        )

    def read_development_source(self, reservation_row: Mapping[str, Any]) -> dict[str, Any]:
        if (
            reservation_row.get("dataset") != self.dataset
            or reservation_row.get("role") != "development"
        ):
            raise RuntimeError("development_reservation_scope_drift")
        source = self._read_source(str(reservation_row.get("source_key")))
        if (
            text_sha256(source["full_text"]) != reservation_row.get("source_hash")
            or normalized_text_sha256(source["full_text"])
            != reservation_row.get("normalized_text_hash")
        ):
            raise RuntimeError("development_source_content_identity_drift")
        return source

    def iter_all_source_texts(self) -> Iterator[str]:
        for source_key in self.source_order:
            row = self._connection.execute(
                "SELECT full_text FROM sources WHERE source_key = ?", (source_key,)
            ).fetchone()
            if row is None or not isinstance(row["full_text"], str):
                raise RuntimeError("aggregate_df_source_missing")
            yield row["full_text"]


def _tokenization_contract(config: Mapping[str, Any]) -> dict[str, Any]:
    selector = config.get("selector_primitives")
    if not isinstance(selector, Mapping):
        raise RuntimeError("selector_primitives_missing")
    normalization = selector.get("text_normalization")
    tokenization = selector.get("tokenization")
    if not isinstance(normalization, Mapping) or not isinstance(tokenization, Mapping):
        raise RuntimeError("aggregate_df_tokenization_binding_missing")
    return {"normalization": dict(normalization), "tokenization": dict(tokenization)}


def _aggregate_paths(root: Path, dataset: str) -> dict[str, Path]:
    directory = _resolve(AGGREGATE_DF_DIRECTORY / dataset, root)
    return {
        "rows": directory / "token_df.jsonl",
        "manifest": directory / "df_manifest.json",
        "lock": directory / ".build.lock",
    }


def _load_token_df(path: Path, *, source_count: int) -> dict[str, int]:
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise RuntimeError("aggregate_df_rows_partial")
    token_df: dict[str, int] = {}
    previous: str | None = None
    for line in raw.decode("utf-8").splitlines():
        row = json.loads(line)
        if not isinstance(row, Mapping) or set(row) != {
            "kind", "token", "document_frequency"
        }:
            raise RuntimeError("aggregate_df_row_schema_drift")
        token = row["token"]
        frequency = row["document_frequency"]
        if (
            row["kind"] != "v23_token_document_frequency"
            or not isinstance(token, str)
            or not token
            or previous is not None and token <= previous
            or isinstance(frequency, bool)
            or not isinstance(frequency, int)
            or not 1 <= frequency <= source_count
        ):
            raise RuntimeError("aggregate_df_row_value_drift")
        token_df[token] = frequency
        previous = token
    return token_df


def validate_aggregate_df(
    *, project_root: str | Path = ".", dataset: str
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_design_config(root)
    pool = _pool_contract(config, dataset)
    paths = _aggregate_paths(root, dataset)
    if not paths["manifest"].is_file() or not paths["rows"].is_file():
        raise RuntimeError("aggregate_df_artifact_missing")
    manifest = _read_json(paths["manifest"])
    if (
        manifest.get("kind") not in {
            "v23_aggregate_document_frequency",
            "v23_lightweight_aggregate_document_frequency",
        }
        or manifest.get("dataset") != dataset
        or manifest.get("source_count") != int(pool["source_count"])
        or manifest.get("token_df_rows_file_sha256") != sha256_file(paths["rows"])
        or manifest.get("tokenization_contract_sha256")
        != canonical_sha256(_tokenization_contract(config))
        or manifest.get("external_calls_performed") != 0
    ):
        raise RuntimeError("aggregate_df_manifest_drift")
    token_df = _load_token_df(paths["rows"], source_count=int(pool["source_count"]))
    if manifest.get("token_count") != len(token_df):
        raise RuntimeError("aggregate_df_token_count_drift")
    return {
        "status": "passed",
        "dataset": dataset,
        "source_count": int(pool["source_count"]),
        "token_count": len(token_df),
        "df_manifest_file_sha256": sha256_file(paths["manifest"]),
        "token_df_rows_file_sha256": sha256_file(paths["rows"]),
        "external_calls_performed": 0,
    }


def run_aggregate_df(
    *, project_root: str | Path = ".", dataset: str
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_design_config(root)
    pool = _pool_contract(config, dataset)
    paths = _aggregate_paths(root, dataset)
    if paths["manifest"].exists() and paths["rows"].exists():
        return validate_aggregate_df(project_root=root, dataset=dataset)
    if paths["manifest"].exists() or paths["rows"].exists():
        raise RuntimeError("aggregate_df_partial_artifact")
    with exclusive_lock(paths["lock"]):
        with FrozenSourcePoolReader(project_root=root, dataset=dataset, pool=pool) as reader:
            token_df, source_count = aggregate_document_frequency(reader.iter_all_source_texts())
        rows = "".join(
            canonical_json(
                {
                    "kind": "v23_token_document_frequency",
                    "token": token,
                    "document_frequency": token_df[token],
                }
            )
            + "\n"
            for token in sorted(token_df)
        ).encode("utf-8")
        _atomic_write_bytes(paths["rows"], rows)
        manifest = {
            "kind": "v23_lightweight_aggregate_document_frequency",
            "execution_revision": LIGHTWEIGHT_EXECUTION_REVISION,
            "design_manifest_sha256": _design_manifest_sha256(root),
            "dataset": dataset,
            "input_identity_sha256": canonical_sha256(
                {"pool": pool, "tokenization": _tokenization_contract(config)}
            ),
            "source_count": source_count,
            "token_count": len(token_df),
            "token_df_rows_path": _relative(paths["rows"], root),
            "token_df_rows_file_sha256": sha256_file(paths["rows"]),
            "tokenization_contract_sha256": canonical_sha256(
                _tokenization_contract(config)
            ),
            "created_at": utc_now(),
            "external_calls_performed": 0,
        }
        _write_new_json(paths["manifest"], manifest)
    return validate_aggregate_df(project_root=root, dataset=dataset)


def load_development_reservation(
    *, project_root: str | Path = ".", dataset: str
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_design_config(root)
    development_count = _development_count(config)
    reservation_path = _resolve(
        ARTIFACT_ROOT
        / "governance/revision_reservations"
        / DEVELOPMENT_RESERVATION_REVISION
        / "plans/development"
        / f"{dataset}.json",
        root,
    )
    if not reservation_path.is_file():
        raise RuntimeError("development_reservation_missing")
    plan = _read_json(reservation_path)
    development = plan.get("ordered_source_identity_objects")
    if (
        plan.get("kind") != "v23_reservation_plan"
        or plan.get("dataset") != dataset
        or plan.get("role") != "development"
        or not isinstance(development, list)
        or len(development) != development_count
    ):
        raise RuntimeError("reservation_count_drift")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(development):
        if not isinstance(item, Mapping):
            raise RuntimeError("development_reservation_row_invalid")
        row = {
            "dataset": dataset,
            "role": "development",
            "source_key": item.get("source_key"),
            "source_hash": item.get("source_hash"),
            "normalized_text_hash": item.get("normalized_text_hash"),
            "reservation_batch_index": index,
            "reservation_batch_size": development_count,
        }
        if (
            not isinstance(row.get("source_key"), str)
            or not _is_sha256(row.get("source_hash"))
            or not _is_sha256(row.get("normalized_text_hash"))
        ):
            raise RuntimeError("development_reservation_order_drift")
        rows.append(row)
    if len({row["source_key"] for row in rows}) != development_count:
        raise RuntimeError("development_reservation_duplicate")
    identity_rows = [
        {
            "source_key": row["source_key"],
            "source_hash": row["source_hash"],
            "normalized_text_hash": row["normalized_text_hash"],
            "reservation_batch_index": row["reservation_batch_index"],
        }
        for row in rows
    ]
    return {
        "dataset": dataset,
        "rows": rows,
        "reservation_batch_id": str(plan.get("attempt_id")),
        "reservation_identity_sha256": canonical_sha256(identity_rows),
        "reservation_file_sha256": sha256_file(reservation_path),
        "reservation_path": _relative(reservation_path, root),
        "source_count": development_count,
        "consumed_non_development_count": _fresh_reserve_count(config),
    }


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(f"runtime_package_missing:{distribution}") from error


def _model_identity(
    root: Path,
    *,
    model_lock_path: str | Path = MODEL_LOCK_PATH,
    injected: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if injected is not None:
        identity = dict(injected)
        reject_forbidden_selection_fields(identity, path="model_runtime_identity")
        return identity
    lock_path = _resolve(model_lock_path, root)
    lock = load_yaml(lock_path)
    models = lock.get("models") if isinstance(lock, Mapping) else None
    matches = [
        item for item in models or []
        if isinstance(item, Mapping) and item.get("role") == "gliner2_base"
    ]
    if len(matches) != 1:
        raise RuntimeError("development_pilot_gliner2_base_lock_missing")
    model = dict(matches[0])
    local_path = _resolve(str(model.get("local_path", "")), root)
    files = model.get("files_sha256")
    if not local_path.is_dir() or not isinstance(files, Mapping) or not files:
        raise RuntimeError("development_pilot_model_missing")
    for relative_name in files:
        if not (local_path / str(relative_name)).is_file():
            raise RuntimeError(f"development_pilot_model_file_missing:{relative_name}")
    package = str(model.get("package") or "")
    actual_package_version = _package_version(package)
    if actual_package_version != str(model.get("package_version") or ""):
        raise RuntimeError("development_pilot_model_package_drift")
    return {
        "model_id": str(model.get("model_id")),
        "model_revision": str(model.get("revision")),
        "model_lock_entry_sha256": canonical_sha256(model),
        "gliner2_version": actual_package_version,
        "transformers_version": _package_version("transformers"),
        "torch_version": _package_version("torch"),
        "python_version": platform.python_version(),
        "device": "cuda",
        "precision": "float16",
    }


def _load_development_model_emitter(
    root: Path, *, model_lock_path: str | Path = MODEL_LOCK_PATH
) -> Callable[[str, str], Sequence[Mapping[str, Any]]]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("development_pilot_cuda_required")
    torch.use_deterministic_algorithms(True)
    lock = load_yaml(_resolve(model_lock_path, root))
    models = lock.get("models") if isinstance(lock, Mapping) else None
    matches = [
        item for item in models or []
        if isinstance(item, Mapping) and item.get("role") == "gliner2_base"
    ]
    if len(matches) != 1:
        raise RuntimeError("development_pilot_gliner2_base_lock_missing")
    model = dict(matches[0])
    backend: SemanticPredictionBackend = _load_backend(
        model,
        _resolve(str(model["local_path"]), root),
        runtime_device="cuda",
        use_fp16=True,
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


def _scientific_config(config: Mapping[str, Any], dataset: str) -> dict[str, Any]:
    bindings = config.get("frozen_v22_bindings", {})
    return {
        "specification_version": config.get("specification_version"),
        "dataset": dataset,
        "source_pool_count": _pool_contract(config, dataset)["source_count"],
        "entity_router": bindings.get("entity_router"),
        "extraction_rule_bindings": bindings.get("extraction_rule_bindings"),
        "selector_primitives": config.get("selector_primitives"),
        "development_gate": config.get("development_gate"),
        "forbidden_selection_inputs": config.get("forbidden_selection_inputs"),
    }


def _git_head(root: Path) -> str:
    """Capture HEAD as non-binding metadata; never inspect historical objects."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    value = completed.stdout.strip().lower()
    return value if _is_sha256(value) or len(value) == 40 else "unavailable"


def development_attempt_identity(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an attempt identity from scientific dependencies only."""

    root = Path(project_root).resolve()
    config = load_design_config(root)
    aggregate = validate_aggregate_df(project_root=root, dataset=dataset)
    reservation = load_development_reservation(project_root=root, dataset=dataset)
    model = _model_identity(root, injected=model_runtime_identity)
    implementation_hashes: dict[str, str] = {}
    for relative_path in SCIENTIFIC_IMPLEMENTATION_FILES:
        path = _resolve(relative_path, root)
        if not path.is_file():
            raise RuntimeError(f"scientific_implementation_missing:{relative_path}")
        actual_hash = sha256_file(path)
        implementation_hashes[relative_path.as_posix()] = (
            CRASH_ONLY_SCIENTIFIC_HASH_COMPATIBILITY
            .get(relative_path.as_posix(), {})
            .get(actual_hash, actual_hash)
        )
    bindings = config["frozen_v22_bindings"]["extraction_rule_bindings"]
    entity_policy_path = _resolve(str(bindings["entity_type_policy_path"]), root)
    if not entity_policy_path.is_file():
        raise RuntimeError("entity_policy_missing")
    identity = {
        "kind": "v23_lightweight_development_scientific_identity",
        "execution_revision": LIGHTWEIGHT_EXECUTION_REVISION,
        "specification_version": config["specification_version"],
        "design_manifest_sha256": _design_manifest_sha256(root),
        "dataset": dataset,
        "reservation_batch_id": reservation["reservation_batch_id"],
        "reservation_identity_sha256": reservation["reservation_identity_sha256"],
        "development_source_count": reservation["source_count"],
        "consumed_non_development_count": reservation[
            "consumed_non_development_count"
        ],
        "aggregate_df_manifest_sha256": aggregate["df_manifest_file_sha256"],
        "token_df_rows_file_sha256": aggregate["token_df_rows_file_sha256"],
        "scientific_config_sha256": canonical_sha256(
            _scientific_config(config, dataset)
        ),
        "entity_policy_file_sha256": sha256_file(entity_policy_path),
        "scientific_implementation_file_sha256": implementation_hashes,
        "scientific_function_source_sha256": {
            function.__name__: text_sha256(inspect.getsource(function))
            for function in (
                _default_source_selection,
                _normalize_selection,
                capacity_decision,
                _load_development_model_emitter,
            )
        },
        "model_runtime_identity": model,
    }
    reject_forbidden_selection_fields(identity, path="scientific_identity")
    identity_sha256 = canonical_sha256(identity)
    attempt_id = canonical_sha256(
        {
            "kind": "v23_lightweight_development_attempt",
            "scientific_identity_sha256": identity_sha256,
        }
    )
    return {
        "attempt_id": attempt_id,
        "scientific_identity": identity,
        "scientific_identity_sha256": identity_sha256,
        "aggregate": aggregate,
        "reservation": reservation,
        "git_head_metadata": _git_head(root),
    }


def _default_source_selection(
    source: Mapping[str, Any],
    *,
    token_df: Mapping[str, int],
    source_count: int,
    config: Mapping[str, Any],
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]],
    project_root: Path,
) -> dict[str, Any]:
    binding = config["frozen_v22_bindings"]["extraction_rule_bindings"]
    entity_policy = _resolve(str(binding["entity_type_policy_path"]), project_root)
    candidates = fresh_extract_candidates(
        source,
        model_emitter=model_emitter,
        entity_policy_path=str(entity_policy),
    )
    pair_candidates: list[dict[str, Any]] = []
    rejection_reasons: Counter[str] = Counter()
    for candidate in candidates:
        pairs, reasons = build_pair_candidates(
            source,
            candidate,
            token_df=token_df,
            source_count=source_count,
            token_df_prevalidated=True,
        )
        pair_candidates.extend(pairs)
        rejection_reasons.update(reasons)
    selected = select_top_three(pair_candidates)
    if not selected:
        rejection_reasons["fewer_than_three_diverse_pairs"] += 1
    return {
        "selected_pairs": selected,
        "rejection_reasons": sorted(rejection_reasons),
        "candidate_count": len(candidates),
        "pair_candidate_count": len(pair_candidates),
        "hard_gate_violation_count": 0,
    }


def _validate_selected_pair(
    pair: Mapping[str, Any],
    *,
    dataset: str,
    source: Mapping[str, Any],
    pair_order: int,
    design_manifest_sha256: str,
) -> dict[str, Any]:
    row = dict(pair)
    row["kind"] = "v23_selected_pair"
    row["specification_version"] = SPECIFICATION_VERSION
    row["protocol_revision_id"] = design_manifest_sha256
    row["dataset"] = dataset
    row["source_key"] = source["source_key"]
    row["source_hash"] = text_sha256(source["full_text"])
    row["normalized_text_hash"] = normalized_text_sha256(source["full_text"])
    row["source_order_rank"] = int(source["source_order_rank"], 16)
    row["pair_order"] = pair_order
    row = {key: row[key] for key in SELECTED_PAIR_FIELDS if key in row}
    reject_forbidden_selection_fields(row, path="selected_pair")
    if (
        set(row) != SELECTED_PAIR_FIELDS
        or row["kind"] != "v23_selected_pair"
        or row["specification_version"] != SPECIFICATION_VERSION
        or row["dataset"] != dataset
        or row["pair_order"] != pair_order
        or not _is_sha256(row["pair_id"])
        or not _is_sha256(row["fact_signature"])
        or not _is_sha256(row["relation_signature"])
        or not isinstance(row["rank_tuple"], list)
        or len(row["rank_tuple"]) != 17
    ):
        raise RuntimeError("selected_pair_schema_drift")
    return row


def _normalize_selection(
    raw: Mapping[str, Any],
    *,
    dataset: str,
    source: Mapping[str, Any],
    design_manifest_sha256: str,
) -> dict[str, Any]:
    reject_forbidden_selection_fields(raw, path="source_selection")
    raw_pairs = raw.get("selected_pairs")
    if not isinstance(raw_pairs, list):
        raise RuntimeError("source_selection_pairs_invalid")
    pairs = [
        _validate_selected_pair(
            pair,
            dataset=dataset,
            source=source,
            pair_order=index,
            design_manifest_sha256=design_manifest_sha256,
        )
        for index, pair in enumerate(raw_pairs)
    ]
    if len(pairs) not in {0, 3}:
        raise RuntimeError("source_selection_pair_count_invalid")
    reasons = raw.get("rejection_reasons", [])
    if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
        raise RuntimeError("source_selection_reasons_invalid")
    integer_fields = {
        "candidate_count": raw.get("candidate_count", 0),
        "pair_candidate_count": raw.get("pair_candidate_count", 0),
        "hard_gate_violation_count": raw.get("hard_gate_violation_count", 0),
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in integer_fields.values()
    ):
        raise RuntimeError("source_selection_count_invalid")
    return {
        "eligible": len(pairs) == 3,
        "selected_pairs": pairs,
        "rejection_reasons": sorted(set(reasons)),
        **integer_fields,
    }


def _source_result_payload_hash(row: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            key: value
            for key, value in row.items()
            if key not in {"completed_at", "source_result_sha256"}
        }
    )


def _validate_source_result(
    row: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    reservation_row: Mapping[str, Any],
    source_order_index: int,
) -> dict[str, Any]:
    reject_forbidden_selection_fields(row, path="source_result")
    if (
        set(row) != SOURCE_RESULT_FIELDS
        or row.get("kind") != "v23_lightweight_development_source_result"
        or row.get("attempt_id") != identity["attempt_id"]
        or row.get("scientific_identity_sha256")
        != identity["scientific_identity_sha256"]
        or row.get("dataset") != identity["scientific_identity"]["dataset"]
        or row.get("source_order_index") != source_order_index
        or row.get("source_key") != reservation_row["source_key"]
        or row.get("source_hash") != reservation_row["source_hash"]
        or row.get("normalized_text_hash")
        != reservation_row["normalized_text_hash"]
        or not isinstance(row.get("eligible"), bool)
        or row.get("eligible") != (len(row.get("selected_pairs", [])) == 3)
        or row.get("deterministic_rerun_hash_match") is not True
        or row.get("source_result_sha256") != _source_result_payload_hash(row)
    ):
        raise RuntimeError("development_source_result_drift")
    if (
        not isinstance(row.get("rejection_reasons"), list)
        or not all(isinstance(item, str) for item in row["rejection_reasons"])
        or any(
            isinstance(row.get(field), bool)
            or not isinstance(row.get(field), int)
            or row[field] < 0
            for field in (
                "candidate_count",
                "pair_candidate_count",
                "hard_gate_violation_count",
            )
        )
    ):
        raise RuntimeError("development_source_result_schema_drift")
    for index, pair in enumerate(row["selected_pairs"]):
        reject_forbidden_selection_fields(pair, path="source_result.selected_pair")
        if (
            set(pair) != SELECTED_PAIR_FIELDS
            or pair.get("pair_order") != index
            or pair.get("source_key") != row["source_key"]
            or pair.get("source_hash") != row["source_hash"]
            or pair.get("normalized_text_hash") != row["normalized_text_hash"]
        ):
            raise RuntimeError("development_source_pair_drift")
    return dict(row)


def _log_combination(n: int, k: int) -> float:
    if k < 0 or k > n:
        return -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def hypergeometric_survival(
    *, population: int, eligible: int, sample: int, observed_at_least: int
) -> float:
    if not 0 <= eligible <= population or not 0 <= sample <= population:
        raise ValueError("hypergeometric_parameters_invalid")
    lower = max(observed_at_least, 0, sample - (population - eligible))
    upper = min(sample, eligible)
    if lower > upper:
        return 0.0
    denominator = _log_combination(population, sample)
    logs = [
        _log_combination(eligible, value)
        + _log_combination(population - eligible, sample - value)
        - denominator
        for value in range(lower, upper + 1)
    ]
    maximum = max(logs)
    return math.exp(maximum) * math.fsum(math.exp(value - maximum) for value in logs)


def hypergeometric_eligible_lower_bound(
    *, population: int, sample: int, observed: int, alpha: float = 0.05
) -> int:
    if not 0.0 < alpha < 1.0 or not 0 <= observed <= sample <= population:
        raise ValueError("hypergeometric_boundary_input_invalid")
    low = observed
    high = population - sample + observed
    while low < high:
        middle = (low + high) // 2
        probability = hypergeometric_survival(
            population=population,
            eligible=middle,
            sample=sample,
            observed_at_least=observed,
        )
        if probability >= alpha:
            high = middle
        else:
            low = middle + 1
    return low


def capacity_decision(
    *,
    population: int,
    sample: int,
    observed_eligible: int,
    consumed_non_development: int,
    required_formal: int = 2_250,
) -> dict[str, Any]:
    if consumed_non_development < 0:
        raise ValueError("consumed_non_development_invalid")
    lower = hypergeometric_eligible_lower_bound(
        population=population, sample=sample, observed=observed_eligible
    )
    formal_lower = max(0, lower - observed_eligible - consumed_non_development)
    return {
        "population_N": population,
        "sample_n": sample,
        "observed_x": observed_eligible,
        "total_eligible_lower_K_L": lower,
        "consumed_non_development_c": consumed_non_development,
        "formal_eligible_lower": formal_lower,
        "required_formal": required_formal,
        "status": (
            "passed" if formal_lower >= required_formal else "failed_capacity_shortfall"
        ),
    }


def _development_paths(root: Path, dataset: str, attempt_id: str) -> dict[str, Path]:
    dataset_directory = _resolve(DEVELOPMENT_DIRECTORY / dataset, root)
    attempt_directory = dataset_directory / "attempts" / attempt_id
    return {
        "dataset_directory": dataset_directory,
        "attempt_directory": attempt_directory,
        "source_results": attempt_directory / "source_results",
        "execution_manifest": attempt_directory / "execution_manifest.json",
        "selected_pairs": attempt_directory / "selected_pairs.jsonl",
        "manifest": attempt_directory / "pilot_manifest.json",
        "checkpoint": attempt_directory / "checkpoint.json",
        "lock": dataset_directory / ".run.lock",
    }


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
            raise RuntimeError(f"jsonl_object_required:{path}")
        rows.append(value)
    return rows


def _write_or_validate_execution_manifest(
    path: Path, *, identity: Mapping[str, Any]
) -> None:
    expected = {
        "kind": "v23_lightweight_development_execution",
        "execution_revision": LIGHTWEIGHT_EXECUTION_REVISION,
        "attempt_id": identity["attempt_id"],
        "scientific_identity_sha256": identity["scientific_identity_sha256"],
        "scientific_identity": identity["scientific_identity"],
        "dataset": identity["scientific_identity"]["dataset"],
        "git_head_metadata": identity["git_head_metadata"],
        "external_calls_performed": 0,
    }
    if path.exists():
        actual = _read_json(path)
        actual_without_time = {
            key: value
            for key, value in actual.items()
            if key not in {"created_at", "git_head_metadata"}
        }
        expected_without_git = {
            key: value for key, value in expected.items() if key != "git_head_metadata"
        }
        if actual_without_time != expected_without_git:
            raise RuntimeError("development_execution_manifest_drift")
        return
    _write_new_json(path, {**expected, "created_at": utc_now()})


def _progress_line(
    completed: int, total: int, started_at: float, initial_completed: int
) -> str:
    elapsed = max(0.0, time.monotonic() - started_at)
    processed = max(1, completed - initial_completed)
    remaining = max(0.0, elapsed / processed * (total - completed))
    return (
        f"Completed {completed}/{total} | elapsed={elapsed:.1f}s "
        f"| eta={remaining:.1f}s"
    )


def _evaluate_source(
    source: Mapping[str, Any],
    *,
    source_selector: Callable[..., Mapping[str, Any]],
    token_df: Mapping[str, int],
    source_count: int,
    config: Mapping[str, Any],
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]],
    project_root: Path,
    dataset: str,
    design_manifest_sha256: str,
) -> dict[str, Any]:
    raw = source_selector(
        source,
        token_df=token_df,
        source_count=source_count,
        config=config,
        model_emitter=model_emitter,
        project_root=project_root,
    )
    if not isinstance(raw, Mapping):
        raise RuntimeError("source_selector_result_invalid")
    return _normalize_selection(
        raw,
        dataset=dataset,
        source=source,
        design_manifest_sha256=design_manifest_sha256,
    )


def run_development_pilot(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
    source_selector: Callable[..., Mapping[str, Any]] | None = None,
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run or resume one development dataset without governance authorizations."""

    root = Path(project_root).resolve()
    identity = development_attempt_identity(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    paths = _development_paths(root, dataset, str(identity["attempt_id"]))
    with exclusive_lock(paths["lock"]):
        if paths["manifest"].exists():
            return validate_development_pilot(
                project_root=root,
                dataset=dataset,
                model_runtime_identity=model_runtime_identity,
            )
        paths["source_results"].mkdir(parents=True, exist_ok=True)
        _write_or_validate_execution_manifest(paths["execution_manifest"], identity=identity)
        config = load_design_config(root)
        pool = _pool_contract(config, dataset)
        token_df = _load_token_df(
            _aggregate_paths(root, dataset)["rows"], source_count=int(pool["source_count"])
        )
        reservation_rows = identity["reservation"]["rows"]
        total = len(reservation_rows)
        completed = 0
        for index, reservation_row in enumerate(reservation_rows):
            result_path = paths["source_results"] / f"{index:06d}.json"
            if not result_path.exists():
                continue
            _validate_source_result(
                _read_json(result_path),
                identity=identity,
                reservation_row=reservation_row,
                source_order_index=index,
            )
            completed += 1
        initial_completed = completed
        print(f"Resuming {dataset}: Completed {completed}/{total}", flush=True)
        if completed == total:
            return _finalize_development_pilot(root=root, identity=identity, paths=paths)
        selector = source_selector or _default_source_selection
        if model_emitter is None:
            if source_selector is None:
                print("Loading GLiNER on CUDA...", flush=True)
                emitter = _load_development_model_emitter(root)
            else:
                emitter = lambda _text, _dataset: ()
        else:
            emitter = model_emitter
        started_at = time.monotonic()
        with FrozenSourcePoolReader(
            project_root=root, dataset=dataset, pool=pool
        ) as reader:
            for index, reservation_row in enumerate(reservation_rows):
                result_path = paths["source_results"] / f"{index:06d}.json"
                if result_path.exists():
                    continue
                source = reader.read_development_source(reservation_row)
                first = _evaluate_source(
                    source,
                    source_selector=selector,
                    token_df=token_df,
                    source_count=int(pool["source_count"]),
                    config=config,
                    model_emitter=emitter,
                    project_root=root,
                    dataset=dataset,
                    design_manifest_sha256=identity["scientific_identity"][
                        "design_manifest_sha256"
                    ],
                )
                second = _evaluate_source(
                    source,
                    source_selector=selector,
                    token_df=token_df,
                    source_count=int(pool["source_count"]),
                    config=config,
                    model_emitter=emitter,
                    project_root=root,
                    dataset=dataset,
                    design_manifest_sha256=identity["scientific_identity"][
                        "design_manifest_sha256"
                    ],
                )
                if canonical_sha256(first) != canonical_sha256(second):
                    raise RuntimeError("development_selector_nondeterministic")
                result: dict[str, Any] = {
                    "kind": "v23_lightweight_development_source_result",
                    "design_manifest_sha256": identity["scientific_identity"][
                        "design_manifest_sha256"
                    ],
                    "scientific_identity_sha256": identity[
                        "scientific_identity_sha256"
                    ],
                    "attempt_id": identity["attempt_id"],
                    "dataset": dataset,
                    "source_order_index": index,
                    "source_key": reservation_row["source_key"],
                    "source_hash": reservation_row["source_hash"],
                    "normalized_text_hash": reservation_row["normalized_text_hash"],
                    **first,
                    "deterministic_rerun_hash_match": True,
                    "completed_at": utc_now(),
                }
                result["source_result_sha256"] = _source_result_payload_hash(result)
                _validate_source_result(
                    result,
                    identity=identity,
                    reservation_row=reservation_row,
                    source_order_index=index,
                )
                _write_new_json(result_path, result)
                completed += 1
                if completed % 10 == 0 or completed == total:
                    print(
                        _progress_line(
                            completed, total, started_at, initial_completed
                        ),
                        flush=True,
                    )
        return _finalize_development_pilot(root=root, identity=identity, paths=paths)


def _finalize_development_pilot(
    *, root: Path, identity: Mapping[str, Any], paths: Mapping[str, Path]
) -> dict[str, Any]:
    reservation_rows = identity["reservation"]["rows"]
    results = [
        _validate_source_result(
            _read_json(paths["source_results"] / f"{index:06d}.json"),
            identity=identity,
            reservation_row=reservation_row,
            source_order_index=index,
        )
        for index, reservation_row in enumerate(reservation_rows)
    ]
    pairs = [pair for result in results for pair in result["selected_pairs"]]
    _write_or_validate_jsonl(paths["selected_pairs"], pairs)
    eligible_count = sum(1 for result in results if result["eligible"])
    gate = capacity_decision(
        population=int(identity["aggregate"]["source_count"]),
        sample=len(results),
        observed_eligible=eligible_count,
        consumed_non_development=int(
            identity["reservation"]["consumed_non_development_count"]
        ),
    )
    hard_gate_violations = sum(
        int(result["hard_gate_violation_count"]) for result in results
    )
    if hard_gate_violations:
        gate = {**gate, "status": "failed_hard_gate_violation"}
    status = str(gate["status"])
    manifest = {
        "kind": "v23_lightweight_development_pilot_manifest",
        "execution_revision": LIGHTWEIGHT_EXECUTION_REVISION,
        "attempt_id": identity["attempt_id"],
        "scientific_identity_sha256": identity["scientific_identity_sha256"],
        "design_manifest_sha256": identity["scientific_identity"][
            "design_manifest_sha256"
        ],
        "dataset": identity["scientific_identity"]["dataset"],
        "source_count": len(results),
        "eligible_source_count": eligible_count,
        "selected_pair_count": len(pairs),
        "hard_gate_violation_count": hard_gate_violations,
        "capacity_gate": gate,
        "source_results_identity_sha256": canonical_sha256(
            [result["source_result_sha256"] for result in results]
        ),
        "selected_pairs_file_sha256": sha256_file(paths["selected_pairs"]),
        "status": status,
        "completed_at": utc_now(),
        "external_calls_performed": 0,
    }
    checkpoint = {
        "kind": "v23_lightweight_development_checkpoint",
        "attempt_id": identity["attempt_id"],
        "scientific_identity_sha256": identity["scientific_identity_sha256"],
        "dataset": identity["scientific_identity"]["dataset"],
        "completed_source_count": len(results),
        "terminal_status": status,
        "pilot_manifest_sha256": canonical_sha256(manifest),
        "completed_at": manifest["completed_at"],
    }
    _write_new_json(paths["manifest"], manifest)
    _write_new_json(paths["checkpoint"], checkpoint)
    return validate_development_pilot(
        project_root=root,
        dataset=str(identity["scientific_identity"]["dataset"]),
        model_runtime_identity=identity["scientific_identity"][
            "model_runtime_identity"
        ],
    )


def validate_development_pilot(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the terminal attempt for the current scientific identity."""

    root = Path(project_root).resolve()
    identity = development_attempt_identity(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    paths = _development_paths(root, dataset, str(identity["attempt_id"]))
    required = (
        paths["execution_manifest"],
        paths["selected_pairs"],
        paths["manifest"],
        paths["checkpoint"],
    )
    if not all(path.is_file() for path in required):
        raise RuntimeError("development_pilot_incomplete")
    _write_or_validate_execution_manifest(paths["execution_manifest"], identity=identity)
    reservation_rows = identity["reservation"]["rows"]
    expected_names = {f"{index:06d}.json" for index in range(len(reservation_rows))}
    actual_names = {
        path.name for path in paths["source_results"].glob("*.json") if path.is_file()
    }
    if actual_names != expected_names:
        raise RuntimeError("development_source_result_set_drift")
    results = [
        _validate_source_result(
            _read_json(paths["source_results"] / f"{index:06d}.json"),
            identity=identity,
            reservation_row=reservation_row,
            source_order_index=index,
        )
        for index, reservation_row in enumerate(reservation_rows)
    ]
    expected_pairs = [pair for result in results for pair in result["selected_pairs"]]
    if _read_jsonl(paths["selected_pairs"]) != expected_pairs:
        raise RuntimeError("development_selected_pairs_drift")
    eligible_count = sum(1 for result in results if result["eligible"])
    hard_gate_violations = sum(
        int(result["hard_gate_violation_count"]) for result in results
    )
    expected_gate = capacity_decision(
        population=int(identity["aggregate"]["source_count"]),
        sample=len(results),
        observed_eligible=eligible_count,
        consumed_non_development=int(
            identity["reservation"]["consumed_non_development_count"]
        ),
    )
    if hard_gate_violations:
        expected_gate = {**expected_gate, "status": "failed_hard_gate_violation"}
    manifest = _read_json(paths["manifest"])
    if (
        manifest.get("kind") != "v23_lightweight_development_pilot_manifest"
        or manifest.get("execution_revision") != LIGHTWEIGHT_EXECUTION_REVISION
        or manifest.get("attempt_id") != identity["attempt_id"]
        or manifest.get("scientific_identity_sha256")
        != identity["scientific_identity_sha256"]
        or manifest.get("dataset") != dataset
        or manifest.get("source_count") != len(results)
        or manifest.get("eligible_source_count") != eligible_count
        or manifest.get("selected_pair_count") != len(expected_pairs)
        or manifest.get("hard_gate_violation_count") != hard_gate_violations
        or manifest.get("capacity_gate") != expected_gate
        or manifest.get("status") != expected_gate["status"]
        or manifest.get("source_results_identity_sha256")
        != canonical_sha256(
            [result["source_result_sha256"] for result in results]
        )
        or manifest.get("selected_pairs_file_sha256")
        != sha256_file(paths["selected_pairs"])
        or manifest.get("external_calls_performed") != 0
    ):
        raise RuntimeError("development_pilot_manifest_drift")
    checkpoint = _read_json(paths["checkpoint"])
    if checkpoint != {
        "kind": "v23_lightweight_development_checkpoint",
        "attempt_id": identity["attempt_id"],
        "scientific_identity_sha256": identity["scientific_identity_sha256"],
        "dataset": dataset,
        "completed_source_count": len(results),
        "terminal_status": manifest["status"],
        "pilot_manifest_sha256": canonical_sha256(manifest),
        "completed_at": manifest["completed_at"],
    }:
        raise RuntimeError("development_checkpoint_drift")
    return {
        "status": manifest["status"],
        "dataset": dataset,
        "attempt_id": identity["attempt_id"],
        "completed_source_count": len(results),
        "eligible_source_count": eligible_count,
        "selected_pair_count": len(expected_pairs),
        "capacity_gate": expected_gate,
        "attempt_directory": _relative(paths["attempt_directory"], root),
        "external_calls_performed": 0,
    }


def validate_development_pilot_group(
    *,
    project_root: str | Path = ".",
    model_runtime_identities: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate all three datasets only when this explicit group command is used."""

    root = Path(project_root).resolve()
    validations: list[dict[str, Any]] = []
    reservations: dict[str, dict[str, Any]] = {}
    for dataset in DATASET_ORDER:
        validations.append(
            validate_development_pilot(
                project_root=root,
                dataset=dataset,
                model_runtime_identity=(model_runtime_identities or {}).get(dataset),
            )
        )
        reservations[dataset] = load_development_reservation(
            project_root=root, dataset=dataset
        )
    for left_index, left in enumerate(DATASET_ORDER):
        left_rows = reservations[left]["rows"]
        left_source_hashes = {row["source_hash"] for row in left_rows}
        left_text_hashes = {row["normalized_text_hash"] for row in left_rows}
        for right in DATASET_ORDER[left_index + 1 :]:
            right_rows = reservations[right]["rows"]
            if left_source_hashes & {row["source_hash"] for row in right_rows}:
                raise RuntimeError("development_cross_dataset_source_overlap")
            if left_text_hashes & {row["normalized_text_hash"] for row in right_rows}:
                raise RuntimeError("development_cross_dataset_text_overlap")
    return {
        "status": (
            "passed"
            if all(item["status"] == "passed" for item in validations)
            else "failed"
        ),
        "datasets": validations,
        "cross_dataset_source_and_text_hash_overlap": 0,
        "external_calls_performed": 0,
    }


def _status_for_dataset(root: Path, dataset: str) -> dict[str, Any]:
    aggregate_paths = _aggregate_paths(root, dataset)
    dataset_directory = _development_paths(root, dataset, "unused")[
        "dataset_directory"
    ]
    attempts_directory = dataset_directory / "attempts"
    attempts = sorted(
        [path for path in attempts_directory.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
    ) if attempts_directory.is_dir() else []
    latest: dict[str, Any] | None = None
    if attempts:
        path = attempts[-1]
        manifest_path = path / "pilot_manifest.json"
        source_results = path / "source_results"
        manifest = _read_json(manifest_path) if manifest_path.is_file() else None
        latest = {
            "attempt_id": path.name,
            "completed_source_count": len(list(source_results.glob("*.json")))
            if source_results.is_dir()
            else 0,
            "terminal_status": manifest.get("status") if manifest else None,
        }
    lock_path = dataset_directory / ".run.lock"
    lock_pid = _read_lock_pid(lock_path) if lock_path.exists() else None
    return {
        "dataset": dataset,
        "aggregate_df_present": aggregate_paths["manifest"].is_file()
        and aggregate_paths["rows"].is_file(),
        "attempt_count": len(attempts),
        "latest_attempt": latest,
        "run_lock": {
            "present": lock_path.exists(),
            "pid": lock_pid,
            "active": lock_pid is not None and _pid_running(lock_pid),
        },
    }


def status(
    *, project_root: str | Path = ".", dataset: str | None = None
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if dataset is not None and dataset not in DATASET_ORDER:
        raise ValueError("dataset_invalid")
    datasets = (dataset,) if dataset is not None else DATASET_ORDER
    return {
        "kind": "v23_lightweight_development_status",
        "execution_revision": LIGHTWEIGHT_EXECUTION_REVISION,
        "datasets": [_status_for_dataset(root, item) for item in datasets],
        "historical_artifacts_preserved": True,
        "authorization_required_for_local_development_run": False,
        "external_calls_performed": 0,
    }
