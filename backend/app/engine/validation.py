"""Voucher rules V-01 .. V-09 and V-13, V-14 (V-10 lives in duplicates.py; V-11 and V-12 are lifecycle rules of the
service layer). Pure functions: they take plain data and return ALL errors, in plain accountant language.

Rules and wording: CLAUDE.md section 5. Group codes are the seeded ones (database/seeds/0001_account_groups.sql).
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from app.engine.models import Group, Ledger, PeriodInfo, ValidationError, VoucherDraft
from app.engine.money import MoneyError, format_inr, parse_amount

VOUCHER_TYPES = (
    "contra", "payment", "receipt", "sales", "purchase", "credit_note", "debit_note", "journal",
)

CASH_BANK = frozenset({"cash_in_hand", "bank_accounts"})
SALES_ACCOUNTS = frozenset({"sales_accounts"})
PURCHASE_ACCOUNTS = frozenset({"purchase_accounts"})
PURCHASE_SIDE = frozenset({"purchase_accounts", "fixed_assets", "direct_expenses", "indirect_expenses"})
NEEDS_REFERENCE = {
    "purchase": "A Purchase voucher needs the supplier's bill number in Reference No.",
    "debit_note": "A Debit Note needs the original bill or debit note reference in Reference No.",
}

ZERO = Decimal("0.00")


def group_chain(code: str, groups: Mapping[str, Group]) -> list[str]:
    """The group's own code, then its parents up to the top. Stops on a cycle or a missing parent."""
    chain = [code]
    current = groups.get(code)
    while current is not None and current.parent_code is not None and current.parent_code not in chain:
        if current.parent_code not in groups:
            break
        chain.append(current.parent_code)
        current = groups[current.parent_code]
    return chain


def _is_blank(text: str | None) -> bool:
    return text is None or text.strip() == ""


def _fmt_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _in_groups(ledger: Ledger, codes: frozenset[str], groups: Mapping[str, Group]) -> bool:
    return any(code in codes for code in group_chain(ledger.group_code, groups))


def _group_name(ledger: Ledger, groups: Mapping[str, Group]) -> str:
    group = groups.get(ledger.group_code)
    return group.name if group else ledger.group_code


