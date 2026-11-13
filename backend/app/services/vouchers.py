"""Voucher lifecycle use-cases: draft -> approved -> posted -> (reversed).

Rules are checked by the engine (validate_voucher, find_possible_duplicate); this file loads the data the engine
needs, writes the result, numbers vouchers at posting and logs every state change.

Services take a SQLAlchemy Connection and never commit (the caller owns the transaction). Every rule check runs
BEFORE the first write, so a refused operation leaves nothing behind; a database error aborts the transaction and
the caller rolls it back. Posted vouchers are immutable: corrections happen only through a linked reversal
voucher. The database triggers enforce the same rules as a second line of defence.

Round trips matter (the database is remote): context and vouchers are each loaded with ONE query.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.db import repositories as repo
from app.db.repositories import ValidationContext, VoucherRecord
from app.engine import reports
from app.engine.bills import mirror_allocations
from app.engine.duplicates import duplicate_error, find_possible_duplicate
from app.engine.models import PeriodInfo, ValidationError, VoucherDraft, VoucherLine
from app.engine.money import format_inr, parse_amount
from app.engine.validation import validate_voucher
from app.services import audit, bills, cash_checks, gst_hooks
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor

TYPE_CODES = {
    "contra": "CON", "payment": "PAY", "receipt": "REC", "sales": "SAL",
    "purchase": "PUR", "credit_note": "CRN", "debit_note": "DBN", "journal": "JRN",
}
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class DraftResult:
    voucher_id: uuid.UUID | None  # None when nothing was saved
    errors: list[ValidationError]


# ================================================================================================== helpers


def _order(errors: list[ValidationError]) -> list[ValidationError]:
    return sorted(errors, key=lambda e: (e.rule_id, e.line_no is None, e.line_no or 0))


def _validate(
    conn: Connection, draft: VoucherDraft, *, is_reversal: bool = False
) -> tuple[list[ValidationError], ValidationContext]:
    ledger_ids = [x.ledger_id for x in draft.lines]
    if draft.party_ledger_id is not None:
        ledger_ids.append(draft.party_ledger_id)
    ctx = repo.load_validation_context(conn, draft.client_id, ledger_ids)
    if not ctx.client_exists:
        raise ServiceError("not_found", "Client not found.")

    def period_for(on: date) -> PeriodInfo | None:
        for p in ctx.periods:
            if p.start <= on <= p.end:
                return PeriodInfo(p.start, p.end, p.status)
        return None

    years = [(y.start_date, y.end_date) for y in ctx.years]
    return validate_voucher(draft, ctx.ledgers, ctx.groups, years, period_for, is_reversal=is_reversal), ctx


def _draft_from(record: VoucherRecord) -> VoucherDraft:
    return VoucherDraft(
        record.client_id, record.voucher_type, record.voucher_date, record.narration, record.reference_no,
        record.party_ledger_id, tuple(VoucherLine(x.ledger_id, x.debit, x.credit, x.allocations) for x in record.lines),
        record.duplicate_override_reason, record.goods_received_date,
    )


def _financial_year_id(ctx: ValidationContext, on: date) -> uuid.UUID:
    for year in ctx.years:
        if year.start_date <= on <= year.end_date:
            return year.id
    raise ServiceError("invalid_date", "The voucher date is not inside any financial year of this client.")


def _amount(raw: object) -> Decimal:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return ZERO
    return parse_amount(raw)


def _lines_snapshot(lines) -> list[dict]:
    out = []
    for n, x in enumerate(lines, start=1):
        row = {"line_no": n, "ledger_id": str(x.ledger_id), "debit": f"{_amount(x.debit):.2f}", "credit": f"{_amount(x.credit):.2f}"}
        if x.allocations:  # Phase 2: only party lines carry them, so Phase 1 snapshots are unchanged
            row["allocations"] = [
                {"kind": a.kind, "bill_ref": a.bill_ref, "amount": f"{_amount(a.amount):.2f}",
                 "due_date": None if a.due_date is None else a.due_date.isoformat()}
                for a in x.allocations
            ]
        out.append(row)
    return out


def _snapshot(draft: VoucherDraft, status: str = "draft") -> dict:
    snap = {
        "voucher_type": draft.voucher_type,
        "voucher_date": draft.voucher_date.isoformat(),
        "narration": draft.narration,
        "reference_no": draft.reference_no,
        "party_ledger_id": None if draft.party_ledger_id is None else str(draft.party_ledger_id),
        "duplicate_override_reason": draft.duplicate_override_reason,
        "status": status,
        "lines": _lines_snapshot(draft.lines),
    }
    if draft.goods_received_date is not None:  # Phase 2.1: only when entered, so older snapshots are unchanged
        snap["goods_received_date"] = draft.goods_received_date.isoformat()
    if draft.gst is not None:  # Phase 3: invoice mode
        snap["gst"] = gst_hooks.snapshot(draft)
    return snap


def _insert_lines(conn: Connection, client_id: object, voucher_id: object, draft: VoucherDraft) -> None:
    conn.execute(
        text(
            "INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, debit, credit) "
            "VALUES (:c, :v, :n, :l, :d, :cr)"
        ),
        [
            {"c": client_id, "v": voucher_id, "n": n, "l": x.ledger_id, "d": _amount(x.debit), "cr": _amount(x.credit)}
            for n, x in enumerate(draft.lines, start=1)
        ],
    )


def _insert_voucher(
    conn: Connection, draft: VoucherDraft, fy_id: object, actor: str, *, reverses_voucher_id: object | None = None
) -> uuid.UUID:
    voucher_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO vouchers (id, client_id, financial_year_id, voucher_type, voucher_date, narration, "
            "reference_no, party_ledger_id, reverses_voucher_id, duplicate_override_reason, created_by, goods_received_date) "
            "VALUES (:id, :c, :fy, :t, :d, :n, :ref, :party, :rev, :dup, :by, :grd)"
        ),
        {
            "id": voucher_id, "c": draft.client_id, "fy": fy_id, "t": draft.voucher_type, "d": draft.voucher_date,
            "n": draft.narration, "ref": draft.reference_no.strip() if draft.reference_no else None,
            "party": draft.party_ledger_id, "rev": reverses_voucher_id, "dup": draft.duplicate_override_reason,
            "by": actor, "grd": draft.goods_received_date,
        },
    )
    _insert_lines(conn, draft.client_id, voucher_id, draft)
    return voucher_id


def _lock(conn: Connection, voucher_id: object) -> VoucherRecord:
    record = repo.load_voucher(conn, voucher_id, lock=True)
    if record is None:
        raise ServiceError("not_found", "Voucher not found.")
    return record


def _log(conn: Connection, record: VoucherRecord, actor: str, action: str, old: dict | None, new: dict | None) -> None:
    audit.log(conn, AuditEntry(record.client_id, actor, action, "voucher", record.id, old=old, new=new))


def _check_duplicates(conn: Connection, draft: VoucherDraft, draft_id: object | None) -> list[ValidationError]:
    if (draft.duplicate_override_reason or "").strip():
        return []
    match = find_possible_duplicate(
        draft, repo.candidate_duplicates(conn, draft.client_id, draft.voucher_type, draft.reference_no), draft_id=draft_id
    )
    return [duplicate_error(draft, match)] if match else []


# ============================================================================================== create/update


def _validate_all(
    conn: Connection, draft: VoucherDraft, draft_id: object | None
) -> tuple[list[ValidationError], ValidationContext]:
    """Every rule that applies to a draft, ordered: the engine rules plus the duplicate check (V-10)."""
    errors, ctx = _validate(conn, draft)
    errors += bills.draft_errors(conn, draft, ctx, draft_id)  # B-01 .. B-05 (bill-wise party lines)
    return _order(errors + _check_duplicates(conn, draft, draft_id) + cash_checks.duplicate_payment_errors(conn, draft, draft_id)), ctx


def validate_draft(conn: Connection, draft: VoucherDraft, draft_id: object | None = None) -> list[ValidationError]:
    """The errors create_draft/update_draft would return for this draft, WITHOUT saving or logging anything.
    draft_id is the voucher being edited (it does not clash with itself under V-10). Used by the Excel dry run."""
    draft, gst_errors = gst_hooks.expand_invoice(conn, draft)  # Phase 3: invoice mode builds the lines
    if gst_errors:
        return _order(gst_errors)
    return _validate_all(conn, draft, draft_id)[0]


def create_draft(conn: Connection, draft: VoucherDraft, *, actor: str) -> DraftResult:
    """Validate and save a new draft. On rule errors (V-01..V-10, V-13, V-14) nothing is saved and all errors are
    returned. A possible duplicate (V-10) needs `draft.duplicate_override_reason` to be saved anyway."""
    actor = require_actor(actor)
    draft, gst_errors = gst_hooks.expand_invoice(conn, draft)  # Phase 3: invoice mode builds the lines
    if gst_errors:
        return DraftResult(None, _order(gst_errors))
    errors, ctx = _validate_all(conn, draft, None)
    if errors:
        return DraftResult(None, errors)
    voucher_id = _insert_voucher(conn, draft, _financial_year_id(ctx, draft.voucher_date), actor)
    gst_hooks.persist_invoice(conn, draft.client_id, voucher_id, draft, actor)
    bills.persist_allocations(conn, voucher_id, draft, ctx)
    audit.log(conn, AuditEntry(draft.client_id, actor, "create", "voucher", voucher_id, new=_snapshot(draft)))
    return DraftResult(voucher_id, [])


def update_draft(conn: Connection, voucher_id: object, draft: VoucherDraft, *, actor: str) -> DraftResult:
    """Replace the content of a DRAFT voucher (header and lines). Approved/posted vouchers are refused."""
    actor = require_actor(actor)
    record = _lock(conn, voucher_id)
    if record.status != "draft":
        raise ServiceError(
            "not_draft",
            f"Only a draft voucher can be edited; this voucher is {record.status}. "
            "Return an approved voucher to draft first; a posted voucher is corrected by reversing it.",
        )
    if draft.client_id != record.client_id:
        raise ServiceError("client_mismatch", "A voucher cannot be moved to another client.")
    draft, gst_errors = gst_hooks.expand_invoice(conn, draft)  # Phase 3: invoice mode builds the lines
    if gst_errors:
        return DraftResult(None, _order(gst_errors))
    errors, ctx = _validate_all(conn, draft, record.id)
    if errors:
        return DraftResult(None, errors)
    conn.execute(
        text(
            "UPDATE vouchers SET voucher_type = :t, voucher_date = :d, financial_year_id = :fy, narration = :n, "
            "reference_no = :ref, party_ledger_id = :party, duplicate_override_reason = :dup, "
            "goods_received_date = :grd WHERE id = :id"
        ),
        {
            "t": draft.voucher_type, "d": draft.voucher_date, "fy": _financial_year_id(ctx, draft.voucher_date),
            "n": draft.narration, "ref": draft.reference_no.strip() if draft.reference_no else None,
            "party": draft.party_ledger_id, "dup": draft.duplicate_override_reason, "grd": draft.goods_received_date,
            "id": record.id,
        },
    )
    conn.execute(text("DELETE FROM voucher_lines WHERE voucher_id = :id"), {"id": record.id})
    _insert_lines(conn, record.client_id, record.id, draft)  # deleting the lines cascaded to their allocations
    gst_hooks.persist_invoice(conn, record.client_id, record.id, draft, actor)
    bills.persist_allocations(conn, record.id, draft, ctx)
    _log(conn, record, actor, "update", _snapshot(_draft_from(record)), _snapshot(draft))
    return DraftResult(record.id, [])


def delete_draft(conn: Connection, voucher_id: object, *, actor: str) -> None:
    actor = require_actor(actor)
    record = _lock(conn, voucher_id)
    if record.status != "draft":
        raise ServiceError("not_draft", f"Only a draft voucher can be deleted; this voucher is {record.status}.")
    conn.execute(text("DELETE FROM voucher_lines WHERE voucher_id = :id"), {"id": record.id})
    conn.execute(text("DELETE FROM vouchers WHERE id = :id"), {"id": record.id})
    _log(conn, record, actor, "delete", _snapshot(_draft_from(record)), None)


# ============================================================================================ approve / post


def _revalidate(conn: Connection, record: VoucherRecord) -> ValidationContext:
    draft, is_reversal = _draft_from(record), record.reverses_voucher_id is not None
    errors, ctx = _validate(conn, draft, is_reversal=is_reversal)
    errors += bills.draft_errors(conn, draft, ctx, record.id, is_reversal=is_reversal)
    errors += gst_hooks.revalidate_invoice(conn, record)  # Phase 3: G-26 (a tampered invoice cannot be approved / posted)
    if errors:
        raise VoucherRuleError(_order(errors))
    return ctx


def _approve_locked(conn: Connection, record: VoucherRecord, actor: str) -> None:
    conn.execute(
        text("UPDATE vouchers SET status = 'approved', approved_by = :by, approved_at = now() WHERE id = :id"),
        {"by": actor, "id": record.id},
    )
    _log(conn, record, actor, "approve", {"status": "draft"}, {"status": "approved"})


def approve(conn: Connection, voucher_id: object, *, actor: str) -> None:
    """draft -> approved, after checking every rule again (a period may have been locked since)."""
    actor = require_actor(actor)
    record = _lock(conn, voucher_id)
    if record.status != "draft":
        raise ServiceError("not_draft", f"Only a draft voucher can be approved (this one is {record.status}).")
    _revalidate(conn, record)
    cash_checks.raise_if_cash_negative(conn, record.client_id, record.voucher_date, record.lines)  # C-01
    _approve_locked(conn, record, actor)


def return_to_draft(conn: Connection, voucher_id: object, *, actor: str) -> None:
    """approved -> draft, so the voucher can be edited again (logged)."""
    actor = require_actor(actor)
    record = _lock(conn, voucher_id)
    if record.status != "approved":
        raise ServiceError("not_approved", f"Only an approved voucher can be returned to draft (this one is {record.status}).")
    conn.execute(
        text("UPDATE vouchers SET status = 'draft', approved_by = NULL, approved_at = NULL WHERE id = :id"),
        {"id": record.id},
    )
    _log(conn, record, actor, "return_to_draft", {"status": "approved"}, {"status": "draft"})


def _fy_label(start: date) -> str:
    return f"{start.year}-{(start.year + 1) % 100:02d}"


def _check_openings(conn: Connection, record: VoucherRecord) -> None:
    check = reports.check_openings(repo.openings_for_year(conn, record.client_id, record.financial_year_id).values())
    if not check.is_balanced:
        raise ServiceError(
            "openings_unbalanced",
            f"Opening balances do not balance: Debit {format_inr(check.total_debit)} and Credit "
            f"{format_inr(check.total_credit)} are not equal (difference {format_inr(check.difference.amount)} "
            f"{check.difference.side}). Fix them before posting.",
        )


def _post_locked(conn: Connection, record: VoucherRecord, actor: str) -> str:
    """Number the voucher and mark it posted. The sequence row is locked until the transaction ends, so numbers
    are gapless and concurrent posts queue up; a rollback gives the number back."""
    last = conn.execute(
        text(
            "INSERT INTO voucher_number_sequences (client_id, financial_year_id, voucher_type, last_number) "
            "VALUES (:c, :fy, :t, 1) ON CONFLICT (client_id, financial_year_id, voucher_type) "
            "DO UPDATE SET last_number = voucher_number_sequences.last_number + 1 RETURNING last_number"
        ),
        {"c": record.client_id, "fy": record.financial_year_id, "t": record.voucher_type},
    ).scalar_one()
    number = f"{TYPE_CODES[record.voucher_type]}/{_fy_label(record.financial_year_start)}/{last:04d}"
    gst_hooks.check_number(conn, record, number)  # Phase 3: G-23 (GST documents: at most 16 characters)
    conn.execute(
        text(
            "UPDATE vouchers SET status = 'posted', voucher_number = :n, posted_by = :by, posted_at = now() "
            "WHERE id = :id"
        ),
        {"n": number, "by": actor, "id": record.id},
    )
    # Run the database's own posting check (>= 2 lines, Dr = Cr, date inside the year) now instead of at commit.
    # The constraint stays IMMEDIATE for the rest of the transaction, which is harmless: lines always exist first.
    conn.execute(text("SET CONSTRAINTS vouchers_posting_check, vouchers_allocation_check IMMEDIATE"))
    _log(conn, record, actor, "post", {"status": "approved"}, {"status": "posted", "voucher_number": number})
    return number


def post(conn: Connection, voucher_id: object, *, actor: str) -> str:
    """approved -> posted. Checks V-11, every rule again, and that the client's opening balances balance; assigns
    the next gapless number '<TYPE>/<YYYY-YY>/<NNNN>' and returns it."""
    actor = require_actor(actor)
    record = _lock(conn, voucher_id)
    if record.status != "approved":
        raise ServiceError("not_approved", f"Only an approved voucher can be posted (this one is {record.status}).")
    bills.lock_parties(conn, record.client_id, record.lines)
    _revalidate(conn, record)
    cash_checks.raise_if_cash_negative(conn, record.client_id, record.voucher_date, record.lines)  # C-01
    _check_openings(conn, record)
    b07 = bills.opening_cover_errors(conn, record.client_id, record.financial_year_id, [x.ledger_id for x in record.lines])
    if b07:
        raise VoucherRuleError(b07)
    number = _post_locked(conn, record, actor)
    gst_hooks.on_post(conn, record.client_id, record.id, actor)  # Phase 3: input-credit entries (package C)
    return number


# ================================================================================================== reverse


def reverse(conn: Connection, voucher_id: object, reversal_date: date, reason: str, *, actor: str) -> uuid.UUID:
    """V-12: post a new voucher of the same type with every line's Dr/Cr swapped, linked both ways, and mark the
    original Reversed. The reversal date must be in an open period. Returns the reversal voucher's id."""
    actor = require_actor(actor)
    original = _lock(conn, voucher_id)
    if original.status == "reversed":
        by = conn.execute(
            text("SELECT voucher_number FROM vouchers WHERE id = :id"), {"id": original.reversed_by_voucher_id}
        ).scalar_one()
        raise ServiceError(
            "already_reversed", f"Voucher {original.voucher_number} has already been reversed by {by}."
        )
    if original.status != "posted":
        raise ServiceError("not_posted", f"Only a posted voucher can be reversed (this one is {original.status}).")
    if original.reverses_voucher_id is not None:
        raise ServiceError(
            "reversal_of_reversal", "A reversal voucher cannot be reversed; enter a new voucher instead."
        )
    reason = (reason or "").strip()
    if not reason:
        raise ServiceError("reason_required", "A reason for the reversal is required.")

    mirror = VoucherDraft(
        original.client_id, original.voucher_type, reversal_date,
        f"Reversal of {original.voucher_number}: {reason}", original.reference_no, original.party_ledger_id,
        tuple(VoucherLine(x.ledger_id, x.credit, x.debit, mirror_allocations(x.allocations)) for x in original.lines),
    )
    errors, ctx = _validate(conn, mirror, is_reversal=True)
    errors += bills.draft_errors(conn, mirror, ctx, None, is_reversal=True)
    if errors:
        raise VoucherRuleError(_order(errors))
    reversal_fy = _financial_year_id(ctx, reversal_date)
    cash_checks.raise_if_cash_negative(conn, mirror.client_id, reversal_date, mirror.lines)  # C-01

    reversal_id = _insert_voucher(conn, mirror, reversal_fy, actor, reverses_voucher_id=original.id)
    bills.persist_allocations(conn, reversal_id, mirror, ctx)
    gst_hooks.copy_for_reversal(conn, original.id, reversal_id)  # Phase 3: item rows follow the mirrored lines
    reversal = repo.load_voucher(conn, reversal_id)
    audit.log(conn, AuditEntry(original.client_id, actor, "create", "voucher", reversal_id, new=_snapshot(mirror)))
    _approve_locked(conn, reversal, actor)
    _check_openings(conn, reversal)
    reversal_number = _post_locked(conn, reversal, actor)
    conn.execute(
        text("UPDATE vouchers SET status = 'reversed', reversed_by_voucher_id = :r WHERE id = :id"),
        {"r": reversal_id, "id": original.id},
    )
    _log(
        conn, original, actor, "reverse", {"status": "posted"},
        {"status": "reversed", "reversed_by": str(reversal_id), "reversal_number": reversal_number, "reason": reason},
    )
    gst_hooks.on_reverse(conn, original.client_id, original.id, reversal_id, actor)  # Phase 3 (package C)
    return reversal_id


# ===================================================================================================== read


def get_voucher(conn: Connection, voucher_id: object) -> VoucherRecord:
    record = repo.load_voucher(conn, voucher_id)
    if record is None:
        raise ServiceError("not_found", "Voucher not found.")
    return record
