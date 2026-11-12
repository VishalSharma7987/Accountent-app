"""Party master rules P-01 .. P-07 (P-08 needs the database and lives in services/parties.py).

Pure functions: plain data in, a list of ValidationError out, in plain accountant language. Format checks only:
the GSTIN check digit is a Phase 3 matter. The patterns are the same as the CHECK constraints of migration 0005.
"""

import re
from collections.abc import Mapping

from app.engine.models import Group, Ledger, ValidationError
from app.engine.validation import group_chain

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
STATE_RE = re.compile(r"^[0-9]{2}$")
UDYAM_RE = re.compile(r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$")
MSME_CATEGORIES = ("none", "micro", "small", "medium")


def normalise_id(value: str | None) -> str | None:
    """GSTIN / PAN / Udyam as typed: trimmed and in capitals; blank means "not given"."""
    if value is None:
        return None
    text = value.strip().upper()
    return text or None


def party_nature(ledger: Ledger, groups: Mapping[str, Group]) -> str | None:
    """'debtor' / 'creditor' when the ledger sits under Sundry Debtors / Sundry Creditors (directly or through
    sub-groups), else None."""
    chain = group_chain(ledger.group_code, groups)
    if "sundry_debtors" in chain:
        return "debtor"
    if "sundry_creditors" in chain:
        return "creditor"
    return None


def _credit_days_ok(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, float):
        return value.is_integer() and value >= 0
    if isinstance(value, str):
        return value.strip().isdigit()
    return False


def validate_party(
    ledger: Ledger,
    groups: Mapping[str, Group],
    *,
    gstin: str | None = None,
    pan: str | None = None,
    state_code: str | None = None,
    credit_days: object = 0,
    msme_category: str = "none",
    udyam_no: str | None = None,
) -> list[ValidationError]:
    """Every problem with the party details of one ledger (empty list = valid). Values are checked as given:
    use normalise_id first if capitals/blank should be forgiven."""
    errors: list[ValidationError] = []

    nature = party_nature(ledger, groups)
    if nature is None:
        group = groups.get(ledger.group_code)
        group_name = group.name if group else ledger.group_code
        errors.append(ValidationError(
            "P-07",
            f"Ledger '{ledger.name}' is under {group_name}; only ledgers under Sundry Debtors or "
            "Sundry Creditors can be parties.",
        ))

    gstin_ok = gstin is not None and GSTIN_RE.match(gstin) is not None
    if gstin is not None and not gstin_ok:
        errors.append(ValidationError(
            "P-01", f"GSTIN '{gstin}' is not valid: it must be 15 characters in the GST format (for example 27AABCU9603R1ZM)."
        ))
    pan_ok = pan is not None and PAN_RE.match(pan) is not None
    if pan is not None and not pan_ok:
        errors.append(ValidationError(
            "P-02", f"PAN '{pan}' is not valid: it must be 5 letters, 4 digits and 1 letter (for example AABCU9603R)."
        ))
    if gstin_ok and pan_ok and gstin[2:12] != pan:
        errors.append(ValidationError(
            "P-03",
            f"PAN {pan} does not match GSTIN {gstin}: characters 3 to 12 of the GSTIN must be the PAN ({gstin[2:12]}).",
        ))

    if state_code is not None:
        if STATE_RE.match(state_code) is None:
            errors.append(ValidationError("P-04", f"State code '{state_code}' is not valid: it must be 2 digits."))
        elif gstin_ok and gstin[:2] != state_code:
            errors.append(ValidationError(
                "P-04",
                f"State code {state_code} does not match GSTIN {gstin}, which starts with {gstin[:2]}.",
            ))

    if msme_category not in MSME_CATEGORIES:
        errors.append(ValidationError("P-05", "MSME category must be none, micro, small or medium."))
    elif msme_category != "none" and udyam_no is None:
        errors.append(ValidationError(
            "P-05", f"MSME category '{msme_category}' needs a valid Udyam number in the form UDYAM-XX-00-0000000."
        ))
    if udyam_no is not None and UDYAM_RE.match(udyam_no) is None:
        errors.append(ValidationError(
            "P-05", f"Udyam number '{udyam_no}' is not valid: use the form UDYAM-XX-00-0000000."
        ))

    if not _credit_days_ok(credit_days):
        errors.append(ValidationError(
            "P-06", f"Credit days must be a whole number of days, not negative (got {credit_days!r})."
        ))
    return errors
