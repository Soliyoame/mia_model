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
    prepare_development_pilot_authorization,
    prepare_revision_reservation_authorization,
    prepare_runtime_bootstrap_authorization,
    prepare_runtime_successor_freeze_authorization,
    prepare_stage_carry_forward_authorization,
    run_aggregate_df,
    run_development_pilot,
    run_revision_reservation,
    run_runtime_bootstrap,
    run_runtime_successor_freeze,
    run_stage_carry_forward,
    stage_status,
    validate_aggregate_df,
    validate_development_pilot,
    validate_development_pilot_group,
    validate_design_bindings,
    validate_implementation_authorization,
    validate_runtime_bootstrap,
    validate_runtime_successor_freeze,
    validate_revision_reservation,
    validate_stage_carry_forward,
    v23_status,
)


DEFAULT_IMPLEMENTATION_AUTHORIZATION = (
    PROJECT_ROOT
    / "artifacts"
    / "v23"
    / "governance"
    / "implementation_authorizations"
    / "37dd6ce01efcda21bdfcfa48e9c8ab6f9444bd89a4f67930f6b8e5ff01f0e3d5.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the zero-external-call v23 Restoration-First runtime"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    scoped_status = commands.add_parser("stage-status")
    scoped_status.add_argument("--stage")
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
    prepare_carry = commands.add_parser("prepare-carry-forward-authorization")
    prepare_carry.add_argument(
        "--stage", required=True, choices=("aggregate_df_precomputation",)
    )
    prepare_carry.add_argument("--user-authorization-record", required=True)
    carry = commands.add_parser("carry-forward")
    carry.add_argument(
        "--stage", required=True, choices=("aggregate_df_precomputation",)
    )
    carry.add_argument("--authorization", required=True)
    validate_carry = commands.add_parser("validate-carry-forward")
    validate_carry.add_argument(
        "--stage", required=True, choices=("aggregate_df_precomputation",)
    )
    prepare_reservation = commands.add_parser(
        "prepare-revision-reservation-authorization"
    )
    prepare_reservation.add_argument("--user-authorization-record", required=True)
    run_reservation = commands.add_parser("run-revision-reservation")
    run_reservation.add_argument("--authorization", required=True)
    commands.add_parser("validate-revision-reservation")
    prepare_pilot = commands.add_parser(
        "prepare-development-pilot-authorization"
    )
    prepare_pilot.add_argument(
        "--dataset", required=True, choices=("edgar", "enron", "pubmed")
    )
    prepare_pilot.add_argument("--user-authorization-record", required=True)
    run_pilot = commands.add_parser("run-development-pilot")
    run_pilot.add_argument(
        "--dataset", required=True, choices=("edgar", "enron", "pubmed")
    )
    run_pilot.add_argument("--authorization", required=True)
    validate_pilot = commands.add_parser("validate-development-pilot")
    validate_pilot.add_argument(
        "--dataset", required=True, choices=("edgar", "enron", "pubmed")
    )
    commands.add_parser("validate-development-pilot-group")
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
    elif args.command == "stage-status":
        result = stage_status(PROJECT_ROOT, stage=args.stage)
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
    elif args.command == "prepare-carry-forward-authorization":
        result = prepare_stage_carry_forward_authorization(
            project_root=PROJECT_ROOT,
            stage=args.stage,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "carry-forward":
        result = run_stage_carry_forward(
            project_root=PROJECT_ROOT,
            stage=args.stage,
            authorization_path=args.authorization,
        )
    elif args.command == "validate-carry-forward":
        result = validate_stage_carry_forward(
            project_root=PROJECT_ROOT,
            stage=args.stage,
        )
    elif args.command == "prepare-revision-reservation-authorization":
        result = prepare_revision_reservation_authorization(
            project_root=PROJECT_ROOT,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "run-revision-reservation":
        result = run_revision_reservation(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    elif args.command == "validate-revision-reservation":
        result = validate_revision_reservation(project_root=PROJECT_ROOT)
    elif args.command == "prepare-development-pilot-authorization":
        result = prepare_development_pilot_authorization(
            project_root=PROJECT_ROOT,
            dataset=args.dataset,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "run-development-pilot":
        result = run_development_pilot(
            project_root=PROJECT_ROOT,
            dataset=args.dataset,
            authorization_path=args.authorization,
        )
    elif args.command == "validate-development-pilot":
        result = validate_development_pilot(
            project_root=PROJECT_ROOT,
            dataset=args.dataset,
        )
    elif args.command == "validate-development-pilot-group":
        result = validate_development_pilot_group(project_root=PROJECT_ROOT)
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
