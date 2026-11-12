"""Finanz-Audit 2026-11 (audit-reports/bereiche-2026-11/04-finanzen.md): Bussen-Export ohne
Personendaten-Recht, gesperrte Pendenzen-Bussen-Buchungen, Nur-Lesen nach Downgrade,
Dashboard-Summe je Währung, Zürcher Datum beim Einkassieren, Eingabegrenzen."""
from __future__ import annotations

import dataclasses
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import finance as finance_routes
from app.api.routes import fines as fines_routes
from app.documents.catalog import BlockSpec, FinesParams
from app.documents.context import BuildContext
from app.documents.providers.finance import provide_fines
from app.models import FinanceAccount, FinanceTransaction
from app.models.entities import TodoFine
from app.repositories.finance_repository import FinanceConflictError, FinanceRepository
from app.repositories.fines_repository import FinesRepository
from app.schemas.finance import FinanceAccountUpdate, FinanceTransactionCreate, FinanceTransactionUpdate
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


def _reader(tenant_id: int, user_id: int):
    return make_current_user(tenant_id, role="reader", user_id=user_id, permissions=system_role_permissions("reader"))


def _fine_for(db, protocol, account, participant, amount="5.00", name=None, fine_type="late"):
    fine = make_fine(db, protocol_id=protocol.id, account_id=account.id, amount=Decimal(amount), participant_name_snapshot=name or participant.display_name, fine_type=fine_type)
    fine.participant_id = participant.id
    db.flush()
    return fine


def _names(blocks) -> list[str]:
    table = blocks[0].table
    return [row.cells[0].v for group in table.groups for row in group.rows]


# ── (1) Document Studio: Bussen sind Personendaten ──────────────────────────────


def test_reader_fines_export_contains_only_own_fines(db):
    tenant = make_tenant(db, "Tenant (FIN-1)")
    template = make_template(db, tenant.id)
    # Abgeschlossen: das darf auch die Rolle «Leser» lesen
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    account = make_finance_account(db, tenant.id)
    me = make_participant(db, tenant.id, "Lea Leserin")
    other = make_participant(db, tenant.id, "Otto Andere")
    _fine_for(db, protocol, account, me)
    _fine_for(db, protocol, account, other)

    reader_ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", user=_reader(tenant.id, me.id))
    assert _names(provide_fines(reader_ctx, BlockSpec(type="fines"), FinesParams())) == ["Lea Leserin"]
    # Auch an ein Protokoll gebunden nur die eigenen
    bound = provide_fines(reader_ctx, BlockSpec(type="fines"), FinesParams(protocol_id=protocol.public_id))
    assert _names(bound) == ["Lea Leserin"]

    kassier_ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", user=make_current_user(tenant.id, role="admin", user_id=me.id))
    assert sorted(_names(provide_fines(kassier_ctx, BlockSpec(type="fines"), FinesParams()))) == ["Lea Leserin", "Otto Andere"]


# ── (2) Buchungen von Pendenzen-Bussen gesperrt ─────────────────────────────────


def _collected_todo_fine(db):
    tenant = make_tenant(db, "Tenant (FIN-2)")
    account = make_finance_account(db, tenant.id)
    tx = FinanceTransaction(account_id=account.id, amount=Decimal("4.00"), description="Busse Pendenz", transaction_date=date(2026, 3, 1))
    db.add(tx)
    db.flush()
    fine = TodoFine(
        tenant_id=tenant.id, participant_name_snapshot="Max Muster", task_snapshot="Bericht",
        due_date=date(2026, 2, 1), completed_on=date(2026, 2, 5), days_late=4, amount=Decimal("4.00"),
        account_id=account.id, status="collected", collected_at=datetime(2026, 3, 1, tzinfo=timezone.utc), collected_transaction_id=tx.id,
    )
    db.add(fine)
    db.flush()
    return tenant, account, fine, tx


