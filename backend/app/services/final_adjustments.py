"""Phase 6 package A: ledger roles, `setup-ledgers`, partners and their deed terms, and the adjustment helpers.

Every accounting effect is a DRAFT Journal created through `services/vouchers.py` (V-01..V-14 apply; it is approved and posted like any
voucher). The amounts come from `engine/final_adjustments.py`; nothing here computes one. Services never commit and check before the
first write; every change is audit-logged.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_final_adjustments as frepo
from app.engine import final_adjustments as engine
from app.engine.final_types import (
    AdjustmentInput,
    AdjustmentResult,
    AdjustmentType,
    EntityType,
    Finding,
)
from app.engine.models import ValidationError, VoucherDraft, VoucherLine
from app.engine.money import format_inr, round_half_up
from app.services import audit, client_setup, final_hooks, reports, vouchers
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor

PARTNER_ENTITIES = ("partnership", "llp")
ROLE_ENTITY_GATE = {   # role -> entities that may use it (F-09)
    "interest_on_capital": PARTNER_ENTITIES, "interest_on_drawings": PARTNER_ENTITIES, "partner_remuneration": PARTNER_ENTITIES,
    "surplus_in_pl": ("company",),
}
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class AdjustmentRequest:
    """The accountant's input (docs/PHASE6_API_CONTRACT.md `Adjustment`) plus the two service-only fields."""

    adj_type: str
    as_on_date: date
    basis_note: str
    amount: Decimal | None = None
    debit_ledger_id: Any = None
    credit_ledger_id: Any = None
    party_ledger_id: Any = None
    rate_percent: Decimal | None = None
    partner_id: Any = None
    months: int | None = None
    auto_reverse_on: date | None = None
    duplicate_reason: str | None = None


def _fmt(on: date) -> str:
    return on.strftime("%d-%m-%Y")


def _rule_error(rule_id: str, message: str) -> VoucherRuleError:
    return VoucherRuleError([ValidationError(rule_id, message)])


def _raise_findings(findings: list[Finding]) -> None:
    raise VoucherRuleError([ValidationError(f.rule_id, f.message) for f in findings])


def _require_client(conn: Connection, client_id: Any) -> str:
    entity = frepo.client_entity(conn, client_id)
    if entity is None:
        raise ServiceError("not_found", "Client not found.")
    return entity


def _require_year(conn: Connection, client_id: Any, fy_id: Any) -> repo.FinancialYearRow:
    year = repo.get_financial_year(conn, client_id, fy_id)
    if year is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return year


# ============================================================================================ ledger roles


def get_ledger_roles(conn: Connection, client_id: Any) -> list[dict]:
    _require_client(conn, client_id)
    return [{"role": role, "ledger_id": lid, "ledger_name": name} for role, lid, name in frepo.role_rows(conn, client_id)]


def _check_role_fit(role: str, info: engine.LedgerInfo, entity: str) -> None:
    gate = ROLE_ENTITY_GATE.get(role)
    if gate is not None and entity not in gate:
        raise _rule_error("F-09", f"The role '{role}' is only for a {' or '.join(gate)} client; this client is a {entity}.")
    if info.group_code not in engine.ROLE_GROUPS[role]:
        allowed = ", ".join(sorted(g.replace("_", " ") for g in engine.ROLE_GROUPS[role]))
        raise _rule_error("F-02", f"'{info.name}' is under {info.group_code.replace('_', ' ')}; the role '{role}' needs a ledger in: {allowed}.")


