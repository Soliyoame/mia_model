"""Run the isolated PCV-MIA v22 attackability-first workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.attackability_v22 import (  # noqa: E402
    evaluate_calibration,
    evaluate_fresh_audit,
    evaluate_shadow_gate,
    finalize_release,
    freeze_calibration,
    freeze_fresh_audit,
    freeze_protocol,
    freeze_splits,
    prepare_source_pool,
    prepare_user_review,
    run_scan,
    v22_status,
    validate_assistant_labels,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "attackability_first_v22.yaml"
DEFAULT_ASSISTANT_LABELS = (
    PROJECT_ROOT
    / "artifacts"
    / "v22"
    / "calibration"
    / "private"
    / "assistant_labels.jsonl"
)
DEFAULT_USER_LABELS = (
    PROJECT_ROOT / "artifacts" / "v22" / "calibration" / "user_labels.jsonl"
)
DEFAULT_FRESH_AUDIT_LABELS = (
    PROJECT_ROOT / "artifacts" / "v22" / "fresh_audit" / "fresh_audit_labels.jsonl"
)


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))


def _add_dataset(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", required=True, choices=("edgar", "enron", "pubmed"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the zero-API v22 attackability-first entity workflow"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    freeze = commands.add_parser("freeze-protocol")
    _add_config(freeze)
    freeze.add_argument("--resume", action="store_true")

    pool = commands.add_parser("prepare-source-pool")
    _add_config(pool)
    _add_dataset(pool)
    pool.add_argument("--resume", action="store_true", required=True)
    pool.add_argument("--max-new-rows", type=int, default=100000)

    for name in ("run-pilot", "run-formal-scan"):
        scan = commands.add_parser(name)
        _add_config(scan)
        _add_dataset(scan)
        scan.add_argument("--resume", action="store_true", required=True)
        scan.add_argument("--max-new-waves", type=int, default=1)

    calibration = commands.add_parser("freeze-calibration")
    _add_config(calibration)
    calibration.add_argument("--resume", action="store_true")

    assistant = commands.add_parser("validate-assistant-labels")
    _add_config(assistant)
    assistant.add_argument("--labels", default=str(DEFAULT_ASSISTANT_LABELS))

    user = commands.add_parser("prepare-user-review")
    _add_config(user)
    user.add_argument("--assistant-labels", default=str(DEFAULT_ASSISTANT_LABELS))
    user.add_argument("--resume", action="store_true")

    evaluate = commands.add_parser("evaluate-calibration")
    _add_config(evaluate)
    evaluate.add_argument("--assistant-labels", default=str(DEFAULT_ASSISTANT_LABELS))
    evaluate.add_argument("--user-labels", default=str(DEFAULT_USER_LABELS))

    audit = commands.add_parser("freeze-fresh-audit")
    _add_config(audit)
    audit.add_argument("--resume", action="store_true")

    audit_eval = commands.add_parser("evaluate-fresh-audit")
    _add_config(audit_eval)
    audit_eval.add_argument("--labels", default=str(DEFAULT_FRESH_AUDIT_LABELS))

    splits = commands.add_parser("freeze-splits")
    _add_config(splits)
    splits.add_argument("--resume", action="store_true")

    shadow = commands.add_parser("evaluate-shadow-gate")
    _add_config(shadow)
    shadow.add_argument("--report", required=True)

    release = commands.add_parser("finalize-release")
    _add_config(release)
    release.add_argument("--resume", action="store_true")

    status = commands.add_parser("status")
    _add_config(status)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "freeze-protocol":
        result = freeze_protocol(
            args.config, resume=args.resume, project_root=PROJECT_ROOT
        )
    elif args.command == "prepare-source-pool":
        result = prepare_source_pool(
            args.config,
            dataset=args.dataset,
            resume=args.resume,
            max_new_rows=args.max_new_rows,
            project_root=PROJECT_ROOT,
        )
    elif args.command in {"run-pilot", "run-formal-scan"}:
        result = run_scan(
            args.config,
            dataset=args.dataset,
            stage="pilot" if args.command == "run-pilot" else "formal_scan",
            resume=args.resume,
            max_new_waves=args.max_new_waves,
            project_root=PROJECT_ROOT,
        )
    elif args.command == "freeze-calibration":
        result = freeze_calibration(
            args.config, resume=args.resume, project_root=PROJECT_ROOT
        )
    elif args.command == "validate-assistant-labels":
        result = validate_assistant_labels(
            args.config, args.labels, project_root=PROJECT_ROOT
        )
    elif args.command == "prepare-user-review":
        result = prepare_user_review(
            args.config,
            args.assistant_labels,
            resume=args.resume,
            project_root=PROJECT_ROOT,
        )
    elif args.command == "evaluate-calibration":
        result = evaluate_calibration(
            args.config,
            args.assistant_labels,
            args.user_labels,
            project_root=PROJECT_ROOT,
        )
    elif args.command == "freeze-fresh-audit":
        result = freeze_fresh_audit(
            args.config, resume=args.resume, project_root=PROJECT_ROOT
        )
    elif args.command == "evaluate-fresh-audit":
        result = evaluate_fresh_audit(
            args.config, args.labels, project_root=PROJECT_ROOT
        )
    elif args.command == "freeze-splits":
        result = freeze_splits(
            args.config, resume=args.resume, project_root=PROJECT_ROOT
        )
    elif args.command == "evaluate-shadow-gate":
        result = evaluate_shadow_gate(
            args.config, args.report, project_root=PROJECT_ROOT
        )
    elif args.command == "finalize-release":
        result = finalize_release(
            args.config, resume=args.resume, project_root=PROJECT_ROOT
        )
    else:
        result = v22_status(args.config, project_root=PROJECT_ROOT)
    print(json.dumps(result, ensure_ascii=False))
    failure_statuses = {
        "failed_capacity_shortfall",
        "failed_new_protocol_identity_required",
        "failed_global_query_revision_required",
    }
    return 1 if result.get("status") in failure_statuses else 0


if __name__ == "__main__":
    raise SystemExit(main())
