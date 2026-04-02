from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ListDefinition, ListEntry


class ListRepository:
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
        for key, value in values.items():
            setattr(definition, key, value)
        db.add(definition)
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
        db.commit()
        db.refresh(entry)
        return entry

    def update_entry(self, db: Session, entry: ListEntry, values: dict) -> ListEntry:
        for key, value in values.items():
            setattr(entry, key, value)
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    def delete_entry(self, db: Session, entry: ListEntry) -> None:
        db.delete(entry)
        db.commit()
