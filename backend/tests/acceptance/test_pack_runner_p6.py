"""Phase 6 (period-end and final accounts) pack against the real services. One run builds three clients (a trading proprietor, a service
partnership and a trading company with two financial years) inside one transaction that is rolled back; each section of each client is
then asserted on its own so pytest shows which part differs. The failure text is the report for the accountants (expected vs tool). The
runner never edits a pack file: if the tool and the hand workings disagree, the owner decides who is right.
"""

from pathlib import Path

import pytest
from pack_loader_p6 import load_pack_p6
from pack_runner_p6 import SECTIONS, format_report, run_pack_p6

pytestmark = pytest.mark.integration

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase6-full-year-accounts-2026-27"

# Sections where the tool disagrees with the hand workings and the owner has not decided yet (reason = the finding).
FINDINGS: dict[str, str] = {}


@pytest.fixture(scope="module")
def p6_run(test_engine):
    pack = load_pack_p6(PACK)
    conn = test_engine.connect()
    transaction = conn.begin()
    try:
        report = run_pack_p6(conn, pack)
    finally:
        transaction.rollback()
        conn.close()
    print("\n" + format_report(report))
    return report


@pytest.mark.parametrize("section", SECTIONS)
def test_section_matches_the_hand_workings(request, p6_run, section):
    if section in FINDINGS:
        request.applymarker(pytest.mark.xfail(strict=True, reason=FINDINGS[section]))
    assert p6_run.problems[section] == [], "\n" + format_report(p6_run)


def test_counts(p6_run):
    assert p6_run.counts["vouchers_posted"] == 117  # 50 proprietor + 29 partnership + 38 company
    assert p6_run.counts["adjustments_posted"] == 19  # 7 + 7 + 5 journals through the voucher service
    assert p6_run.counts["reclosed"] == 2  # proprietor and partnership: reopened and closed again
    assert p6_run.counts["reopen_refused"] == 1  # company: the second year has postings
