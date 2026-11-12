"""Step 2.9: the Phase 2 pack against the real services. One run builds the whole world (client, parties, bills,
vouchers, reversals, wrong vouchers, bank statement, reconciliation) inside one transaction that is rolled back; each
section is then asserted on its own so pytest shows which part differs. The failure text is the report for the
accountants (expected vs tool). The runner never edits a pack file: if the tool and the hand workings disagree, the
owner decides who is right.
"""

from pathlib import Path

import pytest
from pack_loader_p2 import load_pack_p2
from pack_runner_p2 import SECTIONS, format_report, run_pack_p2

pytestmark = pytest.mark.integration

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "abc-traders-phase2-jun-2026"


@pytest.fixture(scope="module")
def p2_run(test_engine):
    pack = load_pack_p2(PACK)
    conn = test_engine.connect()
    transaction = conn.begin()
    try:
        report = run_pack_p2(conn, pack)
    finally:
        transaction.rollback()
        conn.close()
    print("\n" + format_report(report))
    return report


@pytest.mark.parametrize("section", SECTIONS)
def test_section_matches_the_hand_workings(p2_run, section):
    assert p2_run.problems[section] == [], "\n" + format_report(p2_run)


def test_counts(p2_run):
    assert p2_run.counts["vouchers_posted"] == 49
    assert p2_run.counts["reversed"] == 1
    assert p2_run.counts["wrong_vouchers_refused"] == 6
    assert p2_run.counts["wrong_parties_refused"] == 3
    assert p2_run.counts["bank_only_drafts"] == 3
