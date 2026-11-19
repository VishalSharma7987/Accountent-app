"""Phase 6 (period-end and final accounts) acceptance runner: drives the REAL services (not the API) with the Phase 6 pack and compares
every result with the hand-worked expected files.

It never modifies a pack file and never bends the tool to fit them: every difference is collected per section as one plain line
(expected vs tool) for the owner to decide. Three clients are run, each in its own set of sections:
  proprietor  trading proprietorship, FY 2026-27: stock, adjustments (outstanding, prepaid, accrued, in advance, bad debt, provision),
              fixed-asset register with Companies Act and income-tax depreciation (half rate), Trading A/c, P&L, Balance Sheet (horizontal
              and vertical), cash flow, year-end close, carry-forward, reopen and close again.
  partnership service firm 3:2: interest on capital and drawings, remuneration, appropriation, close, carry-forward, reopen.
  company     trading company, FY 2025-26 closed in the pack and FY 2026-27 with Schedule III, notes and previous-year column; reopen of
              the first year is refused because the second year has postings.
Each client gets its own section group so that pytest shows which part differs.
"""

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pack_loader_p6 import ClientPack6, PackP6
from pack_runner_p2 import _draft, diff_keyed
from pack_runner_p3 import _post, _refusal_text, _setup_ledgers
from sqlalchemy import Connection, text

from app.services import (
    client_setup,
    final_adjustments,
    final_assets,
    final_cashflow,
    final_close,
    final_closing_stock,
    final_sch3,
    final_statements,
    reports,
    vouchers,
)
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError

ACTOR = "pack-runner-p6"
COMMON = ("setup", "vouchers", "adjustments", "trial_balance", "statements", "cash_flow", "close", "carry_forward", "reopen")
SECTIONS_BY_CLIENT = {
    "proprietor": ("setup", "vouchers", "adjustments", "depreciation", "it_working", "trial_balance", "statements", "cash_flow", "close",
                   "carry_forward", "reopen"),
    "partnership": COMMON,
    "company": ("setup", "vouchers", "adjustments", "depreciation", "it_working", "trial_balance", "statements", "notes", "cash_flow",
                "close", "carry_forward", "reopen"),
}
SECTIONS = tuple(f"{client}/{s}" for client, names in SECTIONS_BY_CLIENT.items() for s in names)
SNAPSHOTS_AT_CLOSE = {"proprietor": 3, "partnership": 3, "company": 2}  # Trading, P&L, Balance Sheet; a company has the two Schedule III ones
PERIODS_LOCKED = 12


@dataclass
class RunReport:
    pack: str
    problems: dict[str, list[str]] = field(default_factory=lambda: {s: [] for s in SECTIONS})
    notes: list[str] = field(default_factory=list)  # information for the owner (warnings of the tool, rule statuses)
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, section: str, message: str) -> None:
        self.problems[section].append(message)

    @property
    def total_problems(self) -> int:
        return sum(len(v) for v in self.problems.values())


def format_report(report: RunReport) -> str:
    lines = [f"Pack '{report.pack}': {report.total_problems} difference(s)"]
    for section in SECTIONS:
        found = report.problems[section]
        lines.append(f"[{'FAIL' if found else 'ok  '}] {section}")
        lines += [f"        - {p}" for p in found]
    if report.notes:
        lines.append("NOTES:")
        lines += [f"  * {n}" for n in report.notes]
    lines.append("COUNTS: " + ", ".join(f"{k}={v}" for k, v in report.counts.items()))
    return "\n".join(lines)


# ================================================================================================== pure helpers


def money(value) -> str:
    """2-decimal text, minus zero shown as 0.00; a missing value is blank."""
    if value is None or value == "":
        return ""
    d = Decimal(str(value))
    return f"{(d if d != 0 else Decimal('0.00')):.2f}"


def fy_dates(label: str) -> tuple[date, date]:
    start = date(int(label[:4]), 4, 1)
    return start, date(start.year + 1, 3, 31)


def in_year(on: date, label: str) -> bool:
    start, end = fy_dates(label)
    return start <= on <= end


