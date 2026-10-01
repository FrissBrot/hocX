#!/usr/bin/env python3
"""Importiert/ersetzt das Wanderplaner-Wegenetz (Auftrag Abschnitt 3, siehe Wiki-Seite
"Wanderplaner") aus einer GeoJSON-Datei mit 3D-LineString-Features (Koordinaten
[lon, lat, elevation_m] - wie ein swissTLM3D-Export sie liefert).

Erwartetes Feature-Schema (properties je LineString):
  external_ref:      Quell-Objekt-Id (fuer Diffing bei einem spaeteren Reimport)
  wanderweg_status:  "wanderweg" | "bergwanderweg" | "alpinwanderweg" | null
  wegtyp:            "fussweg" | "forststrasse" | "feldweg" | "normalstrasse" | ... (frei)
  is_walkable:        true/false - false-Kanten (z.B. Autobahnen) werden NICHT importiert
                       ("Nicht begehbare ... Verkehrswege duerfen nicht verwendet werden")

Ersetzt bei jedem Lauf das komplette Netz (TRUNCATE + Neuimport) - ein einzelnes
swissTLM3D-Update betrifft potenziell das ganze Land, ein inkrementelles Diffing lohnt sich
fuer den seltenen (jaehrlichen) Reimport nicht. Bestehende hiking_tour_route_leg-Zeilen sind
NICHT betroffen (eigene Geometrie-Kopie, siehe Migration 0098) - bereits geplante Touren
bleiben unveraendert, bis ihr Besitzer die Route bewusst neu berechnet.

Laeuft bewusst mit der Admin-/Migrations-Datenbankrolle (DATABASE_URL), nicht mit der
eingeschraenkten App-Laufzeitrolle (APP_DATABASE_URL/hocx_app) - TRUNCATE und das erstmalige
Anlegen von routing_edge_vertices_pgr durch pgr_createTopology() sind DDL-nahe Operationen,
die hocx_app bewusst nicht darf (Least-Privilege). Dieses Skript ist ein manuell
angestossener Betriebs-/Wartungsschritt wie eine Alembic-Migration, kein Teil der
Request-Laufzeit - dieselbe Vertrauensstufe wie `alembic upgrade head`.

Für den direkten amtlichen GeoPackage-Import inkl. Download stattdessen:
  python -m scripts.import_swisstopo_network --download

Für andere GeoJSON-Quellen: der Export (GeoPackage/Shapefile von shop.swisstopo.admin.ch)
muss vorher in dieses GeoJSON-Schema konvertiert werden (z.B. via ogr2ogr + einem Attribut-
Mapping von swissTLM3D-Objektklassen auf wanderweg_status/wegtyp/is_walkable) - dieser
Konvertierungsschritt ist nicht Teil dieses Skripts, da er von der jeweils aktuellen
swissTLM3D-Attributstruktur abhaengt.

Usage (im Backend-Container/-Image):
  python scripts/import_routing_network.py <pfad-zur-geojson> [--description TEXT]

Fuer das mitgelieferte Test-Fixture:
  python scripts/import_routing_network.py tests/fixtures/routing_network_sample.geojson \
      --description "Test-Fixture (kein echtes swissTLM3D)"
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from geoalchemy2.shape import from_shape
from shapely.geometry import LineString
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.routing_cost import ROUTING_PROFILES, EdgeAttributes, compute_edge_cost
from app.models.entities import RoutingEdge

# Eigene Engine mit der Admin-Rolle statt app.core.db.SessionLocal (das ist an
# APP_DATABASE_URL/hocx_app gebunden) - siehe Modul-Docstring.
_AdminSession = sessionmaker(bind=create_engine(settings.database_url, future=True), autoflush=False, future=True)

# Endpunkte, die um weniger als diese Distanz (in Grad) auseinanderliegen, gelten
# pgr_createTopology zufolge als derselbe Netzknoten. ~1.1 m bei diesem Wert - fuer exakt
# gleiche Koordinaten (Normalfall bei einem sauberen Export) mehr als ausreichend.
TOPOLOGY_TOLERANCE_DEGREES = 0.00001


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Geodaetische Distanz zwischen zwei WGS84-Punkten. Bewusst selbst gerechnet statt einer
    zusaetzlichen Abhaengigkeit (pyproj/geopy) fuer diese eine Formel - Genauigkeit reicht fuer
    Wanderwege-Massstaebe (Fehler < 0.5% auch ueber mehrere Kilometer)."""
    r = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _line_metrics(coords: list[list[float]]) -> tuple[float, float, float]:
    """(length_m, ascent_m, descent_m) ueber alle Teilstuecke einer (moeglicherweise mehr als
    zweipunktigen) Linie - Auf- und Abstieg werden je Teilstueck aufsummiert, nicht nur aus
    Start-/Endpunkt genommen (eine Linie kann zwischendurch wieder abfallen)."""
    length_m = 0.0
    ascent_m = 0.0
    descent_m = 0.0
    for (lon1, lat1, *rest1), (lon2, lat2, *rest2) in zip(coords, coords[1:]):
        length_m += _haversine_m(lon1, lat1, lon2, lat2)
        z1 = rest1[0] if rest1 else 0.0
        z2 = rest2[0] if rest2 else 0.0
        delta = z2 - z1
        if delta > 0:
            ascent_m += delta
        else:
            descent_m += -delta
    return length_m, ascent_m, descent_m


