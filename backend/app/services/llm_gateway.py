"""The ONLY way a model is called (Phase 7, package C): switch (D-51) -> configuration -> rate / cost guard -> masking (D-50) ->
independent clean scan -> the model -> the call is stored (D-52) -> the answer is parsed as strict JSON (D-04, D-53).

Expected failures are RESULTS, not exceptions (plan decision 7): the request transaction rolls back when a handler raises, which
would erase the audit row of a refused or failed call. `call` raises ServiceError only for a bad request (no actor, unknown client,
unknown purpose).

What is stored in `llm_calls`: the MASKED prompt (fixed system text + masked user text), the raw answer exactly as the model sent it
(still with placeholders, key text redacted), counts of what was masked and the client's data class in `masking_report`
(never values), model, prompt version, tokens, latency. A refused call stores no prompt and no answer. The placeholders are put
back (by Python, from an in-memory map) only in the returned `data`; that restored copy is never stored here.
`llm_calls` is insert only, so a later schema failure of a valid JSON answer is recorded by the extraction row (package D), not here.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app import config
from app.ai.llm import LlmClient, LlmError, LlmRequest
from app.db import repositories_ai as repo
from app.engine import doc_mask
from app.services import queries
from app.services.errors import ServiceError, require_actor

PURPOSES = ("invoice_extraction", "narration_suggestion", "audit_summary")
_KEY_TEXT = re.compile(r"sk-or-[A-Za-z0-9_\-]+")
_FENCE = re.compile(r"^```(?:json|JSON)?[ \t]*\r?\n(.*)\r?\n```$", re.DOTALL)


@dataclass(frozen=True)
class GuardLimits:
    """Rate / cost guard. Counted per client from `llm_calls` (refused calls do not count). Defaults suit a free model; override with
    AI_MAX_CALLS_PER_HOUR, AI_MAX_CALLS_PER_DAY, AI_MAX_TOKENS_PER_DAY, AI_MAX_PROMPT_CHARS."""

    calls_per_hour: int = 60
    calls_per_day: int = 500
    tokens_per_day: int = 2_000_000
    max_prompt_chars: int = 60_000

    @classmethod
    def from_env(cls) -> "GuardLimits":
        def number(name: str, default: int) -> int:
            try:
                value = int(os.environ.get(name, "").strip())
            except ValueError:
                return default
            return value if value > 0 else default

        d = cls()
        return cls(number("AI_MAX_CALLS_PER_HOUR", d.calls_per_hour), number("AI_MAX_CALLS_PER_DAY", d.calls_per_day),
                   number("AI_MAX_TOKENS_PER_DAY", d.tokens_per_day), number("AI_MAX_PROMPT_CHARS", d.max_prompt_chars))


@dataclass
class GatewayResult:
    status: str                       # ok | invalid_json | error | blocked  (the llm_calls status)
    reason: str | None                # llm_disabled | llm_unavailable | rate_limited | token_budget | prompt_too_large |
                                      # masking_failed | provider_error | invalid_json | None when ok
    message: str                      # plain language, safe to show
    call_id: Any = None
    data: dict | None = None          # the parsed JSON object with placeholders restored (ok only; never stored here)
    text: str | None = None           # the raw answer as received (placeholders, not restored)
    masking_report: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def parse_json_answer(text: str) -> tuple[dict | None, str | None]:
    """The model's answer as ONE JSON object, or (None, reason). A single surrounding ``` fence is tolerated (formatting, not content);
    nothing else is repaired. Numbers with decimals come back as Decimal, NaN / Infinity and duplicate keys are refused."""
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1).strip()

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
        out: dict = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate key in the JSON object")
            out[key] = value
        return out

    def no_constant(name: str) -> Any:
        raise ValueError("NaN or Infinity is not valid JSON")

    try:
        parsed = json.loads(body, parse_float=Decimal, parse_constant=no_constant, object_pairs_hook=no_duplicates)
    except json.JSONDecodeError as exc:
        return None, f"The answer is not valid JSON ({exc.msg}, position {exc.pos})."
    except ValueError as exc:
        return None, f"The answer is not valid JSON ({exc})."
    if not isinstance(parsed, dict):
        return None, "The answer is JSON but not a single object."
    return parsed, None


def guard_reason(limits: GuardLimits, *, calls_last_hour: int, calls_last_day: int, tokens_last_day: int,
                 prompt_chars: int) -> tuple[str, str] | None:
    """(reason code, message) when a limit is reached, else None. Pure."""
    if prompt_chars > limits.max_prompt_chars:
        return ("prompt_too_large", (f"The text is too long for one model call ({prompt_chars:,} characters; the limit is "
                                    f"{limits.max_prompt_chars:,}). Split the document or enter it by hand."))
    if calls_last_hour >= limits.calls_per_hour:
        return ("rate_limited", (f"This client has already made {calls_last_hour} model calls in the last hour (limit "
                                f"{limits.calls_per_hour}). Try again later or enter the data by hand."))
    if calls_last_day >= limits.calls_per_day:
        return ("rate_limited", (f"This client has already made {calls_last_day} model calls in the last 24 hours (limit "
                                f"{limits.calls_per_day}). Try again tomorrow or enter the data by hand."))
    if tokens_last_day >= limits.tokens_per_day:
        return ("token_budget", (f"This client has used {tokens_last_day:,} model tokens in the last 24 hours (limit "
                                f"{limits.tokens_per_day:,}). Try again tomorrow or enter the data by hand."))
    return None


def _safe_text(value: str, limit: int = 500) -> str:
    return _KEY_TEXT.sub("[REDACTED_KEY]", value)[:limit]


def call(conn: Connection, *, client_id: Any, purpose: str, system: str, user: str, prompt_version: str, actor: str,
         document_id: Any = None, llm_client: LlmClient | None = None, model: str | None = None, max_tokens: int = 4000,
         limits: GuardLimits | None = None) -> GatewayResult:
    actor = require_actor(actor)
    if purpose not in PURPOSES:
        raise ServiceError("invalid_purpose", "Unknown purpose for a model call.")
    queries.require_client(conn, client_id)
    limits = limits or GuardLimits.from_env()
    provider = getattr(llm_client, "provider", None) or ("openrouter" if llm_client is None else type(llm_client).__name__)
    settings = repo.get_settings(conn, client_id)
    data_class = (settings or {}).get("data_class", "synthetic")
    model = model or config.llm_model()

    def refuse(reason: str, message: str, report: dict | None = None) -> GatewayResult:
        report = {"data_class": data_class, **({"counts": report} if report else {})}
        call_id = repo.insert_call(
            conn, client_id=client_id, document_id=document_id, purpose=purpose, provider=provider, model=model,
            prompt_version=prompt_version, prompt_masked=None, prompt_sha256=None, masking_applied=False, masking_report=report,
            response_raw=None, status="blocked", error_message=f"{reason}: {_safe_text(message)}", tokens_in=None, tokens_out=None,
            latency_ms=None, created_by=actor)
        return GatewayResult("blocked", reason, message, call_id=call_id, masking_report=report)

    # D-51: no switch, no call
    if not (settings and settings["llm_enabled"]):
        return refuse("llm_disabled", "AI reading is switched off for this client (D-51). Enter the data by hand, or switch it on in the "
                                      "client's AI settings after confirming that only synthetic or anonymised data is used.")
    if model is None:
        return refuse("llm_unavailable", "No model is configured (LLM_MODEL is not set), so no call was made.")

    # cost guard, before anything is masked or sent
    hour_calls, _ = repo.usage_since(conn, client_id, 3600)
    day_calls, day_tokens = repo.usage_since(conn, client_id, 86400)
    guard = guard_reason(limits, calls_last_hour=hour_calls, calls_last_day=day_calls, tokens_last_day=day_tokens,
                         prompt_chars=len(system) + len(user))
    if guard:
        return refuse(*guard)

    if llm_client is None:
        from app.ai.openrouter import (
            OpenRouterClient,  # reads the key from config inside the client only
        )

        try:
            llm_client = OpenRouterClient()
        except LlmError as exc:
            return refuse("llm_unavailable", f"{_safe_text(str(exc))} No call was made.")

    # D-50: mask, then a second independent scan; refuse to send otherwise
    masked = doc_mask.mask(user)
    try:
        doc_mask.assert_clean(system)
        doc_mask.assert_clean(masked.text)
    except doc_mask.MaskingError as exc:
        return refuse("masking_failed", str(exc), exc.kinds)
    report = {"data_class": data_class, "counts": masked.report}
    prompt_masked = f"[SYSTEM]\n{system}\n[USER]\n{masked.text}"
    prompt_sha256 = hashlib.sha256(prompt_masked.encode("utf-8")).hexdigest()

    def record(status: str, **kw: Any) -> Any:
        return repo.insert_call(
            conn, client_id=client_id, document_id=document_id, purpose=purpose, provider=provider, prompt_version=prompt_version,
            prompt_masked=prompt_masked, prompt_sha256=prompt_sha256, masking_applied=True, masking_report=report, status=status,
            created_by=actor, **{"model": model, "response_raw": None, "error_message": None, "tokens_in": None, "tokens_out": None,
                                 "latency_ms": None, **kw})

    request = LlmRequest(purpose=purpose, system=system, user=masked.text, model=model, max_tokens=max_tokens)
    try:
        response = llm_client.complete(request)
    except LlmError as exc:
        message = _safe_text(str(exc))
        return GatewayResult("error", "provider_error", message, call_id=record("error", error_message=message), masking_report=report)
    except Exception as exc:  # noqa: BLE001   never let an unexpected client failure lose the audit row; the class name only, never its text
        message = f"The model call failed unexpectedly ({type(exc).__name__})."
        return GatewayResult("error", "provider_error", message, call_id=record("error", error_message=message), masking_report=report)

    raw = _KEY_TEXT.sub("[REDACTED_KEY]", response.text)
    usage = {"tokens_in": response.tokens_in, "tokens_out": response.tokens_out, "latency_ms": response.latency_ms,
             "model": response.model or model}
    parsed, problem = parse_json_answer(raw)
    if parsed is None:
        return GatewayResult("invalid_json", "invalid_json", problem or "The answer is not valid JSON.",
                             call_id=record("invalid_json", response_raw=raw, error_message=problem, **usage), text=raw,
                             masking_report=report)
    call_id = record("ok", response_raw=raw, **usage)
    return GatewayResult("ok", None, "The model answered.", call_id=call_id, data=doc_mask.restore_data(parsed, masked.mapping), text=raw,
                         masking_report=report)
