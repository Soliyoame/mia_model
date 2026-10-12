"""目标级判分；保留 v1/v2，显式选择 v3 才启用新的目标解析。

v1 的待复核与绑定复核语义不变。v2 对有效回答自动二分类，运行故障保持
invalid。formal 子命令通过独立评分配置接入正式续跑，不修改旧冻结入口。
"""

from __future__ import annotations

import html
import json
import math
import random
import re
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from src.llm.response_validation import detect_api_error_text
from src.utils.hash import sha256_file, sha256_obj, sha256_text
from src.shared_g.artifacts import ArtifactStore

JUDGMENT_VERSION = "binary_target_rules_v1"
FOLLOWUP_ARMS = ("correct_anchor", "remote_only")
Record = Mapping[str, Any]


def _format(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"<sup>\s*([+−-]?\d+)\s*</sup>", r"^\1", text, flags=re.I)
    superscripts = str.maketrans("⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹", "+-0123456789")
    text = re.sub(r"[⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+", lambda m: "^" + m[0].translate(superscripts), text)
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans({
        "–": "-", "—": "-", "−": "-", "‑": "-", "’": "'", "‘": "'", "“": '"', "”": '"',
    }))
    text = re.sub(r"\\(?:text|mathrm|mathbf)\s*\{([^{}]*)\}", r"\1", text)
    text = text.replace(r"\times", "×").replace(r"\%", "%")
    text = re.sub(r"\\(?:,|;|:|!|quad|qquad)\s*", " ", text)
    text = re.sub(r"\^\{([+-]?\d+)\}", r"^\1", text)
    text = re.sub(r"(?<=\d)\s*·\s*(?=\d)(?!10\^)", ".", text)
    text = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", text)
    text = re.sub(r"(?<![\w.,])\d{1,3}(?:(?:,\s*| )\d{3})+(?![\w,])",
                  lambda m: re.sub(r"[ ,]", "", m[0]), text)
    text = re.sub(r"\$([^$\n]+)\$", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def _key(value: str, *, case_sensitive: bool = False) -> str:
    text = _format(value)
    text = (text if case_sensitive else text.casefold()).strip(' \t\r\n".!?')
    # 只合并字母间的连字符格式，不丢掉数值的负号、范围或比较符。
    text = re.sub(r"(?<=[^\W\d_])\s*-\s*(?=[^\W\d_])", " ", text)
    text = re.sub(r"\s*([/(),;:%=<>+^])\s*", r"\1", text)
    return re.sub(r"^(?:a|an|the)\s+", "", text, flags=re.I).strip()


def _contains(text: str, part: str) -> bool:
    if not part:
        return False
    left = r"(?<!\w)" if part[0].isalnum() or part[0] == "_" else ""
    right = r"(?!\w)" if part[-1].isalnum() or part[-1] == "_" else ""
    return re.search(left + re.escape(part) + right, text) is not None


def _target_question(query: Record) -> str:
    question = str(query.get("question") or "").strip()
    anchor = str(query.get("anchor_claim") or "").strip()
    if anchor:
        anchor = re.sub(r"\s+", " ", anchor)
        if anchor[-1] not in ".!?":
            anchor += "."
        prefix = f"The source reports: “{anchor}” "
        if question.startswith(prefix):
            question = question[len(prefix):]
    return question


_SMALL = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20),
))
_TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_SCALES = {"billion": 10**9, "million": 10**6, "thousand": 1000}
_NUMBER_WORDS = set(_SMALL) | set(_TENS) | set(_SCALES) | {"hundred", "and", "point", "minus", "negative", "plus", "positive"}
_DIGITS = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


def _small_integer(words: list[str]) -> int | None:
    value = 0
    if len(words) >= 2 and words[0] in _SMALL and 0 < _SMALL[words[0]] < 10 and words[1] == "hundred":
        value = _SMALL[words[0]] * 100
        words = words[2:]
        if words[:1] == ["and"]:
            words = words[1:]
    if not words:
        return value
    if len(words) == 1 and words[0] in _SMALL:
        return value + _SMALL[words[0]]
    if words[0] in _TENS and (len(words) == 1 or len(words) == 2 and 0 < _SMALL.get(words[1], -1) < 10):
        return value + _TENS[words[0]] + (_SMALL[words[1]] if len(words) == 2 else 0)
    return None


def _word_number(text: str) -> Fraction | None:
    words = text.lower().replace("-", " ").split()
    sign = 1
    if words and words[0] in {"minus", "negative", "plus", "positive"}:
        sign = -1 if words.pop(0) in {"minus", "negative"} else 1
    if not words or words.count("point") > 1:
        return None
    decimals: list[str] = []
    if "point" in words:
        index = words.index("point")
        decimals, words = words[index + 1:], words[:index]
        if not decimals or any(w not in _SMALL or _SMALL[w] > 9 for w in decimals):
            return None
    total, last_scale = 0, 10**12
    while any(w in _SCALES for w in words):
        index = next(i for i, w in enumerate(words) if w in _SCALES)
        scale = _SCALES[words[index]]
        group = _small_integer(words[:index])
        if group is None or group == 0 or scale >= last_scale:
            return None
        total += group * scale
        last_scale = scale
        words = words[index + 1:]
        if words[:1] == ["and"]:
            words = words[1:]
    tail = _small_integer(words)
    if tail is None:
        return None
    fraction = Fraction(0)
    if decimals:
        fraction = Fraction(int("".join(str(_SMALL[w]) for w in decimals)), 10 ** len(decimals))
    return sign * (Fraction(total + tail) + fraction)


def _number_prefix(text: str) -> tuple[Fraction, str] | None:
    text = re.sub(rf"({_DIGITS})\s*(?:×|x|\*)\s*10\s*\^\s*([+-]?\d+)", r"\1e\2", text)
    text = re.sub(r"^10\s*\^\s*([+-]?\d+)", r"1e\1", text)
    match = re.match(rf"({_DIGITS})(?:\s*/\s*({_DIGITS}))?", text)
    if match:
        if any(len(number) > 512 or (exponent := re.search(r"[eE]([+-]?\d+)$", number)) and abs(int(exponent[1])) > 1000
               for number in (match[1], match[2]) if number is not None):
            return None
        try:
            value = Fraction(Decimal(match[1]))
            if match[2] is not None:
                value /= Fraction(Decimal(match[2]))
        except (InvalidOperation, ZeroDivisionError, ValueError, OverflowError):
            return None
        return value, text[match.end():].strip()
    matches = list(re.finditer(r"[A-Za-z]+(?:-[A-Za-z]+)*", text))
    ends = []
    for match in matches:
        if set(match[0].lower().replace("-", " ").split()) <= _NUMBER_WORDS:
            ends.append(match.end())
        else:
            break
    for end in reversed(ends):
        value = _word_number(text[:end])
        if value is not None:
            return value, text[end:].strip()
    return None


@dataclass(frozen=True)
class _Unit:
    dimensions: tuple[tuple[str, int], ...] = ()
    scale: Fraction = Fraction(1)
    offset: Fraction = Fraction(0)


def _unit(dim: str, scale: str | int | Fraction = 1, offset: str | int | Fraction = 0) -> _Unit:
    return _Unit(((dim, 1),), Fraction(scale), Fraction(offset))


# 单位表是确定的物理定义；不含样本特例、相似度阈值或可调容差。
_SYMBOL_UNITS = {
    "s": _unit("time"), "min": _unit("time", 60), "h": _unit("time", 3600),
    "d": _unit("time", 86400), "wk": _unit("time", 604800),
    "mo": _unit("calendar_month"), "y": _unit("calendar_month", 12), "yr": _unit("calendar_month", 12),
    "m": _unit("length"), "cm": _unit("length", "0.01"), "mm": _unit("length", "0.001"),
    "km": _unit("length", 1000), "µm": _unit("length", "0.000001"), "um": _unit("length", "0.000001"),
    "kg": _unit("mass"), "g": _unit("mass", "0.001"), "mg": _unit("mass", "0.000001"),
    "µg": _unit("mass", "0.000000001"), "ug": _unit("mass", "0.000000001"), "Mg": _unit("mass", 1000),
    "mol": _unit("amount"), "mmol": _unit("amount", "0.001"),
    "%": _unit("percentage", "0.01"), "K": _unit("temperature"),
    "°C": _unit("temperature", 1, "273.15"),
    "°F": _unit("temperature", Fraction(5, 9), Fraction(45967, 180)),
    "L": _Unit((("length", 3),), Fraction("0.001")),
    "l": _Unit((("length", 3),), Fraction("0.001")),
    "mL": _Unit((("length", 3),), Fraction("0.000001")),
    "ml": _Unit((("length", 3),), Fraction("0.000001")),
    "M": _Unit((("amount", 1), ("length", -3)), Fraction(1000)),
    "mM": _Unit((("amount", 1), ("length", -3))),
}
_WORD_UNITS: dict[str, _Unit] = {}
for _symbol, _names in {
    "s": "second seconds sec secs", "min": "minute minutes mins", "h": "hour hours hr hrs",
    "d": "day days", "wk": "week weeks wks", "mo": "month months", "y": "year years yrs",
    "m": "meter meters metre metres", "cm": "centimeter centimeters centimetre centimetres",
    "mm": "millimeter millimeters millimetre millimetres", "km": "kilometer kilometers kilometre kilometres",
    "kg": "kilogram kilograms", "g": "gram grams", "mg": "milligram milligrams", "ug": "microgram micrograms",
    "L": "liter liters litre litres", "mL": "milliliter milliliters millilitre millilitres",
    "%": "percent percentage", "K": "kelvin kelvins", "°C": "celsius", "°F": "fahrenheit",
}.items():
    for _name in _names.split():
        _WORD_UNITS[_name] = _SYMBOL_UNITS[_symbol]


def _parse_unit(text: str) -> _Unit | None:
    text = text.strip().replace("μ", "µ")
    text = re.sub(r"\bper\b", "/", text, flags=re.I)
    text = re.sub(r"\bdegrees?\s+(celsius|fahrenheit)\b", r"\1", text, flags=re.I)
    text = re.sub(r"([A-Za-zµ]+)\((\d+)\)", r"\1^\2", text)
    text = re.sub(r"\b(square|cubic)\s+(\w+)\b", lambda m: m[2] + ("^2" if m[1] == "square" else "^3"), text, flags=re.I)
    parts = re.split(r"\s*/\s*", text)
    if len(parts) > 2 or not text:
        return None
    dims: Counter[str] = Counter()
    scale, offset = Fraction(1), Fraction(0)
    for i, part in enumerate(parts):
        match = re.fullmatch(r"([A-Za-zµ%°]+)(?:\s*\^\s*([+-]?\d+))?", part.strip())
        if not match:
            return None
        unit = _SYMBOL_UNITS.get(match[1]) or _WORD_UNITS.get(match[1].lower())
        if unit is None:
            return None
        power = int(match[2] or 1) * (-1 if i else 1)
        if abs(power) > 6 or unit.offset and (len(parts) != 1 or power != 1):
            return None
        for name, exponent in unit.dimensions:
            dims[name] += exponent * power
        scale *= unit.scale ** power
        offset = unit.offset
    return _Unit(tuple(sorted((k, v) for k, v in dims.items() if v)), scale, offset)


def _noun_key(text: str) -> str:
    replacements = {"men": "man", "women": "woman", "children": "child", "people": "person", "indices": "index"}
    words = _key(text).split()
    return " ".join(replacements.get(w, w[:-3] + "y" if w.endswith("ies") else w[:-1] if w.endswith("s") and not w.endswith("ss") else w) for w in words)


def _count_noun(question: str) -> str | None:
    match = re.search(r"\bhow many\s+(.+?)(?=\s+(?:did|does|do|was|were|is|are|have|has|had|can|must|should|with|in|of|from|to|participated|received|underwent|provided|completed|contributed|remained)\b|[?]|$)", question, re.I)
    return match[1].strip() if match else None


def _question_unit(question: str) -> _Unit | None:
    if re.search(r"\bwhat (?:percentage|percent)\b", question, re.I):
        return _SYMBOL_UNITS["%"]
    noun = _count_noun(question)
    if noun:
        return _parse_unit(noun) or _unit("count:" + _noun_key(noun))
    match = re.search(r"\b(?:in|measured in|expressed in)\s+([A-Za-zµ°%]+(?:\s*/\s*[A-Za-zµ]+(?:\^\d+)?)?)\s*(?:[?,.]|$)", question)
    return _parse_unit(match[1]) if match else None


def _unit_and_qualifier(rest: str, question: str) -> tuple[_Unit, str, bool] | None:
    rest = rest.strip()
    if not rest:
        inferred = _question_unit(question)
        return inferred or _Unit(), "", inferred is not None
    noun = _count_noun(question)
    if noun and _noun_key(rest) == _noun_key(noun):
        return _question_unit(question) or _Unit(), "", True
    unit = _parse_unit(rest)
    if unit:
        return unit, "", True
    # 限定词不能丢弃；仅允许省略问题已经明说的量名。
    for end in range(len(rest), 0, -1):
        if rest[end - 1:end] != " ":
            continue
        unit = _parse_unit(rest[:end].strip())
        suffix = rest[end:].strip()
        if unit and suffix:
            qualifier = "" if _contains(_key(question), _key(suffix)) else _key(suffix)
            return unit, qualifier, True
    return None


@dataclass(frozen=True)
class _Quantity:
    kind: str
    values: tuple[Fraction, ...]
    unit: _Unit
    closed: tuple[bool, bool] = (True, True)
    qualifier: str = ""
    approximate: bool = False
    has_unit: bool = False

    def canonical(self) -> dict[str, Any]:
        values = [value * self.unit.scale + (self.unit.offset if self.kind != "spread" or i == 0 else 0)
                  for i, value in enumerate(self.values)]
        return {"kind": self.kind, "values": [str(v) for v in values], "dimensions": list(self.unit.dimensions),
                "closed": list(self.closed), "qualifier": self.qualifier, "approximate": self.approximate,
                "has_unit": self.has_unit}


def _quantity(value: str, question: str = "") -> _Quantity | None:
    text = _format(value).strip(' \t\r\n".!?')
    if re.search(r"\b(?:how old|age)\b", question, re.I):
        text = re.sub(r"([\dA-Za-z]+)[ -]+(y|yr|years?|months?)[ -]+old$", r"\1 \2", text, flags=re.I)
    text = re.sub(r"^(?:at(?! least\b| most\b)|for)\s+", "", text, flags=re.I)
    approximate = bool(re.match(r"^(?:about|approximately|around)\s+", text, re.I))
    text = re.sub(r"^(?:about|approximately|around)\s+", "", text, flags=re.I)
    # p/r 是变量名，不把任意公式当作单个数值。
    if re.search(r"\bp[ -]?value\b", question, re.I):
        text = re.sub(r"^[pP]\s*(?:=\s*)?(?=[<>=≤≥+\d.-])", "", text)
    if re.search(r"\bcorrelation\b", question, re.I):
        text = re.sub(r"^[rR]\s*=\s*", "", text)
    kind, closed = "point", (True, True)
    pieces = [text]
    match = re.fullmatch(r"between\s+(.+)\s+and\s+(.+)", text, re.I)
    if match:
        kind, pieces = "range", [match[1], match[2]]
    elif re.fullmatch(r"[\[(].+,.+[\])]", text):
        kind, pieces = "range", text[1:-1].split(",", 1)
        closed = (text[0] == "[", text[-1] == "]")
    elif re.search(r"\s+to\s+|(?<=[\d%])\s*-\s*(?=[+-]?\d)", text):
        pieces = re.split(r"\s+to\s+|(?<=[\d%])\s*-\s*(?=[+-]?\d)", re.sub(r"^from\s+", "", text, flags=re.I))
        kind = "range"
    elif re.search(r"±|\+\s*/\s*-", text):
        kind, pieces = "spread", re.split(r"±|\+\s*/\s*-", text)
    else:
        match = re.match(r"^(>=|<=|>|<|≥|≤|at least\b|at most\b|more than\b|less than\b|over\b|under\b)\s*", text, re.I)
        if match:
            op = match[1].lower()
            kind = "lower" if op in {">=", ">", "≥", "at least", "more than", "over"} else "upper"
            inclusive = op in {">=", "<=", "≥", "≤", "at least", "at most"}
            closed, pieces = (inclusive, inclusive), [text[match.end():]]
    if len(pieces) != (2 if kind in {"range", "spread"} else 1):
        return None
    parsed = [_number_prefix(piece.strip()) for piece in pieces]
    if any(part is None for part in parsed):
        return None
    numbers = [part[0] for part in parsed if part is not None]
    tails = [part[1] for part in parsed if part is not None]
    if len(tails) == 2:
        if not tails[0] and tails[1]:
            tails[0] = tails[1]
        elif not tails[1] and tails[0]:
            tails[1] = tails[0]
    units = [_unit_and_qualifier(tail, question) for tail in tails]
    if any(unit is None for unit in units):
        return None
    valid_units = [unit for unit in units if unit is not None]
    unit, qualifier, has_unit = valid_units[0]
    if any(other[0].dimensions != unit.dimensions or other[1:] != (qualifier, has_unit) for other in valid_units[1:]):
        return None
    if any(other[0] != unit for other in valid_units[1:]):
        if kind != "range":
            return None
        numbers = [value * other[0].scale + other[0].offset for value, other in zip(numbers, valid_units)]
        unit = _Unit(unit.dimensions)
    if kind == "range" and numbers[0] > numbers[1] or kind == "spread" and numbers[1] < 0:
        return None
    return _Quantity(kind, tuple(numbers), unit, closed, qualifier, approximate, has_unit)


