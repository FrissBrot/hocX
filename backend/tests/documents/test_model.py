"""Dokumentmodell: Union, Validierung, Leer-Erkennung."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.documents.model import (
    BLOCK_MODELS,
    Cell,
    Document,
    DocumentMeta,
    ImageRef,
    ResolvedStyle,
    TableColumn,
    TableRow,
    Tag,
    table_from_rows,
)


def test_block_registry_is_complete():
    expected = {
        "heading", "richtext", "static_text", "page_break", "toc", "spacer", "divider",
        "protocol_element", "session_date", "session_notes", "form", "bullet_list", "matrix",
        "entry_exit", "image", "image_gallery", "attendance", "attendance_matrix", "member_list",
        "signature_fields", "attendance_sheet", "todo_table", "event_table",
        "event_calendar_month", "event_agenda", "list_table", "finance_balance",
        "finance_transactions", "fines", "kpi_tiles", "chart", "stat_table", "qr_link",
        "generic_table",
    }
    assert set(BLOCK_MODELS) == expected


def test_document_round_trip_with_nested_protocol_element():
    table = table_from_rows(
        [TableColumn(key="task", label_key="col.task")],
        [TableRow(cells=[Cell(v="Aufgabe")])],
    )
    doc = Document.model_validate(
        {
            "meta": {"document_type": "protocol", "title": "T"},
            "blocks": [
                {
                    "type": "protocol_element",
                    "title": "Traktandum",
                    "children": [
                        {"type": "todo_table", "table": table.model_dump()},
                        {"type": "richtext", "content": [{"t": "p", "c": [{"t": "text", "v": "x"}]}]},
                    ],
                }
            ],
        }
    )
    again = Document.model_validate_json(doc.model_dump_json())
    assert again == doc
    assert again.blocks[0].children[0].table.row_count() == 1


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        Document.model_validate({"meta": {"document_type": "x", "title": "T"}, "blocks": [{"type": "heading", "text": "a", "code": "#eval"}]})


def test_colors_and_paths_are_validated():
    with pytest.raises(ValidationError):
        Tag(label="x", color="red; #eval")
    with pytest.raises(ValidationError):
        ResolvedStyle(primary_color="#12345")
    with pytest.raises(ValidationError):
        ImageRef(path="../../etc/passwd")
    with pytest.raises(ValidationError):
        ResolvedStyle(logo="/etc/passwd")
    assert ImageRef(path="assets/img-1.png").path == "assets/img-1.png"


@pytest.mark.parametrize("block_type", sorted(BLOCK_MODELS))
def test_every_block_has_empty_detection(block_type):
    model = BLOCK_MODELS[block_type]
    required = {name for name, field in model.model_fields.items() if field.is_required()}
    payload: dict = {"type": block_type}
    if "table" in required:
        payload["table"] = {"columns": [{"key": "a"}]}
    if "url" in required:
        payload["url"] = "https://hocx.ch"
    block = model.model_validate(payload)
    assert isinstance(block.is_empty(), bool)


def test_meta_is_minimal():
    meta = DocumentMeta(document_type="todos", title="Pendenzen")
    assert meta.language == "de"
