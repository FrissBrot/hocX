"""Unit-Tests fuer app/core/march_time.py. Die leistungskilometer()-Faelle nutzen wo moeglich
die exakten Zahlen aus der vom Nutzer bereitgestellten Referenzdatei "Marschtabelle_
Zeitberechnung.xlsx" (Jubla-Vorlage, Blatt "Beispiel": Vrin-Disrut-Greina-Campo), nicht nur
synthetische Werte - direkt gegen die reale Quelle nachvollziehbar (siehe Wiki-Seite
"Wanderplaner")."""
from __future__ import annotations

from datetime import time

import pytest

from app.core.march_time import (
    DEFAULT_SPEED_FACTOR_KMH,
    MarchTimeLegInput,
    MarchTimeWaypointInput,
    build_march_table,
    gradient_percent,
    leistungskilometer,
    resolve_speed_factor_kmh,
)


# --- leistungskilometer, gegen die xlsx-Beispielroute -------------------------------------


def test_ascent_segment_matches_xlsx_row9_cons():
    # Vrin -> Cons: 1 km, 100 Hm Aufstieg -> 2.0 Lkm (xlsx: F9 = 2)
    assert leistungskilometer(length_m=1000, ascent_m=100, descent_m=0) == pytest.approx(2.0)


def test_steep_descent_segment_matches_xlsx_row14_camona():
    # Pass Diesrut -> Camona: 1 km, 234 Hm Abstieg bei -23.4% (>20%) -> 2.56 Lkm (xlsx: F14)
    assert leistungskilometer(length_m=1000, ascent_m=0, descent_m=234) == pytest.approx(2.56)


def test_mild_descent_segment_matches_xlsx_row23_scaletta():
    # bei Scaletta Huette: 1.3 km, 150 Hm Abstieg bei -11.5% (<20%, kein Aufschlag) -> 1.3 Lkm
    assert leistungskilometer(length_m=1300, ascent_m=0, descent_m=150) == pytest.approx(1.3)


def test_gradient_percent_zero_length_is_zero():
    assert gradient_percent(0, 100) == 0.0


# --- resolve_speed_factor_kmh ---------------------------------------------------------------


def test_preset_untrainiert_mit_gepaeck():
    assert resolve_speed_factor_kmh(group_type="untrainiert", luggage_type="mit_gepaeck", override_kmh=None) == 4.0


def test_preset_trainiert_ohne_gepaeck():
    assert resolve_speed_factor_kmh(group_type="trainiert", luggage_type="ohne_gepaeck", override_kmh=None) == 6.0


def test_manual_override_wins_over_preset():
    assert resolve_speed_factor_kmh(group_type="trainiert", luggage_type="ohne_gepaeck", override_kmh=3.5) == 3.5


def test_unknown_combination_falls_back_to_default():
    assert resolve_speed_factor_kmh(group_type=None, luggage_type=None, override_kmh=None) == DEFAULT_SPEED_FACTOR_KMH


# --- build_march_table -----------------------------------------------------------------------


def _wp(sequence, kind, label=None, break_minutes=0, break_reason=None) -> MarchTimeWaypointInput:
    return MarchTimeWaypointInput(sequence=sequence, label=label, kind=kind, break_minutes=break_minutes, break_reason=break_reason)


def test_build_march_table_start_end_only():
    table = build_march_table(
        waypoints=[_wp(0, "START"), _wp(1, "END")],
        legs=[MarchTimeLegInput(distance_m=2000, ascent_m=200, descent_m=0)],
        speed_factor_kmh=4.0,
        planned_start_time=None,
    )

    assert len(table.entries) == 2
    assert table.entries[0].cumulative_lkm == 0
    # 2 km + 200 Hm/100 = 4 Lkm, bei 4 Lkm/h = 60 min
    assert table.entries[1].segment_lkm == pytest.approx(4.0)
    assert table.entries[1].segment_duration_minutes == pytest.approx(60.0)
    assert table.summary.total_lkm == pytest.approx(4.0)
    assert table.summary.total_duration_minutes == pytest.approx(60.0)
    assert table.summary.break_duration_minutes == 0


def test_build_march_table_computes_planned_arrival_and_departure_with_break():
    table = build_march_table(
        waypoints=[_wp(0, "START"), _wp(1, "USER_DEFINED", break_minutes=30, break_reason="Mittagspause"), _wp(2, "END")],
        legs=[
            MarchTimeLegInput(distance_m=1000, ascent_m=0, descent_m=0),  # 1 Lkm, 4 Lkm/h -> 15 min
            MarchTimeLegInput(distance_m=1000, ascent_m=0, descent_m=0),
        ],
        speed_factor_kmh=4.0,
        planned_start_time=time(9, 0),
    )

    via = table.entries[1]
    assert via.planned_arrival == time(9, 15)
    assert via.break_minutes == 30
    assert via.planned_departure == time(9, 45)
    assert via.remarks == "Mittagspause"

    end = table.entries[2]
    assert end.planned_arrival == time(10, 0)
    assert table.summary.break_duration_minutes == 30
    assert table.summary.walking_duration_minutes == pytest.approx(30.0)
    assert table.summary.total_duration_minutes == pytest.approx(60.0)


def test_build_march_table_requires_matching_leg_count():
    with pytest.raises(ValueError, match="Routenabschnitte"):
        build_march_table(
            waypoints=[_wp(0, "START"), _wp(1, "END")],
            legs=[],
            speed_factor_kmh=4.0,
            planned_start_time=None,
        )


def test_build_march_table_requires_at_least_one_waypoint():
    with pytest.raises(ValueError, match="mindestens einen Wegpunkt"):
        build_march_table(waypoints=[], legs=[], speed_factor_kmh=4.0, planned_start_time=None)


def test_build_march_table_requires_positive_speed_factor():
    with pytest.raises(ValueError, match="positiv"):
        build_march_table(
            waypoints=[_wp(0, "START"), _wp(1, "END")],
            legs=[MarchTimeLegInput(distance_m=1000, ascent_m=0, descent_m=0)],
            speed_factor_kmh=0,
            planned_start_time=None,
        )
