"""Route-level tests for the table-snapshot endpoints. Route functions are called
directly as plain Python callables (bypassing Depends/ASGI/auth entirely), matching the
existing convention in test_protocol_element_list_snapshot_routes.py.

There is no manual/on-demand snapshot-creation endpoint (this is a historical-record
feature, not a backup tool) - tests seed a TableSnapshot row by calling
TableSnapshotService.create_snapshot() directly, the same way the daily background loop
would."""
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.api.routes import table_snapshots
from app.core.cycle_utils import get_cycle_year
from app.schemas.table_snapshot import TableSnapshotListReconstructRequest, TableSnapshotRowDelete, TableSnapshotRowUpdate
from app.services.table_snapshot_service import TableSnapshotService

from tests.factories import (
    make_current_user,
    make_cycle_config,
    make_list_definition,
    make_list_entry,
    make_protocol,
    make_template,
    make_tenant,
)


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


def test_list_snapshot_cycles_flags_ended_period_with_protocol_but_no_snapshot(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, reset_month=12, reset_day=31)
    template = make_template(db, tenant.id)
    template.cycle_config_id = cycle_config.id
    db.flush()
    make_protocol(db, tenant.id, template.id, protocol_date=date(2020, 6, 1))

    reader = make_current_user(tenant.id, role="reader")
    cycles = table_snapshots.list_snapshot_cycles(db=db, user=reader)

    assert len(cycles) == 1
    assert cycles[0].cycle_year == 2020
    assert cycles[0].has_snapshot is False
    assert cycles[0].tables == []


def test_list_snapshot_cycles_does_not_flag_the_still_active_period(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, reset_month=12, reset_day=31)
    template = make_template(db, tenant.id)
    template.cycle_config_id = cycle_config.id
    db.flush()
    make_protocol(db, tenant.id, template.id, protocol_date=date.today())

    reader = make_current_user(tenant.id, role="reader")
    cycles = table_snapshots.list_snapshot_cycles(db=db, user=reader)

    assert cycles == []


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


def test_reconstruction_draft_from_live_when_no_snapshots_exist(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")
    make_list_entry(db, definition.id, sort_index=0, column_one_value={"text_value": "a"})
    writer = make_current_user(tenant.id, role="writer")

    draft = table_snapshots.get_reconstruction_draft(cycle_config.public_id, 2020, definition.public_id, db=db, user=writer)

    assert draft.source == "live"
    assert draft.source_cycle_year is None
    assert draft.definition_values["name"] == "Alice's List"
    assert len(draft.entries) == 1
    assert draft.entries[0]["column_one_value_json"] == {"text_value": "a"}


def test_reconstruction_draft_picks_nearest_existing_snapshot_by_distance(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")

    # Snapshots at 2018 and 2022 already exist (e.g. from earlier reconstructions);
    # 2020 is missing. 2022 (distance 2) is nearer than 2018 (distance 2)... make it
    # unambiguous: 2021 (distance 1) vs 2018 (distance 3).
    TableSnapshotService().reconstruct_list_period(
        db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2018,
        list_public_id=str(definition.public_id),
        definition_values={"name": "From 2018", "column_one_title": "x", "column_one_value_type": "text", "column_two_title": "y", "column_two_value_type": "text", "is_active": True},
        entry_payloads=[], edited_by=1,
    )
    TableSnapshotService().reconstruct_list_period(
        db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2021,
        list_public_id=str(definition.public_id),
        definition_values={"name": "From 2021", "column_one_title": "x", "column_one_value_type": "text", "column_two_title": "y", "column_two_value_type": "text", "is_active": True},
        entry_payloads=[], edited_by=1,
    )
    writer = make_current_user(tenant.id, role="writer")

    draft = table_snapshots.get_reconstruction_draft(cycle_config.public_id, 2020, definition.public_id, db=db, user=writer)

    assert draft.source == "snapshot"
    assert draft.source_cycle_year == 2021
    assert draft.definition_values["name"] == "From 2021"


def test_reconstruction_draft_404_for_unknown_list(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        table_snapshots.get_reconstruction_draft(
            cycle_config.public_id, 2020, "00000000-0000-0000-0000-000000000000", db=db, user=writer
        )
    assert exc_info.value.status_code == 404


def test_reconstruct_list_period_requires_at_least_writer(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")
    reader = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        table_snapshots.reconstruct_list_period(
            cycle_config.public_id, 2020, definition.public_id,
            TableSnapshotListReconstructRequest(definition_values={"name": definition.name}, entries=[]),
            db=db, user=reader,
        )
    assert exc_info.value.status_code == 403


def test_reconstruct_list_period_succeeds_as_writer(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "a"})
    writer = make_current_user(tenant.id, role="writer")

    table_snapshots.reconstruct_list_period(
        cycle_config.public_id, 2020, definition.public_id,
        TableSnapshotListReconstructRequest(
            definition_values={
                "name": definition.name, "column_one_title": definition.column_one_title,
                "column_one_value_type": definition.column_one_value_type,
                "column_two_title": definition.column_two_title,
                "column_two_value_type": definition.column_two_value_type, "is_active": True,
            },
            entries=[{"public_id": str(entry.public_id), "sort_index": 0, "column_one_value_json": {"text_value": "a"}, "column_two_value_json": {}}],
        ),
        db=db, user=writer,
    )

    read_back = table_snapshots.get_snapshot_table(cycle_config.public_id, 2020, "list_definition", db=db, user=writer)
    assert read_back.row_count == 1
    assert read_back.rows[0]["name"] == definition.name

    audit_rows = db.execute(
        text("SELECT action FROM audit_log WHERE tenant_id = :tenant_id AND action = 'table_snapshot.reconstruct'"),
        {"tenant_id": tenant.id},
    ).all()
    assert len(audit_rows) == 1


def test_reconstruct_list_period_rejects_current_active_period(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, reset_month=12, reset_day=31)
    definition = make_list_definition(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")
    current_cycle_year = get_cycle_year(date.today(), 12, 31)

    with pytest.raises(HTTPException) as exc_info:
        table_snapshots.reconstruct_list_period(
            cycle_config.public_id, current_cycle_year, definition.public_id,
            TableSnapshotListReconstructRequest(definition_values={"name": definition.name}, entries=[]),
            db=db, user=writer,
        )
    assert exc_info.value.status_code == 400


def test_reconstruct_list_period_conflicts_when_already_captured(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id, name="Alice's List")
    TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2020)
    writer = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        table_snapshots.reconstruct_list_period(
            cycle_config.public_id, 2020, definition.public_id,
            TableSnapshotListReconstructRequest(definition_values={"name": definition.name}, entries=[]),
            db=db, user=writer,
        )
    assert exc_info.value.status_code == 409


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
