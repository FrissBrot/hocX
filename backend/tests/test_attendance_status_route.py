"""Regression test for the attendance-check lost-update bug reported by a user: ticking off
one participant's attendance status in the protocol editor could silently erase another
participant's status that had just been saved. Root cause: the attendance block's buttons
used to save by PATCHing the *entire* configuration_snapshot_json with a locally-held copy
of attendance_entries (frontend/components/protocol/focused-element-editor.tsx::
handleAttendanceChange via saveBlockConfiguration) - if a second click's local snapshot was
taken before a first click's response/re-render had landed (the same person clicking through
the list fast, or two people taking attendance together), the second save's full-array
overwrite discarded the first click's change server-side.

Fix: POST /protocol-element-blocks/{id}/attendance/{participant_id} (set_block_attendance_
status / ProtocolElementService.set_attendance_status) reads the block fresh and merges only
the one participant's entry, so two overlapping saves for different participants can never
clobber each other regardless of what either client had cached locally."""
import pytest
from fastapi import HTTPException

from app.api.routes import protocol_elements
from app.schemas.protocol import AttendanceStatusUpdate
from tests.factories import (
    make_current_user,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def _setup(db, *, status="geplant"):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status=status)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="attendance")
    participant_a = make_participant(db, tenant.id, "Anna Muster")
    participant_b = make_participant(db, tenant.id, "Bruno Beispiel")
    user = make_current_user(tenant.id)
    return tenant, protocol, block, participant_a, participant_b, user


def test_set_attendance_status_creates_first_entry(db, monkeypatch):
    tenant, protocol, block, participant_a, _participant_b, user = _setup(db)
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)

    result = protocol_elements.set_block_attendance_status(
        block.public_id, participant_a.public_id, AttendanceStatusUpdate(status="present"), db=db, user=user
    )

    entries = result.configuration_snapshot_json["attendance_entries"]
    # Translated to the public id here (see snapshot_reference_ids.translate_attendance_entries) -
    # the client only ever knows participants by their public id, never the internal one stored
    # in the DB-side attendance_entries array.
    assert entries == [{"participant_id": str(participant_a.public_id), "participant_name": "Anna Muster", "status": "present"}]


def test_set_attendance_status_does_not_erase_other_participants_entry(db, monkeypatch):
    """The actual regression: saving participant B's status must never discard participant
    A's already-saved status, even though both calls start from a block that (before this
    fix) only the client tracked as a single in-memory array."""
    tenant, protocol, block, participant_a, participant_b, user = _setup(db)
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)

    protocol_elements.set_block_attendance_status(
        block.public_id, participant_a.public_id, AttendanceStatusUpdate(status="present"), db=db, user=user
    )
    result = protocol_elements.set_block_attendance_status(
        block.public_id, participant_b.public_id, AttendanceStatusUpdate(status="late"), db=db, user=user
    )

    entries = {entry["participant_id"]: entry["status"] for entry in result.configuration_snapshot_json["attendance_entries"]}
    assert entries == {str(participant_a.public_id): "present", str(participant_b.public_id): "late"}


def test_set_attendance_status_can_update_an_existing_entry(db, monkeypatch):
    tenant, protocol, block, participant_a, participant_b, user = _setup(db)
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)
    protocol_elements.set_block_attendance_status(
        block.public_id, participant_a.public_id, AttendanceStatusUpdate(status="present"), db=db, user=user
    )

    result = protocol_elements.set_block_attendance_status(
        block.public_id, participant_a.public_id, AttendanceStatusUpdate(status="excused"), db=db, user=user
    )

    entries = result.configuration_snapshot_json["attendance_entries"]
    assert entries == [{"participant_id": str(participant_a.public_id), "participant_name": "Anna Muster", "status": "excused"}]


def test_set_attendance_status_blocked_when_frozen(db, monkeypatch):
    tenant, protocol, block, participant_a, _participant_b, user = _setup(db, status="abgeschlossen")
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)

    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.set_block_attendance_status(
            block.public_id, participant_a.public_id, AttendanceStatusUpdate(status="present"), db=db, user=user
        )

    assert exc_info.value.status_code == 409
