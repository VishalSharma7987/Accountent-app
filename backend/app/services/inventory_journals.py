"""Stock journal use-cases (Phase 5, package D): transfer between godowns and write-off.
Rules S-10, S-11 (+ S-01, S-02, S-03, S-07, S-17, S-19, S-20 through the engine). Draft -> Approved -> Posted -> Reversed;
the number SJ/2026-27/0001 is assigned at posting (gapless); posted journals are never edited, only reversed (mirror
movements). Services never commit; every change is audit-logged. A transfer changes quantity between godowns, never value.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import date

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_inventory_journals as jr
from app.db import repositories_inventory_masters as inv
from app.engine import inventory_journals as engine
from app.engine.inventory_journals import JournalFacts, JournalInput, JournalLineInput
from app.engine.inventory_types import (
    InventoryPolicy,
    Movement,
    NegativeStockMode,
    StockError,
    ValuationMethod,
)
from app.engine.models import ValidationError
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor


@dataclass(frozen=True)
class JournalView:
    row: jr.JournalRow
    lines: list[jr.JournalLineRow]
    warnings: list[StockError] = field(default_factory=list)


def _snap(row: jr.JournalRow, lines: list[jr.JournalLineRow]) -> dict:
    return {
        "journal_type": row.journal_type, "journal_number": row.journal_number, "journal_date": str(row.journal_date),
        "narration": row.narration, "reason_code": row.reason_code, "reason_note": row.reason_note, "status": row.status,
        "financial_year_id": str(row.financial_year_id),
        "lines": [{"line_no": x.line_no, "item_id": str(x.item_id), "from_godown_id": str(x.from_godown_id),
                   "to_godown_id": None if x.to_godown_id is None else str(x.to_godown_id), "quantity": str(x.quantity)}
                  for x in lines],
    }


def _client(conn: Connection, client_id: object) -> None:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")


def _load(conn: Connection, client_id: object, journal_id: object, *, lock: bool = False) -> JournalView:
    _client(conn, client_id)
    row = jr.get_journal(conn, client_id, journal_id, lock=lock)
    if row is None:
        raise ServiceError("not_found", "Stock journal not found for this client.")
    return JournalView(row, jr.lines_of(conn, client_id, [row.id])[row.id])


def _facts(conn: Connection, client_id: object, lines: list[JournalLineInput]) -> JournalFacts:
    item_ids = list({x.item_id for x in lines if _is_uuid(x.item_id)})
    godown_ids = list({g for x in lines for g in (x.from_godown_id, x.to_godown_id) if _is_uuid(g)})
    return JournalFacts(
        items=jr.item_activity(conn, client_id, item_ids), godowns=jr.godown_activity(conn, client_id, godown_ids),
        fy_ranges=[(s, e) for _, s, e in jr.financial_years(conn, client_id)], periods=jr.periods(conn, client_id))


def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
        return value is not None
    except ValueError:
        return False


def _as_input(row: jr.JournalRow, lines: list[jr.JournalLineRow]) -> JournalInput:
    return JournalInput(row.journal_type, row.journal_date, row.narration, row.reason_code, row.reason_note,
                        [JournalLineInput(x.item_id, x.from_godown_id, x.to_godown_id, x.quantity) for x in lines])


def _fy_for(conn: Connection, client_id: object, on: date):
    fy = repo.financial_year_for_date(conn, client_id, on)
    if fy is None:  # unreachable after _check (V-06), kept as a refusal rather than an assumption
        raise VoucherRuleError([ValidationError("V-06", "The journal date is not inside any financial year of this client.")])
    return fy


def _check(conn: Connection, client_id: object, inp: JournalInput) -> list[engine.JournalLine]:
    """Pure rules (S-10, S-02, S-03, S-07, V-06, V-07, V-09) against the client's data; raises VoucherRuleError."""
    normal: list[JournalLineInput] = []
    for line in inp.lines:  # ids that are not UUIDs can never exist
        if not (_is_uuid(line.item_id) and _is_uuid(line.from_godown_id)):
            raise VoucherRuleError([ValidationError("S-10", "Every line needs an item and a godown.")])
        if line.to_godown_id is not None and not _is_uuid(line.to_godown_id):
            raise VoucherRuleError([ValidationError("S-07", "The destination godown was not found for this client.")])
        normal.append(JournalLineInput(uuid.UUID(str(line.item_id)), uuid.UUID(str(line.from_godown_id)),
                                       None if line.to_godown_id is None else uuid.UUID(str(line.to_godown_id)), line.quantity))
    inp = replace(inp, lines=normal)
    errors, lines = engine.validate_journal(inp, _facts(conn, client_id, inp.lines))
    if errors:
        raise VoucherRuleError(errors)
    return lines


