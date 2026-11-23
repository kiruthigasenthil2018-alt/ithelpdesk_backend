import httpx

from app.config import get_settings
from app.schemas.llm import Classification
from app.services.llm_service import LLMConfigError, build_router
import pytest

GOOD = '{"category": "network", "priority": "P2", "confidence": 0.8, "summary": "vpn"}'


def _settings(**kw):
    base = dict(gemini_api_key="g", groq_api_key="q", openrouter_api_key="o",
                llm_max_retries=0, llm_backoff_seconds=0)
    return get_settings().model_copy(update={**base, **kw})


def _router(handler, **kw):
    return build_router(_settings(**kw), transport=httpx.MockTransport(handler))


def _gemini_ok(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def _openai_ok(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def _reply(request, down=()):
    host = request.url.host
    if any(d in host for d in down):
        return httpx.Response(429)
    return _gemini_ok(GOOD) if "googleapis" in host else _openai_ok(GOOD)


def test_uses_first_provider_when_healthy():
    r = _router(lambda req: _reply(req))
    assert r.generate_json("x", Classification).category.value == "network"
    assert r.last_provider == "gemini"


def test_fails_over_gemini_to_groq_to_openrouter():
    r = _router(lambda req: _reply(req, down=("googleapis",)))
    r.generate_json("x", Classification)
    assert r.last_provider == "groq"
    r2 = _router(lambda req: _reply(req, down=("googleapis", "groq")))
    r2.generate_json("x", Classification)
    assert r2.last_provider == "openrouter"


def test_rate_limited_provider_is_skipped_during_cooldown():
    calls = []

    def handler(req):
        calls.append(req.url.host)
        return _reply(req, down=("googleapis",))

    r = _router(handler)
    r.generate_json("x", Classification)
    first = len(calls)
    r.generate_json("x", Classification)
    assert calls[first:].count("generativelanguage.googleapis.com") == 0  # skipped
    status = {s["name"]: s for s in r.status()}
    assert status["gemini"]["cooling_down_seconds"] > 0 and status["gemini"]["last_error"] == "rate limited"


def test_cooldown_expires():
    t = {"now": 0.0}
    r = _router(lambda req: _reply(req, down=("googleapis",)))
    r._clock = lambda: t["now"]
    r.generate_json("x", Classification)
    t["now"] = 1000
    assert r.status()[0]["cooling_down_seconds"] == 0


def test_skips_providers_without_keys():
    r = _router(lambda req: _reply(req), gemini_api_key="", groq_api_key="")
    r.generate_json("x", Classification)
    assert r.last_provider == "openrouter"


def test_all_failing_raises_last_error():
    r = _router(lambda req: httpx.Response(429))
    with pytest.raises(Exception) as e:
        r.generate_text("x")
    assert "rate limit" in str(e.value)


def test_no_keys_at_all():
    r = _router(lambda req: _reply(req), gemini_api_key="", groq_api_key="", openrouter_api_key="")
    assert r.available is False
    with pytest.raises(LLMConfigError):
        r.generate_text("x")


def test_bad_json_from_one_provider_fails_over():
    def handler(req):
        if "googleapis" in req.url.host:
            return _gemini_ok("not json")
        return _openai_ok(GOOD)

    r = _router(handler)
    r.generate_json("x", Classification)
    assert r.last_provider == "groq"


def test_status_never_exposes_keys():
    r = _router(lambda req: _reply(req))
    assert "g" * 5 not in str(r.status()) and "api_key" not in str(r.status())
