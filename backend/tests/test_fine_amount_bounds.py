"""Anwesenheitsbusse: Betrag passend zur Spalte (Bug-Bounty 2026-11-23,
pendenzen-bussen/fehlerbehandlung).

attendance_fine.amount ist numeric(15,2) mit CHECK amount > 0. POST /fines nahm jeden Betrag > 0
an: 10^14 sprengte die Spalte (DataError), 0.004 wurde von PostgreSQL auf 0.00 gerundet und
verletzte den CHECK (IntegrityError) - beides als 400 «Fine could not be created» plus Eintrag
im Fehlerprotokoll, obwohl nur die Eingabe ungültig war."""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.routes import fines as fine_routes
from app.schemas.fines import AttendanceFineCreate
from tests.factories import make_current_user, make_finance_account, make_participant, make_protocol, make_template, make_tenant


def _payload(**values):
    base = {
        "protocol_id": "00000000-0000-0000-0000-000000000001",
        "participant_name_snapshot": "Anna",
        "fine_type": "late",
        "account_id": "00000000-0000-0000-0000-000000000002",
    }
    return AttendanceFineCreate.model_validate({**base, **values})


@pytest.mark.parametrize("amount", ["1e14", "10000000000000", "0.004", "1e40"])
def test_amount_outside_the_column_is_rejected(amount):
    with pytest.raises(ValidationError):
        _payload(amount=amount)


@pytest.mark.parametrize(("amount", "stored"), [("5", "5.00"), ("2.505", "2.51"), ("0.005", "0.01"), ("9999999999999.99", "9999999999999.99")])
def test_amount_is_rounded_like_the_database(amount, stored):
    assert _payload(amount=amount).amount == Decimal(stored)


def test_tariff_mode_still_needs_no_amount():
    assert _payload(use_tariff=True).amount is None


def test_rounded_amount_is_stored(db):
    tenant = make_tenant(db, "Busse Betrag")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-AMT")
    account = make_finance_account(db, tenant.id)
    anna = make_participant(db, tenant.id, display_name="Anna")
    payload = _payload(
        protocol_id=str(protocol.public_id), participant_id=str(anna.public_id), account_id=str(account.public_id), amount="2.505"
    )

    created = fine_routes.create_fine(payload, db=db, user=make_current_user(tenant.id, role="admin"))

    assert created.amount == Decimal("2.51")
