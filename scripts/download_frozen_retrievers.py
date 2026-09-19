"""下载并验证 v20 冻结的 BGE Retriever snapshots；不调用 Generator API。"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import requests
from huggingface_hub import constants as hf_constants

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.hash import sha256_file
from src.utils.io import load_yaml, resolve_path, write_json


REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "BAAI/bge-base-en-v1.5": (
        "1_Pooling/config.json",
        "config.json",
        "config_sentence_transformers.json",
        "model.safetensors",
        "modules.json",
        "sentence_bert_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.txt",
    ),
    "BAAI/bge-reranker-base": (
        "config.json",
        "model.safetensors",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ),
}


@dataclass(frozen=True)
class FrozenModelSpec:
    repo_id: str
    revision: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download frozen BGE snapshots without any Generator API calls."
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "configs" / "rag_config.yaml"),
    )
    parser.add_argument("--endpoint", default="https://hf-mirror.com")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def frozen_model_specs(config: dict[str, Any]) -> tuple[FrozenModelSpec, ...]:
    embedding = config["embedding"]
    hybrid = config["retrieval"]["hybrid"]
    specs = (
        FrozenModelSpec(
            repo_id=str(embedding["model"]),
            revision=str(embedding.get("revision") or ""),
        ),
        FrozenModelSpec(
            repo_id=str(hybrid["reranker_model"]),
            revision=str(hybrid.get("reranker_revision") or ""),
        ),
    )
    for spec in specs:
        if spec.repo_id not in REQUIRED_FILES:
            raise ValueError(f"Unsupported frozen retriever repository: {spec.repo_id}")
        if re.fullmatch(r"[0-9a-f]{40}", spec.revision) is None:
            raise ValueError(
                f"Exact 40-character commit SHA required for {spec.repo_id}: "
                f"{spec.revision!r}"
            )
    return specs


def snapshot_root(cache_dir: Path, spec: FrozenModelSpec) -> Path:
    repo_cache_key = f"models--{spec.repo_id.replace('/', '--')}"
    return cache_dir / repo_cache_key / "snapshots" / spec.revision


def _download_file(
    session: requests.Session,
    *,
    endpoint: str,
    spec: FrozenModelSpec,
    filename: str,
    destination: Path,
    force: bool,
) -> None:
    if destination.is_file() and destination.stat().st_size > 0 and not force:
        print(
            f"SKIP {spec.repo_id} {filename} ({destination.stat().st_size} bytes)",
            flush=True,
        )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_name(f"{destination.name}.part")
    url = (
        f"{endpoint.rstrip('/')}/{quote(spec.repo_id, safe='/')}/resolve/"
        f"{spec.revision}/{quote(filename, safe='/')}"
    )
    print(f"DOWNLOAD {spec.repo_id} {filename}", flush=True)
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
                    print(
                        f"PROGRESS {spec.repo_id} {filename} "
                        f"{downloaded / 1024 / 1024:.0f} MiB",
                        flush=True,
                    )
                    next_report += 128 * 1024 * 1024
    if downloaded <= 0:
        raise RuntimeError(f"Downloaded empty file: {url}")
    os.replace(part_path, destination)
    print(
        f"DONE {spec.repo_id} {filename} ({destination.stat().st_size} bytes)",
        flush=True,
    )


def main() -> int:
    args = parse_args()
    endpoint = str(args.endpoint).rstrip("/")
    if not endpoint.startswith("https://"):
        raise ValueError("--endpoint must use HTTPS")
    config = load_yaml(args.config)
    specs = frozen_model_specs(config)
    cache_dir = (
        resolve_path(args.cache_dir)
        if args.cache_dir
        else Path(hf_constants.HF_HUB_CACHE).resolve()
    )
    session = requests.Session()
    for spec in specs:
        root = snapshot_root(cache_dir, spec)
        for filename in REQUIRED_FILES[spec.repo_id]:
            destination = root.joinpath(*PurePosixPath(filename).parts)
            _download_file(
                session,
                endpoint=endpoint,
                spec=spec,
                filename=filename,
                destination=destination,
                force=bool(args.force),
            )
        files = {
            filename: {
                "size": (root.joinpath(*PurePosixPath(filename).parts)).stat().st_size,
                "sha256": sha256_file(
                    root.joinpath(*PurePosixPath(filename).parts)
                ),
            }
            for filename in REQUIRED_FILES[spec.repo_id]
        }
        write_json(
            {
                "repo_id": spec.repo_id,
                "revision": spec.revision,
                "endpoint": endpoint,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "files": files,
            },
            root / "pcv_snapshot_manifest.json",
        )
        print(f"SNAPSHOT_READY {spec.repo_id} {root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
