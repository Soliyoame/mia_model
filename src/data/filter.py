"""Entity-density filters used during PCV-MIA preprocessing.

中文说明
========
本文件用一组正则表达式来"识别文本里有哪些关键实体"(金额、日期、百分比、机构名、
邮箱、医疗数值、合同条款、数字)，并据此做筛选。

为什么重要：PCV-MIA 的攻击是"把关键实体换成假的"来构造反事实声明。如果一段文本里
没有可替换的实体，就没法对它做攻击。所以预处理时要靠本文件把"实体太少、或像模板/
免责声明"的片段筛掉，只保留"实体丰富、适合攻击"的样本。
"""

from __future__ import annotations

import re


# ===== 下面每个正则负责识别一类"实体"。注释说明它在匹配什么样的文本。=====
# 数字:如 123、1,000、3.14 。
NUMERIC_RE = re.compile(r"\b\d+(?:[,.]\d+)*(?:\.\d+)?\b")
# 日期:如 "January 5, 2020"、"01/05/2020"、"2020-01-05" 等多种写法。
DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{2,4}\b|"
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
    re.IGNORECASE,
)
# 金额:如 "$1,200.50"、"5 million dollars"、"100 USD"。
MONEY_RE = re.compile(
    r"(?:[$]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|dollars|million|billion)\b)",
    re.IGNORECASE,
)
# 百分比:如 "12%"、"3.5 percent"。
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d+(?:\.\d+)?\s?percent\b", re.IGNORECASE)
# 机构名:以大写词开头、并以 Inc/Corp/LLC/Bank/University 等后缀结尾的名称。
ORG_RE = re.compile(
    r"\b[A-Z][A-Za-z&.,'-]*(?:\s+[A-Z][A-Za-z&.,'-]*){0,5}\s+"
    r"(?:Inc|Corp|Corporation|LLC|Ltd|Limited|Company|Co|Bank|Group|University|Hospital|Agency|Department)\b"
)
# 邮箱地址。
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# 医疗数值:如 "500 mg"、"120 mmHg"、"30 patients"。
MEDICAL_VALUE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|g|kg|ml|mL|mmHg|bpm|IU|days?|weeks?|months?|years?|patients?|cases?)\b",
    re.IGNORECASE,
)
# 合同条款关键词:如 "effective date"、"termination"、"governing law"。
CONTRACT_TERM_RE = re.compile(
    r"\b(?:effective date|termination|renewal|confidentiality|indemnification|governing law|"
    r"non-disclosure|assignment|liability|warranty|payment term|license term)\b",
    re.IGNORECASE,
)
# 模板/套话:如 "all rights reserved"、"for informational purposes only" 等免责声明类文字。
TEMPLATE_RE = re.compile(
    r"\b(?:all rights reserved|forward-looking statements|not intended to provide medical advice|"
    r"for informational purposes only|copyright|terms and conditions apply|safe harbor statement|"
    r"this communication may contain privileged|confidential information)\b",
    re.IGNORECASE,
)

# 把"实体名 → 对应正则"集中成一个字典,方便统一遍历。
ENTITY_PATTERNS = {
    "money": MONEY_RE,
    "date": DATE_RE,
    "percent": PERCENT_RE,
    "org": ORG_RE,
    "email": EMAIL_RE,
    "medical_value": MEDICAL_VALUE_RE,
    "contract_term": CONTRACT_TERM_RE,
    "numeric": NUMERIC_RE,
}


def entity_signals(text: str) -> dict[str, bool]:
    """对每类实体返回"文本里是否至少出现过一次"(布尔)。

    参数:
        text: 待检查文本。
    返回:
        {实体名: 是否出现} 的字典。
    """
    # search 命中即为 True;只关心"有没有",不关心数量。
    return {name: bool(pattern.search(text or "")) for name, pattern in ENTITY_PATTERNS.items()}


def entity_signal_counts(text: str) -> dict[str, int]:
    """对每类实体返回"在文本里出现了几次"(计数)。

    参数:
        text: 待检查文本。
    返回:
        {实体名: 出现次数} 的字典。
    """
    # findall 找出所有匹配,取其个数。
    return {name: len(pattern.findall(text or "")) for name, pattern in ENTITY_PATTERNS.items()}


