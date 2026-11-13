"""Inventory masters use-cases (Phase 5, package A): godowns, stock items, per-year policy, opening stock.
Rules S-02, S-03, S-04, S-07, S-08, S-09, S-18 (engine/inventory_masters.py holds the pure checks). Nothing is ever
deleted (switch off with is_active); services never commit; every change is audit-logged.
"""

import uuid
from dataclasses import asdict, dataclass
from decimal import Decimal

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_gst_masters as gst_repo
from app.db import repositories_inventory_masters as inv
from app.engine import inventory_masters as engine
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor

ZERO = Decimal(0)


def _snap(value: object) -> dict:
    return {k: (str(v) if isinstance(v, (uuid.UUID, Decimal)) else v) for k, v in asdict(value).items()}  # type: ignore[call-overload]


def _client(conn: Connection, client_id: object) -> None:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")


def _year(conn: Connection, client_id: object, fy_id: object):
    fy = repo.get_financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return fy


def _require_unlocked(conn: Connection, client_id: object, fy_id: object, what: str) -> None:
    """S-09: opening, policy and NRV edits are blocked for a year with a locked period."""
    if inv.year_has_locked_period(conn, client_id, fy_id):
        raise ServiceError("period_locked", f"A period of this financial year is locked; the {what} cannot be changed (S-09).")


# =============================================================================================== godowns


def list_godowns(conn: Connection, client_id: object) -> list[inv.GodownRow]:
    _client(conn, client_id)
    return inv.godown_rows(conn, client_id)


def create_godown(conn: Connection, client_id: object, *, name: str, actor: str) -> uuid.UUID:
    actor = require_actor(actor)
    _client(conn, client_id)
    name = (name or "").strip()
    if not name:
        raise ServiceError("invalid_name", "The godown name is required.")
    if inv.godown_name_taken(conn, client_id, name, None):
        raise ServiceError("godown_exists", f"A godown named '{name}' already exists.")
    godown_id = uuid.uuid4()
    inv.insert_godown(conn, client_id, godown_id, name)
    audit.log(conn, AuditEntry(client_id, actor, "create", "godown", godown_id, new={"name": name, "is_active": True}))
    return godown_id


def update_godown(conn: Connection, client_id: object, godown_id: object, *, name: str | None = None,
                  is_active: bool | None = None, actor: str) -> None:
    actor = require_actor(actor)
    existing = inv.godown_row(conn, client_id, godown_id)
    if existing is None:
        raise ServiceError("not_found", "Godown not found for this client.")
    new_name = existing.name if name is None else name.strip()
    if not new_name:
        raise ServiceError("invalid_name", "The godown name is required.")
    new_active = existing.is_active if is_active is None else bool(is_active)
    if inv.godown_name_taken(conn, client_id, new_name, existing.id):
        raise ServiceError("godown_exists", f"A godown named '{new_name}' already exists.")
    if existing.is_active and not new_active:
        holding = [q for _, g, q in inv.nonzero_balances(conn, client_id) if g == existing.id]
        if holding:
            raise ServiceError("godown_in_use", f"Godown '{existing.name}' still holds stock; move or write it off first (S-18).")
        if inv.active_items_defaulting_to(conn, client_id, existing.id):
            raise ServiceError("godown_in_use", f"Godown '{existing.name}' is the default godown of active stock items.")
    inv.update_godown(conn, client_id, existing.id, new_name, new_active)
    audit.log(conn, AuditEntry(client_id, actor, "update", "godown", existing.id, old=_snap(existing),
                               new={"id": str(existing.id), "name": new_name, "is_active": new_active}))


# ============================================================================================ stock items


def list_stock_items(conn: Connection, client_id: object, *, q: str | None = None, active: bool | None = None,
                     financial_year_id: object | None = None) -> list[inv.StockItemRow]:
    _client(conn, client_id)
    if financial_year_id is not None:
        _year(conn, client_id, financial_year_id)
    return inv.stock_item_rows(conn, client_id, (q or "").strip() or None, active, financial_year_id)


