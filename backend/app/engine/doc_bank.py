"""Engine checks of an extracted bank statement (Phase 7, package D). Pure Python: no DB, web, LLM or OCR imports.

Two rules exist only here (the catalogue in doc_types.RULES stops at D-17 for the invoice; the main agent may add these two):
  D-18  the printed running balance does not equal opening balance + credits - debits so far (a row was misread or missed), or the printed
        closing balance differs from the balance the rows give.
  D-19  a row has both a debit and a credit amount, or neither.
D-05 (required fields, confidence), D-06 (amounts plain with at most 2 decimals, dates parse) are the invoice rules applied to the rows.
The statement is only READ here: nothing in it becomes a voucher (bank lines enter through the bank-statement import of Phase 2).
Balances are signed text as printed ("-100.00" = overdrawn); the running check is exact (a bank statement has no rounding).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.engine.doc_check import Collector, blank, parse_date_text, source_checks_for
from app.engine.doc_types import DocFinding, Field, Severity
from app.engine.money import format_inr

BANK_RULES = {
    "D-18": "Printed running balance (or closing balance) differs from opening balance + credits - debits",
    "D-19": "A statement row has both a debit and a credit amount, or neither",
}

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class BankLine:
    date: Field
    narration: Field
    reference: Field
    debit: Field
    credit: Field
    balance: Field


@dataclass(frozen=True)
class BankStatement:
    bank_name: Field
    account_ref: Field
    period_from: Field
    period_to: Field
    opening_balance: Field
    closing_balance: Field
    lines: tuple[BankLine, ...]
    currency: str = "INR"
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BankCheckContext:
    today: date
    min_confidence: Decimal = Decimal("0.85")
    require_source: bool = True
    page_count: int | None = None


@dataclass(frozen=True)
class BankCheckResult:
    findings: tuple[DocFinding, ...]

    @property
    def blocking(self) -> list[DocFinding]:
        return [f for f in self.findings if f.severity in (Severity.ERROR, Severity.REVIEW)]


def _fields(st: BankStatement):
    for name in ("bank_name", "account_ref", "period_from", "period_to", "opening_balance", "closing_balance"):
        yield name, getattr(st, name)
    for i, line in enumerate(st.lines):
        for name in ("date", "narration", "reference", "debit", "credit", "balance"):
            yield f"lines[{i}].{name}", getattr(line, name)


def check_bank_statement(st: BankStatement, ctx: BankCheckContext) -> BankCheckResult:
    out = Collector()
    source_checks_for(_fields(st), ctx.require_source, ctx.min_confidence, ctx.page_count, out)
    if st.currency.strip().upper() != "INR":
        out.add("D-06", Severity.ERROR, f"Currency '{st.currency}' is not accepted: only INR statements can be used.", "currency")
    if not st.lines:
        out.add("D-05", Severity.ERROR, "No transaction rows were found on the statement: enter them.", "lines")

    opening = out.amount(st.opening_balance, "opening_balance", signed=True)
    closing = out.amount(st.closing_balance, "closing_balance", signed=True)
    for name in ("period_from", "period_to"):
        _date(getattr(st, name), name, out, required=False)

    running: Decimal | None = opening
    for i, line in enumerate(st.lines):
        p = f"lines[{i}]"
        _date(line.date, f"{p}.date", out, required=True)
        if blank(line.narration.value):
            out.add("D-05", Severity.ERROR, f"Row {i + 1}: narration was not found: enter it.", f"{p}.narration")
        before = len(out.items)
        debit = out.amount(line.debit, f"{p}.debit")
        credit = out.amount(line.credit, f"{p}.credit")
        balance = out.amount(line.balance, f"{p}.balance", signed=True)
        unreadable = len(out.items) > before
        movement: Decimal | None = None
        if not unreadable:
            has_d, has_c = (debit or ZERO) > 0, (credit or ZERO) > 0
            if has_d == has_c:
                what = "both a debit and a credit amount" if has_d else "neither a debit nor a credit amount"
                out.add("D-19", Severity.ERROR, f"Row {i + 1} has {what}: exactly one of them must be given.", p)
            else:
                movement = (credit or ZERO) - (debit or ZERO)
        if running is None and balance is not None and movement is not None:
            running = balance - movement      # no opening balance printed: the first row defines the starting point
            continue
        if running is not None and movement is not None:
            running += movement
            if balance is not None and balance != running:
                out.add("D-18", Severity.ERROR,
                        f"Row {i + 1}: printed balance {format_inr(balance)} but the rows give {format_inr(running)} "
                        f"(difference {format_inr(abs(balance - running))}): a row may be misread or missing.",
                        f"{p}.balance", f"{balance:.2f}", f"{running:.2f}")
        else:
            running = balance          # this row's movement is unknown: continue from what the statement says
    if st.lines and running is not None and closing is not None and closing != running:
        out.add("D-18", Severity.ERROR,
                f"Printed closing balance {format_inr(closing)} but the rows give {format_inr(running)} "
                f"(difference {format_inr(abs(closing - running))}).", "closing_balance", f"{closing:.2f}", f"{running:.2f}")
    return BankCheckResult(tuple(out.items))


def _date(f: Field, path: str, out: Collector, *, required: bool) -> None:
    if blank(f.value):
        if required:
            out.add("D-05", Severity.ERROR, f"Row {int(path.split('[')[1].split(']')[0]) + 1}: date was not found: enter it.", path)
        return
    try:
        parse_date_text(f.value)
    except ValueError:
        out.add("D-06", Severity.ERROR, f"Date '{f.value.strip()}' is not a valid date (use dd-mm-yyyy).", path)


