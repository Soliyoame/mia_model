"""Download and freeze the local semantic models used by claim-pair v6.3."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import yaml

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")

from huggingface_hub import HfApi, snapshot_download


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.attack.semantic_entity_resolver import (  # noqa: E402
    SEMANTIC_RESOLVER_PROTOCOL,
    SEMANTIC_SCHEMA_SHA256,
)


HF_MODELS = (
    {
        "model_id": "fastino/gliner2-base-v1",
        "backend": "gliner2",
        "role": "gliner2_base",
        "package": "gliner2",
        "directory": "gliner2-base-v1",
    },
    {
        "model_id": "fastino/gliner2-large-v1",
        "backend": "gliner2",
        "role": "gliner2_large",
        "package": "gliner2",
        "directory": "gliner2-large-v1",
    },
    {
        "model_id": "Ihor/gliner-biomed-large-v1.0",
        "backend": "gliner_biomed",
        "role": "biomedical_veto",
        "package": "gliner",
        "directory": "gliner-biomed-large-v1.0",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and hash-lock the v6.3 local semantic models."
    )
    parser.add_argument(
        "--models-dir",
        default=str(PROJECT_ROOT / "models" / "v6_3"),
    )
    parser.add_argument(
        "--lock-path",
        default=str(
            PROJECT_ROOT
            / "configs"
            / "semantic_entity_models_v6_3.lock.yaml"
        ),
    )
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_model_directory(path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for artifact in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = artifact.relative_to(path)
        if (
            ".cache" in relative.parts
            or ".git" in relative.parts
            or "__pycache__" in relative.parts
            or artifact.suffix == ".pyc"
        ):
            continue
        hashes[relative.as_posix()] = _sha256_file(artifact)
    if not hashes:
        raise RuntimeError(f"No model artifacts found under {path}")
    return hashes


def _relative_to_project(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _download_huggingface_models(models_dir: Path) -> list[dict[str, Any]]:
    api = HfApi()
    locked: list[dict[str, Any]] = []
    for spec in HF_MODELS:
        model_id = str(spec["model_id"])
        info = api.model_info(model_id)
        revision = str(info.sha or "")
        if not revision:
            raise RuntimeError(f"Hugging Face returned no commit SHA for {model_id}")
        destination = models_dir / str(spec["directory"])
        destination.mkdir(parents=True, exist_ok=True)
        print(f"[download] {model_id}@{revision} -> {destination}", flush=True)
        for attempt in range(1, 6):
            try:
                snapshot_download(
                    repo_id=model_id,
                    revision=revision,
                    local_dir=destination,
                    max_workers=1,
                )
                break
            except Exception as exc:
                if attempt == 5:
                    raise
                delay = 2**attempt
                print(
                    f"[retry {attempt}/5] {model_id}: "
                    f"{type(exc).__name__}: {exc}; wait={delay}s",
                    flush=True,
                )
                time.sleep(delay)
        print(f"[hash] {model_id}", flush=True)
        locked.append(
            {
                "model_id": model_id,
                "backend": spec["backend"],
                "role": spec["role"],
                "local_path": _relative_to_project(destination),
                "revision": revision,
                "package": spec["package"],
                "package_version": importlib.metadata.version(
                    str(spec["package"])
                ),
                "files_sha256": _hash_model_directory(destination),
            }
        )
    return locked


def _find_spacy_data_directory() -> Path:
    package = importlib.import_module("en_core_web_trf")
    package_root = Path(package.__file__).resolve().parent
    candidates = sorted(
        meta.parent
        for meta in package_root.rglob("meta.json")
        if meta.is_file() and (meta.parent / "config.cfg").is_file()
    )
    if not candidates:
        raise RuntimeError(
            f"Cannot locate en_core_web_trf model data under {package_root}"
        )
    return candidates[0]


def _freeze_spacy_model(models_dir: Path) -> dict[str, Any]:
    source = _find_spacy_data_directory()
    destination = models_dir / "en_core_web_trf-3.8.0-data"
    if not destination.exists():
        print(f"[copy] {source} -> {destination}", flush=True)
        shutil.copytree(source, destination)
    else:
        print(f"[reuse] {destination}", flush=True)
    print("[hash] en_core_web_trf==3.8.0", flush=True)
    return {
        "model_id": "en_core_web_trf==3.8.0",
        "backend": "spacy",
        "role": "spacy_transformer",
        "local_path": _relative_to_project(destination),
        "revision": "3.8.0",
        "package": "en_core_web_trf",
        "package_version": importlib.metadata.version("en_core_web_trf"),
        "files_sha256": _hash_model_directory(destination),
    }


def main() -> int:
    args = parse_args()
    models_dir = Path(args.models_dir).resolve()
    lock_path = Path(args.lock_path).resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    models = _download_huggingface_models(models_dir)
    # Keep the independent spaCy vote before the PubMed-only veto in the lock.
    models.insert(2, _freeze_spacy_model(models_dir))
    payload = {
        "protocol": SEMANTIC_RESOLVER_PROTOCOL,
        "execution_mode": "precision_cascade",
        "primary_model_role": "gliner2_large",
        "audit_only_model_roles": ["gliner2_base", "spacy_transformer"],
        "biomedical_candidate_only": True,
        "schema_sha256": SEMANTIC_SCHEMA_SHA256,
        "local_files_only": True,
        "models": models,
    }
    with lock_path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(
            payload,
            handle,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
    print(f"[done] wrote {lock_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