def _quantity_comparison(reference: _Quantity, candidate: _Quantity) -> tuple[str | None, str]:
    expected, actual = reference.canonical(), candidate.canonical()
    if expected == actual:
        return "correct", "quantity_equivalent"
    dimensions = {name for name, _ in reference.unit.dimensions + candidate.unit.dimensions}
    if {"time", "calendar_month"} <= dimensions:
        return None, "calendar_conversion_undefined"
    if reference.has_unit != candidate.has_unit:
        return None, "unit_not_explicit_in_question"
    if reference.unit.dimensions != candidate.unit.dimensions:
        return "not_correct", "wrong_unit"
    if reference.qualifier != candidate.qualifier:
        return ("not_correct", "missing_required_condition") if not candidate.qualifier else (None, "condition_unconfirmed")
    if reference.approximate != candidate.approximate:
        return None, "precision_unconfirmed"
    if reference.kind != candidate.kind:
        return None, "numeric_relation_unconfirmed"
    if reference.closed != candidate.closed:
        return "not_correct", "wrong_bound"
    return "not_correct", "wrong_value"


def _expansion_start(long: str, short: str) -> int | None:
    letters = re.sub(r"[^\w]", "", short).lower()
    if not 2 <= len(letters) <= 16:
        return None
    index = len(long) - 1
    for i, letter in reversed(list(enumerate(letters))):
        while index >= 0 and (long[index].lower() != letter or i == 0 and index > 0 and long[index - 1].isalnum()):
            index -= 1
        if index < 0:
            return None
        if i:
            index -= 1
    return index


def _variants(answer: str, claim: str) -> set[str]:
    variants = {_key(answer)}
    for material in (answer, claim):
        text = _format(material)
        for match in re.finditer(r"([\w][\w /'-]*?)\s*\(([\w-]{2,20})\)", text):
            long, short = match[1], match[2]
            start = _expansion_start(long, short)
            if start is None:
                continue
            expansion = long[start:]
            paired = expansion + " (" + short + ")"
            for old, new in ((paired, expansion), (paired, short), (expansion, short), (short, expansion)):
                old_key, new_key = _key(old), _key(new)
                for variant in list(variants):
                    if _contains(variant, old_key):
                        variants.add(re.sub(r"(?<!\w)" + re.escape(old_key) + r"(?!\w)", new_key, variant))
    return {v for v in variants if v}


def _list_parts(text: str) -> list[str]:
    # 括号内的解释、缩写和例子不是新的必要项。
    depth, buffer, parts = 0, [], []
    text = re.sub(r"\((?:e\.g\.,?|for example)[^()]*\)", "", _format(text), flags=re.I)
    tokens = re.split(r"(\(|\)|,|;|\band\b)", text)
    for token in tokens:
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        if depth == 0 and token in {",", ";", "and"}:
            if "".join(buffer).strip():
                parts.append(_key("".join(buffer)))
            buffer = []
        else:
            buffer.append(token)
    if "".join(buffer).strip():
        parts.append(_key("".join(buffer)))
    return parts


def _is_list(question: str, answer: str) -> bool:
    cue = re.search(r"\b(?:list|enumerate|name all)\b|\b(?:what|which)\s+(?:(?:all|two|three|four|five|brain|named|ecologically valid)\s+)*(?:regions|components|conditions|factors|types|kinds|representations|paths|data sets|datasets|simulations|drugs|items|steps|methods)\b", question, re.I)
    return bool(cue and len(_list_parts(answer)) > 1)


def _list_comparison(answer: str, candidate: str, question: str, claim: str) -> tuple[str | None, str]:
    expected, actual = _list_parts(answer), _list_parts(candidate)
    context = re.search(r"\b(?:types|kinds) of (.+?)(?=\s+(?:does|did|do|were|was|are|is)\b|[?]|$)", question, re.I)
    if context:
        head = " " + _key(context[1])
        expected = [item.removesuffix(head) for item in expected]
        actual = [item.removesuffix(head) for item in actual]
    # 每个列表元素仍只允许冻结材料明示的名称等价。
    mapped = []
    for item in actual:
        matches = [i for i, ref in enumerate(expected) if item in _variants(ref, claim)]
        if len(matches) != 1:
            return None, "list_item_unconfirmed"
        mapped.append(matches[0])
    if len(mapped) != len(set(mapped)):
        return "not_correct", "duplicate_list_item"
    if set(mapped) != set(range(len(expected))):
        return "not_correct", "missing_required_item"
    ordered = re.search(r"\b(?:order|ordered|sequence|respectively|ranked)\b", question, re.I)
    if ordered and mapped != list(range(len(expected))):
        return "not_correct", "wrong_order"
    return "correct", "complete_list_equivalent"


def _answer_type(question: str, answer: str) -> str:
    if not question.strip() or not answer.strip():
        return "unknown"
    quantity = _quantity(answer, question)
    if quantity:
        return "quantity" if quantity.has_unit else "number"
    if _is_list(question, answer):
        return "list"
    if _number_prefix(_format(answer)) and re.search(r"\b(?:how many|amount|dose|dosage|value|rate|ratio|temperature|duration|range)\b", question, re.I):
        return "unknown"
    if re.search(r"\b(?:which|what)\b.*\b(?:name|called|drug|protein|strain|city|country|dataset|system|model|method|network|theorem|scale|treatment)\b|^(?:who|where)\b", question, re.I):
        return "name"
    if re.search(r"\b(?:what|which|how|when|why|who|whom|where)\b", question, re.I) or re.match(r"^(?:did|does|do|is|was|were|are)\b", question, re.I):
        return "text"
    return "unknown"


_PROPERTY_WORDS = {
    "duration": {"duration", "long", "length"}, "dose": {"dose", "dosage"},
    "age": {"age", "old"}, "author": {"author", "authors"}, "date": {"publication date", "publication year"},
    "temperature": {"temperature"}, "location": {"country", "city", "location"},
}


def _properties(text: str) -> set[str]:
    key = _key(text)
    if "?" in text:
        if re.search(r"\bhow long\b", text, re.I):
            return {"duration"}
        if re.search(r"\bhow old\b", text, re.I):
            return {"age"}
    return {name for name, words in _PROPERTY_WORDS.items() if any(_contains(key, word) for word in words)}


def _unrelated(piece: str, question: str, variants: set[str]) -> bool:
    if any(_contains(_key(piece), v) for v in variants):
        return False
    if re.search(r"\b(?:actually|correction|retract|instead|rather)\b", piece, re.I):
        return False
    target, mentioned = _properties(question), _properties(piece)
    head = re.sub(r"^(?:i|we) (?:cannot|can't|could not) (?:determine|identify|tell) (?:the )?", "", _key(piece)).strip(" ,.")
    explicit = any(re.match(re.escape(word) + r"(?:\s+(?:is|was|remains|unknown|unclear)\b|:|$)", head)
                   for words in _PROPERTY_WORDS.values() for word in words)
    return bool(explicit and target and mentioned and not target & mentioned)


def _refusal(piece: str, question: str, answer: str = "") -> bool:
    text = _key(piece)
    if re.fullmatch(r"(?:unknown|unclear|not (?:known|specified|provided|available)|i (?:do not|don't) know|i cannot answer)", text):
        return True
    if re.search(r"\b(?:i|we) (?:cannot|can't|could not|am unable to|are unable to) (?:answer|determine|tell|find|identify|confirm|infer|describe|list)\b|\b(?:i|we) (?:do not know|don't know|am not sure|are not sure)\b", text):
        return True
    if re.match(r"^(?:cannot|can't|unable to) (?:answer|determine|tell|find|identify|confirm|infer|describe|list)\b", text):
        return True
    if (answer and _contains(text, _key(answer)) and not re.search(r"\b(?:your question|the answer)\b", text)
            and re.search(r"\b(?:what|which)\b.*\b(?:not|no|unknown|unclear|missing|omit|lack)\b", question, re.I)):
        return False
    if re.search(r"^(?:this |provided |reference |available )?(?:text|reference(?: information)?|document|passage|source|information) (?:does not|doesn't|did not) (?:(?:explicitly|clearly|directly) )?(?:contain|provide|specify|state|mention|include|give|describe|list|report)\b", text):
        return True
    if re.search(r"^(?:there is |there was )?(?:no|insufficient|not enough) (?:relevant |specific )?(?:information|context|details)\b", text):
        return True
    if re.search(r"\b(?:is|was|remains) (?:unknown|unclear|not (?:known|specified|provided|reported))\b", text):
        if re.search(r"\b(?:what|which)\b.*\b(?:unknown|unclear|not known|not specified|not reported)\b", question, re.I):
            return False
        return bool(_properties(piece) & _properties(question))
    return False


