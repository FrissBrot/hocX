from app.core.decision_points import DecisionRow, ExitCandidate, compute_decision_metrics, find_decision_candidates
from app.core.waypoint_detection import ClimbSegment, RoutePoint


def _flat_points(total_distance_m: float, *, step_m: float = 500.0) -> list[RoutePoint]:
    points = []
    distance = 0.0
    while distance <= total_distance_m:
        points.append(RoutePoint(distance_m=distance, lat=47.0 + distance * 0.00001, lon=8.5, elevation_m=1000))
        distance += step_m
    return points


class TestFindDecisionCandidates:
    def test_a_candidate_is_placed_before_each_climb_segment(self):
        segments = [
            ClimbSegment(start_distance_m=1000, start_lat=47.01, start_lon=8.5, end_distance_m=3000, end_lat=47.03, end_lon=8.5, ascent_m=400),
            ClimbSegment(start_distance_m=6000, start_lat=47.06, start_lon=8.5, end_distance_m=7000, end_lat=47.07, end_lon=8.5, ascent_m=200),
        ]
        candidates = find_decision_candidates(climb_segments=segments, elevation_points=_flat_points(10000))

        assert [c.distance_m for c in candidates] == [1000, 6000]
        assert candidates[0].lat == 47.01
        assert "400" in candidates[0].reason
        assert "letzter guter Punkt" in candidates[0].reason

    def test_falls_back_to_the_halfway_point_without_any_climb_segment(self):
        candidates = find_decision_candidates(climb_segments=[], elevation_points=_flat_points(10000))

        assert len(candidates) == 1
        assert candidates[0].distance_m == 5000
        assert "halber Strecke" in candidates[0].reason
        assert candidates[0].lat == 47.05

    def test_no_candidates_for_a_zero_length_route_without_climbs(self):
        assert find_decision_candidates(climb_segments=[], elevation_points=[]) == []


class TestComputeDecisionMetrics:
    def test_time_back_accounts_for_reversed_ascent_and_descent(self):
        # 5km mit 500m Aufstieg, 0m Abstieg bis hierher: der Rueckweg ist dann 5km bergab -
        # das ist SCHNELLER als der Hinweg (kein Aufschlag unter der 20%-Gefaelle-Schwelle).
        row = DecisionRow(sequence=2, cumulative_distance_m=5000, cumulative_ascent_m=500, cumulative_descent_m=0, cumulative_duration_minutes=90)
        metrics = compute_decision_metrics(row=row, total_duration_minutes=200, speed_factor_kmh=4.0, nearest_exit=None)

        assert metrics.time_from_start_minutes == 90
        assert metrics.time_to_end_minutes == 110
        assert metrics.time_back_minutes < metrics.time_from_start_minutes
        assert metrics.nearest_exit_label is None

    def test_nearest_exit_metrics_are_passed_through(self):
        row = DecisionRow(sequence=1, cumulative_distance_m=2000, cumulative_ascent_m=100, cumulative_descent_m=50, cumulative_duration_minutes=30)
        exit_candidate = ExitCandidate(waypoint_label="Ausstieg Alp Sura", distance_from_route_m=350.0, time_to_exit_minutes=12.0)

        metrics = compute_decision_metrics(row=row, total_duration_minutes=150, speed_factor_kmh=4.0, nearest_exit=exit_candidate)

        assert metrics.nearest_exit_label == "Ausstieg Alp Sura"
        assert metrics.time_to_exit_minutes == 12.0
        assert metrics.distance_to_exit_m == 350.0
