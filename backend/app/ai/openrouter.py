"""The real language-model client (OpenRouter, chat completions) behind the `LlmClient` interface of `app/ai/llm.py`.

* The key is read from `app.config` when the client is built (or passed in by a test) and is used only in the Authorization header.
  It is never logged, stored, put in a message or shown by repr. Error messages are fixed texts plus the HTTP status and the model
  name; the provider's error body is never copied (it can echo the prompt).
* The model is `request.model` (the gateway fills it from LLM_MODEL); nothing is hard-coded.
* Strict JSON (`response_format: json_object`), `provider.require_parameters` so a provider that cannot honour it is not used
  silently, reasoning off, temperature 0, no tools, no streaming.
* Whether the answer is JSON that fits the schema is judged by the gateway and the extraction schema, not here (never repaired).
Tests use `httpx.MockTransport` only; no test or development step calls the real service.
"""

import re
import time

import httpx

from app import config
from app.ai.llm import LlmError, LlmRequest, LlmResponse

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
_KEY_TEXT = re.compile(r"sk-or-[A-Za-z0-9_\-]+")


def _redact(text: str, key: str | None = None) -> str:
    text = _KEY_TEXT.sub("[REDACTED_KEY]", text)
    return text.replace(key, "[REDACTED_KEY]") if key else text


class OpenRouterClient:
    provider = "openrouter"

    def __init__(self, api_key: str | None = None, *, base_url: str = BASE_URL, timeout: float = 60.0,
                 transport: httpx.BaseTransport | None = None):
        key = api_key if api_key is not None else config.openrouter_api_key()
        if not key:
            raise LlmError("OPENROUTER_API_KEY is not set; no model call can be made.")
        self._key = key
        self._url = base_url
        self._timeout = timeout
        self._transport = transport

    def __repr__(self) -> str:
        return "OpenRouterClient(key=<hidden>)"

    def complete(self, request: LlmRequest) -> LlmResponse:
        payload = {
            "model": request.model,
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
            "reasoning": {"enabled": False},
            "provider": {"require_parameters": True},
        }
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as http:
                http_response = http.post(self._url, json=payload, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException:
            raise LlmError(f"The model service did not answer within {self._timeout:g} seconds.") from None
        except httpx.HTTPError:
            raise LlmError("The model service could not be reached (network error).") from None
        latency_ms = int((time.monotonic() - started) * 1000)
        self._raise_for_status(http_response.status_code, request.model)
        try:
            body = http_response.json()
        except ValueError:
            raise LlmError("The model service answered with something that is not a JSON message.") from None
        if not isinstance(body, dict):
            raise LlmError("The model service answered with something that is not a JSON message.")
        if body.get("error"):
            raise LlmError("The model service returned an error instead of an answer (HTTP 200 with an error object).")
        text = self._content(body)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return LlmResponse(
            text=_redact(text, self._key),
            model=str(body.get("model") or request.model),
            tokens_in=_count(usage.get("prompt_tokens")),
            tokens_out=_count(usage.get("completion_tokens")),
            latency_ms=latency_ms,
        )

    @staticmethod
    def _raise_for_status(status: int, model: str) -> None:
        if status < 400:
            return
        if status in (401, 403):
            text = "The model service rejected the API key (check OPENROUTER_API_KEY)"
        elif status == 402:
            text = "The model service says there is no credit left for this model"
        elif status == 404:
            text = f"The model '{model}' is not available on the model service (it may have been withdrawn; check LLM_MODEL)"
        elif status == 408:
            text = "The model service timed out"
        elif status == 429:
            text = "The model service rate limit was reached, try again later"
        elif status >= 500:
            text = "The model service had a server error"
        else:
            text = "The model service refused the request"
        raise LlmError(f"{text} (HTTP {status}).")

    @staticmethod
    def _content(body: dict) -> str:
        choices = body.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LlmError("The model service returned no usable answer (empty or not text).")
        return content


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
