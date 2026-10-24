"""Oeffentliche (unauthentifizierte) Downloadseite eines Freigabe-Links: der Token IST die
Authentifizierung (siehe share_link_service.py), es gibt hier bewusst kein CurrentUser/
get_current_user. Reiner Lesezugriff (Download), daher im normalen Haupt-Backend statt einem
separaten, restricted Service wie Abgabebox - trotzdem IP-Rate-Limitiert gegen Enumeration,
gleiches Muster wie auth.py's tenant_by_domain."""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.config import settings
from app.core.client_ip import client_ip
from app.core.db import get_db, release_for_stream
from app.core.rate_limit import enforce_rate_limit
from app.models.entities import PhotoAlbum, ShareLink, StoredFile, Tenant
from app.schemas.files import PublicShareFile, PublicShareRead
from app.services import photo_album_share_service, share_link_service
from app.core.storage import MAIN, get_object_store, object_response, read_bytes_or_404, safe_suffix, write_object_to_zip
from app.services.file_service import FileService
from app.services import image_export_service
from app.services.photo_metadata_privacy import SANITIZABLE_MIME_TYPES, MetadataPolicy, sanitize_image

router = APIRouter()
service = FileService()


def _enforce_rate_limit(request: Request, scope: str, *, limit: int) -> None:
    """Eigener Zaehler pro Endpunkt-Art: ein gemeinsamer Zaehler liess die Vorschaubilder einer
    groesseren Galerie (je ein Request) das niedrige ZIP-Limit schon beim Seitenaufruf aufbrauchen -
    "Alle herunterladen" lieferte dann ein 429-JSON statt des ZIPs."""
    enforce_rate_limit(f"public-share:{scope}:{client_ip(request)}", limit=limit, period_seconds=60)


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
    statement = select(StoredFile).where(StoredFile.public_id.in_(file_ids), StoredFile.scan_status == "clean")
    if link.album_id is None:
        # Dateilinks enthalten nur eigene Dateien (beim Anlegen geprüft). Öffentliche Sessions haben
        # keinen RLS-Kontext - die Bindung an den Link-Mandanten hier ist das Netz dafür, dass ein
        # verwaister Eintrag nie eine fremde Datei mit derselben public_id ausliefert (PRIV-016).
        # Album-Links (auch geteilte Partner-Alben) prüft file_ids_for_link selbst.
        statement = statement.where(StoredFile.tenant_id == link.tenant_id)
    rows = {row.public_id: row for row in db.scalars(statement)}
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


def _policy_for(db: Session, link: ShareLink, stored_file: StoredFile) -> MetadataPolicy:
    """Metadaten-Policy des Links für eine einzelne Datei. Den Standort gibt der Link nur weiter,
    wenn der anlegende Mandant ihn auch intern sehen darf (Security-Audit SEC-002): bei Fotos
    eines anderen Mandanten in einem geteilten Album entscheidet dessen Standort-Freigabe
    (photo_album_share_service.location_shared_with, gleiche Regel wie im Innenbereich,
    IMGMETA-007) - der Link kann sie nicht aufheben."""
    policy = share_link_service.metadata_policy_for(link)
    if policy.location and not photo_album_share_service.location_shared_with(db, link.tenant_id, stored_file.id, stored_file.tenant_id):
        return replace(policy, location=False)
    return policy


def _needs_sanitizing(policy: MetadataPolicy, stored_file: StoredFile) -> bool:
    """Muss die Datei fuer den Abruf umgeschrieben werden - Metadaten entfernen, die der Link
    nicht teilt, oder ein geschaetztes Aufnahmedatum eintragen (image_export_service)?"""
    sanitize = stored_file.mime_type in SANITIZABLE_MIME_TYPES and not policy.keeps_everything
    return sanitize or image_export_service.needs_export_processing(stored_file)


