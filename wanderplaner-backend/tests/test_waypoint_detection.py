from app.core.waypoint_detection import RoutePoint, detect_climb_segments, detect_direction_changes


def _line_points(n: int, *, step_m: float = 50.0, lat0: float = 47.0, lon0: float = 8.5) -> list[RoutePoint]:
    """n Punkte auf einer geraden Ostlinie."""
    return [RoutePoint(distance_m=i * step_m, lat=lat0, lon=lon0 + i * 0.001) for i in range(n)]


def _l_shaped_points(corner_index: int, total: int, *, step_m: float = 50.0) -> list[RoutePoint]:
    """Erst nach Osten, ab corner_index nach Norden abbiegend - eine klare 90-Grad-Kehre."""
    points = []
    lat0, lon0 = 47.0, 8.5
    corner_lon = lon0 + corner_index * 0.001
    for i in range(total):
        distance = i * step_m
        if i <= corner_index:
            points.append(RoutePoint(distance_m=distance, lat=lat0, lon=lon0 + i * 0.001))
        else:
            steps_after_corner = i - corner_index
            points.append(RoutePoint(distance_m=distance, lat=lat0 + steps_after_corner * 0.001, lon=corner_lon))
    return points


class TestDetectDirectionChanges:
    def test_straight_line_has_no_direction_change(self):
        assert detect_direction_changes(_line_points(10)) == []

    def test_a_90_degree_corner_is_detected_near_the_corner(self):
        points = _l_shaped_points(corner_index=6, total=13)
        changes = detect_direction_changes(points)

        assert len(changes) == 1
        assert changes[0].bearing_change_deg > 60
        corner_distance = 6 * 50.0
        assert abs(changes[0].distance_m - corner_distance) <= 150

    def test_two_corners_far_apart_are_reported_separately(self):
        # Ost -> Nord bei Index 4, dann zurueck Richtung Ost bei Index 20 (weit genug entfernt,
        # damit die Kandidatenluecke zwischen den Kehren klar ueber merge_distance_m liegt).
        lat0, lon0 = 47.0, 8.5
        points = []
        for i in range(4 + 1):
            points.append(RoutePoint(distance_m=i * 50.0, lat=lat0, lon=lon0 + i * 0.001))
        corner_lat = lat0
        corner_lon = lon0 + 4 * 0.001
        for i in range(1, 17):
            points.append(RoutePoint(distance_m=(4 + i) * 50.0, lat=corner_lat + i * 0.001, lon=corner_lon))
        turn_back_lat = corner_lat + 16 * 0.001
        for i in range(1, 5):
            points.append(RoutePoint(distance_m=(20 + i) * 50.0, lat=turn_back_lat, lon=corner_lon + i * 0.001))

        changes = detect_direction_changes(points)
        assert len(changes) == 2
        assert changes[1].distance_m - changes[0].distance_m > 300

    def test_below_threshold_bearing_change_is_ignored(self):
        # Sehr sanfte Kurve statt einer scharfen Kehre - unter dem Schwellenwert.
        points = [RoutePoint(distance_m=i * 50.0, lat=47.0 + i * 0.0001, lon=8.5 + i * 0.001) for i in range(12)]
        assert detect_direction_changes(points, min_bearing_change_deg=50.0) == []


class TestDetectClimbSegments:
    def test_monotonic_climb_above_threshold_is_detected(self):
        points = [RoutePoint(distance_m=i * 100.0, lat=47.0, lon=8.5, elevation_m=1000 + i * 20) for i in range(11)]
        segments = detect_climb_segments(points)

        assert len(segments) == 1
        assert segments[0].ascent_m == 200
        assert segments[0].start_distance_m == 0
        assert segments[0].end_distance_m == 1000

    def test_climb_below_threshold_is_not_reported(self):
        points = [RoutePoint(distance_m=i * 100.0, lat=47.0, lon=8.5, elevation_m=1000 + i * 5) for i in range(11)]
        assert detect_climb_segments(points, min_ascent_m=150.0) == []

    def test_small_dip_within_tolerance_does_not_split_the_segment(self):
        elevations = [1000, 1050, 1100, 1090, 1150, 1200, 1250]  # -10m Zwischeneinsenkung
        points = [RoutePoint(distance_m=i * 100.0, lat=47.0, lon=8.5, elevation_m=e) for i, e in enumerate(elevations)]
        segments = detect_climb_segments(points, tolerance_m=20.0)

        assert len(segments) == 1
        assert segments[0].ascent_m == 250

    def test_dip_beyond_tolerance_splits_into_two_segments(self):
        elevations = [1000, 1100, 1200, 1150, 1100, 1250, 1400]  # -100m Abstieg dazwischen
        points = [RoutePoint(distance_m=i * 100.0, lat=47.0, lon=8.5, elevation_m=e) for i, e in enumerate(elevations)]
        segments = detect_climb_segments(points, min_ascent_m=150.0, tolerance_m=20.0)

        assert len(segments) == 2
        assert segments[0].ascent_m == 200  # 1000 -> 1200
        assert segments[1].ascent_m == 300  # 1100 -> 1400

    def test_pure_descent_has_no_climb_segments(self):
        points = [RoutePoint(distance_m=i * 100.0, lat=47.0, lon=8.5, elevation_m=2000 - i * 50) for i in range(10)]
        assert detect_climb_segments(points) == []
