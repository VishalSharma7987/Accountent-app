"""TDS / TCS deduction on vouchers (Phase 4, package B; rules T-01 .. T-17, T-13).

The accountant marks items (deductee, nature, amount, dates); the engine (engine/tds_calc.py) computes the tax from the rule
tables; this service loads the data, adds the generated tax line to the draft, writes `tds_voucher_items` (the engine's whole
working) and re-checks the stored working at approve and post (T-13). Services take a Connection and never commit.

Position rule (decision, see docs/decisions_parts/B4.md): the position of a deductee + nature + financial year is the sum of POSTED,
non-reversed vouchers. A draft is therefore computed against what is posted now; if another voucher posts first and changes the
position, T-13 blocks the later one at approve / post until it is saved again.
"""

import dataclasses
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_tds_deduction as tdb
from app.engine import tds_calc
from app.engine.models import Allocation, ValidationError, VoucherDraft, VoucherLine
from app.engine.money import MoneyError, format_inr, parse_amount
from app.engine.tds_types import ENGINE_VERSION, TdsItemResult, TdsLineIn
from app.engine.validation import CASH_BANK, group_chain

ZERO = Decimal("0.00")
PAYABLE_GROUP = "duties_taxes"
ROLE_OF_KIND = {"tds": "tds_payable", "tcs": "tcs_payable"}


def _amount(raw: object) -> Decimal:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return ZERO
    return parse_amount(raw)


def _rate_text(rate: Decimal) -> str:
    return format(rate.normalize(), "f")


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


@dataclasses.dataclass
class _Computed:
    comp: tds_calc.TdsComputation
    kind: str
    vctx: Any
    roles: list
    names: dict
    errors: list[ValidationError]


def _compute(conn: Connection, client_id: object, items: list[TdsLineIn], extra_ledgers: list[object]) -> _Computed:
    natures = tdb.load_natures(conn)
    first = natures.get(items[0].nature_key)
    kind = first.kind if first else "tds"
    keys = sorted({i.nature_key for i in items})
    ledgers = sorted({i.deductee_ledger_id for i in items}, key=str)
    deductees, inactive, names = tdb.load_deductees(conn, client_id, ledgers)
    roles = tdb.load_roles(conn, client_id)
    payable_ids = [r[2] for r in roles]
    vctx = repo.load_validation_context(conn, client_id, ledgers + list(extra_ledgers) + payable_ids)
    if not vctx.client_exists:
        raise _service_error("not_found", "Client not found.")
    pre = [
        ValidationError("T-09", f"Item {n}: deductee '{names.get(i.deductee_ledger_id, '')}' is switched off; activate it first.", n)
        for n, i in enumerate(items, start=1) if i.deductee_ledger_id in inactive
    ]
    years = vctx.years

    def fy_of(on: date):
        for y in years:
            if y.start_date <= on <= y.end_date:
                return y.id
        return None

    events = [tds_calc.event_date(i.credit_date, i.payment_date) for i in items]
    fy_ids = sorted({fy_of(e) for e in events if e is not None and fy_of(e) is not None}, key=str)
    cert_ids = sorted({i.lower_cert_id for i in items if i.lower_cert_id is not None}, key=str)
    ctx = tds_calc.TdsContext(
        kind, natures, deductees, tdb.load_rates(conn, keys), tdb.load_section_refs(conn, keys),
        tdb.load_certs(conn, client_id, cert_ids), tdb.load_priors(conn, client_id, ledgers, keys, fy_ids), fy_of,
        tdb.load_buyer_flags(conn, client_id),
    )
    if pre:
        return _Computed(tds_calc.TdsComputation((), tuple(pre), tds_calc.rule_status_of([])), kind, vctx, roles, names, pre)
    comp = tds_calc.compute_items(items, ctx)
    return _Computed(comp, kind, vctx, roles, names, list(comp.errors))


def _service_error(code: str, message: str):
    from app.services.errors import ServiceError

    return ServiceError(code, message)


