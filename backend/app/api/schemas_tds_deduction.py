"""Request models of the TDS block on vouchers (Phase 4, package B). Amounts are strings; the tax is never typed (T-05)."""

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.engine.models import ValidationError
from app.engine.money import MoneyError, parse_amount
from app.engine.tds_types import TdsLineIn


class TdsItemIn(BaseModel):
    """One deduction. Extra fields are kept (not rejected by pydantic) so that a typed tax amount, rate or tax ledger
    is refused with the rule error T-05 in the same shape as every other rule error."""

    model_config = ConfigDict(extra="allow")
    deductee_ledger_id: uuid.UUID
    nature_key: str
    amount: str
    credit_date: date | None = None
    payment_date: date | None = None
    lower_cert_id: uuid.UUID | None = None
    manual_tax: str | None = None  # salary only (slab_manual natures)


class TdsBlockIn(BaseModel):
    items: list[TdsItemIn] = Field(default_factory=list)


def tds_from_body(block: TdsBlockIn | None) -> tuple[tuple[TdsLineIn, ...], list[ValidationError]]:
    """The engine inputs of a request's `tds` block, or the T-05 / T-16 errors of what was typed."""
    if block is None or not block.items:
        return (), []
    errors: list[ValidationError] = []
    items = []
    for n, item in enumerate(block.items, start=1):
        if item.model_extra:
            typed = ", ".join(sorted(item.model_extra))
            errors.append(ValidationError(
                "T-05", f"Item {n}: the tax amount, rate and tax ledger are calculated by the engine; remove {typed} from the item.", n))
            continue
        try:
            amount = parse_amount(item.amount)
            manual = None if item.manual_tax is None else parse_amount(item.manual_tax)
        except MoneyError as problem:
            errors.append(ValidationError("T-16", f"Item {n}: {problem}.", n))
            continue
        items.append(TdsLineIn(item.deductee_ledger_id, item.nature_key.strip(), amount, item.credit_date, item.payment_date,
                               item.lower_cert_id, manual))
    return (() if errors else tuple(items)), errors
