"""D-50 / D-52: masking of personal and secret data before any text goes to a language model. Pure Python, no DB / web / AI imports.

`mask(text)` replaces, with numbered placeholders, every
  * GSTIN (it contains the PAN of its holder)                      -> [GSTIN_n]
  * PAN                                                            -> [PAN_n]
  * Aadhaar (12 digits, plain or grouped 4-4-4, first digit 2-9)    -> [AADHAAR_n]
  * bank account number (any other run of 9 or more digits, 16-digit groups like 1234 5678 9012 3456, or the digits after a
    keyword such as "A/c No." when there are 6 to 18 of them)       -> [ACCOUNT_n]
  * text that looks like an OpenRouter key (sk-or-...)             -> [SECRET_n]
The same text always gets the same placeholder (repeated values share one). Over-masking is harmless because `restore` puts the
original text back from the in-memory mapping, which is never stored: a 12-digit invoice number is masked and comes back unchanged.
A digit run that is clearly an amount (followed by ".dd" or preceded by "d.") is not masked.

`find_leftovers` / `assert_clean` are a second, independently written scan of the masked text; the gateway refuses to send anything
that is not clean. Reports and errors hold counts per kind, never values.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

KINDS = ("GSTIN", "PAN", "AADHAAR", "ACCOUNT", "SECRET")

_SEP = r"[ \-\u00a0]"
_COMBINED = re.compile(
    r"(?P<secret>sk-or-[A-Za-z0-9_\-]+)"
    r"|(?P<gstin>\d{2}[A-Za-z]{5}\d{4}[A-Za-z][1-9A-Za-z][Zz][0-9A-Za-z])"
    r"|(?P<pan>[A-Za-z]{5}\d{4}[A-Za-z])"
    r"|(?P<kw>\b(?:a/c|acc(?:ount|t)?\.?)(?:\s*(?:no\.?|number|num\.?|\#))?\s*[:.\-]?\s*)(?P<kwnum>\d(?:[\d \-\u00a0]{3,22})\d)"
    r"|(?<!\d)(?P<grouped>\d{4}(?:" + _SEP + r"\d{4}){2,3})(?!\d)"
    r"|(?<!\d)(?P<run>\d{9,})(?!\d)",
    re.IGNORECASE,
)
_LITERAL_TOKEN = re.compile(r"\[(GSTIN|PAN|AADHAAR|ACCOUNT|SECRET)_(\d+)\]")
_AMOUNT_TAIL = re.compile(r"\.\d")
_AMOUNT_HEAD = re.compile(r"\d\.$")


class MaskingError(ValueError):
    """Text that still holds personal or secret data after masking. `kinds` = {kind: count}; the message never holds a value."""

    def __init__(self, kinds: dict[str, int]):
        super().__init__("The text still contains " + ", ".join(f"{k} x{n}" for k, n in sorted(kinds.items())) + " after masking; nothing was sent.")
        self.kinds = kinds


@dataclass(frozen=True)
class MaskResult:
    text: str
    report: dict[str, int]                             # kind -> number of occurrences masked (never values)
    mapping: dict[str, str] = field(repr=False)        # token -> original text; in memory only, never stored


def _digits(value: str) -> str:
    return "".join(str(unicodedata.digit(c)) for c in value if c.isdigit())


def _is_aadhaar(digits: str) -> bool:
    return len(digits) == 12 and digits[0] in "23456789"


def mask(text: str) -> MaskResult:
    counters = {k: 0 for k in KINDS}
    for m in _LITERAL_TOKEN.finditer(text):      # numbering starts above any placeholder-looking text already present
        counters[m.group(1)] = max(counters[m.group(1)], int(m.group(2)))
    tokens: dict[tuple[str, str], str] = {}
    mapping: dict[str, str] = {}
    report: dict[str, int] = {}

    def token(kind: str, original: str) -> str:
        report[kind] = report.get(kind, 0) + 1
        key = (kind, original)
        if key not in tokens:
            counters[kind] += 1
            tokens[key] = f"[{kind}_{counters[kind]}]"
            mapping[tokens[key]] = original
        return tokens[key]

    def digits_kind(original: str) -> str:
        return "AADHAAR" if _is_aadhaar(_digits(original)) else "ACCOUNT"

    def replace(m: re.Match) -> str:
        whole = m.group(0)
        if m.group("secret"):
            return token("SECRET", whole)
        if m.group("gstin"):
            return token("GSTIN", whole)
        if m.group("pan"):
            return token("PAN", whole)
        if m.group("kw") is not None:
            number = m.group("kwnum")
            if not 6 <= len(_digits(number)) <= 18:
                return whole
            return m.group("kw") + token(digits_kind(number), number)
        if m.group("grouped"):
            return token(digits_kind(whole), whole)
        # a plain digit run: leave amounts alone (123456789.50, 0.123456789)
        before, after = text[: m.start()], text[m.end():]
        if _AMOUNT_TAIL.match(after) or _AMOUNT_HEAD.search(before):
            return whole
        return token(digits_kind(whole), whole)

    return MaskResult(_COMBINED.sub(replace, text), report, mapping)


def restore(text: str, mapping: dict[str, str]) -> str:
    """Put the original text back for every placeholder in the mapping; unknown placeholders stay as they are."""
    return _LITERAL_TOKEN.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)


def restore_data(value: Any, mapping: dict[str, str]) -> Any:
    """`restore` applied to every string value of parsed JSON (dicts, lists, strings); other values pass through."""
    if isinstance(value, str):
        return restore(value, mapping)
    if isinstance(value, list):
        return [restore_data(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: restore_data(v, mapping) for k, v in value.items()}
    return value


# ---- the independent second scan -----------------------------------------------------------------------------------------

def _window_is_pan(w: str) -> bool:
    return len(w) == 10 and w[:5].isalpha() and w[5:9].isdecimal() and w[9].isalpha() and w.isascii()


def find_leftovers(text: str) -> dict[str, int]:
    """Count what is still in the text: {"PAN": n, "GSTIN": n, "AADHAAR_OR_ACCOUNT": n, "SECRET": n}; empty = clean."""
    stripped = _LITERAL_TOKEN.sub(" ", text)
    found: dict[str, int] = {}

    def add(kind: str, n: int = 1) -> None:
        if n:
            found[kind] = found.get(kind, 0) + n

    add("SECRET", stripped.lower().count("sk-or-"))
    for i in range(len(stripped) - 9):
        w = stripped[i:i + 15]
        if len(w) == 15 and w[:2].isdecimal() and _window_is_pan(w[2:12]) and w[12] != " " and w[13] in "Zz" and w[14].isalnum():
            add("GSTIN")
        if _window_is_pan(stripped[i:i + 10]):
            add("PAN")
    for m in re.finditer(r"\d+", stripped):
        if len(m.group(0)) >= 9 and not (_AMOUNT_TAIL.match(stripped[m.end():]) or _AMOUNT_HEAD.search(stripped[: m.start()])):
            add("AADHAAR_OR_ACCOUNT")
    add("AADHAAR_OR_ACCOUNT", len(re.findall(r"(?<!\d)\d{4}(?:[ \-\u00a0]\d{4}){2,3}(?!\d)", stripped)))
    for m in re.finditer(r"(?i)\b(?:a/c|acc(?:ount|t)?\.?)[^0-9\n]{0,12}(\d[\d \-\u00a0]{3,22}\d)", stripped):
        if 6 <= len(_digits(m.group(1))) <= 18 and not re.fullmatch(r"\d{9,}|\d{4}(?:[ \-\u00a0]\d{4}){2,3}", m.group(1)):
            add("AADHAAR_OR_ACCOUNT")
    return found


def assert_clean(text: str) -> None:
    leftovers = find_leftovers(text)
    if leftovers:
        raise MaskingError(leftovers)