def _payable_of(done: _Computed) -> tuple[dict[str, object], list[ValidationError]]:
    """T-14: the TDS / TCS payable ledger of every nature with tax: the nature's own mapping, else the default; it must sit under Duties & Taxes."""
    role = ROLE_OF_KIND[done.kind]
    own = {r[1]: r[2] for r in done.roles if r[0] == role and r[1] is not None}
    default = next((r[2] for r in done.roles if r[0] == role and r[1] is None), None)
    out: dict[str, object] = {}
    errors: list[ValidationError] = []
    for r in done.comp.items:
        if r.tds_amount <= 0 or r.nature_key in out:
            continue
        ledger_id = own.get(r.nature_key, default)
        ledger = done.vctx.ledgers.get(ledger_id) if ledger_id is not None else None
        if ledger is None:
            errors.append(ValidationError("T-14", f"Item {r.item_no}: no {done.kind.upper()} payable ledger is set up for '{r.nature_key}'; map the ledger first.", r.item_no))
        elif PAYABLE_GROUP not in group_chain(ledger.group_code, done.vctx.groups):
            errors.append(ValidationError("T-14", f"Item {r.item_no}: '{ledger.name}' is not under Duties & Taxes and cannot be the {done.kind.upper()} payable ledger.", r.item_no))
        else:
            out[r.nature_key] = ledger_id
    return out, errors


def _adjusted(original: VoucherLine, debit: Decimal, credit: Decimal, old_debit: Decimal, old_credit: Decimal) -> VoucherLine:
    """The party line with its new amount; bill allocations follow the change on their last row."""
    delta = (debit - old_debit) + (credit - old_credit)
    allocations = original.allocations
    if allocations and delta != 0:
        *head, last = allocations
        allocations = (*head, Allocation(last.kind, _amount(last.amount) + delta, last.bill_ref, last.due_date))
    return dataclasses.replace(
        original, debit=debit if debit != old_debit else original.debit, credit=credit if credit != old_credit else original.credit,
        allocations=allocations,
    )


# ================================================================================================== hooks


def expand(conn: Connection, draft: VoucherDraft) -> tuple[VoucherDraft, list[ValidationError]]:
    """Run the engine on the draft's `tds` block and add the tax line(s). A draft without a block (or already expanded) is unchanged."""
    if not draft.tds or draft.tds_results:
        return draft, []
    if draft.gst is not None:
        return draft, [ValidationError("T-16", "TDS on a voucher entered in GST invoice mode is not supported yet; enter it as a plain voucher.")]
    try:
        old = [(x.ledger_id, _amount(x.debit), _amount(x.credit)) for x in draft.lines]
    except MoneyError:
        return draft, []  # V-03 reports the unreadable amount
    done = _compute(conn, draft.client_id, list(draft.tds), [x.ledger_id for x in draft.lines])
    if done.errors:
        return draft, done.errors
    payable_of, errors = _payable_of(done)
    if errors:
        return draft, errors
    cash_bank = {lid for lid, led in done.vctx.ledgers.items() if CASH_BANK & set(group_chain(led.group_code, done.vctx.groups))}
    new, _, errors = tds_calc.expand_lines(draft.voucher_type, done.kind, old, done.comp.items, payable_of, cash_bank)
    if errors:
        return draft, errors
    lines = []
    for n, (ledger_id, debit, credit) in enumerate(new):
        if n < len(old):
            o = draft.lines[n]
            lines.append(o if (debit, credit) == old[n][1:] else _adjusted(o, debit, credit, old[n][1], old[n][2]))
        else:
            lines.append(VoucherLine(ledger_id, debit if debit > 0 else None, credit if credit > 0 else None))
    return dataclasses.replace(draft, lines=tuple(lines), tds_results=tuple(done.comp.items)), []


def _tax_line_numbers(draft_lines: int, results: tuple[TdsItemResult, ...]) -> dict[int, int]:
    """item_no -> voucher line of its tax line: the tax lines are the last lines, one per item with tax, in item order."""
    taxed = [r for r in results if r.tds_amount > 0]
    first = draft_lines - len(taxed) + 1
    return {r.item_no: first + k for k, r in enumerate(taxed)}


