"""The `tds` block of a voucher request (T-05, T-16) and the quarter dates of the register. No database."""

import uuid
from datetime import date
from decimal import Decimal as D

from app.api.schemas_tds_deduction import TdsBlockIn, tds_from_body
from app.services.tds_deduction import quarter_range

LEDGER = uuid.UUID(int=5)


def block(**extra):
    item = {"deductee_ledger_id": str(LEDGER), "nature_key": "contractor", "amount": "50000.00", "payment_date": "2026-06-10", **extra}
    return TdsBlockIn.model_validate({"items": [item]})


def test_T05_a_typed_tax_amount_rate_or_ledger_is_refused_with_the_rule_id():
    items, errors = tds_from_body(block(tds_amount="999.00", rate="5"))
    assert items == ()
    assert [(e.rule_id, e.line_no) for e in errors] == [("T-05", 1)]
    assert errors[0].message == "Item 1: the tax amount, rate and tax ledger are calculated by the engine; remove rate, tds_amount from the item."


def test_T05_a_plain_block_becomes_engine_input():
    items, errors = tds_from_body(block())
    assert errors == []
    assert (items[0].deductee_ledger_id, items[0].nature_key, items[0].amount, items[0].payment_date, items[0].credit_date) == (
        LEDGER, "contractor", D("50000.00"), date(2026, 6, 10), None)


def test_T16_an_amount_with_three_decimals_is_refused():
    _, errors = tds_from_body(block(amount="100.005"))
    assert [e.rule_id for e in errors] == ["T-16"]


def test_no_block_means_no_items():
    assert tds_from_body(None) == ((), [])


def test_quarters_of_the_financial_year_are_april_to_march():
    fy = date(2026, 4, 1)
    assert [quarter_range(fy, q) for q in (1, 2, 3, 4)] == [
        (date(2026, 4, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 9, 30)),
        (date(2026, 10, 1), date(2026, 12, 31)), (date(2027, 1, 1), date(2027, 3, 31))]
