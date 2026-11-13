"""Step 4.8: the Phase 4 (TDS / TCS) pack against the real services. One run builds the whole world (client with two financial
years, deductees, certificates, 28 vouchers with TDS / TCS, challans, interest, quarterly workings, certificate data, 26AS import
and reconciliation, wrong cases) inside one transaction that is rolled back; each section is then asserted on its own so pytest
shows which part differs. The failure text is the report for the accountants (expected vs tool). The runner never edits a pack
file: if the tool and the hand workings disagree, the owner decides who is right (findings go to the owner, not into the pack).
"""

from pathlib import Path

import pytest
from pack_loader_p4 import load_pack_p4
from pack_runner_p4 import SECTIONS, format_report, run_pack_p4

pytestmark = pytest.mark.integration

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase4-greenfield-contractors-2026"

# Sections where the tool disagrees with the hand workings and the owner has not decided yet (reason = the finding).
FINDINGS: dict[str, str] = {}


@pytest.fixture(scope="module")
def p4_run(test_engine):
    pack = load_pack_p4(PACK)
    conn = test_engine.connect()
    transaction = conn.begin()
    try:
        report = run_pack_p4(conn, pack)
    finally:
        transaction.rollback()
        conn.close()
    print("\n" + format_report(report))
    return report


@pytest.mark.parametrize("section", SECTIONS)
def test_section_matches_the_hand_workings(request, p4_run, section):
    if section in FINDINGS:
        request.applymarker(pytest.mark.xfail(strict=True, reason=FINDINGS[section]))
    assert p4_run.problems[section] == [], "\n" + format_report(p4_run)


def test_counts(p4_run):
    assert p4_run.counts["vouchers_posted"] == 28
    assert p4_run.counts["challans"] == 5
    assert p4_run.counts["wrong_cases_refused"] == 11