def set_ledger_role(conn: Connection, client_id: Any, role: str, ledger_id: Any, *, actor: str) -> None:
    actor = require_actor(actor)
    entity = _require_client(conn, client_id)
    if role not in engine.ROLE_GROUPS:
        raise ServiceError("invalid_role", f"Unknown ledger role '{role}'.")
    infos = frepo.ledger_infos(conn, client_id)
    info = infos.get(ledger_id)
    if info is None:
        raise ServiceError("not_found", "Ledger not found for this client.")
    _check_role_fit(role, info, entity)
    other = frepo.role_of_ledger(conn, client_id, ledger_id)
    if other is not None and other != role:
        raise ServiceError("role_conflict", f"'{info.name}' already has the role '{other}'; one ledger cannot play two roles.")
    old = {r: str(lid) for r, lid, _ in frepo.role_rows(conn, client_id)}.get(role)
    frepo.set_role(conn, client_id, role, ledger_id, actor)
    audit.log(conn, AuditEntry(client_id, actor, "update" if old else "create", "final_ledger_role", client_id,
                               old={"role": role, "ledger_id": old} if old else None, new={"role": role, "ledger_id": str(ledger_id)}))


def setup_ledgers(conn: Connection, client_id: Any, financial_year_id: Any, *, actor: str) -> list[dict]:
    """Create (if absent) the system ledgers and set their roles. Idempotent; a name clash or an ambiguous existing ledger is an error,
    never a silent pick. Everything is planned first so a refusal writes nothing."""
    actor = require_actor(actor)
    entity = _require_client(conn, client_id)
    _require_year(conn, client_id, financial_year_id)
    infos = frepo.ledger_infos(conn, client_id)
    by_name = {i.name.lower(): i for i in infos.values()}
    held = {r: (lid, name) for r, lid, name in frepo.role_rows(conn, client_id)}
    used = {lid for lid, _ in held.values()}
    roles = list(engine.SETUP_ROLES_ALL) + (list(engine.SETUP_ROLES_PARTNERS) if entity in PARTNER_ENTITIES else [])

    plan: list[tuple[str, Any, str, str | None]] = []   # (role, existing ledger id | None, name, group to create in | None)
    for role in roles:
        if role in held:
            continue
        name, group = engine.ROLE_DEFAULTS[role]
        if role == "stock_ledger":
            candidates = [(lid, n) for lid, n in frepo.ledgers_in_group(conn, client_id, "stock_in_hand") if lid not in used]
            if len(candidates) == 1:
                plan.append((role, candidates[0][0], candidates[0][1], None))
                used.add(candidates[0][0])
                continue
            if len(candidates) > 1:
                raise ServiceError("ledger_role_missing", "The client has several Stock-in-hand ledgers; choose which one is the stock ledger "
                                   "with PUT /final/ledger-roles/stock_ledger (nothing is guessed).")
        existing = by_name.get(name.lower())
        if existing is not None:
            if existing.group_code not in engine.ROLE_GROUPS[role] or existing.ledger_id in used:
                raise ServiceError("role_conflict", f"A ledger named '{name}' already exists but cannot be used for the role '{role}' "
                                   f"(it is under {existing.group_code.replace('_', ' ')} or already has a role). Set the role by hand.")
            plan.append((role, existing.ledger_id, existing.name, None))
            used.add(existing.ledger_id)
        else:
            plan.append((role, None, name, group))
    if entity == "company" and "surplus_in_pl" not in held:
        taken = used | {p[1] for p in plan if p[1]}
        candidates = [(lid, n) for lid, n in frepo.ledgers_in_group(conn, client_id, "reserves_surplus") if lid not in taken]
        if len(candidates) != 1:
            raise ServiceError("ledger_role_missing", "Could not find the company's single Surplus ledger in Reserves & Surplus; set the role "
                               "surplus_in_pl with PUT /final/ledger-roles/surplus_in_pl.")
        plan.append(("surplus_in_pl", candidates[0][0], candidates[0][1], None))

    done = {r: {"role": r, "ledger_id": lid, "ledger_name": name, "created": False} for r, (lid, name) in held.items()}
    for role, existing_id, name, group in plan:
        created = existing_id is None
        ledger_id = client_setup.add_ledger(conn, client_id, name, group, actor=actor) if created else existing_id
        frepo.set_role(conn, client_id, role, ledger_id, actor)
        audit.log(conn, AuditEntry(client_id, actor, "create", "final_ledger_role", client_id, new={"role": role, "ledger_id": str(ledger_id),
                                                                                                     "created_ledger": created}))
        done[role] = {"role": role, "ledger_id": ledger_id, "ledger_name": name, "created": created}
    order = list(engine.SETUP_ROLES_ALL) + list(engine.SETUP_ROLES_PARTNERS) + ["surplus_in_pl"]
    return [done[r] for r in order if r in done]


