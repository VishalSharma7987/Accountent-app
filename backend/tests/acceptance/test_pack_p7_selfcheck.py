"""Internal consistency of the Phase 7 pack docs/test-packs/phase7-documents-and-ai-2026-27 (no database, no service, no engine, no model).

Plain csv / Decimal / regex arithmetic only. Every figure asserted here is typed by hand (WORKING.md); everything else is re-derived from the
pack's own inputs (texts, scripted answers, XML) and compared with the expected_*.csv files, so a slip in a hand-typed expected file is caught
before the tool is blamed. The only app code used is the PURE bank CSV reader and the PURE Tally XML reader, to show the inputs are readable.
"""

import copy
import json
import os
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from pack_loader_p7 import MARKER, load_pack_p7

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase7-documents-and-ai-2026-27"
REPO = Path(__file__).resolve().parents[3]
D = Decimal
ZERO = D("0.00")
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
PAN_RE = re.compile(r"[A-Za-z]{5}\d{4}[A-Za-z]")
AADHAAR_RE = re.compile(r"(?<!\d)[2-9]\d{3} \d{4} \d{4}(?!\d)")
ACCOUNT_RE = re.compile(r"A/c No\. (\d{6,18})|Account No: (\d{6,18})")
# typed by hand from the seeded EXAMPLE rate rules (database/seeds/0005): rate in percent by HSN / SAC on the invoice dates of the pack
RATE = {"8415": D("18"), "1701": D("5"), "851712": D("18"), "9983": D("18"), "3004": D("5")}
# the sixteen real GSTINs of the pack and the check character each must have (hand-computed with the mod-36 rule of docs/PHASE3_LEGAL_VALUES.md)
GSTINS = {"27AAAPL1234C1ZE": True, "27CCCPM4321E1ZZ": True, "29AAAPK5678F1ZH": True, "27BBBPV9012G1ZK": True, "27DDDPG3456H1ZL": True,
          "27CCCPM4321E1ZX": False}


def q2(value: Decimal) -> Decimal:
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def check_char(first14: str) -> str:
    total = 0
    for i, c in enumerate(first14):
        p = ALPHABET.index(c) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return ALPHABET[(36 - total % 36) % 36]


@pytest.fixture(scope="module")
def pack():
    return load_pack_p7(PACK)


def all_files():
    return [p for p in PACK.rglob("*") if p.is_file()]


# ------------------------------------------------------------------------------------------------------------------- the inputs


def test_the_marker_file_keeps_the_earlier_runners_away():
    assert (PACK / MARKER).is_file() and MARKER == "phase7.yaml"
    import test_pack_runner as earlier  # the Phase 1 runner lists packs by marker files

    assert PACK.name not in [p.name for p in earlier.PACKS]
    for other in ("allocations.csv", "gst_registrations.csv", "deductees.csv", "godowns.csv", "phase6.yaml"):
        assert not (PACK / other).exists()


def test_every_document_has_a_text_a_matching_pdf_and_a_scripted_answer(pack):
    assert [d.doc_id for d in pack.docs] == ["P7-01", "P7-02", "P7-03", "P7-04", "P7-05", "P7-06", "P7-07", "P7-08", "P7-09", "P7-11",
                                             "P7-12", "P7-B1", "P7-10"]
    for d in pack.docs:
        assert (PACK / "pdf" / f"{d.doc_id}.pdf").is_file()
        assert pack.answers[d.doc_id]
    assert len(pack.answers["P7-01"]) == 2 and all(len(pack.answers[d.doc_id]) == 1 for d in pack.docs if d.doc_id != "P7-01")


def test_the_pdfs_carry_the_same_text_as_the_txt_files(pack):
    pypdf = pytest.importorskip("pypdf")
    for d in pack.docs:
        reader = pypdf.PdfReader(str(PACK / "pdf" / f"{d.doc_id}.pdf"))
        assert len(reader.pages) == 1
        assert " ".join(reader.pages[0].extract_text().split()) == " ".join(d.text.split()), d.doc_id


def test_no_api_key_text_in_any_file_of_the_pack_or_of_this_package():
    mine = [PACK, REPO / "scripts" / "build_pack_p7_inputs.py", REPO / "scripts" / "build_verification_sheet_p7.py"] +         sorted((REPO / "backend" / "tests" / "acceptance").glob("*p7*.py"))
    files = [p for m in mine for p in ([m] if m.is_file() else sorted(m.rglob("*")))
             if p.is_file() and p.suffix in (".txt", ".csv", ".json", ".xml", ".yaml", ".md", ".py")]
    assert files
    env = REPO / ".env"
    key = ""
    if env.is_file():   # compared, never printed
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    key = key or os.environ.get("OPENROUTER_API_KEY", "")
    for path in files:
        body = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix != ".py":   # the python files only name the prefix in order to look for it
            assert "sk-or-" not in body, path.name
        if len(key) >= 12:
            assert key not in body, path.name


