"""Item / service master use-cases (HSN / SAC, UQC, default ledgers and ITC / RCM tags). The tax RATE is never stored
here: it comes from the rate rule table by date. Rule G-07 comes from engine/gst_masters.py. No delete: switch an item
off with is_active = False. Services never commit; every change is audit-logged.
"""

import uuid
from dataclasses import asdict
from datetime import date

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_gst_masters as gst_repo
from app.db.repositories_gst_masters import ItemRow
from app.engine import gst_masters as engine
from app.engine.gst_types import GstItem
from app.rules import gst_rules
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor


def _snapshot(row: ItemRow) -> dict:
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in asdict(row).items()}


def _opt_id(value: object) -> uuid.UUID | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise ServiceError("invalid_ledger", "Ledger not found for this client.") from None


def _prepare(conn: Connection, client_id: object, item_id: uuid.UUID, *, name: str, item_kind: str, hsn_sac: str,
             uqc: str | None, sales_ledger_id: object, purchase_ledger_id: object, default_itc_category_key: str | None,
             default_rcm_category_key: str | None, is_active: bool, exclude_id: object | None) -> ItemRow:
    """Validate every rule and return the row to write (raises before anything is written)."""
    name = (name or "").strip()
    if not name:
        raise ServiceError("invalid_name", "The item name is required.")
    hsn_sac = (hsn_sac or "").strip()
    uqc = (uqc or "").strip().upper() or None
    errors = engine.validate_item(item_kind, hsn_sac, uqc, [u.code for u in gst_rules.uqc_list(conn, date.today())])
    if errors:
        raise VoucherRuleError(errors)
    ledgers = []
    for value in (sales_ledger_id, purchase_ledger_id):
        ledger_id = _opt_id(value)
        if ledger_id is not None and repo.get_ledger(conn, client_id, ledger_id) is None:
            raise ServiceError("invalid_ledger", "Ledger not found for this client.")
        ledgers.append(ledger_id)
    itc = (default_itc_category_key or "").strip() or None
    rcm = (default_rcm_category_key or "").strip() or None
    if itc and not gst_repo.rule_key_exists(conn, "gst_blocked_credit_rules", "category_key", itc):
        raise ServiceError("invalid_category", f"'{itc}' is not a Section 17(5) category in the rule table.")
    if rcm and not gst_repo.rule_key_exists(conn, "gst_rcm_rules", "category_key", rcm):
        raise ServiceError("invalid_category", f"'{rcm}' is not a reverse-charge category in the rule table.")
    if gst_repo.item_name_taken(conn, client_id, name, exclude_id):
        raise ServiceError("item_exists", f"An item named '{name}' already exists.")
    return ItemRow(item_id, name, item_kind, hsn_sac, uqc, ledgers[0], ledgers[1], itc, rcm, bool(is_active))


def create_item(
    conn: Connection, client_id: object, *, name: str, item_kind: str, hsn_sac: str, uqc: str | None = None,
    sales_ledger_id: object = None, purchase_ledger_id: object = None, default_itc_category_key: str | None = None,
    default_rcm_category_key: str | None = None, actor: str,
) -> uuid.UUID:
    actor = require_actor(actor)
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    row = _prepare(conn, client_id, uuid.uuid4(), name=name, item_kind=item_kind, hsn_sac=hsn_sac, uqc=uqc,
                   sales_ledger_id=sales_ledger_id, purchase_ledger_id=purchase_ledger_id,
                   default_itc_category_key=default_itc_category_key,
                   default_rcm_category_key=default_rcm_category_key, is_active=True, exclude_id=None)
    gst_repo.insert_item(conn, client_id, row)
    audit.log(conn, AuditEntry(client_id, actor, "create", "gst_item", row.id, new=_snapshot(row)))
    return row.id


def update_item(
    conn: Connection, client_id: object, item_id: object, *, name: str, item_kind: str, hsn_sac: str,
    uqc: str | None = None, sales_ledger_id: object = None, purchase_ledger_id: object = None,
    default_itc_category_key: str | None = None, default_rcm_category_key: str | None = None, is_active: bool = True,
    actor: str,
) -> None:
    actor = require_actor(actor)
    existing = gst_repo.item_row(conn, client_id, item_id)
    if existing is None:
        raise ServiceError("not_found", "Item not found for this client.")
    row = _prepare(conn, client_id, existing.id, name=name, item_kind=item_kind, hsn_sac=hsn_sac, uqc=uqc,
                   sales_ledger_id=sales_ledger_id, purchase_ledger_id=purchase_ledger_id,
                   default_itc_category_key=default_itc_category_key,
                   default_rcm_category_key=default_rcm_category_key, is_active=is_active, exclude_id=existing.id)
    gst_repo.update_item(conn, client_id, row)
    audit.log(conn, AuditEntry(client_id, actor, "update", "gst_item", row.id, old=_snapshot(existing),
                               new=_snapshot(row)))


def get_item(conn: Connection, client_id: object, item_id: object) -> GstItem:
    row = gst_repo.item_row(conn, client_id, item_id)
    if row is None:
        raise ServiceError("not_found", "Item not found for this client.")
    return _item(row)


def list_items(conn: Connection, client_id: object, q: str | None = None, kind: str | None = None) -> list[GstItem]:
    """Items sorted by name; `q` matches part of the name or the start of the HSN/SAC; `kind` goods | service."""
    if kind not in (None, "goods", "service"):
        raise ServiceError("invalid_kind", "kind must be goods or service.")
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    return [_item(r) for r in gst_repo.item_rows(conn, client_id, (q or "").strip() or None, kind)]


def _item(r: ItemRow) -> GstItem:
    return GstItem(
        str(r.id), r.name, r.item_kind, r.hsn_sac, r.uqc,
        None if r.sales_ledger_id is None else str(r.sales_ledger_id),
        None if r.purchase_ledger_id is None else str(r.purchase_ledger_id),
        r.default_itc_category_key, r.default_rcm_category_key, r.is_active,
    )
