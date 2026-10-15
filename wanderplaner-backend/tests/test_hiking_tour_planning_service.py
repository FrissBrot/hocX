from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HikingTour
from app.schemas.hiking_tour import HikingTourCreate, HikingTourPlanRequest, PointCreate, ViaPointCreate
from app.services.elevation_service import ElevationServiceError
from app.services.hiking_tour_planning_service import HikingTourPlanningService
from app.services.hiking_tour_service import HikingTourService
from tests.factories import make_caller, make_tenant


def payload():
    return HikingTourCreate(title="Plan-Test", start=PointCreate(lat=47, lon=8.5), end=PointCreate(lat=47, lon=8.52))


def planner():
    calls = []
    def compute(db, tour, *, profile, commit):
        assert not commit
        calls.append("route")
        tour.routing_profile = profile
        tour.route_computed_at = datetime.now(UTC)
    def elevation(db, tour, *, commit):
        assert not commit
        calls.append("elevation")
        tour.elevation_profile_json = [{"distance_m": 0, "elevation_m": 500, "lat": 47, "lon": 8.5}]
        tour.elevation_profile_fetched_at = datetime.now(UTC)
    def terrain_danger(db, tour, *, commit):
        assert not commit
        calls.append("terrain_danger")
        tour.terrain_danger_json = []
        tour.terrain_danger_computed_at = datetime.now(UTC)
    def analyze(db, tour, *, commit):
        assert not commit
        calls.append("analysis")
        tour.status = "analyzed"
    service = HikingTourPlanningService(routing=MagicMock(compute_route=compute),
        elevation=MagicMock(fetch_and_store=elevation),
        terrain_danger=MagicMock(compute_and_store=terrain_danger), analysis=MagicMock(analyze=analyze))
    return service, calls


def test_creation_runs_all_steps_before_committing(db):
    tenant = make_tenant(db, "Plan Creation")
    service, calls = planner()
    tour = service.create(db, payload(), tenant_id=tenant.id)
    assert calls == ["route", "elevation", "terrain_danger", "analysis"]
    assert tour.status == "analyzed"
    assert tour.elevation_profile_json


def test_save_applies_move_addition_deletion_and_preserves_edited_auto_point(db):
    tenant = make_tenant(db, "Plan Save")
    tour = HikingTourService().create_tour(db, payload(), tenant_id=tenant.id)
    first = HikingTourService().add_via_point(db, tour, ViaPointCreate(lat=47, lon=8.51))
    db.refresh(tour)
    first.auto_generated = True
    first.kind = "NAVIGATION"
    db.commit()
    service, calls = planner()
    result = service.save(db, tour, HikingTourPlanRequest(
        routing_profile="schnellste_route",
        updates=[{"id": first.public_id, "lat": 47.001, "lon": 8.51, "break_minutes": 12}],
        additions=[{"lat": 47, "lon": 8.515, "label": "Neuer Via", "break_minutes": 5}],
    ))
    assert calls == ["route", "elevation", "terrain_danger", "analysis"]
    assert [point.kind for point in result.waypoints] == ["START", "USER_DEFINED", "USER_DEFINED", "END"]
    assert [point.sequence for point in result.waypoints] == [0, 1, 2, 3]
    assert result.waypoints[1].public_id == first.public_id
    assert to_shape(result.waypoints[1].point).y == pytest.approx(47.001)
    assert result.waypoints[1].break_minutes == 12
    assert result.waypoints[2].break_minutes == 5
    assert not result.waypoints[1].auto_generated
    service.save(db, result, HikingTourPlanRequest(deletions=[result.waypoints[2].public_id]))
    assert [point.sequence for point in result.waypoints] == [0, 1, 2]


def test_failed_recalculation_rolls_back_position_and_previous_profile(db):
    tenant = make_tenant(db, "Plan Failure")
    tour = HikingTourService().create_tour(db, payload(), tenant_id=tenant.id)
    tour.elevation_profile_json = [{"distance_m": 0, "elevation_m": 900}]
    db.commit()
    point_id = tour.waypoints[0].public_id
    service, _ = planner()
    service.elevation.fetch_and_store = MagicMock(side_effect=ElevationServiceError("swisstopo unavailable"))
    with Session(bind=db.connection(), join_transaction_mode="create_savepoint", autoflush=False) as saving:
        saved_tour = saving.get(HikingTour, tour.id)
        with pytest.raises(ElevationServiceError):
            service.save(saving, saved_tour, HikingTourPlanRequest(updates=[{"id": point_id, "lat": 47.01, "lon": 8.5}]))
        saving.rollback()
        saving.refresh(saved_tour)
        assert to_shape(saved_tour.waypoints[0].point).y == pytest.approx(47)
        assert saved_tour.elevation_profile_json == [{"distance_m": 0, "elevation_m": 900}]



def test_failed_creation_leaves_no_partial_tour(db):
    tenant = make_tenant(db, "Plan Failed Create")
    service, _ = planner()
    service.elevation.fetch_and_store = MagicMock(side_effect=ElevationServiceError("Unavailable"))
    with Session(bind=db.connection(), join_transaction_mode="create_savepoint", autoflush=False) as creating:
        with pytest.raises(ElevationServiceError):
            service.create(creating, payload(), tenant_id=tenant.id)
        creating.rollback()
    assert db.scalars(select(HikingTour).where(HikingTour.tenant_id == tenant.id)).all() == []


