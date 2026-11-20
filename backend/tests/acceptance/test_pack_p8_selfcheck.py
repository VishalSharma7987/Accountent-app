"""Internal consistency of the Phase 8 pack docs/test-packs/phase8-audit-checks-2026-27 (no database, no service, no engine, no model).

Plain csv / Decimal / date arithmetic only. Every figure asserted literally here was typed by hand (WORKING.md). Everything else is re-derived from the
pack's own INPUT files by an independent calculation and compared with the hand-typed expected_*.csv files, so a slip in an expected file is caught
before the tool is blamed. The sampling cases are re-derived with an independent SplitMix64 written in this file.
"""

import itertools
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from pack_loader_p8 import CHECK_IDS, MARKER, load_pack_p8

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase8-audit-checks-2026-27"
REPO = Path(__file__).resolve().parents[3]
D = Decimal
ZERO = D("0.00")
LIMIT_PAYMENT, LIMIT_RECEIPT = D("10000.00"), D("200000.00")


@pytest.fixture(scope="module")
def pack():
    return load_pack_p8(PACK)


def live(pack):
    return [v for v in pack.vouchers if v.fy == "F26"]


def refs(vs):
    return sorted(v.ref for v in vs)


# ------------------------------------------------------------------------------------------------------------------- the pack as a whole


def test_the_marker_file_keeps_the_earlier_runners_away():
    assert (PACK / MARKER).is_file() and MARKER == "phase8.yaml"
    import test_pack_runner as earlier  # the Phase 1 runner lists packs by marker files

    assert PACK.name not in [p.name for p in earlier.PACKS]
    for other in ("allocations.csv", "gst_registrations.csv", "deductees.csv", "godowns.csv", "phase6.yaml", "phase7.yaml"):
        assert not (PACK / other).exists()


def test_the_pack_has_41_vouchers_of_this_year_and_3_of_the_last_and_every_voucher_balances(pack):
    assert len(live(pack)) == 41 and len([v for v in pack.vouchers if v.fy == "F25"]) == 3
    for v in pack.vouchers:
        assert sum(ln[1] for ln in v.lines) == sum(ln[2] for ln in v.lines), v.ref
        assert all((ln[1] > 0) != (ln[2] > 0) for ln in v.lines), v.ref
    assert sum(o[1] for o in pack.openings) == sum(o[2] for o in pack.openings) == D("700000.00")


def test_exactly_one_error_is_injected_per_check_and_the_expected_files_agree(pack):
    injected = [f for f in pack.findings if f.run == "FY26" and f.kind == "injected"]
    assert sorted(f.check_id for f in injected) == list(CHECK_IDS)
    fy26 = [f for f in pack.findings if f.run == "FY26"]
    assert len(fy26) == 21 and len([f for f in pack.findings if f.run == "FY25"]) == 1
    by_sev = defaultdict(int)
    for f in fy26:
        by_sev[f.severity] += 1
    assert dict(by_sev) == pack.config["headline"]["by_severity"] == {"error": 10, "warning": 4, "review": 2, "info": 5}
    assert sum((f.disallowance or ZERO for f in fy26), ZERO) == D("11000.00") == D(pack.config["headline"]["disallowance_total"])
    assert sorted(f.id for f in fy26 if f.kind != "injected") == ["F-13", "F-15", "F-18"]
    assert {f.check_id for f in fy26 if f.evidence_vouchers or f.evidence_ledgers or f.evidence_values}   # every expected finding names its evidence
    assert all(f.evidence_values for f in pack.findings)
    assert len([k for k in pack.summary if k[0] == "FY26"]) == 18


def test_every_control_is_not_an_expected_finding_of_its_check(pack):
    assert len(pack.controls) == 32
    for c in pack.controls:
        mine = [f for f in pack.findings if f.run == "FY26" and f.check_id == c.check_id]
        if c.kind == "voucher":
            assert all(c.target not in f.evidence_vouchers for f in mine), c.id
        elif c.kind == "ledger":
            assert all(c.target not in f.evidence_ledgers and c.target != f.subject_ref for f in mine), c.id
        else:
            assert all(c.target not in " ".join(v for _, v in f.evidence_values) for f in mine), c.id


