"""Create and verify v20 provenance before the approved large-artifact cleanup."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_ROOT = PROJECT_ROOT / "legacy" / "provenance_v20_superseded_20260803"
TARGETS = (
    "artifacts/v6_3",
    "artifacts/v20",
    "indexes",
    "outputs",
    "legacy/abandoned_retriever_20260730",
    "legacy/pre_response_regroup_20260731",
)
STOP_REASON = (
    "superseded_by_pcv_mia_v21_full_rescan_luna_queries_qwen_ia_shadow_"
    "gemma2_2b_primary"
)
EVIDENCE_TOKENS = (
    "manifest",
    "benchmark",
    "split",
    "audit",
    "gate",
    "report",
    "identity",
    "schedule",
    "whitelist",
    "registry",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args()


def _safe_target(relative: str) -> Path:
    root = PROJECT_ROOT.resolve()
    target = (PROJECT_ROOT / relative).resolve()
    if target == root or root not in target.parents:
        raise RuntimeError(f"Unsafe provenance target: {target}")
    if target == PROVENANCE_ROOT.resolve() or PROVENANCE_ROOT.resolve() in target.parents:
        raise RuntimeError(f"Provenance output cannot be a cleanup target: {target}")
    return target


def _hash_and_rows(path: Path) -> tuple[str, int | None]:
    digest = hashlib.sha256()
    rows = 0 if path.suffix.casefold() == ".jsonl" else None
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            if rows is not None:
                rows += chunk.count(b"\n")
    return digest.hexdigest(), rows


def _git_state() -> dict[str, Any]:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        return result.stdout.strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "status_porcelain": run("status", "--porcelain=v1"),
    }


def build_provenance() -> dict[str, Any]:
    if PROVENANCE_ROOT.exists():
        raise FileExistsError(
            f"Provenance directory already exists; overwrite refused: {PROVENANCE_ROOT}"
        )
    evidence_root = PROVENANCE_ROOT / "evidence"
    evidence_root.mkdir(parents=True)
    inventory_path = PROVENANCE_ROOT / "inventory.jsonl"
    entries: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    target_summaries: list[dict[str, Any]] = []

    for relative in TARGETS:
        target = _safe_target(relative)
        target_entries = 0
        target_bytes = 0
        if target.is_file():
            files = [target]
        elif target.is_dir():
            files = sorted(path for path in target.rglob("*") if path.is_file())
        else:
            files = []
        for path in files:
            digest, row_count = _hash_and_rows(path)
            size = path.stat().st_size
            rel_path = path.relative_to(PROJECT_ROOT).as_posix()
            entry = {
                "path": rel_path,
                "target": relative,
                "size": size,
                "mtime_utc": datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).isoformat(),
                "sha256": digest,
                "jsonl_rows": row_count,
            }
            entries.append(entry)
            target_entries += 1
            target_bytes += size
            name = path.name.casefold()
            copy_evidence = (
                any(token in name for token in EVIDENCE_TOKENS)
                and size <= 10 * 1024 * 1024
                and path.suffix.casefold() in {".json", ".jsonl", ".yaml", ".yml", ".md", ".txt", ".csv"}
            )
            if copy_evidence:
                destination = evidence_root / rel_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                copied_hash, _ = _hash_and_rows(destination)
                if copied_hash != digest:
                    raise RuntimeError(f"Evidence copy hash mismatch: {destination}")
                evidence.append(
                    {
                        "source_path": rel_path,
                        "evidence_path": destination.relative_to(PROVENANCE_ROOT).as_posix(),
                        "sha256": copied_hash,
                        "size": size,
                    }
                )
        target_summaries.append(
            {
                "target": relative,
                "resolved_path": str(target),
                "exists": target.exists(),
                "file_count": target_entries,
                "total_bytes": target_bytes,
            }
        )

    with inventory_path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    inventory_hash, inventory_rows = _hash_and_rows(inventory_path)
    summary = {
        "protocol_version": "pcv-mia-v21",
        "legacy_protocol_version": "pcv-mia-v20",
        "status": "provenance_complete_cleanup_not_yet_executed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stop_reason": STOP_REASON,
        "targets": target_summaries,
        "total_files": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
        "inventory_path": "inventory.jsonl",
        "inventory_sha256": inventory_hash,
        "inventory_rows": inventory_rows,
        "evidence_files": evidence,
        "git": _git_state(),
    }
    (PROVENANCE_ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def verify_provenance() -> dict[str, Any]:
    summary_path = PROVENANCE_ROOT / "summary.json"
    inventory_path = PROVENANCE_ROOT / "inventory.jsonl"
    if not summary_path.is_file() or not inventory_path.is_file():
        raise FileNotFoundError("Provenance summary/inventory is missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    inventory_hash, inventory_rows = _hash_and_rows(inventory_path)
    if inventory_hash != summary.get("inventory_sha256"):
        raise RuntimeError("Provenance inventory hash mismatch")
    if inventory_rows != summary.get("inventory_rows"):
        raise RuntimeError("Provenance inventory row-count mismatch")
    if int(summary.get("total_files") or -1) != int(inventory_rows or 0):
        raise RuntimeError("Provenance total file count mismatch")
    for item in summary.get("evidence_files") or []:
        evidence_path = PROVENANCE_ROOT / str(item["evidence_path"])
        digest, _ = _hash_and_rows(evidence_path)
        if digest != item["sha256"]:
            raise RuntimeError(f"Evidence verification failed: {evidence_path}")
    verification = {
        "status": "verified_cleanup_authorized",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "inventory_sha256": inventory_hash,
        "inventory_rows": inventory_rows,
        "evidence_file_count": len(summary.get("evidence_files") or []),
        "approved_cleanup_targets": list(TARGETS),
    }
    (PROVENANCE_ROOT / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return verification


def main() -> int:
    result = verify_provenance() if parse_args().verify else build_provenance()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
