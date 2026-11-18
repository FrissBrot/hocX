from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, ListColumn, ListDefinition, ListEntry, Participant
from app.repositories.list_repository import ListRepository
from app.schemas.list_definition import (
    ListColumnCreate,
    ListColumnRead,
    ListColumnUpdate,
    ListDefinitionCreate,
    ListDefinitionRead,
    ListDefinitionUpdate,
    ListEntryCreate,
    ListEntryRead,
    ListEntryUpdate,
)
from app.services import list_columns, public_id_service


def lock_linked_list_definitions(db: Session, list_ids, *, tenant_id: int | None) -> set[int]:
    """Sperrt die Listen, die ein Baustein gerade verknüpft, bis zum Commit (Audit 07, C10).

    Gegenstück zur Zeilensperre in DELETE /lists/{id}: läuft das Löschen zuerst, wartet das
    Verknüpfen und findet die Liste danach nicht mehr (-> «Linked list not found»); verknüpft
    der Baustein zuerst, sieht das Löschen nach dem Warten die Verknüpfung und antwortet 409.
    FOR SHARE statt FOR UPDATE: blockiert nur das Löschen/Ändern der Liste, nicht gleichzeitige
    Verknüpfungen oder neue Einträge. Feste Reihenfolge gegen Deadlocks.
    Liefert die gefundenen IDs (nur Listen des Mandanten)."""
    ids = sorted({int(list_id) for list_id in list_ids if list_id})
    if not ids or tenant_id is None:
        return set()
    return set(
        db.scalars(
            select(ListDefinition.id)
            .where(ListDefinition.id.in_(ids), ListDefinition.tenant_id == tenant_id)
            .order_by(ListDefinition.id)
            .with_for_update(read=True)
        )
    )


