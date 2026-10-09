"""Automatische Fotoalben pro Wandertour (GPS + Aufnahmedatum).

Die Touren leben im Wanderplaner-Service (eigene Datenbank), die Fotos hier. hocX schickt
deshalb nur Koordinaten und Aufnahmedatum der Fotos an den Service
(wanderplaner_client.match_photos) und pflegt mit dem Ergebnis die Alben vom Typ
'hiking_tour'. Alben verweisen per hiking_tour_public_id ohne Fremdschluessel auf die Tour;
Alben verschwundener Touren werden beim Abgleich entfernt.

Aufrufer steuern die Transaktion. Der Abgleich ist ein Komfortmerkmal: Ist der
Wanderplaner fuer den Mandanten nicht gebucht oder nicht erreichbar, bleiben Uploads und
Tour-Aenderungen davon unberuehrt (siehe sync_photos_for_tours_best_effort)."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from io import BytesIO

from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.error_log import record_system_error
from app.models.entities import PhotoAlbum, PhotoAlbumItem, StoredFile, TenantFeature
from app.services import wanderplaner_client
from app.services.photo_event_link_service import capture_date

_logger = logging.getLogger(__name__)

WANDERPLANER_FEATURE = "wanderplaner"


def extract_gps(content: bytes) -> tuple[float | None, float | None]:
    """Fehlende oder beschädigte optionale EXIF-Daten verhindern keinen Upload."""
    try:
        with Image.open(BytesIO(content)) as image:
            gps = image.getexif().get_ifd(0x8825)
        def coordinate(values, ref, positive, negative, limit):
            if isinstance(ref, bytes):
                ref = ref.decode('ascii')
            if ref not in (positive, negative) or len(values) != 3:
                raise ValueError('Ungültige GPS-Angabe')
            degrees, minutes, seconds = map(float, values)
            if not (0 <= degrees <= limit and 0 <= minutes < 60 and 0 <= seconds < 60):
                raise ValueError('Ungültige GPS-Koordinaten')
            value = degrees + minutes / 60 + seconds / 3600
            if not math.isfinite(value) or value > limit:
                raise ValueError('Ungültige GPS-Koordinaten')
            return -value if ref == negative else value
        return coordinate(gps[2], gps[1], 'N', 'S', 90), coordinate(gps[4], gps[3], 'E', 'W', 180)
    except Exception:
        return None, None


def tenant_uses_wanderplaner(db: Session, tenant_id: int) -> bool:
    if not wanderplaner_client.is_configured():
        return False
    return db.scalar(select(TenantFeature.feature_code).where(
        TenantFeature.tenant_id == tenant_id, TenantFeature.feature_code == WANDERPLANER_FEATURE,
    )) is not None


def _analyze_missing_gps(db: Session, tenant_id: int) -> None:
    """Einmaliges Nachlesen bestehender Fotos, damit neue Touren ältere Uploads finden."""
    from app.core.config import settings
    from app.services.file_service import _extract_image_metadata, _safe_storage_path

    for stored_file in db.scalars(select(StoredFile).where(
        StoredFile.tenant_id == tenant_id, StoredFile.mime_type.like('image/%'),
        StoredFile.gps_analyzed_at.is_(None), StoredFile.scan_status == 'clean',
    )):
        path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
        try:
            content = path.read_bytes()
        except OSError:
            continue
        stored_file.gps_latitude, stored_file.gps_longitude = extract_gps(content)
        _, _, taken_at, _ = _extract_image_metadata(content)
        if stored_file.exif_taken_at is None:
            stored_file.exif_taken_at = taken_at
        stored_file.gps_analyzed_at = datetime.now(UTC)
    db.flush()


def sync_photos_for_tours(db: Session, tenant_id: int, *, file_ids=None) -> None:
    """Beide Richtungen (neues Foto, geänderte Tour) verwenden denselben Abgleich;
    wiederholte Aufrufe sind idempotent. Ohne file_ids werden alle Fotos des Mandanten
    abgeglichen. Fehler des Wanderplaner-Service werden geworfen."""
    from app.services.photo_album_service import add_items

    if file_ids is not None and not file_ids:
        return
    db.flush()
    if file_ids is None:
        _analyze_missing_gps(db, tenant_id)
    query = select(StoredFile).where(
        StoredFile.tenant_id == tenant_id, StoredFile.gps_latitude.is_not(None), StoredFile.gps_longitude.is_not(None),
    )
    if file_ids is not None:
        query = query.where(StoredFile.public_id.in_(file_ids))
    photos = list(db.scalars(query))
    tours, matches = wanderplaner_client.match_photos(tenant_id, [
        wanderplaner_client.PhotoPosition(file_id=f.public_id, lat=f.gps_latitude, lon=f.gps_longitude, taken_on=capture_date(f))
        for f in photos
    ])

    albums = list(db.scalars(select(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbum.kind == 'hiking_tour')))
    # Tour im Wanderplaner geloescht: Album samt Einträgen entfernen (frueher per FK-Cascade).
    for album in [album for album in albums if album.hiking_tour_public_id not in tours]:
        db.execute(delete(PhotoAlbumItem).where(PhotoAlbumItem.album_id == album.id))
        db.delete(album)
        albums.remove(album)
    by_tour = {album.hiking_tour_public_id: album for album in albums}

    for stored_file in photos:
        tour_id = matches.get(stored_file.public_id)
        for album in albums:
            if album.hiking_tour_public_id != tour_id:
                db.execute(delete(PhotoAlbumItem).where(PhotoAlbumItem.album_id == album.id, PhotoAlbumItem.file_id == stored_file.public_id))
        if tour_id is None:
            continue
        album = by_tour.get(tour_id)
        if album is None:
            db.execute(insert(PhotoAlbum).values(
                tenant_id=tenant_id, name=tours[tour_id], kind='hiking_tour', hiking_tour_public_id=tour_id,
            ).on_conflict_do_nothing())
            album = db.scalars(select(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbum.hiking_tour_public_id == tour_id)).one()
            by_tour[tour_id] = album
            albums.append(album)
        add_items(db, album, [stored_file.public_id])
    # Auch leere Alben behalten bei einer Umbenennung den aktuellen Tournamen.
    for tour_id, album in by_tour.items():
        album.name = tours[tour_id]
    db.flush()


def sync_photos_for_tours_best_effort(db: Session, tenant_id: int, *, file_ids=None, actor_email: str | None = None) -> None:
    """Abgleich in einem Savepoint nach einer Tour-Aenderung bzw. einem Upload. Ein Fehler
    hier darf die eigentliche Aktion nicht scheitern lassen, wird aber in system_error_log
    festgehalten (CLAUDE.md, Zentrale Fehlererfassung, Regel 4)."""
    if not tenant_uses_wanderplaner(db, tenant_id):
        return
    try:
        with db.begin_nested():
            sync_photos_for_tours(db, tenant_id, file_ids=file_ids)
    except Exception as exc:
        _logger.exception("Foto-Abgleich mit dem Wanderplaner fehlgeschlagen (Mandant %s)", tenant_id)
        # Eigene Session: record_system_error committet, die Transaktion des Aufrufers (z.B.
        # ein laufender Upload) darf dadurch nicht vorzeitig festgeschrieben werden.
        with SessionLocal() as log_db:
            record_system_error(log_db, exc=exc, tenant_id=tenant_id, actor_email=actor_email)


def attach_tour_context(db: Session, items) -> None:
    if not items:
        return
    by_id = {item.id: item for item in items}
    rows = db.execute(select(PhotoAlbumItem.file_id, PhotoAlbum.hiking_tour_public_id, PhotoAlbum.name)
        .join(PhotoAlbum, PhotoAlbum.id == PhotoAlbumItem.album_id)
        .where(PhotoAlbum.kind == 'hiking_tour', PhotoAlbumItem.file_id.in_(by_id)))
    for file_id, tour_id, title in rows:
        by_id[file_id].hiking_tour_id = tour_id
        by_id[file_id].hiking_tour_title = title
