"""Guard in front of the voucher service's delete of a draft (Phase 7 package F). A draft that belongs to an approval-queue item is
removed only by rejecting the item (which unlinks it first, D-63); deleting it directly would leave the item without its draft."""

from typing import Any

from sqlalchemy import Connection, text

from app.services.errors import ServiceError


def guard_draft_delete(conn: Connection, client_id: Any, voucher_id: Any) -> None:
    row = conn.execute(
        text("SELECT id, status FROM approval_queue_items WHERE client_id = :c AND draft_voucher_id = :v AND status <> 'rejected'"),
        {"c": client_id, "v": voucher_id}).first()
    if row is not None:
        raise ServiceError(
            "queue_item_exists",
            "This draft belongs to an item in the approval queue. Reject the item there (that removes the draft); it cannot be deleted here.",
            {"queue_item_id": str(row[0])})
