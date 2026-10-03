"""Ausschliesslich lokale Umgebungsabfrage. Kein HTTP-Aufruf, kein Online-Fallback."""
import json

from shapely.geometry import LineString
from sqlalchemy import text

from app.core.swiss_coords import wgs84_to_lv95


class RouteLandmarkService:
    def nearest_name(self, db, lat, lon):
        """Benannte Umgebung aus lokalen Kartendaten; ohne Treffer kein erfundener Name."""
        x, y = wgs84_to_lv95(lat, lon)
        return db.scalar(text("""SELECT tags->>'name' FROM hiking_landmark
            WHERE NULLIF(tags->>'name', '') IS NOT NULL
              AND geom && ST_Expand(ST_SetSRID(ST_MakePoint(:x,:y),2056),1500)
              AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:x,:y),2056),
                  CASE WHEN tags ? 'place' THEN 1500 ELSE 250 END)
            ORDER BY ST_Distance(geom, ST_SetSRID(ST_MakePoint(:x,:y),2056)), osm_type, osm_id
            LIMIT 1"""), {'x': x, 'y': y})

    def fetch(self, db, coordinates):
        if not db.scalar(text('SELECT count(*) FROM hiking_landmark_import')):
            raise ValueError('Lokale Umgebungsdaten fehlen. Bitte zuerst den Schweizer OSM-Datensatz importieren.')
        line = LineString([wgs84_to_lv95(lat,lon) for lon,lat in coordinates])
        rows = db.execute(text('''SELECT osm_type, osm_id, tags, nodes,
            ST_AsGeoJSON(ST_Transform(geom,4326)) AS geometry
            FROM hiking_landmark
            WHERE ST_DWithin(geom, ST_GeomFromText(:route,2056), 1500)
              AND (tags ? 'place' OR ST_DWithin(geom, ST_GeomFromText(:route,2056), 300))
            ORDER BY osm_type, osm_id LIMIT 50001'''), {'route':line.wkt}).mappings().all()
        if len(rows) > 50000:
            raise ValueError('Zu viele Umgebungsobjekte. Bitte die Wanderung in kleinere Etappen aufteilen.')
        elements = []
        for row in rows:
            geometry = json.loads(row['geometry'])
            element = {'type':row['osm_type'], 'id':row['osm_id'], 'tags':row['tags'], 'nodes':row['nodes']}
            if geometry['type'] == 'Point':
                element.update(lon=geometry['coordinates'][0], lat=geometry['coordinates'][1])
            else:
                element['geometry'] = [{'lon':x, 'lat':y} for x,y in geometry['coordinates']]
            elements.append(element)
        return elements