def persist(conn: Connection, client_id: object, voucher_id: object, draft: VoucherDraft, actor: str) -> None:
    """Replace the items of a draft voucher (the guard trigger allows this only while it is a draft)."""
    tdb.delete_items(conn, voucher_id)
    if not draft.tds_results:
        return
    kinds = tdb.nature_kinds(conn)
    line_of = _tax_line_numbers(len(draft.lines), draft.tds_results)
    fy_cache: dict[date, object] = {}
    rows = []
    for r, inp in zip(draft.tds_results, draft.tds, strict=True):
        if r.event_date not in fy_cache:
            fy_cache[r.event_date] = tdb.financial_year_of(conn, client_id, r.event_date)[0]
        rows.append({
            "client_id": client_id, "voucher_id": voucher_id, "item_no": r.item_no, "kind": kinds[r.nature_key],
            "deductee_ledger_id": r.deductee_ledger_id, "nature_key": r.nature_key, "act": r.act, "section_ref": r.section_ref,
            "table_ref": r.table_ref, "rate_rule_id": None if r.rate_rule_id is None else uuid.UUID(r.rate_rule_id),
            "financial_year_id": fy_cache[r.event_date], "event_date": r.event_date, "credit_date": inp.credit_date,
            "payment_date": inp.payment_date, "payment_amount": r.payment_amount, "cumulative_before": r.cumulative_before,
            "cumulative_after": r.cumulative_after, "threshold_crossed": r.threshold_crossed, "taxable_base": r.taxable_base,
            "rate_applied": r.rate_applied, "rate_reason": r.rate_reason, "lower_cert_id": r.lower_cert_id,
            "tax_already_on_base": r.tax_already_on_base, "tds_amount": r.tds_amount, "tds_line_no": line_of.get(r.item_no),
            "engine_version": ENGINE_VERSION, "note": " | ".join(r.warnings) or None,
        })
    tdb.insert_items(conn, rows)


def _warnings(note: str | None) -> list[dict]:
    out = []
    for part in (note or "").split(" | "):
        if part.strip():
            rule, _, message = part.partition(": ")
            out.append({"rule_id": rule, "message": message})
    return out


def _item_out(*, item_no, ledger_id, name, nature_key, act, section_ref, table_ref, event_date, payment_amount, cumulative_before,
              cumulative_after, threshold_crossed, taxable_base, rate_applied, rate_reason, lower_cert_id, tax_already, tds_amount,
              line_no, status, warnings) -> dict:
    return {
        "item_no": item_no, "deductee_ledger_id": str(ledger_id), "deductee_name": name, "nature_key": nature_key, "act": act,
        "section_ref": section_ref, "table_ref": table_ref, "event_date": event_date.isoformat(),
        "payment_amount": f"{payment_amount:.2f}", "cumulative_before": f"{cumulative_before:.2f}",
        "cumulative_after": f"{cumulative_after:.2f}", "threshold_crossed": threshold_crossed, "taxable_base": f"{taxable_base:.2f}",
        "rate_applied": _rate_text(rate_applied), "rate_reason": rate_reason,
        "lower_cert_id": None if lower_cert_id is None else str(lower_cert_id), "tax_already_on_base": f"{tax_already:.2f}",
        "tds_amount": f"{tds_amount:.2f}", "tds_line_no": line_no, "verification_status": status, "warnings": warnings,
    }


def preview_block(conn: Connection, draft: VoucherDraft) -> dict | None:
    """The `tds` block of an expanded draft for tds-preview (None when the draft has no results)."""
    if not draft.tds_results:
        return None
    names = repo_names(conn, [r.deductee_ledger_id for r in draft.tds_results])
    line_of = _tax_line_numbers(len(draft.lines), draft.tds_results)
    items = [
        _item_out(
            item_no=r.item_no, ledger_id=r.deductee_ledger_id, name=names.get(r.deductee_ledger_id, ""), nature_key=r.nature_key,
            act=r.act, section_ref=r.section_ref, table_ref=r.table_ref, event_date=r.event_date, payment_amount=r.payment_amount,
            cumulative_before=r.cumulative_before, cumulative_after=r.cumulative_after, threshold_crossed=r.threshold_crossed,
            taxable_base=r.taxable_base, rate_applied=r.rate_applied, rate_reason=r.rate_reason, lower_cert_id=r.lower_cert_id,
            tax_already=r.tax_already_on_base, tds_amount=r.tds_amount, line_no=line_of.get(r.item_no), status=r.verification_status,
            warnings=[w for n in r.warnings for w in _warnings(n)],
        )
        for r in draft.tds_results
    ]
    return {"engine_version": ENGINE_VERSION, "items": items}


