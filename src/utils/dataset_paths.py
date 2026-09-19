"""Resolve dataset-specific artifact directories without reusing legacy outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import resolve_path


def resolve_dataset_dir(config: dict[str, Any], path_key: str, dataset: str) -> Path:
    """Resolve a final dataset directory, honoring an optional explicit override."""

    dataset_cfg = config.get("dataset_paths", {}).get(dataset, {})
    override = dataset_cfg.get(path_key) if isinstance(dataset_cfg, dict) else None
    if override:
        return resolve_path(str(override))
    return resolve_path(config["paths"][path_key]) / dataset


def resolve_processed_path(config: dict[str, Any], dataset: str) -> Path:
    """Resolve a dataset's Step 01 JSONL, honoring an explicit v2 input path."""

    dataset_cfg = config.get("datasets", {}).get(dataset, {})
    override = dataset_cfg.get("processed_path") if isinstance(dataset_cfg, dict) else None
    if override:
        return resolve_path(str(override))
    return resolve_path(config["paths"]["processed_dir"]) / f"{dataset}.jsonl"
