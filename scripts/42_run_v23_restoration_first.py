"""Run the lightweight PCV-MIA v23 development selector workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v23 import (  # noqa: E402
    run_aggregate_df,
    run_development_pilot,
    status,
    validate_aggregate_df,
    validate_development_pilot,
    validate_development_pilot_group,
)


DATASETS = ("edgar", "enron", "pubmed")


def _dataset_argument(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument("--dataset", required=required, choices=DATASETS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PCV-MIA v23 lightweight local development workflow"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser("status")
    _dataset_argument(status_parser, required=False)
    _dataset_argument(commands.add_parser("aggregate-df"))
    _dataset_argument(commands.add_parser("validate-aggregate-df"))
    _dataset_argument(commands.add_parser("run-development-pilot"))
    _dataset_argument(commands.add_parser("validate-development-pilot"))
    commands.add_parser("validate-development-pilot-group")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        result = status(project_root=PROJECT_ROOT, dataset=args.dataset)
    elif args.command == "aggregate-df":
        result = run_aggregate_df(project_root=PROJECT_ROOT, dataset=args.dataset)
    elif args.command == "validate-aggregate-df":
        result = validate_aggregate_df(project_root=PROJECT_ROOT, dataset=args.dataset)
    elif args.command == "run-development-pilot":
        result = run_development_pilot(project_root=PROJECT_ROOT, dataset=args.dataset)
    elif args.command == "validate-development-pilot":
        result = validate_development_pilot(
            project_root=PROJECT_ROOT, dataset=args.dataset
        )
    else:
        result = validate_development_pilot_group(project_root=PROJECT_ROOT)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
