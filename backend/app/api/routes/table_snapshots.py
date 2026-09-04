from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader
from app.models.entities import CycleConfig, TableSnapshot
from app.schemas.table_snapshot import (
    TableSnapshotCycleSummary,
    TableSnapshotRowDelete,
    TableSnapshotRowUpdate,
    TableSnapshotRowsRead,
    TableSnapshotTableSummary,
)
from app.services import public_id_service
from app.services.audit_service import AuditService
from app.services.table_snapshot_config import SNAPSHOT_TABLES
from app.services.table_snapshot_service import get_snapshot_row

router = APIRouter()


def _get_owned_cycle_config(db: Session, cycle_config_id: uuid.UUID, tenant_id: int) -> CycleConfig:
    obj = public_id_service.get_by_public_id(db, CycleConfig, cycle_config_id, tenant_id=tenant_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Cycle config not found")
    return obj


def _require_known_table(table_name: str) -> None:
    if table_name not in SNAPSHOT_TABLES:
        raise HTTPException(status_code=404, detail="Unknown snapshot table")


def _table_summary(row: TableSnapshot) -> TableSnapshotTableSummary:
    return TableSnapshotTableSummary(
        table_name=row.table_name,
        row_count=row.row_count,
        created_at=row.created_at,
        is_edited=row.is_edited,
        edited_at=row.edited_at,
    )


@router.get("/table-snapshots/cycles", response_model=list[TableSnapshotCycleSummary])
def list_snapshot_cycles(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Lists every (cycle_config, cycle_year) that has at least one table snapshot for
    the current tenant, each with its per-table summaries - the data a "switch to
    historical view" picker in the table overview UI needs to render its options."""
    require_reader(user)
    rows = db.scalars(
        select(TableSnapshot)
        .where(TableSnapshot.tenant_id == user.current_tenant_id)
        .order_by(TableSnapshot.cycle_year.desc(), TableSnapshot.table_name)
    ).all()
    if not rows:
        return []

    cycle_configs = {
        cfg.id: cfg
        for cfg in db.scalars(select(CycleConfig).where(CycleConfig.tenant_id == user.current_tenant_id))
    }

    grouped: dict[tuple[int, int], list[TableSnapshot]] = {}
    for row in rows:
        grouped.setdefault((row.cycle_config_id, row.cycle_year), []).append(row)

    summaries: list[TableSnapshotCycleSummary] = []
    for (cycle_config_id, cycle_year), table_rows in grouped.items():
        cfg = cycle_configs.get(cycle_config_id)
        if cfg is None:
            continue
        summaries.append(
            TableSnapshotCycleSummary(
                cycle_config_id=cfg.public_id,
                cycle_config_name=cfg.name,
                cycle_year=cycle_year,
                tables=[_table_summary(r) for r in table_rows],
            )
        )
    summaries.sort(key=lambda s: (s.cycle_config_name, -s.cycle_year))
    return summaries


@router.get("/table-snapshots/{cycle_config_id}/{cycle_year}/{table_name}", response_model=TableSnapshotRowsRead)
def get_snapshot_table(
    cycle_config_id: uuid.UUID,
    cycle_year: int,
    table_name: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    _require_known_table(table_name)
    cfg = _get_owned_cycle_config(db, cycle_config_id, user.current_tenant_id)
    snapshot = db.scalar(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == user.current_tenant_id,
            TableSnapshot.cycle_config_id == cfg.id,
            TableSnapshot.cycle_year == cycle_year,
            TableSnapshot.table_name == table_name,
        )
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No snapshot for this cycle/table")
    return TableSnapshotRowsRead(
        table_name=table_name,
        cycle_year=cycle_year,
        row_count=snapshot.row_count,
        is_edited=snapshot.is_edited,
        rows=snapshot.snapshot_json,
    )


@router.put("/table-snapshots/{cycle_config_id}/{cycle_year}/{table_name}/rows/{row_public_id}")
def update_snapshot_row(
    cycle_config_id: uuid.UUID,
    cycle_year: int,
    table_name: str,
    row_public_id: uuid.UUID,
    payload: TableSnapshotRowUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Guarded historical-edit: directly overwrites the frozen row in place (v1 - no
    revision system, see the cycle-snapshot feature plan). Editing frozen historical
    data is admin-only, stricter than the live table's own write permission, and
    requires the client to explicitly pass confirm_historical_edit=true - the API-level
    half of the "only with an explicit warning" requirement (the UI half is a
    confirmation modal that must be shown before this call is ever made)."""
    require_admin(user)
    _require_known_table(table_name)
    if payload.confirm_historical_edit is not True:
        raise HTTPException(status_code=400, detail="confirm_historical_edit must be true to edit historical data")
    cfg = _get_owned_cycle_config(db, cycle_config_id, user.current_tenant_id)
    found = get_snapshot_row(
        db,
        tenant_id=user.current_tenant_id,
        cycle_config_id=cfg.id,
        cycle_year=cycle_year,
        table_name=table_name,
        row_public_id=str(row_public_id),
    )
    if found is None:
        raise HTTPException(status_code=404, detail="Snapshot row not found")
    snapshot, row, index = found

    # id/public_id are never client-editable - always keep the frozen row's originals,
    # regardless of what payload.values happens to contain.
    updated_row = {**row, **payload.values, "id": row["id"], "public_id": row["public_id"]}
    updated_rows = list(snapshot.snapshot_json)
    updated_rows[index] = updated_row
    snapshot.snapshot_json = updated_rows
    snapshot.is_edited = True
    snapshot.edited_at = datetime.now(UTC)
    snapshot.edited_by = user.user_id
    db.commit()

    AuditService().log(
        db,
        action="table_snapshot.historical_edit",
        actor=user,
        entity_type=table_name,
        entity_id=row.get("id"),
        details={"cycle_config_id": cfg.id, "cycle_year": cycle_year, "changed_fields": list(payload.values.keys())},
    )
    return updated_row


@router.delete(
    "/table-snapshots/{cycle_config_id}/{cycle_year}/{table_name}/rows/{row_public_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_snapshot_row(
    cycle_config_id: uuid.UUID,
    cycle_year: int,
    table_name: str,
    row_public_id: uuid.UUID,
    payload: TableSnapshotRowDelete,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Same guard as update_snapshot_row, for removing a row from a historical view."""
    require_admin(user)
    _require_known_table(table_name)
    if payload.confirm_historical_edit is not True:
        raise HTTPException(status_code=400, detail="confirm_historical_edit must be true to edit historical data")
    cfg = _get_owned_cycle_config(db, cycle_config_id, user.current_tenant_id)
    found = get_snapshot_row(
        db,
        tenant_id=user.current_tenant_id,
        cycle_config_id=cfg.id,
        cycle_year=cycle_year,
        table_name=table_name,
        row_public_id=str(row_public_id),
    )
    if found is None:
        raise HTTPException(status_code=404, detail="Snapshot row not found")
    snapshot, row, index = found

    updated_rows = list(snapshot.snapshot_json)
    del updated_rows[index]
    snapshot.snapshot_json = updated_rows
    snapshot.row_count = len(updated_rows)
    snapshot.is_edited = True
    snapshot.edited_at = datetime.now(UTC)
    snapshot.edited_by = user.user_id
    db.commit()

    AuditService().log(
        db,
        action="table_snapshot.historical_delete",
        actor=user,
        entity_type=table_name,
        entity_id=row.get("id"),
        details={"cycle_config_id": cfg.id, "cycle_year": cycle_year},
    )
