"""Tests für TerrainDangerService mit simuliertem Gelände statt des swisstopo-Dienstes
(Auftrag Abschnitt 23: externe Dienste mocken). Prüft das Zusammenspiel aus dichter
Routenabfrage, Querprofilen und Klassifikation auf einer realistisch langen Strecke."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from shapely.geometry import LineString

from app.core.swiss_coords import lv95_to_wgs84, wgs84_to_lv95
from app.services import terrain_danger_service
from app.services.terrain_danger_service import TerrainDangerService, sample_count

START_E, START_N = 2_640_000.0, 1_160_000.0
ROUTE_LENGTH_M = 3000.0
# Zwischen 1200 und 1500 m fällt das Gelände südlich des Weges mit 120% ab (ausgesetzte
# Querung), sonst ist alles flach.
EXPOSED_FROM_E, EXPOSED_TO_E = START_E + 1200, START_E + 1500


def _terrain(easting: float, northing: float) -> float:
    if EXPOSED_FROM_E <= easting <= EXPOSED_TO_E and northing < START_N:
        return 1500.0 - (START_N - northing) * 1.2
    return 1500.0


def _fake_profile(requested_points: list[int]):
    def fetch_profile(coordinates, nb_points=200):
        requested_points.append(nb_points)
        line = LineString([wgs84_to_lv95(lat, lon) for lon, lat in coordinates])
        samples = []
        for index in range(nb_points):
            distance = line.length * index / (nb_points - 1)
            point = line.interpolate(distance)
            lat, lon = lv95_to_wgs84(point.x, point.y)
            samples.append({"distance_m": distance, "elevation_m": _terrain(point.x, point.y), "lat": lat, "lon": lon})
        return samples
    return fetch_profile


def test_sample_count_targets_ten_metre_spacing_within_limits():
    assert sample_count(500) == 200
    assert sample_count(10_000) == 1001
    assert sample_count(200_000) == 5000


def test_compute_and_store_flags_exposed_traverse_on_long_route(monkeypatch):
    route = [lv95_to_wgs84(START_E + offset, START_N) for offset in (0.0, ROUTE_LENGTH_M)]
    coordinates = [(lon, lat) for lat, lon in route]
    requested_points: list[int] = []
    monkeypatch.setattr(terrain_danger_service.elevation_service, "route_coordinates", lambda tour: coordinates)
    monkeypatch.setattr(terrain_danger_service.elevation_service, "fetch_profile", _fake_profile(requested_points))
    tour = SimpleNamespace(
        route_legs=[SimpleNamespace(distance_m=ROUTE_LENGTH_M, wanderweg_segments_json=[])],
        elevation_profile_json=[{"distance_m": 0}],
        terrain_danger_json=None,
        terrain_danger_computed_at=None,
    )

    TerrainDangerService().compute_and_store(MagicMock(), tour, commit=False)

    # Route dicht (≈10 m), Querlinien doppelt so dicht.
    assert abs(requested_points[0] - sample_count(ROUTE_LENGTH_M)) <= 1  # Rundung der Koordinatenumrechnung
    assert requested_points[1:] == [2 * requested_points[0]] * 2
    dangerous = [segment for segment in tour.terrain_danger_json if segment["danger"] != "normal"]
    assert len(dangerous) == 1
    assert dangerous[0]["danger"] == "steep_exposed"
    # Querung liegt bei 1200-1500 m; die Approximationsformel LV95<->WGS84 und die Markierung
    # beider angrenzenden Intervalle verschieben die Grenzen um wenige Meter.
    assert 1170 <= dangerous[0]["from_m"] <= 1210
    assert 1490 <= dangerous[0]["to_m"] <= 1530
    assert tour.terrain_danger_computed_at is not None
