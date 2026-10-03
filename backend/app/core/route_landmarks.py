"""Markante Orte entlang der Route und ausgedünnte Auswahl nach effektiver Gehzeit."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from math import acos, degrees, hypot

from shapely import remove_repeated_points
from shapely.geometry import LineString, Point

from app.core.march_time import leistungskilometer
from app.core.swiss_coords import wgs84_to_lv95, lv95_to_wgs84


@dataclass(frozen=True)
class Landmark:
    distance_m: float
    lat: float
    lon: float
    kind: str
    label: str
    description: str
    priority: int


def metric_point(item):
    return Point(wgs84_to_lv95(item['lat'], item['lon']))


def _points(geometry):
    if geometry.geom_type == 'Point':
        return [geometry]
    if geometry.geom_type in ('MultiPoint', 'GeometryCollection'):
        return [p for g in geometry.geoms for p in _points(g)]
    return []  # Gemeinsam verlaufende Linien sind keine Querungen.


def _transverse(route, line, point):
    vectors = []
    for geometry in (route, line):
        distance = geometry.project(point)
        a, b = geometry.interpolate(max(0, distance - 12)), geometry.interpolate(min(geometry.length, distance + 12))
        vectors.append((b.x - a.x, b.y - a.y))
    (ax, ay), (bx, by) = vectors
    denominator = hypot(ax, ay) * hypot(bx, by)
    return denominator > 0 and degrees(acos(min(1, abs(ax * bx + ay * by) / denominator))) >= 25


def find_landmarks(coordinates, elements) -> list[Landmark]:
    route = remove_repeated_points(LineString([wgs84_to_lv95(lat, lon) for lon, lat in coordinates]), tolerance=0.001)
    if route.length == 0:
        return []
    features, names, neighbours, positions = [], [], {}, {}
    for element in elements:
        tags = element.get('tags', {})
        geometry = element.get('geometry', [])
        if len(geometry) >= 2:
            shape = remove_repeated_points(LineString([metric_point(p) for p in geometry]), tolerance=0.001)
            if shape.length == 0:
                continue
        elif 'lat' in element and 'lon' in element:
            shape = metric_point(element)
        else:
            continue
        features.append((tags, shape))
        if tags.get('name'):
            names.append((tags, shape))
        if tags.get('highway') and tags.get('access') != 'private' and tags.get('foot') != 'no':
            nodes = element.get('nodes', [])
            for i, node in enumerate(nodes):
                if i < len(geometry):
                    positions[node] = metric_point(geometry[i])
                neighbours.setdefault(node, set()).update(nodes[max(0, i-1):i] + nodes[i+1:i+2])

    def label(prefix, tags, point):
        name = tags.get('name') or tags.get('ref')
        if name:
            return name if prefix == 'Bei' else f'{prefix} {name}'
        nearby = [(point.distance(g), t['name']) for t, g in names
                  if point.distance(g) <= (1500 if t.get('place') else 250)]
        if nearby:
            return min(nearby)[1] if prefix == 'Bei' else f'{prefix} {min(nearby)[1]}'
        return prefix  # Keine Ortsnamen erfinden; km-Zusatz wird unten ergänzt.

    candidates = []
    def add(point, tags, prefix, kind, priority):
        distance = route.project(point)
        snapped = route.interpolate(distance)
        lat, lon = lv95_to_wgs84(snapped.x, snapped.y)
        candidates.append(Landmark(distance, lat, lon, kind, label(prefix, tags, point),
            'Automatisch aus OpenStreetMap erkannt; Lage und Begehbarkeit vor Ort prüfen.', priority))

    for node, adjacent in neighbours.items():
        point = positions.get(node)
        if len(adjacent) >= 3 and point is not None and point.distance(route) <= 18:
            add(point, {}, 'KP', 'DECISION', 3)
    roads = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'service', 'living_street'}
    for tags, shape in features:
        water = tags.get('waterway') in ('stream', 'river', 'canal', 'ditch')
        road = tags.get('highway') in roads
        if (water or road) and shape.geom_type == 'LineString':
            for point in _points(route.intersection(shape)):
                if _transverse(route, shape, point):
                    # Auch Brücken sind nützliche Orientierungspunkte, keine behauptete Furt.
                    add(point, tags, 'Bach' if water else 'Strasse', 'NAVIGATION', 5 if water else 4)
        hut = tags.get('tourism') in ('alpine_hut', 'wilderness_hut') or tags.get('building') in ('hut', 'cabin')
        alp = tags.get('place') in ('isolated_dwelling', 'farm') and tags.get('name')
        if (hut or alp) and shape.distance(route) <= 60:
            from shapely.ops import nearest_points
            add(nearest_points(shape, route)[0], tags, 'Bei', 'HUT' if hut else 'NAVIGATION', 4)
    return candidates


def select_landmarks(candidates, profile, speed_kmh, existing_distances=(), reserved_names=()):
    """15 min Richtwert, 7 min Mindestabstand; markante Orte dürfen dichter folgen.

    Pro Lücke wird der am besten bewertete Kandidat nahe 15 min gewählt. Danach wird
    bis zur nächsten Lücke weitergegangen. Keine künstlichen Zwischenpunkte.
    """
    if len(profile) < 2:
        return []
    distances = [p.distance_m for p in profile]
    times = [0.0]
    for a, b in zip(profile, profile[1:]):
        delta = b.elevation_m - a.elevation_m
        times.append(times[-1] + 60 * leistungskilometer(max(0, b.distance_m-a.distance_m), max(0, delta), max(0, -delta)) / speed_kmh)
    def minutes(distance):
        i = min(max(1, bisect_right(distances, distance)), len(distances)-1)
        fraction = max(0, min(1, (distance-distances[i-1]) / max(0.001, distances[i]-distances[i-1])))
        return times[i-1] + fraction * (times[i]-times[i-1])
    anchors = sorted(set([0.0, times[-1]] + [minutes(d) for d in existing_distances]))
    selected = []
    for start, end in zip(anchors, anchors[1:]):
        available = [(minutes(c.distance_m), c) for c in candidates
                     if start+7 <= minutes(c.distance_m) <= end-7
                     and all(abs(c.distance_m-d) >= 100 for d in existing_distances)]
        cursor = start
        while available and end - cursor > 20:
            near = [(t, c) for t, c in available if cursor+7 <= t <= cursor+22]
            if not near:
                near = [(t, c) for t, c in available if t >= cursor+7]
                if not near:
                    break
                earliest = min(t for t, c in near)
                near = [(t, c) for t, c in near if t <= earliest+5]
            t, chosen = max(near, key=lambda item: (item[1].priority*2 - abs(item[0]-cursor-15)/3, -item[0], item[1].label))
            selected.append(chosen)
            cursor = t
            available = [(time, c) for time, c in available if time >= cursor+7 and c.distance_m-chosen.distance_m >= 100]
    # Lesbare, eindeutige Namen auch bei mehrfacher Querung desselben Bachs.
    used = set(reserved_names)
    result = []
    for candidate in sorted(selected, key=lambda c: c.distance_m):
        base = candidate.label
        if base in used or base in ('KP', 'Bach', 'Strasse', 'Bei'):
            base = f'{base} · km {candidate.distance_m/1000:.2f}'
        name, suffix = base, 2
        while name in used:
            name = f'{base} ({suffix})'
            suffix += 1
        used.add(name)
        result.append(replace(candidate, label=name))
    return result
