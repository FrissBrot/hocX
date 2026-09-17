"""Tests for table_snapshot_service.py - the cycle-boundary snapshot creation and
due-check logic backing the historical-table-view feature for user-created lists."""
from datetime import date

import pytest

from app.core.cycle_utils import get_cycle_year
from app.models.entities import TableSnapshot
from app.services.table_snapshot_config import SNAPSHOT_TABLES
from app.services.table_snapshot_service import ReconstructionIdentityError, TableSnapshotService, run_due_cycle_snapshots

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


def test_reconstruct_list_period_creates_gap_snapshot_from_live_data(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")
    entry = make_list_entry(db, definition.id, sort_index=0, column_one_value={"text_value": "a"})

    TableSnapshotService().reconstruct_list_period(
        db,
        tenant_id=tenant.id,
        cycle_config=cycle_config,
        cycle_year=2020,
        list_public_id=str(definition.public_id),
        definition_values={
            "name": "Alice's List (reconstructed)",
            "description": None,
            "column_one_title": definition.column_one_title,
            "column_one_value_type": definition.column_one_value_type,
            "column_two_title": definition.column_two_title,
            "column_two_value_type": definition.column_two_value_type,
            "is_active": True,
        },
        entry_payloads=[
            {"public_id": str(entry.public_id), "sort_index": 0, "column_one_value_json": {"text_value": "reconstructed"}, "column_two_value_json": {}},
        ],
        edited_by=1,
    )

    definition_snapshot = db.query(TableSnapshot).filter_by(
        tenant_id=tenant.id, cycle_config_id=cycle_config.id, cycle_year=2020, table_name="list_definition"
    ).one()
    assert definition_snapshot.row_count == 1
    assert definition_snapshot.snapshot_json[0]["id"] == definition.id
    assert definition_snapshot.snapshot_json[0]["name"] == "Alice's List (reconstructed)"
    assert definition_snapshot.is_edited is True

    entry_snapshot = db.query(TableSnapshot).filter_by(
        tenant_id=tenant.id, cycle_config_id=cycle_config.id, cycle_year=2020, table_name="list_entry"
    ).one()
    assert entry_snapshot.row_count == 1
    assert entry_snapshot.snapshot_json[0]["id"] == entry.id
    assert entry_snapshot.snapshot_json[0]["column_one_value_json"] == {"text_value": "reconstructed"}


def test_reconstruct_list_period_does_not_disturb_other_lists_in_same_period(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition_a = make_list_definition(db, tenant.id, name="List A")
    definition_b = make_list_definition(db, tenant.id, name="List B")
    entry_b = make_list_entry(db, definition_b.id, column_one_value={"text_value": "b1"})

    # List B already has a snapshot for 2020 (e.g. reconstructed earlier or auto-captured).
    TableSnapshotService().reconstruct_list_period(
        db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2020,
        list_public_id=str(definition_b.public_id),
        definition_values={"name": definition_b.name, "column_one_title": "x", "column_one_value_type": "text", "column_two_title": "y", "column_two_value_type": "text", "is_active": True},
        entry_payloads=[{"public_id": str(entry_b.public_id), "sort_index": 0, "column_one_value_json": {"text_value": "b1"}, "column_two_value_json": {}}],
        edited_by=1,
    )

    # Now reconstruct List A for the same period - must not remove List B's rows.
    TableSnapshotService().reconstruct_list_period(
        db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2020,
        list_public_id=str(definition_a.public_id),
        definition_values={"name": definition_a.name, "column_one_title": "x", "column_one_value_type": "text", "column_two_title": "y", "column_two_value_type": "text", "is_active": True},
        entry_payloads=[],
        edited_by=1,
    )

    definition_snapshot = db.query(TableSnapshot).filter_by(
        tenant_id=tenant.id, cycle_config_id=cycle_config.id, cycle_year=2020, table_name="list_definition"
    ).one()
    assert {row["id"] for row in definition_snapshot.snapshot_json} == {definition_a.id, definition_b.id}

    entry_snapshot = db.query(TableSnapshot).filter_by(
        tenant_id=tenant.id, cycle_config_id=cycle_config.id, cycle_year=2020, table_name="list_entry"
    ).one()
    assert {row["id"] for row in entry_snapshot.snapshot_json} == {entry_b.id}


def test_reconstruct_list_period_rejects_unknown_entry(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id)

    with pytest.raises(ReconstructionIdentityError):
        TableSnapshotService().reconstruct_list_period(
            db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2020,
            list_public_id=str(definition.public_id),
            definition_values={"name": definition.name, "column_one_title": "x", "column_one_value_type": "text", "column_two_title": "y", "column_two_value_type": "text", "is_active": True},
            entry_payloads=[{"public_id": "00000000-0000-0000-0000-000000000000", "sort_index": 0, "column_one_value_json": {}, "column_two_value_json": {}}],
            edited_by=1,
        )


def test_reconstruct_list_period_rejects_unknown_list(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)

    with pytest.raises(ReconstructionIdentityError):
        TableSnapshotService().reconstruct_list_period(
            db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2020,
            list_public_id="00000000-0000-0000-0000-000000000000",
            definition_values={"name": "Ghost"},
            entry_payloads=[],
            edited_by=1,
        )


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


def test_run_due_cycle_snapshots_does_not_backfill_a_brand_new_config(db):
    """A CycleConfig with no snapshot history yet only ever gets the single
    immediately-preceding cycle, even though the walk-backward catch-up logic exists -
    otherwise every brand-new config (the overwhelmingly common case: set up once per
    tenant, typically for a group that already has years of pre-existing list data) would
    immediately get flooded with several "historical" snapshots that are really just
    today's data relabeled as older years, since there is nothing else to draw from."""
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, reset_month=12, reset_day=31)
    make_list_definition(db, tenant.id)

    run_due_cycle_snapshots(db, TableSnapshotService())

    expected_latest = get_cycle_year(date.today(), 12, 31) - 1
    written_years = {
        row.cycle_year
        for row in db.query(TableSnapshot).filter_by(tenant_id=tenant.id, cycle_config_id=cycle_config.id, table_name="list_definition")
    }
    assert written_years == {expected_latest}


def test_run_due_cycle_snapshots_catches_up_a_bounded_number_of_missed_cycles_for_an_established_config(db, monkeypatch):
    """Regression test (2026-09-17 audit fix): previously this only ever looked exactly
    one cycle back (current_cycle_year - 1), so once a second cycle boundary passed
    without the loop running (a real outage spanning >1 boundary, not just the single-day
    gaps it already tolerated), the older missed cycle could never be reached again -
    current_cycle_year - 1 always points at whatever cycle *just* ended, never further
    back. For a CycleConfig that already has at least one snapshot from an earlier tick
    (i.e. this isn't brand new - see the sibling "does_not_backfill_a_brand_new_config"
    test), it now walks backward while a cycle is missing, bounded by
    MAX_CYCLE_SNAPSHOT_CATCH_UP."""
    import app.services.table_snapshot_service as svc

    monkeypatch.setattr(svc, "MAX_CYCLE_SNAPSHOT_CATCH_UP", 3)
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, reset_month=12, reset_day=31)
    make_list_definition(db, tenant.id)
    service = TableSnapshotService()
    expected_latest = get_cycle_year(date.today(), 12, 31) - 1

    # Simulate "this config ran successfully a long time ago" - one old snapshot exists,
    # then a gap of several missed boundaries (bigger than the bound) opens up before the
    # loop runs again.
    service.create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=expected_latest - 5)

    run_due_cycle_snapshots(db, service)

    written_years = {
        row.cycle_year
        for row in db.query(TableSnapshot).filter_by(tenant_id=tenant.id, cycle_config_id=cycle_config.id, table_name="list_definition")
    }
    # The 3 most recent missing cycles get backfilled (bounded catch-up); the gap between
    # them and the old pre-existing snapshot is left alone, same as a longer real outage
    # always leaves an older, unreachable gap under this bounded design.
    assert written_years == {expected_latest, expected_latest - 1, expected_latest - 2, expected_latest - 5}


def test_run_due_cycle_snapshots_stops_at_the_first_already_complete_cycle(db):
    """The backward walk must stop as soon as it finds a cycle that's already fully
    snapshotted, not keep going for MAX_CYCLE_SNAPSHOT_CATCH_UP cycles regardless -
    otherwise a tenant that's been running this loop successfully for years would get its
    older, already-complete cycles re-touched (still idempotent/no-op per table, but
    pointless extra work) on every single tick forever."""
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, reset_month=12, reset_day=31)
    make_list_definition(db, tenant.id)
    service = TableSnapshotService()
    expected_latest = get_cycle_year(date.today(), 12, 31) - 1

    # Simulate "already caught up": every table already has a snapshot for the
    # immediately-preceding cycle.
    service.create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=expected_latest)

    run_due_cycle_snapshots(db, service)

    written_years = {
        row.cycle_year
        for row in db.query(TableSnapshot).filter_by(tenant_id=tenant.id, cycle_config_id=cycle_config.id, table_name="list_definition")
    }
    assert written_years == {expected_latest}


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
