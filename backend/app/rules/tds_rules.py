"""Loaders and pickers of the TDS / TCS rule tables (law is data, CLAUDE.md 2.5; Phase 4, package A). Every picker is
pure and chooses the row in force on the TRANSACTION date (the caller passes the event date: the earlier of payment and
credit date). Two rows in force for one key is an error (AmbiguousRuleError), never a guess; no row -> None and the
caller refuses (rule T-02). `verification_status` and `source_reference` travel with every row; `rule_status` rolls them
up (T-50) so screens show "pending" until the owner's CA has signed the legal values.

The SQL lives in db/repositories_tds_masters.py; the `load_*` functions here take a Connection.
"""

from collections.abc import Iterable, Mapping
from datetime import date

from sqlalchemy import Connection

from app.db import repositories_tds_masters as repo
from app.engine.gst_masters import in_force
from app.engine.tds_types import (
    DueDateRule,
    FormRule,
    InterestRule,
    Nature,
    Provision,
    RateRule,
    SectionRef,
)
from app.rules.gst_rules import AmbiguousRuleError, status_summary

__all__ = [
    "AmbiguousRuleError",
    "deductee_group",
    "load_due_dates",
    "load_forms",
    "load_interest_rules",
    "load_natures",
    "load_provisions",
    "load_rates",
    "load_section_refs",
    "pick_by_date",
    "pick_form",
    "pick_rate",
    "pick_section_ref",
    "rate_lookup",
    "rule_status",
    "section_map",
    "status_summary",
]

_STATUS_ORDER = ("pending", "secondary_verified", "verified")  # weakest first
_ACTS = ("it_act_1961", "it_act_2025")


def deductee_group(deductee_type: str) -> str:
    """T-04: individual / HUF pay the lower rate group; every other type (company, firm, LLP, AOP, society, trust,
    local authority, other) is 'others'."""
    return "individual_huf" if deductee_type in ("individual", "huf") else "others"


def _in(row: object, on: date) -> bool:
    return in_force(row.effective_from, row.effective_to, on)  # type: ignore[attr-defined]


def pick_by_date[T](rows: Iterable[T], key_attr: str, key: str, on: date) -> T | None:
    found = [r for r in rows if getattr(r, key_attr) == key and _in(r, on)]
    if len(found) > 1:
        raise AmbiguousRuleError(f"{len(found)} rules for '{key}' are in force on {on.isoformat()}.")
    return found[0] if found else None


def pick_form(rows: Iterable[FormRule], form_key: str, on: date) -> FormRule | None:
    return pick_by_date(rows, "form_key", form_key, on)


def pick_section_ref(rows: Iterable[SectionRef], nature_key: str, act: str, on: date) -> SectionRef | None:
    """The section / table entry of the nature under the Act, in force on `on` (None = not mapped)."""
    found = [r for r in rows if r.nature_key == nature_key and r.act == act and _in(r, on)]
    if len(found) > 1:
        raise AmbiguousRuleError(f"{len(found)} section references for '{nature_key}' ({act}) are in force on {on.isoformat()}.")
    return found[0] if found else None


def pick_rate(rows: Iterable[RateRule], nature_key: str, group: str, on: date) -> RateRule | None:
    """The rate rule of the nature in force on `on` for the deductee group (an exact group row or a group 'any' row).
    None when nothing is in force (rule T-02). A specific row and an 'any' row in force together are ambiguous."""
    found = [r for r in rows if r.nature_key == nature_key and r.deductee_group in (group, "any") and _in(r, on)]
    if len(found) > 1:
        raise AmbiguousRuleError(
            f"{len(found)} rate rules for '{nature_key}' ({group}) are in force on {on.isoformat()}: "
            "the rule table has overlapping rows.")
    return found[0] if found else None


def _source(row: object) -> str:
    return (getattr(row, "source_reference", None) or getattr(row, "due_key", None) or getattr(row, "interest_key", None)
            or getattr(row, "form_key", None) or getattr(row, "provision_key", None) or "?")


def rule_status(tables: Mapping[str, Iterable[object]]) -> dict:
    """T-50: {"worst", "tables": {name: weakest status}, "pending_sources": [distinct source references of pending rows]}.
    No tables or empty tables count as pending: nothing is verified."""
    per_table: dict[str, str] = {}
    pending: list[str] = []
    for name, rows in tables.items():
        rows = list(rows)
        per_table[name] = status_summary(rows)["overall"]
        for row in rows:
            if row.verification_status == "pending":  # type: ignore[attr-defined]
                source = _source(row)
                if source not in pending:
                    pending.append(source)
    worst = next((s for s in _STATUS_ORDER if s in per_table.values()), "pending")
    return {"worst": worst, "tables": per_table, "pending_sources": pending}


def section_map(natures: Iterable[Nature], refs: Iterable[SectionRef], on: date) -> list[dict]:
    """Old <-> new section map: per nature the 1961 and 2025 section, the 2025 table entry and payment code, the weakest
    status of the two rows and the Act in force on `on` (None before the first rule). For each Act the row in force on
    `on` is shown, else the row nearest to it (the latest one), so the screen always shows both sides."""
    refs = list(refs)
    out = []
    for nature in natures:
        chosen: dict[str, SectionRef] = {}
        for act in _ACTS:
            mine = sorted((r for r in refs if r.nature_key == nature.nature_key and r.act == act),
                          key=lambda r: r.effective_from)
            current = [r for r in mine if _in(r, on)]
            if current:
                chosen[act] = current[0]
            elif mine:
                chosen[act] = mine[-1]
        old, new = chosen.get("it_act_1961"), chosen.get("it_act_2025")
        statuses = [r.verification_status for r in (old, new) if r is not None]
        status = next((s for s in _STATUS_ORDER if s in statuses), "pending")
        in_force_act = next((r.act for r in chosen.values() if _in(r, on)), None)
        out.append({
            "nature_key": nature.nature_key, "description": nature.description,
            "sec_1961": old.section_ref if old else None, "sec_2025": new.section_ref if new else None,
            "table_ref_2025": new.table_ref if new else None, "payment_code_2025": new.payment_code if new else None,
            "act_in_force": in_force_act, "status": status,
        })
    return out


# ---- loaders (SQL through the repository) ---------------------------------------------------------------------


def load_natures(conn: Connection) -> list[Nature]:
    return [Nature(*r) for r in repo.nature_rows(conn)]


def load_section_refs(conn: Connection) -> list[SectionRef]:
    """All rows (both Acts, all dates): the section map shows both sides."""
    return [SectionRef(*r) for r in repo.section_ref_rows(conn)]


def load_rates(conn: Connection, on: date, nature_key: str | None = None) -> list[RateRule]:
    return [RateRule(*r) for r in repo.rate_rows(conn, on, nature_key)]


def load_provisions(conn: Connection, on: date) -> list[Provision]:
    return [Provision(*r) for r in repo.provision_rows(conn, on)]


def load_due_dates(conn: Connection, on: date) -> list[DueDateRule]:
    return [DueDateRule(*r) for r in repo.due_date_rows(conn, on)]


def load_interest_rules(conn: Connection, on: date) -> list[InterestRule]:
    return [InterestRule(*r) for r in repo.interest_rows(conn, on)]


def load_forms(conn: Connection, on: date) -> list[FormRule]:
    return [FormRule(*r) for r in repo.form_rows(conn, on)]


def rate_lookup(conn: Connection, nature_key: str, group: str, on: date) -> RateRule | None:
    """The rate rule for a nature and deductee group on a date (None = no rule: the caller refuses, T-02)."""
    return pick_rate(load_rates(conn, on, nature_key), nature_key, group, on)
