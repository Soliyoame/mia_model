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

from ..utils.hash import short_hash


ATTACK_FIRST_GENERATION_PROTOCOL = "v6_3_attack_first_counterfactual_rc2"

# 下面几组是"候选替换库":当要替换地点/人名/机构/产品/项目名时，从这里挑一个不同的。
# 库适当扩大,配合 _candidate_replacement 的哈希选择,让不同原值落到不同假值、跨文档不雷同
# (固定且过小的库会使反事实高度重复,容易被模型先验识破,从而抬高 cvg_llm 假阳性)。
LOCATION_CANDIDATES = [
    "California",
    "Texas",
    "New York",
    "London",
    "Canada",
    "Germany",
    "Singapore",
    "Tokyo",
    "Sydney",
    "Toronto",
    "Paris",
    "Dublin",
]
DEFINITE_ARTICLE_LOCATION_CANDIDATES = [
    "United Kingdom",
    "United Arab Emirates",
    "Netherlands",
    "Philippines",
]
PERSON_CANDIDATES = [
    "Jordan Ellis",
    "Taylor Morgan",
    "Alex Carter",
    "Morgan Lee",
    "Casey Brooks",
    "Riley Bennett",
    "Avery Sinclair",
    "Dakota Reyes",
    "Quinn Harper",
    "Sawyer Bishop",
]
ORG_CANDIDATES = [
    "Orion Services Inc",
    "Northstar Logistics LLC",
    "Harborview Group",
    "Summit Data Corp",
    "Cedarline Partners",
    "Vanta Industries",
    "Brightpeak Holdings",
    "Ironwood Associates",
]
PRODUCT_CANDIDATES = [
    "Atlas Platform",
    "Beacon System",
    "Meridian Service",
    "Nova Device",
    "Helix Suite",
    "Quanta Engine",
    "Lumen Toolkit",
    "Vertex Console",
]
PROJECT_CANDIDATES = [
    "Project Atlas",
    "Project Beacon",
    "Program Meridian",
    "Initiative Nova",
    "Project Helix",
    "Program Vega",
    "Initiative Lumen",
    "Project Vertex",
]

