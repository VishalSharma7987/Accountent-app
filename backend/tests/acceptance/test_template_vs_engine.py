"""The template pack against the real engine: every correct voucher passes, every wrong voucher is rejected with
the rule ID and the message word the pack promises. (Pure engine: no database.)

This keeps the pack format honest: its `expected_message_contains` words must really appear in the engine's messages.
"""

from datetime import date
from itertools import groupby
from pathlib import Path

import pytest
from chart_fixture import EXPECTED_GROUPS
from pack_loader import load_pack

from app.engine.models import Group, Ledger, PeriodInfo, VoucherDraft, VoucherLine
from app.engine.validation import validate_voucher

TEMPLATE = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "_template"
CLIENT = "pack-client"
GROUPS = {code: Group(code, name, nature, report, parent) for code, name, parent, nature, report in EXPECTED_GROUPS}
GROUP_CODE_BY_NAME = {name: code for code, name, *_ in EXPECTED_GROUPS}


@pytest.fixture(scope="module")
def pack():
    return load_pack(TEMPLATE)


def engine_inputs(pack):
    ledgers = {x.name: Ledger(x.name, x.name, GROUP_CODE_BY_NAME[x.group], True, CLIENT) for x in pack.ledgers}
    fy_start = pack.client.fy_start
    fy_ranges = [(fy_start, date(fy_start.year + 1, 3, 31))]

    def period_for(on):  # every month of the pack year is an open period
        return PeriodInfo(date(on.year, on.month, 1), date(on.year, on.month, 28), "open")

    return ledgers, fy_ranges, period_for


def draft_from(rows) -> VoucherDraft:
    """A voucher draft from the CSV rows of one ref_id. Amounts stay as typed (text)."""
    head = rows[0]
    lines = tuple(VoucherLine(r.ledger_name, r.debit, r.credit) for r in rows)
    return VoucherDraft(
        CLIENT, head.voucher_type, head.date, head.narration, head.reference_no or None, head.party_ledger or None, lines
    )


def vouchers(rows):
    return [(ref, list(group)) for ref, group in groupby(rows, key=lambda r: r.ref_id)]


def test_every_correct_voucher_of_the_template_passes_the_engine(pack):
    ledgers, fy_ranges, period_for = engine_inputs(pack)
    results = {
        ref: validate_voucher(draft_from(rows), ledgers, GROUPS, fy_ranges, period_for)
        for ref, rows in vouchers(pack.vouchers)
    }
    assert results == {"V01": [], "V02": [], "V03": []}


@pytest.mark.parametrize(
    ("ref", "rule_id", "word"),
    [
        ("X01", "V-04", "equal"),
        ("X02", "V-09", "narration"),
        ("X03", "V-03", "decimal"),
        ("X04", "V-13", "party"),
        ("X05", "V-14", "bill number"),
    ],
)
def test_every_wrong_voucher_of_the_template_is_rejected_with_the_promised_rule_and_word(pack, ref, rule_id, word):
    ledgers, fy_ranges, period_for = engine_inputs(pack)
    rows = dict(vouchers(pack.invalid_vouchers))[ref]
    assert {r.expected_rule_id for r in rows} == {rule_id}
    assert {r.expected_message_contains for r in rows} == {word}

    errors = validate_voucher(draft_from(rows), ledgers, GROUPS, fy_ranges, period_for)

    assert rule_id in {e.rule_id for e in errors}, errors
    assert any(word.lower() in e.message.lower() for e in errors if e.rule_id == rule_id), errors
    # each wrong voucher is wrong in ONE way only, so the expected rule is the only rule reported
    assert {e.rule_id for e in errors} == {rule_id}, errors


def test_the_template_promises_exactly_the_wrong_vouchers_tested_here(pack):
    assert [ref for ref, _ in vouchers(pack.invalid_vouchers)] == ["X01", "X02", "X03", "X04", "X05"]
