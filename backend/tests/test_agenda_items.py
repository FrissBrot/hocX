"""Anliegen (agenda_item, Migration 0153): Zielprotokoll, Binden beim Durchführen, Vertagen,
Einfrieren, Editor-Erstellung, Mandantentrennung und PDF-Export."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.api.routes import agenda_items as route
from app.models.entities import AgendaItem
from app.schemas.agenda import (
    AgendaItemCreate,
    AgendaItemPostpone,
    AgendaItemUpdate,
    AgendaSchedule,
    AgendaTemplatePreference,
    ProtocolAgendaItemCreate,
)
from app.schemas.protocol import ProtocolUpdate
from app.services.agenda_item_service import AgendaItemService, Schedule
from app.services.protocol_service import ProtocolService

from tests.factories import (
    make_app_user,
    make_current_user,
    make_element_definition,
    make_protocol,
    make_protocol_element,
    make_template,
    make_template_element,
    make_tenant,
)

service = AgendaItemService()
TODAY = date.today()


def _setup(db, name="Anliegen"):
    tenant = make_tenant(db, f"Tenant {name}")
    template = make_template(db, tenant.id, f"Vorstand {name}")
    definition = make_element_definition(db, tenant.id, "Punkt", [])
    finances = make_template_element(db, template.id, definition.id, 0, "Finanzen")
    various = make_template_element(db, template.id, definition.id, 1, "Varia")
    user = make_app_user(db, email=f"{name.lower()}@example.com", tenant_id=tenant.id, role_code="writer")
    writer = make_current_user(tenant.id, user_id=user.id)
    return tenant, template, finances, various, writer


def _protocol(db, tenant, template, number, days, status="geplant", points=()):
    protocol = make_protocol(db, tenant.id, template.id, protocol_number=number, protocol_date=TODAY + timedelta(days=days), status=status)
    elements = []
    for index, point in enumerate(points):
        element = make_protocol_element(db, protocol.id, sort_index=index, section_name=point.section_name)
        element.template_element_id = point.id
        elements.append(element)
    db.flush()
    return protocol, elements


def _create(db, writer, template, point, title="Neue Kasse", schedule=None):
    return route.create_agenda_item(
        AgendaItemCreate(template_id=template.public_id, template_element_id=point.public_id if point else None,
                         title=title, body="Die alte ist kaputt.", schedule=schedule or AgendaSchedule()),
        db=db, user=writer,
    )


def test_next_meeting_item_appears_in_earliest_open_protocol_under_its_point(db):
    tenant, template, finances, various, writer = _setup(db, "Next")
    _protocol(db, tenant, template, "P-past", -7, points=[finances])  # vor dem Erstellen: nie
    _protocol(db, tenant, template, "P-done", 0, status="durchgeführt", points=[finances])
    first, first_elements = _protocol(db, tenant, template, "P-1", 3, points=[finances, various])
    second, _ = _protocol(db, tenant, template, "P-2", 10, points=[finances])

    created = _create(db, writer, template, finances)

    assert created.state == "scheduled"
    assert created.protocol.protocol_number == "P-1"
    assert created.created_by_name == "Test User"
    in_first = route.list_protocol_agenda_items(first.public_id, db=db, user=writer)
    assert [(item.title, item.protocol_element_id) for item in in_first] == [("Neue Kasse", first_elements[0].public_id)]
    assert route.list_protocol_agenda_items(second.public_id, db=db, user=writer) == []


def test_month_item_waits_until_that_month(db):
    tenant, template, finances, _, writer = _setup(db, "Month")
    _protocol(db, tenant, template, "P-now", 1, points=[finances])
    later_month = (TODAY.replace(day=1) + timedelta(days=95)).replace(day=1)
    later, _ = _protocol(db, tenant, template, "P-later", (later_month - TODAY).days + 2, points=[finances])

    created = _create(db, writer, template, finances, schedule=AgendaSchedule(kind="month", month=later_month + timedelta(days=9)))

    assert created.scheduled_month == later_month
    assert created.earliest_date == later_month
    assert created.protocol.protocol_number == "P-later"
    assert [item.title for item in route.list_protocol_agenda_items(later.public_id, db=db, user=writer)] == ["Neue Kasse"]


def test_waiting_without_protocol_and_point_fallback(db):
    tenant, template, finances, _, writer = _setup(db, "Wait")
    created = _create(db, writer, template, finances)
    assert created.state == "waiting"
    assert created.protocol is None

    # Protokoll ohne den Punkt: Anliegen erscheint, aber ohne Element (Abschnitt «Weitere Anliegen»)
    protocol, _ = _protocol(db, tenant, template, "P-1", 2, points=[])
    items = route.list_protocol_agenda_items(protocol.public_id, db=db, user=writer)
    assert [(item.title, item.protocol_element_id) for item in items] == [("Neue Kasse", None)]


def test_conducting_binds_and_next_protocol_no_longer_shows_it(db):
    tenant, template, finances, _, writer = _setup(db, "Bind")
    first, elements = _protocol(db, tenant, template, "P-1", 1, status="vorbereitet", points=[finances])
    second, _ = _protocol(db, tenant, template, "P-2", 8, points=[finances])
    created = _create(db, writer, template, finances)

    ProtocolService().update_protocol(db, first.id, ProtocolUpdate(status="durchgeführt"))

    item = db.get(AgendaItem, service.list_for_tenant(db, tenant.id)[0].id)
    assert item.protocol_id == first.id
    assert item.protocol_element_id == elements[0].id
    assert route.list_protocol_agenda_items(second.public_id, db=db, user=writer) == []
    listed = route.list_agenda_items(db=db, user=writer)
    assert listed[0].id == created.id and listed[0].state == "treated" and listed[0].is_bound


def test_postpone_to_next_meeting_moves_to_following_protocol(db):
    tenant, template, finances, _, writer = _setup(db, "Postpone")
    first, _ = _protocol(db, tenant, template, "P-1", 0, points=[finances])
    second, _ = _protocol(db, tenant, template, "P-2", 7, points=[finances])
    created = _create(db, writer, template, finances)
    assert created.protocol.protocol_number == "P-1"

    moved = route.postpone_agenda_item(created.id, AgendaItemPostpone(schedule=AgendaSchedule()), db=db, user=writer)

    assert moved.protocol.protocol_number == "P-2"
    assert moved.postponed_count == 1
    assert moved.earliest_date == first.protocol_date + timedelta(days=1)
    assert route.list_protocol_agenda_items(first.public_id, db=db, user=writer) == []
    assert len(route.list_protocol_agenda_items(second.public_id, db=db, user=writer)) == 1


def test_postpone_bound_item_from_editor_unbinds_it(db):
    tenant, template, finances, _, writer = _setup(db, "Unbind")
    first, elements = _protocol(db, tenant, template, "P-1", 0, status="durchgeführt", points=[finances])
    second, _ = _protocol(db, tenant, template, "P-2", 14, points=[finances])
    in_editor = route.create_protocol_agenda_item(
        first.public_id, ProtocolAgendaItemCreate(title="Spontan", protocol_element_id=elements[0].public_id), db=db, user=writer,
    )
    assert in_editor.protocol_element_id == elements[0].public_id

    route.postpone_agenda_item(in_editor.id, AgendaItemPostpone(schedule=AgendaSchedule()), db=db, user=writer)

    assert route.list_protocol_agenda_items(first.public_id, db=db, user=writer) == []
    assert [item.title for item in route.list_protocol_agenda_items(second.public_id, db=db, user=writer)] == ["Spontan"]


def test_items_of_closed_protocol_are_frozen(db):
    tenant, template, finances, _, writer = _setup(db, "Frozen")
    protocol, elements = _protocol(db, tenant, template, "P-1", 0, status="durchgeführt", points=[finances])
    item = route.create_protocol_agenda_item(protocol.public_id, ProtocolAgendaItemCreate(title="Fix"), db=db, user=writer)
    protocol.status = "abgeschlossen"
    db.flush()

    for call in (
        lambda: route.update_agenda_item(item.id, AgendaItemUpdate(title="Neu"), db=db, user=writer),
        lambda: route.postpone_agenda_item(item.id, AgendaItemPostpone(schedule=AgendaSchedule()), db=db, user=writer),
        lambda: route.delete_agenda_item(item.id, db=db, user=writer),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        route.create_protocol_agenda_item(protocol.public_id, ProtocolAgendaItemCreate(title="Zu spät"), db=db, user=writer)
    assert exc.value.status_code == 409
    assert route.list_protocol_agenda_items(protocol.public_id, db=db, user=writer)[0].can_edit is False


def test_edit_title_and_text_and_delete(db):
    tenant, template, finances, various, writer = _setup(db, "Edit")
    created = _create(db, writer, template, finances)

    updated = route.update_agenda_item(
        created.id, AgendaItemUpdate(title="Neue Kasse kaufen", body="", template_element_id=various.public_id), db=db, user=writer,
    )
    assert (updated.title, updated.body, updated.template_element_name) == ("Neue Kasse kaufen", None, "Varia")

    route.delete_agenda_item(created.id, db=db, user=writer)
    assert route.list_agenda_items(db=db, user=writer) == []


def test_point_of_other_template_and_foreign_tenant_rejected(db):
    tenant, template, finances, _, writer = _setup(db, "Own")
    other_tenant, other_template, other_point, _, other_writer = _setup(db, "Foreign")

    with pytest.raises(HTTPException) as exc:
        _create(db, writer, template, other_point)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _create(db, writer, other_template, other_point)
    assert exc.value.status_code == 404

    foreign = _create(db, other_writer, other_template, other_point)
    for call in (
        lambda: route.update_agenda_item(foreign.id, AgendaItemUpdate(title="x"), db=db, user=writer),
        lambda: route.delete_agenda_item(foreign.id, db=db, user=writer),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404
    assert route.list_agenda_items(db=db, user=writer) == []
    foreign_protocol, _ = _protocol(db, other_tenant, other_template, "F-1", 1)
    with pytest.raises(HTTPException) as exc:
        route.list_protocol_agenda_items(foreign_protocol.public_id, db=db, user=writer)
    assert exc.value.status_code == 404


def test_readers_can_list_but_not_write(db):
    tenant, template, finances, _, writer = _setup(db, "Reader")
    created = _create(db, writer, template, finances)
    reader = make_current_user(tenant.id, role="reader")

    assert [item.id for item in route.list_agenda_items(db=db, user=reader)] == [created.id]
    with pytest.raises(HTTPException) as exc:
        route.update_agenda_item(created.id, AgendaItemUpdate(title="x"), db=db, user=reader)
    assert exc.value.status_code == 403


def test_template_preference_round_trip(db):
    tenant, template, _, _, writer = _setup(db, "Pref")
    assert route.get_agenda_template_preference(db=db, user=writer).get("template_id") is None
    route.save_agenda_template_preference(AgendaTemplatePreference(template_id=template.public_id), db=db, user=writer)
    assert route.get_agenda_template_preference(db=db, user=writer) == {"template_id": template.public_id}

    options = route.list_agenda_templates(db=db, user=writer)
    assert [(option.name if hasattr(option, "name") else option["name"]) for option in options] == [template.name]
    points = options[0]["points"]
    assert [point["name"] for point in points] == ["Finanzen", "Varia"]


def test_month_in_past_is_clamped_to_today(db):
    _, template, finances, _, _ = _setup(db, "Clamp")
    item = service.create(
        db, tenant_id=template.tenant_id, template=template, template_element_id=finances.id, title="x", body=None,
        schedule=Schedule(kind="month", month=date(2020, 5, 1)), created_by=None, today=date(2026, 10, 24),
    )
    assert item.scheduled_month == date(2020, 5, 1)
    assert item.earliest_date == date(2026, 10, 24)


def test_pdf_lists_items_under_their_point(db):
    from app.documents.context import BuildContext
    from app.documents.providers.protocol import element_blocks

    tenant, template, finances, _, writer = _setup(db, "Pdf")
    protocol, _ = _protocol(db, tenant, template, "P-1", 1, points=[finances])
    _create(db, writer, template, finances, title="Neue Kasse")
    _create(db, writer, template, None, title="Ohne Punkt")

    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=protocol)
    elements = element_blocks(ctx, protocol)

    texts = [[span.v for paragraph in child.content for span in getattr(paragraph, "c", [])] for child in elements[0].children]
    assert ["Neue Kasse", "Die alte ist kaputt."] in texts
    assert elements[-1].title_key == "label.agendaOther"
    assert elements[-1].children[0].content[0].c[0].v == "Ohne Punkt"


def test_readers_only_see_protocols_they_may_open(db):
    tenant, template, finances, _, writer = _setup(db, "Visibility")
    _protocol(db, tenant, template, "P-1", 2, points=[finances])
    _create(db, writer, template, finances)

    reader = make_current_user(tenant.id, role="reader")
    listed = route.list_agenda_items(db=db, user=reader)
    # Unbeschränkte Leser sehen nur abgeschlossene Protokolle - das geplante bleibt verborgen.
    assert listed[0].state == "scheduled"
    assert listed[0].protocol is None
    assert route.list_agenda_items(db=db, user=writer)[0].protocol.protocol_number == "P-1"
