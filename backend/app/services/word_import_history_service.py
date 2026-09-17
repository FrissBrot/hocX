"""Fill historical list gaps from reviewed imports without changing live lists."""
from datetime import date
import uuid

from sqlalchemy import select

from app.core.cycle_utils import get_cycle_year
from app.models import CycleConfig, ListEntry, Protocol, TableSnapshot
from app.services.tenant_transfer_common import row_to_dict

SOURCE_KEY = "word_import_source"


def record_imported_list_history(db, *, tenant_id, cycle_config_id, protocol_id, definitions, rows_by_list):
    if not cycle_config_id or not rows_by_list:
        return
    # Serialize imports into the same cycle, including creation of missing snapshots.
    cycle = db.scalar(select(CycleConfig).where(
        CycleConfig.id == cycle_config_id, CycleConfig.tenant_id == tenant_id
    ).with_for_update())
    protocol = db.get(Protocol, protocol_id)
    if cycle is None or protocol is None or protocol.tenant_id != tenant_id:
        return
    year = get_cycle_year(protocol.protocol_date, cycle.reset_month, cycle.reset_day)
    if year >= get_cycle_year(date.today(), cycle.reset_month, cycle.reset_day):
        return  # Current/future cycles are still live, not historical records.
    snapshots = {row.table_name: row for row in db.scalars(select(TableSnapshot).where(
        TableSnapshot.tenant_id == tenant_id, TableSnapshot.cycle_config_id == cycle.id,
        TableSnapshot.cycle_year == year,
        TableSnapshot.table_name.in_(["list_definition", "list_entry"]),
    ).with_for_update())}
    source = {"protocol_id": str(protocol.public_id), "protocol_date": protocol.protocol_date.isoformat()}
    synthetic_index = 0
    for list_id, imported_rows in rows_by_list.items():
        definition = definitions[list_id]
        if definition.tenant_id != tenant_id:
            continue
        definition_snapshot = snapshots.get("list_definition")
        entry_snapshot = snapshots.get("list_entry")
        existing = next((row for row in (definition_snapshot.snapshot_json if definition_snapshot else [])
                         if row.get("id") == list_id), None)
        if existing is not None:
            previous_source = existing.get(SOURCE_KEY)
            # Regular snapshots and any human edits always win over automatic imports.
            if not previous_source or definition_snapshot.is_edited or (entry_snapshot and entry_snapshot.is_edited):
                continue
            # Equal dates also preserve the first reviewed state rather than arbitrarily overwriting it.
            if previous_source["protocol_date"] >= source["protocol_date"]:
                continue
        elif entry_snapshot and any(row.get("list_definition_id") == list_id for row in entry_snapshot.snapshot_json):
            continue  # A partial existing historical record is still protected.
        entries = []
        for index, row in enumerate(imported_rows):
            live = db.get(ListEntry, row["id"]) if row["id"] > 0 else None
            if live is not None and live.list_definition_id == list_id:
                internal_id, public_id = live.id, str(live.public_id)
            else:
                # Snapshot-only rows need stable identities too, without creating live entries.
                synthetic_index += 1
                internal_id = -((protocol.id << 32) + synthetic_index)
                public_id = str(uuid.uuid5(protocol.public_id, f"list:{list_id}:row:{index}"))
            entries.append({"id": internal_id, "public_id": public_id, "list_definition_id": list_id,
                            "sort_index": row["sort_index"], "column_one_value_json": row["column_one_value"],
                            "column_two_value_json": row["column_two_value"]})
        new_definition = {**row_to_dict(definition), SOURCE_KEY: source}
        for table_name, new_rows, foreign_key in (
            ("list_definition", [new_definition], "id"), ("list_entry", entries, "list_definition_id")
        ):
            snapshot = snapshots.get(table_name)
            if snapshot is None:
                snapshot = TableSnapshot(tenant_id=tenant_id, cycle_config_id=cycle.id, cycle_year=year,
                                         table_name=table_name, snapshot_json=[], row_count=0)
                db.add(snapshot)
                snapshots[table_name] = snapshot
            snapshot.snapshot_json = [row for row in snapshot.snapshot_json if row.get(foreign_key) != list_id] + new_rows
            snapshot.row_count = len(snapshot.snapshot_json)
    # Caller commits together with the final imported protocol values.
