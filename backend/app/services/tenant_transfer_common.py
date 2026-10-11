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
  accounts of the newly created tenant can be referenced (UserIdentityCache.tenant_id) - never
  a same-email account that happens to exist in another tenant of the target. If a reference
  can't be resolved the column is set to NULL (or, where NULL isn't allowed - e.g.
  user_template_access.user_id - the row is skipped) and reported back to the admin as a
  warning rather than failing the import.
"""

from __future__ import annotations

import copy
import re
import secrets
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
    "table_snapshot": ["edited_by"],
    "share_link": ["created_by"],
    "calendar_feed": ["user_id"],
    "photo_album_tenant_share": ["invited_by", "responded_by"],
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


class UserIdentityCache:
    """Portable Identitätsverweise via UUID; alte Archive können weiter E-Mails liefern."""

    def __init__(self, db: Session, *, tenant_id: int | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._id_by_reference: dict[str, int | None] = {}
        self._reference_by_id: dict[int, str | None] = {}

    def reference_for(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        if user_id not in self._reference_by_id:
            user = self.db.get(AppUser, user_id)
            self._reference_by_id[user_id] = (
                str(user.public_id) if user is not None and (self.tenant_id is None or user.tenant_id == self.tenant_id) else None
            )
        return self._reference_by_id[user_id]

    def email_exists(self, email: str | None) -> bool:
        if not email:
            return False
        return self.db.query(AppUser.id).filter(AppUser.email == email.strip().lower(), AppUser.login_enabled.is_(True)).first() is not None

    def set_id(self, reference: str | None, user_id: int) -> None:
        if reference is not None:
            self._id_by_reference[reference] = user_id

    def id_for(self, reference: str | None) -> int | None:
        if reference is None:
            return None
        if reference not in self._id_by_reference:
            query = self.db.query(AppUser)
            if self.tenant_id is not None:
                query = query.filter(AppUser.tenant_id == self.tenant_id)
            try:
                public_id = uuid.UUID(reference)
            except ValueError:
                query = query.filter(AppUser.email == reference)
            else:
                query = query.filter(AppUser.public_id == public_id)
            user = query.first()
            self._id_by_reference[reference] = user.id if user is not None else None
        return self._id_by_reference[reference]


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
    new_assignments = remap_responsible_assignments(
        responsibility["assignments"], participant_map=participant_map,
        list_definition_map=list_definition_map, list_entry_map=list_entry_map,
    )
    return {**config, "responsibility": {**responsibility, "assignments": new_assignments}}


def remap_responsible_assignments(
    assignments: list | None,
    *,
    participant_map: dict[int, int],
    list_definition_map: dict[int, int],
    list_entry_map: dict[int, int],
) -> list | None:
    """Remaps a list of Verantwortlichen-Zuweisungen ({participant_id, list_definition_id,
    list_entry_id, locked, ...}). Same shape in template_element.configuration_json
    ["responsibility"]["assignments"] (the template default) and in
    protocol_element.responsible_assignments_snapshot (the per-protocol frozen copy) - the
    latter used to be copied verbatim, leaving every imported/cloned protocol's
    Verantwortliche pointing at the source tenant's participants/list entries."""
    if not isinstance(assignments, list):
        return assignments
    new_assignments = []
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        new_participant_id = participant_map.get(_as_int(assignment.get("participant_id")))
        if new_participant_id is None:
            # The participant this assignment pointed at doesn't exist in the new tenant
            # (e.g. structure-only scope, or the participant wasn't included) - drop it
            # rather than keep a dangling reference to an id from the source tenant.
            continue
        new_assignment = {**assignment, "participant_id": new_participant_id}
        list_definition_id = _as_int(assignment.get("list_definition_id"))
        list_entry_id = _as_int(assignment.get("list_entry_id"))
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
    return new_assignments


