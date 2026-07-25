"""Shared helpers for TenantCloneService/TenantExportService/TenantImportService.

Export walks the DB with plain SELECTs and serializes every column generically (no
FK-remapping needed - a JSON file has no foreign key constraints). Import is the
mirror image: it re-creates fresh ORM rows from the JSON dicts and has to remap every
foreign key from the old (source-tenant) id space into a newly assigned id space,
exactly like TenantCloneService does when copying within the same DB - the difference
here is that the "source" is JSON data read back from a zip, potentially on a
completely different hocX installation, instead of a live ORM query.

Two kinds of references can't just be remapped through an in-memory id_map because they
point outside the exported tenant's own row set entirely:

- Global lookup tables (role/event_category/element_type/render_type/todo_status) are
  static seed data, identical in every installation - but their numeric ids are not
  guaranteed stable across schema versions, so they are exported/imported by `code`,
  not by id (see LOOKUP_COLUMNS).
- AppUser is a systemwide, cross-tenant table - a user_id from the source installation
  means nothing on the target. These columns are exported/imported by email instead
  (see USER_ID_COLUMNS); if no user with that email exists on the target, the column is
  set to NULL (or, where NULL isn't allowed - e.g. user_tenant_role.user_id - the row is
  skipped) and reported back to the admin as a warning rather than failing the import.
"""

from __future__ import annotations

import copy
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import Date, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models import AppUser, ElementType, EventCategory, RenderType, Role, TodoStatus

LOOKUP_COLUMNS: dict[str, dict[str, type]] = {
    "element_definition": {"element_type_id": ElementType, "render_type_id": RenderType},
    "protocol_element_block": {"element_type_id": ElementType, "render_type_id": RenderType},
    "event": {"event_category_id": EventCategory},
    "protocol_todo": {"todo_status_id": TodoStatus},
    "user_tenant_role": {"role_id": Role},
}

USER_ID_COLUMNS: dict[str, list[str]] = {
    "template": ["created_by"],
    "protocol": ["created_by"],
    "stored_file": ["created_by"],
    "protocol_todo": ["assigned_user_id", "created_by"],
    "attendance_fine": ["collected_by_user_id"],
    "user_template_access": ["user_id"],
    "user_protocol_access": ["user_id"],
    "user_tenant_role": ["user_id"],
}
# user_id is part of the primary key on user_template_access/user_protocol_access/
# user_tenant_role - it can never be NULL, so TenantImportService drops those rows
# entirely (with a warning) rather than nulling the column out when a target user
# can't be resolved by email.


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def row_to_dict(row: Any) -> dict[str, Any]:
    """Serializes every column of `row` (including id/created_at/updated_at) to a JSON-safe dict."""
    mapper = sa_inspect(type(row))
    return {column.key: json_safe(getattr(row, column.key)) for column in mapper.columns}


def coerce_value(column: Any, raw: Any) -> Any:
    if raw is None:
        return None
    col_type = column.type
    if isinstance(col_type, JSONB):
        return raw
    if isinstance(col_type, DateTime):
        return datetime.fromisoformat(raw) if isinstance(raw, str) else raw
    if isinstance(col_type, Date):
        return date.fromisoformat(raw) if isinstance(raw, str) else raw
    if isinstance(col_type, Numeric):
        return raw if isinstance(raw, Decimal) else Decimal(str(raw))
    return raw


def build_row(model: type, data: dict[str, Any], overrides: dict[str, Any] | None = None) -> Any:
    """Builds a new, unattached ORM instance from an exported row dict.

    `id` is always dropped (the DB assigns a fresh one); `created_at`/`updated_at` are kept
    as-is so imported historical data keeps its real timestamps instead of getting "now".
    """
    mapper = sa_inspect(model)
    values: dict[str, Any] = {}
    for column in mapper.columns:
        if column.key == "id":
            continue
        if column.key in data:
            values[column.key] = coerce_value(column, data[column.key])
    if overrides:
        values.update(overrides)
    return model(**values)


