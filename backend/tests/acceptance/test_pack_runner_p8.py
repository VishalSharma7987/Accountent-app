"""Phase 8 pack (audit assistant) against the real audit services with a FAKE language model. One run builds one synthetic client with one injected
error per audit check in a transaction that is rolled back; each section is asserted on its own so pytest shows which part differs. The failure text
is the report for the accountants (expected versus tool). The runner never edits a pack file: when the tool and the hand workings disagree, the owner
decides who is right (a confirmed tool bug is recorded as a strict xfail in FINDINGS below).

It never calls the network or the real model (the fake client only; the OpenRouter client and httpx are made to raise while it runs).
HEADLINE PROPERTY: every injected error appears in the audit report as a finding with non-empty evidence, no clean control is flagged, and the books
(row counts and a hash of every voucher and line) are unchanged after the audit.

Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/acceptance/test_pack_runner_p8.py`.
"""

from pathlib import Path

import pytest
from pack_loader_p8 import load_pack_p8
from pack_runner_p8 import SECTIONS, format_report, run_pack_p8

pytestmark = pytest.mark.integration

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase8-audit-checks-2026-27"

# Sections where the tool disagrees with the hand workings and the owner has not decided yet (reason = the finding).
FINDINGS: dict[str, str] = {}  # (the one tool bug found by the pack was fixed: audit_form now reads rule.status as well)


@pytest.fixture(scope="module")
def p8_run(test_engine):
    pack = load_pack_p8(PACK)
    conn = test_engine.connect()
    transaction = conn.begin()
    try:
        report = run_pack_p8(conn, pack)
    finally:
        transaction.rollback()
        conn.close()
    print("\n" + format_report(report))
    return report


@pytest.mark.parametrize("section", SECTIONS)
def test_section_matches_the_hand_workings(request, p8_run, section):
    if section in FINDINGS:
        request.applymarker(pytest.mark.xfail(strict=True, reason=FINDINGS[section]))
    assert p8_run.problems[section] == [], "\n" + format_report(p8_run)


def test_the_headline_property_every_injected_error_is_reported_with_evidence_and_the_books_are_unchanged(p8_run):
    assert p8_run.problems["headline"] == [], "\n" + format_report(p8_run)
    assert p8_run.counts["injected_errors"] == 18
    assert p8_run.counts["findings_fy26"] == 21 and p8_run.counts["findings_fy25"] == 1
    assert p8_run.counts["findings_matched_with_evidence"] == 22      # 21 of this year + 1 of last year, every one with its evidence
    assert p8_run.counts["controls_checked"] == 32


def test_nothing_reached_the_network_and_only_the_fake_model_was_used(p8_run):
    assert p8_run.counts["network_attempts"] == 0
    assert p8_run.counts["model_requests"] == 2