def _as_int(value: Any) -> Any:
    """JSONB ids are normally ints, but a few writers store them as digit strings - normalize
    those so an id_map lookup (int keys) still finds them. Anything else is returned as-is."""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


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
    participant_public_ids: dict[str, int] | None = None,
    event_public_ids: dict[str, int] | None = None,
) -> dict:
    """Remaps every participant/event/list/finance-account id embedded in a block's
    configuration. Shape is shared between template_element_block.configuration_json (the
    per-template defaults, incl. the template_participant_id/template_event_id placeholders
    used by "auto" mode) and protocol_element_block.configuration_snapshot_json (the frozen
    per-protocol copy) - both go through here. Unresolvable ids are dropped rather than left
    pointing at a row from the source tenant/instance."""
    config = copy.deepcopy(config or {})

    # Teilnehmer/Events, die im Protokoll-Editor gewaehlt wurden, stehen im Snapshot als
    # public UUID statt als interne int-ID (siehe snapshot_reference_ids.py). Ohne diese
    # Rueckuebersetzung ueber participant_public_ids/event_public_ids (str(public_id) ->
    # alte interne ID) wuerden sie beim Klonen/Importieren stillschweigend verworfen
    # (Bug 2026-10-05).
    def map_participant(ref):
        if isinstance(ref, str) and participant_public_ids:
            ref = participant_public_ids.get(ref.lower(), ref)
        return participant_map.get(ref)

    def map_event(ref):
        if isinstance(ref, str) and event_public_ids:
            ref = event_public_ids.get(ref.lower(), ref)
        return event_map.get(ref)

    def map_participants(refs: list) -> list:
        return [mapped for mapped in (map_participant(ref) for ref in refs) if mapped is not None]

    def remap_value(value: dict) -> dict:
        value = dict(value)
        if "participant_id" in value:
            value["participant_id"] = map_participant(value["participant_id"])
        if isinstance(value.get("participant_ids"), list):
            value["participant_ids"] = map_participants(value["participant_ids"])
        if "event_id" in value:
            value["event_id"] = map_event(value["event_id"])
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

    # "Wiederholen aus Termin": the block is bound to one Event (and writes back into it, see
    # block_field_sync.py). repeat_source_type == "todo" points at a ProtocolTodo instead -
    # those are created after the blocks, so callers remap them in a second pass via
    # remap_repeat_source_todo() once the todo id map exists.
    if config.get("repeat_source_type") == "event" and config.get("repeat_source_id") is not None:
        config["repeat_source_id"] = map_event(_as_int(config["repeat_source_id"]))

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
            {**entry, "participant_id": map_participant(entry.get("participant_id"))} if isinstance(entry, dict) else entry
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
                new_row["template_participant_id"] = map_participant(new_row["template_participant_id"])
            if isinstance(new_row.get("template_participant_ids"), list):
                new_row["template_participant_ids"] = map_participants(new_row["template_participant_ids"])
            if "template_event_id" in new_row:
                new_row["template_event_id"] = map_event(new_row["template_event_id"])
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


def remap_repeat_source_todo(config: dict | None, todo_map: dict[int, int]) -> dict | None:
    """Second pass for remap_block_configuration: a block with repeat_source_type == "todo"
    points at a ProtocolTodo, which is only created after all blocks exist. Returns the
    remapped config, or None if `config` doesn't reference a todo at all (nothing to update).
    An unresolvable todo id is cleared (the block simply stops repeating) rather than left
    pointing at a source-tenant row."""
    if not isinstance(config, dict) or config.get("repeat_source_type") != "todo":
        return None
    if config.get("repeat_source_id") is None:
        return None
    return {**config, "repeat_source_id": todo_map.get(_as_int(config["repeat_source_id"]))}


# ── public_id handling ───────────────────────────────────────────────────────