# ============================================================================================ partners


def _require_partner_entity(entity: str) -> None:
    if entity not in PARTNER_ENTITIES:
        raise ServiceError("invalid_entity", f"Partners exist only for a partnership or LLP; this client is a {entity}.")


def _check_partner_ledger(infos: dict, ledger_id: Any, what: str) -> None:
    info = infos.get(ledger_id)
    if info is None:
        raise ServiceError("not_found", f"The {what} ledger was not found for this client.")
    if info.group_code != "capital_account":
        raise _rule_error("F-02", f"'{info.name}' is under {info.group_code.replace('_', ' ')}; a partner's {what} ledger must be under Capital Account.")


def _partner_json(p: dict) -> dict:
    return {k: (str(v) if k.endswith("_id") and v is not None else v) for k, v in p.items()}


def list_partners(conn: Connection, client_id: Any) -> list[dict]:
    _require_client(conn, client_id)
    return frepo.list_partners(conn, client_id)


def create_partner(conn: Connection, client_id: Any, name: str, capital_ledger_id: Any, current_ledger_id: Any = None, *, actor: str) -> Any:
    actor = require_actor(actor)
    _require_partner_entity(_require_client(conn, client_id))
    name = (name or "").strip()
    if not name:
        raise ServiceError("invalid_partner", "The partner's name is required.")
    infos = frepo.ledger_infos(conn, client_id)
    _check_partner_ledger(infos, capital_ledger_id, "capital")
    if current_ledger_id is not None:
        _check_partner_ledger(infos, current_ledger_id, "current")
    _check_partner_unique(conn, client_id, name, capital_ledger_id, current_ledger_id, None)
    partner_id = uuid.uuid4()
    frepo.insert_partner(conn, partner_id, client_id, name, capital_ledger_id, current_ledger_id)
    audit.log(conn, AuditEntry(client_id, actor, "create", "partner", partner_id, new=_partner_json(
        {"name": name, "capital_ledger_id": capital_ledger_id, "current_ledger_id": current_ledger_id, "is_active": True})))
    return partner_id


def _check_partner_unique(conn, client_id, name, capital_id, current_id, except_id) -> None:
    if frepo.partner_name_taken(conn, client_id, name, except_id):
        raise ServiceError("partner_exists", f"A partner named '{name}' already exists for this client.")
    if capital_id == current_id:
        raise ServiceError("invalid_partner", "The capital and current ledgers of a partner must be different.")
    for ledger_id in (capital_id, current_id):
        if ledger_id is not None and frepo.ledger_used_by_partner(conn, client_id, ledger_id, except_id):
            raise ServiceError("partner_exists", "That ledger already belongs to another partner.")


def update_partner(conn: Connection, client_id: Any, partner_id: Any, changes: dict, *, actor: str) -> None:
    """`changes` holds only the fields the caller sent: name, capital_ledger_id, current_ledger_id (may be None), is_active."""
    actor = require_actor(actor)
    _require_partner_entity(_require_client(conn, client_id))
    old = frepo.get_partner(conn, client_id, partner_id)
    if old is None:
        raise ServiceError("not_found", "Partner not found.")
    new = {**old, **{k: v for k, v in changes.items() if k in old and k != "id"}}
    new["name"] = (new["name"] or "").strip()
    if not new["name"]:
        raise ServiceError("invalid_partner", "The partner's name is required.")
    infos = frepo.ledger_infos(conn, client_id)
    if new["capital_ledger_id"] != old["capital_ledger_id"]:
        _check_partner_ledger(infos, new["capital_ledger_id"], "capital")
    if new["current_ledger_id"] != old["current_ledger_id"] and new["current_ledger_id"] is not None:
        _check_partner_ledger(infos, new["current_ledger_id"], "current")
    _check_partner_unique(conn, client_id, new["name"], new["capital_ledger_id"], new["current_ledger_id"], partner_id)
    ledgers_changed = (new["capital_ledger_id"], new["current_ledger_id"]) != (old["capital_ledger_id"], old["current_ledger_id"])
    if ledgers_changed and (frepo.partner_has_terms(conn, partner_id) or frepo.partner_has_adjustments(conn, client_id, partner_id)):
        raise ServiceError("partner_in_use", "This partner already has deed terms or adjustments; the ledgers cannot be changed. "
                           "Mark the partner inactive and add a new one if the ledgers must change.")
    if new == old:
        return
    frepo.update_partner(conn, partner_id, new["name"], new["capital_ledger_id"], new["current_ledger_id"], new["is_active"])
    audit.log(conn, AuditEntry(client_id, actor, "update", "partner", partner_id, old=_partner_json(old), new=_partner_json(new)))


