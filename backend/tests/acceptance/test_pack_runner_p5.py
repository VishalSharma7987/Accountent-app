"""Phase 5 (Inventory) pack against the real services. One run builds three clients (FIFO, weighted average periodic, weighted
average moving) with the same April month inside one transaction that is rolled back; each section (method / part) is then asserted
on its own so pytest shows which part differs. The failure text is the report for the accountants (expected vs tool). The runner
never edits a pack file: if the tool and the hand workings disagree, the owner decides who is right.
"""

from pathlib import Path

import pytest
from pack_loader_p5 import load_pack_p5
from pack_runner_p5 import SECTIONS, format_report, run_pack_p5

pytestmark = pytest.mark.integration

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase5-fresh-pharma-apr-2026"

# Sections where the tool disagrees with the hand workings and the owner has not decided yet (reason = the finding).
FINDINGS: dict[str, str] = {}


@pytest.fixture(scope="module")
def p5_run(test_engine):
    pack = load_pack_p5(PACK)
    conn = test_engine.connect()
    transaction = conn.begin()
    try:
        report = run_pack_p5(conn, pack)
    finally:
        transaction.rollback()
        conn.close()
    print("\n" + format_report(report))
    return report


@pytest.mark.parametrize("section", SECTIONS)
def test_section_matches_the_hand_workings(request, p5_run, section):
    if section in FINDINGS:
        request.applymarker(pytest.mark.xfail(strict=True, reason=FINDINGS[section]))
    assert p5_run.problems[section] == [], "\n" + format_report(p5_run)


def test_counts(p5_run):
    assert p5_run.counts["vouchers_posted"] == 30  # 10 invoices x 3 clients
    assert p5_run.counts["journals_posted"] == 6  # 2 stock journals x 3 clients
    assert p5_run.counts["wrong_cases_refused"] == 21  # 7 wrong cases x 3 clients
