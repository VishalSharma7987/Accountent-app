"""Hook points between the voucher service and the GST packages (Phase 3, step 3.0 stubs).

`services/vouchers.py` calls these five functions (package B adds the calls once). Until a package fills a body
they do nothing, so every package imports from day one:
  expand_invoice    - B: build the ledger lines of an invoice-mode draft from its `gst` block (added by B)
  validate_invoice  - B: engine check of a draft's `gst` block (G-10..G-26); returns rule errors (list)
  persist_invoice   - B: write voucher_gst / voucher_item_lines / voucher_gst_line_roles of a draft
  load_invoice      - B: read them back for the voucher response (None when not invoice mode)
  revalidate_invoice, check_number, copy_for_reversal, snapshot - B: G-26 at approve/post, G-23 at posting, reversal copy, audit
  on_post           - C: create itc_entries for a posted purchase / note (lazy import of services.gst_itc)
  on_reverse        - C: mark itc_entries of the reversed voucher as reversed
Owner of this file after 3.0: B (bodies of validate/persist/load); the on_post/on_reverse wiring below is final.
"""

from typing import Any

from sqlalchemy import Connection

from app.db import repositories_gst_invoice as repo_gst
from app.engine.models import ValidationError, VoucherDraft
from app.services import gst_invoices


def expand_invoice(conn: Connection, draft: VoucherDraft) -> tuple[VoucherDraft, list[ValidationError]]:
    """B: build the ledger lines of a draft in invoice mode (draft.gst set); other drafts pass through unchanged."""
    return gst_invoices.expand_invoice(conn, draft)


def validate_invoice(conn: Connection, client_id: Any, draft: Any) -> list:
    """B: the GST rule errors (G-06 .. G-30) of a draft's `gst` block; [] for a draft without one."""
    return gst_invoices.expand_invoice(conn, draft)[1]


def persist_invoice(conn: Connection, client_id: Any, voucher_id: Any, draft: Any, actor: str) -> None:
    """B: write voucher_gst / voucher_item_lines / voucher_gst_line_roles of a saved draft (replaces earlier rows)."""
    gst_invoices.persist(conn, client_id, voucher_id, draft)


def load_invoice(conn: Connection, client_id: Any, voucher_id: Any) -> dict | None:
    """B: the `gst` block of a voucher response, or None when the voucher is not in invoice mode."""
    return gst_invoices.load(conn, client_id, voucher_id)


def revalidate_invoice(conn: Connection, record: Any) -> list:
    """B: G-26 at approve / post (a tampered draft cannot post)."""
    return gst_invoices.revalidate(conn, record)


def check_number(conn: Connection, record: Any, number: str) -> None:
    """B: G-23 at posting; raises VoucherRuleError."""
    gst_invoices.check_number(conn, record, number)


def copy_for_reversal(conn: Connection, original_voucher_id: Any, reversal_voucher_id: Any) -> None:
    """B: the reversal voucher carries copies of the GST rows (its lines mirror the original's, same numbers)."""
    repo_gst.copy_invoice(conn, original_voucher_id, reversal_voucher_id)


def snapshot(draft: VoucherDraft) -> dict | None:
    """B: the GST header for the audit log (None for a plain voucher)."""
    if draft.gst is None or draft.gst_result is None:
        return None
    g = draft.gst
    return {
        "gst_registration_id": str(g.gst_registration_id), "document_kind": g.document_kind,
        "supply_category": g.supply_category, "place_of_supply": g.place_of_supply,
        "invoice_date": g.invoice_date.isoformat(), "counterparty_gstin": g.counterparty_gstin, "items": len(g.items),
        "invoice_value": f"{draft.gst_result.invoice_value:.2f}", "engine_version": draft.gst_result.engine_version,
    }


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