# ============================================================================================ partner deed terms


def _terms_json(rows: list[dict]) -> list[dict]:
    return [{k: (str(v) if v is not None and not isinstance(v, str) else v) for k, v in r.items()} for r in rows]


def get_terms(conn: Connection, client_id: Any, financial_year_id: Any) -> dict:
    _require_client(conn, client_id)
    _require_year(conn, client_id, financial_year_id)
    terms = {t["partner_id"]: t for t in frepo.terms_for_year(conn, client_id, financial_year_id)}
    rows, total = [], Decimal("0.0000")
    for p in frepo.list_partners(conn, client_id):
        t = terms.get(p["id"])
        if t is None and not p["is_active"]:
            continue
        t = t or {"profit_share_percent": Decimal("0.0000"), "interest_on_capital_rate": None, "interest_on_drawings_rate": None,
                  "remuneration_annual": None, "deed_reference": None}
        total += Decimal(t["profit_share_percent"])
        rows.append({"partner_id": p["id"], "name": p["name"], **{k: v for k, v in t.items() if k != "partner_id"}})
    return {"rows": rows, "share_total": total, "share_ok": total == Decimal(100)}


def _opt(value: Any, places: int, what: str) -> Decimal | None:
    if value is None:
        return None
    value = Decimal(value)
    if value != round_half_up(value, places):
        raise ServiceError("invalid_terms", f"{what} has more than {places} decimal places; it is rejected, not rounded.")
    if value < 0 or (places == 4 and value > 100):
        raise ServiceError("invalid_terms", f"{what} is out of range.")
    return value.quantize(Decimal(1).scaleb(-places))


def put_terms(conn: Connection, client_id: Any, financial_year_id: Any, rows: list[dict], *, actor: str) -> None:
    actor = require_actor(actor)
    _require_partner_entity(_require_client(conn, client_id))
    _require_year(conn, client_id, financial_year_id)
    if final_hooks.year_is_closed(conn, client_id, financial_year_id):
        raise ServiceError("year_closed", "This financial year is closed; partner terms are frozen. Reopen the year to change them.")
    partners = {p["id"]: p for p in frepo.list_partners(conn, client_id)}
    clean, seen, total = [], set(), Decimal("0.0000")
    for r in rows:
        pid = r["partner_id"]
        p = partners.get(pid)
        if p is None:
            raise ServiceError("not_found", "A partner in the list was not found for this client.")
        if pid in seen:
            raise ServiceError("invalid_terms", f"Partner '{p['name']}' appears twice.")
        seen.add(pid)
        if not p["is_active"]:
            raise ServiceError("invalid_terms", f"Partner '{p['name']}' is inactive.")
        share = _opt(r["profit_share_percent"], 4, f"The profit share of '{p['name']}'")
        if share is None:
            raise ServiceError("invalid_terms", f"The profit share of '{p['name']}' is required.")
        item = {
            "partner_id": pid, "profit_share_percent": share,
            "interest_on_capital_rate": _opt(r.get("interest_on_capital_rate"), 4, f"The interest on capital rate of '{p['name']}'"),
            "interest_on_drawings_rate": _opt(r.get("interest_on_drawings_rate"), 4, f"The interest on drawings rate of '{p['name']}'"),
            "remuneration_annual": _opt(r.get("remuneration_annual"), 2, f"The remuneration of '{p['name']}'"),
            "deed_reference": (r.get("deed_reference") or "").strip() or None,
        }
        if item["deed_reference"] is None and any(item[k] is not None for k in ("interest_on_capital_rate", "interest_on_drawings_rate", "remuneration_annual")):
            raise ServiceError("invalid_terms", f"A deed reference is required for '{p['name']}': interest rates and remuneration are deed values.")
        total += share
        clean.append(item)
    if total != Decimal(100):
        raise _rule_error("F-62", f"The profit shares add up to {total:.4f}; they must add up to exactly 100.0000.")
    old = frepo.terms_for_year(conn, client_id, financial_year_id)
    frepo.replace_terms(conn, client_id, financial_year_id, clean, actor)
    audit.log(conn, AuditEntry(client_id, actor, "update", "partner_fy_terms", financial_year_id,
                               old={"rows": _terms_json(old)}, new={"rows": _terms_json(clean)}))


