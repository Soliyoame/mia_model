"""Resumable offline runner for the v23 fact-layer revision."""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..attack.restoration_first_v23 import (
    canonical_json,
    canonical_sha256,
    normalize_text,
    reject_forbidden_selection_fields,
)
from ..attack.restoration_first_v23_fact_layer import (
    FACT_LAYER_SPECIFICATION_VERSION,
    STRUCTURED_TYPES,
    extract_fact_candidates,
    validate_fact_row,
)
from ..utils.hash import sha256_file
from ..utils.io import load_yaml
from .restoration_first_v23 import (
    ARTIFACT_ROOT,
    DATASET_ORDER,
    DESIGN_MANIFEST,
    FrozenSourcePoolReader,
    _load_development_model_emitter,
    _model_identity,
    _pool_contract,
    _read_json,
    _resolve,
    _git_head,
    capacity_decision,
    exclusive_lock,
    load_development_reservation,
    load_design_config,
)


FACT_CONFIG_PATH = Path("configs/restoration_first_v23_fact_layer_r1.yaml")
FACT_LAYER_ROOT = ARTIFACT_ROOT / "selection/development_fact_layer"
FACT_IMPLEMENTATION_FILES = (
    Path("src/attack/restoration_first_v23_fact_layer.py"),
    Path("src/prepare/restoration_first_v23_fact_layer.py"),
    FACT_CONFIG_PATH,
)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_fact_config(root: Path) -> dict[str, Any]:
    config = load_yaml(_resolve(FACT_CONFIG_PATH, root))
    if not isinstance(config, Mapping):
        raise RuntimeError("fact_layer_config_invalid")
    expected = {
        "protocol_version": "pcv-mia-v23",
        "method_version": "pcv-restoration-first-v23-fact-layer",
        "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
    }
    if any(config.get(key) != value for key, value in expected.items()):
        raise RuntimeError("fact_layer_config_identity_drift")
    if config.get("external_calls_performed") != 0:
        raise RuntimeError("fact_layer_external_calls_forbidden")
    return dict(config)


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


def _write_or_validate_json(
    path: Path,
    value: Mapping[str, Any],
    *,
    ignored_keys: frozenset[str] = frozenset({"created_at"}),
) -> None:
    """Atomically create an immutable JSON artifact or verify an existing one."""

    expected = dict(value)
    if path.exists():
        actual = _read_json(path)
        actual_cmp = {key: item for key, item in actual.items() if key not in ignored_keys}
        expected_cmp = {key: item for key, item in expected.items() if key not in ignored_keys}
        if actual_cmp != expected_cmp:
            raise RuntimeError(f"fact_layer_artifact_identity_drift:{path}")
        return
    _atomic_write(path, (canonical_json(expected) + "\n").encode("utf-8"))


def _write_or_validate_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    payload = "".join(canonical_json(dict(row)) + "\n" for row in rows).encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError(f"fact_layer_artifact_identity_drift:{path}")
        return
    _atomic_write(path, payload)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise RuntimeError(f"fact_layer_jsonl_partial:{path}")
    rows: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"fact_layer_json_object_required:{path}")
        rows.append(value)
    return rows


def _fact_paths(root: Path, dataset: str, attempt_id: str) -> dict[str, Path]:
    directory = _resolve(FACT_LAYER_ROOT / dataset, root)
    attempt = directory / "attempts" / attempt_id
    return {
        "dataset_directory": directory,
        "attempt_directory": attempt,
        "source_results": attempt / "source_results",
        "facts": attempt / "facts.jsonl",
        "diagnostics": attempt / "fact_diagnostics.jsonl",
        "checkpoint": attempt / "checkpoint.json",
        "manifest": attempt / "manifest.json",
        "selection": attempt / "selected_pairs.jsonl",
        "selection_manifest": attempt / "selection_manifest.json",
        "pilot_manifest": attempt / "pilot_manifest.json",
        "lock": directory / ".fact-extraction.lock",
    }


def _source_order_sort_key(value: Any) -> int:
    """Normalize the frozen source-order rank for deterministic sorting."""

    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value or "")
    if not text:
        return -1
    try:
        return int(text, 16)
    except ValueError:
        return -1


