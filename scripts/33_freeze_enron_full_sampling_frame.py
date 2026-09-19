"""Freeze the v21 Enron full-corpus sampling frame and screening pool."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.enron_sampling import freeze_enron_sampling_frame  # noqa: E402
from src.utils.io import load_yaml, resolve_path  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze the complete-Enron hash sampling frame"
    )
    parser.add_argument(
        "--config",
        default="configs/data_config_v21_enron_full.yaml",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.resume and args.force:
        raise ValueError("--resume and --force are mutually exclusive")
    config = load_yaml(args.config)
    sampling = dict(config.get("enron_sampling_frame") or {})
    if sampling.get("protocol") != "enron_full_csv_hash_sample_v1":
        raise RuntimeError("Unexpected Enron sampling protocol")
    result = freeze_enron_sampling_frame(
        raw_csv_path=resolve_path(sampling["raw_csv_path"]),
        selected_jsonl_path=resolve_path(sampling["selected_jsonl_path"]),
        selection_index_path=resolve_path(sampling["selection_index_path"]),
        pass_manifest_path=resolve_path(sampling["pass_manifest_path"]),
        final_manifest_path=resolve_path(sampling["manifest_path"]),
        selection_seed=int(sampling["selection_seed"]),
        expected_raw_records=int(sampling["expected_raw_records"]),
        expected_mailbox_users=int(sampling["expected_mailbox_users"]),
        raw_screening_target_sources=int(
            sampling["raw_screening_target_sources"]
        ),
        resume=args.resume,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
