"""Regression tests for HikingTourService (Wanderplaner Phase 1: Basis-CRUD).

Covers tour creation (start/end/via-point sequencing), tenant isolation (the recurring
IDOR-shaped bug class in this codebase, see test_finance_tenant_scoping.py for the same
pattern elsewhere), waypoint mutation (add/move/delete, START/END protection), and the
Schweiz/Liechtenstein bounding-box validation at the schema boundary."""
from __future__ import annotations

import pytest
from geoalchemy2.shape import to_shape

from app.schemas.hiking_tour import HikingTourCreate, HikingTourUpdate, PointCreate, ViaPointCreate, WaypointUpdate
from app.services.hiking_tour_service import HikingTourService
from tests.factories import make_tenant

RIGI_KULM = {"lat": 47.0576, "lon": 8.4883}
GOLDAU = {"lat": 47.0512, "lon": 8.5478}
KLOESTERLI = {"lat": 47.0489, "lon": 8.4949}


def _basic_payload(**overrides) -> HikingTourCreate:
    data = {
        "title": "Rigi Kulm ab Goldau",
        "start": PointCreate(**GOLDAU),
        "end": PointCreate(**RIGI_KULM),
    }
    data.update(overrides)
    return HikingTourCreate(**data)


# --- create_tour -------------------------------------------------------------------------


def test_create_tour_basic(db):
    tenant = make_tenant(db, "Wandersektion")
    service = HikingTourService()

    tour = service.create_tour(db, _basic_payload(), tenant_id=tenant.id)

    assert tour.id is not None
    assert tour.tenant_id == tenant.id
    assert tour.status == "draft"
    assert len(tour.waypoints) == 2
    assert [wp.kind for wp in tour.waypoints] == ["START", "END"]
    assert [wp.sequence for wp in tour.waypoints] == [0, 1]

    start_point = to_shape(tour.waypoints[0].point)
    assert start_point.y == pytest.approx(GOLDAU["lat"])
    assert start_point.x == pytest.approx(GOLDAU["lon"])


def test_create_tour_with_via_points_sequences_in_order(db):
    tenant = make_tenant(db, "Wandersektion Via")
    service = HikingTourService()

    tour = service.create_tour(
        db,
        _basic_payload(via_points=[ViaPointCreate(**KLOESTERLI, label="Kloesterli")]),
        tenant_id=tenant.id,
    )

    assert [wp.kind for wp in tour.waypoints] == ["START", "USER_DEFINED", "END"]
    assert [wp.sequence for wp in tour.waypoints] == [0, 1, 2]
    assert tour.waypoints[1].label == "Kloesterli"


def test_create_tour_rejects_point_outside_switzerland():
    with pytest.raises(ValueError, match="ausserhalb der Schweiz"):
        PointCreate(lat=48.8566, lon=2.3522)  # Paris


# --- tenant isolation --------------------------------------------------------------------


def test_list_tours_is_tenant_scoped(db):
    tenant_a = make_tenant(db, "Verein A")
    tenant_b = make_tenant(db, "Verein B")
    service = HikingTourService()
    service.create_tour(db, _basic_payload(title="Tour A"), tenant_id=tenant_a.id)
    service.create_tour(db, _basic_payload(title="Tour B"), tenant_id=tenant_b.id)

    tours_a = service.list_tours(db, tenant_id=tenant_a.id)

    assert [t.title for t in tours_a] == ["Tour A"]


def test_get_tour_from_foreign_tenant_returns_none(db):
    tenant_a = make_tenant(db, "Verein A2")
    tenant_b = make_tenant(db, "Verein B2")
    service = HikingTourService()
    tour = service.create_tour(db, _basic_payload(), tenant_id=tenant_a.id)

    assert service.get_tour(db, tour.public_id, tenant_id=tenant_b.id) is None
    assert service.get_tour(db, tour.public_id, tenant_id=tenant_a.id) is not None


# --- waypoint mutation ---------------------------------------------------------------------


def test_add_via_point_inserts_before_end_and_shifts_it(db):
    tenant = make_tenant(db, "Verein Via")
    service = HikingTourService()
    tour = service.create_tour(db, _basic_payload(), tenant_id=tenant.id)

    service.add_via_point(db, tour, ViaPointCreate(**KLOESTERLI, label="Kloesterli"))
    db.refresh(tour)

    assert [(wp.kind, wp.sequence) for wp in tour.waypoints] == [
        ("START", 0),
        ("USER_DEFINED", 1),
        ("END", 2),
    ]


def test_update_waypoint_moves_point(db):
    tenant = make_tenant(db, "Verein Move")
    service = HikingTourService()
    tour = service.create_tour(db, _basic_payload(), tenant_id=tenant.id)
    start = tour.waypoints[0]

    updated = service.update_waypoint(db, start, WaypointUpdate(lat=KLOESTERLI["lat"], lon=KLOESTERLI["lon"]))

    point = to_shape(updated.point)
    assert point.y == pytest.approx(KLOESTERLI["lat"])
    assert point.x == pytest.approx(KLOESTERLI["lon"])


def test_delete_start_waypoint_raises(db):
    tenant = make_tenant(db, "Verein Delete Start")
    service = HikingTourService()
    tour = service.create_tour(db, _basic_payload(), tenant_id=tenant.id)
    start = tour.waypoints[0]

    with pytest.raises(ValueError, match="koennen nicht geloescht werden"):
        service.delete_waypoint(db, start)


def test_delete_user_defined_waypoint_succeeds(db):
    tenant = make_tenant(db, "Verein Delete Via")
    service = HikingTourService()
    tour = service.create_tour(db, _basic_payload(), tenant_id=tenant.id)
    via = service.add_via_point(db, tour, ViaPointCreate(**KLOESTERLI))

    service.delete_waypoint(db, via)
    db.refresh(tour)

    assert [wp.kind for wp in tour.waypoints] == ["START", "END"]


# --- update_tour ---------------------------------------------------------------------------


def test_update_tour_only_changes_given_fields(db):
    tenant = make_tenant(db, "Verein Update")
    service = HikingTourService()
    tour = service.create_tour(db, _basic_payload(description="Alt"), tenant_id=tenant.id)

    updated = service.update_tour(db, tour, HikingTourUpdate(title="Neuer Titel"))

    assert updated.title == "Neuer Titel"
    assert updated.description == "Alt"


def test_unnamed_via_points_use_unique_local_environment_and_preserve_custom_names(db):
    from sqlalchemy import text
    tenant = make_tenant(db, "Via Ortsnamen")
    service = HikingTourService()
    db.execute(text("""INSERT INTO hiking_landmark (osm_type, osm_id, tags, geom)
        VALUES ('node', 99101, '{"name":"Rigi Klösterli"}',
            ST_Transform(ST_SetSRID(ST_MakePoint(8.4949,47.0489),4326),2056)),
            ('node', 99102, '{"name":"Klosterweg"}',
            ST_Transform(ST_SetSRID(ST_MakePoint(8.4954,47.0489),4326),2056))"""))
    tour = service.create_tour(db, _basic_payload(via_points=[ViaPointCreate(**KLOESTERLI)]), tenant_id=tenant.id)
    assert tour.waypoints[1].label == "Rigi Klösterli"
    added = service.add_via_point(db, tour, ViaPointCreate(**KLOESTERLI))
    assert added.label == "Rigi Klösterli / Klosterweg"
    assert service.add_via_point(db, tour, ViaPointCreate(**KLOESTERLI, label="Sammelpunkt")).label == "Sammelpunkt"
    labels = [point.label.casefold() for point in tour.waypoints if point.label]
    assert len(labels) == len(set(labels))
