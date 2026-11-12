"""Runs a test pack through the REAL services (create client -> openings -> create/approve/post vouchers ->
reversals -> period locks -> wrong vouchers) and compares the result with the pack's expected files.

It never modifies a pack file. Differences are collected as plain lines for the accountants:
    Cash: expected Dr 54,200.00, tool says Dr 54,000.00
"""

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import groupby

from chart_fixture import EXPECTED_GROUPS
from pack_loader import Pack, balance_warnings
from sqlalchemy import Connection, text

from app.engine.models import VoucherDraft, VoucherLine
from app.engine.money import format_inr
from app.services import client_setup, periods, reports, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError

ACTOR = "pack-runner"
GROUP_CODE_BY_NAME = {name: code for code, name, *_ in EXPECTED_GROUPS}
ZERO = Decimal("0.00")


@dataclass
class RunReport:
    pack: str
    problems: list[str] = field(default_factory=list)  # every difference, one line each
    warnings: list[str] = field(default_factory=list)  # pack self-check (warning only)
    posted: int = 0  # correct vouchers posted
    reversed: int = 0
    wrong_checked: int = 0  # wrong vouchers that were correctly rejected


def side(debit: Decimal, credit: Decimal) -> str:
    """'Dr 54,200.00' / 'Cr 1,00.00' / 'nil' for a closing balance given as two columns."""
    if debit > 0 and credit > 0:
        return f"Dr {format_inr(debit)} and Cr {format_inr(credit)}"
    if debit > 0:
        return f"Dr {format_inr(debit)}"
    if credit > 0:
        return f"Cr {format_inr(credit)}"
    return "nil"


def describe_difference(name: str, expected: tuple[Decimal, Decimal], actual: tuple[Decimal, Decimal]) -> str:
    """One report line for a ledger whose expected and actual closing balances differ."""
    net_expected, net_actual = expected[0] - expected[1], actual[0] - actual[1]
    return (
        f"{name}: expected {side(*expected)}, tool says {side(*actual)} "
        f"(difference {format_inr(abs(net_expected - net_actual))})"
    )


def format_report(report: RunReport) -> str:
    lines = [f"Pack '{report.pack}': {len(report.problems)} difference(s)"]
    lines += [f"  - {p}" for p in report.problems]
    lines.append(
        f"  ({report.posted} vouchers posted, {report.reversed} reversed, {report.wrong_checked} wrong vouchers rejected)"
    )
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ helpers


def _group_name_of_ledger(conn: Connection, ledger_id: object) -> str:
    return conn.execute(
        text("SELECT g.name FROM ledgers l JOIN account_groups g ON g.id = l.group_id WHERE l.id = :id"),
        {"id": ledger_id},
    ).scalar_one()


def _amount(value: Decimal) -> str | None:
    return None if value == 0 else f"{value:.2f}"


def _vouchers(rows):
    return [(ref, list(group)) for ref, group in groupby(rows, key=lambda r: r.ref_id)]


class _Names:
    """Pack ledger name -> the tool's ledger id. A name the tool does not know maps to a value that is not a
    ledger, so the engine reports it as an unknown ledger (rule V-05) instead of the runner hiding it."""

    def __init__(self, ids: dict[str, object]):
        self.ids = ids

    def id(self, name: str) -> object:
        return self.ids.get(name, f"no ledger named '{name}'")


# ------------------------------------------------------------------------------------------------- the run


