"""Aus der Vorlage vorbefuellte Formularzeilen/Matrixzellen speichern Teilnehmer als
interne ints, der Editor vergleicht aber mit public UUIDs - ohne Uebersetzung zeigte er
nur "N ausgewaehlt" statt der Namen (bug found 2026-10-05)."""
from __future__ import annotations

from datetime import date

from app.documents.context import BuildContext
from app.documents.providers.lists import form_row_value
from app.documents.providers.protocol import _single_value
from app.api.routes.protocol_elements import _block_to_read
from app.services.snapshot_reference_ids import (
    participant_display_names,
    normalize_attendance_entries,
    normalize_list_snapshot_refs,
    translate_list_snapshot_refs,
    translate_participant_refs,
)
from app.services.tenant_transfer_common import remap_block_configuration
from tests.factories import (
    make_event,
    make_finance_account,
    make_list_definition,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
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

    value = form_row_value(
        BuildContext(db=db, tenant_id=tenant.id, language="de"),
        {"value_type": "participants", "participant_ids": [anna.id, str(ben.public_id), "kaputt"]},
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
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=protocol)

    def cell_value(value_type, cell):
        nodes = _single_value(ctx, protocol, value_type, cell, {}, {})
        return "".join(span.v for node in nodes for span in node.c if hasattr(span, "v"))

    assert cell_value("participant", {"participant_id": str(anna.public_id)}) == "Anna"
    assert cell_value("participants", {"participant_ids": [str(anna.public_id)]}) == "Anna"
    assert "04.07.2026" in cell_value("event", {"event_id": str(event.public_id)})
    assert "04.07.2026" in cell_value("event", {"event_id": event.id})
    assert cell_value("event", {"event_id": str(foreign_event.public_id)}) == ""
    assert cell_value("event", {"event_id": "kaputt"}) == ""


def test_export_form_row_resolves_public_event_ref(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Sommerlager")

    value = form_row_value(BuildContext(db=db, tenant_id=tenant.id, language="de"), {"value_type": "event", "event_id": str(event.public_id)})

    assert value.endswith("Sommerlager")


def test_ref_to_internal_id_accepts_int_digit_string_and_tenant_scoped_uuid(db):
    tenant = make_tenant(db)
    other = make_tenant(db, name="Fremd")
    definition = make_list_definition(db, tenant.id)
    foreign_account = make_finance_account(db, other.id)
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de")
    resolve = ctx.ref_to_internal_id

    assert resolve(type(definition), definition.id) == definition.id
    assert resolve(type(definition), str(definition.id)) == definition.id
    assert resolve(type(definition), str(definition.public_id)) == definition.id
    assert resolve(type(foreign_account), str(foreign_account.public_id)) is None
    assert resolve(type(definition), None) is None
    assert resolve(type(definition), "kaputt") is None
    # Interne ints fremder Mandanten liefert erst entity_by_ref nicht aus
    assert ctx.entity_by_ref(type(foreign_account), foreign_account.id) is None


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


def _list_snapshot(person, people, event, *, types=("participant", "participants")):
    return {
        "synced_version": 1,
        "column_one_value_type": "text",
        "column_two_value_type": types[0],
        "entries": [
            {"id": 1, "sort_index": 10, "column_one_value": {"text_value": "Karo"}, "column_two_value": {"participant_id": person}},
            {
                "id": 2, "sort_index": 20, "column_one_value": {"text_value": "Bati"}, "column_two_value": {"participant_id": person},
                "_tracked": "changed", "_tracked_before": {"column_one_value": {"text_value": "Bati"}, "column_two_value": {"participant_id": person}},
            },
        ],
        "previous": {
            "column_one_value_type": types[1],
            "column_two_value_type": "event",
            "entries": [{"id": 1, "column_one_value": {"participant_ids": people}, "column_two_value": {"event_id": event}}],
        },
    }


def test_translates_list_snapshot_refs_and_back(db):
    """Gekoppelte Liste im Protokoll: der eingefrorene Snapshot hielt interne ids, der Editor
    verwarf sie - Spalte «Verantwortlich» leer, Gruppierung alles in «Ohne Wert» (Bug 2026-11-08)."""
    tenant = make_tenant(db)
    anna = make_participant(db, tenant.id, display_name="Anna")
    ben = make_participant(db, tenant.id, display_name="Ben")
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 4))
    foreign = make_participant(db, make_tenant(db, name="Fremd").id, display_name="Fremd")
    stored = {
        "linked_list_id": 1,
        "list_snapshot": _list_snapshot(anna.id, [anna.id, ben.id, foreign.id], event.id),
        "rows": [{"id": "r1", "value_type": "list_entry", "list_snapshot": {
            "entry_exists": True, "column_one_value_type": "participant", "column_two_value_type": "text",
            "column_one_value": {"participant_id": ben.id}, "column_two_value": {"text_value": "x"},
        }}],
    }

    public = translate_list_snapshot_refs(db, stored, tenant.id)

    entries = public["list_snapshot"]["entries"]
    assert entries[0]["column_two_value"] == {"participant_id": str(anna.public_id)}
    assert entries[1]["_tracked_before"]["column_two_value"] == {"participant_id": str(anna.public_id)}
    previous = public["list_snapshot"]["previous"]["entries"][0]
    assert previous["column_one_value"] == {"participant_ids": [str(anna.public_id), str(ben.public_id)]}
    assert previous["column_two_value"] == {"event_id": str(event.public_id)}
    assert public["rows"][0]["list_snapshot"]["column_one_value"] == {"participant_id": str(ben.public_id)}
    assert entries[0]["column_one_value"] == {"text_value": "Karo"}
    # Gespeicherter Stand bleibt unveraendert
    assert stored["list_snapshot"]["entries"][0]["column_two_value"] == {"participant_id": anna.id}

    back = normalize_list_snapshot_refs(db, public, tenant.id)

    assert back["list_snapshot"]["entries"] == stored["list_snapshot"]["entries"]
    assert back["list_snapshot"]["previous"]["entries"][0]["column_one_value"] == {"participant_ids": [anna.id, ben.id]}
    assert back["list_snapshot"]["previous"]["entries"][0]["column_two_value"] == {"event_id": event.id}
    assert back["rows"] == stored["rows"]


