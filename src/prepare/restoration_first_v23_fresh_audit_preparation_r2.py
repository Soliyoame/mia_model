"""Expanded-reserve preparation revision for the frozen-r2 v23 fresh audit."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from ..attack.restoration_first_v23 import (
    canonical_json,
    canonical_sha256,
    normalized_text_sha256,
    text_sha256,
)
from ..utils.hash import sha256_file
from ..utils.io import load_yaml
from . import restoration_first_v23_fresh_audit_preparation as legacy


CONFIG_PATH = Path("configs/restoration_first_v23_fresh_audit_preparation_r2.yaml")
POLICY_FREEZE_PATH = Path(
    "configs/restoration_first_v23_fresh_audit_preparation_r2.policy.freeze.json"
)
FREEZE_MANIFEST_PATH = Path(
    "configs/restoration_first_v23_fresh_audit_preparation_r2.freeze.json"
)
COMPATIBILITY_ENVELOPE_PATH = Path(
    "configs/restoration_first_v23_fresh_audit_compatibility_r1.json"
)
COMPATIBILITY_ENVELOPE_REVISION = "compatibility-envelope-r1"
COMPATIBILITY_ALLOWED_FUNCTIONS = {
    "src/prepare/restoration_first_v23_fresh_audit_preparation.py": (
        "build_packets",
    ),
    "src/prepare/restoration_first_v23_fresh_audit_preparation_r2.py": (
        "_legacy_packet_freeze_manifest",
        "_legacy_profile",
        "build_packets",
    )
}
RUNNER_REVISION = "r2-enron-reserve-1000"
DATASETS = ("edgar", "enron", "pubmed")
ZERO_SHA256 = "0" * 64
RESERVATION_AUTH_KIND = "v23_fresh_audit_expanded_reserve_authorization"
RUN_AUTH_KIND = "v23_fresh_audit_preparation_r2_run_authorization"
LEDGER_ROLES = {
    "development",
    "fresh_audit_reserve",
    "human_viewed",
    "diagnostic_viewed",
    "formal_scan_viewed",
}
GENESIS_FIELDS = {
    "kind",
    "sequence",
    "protocol_revision_id",
    "role",
    "dataset",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "consumed_at",
    "reason",
    "previous_row_sha256",
    "design_manifest_sha256",
    "frozen_v22_protocol_identity_sha256",
    "source_order_file_sha256_by_dataset",
    "row_sha256",
}
SOURCE_LEDGER_FIELDS = {
    "kind",
    "sequence",
    "protocol_revision_id",
    "attempt_id",
    "reservation_batch_id",
    "reservation_batch_index",
    "reservation_batch_size",
    "role",
    "dataset",
    "source_key",
    "source_hash",
    "normalized_text_hash",
    "consumed_at",
    "reason",
    "previous_row_sha256",
    "row_sha256",
}
BUDGET_FIELDS = {
    "kind",
    "sequence",
    "authorization_id",
    "stage",
    "charge_ordinal",
    "operation_identity_sha256",
    "previous_row_sha256",
    "row_sha256",
    "charged_at",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise RuntimeError(f"artifact_already_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (canonical_json(dict(value)) + "\n").encode("utf-8")
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_or_validate_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        if _read_json(path) != dict(value):
            raise RuntimeError(f"artifact_identity_drift:{path}")
        return
    _write_new_json(path, value)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"fresh_audit_r2_active_lock:{path}") from error
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _assert_exact_fields(
    value: Mapping[str, Any], expected: set[str], *, kind: str
) -> None:
    if set(value) != expected:
        raise RuntimeError(f"{kind}_schema_drift")


def _config_file_sha256(root: Path) -> str:
    return sha256_file(_resolve(CONFIG_PATH, root))


def _reservation_revision_id(config: Mapping[str, Any], root: Path) -> str:
    return canonical_sha256(
        {
            "kind": "v23_fresh_audit_expanded_reserve_revision",
            "runner_revision": RUNNER_REVISION,
            "config_sha256": _config_file_sha256(root),
            "predecessor_freeze_identity_sha256": config["predecessor"][
                "preparation_freeze_identity_sha256"
            ],
            "prior_ledger_tip_sha256": config["reserve_group"][
                "prior_ledger_tip_sha256"
            ],
            "reserve_source_count_by_dataset": config["reserve_group"][
                "reserve_source_count_by_dataset"
            ],
            "selection_specification_version": config[
                "selection_specification_version"
            ],
            "selection_manifest_sha256_by_dataset": {
                dataset: config["datasets"][dataset]["selection_manifest_sha256"]
                for dataset in DATASETS
            },
        }
    )


def load_preparation_config(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    value = load_yaml(_resolve(CONFIG_PATH, root))
    if not isinstance(value, Mapping):
        raise RuntimeError("fresh_audit_r2_config_invalid")
    config = dict(value)
    expected = {
        "protocol_version": "pcv-mia-v23",
        "method_version": "pcv-restoration-first-v23-fresh-audit-preparation",
        "specification_version": "pcv-restoration-first-v23-fresh-audit-preparation-r2",
        "selection_specification_version": (
            "pcv-restoration-first-v23-fact-layer-selection-r2"
        ),
        "fact_specification_version": "pcv-restoration-first-v23-fact-layer-r1",
        "external_calls_performed": 0,
    }
    if any(config.get(key) != expected_value for key, expected_value in expected.items()):
        raise RuntimeError("fresh_audit_r2_config_identity_drift")
    group = config.get("reserve_group")
    if not isinstance(group, Mapping):
        raise RuntimeError("fresh_audit_r2_reserve_group_missing")
    if tuple(group.get("dataset_order", ())) != DATASETS:
        raise RuntimeError("fresh_audit_r2_dataset_order_drift")
    counts = group.get("reserve_source_count_by_dataset")
    if (
        not isinstance(counts, Mapping)
        or set(counts) != set(DATASETS)
        or any(
            isinstance(counts[dataset], bool)
            or not isinstance(counts[dataset], int)
            or counts[dataset] < 1
            for dataset in DATASETS
        )
        or counts["edgar"] != 250
        or counts["enron"] != 1000
        or counts["pubmed"] != 250
    ):
        raise RuntimeError("fresh_audit_r2_reserve_count_drift")
    if (
        group.get("selected_source_count_per_dataset") != 100
        or group.get("pairs_per_source") != 3
        or group.get("total_packet_rows") != 900
        or group.get("registration_identity_only") is not True
    ):
        raise RuntimeError("fresh_audit_r2_selection_contract_drift")
    if set(config.get("forbidden_inputs") or ()) != {
        "membership",
        "victim_response",
        "llm_only_response",
        "retriever_output",
        "auc",
        "formal_labels",
    }:
        raise RuntimeError("fresh_audit_r2_forbidden_input_drift")
    config["execution_reservation_revision"] = _reservation_revision_id(config, root)
    return config


def _reserve_count(config: Mapping[str, Any], dataset: str) -> int:
    return int(config["reserve_group"]["reserve_source_count_by_dataset"][dataset])


def _reservation_directory(root: Path, config: Mapping[str, Any]) -> Path:
    base = _resolve(str(config["reserve_group"]["reservation_directory"]), root)
    return base / str(config["execution_reservation_revision"])


def _ledger_path(root: Path, config: Mapping[str, Any]) -> Path:
    return _resolve(str(config["reserve_group"]["ledger_path"]), root)


def _anchor_directory(root: Path, config: Mapping[str, Any]) -> Path:
    return _resolve(str(config["reserve_group"]["ledger_anchor_directory"]), root)


def _implementation_files() -> tuple[Path, ...]:
    return (
        Path("src/attack/restoration_first_v23.py"),
        Path("src/attack/restoration_first_v23_fact_layer.py"),
        Path("src/attack/restoration_first_v23_fact_layer_selection_r2.py"),
        Path("src/prepare/restoration_first_v23_fresh_audit_preparation.py"),
        Path("src/prepare/restoration_first_v23_fresh_audit_preparation_r2.py"),
        Path("scripts/44_prepare_v23_fresh_audit_expanded.py"),
    )


def _file_hashes(root: Path, paths: Sequence[Path]) -> dict[str, str]:
    output: dict[str, str] = {}
    for path in paths:
        resolved = _resolve(path, root)
        if not resolved.is_file():
            raise RuntimeError(f"fresh_audit_r2_implementation_missing:{path}")
        output[path.as_posix()] = sha256_file(resolved)
    return output


def _protected_surface_sha256(
    root: Path, path: str, excluded_functions: Sequence[str] = ()
) -> str:
    """计算兼容层之外的 AST 身份，避免格式变化影响校验。"""
    resolved = _resolve(path, root)
    tree = ast.parse(resolved.read_text(encoding="utf-8"), filename=path)
    excluded = set(excluded_functions)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in excluded:
            node.body = [ast.Pass()]
    return canonical_sha256(ast.dump(tree, annotate_fields=True, include_attributes=False))


def _compatibility_surface_hashes(root: Path) -> dict[str, str]:
    paths = set(_implementation_files())
    result: dict[str, str] = {}
    for path in sorted(paths, key=lambda item: item.as_posix()):
        key = path.as_posix()
        result[key] = _protected_surface_sha256(
            root, key, COMPATIBILITY_ALLOWED_FUNCTIONS.get(key, ())
        )
    return result


def _compatibility_envelope_identity(value: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: item for key, item in value.items() if key not in {"created_at", "compatibility_identity_sha256"}}
    )


def _validate_compatibility_envelope(
    root: Path, freeze_identity: str
) -> dict[str, Any]:
    path = _resolve(COMPATIBILITY_ENVELOPE_PATH, root)
    if not path.is_file():
        raise RuntimeError("fresh_audit_r2_compatibility_envelope_missing")
    envelope = _read_json(path)
    if (
        envelope.get("kind") != "v23_fresh_audit_compatibility_envelope"
        or envelope.get("revision") != COMPATIBILITY_ENVELOPE_REVISION
        or envelope.get("freeze_identity_sha256") != freeze_identity
        or envelope.get("allowed_functions") != {
            key: list(value) for key, value in COMPATIBILITY_ALLOWED_FUNCTIONS.items()
        }
        or envelope.get("protected_surface_sha256_by_file")
        != _compatibility_surface_hashes(root)
        or envelope.get("compatibility_identity_sha256")
        != _compatibility_envelope_identity(envelope)
    ):
        raise RuntimeError("fresh_audit_r2_compatibility_envelope_drift")
    return envelope


def _validate_implementation_binding(
    root: Path, actual: Mapping[str, Any]
) -> dict[str, Any]:
    bound = actual.get("implementation_file_sha256")
    if not isinstance(bound, Mapping):
        raise RuntimeError("fresh_audit_r2_implementation_binding_missing")
    current = _file_hashes(root, _implementation_files())
    changed = sorted(
        path for path, digest in current.items() if bound.get(path) != digest
    )
    unexpected = sorted(
        path for path in bound if path not in current
    )
    if unexpected or any(path not in COMPATIBILITY_ALLOWED_FUNCTIONS for path in changed):
        raise RuntimeError("fresh_audit_r2_scientific_implementation_drift")
    if not changed:
        return {"status": "unchanged", "changed_files": []}
    freeze_identity = actual.get("freeze_identity_sha256")
    if not isinstance(freeze_identity, str):
        preparation_path = _resolve(FREEZE_MANIFEST_PATH, root)
        preparation_manifest = _read_json(preparation_path)
        freeze_identity = preparation_manifest.get("freeze_identity_sha256")
    envelope = _validate_compatibility_envelope(root, str(freeze_identity))
    return {
        "status": "compatibility_only",
        "changed_files": changed,
        "compatibility_identity_sha256": envelope["compatibility_identity_sha256"],
    }


def _assert_freeze_manifest_compatible(
    root: Path, actual: Mapping[str, Any], expected: Mapping[str, Any], *, identity_key: str
) -> dict[str, Any]:
    ignored = {"created_at", "implementation_file_sha256", identity_key}
    if {
        key: value for key, value in actual.items() if key not in ignored
    } != {
        key: value for key, value in expected.items() if key not in ignored
    }:
        raise RuntimeError("fresh_audit_r2_freeze_manifest_drift")
    identity = actual.get(identity_key)
    if not isinstance(identity, str) or canonical_sha256(
        {
            key: value
            for key, value in actual.items()
            if key not in {"created_at", identity_key}
        }
    ) != identity:
        raise RuntimeError("fresh_audit_r2_freeze_identity_hash_drift")
    implementation = _validate_implementation_binding(root, actual)
    if not _is_sha256(identity):
        raise RuntimeError("fresh_audit_r2_freeze_identity_invalid")
    return implementation


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes() if path.is_file() else b""
    if not raw or not raw.endswith(b"\n"):
        raise RuntimeError("fresh_audit_r2_ledger_missing_or_partial")
    rows: list[dict[str, Any]] = []
    previous = ZERO_SHA256
    for sequence, line in enumerate(raw.decode("utf-8").splitlines()):
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RuntimeError("fresh_audit_r2_ledger_row_invalid")
        _assert_exact_fields(
            row,
            GENESIS_FIELDS if sequence == 0 else SOURCE_LEDGER_FIELDS,
            kind="fresh_audit_r2_ledger_row",
        )
        if (
            row.get("sequence") != sequence
            or row.get("previous_row_sha256") != previous
            or row.get("row_sha256")
            != canonical_sha256(
                {key: item for key, item in row.items() if key != "row_sha256"}
            )
        ):
            raise RuntimeError("fresh_audit_r2_ledger_chain_drift")
        if sequence and (
            row.get("kind") != "v23_consumed_source"
            or row.get("role") not in LEDGER_ROLES
        ):
            raise RuntimeError("fresh_audit_r2_ledger_scope_drift")
        rows.append(row)
        previous = str(row["row_sha256"])
    return rows


def _find_anchor(root: Path, config: Mapping[str, Any], tip: str) -> Path:
    matches = []
    for path in sorted(_anchor_directory(root, config).glob("*.json")):
        value = _read_json(path)
        if value.get("ledger_tip_sha256") == tip:
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError("fresh_audit_r2_ledger_tip_anchor_invalid")
    return matches[0]


def _validate_predecessor(root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    binding = config["predecessor"]
    path = _resolve(str(binding["preparation_freeze_path"]), root)
    if (
        not path.is_file()
        or sha256_file(path) != binding["preparation_freeze_sha256"]
    ):
        raise RuntimeError("fresh_audit_r2_predecessor_file_drift")
    predecessor = _read_json(path)
    if (
        predecessor.get("freeze_identity_sha256")
        != binding["preparation_freeze_identity_sha256"]
        or binding.get("terminal_enron_status")
        != "failed_reserve_eligible_shortfall"
        or binding.get("enron_evaluated_source_count") != 250
        or binding.get("enron_eligible_source_count") != 29
    ):
        raise RuntimeError("fresh_audit_r2_predecessor_identity_drift")
    return predecessor


def build_policy_freeze_manifest(
    project_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_preparation_config(root)
    predecessor = _validate_predecessor(root, config)
    design_path = _resolve(str(config["design_config_path"]), root)
    design_manifest_path = _resolve(str(config["design_manifest_path"]), root)
    selection_config_path = _resolve(str(config["selection_config_path"]), root)
    model_lock_path = _resolve(str(config["model_lock_path"]), root)
    for path in (
        design_path,
        design_manifest_path,
        selection_config_path,
        model_lock_path,
    ):
        if not path.is_file():
            raise RuntimeError(f"fresh_audit_r2_bound_file_missing:{path}")
    design = load_yaml(design_path)
    pools = design.get("frozen_v22_bindings", {}).get("source_pools", {})
    if not isinstance(pools, Mapping):
        raise RuntimeError("fresh_audit_r2_source_pool_bindings_missing")
    datasets: dict[str, Any] = {}
    for dataset in DATASETS:
        binding = config["datasets"][dataset]
        manifests = legacy._validate_r2_manifest(root, dataset, binding)
        pool = pools.get(dataset)
        if not isinstance(pool, Mapping):
            raise RuntimeError(f"fresh_audit_r2_source_pool_missing:{dataset}")
        order_path = _resolve(str(pool["source_order_path"]), root)
        database_path = _resolve(str(pool["database_path"]), root)
        manifest_path = _resolve(str(pool["manifest_path"]), root)
        for path, expected_hash in (
            (order_path, pool["source_order_file_sha256"]),
            (database_path, pool["database_sha256"]),
            (manifest_path, pool["manifest_sha256"]),
        ):
            if not path.is_file() or sha256_file(path) != expected_hash:
                raise RuntimeError(f"fresh_audit_r2_source_pool_drift:{dataset}")
        datasets[dataset] = {
            "fact_attempt_id": binding["fact_attempt_id"],
            "selection_attempt_id": binding["selection_attempt_id"],
            "fact_manifest_sha256": binding["fact_manifest_sha256"],
            "selection_manifest_sha256": binding["selection_manifest_sha256"],
            "pilot_manifest_sha256": binding["pilot_manifest_sha256"],
            "selection_status": manifests["selection_manifest"]["status"],
            "pilot_status": manifests["pilot_manifest"]["status"],
            "source_order_file_sha256": pool["source_order_file_sha256"],
            "source_pool_database_sha256": pool["database_sha256"],
            "reserve_source_count": _reserve_count(config, dataset),
        }
    ledger_rows = _read_ledger(_ledger_path(root, config))
    prior_tip = str(config["reserve_group"]["prior_ledger_tip_sha256"])
    if sum(row["row_sha256"] == prior_tip for row in ledger_rows) != 1:
        raise RuntimeError("fresh_audit_r2_policy_prior_ledger_tip_missing")
    prior_anchor = _find_anchor(root, config, prior_tip)
    payload = {
        "kind": "v23_fresh_audit_expanded_reserve_policy_freeze",
        "runner_revision": RUNNER_REVISION,
        "specification_version": config["specification_version"],
        "execution_reservation_revision": config[
            "execution_reservation_revision"
        ],
        "config_sha256": _config_file_sha256(root),
        "predecessor_freeze_identity_sha256": predecessor[
            "freeze_identity_sha256"
        ],
        "predecessor_freeze_file_sha256": config["predecessor"][
            "preparation_freeze_sha256"
        ],
        "prior_ledger_tip_sha256": prior_tip,
        "prior_ledger_tip_anchor_sha256": sha256_file(prior_anchor),
        "design_config_sha256": sha256_file(design_path),
        "design_manifest_sha256": sha256_file(design_manifest_path),
        "selection_config_sha256": sha256_file(selection_config_path),
        "model_lock_sha256": sha256_file(model_lock_path),
        "implementation_file_sha256": _file_hashes(root, _implementation_files()),
        "reserve_source_count_by_dataset": dict(
            config["reserve_group"]["reserve_source_count_by_dataset"]
        ),
        "selected_source_count_per_dataset": int(
            config["reserve_group"]["selected_source_count_per_dataset"]
        ),
        "pairs_per_source": int(config["reserve_group"]["pairs_per_source"]),
        "datasets": datasets,
        "source_content_read": False,
        "ledger_mutation": False,
        "external_calls_performed": 0,
        "created_at": _utc_now(),
    }
    payload["policy_freeze_identity_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "created_at"}
    )
    return payload


def freeze_policy(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_preparation_config(root)
    ledger_rows = _read_ledger(_ledger_path(root, config))
    if (
        ledger_rows[-1]["row_sha256"]
        != config["reserve_group"]["prior_ledger_tip_sha256"]
    ):
        raise RuntimeError("fresh_audit_r2_policy_prior_ledger_tip_drift")
    expected = build_policy_freeze_manifest(root)
    path = _resolve(POLICY_FREEZE_PATH, root)
    if path.exists():
        actual = _read_json(path)
        _assert_freeze_manifest_compatible(
            root, actual, expected, identity_key="policy_freeze_identity_sha256"
        )
    else:
        _write_new_json(path, expected)
        actual = expected
    return {
        "status": "passed",
        "policy_freeze_identity_sha256": actual[
            "policy_freeze_identity_sha256"
        ],
        "execution_reservation_revision": expected[
            "execution_reservation_revision"
        ],
        "policy_freeze_path": path.relative_to(root).as_posix(),
        "source_content_read": False,
        "ledger_mutation": False,
        "external_calls_performed": 0,
    }


def validate_policy_freeze(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = _resolve(POLICY_FREEZE_PATH, root)
    if not path.is_file():
        raise RuntimeError("fresh_audit_r2_policy_freeze_missing")
    expected = build_policy_freeze_manifest(root)
    actual = _read_json(path)
    implementation = _assert_freeze_manifest_compatible(
        root, actual, expected, identity_key="policy_freeze_identity_sha256"
    )
    return {
        "status": "passed",
        "policy_freeze_identity_sha256": actual[
            "policy_freeze_identity_sha256"
        ],
        "execution_reservation_revision": actual[
            "execution_reservation_revision"
        ],
        "policy_freeze_sha256": sha256_file(path),
        "source_content_read": False,
        "ledger_mutation": False,
        "implementation_binding_status": implementation["status"],
        "implementation_changed_files": implementation["changed_files"],
        "external_calls_performed": 0,
    }


def _validate_reserve_metadata(
    root: Path, config: Mapping[str, Any], dataset: str
) -> dict[str, Any]:
    if dataset not in DATASETS:
        raise ValueError("fresh_audit_r2_dataset_invalid")
    directory = _reservation_directory(root, config)
    revision = str(config["execution_reservation_revision"])
    prior_path = directory / "prior_snapshot.json"
    completion_path = directory / "group_completion.json"
    plan_path = directory / "plans" / "fresh_audit_reserve" / f"{dataset}.json"
    snapshot_path = directory / f"{dataset}_reserve_snapshot.json"
    if not all(
        path.is_file()
        for path in (prior_path, completion_path, plan_path, snapshot_path)
    ):
        raise RuntimeError(f"fresh_audit_r2_reserve_metadata_missing:{dataset}")
    prior = _read_json(prior_path)
    completion = _read_json(completion_path)
    plan = _read_json(plan_path)
    snapshot = _read_json(snapshot_path)
    count = _reserve_count(config, dataset)
    identities = plan.get("ordered_source_identity_objects")
    ordered = snapshot.get("ordered_sources")
    if (
        prior.get("kind") != "v23_revision_reservation_prior_snapshot"
        or prior.get("protocol_revision_id") != revision
        or completion.get("kind") != "v23_revision_reservation_group_complete"
        or completion.get("protocol_revision_id") != revision
        or plan.get("kind") != "v23_reservation_plan"
        or plan.get("protocol_revision_id") != revision
        or plan.get("role") != "fresh_audit_reserve"
        or plan.get("dataset") != dataset
        or not isinstance(identities, list)
        or len(identities) != count
        or snapshot.get("kind") != "v23_fresh_audit_reserve_snapshot"
        or snapshot.get("protocol_revision_id") != revision
        or snapshot.get("dataset") != dataset
        or not isinstance(ordered, list)
        or len(ordered) != count
    ):
        raise RuntimeError(f"fresh_audit_r2_reserve_metadata_drift:{dataset}")
    plan_keys = [str(item.get("source_key")) for item in identities]
    snapshot_keys = [str(item.get("source_key")) for item in ordered]
    if len(set(plan_keys)) != count or plan_keys != snapshot_keys:
        raise RuntimeError(f"fresh_audit_r2_reserve_order_drift:{dataset}")
    for identity, snapshot_item in zip(identities, ordered, strict=True):
        if (
            set(identity)
            != {"source_key", "source_hash", "normalized_text_hash"}
            or not _is_sha256(identity.get("source_hash"))
            or not _is_sha256(identity.get("normalized_text_hash"))
            or set(snapshot_item) != {"source_order_index", "source_key"}
            or isinstance(snapshot_item.get("source_order_index"), bool)
            or not isinstance(snapshot_item.get("source_order_index"), int)
        ):
            raise RuntimeError(
                f"fresh_audit_r2_reserve_identity_schema_drift:{dataset}"
            )
    return {
        "plan_path": plan_path,
        "plan_sha256": sha256_file(plan_path),
        "snapshot_path": snapshot_path,
        "snapshot_sha256": sha256_file(snapshot_path),
        "source_count": count,
        "source_keys": tuple(plan_keys),
        "prior_snapshot_sha256": sha256_file(prior_path),
        "group_completion_sha256": sha256_file(completion_path),
    }


def build_preparation_freeze_manifest(
    project_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_preparation_config(root)
    policy = validate_policy_freeze(root)
    group = validate_reserve_group(root)
    design_path = _resolve(str(config["design_config_path"]), root)
    design_manifest_path = _resolve(str(config["design_manifest_path"]), root)
    selection_config_path = _resolve(str(config["selection_config_path"]), root)
    model_lock_path = _resolve(str(config["model_lock_path"]), root)
    datasets: dict[str, Any] = {}
    group_metadata: dict[str, Any] | None = None
    for dataset in DATASETS:
        binding = config["datasets"][dataset]
        manifests = legacy._validate_r2_manifest(root, dataset, binding)
        reserve = _validate_reserve_metadata(root, config, dataset)
        if group_metadata is None:
            group_metadata = reserve
        elif (
            reserve["prior_snapshot_sha256"]
            != group_metadata["prior_snapshot_sha256"]
            or reserve["group_completion_sha256"]
            != group_metadata["group_completion_sha256"]
        ):
            raise RuntimeError("fresh_audit_r2_reserve_group_metadata_drift")
        datasets[dataset] = {
            "fact_attempt_id": binding["fact_attempt_id"],
            "fact_manifest_sha256": binding["fact_manifest_sha256"],
            "selection_attempt_id": binding["selection_attempt_id"],
            "selection_manifest_sha256": binding["selection_manifest_sha256"],
            "pilot_manifest_sha256": binding["pilot_manifest_sha256"],
            "fact_manifest_file_sha256": sha256_file(
                _resolve(str(binding["fact_manifest_path"]), root)
            ),
            "selection_manifest_file_sha256": sha256_file(
                _resolve(str(binding["selection_manifest_path"]), root)
            ),
            "pilot_manifest_file_sha256": sha256_file(
                _resolve(str(binding["pilot_manifest_path"]), root)
            ),
            "reserve_plan_sha256": reserve["plan_sha256"],
            "reserve_snapshot_sha256": reserve["snapshot_sha256"],
            "reserve_source_count": reserve["source_count"],
            "selection_status": manifests["selection_manifest"]["status"],
            "pilot_status": manifests["pilot_manifest"]["status"],
        }
    assert group_metadata is not None
    payload = {
        "kind": "v23_fresh_audit_preparation_freeze_manifest",
        "runner_revision": RUNNER_REVISION,
        "specification_version": config["specification_version"],
        "selection_specification_version": config[
            "selection_specification_version"
        ],
        "fact_specification_version": config["fact_specification_version"],
        "execution_reservation_revision": config[
            "execution_reservation_revision"
        ],
        "policy_freeze_identity_sha256": policy[
            "policy_freeze_identity_sha256"
        ],
        "policy_freeze_sha256": policy["policy_freeze_sha256"],
        "reservation_validation_sha256": group["reservation_validation_sha256"],
        "config_sha256": _config_file_sha256(root),
        "design_config_sha256": sha256_file(design_path),
        "design_manifest_sha256": sha256_file(design_manifest_path),
        "selection_config_sha256": sha256_file(selection_config_path),
        "model_lock_sha256": sha256_file(model_lock_path),
        "implementation_file_sha256": _file_hashes(root, _implementation_files()),
        "reserve_group": {
            "prior_snapshot_sha256": group_metadata["prior_snapshot_sha256"],
            "group_completion_sha256": group_metadata[
                "group_completion_sha256"
            ],
            "dataset_order": list(DATASETS),
            "reserve_source_count_by_dataset": dict(
                config["reserve_group"]["reserve_source_count_by_dataset"]
            ),
            "selected_source_count_per_dataset": int(
                config["reserve_group"]["selected_source_count_per_dataset"]
            ),
            "pairs_per_source": int(
                config["reserve_group"]["pairs_per_source"]
            ),
            "total_packet_rows": int(
                config["reserve_group"]["total_packet_rows"]
            ),
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
    expected = build_preparation_freeze_manifest(root)
    path = _resolve(FREEZE_MANIFEST_PATH, root)
    if path.exists():
        actual = _read_json(path)
        _assert_freeze_manifest_compatible(
            root, actual, expected, identity_key="freeze_identity_sha256"
        )
    else:
        _write_new_json(path, expected)
        actual = expected
    return {
        "status": "passed",
        "freeze_identity_sha256": actual["freeze_identity_sha256"],
        "freeze_manifest_path": path.relative_to(root).as_posix(),
        "source_content_read": False,
        "external_calls_performed": 0,
    }


def validate_preparation_freeze(
    project_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = _resolve(FREEZE_MANIFEST_PATH, root)
    if not path.is_file():
        raise RuntimeError("fresh_audit_r2_freeze_manifest_missing")
    expected = build_preparation_freeze_manifest(root)
    actual = _read_json(path)
    implementation = _assert_freeze_manifest_compatible(
        root, actual, expected, identity_key="freeze_identity_sha256"
    )
    return {
        "status": "passed",
        "freeze_identity_sha256": actual["freeze_identity_sha256"],
        "freeze_manifest_sha256": sha256_file(path),
        "datasets": list(DATASETS),
        "source_content_read": False,
        "implementation_binding_status": implementation["status"],
        "implementation_changed_files": implementation["changed_files"],
        "external_calls_performed": 0,
    }


def validate_implementation_compatibility(
    project_root: str | Path = ".",
) -> dict[str, Any]:
    """只验证兼容适配层，科学 freeze identity 不被重新生成。"""
    root = Path(project_root).resolve()
    freeze = validate_preparation_freeze(root)
    manifest = _read_json(_resolve(FREEZE_MANIFEST_PATH, root))
    implementation = _validate_implementation_binding(root, manifest)
    envelope = _validate_compatibility_envelope(
        root, freeze["freeze_identity_sha256"]
    )
    return {
        "status": "passed",
        "freeze_identity_sha256": freeze["freeze_identity_sha256"],
        "compatibility_revision": envelope["revision"],
        "compatibility_identity_sha256": envelope[
            "compatibility_identity_sha256"
        ],
        "implementation_binding_status": implementation["status"],
        "implementation_changed_files": implementation["changed_files"],
        "source_content_read": False,
        "external_calls_performed": 0,
    }


def _legacy_packet_freeze_manifest(project_root: str | Path = ".") -> dict[str, Any]:
    """为旧 packet builder 提供已验证的完整 freeze manifest。"""
    root = Path(project_root).resolve()
    summary = validate_preparation_freeze(root)
    path = _resolve(FREEZE_MANIFEST_PATH, root)
    manifest = _read_json(path)
    if (
        manifest.get("freeze_identity_sha256")
        != summary["freeze_identity_sha256"]
        or not isinstance(manifest.get("datasets"), Mapping)
    ):
        raise RuntimeError("fresh_audit_r2_packet_freeze_manifest_invalid")
    return manifest


@contextmanager
def _legacy_profile(
    *,
    freeze_validator: Any = validate_preparation_freeze,
    authorization_validator: Any | None = None,
) -> Iterator[None]:
    replacements = {
        "CONFIG_PATH": CONFIG_PATH,
        "FREEZE_MANIFEST_PATH": FREEZE_MANIFEST_PATH,
        "RUNNER_REVISION": RUNNER_REVISION,
        "RUN_AUTH_KIND": RUN_AUTH_KIND,
        "load_preparation_config": load_preparation_config,
        "_validate_reserve_metadata": _validate_reserve_metadata,
        "validate_preparation_freeze": freeze_validator,
    }
    if authorization_validator is not None:
        replacements["validate_run_authorization"] = authorization_validator
    previous = {name: getattr(legacy, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(legacy, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(legacy, name, value)


def prepare_dataset(
    *,
    project_root: str | Path = ".",
    dataset: str,
    authorization_path: str | Path,
    model_emitter: Any = None,
) -> dict[str, Any]:
    with _legacy_profile():
        return legacy.prepare_dataset(
            project_root=project_root,
            dataset=dataset,
            authorization_path=authorization_path,
            model_emitter=model_emitter,
        )


def build_packets(
    *, project_root: str | Path = ".", authorization_path: str | Path
) -> dict[str, Any]:
    with _legacy_profile(
        freeze_validator=_legacy_packet_freeze_manifest,
        authorization_validator=validate_run_authorization,
    ):
        return legacy.build_packets(
            project_root=project_root, authorization_path=authorization_path
        )


def prepare_run_authorization(
    *,
    project_root: str | Path = ".",
    stage: str,
    dataset: str | None = None,
    user_authorization_record: str,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    freeze = validate_preparation_freeze(root)
    if stage not in {"dataset_preparation", "packet_preparation"}:
        raise ValueError("fresh_audit_r2_authorization_stage_invalid")
    if stage == "dataset_preparation" and dataset not in DATASETS:
        raise ValueError("fresh_audit_r2_authorization_dataset_required")
    if stage == "packet_preparation" and dataset is not None:
        raise ValueError("fresh_audit_r2_packet_dataset_forbidden")
    if not isinstance(user_authorization_record, str) or not user_authorization_record.strip():
        raise ValueError("fresh_audit_r2_authorization_record_required")
    config = load_preparation_config(root)
    payload = {
        "kind": RUN_AUTH_KIND,
        "specification_version": config["specification_version"],
        "stage": stage,
        "dataset": dataset,
        "freeze_identity_sha256": freeze["freeze_identity_sha256"],
        "budget_maximum_source_reads": (
            _reserve_count(config, str(dataset))
            if stage == "dataset_preparation"
            else 0
        ),
        "external_calls_allowed": False,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "formal_experiment_allowed": False,
        "user_authorization_record": user_authorization_record.strip(),
        "created_at": _utc_now(),
    }
    payload["authorization_id"] = canonical_sha256(payload)
    path = _resolve(
        Path("artifacts/v23/governance/run_authorizations")
        / f"{payload['authorization_id']}.json",
        root,
    )
    _write_or_validate_json(path, payload)
    return {
        **payload,
        "authorization_path": path.relative_to(root).as_posix(),
        "external_calls_performed": 0,
    }


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
    if (
        auth.get("kind") != RUN_AUTH_KIND
        or auth.get("stage") != stage
        or auth.get("dataset") != dataset
        or auth.get("freeze_identity_sha256")
        != freeze["freeze_identity_sha256"]
        or any(
            auth.get(key) is not False
            for key in (
                "external_calls_allowed",
                "api_allowed",
                "victim_allowed",
                "retriever_allowed",
                "formal_experiment_allowed",
            )
        )
    ):
        raise RuntimeError("fresh_audit_r2_authorization_scope_drift")
    payload = {key: value for key, value in auth.items() if key != "authorization_id"}
    if auth.get("authorization_id") != canonical_sha256(payload):
        raise RuntimeError("fresh_audit_r2_authorization_hash_drift")
    return auth


def prepare_reservation_authorization(
    *, project_root: str | Path = ".", user_authorization_record: str
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    policy = validate_policy_freeze(root)
    if not isinstance(user_authorization_record, str) or not user_authorization_record.strip():
        raise ValueError("fresh_audit_r2_reservation_authorization_record_required")
    config = load_preparation_config(root)
    budget = sum(_reserve_count(config, dataset) for dataset in DATASETS)
    payload = {
        "kind": RESERVATION_AUTH_KIND,
        "stage": "expanded_reserve_registration",
        "policy_freeze_identity_sha256": policy[
            "policy_freeze_identity_sha256"
        ],
        "execution_reservation_revision": config[
            "execution_reservation_revision"
        ],
        "expected_prior_ledger_tip_sha256": config["reserve_group"][
            "prior_ledger_tip_sha256"
        ],
        "reserve_source_count_by_dataset": dict(
            config["reserve_group"]["reserve_source_count_by_dataset"]
        ),
        "budget_maximum_identity_reads": budget,
        "source_content_persistence_allowed": False,
        "derived_feature_persistence_allowed": False,
        "ledger_mutation_allowed": True,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "formal_experiment_allowed": False,
        "user_authorization_record": user_authorization_record.strip(),
        "created_at": _utc_now(),
    }
    payload["authorization_id"] = canonical_sha256(payload)
    path = _resolve(
        Path("artifacts/v23/governance/run_authorizations")
        / f"{payload['authorization_id']}.json",
        root,
    )
    _write_or_validate_json(path, payload)
    return {
        **payload,
        "authorization_path": path.relative_to(root).as_posix(),
        "source_content_persisted": False,
        "external_calls_performed": 0,
    }


def validate_reservation_authorization(
    *, project_root: str | Path, authorization_path: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    policy = validate_policy_freeze(root)
    config = load_preparation_config(root)
    path = _resolve(authorization_path, root)
    auth = _read_json(path)
    expected_path = _resolve(
        Path("artifacts/v23/governance/run_authorizations")
        / f"{auth.get('authorization_id')}.json",
        root,
    )
    if path != expected_path:
        raise RuntimeError("fresh_audit_r2_reservation_authorization_path_drift")
    required_false = (
        "source_content_persistence_allowed",
        "derived_feature_persistence_allowed",
        "api_allowed",
        "victim_allowed",
        "retriever_allowed",
        "formal_experiment_allowed",
    )
    if (
        auth.get("kind") != RESERVATION_AUTH_KIND
        or auth.get("stage") != "expanded_reserve_registration"
        or auth.get("policy_freeze_identity_sha256")
        != policy["policy_freeze_identity_sha256"]
        or auth.get("execution_reservation_revision")
        != config["execution_reservation_revision"]
        or auth.get("expected_prior_ledger_tip_sha256")
        != config["reserve_group"]["prior_ledger_tip_sha256"]
        or auth.get("reserve_source_count_by_dataset")
        != config["reserve_group"]["reserve_source_count_by_dataset"]
        or auth.get("budget_maximum_identity_reads")
        != sum(_reserve_count(config, dataset) for dataset in DATASETS)
        or auth.get("ledger_mutation_allowed") is not True
        or any(auth.get(key) is not False for key in required_false)
    ):
        raise RuntimeError("fresh_audit_r2_reservation_authorization_scope_drift")
    payload = {key: value for key, value in auth.items() if key != "authorization_id"}
    if auth.get("authorization_id") != canonical_sha256(payload):
        raise RuntimeError("fresh_audit_r2_reservation_authorization_hash_drift")
    return auth


def _read_budget(
    path: Path, authorization: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], set[str]]:
    if not path.exists():
        return [], set()
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise RuntimeError("fresh_audit_r2_budget_partial")
    rows: list[dict[str, Any]] = []
    operations: set[str] = set()
    previous = ZERO_SHA256
    for sequence, line in enumerate(raw.decode("utf-8").splitlines()):
        row = json.loads(line)
        _assert_exact_fields(row, BUDGET_FIELDS, kind="fresh_audit_r2_budget")
        if (
            row.get("sequence") != sequence
            or row.get("charge_ordinal") != sequence
            or row.get("authorization_id") != authorization["authorization_id"]
            or row.get("stage") != "expanded_reserve_registration"
            or row.get("previous_row_sha256") != previous
            or row.get("row_sha256")
            != canonical_sha256(
                {key: item for key, item in row.items() if key != "row_sha256"}
            )
            or not _is_sha256(row.get("operation_identity_sha256"))
            or row["operation_identity_sha256"] in operations
        ):
            raise RuntimeError("fresh_audit_r2_budget_drift")
        rows.append(row)
        operations.add(row["operation_identity_sha256"])
        previous = row["row_sha256"]
    return rows, operations


def _charge_budget(
    path: Path, authorization: Mapping[str, Any], operation: str
) -> None:
    rows, operations = _read_budget(path, authorization)
    if operation in operations:
        raise RuntimeError("fresh_audit_r2_budget_duplicate_operation")
    if len(rows) >= int(authorization["budget_maximum_identity_reads"]):
        raise RuntimeError("fresh_audit_r2_budget_exhausted")
    previous = rows[-1]["row_sha256"] if rows else ZERO_SHA256
    row = {
        "kind": "v23_fresh_audit_expanded_reserve_budget_charge",
        "sequence": len(rows),
        "authorization_id": authorization["authorization_id"],
        "stage": "expanded_reserve_registration",
        "charge_ordinal": len(rows),
        "operation_identity_sha256": operation,
        "previous_row_sha256": previous,
        "charged_at": _utc_now(),
    }
    row["row_sha256"] = canonical_sha256(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _registration_identity(
    reader: legacy._FreshAuditSourceReader, source_key: str
) -> dict[str, str]:
    row = reader.connection.execute(
        "SELECT full_text FROM sources WHERE source_key = ?", (source_key,)
    ).fetchone()
    if row is None or not isinstance(row["full_text"], str):
        raise RuntimeError("fresh_audit_r2_registration_source_missing")
    full_text = row["full_text"]
    return {
        "source_key": source_key,
        "source_hash": text_sha256(full_text),
        "normalized_text_hash": normalized_text_sha256(full_text),
    }


def _collect_reserve_identities(
    root: Path,
    config: Mapping[str, Any],
    prior_rows: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[str, list[dict[str, str]]], dict[str, list[dict[str, Any]]]
]:
    design = legacy._load_design_config(root)
    pools = design["frozen_v22_bindings"]["source_pools"]
    excluded_keys = {
        dataset: {
            str(row["source_key"])
            for row in prior_rows
            if row.get("dataset") == dataset and row.get("role") != "genesis"
        }
        for dataset in DATASETS
    }
    excluded_hashes = {
        str(row["source_hash"])
        for row in prior_rows
        if row.get("role") != "genesis"
    }
    excluded_normalized = {
        str(row["normalized_text_hash"])
        for row in prior_rows
        if row.get("role") != "genesis"
    }
    development_count = int(
        config["reserve_group"]["development_source_count_per_dataset"]
    )
    identities: dict[str, list[dict[str, str]]] = {}
    snapshots: dict[str, list[dict[str, Any]]] = {}
    for dataset in DATASETS:
        selected: list[dict[str, str]] = []
        snapshot: list[dict[str, Any]] = []
        with legacy._FreshAuditSourceReader(
            root, dataset, pools[dataset]
        ) as reader:
            for index in range(development_count, len(reader.source_order)):
                source_key = reader.source_order[index]
                if source_key in excluded_keys[dataset]:
                    continue
                identity = _registration_identity(reader, source_key)
                if (
                    identity["source_hash"] in excluded_hashes
                    or identity["normalized_text_hash"] in excluded_normalized
                ):
                    continue
                selected.append(identity)
                snapshot.append(
                    {"source_order_index": index, "source_key": source_key}
                )
                excluded_keys[dataset].add(source_key)
                excluded_hashes.add(identity["source_hash"])
                excluded_normalized.add(identity["normalized_text_hash"])
                if len(selected) == _reserve_count(config, dataset):
                    break
        if len(selected) != _reserve_count(config, dataset):
            raise RuntimeError(
                f"fresh_audit_r2_reserve_capacity_shortfall:{dataset}"
            )
        identities[dataset] = selected
        snapshots[dataset] = snapshot
    return identities, snapshots


def _batch_id(
    config: Mapping[str, Any],
    *,
    dataset: str,
    identities: Sequence[Mapping[str, str]],
    expected_prior_tip: str,
    attempt_id: str,
) -> str:
    return canonical_sha256(
        {
            "kind": "v23_reservation_batch",
            "protocol_revision_id": config["execution_reservation_revision"],
            "attempt_id": attempt_id,
            "role": "fresh_audit_reserve",
            "dataset": dataset,
            "expected_batch_size": len(identities),
            "ordered_source_identity_sha256": canonical_sha256(
                [dict(item) for item in identities]
            ),
            "expected_prior_ledger_tip_sha256": expected_prior_tip,
        }
    )


def _validate_batch_rows(
    root: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    config: Mapping[str, Any],
    dataset: str,
    identities: Sequence[Mapping[str, str]],
    expected_prior_tip: str,
    attempt_id: str,
) -> dict[str, Any] | None:
    batch_id = _batch_id(
        config,
        dataset=dataset,
        identities=identities,
        expected_prior_tip=expected_prior_tip,
        attempt_id=attempt_id,
    )
    matches = [row for row in rows if row.get("reservation_batch_id") == batch_id]
    if not matches:
        return None
    if len(matches) < len(identities):
        return None
    if len(matches) > len(identities):
        raise RuntimeError("fresh_audit_r2_reservation_batch_partial")
    matches.sort(key=lambda row: int(row["reservation_batch_index"]))
    prior_indices = [
        index for index, row in enumerate(rows) if row.get("row_sha256") == expected_prior_tip
    ]
    if len(prior_indices) != 1:
        raise RuntimeError("fresh_audit_r2_reservation_prior_tip_missing")
    first_sequence = prior_indices[0] + 1
    for index, (row, identity) in enumerate(zip(matches, identities, strict=True)):
        expected = {
            "kind": "v23_consumed_source",
            "sequence": first_sequence + index,
            "protocol_revision_id": config["execution_reservation_revision"],
            "attempt_id": attempt_id,
            "reservation_batch_id": batch_id,
            "reservation_batch_index": index,
            "reservation_batch_size": len(identities),
            "role": "fresh_audit_reserve",
            "dataset": dataset,
            **dict(identity),
            "reason": "v23_fresh_audit_expanded_reserve_registration",
        }
        if any(row.get(key) != value for key, value in expected.items()):
            raise RuntimeError("fresh_audit_r2_reservation_batch_identity_drift")
        previous = expected_prior_tip if index == 0 else matches[index - 1]["row_sha256"]
        if row.get("previous_row_sha256") != previous:
            raise RuntimeError("fresh_audit_r2_reservation_batch_chain_drift")
    anchor_sha256: str | None = None
    try:
        anchor_path = _find_anchor(root, config, matches[-1]["row_sha256"])
    except RuntimeError as error:
        if str(error) != "fresh_audit_r2_ledger_tip_anchor_invalid":
            raise
    else:
        anchor_sha256 = sha256_file(anchor_path)
    return {
        "reservation_batch_id": batch_id,
        "ledger_tip_sha256": matches[-1]["row_sha256"],
        "anchor_sha256": anchor_sha256,
        "first_sequence": first_sequence,
    }


def _append_batch(
    root: Path,
    config: Mapping[str, Any],
    authorization: Mapping[str, Any],
    *,
    dataset: str,
    identities: Sequence[Mapping[str, str]],
    expected_prior_tip: str,
    plan_path: Path,
) -> dict[str, Any]:
    attempt_id = str(authorization["authorization_id"])
    batch_id = _batch_id(
        config,
        dataset=dataset,
        identities=identities,
        expected_prior_tip=expected_prior_tip,
        attempt_id=attempt_id,
    )
    plan = {
        "kind": "v23_reservation_plan",
        "protocol_revision_id": config["execution_reservation_revision"],
        "attempt_id": attempt_id,
        "role": "fresh_audit_reserve",
        "dataset": dataset,
        "expected_prior_ledger_tip_sha256": expected_prior_tip,
        "ordered_source_identity_objects": [dict(item) for item in identities],
    }
    _write_or_validate_json(plan_path, plan)
    ledger_path = _ledger_path(root, config)
    budget_path = _resolve(
        Path("artifacts/v23/governance/authorization_budgets")
        / f"{authorization['authorization_id']}.jsonl",
        root,
    )
    with _exclusive_lock(ledger_path.with_suffix(ledger_path.suffix + ".lock")):
        rows = _read_ledger(ledger_path)
        completed = _validate_batch_rows(
            root,
            rows,
            config=config,
            dataset=dataset,
            identities=identities,
            expected_prior_tip=expected_prior_tip,
            attempt_id=attempt_id,
        )
        if completed is not None:
            if completed["anchor_sha256"] is not None:
                return completed
            anchor = {
                "kind": "v23_ledger_tip_anchor",
                "protocol_revision_id": config["execution_reservation_revision"],
                "attempt_id": attempt_id,
                "reservation_batch_id": batch_id,
                "first_sequence": completed["first_sequence"],
                "last_sequence": completed["first_sequence"]
                + len(identities)
                - 1,
                "batch_size": len(identities),
                "prior_ledger_tip_sha256": expected_prior_tip,
                "ledger_tip_sha256": completed["ledger_tip_sha256"],
                "created_at": _utc_now(),
            }
            anchor_path = _anchor_directory(root, config) / (
                f"{anchor['last_sequence']:012d}_{completed['ledger_tip_sha256']}.json"
            )
            _write_or_validate_json(anchor_path, anchor)
            return {
                **completed,
                "anchor_sha256": sha256_file(anchor_path),
            }
        prior_indices = [
            index
            for index, row in enumerate(rows)
            if row.get("row_sha256") == expected_prior_tip
        ]
        if len(prior_indices) != 1:
            raise RuntimeError("fresh_audit_r2_reservation_prior_tip_missing")
        first_sequence = prior_indices[0] + 1
        tail = rows[first_sequence:]
        if len(tail) > len(identities):
            raise RuntimeError("fresh_audit_r2_reservation_unexpected_tail")
        for index, row in enumerate(tail):
            if (
                row.get("reservation_batch_id") != batch_id
                or row.get("reservation_batch_index") != index
            ):
                raise RuntimeError("fresh_audit_r2_reservation_prefix_drift")
        _, charged_operations = _read_budget(budget_path, authorization)
        for index, identity in enumerate(identities[: len(tail)]):
            operation = canonical_sha256(
                {
                    "kind": "v23_fresh_audit_expanded_reserve_identity_read",
                    "reservation_batch_id": batch_id,
                    "reservation_batch_index": index,
                    "source_key": identity["source_key"],
                }
            )
            if operation not in charged_operations:
                raise RuntimeError(
                    "fresh_audit_r2_reservation_row_without_budget_charge"
                )
        previous = tail[-1]["row_sha256"] if tail else expected_prior_tip
        with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            for index in range(len(tail), len(identities)):
                identity = identities[index]
                operation = canonical_sha256(
                    {
                        "kind": "v23_fresh_audit_expanded_reserve_identity_read",
                        "reservation_batch_id": batch_id,
                        "reservation_batch_index": index,
                        "source_key": identity["source_key"],
                    }
                )
                _charge_budget(budget_path, authorization, operation)
                row = {
                    "kind": "v23_consumed_source",
                    "sequence": first_sequence + index,
                    "protocol_revision_id": config["execution_reservation_revision"],
                    "attempt_id": attempt_id,
                    "reservation_batch_id": batch_id,
                    "reservation_batch_index": index,
                    "reservation_batch_size": len(identities),
                    "role": "fresh_audit_reserve",
                    "dataset": dataset,
                    **identity,
                    "consumed_at": _utc_now(),
                    "reason": "v23_fresh_audit_expanded_reserve_registration",
                    "previous_row_sha256": previous,
                }
                row["row_sha256"] = canonical_sha256(row)
                handle.write(canonical_json(row) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                previous = row["row_sha256"]
        anchor = {
            "kind": "v23_ledger_tip_anchor",
            "protocol_revision_id": config["execution_reservation_revision"],
            "attempt_id": attempt_id,
            "reservation_batch_id": batch_id,
            "first_sequence": first_sequence,
            "last_sequence": first_sequence + len(identities) - 1,
            "batch_size": len(identities),
            "prior_ledger_tip_sha256": expected_prior_tip,
            "ledger_tip_sha256": previous,
            "created_at": _utc_now(),
        }
        anchor_path = _anchor_directory(root, config) / (
            f"{anchor['last_sequence']:012d}_{previous}.json"
        )
        _write_or_validate_json(anchor_path, anchor)
    return {
        "reservation_batch_id": batch_id,
        "ledger_tip_sha256": previous,
        "anchor_sha256": sha256_file(anchor_path),
    }


def _load_snapshot_identities(
    root: Path,
    config: Mapping[str, Any],
    snapshots: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, list[dict[str, str]]]:
    design = legacy._load_design_config(root)
    pools = design["frozen_v22_bindings"]["source_pools"]
    output: dict[str, list[dict[str, str]]] = {}
    for dataset in DATASETS:
        identities: list[dict[str, str]] = []
        with legacy._FreshAuditSourceReader(
            root, dataset, pools[dataset]
        ) as reader:
            for item in snapshots[dataset]:
                index = item.get("source_order_index")
                source_key = item.get("source_key")
                if (
                    isinstance(index, bool)
                    or not isinstance(index, int)
                    or index < 0
                    or index >= len(reader.source_order)
                    or reader.source_order[index] != source_key
                ):
                    raise RuntimeError("fresh_audit_r2_snapshot_order_drift")
                identities.append(_registration_identity(reader, str(source_key)))
        if len(identities) != _reserve_count(config, dataset):
            raise RuntimeError("fresh_audit_r2_snapshot_count_drift")
        output[dataset] = identities
    return output


def register_reserve_group(
    *, project_root: str | Path = ".", authorization_path: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_preparation_config(root)
    policy = validate_policy_freeze(root)
    authorization = validate_reservation_authorization(
        project_root=root, authorization_path=authorization_path
    )
    ledger_path = _ledger_path(root, config)
    directory = _reservation_directory(root, config)
    prior_tip = str(config["reserve_group"]["prior_ledger_tip_sha256"])
    prior_snapshot_path = directory / "prior_snapshot.json"
    completion_path = directory / "group_completion.json"
    if completion_path.is_file():
        return validate_reserve_group(root)
    rows = _read_ledger(ledger_path)
    if (
        not rows
        or rows[-1]["row_sha256"] != prior_tip
        and not prior_snapshot_path.is_file()
    ):
        raise RuntimeError("fresh_audit_r2_registration_prior_tip_drift")
    snapshot_paths = {
        dataset: directory / f"{dataset}_reserve_snapshot.json"
        for dataset in DATASETS
    }
    metadata_presence = [prior_snapshot_path.is_file()] + [
        path.is_file() for path in snapshot_paths.values()
    ]
    if any(metadata_presence) and not all(metadata_presence):
        raise RuntimeError("fresh_audit_r2_registration_metadata_partial")
    if all(metadata_presence):
        snapshots = {
            dataset: _read_json(snapshot_paths[dataset])["ordered_sources"]
            for dataset in DATASETS
        }
        identities = _load_snapshot_identities(root, config, snapshots)
    else:
        identities, snapshots = _collect_reserve_identities(root, config, rows)
        directory.mkdir(parents=True, exist_ok=True)
        snapshot_hashes: list[str] = []
        for dataset in DATASETS:
            pool = legacy._load_design_config(root)["frozen_v22_bindings"][
                "source_pools"
            ][dataset]
            snapshot = {
                "kind": "v23_fresh_audit_reserve_snapshot",
                "specification_version": config["specification_version"],
                "protocol_revision_id": config[
                    "execution_reservation_revision"
                ],
                "dataset": dataset,
                "prior_ledger_tip_sha256": prior_tip,
                "source_order_file_sha256": pool["source_order_file_sha256"],
                "ordered_sources": list(snapshots[dataset]),
            }
            _write_or_validate_json(snapshot_paths[dataset], snapshot)
            snapshot_hashes.append(sha256_file(snapshot_paths[dataset]))
        prior_snapshot = {
            "kind": "v23_revision_reservation_prior_snapshot",
            "protocol_revision_id": config["execution_reservation_revision"],
            "common_prior_ledger_tip_sha256": prior_tip,
            "common_prior_tip_anchor_sha256": sha256_file(
                _find_anchor(root, config, prior_tip)
            ),
            "dataset_order": list(DATASETS),
            "ordered_reserve_snapshot_sha256": snapshot_hashes,
        }
        _write_or_validate_json(prior_snapshot_path, prior_snapshot)
    current_tip = prior_tip
    batch_ids: list[str] = []
    for dataset in DATASETS:
        plan_path = directory / "plans" / "fresh_audit_reserve" / f"{dataset}.json"
        if plan_path.is_file():
            plan = _read_json(plan_path)
            if plan.get("expected_prior_ledger_tip_sha256") != current_tip:
                raise RuntimeError("fresh_audit_r2_registration_plan_tip_drift")
            plan_identities = plan.get("ordered_source_identity_objects")
            if plan_identities != identities[dataset]:
                raise RuntimeError("fresh_audit_r2_registration_plan_identity_drift")
        result = _append_batch(
            root,
            config,
            authorization,
            dataset=dataset,
            identities=identities[dataset],
            expected_prior_tip=current_tip,
            plan_path=plan_path,
        )
        current_tip = result["ledger_tip_sha256"]
        batch_ids.append(result["reservation_batch_id"])
    completion = {
        "kind": "v23_revision_reservation_group_complete",
        "protocol_revision_id": config["execution_reservation_revision"],
        "common_prior_snapshot_sha256": sha256_file(prior_snapshot_path),
        "ordered_reservation_batch_ids": batch_ids,
        "final_ledger_tip_sha256": current_tip,
        "final_tip_anchor_sha256": sha256_file(
            _find_anchor(root, config, current_tip)
        ),
        "created_at": _utc_now(),
    }
    _write_or_validate_json(completion_path, completion)
    budget_path = _resolve(
        Path("artifacts/v23/governance/authorization_budgets")
        / f"{authorization['authorization_id']}.jsonl",
        root,
    )
    budget_rows, _ = _read_budget(budget_path, authorization)
    if len(budget_rows) != int(authorization["budget_maximum_identity_reads"]):
        raise RuntimeError("fresh_audit_r2_registration_budget_incomplete")
    return {
        "status": "passed",
        "policy_freeze_identity_sha256": policy[
            "policy_freeze_identity_sha256"
        ],
        "execution_reservation_revision": config[
            "execution_reservation_revision"
        ],
        "reserve_source_count_by_dataset": dict(
            config["reserve_group"]["reserve_source_count_by_dataset"]
        ),
        "final_ledger_tip_sha256": current_tip,
        "reservation_group_path": directory.relative_to(root).as_posix(),
        "source_content_persisted": False,
        "external_calls_performed": 0,
    }


def validate_reserve_group(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    validate_policy_freeze(root)
    config = load_preparation_config(root)
    directory = _reservation_directory(root, config)
    prior_path = directory / "prior_snapshot.json"
    completion_path = directory / "group_completion.json"
    if not prior_path.is_file() or not completion_path.is_file():
        raise RuntimeError("fresh_audit_r2_reservation_group_missing")
    prior = _read_json(prior_path)
    completion = _read_json(completion_path)
    _assert_exact_fields(
        prior,
        {
            "kind",
            "protocol_revision_id",
            "common_prior_ledger_tip_sha256",
            "common_prior_tip_anchor_sha256",
            "dataset_order",
            "ordered_reserve_snapshot_sha256",
        },
        kind="fresh_audit_r2_prior_snapshot",
    )
    _assert_exact_fields(
        completion,
        {
            "kind",
            "protocol_revision_id",
            "common_prior_snapshot_sha256",
            "ordered_reservation_batch_ids",
            "final_ledger_tip_sha256",
            "final_tip_anchor_sha256",
            "created_at",
        },
        kind="fresh_audit_r2_group_completion",
    )
    prior_tip = str(config["reserve_group"]["prior_ledger_tip_sha256"])
    if (
        prior["kind"] != "v23_revision_reservation_prior_snapshot"
        or prior["protocol_revision_id"]
        != config["execution_reservation_revision"]
        or prior["common_prior_ledger_tip_sha256"] != prior_tip
        or prior["dataset_order"] != list(DATASETS)
        or completion["kind"] != "v23_revision_reservation_group_complete"
        or completion["protocol_revision_id"]
        != config["execution_reservation_revision"]
        or completion["common_prior_snapshot_sha256"] != sha256_file(prior_path)
        or len(completion["ordered_reservation_batch_ids"]) != len(DATASETS)
    ):
        raise RuntimeError("fresh_audit_r2_reservation_group_identity_drift")
    rows = _read_ledger(_ledger_path(root, config))
    if rows[-1]["row_sha256"] != completion["final_ledger_tip_sha256"]:
        raise RuntimeError("fresh_audit_r2_reservation_group_tip_drift")
    current_tip = prior_tip
    batch_ids: list[str] = []
    snapshot_hashes: list[str] = []
    attempt_ids: set[str] = set()
    for dataset in DATASETS:
        reserve = _validate_reserve_metadata(root, config, dataset)
        snapshot_hashes.append(reserve["snapshot_sha256"])
        plan = _read_json(reserve["plan_path"])
        attempt_ids.add(str(plan["attempt_id"]))
        identities = plan["ordered_source_identity_objects"]
        result = _validate_batch_rows(
            root,
            rows,
            config=config,
            dataset=dataset,
            identities=identities,
            expected_prior_tip=current_tip,
            attempt_id=str(plan["attempt_id"]),
        )
        if result is None:
            raise RuntimeError("fresh_audit_r2_reservation_batch_missing")
        if result["anchor_sha256"] is None:
            raise RuntimeError("fresh_audit_r2_reservation_batch_anchor_missing")
        current_tip = result["ledger_tip_sha256"]
        batch_ids.append(result["reservation_batch_id"])
    if (
        current_tip != completion["final_ledger_tip_sha256"]
        or batch_ids != completion["ordered_reservation_batch_ids"]
        or snapshot_hashes != prior["ordered_reserve_snapshot_sha256"]
    ):
        raise RuntimeError("fresh_audit_r2_reservation_group_hash_drift")
    if len(attempt_ids) != 1:
        raise RuntimeError("fresh_audit_r2_reservation_attempt_identity_drift")
    attempt_id = attempt_ids.pop()
    authorization_path = _resolve(
        Path("artifacts/v23/governance/run_authorizations")
        / f"{attempt_id}.json",
        root,
    )
    authorization = validate_reservation_authorization(
        project_root=root, authorization_path=authorization_path
    )
    budget_path = _resolve(
        Path("artifacts/v23/governance/authorization_budgets")
        / f"{attempt_id}.jsonl",
        root,
    )
    budget_rows, _ = _read_budget(budget_path, authorization)
    if len(budget_rows) != sum(
        _reserve_count(config, dataset) for dataset in DATASETS
    ):
        raise RuntimeError("fresh_audit_r2_reservation_budget_count_drift")
    validation_identity = canonical_sha256(
        {
            "prior_snapshot_sha256": sha256_file(prior_path),
            "completion_sha256": sha256_file(completion_path),
            "batch_ids": batch_ids,
            "snapshot_hashes": snapshot_hashes,
        }
    )
    return {
        "status": "passed",
        "execution_reservation_revision": config[
            "execution_reservation_revision"
        ],
        "final_ledger_tip_sha256": current_tip,
        "reservation_validation_sha256": validation_identity,
        "source_content_read": False,
        "external_calls_performed": 0,
    }


def status(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_preparation_config(root)
    policy_status = "not_started"
    policy_identity = None
    if _resolve(POLICY_FREEZE_PATH, root).is_file():
        try:
            policy = validate_policy_freeze(root)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            policy_status = f"stale:{error}"
        else:
            policy_status = "passed"
            policy_identity = policy["policy_freeze_identity_sha256"]
    reservation_status = "not_started"
    if (_reservation_directory(root, config) / "group_completion.json").is_file():
        try:
            validate_reserve_group(root)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            reservation_status = f"stale:{error}"
        else:
            reservation_status = "passed"
    freeze_status = "not_started"
    freeze_identity = None
    if _resolve(FREEZE_MANIFEST_PATH, root).is_file():
        try:
            freeze = validate_preparation_freeze(root)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            freeze_status = f"stale:{error}"
        else:
            freeze_status = "passed"
            freeze_identity = freeze["freeze_identity_sha256"]
    return {
        "kind": "v23_fresh_audit_expanded_reserve_status",
        "status": "policy_frozen_downstream_blocked",
        "runner_revision": RUNNER_REVISION,
        "execution_reservation_revision": config[
            "execution_reservation_revision"
        ],
        "policy_freeze_status": policy_status,
        "policy_freeze_identity_sha256": policy_identity,
        "reservation_group_status": reservation_status,
        "preparation_freeze_status": freeze_status,
        "preparation_freeze_identity_sha256": freeze_identity,
        "reserve_source_count_by_dataset": dict(
            config["reserve_group"]["reserve_source_count_by_dataset"]
        ),
        "source_content_read": False,
        "external_calls_performed": 0,
        "api_allowed": False,
        "victim_allowed": False,
        "retriever_allowed": False,
        "formal_experiment_allowed": False,
    }
