"""Step 3.10: the Phase 3 (GST) pack against the real services. One run builds the whole world (client, GST
registration, invoice-mode vouchers, GSTR-2B imports, ITC register, returns, 180-day check, composition client, wrong
cases) inside one transaction that is rolled back; each section is then asserted on its own so pytest shows which part
differs. The failure text is the report for the accountants (expected vs tool). The runner never edits a pack file: if
the tool and the hand workings disagree, the owner decides who is right (findings go to the owner, not into the pack).
"""

from pathlib import Path

import pytest
from pack_loader_p3 import load_pack_p3
from pack_runner_p3 import SECTIONS, format_report, run_pack_p3

pytestmark = pytest.mark.integration

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase3-sunrise-traders-apr-2026"


@pytest.fixture(scope="module")
def p3_run(test_engine):
    pack = load_pack_p3(PACK)
    conn = test_engine.connect()
    transaction = conn.begin()
    try:
        report = run_pack_p3(conn, pack)
    finally:
        transaction.rollback()
        conn.close()
    print("\n" + format_report(report))
    return report


@pytest.mark.parametrize(
    "section",
    SECTIONS,
)
def test_section_matches_the_hand_workings(p3_run, section):
    assert p3_run.problems[section] == [], "\n" + format_report(p3_run)


def test_counts(p3_run):
    assert p3_run.counts["vouchers_posted"] == 14
    assert p3_run.counts["payments_posted"] == 4
    assert p3_run.counts["wrong_cases_refused"] == 8
