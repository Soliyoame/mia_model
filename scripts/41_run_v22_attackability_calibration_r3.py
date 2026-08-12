"""Run the final PCV-MIA v22 calibration r3."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.attackability_calibration_r3 import (  # noqa: E402
    check_r3_capacity,
    evaluate_calibration_r3,
    freeze_calibration_r3,
    freeze_context_plan,
    r3_status,
    run_context_validation,
    validate_r3_assistant_labels,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "attackability_calibration_r3.yaml"
DEFAULT_LABELS = (
    PROJECT_ROOT
    / "artifacts"
    / "v22"
    / "calibration_r3"
    / "private"
    / "assistant_labels.jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PCV-MIA v22 calibration r3")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--config", default=str(DEFAULT_CONFIG))
    context = commands.add_parser("freeze-context-plan")
    context.add_argument("--config", default=str(DEFAULT_CONFIG))
    context.add_argument("--resume", action="store_true")
    run = commands.add_parser("run-context-validation")
    run.add_argument("--config", default=str(DEFAULT_CONFIG))
    run.add_argument("--resume", action="store_true")
    run.add_argument("--max-new-batches", type=int, default=1)
    capacity = commands.add_parser("check-capacity")
    capacity.add_argument("--config", default=str(DEFAULT_CONFIG))
    freeze = commands.add_parser("freeze-calibration")
    freeze.add_argument("--config", default=str(DEFAULT_CONFIG))
    freeze.add_argument("--resume", action="store_true")
    validate = commands.add_parser("validate-assistant-labels")
    validate.add_argument("--config", default=str(DEFAULT_CONFIG))
    validate.add_argument("--labels", default=str(DEFAULT_LABELS))
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--config", default=str(DEFAULT_CONFIG))
    evaluate.add_argument("--labels", default=str(DEFAULT_LABELS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        result = r3_status(args.config, project_root=PROJECT_ROOT)
    elif args.command == "freeze-context-plan":
        result = freeze_context_plan(
            args.config, resume=args.resume, project_root=PROJECT_ROOT
        )
    elif args.command == "run-context-validation":
        result = run_context_validation(
            args.config,
            resume=args.resume,
            max_new_batches=args.max_new_batches,
            project_root=PROJECT_ROOT,
        )
    elif args.command == "check-capacity":
        result = check_r3_capacity(args.config, project_root=PROJECT_ROOT)
    elif args.command == "freeze-calibration":
        result = freeze_calibration_r3(
            args.config, resume=args.resume, project_root=PROJECT_ROOT
        )
    elif args.command == "validate-assistant-labels":
        result = validate_r3_assistant_labels(
            args.config, args.labels, project_root=PROJECT_ROOT
        )
    else:
        result = evaluate_calibration_r3(
            args.config, args.labels, project_root=PROJECT_ROOT
        )
    print(json.dumps(result, ensure_ascii=False))
    return 1 if str(result.get("status") or "").startswith("failed_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
