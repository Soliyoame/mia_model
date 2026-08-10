"""Token-level lexical-copy metrics for stealth-preserving queries."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any


ENTITY_SLOT = "{ENTITY}"
_TOKEN_RE = re.compile(r"\{ENTITY\}|[A-Za-z0-9]+(?:[.'’_-][A-Za-z0-9]+)*")
_WHITESPACE_RE = re.compile(r"\s+")


def replace_entity_values(text: str, values: Iterable[str]) -> str:
    """用统一槽位遮蔽目标实体，避免实体本身主导复制分数。"""

    result = str(text or "")
    ordered = sorted(
        {" ".join(str(value or "").split()) for value in values if str(value or "").strip()},
        key=len,
        reverse=True,
    )
    for value in ordered:
        body = r"\s+".join(re.escape(part) for part in value.split(" "))
        result = re.sub(
            rf"(?<!\w){body}(?!\w)",
            ENTITY_SLOT,
            result,
            flags=re.IGNORECASE,
        )
    return result


def normalized_tokens(text: str) -> list[str]:
    """NFKC 归一化并生成大小写无关 token。"""

    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(normalized)]


def ngram_containment(
    query_tokens: Sequence[str],
    source_tokens: Sequence[str],
    *,
    n: int = 5,
) -> float:
    """返回 query n-gram 中出现在 source 的比例。"""

    if n < 1:
        raise ValueError("n must be positive")
    if len(query_tokens) < n:
        return 0.0
    query_ngrams = [tuple(query_tokens[index : index + n]) for index in range(len(query_tokens) - n + 1)]
    source_ngrams = {
        tuple(source_tokens[index : index + n])
        for index in range(max(0, len(source_tokens) - n + 1))
    }
    copied = sum(ngram in source_ngrams for ngram in query_ngrams)
    return copied / len(query_ngrams)


def longest_common_contiguous_run(
    left: Sequence[str],
    right: Sequence[str],
) -> int:
    """计算最长连续公共 token 串长度，而非可跳词的 LCS。"""

    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_token in left:
        current = [0] * (len(right) + 1)
        for index, right_token in enumerate(right, start=1):
            if left_token == right_token:
                current[index] = previous[index - 1] + 1
                best = max(best, current[index])
        previous = current
    return best


def lexical_copy_scores(
    query: str,
    source_text: str,
    *,
    entity_values: Iterable[str] = (),
) -> dict[str, Any]:
    """对槽位遮蔽后的 query/source 计算字面复制指标。"""

    masked_query = replace_entity_values(query, entity_values)
    masked_source = replace_entity_values(source_text, entity_values)
    query_tokens = normalized_tokens(masked_query)
    source_tokens = normalized_tokens(masked_source)
    return {
        "masked_query": masked_query,
        "query_token_count": len(query_tokens),
        "source_token_count": len(source_tokens),
        "five_gram_containment": round(
            ngram_containment(query_tokens, source_tokens, n=5),
            6,
        ),
        "longest_common_token_run": longest_common_contiguous_run(
            query_tokens,
            source_tokens,
        ),
    }


def diversity_statistics(templates: Sequence[str]) -> dict[str, Any]:
    """汇总模板重复、开头集中度与 distinct-n。"""

    token_rows = [normalized_tokens(template) for template in templates]
    normalized_templates = [" ".join(tokens) for tokens in token_rows]
    template_counts = Counter(normalized_templates)
    opening_counts = Counter(tuple(tokens[:4]) for tokens in token_rows if tokens)

    def distinct(n: int) -> float:
        grams = [
            tuple(tokens[index : index + n])
            for tokens in token_rows
            for index in range(max(0, len(tokens) - n + 1))
        ]
        return len(set(grams)) / len(grams) if grams else 0.0

    total = len(templates)
    duplicates = sum(count - 1 for count in template_counts.values() if count > 1)
    dominant_opening = max(opening_counts.values(), default=0)
    return {
        "templates": total,
        "duplicate_templates": duplicates,
        "duplicate_template_rate": duplicates / max(1, total),
        "dominant_opening_4gram_rate": dominant_opening / max(1, total),
        "distinct_2": distinct(2),
        "distinct_3": distinct(3),
        "opening_4gram_counts": {
            " ".join(opening): count
            for opening, count in sorted(opening_counts.items())
        },
    }