def test_todo_fine_transaction_cannot_be_changed_or_deleted(db):
    tenant, account, fine, tx = _collected_todo_fine(db)
    repo = FinanceRepository()

    with pytest.raises(FinanceConflictError) as exc:
        repo.update_transaction(db, tx.id, tenant.id, FinanceTransactionUpdate(amount=Decimal("1.00")))
    assert exc.value.code == "todo_fine_transaction"
    with pytest.raises(FinanceConflictError):
        repo.delete_transaction(db, tx.id, tenant.id)
    assert db.get(FinanceTransaction, tx.id).amount == Decimal("4.00")
    assert db.get(TodoFine, fine.id).collected_transaction_id == tx.id

    listed = repo.list_transactions(db, account.id)
    assert listed[0].locked_reason == "todo_fine_transaction"
    assert listed[0].locked_detail == "Max Muster"

    user = make_current_user(tenant.id, role="admin")
    with pytest.raises(HTTPException) as http:
        finance_routes.delete_transaction(tx.public_id, db=db, user=user)
    assert http.value.status_code == 409
    assert http.value.detail["code"] == "todo_fine_transaction"


def test_finalized_protocol_transaction_returns_409_not_404(db):
    tenant = make_tenant(db, "Tenant (FIN-2b)")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    account = make_finance_account(db, tenant.id)
    tx = FinanceTransaction(account_id=account.id, amount=Decimal("2.00"), description="x", transaction_date=date(2026, 1, 1), protocol_id=protocol.id)
    db.add(tx)
    db.flush()

    user = make_current_user(tenant.id, role="admin")
    with pytest.raises(HTTPException) as http:
        finance_routes.update_transaction(tx.public_id, FinanceTransactionUpdate(description="y"), db=db, user=user)
    assert http.value.status_code == 409
    assert http.value.detail["code"] == "protocol_finalized"
    assert FinanceRepository().list_transactions(db, account.id)[0].locked_reason == "protocol_finalized"


def test_todo_fine_blocks_account_delete_and_counts_as_provisional(db):
    tenant, account, fine, _ = _collected_todo_fine(db)
    pending = TodoFine(
        tenant_id=tenant.id, participant_name_snapshot="Eva", task_snapshot="Kasse",
        due_date=date(2026, 2, 1), completed_on=date(2026, 2, 3), days_late=2, amount=Decimal("2.50"),
        account_id=account.id, status="pending",
    )
    db.add(pending)
    db.flush()
    read = FinanceRepository().get_account(db, account.id, tenant.id)
    assert read.provisional_balance == Decimal("2.50")
    assert [row.provisional_balance for row in FinanceRepository().list_accounts(db, tenant.id)] == [Decimal("2.50")]
    with pytest.raises(FinanceConflictError):
        FinanceRepository().delete_account(db, account.id, tenant.id)


# ── (3) Nur-Lesen nach Downgrade ────────────────────────────────────────────────


def test_fine_read_routes_work_in_read_only_mode(db):
    tenant = make_tenant(db, "Tenant (FIN-3)")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    user = dataclasses.replace(
        make_current_user(tenant.id, role="admin"),
        current_tenant_features=frozenset(), current_tenant_read_only_features=frozenset({"finance"}),
    )
    assert fines_routes.list_fines(skip=0, limit=50, fine_status=None, db=db, user=user) == []
    assert fines_routes.get_fine_tariff(db=db, user=user) is not None
    assert fines_routes.list_protocol_fines(protocol.public_id, db=db, user=user) == []
    assert fines_routes.list_pending_fines(protocol.public_id, db=db, user=user) == []
    assert fines_routes.open_fines_summary(db=db, user=user).count == 0


# ── (4) Dashboard: offene Bussen je Währung über alle Bussen ────────────────────


