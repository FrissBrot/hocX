from app.core.break_planning import MarchTableRow, suggest_breaks
from app.core.waypoint_detection import ClimbSegment, RoutePoint


def _rows(total_minutes: float, *, step_minutes: float = 15.0, pace_m_per_min: float = 80.0, ascent_per_min: float = 3.0) -> list[MarchTableRow]:
    rows = []
    minutes = 0.0
    sequence = 0
    while minutes <= total_minutes + 1e-9:
        rows.append(
            MarchTableRow(
                sequence=sequence,
                cumulative_distance_m=minutes * pace_m_per_min,
                cumulative_ascent_m=minutes * ascent_per_min,
                cumulative_duration_minutes=minutes,
            )
        )
        minutes += step_minutes
        sequence += 1
    return rows


class TestSuggestBreaks:
    def test_short_tour_below_the_threshold_gets_no_break(self):
        rows = _rows(60.0)
        suggestions = suggest_breaks(rows=rows, climb_segments=[], elevation_points=[], total_duration_minutes=60.0)
        assert suggestions == []

    def test_break_is_placed_at_a_nearby_climb_end_with_a_matching_reason(self):
        rows = _rows(180.0)
        climb_segments = [ClimbSegment(start_distance_m=0, start_lat=47.0, start_lon=8.5, end_distance_m=8400.0, end_lat=47.1, end_lon=8.5, ascent_m=300.0)]

        suggestions = suggest_breaks(rows=rows, climb_segments=climb_segments, elevation_points=[], total_duration_minutes=180.0)

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert "Ende eines längeren Aufstiegs" in suggestion.reason
        assert suggestion.reason.startswith("Nach ")
        assert "Marschzeit" in suggestion.reason and "hm Aufstieg" in suggestion.reason
        assert abs(suggestion.distance_m - 8400.0) < 1300  # naechstgelegene Wegpunkt-Zeile

    def test_break_falls_back_to_a_flat_section_without_a_nearby_climb_end(self):
        rows = _rows(180.0)

        def elevation(distance_m: float) -> float:
            if distance_m < 8000:
                return 1000 + distance_m * 0.3
            if distance_m <= 8200:
                return 1000 + 8000 * 0.3
            return 1000 + 8000 * 0.3 + (distance_m - 8200) * 0.3

        points = [RoutePoint(distance_m=d, lat=47.0, lon=8.5, elevation_m=elevation(d)) for d in range(0, 14401, 100)]

        suggestions = suggest_breaks(rows=rows, climb_segments=[], elevation_points=points, total_duration_minutes=180.0)

        assert len(suggestions) == 1
        assert "geeigneter flacher Abschnitt" in suggestions[0].reason

    def test_a_long_tour_gets_multiple_breaks_spaced_apart(self):
        rows = _rows(400.0)
        suggestions = suggest_breaks(rows=rows, climb_segments=[], elevation_points=[], total_duration_minutes=400.0)

        assert len(suggestions) >= 2
        for a, b in zip(suggestions, suggestions[1:]):
            row_a = next(r for r in rows if r.sequence == a.after_sequence)
            row_b = next(r for r in rows if r.sequence == b.after_sequence)
            assert row_b.cumulative_duration_minutes - row_a.cumulative_duration_minutes >= 45.0

    def test_no_break_is_suggested_in_the_final_stretch_before_the_end(self):
        rows = _rows(115.0)
        suggestions = suggest_breaks(rows=rows, climb_segments=[], elevation_points=[], total_duration_minutes=115.0, skip_last_minutes=15.0)

        for suggestion in suggestions:
            row = next(r for r in rows if r.sequence == suggestion.after_sequence)
            assert row.cumulative_duration_minutes <= 100.0
