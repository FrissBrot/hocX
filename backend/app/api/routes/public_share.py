"""Oeffentliche (unauthentifizierte) Downloadseite eines Freigabe-Links: der Token IST die
Authentifizierung (siehe share_link_service.py), es gibt hier bewusst kein CurrentUser/
get_current_user. Reiner Lesezugriff (Download), daher im normalen Haupt-Backend statt einem
separaten, restricted Service wie Abgabebox - trotzdem IP-Rate-Limitiert gegen Enumeration,
gleiches Muster wie auth.py's tenant_by_domain."""

from __future__ import annotations

import uuid
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.models.entities import PhotoAlbum, ShareLink, StoredFile, Tenant
from app.schemas.files import PublicShareFile, PublicShareRead
from app.services import share_link_service
from app.services.file_service import FileService, _safe_storage_path
from app.services.photo_metadata_privacy import SANITIZABLE_MIME_TYPES, sanitize_image

router = APIRouter()
service = FileService()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request, scope: str, *, limit: int) -> None:
    """Eigener Zaehler pro Endpunkt-Art: ein gemeinsamer Zaehler liess die Vorschaubilder einer
    groesseren Galerie (je ein Request) das niedrige ZIP-Limit schon beim Seitenaufruf aufbrauchen -
    "Alle herunterladen" lieferte dann ein 429-JSON statt des ZIPs."""
    enforce_rate_limit(f"public-share:{scope}:{_client_ip(request)}", limit=limit, period_seconds=60)


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


# Nur Formate, die jeder Browser sicher inline darstellt - bewusst kein SVG (Script-faehig)
# und kein HEIC (in den meisten Browsern nicht darstellbar, dort bleibt die Vorschau).
_INLINE_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


def _resolve_file_or_404(db: Session, link: ShareLink, file_id: uuid.UUID) -> StoredFile:
    for stored_file in _clean_stored_files_for_link(db, link):
        if stored_file.public_id == file_id:
            return stored_file
    raise HTTPException(status_code=404, detail="Datei nicht gefunden")


def _needs_sanitizing(link: ShareLink, stored_file: StoredFile) -> bool:
    return stored_file.mime_type in SANITIZABLE_MIME_TYPES and not share_link_service.metadata_policy_for(link).keeps_everything


def _public_file_bytes(link: ShareLink, stored_file: StoredFile, file_path: Path) -> bytes:
    """Dateiinhalt fuer den oeffentlichen Abruf - Fotos ohne die Metadaten, die der Link nicht
    teilt (Standort/Aufnahmedatum/Kamera, siehe photo_metadata_privacy.py)."""
    return sanitize_image(file_path.read_bytes(), stored_file.mime_type, share_link_service.metadata_policy_for(link))


def _public_file_response(link: ShareLink, stored_file: StoredFile, *, attachment: bool, headers: dict[str, str]) -> FileResponse:
    file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    disposition = {"filename": stored_file.original_name, "content_disposition_type": "attachment"} if attachment else {}
    if not _needs_sanitizing(link, stored_file):
        return FileResponse(path=file_path, media_type=stored_file.mime_type, headers=headers, **disposition)
    # Gefilterte Kopie auf der Platte statt Response(bytes), damit FileResponse weiterhin
    # Content-Disposition (inkl. Umlaut-Dateinamen) und Range-Requests uebernimmt.
    work_dir = Path(settings.upload_root) / "_staging" / "download"
    work_dir.mkdir(parents=True, exist_ok=True)
    clean_path = work_dir / f"{uuid.uuid4().hex}{file_path.suffix}"
    clean_path.write_bytes(_public_file_bytes(link, stored_file, file_path))
    return FileResponse(
        path=clean_path,
        media_type=stored_file.mime_type,
        headers=headers,
        background=BackgroundTask(clean_path.unlink, missing_ok=True),
        **disposition,
    )


