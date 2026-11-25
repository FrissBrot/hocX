"""Buchung anlegen mit protocol_id prüft den Zugriff auf das Protokoll, nicht nur den Mandanten.

Wie die Bussen-Routen (test_fines_protocol_access.py): Wer Finanzen verwaltet (finances.manage),
Entwürfe aber nicht lesen darf (ohne meetings.read_drafts), konnte eine Buchung mit einem
Entwurf verknüpfen, den er nicht öffnen darf - und an der Antwort (201 statt 404) erkennen, dass
es ihn gibt. Erwartet: dieselben Regeln wie access_service.can_read_protocol, nicht lesbar =
unbekannt (gleiche 404), nichts angelegt."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.routes import finance as finance_routes
from app.models import FinanceTransaction
from app.schemas.finance import FinanceTransactionCreate
from tests.factories import make_current_user, make_finance_account, make_protocol, make_template, make_tenant

# Eigene Rolle: Kasse, Protokolle aber nur abgeschlossen lesen
FINANCE_WITHOUT_DRAFTS = frozenset({"meetings.read", "finances.read", "finances.manage"})


def _payload(protocol_public_id) -> FinanceTransactionCreate:
    return FinanceTransactionCreate(amount=Decimal("10.00"), description="Getränke", transaction_date=date(2026, 3, 1), protocol_id=protocol_public_id)


def _count(db, account_id: int) -> int:
    return db.scalar(select(func.count()).select_from(FinanceTransaction).where(FinanceTransaction.account_id == account_id))


def test_transaction_cannot_be_linked_to_an_unreadable_draft(db):
    tenant = make_tenant(db, "Buchung Protokollzugriff")
    template = make_template(db, tenant.id)
    draft = make_protocol(db, tenant.id, template.id, protocol_number="E-1", status="geplant")
    account = make_finance_account(db, tenant.id)
    user = make_current_user(tenant.id, permissions=FINANCE_WITHOUT_DRAFTS)

    with pytest.raises(HTTPException) as unknown:
        finance_routes.create_transaction(account.public_id, _payload(uuid.uuid4()), db=db, user=user)
    with pytest.raises(HTTPException) as hidden:
        finance_routes.create_transaction(account.public_id, _payload(draft.public_id), db=db, user=user)

    assert hidden.value.status_code == unknown.value.status_code == 404
    assert hidden.value.detail == unknown.value.detail
    assert _count(db, account.id) == 0


def test_transaction_links_to_a_readable_draft_with_read_drafts(db):
    tenant = make_tenant(db, "Buchung Protokollzugriff Kasse")
    template = make_template(db, tenant.id)
    draft = make_protocol(db, tenant.id, template.id, protocol_number="E-1", status="geplant")
    account = make_finance_account(db, tenant.id)
    kassier = make_current_user(tenant.id, role="kassier")

    created = finance_routes.create_transaction(account.public_id, _payload(draft.public_id), db=db, user=kassier)

    assert created.protocol_id == draft.public_id
