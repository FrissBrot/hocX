"""Bestehende automatische Namen bereinigen, manuelle Namen erhalten."""
from pathlib import Path
from runpy import run_path

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.schemas.hiking_tour import HikingTourCreate, PointCreate, ViaPointCreate
from app.services.hiking_tour_service import HikingTourService
from tests.factories import make_tenant


def test_migration_removes_old_type_and_distance_additions_only_from_auto_names(db):
    point = {"lat": 47.0489, "lon": 8.4949}
    names = ["NA KP Oberalp · km 1.00 (2)", "KP · km 2.00", "Bach Alpbach", "NA Unteralp"]
    tenant = make_tenant(db, "Punktnamen Migration")
    tour = HikingTourService().create_tour(db, HikingTourCreate(
        title="Punktnamen", start=PointCreate(**point), end=PointCreate(**point),
        via_points=[ViaPointCreate(**point, label=name) for name in names]), tenant_id=tenant.id)
    for waypoint in tour.waypoints[1:4]:
        waypoint.auto_generated = True
    db.flush()
    migration = run_path(str(Path(__file__).parents[1] / "alembic/versions/0103_waypoint_environment_names.py"))
    with Operations.context(MigrationContext.configure(db.connection())):
        migration["upgrade"]()
    db.expire_all()
    assert [waypoint.label for waypoint in tour.waypoints[1:5]] == ["Oberalp", None, "Alpbach", "NA Unteralp"]
