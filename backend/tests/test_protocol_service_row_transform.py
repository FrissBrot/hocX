"""Tests for ProtocolService._transform_field_row - specifically that
row_config.value_source ("live"/"historical", the "historische Daten verwenden" row
option) is flattened onto the runtime row schema the same way linked_list_id/
linked_list_entry_id/list_fixed_column already are, so
list_snapshot_service.compute_row_list_snapshot_for_protocol can see it."""
from app.services.protocol_service import ProtocolService


def test_transform_field_row_flattens_value_source_for_list_entry_rows():
    row = {
        "id": "row-1",
        "row_type": "list_entry",
        "row_config": {"linked_list_id": 42, "linked_list_entry_id": 7, "list_fixed_column": "column_one", "value_source": "historical"},
    }

    transformed = ProtocolService()._transform_field_row(row, repeat_context=None)

    assert transformed["value_type"] == "list_entry"
    assert transformed["linked_list_id"] == 42
    assert transformed["linked_list_entry_id"] == 7
    assert transformed["value_source"] == "historical"


def test_transform_field_row_defaults_value_source_to_none_when_unset():
    row = {
        "id": "row-2",
        "row_type": "list_entry",
        "row_config": {"linked_list_id": 42, "linked_list_entry_id": 7, "list_fixed_column": "column_one"},
    }

    transformed = ProtocolService()._transform_field_row(row, repeat_context=None)

    assert transformed["value_source"] is None


def test_transform_field_row_value_source_is_none_for_non_list_entry_rows():
    row = {"id": "row-3", "row_type": "text", "template_value": "Hello"}

    transformed = ProtocolService()._transform_field_row(row, repeat_context=None)

    assert transformed["value_type"] == "text"
    assert transformed["value_source"] is None
