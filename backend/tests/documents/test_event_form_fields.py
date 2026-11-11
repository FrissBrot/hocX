"""Formularblock «Pro Termin»: die mit dem Termin verknüpften Felder («aus Termin» im Editor, z. B.
Organisatoren, Leitungsteam) erscheinen im PDF (Rückmeldung 2026-11-11, «Scharanlässe»)."""

from __future__ import annotations

from app.documents.context import BuildContext
from app.documents.providers.protocol import element_blocks
from tests.factories import (
    make_event,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def test_linked_event_fields_are_exported(db):
    tenant = make_tenant(db, "Termin Felder Verein")
    gian, jan = make_participant(db, tenant.id, "Gian Inderbitzin"), make_participant(db, tenant.id, "Jan Grisiger")
    lino = make_participant(db, tenant.id, "Lino Enz")
    event = make_event(db, tenant.id, title="Bounce Lab")
    event.organizer_ids = [gian.id, jan.id]
    event.leadership_ids = [lino.id]
    event.spezial_text1 = "Bahnhof Sachseln"
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="EF-1")
    element = make_protocol_element(db, protocol.id, sort_index=0, section_name="Scharanlässe")
    config = {
        "repeat_source_type": "event", "repeat_source_id": event.id, "repeat_source_label": "Bounce Lab",
        "event_fields": [
            {"field": "organizer_ids", "label": ""},
            {"field": "leadership_ids", "label": "Leitungsteam"},
            {"field": "participant_ids", "label": "Wer geht"},  # leer: erscheint nicht
            {"field": "spezial_text1", "label": ""},
        ],
        "rows": [{"label": "Treffpunkt", "text_value": "0800 Bahnhof Sachseln"}],
    }
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json=config, element_type_code="form")
    block.title_snapshot = "Bounce Lab"
    # Spezial Text 1 hat im Verein einen eigenen Namen
    tenant.event_field_config_json = {"spezial_text1": {"label": "Treffort", "hidden": False}}
    db.flush()

    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=protocol)
    [section] = element_blocks(ctx, protocol)
    exported = str([child.model_dump() for child in section.children])

    assert "Organisatoren" in exported and "Gian Inderbitzin, Jan Grisiger" in exported
    assert "Leitungsteam" in exported and "Lino Enz" in exported
    assert "Treffort" in exported
    assert "Wer geht" not in exported
    assert "0800 Bahnhof Sachseln" in exported
    assert exported.index("Organisatoren") < exported.index("Treffpunkt")


def test_hidden_special_field_and_foreign_event_are_not_exported(db):
    tenant = make_tenant(db, "Termin Felder Verein 2")
    other = make_tenant(db, "Fremder Verein")
    foreign = make_event(db, other.id, title="Fremd")
    foreign.spezial_text2 = "Geheim"
    own = make_event(db, tenant.id, title="Eigen")
    own.spezial_text1 = "Versteckt"
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="EF-2")
    element = make_protocol_element(db, protocol.id, sort_index=0, section_name="Anlässe")
    for index, (event, field) in enumerate(((foreign, "spezial_text2"), (own, "spezial_text1"))):
        block = make_protocol_element_block(
            db, element.id, sort_index=index, element_type_code="form",
            configuration_snapshot_json={"repeat_source_type": "event", "repeat_source_id": event.id, "event_fields": [{"field": field, "label": "Feld"}], "rows": []},
        )
        block.title_snapshot = event.title
    tenant.event_field_config_json = {"spezial_text1": {"label": "", "hidden": True}}
    db.flush()

    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=protocol)
    exported = str([child.model_dump() for child in element_blocks(ctx, protocol)[0].children])
    assert "Geheim" not in exported and "Versteckt" not in exported