# ============================================================================================ adjustments


def _load_context(conn: Connection, client_id: Any, entity: str, year: repo.FinancialYearRow, req: AdjustmentRequest) -> engine.AdjustmentContext:
    ledgers = frepo.ledger_infos(conn, client_id)
    roles = {r: lid for r, lid, _ in frepo.role_rows(conn, client_id)}
    closing: dict[Any, Decimal] = {}
    debtors: Decimal | None = None
    adj_type = AdjustmentType(req.adj_type)
    if adj_type in (AdjustmentType.BAD_DEBT, AdjustmentType.PROVISION_DOUBTFUL_DEBTS):
        trial = reports.trial_balance(conn, client_id, req.as_on_date)
        closing = {row.ledger_id: row.debit - row.credit for section in trial.sections for row in section.rows}
        debtors = sum((v for lid, v in closing.items() if ledgers[lid].group_code == "sundry_debtors" and v > 0), ZERO)
    partner = terms = None
    capital_opening, capital_moves, drawings = ZERO, (), ()
    if adj_type in engine.PARTNER_TYPES and req.partner_id is not None:
        p = frepo.get_partner(conn, client_id, req.partner_id)
        if p is None:
            raise ServiceError("not_found", "Partner not found.")
        if not p["is_active"]:
            raise _rule_error("F-07", f"Partner '{p['name']}' is inactive.")
        partner = engine.PartnerInfo(p["id"], p["name"], p["capital_ledger_id"], p["current_ledger_id"] or p["capital_ledger_id"])
        t = frepo.terms_of_partner(conn, client_id, year.id, p["id"])
        if t is not None:
            terms = engine.PartnerTermsIn(_dec(t["interest_on_capital_rate"], 4), _dec(t["interest_on_drawings_rate"], 4),
                                          _dec(t["remuneration_annual"], 2), t["deed_reference"])
        if adj_type is AdjustmentType.INTEREST_ON_CAPITAL:
            capital_opening = frepo.opening_signed(conn, client_id, year.id, p["capital_ledger_id"])
            capital_moves = tuple((d, dr - cr) for d, dr, cr in frepo.posted_movements(conn, client_id, year.id, p["capital_ledger_id"]))
        if adj_type is AdjustmentType.INTEREST_ON_DRAWINGS and req.party_ledger_id in ledgers:
            drawings = tuple((d, dr) for d, dr, _ in frepo.posted_movements(conn, client_id, year.id, req.party_ledger_id) if dr > 0)
    return engine.AdjustmentContext(
        entity_type=EntityType(entity), fy_start=year.start_date, fy_end=year.end_date, ledgers=ledgers, roles=roles,
        closing_balances=closing, debtors_closing=debtors, partner=partner, terms=terms, capital_opening=capital_opening,
        capital_movements=capital_moves, drawings=drawings,
    )


def _dec(value: Any, places: int) -> Decimal | None:
    return None if value is None else Decimal(value).quantize(Decimal(1).scaleb(-places))