def _policy(conn: Connection, client_id: object, fy_id: object) -> InventoryPolicy:
    row = inv.policy_row(conn, client_id, fy_id)
    if row is None:
        raise ServiceError("no_policy", "The inventory policy (valuation method) is not set for this financial year (S-04).")
    return InventoryPolicy(ValuationMethod(row.valuation_method), NegativeStockMode(row.negative_stock_mode))


def _stock_findings(conn: Connection, client_id: object, journal: jr.JournalRow, policy: InventoryPolicy,
                    new: list[Movement], item_ids: set, fy_range: tuple[date, date]) -> list[StockError]:
    ids = list(item_ids)
    existing = jr.load_movements(conn, client_id, journal.financial_year_id, ids)
    opening = jr.load_opening(conn, client_id, journal.financial_year_id, ids)
    return engine.check_stock_chain(policy, fy_range[0], fy_range[1], opening, existing, new, item_ids,
                                    jr.names(conn, client_id, ids, _godowns_of(existing, new)))


def _godowns_of(*groups: list[Movement]) -> list[object]:
    return list({m.godown_id for g in groups for m in g})


def _fy_range(conn: Connection, client_id: object, fy_id: object) -> tuple[date, date]:
    fy = repo.get_financial_year(conn, client_id, fy_id)
    return (fy.start_date, fy.end_date)  # type: ignore[union-attr]


def _planned(conn: Connection, view: JournalView, base_seq: int) -> list[Movement]:
    lines = [engine.JournalLine(x.line_no, x.item_id, x.from_godown_id, x.to_godown_id, x.quantity) for x in view.lines]
    plan = engine.planned_movements(view.row.journal_type, lines)
    return [engine.new_movement(view.row.journal_date, base_seq + i, p.kind, p.item_id, p.godown_id, p.quantity)
            for i, p in enumerate(plan, start=1)]


def _block_or_warn(findings: list[StockError], code: str, what: str) -> list[StockError]:
    """S-01: an error finding stops the action (code `negative_stock` / `journal_reversal_blocked`); warnings are returned."""
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        raise ServiceError(code, f"{what} " + " ".join(e.message + "." for e in errors),
                           [{"rule_id": e.rule_id, "message": e.message, "item_id": str(e.item_id), "severity": e.severity}
                            for e in errors])
    return [f for f in findings if f.severity == "warning"]


# ============================================================================================ create / update / delete


def create_journal(conn: Connection, client_id: object, *, journal_type: str, journal_date: date, narration: str,
                   reason_code: str | None, reason_note: str | None, lines: list[JournalLineInput], actor: str) -> JournalView:
    actor = require_actor(actor)
    _client(conn, client_id)
    inp = JournalInput(journal_type, journal_date, narration, reason_code, reason_note, lines)
    checked = _check(conn, client_id, inp)
    fy = _fy_for(conn, client_id, journal_date)
    journal_id = uuid.uuid4()
    jr.insert_journal(conn, client_id, journal_id, fy.id, journal_type, journal_date, narration.strip(),
                      reason_code, (reason_note or "").strip() or None, actor)
    jr.replace_lines(conn, client_id, journal_id, checked)
    view = _load(conn, client_id, journal_id)
    audit.log(conn, AuditEntry(client_id, actor, "create", "stock_journal", journal_id, new=_snap(view.row, view.lines)))
    return view


