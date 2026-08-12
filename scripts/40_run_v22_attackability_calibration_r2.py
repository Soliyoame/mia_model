"""Run the independent assistant-only PCV-MIA v22 calibration r2."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.attackability_calibration_r2 import (  # noqa: E402
    check_r2_capacity,
    evaluate_calibration_r2,
    freeze_calibration_r2,
    r2_status,
    validate_r2_assistant_labels,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "attackability_calibration_r2.yaml"
DEFAULT_LABELS = (
    PROJECT_ROOT
    / "artifacts"
    / "v22"
    / "calibration_r2"
    / "private"
    / "assistant_labels.jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run assistant-only PCV-MIA v22 calibration r2"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check-capacity", "status"):
        command = commands.add_parser(name)
        command.add_argument("--config", default=str(DEFAULT_CONFIG))
    freeze = commands.add_parser("freeze")
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
    if args.command == "check-capacity":
        result = check_r2_capacity(args.config, project_root=PROJECT_ROOT)
    elif args.command == "freeze":
        result = freeze_calibration_r2(
            args.config, resume=args.resume, project_root=PROJECT_ROOT
        )
    elif args.command == "validate-assistant-labels":
        result = validate_r2_assistant_labels(
            args.config, args.labels, project_root=PROJECT_ROOT
        )
    elif args.command == "evaluate":
        result = evaluate_calibration_r2(
            args.config, args.labels, project_root=PROJECT_ROOT
        )
    else:
        result = r2_status(args.config, project_root=PROJECT_ROOT)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if str(result.get("status") or "").startswith("failed_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