def _prepare(conn: Connection, client_id: Any, req: AdjustmentRequest) -> tuple[repo.FinancialYearRow, AdjustmentResult, engine.AdjustmentContext]:
    entity = _require_client(conn, client_id)
    try:
        adj_type = AdjustmentType(req.adj_type)
    except ValueError:
        raise ServiceError("invalid_adjustment", f"Unknown adjustment type '{req.adj_type}'.") from None
    year = repo.financial_year_for_date(conn, client_id, req.as_on_date)
    if year is None:
        raise _rule_error("F-01", f"No financial year of this client contains {_fmt(req.as_on_date)} (V-06).")
    ctx = _load_context(conn, client_id, entity, year, req)
    inp = AdjustmentInput(adj_type, req.as_on_date, req.basis_note, req.amount, req.debit_ledger_id, req.credit_ledger_id, req.party_ledger_id,
                          req.rate_percent, req.partner_id, req.auto_reverse_on)
    built = engine.build_adjustment(inp, ctx, months=req.months)
    if isinstance(built, list):
        _raise_findings(built)
    return year, built, ctx  # type: ignore[return-value]


def _pair(params: dict) -> frozenset:
    return frozenset((str(params.get("debit_ledger_id")), str(params.get("credit_ledger_id"))))


def _duplicates(conn: Connection, client_id: Any, year: repo.FinancialYearRow, result: AdjustmentResult) -> list[dict]:
    """F-10: same type + same ledger pair in the year while an earlier adjustment's voucher is not reversed."""
    mine = _pair(result.params)
    return [a for a in frepo.list_adjustments(conn, client_id, year.id, result.adj_type.value)
            if a["voucher_status"] != "reversed" and _pair(a["params"]) == mine]


def _lines_out(result: AdjustmentResult, ledgers: dict) -> list[dict]:
    return [{"ledger_id": x.ledger_id, "ledger_name": ledgers[x.ledger_id].name, "debit": x.debit, "credit": x.credit} for x in result.lines]


def _warnings(conn: Connection, client_id: Any, year: repo.FinancialYearRow, result: AdjustmentResult, duplicates: list[dict]) -> list[dict]:
    out = []
    if duplicates:
        out.append({"rule_id": "F-10", "severity": "warning", "message": f"A {result.adj_type.value.replace('_', ' ')} for the same ledgers "
                    f"already exists in this year ({format_inr(duplicates[0]['amount'])}); give a reason to save another."})
    if result.adj_type is AdjustmentType.PROVISION_DOUBTFUL_DEBTS and frepo.unposted_adjustment_count(conn, client_id, year.id, "bad_debt"):
        out.append({"rule_id": "F-05", "severity": "warning", "message": "Bad-debt adjustments of this year are still draft or approved; "
                    "post them first or the provision is computed on debtors before those write-offs."})
    return out


def preview(conn: Connection, client_id: Any, req: AdjustmentRequest) -> dict:
    year, result, ctx = _prepare(conn, client_id, req)
    return {"amount": result.amount, "lines": _lines_out(result, ctx.ledgers), "narration": result.narration, "params": result.params,
            "findings": _warnings(conn, client_id, year, result, _duplicates(conn, client_id, year, result))}


def _journal(client_id: Any, on: date, narration: str, lines) -> VoucherDraft:
    return VoucherDraft(client_id, "journal", on, narration, None, None, tuple(VoucherLine(x.ledger_id, x.debit, x.credit) for x in lines))