def _object_ids(text: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for match in re.finditer(r"\b(marker|drug|compound|group|arm|cohort|protein|model|scale|trial|treatment)\s+([A-Za-z](?:\d+)?|\d+)\b", text, re.I):
        result.setdefault(match[1].lower(), set()).add(match[2].lower())
    return result


def _wrong_object(piece: str, question: str, answer: str) -> bool:
    expected = _object_ids(question)
    if not expected:
        expected = _object_ids(answer)
    actual = _object_ids(piece)
    return any(name in actual and actual[name].isdisjoint(values) for name, values in expected.items())


def _subject(question: str) -> str | None:
    match = re.fullmatch(r"(?:what|which) (?:is|was|are|were) (.+?)\?", question.strip(), re.I)
    return _key(match[1]) if match else None


def _fragments(piece: str, question: str) -> list[str]:
    result = [piece.strip()]
    stripped = re.sub(r"^(?:the answer (?:is|was)|answer\s*:|it (?:is|was)|they (?:are|were))\s*", "", piece, flags=re.I)
    stripped = re.sub(r"^(?:the )?(?:reference(?: text| information)?|text|source) (?:states|says|reports) that\s+", "", stripped, flags=re.I)
    if stripped != piece:
        result.append(stripped.strip(' "'))
    subject = _subject(question)
    if subject:
        match = re.match(re.escape(subject) + r" (?:is|was|are|were|equals)\s+(.+)$", _key(piece))
        if match:
            # 从原文取值，避免大小写单位被 casefold 后混淆。
            original = re.search(r"\b(?:is|was|are|were|equals)\s+(.+)$", piece, re.I)
            if original:
                result.append(original[1])
    # 问句给定的被动谓语允许前置答案，保持谓语和对象逐词一致。
    passive = re.search(r"\b(?:what|which)(?: [\w-]+){0,3} (was|were|is|are) (.+?)\?$", question, re.I)
    if passive:
        suffix = passive[1] + " " + passive[2]
        match = re.fullmatch(r"(.+?)\s+" + re.escape(suffix) + r"[.!]?", piece, re.I)
        if match:
            result.append(match[1])
    return list(dict.fromkeys(result))


def _negated(piece: str, variants: set[str]) -> bool:
    text = _key(piece)
    for variant in variants:
        if re.search(r"\b(?:not|never|no)\s+(?:(?:a|an|the)\s+)?" + re.escape(variant) + r"(?!\w)", text):
            return True
    return False


def _judge_piece(piece: str, question: str, answer: str, claim: str, kind: str, variants: set[str]) -> tuple[str | None, str, dict[str, Any]]:
    evidence: dict[str, Any] = {"text": piece}
    if _wrong_object(piece, question, answer):
        return "not_correct", "wrong_object", evidence
    if _refusal(piece, question, answer):
        return "not_correct", "refused", evidence
    if _negated(piece, variants):
        return "not_correct", "negated_target", evidence
    if re.search(r"\b(?:maybe|perhaps|i think|not sure whether|could be|might be)\b", piece, re.I):
        return None, "uncertain_target_assertion", evidence
    reference_quantity = _quantity(answer, question)
    for fragment in _fragments(piece, question):
        if reference_quantity:
            candidate = _quantity(fragment, question)
            if candidate:
                label, reason = _quantity_comparison(reference_quantity, candidate)
                return label, reason, {**evidence, "reference_quantity": reference_quantity.canonical(), "candidate_quantity": candidate.canonical()}
            # 数量分支不退回忽略大小写的名称匹配，否则 MG/mg 会被误放行。
            if claim and _contains(_key(claim, case_sensitive=True), _key(fragment, case_sensitive=True)) and _contains(_key(fragment, case_sensitive=True), _key(answer, case_sensitive=True)):
                return "correct", "claim_supported_quantity_excerpt", evidence
            continue
        if _key(fragment) in variants:
            return "correct", "exact_or_defined_name_equivalent", evidence
        if kind == "list":
            label, reason = _list_comparison(answer, fragment, question, claim)
            if label is not None:
                return label, reason, evidence
        # 冻结 claim 的完整片段是直接证据；不能仅因长回答含参考词就放行。
        if claim and _contains(_key(claim), _key(fragment)) and any(_contains(_key(fragment), v) for v in variants):
            return "correct", "claim_supported_target_excerpt", evidence
    # 直接给出相反极性，而不是对当前问题拒答。
    opposite = re.sub(r"\b(?:no|not|never)\s+", "", answer, flags=re.I)
    if opposite != answer and _key(piece) == _key(opposite):
        return "not_correct", "negation_reversed", evidence
    if _key(answer) in {"yes", "no"} and _key(piece) in {"yes", "no"}:
        return "not_correct", "negation_reversed", evidence
    if kind == "text":
        for first, second in (("increase", "decrease"), ("increased", "decreased"), ("increases", "decreases"),
                              ("higher", "lower"), ("positive", "negative"), ("present", "absent")):
            for old, new in ((first, second), (second, first)):
                if not _contains(_key(answer), old):
                    continue
                opposite = re.sub(r"\b" + old + r"\b", new, _key(answer))
                changed_claim = re.sub(r"\b" + old + r"\b", new, _key(claim))
                if _key(piece) == opposite or claim and _contains(changed_claim, _key(piece)) and _contains(_key(piece), opposite):
                    return "not_correct", "wrong_direction", evidence
    return None, "target_relation_unconfirmed", evidence


def _result(label: str | None, status: str, reason: str, kind: str, evidence: Any) -> dict[str, Any]:
    return {"version": JUDGMENT_VERSION, "label": label, "status": status,
            "score": int(label == "correct") if status == "resolved" else None,
            "reason": reason, "answer_type": kind, "label_source": "rule", "evidence": evidence}


def _rule_judgment(text: str, query: Record) -> dict[str, Any]:
    question, answer, claim = _target_question(query), str(query.get("answer") or ""), str(query.get("claim") or "")
    kind = _answer_type(question, answer)
    variants = _variants(answer, claim)
    if re.match(r"^(?:in what|where)\b", question, re.I):
        variants.update(re.sub(r"^in ", "", v) for v in list(variants))
    if re.match(r"^when\b", question, re.I):
        variants.update(re.sub(r"^at ", "", v) for v in list(variants))
    formatted = _format(text)
    split_pattern = r"(?<=[.!?])\s+(?=[A-Za-z0-9+-])|\s*;\s*|\s+but\s+"
    pieces = [formatted] if _key(formatted) in variants else [p.strip() for p in re.split(split_pattern, formatted) if p.strip()]
    relevant, supplements = [], []
    for piece in pieces:
        (supplements if _unrelated(piece, question, variants) else relevant).append(piece)
    evidence: dict[str, Any] = {"question": question, "reference": answer, "claim": claim, "supplementary_text": supplements, "pieces": []}
    if _key(answer) in {"unknown", "unclear", "not known", "not specified", "not provided"} and _key(formatted) == _key(answer):
        return _result(None, "needs_review", "reference_refusal_term_unconfirmed", kind, evidence)
    if relevant and all(_refusal(piece, question, answer) for piece in relevant):
        return _result("not_correct", "resolved", "refused", kind, {**evidence, "refusal_text": relevant})
    if kind == "unknown":
        return _result(None, "needs_review", "answer_type_unconfirmed", kind, evidence)
    if claim and _negated(claim, variants) and not re.search(r"\b(?:not|no|never|without|lack)\b", question, re.I):
        return _result(None, "needs_review", "reference_polarity_conflict", kind, evidence)
    if claim and not any(_contains(_key(claim), v) for v in variants):
        reference_quantity = _quantity(answer, question)
        comparisons = [_quantity_comparison(reference_quantity, candidate)[0] for fragment in _fragments(claim, question)
                       if reference_quantity and (candidate := _quantity(fragment, question))]
        if "correct" not in comparisons:
            return _result(None, "needs_review", "reference_not_supported_by_claim", kind, evidence)
    if not relevant:
        return _result("not_correct", "resolved", "wrong_target", kind, evidence)
    outcomes = []
    for piece in relevant:
        correction = bool(re.match(r"^(?:actually|correction|instead|rather)\b", piece, re.I))
        candidate = re.sub(r"^(?:actually|correction|instead|rather)\s*[:,]?\s*", "", piece, flags=re.I)
        label, reason, item = _judge_piece(candidate, question, answer, claim, kind, variants)
        item.update(label=label, reason=reason, correction=correction)
        evidence["pieces"].append(item)
        outcomes.append((label, reason, correction))
    expected_ids = _object_ids(question)
    explicit_target_correct = any(item["label"] == "correct" and any(
        _object_ids(item["text"]).get(name, set()) & identifiers for name, identifiers in expected_ids.items())
        for item in evidence["pieces"])
    if explicit_target_correct:
        kept = []
        for item, outcome in zip(evidence["pieces"], outcomes):
            if item["reason"] == "wrong_object":
                evidence["supplementary_text"].append(item["text"])
                item["scope"] = "other_object_supplement"
            else:
                kept.append(outcome)
        outcomes = kept
    labels = {label for label, _, _ in outcomes}
    if "correct" in labels and "not_correct" in labels:
        if outcomes[-1][2] and outcomes[-1][0] == "not_correct" and outcomes[-1][1] != "refused":
            return _result("not_correct", "resolved", "answer_retracted", kind, evidence)
        return _result(None, "needs_review", "conflicting_target_answers", kind, evidence)
    if None in labels:
        reason = next(reason for label, reason, _ in outcomes if label is None)
        return _result(None, "needs_review", reason, kind, evidence)
    label, reason, _ = outcomes[0]
    return _result(label, "resolved", reason, kind, evidence)


def judge_answer(response: Record, query: Record, *, review: Record | None = None, source_hash: str | None = None) -> dict[str, Any]:
    """判一个已保存响应；复核需绑定原始 query（包括其全部字段）与 source hash。

    review 必须注明 reviewer_type='assistant'、independent_human_annotation=False，
    含 label/status/reason/evidence 及 query_id/source_key/source_hash/query_sha256/
    response_sha256。争议保持 label=None/status='needs_review'。
    """
    raw = response.get("response")
    invalid = None
    if response.get("status") != "completed" or response.get("error"):
        invalid = "response_not_completed"
    elif not isinstance(raw, str) or not raw.strip():
        invalid = "empty_response"
    elif detect_api_error_text(raw):
        invalid = "api_error"
    elif not query.get("query_id") or not query.get("source_key") or any(response.get(k) != query.get(k) for k in ("query_id", "source_key")):
        invalid = "response_binding_mismatch"
    elif response.get("response_sha256") is not None and response["response_sha256"] != sha256_text(raw):
        invalid = "response_hash_mismatch"
    elif source_hash is not None and response.get("source_hash") not in (None, source_hash):
        invalid = "source_hash_mismatch"
    if invalid:
        return _result(None, "invalid", invalid, "unknown", {"query_id": query.get("query_id")})
    automatic = _rule_judgment(raw, query)
    if review is None:
        return automatic
    expected = {"query_id": query["query_id"], "source_key": query["source_key"], "source_hash": source_hash,
                "query_sha256": sha256_obj(query), "response_sha256": sha256_text(raw)}
    if not source_hash or any(review.get(k) != v for k, v in expected.items()):
        raise ValueError("review_identity_drift")
    status, label = review.get("status"), review.get("label")
    if (review.get("reviewer_type") != "assistant" or review.get("independent_human_annotation") is not False
            or not isinstance(review.get("reason"), str) or not review["reason"].strip()
            or not isinstance(review.get("evidence"), list) or not review["evidence"]
            or any(not isinstance(e, str) or not e.strip() for e in review["evidence"])
            or not (status == "resolved" and isinstance(label, str) and label in {"correct", "not_correct"}
                    or status == "needs_review" and label is None)
            or review["reason"] == "refused" and not (status == "resolved" and label == "not_correct")):
        raise ValueError("invalid_answer_review")
    return {**_result(label, status, review["reason"], automatic["answer_type"], list(review["evidence"])),
            "label_source": "assistant_review", "automatic": automatic, "binding": expected,
            "independent_human_annotation": False}


class IncompleteJudgmentError(RuntimeError):
    """只有诊断信息，不携带可被误用的部分最终分数或门控集合。"""

    def __init__(self, unresolved: list[dict[str, Any]]):
        self.unresolved = unresolved
        super().__init__(f"cell_judgments_incomplete:{len(unresolved)}")


def _unique(rows: Sequence[Record], name: str) -> dict[str, Record]:
    result = {str(row.get("query_id") or ""): row for row in rows}
    if "" in result or len(result) != len(rows):
        raise ValueError(f"{name}_missing_or_duplicate_query_id")
    return result


def resolved_scores(queries: Sequence[Record], responses: Sequence[Record], *, reviews: Mapping[str, Record] | None = None,
                    source_hashes: Mapping[str, str] | None = None, judgment_version: str = JUDGMENT_VERSION,
                    nli_config: NLIConfig | None = None, nli_backend: NLIBackend | None = None,
                    query_plan: Sequence[Record] | None = None) -> dict[str, int]:
    """全量定案后才返回 query 分数；是离线最终指标输入的必经检查。"""
    planned, observed = _unique(queries, "query"), _unique(responses, "response")
    if not planned or set(planned) != set(observed):
        raise ValueError("response_set_missing_or_extra")
    if len({q.get("dataset") for q in queries}) > 1:
        raise ValueError("one_dataset_cell_required")
    if reviews and not set(reviews) <= set(planned):
        raise ValueError("review_target_not_planned")
    if judgment_version == JUDGMENT_VERSION:
        judgments = {key: judge_answer(observed[key], q, review=(reviews or {}).get(key),
                                      source_hash=(source_hashes or {}).get(str(q.get("source_key")))) for key, q in planned.items()}
    elif judgment_version in {AUTOMATIC_JUDGMENT_VERSION, TARGETED_JUDGMENT_VERSION}:
        if reviews:
            raise ValueError("automatic_judgment_does_not_accept_assistant_reviews")
        pairs = paired_targets(query_plan or queries)
        items = [{"query": q, "response": observed[key], "paired_query": pairs.get(key),
                  "source_hash": (source_hashes or {}).get(str(q.get("source_key")))} for key, q in planned.items()]
        judgments = dict(zip(planned, judge_answers_auto(items, config=nli_config, backend=nli_backend,
                                                        judgment_version=judgment_version)))
    else:
        raise ValueError("unknown_judgment_version")
    unresolved = [{"query_id": key, "status": value["status"], "reason": value["reason"]}
                  for key, value in judgments.items() if value["status"] != "resolved"]
    if unresolved:
        raise IncompleteJudgmentError(unresolved)
    return {key: value["score"] for key, value in judgments.items()}


def gated_queries(queries: Sequence[Record], initial: Sequence[Record], *, reviews: Mapping[str, Record] | None = None,
                  source_hashes: Mapping[str, str] | None = None, judgment_version: str = JUDGMENT_VERSION,
                  nli_config: NLIConfig | None = None, nli_backend: NLIBackend | None = None) -> list[Record]:
    """独立离线门控适配器；不调用旧门控，也不启动任何追问。"""
    _unique(queries, "query")
    if len({q.get("dataset") for q in queries}) > 1:
        raise ValueError("one_dataset_cell_required")
    slots: dict[tuple[str, Any], dict[str, Record]] = {}
    for query in queries:
        key, arm = (str(query.get("source_key") or ""), query.get("slot_index")), query.get("arm")
        if not key[0] or type(key[1]) is not int or key[1] < 0 or arm not in ("initial", *FOLLOWUP_ARMS):
            raise ValueError("invalid_gate_query")
        slot = slots.setdefault(key, {})
        if arm in slot:
            raise ValueError("duplicate_gate_slot")
        slot[arm] = query
    if not slots or any(set(slot) != {"initial", *FOLLOWUP_ARMS} for slot in slots.values()):
        raise ValueError("incomplete_gate_plan")
    local = [q for q in queries if q["arm"] == "initial"]
    scores = resolved_scores(local, initial, reviews=reviews, source_hashes=source_hashes,
                             judgment_version=judgment_version, nli_config=nli_config,
                             nli_backend=nli_backend, query_plan=queries)
    triggered = {key for key, slot in slots.items() if scores[slot["initial"]["query_id"]] == 1}
    return [q for q in queries if q["arm"] in FOLLOWUP_ARMS and (q["source_key"], q["slot_index"]) in triggered]


AUTOMATIC_JUDGMENT_VERSION = "binary_target_rules_nli_v2"
TARGETED_JUDGMENT_VERSION = "binary_target_rules_nli_v3"
NLI_LABELS = ("entailment", "neutral", "contradiction")
NLI_INPUT_MODES = ("qa_pair", "target_claim")
TARGETED_INPUT_MODES = ("qa_pair", "target_statement")
REFUSAL_HYPOTHESES = (
    "I do not know the answer.",
    "I cannot answer this question.",
    "The answer is unknown.",
    "The provided information does not contain the answer.",
    "There is not enough information to determine the answer.",
    "The requested information is not specified.",
    "The question cannot be answered from the provided text.",
)


@dataclass(frozen=True)
class NLIConfig:
    """模型和输入参数只在此集中定义；离线实验 JSON 可显式固定全部值。"""

    model_id: str = "tasksource/deberta-base-long-nli"
    revision: str = "04dcf11f844b07bc57015169fca2b7d6df8299d5"
    snapshot_dir: str = "models/menta/deberta-base-long-nli"
    device: str = "cuda"
    dtype: str = "float32"
    batch_size: int = 4
    max_length: int = 1280
    window_overlap: int = 128
    input_mode: str = "qa_pair"
    threshold: float = 0.5
    classify_refusals: bool = True
    seed: int = 20261008

    def __post_init__(self) -> None:
        if self.device != "cuda" or self.dtype != "float32":
            raise ValueError("nli_requires_cuda_fp32")
        if self.batch_size != 4 or self.max_length != 1280:
            raise ValueError("nli_runtime_configuration_drift")
        if not 0 <= self.window_overlap < self.max_length // 2:
            raise ValueError("invalid_nli_window_overlap")
        if self.input_mode not in {*NLI_INPUT_MODES, *TARGETED_INPUT_MODES} or not math.isfinite(self.threshold) or not -1 <= self.threshold <= 1:
            raise ValueError("invalid_nli_decision_configuration")


class NLIBackend(Protocol):
    identity: dict[str, Any]

    def windows(self, question: str, response: str, hypothesis: str) -> list[dict[str, Any]]: ...

    def probabilities(self, pairs: Sequence[tuple[str, str]]) -> list[dict[str, float]]: ...


def paired_targets(queries: Sequence[Record]) -> dict[str, Record]:
    """只查冻结计划中的对应无锚点问句，不从回答反推目标。"""
    _unique(queries, "query")
    remote: dict[tuple[Any, Any, Any], Record] = {}
    for query in queries:
        if query.get("arm") in {"remote_only", "no_anchor"}:
            key = (query.get("source_key"), query.get("slot_index"), query.get("arm"))
            if key in remote:
                raise ValueError("duplicate_paired_target")
            remote[key] = query
    result = {}
    for query in queries:
        arm = {"correct_anchor": "remote_only", "anchored": "no_anchor"}.get(query.get("arm"))
        if arm:
            paired = remote.get((query.get("source_key"), query.get("slot_index"), arm))
            if paired is not None:
                result[str(query["query_id"])] = paired
    return result


def automatic_target(query: Record, paired_query: Record | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """展示和推理适配不修改原 query/hash，initial 始终使用自己的 answer。"""
    question = str(query.get("question") or "").strip()
    evidence = {"original_query_sha256": sha256_obj(query), "target_source": "original_question"}
    if query.get("arm") in {"correct_anchor", "anchored"}:
        required_arm = {"correct_anchor": "remote_only", "anchored": "no_anchor"}[query["arm"]]
        if paired_query is None:
            raise ValueError("missing_paired_target_question")
        if (paired_query.get("arm") != required_arm
                or any(query.get(k) != paired_query.get(k) for k in ("source_key", "slot_index", "answer", "claim"))
                or not paired_query.get("query_id") or paired_query["query_id"] == query.get("query_id")):
            raise ValueError("paired_target_identity_mismatch")
        question = str(paired_query.get("question") or "").strip()
        evidence.update(target_source="frozen_paired_question", paired_query_id=paired_query["query_id"],
                        paired_query_sha256=sha256_obj(paired_query))
    if not question or not str(query.get("answer") or "").strip():
        raise ValueError("missing_question_or_reference")
    # 只传判定需要的字段；不把 membership、旧标签、复核标签传给模型。
    target = {key: query.get(key) for key in ("query_id", "source_key", "answer", "claim", "arm", "slot_index")}
    target["question"] = question
    evidence["target_question"] = question
    return target, evidence


def _v2_result(label: str | None, reason: str, kind: str, evidence: Any, *, invalid: bool = False) -> dict[str, Any]:
    return {**_result(label, "invalid" if invalid else "resolved", reason, kind, evidence),
            "version": AUTOMATIC_JUDGMENT_VERSION}


def _claim_slot(fragment: str, answer: str, claim: str) -> str | None:
    """仅当整句除答案槽外逐字相同时抽取槽位；不做子串关键词放行。"""
    reference = _format(answer).strip(' ".!?')
    source = _format(claim).strip(' ".!?')
    actual = _format(fragment).strip(' ".!?')
    matches = list(re.finditer(r"(?<!\w)" + re.escape(reference) + r"(?!\w)", source, re.I))
    if not reference or len(matches) != 1:
        return None
    hit = matches[0]
    prefix, suffix = source[:hit.start()], source[hit.end():]
    if not prefix and not suffix:
        return None
    match = re.fullmatch(re.escape(prefix) + r"(.+?)" + re.escape(suffix), actual, re.I)
    return match[1] if match else None


def _v2_single_rule(text: str, query: Record) -> dict[str, Any] | None:
    question, answer, claim = query["question"], str(query["answer"]), str(query.get("claim") or "")
    kind = _answer_type(question, answer)
    variants = _variants(answer, claim)
    quantity = _quantity(answer, question)
    evidence: dict[str, Any] = {"question": question, "reference": answer, "text": text}
    fragments = _fragments(_format(text), question)
    slot = _claim_slot(text, answer, claim)
    if slot is not None:
        fragments.append(slot)
    for fragment in fragments:
        if quantity:
            negation = re.match(r"^(?:not|never)\s+(.+)$", fragment.strip(), re.I)
            if negation:
                denied = _quantity(negation[1], question)
                if denied and _quantity_comparison(quantity, denied)[0] == "correct":
                    return _v2_result("not_correct", "negated_target", kind, evidence)
            candidate = _quantity(fragment, question)
            if candidate:
                label, reason = _quantity_comparison(quantity, candidate)
                if label is not None:
                    return _v2_result(label, reason, kind, {**evidence,
                                      "reference_quantity": quantity.canonical(), "candidate_quantity": candidate.canonical()})
                return None
            continue
        if kind == "list":
            label, reason = _list_comparison(answer, fragment, question, claim)
            if label is not None:
                return _v2_result(label, reason, kind, evidence)
        if kind != "unknown" and _key(fragment) in variants:
            return _v2_result("correct", "exact_or_defined_name_equivalent", kind, evidence)
        # 仅完整答案槽的显式反转能直接判错。
        opposite = re.sub(r"\b(?:no|not|never)\s+", "", answer, flags=re.I)
        if opposite != answer and _key(fragment) == _key(opposite):
            return _v2_result("not_correct", "negation_reversed", kind, evidence)
        if _key(answer) in {"yes", "no"} and _key(fragment) in {"yes", "no"}:
            return _v2_result("not_correct", "negation_reversed", kind, evidence)
        if any(_key(fragment) in {"not " + v, "no " + v, "never " + v} for v in variants):
            return _v2_result("not_correct", "negated_target", kind, evidence)
        for left, right in (("increased", "decreased"), ("increase", "decrease"), ("higher", "lower"),
                            ("positive", "negative"), ("present", "absent")):
            for before, after in ((left, right), (right, left)):
                if _contains(_key(answer), before) and _key(fragment) == re.sub(r"\b" + before + r"\b", after, _key(answer)):
                    return _v2_result("not_correct", "wrong_direction", kind, evidence)
    return None


def _v2_rules(text: str, query: Record) -> dict[str, Any] | None:
    # v1 只提供参考冲突和明确拒答诊断；v2 不继承 claim 片段放行。
    old = _rule_judgment(text, query)
    if old["reason"] in {"reference_polarity_conflict", "reference_not_supported_by_claim"}:
        return None
    direct = _v2_single_rule(text, query)
    if direct is not None:
        return direct
    if old["status"] == "resolved" and old["reason"] == "refused":
        return {**old, "version": AUTOMATIC_JUDGMENT_VERSION}
    # 明确末句改口可以定案；混合长句、一般对象关系统一交给 NLI。
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Za-z])|\s*;\s*", _format(text)) if p.strip()]
    if (len(pieces) > 1 and re.fullmatch(r"(?:i|we) (?:retract|withdraw) (?:that|the previous|my previous) answer[.!]?", pieces[-1], re.I)
            and all(_v2_single_rule(piece, query) is not None for piece in pieces[:-1])):
        return _v2_result("not_correct", "answer_retracted", old["answer_type"], {"text": text})
    if len(pieces) > 1 and re.match(r"^(?:actually|correction|instead|rather)\b", pieces[-1], re.I):
        last = re.sub(r"^(?:actually|correction|instead|rather)\s*[:,]?\s*", "", pieces[-1], flags=re.I)
        verdict = _v2_single_rule(last, query)
        earlier = [_v2_single_rule(piece, query) for piece in pieces[:-1]]
        if verdict is not None and all(item is not None for item in earlier):
            return {**verdict, "reason": "answer_retracted" if verdict["label"] == "not_correct" else "answer_corrected",
                    "evidence": {**verdict["evidence"], "earlier_text": pieces[:-1], "correction_text": pieces[-1]}}
    return None


def _v3_surface(text: str) -> str:
    text = _format(text).strip(' ".!?')
    text = re.sub(r"(?<=\w)\s*-\s*(?=\w)", "-", text)
    text = re.sub(r"\bcannot\b", "can not", text, flags=re.I)
    return text