def update_journal(conn: Connection, client_id: object, journal_id: object, *, journal_type: str, journal_date: date,
                   narration: str, reason_code: str | None, reason_note: str | None, lines: list[JournalLineInput],
                   actor: str) -> JournalView:
    actor = require_actor(actor)
    old = _load(conn, client_id, journal_id, lock=True)
    _require(old.row.status, "update")
    if journal_type != old.row.journal_type:
        raise VoucherRuleError([ValidationError("S-10", "The type of a stock journal cannot be changed; delete it and enter a new one.")])
    checked = _check(conn, client_id, JournalInput(journal_type, journal_date, narration, reason_code, reason_note, lines))
    fy = _fy_for(conn, client_id, journal_date)
    if fy.id != old.row.financial_year_id:
        raise VoucherRuleError([ValidationError(
            "S-20", "The date of a stock journal must stay inside its financial year; delete it and enter a new one.")])
    jr.update_header(conn, old.row.id, journal_date, narration.strip(), reason_code, (reason_note or "").strip() or None)
    jr.replace_lines(conn, client_id, old.row.id, checked)
    new = _load(conn, client_id, old.row.id)
    audit.log(conn, AuditEntry(client_id, actor, "update", "stock_journal", old.row.id, old=_snap(old.row, old.lines),
                               new=_snap(new.row, new.lines)))
    return new


def delete_journal(conn: Connection, client_id: object, journal_id: object, *, actor: str) -> None:
    actor = require_actor(actor)
    old = _load(conn, client_id, journal_id, lock=True)
    _require(old.row.status, "delete")
    jr.delete_journal(conn, old.row.id)
    audit.log(conn, AuditEntry(client_id, actor, "delete", "stock_journal", old.row.id, old=_snap(old.row, old.lines)))


def _require(status: str, action: str) -> None:
    message = engine.check_transition(status, action)
    if message:
        raise ServiceError("journal_state", message)


# =============================================================================================== reads


def get_journal(conn: Connection, client_id: object, journal_id: object) -> JournalView:
    return _load(conn, client_id, journal_id)


def list_journals(conn: Connection, client_id: object, *, financial_year_id: object | None = None, journal_type: str | None = None,
                  status: str | None = None, from_date: date | None = None, to_date: date | None = None) -> list[JournalView]:
    _client(conn, client_id)
    rows = jr.list_journals(conn, client_id, financial_year_id, journal_type, status, from_date, to_date)
    lines = jr.lines_of(conn, client_id, [r.id for r in rows])
    return [JournalView(r, lines[r.id]) for r in rows]


# ========================================================================================= approve / post / reverse


def _recheck(conn: Connection, view: JournalView) -> list[StockError]:
    """Everything that can have changed since the draft was saved: the rules again (items, godowns, period) and S-01 over the
    whole chronology with this journal's movements added (a backdated journal re-runs the chain, S-19)."""
    row = view.row
    _check(conn, row.client_id, _as_input(row, view.lines))
    policy = _policy(conn, row.client_id, row.financial_year_id)
    new = _planned(conn, view, jr.max_seq(conn))
    findings = _stock_findings(conn, row.client_id, row, policy, new, {x.item_id for x in view.lines},
                               _fy_range(conn, row.client_id, row.financial_year_id))
    return _block_or_warn(findings, "negative_stock", "Stock would go negative (S-01):")


def approve_journal(conn: Connection, client_id: object, journal_id: object, *, actor: str) -> JournalView:
    actor = require_actor(actor)
    view = _load(conn, client_id, journal_id, lock=True)
    _require(view.row.status, "approve")
    jr.lock_stock_chain(conn, client_id)
    warnings = _recheck(conn, view)
    jr.mark_approved(conn, view.row.id, actor)
    new = _load(conn, client_id, view.row.id)
    audit.log(conn, AuditEntry(client_id, actor, "approve", "stock_journal", view.row.id,
                               old={"status": "draft"}, new={"status": "approved", "approved_by": actor}))
    return replace(new, warnings=warnings)