def table(rows: list[dict], key_cols: tuple[str, ...], value_cols: tuple[str, ...], **where) -> dict[tuple, dict]:
    """Expected rows of one section as {key: {column: 2-decimal text}} (text kept as typed for non-amount columns)."""
    out = {}
    for r in rows:
        if all(r.get(k) == v for k, v in where.items()):
            out[tuple(r[c] for c in key_cols)] = {c: (money(r[c]) if c in AMOUNT_COLS else r[c]) for c in value_cols}
    return out


AMOUNT_COLS = {
    "amount", "previous_amount", "debit", "credit", "opening_accumulated", "depreciation", "closing_accumulated", "opening_cost", "additions",
    "disposals", "closing_cost", "depreciation_for_year", "net_block", "opening_wdv", "additions_full", "additions_half", "closing_wdv",
}


@contextmanager
def guard(report: RunReport, section: str):
    """A service that raises instead of answering is a difference too: it is reported, the run goes on."""
    try:
        yield
    except (VoucherRuleError, ServiceError) as refusal:
        report.add(section, f"the tool refused instead of answering: {_refusal_text(refusal)}")
    except Exception as crash:  # noqa: BLE001 - any failure of the tool is a finding, not a crash of the report
        report.add(section, f"the tool failed with {type(crash).__name__}: {crash}")


class Adapter:
    """What the Phase 3 helper `_setup_ledgers` needs: a report with add(section, message), prefixed with the client."""

    def __init__(self, report: RunReport, key: str):
        self.report, self.key = report, key

    def add(self, section: str, message: str) -> None:
        self.report.add(f"{self.key}/{section}", message)


# ================================================================================================== one client


