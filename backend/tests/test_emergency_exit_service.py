"""Integrationstest fuer EmergencyExitService gegen das importierte Test-Fixture-Wegenetz
(tests/fixtures/routing_network_sample.geojson). Die Kante E5 (A -> (8.495, 46.995)) ist dort
extra als `wegtyp = 'normalstrasse'` angelegt - genau fuer diesen Testfall."""
from __future__ import annotations

from app.services.emergency_exit_service import EmergencyExitService

A = {"lat": 47.00, "lon": 8.50}
C = {"lat": 47.00, "lon": 8.52}
FAR_AWAY = {"lat": 46.20, "lon": 6.15}
ISLAND = {"lat": 46.0207, "lon": 7.7491}


def test_finds_the_road_edge_directly_from_its_own_vertex(db, routing_network):
    finding = EmergencyExitService().find_exit(db, lat=A["lat"], lon=A["lon"], profile="schnellste_route", speed_factor_kmh=4.0)

    assert finding is not None
    assert finding.distance_m > 0
    assert finding.time_to_exit_minutes > 0
    assert finding.exit_lat == 46.995
    assert finding.exit_lon == 8.495


def test_finds_the_road_edge_via_a_multi_hop_path(db, routing_network):
    finding = EmergencyExitService().find_exit(db, lat=C["lat"], lon=C["lon"], profile="schnellste_route", speed_factor_kmh=4.0)

    assert finding is not None
    # A selbst liegt schon an der Strassenkante E5 - von C aus ist A damit der naechste
    # "Strassen-Knoten", nicht erst deren fernes Ende (8.495, 46.995).
    assert finding.exit_lat == A["lat"]
    assert finding.exit_lon == A["lon"]
    assert finding.distance_m > 1000


def test_returns_none_far_away_from_any_network(db, routing_network):
    finding = EmergencyExitService().find_exit(db, lat=FAR_AWAY["lat"], lon=FAR_AWAY["lon"], profile="schnellste_route", speed_factor_kmh=4.0)
    assert finding is None


def test_returns_none_from_an_isolated_network_segment_without_road_access(db, routing_network):
    finding = EmergencyExitService().find_exit(db, lat=ISLAND["lat"], lon=ISLAND["lon"], profile="schnellste_route", speed_factor_kmh=4.0)
    assert finding is None
