"""Prepare the versioned v23 fresh-audit reserve expansion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v23_fresh_audit_preparation_r2 import (  # noqa: E402
    build_packets,
    freeze_policy,
    freeze_preparation,
    prepare_dataset,
    prepare_reservation_authorization,
    prepare_run_authorization,
    register_reserve_group,
    status,
    validate_policy_freeze,
    validate_preparation_freeze,
    validate_reservation_authorization,
    validate_reserve_group,
    validate_run_authorization,
)


DATASETS = ("edgar", "enron", "pubmed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PCV-MIA v23 r2 expanded fresh-audit reserve preparation"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("freeze-policy")
    commands.add_parser("validate-policy")
    commands.add_parser("register-status")
    reserve_auth = commands.add_parser("prepare-reservation-authorization")
    reserve_auth.add_argument("--user-authorization-record", required=True)
    reserve_validate = commands.add_parser("validate-reservation-authorization")
    reserve_validate.add_argument("--authorization", required=True)
    register = commands.add_parser("register-reserve-group")
    register.add_argument("--authorization", required=True)
    commands.add_parser("validate-reserve-group")
    commands.add_parser("freeze-preparation")
    commands.add_parser("validate-freeze")
    commands.add_parser("status")
    prepare_auth = commands.add_parser("prepare-authorization")
    prepare_auth.add_argument(
        "--stage", choices=("dataset_preparation", "packet_preparation"), required=True
    )
    prepare_auth.add_argument("--dataset", choices=DATASETS)
    prepare_auth.add_argument("--user-authorization-record", required=True)
    validate_auth = commands.add_parser("validate-authorization")
    validate_auth.add_argument("--authorization", required=True)
    validate_auth.add_argument(
        "--stage", choices=("dataset_preparation", "packet_preparation"), required=True
    )
    validate_auth.add_argument("--dataset", choices=DATASETS)
    dataset = commands.add_parser("prepare-dataset")
    dataset.add_argument("--dataset", choices=DATASETS, required=True)
    dataset.add_argument("--authorization", required=True)
    packet = commands.add_parser("build-packets")
    packet.add_argument("--authorization", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "freeze-policy":
        result = freeze_policy(PROJECT_ROOT)
    elif args.command == "validate-policy":
        result = validate_policy_freeze(PROJECT_ROOT)
    elif args.command == "register-status":
        result = status(PROJECT_ROOT)
    elif args.command == "prepare-reservation-authorization":
        result = prepare_reservation_authorization(
            project_root=PROJECT_ROOT,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "validate-reservation-authorization":
        result = validate_reservation_authorization(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    elif args.command == "register-reserve-group":
        result = register_reserve_group(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    elif args.command == "validate-reserve-group":
        result = validate_reserve_group(PROJECT_ROOT)
    elif args.command == "freeze-preparation":
        result = freeze_preparation(PROJECT_ROOT)
    elif args.command == "validate-freeze":
        result = validate_preparation_freeze(PROJECT_ROOT)
    elif args.command == "status":
        result = status(PROJECT_ROOT)
    elif args.command == "prepare-authorization":
        result = prepare_run_authorization(
            project_root=PROJECT_ROOT,
            stage=args.stage,
            dataset=args.dataset,
            user_authorization_record=args.user_authorization_record,
        )
    elif args.command == "validate-authorization":
        result = validate_run_authorization(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
            stage=args.stage,
            dataset=args.dataset,
        )
    elif args.command == "prepare-dataset":
        result = prepare_dataset(
            project_root=PROJECT_ROOT,
            dataset=args.dataset,
            authorization_path=args.authorization,
        )
    else:
        result = build_packets(
            project_root=PROJECT_ROOT,
            authorization_path=args.authorization,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
