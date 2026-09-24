"""Oeffentliche (unauthentifizierte) Downloadseite eines Freigabe-Links: der Token IST die
Authentifizierung (siehe share_link_service.py), es gibt hier bewusst kein CurrentUser/
get_current_user. Reiner Lesezugriff (Download), daher im normalen Haupt-Backend statt einem
separaten, restricted Service wie Abgabebox - trotzdem IP-Rate-Limitiert gegen Enumeration,
gleiches Muster wie auth.py's tenant_by_domain."""

from __future__ import annotations

import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.models.entities import ShareLink, StoredFile
from app.schemas.files import PublicShareFile, PublicShareRead
from app.services import share_link_service
from app.services.file_service import FileService, _safe_storage_path

router = APIRouter()
service = FileService()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _resolve_link_or_404(db: Session, token: str) -> ShareLink:
    link = share_link_service.resolve_active(db, token)
    if link is None:
        # Same 404 whether the token never existed, was revoked, or expired - a guesser
        # can't learn which.
        raise HTTPException(status_code=404, detail="Link ungültig oder abgelaufen")
    return link


def _clean_stored_files_for_link(db: Session, link: ShareLink) -> list[StoredFile]:
    file_ids = share_link_service.file_ids_for_link(db, link)
    if not file_ids:
        return []
    rows = {
        row.public_id: row
        for row in db.scalars(select(StoredFile).where(StoredFile.public_id.in_(file_ids), StoredFile.scan_status == "clean"))
    }
    # Preserve the link's own file order (album order / selection order), not the id-set's.
    return [rows[file_id] for file_id in file_ids if file_id in rows]


def _resolve_file_or_404(db: Session, link: ShareLink, file_id: uuid.UUID) -> StoredFile:
    for stored_file in _clean_stored_files_for_link(db, link):
        if stored_file.public_id == file_id:
            return stored_file
    raise HTTPException(status_code=404, detail="Datei nicht gefunden")


@router.get("/public/share/{token}", response_model=PublicShareRead)
def get_public_share(token: str, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"public-share:{_client_ip(request)}", limit=60, period_seconds=60)
    link = _resolve_link_or_404(db, token)
    stored_files = _clean_stored_files_for_link(db, link)
    files = [
        PublicShareFile(
            id=stored_file.public_id,
            original_name=stored_file.original_name,
            mime_type=stored_file.mime_type,
            file_size_bytes=stored_file.file_size_bytes,
            is_image=(stored_file.mime_type or "").startswith("image/"),
            thumbnail_url=(
                f"/api/public/share/{token}/files/{stored_file.public_id}/thumbnail"
                if (stored_file.mime_type or "").startswith("image/")
                else None
            ),
            download_url=f"/api/public/share/{token}/files/{stored_file.public_id}/download",
        )
        for stored_file in stored_files
    ]
    return PublicShareRead(name=link.name, files=files, download_all_url=f"/api/public/share/{token}/download" if len(files) > 1 else None)


@router.get("/public/share/{token}/files/{file_id}/thumbnail")
def get_public_share_thumbnail(token: str, file_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"public-share:{_client_ip(request)}", limit=300, period_seconds=60)
    link = _resolve_link_or_404(db, token)
    stored_file = _resolve_file_or_404(db, link, file_id)
    thumbnail_path = service.ensure_thumbnail(db, stored_file, settings.storage_root)
    if thumbnail_path is None:
        raise HTTPException(status_code=404, detail="Keine Vorschau verfügbar")
    return FileResponse(
        path=thumbnail_path,
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=604800, immutable"},
    )


@router.get("/public/share/{token}/files/{file_id}/download")
def download_public_share_file(token: str, file_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"public-share:{_client_ip(request)}", limit=60, period_seconds=60)
    link = _resolve_link_or_404(db, token)
    stored_file = _resolve_file_or_404(db, link, file_id)
    file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    return FileResponse(
        path=file_path,
        media_type=stored_file.mime_type,
        filename=stored_file.original_name,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.get("/public/share/{token}/download")
def download_public_share_all(token: str, request: Request, db: Session = Depends(get_db)):
    """Alle Dateien des Links: die einzelne Datei direkt, mehrere als ZIP (gebaut auf der
    Platte, nicht im Speicher - wie files.py's download_stored_file(part="both"))."""
    enforce_rate_limit(f"public-share:{_client_ip(request)}", limit=20, period_seconds=60)
    link = _resolve_link_or_404(db, token)
    stored_files = [f for f in _clean_stored_files_for_link(db, link) if _safe_storage_path(settings.storage_root, f.storage_path).exists()]
    if not stored_files:
        raise HTTPException(status_code=404, detail="Keine Dateien verfügbar")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    if len(stored_files) == 1:
        stored_file = stored_files[0]
        return FileResponse(
            path=_safe_storage_path(settings.storage_root, stored_file.storage_path),
            media_type=stored_file.mime_type,
            filename=stored_file.original_name,
            content_disposition_type="attachment",
            headers=headers,
        )

    work_dir = Path(settings.upload_root) / "_staging" / "download"
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / f"{uuid.uuid4().hex}.zip"
    used_names: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for stored_file in stored_files:
            name = Path(stored_file.original_name).name
            if name in used_names:
                name = f"{stored_file.public_id.hex[:8]}_{name}"
            used_names.add(name)
            archive.write(_safe_storage_path(settings.storage_root, stored_file.storage_path), arcname=name)
    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"{link.name}.zip",
        content_disposition_type="attachment",
        headers=headers,
        background=BackgroundTask(zip_path.unlink, missing_ok=True),
    )
