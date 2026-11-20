"""Hook points shared by the Phase 8 packages (docs/PHASE8_PLAN.md). Bodies are final; packages call them instead of each writing their own SQL.

  log_action        - principle 7: one audit_log row for every audit action (run, paper, decision, sign-off, flag, form entry).
  require_ai_for_summary - D-51 reused: no model call unless the client's AI switch is on (a suggestion text only, never a conclusion).
  READ_ONLY_TABLES  - the books tables the audit service must never write to; a unit test scans audit_* services for INSERT / UPDATE / DELETE on them.
"""

from typing import Any

from sqlalchemy import Connection

from app.services import ai_hooks, audit

ENTITIES = (
    "audit_run", "audit_working_paper", "audit_paper_item", "audit_paper_note", "audit_holiday", "audit_related_party",
    "audit_form_set", "audit_form_entry", "audit_ai_summary",
)

READ_ONLY_TABLES = (
    "vouchers", "voucher_lines", "voucher_number_sequences", "ledgers", "account_groups", "opening_balances", "periods", "financial_years",
    "parties", "opening_bills", "bill_allocations", "voucher_gst", "tds_voucher_items", "tds_challans", "stock_movements",
    "documents", "document_vouchers", "gst_filed_returns", "tds_filed_returns", "fixed_assets",
)


def log_action(conn: Connection, client_id: Any, actor: str, action: str, entity: str, entity_id: Any,
               old: dict | None = None, new: dict | None = None) -> None:
    if entity not in ENTITIES:
        raise ValueError(f"unknown audit entity {entity!r}")
    audit.log(conn, audit.AuditEntry(client_id, actor, action, entity, entity_id, old, new))


def require_ai_for_summary(conn: Connection, client_id: Any) -> None:
    ai_hooks.require_llm_enabled(conn, client_id)
