"""Hook points between the voucher service and the GST packages (Phase 3, step 3.0 stubs).

`services/vouchers.py` calls these five functions (package B adds the calls once). Until a package fills a body
they do nothing, so every package imports from day one:
  validate_invoice  - B: engine check of a draft's `gst` block (G-10..G-26); returns rule errors (list)
  persist_invoice   - B: write voucher_gst / voucher_item_lines / voucher_gst_line_roles of a draft
  load_invoice      - B: read them back for the voucher response (None when not invoice mode)
  on_post           - C: create itc_entries for a posted purchase / note (lazy import of services.gst_itc)
  on_reverse        - C: mark itc_entries of the reversed voucher as reversed
Owner of this file after 3.0: B (bodies of validate/persist/load); the on_post/on_reverse wiring below is final.
"""

from typing import Any

from sqlalchemy import Connection


def validate_invoice(conn: Connection, client_id: Any, draft: Any) -> list:
    return []


def persist_invoice(conn: Connection, client_id: Any, voucher_id: Any, draft: Any, actor: str) -> None:
    return None


def load_invoice(conn: Connection, client_id: Any, voucher_id: Any) -> dict | None:
    return None


def on_post(conn: Connection, client_id: Any, voucher_id: Any, actor: str) -> None:
    try:
        from app.services import gst_itc
    except ImportError:  # package C not merged yet
        return
    gst_itc.on_post(conn, client_id, voucher_id, actor)


def on_reverse(conn: Connection, client_id: Any, original_voucher_id: Any, reversal_voucher_id: Any, actor: str) -> None:
    try:
        from app.services import gst_itc
    except ImportError:
        return
    gst_itc.on_reverse(conn, client_id, original_voucher_id, reversal_voucher_id, actor)
