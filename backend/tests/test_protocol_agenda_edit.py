"""Traktanden im Protokoll bearbeiten (Protokoll-Editor 1a, Migration 0270): hinzufügen,
umbenennen, ausblenden, atomar sortieren; Vorlagen-Abgleich, PDF, Folgeprotokoll; Abweichungen
gegenüber der Vorlage beim Abschliessen und Übernahme einer Auswahl; Mandantentrennung.

Wichtigste Regel: Änderungen im Protokoll ändern NIE die Vorlage - nur die ausdrückliche
Übernahme (templates.edit) tut das."""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.api.routes import protocol_elements as element_routes
from app.api.routes import protocols as protocol_routes
from app.models import (
    ElementDefinition,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolText,
    Template,
    TemplateElement,
)
from app.schemas.protocol import (
    ProtocolCreateFromTemplate,
    ProtocolElementCreate,
    ProtocolElementOrderUpdate,
    ProtocolElementUpdate,
    ProtocolTemplateChangesApply,
)
from app.services.protocol_service import ProtocolService

from tests.factories import (
    element_type_id,
    make_current_user,
    make_element_definition,
    make_template,
    make_template_element,
    make_tenant,
    system_role_permissions,
)

RENDER_TYPE_PARAGRAPH = 2
# Schreibende Rolle ohne Vorlagenrecht (sieht wie «writer» auch Entwürfe)
EDITOR = system_role_permissions("writer") - {"templates.edit"}


def _text_block(db, title: str) -> dict:
    return {
        "id": 10, "title": title, "description": None, "block_title": None,
        "default_content": "", "copy_from_last_protocol": False,
        "element_type_id": element_type_id(db, "text"), "render_type_id": RENDER_TYPE_PARAGRAPH,
        "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
        "sort_index": 10, "render_order": 10, "configuration_json": {},
    }


def _create(db, template: Template, number: str = "P-1", protocol_date: date = date(2026, 10, 1)) -> Protocol:
    protocol_id = ProtocolService().create_from_template(
        db,
        ProtocolCreateFromTemplate(template_id=template.public_id, protocol_number=number, protocol_date=protocol_date),
        tenant_id=template.tenant_id,
        created_by=None,
    )
    return db.get(Protocol, protocol_id)


def _following(db, template: Template) -> Protocol:
    """Folgeprotokoll aus dem aktuellen Stand der Vorlage. Je Test geht nur ein create_from_template
    (Savepoint der Test-Session); der Abgleich eines leeren Protokolls materialisiert die Vorlage
    mit demselben Code (_materialize_template_element)."""
    from tests.factories import make_protocol

    protocol = make_protocol(db, template.tenant_id, template.id, protocol_number="P-2", protocol_date=date(2026, 11, 1))
    ProtocolService().sync_with_template(db, protocol.id)
    return protocol


def _setup(db, *, library: bool = False):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock")
    definitions = []
    for index, title in enumerate(("Begrüssung", "Finanzen", "Varia")):
        definition = make_element_definition(db, tenant.id, title, blocks=[_text_block(db, title)])
        definition.is_library = library
        definitions.append(definition)
        make_template_element(db, template.id, definition.id, sort_index=(index + 1) * 10, section_name=title)
    db.flush()
    protocol = _create(db, template)
    admin = make_current_user(tenant.id, role="admin")
    return tenant, template, protocol, admin


def _elements(db, protocol_id: int) -> list[ProtocolElement]:
    return list(db.scalars(
        select(ProtocolElement).where(ProtocolElement.protocol_id == protocol_id).order_by(ProtocolElement.sort_index)
    ))


def _titles(db, protocol_id: int) -> list[str]:
    return [element.element_title_snapshot or element.section_name_snapshot for element in _elements(db, protocol_id)]


def _template_titles(db, template_id: int) -> list[str]:
    return list(db.scalars(
        select(ElementDefinition.title)
        .join(TemplateElement, TemplateElement.element_definition_id == ElementDefinition.id)
        .where(TemplateElement.template_id == template_id)
        .order_by(TemplateElement.sort_index)
    ))


