"""Independent assistant-only calibration r2 for PCV-MIA v22."""

from __future__ import annotations

import subprocess
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..attack.attackability_selector import MAIN_ENTITY_TYPES, select_top_pairs
from ..utils.hash import sha256_file, sha256_obj, sha256_text
from ..utils.io import load_yaml, read_json, read_jsonl, write_json, write_jsonl_atomic
from .attackability_v22 import (
    REVIEW_FIELDS,
    REVIEW_VALUES,
    _identity,
    _pilot_rows,
    _structural_controls,
    _validate_label_rows,
    load_v22_config,
)


R2_PROTOCOL = "pcv_v22_attackability_calibration_r2"
R2_PLAN_PROTOCOL = "pcv_v22_attackability_calibration_plan_r2"
R2_LABEL_RECEIPT_PROTOCOL = "pcv_v22_attackability_assistant_labels_r2"
R2_EVALUATION_PROTOCOL = "pcv_v22_attackability_calibration_evaluation_r2"
R2_THRESHOLD_PROTOCOL = "pcv_v22_attackability_threshold_r2"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve(path: str | Path, root: Path) -> Path:
    value = Path(path)
    return value.resolve() if value.is_absolute() else (root / value).resolve()


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def load_r2_config(config_path: str | Path) -> dict[str, Any]:
    config = load_yaml(config_path)
    if config.get("protocol") != R2_PROTOCOL:
        raise RuntimeError("v22 calibration r2 protocol drift")
    if config.get("method_version") != "pcv-attackability-first-v22":
        raise RuntimeError("v22 calibration r2 method drift")
    review = config.get("review") or {}
    if review.get("mode") != "assistant_only_no_human_validation":
        raise RuntimeError("v22 calibration r2 reviewer mode drift")
    if bool(review.get("human_review_required")):
        raise RuntimeError("v22 calibration r2 must not require human review")
    if bool(review.get("human_validation_claim_allowed")):
        raise RuntimeError("v22 calibration r2 cannot claim human validation")
    if bool(review.get("controls_use_machine_ground_truth")) is not True:
        raise RuntimeError("v22 calibration r2 controls must use machine ground truth")
    if set(review.get("allowed_values") or ()) != set(REVIEW_VALUES):
        raise RuntimeError("v22 calibration r2 review values drift")
    calibration = config.get("calibration") or {}
    if int(calibration.get("total_rows", -1)) != 300:
        raise RuntimeError("v22 calibration r2 row budget drift")
    if int(calibration.get("cells", -1)) != 15:
        raise RuntimeError("v22 calibration r2 cell budget drift")
    boundaries = config.get("boundaries") or {}
    for field in ("membership_visible", "victim_response_visible", "attack_auc_visible"):
        if bool(boundaries.get(field)):
            raise RuntimeError(f"v22 calibration r2 forbidden visibility: {field}")
    for field in ("api_calls_allowed", "victim_calls_allowed", "retriever_runs_allowed"):
        if bool(boundaries.get(field)):
            raise RuntimeError(f"v22 calibration r2 external work must be disabled: {field}")
    return config


def _validate_bound_file(
    root: Path, path_value: str, expected_hash: str, description: str
) -> Path:
    path = _resolve(path_value, root)
    if not path.is_file() or sha256_file(path) != expected_hash:
        raise RuntimeError(f"v22 calibration r2 bound artifact drift: {description}")
    return path


def _commit_is_ancestor(root: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=root
    )
    return result.returncode == 0


