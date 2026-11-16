"""Stock movements of invoice vouchers (Phase 5, package C): rules at save / approve / post, movements written at posting,
mirror movements at reversal, the stock preview, the `stock` part of a voucher response.

Services take a SQLAlchemy Connection and never commit. S-01 (no negative stock) is checked over the WHOLE chronology of the
financial year by the valuation engine (package B) with the voucher's movements added, so a backdated entry cannot hide a gap (S-19).
Nothing here computes a cost: outward cost comes from the engine, a purchase's value from engine/inventory_costing (S-14).
The hooks of services/inventory_hooks.py call these functions, so services/vouchers.py needs no inventory knowledge.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection

from app.db import repositories_inventory_movements as repo
from app.engine.inventory_types import (
    INWARD_KINDS,
    Movement,
    MovementKind,
    NegativeStockMode,
    ValuationMethod,
)
from app.engine.inventory_valuation import compute_valuation
from app.engine.inventory_voucher import (
    ItemFacts,
    LineFacts,
    PlannedMovement,
    StockLineIn,
    plan_stock,
)
from app.engine.models import ValidationError, VoucherDraft
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError

K = MovementKind
STOCK_TYPES = frozenset({"sales", "purchase", "credit_note", "debit_note"})


@dataclass
class Check:
    """Result of checking the stock side of one voucher."""

    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    movements: list[dict] = field(default_factory=list)   # preview rows
    stock_after: list[dict] = field(default_factory=list)
    plan: list[PlannedMovement] = field(default_factory=list)
    item_ids: list[str] = field(default_factory=list)


# ================================================================================================== facts


def _lines_of_draft(draft: VoucherDraft) -> list[LineFacts]:
    if draft.gst is None or draft.gst_result is None:
        return []
    lines = []
    for entry, tax in zip(draft.gst.items, draft.gst_result.items, strict=True):
        lines.append(LineFacts(
            tax.item_line_no, None if entry.item_id is None else str(entry.item_id), entry.quantity,
            entry.uqc, entry.hsn_sac, tax.taxable_value, tax.cgst, tax.sgst, tax.igst, tax.cess, tax.tax_in_cost))
    return lines


def _plan(conn: Connection, client_id: object, vtype: str, lines: list[LineFacts], stock: dict[int, StockLineIn]):
    """-> (plan, items, godown names). One query for the items; the rest only when there is something to decide."""
    items = repo.stock_item_facts(conn, client_id, [x.item_id for x in lines if x.item_id])
    if not items and not stock:
        return plan_stock(vtype, [], {}, {}, {}, {}), items, {}
    godowns = repo.godowns_of(conn, client_id)
    wanted = [s.original_movement_id for s in stock.values() if s.original_movement_id]
    originals = repo.original_facts(conn, client_id, wanted) if wanted else {}
    plan = plan_stock(vtype, lines, stock, items, {g: v[1] for g, v in godowns.items()}, originals)
    return plan, items, godowns


# ============================================================================================ S-01 chronology


def _rewrite(message: str, items: dict[str, ItemFacts], godowns: dict[str, tuple[str, bool]], item_id, godown_id) -> str:
    if item_id is not None and str(item_id) in items:
        message = message.replace(str(item_id), items[str(item_id)].name)
    if godown_id is not None and str(godown_id) in godowns:
        message = message.replace(str(godown_id), godowns[str(godown_id)][0])
    return message


def _chronology(
    conn: Connection, client_id: object, fy: repo.YearPolicy, new: list[Movement], line_of: dict[str, int | None],
    items: dict[str, ItemFacts], godowns: dict[str, tuple[str, bool]], *, rule: str,
) -> tuple[list[ValidationError], list[ValidationError], list]:
    """Run the valuation engine over the year's movements of the touched items plus `new`.
    -> (errors, warnings, costed movements of the new ones). `rule` renames the rule id ('S-17' for a reversal)."""
    touched = sorted({m.item_id for m in new})
    existing = repo.load_movements(conn, client_id, fy.financial_year_id, item_ids=touched)
    opening = repo.load_opening(conn, client_id, fy.financial_year_id, touched)
    result = compute_valuation(fy.policy, fy.start_date, fy.end_date, opening, existing + new)
    errors, warnings = [], []
    warn_mode = fy.policy.negative_stock_mode == NegativeStockMode.WARN
    for e in result.errors:
        if e.item_id is not None and str(e.item_id) not in touched:
            continue
        if warn_mode and e.rule_id == "S-01" and e.severity == "error":
            continue  # "cannot be costed" companion of a warning: the finding itself is the warning
        text = _rewrite(e.message, items, godowns, e.item_id, e.godown_id)
        line_no = line_of.get(str(e.movement_id))
        out = ValidationError(rule if rule == "S-17" else e.rule_id, text, line_no)
        (warnings if e.severity == "warning" else errors).append(out)
    ids = {m.movement_id for m in new}
    return errors, warnings, [c for c in result.costed if c.movement_id in ids]


def _stock_after(conn: Connection, client_id: object, fy: repo.YearPolicy, new: list[Movement], items, godowns) -> list[dict]:
    touched = sorted({m.item_id for m in new})
    on_hand: dict[tuple[str, str], Decimal] = {}
    for o in repo.load_opening(conn, client_id, fy.financial_year_id, touched):
        on_hand[(o.item_id, o.godown_id)] = on_hand.get((o.item_id, o.godown_id), Decimal(0)) + o.quantity
    for m in repo.load_movements(conn, client_id, fy.financial_year_id, item_ids=touched) + new:
        sign = 1 if m.kind in INWARD_KINDS else -1
        on_hand[(m.item_id, m.godown_id)] = on_hand.get((m.item_id, m.godown_id), Decimal(0)) + sign * m.quantity
    return [{"item_id": i, "item_name": items[i].name if i in items else None, "godown_id": g,
             "godown_name": godowns[g][0] if g in godowns else None, "quantity": q}
            for (i, g), q in sorted(on_hand.items()) if (i, g) in {(m.item_id, m.godown_id) for m in new}]


# ================================================================================================ the check


def _evaluate(conn: Connection, client_id: object, vtype: str, vdate: date, lines: list[LineFacts],
              stock: dict[int, StockLineIn], *, chronology: bool) -> Check:
    check = Check()
    if vtype not in STOCK_TYPES or (not lines and not stock):
        return check
    plan, items, godowns = _plan(conn, client_id, vtype, lines, stock)
    check.errors.extend(plan.errors)
    check.plan = plan.movements
    check.item_ids = sorted({m.item_id for m in plan.movements})
    if not plan.movements or plan.errors:
        return check
    fy = repo.year_policy_on(conn, client_id, vdate)
    if fy is None:
        return check  # V-06 reports a date outside every financial year
    if fy.policy is None:
        check.errors.append(ValidationError(
            "S-04", "The inventory method (FIFO / weighted average) and the negative stock rule are not set for this financial "
                    "year. Set the inventory policy before entering stock vouchers."))
        return check
    if not chronology:
        return check
    seq = repo.max_seq(conn)
    new, line_of = [], {}
    for n, m in enumerate(plan.movements, start=1):
        temp = f"new-{n}"
        new.append(Movement(temp, seq + n, vdate, m.item_id, m.godown_id, m.kind, m.quantity, m.value, m.original_movement_id))
        line_of[temp] = m.item_line_no
    errors, warnings, costed = _chronology(conn, client_id, fy, new, line_of, items, godowns, rule="S-01")
    check.errors.extend(errors)
    check.warnings.extend(warnings)
    cost_of = {c.movement_id: c.value for c in costed}
    periodic = fy.policy.method == ValuationMethod.WA_PERIODIC
    for temp, m in zip(line_of, plan.movements, strict=True):
        if m.kind == K.PURCHASE:
            cost = m.value
        elif periodic or temp not in cost_of:
            cost = None  # periodic average is known only at period end; an uncostable item has no cost (never guessed)
        else:
            cost = cost_of[temp]
        check.movements.append({"item_line_no": m.item_line_no, "item_id": m.item_id, "godown_id": m.godown_id,
                                "kind": m.kind.value, "quantity": m.quantity, "cost": cost})
    check.stock_after = _stock_after(conn, client_id, fy, new, items, godowns)
    return check


def check_draft(conn: Connection, client_id: object, draft: VoucherDraft, *, chronology: bool = False) -> Check:
    """Rules of a draft after the GST expansion. At save (chronology=False): S-02, S-03, S-04, S-06, S-07, S-12.
    The preview adds S-01 over the whole chronology."""
    stock = {s.item_line_no: s for s in draft.stock}
    return _evaluate(conn, client_id, draft.voucher_type, draft.voucher_date, _lines_of_draft(draft), stock, chronology=chronology)


def check_stored(conn: Connection, record, *, lock: bool = False) -> Check:
    """The same rules for a saved voucher (approve / post), with S-01 over the whole chronology."""
    if record.reverses_voucher_id is not None or record.voucher_type not in STOCK_TYPES:
        return Check()
    lines = repo.stored_item_lines(conn, record.id)
    if not lines:
        return Check()
    stock = repo.stored_stock_lines(conn, record.id)
    if lock:
        items = repo.stock_item_facts(conn, record.client_id, [x.item_id for x in lines])
        repo.lock_items(conn, record.client_id, list(items))
    return _evaluate(conn, record.client_id, record.voucher_type, record.voucher_date, lines, stock, chronology=True)


def revalidate(conn: Connection, record) -> list[ValidationError]:
    """Approve / post: every stock rule again. Negative stock in `block` mode is raised as `negative_stock` (422) when it is the
    only problem; in `warn` mode it is only a warning (see preview)."""
    check = check_stored(conn, record, lock=True)
    if check.errors and all(e.rule_id == "S-01" for e in check.errors):
        raise ServiceError("negative_stock", "; ".join(e.message for e in check.errors),
                           [{"rule_id": e.rule_id, "message": e.message, "line_no": e.line_no} for e in check.errors])
    return check.errors


def preview(conn: Connection, draft: VoucherDraft) -> Check:
    return check_draft(conn, draft.client_id, draft, chronology=True)


# ================================================================================================ persist / read


def persist(conn: Connection, client_id: object, voucher_id: object, draft: VoucherDraft) -> None:
    """Write voucher_stock_lines of a saved draft: a Credit / Debit Note row per stock block, a Sales / Purchase row only when a
    godown other than the default was named. Call after the item rows exist."""
    rows = []
    if draft.stock:
        stock = {s.item_line_no: s for s in draft.stock}
        plan, _, _ = _plan(conn, client_id, draft.voucher_type, _lines_of_draft(draft), stock)
        if plan.errors:  # the caller validated first; never write a half-decided row
            raise VoucherRuleError(plan.errors)
        for m in plan.movements:
            block = stock[m.item_line_no]
            if block.godown_id or block.original_movement_id:
                rows.append((m.item_line_no, m.godown_id, block.original_movement_id))
    repo.replace_stock_lines(conn, client_id, voucher_id, rows)


def stock_part(conn: Connection, client_id: object, voucher_id: object) -> list[dict] | None:
    """The `stock` block of each item line for the voucher response: from the posted movements, else as it will be posted."""
    facts = repo.voucher_facts(conn, client_id, voucher_id)
    if facts is None or facts.voucher_type not in STOCK_TYPES or facts.reverses_voucher_id is not None:
        return None
    moved = repo.voucher_movements(conn, voucher_id)
    if moved:
        return [{"item_line_no": m["item_line_no"], "godown_id": m["godown_id"], "godown_name": m["godown_name"],
                 "kind": m["kind"], "quantity": f"{m['quantity']:.3f}",
                 "original_movement_id": None if m["ref_movement_id"] is None else str(m["ref_movement_id"]),
                 "movement_id": str(m["id"])} for m in moved]
    lines = repo.stored_item_lines(conn, voucher_id)
    if not lines:
        return None
    plan, _, godowns = _plan(conn, client_id, facts.voucher_type, lines, repo.stored_stock_lines(conn, voucher_id))
    if not plan.movements:
        return None
    return [{"item_line_no": m.item_line_no, "godown_id": m.godown_id, "godown_name": godowns[m.godown_id][0],
             "kind": m.kind.value, "quantity": f"{m.quantity:.3f}", "original_movement_id": m.original_movement_id,
             "movement_id": None} for m in plan.movements]


# ========================================================================================= post and reverse


def _direction(kind: MovementKind) -> str:
    return "in" if kind in INWARD_KINDS else "out"


def on_post(conn: Connection, client_id: object, voucher_id: object, actor: str) -> None:
    """S-05: append the movements of the item lines of a posted Sales / Purchase / Credit Note / Debit Note, in the same
    transaction. The rules were checked just before (approve / post); a failure here aborts the posting."""
    facts = repo.voucher_facts(conn, client_id, voucher_id)
    if facts is None or facts.voucher_type not in STOCK_TYPES or facts.reverses_voucher_id is not None:
        return
    lines = repo.stored_item_lines(conn, voucher_id)
    if not lines:
        return
    plan, _, _ = _plan(conn, client_id, facts.voucher_type, lines, repo.stored_stock_lines(conn, voucher_id))
    if plan.errors:
        raise VoucherRuleError(plan.errors)
    if not plan.movements:
        return
    rows = [{
        "id": uuid.uuid4(), "client_id": client_id, "financial_year_id": facts.financial_year_id, "item_id": m.item_id,
        "godown_id": m.godown_id, "movement_date": facts.voucher_date, "kind": m.kind.value, "direction": _direction(m.kind),
        "quantity": m.quantity, "value": m.value, "voucher_id": voucher_id, "item_line_no": m.item_line_no,
        "ref_movement_id": m.original_movement_id, "created_by": actor,
    } for m in plan.movements]
    repo.insert_movements(conn, rows)
    audit.log(conn, AuditEntry(client_id, actor, "stock_posted", "voucher", voucher_id, new={
        "movements": [{"kind": r["kind"], "item_id": str(r["item_id"]), "godown_id": str(r["godown_id"]),
                       "quantity": f"{r['quantity']:.3f}", "value": None if r["value"] is None else f"{r['value']:.2f}"}
                      for r in rows]}))


def _mirrors(originals: list[dict], vdate: date, seq: int) -> list[Movement]:
    out = []
    for n, o in enumerate(originals, start=1):
        kind = K.REVERSAL_IN if o["direction"] == "out" else K.REVERSAL_OUT
        out.append(Movement(f"new-{n}", seq + n, vdate, str(o["item_id"]), str(o["godown_id"]), kind, o["quantity"], None,
                            str(o["id"])))
    return out


def check_reverse(conn: Connection, client_id: object, original_id: object, reversal_date: date) -> None:
    """S-17, BEFORE the reversal voucher is written: the mirror movements must not make stock negative, must stay in the
    original's financial year, and a sale / purchase with live returns cannot be reversed. Raises VoucherRuleError."""
    originals = repo.voucher_movements(conn, original_id)
    if not originals:
        return
    items = repo.stock_item_facts(conn, client_id, [o["item_id"] for o in originals])
    repo.lock_items(conn, client_id, list(items))
    fy = repo.year_policy_on(conn, client_id, reversal_date)
    if fy is None or fy.financial_year_id != str(originals[0]["financial_year_id"]):
        raise VoucherRuleError([ValidationError(
            "S-17", "The stock of this voucher can be reversed only on a date inside the financial year of the original, "
                    "because stock is kept year by year.")])
    if fy.policy is None:
        raise VoucherRuleError([ValidationError("S-04", "The inventory policy of this financial year is not set.")])
    if repo.live_returns_of(conn, [o["id"] for o in originals]):
        raise VoucherRuleError([ValidationError(
            "S-17", "Goods of this voucher have already been returned by a Credit / Debit Note; reverse that note first.")])
    new = _mirrors(originals, reversal_date, repo.max_seq(conn))
    godowns = repo.godowns_of(conn, client_id)
    errors, _, _ = _chronology(conn, client_id, fy, new, {}, items, godowns, rule="S-17")
    if errors:
        raise VoucherRuleError([ValidationError(
            "S-17", "The reversal is blocked: " + " ".join(e.message.rstrip(".") + "." for e in errors))])


