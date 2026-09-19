"""Download and hash-lock the local-only NLI snapshot used by MEntA."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.baselines.menta import (  # noqa: E402
    MENTA_NLI_MODEL_ID,
    MENTA_NLI_REVISION,
    validate_nli_snapshot,
)
from src.utils.hash import sha256_file  # noqa: E402
from src.utils.io import load_yaml, resolve_path, write_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download the exact local-only MEntA DeBERTa snapshot"
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "configs" / "baseline_config.yaml"),
    )
    parser.add_argument("--endpoint", default="https://hf-mirror.com")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _validated_spec(config: dict[str, Any]) -> tuple[str, str, Path]:
    nli = dict(config.get("baseline", {}).get("menta", {}).get("nli") or {})
    model_id = str(nli.get("model_id") or "")
    revision = str(nli.get("revision") or "")
    snapshot_dir = resolve_path(str(nli.get("snapshot_dir") or ""))
    if model_id != MENTA_NLI_MODEL_ID:
        raise ValueError(f"Unexpected MEntA NLI model id: {model_id!r}")
    if revision != MENTA_NLI_REVISION or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError(f"Unexpected MEntA NLI revision: {revision!r}")
    return model_id, revision, snapshot_dir


def _validated_snapshot_filename(filename: str) -> str:
    relative = PurePosixPath(str(filename))
    if not filename or relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"Unsafe MEntA NLI repository path: {filename!r}")
    return relative.as_posix()


def _list_snapshot_files(
    session: requests.Session,
    *,
    endpoint: str,
    model_id: str,
    revision: str,
) -> tuple[str, ...]:
    url = (
        f"{endpoint.rstrip('/')}/api/models/{quote(model_id, safe='/')}/"
        f"revision/{revision}"
    )
    with session.get(url, timeout=(30, 60)) as response:
        response.raise_for_status()
        payload = response.json()
    siblings = payload.get("siblings")
    if not isinstance(siblings, list):
        raise RuntimeError("MEntA NLI repository response contains no file list")
    files = tuple(
        sorted(
            {
                _validated_snapshot_filename(str(item.get("rfilename") or ""))
                for item in siblings
                if isinstance(item, dict)
            }
        )
    )
    if not files:
        raise RuntimeError("MEntA NLI repository file list is empty")
    return files


def _download_file(
    session: requests.Session,
    *,
    endpoint: str,
    model_id: str,
    revision: str,
    filename: str,
    destination: Path,
    force: bool,
) -> None:
    if destination.is_file() and destination.stat().st_size > 0 and not force:
        print(f"SKIP {filename} ({destination.stat().st_size} bytes)", flush=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_name(f"{destination.name}.part")
    url = (
        f"{endpoint.rstrip('/')}/{quote(model_id, safe='/')}/resolve/"
        f"{revision}/{quote(filename, safe='/')}"
    )
    print(f"DOWNLOAD {filename}", flush=True)
    downloaded = 0
    next_report = 128 * 1024 * 1024
    with session.get(url, stream=True, timeout=(30, 300)) as response:
        response.raise_for_status()
        with part_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_report:
                    print(f"PROGRESS {filename} {downloaded / 1024 / 1024:.0f} MiB", flush=True)
                    next_report += 128 * 1024 * 1024
    if downloaded <= 0:
        raise RuntimeError(f"Downloaded empty file: {url}")
    os.replace(part_path, destination)


def main() -> int:
    args = parse_args()
    endpoint = str(args.endpoint).rstrip("/")
    if not endpoint.startswith("https://"):
        raise ValueError("--endpoint must use HTTPS")
    config = load_yaml(args.config)
    model_id, revision, snapshot_dir = _validated_spec(config)
    manifest_path = snapshot_dir / "pcv_snapshot_manifest.json"
    if manifest_path.is_file() and not args.force:
        try:
            identity = validate_nli_snapshot(
                snapshot_dir,
                expected_model_id=model_id,
                expected_revision=revision,
            )
        except (FileNotFoundError, RuntimeError, ValueError):
            pass
        else:
            print(
                f"SNAPSHOT_READY {model_id}@{revision} "
                f"manifest={identity['snapshot_manifest_sha256']}",
                flush=True,
            )
            return 0

    session = requests.Session()
    snapshot_files = _list_snapshot_files(
        session,
        endpoint=endpoint,
        model_id=model_id,
        revision=revision,
    )
    for filename in snapshot_files:
        destination = snapshot_dir.joinpath(*PurePosixPath(filename).parts)
        _download_file(
            session,
            endpoint=endpoint,
            model_id=model_id,
            revision=revision,
            filename=filename,
            destination=destination,
            force=True,
        )
    files = {
        filename: {
            "size": snapshot_dir.joinpath(*PurePosixPath(filename).parts).stat().st_size,
            "sha256": sha256_file(
                snapshot_dir.joinpath(*PurePosixPath(filename).parts)
            ),
        }
        for filename in snapshot_files
    }
    write_json(
        {
            "repo_id": model_id,
            "revision": revision,
            "endpoint": endpoint,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
        },
        manifest_path,
    )
    identity = validate_nli_snapshot(
        snapshot_dir,
        expected_model_id=model_id,
        expected_revision=revision,
    )
    print(
        f"SNAPSHOT_READY {model_id}@{revision} "
        f"manifest={identity['snapshot_manifest_sha256']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
