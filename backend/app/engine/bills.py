"""Bill-wise accounting: allocation rules B-01 .. B-05, due dates, open bills, ageing, opening-bills check.

Pure functions: no database, web or AI. Signed amounts everywhere: debit positive, credit negative (CLAUDE.md
section 5). A "bill" is a reference of one party: created by a new_ref allocation (or an opening bill) on the party's
natural side (debtor Dr / creditor Cr), or by an advance on the opposite side; settled by against_ref allocations.
A bill never ends on the wrong side of zero (B-04).
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.engine.models import (
    Allocation,
    Balance,
    OpenBill,
    OpeningBalance,
    ValidationError,
    VoucherLine,
)
from app.engine.money import MoneyError, format_inr, parse_amount

ZERO = Decimal("0.00")
KINDS = ("new_ref", "against_ref", "advance", "on_account")
CREATES = ("new_ref", "advance")
BUCKETS = ("not_due", "0-30", "31-60", "61-90", "90+")


def _fmt(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _clean(ref: str | None) -> str:
    return (ref or "").strip()


def ref_key(party_ledger_id: object, bill_ref: str) -> tuple[object, str]:
    """Identity of a bill: party + reference, trimmed and case-insensitive (rule B-03)."""
    return (party_ledger_id, _clean(bill_ref).lower())


@dataclass(frozen=True)
class PartyInfo:
    name: str
    nature: str  # debtor | creditor
    bill_wise: bool
    credit_days: int


@dataclass(frozen=True)
class BillState:
    """One bill as it stands: signed outstanding and the side it was created on ('Dr' | 'Cr')."""

    outstanding: Decimal
    origin: str
    bill_date: date | None = None


@dataclass(frozen=True)
class OpeningBillRow:
    party_ledger_id: object
    bill_ref: str
    bill_date: date
    due_date: date
    amount: Decimal  # signed


@dataclass(frozen=True)
class AllocationRow:
    """A stored allocation of a posted/reversed voucher, with the voucher's date. amount is signed."""

    party_ledger_id: object
    kind: str
    bill_ref: str | None
    voucher_date: date
    due_date: date | None
    amount: Decimal


@dataclass(frozen=True)
class ResolvedAllocation:
    """An allocation ready to store: due date resolved, trimmed reference, amount on the line's side."""

    line_no: int
    party_ledger_id: object
    kind: str
    bill_ref: str | None
    due_date: date | None
    debit: Decimal
    credit: Decimal


def default_due_date(bill_date: date, credit_days: int, explicit: date | None = None) -> date:
    """The due date given by the user, else bill date + the party's credit days."""
    return explicit if explicit is not None else bill_date + timedelta(days=credit_days)


# ======================================================================================== B-01 .. B-05


def _line_amount_side(line: VoucherLine) -> tuple[Decimal, str] | None:
    """(amount, 'Dr'|'Cr') of a readable line with exactly one side, else None (V-02/V-03 report those)."""
    sides: list[Decimal] = []
    for raw in (line.debit, line.credit):
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            sides.append(ZERO)
            continue
        try:
            sides.append(parse_amount(raw))
        except MoneyError:
            return None
    debit, credit = sides
    if debit > 0 and credit == 0:
        return debit, "Dr"
    if credit > 0 and debit == 0:
        return credit, "Cr"
    return None