def test_no_api_key_text_in_any_file_of_the_pack_or_of_this_package():
    mine = [PACK, REPO / "scripts" / "build_pack_p8_inputs.py", REPO / "scripts" / "build_verification_sheet_p8.py"] + \
        sorted((REPO / "backend" / "tests" / "acceptance").glob("*p8*.py"))
    files = [p for m in mine for p in ([m] if m.is_file() else sorted(m.rglob("*"))) if p.is_file() and p.suffix in (".csv", ".json", ".yaml", ".md", ".py")]
    assert files
    key = ""
    env = REPO / ".env"
    if env.is_file():   # compared, never printed
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    key = key or os.environ.get("OPENROUTER_API_KEY", "")
    for path in files:
        body = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix != ".py":
            assert "sk-or-" not in body, path.name
        if len(key) >= 12:
            assert key not in body, path.name


def test_the_gstin_has_the_check_character_the_pack_says():
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    gstin = "27AAAPL1234C1ZE"
    total = 0
    for i, ch in enumerate(gstin[:14]):
        p = alphabet.index(ch) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    assert alphabet[(36 - total % 36) % 36] == gstin[14]


# ------------------------------------------------------------------------------------------------------------------- A-01 .. A-06 re-derived


def test_A01_A02_A03_A04_are_re_derived_from_the_inputs(pack):
    vs = live(pack)

    def norm(text):
        return "".join(ch for ch in text.casefold() if ch.isalnum())

    bills = defaultdict(list)
    for v in vs:
        if v.voucher_type == "purchase" and v.party and norm(v.reference_no):
            bills[(v.party, norm(v.reference_no))].append(v.ref)
    assert {k: r for k, r in bills.items() if len(r) > 1} == {("Kumar Steel", "inv17"): ["V-04", "V-05"]}
    assert sum(len(r) for r in bills.values()) == 11 == pack.summary[("FY26", "A-01")][1]

    pays = defaultdict(list)
    for v in vs:
        if v.voucher_type == "payment" and v.party:
            pays[(v.party, v.total)].append(v)
    dup = []
    for group in pays.values():
        group.sort(key=lambda x: x.on)
        for a, b in itertools.pairwise(group):
            if (b.on - a.on).days <= 7:
                dup.append((a.ref, b.ref))
    assert dup == [("V-16", "V-17")]
    assert sum(len(g) for g in pays.values()) == 14 == pack.summary[("FY26", "A-02")][1]

    needing = [v for v in vs if v.voucher_type in ("purchase", "payment", "debit_note")]
    assert [v.ref for v in needing if not v.document] == ["V-08"] and len(needing) == 26 == pack.summary[("FY26", "A-03")][1]

    numbers = defaultdict(set)
    for v in vs:
        numbers[v.voucher_type].add(int(v.number.rsplit("/", 1)[1]))
    gaps = {t: sorted(set(range(1, max(n) + 1)) - n) for t, n in numbers.items()}
    assert {t: g for t, g in gaps.items() if g} == {"sales": [3]}
    assert sum(len(n) for n in numbers.values()) == 41 == pack.summary[("FY26", "A-04")][1]


def cash_lines(v, ledgers=("Cash", "Petty Cash")):
    return [ln for ln in v.lines if ln[0] in ledgers]


def test_A05_A06_cash_limits_are_re_derived_from_the_inputs(pack):
    day = defaultdict(lambda: ZERO)
    count = 0
    for v in live(pack):
        if v.voucher_type == "payment" and sum(ln[2] for ln in cash_lines(v)) > 0:
            count += 1
            person = v.party or next(ln[0] for ln in v.lines if ln[1] > 0)
            day[(person, v.on)] += sum(ln[2] for ln in cash_lines(v))
    assert {k: t for k, t in day.items() if t > LIMIT_PAYMENT} == {("Sharma Traders", date(2026, 8, 14)): D("11000.00")}
    assert day[("Sharma Traders", date(2026, 8, 17))] == LIMIT_PAYMENT and count == 4 == pack.summary[("FY26", "A-05")][1]
    rec = defaultdict(lambda: ZERO)
    count = 0
    for v in live(pack):
        if v.voucher_type == "receipt" and sum(ln[1] for ln in cash_lines(v)) > 0:
            count += 1
            rec[(v.party, v.on)] += sum(ln[1] for ln in cash_lines(v))
    assert {k: t for k, t in rec.items() if t >= LIMIT_RECEIPT} == {("Mehta & Co", date(2026, 9, 3)): D("200000.00")}
    assert rec[("Gamma Retail", date(2026, 9, 4))] == D("199999.99") and count == 4 == pack.summary[("FY26", "A-06")][1]
    prior = [v for v in pack.vouchers if v.fy == "F25" and v.voucher_type == "payment" and cash_lines(v)]
    assert [(v.ref, v.party, v.total) for v in prior] == [("P-02", "Sharma Traders", D("12500.00"))]


