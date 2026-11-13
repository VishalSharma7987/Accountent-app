"""Literal rule rows and masters for the TDS engine tests (values typed by hand, not read from the seed)."""

from datetime import date
from decimal import Decimal as D

from app.engine.tds_calc import TdsContext
from app.engine.tds_types import (
    Deductee,
    LowerDeductionCert,
    Nature,
    PriorPosition,
    RateRule,
    SectionRef,
    TdsLineIn,
)

FY = "FY2026-27"
Z = D("0.00")
NATURES = {
    "contractor": Nature("contractor", "tds", "Payment to contractor", "flat", "secondary_verified"),
    "technical_fees": Nature("technical_fees", "tds", "Technical fees", "flat", "secondary_verified"),
    "rent_land_building": Nature("rent_land_building", "tds", "Rent of land or building", "flat", "pending"),
    "purchase_of_goods": Nature("purchase_of_goods", "tds", "Purchase of goods", "flat", "secondary_verified"),
    "salary": Nature("salary", "tds", "Salary", "slab_manual", "secondary_verified"),
    "tcs_motor_vehicle": Nature("tcs_motor_vehicle", "tcs", "TCS motor vehicle", "flat", "pending"),
}


def sect(nature, act, section, frm, to=None, table=None, status="secondary_verified"):
    return SectionRef(nature, act, section, table, None, frm, to, f"src {nature} {act}", status)


A61, A25 = "it_act_1961", "it_act_2025"
END61, START25 = date(2026, 3, 31), date(2026, 4, 1)
SECTIONS = [
    sect("contractor", A61, "194C", date(2025, 4, 1), END61, status="pending"),
    sect("contractor", A25, "393(1)", START25, table="Sl.6(i)"),
    sect("technical_fees", A61, "194J(a)", date(2025, 4, 1), END61, status="pending"),
    sect("technical_fees", A25, "393(1)", START25, table="Sl.6(iii)(a)"),
    sect("rent_land_building", A61, "194I(b)", date(2025, 4, 1), END61, status="pending"),
    sect("rent_land_building", A25, "393(1)", START25, table="Sl.2(ii)(b)", status="pending"),
    sect("purchase_of_goods", A61, "194Q", date(2025, 4, 1), END61, status="pending"),
    sect("purchase_of_goods", A25, "393(1)", START25, table="Sl.8(ii)"),
    sect("salary", A61, "192", date(2025, 4, 1), END61),
    sect("salary", A25, "392", START25),
    sect("tcs_motor_vehicle", A61, "206C(1F)", date(2025, 4, 1), END61, status="pending"),
    sect("tcs_motor_vehicle", A25, "394", START25, status="pending"),
]


def rate(rid, nature, act, group, r, nopan, single, monthly, annual, mode, frm, to, status="secondary_verified"):
    f = lambda x: None if x is None else D(x)
    return RateRule(rid, nature, act, group, D(r), D(nopan), f(single), f(monthly), f(annual), mode, frm, to, f"src {rid}", status)


RATES = [
    # the 2025 rows carry deliberately different rates so that a wrong Act would show in every figure
    rate("c61-ih", "contractor", A61, "individual_huf", "1", "20", "30000", None, "100000", "whole_amount", date(2025, 4, 1), END61, "pending"),
    rate("c61-ot", "contractor", A61, "others", "2", "20", "30000", None, "100000", "whole_amount", date(2025, 4, 1), END61, "pending"),
    rate("c25-ih", "contractor", A25, "individual_huf", "1.5", "20", "30000", None, "100000", "whole_amount", START25, None),
    rate("c25-ot", "contractor", A25, "others", "2.5", "20", "30000", None, "100000", "whole_amount", START25, None),
    rate("tf25", "technical_fees", A25, "any", "2", "20", None, None, "50000", "whole_amount", START25, None),
    rate("rent25", "rent_land_building", A25, "any", "10", "20", None, "50000", None, "whole_amount", START25, None, "pending"),
    rate("q25", "purchase_of_goods", A25, "any", "0.1", "5", None, None, "5000000", "excess_only", START25, None),
    rate("mv25", "tcs_motor_vehicle", A25, "any", "1", "5", None, None, "1000000", "excess_only", START25, None, "pending"),
]

COMPANY = Deductee("co", "AAACS1234A", "valid", "company")
PERSON = Deductee("ind", "ABCPK1234A", "valid", "individual")
NO_PAN = Deductee("nopan", None, "missing", "company")
BAD_PAN = Deductee("badpan", "ABCDE1234F", "invalid", "company")
DEDUCTEES = {d.ledger_id: d for d in (COMPANY, PERSON, NO_PAN, BAD_PAN)}


def ctx(*, priors=None, certs=(), flags=None, kind="tds", fy=lambda d: FY, rates=RATES, deductees=DEDUCTEES):
    return TdsContext(kind, NATURES, deductees, rates, SECTIONS, {c.id: c for c in certs}, priors or {}, fy, flags or {})


def line(who, nature, amount, pay=None, credit=None, cert=None, manual=None):
    return TdsLineIn(who, nature, D(amount), credit, pay, cert, None if manual is None else D(manual))


def prior(who, nature, cumulative, tax="0", months=None):
    return {(who, nature, FY): PriorPosition(D(cumulative), D(tax), months or {})}


def cert(cid, who, rate_, max_amount, frm, to, nature=None, used="0", no="CERT-1"):
    return LowerDeductionCert(cid, who, no, nature, D(rate_), D(max_amount), frm, to, D(used))
