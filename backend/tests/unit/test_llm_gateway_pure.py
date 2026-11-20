"""Package C, pure parts of the gateway: strict JSON parsing (D-04 / D-53) and the rate / cost guard. No database."""

from decimal import Decimal

import pytest

from app.services.llm_gateway import GuardLimits, guard_reason, parse_json_answer

LIM = GuardLimits(calls_per_hour=3, calls_per_day=10, tokens_per_day=1000, max_prompt_chars=100)


def test_D04_plain_object_parses_and_decimals_stay_exact():
    data, problem = parse_json_answer('{"total": 1234.50, "no": "B-1", "n": 2}')
    assert problem is None
    assert data == {"total": Decimal("1234.50"), "no": "B-1", "n": 2}
    assert isinstance(data["total"], Decimal)


def test_D04_one_surrounding_code_fence_is_tolerated():
    assert parse_json_answer('```json\n{"a": "x"}\n```')[0] == {"a": "x"}
    assert parse_json_answer('```\n{"a": "x"}\n```')[0] == {"a": "x"}
    assert parse_json_answer('  \n```json\r\n{"a": "x"}\r\n```  ')[0] == {"a": "x"}


@pytest.mark.parametrize("text", [
    "I think the total is 1000",
    '{"a": 1} and then some text',
    'Here is the JSON: {"a": 1}',
    '{"a": 1',
    "",
    "   ",
    "[1, 2]",
    '"just a string"',
    "42",
    "null",
    '{"a": NaN}',
    '{"a": Infinity}',
    '{"a": 1, "a": 2}',
    "{'a': 1}",
    '```json\n{"a": 1}\n``` extra',
])
def test_D04_anything_else_is_invalid_and_nothing_is_repaired(text):
    data, problem = parse_json_answer(text)
    assert data is None
    assert problem


def test_D04_the_reason_never_copies_the_answer_text():
    _, problem = parse_json_answer('{"secret": "ABCDE1234F" oops}')
    assert "ABCDE1234F" not in problem


def test_D51_guard_allows_when_below_every_limit():
    assert guard_reason(LIM, calls_last_hour=2, calls_last_day=9, tokens_last_day=999, prompt_chars=100) is None


def test_D51_guard_hour_limit():
    reason, message = guard_reason(LIM, calls_last_hour=3, calls_last_day=3, tokens_last_day=0, prompt_chars=10)
    assert reason == "rate_limited"
    assert "last hour" in message and "limit 3" in message


def test_D51_guard_day_limit():
    reason, message = guard_reason(LIM, calls_last_hour=0, calls_last_day=10, tokens_last_day=0, prompt_chars=10)
    assert reason == "rate_limited"
    assert "24 hours" in message


def test_D51_guard_token_budget():
    reason, message = guard_reason(LIM, calls_last_hour=0, calls_last_day=1, tokens_last_day=1000, prompt_chars=10)
    assert reason == "token_budget"
    assert "1,000" in message


def test_D51_guard_prompt_size_is_checked_first():
    reason, message = guard_reason(LIM, calls_last_hour=99, calls_last_day=99, tokens_last_day=99999, prompt_chars=101)
    assert reason == "prompt_too_large"
    assert "101" in message


def test_D51_limits_come_from_the_environment_with_safe_fallbacks(monkeypatch):
    monkeypatch.setenv("AI_MAX_CALLS_PER_HOUR", "7")
    monkeypatch.setenv("AI_MAX_CALLS_PER_DAY", "not a number")
    monkeypatch.setenv("AI_MAX_TOKENS_PER_DAY", "-5")
    monkeypatch.delenv("AI_MAX_PROMPT_CHARS", raising=False)
    lim = GuardLimits.from_env()
    assert (lim.calls_per_hour, lim.calls_per_day, lim.tokens_per_day, lim.max_prompt_chars) == (7, 500, 2_000_000, 60_000)