@router.get("/public/share/{token}", response_model=PublicShareRead)
def get_public_share(token: str, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit(request, "page", limit=60)
    link = _resolve_link_or_404(db, token)
    stored_files = _clean_stored_files_for_link(db, link)
    base = f"/api/public/share/{token}"
    files = []
    for stored_file in stored_files:
        mime_type = stored_file.mime_type or ""
        is_image = mime_type.startswith("image/")
        thumbnail_url = f"{base}/files/{stored_file.public_id}/thumbnail" if is_image else None
        files.append(
            PublicShareFile(
                id=stored_file.public_id,
                original_name=stored_file.original_name,
                mime_type=stored_file.mime_type,
                file_size_bytes=stored_file.file_size_bytes,
                is_image=is_image,
                width=stored_file.width,
                height=stored_file.height,
                taken_at=stored_file.exif_taken_at if link.share_capture_date else None,
                thumbnail_url=thumbnail_url,
                view_url=f"{base}/files/{stored_file.public_id}/view" if mime_type in _INLINE_IMAGE_TYPES else thumbnail_url,
                download_url=f"{base}/files/{stored_file.public_id}/download",
            )
        )
    taken_dates = [f.exif_taken_at for f in stored_files if f.exif_taken_at is not None] if link.share_capture_date else []
    album_name = db.scalar(select(PhotoAlbum.name).where(PhotoAlbum.id == link.album_id)) if link.album_id is not None else None
    tenant_name = db.scalar(select(Tenant.name).where(Tenant.id == link.tenant_id)) or ""
    return PublicShareRead(
        name=link.name,
        context=album_name if album_name and album_name != link.name else None,
        is_album=link.album_id is not None,
        tenant_name=tenant_name,
        expires_at=link.expires_at,
        total_size_bytes=sum(f.file_size_bytes or 0 for f in stored_files),
        date_from=min(taken_dates) if taken_dates else None,
        date_to=max(taken_dates) if taken_dates else None,
        files=files,
        download_all_url=f"{base}/download" if files else None,
    )


@router.get("/public/share/{token}/files/{file_id}/thumbnail")
def get_public_share_thumbnail(token: str, file_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    # Ein Request pro Vorschaubild: Alben haben keine Obergrenze, und schnelles Scrollen laedt
    # trotz loading="lazy" schnell einige hundert. Gegen Token-Raten schuetzt das Limit hier
    # ohnehin nicht (192 Bit), es bremst nur Missbrauch - daher grosszuegig.
    _enforce_rate_limit(request, "thumbnail", limit=3000)
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


@router.get("/public/share/{token}/files/{file_id}/view")
def view_public_share_file(token: str, file_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """Original inline fuer die Lightbox (die Vorschau ist nur 480 px gross) - nur fuer
    _INLINE_IMAGE_TYPES, alles andere laeuft ueber /download als Attachment."""
    _enforce_rate_limit(request, "view", limit=300)
    link = _resolve_link_or_404(db, token)
    stored_file = _resolve_file_or_404(db, link, file_id)
    if stored_file.mime_type not in _INLINE_IMAGE_TYPES:
        raise HTTPException(status_code=404, detail="Keine Ansicht verfügbar")
    return _public_file_response(
        link, stored_file, attachment=False, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    )


@router.get("/public/share/{token}/files/{file_id}/download")
def download_public_share_file(token: str, file_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit(request, "file", limit=60)
    link = _resolve_link_or_404(db, token)
    stored_file = _resolve_file_or_404(db, link, file_id)
    return _public_file_response(
        link, stored_file, attachment=True, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    )


@router.get("/public/share/{token}/download")
def download_public_share_all(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    ids: Annotated[str | None, Query(max_length=20000)] = None,
):
    """Alle Dateien des Links (oder mit ?ids=<uuid>,<uuid> nur die Auswahl) - immer als ZIP,
    auch bei einer einzelnen Datei, damit "Alle herunterladen" sich verlaesslich gleich
    verhaelt. Gebaut auf der Platte, nicht im Speicher - wie files.py's
    download_stored_file(part="both")."""
    _enforce_rate_limit(request, "zip", limit=20)
    link = _resolve_link_or_404(db, token)
    stored_files = _clean_stored_files_for_link(db, link)
    if ids is not None:
        try:
            wanted = {uuid.UUID(part.strip()) for part in ids.split(",") if part.strip()}
        except ValueError:
            raise HTTPException(status_code=422, detail="Ungültige Auswahl") from None
        stored_files = [f for f in stored_files if f.public_id in wanted]
    stored_files = [f for f in stored_files if _safe_storage_path(settings.storage_root, f.storage_path).exists()]
    if not stored_files:
        raise HTTPException(status_code=404, detail="Keine Dateien verfügbar")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}

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
            file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
            if _needs_sanitizing(link, stored_file):
                archive.writestr(name, _public_file_bytes(link, stored_file, file_path))
            else:
                archive.write(file_path, arcname=name)
    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"{link.name}.zip",
        content_disposition_type="attachment",
        headers=headers,
        background=BackgroundTask(zip_path.unlink, missing_ok=True),
    )
