"""Calibrate v6.3 semantic thresholds on frozen historical audit labels."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.attack.semantic_entity_resolver import (  # noqa: E402
    PRECISION_CASCADE_MODE,
    SEMANTIC_RESOLVER_PROTOCOL,
    SEMANTIC_SCHEMA_SHA256,
    SEMANTIC_TARGET_TYPES,
    SemanticEntityResolver,
    SemanticPrediction,
    load_semantic_entity_resolver,
    semantic_thresholds_sha256,
)
from src.paired_claims.validator import find_entity_span  # noqa: E402
from src.utils.io import ensure_dir, read_jsonl, write_json, write_jsonl  # noqa: E402


DATASETS = ("edgar", "enron", "pubmed")
AUDIT_DIR = (
    PROJECT_ROOT
    / "artifacts"
    / "v19"
    / "audits"
    / "claim_pair_ai_adjudication"
)
SUPPLEMENT_PATH = (
    PROJECT_ROOT
    / "configs"
    / "semantic_v6_3_dev_supplement.yaml"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calibrate the local v6.3 semantic resolver."
    )
    parser.add_argument(
        "--model-lock",
        default=str(
            PROJECT_ROOT
            / "configs"
            / "semantic_entity_models_v6_3.lock.yaml"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(
            PROJECT_ROOT
            / "artifacts"
            / "v6_3"
            / "semantic_calibration_precision_cascade_per_type"
        ),
    )
    parser.add_argument(
        "--prediction-cache-dir",
        default=None,
        help=(
            "Read validated raw prediction caches from this directory without "
            "loading any model or modifying the cache."
        ),
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=DATASETS,
        default=list(DATASETS),
    )
    parser.add_argument("--max-rows-per-dataset", type=int, default=None)
    parser.add_argument("--supplement-only", action="store_true")
    parser.add_argument("--force-inference", action="store_true")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--spacy-device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--biomedical-device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--use-fp16", action="store_true")
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _audit_path(dataset: str) -> Path:
    return AUDIT_DIR / f"{dataset}_claim_pair_ai_adjudication.jsonl"


def _load_semantic_dev_rows(
    dataset: str,
    max_rows: int | None,
    *,
    supplement_only: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in (() if supplement_only else read_jsonl(_audit_path(dataset))):
        entity_type = str(row.get("entity_type") or "").upper()
        label = str(row.get("ai_pair_valid") or "").casefold()
        failure_code = str(row.get("ai_failure_reason_code") or "")
        if entity_type not in SEMANTIC_TARGET_TYPES:
            continue
        # Only entity-type/boundary negatives train this resolver.  Claim
        # truncation/artifact failures belong to the deterministic validator.
        if label == "pass":
            semantic_label = "pass"
        elif label == "fail" and failure_code == "entity_type_or_boundary_error":
            semantic_label = "fail"
        else:
            continue
        claim = str(row.get("true_claim") or "")
        entity = str(row.get("original_entity") or "")
        span = find_entity_span(claim, entity)
        if span is None:
            # A missing literal boundary is itself a known bad boundary case.
            literal = claim.casefold().find(entity.casefold())
            if literal < 0:
                continue
            span = (literal, literal + len(entity))
        rows.append(
            {
                "audit_id": row.get("audit_id"),
                "dataset": dataset,
                "entity_type": entity_type,
                "entity": entity,
                "text": claim,
                "start": span[0],
                "end": span[1],
                "semantic_label": semantic_label,
                "source_protocol": row.get("adjudication_protocol_version"),
                "source_confidence": row.get("ai_review_confidence"),
            }
        )
        if max_rows is not None and len(rows) >= max_rows:
            break
    if max_rows is None:
        supplement = yaml.safe_load(
            SUPPLEMENT_PATH.read_text(encoding="utf-8")
        )
        for case in supplement.get("cases", []):
            if str(case.get("dataset") or "").casefold() != dataset:
                continue
            text = str(case["text"])
            entity = str(case["entity"])
            span = find_entity_span(text, entity)
            if span is None:
                raise RuntimeError(
                    f"Supplement entity boundary missing: {case['audit_id']}"
                )
            rows.append(
                {
                    "audit_id": str(case["audit_id"]),
                    "dataset": dataset,
                    "entity_type": str(case["entity_type"]).upper(),
                    "entity": entity,
                    "text": text,
                    "start": span[0],
                    "end": span[1],
                    "semantic_label": str(case["semantic_label"]).casefold(),
                    "source_protocol": str(supplement["protocol"]),
                    "source_confidence": "ai_assisted_development_review",
                    "review_rationale": str(case.get("rationale") or ""),
                }
            )
    return rows


def _prediction_to_dict(prediction: SemanticPrediction) -> dict[str, Any]:
    return asdict(prediction)


def _prediction_from_dict(payload: dict[str, Any]) -> SemanticPrediction:
    return SemanticPrediction(
        model_id=str(payload["model_id"]),
        role=str(payload["role"]),
        label=str(payload["label"]),
        text=str(payload["text"]),
        start=int(payload["start"]),
        end=int(payload["end"]),
        score=float(payload["score"]),
    )


def _inference_config(
    model_lock: Path,
    *,
    device: str,
    spacy_device: str,
    biomedical_device: str,
    batch_size: int,
    use_fp16: bool,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "protocol": SEMANTIC_RESOLVER_PROTOCOL,
        "execution_mode": PRECISION_CASCADE_MODE,
        "primary_model_role": "gliner2_large",
        "biomedical_candidate_only": True,
        "calibration_mode": True,
        "schema_sha256": SEMANTIC_SCHEMA_SHA256,
        "local_files_only": True,
        "model_lock_path": str(model_lock),
        "device": device,
        "spacy_device": spacy_device,
        "biomedical_device": biomedical_device,
        "batch_size": batch_size,
        "use_fp16": use_fp16,
        # Low collection threshold; formal thresholds are swept offline.
        "min_target_confidence": 0.0,
        "min_confidence_margin": -1.0,
        "min_consensus_votes": 1,
        "min_boundary_votes": 1,
        "biomedical_veto_threshold": 0.0,
    }


def _collect_predictions(
    rows: list[dict[str, Any]],
    dataset: str,
    model_lock: Path,
    *,
    runtime: dict[str, Any],
) -> list[dict[str, Any]]:
    resolver, metadata = load_semantic_entity_resolver(
        _inference_config(model_lock, **runtime),
        dataset=dataset,
        workspace_root=PROJECT_ROOT,
    )
    assert resolver is not None
    collected: list[dict[str, Any]] = []
    total = len(rows)
    batch_size = int(runtime["batch_size"])
    for offset in range(0, total, batch_size):
        batch = rows[offset : offset + batch_size]
        predictions = resolver.predict_batch(
            [str(row["text"]) for row in batch],
            dataset=dataset,
            batch_size=batch_size,
            candidate_spans=[
                {
                    "type": row["entity_type"],
                    "start": row["start"],
                    "end": row["end"],
                }
                for row in batch
            ],
        )
        for row, (voter_predictions, biomedical_predictions) in zip(
            batch,
            predictions,
            strict=True,
        ):
            collected.append(
                {
                    **row,
                    "voter_predictions": {
                        model_id: [
                            _prediction_to_dict(prediction)
                            for prediction in model_predictions
                        ]
                        for model_id, model_predictions in voter_predictions.items()
                    },
                    "biomedical_predictions": [
                        _prediction_to_dict(prediction)
                        for prediction in biomedical_predictions
                    ],
                    "resolver_models": [
                        {
                            "model_id": model["model_id"],
                            "revision": model["revision"],
                            "role": model["role"],
                            "runtime_device": model["runtime_device"],
                            "runtime_precision": model["runtime_precision"],
                        }
                        for model in metadata.models
                    ],
                }
            )
        completed = min(offset + len(batch), total)
        print(
            f"[{dataset}] semantic inference {completed}/{total}",
            flush=True,
        )
    return collected


def _load_or_collect_dataset(
    dataset: str,
    model_lock: Path,
    output_dir: Path,
    *,
    max_rows: int | None,
    supplement_only: bool,
    force: bool,
    runtime: dict[str, Any],
    prediction_cache_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_path = _audit_path(dataset)
    cache_root = prediction_cache_dir or output_dir
    cache_path = cache_root / f"{dataset}_raw_predictions.jsonl"
    cache_manifest_path = (
        cache_root / f"{dataset}_raw_predictions.manifest.json"
    )
    source_hash = _sha256_file(source_path)
    lock_hash = _sha256_file(model_lock)
    expected = {
        "dataset": dataset,
        "source_path": str(source_path),
        "source_sha256": source_hash,
        "model_lock_path": str(model_lock),
        "model_lock_sha256": lock_hash,
        "schema_sha256": SEMANTIC_SCHEMA_SHA256,
        "supplement_path": str(SUPPLEMENT_PATH),
        "supplement_sha256": _sha256_file(SUPPLEMENT_PATH),
        "max_rows_per_dataset": max_rows,
        "supplement_only": supplement_only,
        "runtime": runtime,
        "protocol": SEMANTIC_RESOLVER_PROTOCOL,
        "execution_mode": PRECISION_CASCADE_MODE,
        "primary_model_role": "gliner2_large",
    }
    if cache_path.is_file() and cache_manifest_path.is_file() and not force:
        manifest = json.loads(cache_manifest_path.read_text(encoding="utf-8"))
        if all(manifest.get(key) == value for key, value in expected.items()):
            return list(read_jsonl(cache_path)), manifest
        if prediction_cache_dir is not None:
            mismatches = {
                key: {
                    "expected": value,
                    "actual": manifest.get(key),
                }
                for key, value in expected.items()
                if manifest.get(key) != value
            }
            raise RuntimeError(
                f"{dataset} prediction cache identity mismatch: {mismatches}"
            )
    if prediction_cache_dir is not None:
        raise FileNotFoundError(
            f"Validated {dataset} prediction cache is missing under "
            f"{prediction_cache_dir}"
        )

    rows = _load_semantic_dev_rows(
        dataset,
        max_rows,
        supplement_only=supplement_only,
    )
    predictions = _collect_predictions(
        rows,
        dataset,
        model_lock,
        runtime=runtime,
    )
    write_jsonl(predictions, cache_path)
    manifest = {
        **expected,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(predictions),
        "labels": dict(Counter(str(row["semantic_label"]) for row in rows)),
        "entity_types": dict(Counter(str(row["entity_type"]) for row in rows)),
        "api_calls_performed": 0,
        "label_scope": (
            "AI-assisted historical development labels; not a release audit "
            "and not a two-human blind annotation."
        ),
        "output_path": str(cache_path),
        "output_sha256": _sha256_file(cache_path),
    }
    write_json(manifest, cache_manifest_path)
    return predictions, manifest


def _evaluate_thresholds(
    rows: list[dict[str, Any]],
    *,
    target_threshold: float,
    margin_threshold: float,
    consensus_votes: int,
    biomedical_threshold: float,
    thresholds_by_entity_type: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    # Backends are never called here; _resolve_one consumes cached predictions.
    placeholder = type(
        "PlaceholderBackend",
        (),
        {"model_id": "placeholder", "role": "gliner2_large"},
    )()
    evaluator = SemanticEntityResolver(
        [placeholder],
        min_target_confidence=target_threshold,
        min_confidence_margin=margin_threshold,
        thresholds_by_entity_type=thresholds_by_entity_type,
        min_consensus_votes=consensus_votes,
        min_boundary_votes=1,
        biomedical_veto_threshold=biomedical_threshold,
        execution_mode=PRECISION_CASCADE_MODE,
        protocol=SEMANTIC_RESOLVER_PROTOCOL,
    )
    outcomes: list[dict[str, Any]] = []
    for row in rows:
        voter_predictions = {
            model_id: [
                _prediction_from_dict(item)
                for item in predictions
            ]
            for model_id, predictions in row["voter_predictions"].items()
        }
        biomedical_predictions = [
            _prediction_from_dict(item)
            for item in row.get("biomedical_predictions", [])
        ]
        resolution = evaluator._resolve_one(
            str(row["text"]),
            {
                "text": row["entity"],
                "type": row["entity_type"],
                "start": row["start"],
                "end": row["end"],
            },
            voter_predictions,
            biomedical_predictions,
        )
        boundary_repaired = bool(
            row["semantic_label"] == "fail"
            and resolution.accepted
            and (
                resolution.start != int(row["start"])
                or resolution.end != int(row["end"])
            )
        )
        outcomes.append(
            {
                "audit_id": row["audit_id"],
                "dataset": row["dataset"],
                "entity_type": row["entity_type"],
                "label": row["semantic_label"],
                "accepted": resolution.accepted,
                "resolved_text": resolution.text,
                "resolved_start": resolution.start,
                "resolved_end": resolution.end,
                "boundary_repaired": boundary_repaired,
                "failure_reasons": list(resolution.failure_reasons),
            }
        )

    def metrics_for(items: list[dict[str, Any]]) -> dict[str, Any]:
        positives = sum(
            item["label"] == "pass" or item["boundary_repaired"]
            for item in items
        )
        negatives = sum(
            item["label"] == "fail" and not item["boundary_repaired"]
            for item in items
        )
        true_accepts = sum(
            item["accepted"]
            and (item["label"] == "pass" or item["boundary_repaired"])
            for item in items
        )
        false_accepts = sum(
            item["accepted"]
            and item["label"] == "fail"
            and not item["boundary_repaired"]
            for item in items
        )
        accepted = true_accepts + false_accepts
        return {
            "rows": len(items),
            "positives": positives,
            "negatives": negatives,
            "true_accepts": true_accepts,
            "false_accepts": false_accepts,
            "repaired_bad_boundaries": sum(
                item["boundary_repaired"] for item in items
            ),
            "precision": (
                true_accepts / accepted
                if accepted
                else None
            ),
            "recall": (
                true_accepts / positives
                if positives
                else None
            ),
        }

    overall = metrics_for(outcomes)
    by_type = {
        entity_type: metrics_for(
            [
                outcome
                for outcome in outcomes
                if outcome["entity_type"] == entity_type
            ]
        )
        for entity_type in sorted(SEMANTIC_TARGET_TYPES)
    }
    gate_failures: list[str] = []
    if overall["precision"] is None or overall["precision"] < 0.97:
        gate_failures.append("overall_exact_precision_below_0_97")
    if overall["false_accepts"] != 0:
        gate_failures.append("known_bad_false_accepts_nonzero")
    for entity_type, metrics in by_type.items():
        if metrics["positives"] <= 0:
            gate_failures.append(f"{entity_type}_missing_positive_dev_examples")
        elif metrics["precision"] is None:
            gate_failures.append(f"{entity_type}_accepted_none")
        elif metrics["precision"] < 0.95:
            gate_failures.append(f"{entity_type}_precision_below_0_95")
    thresholds = {
        "min_target_confidence": target_threshold,
        "min_confidence_margin": margin_threshold,
        "min_consensus_votes": consensus_votes,
        "min_boundary_votes": 1,
        "biomedical_veto_threshold": biomedical_threshold,
        "overlap_threshold": evaluator.overlap_threshold,
    }
    if evaluator.thresholds_by_entity_type:
        thresholds["thresholds_by_entity_type"] = (
            evaluator.thresholds_by_entity_type
        )
    return {
        "thresholds": thresholds,
        "thresholds_sha256": semantic_thresholds_sha256(**thresholds),
        "gate_passed": not gate_failures,
        "gate_failures": gate_failures,
        "overall": overall,
        "by_entity_type": by_type,
        "false_accept_audit_ids": [
            outcome["audit_id"]
            for outcome in outcomes
            if (
                outcome["accepted"]
                and outcome["label"] == "fail"
                and not outcome["boundary_repaired"]
            )
        ],
        "repaired_boundary_cases": [
            {
                "audit_id": outcome["audit_id"],
                "resolved_text": outcome["resolved_text"],
                "resolved_start": outcome["resolved_start"],
                "resolved_end": outcome["resolved_end"],
            }
            for outcome in outcomes
            if outcome["boundary_repaired"]
        ],
    }


def _select_thresholds(
    rows: list[dict[str, Any]],
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    evaluated: list[dict[str, Any]] = []
    biomedical_values = (0.70, 0.75, 0.80, 0.85, 0.90, 0.95)
    grid = itertools.product(
        (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95),
        (0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40),
        (1,),
        biomedical_values,
    )
    for target, margin, votes, biomedical in grid:
        evaluated.append(
            _evaluate_thresholds(
                rows,
                target_threshold=target,
                margin_threshold=margin,
                consensus_votes=votes,
                biomedical_threshold=biomedical,
            )
        )
    policy_candidates: list[dict[str, Any]] = []
    for biomedical_threshold in biomedical_values:
        selected_by_type: dict[str, dict[str, float]] = {}
        component_metrics: dict[str, Any] = {}
        for entity_type in sorted(SEMANTIC_TARGET_TYPES):
            candidates = [
                result
                for result in evaluated
                if (
                    result["thresholds"]["biomedical_veto_threshold"]
                    == biomedical_threshold
                    and result["by_entity_type"][entity_type]["precision"]
                    is not None
                    and result["by_entity_type"][entity_type]["precision"]
                    >= 0.95
                    and result["by_entity_type"][entity_type]["false_accepts"]
                    == 0
                )
            ]
            candidates.sort(
                key=lambda result: (
                    -int(
                        result["by_entity_type"][entity_type]["true_accepts"]
                    ),
                    -float(
                        result["by_entity_type"][entity_type]["recall"] or 0.0
                    ),
                    -float(
                        result["thresholds"]["min_target_confidence"]
                    ),
                    -float(
                        result["thresholds"]["min_confidence_margin"]
                    ),
                )
            )
            if not candidates:
                selected_by_type = {}
                break
            component = candidates[0]
            selected_by_type[entity_type] = {
                "min_target_confidence": float(
                    component["thresholds"]["min_target_confidence"]
                ),
                "min_confidence_margin": float(
                    component["thresholds"]["min_confidence_margin"]
                ),
            }
            component_metrics[entity_type] = {
                "thresholds": selected_by_type[entity_type],
                "metrics": component["by_entity_type"][entity_type],
            }
        if not selected_by_type:
            continue
        combined = _evaluate_thresholds(
            rows,
            target_threshold=0.95,
            margin_threshold=0.40,
            consensus_votes=1,
            biomedical_threshold=biomedical_threshold,
            thresholds_by_entity_type=selected_by_type,
        )
        combined["selection_policy"] = "per_entity_type"
        combined["component_metrics"] = component_metrics
        policy_candidates.append(combined)

    passing = [
        result for result in policy_candidates if result["gate_passed"]
    ]
    passing.sort(
        key=lambda result: (
            -int(result["overall"]["true_accepts"]),
            -float(result["overall"]["recall"] or 0.0),
            float(result["thresholds"]["biomedical_veto_threshold"]),
            str(result["thresholds_sha256"]),
        )
    )
    return (
        passing[0] if passing else None,
        evaluated,
        policy_candidates,
    )


def main() -> int:
    args = parse_args()
    model_lock = Path(args.model_lock).resolve()
    output_dir = ensure_dir(args.output_dir)
    prediction_cache_dir = (
        Path(args.prediction_cache_dir).resolve()
        if args.prediction_cache_dir
        else None
    )
    if args.batch_size < 1:
        raise ValueError("--batch-size must be positive")
    if prediction_cache_dir is not None and args.force_inference:
        raise ValueError(
            "--force-inference cannot be combined with --prediction-cache-dir"
        )
    runtime = {
        "device": args.device,
        "spacy_device": args.spacy_device,
        "biomedical_device": args.biomedical_device,
        "batch_size": args.batch_size,
        "use_fp16": args.use_fp16,
    }
    all_rows: list[dict[str, Any]] = []
    source_manifests: dict[str, Any] = {}
    for dataset in args.datasets:
        rows, manifest = _load_or_collect_dataset(
            dataset,
            model_lock,
            output_dir,
            max_rows=args.max_rows_per_dataset,
            supplement_only=args.supplement_only,
            force=args.force_inference,
            runtime=runtime,
            prediction_cache_dir=prediction_cache_dir,
        )
        all_rows.extend(rows)
        source_manifests[dataset] = manifest

    selected, evaluated, policy_candidates = _select_thresholds(all_rows)
    summary = {
        "status": "passed" if selected is not None else "stopped_threshold_gate_failed",
        "protocol": SEMANTIC_RESOLVER_PROTOCOL,
        "schema_sha256": SEMANTIC_SCHEMA_SHA256,
        "runtime": runtime,
        "selection_policy": "per_entity_type",
        "prediction_cache_dir": (
            str(prediction_cache_dir)
            if prediction_cache_dir is not None
            else None
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "api_calls_performed": 0,
        "development_label_disclosure": (
            "Threshold selection uses frozen AI-assisted historical adjudication "
            "labels only. It is not the v6.3 release audit."
        ),
        "rows": len(all_rows),
        "source_manifests": source_manifests,
        "scalar_grid_size": len(evaluated),
        "policy_candidate_count": len(policy_candidates),
        "scalar_passing_threshold_count": sum(
            result["gate_passed"] for result in evaluated
        ),
        "passing_threshold_count": sum(
            result["gate_passed"] for result in policy_candidates
        ),
        "selected": selected,
        "selected_thresholds_sha256": (
            selected.get("thresholds_sha256") if selected is not None else None
        ),
    }
    write_json(summary, output_dir / "calibration_summary.json")
    write_json(
        {
            "selection_policy": "per_entity_type",
            "evaluated": evaluated,
            "policy_candidates": policy_candidates,
        },
        output_dir / "threshold_grid.json",
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "rows": summary["rows"],
                "passing_threshold_count": summary["passing_threshold_count"],
                "selected": selected,
            },
            ensure_ascii=True,
            indent=2,
        ),
        flush=True,
    )
    return 0 if selected is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
