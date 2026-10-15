"""Gefahreneinschätzung: Geländeanalyse über den swisstopo-Höhendienst (Auftrag
"Gefahreneinschätzung des Weges"). Nutzt fetch_profile() aus elevation_service.py - keine neue
HTTP-Logik, derselbe Redis-Cache - mit drei Abfragen:

1. die Route selbst, aber dicht (etwa alle route_danger.SAMPLE_SPACING_M Meter statt der 200
   Punkte des angezeigten Höhenprofils, sonst würden kurze Steilstufen weggemittelt),
2. und 3. je eine Linie durch die Querpunkte CROSS_SECTION_OFFSET_M links bzw. rechts jedes
   dieser Routenpunkte (route_danger.cross_section_targets()).

Die Querhöhen werden den Routenpunkten über die Lage zugeordnet, nicht über die Distanz entlang
der Querlinie (die in Kurven von der Wegdistanz abweicht). Die Distanzen der dichten Abfrage
liegen auf derselben Skala wie tour.elevation_profile_json (gleiche Linie, siehe
elevation_service.route_coordinates()). Läuft in der Orchestrierung nach dem Höhenprofil, siehe
hiking_tour_planning_service.py::recalculate.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from shapely.geometry import LineString
from sqlalchemy.orm import Session

from app.core.route_danger import (
    SAMPLE_SPACING_M,
    classify_terrain,
    cross_section_targets,
    downhill_cross_slopes,
    merge_with_official_status,
)
from app.core.swiss_coords import lv95_to_wgs84, wgs84_to_lv95
from app.core.waypoint_detection import RoutePoint
from app.models import HikingTour
from app.services import elevation_service
from app.services.elevation_service import MAX_POINTS, ElevationServiceError

# Untergrenze wie das angezeigte Höhenprofil - auch sehr kurze Touren bekommen nicht weniger
# Punkte als bisher.
MIN_SAMPLE_POINTS = 200


class TerrainDangerServiceError(RuntimeError):
    """Geländeanalyse (Querschnitts-Höhendaten) nicht möglich (Auftrag Abschnitt 20) - vom
    Router immer als 422 behandelt, nie als unerwarteter Fehler (siehe hiking_tours.py)."""


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


def sample_count(length_m: float) -> int:
    """Anzahl Höhenpunkte für eine Linie dieser Länge: ein Punkt etwa alle SAMPLE_SPACING_M
    Meter, begrenzt auf [MIN_SAMPLE_POINTS, MAX_POINTS] (sehr lange Touren werden gröber)."""
    return min(MAX_POINTS, max(MIN_SAMPLE_POINTS, math.ceil(length_m / SAMPLE_SPACING_M) + 1))


def _side_samples(targets: list[tuple[float, float]], *, nb_points: int) -> list[tuple[float, float, float]]:
    """Höhen entlang der Linie durch die Querpunkte als (easting, northing, elevation_m)."""
    if len(targets) < 2:
        return []
    coordinates = [(lon, lat) for lat, lon in (lv95_to_wgs84(easting, northing) for easting, northing in targets)]
    profile = elevation_service.fetch_profile(coordinates, nb_points=nb_points)
    return [(*wgs84_to_lv95(p["lat"], p["lon"]), p["elevation_m"]) for p in profile]


class TerrainDangerService:
    """DB-Orchestrierung (Stil wie ElevationProfileService) - die eigentliche Berechnung steckt
    in app/core/route_danger.py."""

    def compute_and_store(self, db: Session, tour: HikingTour, *, commit: bool = True) -> HikingTour:
        if not tour.route_legs:
            raise ValueError("Route muss zuerst berechnet werden, bevor eine Gefahreneinschätzung möglich ist")
        if not tour.elevation_profile_json:
            raise ValueError("Höhenprofil muss zuerst abgerufen werden, bevor eine Gefahreneinschätzung möglich ist")

        coordinates = elevation_service.route_coordinates(tour)
        length_m = LineString([wgs84_to_lv95(lat, lon) for lon, lat in coordinates]).length
        nb_points = sample_count(length_m)
        try:
            profile = elevation_service.fetch_profile(coordinates, nb_points=nb_points)
            centerline = [(*wgs84_to_lv95(p["lat"], p["lon"]), p["elevation_m"]) for p in profile]
            left_targets, right_targets = cross_section_targets([(e, n) for e, n, _ in centerline])
            # Doppelte Dichte auf den Querlinien: deren Länge weicht in Kurven von der Route ab,
            # so liegt trotzdem fast immer ein Messpunkt nahe genug am gewünschten Querpunkt.
            side_points = min(MAX_POINTS, 2 * len(centerline))
            left_samples = _side_samples(left_targets, nb_points=side_points)
            right_samples = _side_samples(right_targets, nb_points=side_points)
        except ElevationServiceError as exc:
            raise TerrainDangerServiceError(str(exc)) from exc

        left_slopes = downhill_cross_slopes(centerline, left_targets, left_samples)
        right_slopes = downhill_cross_slopes(centerline, right_targets, right_samples)
        cross_slopes = [
            max((slope for slope in pair if slope is not None), default=None) for pair in zip(left_slopes, right_slopes)
        ]
        points = [
            RoutePoint(distance_m=p["distance_m"], lat=p["lat"], lon=p["lon"], elevation_m=p["elevation_m"])
            for p in profile
        ]

        terrain_segments = classify_terrain(points, cross_slopes=cross_slopes)
        danger_segments = merge_with_official_status(terrain_segments, _wanderweg_segments(tour))

        tour.terrain_danger_json = [segment.as_dict() for segment in danger_segments]
        tour.terrain_danger_computed_at = datetime.now(UTC)
        db.add(tour)
        if commit:
            db.commit()
        db.refresh(tour)
        return tour
