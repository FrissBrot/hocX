"""GPS-Abgleich am Tourdatum. Aufrufer steuern die gemeinsame Transaktion."""
from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import math

from PIL import Image
from geoalchemy2 import Geography
from sqlalchemy import cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.models.entities import HikingTour, HikingTourRouteLeg, HikingTourWaypoint, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.services.photo_event_link_service import capture_date

# Toleranz für GPS-Ungenauigkeit und kurze Abstecher neben dem Wanderweg.
MATCH_RADIUS_M = 150


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


def find_matching_tour(db, stored_file):
    if stored_file.gps_latitude is None or stored_file.gps_longitude is None:
        return None
    point = cast(func.ST_SetSRID(func.ST_MakePoint(stored_file.gps_longitude, stored_file.gps_latitude), 4326), Geography)
    route = select(func.ST_Collect(HikingTourRouteLeg.geom)).where(
        HikingTourRouteLeg.hiking_tour_id == HikingTour.id
    ).correlate(HikingTour).scalar_subquery()
    # Vor der Routenberechnung nur echte Wegpunkte prüfen, keine erfundene Luftlinie.
    waypoints = select(func.ST_Collect(HikingTourWaypoint.point)).where(
        HikingTourWaypoint.hiking_tour_id == HikingTour.id
    ).correlate(HikingTour).scalar_subquery()
    geometry = cast(func.coalesce(route, waypoints), Geography)
    distance = func.ST_Distance(geometry, point)
    return db.scalars(select(HikingTour).where(
        HikingTour.tenant_id == stored_file.tenant_id,
        HikingTour.tour_date == capture_date(stored_file),
        func.ST_DWithin(geometry, point, MATCH_RADIUS_M),
    ).order_by(distance, HikingTour.id).limit(1)).first()


def sync_photos_for_tours(db, tenant_id, *, file_ids=None):
    """Beide Richtungen verwenden denselben Abgleich; wiederholte Aufrufe sind idempotent."""
    from app.services.photo_album_service import add_items
    db.flush()
    if file_ids is None:
        from app.core.config import settings
        from app.services.file_service import _safe_storage_path, _extract_image_metadata
        # Einmaliges Nachlesen bestehender Fotos, damit neue Touren ältere Uploads finden.
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
    query = select(StoredFile).where(StoredFile.tenant_id == tenant_id, StoredFile.gps_latitude.is_not(None), StoredFile.gps_longitude.is_not(None))
    if file_ids is not None:
        if not file_ids:
            return
        query = query.where(StoredFile.public_id.in_(file_ids))
    albums = list(db.scalars(select(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbum.kind == 'hiking_tour')))
    by_tour = {album.hiking_tour_id: album for album in albums}
    for stored_file in db.scalars(query):
        tour = find_matching_tour(db, stored_file)
        for album in albums:
            if tour is None or album.hiking_tour_id != tour.id:
                db.execute(delete(PhotoAlbumItem).where(PhotoAlbumItem.album_id == album.id, PhotoAlbumItem.file_id == stored_file.public_id))
        if tour is None:
            continue
        album = by_tour.get(tour.id)
        if album is None:
            db.execute(insert(PhotoAlbum).values(tenant_id=tenant_id, name=tour.title, kind='hiking_tour', hiking_tour_id=tour.id).on_conflict_do_nothing())
            album = db.scalars(select(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbum.hiking_tour_id == tour.id)).one()
            by_tour[tour.id] = album
            albums.append(album)
        album.name = tour.title
        add_items(db, album, [stored_file.public_id])
    # Auch leere Alben behalten bei einer Umbenennung den aktuellen Tournamen.
    for album, title in db.execute(select(PhotoAlbum, HikingTour.title).join(HikingTour, HikingTour.id == PhotoAlbum.hiking_tour_id).where(PhotoAlbum.tenant_id == tenant_id)):
        album.name = title
    db.flush()


def attach_tour_context(db, items):
    if not items:
        return
    by_id = {item.id: item for item in items}
    rows = db.execute(select(PhotoAlbumItem.file_id, HikingTour.public_id, HikingTour.title)
        .join(PhotoAlbum, PhotoAlbum.id == PhotoAlbumItem.album_id)
        .join(HikingTour, HikingTour.id == PhotoAlbum.hiking_tour_id)
        .where(PhotoAlbum.kind == 'hiking_tour', PhotoAlbumItem.file_id.in_(by_id)))
    for file_id, tour_id, title in rows:
        by_id[file_id].hiking_tour_id = tour_id
        by_id[file_id].hiking_tour_title = title
