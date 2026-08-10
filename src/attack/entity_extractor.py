"""Entity extraction for attackable PCV-MIA facts.

The extractor keeps regex rules as the high-precision backbone, accepts an
optional NER model as a recall-oriented candidate source, and selects final
entities with sentence quality, attackability scoring, and family diversity.

中文说明
========
本文件对应流水线第 06 步「抽取事实」里的核心:从一段文本里找出"最适合拿来做攻击的
关键实体"(如金额、日期、人名、机构、邮箱等)。

工作流程(三步走)：
    1. 产生候选：用一堆正则表达式高精度地找实体(主力)，可选地再用 NER(命名实体识别)
       模型补一些召回(配菜)。
    2. 合并候选：同一处被多种规则识别到时合并，重叠时保留优先级更高的。
    3. 打分筛选：给每个候选算一个"可攻击性(attackability)"分数(综合考虑这处实体重不重要、
       好不好替换、上下文质量等)，再过硬门槛、并按"实体家族(family)"配额挑选，保证多样性。

名词:
    - entity(实体)：文本里的关键信息单元，如 "$1,000"、"2020-01-05"。
    - family(家族)：把实体类型归成几大类(数字类/日期类/标识符类/命名实体类/领域术语类)，
      挑选时每类有配额，避免一篇文档全选同一类。
    - attackability(可攻击性)：这处实体拿来构造攻击声明的"性价比"评分。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    # 进度条;没装 tqdm 就用"原样返回"的替身。
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = lambda x, **_: x

# 复用 data.filter 里已经定义好的一批实体正则(金额、日期、邮箱、机构等)，避免重复造轮子。
from ..data.filter import CONTRACT_TERM_RE, DATE_RE, EMAIL_RE, MEDICAL_VALUE_RE, MONEY_RE, NUMERIC_RE, ORG_RE, PERCENT_RE, TEMPLATE_RE
from ..utils.io import read_jsonl, write_json, write_jsonl
from ..utils.logger import get_logger
from .entity_type_policy import SUPPORTED_ENTITY_TYPES


LOGGER = get_logger(__name__)


# ===== 本文件额外补充的一批实体正则(filter 里没有的类型)。注释说明各自匹配什么。=====
# 地点:一批常见国家/地区/城市名。
LOCATION_RE = re.compile(r"\b(?:New York|California|Texas|London|Paris|China|Japan|Germany|Canada|Europe|Asia|United States|U\.S\.)\b")
# 人名:可选称谓(Mr./Dr. 等) + 2~3 个首字母大写的词。
PERSON_RE = re.compile(r"\b(?:Mr\.|Ms\.|Mrs\.|Dr\.)?\s?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")
# 产品名:大写词组 + Platform/System/Product/Service/Drug/Device 之类后缀。
PRODUCT_RE = re.compile(r"\b[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*){0,3}\s+(?:Platform|System|Product|Service|Drug|Device)\b")
# 项目名:Project/Program/Initiative + 一个大写开头的名字。
PROJECT_NAME_RE = re.compile(r"\b(?:Project|Program|Initiative)\s+[A-Z][A-Za-z0-9-]+\b")
# 时间:如 "14:30"、"2:30 PM"、"9 AM"、"noon"、"midnight"。
TIME_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s?(?:AM|PM))?\b|\b(?:[1-9]|1[0-2])\s?(?:AM|PM)\b|\b(?:noon|midnight)\b",
    re.IGNORECASE,
)
# 时长:可选介词(for/within...) + 数字 + 单位(minutes/days/years...)。
DURATION_RE = re.compile(
    r"\b(?:for|within|over|after|before|during)?\s*\d+(?:\.\d+)?\s?"
    r"(?:minutes?|hours?|days?|weeks?|months?|years?|quarters?)\b",
    re.IGNORECASE,
)
# 网址:http(s):// 或 www. 开头的一串。句号、逗号等句末标点不能成为实体的一部分。
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>'\")\],;]+(?<![.,:;!?])", re.IGNORECASE)
# 电话:可选国家码 + (区号) + 7 位号码,允许 - . 空格分隔。
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b")
# 条款编号:Section/Article/Clause 等 + 形如 3.2(a) 的编号。
SECTION_ID_RE = re.compile(
    r"\b(?:Section|Sec\.|Article|Clause|Schedule|Exhibit|Appendix)\s+"
    r"\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*\b",
    re.IGNORECASE,
)
# 结构化标识符:ID/No./Invoice/Order 等 + 一串字母数字编号。
IDENTIFIER_RE = re.compile(
    r"\b(?:(?:ID|Number|Account|Invoice|Contract|Document|Order|Claim|Case)\b|No\.)\s*[:#-]?\s*"
    r"(?=[A-Z0-9._/-]*\d)[A-Z0-9][A-Z0-9._/-]{3,}\b",
    re.IGNORECASE,
)
# 句子:一段不含句末标点的内容 + 一个句末标点(或到行尾)。用于把实体定位到所在句子。
SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]|$)")
# 大写词组:连续的首字母大写词，用作"上下文锚点"(衡量句子里还有多少别的实体)。
CAPITAL_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.,'-]*(?:\s+[A-Z][A-Za-z0-9&.,'-]*){0,5}\b")
# 关系线索词:句子里出现这些动词，说明实体处在一个"陈述某事实"的语境里(更适合攻击)。
RELATION_CUE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|will|would|shall|should|can|could|"
    r"received|paid|sent|met|meet|discussed|signed|reported|increased|decreased|"
    r"acquired|sold|filed|approved|required|requires|expires|begins|ends|contains|"
    r"assigned|located|treated|measured|observed|compared)\b",
    re.IGNORECASE,
)
# 套话/免责声明:命中说明这句多半是模板噪声，应降权。
BOILERPLATE_RE = re.compile(
    r"\b(?:all rights reserved|for informational purposes|forward-looking statements|"
    r"this communication may contain|copyright|safe harbor|unsubscribe|confidentiality notice)\b",
    re.IGNORECASE,
)
# 邮件页眉页脚行(From:/To:/Regards 等),也属于噪声。
HEADER_FOOTER_RE = re.compile(r"^\s*(?:from|to|cc|bcc|subject|sent|date|regards|thanks|sincerely)\s*:?\s*$", re.IGNORECASE)

# 抽取器版本号,写进每条结果便于追溯是哪版规则产出的。
EXTRACTOR_VERSION = "attackability_v21_entity_policy_r1"


@dataclass(frozen=True)
class PatternSpec:
    """一条"实体正则规则"的完整描述(不可变数据类)。

    字段:
        entity_type: 实体类型名(如 MONEY、DATE)。
        family:      所属家族(用于多样性配额)。
        pattern:     用于匹配该实体的正则。
        base_scores: 该类型的"基础分"(重要性/可替换性/隐私特异性)。
        priority:    优先级,数字越大越优先(重叠冲突时保留高优先级者)。
        source:      候选来源标记,默认 "regex"。
    """
    entity_type: str
    family: str
    pattern: re.Pattern[str]
    base_scores: dict[str, float]
    priority: int
    source: str = "regex"


def _scores(importance: float, replaceability: float, privacy_specificity: float) -> dict[str, float]:
    """小工具:把三项基础分打包成字典。

    参数:
        importance:          重要性(这处信息有多关键)。
        replaceability:      可替换性(改成假值有多容易、多自然)。
        privacy_specificity: 隐私特异性(这处信息有多"独一无二、可定位个人")。
    返回:
        含上述三项的字典。
    """
    return {
        "importance": importance,
        "replaceability": replaceability,
        "privacy_specificity": privacy_specificity,
    }


# 规则登记表:把上面所有正则规则集中登记,并设定各自的家族、基础分与优先级。
# 顺序大致按优先级从高到低;末尾的 NUMERIC_VALUE 优先级很低(10),作为兜底的泛数字。
PATTERN_REGISTRY: tuple[PatternSpec, ...] = (
    PatternSpec("URL", "identifier", URL_RE, _scores(0.84, 0.70, 0.88), 100),
    PatternSpec("EMAIL", "identifier", EMAIL_RE, _scores(0.82, 0.78, 0.90), 98),
    PatternSpec("PHONE", "identifier", PHONE_RE, _scores(0.80, 0.78, 0.88), 96),
    PatternSpec("SECTION_ID", "identifier", SECTION_ID_RE, _scores(0.86, 0.76, 0.80), 94),
    PatternSpec("IDENTIFIER", "identifier", IDENTIFIER_RE, _scores(0.78, 0.72, 0.82), 92),
    PatternSpec("MONEY", "structured_numeric", MONEY_RE, _scores(0.95, 0.90, 0.90), 90),
    PatternSpec("MEDICAL_VALUE", "structured_numeric", MEDICAL_VALUE_RE, _scores(0.93, 0.88, 0.85), 88),
    PatternSpec("PERCENT", "structured_numeric", PERCENT_RE, _scores(0.92, 0.90, 0.82), 86),
    PatternSpec("DATE", "date_time", DATE_RE, _scores(0.90, 0.85, 0.80), 84),
    PatternSpec("TIME", "date_time", TIME_RE, _scores(0.82, 0.78, 0.75), 82),
    PatternSpec("DURATION", "date_time", DURATION_RE, _scores(0.84, 0.80, 0.76), 80),
    PatternSpec("CONTRACT_TERM", "domain_term", CONTRACT_TERM_RE, _scores(0.88, 0.70, 0.75), 78),
    PatternSpec("PRODUCT", "domain_term", PRODUCT_RE, _scores(0.82, 0.72, 0.78), 76),
    PatternSpec("PROJECT_NAME", "domain_term", PROJECT_NAME_RE, _scores(0.82, 0.72, 0.80), 74),
    PatternSpec("ORG", "named_entity", ORG_RE, _scores(0.88, 0.82, 0.86), 72),
    PatternSpec("LOCATION", "named_entity", LOCATION_RE, _scores(0.75, 0.75, 0.70), 70),
    PatternSpec("PERSON", "named_entity", PERSON_RE, _scores(0.70, 0.70, 0.82), 68),
    PatternSpec("NUMERIC_VALUE", "structured_numeric", NUMERIC_RE, _scores(0.60, 0.65, 0.55), 10),
)

_EXTRACTOR_ENTITY_TYPES = frozenset(spec.entity_type for spec in PATTERN_REGISTRY)
if _EXTRACTOR_ENTITY_TYPES != SUPPORTED_ENTITY_TYPES:
    raise RuntimeError(
        "Extractor/entity-policy type coverage mismatch: "
        f"missing={sorted(SUPPORTED_ENTITY_TYPES - _EXTRACTOR_ENTITY_TYPES)} "
        f"extra={sorted(_EXTRACTOR_ENTITY_TYPES - SUPPORTED_ENTITY_TYPES)}"
    )

# 由登记表派生:实体类型 → (家族, 基础分, 优先级)，给 NER 候选查默认值用。
TYPE_DEFAULTS: dict[str, tuple[str, dict[str, float], int]] = {
    spec.entity_type: (spec.family, spec.base_scores, spec.priority) for spec in PATTERN_REGISTRY
}

# 把 NER 模型给出的标签(如 PER/GPE)映射到本项目统一的实体类型。
NER_LABEL_MAP = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "ORG": "ORG",
    "ORGANIZATION": "ORG",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "LOCATION": "LOCATION",
    "FAC": "LOCATION",
    "LAW": "CONTRACT_TERM",
    "PRODUCT": "PRODUCT",
    "EVENT": "PROJECT_NAME",
}

# 多样性配额:每个家族最多选几个,避免最终实体全挤在同一类。
DEFAULT_DIVERSITY_QUOTAS = {
    "structured_numeric": 2,
    "date_time": 1,
    "identifier": 1,
    "named_entity": 1,
    "domain_term": 1,
}

# 锚点正则集合:用于数一个句子里除目标实体外,还有多少别的"具体信息点"。
# 锚点越多,说明该句信息越丰富、越利于 RAG 检索命中,因而更适合攻击。
ANCHOR_PATTERNS = (
    MONEY_RE,
    MEDICAL_VALUE_RE,
    PERCENT_RE,
    DATE_RE,
    TIME_RE,
    DURATION_RE,
    EMAIL_RE,
    URL_RE,
    PHONE_RE,
    SECTION_ID_RE,
    IDENTIFIER_RE,
    ORG_RE,
    CONTRACT_TERM_RE,
)

# 太泛化、没区分度的词:如果实体本身就是这些词,基本没有攻击价值,要降权/排除。
GENERIC_ENTITY_VALUES = {
    "company",
    "department",
    "project",
    "program",
    "initiative",
    "service",
    "system",
    "product",
    "team",
    "group",
    "agreement",
}

# 看起来更像"机构"而非"人名"的结尾词:用于剔除被 PERSON 正则误抓的机构名。
ORGISH_PERSON_TOKENS = {
    "Bank",
    "Capital",
    "Company",
    "Data",
    "Energy",
    "Finance",
    "Group",
    "Health",
    "Hospital",
    "Logistics",
    "Services",
    "Systems",
    "University",
}

# PERSON 的正则候选只提供召回，下面这些章节词、角色词和普通文档词用于本地高精度门禁。
# 这是类别级词表，不针对某个数据集中的具体样本或 source ID。
NON_PERSON_TOKENS = {
    "abstract",
    "agreement",
    "annual",
    "announcements",
    "assets",
    "assessment",
    "assignments",
    "author",
    "background",
    "both",
    "business",
    "card",
    "capital",
    "cash",
    "center",
    "clinical",
    "combination",
    "conclusion",
    "conclusions",
    "contributions",
    "contract",
    "credit",
    "discovery",
    "discussion",
    "division",
    "factors",
    "financial",
    "flow",
    "figure",
    "general",
    "hemichannels",
    "hybridization",
    "immunological",
    "introduction",
    "items",
    "lien",
    "management",
    "material",
    "materials",
    "method",
    "methods",
    "objective",
    "objectives",
    "offering",
    "officer",
    "our",
    "partner",
    "permeability",
    "prophage",
    "project",
    "purpose",
    "recognition",
    "release",
    "result",
    "results",
    "revenue",
    "risk",
    "sale",
    "second",
    "studio",
    "study",
    "supplementary",
    "supply",
    "table",
    "test",
    "the",
    "this",
    "timing",
    "updated",
}

NON_PERSON_TOKENS.update(
    {
        "application",
        "accounting",
        "agreement",
        "average",
        "brain",
        "certain",
        "committees",
        "control",
        "delaware",
        "fab",
        "flash",
        "framework",
        "gene",
        "glycosylation",
        "immunoglobulin",
        "immunohistochemistry",
        "law",
        "learning",
        "license",
        "manuscript",
        "matrix",
        "measurements",
        "model",
        "note",
        "nurse",
        "ontology",
        "outlier",
        "overdose",
        "percent",
        "plan",
        "ratio",
        "ref",
        "registered",
        "related",
        "relationships",
        "revised",
        "sanger",
        "sequencing",
        "service",
        "shareholder",
        "statements",
        "stock",
        "structure",
        "swap",
        "transactions",
        "unit",
    }
)

GENERIC_PROJECT_NAMES = {
    "advisors",
    "agreement",
    "an",
    "at",
    "appropriation",
    "cost",
    "enrolment",
    "flexibility",
    "leader",
    "liquidity",
    "loan",
    "loans",
    "management",
    "optimization",
    "partners",
    "phase",
    "report",
    "standardizes",
    "table",
    "testing",
    "the",
}

GENERIC_PROJECT_NAMES.update(
    {
        "according",
        "assets",
        "background",
        "be",
        "consensus",
        "consortium",
        "costs",
        "entities",
        "forgiveness",
        "id",
        "implementation",
        "insomnia",
        "labor",
        "limited",
        "mineral",
        "overview",
        "plus",
        "promissory",
        "revenues",
        "this",
        "we",
    }
)

_TERMINAL_SENTENCE_RE = re.compile(r"[.!?](?:[\"')\]]+)?$")
_LEADING_FRAGMENT_SURFACE_RE = re.compile(
    r"^(?:[,;:]|(?:>\s*){2,}|[•▪◦]|-\s*based\b|"
    r"\d+\s+(?:\[IMAGE\]|IN\b)|\d+(?:\.\d+)?%\s+reported\b)",
    re.IGNORECASE,
)
_EMAIL_METADATA_RE = re.compile(
    r"(?:Content-Transfer-Encoding|Content-Type|Message-ID|Mime-Version|"
    r"X-(?:From|To|cc|bcc|Folder|Origin|FileName)|"
    r"(?:^|[>\s])(?:From|To|Subject|Date))\s*:",
    re.IGNORECASE,
)
_ENCODING_OR_MAILBOX_RE = re.compile(
    r"(?:=\d{2}|quoted-printable|\b[A-Za-z]{2,}=\s+[A-Za-z]|"
    r"(?:\\[^\\\s]+){2,}|(?:maildir|exmerge)[\\/])",
    re.IGNORECASE,
)
_EMAIL_INTERNAL_ADDRESS_RE = re.compile(
    r"(?:/[A-Z]{2,}/[A-Z]{2,})?@[A-Z]{2,}(?:\b|/)",
    re.IGNORECASE,
)
_TRUNCATED_ENUMERATION_RE = re.compile(r"(?:^|\n)\s*\d+\.\s*$")
_COPY_LINK_LIST_RE = re.compile(r"\bcopy and paste the link\b", re.IGNORECASE)
_IDENTIFIER_PARTS_RE = re.compile(
    r"^(?P<prefix>ID|Number|Account|Invoice|Contract|Document|Order|Claim|Case|No\.)"
    r"\s*[:#-]?\s*(?P<payload>[A-Za-z0-9][A-Za-z0-9._/-]{3,})$",
    re.IGNORECASE,
)
_QUANTITY_WORD_SUFFIXES = {
    "beer",
    "beers",
    "item",
    "items",
    "patient",
    "patients",
    "shot",
    "shots",
    "unit",
    "units",
}
_TRUNCATED_ENDING_RE = re.compile(
    r"(?:\b(?:p|a|v|u|Mr|Mrs|Ms|Dr|Mon|Tue|Wed|Thu|Fri|Sat|Sun|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.|"
    r"(?<!\.)\b[A-Z]\.|https?://(?:www\.)?|"
    r"(?:(?:[$€£¥]|[A-Z]\$)\s*\d{1,2}\.))$",
    re.IGNORECASE,
)
_SCIENTIFIC_HEADING_PREFIX_RE = re.compile(
    r"^(?:Background|Methods?|Results?|Setting|Affinity measurement|"
    r"Research design and methods|Materials and Methods|Cell Culture|"
    r"Accession Number|Experimental and Clinical Evidence|"
    r"Boundary Conditions and Mesh for Unit-Cell Model)\s+(?=[A-Z])",
    re.IGNORECASE,
)
_NOMINAL_FRAGMENT_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3}\s+et al\.|"
    r"(?:Project|Program|Initiative)\s+[A-Z][A-Za-z0-9-]*"
    r"(?:\s*\([^)]*\))?\s+for\b[^.!?]*\.|"
    r"\d+\s+[A-Z][^.!?]{2,120}\.|"
    r"(?:Section\s+\S+,\s+as adopted|Code of Federal Regulations\b)[^.!?]*\.|"
    r"(?:Objective responses|Follow-up and histology):\s+[^.!?]{2,160}\."
    r")$",
    re.IGNORECASE,
)
_MULTI_EMAIL_LIST_RE = re.compile(
    r"(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\s*[,;]\s*){2,}",
    re.IGNORECASE,
)
_MONEY_NONFINANCIAL_UNIT_RE = re.compile(
    r"^\s*(?:active\s+)?(?:people|persons|users|connections|reads|pbmcs?|deaths?|"
    r"workers?|patients?|cases?|cells?|shares?|stocks?|inhabitants?|residents?|population)\b",
    re.IGNORECASE,
)
_MONEY_FINANCIAL_CUE_RE = re.compile(
    r"\b(?:usd|dollars?|dlrs?|revenue|sales?|assets?|charges?|costs?|expenses?|"
    r"payment|price|value|debt|income|funds?|cash|fees?|consideration|notional|"
    r"market|capital|investment|budget|profit|loss|worth)\b|[$€£¥]",
    re.IGNORECASE,
)
_CLOCK_CONTEXT_RE = re.compile(
    r"\b(?:at|from|until|between|before|after|by|meeting|time|schedule|"
    r"morning|afternoon|evening|noon|midnight|opens?|closes?|deadline)\b",
    re.IGNORECASE,
)
_RATIO_CONTEXT_RE = re.compile(
    r"\b(?:v/v|w/w|ratio|dilution|diluted|antibod|concentration|mixture|"
    r"solution|prepared|composed|codon|case\s+(?:no|number))\b|-(?:cv|cr)-",
    re.IGNORECASE,
)
_STRICT_CONTRACT_CONTEXT_RE = re.compile(
    r"\b(?:agreement|contract|lease|license|clause|provision|covenant|party|"
    r"borrower|lender|warranty|indemnif|non-disclosure|payment\s+term|"
    r"effective\s+date|governing\s+law)\b",
    re.IGNORECASE,
)
_NONCONTRACT_CONTEXT_RE = re.compile(
    r"\b(?:accounting|asset|balance\s+sheet|codon|fetal|pregnan|polymer|radical|"
    r"regeneration|ribosome|treatment|assessor|randomi[sz]|transformer|"
    r"participant|questionnaire|anonymity|healthcare|tax|deferred)\b",
    re.IGNORECASE,
)
_PRODUCT_OR_ORG_SUFFIX_RE = re.compile(
    r"^\s+(?:Act|Application|Company|Control|Electric|Group|Manager|Operator|"
    r"Plan|Regulations?|Agency|Administration|Department|Bank|Corporation|Inc|LLC)\b"
)
_BIOLOGICAL_SYSTEM_CONTEXT_RE = re.compile(
    r"\b(?:biological|cellular|immune|nervous|vascular|organ|model\s+organism|"
    r"experimental\s+section|device\s+design)\b",
    re.IGNORECASE,
)
_LOCATION_COMPOUND_SUFFIX_RE = re.compile(
    r"^\s+(?:Instruments?|University|Hospital|Bank|Department|Service|"
    r"Corporation|Corp|Inc|LLC|Group|Bay|River|Valley)\b"
)
_LOWERCASE_FRAGMENT_START_RE = re.compile(r"^[a-z][a-z'-]*\b")
_MONTH_BEFORE_NUMBER_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+$",
    re.IGNORECASE,
)
_GENERIC_ORG_VALUES = {
    "company",
    "public company",
    "emerging growth company",
}
_GENERIC_PRODUCT_VALUES = {
    "bibles",
    "common stock",
    "electrical products",
    "gps",
}
_PRODUCT_COMPETING_CONTEXT_RE = re.compile(
    r"\b(?:hotels?|seminars?|conferences?|nanowires?|powders?|questionnaires?|"
    r"clinical scales?|general practitioners?)\b",
    re.IGNORECASE,
)
_PRODUCT_BIOMEDICAL_SURFACE_RE = re.compile(
    r"^(?:D|R)?NaseI?$|^[A-Za-z]*(?:ase|aseI)\d*$",
    re.IGNORECASE,
)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    """把数值夹在 [lower, upper] 区间内(默认 0~1),防止分数越界。"""
    return min(upper, max(lower, value))


def _rounded(value: float) -> float:
    """先夹到 0~1，再四舍五入到 4 位小数(让输出分数整洁)。"""
    return round(_clamp(value), 4)


def _overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """判断两个候选在原文中的位置区间是否重叠(用于去重/冲突处理)。

    参数:
        left, right: 各含 start/end 位置的候选字典。
    返回:
        两个 [start,end) 区间有交叠则 True。
    """
    return int(left["start"]) < int(right["end"]) and int(right["start"]) < int(left["end"])


def has_meaningful_ner_covering_extension(
    candidate_span: tuple[int, int],
    ner_span: tuple[int, int],
    ner_text: str,
) -> bool:
    """Whether a covering NER span adds meaningful tokens around a candidate.

    Leading articles and trailing punctuation are harmless normalization
    differences.  Tokens such as ``São`` in ``São Paulo ... Department`` or
    ``PLC`` after ``BG Group`` indicate that the regex span is incomplete.
    """

    start, end = candidate_span
    ner_start, ner_end = ner_span
    if not (ner_start <= start and end <= ner_end):
        return False
    relative_start = max(0, start - ner_start)
    relative_end = max(relative_start, end - ner_start)
    left = ner_text[:relative_start]
    right = ner_text[relative_end:]

    def words(value: str) -> str:
        return " ".join(re.findall(r"[A-Za-z0-9]+", value)).casefold()

    left_words = words(left)
    right_words = words(right)
    return left_words not in {"", "a", "an", "the"} or bool(right_words)


def _normalized(value: str) -> str:
    """把字符串规范化:转小写、压缩空白。用于宽松比较两个实体是否"算同一个"。"""
    return " ".join(value.lower().split())


def _sentence_for_span(
    text: str,
    start: int,
    end: int,
    sentence_spans: list[tuple[int, int, str]] | None = None,
) -> str:
    """找出"完整包含 [start,end) 这个实体"的那句话。

    参数:
        text:       全文。
        start, end: 实体在全文中的起止位置。
    返回:
        包含该实体的句子;找不到则返回全文前 300 字符兜底。
    """
    # 本地 NER 管线启用句法分析时，优先复用其句界；它不会把 ``$37.2``、
    # ``Inc.`` 或 ``p.m.`` 中的句点误当成 claim 结尾。
    for sentence_start, sentence_end, sentence in sentence_spans or []:
        if sentence_start <= start and end <= sentence_end:
            return sentence.strip()
    # 无本地句界时退回原有确定性正则切分。
    for match in SENTENCE_RE.finditer(text or ""):
        sentence = match.group(0).strip()
        if match.start() <= start and end <= match.end():
            return sentence
    return " ".join((text or "").split())[:300]


def _anchor_count(sentence: str, entity_text: str) -> int:
    """数一句话里除目标实体外，还有多少"锚点"(别的具体信息点)。

    参数:
        sentence:    实体所在的句子。
        entity_text: 目标实体本身(它自己不计入锚点)。
    返回:
        去重后的锚点数量。
    """
    entity_norm = _normalized(entity_text)
    # 用 (起, 止, 规范化文本) 去重,避免同一处被重复计数。
    anchors: set[tuple[int, int, str]] = set()
    # 先用各类实体正则找锚点。
    for pattern in ANCHOR_PATTERNS:
        for match in pattern.finditer(sentence):
            value = match.group(0).strip()
            # 排除目标实体自己。
            if _normalized(value) != entity_norm:
                anchors.add((match.start(), match.end(), _normalized(value)))
    # 再把"多词大写短语"也算作锚点(往往是机构/专名)。
    for match in CAPITAL_PHRASE_RE.finditer(sentence):
        value = match.group(0).strip()
        if len(value.split()) >= 2 and _normalized(value) != entity_norm:
            anchors.add((match.start(), match.end(), _normalized(value)))
    return len(anchors)


def _looks_like_template(sentence: str) -> bool:
    """判断句子是否像模板/套话(命中 TEMPLATE_RE 或 BOILERPLATE_RE)。"""
    return bool(TEMPLATE_RE.search(sentence) or BOILERPLATE_RE.search(sentence))


def _looks_like_header_footer(sentence: str) -> bool:
    """判断句子是否像邮件页眉页脚/客套结尾(如单独一行的 "Regards")。"""
    compact = " ".join(sentence.split())
    if HEADER_FOOTER_RE.match(compact):
        return True
    return compact.lower() in {"regards", "thanks", "thank you", "sincerely"}


def is_likely_bad_person(value: str) -> bool:
    """判断一个被当成 PERSON 的值是不是"很可能不是真人名"。

    规则:带 Mr/Dr 等称谓的认为是真人;以机构性词(Bank/Group...)结尾的判为机构(非人名)。

    参数:
        value: 候选人名字符串。
    返回:
        判定"不像真人名"则 True。
    """
    raw_words = value.split()
    if not raw_words:
        return True
    honorific = raw_words[0].rstrip(".") in {"Mr", "Ms", "Mrs", "Dr"}
    words = raw_words[1:] if honorific else raw_words
    if not words:
        return True
    # 无称谓时只接受常见的二词姓名，或带单字母中间名的三词姓名；宁可少召回也不
    # 把章节标题、财务术语和角色短语当作人名。带称谓时允许 1~3 个姓名 token。
    if honorific:
        if not 1 <= len(words) <= 3:
            return True
    elif not (len(words) == 2 or (len(words) == 3 and len(words[1].rstrip(".")) == 1)):
        return True
    normalized_words = [word.strip(".,'").casefold() for word in words]
    if any(word in NON_PERSON_TOKENS for word in normalized_words):
        return True
    if not all(re.fullmatch(r"[A-Z][A-Za-z'-]*|[A-Z]\.?", word) for word in words):
        return True
    # 以机构性词结尾,多半其实是机构名。
    if words[-1].rstrip(".") in ORGISH_PERSON_TOKENS:
        return True
    return False


def is_likely_bad_project_name(value: str) -> bool:
    """Reject generic ``Project/Program/Initiative + noun`` phrases."""

    match = PROJECT_NAME_RE.fullmatch(" ".join((value or "").split()))
    if match is None:
        return True
    name = match.group(0).split()[-1].casefold()
    return name in GENERIC_PROJECT_NAMES


def is_likely_bad_identifier(value: str) -> bool:
    """Reject quantity phrases accidentally captured as structured identifiers."""

    compact = " ".join((value or "").split())
    match = _IDENTIFIER_PARTS_RE.fullmatch(compact)
    if match is None or re.search(r"\d", match.group("payload")) is None:
        return True
    payload = match.group("payload")
    quantity = re.fullmatch(r"\d+(?P<word>[a-z]{3,})", payload)
    return bool(quantity and quantity.group("word") in _QUANTITY_WORD_SUFFIXES)


def sentence_semantic_failure_reasons(sentence: str) -> tuple[str, ...]:
    """Return non-bypassable local reasons why a support sentence is unsafe."""

    compact = " ".join((sentence or "").split())
    reasons: list[str] = []
    if not compact or len(compact.split()) < 4:
        reasons.append("supporting_sentence_too_short")
    if compact and _TERMINAL_SENTENCE_RE.search(compact) is None:
        reasons.append("supporting_sentence_incomplete")
    if _LEADING_FRAGMENT_SURFACE_RE.search(compact):
        reasons.append("supporting_sentence_fragment_surface")
    if _EMAIL_METADATA_RE.search(compact):
        reasons.append("supporting_sentence_email_metadata")
    if _ENCODING_OR_MAILBOX_RE.search(compact):
        reasons.append("supporting_sentence_encoding_or_mailbox_artifact")
    if len(_EMAIL_INTERNAL_ADDRESS_RE.findall(sentence or "")) >= 3:
        reasons.append("supporting_sentence_internal_address_list")
    if (sentence or "").count("\n") >= 12:
        reasons.append("supporting_sentence_excessive_multiline_structure")
    if _TRUNCATED_ENUMERATION_RE.search(sentence or ""):
        reasons.append("supporting_sentence_truncated_enumeration")
    if (
        len(_COPY_LINK_LIST_RE.findall(compact)) >= 2
        or len(re.findall(r"https?://", compact, re.IGNORECASE)) >= 3
    ):
        reasons.append("supporting_sentence_repeated_link_list")
    if re.search(r"<[^>]+>|&(?:lt|gt|amp|nbsp);", compact, re.IGNORECASE):
        reasons.append("supporting_sentence_markup_artifact")
    if _TRUNCATED_ENDING_RE.search(compact):
        reasons.append("supporting_sentence_truncated_ending")
    if compact[:1].islower() and _LOWERCASE_FRAGMENT_START_RE.search(compact):
        reasons.append("supporting_sentence_lowercase_fragment")
    if _SCIENTIFIC_HEADING_PREFIX_RE.search(compact):
        reasons.append("supporting_sentence_heading_prefix")
    if _NOMINAL_FRAGMENT_RE.search(compact):
        reasons.append("supporting_sentence_nominal_fragment")
    if _MULTI_EMAIL_LIST_RE.search(compact):
        reasons.append("supporting_sentence_email_list")
    if compact.count('"') % 2:
        reasons.append("supporting_sentence_unbalanced_quote")
    if (
        compact.count("(") != compact.count(")")
        or compact.count("[") != compact.count("]")
        or compact.count("{") != compact.count("}")
    ):
        reasons.append("supporting_sentence_unbalanced_delimiters")
    return tuple(dict.fromkeys(reasons))


def entity_context_failure_reasons(
    text: str,
    span: tuple[int, int],
    entity_type: str,
) -> tuple[str, ...]:
    """Return deterministic context failures for one proposed entity span.

    These checks complement surface regexes.  They detect a syntactically
    matching substring that is semantically the wrong subtype, such as
    ``1:10`` in a dilution ratio or ``liability`` in an accounting sentence.
    """

    start, end = span
    source = text or ""
    if start < 0 or end <= start or end > len(source):
        return ("entity_span_out_of_bounds",)
    value = source[start:end]
    kind = (entity_type or "").upper()
    before = source[max(0, start - 100) : start]
    after = source[end : min(len(source), end + 100)]
    window = source[max(0, start - 180) : min(len(source), end + 180)]
    reasons: list[str] = []

    # Do not accept a numeric tail, a date/version component, or one endpoint
    # of a range as a standalone entity.
    if value[:1].isdigit() and before:
        if before[-1].isdigit() or before[-1] in {",", "."}:
            reasons.append("entity_numeric_prefix_boundary_mismatch")
        if re.search(r"\d{2,4}[-/.]\s*$", before):
            reasons.append("entity_numeric_component_boundary_mismatch")
    if value[-1:].isdigit() and after:
        if after[0].isdigit() or re.match(r"^[.,]\d", after):
            reasons.append("entity_numeric_suffix_boundary_mismatch")
    if kind == "DURATION" and re.search(r"\d[\d,]*\s*[-–—]\s*$", before):
        reasons.append("duration_range_endpoint_only")

    if kind == "NUMERIC_VALUE":
        if re.search(r"[A-Za-z][-–—]\s*$", before):
            reasons.append("numeric_inside_compound_identifier")
        if (
            re.search(r"\[\s*(?:\d+\s*,\s*)*$", before)
            and re.match(r"^\s*(?:,|\])", after)
        ):
            reasons.append("numeric_citation_context")
        if _MONTH_BEFORE_NUMBER_RE.search(before):
            reasons.append("numeric_calendar_day_context")
        if re.search(r"\b(?:Big|Chapter)\s+$", before, re.IGNORECASE):
            reasons.append("numeric_named_or_legal_context")

    if kind == "MONEY":
        if _MONEY_NONFINANCIAL_UNIT_RE.search(after):
            reasons.append("money_nonfinancial_quantity")
        if re.fullmatch(r"[$€£¥]\s?\d[\d,]*(?:\.\d+)?", value.strip()) and re.match(
            r"^\s*(?:million|billion)\b", after, re.IGNORECASE
        ):
            reasons.append("money_magnitude_suffix_outside_span")
        if re.search(r"\b(?:million|billion)\b", value, re.IGNORECASE) and not _MONEY_FINANCIAL_CUE_RE.search(window):
            reasons.append("money_missing_financial_context")

    if kind == "TIME":
        explicit_clock = bool(
            re.search(r"\b(?:am|pm)\b|noon|midnight", value, re.IGNORECASE)
        )
        repeated_colon_values = len(
            re.findall(r"(?<!\d)\d{1,2}:\d{2,4}(?!\d)", window)
        ) >= 2
        laboratory_ratio_series = repeated_colon_values and re.search(
            r"(?:\bab\d+\b|\banti-|\bIgG\b|\bantibod\w*|"
            r"\bdilution\w*|\blight:dark\b)",
            window,
            re.IGNORECASE,
        )
        if (
            _RATIO_CONTEXT_RE.search(window)
            or laboratory_ratio_series
            or re.match(r"^\s*h\b", after, re.IGNORECASE)
        ):
            reasons.append("time_ratio_or_identifier_context")
        elif not explicit_clock and not _CLOCK_CONTEXT_RE.search(window):
            reasons.append("time_missing_clock_context")

    if kind == "DATE":
        if (
            re.fullmatch(
                r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
                r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
                r"Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{2}",
                value.strip(),
                re.IGNORECASE,
            )
            and re.match(r"^\s*,\s*\d{1,2}\b", after)
        ):
            reasons.append("date_list_misparsed_as_year")

    if kind == "CONTRACT_TERM":
        if _NONCONTRACT_CONTEXT_RE.search(window):
            reasons.append("contract_term_noncontract_context")
        if value.casefold().strip() in {"liability", "indemnity"} and not _STRICT_CONTRACT_CONTEXT_RE.search(window):
            reasons.append("contract_term_missing_contract_context")

    if kind == "IDENTIFIER":
        if (
            re.match(r"(?i)^contract\s+[A-Za-z]+-\d+\b", value.strip())
            and re.search(
                r"\b(?:agents?|people|employees?|workers?|patients?|users?)\s+$",
                before,
                re.IGNORECASE,
            )
        ):
            reasons.append("identifier_prefix_used_as_verb")

    if kind == "MEDICAL_VALUE":
        if re.search(r"\bChapter\s+$", before, re.IGNORECASE):
            reasons.append("medical_value_legal_chapter_context")
        if re.fullmatch(r"\d+G", value.strip(), re.IGNORECASE) and re.search(
            r"\b(?:cell phones?|mobile|network|wireless)\b",
            window,
            re.IGNORECASE,
        ):
            reasons.append("medical_value_telecom_generation")

    if kind == "PROJECT_NAME":
        if re.match(r"^\s+[A-Z][A-Za-z0-9-]+\b", after):
            reasons.append("project_name_incomplete_boundary")
        if re.search(r"\b[A-Z][A-Za-z0-9-]+\s+$", before):
            reasons.append("project_name_incomplete_boundary")

    if kind == "PRODUCT":
        if _PRODUCT_OR_ORG_SUFFIX_RE.search(after):
            reasons.append("product_incomplete_or_org_boundary")
        if _BIOLOGICAL_SYSTEM_CONTEXT_RE.search(window):
            reasons.append("product_biological_or_heading_context")
        normalized_value = _normalized(value)
        if normalized_value in _GENERIC_PRODUCT_VALUES:
            reasons.append("product_generic_common_noun")
        if _PRODUCT_BIOMEDICAL_SURFACE_RE.fullmatch(value.strip()):
            reasons.append("product_biomedical_surface")
        if _PRODUCT_COMPETING_CONTEXT_RE.search(value) or (
            re.search(r"\bcompany\s+$", before, re.IGNORECASE)
            and not re.search(
                r"\b(?:product|platform|device|service|tool|software)\s+$",
                before,
                re.IGNORECASE,
            )
        ):
            reasons.append("product_competing_semantic_context")

    if kind == "LOCATION" and _LOCATION_COMPOUND_SUFFIX_RE.search(after):
        reasons.append("location_inside_named_entity")
    if kind == "ORG":
        if _normalized(value) in _GENERIC_ORG_VALUES:
            reasons.append("org_generic_common_noun")
        if re.search(r"(?:&|/)\s*$", before):
            reasons.append("org_incomplete_prefix_boundary")
        if re.match(
            r"^\s+(?:of|PLC|Inc|Corp|Corporation|LLC|Ltd|Limited|Company|Co)\b",
            after,
            re.IGNORECASE,
        ):
            reasons.append("org_incomplete_suffix_boundary")

    return tuple(dict.fromkeys(reasons))


def _specificity_score(value: str, entity_type: str, family: str) -> float:
    """给实体打"特异性"分:越独特、越具体(含数字/符号/多词)的实体分越高。

    参数:
        value:       实体文本。
        entity_type: 实体类型。
        family:      所属家族。
    返回:
        0~1 的特异性分。
    """
    compact = " ".join(value.split())
    tokens = compact.split()
    # 不同家族给一个起始基础分。
    base_by_family = {
        "identifier": 0.82,
        "structured_numeric": 0.78,
        "date_time": 0.74,
        "named_entity": 0.62,
        "domain_term": 0.60,
    }
    score = base_by_family.get(family, 0.55)
    # 泛数字本身区分度低,扣分。
    if entity_type == "NUMERIC_VALUE":
        score -= 0.18
    # 多词、含数字、含特殊符号都加分(更具体)。
    if len(tokens) >= 2:
        score += 0.08
    if any(ch.isdigit() for ch in compact):
        score += 0.08
    if any(ch in compact for ch in ("@", "/", "-", "_", "$", "%", ".")):
        score += 0.05
    # 太短、或属于泛化词,扣分。
    if len(compact) < 4:
        score -= 0.20
    if _normalized(compact) in GENERIC_ENTITY_VALUES:
        score -= 0.30
    return _clamp(score)


def _parser_friendliness(entity_type: str, family: str, value: str) -> float:
    """给实体打"解析友好度"分:结构化的(数字/日期/标识符)更容易在回答里被准确判读。

    参数:
        entity_type: 实体类型。
        family:      所属家族。
        value:       实体文本。
    返回:
        0~1 的解析友好度分。
    """
    # 结构化家族最友好,命名实体次之,其它再次。
    if family in {"structured_numeric", "date_time", "identifier"}:
        score = 0.82
    elif family == "named_entity":
        score = 0.64
    else:
        score = 0.60
    # 泛数字略扣;含换行或过长(>80)难解析,扣分。
    if entity_type == "NUMERIC_VALUE":
        score -= 0.12
    if "\n" in value or len(value) > 80:
        score -= 0.15
    return _clamp(score)


def _context_features(sentence: str, entity_text: str, entity_type: str) -> dict[str, Any]:
    """评估实体"所在句子"的上下文质量，并给出加分/扣分理由。

    一句"长度适中、含关系动词、还有别的锚点、不是模板/页脚"的话，最适合攻击；反之降权。

    参数:
        sentence:    实体所在句子。
        entity_text: 实体文本。
        entity_type: 实体类型。
    返回:
        含 context_quality(综合质量)、has_relation、anchor_count 等字段的字典。
    """
    compact = " ".join(sentence.split())
    words = compact.split()
    word_count = len(words)
    # 句子里是否有"关系动词"(陈述事实的标志)。
    has_relation = bool(RELATION_CUE_RE.search(compact))
    # 句子里有多少别的锚点。
    anchor_count = _anchor_count(compact, entity_text)
    is_template = _looks_like_template(compact)
    is_header_footer = _looks_like_header_footer(compact)
    # 实体是否"几乎就是整句话"(那样缺乏上下文,不利攻击)。
    entity_is_whole_sentence = _normalized(compact.strip(" ,;:-")) == _normalized(entity_text)

    quality = 0.0
    reasons: list[str] = []
    # —— 正向加分项 ——
    # 句子长度适中加分(6~45 词最佳,4~70 词可用)。
    if 6 <= word_count <= 45:
        quality += 0.25
        reasons.append("sentence_length_good")
    elif 4 <= word_count <= 70:
        quality += 0.15
        reasons.append("sentence_length_usable")
    else:
        quality += 0.05

    if has_relation:
        quality += 0.25
        reasons.append("relation_cue")
    # 锚点越多越好。
    if anchor_count >= 2:
        quality += 0.20
        reasons.append("multiple_anchors")
    elif anchor_count == 1:
        quality += 0.10
        reasons.append("single_anchor")
    # 实体不是整句(有上下文)加分。
    if not entity_is_whole_sentence:
        quality += 0.10
    # 不是模板/页脚加分。
    if not is_template and not is_header_footer:
        quality += 0.20
    # 句子完整(有句末标点)或较长,再略加。
    if compact.endswith((".", "!", "?")) or word_count > 8:
        quality += 0.05

    # —— 负向扣分项(generic_penalty,越大越糟) ——
    generic_penalty = 0.0
    if is_template:
        generic_penalty += 0.35
        reasons.append("template_penalty")
    if is_header_footer:
        generic_penalty += 0.30
        reasons.append("header_footer_penalty")
    if entity_is_whole_sentence:
        generic_penalty += 0.20
        reasons.append("standalone_entity_penalty")
    # 光秃秃一个数字、又没什么上下文,扣分。
    if entity_type == "NUMERIC_VALUE" and word_count < 8:
        generic_penalty += 0.25
        reasons.append("bare_numeric_penalty")

    return {
        # 最终上下文质量 = 正向加分 - 负向扣分(再夹到 0~1)。
        "context_quality": _rounded(quality - generic_penalty),
        "has_relation": has_relation,
        "anchor_count": anchor_count,
        # 把锚点数归一化成 0~1 的"检索锚点强度"(3 个及以上算满)。
        "retrieval_anchor_strength": _rounded(min(1.0, anchor_count / 3)),
        "generic_penalty": _rounded(generic_penalty),
        "context_reasons": reasons,
    }


def _selection_reason(candidate: dict[str, Any]) -> str:
    """根据候选的各项分数，拼出一句"它为什么被选中"的可读理由。

    参数:
        candidate: 已打分的候选字典。
    返回:
        用 "+" 连接的若干理由标签;没有突出项则给默认理由。
    """
    reasons = []
    if candidate.get("context_quality", 0.0) >= 0.70:
        reasons.append("high_context_quality")
    if candidate.get("retrieval_anchor_strength", 0.0) >= 0.50:
        reasons.append("strong_retrieval_anchor")
    # 同时被多种来源(regex + ner)识别到,更可信。
    if len(candidate.get("candidate_sources", [])) > 1:
        reasons.append("source_agreement")
    if candidate.get("parser_friendliness", 0.0) >= 0.75:
        reasons.append("parser_friendly")
    if candidate.get("entity_family"):
        reasons.append(f"family_quota:{candidate['entity_family']}")
    return "+".join(reasons or ["highest_attackability_available"])


class EntityExtractor:
    """Attackable fact entity extractor.

    Regex registry provides high-precision candidates. Optional NER output is
    normalized into the same representation, then gated and selected by
    deterministic attackability features.

    中文说明：可攻击实体抽取器(本文件的主类)。正则负责高精度候选;可选的 NER 模型负责
    补召回。所有候选最终用一套确定性的"可攻击性特征"过门槛并挑选——确定性意味着同样的
    输入永远得到同样的输出，利于实验复现。
    """

    def __init__(
        self,
        pattern_registry: tuple[PatternSpec, ...] | None = None,
        ner_model: Any | None = None,
        ner_model_name: str | None = None,
        enable_ner: bool | None = None,
        ner_confidence_threshold: float = 0.75,
        diversity_quotas: dict[str, int] | None = None,
        semantic_resolver: Any | None = None,
        require_semantic_resolver: bool = False,
    ) -> None:
        """初始化抽取器。

        参数:
            pattern_registry:         正则规则表,默认用全局 PATTERN_REGISTRY。
            ner_model:                可选的 NER 模型对象(不给则只用正则)。
            ner_model_name:           NER 模型名(用于记录)。
            enable_ner:               是否启用 NER;默认"有模型就启用"。
            ner_confidence_threshold: NER 候选的置信度门槛。
            diversity_quotas:         各家族的挑选配额,默认 DEFAULT_DIVERSITY_QUOTAS。
            semantic_resolver:        v6.3 本地语义 precision cascade。
            require_semantic_resolver:是否禁止六类语义实体绕过 resolver。
        """
        self.pattern_registry = pattern_registry or PATTERN_REGISTRY
        self.ner_model = ner_model
        # 没给名字就用模型类名兜底。
        self.ner_model_name = ner_model_name or (ner_model.__class__.__name__ if ner_model is not None else None)
        # enable_ner 没显式指定时,以"是否提供了模型"为准。
        self.enable_ner = bool(ner_model is not None) if enable_ner is None else enable_ner
        self.ner_confidence_threshold = ner_confidence_threshold
        self.diversity_quotas = diversity_quotas or DEFAULT_DIVERSITY_QUOTAS
        self.semantic_resolver = semantic_resolver
        self.require_semantic_resolver = bool(require_semantic_resolver)
        if self.require_semantic_resolver and self.semantic_resolver is None:
            raise RuntimeError(
                "v6.3 semantic entity extraction requires a loaded SemanticEntityResolver"
            )

    def extract(
        self,
        text: str,
        max_entities: int = 5,
        guarantee_min: int = 1,
        *,
        ner_output: Any | None = None,
        dataset: str = "",
        semantic_predictions: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Extract high-attackability entities with non-bypassable semantic gates.

        中文说明：对外的主方法。流程为"产生候选→合并→打分→语义安全硬门禁→质量优选→
        安全 fallback"。句子不完整、邮件/编码污染和实体表面类型错误是不可旁路的硬失败；
        guarantee_min 只能从语义安全但分数未过优选阈值的候选中补齐。

        参数:
            text:         待抽取的文本。
            max_entities: 最多返回几个实体(优选上限)。
            guarantee_min: 每篇文档至少保底返回几个语义安全候选。补齐时忽略 family 配额。
            ner_output: 可选的预计算本地 NER 文档；用于批处理提速，不改变候选与门禁逻辑。
            dataset:    数据集名；PubMed 用它启用生物实体 veto。
        返回:
            选中实体的字典列表;每个含 entity_id、分数、gate_passed、selection_reason 等。
        """
        # 1) 正则候选(主力)。
        source_text = text or ""
        raw_candidates = self._regex_candidates(source_text)
        ner_candidates: list[dict[str, Any]] = []
        sentence_spans: list[tuple[int, int, str]] = []
        # 2) 可选地追加 NER 候选。
        if self.enable_ner and ner_output is not None:
            ner_candidates = self._ner_candidates(source_text, ner_output)
            sentence_spans = self._ner_sentence_spans(ner_output)
            raw_candidates.extend(ner_candidates)
        elif self.enable_ner and self.ner_model is not None:
            ner_candidates, sentence_spans = self._ner_analysis(source_text)
            raw_candidates.extend(ner_candidates)
        # 3) 合并重叠/重复候选。
        candidates = self._merge_candidates(raw_candidates)
        self._annotate_ner_evidence(candidates, ner_candidates)
        # 4) v6.3 语义实体 precision cascade。正式 bulk 只运行 GLiNER2 large；
        # 结构化实体不经过这一步。通过时允许把规则召回的短 span 校正为完整边界。
        if self.semantic_resolver is not None:
            candidates, resolutions = self.semantic_resolver.resolve_and_propose(
                source_text,
                candidates,
                dataset=dataset,
                precomputed_predictions=semantic_predictions,
            )
            for candidate, resolution in zip(candidates, resolutions, strict=True):
                if resolution is None:
                    continue
                if candidate.get("semantic_proposal"):
                    entity_type = str(candidate.get("type") or "").upper()
                    family, base_scores, priority = TYPE_DEFAULTS.get(
                        entity_type,
                        (
                            "named_entity",
                            _scores(0.70, 0.68, 0.68),
                            55,
                        ),
                    )
                    candidate["entity_family"] = family
                    candidate["base_scores"] = dict(base_scores)
                    candidate["priority"] = priority
                    candidate["candidate_sources"] = ["semantic_precision_cascade"]
                candidate["semantic_resolution"] = resolution.to_dict()
                if resolution.accepted:
                    candidate.update(
                        {
                            "text": resolution.text,
                            "start": resolution.start,
                            "end": resolution.end,
                            "span": [resolution.start, resolution.end],
                        }
                    )
                    candidate["candidate_sources"] = sorted(
                        {
                            *candidate.get("candidate_sources", []),
                            "semantic_precision_cascade",
                        }
                    )
        # 5) 给每个候选打分。
        scored = [
            self._score_candidate(source_text, candidate, sentence_spans=sentence_spans)
            for candidate in candidates
        ]
        # 6) 不可旁路的语义安全门禁。失败项既不能进入 primary，也不能被 fallback 补回。
        semantic_safe: list[dict[str, Any]] = []
        for candidate in scored:
            semantic_failures = self._semantic_gate_failure_reasons(candidate)
            candidate["semantic_gate_passed"] = not semantic_failures
            candidate["semantic_gate_failure_reasons"] = list(semantic_failures)
            if not semantic_failures:
                semantic_safe.append(candidate)
        # 7) 优选:在配额约束下挑出通过质量门槛的多样高分实体。
        gated = [candidate for candidate in semantic_safe if self._passes_hard_gates(candidate)]
        primary = self._select_diverse(gated, max_entities=max_entities)
        for candidate in primary:
            candidate["gate_passed"] = True
        # 8) 安全保覆盖:不足 guarantee_min 时，只从语义安全但质量分未过门槛的候选补齐。
        selected = list(primary)
        if len(selected) < guarantee_min:
            chosen_keys = {(str(c["type"]), _normalized(str(c["text"]))) for c in selected}
            ungated = [c for c in semantic_safe if not self._passes_hard_gates(c)]
            fallback = self._select_topk(ungated, guarantee_min - len(selected), exclude=chosen_keys)
            for candidate in fallback:
                candidate["gate_passed"] = False
            selected.extend(fallback)
        # 给选中项编号、补上人类可读的选择理由。
        for idx, candidate in enumerate(selected, start=1):
            candidate["entity_id"] = f"e{idx}"
            candidate["selection_reason"] = _selection_reason(candidate)
            candidate["reason"] = (
                f"attackability={candidate['attackability_score']:.3f}; "
                f"gate_passed={candidate.get('gate_passed', True)}; "
                f"{candidate['selection_reason']}"
            )
        return selected

    def _select_topk(
        self,
        candidates: list[dict[str, Any]],
        k: int,
        exclude: set[tuple[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """按可攻击性降序取前 k 个(忽略 family 配额，用于保底补齐)。

        参数:
            candidates: 候选(通常是未过门槛者)。
            k:          最多取几个。
            exclude:    已选过的 (type, 规范化文本) 集合，避免与 primary 重复。
        返回:
            选中的候选列表(最多 k 个)。
        """
        if k <= 0:
            return []
        exclude = exclude or set()
        # 排序与 _select_diverse 一致，保证确定性可复现。
        ordered = sorted(
            candidates,
            key=lambda x: (
                -float(x["attackability_score"]),
                -float(x["importance"]),
                -float(x.get("privacy_specificity", 0.0)),
                int(x["start"]),
            ),
        )
        picked: list[dict[str, Any]] = []
        seen = set(exclude)
        for candidate in ordered:
            if len(picked) >= k:
                break
            key = (str(candidate["type"]), _normalized(str(candidate["text"])))
            if key in seen:
                continue
            picked.append(candidate)
            seen.add(key)
        return picked

    def _regex_candidates(self, text: str) -> list[dict[str, Any]]:
        """用规则表里的所有正则扫描文本，产出候选实体列表。

        参数:
            text: 待扫描文本。
        返回:
            候选字典列表(含文本、类型、家族、位置、来源、基础分、优先级)。
        """
        candidates: list[dict[str, Any]] = []
        for spec in self.pattern_registry:
            # 找出该规则在文中的所有匹配。
            for match in spec.pattern.finditer(text):
                raw_value = match.group(0)
                leading = len(raw_value) - len(raw_value.lstrip())
                value = raw_value.strip()
                start = match.start() + leading
                end = start + len(value)
                if spec.entity_type == "ORG" and value.endswith("."):
                    value = value[:-1]
                    end -= 1
                # 过一道"表面合法性"检查(太短/太长/泛词等直接跳过)。
                if not self._valid_surface(value, spec.entity_type):
                    continue
                candidates.append(
                    {
                        "text": value,
                        "type": spec.entity_type,
                        "entity_family": spec.family,
                        "start": start,
                        "end": end,
                        "span": [start, end],
                        "candidate_sources": [spec.source],
                        "base_scores": dict(spec.base_scores),
                        "priority": spec.priority,
                    }
                )
        return candidates

    def _ner_analysis(
        self,
        text: str,
    ) -> tuple[list[dict[str, Any]], list[tuple[int, int, str]]]:
        """Run the pinned local model once and return entities plus sentence spans."""

        try:
            output = self.ner_model(text)
        except Exception as exc:  # pragma: no cover - external model behavior
            LOGGER.warning("NER candidate generation failed: %s", exc)
            return [], []
        return self._ner_candidates(text, output), self._ner_sentence_spans(output)

    def _ner_sentence_spans(self, output: Any) -> list[tuple[int, int, str]]:
        """Normalize spaCy sentence boundaries without requiring them from other backends."""

        try:
            sentences = output.sents if hasattr(output, "sents") else ()
            return [
                (int(sentence.start_char), int(sentence.end_char), str(sentence.text))
                for sentence in sentences
                if str(sentence.text).strip()
            ]
        except (AttributeError, ValueError):
            return []

    def _ner_candidates(self, text: str, output: Any) -> list[dict[str, Any]]:
        """调用可选的 NER 模型，把它识别到的实体也转成统一格式的候选。

        参数:
            text: 待识别文本。
        返回:
            候选字典列表;模型报错或置信度不足时相应跳过。
        """
        candidates: list[dict[str, Any]] = []

        # 兼容两种输出:spaCy 风格(有 .ents)或直接的列表。
        if hasattr(output, "ents"):
            iterable = output.ents
        else:
            iterable = output if isinstance(output, list) else []

        for item in iterable:
            # 把不同框架的单个实体统一解析成 (值,标签,起,止,置信度)。
            parsed = self._parse_ner_item(text, item)
            if parsed is None:
                continue
            value, label, start, end, confidence = parsed
            # 把 NER 标签映射到本项目类型;映射不到、或置信度不够,跳过。
            entity_type = NER_LABEL_MAP.get(label.upper())
            if (
                entity_type not in {"PERSON", "ORG", "LOCATION"}
                or confidence < self.ner_confidence_threshold
            ):
                continue
            article = re.match(r"(?i)^(?:the|a|an)\s+", value)
            if article is not None:
                start += article.end()
                value = value[article.end() :]
            if entity_type == "ORG" and value.endswith("."):
                value = value[:-1]
                end -= 1
            # 查该类型的默认家族/基础分/优先级(查不到给一组兜底默认值)。
            family, base_scores, priority = TYPE_DEFAULTS.get(entity_type, ("domain_term", _scores(0.70, 0.62, 0.66), 50))
            if not self._valid_surface(value, entity_type):
                continue
            candidates.append(
                {
                    "text": value,
                    "type": entity_type,
                    "entity_family": family,
                    "start": start,
                    "end": end,
                    "span": [start, end],
                    "candidate_sources": ["ner"],
                    "base_scores": dict(base_scores),
                    # NER 候选优先级比同类型正则略低(正则更可信),但不低于 50。
                    "priority": max(50, priority - 5),
                    "ner_confidence": _rounded(confidence),
                    "ner_model": self.ner_model_name,
                }
            )
        return candidates

    def _annotate_ner_evidence(
        self,
        candidates: list[dict[str, Any]],
        ner_candidates: list[dict[str, Any]],
    ) -> None:
        """Attach exact/covering/overlapping local-NER evidence to every candidate."""

        for candidate in candidates:
            start = int(candidate["start"])
            end = int(candidate["end"])
            exact: set[str] = set()
            covering: set[str] = set()
            overlapping: set[str] = set()
            meaningful_covering: set[str] = set()
            for ner_candidate in ner_candidates:
                ner_start = int(ner_candidate["start"])
                ner_end = int(ner_candidate["end"])
                ner_type = str(ner_candidate["type"]).upper()
                if ner_start == start and ner_end == end:
                    exact.add(ner_type)
                if ner_start <= start and end <= ner_end:
                    covering.add(ner_type)
                    if has_meaningful_ner_covering_extension(
                        (start, end),
                        (ner_start, ner_end),
                        str(ner_candidate["text"]),
                    ):
                        meaningful_covering.add(ner_type)
                if start < ner_end and ner_start < end:
                    overlapping.add(ner_type)
            candidate["ner_exact_types"] = sorted(exact)
            candidate["ner_covering_types"] = sorted(covering)
            candidate["ner_meaningful_covering_types"] = sorted(meaningful_covering)
            candidate["ner_overlapping_types"] = sorted(overlapping)

    def _parse_ner_item(self, text: str, item: Any) -> tuple[str, str, int, int, float] | None:
        """把"一个 NER 实体对象"解析成统一的 (值, 标签, 起, 止, 置信度) 五元组。

        兼容三种常见形态:spaCy 的 Span 对象、HuggingFace 的 dict、或简单的元组。

        参数:
            text: 全文(当对象没给位置时,用来查找实体位置)。
            item: 一个 NER 实体(形态不定)。
        返回:
            五元组;无法解析则返回 None。
        """
        # 形态一:spaCy Span(有 .text 和 .label_)。
        if hasattr(item, "text") and hasattr(item, "label_"):
            value = str(item.text).strip()
            label = str(item.label_)
            start = int(getattr(item, "start_char", text.find(value)))
            end = int(getattr(item, "end_char", start + len(value)))
            confidence = float(getattr(item, "score", 1.0))
            return value, label, start, end, confidence
        # 形态二:HuggingFace pipeline 输出的字典。
        if isinstance(item, dict):
            value = str(item.get("word") or item.get("text") or item.get("entity") or "").strip()
            label = str(item.get("entity_group") or item.get("label") or item.get("entity") or "")
            start = item.get("start")
            end = item.get("end")
            # 字典没带位置时,用 find 在全文里查。
            if start is None or end is None:
                found = text.find(value)
                if found < 0:
                    return None
                start = found
                end = found + len(value)
            confidence = float(item.get("score") or item.get("confidence") or 1.0)
            return value, label, int(start), int(end), confidence
        # 形态三:简单元组 (值, 标签, 起, 止[, 置信度])。
        if isinstance(item, tuple) and len(item) >= 4:
            value = str(item[0]).strip()
            label = str(item[1])
            start = int(item[2])
            end = int(item[3])
            confidence = float(item[4]) if len(item) >= 5 else 1.0
            return value, label, start, end, confidence
        return None

    def _merge_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """合并候选:同一处的多个候选合一，重叠冲突时保留优先级更高/更长的。

        参数:
            candidates: 合并前的全部候选。
        返回:
            合并去重后的候选列表。
        """
        merged: list[dict[str, Any]] = []
        # 先排序:优先级高的在前;同优先级按位置;再按文本长度降序(长的更具体)。
        ordered = sorted(candidates, key=lambda x: (-int(x["priority"]), int(x["start"]), -len(str(x["text"]))))
        for candidate in ordered:
            # 若已有"同一处"的候选,合并进去(累积来源、必要时升级)。
            existing = self._find_merge_target(merged, candidate)
            if existing is not None:
                self._merge_into(existing, candidate)
                continue
            # 本地 NER 若给出覆盖整个名称的更长 PERSON/ORG/LOCATION span，应替换
            # 较短的正则命名实体，而不是被正则优先级挡住。
            if candidate.get("candidate_sources") == ["ner"]:
                covered_named = [
                    item
                    for item in merged
                    if int(candidate["start"]) <= int(item["start"])
                    and int(item["end"]) <= int(candidate["end"])
                    and (
                        int(candidate["start"]) < int(item["start"])
                        or int(item["end"]) < int(candidate["end"])
                    )
                    and str(candidate.get("type") or "").upper()
                    in {"PERSON", "ORG", "LOCATION"}
                    and str(item.get("type") or "").upper()
                    in {"PERSON", "ORG", "LOCATION", "PRODUCT"}
                ]
                if covered_named:
                    candidate["candidate_sources"] = sorted(
                        {
                            *candidate.get("candidate_sources", []),
                            *(
                                source
                                for item in covered_named
                                for source in item.get("candidate_sources", [])
                            ),
                        }
                    )
                    merged = [item for item in merged if item not in covered_named]
                    merged.append(candidate)
                    continue
            # 若被一个更优的重叠候选挡住,则丢弃本候选。
            if self._is_blocked_by_better_overlap(merged, candidate):
                continue
            # 反过来,把已有里那些"被本候选(更高优先级)压制"的重叠项移除。
            merged = [item for item in merged if not (_overlaps(item, candidate) and int(candidate["priority"]) > int(item["priority"]))]
            merged.append(candidate)
        return merged

    def _find_merge_target(self, merged: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any] | None:
        """在已合并列表里找"应该和本候选合并"的那一项(同位置,或同文本且重叠)。

        参数:
            merged:    已合并的候选列表。
            candidate: 当前候选。
        返回:
            可合并的目标项;没有则 None。
        """
        for existing in merged:
            # 位置完全相同。
            same_span = int(existing["start"]) == int(candidate["start"]) and int(existing["end"]) == int(candidate["end"])
            # 文本相同且区间有重叠。
            same_text_overlap = _normalized(str(existing["text"])) == _normalized(str(candidate["text"])) and _overlaps(existing, candidate)
            if same_span or same_text_overlap:
                return existing
        return None

    def _merge_into(self, existing: dict[str, Any], candidate: dict[str, Any]) -> None:
        """把 candidate 合并进 existing:累积来源；若 candidate 优先级更高则用它的信息覆盖。

        参数:
            existing:  保留的目标项(就地修改)。
            candidate: 被并入的候选。
        """
        # 合并并集去重来源(便于后面判断"多来源一致")。
        sources = set(existing.get("candidate_sources", [])) | set(candidate.get("candidate_sources", []))
        existing["candidate_sources"] = sorted(sources)
        # PERSON 正则只负责召回。若同一 span 被本地 NER 明确识别为 ORG/LOCATION，
        # 使用 NER 类型，避免 ``Internal Control``、``New Jersey`` 一类系统误标。
        prefer_named_ner_type = (
            str(existing.get("type") or "").upper() == "PERSON"
            and candidate.get("candidate_sources") == ["ner"]
            and str(candidate.get("type") or "").upper() in {"ORG", "LOCATION"}
        )
        # candidate 优先级更高时,用它的类型/文本/位置/基础分覆盖。
        if prefer_named_ner_type or int(candidate["priority"]) > int(existing["priority"]):
            existing.update(
                {
                    "type": candidate["type"],
                    "entity_family": candidate["entity_family"],
                    "text": candidate["text"],
                    "start": candidate["start"],
                    "end": candidate["end"],
                    "span": candidate["span"],
                    "base_scores": candidate["base_scores"],
                    "priority": candidate["priority"],
                }
            )
        # 若 candidate 来自 NER,保留较高的置信度与模型名。
        if "ner_confidence" in candidate:
            existing["ner_confidence"] = max(float(existing.get("ner_confidence", 0.0)), float(candidate["ner_confidence"]))
            existing["ner_model"] = candidate.get("ner_model")

    def _is_blocked_by_better_overlap(self, merged: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
        """判断本候选是否被某个"更优的重叠候选"挡住(从而应被丢弃)。

        参数:
            merged:    已合并列表。
            candidate: 当前候选。
        返回:
            被更高优先级、或同优先级但更长的重叠项挡住则 True。
        """
        for existing in merged:
            if not _overlaps(existing, candidate):
                continue
            # 已有项优先级更高 → 挡住。
            if int(existing["priority"]) > int(candidate["priority"]):
                return True
            # 优先级相同但已有项文本更长(更具体)→ 也挡住。
            if int(existing["priority"]) == int(candidate["priority"]) and len(str(existing["text"])) >= len(str(candidate["text"])):
                return True
        return False

    def _score_candidate(
        self,
        text: str,
        candidate: dict[str, Any],
        *,
        sentence_spans: list[tuple[int, int, str]] | None = None,
    ) -> dict[str, Any]:
        """给单个候选计算各项分数,核心是"可攻击性(attackability)"综合分。

        综合分是多项特征的加权和:基础重要性、上下文质量、特异性、可替换性、检索锚点强度、
        解析友好度等正向项，再减去 generic_penalty(模板/裸数字等扣分)。

        参数:
            text:      全文(用于定位实体所在句子)。
            candidate: 待打分的候选。
        返回:
            在原候选基础上补齐各项分数与上下文信息后的新字典。
        """
        entity_text = str(candidate["text"])
        entity_type = str(candidate["type"])
        family = str(candidate["entity_family"])
        # 定位实体所在句子,并据此算上下文特征。
        start = int(candidate["start"])
        end = int(candidate["end"])
        sentence = _sentence_for_span(text, start, end, sentence_spans)
        sentence_start = text.rfind(sentence, 0, start + 1)
        if sentence_start < 0:
            sentence_start = text.find(sentence)
        relative_start = start - sentence_start if sentence_start >= 0 else -1
        relative_end = relative_start + len(entity_text) if relative_start >= 0 else -1
        if (
            relative_start < 0
            or relative_end > len(sentence)
            or sentence[relative_start:relative_end] != entity_text
        ):
            occurrences = [
                match.start()
                for match in re.finditer(re.escape(entity_text), sentence)
            ]
            if occurrences:
                expected = max(0, start - max(0, sentence_start))
                relative_start = min(occurrences, key=lambda item: abs(item - expected))
                relative_end = relative_start + len(entity_text)
            else:
                relative_start = -1
                relative_end = -1
        context = _context_features(sentence, entity_text, entity_type)
        entity_context_failures = entity_context_failure_reasons(text, (start, end), entity_type)
        specificity = _specificity_score(entity_text, entity_type, family)
        parser_score = _parser_friendliness(entity_type, family, entity_text)
        base = candidate.get("base_scores", _scores(0.60, 0.60, 0.60))
        # 多来源一致(regex+ner)给一点点加成。
        source_agreement = 0.08 if len(candidate.get("candidate_sources", [])) > 1 else 0.0
        ner_confidence = float(candidate.get("ner_confidence", 0.0))
        # NER 置信度超过门槛的部分,折算成小幅加成(上限 0.05)。
        ner_bonus = min(0.05, max(0.0, ner_confidence - self.ner_confidence_threshold) * 0.20)
        generic_penalty = float(context["generic_penalty"])

        # 重要性 = 基础重要性、上下文质量、特异性、锚点强度的加权和 + 加成 - 扣分。
        importance = _rounded(
            0.52 * float(base["importance"])
            + 0.24 * float(context["context_quality"])
            + 0.12 * specificity
            + 0.08 * float(context["retrieval_anchor_strength"])
            + source_agreement
            + ner_bonus
            - generic_penalty
        )
        # 可替换性 = 基础可替换性 + 解析友好度 + 上下文 + 特异性 的加权和 - 扣分。
        replaceability = _rounded(
            0.58 * float(base["replaceability"])
            + 0.18 * parser_score
            + 0.14 * float(context["context_quality"])
            + 0.10 * specificity
            + source_agreement
            - generic_penalty
        )
        # 隐私特异性 = 基础隐私分 + 特异性 + 锚点 + 上下文 的加权和 - 扣分。
        privacy_specificity = _rounded(
            0.58 * float(base["privacy_specificity"])
            + 0.24 * specificity
            + 0.10 * float(context["retrieval_anchor_strength"])
            + 0.08 * float(context["context_quality"])
            + source_agreement
            - generic_penalty
        )
        # 可攻击性总分:综合以上所有维度的加权和(这是最终挑选的主要依据)。
        attackability = _rounded(
            0.20 * float(base["importance"])
            + 0.20 * float(context["context_quality"])
            + 0.15 * specificity
            + 0.15 * float(base["replaceability"])
            + 0.10 * float(context["retrieval_anchor_strength"])
            + 0.10 * parser_score
            + source_agreement
            + ner_bonus
            - generic_penalty
        )

        # 复制候选并去掉中间字段(base_scores/priority),换成最终对外的各项分数。
        scored = dict(candidate)
        scored.pop("base_scores", None)
        scored.pop("priority", None)
        scored.update(
            {
                "importance": importance,
                "replaceability": replaceability,
                "privacy_specificity": privacy_specificity,
                "attackability_score": attackability,
                "specificity": _rounded(specificity),
                "context_quality": context["context_quality"],
                "retrieval_anchor_strength": context["retrieval_anchor_strength"],
                "parser_friendliness": _rounded(parser_score),
                "generic_penalty": context["generic_penalty"],
                "context_reasons": context["context_reasons"],
                "has_relation_context": context["has_relation"],
                "context_anchor_count": context["anchor_count"],
                "supporting_sentence": sentence,
                "supporting_sentence_span": (
                    [sentence_start, sentence_start + len(sentence)]
                    if sentence_start >= 0
                    else None
                ),
                "entity_sentence_span": (
                    [relative_start, relative_end]
                    if relative_start >= 0
                    else None
                ),
                "entity_context_failure_reasons": list(entity_context_failures),
                "extractor_version": EXTRACTOR_VERSION,
            }
        )
        return scored

    def _passes_hard_gates(self, candidate: dict[str, Any]) -> bool:
        """硬门槛:质量明显不达标的候选直接淘汰，无论它分数排第几。

        参数:
            candidate: 已打分候选。
        返回:
            通过全部门槛返回 True,否则 False。
        """
        entity_type = str(candidate.get("type") or "")
        family = str(candidate.get("entity_family") or "")
        sources = set(candidate.get("candidate_sources", []))
        # 上下文质量过低 → 淘汰。
        if float(candidate.get("context_quality", 0.0)) < 0.30:
            return False
        # 扣分过重(模板/页脚等)→ 淘汰。
        if float(candidate.get("generic_penalty", 0.0)) >= 0.45:
            return False
        # 可攻击性过低 → 淘汰。
        if float(candidate.get("attackability_score", 0.0)) < 0.45:
            return False
        # 裸数字要求更高的上下文质量,否则淘汰。
        if entity_type == "NUMERIC_VALUE" and float(candidate.get("context_quality", 0.0)) < 0.55:
            return False
        # 不像真人名的 PERSON → 淘汰。
        if entity_type == "PERSON" and is_likely_bad_person(str(candidate.get("text") or "")):
            return False
        # 仅由 NER 给出的命名实体,要求更严:置信度、上下文质量、关系语境三道都要过。
        if sources == {"ner"} and family == "named_entity":
            if float(candidate.get("ner_confidence", 0.0)) < self.ner_confidence_threshold:
                return False
            if float(candidate.get("context_quality", 0.0)) < 0.55:
                return False
            if not bool(candidate.get("has_relation_context")):
                return False
        return True

    def _semantic_gate_failure_reasons(self, candidate: dict[str, Any]) -> tuple[str, ...]:
        """Return semantic failures that fallback is forbidden to bypass."""

        reasons = list(sentence_semantic_failure_reasons(str(candidate.get("supporting_sentence") or "")))
        reasons.extend(str(reason) for reason in candidate.get("entity_context_failure_reasons", []))
        entity_type = str(candidate.get("type") or "").upper()
        value = str(candidate.get("text") or "")
        if entity_type in {
            "PERSON",
            "ORG",
            "LOCATION",
            "PRODUCT",
            "PROJECT_NAME",
            "CONTRACT_TERM",
        } and (self.semantic_resolver is not None or self.require_semantic_resolver):
            semantic_resolution = candidate.get("semantic_resolution")
            if not isinstance(semantic_resolution, dict):
                reasons.append("semantic_resolution_missing")
            elif not bool(semantic_resolution.get("accepted")):
                resolution_reasons = semantic_resolution.get("failure_reasons")
                if isinstance(resolution_reasons, (list, tuple)):
                    reasons.extend(str(reason) for reason in resolution_reasons)
                else:
                    reasons.append("semantic_resolution_rejected")
        if entity_type == "PERSON" and is_likely_bad_person(value):
            reasons.append("person_surface_mismatch")
        if entity_type == "PROJECT_NAME" and is_likely_bad_project_name(value):
            reasons.append("project_name_surface_mismatch")
        if entity_type == "IDENTIFIER" and is_likely_bad_identifier(value):
            reasons.append("identifier_surface_mismatch")
        if self.enable_ner and self.ner_model is not None:
            exact_types = {str(item).upper() for item in candidate.get("ner_exact_types", [])}
            covering_types = {str(item).upper() for item in candidate.get("ner_covering_types", [])}
            meaningful_covering_types = {
                str(item).upper()
                for item in candidate.get("ner_meaningful_covering_types", [])
            }
            conflicts = (exact_types | covering_types) - {entity_type}
            if entity_type == "PERSON" and "PERSON" not in exact_types:
                reasons.append("person_missing_exact_local_ner_support")
            if entity_type == "PRODUCT" and conflicts & {"PERSON", "ORG", "LOCATION"}:
                reasons.append("product_local_ner_type_conflict")
            if entity_type == "LOCATION" and conflicts & {"PERSON", "ORG"}:
                reasons.append("location_local_ner_type_conflict")
            if entity_type == "ORG" and exact_types & {"PERSON", "LOCATION"}:
                reasons.append("org_local_ner_type_conflict")
            if entity_type in {"ORG", "LOCATION", "PRODUCT"} and meaningful_covering_types:
                reasons.append("named_entity_local_ner_covering_boundary")
        return tuple(dict.fromkeys(reasons))

    def _select_diverse(self, candidates: list[dict[str, Any]], max_entities: int) -> list[dict[str, Any]]:
        """在"每个家族有配额"的约束下，按分数从高到低挑出最多 max_entities 个实体。

        这样能避免最终结果全是同一类(比如全是数字)，保证攻击点多样。

        参数:
            candidates:   通过门槛的候选。
            max_entities: 最多选几个。
        返回:
            选中的候选列表。
        """
        if max_entities <= 0:
            return []
        # 排序:可攻击性→重要性→隐私特异性 依次降序,最后按出现位置升序(让结果稳定可复现)。
        sorted_candidates = sorted(
            candidates,
            key=lambda x: (
                -float(x["attackability_score"]),
                -float(x["importance"]),
                -float(x.get("privacy_specificity", 0.0)),
                int(x["start"]),
            ),
        )
        selected: list[dict[str, Any]] = []
        family_counts: dict[str, int] = {}   # 每个家族已选几个
        seen: set[tuple[str, str]] = set()    # 已选过的(类型,文本),用于去重
        for candidate in sorted_candidates:
            # 选够了就停。
            if len(selected) >= max_entities:
                break
            # 同类型同文本的重复项跳过。
            key = (str(candidate["type"]), _normalized(str(candidate["text"])))
            if key in seen:
                continue
            family = str(candidate.get("entity_family") or "")
            # 该家族的配额(没配置就允许到 max_entities)。
            quota = self.diversity_quotas.get(family, max_entities)
            # 该家族已选满 → 跳过这个候选。
            if family_counts.get(family, 0) >= quota:
                continue
            selected.append(candidate)
            seen.add(key)
            family_counts[family] = family_counts.get(family, 0) + 1
        return selected

    def _valid_surface(self, value: str, entity_type: str) -> bool:
        """"表面合法性"快检:把明显不能用的候选(太短/太长/泛词/没字母数字)提前刷掉。

        参数:
            value:       候选文本。
            entity_type: 实体类型。
        返回:
            通过返回 True。
        """
        compact = " ".join(value.split())
        # 长度太短(<2)或太长(>120)都不要。
        if len(compact) < 2 or len(compact) > 120:
            return False
        if entity_type == "NUMERIC_VALUE" and re.fullmatch(
            r"\d+(?:,\d{3})*(?:\.\d+)?",
            compact,
        ) is None:
            return False
        if entity_type in {"PERSON", "ORG", "LOCATION", "PRODUCT"}:
            if (
                compact.count("(") != compact.count(")")
                or compact.count("[") != compact.count("]")
                or compact.count("{") != compact.count("}")
                or compact.count('"') % 2
            ):
                return False
            if re.fullmatch(r"(?:[A-Za-z]\.){1,4}", compact):
                return False
        # 不像真人名的 PERSON 直接刷掉。
        if entity_type == "PERSON" and is_likely_bad_person(compact):
            return False
        if entity_type == "PROJECT_NAME" and is_likely_bad_project_name(compact):
            return False
        if entity_type == "IDENTIFIER" and is_likely_bad_identifier(compact):
            return False
        # 纯泛化词刷掉。
        if _normalized(compact) in GENERIC_ENTITY_VALUES:
            return False
        # 一个字母或数字都没有(纯符号)刷掉。
        if not any(ch.isalnum() for ch in compact):
            return False
        return True


def extract_entities_for_benchmark(records: list[dict[str, Any]], max_entities: int = 5) -> list[dict[str, Any]]:
    """In-memory entity extraction for tests and small callers.

    中文说明：内存版的批量抽取(给测试和小批量调用用,不读写文件)。

    参数:
        records:      benchmark 记录列表(每条含 audit_id/dataset/group/text)。
        max_entities: 每条最多抽几个实体。
    返回:
        每条记录加上 entities 字段后的列表。
    """
    extractor = EntityExtractor()
    return [{"audit_id": row["audit_id"], "dataset": row["dataset"], "group": row["group"], "entities": extractor.extract(row["text"], max_entities)} for row in records]


def extract_entities_file(
    benchmark_path: str | Path,
    output_path: str | Path,
    max_entities: int = 5,
    max_samples: int | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Extract entities from benchmark JSONL and save entities.jsonl.

    中文说明：文件版的批量抽取(第 06 步主入口)。读入攻击基准 JSONL,逐条抽实体,写出
    entities.jsonl 及统计/manifest。

    参数:
        benchmark_path: 攻击基准文件路径。
        output_path:    实体输出路径(并派生 .stats/.manifest)。
        max_entities:   每条样本最多抽几个实体。
        max_samples:    最多处理多少条样本(用于试跑);None 表示不限。
        resume:         断点续跑:产物已存在则跳过。
        force:          强制重跑。
    返回:
        stats(字典):样本数与实体总数;若跳过则带 skipped_existing。
    """
    output = Path(output_path)
    manifest_path = output.with_suffix(".manifest.json")
    # 断点续跑:产物非空且 manifest 存在则跳过。
    if resume and not force and output.exists() and output.stat().st_size > 0 and manifest_path.exists():
        LOGGER.info("Skipping existing entities: %s", output)
        return {"output_path": str(output), "skipped_existing": True}

    extractor = EntityExtractor()
    rows = []
    samples = 0
    entities = 0
    for row in tqdm(read_jsonl(benchmark_path), desc="entities", unit="sample"):
        # 达到样本上限就停。
        if max_samples is not None and samples >= max_samples:
            break
        extracted = extractor.extract(row["text"], max_entities=max_entities)
        rows.append(
            {
                "audit_id": row["audit_id"],
                "dataset": row["dataset"],
                "group": row["group"],
                "doc_id": row.get("doc_id"),
                "entities": extracted,
            }
        )
        samples += 1
        entities += len(extracted)
    write_jsonl(rows, output)
    stats = {"output_path": str(output), "samples": samples, "entities": entities}
    # 统计信息写一份 .stats.json 和一份 .manifest.json。
    write_json(stats, output.with_suffix(".stats.json"))
    write_json(stats, output.with_suffix(".manifest.json"))
    LOGGER.info("Extracted entities for %s samples, entities=%s", samples, entities)
    return stats
