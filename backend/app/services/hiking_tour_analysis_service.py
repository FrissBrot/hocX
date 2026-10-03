"""Lokale Touranalyse: markante OSM-Orte statt geometrischer Kurven.

Verzweigungen, Querungen und Hütten werden anhand der Marschzeit ausgedünnt.
Die Umgebungsabfrage bleibt vollständig in der lokalen Datenbank.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from shapely.ops import substring
from sqlalchemy.orm import Session

from app.core.break_planning import MarchTableRow, suggest_breaks
from app.core.decision_points import DecisionRow, ExitCandidate, compute_decision_metrics
from app.core.march_time import resolve_speed_factor_kmh
from app.core.waypoint_detection import RoutePoint, detect_climb_segments
from app.core.route_landmarks import find_landmarks, select_landmarks
from app.core.swiss_coords import wgs84_to_lv95
from app.services.route_landmark_service import RouteLandmarkService
from app.models.entities import HikingTour, HikingTourWaypoint, HikingTourRouteLeg
from app.services.elevation_service import elevation_at_distance
from app.services.emergency_exit_service import EmergencyExitService
from app.services.march_time_service import MarchTimeService

# Damit reine Sequence-Neunummerierungen nie mit einer noch gueltigen alten Sequence
# kollidieren (UNIQUE(hiking_tour_id, sequence)) - hoch genug fuer jede realistische Tour.
_RENUMBER_OFFSET = 100_000
# Eigener Sequence-Namensraum fuer EMERGENCY_EXIT-Wegpunkte (ausserhalb der Kette, siehe
# Moduldocstring) - sie teilen die UNIQUE(hiking_tour_id, sequence)-Constraint mit den
# Ketten-Wegpunkten, brauchen aber keine fortlaufende Position darin. Weit genug ueber
# _RENUMBER_OFFSET, damit beide Namensraeume sich nie ueberschneiden koennen.
_EXIT_SEQUENCE_OFFSET = 500_000


def _make_point(lat: float, lon: float):
    return from_shape(Point(lon, lat), srid=4326)


def _cumulative_distances(waypoints: list[HikingTourWaypoint], legs) -> dict[int, float]:
    distances: dict[int, float] = {}
    cumulative = 0.0
    for index, waypoint in enumerate(waypoints):
        if index > 0:
            cumulative += legs[index - 1].distance_m
        distances[waypoint.id] = cumulative
    return distances


class HikingTourAnalysisService:
    def __init__(
        self,
        *,
        march_time_service: MarchTimeService | None = None,
        emergency_exit_service: EmergencyExitService | None = None,
        landmark_service: RouteLandmarkService | None = None,
    ) -> None:
        self.landmark_service = landmark_service or RouteLandmarkService()
        self.march_time_service = march_time_service or MarchTimeService()
        self.emergency_exit_service = emergency_exit_service or EmergencyExitService()

    def analyze(self, db: Session, tour: HikingTour) -> HikingTour:
        if not tour.route_legs:
            raise ValueError("Route muss zuerst berechnet werden, bevor eine automatische Analyse möglich ist")
        if not tour.elevation_profile_json:
            raise ValueError("Höhenprofil muss zuerst abgerufen werden, bevor eine automatische Analyse möglich ist")

        coordinates = [coordinate[:2] for leg in tour.route_legs for coordinate in to_shape(leg.geom).coords]
        # Erst Datenverfügbarkeit prüfen, bevor vorhandene automatische Punkte entfernt werden.
        elements = self.landmark_service.fetch(db, coordinates)

        original_chain = [wp for wp in tour.waypoints if wp.kind != "EMERGENCY_EXIT"]
        original_legs = list(tour.route_legs)
        original_distances = _cumulative_distances(original_chain, original_legs)
        # Geometrien und Kennzahlen vor dem Entfernen der alten Automatik sichern.
        snapshots = [(to_shape(leg.geom), leg.distance_m, leg.ascent_m, leg.descent_m,
                      leg.cost, leg.network_version_id) for leg in original_legs]
        self._remove_previous_auto_waypoints(db, tour)

        elevation_points = [
            RoutePoint(distance_m=p["distance_m"], lat=p["lat"], lon=p["lon"], elevation_m=p["elevation_m"])
            for p in tour.elevation_profile_json
        ]
        chain_waypoints = [wp for wp in tour.waypoints if wp.kind != "EMERGENCY_EXIT"]
        distances = {wp.id: original_distances[wp.id] for wp in chain_waypoints}
        for waypoint in chain_waypoints:
            if not waypoint.label:
                point = to_shape(waypoint.point)
                waypoint.label = self.landmark_service.nearest_name(db, point.y, point.x)
        existing_distances = set(distances.values())

        speed = resolve_speed_factor_kmh(group_type=tour.group_type, luggage_type=tour.luggage_type,
            override_kmh=float(tour.speed_factor_kmh) if tour.speed_factor_kmh is not None else None)
        candidates = find_landmarks(coordinates, elements)
        route_length = LineString([wgs84_to_lv95(lat, lon) for lon, lat in coordinates]).length
        ratio = sum(snapshot[1] for snapshot in snapshots) / route_length if route_length else 1
        candidates = [replace(c, distance_m=c.distance_m * ratio) for c in candidates]
        selected = select_landmarks(candidates, elevation_points, speed, existing_distances,
            [wp.label for wp in chain_waypoints if wp.label])
        new_points = [(p.distance_m, p.lat, p.lon, p.kind, p.label, p.description, "AUTO_DETECTED") for p in selected]

        ordered_distances = self._insert_waypoints(db, tour, chain_waypoints, new_points, distances)
        db.flush()
        db.expire(tour, ["waypoints", "route_legs"])
        self._resplit_route(db, tour, snapshots, ordered_distances)

        self._suggest_breaks_and_decision_metrics(db, tour)

        if tour.status == "draft":
            tour.status = "analyzed"
        db.add(tour)
        db.commit()
        db.refresh(tour)
        return tour

    def _remove_previous_auto_waypoints(self, db: Session, tour: HikingTour) -> None:
        for waypoint in list(tour.waypoints):
            if waypoint.auto_generated:
                db.delete(waypoint)
        db.flush()
        db.expire(tour, ["waypoints"])

    def _insert_waypoints(
        self,
        db: Session,
        tour: HikingTour,
        chain_waypoints: list[HikingTourWaypoint],
        new_points: list[tuple[float, float, float, str, str | None, str | None, str | None]],
        distances: dict[int, float],
    ) -> list[float]:
        existing_ordered = [(distances[wp.id], "EXISTING", wp) for wp in chain_waypoints]
        combined: list[tuple[float, str, object]] = existing_ordered + [(p[0], "NEW", p) for p in new_points]
        combined.sort(key=lambda item: item[0])

        # Erst alle bestehenden Sequenzen kollisionsfrei verschieben, dann final durchnummerieren
        # - vermeidet UNIQUE(hiking_tour_id, sequence)-Konflikte unabhaengig von der Reihenfolge.
        for waypoint in chain_waypoints:
            waypoint.sequence += _RENUMBER_OFFSET
            db.add(waypoint)
        db.flush()

        for index, (_, kind_marker, payload) in enumerate(combined):
            if kind_marker == "EXISTING":
                payload.sequence = index
                db.add(payload)
            else:
                distance_m, lat, lon, kind, label, description, verification_status = payload
                db.add(
                    HikingTourWaypoint(
                        hiking_tour_id=tour.id,
                        sequence=index,
                        kind=kind,
                        label=label,
                        description=description,
                        point=_make_point(lat, lon),
                        auto_generated=True,
                        verification_status=verification_status,
                    )
                )
        db.flush()

        return [item[0] for item in combined]

    def _resplit_route(self, db, tour, snapshots, distances):
        """Bestehende Route nur aufteilen; kein Neurouting und kein externer Höhenabruf."""
        db.query(HikingTourRouteLeg).filter(HikingTourRouteLeg.hiking_tour_id == tour.id).delete()
        db.expire(tour, ["route_legs"])
        chain = [wp for wp in tour.waypoints if wp.kind != "EMERGENCY_EXIT"]
        for waypoint, distance in zip(chain, distances):
            waypoint.elevation_m = elevation_at_distance(tour.elevation_profile_json, distance)
        for i, (start, end) in enumerate(zip(distances, distances[1:])):
            coordinates, ascent, descent, cost = [], 0.0, 0.0, 0.0
            offset = 0.0
            network_version = None
            for geometry, length, up, down, old_cost, version in snapshots:
                lo, hi = max(start, offset), min(end, offset+length)
                if hi > lo and length > 0:
                    part = substring(geometry, (lo-offset)/length, (hi-offset)/length, normalized=True)
                    points = list(part.coords)
                    coordinates.extend(points[1:] if coordinates and points[0] == coordinates[-1] else points)
                    fraction = (hi-lo)/length
                    ascent += up*fraction
                    descent += down*fraction
                    cost += old_cost*fraction
                    network_version = version
                offset += length
            if len(coordinates) < 2:
                point = to_shape(chain[i].point)
                coordinates = [(point.x, point.y)]*2
            db.add(HikingTourRouteLeg(hiking_tour_id=tour.id, from_waypoint_id=chain[i].id,
                to_waypoint_id=chain[i+1].id, sequence=chain[i].sequence,
                geom=from_shape(LineString(coordinates), srid=4326), distance_m=end-start,
                ascent_m=ascent, descent_m=descent, cost=cost,
                routing_profile=tour.routing_profile or "wanderwege_bevorzugen", network_version_id=network_version))
        tour.route_computed_at = datetime.now(UTC)
        db.flush()
        db.expire(tour, ["route_legs"])

    def _suggest_breaks_and_decision_metrics(self, db: Session, tour: HikingTour) -> None:
        table = self.march_time_service.build_table(tour)
        elevation_points = [
            RoutePoint(distance_m=p["distance_m"], lat=p["lat"], lon=p["lon"], elevation_m=p["elevation_m"])
            for p in (tour.elevation_profile_json or [])
        ]
        climb_segments = detect_climb_segments(elevation_points)

        rows: list[MarchTableRow] = []
        decision_rows: dict[int, DecisionRow] = {}
        cumulative_ascent = cumulative_descent = 0.0
        for entry in table.entries:
            cumulative_ascent += entry.segment_ascent_m
            cumulative_descent += entry.segment_descent_m
            rows.append(
                MarchTableRow(
                    sequence=entry.sequence,
                    cumulative_distance_m=entry.cumulative_distance_m,
                    cumulative_ascent_m=cumulative_ascent,
                    cumulative_duration_minutes=entry.cumulative_duration_minutes,
                )
            )
            decision_rows[entry.sequence] = DecisionRow(
                sequence=entry.sequence,
                cumulative_distance_m=entry.cumulative_distance_m,
                cumulative_ascent_m=cumulative_ascent,
                cumulative_descent_m=cumulative_descent,
                cumulative_duration_minutes=entry.cumulative_duration_minutes,
            )

        chain_waypoints_by_seq = {wp.sequence: wp for wp in tour.waypoints if wp.kind != "EMERGENCY_EXIT"}

        break_suggestions = suggest_breaks(
            rows=rows, climb_segments=climb_segments, elevation_points=elevation_points, total_duration_minutes=table.summary.total_duration_minutes
        )
        for suggestion in break_suggestions:
            waypoint = chain_waypoints_by_seq.get(suggestion.after_sequence)
            if waypoint is None or waypoint.kind in ("START", "END"):
                continue
            waypoint.break_minutes = suggestion.minutes
            waypoint.break_reason = suggestion.reason
            if waypoint.kind == "NAVIGATION":
                waypoint.kind = "BREAK"
            db.add(waypoint)

        speed_factor = resolve_speed_factor_kmh(
            group_type=tour.group_type,
            luggage_type=tour.luggage_type,
            override_kmh=float(tour.speed_factor_kmh) if tour.speed_factor_kmh is not None else None,
        )
        profile = tour.routing_profile or "wanderwege_bevorzugen"

        for waypoint in tour.waypoints:
            if waypoint.kind != "DECISION" or not waypoint.auto_generated:
                continue
            row = decision_rows.get(waypoint.sequence)
            if row is None:
                continue
            point = to_shape(waypoint.point)
            finding = self.emergency_exit_service.find_exit(db, lat=point.y, lon=point.x, profile=profile, speed_factor_kmh=speed_factor)
            exit_candidate = None
            if finding is not None:
                exit_waypoint = HikingTourWaypoint(
                    hiking_tour_id=tour.id,
                    sequence=_EXIT_SEQUENCE_OFFSET + waypoint.sequence,  # eigener Namensraum, siehe Konstante
                    kind="EMERGENCY_EXIT",
                    label=self.landmark_service.nearest_name(db, finding.exit_lat, finding.exit_lon),
                    description="Potenzieller Fahrzeug-Ausstieg – vor der Tour prüfen.",
                    point=_make_point(finding.exit_lat, finding.exit_lon),
                    auto_generated=True,
                    verification_status="AUTO_DETECTED",
                    exit_metrics_json={
                        "source_sequence": waypoint.sequence,
                        "distance_m": finding.distance_m,
                        "ascent_m": finding.ascent_m,
                        "descent_m": finding.descent_m,
                        "time_to_exit_minutes": finding.time_to_exit_minutes,
                    },
                )
                db.add(exit_waypoint)
                exit_candidate = ExitCandidate(
                    waypoint_label=exit_waypoint.label,
                    distance_from_route_m=finding.distance_m,
                    time_to_exit_minutes=finding.time_to_exit_minutes,
                )

            metrics = compute_decision_metrics(row=row, total_duration_minutes=table.summary.total_duration_minutes, speed_factor_kmh=speed_factor, nearest_exit=exit_candidate)
            waypoint.decision_metrics_json = {
                "time_from_start_minutes": metrics.time_from_start_minutes,
                "time_to_end_minutes": metrics.time_to_end_minutes,
                "time_back_minutes": metrics.time_back_minutes,
                "nearest_exit_label": metrics.nearest_exit_label,
                "time_to_exit_minutes": metrics.time_to_exit_minutes,
                "distance_to_exit_m": metrics.distance_to_exit_m,
            }
            db.add(waypoint)

        db.flush()
