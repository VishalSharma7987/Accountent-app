"""TDS masters rules (Phase 4, package A): PAN T-10 / T-11, lower-deduction certificate T-12 (master side),
ledger roles T-14, deductor TAN T-30. Pure Python: plain data in, ValidationError lists out, plain accountant language.

The PAN 4th letter table is the structure of the PAN number (not a tax rate). A mismatch is only a warning (T-11).
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from app.engine.models import Group, Ledger, ValidationError
from app.engine.tds_types import DeducteeType, PanStatus
from app.engine.validation import group_chain

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
TAN_RE = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")
PAN_STATUSES = tuple(s.value for s in PanStatus)
DEDUCTEE_TYPES = tuple(t.value for t in DeducteeType)
_WITH_PAN = (PanStatus.VALID.value, PanStatus.INVALID.value)

# 4th letter of a PAN -> deductee types it fits ('other' fits anything)
PAN_LETTER_TYPES: dict[str, tuple[str, ...]] = {
    "P": ("individual",), "H": ("huf",), "C": ("company",), "F": ("firm", "llp"),
    "A": ("aop_boi", "co_operative_society"), "B": ("aop_boi",), "T": ("trust",), "L": ("local_authority",),
    "J": (), "G": (),  # artificial juridical person / government: only the type 'other'
}

# role -> (allowed group codes, label, kind of the nature that may be attached: None = no nature allowed)
ROLE_RULES: dict[str, tuple[tuple[str, ...], str, str | None]] = {
    "tds_payable": (("duties_taxes",), "Duties & Taxes", "tds"),
    "tcs_payable": (("duties_taxes",), "Duties & Taxes", "tcs"),
    "tds_receivable": (("current_assets",), "Current Assets or Loans & Advances (Asset)", None),
    "tcs_receivable": (("current_assets",), "Current Assets or Loans & Advances (Asset)", None),
    "interest_expense": (("indirect_expenses",), "Indirect Expenses", None),
    "late_fee_expense": (("indirect_expenses",), "Indirect Expenses", None),
}


def _d(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def validate_tan(tan: str | None) -> list[ValidationError]:
    """T-30: TAN format AAAA99999A (4 letters, 5 digits, 1 letter; capitals)."""
    if tan is None or TAN_RE.match(tan) is None:
        return [ValidationError("T-30", "The TAN must be 4 letters, 5 digits and 1 letter in capitals (AAAA99999A).")]
    return []


def validate_deductee(pan: str | None, pan_status: str, deductee_type: str) -> tuple[list[ValidationError], list[ValidationError]]:
    """(errors, warnings). T-10: format and status; T-09: known type; T-11 (warning): PAN 4th letter vs type."""
    errors: list[ValidationError] = []
    warnings: list[ValidationError] = []
    if pan_status not in PAN_STATUSES:
        errors.append(ValidationError("T-10", f"PAN status '{pan_status}' is not one of: {', '.join(PAN_STATUSES)}."))
    if deductee_type not in DEDUCTEE_TYPES:
        errors.append(ValidationError("T-09", f"Deductee type '{deductee_type}' is not one of: {', '.join(DEDUCTEE_TYPES)}."))
    if errors:
        return errors, warnings
    if pan_status in _WITH_PAN:
        if pan is None:
            errors.append(ValidationError("T-10", f"A deductee with PAN status '{pan_status}' needs a PAN."))
        elif PAN_RE.match(pan) is None:
            errors.append(ValidationError(
                "T-10", f"PAN '{pan}' is not in the form AAAAA9999A (5 letters, 4 digits, 1 letter, capitals); "
                        "enter the right PAN or set the status to 'missing'."))
    elif pan is not None:
        errors.append(ValidationError(
            "T-10", f"A deductee with PAN status '{pan_status}' must not carry a PAN; remove it or set the status to 'valid'."))
    if not errors and pan is not None and deductee_type != DeducteeType.OTHER.value:
        letter = pan[3]
        if deductee_type not in PAN_LETTER_TYPES.get(letter, ()):
            warnings.append(ValidationError(
                "T-11", f"The 4th letter '{letter}' of PAN {pan} does not fit the deductee type '{deductee_type}'; check the type."))
    return errors, warnings


def validate_certificate(*, certificate_no: str, rate: Decimal, max_amount: Decimal, valid_from: date,
                         valid_to: date) -> list[ValidationError]:
    """T-12 (master side): number given, rate 0..100 with at most 4 decimals (0 = nil), limit > 0 with 2 decimals,
    validity from <= to. Use against the normal rate and the used-up limit is checked by the deduction engine."""
    errors: list[ValidationError] = []
    if not certificate_no.strip():
        errors.append(ValidationError("T-12", "The certificate number is required."))
    if rate < 0 or rate > 100:
        errors.append(ValidationError("T-12", f"The certificate rate {rate} % must be between 0 and 100 (0 = nil deduction)."))
    elif rate != rate.quantize(Decimal("0.0001")):
        errors.append(ValidationError("T-12", f"The certificate rate {rate} % can have at most 4 decimal places."))
    if max_amount <= 0:
        errors.append(ValidationError("T-12", "The amount limit of the certificate must be more than zero."))
    elif max_amount != max_amount.quantize(Decimal("0.01")):
        errors.append(ValidationError("T-12", f"The amount limit {max_amount} can have at most 2 decimal places."))
    if valid_to < valid_from:
        errors.append(ValidationError(
            "T-12", f"The certificate is valid from {_d(valid_from)} but ends on {_d(valid_to)}, which is earlier."))
    return errors


def available_amount(max_amount: Decimal, amount_used: Decimal) -> Decimal:
    """Limit left on a certificate (never below zero)."""
    return max(max_amount - amount_used, Decimal("0.00"))


def validate_ledger_roles(
    entries: Sequence[tuple[str, str | None, object]], ledgers: Mapping[object, Ledger | None],
    groups: Mapping[str, Group], client_id: object, nature_kinds: Mapping[str, str],
) -> list[ValidationError]:
    """T-14: each (role, nature_key | None, ledger_id) names a known role, a nature of the right kind (or none), a
    ledger that exists for the client, is active and sits under the group of the role; no (role, nature) twice."""
    errors: list[ValidationError] = []
    seen: set[tuple[str, str | None]] = set()
    for role, nature, ledger_id in entries:
        if role not in ROLE_RULES:
            errors.append(ValidationError("T-14", f"'{role}' is not a TDS / TCS ledger role."))
            continue
        allowed, label, nature_kind = ROLE_RULES[role]
        if (role, nature) in seen:
            errors.append(ValidationError("T-14", f"Role '{role}' is given twice" + (f" for nature '{nature}'." if nature else ".")))
            continue
        seen.add((role, nature))
        if nature is not None:
            if nature_kind is None:
                errors.append(ValidationError("T-14", f"Role '{role}' is one ledger for all natures; remove the nature '{nature}'."))
                continue
            if nature not in nature_kinds:
                errors.append(ValidationError("T-14", f"Nature '{nature}' (role '{role}') does not exist."))
                continue
            if nature_kinds[nature] != nature_kind:
                errors.append(ValidationError(
                    "T-14", f"Nature '{nature}' is a {nature_kinds[nature].upper()} nature and cannot take role '{role}'."))
                continue
        ledger = ledgers.get(ledger_id)
        if ledger is None or ledger.client_id != client_id:
            errors.append(ValidationError("T-14", f"The ledger given for role '{role}' does not exist for this client."))
        elif not ledger.is_active:
            errors.append(ValidationError("T-14", f"Ledger '{ledger.name}' (role '{role}') is inactive."))
        elif not set(allowed) & set(group_chain(ledger.group_code, groups)):
            group = groups.get(ledger.group_code)
            errors.append(ValidationError(
                "T-14", f"Ledger '{ledger.name}' is under {group.name if group else ledger.group_code}; "
                        f"the ledger for role '{role}' must be under {label}."))
    return errors
