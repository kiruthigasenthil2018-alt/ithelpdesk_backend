"""LLM clients with structured outputs, timeouts, retries, rate-limit handling and
automatic failover between providers (Gemini -> Groq -> OpenRouter by default)."""

import json
import logging
import time
from functools import lru_cache
from typing import Callable, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(Exception):
    """Base class for LLM failures."""


class LLMConfigError(LLMError):
    """API key missing."""


class LLMTimeoutError(LLMError):
    """The request timed out after all retries."""


class LLMRateLimitError(LLMError):
    """Rate limit (HTTP 429) persisted after all retries."""


def _parse_json(text: str, model_cls: type[T]) -> T:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return model_cls.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMError("LLM returned invalid structured output") from exc


def _json_prompt(prompt: str, model_cls: type[BaseModel]) -> str:
    schema = json.dumps(model_cls.model_json_schema())
    return f"{prompt}\n\nReturn ONLY valid JSON matching this JSON schema:\n{schema}"


class _HttpLLM:
    """Shared HTTP + retry logic."""

    name = "llm"
    model = ""

    def __init__(self, settings, transport, sleep, max_retries):
        self.settings = settings
        self._transport = transport
        self._sleep = sleep
        self.max_retries = settings.llm_max_retries if max_retries is None else max_retries

    api_key: str = ""

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _send(self, url: str, headers: dict, body: dict) -> dict:
        s = self.settings
        if not self.api_key:
            raise LLMConfigError(f"{self.name}: API key is not set")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(s.llm_timeout_seconds), transport=self._transport
                ) as client:
                    resp = client.post(url, json=body, headers=headers)
            except httpx.TimeoutException:
                last_error = LLMTimeoutError(f"{self.name}: request timed out")
                self._wait(attempt, None)
                continue
            except httpx.HTTPError as exc:
                raise LLMError(f"{self.name}: network error {exc.__class__.__name__}") from exc

            if resp.status_code in RETRY_STATUS:
                last_error = (
                    LLMRateLimitError(f"{self.name}: rate limit reached")
                    if resp.status_code == 429
                    else LLMError(f"{self.name}: server error {resp.status_code}")
                )
                self._wait(attempt, resp.headers.get("retry-after"))
                continue
            if resp.status_code != 200:
                raise LLMError(f"{self.name}: HTTP {resp.status_code}")  # e.g. bad key / model
            return resp.json()
        assert last_error is not None
        raise last_error

    def _wait(self, attempt: int, retry_after: str | None) -> None:
        if attempt >= self.max_retries:
            return
        delay = self.settings.llm_backoff_seconds * (2**attempt)
        if retry_after and retry_after.replace(".", "", 1).isdigit():
            delay = max(delay, float(retry_after))
        self._sleep(min(delay, 60))


class GeminiClient(_HttpLLM):
    name = "gemini"

    def __init__(self, settings: Settings | None = None, transport=None,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int | None = None):
        settings = settings or get_settings()
        super().__init__(settings, transport, sleep, max_retries)
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model

    def _request(self, body: dict) -> str:
        s = self.settings
        url = f"{s.gemini_base_url}/models/{s.gemini_model}:generateContent"
        data = self._send(url, {"x-goog-api-key": self.api_key}, body)  # key in header, not URL
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("gemini: unexpected response format (maybe blocked)") from exc

    def generate_text(self, prompt: str, system: str | None = None) -> str:
        body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return self._request(body)

    def generate_json(self, prompt: str, model_cls: type[T], system: str | None = None) -> T:
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": _json_prompt(prompt, model_cls)}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return _parse_json(self._request(body), model_cls)


