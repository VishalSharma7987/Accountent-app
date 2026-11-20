"""A scripted language-model client for tests and the Phase 7 acceptance pack: no network, no key.

`FakeLlmClient(["{...json...}", LlmError("timeout")])` answers the first call with the first item (an Exception item is raised);
`FakeLlmClient(lambda request: "...")` answers every call from a function. Every request is kept in `.requests` so a test can assert
what was (and was not) sent, e.g. that a PAN never reached the model.
"""

from collections.abc import Callable, Sequence

from app.ai.llm import LlmRequest, LlmResponse


class FakeLlmClient:
    def __init__(self, answers: Sequence[str | Exception] | Callable[[LlmRequest], str], model: str = "fake/model"):
        self._answers = answers
        self._model = model
        self.requests: list[LlmRequest] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        if callable(self._answers):
            return LlmResponse(text=self._answers(request), model=self._model, tokens_in=0, tokens_out=0, latency_ms=0)
        if len(self.requests) > len(self._answers):
            raise AssertionError("FakeLlmClient was called more often than it has scripted answers")
        item = self._answers[len(self.requests) - 1]
        if isinstance(item, Exception):
            raise item
        return LlmResponse(text=item, model=self._model, tokens_in=0, tokens_out=0, latency_ms=0)