def test_rejects_foreign_waypoint_and_start_deletion(db):
    tenant = make_tenant(db, "Plan Validation")
    tour = HikingTourService().create_tour(db, payload(), tenant_id=tenant.id)
    service, calls = planner()
    with pytest.raises(ValueError, match="gehört nicht"):
        service.save(db, tour, HikingTourPlanRequest(updates=[{"id": uuid4(), "lat": 47, "lon": 8.5}]))
    with pytest.raises(ValueError, match="Start und Ziel"):
        service.save(db, tour, HikingTourPlanRequest(deletions=[tour.waypoints[0].public_id]))
    assert calls == []


def test_full_pipeline_with_real_routing_and_analysis(db, routing_network, monkeypatch):
    from shapely.geometry import LineString
    from app.core.swiss_coords import wgs84_to_lv95
    from math import dist

    def profile(coordinates, nb_points=200):
        line = LineString(coordinates)
        length = sum(dist(wgs84_to_lv95(a[1], a[0]), wgs84_to_lv95(b[1], b[0])) for a, b in zip(coordinates, coordinates[1:]))
        return [{"distance_m": length * index / 39, "elevation_m": 500 + index * 4,
                 "lat": line.interpolate(index / 39, normalized=True).y,
                 "lon": line.interpolate(index / 39, normalized=True).x} for index in range(40)]

    def landmarks(self, db, coordinates):
        line = LineString(coordinates)
        start, mid, end = [line.interpolate(fraction, normalized=True) for fraction in (0, 0.5, 1)]
        geometry = [{"lat": point.y, "lon": point.x} for point in (start, mid, end)]
        return [{"tags": {"highway": "path", "name": "Alpweg"}, "nodes": [1, 2, 3], "geometry": geometry},
                {"tags": {"highway": "path"}, "nodes": [2, 4], "geometry": [geometry[1], {"lat": mid.y + 0.001, "lon": mid.x}]}]

    monkeypatch.setattr("app.services.elevation_service.fetch_profile", profile)
    monkeypatch.setattr("app.services.route_landmark_service.RouteLandmarkService.fetch", landmarks)
    tenant = make_tenant(db, "Full Planning")
    service = HikingTourPlanningService()
    tour = service.create(db, payload(), tenant_id=tenant.id)
    assert tour.status == "analyzed"
    assert tour.route_legs and tour.elevation_profile_json
    assert any(point.auto_generated for point in tour.waypoints)
    old_points = {point.public_id for point in tour.waypoints if point.auto_generated}
    start = next(point for point in tour.waypoints if point.kind == "START")
    tour = service.save(db, tour, HikingTourPlanRequest(
        updates=[{"id": start.public_id, "lat": 47.0, "lon": 8.5001}], routing_profile="schnellste_route"))
    assert tour.status == "analyzed"
    assert tour.routing_profile == "schnellste_route"
    assert tour.route_legs and tour.elevation_profile_json
    assert old_points.isdisjoint({point.public_id for point in tour.waypoints})

    # Auch ein späterer Abruffehler muss die komplette vorhandene Geometrie erhalten.
    old_geometry = [to_shape(leg.geom).wkt for leg in tour.route_legs]
    old_profile = tour.elevation_profile_json
    with Session(bind=db.connection(), join_transaction_mode="create_savepoint", autoflush=False) as saving:
        saved_tour = saving.get(HikingTour, tour.id)
        service.elevation.fetch_and_store = MagicMock(side_effect=ElevationServiceError("Unavailable"))
        with pytest.raises(ElevationServiceError):
            service.save(saving, saved_tour, HikingTourPlanRequest(routing_profile="wanderwege_bevorzugen"))
        saving.rollback()
        saving.refresh(saved_tour)
        assert [to_shape(leg.geom).wkt for leg in saved_tour.route_legs] == old_geometry
        assert saved_tour.elevation_profile_json == old_profile


def test_plan_endpoint_checks_tenant_and_revision_before_recalculation(db, monkeypatch):
    from datetime import timedelta
    from fastapi import HTTPException
    from app.api.routes import hiking_tours

    planning = MagicMock()
    monkeypatch.setattr(hiking_tours, "planning_service", planning)
    owner = make_tenant(db, "Plan Owner")
    other = make_tenant(db, "Plan Other")
    tour = HikingTourService().create_tour(db, payload(), tenant_id=owner.id)
    with pytest.raises(HTTPException) as foreign:
        hiking_tours.save_hiking_tour_plan(tour.public_id, HikingTourPlanRequest(), db, make_caller(other.id))
    assert foreign.value.status_code == 404
    with pytest.raises(HTTPException) as conflict:
        hiking_tours.save_hiking_tour_plan(tour.public_id,
            HikingTourPlanRequest(expected_updated_at=tour.updated_at - timedelta(seconds=1)), db,
            make_caller(owner.id))
    assert conflict.value.status_code == 409
    planning.save.assert_not_called()
