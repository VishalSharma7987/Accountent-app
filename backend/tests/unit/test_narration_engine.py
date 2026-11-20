"""Package F, pure engine (engine/narration.py): D-40 key, D-41 / D-42 rule decision, D-43 strict reading of a model's choice.
Expected values are typed by hand."""

from decimal import Decimal

import pytest

from app.engine import narration as n


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("UPI/CR/412345678901/Ramesh Tea Stall/HDFC", "upi cr ramesh tea stall hdfc"),
        ("NEFT-HDFC24052600123-SHARMA TRADERS 12/05/2026", "neft sharma traders"),
        ("  Cheque No 004512 to   Gupta  ", "cheque no to gupta"),
        ("ATM WDL 05-Jan-2026 Andheri", "atm wdl andheri"),
        ("IMPS 2026-05-12 Verma & Sons", "imps verma sons"),
        ("123456", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_D40_narration_key(raw, expected):
    assert n.narration_key(raw) == expected


def test_D40_key_is_idempotent_and_same_payee_gives_same_key():
    a = n.narration_key("UPI/DR/111111111111/Ramesh Tea Stall/SBIN")
    b = n.narration_key("UPI/DR/222222222222/RAMESH TEA STALL/SBIN 03/06/2026")
    assert a == b == "upi dr ramesh tea stall sbin"
    assert n.narration_key(a) == a


def test_D41_one_ledger_is_suggested_with_count_as_reason():
    out = n.decide_from_rules([("L1", 3, True)])
    assert (out.status, out.chosen.ledger_id, out.chosen.count) == ("suggested", "L1", 3)
    assert out.reason == "Learned from 3 earlier entries with the same narration."


def test_D41_single_earlier_entry_wording():
    assert n.decide_from_rules([("L1", 1, True)]).reason == "Learned from 1 earlier entry with the same narration."


def test_D41_inactive_rules_are_ignored():
    assert n.decide_from_rules([("L1", 5, False)]).status == "none"
    out = n.decide_from_rules([("L1", 5, False), ("L2", 2, True)])
    assert (out.status, out.chosen.ledger_id) == ("suggested", "L2")


def test_D42_several_ledgers_is_ambiguous_nothing_chosen_sorted_by_count():
    out = n.decide_from_rules([("A", 1, True), ("B", 4, True), ("C", 4, True)])
    assert out.status == "ambiguous"
    assert out.chosen is None
    assert [(c.ledger_id, c.count) for c in out.candidates] == [("B", 4), ("C", 4), ("A", 1)]
    assert out.reason == "The same narration was booked to 3 different ledgers earlier; choose one. No ledger was selected."


def test_D41_no_rules_is_none():
    out = n.decide_from_rules([])
    assert (out.status, out.chosen, out.candidates) == ("none", None, ())


OPTIONS = {"L1": "ledger-one", "L2": "ledger-two"}


def test_D43_valid_choice_is_mapped_to_the_ledger_id():
    r = n.read_llm_choice({"choice": "L2", "confidence": Decimal("0.8")}, OPTIONS)
    assert (r.ledger_id, r.confidence, r.problem) == ("ledger-two", Decimal("0.8000"), None)


def test_D43_choice_not_in_the_list_is_dropped():
    r = n.read_llm_choice({"choice": "L9", "confidence": "0.9"}, OPTIONS)
    assert (r.ledger_id, r.problem is not None) == (None, True)
    # a real ledger id typed by the model is not an option either
    assert n.read_llm_choice({"choice": "ledger-one", "confidence": "0.9"}, OPTIONS).ledger_id is None


def test_D43_null_choice_means_no_suggestion_without_a_problem():
    r = n.read_llm_choice({"choice": None, "confidence": None}, OPTIONS)
    assert (r.ledger_id, r.problem) == (None, None)


@pytest.mark.parametrize(
    "answer",
    [
        {"choice": "L1", "confidence": "1.5"},
        {"choice": "L1", "confidence": "abc"},
        {"choice": "L1", "confidence": "0.5", "extra": "x"},
        {"choice": 1, "confidence": "0.5"},
        {"confidence": "0.5"},
        {"choice": ["L1"], "confidence": "0.5"},
    ],
)
def test_D53_malformed_choice_is_dropped(answer):
    r = n.read_llm_choice(answer, OPTIONS)
    assert r.ledger_id is None and r.problem


def test_D43_missing_confidence_is_allowed_and_stored_as_null():
    r = n.read_llm_choice({"choice": "L1"}, OPTIONS)
    assert (r.ledger_id, r.confidence) == ("ledger-one", None)
