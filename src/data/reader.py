"""本地数据读取模块。

支持 JSONL、JSON、CSV、TXT 等常见格式，并抽取最可能的正文文本字段。

中文说明
========
本文件负责预处理的第一步:把磁盘上的原始数据"读进来"。不同数据集格式五花八门
(jsonl、json、csv、txt)，字段名也不统一(有的叫 text、有的叫 body/abstract...)，
本文件统一处理这些差异，从每条记录里"猜"出最像正文的那段文字，包装成 RawRecord。
注意:这里只管"读取 + 抽正文"，清洗/切分/过滤都交给后面的模块,职责单一。
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..utils.hash import short_hash
from ..utils.io import read_jsonl


# 候选的"正文字段名"，按优先级从高到低排列。读到记录时优先找这些键。
TEXT_KEYS = (
    "text",
    "body",
    "content",
    "message",
    "abstract",
    "article",
    "full_text",
    "plain_text",
    "document",
)


@dataclass(frozen=True)
class RawRecord:
    """原始读取记录。

    reader 只负责读取和提取正文，不在这里做清洗、切分和过滤。

    字段:
        source_id:   这条记录的来源标识(尽量稳定,便于追溯)。
        source_path: 来源文件路径。
        text:        抽取出的正文文本。
        metadata:    附加信息(格式类型,或读取错误等)。
    """
    source_id: str
    source_path: str
    text: str
    metadata: dict[str, Any]


def _first_text_value(row: dict[str, Any]) -> str:
    """从一行结构化记录中找到最可能的正文文本字段。

    先按 TEXT_KEYS 优先级找;都没有时,退而选所有字符串值里"最长且超过 40 字符"的那个。

    参数:
        row: 一条结构化记录(字典)。
    返回:
        最可能是正文的字符串;找不到返回 ""。
    """
    # 优先按已知字段名找。
    for key in TEXT_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    # 兜底:在所有较长的字符串值里选最长的当正文。
    strings = [str(v) for v in row.values() if isinstance(v, str) and len(v.strip()) > 40]
    return max(strings, key=len) if strings else ""


def _read_json_file(path: Path) -> Iterator[RawRecord]:
    """读取 JSON 文件；兼容 CUAD 这类嵌套 paragraph/context 结构。

    参数:
        path: JSON 文件路径。
    产出(生成器):
        逐条 RawRecord。
    """
    with path.open("r", encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    # JSON 顶层可能是列表、{"data": [...]}、或单个对象,统一成可迭代列表。
    if isinstance(data, list):
        iterable = data
    elif isinstance(data, dict) and isinstance(data.get("data"), list):
        iterable = data["data"]
    else:
        iterable = [data]

    idx = 0
    for obj in iterable:
        if not isinstance(obj, dict):
            continue
        # 处理嵌套 paragraphs 结构(如 CUAD 合同数据)。
        if "paragraphs" in obj and isinstance(obj["paragraphs"], list):
            # 嵌套 paragraph 结构（如 CUAD）：只抽取各 paragraph 正文，
            # 不再对外层 obj 重复抽取，否则同一文档会被读入两次。
            for para in obj["paragraphs"]:
                if isinstance(para, dict):
                    # 优先用 context 字段,否则再猜正文。
                    text = para.get("context") or _first_text_value(para)
                    if text:
                        yield RawRecord(f"{path.stem}_{idx:08d}", str(path), text, {"format": "json_paragraph"})
                        idx += 1
            continue
        # 普通对象:直接猜正文。
        text = _first_text_value(obj)
        if text:
            yield RawRecord(f"{path.stem}_{idx:08d}", str(path), text, {"format": "json"})
            idx += 1


def _read_jsonl_file(path: Path) -> Iterator[RawRecord]:
    """读取 JSONL 文件(每行一个 JSON 对象)。

    参数:
        path: JSONL 文件路径。
    产出(生成器):
        逐行 RawRecord;其它非正文字段会原样收进 metadata。
    """
    for idx, row in enumerate(read_jsonl(path)):
        text = _first_text_value(row)
        if not text:
            continue
        # 来源 id 优先用记录自带的 id 类字段,否则用"文件名_行号"。
        source_id = str(row.get("id") or row.get("sample_id") or row.get("audit_id") or f"{path.stem}_{idx:08d}")
        # 把正文之外的字段都留作 metadata。
        metadata = {k: v for k, v in row.items() if k not in {"text", "body", "content", "message"}}
        yield RawRecord(source_id, str(path), text, metadata)


def _read_csv_file(path: Path) -> Iterator[RawRecord]:
    """读取 CSV 文件(按表头解析成字典行)。

    参数:
        path: CSV 文件路径。
    产出(生成器):
        逐行 RawRecord。
    """
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        # DictReader 用首行表头把每行解析成字典。
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            text = _first_text_value(row)
            if not text:
                continue
            # 来源 id 优先用 id / Message-ID 等列,否则用"文件名_行号"。
            source_id = row.get("id") or row.get("Message-ID") or row.get("message_id") or f"{path.stem}_{idx:08d}"
            yield RawRecord(str(source_id), str(path), text, {"format": "csv"})


def _read_txt_file(path: Path) -> Iterator[RawRecord]:
    """读取纯文本文件,整篇作为一条记录。

    参数:
        path: txt/text/md 文件路径。
    产出(生成器):
        若文件非空,产出一条 RawRecord。
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.strip():
        yield RawRecord(path.stem, str(path), text, {"format": "text"})


def read_local_records(dataset: str, input_path: str | Path) -> Iterator[RawRecord]:
    """读取一个文件或目录下的所有支持格式文件。

    参数:
        dataset:    数据集名(仅用于报错信息)。
        input_path: 单个文件,或包含多文件的目录。
    产出(生成器):
        逐条 RawRecord;读取某文件出错时,产出一条带 read_error 的记录而不是中断整体。
    异常:
        FileNotFoundError: 输入路径不存在时抛出。
    """
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input path not found for {dataset}: {path}")

    files: Iterable[Path]
    # 输入是单个文件就只处理它;是目录则递归收集所有受支持后缀的文件并排序。
    if path.is_file():
        files = [path]
    else:
        files = sorted(
            p
            for p in path.rglob("*")
            if p.is_file() and p.suffix.lower() in {".jsonl", ".json", ".csv", ".txt", ".text", ".md"}
        )

    for file_path in files:
        suffix = file_path.suffix.lower()
        try:
            # 按后缀分派到对应的读取函数。
            if suffix == ".jsonl":
                yield from _read_jsonl_file(file_path)
            elif suffix == ".json":
                yield from _read_json_file(file_path)
            elif suffix == ".csv":
                yield from _read_csv_file(file_path)
            elif suffix in {".txt", ".text", ".md"}:
                yield from _read_txt_file(file_path)
        except Exception as exc:
            # 单个文件读失败不影响整体:产出一条带错误信息的记录,交由上层记录到错误文件。
            error_id = f"{file_path.stem}_{short_hash(str(file_path))}"
            yield RawRecord(error_id, str(file_path), "", {"read_error": str(exc)})
