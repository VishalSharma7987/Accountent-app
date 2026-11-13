"""GST tax engine (Phase 3, step 3.2). Pure Python: no DB, web or AI imports (CLAUDE.md 2.6).

Every number comes from a rule object passed in (law is data, 2.5) and from Decimal arithmetic rounded ROUND_HALF_UP
through the one shared helper `engine.money.round_half_up`. The rule rows are picked by the supply date.

Rules: G-10 rate rule by date (longest prefix, default flagged), G-11 rate must be a slab in force, G-13 head by place
of supply, G-15 rounding, G-17 quantity / rate / discount, G-19 export / SEZ, G-20 reverse charge, G-21 treatments.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal, localcontext

from app.engine.gst_types import BlockedRule, RateRule, RateSlab, RcmRule, TaxLine
from app.engine.money import round_half_up

ZERO = Decimal("0.00")
ZERO_RATE = Decimal("0.0000")

LUT_CATEGORIES = frozenset({"export_without_payment", "sez_without_payment"})
ALWAYS_INTER = frozenset(
    {"sez_with_payment", "sez_without_payment", "export_with_payment", "export_without_payment", "import_of_service"}
)


class GstRuleError(Exception):
    """A GST rule failed for one item line (or, with item_line_no None, for the whole invoice)."""

    def __init__(self, rule_id: str, message: str, item_line_no: int | None = None):
        super().__init__(message)
        self.rule_id = rule_id
        self.message = message
        self.item_line_no = item_line_no


@dataclass(frozen=True)
class RuleData:
    """The rule rows the engine needs, already loaded by the caller (any date; the engine filters by date)."""

    rate_rules: tuple[RateRule, ...]
    slabs: tuple[RateSlab, ...]
    rcm_rules: tuple[RcmRule, ...]
    blocked_rules: tuple[BlockedRule, ...]
    state_codes: frozenset[str]  # codes valid as a place of supply on the date (incl. 96 for exports)


def fmt_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def in_force(row, on: date) -> bool:
    return row.effective_from <= on and (row.effective_to is None or on <= row.effective_to)


def supply_kind_of(hsn_sac: str) -> str:
    """SAC codes start with 99 (G-07); everything else is goods."""
    return "services" if hsn_sac.startswith("99") else "goods"


def head_for(supplier_state: str, place_of_supply: str, supply_category: str) -> str:
    """G-13 / G-19: 'intra' (CGST + SGST) when supplier state = place of supply, else 'inter' (IGST).
    Exports, SEZ supplies and imports of services are always IGST."""
    if supply_category in ALWAYS_INTER:
        return "inter"
    return "intra" if supplier_state == place_of_supply else "inter"


def pick_rate_rule(rules, hsn_sac: str, supply_kind: str, on: date) -> tuple[RateRule | None, bool]:
    """G-10: the longest code prefix in force on `on`; otherwise the single `default` rule of the supply kind
    (flag True); otherwise (None, False). Two different rules with the same longest prefix are refused."""
    live = [r for r in rules if r.supply_kind == supply_kind and in_force(r, on)]
    matches = [r for r in live if r.code_kind != "default" and r.code_prefix and hsn_sac.startswith(r.code_prefix)]
    if matches:
        longest = max(len(r.code_prefix) for r in matches)
        best = [r for r in matches if len(r.code_prefix) == longest]
        if len(best) > 1:
            keys = ", ".join(sorted(r.rule_key for r in best))
            raise GstRuleError(
                "G-10",
                f"More than one rate rule ({keys}) applies to {hsn_sac} on {fmt_date(on)}; the rule table needs correcting.",
            )
        return best[0], False
    defaults = [r for r in live if r.code_kind == "default"]
    if len(defaults) == 1:
        return defaults[0], True
    return None, False


def _places_ok(value: Decimal, places: int) -> bool:
    with localcontext() as ctx:
        ctx.prec = 60
        return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN) == value


def _check_number(n: int, label: str, value, places: int, *, positive: bool) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise GstRuleError("G-17", f"Item {n}: {label} must be a decimal number given as text, not {value!r}.", n)
    if value < 0 or (positive and value == 0):
        word = "greater than zero" if positive else "not negative"
        raise GstRuleError("G-17", f"Item {n}: {label} must be {word}.", n)
    if not _places_ok(value, places):
        raise GstRuleError("G-17", f"Item {n}: {label} {value} has more than {places} decimal places.", n)
    return value


def _rcm_rule(rules: RuleData, key: str, hsn_sac: str, supply_kind: str, supply_category: str, on: date, n: int) -> RcmRule:
    live = [r for r in rules.rcm_rules if r.category_key == key and in_force(r, on)]
    if not live:
        raise GstRuleError(
            "G-20", f"Item {n}: reverse charge category '{key}' is not in force on {fmt_date(on)} (or does not exist).", n
        )
    rule = live[0]
    if rule.supply_kind != supply_kind:
        raise GstRuleError("G-20", f"Item {n}: reverse charge category '{key}' is for {rule.supply_kind}, but {hsn_sac} is {supply_kind}.", n)
    if rule.hsn_sac_prefix and not hsn_sac.startswith(rule.hsn_sac_prefix):
        raise GstRuleError(
            "G-20", f"Item {n}: reverse charge category '{key}' applies to codes starting {rule.hsn_sac_prefix}, not {hsn_sac}.", n
        )
    if rule.supplier_condition == "unregistered_only" and supply_category != "unregistered_supplier":
        raise GstRuleError("G-20", f"Item {n}: reverse charge category '{key}' applies only to a supplier who is not registered.", n)
    if rule.supplier_condition == "non_resident_only" and supply_category != "import_of_service":
        raise GstRuleError("G-20", f"Item {n}: reverse charge category '{key}' applies only to an import of service.", n)
    return rule


def compute_item(
    item_line_no: int,
    item,
    rules: RuleData,
    on: date,
    head: str,
    *,
    charge_tax: bool,
    supply_category: str,
) -> TaxLine:
    """Tax of one item line (G-10 .. G-21). `head` is 'intra' or 'inter' (see head_for). `charge_tax` False means the
    document carries no tax (composition or unregistered supplier, composition client): all tax is zero, except on a
    reverse-charge line, where the recipient pays the tax. Raises GstRuleError."""
    n = item_line_no
    qty = _check_number(n, "quantity", item.quantity, 3, positive=True)
    price = _check_number(n, "rate", item.unit_rate, 2, positive=False)
    discount = _check_number(n, "discount", item.discount, 2, positive=False)
    gross = round_half_up(qty * price, 2)
    if discount > gross:
        raise GstRuleError("G-17", f"Item {n}: discount {discount} is more than the item value {gross}.", n)
    taxable = gross - discount

    kind = supply_kind_of(item.hsn_sac)
    try:
        rule, is_default = pick_rate_rule(rules.rate_rules, item.hsn_sac, kind, on)
    except GstRuleError as problem:
        raise GstRuleError(problem.rule_id, f"Item {n}: {problem.message}", n) from None
    if rule is None:
        raise GstRuleError(
            "G-10", f"Item {n}: no GST rate rule for {item.hsn_sac} ({kind}) on {fmt_date(on)}; add the rule before using this code.", n
        )

    rcm = False
    if item.rcm_category_key:
        _rcm_rule(rules, item.rcm_category_key, item.hsn_sac, kind, supply_category, on, n)
        rcm = True

    treatment, rate, cess_rate, spec_unit = rule.treatment, rule.rate, rule.cess_rate, rule.cess_specific_amount
    if treatment == "taxable" and not any(s.rate == rate and in_force(s, on) for s in rules.slabs):
        raise GstRuleError(
            "G-11", f"Item {n}: rate {rate}% of rule '{rule.rule_key}' is not a GST slab in force on {fmt_date(on)}.", n
        )
    if treatment == "taxable" and supply_category in LUT_CATEGORIES:
        treatment, rate, cess_rate, spec_unit = "zero_rated", Decimal(0), Decimal(0), Decimal(0)
    if not (charge_tax or rcm):
        rate, cess_rate, spec_unit = Decimal(0), Decimal(0), Decimal(0)

    cgst = sgst = igst = cess = ZERO
    spec_total = ZERO
    if treatment == "taxable":
        if head == "intra":
            cgst = sgst = round_half_up(taxable * rate / 200, 2)
        else:
            igst = round_half_up(taxable * rate / 100, 2)
        if spec_unit > 0:
            if item.uqc != rule.cess_uqc:
                raise GstRuleError(
                    "G-15",
                    f"Item {n}: specific cess is per {rule.cess_uqc}, but the item's unit is {item.uqc or 'not given'}.", n,
                )
            spec_total = round_half_up(qty * spec_unit, 2)
        cess = round_half_up(taxable * cess_rate / 100, 2) + spec_total
    else:
        rate = cess_rate = Decimal(0)

    return TaxLine(
        item_line_no=n, gross_amount=gross, discount=discount, taxable_value=taxable, treatment=treatment,
        gst_rate=Decimal(rate).quantize(Decimal("0.0001")), cess_rate=Decimal(cess_rate).quantize(Decimal("0.0001")),
        cgst=cgst, sgst=sgst, igst=igst, cess=cess, rate_rule_id=rule.id, rate_is_default=is_default, rcm=rcm,
        cess_specific_amount=spec_total,
    )