def _validate_base_protocol_for_extension(
    base_config: Mapping[str, Any], manifest: Mapping[str, Any], root: Path
) -> None:
    if manifest.get("protocol") != "pcv_v22_protocol_manifest_r1" or manifest.get(
        "protocol_identity_sha256"
    ) != _identity(manifest, "created_at", "protocol_identity_sha256"):
        raise RuntimeError("v22 calibration r2 base protocol manifest drift")
    config_path = _resolve(str(manifest["config_path"]), root)
    if not config_path.is_file() or sha256_file(config_path) != manifest.get(
        "config_sha256"
    ):
        raise RuntimeError("v22 calibration r2 base config drift")
    expected_paths = [
        _relative(_resolve(str(path), root), root)
        for path in base_config.get("runtime_files") or ()
    ]
    runtime_bundle = list(manifest.get("runtime_bundle") or ())
    if [str(item.get("path") or "") for item in runtime_bundle] != expected_paths:
        raise RuntimeError("v22 calibration r2 base runtime file list drift")
    for item in runtime_bundle:
        path = _resolve(str(item["path"]), root)
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise RuntimeError(f"v22 calibration r2 base runtime drift: {path}")
    router = dict(manifest.get("single_router_model") or {})
    lock_path = _resolve(str(router.get("model_lock_path") or ""), root)
    if (
        router.get("model_id") != base_config["routing"]["single_model_id"]
        or router.get("revision")
        != base_config["routing"]["single_model_revision"]
        or not lock_path.is_file()
        or sha256_file(lock_path) != router.get("model_lock_sha256")
        or router.get("model_lock_sha256")
        != base_config["routing"]["model_lock_sha256"]
    ):
        raise RuntimeError("v22 calibration r2 base router identity drift")
    ancestor = str(manifest.get("code_commit") or "")
    if not _commit_is_ancestor(root, ancestor):
        raise RuntimeError("v22 calibration r2 base commit is not an ancestor of HEAD")


def _validate_source_pool_for_extension(
    base_config: Mapping[str, Any],
    dataset: str,
    base_protocol_identity: str,
    root: Path,
) -> dict[str, Any]:
    manifest_path = (
        _resolve(str(base_config["output_root"]), root)
        / "source_pools"
        / dataset
        / "source_pool_manifest.json"
    )
    if not manifest_path.is_file():
        raise RuntimeError(f"v22 calibration r2 source pool missing: {dataset}")
    manifest = read_json(manifest_path)
    if (
        manifest.get("protocol") != "pcv_v22_frozen_source_pool_r1"
        or manifest.get("status") != "passed"
        or manifest.get("dataset") != dataset
        or manifest.get("protocol_identity_sha256") != base_protocol_identity
        or manifest.get("source_pool_identity_sha256")
        != _identity(manifest, "created_at", "source_pool_identity_sha256")
    ):
        raise RuntimeError(f"v22 calibration r2 source pool identity drift: {dataset}")
    for path_key, hash_key in (
        ("database_path", "database_sha256"),
        ("source_order_path", "source_order_file_sha256"),
        ("processed_path", "processed_sha256"),
    ):
        path = _resolve(str(manifest[path_key]), root)
        if not path.is_file() or sha256_file(path) != manifest.get(hash_key):
            raise RuntimeError(
                f"v22 calibration r2 source pool artifact drift: {dataset}/{path_key}"
            )
    return manifest