def _edge_rows(feature: dict) -> dict | None:
    props = feature["properties"]
    if props.get("is_walkable") is False:
        return None
    coords = feature["geometry"]["coordinates"]
    if len(coords) < 2:
        return None
    length_m, ascent_m, descent_m = _line_metrics(coords)
    wanderweg_status = props.get("wanderweg_status")
    wegtyp = props["wegtyp"]
    forward = EdgeAttributes(length_m, ascent_m, descent_m, wanderweg_status, wegtyp, is_walkable=True)
    reverse = EdgeAttributes(length_m, descent_m, ascent_m, wanderweg_status, wegtyp, is_walkable=True)
    geom_2d = from_shape(LineString([(lon, lat) for lon, lat, *_ in coords]), srid=4326)
    row = {
        "geom": geom_2d,
        "length_m": length_m,
        "ascent_m": ascent_m,
        "descent_m": descent_m,
        "wanderweg_status": wanderweg_status,
        "wegtyp": wegtyp,
        "external_ref": props.get("external_ref"),
    }
    for profile in ROUTING_PROFILES:
        row[f"cost_{profile}"] = compute_edge_cost(profile, forward)
        row[f"reverse_cost_{profile}"] = compute_edge_cost(profile, reverse)
    return row


def import_network(geojson_path: Path, description: str) -> int:
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    rows = [row for feature in data["features"] if (row := _edge_rows(feature)) is not None]
    if not rows:
        raise ValueError(f"{geojson_path}: keine begehbaren Wegkanten gefunden")

    db = _AdminSession()
    try:
        db.execute(text("TRUNCATE routing_edge RESTART IDENTITY CASCADE"))
        # TRUNCATE CASCADE erfasst nur Tabellen mit FK auf routing_edge - die von
        # pgr_createTopology separat verwaltete Knotentabelle hat keine und muss explizit
        # weg, sonst bleiben verwaiste Knoten von der vorherigen Topologie stehen.
        db.execute(text("DROP TABLE IF EXISTS routing_edge_vertices_pgr"))
        # Ueber die gemappte Tabelle (nicht rohes text()-SQL) einfuegen - nur so kennt der
        # DBAPI-Adapter GeoAlchemy2s WKBElement fuer die geom-Spalte.
        db.execute(RoutingEdge.__table__.insert(), rows)
        # pgr_createTopology befuellt source/target auf routing_edge und legt
        # routing_edge_vertices_pgr an/aktualisiert es (Standard-pgRouting-Workflow).
        db.execute(
            text("SELECT pgr_createTopology('routing_edge'::text, :tol, 'geom'::text, 'id'::text)"),
            {"tol": TOPOLOGY_TOLERANCE_DEGREES},
        )
        # pgr_createTopology legt keinen raeumlichen Index an - ohne ihn wuerde jede
        # Punkt-Snapping-Abfrage (emergency_exit_service.py::_nearest_vertex) das ganze Netz
        # sequenziell scannen.
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_routing_edge_vertices_pgr_geom ON routing_edge_vertices_pgr USING GIST (the_geom)"))
        db.execute(
            text("INSERT INTO routing_network_meta (source_description, edge_count) VALUES (:d, :n)"),
            {"d": description, "n": len(rows)},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("geojson_path", type=Path)
    parser.add_argument("--description", default=None, help="Freitext fuer routing_network_meta.source_description")
    args = parser.parse_args()

    if not args.geojson_path.exists():
        print(f"Datei nicht gefunden: {args.geojson_path}", file=sys.stderr)
        sys.exit(1)

    description = args.description or f"Import von {args.geojson_path.name}"
    count = import_network(args.geojson_path, description)
    print(f"Wegenetz importiert: {count} Kanten aus {args.geojson_path}")


if __name__ == "__main__":
    main()
