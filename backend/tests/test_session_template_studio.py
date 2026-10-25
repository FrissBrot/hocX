"""Vorlagen-Editor einer Sitzungsvorlage: Baustein-Bibliothek, «nur in dieser Vorlage ändern»,
Aufräumen von Einzelstücken, Darstellung je Baustein, Rechte für Schreibende und die Vorschau
aus der Vorlagen-Konfiguration (Traktanden der Vorlage, Inhalte der letzten Sitzung)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import templates as template_routes
from app.documents.context import BuildContext
from app.documents.hashing import content_hash
from app.documents.model import DocumentMeta, RichTextBlock
from app.documents.providers.protocol import session_template_blocks
from app.models import ElementDefinition, TemplateElement
from app.schemas.template import TemplateElementCreate, TemplateElementUpdate
from app.services.element_definition_service import ElementDefinitionService
from app.services.template_element_service import TemplateElementService
from app.services.template_service import TemplateService
from tests.factories import make_current_user, make_element_definition, make_template, make_template_element, make_tenant


def _text_block(block_id: int = 1, title: str = "Notiz", **extra) -> dict:
    return {"id": block_id, "title": title, "sort_index": block_id * 10, "element_type_id": 1, "render_type_id": 2, "configuration_json": {}, "default_content": "Vorgabe", **extra}


def _todo_block(block_id: int = 2) -> dict:
    return {"id": block_id, "title": "Aufgaben", "sort_index": block_id * 10, "element_type_id": 2, "render_type_id": 3, "configuration_json": {}}


@pytest.fixture
def world(db):
    tenant = make_tenant(db, "Studio-Verein")
    first = make_template(db, tenant.id, name="Vorstand")
    second = make_template(db, tenant.id, name="GV")
    shared = make_element_definition(db, tenant.id, "Begrüssung", [_text_block()])
    first_element = make_template_element(db, first.id, shared.id, 10, "Begrüssung")
    second_element = make_template_element(db, second.id, shared.id, 10, "Begrüssung")
    return {"tenant": tenant, "first": first, "second": second, "shared": shared, "first_element": first_element, "second_element": second_element}


def test_library_and_usage_counts(db, world):
    single = make_element_definition(db, world["tenant"].id, "Nur hier", [_text_block()])
    single.is_library = False
    db.flush()
    service = ElementDefinitionService()
    library = service.list_element_definitions(db, tenant_id=world["tenant"].id, library_only=True)
    assert [item.title for item in library] == ["Begrüssung"]
    assert library[0].usage_count == 2
    read = TemplateElementService().get_template_element(db, world["first_element"].id)
    assert read.definition_is_library is True and read.definition_usage_count == 2


def test_detach_gives_the_agenda_item_its_own_content(db, world):
    service = TemplateElementService()
    detached = service.detach_definition(db, world["first_element"].id)
    copy = db.get(ElementDefinition, db.get(TemplateElement, world["first_element"].id).element_definition_id)
    assert copy.id != world["shared"].id and copy.is_library is False
    assert copy.configuration_json == world["shared"].configuration_json
    assert detached.definition_usage_count == 1
    # Der Bibliotheks-Baustein bleibt für die andere Vorlage bestehen
    assert db.get(ElementDefinition, world["shared"].id) is not None
    assert service.get_template_element(db, world["second_element"].id).definition_usage_count == 1


def test_single_definitions_are_removed_with_their_last_agenda_item(db, world):
    service = TemplateElementService()
    service.detach_definition(db, world["first_element"].id)
    copy_id = db.get(TemplateElement, world["first_element"].id).element_definition_id
    assert service.delete_template_element(db, world["first_element"].id)
    assert db.get(ElementDefinition, copy_id) is None
    # Bibliotheks-Bausteine bleiben auch ohne Verwendung erhalten
    assert service.delete_template_element(db, world["second_element"].id)
    assert db.get(ElementDefinition, world["shared"].id) is not None


def test_duplicating_a_template_copies_single_definitions(db, world):
    TemplateElementService().detach_definition(db, world["first_element"].id)
    source_definition = db.get(TemplateElement, world["first_element"].id).element_definition_id
    duplicate = TemplateService().duplicate_template(db, world["first"].id, new_name="Vorstand (Kopie)", created_by=None)
    copied = db.query(TemplateElement).filter(TemplateElement.template_id == duplicate.id).one()
    assert copied.element_definition_id != source_definition
    assert db.get(ElementDefinition, copied.element_definition_id).is_library is False


def test_block_appearance_is_validated(db, world):
    service = TemplateElementService()
    good = {"block_appearance": {"1": {"table": {"variant": "zebra", "corners": None}}}}
    updated = service.update_template_element(db, world["first_element"].id, TemplateElementUpdate(configuration_json=good))
    assert updated.configuration_json["block_appearance"] == {"1": {"table": {"variant": "zebra", "corners": None}}}
    for bad in ({"1": {"table": {"variant": "neon"}}}, {"1": {"heading": {"variant": "bar"}}}, {"x": {}}):
        with pytest.raises(ValueError):
            service.update_template_element(db, world["first_element"].id, TemplateElementUpdate(configuration_json={"block_appearance": bad}))


def test_writers_shape_agenda_items_but_not_template_settings(db, world):
    tenant = world["tenant"]
    writer = make_current_user(tenant.id, role="writer")
    reader = make_current_user(tenant.id, role="reader")
    single = make_element_definition(db, tenant.id, "Kasse", [_text_block()])
    payload = TemplateElementCreate(element_definition_id=single.public_id, sort_index=20)
    created = template_routes.create_template_element(world["first"].public_id, payload, db=db, user=writer)
    assert created.title == "Kasse"
    with pytest.raises(HTTPException) as excinfo:
        template_routes.create_template_element(world["first"].public_id, payload, db=db, user=reader)
    assert excinfo.value.status_code == 403
    detached = template_routes.detach_template_element(world["second_element"].public_id, db=db, user=writer)
    assert detached.definition_is_library is False
    from app.schemas.template import TemplateUpdate

    with pytest.raises(HTTPException) as excinfo:
        template_routes.patch_template(world["first"].public_id, TemplateUpdate(name="Neu"), db=db, user=writer)
    assert excinfo.value.status_code == 403


def test_detach_of_a_foreign_agenda_item_is_not_found(db, world):
    other = make_tenant(db, "Fremd")
    with pytest.raises(HTTPException) as excinfo:
        template_routes.detach_template_element(world["first_element"].public_id, db=db, user=make_current_user(other.id, role="admin"))
    assert excinfo.value.status_code == 404


def test_preview_follows_the_template_configuration(db, world):
    """Ohne Sitzung: Traktanden in Reihenfolge der Vorlage, im PDF ausgeblendete Bausteine fehlen,
    Bausteine ohne Inhalt erscheinen als Platzhalter, Darstellung und Einladungsfilter gelten."""
    tenant = world["tenant"]
    definition = make_element_definition(db, tenant.id, "Finanzen", [_text_block(1, "Bericht"), _todo_block(2), _text_block(3, "Intern")])
    make_template_element(db, world["first"].id, definition.id, 5, "Finanzen", configuration_json={
        "block_overrides": {"3": {"export_visible": False}},
        "block_appearance": {"2": {"table": {"variant": "grid"}}},
        "invitation_visible": False,
    })
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", session_template=world["first"])
    elements = session_template_blocks(ctx, None)
    assert [element.title for element in elements] == ["Finanzen", "Begrüssung"]
    finance = elements[0]
    assert [child.title for child in finance.children] == ["Bericht", "Aufgaben"]
    assert finance.children[1].appearance == {"table": {"variant": "grid"}}
    assert all(isinstance(child, RichTextBlock) and child.hide_if_empty is False for child in finance.children)
    assert [element.title for element in session_template_blocks(ctx, None, invitation_only=True)] == ["Begrüssung"]


def test_block_appearance_is_not_part_of_the_content_hash():
    meta = DocumentMeta(document_type="protocol", title="P", language="de")
    plain = RichTextBlock(title="Text")
    styled = RichTextBlock(title="Text", appearance={"table": {"variant": "grid"}})
    assert content_hash(meta, [plain]) == content_hash(meta, [styled])


def test_older_exports_without_library_flag_import_as_library_building_blocks(db):
    """Mandanten-Exporte bis Format 7 kennen is_library nicht: ihre Elemente landen wie bisher
    im Element-Katalog, jetzt «Meine Bausteine»."""
    from app.services.tenant_import_service import SUPPORTED_FORMAT_VERSIONS
    from app.services.tenant_transfer_common import build_row

    assert {7, 8} <= SUPPORTED_FORMAT_VERSIONS
    tenant = make_tenant(db, "Import-Verein")
    row = build_row(ElementDefinition, {"title": "Alt", "element_type_id": 1, "render_type_id": 2, "configuration_json": {"blocks": [_text_block()]}}, {"tenant_id": tenant.id})
    db.add(row)
    db.flush()
    assert row.is_library is True
