"""文件读写工具。

中文说明
========
本文件集中处理工程内所有路径解析与文件读写。项目的中间数据统一以 JSONL/JSON 保存,
配置则以 YAML 编写,这里提供:路径解析(相对路径定位到工程根)、目录创建、JSON/JSONL
的读写与追加、记录计数,以及断点续跑辅助(读取已有产物里的字段集合用于去重、判断某
步骤是否已完成)。当环境缺少 PyYAML 时,还内置一个只支持本项目所需简单语法的轻量
YAML 解析器作为兜底。被预处理、生成、评估等几乎所有模块复用。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator


# 工程根目录:本文件位于 src/utils/ 下,向上两级即工程根。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent


def resolve_path(path: str | Path, base_dir: str | Path | None = None) -> Path:
    """把配置中的相对路径解析到工程根目录。

    参数:
        path:     待解析路径;绝对路径原样返回。
        base_dir: 相对路径的基准目录;为空时用工程根。
    返回:
        解析后的绝对路径。
    """
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    base = Path(base_dir) if base_dir is not None else PROJECT_ROOT
    return (base / p).resolve()


def ensure_dir(path: str | Path) -> Path:
    """确保目录存在(不存在则递归创建),返回该目录路径。"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_parent(path: str | Path) -> Path:
    """确保某文件路径的父目录存在,返回原文件路径(便于随后写入)。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _parse_scalar(value: str) -> Any:
    """把 YAML 标量字符串解析为对应的 Python 值(供轻量 YAML 解析器使用)。

    依次尝试识别空串、null、布尔、内联列表、带引号字符串,最后退回 int/float/原字符串。

    参数:
        value: 单个标量的原始字符串。
    返回:
        解析后的 Python 值。
    """
    value = value.strip()
    if value == "":
        return ""
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    # 内联列表 [a, b, c]:去掉方括号后按逗号逐项递归解析。
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    # 带引号的字符串:剥掉两侧引号。
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    # 无引号时尝试当数字,失败则当作普通字符串。
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _simple_yaml_load(path: Path) -> dict[str, Any]:
    """轻量 YAML 解析器。

    环境里没有 PyYAML 时使用，只支持本项目配置需要的简单字典、内联列表和标量。

    参数:
        path: YAML 文件路径。
    返回:
        解析得到的嵌套字典。
    异常:
        RuntimeError: 遇到不支持的块状列表或非法行时抛出。
    """
    root: dict[str, Any] = {}
    # stack 记录 (缩进层级, 对应字典),用于按缩进维护嵌套关系;-1 为根哨兵。
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    # 用 utf-8-sig 读取以自动吞掉可能的 BOM。
    for line_no, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if stripped.startswith("- "):
            raise RuntimeError(f"Fallback YAML parser does not support block lists at {path}:{line_no}")
        if ":" not in stripped:
            raise RuntimeError(f"Invalid YAML line at {path}:{line_no}: {raw}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        # 缩进回退:弹出所有不再是当前行祖先的层级,定位正确父字典。
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip() == "":
            # 冒号后为空表示这是一个新的嵌套块,压栈等待其子项。
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value)
    return root


def load_yaml(path: str | Path) -> dict[str, Any]:
    """读取 YAML 配置；优先使用 PyYAML，缺失时退回轻量解析器。

    参数:
        path: YAML 配置文件路径。
    返回:
        配置内容字典。
    异常:
        ValueError: 使用 PyYAML 时,顶层不是映射(字典)则抛出。
    """
    try:
        import yaml
    except ImportError as exc:
        # 没装 PyYAML:退回自带的简化解析器。
        p = Path(path)
        return _simple_yaml_load(p)

    p = Path(path)
    with p.open("r", encoding="utf-8-sig") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {p}")
    return data


def read_json(path: str | Path) -> Any:
    """读取并解析一个 JSON 文件,返回其内容。"""
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(obj: Any, path: str | Path, indent: int = 2) -> None:
    """把对象写成 JSON 文件(原子写:先写临时文件再替换)。

    参数:
        obj:    待写入的对象。
        path:   目标文件路径。
        indent: 缩进空格数。
    """
    p = ensure_parent(path)
    # 先写 .tmp 再原子替换,避免写一半被中断导致文件损坏。
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.write("\n")
    tmp.replace(p)


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """逐行读取 JSONL，并在出错时报告具体行号。

    参数:
        path: JSONL 文件路径。
    产出(生成器):
        每行解析出的字典(跳过空行)。
    异常:
        ValueError: 某行不是合法 JSON,或不是 JSON 对象时抛出(附带行号)。
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {p}:{line_no}: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"JSONL record must be an object at {p}:{line_no}")
            yield obj


def write_jsonl(records: Iterable[dict[str, Any]], path: str | Path, append: bool = False) -> int:
    """写入 JSONL；返回写入记录数。

    参数:
        records: 待写入的记录序列(每条为字典)。
        path:    目标文件路径。
        append:  True 为追加写,False 为覆盖写。
    返回:
        实际写入的记录条数。
    """
    p = ensure_parent(path)
    mode = "a" if append else "w"
    count = 0
    with p.open(mode, encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=False))
            f.write("\n")
            count += 1
    return count


def write_jsonl_atomic(records: Iterable[dict[str, Any]], path: str | Path) -> int:
    """原子覆盖 JSONL：完整写入临时文件后再替换目标文件。"""
    p = ensure_parent(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    count = write_jsonl(records, tmp, append=False)
    tmp.replace(p)
    return count


def append_jsonl_record(record: dict[str, Any], path: str | Path) -> None:
    """向 JSONL 文件追加一条记录(常用于断点续跑时逐条落盘)。"""
    p = ensure_parent(path)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=False))
        f.write("\n")


def count_jsonl(path: str | Path) -> int:
    """统计 JSONL 文件的非空行数;文件不存在返回 0。"""
    p = Path(path)
    if not p.exists():
        return 0
    with p.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def existing_values(path: str | Path, key: str) -> set[Any]:
    """读取已有 JSONL 中某个字段的取值集合，用于断点续跑去重。

    参数:
        path: JSONL 文件路径。
        key:  要收集取值的字段名。
    返回:
        该字段已出现过的所有取值集合;文件不存在返回空集合。
    """
    p = Path(path)
    if not p.exists():
        return set()
    values: set[Any] = set()
    for row in read_jsonl(p):
        if key in row:
            values.add(row[key])
    return values


def is_done(path: str | Path) -> bool:
    """判断某产物是否"已完成":文件存在且非空(用于跳过已跑完的步骤)。"""
    p = Path(path)
    return p.exists() and p.stat().st_size > 0
