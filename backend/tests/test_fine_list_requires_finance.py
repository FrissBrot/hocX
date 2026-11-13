"""Bussenliste (Protokollelement «fine_list») zeigt die Bussen aller Mitglieder: anlegen,
einstellen oder als Baustein in eine Vorlage einfügen darf sie nur, wer Finanzen sehen darf
(finances.read). Andere Änderungen am Element und das Entfernen bleiben mit templates.edit frei."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import templates as routes
from app.schemas.template import ElementDefinitionBlockCreate, ElementDefinitionCreate, ElementDefinitionUpdate, TemplateElementCreate
from tests.factories import make_current_user, make_template, make_tenant

FINE_LIST = 14
TEXT = 1


def _block(block_id: int, element_type_id: int, config: dict | None = None, title: str = "Block") -> ElementDefinitionBlockCreate:
    return ElementDefinitionBlockCreate(
        id=block_id, title=title, element_type_id=element_type_id, render_type_id=1, sort_index=block_id, configuration_json=config or {}
    )


def _users(tenant_id: int):
    without_finance = make_current_user(tenant_id, permissions=frozenset({"meetings.read", "meetings.edit", "templates.edit"}))
    with_finance = make_current_user(tenant_id, permissions=frozenset({"meetings.read", "meetings.edit", "templates.edit", "finances.read"}))
    return without_finance, with_finance


def test_creating_a_fine_list_needs_finance_access(db):
    tenant = make_tenant(db, "Bussenliste anlegen")
    without_finance, with_finance = _users(tenant.id)
    payload = ElementDefinitionCreate(title="Bussen", blocks=[_block(1, FINE_LIST)])

    with pytest.raises(HTTPException) as excinfo:
        routes.create_element_definition(payload, db=db, user=without_finance)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail["code"] == "fine_list_requires_finance"

    created = routes.create_element_definition(payload, db=db, user=with_finance)
    assert created.blocks[0].element_type_id == FINE_LIST
    # Ohne Bussenliste ändert sich nichts
    assert routes.create_element_definition(ElementDefinitionCreate(title="Text", blocks=[_block(1, TEXT)]), db=db, user=without_finance)


def test_changing_fine_list_settings_needs_finance_access_other_changes_do_not(db):
    tenant = make_tenant(db, "Bussenliste ändern")
    without_finance, with_finance = _users(tenant.id)
    created = routes.create_element_definition(
        ElementDefinitionCreate(title="Bussen", blocks=[_block(1, FINE_LIST, {"fine_list_status": "all"}), _block(2, TEXT)]), db=db, user=with_finance
    )
    blocks = [block.model_dump() for block in created.blocks]

    # Titel ändern und anderen Block bearbeiten: erlaubt
    renamed = [{**blocks[0], "title": "Offene Bussen"}, {**blocks[1], "title": "Notizen"}]
    routes.patch_element_definition(created.id, ElementDefinitionUpdate(blocks=renamed), db=db, user=without_finance)

    # Bussen-Einstellung ändern: nur mit Finanzzugriff
    changed = [{**renamed[0], "configuration_json": {**renamed[0]["configuration_json"], "fine_list_status": "open"}}, renamed[1]]
    with pytest.raises(HTTPException) as excinfo:
        routes.patch_element_definition(created.id, ElementDefinitionUpdate(blocks=changed), db=db, user=without_finance)
    assert excinfo.value.status_code == 403

    # Zweite Bussenliste dazu: ebenfalls nicht
    added = renamed + [{**renamed[0], "id": 3, "sort_index": 3}]
    with pytest.raises(HTTPException):
        routes.patch_element_definition(created.id, ElementDefinitionUpdate(blocks=added), db=db, user=without_finance)

    # Entfernen ist erlaubt
    removed = routes.patch_element_definition(created.id, ElementDefinitionUpdate(blocks=[renamed[1]]), db=db, user=without_finance)
    assert [block.element_type_id for block in removed.blocks] == [TEXT]


def test_inserting_a_library_element_with_fine_list_needs_finance_access(db):
    tenant = make_tenant(db, "Bussenliste einfügen")
    without_finance, with_finance = _users(tenant.id)
    template = make_template(db, tenant.id)
    library = routes.create_element_definition(
        ElementDefinitionCreate(title="Bussen", is_library=True, blocks=[_block(1, FINE_LIST)]), db=db, user=with_finance
    )
    payload = TemplateElementCreate(element_definition_id=library.id, sort_index=10)

    with pytest.raises(HTTPException) as excinfo:
        routes.create_template_element(template.public_id, payload, db=db, user=without_finance)
    assert excinfo.value.status_code == 403
    assert routes.create_template_element(template.public_id, payload, db=db, user=with_finance)