def test_A12_A13_A14_are_re_derived_from_the_inputs(pack):
    vs = live(pack)
    assert [v.ref for v in vs if v.total >= D("10000.00") and v.total % D("1000.00") == 0] == ["V-27", "V-36"] or \
        sorted(v.ref for v in vs if v.total >= D("10000.00") and v.total % D("1000.00") == 0) == ["V-27", "V-36"]
    holidays = {date.fromisoformat(h["date"]) for h in pack.holidays}
    assert sorted(v.ref for v in vs if v.on.weekday() == 6) == ["V-33"]            # 06-09-2026 is a Sunday (typed: weekday 6)
    assert sorted(v.ref for v in vs if v.on in holidays) == ["V-40"] and date(2026, 10, 20).weekday() == 1   # Tuesday, Dussehra
    assert not [v for v in vs if v.on in holidays and v.on.weekday() == 6]
    lock = next(e for e in pack.lock_events if e["action"] == "lock")
    locked_at = datetime.fromisoformat(lock["at"])
    period = (date(2026, 7, 1), date(2026, 7, 31))
    late = []
    for v in vs:
        posted = v.posted_at or datetime.combine(v.on, datetime.min.time().replace(hour=12), tzinfo=locked_at.tzinfo)
        if period[0] <= v.on <= period[1] and posted > locked_at:
            late.append(v.ref)
        month_end = date(v.on.year + (v.on.month == 12), v.on.month % 12 + 1, 1) - timedelta(days=1)
        assert (posted.date() - month_end).days <= 30, v.ref                    # nobody else is posted more than 30 days after the period end
    assert late == ["V-20"]


# ------------------------------------------------------------------------------------------------------------------- A-07 .. A-11, A-15 .. A-18 re-derived


def test_A07_msme_bill_dates_and_days_are_re_derived(pack):
    open_bills = {}
    for v in live(pack):
        for ln in v.lines:
            if ln[3] == "new_ref":
                open_bills[(ln[0], ln[4])] = [v.on, ln[2]]
            if ln[3] == "against_ref":
                open_bills[(ln[0], ln[4])][1] -= ln[1]
    still = {k: b for k, b in open_bills.items() if b[1] > 0}
    assert sorted(still) == [("Gupta Enterprises", "GE/884"), ("Patel Plastics", "PP/310")]
    as_on = date(2026, 10, 31)
    overdue = {k: ((b[0] + timedelta(days=15)), (as_on - (b[0] + timedelta(days=15))).days, b[1]) for k, b in still.items()
               if as_on > b[0] + timedelta(days=15)}
    assert overdue == {("Gupta Enterprises", "GE/884"): (date(2026, 9, 16), 45, D("38260.00"))}
    assert (as_on - date(2026, 9, 1)).days == 60                                 # "a bill 60 days old"
    assert pack.summary[("FY26", "A-07")][1] == len(still) == 2


