"""Verantwortliche aus einer Tabellenzeile folgen der Tabelle: der Protokoll-Editor beobachtet
die Tabellen hinter den Zuweisungen (collaboration_ws), und ein neues Protokoll übernimmt aus der
Vorlage den aktuellen Wert der Zeile statt der beim Zuweisen gespeicherten Person."""
from app.services.protocol_service import ProtocolService
from app.services.responsible_label_service import responsible_list_definition_ids
from tests.factories import (
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_template,
    make_tenant,
)


def test_responsible_list_ids_include_linked_lists_of_own_tenant_only(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    own_list = make_list_definition(db, tenant.id, column_one_value_type="participant", column_two_value_type="text")
    foreign_list = make_list_definition(db, other.id, column_one_value_type="participant", column_two_value_type="text")
    person = make_participant(db, tenant.id, display_name="Alice Muster")
    own_entry = make_list_entry(db, own_list.id, column_one_value={"participant_id": person.id})
    foreign_entry = make_list_entry(db, foreign_list.id, column_one_value={"participant_id": person.id})

    element = make_protocol_element(db, protocol.id, sort_index=0, section_name="Traktandum")
    element.responsible_assignments_snapshot = [
        {"participant_id": person.id, "list_definition_id": own_list.id, "list_entry_id": own_entry.id},
        {"participant_id": person.id, "list_definition_id": foreign_list.id, "list_entry_id": foreign_entry.id},
        {"participant_id": person.id},
    ]
    db.add(element)
    db.commit()

    assert responsible_list_definition_ids(db, protocol.id) == {own_list.id}


def test_template_label_reads_current_list_row(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id, column_one_value_type="participant", column_two_value_type="text")
    before = make_participant(db, tenant.id, display_name="Alice Muster")
    now = make_participant(db, tenant.id, display_name="Bob Beispiel")
    entry = make_list_entry(db, definition.id, column_one_value={"participant_id": now.id})
    manual = make_participant(db, tenant.id, display_name="Carla Fix")
    configuration = {
        "responsibility": {
            "name_display_mode": "display_name",
            "assignments": [
                # beim Zuweisen stand Alice in der Zeile, inzwischen Bob
                {"participant_id": before.id, "list_definition_id": definition.id, "list_entry_id": entry.id},
                {"participant_id": manual.id},
            ],
        }
    }

    label = ProtocolService()._template_element_responsible_label(db, configuration, tenant.id)

    assert label == "Bob Beispiel, Carla Fix"
