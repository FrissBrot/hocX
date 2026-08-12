from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import ListDefinition, ListEntry

_COLUMN_STRUCTURE_FIELDS = {
    "column_one_title", "column_one_value_type", "column_two_title", "column_two_value_type",
}


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

    def create_definition(self, db: Session, definition: ListDefinition) -> ListDefinition:
        db.add(definition)
        db.commit()
        db.refresh(definition)
        return definition

    def update_definition(self, db: Session, definition: ListDefinition, values: dict) -> ListDefinition:
        # A column's value_type change (e.g. "text" -> "participant") invalidates the shape
        # of every existing entry's value for that column (list_service._normalize_value
        # produces "text_value"/"participant_id"/"participant_ids"/"event_id" keys depending
        # on value_type - there's no generic semantic conversion between them). Rather than
        # leaving entries in the old, now-invalid shape, clear them to {} - a valid "empty"
        # value for every value_type - before applying the type change.
        value_columns_to_clear = []
        if "column_one_value_type" in values and values["column_one_value_type"] != definition.column_one_value_type:
            value_columns_to_clear.append(ListEntry.column_one_value_json)
        if "column_two_value_type" in values and values["column_two_value_type"] != definition.column_two_value_type:
            value_columns_to_clear.append(ListEntry.column_two_value_json)

        for key, value in values.items():
            setattr(definition, key, value)
        db.add(definition)

        if value_columns_to_clear:
            db.execute(
                update(ListEntry)
                .where(ListEntry.list_definition_id == definition.id)
                .values(**{column.key: {} for column in value_columns_to_clear})
            )
            db.flush()

        if _COLUMN_STRUCTURE_FIELDS & values.keys():
            db.flush()
            self._bump_content_version(db, definition.id)
        db.commit()
        db.refresh(definition)
        return definition

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

    def create_entry(self, db: Session, entry: ListEntry) -> ListEntry:
        db.add(entry)
        db.flush()
        self._bump_content_version(db, entry.list_definition_id)
        db.commit()
        db.refresh(entry)
        return entry

    def update_entry(self, db: Session, entry: ListEntry, values: dict) -> ListEntry:
        for key, value in values.items():
            setattr(entry, key, value)
        db.add(entry)
        db.flush()
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