def _template_snapshot(db, template: Template):
    db.refresh(template)
    rows = db.execute(
        select(TemplateElement.id, TemplateElement.sort_index, TemplateElement.is_visible, ElementDefinition.title)
        .join(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
        .where(TemplateElement.template_id == template.id)
        .order_by(TemplateElement.sort_index)
    ).all()
    return template.version, [tuple(row) for row in rows]


def _add(db, protocol: Protocol, user, title: str, after: ProtocolElement | None = None):
    return element_routes.create_protocol_element(
        protocol.public_id, ProtocolElementCreate(title=title, after_element_id=after.public_id if after else None), db=db, user=user
    )


def _status(call) -> int:
    with pytest.raises(HTTPException) as exc_info:
        call()
    return exc_info.value.status_code


# ── Hinzufügen ──────────────────────────────────────────────────────────────────────────────


def test_add_element_only_in_protocol_with_text_block(db):
    _tenant, template, protocol, admin = _setup(db)
    before = _template_snapshot(db, template)
    first = _elements(db, protocol.id)[0]

    read = _add(db, protocol, admin, "  Neuer   Punkt ", after=first)

    assert read.origin == "protocol"
    assert read.template_element_id is None
    assert read.section_name_snapshot == "Neuer Punkt"
    assert len(read.blocks) == 1 and read.blocks[0].element_type_code == "text"
    assert read.blocks[0].text_content == ""
    assert _titles(db, protocol.id) == ["Begrüssung", "Neuer Punkt", "Finanzen", "Varia"]
    assert [element.sort_index for element in _elements(db, protocol.id)] == [10, 20, 30, 40]
    assert _template_snapshot(db, template) == before  # Vorlage unverändert


def test_add_element_at_end_stays_before_session_notes(db):
    tenant, _template, protocol, admin = _setup(db)
    ProtocolService().create_quick_todo(db, protocol_id=protocol.id, task="Etwas", tag="Sitzungsnotizen", created_by=None)
    _add(db, protocol, admin, "Am Ende")
    elements = _elements(db, protocol.id)
    assert [element.origin for element in elements][-2:] == ["protocol", "session"]


def test_add_element_validation_and_closed_protocol(db):
    _tenant, _template, protocol, admin = _setup(db)
    assert _status(lambda: _add(db, protocol, admin, "   ")) == 422
    assert _status(lambda: _add(db, protocol, admin, "x" * 201)) == 422
    protocol.status = "abgeschlossen"
    db.flush()
    assert _status(lambda: _add(db, protocol, admin, "Zu spät")) == 409


def test_add_element_requires_edit_permission(db):
    tenant, _template, protocol, _admin = _setup(db)
    reader = make_current_user(tenant.id, permissions=frozenset({"meetings.read"}))
    assert _status(lambda: _add(db, protocol, reader, "Nein")) == 403


# ── Vorlagen-Abgleich, Folgeprotokoll, PDF ──────────────────────────────────────────────────


def test_sync_keeps_added_element_rename_and_visibility(db):
    _tenant, template, protocol, admin = _setup(db)
    begr, fin, varia = _elements(db, protocol.id)
    _add(db, protocol, admin, "Lokal leer", after=fin)
    element_routes.patch_protocol_element(begr.public_id, ProtocolElementUpdate(section_name_snapshot="Willkommen"), db=db, user=admin)
    element_routes.patch_protocol_element(varia.public_id, ProtocolElementUpdate(is_visible_snapshot=False), db=db, user=admin)
    # Vorlage ändert inzwischen den Titel von «Begrüssung»
    definition = db.get(ElementDefinition, db.get(TemplateElement, begr.template_element_id).element_definition_id)
    definition.title = "Begrüssung neu"
    db.flush()

    summary = ProtocolService().sync_with_template(db, protocol.id)

    assert summary["applied"]
    assert _titles(db, protocol.id) == ["Willkommen", "Finanzen", "Lokal leer", "Varia"]
    begr = db.get(ProtocolElement, begr.id)
    assert begr.template_title_snapshot == "Begrüssung neu"
    assert db.get(ProtocolElement, varia.id).is_visible_snapshot is False


def test_sync_keeps_custom_order_and_places_new_template_element_after_its_predecessor(db):
    tenant, template, protocol, admin = _setup(db)
    begr, fin, varia = _elements(db, protocol.id)
    element_routes.put_protocol_element_order(protocol.public_id, ProtocolElementOrderUpdate(
        element_ids=[varia.public_id, begr.public_id, fin.public_id],
        expected_element_ids=[begr.public_id, fin.public_id, varia.public_id],
    ), db=db, user=admin)
    extra = make_element_definition(db, tenant.id, "Neu in Vorlage", blocks=[_text_block(db, "Neu in Vorlage")])
    make_template_element(db, template.id, extra.id, sort_index=15, section_name="Neu in Vorlage")
    db.flush()

    ProtocolService().sync_with_template(db, protocol.id)

    assert _titles(db, protocol.id) == ["Varia", "Begrüssung", "Neu in Vorlage", "Finanzen"]


def test_next_protocol_from_template_does_not_contain_added_element(db):
    _tenant, template, protocol, admin = _setup(db)
    _add(db, protocol, admin, "Nur einmal")
    following = _following(db, template)
    assert "Nur einmal" not in _titles(db, following.id)


def test_pdf_contains_added_element_and_skips_hidden(db):
    from app.documents.context import BuildContext
    from app.documents.providers.protocol import element_blocks

    tenant, _template, protocol, admin = _setup(db)
    begr, _fin, _varia = _elements(db, protocol.id)
    _add(db, protocol, admin, "Neu im PDF")
    element_routes.patch_protocol_element(begr.public_id, ProtocolElementUpdate(is_visible_snapshot=False), db=db, user=admin)
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=protocol)
    titles = [element.title for element in element_blocks(ctx, protocol)]
    assert titles == ["Finanzen", "Varia", "Neu im PDF"]