def on_reverse(conn: Connection, client_id: object, original_id: object, reversal_id: object, actor: str) -> None:
    """S-17: append the mirror movements (same godown and quantity, dated the reversal date, referring to the original's)."""
    originals = repo.voucher_movements(conn, original_id)
    if not originals:
        return
    facts = repo.voucher_facts(conn, client_id, reversal_id)
    rows = []
    for o in originals:
        kind = K.REVERSAL_IN if o["direction"] == "out" else K.REVERSAL_OUT
        rows.append({
            "id": uuid.uuid4(), "client_id": client_id, "financial_year_id": facts.financial_year_id, "item_id": o["item_id"],
            "godown_id": o["godown_id"], "movement_date": facts.voucher_date, "kind": kind.value, "direction": _direction(kind),
            "quantity": o["quantity"], "value": None, "voucher_id": reversal_id, "item_line_no": None,
            "ref_movement_id": o["id"], "created_by": actor,
        })
    repo.insert_movements(conn, rows)
    audit.log(conn, AuditEntry(client_id, actor, "stock_reversed", "voucher", original_id, new={
        "reversal_voucher_id": str(reversal_id),
        "movements": [{"kind": r["kind"], "item_id": str(r["item_id"]), "godown_id": str(r["godown_id"]),
                       "quantity": f"{r['quantity']:.3f}"} for r in rows]}))


# ============================================================================================= returnable


def returnable(conn: Connection, client_id: object, item_id: object, on: date | None) -> list[dict]:
    return repo.returnable(conn, client_id, item_id, on)
