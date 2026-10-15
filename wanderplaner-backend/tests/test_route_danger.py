"""Unit-Tests für app/core/route_danger.py - reine Funktionen, keine DB/Netzwerk-Abhängigkeit
(Stil wie test_routing_cost.py/test_break_planning.py)."""
from __future__ import annotations

import pytest

from app.core.route_danger import (
    DangerSegment,
    classify_terrain,
    cross_section_targets,
    downhill_cross_slopes,
    merge_with_official_status,
)
from app.core.waypoint_detection import RoutePoint


def _point(distance_m: float, elevation_m: float) -> RoutePoint:
    return RoutePoint(distance_m=distance_m, lat=47.0, lon=8.5, elevation_m=elevation_m)


def test_classify_terrain_flags_steep_along_track_gradient():
    points = [_point(0, 1000), _point(50, 1000), _point(60, 1040)]  # 400% über die letzten 10 m

    segments = classify_terrain(points)

    assert segments == [
        DangerSegment(0, 50, "normal"),
        DangerSegment(50, 60, "steep_exposed"),
    ]


def test_classify_terrain_flags_steep_gradient_with_sparse_points():
    # Punktabstand (50 m) grösser als das Steigungsfenster (40 m): früher lag nie ein
    # Nachbarpunkt im Fenster und jede Steigung ergab 0% - jetzt zählt das Intervall selbst.
    points = [_point(index * 50.0, 1000 + index * 30.0) for index in range(200)]  # 60%

    segments = classify_terrain(points)

    assert segments == [DangerSegment(0, 9950, "steep_exposed")]


def test_classify_terrain_flags_steep_gradient_with_dense_points():
    flat = [_point(index * 10.0, 1000) for index in range(30)]  # 0-290 m flach
    steep = [_point(300 + index * 10.0, 1000 + (index + 1) * 6.0) for index in range(10)]  # 290-390 m, 60%
    after = [_point(400 + index * 10.0, 1060) for index in range(30)]  # 400-690 m flach

    segments = classify_terrain(flat + steep + after)

    assert [segment.danger for segment in segments] == ["normal", "steep_exposed", "normal"]
    steep_segment = segments[1]
    assert 260 <= steep_segment.from_m <= 300
    assert 370 <= steep_segment.to_m <= 430


def test_classify_terrain_stays_normal_below_gradient_threshold():
    points = [_point(0, 1000), _point(100, 1010)]  # 10% über 100 m, deutlich unter der Schwelle

    segments = classify_terrain(points)

    assert segments == [DangerSegment(0, 100, "normal")]


def test_classify_terrain_flags_both_intervals_around_exposed_point():
    points = [_point(0, 1000), _point(50, 1000), _point(100, 1000), _point(150, 1000)]  # flach

    segments = classify_terrain(points, cross_slopes=[0.0, 0.0, 90.0, None])

    assert segments == [
        DangerSegment(0, 50, "normal"),
        DangerSegment(50, 150, "steep_exposed"),
    ]


def test_classify_terrain_bridges_short_normal_gap_between_dangerous_sections():
    points = [_point(index * 10.0, 1000) for index in range(10)]
    slopes = [0.0, 90.0, 0.0, 0.0, 0.0, 90.0, 0.0, 0.0, 0.0, 0.0]  # Lücke 20-40 m < 30 m

    segments = classify_terrain(points, cross_slopes=slopes)

    assert segments == [
        DangerSegment(0, 60, "steep_exposed"),
        DangerSegment(60, 90, "normal"),
    ]


def test_classify_terrain_ignores_missing_elevation_points():
    points = [_point(0, 1000), RoutePoint(distance_m=20, lat=47.0, lon=8.5, elevation_m=None), _point(100, 1005)]

    segments = classify_terrain(points, cross_slopes=[None, 95.0, None])

    assert segments == [DangerSegment(0, 100, "normal")]


def test_cross_section_targets_are_perpendicular_left_and_right():
    left, right = cross_section_targets([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)], offset_m=15)  # nach Osten

    assert left == [(0.0, 15.0), (10.0, 15.0), (20.0, 15.0)]
    assert right == [(0.0, -15.0), (10.0, -15.0), (20.0, -15.0)]


def test_cross_section_targets_reuse_direction_for_duplicate_points():
    left, _ = cross_section_targets([(0.0, 0.0), (0.0, 0.0), (0.0, 10.0)], offset_m=10)  # nach Norden

    assert left[1] == pytest.approx((-10.0, 0.0))


def test_cross_section_targets_without_direction_is_empty():
    assert cross_section_targets([(5.0, 5.0), (5.0, 5.0)]) == ([], [])


def test_downhill_cross_slopes_match_by_position_not_distance():
    centerline = [(0.0, 0.0, 1000.0), (10.0, 0.0, 1000.0), (20.0, 0.0, 1000.0)]
    targets = [(0.0, -15.0), (10.0, -15.0), (20.0, -15.0)]
    # Messpunkte in anderer Reihenfolge und leicht versetzt - die Zuordnung läuft über die Lage.
    samples = [(21.0, -15.0, 1000.0), (10.0, -16.0, 985.0), (60.0, -15.0, 500.0)]

    slopes = downhill_cross_slopes(centerline, targets, samples)

    assert slopes[0] is None  # nächster Messpunkt zu weit weg
    assert slopes[1] == pytest.approx(15 / 16 * 100)
    assert slopes[2] == pytest.approx(0.0)


def test_downhill_cross_slopes_ignore_rising_terrain():
    centerline = [(0.0, 0.0, 1000.0)]
    slopes = downhill_cross_slopes(centerline, [(0.0, 15.0)], [(0.0, 15.0, 1030.0)])

    assert slopes == [0.0]


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
