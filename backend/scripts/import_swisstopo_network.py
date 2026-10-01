#!/usr/bin/env python3
"""Amtliches swissTLM3D-Wegenetz aus GeoPackage importieren.

Im Backend-Container: python -m scripts.import_swisstopo_network --download
Alternativ: --gpkg /data/SWISSTLM3D_WANDERWEGE.gpkg
Quelle: https://opendata.swiss/de/dataset/swisstlm3d-wanderwege
Der Download enthält die gesamte Schweiz, nicht nur einen Testausschnitt.
Ein vollständiges swissTLM3D-GeoPackage mit derselben Strassen-Tabelle kann ebenfalls
importiert werden; geeignete Wege ohne Wanderwegstatus bleiben dabei nutzbar.
Bestehende Touren werden nicht verändert. Import/Topologie werden atomar ersetzt.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import sqlite3
import struct
import tempfile
import urllib.request
import zipfile
from contextlib import closing
from pathlib import Path

from shapely import from_wkb
from sqlalchemy import text

from app.core.routing_cost import ROUTING_PROFILES, EdgeAttributes, compute_edge_cost
from scripts.import_routing_network import _AdminSession, TOPOLOGY_TOLERANCE_DEGREES

SOURCE_URL = (
    "https://data.geo.admin.ch/ch.swisstopo.swisstlm3d-wanderwege/"
    "swisstlm3d-wanderwege/swisstlm3d-wanderwege_2056_5728.gpkg.zip"
)
CATEGORIES = {"Wanderweg": "wanderweg", "Bergwanderweg": "bergwanderweg", "Alpinwanderweg": "alpinwanderweg"}
# Ausschluss unbekannter Klassen, Autobahnen, Autostrassen, Rampen und Fähren.
WAY_TYPES = {
    "1m Weg": "fussweg", "2m Weg": "forststrasse", "3m Strasse": "forststrasse",
    "4m Strasse": "normalstrasse", "6m Strasse": "normalstrasse",
    "8m Strasse": "normalstrasse", "10m Strasse": "normalstrasse",
    "Markierte Spur": "fussweg", "Verbindung": "fussweg", "Platz": "fussweg",
}
BLOCKED = {"Gesperrt", "Fussgaengerverbot", "Fussgängerverbot", "Gesicherte Kletterpartie", "Militaerstrasse"}


def geopackage_wkb(blob: bytes) -> bytes:
    """GeoPackage-Binary-Header entfernen (OGC: Envelope-Indikator in Flagbits 1–3)."""
    if len(blob) < 8 or blob[:2] != b"GP" or blob[2] != 0:
        raise ValueError("Ungültige GeoPackage-Geometrie")
    envelope = (blob[3] >> 1) & 7
    sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope not in sizes or blob[3] & 0x10:
        raise ValueError("Leere oder ungültige GeoPackage-Geometrie")
    srid = struct.unpack('<i' if blob[3] & 1 else '>i', blob[4:8])[0]
    if srid != 2056:
        raise ValueError(f"LV95 (EPSG:2056) erwartet, erhalten: {srid}")
    return blob[8 + sizes[envelope]:]


def edge_record(row) -> tuple | None:
    kind = WAY_TYPES.get(row['objektart'])
    if kind is None or row['verkehrsbeschraenkung'] in BLOCKED:
        return None
    status = CATEGORIES.get(row['wanderwege'])
    if row['wanderwege'] not in {*CATEGORIES, 'andere', 'Keine', 'k_W', None}:
        raise ValueError(f"Unbekannte Wanderwegklasse: {row['wanderwege']}")
    wkb = geopackage_wkb(row['geom'])
    line = from_wkb(wkb)
    if line.geom_type != 'LineString' or line.is_empty:
        raise ValueError("LineString erwartet")
    coords = list(line.coords)
    if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in coords):
        raise ValueError("Weg benötigt endliche LV95-Koordinaten mit Höhe")
    length = line.length  # LV95 in Metern; keine Grad-Distanz.
    if length <= 0:
        return None
    ascent = sum(max(0, b[2] - a[2]) for a, b in zip(coords, coords[1:]))
    descent = sum(max(0, a[2] - b[2]) for a, b in zip(coords, coords[1:]))
    costs = [compute_edge_cost(p, EdgeAttributes(length, a, d, status, kind, True))
             for a, d in ((ascent, descent), (descent, ascent)) for p in ROUTING_PROFILES]
    return (wkb.hex(), length, ascent, descent, status, kind, row['uuid'], *costs)


def import_geopackage(path: Path, description: str) -> int:
    with path.open('rb') as data:
        digest = hashlib.file_digest(data, 'sha256').hexdigest()
    with closing(sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True)) as source:
        source.row_factory = sqlite3.Row
        layers = source.execute("SELECT table_name, column_name, srs_id FROM gpkg_geometry_columns").fetchall()
        layer = next((r for r in layers if r['table_name'].lower().endswith('strassen_strasse')), None)
        if layer is None or layer['column_name'] != 'geom' or layer['srs_id'] != 2056:
            raise ValueError("swissTLM3D Strassen-Layer mit geom/EPSG:2056 fehlt")
        table = layer['table_name'].replace('"', '""')
        with _AdminSession() as db:
            # Netzwerkweite Importe serialisieren, auch bei parallelen Wartungsläufen.
            db.execute(text("SELECT pg_advisory_xact_lock(731098)"))
            db.execute(text("""CREATE TEMP TABLE routing_import (
                wkb text, length_m float8, ascent_m float8, descent_m float8,
                wanderweg_status text, wegtyp text, external_ref text,
                cost_wanderwege_bevorzugen float8, cost_schnellste_route float8, cost_einfache_route float8,
                reverse_cost_wanderwege_bevorzugen float8, reverse_cost_schnellste_route float8,
                reverse_cost_einfache_route float8) ON COMMIT DROP"""))
            count = 0
            raw = db.connection().connection.driver_connection
            with raw.cursor().copy("COPY routing_import FROM STDIN") as copy:
                for row in source.execute(f'SELECT geom, uuid, objektart, wanderwege, verkehrsbeschraenkung FROM "{table}" ORDER BY id'):
                    record = edge_record(row)
                    if record is not None:
                        copy.write_row(record)
                        count += 1
            if count == 0:
                raise ValueError("Keine begehbaren Wege gefunden; bestehendes Netz bleibt erhalten")
            print(f'{count} Wegabschnitte geprüft; importiere und verbinde Topologie …', flush=True)
            db.execute(text("TRUNCATE routing_edge RESTART IDENTITY CASCADE"))
            db.execute(text("DROP TABLE IF EXISTS routing_edge_vertices_pgr"))
            db.execute(text("""INSERT INTO routing_edge (
                geom, length_m, ascent_m, descent_m, wanderweg_status, wegtyp, external_ref,
                cost_wanderwege_bevorzugen, cost_schnellste_route, cost_einfache_route,
                reverse_cost_wanderwege_bevorzugen, reverse_cost_schnellste_route, reverse_cost_einfache_route)
                SELECT ST_Transform(ST_Force2D(ST_GeomFromWKB(decode(wkb, 'hex'),2056)),4326),
                length_m, ascent_m, descent_m, wanderweg_status, wegtyp, external_ref,
                cost_wanderwege_bevorzugen, cost_schnellste_route, cost_einfache_route,
                reverse_cost_wanderwege_bevorzugen, reverse_cost_schnellste_route, reverse_cost_einfache_route
                FROM routing_import"""))
            result = db.scalar(text("SELECT pgr_createTopology('routing_edge', :tol, 'geom', 'id')"),
                               {'tol': TOPOLOGY_TOLERANCE_DEGREES})
            if result != 'OK':
                raise ValueError(f"Topologie konnte nicht erstellt werden: {result}")
            db.execute(text("CREATE INDEX IF NOT EXISTS idx_routing_edge_vertices_pgr_geom ON routing_edge_vertices_pgr USING GIST(the_geom)"))
            db.execute(text("ANALYZE routing_edge"))
            db.execute(text("INSERT INTO routing_network_meta(source_description,edge_count) VALUES (:d,:n)"),
                       {'d': f'{description}; SHA256={digest}', 'n': count})
            db.commit()
            return count


def download(destination: Path) -> Path:
    archive = destination / 'swisstlm3d.zip'
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as response, archive.open('wb') as out:
        import shutil
        shutil.copyfileobj(response, out)
    with zipfile.ZipFile(archive) as zipped:
        names = [n for n in zipped.namelist() if n.lower().endswith('.gpkg')]
        if len(names) != 1:
            raise ValueError('Genau ein GeoPackage im Download erwartet')
        target = destination / 'network.gpkg'
        with zipped.open(names[0]) as src, target.open('wb') as out:
            shutil.copyfileobj(src, out)
    archive.unlink()
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--download', action='store_true')
    group.add_argument('--gpkg', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hocx-swisstopo-') as tmp:
        path = download(Path(tmp)) if args.download else args.gpkg
        count = import_geopackage(path, f'swisstopo swissTLM3D: {SOURCE_URL if args.download else path.name}')
        print(f'Wegenetz bereit: {count} Abschnitte. Bestehende Touren bei Bedarf neu berechnen.')


if __name__ == '__main__':
    main()
