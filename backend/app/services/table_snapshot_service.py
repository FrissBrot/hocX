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

from datetime import date
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.core.cycle_utils import get_cycle_year
from app.models.entities import CycleConfig, TableSnapshot
from app.services.table_snapshot_config import SNAPSHOT_TABLES, TRANSITIVE_SNAPSHOT_SCOPE
from app.services.tenant_transfer_common import row_to_dict


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


def run_due_cycle_snapshots(db: Session, service: TableSnapshotService) -> None:
    """Daily-loop entry point (see main.py's cycle_snapshot_loop): for every
    CycleConfig, snapshots the most recently *completed* cycle (current_cycle_year - 1)
    if any table in SNAPSHOT_TABLES is missing a snapshot for it yet. Whether a table
    already has one is checked directly against table_snapshot rather than tracked in a
    separate marker column/table, so this both is idempotent and self-heals a missed
    check day - as long as the gap wasn't longer than one full cycle, since this only
    ever looks one cycle back. There is no manual catch-up trigger for a longer gap (this
    is a historical-record feature, not a backup tool) - the cycle would simply stay
    unsnapshotted until the next boundary.

    Checked per-table, not just "does this cycle have any snapshot at all": otherwise a
    table added to SNAPSHOT_TABLES after a cycle was already (even partially) snapshotted
    would never get backfilled automatically - the loop would see the cycle as "done"
    from its first snapshotted table onward and skip it forever. create_snapshot()
    itself already skips any table that already has a snapshot, so calling it again here
    only ever fills in what's missing - it never touches an admin's historical edits on
    an already-snapshotted table.
    """
    today = date.today()
    for cycle_config in db.scalars(select(CycleConfig)):
        current_cycle_year = get_cycle_year(today, cycle_config.reset_month, cycle_config.reset_day)
        just_ended_cycle_year = current_cycle_year - 1
        existing_tables = set(
            db.scalars(
                select(TableSnapshot.table_name).where(
                    TableSnapshot.cycle_config_id == cycle_config.id,
                    TableSnapshot.cycle_year == just_ended_cycle_year,
                )
            )
        )
        if existing_tables >= SNAPSHOT_TABLES.keys():
            continue
        service.create_snapshot(
            db,
            tenant_id=cycle_config.tenant_id,
            cycle_config=cycle_config,
            cycle_year=just_ended_cycle_year,
        )


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
