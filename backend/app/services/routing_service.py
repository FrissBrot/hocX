"""Serverseitiges Wanderrouting (Auftrag Abschnitt 3) auf dem via
scripts/import_routing_network.py importierten Wegenetz (routing_edge +
routing_edge_vertices_pgr, siehe Migration 0098). Berechnet fuer eine Tour die Route
zwischen jedem Paar aufeinanderfolgender Wegpunkte separat (hiking_tour_route_leg) statt
einer einzigen Gesamtgeometrie - das ist die natuerliche Grundlage fuer die
Marschzeittabelle (Phase 3) und dafuer, dass ein spaeter eingefuegter Wegpunkt (Phase 4/5)
nur die beiden angrenzenden Legs neu berechnet statt der ganzen Tour.

pgr_dijkstra statt pgr_astar: bei diesem Kantenumfang (kantonale/landesweite Wanderwege,
keine Millionen Kanten) ist der Performance-Unterschied vernachlaessigbar, pgr_dijkstra ist
die einfachere, besser dokumentierte Funktion. Falls die Netzgroesse das je aendert, ist
das ein reiner Austausch der SQL-Funktion in _run_dijkstra(), keine API-Aenderung.

Punkt-Snapping: der naechste Netzknoten (routing_edge_vertices_pgr), nicht die naechste
Kante mit virtuellem Einfuegepunkt (pgr_withPoints waere praeziser) - bewusst vereinfacht
fuer die erste Ausbaustufe, siehe Wiki-Seite "Wanderplaner" fuer die Begruendung. Bei einem
dichten Wegenetz ist der Unterschied zur echten Position typischerweise wenige Meter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
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


def _nearest_vertex(db: Session, *, lon: float, lat: float) -> int | None:
    row = db.execute(
        text(
            "SELECT id FROM routing_edge_vertices_pgr "
            "ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) LIMIT 1"
        ),
        {"lon": lon, "lat": lat},
    ).first()
    return row[0] if row else None


def _is_reachable(db: Session, *, edges_sql: str, from_vertex: int, to_vertex: int) -> bool:
    return bool(
        db.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pgr_dijkstra(:edges_sql, :from_v, :to_v, true) "
                "WHERE edge = -1 AND node = :to_v)"
            ),
            {"edges_sql": edges_sql, "from_v": from_vertex, "to_v": to_vertex},
        ).scalar()
    )


def _route_leg(db: Session, *, profile: str, from_vertex: int, to_vertex: int) -> _LegResult:
    edges_sql = (
        f"SELECT id, source, target, cost_{profile} AS cost, reverse_cost_{profile} AS reverse_cost "
        "FROM routing_edge"
    )
    if from_vertex == to_vertex:
        return _LegResult(geom=LineString(), distance_m=0.0, ascent_m=0.0, descent_m=0.0, cost=0.0)
    if not _is_reachable(db, edges_sql=edges_sql, from_vertex=from_vertex, to_vertex=to_vertex):
        raise RoutingError("Kein Routing zwischen diesen Punkten möglich")

    rows = db.execute(
        text(
            """
            WITH route AS (
                SELECT * FROM pgr_dijkstra(:edges_sql, :from_v, :to_v, true)
            )
            SELECT
                route.seq,
                route.cost AS step_cost,
                CASE WHEN route.node = e.source THEN e.geom ELSE ST_Reverse(e.geom) END AS oriented_geom,
                CASE WHEN route.node = e.source THEN e.ascent_m ELSE e.descent_m END AS leg_ascent_m,
                CASE WHEN route.node = e.source THEN e.descent_m ELSE e.ascent_m END AS leg_descent_m,
                e.length_m
            FROM route
            JOIN routing_edge e ON e.id = route.edge
            ORDER BY route.seq
            """
        ),
        {"edges_sql": edges_sql, "from_v": from_vertex, "to_v": to_vertex},
    ).all()

    if not rows:
        # from_vertex != to_vertex aber trotzdem keine Kante dazwischen - degenerierter Fall
        # (z.B. beide Punkte snappen auf denselben Knoten trotz unterschiedlicher Ids durch
        # Rundung). Als Nullstrecke behandeln statt eines verwirrenden Fehlers.
        return _LegResult(geom=LineString(), distance_m=0.0, ascent_m=0.0, descent_m=0.0, cost=0.0)

    coords: list[tuple[float, float]] = []
    distance_m = ascent_m = descent_m = cost = 0.0
    for row in rows:
        # Aus rohem text()-SQL kommt die Geometrie als reiner EWKB-Hex-String zurueck (die
        # Column-Typinfo aus dem ORM-Mapping greift hier nicht) - explizit als WKBElement
        # verpacken, bevor to_shape() sie in ein Shapely-Objekt uebersetzt.
        segment = to_shape(WKBElement(row.oriented_geom, srid=4326, extended=True))
        points = list(segment.coords)
        if coords and points and coords[-1] == points[0]:
            points = points[1:]
        coords.extend(points)
        distance_m += row.length_m
        ascent_m += row.leg_ascent_m
        descent_m += row.leg_descent_m
        cost += row.step_cost

    return _LegResult(geom=LineString(coords), distance_m=distance_m, ascent_m=ascent_m, descent_m=descent_m, cost=cost)


class RoutingService:
    def compute_route(self, db: Session, tour: HikingTour, *, profile: str) -> HikingTour:
        if profile not in ROUTING_PROFILES:
            raise ValueError(f"Unknown routing profile: {profile}")
        waypoints: list[HikingTourWaypoint] = list(tour.waypoints)
        if len(waypoints) < 2:
            raise RoutingError("Tour braucht mindestens Start und Ziel für eine Route")

        vertex_ids: list[int] = []
        for waypoint in waypoints:
            point: Point = to_shape(waypoint.point)
            vertex_id = _nearest_vertex(db, lon=point.x, lat=point.y)
            if vertex_id is None:
                raise RoutingError(
                    f"Kein Wegenetz in der Nähe von Wegpunkt {waypoint.sequence} "
                    f"({waypoint.label or waypoint.kind}) gefunden"
                )
            vertex_ids.append(vertex_id)

        legs: list[_LegResult] = []
        for index in range(len(waypoints) - 1):
            try:
                legs.append(_route_leg(db, profile=profile, from_vertex=vertex_ids[index], to_vertex=vertex_ids[index + 1]))
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

        total_distance = total_ascent = total_descent = total_cost = 0.0
        for index, leg in enumerate(legs):
            db.add(
                HikingTourRouteLeg(
                    hiking_tour_id=tour.id,
                    from_waypoint_id=waypoints[index].id,
                    to_waypoint_id=waypoints[index + 1].id,
                    sequence=waypoints[index].sequence,
                    geom=from_shape(leg.geom, srid=4326) if not leg.geom.is_empty else from_shape(
                        LineString([to_shape(waypoints[index].point).coords[0], to_shape(waypoints[index + 1].point).coords[0]]),
                        srid=4326,
                    ),
                    distance_m=leg.distance_m,
                    ascent_m=leg.ascent_m,
                    descent_m=leg.descent_m,
                    cost=leg.cost,
                    routing_profile=profile,
                )
            )
            total_distance += leg.distance_m
            total_ascent += leg.ascent_m
            total_descent += leg.descent_m
            total_cost += leg.cost

        tour.routing_profile = profile
        tour.route_distance_m = total_distance
        tour.route_ascent_m = total_ascent
        tour.route_descent_m = total_descent
        tour.route_cost = total_cost
        tour.route_computed_at = datetime.now(UTC)
        db.add(tour)
        db.commit()
        db.refresh(tour)
        return tour
