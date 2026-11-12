"""Business errors raised by services. The API turns them into 4xx answers; messages are plain language."""

from app.engine.models import ValidationError


class ServiceError(Exception):
    """A refused operation. `code` is stable (for programs), `message` is for the accountant."""

    def __init__(self, code: str, message: str, details: object = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details  # optional structured data for the caller, e.g. the vouchers blocking a period lock


class VoucherRuleError(ServiceError):
    """A voucher that breaks accounting rules: carries every ValidationError (rule_id, message, line_no)."""

    def __init__(self, errors: list[ValidationError]):
        super().__init__("rule_violation", "; ".join(e.message for e in errors))
        self.errors = errors


def require_actor(actor: str | None) -> str:
    if actor is None or not actor.strip():
        raise ServiceError("invalid_actor", "The actor (who is making this change) is required.")
    return actor.strip()
