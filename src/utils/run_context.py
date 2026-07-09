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
from datetime import datetime
from pathlib import Path
from typing import Any

from .io import ensure_dir, load_yaml, resolve_path, write_json, write_jsonl


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


def victim_model_slug() -> str:
    """受害者模型的文件夹安全 slug:读环境变量 PCV_VICTIM_MODEL;未设为 'unspecified'。

    形如 'qwen/qwen3.5-397b-a17b' 先去掉 org 前缀取最后一段,再把非法字符折叠成连字符,
    得到 'qwen3.5-397b-a17b'。模型相关产物据此按 {数据集}/{模型}/ 分目录,换模型不互相覆盖。
    """
    raw = os.environ.get("PCV_VICTIM_MODEL", "").strip()
    if not raw:
        return "unspecified"
    raw = raw.split("/")[-1]  # 去掉 org/ 前缀
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return slug or "unspecified"


def model_scoped_dir(stage_base: str | Path, dataset: str, *, model: str | None = None) -> Path:
    """模型相关阶段的目录 {stage_base}/{dataset}/{model}(不创建;写方自行 ensure_dir)。

    参数:
        stage_base: 阶段基目录(如 'outputs/scores' 或 config 里的 scores_dir)。
        dataset:    数据集名。
        model:      模型 slug;缺省用当前 victim_model_slug()。
    """
    return resolve_path(stage_base) / dataset / (model or victim_model_slug())


def run_dir(dataset: str, run_id: str, *, model: str | None = None) -> Path:
    """返回并创建该次运行的归档目录 outputs/runs/{dataset}/{model}/{run_id}/。"""
    return ensure_dir(resolve_path("outputs/runs") / dataset / (model or victim_model_slug()) / run_id)


def index_path(dataset: str, *, model: str | None = None) -> Path:
    """返回历次运行总表路径 outputs/runs/{dataset}/{model}/index.jsonl(不创建文件)。"""
    return resolve_path("outputs/runs") / dataset / (model or victim_model_slug()) / "index.jsonl"


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
    "diagnostics",
)
_MODEL_STAGE_DIRS: tuple[str, ...] = (
    "rag_responses",
    "llm_only_responses",
    "parsed_stance",
    "scores",
    "baselines",
    "defenses",
    "mechanisms",
    "reports",
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
    return {"files": total_files, "bytes": total_bytes, "by_stage": by_stage}


def write_run_manifest(dataset: str, run_id: str, meta: dict[str, Any]) -> Path:
    """把本次运行的元信息写成 run 文件夹下的 run_manifest.json,返回其路径。"""
    path = run_dir(dataset, run_id) / "run_manifest.json"
    write_json(meta, path)
    return path


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


def read_scale() -> str:
    """从 configs/data_config.yaml 读当前 split.scale(读不到留空,不阻塞)。"""
    try:
        cfg = load_yaml(resolve_path("configs/data_config.yaml"))
        return str(cfg.get("split", {}).get("scale", ""))
    except Exception:
        return ""
