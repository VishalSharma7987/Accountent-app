"""Party master rules P-01 .. P-07 and P-09 .. P-11 (P-08 needs the database and lives in services/parties.py).

Pure functions: plain data in, a list of ValidationError out, in plain accountant language. Format checks only
(P-01), PAN (P-03) and state (P-04) consistency; when the caller passes the GST state-code table (`gst_state_codes`)
the GSTIN check character (G-02) and the state in force (G-03) of engine/gstin.py are checked too.
The patterns are the same as the CHECK constraints of migration 0005.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date

from app.engine.gst_types import StateCode
from app.engine.gstin import validate_gstin
from app.engine.models import Group, Ledger, ValidationError
from app.engine.validation import group_chain

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
STATE_RE = re.compile(r"^[0-9]{2}$")
UDYAM_RE = re.compile(r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$")
GST_REGISTRATION_TYPES = ("regular", "composition", "unregistered", "sez", "overseas", "uin_holder", "government")
GST_TYPES_WITH_GSTIN = ("regular", "composition", "sez", "uin_holder")
MSME_CATEGORIES = ("none", "micro", "small", "medium")
MSME_ACTIVITIES = ("manufacturing", "services", "trading")
MSME_MAX_AGREED_DAYS = 45  # MSMED Act 2006 s.15: an agreed credit period is never longer than 45 days


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
    msme_activity: str | None = None,
    udyam_registration_date: date | None = None,
    msme_written_agreement: bool = False,
    msme_agreed_days: int | None = None,
    gst_registration_type: str | None = None,
    gst_state_codes: Sequence[StateCode] | None = None,
    on_date: date | None = None,
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

    gst_checks = gst_state_codes is not None and on_date is not None
    gstin_ok = gstin is not None and GSTIN_RE.match(gstin) is not None
    if gstin is not None and not gstin_ok:
        errors.append(ValidationError(
            "P-01", f"GSTIN '{gstin}' is not valid: it must be 15 characters in the GST format (for example 27AABCU9603R1ZN)."
        ))
    elif gstin is not None and gst_checks:  # check character (G-02) and state in force (G-03) on top of the format
        errors += [e for e in validate_gstin(gstin, gst_state_codes, on_date) if e.rule_id in ("G-02", "G-03")]  # type: ignore[arg-type]
    pan_ok = pan is not None and PAN_RE.match(pan) is not None
    if pan is not None and not pan_ok:
        errors.append(ValidationError(
            "P-02", f"PAN '{pan}' is not valid: it must be 5 letters, 4 digits and 1 letter (for example AABCU9603R)."
        ))
    state_ok = state_code is not None and STATE_RE.match(state_code) is not None
    if state_code is not None and not state_ok:
        errors.append(ValidationError("P-04", f"State code '{state_code}' is not valid: it must be 2 digits."))
    if gstin_ok and pan_ok and gstin[2:12] != pan:  # type: ignore[index]
        errors.append(ValidationError(
            "P-03",
            f"PAN {pan} does not match GSTIN {gstin}: characters 3 to 12 of the GSTIN must be the PAN ({gstin[2:12]}).",  # type: ignore[index]
        ))
    if gstin_ok and state_ok and gstin[:2] != state_code:  # type: ignore[index]
        errors.append(ValidationError(
            "P-04", f"State code {state_code} does not match GSTIN {gstin}, which starts with {gstin[:2]}."  # type: ignore[index]
        ))

    if gst_registration_type is not None:
        if gst_registration_type not in GST_REGISTRATION_TYPES:
            errors.append(ValidationError(
                "G-05", f"GST registration type '{gst_registration_type}' is not valid: use one of "
                f"{', '.join(GST_REGISTRATION_TYPES)}."
            ))
        elif gst_registration_type in GST_TYPES_WITH_GSTIN and gstin is None:
            errors.append(ValidationError(
                "G-01", f"A {gst_registration_type} party needs a GSTIN: enter it, or set the type to unregistered."
            ))
        elif gst_registration_type == "unregistered" and gstin is not None:
            errors.append(ValidationError(
                "G-01", f"The party is marked unregistered but has GSTIN {gstin}: remove the GSTIN or change the type."
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

    if msme_activity is not None and msme_activity not in MSME_ACTIVITIES:
        errors.append(ValidationError("P-09", "MSME activity must be manufacturing, services or trading."))
    elif msme_category in ("micro", "small") and msme_activity is None:
        errors.append(ValidationError(
            "P-09",
            f"MSME category '{msme_category}' needs the supplier's activity (manufacturing, services or trading): "
            "the payment-time rule covers manufacturing and services suppliers only.",
        ))
    if udyam_no is not None and udyam_registration_date is None:
        errors.append(ValidationError(
            "P-10", "The Udyam registration date is required when a Udyam number is given: only supplies on or "
            "after that date are covered by the payment-time rule."
        ))

    days_ok = (
        isinstance(msme_agreed_days, int) and not isinstance(msme_agreed_days, bool)
        and 1 <= msme_agreed_days <= MSME_MAX_AGREED_DAYS
    )
    if msme_written_agreement and msme_agreed_days is None:
        errors.append(ValidationError(
            "P-11", "A written agreement needs the agreed credit days (1 to 45): MSMED Act s.15 allows no more than 45 days."
        ))
    elif msme_agreed_days is not None and not msme_written_agreement:
        errors.append(ValidationError(
            "P-11", "Agreed credit days can be entered only when a written agreement exists; without one the legal limit is 15 days."
        ))
    elif msme_agreed_days is not None and not days_ok:
        errors.append(ValidationError(
            "P-11", f"Agreed credit days must be a whole number from 1 to 45 (got {msme_agreed_days!r}): "
            "MSMED Act s.15 does not allow an agreed period above 45 days."
        ))

    if not _credit_days_ok(credit_days):
        errors.append(ValidationError(
            "P-06", f"Credit days must be a whole number of days, not negative (got {credit_days!r})."
        ))
    return errors
