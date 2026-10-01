"""Automatische Tour-Analyse (Auftrag Abschnitt 7-11, Phase 4): erkennt zusaetzliche
Wegpunkte (Richtungsaenderungen, Beginn/Ende langer Aufstiege), schlaegt Pausen vor,
platziert Entscheidungspunkte mit Kennzahlen (inkl. naechstem Notausstieg) und sucht potenzielle
Fahrzeug-Ausstiege. Reine Orchestrierung: die eigentlichen Algorithmen leben DB-frei in
app/core/waypoint_detection.py, break_planning.py, decision_points.py - dieser Service
uebersetzt ihre Ergebnisse in HikingTourWaypoint-Zeilen und ruft RoutingService/
ElevationProfileService fuer die dadurch noetige Neuberechnung.

Ablauf (ein Aufruf von analyze()):
1. Aus dem bereits abgerufenen Hoehenprofil (Phase 3) Richtungsaenderungen und
   Aufstiegsabschnitte erkennen (NAVIGATION-Wegpunkte) sowie Entscheidungspunkte platzieren
   (DECISION-Wegpunkte) - beides bezogen auf die noch unveraenderte Route.
2. Alle neuen Punkte einfuegen (Sequence neu durchnummeriert), Route NEU berechnen (das
   spaltet jedes betroffene Leg an den neuen Punkten auf) und das Hoehenprofil erneut abrufen
   (identische Routengeometrie -> Redis-Cache-Treffer, kein echter Netzwerkaufruf).
3. Mit der jetzt aktuellen Marschzeittabelle: Pausenvorschlaege (auf bestehende/neue Zeilen
   angewendet) und je Entscheidungspunkt eine Ausstiegssuche (EMERGENCY_EXIT-Wegpunkte,
   ABSEITS der Wegpunktkette - siehe routing_service.py/march_time_service.py fuer den
   Filter, der sie von der linearen Route ausschliesst - ein Abstecher zu einer Strasse ist
   kein Teil der geplanten Wanderung selbst).

Ein erneuter Aufruf ist idempotent: alle zuvor automatisch erzeugten Punkte werden zuerst
entfernt und neu berechnet, nie dupliziert."""

from __future__ import annotations

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy.orm import Session

from app.core.break_planning import MarchTableRow, suggest_breaks
from app.core.decision_points import DecisionRow, ExitCandidate, compute_decision_metrics, find_decision_candidates
from app.core.march_time import resolve_speed_factor_kmh
from app.core.waypoint_detection import RoutePoint, detect_climb_segments, detect_direction_changes
from app.models.entities import HikingTour, HikingTourWaypoint
from app.services.elevation_service import ElevationProfileService
from app.services.emergency_exit_service import EmergencyExitService
from app.services.march_time_service import MarchTimeService
from app.services.routing_service import RoutingService

