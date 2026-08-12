"""Regression tests for 3 HIGH findings from the 2026-08-12 audit, "Listen" domain
(H7-H9 in this batch's write-up).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import lists as lists_route
from app.models import ListDefinition, ListEntry
from app.schemas.list_definition import ListDefinitionUpdate
from app.services import list_snapshot_service
from app.services.list_service import ListService

from tests.factories import (
    make_current_user,
    make_element_definition,
    make_list_definition,
    make_list_entry,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


# --- H7: Deleting a linked list has no usage check ------------------------------------


def test_h7_delete_blocked_when_referenced_by_template_element_block(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    element_definition = make_element_definition(
        db,
        tenant.id,
        "Form With List",
        blocks=[{"element_type_id": 6, "configuration_json": {"linked_list_id": definition.id}}],
    )
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        lists_route.delete_definition(definition.id, db=db, user=user)
    assert exc_info.value.status_code == 409
    assert db.get(ListDefinition, definition.id) is not None

    # Unlink the template element block, then deletion must succeed.
    element_definition.configuration_json = {
        "blocks": [{"element_type_id": 6, "configuration_json": {}}]
    }
    db.add(element_definition)
    db.flush()

    result = lists_route.delete_definition(definition.id, db=db, user=user)
    assert result == {"message": "Liste geloescht"}
    assert db.get(ListDefinition, definition.id) is None


def test_h7_delete_blocked_when_referenced_by_protocol_block(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(
        db, element.id, configuration_snapshot_json={"linked_list_id": definition.id}
    )
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        lists_route.delete_definition(definition.id, db=db, user=user)
    assert exc_info.value.status_code == 409
    assert db.get(ListDefinition, definition.id) is not None


def test_h7_delete_blocked_when_referenced_via_row_link(db):
    """The 'Zeile aus Liste' row-link mode (rows[].linked_list_id) must be caught too,
    not just the whole-list linked_list_id key."""
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(
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
                }
            ],
        },
    )
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        lists_route.delete_definition(definition.id, db=db, user=user)
    assert exc_info.value.status_code == 409


def test_h7_delete_succeeds_when_unreferenced(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    user = make_current_user(tenant.id)

    result = lists_route.delete_definition(definition.id, db=db, user=user)
    assert result == {"message": "Liste geloescht"}
    assert db.get(ListDefinition, definition.id) is None


# --- H8: Column value-type change doesn't migrate existing entries --------------------


def test_h8_column_value_type_change_clears_stale_entry_values(db):
    tenant = make_tenant(db)
    definition = make_list_definition(
        db, tenant.id, column_one_value_type="text", column_two_value_type="text"
    )
    entry = make_list_entry(
        db,
        definition.id,
        column_one_value={"text_value": "Hello"},
        column_two_value={"text_value": "Untouched"},
    )

    service = ListService()
    service.update_definition(
        db, definition.id, ListDefinitionUpdate(column_one_value_type="participant")
    )

    db.expire_all()
    refreshed_entry = db.get(ListEntry, entry.id)
    # The old text-shaped value must not survive under the new participant-typed column.
    assert refreshed_entry.column_one_value_json == {}
    assert "text_value" not in refreshed_entry.column_one_value_json
    # column_two's value_type was untouched, so its value must be left alone.
    assert refreshed_entry.column_two_value_json == {"text_value": "Untouched"}

    refreshed_definition = db.get(ListDefinition, definition.id)
    assert refreshed_definition.column_one_value_type == "participant"


def test_h8_column_value_type_unchanged_leaves_entries_untouched(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id, column_one_value_type="text")
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "Hello"})

    service = ListService()
    # Setting the same value_type again (a no-op change) must not clear the value.
    service.update_definition(
        db, definition.id, ListDefinitionUpdate(column_one_value_type="text")
    )

    refreshed_entry = db.get(ListEntry, entry.id)
    assert refreshed_entry.column_one_value_json == {"text_value": "Hello"}


# --- H9: Deleted source list never marked as deleted in table-block mode --------------


def test_h9_deleted_source_list_marks_entry_exists_false_in_table_block(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    make_list_entry(db, definition.id, column_one_value={"text_value": "a"})
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(
        db, element.id, configuration_snapshot_json={"linked_list_id": definition.id}
    )

    # First refresh while the source list still exists - captures a live snapshot.
    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=False)
    assert block.configuration_snapshot_json["list_snapshot"]["entries"]

    # Delete the source list out from under the block, then recompute.
    db.delete(db.get(ListDefinition, definition.id))
    db.flush()

    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=False)
    snapshot = block.configuration_snapshot_json["list_snapshot"]
    assert snapshot == {"synced_version": 0, "entry_exists": False}, (
        "must mirror compute_row_list_snapshot's deleted-source marker, not keep the stale "
        "old snapshot"
    )


def test_h9_refresh_is_idempotent_once_marked_deleted(db):
    """A second refresh call after the source list is gone must not error or thrash the
    config (config only counts as 'changed' - and gets re-persisted - once)."""
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(
        db, element.id, configuration_snapshot_json={"linked_list_id": definition.id}
    )

    db.delete(db.get(ListDefinition, definition.id))
    db.flush()

    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=False)
    block = list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=False)
    assert block.configuration_snapshot_json["list_snapshot"] == {
        "synced_version": 0,
        "entry_exists": False,
    }
