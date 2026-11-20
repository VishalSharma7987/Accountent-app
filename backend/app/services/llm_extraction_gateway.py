"""Adapter between the extraction service (package D) and the model gateway (package C).

D's service asks for `gateway.call(conn, client_id=, document_id=, request=, prompt_version=, actor=)` and expects an object with
`status` ("ok" | "blocked" | "error"), `llm_call_id`, `text` (the answer with the masking tokens restored) and `message`.
C's `llm_gateway.call` masks the prompt, writes the audit row and returns a `GatewayResult`. This adapter only translates between the
two; it never sees an unmasked prompt leave the gateway and it never stores the restored answer.
"""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

from app.ai.llm import LlmRequest
from app.services import llm_gateway


@dataclass(frozen=True)
class ExtractionCall:
    status: str
    llm_call_id: Any
    text: str | None
    message: str


class LlmGateway:
    def call(self, conn: Connection, *, client_id: Any, document_id: Any, request: LlmRequest, prompt_version: str,
             actor: str) -> ExtractionCall:
        result = llm_gateway.call(
            conn, client_id=client_id, purpose=request.purpose, system=request.system, user=request.user,
            prompt_version=prompt_version, actor=actor, document_id=document_id, model=request.model or None,
            max_tokens=request.max_tokens)
        if result.status == "ok" and result.data is not None:
            # decimals go back as exact text ("123.45"), never as binary floats; the schema reads them as Decimal
            text = json.dumps(result.data, default=str)
            return ExtractionCall("ok", result.call_id, text, result.message)
        shown = "blocked" if result.status == "blocked" else "error"
        return ExtractionCall(shown, result.call_id, None, result.message)
