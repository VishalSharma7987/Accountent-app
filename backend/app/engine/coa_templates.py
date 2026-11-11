"""Default chart of accounts (ledgers) for a new client, by entity type and business type.

Pure data: group codes are the seeded system groups. The order is fixed so that results are reproducible.
Reviewed for Indian practice (docs/DECISIONS.md, step 1.4).
"""

from collections.abc import Sequence
from dataclasses import dataclass

ENTITY_TYPES = ("proprietorship", "partnership", "llp", "company")
BUSINESS_TYPES = ("trading", "service", "manufacturing")

_EXPENSE_LEDGERS = (
    "Rent", "Salary", "Electricity", "Telephone & Internet", "Printing & Stationery",
    "Travelling", "Repairs & Maintenance", "Bank Charges", "Office Expenses",
)


@dataclass(frozen=True)
class TemplateLedger:
    name: str
    group_code: str


def _clean_partners(partners: Sequence[str] | None) -> list[str]:
    names = [(p or "").strip() for p in (partners or [])]
    if not names:
        raise ValueError("A partnership or LLP needs at least one partner name.")
    if any(not n for n in names):
        raise ValueError("Every partner needs a name (a partner name is blank).")
    seen: set[str] = set()
    for n in names:
        if n.lower() in seen:
            raise ValueError(f"Two partners have the same name: '{n}'.")
        seen.add(n.lower())
    return names


def _entity_ledgers(entity_type: str, proprietor_name: str | None, partners: Sequence[str] | None) -> list[TemplateLedger]:
    if entity_type == "proprietorship":
        owner = (proprietor_name or "").strip()
        if not owner:
            raise ValueError("A proprietorship needs the proprietor's name for the Capital account.")
        return [
            TemplateLedger(f"{owner} Capital A/c", "capital_account"),
            TemplateLedger("Drawings A/c", "capital_account"),
        ]
    if entity_type in ("partnership", "llp"):
        out: list[TemplateLedger] = []
        for name in _clean_partners(partners):
            out.append(TemplateLedger(f"{name} Capital A/c", "capital_account"))
            out.append(TemplateLedger(f"{name} Current A/c", "capital_account"))
        return out
    return [  # company
        TemplateLedger("Share Capital", "capital_account"),
        TemplateLedger("Surplus in Profit & Loss", "reserves_surplus"),
    ]


def _business_ledgers(business_type: str) -> list[TemplateLedger]:
    trading = [
        TemplateLedger("Purchases", "purchase_accounts"),
        TemplateLedger("Sales", "sales_accounts"),
        TemplateLedger("Purchase Returns", "purchase_accounts"),
        TemplateLedger("Sales Returns", "sales_accounts"),
        TemplateLedger("Opening Stock", "stock_in_hand"),
    ]
    if business_type == "trading":
        return trading
    if business_type == "service":
        return [TemplateLedger("Service Income", "sales_accounts")]
    return trading + [TemplateLedger("Raw Material Purchases", "purchase_accounts")]  # manufacturing, for now


def default_ledgers(
    entity_type: str,
    business_type: str,
    *,
    proprietor_name: str | None = None,
    partners: Sequence[str] | None = None,
) -> list[TemplateLedger]:
    """The ledgers every new client starts with: common, entity-specific, business-specific, common expenses."""
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"Unknown entity type {entity_type!r}; use one of {', '.join(ENTITY_TYPES)}.")
    if business_type not in BUSINESS_TYPES:
        raise ValueError(f"Unknown business type {business_type!r}; use one of {', '.join(BUSINESS_TYPES)}.")
    return (
        [TemplateLedger("Cash", "cash_in_hand"), TemplateLedger("Suspense A/c", "suspense")]
        + _entity_ledgers(entity_type, proprietor_name, partners)
        + _business_ledgers(business_type)
        + [TemplateLedger(name, "indirect_expenses") for name in _EXPENSE_LEDGERS]
    )
