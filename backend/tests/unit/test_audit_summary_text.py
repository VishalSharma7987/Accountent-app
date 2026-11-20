"""Package F: the audit summary prompt text and the check that a summary only quotes what the findings say (no model, no database)."""

from decimal import Decimal

from app.ai import prompts_audit as p

F1 = p.SummaryFinding("id1", "A-05", "error", "Cash payments to Sharma Traders on 14-08-2026 total 11,000.00, above the daily limit of 10,000.00 "
                      "(limit pending verification)", "14-08-2026", Decimal("11000.00"), "Sharma Traders")
F2 = p.SummaryFinding("id2", "A-06", "error", "Cash receipts from Mehta & Co on 03-09-2026 total 2,00,000.00", "03-09-2026",
                      Decimal("200000.00"), "Mehta & Co")
SENT = p.build_user([F1, F2])


def test_A_summary_user_text_has_counts_codes_indian_amounts_and_the_markers():
    assert SENT.splitlines()[0] == "Findings listed: 2 of 2"
    assert SENT.splitlines()[1] == "Per check: A-05: 1; A-06: 1"
    assert "F1 | check A-05 | severity error | date 14-08-2026 | amount 11,000.00 | ref Sharma Traders | Cash payments" in SENT
    assert "F2 | check A-06 | severity error | date 03-09-2026 | amount 2,00,000.00" in SENT
    assert "<<<FINDINGS_START>>>" in SENT and SENT.rstrip().endswith("<<<FINDINGS_END>>>")


def test_A_summary_truncated_list_states_how_many_are_listed():
    assert p.build_user([F1], total=75).splitlines()[0] == "Findings listed: 1 of 75"


def test_A_summary_a_faithful_text_passes():
    text = ("F1 (check A-05): cash payments to Sharma Traders on 14-08-2026 total 11,000.00, above the limit of 10,000.00. "
            "F2 (check A-06): cash receipts of 2,00,000.00 from Mehta & Co on 03-09-2026. 2 findings in all.")
    assert p.check_summary(text, SENT) == []


def test_A_summary_amount_comparison_ignores_commas_and_trailing_zeros():
    assert p.check_summary("F1 is about 11000 paid in cash.", SENT) == []


def test_A_summary_an_invented_amount_is_rejected():
    problems = p.check_summary("F1: Sharma Traders were paid 12,500.00 in cash.", SENT)
    assert problems == ["The summary quotes the number 12,500.00, which is not in the findings."]


def test_A_summary_a_calculated_total_is_rejected():
    problems = p.check_summary("Cash of 2,11,000.00 is involved in F1 and F2.", SENT)
    assert problems == ["The summary quotes the number 2,11,000.00, which is not in the findings."]


def test_A_summary_an_unknown_finding_code_or_check_id_is_rejected():
    problems = p.check_summary("See F3 and check A-09.", SENT)
    assert "The summary refers to A-09, which is not in the findings." in problems
    assert "The summary refers to F3, which is not in the findings." in problems


def test_A_summary_an_unknown_voucher_number_is_rejected():
    sent = p.build_user([p.SummaryFinding("i", "A-04", "error", "Number PUR/2026-27/0003 is missing", None, None, "PUR/2026-27/0003")])
    assert p.check_summary("F1: PUR/2026-27/0003 is missing.", sent) == []
    assert "The summary refers to PUR/2026-27/0004, which is not in the findings." in p.check_summary("F1: PUR/2026-27/0004 is missing.", sent)


def test_A_summary_conclusion_and_opinion_words_are_rejected():
    assert p.check_summary("In our opinion the books are compliant.", SENT) == [
        "The summary uses the conclusion wording 'compliant': only the accountant concludes.",
        "The summary uses the conclusion wording 'opinion': only the accountant concludes."]
    assert p.check_summary("F1 is cleared.", SENT) == ["The summary uses the conclusion wording 'cleared': only the accountant concludes."]


def test_A_summary_empty_text_is_rejected():
    assert p.check_summary("   ", SENT) == ["The summary is empty."]


def test_A_summary_the_fixed_prompt_forbids_conclusions_and_calculation():
    assert "never give an opinion or a conclusion" in p.SYSTEM and "never calculate" in p.SYSTEM