def validate_allocations(
    lines: Sequence[VoucherLine],
    parties: Mapping[object, PartyInfo],
    voucher_date: date,
    state: Mapping[tuple, BillState],
    used_refs: Collection[tuple] = (),
    *,
    is_reversal: bool = False,
) -> list[ValidationError]:
    """B-01 .. B-05 for one voucher. Returns every problem found (empty = valid).

    parties     the `parties` rows of the ledgers on the voucher (ledger id -> PartyInfo); a ledger without a
                row is a plain ledger (Phase 1 behaviour)
    state       the posted bills of the party/ies as they stand now: ref_key -> BillState (settled bills included)
    used_refs   every bill reference ever created (any year), so a reference is never reused (B-03)
    is_reversal the voucher mirrors a posted one: exempt from B-02 (a reversal goes on the bill's own side) but
                still never allowed to push a bill to the wrong side of zero (B-04)
    """
    errors: list[ValidationError] = []
    created_here: set[tuple] = set()
    running: dict[tuple, Decimal] = {}
    flagged: set[tuple] = set()

    for number, line in enumerate(lines, start=1):
        allocations = line.allocations
        info = parties.get(line.ledger_id)
        if info is None or not info.bill_wise:
            if allocations:
                errors.append(ValidationError(
                    "B-01",
                    f"Line {number}: bill allocations are accepted only for bill-wise party ledgers "
                    "(Sundry Debtors / Sundry Creditors set up as parties).",
                    number,
                ))
            continue
        read = _line_amount_side(line)
        if read is None:
            continue
        line_amount, side = read
        natural = "Dr" if info.nature == "debtor" else "Cr"

        total = ZERO
        amounts_ok = True
        parsed: list[tuple[Allocation, Decimal]] = []
        for alloc in allocations:
            try:
                amount = parse_amount(alloc.amount)
            except MoneyError as problem:
                errors.append(ValidationError("B-05", f"Line {number}: allocation {problem}.", number))
                amounts_ok = False
                continue
            if amount == 0:
                errors.append(ValidationError(
                    "B-05", f"Line {number}: an allocation amount must be greater than zero.", number
                ))
                amounts_ok = False
                continue
            total += amount
            parsed.append((alloc, amount))

        if not allocations:
            errors.append(ValidationError(
                "B-01",
                f"Line {number}: '{info.name}' is a bill-wise party; allocate the full amount "
                f"{format_inr(line_amount)} to bills (new reference, against reference, advance or on account).",
                number,
            ))
        elif amounts_ok and total != line_amount:
            errors.append(ValidationError(
                "B-01",
                f"Line {number}: bill allocations of '{info.name}' add up to {format_inr(total)} but the line is "
                f"{format_inr(line_amount)} (difference {format_inr(abs(line_amount - total))}).",
                number,
            ))

        for alloc, amount in parsed:
            ref = _clean(alloc.bill_ref)
            key = ref_key(line.ledger_id, ref)
            if alloc.kind not in KINDS:
                errors.append(ValidationError(
                    "B-02",
                    f"Line {number}: unknown allocation kind '{alloc.kind}'; use new_ref, against_ref, advance or on_account.",
                    number,
                ))
                continue

            # ---- B-05: due date
            if alloc.due_date is not None:
                if alloc.kind != "new_ref":
                    errors.append(ValidationError(
                        "B-05", f"Line {number}: a due date applies only to a new bill reference.", number
                    ))
                elif alloc.due_date < voucher_date:
                    errors.append(ValidationError(
                        "B-05",
                        f"Line {number}: due date {_fmt(alloc.due_date)} is before the bill date {_fmt(voucher_date)}.",
                        number,
                    ))

            # ---- B-02: kind against side
            if not is_reversal:
                if alloc.kind == "new_ref" and side != natural:
                    errors.append(ValidationError(
                        "B-02",
                        f"Line {number}: a new bill reference of a {info.nature} goes on the {natural} side; this line is "
                        f"{side}. Use an advance, an against-reference or on account.",
                        number,
                    ))
                elif alloc.kind == "advance" and side == natural:
                    errors.append(ValidationError(
                        "B-02",
                        f"Line {number}: an advance of a {info.nature} goes on the {'Cr' if natural == 'Dr' else 'Dr'} "
                        f"side; this line is {side}. Use a new reference.",
                        number,
                    ))

            # ---- B-03: references
            if alloc.kind == "on_account":
                if ref:
                    errors.append(ValidationError(
                        "B-03", f"Line {number}: an on-account amount has no bill reference ('{ref}' given).", number
                    ))
                continue
            if not ref:
                code = "B-03" if alloc.kind in CREATES else "B-04"
                what = {"new_ref": "a new bill reference", "advance": "an advance reference",
                        "against_ref": "the reference of the bill to settle"}[alloc.kind]
                errors.append(ValidationError(code, f"Line {number}: {what} is required.", number))
                continue
            if alloc.kind in CREATES:
                if key in state or key in used_refs or key in created_here:
                    errors.append(ValidationError(
                        "B-03",
                        f"Line {number}: reference '{ref}' is already used by '{info.name}'; "
                        "a bill reference can be used only once per party.",
                        number,
                    ))
                created_here.add(key)
                continue

            # ---- against_ref: B-04 (and B-02 against the bill's own side)
            bill = state.get(key)
            if bill is None:
                errors.append(ValidationError(
                    "B-04",
                    f"Line {number}: bill '{ref}' of '{info.name}' does not exist; only posted bills can be settled.",
                    number,
                ))
                continue
            if bill.bill_date is not None and voucher_date < bill.bill_date:
                errors.append(ValidationError(
                    "B-04",
                    f"Line {number}: bill '{ref}' of '{info.name}' is dated {_fmt(bill.bill_date)}; it cannot be "
                    f"settled by a voucher dated {_fmt(voucher_date)}.",
                    number,
                ))
                continue
            if not is_reversal and side == bill.origin:
                errors.append(ValidationError(
                    "B-02",
                    f"Line {number}: bill '{ref}' is on the {bill.origin} side; it is settled by a {'Cr' if bill.origin == 'Dr' else 'Dr'} "
                    f"line, but this line is {side}.",
                    number,
                ))
            running[key] = running.get(key, ZERO) + (amount if side == "Dr" else -amount)
            after = bill.outstanding + running[key]
            wrong = after < 0 if bill.origin == "Dr" else after > 0
            if wrong and key not in flagged:
                flagged.add(key)
                errors.append(ValidationError(
                    "B-04",
                    f"Line {number}: bill '{ref}' of '{info.name}' has {format_inr(abs(bill.outstanding))} "
                    f"{bill.origin} outstanding; this voucher would take it {format_inr(abs(after))} past zero "
                    f"(over by {format_inr(abs(after))}).",
                    number,
                ))
    errors.sort(key=lambda e: (e.rule_id, e.line_no is None, e.line_no or 0))
    return errors


