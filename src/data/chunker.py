"""语义切分模块。

优先按段落和句子边界切分，避免把一个事实实体拆到不同片段里。

中文说明
========
本文件负责把一篇长文档切成若干"大小合适的片段(chunk)"。为什么要讲究切法：PCV-MIA
要针对片段里的"关键实体(如金额、日期)"构造攻击声明，如果把一句话从中间切断、或把
本属于一处的事实拆到两个片段，攻击就会失真。所以这里优先沿"段落→句子"的自然边界切，
实在太长才退而按字符硬切。
"""

from __future__ import annotations

import re
from typing import Iterable


# 句子切分正则：在 . ! ? 。！？ 这些句末标点【后面】的空白处断句。
# (?<=...) 是"后顾断言"，表示"前面得是这些标点"，但不把标点本身吃掉。
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


def _paragraphs(text: str) -> list[str]:
    """把文本拆成段落列表。

    切分规则:遇到"空行"(\\n\\n)，或"换行后紧跟大写字母/数字开头的新行"，都视为段落边界。
    最后去掉空白段。

    参数:
        text: 整篇文本。
    返回:
        去空后的段落字符串列表。
    """
    parts = re.split(r"\n\s*\n|(?:\n(?=[A-Z0-9]))", text)
    return [p.strip() for p in parts if p.strip()]


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """长段落按句子拆分；极长句子再按字符兜底切分。

    参数:
        paragraph: 一个(超过上限的)长段落。
        max_chars: 单个片段允许的最大字符数。
    返回:
        切好的片段列表。
    """
    # 先按句子切；去掉空句。
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(paragraph) if s.strip()]
    # 一句都切不出来(没有句末标点)：直接按 max_chars 等长硬切。
    if not sentences:
        return [paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars)]

    chunks: list[str] = []
    current: list[str] = []   # 当前正在累积的句子
    current_len = 0           # 当前累积长度
    for sent in sentences:
        # 单句就超长:先把已累积的收尾,再把这句按字符硬切。
        if len(sent) > max_chars:
            if current:
                chunks.append(" ".join(current).strip())
                current, current_len = [], 0
            chunks.extend(sent[i : i + max_chars] for i in range(0, len(sent), max_chars))
            continue
        # 再加这句会超上限:先收尾当前片段,这句作为新片段的开头。
        if current and current_len + len(sent) + 1 > max_chars:
            chunks.append(" ".join(current).strip())
            current, current_len = [sent], len(sent)
        else:
            # 否则把这句并入当前片段(+1 是预留的空格)。
            current.append(sent)
            current_len += len(sent) + 1
    # 收尾:把最后剩下的句子也作为一个片段。
    if current:
        chunks.append(" ".join(current).strip())
    return [c for c in chunks if c]


def chunk_text(text: str, min_chars: int = 200, max_chars: int = 3000, target_chars: int = 1000) -> list[str]:
    """把一篇文档切成适合攻击实验的片段。

    策略:逐段累积,接近 target_chars(目标大小)就收成一个片段;太短(< min_chars)的片段丢弃,
    太长则截到 max_chars。这样片段大小集中在目标值附近,既不过碎也不过长。

    参数:
        text:        整篇文档文本。
        min_chars:   片段最小字符数(更短则丢弃)。
        max_chars:   片段最大字符数(更长则截断)。
        target_chars:理想片段大小,累积到接近它就收尾。
    返回:
        满足 [min_chars, max_chars] 的片段列表。
    """
    chunks: list[str] = []
    current: list[str] = []   # 当前正在累积的段落片段
    current_len = 0

    for para in _paragraphs(text):
        # 段落不超长就整段用;超长则先拆成小块。
        para_parts = [para] if len(para) <= max_chars else _split_long_paragraph(para, max_chars)
        for part in para_parts:
            part_len = len(part)
            # 单块仍超 max_chars(理论上拆过后不会),保险起见跳过。
            if part_len > max_chars:
                continue
            # 再加这块会超过目标大小:先把当前累积收成一个片段(满足下限才保留)。
            if current and current_len + part_len + 2 > target_chars:
                joined = "\n\n".join(current).strip()
                if len(joined) >= min_chars:
                    chunks.append(joined[:max_chars])
                current, current_len = [], 0
            current.append(part)
            current_len += part_len + 2  # +2 是两段之间 "\n\n" 的长度

    # 收尾:处理最后剩下的累积内容。
    if current:
        joined = "\n\n".join(current).strip()
        if len(joined) >= min_chars:
            chunks.append(joined[:max_chars])
    # 最终再过滤一遍,确保每个片段长度都在合法区间内。
    return [c for c in chunks if min_chars <= len(c) <= max_chars]


def chunk_records(records: Iterable[tuple[str, str]], min_chars: int, max_chars: int, target_chars: int) -> Iterable[tuple[str, str]]:
    """批量切分记录，并为每个 chunk 生成稳定来源 id。

    参数:
        records:     (来源id, 文本) 元组的可迭代序列。
        min_chars/max_chars/target_chars: 同 chunk_text。
    产出(生成器):
        逐个产出 (新chunk_id, chunk文本);新 id 形如 "原id::chunk_0001",保证可追溯。
    """
    for source_id, text in records:
        for idx, chunk in enumerate(chunk_text(text, min_chars=min_chars, max_chars=max_chars, target_chars=target_chars)):
            # 用 :04d 把序号补成 4 位,便于排序与对齐。
            yield f"{source_id}::chunk_{idx:04d}", chunk
