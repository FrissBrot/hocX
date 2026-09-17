"""Snapshotting of structured-list data referenced by protocol blocks (both the
whole-list "Gekoppelte Liste" Tabellenblock mode and the single-row "Zeile aus Liste"
mode), so a protocol shows a frozen view of list data with an explicit, undoable
"Daten aktualisieren" refresh instead of always reading the shared list live.

Mirrors the module-level-function style and "live until abgeschlossen" precedent of
responsible_label_service.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ListDefinition, ListEntry, Protocol, ProtocolElement, ProtocolElementBlock, TableSnapshot
from app.services.event_cycle_service import resolve_protocol_cycle


@dataclass
class ListSnapshotCache:
    """Per-call memoization for compute_whole_list_snapshot/compute_row_list_snapshot, so a
    refresh-all pass over many blocks that reference the same underlying list (a common case -
    e.g. a shared "Verantwortliche" list linked from several blocks) issues each list's
    definition/entries query at most once instead of once per block. Purely an optimization -
    behavior is identical to passing no cache at all, just with fewer round-trips."""

    definitions: dict[int, ListDefinition | None] = field(default_factory=dict)
    entries: dict[int, list[ListEntry]] = field(default_factory=dict)
    # (cycle_config_id, cycle_year, table_name) -> TableSnapshot|None. Added alongside the
    # live-row caches above (audit fix, 2026-09-17) so compute_row_list_snapshot_for_
    # protocol's "historical" branch can actually benefit from a cache the caller passed
    # in - it used to accept `cache` but never forward it to
    # _compute_row_list_snapshot_from_table_snapshot, so every historical-sourced row in a
    # refresh-all pass re-queried both TableSnapshot rows from scratch even when the
    # caller had gone out of its way to build a shared cache specifically to avoid that.
    table_snapshots: dict[tuple[int, int, str], TableSnapshot | None] = field(default_factory=dict)

    def get_table_snapshot(
        self, db: Session, *, tenant_id: int, cycle_config_id: int, cycle_year: int, table_name: str
    ) -> TableSnapshot | None:
        key = (cycle_config_id, cycle_year, table_name)
        if key not in self.table_snapshots:
            self.table_snapshots[key] = db.scalar(
                select(TableSnapshot).where(
                    TableSnapshot.tenant_id == tenant_id,
                    TableSnapshot.cycle_config_id == cycle_config_id,
                    TableSnapshot.cycle_year == cycle_year,
                    TableSnapshot.table_name == table_name,
                )
            )
        return self.table_snapshots[key]

    def get_definition(self, db: Session, list_definition_id: int, tenant_id: int) -> ListDefinition | None:
        if list_definition_id not in self.definitions:
            definition = db.get(ListDefinition, list_definition_id)
            # linked_list_id/rows[].linked_list_id are client-supplied (configuration_snapshot_json)
            # and only ever validated as "exists", never as "belongs to this tenant" - without this
            # check a writer could point a block at another tenant's list_definition_id and exfiltrate
            # its entries via refresh/sync. Treat cross-tenant the same as "list was deleted".
            self.definitions[list_definition_id] = definition if definition is not None and definition.tenant_id == tenant_id else None
        return self.definitions[list_definition_id]

    def get_entries(self, db: Session, list_definition_id: int) -> list[ListEntry]:
        if list_definition_id not in self.entries:
            self.entries[list_definition_id] = list(
                db.scalars(
                    select(ListEntry)
                    .where(ListEntry.list_definition_id == list_definition_id)
                    .order_by(ListEntry.sort_index.asc(), ListEntry.id.asc())
                )
            )
        return self.entries[list_definition_id]


def compute_whole_list_snapshot(
    db: Session, list_definition_id: int, tenant_id: int, *, cache: ListSnapshotCache | None = None
) -> dict[str, Any] | None:
    """Full frozen view of a list for the "Gekoppelte Liste" whole-list mode, or None if
    the list itself was deleted (or belongs to a different tenant - see
    ListSnapshotCache.get_definition)."""
    if cache:
        definition = cache.get_definition(db, list_definition_id, tenant_id)
    else:
        definition = db.get(ListDefinition, list_definition_id)
        if definition is not None and definition.tenant_id != tenant_id:
            definition = None
    if definition is None:
        return None
    entries = (
        cache.get_entries(db, list_definition_id)
        if cache
        else list(
            db.scalars(
                select(ListEntry)
                .where(ListEntry.list_definition_id == list_definition_id)
                .order_by(ListEntry.sort_index.asc(), ListEntry.id.asc())
            )
        )
    )
    return {
        "synced_version": definition.content_version,
        "column_one_title": definition.column_one_title,
        "column_one_value_type": definition.column_one_value_type,
        "column_two_title": definition.column_two_title,
        "column_two_value_type": definition.column_two_value_type,
        "entries": [
            {
                "id": entry.id,
                "sort_index": entry.sort_index,
                "column_one_value": dict(entry.column_one_value_json or {}),
                "column_two_value": dict(entry.column_two_value_json or {}),
            }
            for entry in entries
        ],
        "previous": None,
    }


def compute_row_list_snapshot(
    db: Session, list_definition_id: int, list_entry_id: int, tenant_id: int, *, cache: ListSnapshotCache | None = None
) -> dict[str, Any]:
    """Frozen view of one list entry for a "Zeile aus Liste" row. Stores both raw column
    values (not just the row's own fixed/variable split) so which column is "fixed" can
    still change without needing to recompute. entry_exists=False means the entry (or the
    whole list) was deleted since the last sync, or belongs to a different tenant (see
    ListSnapshotCache.get_definition) - callers show the existing "Verknuepfter
    Listeneintrag wurde geloescht" message in that case."""
    if cache:
        definition = cache.get_definition(db, list_definition_id, tenant_id)
    else:
        definition = db.get(ListDefinition, list_definition_id)
        if definition is not None and definition.tenant_id != tenant_id:
            definition = None
    if definition is None:
        return {"synced_version": 0, "entry_exists": False}
    if cache and list_definition_id in cache.entries:
        entry = next((e for e in cache.entries[list_definition_id] if e.id == list_entry_id), None)
    else:
        entry = db.get(ListEntry, list_entry_id)
    base = {
        "synced_version": definition.content_version,
        "column_one_title": definition.column_one_title,
        "column_one_value_type": definition.column_one_value_type,
        "column_two_title": definition.column_two_title,
        "column_two_value_type": definition.column_two_value_type,
    }
    if entry is None:
        return {**base, "entry_exists": False}
    return {
        **base,
        "entry_exists": True,
        "column_one_value": dict(entry.column_one_value_json or {}),
        "column_two_value": dict(entry.column_two_value_json or {}),
        "previous": None,
    }


def _compute_row_list_snapshot_from_table_snapshot(
    db: Session, *, tenant_id: int, cycle_config_id: int, cycle_year: int, list_definition_id: int, list_entry_id: int,
    cache: ListSnapshotCache | None = None,
) -> dict[str, Any] | None:
    """Same return shape as compute_row_list_snapshot, resolved from a frozen
    table_snapshot (see app/services/table_snapshot_service.py) for
    (cycle_config_id, cycle_year) instead of the live ListEntry table. Matches rows by
    their internal id, which table_snapshot rows keep verbatim (no remapping - see
    TableSnapshot's model docstring). Returns None (not a dict) if that cycle has no
    list_definition snapshot at all yet, so the caller can fall back to live data -
    entry_exists=False is reserved for "the list has a snapshot but this entry wasn't in
    it", a real, distinct answer from "no historical data exists for this cycle at all".

    cache, when given, memoizes the two TableSnapshot lookups the same way
    ListSnapshotCache already memoizes live ListDefinition/ListEntry lookups - see
    compute_row_list_snapshot_for_protocol, whose refresh-all-blocks caller builds one
    cache and expects every row in the pass to share it (audit fix, 2026-09-17)."""

    def _lookup(table_name: str) -> TableSnapshot | None:
        if cache is not None:
            return cache.get_table_snapshot(
                db, tenant_id=tenant_id, cycle_config_id=cycle_config_id, cycle_year=cycle_year, table_name=table_name
            )
        return db.scalar(
            select(TableSnapshot).where(
                TableSnapshot.tenant_id == tenant_id,
                TableSnapshot.cycle_config_id == cycle_config_id,
                TableSnapshot.cycle_year == cycle_year,
                TableSnapshot.table_name == table_name,
            )
        )

    definition_snapshot = _lookup("list_definition")
    if definition_snapshot is None:
        return None
    def_row = next((r for r in definition_snapshot.snapshot_json if r.get("id") == list_definition_id), None)
    if def_row is None:
        return None
    base = {
        "synced_version": def_row.get("content_version", 0),
        "column_one_title": def_row.get("column_one_title"),
        "column_one_value_type": def_row.get("column_one_value_type"),
        "column_two_title": def_row.get("column_two_title"),
        "column_two_value_type": def_row.get("column_two_value_type"),
    }
    entry_snapshot = _lookup("list_entry")
    entry_row = next(
        (r for r in (entry_snapshot.snapshot_json if entry_snapshot else []) if r.get("id") == list_entry_id),
        None,
    )
    if entry_row is None:
        return {**base, "entry_exists": False}
    return {
        **base,
        "entry_exists": True,
        "column_one_value": dict(entry_row.get("column_one_value_json") or {}),
        "column_two_value": dict(entry_row.get("column_two_value_json") or {}),
        "previous": None,
    }


def compute_row_list_snapshot_for_protocol(
    db: Session,
    *,
    list_definition_id: int,
    list_entry_id: int,
    tenant_id: int,
    value_source: str | None,
    protocol: Protocol,
    cache: ListSnapshotCache | None = None,
) -> dict[str, Any]:
    """compute_row_list_snapshot, plus the "historische Daten verwenden" row option (see
    the template row editor's row_config.value_source): when value_source == "historical",
    first tries to resolve the row from the table_snapshot of the cycle *this protocol
    itself* falls into (resolve_protocol_cycle) - "the value as of the cycle this
    protocol happened in", not always today's live value. Falls back to the live
    compute_row_list_snapshot result whenever historical resolution isn't possible (no
    row_config.value_source set, the protocol's template has no cycle_config, or that
    cycle has no snapshot yet - e.g. it's still the active cycle, or a gap that hasn't
    been reconstructed) - historical accuracy degrades gracefully to "best available
    live data", never a hard error or blank value."""
    if value_source == "historical":
        resolved = resolve_protocol_cycle(db, protocol)
        if resolved is not None:
            cycle_config, cycle_year = resolved
            historical = _compute_row_list_snapshot_from_table_snapshot(
                db,
                tenant_id=tenant_id,
                cycle_config_id=cycle_config.id,
                cycle_year=cycle_year,
                list_definition_id=list_definition_id,
                list_entry_id=list_entry_id,
                cache=cache,
            )
            if historical is not None:
                return historical
    return compute_row_list_snapshot(db, list_definition_id, list_entry_id, tenant_id, cache=cache)


def _protocol_blocks(db: Session, protocol_id: int) -> list[ProtocolElementBlock]:
    return list(
        db.scalars(
            select(ProtocolElementBlock)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .where(ProtocolElement.protocol_id == protocol_id)
        )
    )


def _row_list_ids(config: dict) -> list[int]:
    rows = config.get("rows")
    if not isinstance(rows, list):
        return []
    ids = []
    for row in rows:
        if isinstance(row, dict) and row.get("linked_list_id"):
            ids.append(int(row["linked_list_id"]))
    return ids


def referenced_list_definition_ids(db: Session, protocol_id: int) -> set[int]:
    """All list_definition_ids this protocol's blocks are linked to (whole-list
    `linked_list_id` or any row-link `rows[].linked_list_id`). Used to subscribe a
    protocol's WebSocket connection to every relevant hocx:list:{id}:events channel.
    Mirrors the linkedListIds collection in frontend/app/protocols/[id]/page.tsx -
    keep both in sync if the list-linkage JSON shape ever changes."""
    ids: set[int] = set()
    for block in _protocol_blocks(db, protocol_id):
        config = block.configuration_snapshot_json or {}
        if config.get("linked_list_id"):
            ids.add(int(config["linked_list_id"]))
        ids.update(_row_list_ids(config))
    return ids


def list_linked_blocks_for_protocol(db: Session, protocol_id: int) -> list[ProtocolElementBlock]:
    """Every block that owns a whole-list link or at least one list_entry row - the set
    that refresh-all operations (finalize-freeze, backfill) need to walk."""
    result = []
    for block in _protocol_blocks(db, protocol_id):
        config = block.configuration_snapshot_json or {}
        if config.get("linked_list_id") or _row_list_ids(config):
            result.append(block)
    return result


def _merge_tracked_list_entries(
    new_entries: list[dict[str, Any]], old_entries: Any, *, track_changes_active: bool
) -> list[dict[str, Any]]:
    """Diff-merges freshly-fetched whole-list entries against the entries as they were on
    the block's own last-stored snapshot, tagging each with a sticky '_tracked' marker
    ('added'/'changed'/'removed') for the track-changes feature. Once an entry is marked
    'added' or 'changed', that marker (and its pinned '_tracked_before') is carried forward
    unconditionally on every later call, regardless of track_changes_active, so toggling
    tracking off never erases history - only tracking new changes stops. An 'added' entry
    that disappears again just vanishes (it never existed in accepted history, mirrors how
    a todo created-then-deleted while tracked hard-deletes with no phantom); a 'changed' or
    previously-untracked entry that disappears is re-injected using its last-known values,
    tagged 'removed', and keeps being carried forward until the whole protocol's tracked
    changes are cleared (see clear_tracked_changes_for_protocol)."""
    old_by_id = {e["id"]: e for e in (old_entries or []) if isinstance(e, dict)}
    new_ids = {e["id"] for e in new_entries}
    merged: list[dict[str, Any]] = []
    for entry in new_entries:
        entry = dict(entry)
        old = old_by_id.get(entry["id"])
        if old is not None and old.get("_tracked") in ("added", "changed"):
            entry["_tracked"] = old["_tracked"]
            if "_tracked_before" in old:
                entry["_tracked_before"] = old["_tracked_before"]
        elif track_changes_active:
            if old is None:
                entry["_tracked"] = "added"
            elif entry.get("column_one_value") != old.get("column_one_value") or entry.get("column_two_value") != old.get("column_two_value"):
                entry["_tracked"] = "changed"
                entry["_tracked_before"] = {
                    "column_one_value": old.get("column_one_value"),
                    "column_two_value": old.get("column_two_value"),
                }
        merged.append(entry)
    for old_id, old in old_by_id.items():
        if old_id in new_ids:
            continue
        previous_marker = old.get("_tracked")
        if previous_marker == "removed":
            merged.append(dict(old))
            continue
        if previous_marker == "added":
            continue
        if track_changes_active or previous_marker == "changed":
            phantom = {k: v for k, v in old.items() if k not in ("_tracked", "_tracked_before")}
            phantom["_tracked"] = "removed"
            if previous_marker == "changed" and "_tracked_before" in old:
                phantom["_tracked_before"] = old["_tracked_before"]
            merged.append(phantom)
    return merged


def _merge_tracked_row_snapshot(new_snapshot: dict[str, Any], old_snapshot: Any, *, track_changes_active: bool) -> dict[str, Any]:
    """Same idea as _merge_tracked_list_entries but for a single row-link entry (no id
    array to diff - just one before/current pair)."""
    if not isinstance(old_snapshot, dict):
        return new_snapshot
    old_marker = old_snapshot.get("_tracked")
    if old_marker == "removed":
        return dict(old_snapshot)
    if old_marker == "changed":
        if new_snapshot.get("entry_exists"):
            merged = dict(new_snapshot)
            merged["_tracked"] = "changed"
            merged["_tracked_before"] = old_snapshot.get("_tracked_before")
            return merged
        phantom = {k: v for k, v in old_snapshot.items() if k != "_tracked"}
        phantom["_tracked"] = "removed"
        return phantom
    if not old_snapshot.get("entry_exists"):
        return new_snapshot
    if not new_snapshot.get("entry_exists"):
        if track_changes_active:
            phantom = dict(old_snapshot)
            phantom["_tracked"] = "removed"
            return phantom
        return new_snapshot
    if track_changes_active and (
        new_snapshot.get("column_one_value") != old_snapshot.get("column_one_value")
        or new_snapshot.get("column_two_value") != old_snapshot.get("column_two_value")
    ):
        merged = dict(new_snapshot)
        merged["_tracked"] = "changed"
        merged["_tracked_before"] = {
            "column_one_value": old_snapshot.get("column_one_value"),
            "column_two_value": old_snapshot.get("column_two_value"),
        }
        return merged
    return new_snapshot


def tag_initial_list_entries(new_entries: list[dict[str, Any]], old_entries: Any, *, track_changes_active: bool) -> list[dict[str, Any]]:
    """Public entry point for _merge_tracked_list_entries, used by
    ProtocolService.create_from_template to pre-tag a freshly-created whole-list
    block's entries against the last abgeschlossen protocol's frozen entries
    (rather than leaving it untagged until the first later edit/refresh) - so a
    new protocol shows changes since the last completed meeting immediately."""
    return _merge_tracked_list_entries(new_entries, old_entries, track_changes_active=track_changes_active)


def tag_initial_row_snapshot(new_snapshot: dict[str, Any], old_snapshot: Any, *, track_changes_active: bool) -> dict[str, Any]:
    """Row-link counterpart to tag_initial_list_entries - see its docstring."""
    return _merge_tracked_row_snapshot(new_snapshot, old_snapshot, track_changes_active=track_changes_active)


def _carry_or_stash_previous(new_snapshot: dict, old_snapshot: Any, *, keep_undo: bool) -> None:
    """Mutates new_snapshot in place to set its 'previous' key. keep_undo=True (explicit
    manual refresh): stash the old snapshot's own current values as the one undo step -
    never nests (the old snapshot's own 'previous', if any, is dropped, so undo is always
    exactly one level deep). keep_undo=False (silent self-write sync): never touch an
    existing 'previous' at all, so a manual refresh's undo point survives any amount of
    further self-editing."""
    if keep_undo:
        if isinstance(old_snapshot, dict):
            new_snapshot["previous"] = {k: v for k, v in old_snapshot.items() if k != "previous"}
    elif isinstance(old_snapshot, dict) and old_snapshot.get("previous") is not None:
        new_snapshot["previous"] = old_snapshot["previous"]


def refresh_block_list_snapshot(
    db: Session,
    block: ProtocolElementBlock,
    tenant_id: int,
    *,
    keep_undo: bool,
    protocol: Protocol,
    track_changes_active: bool = False,
    commit: bool = True,
    cache: ListSnapshotCache | None = None,
) -> ProtocolElementBlock:
    """Recomputes list_snapshot (whole-list) and/or every row's list_snapshot (row-link)
    from current live data (or, for a row with row_config.value_source == "historical",
    from this protocol's own cycle's table_snapshot - see
    compute_row_list_snapshot_for_protocol) and writes it back onto the block. When
    track_changes_active, also diff-merges against the entries this same call is about
    to overwrite so added/changed/removed rows get a sticky '_tracked' marker for the
    track-changes feature (see _merge_tracked_list_entries/_merge_tracked_row_snapshot)
    - this is completely independent of the 'previous'/undo mechanism above."""
    config = dict(block.configuration_snapshot_json or {})
    changed = False

    linked_list_id = config.get("linked_list_id")
    if linked_list_id:
        new_snapshot = compute_whole_list_snapshot(db, int(linked_list_id), tenant_id, cache=cache)
        if new_snapshot is not None:
            old_list_snapshot = config.get("list_snapshot")
            new_snapshot["entries"] = _merge_tracked_list_entries(
                new_snapshot["entries"],
                old_list_snapshot.get("entries") if isinstance(old_list_snapshot, dict) else None,
                track_changes_active=track_changes_active,
            )
            _carry_or_stash_previous(new_snapshot, old_list_snapshot, keep_undo=keep_undo)
            config["list_snapshot"] = new_snapshot
            changed = True
        else:
            # Source list itself was deleted - mirror compute_row_list_snapshot's
            # entry_exists=False marker for the same case (see its docstring) instead of
            # silently leaving the stale old snapshot in place forever.
            deleted_marker = {"synced_version": 0, "entry_exists": False}
            if config.get("list_snapshot") != deleted_marker:
                config["list_snapshot"] = deleted_marker
                changed = True

    rows = config.get("rows")
    if isinstance(rows, list):
        new_rows = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("linked_list_id"):
                new_rows.append(row)
                continue
            row = dict(row)
            new_snapshot = compute_row_list_snapshot_for_protocol(
                db,
                list_definition_id=int(row["linked_list_id"]),
                list_entry_id=int(row.get("linked_list_entry_id") or 0),
                tenant_id=tenant_id,
                value_source=row.get("value_source"),
                protocol=protocol,
                cache=cache
            )
            new_snapshot = _merge_tracked_row_snapshot(
                new_snapshot, row.get("list_snapshot"), track_changes_active=track_changes_active
            )
            _carry_or_stash_previous(new_snapshot, row.get("list_snapshot"), keep_undo=keep_undo)
            row["list_snapshot"] = new_snapshot
            new_rows.append(row)
            changed = True
        if changed:
            config["rows"] = new_rows

    if changed:
        block.configuration_snapshot_json = config
        db.add(block)
        if commit:
            db.commit()
            db.refresh(block)
        else:
            db.flush()
    return block


def accept_tracked_list_entry(db: Session, block: ProtocolElementBlock, entry_id: int) -> ProtocolElementBlock:
    """'Ausblenden' for one whole-list entry's tracked-change highlight: strips its
    '_tracked'/'_tracked_before' markers so it renders as plain data again, independent
    of the protocol-wide clear that otherwise only happens at vorbereitet ->
    durchgefuehrt (clear_tracked_changes_for_protocol). A 'removed' phantom is dropped
    entirely now, finalizing its removal early."""
    config = dict(block.configuration_snapshot_json or {})
    list_snapshot = config.get("list_snapshot")
    entries = list_snapshot.get("entries") if isinstance(list_snapshot, dict) else None
    if not isinstance(entries, list):
        return block
    new_entries = []
    changed = False
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") != entry_id or not entry.get("_tracked"):
            new_entries.append(entry)
            continue
        changed = True
        if entry.get("_tracked") == "removed":
            continue
        new_entries.append({k: v for k, v in entry.items() if k not in ("_tracked", "_tracked_before")})
    if not changed:
        return block
    config["list_snapshot"] = {**list_snapshot, "entries": new_entries}
    block.configuration_snapshot_json = config
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def accept_tracked_row(db: Session, block: ProtocolElementBlock, row_id: str) -> ProtocolElementBlock:
    """Row-link ('Zeile aus Liste') counterpart to accept_tracked_list_entry - see its
    docstring. row_id is the form row's own id (compared as a string since it may be
    stored as either an int or a string in configuration_snapshot_json), not the linked
    list entry's id."""
    config = dict(block.configuration_snapshot_json or {})
    rows = config.get("rows")
    if not isinstance(rows, list):
        return block
    new_rows = []
    changed = False
    for row in rows:
        if not isinstance(row, dict) or str(row.get("id")) != row_id:
            new_rows.append(row)
            continue
        row_snapshot = row.get("list_snapshot")
        if isinstance(row_snapshot, dict) and row_snapshot.get("_tracked"):
            changed = True
            row = dict(row)
            row["list_snapshot"] = {k: v for k, v in row_snapshot.items() if k not in ("_tracked", "_tracked_before")}
        new_rows.append(row)
    if not changed:
        return block
    config["rows"] = new_rows
    block.configuration_snapshot_json = config
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def undo_block_list_snapshot(db: Session, block: ProtocolElementBlock) -> ProtocolElementBlock | None:
    """Restores whichever list_snapshot(s) on this block have a 'previous' back into the
    current position and clears 'previous'. Returns None if there's nothing to undo (route
    should respond 409). Never touches the shared list itself - purely local to this block."""
    config = dict(block.configuration_snapshot_json or {})
    changed = False

    list_snapshot = config.get("list_snapshot")
    if isinstance(list_snapshot, dict) and list_snapshot.get("previous") is not None:
        config["list_snapshot"] = list_snapshot["previous"]
        changed = True

    rows = config.get("rows")
    if isinstance(rows, list):
        new_rows = list(rows)
        for i, row in enumerate(new_rows):
            if isinstance(row, dict) and isinstance(row.get("list_snapshot"), dict) and row["list_snapshot"].get("previous") is not None:
                row = dict(row)
                row["list_snapshot"] = row["list_snapshot"]["previous"]
                new_rows[i] = row
                changed = True
        if changed:
            config["rows"] = new_rows

    if not changed:
        return None
    block.configuration_snapshot_json = config
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def clear_tracked_changes_for_protocol(db: Session, protocol_id: int, *, commit: bool = True) -> None:
    """Called once at vorbereitet -> durchgefuehrt: strips every '_tracked'/'_tracked_before'
    marker and drops every '_tracked: removed' phantom entry from every list-linked block's
    list_snapshot, permanently - mirrors freeze_list_snapshots_for_protocol's shape. Never
    touches 'previous' (an unrelated, pre-existing undo mechanism)."""

    def _strip(snapshot: Any) -> tuple[Any, bool]:
        if not isinstance(snapshot, dict):
            return snapshot, False
        stripped_any = False
        result = dict(snapshot)
        if "entries" in result and isinstance(result["entries"], list):
            new_entries = []
            for entry in result["entries"]:
                if not isinstance(entry, dict):
                    new_entries.append(entry)
                    continue
                if entry.get("_tracked") == "removed":
                    stripped_any = True
                    continue
                if "_tracked" in entry or "_tracked_before" in entry:
                    entry = {k: v for k, v in entry.items() if k not in ("_tracked", "_tracked_before")}
                    stripped_any = True
                new_entries.append(entry)
            if stripped_any:
                result["entries"] = new_entries
        elif "_tracked" in result or "_tracked_before" in result:
            result = {k: v for k, v in result.items() if k not in ("_tracked", "_tracked_before")}
            stripped_any = True
        return result, stripped_any

    for block in list_linked_blocks_for_protocol(db, protocol_id):
        config = dict(block.configuration_snapshot_json or {})
        changed = False

        list_snapshot, stripped = _strip(config.get("list_snapshot"))
        if stripped:
            config["list_snapshot"] = list_snapshot
            changed = True

        rows = config.get("rows")
        if isinstance(rows, list):
            new_rows = list(rows)
            for i, row in enumerate(new_rows):
                if not isinstance(row, dict):
                    continue
                row_snapshot, row_stripped = _strip(row.get("list_snapshot"))
                if row_stripped:
                    row = dict(row)
                    row["list_snapshot"] = row_snapshot
                    new_rows[i] = row
                    changed = True
            if changed:
                config["rows"] = new_rows

        if changed:
            block.configuration_snapshot_json = config
            db.add(block)
    if commit:
        db.commit()
    else:
        db.flush()


def freeze_list_snapshots_for_protocol(db: Session, protocol_id: int, tenant_id: int, *, commit: bool = True) -> None:
    """Called once at durchgefuehrt -> abgeschlossen (mirrors _freeze_responsible_titles):
    resolve every list-linked block one last time and drop any leftover undo point, since
    abgeschlossen protocols are permanently read-only and never show the refresh/undo UI
    again."""
    cache = ListSnapshotCache()
    protocol = db.get(Protocol, protocol_id)
    for block in list_linked_blocks_for_protocol(db, protocol_id):
        refresh_block_list_snapshot(db, block, tenant_id, keep_undo=False, protocol=protocol, commit=commit, cache=cache)
        config = dict(block.configuration_snapshot_json or {})
        changed = False
        list_snapshot = config.get("list_snapshot")
        if isinstance(list_snapshot, dict) and list_snapshot.get("previous") is not None:
            config["list_snapshot"] = {k: v for k, v in list_snapshot.items() if k != "previous"}
            changed = True
        rows = config.get("rows")
        if isinstance(rows, list):
            new_rows = list(rows)
            for i, row in enumerate(new_rows):
                if isinstance(row, dict) and isinstance(row.get("list_snapshot"), dict) and row["list_snapshot"].get("previous") is not None:
                    row = dict(row)
                    row["list_snapshot"] = {k: v for k, v in row["list_snapshot"].items() if k != "previous"}
                    new_rows[i] = row
                    changed = True
            if changed:
                config["rows"] = new_rows
        if changed:
            block.configuration_snapshot_json = config
            db.add(block)
            if commit:
                db.commit()
                db.refresh(block)
            else:
                db.flush()
