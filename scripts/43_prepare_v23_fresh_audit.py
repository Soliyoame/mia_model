"""Freeze and validate the frozen-r2 fresh-audit preparation runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v23_fresh_audit_preparation import (  # noqa: E402
    build_packets,
    freeze_preparation,
    prepare_dataset,
    prepare_run_authorization,
    status,
    validate_preparation_freeze,
    validate_run_authorization,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PCV-MIA v23 frozen-r2 fresh-audit preparation runner"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("freeze")
    commands.add_parser("validate-freeze")
    commands.add_parser("status")
    prepare = commands.add_parser("prepare-authorization")
    prepare.add_argument("--stage", choices=("dataset_preparation", "packet_preparation"), required=True)
    prepare.add_argument("--dataset", choices=("edgar", "enron", "pubmed"))
    prepare.add_argument("--user-authorization-record", required=True)
    validate = commands.add_parser("validate-authorization")
    validate.add_argument("--authorization", required=True)
    validate.add_argument("--stage", choices=("dataset_preparation", "packet_preparation"), required=True)
    validate.add_argument("--dataset", choices=("edgar", "enron", "pubmed"))
    dataset_prepare = commands.add_parser("prepare-dataset")
    dataset_prepare.add_argument("--dataset", choices=("edgar", "enron", "pubmed"), required=True)
    dataset_prepare.add_argument("--authorization", required=True)
    packets = commands.add_parser("build-packets")
    packets.add_argument("--authorization", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "freeze":
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
