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
- AppUser ids from the source installation mean nothing on the target. These columns are
  exported/imported by email instead (see USER_ID_COLUMNS). A user belongs to exactly one
  tenant, so only the exported tenant's own users are ever exported, and on import only the
  accounts of the newly created tenant can be referenced (UserEmailCache.tenant_id) - never
  a same-email account that happens to exist in another tenant of the target. If a reference
  can't be resolved the column is set to NULL (or, where NULL isn't allowed - e.g.
  user_template_access.user_id - the row is skipped) and reported back to the admin as a
  warning rather than failing the import.
"""

from __future__ import annotations

import copy
import uuid
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
    "app_user": {"role_id": Role},
}

REDACTED_PASSWORD_HASH_MARKER = "REDACTED:not-a-tenant-member"
"""Legacy (format_version 2) exports wrote this placeholder into app_user.password_hash for
users who were only referenced as metadata (e.g. created_by) but were not members of the
exported tenant. Exports no longer contain such users at all (every exported user is a member
of the exported tenant), but TenantImportService still recognizes the marker in old archives
and generates a random unusable hash instead of ever writing this literal string to the
password_hash column."""

USER_ID_COLUMNS: dict[str, list[str]] = {
    "participant": ["app_user_id"],
    "template": ["created_by"],
    "protocol": ["created_by"],
    "stored_file": ["created_by"],
    "gallery_image": ["created_by"],
    "word_import_document": ["created_by", "imported_by"],
    "protocol_todo": ["assigned_user_id", "created_by"],
    "attendance_fine": ["collected_by_user_id"],
    "user_template_access": ["user_id"],
    "user_protocol_access": ["user_id"],
    "user_protocol_scroll": ["user_id"],
}
# user_id is part of the primary key on user_template_access/user_protocol_access/
# user_protocol_scroll - it can never be NULL, so TenantImportService drops those rows
# entirely (with a warning) rather than nulling the column out when a target user
# can't be resolved by email.


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
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


FORCED_SECURE_DEFAULTS: dict[str, Any] = {"scan_status": "pending"}
"""Columns that must never be taken from an imported manifest, even though they're ordinary
non-computed model columns build_row() would otherwise happily copy 1:1. StoredFile.scan_status
in particular gates whether get_stored_file_content() (routes/files.py) will ever serve the
file's bytes - a manifest shipping `"scan_status": "clean"` for a file that was never actually
run past ClamAV would let an attacker's payload skip the scan workflow entirely and be served
as trusted content (audit S4, 2026-08-16). Every imported StoredFile must start in the same
"pending until scanned" state a fresh upload gets. Note StoredFile.scan_status even has a
DB-level server_default of 'clean' (see models/entities.py) - simply omitting the column from
`values` and letting the DB default kick in would NOT be safe, so the value is forced here
explicitly. A call site can still legitimately set the real, freshly-computed scan result via
`overrides` (see TenantImportService._import_stored_files, which actually re-scans the restored
file bytes through ClamAV) - `overrides` is applied after this loop and wins."""


def build_row(model: type, data: dict[str, Any], overrides: dict[str, Any] | None = None) -> Any:
    """Builds a new, unattached ORM instance from an exported row dict.

    `id` is always dropped (the DB assigns a fresh one); so is `public_id` (the imported row
    gets its own fresh UUIDv7 via the column's server_default - reusing the exported value
    would collide with the still-existing source row's public_id under the UNIQUE
    constraint). So is any DB-computed column (e.g. app_user.name is `GENERATED ALWAYS AS
    (display_name)` - Postgres rejects an explicit value for it). `created_at`/`updated_at`
    are kept as-is so imported historical data keeps its real timestamps instead of getting
    "now". See FORCED_SECURE_DEFAULTS for the (small) set of columns that are never trusted
    from the manifest regardless.
    """
    mapper = sa_inspect(model)
    values: dict[str, Any] = {}
    for column in mapper.columns:
        if column.key in ("id", "public_id") or column.computed is not None:
            continue
        if column.key in FORCED_SECURE_DEFAULTS:
            values[column.key] = FORCED_SECURE_DEFAULTS[column.key]
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
    """Resolves app_user ids <-> emails, caching one query per set of ids/emails looked up.

    When `tenant_id` is set, only that tenant's own users are ever resolved (both directions):
    a user of any other tenant looks like "no such user". Export sets it to the exported
    tenant, so a stray reference to a foreign tenant's user (e.g. created_by copied over by a
    tenant clone) is exported as NULL instead of leaking that user's email; import sets it to
    the newly created tenant once it exists, so a reference can never link to a same-email
    account of another tenant of the target installation.
    """

    def __init__(self, db: Session, *, tenant_id: int | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._email_by_id: dict[int, str | None] = {}
        self._id_by_email: dict[str, int | None] = {}

    def _in_scope(self, user: AppUser | None) -> bool:
        return user is not None and (self.tenant_id is None or user.tenant_id == self.tenant_id)

    def email_for(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        if user_id not in self._email_by_id:
            user = self.db.get(AppUser, user_id)
            self._email_by_id[user_id] = user.email if self._in_scope(user) else None
        return self._email_by_id[user_id]

    def email_exists(self, email: str) -> bool:
        """Whether ANY account (of any tenant) already owns this email - for import's
        "would creating this account collide" check, deliberately not scoped by tenant_id."""
        return self.db.query(AppUser.id).filter(AppUser.email == email).first() is not None

    def set_id(self, email: str, user_id: int) -> None:
        """Used on import right after creating a brand new account (see
        TenantImportService._import_app_users) - without this, the `id_for` call that was
        used to check "does this email already exist" would have already cached the answer
        as None, and every later lookup for that email would keep returning None forever
        even though the account exists now."""
        self._id_by_email[email] = user_id

    def id_for(self, email: str | None) -> int | None:
        if email is None:
            return None
        if email not in self._id_by_email:
            user = self.db.query(AppUser).filter(AppUser.email == email).first()
            self._id_by_email[email] = user.id if self._in_scope(user) else None
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


def remap_block_configuration(
    config: dict | None,
    *,
    participant_map: dict[int, int],
    event_map: dict[int, int],
    list_definition_map: dict[int, int],
    list_entry_map: dict[int, int],
    finance_account_map: dict[int, int],
) -> dict:
    """Remaps every participant/event/list/finance-account id embedded in a block's
    configuration. Shape is shared between template_element_block.configuration_json (the
    per-template defaults, incl. the template_participant_id/template_event_id placeholders
    used by "auto" mode) and protocol_element_block.configuration_snapshot_json (the frozen
    per-protocol copy) - both go through here. Unresolvable ids are dropped rather than left
    pointing at a row from the source tenant/instance."""
    config = copy.deepcopy(config or {})

    def remap_value(value: dict) -> dict:
        value = dict(value)
        if "participant_id" in value:
            value["participant_id"] = participant_map.get(value["participant_id"])
        if isinstance(value.get("participant_ids"), list):
            value["participant_ids"] = [participant_map[i] for i in value["participant_ids"] if i in participant_map]
        if "event_id" in value:
            value["event_id"] = event_map.get(value["event_id"])
        return value

    def remap_list_link(container: dict) -> dict:
        # Row-level "Zeile aus Liste"/"Spalte aus Liste" link, shared by the flattened
        # protocol-snapshot row shape (linked_list_id directly on the row) and the nested
        # template/element_definition row shape (linked_list_id under row.row_config).
        if container.get("linked_list_id") is None:
            return container
        container = dict(container)
        new_list_id = list_definition_map.get(container["linked_list_id"])
        container["linked_list_id"] = new_list_id
        entry_id = container.get("linked_list_entry_id")
        container["linked_list_entry_id"] = (
            list_entry_map.get(entry_id) if new_list_id is not None and entry_id is not None else None
        )
        return container

    if config.get("linked_list_id") is not None:
        config["linked_list_id"] = list_definition_map.get(config["linked_list_id"])
    if config.get("fine_account_id") is not None:
        config["fine_account_id"] = finance_account_map.get(config["fine_account_id"])
    if config.get("finance_account_id") is not None:
        config["finance_account_id"] = finance_account_map.get(config["finance_account_id"])

    auto_source = config.get("auto_source")
    if isinstance(auto_source, dict) and auto_source.get("list_id") is not None:
        config["auto_source"] = {**auto_source, "list_id": list_definition_map.get(auto_source["list_id"])}

    entries = config.get("attendance_entries")
    if isinstance(entries, list):
        config["attendance_entries"] = [
            {**entry, "participant_id": participant_map.get(entry.get("participant_id"))} if isinstance(entry, dict) else entry
            for entry in entries
        ]

    rows = config.get("rows")
    if isinstance(rows, list):
        new_rows = []
        for row in rows:
            if not isinstance(row, dict):
                new_rows.append(row)
                continue
            new_row = remap_list_link(remap_value(row))
            if isinstance(new_row.get("row_config"), dict):
                new_row["row_config"] = remap_list_link(new_row["row_config"])
            if "template_participant_id" in new_row:
                new_row["template_participant_id"] = participant_map.get(new_row["template_participant_id"])
            if isinstance(new_row.get("template_participant_ids"), list):
                new_row["template_participant_ids"] = [
                    participant_map[i] for i in new_row["template_participant_ids"] if i in participant_map
                ]
            if "template_event_id" in new_row:
                new_row["template_event_id"] = event_map.get(new_row["template_event_id"])
            new_rows.append(new_row)
        config["rows"] = new_rows

    columns = config.get("columns")
    if isinstance(columns, list):
        new_columns = []
        for column in columns:
            if not isinstance(column, dict):
                new_columns.append(column)
                continue
            new_column = dict(column)
            row_values = new_column.get("row_values")
            if isinstance(row_values, dict):
                new_column["row_values"] = {
                    row_id: (remap_value(value) if isinstance(value, dict) else value)
                    for row_id, value in row_values.items()
                }
            new_columns.append(new_column)
        config["columns"] = new_columns

    return config


def remap_element_definition_config(
    config: dict | None,
    *,
    participant_map: dict[int, int],
    event_map: dict[int, int],
    list_definition_map: dict[int, int],
    list_entry_map: dict[int, int],
    finance_account_map: dict[int, int],
) -> dict:
    """element_definition.configuration_json is `{"blocks": [...]}`, where each block carries
    its own nested `configuration_json` (same shape remap_block_configuration already handles -
    linked_list_id, fine_account_id, rows[], columns[].row_values, ...). This is the ACTUAL
    source of a block's list/participant/event/finance-account links (not
    template_element_block, which exists but isn't where the block designer UI writes to) - it
    was previously copied through verbatim on both clone and import, leaving every "linked list"
    pointed at the source tenant's list_definition id."""
    config = copy.deepcopy(config or {})
    blocks = config.get("blocks")
    if not isinstance(blocks, list):
        return config
    new_blocks = []
    for block in blocks:
        if not isinstance(block, dict):
            new_blocks.append(block)
            continue
        new_block = dict(block)
        new_block["configuration_json"] = remap_block_configuration(
            block.get("configuration_json"),
            participant_map=participant_map, event_map=event_map,
            list_definition_map=list_definition_map, list_entry_map=list_entry_map,
            finance_account_map=finance_account_map,
        )
        new_blocks.append(new_block)
    config["blocks"] = new_blocks
    return config
