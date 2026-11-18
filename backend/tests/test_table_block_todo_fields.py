"""Tabellenblock «Pro Pendenz»: Zeilen aus der Pendenz (todo_fields) im PDF und im Protokoll-Editor
(linked_todo), nur aus dem eigenen Mandanten."""
from __future__ import annotations

from datetime import date

from app.documents.context import BuildContext
from app.documents.providers.protocol import _event_field_rows
from app.services.linked_todo import load_linked_todo
from app.services.protocol_element_service import _linked_todo_read
from tests.factories import (
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)

TODO_FIELDS = [
    {"field": "task", "label": "", "enabled": True},
    {"field": "due_date", "label": "Bis", "enabled": True},
    {"field": "status", "label": "", "enabled": True},
    {"field": "origin", "label": "", "enabled": True},
    {"field": "participant", "label": "", "enabled": True},
]


def _todo(db, tenant_name: str, number: str):
    tenant = make_tenant(db, tenant_name)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number=number)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, {}, element_type_code="todo")
    block.block_title_snapshot = "Lager"
    todo = make_protocol_todo(db, block.id, task="Lagerhaus reservieren")
    todo.due_date = date(2026, 12, 1)
    db.flush()
    return tenant, todo


def _config(todo_id: int) -> dict:
    return {"repeat_source_type": "todo", "repeat_source_id": str(todo_id), "todo_fields": TODO_FIELDS}


def test_pdf_rows_come_from_the_linked_todo(db):
    tenant, todo = _todo(db, "Pendenz PDF", "41")
    rows = _event_field_rows(BuildContext(db=db, tenant_id=tenant.id, language="de"), _config(todo.id))
    # Leerer Wert (keine zugewiesene Person) fällt weg, eigenes Label gilt
    assert [row.label for row in rows] == ["Aufgabe", "Bis", "Status", "Herkunft"]
    text = str([row.model_dump() for row in rows])
    assert "Lagerhaus reservieren" in text and "01.12.2026" in text and "Offen" in text and "41 · Lager" in text


def test_editor_gets_the_linked_todo(db):
    tenant, todo = _todo(db, "Pendenz Editor", "42")
    read = _linked_todo_read(db, _config(todo.id), tenant.id)
    assert read is not None
    assert (read.task, read.status_code, read.origin) == ("Lagerhaus reservieren", "open", "42 · Lager")
    # Ohne Pendenzfelder keine Abfrage, ohne «Pro Pendenz» ohnehin nicht
    assert _linked_todo_read(db, {**_config(todo.id), "todo_fields": []}, tenant.id) is None
    assert _linked_todo_read(db, {"repeat_source_type": "event", "repeat_source_id": str(todo.id)}, tenant.id) is None


def test_foreign_tenant_todo_is_never_loaded(db):
    _, todo = _todo(db, "Pendenz Fremd", "43")
    other = make_tenant(db, "Pendenz Andere")
    assert load_linked_todo(db, _config(todo.id), other.id) is None
    assert _event_field_rows(BuildContext(db=db, tenant_id=other.id, language="de"), _config(todo.id)) == []