def _v3_templates(question: str) -> list[tuple[str, str]]:
    """仅用问题构造可逆的答案槽；不读取参考答案或 claim。"""
    q = _v3_surface(question)
    templates = []
    match = re.fullmatch(r"(?:what|which) (is|was|are|were) (.+)", q, re.I)
    if match and not re.match(r"(?:identified|used|measured|reported|called|defined)\b", match[2], re.I):
        templates.append((match[2] + " " + match[1] + " ", ""))
    match = re.fullmatch(r"how (was|were|is|are) (.+?) (described|characterized)", q, re.I)
    if match:
        templates.append((f"{match[2]} {match[1]} {match[3]} as ", ""))
    match = re.fullmatch(r"where (can|could|will|would|should|must) (.+?) (not )?be (.+)", q, re.I)
    if match:
        templates.append((f"{match[2]} {match[1]} {match[3] or ''}be {match[4]} ", ""))
    match = re.fullmatch(r"when (was|were|is|are) (.+?) (generated|published|released|measured|observed|collected|conducted|started|completed)", q, re.I)
    if match:
        templates.append((f"{match[2]} {match[1]} {match[3]} ", ""))
    match = re.fullmatch(r"what (does|do|did|can|could|will|would) (.+?) (represent|mean|produce|prevent|measure|contain|include|use|predict|encode)", q, re.I)
    if match:
        auxiliary, subject, verb = match.groups()
        if auxiliary.lower() in {"do", "does"}:
            predicate = verb + ("s" if auxiliary.lower() == "does" else "")
        elif auxiliary.lower() == "did":
            predicate = "did " + verb
        else:
            predicate = auxiliary + " " + verb
        templates.append((subject + " " + predicate + " ", ""))
        if verb.lower() in {"represent", "mean"}:
            templates.append((subject + " is ", ""))
    match = re.fullmatch(r"(?:what|which) (.+?) (has|have|had) (occurred|been observed|been reported)", q, re.I)
    if match:
        templates.append((match[1] + " of ", " " + match[2] + " " + match[3]))
    # 被动问句中，所问名词就是答案槽的主语。
    match = re.fullmatch(r"(?:what|which) (.+?) (was|were|is|are) (.+)", q, re.I)
    if match and re.match(r"(?:(?:systematically|primarily|mainly|originally|often)\s+)?"
                          r"(?:[\w-]+ed|used|found|known|shown|given|taken|made|"
                          r"(?:the|a|an) (?:main|primary|largest|smallest|first|most|only|best|barrier))\b", match[3], re.I):
        templates.append(("", " " + match[2] + " " + match[3]))
    match = re.fullmatch(
        r"(.+? )(?:what|which) ([\w -]+?) (was|were|is|are) (.+?) "
        r"(associated|observed|found|located|identified|detected|measured)(.*)", q, re.I)
    if match:
        front, _, auxiliary, subject, verb, tail = match.groups()
        templates.append((f"{subject} {auxiliary} {verb}{tail} {front.lower()}", ""))
        templates.extend((f"{subject} {verb}{tail} {auxiliary} {reporting} {front.lower()}", "")
                         for reporting in ("found", "observed", "reported"))
    match = re.fullmatch(r"(in|at|under|for) (?:what|which) .+? (do|does) (.+?) "
                         r"(enjoy|work|occur|function|operate|achieve|provide|use|show|remain|give)(.*)", q, re.I)
    if match:
        prep, auxiliary, subject, verb, tail = match.groups()
        templates.append((f"{subject} {verb}{'s' if auxiliary.lower() == 'does' else ''}{tail} {prep.lower()} ", ""))
    match = re.fullmatch(r"(?:what|which) [\w -]+? (do|does) (.+?) "
                         r"(perform|use|study|evaluate|compare|include|analyze|measure)(.*)", q, re.I)
    if match:
        auxiliary, subject, verb, tail = match.groups()
        conjugated = ("studies" if verb.lower() == "study" else verb + "s") if auxiliary.lower() == "does" else verb
        templates.append((f"{subject} {conjugated} ", tail))
    return list(dict.fromkeys(templates))


def _v3_template_slot(text: str, template: tuple[str, str]) -> str | None:
    prefix, suffix = (_v3_surface(part) for part in template)
    prefix = re.sub(r"^(?:a|an|the) ", "", prefix, flags=re.I)
    actual = re.sub(r"^(?:a|an|the) ", "", _v3_surface(text), flags=re.I)
    pattern = (re.escape(prefix) + r"\s+" if prefix else "") + r"(.+?)" + (r"\s+" + re.escape(suffix) if suffix else "")
    match = re.fullmatch(pattern, actual, re.I)
    return match[1] if match else None


_V3_EXTRA_UNITS = {
    "nM": _Unit((("amount", 1), ("length", -3)), Fraction("0.000001")),
    "µM": _Unit((("amount", 1), ("length", -3)), Fraction("0.001")),
    "uM": _Unit((("amount", 1), ("length", -3)), Fraction("0.001")),
    "nm": _unit("length", "0.000000001"),
    "J": _unit("energy"), "kJ": _unit("energy", 1000),
    "cal": _unit("energy", Fraction("4.184")), "kcal": _unit("energy", 4184),
}


def _v3_unit(text: str) -> _Unit | None:
    return _V3_EXTRA_UNITS.get(text.strip().replace("μ", "µ")) or _parse_unit(text)


def _v3_quantity(value: str, question: str) -> _Quantity | None:
    """先识别复合数值，再解析单位；第二个数值不能被吞进限定词。"""
    text = _v3_surface(value)
    text = re.sub(r"^(?:a|an|the) ", "", text, flags=re.I)
    if re.search(r"\b(?:rank|ranking|position)\b", question, re.I) and not re.search(r"\b(?:and|how many|total)\b", question, re.I):
        match = re.fullmatch(r"(\d+)(?:st|nd|rd|th)?(?: out of \d+)?", text, re.I)
        if match:
            return _Quantity("rank", (Fraction(match[1]),), _Unit())
    # 所问量名是可省略的引导语，不能删掉未出现在问题中的条件。
    prefix = re.match(r"^(.+?)\s+of\s+(?=[+-]?\d)", text, re.I)
    if prefix and _contains(_key(question), _key(prefix[1])):
        text = text[prefix.end():]
    if re.search(r"\d\s*(?:-|to)\s*\d", text):
        text = re.sub(r"\s+\((?:for|across) different [^()]+\)$", "", text, flags=re.I)
    ordered = bool(re.search(r"\brespectively\b", question, re.I))
    range_question = bool(re.search(r"\b(?:range|ranging|between|interval)\b", question, re.I))
    split = re.split(r"\s+(?:vs\.?|versus)\s+|\s+and\s+" if ordered else r"\s+and\s+", text, flags=re.I)
    if len(split) == 2 and (ordered or range_question) and all(_number_prefix(part.strip()) for part in split):
        parts, kind, closed = split, "ordered_values" if ordered else "range", (True, True)
    else:
        old = _quantity(text, question)
        if old and not re.search(r"\d|\b(?:and|vs|versus)\b", old.qualifier):
            return old
        if old:
            return None
        parts, kind, closed = [text], "point", (True, True)
        between = re.fullmatch(r"between (.+) and (.+)", text, re.I)
        if between:
            parts, kind = [between[1], between[2]], "range"
        elif re.search(r"\s+to\s+|(?<=[\d%])\s*-\s*(?=[+-]?\d)", text):
            parts = re.split(r"\s+to\s+|(?<=[\d%])\s*-\s*(?=[+-]?\d)", re.sub(r"^from ", "", text, flags=re.I))
            kind = "range"
        elif re.search(r"±|\+\s*/\s*-", text):
            parts, kind = re.split(r"±|\+\s*/\s*-", text), "spread"
        else:
            bound = re.match(r"^(>=|<=|>|<|≥|≤|at least\b|at most\b|more than\b|less than\b)\s*", text, re.I)
            if bound:
                kind = "lower" if bound[1].lower() in {">=", ">", "≥", "at least", "more than"} else "upper"
                inclusive = bound[1].lower() in {">=", "<=", "≥", "≤", "at least", "at most"}
                closed, parts = (inclusive, inclusive), [text[bound.end():]]
    if len(parts) != (2 if kind in {"range", "spread", "ordered_values"} else 1):
        return None
    parsed = [_number_prefix(part.strip()) for part in parts]
    if any(part is None for part in parsed):
        return None
    numbers = [part[0] for part in parsed if part is not None]
    tails = [part[1] for part in parsed if part is not None]
    if len(tails) == 2:
        if not tails[0]:
            tails[0] = tails[1]
        elif not tails[1]:
            tails[1] = tails[0]
    units = []
    for tail in tails:
        if re.search(r"\d|\b(?:and|vs|versus)\b", tail):
            return None
        found = None
        if not tail:
            unit = _question_unit(question)
            found = (unit or _Unit(), "", unit is not None)
        for end in [len(tail), *[m.start() for m in re.finditer(r"\s+", tail)]]:
            unit = _v3_unit(tail[:end])
            qualifier = tail[end:].strip()
            if unit:
                found = (unit, "" if _contains(_key(question), _key(qualifier)) else _key(qualifier), True)
                break
        if found is None:
            return None
        units.append(found)
    first, qualifier, has_unit = units[0]
    if any(unit.dimensions != first.dimensions or (qual, explicit) != (qualifier, has_unit) for unit, qual, explicit in units):
        return None
    if kind == "range" and numbers[0] * first.scale > numbers[1] * units[1][0].scale:
        return None
    if any(unit != first for unit, _, _ in units):
        numbers = [value * unit.scale + (unit.offset if kind != "spread" or i == 0 else 0)
                   for i, (value, (unit, _, _)) in enumerate(zip(numbers, units))]
        first = _Unit(first.dimensions)
    return _Quantity(kind, tuple(numbers), first, closed, qualifier, False, has_unit)


def _v3_format_unit_case(text: str, question: str, answer: str) -> str:
    # 仅恢复上下文清楚的摩尔浓度大小写，不把 mg/g 或 mM/µM 当成笔误。
    if re.search(r"\b(?:concentration|dissociation|affinity|linear range)\b", question, re.I):
        for match in re.finditer(r"(?<!\w)(nM|[µμu]M)(?!\w)", answer):
            symbol = match[1]
            text = re.sub(r"(?<=\d)\s*" + re.escape(symbol.lower()) + r"(?!\w)", " " + symbol, text)
    return text


def _v3_is_list(question: str, answer: str) -> bool:
    return _is_list(question, answer) or bool(
        len(_list_parts(answer)) > 1 and re.search(
            r"\b(?:what|which)\s+(?:(?:all|two|three|four|five|six)\s+)?[\w-]*s\b", question, re.I))


def _v3_kind(question: str, answer: str) -> str:
    quantity = _v3_quantity(answer, question)
    if quantity:
        return quantity.kind if quantity.kind in {"rank", "ordered_values"} else "quantity" if quantity.has_unit else "number"
    return "list" if _v3_is_list(question, answer) else _answer_type(question, answer)


def _v3_list_comparison(answer: str, candidate: str, question: str, claim: str) -> tuple[str | None, str]:
    expected, actual = _list_parts(answer), _list_parts(candidate)
    mapped = []
    for part in actual:
        matches = []
        for i, reference in enumerate(expected):
            for variant in _variants(reference, claim):
                if part == variant:
                    matches.append(i)
                elif part.endswith(" " + variant):
                    prefix = part[:-len(variant)].strip()
                    # 仅允许 claim 明示的类别前缀；不据字符串包含放行整个长句。
                    if (len(prefix.split()) <= 4 and not re.search(r"\b(?:not|no|except|without|rather)\b", prefix)
                            and _contains(_key(claim), prefix + " " + variant)):
                        matches.append(i)
        if len(set(matches)) != 1:
            return None, "list_item_unconfirmed"
        mapped.append(matches[0])
    if len(mapped) != len(set(mapped)):
        return "not_correct", "duplicate_list_item"
    if set(mapped) != set(range(len(expected))):
        return "not_correct", "missing_required_item"
    if re.search(r"\b(?:order|ordered|sequence|respectively|ranked)\b", question, re.I) and mapped != list(range(len(expected))):
        return "not_correct", "wrong_order"
    return "correct", "complete_list_equivalent"


def _v3_identifiers(text: str) -> set[str]:
    identifiers = set()
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", text):
        if sum(c.isupper() for c in word) >= 2 and len(word) >= 2:
            identifiers.add(word.removesuffix("s").casefold())
    return identifiers


def _v3_conflict(text: str, query: Record) -> tuple[str, dict[str, Any]] | None:
    question, answer, claim = query["question"], query["answer"], query.get("claim") or ""
    if re.search(r"\b(?:was|were|did)\b", question, re.I) and not _contains(_key(text), _key(answer)):
        for future in re.finditer(r"\b(?:will|would|may|might) (?:eventually |later |probably |likely )?([a-z]+)\b", text, re.I):
            stem = future[1].lower()
            past = stem + ("d" if stem.endswith("e") else "ed")
            if _key(answer) == past:
                return "future_event_not_observed_outcome", {"future_event": future[0], "reference_outcome": answer}
    for template in _v3_templates(question):
        opposite = tuple(re.sub(r"\bnot\s+", "", part, flags=re.I) if re.search(r"\bnot\b", part, re.I)
                         else re.sub(r"\b(is|was|are|were|can|could|will|would)\s+", r"\1 not ", part, count=1, flags=re.I)
                         for part in template)
        if opposite != template:
            slot = _v3_template_slot(text, opposite)
            if slot and _key(slot) in _variants(answer, claim):
                return "negation_reversed", {"question_template": template, "opposite_template": opposite}
    if _wrong_object(text, question, answer) and not any(
            _object_ids(text).get(name, set()) & ids for name, ids in _object_ids(question).items()):
        return "wrong_object", {"expected_objects": _object_ids(question), "actual_objects": _object_ids(text)}
    for first, second in (("before", "after"), ("with", "without")):
        for expected, actual in ((first, second), (second, first)):
            for match in re.finditer(r"\b" + expected + r"\s+([\w-]+(?:\s+[\w-]+)?)", question, re.I):
                phrase = match[1].split()[0]
                if (re.search(r"\b" + actual + r"\s+" + re.escape(phrase) + r"\b", text, re.I)
                        and not re.search(r"\b" + expected + r"\s+" + re.escape(phrase) + r"\b", text, re.I)):
                    return "wrong_condition", {"question_condition": match[0], "opposite_condition": actual + " " + phrase}
    # 明确不同的缩写/编号对象，不能由高蕴含概率覆盖。一般名称改写仍交给 NLI。
    expected_ids = _v3_identifiers(answer) - _v3_identifiers(question)
    actual_ids = _v3_identifiers(text) - _v3_identifiers(question)
    actual_ids.update(identifier for identifier in expected_ids if _contains(_v3_surface(text).casefold(), identifier))
    if (expected_ids and actual_ids and expected_ids.isdisjoint(actual_ids)
            and _key(text) not in _variants(answer, claim)):
        return "different_named_identifier", {"reference_identifiers": sorted(expected_ids), "response_identifiers": sorted(actual_ids)}
    return None


_V3_UNIT_PATTERN = "(?:" + "|".join(re.escape(u) for u in sorted(
    {*_SYMBOL_UNITS, *_WORD_UNITS, *_V3_EXTRA_UNITS, "μM", "μm"}, key=lambda s: (-len(s), s))) + r")(?![A-Za-z])"
_V3_VALUE_PATTERN = rf"{_DIGITS}\s*(?:{_V3_UNIT_PATTERN})?(?:\s*(?:to\b|-)\s*{_DIGITS}\s*(?:{_V3_UNIT_PATTERN})?)?"


def _v3_numeric_slots(text: str, question: str, reference: _Quantity) -> list[str]:
    slots = []
    if reference.kind == "ordered_values":
        match = re.search(r"\bfor (.+?) and (.+?),?\s+respectively[?]?$", question, re.I)
        if match:
            objects = [re.sub(r"\b(?:procedures?|techniques?|groups?|treatments?)\b", "", part, flags=re.I).strip() for part in match.groups()]
            values = []
            for subject in objects:
                hits = re.findall(re.escape(_v3_surface(subject)) + r"[^,;.!?]*?\b(?:was|were|is|are|:)\s*(" + _V3_VALUE_PATTERN + r")", text, re.I)
                if len(hits) != 1:
                    break
                values.append(hits[0])
            if len(values) == 2:
                slots.append(" vs ".join(values))
        return slots
    # 数值必须紧邻问题所问量名；其他百分比/组别数量不能充当答案。
    for noun in ("reduction", "increase", "decrease", "dose", "dosage", "duration", "intake", "concentration"):
        if not re.search(r"\b" + noun + r"\b", question, re.I):
            continue
        patterns = (rf"({_V3_VALUE_PATTERN})\s+{noun}\b",
                    rf"\b{noun}\s+(?:of|was|is|were|=)\s+({_V3_VALUE_PATTERN})")
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.I):
                prefix = text[max(0, match.start() - 30):match.start()]
                if not re.search(r"\b(?:not|no|never|instead of|rather than)\b[^,;.!?]*$", prefix, re.I):
                    slots.append(match[1])
    return slots


