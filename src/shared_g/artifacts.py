"""简单产物读写与恢复检查；不承载科研判定规则。"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from src.llm.factory import llm_profile_identity
from src.utils.hash import sha256_file, sha256_obj
from src.utils.io import read_jsonl, write_jsonl_atomic

from .config import ExperimentConfig


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict[str, Any]]:
    return list(read_jsonl(path)) if path.is_file() else []


def unique_map(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result = {str(row[key]): row for row in rows}
    if len(result) != len(rows):
        raise RuntimeError(f"duplicate_record:{key}")
    return result


def retry_local_write(action: Callable[[], Any]) -> Any:
    for attempt in range(3):
        try:
            return action()
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.2)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    retry_local_write(lambda: temporary.write_text(text, encoding="utf-8", newline="\n"))
    retry_local_write(lambda: temporary.replace(path))


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    retry_local_write(lambda: write_jsonl_atomic(rows, path))


def write_once(path: Path, value: dict[str, Any] | list[dict[str, Any]]) -> None:
    if path.exists():
        previous = read_rows(path) if isinstance(value, list) else read_json(path)
        if previous != value:
            raise RuntimeError(f"refuse_artifact_overwrite:{path.name}")
        return
    if isinstance(value, list):
        write_rows(path, value)
    else:
        write_json_atomic(path, value)


def append_request(path: Path, row: dict[str, Any]) -> None:
    """调用前后各写一条原始记录，避免逐次重写大型响应文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    # 只重试尚未开始写入的打开操作；写入途中失败后保持原件并暂停。
    handle = retry_local_write(lambda: path.open("a", encoding="utf-8", newline="\n"))
    with handle:
        handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def request_records(path: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in read_rows(path):
        key = row["request_key"]
        previous = latest.get(key)
        if previous is None:
            if row["status"] != "attempt_started":
                raise RuntimeError("request_start_missing")
        elif previous["status"] != "attempt_started" or row["status"] == "attempt_started":
            raise RuntimeError("duplicate_request_or_terminal_record")
        elif any(previous.get(field) != row.get(field)
                 for field in ("query_id", "source_key", "source_hash", "attempt", "prompt_sha256",
                               "retrieval_sha256", "profile_identity", "source_bindings", "source_aliases")):
            raise RuntimeError("request_identity_drift")
        latest[key] = row
    return list(latest.values())


def code_hashes(config: ExperimentConfig) -> dict[str, str]:
    paths = list(Path(__file__).parent.glob("*.py"))
    paths += [config.root / value for value in (
        "scripts/104_run_v25_shared_g_formal.py", "src/evaluation/metrics.py",
        "src/llm/factory.py", "src/llm/openai_compatible.py", "src/llm/victim_client.py",
        "src/llm/response_validation.py", "src/rag/embeddings.py", "src/rag/index_builder.py",
        "src/utils/io.py", "src/utils/hash.py")]
    return {str(path.relative_to(config.root)).replace("\\", "/"): sha256_file(path)
            for path in sorted(paths)}


class ArtifactStore:
    def __init__(self, config: ExperimentConfig):
        self.config = config

    def path(self, name: str, dataset: str | None = None) -> Path:
        if dataset is not None and dataset not in self.config.datasets:
            raise ValueError("unknown_dataset")
        reused = self.config.data.get("reused_inputs")
        if reused:
            if dataset is None and name in {"source_manifest.jsonl", "index_manifest.jsonl", "query_plan.jsonl"}:
                return self.config.resolve(reused["source_dir"]) / name
            if dataset is not None and name == "retrieval.jsonl":
                return self.config.resolve(reused["retrieval_dirs"][dataset]) / dataset / name
        return self.config.output / dataset / name if dataset else self.config.output / name

    def validate(self, frozen: bool = False) -> dict[str, Any]:
        from .sources import unused_preparation_files

        unused_preparation_files(self.config)
        if self.config.output.exists() and any(self.config.output.rglob("*.tmp")):
            raise RuntimeError("partial_write_preserved_manual_recovery_required")
        run = read_json(self.path("run_config.json"))
        if run["config_sha256"] != sha256_file(self.config.path) or run["code_hashes"] != code_hashes(self.config):
            raise RuntimeError("code_or_config_drift")
        profile_path = self.config.resolve(self.config.data["runtime"]["llm_profiles_path"])
        if run["profiles_sha256"] != sha256_file(profile_path):
            raise RuntimeError("model_profiles_file_drift")
        identities = {role: llm_profile_identity(profile) for role, profile in self.config.profiles().items()}
        if run["model_profiles"] != identities:
            raise RuntimeError("effective_model_profile_drift")
        for name, digest in run["input_hashes"].items():
            if sha256_file(self.config.resolve(name)) != digest:
                raise RuntimeError(f"input_drift:{name}")
        for name, digest in {**run["artifacts"], **run.get("frozen_artifacts", {})}.items():
            if sha256_file(self.path(name)) != digest:
                raise RuntimeError(f"artifact_drift:{name}")
        query_frozen = run.get("status") == "frozen_before_retrieval_and_victim"
        corrected = (run.get("status") == "scoring_corrected_after_initial"
                     and bool(run.get("scoring_correction")) and bool(run.get("frozen_artifacts")))
        if frozen and not (query_frozen or corrected):
            raise RuntimeError("query_freeze_required")
        return run

    def git_commit(self) -> str:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.config.root, text=True).strip()

    def index_identity(self, dataset: str) -> str:
        rows = read_rows(self.path("index_manifest.jsonl"))
        return sha256_obj([(r["source_key"], r["source_hash"]) for r in rows if r["dataset"] == dataset])


