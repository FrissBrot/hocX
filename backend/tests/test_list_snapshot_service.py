"""Tests for list_snapshot_service.py - the snapshot compute/refresh/undo/freeze logic
backing the "Daten aktualisieren" hint on list-linked protocol blocks."""
from app.schemas.list_definition import ListDefinitionUpdate, ListEntryCreate, ListEntryUpdate
from app.services import list_snapshot_service
from app.services.list_service import ListService

from tests.factories import (
    make_list_definition,
    make_list_entry,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def test_compute_whole_list_snapshot_shape(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    make_list_entry(db, definition.id, sort_index=0, column_one_value={"text_value": "a"})
    make_list_entry(db, definition.id, sort_index=1, column_one_value={"text_value": "b"})

    snapshot = list_snapshot_service.compute_whole_list_snapshot(db, definition.id)

    assert snapshot["synced_version"] == definition.content_version
    assert snapshot["column_one_title"] == definition.column_one_title
    assert [e["column_one_value"]["text_value"] for e in snapshot["entries"]] == ["a", "b"]
    assert snapshot["previous"] is None


def test_compute_whole_list_snapshot_returns_none_for_deleted_list(db):
    assert list_snapshot_service.compute_whole_list_snapshot(db, 999_999_999) is None


def test_compute_row_list_snapshot_entry_exists(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "hello"})

    snapshot = list_snapshot_service.compute_row_list_snapshot(db, definition.id, entry.id)

    assert snapshot["entry_exists"] is True
    assert snapshot["column_one_value"]["text_value"] == "hello"
    assert snapshot["synced_version"] == definition.content_version


def test_compute_row_list_snapshot_deleted_entry(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)

    snapshot = list_snapshot_service.compute_row_list_snapshot(db, definition.id, 999_999_999)

    assert snapshot["entry_exists"] is False
    assert snapshot["synced_version"] == definition.content_version


def test_content_version_bumps_on_entry_create_update_delete(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    service = ListService()
    v0 = definition.content_version

    created = service.create_entry(db, definition.id, ListEntryCreate(column_one_value={"text_value": "x"}))
    v1 = db.get(type(definition), definition.id).content_version
    assert v1 == v0 + 1

    service.update_entry(db, created.id, ListEntryUpdate(column_one_value={"text_value": "y"}))
    v2 = db.get(type(definition), definition.id).content_version
    assert v2 == v1 + 1

    service.delete_entry(db, created.id)
    v3 = db.get(type(definition), definition.id).content_version
    assert v3 == v2 + 1


def test_content_version_bumps_on_column_structure_change_only(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    service = ListService()
    v0 = definition.content_version

    service.update_definition(db, definition.id, ListDefinitionUpdate(description="just a description update"))
    v1 = db.get(type(definition), definition.id).content_version
    assert v1 == v0, "name/description/is_active-only changes must not bump content_version"

    service.update_definition(db, definition.id, ListDefinitionUpdate(column_one_title="New Title"))
    v2 = db.get(type(definition), definition.id).content_version
    assert v2 == v0 + 1, "a column title change must bump content_version"


def _protocol_with_list_row_block(db, tenant, definition, entry):
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(
        db,
        element.id,
        configuration_snapshot_json={
            "linked_list_id": None,
            "rows": [
                {
                    "id": "row-1",
                    "value_type": "list_entry",
                    "linked_list_id": definition.id,
                    "linked_list_entry_id": entry.id,
                    "list_fixed_column": "column_one",
                    "label": "",
                }
            ],
        },
    )
    return protocol, block


def test_refresh_row_block_sets_snapshot_and_keeps_undo_one_level_deep(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "v1"})
    _protocol, block = _protocol_with_list_row_block(db, tenant, definition, entry)

    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=True)
    row = block.configuration_snapshot_json["rows"][0]
    assert row["list_snapshot"]["column_one_value"]["text_value"] == "v1"
    assert row["list_snapshot"]["previous"] is None  # nothing to stash the first time

    entry.column_one_value_json = {"text_value": "v2"}
    db.add(entry)
    db.commit()

    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=True)
    row = block.configuration_snapshot_json["rows"][0]
    assert row["list_snapshot"]["column_one_value"]["text_value"] == "v2"
    assert row["list_snapshot"]["previous"]["column_one_value"]["text_value"] == "v1"
    assert row["list_snapshot"]["previous"].get("previous") is None, "undo must never nest more than one level"


def test_silent_sync_never_overwrites_existing_previous(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "v1"})
    _protocol, block = _protocol_with_list_row_block(db, tenant, definition, entry)

    # First manual refresh with nothing to undo yet, then a real change + a second manual
    # refresh to establish a genuine undo point.
    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=True)
    entry.column_one_value_json = {"text_value": "v2"}
    db.add(entry)
    db.commit()
    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=True)
    assert block.configuration_snapshot_json["rows"][0]["list_snapshot"]["previous"]["column_one_value"]["text_value"] == "v1"

    # Now simulate a silent self-write sync (keep_undo=False) after further edits - the
    # existing undo point must survive untouched.
    entry.column_one_value_json = {"text_value": "v3"}
    db.add(entry)
    db.commit()
    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=False)
    row = block.configuration_snapshot_json["rows"][0]
    assert row["list_snapshot"]["column_one_value"]["text_value"] == "v3"
    assert row["list_snapshot"]["previous"]["column_one_value"]["text_value"] == "v1"


def test_undo_restores_and_clears_previous(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "v1"})
    _protocol, block = _protocol_with_list_row_block(db, tenant, definition, entry)

    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=True)
    entry.column_one_value_json = {"text_value": "v2"}
    db.add(entry)
    db.commit()
    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=True)
    assert block.configuration_snapshot_json["rows"][0]["list_snapshot"]["column_one_value"]["text_value"] == "v2"

    restored = list_snapshot_service.undo_block_list_snapshot(db, block)
    row = restored.configuration_snapshot_json["rows"][0]
    assert row["list_snapshot"]["column_one_value"]["text_value"] == "v1"
    assert row["list_snapshot"].get("previous") is None


def test_undo_returns_none_when_nothing_to_undo(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "v1"})
    _protocol, block = _protocol_with_list_row_block(db, tenant, definition, entry)
    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=True)

    assert list_snapshot_service.undo_block_list_snapshot(db, block) is None


def test_freeze_updates_version_and_clears_previous(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "v1"})
    protocol, block = _protocol_with_list_row_block(db, tenant, definition, entry)

    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=True)
    entry.column_one_value_json = {"text_value": "v2"}
    db.add(entry)
    db.commit()
    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=True)
    assert block.configuration_snapshot_json["rows"][0]["list_snapshot"]["previous"] is not None

    list_snapshot_service.freeze_list_snapshots_for_protocol(db, protocol.id)
    frozen = db.get(type(block), block.id)
    row = frozen.configuration_snapshot_json["rows"][0]
    assert row["list_snapshot"]["column_one_value"]["text_value"] == "v2"
    assert row["list_snapshot"].get("previous") is None


def test_referenced_list_definition_ids_finds_row_link(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id)
    protocol, _block = _protocol_with_list_row_block(db, tenant, definition, entry)

    assert list_snapshot_service.referenced_list_definition_ids(db, protocol.id) == {definition.id}