def run_pack(conn: Connection, pack: Pack) -> RunReport:
    report = RunReport(pack.folder.name)
    report.warnings = balance_warnings(pack)
    problems = report.problems
    client = pack.client

    # 1. the client with its standard ledgers, then the pack's own ledgers
    created = client_setup.create_client(
        conn,
        ClientProfile(client.name, client.entity_type, client.business_type, client.gst_type),
        fy_start=client.fy_start,
        actor=ACTOR,
        proprietor_name=client.proprietor_name or None,
        partners=list(client.partners) or None,
    )
    template_ids = {name.lower(): (name, lid) for name, lid in created.ledger_ids.items()}
    ids: dict[str, object] = {}
    tool_name: dict[str, str] = {}  # pack ledger name -> name in the tool (same, unless only the case differs)
    for row in pack.ledgers:
        if row.name.lower() in template_ids:
            name, lid = template_ids[row.name.lower()]
            actual_group = _group_name_of_ledger(conn, lid)
            if actual_group != row.group:
                problems.append(f"ledger {row.name}: the pack puts it under '{row.group}' but the tool's standard ledger is under '{actual_group}'")
            if name != row.name:
                problems.append(f"ledger {row.name}: the tool's standard ledger is spelt '{name}' (names must match exactly)")
            ids[row.name], tool_name[row.name] = lid, name
        else:
            ids[row.name] = client_setup.add_ledger(conn, created.client_id, row.name, GROUP_CODE_BY_NAME[row.group], actor=ACTOR)
            tool_name[row.name] = row.name
    names = _Names(ids)

    # 2. opening balances
    for row in pack.ledgers:
        if row.opening_dr > 0 or row.opening_cr > 0:
            try:
                client_setup.set_opening_balance(
                    conn, created.client_id, created.financial_year_id, ids[row.name],
                    _amount(row.opening_dr), _amount(row.opening_cr), actor=ACTOR,
                )
            except ServiceError as refusal:
                problems.append(f"opening balance of {row.name} refused: {refusal.message}")
    check = client_setup.opening_balance_difference(conn, created.client_id, created.financial_year_id)
    if not check.is_balanced:
        problems.append(f"opening balances differ: Dr {format_inr(check.total_debit)} vs Cr {format_inr(check.total_credit)}")

    # 3. the correct vouchers: create -> approve -> post, in file order
    posted_ids: dict[str, object] = {}
    for ref, rows in _vouchers(pack.vouchers):
        head = rows[0]
        draft = VoucherDraft(
            created.client_id, head.voucher_type, head.date, head.narration, head.reference_no or None,
            names.id(head.party_ledger) if head.party_ledger else None,
            tuple(VoucherLine(names.id(r.ledger_name), _amount(r.debit), _amount(r.credit)) for r in rows),
        )
        try:
            result = vouchers.create_draft(conn, draft, actor=ACTOR)
            if result.errors:
                problems.append(f"correct voucher {ref} was refused: " + "; ".join(f"{e.rule_id} {e.message}" for e in result.errors))
                continue
            vouchers.approve(conn, result.voucher_id, actor=ACTOR)
            vouchers.post(conn, result.voucher_id, actor=ACTOR)
        except ServiceError as refusal:
            problems.append(f"correct voucher {ref} could not be posted: {refusal.message}")
            continue
        posted_ids[ref] = result.voucher_id
        report.posted += 1

    # 4. reversals
    for r in pack.reversals:
        if r.ref_id not in posted_ids:
            problems.append(f"reversal of {r.ref_id} skipped: the voucher was not posted")
            continue
        try:
            vouchers.reverse(conn, posted_ids[r.ref_id], r.reversal_date, r.reason, actor=ACTOR)
            report.reversed += 1
        except ServiceError as refusal:
            problems.append(f"reversal of {r.ref_id} refused: {refusal.message}")

    # 5. locked periods (after the correct vouchers, before the wrong ones)
    year_periods = periods.list_periods(conn, created.client_id, created.financial_year_id)
    for month in pack.locked_periods:
        match = next((p for p in year_periods if p.start.strftime("%Y-%m") == month), None)
        if match is None:
            problems.append(f"locked month {month}: the tool has no such period")
            continue
        try:
            periods.lock_period(conn, created.client_id, match.id, actor=ACTOR)
        except ServiceError as refusal:
            problems.append(f"locking {month} refused: {refusal.message}")

    # 6. the wrong vouchers must all be rejected, with the promised rule (and only that rule)
    for ref, rows in _vouchers(pack.invalid_vouchers):
        head = rows[0]
        draft = VoucherDraft(
            created.client_id, head.voucher_type, head.date, head.narration, head.reference_no or None,
            names.id(head.party_ledger) if head.party_ledger else None,
            tuple(VoucherLine(names.id(r.ledger_name), r.debit or None, r.credit or None) for r in rows),
        )
        expected_rule, word = head.expected_rule_id, head.expected_message_contains
        try:
            result = vouchers.create_draft(conn, draft, actor=ACTOR)
        except ServiceError as refusal:
            problems.append(f"wrong voucher {ref}: the tool raised '{refusal.message}' instead of a rule error")
            continue
        if result.voucher_id is not None:
            problems.append(f"wrong voucher {ref} (expected {expected_rule}) was ACCEPTED and saved as a draft")
            continue
        got = {e.rule_id for e in result.errors}
        shown = "; ".join(f"{e.rule_id}: {e.message}" for e in result.errors)
        if expected_rule not in got:
            problems.append(f"wrong voucher {ref}: expected rule {expected_rule}, the tool reported {shown}")
        elif got != {expected_rule}:
            problems.append(f"wrong voucher {ref}: wrong in more than one way; expected only {expected_rule}, the tool reported {shown}")
        elif not any(word.lower() in e.message.lower() for e in result.errors if e.rule_id == expected_rule):
            problems.append(f"wrong voucher {ref}: the {expected_rule} message does not contain '{word}': {shown}")
        else:
            report.wrong_checked += 1

    _compare_with_expected(conn, pack, created.client_id, tool_name, report)
    return report


