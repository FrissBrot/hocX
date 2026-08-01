"""Tests for the "Änderungen nachverfolgen" (track changes) feature. Confusingly, the
tracked phase is protocol status 'geplant' - that's the status the app's own workflowMeta
(frontend/components/protocol/protocol-editor.tsx) labels "Vorbereitungsmodus"
("preparation mode"); 'vorbereitet' is actually the live-session phase ("Sitzungsmodus"),
where existing marks stay visible but nothing new gets marked. Everything is cleared for
good the instant the protocol moves from 'vorbereitet' to 'durchgeführt'. List entries get
marked at list-snapshot sync time. Route functions are called directly as plain callables
(see test_protocol_element_list_snapshot_routes.py for why this works without a test
client)."""
from app.api.routes import protocol_elements, todos
from app.schemas.protocol import ProtocolTextUpdate, ProtocolTodoCreate, ProtocolTodoUpdate, ProtocolUpdate
from app.services import list_snapshot_service
from app.services.protocol_service import ProtocolService
from app.services.protocol_todo_service import ProtocolTodoService

from tests.factories import (
    make_current_user,
    make_list_definition,
    make_list_entry,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_protocol_todo,
    make_template,
    make_tenant,
)

protocol_service = ProtocolService()
todo_service = ProtocolTodoService()


def _geplant_protocol(db, tenant, *, track_changes_enabled=True):
    template = make_template(db, tenant.id)
    return make_protocol(db, tenant.id, template.id, status="geplant", track_changes_enabled=track_changes_enabled)


_next_sort_index: dict[int, int] = {}


def _block(db, protocol, *, element_type_code="text", configuration=None):
    sort_index = _next_sort_index.get(protocol.id, 0)
    _next_sort_index[protocol.id] = sort_index + 1
    element = make_protocol_element(db, protocol.id, sort_index=sort_index)
    return make_protocol_element_block(
        db, element.id, configuration_snapshot_json=configuration or {}, element_type_code=element_type_code
    )


# ---- Text ----

