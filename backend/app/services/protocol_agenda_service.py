"""Traktanden im Protokoll bearbeiten (Protokoll-Editor 1a) und Abweichungen zur Vorlage.

Im Editor lassen sich Traktanden hinzufügen, umbenennen, aus-/einblenden und umsortieren. Das
ändert nur das Protokoll, nie die Vorlage. Beim Abschliessen listet ``template_changes`` die
Abweichungen (live gegen die aktuelle Vorlage gerechnet, nur was im Protokoll geändert wurde),
``apply_template_changes`` übernimmt eine Auswahl davon in die Vorlage.

Herkunft und lokale Änderungen stehen auf dem Protokoll-Traktandum (Migration 0270): ``origin``,
``template_title_snapshot`` (Vorlagentitel, wenn umbenannt), ``visibility_customized`` und auf dem
Protokoll ``agenda_order_customized``. Der Vorlagen-Abgleich (ProtocolService.sync_with_template)
respektiert sie.

Alle Schreibwege sperren die Protokollzeile (bzw. beim Übernehmen die Vorlage) bis zum Commit,
damit gleichzeitige Änderungen nacheinander laufen. Mandanten- und Rechteprüfung machen die Routen.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.element_types import element_type_id_for_code, render_type_id
from app.documents.locking import lock_row
from app.models import (
    ElementDefinition,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolText,
    Template,
    TemplateElement,
    TemplateElementBlock,
)
from app.services.element_definition_service import ElementDefinitionService
from app.services.protocol_service import ProtocolService, resequence_protocol_elements

TITLE_MAX_LENGTH = 200
# Zwischenplatz für Vorlagen-Traktanden beim Umsortieren ((template_id, sort_index) ist eindeutig)
_TEMPLATE_PARKED_SORT_INDEX = 1_000_000
# Block-ID des Textblocks in einem übernommenen Traktandum (Blöcke leben im JSON der Definition)
_ADDED_BLOCK_SORT_INDEX = 10


class AgendaError(ValueError):
    """Erwartete, kuratierte Ablehnung (Route übersetzt den Code in 409/422)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OrderConflict(Exception):
    """Reihenfolge des Clients veraltet (409 order_conflict mit aktueller Reihenfolge)."""

    def __init__(self, current: list[uuid.UUID]) -> None:
        super().__init__("order_conflict")
        self.current = current


class ChangesOutdated(Exception):
    """Ausgewählte Abweichung existiert nicht mehr oder Vorlage inzwischen geändert (409)."""

    def __init__(self, changes: dict) -> None:
        super().__init__("changes_outdated")
        self.changes = changes


def element_title(element: ProtocolElement) -> str:
    """Titel ohne Verantwortlichen-Zusatz (der wird live angehängt)."""
    return element.element_title_snapshot or element.section_name_snapshot


def clean_title(value: str) -> str:
    title = " ".join((value or "").split())
    if not title:
        raise AgendaError("title_required", "Der Titel darf nicht leer sein")
    if len(title) > TITLE_MAX_LENGTH:
        raise AgendaError("title_too_long", f"Der Titel darf höchstens {TITLE_MAX_LENGTH} Zeichen lang sein")
    return title


def ordered_elements(db: Session, protocol_id: int) -> list[ProtocolElement]:
    return list(db.scalars(
        select(ProtocolElement)
        .where(ProtocolElement.protocol_id == protocol_id)
        .order_by(ProtocolElement.sort_index.asc(), ProtocolElement.id.asc())
    ))


