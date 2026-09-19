"""Offline r2 pair selection that reuses immutable v23 Fact Layer r1 facts."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..attack.restoration_first_v23 import (
    canonical_sha256,
    reject_forbidden_selection_fields,
)
from ..attack.restoration_first_v23_fact_layer import FACT_LAYER_SPECIFICATION_VERSION
from ..attack.restoration_first_v23_fact_layer_selection_r2 import (
    SELECTION_R2_SPECIFICATION_VERSION,
    select_pairs_from_r1_facts,
)
from ..utils.hash import sha256_file
from ..utils.io import load_yaml
from .restoration_first_v23 import (
    _pool_contract,
    _read_json,
    _resolve,
    capacity_decision,
    load_design_config,
)
from .restoration_first_v23_fact_layer import (
    _fact_paths,
    _read_jsonl,
    _utc_now,
    _write_new_json,
    _write_or_validate_jsonl,
    fact_layer_attempt_identity,
    validate_facts,
)


SELECTION_R2_CONFIG_PATH = Path(
    "configs/restoration_first_v23_fact_layer_selection_r2.yaml"
)
SELECTION_R2_IMPLEMENTATION_FILES = (
    Path("src/attack/restoration_first_v23_fact_layer_selection_r2.py"),
    Path("src/prepare/restoration_first_v23_fact_layer_selection_r2.py"),
    SELECTION_R2_CONFIG_PATH,
)


def _load_selection_config(root: Path) -> dict[str, Any]:
    config = load_yaml(_resolve(SELECTION_R2_CONFIG_PATH, root))
    if not isinstance(config, Mapping):
        raise RuntimeError("selection_r2_config_invalid")
    expected = {
        "protocol_version": "pcv-mia-v23",
        "method_version": "pcv-restoration-first-v23-fact-layer-selection",
        "specification_version": SELECTION_R2_SPECIFICATION_VERSION,
        "source_fact_specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "external_calls_performed": 0,
    }
    if any(config.get(key) != value for key, value in expected.items()):
        raise RuntimeError("selection_r2_config_identity_drift")
    reject_forbidden_selection_fields(config, path="selection_r2_config")
    return dict(config)


def selection_r2_identity(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    fact_identity = fact_layer_attempt_identity(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    fact_paths = _fact_paths(root, dataset, fact_identity["attempt_id"])
    if not fact_paths["manifest"].is_file():
        raise RuntimeError("selection_r2_source_fact_manifest_missing")
    config = _load_selection_config(root)
    implementation_hashes = {
        path.as_posix(): sha256_file(_resolve(path, root))
        for path in SELECTION_R2_IMPLEMENTATION_FILES
    }
    scientific_identity = {
        "kind": "v23_fact_layer_selection_r2_scientific_identity",
        "specification_version": SELECTION_R2_SPECIFICATION_VERSION,
        "source_fact_specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "dataset": dataset,
        "source_fact_attempt_id": fact_identity["attempt_id"],
        "source_fact_manifest_sha256": sha256_file(fact_paths["manifest"]),
        "selection_config_sha256": sha256_file(
            _resolve(SELECTION_R2_CONFIG_PATH, root)
        ),
        "selection_implementation_file_sha256": implementation_hashes,
        "external_calls_performed": 0,
    }
    reject_forbidden_selection_fields(
        scientific_identity, path="selection_r2_identity"
    )
    scientific_identity_sha256 = canonical_sha256(scientific_identity)
    selection_attempt_id = canonical_sha256(
        {
            "kind": "v23_fact_layer_selection_r2_attempt",
            "scientific_identity_sha256": scientific_identity_sha256,
        }
    )
    return {
        "selection_attempt_id": selection_attempt_id,
        "scientific_identity": scientific_identity,
        "scientific_identity_sha256": scientific_identity_sha256,
        "source_fact_identity": fact_identity,
        "source_fact_paths": fact_paths,
        "config": config,
    }


def _selection_paths(identity: Mapping[str, Any]) -> dict[str, Path]:
    directory = (
        identity["source_fact_paths"]["attempt_directory"]
        / "selection_r2"
        / "attempts"
        / str(identity["selection_attempt_id"])
    )
    return {
        "attempt_directory": directory,
        "execution_manifest": directory / "execution_manifest.json",
        "selection": directory / "selected_pairs.jsonl",
        "diagnostics": directory / "quality_filter_diagnostics.jsonl",
        "selection_manifest": directory / "selection_manifest.json",
        "pilot_manifest": directory / "pilot_manifest.json",
    }


def _write_or_validate_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    if path.exists():
        actual = _read_json(path)
        actual_comparable = {
            key: value for key, value in actual.items() if key != "created_at"
        }
        expected_comparable = {
            key: value for key, value in manifest.items() if key != "created_at"
        }
        if actual_comparable != expected_comparable:
            raise RuntimeError(f"selection_r2_manifest_drift:{path}")
        return
    _write_new_json(path, manifest)


def select_pairs_r2(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or validate a selection-r2 artifact from existing r1 facts."""

    root = Path(project_root).resolve()
    fact_status = validate_facts(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    identity = selection_r2_identity(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    paths = _selection_paths(identity)
    execution_manifest = {
        "kind": "v23_fact_layer_selection_r2_execution",
        "specification_version": SELECTION_R2_SPECIFICATION_VERSION,
        "selection_attempt_id": identity["selection_attempt_id"],
        "scientific_identity_sha256": identity["scientific_identity_sha256"],
        "scientific_identity": identity["scientific_identity"],
        "dataset": dataset,
        "external_calls_performed": 0,
        "created_at": _utc_now(),
    }
    _write_or_validate_manifest(paths["execution_manifest"], execution_manifest)
    facts = _read_jsonl(identity["source_fact_paths"]["facts"])
    result = select_pairs_from_r1_facts(
        facts,
        dataset=dataset,
        selection_identity_sha256=identity["scientific_identity_sha256"],
        config=identity["config"],
    )
    for row in [*result["selected"], *result["diagnostics"]]:
        reject_forbidden_selection_fields(row, path="selection_r2_artifact")
    _write_or_validate_jsonl(paths["selection"], result["selected"])
    _write_or_validate_jsonl(paths["diagnostics"], result["diagnostics"])
    manifest = {
        "kind": "v23_fact_layer_selection_r2_manifest",
        "specification_version": SELECTION_R2_SPECIFICATION_VERSION,
        "source_fact_specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "selection_attempt_id": identity["selection_attempt_id"],
        "selection_scientific_identity_sha256": identity[
            "scientific_identity_sha256"
        ],
        "source_fact_attempt_id": identity["source_fact_identity"]["attempt_id"],
        "dataset": dataset,
        "source_fact_manifest_sha256": sha256_file(
            identity["source_fact_paths"]["manifest"]
        ),
        "execution_manifest_sha256": sha256_file(paths["execution_manifest"]),
        "selected_pairs_file_sha256": sha256_file(paths["selection"]),
        "quality_filter_diagnostics_file_sha256": sha256_file(
            paths["diagnostics"]
        ),
        "selected_pair_count": len(result["selected"]),
        "eligible_source_count": result["eligible_source_count"],
        "candidate_pair_count": result["candidate_pair_count"],
        "raw_candidate_pair_count": result["raw_candidate_pair_count"],
        "quality_rejected_fact_count": result["quality_rejected_fact_count"],
        "rejection_reason_counts": result["rejection_reason_counts"],
        "external_calls_performed": 0,
        "status": "passed",
        "created_at": _utc_now(),
    }
    _write_or_validate_manifest(paths["selection_manifest"], manifest)
    return {
        "status": "passed",
        "dataset": dataset,
        "source_fact_attempt_id": identity["source_fact_identity"]["attempt_id"],
        "selection_attempt_id": identity["selection_attempt_id"],
        "attempt_directory": str(paths["attempt_directory"].relative_to(root)),
        "selected_pair_count": len(result["selected"]),
        "eligible_source_count": result["eligible_source_count"],
        "candidate_pair_count": result["candidate_pair_count"],
        "raw_candidate_pair_count": result["raw_candidate_pair_count"],
        "quality_rejected_fact_count": result["quality_rejected_fact_count"],
        "rejection_reason_counts": result["rejection_reason_counts"],
        "fact_layer_status": fact_status["status"],
        "external_calls_performed": 0,
    }


def run_development_pilot_r2(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute the capacity gate from selection r2 without fact extraction."""

    root = Path(project_root).resolve()
    selection = select_pairs_r2(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    identity = selection_r2_identity(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    paths = _selection_paths(identity)
    pool = _pool_contract(load_design_config(root), dataset)
    reservation = identity["source_fact_identity"]["reservation"]
    capacity = capacity_decision(
        population=int(pool["source_count"]),
        sample=int(reservation["source_count"]),
        observed_eligible=int(selection["eligible_source_count"]),
        consumed_non_development=int(reservation["consumed_non_development_count"]),
    )
    manifest = {
        "kind": "v23_fact_layer_selection_r2_pilot_manifest",
        "specification_version": SELECTION_R2_SPECIFICATION_VERSION,
        "source_fact_specification_version": FACT_LAYER_SPECIFICATION_VERSION,
        "selection_attempt_id": identity["selection_attempt_id"],
        "source_fact_attempt_id": identity["source_fact_identity"]["attempt_id"],
        "dataset": dataset,
        "source_fact_manifest_sha256": sha256_file(
            identity["source_fact_paths"]["manifest"]
        ),
        "selection_manifest_sha256": sha256_file(paths["selection_manifest"]),
        "completed_source_count": reservation["source_count"],
        "eligible_source_count": selection["eligible_source_count"],
        "selected_pair_count": selection["selected_pair_count"],
        "capacity_gate": capacity,
        "external_calls_performed": 0,
        "status": capacity["status"],
        "created_at": _utc_now(),
    }
    _write_or_validate_manifest(paths["pilot_manifest"], manifest)
    return manifest


def validate_development_pilot_r2(
    *,
    project_root: str | Path = ".",
    dataset: str,
    model_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    selection = select_pairs_r2(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    identity = selection_r2_identity(
        project_root=root,
        dataset=dataset,
        model_runtime_identity=model_runtime_identity,
    )
    paths = _selection_paths(identity)
    if not paths["pilot_manifest"].is_file():
        raise RuntimeError("selection_r2_pilot_manifest_missing")
    manifest = _read_json(paths["pilot_manifest"])
    pool = _pool_contract(load_design_config(root), dataset)
    reservation = identity["source_fact_identity"]["reservation"]
    capacity = capacity_decision(
        population=int(pool["source_count"]),
        sample=int(reservation["source_count"]),
        observed_eligible=int(selection["eligible_source_count"]),
        consumed_non_development=int(reservation["consumed_non_development_count"]),
    )
    if (
        manifest.get("kind") != "v23_fact_layer_selection_r2_pilot_manifest"
        or manifest.get("specification_version")
        != SELECTION_R2_SPECIFICATION_VERSION
        or manifest.get("selection_attempt_id")
        != identity["selection_attempt_id"]
        or manifest.get("source_fact_attempt_id")
        != identity["source_fact_identity"]["attempt_id"]
        or manifest.get("source_fact_manifest_sha256")
        != sha256_file(identity["source_fact_paths"]["manifest"])
        or manifest.get("selection_manifest_sha256")
        != sha256_file(paths["selection_manifest"])
        or manifest.get("completed_source_count") != reservation["source_count"]
        or manifest.get("eligible_source_count")
        != selection["eligible_source_count"]
        or manifest.get("selected_pair_count") != selection["selected_pair_count"]
        or manifest.get("capacity_gate") != capacity
        or manifest.get("status") != capacity["status"]
        or manifest.get("external_calls_performed") != 0
    ):
        raise RuntimeError("selection_r2_pilot_manifest_drift")
    return {
        **manifest,
        "fact_layer_status": "passed",
        "selection_status": selection["status"],
        "validation_mode": "recomputed_from_r1_fact_and_r2_selection_artifacts",
    }
