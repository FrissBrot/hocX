"""Vorlagenversion zählt inhaltliche Änderungen (Migration 0214) und Protokolle zeigen, ob ihre
Vorlage seit dem Erstellen bzw. letzten Abgleich geändert wurde (template_latest_version).

Die Tests laufen in einer einzigen Transaktion (conftest.db). Die Version steigt höchstens einmal
je Vorlage und Transaktion; _next_transaction setzt diese Markierung zurück, um eine weitere
Speicherung in einem neuen Request nachzubilden.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select, text

from app.api.routes.protocols import _build_protocol_reads
from app.models import ElementDefinition, Protocol, Template, TemplateElement
from app.schemas.protocol import ProtocolCreateFromTemplate
from app.schemas.template import ElementDefinitionUpdate, TemplateElementBehaviorUpdate, TemplateElementUpdate
from app.services.element_definition_service import ElementDefinitionService
from app.services.protocol_service import ProtocolService
from app.services.template_element_service import TemplateElementService

from tests.factories import element_type_id, make_element_definition, make_event, make_template, make_template_element, make_tenant

REPEAT = {"repeat_source": "event", "repeat_event_filter": {"tags": ["hock"], "range": {"mode": "window", "start_days": 0, "end_days": 14}}}


def _fields(order: list[str]) -> list[dict]:
    return [{"field": field, "label": "", "enabled": True} for field in order]


def _block(db, *, title: str = "{title}", order: list[str] | None = None, rows: list | None = None) -> dict:
    return {
        "id": 1, "title": title, "description": None, "block_title": None, "default_content": None,
        "copy_from_last_protocol": False, "element_type_id": element_type_id(db, "form"), "render_type_id": 5,
        "sort_index": 10,
        "configuration_json": {**REPEAT, "rows": rows or [], "event_fields": _fields(order or ["program", "location"])},
    }


def _version(db, template_id: int) -> int:
    return db.scalar(select(Template.version).where(Template.id == template_id))


def _next_transaction(db, template_id: int) -> None:
    db.execute(text("SELECT set_config('hocx.template_version_bumped_' || :id, '', true)"), {"id": template_id})


def _setup(db, *, with_protocol: bool = True):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock")
    event = make_event(db, tenant.id, title="4. Hock", event_date=date(2026, 10, 5))
    event.tag = "hock"
    db.flush()
    definition = make_element_definition(db, tenant.id, "Anlass", blocks=[_block(db)])
    template_element = make_template_element(db, template.id, definition.id, sort_index=10, section_name="Anlass")
    # Einmal über den Service speichern, damit die Blöcke im normalisierten Format liegen wie im
    # Betrieb (sonst wäre schon «unverändert speichern» eine Änderung); noch ohne Protokoll.
    # (ohne Commit: create_from_template verträgt in der Test-Transaktion keinen vorherigen Commit)
    definition.configuration_json = {
        "blocks": ElementDefinitionService()._normalize_blocks(db, [_block(db)], tenant_id=tenant.id)
    }
    db.add(definition)
    db.flush()
    protocol = None
    if with_protocol:
        protocol_id = ProtocolService().create_from_template(
            db,
            ProtocolCreateFromTemplate(template_id=template.public_id, protocol_number="P-1", protocol_date=date(2026, 10, 1)),
            tenant_id=tenant.id,
            created_by=None,
        )
        protocol = db.get(Protocol, protocol_id)
    return tenant, template, template_element, definition, protocol


def _save(db, definition: ElementDefinition, block: dict, **extra) -> None:
    ElementDefinitionService().update_element_definition(db, definition.id, ElementDefinitionUpdate(blocks=[block], **extra))
    db.expire_all()


def _latest(db, protocol: Protocol) -> tuple[int, int | None]:
    read = _build_protocol_reads(db, [db.get(Protocol, protocol.id)])[0]
    return read.template_version, read.template_latest_version


def test_version_rises_once_per_content_change_and_not_on_plain_save(db):
    _, template, _, definition, protocol = _setup(db)
    assert _version(db, template.id) == 1
    assert _latest(db, protocol) == (1, 1)

    _save(db, definition, _block(db))  # unverändert gespeichert
    assert _version(db, template.id) == 1

    _save(db, definition, _block(db, rows=[{"id": "r1", "label": "Ort", "row_type": "text"}]))
    assert _version(db, template.id) == 2
    # Weitere Änderung in derselben Transaktion: keine zweite Erhöhung
    _save(db, definition, _block(db, title="Neu {title}"))
    assert _version(db, template.id) == 2
    _next_transaction(db, template.id)
    _save(db, definition, _block(db, title="Noch neuer {title}"))
    assert _version(db, template.id) == 3
    assert _latest(db, protocol) == (1, 3)


def test_template_element_changes_count(db):
    tenant, template, template_element, definition, _ = _setup(db)
    service = TemplateElementService()

    service.update_template_element(db, template_element.id, TemplateElementUpdate(sort_index=10))
    assert _version(db, template.id) == 1  # gleicher Wert

    service.update_block_behavior(db, template_element.id, TemplateElementBehaviorUpdate(scope="block", block_id=1, is_visible=False))
    assert _version(db, template.id) == 2

    _next_transaction(db, template.id)
    other = make_element_definition(db, tenant.id, "Notizen", blocks=[])
    added = make_template_element(db, template.id, other.id, sort_index=20, section_name="Notizen")
    assert _version(db, template.id) == 3

    _next_transaction(db, template.id)
    db.delete(db.get(TemplateElement, added.id))
    db.flush()
    db.expire_all()
    assert _version(db, template.id) == 4


def test_templates_without_protocols_keep_their_version(db):
    _, template, _, definition, _ = _setup(db, with_protocol=False)
    _save(db, definition, _block(db, title="Anders {title}"))
    assert _version(db, template.id) == 1


def test_sync_brings_the_protocol_up_to_date(db):
    _, template, _, definition, protocol = _setup(db)
    _save(db, definition, _block(db, title="Anders {title}"))
    assert _latest(db, protocol) == (1, 2)
    ProtocolService().sync_with_template(db, protocol.id)
    db.expire_all()
    assert _latest(db, protocol) == (2, 2)


def test_field_order_only_change_keeps_open_protocols_current(db):
    # Die Feldanordnung kommt per propagate_source_fields direkt an - kein Hinweis nötig.
    _, template, _, definition, protocol = _setup(db)
    _save(db, definition, _block(db, order=["location", "program"]))
    assert _version(db, template.id) == 2
    assert _latest(db, protocol) == (2, 2)


def test_field_order_only_change_does_not_advance_held_or_outdated_protocols(db):
    _, template, _, definition, protocol = _setup(db)
    protocol.status = "durchgeführt"
    db.flush()
    _save(db, definition, _block(db, order=["location", "program"]))
    assert _latest(db, protocol) == (1, 2)


def test_foreign_template_using_the_definition_is_not_bumped(db):
    # Inkonsistenter Altbestand: ein fremdes Traktandum zeigt auf unseren Baustein.
    _, template, _, definition, _ = _setup(db)
    foreign = make_tenant(db, "Fremd")
    foreign_template = make_template(db, foreign.id, name="Fremd")
    make_template_element(db, foreign_template.id, definition.id, sort_index=10, section_name="Fremd")
    db.add(Protocol(
        tenant_id=foreign.id, template_id=foreign_template.id, template_version=1, protocol_number="F-1",
        title="Fremd", protocol_date=date(2026, 10, 1), status="geplant",
    ))
    db.flush()
    foreign_version = _version(db, foreign_template.id)

    _save(db, definition, _block(db, title="Anders {title}"))

    assert _version(db, template.id) == 2
    assert _version(db, foreign_template.id) == foreign_version