def _v3_single_rule(text: str, query: Record) -> dict[str, Any] | None:
    question, answer, claim = query["question"], query["answer"], query.get("claim") or ""
    kind = _v3_kind(question, answer)
    formatted = _v3_surface(_v3_format_unit_case(_format(text), question, answer))
    evidence = {"question": question, "reference": answer, "text": text, "normalized_text": formatted}
    fragments = _fragments(formatted, question)
    slot = _claim_slot(formatted, answer, claim)
    if slot:
        fragments.append(slot)
    for template in _v3_templates(question):
        slot = _v3_template_slot(formatted, template)
        if slot:
            fragments.append(slot)
    quantity = _v3_quantity(answer, question)
    if quantity:
        fragments.extend(_v3_numeric_slots(formatted, question, quantity))
        comparisons = []
        for fragment in dict.fromkeys(fragments):
            candidate = _v3_quantity(fragment, question)
            if candidate:
                label, reason = _quantity_comparison(quantity, candidate)
                if quantity.kind != candidate.kind and not quantity.qualifier and not candidate.qualifier:
                    label, reason = "not_correct", "wrong_numeric_relation"
                if label is not None:
                    comparisons.append((label, reason, candidate, fragment))
        if comparisons:
            label, reason, candidate, fragment = next((v for v in comparisons if v[0] != "correct"), comparisons[0])
            if len({v[0] for v in comparisons}) > 1:
                label, reason = "not_correct", "conflicting_target_values"
            return {**_v2_result(label, reason, kind, {**evidence, "target_fragment": fragment,
                      "reference_quantity": quantity.canonical(), "candidate_quantity": candidate.canonical()}),
                    "version": TARGETED_JUDGMENT_VERSION}
    for fragment in dict.fromkeys(fragments):
        if kind == "list":
            label, reason = _v3_list_comparison(answer, fragment, question, claim)
            if label is not None:
                return {**_v2_result(label, reason, kind, {**evidence, "target_fragment": fragment}), "version": TARGETED_JUDGMENT_VERSION}
        if not quantity:
            decision = _v2_single_rule(fragment, query)
            if decision:
                return {**decision, "version": TARGETED_JUDGMENT_VERSION, "evidence": {**evidence, "target_fragment": fragment}}
    return None


def _v3_rules(text: str, query: Record) -> dict[str, Any] | None:
    formatted = _v3_surface(text)
    old = _rule_judgment(text, query)
    if old["status"] == "resolved" and old["reason"] == "refused":
        return {**old, "version": TARGETED_JUDGMENT_VERSION}
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Za-z0-9+-])|\s*;\s*", _format(text)) if p.strip()]
    if re.search(r"\b(?:i|we) (?:retract|withdraw) (?:that|the previous|my previous) answer[.!]?$", formatted, re.I):
        return {**_v2_result("not_correct", "answer_retracted", _v3_kind(query["question"], query["answer"]), {"text": text}),
                "version": TARGETED_JUDGMENT_VERSION}
    if len(pieces) > 1 and re.match(r"^(?:actually|correction|instead|rather)\b", pieces[-1], re.I):
        last = re.sub(r"^(?:actually|correction|instead|rather)\s*[:,]?\s*", "", pieces[-1], flags=re.I)
        decision = _v3_single_rule(last, query)
        if decision:
            return {**decision, "reason": "answer_corrected" if decision["label"] == "correct" else "answer_retracted",
                    "evidence": {**decision["evidence"], "earlier_text": pieces[:-1]}}
    conflict = _v3_conflict(formatted, query)
    if conflict:
        reason, evidence = conflict
        return {**_v2_result("not_correct", reason, _v3_kind(query["question"], query["answer"]), {"text": text, **evidence}),
                "version": TARGETED_JUDGMENT_VERSION}
    if old["reason"] in {"reference_polarity_conflict", "reference_not_supported_by_claim"}:
        return None
    direct = _v3_single_rule(text, query)
    if direct:
        return direct
    if len(pieces) > 1:
        decisions = [_v3_single_rule(piece, query) for piece in pieces]
        if all(decision is not None for decision in decisions):
            wrong = next((decision for decision in decisions if decision["label"] == "not_correct"), None)
            if wrong:
                return {**wrong, "reason": "conflicting_target_answers", "evidence": {"pieces": decisions}}
    # 旧确定性规则仍可复用，v3 的冲突检查具有优先级。
    old_direct = _v2_rules(text, query)
    return {**old_direct, "version": TARGETED_JUDGMENT_VERSION} if old_direct else None


def _v3_nli_input(query: Record, response: str, mode: str) -> tuple[str, str, str, dict[str, Any]]:
    if mode == "qa_pair":
        hypothesis, actual_mode = nli_hypothesis(query, mode)
        return query["question"], response, hypothesis, {"input_mode": actual_mode}
    templates = _v3_templates(query["question"])
    answer = _v3_surface(str(query["answer"]))
    # 完整参考句不能被再塞进主语/宾语槽，无法确定时回退问答对。
    if not templates or re.search(r"\b(?:is|are|was|were|has|have|had|did|does|cannot|can not)\b", answer, re.I):
        hypothesis, _ = nli_hypothesis(query, "qa_pair")
        return query["question"], response, hypothesis, {"input_mode": "qa_pair", "statement_fallback": True}
    template = templates[0]
    prefix, suffix = template
    hypothesis = (prefix + answer + suffix).strip() + "."
    actual = _v3_surface(response)
    finite = re.search(r"\b(?:is|are|was|were|has|have|had|did|does|can|could|will|would|should|must|may|might|cannot|can not|"
                       r"\w+ed|represents?|means?|produces?|prevents?|measures?|contains?|includes?|uses?|predicts?|encodes?)\b", actual, re.I)
    short = len(actual.split()) <= 24 and not re.search(r"[.!?]\s|\b(?:but|however|although)\b", actual, re.I)
    if short and not finite:
        actual = (prefix + actual + suffix).strip() + "."
    else:
        actual = response
    return query["question"], actual, hypothesis, {"input_mode": "target_statement", "template": {"prefix": prefix, "suffix": suffix},
                                    "premise_origin": "question_and_response_only", "response_transformed": actual != response}


def nli_hypothesis(query: Record, input_mode: str) -> tuple[str, str]:
    question, answer = query["question"], str(query["answer"])
    if input_mode not in NLI_INPUT_MODES:
        raise ValueError("unknown_nli_input_mode")
    if input_mode == "target_claim":
        # 句号/问叹号后的大写句首或分号为边界，不拆 and/but，保留条件和否定。
        claim = str(query.get("claim") or "").strip()
        clauses = [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])|;\s+(?=[A-Z])", claim) if part.strip()]
        matches = [part for part in clauses if _contains(_key(part), _key(answer))]
        if len(matches) == 1:
            return matches[0], "target_claim"
    return f"Question: {question}\nAnswer: {answer}", "qa_pair"


def response_windows(tokenizer: Any, question: str, response: str, hypothesis: str, *,
                     max_length: int, overlap: int) -> list[dict[str, Any]]:
    """按原回答的字符区间分窗，每窗保留完整问题和假设，不丢尾部矛盾。"""
    prefix = f"Question: {question}\nAnswer: "

    def pair_length(piece: str) -> int:
        return len(tokenizer(prefix + piece, hypothesis, add_special_tokens=True, truncation=False)["input_ids"])

    full_length = pair_length(response)
    if full_length <= max_length:
        return [{"premise": prefix + response, "hypothesis": hypothesis, "char_start": 0,
                 "char_end": len(response), "input_tokens": full_length}]
    tokens = tokenizer(response, add_special_tokens=False, return_offsets_mapping=True)
    offsets = tokens["offset_mapping"]
    budget = max_length - pair_length("") - 4
    if budget <= overlap or not offsets:
        raise ValueError("nli_question_or_hypothesis_too_long")
    result, start = [], 0
    while start < len(offsets):
        end = min(len(offsets), start + budget)
        char_start = 0 if start == 0 else offsets[start][0]
        char_end = len(response) if end == len(offsets) else offsets[end - 1][1]
        while end > start and pair_length(response[char_start:char_end]) > max_length:
            end -= 1
            char_end = offsets[end - 1][1] if end > start else char_start
        if end <= start or end - start <= overlap and end != len(offsets):
            raise ValueError("nli_window_budget_exhausted")
        piece = response[char_start:char_end]
        result.append({"premise": prefix + piece, "hypothesis": hypothesis, "char_start": char_start,
                       "char_end": char_end, "input_tokens": pair_length(piece)})
        if end == len(offsets):
            break
        start = end - overlap
    return result


class LocalNLIPredictor:
    """复用 MEntA 的 snapshot/hash/标签检查，运行时不导入历史工作树。"""

    def __init__(self, config: NLIConfig):
        import os

        self.config = config
        root = Path(config.snapshot_dir).resolve()
        manifest_path = root / "pcv_snapshot_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("repo_id") != config.model_id or manifest.get("revision") != config.revision:
            raise ValueError("nli_snapshot_identity_mismatch")
        files = manifest["files"]
        if {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p != manifest_path} != set(files):
            raise ValueError("nli_snapshot_file_list_mismatch")
        for name, metadata in files.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or path.stat().st_size != metadata["size"] or sha256_file(path) != metadata["sha256"]:
                raise ValueError("nli_snapshot_hash_mismatch")
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError("nli_cuda_unavailable")
        torch.manual_seed(config.seed)
        torch.use_deterministic_algorithms(True)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(str(root), local_files_only=True, use_fast=True, trust_remote_code=False)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            str(root), local_files_only=True, dtype=torch.float32, trust_remote_code=False)
        labels = {int(k): str(v).casefold() for k, v in self._model.config.id2label.items()}
        if set(labels.values()) != set(NLI_LABELS) or len(labels) != 3:
            raise ValueError("nli_label_mapping_mismatch")
        self._indices = {label: index for index, label in labels.items()}
        self._model.to(device="cuda", dtype=torch.float32).eval()
        self.identity = {"model_id": config.model_id, "revision": config.revision,
                         "snapshot_manifest_sha256": sha256_file(manifest_path),
                         "device": torch.cuda.get_device_name(0), "dtype": "float32", "torch_version": torch.__version__,
                         "tokenizer_class": type(self._tokenizer).__name__, "id2label": labels,
                         "batch_size": config.batch_size, "max_length": config.max_length,
                         "window_overlap": config.window_overlap, "local_files_only": True}
        self.statistics: dict[str, Any] = {"forward_batches": 0, "pairs": 0, "input_tokens": 0, "inference_seconds": 0.0}

    def windows(self, question: str, response: str, hypothesis: str) -> list[dict[str, Any]]:
        return response_windows(self._tokenizer, question, response, hypothesis,
                                max_length=self.config.max_length, overlap=self.config.window_overlap)

    def probabilities(self, pairs: Sequence[tuple[str, str]]) -> list[dict[str, float]]:
        result = []
        for start in range(0, len(pairs), self.config.batch_size):
            batch = pairs[start:start + self.config.batch_size]
            encoded = self._tokenizer([p for p, _ in batch], [h for _, h in batch], padding=True,
                                      truncation=False, return_tensors="pt")
            if encoded["input_ids"].shape[1] > self.config.max_length:
                raise ValueError("nli_oversized_unwindowed_input")
            self.statistics["input_tokens"] += int(encoded["attention_mask"].sum())
            encoded = {key: value.to("cuda") for key, value in encoded.items()}
            self._torch.cuda.synchronize()
            tick = time.perf_counter()
            with self._torch.inference_mode():
                logits = self._model(**encoded).logits
                values = self._torch.softmax(logits.float(), dim=-1).cpu().tolist()
            self.statistics["inference_seconds"] += time.perf_counter() - tick
            self.statistics["forward_batches"] += 1
            self.statistics["pairs"] += len(batch)
            result.extend({label: float(v[index]) for label, index in self._indices.items()} for v in values)
        return result


class _UnavailableNLIBackend:
    """离线批处理保留模型加载失败，不下载、不降级，也不把故障计零。"""

    def __init__(self, config: NLIConfig, error: Exception):
        self.identity = {"model_id": config.model_id, "revision": config.revision, "error_type": type(error).__name__}
        self.statistics = {"forward_batches": 0, "pairs": 0, "input_tokens": 0, "inference_seconds": 0.0,
                           "load_error_type": type(error).__name__}

    def windows(self, question: str, response: str, hypothesis: str) -> list[dict[str, Any]]:
        return [{"premise": f"Question: {question}\nAnswer: {response}", "hypothesis": hypothesis}]

    def probabilities(self, pairs: Sequence[tuple[str, str]]) -> list[dict[str, float]]:
        raise RuntimeError("nli_model_unavailable")


def _offline_backend(config: NLIConfig) -> NLIBackend:
    try:
        return LocalNLIPredictor(config)
    except Exception as error:
        return _UnavailableNLIBackend(config, error)


def _validated_probabilities(backend: NLIBackend, pairs: Sequence[tuple[str, str]]) -> list[dict[str, float]]:
    values = backend.probabilities(pairs)
    if len(values) != len(pairs):
        raise ValueError("nli_prediction_count_mismatch")
    for value in values:
        if (set(value) != set(NLI_LABELS) or any(not math.isfinite(p) or not 0 <= p <= 1 for p in value.values())
                or abs(sum(value.values()) - 1) > 1e-5):
            raise ValueError("nli_invalid_probabilities")
    return values


def judge_answers_auto(items: Sequence[Record], *, config: NLIConfig | None = None,
                       backend: NLIBackend | None = None,
                       judgment_version: str = AUTOMATIC_JUDGMENT_VERSION) -> list[dict[str, Any]]:
    """批量自动判定，只读取 query/response/source_hash/paired_query；不接受复核定案。"""
    config = config or NLIConfig()
    if judgment_version not in {AUTOMATIC_JUDGMENT_VERSION, TARGETED_JUDGMENT_VERSION}:
        raise ValueError("unknown_automatic_judgment_version")
    modes = TARGETED_INPUT_MODES if judgment_version == TARGETED_JUDGMENT_VERSION else NLI_INPUT_MODES
    if config.input_mode not in modes:
        raise ValueError("input_mode_not_supported_by_judgment_version")
    results: list[dict[str, Any] | None] = [None] * len(items)
    pending: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index, item in enumerate(items):
        query, response = item["query"], item["response"]
        validity = judge_answer(response, query, source_hash=item.get("source_hash"))
        if validity["status"] == "invalid":
            results[index] = {**validity, "version": AUTOMATIC_JUDGMENT_VERSION}
            continue
        try:
            target, binding = automatic_target(query, item.get("paired_query"))
        except ValueError as error:
            results[index] = _v2_result(None, str(error), "unknown", {}, invalid=True)
            continue
        binding.update(query_id=query["query_id"], source_key=query["source_key"], source_hash=item.get("source_hash"),
                       response_sha256=sha256_text(response["response"]))
        rule = (_v3_rules if judgment_version == TARGETED_JUDGMENT_VERSION else _v2_rules)(response["response"], target)
        if rule is not None:
            results[index] = {**rule, "binding": binding}
        else:
            pending.append((index, target, binding))
    if not pending:
        return [{**r, "version": judgment_version} for r in results if r is not None]
    try:
        backend = backend or LocalNLIPredictor(config)
    except Exception as error:
        for index, target, binding in pending:
            results[index] = {**_v2_result(None, "nli_model_failure", _answer_type(target["question"], target["answer"]),
                                          {"error_type": type(error).__name__}, invalid=True), "binding": binding}
        return [{**r, "version": judgment_version} for r in results if r is not None]
    windows, requests, input_evidence = [], [], {}
    for index, target, binding in pending:
        try:
            raw = items[index]["response"]["response"]
            if judgment_version == TARGETED_JUDGMENT_VERSION:
                question, actual, hypothesis, details = _v3_nli_input(target, raw, config.input_mode)
                actual_mode = details["input_mode"]
                input_evidence[index] = details
                local = backend.windows(question, actual, hypothesis)
                if actual_mode == "target_statement":
                    local = [{**window, "offsets_refer_to": "nli_input_response"} for window in local]
            else:
                hypothesis, actual_mode = nli_hypothesis(target, config.input_mode)
                local = backend.windows(target["question"], raw, hypothesis)
            if not local:
                raise ValueError("nli_empty_window_list")
            requests.append((index, target, binding, actual_mode, len(windows), len(local)))
            windows.extend(local)
        except Exception as error:
            results[index] = {**_v2_result(None, "nli_input_failure", _answer_type(target["question"], target["answer"]),
                                          {"error_type": type(error).__name__}, invalid=True), "binding": binding}
    try:
        probabilities = _validated_probabilities(backend, [(w["premise"], w["hypothesis"]) for w in windows]) if windows else []
    except Exception as error:
        for index, target, binding, _, _, _ in requests:
            results[index] = {**_v2_result(None, "nli_model_failure", _answer_type(target["question"], target["answer"]),
                                          {"error_type": type(error).__name__}, invalid=True), "binding": binding,
                              "model": backend.identity}
        return [{**r, "version": judgment_version} for r in results if r is not None]
    for index, target, binding, actual_mode, start, count in requests:
        local = [{**w, "probabilities": p} for w, p in zip(windows[start:start + count], probabilities[start:start + count])]
        support = max(range(count), key=lambda j: local[j]["probabilities"]["entailment"])
        conflict = max(range(count), key=lambda j: local[j]["probabilities"]["contradiction"])
        score = local[support]["probabilities"]["entailment"] - local[conflict]["probabilities"]["contradiction"]
        label = "correct" if score >= config.threshold else "not_correct"
        results[index] = {**_v2_result(label, "nli_entails_target" if label == "correct" else "nli_target_not_established",
                                     _answer_type(target["question"], target["answer"]),
                                     {**input_evidence.get(index, {}), "input_mode": actual_mode, "requested_input_mode": config.input_mode,
                                      "windows": local, "strongest_support_window": support, "strongest_contradiction_window": conflict}),
                          "label_source": "nli", "model": backend.identity, "nli_score": score,
                          "threshold": config.threshold, "binding": binding}
    if config.classify_refusals:
        _nli_refusal_reasons(items, results, pending, backend)
    assert all(result is not None for result in results)
    return [{**r, "version": judgment_version} for r in results if r is not None]


