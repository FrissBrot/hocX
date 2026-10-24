"""Listen-Routen ohne N+1: die Zahl der SQL-Abfragen darf nicht mit der Zahl der Einträge wachsen.

Vorher luden Protokoll-, Todo- und Albenliste Mandant, Vorlage, Block, Protokoll bzw. Freigaben
je Eintrag einzeln (Protokolle 6 -> 44, Todos 3 -> 41, Alben 9 -> 66 Abfragen bei 1 -> 20
Einträgen)."""

import pytest
from sqlalchemy import event

from app.api.routes import events, files, fines, lists, participants, protocols, templates, todos
from app.models.entities import PhotoAlbum, PhotoAlbumTenantShare
from tests.factories import (
    make_app_user,
    make_current_user,
    make_event,
    make_finance_account,
    make_fine,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)

# Spielraum für Abfragen, die nur einmal je Request vorkommen (Rollen, Feature-Prüfungen ...).
CONSTANT_SLACK = 2


def _query_count(db, call) -> int:
    counter = {"n": 0}

    def count(*_args):
        counter["n"] += 1

    db.flush()
    db.expire_all()
    db.info.pop("public_id_cache", None)  # wie eine neue Request-Session
    engine = db.connection().engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return counter["n"]


def _protocols(db, n):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    for i in range(n):
        make_protocol(db, tenant.id, template.id, protocol_number=f"P-{i}")
    user = make_current_user(tenant.id, role="admin")
    return lambda: protocols.list_protocols(q=None, status_filter=None, skip=0, limit=100, db=db, user=user)


def _todos(db, n):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    for i in range(n):
        # Jedes Todo in einem eigenen Protokoll und mit eigenem Zuständigen: verschiedene
        # Fremdschlüssel je Zeile, nicht nur dieselben.
        protocol = make_protocol(db, tenant.id, template.id, protocol_number=f"P-{i}")
        block = make_protocol_element_block(db, make_protocol_element(db, protocol.id).id, {}, element_type_code="todo")
        todo = make_protocol_todo(db, block.id, task=f"T{i}")
        todo.assigned_user_id = make_app_user(db, email=f"todo-{i}-{tenant.id}@example.org", tenant_id=tenant.id).id
    user = make_current_user(tenant.id, role="admin")
    return lambda: todos.list_all_todos(skip=0, limit=100, db=db, user=user)


def _albums(db, n):
    tenant = make_tenant(db)
    for i in range(n):
        album = PhotoAlbum(tenant_id=tenant.id, name=f"A{i}", kind="manual")
        db.add(album)
        db.flush()
        db.add(PhotoAlbumTenantShare(album_id=album.id, tenant_id=make_tenant(db).id, status="pending"))
        foreign = PhotoAlbum(tenant_id=make_tenant(db).id, name=f"F{i}", kind="manual")
        db.add(foreign)
        db.flush()
        db.add(PhotoAlbumTenantShare(album_id=foreign.id, tenant_id=tenant.id, status="accepted"))
    user = make_current_user(tenant.id, role="writer")
    return lambda: files.list_albums(db=db, user=user)


def _events(db, n):
    tenant = make_tenant(db)
    for i in range(n):
        make_event(db, tenant.id, title=f"E{i}")
    user = make_current_user(tenant.id, role="admin")
    return lambda: events.list_events(skip=0, limit=100, db=db, user=user)


def _participants(db, n):
    tenant = make_tenant(db)
    for i in range(n):
        make_participant(db, tenant.id, f"Person {i}")
    user = make_current_user(tenant.id, role="admin")
    return lambda: participants.list_participants(active_only=False, skip=0, limit=100, db=db, user=user)


def _fines(db, n):
    tenant = make_tenant(db)
    account = make_finance_account(db, tenant.id)
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id)
    for i in range(n):
        make_fine(db, protocol.id, account.id, participant_name_snapshot=f"P{i}")
    user = make_current_user(tenant.id, role="admin")
    return lambda: fines.list_fines(skip=0, limit=100, db=db, user=user)


def _list_entries(db, n):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    for i in range(n):
        make_list_entry(db, definition.id, sort_index=i)
    user = make_current_user(tenant.id, role="admin")
    return lambda: lists.list_entries(definition.public_id, db=db, user=user)


def _templates(db, n):
    tenant = make_tenant(db)
    for i in range(n):
        make_template(db, tenant.id, name=f"T{i}")
    user = make_current_user(tenant.id, role="admin")
    return lambda: templates.list_templates(q=None, status_filter=None, db=db, user=user)


@pytest.mark.parametrize(
    "setup", [_protocols, _todos, _albums, _events, _participants, _fines, _list_entries, _templates], ids=lambda f: f.__name__[1:]
)
def test_list_query_count_does_not_grow_with_the_number_of_entries(db, setup):
    one = _query_count(db, setup(db, 1))
    twenty = _query_count(db, setup(db, 20))
    assert twenty <= one + CONSTANT_SLACK, f"{one} Abfragen bei 1 Eintrag, {twenty} bei 20"
