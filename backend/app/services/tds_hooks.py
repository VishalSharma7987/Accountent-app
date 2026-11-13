"""Hook points between the voucher service and the TDS packages (Phase 4).

`services/vouchers.py` calls these functions (package B added the calls once):
  expand_tds       - B: add the TDS / TCS payable line(s) of a draft that carries a `tds` block; plain drafts pass through
  validate_tds     - B: engine check of a draft's `tds` block (T-01 .. T-17); returns rule errors (list)
  persist_tds      - B: write tds_voucher_items of a saved draft (replaces earlier rows)
  load_tds         - B: read them back for the voucher response (None when the voucher has no TDS)
  revalidate_tds   - B: T-13 at approve / post (a tampered draft cannot post)
  snapshot         - B: the TDS items for the audit log
  on_post          - C: after posting (the register reads posted items, so nothing to write; kept for later use)
  on_reverse       - C: a reversed voucher drops out of the register (it is no longer 'posted'); challan allocations to its items
                     block the reversal (T-25) through services/tds_challans.py::on_reverse_check (lazy import, package C)
Owner of this file after 4.0: B (bodies); the signatures below are final.
"""

from typing import Any

from sqlalchemy import Connection

from app.engine.models import ValidationError, VoucherDraft
from app.services import tds_deduction


def expand_tds(conn: Connection, draft: VoucherDraft) -> tuple[VoucherDraft, list[ValidationError]]:
    """B: add the payable line(s) of a draft with a `tds` block (a draft without one is returned unchanged)."""
    return tds_deduction.expand(conn, draft)


def validate_tds(conn: Connection, client_id: Any, draft: Any) -> list:
    """B: the TDS rule errors of a draft's `tds` block ([] for a draft without one)."""
    return tds_deduction.expand(conn, draft)[1]


def persist_tds(conn: Connection, client_id: Any, voucher_id: Any, draft: Any, actor: str) -> None:
    """B: write tds_voucher_items of a saved draft (replaces earlier rows; none for a plain voucher)."""
    tds_deduction.persist(conn, client_id, voucher_id, draft, actor)


def load_tds(conn: Connection, client_id: Any, voucher_id: Any) -> dict | None:
    """B: the `tds` block of a voucher response (None when the voucher has no TDS)."""
    return tds_deduction.load(conn, client_id, voucher_id)


def revalidate_tds(conn: Connection, record: Any) -> list:
    """B: T-13 at approve / post (the stored working is recomputed; a difference blocks)."""
    return tds_deduction.revalidate(conn, record)


def snapshot(draft: VoucherDraft) -> dict | None:
    """B: the TDS items for the audit log (None for a plain voucher)."""
    return tds_deduction.snapshot(draft)


def on_post(conn: Connection, client_id: Any, voucher_id: Any, actor: str) -> None:
    """C: after posting (nothing to write: the register reads the posted items)."""
    return


def on_reverse(conn: Connection, client_id: Any, original_voucher_id: Any, reversal_voucher_id: Any, actor: str) -> None:
    """C: a reversal is refused while a challan allocation exists on an item of the original (T-25, 409 item_has_allocation)."""
    try:
        from app.services import tds_challans
    except ImportError:  # package C not merged yet
        return
    tds_challans.on_reverse_check(conn, client_id, original_voucher_id)
