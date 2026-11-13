"""Turns service errors into HTTP answers exactly as docs/API_CONTRACT.md says.

ServiceError            -> {"code", "message", "details"} with a status chosen by code
VoucherRuleError        -> 422 {"errors": [{"rule_id", "message", "line_no"}]}
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.engine.models import ValidationError
from app.services.errors import ServiceError, VoucherRuleError

UNPROCESSABLE = {"reason_required", "client_mismatch", "no_financial_year", "statement_invalid", "import_invalid"}


def status_for(code: str) -> int:
    if code == "not_found":
        return 404
    if code == "invalid_actor":
        return 400
    if code == "database_unavailable":
        return 503
    if code.startswith("invalid_") or code in UNPROCESSABLE:
        return 422
    return 409


def rule_errors_body(errors: list[ValidationError]) -> dict:
    return {"errors": [{"rule_id": e.rule_id, "message": e.message, "line_no": e.line_no} for e in errors]}


def rule_errors_response(errors: list[ValidationError]) -> JSONResponse:
    return JSONResponse(status_code=422, content=rule_errors_body(errors))


def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=status_for(exc.code),
        content={"code": exc.code, "message": exc.message, "details": _jsonable(exc.details)},
    )


def _voucher_rule_error(_: Request, exc: VoucherRuleError) -> JSONResponse:
    return rule_errors_response(exc.errors)


def _jsonable(value):
    """Details may hold UUIDs and dates (e.g. the vouchers blocking a period lock)."""
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(VoucherRuleError, _voucher_rule_error)
    app.add_exception_handler(ServiceError, _service_error)
