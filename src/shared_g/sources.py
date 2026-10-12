"""只读原文池、固定无标签候选顺序与合格后的成员划分。"""

from __future__ import annotations

import random
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any

from src.llm.factory import llm_profile_identity
from src.utils.hash import sha256_file, sha256_text

from .artifacts import ArtifactStore, code_hashes, read_json, read_rows, unique_map, write_once
from .config import ExperimentConfig
from .types import CandidateRecord, GROUPS, SourceRecord


def identities(value: Any) -> tuple[set[str], set[str]]:
    keys: set[str] = set()
    hashes: set[str] = set()
    if isinstance(value, dict):
        if value.get("source_key"):
            keys.add(str(value["source_key"]))
        hashes.update(str(value[field]) for field in ("source_hash", "normalized_text_hash") if value.get(field))
        for child in value.values():
            child_keys, child_hashes = identities(child)
            keys.update(child_keys)
            hashes.update(child_hashes)
    elif isinstance(value, list):
        for child in value:
            child_keys, child_hashes = identities(child)
            keys.update(child_keys)
            hashes.update(child_hashes)
    return keys, hashes


def unused_preparation_files(config: ExperimentConfig) -> list[Path]:
    files: list[Path] = []
    for name in config.data["source_selection"].get("unused_preparations", []):
        directory = config.resolve(name)
        expected = {"run_config.json", "source_manifest.jsonl", "index_manifest.jsonl"}
        present = {path.name for path in directory.iterdir()}
        if (directory == config.output or present != expected
                or read_json(directory / "run_config.json").get("status") != "prepared_before_construction"):
            raise RuntimeError("unused_preparation_has_execution_or_unknown_artifacts")
        files.extend(directory / filename for filename in sorted(expected))
    return files


def history_identity_files(config: ExperimentConfig) -> list[Path]:
    selection = config.data["source_selection"]
    unused_preparation_files(config)
    unused = [config.resolve(name) for name in selection.get("unused_preparations", [])]
    files = {config.resolve(name) for name in selection["explicit_development_inputs"]}
    for directory in selection["history_roots"]:
        for name in selection["identity_filenames"]:
            files.update(path for path in config.resolve(directory).rglob(name)
                         if not path.is_relative_to(config.output)
                         and not any(path.is_relative_to(directory) for directory in unused))
    files.update(config.pool_paths(dataset)["development_exclusions"] for dataset in config.datasets)
    if any(not path.is_file() for path in files):
        raise RuntimeError("history_identity_input_missing")
    return sorted(files)


def load_pool(config: ExperimentConfig, dataset: str) -> list[dict[str, Any]]:
    paths = config.pool_paths(dataset)
    fields = ("source_key", "dataset", "document_id", "source_order_rank", "source_hash", "normalized_text_hash", "full_text")
    with closing(sqlite3.connect(paths["database"].as_uri() + "?mode=ro", uri=True)) as connection:
        rows = [dict(zip(fields, map(str, row))) for row in connection.execute(
            "SELECT source_key,dataset,document_id,source_order_rank,source_hash,normalized_text_hash,full_text FROM sources")]
    by_key = unique_map(rows, "source_key")
    order = read_json(paths["source_order"])["source_order"]
    if len(set(order)) != len(order) or set(order) != set(by_key):
        raise RuntimeError("source_order_identity_drift")
    for row in rows:
        if row["dataset"] != dataset or sha256_text(row["full_text"]) != row["source_hash"]:
            raise RuntimeError("raw_source_identity_drift")
    return [by_key[key] for key in order]


def read_source_text(config: ExperimentConfig, source: CandidateRecord) -> str:
    path = config.pool_paths(source["dataset"])["database"]
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT source_hash,normalized_text_hash,full_text FROM sources WHERE source_key=?",
            (source["source_key"],)).fetchone()
    if (row is None or str(row[0]) != source["source_hash"]
            or str(row[1]) != source["normalized_text_hash"] or sha256_text(str(row[2])) != source["source_hash"]):
        raise RuntimeError("source_text_hash_drift")
    return str(row[2])


def order_blind_candidates(pool: list[dict[str, Any]], seed: int, minimum_words: int,
                           excluded_keys: set[str], excluded_hashes: set[str]) -> list[CandidateRecord]:
    candidates = [row for row in pool if row["source_key"] not in excluded_keys
                  and not {row["source_hash"], row["normalized_text_hash"]} & excluded_hashes
                  and len(row["full_text"].split()) >= minimum_words]
    random.Random(seed).shuffle(candidates)
    selected: list[dict[str, Any]] = []
    seen_hashes = set(excluded_hashes)
    for row in candidates:
        hashes = {row["source_hash"], row["normalized_text_hash"]}
        if hashes & seen_hashes:
            continue
        selected.append({key: row[key] for key in ("source_key", "dataset", "document_id",
                        "source_order_rank", "source_hash", "normalized_text_hash")})
        selected[-1]["candidate_rank"] = len(selected) - 1
        seen_hashes.update(hashes)
    return selected


