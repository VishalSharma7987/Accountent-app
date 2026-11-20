"""Tally -> LedgerMind mapping rules (Phase 7 package B, D-31..D-37). Pure Python: no DB, web, LLM or XML imports.

Groups: Tally's predefined groups map by a fixed table; a custom group is mapped through its chain of parents up to a predefined
group; anything else is "unknown" and the accountant decides. Nothing is created here. Amounts are Decimal and are never
rounded: more than two decimals were already refused by the reader.

NOT VERIFIED against a real Tally company: the table of predefined groups and the debit / credit sign convention below are the
documented behaviour as understood by the developers. The accountant confirms them with a real export (docs/decisions_parts/B7.md).
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")


def name_key(name: str) -> str:
    """The key under which a Tally name is remembered: trimmed, lower case, inner spaces collapsed."""
    return " ".join(name.lower().split())


# Tally predefined group (by name_key) -> system group code of LedgerMind, or None = no equivalent (the accountant decides).
PREDEFINED_GROUPS: dict[str, str | None] = {
    "capital account": "capital_account",
    "reserves & surplus": "reserves_surplus",
    "loans (liability)": "loans_liability",
    "bank od a/c": "loans_liability",          # a sub-group of Loans (Liability) in Tally
    "secured loans": "loans_liability",
    "unsecured loans": "loans_liability",
    "current liabilities": "current_liabilities",
    "sundry creditors": "sundry_creditors",
    "duties & taxes": "duties_taxes",
    "provisions": "provisions",
    "fixed assets": "fixed_assets",
    "investments": "investments",
    "current assets": "current_assets",
    "sundry debtors": "sundry_debtors",
    "bank accounts": "bank_accounts",
    "cash-in-hand": "cash_in_hand",
    "stock-in-hand": "stock_in_hand",
    "loans & advances (asset)": "loans_advances_asset",
    "deposits (asset)": "deposits_asset",
    "sales accounts": "sales_accounts",
    "direct incomes": "direct_incomes",
    "income (direct)": "direct_incomes",
    "indirect incomes": "indirect_incomes",
    "income (indirect)": "indirect_incomes",
    "purchase accounts": "purchase_accounts",
    "direct expenses": "direct_expenses",
    "expenses (direct)": "direct_expenses",
    "indirect expenses": "indirect_expenses",
    "expenses (indirect)": "indirect_expenses",
    "suspense a/c": "suspense",
    "misc. expenses (asset)": None,            # no such group here: the accountant chooses
    "branch / divisions": None,
    "primary": None,
}

MAX_CHAIN = 20


@dataclass(frozen=True)
class GroupSuggestion:
    code: str | None        # system group code, None = needs the accountant
    predefined: bool        # the name itself is a Tally predefined group with a code
    chain: tuple[str, ...]  # the names walked, starting with the group itself
    reason: str


def resolve_group(
    name: str | None, defined: Mapping[str, str | None], confirmed: Mapping[str, str] | None = None
) -> GroupSuggestion:
    """D-31. `defined` = name_key -> parent name (or None) of the groups defined in the file; `confirmed` = name_key -> system
    group code the accountant already confirmed for a custom group in an earlier import."""
    confirmed = confirmed or {}
    if name is None or not name.strip():
        return GroupSuggestion(None, False, (), "The ledger has no parent group in the file; choose its group.")
    chain: list[str] = []
    current: str | None = name
    while current is not None:
        key = name_key(current)
        chain.append(current)
        if key in PREDEFINED_GROUPS:
            code = PREDEFINED_GROUPS[key]
            if code is None:
                return GroupSuggestion(None, False, tuple(chain), f"'{current}' is a Tally group with no equivalent here; choose a group.")
            if len(chain) == 1:
                return GroupSuggestion(code, True, tuple(chain), f"'{current}' is a standard Tally group.")
            return GroupSuggestion(code, False, tuple(chain), "Custom group; its parents are " + " > ".join(chain[1:]) + ".")
        if key in confirmed:
            return GroupSuggestion(confirmed[key], False, tuple(chain), f"'{current}' was mapped earlier by an accountant.")
        if key not in defined:
            return GroupSuggestion(None, False, tuple(chain),
                                   f"Group '{current}' is neither a standard Tally group nor defined in the file; choose a group.")
        if len(chain) >= MAX_CHAIN or any(name_key(x) == name_key(defined[key] or "") for x in chain):
            return GroupSuggestion(None, False, tuple(chain), "The groups of the file refer to each other in a circle; choose a group.")
        current = defined[key]
    return GroupSuggestion(None, False, tuple(chain), f"The parent chain of '{name}' ends without a standard group; choose a group.")


@dataclass(frozen=True)
class LedgerSuggestion:
    target_group_code: str | None
    existing_ledger_id: object | None
    needs_decision: bool
    rule_id: str
    reason: str


def suggest_ledger(
    name: str, group: GroupSuggestion, existing_id: object | None, existing_group_code: str | None, existing_group_name: str | None = None
) -> LedgerSuggestion:
    """D-31 / D-32: a ledger is never overwritten and never created without the accountant's decision."""
    if existing_id is not None and group.code is not None and existing_group_code == group.code:
        return LedgerSuggestion(group.code, existing_id, False, "D-32",
                                f"A ledger named '{name}' already exists in the same group. Confirm to use it.")
    if existing_id is not None:
        where = existing_group_name or existing_group_code or "another group"
        return LedgerSuggestion(group.code, existing_id, True, "D-32",
                                f"A ledger named '{name}' already exists in '{where}', but Tally has it in a different group. "
                                "It is not changed. Decide: use the existing ledger, or skip.")
    if group.code is None:
        return LedgerSuggestion(None, None, True, "D-31", group.reason)
    return LedgerSuggestion(group.code, None, False, "D-31", f"No ledger named '{name}' yet. Choose create (under this group) or map it to an existing ledger.")


