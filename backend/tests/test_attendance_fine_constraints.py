"""Audit MAIN-BE-016: Status und Typ einer Busse sind per CHECK-Constraint abgesichert
(Baseline bzw. Migration 0115)."""
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import AttendanceFine
from tests.factories import make_finance_account, make_protocol, make_template, make_tenant


def _fine_kwargs(db):
    tenant = make_tenant(db, "Constraint-Test")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    return {"protocol_id": protocol.id, "account_id": account.id, "amount": Decimal("5.00"), "participant_name_snapshot": "X"}


@pytest.mark.parametrize(("field", "value"), [("status", "bezahlt"), ("fine_type", "zu_spaet")])
def test_invalid_values_are_rejected_by_the_database(db, field, value):
    values = {**_fine_kwargs(db), "fine_type": "late", "status": "pending", field: value}
    nested = db.begin_nested()
    db.add(AttendanceFine(**values))
    with pytest.raises(IntegrityError):
        db.flush()
    nested.rollback()


def test_valid_values_are_accepted(db):
    db.add(AttendanceFine(**_fine_kwargs(db), fine_type="absent", status="collected"))
    db.flush()
