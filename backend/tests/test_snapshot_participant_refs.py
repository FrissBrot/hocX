"""Aus der Vorlage vorbefuellte Formularzeilen/Matrixzellen speichern Teilnehmer als
interne ints, der Editor vergleicht aber mit public UUIDs - ohne Uebersetzung zeigte er
nur "N ausgewaehlt" statt der Namen (bug found 2026-10-05)."""
from __future__ import annotations

from datetime import date

from app.services.export_service import ExportService
from app.services.snapshot_reference_ids import normalize_attendance_entries, translate_participant_refs
from app.services.tenant_transfer_common import remap_block_configuration
from tests.factories import (
    make_event,
    make_finance_account,
    make_list_definition,
    make_participant,
    make_protocol,
    make_template,
    make_tenant,
)


def test_translates_form_rows_and_matrix_cells_to_public_ids(db):
    tenant = make_tenant(db)
    anna = make_participant(db, tenant.id, display_name="Anna")
    ben = make_participant(db, tenant.id, display_name="Ben")
    other_tenant = make_tenant(db, name="Fremd")
    foreign = make_participant(db, other_tenant.id, display_name="Fremd")
    picked = "0190a000-0000-7000-8000-000000000001"

    config = {
        "rows": [
            {"id": "r1", "value_type": "participants", "participant_ids": [anna.id, picked, foreign.id]},
            {"id": "r2", "value_type": "participant", "participant_id": ben.id},
            {"id": "r3", "row_type": "participants", "template_participant_ids": [ben.id]},
        ],
        "columns": [{"id": "c1", "row_values": {"r3": {"participant_ids": [anna.id, ben.id]}}}],
    }

    result = translate_participant_refs(db, config, tenant.id)

    assert result["rows"][0]["participant_ids"] == [str(anna.public_id), picked]
    assert result["rows"][1]["participant_id"] == str(ben.public_id)
    assert result["rows"][2]["template_participant_ids"] == [str(ben.public_id)]
    assert result["columns"][0]["row_values"]["r3"]["participant_ids"] == [str(anna.public_id), str(ben.public_id)]
    # Original bleibt unveraendert (Snapshot wird nur fuer die Antwort uebersetzt).
    assert config["rows"][0]["participant_ids"] == [anna.id, picked, foreign.id]


def test_export_resolves_mixed_int_and_public_participant_refs(db):
    tenant = make_tenant(db)
    anna = make_participant(db, tenant.id, display_name="Anna")
    ben = make_participant(db, tenant.id, display_name="Ben")

    value = ExportService()._form_row_value(
        db, {"value_type": "participants", "participant_ids": [anna.id, str(ben.public_id), "kaputt"]}, tenant.id
    )

    assert value == "Anna, Ben"


def test_export_matrix_cells_resolve_public_participant_and_event_refs(db):
    """Im Editor gewaehlte Matrixzellen speichern Teilnehmer/Events als public UUID -
    int(participant_id)/int(event_id) crashte den PDF-Export mit "invalid literal for
    int() with base 10: '<uuid>'" (bug found 2026-10-05)."""
    tenant = make_tenant(db)
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id)
    anna = make_participant(db, tenant.id, display_name="Anna")
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 4))
    foreign_event = make_event(db, make_tenant(db, name="Fremd").id, title="Fremdlager", event_date=date(2026, 7, 4))
    service = ExportService()

    def cell_value(value_type, cell):
        return service._matrix_single_value(
            db, value_type=value_type, cell=cell, protocol=protocol, row={}, column={}, prefix=""
        )

    assert cell_value("participant", {"participant_id": str(anna.public_id)}) == "Anna"
    assert cell_value("participants", {"participant_ids": [str(anna.public_id)]}) == "Anna"
    assert "04.07.2026" in cell_value("event", {"event_id": str(event.public_id)})
    assert "04.07.2026" in cell_value("event", {"event_id": event.id})
    assert cell_value("event", {"event_id": str(foreign_event.public_id)}) == ""
    assert cell_value("event", {"event_id": "kaputt"}) == ""


def test_export_form_row_resolves_public_event_ref(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Sommerlager")

    value = ExportService()._form_row_value(db, {"value_type": "event", "event_id": str(event.public_id)}, tenant.id)

    assert value.endswith("Sommerlager")


def test_ref_to_internal_id_accepts_int_digit_string_and_tenant_scoped_uuid(db):
    tenant = make_tenant(db)
    other = make_tenant(db, name="Fremd")
    definition = make_list_definition(db, tenant.id)
    foreign_account = make_finance_account(db, other.id)
    resolve = ExportService._ref_to_internal_id

    assert resolve(db, type(definition), definition.id, tenant.id) == definition.id
    assert resolve(db, type(definition), str(definition.id), tenant.id) == definition.id
    assert resolve(db, type(definition), str(definition.public_id), tenant.id) == definition.id
    assert resolve(db, type(foreign_account), str(foreign_account.public_id), tenant.id) is None
    assert resolve(db, type(definition), None, tenant.id) is None
    assert resolve(db, type(definition), "kaputt", tenant.id) is None


def test_normalize_attendance_entries_maps_public_ids_back_to_internal(db):
    """Gegenstueck zu translate_attendance_entries: ein vom Client zurueckgespeicherter
    Snapshot darf keine UUIDs in der eigenstaendigen Anwesenheit hinterlassen."""
    tenant = make_tenant(db)
    anna = make_participant(db, tenant.id, display_name="Anna")
    ben = make_participant(db, tenant.id, display_name="Ben")
    foreign = make_participant(db, make_tenant(db, name="Fremd").id, display_name="Fremd")
    config = {
        "attendance_entries": [
            {"participant_id": str(anna.public_id), "status": "present"},
            {"participant_id": ben.id, "status": "late"},
            {"participant_id": str(foreign.public_id), "status": "absent"},
        ]
    }

    result = normalize_attendance_entries(db, config, tenant.id)

    assert [entry["participant_id"] for entry in result["attendance_entries"]] == [anna.id, ben.id, str(foreign.public_id)]
    assert config["attendance_entries"][0]["participant_id"] == str(anna.public_id)


def test_remap_block_configuration_keeps_public_id_refs():
    """Klonen/Import: im Editor gewaehlte (UUID-)Referenzen gingen beim Umschluesseln verloren."""
    anna_uuid = "0190a000-0000-7000-8000-000000000001"
    event_uuid = "0190a000-0000-7000-8000-000000000002"
    config = {
        "attendance_entries": [{"participant_id": anna_uuid, "status": "present"}],
        "rows": [{"id": "r1", "value_type": "event", "event_id": event_uuid, "participant_ids": [anna_uuid, 7]}],
        "columns": [{"id": "c1", "row_values": {"r1": {"participant_id": anna_uuid, "event_id": event_uuid}}}],
    }

    result = remap_block_configuration(
        config,
        participant_map={5: 105, 7: 107},
        event_map={9: 109},
        list_definition_map={},
        list_entry_map={},
        finance_account_map={},
        participant_public_ids={anna_uuid: 5},
        event_public_ids={event_uuid: 9},
    )

    assert result["attendance_entries"][0]["participant_id"] == 105
    assert result["rows"][0]["event_id"] == 109
    assert result["rows"][0]["participant_ids"] == [105, 107]
    assert result["columns"][0]["row_values"]["r1"] == {"participant_id": 105, "event_id": 109}