def test_A09_A10_A11_tax_is_re_derived_from_the_inputs(pack):
    rate = D("0.01")                                                              # 1 percent: contractor, individual (seeded, secondary_verified)
    items = {i["voucher"]: i for i in pack.tds_items}
    deducted = {v: D(i["tax_deducted"]) for v, i in items.items()}
    paid = {v.ref: (v.party, sum(ln[1] for ln in v.lines if ln[0] == v.party)) for v in live(pack)
            if v.party in {d["ledger"] for d in pack.tds_deductees} and v.voucher_type == "payment"}
    assert sorted(paid) == ["V-11", "V-12", "V-13", "V-14", "V-15"] == sorted(set(paid) & set(paid))
    computed = {r: ((b * rate).quantize(D("1"), rounding=ROUND_HALF_UP) if b >= D("30000.00") else ZERO) for r, (_, b) in paid.items()}   # single payment limit 30,000.00, hand-typed
    assert computed == {"V-11": D("1015.00"), "V-12": D("1058.00"), "V-13": D("1083.00"), "V-14": D("1032.00"), "V-15": ZERO}
    not_deducted = [r for r, t in computed.items() if t > 0 and r not in deducted]
    short = {r: computed[r] - deducted[r] for r in deducted if deducted[r] < computed[r]}
    assert not_deducted == ["V-11"] and short == {"V-13": D("683.00")}
    for r, it in items.items():                                                   # the typed base is the voucher amount
        assert D(it["base"]) == paid[r][1]
    # A-11: due on the 7th of the month after the deduction; late = deposit after it
    late = {}
    for ch in pack.tds_challans:
        event = next(v.on for v in live(pack) if v.ref == ch["item_voucher"])
        due = date(event.year + (event.month == 12), event.month % 12 + 1, 7)
        deposit = date.fromisoformat(ch["deposit_date"])
        if deposit > due:
            late[ch["item_voucher"]] = (due, deposit, (deposit - due).days)
    assert late == {"V-12": (date(2026, 7, 7), date(2026, 7, 20), 13)}
    assert sum(D(c["allocated"]) for c in pack.tds_challans if c["challan"] == "CH-1") == D("1432.00")
    assert {r: D(c["allocated"]) for c in pack.tds_challans for r in [c["item_voucher"]]} == deducted


def test_A08_gst_difference_is_re_derived(pack):
    sales_in_oct = [v for v in live(pack) if v.voucher_type == "sales" and date(2026, 10, 1) <= v.on <= date(2026, 10, 31)]
    sales_in_sep = [v for v in live(pack) if v.voucher_type == "sales" and date(2026, 9, 1) <= v.on <= date(2026, 9, 30)]
    assert not sales_in_oct and not sales_in_sep                                  # books show nothing in September and October
    diffs = {}
    for r in pack.gst_filed:
        filed = {k: D(v) for k, v in r.items() if k.startswith("gstr1_")}
        diffs[r["return_period"]] = {k: -v for k, v in filed.items() if v}        # books (0.00) minus filed
    assert diffs == {"2026-09-01": {}, "2026-10-01": {"gstr1_taxable_value": D("-50000.00"), "gstr1_cgst": D("-4500.00"), "gstr1_sgst": D("-4500.00")}}
    assert sum(abs(x) for x in diffs["2026-10-01"].values()) == D("59000.00")
    assert pack.config["client"]["gst_effective_from"] == date(2026, 9, 1)


def test_A15_ledger_movements_are_re_derived(pack):
    this, prev = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for v in pack.vouchers:
        for ln in v.lines:
            if date(2026, 4, 1) <= v.on <= date(2026, 10, 31):
                this[ln[0]] += ln[1] - ln[2]
            if date(2025, 4, 1) <= v.on <= date(2025, 10, 31):
                prev[ln[0]] += ln[1] - ln[2]
    flagged = {}
    for led in set(this) | set(prev):
        change = this[led] - prev[led]
        if abs(change) >= D("500000.00") and (not prev[led] or abs(change) * 100 / abs(prev[led]) > 50):
            flagged[led] = (this[led], prev[led], change, (abs(change) * 100 / abs(prev[led])).quantize(D("0.01")))
    assert flagged == {"Repairs & Maintenance": (D("840250.00"), D("260150.00"), D("580100.00"), D("222.99")),
                       "Reliable Repairs": (D("-840250.00"), D("-63800.00"), D("-776450.00"), D("1217.01"))}
    assert this["Cash"] - prev["Cash"] == D("428849.99") and this["HDFC Bank"] - prev["HDFC Bank"] == D("-230341.10")
    assert len([x for x in set(this) | set(prev) if this[x] or prev[x]]) == 26 == pack.summary[("FY26", "A-15")][1]


