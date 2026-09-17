"""Creates and serves cycle-boundary snapshots of the tables listed in
table_snapshot_config.SNAPSHOT_TABLES - see the cycle-snapshot feature plan for the
overall design (table_snapshot is a JSONB blob per table/cycle, not a parallel shadow
schema; editing a historical snapshot overwrites it in place, gated behind an explicit
confirm flag at the API layer).

Snapshots are only ever created by the daily background loop (main.py's
cycle_snapshot_loop) at a cycle boundary - there is deliberately no manual/on-demand
trigger. This is a historical-record feature, not a backup/restore tool.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Callable

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.core.cycle_utils import get_cycle_year
from app.models.entities import CycleConfig, ListDefinition, ListEntry, TableSnapshot
from app.services.table_snapshot_config import SNAPSHOT_TABLES, TRANSITIVE_SNAPSHOT_SCOPE
from app.services.tenant_transfer_common import row_to_dict

# How many cycles run_due_cycle_snapshots will walk backward in one tick to catch up a
# CycleConfig that's behind by more than one cycle - see that function's docstring. A
# snapshot always captures whatever the live tables look like *today*, not a true
# point-in-time record (there is no other source of historical data to draw from), so
# this is already an approximation even for the single most-recently-ended cycle; kept
# deliberately small (rather than large/unbounded) so a brand-new CycleConfig created for
# a tenant with years of pre-existing list data doesn't flood the cycle picker with many
# identical "historical" snapshots that are all really just today's data relabeled - 3
# missed boundaries in a row is already a serious, rare operational outage (this
# module's background loop runs daily), which is the actual scenario this catches up.
MAX_CYCLE_SNAPSHOT_CATCH_UP = 3


class ReconstructionIdentityError(ValueError):
    """Raised when a reconstruction payload references a row (by public_id) that can't
    be resolved to any known identity - neither a live row nor a row already captured
    in some existing snapshot for this cycle_config. Reconstruction can only edit or
    drop rows that already exist somewhere; it can never fabricate a brand new one."""


def _resolve_tenant_scoped_id_query(model: type, tenant_id: int) -> Select:
    """Returns a `select(model.id)` scoped to tenant_id - directly if the model has its
    own tenant_id column, otherwise by walking TRANSITIVE_SNAPSHOT_SCOPE recursively up
    to a directly tenant_id-scoped ancestor. This is the same resolution
    TableSnapshotService.create_snapshot uses for the target table itself, applied here
    to an intermediate parent - today that's just list_entry's single hop up to
    list_definition, but it recurses so a future multi-level chain (a table scoped via a
    parent that is itself only transitively scoped) needs no code change here, only a
    new TRANSITIVE_SNAPSHOT_SCOPE entry."""
    if hasattr(model, "tenant_id"):
        return select(model.id).where(model.tenant_id == tenant_id)
    parent_model, fk_column_name = TRANSITIVE_SNAPSHOT_SCOPE[model.__tablename__]
    parent_ids = _resolve_tenant_scoped_id_query(parent_model, tenant_id)
    fk_column = getattr(model, fk_column_name)
    return select(model.id).where(fk_column.in_(parent_ids))


class TableSnapshotService:
    def create_snapshot(
        self,
        db: Session,
        *,
        tenant_id: int,
        cycle_config: CycleConfig,
        cycle_year: int,
    ) -> list[TableSnapshot]:
        """Writes one TableSnapshot row per table in SNAPSHOT_TABLES, scoped to
        tenant_id. Commits once at the end, so a snapshot is all-or-nothing per cycle -
        callers never see a partially-written historical view.

        Skips any table that already has a snapshot for this (tenant, cycle_config,
        cycle_year) - this is what makes run_due_cycle_snapshots idempotent and keeps it
        from ever clobbering a historical edit already made to that table. There is no
        force/overwrite path: a table_snapshot row, once written, is only ever changed
        again through the guarded historical-edit API (see table_snapshots routes), not
        by re-running this.

        A model with its own tenant_id column is fetched with a plain
        `WHERE tenant_id = ...`. A table that is only transitively tenant-scoped (via a
        parent FK - today just list_entry through list_definition) is listed in
        TRANSITIVE_SNAPSHOT_SCOPE instead and fetched via _resolve_tenant_scoped_id_query,
        which walks that chain recursively - see that function's docstring.
        """
        existing_by_table = {
            row.table_name: row
            for row in db.scalars(
                select(TableSnapshot).where(
                    TableSnapshot.tenant_id == tenant_id,
                    TableSnapshot.cycle_config_id == cycle_config.id,
                    TableSnapshot.cycle_year == cycle_year,
                )
            )
        }

        written: list[TableSnapshot] = []
        for table_name, model in SNAPSHOT_TABLES.items():
            existing = existing_by_table.get(table_name)
            if existing is not None:
                written.append(existing)
                continue

            transitive_scope = TRANSITIVE_SNAPSHOT_SCOPE.get(table_name)
            if transitive_scope is not None:
                parent_model, fk_column_name = transitive_scope
                parent_ids = _resolve_tenant_scoped_id_query(parent_model, tenant_id)
                fk_column = getattr(model, fk_column_name)
                query = select(model).where(fk_column.in_(parent_ids))
            else:
                query = select(model).where(model.tenant_id == tenant_id)
            # Order by whatever the model's actual primary key columns are rather than
            # assuming a single `.id` - both list_definition/list_entry have a plain
            # `id`, but a future table with a composite primary key (no single `id`
            # column) would otherwise crash here.
            pk_columns = sa_inspect(model).primary_key
            if pk_columns:
                query = query.order_by(*pk_columns)
            rows = db.scalars(query).all()
            payload: list[dict[str, Any]] = [row_to_dict(row) for row in rows]

            snapshot = TableSnapshot(
                tenant_id=tenant_id,
                cycle_config_id=cycle_config.id,
                cycle_year=cycle_year,
                table_name=table_name,
                snapshot_json=payload,
                row_count=len(payload),
            )
            db.add(snapshot)
            db.flush()
            written.append(snapshot)

        db.commit()
        return written

    def reconstruct_list_period(
        self,
        db: Session,
        *,
        tenant_id: int,
        cycle_config: CycleConfig,
        cycle_year: int,
        list_public_id: str,
        definition_values: dict[str, Any],
        entry_payloads: list[dict[str, Any]],
        edited_by: int,
    ) -> None:
        """Fills a genuine snapshot gap for one list in one period. The caller (the
        reconstruct route) already pre-filled definition_values/entry_payloads from the
        nearest available source (an existing snapshot or the live list) and let a human
        review/edit them - this just resolves each row's real identity (never trusting
        client-supplied ids) and writes it into the period's table_snapshot rows.

        Every identity is re-resolved from a live row or an existing snapshot, so a
        reconstructed row always carries the same id/public_id it has everywhere else in
        the system - see _resolve_list_definition_identity/_resolve_list_entry_identities_batch.
        Raises ReconstructionIdentityError if the list or any entry can't be resolved:
        reconstruction can only edit or drop already-known rows, never fabricate one.
        """
        definition_identity = _resolve_list_definition_identity(
            db, public_id=list_public_id, tenant_id=tenant_id, cycle_config_id=cycle_config.id
        )
        if definition_identity is None:
            raise ReconstructionIdentityError(f"Unknown list {list_public_id}")
        list_internal_id = definition_identity["id"]

        definition_row = {**definition_identity, "tenant_id": tenant_id, **definition_values}

        entry_identities = _resolve_list_entry_identities_batch(
            db,
            public_ids=[payload.get("public_id") for payload in entry_payloads if payload.get("public_id")],
            list_definition_internal_id=list_internal_id,
            cycle_config_id=cycle_config.id,
            tenant_id=tenant_id,
        )
        entry_rows: list[dict[str, Any]] = []
        for payload in entry_payloads:
            entry_public_id = payload.get("public_id")
            entry_identity = entry_identities.get(entry_public_id) if entry_public_id else None
            if entry_identity is None:
                raise ReconstructionIdentityError(f"Unknown list entry {entry_public_id}")
            entry_rows.append({
                **entry_identity,
                "list_definition_id": list_internal_id,
                "sort_index": payload.get("sort_index", 0),
                "column_one_value_json": payload.get("column_one_value_json", {}),
                "column_two_value_json": payload.get("column_two_value_json", {}),
            })

        now = datetime.now(UTC)
        _upsert_snapshot_rows(
            db, tenant_id=tenant_id, cycle_config_id=cycle_config.id, cycle_year=cycle_year,
            table_name="list_definition",
            keep=lambda row: row.get("id") != list_internal_id,
            new_rows=[definition_row], edited_by=edited_by, edited_at=now,
        )
        _upsert_snapshot_rows(
            db, tenant_id=tenant_id, cycle_config_id=cycle_config.id, cycle_year=cycle_year,
            table_name="list_entry",
            keep=lambda row: row.get("list_definition_id") != list_internal_id,
            new_rows=entry_rows, edited_by=edited_by, edited_at=now,
        )
        db.commit()


def build_reconstruction_draft(
    db: Session,
    *,
    tenant_id: int,
    cycle_config: CycleConfig,
    cycle_year: int,
    list_public_id: str,
) -> dict[str, Any] | None:
    """Finds the nearest available source for `list_public_id`'s data - the live list,
    or any existing complete snapshot for this cycle_config - ranked by distance
    (|source_cycle_year - cycle_year|, with live ranked by |current_cycle_year -
    cycle_year|) and returns a pre-filled draft the frontend presents as an editable
    starting point for reconstructing this list in `cycle_year`. Tries candidates in
    distance order and skips any that don't actually contain this list (e.g. the
    nearest snapshot predates the list's creation) - returns the first real match.
    None if no source has this list at all (unknown list - reconstruction can't
    fabricate one with no prior existence anywhere)."""
    today = date.today()
    current_cycle_year = get_cycle_year(today, cycle_config.reset_month, cycle_config.reset_day)

    existing_years = sorted({
        row.cycle_year
        for row in db.scalars(
            select(TableSnapshot).where(
                TableSnapshot.tenant_id == tenant_id,
                TableSnapshot.cycle_config_id == cycle_config.id,
                TableSnapshot.table_name == "list_definition",
            )
        )
    })
    candidates: list[tuple[int, str, int | None]] = [(abs(current_cycle_year - cycle_year), "live", None)]
    candidates += [(abs(year - cycle_year), "snapshot", year) for year in existing_years]
    candidates.sort(key=lambda c: c[0])

    for _, source, source_cycle_year in candidates:
        if source == "live":
            draft = _draft_from_live(db, tenant_id=tenant_id, list_public_id=list_public_id)
        else:
            draft = _draft_from_snapshot(
                db, tenant_id=tenant_id, cycle_config_id=cycle_config.id,
                source_cycle_year=source_cycle_year, list_public_id=list_public_id,
            )
        if draft is not None:
            return {"source": source, "source_cycle_year": source_cycle_year, **draft}
    return None


def _draft_from_live(db: Session, *, tenant_id: int, list_public_id: str) -> dict[str, Any] | None:
    live_def = db.scalar(select(ListDefinition).where(ListDefinition.public_id == list_public_id, ListDefinition.tenant_id == tenant_id))
    if live_def is None:
        return None
    definition_values = {
        "name": live_def.name,
        "description": live_def.description,
        "column_one_title": live_def.column_one_title,
        "column_one_value_type": live_def.column_one_value_type,
        "column_two_title": live_def.column_two_title,
        "column_two_value_type": live_def.column_two_value_type,
        "is_active": live_def.is_active,
    }
    live_entries = db.scalars(
        select(ListEntry).where(ListEntry.list_definition_id == live_def.id).order_by(ListEntry.sort_index)
    ).all()
    entries = [
        {
            "public_id": str(entry.public_id),
            "sort_index": entry.sort_index,
            "column_one_value_json": entry.column_one_value_json,
            "column_two_value_json": entry.column_two_value_json,
        }
        for entry in live_entries
    ]
    return {"definition_values": definition_values, "entries": entries}


def _draft_from_snapshot(
    db: Session, *, tenant_id: int, cycle_config_id: int, source_cycle_year: int, list_public_id: str
) -> dict[str, Any] | None:
    def_snapshot = db.scalar(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.cycle_year == source_cycle_year,
            TableSnapshot.table_name == "list_definition",
        )
    )
    def_row = next((r for r in (def_snapshot.snapshot_json if def_snapshot else []) if r.get("public_id") == list_public_id), None)
    if def_row is None:
        return None
    definition_values = {
        "name": def_row.get("name"),
        "description": def_row.get("description"),
        "column_one_title": def_row.get("column_one_title"),
        "column_one_value_type": def_row.get("column_one_value_type"),
        "column_two_title": def_row.get("column_two_title"),
        "column_two_value_type": def_row.get("column_two_value_type"),
        "is_active": def_row.get("is_active"),
    }
    entry_snapshot = db.scalar(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.cycle_year == source_cycle_year,
            TableSnapshot.table_name == "list_entry",
        )
    )
    entries = [
        {
            "public_id": r.get("public_id"),
            "sort_index": r.get("sort_index", 0),
            "column_one_value_json": r.get("column_one_value_json", {}),
            "column_two_value_json": r.get("column_two_value_json", {}),
        }
        for r in (entry_snapshot.snapshot_json if entry_snapshot else [])
        if r.get("list_definition_id") == def_row.get("id")
    ]
    return {"definition_values": definition_values, "entries": entries}


def _resolve_list_definition_identity(
    db: Session, *, public_id: str, tenant_id: int, cycle_config_id: int
) -> dict[str, Any] | None:
    """Resolves {id, public_id, created_at, updated_at} for a list_definition addressed
    by public_id - the live row if it still exists (tenant-scoped), otherwise any
    existing table_snapshot("list_definition") row for this cycle_config that already
    captured it. None if neither source has it."""
    live = db.scalar(select(ListDefinition).where(ListDefinition.public_id == public_id, ListDefinition.tenant_id == tenant_id))
    if live is not None:
        return {
            "id": live.id,
            "public_id": str(live.public_id),
            "created_at": live.created_at.isoformat(),
            "updated_at": live.updated_at.isoformat(),
        }
    other_snapshots = db.scalars(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.table_name == "list_definition",
        )
    )
    for snap in other_snapshots:
        for row in snap.snapshot_json:
            if row.get("public_id") == public_id:
                return {"id": row["id"], "public_id": row["public_id"], "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}
    return None


def _resolve_list_entry_identities_batch(
    db: Session, *, public_ids: list[str], list_definition_internal_id: int, tenant_id: int, cycle_config_id: int
) -> dict[str, dict[str, Any]]:
    """Batched counterpart to _resolve_list_definition_identity, for every requested
    list_entry at once - scoped to the already-resolved list_definition_internal_id
    (itself tenant-verified), so no separate tenant filter is needed on ListEntry (it has
    no tenant_id column). Returns {public_id: {id, public_id, created_at, updated_at}} for
    every id resolvable via a live row or an existing table_snapshot("list_entry") row for
    this cycle_config; a requested id absent from the result was resolvable in neither.

    Resolves every id in at most one live query plus one full pass over this
    cycle_config's list_entry snapshots, instead of a query and a full snapshot-array
    rescan per entry (audit fix, 2026-09-17: reconstructing a list whose live rows are
    gone - the common case, that's the whole point of reconstruction - used to cost
    O(entries x existing snapshot rows), since the previous per-entry version re-ran both
    the query and the linear scan from scratch for every single entry)."""
    resolved: dict[str, dict[str, Any]] = {}
    remaining = set(public_ids)
    if not remaining:
        return resolved

    live_rows = db.scalars(
        select(ListEntry).where(ListEntry.public_id.in_(remaining), ListEntry.list_definition_id == list_definition_internal_id)
    )
    for entry in live_rows:
        pid = str(entry.public_id)
        resolved[pid] = {
            "id": entry.id, "public_id": pid,
            "created_at": entry.created_at.isoformat(), "updated_at": entry.updated_at.isoformat(),
        }
    remaining -= resolved.keys()
    if not remaining:
        return resolved

    other_snapshots = db.scalars(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.table_name == "list_entry",
        )
    )
    for snap in other_snapshots:
        for row in snap.snapshot_json:
            pid = row.get("public_id")
            if pid in remaining and row.get("list_definition_id") == list_definition_internal_id:
                resolved[pid] = {"id": row["id"], "public_id": row["public_id"], "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}
        remaining -= resolved.keys()
        if not remaining:
            break
    return resolved


def _upsert_snapshot_rows(
    db: Session,
    *,
    tenant_id: int,
    cycle_config_id: int,
    cycle_year: int,
    table_name: str,
    keep: Callable[[dict[str, Any]], bool],
    new_rows: list[dict[str, Any]],
    edited_by: int,
    edited_at: datetime,
) -> None:
    """Get-or-create the (tenant, cycle_config, cycle_year, table_name) snapshot row,
    drop whichever existing entries `keep` rejects (the ones being replaced), append
    new_rows, and flag it as edited. Used by reconstruct_list_period to fold one list's
    reconstructed data into a period's snapshot without disturbing any other list
    already captured there (each call only ever touches rows for the one list it's
    reconstructing)."""
    snapshot = db.scalar(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.cycle_year == cycle_year,
            TableSnapshot.table_name == table_name,
        )
    )
    if snapshot is None:
        snapshot = TableSnapshot(
            tenant_id=tenant_id, cycle_config_id=cycle_config_id, cycle_year=cycle_year,
            table_name=table_name, snapshot_json=[],
        )
        db.add(snapshot)
        db.flush()
    updated_rows = [row for row in snapshot.snapshot_json if keep(row)] + new_rows
    snapshot.snapshot_json = updated_rows
    snapshot.row_count = len(updated_rows)
    snapshot.is_edited = True
    snapshot.edited_at = edited_at
    snapshot.edited_by = edited_by


def run_due_cycle_snapshots(db: Session, service: TableSnapshotService) -> None:
    """Daily-loop entry point (see main.py's cycle_snapshot_loop): for every CycleConfig,
    snapshots the most recently *completed* cycle (current_cycle_year - 1) if any table in
    SNAPSHOT_TABLES is missing a snapshot for it yet - same as always, so a brand-new
    CycleConfig (even one set up for a group that's already run cycles for years before
    adopting this system) still only ever gets that one cycle's worth of snapshots, not a
    pile of extra ones that would all just be today's data relabeled as older years (there
    is no other source of historical data to draw from, so a snapshot dated further back
    than "the cycle that just ended" is already an approximation, not a real record of
    that time).

    If the CycleConfig already has at least one snapshot from some earlier tick, though,
    this additionally walks further backward (bounded by MAX_CYCLE_SNAPSHOT_CATCH_UP,
    stopping at the first cycle that's already fully snapshotted) to self-heal a real
    operational outage spanning more than one cycle boundary - previously this only ever
    looked exactly one cycle back regardless, so once a second boundary passed with the
    loop down, the older missed cycle could never be reached again (audit fix,
    2026-09-17): current_cycle_year - 1 always points at whichever cycle *just* ended,
    never further, so it silently and permanently skipped it.

    Whether a table already has a snapshot for a given cycle is checked directly against
    table_snapshot rather than tracked in a separate marker column/table, so this is both
    idempotent and self-heals a missed check day. Checked per-table, not just "does this
    cycle have any snapshot at all": otherwise a table added to SNAPSHOT_TABLES after a
    cycle was already (even partially) snapshotted would never get backfilled
    automatically - the loop would see the cycle as "done" from its first snapshotted
    table onward and skip it forever. create_snapshot() itself already skips any table
    that already has a snapshot, so calling it again here only ever fills in what's
    missing - it never touches an admin's historical edits on an already-snapshotted
    table.
    """
    today = date.today()
    for cycle_config in db.scalars(select(CycleConfig)):
        current_cycle_year = get_cycle_year(today, cycle_config.reset_month, cycle_config.reset_day)
        candidate_cycle_year = current_cycle_year - 1
        has_prior_snapshot = (
            db.scalar(select(TableSnapshot.id).where(TableSnapshot.cycle_config_id == cycle_config.id).limit(1)) is not None
        )
        max_cycles_this_tick = MAX_CYCLE_SNAPSHOT_CATCH_UP if has_prior_snapshot else 1
        for _ in range(max_cycles_this_tick):
            existing_tables = set(
                db.scalars(
                    select(TableSnapshot.table_name).where(
                        TableSnapshot.cycle_config_id == cycle_config.id,
                        TableSnapshot.cycle_year == candidate_cycle_year,
                    )
                )
            )
            if existing_tables >= SNAPSHOT_TABLES.keys():
                break
            service.create_snapshot(
                db,
                tenant_id=cycle_config.tenant_id,
                cycle_config=cycle_config,
                cycle_year=candidate_cycle_year,
            )
            candidate_cycle_year -= 1


def get_snapshot_row(
    db: Session,
    *,
    tenant_id: int,
    cycle_config_id: int,
    cycle_year: int,
    table_name: str,
    row_public_id: str,
) -> tuple[TableSnapshot, dict[str, Any], int] | None:
    """Looks up one row inside a table_snapshot's snapshot_json by its original
    (unremapped) public_id - every snapshotted table has one, and addressing by
    public_id rather than the raw internal bigint id matches how every other route in
    this codebase exposes row identity to clients (see public_id_service module
    docstring). Returns (snapshot, row_dict, index_in_array) so a caller can mutate
    snapshot_json[index] in place, or None if the snapshot or the row within it doesn't
    exist. Used by the guarded historical-edit/delete API routes; also the natural place
    a future block-reference-resolution feature would call into (see the cycle-snapshot
    feature plan, section 6).

    A table without a public_id column (composite primary key instead) would have every
    row's "public_id" key simply absent, so this returns None for it rather than
    matching by coincidence - not an issue for list_definition/list_entry today, both of
    which have a public_id, but relevant if a junction-style table is ever added here."""
    snapshot = db.scalar(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.cycle_year == cycle_year,
            TableSnapshot.table_name == table_name,
        )
    )
    if snapshot is None:
        return None
    for index, row in enumerate(snapshot.snapshot_json):
        if row.get("public_id") == row_public_id:
            return snapshot, row, index
    return None
