"""Default ledgers for a new client, by entity type and business type (Step 1.4). Expected lists typed literally."""

import pytest
from chart_fixture import EXPECTED_GROUPS

from app.engine.coa_templates import BUSINESS_TYPES, ENTITY_TYPES, TemplateLedger, default_ledgers

SEEDED_GROUP_CODES = {code for code, *_ in EXPECTED_GROUPS}

COMMON_FIRST = [("Cash", "cash_in_hand"), ("Suspense A/c", "suspense")]
EXPENSES = [(name, "indirect_expenses") for name in (
    "Rent", "Salary", "Electricity", "Telephone & Internet", "Printing & Stationery",
    "Travelling", "Repairs & Maintenance", "Bank Charges", "Office Expenses",
)]
TRADING = [
    ("Purchases", "purchase_accounts"), ("Sales", "sales_accounts"), ("Purchase Returns", "purchase_accounts"),
    ("Sales Returns", "sales_accounts"), ("Opening Stock", "stock_in_hand"),
]


def pairs(ledgers):
    return [(x.name, x.group_code) for x in ledgers]


def test_proprietorship_trading_gets_the_full_list_in_a_fixed_order():
    result = default_ledgers("proprietorship", "trading", proprietor_name="Ramesh Kumar")
    assert pairs(result) == (
        COMMON_FIRST
        + [("Ramesh Kumar Capital A/c", "capital_account"), ("Drawings A/c", "capital_account")]
        + TRADING
        + EXPENSES
    )
    assert all(isinstance(x, TemplateLedger) for x in result)


def test_proprietorship_service_has_service_income_instead_of_trading_ledgers():
    result = default_ledgers("proprietorship", "service", proprietor_name="Sita Devi")
    assert pairs(result) == (
        COMMON_FIRST
        + [("Sita Devi Capital A/c", "capital_account"), ("Drawings A/c", "capital_account")]
        + [("Service Income", "sales_accounts")]
        + EXPENSES
    )


def test_partnership_gets_a_capital_and_a_current_account_for_every_partner():
    result = default_ledgers("partnership", "trading", partners=["Anil Shah", "Bina Shah"])
    assert pairs(result)[2:8] == [
        ("Anil Shah Capital A/c", "capital_account"), ("Anil Shah Current A/c", "capital_account"),
        ("Bina Shah Capital A/c", "capital_account"), ("Bina Shah Current A/c", "capital_account"),
        ("Purchases", "purchase_accounts"), ("Sales", "sales_accounts"),
    ]
    assert "Drawings A/c" not in [x.name for x in result]


def test_llp_is_set_up_like_a_partnership():
    llp = default_ledgers("llp", "service", partners=["P One", "P Two"])
    firm = default_ledgers("partnership", "service", partners=["P One", "P Two"])
    assert llp == firm


def test_company_gets_share_capital_and_surplus_in_reserves():
    result = default_ledgers("company", "service")
    assert pairs(result) == (
        COMMON_FIRST
        + [("Share Capital", "capital_account"), ("Surplus in Profit & Loss", "reserves_surplus")]
        + [("Service Income", "sales_accounts")]
        + EXPENSES
    )


def test_manufacturing_is_trading_plus_raw_material_purchases_for_now():
    result = default_ledgers("company", "manufacturing")
    assert pairs(result) == (
        COMMON_FIRST
        + [("Share Capital", "capital_account"), ("Surplus in Profit & Loss", "reserves_surplus")]
        + TRADING
        + [("Raw Material Purchases", "purchase_accounts")]
        + EXPENSES
    )


@pytest.mark.parametrize("entity", ENTITY_TYPES)
@pytest.mark.parametrize("business", BUSINESS_TYPES)
def test_every_combination_gives_unique_names_and_only_seeded_groups(entity, business):
    result = default_ledgers(entity, business, proprietor_name="Owner One", partners=["Pa One", "Pa Two"])
    names = [x.name.lower() for x in result]
    assert len(names) == len(set(names))
    assert {x.group_code for x in result} <= SEEDED_GROUP_CODES
    assert names[:2] == ["cash", "suspense a/c"]


def test_entity_and_business_types_are_the_ones_the_database_accepts():
    assert ENTITY_TYPES == ("proprietorship", "partnership", "llp", "company")
    assert BUSINESS_TYPES == ("trading", "service", "manufacturing")


def test_names_are_trimmed():
    result = default_ledgers("proprietorship", "service", proprietor_name="  Ramesh Kumar  ")
    assert result[2].name == "Ramesh Kumar Capital A/c"


@pytest.mark.parametrize("name", [None, "", "   "])
def test_proprietorship_needs_the_proprietors_name(name):
    with pytest.raises(ValueError, match="proprietor"):
        default_ledgers("proprietorship", "trading", proprietor_name=name)


@pytest.mark.parametrize("entity", ["partnership", "llp"])
def test_partnership_and_llp_need_at_least_one_partner(entity):
    with pytest.raises(ValueError, match="partner"):
        default_ledgers(entity, "trading", partners=[])


def test_partner_names_must_be_filled_and_different():
    with pytest.raises(ValueError, match="partner"):
        default_ledgers("partnership", "trading", partners=["Anil", "  "])
    with pytest.raises(ValueError, match="same name"):
        default_ledgers("partnership", "trading", partners=["Anil Shah", "anil shah"])


def test_unknown_types_are_rejected():
    with pytest.raises(ValueError, match="entity type"):
        default_ledgers("trust", "trading")
    with pytest.raises(ValueError, match="business type"):
        default_ledgers("company", "farming")
