"""Phase 7 pack (documents and AI) against the real services with a FAKE language model. One run builds two clients in one transaction that is
rolled back; each section is asserted on its own so pytest shows which part differs. The failure text is the report for the accountants
(expected versus tool). The runner never edits a pack file: when the tool and the hand workings disagree, the owner decides who is right.

It never calls the network or the real model (the fake client only; the OpenRouter client and httpx are made to raise while it runs).
The headline property is asserted over the whole pack: no voucher with a blocking finding is ever approvable or postable, and every posted
voucher came from an accepted queue item.

Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/acceptance/test_pack_runner_p7.py`.
"""

from pathlib import Path

import pytest
from pack_loader_p7 import load_pack_p7
from pack_runner_p7 import SECTIONS, format_report, run_pack_p7

pytestmark = pytest.mark.integration

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase7-documents-and-ai-2026-27"

# Sections where the tool disagrees with the hand workings and the owner has not decided yet (reason = the finding).
FINDINGS: dict[str, str] = {}


@pytest.fixture(scope="module")
def p7_run(test_engine):
    pack = load_pack_p7(PACK)
    conn = test_engine.connect()
    transaction = conn.begin()
    try:
        report = run_pack_p7(conn, pack)
    finally:
        transaction.rollback()
        conn.close()
    print("\n" + format_report(report))
    return report


@pytest.mark.parametrize("section", SECTIONS)
def test_section_matches_the_hand_workings(request, p7_run, section):
    if section in FINDINGS:
        request.applymarker(pytest.mark.xfail(strict=True, reason=FINDINGS[section]))
    assert p7_run.problems[section] == [], "\n" + format_report(p7_run)


def test_the_headline_property_no_blocked_voucher_is_posted_and_every_posted_voucher_was_accepted(p7_run):
    assert p7_run.problems["headline"] == [], "\n" + format_report(p7_run)
    assert p7_run.counts["vouchers_posted"] == 11
    assert p7_run.counts["pending_items_refused"] == 2     # the two items still pending are refused by accept
    assert p7_run.counts["approve_refused_before_accept"] == 12


def test_nothing_reached_the_network_and_only_the_fake_model_was_used(p7_run):
    assert p7_run.counts["network_attempts"] == 0
    assert p7_run.counts["model_requests"] == 17
