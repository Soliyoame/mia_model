"""Final single-router context calibration for PCV-MIA v22."""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..attack.attackability_context_overlay import (
    DEFAULT_OVERLAY_WEIGHTS,
    OVERLAY_VERSION,
    overlay_pair,
    r3_pair_is_eligible,
)
from ..attack.attackability_selector import MAIN_ENTITY_TYPES
from ..attack.semantic_entity_resolver import ALL_SEMANTIC_SCHEMA, SemanticPredictionBackend
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import load_yaml, read_json, read_jsonl, write_json, write_jsonl_atomic
from .attackability_calibration_r2 import (
    _commit_is_ancestor,
    _git_commit,
    _relative,
    _resolve,
    _source_evidence_excerpt,
    _validate_base_protocol_for_extension,
    _validate_source_pool_for_extension,
)
from .attackability_v22 import (
    REVIEW_FIELDS,
    REVIEW_VALUES,
    _identity,
    _pilot_rows,
    _structural_controls,
    _validate_label_rows,
    load_single_router,
    load_v22_config,
)


R3_PROTOCOL = "pcv_v22_attackability_calibration_r3"
R3_PLAN_PROTOCOL = "pcv_v22_attackability_calibration_plan_r3"
R3_CONTEXT_PLAN_PROTOCOL = "pcv_v22_attackability_context_plan_r3"
R3_CONTEXT_CHECKPOINT_PROTOCOL = "pcv_v22_attackability_context_checkpoint_r3"
R3_CONTEXT_MANIFEST_PROTOCOL = "pcv_v22_attackability_context_manifest_r3"
R3_LABEL_RECEIPT_PROTOCOL = "pcv_v22_attackability_assistant_labels_r3"
R3_EVALUATION_PROTOCOL = "pcv_v22_attackability_calibration_evaluation_r3"
R3_THRESHOLD_PROTOCOL = "pcv_v22_attackability_threshold_r3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_r3_config(config_path: str | Path) -> dict[str, Any]:
    config = load_yaml(config_path)
    if config.get("protocol") != R3_PROTOCOL:
        raise RuntimeError("v22 calibration r3 protocol drift")
    if config.get("method_version") != "pcv-attackability-first-v22":
        raise RuntimeError("v22 calibration r3 method drift")
    if config.get("context_overlay", {}).get("version") != OVERLAY_VERSION:
        raise RuntimeError("v22 calibration r3 overlay version drift")
    weights = dict(config.get("context_overlay", {}).get("weights") or {})
    if weights != DEFAULT_OVERLAY_WEIGHTS:
        raise RuntimeError("v22 calibration r3 overlay weights drift")
    router = dict(config.get("single_router_validation") or {})
    base = dict(config.get("base_v22") or {})
    base_config = load_yaml(base.get("config_path"))
    if (
        router.get("model_id") != base_config.get("routing", {}).get("single_model_id")
        or router.get("model_revision")
        != base_config.get("routing", {}).get("single_model_revision")
        or router.get("model_role")
        != base_config.get("routing", {}).get("single_model_role")
    ):
        raise RuntimeError("v22 calibration r3 single-router identity drift")
    if router.get("device") != "cuda" or not bool(router.get("local_files_only")):
        raise RuntimeError("v22 calibration r3 requires local CUDA router")
    if not bool(router.get("require_exact_counterfactual_span")) or not bool(
        router.get("require_same_effective_type")
    ):
        raise RuntimeError("v22 calibration r3 context validation policy drift")
    review = dict(config.get("review") or {})
    if (
        review.get("mode") != "assistant_only_no_human_validation"
        or bool(review.get("human_review_required"))
        or bool(review.get("human_validation_claim_allowed"))
        or set(review.get("allowed_values") or ()) != set(REVIEW_VALUES)
    ):
        raise RuntimeError("v22 calibration r3 review policy drift")
    calibration = dict(config.get("calibration") or {})
    if int(calibration.get("total_rows", -1)) != 300 or int(
        calibration.get("cells", -1)
    ) != 15:
        raise RuntimeError("v22 calibration r3 row budget drift")
    boundaries = dict(config.get("boundaries") or {})
    forbidden = (
        "membership_visible",
        "victim_response_visible",
        "attack_auc_visible",
        "api_calls_allowed",
        "victim_calls_allowed",
        "retriever_runs_allowed",
        "formal_scan_allowed_before_r3_pass",
    )
    if any(bool(boundaries.get(field)) for field in forbidden):
        raise RuntimeError("v22 calibration r3 boundary drift")
    return config


def _validate_bound_file(
    root: Path, path_value: str, expected_hash: str, description: str
) -> Path:
    path = _resolve(path_value, root)
    if not path.is_file() or sha256_file(path) != expected_hash:
        raise RuntimeError(f"v22 calibration r3 bound artifact drift: {description}")
    return path