# ── Umbenennen / Ausblenden ─────────────────────────────────────────────────────────────────


def test_rename_back_to_template_title_clears_deviation(db):
    _tenant, _template, protocol, admin = _setup(db)
    begr = _elements(db, protocol.id)[0]
    read = element_routes.patch_protocol_element(begr.public_id, ProtocolElementUpdate(section_name_snapshot="Hallo"), db=db, user=admin)
    assert read.template_title == "Begrüssung"
    read = element_routes.patch_protocol_element(begr.public_id, ProtocolElementUpdate(section_name_snapshot="Begrüssung"), db=db, user=admin)
    assert read.template_title is None
    assert _status(lambda: element_routes.patch_protocol_element(
        begr.public_id, ProtocolElementUpdate(section_name_snapshot=" "), db=db, user=admin
    )) == 422


def test_session_notes_cannot_be_renamed(db):
    tenant, _template, protocol, admin = _setup(db)
    ProtocolService().create_quick_todo(db, protocol_id=protocol.id, task="Etwas", tag="Sitzungsnotizen", created_by=None)
    session = _elements(db, protocol.id)[-1]
    assert session.origin == "session"
    assert _status(lambda: element_routes.patch_protocol_element(
        session.public_id, ProtocolElementUpdate(section_name_snapshot="Anders"), db=db, user=admin
    )) == 409


# ── Sortieren ───────────────────────────────────────────────────────────────────────────────


def test_reorder_is_atomic_and_detects_stale_order(db):
    _tenant, _template, protocol, admin = _setup(db)
    begr, fin, varia = _elements(db, protocol.id)
    current = [begr.public_id, fin.public_id, varia.public_id]

    result = element_routes.put_protocol_element_order(protocol.public_id, ProtocolElementOrderUpdate(
        element_ids=[fin.public_id, varia.public_id, begr.public_id], expected_element_ids=current,
    ), db=db, user=admin)
    assert result.element_ids == [fin.public_id, varia.public_id, begr.public_id]
    assert _titles(db, protocol.id) == ["Finanzen", "Varia", "Begrüssung"]
    assert db.get(Protocol, protocol.id).agenda_order_customized is True

    # Veraltete Ausgangsreihenfolge -> 409 mit aktueller Reihenfolge, nichts geändert
    with pytest.raises(HTTPException) as exc_info:
        element_routes.put_protocol_element_order(protocol.public_id, ProtocolElementOrderUpdate(
            element_ids=current, expected_element_ids=current,
        ), db=db, user=admin)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "order_conflict"
    assert exc_info.value.detail["element_ids"] == [str(fin.public_id), str(varia.public_id), str(begr.public_id)]
    assert _titles(db, protocol.id) == ["Finanzen", "Varia", "Begrüssung"]

    now = [fin.public_id, varia.public_id, begr.public_id]
    # Unvollständig (Menge stimmt nicht) -> 409, Duplikate -> 422
    assert _status(lambda: element_routes.put_protocol_element_order(protocol.public_id, ProtocolElementOrderUpdate(
        element_ids=now[:2], expected_element_ids=now,
    ), db=db, user=admin)) == 409
    assert _status(lambda: element_routes.put_protocol_element_order(protocol.public_id, ProtocolElementOrderUpdate(
        element_ids=[now[0], now[0], now[1]], expected_element_ids=now,
    ), db=db, user=admin)) == 422
    # Fremde Element-ID in der Liste -> 409 (Menge stimmt nicht), nie ein Zugriff darauf
    assert _status(lambda: element_routes.put_protocol_element_order(protocol.public_id, ProtocolElementOrderUpdate(
        element_ids=[now[0], now[1], uuid.uuid4()], expected_element_ids=now,
    ), db=db, user=admin)) == 409