def _projection_by_threshold_r2(
    base_config: Mapping[str, Any],
    pilot_rows: Sequence[Mapping[str, Any]],
    threshold: float,
    base_protocol_identity: str,
    root: Path,
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for dataset in sorted(base_config["source_pools"]):
        by_source: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in pilot_rows:
            if str(row.get("dataset") or "") == dataset:
                by_source[str(row["source_key"])].append(row)
        required_pairs = int(
            base_config["candidate_extraction"]["required_pairs_per_source"]
        )
        eligible = sum(
            len(
                select_top_pairs(
                    rows,
                    threshold=threshold,
                    required_pairs=required_pairs,
                    max_pairs_per_original_entity=int(
                        base_config["candidate_extraction"][
                            "maximum_pairs_per_original_entity"
                        ]
                    ),
                )
            )
            == required_pairs
            for rows in by_source.values()
        )
        scanned = int(base_config["calibration"]["projection_sources_per_dataset"])
        source_manifest = _validate_source_pool_for_extension(
            base_config, dataset, base_protocol_identity, root
        )
        projected = eligible / max(1, scanned) * int(source_manifest["source_count"])
        result[dataset] = {
            "pilot_sources": scanned,
            "eligible_sources": eligible,
            "eligible_rate": eligible / max(1, scanned),
            "processed_pool_sources": int(source_manifest["source_count"]),
            "projected_eligible_sources": projected,
        }
    return result


def _load_base_and_r1(
    config: Mapping[str, Any], root: Path
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
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
        raise RuntimeError("v22 calibration r2 base protocol identity drift")

    r1 = dict(config["superseded_r1"])
    r1_plan_path = _validate_bound_file(
        root,
        str(r1["calibration_plan_path"]),
        str(r1["calibration_plan_sha256"]),
        "r1 calibration plan",
    )
    r1_plan = read_json(r1_plan_path)
    if r1_plan.get("calibration_plan_identity_sha256") != r1.get(
        "calibration_plan_identity_sha256"
    ) or r1_plan.get("calibration_plan_identity_sha256") != _identity(
        r1_plan, "created_at", "calibration_plan_identity_sha256"
    ):
        raise RuntimeError("v22 calibration r2 r1 plan identity drift")
    private_binding = dict(r1_plan["artifacts"]["private_key"])
    private_path = _validate_bound_file(
        root,
        str(private_binding["path"]),
        str(private_binding["sha256"]),
        "r1 private key",
    )
    private_rows = list(read_jsonl(private_path))

    evaluation_path = _validate_bound_file(
        root,
        str(r1["evaluation_path"]),
        str(r1["evaluation_sha256"]),
        "r1 evaluation",
    )
    evaluation = read_json(evaluation_path)
    if evaluation.get("status") != r1.get("required_status"):
        raise RuntimeError("v22 calibration r2 r1 status drift")
    if evaluation.get("evaluation_identity_sha256") != r1.get(
        "evaluation_identity_sha256"
    ) or evaluation.get("evaluation_identity_sha256") != _identity(
        evaluation, "created_at", "evaluation_identity_sha256"
    ):
        raise RuntimeError("v22 calibration r2 r1 evaluation identity drift")
    if evaluation.get("attack_auc_accessed") or evaluation.get(
        "victim_responses_accessed"
    ):
        raise RuntimeError("v22 calibration r2 cannot follow an AUC/victim-informed failure")
    return base_config, r1_plan, private_rows, evaluation


def _runtime_bundle(config: Mapping[str, Any], root: Path) -> list[dict[str, str]]:
    bundle: list[dict[str, str]] = []
    for raw_path in config.get("runtime_files") or ():
        path = _resolve(str(raw_path), root)
        if not path.is_file():
            raise RuntimeError(f"v22 calibration r2 runtime file missing: {path}")
        bundle.append({"path": _relative(path, root), "sha256": sha256_file(path)})
    return bundle


def _git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if len(commit) != 40:
        raise RuntimeError("v22 calibration r2 code commit unavailable")
    return commit


def _assert_runtime_committed(config: Mapping[str, Any], root: Path) -> None:
    relative_paths = [
        _relative(_resolve(str(item), root), root)
        for item in config.get("runtime_files") or ()
    ]
    for relative_path in relative_paths:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative_path],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if tracked.returncode != 0:
            raise RuntimeError(
                f"v22 calibration r2 runtime is not committed: {relative_path}"
            )
    changed = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *relative_paths], cwd=root
    )
    if changed.returncode == 1:
        raise RuntimeError("v22 calibration r2 runtime has uncommitted changes")
    if changed.returncode != 0:
        raise RuntimeError("v22 calibration r2 git identity check failed")