def _load_base_and_superseded(
    config: Mapping[str, Any], root: Path
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    base = dict(config["base_v22"])
    base_config_path = _validate_bound_file(
        root, str(base["config_path"]), str(base["config_sha256"]), "base config"
    )
    base_config = load_v22_config(base_config_path)
    protocol_path = _validate_bound_file(
        root,
        str(base["protocol_manifest_path"]),
        str(base["protocol_manifest_sha256"]),
        "base protocol manifest",
    )
    protocol_manifest = read_json(protocol_path)
    _validate_base_protocol_for_extension(base_config, protocol_manifest, root)
    if protocol_manifest.get("protocol_identity_sha256") != base.get(
        "protocol_identity_sha256"
    ):
        raise RuntimeError("v22 calibration r3 base protocol identity drift")

    records: dict[str, dict[str, Any]] = {}
    private_rows: list[dict[str, Any]] = []
    for revision in ("superseded_r1", "superseded_r2"):
        binding = dict(config[revision])
        plan_path = _validate_bound_file(
            root,
            str(binding["calibration_plan_path"]),
            str(binding["calibration_plan_sha256"]),
            f"{revision} plan",
        )
        plan = read_json(plan_path)
        if plan.get("calibration_plan_identity_sha256") != binding.get(
            "calibration_plan_identity_sha256"
        ) or plan.get("calibration_plan_identity_sha256") != _identity(
            plan, "created_at", "calibration_plan_identity_sha256"
        ):
            raise RuntimeError(f"v22 calibration r3 {revision} plan identity drift")
        private_binding = dict(plan["artifacts"]["private_key"])
        private_path = _validate_bound_file(
            root,
            str(private_binding["path"]),
            str(private_binding["sha256"]),
            f"{revision} private key",
        )
        private_rows.extend(read_jsonl(private_path))
        evaluation_path = _validate_bound_file(
            root,
            str(binding["evaluation_path"]),
            str(binding["evaluation_sha256"]),
            f"{revision} evaluation",
        )
        evaluation = read_json(evaluation_path)
        if (
            evaluation.get("status") != binding.get("required_status")
            or evaluation.get("evaluation_identity_sha256")
            != binding.get("evaluation_identity_sha256")
            or evaluation.get("evaluation_identity_sha256")
            != _identity(evaluation, "created_at", "evaluation_identity_sha256")
        ):
            raise RuntimeError(f"v22 calibration r3 {revision} evaluation drift")
        if evaluation.get("attack_auc_accessed") or evaluation.get(
            "victim_responses_accessed"
        ):
            raise RuntimeError("v22 calibration r3 cannot follow outcome-informed tuning")
        if revision == "superseded_r2":
            _validate_bound_file(
                root,
                str(binding["assistant_labels_receipt_path"]),
                str(binding["assistant_labels_receipt_sha256"]),
                "r2 assistant label receipt",
            )
        records[revision] = {"plan": plan, "evaluation": evaluation}
    return base_config, records, private_rows


def _runtime_bundle(config: Mapping[str, Any], root: Path) -> list[dict[str, str]]:
    bundle: list[dict[str, str]] = []
    for raw_path in config.get("runtime_files") or ():
        path = _resolve(str(raw_path), root)
        if not path.is_file():
            raise RuntimeError(f"v22 calibration r3 runtime file missing: {path}")
        bundle.append({"path": _relative(path, root), "sha256": sha256_file(path)})
    return bundle


def _assert_runtime_committed(config: Mapping[str, Any], root: Path) -> None:
    paths = [
        _relative(_resolve(str(value), root), root)
        for value in config.get("runtime_files") or ()
    ]
    for path in paths:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"v22 calibration r3 runtime is not committed: {path}")
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *paths], cwd=root)
    if changed.returncode == 1:
        raise RuntimeError("v22 calibration r3 runtime has uncommitted changes")
    if changed.returncode != 0:
        raise RuntimeError("v22 calibration r3 git identity check failed")


