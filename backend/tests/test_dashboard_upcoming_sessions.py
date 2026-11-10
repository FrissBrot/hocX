"""Dashboard: nur zukünftige offene Sitzungen, je Protokoll eigene Anwesenheit."""
from datetime import datetime, date
from unittest.mock import patch

from app.repositories.protocol_repository import ProtocolRepository
from app.services.protocol_service import ProtocolService
from tests.factories import (
    make_tenant, make_template, make_protocol, make_participant,
    make_template_participant, make_protocol_element, make_protocol_element_block,
)


def test_upcoming_sessions_filter_and_order_across_templates(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    other_template = make_template(db, tenant.id)
    past = make_protocol(db, tenant.id, template.id, protocol_number="past", protocol_date=date(2026, 10, 4))
    later = make_protocol(db, tenant.id, other_template.id, protocol_number="later", protocol_date=date(2027, 1, 1))
    today = make_protocol(db, tenant.id, template.id, protocol_number="today", protocol_date=date(2026, 10, 11))
    closed = make_protocol(db, tenant.id, template.id, protocol_number="closed", protocol_date=date(2026, 10, 12), status="abgeschlossen")
    make_protocol(db, tenant.id, template.id, protocol_number="conducted", protocol_date=date(2026, 10, 11), status="durchgeführt")
    other_tenant = make_tenant(db)
    other = make_protocol(db, other_tenant.id, make_template(db, other_tenant.id).id, protocol_number="today", protocol_date=date(2026, 10, 11))
    with patch("app.repositories.protocol_repository.datetime") as clock:
        clock.now.return_value = datetime(2026, 10, 11, 0, 30)
        repository = ProtocolRepository()
        assert [p.id for p in repository.upcoming_open(db, tenant_id=tenant.id)] == [today.id, later.id]
        assert [p.id for p in repository.upcoming_open(db, tenant_id=tenant.id, protocol_ids=[later.id])] == [later.id]
        assert repository.upcoming_open(db, tenant_id=tenant.id, protocol_ids=[]) == []
        assert str(clock.now.call_args.args[0]) == "Europe/Zurich"
        today.status = later.status = "abgeschlossen"
        db.flush()
        assert ProtocolService().get_next_session_attendance(db, tenant.id).protocol is None
        assert ProtocolService().get_upcoming_sessions_attendance(db, tenant.id) == []


def test_upcoming_attendance_and_excuses_are_separate_per_protocol(db):
    tenant = make_tenant(db)
    person = make_participant(db, tenant.id, "Teilnehmer")
    blocks = []
    protocols = []
    for index in range(2):
        template = make_template(db, tenant.id)
        make_template_participant(db, template.id, person.id)
        protocol = make_protocol(db, tenant.id, template.id, protocol_number=f"P-{index}", protocol_date=date(2026, 10, 12 + index))
        protocols.append(protocol)
        blocks.append(make_protocol_element_block(db, make_protocol_element(db, protocol.id).id, {
            "attendance_entries": [{"participant_id": person.id, "participant_name": person.display_name, "status": "absent"}],
        }, element_type_code="attendance"))
    service = ProtocolService()
    with patch("app.repositories.protocol_repository.datetime") as clock:
        clock.now.return_value = datetime(2026, 10, 11)
        sessions = service.get_upcoming_sessions_attendance(db, tenant.id)
        assert [s.protocol.id for s in sessions] == [p.public_id for p in protocols]
        assert all(s.entries[0].participant_id == person.public_id for s in sessions)
        service.set_attendance_excused(db, protocols[1].id, person.id, True)
        sessions = service.get_upcoming_sessions_attendance(db, tenant.id)
        assert [s.entries[0].status for s in sessions] == ["absent", "excused"]
