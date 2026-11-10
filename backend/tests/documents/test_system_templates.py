"""Systemvorlagen, Komponentenbibliothek und Katalog: vollständig, gültig, ohne Hardcode-Texte."""
from __future__ import annotations

import json

import pytest

from app.documents.compiler import validate_template
from app.documents.components import LIBRARY, NODE_TYPES, catalog_payload, validate_library
from app.documents.doc_types import DOCUMENT_TYPES
from app.documents.layout import NODE_MODELS, all_node_lists, iter_nodes
from app.documents.strings import strings_for
from app.documents.system_templates import SYSTEM_TEMPLATES, build_content


class _NoDb:
    def get(self, *args, **kwargs):
        return None


@pytest.mark.parametrize("definition", SYSTEM_TEMPLATES, ids=lambda item: item.key)
def test_system_template_is_valid_and_free_of_errors(definition):
    content = build_content(definition)
    diagnostics = validate_template(_NoDb(), None, content, document_type=definition.document_type)
    assert [item for item in diagnostics if item.severity == "error"] == []


@pytest.mark.parametrize("definition", SYSTEM_TEMPLATES, ids=lambda item: item.key)
def test_system_templates_use_text_keys_not_literal_texts(definition):
    """Systemvorlagen müssen in jeder Sprache stimmen: feste Texte nur als Schlüssel, die es in
    allen Sprachen gibt; literale Texte nur als Satzzeichen."""
    content = build_content(definition)
    keys: set[str] = set()
    for _area, nodes in all_node_lists(content):
        for node, _depth in iter_nodes(nodes):
            for value in json.loads(node.model_dump_json(exclude={"children"})).values():
                stack = [value]
                while stack:
                    item = stack.pop()
                    if isinstance(item, dict):
                        if item.get("t") == "key":
                            keys.add(item["key"])
                        if item.get("t") == "text":
                            assert item["v"].strip() in ("", ":", ",", "-", "–"), (definition.key, item["v"])
                        stack.extend(item.values())
                    elif isinstance(item, list):
                        stack.extend(item)
    from app.core.locale_config_generated import SUPPORTED_LOCALES

    for language in SUPPORTED_LOCALES:
        strings = strings_for(language)
        assert [key for key in keys if key not in strings] == [], language


def test_every_document_type_has_a_platform_default():
    defaults = {item.document_type for item in SYSTEM_TEMPLATES if item.platform_default}
    assert defaults == set(DOCUMENT_TYPES)
    for document_type in DOCUMENT_TYPES:
        assert sum(1 for item in SYSTEM_TEMPLATES if item.document_type == document_type and item.platform_default) == 1


def test_important_types_have_variants():
    for document_type in ("protocol", "invitation", "todos", "events", "statistics", "attendance_sheet", "custom"):
        assert sum(1 for item in SYSTEM_TEMPLATES if item.document_type == document_type) >= 2


def test_library_and_node_metadata_are_complete():
    validate_library()
    assert set(NODE_TYPES) == set(NODE_MODELS)
    assert len({entry.key for entry in LIBRARY}) == len(LIBRARY)
    payload = catalog_payload()
    assert set(payload["node_types"]) == set(NODE_MODELS)
    assert {item["key"] for item in payload["document_types"]} == set(DOCUMENT_TYPES)
    required = {"heading", "text", "rich_text", "image", "image_gallery", "table", "list", "divider", "spacer", "qr_code", "page_break", "container", "columns_2",
                "document_title", "subtitle", "metadata", "document_number", "date", "version", "toc", "header", "footer", "page_number", "watermark", "verify_note",
                "session_info", "protocol_sections", "agenda_items", "decisions", "tasks", "attendance", "members", "events_agenda", "finance_balance", "fines",
                "statistics_kpis", "chart", "form", "signatures"}
    assert required <= {entry.key for entry in LIBRARY}


def test_sync_is_idempotent_and_versioned(db, monkeypatch):
    from app.documents import system_templates
    from app.models import DocumentTemplate, DocumentTemplateRevision

    assert system_templates.sync_system_templates(db) == {"created": 0, "updated": 0}  # bereits durch Fixture synchronisiert
    template = db.query(DocumentTemplate).filter(DocumentTemplate.system_key == "protocol_standard").one()
    old_revision_id = template.published_revision_id
    original = next(item for item in system_templates.SYSTEM_TEMPLATES if item.key == "protocol_standard")
    changed = system_templates.SystemTemplate(original.key, original.document_type, original.variant, lambda: {**original.build(), "page": {"size": "A5"}}, original.platform_default, original.sort_index)
    monkeypatch.setattr(system_templates, "SYSTEM_TEMPLATES", tuple(changed if item.key == original.key else item for item in system_templates.SYSTEM_TEMPLATES))
    assert system_templates.sync_system_templates(db)["updated"] == 1
    db.refresh(template)
    assert template.published_revision_id != old_revision_id
    assert db.get(DocumentTemplateRevision, old_revision_id).status == "superseded"
    assert db.get(DocumentTemplateRevision, template.published_revision_id).content_json["page"]["size"] == "A5"
    assert db.query(DocumentTemplate).filter(DocumentTemplate.tenant_id.is_(None), DocumentTemplate.is_platform_default.is_(True)).count() == len(DOCUMENT_TYPES)