def _nli_refusal_reasons(items: Sequence[Record], results: list[Any],
                        pending: Sequence[tuple[int, dict[str, Any], dict[str, Any]]], backend: NLIBackend) -> None:
    pairs, owners = [], []
    for index, target, _ in pending:
        result = results[index]
        text = items[index]["response"]["response"]
        if result["status"] != "resolved" or result["label"] != "not_correct":
            continue
        if not re.search(r"\b(?:unknown|cannot|can't|unable|not (?:know|specified|provided)|insufficient|no information|does not (?:contain|provide))\b", text, re.I):
            continue
        try:
            local_pairs, local_owners = [], []
            for hypothesis in REFUSAL_HYPOTHESES:
                for window in backend.windows(target["question"], text, f"Question: {target['question']}\nAnswer: {hypothesis}"):
                    local_pairs.append((window["premise"], window["hypothesis"]))
                    local_owners.append((index, hypothesis))
            pairs.extend(local_pairs)
            owners.extend(local_owners)
        except Exception as error:
            result.update(label=None, status="invalid", score=None, reason="nli_input_failure")
            result["evidence"]["refusal_error_type"] = type(error).__name__
    if not pairs:
        return
    try:
        probabilities = _validated_probabilities(backend, pairs)
    except Exception as error:
        for index in {owner[0] for owner in owners}:
            # 任何实际启动的推理失败都保持 invalid，不能隐藏成一次成功判错。
            results[index].update(label=None, status="invalid", score=None, reason="nli_model_failure")
            results[index]["evidence"]["refusal_error_type"] = type(error).__name__
        return
    for (index, hypothesis), values in zip(owners, probabilities):
        results[index]["evidence"].setdefault("refusal_probabilities", []).append({"hypothesis": hypothesis, **values})
        if values["entailment"] > max(values["neutral"], values["contradiction"]):
            results[index]["reason"] = "refused"


def judge_answer_auto(response: Record, query: Record, *, config: NLIConfig | None = None,
                      backend: NLIBackend | None = None, source_hash: str | None = None,
                      paired_query: Record | None = None,
                      judgment_version: str = AUTOMATIC_JUDGMENT_VERSION) -> dict[str, Any]:
    return judge_answers_auto([{"query": query, "response": response, "source_hash": source_hash,
                                "paired_query": paired_query}], config=config, backend=backend,
                              judgment_version=judgment_version)[0]


def _thresholded(prediction: Record, threshold: float) -> dict[str, Any]:
    result = dict(prediction)
    if result["status"] == "resolved" and result["label_source"] == "nli":
        label = "correct" if result["nli_score"] >= threshold else "not_correct"
        result.update(label=label, score=int(label == "correct"), threshold=threshold,
                      reason="nli_entails_target" if label == "correct" else "nli_target_not_established")
        if label == "not_correct":
            for values in result["evidence"].get("refusal_probabilities", []):
                if values["entailment"] > max(values["neutral"], values["contradiction"]):
                    result["reason"] = "refused"
    return result


def classification_summary(annotations: Sequence[Record], predictions: Sequence[Record]) -> dict[str, Any]:
    if len(annotations) != len(predictions):
        raise ValueError("annotation_prediction_count_mismatch")
    false_negatives = false_positives = disputes = refusal_errors = invalid = pending = 0
    known_resolved = expected_refusals = predicted_refusals = 0
    labels = Counter()
    for annotation, prediction in zip(annotations, predictions):
        labels[str(prediction["label"])] += 1
        expected_refusals += annotation.get("reason") == "refused"
        predicted_refusals += prediction.get("reason") == "refused" and prediction["status"] == "resolved"
        invalid += prediction["status"] == "invalid"
        pending += prediction["status"] == "needs_review"
        if annotation.get("label") is None:
            disputes += 1
        elif prediction["status"] == "resolved":
            known_resolved += 1
            false_negatives += annotation["label"] == "correct" and prediction["label"] != "correct"
            false_positives += annotation["label"] == "not_correct" and prediction["label"] == "correct"
            refusal_errors += (annotation.get("reason") == "refused") != (prediction.get("reason") == "refused")
    n = len(predictions)
    known_errors = false_negatives + false_positives
    unresolved_or_disputed = sum(a.get("label") is None or p["status"] != "resolved" for a, p in zip(annotations, predictions))
    upper_errors = known_errors + unresolved_or_disputed
    return {"responses": n, "automatic_resolved": n - invalid - pending,
            "automatic_coverage": (n - invalid - pending) / n if n else None,
            "false_negatives": false_negatives, "false_positives": false_positives,
            "known_errors": known_errors, "reference_disputes": disputes, "invalid": invalid, "needs_review": pending,
            "error_upper_bound_count": upper_errors, "error_upper_bound_rate": upper_errors / n if n else None,
            "accuracy_lower_bound": 1 - upper_errors / n if n else None,
            "known_resolved_denominator": known_resolved,
            "known_resolved_accuracy": 1 - known_errors / known_resolved if known_resolved else None,
            "expected_refusals": expected_refusals, "predicted_refusals": predicted_refusals,
            "refusal_reason_errors": refusal_errors, "labels": dict(labels),
            "final_metrics_available": invalid == 0 and pending == 0}


def source_folds(items: Sequence[Record], *, seed: int, folds: int) -> dict[str, int]:
    if folds < 2:
        raise ValueError("at_least_two_source_folds_required")
    source_datasets = {}
    for item in items:
        query = item["query"]
        key, dataset = query["source_key"], query.get("dataset", "")
        if key in source_datasets and source_datasets[key] != dataset:
            raise ValueError("source_dataset_mismatch")
        source_datasets[key] = dataset
    if len(source_datasets) < folds:
        raise ValueError("too_few_sources_for_folds")
    rng, result, offset = random.Random(seed), {}, 0
    for dataset in sorted(set(source_datasets.values())):
        keys = sorted(k for k, d in source_datasets.items() if d == dataset)
        rng.shuffle(keys)
        for index, key in enumerate(keys):
            result[key] = (offset + index) % folds
        offset += len(keys)
    return result


def calibrate_nli(items: Sequence[Record], predictions: Mapping[str, Sequence[Record]], *,
                  seed: int, folds: int, thresholds: Sequence[float],
                  judgment_version: str = AUTOMATIC_JUDGMENT_VERSION) -> dict[str, Any]:
    """折内选阈值，折外选输入；只读取开发 Assistant 对照，不读取 membership。"""
    input_modes = TARGETED_INPUT_MODES if judgment_version == TARGETED_JUDGMENT_VERSION else NLI_INPUT_MODES
    if set(predictions) != set(input_modes) or not thresholds:
        raise ValueError("two_fixed_input_modes_and_threshold_grid_required")
    if any(len(p) != len(items) for p in predictions.values()):
        raise ValueError("development_prediction_count_mismatch")
    if any(p["status"] != "resolved" for values in predictions.values() for p in values):
        raise ValueError("cannot_calibrate_with_invalid_predictions")
    assignments = source_folds(items, seed=seed, folds=folds)
    annotations = [item["annotation"] for item in items]

    def choose(values: Sequence[Record], indices: Sequence[int]) -> tuple[float, list[dict[str, Any]]]:
        curve = []
        for threshold in thresholds:
            summary = classification_summary([annotations[i] for i in indices],
                                             [_thresholded(values[i], threshold) for i in indices])
            curve.append({"threshold": threshold, **summary})
        selected = min(curve, key=lambda r: (r["error_upper_bound_count"], r["false_positives"], -r["threshold"]))
        return selected["threshold"], curve

    modes = {}
    for mode in input_modes:
        values = predictions[mode]
        oof: list[Any] = [None] * len(items)
        fold_records = []
        for fold in range(folds):
            train = [i for i, item in enumerate(items) if assignments[item["query"]["source_key"]] != fold]
            held = [i for i, item in enumerate(items) if assignments[item["query"]["source_key"]] == fold]
            threshold, curve = choose(values, train)
            for index in held:
                oof[index] = _thresholded(values[index], threshold)
            fold_records.append({"fold": fold, "threshold": threshold, "train_responses": len(train),
                                 "held_responses": len(held), "training_curve": curve,
                                 "held_summary": classification_summary([annotations[i] for i in held], [oof[i] for i in held])})
        modes[mode] = {"oof": classification_summary(annotations, oof), "folds": fold_records,
                       "oof_labels": [{"query_id": item["query"]["query_id"], "label": value["label"]}
                                      for item, value in zip(items, oof)]}
    selected_mode = min(input_modes, key=lambda mode: (modes[mode]["oof"]["error_upper_bound_count"],
                                                          modes[mode]["oof"]["false_positives"], mode != "qa_pair"))
    threshold, curve = choose(predictions[selected_mode], list(range(len(items))))
    return {"seed": seed, "source_folds": assignments, "modes": modes, "selected_input_mode": selected_mode,
            "selected_threshold": threshold, "full_development_curve": curve,
            "selection_order": ["out_of_fold_total_error", "out_of_fold_false_positive", "prefer_qa_pair"],
            "threshold_selection_order": ["total_error", "false_positive", "higher_threshold"]}


