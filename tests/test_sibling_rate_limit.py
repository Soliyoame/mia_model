from __future__ import annotations

import urllib.error
import urllib.request
import unittest
from unittest.mock import patch

from src.llm.factory import request_rate_limiter_from_profile
from src.llm.openai_compatible import OpenAICompatibleChatClient
from src.utils.io import load_yaml


class _CountingLimiter:
    def __init__(self) -> None:
        self.calls = 0

    def acquire(self) -> None:
        self.calls += 1


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return b'{"ok": true}'


class SiblingRateLimitTests(unittest.TestCase):
    def test_every_physical_retry_acquires_a_token(self) -> None:
        limiter = _CountingLimiter()
        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="test-model",
            max_retries=1,
            retry_backoff_base=0,
            retry_backoff_max=0,
            request_rate_limiter=limiter,
        )
        request = urllib.request.Request("https://example.invalid")
        with patch(
            "urllib.request.urlopen",
            side_effect=[urllib.error.URLError("temporary"), _Response()],
        ):
            body, retry_count = client._urlopen_with_retries(request, 1.0)
        self.assertEqual(body, '{"ok": true}')
        self.assertEqual(retry_count, 1)
        self.assertEqual(limiter.calls, 2)

    def test_remote_sibling_profiles_enable_four_rpm(self) -> None:
        profiles = load_yaml("configs/llm_profiles.yaml")
        sibling = profiles["sibling"]["profiles"]
        self.assertEqual(
            sibling["luna_query_generator"]["requests_per_minute"], 4
        )
        self.assertEqual(sibling["openai_api"]["requests_per_minute"], 4)
        self.assertEqual(sibling["ollama_qwen3_4b"]["requests_per_minute"], 0)
        self.assertIsNotNone(
            request_rate_limiter_from_profile(
                sibling["luna_query_generator"]
            )
        )

    def test_negative_rpm_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            request_rate_limiter_from_profile(
                {"requests_per_minute": -1}
            )


if __name__ == "__main__":
    unittest.main()
