"""Gefahreneinschätzung: Geländeanalyse über den swisstopo-Höhendienst (Auftrag
"Gefahreneinschätzung des Weges"). Ruft fetch_profile() aus elevation_service.py zusätzlich für
zwei um CROSS_SECTION_OFFSET_M nach links/rechts versetzte Parallellinien auf - keine neue
HTTP-Logik, kein neuer Cache-Mechanismus, exakt dieselbe Funktion/Redis-Cache-Strategie wie das
Höhenprofil selbst, nur mit anderer Geometrie. Braucht ein bereits abgerufenes Höhenprofil
(tour.elevation_profile_json), läuft deshalb in der Orchestrierung immer danach, siehe
hiking_tour_planning_service.py::recalculate.
"""

from __future__ import annotations

from datetime import UTC, datetime

import shapely
from geoalchemy2.shape import to_shape
from shapely.geometry import LineString
from sqlalchemy.orm import Session

from app.core.route_danger import classify_terrain, merge_with_official_status
from app.core.swiss_coords import lv95_to_wgs84, wgs84_to_lv95
from app.core.waypoint_detection import RoutePoint
from app.models import HikingTour
from app.services import elevation_service
from app.services.elevation_service import ElevationServiceError

# Muss mit route_danger.CROSS_SECTION_OFFSET_M übereinstimmen (dort die Gelände-Schwelle fürs
# Quergefälle, hier der tatsächliche Versatz der Querschnittslinie).
CROSS_SECTION_OFFSET_M = 15.0


class TerrainDangerServiceError(RuntimeError):
    """Geländeanalyse (Querschnitts-Höhendaten) nicht möglich (Auftrag Abschnitt 20) - vom
    Router immer als 422 behandelt, nie als unerwarteter Fehler (siehe hiking_tours.py)."""


def _concatenated_lv95_line(tour: HikingTour) -> LineString:
    coordinates = [coordinate[:2] for leg in tour.route_legs for coordinate in to_shape(leg.geom).coords]
    return LineString([wgs84_to_lv95(lat, lon) for lon, lat in coordinates])


def _wanderweg_segments(tour: HikingTour) -> list[dict]:
    """Leg-relative wanderweg_segments_json auf tourweite (kumulierte) Distanz verschoben -
    gleiche Kumulierung wie die Höhenprofil-/Marschzeit-Distanz, siehe
    hiking_tour_analysis_service.py::_cumulative_distances."""
    segments: list[dict] = []
    cumulative = 0.0
    for leg in tour.route_legs:
        for segment in leg.wanderweg_segments_json or []:
            segments.append({
                "from_m": cumulative + segment["from_m"],
                "to_m": cumulative + segment["to_m"],
                "status": segment["status"],
            })
        cumulative += leg.distance_m
    return segments


def _offset_profile(line_lv95: LineString, *, side: float) -> list[dict] | None:
    """Höhenprofil einer um `side` Meter versetzten Parallellinie (positiv = links, negativ =
    rechts der Wegrichtung). None, wenn das Offsetting selbst keine brauchbare einfache Linie
    liefert (z. B. sehr enge Krümmung im Wegverlauf) - ein bewusst begrenzter Fallback auf
    "für diese Seite keine Quergefälle-Daten" (siehe route_danger._cross_slope_percent), kein
    verschluckter Dienstausfall: ein echter ElevationServiceError aus fetch_profile() läuft
    hier unverändert durch und wird vom Aufrufer behandelt."""
    try:
        offset = shapely.offset_curve(line_lv95, side)
    except Exception:
        return None
    if offset.is_empty or offset.geom_type != "LineString" or len(offset.coords) < 2:
        return None
    coordinates = [(lon, lat) for lat, lon in (lv95_to_wgs84(easting, northing) for easting, northing in offset.coords)]
    return elevation_service.fetch_profile(coordinates)


class TerrainDangerService:
    """DB-Orchestrierung (Stil wie ElevationProfileService) - die eigentliche Berechnung steckt
    in den modulweiten Funktionen oben, analog fetch_profile()/elevation_at_distance()."""

    def compute_and_store(self, db: Session, tour: HikingTour, *, commit: bool = True) -> HikingTour:
        if not tour.route_legs:
            raise ValueError("Route muss zuerst berechnet werden, bevor eine Gefahreneinschätzung möglich ist")
        if not tour.elevation_profile_json:
            raise ValueError("Höhenprofil muss zuerst abgerufen werden, bevor eine Gefahreneinschätzung möglich ist")

        points = [
            RoutePoint(distance_m=p["distance_m"], lat=p["lat"], lon=p["lon"], elevation_m=p["elevation_m"])
            for p in tour.elevation_profile_json
        ]
        line = _concatenated_lv95_line(tour)
        try:
            left_profile = _offset_profile(line, side=CROSS_SECTION_OFFSET_M) or []
            right_profile = _offset_profile(line, side=-CROSS_SECTION_OFFSET_M) or []
        except ElevationServiceError as exc:
            raise TerrainDangerServiceError(str(exc)) from exc

        terrain_segments = classify_terrain(points, left_profile=left_profile, right_profile=right_profile)
        danger_segments = merge_with_official_status(terrain_segments, _wanderweg_segments(tour))

        tour.terrain_danger_json = [segment.as_dict() for segment in danger_segments]
        tour.terrain_danger_computed_at = datetime.now(UTC)
        db.add(tour)
        if commit:
            db.commit()
        db.refresh(tour)
        return tour
