"""Recover a fail-closed v21 calibration identity from retained v20 evidence.

This script does not recreate the deleted calibration summary.  It creates a
new provenance record that binds the deleted file's inventory hash to the
surviving research record, frozen decision surface, and semantic model lock.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.attack.semantic_entity_resolver import (  # noqa: E402
    semantic_thresholds_sha256,
)
from src.utils.hash import sha256_file, sha256_text  # noqa: E402
from src.utils.io import load_yaml, resolve_path, write_json  # noqa: E402


PROTOCOL = "pcv_mia_v21_calibration_provenance_recovery_v1"
STATUS = "verified_from_immutable_inventory_and_research_record"
REQUIRED_TYPES = {
    "PERSON",
    "ORG",
    "LOCATION",
    "PRODUCT",
    "PROJECT_NAME",
    "CONTRACT_TERM",
}
DEFAULT_PROVENANCE_ROOT = (
    PROJECT_ROOT / "legacy" / "provenance_v20_superseded_20260803"
)
DEFAULT_NOTES_PATH = PROJECT_ROOT / "研究记录" / "顶会推进_notes.md"
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "v21"
    / "release_controls"
    / "semantic_calibration_provenance.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--attack-config",
        default="configs/pcv_attack_v6_3.yaml",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    return parser.parse_args()


def _inventory_entry(inventory_path: Path, legacy_path: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    with inventory_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("path") == legacy_path:
                matches.append(row)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one retained inventory entry for {legacy_path}; "
            f"found {len(matches)}"
        )
    return matches[0]


def _research_evidence(notes_path: Path) -> str:
    text = notes_path.read_text(encoding="utf-8")
    start_marker = "### Phase 7I 阶段 D 按实体类型阈值校准通过（2026-07-25）"
    end_marker = "### Phase 7I 阶段 E 隔离配置冻结与 formal loader 核验（2026-07-25）"
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise RuntimeError("Frozen Phase 7I calibration evidence block is missing")
    evidence = text[start:end].strip()
    required_fragments = (
        "rows=206",
        "false accepts=0",
        "overall precision=1.0",
        "六类 precision 均为 1.0",
        "d180bdb02d5bcb5748cfac64b955ecc307b37022671c0200a35a50d0394edfa8",
    )
    missing = [fragment for fragment in required_fragments if fragment not in evidence]
    if missing:
        raise RuntimeError(f"Research calibration evidence drift: {missing}")
    return evidence


def _threshold_hash(semantic: dict[str, Any]) -> str:
    return semantic_thresholds_sha256(
        min_target_confidence=float(semantic.get("min_target_confidence", 0.0)),
        min_confidence_margin=float(semantic.get("min_confidence_margin", 0.0)),
        min_consensus_votes=int(semantic.get("min_consensus_votes", 0)),
        min_boundary_votes=int(semantic.get("min_boundary_votes", 0)),
        biomedical_veto_threshold=float(
            semantic.get("biomedical_veto_threshold", 0.0)
        ),
        overlap_threshold=float(semantic.get("overlap_threshold", 0.0)),
        thresholds_by_entity_type=semantic.get("thresholds_by_entity_type"),
    )


def build_record(attack_config_path: Path) -> dict[str, Any]:
    attack_config = load_yaml(attack_config_path)
    semantic = (
        attack_config.get("fact_extraction", {}).get("semantic_resolver", {})
    )
    frozen_hash = str(semantic.get("thresholds_sha256") or "")
    if semantic.get("thresholds_frozen") is not True:
        raise RuntimeError("Semantic thresholds are not frozen")
    if _threshold_hash(semantic) != frozen_hash:
        raise RuntimeError("Current semantic decision surface does not match its hash")
    type_thresholds = semantic.get("thresholds_by_entity_type") or {}
    if set(type_thresholds) != REQUIRED_TYPES:
        raise RuntimeError("Current semantic decision surface does not cover six types")

    provenance_summary_path = DEFAULT_PROVENANCE_ROOT / "summary.json"
    provenance_verification_path = DEFAULT_PROVENANCE_ROOT / "verification.json"
    inventory_path = DEFAULT_PROVENANCE_ROOT / "inventory.jsonl"
    summary = json.loads(provenance_summary_path.read_text(encoding="utf-8"))
    verification = json.loads(
        provenance_verification_path.read_text(encoding="utf-8")
    )
    inventory_hash = sha256_file(inventory_path)
    if (
        summary.get("inventory_sha256") != inventory_hash
        or verification.get("inventory_sha256") != inventory_hash
        or verification.get("status") != "verified_cleanup_authorized"
    ):
        raise RuntimeError("Retained v20 provenance inventory is not verified")

    legacy_path = Path(str(semantic.get("calibration_summary_path"))).as_posix()
    inventory_entry = _inventory_entry(inventory_path, legacy_path)
    notes_evidence = _research_evidence(DEFAULT_NOTES_PATH)
    model_lock_path = resolve_path(semantic.get("model_lock_path"))

    return {
        "protocol": PROTOCOL,
        "status": STATUS,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Bind the deleted v20 calibration summary identity for v21 eligibility; "
            "this is provenance recovery, not a regenerated calibration result."
        ),
        "legacy_calibration": {
            "path": legacy_path,
            "sha256": inventory_entry["sha256"],
            "size": inventory_entry["size"],
            "inventory_path": inventory_path.relative_to(PROJECT_ROOT).as_posix(),
            "inventory_sha256": inventory_hash,
            "provenance_summary_sha256": sha256_file(provenance_summary_path),
            "provenance_verification_sha256": sha256_file(
                provenance_verification_path
            ),
        },
        "research_evidence": {
            "path": DEFAULT_NOTES_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "section": "Phase 7I 阶段 D 按实体类型阈值校准通过（2026-07-25）",
            "excerpt": notes_evidence,
            "excerpt_sha256": sha256_text(notes_evidence),
        },
        "selected": {
            "gate_passed": True,
            "rows": 206,
            "positives": 93,
            "negatives": 113,
            "overall": {
                "true_accepts": 68,
                "false_accepts": 0,
                "repaired_bad_boundaries": 9,
                "precision": 1.0,
                "recall": 0.7312,
            },
            "by_entity_type": {
                entity_type: {"precision": 1.0}
                for entity_type in sorted(REQUIRED_TYPES)
            },
        },
        "semantic_thresholds_sha256": frozen_hash,
        "model_lock": {
            "path": model_lock_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256_file(model_lock_path),
        },
        "limitations": [
            "The deleted calibration summary content was not copied into the v20 evidence directory.",
            "The original summary identity is retained through its pre-deletion path, size, and SHA-256.",
            "The calibration should be rerun from original labeled rows before publication if those rows are recovered.",
        ],
    }


def main() -> int:
    args = parse_args()
    output_path = resolve_path(args.output)
    if output_path.exists():
        raise FileExistsError(f"Overwrite refused: {output_path}")
    record = build_record(resolve_path(args.attack_config))
    write_json(record, output_path)
    result = {
        "status": "written",
        "path": str(output_path),
        "sha256": sha256_file(output_path),
        "legacy_calibration_sha256": record["legacy_calibration"]["sha256"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
