"""Phase 8 glue: one end-to-end flow through the real services on the mini case (7 posted vouchers).

All 18 real checks run through audit_runs; a working paper is made from a check, sampled with a seed (twice: same ids), every exception is
decided, the paper is signed off and then proved immutable. The books (voucher / line counts and a hash) must be identical at the end.
Run once: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_audit_end_to_end.py`.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.engine.audit_types import CHECKS
from app.services import audit_papers as papers
from app.services import audit_runs
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration


def _books_state(conn):
    return tuple(conn.execute(text(
        "SELECT (SELECT count(*) FROM vouchers), (SELECT count(*) FROM voucher_lines), "
        "(SELECT md5(string_agg(id::text || status || voucher_date::text || coalesce(voucher_number, ''), ',' ORDER BY id)) FROM vouchers), "
        "(SELECT md5(string_agg(id::text || ledger_id::text || debit::text || credit::text, ',' ORDER BY id)) FROM voucher_lines)")).one())


def _code(fn, *a, **kw):
    with pytest.raises(ServiceError) as e:
        fn(*a, **kw)
    return e.value.code


def test_A00_end_to_end_run_paper_sample_sign_off_and_books_untouched(books, svc_conn):
    b = books[0]
    before = _books_state(svc_conn)
    assert before[0] == 7 and before[1] == 14

    # ---- run all 18 checks
    run = audit_runs.create_run(svc_conn, b.client_id, "auditor", b.fy_id)
    assert run["status"] == "completed"
    by = run["summary"]["by_check"]
    assert sorted(by) == sorted(CHECKS) and len(by) == 18
    for check_id, entry in by.items():   # no silent skip: ok (population recorded) or an explicit error text
        if entry.get("error"):
            assert isinstance(entry["error"], str) and check_id in entry["error"]
        else:
            assert isinstance(entry["population_ids"], list) and entry["population"] == len(entry["population_ids"]), check_id
    findings = audit_runs.list_findings(svc_conn, b.client_id, run["id"])
    assert len(findings) == run["finding_count"] and findings
    assert all(f["evidence"] for f in findings)

    # ---- working paper from a check that has findings and a population of at least 3
    check_id = next(c for c, e in sorted(by.items()) if not e.get("error") and e["findings"] > 0 and e["population"] >= 3)
    pop_ids = by[check_id]["population_ids"]
    paper = papers.create_paper(svc_conn, b.client_id, run["id"], check_id, "auditor")
    assert paper["population_count"] == len(pop_ids) and paper["items"] == by[check_id]["findings"]

    # ---- sample with a seed: reproducible, drawn from the run's population
    first = papers.sample(svc_conn, b.client_id, paper["id"], "random", "auditor", size=2, seed=7)
    again = papers.sample(svc_conn, b.client_id, paper["id"], "random", "auditor", size=2, seed=7)
    assert first["ids"] == again["ids"] and len(first["ids"]) == 2
    assert set(first["ids"]) <= set(pop_ids) and first["params"]["population_source"] == "run"
    assert first["population_digest"] == paper["population_digest"]

    # ---- decide every exception, review, sign off
    detail = papers.get_paper(svc_conn, b.client_id, paper["id"])
    assert detail["sample"]["ids"] == first["ids"]
    for i, item in enumerate(detail["items"]):
        papers.decide_item(svc_conn, b.client_id, paper["id"], item["id"], "confirmed" if i == 0 else "cleared",
                           "Checked the voucher and its bill", "reviewer")
    papers.add_note(svc_conn, b.client_id, paper["id"], "Discussed with the accountant", "reviewer")
    papers.send_to_review(svc_conn, b.client_id, paper["id"], "reviewer")
    assert papers.sign_off(svc_conn, b.client_id, paper["id"], "Exceptions answered by the client.", "partner")["ok"] is True
    signed = papers.get_paper(svc_conn, b.client_id, paper["id"])
    assert signed["status"] == "signed_off" and signed["conclusion"] == "Exceptions answered by the client."

    # ---- immutability, in the service and in the database
    first_item = signed["items"][0]["id"]
    assert _code(papers.decide_item, svc_conn, b.client_id, paper["id"], first_item, "cleared", "changed my mind", "reviewer") == "paper_signed_off"
    assert _code(papers.add_note, svc_conn, b.client_id, paper["id"], "late note", "reviewer") == "paper_signed_off"
    assert _code(papers.sample, svc_conn, b.client_id, paper["id"], "random", "auditor", size=1, seed=1) == "paper_signed_off"
    assert _code(papers.reopen, svc_conn, b.client_id, paper["id"], "reviewer") == "paper_signed_off"
    for sql in ("UPDATE audit_working_papers SET conclusion = 'tampered' WHERE id = :p",
                "UPDATE audit_paper_items SET status = 'open' WHERE paper_id = :p"):
        with pytest.raises(DBAPIError), svc_conn.begin_nested():
            svc_conn.execute(text(sql), {"p": paper["id"]})
    assert papers.get_paper(svc_conn, b.client_id, paper["id"])["conclusion"] == "Exceptions answered by the client."

    # ---- the audit never touched the books
    assert _books_state(svc_conn) == before