class ListService:
    def __init__(self, repository: ListRepository | None = None) -> None:
        self.repository = repository or ListRepository()

    def _normalize_value(self, db: Session, tenant_id: int, value_type: str, raw_value: dict[str, Any] | None) -> dict[str, Any]:
        # participant_id(s)/event_id arrive as public UUIDs from the API - resolve to
        # internal ids scoped to tenant_id here, which also serves as their ownership
        # validation (an id from another tenant simply fails to resolve): before the
        # underlying tenant check existed at all, responsible_label_service resolved these
        # ids to a real Participant without a tenant filter of its own, so a writer could
        # store another tenant's participant_id here and have their name/label displayed -
        # a cross-tenant PII leak (audit finding H1, 2026-08-25).
        value = raw_value or {}
        if value_type == "participant":
            participant_id = value.get("participant_id")
            if not participant_id:
                return {}
            internal_id = public_id_service.resolve_internal_id(db, Participant, uuid.UUID(str(participant_id)), tenant_id=tenant_id)
            if internal_id is None:
                raise ValueError("Participant not found")
            return {"participant_id": internal_id}
        if value_type == "participants":
            participant_ids = value.get("participant_ids")
            if not isinstance(participant_ids, list):
                return {}
            public_ids = [uuid.UUID(str(pid)) for pid in participant_ids if str(pid or "").strip()]
            id_map = public_id_service.resolve_internal_ids(db, Participant, public_ids, tenant_id=tenant_id)
            if len(id_map) != len(set(public_ids)):
                raise ValueError("Participant not found")
            return {"participant_ids": [id_map[pid] for pid in public_ids]}
        if value_type == "event":
            event_id = value.get("event_id")
            if not event_id:
                return {}
            internal_id = public_id_service.resolve_internal_id(db, Event, uuid.UUID(str(event_id)), tenant_id=tenant_id)
            if internal_id is None:
                raise ValueError("Event not found")
            return {"event_id": internal_id}
        text_value = str(value.get("text_value") or "").strip()
        return {"text_value": text_value} if text_value else {}

    def _denormalize_value(self, db: Session, value_type: str, stored_value: dict[str, Any] | None) -> dict[str, Any]:
        """Inverse of _normalize_value - translates the internal ids stored in
        list_entry.values_json back to public UUIDs before a value crosses the API."""
        value = stored_value or {}
        if value_type == "participant" and value.get("participant_id") is not None:
            public_id = public_id_service.resolve_public_id(db, Participant, value["participant_id"])
            return {"participant_id": public_id} if public_id else {}
        if value_type == "participants" and isinstance(value.get("participant_ids"), list):
            mapping = public_id_service.resolve_public_ids(db, Participant, value["participant_ids"])
            return {"participant_ids": [mapping[i] for i in value["participant_ids"] if i in mapping]}
        if value_type == "event" and value.get("event_id") is not None:
            public_id = public_id_service.resolve_public_id(db, Event, value["event_id"])
            return {"event_id": public_id} if public_id else {}
        return dict(value)

    def _definition_read(self, definition: ListDefinition) -> ListDefinitionRead:
        columns = list_columns.columns_of(definition)
        by_id = {column.id: column for column in columns}
        role = lambda column_id: by_id[column_id].key if column_id in by_id else None  # noqa: E731
        return ListDefinitionRead.model_validate(definition).model_copy(
            update={
                "columns": [
                    ListColumnRead(id=column.key, title=column.title, value_type=column.value_type, sort_index=column.sort_index)
                    for column in columns
                ],
                "label_column_id": role(definition.label_column_id),
                "responsible_column_id": role(definition.responsible_column_id),
            }
        )

    def _entry_read(self, db: Session, entry: ListEntry, *, definition: ListDefinition | None = None) -> ListEntryRead:
        definition = definition or self.repository.get_definition(db, entry.list_definition_id)
        values = {}
        for column in list_columns.columns_of(definition):
            value = self._denormalize_value(db, column.value_type, list_columns.get_value(entry, column))
            if value:
                values[column.key] = value
        return ListEntryRead(
            id=entry.public_id,
            list_definition_id=public_id_service.resolve_public_id(db, ListDefinition, entry.list_definition_id),
            sort_index=entry.sort_index,
            values=values,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    def _normalize_values(
        self, db: Session, definition: ListDefinition, raw: dict[str, Any] | None, *, current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Werte aus der API (öffentliche IDs) je Spalte prüfen und intern speichern. Unbekannte
        Spalten-Keys sind ein Fehler; ``current`` wird mit den genannten Spalten überschrieben."""
        by_key = {column.key: column for column in definition.columns}
        result = dict(current or {})
        for key, value in (raw or {}).items():
            column = by_key.get(str(key))
            if column is None:
                raise ValueError("Unknown list column")
            normalized = self._normalize_value(db, definition.tenant_id, column.value_type, value)
            if normalized:
                result[column.key] = normalized
            else:
                result.pop(column.key, None)
        return result

    def list_definitions(self, db: Session, *, tenant_id: int) -> list[ListDefinitionRead]:
        return [self._definition_read(item) for item in self.repository.list_definitions(db, tenant_id=tenant_id)]

    def get_definition(self, db: Session, list_definition_id: int) -> ListDefinition | None:
        return self.repository.get_definition(db, list_definition_id)

    def create_definition(self, db: Session, payload: ListDefinitionCreate, *, tenant_id: int) -> ListDefinitionRead:
        entity = ListDefinition(
            tenant_id=tenant_id,
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
            is_group_source=payload.is_group_source,
        )
        # Mindestens eine Spalte; Rollen wie bei der Migration: erste Text-/Personen-Spalte
        starts = payload.columns or [ListColumnCreate(title="Name", value_type="text")]
        entity.columns = [
            ListColumn(title=column.title.strip(), value_type=column.value_type, sort_index=(index + 1) * 10)
            for index, column in enumerate(starts[: list_columns.MAX_COLUMNS])
        ]
        created = self.repository.create_definition(db, entity)
        label = next((c for c in created.columns if c.value_type in list_columns.LABEL_TYPES), None)
        responsible = next((c for c in created.columns if c.value_type in list_columns.PARTICIPANT_TYPES), None)
        if label is not None or responsible is not None:
            created = self.repository.update_definition(
                db, created, {"label_column_id": label.id if label else None, "responsible_column_id": responsible.id if responsible else None}
            )
        return self._definition_read(created)

    def update_definition(
        self, db: Session, list_definition_id: int, payload: ListDefinitionUpdate
    ) -> ListDefinitionRead | None:
        definition = self.repository.get_definition(db, list_definition_id)
        if definition is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        by_key = {column.key: column for column in definition.columns}
        for role, allowed in (("label_column_id", list_columns.LABEL_TYPES), ("responsible_column_id", list_columns.PARTICIPANT_TYPES)):
            if role not in values:
                continue
            if values[role] is None:
                continue
            column = by_key.get(str(values[role]))
            if column is None:
                raise ValueError("Unknown list column")
            if column.value_type not in allowed:
                raise ValueError("List column type does not fit the role")
            values[role] = column.id
        if not values:
            return self._definition_read(definition)
        updated = self.repository.update_definition(db, definition, values)
        return self._definition_read(updated)

    # ── Spalten ────────────────────────────────────────────────────────────────────────────

    def add_column(self, db: Session, definition: ListDefinition, payload: ListColumnCreate) -> ListDefinitionRead:
        # Liste sperren, damit gleichzeitige Anfragen die Grenze nicht gemeinsam überschreiten
        db.execute(select(ListDefinition.id).where(ListDefinition.id == definition.id).with_for_update())
        db.refresh(definition, attribute_names=["columns"])
        if len(definition.columns) >= list_columns.MAX_COLUMNS:
            raise ValueError("Too many list columns")
        last = max((column.sort_index for column in definition.columns), default=0)
        column = ListColumn(title=payload.title.strip(), value_type=payload.value_type, sort_index=last + 10)
        self.repository.add_column(db, definition, column)
        return self._definition_read(definition)

    def update_column(self, db: Session, definition: ListDefinition, column: ListColumn, payload: ListColumnUpdate) -> ListDefinitionRead:
        values = payload.model_dump(exclude_unset=True, exclude_none=True)
        if "title" in values:
            values["title"] = values["title"].strip()
        type_changed = "value_type" in values and values["value_type"] != column.value_type
        if type_changed:
            # Rollen, deren Typ nicht mehr passt, entfallen
            if definition.label_column_id == column.id and values["value_type"] not in list_columns.LABEL_TYPES:
                definition.label_column_id = None
            if definition.responsible_column_id == column.id and values["value_type"] not in list_columns.PARTICIPANT_TYPES:
                definition.responsible_column_id = None
        self.repository.update_column(db, definition, column, values, clear_values=type_changed)
        return self._definition_read(definition)

    def delete_column(self, db: Session, definition: ListDefinition, column: ListColumn) -> ListDefinitionRead:
        if len(definition.columns) <= 1:
            raise ValueError("A list needs at least one column")
        self.repository.delete_column(db, definition, column)
        return self._definition_read(definition)

    def reorder_columns(self, db: Session, definition: ListDefinition, column_ids: list[str]) -> ListDefinitionRead:
        by_key = {column.key: column for column in definition.columns}
        if set(column_ids) != set(by_key) or len(column_ids) != len(by_key):
            raise ValueError("Column order must name every column once")
        self.repository.reorder_columns(db, definition, [by_key[column_id] for column_id in column_ids])
        return self._definition_read(definition)

    def delete_definition(self, db: Session, list_definition_id: int) -> bool:
        definition = self.repository.get_definition(db, list_definition_id)
        if definition is None:
            return False
        self.repository.delete_definition(db, definition)
        return True

    def list_entries(self, db: Session, *, list_definition_id: int) -> list[ListEntryRead]:
        definition = self.repository.get_definition(db, list_definition_id)
        entries = self.repository.list_entries(db, list_definition_id=list_definition_id)
        self._prime_entry_references(db, definition, entries)
        return [self._entry_read(db, item, definition=definition) for item in entries]

    def entries_by_list(self, db: Session, *, tenant_id: int) -> dict[str, list[ListEntryRead]]:
        """Einträge aller Listen des Mandanten, nach öffentlicher Listen-ID: zwei Abfragen plus
        eine Sammelauflösung je Personen-/Termin-Typ und Liste (statt eines HTTP-Aufrufs je Liste)."""
        definitions = self.repository.list_definitions(db, tenant_id=tenant_id)
        if not definitions:
            return {}
        by_id = {definition.id: definition for definition in definitions}
        entries = list(
            db.scalars(
                select(ListEntry)
                .where(ListEntry.list_definition_id.in_(by_id))
                .order_by(ListEntry.list_definition_id, ListEntry.sort_index.asc(), ListEntry.id.asc())
            )
        )
        grouped: dict[int, list[ListEntry]] = {definition_id: [] for definition_id in by_id}
        for entry in entries:
            grouped[entry.list_definition_id].append(entry)
        result: dict[str, list[ListEntryRead]] = {}
        for definition_id, items in grouped.items():
            definition = by_id[definition_id]
            self._prime_entry_references(db, definition, items)
            result[str(definition.public_id)] = [self._entry_read(db, item, definition=definition) for item in items]
        return result

    @staticmethod
    def _prime_entry_references(db: Session, definition: ListDefinition | None, entries: list[ListEntry]) -> None:
        """Eine Sammelabfrage je Modell (Liste, Personen, Termine) für alle Einträge, statt dass
        _denormalize_value jede Person/jeden Termin einzeln auflöst (16-20 Abfragen je Liste)."""
        if not entries:
            return
        public_id_service.prime_public_ids(db, ListDefinition, {entry.list_definition_id for entry in entries})
        wanted: dict[type, set[int]] = {Participant: set(), Event: set()}

        def add(model: type, value: Any) -> None:
            # Nur echte interne ids; alles andere löst _denormalize_value wie bisher selbst auf
            if isinstance(value, int) and not isinstance(value, bool):
                wanted[model].add(value)

        columns = list_columns.columns_of(definition)
        for entry in entries:
            for column in columns:
                value_type = column.value_type
                value = list_columns.get_value(entry, column)
                if value_type == "participant":
                    add(Participant, value.get("participant_id"))
                elif value_type == "participants" and isinstance(value.get("participant_ids"), list):
                    for item in value["participant_ids"]:
                        add(Participant, item)
                elif value_type == "event":
                    add(Event, value.get("event_id"))
        for model, ids in wanted.items():
            if ids:
                public_id_service.prime_public_ids(db, model, ids)

    def get_entry(self, db: Session, list_entry_id: int) -> ListEntry | None:
        return self.repository.get_entry(db, list_entry_id)

    def create_entry(self, db: Session, list_definition_id: int, payload: ListEntryCreate) -> ListEntryRead:
        definition = self.repository.get_definition(db, list_definition_id)
        if definition is None:
            raise ValueError("Liste nicht gefunden")
        entity = ListEntry(
            list_definition_id=list_definition_id,
            sort_index=payload.sort_index,
            values_json=self._normalize_values(db, definition, payload.values),
        )
        created = self.repository.create_entry(db, entity)
        return self._entry_read(db, created, definition=definition)

    def update_entry(self, db: Session, list_entry_id: int, payload: ListEntryUpdate) -> ListEntryRead | None:
        entry = self.repository.get_entry(db, list_entry_id)
        if entry is None:
            return None
        definition = self.repository.get_definition(db, entry.list_definition_id)
        if definition is None:
            raise ValueError("Liste nicht gefunden")
        values = payload.model_dump(exclude_unset=True)
        if "values" in values:
            raw = values.pop("values")
            if raw is not None:
                values["values_json"] = self._normalize_values(db, definition, raw, current=entry.values_json)
        if not values:
            return self._entry_read(db, entry, definition=definition)
        updated = self.repository.update_entry(db, entry, values)
        return self._entry_read(db, updated, definition=definition)

    def delete_entry(self, db: Session, list_entry_id: int) -> bool:
        from app.services import deletion_service

        entry = self.repository.get_entry(db, list_entry_id)
        if entry is None:
            return False
        # Einreichungen zu diesem Eintrag samt Dateien löschen (sonst verwaist, PRIV-003).
        if deletion_service.erase_uploads_of(db, list_entry_id=list_entry_id):
            entry = self.repository.get_entry(db, list_entry_id)
        self.repository.delete_entry(db, entry)
        return True