def create(conn: Connection, client_id: Any, req: AdjustmentRequest, *, actor: str) -> dict:
    actor = require_actor(actor)
    year, result, ctx = _prepare(conn, client_id, req)
    duplicates = _duplicates(conn, client_id, year, result)
    reason = (req.duplicate_reason or "").strip()
    if duplicates and not reason:
        raise ServiceError("adjustment_duplicate", f"F-10: a {result.adj_type.value.replace('_', ' ')} for the same two ledgers already exists in "
                           f"this financial year ({format_inr(duplicates[0]['amount'])} dated {_fmt(duplicates[0]['as_on_date'])}). "
                           "Give a reason to save another one.")
    params = dict(result.params)
    if duplicates:
        params["duplicate_reason"] = reason
    main = _journal(client_id, req.as_on_date, result.narration, result.lines)
    reverse = None
    if req.auto_reverse_on is not None:
        if repo.financial_year_for_date(conn, client_id, req.auto_reverse_on) is None:
            raise _rule_error("F-04", f"The automatic reversal needs the next financial year ({_fmt(req.auto_reverse_on)}); create it first.")
        reverse = _journal(client_id, req.auto_reverse_on, f"Reversal of: {result.narration}", engine.reversal_lines(result.lines))
    for draft in (main, reverse):   # check everything before the first write
        if draft is not None:
            errors = vouchers.validate_draft(conn, draft)
            if errors:
                raise VoucherRuleError(errors)
    created = vouchers.create_draft(conn, main, actor=actor)
    if created.errors:
        raise VoucherRuleError(created.errors)
    reverse_id = None
    if reverse is not None:
        rev = vouchers.create_draft(conn, reverse, actor=actor)
        if rev.errors:
            raise VoucherRuleError(rev.errors)
        reverse_id = rev.voucher_id
    adjustment_id = uuid.uuid4()
    frepo.insert_adjustment(conn, {
        "id": adjustment_id, "client_id": client_id, "financial_year_id": year.id, "adj_type": result.adj_type.value, "as_on_date": req.as_on_date,
        "amount": result.amount, "params": params, "basis_note": req.basis_note.strip(), "voucher_id": created.voucher_id,
        "auto_reverse_voucher_id": reverse_id, "created_by": actor,
    })
    audit.log(conn, AuditEntry(client_id, actor, "create", "adjustment_entry", adjustment_id, new={
        "adj_type": result.adj_type.value, "as_on_date": req.as_on_date.isoformat(), "amount": str(result.amount), "voucher_id": str(created.voucher_id),
        "auto_reverse_voucher_id": str(reverse_id) if reverse_id else None, "params": params}))
    return {"adjustment_id": adjustment_id, "voucher_id": created.voucher_id, "auto_reverse_voucher_id": reverse_id, "amount": result.amount,
            "lines": _lines_out(result, ctx.ledgers)}


def list_adjustments(conn: Connection, client_id: Any, financial_year_id: Any, adj_type: str | None = None) -> list[dict]:
    _require_client(conn, client_id)
    _require_year(conn, client_id, financial_year_id)
    return frepo.list_adjustments(conn, client_id, financial_year_id, adj_type)


def delete_adjustment(conn: Connection, client_id: Any, adjustment_id: Any, *, actor: str) -> None:
    """Only while the journal (and its automatic reversal) is still a draft; a posted adjustment is undone by reversing its voucher."""
    actor = require_actor(actor)
    entry = frepo.get_adjustment(conn, client_id, adjustment_id)
    if entry is None:
        raise ServiceError("not_found", "Adjustment not found.")
    if entry["voucher_status"] != "draft" or entry["auto_reverse_status"] not in (None, "draft"):
        raise ServiceError("adjustment_state", "Only an adjustment whose journal is still a draft can be deleted; "
                           "reverse a posted journal with the ordinary voucher reversal.")
    frepo.delete_adjustment(conn, adjustment_id)
    vouchers.delete_draft(conn, entry["voucher_id"], actor=actor)
    if entry["auto_reverse_voucher_id"] is not None:
        vouchers.delete_draft(conn, entry["auto_reverse_voucher_id"], actor=actor)
    audit.log(conn, AuditEntry(client_id, actor, "delete", "adjustment_entry", adjustment_id, old={
        "adj_type": entry["adj_type"], "as_on_date": entry["as_on_date"].isoformat(), "amount": str(entry["amount"]),
        "voucher_id": str(entry["voucher_id"]), "params": entry["params"]}))


__all__ = ["AdjustmentRequest", "create", "create_partner", "delete_adjustment", "get_ledger_roles", "get_terms", "list_adjustments",
           "list_partners", "preview", "put_terms", "set_ledger_role", "setup_ledgers", "update_partner"]