class LookupCodeCache:
    """Resolves global lookup-table ids <-> codes, caching one query per model."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._code_by_id: dict[type, dict[int, str]] = {}
        self._id_by_code: dict[type, dict[str, int]] = {}

    def _load(self, model: type) -> None:
        if model in self._code_by_id:
            return
        rows = self.db.query(model).all()
        self._code_by_id[model] = {row.id: row.code for row in rows}
        self._id_by_code[model] = {row.code: row.id for row in rows}

    def code_for(self, model: type, id_value: int) -> str:
        self._load(model)
        try:
            return self._code_by_id[model][id_value]
        except KeyError as exc:
            raise ValueError(f"Unbekannter {model.__tablename__}-Eintrag mit id={id_value}") from exc

    def id_for(self, model: type, code: str) -> int:
        self._load(model)
        try:
            return self._id_by_code[model][code]
        except KeyError as exc:
            raise ValueError(
                f"Ziel-Installation kennt {model.__tablename__}-Code '{code}' nicht - "
                "Import inkompatibel (unterschiedlicher Schema-/Migrationsstand?)."
            ) from exc


class UserEmailCache:
    """Resolves app_user ids <-> emails, caching one query per set of ids/emails looked up."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._email_by_id: dict[int, str] = {}
        self._id_by_email: dict[str, int | None] = {}

    def email_for(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        if user_id not in self._email_by_id:
            user = self.db.get(AppUser, user_id)
            self._email_by_id[user_id] = user.email if user is not None else None
        return self._email_by_id[user_id]

    def id_for(self, email: str | None) -> int | None:
        if email is None:
            return None
        if email not in self._id_by_email:
            user = self.db.query(AppUser).filter(AppUser.email == email).first()
            self._id_by_email[email] = user.id if user is not None else None
        return self._id_by_email[email]


# ── JSONB config remapping ───────────────────────────────────────────────────
#
# Shared between TenantCloneService (same-DB copy) and TenantImportService (restore from
# a portable export) - both need to rewrite the participant/list/event ids embedded in
# these JSONB blobs from an old id space into a newly assigned one.

def remap_document_template_config(config: dict | None, part_map: dict[int, int]) -> dict:
    config = copy.deepcopy(config or {})
    slots = config.get("slots")
    if isinstance(slots, dict):
        config["slots"] = {k: part_map.get(v, v) for k, v in slots.items()}
    theme = config.get("theme")
    if isinstance(theme, dict):
        font_parts = theme.get("font_parts")
        if isinstance(font_parts, dict):
            theme["font_parts"] = {k: part_map.get(v, v) for k, v in font_parts.items()}
    title_assets = config.get("title_assets")
    if isinstance(title_assets, dict):
        config["title_assets"] = {k: part_map.get(v, v) for k, v in title_assets.items()}
    return config


def remap_template_element_config(
    config: dict | None,
    *,
    participant_map: dict[int, int],
    list_definition_map: dict[int, int],
    list_entry_map: dict[int, int],
) -> dict:
    config = copy.deepcopy(config or {})
    responsibility = config.get("responsibility")
    if not isinstance(responsibility, dict) or not isinstance(responsibility.get("assignments"), list):
        return config
    new_assignments = []
    for assignment in responsibility["assignments"]:
        if not isinstance(assignment, dict):
            continue
        new_participant_id = participant_map.get(assignment.get("participant_id"))
        if new_participant_id is None:
            # The participant this assignment pointed at doesn't exist in the new tenant
            # (e.g. structure-only scope, or the participant wasn't included) - drop it
            # rather than keep a dangling reference to an id from the source tenant.
            continue
        new_assignment = {**assignment, "participant_id": new_participant_id}
        list_definition_id = assignment.get("list_definition_id")
        list_entry_id = assignment.get("list_entry_id")
        if list_definition_id and list_entry_id:
            new_list_definition_id = list_definition_map.get(list_definition_id)
            new_list_entry_id = list_entry_map.get(list_entry_id)
            if new_list_definition_id is None or new_list_entry_id is None:
                new_assignment["list_definition_id"] = None
                new_assignment["list_entry_id"] = None
                new_assignment["locked"] = False
            else:
                new_assignment["list_definition_id"] = new_list_definition_id
                new_assignment["list_entry_id"] = new_list_entry_id
        new_assignments.append(new_assignment)
    return {**config, "responsibility": {**responsibility, "assignments": new_assignments}}


def remap_list_value(
    value_type: str | None, raw: dict | None, participant_map: dict[int, int], event_map: dict[int, int]
) -> dict:
    """Remaps participant/event ids embedded in a list_entry value.

    Unresolvable ids are dropped (None / filtered out of the list) rather than left pointing
    at the old id - important for the "structure + Listeninhalt" export scope, where
    participant_map/event_map are always empty (no participants/events in that scope) and a
    naive id passthrough would leave the entry pointing at an unrelated row (or nothing) in
    the target tenant.
    """
    value = copy.deepcopy(raw or {})
    if value_type == "participant" and "participant_id" in value:
        value["participant_id"] = participant_map.get(value["participant_id"])
    elif value_type == "participants" and isinstance(value.get("participant_ids"), list):
        value["participant_ids"] = [participant_map[i] for i in value["participant_ids"] if i in participant_map]
    elif value_type == "event" and "event_id" in value:
        value["event_id"] = event_map.get(value["event_id"])
    return value


def remap_block_configuration(config: dict | None, participant_map: dict[int, int]) -> dict:
    config = config or {}
    entries = config.get("attendance_entries")
    if not isinstance(entries, list):
        return copy.deepcopy(config)
    new_entries = []
    for entry in entries:
        new_entry = dict(entry)
        participant_id = new_entry.get("participant_id")
        if participant_id in participant_map:
            new_entry["participant_id"] = participant_map[participant_id]
        new_entries.append(new_entry)
    rest = {k: copy.deepcopy(v) for k, v in config.items() if k != "attendance_entries"}
    return {**rest, "attendance_entries": new_entries}