def put_stock_item(conn: Connection, client_id: object, item_id: object, *, sku: str, default_godown_id: object,
                   is_active: bool = True, actor: str) -> None:
    """Make a goods GST item a stock item (or change its SKU / default godown / active flag)."""
    actor = require_actor(actor)
    _client(conn, client_id)
    item = gst_repo.item_row(conn, client_id, item_id)
    if item is None:
        raise ServiceError("not_found", "Item not found for this client.")
    sku = (sku or "").strip()
    godown = inv.godown_row(conn, client_id, default_godown_id) if _is_uuid(default_godown_id) else None
    errors = engine.validate_stock_item(sku, item.item_kind, item.is_active or not is_active,
                                        None if godown is None else godown.is_active)
    if errors:
        raise VoucherRuleError(errors)
    if inv.sku_taken(conn, client_id, sku, item.id):
        raise ServiceError("sku_exists", f"SKU '{sku}' is already used by another stock item.")
    existing = inv.stock_item_row(conn, client_id, item.id)
    if existing is None:
        inv.insert_stock_item(conn, client_id, item.id, sku, godown.id, bool(is_active))  # type: ignore[union-attr]
        audit.log(conn, AuditEntry(client_id, actor, "create", "stock_item", item.id, new={
            "sku": sku, "default_godown_id": str(godown.id), "is_active": bool(is_active)}))  # type: ignore[union-attr]
        return
    if existing.is_active and not is_active:
        held = [q for i, _, q in inv.nonzero_balances(conn, client_id) if i == item.id]
        if held:
            raise ServiceError("stock_item_in_use", f"'{item.name}' still has closing stock; clear it before deactivating (S-18).")
    inv.update_stock_item(conn, client_id, item.id, sku, godown.id, bool(is_active))  # type: ignore[union-attr]
    audit.log(conn, AuditEntry(
        client_id, actor, "update", "stock_item", item.id,
        old={"sku": existing.sku, "default_godown_id": str(existing.default_godown_id), "is_active": existing.is_active},
        new={"sku": sku, "default_godown_id": str(godown.id), "is_active": bool(is_active)}))  # type: ignore[union-attr]


def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


# ===================================================================================================== policy


def get_policy(conn: Connection, client_id: object, fy_id: object) -> inv.PolicyRow:
    _client(conn, client_id)
    _year(conn, client_id, fy_id)
    row = inv.policy_row(conn, client_id, fy_id)
    if row is None:
        raise ServiceError("no_policy", "The inventory policy (valuation method) is not set for this financial year (S-04).")
    return row


def put_policy(conn: Connection, client_id: object, fy_id: object, *, valuation_method: str, negative_stock_mode: str,
               actor: str) -> None:
    actor = require_actor(actor)
    _client(conn, client_id)
    _year(conn, client_id, fy_id)
    errors = engine.validate_policy(valuation_method, negative_stock_mode)
    if errors:
        raise VoucherRuleError(errors)
    _require_unlocked(conn, client_id, fy_id, "inventory policy")
    existing = inv.policy_row(conn, client_id, fy_id)
    if existing is None:
        inv.insert_policy(conn, client_id, fy_id, valuation_method, negative_stock_mode, actor)
        audit.log(conn, AuditEntry(client_id, actor, "create", "inventory_policy", fy_id, new={
            "valuation_method": valuation_method, "negative_stock_mode": negative_stock_mode}))
        return
    if existing.valuation_method != valuation_method and inv.year_has_movements(conn, client_id, fy_id):
        raise ServiceError("policy_locked", "This year already has stock movements; the valuation method cannot change (S-04).")
    inv.update_policy(conn, client_id, fy_id, valuation_method, negative_stock_mode, actor)
    audit.log(conn, AuditEntry(
        client_id, actor, "update", "inventory_policy", fy_id,
        old={"valuation_method": existing.valuation_method, "negative_stock_mode": existing.negative_stock_mode},
        new={"valuation_method": valuation_method, "negative_stock_mode": negative_stock_mode}))