def new_uuid7() -> uuid.UUID:
    """UUIDv7 (RFC 9562) - same flavour as the columns' server_default uuidv7(), for the rare
    import case where an exported public_id is already taken on the target and a fresh one has
    to be assigned in Python (so the old -> new mapping is known without a DB round trip)."""
    timestamp_ms = int(datetime.now().timestamp() * 1000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


_UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def replace_public_ids(value: Any, public_id_map: dict[str, str]) -> Any:
    """Recursively rewrites every UUID occurring in `value` (strings, dict keys, list items,
    also embedded like "event-<uuid>") through `public_id_map` (lowercase old -> new). UUIDs
    are globally unique, so a blind textual substitution is safe - it can never hit an
    unrelated value. Used for every reference that is stored by public_id rather than by FK
    (element_ref strings, photo_album_item.file_id, table snapshots, word-import drafts)."""
    if not public_id_map:
        return value
    if isinstance(value, str):
        return _UUID_PATTERN.sub(lambda m: public_id_map.get(m.group(0).lower(), m.group(0)), value)
    if isinstance(value, list):
        return [replace_public_ids(item, public_id_map) for item in value]
    if isinstance(value, dict):
        return {replace_public_ids(k, public_id_map): replace_public_ids(v, public_id_map) for k, v in value.items()}
    return value


# ── Word-Import JSON remapping ───────────────────────────────────────────────
#
# WordImportProfile.mapping_config_json and WordImportDocument.analysis_snapshot_json embed
# internal ids of participants/events/list definitions/list entries/template elements/
# protocols - as plain values, inside "{template_element_id}:{block_sort_index}" matrix keys
# and inside generated Matrix column keys ("gen-p-<participant>", "gen-e-<event>",
# "gen-l-<list_entry>"). Unresolvable references are dropped (or set to None where the
# schema allows it) - never left pointing at a row of the source tenant/installation.

class WordImportIdMaps:
    def __init__(
        self,
        *,
        participant_map: dict[int, int],
        event_map: dict[int, int],
        list_definition_map: dict[int, int],
        list_entry_map: dict[int, int],
        template_element_map: dict[int, int],
        protocol_map: dict[int, int] | None = None,
    ) -> None:
        self.participant = participant_map
        self.event = event_map
        self.list_definition = list_definition_map
        self.list_entry = list_entry_map
        self.template_element = template_element_map
        self.protocol = protocol_map or {}

    @staticmethod
    def _get(id_map: dict[int, int], value: Any) -> int | None:
        return id_map.get(_as_int(value)) if value is not None else None

    def matrix_key(self, key: Any) -> str | None:
        """"{template_element_id}:{block_sort_index}" -> same with the new element id."""
        if not isinstance(key, str) or ":" not in key:
            return None
        element_id, _, rest = key.partition(":")
        new_element_id = self._get(self.template_element, element_id)
        return f"{new_element_id}:{rest}" if new_element_id is not None else None

    def column_key(self, key: Any) -> Any:
        """Generated Matrix column keys embed an id; template-configured keys are kept as-is.
        Returns None for a generated key whose entity wasn't imported."""
        if not isinstance(key, str):
            return key
        match = re.fullmatch(r"gen-([pel])-(\d+)", key)
        if match is None:
            return key
        id_map = {"p": self.participant, "e": self.event, "l": self.list_entry}[match.group(1)]
        new_id = id_map.get(int(match.group(2)))
        return f"gen-{match.group(1)}-{new_id}" if new_id is not None else None


def remap_word_import_profile_config(config: dict | None, maps: WordImportIdMaps) -> dict:
    config = copy.deepcopy(config or {})
    get = WordImportIdMaps._get

    heading_to_target = config.get("heading_to_target")
    if isinstance(heading_to_target, dict):
        new_headings = {}
        for heading, target in heading_to_target.items():
            if not isinstance(target, dict):
                continue
            new_element_id = get(maps.template_element, target.get("template_element_id"))
            if new_element_id is not None:
                new_headings[heading] = {**target, "template_element_id": new_element_id}
        config["heading_to_target"] = new_headings

    table_roles = config.get("table_roles_by_signature")
    if isinstance(table_roles, dict):
        new_roles = {}
        for signature, role in table_roles.items():
            if not isinstance(role, dict):
                continue
            new_role = dict(role)
            if role.get("list_definition_id") is not None:
                new_role["list_definition_id"] = get(maps.list_definition, role["list_definition_id"])
                if new_role["list_definition_id"] is None:
                    continue
            if role.get("matrix_key") is not None:
                new_role["matrix_key"] = maps.matrix_key(role["matrix_key"])
                if new_role["matrix_key"] is None:
                    continue
            new_roles[signature] = new_role
        config["table_roles_by_signature"] = new_roles

    name_overrides = config.get("participant_name_overrides")
    if isinstance(name_overrides, dict):
        config["participant_name_overrides"] = {
            name: (None if participant_id is None else get(maps.participant, participant_id))
            for name, participant_id in name_overrides.items()
            if participant_id is None or get(maps.participant, participant_id) is not None
        }

    matrix_column_overrides = config.get("matrix_column_overrides")
    if isinstance(matrix_column_overrides, dict):
        new_overrides = {}
        for key, column_key in matrix_column_overrides.items():
            new_key = _remap_matrix_prefixed_key(key, maps)
            new_column_key = maps.column_key(column_key)
            if new_key is not None and new_column_key is not None:
                new_overrides[new_key] = new_column_key
        config["matrix_column_overrides"] = new_overrides

    rejected = config.get("rejected_candidates")
    if isinstance(rejected, dict):
        new_rejected = {}
        for key, entry in rejected.items():
            remapped = _remap_rejected_candidate(key, entry, maps)
            if remapped is not None:
                new_rejected[remapped[0]] = remapped[1]
        config["rejected_candidates"] = new_rejected

    conflicts = config.get("event_conflict_resolutions")
    if isinstance(conflicts, dict):
        new_conflicts = {}
        for key, resolution in conflicts.items():
            event_id, sep, title = str(key).partition("|")
            new_event_id = get(maps.event, event_id)
            if sep and new_event_id is not None:
                new_conflicts[f"{new_event_id}|{title}"] = resolution
        config["event_conflict_resolutions"] = new_conflicts

    new_event_links = config.get("new_event_link_resolutions")
    if isinstance(new_event_links, dict):
        config["new_event_link_resolutions"] = {
            title: {**link, "linked_event_id": get(maps.event, link.get("linked_event_id"))}
            for title, link in new_event_links.items()
            if isinstance(link, dict) and get(maps.event, link.get("linked_event_id")) is not None
        }

    ignored = config.get("event_ignored_keys")
    if isinstance(ignored, list):
        new_ignored = []
        for key in ignored:
            # Matrix-sourced keys are "{matrix_key}:{row_id}:{column_key}:{title}", plain
            # Termine-table keys are just the normalized title (see _event_ignore_key).
            if isinstance(key, str) and re.match(r"\d+:\d+:", key):
                element_id, sort_index, row_id, rest = (key.split(":", 3) + ["", "", ""])[:4]
                new_matrix_key = maps.matrix_key(f"{element_id}:{sort_index}")
                column_key, sep, title = rest.partition(":")
                new_column_key = maps.column_key(column_key)
                if new_matrix_key is None or new_column_key is None:
                    continue
                key = f"{new_matrix_key}:{row_id}:{new_column_key}{sep}{title}"
            new_ignored.append(key)
        config["event_ignored_keys"] = new_ignored

    return config


def _remap_matrix_prefixed_key(key: Any, maps: WordImportIdMaps) -> str | None:
    """"{element_id}:{sort_index}:{rest}" -> same with the new element id."""
    if not isinstance(key, str):
        return None
    element_id, sort_index, rest = (key.split(":", 2) + ["", ""])[:3]
    new_matrix_key = maps.matrix_key(f"{element_id}:{sort_index}")
    return f"{new_matrix_key}:{rest}" if new_matrix_key is not None else None


def _remap_rejected_candidate(key: str, entry: Any, maps: WordImportIdMaps) -> tuple[str, Any] | None:
    """rejected_candidates is {"{signal}:{context}": {"rejected": [ids], "chosen": id}}; which
    id space the ids live in depends on the signal prefix (see WordImportService.commit's
    _log_outcome call sites)."""
    if not isinstance(entry, dict):
        return None
    prefix, _, context = str(key).partition(":")
    if prefix == "event":
        new_key, convert = key, lambda v: WordImportIdMaps._get(maps.event, v)
    elif prefix == "name":
        new_key, convert = key, lambda v: WordImportIdMaps._get(maps.participant, v)
    elif prefix == "list_entry":
        list_definition_id, _, raw = context.partition(":")
        new_list_definition_id = WordImportIdMaps._get(maps.list_definition, list_definition_id)
        if new_list_definition_id is None:
            return None
        new_key, convert = f"list_entry:{new_list_definition_id}:{raw}", lambda v: WordImportIdMaps._get(maps.list_entry, v)
    elif prefix == "matrix_column":
        new_context = _remap_matrix_prefixed_key(context, maps)
        if new_context is None:
            return None
        new_key, convert = f"matrix_column:{new_context}", maps.column_key
    else:
        # table_role (role names) and anything unknown carry no ids.
        return key, entry
    rejected = [mapped for mapped in (convert(v) for v in entry.get("rejected") or []) if mapped is not None]
    chosen = convert(entry["chosen"]) if entry.get("chosen") is not None else None
    if not rejected:
        return None
    return new_key, {**entry, "rejected": rejected, "chosen": chosen}


def remap_word_import_analysis(analysis: dict | None, maps: WordImportIdMaps) -> dict:
    """Mirror of routes/word_import.py's _collect_analysis_ids: rewrites every id it collects
    (plus matrix keys and generated column keys) into the new id space."""
    analysis = copy.deepcopy(analysis or {})
    get = WordImportIdMaps._get

    def remap_names(names: Any) -> Any:
        if not isinstance(names, list):
            return names
        for name in names:
            if not isinstance(name, dict):
                continue
            for field in ("participant_id", "originally_suggested_participant_id"):
                if name.get(field) is not None:
                    name[field] = get(maps.participant, name[field])
            name["candidates"] = _filter_candidates(name.get("candidates"), "participant_id", maps.participant)
        return names

    def remap_fields(fields: Any) -> Any:
        for field in fields if isinstance(fields, list) else []:
            if isinstance(field, dict):
                remap_names(field.get("names"))
        return fields

    for table in analysis.get("tables") or []:
        if table.get("list_definition_id") is not None:
            table["list_definition_id"] = get(maps.list_definition, table["list_definition_id"])
        if table.get("matrix_key") is not None:
            table["matrix_key"] = maps.matrix_key(table["matrix_key"])

    for mapping in analysis.get("text_mappings") or []:
        if mapping.get("template_element_id") is not None:
            mapping["template_element_id"] = get(maps.template_element, mapping["template_element_id"])
        if mapping.get("matched_event_id") is not None:
            mapping["matched_event_id"] = get(maps.event, mapping["matched_event_id"])
        mapping["event_candidates"] = _filter_candidates(mapping.get("event_candidates"), "event_id", maps.event)
        remap_fields(mapping.get("form_fields"))
        if isinstance(mapping.get("form_fields_by_target"), dict):
            mapping["form_fields_by_target"] = {
                maps.matrix_key(key): remap_fields(fields)
                for key, fields in mapping["form_fields_by_target"].items()
                if maps.matrix_key(key) is not None
            }

    if "text_targets" in analysis:
        analysis["text_targets"] = _filter_candidates(analysis["text_targets"], "template_element_id", maps.template_element)

    for mapping in analysis.get("attendance_mappings") or []:
        if mapping.get("suggested_participant_id") is not None:
            mapping["suggested_participant_id"] = get(maps.participant, mapping["suggested_participant_id"])
        mapping["candidates"] = _filter_candidates(mapping.get("candidates"), "participant_id", maps.participant)

    for mapping in analysis.get("event_mappings") or []:
        if mapping.get("matched_event_id") is not None:
            mapping["matched_event_id"] = get(maps.event, mapping["matched_event_id"])
        mapping["candidates"] = _filter_candidates(mapping.get("candidates"), "event_id", maps.event)
        if mapping.get("matrix_key") is not None:
            mapping["matrix_key"] = maps.matrix_key(mapping["matrix_key"])
        if mapping.get("column_key") is not None:
            mapping["column_key"] = maps.column_key(mapping["column_key"])

    if "list_definitions" in analysis:
        analysis["list_definitions"] = _filter_candidates(analysis["list_definitions"], "id", maps.list_definition)

    for mapping in analysis.get("list_mappings") or []:
        if mapping.get("matched_entry_id") is not None:
            mapping["matched_entry_id"] = get(maps.list_entry, mapping["matched_entry_id"])
        remap_names(mapping.get("column_one_names"))
        remap_names(mapping.get("column_two_names"))
        mapping["candidates"] = _filter_candidates(mapping.get("candidates"), "entry_id", maps.list_entry)

    if "matrix_options" in analysis:
        analysis["matrix_options"] = [
            {**option, "matrix_key": maps.matrix_key(option.get("matrix_key"))}
            for option in analysis["matrix_options"] or []
            if isinstance(option, dict) and maps.matrix_key(option.get("matrix_key")) is not None
        ]

    new_matrix_mappings = []
    for mapping in analysis.get("matrix_mappings") or []:
        new_matrix_key = maps.matrix_key(mapping.get("matrix_key"))
        if new_matrix_key is None:
            continue
        mapping["matrix_key"] = new_matrix_key
        if mapping.get("column_key") is not None:
            mapping["column_key"] = maps.column_key(mapping["column_key"])
        mapping["column_candidates"] = [
            {**candidate, "column_key": maps.column_key(candidate.get("column_key"))}
            for candidate in mapping.get("column_candidates") or []
            if isinstance(candidate, dict) and maps.column_key(candidate.get("column_key")) is not None
        ]
        remap_names(mapping.get("names"))
        new_matrix_mappings.append(mapping)
    if "matrix_mappings" in analysis:
        analysis["matrix_mappings"] = new_matrix_mappings

    if "duplicate_protocols" in analysis:
        analysis["duplicate_protocols"] = _filter_candidates(analysis["duplicate_protocols"], "id", maps.protocol)
    return analysis


def _filter_candidates(items: Any, id_field: str, id_map: dict[int, int]) -> list:
    """Remaps `id_field` of every dict in `items`, dropping those whose id can't be resolved."""
    result = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        new_id = WordImportIdMaps._get(id_map, item.get(id_field))
        if new_id is not None:
            result.append({**item, id_field: new_id})
    return result


# ── table_snapshot (cycle snapshots of list_definition / list_entry) ─────────

def remap_table_snapshot_rows(
    table_name: str,
    rows: list | None,
    *,
    new_tenant_id: int,
    list_definition_map: dict[int, int],
    list_entry_map: dict[int, int],
    participant_map: dict[int, int],
    event_map: dict[int, int],
    public_id_map: dict[str, str],
) -> list:
    """table_snapshot.snapshot_json holds row_to_dict() copies of list_definition/list_entry
    rows as of a cycle boundary - including rows that were deleted live since. Live rows map
    through the id maps; a historical row without a live counterpart gets a negative
    placeholder id (-old_id): unique within the snapshot (entries still group under their
    definition) but guaranteed never to collide with a real row on the target. public_ids
    (the identity reconstruction works with) go through public_id_map; participant/event
    references inside the list values are remapped like live list entries."""
    id_map = list_definition_map if table_name == "list_definition" else list_entry_map

    def remap_id(value: Any, mapping: dict[int, int]) -> Any:
        value = _as_int(value)
        if not isinstance(value, int) or isinstance(value, bool):
            return value
        return mapping.get(value, -abs(value))

    def remap_reference(value: Any, mapping: dict[int, int]) -> Any:
        # Values are internal ids or (after an edit through the API) public UUIDs.
        if isinstance(_as_int(value), int):
            return mapping.get(_as_int(value))
        return value

    new_rows = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            new_rows.append(row)
            continue
        row = replace_public_ids(copy.deepcopy(row), public_id_map)
        if "id" in row:
            row["id"] = remap_id(row["id"], id_map)
        if "tenant_id" in row:
            row["tenant_id"] = new_tenant_id
        if "list_definition_id" in row:
            row["list_definition_id"] = remap_id(row["list_definition_id"], list_definition_map)
        for column in ("column_one_value_json", "column_two_value_json"):
            value = row.get(column)
            if not isinstance(value, dict):
                continue
            for key, mapping in (("participant", participant_map), ("event", event_map)):
                # An unmapped internal id falls back to the parallel *_public_id(s) value the
                # snapshot keeps alongside (see snapshot_list_references.py) - the reader
                # accepts both forms. Lists are never shortened: participant_names and
                # *_public_ids are index-aligned with them.
                if f"{key}_id" in value:
                    mapped = remap_reference(value[f"{key}_id"], mapping)
                    value[f"{key}_id"] = mapped if mapped is not None else value.get(f"{key}_public_id")
                if isinstance(value.get(f"{key}_ids"), list):
                    public_ids = value.get(f"{key}_public_ids") or []
                    value[f"{key}_ids"] = [
                        mapped if mapped is not None else (public_ids[index] if index < len(public_ids) else None)
                        for index, mapped in enumerate(remap_reference(v, mapping) for v in value[f"{key}_ids"])
                    ]
        new_rows.append(row)
    return new_rows