class OpenAICompatClient(_HttpLLM):
    """Groq and OpenRouter both speak the OpenAI chat-completions format."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str,
                 settings: Settings | None = None, json_mode: bool = False,
                 extra_headers: dict | None = None, transport=None,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int | None = None):
        settings = settings or get_settings()
        super().__init__(settings, transport, sleep, max_retries)
        self.name, self.base_url, self.api_key, self.model = name, base_url, api_key, model
        self.json_mode, self.extra_headers = json_mode, extra_headers or {}

    def _request(self, messages: list[dict], json_mode: bool) -> str:
        body: dict = {"model": self.model, "messages": messages, "temperature": 0.2}
        if json_mode and self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}", **self.extra_headers}
        data = self._send(f"{self.base_url}/chat/completions", headers, body)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"{self.name}: unexpected response format") from exc

    @staticmethod
    def _messages(prompt: str, system: str | None) -> list[dict]:
        msgs = [{"role": "system", "content": system}] if system else []
        return msgs + [{"role": "user", "content": prompt}]

    def generate_text(self, prompt: str, system: str | None = None) -> str:
        return self._request(self._messages(prompt, system), json_mode=False)

    def generate_json(self, prompt: str, model_cls: type[T], system: str | None = None) -> T:
        text = self._request(self._messages(_json_prompt(prompt, model_cls), system), json_mode=True)
        return _parse_json(text, model_cls)


class LLMRouter:
    """Tries providers in order. If one is rate-limited, slow, failing or has no key,
    the next one is used. Rate-limited providers are skipped for a cooldown period."""

    def __init__(self, providers: list, cooldown: int = 60, clock: Callable[[], float] = time.monotonic):
        self.providers = providers
        self.cooldown = cooldown
        self._clock = clock
        self._until: dict[str, float] = {}
        self._last_error: dict[str, str] = {}
        self.last_provider: str | None = None

    @property
    def available(self) -> bool:
        return any(p.available for p in self.providers)

    def status(self) -> list[dict]:
        now = self._clock()
        return [
            {
                "name": p.name,
                "model": p.model,
                "configured": p.available,  # never expose the key itself
                "cooling_down_seconds": max(0, int(self._until.get(p.name, 0) - now)),
                "last_error": self._last_error.get(p.name),
                "last_used": p.name == self.last_provider,
            }
            for p in self.providers
        ]

    def _call(self, method: str, *args, **kwargs):
        now = self._clock()
        last_exc: Exception | None = None
        for p in self.providers:
            if not p.available or self._until.get(p.name, 0) > now:
                continue
            try:
                result = getattr(p, method)(*args, **kwargs)
                self.last_provider = p.name
                self._last_error.pop(p.name, None)
                return result
            except LLMRateLimitError as exc:
                self._until[p.name] = self._clock() + self.cooldown
                self._last_error[p.name] = "rate limited"
                last_exc = exc
            except LLMTimeoutError as exc:
                self._until[p.name] = self._clock() + min(self.cooldown, 15)
                self._last_error[p.name] = "timeout"
                last_exc = exc
            except LLMError as exc:
                self._last_error[p.name] = str(exc)[:120]
                last_exc = exc
            log.warning("LLM provider %s failed (%s); trying next", p.name, last_exc)
        if last_exc is None:
            raise LLMConfigError("No LLM provider is available (no keys set or all cooling down)")
        raise last_exc

    def generate_text(self, prompt: str, system: str | None = None) -> str:
        return self._call("generate_text", prompt, system)

    def generate_json(self, prompt: str, model_cls: type[T], system: str | None = None) -> T:
        return self._call("generate_json", prompt, model_cls, system)


def build_router(settings: Settings | None = None, transport=None) -> LLMRouter:
    s = settings or get_settings()
    r = s.llm_max_retries
    makers = {
        "gemini": lambda: GeminiClient(s, transport=transport, max_retries=r),
        "groq": lambda: OpenAICompatClient(
            "groq", s.groq_base_url, s.groq_api_key, s.groq_model, s, json_mode=True,
            transport=transport, max_retries=r),
        "openrouter": lambda: OpenAICompatClient(
            "openrouter", s.openrouter_base_url, s.openrouter_api_key, s.openrouter_model, s,
            extra_headers={"X-Title": s.app_name}, transport=transport, max_retries=r),
    }
    order = [n.strip() for n in s.llm_provider_order.split(",") if n.strip() in makers]
    return LLMRouter([makers[n]() for n in order], cooldown=s.provider_cooldown_seconds)


@lru_cache
def get_llm() -> LLMRouter:
    return build_router()