def repo_names(conn: Connection, ids: list[object]) -> dict[object, str]:
    return tdb.ledger_names(conn, ids)


def load(conn: Connection, client_id: object, voucher_id: object) -> dict | None:
    rows = tdb.load_items(conn, voucher_id)
    if not rows:
        return None
    items = [
        _item_out(
            item_no=r["item_no"], ledger_id=r["deductee_ledger_id"], name=r["deductee_name"], nature_key=r["nature_key"], act=r["act"],
            section_ref=r["section_ref"], table_ref=r["table_ref"], event_date=r["event_date"], payment_amount=r["payment_amount"],
            cumulative_before=r["cumulative_before"], cumulative_after=r["cumulative_after"], threshold_crossed=r["threshold_crossed"],
            taxable_base=r["taxable_base"], rate_applied=r["rate_applied"], rate_reason=r["rate_reason"],
            lower_cert_id=r["lower_cert_id"], tax_already=r["tax_already_on_base"], tds_amount=r["tds_amount"],
            line_no=r["tds_line_no"], status=r["verification_status"] or "pending", warnings=_warnings(r["note"]),
        )
        for r in rows
    ]
    statuses = [i["verification_status"] for i in items]
    rule_ids = [r["rate_rule_id"] for r in rows if r["rate_rule_id"] is not None]
    return {
        "engine_version": rows[0]["engine_version"], "items": items,
        "rule_status": {"worst": tds_calc.worst_status(statuses), "pending_sources": tdb.pending_rate_sources(conn, rule_ids)},
    }


def snapshot(draft: VoucherDraft) -> dict | None:
    """The TDS items for the audit log (None for a voucher without a block)."""
    if not draft.tds_results:
        return None
    return {"engine_version": ENGINE_VERSION, "items": [
        {"item_no": r.item_no, "deductee_ledger_id": str(r.deductee_ledger_id), "nature_key": r.nature_key, "act": r.act,
         "section_ref": r.section_ref, "event_date": r.event_date.isoformat(), "taxable_base": f"{r.taxable_base:.2f}",
         "rate_applied": _rate_text(r.rate_applied), "rate_reason": r.rate_reason, "tds_amount": f"{r.tds_amount:.2f}"}
        for r in draft.tds_results
    ]}


# ===================================================================================== T-13 at approve / post

_COMPARED = (
    ("act", "Act"), ("section_ref", "section"), ("table_ref", "table entry"), ("event_date", "event date"),
    ("cumulative_before", "amount before this voucher"), ("taxable_base", "taxable amount"), ("rate_applied", "rate"),
    ("rate_reason", "reason for the rate"), ("lower_cert_id", "certificate"), ("tax_already_on_base", "tax already deducted"),
    ("tds_amount", "tax"), ("threshold_crossed", "threshold crossed"),
)


def _shown(value: object, field: str) -> str:
    if isinstance(value, Decimal):
        return _rate_text(value) + "%" if field == "rate_applied" else format_inr(value)
    if isinstance(value, date):
        return _fmt(value)
    return "none" if value is None else str(value)