def select_qualified_sources(config: ExperimentConfig, candidates: list[CandidateRecord],
                             accepted: set[str]) -> list[SourceRecord]:
    if accepted - set(unique_map(candidates, "source_key")):
        raise RuntimeError("qualified_source_outside_candidate_pool")
    sources: list[SourceRecord] = []
    for offset, dataset in enumerate(config.datasets):
        selected = [dict(row) for row in candidates if row["dataset"] == dataset and row["source_key"] in accepted]
        if len(selected) != sum(config.data["source_selection"]["counts"][dataset].values()):
            raise RuntimeError(f"qualified_source_quota_not_exact:{dataset}")
        random.Random(config.data["seed"] + offset).shuffle(selected)
        for index, row in enumerate(selected):
            row["group"] = GROUPS[index % 2]
        sources.extend(selected)
    validate_isolation(sources, [row for row in sources if row["group"] == "KB_Member"])
    return sources


def validate_isolation(sources: list[SourceRecord], index_rows: list[SourceRecord]) -> None:
    by_key = unique_map(sources, "source_key")
    index = unique_map(index_rows, "source_key")
    members = {key for key, row in by_key.items() if row["group"] == "KB_Member"}
    if set(index) != members:
        raise RuntimeError("index_must_equal_designated_members")
    for row in index_rows:
        if row != by_key[row["source_key"]] or row["group"] != "KB_Member":
            raise RuntimeError("index_source_identity_drift")
    seen: set[str] = set()
    for row in sources:
        if row["group"] not in GROUPS:
            raise RuntimeError("unexpected_membership_group")
        hashes = {row["source_hash"], row["normalized_text_hash"]}
        if hashes & seen:
            raise RuntimeError("source_text_overlap")
        seen.update(hashes)


def prepare_reused_inputs(config: ExperimentConfig, store: ArtifactStore, dry_run: bool) -> dict[str, Any]:
    """跨Generator只读复用已固定输入，不复制旧回答、标签或评分。"""
    from .retrieval import validate_retrieval

    parent_path = config.resolve(config.data["reused_inputs"]["source_dir"]) / "run_config.json"
    parent = read_json(parent_path)
    if parent.get("status") not in {"frozen_before_retrieval_and_victim", "scoring_corrected_after_initial"}:
        raise RuntimeError("reused_queries_must_be_frozen")
    original = parent["config"]
    if (original["datasets"] != list(config.datasets) or original["seed"] != config.data["seed"]
            or original["query_protocol"] != config.data["query_protocol"]
            or original["source_selection"]["counts"] != config.data["source_selection"]["counts"]
            or any(original["runtime"][name] != config.data["runtime"][name]
                   for name in ("retrieval", "rag_prompt", "rag_prompt_version"))):
        raise RuntimeError("reused_input_configuration_drift")
    bound = {**parent["artifacts"], **parent.get("frozen_artifacts", {})}
    names = ("source_manifest.jsonl", "index_manifest.jsonl", "query_plan.jsonl")
    for name in names:
        if name not in bound or sha256_file(store.path(name)) != bound[name]:
            raise RuntimeError(f"reused_frozen_input_drift:{name}")
    sources, members = read_rows(store.path(names[0])), read_rows(store.path(names[1]))
    validate_isolation(sources, members)
    for dataset in config.datasets:
        if dict(Counter(row["group"] for row in sources if row["dataset"] == dataset)) != config.data["source_selection"]["counts"][dataset]:
            raise RuntimeError("reused_source_count_drift")
        validate_retrieval(config, store, dataset)
    profiles = config.profiles()
    if profiles["victim"].get("model_version") != config.data["runtime"]["generator_version"]:
        raise RuntimeError("effective_generator_version_drift")
    summary = {"stage": "prepare", "status": "dry_run" if dry_run else "frozen_reused_inputs",
               "candidate_count": len(sources), "source_count": len(sources), "target_source_count": len(sources),
               "index_source_count": len(members), "queries": len(read_rows(store.path("query_plan.jsonl"))),
               "new_victim_calls": 0, "query_identity_reused": True}
    if dry_run:
        return summary
    inputs = [parent_path, *(store.path(name) for name in names),
              *(store.path("retrieval.jsonl", dataset) for dataset in config.datasets)]
    run = {**summary, "status": "frozen_before_retrieval_and_victim", "run_role": "formal",
           "experiment_id": config.data["experiment_id"], "config": config.data,
           "config_sha256": sha256_file(config.path), "code_hashes": code_hashes(config),
           "code_commit": store.git_commit(), "uncommitted_code_bound_by_sha256": True,
           "profiles_sha256": sha256_file(config.resolve(config.data["runtime"]["llm_profiles_path"])),
           "model_profiles": {role: llm_profile_identity(profile) for role, profile in profiles.items()},
           "input_hashes": {path.relative_to(config.root).as_posix(): sha256_file(path) for path in inputs},
           "artifacts": {name: sha256_file(store.path(name)) for name in names},
           "source_unit": "source_document", "replacement_after_freeze": False}
    write_once(store.path("run_config.json"), run)
    return summary


