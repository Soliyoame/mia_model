"""Configuration and source-pool controls for the V25 successor protocol."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.utils.hash import sha256_file, sha256_obj, sha256_text
from src.utils.io import load_yaml, write_json, write_jsonl_atomic


DATASETS = ("nfcorpus", "scidocs", "trec-covid")
GROUPS = ("KB_Member", "True_Non_Member")
REQUIRED_PROTOCOL = "pcv-mia-v25"
REQUIRED_RETRIEVER_REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"


def load_v25_config(project_root: str | Path, config_path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the V25 config without reading any membership labels."""

    root = Path(project_root).resolve()
    path = Path(config_path) if config_path is not None else root / "configs/restoration_first_v25.yaml"
    if not path.is_absolute():
        path = root / path
    config = load_yaml(path)
    validate_v25_config(config)
    config["_config_path"] = str(path.resolve())
    return config


def validate_v25_config(config: dict[str, Any]) -> None:
    if config.get("protocol_version") != REQUIRED_PROTOCOL:
        raise ValueError("v25_protocol_version_required")
    if tuple(config.get("datasets") or ()) != DATASETS:
        raise ValueError("v25_dataset_order_drift")
    runtime = config.get("runtime") or {}
    retriever = runtime.get("retrieval") or {}
    if runtime.get("victim_profile") != "gemma2_2b_server":
        raise ValueError("v25_victim_profile_must_match_menta_cell")
    if runtime.get("concrete_model") != "gemma-2-2b-it-bf16":
        raise ValueError("v25_victim_model_must_match_menta_cell")
    if retriever.get("backend") != "dense":
        raise ValueError("v25_dense_retriever_required")
    if retriever.get("retriever_id") != "BAAI/bge-base-en-v1.5":
        raise ValueError("v25_retriever_must_match_menta_cell")
    if retriever.get("revision") != REQUIRED_RETRIEVER_REVISION:
        raise ValueError("v25_retriever_revision_must_match_menta_cell")
    if retriever.get("chunk_size") != 128 or retriever.get("chunk_overlap") != 32:
        raise ValueError("v25_chunking_must_match_menta_cell")
    if retriever.get("top_k") != 5:
        raise ValueError("v25_top_k_must_match_menta_cell")
    generation = runtime.get("generation") or {}
    if generation.get("temperature") != 0 or generation.get("max_tokens") != 512:
        raise ValueError("v25_generation_must_match_menta_cell")
    protocol = config.get("query_protocol") or {}
    if protocol.get("initial_queries") != 3 or protocol.get("followup_max") != 3:
        raise ValueError("v25_query_budget_drift")
    if protocol.get("total_max") != 6:
        raise ValueError("v25_total_query_budget_drift")
    scoring = config.get("scoring") or {}
    if scoring.get("primary") != "S_chain":
        raise ValueError("v25_primary_score_must_be_s_chain")
    if scoring.get("statistical_unit") != "source_document":
        raise ValueError("v25_source_level_statistics_required")
    split = config.get("split") or {}
    counts = split.get("counts") or {}
    if counts != {"KB_Member": 1000, "True_Non_Member": 1000, "Reserve": 250}:
        raise ValueError("v25_split_counts_drift")


def source_pool_paths(project_root: str | Path, config: dict[str, Any], dataset: str) -> dict[str, Path]:
    root = Path(project_root).resolve()
    paths = config["source_pool"]["paths"]
    return {
        name: root / str(template).format(dataset=dataset)
        for name, template in paths.items()
    }