def revalidate(conn: Connection, record: Any) -> list[ValidationError]:
    """T-13: recompute the stored items and compare; a difference (or a tax line that does not match) blocks approve / post."""
    rows = tdb.load_items(conn, record.id)
    if not rows:
        return []
    inputs = [
        TdsLineIn(r["deductee_ledger_id"], r["nature_key"], r["payment_amount"].quantize(Decimal("0.01")), r["credit_date"], r["payment_date"], r["lower_cert_id"],
                  r["tds_amount"] if r["rate_reason"] == "manual_salary" else None)
        for r in rows
    ]
    done = _compute(conn, record.client_id, inputs, [x.ledger_id for x in record.lines])
    if done.errors:
        return done.errors
    errors: list[ValidationError] = []
    for r, got in zip(rows, done.comp.items, strict=True):
        n = r["item_no"]
        for field, label in _COMPARED:
            stored, fresh = r[field], getattr(got, field)
            if stored is not None and isinstance(stored, Decimal) and isinstance(fresh, Decimal):
                stored, fresh = stored.quantize(Decimal("0.0001")), fresh.quantize(Decimal("0.0001"))
            if stored != fresh:
                errors.append(ValidationError(
                    "T-13", f"Item {n}: the stored {label} ({_shown(r[field], field)}) differs from the recalculation ({_shown(getattr(got, field), field)}). "
                    "The deductee's position or the rule data changed, or the draft was altered: return it to draft and save it again.", n))
                break
    if errors:
        return errors
    payable_of, perrors = _payable_of(done)
    if perrors:
        return perrors
    by_line = {x.line_no: x for x in record.lines}
    for r in rows:
        if r["tds_amount"] > 0:
            line = by_line.get(r["tds_line_no"])
            if line is None or line.ledger_id != payable_of.get(r["nature_key"]) or line.credit != r["tds_amount"].quantize(Decimal("0.01")) or line.debit != 0:
                errors.append(ValidationError(
                    "T-13", f"Item {r['item_no']}: the tax line of the voucher does not match the calculated tax {format_inr(r['tds_amount'])}; "
                    "return the voucher to draft and save it again.", r["item_no"]))
    return errors


# ============================================================================================== register, position


