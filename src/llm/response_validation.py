"""Generator 响应的统一成功判定。

正式实验必须同时满足：回答不是 API/HTTP 错误文本、没有显式错误字段，并且 provider
返回的实际模型身份与冻结的具体模型完全一致。
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


_ERROR_STATUSES = frozenset(
    {
        "error",
        "failed",
        "failure",
        "unauthenticated",
        "unauthorized",
        "permission_denied",
        "resource_exhausted",
        "rate_limited",
        "unavailable",
    }
)

_LEADING_ERROR_PATTERN = re.compile(
    r"""(?ix)
    ^\s*
    (?:
        <!(?:doctype\s+html) |
        <html\b |
        (?:openai[-\s]?compatible\s+)?request\s+failed\b |
        (?:api|http|authentication|authorization)\s+error
        \s*(?::|\#|-|[45]\d{2}\b) |
        error\s*(?:code\s*)?[:#-]?\s*(?:http\s*)?[45]\d{2}\b |
        error\s*[:#-]\s*
        (?:
            (?:error\s+code\s*[:#-]?\s*)?(?:http\s*)?[45]\d{2}\b |
            (?:invalid|incorrect)\s+(?:api\s+)?key\b |
            api\s+key\s+(?:is\s+)?(?:invalid|not\s+valid)\b |
            unauthorized\b |
            unauthenticated\b |
            authentication\s+failed\b |
            authorization\s+failed\b |
            permission\s+denied\b |
            quota\s+exceeded\b |
            rate\s+limit
        ) |
        http\s+[45]\d{2}\b |
        (?:invalid|incorrect)\s+(?:api\s+)?key\b |
        api\s+key\s+(?:is\s+)?(?:invalid|not\s+valid)\b |
        unauthorized\b |
        unauthenticated\b |
        authentication\s+failed\b |
        authorization\s+failed\b |
        permission\s+denied\b |
        quota\s+exceeded\b |
        rate\s+limit(?:ed|\s+exceeded)?\b |
        resource\s+exhausted\b |
        model\s+[\w./:-]+\s+(?:was\s+)?not\s+found\s*[.!]?\s*$ |
        service\s+unavailable\b |
        upstream\s+(?:request\s+)?(?:timeout|error)\b
    )
    """
)


def _compact_error_detail(value: Any) -> str:
    """把 provider 错误载荷压成可审计但不过长的单行文本。"""

    if isinstance(value, Mapping):
        detail = {
            key: value.get(key)
            for key in ("code", "status", "type", "message")
            if value.get(key) not in (None, "")
        }
        value = detail or dict(value)
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    return " ".join(text.split())[:500]


def detect_api_error_text(text: str | None) -> str | None:
    """识别被 HTTP 200 或第三方 client 包装成普通回答的 API 错误。

    返回可记录的原因；普通模型回答返回 ``None``。规则优先识别完整 JSON 错误对象，
    再识别只出现在回答开头的常见 HTTP/API 错误页，避免仅凭正文中出现 ``error`` 一词
    就误伤正常回答。
    """

    stripped = str(text or "").strip()
    if not stripped:
        return None

    try:
        payload = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        payload = None

    if isinstance(payload, Mapping):
        error_value = payload.get("error")
        if error_value not in (None, False, "", {}):
            return f"structured_api_error:{_compact_error_detail(error_value)}"
        if payload.get("success") is False:
            return f"structured_api_failure:{_compact_error_detail(payload)}"
        status = str(payload.get("status") or "").strip().casefold()
        if status in _ERROR_STATUSES:
            return f"structured_api_status:{_compact_error_detail(payload)}"

    match = _LEADING_ERROR_PATTERN.search(stripped[:2000])
    if match:
        excerpt = " ".join(stripped[:500].split())
        return f"api_error_text:{excerpt}"
    return None


def generator_response_error(
    content: str | None,
    *,
    provider_model_id: str | None,
    expected_model_id: str | None = None,
    require_provider_model_id: bool = False,
) -> str | None:
    """返回响应失败原因；满足全部协议条件时返回 ``None``。"""

    response = str(content or "").strip()
    if not response:
        return "empty_response"

    api_error = detect_api_error_text(response)
    if api_error:
        return api_error

    expected = str(expected_model_id or "").strip()
    actual = str(provider_model_id or "").strip()
    if (require_provider_model_id or expected) and not actual:
        return f"provider_model_identity_missing: expected={expected!r}"
    if expected and actual != expected:
        return (
            "provider_model_identity_drift:"
            f" expected={expected!r} actual={actual!r}"
        )
    return None


def response_record_is_success(
    row: Mapping[str, Any],
    *,
    expected_model_id: str | None = None,
) -> bool:
    """以统一 fail-closed 规则判断 JSONL 响应能否用于 resume、解析和论文统计。"""

    if not row.get("query_id") or row.get("error"):
        return False
    row_expected = (
        str(
            row.get("generator_id")
            or row.get("concrete_model")
            or ""
        ).strip()
        or None
    )
    expected = str(expected_model_id or "").strip() or row_expected
    validation_error = generator_response_error(
        str(row.get("response") or ""),
        provider_model_id=(
            str(row.get("provider_model_id"))
            if row.get("provider_model_id") is not None
            else None
        ),
        expected_model_id=expected,
        require_provider_model_id=bool(expected),
    )
    return validation_error is None
