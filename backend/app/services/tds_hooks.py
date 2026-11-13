"""Hook points between the voucher service and the TDS packages (Phase 4, step 4.0 stubs).

`services/vouchers.py` calls these functions (package B adds the calls once). Until a package fills a body they do
nothing, so every package imports from day one:
  expand_tds       - B: add the TDS / TCS payable line(s) of a draft that carries a `tds` block; plain drafts pass through
  validate_tds     - B: engine check of a draft's `tds` block (T-01 .. T-12); returns rule errors (list)
  persist_tds      - B: write tds_voucher_items of a saved draft (replaces earlier rows)
  load_tds         - B: read them back for the voucher response (None when the voucher has no TDS)
  revalidate_tds   - B: T-13 at approve / post (a tampered draft cannot post)
  on_post          - C: after posting (the register reads posted items, so nothing to write; kept for later use)
  on_reverse       - C: a reversed voucher drops out of the register; challan allocations to its items block the reversal (T-25)
Owner of this file after 4.0: B (bodies); the signatures below are final.
"""

from typing import Any

from sqlalchemy import Connection

from app.engine.models import ValidationError, VoucherDraft


def expand_tds(conn: Connection, draft: VoucherDraft) -> tuple[VoucherDraft, list[ValidationError]]:
    """B: add the payable line(s) of a draft with a `tds` block (stub: unchanged)."""
    return draft, []


def validate_tds(conn: Connection, client_id: Any, draft: Any) -> list:
    """B: the TDS rule errors of a draft (stub: none)."""
    return []


def persist_tds(conn: Connection, client_id: Any, voucher_id: Any, draft: Any, actor: str) -> None:
    """B: write tds_voucher_items (stub: nothing)."""
    return


def load_tds(conn: Connection, client_id: Any, voucher_id: Any) -> dict | None:
    """B: the `tds` block of a voucher response (stub: None)."""
    return None


def revalidate_tds(conn: Connection, record: Any) -> list:
    """B: T-13 at approve / post (stub: none)."""
    return []


def on_post(conn: Connection, client_id: Any, voucher_id: Any, actor: str) -> None:
    """C: after posting (stub: nothing)."""
    return


def on_reverse(conn: Connection, client_id: Any, original_voucher_id: Any, reversal_voucher_id: Any, actor: str) -> None:
    """C: after a reversal (stub: nothing)."""
    return
