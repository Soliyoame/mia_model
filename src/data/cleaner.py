"""文本清洗模块。

负责把不同来源的数据统一清理成适合切分和实体抽取的纯文本。

中文说明
========
本文件负责"洗数据"：原始文本里常夹杂 HTML 标签、控制字符、邮件头、转发分隔线、
签名、参考文献等噪声。这些东西要么没意义，要么实体很多但不是正文，会污染后续的
攻击样本。本文件按数据集类型选用不同清洗策略，把文本洗成干净的纯文本。
原则是"保守清洗"——宁可少删，也不能误删正文里真正的金额、日期、机构名等关键实体。
"""

from __future__ import annotations

import html
import re


# 下面是一组用于"识别噪声"的正则。各自匹配的内容见行内注释。
HTML_TAG_RE = re.compile(r"<[^>]+>")                          # 形如 <p>、<div> 的 HTML 标签
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # 不可见控制字符
SPACE_RE = re.compile(r"[ \t\r\f\v]+")                        # 连续的空格/制表符等(不含换行)
NEWLINE_RE = re.compile(r"\n{3,}")                            # 3 个及以上连续换行
EMAIL_HEADER_RE = re.compile(                                 # 邮件/MIME/X-* 技术头行
    r"^(?:(?:from|to|cc|bcc|subject|date|sent|received|return-path|reply-to|sender|"
    r"delivered-to|message-id|mime-version|content-type|content-transfer-encoding|"
    r"content-disposition)|x-[a-z0-9-]+):[^\n]*$",
    re.IGNORECASE | re.MULTILINE,                             # 多行模式,逐行匹配行首
)
FORWARD_NOISE_RE = re.compile(                               # 只删转发分隔行，绝不能吞掉后续正文
    r"^[ \t>]*[-_]{2,}[^\n]*(?:forwarded by|original message|forwarded message)[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
SIGNATURE_RE = re.compile(r"\n--\s*\n.*$", re.DOTALL)        # 邮件签名分隔线 "\n-- \n" 及之后内容
REFERENCES_RE = re.compile(r"\n\s*(?:references|bibliography)\s*\n.*$", re.IGNORECASE | re.DOTALL)  # 参考文献段及之后
PUBMED_TEMPLATE_RE = re.compile(                             # PubMed 论文里的套话/模板句
    r"\b(?:background:?\s*)?(?:the purpose of this study|further studies are needed|"
    r"more research is needed|this article is protected by copyright)\b",
    re.IGNORECASE,
)

ENRON_CLEANER_VERSION = "enron_cleaner_v2_preserve_forwarded_body"


def cleaner_version_for_dataset(dataset: str) -> str | None:
    """Return a version only for cleaners whose resume identity is frozen."""

    return ENRON_CLEANER_VERSION if (dataset or "").casefold() == "enron" else None


def clean_text(text: str) -> str:
    """去除 HTML、控制字符和异常空白，保留段落结构。

    这是"通用清洗",所有数据集最后都会走这一步。

    参数:
        text: 待清洗文本(可能为 None)。
    返回:
        清洗后的纯文本(段落之间最多保留一个空行)。
    """
    # 把 &amp; &lt; 这类 HTML 转义还原成 & < 等真实字符。
    text = html.unescape(text or "")
    # 去掉 HTML 标签(替换成空格,避免相邻词粘连)。
    text = HTML_TAG_RE.sub(" ", text)
    # 去掉不可见控制字符。
    text = CONTROL_RE.sub(" ", text)
    # 把不间断空格( )、BOM 字符(﻿)都换成普通空格。
    text = text.replace(" ", " ")
    text = text.replace("﻿", " ")
    # 连续空白压成一个空格。
    text = SPACE_RE.sub(" ", text)
    # 去掉换行两侧多余空格,让换行更干净。
    text = re.sub(r" *\n *", "\n", text)
    # 3 个以上连续换行压成 2 个(即最多隔一个空行)。
    text = NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def clean_enron_text(text: str) -> str:
    """Enron 邮件专用清洗。

    邮件 header、转发分隔符和签名会造成很多模板噪声；这里先粗清洗这些部分，
    再调用通用 clean_text。保守处理，避免误删正文里的交易金额、日期、机构名。

    参数:
        text: 原始邮件文本。
    返回:
        清洗后的邮件正文。
    """
    # 依次去掉转发噪声、邮件头、签名,再做通用清洗。
    text = FORWARD_NOISE_RE.sub(" ", text or "")
    text = EMAIL_HEADER_RE.sub(" ", text)
    text = SIGNATURE_RE.sub(" ", text)
    return clean_text(text)


def clean_pubmed_text(text: str) -> str:
    """PubMed/PMC 文本专用清洗。

    参考文献列表通常实体很多但不是候选样本正文，会污染攻击 benchmark；
    因此尽量截掉 References/Bibliography 之后的内容。

    参数:
        text: 原始论文文本。
    返回:
        清洗后的论文正文。
    """
    # 截掉参考文献段,并去掉常见套话。
    text = REFERENCES_RE.sub(" ", text or "")
    text = PUBMED_TEMPLATE_RE.sub(" ", text)
    return clean_text(text)


def clean_dataset_text(dataset: str, text: str) -> str:
    """按数据集选择清洗策略。

    参数:
        dataset: 数据集名(enron / pubmed / pmc / 其它)。
        text:    原始文本。
    返回:
        用对应策略清洗后的文本;未知数据集走通用清洗。
    """
    dataset = (dataset or "").lower()
    if dataset == "enron":
        return clean_enron_text(text)
    if dataset in {"pubmed", "pmc"}:
        return clean_pubmed_text(text)
    return clean_text(text)


def is_valid_text(text: str, min_chars: int = 200, max_chars: int = 3000) -> bool:
    """检查文本长度是否落在实验要求范围内。

    参数:
        text:      待检查文本。
        min_chars: 最小字符数。
        max_chars: 最大字符数。
    返回:
        长度在 [min_chars, max_chars] 内返回 True。
    """
    n = len(text.strip())
    return min_chars <= n <= max_chars
