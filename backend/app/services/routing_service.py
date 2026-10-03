"""Wanderrouting auf dem importierten Wegenetz mit pgRouting.

Wegpunkte werden maximal 150 m auf eine Wegkante projiziert. pgr_withPoints
berechnet auch Teilkanten, damit Start/Ziel mitten auf einem Weg liegen können.
Es gibt keinen Luftlinien-Ersatz für fehlende oder unverbundene Wege.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from shapely.ops import substring
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.routing_cost import ROUTING_PROFILES
from app.models.entities import HikingTour, HikingTourRouteLeg, HikingTourWaypoint


class RoutingError(ValueError):
    """Kein Routing moeglich (Auftrag Abschnitt 20) - vom Router immer als 422 behandelt,
    nie als unerwarteter Fehler (siehe hiking_tours.py)."""


@dataclass
class _LegResult:
    geom: LineString
    distance_m: float
    ascent_m: float
    descent_m: float
    cost: float


MAX_SNAP_DISTANCE_M = 150.0


@dataclass(frozen=True)
class _Snap:
    edge_id: int
    fraction: float
    vertex_id: int | None
    point: tuple[float, float]


def _snap_to_edge(db: Session, *, lon: float, lat: float) -> _Snap | None:
    row = db.execute(text("""
        WITH point AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) AS geom),
        candidates AS (
            SELECT e.*, ST_LineLocatePoint(e.geom, p.geom) AS fraction,
                   ST_Distance(e.geom::geography, p.geom::geography) AS distance_m
            FROM routing_edge e CROSS JOIN point p
            WHERE e.geom && ST_Expand(p.geom, 0.003)
              AND e.source IS NOT NULL AND e.target IS NOT NULL
            ORDER BY distance_m, e.id LIMIT 1
        )
        SELECT id, source, target, fraction, distance_m,
               ST_X(ST_LineInterpolatePoint(geom, fraction)) AS lon,
               ST_Y(ST_LineInterpolatePoint(geom, fraction)) AS lat
        FROM candidates WHERE distance_m <= :max_distance
    """), {"lon": lon, "lat": lat, "max_distance": MAX_SNAP_DISTANCE_M}).first()
    if row is None:
        return None
    vertex = row.source if row.fraction <= 1e-9 else row.target if row.fraction >= 1 - 1e-9 else None
    return _Snap(row.id, row.fraction, vertex, (row.lon, row.lat))


def _route_leg(db: Session, *, profile: str, start: _Snap, end: _Snap) -> _LegResult:
    if start.point == end.point or (start.vertex_id is not None and start.vertex_id == end.vertex_id):
        return _LegResult(LineString([start.point, start.point]), 0.0, 0.0, 0.0, 0.0)
    edges_sql = (
        f"SELECT id, source, target, cost_{profile} AS cost, reverse_cost_{profile} AS reverse_cost "
        "FROM routing_edge ORDER BY id"
    )
    # Nur intern aus DB-Zahlen aufgebaut; keine Benutzereingaben in dynamischem SQL.
    points = [(pid, snap) for pid, snap in ((1, start), (2, end)) if snap.vertex_id is None]
    points_sql = " UNION ALL ".join(
        f"SELECT {pid}::bigint AS pid, {int(snap.edge_id)}::bigint AS edge_id, "
        f"{float(snap.fraction)!r}::float8 AS fraction, 'b'::char AS side"
        for pid, snap in points
    ) or "SELECT 1::bigint AS pid, 1::bigint AS edge_id, 0.5::float8 AS fraction WHERE false"
    rows = db.execute(text("""
        WITH route AS (
            SELECT *, lead(node) OVER (ORDER BY seq) AS next_node
            FROM pgr_withPoints(:edges_sql, :points_sql, CAST(:from_v AS bigint),
                CAST(:to_v AS bigint), directed := true, driving_side := 'b', details := true)
        )
        SELECT r.node, r.next_node, r.cost AS step_cost, e.source, e.target,
               e.geom, e.length_m, e.ascent_m, e.descent_m
        FROM route r JOIN routing_edge e ON e.id = r.edge ORDER BY r.seq
    """), {"edges_sql": edges_sql, "points_sql": points_sql,
           "from_v": start.vertex_id if start.vertex_id is not None else -1,
           "to_v": end.vertex_id if end.vertex_id is not None else -2}).all()
    if not rows:
        raise RoutingError("Kein Routing zwischen diesen Punkten möglich: Wegenetz nicht verbunden")
    coords: list[tuple[float, float]] = []
    distance_m = ascent_m = descent_m = cost = 0.0
    fractions = {-1: start.fraction, -2: end.fraction}
    for row in rows:
        frm = fractions[row.node] if row.node < 0 else 0.0 if row.node == row.source else 1.0
        to = fractions[row.next_node] if row.next_node < 0 else 0.0 if row.next_node == row.source else 1.0
        line = to_shape(WKBElement(row.geom, srid=4326, extended=True))
        segment = substring(line, frm, to, normalized=True)
        points_on_edge = list(segment.coords)
        if coords and points_on_edge and coords[-1] == points_on_edge[0]:
            points_on_edge = points_on_edge[1:]
        coords.extend(points_on_edge)
        proportion = abs(to - frm)
        distance_m += row.length_m * proportion
        ascent_m += (row.ascent_m if to >= frm else row.descent_m) * proportion
        descent_m += (row.descent_m if to >= frm else row.ascent_m) * proportion
        cost += row.step_cost
    if len(coords) < 2:
        raise RoutingError("Keine gültige Weggeometrie zwischen diesen Punkten gefunden")
    return _LegResult(LineString(coords), distance_m, ascent_m, descent_m, cost)


class RoutingService:
    def compute_route(self, db: Session, tour: HikingTour, *, profile: str) -> HikingTour:
        if profile not in ROUTING_PROFILES:
            raise ValueError(f"Unknown routing profile: {profile}")
        # EMERGENCY_EXIT-Wegpunkte (Phase 4) sind ein Abstecher abseits der Route, keine
        # Kettenglieder zwischen Start und Ziel - siehe march_time_service.py fuer denselben
        # Filter und die Begruendung.
        waypoints: list[HikingTourWaypoint] = [wp for wp in tour.waypoints if wp.kind != "EMERGENCY_EXIT"]
        if len(waypoints) < 2:
            raise RoutingError("Tour braucht mindestens Start und Ziel für eine Route")

        snaps: list[_Snap] = []
        for waypoint in waypoints:
            point: Point = to_shape(waypoint.point)
            snap = _snap_to_edge(db, lon=point.x, lat=point.y)
            if snap is None:
                raise RoutingError(
                    f"Kein begehbarer Weg innerhalb von {MAX_SNAP_DISTANCE_M:g} m bei Wegpunkt {waypoint.sequence} "
                    f"({waypoint.label or waypoint.kind}) gefunden"
                )
            snaps.append(snap)

        legs: list[_LegResult] = []
        for index in range(len(waypoints) - 1):
            try:
                legs.append(_route_leg(db, profile=profile, start=snaps[index], end=snaps[index + 1]))
            except RoutingError as exc:
                frm, to = waypoints[index], waypoints[index + 1]
                raise RoutingError(
                    f"{exc} (zwischen Wegpunkt {frm.sequence} und {to.sequence})"
                ) from exc

        db.query(HikingTourRouteLeg).filter(HikingTourRouteLeg.hiking_tour_id == tour.id).delete()
        # route_legs hat kein back_populates auf HikingTourRouteLeg - die Bulk-.delete()-Query
        # oben aktualisiert das bereits geladene tour.route_legs deshalb NICHT automatisch.
        # Ohne dieses expire() haelt tour.route_legs weiter auf jetzt geloeschte Instanzen,
        # und ein erneutes db.add(tour) im selben compute_route()-Aufruf auf derselben Tour
        # schlaegt fehl ("Instance has been deleted").
        db.expire(tour, ["route_legs"])
        db.flush()

        network_version_id = db.scalar(text("SELECT max(id) FROM routing_network_meta"))
        total_distance = total_ascent = total_descent = total_cost = 0.0
        for index, leg in enumerate(legs):
            db.add(
                HikingTourRouteLeg(
                    hiking_tour_id=tour.id,
                    from_waypoint_id=waypoints[index].id,
                    to_waypoint_id=waypoints[index + 1].id,
                    sequence=waypoints[index].sequence,
                    geom=from_shape(leg.geom, srid=4326),
                    distance_m=leg.distance_m,
                    ascent_m=leg.ascent_m,
                    descent_m=leg.descent_m,
                    cost=leg.cost,
                    routing_profile=profile,
                    network_version_id=network_version_id,
                )
            )
            total_distance += leg.distance_m
            total_ascent += leg.ascent_m
            total_descent += leg.descent_m
            total_cost += leg.cost

        # Das alte Höhenprofil gehört zur vorherigen Geometrie.
        tour.elevation_profile_json = None
        tour.elevation_profile_fetched_at = None
        for waypoint in waypoints:
            waypoint.elevation_m = None
        tour.routing_profile = profile
        tour.route_distance_m = total_distance
        tour.route_ascent_m = total_ascent
        tour.route_descent_m = total_descent
        tour.route_cost = total_cost
        tour.route_computed_at = datetime.now(UTC)
        db.add(tour)
        db.flush()
        from app.services.photo_tour_link_service import sync_photos_for_tours
        sync_photos_for_tours(db, tour.tenant_id)
        db.commit()
        db.refresh(tour)
        return tour
