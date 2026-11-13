"""GST masters: registration (G-04 .. G-06), item master (G-07), ledger roles (G-08). Pure Python."""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from app.engine.gst_types import GstRegistration, StateCode
from app.engine.gstin import extract_pan, validate_gstin
from app.engine.models import Group, Ledger, ValidationError
from app.engine.validation import group_chain

REGISTRATION_TYPES = ("regular", "composition")
RETURN_FREQUENCIES = ("monthly", "qrmp")
COMPOSITION_CATEGORIES = ("manufacturer", "trader", "restaurant", "service_provider")
ITEM_KINDS = ("goods", "service")
HSN_RE = re.compile(r"^[0-9]{4}([0-9]{2}([0-9]{2})?)?$")  # 4, 6 or 8 digits
SAC_RE = re.compile(r"^99[0-9]{4}$")

_TAX_GROUP = ("duties_taxes",)
ROLE_GROUPS: dict[str, tuple[tuple[str, ...], str]] = {
    **{f"{kind}_{head}": (_TAX_GROUP, "Duties & Taxes")
       for kind in ("output", "input", "rcm") for head in ("cgst", "sgst", "igst", "cess")},
    "round_off": (("indirect_expenses", "indirect_incomes"), "Indirect Expenses or Indirect Incomes"),
    "itc_reversal": (("indirect_expenses",), "Indirect Expenses"),
    "composition_tax_expense": (("indirect_expenses",), "Indirect Expenses"),
    "composition_tax_payable": (_TAX_GROUP, "Duties & Taxes"),
}
# roles an invoice needs before invoice mode can be used (RCM, cess, round-off and reversal only when used)
REQUIRED_ROLES: dict[str, tuple[str, ...]] = {
    "regular": ("output_cgst", "output_sgst", "output_igst", "input_cgst", "input_sgst", "input_igst"),
    "composition": ("composition_tax_expense", "composition_tax_payable"),
}