def _perturbable_count(counts: dict[str, int]) -> int:
    """从已算好的 entity counts 推导可扰动实体数，避免重复跑正则。

    "可扰动实体"指能被替换成假值来构造反事实的实体。这里优先数"具体类型"(金额/日期/
    机构等),因为它们替换后更自然;只有当一个具体实体都没有时,才退而用泛化的 numeric 计数。

    参数:
        counts: entity_signal_counts 的结果。
    返回:
        可扰动实体的数量。
    """
    # 把除 numeric 之外的所有具体类型计数相加。
    specific = sum(count for name, count in counts.items() if name != "numeric")
    # 有具体实体就用具体计数;否则退回用 numeric 计数兜底。
    return specific if specific else counts.get("numeric", 0)


def perturbable_entity_count(text: str) -> int:
    """直接对一段文本计算"可扰动实体数"(内部会先跑一遍计数正则)。"""
    return _perturbable_count(entity_signal_counts(text))


def entity_density(text: str) -> float:
    """计算"实体密度" = 可扰动实体数 / 词数。密度越高越适合做攻击样本。

    参数:
        text: 待评估文本。
    返回:
        实体密度(保留 6 位小数)。
    """
    # 词数至少算 1,避免除以 0。
    token_count = max(1, len((text or "").split()))
    return round(perturbable_entity_count(text) / token_count, 6)


def metadata_for_text(text: str) -> dict[str, object]:
    """为一段文本生成"实体相关的元信息"(供预处理记录与后续筛选/分析使用)。

    参数:
        text: 文本片段。
    返回:
        含长度、各类实体是否存在、实体计数、实体密度等字段的字典。
    """
    # 只跑一次 findall；signals 由 counts 推导（count>0 等价于 search 命中），
    # 省去原先额外的一整组 search 以及多次重复的 findall。
    counts = entity_signal_counts(text)
    signals = {name: count > 0 for name, count in counts.items()}
    entity_count = _perturbable_count(counts)
    token_count = max(1, len((text or "").split()))
    return {
        "length": len(text or ""),
        "has_money": signals["money"],
        "has_date": signals["date"],
        # 机构或邮箱任一出现都算"有机构类实体"。
        "has_org": signals["org"] or signals["email"],
        "has_percent": signals["percent"],
        "has_medical_value": signals["medical_value"],
        "has_contract_term": signals["contract_term"],
        "entity_count": entity_count,
        "entity_counts": counts,
        "entity_density": round(entity_count / token_count, 6),
    }


def is_template_like(text: str) -> bool:
    """判断一段文本是否"像模板/套话"(从而应被丢弃)。

    两种判定:(1) 命中模板套话且可扰动实体很少(<2);(2) 重复行占比过高(>40%)。

    参数:
        text: 待判断文本。
    返回:
        像模板返回 True。
    """
    # 把所有空白压成单空格,得到单行形式。
    stripped = " ".join((text or "").split())
    # 空文本视为模板(无价值)。
    if not stripped:
        return True
    # 命中免责声明类套话,且几乎没有可扰动实体 → 判为模板。
    if TEMPLATE_RE.search(stripped) and perturbable_entity_count(stripped) < 2:
        return True
    # 取所有非空行(转小写)。
    lines = [line.strip().lower() for line in (text or "").splitlines() if line.strip()]
    # 行数太少不足以判断重复,直接认为不是模板。
    if len(lines) < 6:
        return False
    # 统计有多少行是"之前出现过的重复行"。
    seen: set[str] = set()
    repeated_lines = 0
    for line in lines:
        if line in seen:
            repeated_lines += 1
        seen.add(line)
    # 重复行占比超过 40% → 判为模板(如自动生成的列表/表单)。
    return repeated_lines / max(1, len(lines)) > 0.4


def contains_required_entity(text: str, require_numeric: bool = False) -> bool:
    """判断文本是否含有"必需的实体"(用于预处理过滤)。

    参数:
        text:            待判断文本。
        require_numeric: 为 True 时,必须含有数字类实体才算通过。
    返回:
        满足要求返回 True。
    """
    signals = entity_signals(text)
    # 要求必须有数字却没有 → 不通过。
    if require_numeric and not signals["numeric"]:
        return False
    # 只要任意一类实体出现即通过。
    return any(signals.values())


def has_min_perturbable_entities(text: str, min_entities: int = 2) -> bool:
    """判断文本的可扰动实体数是否达到下限(默认至少 2 个)。

    参数:
        text:         待判断文本。
        min_entities: 可扰动实体数量下限。
    返回:
        达到下限返回 True。
    """
    return perturbable_entity_count(text) >= min_entities
