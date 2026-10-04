"""Verwaltung von Freigabe-Links (authentifiziert, mandantenweit) - die oeffentliche
Download-Seite selbst liegt in public_share.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_writer
from app.models.entities import ShareLink
from app.schemas.files import ShareLinkCreate, ShareLinkRead
from app.services import photo_album_share_service, share_link_service
from app.services.file_service import FileService
from app.services.photo_metadata_privacy import MetadataPolicy

router = APIRouter()
service = FileService()


def _read(link: ShareLink, *, album_name: str | None, file_count: int, created_by_name: str | None) -> ShareLinkRead:
    return ShareLinkRead(
        id=link.id,
        name=link.name,
        url=f"/share/{link.token}",
        album_name=album_name,
        file_count=file_count,
        created_at=link.created_at,
        created_by_name=created_by_name,
        expires_at=link.expires_at,
        revoked_at=link.revoked_at,
        status=share_link_service.status_for(link),
        share_location=link.share_location,
        share_capture_date=link.share_capture_date,
        share_camera=link.share_camera,
    )


@router.post("/share-links", response_model=ShareLinkRead, status_code=201)
def create_share_link(payload: ShareLinkCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    name = payload.name.strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=422, detail="Name muss zwischen 1 und 120 Zeichen lang sein")
    has_files = bool(payload.file_ids)
    has_album = payload.album_id is not None
    if has_files == has_album:
        raise HTTPException(status_code=422, detail="Bitte entweder Dateien oder ein Album auswählen (genau eines).")
    metadata = MetadataPolicy(location=payload.share_location, capture_date=payload.share_capture_date, camera=payload.share_camera)

    if has_album:
        album = photo_album_share_service.get_accessible_album(db, payload.album_id, user.current_tenant_id)
        if album is None:
            raise HTTPException(status_code=404, detail="Album nicht gefunden")
        link = share_link_service.create_for_album(
            db, tenant_id=user.current_tenant_id, name=name, album=album, expires_at=payload.expires_at, created_by=user.user_id, metadata=metadata
        )
        return _read(link, album_name=album.name, file_count=len(share_link_service.file_ids_for_link(db, link)), created_by_name=user.display_name)

    ids = list(dict.fromkeys(payload.file_ids or []))
    found = service.list_tenant_files(db, user.current_tenant_id, file_ids=ids, limit=200)
    if {item.id for item in found} != set(ids):
        raise HTTPException(status_code=404, detail="Mindestens eine Datei wurde nicht gefunden")
    try:
        link = share_link_service.create_for_files(
            db, tenant_id=user.current_tenant_id, name=name, file_ids=ids, expires_at=payload.expires_at, created_by=user.user_id, metadata=metadata
        )
    except share_link_service.ShareLinkError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _read(link, album_name=None, file_count=len(ids), created_by_name=user.display_name)


@router.get("/share-links", response_model=list[ShareLinkRead])
def list_share_links(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return [
        _read(row.link, album_name=row.album_name, file_count=row.file_count, created_by_name=row.created_by_name)
        for row in share_link_service.list_for_tenant(db, user.current_tenant_id)
    ]


@router.delete("/share-links/{share_link_id}", status_code=204)
def revoke_share_link(share_link_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    link = db.get(ShareLink, share_link_id)
    if link is None or link.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Link nicht gefunden")
    share_link_service.revoke(db, link)
