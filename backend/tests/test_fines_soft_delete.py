"""MAIN-BE-002 (Entscheidung 2026-10-16): Offene Bussen aus einem abgeschlossenen Protokoll
werden mit Begründung gelöscht (Status `deleted`) und im Protokoll aufgeführt, in dem gelöscht
wurde. Im noch offenen Ursprungsprotokoll bleibt das harte Löschen."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.routes import fines as fine_routes
from app.models import AttendanceFine
from app.repositories.fines_repository import FineDeleteError, FinesRepository
from app.schemas.fines import DeleteFinePayload
from app.documents.context import BuildContext
from app.documents.providers.finance import protocol_fines
from tests.factories import (
    make_app_user,
    make_current_user,
    make_finance_account,
    make_fine,
    make_protocol,
    make_template,
    make_tenant,
)


def _setup(db, *, origin_status="abgeschlossen"):
    tenant = make_tenant(db, "Tenant (Soft-Delete)")
    template = make_template(db, tenant.id)
    origin = make_protocol(db, tenant.id, template.id, protocol_number="P-A", protocol_date=date(2026, 1, 1), status=origin_status)
    following = make_protocol(db, tenant.id, template.id, protocol_number="P-B", protocol_date=date(2026, 2, 1))
    account = make_finance_account(db, tenant.id)
    fine = make_fine(db, protocol_id=origin.id, account_id=account.id, amount=Decimal("5.00"))
    return tenant, origin, following, fine


def test_fine_in_open_origin_is_still_hard_deleted(db):
    tenant, _, _, fine = _setup(db, origin_status="geplant")

    assert FinesRepository().delete_fine(db, fine.id, tenant.id) == "hard"
    assert db.get(AttendanceFine, fine.id) is None


def test_fine_from_closed_origin_needs_a_reason(db):
    tenant, _, _, fine = _setup(db)

    with pytest.raises(FineDeleteError) as exc:
        FinesRepository().delete_fine(db, fine.id, tenant.id, reason="   ")
    assert exc.value.code == "reason_required"
    assert db.get(AttendanceFine, fine.id).status == "pending"


def test_soft_delete_is_listed_in_the_deleting_protocol(db):
    tenant, origin, following, fine = _setup(db)
    actor = make_app_user(db, email="kassier@example.com", tenant_id=tenant.id, role_code="admin")
    repo = FinesRepository()

    assert repo.delete_fine(
        db, fine.id, tenant.id, actor_user_id=actor.id, reason="Doppelt erfasst", protocol_context_id=following.id,
    ) == "soft"

    row = db.get(AttendanceFine, fine.id)
    assert (row.status, row.delete_comment, row.closed_in_protocol_id, row.deleted_by_user_id) == (
        "deleted", "Doppelt erfasst", following.id, actor.id,
    )
    assert row.deleted_at is not None
    listed = repo.list_pending_fines_for_protocol(db, following.id, tenant.id)
    assert [(item.status, item.delete_comment, item.can_restore) for item in listed] == [("deleted", "Doppelt erfasst", True)]
    assert listed[0].deleted_by_display_name == actor.display_name


def test_soft_delete_without_context_uses_the_next_open_protocol(db):
    tenant, _, following, fine = _setup(db)

    assert FinesRepository().delete_fine(db, fine.id, tenant.id, reason="Erlassen") == "soft"
    assert db.get(AttendanceFine, fine.id).closed_in_protocol_id == following.id


def test_soft_delete_without_open_protocol_is_rejected(db):
    tenant, _, following, fine = _setup(db)
    following.status = "abgeschlossen"
    db.flush()

    with pytest.raises(FineDeleteError) as exc:
        FinesRepository().delete_fine(db, fine.id, tenant.id, reason="Erlassen")
    assert exc.value.code == "no_open_protocol"
    with pytest.raises(FineDeleteError) as exc:
        FinesRepository().delete_fine(db, fine.id, tenant.id, reason="Erlassen", protocol_context_id=following.id)
    assert exc.value.code == "protocol_closed"


def test_restore_only_while_the_listing_protocol_is_open(db):
    tenant, _, following, fine = _setup(db)
    repo = FinesRepository()
    repo.delete_fine(db, fine.id, tenant.id, reason="Irrtum", protocol_context_id=following.id)

    following.status = "abgeschlossen"
    db.flush()
    assert repo.restore_fine(db, fine.id, tenant.id) is None
    assert db.get(AttendanceFine, fine.id).status == "deleted"

    following.status = "geplant"
    db.flush()
    restored = repo.restore_fine(db, fine.id, tenant.id)
    assert restored is not None and restored.status == "pending"
    row = db.get(AttendanceFine, fine.id)
    assert (row.delete_comment, row.deleted_at, row.closed_in_protocol_id) == (None, None, None)


def test_deleted_fine_cannot_be_collected_and_is_not_provisional(db):
    tenant, _, following, fine = _setup(db)
    repo = FinesRepository()
    repo.delete_fine(db, fine.id, tenant.id, reason="Erlassen", protocol_context_id=following.id)

    assert repo.collect_fine(db, fine.id, tenant.id, actor_user_id=None, collecting_protocol_id=following.id) is None


def test_list_item_tells_the_client_when_a_reason_is_required(db):
    tenant, _, following, fine = _setup(db)
    items = FinesRepository().list_pending_fines_for_protocol(db, following.id, tenant.id)
    assert [item.delete_requires_reason for item in items] == [True]


def _route_setup(db):
    tenant, _, following, fine = _setup(db)
    user = make_current_user(tenant.id, role="admin", user_id=make_app_user(db, email="a@example.com", tenant_id=tenant.id).id)
    db.refresh(fine)
    db.refresh(following)
    return user, following, fine


def test_route_maps_missing_reason_to_422(db):
    # Die Route rollt danach zurück (im Test bis zum Testbeginn), daher eigener Test.
    user, _, fine = _route_setup(db)

    with pytest.raises(HTTPException) as exc:
        fine_routes.delete_fine(fine.public_id, payload=None, db=db, user=user)
    assert exc.value.status_code == 422


def test_route_deletes_with_reason_in_the_given_protocol(db):
    user, following, fine = _route_setup(db)

    fine_routes.delete_fine(
        fine.public_id, payload=DeleteFinePayload(reason="Krank gemeldet", protocol_id=following.public_id), db=db, user=user,
    )
    row = db.get(AttendanceFine, fine.id)
    assert (row.status, row.closed_in_protocol_id) == ("deleted", following.id)


def test_export_lists_the_deletion_with_reason_in_the_deleting_protocol(db):
    tenant, _, following, fine = _setup(db)
    FinesRepository().delete_fine(db, fine.id, tenant.id, reason="Doppelt erfasst", protocol_context_id=following.id)

    table = protocol_fines(BuildContext(db=db, tenant_id=tenant.id, language="de"), following)

    status = table.groups[0].rows[0].cells[3]
    assert (status.status, status.v) == ("fineStatus.deleted", "P-A: Doppelt erfasst")
    assert table.groups[0].rows[0].cells[2].strike is True
    # Gelöschte Bussen zählen nicht zur Summe.
    assert table.totals[2].v == ""
