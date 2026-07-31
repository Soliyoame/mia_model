"""Prepare all zero-API release controls required before the v20 Pilot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.v20_release_controls import (  # noqa: E402
    DATASETS,
    build_execution_schedule,
    build_ground_truth_source_store,
    build_reserve_role_manifest,
    near_duplicate_audit,
)
from src.utils.hash import sha256_file  # noqa: E402
from src.utils.io import ensure_dir, load_yaml, read_jsonl, resolve_path, write_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze PCV-MIA v20 release controls")
    parser.add_argument("--config", default="configs/rag_config.yaml")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_yaml(args.config)
    paths = config["paths"]
    controls_root = ensure_dir(
        resolve_path(paths.get("release_controls_dir", "artifacts/v20/release_controls"))
    )
    reserve_root = ensure_dir(
        resolve_path(
            paths.get(
                "reserve_roles_dir",
                "artifacts/v20/release_controls/reserve_roles",
            )
        )
    )
    store_root = ensure_dir(
        resolve_path(
            paths.get(
                "ground_truth_source_store_dir",
                "artifacts/v20/release_controls/ground_truth_source_store",
            )
        )
    )
    summaries = {}
    for dataset in DATASETS:
        split_dir = resolve_path(config["dataset_paths"][dataset]["splits_dir"])
        role_path = reserve_root / f"{dataset}_reserve_roles.json"
        store_path = store_root / f"{dataset}_sources.jsonl"
        audit_path = controls_root / f"{dataset}_near_duplicate_audit.json"
        if not args.force and role_path.exists() and store_path.exists() and audit_path.exists():
            summaries[dataset] = {
                "status": "existing",
                "reserve_roles_hash": sha256_file(role_path),
                "source_store_hash": sha256_file(store_path),
                "near_duplicate_audit_hash": sha256_file(audit_path),
            }
            continue
        role_manifest = build_reserve_role_manifest(
            dataset=dataset,
            reserve_path=split_dir / "reserve.jsonl",
            pilot_budget_path=(
                resolve_path(paths["query_controls_dir"])
                / dataset
                / "llama-3.1-70b-instruct-pilot"
                / "budget.json"
            ),
            output_path=role_path,
        )
        store_manifest = build_ground_truth_source_store(
            dataset=dataset,
            split_dir=split_dir,
            output_path=store_path,
        )
        audit = near_duplicate_audit(read_jsonl(store_path))
        audit.update(
            {
                "protocol_version": "pcv-mia-v20",
                "dataset": dataset,
                "source_store_hash": sha256_file(store_path),
                "policy": (
                    "cross-group clusters require deterministic cluster-level "
                    "regrouping before any API call"
                ),
            }
        )
        write_json(audit, audit_path)
        if not audit["passed"]:
            raise RuntimeError(
                f"{dataset}: {audit['cross_group_pair_count']} cross-group "
                "near-duplicate pairs require split regeneration; API use is blocked"
            )
        summaries[dataset] = {
            "status": "prepared",
            "reserve_roles_hash": sha256_file(role_path),
            "source_store_hash": store_manifest["store_hash"],
            "near_duplicate_audit_hash": sha256_file(audit_path),
            "pilot_reserve_count": role_manifest["pilot_diagnostic_count"],
            "conformal_reserve_count": role_manifest["conformal_calibration_count"],
        }
    schedule_path = resolve_path(paths["execution_schedule_path"])
    schedule_manifest = build_execution_schedule(
        {
            dataset: (
                resolve_path(paths["queries_dir"])
                / f"{dataset}_paired_queries.jsonl"
            )
            for dataset in DATASETS
        },
        output_path=schedule_path,
        seed=42,
    )
    release_manifest = {
        "protocol_version": "pcv-mia-v20",
        "method_version": "pcv-rag-only-source-v20",
        "dataset_status": "pre_response_frozen_canonical",
        "metrics_version": "source-conformal-bootstrap-v2",
        "reserve_role": "retriever_dev_and_conformal",
        "execution": "source_block_interleaved",
        "datasets": summaries,
        "schedule_hash": schedule_manifest["schedule_hash"],
        "schedule_request_count": schedule_manifest["request_count"],
        "api_calls_made": 0,
    }
    output = controls_root / "release_controls_manifest.json"
    write_json(release_manifest, output)
    print(f"[saved] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
