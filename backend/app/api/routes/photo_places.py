"""Foto-Standorte: Ortssuche, Ort von Hand setzen/entfernen, Rückgängig (Migration 0260).

Die Umkreissuche selbst läuft über GET /files?near=…&near_km=… (routes/files.py), damit Suche,
Tags, Alben und Reichweite unverändert mitgelten.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_any_permission, require_permission
from app.models.entities import AppUser, StoredFile
from app.models.place_entities import GeoPlace, PlaceChangeBatch
from app.schemas.photo_places import (
    GeoDatasetRead,
    PlaceAssign,
    PlaceAssignResult,
    PlaceChangeBatchRead,
    PlaceChangeUndoResult,
    PlaceSearchHit,
)
from app.services import context_visibility_service, geo_places, photo_places, upload_job_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()
access_service = AccessService()


@router.get("/places/search", response_model=list[PlaceSearchHit])
def search_places(
    q: str = Query(min_length=1, max_length=photo_places.MAX_QUERY_LENGTH),
    limit: int = Query(default=8, ge=1, le=20),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Orte zu einer Eingabe (Treffertyp «Ort» der Fotosuche, Ort von Hand). Öffentliche
    Referenzdaten, ohne Koordinaten und ohne Bezug zu Fotos."""
    require_any_permission(user, P.FILES_READ, P.PHOTOS_READ)
    return photo_places.search_places(db, q, limit=limit)