# ============================================================================================ vouchers (D-34, D-35, D-36)

VOUCHER_TYPES: dict[str, str] = {
    "sales": "sales", "purchase": "purchase", "payment": "payment", "receipt": "receipt", "contra": "contra",
    "journal": "journal", "credit note": "credit_note", "debit note": "debit_note",
}
TALLY_TYPE_NAMES = {v: k.title() for k, v in VOUCHER_TYPES.items()}  # our code -> Tally's name, for the export


def voucher_type(tally_type: str) -> str | None:
    return VOUCHER_TYPES.get(name_key(tally_type))


def skip_reason(tally_type: str, is_cancelled: bool, is_optional: bool, is_postdated: bool) -> tuple[str, str] | None:
    """(rule id, reason) when the voucher is listed and not drafted, else None. Cancelled / optional / post-dated first (D-36)."""
    if is_cancelled:
        return "D-36", "Cancelled in Tally."
    if is_optional:
        return "D-36", "Optional voucher in Tally (not part of the books)."
    if is_postdated:
        return "D-36", "Post-dated voucher in Tally."
    if voucher_type(tally_type) is None:
        return "D-34", f"Voucher type '{tally_type}' is not imported; only Sales, Purchase, Payment, Receipt, Contra, Journal, Credit Note and Debit Note are."
    return None


@dataclass(frozen=True)
class SideLine:
    ledger_name: str
    debit: Decimal
    credit: Decimal


def to_lines(entries: Sequence[tuple[str, Decimal, bool]]) -> tuple[list[SideLine], list[str]]:
    """D-35. entries = (ledger name, amount as in the file, ISDEEMEDPOSITIVE). Tally writes a debit as Yes with a negative amount
    and a credit as No with a positive amount. An entry that contradicts itself is reported, never guessed; a zero entry is dropped
    and reported. Returns (lines, problems)."""
    lines: list[SideLine] = []
    problems: list[str] = []
    for name, amount, deemed_positive in entries:
        if amount == 0:
            problems.append(f"'{name}' has a zero amount in Tally; the line was left out.")
        elif deemed_positive and amount < 0:
            lines.append(SideLine(name, -amount, ZERO))
        elif not deemed_positive and amount > 0:
            lines.append(SideLine(name, ZERO, amount))
        else:
            problems.append(
                f"'{name}': Tally marks it as {'debit' if deemed_positive else 'credit'} (ISDEEMEDPOSITIVE) but the amount is "
                f"{'positive' if amount > 0 else 'negative'}; the side cannot be decided. Fix it in the queue.")
    return lines, problems


def source_refs(guid: str | None, tally_type: str, on: date, number: str | None, party: str | None, total_debit: Decimal) -> tuple[str, str]:
    """D-37. (reference stored on the queue item, fallback reference). The fallback is a hash of type + date + number + party +
    total; the stored reference is the GUID when the file has one, else the fallback."""
    raw = "|".join([name_key(tally_type), on.isoformat(), (number or "").strip().lower(), name_key(party or ""), f"{total_debit:.2f}"])
    fallback = "tvh:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return (guid.strip() if guid and guid.strip() else fallback), fallback