def resolve_allocations(
    lines: Sequence[VoucherLine], parties: Mapping[object, PartyInfo], voucher_date: date
) -> list[ResolvedAllocation]:
    """The allocations of a VALID voucher as rows to store: due date filled in for new_ref (explicit date, else
    voucher date + the party's credit days), reference trimmed, amount on the line's side."""
    out: list[ResolvedAllocation] = []
    for number, line in enumerate(lines, start=1):
        info = parties.get(line.ledger_id)
        if info is None or not line.allocations:
            continue
        read = _line_amount_side(line)
        if read is None:
            continue
        side = read[1]
        for alloc in line.allocations:
            amount = parse_amount(alloc.amount)
            due = default_due_date(voucher_date, info.credit_days, alloc.due_date) if alloc.kind == "new_ref" else None
            ref = _clean(alloc.bill_ref) or None
            out.append(ResolvedAllocation(
                number, line.ledger_id, alloc.kind, ref, due,
                amount if side == "Dr" else ZERO, amount if side == "Cr" else ZERO,
            ))
    return out


def mirror_allocations(allocations: Sequence[Allocation]) -> tuple[Allocation, ...]:
    """The allocations of a reversal voucher's line: every reference becomes an against_ref on the same
    reference (the reversal goes on the opposite side); on_account stays on_account."""
    return tuple(
        Allocation("on_account", a.amount) if a.kind == "on_account" else Allocation("against_ref", a.amount, a.bill_ref)
        for a in allocations
    )


# ================================================================================================ open bills


@dataclass
class _Bill:
    party_ledger_id: object
    ref: str
    kind: str
    bill_date: date
    due_date: date | None
    original: Decimal
    outstanding: Decimal


def _fold(
    opening: Sequence[OpeningBillRow], allocations: Sequence[AllocationRow]
) -> tuple[dict[tuple, _Bill], dict[object, _Bill]]:
    bills: dict[tuple, _Bill] = {}
    on_account: dict[object, _Bill] = {}
    for row in opening:
        key = ref_key(row.party_ledger_id, row.bill_ref)
        if key in bills:
            raise ValueError(f"bill {row.bill_ref!r} of party {row.party_ledger_id!r} is created twice")
        bills[key] = _Bill(row.party_ledger_id, _clean(row.bill_ref), "bill", row.bill_date, row.due_date,
                           row.amount, row.amount)
    ordered = sorted(allocations, key=lambda a: (a.kind not in CREATES, a.voucher_date))
    for a in ordered:
        if a.kind in CREATES:
            key = ref_key(a.party_ledger_id, a.bill_ref or "")
            if key in bills:
                raise ValueError(f"bill {a.bill_ref!r} of party {a.party_ledger_id!r} is created twice")
            bills[key] = _Bill(a.party_ledger_id, _clean(a.bill_ref), "bill" if a.kind == "new_ref" else "advance",
                               a.voucher_date, a.due_date, a.amount, a.amount)
        elif a.kind == "against_ref":
            key = ref_key(a.party_ledger_id, a.bill_ref or "")
            if key not in bills:
                raise ValueError(f"allocation against unknown bill {a.bill_ref!r} of party {a.party_ledger_id!r}")
            bills[key].outstanding += a.amount
        elif a.kind == "on_account":
            entry = on_account.get(a.party_ledger_id)
            if entry is None:
                on_account[a.party_ledger_id] = _Bill(a.party_ledger_id, "", "on_account", a.voucher_date,
                                                      a.voucher_date, a.amount, a.amount)
            else:
                entry.original += a.amount
                entry.outstanding += a.amount
                entry.bill_date = min(entry.bill_date, a.voucher_date)
                entry.due_date = entry.bill_date
        else:
            raise ValueError(f"unknown allocation kind {a.kind!r}")
    return bills, on_account


