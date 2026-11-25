"""Fachentscheid 2026-11-25: Namen gebüsster Personen im Kassenbuch nur mit reports.personal.
Ohne (Standardrolle «Leser») stehen Buchungstext und locked_detail als «Busse …: ·····» da - in
der API und im PDF; Kasse und Admin sehen weiter alles. Gespeichert wird nichts anders."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from app.api.routes import finance as finance_routes
from app.documents.providers import finance as finance_provider
from app.models.entities import FinanceTransaction
from app.services.fine_name_masking import MASK
from tests.factories import (
    make_current_user,
    make_finance_account,
    make_fine,
    make_participant,
    make_protocol,
    make_template,
    make_tenant,
    system_role_permissions,
)

TEXT = "Busse Verspätet: Max Muster"


def _setup(db):
    tenant = make_tenant(db, "Kasse Namen")
    account = make_finance_account(db, tenant.id)
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id, protocol_date=date(2026, 3, 1))
    fine = make_fine(db, protocol_id=protocol.id, account_id=account.id, amount=5.0, participant_name_snapshot="Max Muster")
    tx = FinanceTransaction(account_id=account.id, amount=Decimal("5.00"), description=TEXT, transaction_date=date(2026, 3, 2))
    other = FinanceTransaction(account_id=account.id, amount=Decimal("-20.00"), description="Material: Seile", transaction_date=date(2026, 3, 3))
    db.add_all([tx, other])
    db.flush()
    fine.collected_transaction_id = tx.id
    fine.status = "collected"
    db.flush()
    return tenant, account, tx, other


def _user(db, tenant, role):
    person = make_participant(db, tenant.id, f"{role} Person")
    return make_current_user(tenant.id, role=role, user_id=person.id, permissions=system_role_permissions(role))


def _listed(db, account, user):
    rows = finance_routes.list_transactions(account.public_id, skip=0, limit=50, year=None, db=db, user=user)
    return {row.description: row for row in rows}


def test_reader_sees_the_fine_booking_without_the_name(db):
    tenant, account, tx, _other = _setup(db)

    rows = _listed(db, account, _user(db, tenant, "reader"))

    assert set(rows) == {f"Busse Verspätet: {MASK}", "Material: Seile"}
    assert rows[f"Busse Verspätet: {MASK}"].locked_detail == MASK
    assert db.scalar(select(FinanceTransaction.description).where(FinanceTransaction.id == tx.id)) == TEXT  # gespeichert unverändert


def test_cashier_and_admin_see_the_name(db):
    tenant, account, _tx, _other = _setup(db)

    for role in ("kassier", "admin"):
        rows = _listed(db, account, _user(db, tenant, role))
        assert TEXT in rows and rows[TEXT].locked_detail == "Max Muster", role


def test_pdf_table_masks_the_name_for_the_reader_only(db):
    tenant, account, tx, other = _setup(db)

    def table_for(role):
        ctx = SimpleNamespace(db=db, user=_user(db, tenant, role))
        table = finance_provider.transactions_table(account, [tx, other], fine_names=finance_provider.masked_fine_names(ctx, [tx, other]))
        return [row.cells[1].v for group in table.groups for row in group.rows]

    assert table_for("reader") == [f"Busse Verspätet: {MASK}", "Material: Seile"]
    assert table_for("kassier") == [TEXT, "Material: Seile"]
