from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import ListDefinition, ListEntry
from app.repositories.list_repository import ListRepository
from app.schemas.list_definition import (
    ListDefinitionCreate,
    ListDefinitionRead,
    ListDefinitionUpdate,
    ListEntryCreate,
    ListEntryRead,
    ListEntryUpdate,
)


class ListService:
    def __init__(self, repository: ListRepository | None = None) -> None:
        self.repository = repository or ListRepository()

    def _normalize_value(self, value_type: str, raw_value: dict[str, Any] | None) -> dict[str, Any]:
        value = raw_value or {}
        if value_type == "participant":
            participant_id = value.get("participant_id")
            return {"participant_id": int(participant_id)} if participant_id else {}
        if value_type == "participants":
            participant_ids = value.get("participant_ids")
            if not isinstance(participant_ids, list):
                return {}
            return {
                "participant_ids": [
                    int(participant_id)
                    for participant_id in participant_ids
                    if str(participant_id or "").strip()
                ]
            }
        if value_type == "event":
            event_id = value.get("event_id")
            return {"event_id": int(event_id)} if event_id else {}
        text_value = str(value.get("text_value") or "").strip()
        return {"text_value": text_value} if text_value else {}

    def _definition_read(self, definition: ListDefinition) -> ListDefinitionRead:
        return ListDefinitionRead.model_validate(definition)

    def _entry_read(self, entry: ListEntry) -> ListEntryRead:
        return ListEntryRead(
            id=entry.id,
            list_definition_id=entry.list_definition_id,
            sort_index=entry.sort_index,
            column_one_value=dict(entry.column_one_value_json or {}),
            column_two_value=dict(entry.column_two_value_json or {}),
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    def list_definitions(self, db: Session, *, tenant_id: int) -> list[ListDefinitionRead]:
        return [self._definition_read(item) for item in self.repository.list_definitions(db, tenant_id=tenant_id)]

    def get_definition(self, db: Session, list_definition_id: int) -> ListDefinition | None:
        return self.repository.get_definition(db, list_definition_id)

    def create_definition(self, db: Session, payload: ListDefinitionCreate, *, tenant_id: int) -> ListDefinitionRead:
        entity = ListDefinition(
            tenant_id=tenant_id,
            name=payload.name,
            description=payload.description,
            column_one_title=payload.column_one_title,
            column_one_value_type=payload.column_one_value_type,
            column_two_title=payload.column_two_title,
            column_two_value_type=payload.column_two_value_type,
            is_active=payload.is_active,
        )
        created = self.repository.create_definition(db, entity)
        return self._definition_read(created)

    def update_definition(
        self, db: Session, list_definition_id: int, payload: ListDefinitionUpdate
    ) -> ListDefinitionRead | None:
        definition = self.repository.get_definition(db, list_definition_id)
        if definition is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return self._definition_read(definition)
        updated = self.repository.update_definition(db, definition, values)
        return self._definition_read(updated)

    def delete_definition(self, db: Session, list_definition_id: int) -> bool:
        definition = self.repository.get_definition(db, list_definition_id)
        if definition is None:
            return False
        self.repository.delete_definition(db, definition)
        return True

    def list_entries(self, db: Session, *, list_definition_id: int) -> list[ListEntryRead]:
        return [self._entry_read(item) for item in self.repository.list_entries(db, list_definition_id=list_definition_id)]

    def get_entry(self, db: Session, list_entry_id: int) -> ListEntry | None:
        return self.repository.get_entry(db, list_entry_id)

    def create_entry(self, db: Session, list_definition_id: int, payload: ListEntryCreate) -> ListEntryRead:
        definition = self.repository.get_definition(db, list_definition_id)
        if definition is None:
            raise ValueError("Liste nicht gefunden")
        entity = ListEntry(
            list_definition_id=list_definition_id,
            sort_index=payload.sort_index,
            column_one_value_json=self._normalize_value(definition.column_one_value_type, payload.column_one_value),
            column_two_value_json=self._normalize_value(definition.column_two_value_type, payload.column_two_value),
        )
        created = self.repository.create_entry(db, entity)
        return self._entry_read(created)

    def update_entry(self, db: Session, list_entry_id: int, payload: ListEntryUpdate) -> ListEntryRead | None:
        entry = self.repository.get_entry(db, list_entry_id)
        if entry is None:
            return None
        definition = self.repository.get_definition(db, entry.list_definition_id)
        if definition is None:
            raise ValueError("Liste nicht gefunden")
        values = payload.model_dump(exclude_unset=True)
        if "column_one_value" in values:
            values["column_one_value_json"] = self._normalize_value(
                definition.column_one_value_type, values.pop("column_one_value")
            )
        if "column_two_value" in values:
            values["column_two_value_json"] = self._normalize_value(
                definition.column_two_value_type, values.pop("column_two_value")
            )
        if not values:
            return self._entry_read(entry)
        updated = self.repository.update_entry(db, entry, values)
        return self._entry_read(updated)

    def delete_entry(self, db: Session, list_entry_id: int) -> bool:
        entry = self.repository.get_entry(db, list_entry_id)
        if entry is None:
            return False
        self.repository.delete_entry(db, entry)
        return True