def validate_voucher(
    draft: VoucherDraft,
    ledgers_by_id: Mapping[object, Ledger],
    groups_by_code: Mapping[str, Group],
    fy_ranges: Sequence[tuple[date, date]],
    period_for_date: Callable[[date], PeriodInfo | None],
    *,
    is_reversal: bool = False,
) -> list[ValidationError]:
    """Check a voucher draft and return every problem found (empty list = valid).

    ledgers_by_id        ledgers the draft may refer to (other clients' ledgers are reported, not hidden)
    groups_by_code       the group tree (system groups + this client's own)
    fy_ranges            (start, end) of each financial year of the client
    period_for_date      the period a date falls into (open/locked) or None when no period exists
    is_reversal          the voucher mirrors a posted voucher (every line swapped), so the voucher-type rules
                         (V-08) do not apply: a reversed Payment legitimately has a debit to cash
    """
    if draft.voucher_type not in VOUCHER_TYPES:
        raise ValueError(f"Unknown voucher type {draft.voucher_type!r}")

    errors: list[ValidationError] = []
    lines = draft.lines

    # ---- V-01 --------------------------------------------------------------------------------------
    if len(lines) < 2:
        errors.append(ValidationError("V-01", f"A voucher needs at least 2 lines; this one has {len(lines)}."))

    # ---- V-02 / V-03: each line's amounts -----------------------------------------------------------
    amounts: dict[int, tuple[Decimal, Decimal]] = {}  # line_no -> (debit, credit), only for readable lines
    amounts_ok = True
    for number, line in enumerate(lines, start=1):
        sides: list[Decimal] = []
        readable = True
        for raw in (line.debit, line.credit):
            if raw is None or (isinstance(raw, str) and raw.strip() == ""):
                sides.append(ZERO)
                continue
            try:
                sides.append(parse_amount(raw))
            except MoneyError as problem:
                errors.append(ValidationError("V-03", f"Line {number}: {problem}.", number))
                readable = False
                sides.append(ZERO)
        if not readable:
            amounts_ok = False
            continue
        debit, credit = sides
        if debit > 0 and credit > 0:
            errors.append(ValidationError("V-02", f"Line {number}: enter either a Debit or a Credit amount, not both.", number))
            amounts_ok = False
        elif debit == 0 and credit == 0:
            errors.append(ValidationError("V-02", f"Line {number}: enter a Debit or a Credit amount; both are empty or zero.", number))
            amounts_ok = False
        else:
            amounts[number] = (debit, credit)

    # ---- V-05: ledgers (and the party ledger) -------------------------------------------------------
    ledgers_ok = True
    for number, line in enumerate(lines, start=1):
        ledger = ledgers_by_id.get(line.ledger_id)
        if ledger is None:
            errors.append(ValidationError("V-05", f"Line {number}: this ledger does not exist.", number))
            ledgers_ok = False
        elif ledger.client_id != draft.client_id:
            errors.append(ValidationError("V-05", f"Line {number}: ledger '{ledger.name}' belongs to another client.", number))
            ledgers_ok = False
        elif not ledger.is_active:
            errors.append(ValidationError("V-05", f"Line {number}: ledger '{ledger.name}' is inactive.", number))
            ledgers_ok = False

    party: Ledger | None = None
    if draft.party_ledger_id is not None:
        party = ledgers_by_id.get(draft.party_ledger_id)
        if party is None:
            errors.append(ValidationError("V-05", "The party ledger does not exist."))
        elif party.client_id != draft.client_id:
            errors.append(ValidationError("V-05", f"The party ledger '{party.name}' belongs to another client."))
            party = None
        elif not party.is_active:
            errors.append(ValidationError("V-05", f"The party ledger '{party.name}' is inactive."))

    # ---- V-04: Dr = Cr (only when the amounts can be trusted) ---------------------------------------
    if len(lines) >= 2 and amounts_ok:
        total_debit = sum((d for d, _ in amounts.values()), ZERO)
        total_credit = sum((c for _, c in amounts.values()), ZERO)
        if total_debit != total_credit:
            errors.append(ValidationError(
                "V-04",
                f"Debit {format_inr(total_debit)} and Credit {format_inr(total_credit)} are not equal "
                f"(difference {format_inr(abs(total_debit - total_credit))})",
            ))

    # ---- V-06 / V-07: date and period ---------------------------------------------------------------
    if not any(start <= draft.voucher_date <= end for start, end in fy_ranges):
        errors.append(ValidationError(
            "V-06", f"Voucher date {_fmt_date(draft.voucher_date)} is not inside any financial year of this client."
        ))
    else:
        period = period_for_date(draft.voucher_date)
        if period is None:
            errors.append(ValidationError(
                "V-07",
                f"No period is defined for {_fmt_date(draft.voucher_date)}; create the period before entering this voucher.",
            ))
        elif period.status == "locked":
            errors.append(ValidationError(
                "V-07", f"The period {_fmt_date(period.start)} to {_fmt_date(period.end)} is locked."
            ))

    # ---- V-08: voucher-type rules -------------------------------------------------------------------
    if is_reversal:
        pass
    elif draft.voucher_type == "contra" and draft.party_ledger_id is not None:
        errors.append(ValidationError(
            "V-08", "A Contra voucher moves money between Cash and Bank; it cannot have a party ledger."
        ))
    if not is_reversal and len(lines) >= 2 and amounts_ok and ledgers_ok:
        rows = [
            (number, ledgers_by_id[line.ledger_id], *amounts[number])
            for number, line in enumerate(lines, start=1)
        ]
        errors.extend(_type_rules(draft.voucher_type, rows, groups_by_code))

    # ---- V-09 ---------------------------------------------------------------------------------------
    if _is_blank(draft.narration):
        errors.append(ValidationError("V-09", "Narration is required."))

    # ---- V-13 / V-14 --------------------------------------------------------------------------------
    if party is not None and not any(line.ledger_id == draft.party_ledger_id for line in lines):
        errors.append(ValidationError("V-13", f"Party ledger '{party.name}' is not in the voucher's lines."))
    if draft.voucher_type in NEEDS_REFERENCE and _is_blank(draft.reference_no):
        errors.append(ValidationError("V-14", NEEDS_REFERENCE[draft.voucher_type]))

    errors.sort(key=lambda e: (e.rule_id, e.line_no is None, e.line_no or 0))
    return errors