# ── Abweichungen und Übernahme in die Vorlage ───────────────────────────────────────────────


def _make_all_changes(db, protocol, admin):
    begr, fin, varia = _elements(db, protocol.id)
    added = _add(db, protocol, admin, "Neuer Punkt", after=fin)
    element_routes.patch_protocol_element(begr.public_id, ProtocolElementUpdate(section_name_snapshot="Willkommen"), db=db, user=admin)
    element_routes.patch_protocol_element(varia.public_id, ProtocolElementUpdate(is_visible_snapshot=False), db=db, user=admin)
    ids = [element.public_id for element in _elements(db, protocol.id)]  # begr, fin, neu, varia
    element_routes.put_protocol_element_order(protocol.public_id, ProtocolElementOrderUpdate(
        element_ids=[ids[1], ids[0], ids[2], ids[3]], expected_element_ids=ids,
    ), db=db, user=admin)
    return begr, fin, varia, added


def test_template_changes_list_exact_deviations(db):
    tenant, template, protocol, admin = _setup(db)
    before = _template_snapshot(db, template)
    begr, fin, varia, added = _make_all_changes(db, protocol, admin)
    assert _template_snapshot(db, template) == before  # nichts davon ändert die Vorlage

    result = protocol_routes.get_protocol_template_changes(protocol.public_id, db=db, user=admin)
    changes = {change.kind: change for change in result.changes}
    assert result.can_apply is True
    assert set(changes) == {"added", "renamed", "visibility", "order"}
    assert changes["added"].title == "Neuer Punkt"
    # Nach dem Umsortieren steht «Willkommen» (Begrüssung) vor dem neuen Punkt
    assert changes["added"].after_title == "Willkommen"
    assert changes["renamed"].old_title == "Begrüssung" and changes["renamed"].new_title == "Willkommen"
    assert changes["visibility"].old_visible is True and changes["visibility"].new_visible is False
    assert [entry.title for entry in changes["order"].old_order] == ["Willkommen", "Finanzen", "Varia"]
    assert [entry.title for entry in changes["order"].new_order] == ["Finanzen", "Willkommen", "Varia"]

    editor = make_current_user(tenant.id, permissions=EDITOR)
    assert protocol_routes.get_protocol_template_changes(protocol.public_id, db=db, user=editor).can_apply is False


