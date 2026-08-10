"""运行上下文工具:为每次输出生成时间戳 run_id 与归档目录。

中文说明
========
PCV-MIA 的产物原本都是固定文件名、--force 直接覆盖,没法回看"哪次、什么时候"跑的。
本模块提供一个轻量的 run 标识与归档帮助:
    - current_run_id():  本次运行的唯一标识。优先用环境变量 PCV_RUN_ID(便于一条
      流水线的多个步骤共享同一个 id);没有就用本地时间现生成 YYYYMMDD-HHMMSS。
    - new_run_id(label): 现生成一个全新 run_id(不读环境变量),供流水线启动时盖"开始
      时间"戳并 export 给所有子步骤共享;可选人类标签拼成 {时间戳}_{标签}。
    - local_timestamp(): 人类可读的本地时间字符串(写进总表/图标题)。
    - run_dir(dataset, run_id): 该次运行的归档目录 outputs/runs/{dataset}/{run_id}/(自动建)。
    - index_path(dataset):      历次运行总表 outputs/runs/{dataset}/index.jsonl 的路径。
    - append_index(dataset, record): 往总表追加一行(历次运行速查表)。
    - stage_output_dirs():      全部阶段产物目录的单一事实源(归档时遍历它)。
    - archive_run(dataset, run_id): 把本次实验各阶段产物拷进 run 文件夹,自包含存档。
    - write_run_manifest(...):   往 run 文件夹写 run_manifest.json(配置/参数/git/耗时)。
    - git_snapshot():           采集 {commit, branch, dirty} 快照(git 不可用不报错)。
    - read_scale():             读 data_config.yaml 的 split.scale(写进 manifest/总表)。
这样每次结果都能按时间归档、不再互相覆盖,并有一张总表速查历次。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..llm.response_validation import response_record_is_success
from .env import env_str
from .hash import sha256_file, sha256_obj
from .io import ensure_dir, load_yaml, read_json, read_jsonl, resolve_path, write_json, write_jsonl


RUN_STATUSES: tuple[str, ...] = (
    "scratch",
    "candidate",
    "canonical",
    "invalid",
    "superseded",
    "legacy_feasibility",
)

P0_PROTOCOL: dict[str, Any] = {
    "protocol_version": "pcv-mia-v20",
    "method_version": "pcv-rag-only-source-v20",
    "threat_model_version": "strict-blackbox-v1",
    "metrics_version": "source-conformal-bootstrap-v2",
    "dataset_status": "pre_response_frozen_canonical",
    "reserve_role": "retriever_dev_and_conformal",
    "conformal_source_count": 245,
    "conformal_alphas": [0.01, 0.05],
    "execution": "source_block_interleaved",
    "calibration_scope": "post_retriever_frozen_nonmember_calibration",
    "retriever_selection_used_reserve_recall": True,
    "retriever_selection_used_attack_scores": False,
    "pilot_reserve_excluded_from_calibration": True,
    "method": "rag_only_paired_counterfactual_verification",
    "membership_unit": "dataset_specific_source",
    "membership_units": {
        "edgar": "filing",
        "enron": "complete_email",
        "pubmed": "pmcid_article",
    },
    "retrieval_unit": "chunk",
    "evaluation_unit": "source",
    "pairs_per_source": 3,
    "queries_per_source_per_cell": 6,
    "retrievers": ["dense", "bm25", "hybrid"],
    "dense_retriever_model": "BAAI/bge-base-en-v1.5",
    "reranker_model": "BAAI/bge-reranker-base",
    "generator_families": ["gemini", "qwen", "gpt", "llama"],
    "primary_generator_family": "llama",
    "primary_generator_model": "meta/llama-3.1-70b-instruct",
    "baseline_method_policy": {
        "full_generator": "meta/llama-3.1-70b-instruct",
        "full_methods": ["RAG-MIA", "S2MIA", "MBA", "IA", "DCMI", "MEntA"],
        "extension_methods": [],
    },
    "defense_representative_cells": [
        {"dataset": dataset, "victim_model": "meta/llama-3.1-70b-instruct", "retriever_backend": "dense"}
        for dataset in ("edgar", "enron", "pubmed")
    ],
    "threat_model": "candidate-known,response-only,non-adaptive,fixed-budget,strict-black-box",
    "main_score": "mean_source_pvs_rag",
    "main_metric": "source_level_auc",
    "calibration": "reserve_conformal",
}


def canonical_baseline_methods(victim_model: str) -> tuple[str, ...] | None:
    """Return the preregistered baseline set for a canonical generator."""

    policy = P0_PROTOCOL["baseline_method_policy"]
    model = str(victim_model or "").strip().casefold()
    family_tokens = ("gemini", "qwen", "gpt", "llama")
    if not any(token in model for token in family_tokens):
        return None
    key = "full_methods" if model == str(policy["full_generator"]).casefold() else "extension_methods"
    return tuple(str(method) for method in policy[key])


def canonical_defense_required(dataset: str, victim_model: str, retriever_backend: str) -> bool:
    """Whether this main cell is one of the three preregistered defense cells."""

    identity = (str(dataset), str(victim_model).casefold(), str(retriever_backend))
    return any(
        identity
        == (
            str(cell["dataset"]),
            str(cell["victim_model"]).casefold(),
            str(cell["retriever_backend"]),
        )
        for cell in P0_PROTOCOL["defense_representative_cells"]
    )

CANONICAL_SCALE = "formal"
CANONICAL_SPLIT_SEED = 42
CANONICAL_SELECTION_RULE = "first_preregistered_run_passing_all_gates"
CANONICAL_RUN_ROLES: tuple[str, ...] = ("main", "matched_control")


def current_run_id() -> str:
    """返回本次运行的 run_id。

    优先读环境变量 PCV_RUN_ID(便于一条流水线的多个步骤共享同一 id);
    未设置时用本地时间现生成 YYYYMMDD-HHMMSS。
    """
    env = os.environ.get("PCV_RUN_ID")
    if env and env.strip():
        return env.strip()
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def local_timestamp() -> str:
    """返回人类可读的本地时间字符串(写进总表与图标题)。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def model_slug(value: str | None) -> str:
    """Convert a model identifier such as ``org/model`` into one safe directory name."""

    raw = str(value or "").strip()
    if not raw:
        return "unspecified"
    raw = raw.split("/")[-1]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return slug or "unspecified"


def victim_model_slug() -> str:
    """受害者模型的文件夹安全 slug:读环境变量 PCV_VICTIM_MODEL;未设为 'unspecified'。

    形如 'qwen/qwen3.5-397b-a17b' 先去掉 org 前缀取最后一段,再把非法字符折叠成连字符,
    得到 'qwen3.5-397b-a17b'。模型相关产物据此按 {数据集}/{模型}/ 分目录,换模型不互相覆盖。
    """
    return model_slug(env_str("PCV_VICTIM_MODEL", ""))