def read_response_adjudications(store: ArtifactStore) -> dict[str, dict[str, Any]]:
    """读取显式启用的回答复核；缺失或身份变化时拒绝静默退回自动标签。"""
    from src.utils.hash import sha256_text
    from .scoring import answer_judgment

    filename = store.config.data["answer_policy"].get("response_adjudications")
    if filename is None:
        return {}
    run = read_json(store.path("run_config.json"))
    path = store.path(filename)
    if (not path.is_file() or not run.get("scoring_correction")
            or sha256_file(path) != run.get("frozen_artifacts", {}).get(filename)):
        raise RuntimeError("response_adjudication_not_bound")
    packet = read_json(path)
    if (packet.get("reviewer_type") != "assistant_post_response"
            or packet.get("independent_human_annotation") is not False
            or packet.get("scope") != "reviewed_responses_only"
            or not isinstance(packet.get("decisions"), list) or not packet["decisions"]):
        raise RuntimeError("response_adjudication_provenance_invalid")
    decisions = unique_map(packet["decisions"], "query_id")
    queries = unique_map(read_rows(store.path("query_plan.jsonl")), "query_id")
    sources = unique_map(read_rows(store.path("source_manifest.jsonl")), "source_key")
    responses = unique_map([row for dataset in store.config.datasets
                            for name in ("initial_responses.jsonl", "followup_responses.jsonl")
                            for row in request_records(store.path(name, dataset))], "query_id")
    for key, decision in decisions.items():
        query, response = queries.get(key), responses.get(key)
        if query is None or response is None:
            raise RuntimeError("response_adjudication_target_missing")
        source = sources.get(query["source_key"])
        if (source is None or decision.get("source_hash") != source["source_hash"]
                or response.get("response_sha256") != sha256_text(response.get("response", ""))):
            raise RuntimeError("response_adjudication_source_or_response_drift")
        value = answer_judgment(response, query, matcher=store.config.data["answer_policy"]["matcher"],
                                adjudications=decisions)
        if value["label"] == "invalid":
            raise RuntimeError("response_adjudication_invalid_response")
    return decisions
