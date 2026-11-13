"""Excel and JSON outputs of the GST workings (Phase 3, package E).

Input is the working as the service returns it after `jsonable` (amounts as strings). Excel: a Summary sheet with the rule
statuses and warnings first, then one sheet per table, numbers as numbers (2 decimals). JSON: the portal's offline-tool
structure AS UNDERSTOOD; no official sample has been checked, so the API labels it `unverified-against-portal-schema`.
Floats appear only in the JSON file (portal numbers); no accounting is done here.
"""

import io
import re
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font

FORMAT_STATUS = "unverified-against-portal-schema"
_TWO = re.compile(r"^-?\d+\.\d{2}$")
_THREE = re.compile(r"^-?\d+\.\d{3}$")
_RATE = re.compile(r"^-?\d+(\.\d{1,4})?$")
TEXT_KEYS = {
    "invoice_no", "note_no", "hsn_sac", "from_no", "to_no", "reference", "reference_no", "voucher_number", "party_gstin",
    "gstin", "place_of_supply", "number", "voucher_id", "registration_id", "arn", "uqc", "nature", "line",
}
RATE_KEYS = {"rate", "gst_rate", "cess_rate"}


def _scalar(key: str, value):
    """An Excel cell value: strings that are amounts become numbers."""
    if isinstance(value, str) and key not in TEXT_KEYS:
        if key in RATE_KEYS and _RATE.match(value):
            return Decimal(value), "0.00##"
        if key == "quantity" and _THREE.match(value):
            return Decimal(value), "0.000"
        if _TWO.match(value):
            return Decimal(value), "0.00"
    return value, None


def _flatten(node, ctx: dict):
    """Rows of a table: nested lists repeat their parents' fields, nested dicts become a 'line' path."""
    if isinstance(node, list):
        for el in node:
            if isinstance(el, (dict, list)):
                yield from _flatten(el, ctx)
        return
    if not isinstance(node, dict):
        return
    scalars = {k: v for k, v in node.items() if not isinstance(v, (dict, list))}
    containers = {k: v for k, v in node.items() if isinstance(v, (dict, list))}
    merged = {**ctx, **scalars}
    if not containers or all(isinstance(v, list) and not any(isinstance(e, (dict, list)) for e in v) for v in containers.values()):
        yield {**merged, **{k: "; ".join(map(str, v)) for k, v in containers.items() if v}}
        return
    for k, v in containers.items():
        if isinstance(v, dict):
            line = f"{ctx.get('line', '')}/{k}".lstrip("/")
            yield from _flatten(v, {**merged, "line": line})
        else:
            yield from _flatten(v, merged)


def _sheet(wb: Workbook, name: str, node) -> None:
    ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "_", name)[:31])
    rows = list(_flatten(node, {}))
    columns: list[str] = []
    for r in rows:
        for k in r:
            if k not in columns:
                columns.append(k)
    ws.append(columns)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        cells = []
        formats = []
        for col in columns:
            v = r.get(col)
            v, fmt = _scalar(col, v)
            cells.append(v)
            formats.append(fmt)
        ws.append(cells)
        for cell, fmt in zip(ws[ws.max_row], formats, strict=True):
            if fmt:
                cell.number_format = fmt