def model_scoped_dir(stage_base: str | Path, dataset: str, *, model: str | None = None) -> Path:
    """模型相关阶段的目录 {stage_base}/{dataset}/{model}(不创建;写方自行 ensure_dir)。

    参数:
        stage_base: 阶段基目录(如 'outputs/scores' 或 config 里的 scores_dir)。
        dataset:    数据集名。
        model:      模型 slug;缺省用当前 victim_model_slug()。
    """
    return resolve_path(stage_base) / dataset / (
        model_slug(model) if model is not None else victim_model_slug()
    )


def experiment_scoped_dir(
    stage_base: str | Path,
    dataset: str,
    *,
    generator_family: str,
    concrete_model: str,
    retriever_id: str,
) -> Path:
    """v20 正式产物目录：dataset/family/model/retriever。"""

    family = re.sub(
        r"[^A-Za-z0-9._-]+",
        "-",
        str(generator_family or "").strip().casefold(),
    ).strip("-")
    if family not in {"gemini", "gemma", "qwen", "gpt", "llama", "phi", "command-r"}:
        raise ValueError(f"Invalid generator family: {generator_family!r}")
    if not str(concrete_model or "").strip():
        raise ValueError("concrete_model is required")
    if not str(retriever_id or "").strip():
        raise ValueError("retriever_id is required")
    return (
        resolve_path(stage_base)
        / dataset
        / family
        / model_slug(concrete_model)
        / model_slug(retriever_id)
    )


def experiment_run_dir(
    runs_base: str | Path,
    dataset: str,
    run_id: str,
    *,
    generator_family: str,
    concrete_model: str,
    retriever_id: str,
) -> Path:
    """v20 run 目录：dataset/family/model/retriever/run_id。"""

    return ensure_dir(
        experiment_scoped_dir(
            runs_base,
            dataset,
            generator_family=generator_family,
            concrete_model=concrete_model,
            retriever_id=retriever_id,
        )
        / run_id
    )


def run_dir(dataset: str, run_id: str, *, model: str | None = None) -> Path:
    """返回并创建该次运行的归档目录 outputs/runs/{dataset}/{model}/{run_id}/。"""
    return ensure_dir(
        resolve_path("outputs/runs")
        / dataset
        / (model_slug(model) if model is not None else victim_model_slug())
        / run_id
    )


def index_path(dataset: str, *, model: str | None = None) -> Path:
    """返回历次运行总表路径 outputs/runs/{dataset}/{model}/index.jsonl(不创建文件)。"""
    return (
        resolve_path("outputs/runs")
        / dataset
        / (model_slug(model) if model is not None else victim_model_slug())
        / "index.jsonl"
    )


def append_index(dataset: str, record: dict[str, Any], *, model: str | None = None) -> Path:
    """往历次运行总表追加一行(自动建目录)。返回总表路径。"""
    path = index_path(dataset, model=model)
    ensure_dir(path.parent)
    write_jsonl([record], path, append=True)
    return path


