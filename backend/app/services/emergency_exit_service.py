"""Automatische Notfall-/Ausstiegspunkt-Suche (Auftrag Abschnitt 10). Sucht ab jedem
Zwischenwegpunkt der Tour (nicht Start/Ziel - die liegen ueblicherweise schon an einem
Parkplatz/einer Strasse) entlang des bestehenden Wegenetzes (dasselbe `routing_edge` wie das
Tourrouting, Migration 0098) nach der naechstgelegenen Kante mit `wegtyp = 'normalstrasse'`.
Das Wegenetz enthaelt Strassenkanten bereits (siehe app/core/routing_cost.py -
"normalstrasse" ist einer der bekannten `wegtyp`-Werte, mit eigenem Kostenfaktor je Profil) -
es braucht dafuer keinen separaten Strassendatensatz.

`pgr_drivingDistance` findet zunaechst GUENSTIGE Ziel-Knoten (nach den ueblichen
Kosten des Tourprofils, nicht Luftlinie) innerhalb eines Kostenlimits; der eigentliche Pfad
(fuer Distanz/Auf-/Abstieg/Marschzeit) wird danach mit `pgr_dijkstra` exakt nachgerechnet -
wie `routing_service._route_leg()`, hier bewusst dupliziert statt importiert (unterschiedliche
Query-Form: dort fester Start/Ziel, hier ein zuvor erst noch zu findendes Ziel).

Liefert ausschliesslich Kandidaten - keine Kante hier erzeugt eine sichere Aussage ueber
Befahrbarkeit, Schranken oder saisonale Sperrung (Auftrag Abschnitt 10: "Behaupte niemals
automatisch..."); das entsprechende Disclaimer-Label setzt die aufrufende Analyse-Service-
Schicht, nicht dieses Modul."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape
from shapely.geometry import Point
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.march_time import leistungskilometer
from app.core.routing_cost import ROUTING_PROFILES

# Kostenobergrenze fuer die Ausstiegssuche (dieselbe Einheit wie routing_edge.cost_<profil> -
# ein Vielfaches der Leistungskilometer, siehe routing_cost.py). Grosszuegig, aber begrenzt,
# damit die Suche auf duennem Wegenetz nicht den ganzen Graphen durchsucht.
DEFAULT_MAX_SEARCH_COST = 20.0


@dataclass(frozen=True)
class ExitFinding:
    from_lat: float
    from_lon: float
    exit_lat: float
    exit_lon: float
    distance_m: float
    ascent_m: float
    descent_m: float
    time_to_exit_minutes: float


def _nearest_vertex(db: Session, *, lon: float, lat: float) -> int | None:
    row = db.execute(
        text(
            "SELECT id FROM routing_edge_vertices_pgr "
            "ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) LIMIT 1"
        ),
        {"lon": lon, "lat": lat},
    ).first()
    return row[0] if row else None


def _nearest_road_vertex(db: Session, *, edges_sql: str, from_vertex: int, max_search_cost: float) -> int | None:
    row = db.execute(
        text(
            """
            WITH local_edges AS (
                SELECT source, target FROM routing_edge
                WHERE wegtyp = 'normalstrasse' AND geom && (
                    SELECT ST_Envelope(ST_Transform(ST_Expand(ST_Transform(the_geom, 2056), :radius_m), 4326))
                    FROM routing_edge_vertices_pgr WHERE id = :from_v
                )
            ), road_vertices AS (
                SELECT source AS vid FROM local_edges WHERE source IS NOT NULL
                UNION
                SELECT target AS vid FROM local_edges WHERE target IS NOT NULL
            ),
            reach AS (
                SELECT node, agg_cost FROM pgr_drivingDistance(:edges_sql, :from_v, :max_cost, true)
            )
            SELECT reach.node
            FROM reach JOIN road_vertices ON road_vertices.vid = reach.node
            WHERE reach.node != :from_v
            ORDER BY reach.agg_cost
            LIMIT 1
            """
        ),
        {"edges_sql": edges_sql, "from_v": from_vertex, "max_cost": max_search_cost,
         "radius_m": max_search_cost * 1000 + 1000},
    ).first()
    return row[0] if row else None


def _shortest_path_metrics(db: Session, *, edges_sql: str, from_vertex: int, to_vertex: int) -> tuple[float, float, float, float, float]:
    """(distance_m, ascent_m, descent_m, exit_lat, exit_lon) entlang des kuerzesten Pfads."""
    rows = db.execute(
        text(
            """
            WITH route AS (
                SELECT * FROM pgr_dijkstra(:edges_sql, :from_v, :to_v, true)
            )
            SELECT
                CASE WHEN route.node = e.source THEN e.ascent_m ELSE e.descent_m END AS leg_ascent_m,
                CASE WHEN route.node = e.source THEN e.descent_m ELSE e.ascent_m END AS leg_descent_m,
                e.length_m,
                CASE WHEN route.node = e.source THEN e.geom ELSE ST_Reverse(e.geom) END AS oriented_geom
            FROM route
            JOIN routing_edge e ON e.id = route.edge
            ORDER BY route.seq
            """
        ),
        {"edges_sql": edges_sql, "from_v": from_vertex, "to_v": to_vertex},
    ).all()

    distance_m = ascent_m = descent_m = 0.0
    exit_point: Point | None = None
    for row in rows:
        distance_m += row.length_m
        ascent_m += row.leg_ascent_m
        descent_m += row.leg_descent_m
        exit_point = to_shape(WKBElement(row.oriented_geom, srid=4326, extended=True))
    if exit_point is None:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    last_coord = exit_point.coords[-1]
    return distance_m, ascent_m, descent_m, last_coord[1], last_coord[0]


class EmergencyExitService:
    def find_exit(
        self,
        db: Session,
        *,
        lat: float,
        lon: float,
        profile: str,
        speed_factor_kmh: float,
        max_search_cost: float = DEFAULT_MAX_SEARCH_COST,
    ) -> ExitFinding | None:
        """Naechstgelegener potenzieller Fahrzeug-Ausstieg ab (lat, lon), oder None, wenn
        innerhalb von max_search_cost keiner erreichbar ist (z.B. kein Strassennetz
        importiert - siehe Wiki "Wanderplaner", Offene Punkte)."""
        if profile not in ROUTING_PROFILES:
            raise ValueError("Unbekanntes Routingprofil")
        if not isfinite(max_search_cost) or max_search_cost <= 0:
            raise ValueError("Suchkosten müssen positiv und endlich sein")
        from_vertex = _nearest_vertex(db, lon=lon, lat=lat)
        if from_vertex is None:
            return None
        # Jede Profilkante kostet mindestens ihre Länge in km. Ein Pfad mit
        # Kosten <= Suchlimit bleibt deshalb innerhalb dieses Radius um den
        # Startknoten. 1 km Reserve deckt Projektions-/Rundungsabweichungen ab.
        # GiST nutzt die WGS84-Boundingbox; beide pgRouting-Aufrufe laden nur
        # diesen lokalen Graphen statt bei jedem Kontrollpunkt die ganze Schweiz.
        radius_m = max_search_cost * 1000 + 1000
        edges_sql = (
            f"SELECT id, source, target, cost_{profile} AS cost, reverse_cost_{profile} AS reverse_cost "
            "FROM routing_edge WHERE geom && ("
            "SELECT ST_Envelope(ST_Transform(ST_Expand(ST_Transform(the_geom, 2056), "
            f"{radius_m!r}), 4326)) FROM routing_edge_vertices_pgr WHERE id = {int(from_vertex)})"
        )
        road_vertex = _nearest_road_vertex(db, edges_sql=edges_sql, from_vertex=from_vertex, max_search_cost=max_search_cost)
        if road_vertex is None:
            return None
        distance_m, ascent_m, descent_m, exit_lat, exit_lon = _shortest_path_metrics(
            db, edges_sql=edges_sql, from_vertex=from_vertex, to_vertex=road_vertex
        )
        if distance_m <= 0:
            return None
        lkm = leistungskilometer(distance_m, ascent_m, descent_m)
        time_to_exit_minutes = (lkm / speed_factor_kmh) * 60 if speed_factor_kmh > 0 else 0.0
        return ExitFinding(
            from_lat=lat,
            from_lon=lon,
            exit_lat=exit_lat,
            exit_lon=exit_lon,
            distance_m=distance_m,
            ascent_m=ascent_m,
            descent_m=descent_m,
            time_to_exit_minutes=time_to_exit_minutes,
        )