def _exclusions(rows: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    fields = {
        "pair_ids": "pair_id",
        "source_keys": "source_key",
        "fact_signatures": "fact_signature",
    }
    return {
        name: {
            str(row[field])
            for row in rows
            if row.get(field) is not None and str(row.get(field) or "")
        }
        for name, field in fields.items()
    }


def _available_overlay_rows(
    pilot_rows: Sequence[Mapping[str, Any]], exclusions: Mapping[str, set[str]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in pilot_rows:
        if str(raw.get("effective_type") or "") not in MAIN_ENTITY_TYPES:
            continue
        if str(raw.get("pair_id") or "") in exclusions["pair_ids"]:
            continue
        if str(raw.get("source_key") or "") in exclusions["source_keys"]:
            continue
        if str(raw.get("fact_signature") or "") in exclusions["fact_signatures"]:
            continue
        row = overlay_pair(raw)
        if bool(row.get("r3_hard_gate_passed")):
            output.append(row)
    return output


def _score_strata(rows: Sequence[Mapping[str, Any]], count: int) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        signature = str(row.get("fact_signature") or row.get("pair_id") or "")
        current = unique.get(signature)
        if current is None or float(row.get("r3_utility_score", 0.0)) > float(
            current.get("r3_utility_score", 0.0)
        ):
            unique[signature] = row
    ordered = sorted(
        unique.values(),
        key=lambda row: (
            float(row.get("r3_utility_score", 0.0)),
            str(row.get("pair_id") or ""),
        ),
    )
    if len(ordered) < count:
        raise RuntimeError(
            f"v22 calibration r3 cell shortfall: required={count} available={len(ordered)}"
        )
    selected: list[dict[str, Any]] = []
    for stratum in range(4):
        start = len(ordered) * stratum // 4
        end = len(ordered) * (stratum + 1) // 4
        bucket = sorted(
            ordered[start:end],
            key=lambda row: (
                sha256_text(
                    "\0".join(
                        (R3_PROTOCOL, str(stratum), str(row.get("pair_id") or ""))
                    )
                ),
                str(row.get("pair_id") or ""),
            ),
        )
        selected.extend(bucket[: count // 4])
    if len(selected) != count:
        raise RuntimeError("v22 calibration r3 score-strata allocation drift")
    return selected


def _context_output(config: Mapping[str, Any], root: Path) -> Path:
    return _resolve(str(config["output_root"]), root) / "context_validation"


def _prediction_match(row: Mapping[str, Any], prediction: Mapping[str, Any], minimum: float) -> bool:
    span = row.get("counterfactual_span")
    return (
        isinstance(span, (list, tuple))
        and len(span) == 2
        and str(prediction.get("label") or "").upper()
        == str(row.get("effective_type") or "").upper()
        and int(prediction.get("start", -1)) == int(span[0])
        and int(prediction.get("end", -1)) == int(span[1])
        and float(prediction.get("score", 0.0)) >= minimum
    )


def freeze_context_plan(
    config_path: str | Path, *, resume: bool, project_root: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_r3_config(config_file)
    _assert_runtime_committed(config, root)
    base_config, records, private_rows = _load_base_and_superseded(config, root)
    output = _context_output(config, root)
    plan_path = output / "context_plan.json"
    if plan_path.exists():
        if not resume:
            raise RuntimeError("v22 calibration r3 context plan is already frozen")
        plan = _load_context_plan(config, root)
        return {"status": "frozen", "rows": plan["row_count"], "resumed": True}
    pilot_rows, checkpoints = _pilot_rows(base_config, root)
    rows = _available_overlay_rows(pilot_rows, _exclusions(private_rows))
    rows.sort(key=lambda row: (str(row["dataset"]), str(row["pair_id"])))
    rows_path = output / "context_candidates.jsonl"
    write_jsonl_atomic(rows, rows_path)
    batches: list[dict[str, Any]] = []
    batch_rows = int(config["single_router_validation"]["batch_rows"])
    for index, start in enumerate(range(0, len(rows), batch_rows)):
        batch = rows[start : start + batch_rows]
        batches.append(
            {
                "batch_index": index,
                "start": start,
                "end": start + len(batch),
                "pair_ids_sha256": sha256_obj([str(row["pair_id"]) for row in batch]),
            }
        )
    plan: dict[str, Any] = {
        "protocol": R3_CONTEXT_PLAN_PROTOCOL,
        "status": "frozen_before_context_predictions",
        "created_at": _utc_now(),
        "config_path": _relative(config_file, root),
        "config_sha256": sha256_file(config_file),
        "runtime_bundle": _runtime_bundle(config, root),
        "code_commit": _git_commit(root),
        "base_protocol_identity_sha256": config["base_v22"]["protocol_identity_sha256"],
        "superseded_identities": {
            key: value["evaluation"]["evaluation_identity_sha256"]
            for key, value in records.items()
        },
        "excluded_counts": {key: len(value) for key, value in _exclusions(private_rows).items()},
        "row_count": len(rows),
        "candidate_rows_path": _relative(rows_path, root),
        "candidate_rows_sha256": sha256_file(rows_path),
        "batches": batches,
        "pilot_checkpoint_identities": {
            dataset: value["checkpoint_identity_sha256"]
            for dataset, value in sorted(checkpoints.items())
        },
        "single_router_model": {
            key: config["single_router_validation"][key]
            for key in ("model_role", "model_id", "model_revision")
        },
        "attack_auc_accessed": False,
        "victim_responses_accessed": False,
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs": 0,
    }
    plan["context_plan_identity_sha256"] = _identity(
        plan, "created_at", "context_plan_identity_sha256"
    )
    write_json(plan, plan_path)
    checkpoint = {
        "protocol": R3_CONTEXT_CHECKPOINT_PROTOCOL,
        "status": "paused",
        "context_plan_identity_sha256": plan["context_plan_identity_sha256"],
        "completed_batches": [],
    }
    checkpoint["checkpoint_identity_sha256"] = _identity(
        checkpoint, "checkpoint_identity_sha256"
    )
    write_json(checkpoint, output / "context_checkpoint.json")
    return {
        "status": "frozen",
        "rows": len(rows),
        "batches": len(batches),
        "plan": str(plan_path),
        "resumed": False,
    }


def _load_context_plan(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    output = _context_output(config, root)
    plan_path = output / "context_plan.json"
    if not plan_path.is_file():
        raise RuntimeError("v22 calibration r3 context plan is not frozen")
    plan = read_json(plan_path)
    if plan.get("protocol") != R3_CONTEXT_PLAN_PROTOCOL or plan.get(
        "context_plan_identity_sha256"
    ) != _identity(plan, "created_at", "context_plan_identity_sha256"):
        raise RuntimeError("v22 calibration r3 context plan identity drift")
    if plan.get("config_sha256") != sha256_file(
        _resolve(str(plan["config_path"]), root)
    ) or plan.get("runtime_bundle") != _runtime_bundle(config, root):
        raise RuntimeError("v22 calibration r3 context runtime drift")
    if not _commit_is_ancestor(root, str(plan.get("code_commit") or "")):
        raise RuntimeError("v22 calibration r3 code commit is not an ancestor")
    rows_path = _resolve(str(plan["candidate_rows_path"]), root)
    if not rows_path.is_file() or sha256_file(rows_path) != plan.get(
        "candidate_rows_sha256"
    ):
        raise RuntimeError("v22 calibration r3 context candidates drift")
    return plan


def run_context_validation(
    config_path: str | Path,
    *,
    resume: bool,
    max_new_batches: int,
    project_root: str | Path,
    injected_backend: SemanticPredictionBackend | None = None,
) -> dict[str, Any]:
    if not resume or max_new_batches < 1:
        raise RuntimeError("v22 calibration r3 context validation requires bounded resume")
    root = Path(project_root).resolve()
    config = load_r3_config(Path(config_path).resolve())
    plan = _load_context_plan(config, root)
    output = _context_output(config, root)
    checkpoint_path = output / "context_checkpoint.json"
    checkpoint = read_json(checkpoint_path)
    if checkpoint.get("protocol") != R3_CONTEXT_CHECKPOINT_PROTOCOL or checkpoint.get(
        "checkpoint_identity_sha256"
    ) != _identity(checkpoint, "checkpoint_identity_sha256"):
        raise RuntimeError("v22 calibration r3 context checkpoint drift")
    rows = list(read_jsonl(_resolve(str(plan["candidate_rows_path"]), root)))
    completed = {int(value) for value in checkpoint.get("completed_batches") or ()}
    pending = [
        batch for batch in plan["batches"] if int(batch["batch_index"]) not in completed
    ][:max_new_batches]
    if not pending:
        return _finalize_context(config, plan, rows, root)
    base_config = load_v22_config(_resolve(str(config["base_v22"]["config_path"]), root))
    backend, metadata = load_single_router(
        base_config, root=root, injected_backend=injected_backend
    )
    expected = config["single_router_validation"]
    if (
        metadata.get("model_id") != expected["model_id"]
        or metadata.get("revision") != expected["model_revision"]
        or metadata.get("role") != expected["model_role"]
    ):
        raise RuntimeError("v22 calibration r3 loaded router identity drift")
    minimum = float(expected["minimum_prediction_score"])
    for batch in pending:
        index = int(batch["batch_index"])
        subset = rows[int(batch["start"]) : int(batch["end"])]
        texts = [str(row["counterfactual_claim"]) for row in subset]
        if hasattr(backend, "predict_batch"):
            raw = backend.predict_batch(  # type: ignore[attr-defined]
                texts,
                ALL_SEMANTIC_SCHEMA,
                batch_size=int(expected["inference_batch_size"]),
            )
        else:
            raw = [backend.predict(text, ALL_SEMANTIC_SCHEMA) for text in texts]
        if len(raw) != len(subset):
            raise RuntimeError("v22 calibration r3 context prediction count drift")
        validated: list[dict[str, Any]] = []
        for row, predictions in zip(subset, raw, strict=True):
            payload = [asdict(value) for value in predictions]
            matches = [
                value for value in payload if _prediction_match(row, value, minimum)
            ]
            validated.append(
                {
                    "pair_id": row["pair_id"],
                    "dataset": row["dataset"],
                    "effective_type": row["effective_type"],
                    "context_validation_passed": bool(matches),
                    "matching_predictions": matches,
                    "all_predictions": payload,
                }
            )
        prediction_path = output / "batches" / f"batch_{index:04d}.jsonl"
        write_jsonl_atomic(validated, prediction_path)
        manifest: dict[str, Any] = {
            "protocol": R3_CONTEXT_MANIFEST_PROTOCOL,
            "status": "complete",
            "completed_at": _utc_now(),
            "context_plan_identity_sha256": plan["context_plan_identity_sha256"],
            "batch_index": index,
            "row_count": len(validated),
            "pair_ids_sha256": batch["pair_ids_sha256"],
            "prediction_path": _relative(prediction_path, root),
            "prediction_sha256": sha256_file(prediction_path),
            "single_router_metadata": metadata,
            "api_calls_performed": 0,
            "victim_calls_performed": 0,
            "retriever_runs": 0,
        }
        manifest["manifest_identity_sha256"] = _identity(
            manifest, "completed_at", "manifest_identity_sha256"
        )
        write_json(manifest, output / "batches" / f"batch_{index:04d}.manifest.json")
        completed.add(index)
        checkpoint = {
            "protocol": R3_CONTEXT_CHECKPOINT_PROTOCOL,
            "status": "passed" if len(completed) == len(plan["batches"]) else "paused",
            "context_plan_identity_sha256": plan["context_plan_identity_sha256"],
            "completed_batches": sorted(completed),
        }
        checkpoint["checkpoint_identity_sha256"] = _identity(
            checkpoint, "checkpoint_identity_sha256"
        )
        write_json(checkpoint, checkpoint_path)
    if len(completed) == len(plan["batches"]):
        return _finalize_context(config, plan, rows, root)
    return {
        "status": "paused",
        "completed_batches": len(completed),
        "total_batches": len(plan["batches"]),
        "new_batches": len(pending),
        "checkpoint": str(checkpoint_path),
    }


def _finalize_context(
    config: Mapping[str, Any],
    plan: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    root: Path,
) -> dict[str, Any]:
    output = _context_output(config, root)
    by_pair: dict[str, dict[str, Any]] = {}
    for batch in plan["batches"]:
        index = int(batch["batch_index"])
        manifest_path = output / "batches" / f"batch_{index:04d}.manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("v22 calibration r3 context batch incomplete")
        manifest = read_json(manifest_path)
        if manifest.get("manifest_identity_sha256") != _identity(
            manifest, "completed_at", "manifest_identity_sha256"
        ):
            raise RuntimeError("v22 calibration r3 context batch identity drift")
        prediction_path = _resolve(str(manifest["prediction_path"]), root)
        if sha256_file(prediction_path) != manifest.get("prediction_sha256"):
            raise RuntimeError("v22 calibration r3 context prediction drift")
        for value in read_jsonl(prediction_path):
            pair_id = str(value["pair_id"])
            if pair_id in by_pair:
                raise RuntimeError("v22 calibration r3 duplicate context prediction")
            by_pair[pair_id] = value
    if set(by_pair) != {str(row["pair_id"]) for row in rows}:
        raise RuntimeError("v22 calibration r3 context prediction coverage drift")
    merged: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        validation = by_pair[str(row["pair_id"])]
        row["r3_context_validation_passed"] = bool(
            validation["context_validation_passed"]
        )
        row["r3_context_matching_predictions"] = validation["matching_predictions"]
        merged.append(row)
    merged_path = output / "context_validated_candidates.jsonl"
    if not merged_path.exists():
        write_jsonl_atomic(merged, merged_path)
    elif sha256_obj(list(read_jsonl(merged_path))) != sha256_obj(merged):
        raise RuntimeError("v22 calibration r3 merged context candidates drift")
    report = {
        "status": "passed",
        "rows": len(merged),
        "context_validated_rows": sum(
            bool(row["r3_context_validation_passed"]) for row in merged
        ),
        "merged_path": str(merged_path),
        "merged_sha256": sha256_file(merged_path),
    }
    return report


def _context_rows(config: Mapping[str, Any], root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plan = _load_context_plan(config, root)
    output = _context_output(config, root)
    merged_path = output / "context_validated_candidates.jsonl"
    if not merged_path.is_file():
        raise RuntimeError("v22 calibration r3 context validation is incomplete")
    return list(read_jsonl(merged_path)), plan


def _anonymous_review_id(*parts: str) -> str:
    return "v22_c3_" + sha256_text("\0".join((R3_PROTOCOL, *parts)))[:24]


def _blinded(review_id: str, row: Mapping[str, Any], evidence: str) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "true_claim": str(row["true_claim"]),
        "counterfactual_claim": str(row["counterfactual_claim"]),
        "original_entity": str(row["original_entity"]),
        "counterfactual_entity": str(row["counterfactual_entity"]),
        "source_evidence_excerpt": evidence,
    }


def _template(review_id: str) -> dict[str, Any]:
    return {
        "review_id": review_id,
        **{field: None for field in REVIEW_FIELDS},
        "reason_codes": [],
        "evidence": "",
    }


def check_r3_capacity(config_path: str | Path, *, project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_r3_config(Path(config_path).resolve())
    rows, _ = _context_rows(config, root)
    eligible = [row for row in rows if bool(row.get("r3_context_validation_passed"))]
    counts = {
        f"{dataset}/{entity_type}": len(
            {
                str(row.get("fact_signature") or row.get("pair_id") or "")
                for row in eligible
                if row.get("dataset") == dataset
                and row.get("effective_type") == entity_type
            }
        )
        for dataset in ("edgar", "enron", "pubmed")
        for entity_type in sorted(MAIN_ENTITY_TYPES)
    }
    required = int(config["calibration"]["real_rows_per_cell"])
    return {
        "status": "passed" if all(value >= required for value in counts.values()) else "failed_capacity_shortfall",
        "required_real_rows_per_cell": required,
        "available_unique_facts_by_cell": counts,
        "minimum_available": min(counts.values()),
        "external_calls": 0,
    }


def freeze_calibration_r3(
    config_path: str | Path, *, resume: bool, project_root: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_r3_config(config_file)
    _assert_runtime_committed(config, root)
    base_config, records, private_rows = _load_base_and_superseded(config, root)
    rows, context_plan = _context_rows(config, root)
    eligible = [row for row in rows if bool(row.get("r3_context_validation_passed"))]
    output = _resolve(str(config["output_root"]), root)
    plan_path = output / "calibration_plan.json"
    if plan_path.exists():
        if not resume:
            raise RuntimeError("v22 calibration r3 is already frozen")
        plan = _load_calibration_plan(config, root)
        return {"status": "frozen", "rows": plan["row_count"], "resumed": True}
    blinded_rows: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    templates: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    real_per_cell = int(config["calibration"]["real_rows_per_cell"])
    controls_per_cell = int(config["calibration"]["structural_controls_per_cell"])
    for dataset in ("edgar", "enron", "pubmed"):
        source_manifest = _validate_source_pool_for_extension(
            base_config,
            dataset,
            str(config["base_v22"]["protocol_identity_sha256"]),
            root,
        )
        for entity_type in sorted(MAIN_ENTITY_TYPES):
            selected = _score_strata(
                [
                    row
                    for row in eligible
                    if row.get("dataset") == dataset
                    and row.get("effective_type") == entity_type
                ],
                real_per_cell,
            )
            for row in selected:
                review_id = _anonymous_review_id("real", dataset, entity_type, str(row["pair_id"]))
                evidence = _source_evidence_excerpt(source_manifest, row, root)
                blinded_rows.append(_blinded(review_id, row, evidence))
                templates.append(_template(review_id))
                key_rows.append(
                    {
                        "review_id": review_id,
                        "dataset": dataset,
                        "effective_type": entity_type,
                        "row_kind": "real_candidate",
                        "pair_id": row["pair_id"],
                        "source_key": row["source_key"],
                        "fact_signature": row["fact_signature"],
                        "utility_score": row["r3_utility_score"],
                        "expected_attack_usable": None,
                    }
                )
                selected_ids.append(str(row["pair_id"]))
            for control_index, (control, reason) in enumerate(
                _structural_controls(dataset, entity_type, selected[:controls_per_cell])
            ):
                review_id = _anonymous_review_id(
                    "control", dataset, entity_type, reason, str(control.get("pair_id") or "")
                )
                evidence = _source_evidence_excerpt(
                    source_manifest, selected[control_index], root
                )
                blinded = _blinded(review_id, control, evidence)
                if reason == "source_span_or_grounding_mismatch":
                    blinded["source_evidence_excerpt"] = str(control["source_evidence_excerpt"])
                blinded_rows.append(blinded)
                templates.append(_template(review_id))
                key_rows.append(
                    {
                        "review_id": review_id,
                        "dataset": dataset,
                        "effective_type": entity_type,
                        "row_kind": "structural_control",
                        "control_reason": reason,
                        "pair_id": None,
                        "source_key": None,
                        "fact_signature": None,
                        "utility_score": None,
                        "expected_attack_usable": "no",
                    }
                )
    if len(blinded_rows) != int(config["calibration"]["total_rows"]):
        raise RuntimeError("v22 calibration r3 total row drift")
    blinded_rows.sort(key=lambda row: str(row["review_id"]))
    key_rows.sort(key=lambda row: str(row["review_id"]))
    templates.sort(key=lambda row: str(row["review_id"]))
    blinded_path = output / "calibration_blinded.jsonl"
    private_path = output / "private" / "calibration_key.jsonl"
    template_path = output / "private" / "assistant_labels.template.jsonl"
    write_jsonl_atomic(blinded_rows, blinded_path)
    write_jsonl_atomic(key_rows, private_path)
    write_jsonl_atomic(templates, template_path)
    current = _exclusions(private_rows)
    real = [row for row in key_rows if row["row_kind"] == "real_candidate"]
    overlap = {
        "pair_ids": len(current["pair_ids"] & set(selected_ids)),
        "source_keys": len(current["source_keys"] & {str(row["source_key"]) for row in real}),
        "fact_signatures": len(current["fact_signatures"] & {str(row["fact_signature"]) for row in real}),
    }
    if any(overlap.values()):
        raise RuntimeError(f"v22 calibration r3 overlaps earlier calibration: {overlap}")
    plan: dict[str, Any] = {
        "protocol": R3_PLAN_PROTOCOL,
        "status": "frozen_before_assistant_labels",
        "created_at": _utc_now(),
        "config_path": _relative(config_file, root),
        "config_sha256": sha256_file(config_file),
        "runtime_bundle": _runtime_bundle(config, root),
        "code_commit": _git_commit(root),
        "base_protocol_identity_sha256": config["base_v22"]["protocol_identity_sha256"],
        "context_plan_identity_sha256": context_plan["context_plan_identity_sha256"],
        "superseded_identities": {
            key: value["evaluation"]["evaluation_identity_sha256"]
            for key, value in records.items()
        },
        "earlier_labels_reused": False,
        "row_count": len(blinded_rows),
        "real_row_count": len(real),
        "structural_control_count": len(key_rows) - len(real),
        "cell_count": int(config["calibration"]["cells"]),
        "earlier_exclusion_counts": {key: len(value) for key, value in current.items()},
        "earlier_overlap": overlap,
        "selected_pair_ids_sha256": sha256_obj(sorted(selected_ids)),
        "review_ids_sha256": sha256_obj(sorted(str(row["review_id"]) for row in blinded_rows)),
        "review_mode": config["review"]["mode"],
        "human_review_required": False,
        "human_validation_claim_allowed": False,
        "artifacts": {
            "blinded": {"path": _relative(blinded_path, root), "sha256": sha256_file(blinded_path)},
            "private_key": {"path": _relative(private_path, root), "sha256": sha256_file(private_path)},
            "assistant_template": {"path": _relative(template_path, root), "sha256": sha256_file(template_path)},
        },
        "attack_auc_accessed": False,
        "victim_responses_accessed": False,
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
        "rows": len(blinded_rows),
        "real_rows": len(real),
        "structural_controls": len(key_rows) - len(real),
        "plan": str(plan_path),
        "assistant_template": str(template_path),
        "resumed": False,
    }


def _load_calibration_plan(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve(str(config["output_root"]), root) / "calibration_plan.json"
    if not path.is_file():
        raise RuntimeError("v22 calibration r3 is not frozen")
    plan = read_json(path)
    if plan.get("protocol") != R3_PLAN_PROTOCOL or plan.get(
        "calibration_plan_identity_sha256"
    ) != _identity(plan, "created_at", "calibration_plan_identity_sha256"):
        raise RuntimeError("v22 calibration r3 plan identity drift")
    if plan.get("runtime_bundle") != _runtime_bundle(config, root):
        raise RuntimeError("v22 calibration r3 runtime bundle drift")
    if not _commit_is_ancestor(root, str(plan.get("code_commit") or "")):
        raise RuntimeError("v22 calibration r3 commit is not an ancestor")
    for artifact in plan["artifacts"].values():
        value = _resolve(str(artifact["path"]), root)
        if not value.is_file() or sha256_file(value) != artifact["sha256"]:
            raise RuntimeError("v22 calibration r3 artifact drift")
    return plan


def validate_r3_assistant_labels(
    config_path: str | Path, labels_path: str | Path, *, project_root: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_r3_config(Path(config_path).resolve())
    plan = _load_calibration_plan(config, root)
    expected = {
        str(row["review_id"])
        for row in read_jsonl(_resolve(str(plan["artifacts"]["blinded"]["path"]), root))
    }
    labels_file = Path(labels_path).resolve()
    labels = _validate_label_rows(labels_file, expected_ids=expected)
    receipt: dict[str, Any] = {
        "protocol": R3_LABEL_RECEIPT_PROTOCOL,
        "status": "validated",
        "reviewer_role": "assistant",
        "review_mode": config["review"]["mode"],
        "human_review_performed": False,
        "calibration_plan_identity_sha256": plan["calibration_plan_identity_sha256"],
        "labels_path": _relative(labels_file, root),
        "labels_sha256": sha256_file(labels_file),
        "rows": len(labels),
        "attack_usable_counts": dict(Counter(str(row["attack_usable"]) for row in labels.values())),
    }
    receipt["receipt_identity_sha256"] = _identity(receipt, "receipt_identity_sha256")
    path = _resolve(str(config["output_root"]), root) / "private" / "assistant_labels_receipt.json"
    if path.exists() and read_json(path) != receipt:
        raise RuntimeError("v22 calibration r3 assistant label receipt drift")
    if not path.exists():
        write_json(receipt, path)
    return {"status": "validated", "rows": len(labels), "counts": receipt["attack_usable_counts"], "receipt": str(path)}


def _select_source_rows(rows: Sequence[Mapping[str, Any]], threshold: float, required: int, maximum: int) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(row) for row in rows if r3_pair_is_eligible(row, threshold) and bool(row.get("r3_context_validation_passed"))),
        key=lambda row: (-float(row["r3_utility_score"]), str(row["fact_signature"]), str(row["pair_id"])),
    )
    selected: list[dict[str, Any]] = []
    facts: set[str] = set()
    entities: Counter[str] = Counter()
    for row in ordered:
        fact = str(row["fact_signature"])
        entity = " ".join(str(row["original_entity"]).casefold().split())
        if fact in facts or entities[entity] >= maximum:
            continue
        selected.append(row)
        facts.add(fact)
        entities[entity] += 1
        if len(selected) == required:
            break
    return selected


def _projection(config: Mapping[str, Any], base_config: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], threshold: float, root: Path) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    required = int(base_config["candidate_extraction"]["required_pairs_per_source"])
    maximum = int(base_config["candidate_extraction"]["maximum_pairs_per_original_entity"])
    for dataset in ("edgar", "enron", "pubmed"):
        grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            if row.get("dataset") == dataset:
                grouped[str(row["source_key"])].append(row)
        eligible = sum(len(_select_source_rows(value, threshold, required, maximum)) == required for value in grouped.values())
        scanned = int(config["calibration"]["projection_sources_per_dataset"])
        manifest = _validate_source_pool_for_extension(
            base_config, dataset, str(config["base_v22"]["protocol_identity_sha256"]), root
        )
        result[dataset] = {
            "pilot_sources": scanned,
            "eligible_sources": eligible,
            "eligible_rate": eligible / max(1, scanned),
            "processed_pool_sources": int(manifest["source_count"]),
            "projected_eligible_sources": eligible / max(1, scanned) * int(manifest["source_count"]),
        }
    return result


def evaluate_calibration_r3(
    config_path: str | Path, labels_path: str | Path, *, project_root: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_r3_config(config_file)
    plan = _load_calibration_plan(config, root)
    private = list(read_jsonl(_resolve(str(plan["artifacts"]["private_key"]["path"]), root)))
    labels_file = Path(labels_path).resolve()
    labels = _validate_label_rows(labels_file, expected_ids={str(row["review_id"]) for row in private})
    receipt_path = _resolve(str(config["output_root"]), root) / "private" / "assistant_labels_receipt.json"
    if not receipt_path.is_file():
        raise RuntimeError("v22 calibration r3 assistant labels are not validated")
    receipt = read_json(receipt_path)
    if receipt.get("labels_sha256") != sha256_file(labels_file) or receipt.get(
        "calibration_plan_identity_sha256"
    ) != plan["calibration_plan_identity_sha256"]:
        raise RuntimeError("v22 calibration r3 assistant label receipt drift")
    controls = [row for row in private if row["row_kind"] == "structural_control"]
    real = [row for row in private if row["row_kind"] == "real_candidate"]
    control_rate = sum(labels[str(row["review_id"])]["attack_usable"] == "no" for row in controls) / max(1, len(controls))
    uncertain_rate = sum(labels[str(row["review_id"])]["attack_usable"] == "uncertain" for row in real) / max(1, len(real))
    label_by_pair = {str(row["pair_id"]): labels[str(row["review_id"])]["attack_usable"] for row in real}
    base_config, _, _ = _load_base_and_superseded(config, root)
    context_rows, _ = _context_rows(config, root)
    gates_cfg = dict(config["calibration"]["gates"])
    grid: list[dict[str, Any]] = []
    for raw_threshold in config["calibration"]["threshold_grid"]:
        threshold = float(raw_threshold)
        labelled = [row for row in real if float(row["utility_score"]) >= threshold and label_by_pair[str(row["pair_id"])] in {"yes", "no"}]
        rate = sum(label_by_pair[str(row["pair_id"])] == "yes" for row in labelled) / max(1, len(labelled))
        projection = _projection(config, base_config, context_rows, threshold, root)
        enough = len(labelled) >= int(gates_cfg["minimum_labelled_real_candidates_per_threshold"])
        grid.append(
            {
                "threshold": threshold,
                "labelled_real_candidates": len(labelled),
                "assistant_judged_usability_rate": rate,
                "retained_context_validated_candidates": sum(r3_pair_is_eligible(row, threshold) and bool(row.get("r3_context_validation_passed")) for row in context_rows),
                "projection": projection,
                "minimum_label_count_passed": enough,
                "usability_rate_gate_passed": enough and rate >= float(gates_cfg["threshold_minimum_assistant_judged_usability_rate"]),
                "projection_gate_passed": all(value["projected_eligible_sources"] >= float(gates_cfg["minimum_projected_eligible_sources_per_dataset"]) for value in projection.values()),
            }
        )
    admissible = [row for row in grid if row["usability_rate_gate_passed"] and row["projection_gate_passed"]]
    selected = sorted(admissible, key=lambda row: (-int(row["retained_context_validated_candidates"]), float(row["threshold"])))[0] if admissible else None
    gates = {
        "structural_negative_rejection": control_rate >= float(gates_cfg["structural_negative_rejection_rate"]),
        "maximum_real_uncertain_rate": uncertain_rate <= float(gates_cfg["maximum_real_uncertain_rate"]),
        "threshold_available": selected is not None,
    }
    report: dict[str, Any] = {
        "protocol": R3_EVALUATION_PROTOCOL,
        "status": "passed" if all(gates.values()) else "failed_final_calibration_revision",
        "created_at": _utc_now(),
        "calibration_plan_identity_sha256": plan["calibration_plan_identity_sha256"],
        "assistant_labels_sha256": sha256_file(labels_file),
        "review_mode": config["review"]["mode"],
        "calibration_supervision": "assistant_only_surrogate_labels",
        "human_review_performed": False,
        "human_validation_claim_allowed": False,
        "precision_against_human_gold_available": False,
        "structural_negative_rejection_rate": control_rate,
        "real_uncertain_rate": uncertain_rate,
        "gates": gates,
        "threshold_grid": grid,
        "selected_threshold": selected["threshold"] if selected else None,
        "attack_auc_accessed": False,
        "victim_responses_accessed": False,
        "api_calls_performed": 0,
        "victim_calls_performed": 0,
        "retriever_runs": 0,
    }
    report["evaluation_identity_sha256"] = _identity(report, "created_at", "evaluation_identity_sha256")
    output = _resolve(str(config["output_root"]), root)
    report_path = output / "calibration_evaluation.json"
    if report_path.exists():
        existing = read_json(report_path)
        report["created_at"] = existing["created_at"]
        report["evaluation_identity_sha256"] = _identity(report, "created_at", "evaluation_identity_sha256")
        if existing != report:
            raise RuntimeError("v22 calibration r3 evaluation is immutable")
        report = existing
    else:
        write_json(report, report_path)
    if report["status"] == "passed" and selected is not None:
        threshold: dict[str, Any] = {
            "protocol": R3_THRESHOLD_PROTOCOL,
            "status": "passed_assistant_only_no_human_validation",
            "created_at": _utc_now(),
            "method_version": config["method_version"],
            "config_sha256": sha256_file(config_file),
            "base_protocol_identity_sha256": plan["base_protocol_identity_sha256"],
            "calibration_evaluation_sha256": sha256_file(report_path),
            "calibration_evaluation_identity_sha256": report["evaluation_identity_sha256"],
            "selected_threshold": selected["threshold"],
            "selected_projection": selected["projection"],
            "selection_rule": config["calibration"]["threshold_selection"],
            "review_mode": config["review"]["mode"],
            "human_validation_claim_allowed": False,
        }
        threshold["threshold_identity_sha256"] = _identity(threshold, "created_at", "threshold_identity_sha256")
        threshold_path = output / "threshold_manifest.json"
        if not threshold_path.exists():
            write_json(threshold, threshold_path)
    return {"status": report["status"], "selected_threshold": report["selected_threshold"], "gates": gates, "report": str(report_path)}


def r3_status(config_path: str | Path, *, project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_r3_config(Path(config_path).resolve())
    output = _resolve(str(config["output_root"]), root)
    context = output / "context_validation"
    plan = output / "calibration_plan.json"
    receipt = output / "private" / "assistant_labels_receipt.json"
    evaluation = output / "calibration_evaluation.json"
    threshold = output / "threshold_manifest.json"
    status = "not_started"
    if (context / "context_plan.json").is_file():
        status = "context_plan_frozen"
    if (context / "context_checkpoint.json").is_file():
        status = str(read_json(context / "context_checkpoint.json").get("status") or status)
    if plan.is_file():
        status = "frozen_waiting_for_assistant_labels"
    if receipt.is_file():
        status = "assistant_labels_validated"
    if evaluation.is_file():
        status = str(read_json(evaluation).get("status") or "evaluation_invalid")
    return {
        "protocol": R3_PROTOCOL,
        "status": status,
        "context_plan_frozen": (context / "context_plan.json").is_file(),
        "context_predictions_complete": (context / "context_validated_candidates.jsonl").is_file(),
        "calibration_plan_frozen": plan.is_file(),
        "assistant_labels_validated": receipt.is_file(),
        "evaluation_present": evaluation.is_file(),
        "threshold_frozen": threshold.is_file(),
        "external_calls": 0,
    }