def test_open_fines_summary_groups_by_currency_and_respects_visibility(db):
    tenant = make_tenant(db, "Tenant (FIN-4)")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    chf = make_finance_account(db, tenant.id, name="Kasse")
    eur = make_finance_account(db, tenant.id, name="Euro")
    eur.currency_label = "EUR"
    db.flush()
    me = make_participant(db, tenant.id, "Lea")
    other = make_participant(db, tenant.id, "Otto")
    _fine_for(db, protocol, chf, me, "5.00")
    _fine_for(db, protocol, chf, other, "7.50")
    _fine_for(db, protocol, eur, other, "3.00", fine_type="absent")
    collected = _fine_for(db, make_protocol(db, tenant.id, template.id, protocol_number="P-2"), chf, other, "100.00")
    collected.status = "collected"
    db.flush()

    admin = make_current_user(tenant.id, role="admin")
    summary = fines_routes.open_fines_summary(db=db, user=admin)
    totals = {item.currency_label: item.amount for item in summary.totals}
    assert totals == {"CHF": Decimal("12.50"), "EUR": Decimal("3.00")}
    assert summary.people == 2 and summary.count == 3 and summary.own_only is False

    reader = fines_routes.open_fines_summary(db=db, user=_reader(tenant.id, me.id))
    assert reader.own_only is True
    assert [(item.currency_label, item.amount) for item in reader.totals] == [("CHF", Decimal("5.00"))]

    pending = fines_routes.list_fines(skip=0, limit=200, fine_status="pending", db=db, user=admin)
    assert len(pending) == 3 and all(item.status == "pending" for item in pending)


# ── Mittel/Niedrig ──────────────────────────────────────────────────────────────


def test_collect_uses_swiss_date_and_translated_text(db):
    tenant = make_tenant(db, "Tenant (FIN-5)")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    fine = make_fine(db, protocol_id=protocol.id, account_id=account.id, participant_name_snapshot="Max Muster")
    # 31.12. 23:30 UTC = 1.1. 00:30 in Zürich
    fake_now = datetime(2025, 12, 31, 23, 30, tzinfo=timezone.utc)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401 - Testersatz
            return fake_now if tz is not None else fake_now.replace(tzinfo=None)

    with patch("app.repositories.fines_repository.datetime", _FakeDatetime):
        assert FinesRepository().collect_fine(db, fine.id, tenant.id, actor_user_id=1, collecting_protocol_id=protocol.id) is not None
    tx = db.query(FinanceTransaction).filter(FinanceTransaction.account_id == account.id).one()
    assert tx.transaction_date == date(2026, 1, 1)
    assert "late" not in tx.description and "Max Muster" in tx.description


def test_account_description_can_be_cleared(db):
    tenant = make_tenant(db, "Tenant (FIN-6)")
    account = make_finance_account(db, tenant.id)
    account.description = "Alt"
    db.flush()
    repo = FinanceRepository()
    repo.update_account(db, account.id, tenant.id, FinanceAccountUpdate(name="Kasse"))
    assert db.get(FinanceAccount, account.id).description == "Alt"
    repo.update_account(db, account.id, tenant.id, FinanceAccountUpdate(description=None))
    assert db.get(FinanceAccount, account.id).description is None


def test_transaction_input_limits():
    with pytest.raises(ValidationError):
        FinanceTransactionCreate(amount=Decimal("100000000000000"), description="x", transaction_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        FinanceTransactionCreate(amount=Decimal("1"), description="   ", transaction_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        FinanceTransactionUpdate(description="")


def test_period_summary_and_year_filter_keep_real_running_balance(db):
    tenant = make_tenant(db, "Tenant (FIN-7)")
    account = make_finance_account(db, tenant.id)
    for when, amount in ((date(2025, 6, 1), "100.00"), (date(2026, 2, 1), "50.00"), (date(2026, 3, 1), "-20.00")):
        db.add(FinanceTransaction(account_id=account.id, amount=Decimal(amount), description="x", transaction_date=when))
    db.flush()
    repo = FinanceRepository()

    summary = repo.period_summary(db, account.id, 2026)
    assert summary["income"] == Decimal("50.00") and summary["expenses"] == Decimal("-20.00")
    assert summary["opening_balance"] == Decimal("100.00") and summary["closing_balance"] == Decimal("130.00")
    assert summary["years"] == [2026, 2025]

    listed = repo.list_transactions(db, account.id, year=2026)
    assert [tx.running_balance for tx in listed] == [Decimal("130.00"), Decimal("150.00")]
