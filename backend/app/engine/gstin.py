"""GSTIN rules G-01 .. G-04. Pure Python: state codes come in as plain data (rule table `gst_state_codes`).

The check character is the mod-36 algorithm of docs/PHASE3_LEGAL_VALUES.md section 2 (an algorithm, not law;
no official publication could be read, so it is `secondary_verified`).
"""

import re
from collections.abc import Iterable
from datetime import date

from app.engine.gst_types import StateCode
from app.engine.models import ValidationError

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# 96 = foreign country (place of supply of exports / imports of services only), 97 = other territory,
# 99 = centre jurisdiction: none of them can be the state of a registration (rule G-03)
NOT_REGISTRATION_STATES = frozenset({"96", "97", "99"})


def gstin_check_char(first14: str) -> str:
    """The check character of the first 14 characters (Luhn mod 36): factor 1 for even positions, 2 for odd."""
    total = 0
    for i, char in enumerate(first14):
        product = ALPHABET.index(char) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return ALPHABET[(36 - total % 36) % 36]


def extract_pan(gstin: str) -> str:
    """The PAN inside a GSTIN: characters 3 to 12."""
    return gstin[2:12]


def _in_force(row: StateCode, on: date) -> bool:
    return row.effective_from <= on and (row.effective_to is None or on <= row.effective_to)


def validate_gstin(text: str, state_codes: Iterable[StateCode], on_date: date) -> list[ValidationError]:
    """G-01 format, G-02 check character, G-03 state code. The text is checked as given (normalise first)."""
    if GSTIN_RE.match(text or "") is None:
        return [ValidationError(
            "G-01",
            f"GSTIN '{text}' is not valid: it must be 15 characters in the GST format "
            "(2-digit state code, 10-character PAN, entity number, Z, check character), for example 27AAPFU0939F1ZV.",
        )]
    errors: list[ValidationError] = []
    expected = gstin_check_char(text[:14])
    if text[14] != expected:
        errors.append(ValidationError(
            "G-02",
            f"GSTIN {text} has a wrong check character '{text[14]}': the last character should be '{expected}'. "
            "Please check the GSTIN against the registration certificate.",
        ))
    code = text[:2]
    if code in NOT_REGISTRATION_STATES:
        errors.append(ValidationError(
            "G-03", f"GSTIN {text} starts with {code}, which is not a registration state "
            "(96 is a foreign country, 97 another territory, 99 the centre jurisdiction).",
        ))
    elif not any(row.code == code and _in_force(row, on_date) for row in state_codes):
        errors.append(ValidationError(
            "G-03",
            f"GSTIN {text} starts with {code}, which is not a state code in force on {on_date.strftime('%d-%m-%Y')}.",
        ))
    return errors


def state_pan_errors(gstin: str, *, state_code: str | None, pan: str | None) -> list[ValidationError]:
    """G-04 for a GSTIN of valid format: the state code and the PAN, when known, must be those inside the GSTIN."""
    errors: list[ValidationError] = []
    if state_code is not None and state_code != gstin[:2]:
        errors.append(ValidationError(
            "G-04", f"State code {state_code} does not match GSTIN {gstin}, which starts with {gstin[:2]}."
        ))
    if pan is not None and pan != extract_pan(gstin):
        errors.append(ValidationError(
            "G-04",
            f"PAN {pan} does not match GSTIN {gstin}: characters 3 to 12 of the GSTIN must be the PAN "
            f"({extract_pan(gstin)}).",
        ))
    return errors