def prepare(config: ExperimentConfig, store: ArtifactStore, dry_run: bool = False) -> dict[str, Any]:
    if store.path("run_config.json").exists():
        run = store.validate()
        return {"stage": "prepare", "status": "already_prepared", "candidate_count": run["candidate_count"],
                "target_source_count": run["target_source_count"], "source_count": run["source_count"]}
    if not dry_run and config.output.exists() and any(config.output.iterdir()):
        raise RuntimeError("refuse_overwrite_partial_prepare")
    if config.data.get("reused_inputs"):
        return prepare_reused_inputs(config, store, dry_run)
    files = history_identity_files(config)
    keys: set[str] = set()
    hashes: set[str] = set()
    for path in files:
        found_keys, found_hashes = identities(read_rows(path) if path.suffix == ".jsonl" else read_json(path))
        keys.update(found_keys)
        hashes.update(found_hashes)
    pools = {dataset: load_pool(config, dataset) for dataset in config.datasets}
    hashes.update(row[field] for rows in pools.values() for row in rows if row["source_key"] in keys
                  for field in ("source_hash", "normalized_text_hash"))
    reuse_files = [config.resolve(name) for name in config.data["source_selection"]["prior_v24_identity_inputs"]]
    reused_keys: set[str] = set()
    for path in reuse_files:
        reused_keys.update(identities(read_rows(path) if path.suffix == ".jsonl" else read_json(path))[0])
    candidates: list[dict[str, Any]] = []
    for offset, dataset in enumerate(config.datasets):
        counts = config.data["source_selection"]["counts"][dataset]
        # 复用授权仅作用于原文身份；历史标签和实验结果不参与候选排序。
        selected = order_blind_candidates(pools[dataset], config.data["seed"] + offset,
                                          config.data["source_selection"]["minimum_words"], set(),
                                          {row[field] for row in candidates
                                           for field in ("source_hash", "normalized_text_hash")})
        for row in selected:
            row["history_raw_document_reused"] = (row["source_key"] in keys
                                                  or bool({row["source_hash"], row["normalized_text_hash"]} & hashes)
                                                  or row["source_key"] in reused_keys)
            row["prior_v24_raw_document_reused"] = row["source_key"] in reused_keys
        if len(selected) < sum(counts.values()):
            raise RuntimeError(f"insufficient_source_capacity:{dataset}")
        candidates.extend(selected)
    summary = {"stage": "prepare", "status": "dry_run" if dry_run else "prepared",
               "source_count": 0, "index_source_count": 0, "candidate_count": len(candidates),
               "target_source_count": sum(sum(counts.values()) for counts in config.data["source_selection"]["counts"].values()),
               "candidate_dataset_counts": dict(Counter(row["dataset"] for row in candidates)),
               "prior_v24_candidate_raw_document_reuse": {dataset: sum(row["source_key"] in reused_keys for row in candidates
                                                           if row["dataset"] == dataset) for dataset in config.datasets}}
    if dry_run:
        return summary
    inputs = {*files, *reuse_files, *unused_preparation_files(config),
              *(path for dataset in config.datasets for path in config.pool_paths(dataset).values())}
    run = {**summary, "status": "candidate_pool_prepared_before_membership", "run_role": "formal",
           "experiment_id": config.data["experiment_id"], "config": config.data,
           "config_sha256": sha256_file(config.path), "code_hashes": code_hashes(config),
           "code_commit": store.git_commit(), "uncommitted_code_bound_by_sha256": True,
           "profiles_sha256": sha256_file(config.resolve(config.data["runtime"]["llm_profiles_path"])),
           "model_profiles": {role: llm_profile_identity(profile) for role, profile in config.profiles().items()},
           "input_hashes": {str(path.relative_to(config.root)).replace("\\", "/"): sha256_file(path) for path in sorted(inputs)},
           "source_unit": "source_document", "eligibility_before_membership": True,
           "replacement_after_freeze": False,
           "prior_v24_reuse_identity_scope": "configured_identity_inputs_only"}
    write_once(store.path("candidate_manifest.jsonl"), candidates)
    run["artifacts"] = {"candidate_manifest.jsonl": sha256_file(store.path("candidate_manifest.jsonl"))}
    write_once(store.path("run_config.json"), run)
    return summary