def new_run_id(label: str | None = None) -> str:
    """现生成一个全新的 run_id(本地开始时间戳 + 可选人类标签)。

    与 current_run_id() 不同:本函数不读 PCV_RUN_ID,总是用当前时间现生成,供流水线在
    启动时盖一个"开始时间"戳、再 export 给所有子步骤共享(子步骤届时用 current_run_id
    读回同一个 id)。

    参数:
        label: 可选人类标签;非空时清洗为安全字符集 [A-Za-z0-9._-] 后拼成 {时间戳}_{标签}。
    返回:
        形如 20260707-153012 或 20260707-153012_baseline-fix 的 run_id。
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    if label and label.strip():
        # 把空格/斜杠等不适合做目录名的字符统一折叠为连字符,首尾多余连字符去掉。
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip()).strip("-")
        if safe:
            return f"{ts}_{safe}"
    return ts


# 阶段产物目录的单一事实源。归档时遍历它,把一次实验散落各处的产物收进 run 文件夹。
# 分两类:模型无关(facts/queries 等,产物直接在 {stage}/{ds}_* 或 {stage}/{ds}/)与
# 模型相关(第 10-15 步,产物在 {stage}/{ds}/{model}/)。显式不含 runs/(归档自身)与 archive/。
_FLAT_STAGE_DIRS: tuple[str, ...] = (
    "facts",
    "paired_claims",
    "paired_queries",
    "stealth_filtered_queries",
    "query_controls",
)
_MODEL_STAGE_DIRS: tuple[str, ...] = (
    "diagnostics",
    "rag_responses",
    "llm_only_responses",
    "parsed_stance",
    "scores",
    "baselines",
    "defenses",
    "mechanisms",
    "reports",
    "query_control_responses",
    "query_control_scores",
)
_STAGE_DIRS: tuple[str, ...] = _FLAT_STAGE_DIRS + _MODEL_STAGE_DIRS


def stage_output_dirs() -> list[tuple[str, Path]]:
    """返回全部阶段产物目录 (阶段名, 绝对路径) 列表(不保证目录已存在)。"""
    base = resolve_path("outputs")
    return [(name, base / name) for name in _STAGE_DIRS]


def _copy_dataset_artifacts(dataset: str, src_dir: Path, dest_dir: Path) -> tuple[int, int]:
    """把 src_dir 里属于 dataset 的产物拷到 dest_dir,返回 (文件数, 总字节数)。

    命中两类:直属的 {dataset}_* 文件(如 edgar_facts.jsonl);名为 {dataset} 的子目录
    则递归整拷。用 shutil.copy2 保留 mtime。仅在确有文件要拷时才建目标目录,避免留空文件夹。
    """
    files = 0
    nbytes = 0
    # ① 直属 {dataset}_* 文件(如 edgar_facts.jsonl / edgar_facts.manifest.json)。
    for item in sorted(src_dir.glob(f"{dataset}_*")):
        if item.is_file():
            ensure_dir(dest_dir)
            shutil.copy2(item, dest_dir / item.name)
            files += 1
            nbytes += item.stat().st_size
    # ② {dataset}/ 子目录(按数据集分子目录存放的模型无关产物)。
    sub = src_dir / dataset
    if sub.is_dir():
        for item in sorted(sub.rglob("*")):
            if item.is_file():
                rel = item.relative_to(sub)
                target = dest_dir / dataset / rel
                ensure_dir(target.parent)
                shutil.copy2(item, target)
                files += 1
                nbytes += item.stat().st_size
    return files, nbytes


def _copy_tree(src_dir: Path, dest_dir: Path) -> tuple[int, int]:
    """递归把 src_dir 下所有文件拷到 dest_dir(保留相对结构),返回 (文件数, 总字节数)。"""
    files = 0
    nbytes = 0
    for item in sorted(src_dir.rglob("*")):
        if item.is_file():
            target = dest_dir / item.relative_to(src_dir)
            ensure_dir(target.parent)
            shutil.copy2(item, target)
            files += 1
            nbytes += item.stat().st_size
    return files, nbytes


def archive_run(dataset: str, run_id: str, *, model: str | None = None, stages: list[str] | None = None) -> dict[str, Any]:
    """把某数据集本次实验的全部阶段产物拷进 run 文件夹,做成自包含存档。

    目标为 outputs/runs/{dataset}/{model}/{run_id}/{阶段}/。
    - 模型无关阶段:拷 {stage}/{dataset}_* 与 {stage}/{dataset}/。
    - 模型相关阶段:只拷当前模型的那份 {stage}/{dataset}/{model}/(不会把别的模型也带进来)。
    缺失的阶段目录静默跳过。

    参数:
        dataset: 数据集名。
        run_id:  本次运行标识(即 run 文件夹名)。
        model:   模型 slug;缺省用当前 victim_model_slug()。
        stages:  仅归档这些阶段名;None 表示全部。
    返回:
        归档清单 {"files": 总文件数, "bytes": 总字节, "by_stage": {阶段: 文件数}}。
    """
    model = model or victim_model_slug()
    dest_root = run_dir(dataset, run_id, model=model)
    base = resolve_path("outputs")
    total_files = 0
    total_bytes = 0
    by_stage: dict[str, int] = {}

    def _tally(name: str, count: int, size: int) -> None:
        nonlocal total_files, total_bytes
        if count:
            by_stage[name] = count
            total_files += count
            total_bytes += size

    # 模型无关阶段:{stage}/{ds}_* 与 {stage}/{ds}/
    for name in _FLAT_STAGE_DIRS:
        if stages is not None and name not in stages:
            continue
        src_dir = base / name
        if src_dir.is_dir():
            _tally(name, *_copy_dataset_artifacts(dataset, src_dir, dest_root / name))
    # 模型相关阶段:只拷 {stage}/{ds}/{model}/
    for name in _MODEL_STAGE_DIRS:
        if stages is not None and name not in stages:
            continue
        msrc = base / name / dataset / model
        if msrc.is_dir():
            _tally(name, *_copy_tree(msrc, dest_root / name))
    inventory = artifact_inventory(dest_root)
    return {
        "files": total_files,
        "bytes": total_bytes,
        "by_stage": by_stage,
        "inventory": inventory,
        "inventory_hash": sha256_obj(inventory),
    }


def archive_experiment_run(
    dataset: str,
    run_id: str,
    *,
    generator_family: str,
    concrete_model: str,
    retriever_id: str,
    runs_base: str | Path,
    flat_stage_dirs: dict[str, str | Path],
    cell_stage_dirs: dict[str, str | Path],
) -> tuple[Path, dict[str, Any]]:
    """把 v20 单个实验 cell 归档到完整 family/model/retriever 身份目录。"""

    dest_root = experiment_run_dir(
        runs_base,
        dataset,
        run_id,
        generator_family=generator_family,
        concrete_model=concrete_model,
        retriever_id=retriever_id,
    )
    total_files = 0
    total_bytes = 0
    by_stage: dict[str, int] = {}
    for name, base_path in flat_stage_dirs.items():
        source = resolve_path(base_path)
        if not source.is_dir():
            continue
        count, size = _copy_dataset_artifacts(
            dataset,
            source,
            dest_root / name,
        )
        if count:
            by_stage[name] = count
            total_files += count
            total_bytes += size
    for name, source_path in cell_stage_dirs.items():
        source = Path(source_path)
        if not source.is_dir():
            continue
        count, size = _copy_tree(source, dest_root / name)
        if count:
            by_stage[name] = count
            total_files += count
            total_bytes += size
    inventory = artifact_inventory(dest_root)
    return dest_root, {
        "files": total_files,
        "bytes": total_bytes,
        "by_stage": by_stage,
        "inventory": inventory,
        "inventory_hash": sha256_obj(inventory),
    }


def file_snapshot(path: str | Path) -> dict[str, Any]:
    """冻结单个文件的绝对路径、大小与 SHA-256；缺失文件显式标记。"""
    p = Path(path).resolve()
    if not p.is_file():
        return {"path": str(p), "exists": False, "size": None, "sha256": ""}
    return {"path": str(p), "exists": True, "size": p.stat().st_size, "sha256": sha256_file(p)}


def preregistration_snapshot(
    path: str | Path,
    *,
    dataset: str,
    victim_model: str,
    run_role: str,
    retriever_backend: str | None = None,
) -> dict[str, Any]:
    """读取预注册 suite 单元并冻结配置 hash；找不到唯一匹配时显式报错。"""
    config_path = Path(path).resolve()
    config = load_yaml(config_path)
    cells = [
        cell for cell in config.get("cells", [])
        if str(cell.get("dataset")) == dataset
        and str(cell.get("victim_model")) == victim_model
        and str(cell.get("run_role", "main")) == run_role
        and (
            retriever_backend is None
            or str(cell.get("retriever_backend") or "none") == str(retriever_backend)
        )
    ]
    if len(cells) != 1:
        return {
            **file_snapshot(config_path),
            "suite_id": str(config.get("suite_id") or ""),
            "selection_rule": str(config.get("selection_rule") or ""),
            "cell": {},
            "error": f"expected_one_matching_cell_found_{len(cells)}",
        }
    return {
        **file_snapshot(config_path),
        "suite_id": str(config.get("suite_id") or ""),
        "selection_rule": str(config.get("selection_rule") or ""),
        "cell": cells[0],
        "expected_cells": list(config.get("cells") or []),
        "expected_cells_hash": sha256_obj(list(config.get("cells") or [])),
    }


def build_experiment_identity(manifest: dict[str, Any], source_whitelist_hash: str) -> dict[str, Any]:
    """从 run manifest 提取决定实验单元身份的冻结字段。"""
    configs = manifest.get("configs") or {}
    protocol = manifest.get("protocol") or {}
    return {
        "dataset": manifest.get("dataset"),
        "generator_family": manifest.get("generator_family"),
        "concrete_model": manifest.get("concrete_model")
        or manifest.get("victim_model"),
        "run_role": manifest.get("run_role", "main"),
        "split_seed": manifest.get("split_seed"),
        "scale": manifest.get("scale"),
        "victim_model": manifest.get("victim_model"),
        "victim_provider": manifest.get("victim_provider"),
        "victim_endpoint": manifest.get("victim_endpoint"),
        "generator_id": manifest.get("generator_id") or manifest.get("victim_model"),
        "generator_version": manifest.get("generator_version"),
        "retriever_backend": manifest.get("retriever_backend"),
        "retriever_id": manifest.get("retriever_id"),
        "index_manifest_hash": manifest.get("index_manifest_hash"),
        "schedule_hash": manifest.get("schedule_hash"),
        "reserve_roles_hash": manifest.get("reserve_roles_hash"),
        "query_hash": manifest.get("query_hash")
        or manifest.get("queries_hash")
        or (manifest.get("query_plan") or {}).get("sha256"),
        "benchmark_hash": (manifest.get("benchmark") or {}).get("benchmark_hash"),
        "ia_shadow_manifest_hash": manifest.get("ia_shadow_manifest_hash")
        or (manifest.get("ia_shadow_identity") or {}).get("ia_shadow_manifest_hash")
        or ((manifest.get("method_identities") or {}).get("IA") or {}).get(
            "ia_shadow_manifest_hash"
        ),
        "ia_shadow_model_version": manifest.get("ia_shadow_model_version")
        or (manifest.get("ia_shadow_identity") or {}).get("ia_shadow_model_version")
        or ((manifest.get("method_identities") or {}).get("IA") or {}).get(
            "ia_shadow_model_version"
        ),
        "config_hashes": {
            name: value.get("sha256") if isinstance(value, dict) else None
            for name, value in sorted(configs.items())
        },
        "method_version": protocol.get("method_version"),
        "threat_model_version": protocol.get("threat_model_version"),
        "metrics_version": protocol.get("metrics_version"),
        "code_commit": (manifest.get("git") or {}).get("commit"),
        "source_whitelist_hash": source_whitelist_hash,
    }


def artifact_inventory(root: str | Path) -> list[dict[str, Any]]:
    """为归档目录生成稳定文件清单，run_manifest 本身不纳入自引用 hash。"""
    base = Path(root)
    rows: list[dict[str, Any]] = []
    if not base.exists():
        return rows
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        if path.name == "run_manifest.json" or path.suffix == ".tmp":
            continue
        rows.append({
            "path": path.relative_to(base).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def verify_artifact_inventory(root: str | Path, inventory: list[dict[str, Any]]) -> list[str]:
    """重算归档文件 hash，返回缺失、大小或摘要不一致的相对路径。"""
    base = Path(root)
    invalid: list[str] = []
    for row in inventory:
        rel = str(row.get("path") or "")
        path = base / rel
        if not rel or not path.is_file():
            invalid.append(rel or "<missing-path>")
            continue
        if path.stat().st_size != int(row.get("size", -1)) or sha256_file(path) != str(row.get("sha256") or ""):
            invalid.append(rel)
    return invalid


def archive_provenance_files(root: str | Path, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把配置、切分、benchmark 与 index 文件复制进 run/provenance，冻结原始输入。"""
    base = Path(root)
    dest = ensure_dir(base / "provenance")
    copied: list[dict[str, Any]] = []
    for index, snapshot in enumerate(snapshots):
        if not snapshot.get("exists"):
            continue
        source = Path(str(snapshot.get("path")))
        if not source.is_file():
            continue
        target = dest / f"{index:03d}_{source.name}"
        shutil.copy2(source, target)
        copied.append({
            "path": target.relative_to(base).as_posix(),
            "source_path": str(source),
            "sha256": str(snapshot.get("sha256") or ""),
        })
    return copied


