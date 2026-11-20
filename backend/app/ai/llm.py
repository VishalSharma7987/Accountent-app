"""The language-model interface (Phase 7). The accounting engine never imports this package; services call a model only through
`services/llm_gateway.py` (package C), which masks the text first (D-50), checks the client's switch (D-51) and stores the call (D-52).

A client is any object with `complete(request) -> LlmResponse`. `app.ai.fake.FakeLlmClient` is used by every test (no network);
`app.ai.openrouter.OpenRouterClient` (package C) is the real one. Nothing here holds a key: the real client reads
OPENROUTER_API_KEY / LLM_MODEL from app.config when it is built and never prints them.
"""

from dataclasses import dataclass
from typing import Protocol


class LlmError(Exception):
    """The call failed (network, HTTP status, timeout, empty answer). The message never contains a key or the prompt."""


@dataclass(frozen=True)
class LlmRequest:
    purpose: str          # an LlmPurpose value
    system: str           # fixed instructions (versioned, see app/ai/prompts.py)
    user: str             # the MASKED document text / narration
    model: str            # from config (LLM_MODEL), never hard-coded
    max_tokens: int = 4000
    temperature: float = 0.0   # a model parameter, not money


@dataclass(frozen=True)
class LlmResponse:
    text: str
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None


class LlmClient(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse: ...
