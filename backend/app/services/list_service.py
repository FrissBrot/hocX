from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import Event, ListDefinition, ListEntry, Participant
from app.repositories.list_repository import ListRepository
from app.schemas.list_definition import (
    ListDefinitionCreate,
    ListDefinitionRead,
    ListDefinitionUpdate,
    ListEntryCreate,
    ListEntryRead,
    ListEntryUpdate,
)
from app.services import public_id_service


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
        column_one/two_value_json back to public UUIDs before a value crosses the API."""
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
        return ListDefinitionRead.model_validate(definition)

    def _entry_read(self, db: Session, entry: ListEntry, *, definition: ListDefinition | None = None) -> ListEntryRead:
        definition = definition or self.repository.get_definition(db, entry.list_definition_id)
        column_one_type = definition.column_one_value_type if definition else "text"
        column_two_type = definition.column_two_value_type if definition else "text"
        return ListEntryRead(
            id=entry.public_id,
            list_definition_id=public_id_service.resolve_public_id(db, ListDefinition, entry.list_definition_id),
            sort_index=entry.sort_index,
            column_one_value=self._denormalize_value(db, column_one_type, entry.column_one_value_json),
            column_two_value=self._denormalize_value(db, column_two_type, entry.column_two_value_json),
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
        definition = self.repository.get_definition(db, list_definition_id)
        return [
            self._entry_read(db, item, definition=definition)
            for item in self.repository.list_entries(db, list_definition_id=list_definition_id)
        ]

    def get_entry(self, db: Session, list_entry_id: int) -> ListEntry | None:
        return self.repository.get_entry(db, list_entry_id)

    def create_entry(self, db: Session, list_definition_id: int, payload: ListEntryCreate) -> ListEntryRead:
        definition = self.repository.get_definition(db, list_definition_id)
        if definition is None:
            raise ValueError("Liste nicht gefunden")
        entity = ListEntry(
            list_definition_id=list_definition_id,
            sort_index=payload.sort_index,
            column_one_value_json=self._normalize_value(db, definition.tenant_id, definition.column_one_value_type, payload.column_one_value),
            column_two_value_json=self._normalize_value(db, definition.tenant_id, definition.column_two_value_type, payload.column_two_value),
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
        if "column_one_value" in values:
            values["column_one_value_json"] = self._normalize_value(
                db, definition.tenant_id, definition.column_one_value_type, values.pop("column_one_value")
            )
        if "column_two_value" in values:
            values["column_two_value_json"] = self._normalize_value(
                db, definition.tenant_id, definition.column_two_value_type, values.pop("column_two_value")
            )
        if not values:
            return self._entry_read(db, entry, definition=definition)
        updated = self.repository.update_entry(db, entry, values)
        return self._entry_read(db, updated, definition=definition)

    def delete_entry(self, db: Session, list_entry_id: int) -> bool:
        entry = self.repository.get_entry(db, list_entry_id)
        if entry is None:
            return False
        self.repository.delete_entry(db, entry)
        return True