@router.get("/places/sources", response_model=list[GeoDatasetRead])
def place_sources(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Stand und Quellenangabe der Ortsdaten (GeoNames CC BY 4.0, swisstopo)."""
    require_any_permission(user, P.FILES_READ, P.PHOTOS_READ)
    return geo_places.status(db)


def _batch_params(db: Session, key: str | None) -> dict:
    """Ort der Änderung mit Namen (Anzeige im Upload-Verlauf, auch wenn der Ort später wegfällt)."""
    if key is None:
        return {}
    name = db.scalar(select(GeoPlace.name).where(GeoPlace.place_key == key))
    return {"place_key": key, "place_name": name}


def _writable_ids(db: Session, user: CurrentUser, ids: list[uuid.UUID]) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """(beschreibbare IDs, nicht lesbare eigene IDs) - Reichweite «nur zugewiesene» wie die übrigen
    Mehrfachaktionen (404 bei Abgabe-Dateien fremder Aufträge), Protokollbilder nur aus lesbaren
    Protokollen. Fremde/unbekannte IDs bleiben drin und kommen als not_found zurück."""
    own = list(db.scalars(select(StoredFile).where(StoredFile.tenant_id == user.current_tenant_id, StoredFile.public_id.in_(ids))))
    readable = context_visibility_service.readable_assignment_ids(db, user)
    if readable is not None:
        for stored in own:
            if not context_visibility_service.abgabe_scope_allows(db, user, stored.id):
                raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    unreadable: list[uuid.UUID] = []
    for stored in own:
        try:
            access_service.ensure_can_read_stored_file(db, user, stored.id, allow_context_grant=False)
        except HTTPException:
            unreadable.append(stored.public_id)
    blocked = set(unreadable)
    return [file_id for file_id in ids if file_id not in blocked], unreadable


@router.post("/photo-places/assign", response_model=PlaceAssignResult)
def assign_place(payload: PlaceAssign, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Ort von Hand setzen (``place_key``) oder entfernen (``null``) - einzeln, Mehrfachauswahl
    oder ganzer Upload-Vorgang (der Browser stückelt zu 500 und sendet ab dem zweiten Stück die
    batch_id). Fotos mit echtem GPS bleiben unverändert (skipped_gps). Nur eigene Fotos; fremde,
    unbekannte und nicht lesbare kommen einheitlich als not_found zurück."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    ids = list(dict.fromkeys(payload.file_ids))
    key = photo_places.place_exists(db, payload.place_key) if payload.place_key is not None else None
    upload_job = upload_job_service.get_visible_job(db, user, payload.upload_job_id) if payload.upload_job_id is not None else None
    writable, unreadable = _writable_ids(db, user, ids)
    mode = "set" if key is not None else "clear"
    batch = photo_places.open_batch(
        db, user, batch_id=payload.batch_id, mode=mode, params=_batch_params(db, key),
        upload_job_id=upload_job.id if upload_job is not None else None,
    )
    if key is not None and payload.batch_id is not None and (batch.params or {}).get("place_key") != key:
        raise HTTPException(status_code=404, detail="Änderung nicht gefunden")
    outcome = photo_places.assign(db, user.current_tenant_id, writable, key, user_id=user.user_id)
    outcome.not_found_ids.extend(unreadable)
    photo_places.record(db, batch, outcome.changes)
    batch_id = batch.id
    if not outcome.changes and payload.batch_id is None:
        db.delete(batch)
        batch_id = None
    audit.log(
        db, action="photo.place_set" if key else "photo.place_cleared", actor=user, entity_type="place_change_batch",
        entity_id=None,
        details={
            "batch_id": str(batch_id) if batch_id else None, "place_key": key, "requested": len(ids),
            "updated": len(outcome.updated_ids), "skipped_gps": len(outcome.skipped_gps_ids),
            "file_ids": [str(public_id) for public_id in outcome.updated_ids],
        },
        commit=False,
    )
    db.commit()
    return PlaceAssignResult(
        updated_ids=outcome.updated_ids, unchanged_ids=outcome.unchanged_ids, skipped_gps_ids=outcome.skipped_gps_ids,
        not_found_ids=outcome.not_found_ids, batch_id=batch_id,
    )


@router.post("/place-changes/{batch_id}/undo", response_model=PlaceChangeUndoResult)
def undo_place_change(batch_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Ortsänderung rückgängig: je Foto der vorherige Ort, aber nur, wo seither nichts geändert wurde."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Änderung nicht gefunden")
    batch = db.scalar(
        select(PlaceChangeBatch)
        .where(PlaceChangeBatch.id == batch_id, PlaceChangeBatch.tenant_id == user.current_tenant_id)
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Änderung nicht gefunden")
    if batch.undone_at is not None:
        raise HTTPException(status_code=409, detail="Diese Änderung wurde bereits rückgängig gemacht")
    readable = context_visibility_service.readable_assignment_ids(db, user)

    def writable(stored: StoredFile) -> bool:
        if readable is not None and not context_visibility_service.abgabe_scope_allows(db, user, stored.id):
            return False
        try:
            access_service.ensure_can_read_stored_file(db, user, stored.id, allow_context_grant=False)
        except HTTPException:
            return False
        return True

    outcome = photo_places.undo(db, batch, user_id=user.user_id, writable=writable)
    audit.log(
        db, action="photo.place_undone", actor=user, entity_type="place_change_batch", entity_id=None,
        details={
            "batch_id": str(batch.id), "restored": len(outcome.restored_ids), "conflicts": len(outcome.conflict_ids),
            "file_ids": [str(public_id) for public_id in outcome.restored_ids],
        },
        commit=False,
    )
    db.commit()
    return PlaceChangeUndoResult(restored_ids=outcome.restored_ids, conflict_ids=outcome.conflict_ids, not_found_ids=outcome.not_found_ids)


@router.get("/place-changes", response_model=list[PlaceChangeBatchRead])
def list_place_changes(
    upload_job_id: uuid.UUID = Query(...), db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Ortsänderungen eines Upload-Vorgangs mit Rückgängig-Status (Reiter «Korrekturen»)."""
    require_permission(user, P.PHOTOS_MANAGE)
    job = upload_job_service.get_visible_job(db, user, upload_job_id)
    batches = photo_places.list_for_job(db, user.current_tenant_id, job.id)
    remaining = photo_places.remaining_items(db, [batch.id for batch in batches])
    creators = {batch.created_by for batch in batches if batch.created_by}
    users = {
        row.id: row.display_name
        for row in db.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(creators)))
    } if creators else {}
    return [
        PlaceChangeBatchRead(
            id=batch.id, mode=batch.mode, params=batch.params or {}, created_at=batch.created_at,
            created_by_name=users.get(batch.created_by), updated_count=batch.updated_count,
            remaining=remaining.get(batch.id, 0), undone_at=batch.undone_at,
            can_undo=batch.undone_at is None and remaining.get(batch.id, 0) > 0,
        )
        for batch in batches
    ]
