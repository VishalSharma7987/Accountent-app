"""Saved party / line mappings (Phase 7 package E, rules D-20, D-21, D-24). Pure Python: plain data in, findings out.

A mapping says "this supplier / this kind of line always goes to that ledger". It is saved only from what an accountant accepted
(D-26, the service's business). Resolving never guesses: no mapping -> review (D-20 / D-21), more than one possible ledger ->
review (D-24). Nothing here creates a party, ledger or item.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.engine.doc_types import DocFinding, Severity

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PARTY_KINDS = ("gstin", "name")
LINE_KINDS = ("hsn_sac", "description")
_SPACES = re.compile(r"\s+")
_PUNCT = re.compile(r"[.,;:'\"()]")


class MappingKeyError(ValueError):
    """The key cannot be a mapping key (wrong format / empty). The message is for the accountant."""


# ============================================================================================ keys


def normalise_gstin(value: str | None) -> str | None:
    text = (value or "").strip().upper()
    return text or None


def normalise_name(value: str | None) -> str | None:
    """Lower case, '&' written as 'and', dots / commas / quotes removed, one space between words. None when nothing is left.
    Only the spelling is normalised ('Sharma Suppliers Pvt. Ltd.' = 'sharma suppliers pvt ltd'); different words stay different."""
    text = (value or "").lower().replace("&", " and ")
    text = _SPACES.sub(" ", _PUNCT.sub("", text)).strip()
    return text or None


def normalise_hsn(value: str | None) -> str | None:
    text = re.sub(r"[\s.]", "", (value or "")).lower()
    return text or None


def party_key(match_kind: str, raw: str | None) -> str:
    """The normalised key to store / look up. Raises MappingKeyError for an unknown kind, an empty key or a GSTIN that is not in GSTIN format."""
    if match_kind == "gstin":
        key = normalise_gstin(raw)
        if key is None or not GSTIN_RE.match(key):
            raise MappingKeyError("A GSTIN mapping needs a GSTIN in the 15-character format.")
        return key
    if match_kind == "name":
        key = normalise_name(raw)
        if key is None:
            raise MappingKeyError("A name mapping needs a party name.")
        return key
    raise MappingKeyError("A party mapping is by 'gstin' or by 'name'.")


def line_key(match_kind: str, raw: str | None) -> str:
    if match_kind == "hsn_sac":
        key = normalise_hsn(raw)
        if key is None or not key.isalnum():
            raise MappingKeyError("An HSN / SAC mapping needs an HSN or SAC code.")
        return key
    if match_kind == "description":
        key = normalise_name(raw)
        if key is None:
            raise MappingKeyError("A description mapping needs the item description.")
        return key
    raise MappingKeyError("A line mapping is by 'hsn_sac' or by 'description'.")


# ============================================================================================ data


@dataclass(frozen=True)
class PartyMap:
    id: object
    match_kind: str
    match_key: str
    party_ledger_id: object


@dataclass(frozen=True)
class LineMap:
    id: object
    match_kind: str
    match_key: str
    party_ledger_id: object | None   # scope: this party's lines only
    ledger_id: object
    item_id: object | None = None


@dataclass(frozen=True)
class PartyResolution:
    ledger_id: object | None
    map_ids: tuple = ()
    finding: DocFinding | None = None


@dataclass(frozen=True)
class LineResolution:
    ledger_id: object | None
    item_id: object | None = None
    map_ids: tuple = ()
    finding: DocFinding | None = None


# ============================================================================================ resolving


def resolve_party(*, label: str, gstin: str | None, name: str | None, maps: Sequence[PartyMap], field_path: str) -> PartyResolution:
    """label is 'Supplier' or 'Buyer'. A GSTIN match and a name match that point to different ledgers are ambiguous (D-24)."""
    g, n = normalise_gstin(gstin), normalise_name(name)
    hits = [m for m in maps if (m.match_kind == "gstin" and g is not None and m.match_key == g)
            or (m.match_kind == "name" and n is not None and m.match_key == n)]
    ledgers = {str(m.party_ledger_id) for m in hits}
    who = f"{label} '{(name or '').strip() or 'not printed'}'" + (f" (GSTIN {g})" if g else "")
    if not hits:
        return PartyResolution(None, (), DocFinding(
            "D-20", Severity.REVIEW,
            f"{who} is not mapped to a party ledger. Choose the ledger and save the mapping; no party was created.", field_path))
    if len(ledgers) > 1:
        return PartyResolution(None, tuple(m.id for m in hits), DocFinding(
            "D-24", Severity.REVIEW,
            f"{who} points to {len(ledgers)} different ledgers in the saved mappings (GSTIN and name disagree). "
            "Fix the mappings; no choice was made.", field_path))
    return PartyResolution(hits[0].party_ledger_id, tuple(m.id for m in hits))


def resolve_line(*, n: int, description: str | None, hsn_sac: str | None, party_ledger_id: object | None,
                 maps: Sequence[LineMap]) -> LineResolution:
    """Lines of this party first, then lines of any party. Inside a tier a description match and an HSN match must agree on
    the ledger and the item, otherwise the line is ambiguous (D-24)."""
    d, h = normalise_name(description), normalise_hsn(hsn_sac)
    path = f"lines[{n - 1}].description"
    what = f"Line {n} '{(description or '').strip() or 'no description'}'" + (f" (HSN/SAC {h})" if h else "")

    def matches(m: LineMap) -> bool:
        return (m.match_kind == "description" and d is not None and m.match_key == d) or \
               (m.match_kind == "hsn_sac" and h is not None and m.match_key == h)

    scoped = [m for m in maps if m.party_ledger_id is not None and party_ledger_id is not None
              and str(m.party_ledger_id) == str(party_ledger_id) and matches(m)]
    unscoped = [m for m in maps if m.party_ledger_id is None and matches(m)]
    for tier in (scoped, unscoped):
        if not tier:
            continue
        targets = {(str(m.ledger_id), None if m.item_id is None else str(m.item_id)) for m in tier}
        if len(targets) > 1:
            return LineResolution(None, None, tuple(m.id for m in tier), DocFinding(
                "D-24", Severity.REVIEW,
                f"{what} points to different ledgers or items in the saved mappings. Fix the mappings; no choice was made.", path))
        first = tier[0]
        return LineResolution(first.ledger_id, first.item_id, tuple(m.id for m in tier))
    return LineResolution(None, None, (), DocFinding(
        "D-21", Severity.REVIEW,
        f"{what} has no saved ledger. Choose the purchase / sales / expense ledger and save the mapping; no ledger was created.", path))
