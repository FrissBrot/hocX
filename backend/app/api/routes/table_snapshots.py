from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cycle_utils import get_cycle_year
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader, require_writer
from app.models.entities import CycleConfig, Protocol, TableSnapshot, Template
from app.schemas.table_snapshot import (
    TableSnapshotCycleSummary,
    TableSnapshotListReconstructDraft,
    TableSnapshotListReconstructRequest,
    TableSnapshotRowDelete,
    TableSnapshotRowUpdate,
    TableSnapshotRowsRead,
    TableSnapshotTableSummary,
)
from app.services import public_id_service
from app.services.audit_service import AuditService
from app.services.table_snapshot_config import SNAPSHOT_TABLES
from app.services.table_snapshot_service import (
    ReconstructionIdentityError,
    TableSnapshotService,
    build_reconstruction_draft,
    get_snapshot_row,
)

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
    """Lists every (cycle_config, cycle_year) worth showing in a "switch to historical
    view" picker: every period that already has a complete table_snapshot
    (has_snapshot=True), plus every *ended* period that has at least one protocol but no
    (or an incomplete) snapshot yet (has_snapshot=False) - a genuine gap the picker
    should flag with a warning and offer to reconstruct. The currently active,
    not-yet-ended period is never listed as a gap - it isn't historical yet."""
    require_reader(user)
    tenant_id = user.current_tenant_id
    cycle_configs = list(db.scalars(select(CycleConfig).where(CycleConfig.tenant_id == tenant_id)))
    if not cycle_configs:
        return []

    existing_rows = db.scalars(select(TableSnapshot).where(TableSnapshot.tenant_id == tenant_id)).all()
    existing_by_cycle: dict[tuple[int, int], list[TableSnapshot]] = {}
    for row in existing_rows:
        existing_by_cycle.setdefault((row.cycle_config_id, row.cycle_year), []).append(row)

    today = date.today()
    summaries: list[TableSnapshotCycleSummary] = []
    for cfg in cycle_configs:
        current_cycle_year = get_cycle_year(today, cfg.reset_month, cfg.reset_day)

        protocol_dates = db.scalars(
            select(Protocol.protocol_date)
            .join(Template, Template.id == Protocol.template_id)
            .where(Template.tenant_id == tenant_id, Template.cycle_config_id == cfg.id)
        ).all()
        ended_protocol_years = {
            get_cycle_year(d, cfg.reset_month, cfg.reset_day)
            for d in protocol_dates
            if d and get_cycle_year(d, cfg.reset_month, cfg.reset_day) < current_cycle_year
        }

        existing_years_for_cfg = {year for (cid, year) in existing_by_cycle if cid == cfg.id}
        cycle_years = existing_years_for_cfg | ended_protocol_years

        for cycle_year in cycle_years:
            table_rows = existing_by_cycle.get((cfg.id, cycle_year), [])
            has_snapshot = {r.table_name for r in table_rows} >= SNAPSHOT_TABLES.keys()
            summaries.append(
                TableSnapshotCycleSummary(
                    cycle_config_id=cfg.public_id,
                    cycle_config_name=cfg.name,
                    cycle_year=cycle_year,
                    has_snapshot=has_snapshot,
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


@router.get(
    "/table-snapshots/{cycle_config_id}/{cycle_year}/lists/{list_public_id}/reconstruct-draft",
    response_model=TableSnapshotListReconstructDraft,
)
def get_reconstruction_draft(
    cycle_config_id: uuid.UUID,
    cycle_year: int,
    list_public_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Pre-fills a starting point for reconstructing one list's data in a missing
    period, from whichever available source (an existing snapshot for this
    cycle_config, or the live list) is nearest by cycle year - see
    build_reconstruction_draft. The frontend shows this as an editable draft; the user's
    edits are posted back via reconstruct_list_period below."""
    require_writer(user)
    cfg = _get_owned_cycle_config(db, cycle_config_id, user.current_tenant_id)
    draft = build_reconstruction_draft(
        db, tenant_id=user.current_tenant_id, cycle_config=cfg, cycle_year=cycle_year, list_public_id=str(list_public_id)
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="No data found for this list in any source")
    return TableSnapshotListReconstructDraft(**draft)


@router.post("/table-snapshots/{cycle_config_id}/{cycle_year}/lists/{list_public_id}/reconstruct", status_code=status.HTTP_204_NO_CONTENT)
def reconstruct_list_period(
    cycle_config_id: uuid.UUID,
    cycle_year: int,
    list_public_id: uuid.UUID,
    payload: TableSnapshotListReconstructRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Fills a genuine snapshot gap for one list in one period - the client already
    pre-filled `payload` from the nearest available source (an existing snapshot or the
    live list, see list_snapshot_cycles' has_snapshot flag for how gaps are detected)
    and let the user review/edit it. Every row's identity is re-resolved server-side
    from a live row or an existing snapshot (see TableSnapshotService.
    reconstruct_list_period) - the client can edit values or drop rows, but can't
    fabricate a brand new one with no prior existence.

    Not a manual/on-demand snapshot trigger: it can only ever fill an already-identified
    gap for this one list, never freshly capture a period that already has this list."""
    require_writer(user)
    cfg = _get_owned_cycle_config(db, cycle_config_id, user.current_tenant_id)

    current_cycle_year = get_cycle_year(date.today(), cfg.reset_month, cfg.reset_day)
    if cycle_year >= current_cycle_year:
        raise HTTPException(status_code=400, detail="Cannot reconstruct a period that hasn't ended yet")

    already_captured = db.scalar(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == user.current_tenant_id,
            TableSnapshot.cycle_config_id == cfg.id,
            TableSnapshot.cycle_year == cycle_year,
            TableSnapshot.table_name == "list_definition",
        )
    )
    if already_captured is not None and any(row.get("public_id") == str(list_public_id) for row in already_captured.snapshot_json):
        raise HTTPException(status_code=409, detail="This list already has a snapshot for this period - use the edit endpoint instead")

    try:
        TableSnapshotService().reconstruct_list_period(
            db,
            tenant_id=user.current_tenant_id,
            cycle_config=cfg,
            cycle_year=cycle_year,
            list_public_id=str(list_public_id),
            definition_values=payload.definition_values,
            entry_payloads=payload.entries,
            edited_by=user.user_id,
        )
    except ReconstructionIdentityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    AuditService().log(
        db,
        action="table_snapshot.reconstruct",
        actor=user,
        entity_type="list_definition",
        entity_id=None,
        details={"cycle_config_id": cfg.id, "cycle_year": cycle_year, "list_public_id": str(list_public_id)},
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
