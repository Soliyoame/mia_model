"""Hash 工具。

中文说明
========
本文件提供文本、对象和文件的 sha256 哈希计算。PCV-MIA 依赖"不可变基准集"与
文本去重,因此关键数据产物都会存一份 sha256 哈希用于校验和比对;canonical_json
负责把对象序列化成稳定形式,保证同一对象每次得到相同哈希。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    """把对象序列化成稳定 JSON 字符串，用于对象级 hash。

    参数:
        obj: 任意可被 json 序列化的对象。
    返回:
        排序键、去多余空白后的紧凑 JSON 字符串(保证同一对象输出一致)。
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    """计算文本的 sha256 十六进制摘要。

    参数:
        text: 待哈希的字符串。
    返回:
        64 位十六进制 sha256 字符串。
    """
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sha256_obj(obj: Any) -> str:
    """先把对象规范化为稳定 JSON,再计算其 sha256。

    参数:
        obj: 任意可序列化对象。
    返回:
        对象内容的 sha256 十六进制摘要。
    """
    return sha256_text(canonical_json(obj))


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """按块读取文件并计算 sha256，避免大文件一次性读入内存。

    参数:
        path:       文件路径。
        chunk_size: 每次读取的字节数(默认 1 MB)。
    返回:
        文件内容的 sha256 十六进制摘要。
    """
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        # iter(callable, sentinel):反复读到返回空字节串为止。
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(text: str, length: int = 12) -> str:
    """取文本 sha256 的前若干位作为短哈希(用于生成稳定短 id)。

    参数:
        text:   待哈希的字符串。
        length: 截取长度(默认 12)。
    返回:
        长度为 length 的十六进制短哈希。
    """
    return sha256_text(text)[:length]
