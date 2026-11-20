"""Package C: the real OpenRouter client, tested ONLY with httpx.MockTransport (no network, no real key). D-52: the key never shows up."""

import json

import httpx
import pytest

from app.ai.llm import LlmError, LlmRequest
from app.ai.openrouter import OpenRouterClient

KEY = "sk-or-v1-TESTKEY-not-real-0123456789"
REQ = LlmRequest(purpose="invoice_extraction", system="Return JSON only.", user="Invoice [GSTIN_1] total 1,000.00",
                 model="vendor/some-model:free")


def client_for(handler, key=KEY, timeout=5.0) -> OpenRouterClient:
    return OpenRouterClient(api_key=key, transport=httpx.MockTransport(handler), timeout=timeout)


def ok_body(content='{"a": 1}', **extra):
    body = {"id": "gen-1", "model": "vendor/some-model:free",
            "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}}
    body.update(extra)
    return body


def test_D52_request_is_strict_json_with_reasoning_off_and_the_key_only_in_the_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        seen["raw"] = request.content.decode()
        return httpx.Response(200, json=ok_body())

    resp = client_for(handler).complete(REQ)
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer " + KEY
    assert KEY not in seen["raw"]
    body = seen["body"]
    assert body["model"] == "vendor/some-model:free"
    assert body["messages"] == [{"role": "system", "content": "Return JSON only."},
                                {"role": "user", "content": "Invoice [GSTIN_1] total 1,000.00"}]
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning"] == {"enabled": False}
    assert body["provider"] == {"require_parameters": True}
    assert body["temperature"] == 0.0 and body["max_tokens"] == 4000
    assert body["stream"] is False
    assert "tools" not in body
    assert (resp.text, resp.model, resp.tokens_in, resp.tokens_out) == ('{"a": 1}', "vendor/some-model:free", 120, 30)
    assert resp.latency_ms is not None and resp.latency_ms >= 0


def test_D52_model_comes_from_the_request_never_from_the_client():
    seen = {}

    def handler(request):
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json=ok_body())

    client_for(handler).complete(LlmRequest("invoice_extraction", "s", "u", "other/model"))
    assert seen["model"] == "other/model"


def test_D52_key_is_read_from_config_when_not_given(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=ok_body())

    OpenRouterClient(transport=httpx.MockTransport(handler)).complete(REQ)
    assert seen["auth"] == "Bearer " + KEY


def test_D52_missing_key_is_a_clear_error_and_no_request_is_made(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    called = []

    def handler(request):
        called.append(request)
        return httpx.Response(200, json=ok_body())

    with pytest.raises(LlmError, match="OPENROUTER_API_KEY is not set"):
        OpenRouterClient(transport=httpx.MockTransport(handler))
    assert called == []


@pytest.mark.parametrize("status, expected", [
    (401, "rejected the API key"),
    (403, "rejected the API key"),
    (402, "no credit"),
    (404, "is not available"),
    (408, "timed out"),
    (429, "rate limit"),
    (500, "server error"),
    (503, "server error"),
    (400, "refused the request"),
])
def test_D52_http_failures_give_a_fixed_clear_message_with_the_status_and_no_key_or_body(status, expected):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": f"echo {KEY} and Invoice [GSTIN_1] ABCDE1234F"}})

    with pytest.raises(LlmError) as info:
        client_for(handler).complete(REQ)
    msg = str(info.value)
    assert expected in msg
    assert f"HTTP {status}" in msg
    assert KEY not in msg and "ABCDE1234F" not in msg and "echo" not in msg


def test_D52_unavailable_model_names_the_model():
    with pytest.raises(LlmError) as info:
        client_for(lambda r: httpx.Response(404, json={"error": {"message": "No endpoints found"}})).complete(REQ)
    assert "vendor/some-model:free" in str(info.value)


def test_D52_timeout_is_a_clear_error():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LlmError, match="did not answer within 5 seconds"):
        client_for(handler).complete(REQ)


def test_D52_network_failure_is_a_clear_error_without_the_key():
    def handler(request):
        raise httpx.ConnectError(f"cannot connect with {KEY}", request=request)

    with pytest.raises(LlmError) as info:
        client_for(handler).complete(REQ)
    assert "could not be reached" in str(info.value) and KEY not in str(info.value)


def test_D52_error_object_inside_a_200_answer_is_an_error():
    with pytest.raises(LlmError, match="returned an error"):
        client_for(lambda r: httpx.Response(200, json={"error": {"code": 502, "message": "upstream"}})).complete(REQ)


@pytest.mark.parametrize("body", [
    {"choices": []},
    {"choices": [{"message": {"content": None}}]},
    {"choices": [{"message": {"content": "   "}}]},
    {"choices": [{"message": {}}]},
    {"nothing": True},
    {"choices": [{"message": {"content": ["not", "text"]}}]},
])
def test_D52_empty_or_odd_answers_are_errors_never_guessed(body):
    with pytest.raises(LlmError, match="no usable answer"):
        client_for(lambda r: httpx.Response(200, json=body)).complete(REQ)


def test_D52_non_json_http_body_is_an_error():
    with pytest.raises(LlmError, match="not a JSON message"):
        client_for(lambda r: httpx.Response(200, text="<html>gateway</html>")).complete(REQ)


def test_D04_invalid_json_content_is_passed_through_untouched_for_the_gateway_to_judge():
    resp = client_for(lambda r: httpx.Response(200, json=ok_body("I think the total is 1000"))).complete(REQ)
    assert resp.text == "I think the total is 1000"


def test_D52_a_key_echoed_by_the_model_in_its_answer_is_not_returned_as_is():
    resp = client_for(lambda r: httpx.Response(200, json=ok_body('{"k": "' + KEY + '"}'))).complete(REQ)
    assert KEY not in resp.text
    assert "[REDACTED_KEY]" in resp.text


def test_D52_repr_and_str_of_the_client_never_show_the_key():
    c = client_for(lambda r: httpx.Response(200, json=ok_body()))
    assert KEY not in repr(c) and KEY not in str(c)


def test_D52_usage_is_optional():
    resp = client_for(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})).complete(REQ)
    assert (resp.tokens_in, resp.tokens_out, resp.model) == (None, None, "vendor/some-model:free")
