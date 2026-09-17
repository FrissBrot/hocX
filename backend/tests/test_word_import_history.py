"""History semantics that complement the real HTTP/browser import testbook."""
from copy import deepcopy
from datetime import date

from sqlalchemy import select

from app.models import TableSnapshot
from app.services.table_snapshot_service import TableSnapshotService
from app.services.word_import_history_service import record_imported_list_history, SOURCE_KEY
from tests.factories import make_tenant, make_cycle_config, make_template, make_protocol, make_list_definition, make_list_entry


def setup_history(db):
    tenant = make_tenant(db)
    cycle = make_cycle_config(db, tenant.id, reset_month=7, reset_day=31)
    template = make_template(db, tenant.id)
    template.cycle_config_id = cycle.id
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "Feuer"}, column_two_value={"text_value": "LIVE"})
    db.flush()
    return tenant, cycle, template, definition, entry


def record(db, seed, protocol_date, value, *, number="P-1", cycle_id=None):
    tenant, cycle, template, definition, entry = seed
    protocol = make_protocol(db, tenant.id, template.id, protocol_date=protocol_date, protocol_number=number)
    record_imported_list_history(db, tenant_id=tenant.id, cycle_config_id=cycle_id if cycle_id is not None else cycle.id,
        protocol_id=protocol.id, definitions={definition.id: definition}, rows_by_list={definition.id: [{
            "id": entry.id, "sort_index": 10, "column_one_value": {"text_value": "Feuer"}, "column_two_value": {"text_value": value},
        }]})
    db.flush()
    return protocol


def snapshots(db, cycle):
    return list(db.scalars(select(TableSnapshot).where(TableSnapshot.cycle_config_id == cycle.id).order_by(TableSnapshot.table_name)))


def test_regular_unedited_snapshot_is_not_overwritten(db):
    seed = setup_history(db)
    tenant, cycle, _, _, entry = seed
    TableSnapshotService().create_snapshot(db, tenant_id=tenant.id, cycle_config=cycle, cycle_year=2023)
    before = [deepcopy(row.snapshot_json) for row in snapshots(db, cycle)]
    record(db, seed, date(2024, 7, 31), "IMPORTED")
    assert [row.snapshot_json for row in snapshots(db, cycle)] == before
    assert entry.column_two_value_json == {"text_value": "LIVE"}


def test_equal_date_preserves_first_reviewed_source_and_other_lists(db):
    seed = setup_history(db)
    tenant, cycle, _, definition, _ = seed
    first = record(db, seed, date(2024, 2, 29), "FIRST")
    before = [deepcopy(row.snapshot_json) for row in snapshots(db, cycle)]
    record(db, seed, date(2024, 2, 29), "SECOND", number="P-2")
    assert [row.snapshot_json for row in snapshots(db, cycle)] == before
    assert before[0][0][SOURCE_KEY]["protocol_id"] == str(first.public_id)
    other = make_list_definition(db, tenant.id, name="Other")
    record_imported_list_history(db, tenant_id=tenant.id, cycle_config_id=cycle.id, protocol_id=first.id,
        definitions={other.id: other}, rows_by_list={other.id: [{"id": -1, "sort_index": 10,
        "column_one_value": {"text_value": "Other"}, "column_two_value": {"text_value": "UNRELATED"}}]})
    db.flush()
    record(db, seed, date(2024, 7, 31), "NEWER", number="P-3")
    definitions, entries = snapshots(db, cycle)
    assert {row["id"] for row in definitions.snapshot_json} == {definition.id, other.id}
    assert {row["column_two_value_json"]["text_value"] for row in entries.snapshot_json} == {"NEWER", "UNRELATED"}


def test_foreign_cycle_is_not_written(db):
    seed = setup_history(db)
    foreign = make_cycle_config(db, make_tenant(db).id)
    record(db, seed, date(2024, 2, 29), "PRIVATE", cycle_id=foreign.id)
    assert snapshots(db, foreign) == []
    assert snapshots(db, seed[1]) == []


def test_missing_cycle_and_no_approved_rows_create_no_history(db):
    seed = setup_history(db)
    tenant, cycle, template, definition, _ = seed
    protocol = make_protocol(db, tenant.id, template.id, protocol_date=date(2024, 2, 29))
    for cycle_id in (None, cycle.id):
        record_imported_list_history(db, tenant_id=tenant.id, cycle_config_id=cycle_id, protocol_id=protocol.id,
                                     definitions={definition.id: definition}, rows_by_list={})
    assert snapshots(db, cycle) == []