def bill_state(opening: Sequence[OpeningBillRow], allocations: Sequence[AllocationRow]) -> dict[tuple, BillState]:
    """Every bill ever created (settled ones included) with its outstanding and origin side."""
    bills, _ = _fold(opening, allocations)
    return {
        key: BillState(b.outstanding.quantize(Decimal("0.01")), "Dr" if b.original > 0 else "Cr", b.bill_date)
        for key, b in bills.items()
    }


def open_bills(
    opening: Sequence[OpeningBillRow], allocations: Sequence[AllocationRow], party_names: Mapping[object, str]
) -> list[OpenBill]:
    """The open items of the parties: bills and advances with a non-zero outstanding, and one on-account item per
    party (net, dated by its earliest entry). Fully settled items drop out. Sorted by party name, date, reference."""
    bills, on_account = _fold(opening, allocations)
    cents = Decimal("0.01")
    items = [b for b in (*bills.values(), *on_account.values()) if b.outstanding != 0]
    items.sort(key=lambda b: (party_names[b.party_ledger_id].lower(), b.bill_date, b.ref.lower()))
    return [
        OpenBill(
            b.party_ledger_id, party_names[b.party_ledger_id], b.ref or None, b.kind, b.bill_date, b.due_date,
            b.original.quantize(cents), b.outstanding.quantize(cents),
        )
        for b in items
    ]


# ============================================================================================ opening bills


@dataclass(frozen=True)
class OpeningBillIn:
    bill_ref: str | None
    bill_date: date
    amount: object  # as entered
    side: str  # "Dr" | "Cr"
    due_date: date | None = None


def validate_opening_bills(bills: Sequence[OpeningBillIn]) -> list[ValidationError]:
    """B-03 (reference present and unique) and B-05 (amount, side, due date) for a party's opening bills.
    line_no is the 1-based row."""
    errors: list[ValidationError] = []
    seen: set[str] = set()
    for number, bill in enumerate(bills, start=1):
        ref = _clean(bill.bill_ref)
        if not ref:
            errors.append(ValidationError("B-03", f"Row {number}: the bill reference is required.", number))
        elif ref.lower() in seen:
            errors.append(ValidationError("B-03", f"Row {number}: reference '{ref}' is entered twice.", number))
        seen.add(ref.lower())
        try:
            if parse_amount(bill.amount) == 0:
                errors.append(ValidationError("B-05", f"Row {number}: the amount must be greater than zero.", number))
        except MoneyError as problem:
            errors.append(ValidationError("B-05", f"Row {number}: {problem}.", number))
        if bill.side not in ("Dr", "Cr"):
            errors.append(ValidationError("B-05", f"Row {number}: the side must be Dr or Cr.", number))
        if bill.due_date is not None and bill.due_date < bill.bill_date:
            errors.append(ValidationError(
                "B-05",
                f"Row {number}: due date {_fmt(bill.due_date)} is before the bill date {_fmt(bill.bill_date)}.",
                number,
            ))
    errors.sort(key=lambda e: (e.rule_id, e.line_no or 0))
    return errors


def resolve_opening_bills(
    party_ledger_id: object, bills: Sequence[OpeningBillIn], credit_days: int
) -> list[OpeningBillRow]:
    """Valid opening bills as rows: trimmed reference, due date = bill date + credit days unless given, signed amount."""
    out = []
    for bill in bills:
        amount = parse_amount(bill.amount)
        out.append(OpeningBillRow(
            party_ledger_id, _clean(bill.bill_ref), bill.bill_date,
            default_due_date(bill.bill_date, credit_days, bill.due_date), amount if bill.side == "Dr" else -amount,
        ))
    return out


@dataclass(frozen=True)
class BillsCheck:
    total: Balance  # of the opening bills
    ledger: Balance  # the ledger's opening balance
    difference: Balance  # ledger - bills; nil when they agree
    is_balanced: bool