# Neue Punkte naeher als das an einem bereits vorhandenen Wegpunkt werden verworfen (Auftrag:
# "Nicht jeder kleine Richtungswechsel darf einen Wegpunkt erzeugen" - gilt sinngemaess auch
# fuers Vermeiden von Wegpunkt-Duplikaten dicht nebeneinander).
MIN_GAP_TO_EXISTING_M = 150.0

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
        routing_service: RoutingService | None = None,
        elevation_service: ElevationProfileService | None = None,
        march_time_service: MarchTimeService | None = None,
        emergency_exit_service: EmergencyExitService | None = None,
    ) -> None:
        self.routing_service = routing_service or RoutingService()
        self.elevation_service = elevation_service or ElevationProfileService()
        self.march_time_service = march_time_service or MarchTimeService()
        self.emergency_exit_service = emergency_exit_service or EmergencyExitService()

    def analyze(self, db: Session, tour: HikingTour) -> HikingTour:
        if not tour.route_legs:
            raise ValueError("Route muss zuerst berechnet werden, bevor eine automatische Analyse möglich ist")
        if not tour.elevation_profile_json:
            raise ValueError("Höhenprofil muss zuerst abgerufen werden, bevor eine automatische Analyse möglich ist")

        had_auto_waypoints = any(wp.auto_generated for wp in tour.waypoints)
        self._remove_previous_auto_waypoints(db, tour)
        if had_auto_waypoints:
            # Entfernte automatische Punkte hinterlassen sonst alte Teilstrecken:
            # deren Distanzen passen nicht zur verbleibenden Wegpunktkette und
            # können neue Analysepunkte sogar hinter das Ziel einsortieren.
            db.expire(tour, ["route_legs"])
            tour = self.routing_service.compute_route(db, tour, profile=tour.routing_profile or "wanderwege_bevorzugen")
            tour = self.elevation_service.fetch_and_store(db, tour)

        elevation_points = [
            RoutePoint(distance_m=p["distance_m"], lat=p["lat"], lon=p["lon"], elevation_m=p["elevation_m"])
            for p in tour.elevation_profile_json
        ]
        chain_waypoints = [wp for wp in tour.waypoints if wp.kind != "EMERGENCY_EXIT"]
        legs = list(tour.route_legs)
        existing_distances = set(_cumulative_distances(chain_waypoints, legs).values())

        direction_changes = detect_direction_changes(elevation_points)
        climb_segments = detect_climb_segments(elevation_points)
        decision_candidates = find_decision_candidates(climb_segments=climb_segments, elevation_points=elevation_points)

        new_points: list[tuple[float, float, float, str, str, str | None, str | None]] = []
        # (distance_m, lat, lon, kind, label, description, verification_status)

        def too_close(distance_m: float, kind: str) -> bool:
            # Nur gegen bestehende Wegpunkte und bereits eingeplante Punkte DERSELBEN Art
            # abgleichen: ein Entscheidungspunkt darf durchaus an derselben Stelle wie eine
            # erkannte Richtungsaenderung liegen (unterschiedliche Information), aber zwei
            # NAVIGATION-Punkte oder zwei DECISION-Punkte dicht nebeneinander waeren
            # redundante Wegpunkt-Haeufung (Auftrag: "Nicht jeder kleine Richtungswechsel
            # darf einen Wegpunkt erzeugen").
            if any(abs(distance_m - d) < MIN_GAP_TO_EXISTING_M for d in existing_distances):
                return True
            return any(
                abs(distance_m - existing[0]) < MIN_GAP_TO_EXISTING_M for existing in new_points if existing[3] == kind
            )

        for change in direction_changes:
            if too_close(change.distance_m, "NAVIGATION"):
                continue
            new_points.append(
                (
                    change.distance_m,
                    change.lat,
                    change.lon,
                    "NAVIGATION",
                    "Richtungsänderung",
                    f"Automatisch erkannt: Richtungsänderung um {round(change.bearing_change_deg)}°.",
                    None,
                )
            )

        for segment in climb_segments:
            if not too_close(segment.start_distance_m, "NAVIGATION"):
                new_points.append(
                    (
                        segment.start_distance_m,
                        segment.start_lat,
                        segment.start_lon,
                        "NAVIGATION",
                        "Beginn Aufstieg",
                        f"Automatisch erkannt: Beginn eines längeren Aufstiegs (ca. {round(segment.ascent_m)} Hm).",
                        None,
                    )
                )
            if not too_close(segment.end_distance_m, "NAVIGATION"):
                new_points.append(
                    (
                        segment.end_distance_m,
                        segment.end_lat,
                        segment.end_lon,
                        "NAVIGATION",
                        "Ende Aufstieg",
                        f"Automatisch erkannt: Ende eines längeren Aufstiegs (ca. {round(segment.ascent_m)} Hm).",
                        None,
                    )
                )

        for candidate in decision_candidates:
            if too_close(candidate.distance_m, "DECISION"):
                continue
            new_points.append(
                (candidate.distance_m, candidate.lat, candidate.lon, "DECISION", candidate.label, candidate.reason, "AUTO_DETECTED")
            )

        if new_points:
            self._insert_waypoints(db, tour, chain_waypoints, new_points)
            db.flush()
            db.expire(tour, ["waypoints"])
            tour = self.routing_service.compute_route(db, tour, profile=tour.routing_profile or "wanderwege_bevorzugen")
            tour = self.elevation_service.fetch_and_store(db, tour)

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
        new_points: list[tuple[float, float, float, str, str, str | None, str | None]],
    ) -> None:
        distances = _cumulative_distances(chain_waypoints, list(tour.route_legs))
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
            waypoint.auto_generated = True
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
                    label="Potenzieller Fahrzeug-Ausstieg",
                    description="Potenzieller Fahrzeug-Ausstieg – vor der Tour prüfen.",
                    point=_make_point(finding.exit_lat, finding.exit_lon),
                    auto_generated=True,
                    verification_status="AUTO_DETECTED",
                    exit_metrics_json={
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