class World6:
    def __init__(self, conn: Connection, pack: PackP6, key: str, report: RunReport):
        self.conn, self.pack, self.key, self.report = conn, pack, key, report
        self.cp: ClientPack6 = pack.clients[key]
        self.c = self.cp.client
        self.cid = None
        self.fy: dict[str, object] = {}
        self.ids: dict[str, object] = {}
        self.partner: dict[str, object] = {}
        self.asset: dict[str, object] = {}
        self.close_ids: dict[str, dict] = {}
        self.fy_pre_close_tb: dict[str, dict] = {}

    # ------------------------------------------------------------------------------------------ small helpers
    def add(self, section: str, message: str) -> None:
        self.report.add(f"{self.key}/{section}", message)

    def g(self, section: str):
        return guard(self.report, f"{self.key}/{section}")

    def ledger(self, name: str):
        return self.ids[name]

    def ledger_names(self) -> dict[object, str]:
        rows = self.conn.execute(text("SELECT id, name FROM ledgers WHERE client_id = :c"), {"c": self.cid})
        return {r[0]: r[1] for r in rows}

    def refresh_years(self) -> None:
        rows = self.conn.execute(text("SELECT id, start_date FROM financial_years WHERE client_id = :c"), {"c": self.cid})
        self.fy = {f"{r[1].year}-{(r[1].year + 1) % 100:02d}": r[0] for r in rows}

    def diff(self, section: str, want: dict, got: dict, fields: tuple[str, ...], what: str) -> None:
        for line in diff_keyed(want, got, fields, label=lambda k: f"{what} {' / '.join(k)}"):
            self.add(section, line)

    def scalar(self, sql: str, **params):
        return self.conn.execute(text(sql), {"c": self.cid, **params}).scalar_one()

    # ------------------------------------------------------------------------------------------ setup
    def setup(self) -> None:
        c = self.c
        with self.g("setup"):
            created = client_setup.create_client(
                self.conn, ClientProfile(c["name"], c["entity_type"], c["business_type"], c["gst_type"]), fy_start=c["fy_start"],
                actor=ACTOR, proprietor_name=c.get("proprietor_name"), partners=c.get("partners"))
            self.cid = created.client_id
            self.fy[f"{c['fy_start'].year}-{(c['fy_start'].year + 1) % 100:02d}"] = created.financial_year_id
            self.ids = _setup_ledgers(self.conn, Adapter(self.report, self.key), self.cid, created.financial_year_id, created, self.cp.ledgers)
            first = created.financial_year_id
            if not client_setup.opening_balance_difference(self.conn, self.cid, first).is_balanced:
                self.add("setup", "the opening balances of the first year do not balance")
            for r in final_adjustments.setup_ledgers(self.conn, self.cid, first, actor=ACTOR):
                self.ids[r["ledger_name"]] = r["ledger_id"]
            rows = [final_sch3.ClassificationRow(self.ids[r["ledger_name"]], r["line_code"] or None, r["cf_class"] or None, r["note"])
                    for r in self.cp.classification]
            if rows:
                final_sch3.put_classification(self.conn, self.cid, rows, actor=ACTOR)
            for p in self.cp.partners:
                self.partner[p["name"]] = final_adjustments.create_partner(
                    self.conn, self.cid, p["name"], self.ids[p["capital_ledger"]], self.ids[p["current_ledger"]], actor=ACTOR)
            for a in self.cp.assets:
                self.asset[a["asset_no"]] = final_assets.create_asset(self.conn, self.cid, {
                    "asset_no": a["asset_no"], "name": a["name"], "asset_ledger_id": self.ids[a["asset_ledger"]],
                    "accumulated_dep_ledger_id": self.ids[a["accum_ledger"]], "is_depreciable": True, "it_block_key": a["it_block"],
                    "sched2_class_key": a["sched2_class"], "useful_life_years": a["life_years"] or None, "residual_value": f"{a['residual']:.2f}",
                    "book_method": a["method"], "life_override_reason": a["life_override_reason"] or None}, actor=ACTOR)
        if self.cid is None:
            raise RuntimeError("client could not be set up")

    # ------------------------------------------------------------------------------------------ one year
    def run_year(self, label: str) -> None:
        self.refresh_years()
        fy = self.fy[label]
        with self.g("setup"):
            self.year_inputs(label, fy)
        self.post_vouchers(label)
        with self.g("adjustments"):
            self.adjustments(label, fy)
        self.compare_year(label, fy)

    def year_inputs(self, label: str, fy) -> None:
        """Closing stock, partner terms, asset events and income-tax openings of the year."""
        for r in self.cp.closing_stock:
            if r["fy"] == label:
                final_closing_stock.approve_closing_stock(
                    self.conn, self.cid, fy, source=r["source"], as_on_date=r["as_on_date"],
                    cost_value=None if r["cost_value"] is None else f"{r['cost_value']:.2f}",
                    write_down=None if r["write_down"] is None else f"{r['write_down']:.2f}", basis_note=r["basis_note"], actor=ACTOR)
        terms = [t for t in self.cp.partner_terms if t["fy"] == label]
        if terms:
            final_adjustments.put_terms(self.conn, self.cid, fy, [{
                "partner_id": self.partner[t["partner"]], "profit_share_percent": t["profit_share_percent"],
                "interest_on_capital_rate": t["interest_on_capital_rate"], "interest_on_drawings_rate": t["interest_on_drawings_rate"],
                "remuneration_annual": t["remuneration_annual"], "deed_reference": t["deed_reference"]} for t in terms], actor=ACTOR)
        for e in self.cp.events:
            if in_year(e["event_date"], label):
                final_assets.add_event(self.conn, self.cid, self.asset[e["asset_no"]], {
                    "kind": e["kind"], "event_date": e["event_date"], "put_to_use_date": e["put_to_use_date"], "amount": f"{e['amount']:.2f}",
                    "accumulated_dep_bf": f"{e['accumulated_dep_bf']:.2f}"}, actor=ACTOR)
        openings = [o for o in self.cp.it_openings if o["fy"] == label]
        if openings:
            final_assets.set_it_openings(self.conn, self.cid, fy, [{"block_key": o["block_key"], "opening_wdv": f"{o['opening_wdv']:.2f}"}
                                                                   for o in openings], actor=ACTOR)

    def post_vouchers(self, label: str) -> None:
        section = f"{self.key}/vouchers"
        for v in self.cp.vouchers:
            if not in_year(v.date, label):
                continue
            with guard(self.report, section):
                vid, problem = _post(self.conn, _draft(self.cid, v, self.ledger))
                if problem:
                    self.add("vouchers", f"correct voucher {v.ref_id} was refused: {problem}")
                else:
                    self.report.counts["vouchers_posted"] += 1

    def post_draft(self, voucher_id, what: str) -> None:
        vouchers.approve(self.conn, voucher_id, actor=ACTOR)
        vouchers.post(self.conn, voucher_id, actor=ACTOR)
        self.report.counts["adjustments_posted"] += 1

    def adjustments(self, label: str, fy) -> None:
        expected = self.cp.expected["expected_adjustments"]
        for a in self.cp.adjustments:
            if not in_year(a.as_on_date, label):
                continue
            with self.g("adjustments"):
                if a.adj_type == "book_depreciation":
                    self.book_depreciation(label, fy, a)
                    continue
                req = final_adjustments.AdjustmentRequest(
                    a.adj_type, a.as_on_date, a.basis_note, amount=a.amount, debit_ledger_id=self.ids.get(a.debit_ledger),
                    credit_ledger_id=self.ids.get(a.credit_ledger), party_ledger_id=self.ids.get(a.party_ledger),
                    rate_percent=a.rate_percent, partner_id=self.partner.get(a.partner), months=a.months)
                made = final_adjustments.create(self.conn, self.cid, req, actor=ACTOR)
                got = sorted((x["ledger_name"], money(x["debit"]), money(x["credit"])) for x in made["lines"])
                want = sorted((r["ledger_name"], money(r["debit"]), money(r["credit"])) for r in expected if r["ref_id"] == a.ref_id)
                if got != want:
                    self.add("adjustments", f"{a.ref_id} ({a.adj_type}): journal expected {want}, tool says {got}")
                self.post_draft(made["voucher_id"], f"adjustment {a.ref_id}")

    def book_depreciation(self, label: str, fy, a) -> None:
        preview = final_assets.preview_book(self.conn, self.cid, fy)
        errors = [f for f in preview["findings"] if f["severity"] == "error"]
        for f in errors:
            self.add("depreciation", f"{label} the preview reports an error {f['rule_id']}: {f['message']}")
        got = {(x["asset_no"],): {"method": x["method"], "days_used": str(x["days_used"]), "days_in_year": str(x["days_in_year"]),
                                  "opening_accumulated": money(x["opening_accumulated"]), "depreciation": money(x["depreciation"]),
                                  "closing_accumulated": money(x["closing_accumulated"]),
                                  "rule_status": x["rule_status"].get("verification_status", "")} for x in preview["lines"]}
        wanted = table(self.cp.expected["expected_depreciation"], ("asset_no",), (
            "method", "days_used", "days_in_year", "opening_accumulated", "depreciation", "closing_accumulated", "rule_status"), fy=label)
        self.diff("depreciation", wanted, got, ("method", "days_used", "days_in_year", "opening_accumulated", "depreciation",
                                                 "closing_accumulated", "rule_status"), f"{label} book depreciation")
        got_journal = sorted((x["ledger_name"], money(x["debit"]), money(x["credit"])) for x in preview["journal_lines"])
        want_journal = sorted((r["ledger_name"], money(r["debit"]), money(r["credit"]))
                              for r in self.cp.expected["expected_adjustments"] if r["ref_id"] == a.ref_id)
        if got_journal != want_journal:
            self.add("adjustments", f"{a.ref_id} (depreciation run): journal expected {want_journal}, tool says {got_journal}")
        made = final_assets.run_book(self.conn, self.cid, fy, actor=ACTOR)
        if money(made["total"]) != money(preview["total"]):
            self.add("depreciation", f"{label} the run total {money(made['total'])} differs from the preview total {money(preview['total'])}")
        self.post_draft(made["voucher_id"], f"depreciation run {label}")

    # ------------------------------------------------------------------------------------------ comparisons
    def compare_year(self, label: str, fy) -> None:
        if self.cp.assets:
            with self.g("depreciation"):
                self.check_register(label, fy)
            with self.g("it_working"):
                self.check_it_working(label, fy)
        with self.g("trial_balance"):
            self.fy_pre_close_tb[label] = self.check_trial_balance(label, fy)
        with self.g("statements"):
            self.check_statements(label, fy)
        if self.c["entity_type"] == "company":
            with self.g("notes"):
                self.check_notes(label, fy)
        if label == self.c["years"][-1]:
            with self.g("cash_flow"):
                self.check_cash_flow(label, fy)

    def check_trial_balance(self, label: str, fy) -> dict:
        positions = final_statements.ledger_positions(self.conn, self.cid, fy)
        got = {(x.name,): {"debit": money(max(x.closing, Decimal(0))), "credit": money(max(-x.closing, Decimal(0)))}
               for x in positions if x.closing != 0}
        want = table(self.cp.expected["expected_trial_balance"], ("ledger_name",), ("debit", "credit"), fy=label)
        self.diff("trial_balance", want, got, ("debit", "credit"), f"{label} ledger")
        total_dr = sum((x.closing for x in positions if x.closing > 0), Decimal(0))
        total_cr = -sum((x.closing for x in positions if x.closing < 0), Decimal(0))
        if total_dr != total_cr:
            self.add("trial_balance", f"{label} the Trial Balance does not balance: Dr {money(total_dr)} Cr {money(total_cr)}")
        return got

    def check_register(self, label: str, fy) -> None:
        reg = final_assets.register(self.conn, self.cid, fy)
        cols = ("opening_cost", "additions", "disposals", "closing_cost", "opening_accumulated", "depreciation_for_year",
                "closing_accumulated", "net_block")
        got = {(r["asset_no"],): {c: money(r[c]) for c in cols} for r in reg["rows"]}
        want = table(self.cp.expected["expected_register"], ("asset_no",), cols, fy=label)
        self.diff("depreciation", want, got, cols, f"{label} fixed-asset register")

    def check_it_working(self, label: str, fy) -> None:
        w = final_assets.it_working(self.conn, self.cid, fy)
        cols = ("rate", "opening_wdv", "additions_full", "additions_half", "disposals", "depreciation", "closing_wdv", "rate_verification")
        got = {(b["block_key"],): {"rate": b["rate"], "opening_wdv": money(b["opening_wdv"]), "additions_full": money(b["additions_full"]),
                                   "additions_half": money(b["additions_half"]), "disposals": money(b["disposals"]),
                                   "depreciation": money(b["depreciation"]), "closing_wdv": money(b["closing_wdv"]),
                                   "rate_verification": b["rate_verification"]} for b in w["blocks"]}
        want = table(self.cp.expected["expected_it_blocks"], ("block_key",), cols, fy=label)
        self.diff("it_working", want, got, cols, f"{label} income-tax block")
        for b in w["blocks"]:
            if b["flags"]:
                self.add("it_working", f"{label} block {b['block_key']} carries flags {b['flags']} (nothing is expected)")
        for f in w["findings"]:
            if f["severity"] == "error":
                self.add("it_working", f"{label} the working reports an error {f['rule_id']}: {f['message']}")
        self.report.notes.append(f"{self.key} {label} income-tax working status {w['status']}; rule status "
                                 + ", ".join(sorted({f"{r.get('rule', '')} {r['verification_status']}" for r in w["rule_status"]})))

    # ---- statements
    def statement_rows(self, body: dict) -> tuple[dict[tuple, dict], list[str]]:
        rows, dupes = {}, []
        for side in ("left", "right"):
            for line in body[side]:
                key = (side, line["label"])
                if key in rows:
                    dupes.append(f"{side} / {line['label']}")
                rows[key] = {"amount": money(line["amount"]), "previous_amount": money(line.get("previous_amount"))}
        return rows, dupes

    def compare_statement(self, section: str, label: str, name: str, body: dict) -> None:
        got, dupes = self.statement_rows(body)
        for d in dupes:
            self.add(section, f"{label} {name}: the label {d} appears twice in the tool's statement")
        want = table(self.cp.expected["expected_statements"], ("side", "label"), ("amount",), fy=label, statement=name)
        self.diff(section, want, {k: {"amount": v["amount"]} for k, v in got.items()}, ("amount",), f"{label} {name}")
        for f in body["findings"]:
            if f["severity"] == "error":
                self.add(section, f"{label} {name} reports an error {f['rule_id']}: {f['message']}")
            else:
                self.report.notes.append(f"{self.key} {label} {name} warning {f['rule_id']}: {f['message']}")

    def check_statements(self, label: str, fy) -> None:
        if self.c["entity_type"] == "company":
            self.check_sch3(label, fy)
            return
        s = final_statements
        self.compare_statement("statements", label, "trading", s.trading(self.conn, self.cid, fy))
        self.compare_statement("statements", label, "profit_loss_horizontal", s.profit_loss(self.conn, self.cid, fy, fmt="horizontal"))
        self.compare_statement("statements", label, "profit_loss_vertical", s.profit_loss(self.conn, self.cid, fy, fmt="vertical"))
        self.compare_statement("statements", label, "balance_sheet_horizontal", s.balance_sheet(self.conn, self.cid, fy, fmt="horizontal"))
        self.compare_statement("statements", label, "balance_sheet_vertical", s.balance_sheet(self.conn, self.cid, fy, fmt="vertical"))
        if self.c["entity_type"] in ("partnership", "llp"):
            self.compare_statement("statements", label, "appropriation", s.appropriation(self.conn, self.cid, fy))

    def sch3_body(self, fn, label: str, fy) -> dict:
        try:
            return fn(self.conn, self.cid, fy)
        except final_sch3.UnclassifiedError as exc:
            self.add("statements", f"{label} F-44: {exc.error.message}")
            return exc.statement

    def check_sch3(self, label: str, fy) -> None:
        for name, fn in (("sch3_balance_sheet", final_sch3.balance_sheet), ("sch3_profit_loss", final_sch3.profit_loss)):
            body = self.sch3_body(fn, label, fy)
            got = {}
            for line in body["left"]:
                got[(line["label"],)] = {"amount": money(line["amount"]), "previous_amount": money(line["previous_amount"])}
            want = table(self.cp.expected["expected_sch3"], ("label",), ("amount", "previous_amount"), fy=label, statement=name)
            self.diff("statements", want, got, ("amount", "previous_amount"), f"{label} {name}")
            for f in body["findings"]:
                if f["severity"] == "error":
                    self.add("statements", f"{label} {name} reports an error {f['rule_id']}: {f['message']}")
            self.report.notes.append(f"{self.key} {label} {name}: comparative source '{body['previous_source']}', rule status "
                                     f"'{body['rule_status_summary']}', warnings {sum(1 for f in body['findings'] if f['severity'] != 'error')}")

    def check_notes(self, label: str, fy) -> None:
        body = self.sch3_body(final_sch3.balance_sheet, label, fy)
        got = {}
        for note in body["notes"]:
            for line in note["lines"]:
                got[(str(note["note_no"]), line["label"])] = {"title": note["title"], "amount": money(line["amount"])}
        want = {(r["note_no"], r["label"]): {"title": r["title"], "amount": money(r["amount"])}
                for r in self.cp.expected["expected_notes"] if r["fy"] == label}
        self.diff("notes", want, got, ("title", "amount"), f"{label} note")

    def check_cash_flow(self, label: str, fy) -> None:
        body = final_cashflow.cash_flow(self.conn, self.cid, fy)
        got = {}
        for line in body["left"]:
            if (line["label"],) in got:
                self.add("cash_flow", f"{label}: the label {line['label']} appears twice")
            got[(line["label"],)] = {"amount": money(line["amount"])}
        want = table(self.cp.expected["expected_cash_flow"], ("label",), ("amount",), fy=label)
        self.diff("cash_flow", want, got, ("amount",), f"{label} cash flow")
        for f in body["findings"]:
            self.report.notes.append(f"{self.key} {label} cash flow {f['severity']} {f['rule_id']}: {f['message']}")

    # ------------------------------------------------------------------------------------------ close, carry-forward, reopen
    def raw_tb(self, as_on: date) -> dict[tuple, dict]:
        """The raw Trial Balance (closing and reversal vouchers included) of the year, nonzero ledgers only."""
        tb = reports.trial_balance(self.conn, self.cid, as_on)
        names = self.ledger_names()
        out = {}
        for section in tb.sections:
            for row in section.rows:
                if row.debit != 0 or row.credit != 0:
                    out[(names[row.ledger_id],)] = {"debit": money(row.debit), "credit": money(row.credit)}
        return out

    def expected_net_profit(self, label: str) -> str:
        if self.c["entity_type"] == "company":
            row = next(r for r in self.cp.expected["expected_sch3"]
                       if r["fy"] == label and r["statement"] == "sch3_profit_loss" and r["label"] == "Profit / (loss) for the year")
            return money(row["amount"])
        row = next(r for r in self.cp.expected["expected_statements"]
                   if r["fy"] == label and r["statement"] == "profit_loss_horizontal" and r["side"] == "left" and r["label"].startswith("Net profit"))
        return money(row["amount"])

    def close_year(self, label: str) -> None:
        fy = self.fy[label]
        start, end = fy_dates(label)
        with self.g("close"):
            chk = final_close.check(self.conn, self.cid, fy, create_next_year=True)
            for item in chk["items"]:
                if not item["ok"]:
                    self.add("close", f"{label} the pre-close check reports {item['rule_id']}: {item['message']}")
            made = final_close.close(self.conn, self.cid, fy, create_next_year=True, actor=ACTOR)
            self.close_ids[label] = made
            self.refresh_years()
            if money(made["net_profit"]) != self.expected_net_profit(label):
                self.add("close", f"{label} net profit expected {self.expected_net_profit(label)}, tool says {money(made['net_profit'])}")
            got, steps = {}, {}
            for step, vid in made["voucher_ids"].items():
                if vid is None:
                    continue
                rows = self.conn.execute(text("SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
                                              "WHERE vl.voucher_id = :v"), {"v": vid}).all()
                steps[step] = len(rows)
                for name, dr, cr in rows:
                    got[(step, name)] = {"debit": money(dr), "credit": money(cr)}
            want = table(self.cp.expected["expected_closing"], ("step", "ledger_name"), ("debit", "credit"), fy=label)
            self.diff("close", want, got, ("debit", "credit"), f"{label} closing entry")
            n = self.scalar("SELECT count(*) FROM statement_snapshots WHERE client_id = :c AND financial_year_id = :f AND is_final "
                            "AND superseded_at IS NULL", f=fy)
            if n != SNAPSHOTS_AT_CLOSE[self.key]:
                self.add("close", f"{label} final statement snapshots expected {SNAPSHOTS_AT_CLOSE[self.key]}, tool has {n}")
            locked = self.scalar("SELECT count(*) FROM periods WHERE client_id = :c AND financial_year_id = :f AND status = 'locked'", f=fy)
            if locked != PERIODS_LOCKED:
                self.add("close", f"{label} locked periods expected {PERIODS_LOCKED}, tool has {locked}")
            state = final_close.get_close(self.conn, self.cid, fy)
            if state["status"] != "closed":
                self.add("close", f"{label} close status expected closed, tool says {state['status']}")
            if self.c["entity_type"] != "company":  # the statements still show the year's trading after the close (F-40)
                        self.compare_statement("close", label, "trading", final_statements.trading(self.conn, self.cid, fy))
            else:
                self.check_sch3_after_close(label, fy)
        with self.g("carry_forward"):
            self.check_carry(label, fy)

    def check_sch3_after_close(self, label: str, fy) -> None:
        body = self.sch3_body(final_sch3.profit_loss, label, fy)
        got = {(line["label"],): {"amount": money(line["amount"])} for line in body["left"]}
        want = table(self.cp.expected["expected_sch3"], ("label",), ("amount",), fy=label, statement="sch3_profit_loss")
        self.diff("close", want, got, ("amount",), f"{label} Schedule III profit and loss after the close")

    def check_carry(self, label: str, fy) -> None:
        nxt = self.scalar("SELECT next_financial_year_id FROM year_end_closes WHERE client_id = :c AND financial_year_id = :f", f=fy)
        rows = self.conn.execute(text("SELECT l.name, o.debit, o.credit FROM opening_balances o JOIN ledgers l ON l.id = o.ledger_id "
                                      "WHERE o.financial_year_id = :f"), {"f": nxt}).all()
        got = {(name,): {"debit": money(dr), "credit": money(cr)} for name, dr, cr in rows}
        want = table(self.cp.expected["expected_carried"], ("ledger_name",), ("debit", "credit"), fy=label)
        self.diff("carry_forward", want, got, ("debit", "credit"), f"{label} opening of the next year")
        total_dr = sum((Decimal(v["debit"]) for v in got.values()), Decimal(0))
        total_cr = sum((Decimal(v["credit"]) for v in got.values()), Decimal(0))
        if total_dr != total_cr:
            self.add("carry_forward", f"{label} the carried openings do not balance: Dr {money(total_dr)} Cr {money(total_cr)}")
        _, end = fy_dates(label)
        raw = self.raw_tb(end)  # after the closing entries every ledger of the year holds exactly what is carried
        self.diff("carry_forward", want, raw, ("debit", "credit"), f"{label} ledger balance after the closing entries")
        it = self.conn.execute(text("SELECT block_key, opening_wdv FROM it_block_openings WHERE client_id = :c AND financial_year_id = :f"),
                               {"c": self.cid, "f": nxt}).all()
        got_it = {(b,): {"opening_wdv": money(w)} for b, w in it}
        want_it = table(self.cp.expected["expected_carried_it"], ("block_key",), ("opening_wdv",), fy=label)
        self.diff("carry_forward", want_it, got_it, ("opening_wdv",), f"{label} income-tax block carried")
        self.report.notes.append(f"{self.key} {label} carried {len(got)} ledger opening(s), {len(got_it)} income-tax block(s)")

    def reopen_check(self) -> None:
        label = self.c["close_years"][0]
        fy = self.fy[label]
        _, end = fy_dates(label)
        with self.g("reopen"):
            close_id = final_close.get_close(self.conn, self.cid, fy)["close_id"]
            if label != self.c["years"][-1]:  # a later year has postings: the reopen must be refused (F-64)
                try:
                    final_close.reopen(self.conn, self.cid, close_id, "Pack check: reopen with a later year posted", actor=ACTOR)
                    self.add("reopen", f"{label} the reopen was accepted although the next year has posted vouchers")
                except ServiceError as refusal:
                    if refusal.code != "reopen_blocked":
                        self.add("reopen", f"{label} the reopen was refused with '{refusal.code}', expected 'reopen_blocked'")
                    else:
                        self.report.counts["reopen_refused"] += 1
                if final_close.get_close(self.conn, self.cid, fy)["status"] != "closed":
                    self.add("reopen", f"{label} the close is no longer 'closed' after a refused reopen")
                return
            result = final_close.reopen(self.conn, self.cid, close_id, "Pack check: late purchase bill found", actor=ACTOR)
            if len(result["reversal_voucher_ids"]) != 3:
                self.add("reopen", f"{label} expected 3 reversal vouchers, the tool made {len(result['reversal_voucher_ids'])}")
            if final_close.get_close(self.conn, self.cid, fy)["status"] != "reopened":
                self.add("reopen", f"{label} close status expected reopened")
            reversed_n = self.scalar("SELECT count(*) FROM vouchers WHERE client_id = :c AND status = 'reversed'")
            if reversed_n != 3:
                self.add("reopen", f"{label} reversed vouchers expected 3 (the closing entries), tool has {reversed_n}")
            snap = "SELECT count(*) FROM statement_snapshots WHERE client_id = :c AND financial_year_id = :f AND is_final AND superseded_at IS NULL"
            nxt = "(SELECT next_financial_year_id FROM year_end_closes WHERE client_id = :c AND financial_year_id = :f)"
            checks = [
                ("locked periods", "SELECT count(*) FROM periods WHERE client_id = :c AND financial_year_id = :f AND status = 'locked'"),
                ("final statement snapshots", snap),
                ("openings of the next year", f"SELECT count(*) FROM opening_balances WHERE financial_year_id = {nxt}"),
            ]
            for what, sql in checks:
                n = self.scalar(sql, f=fy)
                if n != 0:
                    self.add("reopen", f"{label} {what} expected 0 after the reopen, tool has {n}")
            want = table(self.cp.expected["expected_trial_balance"], ("ledger_name",), ("debit", "credit"), fy=label)
            self.diff("reopen", want, self.raw_tb(end), ("debit", "credit"), f"{label} ledger balance after the reopen")
            self.compare_statement("reopen", label, "trading", final_statements.trading(self.conn, self.cid, fy))
            # close again: new vouchers, the same carried openings
            again = final_close.close(self.conn, self.cid, fy, create_next_year=False, actor=ACTOR)
            if money(again["net_profit"]) != self.expected_net_profit(label):
                self.add("reopen", f"{label} net profit after closing again expected {self.expected_net_profit(label)}, tool says {money(again['net_profit'])}")
            with self.g("carry_forward"):
                self.check_carry(label, fy)
            self.report.counts["reclosed"] += 1

    def run(self) -> None:
        self.setup()
        for label in self.c["years"]:
            self.run_year(label)
            if label in self.c["close_years"]:
                self.close_year(label)
        self.reopen_check()


def run_pack_p6(conn: Connection, pack: PackP6) -> RunReport:
    report = RunReport(pack.folder.name)
    for key in pack.clients:
        try:
            World6(conn, pack, key, report).run()
        except Exception as crash:  # noqa: BLE001 - a client that cannot be set up must not hide the others
            report.add(f"{key}/setup", f"the run of this client stopped: {type(crash).__name__}: {crash}")
    return report
