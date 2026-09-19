from __future__ import annotations

import http.client
import io
import ssl
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


class _IncompleteErrorBody:
    def read(self) -> bytes:
        raise http.client.IncompleteRead(b"partial", 10)

    def close(self) -> None:
        return None


class _StreamingResponse(_Response):
    def __iter__(self):
        yield b'data: {"id":"x","model":"test-model","choices":[{"delta":{"content":"ok"}}]}\n'
        yield b"data: [DONE]\n"


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

    def test_retry_until_success_keeps_reconnecting_after_transport_timeouts(self) -> None:
        limiter = _CountingLimiter()
        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="test-model",
            retry_until_success=True,
            retry_backoff_base=0,
            retry_backoff_max=0,
            request_rate_limiter=limiter,
        )
        request = urllib.request.Request("https://example.invalid")
        with patch(
            "urllib.request.urlopen",
            side_effect=[
                TimeoutError("timed out"),
                urllib.error.URLError("temporary"),
                _Response(),
            ],
        ):
            body, retry_count = client._urlopen_with_retries(request, 1.0)
        self.assertEqual(body, '{"ok": true}')
        self.assertEqual(retry_count, 2)
        self.assertEqual(limiter.calls, 3)

    def test_retry_until_success_handles_supported_network_exceptions(self) -> None:
        errors = (
            ssl.SSLError("tls interrupted"),
            http.client.RemoteDisconnected("peer closed connection"),
            OSError("socket unavailable"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                limiter = _CountingLimiter()
                client = OpenAICompatibleChatClient(
                    base_url="https://example.invalid/v1",
                    model="test-model",
                    retry_until_success=True,
                    retry_backoff_base=0,
                    retry_backoff_max=0,
                    request_rate_limiter=limiter,
                )
                request = urllib.request.Request("https://example.invalid")
                with patch("urllib.request.urlopen", side_effect=[error, _Response()]):
                    body, retry_count = client._urlopen_with_retries(request, 1.0)
                self.assertEqual(body, '{"ok": true}')
                self.assertEqual(retry_count, 1)
                self.assertEqual(limiter.calls, 2)

    def test_retry_until_success_retries_retryable_http_status(self) -> None:
        limiter = _CountingLimiter()
        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="test-model",
            retry_until_success=True,
            retry_backoff_base=0,
            retry_backoff_max=0,
            request_rate_limiter=limiter,
        )
        request = urllib.request.Request("https://example.invalid")
        rate_limited = urllib.error.HTTPError(
            request.full_url,
            429,
            "rate limited",
            hdrs=None,
            fp=io.BytesIO(b"retry later"),
        )
        unavailable = urllib.error.HTTPError(
            request.full_url,
            503,
            "unavailable",
            hdrs=None,
            fp=io.BytesIO(b"temporary"),
        )
        with patch(
            "urllib.request.urlopen",
            side_effect=[rate_limited, unavailable, _Response()],
        ):
            body, retry_count = client._urlopen_with_retries(request, 1.0)
        self.assertEqual(body, '{"ok": true}')
        self.assertEqual(retry_count, 2)
        self.assertEqual(limiter.calls, 3)

    def test_retryable_http_status_with_incomplete_error_body_still_retries(self) -> None:
        limiter = _CountingLimiter()
        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="test-model",
            retry_until_success=True,
            retry_backoff_base=0,
            retry_backoff_max=0,
            request_rate_limiter=limiter,
        )
        request = urllib.request.Request("https://example.invalid")
        interrupted = urllib.error.HTTPError(
            request.full_url,
            503,
            "unavailable",
            hdrs=None,
            fp=_IncompleteErrorBody(),
        )
        with patch(
            "urllib.request.urlopen",
            side_effect=[interrupted, _Response()],
        ):
            body, retry_count = client._urlopen_with_retries(request, 1.0)
        self.assertEqual(body, '{"ok": true}')
        self.assertEqual(retry_count, 1)
        self.assertEqual(limiter.calls, 2)

    def test_stream_retryable_http_status_with_incomplete_error_body_still_retries(self) -> None:
        limiter = _CountingLimiter()
        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="test-model",
            stream=True,
            retry_until_success=True,
            retry_backoff_base=0,
            retry_backoff_max=0,
            request_rate_limiter=limiter,
        )
        request = urllib.request.Request("https://example.invalid")
        interrupted = urllib.error.HTTPError(
            request.full_url,
            503,
            "unavailable",
            hdrs=None,
            fp=_IncompleteErrorBody(),
        )
        with patch(
            "urllib.request.urlopen",
            side_effect=[interrupted, _StreamingResponse()],
        ):
            result = client._stream_with_retries(request, 1.0)
        self.assertEqual(result[0], "ok")
        self.assertEqual(result[-1], 1)
        self.assertEqual(limiter.calls, 2)

    def test_retry_until_success_does_not_retry_permanent_http_error(self) -> None:
        limiter = _CountingLimiter()
        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="test-model",
            retry_until_success=True,
            retry_backoff_base=0,
            retry_backoff_max=0,
            request_rate_limiter=limiter,
        )
        request = urllib.request.Request("https://example.invalid")
        unauthorized = urllib.error.HTTPError(
            request.full_url,
            401,
            "unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"bad credentials"),
        )
        with patch("urllib.request.urlopen", side_effect=unauthorized) as urlopen:
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                client._urlopen_with_retries(request, 1.0)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(limiter.calls, 1)

    def test_retry_until_success_does_not_retry_invalid_response_schema(self) -> None:
        client = OpenAICompatibleChatClient(
            base_url="https://example.invalid/v1",
            model="test-model",
            retry_until_success=True,
        )
        with patch.object(
            client,
            "_urlopen_with_retries",
            return_value=('{"choices": []}', 0),
        ) as transport:
            with self.assertRaisesRegex(RuntimeError, "Unexpected OpenAI-compatible response"):
                client.chat_with_metadata("hello")
        transport.assert_called_once()

    def test_remote_sibling_profiles_enable_four_rpm(self) -> None:
        profiles = load_yaml("configs/llm_profiles.yaml")
        sibling = profiles["sibling"]["profiles"]
        self.assertEqual(
            sibling["luna_query_generator"]["requests_per_minute"], 4
        )
        self.assertTrue(sibling["luna_query_generator"]["retry_until_success"])
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