def test_the_gstins_have_the_check_characters_the_pack_says():
    for gstin, valid in GSTINS.items():
        assert (check_char(gstin[:14]) == gstin[14]) is valid, gstin
        assert GSTIN_RE.fullmatch(gstin)


# ------------------------------------------------------------------------------------------------------------------- masking evidence


def test_masking_counts_in_the_pack_equal_what_the_texts_contain(pack):
    for d in pack.docs:
        want = pack.masking[d.doc_id]
        gstins = GSTIN_RE.findall(d.text)
        text_wo_gstin = GSTIN_RE.sub(" ", d.text)
        pans = PAN_RE.findall(text_wo_gstin)
        aadhaar = AADHAAR_RE.findall(d.text)
        accounts = ACCOUNT_RE.findall(d.text)
        assert (len(gstins), len(pans), len(aadhaar), len(accounts)) == (want["gstin"], want["pan"], want["aadhaar"], want["account"]), d.doc_id
        for g in gstins:
            assert g in GSTINS, f"{d.doc_id}: {g} is not one of the known synthetic GSTINs"
    assert pack.masking["P7-01"]["calls"] == 2 and all(v["calls"] == 1 for k, v in pack.masking.items() if k != "P7-01")


def test_no_nine_digit_run_hides_in_a_text_except_the_account_number(pack):
    for d in pack.docs:
        runs = re.findall(r"(?<![\d.])\d{9,}(?![\d])", d.text)
        assert runs == (["50100123456789"] if d.doc_id in ("P7-02", "P7-B1") else []), d.doc_id


def test_the_gstin_tokens_in_the_scripted_answers_point_to_the_gstins_of_the_text(pack):
    for d in pack.docs:
        if d.doc_id == "P7-B1":
            continue
        order = list(dict.fromkeys(GSTIN_RE.findall(d.text)))   # [GSTIN_n] numbering = order of first appearance
        seller = re.search(r"GSTIN: (\S+)", d.text).group(1)
        buyer = re.search(r"Buyer GSTIN: (\S+)", d.text).group(1)
        answer = pack.answers[d.doc_id][-1]
        for key, expected in (("supplier_gstin", seller), ("buyer_gstin", buyer)):
            token = answer[key]["value"]
            n = int(re.fullmatch(r"\[GSTIN_(\d+)\]", token).group(1))
            assert order[n - 1] == expected, (d.doc_id, key)


# ------------------------------------------------------------------------------------------------------------------- hand recomputation


def num(text_value: str) -> Decimal:
    return D(text_value.replace(",", ""))


# truth per posted invoice: (kind, tax heads, [(taxable, hsn)], expense ledger, party ledger); typed from the paper (the texts), not from the answers
TRUTH = {
    "P7-01": ("purchase", "intra", [("2000.00", "8415"), ("450.00", "1701")], "Purchases", "Shree Traders"),
    "P7-02": ("purchase", "inter", [("10000.00", "851712")], "Purchases", "Kumar Electricals"),
    "P7-03": ("purchase", "intra", [("4000.00", "9983")], "Repairs & Maintenance", "Shree Traders"),
    "P7-04": ("purchase", "intra", [("20000.00", "8415")], "Purchases", "Shree Traders"),
    "P7-07": ("purchase", "intra", [("2000.00", "1701"), ("1000.00", "1701"), ("500.00", "1701")], "Purchases", "Shree Traders"),
    "P7-08": ("purchase", "intra", [("10000.00", "8415")], "Purchases", "Shree Traders"),
    "P7-11": ("purchase", "intra", [("30000.00", "8415")], "Purchases", "Verma Cooling Solutions"),
    "P7-12": ("credit_note", "intra", [("5000.00", "3004")], "Sales Returns", "Gamma Retail"),
}


