"""Hook points between the voucher service and the inventory packages (Phase 5, step 5.0 stubs).

`services/vouchers.py` calls these functions (package C adds the calls once, hook calls only). Until a package fills a body they do
nothing, so every package imports from day one:
  validate_stock  - C: S-01..S-14 on a draft's stock-relevant item lines (preview at save / approve / post); returns rule errors (list)
  persist_stock   - C: write voucher_stock_lines of a saved draft (godown override, original_movement_id of a Credit / Debit Note)
  load_stock      - C: read them back for the voucher response (None when the voucher has none)
  on_post         - C: after posting, append stock_movements for the voucher's stock item lines (same transaction; S-01 re-checked
                    over the whole chronology, so a backdated entry cannot leave a negative balance)
  on_reverse      - C: after the reversal voucher is posted, append reversal_in / reversal_out movements for the original's movements
                    (blocks the reversal when it would make stock negative, S-17)
Owner of this file after 5.0: C (bodies); the signatures below are final.
"""

from typing import Any

from sqlalchemy import Connection

from app.engine.models import ValidationError


def validate_stock(conn: Connection, client_id: Any, draft: Any) -> list[ValidationError]:
    """C: stock rule errors of a draft ([] for a draft without stock item lines)."""
    return []


def persist_stock(conn: Connection, client_id: Any, voucher_id: Any, draft: Any, actor: str) -> None:
    """C: write voucher_stock_lines of a saved draft (replaces earlier rows)."""
    return


def load_stock(conn: Connection, client_id: Any, voucher_id: Any) -> list[dict] | None:
    """C: the `stock` part of a voucher response (None when the voucher has no voucher_stock_lines)."""
    return None


def on_post(conn: Connection, client_id: Any, voucher_id: Any, actor: str) -> None:
    """C: append the stock movements of a posted voucher."""
    return


def on_reverse(conn: Connection, client_id: Any, original_id: Any, reversal_id: Any, actor: str) -> None:
    """C: append the mirror movements of a reversed voucher."""
    return
