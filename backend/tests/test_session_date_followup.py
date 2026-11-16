"""Block «Nächste Sitzung» im Folgeprotokoll: das Folgeprotokoll hängt am Sitzungs-Termin, den
das vorherige Protokoll als «nächste Sitzung» angelegt hat (template.next_event_id). Setzt das
Folgeprotokoll seinerseits die nächste Sitzung, darf es diesen - seinen eigenen - Termin nicht
verschieben, sondern muss einen neuen Termin anlegen."""
from datetime import date

from sqlalchemy import select

from app.models import Event, ProtocolElement, ProtocolElementBlock, Template
from app.schemas.protocol import ProtocolCreateFromTemplate
from app.services.protocol_element_service import ProtocolElementService
from app.services.protocol_service import ProtocolService
from tests.factories import (
    element_type_id,
    make_element_definition,
    make_event,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_template_element,
    make_tenant,
)


def _session_block(db, protocol, selected_date):
    element = make_protocol_element(db, protocol.id)
    return make_protocol_element_block(
        db,
        element.id,
        configuration_snapshot_json={"block_kind": "session_date", "selected_date": selected_date},
        element_type_code="session_date",
    )


def test_followup_protocol_does_not_move_its_own_session_event(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    service = ProtocolElementService()

    # Sitzung vom 01.12.: nächste Sitzung am 14.12.
    first = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2026, 12, 1))
    service._sync_session_date_marker(db, _session_block(db, first, "2026-12-14"))
    own_event_id = db.get(Template, template.id).next_event_id
    assert db.get(Event, own_event_id).event_date == date(2026, 12, 14)

    # Folgeprotokoll der Sitzung vom 14.12. hängt an diesem Termin (wie _maybe_auto_create_next_protocol).
    followup = make_protocol(db, tenant.id, template.id, protocol_number="P-2", protocol_date=date(2026, 12, 14))
    followup.event_id = own_event_id
    db.flush()

    # Dort wird die übernächste Sitzung gesetzt.
    service._sync_session_date_marker(db, _session_block(db, followup, "2027-01-11"))

    assert db.get(Event, own_event_id).event_date == date(2026, 12, 14)
    next_event_id = db.get(Template, template.id).next_event_id
    assert next_event_id != own_event_id
    assert db.get(Event, next_event_id).event_date == date(2027, 1, 11)


def _session_definition(db, tenant_id):
    block = {
        "id": 10, "title": "Nächste Sitzung", "description": None, "block_title": None,
        "default_content": "", "copy_from_last_protocol": False,
        "element_type_id": element_type_id(db, "session_date"), "render_type_id": 2,
        "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
        "sort_index": 10, "render_order": 10, "configuration_json": {"block_kind": "session_date"},
    }
    return make_element_definition(db, tenant_id, "Nächste Sitzung", blocks=[block])


def test_followup_protocol_does_not_prefill_its_own_date_as_next_session(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    definition = _session_definition(db, tenant.id)
    make_template_element(db, template.id, definition.id, sort_index=10, section_name="Nächste Sitzung")
    own_event = make_event(db, tenant.id, title="Hock", event_date=date(2026, 12, 14))
    template.next_event_id = own_event.id
    db.flush()

    protocol_id = ProtocolService().create_from_template(
        db,
        ProtocolCreateFromTemplate(
            template_id=template.public_id, protocol_number="P-2", protocol_date=own_event.event_date, event_id=own_event.public_id
        ),
        tenant_id=tenant.id,
        created_by=None,
    )
    config = db.scalar(
        select(ProtocolElementBlock.configuration_snapshot_json)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .where(ProtocolElement.protocol_id == protocol_id)
    )
    assert config["selected_date"] is None
    assert config["session_label"] == "Hock"
