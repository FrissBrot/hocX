"""Gebündelte Aufgaben/Bilder je Protokoll (Performance-Paket B).

GET /protocols/{id}/block-todos und /block-images ersetzen auf der Protokollseite die
Einzelabrufe je Block. Sie müssen dieselben Daten liefern und genau dieselben Prüfungen haben
wie die Einzelrouten (meetings.read, Mandant, Protokollstatus, Teilnehmer-Zuordnung); fremde
oder unbekannte Protokolle ergeben 404.

Routen werden wie in den übrigen Route-Tests direkt als Funktionen aufgerufen.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import files as files_route
from app.api.routes import todos as todos_route
from app.models import ProtocolImage, StoredFile, UserProtocolAccess, UserTemplateAccess
from app.services.protocol_element_service import ProtocolElementService

from tests.factories import (
    make_app_user,
    make_current_user,
    make_list_definition,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)


def _protocol_with_blocks(db, tenant_id: int, *, status: str = "geplant"):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, status=status)
    element = make_protocol_element(db, protocol.id)
    todo_blocks = [make_protocol_element_block(db, element.id, {}, sort_index=i, element_type_code="todo") for i in range(2)]
    empty_todo_block = make_protocol_element_block(db, element.id, {}, sort_index=2, element_type_code="todo")
    image_block = make_protocol_element_block(db, element.id, {}, sort_index=3, element_type_code="image")
    empty_image_block = make_protocol_element_block(db, element.id, {}, sort_index=4, element_type_code="image")
    make_protocol_element_block(db, element.id, {}, sort_index=5, element_type_code="text")
    for block in todo_blocks:
        for index in range(3):
            make_protocol_todo(db, block.id, task=f"Aufgabe {index}", sort_index=2 - index)
    for index in range(2):
        stored = StoredFile(tenant_id=tenant_id, original_name=f"bild-{index}.jpg", storage_path=f"/tmp/bild-{index}.jpg", mime_type="image/jpeg")
        db.add(stored)
        db.flush()
        db.add(ProtocolImage(protocol_element_block_id=image_block.id, stored_file_id=stored.id, sort_index=1 - index, title=f"Bild {index}"))
    db.flush()
    return {
        "template": template,
        "protocol": protocol,
        "todo_blocks": [*todo_blocks, empty_todo_block],
        "image_blocks": [image_block, empty_image_block],
    }


def _dump(items) -> list:
    return [item.model_dump(mode="json") for item in items]


def _per_block_todos(db, blocks, user) -> dict:
    return {block.public_id: _dump(todos_route.list_todos(block.public_id, db=db, user=user)) for block in blocks}


def _per_block_images(db, blocks, user) -> dict:
    return {block.public_id: _dump(files_route.list_images(block.public_id, db=db, user=user)) for block in blocks}


def _bundle(result: dict) -> dict:
    return {key: _dump(value) for key, value in result.items()}


def test_bundles_match_per_block_routes(db):
    tenant = make_tenant(db, "Bundle Tenant")
    data = _protocol_with_blocks(db, tenant.id)
    user = make_current_user(tenant.id)

    todos = todos_route.list_protocol_block_todos(data["protocol"].public_id, db=db, user=user)
    images = files_route.list_protocol_block_images(data["protocol"].public_id, db=db, user=user)

    assert _bundle(todos) == _per_block_todos(db, data["todo_blocks"], user)
    assert _bundle(images) == _per_block_images(db, data["image_blocks"], user)
    # Reihenfolge innerhalb eines Blocks wie in der Einzelroute (sort_index)
    first = _bundle(todos)[data["todo_blocks"][0].public_id]
    assert [item["task"] for item in first] == ["Aufgabe 2", "Aufgabe 1", "Aufgabe 0"]
    assert [item["title"] for item in _bundle(images)[data["image_blocks"][0].public_id]] == ["Bild 1", "Bild 0"]
    # Nur Blöcke des jeweiligen Typs, leere Blöcke mit leerer Liste
    assert set(todos) == {block.public_id for block in data["todo_blocks"]}
    assert set(images) == {block.public_id for block in data["image_blocks"]}
    assert todos[data["todo_blocks"][2].public_id] == []
    assert images[data["image_blocks"][1].public_id] == []


def test_closed_protocol_bundle_uses_frozen_todo_snapshot(db):
    tenant = make_tenant(db, "Bundle Closed")
    data = _protocol_with_blocks(db, tenant.id)
    writer = make_current_user(tenant.id)
    live = {block.id: _dump(todos_route.list_todos(block.public_id, db=db, user=writer)) for block in data["todo_blocks"]}
    # Momentaufnahme wie beim Abschluss, danach weicht der Live-Stand ab
    frozen = {str(block_id): items[:1] for block_id, items in live.items()}
    data["protocol"].status = "abgeschlossen"
    data["protocol"].todos_snapshot_json = {"blocks": frozen, "pending": []}
    db.flush()
    make_protocol_todo(db, data["todo_blocks"][0].id, task="Nach Abschluss", sort_index=9)

    reader = make_current_user(tenant.id, role="reader")
    for user in (writer, reader):
        bundle = _bundle(todos_route.list_protocol_block_todos(data["protocol"].public_id, db=db, user=user))
        assert bundle == _per_block_todos(db, data["todo_blocks"], user)
        assert bundle[data["todo_blocks"][0].public_id] == frozen[str(data["todo_blocks"][0].id)]


@pytest.mark.parametrize("route", ["todos", "images"])
def test_foreign_or_unknown_protocol_is_404(db, route):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    data = _protocol_with_blocks(db, tenant_a.id)
    call = todos_route.list_protocol_block_todos if route == "todos" else files_route.list_protocol_block_images

    for protocol_id, user in (
        (data["protocol"].public_id, make_current_user(tenant_b.id)),
        (uuid.uuid4(), make_current_user(tenant_a.id)),
    ):
        with pytest.raises(HTTPException) as error:
            call(protocol_id, db=db, user=user)
        assert error.value.status_code == 404


def _status_or_ok(call) -> int:
    try:
        call()
    except HTTPException as exc:
        return exc.status_code
    return 200


@pytest.mark.parametrize("route", ["todos", "images"])
@pytest.mark.parametrize("status", ["geplant", "abgeschlossen"])
def test_permission_parity_with_per_block_route(db, route, status):
    tenant = make_tenant(db, "Parity")
    data = _protocol_with_blocks(db, tenant.id, status=status)
    bundle = todos_route.list_protocol_block_todos if route == "todos" else files_route.list_protocol_block_images
    single = todos_route.list_todos if route == "todos" else files_route.list_images
    block = (data["todo_blocks"] if route == "todos" else data["image_blocks"])[0]

    # Eingeschränkter Leser: einer Vorlage zugeordnet, aber nicht diesem Protokoll
    scoped = make_app_user(db, email=f"scoped-{route}-{status}@example.com", tenant_id=tenant.id, role_code="reader")
    db.add(UserTemplateAccess(user_id=scoped.id, tenant_id=tenant.id, template_id=data["template"].id))
    db.flush()
    # Eingeschränkter Leser mit Zuordnung zum Protokoll
    assigned = make_app_user(db, email=f"assigned-{route}-{status}@example.com", tenant_id=tenant.id, role_code="reader")
    db.add(UserTemplateAccess(user_id=assigned.id, tenant_id=tenant.id, template_id=data["template"].id))
    db.add(UserProtocolAccess(user_id=assigned.id, tenant_id=tenant.id, protocol_id=data["protocol"].id))
    db.flush()

    users = {
        "writer": make_current_user(tenant.id),
        "reader": make_current_user(tenant.id, role="reader"),
        "no_permission": make_current_user(tenant.id, permissions=frozenset()),
        "scoped_unassigned": make_current_user(tenant.id, role="reader", user_id=scoped.id),
        "scoped_assigned": make_current_user(tenant.id, role="reader", user_id=assigned.id),
    }
    results = {}
    for name, user in users.items():
        expected = _status_or_ok(lambda: single(block.public_id, db=db, user=user))
        actual = _status_or_ok(lambda: bundle(data["protocol"].public_id, db=db, user=user))
        results[name] = actual
        assert actual == expected, name
    assert results["writer"] == 200
    assert results["no_permission"] == 403
    assert results["scoped_unassigned"] == 403
    assert results["scoped_assigned"] == 200
    # Ohne meetings.read_drafts nur abgeschlossene Protokolle
    assert results["reader"] == (200 if status == "abgeschlossen" else 403)


def _count_queries(db, call):
    statements = []

    def before(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", before)
    try:
        result = call()
    finally:
        event.remove(bind, "before_cursor_execute", before)
    return result, len(statements)


def test_element_listing_query_count_does_not_grow_with_blocks(db):
    """GET /protocols/{id}/elements lud je Block Elementdefinition, Vorlagenelement und alle
    Referenzen einzeln (46 Blöcke -> 71 Abfragen). Jetzt gesammelt: die Zahl der Abfragen hängt
    nicht von der Zahl der Blöcke ab."""
    tenant = make_tenant(db, "Query Count")
    person = make_participant(db, tenant.id, "Anna")
    other = make_participant(db, tenant.id, "Beat")
    linked = make_list_definition(db, tenant.id, name="Liste")

    def build(block_count: int):
        template = make_template(db, tenant.id, name=f"Vorlage {block_count}")
        protocol = make_protocol(db, tenant.id, template.id, protocol_number=f"P-{block_count}")
        for index in range(block_count):
            element = make_protocol_element(db, protocol.id, sort_index=index)
            make_protocol_element_block(
                db,
                element.id,
                {
                    "linked_list_id": linked.id,
                    "rows": [
                        {"id": "r1", "participant_id": person.id, "participant_ids": [other.id]},
                        {"id": "r2", "participant_id": str(other.public_id)},
                    ],
                },
            )
        return protocol

    service = ProtocolElementService()
    small = build(2)
    large = build(12)
    small_result, small_count = _count_queries(db, lambda: service.list_protocol_elements(db, small.id))
    large_result, large_count = _count_queries(db, lambda: service.list_protocol_elements(db, large.id))
    assert large_count == small_count
    block = large_result[0].blocks[0].model_dump(mode="json")
    assert block["configuration_snapshot_json"]["rows"][0]["participant_id"] == str(person.public_id)
    assert block["configuration_snapshot_json"]["rows"][0]["participant_ids"] == [str(other.public_id)]
    assert block["public_reference_ids"]["lists"] == {str(linked.id): str(linked.public_id)}
    assert block["participant_names"] == {str(person.public_id): "Anna", str(other.public_id): "Beat"}
    assert large_result[11].blocks[0].model_dump(mode="json")["participant_names"] == block["participant_names"]
