"""Unit-Tests für app/core/route_danger.py - reine Funktionen, keine DB/Netzwerk-Abhängigkeit
(Stil wie test_routing_cost.py/test_break_planning.py)."""
from __future__ import annotations

from app.core.route_danger import DangerSegment, classify_terrain, merge_with_official_status
from app.core.waypoint_detection import RoutePoint


def _point(distance_m: float, elevation_m: float) -> RoutePoint:
    return RoutePoint(distance_m=distance_m, lat=47.0, lon=8.5, elevation_m=elevation_m)


def test_classify_terrain_flags_steep_along_track_gradient():
    points = [_point(0, 1000), _point(50, 1000), _point(60, 1040)]  # 400% über die letzten 10 m

    segments = classify_terrain(points, left_profile=[], right_profile=[])

    assert segments == [
        DangerSegment(0, 50, "normal"),
        DangerSegment(50, 60, "steep_exposed"),
    ]


def test_classify_terrain_stays_normal_below_gradient_threshold():
    points = [_point(0, 1000), _point(100, 1010)]  # 10% über 100 m, deutlich unter der Schwelle

    segments = classify_terrain(points, left_profile=[], right_profile=[])

    assert segments == [DangerSegment(0, 100, "normal")]


def test_classify_terrain_flags_cross_slope_exposure():
    points = [_point(0, 1000), _point(50, 1000), _point(100, 1000)]  # flach entlang des Weges
    right_profile = [
        {"distance_m": 0, "elevation_m": 1000},
        {"distance_m": 50, "elevation_m": 1020},  # 20 m Abbruch 15 m neben dem Weg bei km 50
        {"distance_m": 100, "elevation_m": 1000},
    ]

    segments = classify_terrain(points, left_profile=[], right_profile=right_profile)

    assert segments == [
        DangerSegment(0, 50, "steep_exposed"),
        DangerSegment(50, 100, "normal"),
    ]


def test_classify_terrain_ignores_missing_elevation_points():
    points = [_point(0, 1000), RoutePoint(distance_m=20, lat=47.0, lon=8.5, elevation_m=None), _point(100, 1005)]

    segments = classify_terrain(points, left_profile=[], right_profile=[])

    assert segments == [DangerSegment(0, 100, "normal")]


def test_merge_with_official_status_alpine_overrides_terrain():
    terrain_segments = [DangerSegment(0, 50, "normal"), DangerSegment(50, 100, "steep_exposed")]
    wanderweg_segments = [{"from_m": 30, "to_m": 70, "status": "alpinwanderweg"}]

    merged = merge_with_official_status(terrain_segments, wanderweg_segments)

    assert merged == [
        DangerSegment(0, 30, "normal"),
        DangerSegment(30, 70, "alpine"),
        DangerSegment(70, 100, "steep_exposed"),
    ]


def test_merge_with_official_status_bergwanderweg_does_not_override():
    terrain_segments = [DangerSegment(0, 100, "steep_exposed")]
    wanderweg_segments = [{"from_m": 0, "to_m": 100, "status": "bergwanderweg"}]

    merged = merge_with_official_status(terrain_segments, wanderweg_segments)

    assert merged == [DangerSegment(0, 100, "steep_exposed")]


def test_merge_with_official_status_without_official_data_passes_terrain_through():
    terrain_segments = [DangerSegment(0, 50, "normal"), DangerSegment(50, 100, "steep_exposed")]

    merged = merge_with_official_status(terrain_segments, [])

    assert merged == terrain_segments