def test_apply_selected_changes_updates_template_once(db):
    tenant, template, protocol, admin = _setup(db)
    _begr, _fin, _varia, added = _make_all_changes(db, protocol, admin)
    old_version = db.get(Template, template.id).version
    protocol_version = db.get(Protocol, protocol.id).template_version
    changes = protocol_routes.get_protocol_template_changes(protocol.public_id, db=db, user=admin).changes
    keys = [change.key for change in changes if change.kind in ("added", "renamed")]

    result = protocol_routes.apply_protocol_template_changes(
        protocol.public_id, ProtocolTemplateChangesApply(keys=keys, expected_template_version=old_version), db=db, user=admin
    )

    assert sorted(result.applied) == sorted(keys)
    assert {change.kind for change in result.changes} == {"visibility", "order"}  # nicht gewählt: bleibt offen
    assert result.template_version == old_version + 1
    # Ohne «order»: neuer Punkt hinter seinem Vorgänger im Protokoll, sonst Vorlagen-Reihenfolge
    assert _template_titles(db, template.id) == ["Willkommen", "Neuer Punkt", "Finanzen", "Varia"]
    visible = db.scalars(select(TemplateElement.is_visible).where(TemplateElement.template_id == template.id)).all()
    assert all(visible)
    # Protokoll war auf Vorlagenstand -> rückt mit, und das neue Traktandum ist verknüpft
    refreshed = db.get(Protocol, protocol.id)
    assert protocol_version == old_version and refreshed.template_version == result.template_version
    linked = db.scalar(select(ProtocolElement).where(ProtocolElement.public_id == added.id))
    assert linked.template_element_id is not None and linked.origin == "protocol"
    audit = db.scalar(text("SELECT count(*) FROM audit_log WHERE action = 'template.agenda_changes_applied'"))
    assert audit == 1

    # Folgeprotokoll aus der Vorlage enthält den übernommenen Punkt, Abgleich lässt alles stehen
    following = _following(db, template)
    assert "Neuer Punkt" in _titles(db, following.id)
    ProtocolService().sync_with_template(db, protocol.id)
    assert "Neuer Punkt" in _titles(db, protocol.id)
    texts = db.scalars(
        select(ProtocolText.content)
        .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolText.protocol_element_block_id)
        .where(ProtocolElementBlock.protocol_element_id == linked.id)
    ).all()
    assert len(texts) == 1


def test_apply_order_and_visibility(db):
    _tenant, template, protocol, admin = _setup(db)
    _make_all_changes(db, protocol, admin)
    changes = protocol_routes.get_protocol_template_changes(protocol.public_id, db=db, user=admin).changes
    keys = [change.key for change in changes if change.kind in ("order", "visibility")]
    result = protocol_routes.apply_protocol_template_changes(
        protocol.public_id, ProtocolTemplateChangesApply(keys=keys), db=db, user=admin
    )
    assert {change.kind for change in result.changes} == {"added", "renamed"}
    assert _template_titles(db, template.id) == ["Finanzen", "Begrüssung", "Varia"]
    hidden = db.scalars(
        select(ElementDefinition.title)
        .join(TemplateElement, TemplateElement.element_definition_id == ElementDefinition.id)
        .where(TemplateElement.template_id == template.id, TemplateElement.is_visible.is_(False))
    ).all()
    assert hidden == ["Varia"]
    # Neue Protokolle übernehmen das Ausblenden
    following = _following(db, template)
    assert [element.is_visible_snapshot for element in _elements(db, following.id)] == [True, True, False]


def test_rename_of_library_block_only_changes_this_template(db):
    tenant, template, protocol, admin = _setup(db, library=True)
    begr = _elements(db, protocol.id)[0]
    other_template = make_template(db, tenant.id, name="Andere")
    shared_definition_id = db.get(TemplateElement, begr.template_element_id).element_definition_id
    make_template_element(db, other_template.id, shared_definition_id, sort_index=10, section_name="Begrüssung")
    db.flush()
    element_routes.patch_protocol_element(begr.public_id, ProtocolElementUpdate(section_name_snapshot="Hallo"), db=db, user=admin)

    protocol_routes.apply_protocol_template_changes(
        protocol.public_id, ProtocolTemplateChangesApply(keys=[f"renamed:{begr.public_id}"]), db=db, user=admin
    )

    assert _template_titles(db, template.id)[0] == "Hallo"
    assert _template_titles(db, other_template.id) == ["Begrüssung"]
    assert db.get(ElementDefinition, shared_definition_id).title == "Begrüssung"