def post_journal(conn: Connection, client_id: object, journal_id: object, *, actor: str) -> JournalView:
    actor = require_actor(actor)
    view = _load(conn, client_id, journal_id, lock=True)
    _require(view.row.status, "post")
    jr.lock_stock_chain(conn, client_id)
    warnings = _recheck(conn, view)
    row = view.row
    fy_start = _fy_range(conn, client_id, row.financial_year_id)[0]
    number = f"{engine.TYPE_CODE}/{fy_start.year}-{(fy_start.year + 1) % 100:02d}/{jr.next_number(conn, client_id, row.financial_year_id):04d}"
    jr.mark_posted(conn, row.id, number, actor)
    lines = [engine.JournalLine(x.line_no, x.item_id, x.from_godown_id, x.to_godown_id, x.quantity) for x in view.lines]
    for p in engine.planned_movements(row.journal_type, lines):
        jr.insert_movement(conn, client_id, row.financial_year_id, row.id, row.journal_date, p.kind, p.item_id, p.godown_id,
                           p.quantity, p.line_no, None, actor)
    new = _load(conn, client_id, row.id)
    audit.log(conn, AuditEntry(client_id, actor, "post", "stock_journal", row.id, old={"status": "approved"},
                               new={"status": "posted", "journal_number": number, "posted_by": actor}))
    return replace(new, warnings=warnings)


def reverse_journal(conn: Connection, client_id: object, journal_id: object, *, reason: str, actor: str,
                    reversal_date: date | None = None) -> JournalView:
    """S-11 / S-17: mark the journal reversed (reason stored) and append mirror movements dated `reversal_date` (default: the
    journal's own date). Blocked (`journal_reversal_blocked`) when the mirrors would make stock negative in block mode."""
    actor = require_actor(actor)
    view = _load(conn, client_id, journal_id, lock=True)
    row = view.row
    _require(row.status, "reverse")
    on = reversal_date or row.journal_date
    reason = (reason or "").strip()
    years = jr.financial_years(conn, client_id)
    errors = engine.validate_reversal(reason, on, journal_fy=_fy_range(conn, client_id, row.financial_year_id),
                                      fy_ranges=[(s, e) for _, s, e in years], periods=jr.periods(conn, client_id))
    if errors:
        raise VoucherRuleError(errors)
    jr.lock_stock_chain(conn, client_id)
    originals = jr.journal_movements(conn, client_id, row.id)
    mirrors = engine.mirror_movements(originals)
    base = jr.max_seq(conn)
    new = [engine.new_movement(on, base + i, m.kind, m.item_id, m.godown_id, m.quantity, m.ref_movement_id)
           for i, m in enumerate(mirrors, start=1)]
    policy = _policy(conn, client_id, row.financial_year_id)
    findings = _stock_findings(conn, client_id, row, policy, new, {m.item_id for m in originals},
                               _fy_range(conn, client_id, row.financial_year_id))
    warnings = _block_or_warn(findings, "journal_reversal_blocked", "The journal cannot be reversed because stock would go negative (S-17):")
    jr.mark_reversed(conn, row.id, reason, actor)
    for m in mirrors:
        jr.insert_movement(conn, client_id, row.financial_year_id, row.id, on, m.kind, m.item_id, m.godown_id, m.quantity, None,
                           m.ref_movement_id, actor)
    result = _load(conn, client_id, row.id)
    audit.log(conn, AuditEntry(client_id, actor, "reverse", "stock_journal", row.id, old={"status": "posted"},
                               new={"status": "reversed", "reversed_by": actor, "reverse_reason": reason,
                                    "reversal_date": str(on)}))
    return replace(result, warnings=warnings)