def _r1_exclusions(private_rows: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    return {
        "pair_ids": {
            str(row["pair_id"]) for row in private_rows if row.get("pair_id") is not None
        },
        "source_keys": {
            str(row["source_key"])
            for row in private_rows
            if row.get("source_key") is not None
        },
        "fact_signatures": {
            str(row["fact_signature"])
            for row in private_rows
            if row.get("fact_signature") is not None
        },
    }


def _available_rows(
    pilot_rows: Sequence[Mapping[str, Any]], exclusions: Mapping[str, set[str]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw_row in pilot_rows:
        row = dict(raw_row)
        if not bool(row.get("hard_gate_passed")):
            continue
        if str(row.get("effective_type") or "") not in MAIN_ENTITY_TYPES:
            continue
        if str(row.get("pair_id") or "") in exclusions["pair_ids"]:
            continue
        if str(row.get("source_key") or "") in exclusions["source_keys"]:
            continue
        if str(row.get("fact_signature") or "") in exclusions["fact_signatures"]:
            continue
        output.append(row)
    return output


def _score_strata_r2(rows: Sequence[Mapping[str, Any]], count: int) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for raw_row in rows:
        row = dict(raw_row)
        signature = str(row.get("fact_signature") or row.get("pair_id") or "")
        current = unique.get(signature)
        if current is None or float(row.get("utility_score", 0.0)) > float(
            current.get("utility_score", 0.0)
        ):
            unique[signature] = row
    ordered = sorted(
        unique.values(),
        key=lambda row: (float(row.get("utility_score", 0.0)), str(row.get("pair_id") or "")),
    )
    if len(ordered) < count:
        raise RuntimeError(
            f"v22 calibration r2 cell shortfall: required={count} available={len(ordered)}"
        )
    selected: list[dict[str, Any]] = []
    strata = 4
    per_stratum = count // strata
    for stratum in range(strata):
        start = len(ordered) * stratum // strata
        end = len(ordered) * (stratum + 1) // strata
        bucket = sorted(
            ordered[start:end],
            key=lambda row: (
                sha256_text(
                    "\0".join(
                        (
                            R2_PROTOCOL,
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
        raise RuntimeError("v22 calibration r2 score-strata allocation drift")
    return selected


def _anonymous_review_id(*parts: str) -> str:
    return "v22_c2_" + sha256_text("\0".join((R2_PROTOCOL, *parts)))[:24]


def _source_evidence_excerpt(
    source_manifest: Mapping[str, Any],
    row: Mapping[str, Any],
    root: Path,
    *,
    context_chars: int = 240,
) -> str:
    database_path = _resolve(str(source_manifest["database_path"]), root)
    connection = sqlite3.connect(database_path)
    try:
        record = connection.execute(
            "SELECT full_text FROM sources WHERE source_key = ?",
            (str(row["source_key"]),),
        ).fetchone()
    finally:
        connection.close()
    if record is None:
        raise RuntimeError("v22 calibration r2 source text missing")
    source = " ".join(str(record[0]).split())
    claim = " ".join(str(row["true_claim"]).split())
    position = source.find(claim)
    if position < 0:
        raise RuntimeError("v22 calibration r2 true claim is not grounded in source")
    start = max(0, position - context_chars)
    end = min(len(source), position + len(claim) + context_chars)
    return source[start:end]


def _r2_blinded_review_row(
    review_id: str, row: Mapping[str, Any], *, source_evidence_excerpt: str
) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "true_claim": str(row["true_claim"]),
        "counterfactual_claim": str(row["counterfactual_claim"]),
        "original_entity": str(row["original_entity"]),
        "counterfactual_entity": str(row["counterfactual_entity"]),
        "source_evidence_excerpt": source_evidence_excerpt,
    }


def _review_template(review_id: str) -> dict[str, Any]:
    return {
        "review_id": review_id,
        **{field: None for field in REVIEW_FIELDS},
        "reason_codes": [],
        "evidence": "",
    }


def check_r2_capacity(
    config_path: str | Path, *, project_root: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_r2_config(Path(config_path).resolve())
    base_config, _, r1_private, _ = _load_base_and_r1(config, root)
    pilot_rows, _ = _pilot_rows(base_config, root)
    available = _available_rows(pilot_rows, _r1_exclusions(r1_private))
    grounded_evidence_rows = 0
    counts = {
        f"{dataset}/{entity_type}": len(
            {
                str(row.get("fact_signature") or row.get("pair_id") or "")
                for row in available
                if str(row.get("dataset") or "") == dataset
                and str(row.get("effective_type") or "") == entity_type
            }
        )
        for dataset in sorted(base_config["source_pools"])
        for entity_type in sorted(MAIN_ENTITY_TYPES)
    }
    required = int(config["calibration"]["real_rows_per_cell"])
    for dataset in sorted(base_config["source_pools"]):
        source_manifest = _validate_source_pool_for_extension(
            base_config,
            dataset,
            str(config["base_v22"]["protocol_identity_sha256"]),
            root,
        )
        for entity_type in sorted(MAIN_ENTITY_TYPES):
            selected = _score_strata_r2(
                [
                    row
                    for row in available
                    if str(row.get("dataset") or "") == dataset
                    and str(row.get("effective_type") or "") == entity_type
                ],
                required,
            )
            for row in selected:
                _source_evidence_excerpt(source_manifest, row, root)
                grounded_evidence_rows += 1
    return {
        "status": "passed" if all(value >= required for value in counts.values()) else "failed_capacity_shortfall",
        "required_real_rows_per_cell": required,
        "available_unique_facts_by_cell": counts,
        "minimum_available": min(counts.values()),
        "grounded_evidence_rows": grounded_evidence_rows,
        "r1_exclusion_applied": True,
        "attack_auc_accessed": False,
        "victim_responses_accessed": False,
        "external_calls": 0,
    }


def freeze_calibration_r2(
    config_path: str | Path,
    *,
    resume: bool,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_r2_config(config_file)
    _assert_runtime_committed(config, root)
    base_config, r1_plan, r1_private, r1_evaluation = _load_base_and_r1(config, root)
    output = _resolve(str(config["output_root"]), root)
    plan_path = output / "calibration_plan.json"
    if plan_path.exists():
        if not resume:
            raise RuntimeError("v22 calibration r2 is already frozen")
        plan = _load_r2_plan(config, root)
        return {
            "status": "frozen",
            "rows": plan["row_count"],
            "plan": str(plan_path),
            "resumed": True,
        }

    pilot_rows, checkpoints = _pilot_rows(base_config, root)
    exclusions = _r1_exclusions(r1_private)
    available = _available_rows(pilot_rows, exclusions)
    real_per_cell = int(config["calibration"]["real_rows_per_cell"])
    controls_per_cell = int(config["calibration"]["structural_controls_per_cell"])
    blinded_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    templates: list[dict[str, Any]] = []
    selected_pair_ids: list[str] = []
    for dataset in sorted(base_config["source_pools"]):
        source_manifest = _validate_source_pool_for_extension(
            base_config,
            dataset,
            str(config["base_v22"]["protocol_identity_sha256"]),
            root,
        )
        for entity_type in sorted(MAIN_ENTITY_TYPES):
            cell = [
                row
                for row in available
                if str(row.get("dataset") or "") == dataset
                and str(row.get("effective_type") or "") == entity_type
            ]
            selected = _score_strata_r2(cell, real_per_cell)
            for row in selected:
                review_id = _anonymous_review_id(
                    "real", dataset, entity_type, str(row["pair_id"])
                )
                blinded_rows.append(
                    _r2_blinded_review_row(
                        review_id,
                        row,
                        source_evidence_excerpt=_source_evidence_excerpt(
                            source_manifest, row, root
                        ),
                    )
                )
                templates.append(_review_template(review_id))
                private_rows.append(
                    {
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
                )
                selected_pair_ids.append(str(row["pair_id"]))
            controls = _structural_controls(
                dataset, entity_type, selected[:controls_per_cell]
            )
            for control_index, (control_row, reason) in enumerate(controls):
                review_id = _anonymous_review_id(
                    "control",
                    dataset,
                    entity_type,
                    reason,
                    str(control_row.get("pair_id") or ""),
                )
                blinded = _r2_blinded_review_row(
                    review_id,
                    control_row,
                    source_evidence_excerpt=_source_evidence_excerpt(
                        source_manifest, selected[control_index], root
                    ),
                )
                if reason == "source_span_or_grounding_mismatch":
                    blinded["source_evidence_excerpt"] = str(
                        control_row["source_evidence_excerpt"]
                    )
                blinded_rows.append(blinded)
                templates.append(_review_template(review_id))
                private_rows.append(
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

    expected_total = int(config["calibration"]["total_rows"])
    if not (
        len(blinded_rows) == len(private_rows) == len(templates) == expected_total
    ):
        raise RuntimeError("v22 calibration r2 total row drift")
    blinded_rows.sort(key=lambda row: str(row["review_id"]))
    private_rows.sort(key=lambda row: str(row["review_id"]))
    templates.sort(key=lambda row: str(row["review_id"]))
    output.mkdir(parents=True, exist_ok=True)
    blinded_path = output / "calibration_blinded.jsonl"
    private_path = output / "private" / "calibration_key.jsonl"
    template_path = output / "private" / "assistant_labels.template.jsonl"
    write_jsonl_atomic(blinded_rows, blinded_path)
    write_jsonl_atomic(private_rows, private_path)
    write_jsonl_atomic(templates, template_path)

    real_private = [row for row in private_rows if row["row_kind"] == "real_candidate"]
    overlap = {
        "pair_ids": len(exclusions["pair_ids"] & set(selected_pair_ids)),
        "source_keys": len(
            exclusions["source_keys"]
            & {str(row["source_key"]) for row in real_private}
        ),
        "fact_signatures": len(
            exclusions["fact_signatures"]
            & {str(row["fact_signature"]) for row in real_private}
        ),
    }
    if any(overlap.values()):
        raise RuntimeError(f"v22 calibration r2 overlaps r1: {overlap}")
    plan: dict[str, Any] = {
        "protocol": R2_PLAN_PROTOCOL,
        "status": "frozen_before_assistant_labels",
        "created_at": _utc_now(),
        "config_path": _relative(config_file, root),
        "config_sha256": sha256_file(config_file),
        "runtime_bundle": _runtime_bundle(config, root),
        "code_commit": _git_commit(root),
        "base_protocol_identity_sha256": config["base_v22"][
            "protocol_identity_sha256"
        ],
        "base_code_commit": read_json(
            _resolve(str(config["base_v22"]["protocol_manifest_path"]), root)
        )["code_commit"],
        "base_code_commit_is_ancestor": True,
        "r1_calibration_plan_identity_sha256": r1_plan[
            "calibration_plan_identity_sha256"
        ],
        "r1_evaluation_identity_sha256": r1_evaluation[
            "evaluation_identity_sha256"
        ],
        "r1_status": r1_evaluation["status"],
        "r1_failure_observed_before_r2_design": True,
        "r1_labels_reused": False,
        "review_mode": config["review"]["mode"],
        "human_review_required": False,
        "human_validation_claim_allowed": False,
        "row_count": len(blinded_rows),
        "real_row_count": len(real_private),
        "structural_control_count": len(private_rows) - len(real_private),
        "cell_count": int(config["calibration"]["cells"]),
        "r1_exclusion_counts": {
            key: len(value) for key, value in sorted(exclusions.items())
        },
        "r1_overlap": overlap,
        "selected_pair_ids_sha256": sha256_obj(sorted(selected_pair_ids)),
        "review_ids_sha256": sha256_obj(
            sorted(str(row["review_id"]) for row in blinded_rows)
        ),
        "pilot_checkpoint_identities": {
            dataset: checkpoint["checkpoint_identity_sha256"]
            for dataset, checkpoint in sorted(checkpoints.items())
        },
        "review_schema": {
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
                "path": _relative(template_path, root),
                "sha256": sha256_file(template_path),
            },
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
        "real_rows": len(real_private),
        "structural_controls": len(private_rows) - len(real_private),
        "plan": str(plan_path),
        "assistant_template": str(template_path),
        "resumed": False,
    }


def _load_r2_plan(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve(str(config["output_root"]), root) / "calibration_plan.json"
    if not path.is_file():
        raise RuntimeError("v22 calibration r2 is not frozen")
    plan = read_json(path)
    if plan.get("protocol") != R2_PLAN_PROTOCOL or plan.get(
        "calibration_plan_identity_sha256"
    ) != _identity(plan, "created_at", "calibration_plan_identity_sha256"):
        raise RuntimeError("v22 calibration r2 plan identity drift")
    if plan.get("config_sha256") != sha256_file(
        _resolve(str(plan["config_path"]), root)
    ):
        raise RuntimeError("v22 calibration r2 config drift")
    if plan.get("runtime_bundle") != _runtime_bundle(config, root):
        raise RuntimeError("v22 calibration r2 runtime bundle drift")
    if not _commit_is_ancestor(root, str(plan.get("code_commit") or "")):
        raise RuntimeError("v22 calibration r2 code commit is not an ancestor of HEAD")
    for artifact in plan["artifacts"].values():
        artifact_path = _resolve(str(artifact["path"]), root)
        if not artifact_path.is_file() or sha256_file(artifact_path) != artifact[
            "sha256"
        ]:
            raise RuntimeError("v22 calibration r2 artifact drift")
    return plan


def validate_r2_assistant_labels(
    config_path: str | Path,
    labels_path: str | Path,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_r2_config(Path(config_path).resolve())
    plan = _load_r2_plan(config, root)
    expected_ids = {
        str(row["review_id"])
        for row in read_jsonl(
            _resolve(str(plan["artifacts"]["blinded"]["path"]), root)
        )
    }
    labels_file = Path(labels_path).resolve()
    labels = _validate_label_rows(labels_file, expected_ids=expected_ids)
    counts = Counter(str(row["attack_usable"]) for row in labels.values())
    receipt: dict[str, Any] = {
        "protocol": R2_LABEL_RECEIPT_PROTOCOL,
        "status": "validated",
        "reviewer_role": "assistant",
        "review_mode": "assistant_only_no_human_validation",
        "human_review_performed": False,
        "calibration_plan_identity_sha256": plan[
            "calibration_plan_identity_sha256"
        ],
        "labels_path": _relative(labels_file, root),
        "labels_sha256": sha256_file(labels_file),
        "rows": len(labels),
        "attack_usable_counts": dict(counts),
    }
    receipt["receipt_identity_sha256"] = sha256_obj(receipt)
    receipt_path = (
        _resolve(str(config["output_root"]), root)
        / "private"
        / "assistant_labels_receipt.json"
    )
    if receipt_path.exists() and read_json(receipt_path) != receipt:
        raise RuntimeError("v22 calibration r2 assistant label receipt drift")
    if not receipt_path.exists():
        write_json(receipt, receipt_path)
    return {
        "status": "validated",
        "rows": len(labels),
        "counts": dict(counts),
        "receipt": str(receipt_path),
    }


def evaluate_calibration_r2(
    config_path: str | Path,
    labels_path: str | Path,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config_file = Path(config_path).resolve()
    config = load_r2_config(config_file)
    plan = _load_r2_plan(config, root)
    private_rows = list(
        read_jsonl(_resolve(str(plan["artifacts"]["private_key"]["path"]), root))
    )
    private_by_id = {str(row["review_id"]): row for row in private_rows}
    labels_file = Path(labels_path).resolve()
    labels = _validate_label_rows(labels_file, expected_ids=set(private_by_id))
    receipt_path = (
        _resolve(str(config["output_root"]), root)
        / "private"
        / "assistant_labels_receipt.json"
    )
    if not receipt_path.is_file():
        raise RuntimeError("v22 calibration r2 assistant labels are not validated")
    receipt = read_json(receipt_path)
    if (
        receipt.get("protocol") != R2_LABEL_RECEIPT_PROTOCOL
        or receipt.get("calibration_plan_identity_sha256")
        != plan.get("calibration_plan_identity_sha256")
        or receipt.get("labels_sha256") != sha256_file(labels_file)
        or receipt.get("receipt_identity_sha256")
        != sha256_obj(
            {
                key: value
                for key, value in receipt.items()
                if key != "receipt_identity_sha256"
            }
        )
    ):
        raise RuntimeError("v22 calibration r2 assistant label receipt drift")

    controls = [row for row in private_rows if row["row_kind"] == "structural_control"]
    real_rows = [row for row in private_rows if row["row_kind"] == "real_candidate"]
    control_rejection_rate = sum(
        labels[str(row["review_id"])]["attack_usable"] == "no" for row in controls
    ) / max(1, len(controls))
    uncertain_count = sum(
        labels[str(row["review_id"])]["attack_usable"] == "uncertain"
        for row in real_rows
    )
    uncertain_rate = uncertain_count / max(1, len(real_rows))
    label_by_pair = {
        str(row["pair_id"]): labels[str(row["review_id"])]["attack_usable"]
        for row in real_rows
    }
    base_config, _, _, _ = _load_base_and_r1(config, root)
    pilot_rows, _ = _pilot_rows(base_config, root)
    gate_config = dict(config["calibration"]["gates"])
    grid: list[dict[str, Any]] = []
    for raw_threshold in config["calibration"]["threshold_grid"]:
        threshold = float(raw_threshold)
        labelled = [
            row
            for row in real_rows
            if float(row["utility_score"]) >= threshold
            and label_by_pair[str(row["pair_id"])] in {"yes", "no"}
        ]
        positive = sum(
            label_by_pair[str(row["pair_id"])] == "yes" for row in labelled
        )
        assistant_judged_usability_rate = positive / max(1, len(labelled))
        retained = sum(
            bool(row.get("hard_gate_passed"))
            and float(row.get("utility_score", 0.0)) >= threshold
            and str(row.get("effective_type") or "") in MAIN_ENTITY_TYPES
            for row in pilot_rows
        )
        projection = _projection_by_threshold_r2(
            base_config,
            pilot_rows,
            threshold,
            str(plan["base_protocol_identity_sha256"]),
            root,
        )
        projection_passed = all(
            values["projected_eligible_sources"]
            >= float(gate_config["minimum_projected_eligible_sources_per_dataset"])
            for values in projection.values()
        )
        enough_labels = len(labelled) >= int(
            gate_config["minimum_labelled_real_candidates_per_threshold"]
        )
        grid.append(
            {
                "threshold": threshold,
                "labelled_real_candidates": len(labelled),
                "assistant_judged_usability_rate": assistant_judged_usability_rate,
                "retained_pilot_candidates": retained,
                "projection": projection,
                "minimum_label_count_passed": enough_labels,
                "usability_rate_gate_passed": enough_labels
                and assistant_judged_usability_rate
                >= float(
                    gate_config[
                        "threshold_minimum_assistant_judged_usability_rate"
                    ]
                ),
                "projection_gate_passed": projection_passed,
            }
        )
    admissible = [
        row
        for row in grid
        if row["usability_rate_gate_passed"] and row["projection_gate_passed"]
    ]
    selected = (
        sorted(
            admissible,
            key=lambda row: (
                -int(row["retained_pilot_candidates"]),
                float(row["threshold"]),
            ),
        )[0]
        if admissible
        else None
    )
    gates = {
        "structural_negative_rejection": control_rejection_rate
        >= float(gate_config["structural_negative_rejection_rate"]),
        "maximum_real_uncertain_rate": uncertain_rate
        <= float(gate_config["maximum_real_uncertain_rate"]),
        "threshold_available": selected is not None,
    }
    passed = all(gates.values())
    output = _resolve(str(config["output_root"]), root)
    report: dict[str, Any] = {
        "protocol": R2_EVALUATION_PROTOCOL,
        "status": "passed" if passed else "failed_new_protocol_identity_required",
        "created_at": _utc_now(),
        "calibration_plan_identity_sha256": plan[
            "calibration_plan_identity_sha256"
        ],
        "assistant_labels_sha256": sha256_file(labels_file),
        "review_mode": "assistant_only_no_human_validation",
        "calibration_supervision": "assistant_only_surrogate_labels",
        "human_review_performed": False,
        "human_validation_claim_allowed": False,
        "precision_against_human_gold_available": False,
        "structural_negative_rejection_rate": control_rejection_rate,
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
    report["evaluation_identity_sha256"] = _identity(
        report, "created_at", "evaluation_identity_sha256"
    )
    report_path = output / "calibration_evaluation.json"
    if report_path.exists():
        existing = read_json(report_path)
        report["created_at"] = existing.get("created_at")
        report["evaluation_identity_sha256"] = _identity(
            report, "created_at", "evaluation_identity_sha256"
        )
        if existing != report:
            raise RuntimeError(
                "v22 calibration r2 evaluation is immutable; create a new protocol identity"
            )
        report = existing
    else:
        write_json(report, report_path)

    if passed and selected is not None:
        threshold_manifest: dict[str, Any] = {
            "protocol": R2_THRESHOLD_PROTOCOL,
            "status": "passed_assistant_only_no_human_validation",
            "created_at": _utc_now(),
            "method_version": config["method_version"],
            "config_sha256": sha256_file(config_file),
            "base_protocol_identity_sha256": plan["base_protocol_identity_sha256"],
            "calibration_evaluation_sha256": sha256_file(report_path),
            "calibration_evaluation_identity_sha256": report[
                "evaluation_identity_sha256"
            ],
            "selected_threshold": selected["threshold"],
            "threshold_grid": list(config["calibration"]["threshold_grid"]),
            "selection_rule": config["calibration"]["threshold_selection"],
            "selected_projection": selected["projection"],
            "review_mode": "assistant_only_no_human_validation",
            "calibration_supervision": "assistant_only_surrogate_labels",
            "human_validation_claim_allowed": False,
            "precision_against_human_gold_available": False,
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
                raise RuntimeError("v22 calibration r2 threshold manifest drift")
        else:
            write_json(threshold_manifest, threshold_path)
    return {
        "status": report["status"],
        "selected_threshold": report["selected_threshold"],
        "gates": gates,
        "report": str(report_path),
    }


def r2_status(config_path: str | Path, *, project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = load_r2_config(Path(config_path).resolve())
    output = _resolve(str(config["output_root"]), root)
    plan_path = output / "calibration_plan.json"
    receipt_path = output / "private" / "assistant_labels_receipt.json"
    evaluation_path = output / "calibration_evaluation.json"
    threshold_path = output / "threshold_manifest.json"
    status = "not_frozen"
    if plan_path.is_file():
        status = "frozen_waiting_for_assistant_labels"
    if receipt_path.is_file():
        status = "assistant_labels_validated"
    if evaluation_path.is_file():
        status = str(read_json(evaluation_path).get("status") or "evaluation_invalid")
    return {
        "protocol": R2_PROTOCOL,
        "review_mode": config["review"]["mode"],
        "human_review_required": False,
        "status": status,
        "plan_frozen": plan_path.is_file(),
        "assistant_labels_validated": receipt_path.is_file(),
        "evaluation_present": evaluation_path.is_file(),
        "threshold_frozen": threshold_path.is_file(),
        "external_calls": 0,
    }
