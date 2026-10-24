"""Vorlagen-Abgleich offener Protokolle (ProtocolService.sync_with_template): Änderungen an
der Vorlage (neue/entfernte Elemente, Texte, Filter, Zeilen) gelangen in ein bestehendes
Protokoll, erfasste Daten (Texte, Todos, Werte) bleiben an den bestehenden Blöcken.

Wie in test_protocol_number_cycle_rank.py: pro Test höchstens ein create_from_template -
weitere Protokolle/Elemente werden direkt angelegt.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    ElementDefinition,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolText,
    ProtocolTodo,
    Template,
    TemplateElement,
    TodoStatus,
)
from app.schemas.protocol import ProtocolCreateFromTemplate
from app.services.protocol_service import ProtocolService

from tests.factories import (
    element_type_id,
    make_element_definition,
    make_event,
    make_template,
    make_template_element,
    make_tenant,
)

RENDER_TYPE_KEY_VALUE = 5
RENDER_TYPE_PARAGRAPH = 2


def _block(db, *, code: str, title: str, sort_index: int = 10, default_content: str = "", configuration_json=None,
           render_type_id: int = RENDER_TYPE_PARAGRAPH, description: str | None = None) -> dict:
    return {
        "id": sort_index, "title": title, "description": description, "block_title": None,
        "default_content": default_content, "copy_from_last_protocol": False,
        "element_type_id": element_type_id(db, code), "render_type_id": render_type_id,
        "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
        "sort_index": sort_index, "render_order": sort_index,
        "configuration_json": configuration_json or {},
    }


def _set_blocks(db, definition: ElementDefinition, blocks: list[dict]) -> None:
    definition.configuration_json = {**(definition.configuration_json or {}), "blocks": blocks}
    db.add(definition)
    db.flush()


def _create(db, template: Template, protocol_date: date = date(2026, 10, 1)) -> Protocol:
    protocol_id = ProtocolService().create_from_template(
        db,
        ProtocolCreateFromTemplate(template_id=template.public_id, protocol_number="P-1", protocol_date=protocol_date),
        tenant_id=template.tenant_id,
        created_by=None,
    )
    return db.get(Protocol, protocol_id)


def _elements(db, protocol_id: int) -> list[ProtocolElement]:
    return list(db.scalars(
        select(ProtocolElement).where(ProtocolElement.protocol_id == protocol_id).order_by(ProtocolElement.sort_index)
    ))


def _blocks(db, element_id: int) -> list[ProtocolElementBlock]:
    return list(db.scalars(
        select(ProtocolElementBlock)
        .where(ProtocolElementBlock.protocol_element_id == element_id)
        .order_by(ProtocolElementBlock.sort_index)
    ))


def _text(db, block_id: int) -> str | None:
    return db.scalar(select(ProtocolText.content).where(ProtocolText.protocol_element_block_id == block_id))


def _setup(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock")
    notes = make_element_definition(db, tenant.id, "Notizen", blocks=[
        _block(db, code="text", title="Notizen", default_content="Alte Vorgabe"),
    ])
    agenda = make_element_definition(db, tenant.id, "Traktanden", blocks=[
        _block(db, code="text", title="Traktanden", default_content="Vorgabe Traktanden"),
    ])
    form = make_element_definition(db, tenant.id, "Kontakt", blocks=[
        _block(db, code="form", title="Kontakt", render_type_id=RENDER_TYPE_KEY_VALUE, configuration_json={"rows": [
            {"id": "r1", "label": "Ort", "row_type": "text"},
        ]}),
    ])
    removed = make_element_definition(db, tenant.id, "Wird entfernt", blocks=[
        _block(db, code="text", title="Wird entfernt", default_content=""),
    ])
    for index, definition in enumerate((notes, agenda, form, removed)):
        make_template_element(db, template.id, definition.id, sort_index=(index + 1) * 10, section_name=definition.title)
    protocol = _create(db, template)
    return tenant, template, protocol, {"notes": notes, "agenda": agenda, "form": form, "removed": removed}


def test_sync_applies_template_changes_and_keeps_entered_data(db):
    tenant, template, protocol, defs = _setup(db)
    elements = _elements(db, protocol.id)
    assert [e.element_title_snapshot for e in elements] == ["Notizen", "Traktanden", "Kontakt", "Wird entfernt"]
    notes_block = _blocks(db, elements[0].id)[0]
    agenda_block = _blocks(db, elements[1].id)[0]
    form_block = _blocks(db, elements[2].id)[0]

    # Im Protokoll erfasst: eigener Text, ein Todo und ein Formularwert.
    db.get(ProtocolText, db.scalar(select(ProtocolText.id).where(ProtocolText.protocol_element_block_id == agenda_block.id))).content = "Eigener Text"
    status_id = db.scalar(select(TodoStatus.id).limit(1))
    db.add(ProtocolTodo(tenant_id=tenant.id, protocol_element_block_id=agenda_block.id, task="Offen", todo_status_id=status_id))
    form_config = dict(form_block.configuration_snapshot_json)
    form_config["rows"] = [{**form_config["rows"][0], "text_value": "Bern"}]
    form_block.configuration_snapshot_json = form_config
    db.flush()

    # Vorlage geändert: neuer Titel + neue Vorgabe, neue Formularzeile, neues Element,
    # ein Element entfernt.
    defs["notes"].title = "Notizen neu"
    _set_blocks(db, defs["notes"], [_block(db, code="text", title="Notizen neu", default_content="Neue Vorgabe", description="Hinweis")])
    _set_blocks(db, defs["agenda"], [_block(db, code="text", title="Traktanden", default_content="Andere Vorgabe")])
    _set_blocks(db, defs["form"], [_block(db, code="form", title="Kontakt", render_type_id=RENDER_TYPE_KEY_VALUE, configuration_json={"rows": [
        {"id": "r1", "label": "Ort (neu)", "row_type": "text"},
        {"id": "r2", "label": "Zeit", "row_type": "text"},
    ]})])
    added = make_element_definition(db, tenant.id, "Neu", blocks=[_block(db, code="text", title="Neu", default_content="Neu da")])
    make_template_element(db, template.id, added.id, sort_index=15, section_name="Neu")
    db.delete(db.scalar(select(TemplateElement).where(TemplateElement.element_definition_id == defs["removed"].id)))
    db.flush()

    summary = ProtocolService().sync_with_template(db, protocol.id)
    db.expire_all()

    assert summary["applied"] is True
    assert summary["added_elements"] == ["Neu"]
    assert summary["removed_elements"] == ["Wird entfernt"]
    assert summary["kept_elements"] == []

    elements = _elements(db, protocol.id)
    assert [e.element_title_snapshot for e in elements] == ["Notizen neu", "Neu", "Traktanden", "Kontakt"]
    # Bestehende Blöcke bleiben dieselben (IDs), Inhalte aus der Vorlage aktualisiert.
    synced_notes = _blocks(db, elements[0].id)
    assert [b.id for b in synced_notes] == [notes_block.id]
    assert synced_notes[0].title_snapshot == "Notizen neu"
    assert synced_notes[0].description_snapshot == "Hinweis"
    assert _text(db, notes_block.id) == "Neue Vorgabe"  # unveränderte Vorgabe folgt der Vorlage
    assert _text(db, _blocks(db, elements[1].id)[0].id) == "Neu da"
    # Eigener Text und Todo bleiben.
    assert [b.id for b in _blocks(db, elements[2].id)] == [agenda_block.id]
    assert _text(db, agenda_block.id) == "Eigener Text"
    assert db.scalar(select(ProtocolTodo.task).where(ProtocolTodo.protocol_element_block_id == agenda_block.id)) == "Offen"
    # Formular: neue Beschriftung + neue Zeile, erfasster Wert bleibt.
    rows = db.get(ProtocolElementBlock, form_block.id).configuration_snapshot_json["rows"]
    assert [(r["id"], r["label"], r["text_value"]) for r in rows] == [("r1", "Ort (neu)", "Bern"), ("r2", "Zeit", "")]
    assert db.get(Protocol, protocol.id).template_version == db.get(Template, template.id).version


def test_dry_run_reports_without_changing_anything(db):
    tenant, template, protocol, defs = _setup(db)
    before = [(e.id, e.sort_index, e.element_title_snapshot) for e in _elements(db, protocol.id)]
    defs["notes"].title = "Notizen neu"
    _set_blocks(db, defs["notes"], [_block(db, code="text", title="Notizen neu", default_content="Neue Vorgabe")])

    summary = ProtocolService().sync_with_template(db, protocol.id, dry_run=True)
    db.expire_all()

    assert summary["applied"] is False
    assert "Notizen neu" in summary["updated_elements"]
    assert [(e.id, e.sort_index, e.element_title_snapshot) for e in _elements(db, protocol.id)] == before


def test_removed_element_with_content_is_kept(db):
    tenant, template, protocol, defs = _setup(db)
    removed_element = _elements(db, protocol.id)[3]
    removed_block = _blocks(db, removed_element.id)[0]
    db.scalar(select(ProtocolText).where(ProtocolText.protocol_element_block_id == removed_block.id)).content = "Wichtig"
    db.delete(db.scalar(select(TemplateElement).where(TemplateElement.element_definition_id == defs["removed"].id)))
    db.flush()

    summary = ProtocolService().sync_with_template(db, protocol.id)
    db.expire_all()

    assert summary["kept_elements"] == ["Wird entfernt"]
    assert summary["removed_elements"] == []
    assert _elements(db, protocol.id)[-1].id == removed_element.id
    assert _text(db, removed_block.id) == "Wichtig"


def test_event_filter_change_adds_and_drops_empty_repeat_blocks(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    hock = make_event(db, tenant.id, title="Hock", event_date=date(2026, 10, 5))
    lager = make_event(db, tenant.id, title="Lager", event_date=date(2026, 10, 7))
    hock.tag = "hock"
    lager.tag = "lager"
    db.flush()
    def repeat(tag: str) -> dict:
        return {"repeat_source": "event", "repeat_event_filter": {"tags": [tag], "range": {"mode": "window", "start_days": 0, "end_days": 14}}}

    definition = make_element_definition(db, tenant.id, "Termine", blocks=[
        _block(db, code="text", title="{title}", configuration_json=repeat("hock")),
    ])
    make_template_element(db, template.id, definition.id, sort_index=10, section_name="Termine")
    protocol = _create(db, template)
    element = _elements(db, protocol.id)[0]
    assert [b.title_snapshot for b in _blocks(db, element.id)] == ["Hock"]

    _set_blocks(db, definition, [_block(db, code="text", title="{title}", configuration_json=repeat("lager"))])
    summary = ProtocolService().sync_with_template(db, protocol.id)
    db.expire_all()

    assert [b.title_snapshot for b in _blocks(db, element.id)] == ["Lager"]
    assert _blocks(db, element.id)[0].configuration_snapshot_json["repeat_event_filter"]["tags"] == ["lager"]
    assert (summary["added_blocks"], summary["removed_blocks"]) == (1, 1)


def test_closed_protocol_cannot_be_synced(db):
    tenant, template, protocol, defs = _setup(db)
    protocol.status = "abgeschlossen"
    db.flush()
    with pytest.raises(HTTPException) as exc_info:
        ProtocolService().sync_with_template(db, protocol.id)
    assert exc_info.value.status_code == 409