def write_run_manifest(
    dataset: str,
    run_id: str,
    meta: dict[str, Any],
    *,
    model: str | None = None,
) -> Path:
    """把本次运行的元信息写成 run 文件夹下的 run_manifest.json,返回其路径。"""
    path = run_dir(dataset, run_id, model=model) / "run_manifest.json"
    write_json(meta, path)
    return path


def benchmark_snapshot(dataset: str) -> dict[str, Any]:
    """读取固定 attack benchmark 的 hash；缺失时返回空 hash，由 canonical 门禁拒绝。"""
    base = resolve_path("datasets/benchmarks")
    hash_path = base / f"{dataset}_attack_benchmark.sha256"
    manifest_path = base / f"{dataset}_benchmark_manifest.json"
    benchmark_path = base / f"{dataset}_attack_benchmark.jsonl"
    digest = hash_path.read_text(encoding="utf-8").strip() if hash_path.exists() else ""
    actual = sha256_file(benchmark_path) if benchmark_path.is_file() else ""
    return {
        "path": str(benchmark_path),
        "hash_path": str(hash_path),
        "benchmark_hash": digest,
        "actual_hash": actual,
        "hash_matches": bool(digest and actual and digest == actual),
        "manifest": read_json(manifest_path) if manifest_path.exists() else {},
    }


def _response_stage_integrity(
    stage_root: Path,
    expected_ids: set[str],
    *,
    expected_model_id: str | None = None,
) -> dict[str, Any]:
    """核对一个响应阶段的 query 唯一性、有效性与计划覆盖。"""
    rows = [row for path in stage_root.rglob("*.jsonl") for row in read_jsonl(path)] if stage_root.exists() else []
    ids = [str(row.get("query_id") or "") for row in rows]
    valid_ids = {
        str(row.get("query_id"))
        for row in rows
        if response_record_is_success(
            row,
            expected_model_id=expected_model_id,
        )
    }
    invalid = sum(
        1
        for row in rows
        if not response_record_is_success(
            row,
            expected_model_id=expected_model_id,
        )
    )
    duplicates = len(ids) - len(set(ids))
    return {
        "rows": len(rows),
        "valid": len(valid_ids),
        "invalid": invalid,
        "duplicates": duplicates,
        "missing": len(expected_ids - valid_ids),
        "unexpected": len(valid_ids - expected_ids),
    }


def archived_source_whitelist(root: str | Path) -> dict[str, Any]:
    """从归档 source scores/coverage 重建唯一评估 source whitelist。"""
    run_root = Path(root)
    score_paths = list((run_root / "scores").rglob("*_pcv_scores_source_scores.jsonl"))
    coverage_paths = list((run_root / "scores").rglob("*_source_coverage.jsonl"))
    score_rows = list(read_jsonl(score_paths[0])) if len(score_paths) == 1 else []
    coverage_rows = list(read_jsonl(coverage_paths[0])) if len(coverage_paths) == 1 else []
    score_keys = {
        str(row.get("source_key"))
        for row in score_rows
        if str(row.get("group")) in {"KB_Member", "True_Non_Member"}
    }
    coverage_keys = {
        str(row.get("source_key"))
        for row in coverage_rows
        if str(row.get("group")) in {"KB_Member", "True_Non_Member"}
        and bool(row.get("evaluation_eligible"))
    }
    groups = {
        group: sum(1 for row in score_rows if str(row.get("group")) == group)
        for group in ("KB_Member", "True_Non_Member")
    }
    return {
        "score_files": len(score_paths),
        "coverage_files": len(coverage_paths),
        "source_count": len(score_keys),
        "source_counts_by_group": groups,
        "source_whitelist_hash": sha256_obj(sorted(score_keys)) if score_keys else "",
        "coverage_whitelist_hash": sha256_obj(sorted(coverage_keys)) if coverage_keys else "",
        "score_coverage_match": bool(score_keys and score_keys == coverage_keys),
        "source_scores_path": str(score_paths[0]) if len(score_paths) == 1 else "",
    }


