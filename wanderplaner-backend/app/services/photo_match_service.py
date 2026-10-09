"""Ordnet hocX-Fotos anhand von GPS-Position und Aufnahmedatum einer Tour zu.

Die Fotos selbst bleiben in hocX; hocX schickt nur Koordinaten und Datum (siehe
photo_tour_link_service.py im hocX-Backend). Eine Tour passt, wenn das Foto am Tourdatum
hoechstens MATCH_RADIUS_M neben der berechneten Route liegt - oder, solange noch keine Route
berechnet ist, neben einem der Wegpunkte (keine erfundene Luftlinie dazwischen)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.models import HikingTour, HikingTourRouteLeg, HikingTourWaypoint

# Toleranz für GPS-Ungenauigkeit und kurze Abstecher neben dem Wanderweg.
MATCH_RADIUS_M = 150


@dataclass(frozen=True)
class PhotoPosition:
    file_id: uuid.UUID
    lat: float
    lon: float
    taken_on: date


def find_matching_tour(db: Session, tenant_id: int, photo: PhotoPosition) -> HikingTour | None:
    point = cast(func.ST_SetSRID(func.ST_MakePoint(photo.lon, photo.lat), 4326), Geography)
    route = select(func.ST_Collect(HikingTourRouteLeg.geom)).where(
        HikingTourRouteLeg.hiking_tour_id == HikingTour.id
    ).correlate(HikingTour).scalar_subquery()
    waypoints = select(func.ST_Collect(HikingTourWaypoint.point)).where(
        HikingTourWaypoint.hiking_tour_id == HikingTour.id
    ).correlate(HikingTour).scalar_subquery()
    geometry = cast(func.coalesce(route, waypoints), Geography)
    distance = func.ST_Distance(geometry, point)
    return db.scalars(select(HikingTour).where(
        HikingTour.tenant_id == tenant_id,
        HikingTour.tour_date == photo.taken_on,
        func.ST_DWithin(geometry, point, MATCH_RADIUS_M),
    ).order_by(distance, HikingTour.id).limit(1)).first()


def match_photos(db: Session, tenant_id: int, photos: list[PhotoPosition]) -> tuple[list[HikingTour], dict[uuid.UUID, HikingTour]]:
    """Alle Touren des Mandanten (fuer Albumnamen und das Entfernen verwaister Alben) plus
    die Zuordnung Foto -> Tour. Fotos von Tagen ohne Tour kosten keine Geo-Abfrage."""
    tours = list(db.scalars(select(HikingTour).where(HikingTour.tenant_id == tenant_id).order_by(HikingTour.id)))
    tour_dates = {tour.tour_date for tour in tours if tour.tour_date is not None}
    matches: dict[uuid.UUID, HikingTour] = {}
    for photo in photos:
        if photo.taken_on not in tour_dates:
            continue
        tour = find_matching_tour(db, tenant_id, photo)
        if tour is not None:
            matches[photo.file_id] = tour
    return tours, matches
