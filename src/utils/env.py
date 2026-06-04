"""轻量 .env 读取工具，用于本地实验开关。

中文说明
========
本文件提供读取 .env 文件和进程环境变量的小工具,被各脚本用来切换实验开关
(例如是否启用某个步骤、指定输出目录等)。刻意不引入 python-dotenv 依赖,只手写
最简单的 KEY=VALUE 解析。注意:进程里已存在的环境变量优先级高于 .env 中的同名项,
即 .env 只做"缺省补充",不会覆盖外部显式设置的变量。
"""

from __future__ import annotations

import os
from pathlib import Path

from .io import PROJECT_ROOT


TRUE_VALUES = {"1", "true", "yes", "y", "on", "enable", "enabled"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "disable", "disabled"}


def load_dotenv(path: str | Path | None = None) -> dict[str, str]:
    """从 .env 读取简单的 KEY=VALUE 键值对,且不覆盖已有环境变量。

    参数:
        path: .env 文件路径;为空时默认取工程根目录下的 .env。
    返回:
        本次从 .env 读到的键值对字典(已写入环境的同时也返回)。
    """
    env_path = Path(path) if path is not None else PROJECT_ROOT / ".env"
    loaded: dict[str, str] = {}
    if not env_path.exists():
        return loaded
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        # 跳过空行、注释行,以及没有 = 的非法行。
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        # 去掉值两侧可能包裹的引号。
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        loaded[key] = value
        # setdefault 保证不覆盖进程里已存在的同名变量。
        os.environ.setdefault(key, value)
    return loaded


def env_bool(name: str, default: bool = False, path: str | Path | None = None) -> bool:
    """从进程环境或 .env 读取一个布尔型实验开关。

    参数:
        name:    环境变量名。
        default: 变量缺失或取值无法识别时返回的默认值。
        path:    .env 文件路径(传给 load_dotenv)。
    返回:
        解析后的布尔值;无法识别时返回 default。
    """
    load_dotenv(path)
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def env_str(name: str, default: str | None = None, path: str | Path | None = None) -> str | None:
    """从进程环境或 .env 读取一个字符串型实验开关。

    参数:
        name:    环境变量名。
        default: 变量缺失或为空字符串时返回的默认值。
        path:    .env 文件路径(传给 load_dotenv)。
    返回:
        去除两侧引号后的字符串;为空时返回 default。
    """
    load_dotenv(path)
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().strip('"').strip("'")
    return normalized or default