def test_apply_requires_template_permission_and_detects_outdated_keys(db):
    tenant, template, protocol, admin = _setup(db)
    _make_all_changes(db, protocol, admin)
    before = _template_snapshot(db, template)
    editor = make_current_user(tenant.id, permissions=EDITOR)
    keys = ["order"]
    assert _status(lambda: protocol_routes.apply_protocol_template_changes(
        protocol.public_id, ProtocolTemplateChangesApply(keys=keys), db=db, user=editor
    )) == 403
    # Vorlagenrecht ohne Protokoll-Bearbeitungsrecht reicht nicht (Übernahme verknüpft das Protokoll)
    template_only = make_current_user(tenant.id, permissions=frozenset({"meetings.read", "templates.edit"}))
    assert _status(lambda: protocol_routes.apply_protocol_template_changes(
        protocol.public_id, ProtocolTemplateChangesApply(keys=keys), db=db, user=template_only
    )) == 403
    with pytest.raises(HTTPException) as exc_info:
        protocol_routes.apply_protocol_template_changes(
            protocol.public_id, ProtocolTemplateChangesApply(keys=[f"renamed:{uuid.uuid4()}"]), db=db, user=admin
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "changes_outdated"
    assert _status(lambda: protocol_routes.apply_protocol_template_changes(
        protocol.public_id, ProtocolTemplateChangesApply(keys=keys, expected_template_version=before[0] + 5), db=db, user=admin
    )) == 409
    assert _template_snapshot(db, template) == before


def test_closing_does_not_depend_on_changes_and_apply_works_after_closing(db):
    from app.schemas.protocol import ProtocolUpdate

    _tenant, template, protocol, admin = _setup(db)
    _make_all_changes(db, protocol, admin)
    service = ProtocolService()
    for status in ("vorbereitet", "durchgeführt", "abgeschlossen"):
        service.update_protocol(db, protocol.id, ProtocolUpdate(status=status), actor_user_id=None)
    assert db.get(Protocol, protocol.id).status == "abgeschlossen"
    result = protocol_routes.apply_protocol_template_changes(
        protocol.public_id, ProtocolTemplateChangesApply(keys=["order"]), db=db, user=admin
    )
    assert "order" in result.applied
    assert _template_titles(db, template.id)[:2] == ["Finanzen", "Begrüssung"]


def test_no_changes_for_untouched_protocol_even_if_template_changed(db):
    """Vorlagenänderungen nach dem Erstellen sind keine Abweichung des Protokolls."""
    _tenant, template, protocol, admin = _setup(db)
    rows = db.scalars(select(TemplateElement).where(TemplateElement.template_id == template.id).order_by(TemplateElement.sort_index)).all()
    rows[0].sort_index, rows[2].sort_index = 1000, 1001
    db.flush()
    rows[0].is_visible = False
    db.flush()
    assert protocol_routes.get_protocol_template_changes(protocol.public_id, db=db, user=admin).changes == []


# ── Mandantentrennung ───────────────────────────────────────────────────────────────────────


def test_foreign_tenant_ids_answer_404(db):
    _tenant, template, protocol, _admin = _setup(db)
    before = _template_snapshot(db, template)
    other = make_tenant(db, "Fremd")
    attacker = make_current_user(other.id, role="admin")
    element = _elements(db, protocol.id)[0]
    ids = [entry.public_id for entry in _elements(db, protocol.id)]

    assert _status(lambda: _add(db, protocol, attacker, "Fremd")) == 404
    assert _status(lambda: element_routes.put_protocol_element_order(protocol.public_id, ProtocolElementOrderUpdate(
        element_ids=list(reversed(ids)), expected_element_ids=ids,
    ), db=db, user=attacker)) == 404
    assert _status(lambda: element_routes.patch_protocol_element(
        element.public_id, ProtocolElementUpdate(section_name_snapshot="Fremd"), db=db, user=attacker
    )) == 404
    assert _status(lambda: protocol_routes.get_protocol_template_changes(protocol.public_id, db=db, user=attacker)) == 404
    assert _status(lambda: protocol_routes.apply_protocol_template_changes(
        protocol.public_id, ProtocolTemplateChangesApply(keys=["order"]), db=db, user=attacker
    )) == 404
    # Eigenes Protokoll, aber fremder Vorgänger -> 404
    own_template = make_template(db, other.id)
    own_protocol = _create_raw(db, other.id, own_template.id)
    assert _status(lambda: element_routes.create_protocol_element(
        own_protocol.public_id, ProtocolElementCreate(title="X", after_element_id=element.public_id), db=db, user=attacker
    )) == 404
    assert _titles(db, protocol.id) == ["Begrüssung", "Finanzen", "Varia"]
    assert _template_snapshot(db, template) == before


def _create_raw(db, tenant_id: int, template_id: int) -> Protocol:
    from tests.factories import make_protocol

    return make_protocol(db, tenant_id, template_id, status="geplant")