def _compare_with_expected(conn, pack: Pack, client_id, tool_name: dict[str, str], report: RunReport) -> None:
    problems = report.problems
    tb = reports.trial_balance(conn, client_id, pack.client.pack_end_date)
    actual = {row.ledger_name: (row.debit, row.credit, row.group_path[-1]) for s in tb.sections for row in s.rows}

    # every ledger's closing balance
    listed = set()
    for exp in pack.expected_balances:
        name = tool_name.get(exp.ledger_name, exp.ledger_name)
        listed.add(name)
        if name not in actual:
            problems.append(f"{exp.ledger_name}: not found in the tool's Trial Balance")
            continue
        got = actual[name][:2]
        want = (exp.closing_dr, exp.closing_cr)
        if got != want:
            problems.append(describe_difference(exp.ledger_name, want, got))
    for name, (dr, cr, _) in actual.items():
        if name not in listed and (dr > 0 or cr > 0):
            problems.append(f"{name}: not in the pack but the tool shows {side(dr, cr)}")

    # every Trial Balance line (group and amounts) and the totals
    for line in pack.expected_tb:
        name = tool_name.get(line.ledger_name, line.ledger_name)
        if name not in actual:
            continue  # already reported above
        dr, cr, group = actual[name]
        if (dr, cr) != (line.dr, line.cr):
            problems.append("Trial Balance line " + describe_difference(line.ledger_name, (line.dr, line.cr), (dr, cr)))
        if group != line.group_name:
            problems.append(f"Trial Balance line {line.ledger_name}: expected under '{line.group_name}', the tool has it under '{group}'")
    want_total = pack.expected_tb_total
    if (tb.total_debit, tb.total_credit) != want_total:
        problems.append(
            f"Trial Balance totals: expected Dr {format_inr(want_total[0])} / Cr {format_inr(want_total[1])}, "
            f"tool says Dr {format_inr(tb.total_debit)} / Cr {format_inr(tb.total_credit)}"
        )
    if not tb.is_balanced:
        problems.append(f"the tool's Trial Balance does not balance: difference {format_inr(tb.difference.amount)} {tb.difference.side}")