def opening_bills_check(bills_signed_total: Decimal, ledger_opening: OpeningBalance | None) -> BillsCheck:
    """Do the party's opening bills add up to its ledger opening balance (rules B-07 / P-08)?"""
    ledger = ZERO if ledger_opening is None else ledger_opening.debit - ledger_opening.credit
    difference = Balance.from_signed(ledger - bills_signed_total)
    return BillsCheck(
        Balance.from_signed(bills_signed_total), Balance.from_signed(ledger), difference, difference.side is None
    )


# ===================================================================================================== ageing


@dataclass(frozen=True)
class AgedItem:
    bill_ref: str | None
    kind: str
    bill_date: date | None
    due_date: date | None
    original: Decimal  # in the report's direction (receivable: Dr positive; payable: Cr positive)
    outstanding: Decimal
    days_past_due: int  # 0 while not yet due
    bucket: str


@dataclass(frozen=True)
class PartyAgeing:
    party_ledger_id: object
    party_name: str
    items: tuple[AgedItem, ...]
    buckets: dict[str, Decimal]
    total: Decimal
    ledger_balance: Decimal  # closing balance of the party ledger in the report's direction
    ties: bool


@dataclass(frozen=True)
class AgeingReport:
    kind: str  # receivable | payable
    as_on: date
    parties: tuple[PartyAgeing, ...]
    buckets: dict[str, Decimal]
    total: Decimal
    ties: bool


def bucket_for(due_date: date, as_on: date) -> tuple[str, int]:
    """(bucket, days past due). Due today counts as 0-30 days; a due date after the report date is 'not_due'."""
    days = (as_on - due_date).days
    if days < 0:
        return "not_due", 0
    if days <= 30:
        return "0-30", days
    if days <= 60:
        return "31-60", days
    if days <= 90:
        return "61-90", days
    return "90+", days


def ageing(
    open_items: Sequence[OpenBill],
    as_on: date,
    kind: str,
    parties: Mapping[object, PartyInfo],
    ledger_balances: Mapping[object, Decimal],
) -> AgeingReport:
    """Outstanding and ageing of the receivable (debtors) or payable (creditors) parties, as on a date.

    open_items       open bills (signed, Dr +) of the bill-wise parties
    parties          the bill-wise parties of the client (name, nature)
    ledger_balances  each party's closing ledger balance as on the date, signed (Dr +): the tie check compares it
                     with the total of the open items
    Amounts are shown in the report's direction (receivable: debit positive; payable: credit positive), so an
    advance or on-account amount shows as a negative figure. Buckets count days past the DUE date.
    """
    if kind not in ("receivable", "payable"):
        raise ValueError(f"kind must be receivable or payable, not {kind!r}")
    nature = "debtor" if kind == "receivable" else "creditor"
    sign = Decimal(1) if kind == "receivable" else Decimal(-1)
    cents = Decimal("0.01")

    wanted = {pid for pid, info in parties.items() if info.nature == nature}
    by_party: dict[object, list[OpenBill]] = {pid: [] for pid in wanted}
    for item in open_items:
        if item.party_ledger_id in wanted:
            by_party[item.party_ledger_id].append(item)

    rows: list[PartyAgeing] = []
    grand = {name: ZERO for name in BUCKETS}
    grand_total = ZERO
    all_tie = True
    for pid, items in by_party.items():
        balance = ledger_balances.get(pid, ZERO)
        if not items and balance == 0:
            continue
        aged = []
        buckets = {name: ZERO for name in BUCKETS}
        raw_total = ZERO
        for item in items:
            due = item.due_date or item.bill_date
            bucket, days = bucket_for(due, as_on) if due is not None else ("not_due", 0)
            outstanding = (item.outstanding * sign).quantize(cents)
            aged.append(AgedItem(item.bill_ref, item.kind, item.bill_date, item.due_date,
                                 (item.original * sign).quantize(cents), outstanding, days, bucket))
            buckets[bucket] += outstanding
            raw_total += item.outstanding
        ties = raw_total == balance
        all_tie = all_tie and ties
        for name in BUCKETS:
            grand[name] += buckets[name]
        total = (raw_total * sign).quantize(cents)
        grand_total += total
        rows.append(PartyAgeing(pid, parties[pid].name, tuple(aged), {k: v.quantize(cents) for k, v in buckets.items()},
                                total, (balance * sign).quantize(cents), ties))
    rows.sort(key=lambda r: r.party_name.lower())
    return AgeingReport(kind, as_on, tuple(rows), {k: v.quantize(cents) for k, v in grand.items()},
                        grand_total.quantize(cents), all_tie)
