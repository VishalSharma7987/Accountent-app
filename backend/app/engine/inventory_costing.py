"""Purchase costing (rule S-14) and unit-cost display. Pure Python, Decimal only."""

from decimal import Decimal

from app.engine.money import MoneyError, parse_amount, round_half_up

ZERO = Decimal("0.00")


def purchase_cost(
    taxable_value: Decimal,
    cgst: Decimal = ZERO,
    sgst: Decimal = ZERO,
    igst: Decimal = ZERO,
    cess: Decimal = ZERO,
    tax_in_cost: bool = False,
) -> Decimal:
    """Cost of a purchase item line (S-14): taxable value after discount, plus CGST/SGST/IGST/cess only when the
    tax is blocked credit (`tax_in_cost`). Recoverable GST is never cost. Freight and other direct costs are not
    allocated in Phase 5. Amounts with more than 2 decimals or negative are rejected (MoneyError), never rounded."""
    cost = parse_amount(taxable_value)
    if tax_in_cost:
        for tax in (cgst, sgst, igst, cess):
            cost += parse_amount(tax)
    else:
        for tax in (cgst, sgst, igst, cess):  # still validated: a bad tax amount is a bad line
            parse_amount(tax)
    return round_half_up(cost, 2)


def unit_cost(value: Decimal, quantity: Decimal) -> Decimal:
    """Value / quantity to 4 decimals (half up). For display only: never used to compute a value."""
    if quantity <= 0:
        raise MoneyError("invalid", "quantity must be above zero to show a unit cost")
    return round_half_up(value / quantity, 4)