def _load_offline_inputs(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    _unique([r["query"] for r in rows], "offline_query")
    for row in rows:
        query, response = row["query"], row["response"]
        if row.get("query_sha256") != sha256_obj(query) or row.get("response_sha256") != sha256_text(response.get("response", "")):
            raise ValueError("offline_input_hash_mismatch")
        if row.get("paired_query") is not None and row.get("paired_query_sha256") != sha256_obj(row["paired_query"]):
            raise ValueError("offline_paired_query_hash_mismatch")
        if any(query.get(k) != response.get(k) for k in ("query_id", "source_key")):
            raise ValueError("offline_response_binding_mismatch")
        if row.get("annotation"):
            _check_annotation(row, row["annotation"])
    return rows


def _check_annotation(row: Record, annotation: Record) -> None:
    expected = {"query_id": row["query"]["query_id"], "source_key": row["query"]["source_key"],
                "source_hash": row["source_hash"], "query_sha256": row["query_sha256"],
                "response_sha256": row["response_sha256"]}
    if any(annotation.get(k) != value for k, value in expected.items()):
        raise ValueError("offline_annotation_binding_mismatch")
    if (annotation.get("reviewer_type") != "assistant" or annotation.get("independent_human_annotation") is not False
            or annotation.get("label") not in {None, "correct", "not_correct"}
            or not annotation.get("reason") or not annotation.get("evidence")
            or annotation.get("reason") == "refused" and annotation.get("label") != "not_correct"):
        raise ValueError("offline_annotation_invalid")


def _save_new_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def source_cluster_intervals(items: Sequence[Record], predictions: Sequence[Record], *,
                             seed: int, samples: int = 2000) -> dict[str, Any]:
    """以 source 为聚类单位，dataset 内重抽 source，计算回答误差率的区间。"""
    groups: dict[str, dict[str, list[int]]] = {}
    for index, item in enumerate(items):
        query = item["query"]
        groups.setdefault(query.get("dataset", ""), {}).setdefault(query["source_key"], []).append(index)
    clusters = []
    for dataset, sources in groups.items():
        local = []
        for key, indices in sources.items():
            summary = classification_summary([items[i]["annotation"] for i in indices], [predictions[i] for i in indices])
            local.append((key, len(indices), summary["known_errors"], summary["error_upper_bound_count"]))
        clusters.append((dataset, local))
    rng = random.Random(seed)
    known_rates, upper_rates = [], []
    for _ in range(samples):
        selected = [rng.choice(local) for _, local in clusters for _ in local]
        denominator = sum(r[1] for r in selected)
        known_rates.append(sum(r[2] for r in selected) / denominator)
        upper_rates.append(sum(r[3] for r in selected) / denominator)

    def interval(values: list[float]) -> list[float]:
        values.sort()
        return [values[int((len(values) - 1) * p)] for p in (0.025, 0.975)]

    source_rates = [r[3] / r[1] for _, local in clusters for r in local]
    return {"unit": "source_document", "stratified_by": "dataset", "seed": seed, "bootstrap_samples": samples,
            "confidence": 0.95, "sources": len(source_rates), "known_error_rate_ci95": interval(known_rates),
            "worst_case_error_rate_ci95": interval(upper_rates),
            "macro_source_worst_case_error_rate": sum(source_rates) / len(source_rates),
            "limitation": "Assistant 对照不是独立人工金标准；聚类区间不修正标注偏差。"}


def compare_judgments(items: Sequence[Record], predictions: Sequence[Record], *, seed: int,
                      judgment_version: str = AUTOMATIC_JUDGMENT_VERSION,
                      previous_predictions: Sequence[Record] | None = None) -> dict[str, Any]:
    from src.shared_g.scoring import repaired_judgment

    if len(items) != len(predictions):
        raise ValueError("comparison_prediction_count_mismatch")
    current_name = "v3" if judgment_version == TARGETED_JUDGMENT_VERSION else "v2"
    if previous_predictions is not None and (current_name != "v3" or len(previous_predictions) != len(items)):
        raise ValueError("previous_prediction_comparison_mismatch")
    legacy, v1, evidence = [], [], []
    for item, prediction in zip(items, predictions):
        query, response = item["query"], item["response"]
        old = repaired_judgment(response["response"], query["answer"], response["status"],
                                query.get("answer_aliases", query.get("aliases")), question=query["question"])
        old_binary = {"label": None if old["label"] == "invalid" else "correct" if old["label"] == "correct" else "not_correct",
                      "status": "invalid" if old["label"] == "invalid" else "resolved",
                      "reason": "refused" if old["label"] == "ambiguous" else old["reason"], "legacy": old}
        legacy.append(old_binary)
        v1_result = judge_answer(response, query, source_hash=item["source_hash"])
        v1.append(v1_result)
        evidence.append({"query_id": query["query_id"], "source_key": query["source_key"],
                         "dataset": query.get("dataset"), "stage": item.get("stage"), "cohort": item.get("cohort"),
                         "annotation": item["annotation"], "legacy": old_binary, "v1": v1_result, current_name: prediction})
    annotations = [item["annotation"] for item in items]
    versions = {"legacy": legacy, "v1": v1, current_name: predictions}
    if previous_predictions is not None:
        versions["v2"] = previous_predictions
        for row, prediction in zip(evidence, previous_predictions):
            row["v2"] = prediction
    result = {"summaries": {name: classification_summary(annotations, values)
                            for name, values in versions.items()},
              "source_cluster_intervals": {name: source_cluster_intervals(items, values, seed=seed)
                                           for name, values in versions.items() if name != "v1"},
              "per_dataset": {}, "per_stage": {}, "per_cohort": {}, "rows": evidence}
    for field in ("dataset", "stage", "cohort"):
        getters = [item["query"].get(field, item.get(field, "")) for item in items]
        for group in sorted(set(getters)):
            indices = [i for i, value in enumerate(getters) if value == group]
            result["per_" + field][group] = {name: classification_summary([annotations[i] for i in indices], [values[i] for i in indices])
                                                for name, values in versions.items()}
    result["macro_dataset"] = {name: {
        "automatic_coverage": sum(v[name]["automatic_coverage"] for v in result["per_dataset"].values()) / len(result["per_dataset"]),
        "worst_case_error_rate": sum(v[name]["error_upper_bound_rate"] for v in result["per_dataset"].values()) / len(result["per_dataset"])}
        for name in versions}
    return result


class FormalJudgmentRun(ArtifactStore):
    """复用冻结问答输入，支持新模型运行及历史回答重判。"""

    _shared_inputs = {"source_manifest.jsonl", "index_manifest.jsonl", "query_plan.jsonl"}

    def __init__(self, path: str | Path, root: Path | None = None, *, backend: NLIBackend | None = None):
        from src.shared_g.config import ExperimentConfig, load_config
        from src.utils.io import load_yaml

        root = (root or Path(__file__).resolve().parents[2]).resolve()
        self.spec_path = (root / path).resolve()
        self.spec = load_yaml(self.spec_path)
        if (set(self.spec) - {"primary_scoring_config"} != {"version", "base_config", "output_dir", "calibration", "development_report",
                               "adoption_reason", "scoring_datasets"} or self.spec["version"] != TARGETED_JUDGMENT_VERSION):
            raise ValueError("unsupported_formal_judgment_configuration")
        self.parent = ArtifactStore(load_config(self.spec["base_config"], root))
        self.scoring_datasets = tuple(self.spec["scoring_datasets"])
        if (not self.scoring_datasets or self.scoring_datasets != tuple(ds for ds in self.parent.config.datasets
                                                                       if ds in self.scoring_datasets)):
            raise ValueError("invalid_scoring_dataset_scope")
        self.calibration_path = (root / self.spec["calibration"]).resolve()
        calibration = json.loads(self.calibration_path.read_text(encoding="utf-8"))
        if calibration.get("version") != TARGETED_JUDGMENT_VERSION:
            raise ValueError("formal_calibration_version_mismatch")
        selected = calibration["selected_config"]
        self.nli_config = NLIConfig(**{**selected, "snapshot_dir": str((root / selected["snapshot_dir"]).resolve())})
        self.backend = backend
        self.metadata: dict[str, Any] = {}
        data = {**self.parent.config.data, "output_dir": self.spec["output_dir"],
                "answer_policy": {"matcher": TARGETED_JUDGMENT_VERSION, "labels": ["correct", "not_correct"],
                                  "refused": "not_correct", "invalid": "incomplete_run_no_final_metrics",
                                  "assistant_response_adjudications": False}}
        super().__init__(ExperimentConfig(root, self.spec_path, data))
        allowed = root / "artifacts/v25/formal"
        if (not self.config.output.is_relative_to(allowed) or self.config.output == allowed
                or self.config.output.is_relative_to(self.parent.config.output)
                or self.parent.config.output.is_relative_to(self.config.output)):
            raise ValueError("independent_scoring_output_required")
        metadata_path = self.config.output / "run_config.json"
        if metadata_path.exists():
            self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.config.root).as_posix()

    def path(self, name: str, dataset: str | None = None) -> Path:
        local = super().path(name, dataset)
        if dataset is None and name in self._shared_inputs:
            return self.parent.path(name)
        inherited = self.metadata.get("inherited_files", {})
        original = self.parent.path(name, dataset)
        if dataset is not None and name == "retrieval.jsonl" and not local.exists():
            if self._relative(original) in inherited or self.parent.config.data.get("reused_inputs"):
                return original
        if dataset is not None and (name == "index" or name.startswith("index/")):
            if (not super().path("index", dataset).exists()
                    and self._relative(self.parent.path("index/index.json", dataset)) in inherited):
                return original
        return local

    def activate(self) -> dict[str, Any]:
        """一次保存评分配置和已有输入；不生成新问答，也不复制大型原始材料。"""
        from datetime import datetime, timezone
        from src.shared_g.artifacts import write_once

        if self.metadata:
            return self.validate(frozen=True)
        self.parent.validate(frozen=True)
        if self.config.output.exists() and any(self.config.output.iterdir()):
            raise RuntimeError("scoring_output_not_empty")
        prospective = bool(self.parent.config.data.get("reused_inputs"))
        if prospective and any(self.parent.config.output.rglob("*responses.jsonl")):
            raise RuntimeError("new_generator_parent_must_not_contain_responses")
        manifest = Path(self.nli_config.snapshot_dir) / "pcv_snapshot_manifest.json"
        model = json.loads(manifest.read_text(encoding="utf-8"))
        if model.get("repo_id") != self.nli_config.model_id or model.get("revision") != self.nli_config.revision:
            raise ValueError("nli_snapshot_identity_mismatch")
        report_path = self.config.resolve(self.spec["development_report"])
        development = json.loads(report_path.read_text(encoding="utf-8"))
        inherited = {self._relative(p): sha256_file(p)
                     for p in sorted(self.parent.config.output.rglob("*")) if p.is_file()}
        inputs = [self.spec_path, self.parent.config.path, self.calibration_path, report_path, manifest]
        if self.spec.get("primary_scoring_config"):
            from .source_scoring import load_scoring_config

            primary_path = self.config.resolve(self.spec["primary_scoring_config"])
            primary = load_scoring_config(primary_path, project_root=self.config.root)
            if (set(primary["inputs"]) != set(self.scoring_datasets)
                    or any(self.config.resolve(path) != self.config.output for path in primary["inputs"].values())
                    or any(primary["scoring"][name] != self.config.data["scoring"][name]
                           for name in ("lambda", "operational_cutoff"))):
                raise ValueError("primary_scoring_input_or_parameter_drift")
            inputs.extend([primary_path, self.config.root / "src/evaluation/source_scoring.py"])
        self.metadata = {
            "version": TARGETED_JUDGMENT_VERSION, "run_role": "formal",
            "status": "frozen_before_victim" if prospective else "active_post_response_scoring",
            "created_at": datetime.now(timezone.utc).isoformat(), "config": self.spec,
            "config_sha256": sha256_file(self.spec_path), "module_sha256": sha256_file(Path(__file__)),
            "code_commit": self.git_commit(), "uncommitted_code_bound_by_sha256": True,
            "input_hashes": {self._relative(p): sha256_file(p) for p in inputs}, "inherited_files": inherited,
            "nli_config": asdict(self.nli_config), "source_unit": "source_document",
            "scoring_datasets": list(self.scoring_datasets),
            "post_response_correction": not prospective, "query_identity_reused": True,
            "adoption_reason": self.spec["adoption_reason"],
            "independent_validation_performed": False, "one_percent_acceptance_passed": False,
            "development_acceptance": development.get("acceptance"),
            "assistant_response_adjudications_used": False,
        }
        write_once(super().path("run_config.json"), self.metadata)
        return self.metadata

    def validate(self, frozen: bool = False) -> dict[str, Any]:
        self.parent.validate(frozen=True)
        if not self.metadata:
            raise RuntimeError("formal_scoring_activation_required")
        current = json.loads(super().path("run_config.json").read_text(encoding="utf-8"))
        if (current != self.metadata or current["config_sha256"] != sha256_file(self.spec_path)
                or current["module_sha256"] != sha256_file(Path(__file__))
                or current["nli_config"] != asdict(self.nli_config)):
            raise RuntimeError("formal_scoring_code_or_config_drift")
        for name, digest in {**current["input_hashes"], **current["inherited_files"]}.items():
            if sha256_file(self.config.resolve(name)) != digest:
                raise RuntimeError(f"formal_scoring_input_drift:{name}")
        if any(self.config.output.rglob("*.tmp")):
            raise RuntimeError("partial_write_preserved_manual_recovery_required")
        return current

    def responses(self, dataset: str, followup: bool) -> list[dict[str, Any]]:
        from src.shared_g.artifacts import request_records

        name = "followup_responses.jsonl" if followup else "initial_responses.jsonl"
        original = self.parent.path(name, dataset)
        inherited = (request_records(original)
                     if self._relative(original) in self.metadata.get("inherited_files", {}) else [])
        combined = inherited + request_records(super().path(name, dataset))
        _unique(combined, "formal_response")
        return combined

    def _data(self, dataset: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        from src.shared_g.artifacts import read_rows
        from src.shared_g.victim import validate_responses

        if dataset not in self.config.datasets:
            raise ValueError("unknown_dataset")
        if dataset not in self.scoring_datasets:
            raise ValueError("dataset_not_enabled_for_new_judgment")
        queries = [q for q in read_rows(self.path("query_plan.jsonl")) if q["dataset"] == dataset]
        query_map = _unique(queries, "formal_query")
        sources = {s["source_key"]: s["source_hash"] for s in read_rows(self.path("source_manifest.jsonl"))}
        paired = paired_targets(queries)
        items, entries = {}, {}
        for followup, phase in ((False, "initial"), (True, "followup")):
            responses = self.responses(dataset, followup)
            planned = [q for q in queries if (q["arm"] != "initial") == followup]
            planned_ids = {q["query_id"] for q in planned}
            if any(r["query_id"] not in planned_ids for r in responses):
                raise RuntimeError("unexpected_saved_response")
            # 已完成记录沿用原 provider/query/retrieval 校验；未完成请求留给 invalid 判定。
            completed = [r for r in responses if r.get("status") == "completed"]
            if completed:
                validate_responses(self.config, self, dataset, planned, completed)
            for response in responses:
                qid = response["query_id"]
                query = query_map[qid]
                items[qid] = {"query": query, "response": response, "paired_query": paired.get(qid),
                              "source_hash": sources[query["source_key"]]}
            saved = read_rows(super().path(f"{phase}_judgments.jsonl", dataset))
            _unique(saved, "formal_judgment")
            for entry in saved:
                qid, judgment = entry["query_id"], entry["judgment"]
                if (qid not in planned_ids or qid not in items or entry["input_sha256"] != sha256_obj(items[qid])
                        or entry["record_sha256"] != sha256_obj({k: v for k, v in entry.items() if k != "record_sha256"})
                        or judgment["version"] != TARGETED_JUDGMENT_VERSION):
                    raise RuntimeError("formal_judgment_binding_drift")
                if judgment["status"] == "resolved":
                    if judgment["label"] not in {"correct", "not_correct"} or judgment["score"] != int(judgment["label"] == "correct"):
                        raise RuntimeError("invalid_binary_judgment")
                elif judgment["status"] != "invalid" or judgment["label"] is not None or judgment["score"] is not None:
                    raise RuntimeError("invalid_binary_judgment")
                entries[qid] = entry
        fingerprints = {item["response"].get("system_fingerprint") for item in items.values()
                        if item["response"].get("provider_model_id")}
        if len(fingerprints) > 1:
            raise RuntimeError("victim_fingerprint_drift")
        gate_path = super().path("followup_gate.json", dataset)
        if gate_path.exists():
            expected = self._gate(queries, entries)
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            if (expected is None or gate.get("version") != TARGETED_JUDGMENT_VERSION
                    or gate.get("query_ids") != [q["query_id"] for q in expected]
                    or gate.get("initial_judgments_sha256") != sha256_file(super().path("initial_judgments.jsonl", dataset))):
                raise RuntimeError("frozen_followup_gate_drift")
        return queries, items, entries

    @staticmethod
    def _gate(queries: Sequence[Record], entries: Mapping[str, Record]) -> list[Record] | None:
        initial = [q for q in queries if q["arm"] == "initial"]
        if not initial or any(q["query_id"] not in entries or entries[q["query_id"]]["judgment"]["status"] != "resolved"
                              for q in initial):
            return None
        triggered = {(q["source_key"], q["slot_index"]) for q in initial
                     if entries[q["query_id"]]["judgment"]["score"] == 1}
        expected = [q for q in queries if q["arm"] in FOLLOWUP_ARMS and (q["source_key"], q["slot_index"]) in triggered]
        if len(expected) != 2 * len(triggered):
            raise RuntimeError("incomplete_gate_plan")
        return expected

    def _state(self, dataset: str, queries: Sequence[Record], items: Mapping[str, Record],
               entries: Mapping[str, Record]) -> dict[str, Any]:
        expected = self._gate(queries, entries)
        phases = {}
        for phase in ("initial", "followup"):
            qids = {q["query_id"] for q in queries if (q["arm"] == "initial") == (phase == "initial")}
            observed = qids & set(items)
            judged = qids & set(entries)
            values = [entries[qid]["judgment"] for qid in judged]
            phases[phase] = {"observed_responses": len(observed), "judged": len(judged),
                             "unscored": len(observed - judged), "labels": dict(Counter(v["label"] for v in values if v["label"] is not None)),
                             "invalid": sum(v["status"] == "invalid" for v in values),
                             "label_sources": dict(Counter(v["label_source"] for v in values)),
                             "reasons": dict(Counter(v["reason"] for v in values))}
        initial_ids = {q["query_id"] for q in queries if q["arm"] == "initial"}
        phases["initial"].update(planned=len(initial_ids), missing_responses=len(initial_ids - set(items)))
        required = None if expected is None else {q["query_id"] for q in expected}
        followup_ids = {q["query_id"] for q in queries if q["arm"] != "initial"} & set(items)
        phases["followup"].update(planned=None if required is None else len(required),
            missing_responses=None if required is None else len(required - set(items)),
            available_required=None if required is None else len(required & set(items)),
            historical_outside_gate=None if required is None else len(followup_ids - required),
            unscored_required=None if required is None else len((required & set(items)) - set(entries)))
        needed = initial_ids | (required or set())
        complete = required is not None and all(qid in entries and entries[qid]["judgment"]["status"] == "resolved"
                                               for qid in needed)
        invalid = sum(p["invalid"] for p in phases.values())
        return {"dataset": dataset, "version": TARGETED_JUDGMENT_VERSION,
                "status": "invalid" if invalid else "complete" if complete else "incomplete",
                "complete": complete and not invalid, "final_metrics_available": complete and not invalid,
                "post_response_correction": True, "initial": phases["initial"], "followup": phases["followup"]}

    def status(self, dataset: str) -> dict[str, Any]:
        self.validate(frozen=True)
        return self._state(dataset, *self._data(dataset))

    def score(self, dataset: str, max_new: int = 20000) -> dict[str, Any]:
        """重算或补算已有回答；按固定小批次保存，可在中断后跳过已有判定。"""
        import logging
        from src.shared_g.artifacts import append_request, write_json_atomic, write_once

        self.validate(frozen=True)
        if max_new < 1:
            raise ValueError("positive_wave_budget_required")
        queries, items, entries = self._data(dataset)
        pending = [q["query_id"] for q in queries if q["query_id"] in items and q["query_id"] not in entries][:max_new]
        started = time.perf_counter()
        before = dict(getattr(self.backend, "statistics", {}))
        if pending and self.backend is None:
            self.backend = _offline_backend(self.nli_config)
        if pending and (self.backend.identity.get("model_id") != self.nli_config.model_id
                        or self.backend.identity.get("revision") != self.nli_config.revision):
            raise RuntimeError("nli_backend_identity_drift")
        processed = 0
        for offset in range(0, len(pending), 64):
            qids = pending[offset:offset + 64]
            judgments = judge_answers_auto([items[qid] for qid in qids], config=self.nli_config,
                                          backend=self.backend, judgment_version=TARGETED_JUDGMENT_VERSION)
            for qid, judgment in zip(qids, judgments):
                entry = {"query_id": qid, "input_sha256": sha256_obj(items[qid]), "judgment": judgment}
                entry["record_sha256"] = sha256_obj(entry)
                phase = "initial" if items[qid]["query"]["arm"] == "initial" else "followup"
                append_request(super().path(f"{phase}_judgments.jsonl", dataset), entry)
                entries[qid] = entry
            processed += len(qids)
            logging.getLogger(__name__).info("judge dataset=%s completed=%d available=%d", dataset, len(entries), len(items))
            if any(j["status"] != "resolved" for j in judgments):
                break
        expected = self._gate(queries, entries)
        if expected is not None:
            write_once(super().path("followup_gate.json", dataset), {
                "version": TARGETED_JUDGMENT_VERSION, "initial_judgments_sha256": sha256_file(super().path("initial_judgments.jsonl", dataset)),
                "query_ids": [q["query_id"] for q in expected],
                "post_response_correction": self.metadata["post_response_correction"]})
        state = self._state(dataset, queries, items, entries)
        stats = getattr(self.backend, "statistics", {})
        state.update(new_judgments=processed, elapsed_seconds=time.perf_counter() - started,
                     model_statistics={k: v - before.get(k, 0) for k, v in stats.items() if isinstance(v, (int, float))})
        write_json_atomic(super().path("status.json", dataset), state)
        return state

    def _require_previous_cells(self, dataset: str) -> None:
        from src.shared_g.artifacts import read_rows, read_response_adjudications
        from src.shared_g.scoring import gated_queries as legacy_gate, source_scores as legacy_scores
        from src.shared_g.victim import response_records, validate_responses

        if dataset not in self.scoring_datasets:
            raise ValueError("dataset_not_enabled_for_new_judgment")
        for previous in self.config.datasets[:self.config.datasets.index(dataset)]:
            if previous in self.scoring_datasets:
                if not self._state(previous, *self._data(previous))["complete"]:
                    raise RuntimeError(f"previous_dataset_incomplete:{previous}")
            else:
                # 未切换的数据集按其原冻结评分验证完成度，不生成新版标签或分数。
                config = self.parent.config
                queries = [q for q in read_rows(self.parent.path("query_plan.jsonl")) if q["dataset"] == previous]
                sources = [s for s in read_rows(self.parent.path("source_manifest.jsonl")) if s["dataset"] == previous]
                initial, followup = response_records(self.parent, previous, False), response_records(self.parent, previous, True)
                decisions = read_response_adjudications(self.parent)
                policy = {"matcher": config.data["answer_policy"]["matcher"], "adjudications": decisions}
                validate_responses(config, self.parent, previous, [q for q in queries if q["arm"] == "initial"], initial)
                expected = legacy_gate(queries, initial, **policy)
                validate_responses(config, self.parent, previous, expected, followup)
                legacy_scores(sources, queries, initial, followup, config.data["scoring"]["lambda"], **policy)

    def retrieve(self, dataset: str, max_new: int = 200) -> dict[str, Any]:
        import shutil
        from src.shared_g.retrieval import retrieve, validate_retrieval
        from src.shared_g.artifacts import read_rows

        self.validate(frozen=True)
        if max_new < 1:
            raise ValueError("positive_wave_budget_required")
        self._require_previous_cells(dataset)
        saved = validate_retrieval(self.config, self, dataset, complete=False)
        planned = [q for q in read_rows(self.path("query_plan.jsonl")) if q["dataset"] == dataset]
        if len(saved) == len(planned):
            return {"stage": "retrieve", "dataset": dataset, "new_queries": 0, "complete": True}
        original, local = self.path("retrieval.jsonl", dataset), super().path("retrieval.jsonl", dataset)
        if original != local:
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, local)
        return retrieve(self.config, self, dataset, max_new)

    def _victim_summary(self, dataset: str, followup: bool, new_calls: int) -> dict[str, Any]:
        state = self.score(dataset)
        phase = "followup" if followup else "initial"
        progress = state[phase]
        missing = progress["missing_responses"]
        unscored = progress["unscored_required"] if followup else progress["unscored"]
        return {**state, "stage": phase, "new_calls": new_calls, "planned": progress["planned"],
                "completed": None if missing is None else progress["planned"] - missing,
                "cell_complete": state["complete"],
                "complete": missing == 0 and unscored == 0 and progress["invalid"] == 0}

    def run_victim(self, dataset: str, followup: bool, max_new: int = 200) -> dict[str, Any]:
        """新请求沿用冻结 prompt/provider 验证，只替换门控并保留旧请求只读。"""
        import logging
        from src.llm.factory import build_victim_client, llm_profile_identity, load_llm_profiles
        from src.llm.response_validation import strict_response_metadata_error
        from src.shared_g.artifacts import append_request
        from src.shared_g.retrieval import rag_prompt, validate_retrieval

        self.validate(frozen=True)
        if max_new < 1:
            raise ValueError("positive_wave_budget_required")
        queries, items, entries = self._data(dataset)
        planned = self._gate(queries, entries) if followup else [q for q in queries if q["arm"] == "initial"]
        if planned is None:
            raise RuntimeError("initial_judgments_incomplete")
        if any(item["response"].get("status") != "completed" for item in items.values()):
            raise RuntimeError("unresolved_or_invalid_victim_response_preserved")
        if any(entry["judgment"]["status"] == "invalid" for entry in entries.values()):
            raise RuntimeError("invalid_judgment_run_incomplete")
        pending = [q for q in planned if q["query_id"] not in items][:max_new]
        if not pending:
            return self._victim_summary(dataset, followup, 0)
        self._require_previous_cells(dataset)
        retrieval = validate_retrieval(self.config, self, dataset)
        profiles = load_llm_profiles({"llm_profiles_path": str(self.config.resolve(self.config.data["runtime"]["llm_profiles_path"]))})
        client, profile = build_victim_client(profiles, profile_name=self.config.data["runtime"]["victim_profile"])
        identity = llm_profile_identity(profile)
        if identity != llm_profile_identity(self.config.profiles()["victim"]):
            raise RuntimeError("victim_client_profile_drift")
        fingerprints = {r.get("system_fingerprint") for ds in self.config.datasets for flag in (False, True)
                        for r in self.responses(ds, flag) if r.get("provider_model_id")}
        if len(fingerprints) > 1:
            raise RuntimeError("victim_fingerprint_drift")
        policy = self.config.data["runtime"]["generation"]
        retrieval_hash = sha256_file(self.path("retrieval.jsonl", dataset))
        name = "followup_responses.jsonl" if followup else "initial_responses.jsonl"
        for count, query in enumerate(pending, 1):
            found = retrieval[query["query_id"]]
            context, prompt = rag_prompt(self.config, query, found["retrieved_chunks"])
            if sha256_text(context) != found["context_sha256"] or sha256_text(prompt) != found["prompt_sha256"]:
                raise RuntimeError("victim_prompt_drift")
            row = {"request_key": query["query_id"], "query_id": query["query_id"], "source_key": query["source_key"],
                   "arm": query["arm"], "slot_index": query["slot_index"], "status": "attempt_started",
                   "retrieval_sha256": retrieval_hash, "prompt_sha256": sha256_text(prompt), "profile_identity": identity}
            append_request(super().path(name, dataset), row)
            try:
                result = client.generate_with_metadata(prompt, temperature=policy["temperature"],
                                                         timeout=policy["timeout"], max_tokens=policy["max_tokens"])
                error = strict_response_metadata_error(result.content, provider_model_id=result.provider_model_id,
                    provider_request_id=result.provider_request_id, called_at=result.called_at,
                    expected_model_id=profile["model"], configured_model_version=profile["model_version"])
                valid = not error and result.retry_count == 0 and (not fingerprints or result.system_fingerprint in fingerprints)
                row.update(status="completed" if valid else "invalid_provider_response", response=result.content,
                           response_sha256=sha256_text(result.content), provider_model_id=result.provider_model_id,
                           provider_request_id=result.provider_request_id, system_fingerprint=result.system_fingerprint,
                           called_at=result.called_at, input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                           latency_ms=result.latency_ms, retry_count=result.retry_count)
                if not valid:
                    row["validation_code"] = error.split(":", 1)[0] if error else "retry_or_fingerprint_drift"
                fingerprints.add(result.system_fingerprint)
            except Exception as error:
                row.update(status="uncertain_transport", error_type=type(error).__name__)
            row["record_sha256"] = sha256_obj(row)
            append_request(super().path(name, dataset), row)
            logging.getLogger(__name__).info("victim dataset=%s phase=%s new=%d planned_new=%d status=%s",
                                            dataset, "followup" if followup else "initial", count, len(pending), row["status"])
            if row["status"] != "completed":
                self.score(dataset)
                raise RuntimeError("victim_invalid_response_stop_preserve_evidence")
            time.sleep(policy["request_interval_seconds"])
        return self._victim_summary(dataset, followup, len(pending))

    def report(self, dataset: str) -> dict[str, Any]:
        from src.shared_g.artifacts import read_rows, write_once
        from src.shared_g.evaluation import finite_json, metrics
        from src.evaluation.metrics import clopper_pearson_interval

        self.validate(frozen=True)
        queries, items, entries = self._data(dataset)
        state = self._state(dataset, queries, items, entries)
        if not state["complete"]:
            return {**state, "metrics": None}
        sources = [s for s in read_rows(self.path("source_manifest.jsonl")) if s["dataset"] == dataset]
        lookup = {(q["source_key"], q["arm"], q["slot_index"]): entries.get(q["query_id"]) for q in queries}
        scores = []
        for source in sources:
            key = source["source_key"]
            local = [lookup[key, "initial", i]["judgment"]["score"] for i in range(3)]
            row = {"source_key": key, "dataset": dataset, "group": source["group"],
                   "initial_bits": local, "local_only": sum(local)}
            for arm in FOLLOWUP_ARMS:
                bits = [lookup[key, arm, i]["judgment"]["score"] if local[i] else 0 for i in range(3)]
                row.update({f"{arm}_bits": bits, arm: sum(local) + self.config.data["scoring"]["lambda"] * sum(bits)})
            scores.append(row)
        results = metrics(self.config, scores)
        for value in results.values():
            fixed = value["fixed_cutoff"]
            correct = fixed["true_positive_count"] + fixed["negative_count"] - fixed["false_positive_count"]
            total = fixed["positive_count"] + fixed["negative_count"]
            fixed.update(accuracy=correct / total, accuracy_ci95=clopper_pearson_interval(correct, total))
        output = finite_json({**state, "run_role": "formal", "statistical_unit": "source_document", "source_count": len(scores),
                  "metrics": results, "answer_policy": self.config.data["answer_policy"],
                  "scoring_config_sha256": sha256_file(self.spec_path), "run_config_sha256": sha256_file(super().path("run_config.json")),
                  "independent_validation_performed": False, "one_percent_acceptance_passed": False,
                  "adoption_reason": self.spec["adoption_reason"],
                  "query_plan_sha256": sha256_file(self.path("query_plan.jsonl")),
                  "judgment_files_sha256": {phase: sha256_file(ArtifactStore.path(self, f"{phase}_judgments.jsonl", dataset))
                                             for phase in ("initial", "followup")
                                             if ArtifactStore.path(self, f"{phase}_judgments.jsonl", dataset).exists()},
                  "cost": {"available_historical_and_new_responses": len(items),
                           "responses_used": state["initial"]["planned"] + state["followup"]["planned"],
                           "historical_responses_outside_new_gate": state["followup"]["historical_outside_gate"]}})
        write_once(super().path("scores.jsonl", dataset), scores)
        write_once(super().path("report.json", dataset), output)
        return output

    def report_suite(self) -> dict[str, Any]:
        from src.shared_g.artifacts import read_rows, write_once
        from src.shared_g.evaluation import finite_json, paired_macro_auc_delta
        from src.evaluation.metrics import bootstrap_macro_auc_ci

        self.validate(frozen=True)
        states = {ds: self._state(ds, *self._data(ds)) for ds in self.scoring_datasets}
        if not all(state["complete"] for state in states.values()):
            return {"version": TARGETED_JUDGMENT_VERSION, "complete": False, "final_metrics_available": False,
                    "post_response_correction": self.metadata["post_response_correction"],
                    "scoring_datasets": list(self.scoring_datasets),
                    "per_dataset": states, "macro_auc": None}
        fingerprints = {r.get("system_fingerprint") for ds in self.config.datasets for flag in (False, True)
                        for r in self.responses(ds, flag)}
        if len(fingerprints) > 1:
            raise RuntimeError("formal_suite_fingerprint_drift")
        per_dataset = {ds: self.report(ds) for ds in self.scoring_datasets}
        if self.scoring_datasets != self.config.datasets:
            return {"version": TARGETED_JUDGMENT_VERSION, "complete": True, "final_metrics_available": True,
                    "full_suite_metrics_available": False,
                    "post_response_correction": self.metadata["post_response_correction"],
                    "scoring_datasets": list(self.scoring_datasets), "per_dataset": per_dataset,
                    "macro_auc": None, "macro_unavailable_reason": "different_scoring_versions_not_aggregated"}
        grouped = {ds: read_rows(ArtifactStore.path(self, "scores.jsonl", ds)) for ds in self.config.datasets}
        boot, seed = self.config.data["evaluation"]["bootstrap_samples"], self.config.data["seed"]
        keys = ("local_only", *FOLLOWUP_ARMS)
        output = finite_json({"version": TARGETED_JUDGMENT_VERSION, "complete": True, "final_metrics_available": True,
            "run_role": "formal", "post_response_correction": self.metadata["post_response_correction"],
            "statistical_unit": "source_document",
            "dataset_weighting": "equal", "per_dataset": per_dataset,
            "macro_auc": {arm: bootstrap_macro_auc_ci(grouped, score_key=arm, n_bootstrap=boot, seed=seed) for arm in keys},
            "paired_macro_auc_deltas": {other: paired_macro_auc_delta(grouped, "correct_anchor", other, boot, seed)
                                        for other in ("local_only", "remote_only")},
            "scoring_config_sha256": sha256_file(self.spec_path),
            "run_config_sha256": sha256_file(super().path("run_config.json")),
            "independent_validation_performed": False, "one_percent_acceptance_passed": False})
        write_once(super().path("report.json"), output)
        return output