def test_expected_postings_equal_the_hand_recomputation_of_the_tax_of_each_posted_invoice(pack):
    for doc_id, (kind, heads, lines, ledger, party) in TRUTH.items():
        prefix = "Input" if kind == "purchase" else "Output"
        taxable = sum((D(t) for t, _ in lines), ZERO)
        want: dict[str, tuple[Decimal, Decimal]] = {ledger: (taxable, ZERO)}
        total_tax = ZERO
        if heads == "intra":
            half = sum((q2(D(t) * RATE[h] / 2 / 100) for t, h in lines), ZERO)
            want[f"{prefix} CGST"] = (half, ZERO)
            want[f"{prefix} SGST"] = (half, ZERO)
            total_tax = half * 2
        else:
            igst = sum((q2(D(t) * RATE[h] / 100) for t, h in lines), ZERO)
            want[f"{prefix} IGST"] = (igst, ZERO)
            total_tax = igst
        want[party] = (ZERO, taxable + total_tax)
        got = {name: (dr, cr) for name, dr, cr in pack.postings[doc_id]}
        assert got == want, doc_id


def test_the_printed_amounts_of_the_paper_add_up_the_way_the_expected_postings_say(pack):
    """Independent of the tax table: each text's own printed lines and totals agree with the expected posting of that document."""
    for doc_id in TRUTH:
        text_body = next(d.text for d in pack.docs if d.doc_id == doc_id)
        grand = num(re.search(r"(?:Grand total|Total credited): ([\d,.]+)", text_body).group(1))
        party_credit = max(cr for _, _, cr in pack.postings[doc_id])
        debit_total = sum(dr for _, dr, _ in pack.postings[doc_id])
        if doc_id == "P7-03":   # the supplier's own bill is 0.50 off (printed CGST 360.50); the tool books the recomputed 4,720.00 (a warning)
            assert (grand, party_credit, debit_total) == (D("4720.50"), D("4720.00"), D("4720.00"))
            continue
        assert grand == party_credit == debit_total, doc_id
        taxable = num(re.search(r"Total taxable value: ([\d,.]+)", text_body).group(1))
        first = pack.postings[doc_id][0]
        assert first[1] == taxable, doc_id


def test_every_expected_voucher_balances_and_the_balances_are_their_sum(pack):
    for doc_id, rows in pack.postings.items():
        assert sum(r[1] for r in rows) == sum(r[2] for r in rows), doc_id
    client_of = lambda item: "B" if item.startswith("TB") else "A"
    sums: dict[str, dict[str, Decimal]] = {"A": defaultdict(lambda: ZERO), "B": defaultdict(lambda: ZERO)}
    for item, rows in pack.postings.items():
        for ledger, dr, cr in rows:
            sums[client_of(item)][ledger] += dr - cr
    for client in ("A", "B"):
        want = {ledger: dr - cr for ledger, dr, cr in pack.balances[client]}
        assert dict(sums[client]) == want, client
        assert sum(dr for _, dr, _ in pack.balances[client]) == pack.balance_totals[client][0]
        assert sum(cr for _, _, cr in pack.balances[client]) == pack.balance_totals[client][1]
        assert pack.balance_totals[client][0] == pack.balance_totals[client][1]


def test_decisions_agree_with_postings_findings_and_the_headline(pack):
    h = pack.config["headline"]
    posted = [k for k, d in pack.decisions.items() if d.final_voucher_status == "posted"]
    assert sorted(posted) == sorted(pack.postings)
    status = [d.final_queue_status for d in pack.decisions.values()]
    assert (len(status), status.count("accepted"), status.count("rejected"), status.count("pending")) == (
        h["queue_items_total"], h["accepted"], h["rejected"], h["pending"])
    assert len(posted) == h["vouchers_posted"] == h["accepted"]
    for item, d in pack.decisions.items():
        assert (d.final_voucher_status == "posted") == (d.final_queue_status == "accepted"), item     # nothing is posted that was not accepted
        if d.final_voucher_status == "posted":
            assert d.blocking_final == 0, item                                                         # an accepted item has no blocking finding
        initial = pack.findings.get((item, "initial"), set())
        blocking = {f for f in initial if f[1] in ("error", "review")}
        assert d.blocking_initial >= len(blocking) and d.warnings_initial >= len({f for f in initial if f[1] == "warning"}), item
        if blocking:
            assert not d.draft_initially, f"{item}: a draft must not exist while a finding blocks"
        if d.draft_initially:
            assert d.blocking_initial == 0, item
    numbers = [d.voucher_number for d in pack.decisions.values() if d.voucher_number]
    assert numbers == [f"PUR/2026-27/{n:04d}" for n in range(1, 9)]                                     # no gaps: numbers are given at posting
    # approve is tried before accept on every item that is accepted (11) and on the drafted Tally item that is rejected (TA-1): 12
    assert h["approve_refused_before_accept"] == len(posted) + 1 == 12
    assert pack.decisions["TA-1"].draft_initially and pack.decisions["TA-1"].final_queue_status == "rejected"


