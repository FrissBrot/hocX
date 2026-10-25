"""Block «Nächste Sitzung»: Uhrzeit (selected_time) wird mit dem Datum im Termin gespeichert,
im PDF angezeigt und ist optional (leer/ungültig = ganztägig)."""
from datetime import time

from app.documents.providers.protocol import _session_date_text
from app.models import Event, Template
from app.services.element_config import parse_session_time
from app.services.protocol_element_service import ProtocolElementService
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template, make_tenant


def test_parse_session_time():
    assert parse_session_time("19:30") == time(19, 30)
    assert parse_session_time("07:05:42") == time(7, 5)
    assert parse_session_time("") is None
    assert parse_session_time(None) is None
    assert parse_session_time("abends") is None


def test_session_date_text_includes_time_only_with_a_date():
    assert _session_date_text({"selected_date": "2026-11-14", "selected_time": "19:30"}) == "14.11.2026, 19:30"
    assert _session_date_text({"selected_date": "2026-11-14"}) == "14.11.2026"
    assert _session_date_text({"selected_time": "19:30"}) == ""


def _session_block(db, config):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={"block_kind": "session_date", **config}, element_type_code="session_date")
    return template, block


def test_session_time_is_stored_on_the_next_event(db):
    template, block = _session_block(db, {"selected_date": "2026-11-14", "selected_time": "19:30"})
    service = ProtocolElementService()
    service._sync_session_date_marker(db, block)
    event = db.get(Event, db.get(Template, template.id).next_event_id)
    assert event.start_time == time(19, 30)

    block.configuration_snapshot_json = {**block.configuration_snapshot_json, "selected_time": None}
    service._sync_session_date_marker(db, block)
    db.refresh(event)
    assert event.start_time is None
