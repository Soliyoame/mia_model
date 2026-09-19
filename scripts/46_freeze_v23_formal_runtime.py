"""冻结并只读验证 PCV-MIA v23 formal runtime。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v23_formal_runtime import (  # noqa: E402
    freeze_formal_runtime,
    prepare_formal_source_scan_authorization,
    run_formal_source_scan,
    status,
    validate_formal_source_scan,
    validate_formal_source_scan_authorization,
    validate_formal_runtime_freeze,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PCV-MIA v23 formal runtime offline freeze/validation"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("freeze")
    commands.add_parser("validate-freeze")
    commands.add_parser("status")
    authorization = commands.add_parser("prepare-formal-source-scan-authorization")
    authorization.add_argument("--dataset", required=True, choices=("edgar",))
    authorization.add_argument("--budget-limit", required=True, type=int)
    authorization.add_argument("--user-authorization-record", required=True)
    validate_authorization = commands.add_parser(
        "validate-formal-source-scan-authorization"
    )
    validate_authorization.add_argument("--authorization", required=True)
    run_scan = commands.add_parser("run-formal-source-scan")
    run_scan.add_argument("--authorization", required=True)
    validate_scan = commands.add_parser("validate-formal-source-scan")
    validate_scan.add_argument("--authorization", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "freeze":
        result = freeze_formal_runtime(PROJECT_ROOT)
    elif args.command == "validate-freeze":
        result = validate_formal_runtime_freeze(PROJECT_ROOT)
    elif args.command == "status":
        result = status(PROJECT_ROOT)
    elif args.command == "prepare-formal-source-scan-authorization":
        result = prepare_formal_source_scan_authorization(
            project_root=PROJECT_ROOT,
            dataset=args.dataset,
            budget_limit=args.budget_limit,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "validate-formal-source-scan-authorization":
        result = validate_formal_source_scan_authorization(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    elif args.command == "run-formal-source-scan":
        result = run_formal_source_scan(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    else:
        result = validate_formal_source_scan(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
