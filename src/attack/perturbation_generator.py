"""Entity perturbation helpers for PCV-MIA paired claims.

中文说明
========
本文件负责"扰动(perturbation)"——把一个真实实体替换成【同类型但内容不同】的假值，
用来构造"反事实声明 Q-"。

关键设计:替换要"同类型、看起来一样真"。比如把金额改成另一个金额(而不是改成日期)，
把日期顺延几天(而不是乱写)。这样伪造声明才足够像真的，能有效考验模型"是真懂这份
文档、还是被表面合理的假信息骗过去"。
- level 参数控制扰动幅度:"light"(轻微,默认) vs "medium"(中等,改得更多)。
- 每类实体(金额/日期/时间/邮箱/电话/机构名...)都有对应的替换函数。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit


# 下面几组是"候选替换库":当要替换地点/人名/机构/产品/项目名时，从这里挑一个不同的。
LOCATION_CANDIDATES = ["California", "Texas", "New York", "London", "Canada", "Germany"]
PERSON_CANDIDATES = ["Jordan Ellis", "Taylor Morgan", "Alex Carter", "Morgan Lee", "Casey Brooks"]
ORG_CANDIDATES = ["Orion Services Inc", "Northstar Logistics LLC", "Harborview Group", "Summit Data Corp"]
PRODUCT_CANDIDATES = ["Atlas Platform", "Beacon System", "Meridian Service", "Nova Device"]
PROJECT_CANDIDATES = ["Project Atlas", "Project Beacon", "Program Meridian", "Initiative Nova"]


def _shift_number(value: str, factor: float) -> str:
    """Shift a numeric entity while preserving surrounding text.

    中文说明：把字符串里的数字按 factor 倍缩放，但保留数字前后的文字(如货币符号、单位)。
    例如 "$1,000" 乘 1.05 → "$1,050"。

    参数:
        value:  含数字的原始字符串。
        factor: 缩放倍数(如 1.05 表示放大 5%)。
    返回:
        替换数字后的字符串;找不到数字则原样返回。
    """
    # 找出第一个数字(支持千分位逗号和小数)。
    match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", value)
    if not match:
        return value
    raw = match.group(0)
    # 去掉逗号转成浮点数再缩放;至少为 1,避免出现 0 或负数。
    number = float(raw.replace(",", ""))
    shifted = max(1, number * factor)
    # 原数有小数就保留两位小数格式,否则按整数(带千分位)渲染。
    if "." in raw:
        rendered = f"{shifted:,.2f}"
    else:
        rendered = f"{int(round(shifted)):,}"
    # 把新数字拼回原字符串中数字所在的位置(前缀 + 新数 + 后缀)。
    return value[: match.start()] + rendered + value[match.end() :]


def _shift_date(value: str, days: int) -> str:
    """Shift parseable date entities by days.

    中文说明：把日期顺延 days 天，并尽量保持原来的日期写法。无法识别格式时，退回当作
    数字来扰动。

    参数:
        value: 日期字符串。
        days:  顺延的天数。
    返回:
        顺延后的日期字符串(沿用原格式);解析失败则按数字扰动。
    """
    # 依次尝试几种常见日期格式。
    formats = ["%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"]
    stripped = value.replace("  ", " ").strip()
    for fmt in formats:
        try:
            # 按该格式解析成日期对象。
            dt = datetime.strptime(stripped, fmt)
            # 加上天数后,再用同一格式还原成字符串。
            return (dt + timedelta(days=days)).strftime(fmt)
        except ValueError:
            continue
    # 所有格式都不匹配:退回当数字处理。
    return _shift_number(value, 1.05)


def _shift_time(value: str, minutes: int) -> str:
    """Shift common time formats while preserving a similar surface form.

    中文说明：把时间往后挪 minutes 分钟，尽量保持原来的时间写法(12小时制/24小时制等)。

    参数:
        value:   时间字符串(如 "3:00 PM"、"noon")。
        minutes: 往后挪多少分钟。
    返回:
        挪动后的时间字符串;无法解析则按数字扰动。
    """
    stripped = value.replace("  ", " ").strip()
    lowered = stripped.lower()
    # 特判 "noon"(中午)和 "midnight"(午夜)。
    if lowered == "noon":
        return "1:00 PM"
    if lowered == "midnight":
        return "1:00 AM"
    formats = ["%I:%M %p", "%I%p", "%I %p", "%H:%M"]
    # 统一成大写并压缩空白,便于按格式解析(%p 需要 AM/PM 大写)。
    normalized = re.sub(r"\s+", " ", stripped.upper())
    for fmt in formats:
        try:
            dt = datetime.strptime(normalized, fmt)
            shifted = dt + timedelta(minutes=minutes)
            # 24 小时制原样输出。
            if fmt == "%H:%M":
                return shifted.strftime("%H:%M")
            # 原文带冒号(有分钟) → 输出 "h:mm AM/PM"(去掉前导 0)。
            if ":" in normalized:
                return shifted.strftime("%I:%M %p").lstrip("0")
            # 挪动后产生了非零分钟 → 也带上分钟。
            if shifted.minute:
                return shifted.strftime("%I:%M %p").lstrip("0")
            # 否则只输出整点 "h AM/PM"。
            return shifted.strftime("%I %p").lstrip("0")
        except ValueError:
            continue
    return _shift_number(value, 1.10)


def _shift_duration(value: str, factor: float) -> str:
    """Shift a duration while keeping the original unit.

    中文说明：把时长按 factor 倍缩放、保留单位(如 "3 days" → "4 days")。直接复用数字扰动。

    参数:
        value:  时长字符串。
        factor: 缩放倍数。
    返回:
        缩放后的时长字符串。
    """
    return _shift_number(value, factor)


def _perturb_email(value: str) -> str:
    """Replace the local part while preserving the domain.

    中文说明：只改邮箱"@前面的用户名部分"，保留域名不变(看起来还是同一家公司的邮箱)。

    参数:
        value: 邮箱地址。
    返回:
        改了用户名的新邮箱;不像邮箱则在末尾加 ".alt"。
    """
    # 以 @ 切成 (用户名, "@", 域名)。
    local, sep, domain = value.partition("@")
    if not sep or not domain:
        return value + ".alt"
    # 用一个固定的替代用户名;若恰好和原来一样,就换另一个,确保产生了变化。
    replacement = "alternate.contact" if local.lower() != "alternate.contact" else "verified.contact"
    return f"{replacement}@{domain}"


def _perturb_url(value: str) -> str:
    """Change a URL path without changing it into a non-URL string.

    中文说明：改 URL 的"路径部分"，但保证结果仍然是个合法 URL(协议、域名不变)。

    参数:
        value: 原始 URL(可能没带 http(s):// 前缀)。
    返回:
        改了路径的新 URL,保持与原来相同的"带不带协议前缀"风格。
    """
    # 判断原文是否自带协议(如 https://)。
    has_scheme = bool(re.match(r"^[a-z][a-z0-9+.-]*://", value, re.IGNORECASE))
    # 解析 URL(没协议就临时补 https:// 以便解析)。
    parsed = urlsplit(value if has_scheme else f"https://{value}")
    path = parsed.path.rstrip("/")
    # 根据原路径情况，构造一个不同的新路径。
    if not path:
        path = "/archive"
    elif path.endswith("/archive"):
        path = path + "-v2"
    else:
        path = f"{path}/archive"
    # 重新拼回完整 URL。
    updated = urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))
    # 原文没带协议的话,把临时加的 https:// 去掉,保持风格一致。
    return updated if has_scheme else re.sub(r"^https://", "", updated)


def _bump_section_id(value: str, amount: int) -> str:
    """Bump the last numeric component in a section-like reference.

    中文说明：把"条款编号"里最后一个数字 +amount(如 "Section 3.2" → "Section 3.3")。

    参数:
        value:  形如 "Section 3.2" 的引用字符串。
        amount: 给最后一个数字加多少。
    返回:
        改了编号的字符串;没有数字则在末尾加 ".1"。
    """
    # 找出所有数字,取最后一个来改。
    matches = list(re.finditer(r"\d+", value))
    if not matches:
        return value + ".1"
    match = matches[-1]
    raw = match.group(0)
    # 若原数字带前导 0(如 "07"),加完后补齐到原来的位数,保持格式。
    bumped = str(int(raw) + amount).zfill(len(raw)) if raw.startswith("0") else str(int(raw) + amount)
    return value[: match.start()] + bumped + value[match.end() :]


def _perturb_identifier(value: str, amount: int) -> str:
    """Alter the final numeric component of a structured identifier.

    中文说明：改"结构化编号"(如订单号、案件号)末尾的数字;若没有数字,就改末尾的字母后缀。

    参数:
        value:  标识符字符串。
        amount: 给末尾数字加多少。
    返回:
        改动后的标识符。
    """
    # 优先改最后一个数字。
    matches = list(re.finditer(r"\d+", value))
    if matches:
        match = matches[-1]
        raw = match.group(0)
        bumped = str(int(raw) + amount).zfill(len(raw)) if raw.startswith("0") else str(int(raw) + amount)
        return value[: match.start()] + bumped + value[match.end() :]
    # 没有数字:改结尾的字母后缀(加 B,已是 B 则加 C)。
    match = re.search(r"[A-Za-z]+$", value)
    if match:
        suffix = match.group(0)
        replacement = suffix + "B" if not suffix.endswith("B") else suffix + "C"
        return value[: match.start()] + replacement + value[match.end() :]
    # 实在无处可改,末尾加 "-ALT"。
    return value + "-ALT"


def _perturb_phone(value: str, amount: int) -> str:
    """Change the subscriber number while preserving phone formatting.

    中文说明：改电话号码的"后四位"，但保留原来的格式(括号、连字符、空格都不动)。

    参数:
        value:  电话号码字符串。
        amount: 给后四位加多少(对 10000 取模,保证仍是四位)。
    返回:
        改了后四位的电话号码;位数太少则当数字扰动。
    """
    # 抽出所有数字。
    digits = re.sub(r"\D", "", value)
    # 位数太少不像电话,退回当数字处理。
    if len(digits) < 7:
        return _shift_number(value, 1.01)
    # 计算新的后四位(加 amount 后对 10000 取模,补齐 4 位)。
    last_four = digits[-4:]
    replacement = f"{(int(last_four) + amount) % 10000:04d}"
    digit_index = 0
    rendered = []
    # 逐字符重建:位于"后四位"范围内的数字替换成新值,其余字符(含格式符)原样保留。
    for char in value:
        if char.isdigit():
            rendered.append(replacement[digit_index - (len(digits) - 4)] if digit_index >= len(digits) - 4 else char)
            digit_index += 1
        else:
            rendered.append(char)
    return "".join(rendered)


def _candidate_replacement(value: str, candidates: list[str], medium: bool) -> str:
    """从候选库里挑一个"与原值不同"的替换项。

    参数:
        value:      原始值。
        candidates: 候选替换库。
        medium:     中等扰动时跳过第一个候选(从更靠后的项里挑),让替换差异更大。
    返回:
        一个与原值不同的候选;若都相同则原样返回。
    """
    # medium 模式下从第二个候选起选(差异更大),否则用全部候选。
    pool = candidates[1:] if medium and len(candidates) > 1 else candidates
    for candidate in pool:
        # 选第一个与原值不同的(忽略大小写)。
        if candidate.lower() != value.lower():
            return candidate
    return value


def perturb_entity_value(value: str, entity_type: str, level: str = "light") -> str:
    """Generate a same-type counterfactual value for a fact entity.

    中文说明：本文件的总入口。根据实体类型，调用对应的扰动函数，生成一个"同类型但不同
    内容"的假值。这是构造反事实声明 Q- 的关键一步。

    参数:
        value:       原始实体值。
        entity_type: 实体类型(MONEY/DATE/EMAIL/PERSON/ORG... 等)。
        level:       扰动强度,"light"(默认)或 "medium"(改得更多)。
    返回:
        同类型的反事实假值;未知类型则在原值后加 " revised" 兜底。
    """
    # medium 标志:是否使用更大的扰动幅度。
    medium = level == "medium"
    # —— 按实体类型分派到对应的扰动逻辑 ——
    if entity_type in {"MONEY", "MEDICAL_VALUE", "NUMERIC_VALUE"}:
        return _shift_number(value, 1.15 if medium else 1.05)
    if entity_type == "PERCENT":
        return _shift_number(value, 1.10 if medium else 1.05)
    if entity_type == "DATE":
        return _shift_date(value, 14 if medium else 3)
    if entity_type == "TIME":
        return _shift_time(value, 60 if medium else 30)
    if entity_type == "DURATION":
        return _shift_duration(value, 1.50 if medium else 1.25)
    if entity_type == "EMAIL":
        return _perturb_email(value)
    if entity_type == "URL":
        return _perturb_url(value)
    if entity_type == "PHONE":
        return _perturb_phone(value, 137 if medium else 29)
    if entity_type == "SECTION_ID":
        return _bump_section_id(value, 2 if medium else 1)
    if entity_type == "IDENTIFIER":
        return _perturb_identifier(value, 50 if medium else 7)
    if entity_type == "CONTRACT_TERM":
        # 合同条款:在 renewal(续约) 和 termination(终止) 之间互换。
        return "renewal" if value.lower() != "renewal" else "termination"
    if entity_type == "LOCATION":
        return _candidate_replacement(value, LOCATION_CANDIDATES, medium)
    if entity_type == "PERSON":
        return _candidate_replacement(value, PERSON_CANDIDATES, medium)
    if entity_type == "ORG":
        # 机构字段里若其实是邮箱,按邮箱方式扰动。
        if "@" in value:
            return _perturb_email(value)
        return _candidate_replacement(value, ORG_CANDIDATES, medium)
    if entity_type == "PRODUCT":
        return _candidate_replacement(value, PRODUCT_CANDIDATES, medium)
    if entity_type == "PROJECT_NAME":
        return _candidate_replacement(value, PROJECT_CANDIDATES, medium)
    # 未知类型的兜底:加一个 " revised" 后缀,至少保证值发生了变化。
    return value + " revised"
