"""Read-only loaders of the compliance checks A-07..A-11, A-16, A-17 (Phase 8, package C).

Builds `ComplianceFacts` (engine/audit_checks_compliance.py) from the books by calling the existing Phase 2 to 5 loaders and services:
bills + MSME rules (services/msme, services/bills), the GST tie-out (services/gst_returns.tie_out, which only reads), the TDS masters and rule
tables (db/repositories_tds_deduction), challans (db/repositories_tds_challans), cash ledger lines and stock movements. It only SELECTs: no
voucher, ledger, bill, return, challan or movement is created or changed (audit_hooks.READ_ONLY_TABLES). A part that cannot be loaded is left
out with a note (never guessed). Services take a Connection and never commit.

TDS candidates (A-09 / A-10). The entered TDS items are the accountant's statement of what was deducted; each (voucher, deductee, nature) group is
re-worked from the rule tables on the typed base. A voucher WITHOUT an item is tested only when its party is an active deductee with a default
nature (a master setting; no guess from names) and the payment / credit is not already covered elsewhere:
  - a Payment that settles an earlier bill (an against-reference allocation, or the party already had a credit in the year or an opening credit)
    is not tested: the tax falls due when the bill is credited;
  - a Purchase / Journal credit whose bill reference was settled by a Payment that carries a TDS item is not tested: the tax was deducted at payment.
The base of an untested-by-item voucher is the party line as booked (gross: GST shown in the line is not removed), said so in the evidence.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.db import repositories as repo
from app.db import repositories_cash as cash_repo
from app.db import repositories_gst_masters as gst_repo
from app.db import repositories_inventory_masters as inv
from app.db import repositories_inventory_reports as inv_rep
from app.db import repositories_tds_challans as chal
from app.db import repositories_tds_deduction as tdb
from app.engine import audit_checks_compliance as c
from app.engine import tds_calc
from app.engine.audit_types import AuditParams
from app.engine.cash_rules import CashMovement
from app.engine.inventory_types import InventoryPolicy, NegativeStockMode, ValuationMethod
from app.engine.models import OpeningBalance
from app.rules.msme import load_msme_rules
from app.services import bills as bills_service
from app.services import gst_returns, queries
from app.services.errors import ServiceError

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")
ALL = ("A-07", "A-08", "A-09", "A-10", "A-11", "A-16", "A-17")


def _as_on(params: AuditParams, today: date | None) -> date:
    """Open items and undeposited tax are judged as on the end of the window, never later than today."""
    return min(params.to_date, today or date.today())


def load_compliance_facts(conn: Connection, client_id: object, fy_id: object, params: AuditParams, check_ids: tuple[str, ...] | None = None,
                          today: date | None = None) -> c.ComplianceFacts:
    queries.require_client(conn, client_id)
    wanted = set(check_ids or ALL)
    fy = repo.get_financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("no_period", "Financial year not found for this client.")
    notes: dict[str, list[str]] = defaultdict(list)
    parts: dict[str, Any] = {}
    as_on = _as_on(params, today)
    if "A-07" in wanted:
        parts["msme"] = _msme(conn, client_id, as_on, notes["A-07"])
    if "A-08" in wanted:
        parts["gst"] = _gst(conn, client_id, params, notes["A-08"])
    if wanted & {"A-09", "A-10"}:
        tds = _tds(conn, client_id, fy_id, notes)
        parts["tds"] = tds
    if "A-11" in wanted:
        parts["deposits"] = _deposits(conn, client_id, fy_id, as_on)
    if "A-16" in wanted:
        parts["cash"] = _cash(conn, client_id, fy_id)
    if "A-17" in wanted:
        parts["stock"] = _stock(conn, client_id, fy, notes["A-17"])
    return c.ComplianceFacts(notes={k: tuple(v) for k, v in notes.items() if v}, **parts)


# ---- A-07 ------------------------------------------------------------------------------------------------------------------------------------


def _msme(conn: Connection, client_id: object, as_on: date, notes: list[str]) -> c.MsmeFacts | None:
    try:
        open_bills = bills_service.open_bills(conn, client_id, as_on)
    except ServiceError as exc:
        notes.append(f"Open bills as on {as_on:%d-%m-%Y} could not be read: {exc.message}")
        return None
    return c.MsmeFacts(tuple(open_bills), cash_repo.party_facts(conn, client_id), tuple(load_msme_rules(conn)), as_on)


# ---- A-08 ------------------------------------------------------------------------------------------------------------------------------------


def _months(start: date, end: date) -> list[date]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return out


def _gst(conn: Connection, client_id: object, params: AuditParams, notes: list[str]) -> tuple[c.GstPeriodFact, ...]:
    out = []
    regs = [r for r in gst_repo.registration_rows(conn, client_id) if r.is_active and r.registration_type == "regular"]
    if not regs:
        notes.append("The client has no active regular GST registration: no tie-out to test.")
    for reg in regs:
        for start in _months(params.from_date, params.to_date):
            end = date(start.year + (start.month == 12), start.month % 12 + 1, 1) - timedelta(days=1)
            if end < reg.effective_from or (reg.effective_to is not None and start > reg.effective_to):
                continue
            try:
                env = gst_returns.tie_out(conn, client_id, reg.id, "month", start)
            except ServiceError as exc:
                notes.append(f"{reg.gstin} {start:%m-%Y}: tie-out not worked, {exc.message}")
                continue
            t = env["tables"]
            out.append(c.GstPeriodFact(reg.id, reg.gstin, start, end, tuple(t["rows"]), t["itc"], tuple(t["causes"]), bool(t["ties"]),
                                       env["rule_status"]["worst"]))
    return tuple(out)


# ---- A-09 / A-10 -------------------------------------------------------------------------------------------------------------------------


def _tds(conn: Connection, client_id: object, fy_id: object, notes: dict[str, list[str]]) -> c.TdsFacts | None:
    natures = tdb.load_natures(conn)
    items = conn.execute(text(
        "SELECT i.voucher_id, v.voucher_number, v.voucher_type, v.voucher_date, i.deductee_ledger_id, i.nature_key, i.payment_amount, i.tds_amount, "
        "i.credit_date, i.payment_date, i.lower_cert_id FROM tds_voucher_items i JOIN vouchers v ON v.id = i.voucher_id AND v.client_id = i.client_id "
        "WHERE i.client_id = :c AND i.kind = 'tds' AND v.status = 'posted' AND v.financial_year_id = :fy ORDER BY v.voucher_date, i.item_no"),
        {"c": client_id, "fy": fy_id}).all()
    default = {r[0]: r[1] for r in conn.execute(text(
        "SELECT ledger_id, default_nature_key FROM tds_deductees WHERE client_id = :c AND is_active AND default_nature_key IS NOT NULL"), {"c": client_id})}
    default = {k: v for k, v in default.items() if natures.get(v) is not None and natures[v].kind == "tds" and natures[v].rate_mode == "flat"}

    marked: dict[tuple, dict] = {}
    for vid, number, vtype, vdate, ledger, nature, amount, tax, cdate, pdate, cert in items:
        if natures.get(nature) is not None and natures[nature].rate_mode == "slab_manual":
            notes["A-09"].append(f"{number or vid}: a salary item (tax typed by the accountant) is not re-worked")
            continue
        key = (vid, ledger, tds_calc.RENT_LAND_BUILDING if nature == tds_calc.RENT_194IB else nature)
        g = marked.setdefault(key, {"number": number, "type": vtype, "date": vdate, "base": ZERO, "tax": ZERO, "credit": cdate, "payment": pdate,
                                    "cert": None if cert is None else str(cert)})
        g["base"] += amount.quantize(CENTS)
        g["tax"] += tax.quantize(CENTS)
    marked_vouchers = {(k[0], k[1]) for k in marked}
    paid_with_items = {(vid, ledger) for vid, ledger, _n in marked if marked[(vid, ledger, _n)]["type"] == "payment"}

    unmarked = _unmarked_candidates(conn, client_id, fy_id, default, marked_vouchers, paid_with_items)
    ledgers = sorted({k[1] for k in marked} | {u["ledger"] for u in unmarked}, key=str)
    if not ledgers:
        notes["A-09"].append("No TDS item and no deductee with a default nature in this year: nothing to test.")
    names = tdb.ledger_names(conn, ledgers) if ledgers else {}
    cands = [c.TdsCandidate(vid, g["number"] or str(vid), g["type"], g["date"], ledger, names.get(ledger, str(ledger)), nature, g["base"], "item",
                            g["credit"], g["payment"], g["tax"], g["cert"]) for (vid, ledger, nature), g in marked.items()]
    for u in unmarked:
        credit_side = u["type"] != "payment"
        cands.append(c.TdsCandidate(u["voucher_id"], u["number"] or str(u["voucher_id"]), u["type"], u["date"], u["ledger"], names.get(u["ledger"], str(u["ledger"])),
                                    default[u["ledger"]], u["base"], "party_line", u["date"] if credit_side else None, None if credit_side else u["date"], ZERO))
    notes["A-10"] = list(notes["A-09"])
    keys = sorted({x.nature_key for x in cands} | ({tds_calc.RENT_194IB} if any(x.nature_key == tds_calc.RENT_LAND_BUILDING for x in cands) else set()))
    years = conn.execute(text("SELECT id, start_date, end_date FROM financial_years WHERE client_id = :c"), {"c": client_id}).all()

    def fy_of(on: date):
        return next((y[0] for y in years if y[1] <= on <= y[2]), None)

    deductees, _inactive, _n = tdb.load_deductees(conn, client_id, ledgers) if ledgers else ({}, set(), {})
    cert_ids = sorted({x.lower_cert_id for x in cands if x.lower_cert_id}, key=str)
    certs = {k: _fresh(v) for k, v in tdb.load_certs(conn, client_id, cert_ids).items()}   # the whole year is re-worked: nothing is used up yet
    ctx = tds_calc.TdsContext("tds", natures, deductees, tdb.load_rates(conn, keys) if keys else [], tdb.load_section_refs(conn, keys) if keys else [],
                              certs, {}, fy_of, tdb.load_buyer_flags(conn, client_id), tdb.load_deductor_flags(conn, client_id))
    return c.TdsFacts(tuple(cands), ctx)


def _fresh(cert):
    import dataclasses

    return dataclasses.replace(cert, amount_used=Decimal(0))


def _unmarked_candidates(conn: Connection, client_id: object, fy_id: object, default: dict, marked_vouchers: set, paid_with_items: set) -> list[dict]:
    if not default:
        return []
    ledgers = list(default)
    lines = conn.execute(text(
        "SELECT v.id, v.voucher_number, v.voucher_type, v.voucher_date, vl.ledger_id, vl.debit, vl.credit FROM voucher_lines vl "
        "JOIN vouchers v ON v.id = vl.voucher_id WHERE v.client_id = :c AND v.financial_year_id = :fy AND v.status = 'posted' "
        "AND v.reverses_voucher_id IS NULL AND v.voucher_type IN ('payment', 'purchase', 'journal') AND vl.ledger_id = ANY(:l) "
        "ORDER BY v.voucher_date, v.id"), {"c": client_id, "fy": fy_id, "l": ledgers}).all()
    allocs = conn.execute(text(
        "SELECT a.voucher_id, a.party_ledger_id, a.kind, lower(btrim(a.bill_ref)) FROM bill_allocations a JOIN vouchers v ON v.id = a.voucher_id "
        "WHERE a.client_id = :c AND v.financial_year_id = :fy AND v.status = 'posted' AND a.party_ledger_id = ANY(:l)"),
        {"c": client_id, "fy": fy_id, "l": ledgers}).all()
    against = defaultdict(set)      # voucher id -> ledgers it settles an earlier bill for
    settled_at_payment = defaultdict(set)   # ledger -> bill refs settled by a Payment that carries a TDS item
    new_refs = defaultdict(set)     # (voucher id, ledger) -> bill refs it creates
    for vid, ledger, kind, ref in allocs:
        if kind == "against_ref":
            against[vid].add(ledger)
            if (vid, ledger) in paid_with_items:
                settled_at_payment[ledger].add(ref)
        elif kind == "new_ref":
            new_refs[(vid, ledger)].add(ref)
    openings = repo.openings_for_year(conn, client_id, fy_id)
    first_credit: dict[Any, date] = {}
    for _vid, _n, vtype, vdate, ledger, debit, credit in lines:
        if vtype != "payment" and credit > 0 and (ledger not in first_credit or vdate < first_credit[ledger]):
            first_credit[ledger] = vdate
    out = []
    for vid, number, vtype, vdate, ledger, debit, credit in lines:
        if (vid, ledger) in marked_vouchers:
            continue
        if vtype == "payment":
            base = debit.quantize(CENTS)
            had_credit = (ledger in first_credit and first_credit[ledger] <= vdate) or (ledger in openings and openings[ledger].credit > 0)
            if base <= 0 or ledger in against[vid] or had_credit:
                continue
        else:
            base = credit.quantize(CENTS)
            if base <= 0 or new_refs.get((vid, ledger), set()) & settled_at_payment[ledger]:
                continue
        out.append({"voucher_id": vid, "number": number, "type": vtype, "date": vdate, "ledger": ledger, "base": base})
    return out


# ---- A-11 ------------------------------------------------------------------------------------------------------------------------------------


def _deposits(conn: Connection, client_id: object, fy_id: object, as_on: date) -> c.DepositFacts:
    deposits = defaultdict(list)
    for a in chal.allocations_for_year(conn, client_id, fy_id):
        if a["deposit_date"] is not None:
            deposits[str(a["item_id"])].append((a["deposit_date"], Decimal(str(a["amount"])).quantize(CENTS)))
    items = tuple(
        c.DepositItem(i["item_id"], i["voucher_id"], i["voucher_number"] or str(i["voucher_id"]), i["deductee_name"], i["section_ref"], i["kind"],
                      i["event_date"], Decimal(str(i["tds_amount"])).quantize(CENTS), tuple(deposits.get(str(i["item_id"]), ())))
        for i in chal.items_for_year(conn, client_id, fy_id))
    rules, _sources = chal.due_date_rules(conn)
    return c.DepositFacts(items, tuple(rules), as_on)


# ---- A-16 ------------------------------------------------------------------------------------------------------------------------------------


def _cash(conn: Connection, client_id: object, fy_id: object) -> tuple[c.CashLedgerFact, ...]:
    ids = [r[0] for r in conn.execute(text("SELECT id FROM ledgers WHERE client_id = :c"), {"c": client_id})]
    cash = cash_repo.cash_ledgers_among(conn, client_id, ids)
    if not cash:
        return ()
    openings = repo.openings_for_year(conn, client_id, fy_id)
    rows = conn.execute(text(
        "SELECT vl.ledger_id, v.voucher_date, vl.debit, vl.credit, v.id FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id "
        "WHERE v.client_id = :c AND v.financial_year_id = :fy AND vl.ledger_id = ANY(:l) AND v.status IN ('posted', 'reversed') "
        "ORDER BY v.voucher_date, v.id"), {"c": client_id, "fy": fy_id, "l": list(cash)}).all()
    moves: dict[Any, list[CashMovement]] = defaultdict(list)
    vouchers: dict[Any, dict[date, list[str]]] = defaultdict(lambda: defaultdict(list))
    for ledger, vdate, debit, credit, vid in rows:
        moves[ledger].append(CashMovement(vdate, debit.quantize(CENTS), credit.quantize(CENTS)))
        if str(vid) not in vouchers[ledger][vdate]:
            vouchers[ledger][vdate].append(str(vid))
    return tuple(
        c.CashLedgerFact(ledger, name, openings.get(ledger, OpeningBalance(ZERO, ZERO)), tuple(moves[ledger]),
                         {d: tuple(v) for d, v in vouchers[ledger].items()})
        for ledger, name in sorted(cash.items(), key=lambda kv: kv[1]))


# ---- A-17 ------------------------------------------------------------------------------------------------------------------------------------


def _stock(conn: Connection, client_id: object, fy: Any, notes: list[str]) -> c.StockFacts | None:
    policy = inv.policy_row(conn, client_id, fy.id)
    opening = inv_rep.load_opening(conn, client_id, fy.id)
    movements, numbers = inv_rep.load_movements(conn, client_id, fy.id)
    if policy is None:
        if opening or movements:
            notes.append("The inventory policy (valuation method) is not set for this financial year: the stock history was not tested.")
            return None
        return c.StockFacts(InventoryPolicy(ValuationMethod.FIFO, NegativeStockMode.BLOCK), (), (), {}, {}, {}, fy.start_date, fy.end_date)
    return c.StockFacts(InventoryPolicy(ValuationMethod(policy.valuation_method), NegativeStockMode(policy.negative_stock_mode)), tuple(opening),
                        tuple(movements), numbers, {i.item_id: i.name for i in inv_rep.stock_item_infos(conn, client_id)},
                        inv_rep.godown_names(conn, client_id), fy.start_date, fy.end_date)