def archived_query_source_whitelist(root: str | Path) -> dict[str, Any]:
    """从归档的固定查询计划重建 matched-control 的评估 source whitelist。"""
    run_root = Path(root)
    query_paths = list(
        (run_root / "stealth_filtered_queries").rglob("*_paired_queries.jsonl")
    )
    query_rows = list(read_jsonl(query_paths[0])) if len(query_paths) == 1 else []
    source_groups: dict[str, set[str]] = defaultdict(set)
    for row in query_rows:
        if not row.get("accepted", True):
            continue
        group = str(row.get("group") or "")
        if group not in {"KB_Member", "True_Non_Member"}:
            continue
        source_key = str(
            row.get("source_key")
            or row.get("source_id")
            or row.get("doc_id")
            or row.get("audit_id")
            or ""
        )
        if source_key:
            source_groups[source_key].add(group)
    conflicts = sorted(key for key, groups in source_groups.items() if len(groups) != 1)
    source_keys = sorted(source_groups)
    groups = {
        group: sum(1 for values in source_groups.values() if values == {group})
        for group in ("KB_Member", "True_Non_Member")
    }
    return {
        "query_files": len(query_paths),
        "source_count": len(source_keys),
        "source_counts_by_group": groups,
        "source_group_conflicts": conflicts,
        "source_whitelist_hash": sha256_obj(source_keys) if source_keys else "",
        "query_plan_path": str(query_paths[0]) if len(query_paths) == 1 else "",
    }


def _matched_control_provenance(
    run_root: Path,
    query_whitelist: dict[str, Any],
) -> dict[str, Any]:
    """核对 matched-control 响应清单是否来自同一固定查询计划且未运行 RAG。"""
    manifest_paths = list(
        (run_root / "llm_only_responses").rglob("*_llm_only_responses.manifest.json")
    )
    response_manifest = read_json(manifest_paths[0]) if len(manifest_paths) == 1 else {}
    query_path = Path(str(query_whitelist.get("query_plan_path") or ""))
    query_hash = sha256_file(query_path) if query_path.is_file() else ""
    return {
        "manifest_files": len(manifest_paths),
        "run_rag": response_manifest.get("run_rag"),
        "run_llm_only": response_manifest.get("run_llm_only"),
        "query_hash_matches": bool(
            query_hash and response_manifest.get("queries_hash") == query_hash
        ),
        "source_whitelist_hash_matches": bool(
            query_whitelist.get("source_whitelist_hash")
            and response_manifest.get("source_whitelist_hash")
            == query_whitelist.get("source_whitelist_hash")
        ),
    }


def _baseline_whitelist_integrity(run_root: Path, source_whitelist_hash: str) -> dict[str, Any]:
    """验证每个 baseline 的 source 集与 PCV 主评估 whitelist 完全一致。"""
    baseline_root = run_root / "baselines"
    paths = list(baseline_root.rglob("*_scores_source_scores.jsonl")) if baseline_root.exists() else []
    methods: dict[str, Any] = {}
    mismatches: list[str] = []
    for path in paths:
        rows = [
            row for row in read_jsonl(path)
            if str(row.get("group")) in {"KB_Member", "True_Non_Member"}
        ]
        source_keys = sorted({str(row.get("source_key")) for row in rows if row.get("source_key")})
        method = str(rows[0].get("baseline")) if rows else path.name.removesuffix("_scores_source_scores.jsonl")
        digest = sha256_obj(source_keys) if source_keys else ""
        methods[method] = {
            "path": str(path),
            "source_count": len(source_keys),
            "source_whitelist_hash": digest,
        }
        if not source_keys or digest != source_whitelist_hash:
            mismatches.append(method)
    comparison_paths = list(baseline_root.rglob("*_baseline_comparison.jsonl")) if baseline_root.exists() else []
    return {
        "comparison_files": len(comparison_paths),
        "source_score_files": len(paths),
        "methods": methods,
        "mismatched_methods": sorted(mismatches),
    }


def archived_integrity_summary(
    root: str | Path,
    *,
    run_role: str = "main",
    expected_model_id: str | None = None,
) -> dict[str, Any]:
    """统计 canonical 所需的查询、双路响应、baseline 与 source coverage 完整性。"""
    run_root = Path(root)
    query_rows = [
        row
        for path in (run_root / "stealth_filtered_queries").rglob("*.jsonl")
        for row in read_jsonl(path)
        if row.get("accepted", True)
    ] if (run_root / "stealth_filtered_queries").exists() else []
    query_ids = [str(row.get("query_id") or "") for row in query_rows]
    expected_ids = {qid for qid in query_ids if qid}
    baseline_failures = 0
    baseline_root = run_root / "baselines"
    if baseline_root.exists():
        for path in baseline_root.rglob("*_scores.jsonl"):
            if path.name.endswith("_source_scores.jsonl"):
                continue
            for row in read_jsonl(path):
                if row.get("error") or row.get("score") is None:
                    baseline_failures += 1
    coverage_rows = [
        row
        for path in (run_root / "scores").rglob("*_source_coverage.jsonl")
        for row in read_jsonl(path)
    ] if (run_root / "scores").exists() else []
    incomplete_sources = sum(
        1 for row in coverage_rows
        if bool(row.get("attack_eligible", True)) and not bool(row.get("execution_complete", row.get("evaluation_eligible")))
    )
    score_whitelist = archived_source_whitelist(run_root)
    query_whitelist = archived_query_source_whitelist(run_root)
    whitelist = query_whitelist if run_role == "matched_control" else score_whitelist
    matched_control_provenance = _matched_control_provenance(run_root, query_whitelist)
    baseline_whitelist = _baseline_whitelist_integrity(
        run_root, str(whitelist.get("source_whitelist_hash") or "")
    )
    return {
        "planned_queries": len(expected_ids),
        "query_duplicates": len(query_ids) - len(expected_ids),
        "rag": _response_stage_integrity(
            run_root / "rag_responses",
            expected_ids,
            expected_model_id=expected_model_id,
        ),
        "llm_only": _response_stage_integrity(
            run_root / "llm_only_responses",
            expected_ids,
            expected_model_id=expected_model_id,
        ),
        "baseline_failures": baseline_failures,
        "coverage_rows": len(coverage_rows),
        "incomplete_sources": incomplete_sources,
        "source_whitelist": whitelist,
        "score_source_whitelist": score_whitelist,
        "query_source_whitelist": query_whitelist,
        "matched_control_provenance": matched_control_provenance,
        "baseline_whitelist": baseline_whitelist,
    }


def archived_failure_count(root: str | Path, *, run_role: str = "main") -> int:
    """兼容旧调用：返回双路无效响应、baseline 失败与不完整 source 总数。"""
    summary = archived_integrity_summary(root, run_role=run_role)
    return (
        int(summary["rag"]["invalid"])
        + int(summary["llm_only"]["invalid"])
        + int(summary["baseline_failures"])
        + int(summary["incomplete_sources"])
    )


