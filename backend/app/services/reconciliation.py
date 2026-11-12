"""Bank reconciliation use-cases (Phase 2, step 2.7): unmatched lists, auto and manual matching, BRS, bank opening
items and DRAFT vouchers for bank-only lines.

All matching maths is in app/engine/reconcile.py and app/engine/brs.py; this file loads data, calls the engine and
writes the result. Services take a Connection and never commit; every rule check runs before the first write.

Scope decisions (docs/decisions_parts/C2.md): matching and the BRS work inside the financial year of `as_on`
(voucher lines of that year plus the bank opening items of that year); statement lines are not tied to a year.
`as_on` is a cut-off for BOTH sides of the unmatched list and of auto-match (items dated after it are not offered).
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.db import repositories as repo
from app.engine import brs as brs_engine
from app.engine import reconcile
from app.engine.models import ValidationError, VoucherDraft, VoucherLine
from app.engine.money import MoneyError, parse_amount
from app.engine.reconcile import DEPOSIT, PAYMENT, BankLine, BookItem
from app.services import audit, vouchers
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, require_actor

CENTS = Decimal("0.01")
RECON_DATE_WINDOW_DAYS = 7  # configuration, not law
OPENING_KINDS = {"issued_not_presented": PAYMENT, "deposited_not_cleared": DEPOSIT}


def _fmt(on: date) -> str:
    return on.strftime("%d-%m-%Y")


@dataclass(frozen=True)
class Unmatched:
    bank: list[BankLine]
    book: list[BookItem]
    suggestions: list[reconcile.Suggestion]


@dataclass(frozen=True)
class AutoMatchSummary:
    matched_groups: int
    matched_bank_lines: int
    matched_book_items: int
    suggestions_left: int


@dataclass(frozen=True)
class DraftsResult:
    created: list[tuple[object, object]]  # (bank_line_id, voucher_id)
    errors: list[tuple[object, list[ValidationError]]]  # (bank_line_id, rule errors); nothing is created when any


# ====================================================================================================== loading


def _bank_ledger(conn: Connection, client_id: object, ledger_id: object):
    ledger = repo.get_ledger(conn, client_id, ledger_id)
    if ledger is None:
        if not repo.client_exists(conn, client_id):
            raise ServiceError("not_found", "Client not found.")
        raise ServiceError("not_found", "Ledger not found for this client.")
    return ledger


def _year_for(conn: Connection, client_id: object, on: date):
    year = repo.financial_year_for_date(conn, client_id, on)
    if year is None:
        raise ServiceError("no_financial_year", f"No financial year of this client contains {_fmt(on)}.")
    return year


def _bank_rows(conn: Connection, client_id: object, ledger_id: object, ids: list | None = None):
    """Statement lines of the bank ledger: (line, statement_id, match_id)."""
    sql = (
        "SELECT l.id, l.txn_date, l.description, l.reference, l.debit, l.credit, l.statement_id, m.match_id "
        "FROM bank_statement_lines l JOIN bank_statements s ON s.id = l.statement_id AND s.client_id = l.client_id "
        "LEFT JOIN recon_match_items m ON m.bank_line_id = l.id "
        "WHERE s.client_id = :c AND s.bank_ledger_id = :b"
    )
    params: dict = {"c": client_id, "b": ledger_id}
    if ids is not None:
        sql += " AND l.id = ANY(:ids)"
        params["ids"] = ids
    return conn.execute(text(sql + " ORDER BY l.txn_date, s.period_from, l.line_no"), params).all()


def _bank_line(r) -> BankLine:
    # statement credit = money in = deposit; debit = money out = payment
    deposit = r.credit > 0
    return BankLine(r.id, r.txn_date, (r.credit if deposit else r.debit).quantize(CENTS),
                    DEPOSIT if deposit else PAYMENT, r.reference, r.description or "")


def _voucher_rows(conn: Connection, client_id: object, ledger_id: object, *, fy_id: object | None = None,
                  ids: list | None = None):
    sql = (
        "SELECT vl.id, v.voucher_date, v.voucher_number, v.narration, v.reference_no, vl.debit, vl.credit, "
        "v.financial_year_id, m.match_id "
        "FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id AND v.client_id = vl.client_id "
        "LEFT JOIN recon_match_items m ON m.voucher_line_id = vl.id "
        "WHERE vl.client_id = :c AND vl.ledger_id = :b AND v.status IN ('posted', 'reversed')"
    )
    params: dict = {"c": client_id, "b": ledger_id}
    if fy_id is not None:
        sql += " AND v.financial_year_id = :fy"
        params["fy"] = fy_id
    if ids is not None:
        sql += " AND vl.id = ANY(:ids)"
        params["ids"] = ids
    return conn.execute(text(sql + " ORDER BY v.voucher_date, v.voucher_number, vl.line_no"), params).all()


def _voucher_item(r) -> BookItem:
    deposit = r.debit > 0
    return BookItem(r.id, r.voucher_date, (r.debit if deposit else r.credit).quantize(CENTS),
                    DEPOSIT if deposit else PAYMENT, r.reference_no, r.narration or "", "voucher_line", r.voucher_number)


def _opening_rows(conn: Connection, client_id: object, ledger_id: object, *, fy_id: object | None = None,
                  ids: list | None = None):
    sql = (
        "SELECT o.id, o.kind, o.reference, o.item_date, o.amount, o.financial_year_id, m.match_id "
        "FROM bank_opening_items o LEFT JOIN recon_match_items m ON m.opening_item_id = o.id "
        "WHERE o.client_id = :c AND o.bank_ledger_id = :b"
    )
    params: dict = {"c": client_id, "b": ledger_id}
    if fy_id is not None:
        sql += " AND o.financial_year_id = :fy"
        params["fy"] = fy_id
    if ids is not None:
        sql += " AND o.id = ANY(:ids)"
        params["ids"] = ids
    return conn.execute(text(sql + " ORDER BY o.item_date, o.id"), params).all()


def _opening_item(r) -> BookItem:
    return BookItem(r.id, r.item_date, r.amount.quantize(CENTS), OPENING_KINDS[r.kind], r.reference, "", "opening_item", None)


def _book_items(conn: Connection, client_id: object, ledger_id: object, fy_id: object):
    """(items, match_id by item id) for the year: voucher lines of posted/reversed vouchers + opening items."""
    items, matched = [], {}
    for r in _voucher_rows(conn, client_id, ledger_id, fy_id=fy_id):
        items.append(_voucher_item(r))
        matched[r.id] = r.match_id
    for r in _opening_rows(conn, client_id, ledger_id, fy_id=fy_id):
        items.append(_opening_item(r))
        matched[r.id] = r.match_id
    return items, matched


# ==================================================================================================== unmatched


def unmatched(
    conn: Connection, client_id: object, bank_ledger_id: object, as_on: date,
    date_window_days: int = RECON_DATE_WINDOW_DAYS,
) -> Unmatched:
    """Bank lines and book items dated on or before as_on that are not matched yet, plus what auto-match would
    leave for the accountant (suggestions)."""
    _bank_ledger(conn, client_id, bank_ledger_id)
    year = _year_for(conn, client_id, as_on)
    bank = [_bank_line(r) for r in _bank_rows(conn, client_id, bank_ledger_id) if r.match_id is None and r.txn_date <= as_on]
    items, matched = _book_items(conn, client_id, bank_ledger_id, year.id)
    book = [x for x in items if matched[x.id] is None and x.date <= as_on]
    return Unmatched(bank, book, reconcile.auto_match(bank, book, date_window_days).suggestions)


# ====================================================================================================== matching


def _write_matches(conn: Connection, client_id: object, bank_ledger_id: object, method: str, actor: str,
                   matches: list[tuple[uuid.UUID, list, list, list, str | None]]) -> None:
    """matches = [(match_id, bank_line_ids, voucher_line_ids, opening_item_ids, note)] - one round trip per table."""
    if not matches:
        return
    conn.execute(
        text("INSERT INTO recon_matches (id, client_id, bank_ledger_id, method, note, created_by) "
             "VALUES (:id, :c, :b, :m, :n, :by)"),
        [{"id": mid, "c": client_id, "b": bank_ledger_id, "m": method, "n": note, "by": actor}
         for mid, _, _, _, note in matches],
    )
    rows = []
    for mid, banks, vlines, openings, _ in matches:
        rows += [{"id": uuid.uuid4(), "c": client_id, "m": mid, "bank": x, "vl": None, "op": None} for x in banks]
        rows += [{"id": uuid.uuid4(), "c": client_id, "m": mid, "bank": None, "vl": x, "op": None} for x in vlines]
        rows += [{"id": uuid.uuid4(), "c": client_id, "m": mid, "bank": None, "vl": None, "op": x} for x in openings]
    conn.execute(
        text("INSERT INTO recon_match_items (id, client_id, match_id, bank_line_id, voucher_line_id, opening_item_id) "
             "VALUES (:id, :c, :m, :bank, :vl, :op)"),
        rows,
    )
    audit.log_many(conn, [
        AuditEntry(client_id, actor, "match", "recon_match", mid, new={
            "method": method, "bank_ledger_id": str(bank_ledger_id), "note": note,
            "bank_line_ids": [str(x) for x in banks], "voucher_line_ids": [str(x) for x in vlines],
            "opening_item_ids": [str(x) for x in openings],
        })
        for mid, banks, vlines, openings, note in matches
    ])


def auto_match(
    conn: Connection, client_id: object, bank_ledger_id: object, as_on: date, *, actor: str,
    date_window_days: int = RECON_DATE_WINDOW_DAYS,
) -> AutoMatchSummary:
    """Run the deterministic rules on the unmatched items and save what they match (method 'auto')."""
    actor = require_actor(actor)
    if date_window_days < 0:
        raise ServiceError("invalid_window", "The date window cannot be negative.")
    found = unmatched(conn, client_id, bank_ledger_id, as_on, date_window_days)
    result = reconcile.auto_match(found.bank, found.book, date_window_days)
    kind = {x.id: x.kind for x in found.book}
    by_id = {x.id: x for x in found.book}
    bank_by_id = {x.id: x for x in found.bank}
    rows = []
    for g in result.groups:
        # the engine only proposes tying groups; this is the safety net required by R-04
        errors = reconcile.validate_match([bank_by_id[i] for i in g.bank_ids], [by_id[i] for i in g.book_ids])
        if errors:
            raise ServiceError("match_not_tied", errors[0].message)
        rows.append((
            uuid.uuid4(), list(g.bank_ids),
            [i for i in g.book_ids if kind[i] == "voucher_line"], [i for i in g.book_ids if kind[i] == "opening_item"],
            f"auto rule {g.rule}",
        ))
    _write_matches(conn, client_id, bank_ledger_id, "auto", actor, rows)
    return AutoMatchSummary(
        len(rows), sum(len(g.bank_ids) for g in result.groups), sum(len(g.book_ids) for g in result.groups),
        len(result.suggestions),
    )


def manual_match(
    conn: Connection, client_id: object, bank_ledger_id: object, bank_line_ids: list, voucher_line_ids: list,
    opening_item_ids: list, note: str | None = None, *, actor: str,
) -> uuid.UUID:
    """R-03: every item must be an unmatched posted voucher line of THIS bank ledger / unmatched bank line of this
    ledger / unmatched opening item. R-04: the match must tie exactly. Returns the match id."""
    actor = require_actor(actor)
    _bank_ledger(conn, client_id, bank_ledger_id)
    bank_ids, v_ids, o_ids = (list(dict.fromkeys(x)) for x in (bank_line_ids, voucher_line_ids, opening_item_ids))
    bank_rows = _bank_rows(conn, client_id, bank_ledger_id, bank_ids) if bank_ids else []
    v_rows = _voucher_rows(conn, client_id, bank_ledger_id, ids=v_ids) if v_ids else []
    o_rows = _opening_rows(conn, client_id, bank_ledger_id, ids=o_ids) if o_ids else []
    for label, wanted, rows in (("bank line", bank_ids, bank_rows), ("voucher line", v_ids, v_rows),
                                ("opening item", o_ids, o_rows)):
        if len(rows) != len(wanted):
            raise ServiceError(
                "match_invalid",
                f"R-03: a {label} in the selection is not a posted line of this bank ledger of this client.",
            )
        if any(r.match_id is not None for r in rows):
            raise ServiceError("match_invalid", f"R-03: a {label} in the selection is already matched.")
    if len({r.financial_year_id for r in v_rows} | {r.financial_year_id for r in o_rows}) > 1:
        raise ServiceError("match_invalid", "R-03: the voucher lines and opening items belong to different financial years.")
    errors = reconcile.validate_match(
        [_bank_line(r) for r in bank_rows], [_voucher_item(r) for r in v_rows] + [_opening_item(r) for r in o_rows]
    )
    if errors:
        code = "match_not_tied" if errors[0].rule_id == "R-04" else "match_invalid"
        raise ServiceError(code, f"{errors[0].rule_id}: {errors[0].message}")
    match_id = uuid.uuid4()
    _write_matches(conn, client_id, bank_ledger_id, "manual", actor,
                   [(match_id, bank_ids, v_ids, o_ids, (note or "").strip() or None)])
    return match_id


def unmatch(conn: Connection, client_id: object, match_id: object, *, actor: str) -> None:
    """Delete a match (its items become unmatched again). The audit log keeps what had been matched."""
    actor = require_actor(actor)
    head = conn.execute(
        text("SELECT bank_ledger_id, method, note, created_by FROM recon_matches WHERE id = :id AND client_id = :c FOR UPDATE"),
        {"id": match_id, "c": client_id},
    ).first()
    if head is None:
        raise ServiceError("not_found", "Match not found.")
    items = conn.execute(
        text("SELECT bank_line_id, voucher_line_id, opening_item_id FROM recon_match_items WHERE match_id = :id"),
        {"id": match_id},
    ).all()
    old = {
        "method": head.method, "note": head.note, "created_by": head.created_by, "bank_ledger_id": str(head.bank_ledger_id),
        "bank_line_ids": [str(r[0]) for r in items if r[0]], "voucher_line_ids": [str(r[1]) for r in items if r[1]],
        "opening_item_ids": [str(r[2]) for r in items if r[2]],
    }
    conn.execute(text("DELETE FROM recon_matches WHERE id = :id AND client_id = :c"), {"id": match_id, "c": client_id})
    audit.log(conn, AuditEntry(client_id, actor, "unmatch", "recon_match", match_id, old=old))


# ========================================================================================== bank opening items


def get_bank_opening_items(conn: Connection, client_id: object, fy_id: object, bank_ledger_id: object) -> list[dict]:
    _bank_ledger(conn, client_id, bank_ledger_id)
    rows = conn.execute(
        text("SELECT id, kind, reference, item_date, amount FROM bank_opening_items "
             "WHERE client_id = :c AND financial_year_id = :fy AND bank_ledger_id = :b ORDER BY item_date, id"),
        {"c": client_id, "fy": fy_id, "b": bank_ledger_id},
    )
    return [{"id": r.id, "kind": r.kind, "reference": r.reference, "item_date": r.item_date,
             "amount": r.amount.quantize(CENTS)} for r in rows]


def set_bank_opening_items(
    conn: Connection, client_id: object, fy_id: object, bank_ledger_id: object, items: list[dict], *, actor: str
) -> None:
    """Replace the cheques issued / deposited before the year began that were still outstanding at its start.
    Each item: kind (issued_not_presented | deposited_not_cleared), reference, item_date (before the year), amount."""
    actor = require_actor(actor)
    ledger = _bank_ledger(conn, client_id, bank_ledger_id)
    year = repo.get_financial_year(conn, client_id, fy_id)
    if year is None:
        raise ServiceError("not_found", "Financial year not found.")
    if not _is_bank_group(conn, client_id, ledger.group_code):
        raise ServiceError("invalid_ledger", "Opening items can only be set for a Bank Accounts ledger.")
    clean = []
    for n, item in enumerate(items, start=1):
        kind = item.get("kind")
        if kind not in OPENING_KINDS:
            raise ServiceError("invalid_item", f"Item {n}: kind must be issued_not_presented or deposited_not_cleared.")
        try:
            amount = parse_amount(item.get("amount"))
        except MoneyError as exc:
            raise ServiceError("invalid_item", f"Item {n}: {exc}.") from None
        if amount <= 0:
            raise ServiceError("invalid_item", f"Item {n}: the amount must be more than zero.")
        on = item.get("item_date")
        if not isinstance(on, date) or on >= year.start_date:
            raise ServiceError(
                "invalid_item", f"Item {n}: the date must be before the year begins ({_fmt(year.start_date)}).")
        reference = (item.get("reference") or "").strip() or None
        clean.append({"kind": kind, "reference": reference, "item_date": on, "amount": amount})
    old = get_bank_opening_items(conn, client_id, fy_id, bank_ledger_id)
    if conn.execute(
        text("SELECT 1 FROM recon_match_items m JOIN bank_opening_items o ON o.id = m.opening_item_id "
             "WHERE o.client_id = :c AND o.financial_year_id = :fy AND o.bank_ledger_id = :b LIMIT 1"),
        {"c": client_id, "fy": fy_id, "b": bank_ledger_id},
    ).first():
        raise ServiceError("opening_item_matched", "An opening item is already matched; un-match it before changing the list.")
    conn.execute(
        text("DELETE FROM bank_opening_items WHERE client_id = :c AND financial_year_id = :fy AND bank_ledger_id = :b"),
        {"c": client_id, "fy": fy_id, "b": bank_ledger_id},
    )
    if clean:
        conn.execute(
            text("INSERT INTO bank_opening_items (client_id, financial_year_id, bank_ledger_id, kind, reference, item_date, amount) "
                 "VALUES (:c, :fy, :b, :kind, :reference, :item_date, :amount)"),
            [{**x, "c": client_id, "fy": fy_id, "b": bank_ledger_id} for x in clean],
        )
    audit.log(conn, AuditEntry(
        client_id, actor, "set", "bank_opening_items", bank_ledger_id,
        old={"financial_year_id": str(fy_id), "items": old},
        new={"financial_year_id": str(fy_id), "items": clean},
    ))


def _is_bank_group(conn: Connection, client_id: object, group_code: str) -> bool:
    groups = repo.groups_for_client(conn, client_id)
    code: str | None = group_code
    while code is not None:
        if code == "bank_accounts":
            return True
        code = groups[code].parent_code if code in groups else None
    return False


# ============================================================================================================ BRS


def brs(conn: Connection, client_id: object, bank_ledger_id: object, as_on: date) -> brs_engine.BrsResult:
    """Bank Reconciliation Statement as on a date. Balance as per bank = the statement covering as_on: its opening
    balance + the movement of its lines up to as_on. No such statement -> ServiceError no_statement."""
    _bank_ledger(conn, client_id, bank_ledger_id)
    year = _year_for(conn, client_id, as_on)
    statement = conn.execute(
        text("SELECT id, opening_balance FROM bank_statements WHERE client_id = :c AND bank_ledger_id = :b "
             "AND period_from <= :d AND period_to >= :d ORDER BY period_from LIMIT 1"),
        {"c": client_id, "b": bank_ledger_id, "d": as_on},
    ).first()
    if statement is None:
        raise ServiceError(
            "no_statement", f"No bank statement of this bank ledger covers {_fmt(as_on)}. Import the statement first.")
    rows = _bank_rows(conn, client_id, bank_ledger_id)
    lines = [_bank_line(r) for r in rows]
    of_statement = [_bank_line(r) for r in rows if r.statement_id == statement.id]
    items, _ = _book_items(conn, client_id, bank_ledger_id, year.id)
    opening = repo.openings_for_year(conn, client_id, year.id).get(bank_ledger_id)
    opening_signed = (opening.debit - opening.credit) if opening else Decimal("0.00")

    grouped: dict[object, tuple[list, list]] = {}
    for r in rows:
        if r.match_id is not None:
            grouped.setdefault(r.match_id, ([], []))[0].append(r.id)
    for item_id, match_id in [(r.id, r.match_id) for r in _voucher_rows(conn, client_id, bank_ledger_id, fy_id=year.id)] + [
        (r.id, r.match_id) for r in _opening_rows(conn, client_id, bank_ledger_id, fy_id=year.id)
    ]:
        if match_id is not None:
            grouped.setdefault(match_id, ([], []))[1].append(item_id)
    matches = [brs_engine.Match(tuple(b), tuple(k)) for b, k in grouped.values()]
    return brs_engine.brs(
        as_on,
        brs_engine.balance_per_books(opening_signed, items, as_on),
        items, lines, matches,
        brs_engine.balance_per_bank(statement.opening_balance.quantize(CENTS), of_statement, as_on),
    )


# ============================================================================================== bank-only lines

_CHARGE_WORDS = re.compile(r"\b(CHARGES?|CHRGS?|CHRG|SMS|FEES?)\b", re.IGNORECASE)
_INTEREST_WORDS = re.compile(r"(INT\.?\s?PD|INTEREST\s+CREDIT)", re.IGNORECASE)


@dataclass(frozen=True)
class BankOnlySuggestion:
    bank_line_id: object
    txn_date: date
    description: str
    amount: Decimal
    direction: str
    counter_ledger_id: object | None
    counter_ledger_name: str | None
    reason: str


def _open_bank_only_lines(conn: Connection, client_id: object, bank_ledger_id: object, as_on: date) -> list[BankLine]:
    drafted = {r[0] for r in conn.execute(
        text("SELECT bank_line_id FROM bank_line_drafts WHERE client_id = :c"), {"c": client_id})}
    return [_bank_line(r) for r in _bank_rows(conn, client_id, bank_ledger_id)
            if r.match_id is None and r.txn_date <= as_on and r.id not in drafted]


def _ledger_named_like(conn: Connection, client_id: object, fragment: str) -> list:
    return conn.execute(
        text("SELECT id, name FROM ledgers WHERE client_id = :c AND is_active AND lower(name) LIKE :p ORDER BY name"),
        {"c": client_id, "p": f"%{fragment.lower()}%"},
    ).all()


def bank_only_suggestions(conn: Connection, client_id: object, bank_ledger_id: object, as_on: date) -> list[BankOnlySuggestion]:
    """Counter-ledger suggestions for unmatched, not yet drafted bank lines, from keywords in the description:
    CHARGES/CHRG/SMS/FEE on a withdrawal -> a ledger named like 'Bank Charges'; INT.PD/INTEREST CREDIT on a
    deposit -> 'Bank Interest'. Only suggestions: the accountant picks the ledger."""
    _bank_ledger(conn, client_id, bank_ledger_id)
    lines = _open_bank_only_lines(conn, client_id, bank_ledger_id, as_on)
    wanted = {"Bank Charges": [x for x in lines if x.direction == PAYMENT and _CHARGE_WORDS.search(x.description)],
              "Bank Interest": [x for x in lines if x.direction == DEPOSIT and _INTEREST_WORDS.search(x.description)]}
    out = []
    for name, hits in wanted.items():
        if not hits:
            continue
        ledgers = _ledger_named_like(conn, client_id, name)
        for x in hits:
            if len(ledgers) == 1:
                out.append(BankOnlySuggestion(x.id, x.date, x.description, x.amount, x.direction, ledgers[0].id,
                                              ledgers[0].name, f"The description looks like {name.lower()}."))
            else:
                why = "no ledger" if not ledgers else "several ledgers"
                out.append(BankOnlySuggestion(x.id, x.date, x.description, x.amount, x.direction, None, None,
                                              f"The description looks like {name.lower()} but there is {why} named like '{name}'."))
    return sorted(out, key=lambda s: (s.txn_date, str(s.bank_line_id)))


def draft_vouchers_for_bank_only(
    conn: Connection, client_id: object, bank_ledger_id: object, items: list[tuple[object, object]], *, actor: str
) -> DraftsResult:
    """For each (bank_line_id, counter_ledger_id) create a DRAFT voucher: a bank withdrawal becomes a Payment
    (Dr counter ledger / Cr bank), a bank deposit a Receipt (Dr bank / Cr counter ledger). Narration = the statement
    description, reference no = the bank reference, date = the transaction date. Never approved or posted.
    A line that is already matched or already drafted is refused (ServiceError, nothing created). Rule errors are
    returned per item; when any item has errors NOTHING is created."""
    actor = require_actor(actor)
    ledger = _bank_ledger(conn, client_id, bank_ledger_id)
    ids = [i for i, _ in items]
    if len(set(ids)) != len(ids):
        raise ServiceError("match_invalid", "The same bank line is listed more than once.")
    rows = {r.id: r for r in _bank_rows(conn, client_id, bank_ledger_id, ids)} if ids else {}
    drafted = {r[0] for r in conn.execute(
        text("SELECT bank_line_id FROM bank_line_drafts WHERE bank_line_id = ANY(:ids)"), {"ids": ids})} if ids else set()
    for bank_line_id, _ in items:
        row = rows.get(bank_line_id)
        if row is None:
            raise ServiceError("match_invalid", "A bank line is not a line of this bank ledger of this client.")
        if row.match_id is not None:
            raise ServiceError("match_invalid", f"The bank line of {_fmt(row.txn_date)} is already matched.")
        if bank_line_id in drafted:
            raise ServiceError("already_drafted", f"A draft voucher was already created for the bank line of {_fmt(row.txn_date)}.")

    drafts = []
    for bank_line_id, counter_id in items:
        line = _bank_line(rows[bank_line_id])
        amount = f"{line.amount:.2f}"
        if line.direction == PAYMENT:
            vtype, lines = "payment", (VoucherLine(counter_id, amount, None), VoucherLine(ledger.id, None, amount))
        else:
            vtype, lines = "receipt", (VoucherLine(ledger.id, amount, None), VoucherLine(counter_id, None, amount))
        drafts.append((bank_line_id, VoucherDraft(
            client_id, vtype, line.date, (line.description or "").strip() or None, line.reference, None, lines)))

    errors = [(i, errs) for i, d in drafts if (errs := vouchers.validate_draft(conn, d))]
    if errors:
        return DraftsResult([], errors)
    created = []
    for bank_line_id, d in drafts:
        result = vouchers.create_draft(conn, d, actor=actor)
        if result.errors:  # e.g. two identical lines in one request: refuse everything (the caller rolls back)
            raise ServiceError("draft_failed", "; ".join(e.message for e in result.errors))
        created.append((bank_line_id, result.voucher_id))
    conn.execute(
        text("INSERT INTO bank_line_drafts (bank_line_id, client_id, voucher_id, created_by) VALUES (:l, :c, :v, :by)"),
        [{"l": b, "c": client_id, "v": v, "by": actor} for b, v in created],
    )
    audit.log_many(conn, [
        AuditEntry(client_id, actor, "draft_from_bank_line", "bank_statement_line", b, new={"voucher_id": str(v)})
        for b, v in created
    ])
    return DraftsResult(created, [])