def _offline_main() -> None:
    """python -m src.evaluation.answer_judgment 的简单离线入口。"""
    import argparse
    from datetime import datetime, timezone

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    calibration = sub.add_parser("calibrate", help="仅开发集五折校准，保存两种输入的全部概率")
    calibration.add_argument("--experiment", type=Path, required=True)
    calibration.add_argument("--output", type=Path, required=True)
    predict = sub.add_parser("predict", help="固定配置后，对已绑定问答自动判定")
    predict.add_argument("--input", type=Path, required=True)
    predict.add_argument("--calibration", type=Path, required=True)
    predict.add_argument("--output", type=Path, required=True)
    evaluate = sub.add_parser("evaluate", help="离线比较已存预测，无模型调用")
    evaluate.add_argument("--input", type=Path, required=True)
    evaluate.add_argument("--predictions", type=Path, required=True)
    evaluate.add_argument("--annotations", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--seed", type=int, default=20261008)
    evaluate.add_argument("--baseline-predictions", type=Path)
    evaluate.add_argument("--evaluation-role", choices=("seen_development", "independent_validation"))
    formal = sub.add_parser("formal", help="显式启用 v3 正式评分；原冻结入口保持不变")
    formal.add_argument("--config", type=Path, required=True)
    stages = formal.add_subparsers(dest="stage", required=True)
    stages.add_parser("activate", help="绑定固定输入和已选判分参数，不调用模型")
    for name in ("score", "status", "retrieve", "run-initial", "run-followup", "report"):
        stage = stages.add_parser(name)
        stage.add_argument("--dataset", required=name != "report", choices=("nfcorpus", "scidocs", "trec-covid"))
        if name in {"score", "retrieve", "run-initial", "run-followup"}:
            stage.add_argument("--max-new", type=int, default=20000 if name == "score" else 200)
    args = parser.parse_args()
    if args.command == "formal":
        import logging

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        run = FormalJudgmentRun(args.config)
        if args.stage == "activate":
            metadata = run.activate()
            result = {"version": metadata["version"], "status": metadata["status"], "output_dir": str(run.config.output),
                      "post_response_correction": metadata["post_response_correction"],
                      "independent_validation_performed": False}
        elif args.stage in {"run-initial", "run-followup"}:
            result = run.run_victim(args.dataset, args.stage == "run-followup", args.max_new)
        elif args.stage in {"score", "retrieve"}:
            result = getattr(run, args.stage)(args.dataset, args.max_new)
        elif args.stage == "report" and args.dataset is None:
            result = run.report_suite()
        else:
            result = getattr(run, args.stage)(args.dataset)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), flush=True)
        if result.get("status") == "invalid":
            raise SystemExit(1)
        return
    if args.output.exists():
        raise FileExistsError("refuse_offline_artifact_overwrite")
    started = datetime.now(timezone.utc).isoformat()
    tick = time.perf_counter()
    module_hash = sha256_file(Path(__file__))
    if args.command == "calibrate":
        experiment = json.loads(args.experiment.read_text(encoding="utf-8"))
        version = experiment.get("version", AUTOMATIC_JUDGMENT_VERSION)
        input_modes = TARGETED_INPUT_MODES if version == TARGETED_JUDGMENT_VERSION else NLI_INPUT_MODES
        if tuple(experiment["calibration"]["input_modes"]) != input_modes:
            raise ValueError("calibration_input_modes_mismatch")
        input_path = args.experiment.parent / experiment["development"]["input_file"]
        if sha256_file(input_path) != experiment["development"]["input_sha256"]:
            raise ValueError("development_input_hash_mismatch")
        items = _load_offline_inputs(input_path)
        config = NLIConfig(**experiment["model"], seed=experiment["seed"], classify_refusals=False)
        backend = _offline_backend(config)
        predictions = {}
        for mode in input_modes:
            print(json.dumps({"stage": "development", "input_mode": mode, "responses": len(items)}), flush=True)
            current = NLIConfig(**{**asdict(config), "input_mode": mode})
            predictions[mode] = judge_answers_auto(items, config=current, backend=backend, judgment_version=version)
        if any(p["status"] != "resolved" for values in predictions.values() for p in values):
            _save_new_json(args.output, {"version": version, "stage": "development_calibration",
                                        "status": "invalid", "predictions": predictions,
                                        "model_statistics": backend.statistics, "module_sha256": module_hash,
                                        "input_sha256": sha256_file(input_path), "started_at": started})
            raise RuntimeError("calibration_has_invalid_predictions_saved_without_threshold")
        selected = calibrate_nli(items, predictions, seed=experiment["seed"],
                                folds=experiment["calibration"]["folds"], thresholds=experiment["calibration"]["thresholds"],
                                judgment_version=version)
        selected_config = {**asdict(config), "input_mode": selected["selected_input_mode"],
                           "threshold": selected["selected_threshold"], "classify_refusals": True}
        result = {"version": version, "stage": "development_calibration",
                  "input_sha256": sha256_file(input_path), "experiment_sha256": sha256_file(args.experiment),
                  "module_sha256": module_hash, "model": backend.identity, "selected_config": selected_config,
                  "selection": selected, "predictions": predictions, "model_statistics": backend.statistics}
    elif args.command == "predict":
        selected = json.loads(args.calibration.read_text(encoding="utf-8"))
        version = selected.get("version", AUTOMATIC_JUDGMENT_VERSION)
        if selected["module_sha256"] != module_hash:
            raise ValueError("calibrated_code_hash_drift")
        items = _load_offline_inputs(args.input)
        config = NLIConfig(**selected["selected_config"])
        backend = _offline_backend(config)
        print(json.dumps({"stage": "fixed_predictions", "responses": len(items),
                          "input_mode": config.input_mode, "threshold": config.threshold}), flush=True)
        predictions = judge_answers_auto(items, config=config, backend=backend, judgment_version=version)
        result = {"version": version, "stage": "fixed_predictions",
                  "input_sha256": sha256_file(args.input), "module_sha256": module_hash,
                  "calibration_sha256": sha256_file(args.calibration), "config": asdict(config),
                  "model_statistics": backend.statistics,
                  "rows": [{"query_id": item["query"]["query_id"], "judgment": p} for item, p in zip(items, predictions)]}
    else:
        items = _load_offline_inputs(args.input)
        annotations = [json.loads(line) for line in args.annotations.read_text(encoding="utf-8").splitlines() if line.strip()]
        by_id = _unique(annotations, "annotation")
        if set(by_id) != {item["query"]["query_id"] for item in items}:
            raise ValueError("annotation_set_missing_or_extra")
        for item in items:
            annotation = by_id[item["query"]["query_id"]]
            _check_annotation(item, annotation)
            item["annotation"] = annotation
        saved = json.loads(args.predictions.read_text(encoding="utf-8"))
        version = saved.get("version", AUTOMATIC_JUDGMENT_VERSION)
        if saved["input_sha256"] != sha256_file(args.input):
            raise ValueError("prediction_input_hash_mismatch")
        predictions_by_id = _unique(saved["rows"], "prediction")
        if set(predictions_by_id) != set(by_id):
            raise ValueError("prediction_set_missing_or_extra")
        previous = None
        if args.baseline_predictions:
            baseline = json.loads(args.baseline_predictions.read_text(encoding="utf-8"))
            if baseline["input_sha256"] != sha256_file(args.input):
                raise ValueError("baseline_input_hash_mismatch")
            baseline_by_id = _unique(baseline["rows"], "baseline_prediction")
            if set(baseline_by_id) != set(by_id):
                raise ValueError("baseline_prediction_set_missing_or_extra")
            previous = [baseline_by_id[item["query"]["query_id"]]["judgment"] for item in items]
        result = compare_judgments(items, [predictions_by_id[item["query"]["query_id"]]["judgment"] for item in items],
                                   seed=args.seed, judgment_version=version, previous_predictions=previous)
        result.update(version=version, stage="offline_comparison",
                      input_sha256=sha256_file(args.input), predictions_sha256=sha256_file(args.predictions),
                      annotations_sha256=sha256_file(args.annotations))
        summary = result["summaries"]["v3" if version == TARGETED_JUDGMENT_VERSION else "v2"]
        role = args.evaluation_role or ("seen_development" if version == TARGETED_JUDGMENT_VERSION else "independent_validation")
        target_met = summary["final_metrics_available"] and summary["error_upper_bound_count"] <= len(items) // 100
        result["evaluation_role"] = role
        result["acceptance"] = {"max_error_rate": 0.01, "max_errors": len(items) // 100,
                                "passed": target_met if role == "independent_validation" else None,
                                "numerical_target_met": target_met,
                                "reference": "Assistant annotation, not independent human gold"}
    result.update(started_at=started, finished_at=datetime.now(timezone.utc).isoformat(),
                  elapsed_seconds=time.perf_counter() - tick)
    _save_new_json(args.output, result)
    print(json.dumps({"output": str(args.output), "elapsed_seconds": result["elapsed_seconds"],
                      "acceptance": result.get("acceptance"), "selection": result.get("selected_config")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    _offline_main()
