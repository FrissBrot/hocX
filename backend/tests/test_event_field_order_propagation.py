"""Reihenfolge der Terminfelder eines Tabellenblocks «Pro Termin» (config.event_fields).

Die im Baustein-Editor gesetzte Reihenfolge kam nicht im Protokoll-Editor an: Protokollblöcke
tragen einen Schnappschuss der Block-Konfiguration, ein bereits geplantes Protokoll behielt die
alte Reihenfolge. Speichern der Elementdefinition überträgt die Feldanordnung jetzt auf noch nicht
durchgeführte Protokolle (geplant/vorbereitet); durchgeführte und abgeschlossene bleiben.

Wie in test_protocol_template_sync.py: pro Test höchstens ein create_from_template.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models import ElementDefinition, Protocol, ProtocolElement, ProtocolElementBlock, TemplateElement
from app.schemas.protocol import ProtocolCreateFromTemplate
from app.schemas.template import ElementDefinitionUpdate
from app.services.element_definition_service import ElementDefinitionService
from app.services.protocol_service import ProtocolService
from app.services.template_element_service import TemplateElementService

from tests.factories import (
    element_type_id,
    make_element_definition,
    make_event,
    make_template,
    make_template_element,
    make_tenant,
)

RENDER_TYPE_KEY_VALUE = 5
REPEAT = {"repeat_source": "event", "repeat_event_filter": {"tags": ["hock"], "range": {"mode": "window", "start_days": 0, "end_days": 14}}}
# Bewusst nicht in der Standardreihenfolge (EVENT_FIELDS: program vor organizer_ids vor location …)
ORIGINAL = ["program", "organizer_ids", "leadership_ids", "location", "spezial_time1", "spezial_time2"]
REORDERED = ["location", "spezial_time1", "program", "spezial_time2", "organizer_ids", "leadership_ids"]


def _fields(order: list[str]) -> list[dict]:
    return [{"field": field, "label": "", "enabled": True} for field in order] + [{"field": "title", "label": "", "enabled": False}]


def _block(db, order: list[str]) -> dict:
    return {
        "id": 1, "title": "{title}", "description": None, "block_title": None, "default_content": None,
        "copy_from_last_protocol": False, "element_type_id": element_type_id(db, "form"),
        "render_type_id": RENDER_TYPE_KEY_VALUE, "sort_index": 10,
        "configuration_json": {**REPEAT, "rows": [], "event_fields": _fields(order)},
    }


def _order(config: dict) -> list[str]:
    return [item["field"] for item in config["event_fields"] if item.get("enabled")]


def _setup(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock")
    event = make_event(db, tenant.id, title="4. Hock", event_date=date(2026, 10, 5))
    event.tag = "hock"
    db.flush()
    definition = make_element_definition(db, tenant.id, "Anlass", blocks=[_block(db, ORIGINAL)])
    template_element = make_template_element(db, template.id, definition.id, sort_index=10, section_name="Anlass")
    protocol_id = ProtocolService().create_from_template(
        db,
        ProtocolCreateFromTemplate(template_id=template.public_id, protocol_number="P-1", protocol_date=date(2026, 10, 1)),
        tenant_id=tenant.id,
        created_by=None,
    )
    return tenant, template, template_element, definition, db.get(Protocol, protocol_id)


def _protocol_block(db, protocol_id: int) -> ProtocolElementBlock:
    return db.scalar(
        select(ProtocolElementBlock)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .where(ProtocolElement.protocol_id == protocol_id)
    )


def _save(db, definition: ElementDefinition, order: list[str]) -> list[ProtocolElementBlock]:
    changed: list[ProtocolElementBlock] = []
    ElementDefinitionService().update_element_definition(
        db, definition.id, ElementDefinitionUpdate(blocks=[_block(db, order)]), changed_protocol_blocks=changed
    )
    db.expire_all()
    return changed


def test_new_protocol_keeps_the_configured_field_order(db):
    _, _, _, _, protocol = _setup(db)
    block = _protocol_block(db, protocol.id)
    assert block.configuration_snapshot_json["repeat_source_type"] == "event"
    assert _order(block.configuration_snapshot_json) == ORIGINAL


@pytest.mark.parametrize("status", ["geplant", "vorbereitet"])
def test_reordering_in_the_template_reaches_open_protocols(db, status):
    _, _, _, definition, protocol = _setup(db)
    protocol.status = status
    db.flush()
    before = _protocol_block(db, protocol.id)
    version_before = before.config_version
    rows_before = before.configuration_snapshot_json["rows"]

    changed = _save(db, definition, REORDERED)

    block = _protocol_block(db, protocol.id)
    assert [item.id for item in changed] == [block.id]
    assert _order(block.configuration_snapshot_json) == REORDERED
    # Nur die Feldanordnung wird ersetzt, der Rest des Schnappschusses bleibt
    assert block.configuration_snapshot_json["rows"] == rows_before
    assert block.configuration_snapshot_json["repeat_source_id"] is not None
    # Optimistische Sperre offener Editoren (CONC-005) sieht die Änderung
    assert block.config_version > version_before
    # Die Definition selbst behält die Reihenfolge ebenfalls
    stored = db.get(ElementDefinition, definition.id).configuration_json["blocks"][0]["configuration_json"]
    assert _order(stored) == REORDERED


@pytest.mark.parametrize("status", ["durchgeführt", "abgeschlossen"])
def test_held_and_closed_protocols_keep_their_snapshot(db, status):
    _, _, _, definition, protocol = _setup(db)
    protocol.status = status
    db.flush()

    changed = _save(db, definition, REORDERED)

    assert changed == []
    assert _order(_protocol_block(db, protocol.id).configuration_snapshot_json) == ORIGINAL


def test_unchanged_save_touches_no_protocol(db):
    _, _, _, definition, protocol = _setup(db)
    version_before = _protocol_block(db, protocol.id).config_version
    assert _save(db, definition, ORIGINAL) == []
    assert _protocol_block(db, protocol.id).config_version == version_before


def test_template_sync_applies_the_saved_order(db):
    # «Mit Vorlage abgleichen» übernimmt die Reihenfolge ebenfalls (Definition direkt geändert,
    # also ohne den Übertrag beim Speichern)
    _, _, _, definition, protocol = _setup(db)
    definition.configuration_json = {"blocks": [_block(db, REORDERED)]}
    db.add(definition)
    db.flush()
    ProtocolService().sync_with_template(db, protocol.id)
    db.expire_all()
    assert _order(_protocol_block(db, protocol.id).configuration_snapshot_json) == REORDERED


def test_detached_agenda_item_follows_its_own_copy(db):
    # «Nur in dieser Vorlage ändern»: das Traktandum bekommt eine Kopie; Änderungen am
    # Bibliotheksbaustein erreichen seine Protokolle nicht mehr, Änderungen an der Kopie schon.
    tenant, _, template_element, definition, protocol = _setup(db)
    definition.is_library = True
    db.add(definition)
    db.flush()
    TemplateElementService().detach_definition(db, template_element.id)
    copy_id = db.scalar(select(TemplateElement.element_definition_id).where(TemplateElement.id == template_element.id))
    assert copy_id != definition.id

    assert _save(db, definition, REORDERED) == []
    assert _order(_protocol_block(db, protocol.id).configuration_snapshot_json) == ORIGINAL

    copy = db.get(ElementDefinition, copy_id)
    assert len(_save(db, copy, REORDERED)) == 1
    assert _order(_protocol_block(db, protocol.id).configuration_snapshot_json) == REORDERED
    assert tenant.id == copy.tenant_id


def test_protocols_of_other_tenants_are_not_touched(db):
    # Altbestand: ein fremdes Traktandum zeigt auf unseren Baustein - dessen Protokolle bleiben.
    _, _, _, definition, protocol = _setup(db)
    foreign = make_tenant(db, "Fremd")
    foreign_template = make_template(db, foreign.id, name="Fremd")
    foreign_element = make_template_element(db, foreign_template.id, definition.id, sort_index=10, section_name="Fremd")
    foreign_protocol = Protocol(
        tenant_id=foreign.id, template_id=foreign_template.id, template_version=1, protocol_number="F-1",
        title="Fremd", protocol_date=date(2026, 10, 1), status="geplant",
    )
    db.add(foreign_protocol)
    db.flush()
    own_block = _protocol_block(db, protocol.id)
    foreign_protocol_element = ProtocolElement(
        protocol_id=foreign_protocol.id, template_element_id=foreign_element.id, sort_index=10,
        section_name_snapshot="Fremd", element_title_snapshot="Fremd", section_order_snapshot=10,
        is_required_snapshot=False, is_visible_snapshot=True, export_visible_snapshot=True,
    )
    db.add(foreign_protocol_element)
    db.flush()
    foreign_block = ProtocolElementBlock(
        protocol_element_id=foreign_protocol_element.id, element_definition_id=definition.id,
        element_type_id=own_block.element_type_id, render_type_id=own_block.render_type_id,
        title_snapshot="Fremd", is_editable_snapshot=True, allows_multiple_values_snapshot=False,
        sort_index=10, render_order=10, is_required_snapshot=False, is_visible_snapshot=True,
        export_visible_snapshot=True, configuration_snapshot_json=dict(own_block.configuration_snapshot_json),
    )
    db.add(foreign_block)
    db.flush()
    foreign_block_id = foreign_block.id

    changed = _save(db, definition, REORDERED)

    assert [item.id for item in changed] == [own_block.id]
    assert _order(db.get(ProtocolElementBlock, foreign_block_id).configuration_snapshot_json) == ORIGINAL
