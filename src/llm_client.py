"""Unified OpenAI-compatible LLM client for the auditor pipeline."""

import json
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LLM_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "llm_api.json")

_DEFAULT_API_KEY = ""
_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_REQUEST_MODE = "chat"
_DEFAULT_TIMEOUT = 60.0


def _load_local_llm_config() -> Dict[str, Any]:
    if not os.path.isfile(_LLM_CONFIG_PATH):
        return {}
    try:
        with open(_LLM_CONFIG_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"[LLM] Failed to read local config {_LLM_CONFIG_PATH}: {exc}")
        return {}
    if not isinstance(payload, dict):
        print(f"[LLM] Ignoring invalid local config format: {_LLM_CONFIG_PATH}")
        return {}
    return payload


def _mask_secret(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_base_url(base_url: str) -> str:
    base_url = (base_url or "").strip()
    if not base_url:
        return _DEFAULT_BASE_URL
    return base_url.rstrip("/")


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


class LLMClient:
    """Small wrapper around OpenAI-compatible chat APIs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        local_config = _load_local_llm_config()

        self.api_key = _coalesce(
            api_key,
            os.environ.get("LLM_API_KEY"),
            local_config.get("api_key"),
            _DEFAULT_API_KEY,
        )
        self.base_url = _normalize_base_url(
            _coalesce(
                base_url,
                os.environ.get("LLM_BASE_URL"),
                local_config.get("base_url"),
                _DEFAULT_BASE_URL,
            )
        )
        self.model = _coalesce(
            model,
            os.environ.get("LLM_MODEL"),
            local_config.get("model"),
            _DEFAULT_MODEL,
        )
        self.request_mode = str(
            _coalesce(
                os.environ.get("LLM_REQUEST_MODE"),
                local_config.get("request_mode"),
                _DEFAULT_REQUEST_MODE,
            )
        ).strip().lower()
        self.timeout = _as_float(
            _coalesce(
                os.environ.get("LLM_TIMEOUT"),
                local_config.get("timeout"),
                _DEFAULT_TIMEOUT,
            ),
            _DEFAULT_TIMEOUT,
        )
        self.max_retries = _as_int(
            _coalesce(
                os.environ.get("LLM_MAX_RETRIES"),
                local_config.get("max_retries"),
                3,
            ),
            3,
        )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )

        print(
            f"[LLM] Configured: {self.base_url}  model: {self.model}  "
            f"API key: {_mask_secret(self.api_key)}  mode: {self.request_mode}"
        )

    def ensure_healthy(self) -> None:
        """Run a minimal request to verify the endpoint and model are usable."""
        replies = self.chat(
            [{"role": "user", "content": "Reply with OK only."}],
            temperature=0.0,
            max_tokens=8,
            n=1,
        )
        if not replies or not replies[0].strip():
            raise RuntimeError(
                f"LLM health check failed for model={self.model} base_url={self.base_url}"
            )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 256,
        n: int = 1,
    ) -> List[str]:
        """Call an OpenAI-compatible chat endpoint and return plain text replies."""
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                return self._chat_once(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    n=n,
                )
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    print(f"[LLM] Request failed ({exc}); retrying in {wait}s")
                    time.sleep(wait)
                    continue
                break

        print(
            f"[LLM] Request failed after {self.max_retries} attempts: {last_error}"
        )
        return [""] * max(1, int(n))

    def _chat_once(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        n: int,
    ) -> List[str]:
        if self.request_mode == "responses":
            return self._call_responses(messages, temperature, max_tokens, n)
        return self._call_chat_completions(messages, temperature, max_tokens, n)

    def _call_chat_completions(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        n: int,
    ) -> List[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "n": n,
        }
        try:
            response = self.client.chat.completions.create(**payload)
        except TypeError:
            payload.pop("n", None)
            response = self.client.chat.completions.create(**payload)
        outputs = self._extract_chat_choices(response)
        if outputs:
            return outputs
        raise RuntimeError(
            "Chat endpoint returned no choices. "
            f"model={self.model} base_url={self.base_url}"
        )

    def _call_responses(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        n: int,
    ) -> List[str]:
        if n != 1:
            raise ValueError("responses mode currently supports n=1 only")

        input_items = []
        for message in messages:
            input_items.append(
                {
                    "role": message.get("role", "user"),
                    "content": [
                        {
                            "type": "input_text",
                            "text": message.get("content", ""),
                        }
                    ],
                }
            )

        payload = {
            "model": self.model,
            "input": input_items,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        response = self.client.responses.create(**payload)
        text = self._extract_response_text(response)
        return [text]

    @staticmethod
    def _extract_chat_choices(response: Any) -> List[str]:
        outputs: List[str] = []
        for choice in getattr(response, "choices", []) or []:
            message = getattr(choice, "message", None)
            content = getattr(message, "content", "") if message else ""
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict)
                )
            outputs.append((content or "").strip())
        return outputs

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        outputs = getattr(response, "output", None) or []
        chunks: List[str] = []
        for item in outputs:
            content_list = getattr(item, "content", None) or []
            for content in content_list:
                text_value = getattr(content, "text", None)
                if text_value:
                    chunks.append(str(text_value))
        return "".join(chunks).strip()
