"""Historische Verknüpfungen bleiben sichtbar, unabhängig von heutiger Mitgliedschaft."""
from datetime import date

from sqlalchemy import select

from app.api.routes.table_snapshots import get_snapshot_table, update_snapshot_row
from app.models import TableSnapshot
from app.schemas.table_snapshot import TableSnapshotRowUpdate
from app.services.snapshot_list_references import snapshot_list_rows
from app.services.table_snapshot_service import TableSnapshotService
from tests.factories import (
    make_current_user, make_cycle_config, make_list_definition, make_list_entry,
    make_participant, make_tenant,
)


def _snapshot(db):
    tenant = make_tenant(db)
    cycle = make_cycle_config(db, tenant.id)
    definition = make_list_definition(db, tenant.id)
    person = make_participant(db, tenant.id, "Damals verantwortlich")
    person.left_at = date(2026, 8, 15)
    person.is_active = False
    entry = make_list_entry(db, definition.id, column_two_value={"participant_id": person.id})
    TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle, cycle_year=2025)
    return tenant, cycle, person, entry


def _read(db, tenant, cycle):
    return get_snapshot_table(cycle.public_id, 2025, "list_entry", db=db,
                              user=make_current_user(tenant.id, role="reader")).rows[0]["column_two_value_json"]


def test_old_snapshot_internal_id_resolves_departed_participant(db):
    tenant, cycle, person, entry = _snapshot(db)
    snapshot = db.scalar(select(TableSnapshot).where(
        TableSnapshot.cycle_config_id == cycle.id, TableSnapshot.table_name == "list_entry"))
    snapshot.snapshot_json = [{**row, "column_two_value_json": {"participant_id": person.id}}
                              for row in snapshot.snapshot_json]
    db.flush()
    value = _read(db, tenant, cycle)
    assert value["participant_id"] == str(person.public_id)
    assert value["participant_name"] == "Damals verantwortlich"
    # Beim Lesen wird der eingefrorene Datensatz nicht umgeschrieben.
    assert snapshot.snapshot_json[0]["column_two_value_json"] == {"participant_id": person.id}


def test_new_snapshot_keeps_original_name_after_rename_and_deletion(db):
    tenant, cycle, person, entry = _snapshot(db)
    original_public_id = str(person.public_id)
    person.display_name = "Heute umbenannt"
    db.flush()
    assert _read(db, tenant, cycle)["participant_name"] == "Damals verantwortlich"
    db.delete(person)
    db.flush()
    value = _read(db, tenant, cycle)
    assert value["participant_id"] == original_public_id
    assert value["participant_name"] == "Damals verantwortlich"


def test_multiple_participants_support_internal_and_public_ids(db):
    tenant = make_tenant(db)
    first = make_participant(db, tenant.id, "Erster")
    second = make_participant(db, tenant.id, "Zweiter")
    raw = [{"column_one_value_json": {"participant_ids": [first.id, str(second.public_id)]}}]
    result = snapshot_list_rows(db, raw, tenant.id, public=True)[0]["column_one_value_json"]
    assert result["participant_ids"] == [str(first.public_id), str(second.public_id)]
    assert result["participant_names"] == ["Erster", "Zweiter"]


def test_reference_resolution_cannot_read_other_tenant_names(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    person = make_participant(db, other.id, "Privater Name")
    raw = [{"column_one_value_json": {"participant_id": person.id}}]
    value = snapshot_list_rows(db, raw, tenant.id, public=True)[0]["column_one_value_json"]
    assert "participant_name" not in value
    assert str(person.public_id) not in str(value)


def test_historical_edit_round_trips_public_id_without_losing_name(db):
    tenant, cycle, old_person, entry = _snapshot(db)
    new_person = make_participant(db, tenant.id, "Neue Verknüpfung")
    payload = TableSnapshotRowUpdate(confirm_historical_edit=True, values={
        "column_two_value_json": {"participant_id": str(new_person.public_id)},
    })
    result = update_snapshot_row(cycle.public_id, 2025, "list_entry", entry.public_id,
                                 payload, db=db, user=make_current_user(tenant.id, role="admin"))
    assert result["column_two_value_json"]["participant_id"] == str(new_person.public_id)
    assert _read(db, tenant, cycle)["participant_name"] == "Neue Verknüpfung"
