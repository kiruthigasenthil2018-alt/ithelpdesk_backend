import httpx
import pytest

from app.config import get_settings
from app.schemas.llm import Classification
from app.services.llm_service import (
    GeminiClient, LLMConfigError, LLMError, LLMRateLimitError, LLMTimeoutError,
)


def _client(handler, key="test-key"):
    s = get_settings().model_copy(update={"gemini_api_key": key, "llm_max_retries": 2})
    return GeminiClient(s, transport=httpx.MockTransport(handler), sleep=lambda _: None)


def _ok(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_missing_key():
    with pytest.raises(LLMConfigError):
        _client(lambda r: _ok("x"), key="").generate_text("hi")


def test_structured_output_and_key_in_header():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["url"] = str(request.url)
        return _ok('{"category": "network", "priority": "P2", "confidence": 0.8, "summary": "vpn"}')

    result = _client(handler).generate_json("classify", Classification)
    assert result.category.value == "network"
    assert seen["key"] == "test-key" and "test-key" not in seen["url"]


def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] < 3 else _ok("done")

    assert _client(handler).generate_text("hi") == "done"
    assert calls["n"] == 3


def test_rate_limit_persists():
    with pytest.raises(LLMRateLimitError):
        _client(lambda r: httpx.Response(429)).generate_text("hi")


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMTimeoutError):
        _client(handler).generate_text("hi")


def test_invalid_json_is_an_error():
    with pytest.raises(LLMError):
        _client(lambda r: _ok("not json")).generate_json("x", Classification)


def test_non_retryable_error():
    with pytest.raises(LLMError):
        _client(lambda r: httpx.Response(400)).generate_text("hi")
