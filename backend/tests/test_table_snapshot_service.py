"""Tests for table_snapshot_service.py - the cycle-boundary snapshot creation and
due-check logic backing the historical-table-view feature for user-created lists."""
from datetime import date

from app.core.cycle_utils import get_cycle_year
from app.models.entities import TableSnapshot
from app.services.table_snapshot_config import SNAPSHOT_TABLES
from app.services.table_snapshot_service import TableSnapshotService, run_due_cycle_snapshots

from tests.factories import make_cycle_config, make_list_definition, make_list_entry, make_tenant


def _by_table(written):
    return {row.table_name: row for row in written}


def test_create_snapshot_writes_one_row_per_configured_table(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    make_list_definition(db, tenant.id, name="List One")
    make_list_definition(db, tenant.id, name="List Two")

    written = TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2024)

    assert len(written) == len(SNAPSHOT_TABLES)
    by_table = _by_table(written)
    definition_snapshot = by_table["list_definition"]
    assert definition_snapshot.row_count == 2
    assert {row["name"] for row in definition_snapshot.snapshot_json} == {"List One", "List Two"}
    assert definition_snapshot.is_edited is False


def test_create_snapshot_list_definition_is_scoped_to_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    cycle_config = make_cycle_config(db, tenant_a.id)
    make_list_definition(db, tenant_a.id, name="In Tenant A")
    make_list_definition(db, tenant_b.id, name="In Tenant B")

    written = TableSnapshotService().create_snapshot(db, tenant_id=tenant_a.id, cycle_config=cycle_config, cycle_year=2024)

    names = {row["name"] for row in _by_table(written)["list_definition"].snapshot_json}
    assert names == {"In Tenant A"}


def test_create_snapshot_list_entry_via_transitive_join(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id)
    make_list_entry(db, definition.id, sort_index=0, column_one_value={"text_value": "a"})
    make_list_entry(db, definition.id, sort_index=1, column_one_value={"text_value": "b"})

    written = TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2024)

    list_entry_snapshot = _by_table(written)["list_entry"]
    assert list_entry_snapshot.row_count == 2
    assert {row["list_definition_id"] for row in list_entry_snapshot.snapshot_json} == {definition.id}


def test_create_snapshot_list_entry_is_scoped_to_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    cycle_config = make_cycle_config(db, tenant_a.id)
    definition_a = make_list_definition(db, tenant_a.id)
    definition_b = make_list_definition(db, tenant_b.id)
    make_list_entry(db, definition_a.id, column_one_value={"text_value": "in tenant a"})
    make_list_entry(db, definition_b.id, column_one_value={"text_value": "in tenant b"})

    written = TableSnapshotService().create_snapshot(db, tenant_id=tenant_a.id, cycle_config=cycle_config, cycle_year=2024)

    list_entry_snapshot = _by_table(written)["list_entry"]
    assert list_entry_snapshot.row_count == 1
    assert list_entry_snapshot.snapshot_json[0]["list_definition_id"] == definition_a.id


def test_create_snapshot_skips_existing_by_default(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    make_list_definition(db, tenant.id, name="Alice")
    service = TableSnapshotService()

    first = _by_table(service.create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2024))["list_definition"]
    make_list_definition(db, tenant.id, name="Bob")
    second = _by_table(service.create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2024))["list_definition"]

    assert second.id == first.id
    assert second.row_count == 1  # unchanged - "Bob" was added after the snapshot, not included


def test_run_due_cycle_snapshots_creates_snapshot_for_just_ended_cycle(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, reset_month=12, reset_day=31)
    make_list_definition(db, tenant.id)

    run_due_cycle_snapshots(db, TableSnapshotService())

    expected_cycle_year = get_cycle_year(date.today(), 12, 31) - 1
    snapshot = db.query(TableSnapshot).filter_by(
        tenant_id=tenant.id, cycle_config_id=cycle_config.id, cycle_year=expected_cycle_year, table_name="list_definition"
    ).one()
    assert snapshot.row_count == 1


def test_run_due_cycle_snapshots_is_idempotent(db):
    tenant = make_tenant(db)
    make_cycle_config(db, tenant.id)
    make_list_definition(db, tenant.id)
    service = TableSnapshotService()

    run_due_cycle_snapshots(db, service)
    count_after_first = db.query(TableSnapshot).filter_by(tenant_id=tenant.id).count()
    run_due_cycle_snapshots(db, service)
    count_after_second = db.query(TableSnapshot).filter_by(tenant_id=tenant.id).count()

    assert count_after_first == len(SNAPSHOT_TABLES)
    assert count_after_second == len(SNAPSHOT_TABLES)


def test_run_due_cycle_snapshots_backfills_a_table_added_to_config_later(db, monkeypatch):
    """Regression test: a table added to SNAPSHOT_TABLES after a cycle was already
    (partially) snapshotted must still get backfilled on the next daily-loop tick, not
    silently skipped forever because the cycle already "has a snapshot" for some other
    table. Observed live when the table list was expanded after a partial snapshot
    already existed for a real dev tenant."""
    import app.services.table_snapshot_service as svc

    tenant = make_tenant(db)
    make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id)
    make_list_entry(db, definition.id)
    service = TableSnapshotService()
    full_tables = svc.SNAPSHOT_TABLES

    monkeypatch.setattr(svc, "SNAPSHOT_TABLES", {"list_definition": full_tables["list_definition"]})
    run_due_cycle_snapshots(db, service)
    assert db.query(TableSnapshot).filter_by(tenant_id=tenant.id).count() == 1

    monkeypatch.setattr(svc, "SNAPSHOT_TABLES", full_tables)
    run_due_cycle_snapshots(db, service)
    written_tables = {row.table_name for row in db.query(TableSnapshot).filter_by(tenant_id=tenant.id)}
    assert written_tables == set(full_tables.keys())


def test_run_due_cycle_snapshots_never_overwrites_a_historical_edit(db):
    tenant = make_tenant(db)
    make_cycle_config(db, tenant.id)
    make_list_definition(db, tenant.id)
    service = TableSnapshotService()

    run_due_cycle_snapshots(db, service)
    snapshot = db.query(TableSnapshot).filter_by(tenant_id=tenant.id, table_name="list_definition").one()
    snapshot.snapshot_json = [{**snapshot.snapshot_json[0], "name": "Edited By Admin"}]
    snapshot.is_edited = True
    db.commit()

    make_list_definition(db, tenant.id, name="Second List")
    run_due_cycle_snapshots(db, service)

    refreshed = db.query(TableSnapshot).filter_by(tenant_id=tenant.id, table_name="list_definition").one()
    assert refreshed.is_edited is True
    assert refreshed.snapshot_json[0]["name"] == "Edited By Admin"
    assert refreshed.row_count == 1
