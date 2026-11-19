"""Nachtlauf 2026-11-19 (Verdacht «Anwesenheits-IDs»): attendance_entries tragen intern die int-ID
der Person. Ein Block-PATCH konnte dort die interne ID einer Person eines anderen Mandanten setzen,
und das Lesen der Protokollelemente übersetzte sie ohne Mandantenfilter in deren public UUID
(nur RLS hielt das auf). Jetzt verwirft der PATCH fremde Ints und das Lesen übersetzt nur Personen
des Protokoll-Mandanten."""

from app.api.routes import protocol_elements
from app.models import ProtocolElementBlock
from app.schemas.protocol import ProtocolElementBlockUpdate
from tests.factories import (
    make_current_user,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def _setup(db):
    tenant = make_tenant(db, "Eigener Verein")
    foreign_tenant = make_tenant(db, "Fremder Verein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="geplant")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="attendance")
    own = make_participant(db, tenant.id, "Anna Eigen")
    foreign = make_participant(db, foreign_tenant.id, "Fritz Fremd")
    return protocol, block, own, foreign, make_current_user(tenant.id)


def _set_entries(db, block, entries):
    block.configuration_snapshot_json = {"attendance_entries": entries}
    db.flush()


def test_patch_drops_internal_id_of_a_foreign_participant(db, monkeypatch):
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)
    _protocol, block, own, foreign, user = _setup(db)

    result = protocol_elements.patch_protocol_element_block(
        block.public_id,
        ProtocolElementBlockUpdate(configuration_snapshot_json={"attendance_entries": [
            {"participant_id": foreign.id, "status": "present"},
            {"participant_id": str(own.public_id), "status": "late"},
        ]}),
        db=db,
        user=user,
    )

    returned = {str(entry["participant_id"]) for entry in result.configuration_snapshot_json["attendance_entries"]}
    assert str(foreign.public_id) not in returned
    db.expire_all()
    stored = db.get(ProtocolElementBlock, block.id).configuration_snapshot_json["attendance_entries"]
    assert [entry["participant_id"] for entry in stored] == [own.id]


def test_reading_never_translates_a_foreign_participant_id(db):
    """Altbestand (z. B. vor dem Fix gespeichert): die fremde ID bleibt unübersetzt."""
    protocol, block, own, foreign, user = _setup(db)
    # Abgeschlossen: kein Abgleich mit den Vorlagen-Personen beim Lesen (refresh_membership_blocks)
    protocol.status = "abgeschlossen"
    _set_entries(db, block, [
        {"participant_id": foreign.id, "status": "present"},
        {"participant_id": own.id, "status": "present"},
    ])

    elements = protocol_elements.list_protocol_elements(protocol.public_id, db=db, user=user)
    ids = {
        str(entry["participant_id"])
        for element in elements
        for read_block in element.blocks
        for entry in (read_block.configuration_snapshot_json or {}).get("attendance_entries", [])
    }
    assert str(own.public_id) in ids
    assert str(foreign.public_id) not in ids

    single = protocol_elements._block_to_read(db, db.get(ProtocolElementBlock, block.id))
    assert str(foreign.public_id) not in {str(e["participant_id"]) for e in single.configuration_snapshot_json["attendance_entries"]}


def test_patch_keeps_own_internal_ids_and_already_stored_entries(db, monkeypatch):
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)
    _protocol, block, own, _foreign, user = _setup(db)
    # Unübersetzbarer Altbestand (Person gelöscht o. ä.) kommt unverändert zurück und bleibt.
    _set_entries(db, block, [{"participant_id": 987654321, "status": "absent"}])

    protocol_elements.patch_protocol_element_block(
        block.public_id,
        ProtocolElementBlockUpdate(configuration_snapshot_json={"attendance_entries": [
            {"participant_id": 987654321, "status": "absent"},
            {"participant_id": own.id, "status": "present"},
        ]}),
        db=db,
        user=user,
    )

    db.expire_all()
    stored = db.get(ProtocolElementBlock, block.id).configuration_snapshot_json["attendance_entries"]
    assert [entry["participant_id"] for entry in stored] == [987654321, own.id]