def _d(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def in_force(effective_from: date, effective_to: date | None, on: date) -> bool:
    return effective_from <= on and (effective_to is None or on <= effective_to)


def periods_overlap(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    """Closed date ranges (None = open ended) share at least one day."""
    return (a_to is None or b_from <= a_to) and (b_to is None or a_from <= b_to)


def registration_covers(registration: GstRegistration, on: date) -> bool:
    """G-06: an invoice date must fall inside an active registration's period."""
    return registration.is_active and in_force(registration.effective_from, registration.effective_to, on)


def validate_registration(
    *,
    gstin: str,
    registration_type: str,
    return_frequency: str,
    composition_category: str | None,
    effective_from: date,
    effective_to: date | None,
    client_gst_type: str,
    client_pan: str | None,
    state_codes: Iterable[StateCode],
    others: Sequence[tuple[object, date, date | None]],
) -> list[ValidationError]:
    """G-01 .. G-06 for one registration. `others` = (id, from, to) of the client's other registrations of the SAME
    GSTIN (the one being edited excluded). The GSTIN is checked as given (normalise first)."""
    errors = validate_gstin(gstin, state_codes, effective_from)
    if not errors and client_pan is not None and extract_pan(gstin) != client_pan:
        errors.append(ValidationError(
            "G-04",
            f"PAN {client_pan} of the client does not match GSTIN {gstin}: characters 3 to 12 of the GSTIN must be "
            f"the PAN ({extract_pan(gstin)}).",
        ))

    if registration_type not in REGISTRATION_TYPES:
        errors.append(ValidationError("G-05", "Registration type must be regular or composition."))
    elif client_gst_type == "unregistered":
        errors.append(ValidationError(
            "G-05", "This client is set up as unregistered under GST, so it cannot have a GST registration. "
            "Change the client's GST type first if it has registered.",
        ))
    elif client_gst_type != registration_type:
        errors.append(ValidationError(
            "G-05",
            f"This client is set up as a {client_gst_type} taxpayer, so its registration must be "
            f"{client_gst_type}, not {registration_type}.",
        ))
    if return_frequency not in RETURN_FREQUENCIES:
        errors.append(ValidationError("G-05", "Return frequency must be monthly or qrmp."))
    elif return_frequency == "qrmp" and registration_type != "regular":
        errors.append(ValidationError("G-05", "QRMP (quarterly return, monthly payment) is only for regular registrations."))
    if registration_type == "composition":
        if composition_category not in COMPOSITION_CATEGORIES:
            errors.append(ValidationError(
                "G-05", "A composition registration needs a category: manufacturer, trader, restaurant or service_provider."
            ))
    elif composition_category is not None and registration_type == "regular":
        errors.append(ValidationError("G-05", "A composition category can be given only for a composition registration."))

    if effective_to is not None and effective_to < effective_from:
        errors.append(ValidationError(
            "G-06", f"The registration end date {_d(effective_to)} is before its start date {_d(effective_from)}."
        ))
    else:
        for _, o_from, o_to in others:
            if periods_overlap(effective_from, effective_to, o_from, o_to):
                errors.append(ValidationError(
                    "G-06",
                    f"GSTIN {gstin} is already registered for {_d(o_from)} to {_d(o_to) if o_to else 'open end'}, "
                    "which overlaps this period.",
                ))
                break
    return errors


def validate_item(kind: str, hsn_sac: str, uqc: str | None, uqc_codes: Iterable[str]) -> list[ValidationError]:
    """G-07: HSN 4/6/8 digits (goods), SAC 6 digits starting 99 (service); goods need a UQC from the table."""
    errors: list[ValidationError] = []
    if kind not in ITEM_KINDS:
        return [ValidationError("G-07", "Item kind must be goods or service.")]
    if kind == "goods":
        if HSN_RE.match(hsn_sac or "") is None:
            errors.append(ValidationError(
                "G-07", f"HSN '{hsn_sac}' is not valid: it must be 4, 6 or 8 digits."
            ))
    elif SAC_RE.match(hsn_sac or "") is None:
        errors.append(ValidationError(
            "G-07", f"SAC '{hsn_sac}' is not valid: it must be 6 digits starting with 99."
        ))
    if uqc is None:
        if kind == "goods":
            errors.append(ValidationError("G-07", "A goods item needs a unit quantity code (UQC), for example NOS or KGS."))
    elif uqc not in set(uqc_codes):
        errors.append(ValidationError("G-07", f"UQC '{uqc}' is not in the UQC list."))
    return errors


def validate_ledger_roles(
    roles: Mapping[str, Ledger | None], groups: Mapping[str, Group], client_id: object
) -> list[ValidationError]:
    """G-08: each mapped ledger exists, is active, belongs to the client and sits under the group of its role."""
    errors: list[ValidationError] = []
    for role, ledger in roles.items():
        if role not in ROLE_GROUPS:
            errors.append(ValidationError("G-08", f"'{role}' is not a GST ledger role."))
            continue
        allowed, label = ROLE_GROUPS[role]
        if ledger is None or ledger.client_id != client_id:
            errors.append(ValidationError("G-08", f"The ledger given for role '{role}' does not exist for this client."))
        elif not ledger.is_active:
            errors.append(ValidationError("G-08", f"Ledger '{ledger.name}' (role '{role}') is inactive."))
        elif not set(allowed) & set(group_chain(ledger.group_code, groups)):
            group = groups.get(ledger.group_code)
            errors.append(ValidationError(
                "G-08",
                f"Ledger '{ledger.name}' is under {group.name if group else ledger.group_code}; "
                f"the ledger for role '{role}' must be under {label}.",
            ))
    return errors


def missing_roles(registration_type: str, mapped: Mapping[str, object]) -> list[str]:
    """Roles an invoice-mode voucher needs that are not mapped yet (in the order of REQUIRED_ROLES)."""
    return [role for role in REQUIRED_ROLES.get(registration_type, ()) if role not in mapped]
