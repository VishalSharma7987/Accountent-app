"""Period lock and unlock. A locked period refuses vouchers dated in it (rule V-07); unlocking needs a reason.

Services take a SQLAlchemy Connection and never commit (the caller owns the transaction).
"""

from sqlalchemy import Connection, text

from app.db import repositories as repo
from app.db.repositories import PeriodRecord
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, require_actor

LISTED = 5  # how many blocking vouchers the message names; all of them are in `details`


def _fmt(value) -> str:
    return value.strftime("%d-%m-%Y")


def _label(period: PeriodRecord) -> str:
    return f"{_fmt(period.start)} to {_fmt(period.end)}"


def list_periods(conn: Connection, client_id: object, financial_year_id: object | None = None) -> list[PeriodRecord]:
    return repo.list_periods(conn, client_id, financial_year_id)


def _find(conn: Connection, client_id: object, period_id: object) -> PeriodRecord:
    period = repo.get_period(conn, client_id, period_id, lock=True)
    if period is None:
        raise ServiceError("not_found", "Period not found for this client.")
    return period


def lock_period(conn: Connection, client_id: object, period_id: object, *, actor: str) -> None:
    """Lock a period. Refused while draft or approved vouchers are dated in it (they are listed)."""
    actor = require_actor(actor)
    period = _find(conn, client_id, period_id)
    if period.status == "locked":
        raise ServiceError("already_locked", f"The period {_label(period)} is already locked.")
    blocking = repo.open_vouchers_in_range(conn, client_id, period.start, period.end)
    if blocking:
        shown = "; ".join(f"{v['status']} {_fmt(v['voucher_date'])} '{v['narration']}'" for v in blocking[:LISTED])
        more = f" and {len(blocking) - LISTED} more" if len(blocking) > LISTED else ""
        raise ServiceError(
            "period_has_open_vouchers",
            f"The period {_label(period)} cannot be locked: {len(blocking)} draft or approved voucher(s) are dated "
            f"in it ({shown}{more}). Post, delete or re-date them first.",
            details=blocking,
        )
    conn.execute(
        text("UPDATE periods SET status = 'locked', locked_at = now(), locked_by = :by WHERE id = :id"),
        {"by": actor, "id": period.id},
    )
    audit.log(conn, AuditEntry(client_id, actor, "lock", "period", period.id,
                               old={"status": "open"}, new={"status": "locked", "locked_by": actor}))


def unlock_period(conn: Connection, client_id: object, period_id: object, reason: str, *, actor: str) -> None:
    """Re-open a locked period. A reason is required and is written to the audit log."""
    actor = require_actor(actor)
    reason = (reason or "").strip()
    period = _find(conn, client_id, period_id)
    if period.status != "locked":
        raise ServiceError("not_locked", f"The period {_label(period)} is not locked.")
    if not reason:
        raise ServiceError("reason_required", "A reason is required to unlock a period.")
    conn.execute(
        text("UPDATE periods SET status = 'open', locked_at = NULL, locked_by = NULL WHERE id = :id"),
        {"id": period.id},
    )
    audit.log(conn, AuditEntry(client_id, actor, "unlock", "period", period.id,
                               old={"status": "locked", "locked_by": period.locked_by},
                               new={"status": "open", "reason": reason}))
