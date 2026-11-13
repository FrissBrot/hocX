"""Eine Währung je Verein (tenant.finance_currency): in den Mandanten-Einstellungen gesetzt, gilt
für alle Konten und Bussen. Konten nehmen sie beim Anlegen, eine Änderung zieht alle Konten mit."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import finance as finance_routes
from app.api.routes import finance_settings as routes
from app.models import FinanceAccount
from app.schemas.finance import FinanceAccountCreate, FinanceAccountUpdate
from tests.factories import make_current_user, make_tenant


def test_currency_is_set_per_tenant_and_applies_to_all_accounts(db):
    tenant = make_tenant(db, "Währung A")
    other = make_tenant(db, "Währung B")
    admin = make_current_user(tenant.id, role="admin")
    other_admin = make_current_user(other.id, role="admin")

    assert routes.get_finance_settings(db=db, user=admin).currency == "CHF"
    first = finance_routes.create_account(FinanceAccountCreate(name="Kasse"), db=db, user=admin)
    assert first.currency_label == "CHF"
    foreign = finance_routes.create_account(FinanceAccountCreate(name="Fremd"), db=db, user=other_admin)

    assert routes.update_finance_settings(routes.FinanceSettingsWrite(currency=" EUR "), db=db, user=admin).currency == "EUR"
    db.expire_all()
    labels = {account.name: account.currency_label for account in db.query(FinanceAccount).filter(FinanceAccount.tenant_id.in_([tenant.id, other.id]))}
    assert labels == {"Kasse": "EUR", "Fremd": "CHF"}  # fremder Mandant bleibt unverändert
    assert foreign.currency_label == "CHF"

    # Neue Konten übernehmen die Vereinswährung, auch wenn ein alter Client eine eigene schickt
    second = finance_routes.create_account(FinanceAccountCreate(name="Bussen", currency_label="USD"), db=db, user=admin)
    assert second.currency_label == "EUR"
    updated = finance_routes.update_account(second.id, FinanceAccountUpdate(currency_label="USD"), db=db, user=admin)
    assert updated.currency_label == "EUR"


def test_only_settings_managers_change_the_currency(db):
    tenant = make_tenant(db, "Währung Rechte")
    kassier = make_current_user(tenant.id, role="kassier")
    reader = make_current_user(tenant.id, role="reader")
    assert routes.get_finance_settings(db=db, user=reader).currency == "CHF"
    for user in (kassier, reader):
        with pytest.raises(HTTPException) as excinfo:
            routes.update_finance_settings(routes.FinanceSettingsWrite(currency="EUR"), db=db, user=user)
        assert excinfo.value.status_code == 403
    with pytest.raises(ValidationError):
        routes.FinanceSettingsWrite(currency="   ")
    with pytest.raises(ValidationError):
        routes.FinanceSettingsWrite(currency="X" * 21)
