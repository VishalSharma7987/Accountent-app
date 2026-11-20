"""Bank narration -> ledger suggestions (Phase 7 package F, D-40..D-43). Pure Python: no DB, web or LLM imports.

D-40  narration_key: the narration as a stable key (lower case, dates and every word that holds a digit removed, whitespace collapsed).
D-41  a key learned from the accountant's accepted choices that points to exactly ONE ledger is suggested, with the count as the reason.
D-42  a key that points to several ledgers is ambiguous: candidates are listed, none is selected.
D-43  an answer of a language model is read strictly: it may only pick one of the options it was given; anything else is dropped.
Nothing here computes an amount.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
_DATES = re.compile(
    rf"\b\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}\b|\b\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}\b|\b\d{{1,2}}[-/ ]?(?:{_MONTHS})[a-z]*[-/ ]?\d{{2,4}}\b",
    re.IGNORECASE,
)
_NOT_WORD = re.compile(r"[^\w\s]|_")


def narration_key(raw: str | None) -> str:
    """D-40. '' when nothing is left (such a narration cannot teach or match a rule)."""
    if not raw:
        return ""
    text = _DATES.sub(" ", raw.lower())
    text = _NOT_WORD.sub(" ", text)
    return " ".join(t for t in text.split() if not any(ch.isdigit() for ch in t))


# ============================================================================================ rules (D-41, D-42)


@dataclass(frozen=True)
class Candidate:
    ledger_id: Any
    count: int


@dataclass(frozen=True)
class RuleOutcome:
    status: str                       # none | suggested | ambiguous
    candidates: tuple[Candidate, ...]
    chosen: Candidate | None
    reason: str


def decide_from_rules(rules: Sequence[tuple[Any, int, bool]]) -> RuleOutcome:
    """rules = (ledger id, approved count, is_active) of one client + direction + key. Inactive rules are ignored."""
    live = [Candidate(ledger, count) for ledger, count, active in rules if active and count > 0]
    if not live:
        return RuleOutcome("none", (), None, "No earlier entry with this narration has been learned.")
    live.sort(key=lambda c: (-c.count, str(c.ledger_id)))
    if len(live) == 1:
        c = live[0]
        entries = "1 earlier entry" if c.count == 1 else f"{c.count} earlier entries"
        return RuleOutcome("suggested", (c,), c, f"Learned from {entries} with the same narration.")
    return RuleOutcome("ambiguous", tuple(live), None,
                       f"The same narration was booked to {len(live)} different ledgers earlier; choose one. No ledger was selected.")


# ============================================================================================ model answer (D-43, D-53)


@dataclass(frozen=True)
class LlmChoice:
    ledger_id: Any | None
    confidence: Decimal | None
    problem: str | None


_ONE = Decimal(1)


def read_llm_choice(answer: Mapping[str, Any], options: Mapping[str, Any]) -> LlmChoice:
    """The answer must be {"choice": "<option code>" | null, "confidence": 0..1 | null (optional)} and nothing else. The model never
    sees or returns a ledger id: it picks a code from `options` (code -> ledger id). Anything that does not fit is dropped."""
    if not isinstance(answer, Mapping) or set(answer) - {"choice", "confidence"} or "choice" not in answer:
        return LlmChoice(None, None, "The model's answer does not have the agreed shape and was dropped.")
    choice = answer["choice"]
    if choice is None:
        return LlmChoice(None, None, None)
    if not isinstance(choice, str) or choice not in options:
        return LlmChoice(None, None, "The model chose a ledger that is not in the client's list; the answer was dropped.")
    raw = answer.get("confidence")
    confidence = None
    if raw is not None:
        if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
            return LlmChoice(None, None, "The model's confidence is not a number; the answer was dropped.")
        try:
            confidence = Decimal(str(raw))
        except InvalidOperation:
            return LlmChoice(None, None, "The model's confidence is not a number; the answer was dropped.")
        if not confidence.is_finite() or not (0 <= confidence <= _ONE):
            return LlmChoice(None, None, "The model's confidence is outside 0 to 1; the answer was dropped.")
        confidence = confidence.quantize(Decimal("0.0001"))
    return LlmChoice(options[choice], confidence, None)
