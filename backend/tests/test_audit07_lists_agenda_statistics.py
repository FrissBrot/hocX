"""Bereichs-Audit 07 (2026-11): Listen, Anliegen, Dokumentquellen, Statistik.

C2/C11 Listeneintrag löschen führt Abgabe-Todos nach, Sync best effort · C3 Gruppenquelle als
Listen-Markierung · C4 Schweizer «heute» bei Anliegen · C5 Fehler der PDF-Auftragsschleife in
system_error_log · C6 Sammelabruf der Listeneinträge · C7 Protokollauswahl für eingeschränkte
Leser · C9/U6 Statistik für eingeschränkte Leser und Zyklus · C10/U4 Löschsperre nennt
Fundstellen · C12 Audit beim Ändern eines Anliegens · C14 404 statt 403 · U2 übersetzte Meldungen."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.api.routes import agenda_items as agenda_route
from app.api.routes import documents as documents_route
from app.api.routes import lists as lists_route
from app.api.routes import templates as templates_route
from app.api.routes.statistics import get_statistics_overview
from app.models.entities import UserProtocolAccess, UserTemplateAccess
from app.schemas.agenda import AgendaItemCreate, AgendaItemUpdate, AgendaSchedule
from app.services import agenda_item_service as agenda_service_module
from app.services import document_render_jobs
from app.services.statistics_common import fetch_group_session_rows
from tests.factories import (
    make_app_user,
    make_current_user,
    make_element_definition,
    make_event,
    make_list_definition,
    make_list_entry,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_template_element,
    make_tenant,
)


def _restricted_reader(db, tenant_id: int, template_id: int, protocol_ids: list[int]):
    account = make_app_user(db, email=f"leser-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant_id)
    db.add(UserTemplateAccess(user_id=account.id, tenant_id=tenant_id, template_id=template_id))
    for protocol_id in protocol_ids:
        db.add(UserProtocolAccess(user_id=account.id, tenant_id=tenant_id, protocol_id=protocol_id))
    db.flush()
    return make_current_user(tenant_id, role="reader", user_id=account.id)


# ── Listen ───────────────────────────────────────────────────────────────


def test_delete_entry_syncs_submission_todos(db, monkeypatch):
    tenant = make_tenant(db, "Liste C2")
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "A"})
    calls = []
    monkeypatch.setattr(
        lists_route.submission_service, "sync_todos_for_list",
        lambda db_, *, tenant_id, list_definition_id: calls.append((tenant_id, list_definition_id)),
    )
    lists_route.delete_entry(entry.public_id, db=db, user=make_current_user(tenant.id))
    assert calls == [(tenant.id, definition.id)]


def test_entry_sync_failure_is_recorded_not_raised(db, monkeypatch):
    tenant = make_tenant(db, "Liste C11")
    definition = make_list_definition(db, tenant.id)
    recorded = []

    def boom(*args, **kwargs):
        raise RuntimeError("sync kaputt")

    monkeypatch.setattr(lists_route.submission_service, "sync_todos_for_list", boom)
    monkeypatch.setattr(lists_route, "record_system_error", lambda db_, *, exc, tenant_id=None: recorded.append((type(exc), tenant_id)))
    lists_route._sync_after_entry_change(db, tenant_id=tenant.id, list_definition_id=definition.id)
    assert recorded == [(RuntimeError, tenant.id)]


def test_entries_of_all_lists_in_one_call_and_tenant_scoped(db):
    tenant = make_tenant(db, "Liste C6")
    other = make_tenant(db, "Liste C6 fremd")
    first = make_list_definition(db, tenant.id, name="Eins")
    second = make_list_definition(db, tenant.id, name="Zwei")
    foreign = make_list_definition(db, other.id, name="Fremd")
    make_list_entry(db, first.id, sort_index=1, column_one_value={"text_value": "b"})
    make_list_entry(db, first.id, sort_index=0, column_one_value={"text_value": "a"})
    make_list_entry(db, foreign.id, column_one_value={"text_value": "x"})

    result = lists_route.list_all_entries(db=db, user=make_current_user(tenant.id))

    assert set(result) == {str(first.public_id), str(second.public_id)}
    assert [entry.column_one_value["text_value"] for entry in result[str(first.public_id)]] == ["a", "b"]
    assert result[str(second.public_id)] == []


def test_delete_linked_list_names_usages_without_prefix_false_positive(db):
    tenant = make_tenant(db, "Liste U4")
    linked = make_list_definition(db, tenant.id, name="Verknüpft")
    make_element_definition(db, tenant.id, "Ämtliliste", [{"configuration_json": {"linked_list_id": linked.id}}])
    # Präfix-Treffer (z. B. 12 in 123) darf nicht als Verknüpfung zählen.
    make_element_definition(db, tenant.id, "Anderer Baustein", [{"configuration_json": {"linked_list_id": int(f"{linked.id}9")}}])

    with pytest.raises(HTTPException) as exc:
        lists_route.delete_definition(linked.public_id, db=db, user=make_current_user(tenant.id))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "list_in_use"
    assert [usage["name"] for usage in exc.value.detail["usages"]] == ["Ämtliliste"]


def test_row_link_as_string_id_also_counts(db):
    tenant = make_tenant(db, "Liste C10")
    linked = make_list_definition(db, tenant.id, name="Zeilen")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-L")
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(db, element.id, configuration_snapshot_json={"rows": [{"linked_list_id": str(linked.id)}]})
    usages = lists_route._list_definition_usages(db, linked.id, tenant.id)
    assert [(usage["kind"], usage["number"]) for usage in usages] == [("protocol", "P-L")]


# ── Statistik ────────────────────────────────────────────────────────────


def test_group_statistics_follow_the_flag_not_the_name(db):
    tenant = make_tenant(db, "Gruppen C3")
    renamed = make_list_definition(db, tenant.id, name="Gruppen 2026", is_group_source=True)
    make_list_entry(db, renamed.id, column_one_value={"text_value": "Adler"})
    unflagged = make_list_definition(db, tenant.id, name="Gruppen")
    make_list_entry(db, unflagged.id, column_one_value={"text_value": "Falken"})
    for tag in ("Adler", "Falken"):
        event = make_event(db, tenant.id, title=tag, event_date=date(2026, 3, 1))
        event.tag = tag
        event.participant_count = 4
    db.flush()

    assert {row.group_name for row in fetch_group_session_rows(db, tenant.id)} == {"Adler"}
    overview = get_statistics_overview(db=db, user=make_current_user(tenant.id))
    assert overview.groups_source_configured is True


def test_restricted_reader_sees_only_numbers_of_assigned_templates(db):
    tenant = make_tenant(db, "Statistik C9")
    mine = make_template(db, tenant.id, "Leitersitzung")
    other = make_template(db, tenant.id, "Vorstand")
    own_protocol = make_protocol(db, tenant.id, mine.id, protocol_number="L-1", protocol_date=date(2026, 3, 1), status="abgeschlossen")
    for number, template in (("V-1", other), ("V-2", other)):
        make_protocol(db, tenant.id, template.id, protocol_number=number, protocol_date=date(2026, 3, 2), status="abgeschlossen")
    # Vorbereitete Protokolle zählen nicht (U6).
    make_protocol(db, tenant.id, mine.id, protocol_number="L-2", protocol_date=date(2026, 4, 1), status="vorbereitet")

    writer = get_statistics_overview(db=db, user=make_current_user(tenant.id))
    assert writer.protocols_total == 3

    reader = _restricted_reader(db, tenant.id, mine.id, [own_protocol.id])
    restricted = get_statistics_overview(db=db, user=reader)
    assert restricted.protocols_total == 1


# ── Anliegen ─────────────────────────────────────────────────────────────


def _agenda_setup(db, name):
    tenant = make_tenant(db, f"Anliegen {name}")
    template = make_template(db, tenant.id, f"Vorstand {name}")
    account = make_app_user(db, email=f"anliegen-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id, role_code="writer")
    return tenant, template, make_current_user(tenant.id, user_id=account.id)


def test_agenda_item_uses_swiss_today(db, monkeypatch):
    tenant, template, writer = _agenda_setup(db, "C4")
    swiss_today = date(2026, 11, 13)  # z. B. 00:30 in Zürich, in UTC noch der 12.
    monkeypatch.setattr(agenda_service_module, "today_local", lambda: swiss_today)
    created = agenda_route.create_agenda_item(
        AgendaItemCreate(template_id=template.public_id, title="Neue Kasse", schedule=AgendaSchedule()), db=db, user=writer,
    )
    assert created.earliest_date == swiss_today


def test_agenda_errors_are_translated_and_update_is_audited(db, monkeypatch):
    tenant, template, writer = _agenda_setup(db, "U2")
    created = agenda_route.create_agenda_item(
        AgendaItemCreate(template_id=template.public_id, title="Thema", schedule=AgendaSchedule()), db=db, user=writer,
    )
    logged = []
    monkeypatch.setattr(agenda_route.audit, "log", lambda db_, **kwargs: logged.append(kwargs))
    agenda_route.update_agenda_item(created.id, AgendaItemUpdate(title="Neues Thema"), db=db, user=writer)
    assert logged[0]["action"] == "agenda_item.updated"
    assert logged[0]["details"]["fields"] == ["title"]

    with pytest.raises(HTTPException) as exc:
        agenda_route.update_agenda_item(uuid.uuid4(), AgendaItemUpdate(title="x"), db=db, user=writer)
    assert exc.value.detail == "Das Anliegen wurde nicht gefunden."

    # Zuletzt: der Fehlerpfad rollt die Sitzung zurück (im Test samt Mandanten-Bindung).
    with pytest.raises(HTTPException) as exc:
        agenda_route.update_agenda_item(created.id, AgendaItemUpdate(title="   "), db=db, user=writer)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Bitte einen Titel eingeben."


# ── Vorlagen, Dokumentquellen ─────────────────────────────────────────────


def test_unassigned_template_answers_404_for_restricted_reader(db):
    tenant = make_tenant(db, "Vorlage C14")
    mine = make_template(db, tenant.id, "Meine")
    other = make_template(db, tenant.id, "Fremde")
    reader = _restricted_reader(db, tenant.id, mine.id, [])
    assert templates_route.get_template(mine.public_id, db=db, user=reader).id == mine.id
    for call in (templates_route.get_template, templates_route.list_template_elements):
        with pytest.raises(HTTPException) as exc:
            call(other.public_id, db=db, user=reader)
        assert exc.value.status_code == 404


def test_protocol_source_includes_old_assigned_protocols(db):
    tenant = make_tenant(db, "Quellen C7")
    template = make_template(db, tenant.id)
    old = make_protocol(db, tenant.id, template.id, protocol_number="ALT", protocol_date=date(2020, 1, 1), status="abgeschlossen")
    for index in range(3):
        make_protocol(db, tenant.id, template.id, protocol_number=f"NEU-{index}", protocol_date=date(2026, 1, 1) + timedelta(days=index))
    reader = _restricted_reader(db, tenant.id, template.id, [old.id])
    options = documents_route.list_source_options("protocols", db=db, user=reader)
    assert [option.id for option in options] == [old.public_id]


def test_protocol_block_source_in_element_order(db):
    tenant = make_tenant(db, "Quellen Blöcke")
    template = make_template(db, tenant.id)
    definition = make_element_definition(db, tenant.id, "Punkt", [])
    make_template_element(db, template.id, definition.id, 0, "Punkt")
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    second = make_protocol_element(db, protocol.id, sort_index=1, section_name="Zwei")
    first = make_protocol_element(db, protocol.id, sort_index=0, section_name="Eins")
    make_protocol_element_block(db, second.id, {})
    make_protocol_element_block(db, first.id, {})
    options = documents_route.list_source_options("protocol_blocks", protocol_id=protocol.public_id, db=db, user=make_current_user(tenant.id))
    assert [option.detail for option in options] == ["Eins", "Zwei"]


# ── PDF-Auftragsschleife ─────────────────────────────────────────────────


def test_render_loop_errors_reach_system_error_log_throttled(db, monkeypatch):
    from contextlib import contextmanager

    from app.core import error_log

    recorded = []

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(document_render_jobs, "SessionLocal", session)
    monkeypatch.setattr(error_log, "record_system_error", lambda db_, *, exc, **kwargs: recorded.append(str(exc)))
    document_render_jobs._last_loop_error.clear()

    document_render_jobs._report_loop_error(RuntimeError("Schema"), 1000.0)
    document_render_jobs._report_loop_error(RuntimeError("Schema"), 1002.0)  # gleicher Fehler kurz danach: still
    document_render_jobs._report_loop_error(RuntimeError("Anderes"), 1004.0)
    document_render_jobs._report_loop_error(RuntimeError("Anderes"), 1004.0 + 601)
    assert recorded == ["Schema", "Anderes", "Anderes"]


def test_linking_a_list_locks_it_against_concurrent_delete(db):
    """C10 Rest: Verknüpfen einer Liste in einem Baustein sperrt die Liste (FOR SHARE) bis zum
    Commit - das Löschen sperrt dieselbe Zeile (FOR UPDATE) und wartet bzw. findet danach die
    Verknüpfung. Fremde Listen gelten weiterhin als nicht gefunden."""
    from sqlalchemy import event

    from app.services.element_definition_service import ElementDefinitionService
    from app.services.list_service import lock_linked_list_definitions

    tenant = make_tenant(db, "C10 Lock")
    other = make_tenant(db, "C10 Fremd")
    own = make_list_definition(db, tenant.id, name="Ämtli")
    foreign = make_list_definition(db, other.id, name="Fremd")

    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        found = lock_linked_list_definitions(db, [own.id, foreign.id, None], tenant_id=tenant.id)
        ElementDefinitionService()._validate_linked_lists(db, [{"configuration_json": {"linked_list_id": own.id}}], tenant_id=tenant.id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert found == {own.id}
    assert sum("FOR SHARE" in statement and "list_definition" in statement for statement in statements) == 2
    with pytest.raises(ValueError):
        ElementDefinitionService()._validate_linked_lists(db, [{"configuration_json": {"linked_list_id": foreign.id}}], tenant_id=tenant.id)
