"""TDS / TCS challans, allocation, matching, interest and due calendar (Phase 4, package C).

Every rule and every date / interest calculation is in `engine/tds_challan.py`; this file loads data, writes the result and logs it.
Services take a Connection and never commit; checks run before the first write. Interest is SHOWN, never posted.

Hook (called by `services/tds_hooks.on_reverse` of package B, imported lazily):
  on_reverse_check(conn, client_id, voucher_id)   refuses the reversal of a voucher whose deduction items have challan allocations (T-25)
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_tds_challans as repo
from app.engine import tds_challan as engine
from app.engine.models import ValidationError
from app.engine.money import MoneyError, format_inr, parse_amount
from app.services import audit, queries
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor

ZERO = Decimal("0.00")
TWO = Decimal("0.01")
AMOUNT_KEYS = ("tax_amount", "interest_amount", "fee_amount", "other_amount")


def _d(value: object) -> Decimal:
    return Decimal(str(value)).quantize(TWO)


def _fmt(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _fy(conn: Connection, client_id: object, fy_id: object) -> dict[str, Any]:
    fy = repo.financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("not_found", "Financial year not found.")
    return fy


def _facts(row: dict[str, Any]) -> engine.ItemFacts:
    return engine.ItemFacts(
        str(row["item_id"]), row["kind"], row["deductee_name"], row["section_ref"], _d(row["tds_amount"]), str(row["financial_year_id"]),
        row["event_date"], row["voucher_date"], row["voucher_status"], row["voucher_number"],
    )


def _snapshot(c: dict[str, Any]) -> dict[str, Any]:
    keys = ("kind", "financial_year_id", "quarter", "bsr_code", "deposit_date", "challan_serial_no", "tax_amount", "interest_amount",
            "fee_amount", "other_amount", "total_amount", "payment_voucher_id", "note", "status")
    return {k: c[k] for k in keys}


# ================================================================================================ challan fields and allocation checks


def _parse_challan(data: dict[str, Any], kind: str) -> tuple[engine.ChallanIn, dict[str, Decimal], list[ValidationError]]:
    amounts, errors = engine.parse_challan_amounts({k: data.get(k) for k in AMOUNT_KEYS})
    c = engine.ChallanIn(
        kind=kind, quarter=int(data["quarter"]), bsr_code=str(data.get("bsr_code") or "").strip(), deposit_date=data.get("deposit_date"),
        challan_serial_no=str(data.get("challan_serial_no") or "").strip(), tax_amount=amounts["tax_amount"],
        interest_amount=amounts["interest_amount"], fee_amount=amounts["fee_amount"], other_amount=amounts["other_amount"],
    )
    found = engine.validate_challan(c)
    if errors:  # an amount that could not be read counts as 0: do not add a second, misleading "total" error
        found = [e for e in found if not e.message.startswith("Challan total")]
    return c, amounts, errors + found


def _parse_allocations(raw: list[dict[str, Any]] | None) -> tuple[list[tuple[uuid.UUID, Decimal]], list[ValidationError]]:
    out: list[tuple[uuid.UUID, Decimal]] = []
    errors: list[ValidationError] = []
    for no, a in enumerate(raw or [], start=1):
        try:
            out.append((uuid.UUID(str(a["item_id"])), parse_amount(a["amount"])))
        except MoneyError as exc:
            errors.append(ValidationError("T-24", f"Allocation {no}: {exc}.", no))
        except (ValueError, KeyError):
            errors.append(ValidationError("T-21", "A deduction in the allocation was not found for this client.", no))
    return out, errors


def _check_allocations(
    conn: Connection, client_id: object, facts: engine.ChallanFacts, allocations: list[tuple[uuid.UUID, Decimal]], except_challan: object | None
) -> list[ValidationError]:
    ids = [i for i, _ in allocations]
    items = {str(r["item_id"]): _facts(r) for r in repo.items_by_ids(conn, client_id, ids, lock=True)}
    elsewhere = repo.allocated_on_other_challans(conn, client_id, ids, except_challan)
    return engine.validate_allocations(facts, [(str(i), a) for i, a in allocations], items, elsewhere)


def _require_payment_voucher(conn: Connection, client_id: object, voucher_id: object | None) -> None:
    if voucher_id is not None and repo.voucher_of_client(conn, client_id, voucher_id) is None:
        raise ServiceError("not_found", "The payment voucher of the challan was not found for this client.")


def create_challan(conn: Connection, client_id: object, data: dict[str, Any], *, actor: str) -> uuid.UUID:
    """data: kind, financial_year_id, quarter, bsr_code, deposit_date, challan_serial_no, tax_amount, interest_amount, fee_amount,
    other_amount, payment_voucher_id, note, allocations [{item_id, amount}]."""
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    _fy(conn, client_id, data["financial_year_id"])
    c, amounts, errors = _parse_challan(data, data["kind"])
    allocations, alloc_errors = _parse_allocations(data.get("allocations"))
    errors += alloc_errors
    if errors:
        raise VoucherRuleError(errors)
    _require_payment_voucher(conn, client_id, data.get("payment_voucher_id"))
    if repo.challan_by_cin(conn, client_id, c.bsr_code, c.deposit_date, c.challan_serial_no):
        raise ServiceError("challan_exists", f"A challan with BSR {c.bsr_code}, date {_fmt(c.deposit_date)} and serial {c.challan_serial_no} already exists.")
    facts = engine.ChallanFacts(None, c.kind, str(data["financial_year_id"]), c.quarter, c.deposit_date, c.tax_amount)
    errors = _check_allocations(conn, client_id, facts, allocations, None)
    if errors:
        raise VoucherRuleError(errors)
    values = {
        "client_id": client_id, "kind": c.kind, "financial_year_id": data["financial_year_id"], "quarter": c.quarter, "bsr_code": c.bsr_code,
        "deposit_date": c.deposit_date, "challan_serial_no": c.challan_serial_no, **amounts, "total_amount": c.total,
        "payment_voucher_id": data.get("payment_voucher_id"), "note": data.get("note"), "created_by": actor,
    }
    challan_id = repo.insert_challan(conn, values)
    repo.insert_allocations(conn, client_id, challan_id, allocations, actor)
    audit.log(conn, AuditEntry(client_id, actor, "create", "tds_challan", challan_id, None, {
        **_snapshot({**values, "status": "entered"}), "allocations": [{"item_id": str(i), "amount": a} for i, a in allocations]}))
    return challan_id


def update_challan(conn: Connection, client_id: object, challan_id: object, data: dict[str, Any], *, actor: str) -> dict[str, Any]:
    """Replace the fields of an entered challan (kind and allocations are not changed here). A locked challan is refused."""
    actor = require_actor(actor)
    old = repo.get_challan(conn, client_id, challan_id, lock=True)
    if old is None:
        raise ServiceError("not_found", "Challan not found.")
    if old["status"] == "locked":
        raise ServiceError("challan_locked", "This challan is locked by a final return working and cannot be changed.")
    _fy(conn, client_id, data["financial_year_id"])
    c, amounts, errors = _parse_challan(data, old["kind"])
    if errors:
        raise VoucherRuleError(errors)
    _require_payment_voucher(conn, client_id, data.get("payment_voucher_id"))
    other = repo.challan_by_cin(conn, client_id, c.bsr_code, c.deposit_date, c.challan_serial_no)
    if other and other["id"] != old["id"]:
        raise ServiceError("challan_exists", f"A challan with BSR {c.bsr_code}, date {_fmt(c.deposit_date)} and serial {c.challan_serial_no} already exists.")
    existing = [(a["item_id"], _d(a["amount"])) for a in repo.allocations_of_challan(conn, challan_id)]
    facts = engine.ChallanFacts(str(challan_id), c.kind, str(data["financial_year_id"]), c.quarter, c.deposit_date, c.tax_amount)
    errors = _check_allocations(conn, client_id, facts, existing, challan_id)
    if errors:
        raise VoucherRuleError(errors)
    values = {
        "financial_year_id": data["financial_year_id"], "quarter": c.quarter, "bsr_code": c.bsr_code, "deposit_date": c.deposit_date,
        "challan_serial_no": c.challan_serial_no, **amounts, "total_amount": c.total, "payment_voucher_id": data.get("payment_voucher_id"),
        "note": data.get("note"),
    }
    repo.update_challan(conn, challan_id, values)
    new = repo.get_challan(conn, client_id, challan_id)
    audit.log(conn, AuditEntry(client_id, actor, "update", "tds_challan", challan_id, _snapshot(old), _snapshot(new)))
    return get_challan(conn, client_id, challan_id)


def replace_allocations(conn: Connection, client_id: object, challan_id: object, raw: list[dict[str, Any]], *, actor: str) -> dict[str, Any]:
    actor = require_actor(actor)
    challan = repo.get_challan(conn, client_id, challan_id, lock=True)
    if challan is None:
        raise ServiceError("not_found", "Challan not found.")
    if challan["status"] == "locked":
        raise ServiceError("challan_locked", "This challan is locked by a final return working; its allocations cannot be changed.")
    allocations, errors = _parse_allocations(raw)
    if errors:
        raise VoucherRuleError(errors)
    facts = engine.ChallanFacts(
        str(challan_id), challan["kind"], str(challan["financial_year_id"]), challan["quarter"], challan["deposit_date"], _d(challan["tax_amount"]))
    errors = _check_allocations(conn, client_id, facts, allocations, challan_id)
    if errors:
        raise VoucherRuleError(errors)
    old = [{"item_id": str(a["item_id"]), "amount": _d(a["amount"])} for a in repo.allocations_of_challan(conn, challan_id)]
    repo.delete_allocations(conn, challan_id)
    repo.insert_allocations(conn, client_id, challan_id, allocations, actor)
    audit.log(conn, AuditEntry(client_id, actor, "allocate", "tds_challan", challan_id, {"allocations": old},
                               {"allocations": [{"item_id": str(i), "amount": a} for i, a in allocations]}))
    return get_challan(conn, client_id, challan_id)


# ================================================================================================ reads


def _challan_view(row: dict[str, Any]) -> dict[str, Any]:
    allocated = _d(row["allocated"])
    out = {k: row[k] for k in ("id", "kind", "financial_year_id", "quarter", "bsr_code", "deposit_date", "challan_serial_no", "payment_voucher_id", "note")}
    out.update({k: _d(row[k]) for k in (*AMOUNT_KEYS, "total_amount")})
    out.update({"allocated": allocated, "unallocated": _d(row["tax_amount"]) - allocated, "status": row["status"]})
    return out


def list_challans(conn: Connection, client_id: object, fy_id: object | None = None, quarter: int | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    queries.require_client(conn, client_id)
    return [_challan_view(r) for r in repo.list_challans(conn, client_id, fy_id, quarter, kind)]


def get_challan(conn: Connection, client_id: object, challan_id: object) -> dict[str, Any]:
    row = repo.get_challan(conn, client_id, challan_id)
    if row is None:
        raise ServiceError("not_found", "Challan not found.")
    out = _challan_view(row)
    allocations = repo.allocations_of_challan(conn, challan_id)
    items = {str(r["item_id"]): r for r in repo.items_by_ids(conn, client_id, [a["item_id"] for a in allocations])}
    out["allocations"] = [
        {"item_id": a["item_id"], "amount": _d(a["amount"]), "deductee_name": items[str(a["item_id"])]["deductee_name"],
         "section_ref": items[str(a["item_id"])]["section_ref"], "event_date": items[str(a["item_id"])]["event_date"]}
        for a in sorted(allocations, key=lambda a: (items[str(a["item_id"])]["event_date"], str(a["item_id"])))
    ]
    return out


# ================================================================================================ matching, interest, calendar


class _Year:
    """The data every year-level view needs, loaded once: items, deposits per item, rule rows and which of them were used."""

    def __init__(self, conn: Connection, client_id: object, fy_id: object, kind: str | None):
        queries.require_client(conn, client_id)
        self.fy = _fy(conn, client_id, fy_id)
        self.fy_id = fy_id
        self.items = repo.items_for_year(conn, client_id, fy_id, kind)
        self.deposits: dict[str, list[tuple[date, Decimal]]] = {}
        self.alloc_total: dict[str, Decimal] = {}
        for a in repo.allocations_for_year(conn, client_id, fy_id):
            self.deposits.setdefault(str(a["item_id"]), []).append((a["deposit_date"], _d(a["amount"])))
        self.due_rules, self.due_sources = repo.due_date_rules(conn)
        self.interest_rules, self.interest_sources = repo.interest_rules(conn)
        self.used: list[tuple[str, str, str]] = []

    def due_date(self, item: dict[str, Any]) -> date:
        due, rule = engine.deposit_due_date(item["event_date"], item["kind"], self.due_rules)
        self.used.append(("due_date", rule.verification_status, self.due_sources[(rule.due_key, rule.kind, rule.effective_from)]))
        return due

    def interest(self, item: dict[str, Any], due: date, as_on: date) -> engine.ItemInterest:
        r = engine.item_interest(
            _d(item["tds_amount"]), item["event_date"], item["voucher_date"], self.deposits.get(str(item["item_id"]), []), due, as_on, self.interest_rules)
        for rule in r.rules_used:
            self.used.append(("interest", rule.verification_status, self.interest_sources[(rule.interest_key, rule.effective_from)]))
        return r

    def status(self) -> dict:
        return engine.rule_status(self.used)


def _guard(fn, *args, **kwargs):
    """Engine rule errors (T-02: no rule in force) become a 422 rule-error answer."""
    try:
        return fn(*args, **kwargs)
    except engine.ChallanRuleError as exc:
        raise VoucherRuleError(exc.errors) from None


def matching(conn: Connection, client_id: object, fy_id: object, quarter: int | None, kind: str | None, as_on: date | None = None) -> dict[str, Any]:
    as_on = as_on or date.today()
    y = _Year(conn, client_id, fy_id, kind)
    rows = []
    totals = {"tds_amount": ZERO, "allocated": ZERO, "balance": ZERO, "interest_late_deposit": ZERO}
    for item in y.items:
        if quarter is not None and engine.quarter_of(item["event_date"]) != quarter:
            continue
        due = _guard(y.due_date, item)
        st = engine.item_status(_d(item["tds_amount"]), y.deposits.get(str(item["item_id"]), []), due, as_on)
        interest = _guard(y.interest, item, due, as_on)
        rows.append({
            "item_id": item["item_id"], "voucher_id": item["voucher_id"], "voucher_number": item["voucher_number"], "kind": item["kind"],
            "deductee_name": item["deductee_name"], "section_ref": item["section_ref"], "event_date": item["event_date"],
            "tds_amount": _d(item["tds_amount"]), "allocated": st.allocated, "balance": st.balance, "due_date": due,
            "deposited_on": st.deposited_on, "days_late": st.days_late, "interest_late_deposit": interest.interest_late_deposit,
        })
        totals["tds_amount"] += _d(item["tds_amount"])
        totals["allocated"] += st.allocated
        totals["balance"] += st.balance
        totals["interest_late_deposit"] += interest.interest_late_deposit
    challans = [
        c for c in repo.list_challans(conn, client_id, fy_id, quarter, kind) if _d(c["tax_amount"]) - _d(c["allocated"]) > 0
    ]
    unallocated = [
        {"id": c["id"], "kind": c["kind"], "quarter": c["quarter"], "bsr_code": c["bsr_code"], "deposit_date": c["deposit_date"],
         "challan_serial_no": c["challan_serial_no"], "tax_amount": _d(c["tax_amount"]), "allocated": _d(c["allocated"]),
         "unallocated": _d(c["tax_amount"]) - _d(c["allocated"])}
        for c in challans
    ]
    return {"rows": rows, "unallocated_challans": unallocated, "totals": totals, "rule_status": y.status()}


def propose(conn: Connection, client_id: object, fy_id: object, quarter: int | None, kind: str | None) -> dict[str, Any]:
    """Proposal only (nothing is written): the accountant confirms with PUT allocations."""
    y = _Year(conn, client_id, fy_id, kind)
    open_items = []
    for item in y.items:
        if quarter is not None and engine.quarter_of(item["event_date"]) != quarter:
            continue
        done = sum((a for _, a in y.deposits.get(str(item["item_id"]), [])), ZERO)
        balance = _d(item["tds_amount"]) - done
        if balance > 0:
            open_items.append(engine.OpenItem(str(item["item_id"]), item["kind"], str(fy_id), item["event_date"], item["voucher_date"], balance))
    open_challans = []
    for c in repo.list_challans(conn, client_id, fy_id, quarter, kind):
        left = _d(c["tax_amount"]) - _d(c["allocated"])
        if left > 0 and c["status"] == "entered":
            open_challans.append(engine.OpenChallan(str(c["id"]), c["kind"], str(fy_id), c["quarter"], c["deposit_date"], c["challan_serial_no"], left))
    return {"proposed": [{"item_id": i, "challan_id": c, "amount": a} for i, c, a in engine.propose_allocations(open_items, open_challans)]}


def interest(conn: Connection, client_id: object, fy_id: object, as_on: date | None = None, kind: str | None = None) -> dict[str, Any]:
    as_on = as_on or date.today()
    y = _Year(conn, client_id, fy_id, kind)
    rows = []
    totals = {"tds_amount": ZERO, "interest_late_deduction": ZERO, "interest_late_deposit": ZERO, "interest_total": ZERO}
    for item in y.items:
        due = _guard(y.due_date, item)
        r = _guard(y.interest, item, due, as_on)
        rows.append({
            "item_id": item["item_id"], "kind": item["kind"], "deductee_name": item["deductee_name"], "section_ref": item["section_ref"],
            "tds_amount": _d(item["tds_amount"]), "deductible_on": r.deductible_on, "deducted_on": r.deducted_on,
            "months_late_deduction": r.months_late_deduction, "interest_late_deduction": r.interest_late_deduction,
            "deposited_on": r.deposited_on, "due_date": r.due_date, "months_late_deposit": r.months_late_deposit,
            "interest_late_deposit": r.interest_late_deposit,
        })
        totals["tds_amount"] += _d(item["tds_amount"])
        totals["interest_late_deduction"] += r.interest_late_deduction
        totals["interest_late_deposit"] += r.interest_late_deposit
        totals["interest_total"] += r.interest_late_deduction + r.interest_late_deposit
    status = y.status()
    for row in rows:
        row["rule_status"] = status["worst"]
    return {"as_on": as_on, "rows": rows, "totals": totals, "rule_status": status}


def due_calendar(conn: Connection, client_id: object, fy_id: object, as_on: date | None = None) -> dict[str, Any]:
    as_on = as_on or date.today()
    y = _Year(conn, client_id, fy_id, None)
    start_year = y.fy["start_date"].year
    deducted: dict[tuple[str, int, int], Decimal] = {}
    deposited: dict[tuple[str, int, int], Decimal] = {}
    for item in y.items:
        key = (item["kind"], item["event_date"].year, item["event_date"].month)
        deducted[key] = deducted.get(key, ZERO) + _d(item["tds_amount"])
        deposited[key] = deposited.get(key, ZERO) + sum((a for _, a in y.deposits.get(str(item["item_id"]), [])), ZERO)
    tax_by_month = {k: (v, deposited.get(k, ZERO)) for k, v in deducted.items()}
    kinds = ["tds"] + (["tcs"] if any(k[0] == "tcs" for k in deducted) else [])
    rows = _guard(
        engine.due_calendar, start_year, kinds, y.due_rules, tax_by_month, repo.returns_filed(conn, client_id, fy_id),
        repo.certificates_issued(conn, client_id, fy_id), as_on)
    used = [("due_date", r.verification_status, y.due_sources[(r.due_key, r.kind, r.effective_from)]) for row in rows for r in row.rules_used]
    return {
        "as_on": as_on,
        "rows": [{"event": r.event, "kind": r.kind, "quarter": r.quarter, "period": r.period, "due_date": r.due_date, "status": r.status,
                  "amount_due": r.amount_due} for r in rows],
        "rule_status": engine.rule_status(used),
    }


# ================================================================================================ hook for services/tds_hooks.on_reverse


def on_reverse_check(conn: Connection, client_id: object, voucher_id: object) -> None:
    """T-25: a voucher whose deduction items are paid by a challan cannot be reversed; remove the allocation first."""
    blocking = repo.allocation_on_voucher(conn, client_id, voucher_id)
    if blocking:
        first = blocking[0]
        raise ServiceError(
            "item_has_allocation",
            f"This voucher cannot be reversed: its tax is allocated to challan BSR {first['bsr_code']} serial {first['challan_serial_no']} "
            f"dated {_fmt(first['deposit_date'])} ({format_inr(_d(first['amount']))}). Remove the allocation first.",
            {"rule_id": "T-25", "challans": [str(b["challan_id"]) for b in blocking]},
        )
