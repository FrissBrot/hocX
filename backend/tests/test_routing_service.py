"""Integrationstests fuer RoutingService gegen das importierte Test-Fixture-Wegenetz
(tests/fixtures/routing_network_sample.geojson, siehe dessen Beschreibung fuer die Topologie).
Setzt voraus, dass das Fixture bereits importiert ist (siehe conftest.py-Fixture
`routing_network`, ruft scripts/import_routing_network.py einmalig pro Testlauf auf - das
Netz selbst liegt ausserhalb der pro-Test-Transaktion, siehe dortigen Kommentar)."""
from __future__ import annotations

import pytest

from app.schemas.hiking_tour import HikingTourCreate, PointCreate
from app.services.hiking_tour_service import HikingTourService
from app.services.routing_service import RoutingError, RoutingService
from tests.factories import make_tenant

# Punkte A/C (Start/Ziel) und weitere aus dem Fixture-Netz - siehe dessen GeoJSON-Datei fuer
# die vollstaendige Topologie (A-B-C = Wanderweg-Umweg, A-D-C = kuerzerer Forstweg-Direktweg).
A = {"lat": 47.00, "lon": 8.50}
C = {"lat": 47.00, "lon": 8.52}
# Weit ausserhalb des Fixture-Netzes - kein Wegenetz in der Naehe.
FAR_AWAY = {"lat": 46.20, "lon": 6.15}
# Im isolierten N7/N8-Wanderweg-Stueck, nicht mit A/C verbunden.
ISLAND = {"lat": 46.0207, "lon": 7.7491}


def _create_tour(db, tenant_id: int, *, start=A, end=C, profile: str) -> object:
    service = HikingTourService()
    return service.create_tour(
        db,
        HikingTourCreate(title="Routing-Test", start=PointCreate(**start), end=PointCreate(**end), routing_profile=profile),
        tenant_id=tenant_id,
    )


def test_wanderwege_bevorzugen_prefers_the_official_trail_despite_the_detour(db, routing_network):
    tenant = make_tenant(db, "Routing Verein 1")
    tour = _create_tour(db, tenant.id, profile="wanderwege_bevorzugen")

    result = RoutingService().compute_route(db, tour, profile="wanderwege_bevorzugen")

    assert len(result.route_legs) == 1
    leg = result.route_legs[0]
    # Der Wanderweg-Umweg A-B-C ist laenger als der direkte Forstweg A-D-C.
    assert leg.distance_m > 2000
    assert result.route_distance_m == pytest.approx(leg.distance_m)


def test_schnellste_route_prefers_the_shorter_forest_road(db, routing_network):
    tenant = make_tenant(db, "Routing Verein 2")
    tour = _create_tour(db, tenant.id, profile="schnellste_route")

    result = RoutingService().compute_route(db, tour, profile="schnellste_route")

    leg = result.route_legs[0]
    # Der direkte Forstweg A-D-C ist deutlich kuerzer als der Wanderweg-Umweg.
    assert leg.distance_m < 1800


def test_the_two_profiles_choose_different_routes_for_the_same_tour(db, routing_network):
    tenant = make_tenant(db, "Routing Verein 3")
    tour = _create_tour(db, tenant.id, profile="wanderwege_bevorzugen")

    # compute_route() mutiert und gibt dieselbe tour-Instanz zurueck - die Distanz muss nach
    # jedem Aufruf sofort gelesen werden, nicht erst am Ende aus zwei (identischen) Referenzen.
    RoutingService().compute_route(db, tour, profile="wanderwege_bevorzugen")
    bevorzugen_distance = tour.route_distance_m
    RoutingService().compute_route(db, tour, profile="schnellste_route")
    schnellste_distance = tour.route_distance_m

    assert bevorzugen_distance != pytest.approx(schnellste_distance)


def test_route_persists_distance_ascent_descent_and_cost_on_the_tour(db, routing_network):
    tenant = make_tenant(db, "Routing Verein 4")
    tour = _create_tour(db, tenant.id, profile="schnellste_route")

    result = RoutingService().compute_route(db, tour, profile="schnellste_route")

    assert result.route_distance_m is not None and result.route_distance_m > 0
    assert result.route_ascent_m is not None and result.route_ascent_m >= 0
    assert result.route_cost is not None and result.route_cost > 0
    assert result.route_computed_at is not None
    assert result.routing_profile == "schnellste_route"


def test_recomputing_a_route_replaces_the_previous_legs(db, routing_network):
    tenant = make_tenant(db, "Routing Verein 5")
    tour = _create_tour(db, tenant.id, profile="schnellste_route")
    service = RoutingService()

    service.compute_route(db, tour, profile="schnellste_route")
    first_leg_count = len(tour.route_legs)
    service.compute_route(db, tour, profile="wanderwege_bevorzugen")

    assert len(tour.route_legs) == first_leg_count  # ersetzt, nicht angehaengt
    assert tour.route_legs[0].routing_profile == "wanderwege_bevorzugen"


def test_no_route_possible_between_disconnected_network_islands(db, routing_network):
    tenant = make_tenant(db, "Routing Verein 6")
    tour = _create_tour(db, tenant.id, start=A, end=ISLAND, profile="schnellste_route")

    with pytest.raises(RoutingError, match="Kein Routing"):
        RoutingService().compute_route(db, tour, profile="schnellste_route")


def test_no_network_near_a_point_raises_a_clear_error(db, routing_network):
    tenant = make_tenant(db, "Routing Verein 7")
    tour = _create_tour(db, tenant.id, start=A, end=FAR_AWAY, profile="schnellste_route")

    with pytest.raises(RoutingError):
        RoutingService().compute_route(db, tour, profile="schnellste_route")


def test_unknown_profile_raises_value_error(db, routing_network):
    tenant = make_tenant(db, "Routing Verein 8")
    tour = _create_tour(db, tenant.id, profile="schnellste_route")

    with pytest.raises(ValueError, match="Unknown routing profile"):
        RoutingService().compute_route(db, tour, profile="ueberhaupt-kein-profil")
