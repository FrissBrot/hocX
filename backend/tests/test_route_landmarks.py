from dataclasses import replace

import pytest

from app.core.route_landmarks import Landmark, find_landmarks, select_landmarks
from app.core.swiss_coords import lv95_to_wgs84
from app.core.waypoint_detection import RoutePoint


def coordinate(x, y=0):
    lat, lon = lv95_to_wgs84(2650000+x, 1200000+y)
    return {'lat': lat, 'lon': lon}


def way(identifier, xy, tags, nodes=None):
    return {'type': 'way', 'id': identifier, 'geometry': [coordinate(x,y) for x,y in xy],
            'nodes': nodes or list(range(identifier*100, identifier*100+len(xy))), 'tags': tags}


def route():
    return [(p['lon'], p['lat']) for p in [coordinate(0), coordinate(3000)]]


def profile(ascent=0):
    return [RoutePoint(distance_m=i*100, lat=47, lon=8, elevation_m=500+ascent*i/30) for i in range(31)]


def candidate(distance, label='Verzweigung bei Alp Test', priority=3):
    return Landmark(distance, 47, 8, 'DECISION', label, 'OSM', priority)


def test_recognizes_actual_junction_crossings_and_nearby_hut():
    elements = [
        way(1, [(0,0),(800,0),(3000,0)], {'highway':'path'}, [1,2,3]),
        way(2, [(800,0),(800,200)], {'highway':'path'}, [2,4]),
        way(3, [(1400,-100),(1400,100)], {'waterway':'stream','name':'Alpbach'}),
        way(4, [(2200,-100),(2200,100)], {'highway':'residential','name':'Alpstrasse'}),
        {'type':'node','id':6, **coordinate(1800,30), 'tags':{'tourism':'alpine_hut','name':'Testhütte'}},
        {'type':'node','id':7, **coordinate(750,100), 'tags':{'place':'locality','name':'Oberalp'}},
    ]
    result = find_landmarks(route(), elements)
    assert {c.label for c in result} == {'KP Oberalp', 'Bach Alpbach', 'Strasse Alpstrasse', 'Testhütte'}
    assert {c.kind for c in result} == {'DECISION','NAVIGATION','HUT'}
    assert next(c for c in result if c.kind == 'HUT').distance_m == pytest.approx(1800, abs=2)


def test_ignores_bends_parallel_roads_and_distant_huts():
    result = find_landmarks(route(), [
        way(1, [(0,0),(500,20),(1000,0)], {'highway':'path'}, [1,2,3]),
        way(2, [(0,15),(3000,15)], {'highway':'residential'}),
        way(3, [(0,0),(3000,0)], {'highway':'residential'}),
        {'type':'node','id':4, **coordinate(1500,150), 'tags':{'tourism':'alpine_hut','name':'Fernhütte'}},
    ])
    assert result == []


def test_timing_prefers_landmarks_near_fifteen_minutes_and_deduplicates_clusters():
    candidates = [candidate(d) for d in range(100,3000,100)]
    result = select_landmarks(candidates, profile(), 4, [0,3000])
    assert [p.distance_m for p in result] == [1000,2000]
    assert len({p.label for p in result}) == len(result)


def test_striking_crossing_beats_exact_interval():
    result = select_landmarks([candidate(1000), candidate(850, 'Bachquerung Testbach', 5)], profile(), 4, [0,3000])
    assert result[0].distance_m == 850


def test_ascent_changes_spacing_and_existing_waypoints_are_respected():
    candidates = [candidate(d) for d in range(100,3000,100)]
    flat = select_landmarks(candidates, profile(), 4, [0,3000])
    uphill = select_landmarks(candidates, profile(300), 4, [0,1500,3000])
    assert len(uphill) > len(flat)
    assert all(abs(c.distance_m-1500) >= 100 for c in uphill)


def test_sparse_landmarks_are_not_replaced_with_artificial_points():
    assert select_landmarks([], profile(), 4) == []
    assert len(select_landmarks([candidate(1800)], profile(), 4)) == 1


def test_unnamed_points_get_honest_unique_distance_labels():
    points = [candidate(1000, 'KP'),candidate(2000, 'KP')]
    assert [c.label for c in select_landmarks(points, profile(), 4)] == ['KP · km 1.00','KP · km 2.00']