def _fact_design_manifest_sha256(root: Path, fact_config: Mapping[str, Any]) -> str:
    base_manifest = _resolve(DESIGN_MANIFEST, root)
    return canonical_sha256(
        {
            "kind": "pcv_v23_fact_layer_design_manifest",
            "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
            "base_design_manifest_sha256": sha256_file(base_manifest),
            "fact_config_sha256": sha256_file(_resolve(FACT_CONFIG_PATH, root)),
            "fact_config": dict(fact_config),
        }
    )


def fact_layer_attempt_identity(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if dataset not in DATASET_ORDER:
        raise ValueError("fact_layer_dataset_invalid")
    fact_config = _load_fact_config(root)
    base_config = load_design_config(root)
    pool = _pool_contract(base_config, dataset)
    reservation = load_development_reservation(project_root=root, dataset=dataset)
    model = _model_identity(root, injected=model_runtime_identity)
    entity_policy = _resolve(
        str(base_config["frozen_v22_bindings"]["extraction_rule_bindings"]["entity_type_policy_path"]),
        root,
    )
    implementation_hashes = {
        path.as_posix(): sha256_file(_resolve(path, root))
        for path in FACT_IMPLEMENTATION_FILES
    }
    identity = {
        "kind": "v23_fact_layer_scientific_identity",
        "execution_revision": FACT_LAYER_SPECIFICATION_VERSION,
        "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "design_manifest_sha256": _fact_design_manifest_sha256(root, fact_config),
        "dataset": dataset,
        "development_source_count": reservation["source_count"],
        "reservation_batch_id": reservation["reservation_batch_id"],
        "reservation_identity_sha256": reservation["reservation_identity_sha256"],
        "source_pool_database_sha256": str(pool["database_sha256"]),
        "source_order_file_sha256": str(pool["source_order_file_sha256"]),
        "entity_policy_file_sha256": sha256_file(entity_policy),
        "fact_config_sha256": sha256_file(_resolve(FACT_CONFIG_PATH, root)),
        "fact_layer_implementation_file_sha256": implementation_hashes,
        "model_runtime_identity": model,
        "external_calls_performed": 0,
    }
    reject_forbidden_selection_fields(identity, path="fact_layer_identity")
    identity_sha256 = canonical_sha256(identity)
    attempt_id = canonical_sha256(
        {
            "kind": "v23_fact_layer_attempt",
            "scientific_identity_sha256": identity_sha256,
        }
    )
    return {
        "attempt_id": attempt_id,
        "scientific_identity": identity,
        "scientific_identity_sha256": identity_sha256,
        "reservation": reservation,
        "pool": pool,
        "fact_config": fact_config,
        "git_head_metadata": _git_head(root),
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
    reject_forbidden_selection_fields(row, path="fact_layer_source_result")
    if (
        row.get("kind") != "v23_fact_layer_source_result"
        or row.get("attempt_id") != identity["attempt_id"]
        or row.get("scientific_identity_sha256") != identity["scientific_identity_sha256"]
        or row.get("dataset") != identity["scientific_identity"]["dataset"]
        or row.get("source_order_index") != source_order_index
        or row.get("source_key") != reservation_row["source_key"]
        or row.get("source_hash") != reservation_row["source_hash"]
        or row.get("normalized_text_hash") != reservation_row["normalized_text_hash"]
        or row.get("deterministic_rerun_hash_match") is not True
        or row.get("external_calls_performed") != 0
        or row.get("source_result_sha256") != _source_result_payload_hash(row)
    ):
        raise RuntimeError("fact_layer_source_result_drift")
    facts = row.get("facts")
    diagnostics = row.get("diagnostics")
    if not isinstance(facts, list) or not isinstance(diagnostics, list):
        raise RuntimeError("fact_layer_source_result_rows_invalid")
    for item in facts:
        validate_fact_row(item)
    if any(not item["fact_valid"] for item in facts):
        raise RuntimeError("fact_layer_source_result_invalid_fact")
    for item in diagnostics:
        validate_fact_row(item)
    fact_ids = {item["fact_signature"] for item in facts}
    diagnostic_ids = {item["fact_signature"] for item in diagnostics if item["fact_signature"]}
    if not fact_ids.issubset(diagnostic_ids):
        raise RuntimeError("fact_layer_fact_not_in_diagnostics")
    return dict(row)


def _fact_layer_df_diagnostics_metadata() -> dict[str, Any]:
    """Describe the deliberately unused legacy DF channel.

    The independent fact layer must not read r6 aggregate-DF artifacts.  The
    corresponding diagnostic fields remain in each candidate row as ``None``
    when no local DF table is supplied, and therefore never affect P0.
    """

    return {
        "status": "not_used",
        "reason": "fact_layer_does_not_consume_r6_aggregate_df",
        "external_calls_performed": 0,
    }


def _progress_line(completed: int, total: int, started_at: float, initial: int) -> str:
    elapsed = max(0.0, time.monotonic() - started_at)
    processed = max(1, completed - initial)
    eta = elapsed / processed * max(0, total - completed)
    return f"Completed {completed}/{total} | elapsed={elapsed:.1f}s | eta={eta:.1f}s"


def _write_execution_metadata(path: Path, identity: Mapping[str, Any]) -> None:
    expected = {
        "kind": "v23_fact_layer_execution",
        "attempt_id": identity["attempt_id"],
        "scientific_identity_sha256": identity["scientific_identity_sha256"],
        "scientific_identity": identity["scientific_identity"],
        "dataset": identity["scientific_identity"]["dataset"],
        "git_head_metadata": identity["git_head_metadata"],
        "external_calls_performed": 0,
    }
    path = path.parent / "execution_manifest.json"
    if path.exists():
        actual = _read_json(path)
        # Git HEAD is provenance metadata only.  It must not make a resumable
        # attempt drift when unrelated commits are made during development.
        actual_cmp = {
            key: actual.get(key)
            for key in expected
            if key != "git_head_metadata"
        }
        expected_cmp = {
            key: value for key, value in expected.items()
            if key != "git_head_metadata"
        }
        if actual_cmp != expected_cmp:
            raise RuntimeError("fact_layer_execution_manifest_drift")
        return
    _write_new_json(path, {**expected, "created_at": _utc_now()})


def extract_facts(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    identity = fact_layer_attempt_identity(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    paths = _fact_paths(root, dataset, identity["attempt_id"])
    with exclusive_lock(paths["lock"]):
        if paths["manifest"].exists():
            if paths["checkpoint"].exists():
                return validate_facts(
                    project_root=root,
                    dataset=dataset,
                    model_runtime_identity=model_runtime_identity,
                )
            # A crash between the immutable manifest and checkpoint writes is
            # recoverable from the source-level results without reloading CUDA.
            paths["source_results"].mkdir(parents=True, exist_ok=True)
            base_config = load_design_config(root)
            pool = _pool_contract(base_config, dataset)
            aggregate_metadata = _fact_layer_df_diagnostics_metadata()
            return _finalize_facts(root, identity, paths, aggregate_metadata)
        paths["source_results"].mkdir(parents=True, exist_ok=True)
        _write_execution_metadata(paths["attempt_directory"] / "execution_manifest.json", identity)
        base_config = load_design_config(root)
        pool = _pool_contract(base_config, dataset)
        entity_policy = _resolve(
            str(base_config["frozen_v22_bindings"]["extraction_rule_bindings"]["entity_type_policy_path"]),
            root,
        )
        token_df = None
        aggregate_metadata = _fact_layer_df_diagnostics_metadata()
        reservation_rows = identity["reservation"]["rows"]
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
        total = len(reservation_rows)
        print(f"Resuming {dataset}: Completed {completed}/{total}", flush=True)
        if completed == total:
            return _finalize_facts(root, identity, paths, aggregate_metadata)
        emitter = model_emitter
        if emitter is None:
            print("Loading GLiNER on CUDA...", flush=True)
            emitter = _load_development_model_emitter(root)
        started_at = time.monotonic()
        initial = completed
        with FrozenSourcePoolReader(project_root=root, dataset=dataset, pool=pool) as reader:
            for index, reservation_row in enumerate(reservation_rows):
                result_path = paths["source_results"] / f"{index:06d}.json"
                if result_path.exists():
                    continue
                source = reader.read_development_source(reservation_row)
                first = extract_fact_candidates(
                    source,
                    model_emitter=emitter,
                    entity_policy_path=str(entity_policy),
                    token_df=token_df,
                    source_count=int(pool["source_count"]),
                )
                second = extract_fact_candidates(
                    source,
                    model_emitter=emitter,
                    entity_policy_path=str(entity_policy),
                    token_df=token_df,
                    source_count=int(pool["source_count"]),
                )
                if canonical_sha256(first) != canonical_sha256(second):
                    raise RuntimeError("fact_layer_nondeterministic")
                result = {
                    "kind": "v23_fact_layer_source_result",
                    "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
                    "attempt_id": identity["attempt_id"],
                    "scientific_identity_sha256": identity["scientific_identity_sha256"],
                    "dataset": dataset,
                    "source_order_index": index,
                    "source_key": reservation_row["source_key"],
                    "source_hash": reservation_row["source_hash"],
                    "normalized_text_hash": reservation_row["normalized_text_hash"],
                    **first,
                    "deterministic_rerun_hash_match": True,
                    "completed_at": _utc_now(),
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
                    print(_progress_line(completed, total, started_at, initial), flush=True)
        return _finalize_facts(root, identity, paths, aggregate_metadata)


def _finalize_facts(
    root: Path,
    identity: Mapping[str, Any],
    paths: Mapping[str, Path],
    aggregate_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    source_files = sorted(paths["source_results"].glob("*.json"))
    if len(source_files) != identity["reservation"]["source_count"]:
        raise RuntimeError("fact_layer_source_result_count_incomplete")
    facts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    p0_ready = 0
    for path in source_files:
        row = _read_json(path)
        _validate_source_result(
            row,
            identity=identity,
            reservation_row=identity["reservation"]["rows"][int(path.stem)],
            source_order_index=int(path.stem),
        )
        facts.extend(row["facts"])
        diagnostics.extend(row["diagnostics"])
        p0_ready += int(row.get("p0_ready_count", 0))
        for reason, count in row.get("rejection_reason_counts", {}).items():
            reason_counts[str(reason)] += int(count)
    facts.sort(
        key=lambda row: (
            _source_order_sort_key(row["source_order_rank"]),
            row["source_key"],
            row["fact_signature"],
        )
    )
    diagnostics.sort(
        key=lambda row: (
            _source_order_sort_key(row["source_order_rank"]),
            row["source_key"],
            tuple(row["proposition_span"]),
            tuple(row["original_span"]),
            row["effective_type"],
        )
    )
    _write_or_validate_jsonl(paths["facts"], facts)
    _write_or_validate_jsonl(paths["diagnostics"], diagnostics)
    manifest = {
        "kind": "v23_fact_layer_manifest",
        "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "attempt_id": identity["attempt_id"],
        "scientific_identity_sha256": identity["scientific_identity_sha256"],
        "design_manifest_sha256": identity["scientific_identity"]["design_manifest_sha256"],
        "dataset": identity["scientific_identity"]["dataset"],
        "completed_source_count": len(source_files),
        "candidate_count": len(diagnostics),
        "fact_valid_count": len(facts),
        "p0_ready_count": p0_ready,
        "structured_diagnostic_count": sum(
            row["effective_type"] in STRUCTURED_TYPES for row in diagnostics
        ),
        "rejection_reason_counts": dict(sorted(reason_counts.items())),
        "facts_file_sha256": sha256_file(paths["facts"]),
        "diagnostics_file_sha256": sha256_file(paths["diagnostics"]),
        "aggregate_df_metadata": dict(aggregate_metadata),
        "external_calls_performed": 0,
        "status": "passed",
        "created_at": _utc_now(),
    }
    _write_or_validate_json(paths["manifest"], manifest)
    checkpoint = {
        "kind": "v23_fact_layer_checkpoint",
        "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "attempt_id": identity["attempt_id"],
        "dataset": identity["scientific_identity"]["dataset"],
        "status": "passed",
        "completed_source_count": len(source_files),
        "facts_file_sha256": manifest["facts_file_sha256"],
        "diagnostics_file_sha256": manifest["diagnostics_file_sha256"],
        "external_calls_performed": 0,
        "ledger_mutation": False,
        "created_at": _utc_now(),
    }
    _write_or_validate_json(paths["checkpoint"], checkpoint)
    return {
        "status": "passed",
        "dataset": identity["scientific_identity"]["dataset"],
        "attempt_id": identity["attempt_id"],
        "attempt_directory": str(paths["attempt_directory"].relative_to(root)),
        "completed_source_count": len(source_files),
        "candidate_count": len(diagnostics),
        "fact_valid_count": len(facts),
        "p0_ready_count": p0_ready,
        "structured_diagnostic_count": manifest["structured_diagnostic_count"],
        "external_calls_performed": 0,
    }


def validate_facts(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    identity = fact_layer_attempt_identity(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    paths = _fact_paths(root, dataset, identity["attempt_id"])
    if not paths["manifest"].is_file() or not paths["checkpoint"].is_file():
        raise RuntimeError("fact_layer_artifact_missing")
    manifest = _read_json(paths["manifest"])
    if (
        manifest.get("kind") != "v23_fact_layer_manifest"
        or manifest.get("attempt_id") != identity["attempt_id"]
        or manifest.get("scientific_identity_sha256") != identity["scientific_identity_sha256"]
        or manifest.get("facts_file_sha256") != sha256_file(paths["facts"])
        or manifest.get("diagnostics_file_sha256") != sha256_file(paths["diagnostics"])
        or manifest.get("external_calls_performed") != 0
    ):
        raise RuntimeError("fact_layer_manifest_drift")
    facts = [validate_fact_row(row) for row in _read_jsonl(paths["facts"])]
    diagnostics = [validate_fact_row(row) for row in _read_jsonl(paths["diagnostics"])]
    if any(not row["fact_valid"] for row in facts):
        raise RuntimeError("fact_layer_invalid_fact_in_canonical_file")
    if manifest.get("completed_source_count") != identity["reservation"]["source_count"]:
        raise RuntimeError("fact_layer_source_count_drift")
    reservation_by_key = {
        str(row["source_key"]): row for row in identity["reservation"]["rows"]
    }
    for row in [*facts, *diagnostics]:
        reservation_row = reservation_by_key.get(str(row["source_key"]))
        if (
            reservation_row is None
            or row["source_hash"] != reservation_row["source_hash"]
            or row["normalized_text_hash"] != reservation_row["normalized_text_hash"]
        ):
            raise RuntimeError("fact_layer_source_identity_drift")
    checkpoint = _read_json(paths["checkpoint"])
    if (
        checkpoint.get("kind") != "v23_fact_layer_checkpoint"
        or checkpoint.get("status") != "passed"
        or checkpoint.get("attempt_id") != identity["attempt_id"]
        or checkpoint.get("completed_source_count") != manifest["completed_source_count"]
        or checkpoint.get("facts_file_sha256") != manifest["facts_file_sha256"]
        or checkpoint.get("diagnostics_file_sha256") != manifest["diagnostics_file_sha256"]
        or checkpoint.get("ledger_mutation") is not False
        or checkpoint.get("external_calls_performed") != 0
    ):
        raise RuntimeError("fact_layer_checkpoint_drift")
    if manifest.get("fact_valid_count") != len(facts) or manifest.get("candidate_count") != len(diagnostics):
        raise RuntimeError("fact_layer_count_drift")
    if manifest.get("p0_ready_count") != sum(bool(row["p0_ready"]) for row in facts):
        raise RuntimeError("fact_layer_p0_count_drift")
    return {
        "status": "passed",
        "dataset": dataset,
        "attempt_id": identity["attempt_id"],
        "completed_source_count": manifest["completed_source_count"],
        "candidate_count": len(diagnostics),
        "fact_valid_count": len(facts),
        "p0_ready_count": sum(bool(row["p0_ready"]) for row in facts),
        "external_calls_performed": 0,
    }


def select_pairs(
    *, project_root: str | Path = ".", dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select deterministic P0 pairs from a validated fact artifact."""

    root = Path(project_root).resolve()
    fact_status = validate_facts(
        project_root=root, dataset=dataset, model_runtime_identity=model_runtime_identity
    )
    identity = fact_layer_attempt_identity(
        project_root=root, dataset=dataset, model_runtime_identity=model_runtime_identity
    )
    paths = _fact_paths(root, dataset, identity["attempt_id"])
    facts = [row for row in _read_jsonl(paths["facts"]) if row.get("p0_ready")]
    candidates: list[dict[str, Any]] = []
    for fact in facts:
        start, end = fact["original_span"]
        for replacement in fact["replacement_candidates"]:
            claim = (
                fact["proposition_text"][:start]
                + replacement
                + fact["proposition_text"][end:]
            )
            pair_id = canonical_sha256(
                {
                    "kind": "v23_fact_layer_pair",
                    "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
                    "fact_signature": fact["fact_signature"],
                    "original_value": normalize_text(fact["original_value"]),
                    "counterfactual_value": normalize_text(replacement),
                }
            )
            candidates.append(
                {
                    "kind": "v23_fact_layer_pair",
                    "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
                    "dataset": dataset,
                    "source_key": fact["source_key"],
                    "source_order_rank": fact["source_order_rank"],
                    "source_hash": fact["source_hash"],
                    "normalized_text_hash": fact["normalized_text_hash"],
                    "fact_signature": fact["fact_signature"],
                    "relation_signature": fact["relation_signature"],
                    "pair_id": pair_id,
                    "original_span": list(fact["original_span"]),
                    "original_entity": fact["original_value"],
                    "counterfactual_entity": replacement,
                    "effective_type": fact["effective_type"],
                    "semantic_subtype": fact["semantic_subtype"],
                    "true_claim": fact["proposition_text"],
                    "counterfactual_claim": claim,
                }
            )
    candidates.sort(
        key=lambda row: (
            _source_order_sort_key(row["source_order_rank"]),
            row["source_key"],
            row["fact_signature"],
            row["pair_id"],
        )
    )
    selected: list[dict[str, Any]] = []
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_source.setdefault(row["source_key"], []).append(row)
    eligible_sources = 0
    source_order = sorted(
        by_source,
        key=lambda key: (
            _source_order_sort_key(by_source[key][0]["source_order_rank"]),
            key,
        ),
    )
    for source_key in source_order:
        rows = by_source[source_key]
        seen_facts: set[str] = set()
        entity_counts: Counter[str] = Counter()
        accepted: list[dict[str, Any]] = []
        for row in rows:
            entity = normalize_text(row["original_entity"])
            if row["fact_signature"] in seen_facts or entity_counts[entity] >= 2:
                continue
            item = dict(row)
            item["pair_order"] = len(accepted)
            accepted.append(item)
            seen_facts.add(row["fact_signature"])
            entity_counts[entity] += 1
            if len(accepted) == 3:
                break
        if len(accepted) == 3:
            selected.extend(accepted)
            eligible_sources += 1
    _write_or_validate_jsonl(paths["selection"], selected)
    manifest = {
        "kind": "v23_fact_layer_selection_manifest",
        "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "attempt_id": identity["attempt_id"],
        "dataset": dataset,
        "fact_manifest_sha256": sha256_file(paths["manifest"]),
        "selected_pair_count": len(selected),
        "eligible_source_count": eligible_sources,
        "candidate_pair_count": len(candidates),
        "external_calls_performed": 0,
        "status": "passed",
        "created_at": _utc_now(),
    }
    if paths["selection_manifest"].exists():
        actual = _read_json(paths["selection_manifest"])
        if {key: actual.get(key) for key in manifest if key != "created_at"} != {
            key: value for key, value in manifest.items() if key != "created_at"
        }:
            raise RuntimeError("fact_layer_selection_manifest_drift")
    else:
        _write_new_json(paths["selection_manifest"], manifest)
    return {
        "status": "passed",
        "dataset": dataset,
        "attempt_id": identity["attempt_id"],
        "selected_pair_count": len(selected),
        "eligible_source_count": eligible_sources,
        "candidate_pair_count": len(candidates),
        "fact_layer_status": fact_status["status"],
        "external_calls_performed": 0,
    }


def run_development_pilot(
    *, project_root: str | Path = ".", dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
    model_emitter: Callable[[str, str], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    facts = extract_facts(
        project_root=project_root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
        model_emitter=model_emitter,
    )
    selection = select_pairs(
        project_root=project_root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    root = Path(project_root).resolve()
    identity = fact_layer_attempt_identity(
        project_root=root, dataset=dataset, model_runtime_identity=model_runtime_identity
    )
    paths = _fact_paths(root, dataset, identity["attempt_id"])
    pool = _pool_contract(load_design_config(root), dataset)
    capacity = capacity_decision(
        population=int(pool["source_count"]),
        sample=int(identity["reservation"]["source_count"]),
        observed_eligible=int(selection["eligible_source_count"]),
        consumed_non_development=int(identity["reservation"]["consumed_non_development_count"]),
    )
    manifest = {
        "kind": "v23_fact_layer_pilot_manifest",
        "specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "attempt_id": identity["attempt_id"],
        "dataset": dataset,
        "fact_manifest_sha256": sha256_file(paths["manifest"]),
        "selection_manifest_sha256": sha256_file(paths["selection_manifest"]),
        "completed_source_count": facts["completed_source_count"],
        "eligible_source_count": selection["eligible_source_count"],
        "selected_pair_count": selection["selected_pair_count"],
        "capacity_gate": capacity,
        "external_calls_performed": 0,
        "status": capacity["status"],
        "created_at": _utc_now(),
    }
    if paths["pilot_manifest"].exists():
        actual = _read_json(paths["pilot_manifest"])
        if {key: actual.get(key) for key in manifest if key != "created_at"} != {
            key: value for key, value in manifest.items() if key != "created_at"
        }:
            raise RuntimeError("fact_layer_pilot_manifest_drift")
    else:
        _write_new_json(paths["pilot_manifest"], manifest)
    return manifest


def validate_development_pilot(
    *, project_root: str | Path = ".", dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    fact_status = validate_facts(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    identity = fact_layer_attempt_identity(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    paths = _fact_paths(root, dataset, identity["attempt_id"])
    if not paths["selection"].is_file() or not paths["selection_manifest"].is_file():
        raise RuntimeError("fact_layer_selection_artifact_missing")
    selection = select_pairs(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    if not paths["pilot_manifest"].is_file():
        raise RuntimeError("fact_layer_pilot_manifest_missing")
    manifest = _read_json(paths["pilot_manifest"])
    pool = _pool_contract(load_design_config(root), dataset)
    capacity = capacity_decision(
        population=int(pool["source_count"]),
        sample=int(identity["reservation"]["source_count"]),
        observed_eligible=int(selection["eligible_source_count"]),
        consumed_non_development=int(identity["reservation"]["consumed_non_development_count"]),
    )
    if (
        manifest.get("attempt_id") != identity["attempt_id"]
        or manifest.get("fact_manifest_sha256") != sha256_file(paths["manifest"])
        or manifest.get("selection_manifest_sha256") != sha256_file(paths["selection_manifest"])
        or manifest.get("capacity_gate") != capacity
        or manifest.get("external_calls_performed") != 0
    ):
        raise RuntimeError("fact_layer_pilot_manifest_drift")
    return {
        **manifest,
        "fact_layer_status": fact_status["status"],
        "selection_status": selection["status"],
        "validation_mode": "recomputed_from_fact_and_selection_artifacts",
    }


def status(*, project_root: str | Path = ".", dataset: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    datasets = (dataset,) if dataset is not None else DATASET_ORDER
    output: dict[str, Any] = {"kind": "v23_fact_layer_status", "datasets": {}}
    for item in datasets:
        directory = _resolve(FACT_LAYER_ROOT / item, root)
        attempts = []
        for path in sorted((directory / "attempts").glob("*") if (directory / "attempts").is_dir() else []):
            if path.is_dir():
                manifest = path / "manifest.json"
                checkpoint = path / "checkpoint.json"
                source_results = path / "source_results"
                attempts.append(
                    {
                        "attempt_id": path.name,
                        "manifest": manifest.is_file(),
                        "checkpoint": checkpoint.is_file(),
                        "completed_source_count": (
                            _read_json(manifest).get("completed_source_count")
                            if manifest.is_file()
                            else len(list(source_results.glob("*.json")))
                            if source_results.is_dir()
                            else 0
                        ),
                    }
                )
        output["datasets"][item] = {
            "attempts": attempts,
            "active_lock": (directory / ".fact-extraction.lock").is_file(),
        }
    return output
