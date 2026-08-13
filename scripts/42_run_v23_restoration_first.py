"""Inspect and validate the isolated PCV-MIA v23 Restoration-First runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v23 import (  # noqa: E402
    prepare_aggregate_df_authorization,
    prepare_runtime_bootstrap_authorization,
    prepare_runtime_successor_freeze_authorization,
    run_aggregate_df,
    run_runtime_bootstrap,
    run_runtime_successor_freeze,
    validate_aggregate_df,
    validate_design_bindings,
    validate_implementation_authorization,
    validate_runtime_bootstrap,
    validate_runtime_successor_freeze,
    v23_status,
)


DEFAULT_IMPLEMENTATION_AUTHORIZATION = (
    PROJECT_ROOT
    / "artifacts"
    / "v23"
    / "governance"
    / "implementation_authorizations"
    / "5c191b1b132a7376c152014c896bf8c4b0295ab46dadd39dce58ff0dff19751d.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the zero-external-call v23 Restoration-First runtime"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("validate-design")
    prepare = commands.add_parser("prepare-bootstrap-authorization")
    prepare.add_argument("--user-authorization-record", required=True)
    bootstrap = commands.add_parser("bootstrap")
    bootstrap.add_argument("--authorization", required=True)
    validate_bootstrap = commands.add_parser("validate-bootstrap")
    validate_bootstrap.add_argument("--authorization")
    prepare_successor = commands.add_parser(
        "prepare-successor-freeze-authorization"
    )
    prepare_successor.add_argument("--user-authorization-record", required=True)
    freeze_successor = commands.add_parser("freeze-successor-runtime")
    freeze_successor.add_argument("--authorization", required=True)
    validate_successor = commands.add_parser("validate-successor-runtime")
    validate_successor.add_argument("--authorization", required=True)
    prepare_df = commands.add_parser("prepare-aggregate-df-authorization")
    prepare_df.add_argument(
        "--dataset", required=True, choices=("edgar", "enron", "pubmed")
    )
    prepare_df.add_argument("--user-authorization-record", required=True)
    aggregate_df = commands.add_parser("aggregate-df")
    aggregate_df.add_argument(
        "--dataset", required=True, choices=("edgar", "enron", "pubmed")
    )
    aggregate_df.add_argument("--authorization", required=True)
    validate_df = commands.add_parser("validate-aggregate-df")
    validate_df.add_argument(
        "--dataset", required=True, choices=("edgar", "enron", "pubmed")
    )
    authorization = commands.add_parser("validate-implementation-authorization")
    authorization.add_argument(
        "--authorization",
        default=str(DEFAULT_IMPLEMENTATION_AUTHORIZATION),
    )
    authorization.add_argument(
        "--requested-path",
        action="append",
        default=[],
        help="Repository-relative path that must be covered by the authorization",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        result = v23_status(PROJECT_ROOT)
    elif args.command == "validate-design":
        result = validate_design_bindings(PROJECT_ROOT)
    elif args.command == "prepare-bootstrap-authorization":
        result = prepare_runtime_bootstrap_authorization(
            project_root=PROJECT_ROOT,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "bootstrap":
        result = run_runtime_bootstrap(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    elif args.command == "validate-bootstrap":
        result = validate_runtime_bootstrap(
            PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    elif args.command == "prepare-successor-freeze-authorization":
        result = prepare_runtime_successor_freeze_authorization(
            project_root=PROJECT_ROOT,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "freeze-successor-runtime":
        result = run_runtime_successor_freeze(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    elif args.command == "validate-successor-runtime":
        result = validate_runtime_successor_freeze(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    elif args.command == "prepare-aggregate-df-authorization":
        result = prepare_aggregate_df_authorization(
            project_root=PROJECT_ROOT,
            dataset=args.dataset,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "aggregate-df":
        result = run_aggregate_df(
            project_root=PROJECT_ROOT,
            dataset=args.dataset,
            authorization_path=args.authorization,
        )
    elif args.command == "validate-aggregate-df":
        result = validate_aggregate_df(
            project_root=PROJECT_ROOT,
            dataset=args.dataset,
        )
    else:
        result = validate_implementation_authorization(
            args.authorization,
            requested_paths=args.requested_path,
            project_root=PROJECT_ROOT,
        )
        result = {
            "status": "passed",
            "authorization_id": result["authorization_id"],
            "authorized_stage": result["authorized_stage"],
            "external_calls_allowed": result["external_calls_allowed"],
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
