"""运行上下文工具:为每次输出生成时间戳 run_id 与归档目录。

中文说明
========
PCV-MIA 的产物原本都是固定文件名、--force 直接覆盖,没法回看"哪次、什么时候"跑的。
本模块提供一个轻量的 run 标识与归档帮助:
    - current_run_id():  本次运行的唯一标识。优先用环境变量 PCV_RUN_ID(便于一条
      流水线的多个步骤共享同一个 id);没有就用本地时间现生成 YYYYMMDD-HHMMSS。
    - local_timestamp(): 人类可读的本地时间字符串(写进总表/图标题)。
    - run_dir(dataset, run_id): 该次运行的归档目录 outputs/runs/{dataset}/{run_id}/(自动建)。
    - index_path(dataset):      历次运行总表 outputs/runs/{dataset}/index.jsonl 的路径。
    - append_index(dataset, record): 往总表追加一行(历次运行速查表)。
这样每次结果都能按时间归档、不再互相覆盖,并有一张总表速查历次。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .io import ensure_dir, resolve_path, write_jsonl


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


def run_dir(dataset: str, run_id: str) -> Path:
    """返回并创建该次运行的归档目录 outputs/runs/{dataset}/{run_id}/。"""
    return ensure_dir(resolve_path("outputs/runs") / dataset / run_id)


def index_path(dataset: str) -> Path:
    """返回历次运行总表路径 outputs/runs/{dataset}/index.jsonl(不创建文件)。"""
    return resolve_path("outputs/runs") / dataset / "index.jsonl"


def append_index(dataset: str, record: dict[str, Any]) -> Path:
    """往历次运行总表追加一行(自动建目录)。返回总表路径。"""
    path = index_path(dataset)
    ensure_dir(path.parent)
    write_jsonl([record], path, append=True)
    return path
