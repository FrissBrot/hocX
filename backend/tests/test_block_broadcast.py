"""Live-Updates aus REST-Routen (Listen-Refresh/Sync/Undo, Anwesenheit): gleiche Form wie die
REST-Antwort - öffentliche Block-/Nutzer-ID, übersetzte Konfiguration, config_version."""

import json

from app.api.routes import protocol_elements
from tests.factories import make_current_user, make_participant, make_protocol, make_protocol_element, make_protocol_element_block, make_template, make_tenant


def test_attendance_broadcast_uses_public_ids_and_config_version(db, monkeypatch):
    sent = []
    monkeypatch.setattr(protocol_elements, "publish_best_effort", lambda channel, payload: sent.append(json.loads(payload)))
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="geplant")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="attendance")
    participant = make_participant(db, tenant.id, "Anna")
    user = make_current_user(tenant.id)

    from app.schemas.protocol import AttendanceStatusUpdate

    read = protocol_elements.set_block_attendance_status(
        block.public_id, participant.public_id, AttendanceStatusUpdate(status="present"), db=db, user=user
    )
    message = sent[-1]
    assert message["field_key"] == f"block-{block.public_id}"
    assert message["user_id"] == str(user.user_public_id)
    assert message["patch"]["config_version"] == read.config_version
    entries = message["patch"]["configuration_snapshot_json"]["attendance_entries"]
    assert entries[0]["participant_id"] == str(participant.public_id)  # keine interne ID