def _public_file_bytes(policy: MetadataPolicy, stored_file: StoredFile) -> bytes:
    """Dateiinhalt fuer den oeffentlichen Abruf - erst die Exportfassung (geschaetztes Datum,
    GPS aus der Datenbank), dann ohne die Metadaten, die der Link nicht teilt
    (Standort/Aufnahmedatum/Kamera, siehe photo_metadata_privacy.py). Die Reihenfolge stellt
    sicher, dass nichts eingetragen wird, was der Link anschliessend nicht teilen darf."""
    original = read_bytes_or_404(MAIN, stored_file.storage_path, detail="File missing on filesystem")
    content = image_export_service.export_bytes(stored_file, original) or original
    return sanitize_image(content, stored_file.mime_type, policy)


def _public_file_response(
    request: Request, db: Session, link: ShareLink, stored_file: StoredFile, *, attachment: bool, headers: dict[str, str]
):
    policy = _policy_for(db, link, stored_file)
    if not _needs_sanitizing(policy, stored_file):
        return object_response(
            request, MAIN, stored_file.storage_path, media_type=stored_file.mime_type,
            filename=stored_file.original_name if attachment else None, attachment=attachment, headers=headers,
            not_found_detail="File missing on filesystem",
        )
    disposition = {"filename": stored_file.original_name, "content_disposition_type": "attachment"} if attachment else {}
    # Gefilterte Kopie auf der Platte statt Response(bytes), damit FileResponse weiterhin
    # Content-Disposition (inkl. Umlaut-Dateinamen) und Range-Requests uebernimmt.
    work_dir = Path(settings.upload_root) / "_staging" / "download"
    work_dir.mkdir(parents=True, exist_ok=True)
    clean_path = work_dir / f"{uuid.uuid4().hex}{safe_suffix(stored_file.storage_path)}"
    clean_path.write_bytes(_public_file_bytes(policy, stored_file))
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
    return release_for_stream(db, FileResponse(
        path=thumbnail_path,
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=604800, immutable"},
    ))


