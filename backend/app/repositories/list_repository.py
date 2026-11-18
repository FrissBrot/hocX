from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Event, ListColumn, ListDefinition, ListEntry, Participant
from app.services import public_id_service

# Rollenwechsel ändern, wie Blöcke einen Eintrag benennen - verlinkte Snapshots neu bewerten
_STRUCTURE_FIELDS = {"label_column_id", "responsible_column_id"}


class ListRepository:
    def _bump_content_version(self, db: Session, list_definition_id: int) -> int:
        """Atomic increment (no read-modify-write race) - the single signal protocol
        blocks compare their snapshot's synced_version against to detect staleness."""
        stmt = (
            update(ListDefinition)
            .where(ListDefinition.id == list_definition_id)
            .values(content_version=ListDefinition.content_version + 1)
            .returning(ListDefinition.content_version)
        )
        return db.execute(stmt).scalar_one()

    def list_definitions(self, db: Session, *, tenant_id: int) -> list[ListDefinition]:
        statement = (
            select(ListDefinition)
            .where(ListDefinition.tenant_id == tenant_id)
            .order_by(ListDefinition.name.asc(), ListDefinition.id.asc())
        )
        return list(db.scalars(statement))

    def get_definition(self, db: Session, list_definition_id: int) -> ListDefinition | None:
        return db.get(ListDefinition, list_definition_id)

    def get_definition_by_public_id(self, db: Session, public_id: uuid.UUID, *, tenant_id: int) -> ListDefinition | None:
        return public_id_service.get_by_public_id(db, ListDefinition, public_id, tenant_id=tenant_id)

    def participant_belongs_to_tenant(self, db: Session, tenant_id: int, participant_id: int) -> bool:
        participant = db.get(Participant, participant_id)
        return participant is not None and participant.tenant_id == tenant_id

    def event_belongs_to_tenant(self, db: Session, tenant_id: int, event_id: int) -> bool:
        event = db.get(Event, event_id)
        return event is not None and event.tenant_id == tenant_id

    def create_definition(self, db: Session, definition: ListDefinition) -> ListDefinition:
        db.add(definition)
        db.commit()
        db.refresh(definition)
        return definition

    def update_definition(self, db: Session, definition: ListDefinition, values: dict) -> ListDefinition:
        for key, value in values.items():
            setattr(definition, key, value)
        db.add(definition)
        if _STRUCTURE_FIELDS & values.keys():
            db.flush()
            self._bump_content_version(db, definition.id)
        db.commit()
        db.refresh(definition)
        return definition

    # ── Spalten (jede Änderung erhöht content_version: verlinkte Blöcke sehen sie) ──────────

    def _finish_column_change(self, db: Session, definition: ListDefinition) -> None:
        db.flush()
        self._bump_content_version(db, definition.id)
        db.commit()
        db.refresh(definition)

    def add_column(self, db: Session, definition: ListDefinition, column: ListColumn) -> ListColumn:
        definition.columns.append(column)
        db.add(definition)
        self._finish_column_change(db, definition)
        return column

    def _clear_column_values(self, db: Session, definition: ListDefinition, column: ListColumn) -> None:
        # Ein Typwechsel macht die gespeicherte Wertform ungültig (text_value vs. participant_id
        # ...), es gibt keine sinnvolle Umwandlung: Werte der Spalte in allen Einträgen leeren.
        db.execute(
            update(ListEntry)
            .where(ListEntry.list_definition_id == definition.id, ListEntry.values_json.has_key(column.key))
            .values(values_json=ListEntry.values_json - column.key)
        )

    def update_column(self, db: Session, definition: ListDefinition, column: ListColumn, values: dict, *, clear_values: bool) -> ListColumn:
        changed = any(getattr(column, key) != value for key, value in values.items())
        for key, value in values.items():
            setattr(column, key, value)
        if clear_values:
            self._clear_column_values(db, definition, column)
        if changed or clear_values:
            self._finish_column_change(db, definition)
        return column

    def delete_column(self, db: Session, definition: ListDefinition, column: ListColumn) -> None:
        self._clear_column_values(db, definition, column)
        definition.columns.remove(column)
        db.delete(column)
        self._finish_column_change(db, definition)

    def reorder_columns(self, db: Session, definition: ListDefinition, ordered: list[ListColumn]) -> None:
        for index, column in enumerate(ordered):
            column.sort_index = (index + 1) * 10
        self._finish_column_change(db, definition)

    def get_column(self, definition: ListDefinition, key: str) -> ListColumn | None:
        """Spalte über ihren Key - immer innerhalb einer bereits mandantengebunden geladenen Liste."""
        return next((column for column in definition.columns if column.key == key), None)

    def delete_definition(self, db: Session, definition: ListDefinition) -> None:
        db.delete(definition)
        db.commit()

    def list_entries(self, db: Session, *, list_definition_id: int) -> list[ListEntry]:
        statement = (
            select(ListEntry)
            .where(ListEntry.list_definition_id == list_definition_id)
            .order_by(ListEntry.sort_index.asc(), ListEntry.id.asc())
        )
        return list(db.scalars(statement))

    def get_entry(self, db: Session, list_entry_id: int) -> ListEntry | None:
        return db.get(ListEntry, list_entry_id)

    def get_entry_by_public_id(self, db: Session, public_id: uuid.UUID) -> ListEntry | None:
        # No tenant_id column of its own (scoped via list_definition_id) - callers must
        # verify tenant/access on the resolved row's list definition.
        return public_id_service.get_by_public_id(db, ListEntry, public_id)

    def create_entry(self, db: Session, entry: ListEntry) -> ListEntry:
        db.add(entry)
        db.flush()
        self._bump_content_version(db, entry.list_definition_id)
        db.commit()
        db.refresh(entry)
        return entry

    def update_entry(self, db: Session, entry: ListEntry, values: dict) -> ListEntry:
        # Only bump content_version if something actually changed - an update with identical
        # values (e.g. a no-op re-save) used to bump it unconditionally, creating unnecessary
        # stale-snapshot markers and WS notifications for blocks that link this list.
        changed = any(getattr(entry, key) != value for key, value in values.items())
        for key, value in values.items():
            setattr(entry, key, value)
        db.add(entry)
        db.flush()
        if changed:
            self._bump_content_version(db, entry.list_definition_id)
        db.commit()
        db.refresh(entry)
        return entry

    def delete_entry(self, db: Session, entry: ListEntry) -> None:
        list_definition_id = entry.list_definition_id
        db.delete(entry)
        db.flush()
        self._bump_content_version(db, list_definition_id)
        db.commit()
