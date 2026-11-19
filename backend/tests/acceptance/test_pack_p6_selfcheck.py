"""Internal consistency of the Phase 6 pack docs/test-packs/phase6-full-year-accounts-2026-27 (no database, no service, no engine).

Plain csv / Decimal arithmetic only. Every total asserted here is typed by hand (WORKING.md); everything else is re-derived from the pack's
own inputs (opening balances, vouchers, adjustment lines) and compared with the expected_*.csv files, so a slip in a hand-typed expected
file is caught before the tool is blamed.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from pack_loader_p6 import CLIENTS, MARKER, load_pack_p6

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase6-full-year-accounts-2026-27"
D = Decimal
ZERO = D("0.00")
SCHEDULE_II_LIFE = {"furniture_fittings": D(10), "plant_machinery_general": D(15)}  # seed 0012 (pending rows)
IT_RATE = {"furniture_fittings": D(10), "plant_machinery_general": D(15)}  # seed 0012
FY_START = {"2025-26": date(2025, 4, 1), "2026-27": date(2026, 4, 1)}


def q2(value: Decimal) -> Decimal:
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def fy_end(label: str) -> date:
    return date(FY_START[label].year + 1, 3, 31)


def days(a: date, b: date) -> int:
    return (b - a).days + 1


@pytest.fixture(scope="module")
def pack():
    return load_pack_p6(PACK)


def expected(client, name: str, fy: str | None = None) -> list[dict]:
    rows = client.expected[name]
    return [r for r in rows if fy is None or r["fy"] == fy]


def fy_of(on: date) -> str:
    return "2025-26" if on < date(2026, 4, 1) else "2026-27"


def ledger_balances(client, fy: str, pack_carried: dict[str, Decimal] | None = None) -> dict[str, Decimal]:
    """Signed (debit +) balance of every ledger at the FY end from the pack's inputs only: openings, the year's vouchers, the expected
    adjustment lines of the year (adjustments are journals the tool creates; their expected lines are hand-typed)."""
    bal: dict[str, Decimal] = defaultdict(lambda: ZERO)
    if pack_carried is None:
        for r in client.ledgers:
            bal[r["ledger_name"]] += r["opening_dr"] - r["opening_cr"]
    else:
        for name, amount in pack_carried.items():
            bal[name] += amount
    for v in client.vouchers:
        if fy_of(v.date) == fy:
            for line in v.lines:
                bal[line.ledger_name] += line.debit - line.credit
    refs = {a.ref_id for a in client.adjustments if fy_of(a.as_on_date) == fy}
    for r in expected(client, "expected_adjustments"):
        if r["ref_id"] in refs:
            bal[r["ledger_name"]] += D(r["debit"]) - D(r["credit"])
    return bal


def carried_of(client, fy: str) -> dict[str, Decimal]:
    return {r["ledger_name"]: D(r["debit"]) - D(r["credit"]) for r in expected(client, "expected_carried", fy)}


def openings_of(client, fy: str) -> dict[str, Decimal] | None:
    """The carried openings of the second year of the company; every other first year opens from ledgers.csv."""
    return carried_of(client, "2025-26") if client.key == "company" and fy == "2026-27" else None


def tb_expected(client, fy: str) -> dict[str, Decimal]:
    return {r["ledger_name"]: D(r["debit"]) - D(r["credit"]) for r in expected(client, "expected_trial_balance", fy)}


YEARS = {"proprietor": ("2026-27",), "partnership": ("2026-27",), "company": ("2025-26", "2026-27")}


def test_pack_loads_and_is_marked_for_the_phase6_runner(pack):
    assert (PACK / MARKER).is_file()
    assert list(pack.clients) == list(CLIENTS)
    assert [len(c.vouchers) for c in pack.clients.values()] == [50, 29, 38]
    assert [len(c.adjustments) for c in pack.clients.values()] == [7, 7, 5]


@pytest.mark.parametrize("key", CLIENTS)
def test_opening_balances_balance_and_every_voucher_balances(pack, key):
    c = pack.clients[key]
    assert sum(r["opening_dr"] for r in c.ledgers) == sum(r["opening_cr"] for r in c.ledgers)
    for v in c.vouchers:
        assert sum(x.debit for x in v.lines) == sum(x.credit for x in v.lines), v.ref_id
    assert len({v.ref_id for v in c.vouchers}) == len(c.vouchers)


def test_headline_opening_totals_typed_by_hand(pack):
    totals = {k: sum(r["opening_dr"] for r in c.ledgers) for k, c in pack.clients.items()}
    assert totals == {"proprietor": D("600000.00"), "partnership": D("530000.00"), "company": D("500000.00")}


@pytest.mark.parametrize("key", CLIENTS)
def test_trial_balance_rebuilt_from_vouchers_and_adjustments_equals_the_expected_file(pack, key):
    c = pack.clients[key]
    for fy in YEARS[key]:
        bal = ledger_balances(c, fy, openings_of(c, fy))
        mine = {n: v for n, v in bal.items() if v != 0}
        assert mine == tb_expected(c, fy), (key, fy)
        rows = expected(c, "expected_trial_balance", fy)
        assert sum(D(r["debit"]) for r in rows) == sum(D(r["credit"]) for r in rows)


def test_trial_balance_totals_typed_by_hand(pack):
    def total(key, fy):
        return sum(D(r["debit"]) for r in expected(pack.clients[key], "expected_trial_balance", fy))

    assert total("proprietor", "2026-27") == D("2092546.57")
    assert total("partnership", "2026-27") == D("1611493.15")
    assert total("company", "2025-26") == D("1471263.01")
    assert total("company", "2026-27") == D("2278519.45")


def side(rows: list[dict], statement: str, which: str, fy: str | None = None) -> dict[str, Decimal]:
    return {r["label"]: D(r["amount"]) for r in rows if r["statement"] == statement and r["side"] == which and (fy is None or r["fy"] == fy)}


@pytest.mark.parametrize("key", ["proprietor", "partnership"])
def test_horizontal_statements_add_up_and_agree_with_the_trial_balance(pack, key):
    c = pack.clients[key]
    rows = c.expected["expected_statements"]
    tb = tb_expected(c, "2026-27")
    for statement in ("trading", "profit_loss_horizontal", "appropriation", "balance_sheet_horizontal"):
        if statement == "appropriation" and key != "partnership":
            continue
        left, right = side(rows, statement, "left"), side(rows, statement, "right")
        assert left["Total"] == right["Total"], statement
        assert sum(v for k, v in left.items() if k != "Total") == left["Total"], statement
        assert sum(v for k, v in right.items() if k != "Total") == right["Total"], statement
    bs_right = side(rows, "balance_sheet_horizontal", "right")
    cash_and_bank = sum(v for k, v in tb.items() if k in ("Cash", "HDFC Bank"))
    assert bs_right.get("Cash-in-hand", ZERO) + bs_right["Bank Accounts"] == cash_and_bank
    # vertical forms are the same figures in one column
    v_bs = {r["label"]: D(r["amount"]) for r in rows if r["statement"] == "balance_sheet_vertical"}
    assert v_bs["Total sources of funds"] == v_bs["Total application of funds"]
    v_pl = {r["label"]: D(r["amount"]) for r in rows if r["statement"] == "profit_loss_vertical"}
    h_pl = side(rows, "profit_loss_horizontal", "left")
    assert [v_pl[k] for k in v_pl if k.startswith("Net profit")] == [next(v for k, v in h_pl.items() if k.startswith("Net profit"))]


def test_proprietor_headline_figures_typed_by_hand(pack):
    rows = pack.clients["proprietor"].expected["expected_statements"]
    assert side(rows, "trading", "left")["Gross profit c/d"] == D("410000.00")
    assert side(rows, "profit_loss_horizontal", "left")["Net profit c/d"] == D("179853.43")
    assert side(rows, "balance_sheet_horizontal", "left")["Total"] == D("917853.43")
    assert side(rows, "balance_sheet_horizontal", "left")["Capital"] == D("579853.43")  # 5,00,000 - 1,00,000 + 1,79,853.38
    assert side(rows, "balance_sheet_horizontal", "right")["Sundry Debtors"] == D("228000.00")  # 2,40,000 less provision 12,000
    v_bs = {r["label"]: D(r["amount"]) for r in rows if r["statement"] == "balance_sheet_vertical"}
    assert (v_bs["Total sources of funds"], v_bs["Net current assets"]) == (D("599853.43"), D("364200.00"))


def test_partnership_appropriation_and_shares_typed_by_hand(pack):
    rows = pack.clients["partnership"].expected["expected_statements"]
    left = side(rows, "appropriation", "left")
    right = side(rows, "appropriation", "right")
    balance = D("425000.00") + right["Interest on Drawings"] - left["Interest on Capital"] - left["Partners Remuneration"]
    assert balance == D("295979.72")  # 4,25,000 + 7,472.87 - 52,493.15 - 84,000
    a, b = left["Share of profit: Anil Sharma"], left["Share of profit: Rakesh Verma"]
    assert (a, b) == (D("177587.83"), D("118391.89"))
    assert q2(balance * D(60) / D(100)) == a
    assert balance - a == b  # the last partner takes the remainder
    assert a + b == balance


def test_partner_adjustments_recomputed_from_the_vouchers(pack):
    """Interest on capital (day-weighted), interest on drawings (each draw to the FY end), remuneration: from the vouchers and terms."""
    c = pack.clients["partnership"]
    start, end = date(2026, 4, 1), date(2027, 3, 31)
    diy = days(start, end)
    assert diy == 365
    terms = {t["partner"]: t for t in c.partner_terms}
    assert sum(t["profit_share_percent"] for t in terms.values()) == D("100.0000")
    lines = {(r["ref_id"], r["ledger_name"]): r for r in c.expected["expected_adjustments"]}

    def moves(ledger: str, side_name: str):
        return [(v.date, getattr(line, side_name)) for v in c.vouchers for line in v.lines if line.ledger_name == ledger and getattr(line, side_name) > 0]

    for partner, ref_ioc, ref_iod in (("Anil Sharma", "A2", "A4"), ("Rakesh Verma", "A3", "A5")):
        opening = next(r["opening_cr"] for r in c.ledgers if r["ledger_name"] == f"{partner} Capital A/c")
        changes = sorted(moves(f"{partner} Capital A/c", "credit"))
        balance, cursor, weighted = opening, start, ZERO
        for when, amount in changes:
            weighted += balance * days(cursor, when - timedelta(days=1))
            balance, cursor = balance + amount, when
        weighted += balance * days(cursor, end)
        ioc = q2(weighted * terms[partner]["interest_on_capital_rate"] / 100 / diy)
        assert str(ioc) == lines[(ref_ioc, "Interest on Capital")]["debit"], partner
        draws = sum((amount * days(when, end) for when, amount in moves(f"{partner} Drawings", "debit")), ZERO)
        iod = q2(draws * terms[partner]["interest_on_drawings_rate"] / 100 / diy)
        assert str(iod) == lines[(ref_iod, "Interest on Drawings")]["credit"], partner
    assert q2(D("60000.00") * 12 / 12) == D(lines[("A6", "Partners Remuneration")]["debit"])
    assert q2(D("48000.00") * 6 / 12) == D(lines[("A7", "Partners Remuneration")]["debit"])


def test_proprietor_provision_and_bad_debt_recomputed(pack):
    c = pack.clients["proprietor"]
    bal = ledger_balances(c, "2026-27")  # includes the adjustments
    debtors = sum(bal[n] for n in ("Anand Traders", "Bhatia & Sons", "Chopra Stores"))
    assert debtors == D("240000.00")  # 2,50,000 less the bad debt 10,000
    assert q2(debtors * D(5) / 100) == D("12000.00")
    assert bal["Provision for Doubtful Debts"] == D("-12000.00") and bal["Bad Debts"] == D("10000.00")


def slm_year(cost: Decimal, residual: Decimal, life: Decimal, ptu: date, ws: date, we: date, acc: Decimal) -> tuple[Decimal, int]:
    begin = max(ptu, ws)
    n = days(begin, we) if we >= begin else 0
    raw = q2((cost - residual) * n / (life * days(ws, we)))
    return min(raw, max(cost - residual - acc, ZERO)), n


def fy_start_of(on: date) -> date:
    return date(on.year if on.month >= 4 else on.year - 1, 4, 1)


def book_depreciation(client, asset: dict, fy: str) -> tuple[Decimal, Decimal, int, Decimal]:
    """(cost, depreciation of the year, days of the first tranche, opening accumulated) by Schedule II straight line, tranche by tranche."""
    life = SCHEDULE_II_LIFE[asset["sched2_class"]]
    events = sorted((e for e in client.events if e["asset_no"] == asset["asset_no"] and e["kind"] != "disposal"), key=lambda e: e["event_date"])
    first = events[0]["amount"]
    total_cost = total_dep = opening_acc = ZERO
    first_days = 0
    for i, e in enumerate(events):
        residual = asset["residual"] if i == 0 else q2(e["amount"] * asset["residual"] / first)
        acc = e["accumulated_dep_bf"]
        ws = fy_start_of(e["event_date"] if e["kind"] == "opening" else e["put_to_use_date"])
        while ws <= FY_START[fy]:
            we = date(ws.year + 1, 3, 31)
            dep, n = slm_year(e["amount"], residual, life, e["put_to_use_date"], ws, we, acc)
            if ws == FY_START[fy]:
                total_dep += dep
                opening_acc += acc
                total_cost += e["amount"]
                first_days = first_days or n
            acc += dep
            ws = date(ws.year + 1, 4, 1)
    return total_cost, total_dep, first_days, opening_acc


@pytest.mark.parametrize("key", ["proprietor", "company"])
def test_book_depreciation_recomputed_by_schedule_ii_straight_line(pack, key):
    c = pack.clients[key]
    for fy in YEARS[key]:
        mine = {}
        for asset in c.assets:
            cost, dep, n, opening = book_depreciation(c, asset, fy)
            if cost:
                mine[asset["asset_no"]] = (n, opening, dep)
        want = {r["asset_no"]: (int(r["days_used"]), D(r["opening_accumulated"]), D(r["depreciation"])) for r in expected(c, "expected_depreciation", fy)}
        assert mine == want, (key, fy)
        for r in expected(c, "expected_depreciation", fy):
            assert D(r["opening_accumulated"]) + D(r["depreciation"]) == D(r["closing_accumulated"])
        reg = expected(c, "expected_register", fy)
        for r in reg:
            assert D(r["opening_cost"]) + D(r["additions"]) - D(r["disposals"]) == D(r["closing_cost"])
            assert D(r["opening_accumulated"]) + D(r["depreciation_for_year"]) == D(r["closing_accumulated"])
            assert D(r["closing_cost"]) - D(r["closing_accumulated"]) == D(r["net_block"])
        # the depreciation run total is the amount of the depreciation adjustment
        run = next(a for a in c.adjustments if a.adj_type == "book_depreciation" and fy_of(a.as_on_date) == fy)
        line = next(r for r in expected(c, "expected_adjustments") if r["ref_id"] == run.ref_id and r["ledger_name"] == "Depreciation")
        assert sum(D(r["depreciation"]) for r in expected(c, "expected_depreciation", fy)) == D(line["debit"])


def test_depreciation_figures_typed_by_hand(pack):
    prop = {r["asset_no"]: r["depreciation"] for r in expected(pack.clients["proprietor"], "expected_depreciation")}
    assert prop == {"FU-1": "10000.00", "PM-1": "3157.99", "PM-2": "1188.58"}  # 1,00,000/10; 95,000 x 182 / 5,475; 47,500 x 137 / 5,475
    comp = {r["fy"]: r["depreciation"] for r in expected(pack.clients["company"], "expected_depreciation")}
    assert comp == {"2025-26": "14263.01", "2026-27": "21519.45"}  # 2,85,000 x 274 / 5,475; 2,85,000/15 + 1,14,000 x 121 / 5,475


@pytest.mark.parametrize("key", ["proprietor", "company"])
def test_income_tax_blocks_recomputed_with_the_half_rate_rule(pack, key):
    c = pack.clients[key]
    carried = {(r["fy"], r["block_key"]): D(r["opening_wdv"]) for r in expected(c, "expected_carried_it")}
    for fy in YEARS[key]:
        end = fy_end(fy)
        for r in expected(c, "expected_it_blocks", fy):
            block = r["block_key"]
            opening = next((o["opening_wdv"] for o in c.it_openings if o["fy"] == fy and o["block_key"] == block), None)
            if opening is None:  # carried from the previous year's close
                opening = carried[("2025-26", block)]
            full = half = ZERO
            for e in c.events:
                asset = next(a for a in c.assets if a["asset_no"] == e["asset_no"])
                if asset["it_block"] == block and e["kind"] in ("purchase", "addition") and FY_START[fy] <= e["put_to_use_date"] <= end:
                    if days(e["put_to_use_date"], end) < 180:  # F-31: fewer than 180 days -> half rate
                        half += e["amount"]
                    else:
                        full += e["amount"]
            dep = q2((opening + full) * IT_RATE[block] / 100 + half * IT_RATE[block] / 100 * D("0.5"))
            assert (opening, full, half, dep) == (D(r["opening_wdv"]), D(r["additions_full"]), D(r["additions_half"]), D(r["depreciation"])), (key, fy, block)
            assert opening + full + half - D(r["disposals"]) - dep == D(r["closing_wdv"])
            assert carried[(fy, block)] == D(r["closing_wdv"]) if (fy, block) in carried else True


def test_half_rate_case_typed_by_hand(pack):
    plant = next(r for r in expected(pack.clients["proprietor"], "expected_it_blocks") if r["block_key"] == "plant_machinery_general")
    # A 1,00,000 put to use 01-10-2026 = 182 days (full), B 50,000 put to use 15-11-2026 = 137 days (half)
    assert days(date(2026, 10, 1), date(2027, 3, 31)) == 182 and days(date(2026, 11, 15), date(2027, 3, 31)) == 137
    assert (plant["additions_full"], plant["additions_half"], plant["depreciation"], plant["closing_wdv"]) == ("100000.00", "50000.00", "18750.00", "131250.00")


@pytest.mark.parametrize("key", CLIENTS)
def test_closing_vouchers_balance_and_carry_forward_follows_from_the_trial_balance(pack, key):
    c = pack.clients[key]
    fy = YEARS[key][0]
    steps = defaultdict(lambda: [ZERO, ZERO])
    after = dict(tb_expected(c, fy))
    for r in expected(c, "expected_closing", fy):
        steps[r["step"]][0] += D(r["debit"])
        steps[r["step"]][1] += D(r["credit"])
        after[r["ledger_name"]] = after.get(r["ledger_name"], ZERO) + D(r["debit"]) - D(r["credit"])
    assert all(dr == cr for dr, cr in steps.values())
    assert [s for s in steps] == ["trading", "profit_loss", "appropriation"]
    carried = {n: v for n, v in after.items() if v != 0}
    assert carried == carried_of(c, fy)
    rows = expected(c, "expected_carried", fy)
    assert sum(D(r["debit"]) for r in rows) == sum(D(r["credit"]) for r in rows)


def test_closing_and_carry_totals_typed_by_hand(pack):
    def totals(key):
        rows = expected(pack.clients[key], "expected_carried", YEARS[key][0])
        return sum(D(r["debit"]) for r in rows)

    assert [totals(k) for k in CLIENTS] == [D("944200.00"), D("1000000.00"), D("952000.00")]
    prop = {s: sum(D(r["debit"]) for r in expected(pack.clients["proprietor"], "expected_closing") if r["step"] == s)
            for s in ("trading", "profit_loss", "appropriation")}
    assert prop == {"trading": D("1260000.00"), "profit_loss": D("428200.00"), "appropriation": D("179853.43")}


@pytest.mark.parametrize("key", CLIENTS)
def test_cash_flow_adds_up_and_ties_to_cash_and_bank(pack, key):
    c = pack.clients[key]
    rows = {r["label"]: D(r["amount"]) for r in c.expected["expected_cash_flow"]}
    labels = [r["label"] for r in c.expected["expected_cash_flow"]]
    a_end, b_end, c_end = (labels.index(x) for x in ("Net cash from operating activities (A)", "Net cash from investing activities (B)",
                                                       "Net cash from financing activities (C)"))
    op = [labels[i] for i in range(1, a_end) if labels[i] != "Operating profit before working capital changes"]
    assert sum(rows[x] for x in op) == rows["Net cash from operating activities (A)"]
    assert sum(rows[x] for x in labels[a_end + 2:b_end]) == rows["Net cash from investing activities (B)"]
    assert sum(rows[x] for x in labels[b_end + 2:c_end]) == rows["Net cash from financing activities (C)"]
    net = rows["Net cash from operating activities (A)"] + rows["Net cash from investing activities (B)"] + rows["Net cash from financing activities (C)"]
    assert net == rows["Net increase / (decrease) in cash and cash equivalents (A + B + C)"]
    opening = rows["Cash and cash equivalents at the beginning of the year"]
    assert opening + net == rows["Cash and cash equivalents at the end of the year"]
    fy = YEARS[key][-1]
    tb = tb_expected(c, fy)
    assert rows["Cash and cash equivalents at the end of the year"] == sum(v for k, v in tb.items() if k in ("Cash", "HDFC Bank"))
    cash_names = [r["ledger_name"] for r in c.ledgers if r["group_name"] in ("Cash-in-hand", "Bank Accounts")]
    opening_cash = sum(r["opening_dr"] for r in c.ledgers if r["ledger_name"] in cash_names)
    if key == "company":
        opening_cash = sum(carried_of(c, "2025-26").get(n, ZERO) for n in cash_names)
    assert opening == opening_cash


def test_cash_flow_totals_typed_by_hand(pack):
    def net(key):
        return next(D(r["amount"]) for r in pack.clients[key].expected["expected_cash_flow"] if r["label"].startswith("Net increase"))

    assert [net(k) for k in CLIENTS] == [D("51000.00"), D("360000.00"), D("-289500.00")]


def test_schedule_iii_adds_up_and_the_comparative_column_is_the_previous_year(pack):
    c = pack.clients["company"]
    rows = c.expected["expected_sch3"]

    def stmt(fy, name):
        return {r["label"]: (D(r["amount"]), D(r["previous_amount"]) if r["previous_amount"] else None) for r in rows if r["fy"] == fy and r["statement"] == name}

    for fy in YEARS["company"]:
        bs = stmt(fy, "sch3_balance_sheet")
        assert bs["TOTAL EQUITY AND LIABILITIES"][0] == bs["TOTAL ASSETS"][0]
        assert bs["Shareholders' funds"][0] == bs["Share capital"][0] + bs["Reserves and surplus"][0]
        assert bs["Current assets"][0] == sum(bs[k][0] for k in ("Inventories", "Trade receivables", "Cash and cash equivalents", "Other current assets") if k in bs)
        pl = stmt(fy, "sch3_profit_loss")
        assert pl["Total revenue"][0] - pl["Total expenses"][0] == pl["Profit / (loss) before tax"][0]
        assert pl["Profit / (loss) for the year"][0] == bs["Reserves and surplus"][0] - (D("184736.99") if fy == "2026-27" else ZERO)
    first, second = stmt("2025-26", "sch3_profit_loss"), stmt("2026-27", "sch3_profit_loss")
    assert all(first[k][1] is None for k in first)  # first year: no comparative ("-")
    assert all(second[k][1] == first[k][0] for k in first)  # the comparative column is the signed-off previous year
    bs1, bs2 = stmt("2025-26", "sch3_balance_sheet"), stmt("2026-27", "sch3_balance_sheet")
    assert all(bs2[k][1] == bs1[k][0] for k in bs1)
    assert bs2["Other current assets"][1] == ZERO  # a line new in the year shows 0.00 before


def test_schedule_iii_figures_typed_by_hand(pack):
    rows = {(r["fy"], r["statement"], r["label"]): r for r in pack.clients["company"].expected["expected_sch3"]}
    assert rows[("2026-27", "sch3_balance_sheet", "TOTAL ASSETS")]["amount"] == "1063717.54"
    assert rows[("2026-27", "sch3_profit_loss", "Profit / (loss) for the year")]["amount"] == "125980.55"
    assert rows[("2026-27", "sch3_balance_sheet", "Reserves and surplus")]["amount"] == "310717.54"  # 1,84,736.99 + 1,25,980.55
    assert rows[("2025-26", "sch3_balance_sheet", "TOTAL ASSETS")]["amount"] == "937736.99"


def test_schedule_iii_notes_agree_with_the_statement_lines(pack):
    c = pack.clients["company"]
    sch3 = {(r["fy"], r["label"]): D(r["amount"]) for r in c.expected["expected_sch3"]}
    totals = {}
    for r in c.expected["expected_notes"]:
        if r["label"].startswith("Total ("):
            totals[(r["fy"], r["title"])] = D(r["amount"])
    for (fy, title), amount in totals.items():
        assert sch3[(fy, title)] == amount, (fy, title)
    notes = c.expected["expected_notes"]
    for fy in YEARS["company"]:
        ppe = {r["label"]: D(r["amount"]) for r in notes if r["fy"] == fy and r["title"] == "Property, plant and equipment"}
        assert ppe["Net block"] == sch3[(fy, "Property, plant and equipment")]
        assert ppe["Gross block: opening"] + ppe["Additions"] + ppe["Disposals"] == ppe["Gross block: closing"]
        assert ppe["Accumulated depreciation: opening"] + ppe["Depreciation for the year"] + ppe["On disposals"] == ppe["Accumulated depreciation: closing"]
        numbers = [int(r["note_no"]) for r in notes if r["fy"] == fy]
        assert numbers == sorted(numbers) and set(numbers) == set(range(1, max(numbers) + 1))


def test_company_second_year_opens_with_the_first_year_carry_forward(pack):
    c = pack.clients["company"]
    carried = carried_of(c, "2025-26")
    tb2 = ledger_balances(c, "2026-27", carried)
    assert tb2["Opening Stock"] == D("110000.00")  # the closing stock of the first year
    assert tb2["Surplus in Profit & Loss"] == D("-184736.99")
    assert carried["Surplus in Profit & Loss"] == D("-184736.99")
    assert {(r["fy"], r["block_key"]): r["opening_wdv"] for r in expected(c, "expected_carried_it")} == {("2025-26", "plant_machinery_general"): "255000.00"}


def test_adjustment_rows_name_a_rule_type_and_a_ledger_pair(pack):
    for c in pack.clients.values():
        refs = {r["ref_id"] for r in c.expected["expected_adjustments"]}
        for a in c.adjustments:
            if a.adj_type in ("provision_doubtful_debts", "interest_on_capital", "interest_on_drawings", "partner_remuneration", "book_depreciation"):
                assert a.amount is None, a.ref_id  # computed by the tool: a typed amount would be refused (F-05, F-07, F-08)
            assert a.ref_id in refs, a.ref_id
            assert a.basis_note
        for ref in refs:
            lines = [r for r in c.expected["expected_adjustments"] if r["ref_id"] == ref]
            assert sum(D(r["debit"]) for r in lines) == sum(D(r["credit"]) for r in lines), ref


def test_every_hand_typed_ledger_exists_in_the_pack_or_is_a_system_ledger(pack):
    system = {"Trading Account", "Profit & Loss Account", "Depreciation", "Accumulated Depreciation", "Bad Debts",
              "Provision for Doubtful Debts Expense", "Provision for Doubtful Debts", "Stock-in-hand", "Interest on Capital",
              "Interest on Drawings", "Partners Remuneration"}
    for c in pack.clients.values():
        known = {r["ledger_name"] for r in c.ledgers} | system
        for name, rows in c.expected.items():
            for r in rows:
                for col in ("ledger_name",):
                    if col in r:
                        assert r[col] in known, (c.key, name, r[col])
        for v in c.vouchers:
            for line in v.lines:
                assert line.ledger_name in known, (c.key, v.ref_id, line.ledger_name)
