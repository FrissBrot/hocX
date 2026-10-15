"""Layoutschema: Validierung der Struktur, Sicherheitsmuster, Seitengrössen, Schema-Migration."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.documents import layout_migrations
from app.documents.layout import MAX_DEPTH, NODE_MODELS, PageSetup, TemplateContent, layout_error_of, parse_content


def _content(body, **extra):
    return {"masters": [{"id": "default"}], "body": body, **extra}


def _layout_error(data):
    with pytest.raises(ValidationError) as excinfo:
        TemplateContent.model_validate(data)
    error = layout_error_of(excinfo.value)
    assert error is not None, excinfo.value
    return error


def test_all_required_layout_types_exist():
    required = {"stack", "row", "column", "grid", "container", "section", "text", "image", "divider", "spacer", "table", "data_block", "page_break", "header", "footer", "absolute_layer"}
    assert required <= set(NODE_MODELS)


def test_duplicate_ids_are_rejected():
    error = _layout_error(_content([{"type": "text", "id": "a"}, {"type": "spacer", "id": "a"}]))
    assert error.code == "duplicateId" and error.node_id == "a"


def test_master_only_nodes_not_in_body():
    assert _layout_error(_content([{"type": "watermark", "id": "w"}])).code == "masterOnly"


def test_unknown_master_references():
    assert _layout_error(_content([], settings={"first_page_master": "fehlt"})).code == "unknownMaster"
    assert _layout_error(_content([{"type": "page_break", "id": "p", "master": "fehlt"}])).code == "unknownMaster"


def test_depth_limit():
    node: dict = {"type": "text", "id": "leaf"}
    for index in range(MAX_DEPTH + 2):
        node = {"type": "stack", "id": f"s{index}", "children": [node]}
    assert _layout_error(_content([node])).code == "tooDeep"


@pytest.mark.parametrize(
    "node",
    [
        {"type": "text", "id": "x", "style": {"background": "red; #eval"}},
        {"type": "text", "id": "x", "style": {"width": "calc(100%)"}},
        {"type": "text", "id": "x", "style": {"text": {"font": "Inter\"); #eval("}}},
        {"type": "text", "id": "x", "content": {"default": [{"t": "bind", "path": "protocol.date; drop"}]}},
        {"type": "text", "id": "x", "content": {"default": [{"t": "key", "key": "../etc"}]}},
        {"type": "text", "id": "x y"},
        {"type": "text", "id": "x", "code": "#eval"},
        {"type": "qr_code", "id": "x", "target": "url", "url": "javascript:alert(1)"},
        {"type": "text", "id": "x", "content": {"default": [], "translations": {"xx": []}}},
        {"type": "data_block", "id": "x"},
    ],
)
def test_unsafe_or_invalid_values_are_rejected(node):
    with pytest.raises(ValidationError):
        TemplateContent.model_validate(_content([node]))


def test_children_of_absolute_layer_get_frames():
    content = TemplateContent.model_validate(_content([{"type": "absolute_layer", "id": "l", "children": [{"type": "text", "id": "t"}]}]))
    assert content.body[0].children[0].frame is not None


def test_table_rows_wider_than_columns_are_rejected():
    assert _layout_error(_content([{"type": "table", "id": "t", "columns": [{"id": "c"}], "rows": [["a", "b"]]}])).code == "tableRowTooWide"


@pytest.mark.parametrize(("size", "orientation", "expected"), [("A4", "portrait", (210, 297)), ("A4", "landscape", (297, 210)), ("A5", "portrait", (148, 210)), ("Letter", "landscape", (279.4, 215.9))])
def test_page_dimensions(size, orientation, expected):
    assert PageSetup(size=size, orientation=orientation).dimensions_mm() == expected


def test_custom_page_size():
    assert PageSetup(size="custom", width=100, height=150).dimensions_mm() == (100, 150)


def test_schema_migration_rejects_future_versions_and_upgrades_old(monkeypatch):
    assert parse_content({}).schema_version == 1
    with pytest.raises(layout_migrations.LayoutMigrationError):
        layout_migrations.migrate_content({"schema_version": 99})
    monkeypatch.setattr(layout_migrations, "LAYOUT_SCHEMA_VERSION", 2)
    monkeypatch.setitem(layout_migrations.MIGRATIONS, 1, lambda data: {**data, "upgraded": True})
    result = layout_migrations.migrate_content({"schema_version": 1, "body": []})
    assert result["schema_version"] == 2 and result["upgraded"] is True
    with pytest.raises(layout_migrations.LayoutMigrationError):
        monkeypatch.delitem(layout_migrations.MIGRATIONS, 1)
        layout_migrations.migrate_content({"schema_version": 1})


def test_total_content_size_is_limited():
    """STUDIO-006: Gesendete Layoutbäume sind in allen Eingängen auf MAX_CONTENT_BYTES begrenzt."""
    from app.api.routes import document_studio as studio
    from app.documents.layout import MAX_CONTENT_BYTES
    from app.documents.service import DocumentRequest

    # Viele Knoten knapp unter den Einzelgrenzen ergeben zusammen mehr als MAX_CONTENT_BYTES
    body = [{"type": "rich_text", "id": f"r{index}", "markdown": "x" * 45_000} for index in range(50)]
    huge = _content(body)
    for build in (
        lambda: studio.DraftSave(content=huge),
        lambda: studio.TemplateCreate(name="X", document_type="protocol", content=huge),
        lambda: studio.ValidateBody(content=huge),
        lambda: studio.ComponentWrite(node={"type": "section", "id": "s", "children": body}),
        lambda: DocumentRequest(content=huge),
    ):
        with pytest.raises(ValidationError) as excinfo:
            build()
        error = layout_error_of(excinfo.value)
        assert error is not None and error.code == "contentTooLarge" and error.detail == str(MAX_CONTENT_BYTES)
    assert studio.DraftSave(content=_content(body[:10])).content["body"][0]["id"] == "r0"