def canonical_eligibility(manifest: dict[str, Any], root: str | Path) -> dict[str, Any]:
    """检查 candidate 是否满足晋升 canonical 的最小可复现性门禁。"""
    run_root = Path(root)
    reasons: list[str] = []
    if manifest.get("status") != "candidate":
        reasons.append("run_is_not_candidate")
    if manifest.get("source") != "pipeline (run_pipeline.py)":
        reasons.append("not_a_pipeline_run")
    run_role = str(manifest.get("run_role") or "main")
    if run_role not in CANONICAL_RUN_ROLES:
        reasons.append("invalid_run_role")
    if str(manifest.get("scale") or "") != CANONICAL_SCALE:
        reasons.append("scale_not_formal")
    if str(manifest.get("split_seed")) != str(CANONICAL_SPLIT_SEED):
        reasons.append("split_seed_not_preregistered")
    victim_model = str(manifest.get("victim_model") or "").strip()
    if not victim_model or victim_model == "unspecified":
        reasons.append("victim_model_missing")
    if not str(manifest.get("generator_id") or "").strip():
        reasons.append("generator_id_missing")
    if not str(manifest.get("generator_family") or "").strip():
        reasons.append("generator_family_missing")
    if not str(manifest.get("concrete_model") or "").strip():
        reasons.append("concrete_model_missing")
    if not str(manifest.get("generator_version") or "").strip():
        reasons.append("generator_version_missing")
    if not (
        str(manifest.get("query_hash") or "").strip()
        or str(manifest.get("queries_hash") or "").strip()
        or str((manifest.get("query_plan") or {}).get("sha256") or "").strip()
    ):
        reasons.append("query_hash_missing")
    git = manifest.get("git") or {}
    if not git.get("commit"):
        reasons.append("git_commit_missing")
    if bool(git.get("dirty")):
        reasons.append("git_worktree_dirty")
    if manifest.get("steps_failed") not in (None, ""):
        reasons.append("pipeline_step_failed")
    if manifest.get("canonical_analysis_failed") not in (None, ""):
        reasons.append("canonical_analysis_failed")
    if run_role == "main" and bool(manifest.get("run_llm_only", False)):
        reasons.append("main_run_must_be_rag_only")
    if run_role == "matched_control" and not bool(manifest.get("run_llm_only", False)):
        reasons.append("matched_control_requires_llm_only")
    if run_role == "main":
        protocol = manifest.get("protocol") or {}
        if protocol.get("metrics_version") != "source-conformal-bootstrap-v2":
            reasons.append("metrics_version_mismatch")
        if protocol.get("dataset_status") != "pre_response_frozen_canonical":
            reasons.append("dataset_status_not_frozen")
        if protocol.get("execution") != "source_block_interleaved":
            reasons.append("execution_not_source_block_interleaved")
        if not str(manifest.get("schedule_hash") or "").strip():
            reasons.append("execution_schedule_hash_missing")
        if not str(manifest.get("reserve_roles_hash") or "").strip():
            reasons.append("reserve_roles_hash_missing")
        if str(manifest.get("retriever_backend") or "") not in {"dense", "bm25", "hybrid"}:
            reasons.append("retriever_backend_missing_or_invalid")
        if not str(manifest.get("retriever_id") or "").strip():
            reasons.append("retriever_id_missing")
        if not str(manifest.get("index_manifest_hash") or "").strip():
            reasons.append("index_manifest_hash_missing")
        retriever_manifest = manifest.get("retriever_manifest") or {}
        retriever_id = str(manifest.get("retriever_id") or "")
        if "minilm" in retriever_id.casefold():
            reasons.append("retired_minilm_retriever")
        if str(manifest.get("retriever_backend") or "") in {"dense", "hybrid"}:
            revision = (
                retriever_manifest.get("embedding_revision")
                or retriever_manifest.get("dense_embedding_revision")
            )
            if not str(revision or "").strip():
                reasons.append("retriever_snapshot_missing")
        required_analyses = {
            "offline_ablation",
            "shortcut_controls",
            "query_control:random_same_type_counterfactual",
            "query_control:independent_unpaired_query",
            "query_control:no_stealth_filter",
        }
        completed_analyses = set(manifest.get("canonical_analyses_completed") or [])
        if not required_analyses.issubset(completed_analyses):
            reasons.append("canonical_analyses_incomplete")
    if run_role == "matched_control":
        required_steps = {10}
    else:
        required_steps = {1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 15}
        if str(manifest.get("retriever_backend") or "") == "dense":
            required_steps.update({12, 13, 14})
        if canonical_defense_required(
            str(manifest.get("dataset") or ""),
            victim_model,
            str(manifest.get("retriever_backend") or ""),
        ):
            required_steps.add(14)
    selected = {int(step) for step in manifest.get("steps_selected", [])}
    completed = {int(step) for step in manifest.get("steps_run", [])}
    if not required_steps.issubset(selected) or not required_steps.issubset(completed):
        reasons.append(
            "matched_control_collection_not_completed"
            if run_role == "matched_control"
            else "full_p0_pipeline_not_completed"
        )
    benchmark = manifest.get("benchmark") or {}
    if not str(benchmark.get("benchmark_hash") or "").strip():
        reasons.append("benchmark_hash_missing")
    elif not bool(benchmark.get("hash_matches")):
        reasons.append("benchmark_hash_mismatch")
    configs = manifest.get("configs") or {}
    if not configs or any(not isinstance(value, dict) or not value.get("sha256") for value in configs.values()):
        reasons.append("config_hashes_missing")
    provenance = manifest.get("input_provenance") or []
    if not provenance or any(not row.get("exists") or not row.get("sha256") for row in provenance):
        reasons.append("input_provenance_incomplete")
    preregistration = manifest.get("preregistration") or {}
    prereg_cell = preregistration.get("cell") or {}
    expected_retriever = str(prereg_cell.get("retriever_backend") or "")
    if (
        not preregistration.get("sha256")
        or preregistration.get("selection_rule") != CANONICAL_SELECTION_RULE
        or str(prereg_cell.get("dataset")) != str(manifest.get("dataset"))
        or str(prereg_cell.get("victim_model")) != victim_model
        or str(prereg_cell.get("run_role", "main")) != run_role
        or str(prereg_cell.get("scale")) != CANONICAL_SCALE
        or str(prereg_cell.get("seed")) != str(CANONICAL_SPLIT_SEED)
        or (
            run_role == "main"
            and expected_retriever
            and expected_retriever != str(manifest.get("retriever_backend") or "")
        )
    ):
        reasons.append("preregistration_missing_or_mismatched")
    if run_role == "main":
        if not list((run_root / "scores").rglob("*_pcv_scores_source_scores.jsonl")):
            reasons.append("source_scores_missing")
        if not list((run_root / "scores").rglob("*_source_coverage.jsonl")):
            reasons.append("source_coverage_missing")
        if not list((run_root / "reports").rglob("*_final_report.json")):
            reasons.append("final_report_missing")
    archive = manifest.get("archive") or {}
    inventory = archive.get("inventory") or []
    if not inventory or archive.get("inventory_hash") != sha256_obj(inventory):
        reasons.append("artifact_inventory_missing_or_invalid")
    elif verify_artifact_inventory(run_root, inventory):
        reasons.append("artifact_inventory_hash_mismatch")
    provenance_files = archive.get("provenance_files") or []
    if not provenance_files:
        reasons.append("provenance_archive_missing")
    else:
        for row in provenance_files:
            if not isinstance(row, dict):
                reasons.append("provenance_archive_invalid")
                break
            archived = run_root / str(row.get("path") or "")
            if not archived.is_file() or sha256_file(archived) != str(row.get("sha256") or ""):
                reasons.append("provenance_archive_hash_mismatch")
                break
    integrity = archived_integrity_summary(
        run_root,
        run_role=run_role,
        expected_model_id=str(
            manifest.get("generator_id")
            or manifest.get("concrete_model")
            or ""
        ).strip(),
    )
    if not integrity["planned_queries"] or integrity["query_duplicates"]:
        reasons.append("query_plan_missing_or_duplicate")
    required_response_modes = ["llm_only"] if run_role == "matched_control" else ["rag"]
    for mode in required_response_modes:
        state = integrity[mode]
        if state["invalid"] or state["duplicates"] or state["missing"] or state["unexpected"]:
            reasons.append(f"{mode}_responses_incomplete")
    whitelist = integrity["source_whitelist"]
    if run_role == "matched_control":
        if (
            whitelist["query_files"] != 1
            or not whitelist["source_count"]
            or whitelist["source_group_conflicts"]
        ):
            reasons.append("query_source_whitelist_invalid")
        matched_provenance = integrity["matched_control_provenance"]
        if (
            matched_provenance["manifest_files"] != 1
            or matched_provenance["run_rag"] is not False
            or matched_provenance["run_llm_only"] is not True
            or not matched_provenance["query_hash_matches"]
            or not matched_provenance["source_whitelist_hash_matches"]
        ):
            reasons.append("matched_control_provenance_invalid")
    else:
        baseline_required = (
            str(manifest.get("retriever_backend") or "") == "dense"
        )
        if baseline_required and integrity["baseline_failures"]:
            reasons.append("baseline_failures")
        if not integrity["coverage_rows"] or integrity["incomplete_sources"]:
            reasons.append("source_coverage_incomplete")
        if (
            whitelist["score_files"] != 1
            or whitelist["coverage_files"] != 1
            or not whitelist["score_coverage_match"]
        ):
            reasons.append("source_whitelist_invalid")
        baseline_whitelist = integrity["baseline_whitelist"]
        if baseline_required:
            if (
                baseline_whitelist["comparison_files"] != 1
                or not baseline_whitelist["source_score_files"]
                or baseline_whitelist["mismatched_methods"]
            ):
                reasons.append("baseline_source_whitelist_mismatch")
            expected_baselines = canonical_baseline_methods(victim_model)
            actual_baselines = set(baseline_whitelist.get("methods") or {})
            if expected_baselines is not None and actual_baselines != set(expected_baselines):
                reasons.append("baseline_method_set_mismatch")
        defense_required = canonical_defense_required(
            str(manifest.get("dataset") or ""),
            victim_model,
            str(manifest.get("retriever_backend") or ""),
        )
        defense_paths = list(
            (run_root / "defenses").rglob("*_defense_results.json")
        )
        if defense_required and not defense_paths:
            reasons.append("representative_defense_missing")
        if defense_required and len(defense_paths) == 1:
            defense_report = read_json(defense_paths[0])
            policies = list(defense_report.get("defenses") or [])
            expected_policies = {
                "answer_without_correction",
                "target_entity_redaction",
            }
            actual_policies = {
                str(row.get("defense")) for row in policies
            }
            if actual_policies != expected_policies or any(
                not row.get("implemented")
                or row.get("status") != "complete"
                or not row.get("privacy")
                or not row.get("utility")
                or row.get("generic_qa_utility_claimed") is not False
                for row in policies
            ):
                reasons.append("placeholder_or_incomplete_defense")
        elif defense_required and len(defense_paths) > 1:
            reasons.append("multiple_defense_reports")
    expected_identity = build_experiment_identity(
        manifest, str(whitelist.get("source_whitelist_hash") or "")
    )
    if manifest.get("experiment_identity") != expected_identity:
        reasons.append("experiment_identity_missing_or_mismatched")
    if run_role == "main":
        report_paths = list((run_root / "reports").rglob("*_final_report.json"))
        if len(report_paths) == 1:
            report = read_json(report_paths[0])
            if report.get("evaluation_unit") != "source":
                reasons.append("report_not_source_level")
            if report.get("source_whitelist_hash") != whitelist.get("source_whitelist_hash"):
                reasons.append("report_source_whitelist_mismatch")
            report_inputs = report.get("input_provenance") or {}
            source_score_path = Path(str(whitelist.get("source_scores_path") or ""))
            if (
                not source_score_path.is_file()
                or (report_inputs.get("source_scores") or {}).get("sha256") != sha256_file(source_score_path)
            ):
                reasons.append("report_input_provenance_mismatch")
        elif report_paths:
            reasons.append("multiple_final_reports")
    transport_failures = archived_failure_count(run_root, run_role=run_role)
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "transport_failures": transport_failures,
        "integrity": integrity,
    }