def test_A16_A17_A18_are_re_derived(pack):
    for ledger, opening in (("Cash", D("300000.00")), ("Petty Cash", ZERO)):
        by_day = defaultdict(lambda: ZERO)
        for v in live(pack):
            for ln in v.lines:
                if ln[0] == ledger:
                    by_day[v.on] += ln[1] - ln[2]
        run, negative = opening, []
        for d in sorted(by_day):
            run += by_day[d]
            if run < 0:
                negative.append((d, run))
        assert negative == ([] if ledger == "Cash" else [(date(2026, 9, 8), D("-4200.00"))])
    stock = {s["item"]: D(s["opening_qty"]) for s in pack.stock_items}
    low = {}
    for j in sorted(pack.stock_journals, key=lambda x: x["date"]):
        stock[j["item"]] -= D(j["quantity"])
        if stock[j["item"]] < 0:
            low[j["item"]] = (j["date"], stock[j["item"]])
    assert low == {"Steel Rod 12mm": ("2026-09-15", D("-2.000"))} and stock["Copper Wire 2.5mm"] == D("15.000")
    related = {r["ledger"] for r in pack.related}
    mine = [v for v in live(pack) if any(ln[0] in related for ln in v.lines)]
    assert refs(mine) == ["V-36", "V-39"]
    assert (sum(ln[1] for v in mine for ln in v.lines if ln[0] == "Singh Brothers"), sum(ln[2] for v in mine for ln in v.lines if ln[0] == "Singh Brothers")) \
        == (D("30150.00"), D("50000.00"))


# ------------------------------------------------------------------------------------------------------------------- sampling


MASK = (1 << 64) - 1


class SplitMix:
    """An independent SplitMix64 (the published algorithm; seed 0 gives 0xE220A8397B1DCDAF first)."""

    def __init__(self, seed):
        self.s = seed & MASK

    def next(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & MASK
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)


def draw_random(ids, n, seed):
    pop, g = sorted(ids), SplitMix(seed)
    order = list(range(len(pop)))
    for i in range(n):
        j = i + g.next() % (len(pop) - i)
        order[i], order[j] = order[j], order[i]
    return [pop[k] for k in sorted(order[:n])]


def test_the_sampling_expectations_are_re_derived_with_an_independent_splitmix(pack):
    assert SplitMix(0).next() == 0xE220A8397B1DCDAF
    population = sorted(pack.sampling_population)
    assert population == sorted(v.ref for v in live(pack) if v.voucher_type in ("purchase", "payment", "debit_note")) and len(population) == 26
    cases = {c.id: c for c in pack.sampling}
    assert draw_random(population, 5, 7) == list(cases["S-01"].expected) == draw_random(population, 5, 7)
    interval = len(population) // 5
    start = SplitMix(7).next() % interval
    assert interval == 5 and start == 2
    assert [population[start + k * interval] for k in range(5)] == list(cases["S-02"].expected)
    assert [population[0 + k * interval] for k in range(5)] == list(cases["S-03"].expected)
    total = {v.ref: v.total for v in live(pack)}
    key = [r for r in population if total[r] >= D("100000.00")]
    rest = [r for r in population if total[r] < D("100000.00")]
    assert key == ["V-11", "V-12", "V-13", "V-14", "V-28"] and len(rest) == 21
    assert sorted(key + draw_random(rest, 3, 11)) == list(cases["S-04"].expected)


# ------------------------------------------------------------------------------------------------------------------- Form 3CD


def test_the_form_3cd_expectation_follows_from_the_last_year_findings(pack):
    last_year = [f for f in pack.findings if f.run == "FY25"]
    assert [(f.check_id, f.amount, f.disallowance) for f in last_year] == [("A-05", D("12500.00"), D("12500.00"))]
    derived = {(c, k): v for c, k, v, o in pack.form if o == "derived"}
    assert derived[("21", "cash_payment_exception_count")] == "1" and derived[("21", "cash_payment_total_amount")] == "12500.00"
    assert derived[("21", "cash_payment_disallowable_amount")] == "12500.00" and derived[("21", "legal_rule_status")] == "pending"
    for clause in ("22", "23", "26", "27", "31", "34"):
        assert [v for (c, k), v in derived.items() if c == clause and k.endswith("_count")] == ["0"]
        assert [v for (c, k), v in derived.items() if c == clause and k.endswith("_amount")] == ["0.00"]
    assert len(derived) == 16


def test_the_input_files_are_unchanged_since_the_pack_was_built():
    """The builder script writes the inputs; rebuilding must give the same files (the expected files were typed against them)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_pack_p8_inputs", REPO / "scripts" / "build_pack_p8_inputs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    nums = module.numbers()
    rows = {r["ref"]: r["number"] for r in __import__("csv").DictReader((PACK / "vouchers.csv").open(encoding="utf-8"))}
    assert rows == nums
