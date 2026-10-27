"""Gestaltungsbeispiele: gültig und ohne Hardcode-Texte, Import legt Vorlage und verknüpftes
Beispiel-CD an (nie als Standardprofil), nur für Admins, mandantengebunden, und exportiert mit
echten Daten."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api.routes import document_studio as studio
from app.documents import brand_service, service
from app.documents.compiler import validate_template
from app.documents.appearance import APPEARANCE_BASES, APPEARANCE_VARIANTS, DESIGN_KEYS
from app.documents.examples import ASSET_DIR, EXAMPLES, build_example_content, example_tokens, thumbnail_path
from app.documents.layout import all_node_lists, iter_nodes
from app.documents.service import DocumentRequest
from app.documents.strings import strings_for
from app.documents.system_templates import SYSTEM_TEMPLATE_KEYS
from app.models import DocumentAsset, DocumentBrand, DocumentTemplate
from tests.factories import (
    make_app_user, make_current_user, make_participant, make_protocol, make_protocol_element,
    make_protocol_element_block, make_protocol_text, make_protocol_todo, make_template, make_tenant,
)


class _NoDb:
    def get(self, *args, **kwargs):
        return None


@pytest.fixture(autouse=True)
def _clean_scanner(db, monkeypatch):
    from app import scanner

    async def clean(contents, **kwargs):
        return ["clean" for _ in contents]

    monkeypatch.setattr(scanner, "scan_many", clean)
    monkeypatch.setattr(db, "rollback", lambda: None)


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda item: item.key)
def test_example_is_valid_and_uses_text_keys(example):
    content = build_example_content(example)
    diagnostics = validate_template(_NoDb(), None, content, document_type=example.document_type)
    assert [item for item in diagnostics if item.severity == "error"] == []
    keys: set[str] = set()
    for _area, nodes in all_node_lists(content):
        for node, _depth in iter_nodes(nodes):
            stack = list(json.loads(node.model_dump_json(exclude={"children"})).values())
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    if item.get("t") == "key":
                        keys.add(item["key"])
                    if item.get("t") == "text":
                        assert item["v"].strip() in ("", ":", ",", "-", "–", "/", "·", "§"), (example.key, item["v"])
                    stack.extend(item.values())
                elif isinstance(item, list):
                    stack.extend(item)
    from app.core.locale_config_generated import SUPPORTED_LOCALES

    for language in SUPPORTED_LOCALES:
        assert [item for item in keys if item not in strings_for(language)] == [], language


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda item: item.key)
def test_example_brand_images_and_thumbnail_are_bundled(example):
    tokens = example_tokens(example)
    assert tokens.organization.name and tokens.assets.logo is None
    for filename in example.images.values():
        assert (ASSET_DIR / filename).read_bytes().startswith(b"\x89PNG")
    assert thumbnail_path(example).read_bytes().startswith(b"\x89PNG")


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda item: item.key)
def test_example_is_a_design_with_every_element_kind(example):
    """Jedes Beispiel ist ein Design: Grundstil mit eigener Darstellung für jede Elementart,
    Seitenaufbau aus dem Design."""
    base = APPEARANCE_BASES[example.key]
    assert example.key in DESIGN_KEYS and not base.get("legacy")
    assert set(base["elements"]) == set(APPEARANCE_VARIANTS) - {"heading", "table"}
    for kind, variant in base["elements"].items():
        assert variant in APPEARANCE_VARIANTS[kind], (example.key, kind)
    tokens = example_tokens(example)
    assert tokens.appearance.base == example.key and not tokens.appearance.elements
    assert tokens.layout.heading_style == base["layout"]["heading_style"] and tokens.layout.radius == base["layout"]["radius"]


def test_examples_are_not_system_templates(db):
    assert not {item.key for item in EXAMPLES} & set(SYSTEM_TEMPLATE_KEYS)
    assert db.scalar(select(DocumentTemplate.id).where(DocumentTemplate.system_key.in_([item.key for item in EXAMPLES]))) is None


@pytest.fixture
def world(db):
    tenant = make_tenant(db, "Beispiel-Verein")
    other = make_tenant(db, "Fremder Verein")
    users = {role: make_app_user(db, email=f"{role}@beispiel.example", tenant_id=tenant.id, role_code=role) for role in ("reader", "writer", "admin")}
    return {
        "tenant": tenant,
        "other": other,
        **{role: make_current_user(tenant.id, role=role, user_id=user.id) for role, user in users.items()},
    }


def _import(db, user, key="alpin", name="Alpin"):
    return asyncio.run(studio._import_design_example_impl(key, studio.ExampleImport(name=name), db=db, user=user))


def test_list_and_thumbnail_for_every_reader(db, world):
    listed = studio.list_design_examples(user=world["reader"])
    assert [item.key for item in listed] == [item.key for item in sorted(EXAMPLES, key=lambda item: item.sort_index)]
    response = studio.get_design_example_thumbnail("fokus", user=world["reader"])
    assert response.media_type == "image/png" and response.body.startswith(b"\x89PNG")
    with pytest.raises(HTTPException) as excinfo:
        studio.get_design_example_thumbnail("../system_templates", user=world["reader"])
    assert excinfo.value.status_code == 404


def test_import_creates_template_linked_to_its_own_brand(db, world):
    tenant_id = world["tenant"].id
    imported = _import(db, world["admin"])
    template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.public_id == imported.id))
    assert template.tenant_id == tenant_id and template.origin == "tenant" and template.document_type == "protocol"
    assert imported.draft_revision is not None and imported.published_revision is None

    brand = db.scalar(select(DocumentBrand).where(DocumentBrand.public_id == imported.brand_id))
    assert brand.tenant_id == tenant_id and brand.name == "Alpin" and not brand.is_default
    default = brand_service.default_brand(db, tenant_id)
    assert default is not None and default.id != brand.id

    tokens = brand_service.tokens_of(brand_service.current_revision(db, brand))
    assert tokens.colors.primary == "#0A600B" and tokens.organization.name
    logo = db.scalar(select(DocumentAsset).where(DocumentAsset.public_id == tokens.assets.logo))
    footer = db.scalar(select(DocumentAsset).where(DocumentAsset.public_id == tokens.assets.footer_image))
    assert logo.tenant_id == tenant_id and footer.tenant_id == tenant_id

    # Ein zweiter Import legt ein weiteres Paar an und ändert nichts am ersten
    again = _import(db, world["admin"])
    assert again.id != imported.id and again.brand_id != imported.brand_id


def test_import_needs_admin_and_known_example(db, world):
    for role in ("reader", "writer"):
        with pytest.raises(HTTPException) as excinfo:
            _import(db, world[role])
        assert excinfo.value.status_code == 403
    with pytest.raises(ValidationError):
        studio.ExampleImport(name="   ")
    with pytest.raises(HTTPException) as excinfo:
        _import(db, world["admin"], key="protocol_standard")
    assert excinfo.value.status_code == 404
    assert db.scalar(select(DocumentBrand.id).where(DocumentBrand.tenant_id == world["tenant"].id, DocumentBrand.name == "Protokoll Farbband")) is None


def test_imported_example_stays_in_its_tenant(db, world):
    imported = _import(db, world["admin"])
    foreign = make_current_user(world["other"].id, role="admin", user_id=make_app_user(db, email="admin@fremd.example", tenant_id=world["other"].id, role_code="admin").id)
    with pytest.raises(HTTPException) as excinfo:
        studio.get_document_template(imported.id, db=db, user=foreign)
    assert excinfo.value.status_code == 404


def test_every_example_compiles_with_its_brand_and_images(db, world):
    tenant_id = world["tenant"].id
    template = make_template(db, tenant_id, name="Hock")
    protocol = make_protocol(db, tenant_id, template.id, protocol_number="2026.2", status="durchgeführt")
    people = [make_participant(db, tenant_id, name) for name in ("Anna Muster", "Ben Beispiel")]
    element = make_protocol_element(db, protocol.id, section_name="Begrüssung")
    block = make_protocol_element_block(db, element.id, {"attendance_entries": [{"participant_id": p.id, "participant_name": p.display_name, "status": "present"} for p in people]}, element_type_code="attendance")
    text_block = make_protocol_element_block(db, element.id, {}, element_type_code="text", sort_index=1)
    make_protocol_text(db, text_block.id, "Die Sitzung wird **eröffnet**.")
    todo_block = make_protocol_element_block(db, element.id, {}, element_type_code="todo", sort_index=2)
    make_protocol_todo(db, todo_block.id, task="Saal reservieren")
    assert block.id
    for example in EXAMPLES:
        imported = _import(db, world["admin"], key=example.key, name=example.key)
        request = DocumentRequest(document_type="protocol", template_id=imported.id, revision_id=imported.draft_revision.id, protocol_id=protocol.public_id, data_mode="sample")
        prepared = service.prepare(db, world["admin"], tenant_id, request, preview=True)
        assert [item for item in prepared.compiled.diagnostics if item.severity == "error"] == [], example.key
        assert prepared.compiled.data["brand"]["colors"]["primary"] == example.tokens["colors"]["primary"]
        assert len([name for name in prepared.compiled.files if name.endswith(".png")]) >= len(example.images), example.key