def experiment_cell_id(manifest: dict[str, Any]) -> str:
    """为 suite 内的一个实验格子生成稳定标识。"""
    identity = dict(manifest.get("experiment_identity") or {})
    identity.pop("run_role", None)
    cell = identity or {
        "dataset": manifest.get("dataset"),
        "victim_model": manifest.get("victim_model"),
        "benchmark_hash": (manifest.get("benchmark") or {}).get("benchmark_hash"),
        "protocol_version": (manifest.get("protocol") or {}).get("protocol_version"),
    }
    return sha256_obj(cell)[:16]


def register_canonical_run(
    suite_id: str,
    manifest: dict[str, Any],
    manifest_path: str | Path,
) -> Path:
    """把 canonical run 登记进 suite；同一格子禁止出现两个不同 canonical run。"""
    if manifest.get("status") != "canonical":
        raise ValueError("Only a canonical manifest can be registered in a suite")
    safe_suite = re.sub(r"[^A-Za-z0-9._-]+", "-", suite_id.strip()).strip("-")
    if not safe_suite:
        raise ValueError("suite_id must contain at least one safe character")
    suite_root = ensure_dir(resolve_path("outputs/releases") / safe_suite)
    suite_path = suite_root / "suite_manifest.json"
    preregistration = manifest.get("preregistration") or {}
    expected_cells = list(preregistration.get("expected_cells") or [preregistration.get("cell") or {}])
    expected_cells = [cell for cell in expected_cells if cell]
    expected_cells_hash = str(preregistration.get("expected_cells_hash") or sha256_obj(expected_cells))
    suite = read_json(suite_path) if suite_path.exists() else {
        "suite_id": safe_suite,
        "protocol": P0_PROTOCOL,
        "selection_rule": CANONICAL_SELECTION_RULE,
        "release_commit": (manifest.get("git") or {}).get("commit"),
        "status": "candidate",
        "expected_cells": expected_cells,
        "expected_cells_hash": expected_cells_hash,
        "created_at": local_timestamp(),
        "cells": {},
    }
    release_commit = str((manifest.get("git") or {}).get("commit") or "")
    if suite.get("release_commit") != release_commit:
        raise RuntimeError(
            f"Suite {safe_suite} release commit is {suite.get('release_commit')}, not {release_commit}"
        )
    if suite.get("expected_cells_hash") != expected_cells_hash:
        raise RuntimeError(
            f"Suite {safe_suite} preregistered cells changed after first registration"
        )
    cell_id = experiment_cell_id(manifest)
    cells = suite.setdefault("cells", {})
    cell = cells.setdefault(cell_id, {
        "cell_id": cell_id,
        "dataset": manifest.get("dataset"),
        "victim_model": manifest.get("victim_model"),
        "benchmark_hash": (manifest.get("benchmark") or {}).get("benchmark_hash"),
        "experiment_identity": manifest.get("experiment_identity"),
        "runs": {},
    })
    role = str(manifest.get("run_role") or "main")
    runs = cell.setdefault("runs", {})
    existing = runs.get(role)
    if existing and existing.get("run_id") != manifest.get("run_id"):
        raise RuntimeError(
            f"Suite {safe_suite} already has {role} run {existing.get('run_id')} for cell {cell_id}"
        )
    runs[role] = {
        "run_role": role,
        "run_id": manifest.get("run_id"),
        "run_manifest_path": str(Path(manifest_path).resolve()),
        "run_manifest_hash": sha256_file(manifest_path),
        "source_whitelist_hash": (manifest.get("experiment_identity") or {}).get("source_whitelist_hash"),
        "registered_at": local_timestamp(),
    }
    missing_cells: list[dict[str, Any]] = []
    for expected in suite.get("expected_cells") or []:
        expected_dataset = str(expected.get("dataset") or "")
        expected_model = str(expected.get("victim_model") or "")
        expected_role = str(expected.get("run_role") or "main")
        expected_retriever = str(expected.get("retriever_backend") or "none")
        found = False
        for candidate in cells.values():
            identity = candidate.get("experiment_identity") or {}
            if (
                str(candidate.get("dataset") or "") == expected_dataset
                and str(candidate.get("victim_model") or "") == expected_model
                and str(identity.get("scale") or "") == str(expected.get("scale") or "")
                and str(identity.get("split_seed")) == str(expected.get("seed"))
                and str(identity.get("retriever_backend") or "none") == expected_retriever
                and expected_role in (candidate.get("runs") or {})
            ):
                found = True
                break
        if not found:
            missing_cells.append(expected)
    suite["missing_cells"] = missing_cells
    suite["status"] = "canonical" if not missing_cells else "candidate"
    suite["updated_at"] = local_timestamp()
    write_json(suite, suite_path)
    return suite_path


