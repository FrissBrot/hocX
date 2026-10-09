"""Importiert öffentliche Schweizer OSM-Daten lokal, ohne Nutzer-/Routendaten zu senden.

python -m scripts.import_osm_landmarks --download
python -m scripts.import_osm_landmarks --pbf /data/switzerland.osm.pbf
© OpenStreetMap contributors, ODbL; Landesextrakt von Geofabrik.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path

import osmium
from shapely import set_srid
from shapely.geometry import LineString, Point
from sqlalchemy import text

from app.core.swiss_coords import wgs84_to_lv95
from scripts.import_routing_network import _AdminSession

SOURCE_URL = 'https://download.geofabrik.de/europe/switzerland-latest.osm.pbf'
KEEP_TAGS = {'name', 'name:de', 'ref', 'highway', 'waterway', 'tourism', 'building', 'place', 'access', 'foot', 'layer', 'bridge', 'tunnel'}


def relevant(tags):
    return (tags.get('highway') is not None or tags.get('waterway') in ('stream','river','canal','ditch')
        or tags.get('tourism') in ('alpine_hut','wilderness_hut') or tags.get('building') in ('hut','cabin')
        or bool(tags.get('place') and tags.get('name')))


def import_pbf(path, *, remove_after_read=False):
    with open(path, 'rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    with _AdminSession() as db:
        db.execute(text('SELECT pg_advisory_xact_lock(731102)'))
        db.execute(text('CREATE TEMP TABLE landmark_stage (LIKE hiking_landmark INCLUDING DEFAULTS) ON COMMIT DROP'))
        connection = db.connection().connection.driver_connection
        with connection.cursor().copy('COPY landmark_stage(osm_type,osm_id,tags,nodes,geom) FROM STDIN') as copy:
            class Handler(osmium.SimpleHandler):
                count = 0
                def save(self, item, kind, points, nodes):
                    tags = {tag.k: tag.v for tag in item.tags if tag.k in KEEP_TAGS}
                    if not relevant(tags):
                        return
                    shape = Point(points[0]) if len(points) == 1 else LineString(points)
                    copy.write_row((kind, item.id, json.dumps(tags), '{'+','.join(map(str,nodes))+'}', set_srid(shape,2056).wkb_hex))
                    self.count += 1
                    if self.count % 100000 == 0:
                        print(f"{self.count} Umgebungsobjekte eingelesen …", flush=True)
                def node(self, node):
                    if relevant(node.tags):
                        self.save(node, 'node', [wgs84_to_lv95(node.location.lat,node.location.lon)], [])
                def way(self, way):
                    if not relevant(way.tags) or len(way.nodes) < 2:
                        return
                    if not all(n.location.valid() for n in way.nodes):
                        return  # Randobjekte ausserhalb des Landesextrakts.
                    self.save(way, 'way', [wgs84_to_lv95(n.lat,n.lon) for n in way.nodes], [n.ref for n in way.nodes])
            handler = Handler()
            handler.apply_file(str(path), locations=True, idx='sparse_mem_array',
                filters=[osmium.filter.KeyFilter('highway', 'waterway', 'tourism', 'building', 'place')])
            if remove_after_read:
                Path(path).unlink()  # Download vor dem Datenbanktausch freigeben.
        if handler.count == 0:
            raise ValueError('Keine Umgebungsdaten gefunden; vorhandener Import bleibt erhalten.')
        db.execute(text('DELETE FROM hiking_landmark'))
        db.execute(text('INSERT INTO hiking_landmark SELECT * FROM landmark_stage'))
        db.execute(text('''INSERT INTO hiking_landmark_import(id, source, feature_count) VALUES (1,:source,:count)
            ON CONFLICT(id) DO UPDATE SET source=excluded.source, feature_count=excluded.feature_count, imported_at=now()'''),
            {'source': f'Geofabrik/OSM Schweiz; SHA256={digest}', 'count': handler.count})
        db.execute(text('ANALYZE hiking_landmark'))
        db.commit()
        return handler.count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--download', action='store_true')
    group.add_argument('--pbf', type=Path)
    args = parser.parse_args()
    if args.pbf:
        print(f'{import_pbf(args.pbf)} lokale Umgebungsobjekte importiert.', flush=True)
    else:
        with tempfile.TemporaryDirectory(prefix='hocx-osm-') as directory:
            path = Path(directory)/'switzerland.osm.pbf'
            print('Lade öffentlichen Schweizer Landesextrakt …', flush=True)
            with urllib.request.urlopen(SOURCE_URL, timeout=120) as response, path.open('wb') as output:
                shutil.copyfileobj(response, output)
            print('Importiere lokale Umgebungsdaten …', flush=True)
            print(f'{import_pbf(path, remove_after_read=True)} lokale Umgebungsobjekte importiert.', flush=True)


if __name__ == '__main__':
    main()