_DEFINITE_ARTICLE_LOCATIONS = frozenset(
    {
        "bahamas",
        "czech republic",
        "european economic area",
        "european union",
        "gambia",
        "middle east",
        "netherlands",
        "nordic region",
        "philippines",
        "u.s.",
        "united arab emirates",
        "united kingdom",
        "united states",
        "united states of america",
    }
)
_COUNTRY_LOCATIONS = frozenset(
    {
        "australia",
        "brazil",
        "canada",
        "china",
        "czech republic",
        "france",
        "germany",
        "india",
        "ireland",
        "italy",
        "japan",
        "korea",
        "malaysia",
        "mexico",
        "netherlands",
        "peru",
        "philippines",
        "singapore",
        "spain",
        "u.s.",
        "united arab emirates",
        "united kingdom",
        "united states",
        "united states of america",
    }
)
_STATE_OR_PROVINCE_LOCATIONS = frozenset(
    {
        "british columbia",
        "california",
        "colorado",
        "florida",
        "missouri",
        "new jersey",
        "ontario",
        "quebec",
        "sabah",
        "texas",
    }
)
_CITY_LOCATIONS = frozenset(
    {
        "abu dhabi",
        "austin",
        "boston",
        "dallas",
        "dublin",
        "dubai",
        "houston",
        "jeddah",
        "kota kinabalu",
        "lawrence",
        "london",
        "manhattan",
        "montreal",
        "paris",
        "sydney",
        "tokyo",
        "toronto",
        "xuzhou city",
    }
)
_REGION_LOCATIONS = frozenset(
    {
        "africa",
        "asia",
        "asia-pacific region",
        "europe",
        "european economic area",
        "european union",
        "latin america",
        "middle east",
        "nordic region",
    }
)
_ATTACK_LOCATION_CANDIDATES: dict[str, list[str]] = {
    "country": ["Canada", "Germany", "Australia", "France"],
    "country_definite": [
        "United Kingdom",
        "United Arab Emirates",
        "Netherlands",
        "Philippines",
    ],
    "state_or_province": ["Texas", "California", "Ontario", "Florida"],
    "city": ["Tokyo", "Paris", "Dublin", "Toronto"],
    "city_explicit": [
        "Suzhou City",
        "Quebec City",
        "Kansas City",
        "Panama City",
    ],
    "region": ["Europe", "Asia", "Africa", "Latin America"],
    "region_definite": [
        "European Economic Area",
        "Middle East",
        "Asia-Pacific region",
        "Nordic region",
    ],
    "compound_location": [
        "Austin, Texas",
        "Toronto, Canada",
        "Dublin, Ireland",
        "Sydney, Australia",
    ],
}
_ATTACK_PRODUCT_CANDIDATES: dict[str, list[str]] = {
    "drug_or_biologic": [
        "Velunatide",
        "Nexorimab",
        "Somarelin",
        "Talveradine",
    ],
    "lab_kit_or_reagent": [
        "Quantiva RNA Kit",
        "BioTrace Cytokine Array",
        "LuminaGreen Dye",
        "GenePure RT Kit",
    ],
    "device_or_instrument": [
        "Axion SP7",
        "NovaSeq 3500",
        "Metrica IMU X2",
        "OptiScan 500",
    ],
    "software_or_system": [
        "Orion OS 11",
        "Meridian Analytics Suite",
        "Atlas Control System",
        "Beacon Platform",
    ],
    "service_or_plan": [
        "Horizon Advantage Plan",
        "Northstar Tax Service",
        "Meridian Water Services",
        "Summit Care Plan",
    ],
    "consumer_or_industrial_product": [
        "Harbor Overnighter Bag",
        "Cedar Color Stain",
        "Atlas Worklight",
        "Northstar Filter",
    ],
}
_PRODUCT_VALUE_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "lab_kit_or_reagent",
        re.compile(
            r"\b(?:kit|toolkit|reagent|assay|array|cytokine|sybr|quantitect|dye)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "device_or_instrument",
        re.compile(
            r"\b(?:device|instrument|microscope|sequencer|notebook|computer|"
            r"imu|sensor|analy[sz]er|console|scanner|hiseq|leica\s+sp\d+|"
            r"presario)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "software_or_system",
        re.compile(
            r"\b(?:windows|software|platform|operating system|analytics suite|"
            r"paging system|control system)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "service_or_plan",
        re.compile(
            r"\b(?:service|services|advantage|insurance plan|premium plan|"
            r"franchise)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "consumer_or_industrial_product",
        re.compile(
            r"\b(?:bag|worklight|filter|industrial product|color stain)\b",
            re.IGNORECASE,
        ),
    ),
)
_PRODUCT_CONTEXT_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "drug_or_biologic",
        re.compile(
            r"\b(?:drug|medication|therap(?:y|eutic)|human growth hormone|"
            r"vaccine|dose|pharmaceutical|treatment of|clinical candidate)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "lab_kit_or_reagent",
        re.compile(
            r"\b(?:pcr|rna|dna|plasma samples?|analytes?|laboratory reagent|"
            r"intercalating dye|reverse transcription)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "device_or_instrument",
        re.compile(
            r"\b(?:microscopy|sequencing was carried out|desktop computer|"
            r"measurements? were taken|sensor data|confocal)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "software_or_system",
        re.compile(
            r"\b(?:installed|software|operating system|application suite|"
            r"developers?|switches)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "service_or_plan",
        re.compile(
            r"\b(?:premium revenues?|service lines?|monthly service|"
            r"franchise|risk adjustment payment)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "consumer_or_industrial_product",
        re.compile(
            r"\b(?:special offer|rebate|per yd|per lb|retail product)\b",
            re.IGNORECASE,
        ),
    ),
)


def requires_definite_article(value: str) -> bool:
    """Return whether a bare location name normally uses an external ``the``."""

    compact = " ".join((value or "").casefold().split())
    return compact in _DEFINITE_ARTICLE_LOCATIONS


def infer_attack_subtype(
    value: str,
    entity_type: str,
    *,
    context: str | None = None,
) -> str | None:
    """Infer only coarse subtypes whose mismatch creates an obvious shortcut."""

    compact = " ".join((value or "").casefold().split())
    kind = (entity_type or "").upper()
    if kind == "LOCATION":
        if "," in compact:
            return "compound_location"
        if compact.endswith(" city"):
            return "city_explicit"
        if compact in _COUNTRY_LOCATIONS:
            return "country"
        if compact in _STATE_OR_PROVINCE_LOCATIONS:
            return "state_or_province"
        if compact in _CITY_LOCATIONS:
            return "city"
        if compact in _REGION_LOCATIONS:
            return "region"
        return None
    if kind != "PRODUCT":
        return None

    for subtype, pattern in _PRODUCT_VALUE_CUES:
        if pattern.search(compact):
            return subtype
    context_text = " ".join((context or "").casefold().split())
    for subtype, pattern in _PRODUCT_CONTEXT_CUES:
        if pattern.search(context_text):
            return subtype
    return None


def _attack_location_pool(value: str, subtype: str) -> list[str] | None:
    if subtype == "country":
        key = "country_definite" if requires_definite_article(value) else "country"
        return _ATTACK_LOCATION_CANDIDATES[key]
    if subtype == "region":
        key = "region_definite" if requires_definite_article(value) else "region"
        return _ATTACK_LOCATION_CANDIDATES[key]
    return _ATTACK_LOCATION_CANDIDATES.get(subtype)


SEMANTIC_SUBTYPE_CANDIDATES = {
    "initialed_person_name": ["J. Ellis", "T. Morgan", "A. Carter", "R. Bennett"],
    "titled_person_name": ["Dr. Jordan Ellis", "Prof. Taylor Morgan", "Dr. Alex Carter"],
    "single_person_name": ["Jordan", "Taylor", "Morgan", "Riley", "Avery"],
    "multi_token_person_name": PERSON_CANDIDATES,
    "corporate_organization": [
        "Orion Services Inc",
        "Northstar Logistics LLC",
        "Summit Data Corp",
        "Vanta Industries Ltd",
    ],
    "academic_or_medical_organization": [
        "Northbridge University",
        "Harborview Medical Institute",
        "Cedarline Research Hospital",
        "Summit Technical College",
    ],
    "government_organization": [
        "Northland Regulatory Commission",
        "Westbridge Public Health Agency",
        "Cedar State Department",
        "Harbor County Authority",
    ],
    "named_organization": ORG_CANDIDATES,
    "compound_geographic_location": [
        "Austin, Texas",
        "Toronto, Canada",
        "Dublin, Ireland",
        "Sydney, Australia",
    ],
    "definite_article_location": DEFINITE_ARTICLE_LOCATION_CANDIDATES,
    "named_geographic_location": LOCATION_CANDIDATES,
    "versioned_or_numbered_product": [
        "Atlas 4",
        "Beacon X2",
        "Meridian 7",
        "Nova 3",
    ],
    "software_or_service_product": [
        "Atlas Platform",
        "Beacon Service",
        "Meridian Software",
        "Nova Suite",
    ],
    "named_product": PRODUCT_CANDIDATES,
    "acronym_project_name": ["ATLAS", "BEACON", "MERIDIAN", "NOVA"],
    "titled_project_name": PROJECT_CANDIDATES,
    "named_agreement": [
        "Northstar Services Agreement",
        "Harborview License Agreement",
        "Cedarline Supply Contract",
        "Summit Facility Lease",
    ],
    "contractual_plan_or_policy": [
        "Northstar Incentive Plan",
        "Harborview Retention Plan",
        "Cedarline Compensation Policy",
        "Summit Benefit Plan",
    ],
    "defined_contract_term": [
        "Renewal Period",
        "Termination Event",
        "Permitted Transfer",
        "Notice Period",
    ],
}
CONTRACT_TERM_REPLACEMENTS = {
    "effective date": "expiration date",
    "expiration date": "effective date",
    "termination": "renewal",
    "renewal": "termination",
    "confidentiality": "non-disclosure",
    "non-disclosure": "confidentiality",
    "indemnification": "warranty",
    "indemnity": "warranty",
    "warranty": "indemnification",
    "governing law": "choice of law",
    "choice of law": "governing law",
    "assignment": "delegation",
    "delegation": "assignment",
    "liability": "indemnity",
    "payment term": "license term",
    "license term": "payment term",
}


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
    shifted = max(1.0, number * factor)
    # 扰动方向:factor>=1 往大改,否则往小改;在"舍入后又变回原值"时用来强制偏移一格。
    direction = 1 if factor >= 1.0 else -1
    # 原数有小数就保留两位小数格式,否则按整数(带千分位)渲染。
    if "." in raw:
        new_number = round(shifted, 2)
        # 小值乘以接近 1 的 factor,两位小数舍入后可能等于原值(如 0.01*1.05→0.01)。
        # 这会让反事实==真值而被上游丢弃,故强制至少偏移 0.01。
        if new_number == round(number, 2):
            new_number = round(number + direction * 0.01, 2)
        new_number = max(0.01, new_number)
        rendered = f"{new_number:,.2f}"
    else:
        # 整数同理:Python round 是银行家舍入,10*1.05=10.5→round→10、2*1.25=2.5→round→2,
        # 小整数会原地不动。检测到没变就强制 ±1,确保一定产生同类型的不同值。
        new_int = int(round(shifted))
        if new_int == int(number):
            new_int = int(number) + direction
        new_int = max(1, new_int)
        rendered = f"{new_int:,}"
    # 把新数字拼回原字符串中数字所在的位置(前缀 + 新数 + 后缀)。
    return value[: match.start()] + rendered + value[match.end() :]


def _shift_year(value: str, amount: int) -> str:
    """Shift a four-digit year without introducing thousands separators."""

    stripped = value.strip()
    if re.fullmatch(r"(?:19|20)\d{2}", stripped) is None:
        return _shift_number(value, 1.05)
    year = int(stripped) + amount
    if year > 2099:
        year = int(stripped) - amount
    return str(year)


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
    shifted = _shift_number(value, factor)
    number_match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", shifted)
    unit_match = re.search(r"\b(minutes?|hours?|days?|weeks?|months?|years?|quarters?)\b", shifted, re.IGNORECASE)
    if number_match is None or unit_match is None:
        return shifted
    number = float(number_match.group(0).replace(",", ""))
    unit = unit_match.group(0)
    singular = unit[:-1] if unit.casefold().endswith("s") else unit
    rendered_unit = singular if number == 1.0 else singular + "s"
    if unit[:1].isupper():
        rendered_unit = rendered_unit[:1].upper() + rendered_unit[1:]
    return shifted[: unit_match.start()] + rendered_unit + shifted[unit_match.end() :]


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

    用原值的稳定哈希来选,达到两个目的:
      (1) 不同原值映射到不同假值,跨文档不再雷同——固定取库里第一个会让所有 PERSON 反事实
          都变成同一个名字,模型容易凭先验识破,从而抬高 cvg_llm 假阳性;
      (2) 同一原值每次得到相同假值,确定可复现,不引入随机种子。

    参数:
        value:      原始值。
        candidates: 候选替换库。
        medium:     中等扰动时在哈希定位基础上再偏移一位,让替换差异更大。
    返回:
        一个与原值不同的候选;若候选都与原值相同则原样返回。
    """
    # 先排除与原值相同的候选(忽略大小写),保证一定换成不同的值。
    pool = [candidate for candidate in candidates if candidate.lower() != value.lower()]
    if not pool:
        return value
    # 用原值的稳定哈希定位,使不同原值落到不同候选(确定性、可复现)。
    idx = int(short_hash(value.lower()), 16) % len(pool)
    # medium 模式再偏移一位,扩大与原值的差异。
    if medium and len(pool) > 1:
        idx = (idx + 1) % len(pool)
    return pool[idx]


def _article_compatible_candidates(
    value: str,
    candidates: list[str],
    context: str | None,
) -> list[str]:
    """Keep a frozen external ``a``/``an`` frame grammatical when detectable."""

    if not context:
        return candidates
    match = re.search(re.escape(value), context, re.IGNORECASE)
    if match is None:
        return candidates
    article_match = re.search(r"\b(a|an)\s+$", context[: match.start()], re.IGNORECASE)
    if article_match is None:
        return candidates
    article = article_match.group(1).casefold()
    filtered: list[str] = []
    for candidate in candidates:
        first_letter = next(
            (
                character.casefold()
                for character in candidate
                if character.isalpha()
            ),
            "",
        )
        if not first_letter:
            continue
        vowel_initial = first_letter in {"a", "e", "i", "o", "u"}
        if (article == "an" and vowel_initial) or (
            article == "a" and not vowel_initial
        ):
            filtered.append(candidate)
    return filtered or candidates


def perturb_entity_value(
    value: str,
    entity_type: str,
    level: str = "light",
    *,
    semantic_subtype_name: str | None = None,
    context: str | None = None,
) -> str:
    """Generate a same-type counterfactual value for a fact entity.

    中文说明：本文件的总入口。根据实体类型，调用对应的扰动函数，生成一个"同类型但不同
    内容"的假值。这是构造反事实声明 Q- 的关键一步。

    参数:
        value:       原始实体值。
        entity_type: 实体类型(MONEY/DATE/EMAIL/PERSON/ORG... 等)。
        level:       扰动强度,"light"(默认)或 "medium"(改得更多)。
        semantic_subtype_name: v6.3 resolver 冻结的语义子型；提供时从对应池替换。
        context:      包含实体的完整 claim；仅用于判断明显 LOCATION/PRODUCT 大类。
    返回:
        同类型的反事实假值;未知类型则在原值后加 " revised" 兜底。
    """
    # medium 标志:是否使用更大的扰动幅度。
    medium = level == "medium"
    kind = (entity_type or "").upper()
    attack_subtype = infer_attack_subtype(
        value,
        kind,
        context=context,
    )
    if kind == "LOCATION" and attack_subtype is not None:
        location_pool = _attack_location_pool(value, attack_subtype)
        if location_pool:
            return _candidate_replacement(
                value,
                _article_compatible_candidates(value, location_pool, context),
                medium,
            )
    if kind == "PRODUCT" and attack_subtype is not None:
        product_pool = _ATTACK_PRODUCT_CANDIDATES.get(attack_subtype)
        if product_pool:
            return _candidate_replacement(
                value,
                _article_compatible_candidates(value, product_pool, context),
                medium,
            )

    subtype_pool = SEMANTIC_SUBTYPE_CANDIDATES.get(
        str(semantic_subtype_name or "")
    )
    if subtype_pool:
        return _candidate_replacement(
            value,
            _article_compatible_candidates(value, subtype_pool, context),
            medium,
        )
    # —— 按实体类型分派到对应的扰动逻辑 ——
    if entity_type == "NUMERIC_VALUE" and re.fullmatch(r"(?:19|20)\d{2}", value.strip()):
        return _shift_year(value, 2 if medium else 1)
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
        # 按合同语义子类替换，避免把 liability/confidentiality 一律改成 renewal。
        compact = " ".join(value.casefold().split())
        replacement = CONTRACT_TERM_REPLACEMENTS.get(compact)
        if replacement is not None:
            return replacement
        return "renewal" if compact != "renewal" else "termination"
    if entity_type == "LOCATION":
        article_class = requires_definite_article(value)
        candidates = DEFINITE_ARTICLE_LOCATION_CANDIDATES if article_class else LOCATION_CANDIDATES
        return _candidate_replacement(
            value,
            _article_compatible_candidates(value, candidates, context),
            medium,
        )
    if entity_type == "PERSON":
        return _candidate_replacement(
            value,
            _article_compatible_candidates(value, PERSON_CANDIDATES, context),
            medium,
        )
    if entity_type == "ORG":
        # 机构字段里若其实是邮箱,按邮箱方式扰动。
        if "@" in value:
            return _perturb_email(value)
        return _candidate_replacement(
            value,
            _article_compatible_candidates(value, ORG_CANDIDATES, context),
            medium,
        )
    if entity_type == "PRODUCT":
        return _candidate_replacement(
            value,
            _article_compatible_candidates(value, PRODUCT_CANDIDATES, context),
            medium,
        )
    if entity_type == "PROJECT_NAME":
        return _candidate_replacement(
            value,
            _article_compatible_candidates(value, PROJECT_CANDIDATES, context),
            medium,
        )
    # 未知类型的兜底:加一个 " revised" 后缀,至少保证值发生了变化。
    return value + " revised"