def test_the_accountants_script_only_uses_known_items_and_ends_every_posted_item_with_approve_post(pack):
    assert set(pack.script) == set(pack.decisions)
    for item, steps in pack.script.items():
        actions = [s.action for s in steps]
        assert (actions[-1] == "approve_post") == (pack.decisions[item].final_voucher_status == "posted"), item
        if pack.decisions[item].final_queue_status == "rejected":
            assert actions[-1] == "reject", item
        first_accept = next((a for a in actions if a.startswith("accept")), None)
        want = {"ok": ("accept", "accept_clean"), "refused": ("accept_refused",), "na": (None,)}[pack.decisions[item].first_accept]
        assert first_accept in want, item


def test_the_corrected_answers_say_what_the_paper_says(pack):
    """Apply the accountant's scripted edits to the model's answer; every value that remains must be readable on the paper."""
    for d in pack.docs:
        if d.doc_id == "P7-B1":
            continue
        answer = copy.deepcopy(pack.answers[d.doc_id][-1])
        for step in pack.script.get(d.doc_id, []):
            if step.action == "edit":
                for path, value, _ in step.args:
                    m = re.fullmatch(r"lines\[(\d+)\]\.(\w+)", path)
                    if m:
                        answer["lines"][int(m.group(1))][m.group(2)]["value"] = value
                    elif path.startswith("totals."):
                        answer["totals"][path.split(".")[1]]["value"] = value
                    elif path in answer:
                        answer[path]["value"] = value
            elif step.action == "add_line":
                answer["lines"].append(json.loads((PACK / step.args[0][0]).read_text(encoding="utf-8")))
        page = d.text.lower().replace(",", "")
        fields = [answer[k] for k in ("document_kind", "supplier_name", "buyer_name", "invoice_no", "invoice_date", "place_of_supply",
                                      "original_invoice_no") if k in answer]
        fields += [f for line in answer["lines"] for f in line.values()] + list(answer["totals"].values())
        for f in fields:
            v = f["value"]
            if v is None or v.startswith("["):
                continue
            assert v.lower().replace(",", "") in page, f"{d.doc_id}: '{v}' is not on the paper"


def test_the_deliberately_wrong_answers_differ_from_the_paper_exactly_where_the_pack_says(pack):
    paper = {d.doc_id: d.text.lower().replace(",", "") for d in pack.docs}
    wrong = {"P7-04": [("lines", 0, "cgst", "1900.00"), ("totals", None, "cgst_total", "1900.00"), ("totals", None, "grand_total", "23700.00")],
             "P7-05": [("lines", 0, "gst_rate", "12"), ("lines", 0, "cgst", "240.00"), ("lines", 0, "sgst", "240.00")],
             "P7-11": [("totals", None, "grand_total", "35040.00")]}
    for doc_id, items in wrong.items():
        answer = pack.answers[doc_id][-1]
        for kind, idx, key, value in items:
            got = answer["lines"][idx][key]["value"] if kind == "lines" else answer["totals"][key]["value"]
            assert got.replace(",", "") == value
            if "." in value:   # an amount: the paper must not print what the model read
                assert value not in paper[doc_id], (doc_id, key)
    # a line the reader missed: the paper has three lines, the answer two
    assert len(pack.answers["P7-07"][-1]["lines"]) == 2 and paper["P7-07"].count("sugar m-30 grade") == 3
    # the first answer of P7-01 has a key the schema does not have; the second is the plain correct one
    assert "amount_in_words" in pack.answers["P7-01"][0] and "amount_in_words" not in pack.answers["P7-01"][1]
    # the bank text: the model misread one running balance (54,320.00 for 54,230.00)
    assert "54,230.00" in next(d.text for d in pack.docs if d.doc_id == "P7-B1")
    assert pack.answers["P7-B1"][0]["lines"][2]["balance"]["value"] == "54,320.00"


def test_p7_03_has_a_low_confidence_field_and_an_instruction_hidden_in_the_text(pack):
    a = pack.answers["P7-03"][0]
    assert a["invoice_date"]["confidence"] == 0.60 and a["invoice_no"]["confidence"] == 0.95
    assert "ignore all previous instructions" in next(d.text for d in pack.docs if d.doc_id == "P7-03").lower()
    assert a["totals"]["grand_total"]["value"] == "4,720.50"   # the model did NOT obey it


