"""Translates internal ids embedded in an ElementDefinitionBlock/TemplateElement block's
configuration_json to/from public ids, for the two spots this JSON is read/written
directly by an HTTP client: element_definition_service.py and template_element_service.py
(the "block designer" UI - list/matrix/table blocks referencing a ListDefinition,
Participant, Event, FinanceAccount by id). Every OTHER consumer of this same stored JSON
(protocol_service.py building a real protocol from a template, word_import_service.py,
list_snapshot_service.py, tenant_transfer_common.py's clone/export/import remapping) reads
it purely internally and is untouched by this module or by the public_id migration -
those ids stay internal ints in storage, exactly as before. Only the two designer-service
read/write boundaries route through encode/decode here.

Field inventory (kept in sync with element-definition-manager.tsx/template-builder.tsx's
BlockFormState -> configuration_json mapping):
- top-level: linked_list_id, matrix_column_source_list_id (legacy, read-only for old
  data), finance_account_id, fine_account_id, auto_source.list_id
- per-row (config["rows"]): template_participant_id, template_participant_ids[],
  template_event_id, row_config.linked_list_id, row_config.linked_list_entry_id
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Event, FinanceAccount, ListDefinition, ListEntry, Participant
from app.services import public_id_service


def _encode_id(db: Session, model: type, value: Any) -> Any:
    if value is None:
        return None
    return public_id_service.resolve_public_id(db, model, int(value))


def _decode_id(db: Session, model: type, value: Any, *, tenant_id: int) -> Any:
    """Raises directly on an unresolvable/foreign uuid, rather than returning a sentinel -
    element_definition_service.py's/template_element_service.py's existing
    _validate_linked_lists re-validates these same ids afterward, but its `if candidate:`-
    style truthiness checks would silently skip a falsy sentinel (e.g. 0) and let an
    invalid reference through, so this has to fail closed here instead."""
    if value is None:
        return None
    internal_id = public_id_service.resolve_internal_id(db, model, value, tenant_id=tenant_id)
    if internal_id is None:
        raise ValueError(f"{model.__name__} {value} not found")
    return internal_id


def _encode_row(db: Session, row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    row = dict(row)
    row["template_participant_id"] = _encode_id(db, Participant, row.get("template_participant_id"))
    raw_ids = row.get("template_participant_ids") or []
    ids = [int(pid) for pid in raw_ids if pid]
    mapping = public_id_service.resolve_public_ids(db, Participant, ids) if ids else {}
    row["template_participant_ids"] = [mapping[i] for i in ids if i in mapping]
    row["template_event_id"] = _encode_id(db, Event, row.get("template_event_id"))
    row_config = row.get("row_config")
    if isinstance(row_config, dict):
        row_config = dict(row_config)
        row_config["linked_list_id"] = _encode_id(db, ListDefinition, row_config.get("linked_list_id"))
        row_config["linked_list_entry_id"] = _encode_id(db, ListEntry, row_config.get("linked_list_entry_id"))
        row["row_config"] = row_config
    return row


def _decode_row(db: Session, row: Any, *, tenant_id: int) -> Any:
    if not isinstance(row, dict):
        return row
    row = dict(row)
    row["template_participant_id"] = _decode_id(db, Participant, row.get("template_participant_id"), tenant_id=tenant_id)
    row["template_participant_ids"] = [
        _decode_id(db, Participant, pid, tenant_id=tenant_id) for pid in (row.get("template_participant_ids") or []) if pid
    ]
    row["template_event_id"] = _decode_id(db, Event, row.get("template_event_id"), tenant_id=tenant_id)
    row_config = row.get("row_config")
    if isinstance(row_config, dict):
        row_config = dict(row_config)
        row_config["linked_list_id"] = _decode_id(db, ListDefinition, row_config.get("linked_list_id"), tenant_id=tenant_id)
        row_config["linked_list_entry_id"] = _decode_id(db, ListEntry, row_config.get("linked_list_entry_id"), tenant_id=tenant_id)
        row["row_config"] = row_config
    return row


def _encode_responsibility_assignment(db: Session, assignment: Any) -> Any:
    if not isinstance(assignment, dict):
        return assignment
    assignment = dict(assignment)
    assignment["participant_id"] = _encode_id(db, Participant, assignment.get("participant_id"))
    assignment["list_definition_id"] = _encode_id(db, ListDefinition, assignment.get("list_definition_id"))
    assignment["list_entry_id"] = _encode_id(db, ListEntry, assignment.get("list_entry_id"))
    return assignment


def _decode_responsibility_assignment(db: Session, assignment: Any, *, tenant_id: int) -> Any:
    if not isinstance(assignment, dict):
        return assignment
    assignment = dict(assignment)
    assignment["participant_id"] = _decode_id(db, Participant, assignment.get("participant_id"), tenant_id=tenant_id)
    assignment["list_definition_id"] = _decode_id(db, ListDefinition, assignment.get("list_definition_id"), tenant_id=tenant_id)
    assignment["list_entry_id"] = _decode_id(db, ListEntry, assignment.get("list_entry_id"), tenant_id=tenant_id)
    return assignment


def encode_block_config(db: Session, config: dict | None) -> dict:
    if not config:
        return config or {}
    result = dict(config)
    if result.get("linked_list_id") is not None:
        result["linked_list_id"] = _encode_id(db, ListDefinition, result["linked_list_id"])
    if result.get("matrix_column_source_list_id") is not None:
        result["matrix_column_source_list_id"] = _encode_id(db, ListDefinition, result["matrix_column_source_list_id"])
    if result.get("finance_account_id") is not None:
        result["finance_account_id"] = _encode_id(db, FinanceAccount, result["finance_account_id"])
    if result.get("fine_account_id") is not None:
        result["fine_account_id"] = _encode_id(db, FinanceAccount, result["fine_account_id"])
    auto_source = result.get("auto_source")
    if isinstance(auto_source, dict) and auto_source.get("list_id") is not None:
        result["auto_source"] = {**auto_source, "list_id": _encode_id(db, ListDefinition, auto_source["list_id"])}
    rows = result.get("rows")
    if isinstance(rows, list):
        result["rows"] = [_encode_row(db, row) for row in rows]
    responsibility = result.get("responsibility")
    if isinstance(responsibility, dict) and isinstance(responsibility.get("assignments"), list):
        result["responsibility"] = {
            **responsibility,
            "assignments": [_encode_responsibility_assignment(db, a) for a in responsibility["assignments"]],
        }
    return result


def decode_block_config(db: Session, config: dict | None, *, tenant_id: int) -> dict:
    if not config:
        return config or {}
    result = dict(config)
    if result.get("linked_list_id") is not None:
        result["linked_list_id"] = _decode_id(db, ListDefinition, result["linked_list_id"], tenant_id=tenant_id)
    if result.get("matrix_column_source_list_id") is not None:
        result["matrix_column_source_list_id"] = _decode_id(db, ListDefinition, result["matrix_column_source_list_id"], tenant_id=tenant_id)
    if result.get("finance_account_id") is not None:
        result["finance_account_id"] = _decode_id(db, FinanceAccount, result["finance_account_id"], tenant_id=tenant_id)
    if result.get("fine_account_id") is not None:
        result["fine_account_id"] = _decode_id(db, FinanceAccount, result["fine_account_id"], tenant_id=tenant_id)
    auto_source = result.get("auto_source")
    if isinstance(auto_source, dict) and auto_source.get("list_id") is not None:
        result["auto_source"] = {**auto_source, "list_id": _decode_id(db, ListDefinition, auto_source["list_id"], tenant_id=tenant_id)}
    rows = result.get("rows")
    if isinstance(rows, list):
        result["rows"] = [_decode_row(db, row, tenant_id=tenant_id) for row in rows]
    responsibility = result.get("responsibility")
    if isinstance(responsibility, dict) and isinstance(responsibility.get("assignments"), list):
        result["responsibility"] = {
            **responsibility,
            "assignments": [
                _decode_responsibility_assignment(db, a, tenant_id=tenant_id) for a in responsibility["assignments"]
            ],
        }
    return result