def _type_rules(
    voucher_type: str,
    rows: list[tuple[int, Ledger, Decimal, Decimal]],
    groups: Mapping[str, Group],
) -> list[ValidationError]:
    """V-08 for one voucher type. rows = (line_no, ledger, debit, credit) with readable amounts."""
    out: list[ValidationError] = []
    cash_bank = [(n, l, d, c) for n, l, d, c in rows if _in_groups(l, CASH_BANK, groups)]

    if voucher_type == "contra":
        for number, ledger, _, _ in rows:
            if not _in_groups(ledger, CASH_BANK, groups):
                out.append(ValidationError(
                    "V-08",
                    f"Line {number}: a Contra voucher can only use Cash and Bank ledgers, but "
                    f"'{ledger.name}' is under {_group_name(ledger, groups)}.",
                    number,
                ))

    elif voucher_type in ("payment", "receipt"):
        label = "Payment" if voucher_type == "payment" else "Receipt"
        side, side_word = ("credit", "Credit") if voucher_type == "payment" else ("debit", "Debit")
        if len(cash_bank) == len(rows):
            out.append(ValidationError(
                "V-08",
                f"Every line of this {label} is a Cash or Bank ledger; money moving between them is a Contra voucher.",
            ))
        elif not any((c if side == "credit" else d) > 0 for _, _, d, c in cash_bank):
            out.append(ValidationError(
                "V-08", f"A {label} voucher needs at least one {side_word} line to a Cash or Bank ledger."
            ))

    elif voucher_type == "sales":
        if not any(c > 0 and _in_groups(l, SALES_ACCOUNTS, groups) for _, l, _, c in rows):
            out.append(ValidationError("V-08", "A Sales voucher needs at least one Credit line to a Sales Accounts ledger."))

    elif voucher_type == "purchase":
        if not any(d > 0 and _in_groups(l, PURCHASE_SIDE, groups) for _, l, d, _ in rows):
            out.append(ValidationError(
                "V-08",
                "A Purchase voucher needs at least one Debit line to a Purchase Accounts, Fixed Assets, "
                "Direct Expenses or Indirect Expenses ledger.",
            ))

    elif voucher_type == "credit_note":
        if not any(d > 0 and _in_groups(l, SALES_ACCOUNTS, groups) for _, l, d, _ in rows):
            out.append(ValidationError(
                "V-08", "A Credit Note needs at least one Debit line to a Sales Accounts ledger (the sales return)."
            ))

    elif voucher_type == "debit_note":
        if not any(c > 0 and _in_groups(l, PURCHASE_ACCOUNTS, groups) for _, l, _, c in rows):
            out.append(ValidationError(
                "V-08", "A Debit Note needs at least one Credit line to a Purchase Accounts ledger (the purchase return)."
            ))

    elif voucher_type == "journal":
        for number, ledger, _, _ in cash_bank:
            out.append(ValidationError(
                "V-08",
                f"Line {number}: a Journal cannot use Cash or Bank ledgers ('{ledger.name}'); "
                f"use a Payment, Receipt or Contra voucher.",
                number,
            ))
    return out
