"""Package F, pure engine (engine/queue_edit.py): D-61 field edits on a copy of the payload; the original is never touched."""

import pytest

from app.engine import queue_edit as q


def payload():
    return {
        "invoice_no": {"value": "SS/101", "page": 2, "bbox": [0.1, 0.1, 0.2, 0.2], "confidence": "0.60"},
        "lines": [{"hsn_sac": {"value": "8415", "page": 1, "bbox": None, "confidence": "0.99"}},
                  {"hsn_sac": {"value": None, "page": None, "bbox": None, "confidence": None}}],
        "totals": {"grand_total": {"value": "2832.50", "page": 1, "bbox": None, "confidence": "0.90"}},
        "currency": "INR",
    }


def test_D61_edit_of_a_field_sets_value_and_confirms_it_keeping_page_and_box():
    original = payload()
    new, old = q.set_path(original, "invoice_no", " SS/102 ")
    assert old == "SS/101"
    assert new["invoice_no"] == {"value": "SS/102", "page": 2, "bbox": [0.1, 0.1, 0.2, 0.2], "confidence": "1"}
    assert original == payload()  # the input is untouched


def test_D61_edit_of_an_empty_line_field_gets_page_1():
    new, old = q.set_path(payload(), "lines[1].hsn_sac", "1701")
    assert old is None
    assert new["lines"][1]["hsn_sac"] == {"value": "1701", "page": 1, "bbox": None, "confidence": "1"}


def test_D61_nested_totals_and_blank_value_means_not_printed():
    new, old = q.set_path(payload(), "totals.grand_total", "")
    assert old == "2832.50"
    assert new["totals"]["grand_total"]["value"] is None


def test_D61_plain_scalar_is_set_directly():
    new, old = q.set_path(payload(), "currency", "USD")
    assert (old, new["currency"]) == ("INR", "USD")


@pytest.mark.parametrize("path", ["", "lines[5].hsn_sac", "nothing.here", ".x", "lines[a]", "lines[0].hsn_sac.value.deeper"])
def test_D61_bad_paths_are_refused(path):
    with pytest.raises(q.PathError):
        q.set_path(payload(), path, "x")


def test_D61_a_number_is_not_text_as_printed():
    with pytest.raises(q.PathError):
        q.set_path(payload(), "invoice_no", 101)


def test_D61_value_at_reads_the_value_of_a_field_or_a_scalar():
    assert q.value_at(payload(), "invoice_no") == "SS/101"
    assert q.value_at(payload(), "currency") == "INR"
    assert q.value_at(payload(), "lines[9].hsn_sac") is None
