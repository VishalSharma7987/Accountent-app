"""Loader of the MSME payment-time rule table (law is data). The rule is picked by the BILL date
(engine.msme.pick_rule); `verification_status` and `source_reference` travel with every flag so reports can show
'pending' / 'secondary_verified' until the owner's CA has signed the legal text."""

from sqlalchemy import Connection

from app.db import repositories_cash as repo
from app.engine.msme import MsmeRule, pick_rule, rules_status

__all__ = ["MsmeRule", "load_msme_rules", "pick_rule", "rules_status"]


def load_msme_rules(conn: Connection) -> list[MsmeRule]:
    return [MsmeRule(*row[:9], tuple(row[9])) for row in repo.msme_rule_rows(conn)]
