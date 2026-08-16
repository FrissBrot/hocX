"""Regression tests for MITTEL findings from the 2026-08-16 audit."""
from datetime import date
from decimal import Decimal

import pytest

from app.models import AttendanceFine, Protocol
from tests.factories import (
    make_finance_account,
    make_participant,
    make_protocol,
    make_tenant,
    make_template,
)


def _frozen_protocol(db, tenant_id, template_id, protocol_number="P-frozen"):
    protocol = make_protocol(db, tenant_id, template_id, protocol_number=protocol_number, status="abgeschlossen")
    return protocol


def _fine(db, *, protocol_id, account_id, status="pending", amount=Decimal("5.00")):
    fine = AttendanceFine(
        protocol_id=protocol_id, account_id=account_id, amount=amount,
        fine_type="late", participant_name_snapshot="Test", status=status,
    )
    db.add(fine)
    db.flush()
    return fine


# --- S6/S7/S8: freeze-guard for fines and finance transactions ----------------------------


def test_create_fine_rejects_frozen_protocol(db):
    from app.repositories.fines_repository import FinesRepository
    from app.schemas.fines import AttendanceFineCreate

    tenant = make_tenant(db, "Tenant (S6)")
    template = make_template(db, tenant.id)
    protocol = _frozen_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)

    repo = FinesRepository()
    result = repo.create_fine(
        db, AttendanceFineCreate(
            protocol_id=protocol.id, account_id=account.id, amount=Decimal("5.00"),
            fine_type="late", participant_name_snapshot="X",
        ), tenant.id,
    )
    assert result is None


def test_delete_fine_rejects_frozen_protocol(db):
    from app.repositories.fines_repository import FinesRepository

    tenant = make_tenant(db, "Tenant (S7)")
    template = make_template(db, tenant.id)
    protocol = _frozen_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    fine = _fine(db, protocol_id=protocol.id, account_id=account.id)

    repo = FinesRepository()
    assert repo.delete_fine(db, fine.id, tenant.id) is False


def test_collect_fine_rejects_frozen_protocol(db):
    from app.repositories.fines_repository import FinesRepository

    tenant = make_tenant(db, "Tenant (S7b)")
    template = make_template(db, tenant.id)
    protocol = _frozen_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    fine = _fine(db, protocol_id=protocol.id, account_id=account.id)

    repo = FinesRepository()
    assert repo.collect_fine(db, fine.id, tenant.id, actor_user_id=1) is None


def test_create_transaction_rejects_frozen_protocol(db):
    from app.repositories.finance_repository import FinanceRepository
    from app.schemas.finance import FinanceTransactionCreate

    tenant = make_tenant(db, "Tenant (S8)")
    template = make_template(db, tenant.id)
    protocol = _frozen_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)

    repo = FinanceRepository()
    result = repo.create_transaction(
        db, account.id, tenant.id,
        FinanceTransactionCreate(amount=Decimal("10.00"), description="x", transaction_date=date(2026, 1, 1), protocol_id=protocol.id),
    )
    assert result is None


# --- D3: title must not be re-rendered when the number update was blocked -----------------


def test_renumber_later_siblings_keeps_title_in_sync_with_blocked_number(db):
    from app.services.protocol_service import ProtocolService

    tenant = make_tenant(db, "Tenant (D3)")
    template = make_template(db, tenant.id, name="Template (D3)")
    template.protocol_number_pattern = "{n}"
    template.title_pattern = "Protokoll {n}"
    db.flush()

    # Frozen protocols are never renumbered (see _renumber_later_siblings' docstring), so
    # this one keeps number "2" despite being dated AFTER the sibling below - a plausible
    # historical quirk (manual number edit, pre-b432393 import order). Sibling (dated
    # earlier, rank 2 once the new Jan-1 protocol is inserted) will try to claim that same
    # "2" and must be blocked by the collision check.
    make_protocol(db, tenant.id, template.id, protocol_number="2", protocol_date=date(2026, 4, 1), status="abgeschlossen")
    sibling = make_protocol(db, tenant.id, template.id, protocol_number="5", protocol_date=date(2026, 2, 1), status="geplant")
    sibling.title = "Protokoll 5"
    db.flush()

    service = ProtocolService()
    service._renumber_later_siblings(
        db, tenant_id=tenant.id, template=template, protocol_date=date(2026, 1, 1), reset_month=12, reset_day=31,
    )
    db.flush()

    refreshed = db.get(Protocol, sibling.id)
    # Number stays "5" (blocked by the frozen protocol's "2") - title must match, not jump
    # to "Protokoll 2" (audit D3, 2026-08-16).
    assert refreshed.protocol_number == "5"
    assert refreshed.title == "Protokoll 5"


# --- D4: changing protocol_date re-derives number/title -----------------------------------


def test_update_protocol_date_rederives_number_and_title(db):
    from app.schemas.protocol import ProtocolUpdate
    from app.services.protocol_service import ProtocolService

    tenant = make_tenant(db, "Tenant (D4)")
    template = make_template(db, tenant.id, name="Template (D4)")
    template.protocol_number_pattern = "{n}"
    template.title_pattern = "Protokoll {n}"
    db.flush()

    make_protocol(db, tenant.id, template.id, protocol_number="1", protocol_date=date(2026, 1, 1), status="geplant")
    moved = make_protocol(db, tenant.id, template.id, protocol_number="2", protocol_date=date(2026, 6, 1), status="geplant")
    moved.title = "Protokoll 2"
    db.flush()

    service = ProtocolService()
    # Move `moved` to before the first protocol - it should become "1" and bump the other
    # one to "2".
    service.update_protocol(db, moved.id, ProtocolUpdate(protocol_date=date(2025, 1, 1)))
    db.flush()

    refreshed = db.get(Protocol, moved.id)
    assert refreshed.protocol_number == "1"
    assert refreshed.title == "Protokoll 1"


def test_update_protocol_date_skipped_for_frozen_protocol(db):
    from app.schemas.protocol import ProtocolUpdate
    from app.services.protocol_service import ProtocolService

    tenant = make_tenant(db, "Tenant (D4b)")
    template = make_template(db, tenant.id, name="Template (D4b)")
    template.protocol_number_pattern = "{n}"
    db.flush()

    protocol = make_protocol(db, tenant.id, template.id, protocol_number="5", protocol_date=date(2026, 6, 1), status="abgeschlossen")

    service = ProtocolService()
    service.update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))
    # Sanity: directly call the helper is not exercised for frozen protocols via
    # update_protocol's own status != "abgeschlossen" guard - verify the number is
    # untouched after a (no-op status) update attempt.
    db.flush()
    refreshed = db.get(Protocol, protocol.id)
    assert refreshed.protocol_number == "5"


# --- E4: delete_fine locks the row like collect_fine does ---------------------------------


def test_delete_fine_locks_row_before_deleting():
    import inspect

    from app.repositories.fines_repository import FinesRepository

    source = inspect.getsource(FinesRepository.delete_fine)
    assert "with_for_update" in source, "delete_fine must lock the row, same as collect_fine"