def working_to_xlsx(env: dict, title: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    for label, key in (("GSTIN", "gstin"), ("Period from", "period_start"), ("Period to", "period_end"),
                       ("Generated at", "generated_at"), ("Posted vouchers used", "source_voucher_count")):
        ws.append([label, env.get(key)])
    status = env.get("rule_status", {})
    ws.append(["Worst rule status", status.get("worst")])
    for table, st in status.get("tables", {}).items():
        ws.append([f"Rule status: {table}", st])
    for src in status.get("pending_sources", []):
        ws.append(["PENDING rule, to be verified", src])
    for w in env.get("warnings", []):
        ws.append(["Warning", w])
    for d in env.get("unposted_drafts_in_period", []):
        ws.append(["Unposted voucher not in figures", f"{d.get('voucher_type')} {d.get('reference_no') or d.get('voucher_id')} {d.get('invoice_value')}"])
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 90
    for name, node in env["tables"].items():
        if isinstance(node, (dict, list)) and node:
            _sheet(wb, name, node)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- JSON (portal offline-tool structure as understood) ------------------------------------------------------------


def _n(value) -> float:
    return float(Decimal(str(value)))


def _d(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}-{m}-{y}"


def _fp(env: dict) -> str:
    d = date.fromisoformat(env["period_start"])
    return f"{d.month:02d}{d.year}"


def _itm(num: int, it: dict) -> dict:
    return {"num": num, "itm_det": {"rt": _n(it["rate"]), "txval": _n(it["taxable_value"]), "iamt": _n(it["igst"]),
                                    "camt": _n(it["cgst"]), "samt": _n(it["sgst"]), "csamt": _n(it["cess"])}}


_INV_TYPE = {"regular": "R", "deemed_export": "DE", "sez_with_payment": "SEWP", "sez_without_payment": "SEWOP"}


def _inv(i: dict) -> dict:
    return {"inum": i["invoice_no"], "idt": _d(i["invoice_date"]), "val": _n(i["invoice_value"]), "pos": i["place_of_supply"],
            "rchrg": i["reverse_charge"], "inv_typ": _INV_TYPE.get(i["supply_type"], "R"),
            "itms": [_itm(n, it) for n, it in enumerate(i["items"], 1)]}


def _note(n: dict) -> dict:
    return {"ntty": n["note_type"], "nt_num": n["note_no"], "nt_dt": _d(n["note_date"]), "val": _n(n["note_value"]),
            "pos": n["place_of_supply"], "rchrg": "N", "inv_typ": _INV_TYPE.get(n["supply_type"], "R"),
            "inum": n["original_invoice_no"], "idt": _d(n["original_invoice_date"]) if n["original_invoice_date"] else None,
            "itms": [_itm(k, it) for k, it in enumerate(n["items"], 1)]}


def gstr1_json(env: dict) -> dict:
    t = env["tables"]
    state = env["gstin"][:2]
    b2b = [{"ctin": p["party_gstin"], "inv": [_inv(i) for i in p["invoices"]]} for p in t["b2b"]]
    for p in t["sez"]:
        b2b.append({"ctin": p["party_gstin"], "inv": [_inv(i) for i in p["invoices"]]})
    nil_map = {"inter_registered": "INTRB2B", "intra_registered": "INTRAB2B",
               "inter_unregistered": "INTRB2C", "intra_unregistered": "INTRAB2C"}
    hsn = [{"num": n, "hsn_sc": r["hsn_sac"], "desc": r["description"], "uqc": r["uqc"], "qty": _n(r["quantity"]),
            "val": _n(r["total_value"]), "txval": _n(r["taxable_value"]), "iamt": _n(r["igst"]), "camt": _n(r["cgst"]),
            "samt": _n(r["sgst"]), "csamt": _n(r["cess"]), "rt": _n(r["rate"])} for n, r in enumerate(t["hsn_summary"], 1)]
    return {
        "gstin": env["gstin"], "fp": _fp(env),
        "b2b": b2b,
        "b2cl": [{"pos": g["place_of_supply"], "inv": [{k: v for k, v in _inv(i).items() if k not in ("pos", "rchrg", "inv_typ")}
                                                       for i in g["invoices"]]} for g in t["b2cl"]],
        "b2cs": [{"sply_ty": "INTRA" if r["place_of_supply"] == state else "INTER", "pos": r["place_of_supply"], "typ": "OE",
                  **{k: v for k, v in _itm(1, r)["itm_det"].items()}} for r in t["b2cs"]],
        "cdnr": [{"ctin": p["party_gstin"], "nt": [_note(n) for n in p["notes"]]} for p in t["cdnr"]],
        "cdnur": [{"typ": n["unregistered_type"], **_note(n)} for n in t["cdnur"]],
        "exp": [{"exp_typ": "WPAY" if e["export_type"] == "with_payment" else "WOPAY",
                 "inv": [{"inum": i["invoice_no"], "idt": _d(i["invoice_date"]), "val": _n(i["invoice_value"]),
                          "itms": [_itm(n, it)["itm_det"] for n, it in enumerate(i["items"], 1)]} for i in e["invoices"]]}
                for e in t["exports"]],
        "nil": {"inv": [{"sply_ty": nil_map[k], "expt_amt": _n(v["exempt"]), "nil_amt": _n(v["nil_rated"]),
                         "ngsup_amt": _n(v["non_gst"])} for k, v in t["nil_exempt_non_gst"].items()]},
        "hsn": {"data": hsn},
        "doc_issue": {"doc_det": [{"doc_num": n, "doc_typ": d["nature"], "docs": [{
            "num": 1, "from": d["from_no"], "to": d["to_no"], "totnum": d["total"], "cancel": d["cancelled"],
            "net_issue": d["net_issued"]}]} for n, d in enumerate(t["documents_issued"], 1)]},
    }


def _hv(h: dict) -> dict:
    return {"iamt": _n(h["igst"]), "camt": _n(h["cgst"]), "samt": _n(h["sgst"]), "csamt": _n(h["cess"])}


def _tv(b: dict) -> dict:
    return {"txval": _n(b["taxable_value"]), **_hv(b)}


def gstr3b_json(env: dict) -> dict:
    t = env["tables"]
    t31, t4, t5 = t["t3_1"], t["t4"], t["t5"]
    zero = t31["b_zero_rated"]
    a4 = t4["a"]

    return {
        "gstin": env["gstin"], "ret_period": _fp(env),
        "sup_details": {
            "osup_det": _tv(t31["a_outward_taxable"]),
            "osup_zero": {"txval": _n(zero["taxable_value"]), "iamt": _n(zero["igst"]), "csamt": _n(zero["cess"])},
            "osup_nil_exmp": {"txval": _n(t31["c_nil_exempt"]["taxable_value"])},
            "isup_rev": _tv(t31["d_inward_rcm"]),
            "osup_nongst": {"txval": _n(t31["e_non_gst"]["taxable_value"])},
        },
        "inter_sup": {
            "unreg_details": [{"pos": r["place_of_supply"], "txval": _n(r["taxable_value"]), "iamt": _n(r["igst"])} for r in t["t3_2"]["unregistered"]],
            "comp_details": [{"pos": r["place_of_supply"], "txval": _n(r["taxable_value"]), "iamt": _n(r["igst"])} for r in t["t3_2"]["composition"]],
            "uin_details": [{"pos": r["place_of_supply"], "txval": _n(r["taxable_value"]), "iamt": _n(r["igst"])} for r in t["t3_2"]["uin"]],
        },
        "itc_elg": {
            "itc_avl": [{"ty": "IMPG", **_hv(a4["import_goods"])}, {"ty": "IMPS", **_hv(a4["import_services"])},
                        {"ty": "ISRC", **_hv(a4["inward_rcm"])}, {"ty": "ISD", **_hv(a4["isd"])},
                        {"ty": "OTH", **_hv(a4["all_other_itc"])}],
            "itc_rev": [{"ty": "RUL", **_hv(t4["b"]["rule_38_42_43_and_17_5"])}, {"ty": "OTH", **_hv(t4["b"]["others"])}],
            "itc_net": _hv(t4["c_net"]),
            "itc_inelg": [{"ty": "OTH", **_hv(t4["d_ineligible"])}],
        },
        "inward_sup": {"isup_details": [
            {"ty": "GST", "inter": _n(t5["inter_composition_exempt"]["taxable_value"]) + _n(t5["inter_nil"]["taxable_value"]),
             "intra": _n(t5["intra_composition_exempt"]["taxable_value"]) + _n(t5["intra_nil"]["taxable_value"])},
            {"ty": "NONGST", "inter": 0.0, "intra": _n(t5["non_gst"]["taxable_value"])}]},
    }
