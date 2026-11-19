"""Year-end close and reopen (Phase 6 package F: F-60..F-67). docs/PHASE6_API_CONTRACT.md.

`check` (no write) and `close` share ONE plan: the statements, the closing stock, the depreciation run, the IT working, the partners and
the books are read; the pure engine `engine/final_close.py` builds the three closing Journal vouchers and the carry-forward. No amount is
computed here. `close` creates, approves and posts the vouchers through the voucher service inside one savepoint, then locks the periods,
stores the final snapshots, finalises the IT working, writes the close record and carries the openings forward: any failure leaves
nothing behind. `reopen` undoes the closing vouchers by reversal (never by deletion), only while the next year has no posted voucher, and
removes only the next year's carried openings, only if they are still exactly what the close wrote (the owner's decision of 2026-11-19).
Services never commit.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_final_assets as fr
from app.db import repositories_final_close as cr
from app.db import repositories_final_statements as frepo
from app.engine import final_close as engine
from app.engine.final_types import ENGINE_VERSION, ClosingStockIn, EntityType
from app.engine.models import VoucherDraft, VoucherLine
from app.services import (
    audit,
    bills,
    final_assets,
    final_hooks,
    final_sch3,
    final_statements,
    inventory_reports,
    periods,
    vouchers,
)
from app.services.audit import AuditEntry
from app.services.client_setup import _month_periods
from app.services.errors import ServiceError, VoucherRuleError, require_actor

ZERO = Decimal("0.00")


def _m(value: Decimal) -> str:
    return f"{value:.2f}"


def _label(start: date) -> str:
    return f"{start.year}-{(start.year + 1) % 100:02d}"


def _item(rule: str, ok: bool, message: str, details: Any = None) -> dict:
    return {"rule_id": rule, "ok": ok, "message": message, "details": details}


@dataclass
class Plan:
    fy: repo.FinancialYearRow
    entity: str
    items: list[dict]
    close: engine.ClosePlan | None
    statements: dict[str, dict]
    names: dict[Any, str]
    next_year: tuple[Any, date, date] | None
    carried_bills: list
    carried_stock: list
    it_acknowledged: list[str]
    it_to_finalise: bool
    closed: dict | None

    @property
    def ready(self) -> bool:
        return all(x["ok"] for x in self.items)


def _year(conn: Connection, client_id: object, fy_id: object) -> repo.FinancialYearRow:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    fy = repo.get_financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return fy


def _statements(conn: Connection, client_id: object, fy_id: object, entity: str, items: list[dict]) -> dict[str, dict]:
    """The statements of the year (they exclude the closing vouchers, so they are the same before and after the close). Their error findings
    (F-40 books balance, F-41 closing stock, F-44 / F-44b) block the close."""
    out: dict[str, dict] = {}
    try:
        if entity == EntityType.COMPANY.value:
            for key, fn in (("profit_loss", final_sch3.profit_loss), ("balance_sheet", final_sch3.balance_sheet)):
                try:
                    out[key] = fn(conn, client_id, fy_id)
                except final_sch3.UnclassifiedError as exc:
                    out[key] = exc.statement
                    items.append(_item("F-44", False, exc.error.message, exc.error.details))
        else:
            out["trading"] = final_statements.trading(conn, client_id, fy_id)
            out["profit_loss"] = final_statements.profit_loss(conn, client_id, fy_id)
            out["balance_sheet"] = final_statements.balance_sheet(conn, client_id, fy_id)
    except ServiceError as exc:
        items.append(_item("F-60", False, exc.message))
        return out
    seen: set[str] = set()
    for body in out.values():
        for f in body["findings"]:
            if f["severity"] == "error" and f["message"] not in seen:
                seen.add(f["message"])
                items.append(_item(f["rule_id"], False, f["message"], {"ledger_id": f.get("ledger_id")}))
    if not seen and not any(not x["ok"] for x in items if x["rule_id"] == "F-44"):
        items.append(_item("F-40", True, "Trial Balance and opening balances agree; closing stock is approved; the Balance Sheet balances."))
    return out


def _it_state(conn: Connection, client_id: object, fy: repo.FinancialYearRow, ack: list[str], items: list[dict]) -> bool:
    """F-34 / F-60: the income-tax working must be final (or finalisable now). Returns True when the close has to finalise it."""
    try:
        w = final_assets.it_working(conn, client_id, fy.id)
    except ServiceError as exc:
        items.append(_item("F-60", False, f"The income-tax depreciation working cannot be computed: {exc.message}"))
        return False
    if w["status"] == "final":
        items.append(_item("F-34", True, "The income-tax depreciation working is final."))
        return False
    if not w["blocks"]:
        items.append(_item("F-34", True, "No income-tax depreciation block to finalise."))
        return False
    errors = [f for f in w["findings"] if f["severity"] == "error"]
    if errors:
        items.append(_item("F-34", False, "The income-tax working has errors: " + "; ".join(f["message"] for f in errors)))
        return False
    pending = sorted(b["block_key"] for b in w["blocks"] if b["flags"] and b["block_key"] not in ack)
    if pending:
        items.append(_item("F-33", False, f"These income-tax blocks carry a flag that needs the CA's acknowledgement: {', '.join(pending)}.",
                           {"blocks": pending}))
        return False
    items.append(_item("F-34", True, "The income-tax depreciation working will be finalised with the close."))
    return True


def _carried_balance(plan: engine.ClosePlan) -> dict[Any, Decimal]:
    return {lid: d - c for lid, d, c in plan.carry.ledger_openings} if plan.carry else {}


def _bills_and_stock(conn: Connection, client_id: object, fy: repo.FinancialYearRow, plan: engine.ClosePlan, stock: frepo.ClosingStockRow | None,
                     items: list[dict]) -> tuple[list, list]:
    carried_bills: list = []
    carried_stock: list = []
    if plan.carry is None:
        return carried_bills, carried_stock
    parties = {pid: info.name for pid, info in bills._bill_wise_parties(conn, client_id).items()}
    if parties:
        open_items = [engine.OpenItem(b.party_ledger_id, b.party_name, b.bill_ref, b.bill_date, b.due_date, b.outstanding)
                      for b in bills.open_bills(conn, client_id, fy.end_date)]
        carried_bills, found = engine.carry_open_bills(open_items, parties, _carried_balance(plan))
        for f in found:
            items.append(_item("F-66", False, f.message, {"ledger_id": str(f.ledger_id)}))
        if not found:
            items.append(_item("F-66", True, f"{len(carried_bills)} open bill(s) carry forward and tie to the party balances."))
    if stock is not None and stock.source == "inventory_report":
        try:
            report = inventory_reports.closing_stock(conn, client_id, fy.id)
            register = inventory_reports.stock_register(conn, client_id, fy.id)
        except ServiceError as exc:
            items.append(_item("F-66", False, f"The inventory report cannot be read: {exc.message}"))
            return carried_bills, carried_stock
        bad = [e["message"] for e in report["errors"]]
        if bad:
            items.append(_item("F-66", False, "The inventory report has errors: " + "; ".join(bad)))
            return carried_bills, carried_stock
        godowns = {r["item_id"]: tuple((uuid.UUID(g["godown_id"]), Decimal(g["closing_qty"])) for g in r["by_godown"]) for r in register["rows"]}
        stock_items = [engine.StockItemIn(uuid.UUID(r["item_id"]), r["name"], Decimal(r["closing_qty"]), Decimal(r["carrying_value"]),
                                          godowns.get(r["item_id"], ())) for r in report["rows"]]
        carried_stock, found = engine.carry_stock(stock_items, stock.carrying_value)
        for f in found:
            items.append(_item("F-66", False, f.message))
        if not found:
            items.append(_item("F-66", True, f"{len(carried_stock)} stock row(s) (item and godown) carry forward at carrying value."))
    return carried_bills, carried_stock


def _plan(conn: Connection, client_id: object, fy_id: object, *, create_next_year: bool = False, confirm_no_depreciation: bool = False,
          acknowledged_flags: list[str] | None = None) -> Plan:
    fy = _year(conn, client_id, fy_id)
    profile = frepo.client_profile(conn, client_id)
    items: list[dict] = []
    closed = cr.get_close(conn, client_id, fy_id)
    if closed is not None and closed["status"] == "closed":
        items.append(_item("F-60", False, "This financial year is already closed."))
    n = cr.open_voucher_count(conn, client_id, fy.start_date, fy.end_date)
    items.append(_item("F-60", n == 0, "No draft or approved voucher is left in the year." if n == 0 else
                       f"{n} draft or approved voucher(s) are dated in the year. Post or delete them first."))
    statements = _statements(conn, client_id, fy_id, profile.entity_type, items)
    # depreciation (F-60)
    if cr.has_depreciable_assets(conn, client_id, fy.start_date, fy.end_date):
        if cr.has_posted_depreciation_run(conn, client_id, fy_id):
            items.append(_item("F-60", True, "The Companies Act depreciation run is posted."))
        elif confirm_no_depreciation:
            items.append(_item("F-60", True, "No book depreciation for the year (confirmed by the accountant)."))
        else:
            items.append(_item("F-60", False, "The client has depreciable assets but no posted Companies Act depreciation run for the year. "
                                              "Run and post the depreciation, or confirm that no depreciation is to be charged."))
    ack = list(acknowledged_flags or [])
    it_final = _it_state(conn, client_id, fy, ack, items)
    # engine
    entity = EntityType(profile.entity_type)
    row = frepo.get_closing_stock(conn, client_id, fy_id)
    stock = None if row is None else ClosingStockIn(row.cost_value, row.write_down, row.carrying_value, row.source, row.as_on_date)
    positions = final_statements.ledger_positions(conn, client_id, fy_id)
    partners = frepo.partner_shares(conn, client_id, fy_id) if entity in engine.FIRMS else ()
    names = {code: g.name for code, g in repo.groups_for_client(conn, client_id).items()}
    plan = engine.build_closing_plan(positions, engine.CloseContext(entity, fy.start_date, fy.end_date, _label(fy.start_date), stock, partners, names))
    for f in plan.errors:
        if f.rule_id != "F-41" or not any(x["rule_id"] == "F-41" for x in items):     # F-41 is already reported by the statements
            items.append(_item(f.rule_id, False, f.message, {"ledger_id": None if f.ledger_id is None else str(f.ledger_id)}))
    if not plan.errors:
        items.append(_item("F-62" if entity in engine.FIRMS else "F-63", True, "The closing entries and the carry-forward balance."))
    # next year and its openings (F-60, F-65, F-67)
    nxt = cr.next_year(conn, client_id, fy.end_date)
    if nxt is None:
        items.append(_item("F-60", create_next_year, "The next financial year will be created with its 12 periods." if create_next_year else
                           "The next financial year does not exist. Confirm that it may be created."))
    else:
        if cr.posted_voucher_in_year(conn, client_id, nxt[0]):
            items.append(_item("F-67", False, "The next financial year already has posted vouchers, so its openings cannot be written (F-67)."))
        elif any(cr.count_openings(conn, client_id, nxt[0]).values()):
            items.append(_item("F-65", False, "The next financial year already has opening balances, bills, stock or income-tax openings. The close writes "
                                              "them from the books; remove the existing ones first."))
        else:
            items.append(_item("F-65", True, "The next financial year has no openings yet."))
    carried_bills, carried_stock = _bills_and_stock(conn, client_id, fy, plan, row, items)
    return Plan(fy, profile.entity_type, items, plan, statements, {x.ledger_id: x.name for x in positions}, nxt, carried_bills, carried_stock,
                ack, it_final, closed)


# ============================================================================================ check


def check(conn: Connection, client_id: object, fy_id: object, *, create_next_year: bool = False, confirm_no_depreciation: bool = False,
          acknowledged_flags: list[str] | None = None) -> dict:
    p = _plan(conn, client_id, fy_id, create_next_year=create_next_year, confirm_no_depreciation=confirm_no_depreciation,
              acknowledged_flags=acknowledged_flags)
    c = p.close
    carry = c.carry if c else None
    return {
        "ready": p.ready, "items": p.items, "net_profit": _m(c.net_profit) if c else None,
        "appropriation_preview": [{"ledger_id": str(i), "name": n, "amount": _m(a)} for i, n, a in (c.appropriation if c else ())],
        "vouchers_preview": [{"step": v.step, "voucher_date": v.voucher_date.isoformat(), "reference_no": v.reference_no, "narration": v.narration,
                              "lines": [{"ledger_id": str(x.ledger_id), "ledger_name": p.names.get(x.ledger_id), "debit": _m(x.debit), "credit": _m(x.credit)}
                                        for x in v.lines]} for v in (c.vouchers if c else ())],
        "carry_preview": {"ledger_count": len(carry.ledger_openings) if carry else 0, "total_debit": _m(carry.total_debit) if carry else None,
                          "total_credit": _m(carry.total_credit) if carry else None, "bills_count": len(p.carried_bills),
                          "stock_items": len(p.carried_stock), "it_blocks": None},
        "next_financial_year": {"id": None if p.next_year is None else str(p.next_year[0]), "exists": p.next_year is not None},
        "engine_version": ENGINE_VERSION,
    }


# ============================================================================================ close


def create_next_financial_year(conn: Connection, client_id: object, fy_id: object, *, actor: str) -> object:
    """The year after `fy_id` with its 12 open monthly periods (audit-logged). Refused if it exists."""
    actor = require_actor(actor)
    fy = _year(conn, client_id, fy_id)
    if cr.next_year(conn, client_id, fy.end_date) is not None:
        raise ServiceError("year_exists", "The next financial year already exists.")
    start = date(fy.end_date.year, 4, 1)
    end = date(start.year + 1, 3, 31)
    months = _month_periods(start)
    new_id = cr.insert_year(conn, client_id, start, end, months)
    audit.log(conn, AuditEntry(client_id, actor, "create", "financial_year", new_id,
                               new={"start_date": start, "end_date": end, "periods": len(months), "created_by_year_end_close": str(fy_id)}))
    return new_id


def _draft_of(client_id: object, v) -> VoucherDraft:
    return VoucherDraft(client_id, "journal", v.voucher_date, v.narration, v.reference_no, None,
                        tuple(VoucherLine(x.ledger_id, x.debit, x.credit) for x in v.lines))


def close(conn: Connection, client_id: object, fy_id: object, *, create_next_year: bool = False, confirm_no_depreciation: bool = False,
          acknowledged_flags: list[str] | None = None, actor: str) -> dict:
    actor = require_actor(actor)
    _year(conn, client_id, fy_id)
    with conn.begin_nested():                       # all or nothing, even when the caller keeps its transaction open
        cr.lock_year(conn, client_id, fy_id)
        p = _plan(conn, client_id, fy_id, create_next_year=create_next_year, confirm_no_depreciation=confirm_no_depreciation,
                  acknowledged_flags=acknowledged_flags)
        if p.closed is not None and p.closed["status"] == "closed":
            raise ServiceError("already_closed", "This financial year is already closed.")
        if p.next_year is None and not create_next_year:
            raise ServiceError("next_year_missing", "The next financial year does not exist. Close again with create_next_year to create it.")
        if not p.ready:
            bad = [x for x in p.items if not x["ok"] and not (x["rule_id"] == "F-60" and p.next_year is None and not create_next_year)]
            raise ServiceError("close_blocked", f"The year cannot be closed: {len(bad)} item(s) need attention. " + " | ".join(x["message"] for x in bad[:5]),
                               bad)
        c = p.close
        next_id = p.next_year[0] if p.next_year else create_next_financial_year(conn, client_id, fy_id, actor=actor)
        voucher_ids: dict[str, object] = {}
        for v in c.vouchers:
            made = vouchers.create_draft(conn, _draft_of(client_id, v), actor=actor)
            if made.errors:
                raise VoucherRuleError(made.errors)
            vouchers.approve(conn, made.voucher_id, actor=actor)
            vouchers.post(conn, made.voucher_id, actor=actor)
            voucher_ids[v.step] = made.voucher_id
        if p.it_to_finalise:
            final_assets.finalize_it(conn, client_id, fy_id, p.it_acknowledged, actor=actor)
        for key, body in p.statements.items():
            cr.insert_snapshot(conn, client_id, fy_id, key, body["format"], body, ENGINE_VERSION, actor)
        it_rows = [(w["block_key"], w["closing_wdv"]) for w in fr.final_workings(conn, client_id, fy_id)]
        carried = {
            "ledger_openings": [{"ledger_id": str(lid), "debit": _m(d), "credit": _m(cc)} for lid, d, cc in c.carry.ledger_openings],
            "total_debit": _m(c.carry.total_debit), "total_credit": _m(c.carry.total_credit),
            "bills": [{"party_ledger_id": str(b.party_ledger_id), "bill_ref": b.bill_ref, "amount": _m(b.amount)} for b in p.carried_bills],
            "stock": [{"item_id": str(s.item_id), "godown_id": str(s.godown_id), "quantity": str(s.quantity), "value": _m(s.value)} for s in p.carried_stock],
            "it_blocks": [{"block_key": b, "opening_wdv": _m(w)} for b, w in it_rows],
        }
        close_id = cr.insert_close(conn, client_id, fy_id, next_id, c.net_profit,
                                   {"balance_transferred": _m(c.balance_to_transfer), "to": [{"ledger_id": str(i), "name": n, "amount": _m(a)} for i, n, a in c.appropriation]},
                                   carried, actor)
        for step, vid in voucher_ids.items():
            cr.link_voucher(conn, close_id, client_id, step, "closing", vid)
        for pid in cr.lock_periods(conn, client_id, fy_id):
            periods.lock_period(conn, client_id, pid, actor=actor)
        cr.insert_ledger_openings(conn, client_id, next_id, [(lid, d, cc) for lid, d, cc in c.carry.ledger_openings])
        cr.insert_bills(conn, client_id, next_id, p.carried_bills)
        cr.insert_stock(conn, client_id, next_id, p.carried_stock, actor)
        cr.insert_it_openings(conn, client_id, next_id, it_rows, actor)
        audit.log(conn, AuditEntry(client_id, actor, "close", "year_end_close", close_id, new={
            "financial_year_id": str(fy_id), "next_financial_year_id": str(next_id), "net_profit": _m(c.net_profit),
            "voucher_ids": {k: str(v) for k, v in voucher_ids.items()}, "carried": carried, "engine_version": ENGINE_VERSION}))
    return {"close_id": close_id, "voucher_ids": {s: voucher_ids.get(s) for s in engine.STEPS}, "net_profit": _m(c.net_profit),
            "carried": {"ledgers": len(c.carry.ledger_openings), "total_debit": _m(c.carry.total_debit), "total_credit": _m(c.carry.total_credit),
                        "bills": len(p.carried_bills), "stock_rows": len(p.carried_stock), "it_blocks": len(it_rows)}}


# ============================================================================================ read


def get_close(conn: Connection, client_id: object, fy_id: object) -> dict:
    _year(conn, client_id, fy_id)
    row = cr.get_close(conn, client_id, fy_id)
    if row is None:
        return {"status": "open", "close_id": None, "closed_by": None, "closed_at": None, "net_profit": None, "voucher_ids": {}, "carried": None,
                "reopened_by": None, "reopened_at": None, "reopen_reason": None}
    return {"status": row["status"], "close_id": row["id"], "closed_by": row["closed_by"], "closed_at": row["closed_at"], "net_profit": _m(row["net_profit"]),
            "voucher_ids": cr.close_vouchers(conn, row["id"], "closing"), "carried": row["carried"], "reopened_by": row["reopened_by"],
            "reopened_at": row["reopened_at"], "reopen_reason": row["reopen_reason"]}


# ============================================================================================ reopen


def reopen(conn: Connection, client_id: object, close_id: object, reason: str, *, actor: str) -> dict:
    actor = require_actor(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ServiceError("reason_required", "A reason is required to reopen a closed year.")
    found = cr.get_close_by_id(conn, client_id, close_id)
    if found is None:
        raise ServiceError("not_found", "Year-end close not found for this client.")
    close_row, fy_id = found
    if close_row["status"] != "closed":
        raise ServiceError("not_closed", "This year-end close has already been reopened.")
    fy = _year(conn, client_id, fy_id)
    next_id = close_row["next_financial_year_id"]
    with conn.begin_nested():
        cr.lock_year(conn, client_id, fy_id)
        if cr.posted_voucher_in_year(conn, client_id, next_id) or final_hooks.year_is_closed(conn, client_id, next_id):
            raise ServiceError("reopen_blocked", "The next financial year already has posted vouchers (or is closed), so this year cannot be reopened "
                                                 "(F-64): the carried openings would become wrong.")
        carried = close_row["carried"]
        want = {uuid.UUID(r["ledger_id"]): (Decimal(r["debit"]), Decimal(r["credit"])) for r in carried["ledger_openings"]}
        counts = cr.count_openings(conn, client_id, next_id)
        if (cr.current_ledger_openings(conn, client_id, next_id) != want or counts["bills"] != len(carried["bills"])
                or counts["stock"] != len(carried["stock"]) or counts["it_blocks"] != len(carried["it_blocks"])):
            raise ServiceError("reopen_blocked", "The openings of the next financial year were changed after the close. Only the openings the close "
                                                 "wrote may be replaced; restore them or ask the owner.")
        for pid in cr.locked_periods(conn, client_id, fy_id):
            periods.unlock_period(conn, client_id, pid, f"Year-end reopen: {reason}", actor=actor)
        closing = cr.close_vouchers(conn, close_id, "closing")
        reversals: dict[str, object] = {}
        for step in reversed(engine.STEPS):
            if step in closing:
                rid = vouchers.reverse(conn, closing[step], fy.end_date, f"Year-end reopen: {reason}", actor=actor, _year_end_reopen=True)
                cr.link_voucher(conn, close_id, client_id, step, "reversal", rid)
                reversals[step] = rid
        cr.mark_reopened(conn, close_id, actor, reason)
        snapshots, workings = cr.supersede_final(conn, client_id, fy_id)
        cr.delete_openings(conn, client_id, next_id)
        audit.log(conn, AuditEntry(client_id, actor, "reopen", "year_end_close", close_id, old={"status": "closed"}, new={
            "status": "reopened", "reason": reason, "reversal_voucher_ids": {k: str(v) for k, v in reversals.items()},
            "snapshots_superseded": snapshots, "it_workings_superseded": workings, "removed_openings": carried}))
    return {"ok": True, "reversal_voucher_ids": [reversals[s] for s in engine.STEPS[::-1] if s in reversals]}
