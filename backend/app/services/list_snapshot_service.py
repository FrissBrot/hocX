"""Snapshotting of structured-list data referenced by protocol blocks (both the
whole-list "Gekoppelte Liste" Tabellenblock mode and the single-row "Zeile aus Liste"
mode), so a protocol shows a frozen view of list data with an explicit, undoable
"Daten aktualisieren" refresh instead of always reading the shared list live.

Mirrors the module-level-function style and "live until abgeschlossen" precedent of
responsible_label_service.py.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ListDefinition, ListEntry, ProtocolElement, ProtocolElementBlock


def compute_whole_list_snapshot(db: Session, list_definition_id: int) -> dict[str, Any] | None:
    """Full frozen view of a list for the "Gekoppelte Liste" whole-list mode, or None if
    the list itself was deleted."""
    definition = db.get(ListDefinition, list_definition_id)
    if definition is None:
        return None
    entries = list(
        db.scalars(
            select(ListEntry)
            .where(ListEntry.list_definition_id == list_definition_id)
            .order_by(ListEntry.sort_index.asc(), ListEntry.id.asc())
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


def compute_row_list_snapshot(db: Session, list_definition_id: int, list_entry_id: int) -> dict[str, Any]:
    """Frozen view of one list entry for a "Zeile aus Liste" row. Stores both raw column
    values (not just the row's own fixed/variable split) so which column is "fixed" can
    still change without needing to recompute. entry_exists=False means the entry (or the
    whole list) was deleted since the last sync - callers show the existing "Verknuepfter
    Listeneintrag wurde geloescht" message in that case."""
    definition = db.get(ListDefinition, list_definition_id)
    if definition is None:
        return {"synced_version": 0, "entry_exists": False}
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


def refresh_block_list_snapshot(db: Session, block: ProtocolElementBlock, *, keep_undo: bool) -> ProtocolElementBlock:
    """Recomputes list_snapshot (whole-list) and/or every row's list_snapshot (row-link)
    from current live data and writes it back onto the block."""
    config = dict(block.configuration_snapshot_json or {})
    changed = False

    linked_list_id = config.get("linked_list_id")
    if linked_list_id:
        new_snapshot = compute_whole_list_snapshot(db, int(linked_list_id))
        if new_snapshot is not None:
            _carry_or_stash_previous(new_snapshot, config.get("list_snapshot"), keep_undo=keep_undo)
            config["list_snapshot"] = new_snapshot
            changed = True

    rows = config.get("rows")
    if isinstance(rows, list):
        new_rows = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("linked_list_id"):
                new_rows.append(row)
                continue
            row = dict(row)
            new_snapshot = compute_row_list_snapshot(
                db, int(row["linked_list_id"]), int(row.get("linked_list_entry_id") or 0)
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


def freeze_list_snapshots_for_protocol(db: Session, protocol_id: int) -> None:
    """Called once at durchgefuehrt -> abgeschlossen (mirrors _freeze_responsible_titles):
    resolve every list-linked block one last time and drop any leftover undo point, since
    abgeschlossen protocols are permanently read-only and never show the refresh/undo UI
    again."""
    for block in list_linked_blocks_for_protocol(db, protocol_id):
        refresh_block_list_snapshot(db, block, keep_undo=False)
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
            db.commit()
            db.refresh(block)
