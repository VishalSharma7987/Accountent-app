"""Loaders and pickers of the GST rule tables (law is data, CLAUDE.md 2.5). Every picker is pure and chooses the
rule in force on the TRANSACTION date; two rules in force for one key/prefix is an error (AmbiguousRuleError),
never a guess. `verification_status` and `source_reference` travel with every row; `status_summary` rolls them up so
screens and workings can show "pending" until the owner's CA has signed the legal text.

The SQL lives in db/repositories_gst_masters.py; the `load_*` / `rate_for` functions here take a Connection.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection

from app.db import repositories_gst_masters as repo
from app.engine.gst_masters import in_force, periods_overlap
from app.engine.gst_types import (
    BlockedRule,
    CompositionRule,
    ItcCondition,
    RateRule,
    RateSlab,
    RcmRule,
    StateCode,
    Threshold,
)

_STATUS_ORDER = ("pending", "secondary_verified", "verified")  # weakest first


class AmbiguousRuleError(Exception):
    """Two rules are in force on the date for the same key: the table is wrong, the caller must not guess."""


@dataclass(frozen=True)
class Uqc:
    code: str
    description: str
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


def _in_force(row: object, on: date) -> bool:
    return in_force(row.effective_from, row.effective_to, on)  # type: ignore[attr-defined]


def states_in_force(rows: Iterable[StateCode], on: date) -> list[StateCode]:
    return sorted((r for r in rows if _in_force(r, on)), key=lambda r: r.code)


def pick_by_date[T](rows: Iterable[T], key_attr: str, key: str, on: date) -> T | None:
    """The one row of `key` in force on `on`; None if there is none."""
    found = [r for r in rows if getattr(r, key_attr) == key and _in_force(r, on)]
    if len(found) > 1:
        raise AmbiguousRuleError(f"{len(found)} rules for '{key}' are in force on {on.isoformat()}.")
    return found[0] if found else None


def pick_rcm(rows: Iterable[RcmRule], category_key: str, on: date) -> RcmRule | None:
    return pick_by_date(rows, "category_key", category_key, on)


def pick_blocked(rows: Iterable[BlockedRule], category_key: str, on: date) -> BlockedRule | None:
    return pick_by_date(rows, "category_key", category_key, on)


def pick_condition(rows: Iterable[ItcCondition], condition_key: str, on: date) -> ItcCondition | None:
    return pick_by_date(rows, "condition_key", condition_key, on)


def pick_threshold(rows: Iterable[Threshold], threshold_key: str, on: date) -> Threshold | None:
    return pick_by_date(rows, "threshold_key", threshold_key, on)


def pick_composition(rows: Iterable[CompositionRule], category: str, on: date) -> CompositionRule | None:
    return pick_by_date(rows, "category", category, on)


def pick_rate(rules: Iterable[RateRule], hsn_sac: str, supply_kind: str, on: date) -> tuple[RateRule | None, bool]:
    """Rate rule for a code: the longest matching prefix in force on `on` (same supply kind). When no prefix matches,
    the `default` rule of SERVICES only (is_default = True: the caller warns "default rate applied"). No rule ->
    (None, False): the caller rejects with the code and date (rule G-10)."""
    in_date = [r for r in rules if r.supply_kind == supply_kind and _in_force(r, on)]
    matches = [r for r in in_date if r.code_prefix is not None and hsn_sac.startswith(r.code_prefix)]
    if matches:
        longest = max(len(r.code_prefix) for r in matches)  # type: ignore[arg-type]
        best = [r for r in matches if len(r.code_prefix) == longest]  # type: ignore[arg-type]
        if len(best) > 1:
            raise AmbiguousRuleError(
                f"Rates '{best[0].rule_key}' and '{best[1].rule_key}' both apply to code {hsn_sac} on {on.isoformat()}."
            )
        return best[0], False
    if supply_kind == "services":
        defaults = [r for r in in_date if r.code_kind == "default"]
        if len(defaults) > 1:
            raise AmbiguousRuleError(f"{len(defaults)} default service rates are in force on {on.isoformat()}.")
        if defaults:
            return defaults[0], True
    return None, False


def slab_in_force(slabs: Iterable[RateSlab], rate: Decimal, on: date, *, allow_special: bool = False) -> bool:
    """G-11: is `rate` a slab in force on the date? Special rates count only with allow_special."""
    return any(
        s.rate == rate and _in_force(s, on) and (allow_special or not s.is_special) for s in slabs
    )


def _row_name(row: object) -> str:
    return str(getattr(row, "id", None) or row.effective_from.isoformat())  # type: ignore[attr-defined]


def find_overlaps[T](rows: Sequence[T], key: Callable[[T], str]) -> list[tuple[str, str, str]]:
    """Rows of the same key whose periods overlap, as (key, id_of_first, id_of_second); a row without `.id` is named
    by its start date. Sorted by key then start date."""
    by_key: dict[str, list[T]] = defaultdict(list)
    for row in rows:
        by_key[key(row)].append(row)
    out = []
    for k in sorted(by_key):
        group = sorted(by_key[k], key=lambda r: r.effective_from)  # type: ignore[attr-defined]
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if periods_overlap(a.effective_from, a.effective_to, b.effective_from, b.effective_to):  # type: ignore[attr-defined]
                    out.append((k, _row_name(a), _row_name(b)))
    return out


def status_summary(rows: Iterable[object]) -> dict:
    """Counts per verification_status and the weakest one as `overall` (no rows = pending: nothing is verified)."""
    counts: dict[str, int] = {}
    for row in rows:
        status = row.verification_status  # type: ignore[attr-defined]
        counts[status] = counts.get(status, 0) + 1
    overall = next((s for s in _STATUS_ORDER if s in counts), "pending")
    return {"overall": overall, "counts": counts}


# ---- loaders (SQL through the repository) ---------------------------------------------------------------------


def state_codes(conn: Connection, on: date) -> list[StateCode]:
    return [StateCode(*r) for r in repo.state_code_rows(conn, on)]


def uqc_list(conn: Connection, on: date) -> list[Uqc]:
    return [Uqc(*r) for r in repo.uqc_rows(conn, on)]


def slabs(conn: Connection, on: date) -> list[RateSlab]:
    return [RateSlab(*r) for r in repo.slab_rows(conn, on)]


def rate_rules_for(conn: Connection, hsn_sac: str, supply_kind: str, on: date) -> list[RateRule]:
    return [RateRule(*r) for r in repo.rate_rule_rows(conn, hsn_sac, supply_kind, on)]


def rate_for(conn: Connection, hsn_sac: str, supply_kind: str, on: date) -> tuple[RateRule | None, bool]:
    """(rule, is_default) for a code on a date; (None, False) when no rule is in force (see pick_rate)."""
    return pick_rate(rate_rules_for(conn, hsn_sac, supply_kind, on), hsn_sac, supply_kind, on)


def rcm_rules(conn: Connection, on: date) -> list[RcmRule]:
    return [RcmRule(*r) for r in repo.rcm_rule_rows(conn, on)]


def rcm_rule(conn: Connection, key: str, on: date) -> RcmRule | None:
    return pick_rcm(rcm_rules(conn, on), key, on)


def blocked_rules(conn: Connection, on: date) -> list[BlockedRule]:
    return [BlockedRule(*r) for r in repo.blocked_rule_rows(conn, on)]


def blocked_rule(conn: Connection, key: str, on: date) -> BlockedRule | None:
    return pick_blocked(blocked_rules(conn, on), key, on)


def itc_conditions(conn: Connection, on: date) -> list[ItcCondition]:
    return [ItcCondition(*r) for r in repo.itc_condition_rows(conn, on)]


def itc_condition(conn: Connection, key: str, on: date) -> ItcCondition | None:
    return pick_condition(itc_conditions(conn, on), key, on)


def thresholds(conn: Connection, on: date) -> list[Threshold]:
    return [Threshold(*r) for r in repo.threshold_rows(conn, on)]


def threshold(conn: Connection, key: str, on: date) -> Threshold | None:
    return pick_threshold(thresholds(conn, on), key, on)


def composition_rules(conn: Connection, on: date) -> list[CompositionRule]:
    return [CompositionRule(*r) for r in repo.composition_rule_rows(conn, on)]


def composition_rule(conn: Connection, category: str, on: date) -> CompositionRule | None:
    return pick_composition(composition_rules(conn, on), category, on)