def source_pool_input_hashes(project_root: str | Path, config: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {str(Path(config["_config_path"]).relative_to(Path(project_root).resolve())): sha256_file(config["_config_path"])}
    for dataset in DATASETS:
        for name, path in source_pool_paths(project_root, config, dataset).items():
            if not path.is_file():
                raise FileNotFoundError(f"v25_source_pool_input_missing:{path}")
            hashes[str(path.relative_to(Path(project_root).resolve()))] = sha256_file(path)
    return hashes


def _development_exclusions(paths: dict[str, Path]) -> set[str]:
    payload = json.loads(paths["development_exclusions"].read_text(encoding="utf-8"))
    exclusions = payload.get("exclusions")
    if not isinstance(exclusions, list):
        raise ValueError("v25_development_exclusions_schema")
    return {str(row["source_key"]) for row in exclusions if row.get("source_key")}


def _ordered_source_keys(paths: dict[str, Path]) -> list[str]:
    payload = json.loads(paths["source_order"].read_text(encoding="utf-8"))
    rows = payload.get("source_order")
    if not isinstance(rows, list) or len(set(rows)) != len(rows):
        raise ValueError("v25_source_order_schema")
    return [str(value) for value in rows]


def _pool_rows(paths: dict[str, Path], source_keys: list[str]) -> dict[str, dict[str, Any]]:
    connection = sqlite3.connect(paths["database"])
    try:
        rows = connection.execute(
            "SELECT source_key, dataset, document_id, source_order_rank, source_hash, "
            "normalized_text_hash, full_text FROM sources"
        ).fetchall()
    finally:
        connection.close()
    by_key = {
        str(row[0]): {
            "source_key": str(row[0]), "dataset": str(row[1]), "document_id": str(row[2]),
            "source_order_rank": str(row[3]), "source_hash": str(row[4]),
            "normalized_text_hash": str(row[5]), "full_text": str(row[6]),
        }
        for row in rows
    }
    if set(source_keys) - set(by_key):
        raise ValueError("v25_source_order_database_mismatch")
    for row in by_key.values():
        if sha256_text(row["full_text"]) != row["source_hash"]:
            raise ValueError(f"v25_source_hash_drift:{row['source_key']}")
    return by_key


def build_source_exclusive_split(
    project_root: str | Path,
    config: dict[str, Any],
    output_dir: str | Path,
    pair_quotas: dict[str, int] | None = None,
    excluded_source_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Select matched pairs from source order and assign roles without prior labels."""

    root = Path(project_root).resolve()
    out = Path(output_dir).resolve()
    quotas = pair_quotas or config["development"]["pair_quotas"]
    if set(quotas) != set(DATASETS) or any(int(value) < 1 for value in quotas.values()):
        raise ValueError("v25_pair_quotas_invalid")
    pairs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    excluded_source_keys = set(excluded_source_keys or ())
    for dataset in DATASETS:
        paths = source_pool_paths(root, config, dataset)
        ordered = _ordered_source_keys(paths)
        excluded = _development_exclusions(paths)
        pool = _pool_rows(paths, ordered)
        candidates = [
            pool[key]
            for key in ordered
            if key not in excluded and key not in excluded_source_keys
        ]
        required = int(quotas[dataset]) * 2
        if len(candidates) < required:
            raise ValueError(f"v25_source_capacity:{dataset}:{len(candidates)}<{required}")
        chosen = candidates[:required]
        for pair_index in range(int(quotas[dataset])):
            pair_sources: list[dict[str, Any]] = []
            for group, source in zip(GROUPS, chosen[pair_index * 2:pair_index * 2 + 2]):
                selected = {key: value for key, value in source.items() if key != "full_text"}
                selected["group"] = group
                selected["selection_basis"] = "source_pool_order_without_prior_membership_labels"
                pair_sources.append(selected)
                rows.append(selected)
            pairs.append({
                "dataset": dataset,
                "pair_index": len([pair for pair in pairs if pair["dataset"] == dataset]) + 1,
                "sources": pair_sources,
            })
    if len(rows) != sum(int(value) * 2 for value in quotas.values()):
        raise ValueError("v25_source_split_count_drift")
    if len({row["source_key"] for row in rows}) != len(rows):
        raise ValueError("v25_source_split_source_collision")
    if {row["group"] for row in rows} != set(GROUPS):
        raise ValueError("v25_source_split_group_drift")
    plan = {
        "kind": "v25_source_exclusive_development_split",
        "status": "selected_before_luna_or_victim_calls",
        "development_only": True,
        "source_unit": "source_document",
        "membership_labels_read": False,
        "selection_inputs": "source_order_and_source_pool_hashes_only",
        "excluded_source_keys_sha256": sha256_obj(sorted(excluded_source_keys)),
        "input_sha256": source_pool_input_hashes(root, config),
        "pair_quotas": {dataset: int(quotas[dataset]) for dataset in DATASETS},
        "pairs": pairs,
        "source_count": len(rows),
        "source_keys_sha256": sha256_obj([row["source_key"] for row in rows]),
    }
    out.mkdir(parents=True, exist_ok=True)
    write_json(plan, out / "source_split.json")
    write_jsonl_atomic(rows, out / "source_manifest.jsonl")
    return plan


def read_source_text(project_root: str | Path, config: dict[str, Any], source: dict[str, Any]) -> str:
    paths = source_pool_paths(project_root, config, str(source["dataset"]))
    connection = sqlite3.connect(paths["database"])
    try:
        row = connection.execute(
            "SELECT source_hash, full_text FROM sources WHERE source_key = ?",
            (str(source["source_key"]),),
        ).fetchone()
    finally:
        connection.close()
    if row is None or str(row[0]) != str(source["source_hash"]):
        raise ValueError(f"v25_source_identity_drift:{source['source_key']}")
    text = str(row[1])
    if sha256_text(text) != str(source["source_hash"]):
        raise ValueError(f"v25_source_text_hash_drift:{source['source_key']}")
    return text
