"""Nachträglich geänderte Mitgliedschaften müssen offene Protokolle erreichen."""
from datetime import date

from app.services.protocol_element_service import ProtocolElementService
from app.services.protocol_service import ProtocolService
from tests.factories import (
    make_participant, make_protocol, make_protocol_element, make_protocol_element_block,
    make_template, make_template_participant, make_tenant,
)


def _setup(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    leaver = make_participant(db, tenant.id, "Austritt")
    joiner = make_participant(db, tenant.id, "Eintritt")
    remaining = make_participant(db, tenant.id, "Bleibt")
    for person in (leaver, joiner, remaining):
        make_template_participant(db, template.id, person.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_date=date(2026, 8, 20))
    element = make_protocol_element(db, protocol.id)
    attendance = make_protocol_element_block(db, element.id, {
        "attendance_entries": [
            {"participant_id": leaver.id, "participant_name": leaver.display_name, "status": "present"},
            {"participant_id": remaining.id, "participant_name": remaining.display_name,
             "status": "excused", "note": "Erhalten"},
        ], "custom_setting": True,
    }, element_type_code="attendance")
    changes = make_protocol_element_block(db, element.id, {"entries": []},
                                          sort_index=1, element_type_code="entry_exit")
    leaver.left_at = date(2026, 8, 15)
    joiner.joined_at = date(2026, 8, 15)
    db.flush()
    return protocol, attendance, changes, leaver, joiner, remaining


def test_open_protocol_read_refreshes_late_membership_changes(db):
    protocol, attendance, changes, leaver, joiner, remaining = _setup(db)
    elements = ProtocolElementService().list_protocol_elements(db, protocol.id)
    config = next(b.configuration_snapshot_json for b in elements[0].blocks if b.element_type_code == "attendance")
    # list_protocol_elements translates attendance_entries to the public id for the API
    # boundary (see snapshot_reference_ids.translate_attendance_entries) - the stored/internal
    # id is only used for the refresh-by-membership merge itself, not in what callers read here.
    entries = {e["participant_id"]: e for e in config["attendance_entries"]}
    assert set(entries) == {str(joiner.public_id), str(remaining.public_id)}
    assert entries[str(remaining.public_id)]["status"] == "excused"
    assert entries[str(remaining.public_id)]["note"] == "Erhalten"
    assert entries[str(joiner.public_id)]["status"] == "absent"
    assert config["custom_setting"] is True
    assert {(e["participant_id"], e["type"], e["date"]) for e in changes.configuration_snapshot_json["entries"]} == {
        (leaver.id, "leave", "2026-08-15"), (joiner.id, "join", "2026-08-15"),
    }


def test_refresh_preserves_hidden_changes_and_is_idempotent(db):
    protocol, attendance, changes, *_ = _setup(db)
    service = ProtocolService()
    service.refresh_membership_blocks(db, protocol.id)
    config = dict(changes.configuration_snapshot_json)
    config["entries"] = [{**entry, "hidden": True} for entry in config["entries"]]
    changes.configuration_snapshot_json = config
    db.flush()
    service.refresh_membership_blocks(db, protocol.id)
    assert changes.configuration_snapshot_json == config


def test_frozen_protocol_keeps_original_membership_snapshots(db):
    protocol, attendance, changes, *_ = _setup(db)
    original = dict(attendance.configuration_snapshot_json)
    protocol.status = "abgeschlossen"
    db.flush()
    ProtocolElementService().list_protocol_elements(db, protocol.id)
    assert attendance.configuration_snapshot_json == original
    assert changes.configuration_snapshot_json == {"entries": []}


def test_refresh_uses_protocol_date_instead_of_today(db):
    protocol, attendance, changes, leaver, joiner, remaining = _setup(db)
    protocol.protocol_date = date(2026, 8, 14)
    db.flush()
    ProtocolService().refresh_membership_blocks(db, protocol.id)
    assert {e["participant_id"] for e in attendance.configuration_snapshot_json["attendance_entries"]} == {leaver.id, remaining.id}
    assert changes.configuration_snapshot_json["entries"] == []
    protocol.protocol_date = date(2026, 8, 20)
    db.flush()
    ProtocolService().refresh_membership_blocks(db, protocol.id)
    assert {e["participant_id"] for e in attendance.configuration_snapshot_json["attendance_entries"]} == {joiner.id, remaining.id}


def test_dashboard_attendance_refreshes_memberships(db):
    protocol, attendance, changes, leaver, joiner, remaining = _setup(db)
    result = ProtocolService().get_next_session_attendance(db, protocol.tenant_id)
    assert {entry.participant_id for entry in result.entries} == {joiner.public_id, remaining.public_id}


def test_closing_without_opening_refreshes_before_freezing(db, monkeypatch):
    from app.schemas.protocol import ProtocolUpdate

    protocol, attendance, changes, leaver, joiner, remaining = _setup(db)
    service = ProtocolService()
    monkeypatch.setattr(service, "_maybe_auto_create_next_protocol", lambda *args: None)
    service.update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))
    assert {e["participant_id"] for e in attendance.configuration_snapshot_json["attendance_entries"]} == {joiner.id, remaining.id}
    assert len(changes.configuration_snapshot_json["entries"]) == 2
    original = dict(attendance.configuration_snapshot_json)
    joiner.left_at = date(2026, 8, 16)
    db.flush()
    service.refresh_membership_blocks(db, protocol.id)
    assert attendance.configuration_snapshot_json == original


def test_export_refreshes_without_editor_read(db, tmp_path, monkeypatch):
    from app.services.export_service import ExportService

    protocol, attendance, changes, leaver, joiner, remaining = _setup(db)
    service = ExportService()
    rendered_configs = []

    def capture_block(db, block, *args):
        rendered_configs.append(block.configuration_snapshot_json)
        return "Test"

    monkeypatch.setattr(service, "_render_block", capture_block)
    service._render_protocol_body(db, protocol.id, tmp_path, protocol.tenant_id)
    assert attendance.configuration_snapshot_json in rendered_configs
    assert {e["participant_id"] for e in attendance.configuration_snapshot_json["attendance_entries"]} == {joiner.id, remaining.id}
    assert len(changes.configuration_snapshot_json["entries"]) == 2


def test_close_and_change_date_in_same_request_uses_new_date(db, monkeypatch):
    from app.schemas.protocol import ProtocolUpdate

    protocol, attendance, changes, leaver, joiner, remaining = _setup(db)
    service = ProtocolService()
    monkeypatch.setattr(service, "_maybe_auto_create_next_protocol", lambda *args: None)
    service.update_protocol(db, protocol.id, ProtocolUpdate(
        status="abgeschlossen", protocol_date=date(2026, 8, 14),
    ))
    assert {e["participant_id"] for e in attendance.configuration_snapshot_json["attendance_entries"]} == {leaver.id, remaining.id}
    assert changes.configuration_snapshot_json["entries"] == []
