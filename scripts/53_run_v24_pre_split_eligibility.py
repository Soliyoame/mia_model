"""Offline v24 pre-split eligibility utilities.

This CLI intentionally exposes only validation, source-pool binding, and a
small mock-friendly split helper.  It never starts Luna, Retriever, victim, or
GPU work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.restoration_first_v24 import (  # noqa: E402
    load_v24_config,
    source_pool_bindings,
    validate_eligibility_manifest,
    validate_split_manifest,
)
from src.utils.io import read_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="v24 offline pre-split eligibility checks")
    parser.add_argument("command", choices=("validate-config", "source-pools", "validate-eligibility", "validate-split"))
    parser.add_argument("--manifest", help="普通 v24 manifest 路径（仅 validate-* 命令使用）")
    args = parser.parse_args()
    if args.command == "validate-config":
        config = load_v24_config(PROJECT_ROOT)
        print(json.dumps({"status": "passed", "protocol_version": config["protocol_version"], "external_calls_performed": 0}, ensure_ascii=False))
    elif args.command == "source-pools":
        print(json.dumps({"status": "passed", "source_pools": source_pool_bindings(PROJECT_ROOT), "external_calls_performed": 0}, ensure_ascii=False))
    else:
        if not args.manifest:
            parser.error("validate-* requires --manifest")
        payload = read_json(Path(args.manifest))
        validator = validate_eligibility_manifest if args.command == "validate-eligibility" else validate_split_manifest
        result = validator(payload)
        print(json.dumps({**result, "external_calls_performed": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