class ProtocolAgendaService:
    # ── Traktanden im Protokoll ───────────────────────────────────────────────────────────────

    def add_element(self, db: Session, protocol: Protocol, *, title: str, after_element_id: int | None) -> ProtocolElement:
        """Neues Traktandum nur in diesem Protokoll, mit einem leeren Textblock. after_element_id
        (intern, bereits als Element dieses Protokolls geprüft) = Vorgänger; None = am Ende vor
        den Sitzungsnotizen."""
        title = clean_title(title)
        protocol = lock_row(db, protocol)
        elements = ordered_elements(db, protocol.id)
        text_type_id = element_type_id_for_code("text")
        if text_type_id is None:
            raise AgendaError("text_type_missing", "Textblock-Typ ist nicht konfiguriert")
        # Alle Prüfungen vor dem ersten Schreiben (die Route rollt bei AgendaError nicht zurück)
        if after_element_id is not None:
            anchor = next((entry for entry in elements if entry.id == after_element_id), None)
            if anchor is None:
                raise AgendaError("anchor_not_found", "Protocol element not found")
            position = elements.index(anchor) + 1
        else:
            # Am Ende, aber vor den Sitzungsnotizen
            position = next((index for index, entry in enumerate(elements) if entry.origin == "session"), len(elements))
        element = ProtocolElement(
            protocol_id=protocol.id,
            template_element_id=None,
            origin="protocol",
            sort_index=_TEMPLATE_PARKED_SORT_INDEX * 2,
            section_name_snapshot=title,
            element_title_snapshot=title,
            section_order_snapshot=None,
            is_required_snapshot=False,
            is_visible_snapshot=True,
            export_visible_snapshot=True,
        )
        db.add(element)
        db.flush()
        block = ProtocolElementBlock(
            protocol_element_id=element.id,
            template_element_block_id=None,
            element_definition_id=None,
            element_type_id=text_type_id,
            render_type_id=render_type_id(text_type_id),
            title_snapshot=title,
            display_title_snapshot=None,
            block_title_snapshot=None,
            is_editable_snapshot=True,
            allows_multiple_values_snapshot=False,
            sort_index=_ADDED_BLOCK_SORT_INDEX,
            render_order=_ADDED_BLOCK_SORT_INDEX,
            is_required_snapshot=False,
            is_visible_snapshot=True,
            export_visible_snapshot=True,
            configuration_snapshot_json={"agenda_custom_block": True, "title_as_subtitle": False, "default_content": ""},
        )
        db.add(block)
        db.flush()
        db.add(ProtocolText(protocol_element_block_id=block.id, content=""))

        elements.insert(position, element)
        resequence_protocol_elements(db, elements)
        return element

    def rename_element(self, element: ProtocolElement, new_title: str) -> None:
        title = clean_title(new_title)
        if element.origin == "session":
            raise AgendaError("session_element_fixed", "Die Sitzungsnotizen können nicht umbenannt werden")
        current = element_title(element)
        if element.template_element_id is not None and element.origin == "template":
            if element.template_title_snapshot is None and title != current:
                element.template_title_snapshot = current
            if title == element.template_title_snapshot:
                element.template_title_snapshot = None
        element.element_title_snapshot = title
        element.section_name_snapshot = title

    def set_visibility(self, element: ProtocolElement, visible: bool) -> None:
        if element.is_visible_snapshot != visible:
            element.visibility_customized = True
        element.is_visible_snapshot = visible

    def reorder(
        self, db: Session, protocol: Protocol, *, element_ids: list[uuid.UUID], expected_element_ids: list[uuid.UUID]
    ) -> list[ProtocolElement]:
        """Vollständige neue Reihenfolge atomar setzen. Weicht die Ausgangsreihenfolge des Clients
        oder die Menge der Traktanden vom aktuellen Stand ab: OrderConflict."""
        if len(set(element_ids)) != len(element_ids):
            raise AgendaError("duplicate_ids", "Ein Traktandum kommt mehrfach vor")
        protocol = lock_row(db, protocol)
        elements = ordered_elements(db, protocol.id)
        current = [element.public_id for element in elements]
        if list(expected_element_ids) != current or set(element_ids) != set(current):
            raise OrderConflict(current)
        by_public_id = {element.public_id: element for element in elements}
        ordered = [by_public_id[public_id] for public_id in element_ids]
        if ordered != elements:
            resequence_protocol_elements(db, ordered)
            protocol.agenda_order_customized = True
            db.add(protocol)
            db.flush()
        return ordered

    # ── Abweichungen gegenüber der Vorlage ─────────────────────────────────────────────────────

    def _template_rows(self, db: Session, template: Template) -> list[tuple[TemplateElement, ElementDefinition]]:
        return [
            (template_element, definition)
            for template_element, definition in db.execute(
                select(TemplateElement, ElementDefinition)
                .join(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
                .where(TemplateElement.template_id == template.id, ElementDefinition.tenant_id == template.tenant_id)
                .order_by(TemplateElement.sort_index.asc(), TemplateElement.id.asc())
            ).all()
        ]

    def template_changes(self, db: Session, protocol: Protocol) -> dict:
        """Abweichungen der Traktanden dieses Protokolls von seiner Vorlage (siehe Moduldoku)."""
        template = db.get(Template, protocol.template_id)
        elements = ordered_elements(db, protocol.id)
        rows = self._template_rows(db, template)
        template_rows = {template_element.id: (template_element, definition) for template_element, definition in rows}
        template_position = {template_element.id: index for index, (template_element, _definition) in enumerate(rows)}
        protocol_service = ProtocolService()
        cycle_tokens = protocol_service._sync_cycle_tokens(db, template, protocol.protocol_date)

        def template_title(definition: ElementDefinition) -> str:
            if cycle_tokens:
                return protocol_service._render_context_text(definition.title, {"tokens": cycle_tokens}) or definition.title
            return definition.title

        changes: list[dict] = []
        linked: list[ProtocolElement] = []
        seen_template_elements: set[int] = set()
        for index, element in enumerate(elements):
            if element.origin == "protocol" and element.template_element_id is None:
                anchor = next(
                    (entry for entry in reversed(elements[:index]) if entry.template_element_id in template_rows), None
                )
                anchor_template_element = template_rows[anchor.template_element_id][0] if anchor is not None else None
                changes.append({
                    "key": f"added:{element.public_id}",
                    "kind": "added",
                    "element_id": element.public_id,
                    "title": element_title(element),
                    "after_template_element_id": anchor_template_element.public_id if anchor_template_element else None,
                    "after_title": element_title(anchor) if anchor is not None else None,
                })
                continue
            row = template_rows.get(element.template_element_id) if element.template_element_id is not None else None
            if row is None:
                continue
            template_element, definition = row
            if template_element.id not in seen_template_elements:
                seen_template_elements.add(template_element.id)
                linked.append(element)
            if element.template_title_snapshot is not None:
                old_title = template_title(definition)
                new_title = element_title(element)
                if old_title != new_title:
                    changes.append({
                        "key": f"renamed:{element.public_id}",
                        "kind": "renamed",
                        "element_id": element.public_id,
                        "template_element_id": template_element.public_id,
                        "old_title": old_title,
                        "new_title": new_title,
                    })
            if element.visibility_customized and element.is_visible_snapshot != template_element.is_visible:
                changes.append({
                    "key": f"visibility:{element.public_id}",
                    "kind": "visibility",
                    "element_id": element.public_id,
                    "template_element_id": template_element.public_id,
                    "title": element_title(element),
                    "old_visible": template_element.is_visible,
                    "new_visible": element.is_visible_snapshot,
                })
        if protocol.agenda_order_customized and linked:
            in_template_order = sorted(linked, key=lambda element: template_position[element.template_element_id])
            if in_template_order != linked:
                def entry(element: ProtocolElement) -> dict:
                    return {
                        "element_id": element.public_id,
                        "template_element_id": template_rows[element.template_element_id][0].public_id,
                        "title": element_title(element),
                    }

                changes.append({
                    "key": "order",
                    "kind": "order",
                    "old_order": [entry(element) for element in in_template_order],
                    "new_order": [entry(element) for element in linked],
                })
        return {
            "template_id": template.public_id,
            "template_name": template.name,
            "template_version": template.version,
            "changes": changes,
        }

    def apply_template_changes(
        self, db: Session, protocol: Protocol, *, keys: list[str], expected_template_version: int | None
    ) -> tuple[list[str], dict]:
        """Ausgewählte Abweichungen in die Vorlage übernehmen (eine Transaktion; der Trigger aus
        0214 erhöht die Vorlagenversion einmal). Gibt (übernommene Keys, verbleibende Abweichungen)
        zurück. Der Aufrufer committet."""
        template = lock_row(db, db.get(Template, protocol.template_id))
        current = self.template_changes(db, protocol)
        if expected_template_version is not None and expected_template_version != template.version:
            raise ChangesOutdated(current)
        by_key = {change["key"]: change for change in current["changes"]}
        selected_keys = list(dict.fromkeys(keys))
        if any(key not in by_key for key in selected_keys):
            raise ChangesOutdated(current)
        selected = [by_key[key] for key in selected_keys]
        old_version = template.version

        elements = ordered_elements(db, protocol.id)
        element_by_public_id = {element.public_id: element for element in elements}
        rows = self._template_rows(db, template)
        template_element_by_public_id = {template_element.public_id: template_element for template_element, _ in rows}
        definitions = {template_element.id: definition for template_element, definition in rows}
        definition_service = ElementDefinitionService()

        for change in selected:
            if change["kind"] == "renamed":
                element = element_by_public_id[change["element_id"]]
                template_element = template_element_by_public_id[change["template_element_id"]]
                definition = definitions[template_element.id]
                usage = definition_service.usage_counts(db, [definition.id]).get(definition.id, 0)
                legacy_usage = db.scalar(
                    select(TemplateElementBlock.id).where(TemplateElementBlock.element_definition_id == definition.id).limit(1)
                )
                if definition.is_library or usage > 1 or legacy_usage is not None:
                    # Wie «nur in dieser Vorlage ändern» (detach): andere Vorlagen und die Bibliothek
                    # behalten den bisherigen Titel.
                    definition = definition_service.copy_element_definition(db, definition, is_library=False)
                    template_element.element_definition_id = definition.id
                    definitions[template_element.id] = definition
                definition.title = change["new_title"]
                definition.display_title = change["new_title"]
                template_element.section_name = change["new_title"]
                element.template_title_snapshot = None
                db.add_all([definition, template_element, element])
            elif change["kind"] == "visibility":
                element = element_by_public_id[change["element_id"]]
                template_element = template_element_by_public_id[change["template_element_id"]]
                template_element.is_visible = change["new_visible"]
                element.visibility_customized = False
                db.add_all([template_element, element])
        db.flush()

        template_order = [template_element for template_element, _ in rows]
        added = [change for change in selected if change["kind"] == "added"]
        last_inserted: dict[uuid.UUID | None, TemplateElement] = {}
        for position, change in enumerate(added):
            element = element_by_public_id[change["element_id"]]
            new_template_element = self._create_template_element(
                db, template, element, sort_index=_TEMPLATE_PARKED_SORT_INDEX * 2 + position
            )
            anchor_key = change["after_template_element_id"]
            anchor = last_inserted.get(anchor_key) or (template_element_by_public_id.get(anchor_key) if anchor_key else None)
            index = template_order.index(anchor) + 1 if anchor is not None else 0
            template_order.insert(index, new_template_element)
            last_inserted[anchor_key] = new_template_element

        reorder = any(change["kind"] == "order" for change in selected)
        if reorder:
            # Vorlagen-Traktanden, die im Protokoll vorkommen, in Protokoll-Reihenfolge; die
            # übrigen behalten ihren Platz.
            position_of = {template_element.id: index for index, template_element in enumerate(template_order)}
            protocol_sequence: list[int] = []
            for element in elements:
                if element.template_element_id in position_of and element.template_element_id not in protocol_sequence:
                    protocol_sequence.append(element.template_element_id)
            slots = sorted(position_of[template_element_id] for template_element_id in protocol_sequence)
            by_id = {template_element.id: template_element for template_element in template_order}
            for slot, template_element_id in zip(slots, protocol_sequence):
                template_order[slot] = by_id[template_element_id]
        if added or reorder:
            for position, template_element in enumerate(template_order):
                template_element.sort_index = _TEMPLATE_PARKED_SORT_INDEX + position
            db.flush()
            for position, template_element in enumerate(template_order):
                template_element.sort_index = (position + 1) * 10
                template_element.section_order = template_element.sort_index
            db.flush()

        db.refresh(template)
        if protocol.template_version == old_version and template.version != old_version:
            # Das Protokoll war auf dem Stand der Vorlage und hat nur seine eigenen Änderungen
            # hineingegeben: kein Hinweis «Vorlage wurde geändert».
            protocol.template_version = template.version
            db.add(protocol)
            db.flush()
        return selected_keys, self.template_changes(db, protocol)

    def _create_template_element(
        self, db: Session, template: Template, element: ProtocolElement, *, sort_index: int
    ) -> TemplateElement:
        """Vorlagen-Traktandum aus einem im Protokoll hinzugefügten Traktandum: eigener Baustein
        (nicht Bibliothek) mit einem leeren Textblock. Das Protokoll-Traktandum wird verknüpft,
        sein Text bleibt im Protokoll; Folgeprotokolle und der Abgleich kennen es danach."""
        title = element_title(element)
        text_type_id = element_type_id_for_code("text")
        definition_service = ElementDefinitionService()
        blocks = definition_service._normalize_blocks(db, [{
            "id": _ADDED_BLOCK_SORT_INDEX,
            "title": title,
            "description": None,
            "block_title": None,
            "default_content": "",
            "copy_from_last_protocol": False,
            "title_as_subtitle": False,
            "element_type_id": text_type_id,
            "render_type_id": render_type_id(text_type_id),
            "is_editable": True,
            "allows_multiple_values": False,
            "export_visible": True,
            "is_visible": True,
            "sort_index": _ADDED_BLOCK_SORT_INDEX,
            "render_order": _ADDED_BLOCK_SORT_INDEX,
            "configuration_json": {},
        }], tenant_id=template.tenant_id)
        definition = ElementDefinition(
            tenant_id=template.tenant_id,
            element_type_id=1,
            render_type_id=2,
            title=title,
            display_title=title,
            description=None,
            is_editable=False,
            allows_multiple_values=False,
            export_visible=True,
            configuration_json={"blocks": blocks},
            is_active=True,
            is_library=False,
        )
        db.add(definition)
        db.flush()
        template_element = TemplateElement(
            template_id=template.id,
            element_definition_id=definition.id,
            sort_index=sort_index,
            section_name=title,
            section_order=sort_index,
            is_required=False,
            is_visible=element.is_visible_snapshot,
            export_visible=True,
            configuration_json={},
        )
        db.add(template_element)
        db.flush()
        element.template_element_id = template_element.id
        element.template_title_snapshot = None
        element.visibility_customized = False
        db.add(element)
        custom_block = db.scalar(
            select(ProtocolElementBlock)
            .where(
                ProtocolElementBlock.protocol_element_id == element.id,
                ProtocolElementBlock.configuration_snapshot_json["agenda_custom_block"].as_boolean().is_(True),
            )
            .order_by(ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
            .limit(1)
        )
        if custom_block is not None:
            # Gleicher Abgleich-Schlüssel wie materialisierte Blöcke (source_sort_index)
            config = dict(custom_block.configuration_snapshot_json or {})
            config["source_sort_index"] = _ADDED_BLOCK_SORT_INDEX
            custom_block.configuration_snapshot_json = config
            custom_block.element_definition_id = definition.id
            db.add(custom_block)
        db.flush()
        return template_element