def test_normalize_list_snapshot_keeps_foreign_and_invalid_refs(db):
    tenant = make_tenant(db)
    foreign = make_participant(db, make_tenant(db, name="Fremd").id, display_name="Fremd")
    config = {"list_snapshot": _list_snapshot(str(foreign.public_id), ["kaputt"], None)}

    result = normalize_list_snapshot_refs(db, config, tenant.id)

    assert result["list_snapshot"]["entries"][0]["column_two_value"] == {"participant_id": str(foreign.public_id)}
    assert result["list_snapshot"]["previous"]["entries"][0]["column_one_value"] == {"participant_ids": ["kaputt"]}


def test_block_read_returns_public_ids_in_list_snapshot(db):
    tenant = make_tenant(db)
    anna = make_participant(db, tenant.id, display_name="Anna")
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id)
    block = make_protocol_element_block(
        db,
        make_protocol_element(db, protocol.id).id,
        configuration_snapshot_json={"list_snapshot": _list_snapshot(anna.id, [anna.id], None)},
    )

    read = _block_to_read(db, block)

    assert read.configuration_snapshot_json["list_snapshot"]["entries"][0]["column_two_value"] == {"participant_id": str(anna.public_id)}


def test_participant_display_names_cover_ints_uuids_and_stay_in_tenant(db):
    """Namen für jede referenzierte Person des Mandanten, damit der Editor nicht «N ausgewählt»
    zeigt, wenn sie in Vorlage und Verzeichnis fehlt; fremde Personen bleiben namenlos."""
    tenant = make_tenant(db, "Namen")
    other = make_tenant(db, "Fremd")
    alice = make_participant(db, tenant.id, "Alice")
    bob = make_participant(db, tenant.id, "Bob")
    carol = make_participant(db, tenant.id, "Carol")
    stranger = make_participant(db, other.id, "Fremd")
    config = {
        "rows": [
            {"id": "r1", "participant_ids": [alice.id, str(bob.public_id), stranger.id, str(stranger.public_id)]},
            {"id": "r2", "participant_id": str(carol.id)},
        ],
    }

    names = participant_display_names(db, config, tenant.id)

    assert names == {str(alice.id): "Alice", str(bob.public_id): "Bob", str(carol.id): "Carol"}


def test_translates_template_event_refs_in_form_rows_and_matrix(db):
    """Aus der Vorlage vorbelegte Termine (Formularzeile, Matrixzeile/-zelle) standen als interne
    Zahl im Block und erschienen im Editor leer."""
    tenant = make_tenant(db)
    other = make_tenant(db)
    event = make_event(db, tenant.id, title="Sola")
    foreign = make_event(db, other.id, title="Fremd")
    config = {
        "rows": [{"id": "r1", "value_type": "event", "event_id": event.id}, {"id": "r2", "template_event_id": event.id}],
        "columns": [{"id": "c1", "row_values": {"r2": {"event_id": event.id}, "r3": {"event_id": foreign.id}}}],
    }

    result = translate_participant_refs(db, config, tenant.id)

    assert result["rows"][0]["event_id"] == str(event.public_id)
    assert result["rows"][1]["template_event_id"] == str(event.public_id)
    assert result["columns"][0]["row_values"]["r2"]["event_id"] == str(event.public_id)
    assert result["columns"][0]["row_values"]["r3"]["event_id"] is None  # fremder Mandant


def test_public_reference_ids_cover_linked_list_entries(db):
    from tests.factories import make_list_entry
    from app.services.snapshot_reference_ids import snapshot_reference_ids

    tenant = make_tenant(db)
    other = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id)
    foreign_entry = make_list_entry(db, make_list_definition(db, other.id).id)
    config = {"rows": [{"linked_list_id": definition.id, "linked_list_entry_id": entry.id}, {"linked_list_entry_id": foreign_entry.id}]}

    refs = snapshot_reference_ids(db, config, tenant.id)

    assert refs["list_entries"] == {str(entry.id): str(entry.public_id)}
