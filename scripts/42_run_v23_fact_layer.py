"""Run the independent v23 fact-layer workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v23_fact_layer import (  # noqa: E402
    extract_facts,
    run_development_pilot,
    select_pairs,
    status,
    validate_development_pilot,
    validate_facts,
)
from src.prepare.restoration_first_v23_fact_layer_selection_r2 import (  # noqa: E402
    run_development_pilot_r2,
    select_pairs_r2,
    validate_development_pilot_r2,
)


DATASETS = ("edgar", "enron", "pubmed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PCV-MIA v23 independent resumable fact-layer workflow"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser("status")
    status_parser.add_argument("--dataset", choices=DATASETS, required=False)
    for name in (
        "extract-facts",
        "validate-facts",
        "select-pairs",
        "run-development-pilot",
        "validate-development-pilot",
    ):
        command = commands.add_parser(name)
        command.add_argument("--dataset", choices=DATASETS, required=True)
        if name in {
            "select-pairs",
            "run-development-pilot",
            "validate-development-pilot",
        }:
            command.add_argument(
                "--selection-revision",
                choices=("r1", "r2"),
                default="r1",
            )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        result = status(project_root=PROJECT_ROOT, dataset=args.dataset)
    elif args.command == "extract-facts":
        result = extract_facts(project_root=PROJECT_ROOT, dataset=args.dataset)
    elif args.command == "validate-facts":
        result = validate_facts(project_root=PROJECT_ROOT, dataset=args.dataset)
    elif args.command == "select-pairs":
        runner = select_pairs_r2 if args.selection_revision == "r2" else select_pairs
        result = runner(project_root=PROJECT_ROOT, dataset=args.dataset)
    elif args.command == "run-development-pilot":
        runner = (
            run_development_pilot_r2
            if args.selection_revision == "r2"
            else run_development_pilot
        )
        result = runner(project_root=PROJECT_ROOT, dataset=args.dataset)
    else:
        runner = (
            validate_development_pilot_r2
            if args.selection_revision == "r2"
            else validate_development_pilot
        )
        result = runner(project_root=PROJECT_ROOT, dataset=args.dataset)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