def test_text_edit_pins_baseline_once_and_marks_dirty(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    block = _block(db, protocol)
    user = make_current_user(tenant.id)

    result1 = protocol_elements.put_protocol_text(block.id, ProtocolTextUpdate(content="v1"), db=db, user=user)
    assert result1.tracked_dirty is True
    assert result1.tracked_baseline_content == ""

    result2 = protocol_elements.put_protocol_text(block.id, ProtocolTextUpdate(content="v2"), db=db, user=user)
    assert result2.tracked_dirty is True
    assert result2.tracked_baseline_content == ""  # still the ORIGINAL value, not "v1"
    assert result2.content == "v2"


def test_text_edit_when_not_active_is_unmarked(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant, track_changes_enabled=False)
    block = _block(db, protocol)
    user = make_current_user(tenant.id)

    result = protocol_elements.put_protocol_text(block.id, ProtocolTextUpdate(content="v1"), db=db, user=user)
    assert result.tracked_dirty is False
    assert result.tracked_baseline_content is None


def test_text_edit_while_vorbereitet_is_unmarked(db):
    """'vorbereitet' is the live-session phase, not the tracked 'geplant' phase - edits
    made there must never be marked, even with the toggle on."""
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    block = _block(db, protocol)
    user = make_current_user(tenant.id)
    protocol_service.update_protocol(db, protocol.id, ProtocolUpdate(status="vorbereitet"))

    result = protocol_elements.put_protocol_text(block.id, ProtocolTextUpdate(content="v1"), db=db, user=user)
    assert result.tracked_dirty is False
    assert result.tracked_baseline_content is None


def test_text_toggle_off_mid_geplant_stops_new_marking_without_erasing(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    block = _block(db, protocol)
    user = make_current_user(tenant.id)

    protocol_elements.put_protocol_text(block.id, ProtocolTextUpdate(content="v1"), db=db, user=user)
    protocol_service.update_protocol(db, protocol.id, ProtocolUpdate(track_changes_enabled=False))
    result = protocol_elements.put_protocol_text(block.id, ProtocolTextUpdate(content="v2"), db=db, user=user)

    assert result.tracked_dirty is True  # existing mark persists
    assert result.tracked_baseline_content == ""  # untouched
    assert result.content == "v2"


# ---- Todos ----

def test_todo_created_while_active_and_deleted_hard_deletes(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    block = _block(db, protocol, element_type_code="todo")
    user = make_current_user(tenant.id)

    created = todos.create_todo(block.id, ProtocolTodoCreate(task="New todo"), db=db, user=user)
    assert created.tracked_change == "added"

    result = todos.delete_todo(created.id, db=db, user=user)
    assert result["pending_delete"] is False
    assert todo_service.repository.get(db, created.id) is None


def test_todo_updated_while_active_pins_original_before_value(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    block = _block(db, protocol, element_type_code="todo")
    todo = make_protocol_todo(db, block.id, task="Original")
    user = make_current_user(tenant.id)

    todos.patch_todo(todo.id, ProtocolTodoUpdate(task="Edit 1"), db=db, user=user)
    result = todos.patch_todo(todo.id, ProtocolTodoUpdate(task="Edit 2"), db=db, user=user)

    assert result.tracked_change == "changed"
    assert result.tracked_change_before_json["task"] == "Original"
    assert result.task == "Edit 2"


def test_todo_deleted_while_active_soft_deletes_and_is_filtered_from_global_lists(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    block = _block(db, protocol, element_type_code="todo")
    todo = make_protocol_todo(db, block.id, task="Pre-existing")
    user = make_current_user(tenant.id)

    result = todos.delete_todo(todo.id, db=db, user=user)
    assert result["pending_delete"] is True
    assert result["todo"].pending_delete is True

    tenant_rows = todo_service.repository.list_for_tenant(db, tenant.id)
    assert todo.id not in [row.ProtocolTodo.id for row in tenant_rows]

    block_rows = todo_service.repository.list_for_protocol_block(db, block.id)
    assert todo.id in [row.ProtocolTodo.id for row in block_rows]


def test_todo_toggle_off_mid_geplant_stops_new_marking(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    block = _block(db, protocol, element_type_code="todo")
    todo = make_protocol_todo(db, block.id, task="Original")
    user = make_current_user(tenant.id)

    protocol_service.update_protocol(db, protocol.id, ProtocolUpdate(track_changes_enabled=False))
    result = todos.patch_todo(todo.id, ProtocolTodoUpdate(task="Edit"), db=db, user=user)
    assert result.tracked_change is None
    assert result.task == "Edit"


# ---- Lists ----

def _row_link_block(db, protocol, list_definition_id, list_entry_id):
    """Mirrors real protocol creation: the block's list_snapshot is computed once, up
    front, untracked - so the first ever tracked sync has a real baseline to diff
    against, exactly like an existing protocol whose blocks were already populated back
    when it was created."""
    block = _block(
        db,
        protocol,
        configuration={
            "linked_list_id": None,
            "rows": [{
                "id": "row-1", "value_type": "list_entry",
                "linked_list_id": list_definition_id, "linked_list_entry_id": list_entry_id,
                "list_fixed_column": "column_one", "label": "",
            }],
        },
    )
    return list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=False, track_changes_active=False)


def _whole_list_block(db, protocol, list_definition_id):
    block = _block(db, protocol, configuration={"linked_list_id": list_definition_id})
    return list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=False, track_changes_active=False)


def test_whole_list_sync_marks_added_changed_removed_and_is_stable_across_repeat_syncs(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    definition = make_list_definition(db, tenant.id)
    kept = make_list_entry(db, definition.id, sort_index=0, column_one_value={"text_value": "kept"})
    to_change = make_list_entry(db, definition.id, sort_index=1, column_one_value={"text_value": "before"})
    to_remove = make_list_entry(db, definition.id, sort_index=2, column_one_value={"text_value": "gone-soon"})
    block = _whole_list_block(db, protocol, definition.id)
    user = make_current_user(tenant.id)

    # Baseline sync (nothing changed yet relative to itself).
    protocol_elements.sync_block_list_snapshot(block.id, db=db, user=user)

    to_change.column_one_value_json = {"text_value": "after"}
    db.add(to_change)
    new_entry = make_list_entry(db, definition.id, sort_index=3, column_one_value={"text_value": "brand-new"})
    db.delete(to_remove)
    db.commit()

    result = protocol_elements.sync_block_list_snapshot(block.id, db=db, user=user)
    entries = {e["id"]: e for e in result.configuration_snapshot_json["list_snapshot"]["entries"]}

    assert entries[kept.id].get("_tracked") is None
    assert entries[to_change.id]["_tracked"] == "changed"
    assert entries[to_change.id]["_tracked_before"]["column_one_value"]["text_value"] == "before"
    assert entries[new_entry.id]["_tracked"] == "added"
    removed = [e for e in entries.values() if e.get("_tracked") == "removed"]
    assert len(removed) == 1
    assert removed[0]["column_one_value"]["text_value"] == "gone-soon"

    # A second, no-op sync must not lose the markers or duplicate the removed phantom.
    again = protocol_elements.sync_block_list_snapshot(block.id, db=db, user=user)
    entries_again = {e["id"]: e for e in again.configuration_snapshot_json["list_snapshot"]["entries"]}
    assert entries_again[to_change.id]["_tracked"] == "changed"
    assert entries_again[to_change.id]["_tracked_before"]["column_one_value"]["text_value"] == "before"
    removed_again = [e for e in entries_again.values() if e.get("_tracked") == "removed"]
    assert len(removed_again) == 1


def test_row_link_sync_marks_changed_and_removed(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "before"})
    block = _row_link_block(db, protocol, definition.id, entry.id)
    user = make_current_user(tenant.id)

    protocol_elements.sync_block_list_snapshot(block.id, db=db, user=user)

    entry.column_one_value_json = {"text_value": "after"}
    db.add(entry)
    db.commit()
    result = protocol_elements.sync_block_list_snapshot(block.id, db=db, user=user)
    row_snapshot = result.configuration_snapshot_json["rows"][0]["list_snapshot"]
    assert row_snapshot["_tracked"] == "changed"
    assert row_snapshot["_tracked_before"]["column_one_value"]["text_value"] == "before"

    db.delete(entry)
    db.commit()
    removed_result = protocol_elements.sync_block_list_snapshot(block.id, db=db, user=user)
    removed_row_snapshot = removed_result.configuration_snapshot_json["rows"][0]["list_snapshot"]
    assert removed_row_snapshot["_tracked"] == "removed"


def test_list_toggle_off_mid_geplant_stops_new_marking_without_erasing(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "before"})
    block = _whole_list_block(db, protocol, definition.id)
    user = make_current_user(tenant.id)

    protocol_elements.sync_block_list_snapshot(block.id, db=db, user=user)
    entry.column_one_value_json = {"text_value": "changed-while-active"}
    db.add(entry)
    db.commit()
    protocol_elements.sync_block_list_snapshot(block.id, db=db, user=user)

    protocol_service.update_protocol(db, protocol.id, ProtocolUpdate(track_changes_enabled=False))
    entry.column_one_value_json = {"text_value": "changed-while-inactive"}
    db.add(entry)
    db.commit()
    result = protocol_elements.sync_block_list_snapshot(block.id, db=db, user=user)
    entries = {e["id"]: e for e in result.configuration_snapshot_json["list_snapshot"]["entries"]}
    assert entries[entry.id]["_tracked"] == "changed"
    # The pinned before-value is the ORIGINAL, from before tracking was toggled off.
    assert entries[entry.id]["_tracked_before"]["column_one_value"]["text_value"] == "before"
    assert entries[entry.id]["column_one_value"]["text_value"] == "changed-while-inactive"


# ---- Clearing on vorbereitet -> durchgeführt ----

def test_clear_on_vorbereitet_to_durchgefuehrt(db):
    tenant = make_tenant(db)
    protocol = _geplant_protocol(db, tenant)
    text_block = _block(db, protocol)
    todo_block = _block(db, protocol, element_type_code="todo")
    definition = make_list_definition(db, tenant.id)
    kept_entry = make_list_entry(db, definition.id, column_one_value={"text_value": "v1"})
    list_block = _whole_list_block(db, protocol, definition.id)
    user = make_current_user(tenant.id)

    # All marking happens while still "geplant" (the tracked phase).
    protocol_elements.put_protocol_text(text_block.id, ProtocolTextUpdate(content="edited"), db=db, user=user)
    added_todo = todos.create_todo(todo_block.id, ProtocolTodoCreate(task="added"), db=db, user=user)
    pre_existing_todo = make_protocol_todo(db, todo_block.id, task="pre-existing", sort_index=1)
    todos.delete_todo(pre_existing_todo.id, db=db, user=user)
    protocol_elements.sync_block_list_snapshot(list_block.id, db=db, user=user)
    kept_entry.column_one_value_json = {"text_value": "v2"}
    db.add(kept_entry)
    db.commit()
    protocol_elements.sync_block_list_snapshot(list_block.id, db=db, user=user)

    # Marks must survive the geplant -> vorbereitet transition (still visible during the
    # live session) and only actually disappear at vorbereitet -> durchgeführt.
    protocol_service.update_protocol(db, protocol.id, ProtocolUpdate(status="vorbereitet"))
    db.expire_all()
    from app.repositories.protocol_element_repository import ProtocolTextRepository
    still_marked_text = ProtocolTextRepository().get_by_protocol_element_block_id(db, text_block.id)
    assert still_marked_text.tracked_dirty is True

    protocol_service.update_protocol(db, protocol.id, ProtocolUpdate(status="durchgeführt"))

    db.expire_all()
    saved_text = ProtocolTextRepository().get_by_protocol_element_block_id(db, text_block.id)
    assert saved_text.tracked_dirty is False
    assert saved_text.tracked_baseline_content is None

    assert todo_service.repository.get(db, pre_existing_todo.id) is None  # hard-deleted for real
    added_todo_after = todo_service.repository.get(db, added_todo.id)
    assert added_todo_after.tracked_change is None

    from app.models.entities import ProtocolElementBlock
    refreshed_list_block = db.get(ProtocolElementBlock, list_block.id)
    entries = refreshed_list_block.configuration_snapshot_json["list_snapshot"]["entries"]
    assert all("_tracked" not in e and "_tracked_before" not in e for e in entries)