def quarter_range(fy_start: date, quarter: int) -> tuple[date, date]:
    """Indian FY quarter: Q1 = first three months from the year start ... Q4 = Jan-Mar."""
    month0 = fy_start.month - 1 + 3 * (quarter - 1)
    start = date(fy_start.year + month0 // 12, month0 % 12 + 1, 1)
    end_month0 = month0 + 3
    end_first = date(fy_start.year + end_month0 // 12, end_month0 % 12 + 1, 1)
    return start, end_first.fromordinal(end_first.toordinal() - 1)


def register(conn: Connection, client_id: object, *, financial_year_id: object | None, quarter: int | None, nature_key: str | None,
             deductee_ledger_id: object | None, deposit_status: str = "all") -> dict:
    """The TDS register: items of POSTED, non-reversed vouchers with their deposit position (challan allocations)."""
    from app.services.errors import ServiceError

    if deposit_status not in ("all", "deposited", "short", "undeposited"):
        raise ServiceError("invalid_filter", "deposit_status must be all, deposited, short or undeposited.")
    qs = qe = None
    if quarter is not None:
        if financial_year_id is None or quarter not in (1, 2, 3, 4):
            raise ServiceError("invalid_filter", "A quarter (1 to 4) needs a financial year.")
        fy = tdb.financial_year(conn, client_id, financial_year_id)
        if fy is None:
            raise ServiceError("not_found", "Financial year not found.")
        qs, qe = quarter_range(fy[0], quarter)
    rows = tdb.register_rows(conn, client_id, fy_id=financial_year_id, nature_key=nature_key, deductee=deductee_ledger_id,
                             quarter_start=qs, quarter_end=qe)
    out = []
    totals = {"payment_amount": ZERO, "taxable_base": ZERO, "tds_amount": ZERO, "deposited": ZERO, "balance": ZERO}
    used = []
    cents = Decimal("0.01")
    for r in rows:
        tax, dep = r["tds_amount"].quantize(cents), r["deposited"].quantize(cents)
        state = "undeposited" if dep == 0 else ("deposited" if dep >= tax else "short")
        if deposit_status != "all" and state != deposit_status:
            continue
        if r["rule_status"] is not None:
            used.append(("rate", r["rule_status"], r["rule_source"]))
        out.append({
            "item_id": str(r["item_id"]), "voucher_id": str(r["voucher_id"]), "voucher_number": r["voucher_number"],
            "voucher_date": r["voucher_date"].isoformat(), "deductee_ledger_id": str(r["deductee_ledger_id"]),
            "deductee_name": r["deductee_name"], "pan": r["pan"], "nature_key": r["nature_key"], "section_ref": r["section_ref"],
            "event_date": r["event_date"].isoformat(), "payment_amount": f"{r['payment_amount']:.2f}",
            "taxable_base": f"{r['taxable_base']:.2f}", "rate_applied": _rate_text(r["rate_applied"]), "rate_reason": r["rate_reason"],
            "tds_amount": f"{tax:.2f}", "deposited": f"{dep:.2f}", "balance": f"{tax - dep:.2f}",
            "due_date": None, "deposited_on": None if r["deposited_on"] is None else r["deposited_on"].isoformat(), "days_late": None,
            "kind": r["kind"], "act": r["act"],
        })
        totals["payment_amount"] += r["payment_amount"].quantize(cents)
        totals["taxable_base"] += r["taxable_base"].quantize(cents)
        totals["tds_amount"] += tax
        totals["deposited"] += dep
        totals["balance"] += tax - dep
    return {"rows": out, "totals": {k: f"{v:.2f}" for k, v in totals.items()}, "rule_status": tds_calc.rule_status_of(used)}


def by_deductee(conn: Connection, client_id: object, financial_year_id: object) -> list[dict]:
    return [
        {"deductee_ledger_id": str(r["deductee_ledger_id"]), "deductee_name": r["deductee_name"], "nature_key": r["nature_key"],
         "cumulative_amount": f"{r['cumulative_amount']:.2f}", "tax_deducted": f"{r['tax_deducted']:.2f}",
         "threshold": None if r["threshold"] is None else f"{r['threshold']:.2f}",
         "threshold_crossed_on": None if r["threshold_crossed_on"] is None else r["threshold_crossed_on"].isoformat()}
        for r in tdb.by_deductee(conn, client_id, financial_year_id)
    ]


def threshold_position(conn: Connection, client_id: object, deductee_ledger_id: object, nature_key: str, on: date) -> dict | list[ValidationError]:
    """The deductee's position for the entry screen; a list of rule errors (T-02 / T-01) when it cannot be worked out."""
    from app.services.errors import ServiceError

    deductees, _, _ = tdb.load_deductees(conn, client_id, [deductee_ledger_id])
    deductee = deductees.get(deductee_ledger_id)
    if deductee is None:
        raise ServiceError("not_found", "The party is not set up as a deductee.")
    fy = tdb.financial_year_of(conn, client_id, on)
    if fy is None:
        return [ValidationError("T-01", f"The date {_fmt(on)} is not inside any financial year of this client.")]
    natures = tdb.load_natures(conn)
    if nature_key not in natures:
        raise ServiceError("not_found", f"Nature '{nature_key}' not found.")
    rule = tds_calc.pick_rate_rule(tdb.load_rates(conn, [nature_key]), nature_key, tds_calc.deductee_group(deductee.deductee_type), on)
    if rule is None:
        return [ValidationError("T-02", f"No rule for {natures[nature_key].description} on {_fmt(on)}.")]
    prior = tdb.load_priors(conn, client_id, [deductee_ledger_id], [nature_key], [fy[0]]).get((deductee_ledger_id, nature_key, fy[0]))
    cumulative = ZERO if prior is None else prior.cumulative_amount
    tax = ZERO if prior is None else prior.tax_deducted
    annual = rule.annual_threshold
    return {
        "financial_year_id": str(fy[0]), "cumulative_amount": f"{cumulative:.2f}", "tax_deducted": f"{tax:.2f}",
        "single_threshold": None if rule.single_payment_threshold is None else f"{rule.single_payment_threshold:.2f}",
        "monthly_threshold": None if rule.monthly_threshold is None else f"{rule.monthly_threshold:.2f}",
        "annual_threshold": None if annual is None else f"{annual:.2f}",
        "headroom": None if annual is None else f"{max(ZERO, annual - cumulative):.2f}",
        "rule_status": tds_calc.rule_status_of([("rate", rule.verification_status, rule.source_reference)]),
    }
