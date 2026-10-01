"""Integrationstest fuer HikingTourAnalysisService (Phase 4) gegen das importierte
Test-Fixture-Wegenetz. Nutzt echtes RoutingService/ElevationProfileService/
EmergencyExitService gegen das Fixture-Netz - nur der externe swisstopo-HTTP-Aufruf ist
gemockt (wie test_elevation_service.py). Das Hoehenprofil wird direkt aus der tatsaechlich
berechneten Routengeometrie abgetastet (echte Koordinaten entlang des Netzes), mit einem
synthetischen Hoehenverlauf - so bleiben Distanzen/Positionen realistisch, ohne einen echten
swisstopo-Request zu brauchen."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from geoalchemy2.shape import to_shape

from app.core.redis_client import get_redis_sync
from app.core.swiss_coords import wgs84_to_lv95
from app.schemas.hiking_tour import HikingTourCreate, PointCreate
from app.services.hiking_tour_analysis_service import HikingTourAnalysisService
from app.services.hiking_tour_service import HikingTourService
from app.services.routing_service import RoutingService
from tests.factories import make_tenant

A = {"lat": 47.00, "lon": 8.50}
C = {"lat": 47.00, "lon": 8.52}


@pytest.fixture(autouse=True)
def _isolated_elevation_cache():
    # Alle Touren hier nutzen dieselben A/C-Koordinaten - ohne das hier wuerde der
    # Hoehenprofil-Cache (Redis, Key = Hash der Routengeometrie, siehe elevation_service.py)
    # zwischen den Tests denselben Eintrag treffen und den jeweils in DIESEM Test gemockten
    # Hoehenverlauf (klimmend vs. flach) ignorieren.
    get_redis_sync().flushdb()
    yield
    get_redis_sync().flushdb()


def _mock_response(body: bytes):
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _profile_body(leg, *, climb: bool) -> bytes:
    line = to_shape(leg.geom)
    n = 40
    points = []
    for i in range(n + 1):
        ratio = i / n
        point = line.interpolate(ratio, normalized=True)
        distance_m = ratio * leg.distance_m
        if not climb:
            elevation = 1000.0
        elif ratio < 0.2:
            elevation = 1000.0
        elif ratio <= 0.5:
            elevation = 1000.0 + (ratio - 0.2) / 0.3 * 300.0
        else:
            elevation = 1300.0
        easting, northing = wgs84_to_lv95(point.y, point.x)
        points.append({"dist": distance_m, "easting": easting, "northing": northing, "alts": {"COMB": elevation}})
    return json.dumps(points).encode("utf-8")


def _prepare_tour(db, tenant_id: int, *, climb: bool):
    service = HikingTourService()
    tour = service.create_tour(
        db,
        HikingTourCreate(title="Analyse-Test", start=PointCreate(**A), end=PointCreate(**C), routing_profile="wanderwege_bevorzugen"),
        tenant_id=tenant_id,
    )
    tour = RoutingService().compute_route(db, tour, profile="wanderwege_bevorzugen")
    body = _profile_body(tour.route_legs[0], climb=climb)
    with patch("app.services.elevation_service.urllib.request.urlopen", side_effect=lambda *a, **kw: _mock_response(body)):
        from app.services.elevation_service import ElevationProfileService

        tour = ElevationProfileService().fetch_and_store(db, tour)
    return tour, body


def test_analyze_inserts_navigation_waypoints_for_a_detected_climb_and_resplits_the_route(db, routing_network):
    tenant = make_tenant(db, "Analyse Verein 1")
    tour, body = _prepare_tour(db, tenant.id, climb=True)
    legs_before = len(tour.route_legs)

    with patch("app.services.elevation_service.urllib.request.urlopen", side_effect=lambda *a, **kw: _mock_response(body)):
        result = HikingTourAnalysisService().analyze(db, tour)

    navigation_waypoints = [wp for wp in result.waypoints if wp.kind == "NAVIGATION" and wp.auto_generated]
    assert len(navigation_waypoints) >= 1
    assert any("Aufstieg" in (wp.description or "") for wp in navigation_waypoints)
    assert len(result.route_legs) > legs_before
    assert result.status == "analyzed"


def test_analyze_is_idempotent_and_does_not_duplicate_points(db, routing_network):
    tenant = make_tenant(db, "Analyse Verein 2")
    tour, body = _prepare_tour(db, tenant.id, climb=True)

    with patch("app.services.elevation_service.urllib.request.urlopen", side_effect=lambda *a, **kw: _mock_response(body)):
        first = HikingTourAnalysisService().analyze(db, tour)
        second = HikingTourAnalysisService().analyze(db, first)

    first_auto_count = len([wp for wp in first.waypoints if wp.auto_generated])
    second_auto_count = len([wp for wp in second.waypoints if wp.auto_generated])
    assert first_auto_count == second_auto_count


def test_analyze_places_a_decision_point_with_metrics_when_there_is_no_climb(db, routing_network):
    tenant = make_tenant(db, "Analyse Verein 3")
    tour, body = _prepare_tour(db, tenant.id, climb=False)

    with patch("app.services.elevation_service.urllib.request.urlopen", side_effect=lambda *a, **kw: _mock_response(body)):
        result = HikingTourAnalysisService().analyze(db, tour)

    decision_waypoints = [wp for wp in result.waypoints if wp.kind == "DECISION"]
    assert len(decision_waypoints) == 1
    decision = decision_waypoints[0]
    assert decision.verification_status == "AUTO_DETECTED"
    assert decision.decision_metrics_json is not None
    assert decision.decision_metrics_json["time_from_start_minutes"] > 0
    assert decision.decision_metrics_json["time_to_end_minutes"] > 0


def test_analyze_finds_a_nearby_emergency_exit_and_links_it_to_the_decision_point(db, routing_network):
    tenant = make_tenant(db, "Analyse Verein 4")
    tour, body = _prepare_tour(db, tenant.id, climb=False)

    with patch("app.services.elevation_service.urllib.request.urlopen", side_effect=lambda *a, **kw: _mock_response(body)):
        result = HikingTourAnalysisService().analyze(db, tour)

    exit_waypoints = [wp for wp in result.waypoints if wp.kind == "EMERGENCY_EXIT"]
    decision = next(wp for wp in result.waypoints if wp.kind == "DECISION")

    assert len(exit_waypoints) == 1
    exit_wp = exit_waypoints[0]
    assert exit_wp.verification_status == "AUTO_DETECTED"
    assert exit_wp.auto_generated is True
    assert exit_wp.exit_metrics_json["distance_m"] > 0
    assert decision.decision_metrics_json["nearest_exit_label"] == exit_wp.label
    assert decision.decision_metrics_json["time_to_exit_minutes"] == pytest.approx(exit_wp.exit_metrics_json["time_to_exit_minutes"])


def test_deleting_an_auto_generated_waypoint_is_allowed(db, routing_network):
    tenant = make_tenant(db, "Analyse Verein 5")
    tour, body = _prepare_tour(db, tenant.id, climb=True)

    with patch("app.services.elevation_service.urllib.request.urlopen", side_effect=lambda *a, **kw: _mock_response(body)):
        result = HikingTourAnalysisService().analyze(db, tour)

    auto_waypoint = next(wp for wp in result.waypoints if wp.auto_generated)
    HikingTourService().delete_waypoint(db, auto_waypoint)  # raises on failure


def test_reanalysis_keeps_end_last_and_does_not_double_back(db, routing_network):
    tenant = make_tenant(db, "Wiederholte Analyse")
    tour, body = _prepare_tour(db, tenant.id, climb=True)
    base_distance = tour.route_distance_m
    with patch("app.services.elevation_service.urllib.request.urlopen", side_effect=lambda *a, **kw: _mock_response(body)):
        for _ in range(2):
            result = HikingTourAnalysisService().analyze(db, tour)
            chain = [w for w in result.waypoints if w.kind != 'EMERGENCY_EXIT']
            assert chain[0].kind == 'START'
            assert chain[-1].kind == 'END'
            assert result.route_distance_m == pytest.approx(base_distance, rel=0.01)
