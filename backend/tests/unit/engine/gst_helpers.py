"""Builders for the GST engine tests: literal rule objects (synthetic test data, NOT the law) and invoice inputs."""

from datetime import date
from decimal import Decimal as D

from app.engine.gst_invoice import InvoiceContext
from app.engine.gst_tax import RuleData
from app.engine.gst_types import (
    BlockedRule,
    GstRegistration,
    InvoiceIn,
    ItemLineIn,
    RateRule,
    RateSlab,
    RcmRule,
)

OLD_END = date(2025, 9, 21)
NEW_START = date(2025, 9, 22)
START = date(2017, 7, 1)
SRC = "test data"


def slab(rate, frm=START, to=None):
    return RateSlab(D(rate), False, frm, to, SRC, "pending")


SLABS = (
    slab("0"), slab("5"), slab("18"),
    slab("12", to=OLD_END), slab("28", to=OLD_END), slab("40", NEW_START),
)


def rule(key, prefix, rate, *, kind="hsn", supply="goods", treatment="taxable", cess="0", spec="0", uqc=None,
         frm=START, to=None):
    return RateRule(
        f"id-{key}", key, kind if prefix else "default", prefix, supply, treatment, D(rate), D(cess), D(spec),
        uqc, frm, to, SRC, "pending",
    )


RATE_RULES = (
    rule("r8471", "8471", "18"),
    rule("r3004_old", "3004", "12", to=OLD_END),
    rule("r3004_new", "3004", "5", frm=NEW_START),
    rule("r1701", "1701", "5"),
    rule("r8703_old", "8703", "28", cess="1", to=OLD_END),
    rule("r2402", "2402", "28", spec="2.50", uqc="NOS", to=OLD_END),
    rule("r0713", "0713", "0", treatment="exempt"),
    rule("r0401", "0401", "0", treatment="nil_rated"),
    rule("r2208", "2208", "0", treatment="non_gst"),
    rule("r9965", "9965", "5", kind="sac", supply="services"),
    rule("r9983", "9983", "18", kind="sac", supply="services"),
    rule("r8517", "8517", "18"),
    rule("r851712", "851712", "12", to=date(2020, 3, 31)),
    rule("r851712b", "851712", "18", frm=date(2020, 4, 1)),
    rule("r_bad", "7777", "7"),  # 7% is not a slab: G-11
    rule("default_services", None, "18", supply="services"),
)

RCM_RULES = (
    RcmRule("gta_services", "CGST 9(3)", "services", "GTA", "any", "9965", START, None, SRC, "pending"),
    RcmRule("sec_9_4", "CGST 9(4)", "services", "unregistered supplier", "unregistered_only", None, START, None, SRC, "pending"),
    RcmRule("import_of_services", "IGST 5(1)", "services", "import", "non_resident_only", None, START, None, SRC, "pending"),
    RcmRule("future_cat", "CGST 9(3)", "services", "future", "any", None, date(2030, 1, 1), None, SRC, "pending"),
)

BLOCKED = (
    BlockedRule("motor_vehicles", "CGST 17(5)(a)", "motor vehicles", True, "passenger transport use", START, None, SRC, "pending"),
    BlockedRule("food_beverages", "CGST 17(5)(b)(i)", "food", False, None, START, None, SRC, "pending"),
)

STATES = frozenset({"27", "29", "07", "96", "99"})
RULES = RuleData(RATE_RULES, SLABS, RCM_RULES, BLOCKED, STATES)

ROLES = {
    "output_cgst": "o-cgst", "output_sgst": "o-sgst", "output_igst": "o-igst", "output_cess": "o-cess",
    "input_cgst": "i-cgst", "input_sgst": "i-sgst", "input_igst": "i-igst", "input_cess": "i-cess",
    "rcm_cgst": "r-cgst", "rcm_sgst": "r-sgst", "rcm_igst": "r-igst", "rcm_cess": "r-cess",
    "round_off": "round",
}


def registration(state="27", kind="regular", roles=ROLES, frm=date(2017, 7, 1), to=None):
    return GstRegistration(
        "reg-1", f"{state}ABCDE1234F1Z0", state, kind, "monthly", "trader" if kind == "composition" else None,
        frm, to, True, None, dict(roles),
    )


def item(*, hsn="8471", qty="1", rate="1000.00", discount="0.00", ledger="goods", uqc="NOS", **kw):
    return ItemLineIn("Item", hsn, D(qty), D(rate), D(discount), ledger, uqc=uqc, **kw)


def invoice(items, *, pos="27", on=date(2026, 5, 10), category="b2b", kind="tax_invoice", gstin="27ABCDE1234F1Z0", **kw):
    return InvoiceIn("reg-1", kind, category, pos, on, tuple(items), counterparty_gstin=gstin, **kw)


def ctx(*, vtype="sales", on=date(2026, 5, 10), reg=None, cp_state="27", round_off=False, party="party", rules=RULES,
        gstin_check=None, party_state=None):
    return InvoiceContext(vtype, on, party, reg or registration(), cp_state, round_off, rules, gstin_check, party_state)
