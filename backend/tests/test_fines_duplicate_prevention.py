"""Regression test for M18 (2026-08-12 audit): find_existing_fine used to be dead code - it
was never called from create_fine, so a user (or a client-side race, e.g. two rapid
double-click requests) could create the same Busse for the same participant/protocol/type
any number of times. create_fine now checks for an existing fine first and raises
DuplicateFineError, which the route turns into a 409.
"""
from __future__ import annotations

import pytest

from app.repositories.fines_repository import DuplicateFineError, FinesRepository
from app.schemas.fines import AttendanceFineCreate

from tests.factories import make_finance_account, make_participant, make_protocol, make_template, make_tenant


def _setup(db):
    tenant = make_tenant(db, "Duplicate Fine Test Verein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-DUP")
    account = make_finance_account(db, tenant.id)
    return tenant, protocol, account


def test_create_fine_rejects_exact_duplicate_for_same_participant(db):
    repo = FinesRepository()
    tenant, protocol, account = _setup(db)
    participant = make_participant(db, tenant.id, display_name="Anna Muster")

    payload = AttendanceFineCreate(
        protocol_id=protocol.id,
        participant_id=participant.id,
        participant_name_snapshot=participant.display_name,
        fine_type="late",
        amount=5,
        account_id=account.id,
    )

    first = repo.create_fine(db, payload, tenant.id)
    assert first is not None

    with pytest.raises(DuplicateFineError):
        repo.create_fine(db, payload, tenant.id)


def test_create_fine_allows_different_fine_type_for_same_participant(db):
    repo = FinesRepository()
    tenant, protocol, account = _setup(db)
    participant = make_participant(db, tenant.id, display_name="Anna Muster")

    late_payload = AttendanceFineCreate(
        protocol_id=protocol.id,
        participant_id=participant.id,
        participant_name_snapshot=participant.display_name,
        fine_type="late",
        amount=5,
        account_id=account.id,
    )
    absent_payload = late_payload.model_copy(update={"fine_type": "absent", "amount": 10})

    assert repo.create_fine(db, late_payload, tenant.id) is not None
    # Different fine_type for the same participant/protocol is not a duplicate.
    assert repo.create_fine(db, absent_payload, tenant.id) is not None


def test_create_fine_allows_same_fine_type_for_different_participants(db):
    repo = FinesRepository()
    tenant, protocol, account = _setup(db)
    anna = make_participant(db, tenant.id, display_name="Anna Muster")
    bruno = make_participant(db, tenant.id, display_name="Bruno Beispiel")

    anna_payload = AttendanceFineCreate(
        protocol_id=protocol.id,
        participant_id=anna.id,
        participant_name_snapshot=anna.display_name,
        fine_type="late",
        amount=5,
        account_id=account.id,
    )
    bruno_payload = anna_payload.model_copy(update={"participant_id": bruno.id, "participant_name_snapshot": bruno.display_name})

    assert repo.create_fine(db, anna_payload, tenant.id) is not None
    # Same fine_type but a different participant is not a duplicate.
    assert repo.create_fine(db, bruno_payload, tenant.id) is not None


def test_create_fine_scopes_nameless_participant_duplicates_by_name_snapshot(db):
    """participant_id is optional (free-text entries, or later SET NULL when the linked
    participant is deleted) - the duplicate check must still distinguish two different
    people in that case instead of treating any same-type fine in the protocol as a dup."""
    repo = FinesRepository()
    tenant, protocol, account = _setup(db)

    anna_payload = AttendanceFineCreate(
        protocol_id=protocol.id,
        participant_id=None,
        participant_name_snapshot="Anna Muster",
        fine_type="late",
        amount=5,
        account_id=account.id,
    )
    bruno_payload = anna_payload.model_copy(update={"participant_name_snapshot": "Bruno Beispiel"})

    assert repo.create_fine(db, anna_payload, tenant.id) is not None
    assert repo.create_fine(db, bruno_payload, tenant.id) is not None

    with pytest.raises(DuplicateFineError):
        repo.create_fine(db, anna_payload, tenant.id)
