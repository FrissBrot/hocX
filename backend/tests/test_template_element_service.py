"""Regression tests for M8 (2026-08-13 audit) - create_template_element/update_template_element
must reject a linked_list_id (whole-list top-level or any rows[].linked_list_id row-link) in
configuration_json that references a nonexistent or cross-tenant ListDefinition, instead of
storing it silently and only failing much later when a protocol snapshot tries to resolve it."""
import pytest

from app.schemas.template import TemplateElementCreate, TemplateElementUpdate
from app.services.template_element_service import TemplateElementService
from tests.factories import (
    make_element_definition,
    make_list_definition,
    make_tenant,
    make_template,
    make_template_element,
)


def _form_blocks():
    return [
        {
            "id": 1,
            "title": "Block",
            "sort_index": 10,
            "element_type_id": 6,
            "render_type_id": 5,
            "configuration_json": {},
        }
    ]


def test_create_template_element_rejects_foreign_tenant_linked_list(db):
    tenant = make_tenant(db, "Tenant A")
    other_tenant = make_tenant(db, "Tenant B")
    template = make_template(db, tenant.id)
    definition = make_element_definition(db, tenant.id, "Formular", _form_blocks(), element_type_id_=6, render_type_id=5)
    foreign_list = make_list_definition(db, other_tenant.id, "Fremde Liste")

    service = TemplateElementService()
    payload = TemplateElementCreate(
        element_definition_id=definition.id,
        sort_index=10,
        configuration_json={"linked_list_id": foreign_list.id},
    )

    with pytest.raises(ValueError):
        service.create_template_element(db, template.id, payload)


def test_create_template_element_rejects_nonexistent_linked_list(db):
    tenant = make_tenant(db, "Tenant C")
    template = make_template(db, tenant.id)
    definition = make_element_definition(db, tenant.id, "Formular", _form_blocks(), element_type_id_=6, render_type_id=5)

    service = TemplateElementService()
    payload = TemplateElementCreate(
        element_definition_id=definition.id,
        sort_index=10,
        configuration_json={"linked_list_id": 999999},
    )

    with pytest.raises(ValueError):
        service.create_template_element(db, template.id, payload)


def test_create_template_element_accepts_same_tenant_linked_list(db):
    tenant = make_tenant(db, "Tenant D")
    template = make_template(db, tenant.id)
    definition = make_element_definition(db, tenant.id, "Formular", _form_blocks(), element_type_id_=6, render_type_id=5)
    own_list = make_list_definition(db, tenant.id, "Eigene Liste")

    service = TemplateElementService()
    payload = TemplateElementCreate(
        element_definition_id=definition.id,
        sort_index=10,
        configuration_json={"linked_list_id": own_list.id},
    )

    result = service.create_template_element(db, template.id, payload)

    assert result.configuration_json.get("linked_list_id") == own_list.id


def test_update_template_element_rejects_foreign_tenant_linked_list_in_rows(db):
    tenant = make_tenant(db, "Tenant E")
    other_tenant = make_tenant(db, "Tenant F")
    template = make_template(db, tenant.id)
    definition = make_element_definition(db, tenant.id, "Formular", _form_blocks(), element_type_id_=6, render_type_id=5)
    template_element = make_template_element(db, template.id, definition.id, 10, "Formular")
    foreign_list = make_list_definition(db, other_tenant.id, "Fremde Liste")

    service = TemplateElementService()
    payload = TemplateElementUpdate(configuration_json={"rows": [{"linked_list_id": foreign_list.id}]})

    with pytest.raises(ValueError):
        service.update_template_element(db, template_element.id, payload)


def test_update_template_element_accepts_same_tenant_linked_list(db):
    tenant = make_tenant(db, "Tenant G")
    template = make_template(db, tenant.id)
    definition = make_element_definition(db, tenant.id, "Formular", _form_blocks(), element_type_id_=6, render_type_id=5)
    template_element = make_template_element(db, template.id, definition.id, 10, "Formular")
    own_list = make_list_definition(db, tenant.id, "Eigene Liste")

    service = TemplateElementService()
    payload = TemplateElementUpdate(configuration_json={"linked_list_id": own_list.id})

    result = service.update_template_element(db, template_element.id, payload)

    assert result.configuration_json.get("linked_list_id") == own_list.id