def resolve_suite_run(
    suite_id: str,
    *,
    dataset: str,
    run_role: str = "main",
    victim_model: str | None = None,
    retriever_backend: str | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """从显式 suite registry 解析唯一 run，拒绝 glob/latest 与失效清单。"""
    suite_path = resolve_path("outputs/releases") / suite_id / "suite_manifest.json"
    if not suite_path.is_file():
        raise FileNotFoundError(f"Suite manifest not found: {suite_path}")
    suite = read_json(suite_path)
    if suite.get("status") != "canonical" or suite.get("missing_cells"):
        raise RuntimeError(f"Suite is incomplete and cannot drive official outputs: {suite_path}")
    matches: list[dict[str, Any]] = []
    for cell in (suite.get("cells") or {}).values():
        if str(cell.get("dataset")) != dataset:
            continue
        if victim_model is not None and str(cell.get("victim_model")) != str(victim_model):
            continue
        identity = cell.get("experiment_identity") or {}
        if retriever_backend is not None and str(identity.get("retriever_backend") or "none") != str(retriever_backend):
            continue
        run = (cell.get("runs") or {}).get(run_role)
        if run:
            matches.append(run)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one suite run for {dataset}/{victim_model or '*'}/{retriever_backend or '*'}/{run_role}, "
            f"found {len(matches)}"
        )
    record = matches[0]
    manifest_path = Path(str(record.get("run_manifest_path") or ""))
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Registered run manifest not found: {manifest_path}")
    if sha256_file(manifest_path) != str(record.get("run_manifest_hash") or ""):
        raise RuntimeError(f"Registered run manifest hash mismatch: {manifest_path}")
    manifest = read_json(manifest_path)
    if manifest.get("status") != "canonical" or str(manifest.get("run_role") or "main") != run_role:
        raise RuntimeError(f"Registered run is not canonical {run_role}: {manifest_path}")
    return manifest_path.parent, manifest, suite


def git_snapshot() -> dict[str, Any]:
    """采集当前 git 快照 {commit, branch, dirty};git 不可用时各字段留空,绝不抛错。"""

    def _run(cmd: list[str]) -> str:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(resolve_path(".")),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            # git 不存在 / 超时 / 非仓库:一律当作拿不到,交由上层留空。
            return ""
        return proc.stdout.strip() if proc.returncode == 0 else ""

    commit = _run(["git", "rev-parse", "HEAD"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    status = _run(["git", "status", "--porcelain"])
    return {"commit": commit, "branch": branch, "dirty": bool(status)}


def require_clean_release_commit(
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Return the immutable code commit or reject an unsafe API launch state."""

    state = dict(snapshot or git_snapshot())
    commit = str(state.get("commit") or "").strip()
    if not commit:
        raise RuntimeError("Canonical API launch requires a frozen git commit.")
    if bool(state.get("dirty")):
        raise RuntimeError(
            "Canonical API launch requires a clean worktree; commit the frozen "
            "protocol before making any victim-model call."
        )
    return commit


def read_scale() -> str:
    """从 configs/data_config.yaml 读当前 split.scale(读不到留空,不阻塞)。"""
    try:
        cfg = load_yaml(resolve_path("configs/data_config.yaml"))
        return str(cfg.get("split", {}).get("scale", ""))
    except Exception:
        return ""
