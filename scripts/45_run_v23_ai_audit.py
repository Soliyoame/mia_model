"""Run the isolated v23 assistant-only blind-packet audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v23_ai_audit import (  # noqa: E402
    prepare_ai_audit_authorization,
    run_ai_audit,
    validate_ai_audit_authorization,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PCV-MIA v23 assistant-only blind-packet structural audit"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-authorization")
    prepare.add_argument("--user-authorization-record", required=True)
    validate = commands.add_parser("validate-authorization")
    validate.add_argument("--authorization", required=True)
    run = commands.add_parser("run")
    run.add_argument("--authorization", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "prepare-authorization":
        result = prepare_ai_audit_authorization(
            project_root=PROJECT_ROOT,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "validate-authorization":
        result = validate_ai_audit_authorization(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    else:
        result = run_ai_audit(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

