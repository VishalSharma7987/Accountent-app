"""Hook points between the voucher service and the inventory packages (Phase 5).

`services/vouchers.py` calls these functions; the work is done in services/inventory_movements.py (package C), so the voucher
service needs no inventory knowledge. A voucher without stock item lines costs at most one query.
  validate_stock  - S-02, S-03, S-04, S-06, S-07, S-12 on a draft's stock-relevant item lines (at save)
  persist_stock   - write voucher_stock_lines of a saved draft (godown override, original_movement_id of a Credit / Debit Note)
  load_stock      - the `stock` part of a voucher response, one entry per item line that moves stock (None when none does)
  revalidate_stock- approve / post: the same rules again plus S-01 over the whole chronology (negative stock -> `negative_stock`)
  on_post         - after posting, append stock_movements for the voucher's stock item lines (same transaction, S-05)
  check_reverse   - S-17 BEFORE the reversal voucher is written: mirror movements must not make stock negative
  on_reverse      - after the reversal voucher is posted, append reversal_in / reversal_out movements (S-17)
"""

from datetime import date
from typing import Any

from sqlalchemy import Connection

from app.engine.models import ValidationError
from app.services import inventory_movements as movements


def validate_stock(conn: Connection, client_id: Any, draft: Any) -> list[ValidationError]:
    """Stock rule errors of a draft ([] for a draft without stock item lines). S-01 is checked at approve / post and in the preview."""
    return movements.check_draft(conn, client_id, draft).errors


def persist_stock(conn: Connection, client_id: Any, voucher_id: Any, draft: Any, actor: str) -> None:
    """Write voucher_stock_lines of a saved draft (replaces earlier rows)."""
    movements.persist(conn, client_id, voucher_id, draft)


def load_stock(conn: Connection, client_id: Any, voucher_id: Any) -> list[dict] | None:
    """The `stock` part of a voucher response (None when the voucher has no stock lines)."""
    return movements.stock_part(conn, client_id, voucher_id)


def revalidate_stock(conn: Connection, record: Any) -> list[ValidationError]:
    """Approve / post: every stock rule again (a stored voucher); raises ServiceError('negative_stock') for S-01 alone."""
    return movements.revalidate(conn, record)


def on_post(conn: Connection, client_id: Any, voucher_id: Any, actor: str) -> None:
    """Append the stock movements of a posted voucher."""
    movements.on_post(conn, client_id, voucher_id, actor)


def check_reverse(conn: Connection, client_id: Any, original_id: Any, reversal_date: date) -> None:
    """Refuse a reversal whose mirror movements would make stock negative (raises VoucherRuleError, S-17)."""
    movements.check_reverse(conn, client_id, original_id, reversal_date)


def on_reverse(conn: Connection, client_id: Any, original_id: Any, reversal_id: Any, actor: str) -> None:
    """Append the mirror movements of a reversed voucher."""
    movements.on_reverse(conn, client_id, original_id, reversal_id, actor)