def copy_policy(conn: Connection, client_id: object, *, from_financial_year_id: object, to_financial_year_id: object,
                actor: str) -> None:
    """A new year's policy is set explicitly: this copies another year's policy (S-04)."""
    actor = require_actor(actor)
    _client(conn, client_id)
    _year(conn, client_id, from_financial_year_id)
    _year(conn, client_id, to_financial_year_id)
    source = inv.policy_row(conn, client_id, from_financial_year_id)
    if source is None:
        raise ServiceError("no_policy", "The year to copy from has no inventory policy (S-04).")
    if inv.policy_row(conn, client_id, to_financial_year_id) is not None:
        raise ServiceError("policy_exists", "The target year already has an inventory policy.")
    _require_unlocked(conn, client_id, to_financial_year_id, "inventory policy")
    inv.insert_policy(conn, client_id, to_financial_year_id, source.valuation_method, source.negative_stock_mode, actor)
    audit.log(conn, AuditEntry(client_id, actor, "create", "inventory_policy", to_financial_year_id, new={
        "valuation_method": source.valuation_method, "negative_stock_mode": source.negative_stock_mode,
        "copied_from": str(from_financial_year_id)}))


# ===================================================================================================== opening


@dataclass(frozen=True)
class OpeningView:
    rows: list[inv.OpeningRow]
    total_value: Decimal
    ledger_opening_value: Decimal | None
    difference: Decimal | None


def get_opening(conn: Connection, client_id: object, fy_id: object) -> OpeningView:
    _client(conn, client_id)
    _year(conn, client_id, fy_id)
    rows = inv.opening_rows(conn, client_id, fy_id)
    total = sum((r.value for r in rows), ZERO).quantize(Decimal("0.01"))
    ledger = inv.stock_in_hand_opening(conn, client_id, fy_id)
    return OpeningView(rows, total, ledger, engine.opening_difference(total, ledger))


def replace_opening(conn: Connection, client_id: object, fy_id: object, rows: list[engine.OpeningInput], *,
                    actor: str) -> Decimal:
    """Replace the whole opening stock of the year. Returns the new total value."""
    actor = require_actor(actor)
    _client(conn, client_id)
    _year(conn, client_id, fy_id)
    items = {s.item_id: engine.ItemFacts("goods", s.is_active) for s in inv.stock_item_rows(conn, client_id, None, None, None)}
    godowns = {g.id: g.is_active for g in inv.godown_rows(conn, client_id)}
    parsed = [engine.OpeningInput(_uuid_or_none(r.item_id), _uuid_or_none(r.godown_id), r.quantity, r.value) for r in rows]
    clean, errors = engine.validate_opening(parsed, items, godowns)
    if errors:
        raise VoucherRuleError(errors)
    _require_unlocked(conn, client_id, fy_id, "opening stock")
    old = [{"item_id": str(r.item_id), "godown_id": str(r.godown_id), "quantity": str(r.quantity), "value": str(r.value)}
           for r in inv.opening_rows(conn, client_id, fy_id)]
    inv.replace_opening(conn, client_id, fy_id, [(c.item_id, c.godown_id, c.quantity, c.value) for c in clean], actor)
    total = sum((c.value for c in clean), ZERO).quantize(Decimal("0.01"))
    new = [{"item_id": str(c.item_id), "godown_id": str(c.godown_id), "quantity": str(c.quantity), "value": str(c.value)}
           for c in clean]
    audit.log(conn, AuditEntry(client_id, actor, "update", "stock_opening", fy_id, old={"rows": old},
                               new={"rows": new, "total_value": str(total)}))
    return total


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None

