"""Aggregate frozen claim-pair and stance audit reports into one release gate."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.hash import sha256_file, sha256_obj  # noqa: E402
from src.utils.io import load_yaml, read_json, resolve_path, write_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check PCV-MIA v19 human-audit quality gates")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "quality_gates.yaml"))
    parser.add_argument("--diagnostics-root", default="outputs/diagnostics")
    parser.add_argument("--output", default="outputs/diagnostics/quality_gate_report.json")
    return parser.parse_args()


def evaluate_quality_reports(
    config: dict[str, Any],
    claim_reports: list[dict[str, Any]],
    stance_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    claim_cfg = config["claim_pair_audit"]
    stance_cfg = config["stance_parser_audit"]
    expected_claim = {str(dataset) for dataset in claim_cfg["datasets"]}
    expected_stance = {
        (str(dataset), str(model))
        for dataset in stance_cfg["datasets"]
        for model in stance_cfg["generators"]
    }
    claim_keys = [str(row.get("dataset")) for row in claim_reports]
    stance_keys = [(str(row.get("dataset")), str(row.get("model"))) for row in stance_reports]
    claim_counts = Counter(claim_keys)
    stance_counts = Counter(stance_keys)
    missing_claim = sorted(expected_claim - set(claim_keys))
    missing_stance = sorted(f"{dataset}::{model}" for dataset, model in expected_stance - set(stance_keys))
    duplicate_claim = sorted(key for key, count in claim_counts.items() if count > 1)
    duplicate_stance = sorted(f"{key[0]}::{key[1]}" for key, count in stance_counts.items() if count > 1)
    unexpected_claim = sorted(set(claim_keys) - expected_claim)
    unexpected_stance = sorted(
        f"{dataset}::{model}" for dataset, model in set(stance_keys) - expected_stance
    )
    minimum_claim_rows = int(claim_cfg.get("pairs_per_dataset", 0))
    minimum_double_pass_rate = claim_cfg.get("minimum_double_pass_rate")
    minimum_kappa = claim_cfg.get("minimum_cohen_kappa")
    minimum_stance_rows = int(stance_cfg.get("responses_per_dataset_generator", 0))
    minimum_macro_f1 = stance_cfg.get("minimum_macro_f1")

    def claim_passes(row: dict[str, Any]) -> bool:
        if not bool(row.get("quality_gate_passed")):
            return False
        if minimum_claim_rows and int(row.get("double_labeled_rows", 0)) < minimum_claim_rows:
            return False
        if minimum_double_pass_rate is not None:
            value = row.get("double_pass_rate")
            if value is None or float(value) < float(minimum_double_pass_rate):
                return False
        if minimum_kappa is not None:
            value = row.get("cohen_kappa")
            if value is None or float(value) < float(minimum_kappa):
                return False
        return True

    def stance_passes(row: dict[str, Any]) -> bool:
        if not bool(row.get("quality_gate_passed")):
            return False
        if minimum_stance_rows and int(row.get("labeled_rows", 0)) < minimum_stance_rows:
            return False
        if minimum_macro_f1 is not None:
            value = row.get("macro_f1")
            if value is None or float(value) < float(minimum_macro_f1):
                return False
        return True

    failed_claim = sorted(
        str(row.get("dataset")) for row in claim_reports if not claim_passes(row)
    )
    failed_stance = sorted(
        f"{row.get('dataset')}::{row.get('model')}"
        for row in stance_reports
        if not stance_passes(row)
    )
    observed_stance_responses = sum(
        int(row.get("labeled_rows", 0))
        for row in stance_reports
        if (str(row.get("dataset")), str(row.get("model"))) in expected_stance
    )
    expected_stance_responses = int(stance_cfg["expected_total_responses"])
    insufficient_total_stance_responses = observed_stance_responses < expected_stance_responses
    passed = not any(
        (
            missing_claim,
            missing_stance,
            duplicate_claim,
            duplicate_stance,
            unexpected_claim,
            unexpected_stance,
            failed_claim,
            failed_stance,
            insufficient_total_stance_responses,
        )
    )
    return {
        "status": "passed" if passed else "failed",
        "quality_gate_passed": passed,
        "expected_claim_pair_reports": len(expected_claim),
        "observed_claim_pair_reports": len(claim_reports),
        "expected_stance_reports": len(expected_stance),
        "observed_stance_reports": len(stance_reports),
        "expected_stance_responses": expected_stance_responses,
        "observed_stance_responses": observed_stance_responses,
        "insufficient_total_stance_responses": insufficient_total_stance_responses,
        "missing_claim_pair_reports": missing_claim,
        "missing_stance_reports": missing_stance,
        "duplicate_claim_pair_reports": duplicate_claim,
        "duplicate_stance_reports": duplicate_stance,
        "unexpected_claim_pair_reports": unexpected_claim,
        "unexpected_stance_reports": unexpected_stance,
        "failed_claim_pair_reports": failed_claim,
        "failed_stance_reports": failed_stance,
    }


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    config = load_yaml(config_path)
    diagnostics_root = resolve_path(args.diagnostics_root)
    claim_paths = sorted(diagnostics_root.rglob("*_claim_pair_audit_report.json"))
    stance_paths = sorted(diagnostics_root.rglob("*_stance_audit_report.json"))
    report = evaluate_quality_reports(
        config,
        [read_json(path) for path in claim_paths],
        [read_json(path) for path in stance_paths],
    )
    report.update({
        "protocol_version": config.get("protocol_version"),
        "config_path": str(config_path.resolve()),
        "config_hash": sha256_file(config_path),
        "claim_report_artifacts": [{"path": str(path.resolve()), "sha256": sha256_file(path)} for path in claim_paths],
        "stance_report_artifacts": [{"path": str(path.resolve()), "sha256": sha256_file(path)} for path in stance_paths],
    })
    report["audit_binding_hash"] = sha256_obj({
        "claim": report["claim_report_artifacts"],
        "stance": report["stance_report_artifacts"],
    })
    output = resolve_path(args.output)
    write_json(report, output)
    print(f"[{report['status']}] {output}")
    return 0 if report["quality_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