def test_p7_10_is_the_same_bill_as_p7_01_and_arrives_last(pack):
    docs = {d.doc_id: d for d in pack.docs}
    assert pack.answers["P7-10"][0] == pack.answers["P7-01"][1]
    assert docs["P7-10"].arrives == "last" and docs["P7-01"].arrives == "first"
    assert docs["P7-10"].text != docs["P7-01"].text           # a different file (different SHA-256), the same invoice number
    assert "SH/0101" in docs["P7-10"].text and "SH/0101" in docs["P7-01"].text


# ------------------------------------------------------------------------------------------------------------------- bank CSV and narration


def test_the_bank_csv_reads_cleanly_and_the_chain_of_balances_is_exact(pack):
    from app.importers.bank_statement import parse_statement

    bank = pack.config["bank"]
    parsed = parse_statement(pack.bank_csv, bank["mapping"], bank["opening_balance"], bank["closing_balance"])
    assert parsed.problems == []
    assert [(l.debit, l.credit, l.balance) for l in parsed.lines] == [
        (D("150.00"), ZERO, D("49850.00")), (D("200.00"), ZERO, D("49650.00")), (D("900.00"), ZERO, D("48750.00")),
        (D("450.00"), ZERO, D("48300.00")), (D("380.00"), ZERO, D("47920.00")), (D("120.00"), ZERO, D("47800.00"))]
    running = D(bank["opening_balance"])
    for l in parsed.lines:
        running = running + l.credit - l.debit
        assert running == l.balance
    assert running == D(bank["closing_balance"])
    assert len(pack.narration) == len(parsed.lines) == 6


def test_the_narration_script_has_a_rule_an_ambiguity_a_dropped_model_answer_and_a_switch_off_step(pack):
    by_step = {s.step: s for s in pack.narration}
    assert (by_step[1].source, by_step[2].source) == ("llm", "rule") and by_step[2].model_called == 0
    assert by_step[3].status == "ambiguous" and by_step[3].detail == "Tea Expense:3|Staff Welfare:1"
    assert json.loads(by_step[4].model["raw"])["choice"] == "L999" and by_step[4].status == "none"
    assert by_step[6].status == "llm_blocked" and by_step[6].model_called == 0
    assert {(d, k, led, n) for d, k, led, n in pack.narration_rules} == {
        ("debit", "cheque no to gupta", "Tea Expense", 3), ("debit", "cheque no to gupta", "Staff Welfare", 1)}


# ------------------------------------------------------------------------------------------------------------------- Tally


def test_the_tally_files_read_and_their_vouchers_balance_except_the_one_that_should_not():
    from app.importers.tally_xml import TallyParseError, parse_tally_xml

    a = parse_tally_xml((PACK / "tally" / "tally_a_masters_vouchers.xml").read_bytes())
    b = parse_tally_xml((PACK / "tally" / "tally_b_second_company.xml").read_bytes())
    assert (len(a.groups), len(a.ledgers), len(a.vouchers)) == (1, 10, 7) and (len(b.groups), len(b.ledgers), len(b.vouchers)) == (1, 4, 2)
    difference = {v.number: -sum((e.amount for e in v.entries), D("0.00")) for v in a.vouchers + b.vouchers if v.entries}
    # Tally: debit = negative amount, credit = positive; the sum of all amounts of a balanced voucher is zero
    assert {n: d for n, d in difference.items() if d != 0} == {"J-1": D("100.00")}
    with pytest.raises(TallyParseError):
        parse_tally_xml((PACK / "tally" / "tally_c_rejected_dtd.xml").read_bytes())


def test_the_tally_expectations_match_the_files(pack):
    t = pack.tally
    assert t[("import_a", "counts")] == "groups=1;ledgers=10;stock_items=0;vouchers=7"
    assert t[("import_b", "counts")] == "groups=1;ledgers=4;stock_items=0;vouchers=2"
    # A: 10 ledgers, 8 exist in the client with the suggested group (confirmed in one click), 2 are new (Tally New Vendor, Rent Paid)
    assert int(t[("import_a", "confirmed_exact")]) + int(t[("import_a", "ledgers_created")]) == 10
    # B: Mystery Ledger is skipped, the other 3 exist
    assert int(t[("import_b", "confirmed_exact")]) + 1 == 4
    assert int(t[("export_a", "voucher_count")]) + int(t[("export_b", "voucher_count")]) == pack.config["headline"]["vouchers_posted"]
    assert int(t[("export_a", "voucher_count")]) == 8 + 2 and int(t[("export_a", "ledger_count")]) == len(pack.balances["A"])
    assert int(t[("export_b", "ledger_count")]) == len(pack.balances["B"])