@router.get("/public/share/{token}/files/{file_id}/view")
def view_public_share_file(token: str, file_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """Original inline fuer die Lightbox (die Vorschau ist nur 480 px gross) - nur fuer
    _INLINE_IMAGE_TYPES, alles andere laeuft ueber /download als Attachment."""
    _enforce_rate_limit(request, "view", limit=300)
    link = _resolve_link_or_404(db, token)
    stored_file = _resolve_file_or_404(db, link, file_id)
    if stored_file.mime_type not in _INLINE_IMAGE_TYPES:
        raise HTTPException(status_code=404, detail="Keine Ansicht verfügbar")
    return release_for_stream(db, _public_file_response(
        request, db, link, stored_file, attachment=False, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    ))


@router.get("/public/share/{token}/files/{file_id}/download")
def download_public_share_file(token: str, file_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    _enforce_rate_limit(request, "file", limit=60)
    link = _resolve_link_or_404(db, token)
    stored_file = _resolve_file_or_404(db, link, file_id)
    return release_for_stream(db, _public_file_response(
        request, db, link, stored_file, attachment=True, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    ))


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
    if not stored_files:
        raise HTTPException(status_code=404, detail="Keine Dateien verfügbar")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    policies = {stored_file.id: _policy_for(db, link, stored_file) for stored_file in stored_files}
    # Nur das komplette Album wird zwischengespeichert; Teilauswahlen (?ids=) entstehen je Anfrage
    # und werden nach der Auslieferung gelöscht - sonst liesse sich der Datenträger mit vielen
    # verschiedenen Auswahlen füllen (Security-Review Paket 7).
    zip_path = _cached_share_zip(link, stored_files, policies, cache=ids is None)
    return release_for_stream(db, FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"{link.name}.zip",
        content_disposition_type="attachment",
        headers=headers,
        background=None if ids is None else BackgroundTask(zip_path.unlink, missing_ok=True),
    ))


# Öffentliche Album-ZIPs (Concurrency-Audit CONC-009): vorher baute jede Anfrage - anonym, 20/min je
# IP - eine vollständige Kopie auf dem Upload-Datenträger, ohne globale Grenze. Jetzt teilen sich
# gleiche Auswahlen eine Datei für SHARE_ZIP_TTL_SECONDS, höchstens _SHARE_ZIP_SLOTS Builds laufen
# je Prozess gleichzeitig, und vor dem Bau wird freier Platz geprüft.
SHARE_ZIP_TTL_SECONDS = 600
_SHARE_ZIP_SLOTS = threading.BoundedSemaphore(2)
_SHARE_ZIP_SLOT_WAIT_SECONDS = 20
_SHARE_ZIP_FREE_RESERVE_BYTES = 1024**3


def _share_zip_dir() -> Path:
    directory = Path(settings.upload_root) / "_staging" / "download" / "share-zip"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# Alles, was den Inhalt einer Datei im ZIP bestimmt (image_export_service: geschätztes Datum, GPS;
# Policy des Links und Standortfreigabe des Partners über policy).
_SHARE_ZIP_FILE_FIELDS = (
    "id", "checksum_sha256", "source_checksum_sha256", "original_name", "mime_type",
    "exif_taken_at", "estimated_taken_on", "gps_latitude", "gps_longitude", "gps_source",
)


def _share_zip_key(link: ShareLink, stored_files: list[StoredFile], policies: dict[int, MetadataPolicy]) -> str:
    parts = [str(link.id), str(link.name)]
    for stored_file in sorted(stored_files, key=lambda item: item.id):
        fields = ":".join(str(getattr(stored_file, name, "")) for name in _SHARE_ZIP_FILE_FIELDS)
        parts.append(f"{fields}:{policies[stored_file.id]!r}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _purge_expired_share_zips(directory: Path) -> None:
    # Erst nach doppelter Frist löschen: eine Datei, die gerade noch wiederverwendet werden durfte,
    # wird nie gelöscht, während ein anderer Request sie ausliefert.
    cutoff = time.time() - 2 * SHARE_ZIP_TTL_SECONDS
    for candidate in directory.glob("*.zip"):
        try:
            if candidate.stat().st_mtime < cutoff:
                candidate.unlink(missing_ok=True)
        except OSError:
            continue


def _cached_share_zip(link: ShareLink, stored_files: list[StoredFile], policies: dict[int, MetadataPolicy], *, cache: bool = True) -> Path:
    directory = _share_zip_dir()
    _purge_expired_share_zips(directory)
    name = _share_zip_key(link, stored_files, policies) if cache else f"once-{uuid.uuid4().hex}"
    target = directory / f"{name}.zip"

    def reusable() -> bool:
        try:
            return time.time() - target.stat().st_mtime < SHARE_ZIP_TTL_SECONDS
        except FileNotFoundError:
            return False

    if reusable():
        return target
    if not _SHARE_ZIP_SLOTS.acquire(timeout=_SHARE_ZIP_SLOT_WAIT_SECONDS):
        raise HTTPException(status_code=503, detail="Gerade werden viele Downloads vorbereitet - bitte gleich erneut versuchen", headers={"Retry-After": "30"})
    try:
        if reusable():  # ein paralleler Request hat dieselbe Auswahl inzwischen gebaut
            return target
        estimated = sum(stored_file.file_size_bytes or 0 for stored_file in stored_files)
        if shutil.disk_usage(directory).free < estimated + _SHARE_ZIP_FREE_RESERVE_BYTES:
            raise HTTPException(status_code=507, detail="Zu wenig freier Speicher für den Download")
        store = get_object_store()
        partial = directory / f".{uuid.uuid4().hex}.partial"
        used_names: set[str] = set()
        try:
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED) as archive:
                for stored_file in stored_files:
                    if not store.exists(MAIN, stored_file.storage_path):
                        continue
                    name = Path(stored_file.original_name).name
                    if name in used_names:
                        name = f"{stored_file.public_id.hex[:8]}_{name}"
                    used_names.add(name)
                    policy = policies[stored_file.id]
                    if _needs_sanitizing(policy, stored_file):
                        archive.writestr(name, _public_file_bytes(policy, stored_file))
                    else:
                        write_object_to_zip(archive, MAIN, stored_file.storage_path, name)
            if not used_names:
                raise HTTPException(status_code=404, detail="Keine Dateien verfügbar")
            partial.replace(target)  # überschreibt eine abgelaufene Fassung atomar
        finally:
            partial.unlink(missing_ok=True)
        return target
    finally:
        _SHARE_ZIP_SLOTS.release()


