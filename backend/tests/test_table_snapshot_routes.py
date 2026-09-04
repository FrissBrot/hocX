"""Route-level tests for the table-snapshot endpoints. Route functions are called
directly as plain Python callables (bypassing Depends/ASGI/auth entirely), matching the
existing convention in test_protocol_element_list_snapshot_routes.py.

There is no manual/on-demand snapshot-creation endpoint (this is a historical-record
feature, not a backup tool) - tests seed a TableSnapshot row by calling
TableSnapshotService.create_snapshot() directly, the same way the daily background loop
would."""
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.api.routes import table_snapshots
from app.schemas.table_snapshot import TableSnapshotRowDelete, TableSnapshotRowUpdate
from app.services.table_snapshot_service import TableSnapshotService

from tests.factories import make_current_user, make_cycle_config, make_list_definition, make_tenant


def test_list_snapshot_cycles_and_read(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    make_list_definition(db, tenant.id, name="Alice's List")
    TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2024)

    reader = make_current_user(tenant.id, role="reader")
    cycles = table_snapshots.list_snapshot_cycles(db=db, user=reader)
    assert len(cycles) == 1
    assert cycles[0].cycle_year == 2024
    assert "list_definition" in {t.table_name for t in cycles[0].tables}

    rows_read = table_snapshots.get_snapshot_table(cycle_config.public_id, 2024, "list_definition", db=db, user=reader)
    assert rows_read.row_count == 1
    assert rows_read.rows[0]["name"] == "Alice's List"


def test_get_snapshot_table_404_when_missing(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    reader = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        table_snapshots.get_snapshot_table(cycle_config.public_id, 2024, "list_definition", db=db, user=reader)
    assert exc_info.value.status_code == 404


def test_get_snapshot_table_404_for_cycle_config_from_another_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    cycle_config_a = make_cycle_config(db, tenant_a.id)
    reader_b = make_current_user(tenant_b.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        table_snapshots.get_snapshot_table(cycle_config_a.public_id, 2024, "list_definition", db=db, user=reader_b)
    assert exc_info.value.status_code == 404


def test_update_snapshot_row_requires_confirm_flag(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")
    TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2024)
    admin = make_current_user(tenant.id, role="admin")

    with pytest.raises(HTTPException) as exc_info:
        table_snapshots.update_snapshot_row(
            cycle_config.public_id, 2024, "list_definition", definition.public_id,
            TableSnapshotRowUpdate(values={"name": "Changed"}, confirm_historical_edit=False),
            db=db, user=admin,
        )
    assert exc_info.value.status_code == 400


def test_update_snapshot_row_requires_admin(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")
    TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2024)
    writer = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        table_snapshots.update_snapshot_row(
            cycle_config.public_id, 2024, "list_definition", definition.public_id,
            TableSnapshotRowUpdate(values={"name": "Changed"}, confirm_historical_edit=True),
            db=db, user=writer,
        )
    assert exc_info.value.status_code == 403


def test_update_snapshot_row_success_sets_is_edited_and_writes_audit_log(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")
    TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2024)
    admin = make_current_user(tenant.id, role="admin")

    updated = table_snapshots.update_snapshot_row(
        cycle_config.public_id, 2024, "list_definition", definition.public_id,
        TableSnapshotRowUpdate(values={"name": "Changed"}, confirm_historical_edit=True),
        db=db, user=admin,
    )
    assert updated["name"] == "Changed"
    assert updated["id"] == definition.id  # id/public_id can't be overwritten by the client

    reader = make_current_user(tenant.id, role="reader")
    read_back = table_snapshots.get_snapshot_table(cycle_config.public_id, 2024, "list_definition", db=db, user=reader)
    assert read_back.is_edited is True
    assert read_back.rows[0]["name"] == "Changed"

    audit_rows = db.execute(
        text("SELECT action FROM audit_log WHERE tenant_id = :tenant_id AND action = 'table_snapshot.historical_edit'"),
        {"tenant_id": tenant.id},
    ).all()
    assert len(audit_rows) == 1


def test_delete_snapshot_row_removes_row_and_decrements_count(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")
    TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2024)
    admin = make_current_user(tenant.id, role="admin")

    table_snapshots.delete_snapshot_row(
        cycle_config.public_id, 2024, "list_definition", definition.public_id,
        TableSnapshotRowDelete(confirm_historical_edit=True),
        db=db, user=admin,
    )

    read_back = table_snapshots.get_snapshot_table(cycle_config.public_id, 2024, "list_definition", db=db, user=admin)
    assert read_back.row_count == 0
    assert read_back.rows == []
