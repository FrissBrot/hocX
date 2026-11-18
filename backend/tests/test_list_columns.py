"""Listen mit dynamischen Spalten (Migrationen 0186/0187): Spalten-Verwaltung, Rollen, Werte,
Personen-Bereinigung, Mandantentrennung, Migration der Altdaten und v1-Adapter."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.api.routes import lists as lists_route
from app.models import ListDefinition, ListEntry
from app.schemas.list_definition import ListColumnCreate, ListColumnOrder, ListColumnUpdate, ListDefinitionCreate, ListDefinitionUpdate, ListEntryUpdate
from app.services import list_column_migration, list_columns, list_legacy_adapter
from app.services.list_service import ListService
from app.services.participant_service import ParticipantService
from tests.factories import make_current_user, make_list_definition, make_list_entry, make_participant, make_tenant

BACKEND_ROOT = Path(__file__).resolve().parents[1]
service = ListService()


def _keys(definition):
    return [column.key for column in list_columns.columns_of(definition)]


# ── Spalten-Verwaltung ───────────────────────────────────────────────────────────────────


def test_new_list_gets_start_columns_and_roles(db):
    tenant = make_tenant(db)
    created = service.create_definition(
        db, ListDefinitionCreate(name="Ämtli", columns=[ListColumnCreate(title="Ämtli"), ListColumnCreate(title="Wer", value_type="participants")]),
        tenant_id=tenant.id,
    )
    assert [column.title for column in created.columns] == ["Ämtli", "Wer"]
    assert created.label_column_id == created.columns[0].id
    assert created.responsible_column_id == created.columns[1].id

    plain = service.create_definition(db, ListDefinitionCreate(name="Leer"), tenant_id=tenant.id)
    assert len(plain.columns) == 1 and plain.columns[0].value_type == "text"


def test_add_rename_reorder_and_delete_columns(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, first_value={"text_value": "a"}, second_value={"text_value": "b"})
    version = definition.content_version

    service.add_column(db, definition, ListColumnCreate(title="Notiz"))
    third = list_columns.columns_of(definition)[2]
    assert definition.content_version > version
    service.update_entry(db, entry.id, ListEntryUpdate(values={third.key: {"text_value": "c"}}))

    service.update_column(db, definition, third, ListColumnUpdate(title="Bemerkung"))
    assert third.title == "Bemerkung"

    service.reorder_columns(db, definition, [third.key, "k1", "k2"])
    assert _keys(definition) == [third.key, "k1", "k2"]

    service.delete_column(db, definition, third)
    db.refresh(entry)
    assert third.key not in entry.values_json and entry.values_json == {"k1": {"text_value": "a"}, "k2": {"text_value": "b"}}


def test_last_column_cannot_be_deleted_and_limit_holds(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id, second_title=None)
    with pytest.raises(ValueError):
        service.delete_column(db, definition, list_columns.columns_of(definition)[0])
    for index in range(list_columns.MAX_COLUMNS - 1):
        service.add_column(db, definition, ListColumnCreate(title=f"S{index}"))
    with pytest.raises(ValueError):
        service.add_column(db, definition, ListColumnCreate(title="zu viel"))


def test_type_change_clears_values_and_drops_unfitting_role(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, first_value={"text_value": "a"}, second_value={"text_value": "b"})
    first = list_columns.columns_of(definition)[0]
    assert definition.label_column_id == first.id

    service.update_column(db, definition, first, ListColumnUpdate(value_type="participant"))
    db.refresh(entry)
    assert "k1" not in entry.values_json and entry.values_json["k2"] == {"text_value": "b"}
    assert definition.label_column_id is None  # Personen-Spalte kann keinen Eintrag benennen


def test_role_must_fit_the_column_type(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id, second_type="participant")
    with pytest.raises(ValueError):
        service.update_definition(db, definition.id, ListDefinitionUpdate(responsible_column_id="k1"))
    with pytest.raises(ValueError):
        service.update_definition(db, definition.id, ListDefinitionUpdate(label_column_id="k2"))
    updated = service.update_definition(db, definition.id, ListDefinitionUpdate(responsible_column_id="k2"))
    assert updated.responsible_column_id == "k2"


def test_unknown_column_in_values_is_rejected(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id)
    with pytest.raises(ValueError):
        service.update_entry(db, entry.id, ListEntryUpdate(values={"fremd": {"text_value": "x"}}))


def test_foreign_tenant_cannot_reach_columns(db):
    tenant, other = make_tenant(db, "Eigen"), make_tenant(db, "Fremd")
    definition = make_list_definition(db, tenant.id)
    stranger = make_current_user(other.id, role="admin")
    with pytest.raises(HTTPException) as exc_info:
        lists_route.patch_column(definition.public_id, "k1", ListColumnUpdate(title="x"), db=db, user=stranger)
    assert exc_info.value.status_code == 404
    with pytest.raises(HTTPException):
        lists_route.reorder_columns(definition.public_id, ListColumnOrder(column_ids=["k2", "k1"]), db=db, user=stranger)


def test_rls_protects_list_columns(db):
    enabled = db.scalar(text("SELECT relrowsecurity FROM pg_class WHERE relname = 'list_column' AND relnamespace = 'public'::regnamespace"))
    assert enabled is True


# ── Konsumenten ────────────────────────────────────────────────────────────────────────────


def test_label_and_responsible_follow_the_roles_with_many_columns(db):
    tenant = make_tenant(db)
    anna, ben = make_participant(db, tenant.id, "Anna"), make_participant(db, tenant.id, "Ben")
    definition = make_list_definition(
        db, tenant.id, first_title="Nr.", second_title="Helfer", second_type="participants",
        extra_columns=[("Bezeichnung", "text"), ("Leitung", "participant"), ("Ort", "text")],
    )
    columns = list_columns.columns_of(definition)
    definition.label_column_id = columns[2].id
    definition.responsible_column_id = columns[3].id
    db.flush()
    entry = make_list_entry(db, definition.id, values={
        "k1": {"text_value": "1"}, "k2": {"participant_ids": [ben.id]}, "k3": {"text_value": "Zeltaufbau"},
        "k4": {"participant_id": anna.id}, "k5": {"text_value": "Wiese"},
    })
    assert list_columns.label_of(entry, definition) == "Zeltaufbau"
    assert list_columns.responsible_ids_of(entry, definition) == [anna.id]
    assert list_columns.all_participant_ids(entry, definition) == {anna.id, ben.id}


def test_deleting_a_person_clears_references_in_every_column(db):
    tenant = make_tenant(db)
    gone, keep = make_participant(db, tenant.id, "Weg"), make_participant(db, tenant.id, "Bleibt")
    definition = make_list_definition(db, tenant.id, first_type="participant", second_type="participants", extra_columns=[("Dritte", "participants")])
    entry = make_list_entry(db, definition.id, values={
        "k1": {"participant_id": gone.id}, "k2": {"participant_ids": [gone.id, keep.id]}, "k3": {"participant_ids": [gone.id]},
    })
    ParticipantService().delete_participant(db, gone.id, tenant_id=tenant.id)
    db.refresh(entry)
    assert entry.values_json == {"k2": {"participant_ids": [keep.id]}}


# ── Migration 0186 / 0187 ───────────────────────────────────────────────────────────────────


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BACKEND_ROOT / "alembic/versions" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_copies_legacy_columns_values_and_roles(db):
    tenant = make_tenant(db)
    anna = make_participant(db, tenant.id, "Anna")
    definition_id = db.scalar(text(
        "INSERT INTO list_definition (tenant_id, name, column_one_title, column_one_value_type, column_two_title, column_two_value_type) "
        "VALUES (:t, 'Alt', 'Wer', 'participant', 'Ämtli', 'text') RETURNING id"
    ), {"t": tenant.id})
    db.execute(text(
        "INSERT INTO list_entry (list_definition_id, column_one_value_json, column_two_value_json) "
        "VALUES (:d, CAST(:one AS jsonb), CAST(:two AS jsonb)), (:d, '{}'::jsonb, CAST(:only AS jsonb))"
    ), {"d": definition_id, "one": f'{{"participant_id": {anna.id}}}', "two": '{"text_value": "Kasse"}', "only": '{"text_value": "Putzen"}'})

    migration = _load("0186_list_columns")
    migration.copy_legacy_data(lambda statement: db.execute(text(statement)))
    migration.copy_legacy_data(lambda statement: db.execute(text(statement)))  # idempotent

    definition = db.get(ListDefinition, definition_id)
    db.refresh(definition)
    columns = list_columns.columns_of(definition)
    assert [(c.title, c.value_type, c.legacy_key) for c in columns] == [("Wer", "participant", "column_one"), ("Ämtli", "text", "column_two")]
    # Bezeichnung: erste Text-Spalte (auch wenn sie die zweite ist), Verantwortliche: erste Personen-Spalte
    assert definition.label_column_id == columns[1].id and definition.responsible_column_id == columns[0].id
    entries = db.scalars(text("SELECT values_json FROM list_entry WHERE list_definition_id = :d ORDER BY id"), {"d": definition_id}).all()
    assert entries == [
        {columns[0].key: {"participant_id": anna.id}, columns[1].key: {"text_value": "Kasse"}},
        {columns[1].key: {"text_value": "Putzen"}},
    ]


def test_config_migration_rewrites_every_known_key():
    key_map = {7: {"column_one": "a1", "column_two": "a2"}, "list-uuid": {"column_one": "b1", "column_two": "b2"}, 9: {"column_one": "m1", "column_two": "m2"}}
    report = list_column_migration.Report()
    config = {
        "linked_list_id": 7, "linked_list_group_by": "column_two", "linked_list_sort_by": "column_one", "linked_list_filter_column": None,
        "auto_source": {"type": "list", "list_id": 9},
        "rows": [
            {"id": "r1", "row_config": {"linked_list_id": 7, "list_fixed_column": "column_two"}},
            {"id": "r2", "auto_source_field": "column_one"},
            {"id": "r3", "row_config": {"linked_list_id": 404, "list_fixed_column": "column_one"}},
        ],
    }
    result = list_column_migration.rewrite_block_config(config, key_map, report)
    assert result["linked_list_group_by"] == "a2" and result["linked_list_sort_by"] == "a1" and result["linked_list_filter_column"] is None
    assert result["rows"][0]["row_config"]["list_fixed_column"] == "a2"
    assert result["rows"][1]["auto_source_field"] == "m1"
    assert result["rows"][2]["row_config"]["list_fixed_column"] is None  # Liste existiert nicht mehr
    assert report.rewritten == 4 and report.nulled == 1

    studio = list_column_migration.rewrite_studio_params(
        {"nodes": [{"params": {"list_id": "LIST-UUID", "group_by": "column_one", "sort_by": "", "filter_column": "column_two"}}]}, key_map, report,
    )
    assert studio["nodes"][0]["params"] == {"list_id": "LIST-UUID", "group_by": "b1", "sort_by": "", "filter_column": "b2"}


def test_config_migration_upgrades_open_protocol_snapshots():
    report = list_column_migration.Report()
    config = {
        "linked_list_id": 7,
        "list_snapshot": {
            "synced_version": 3, "column_one_title": "Ämtli", "column_one_value_type": "text", "column_two_title": "Wer", "column_two_value_type": "participant",
            "entries": [{"id": 1, "sort_index": 0, "column_one_value": {"text_value": "Kasse"}, "column_two_value": {"participant_id": 5}, "_tracked": "changed",
                         "_tracked_before": {"column_one_value": {"text_value": "Kasse"}, "column_two_value": {"participant_id": 4}}}],
        },
    }
    result = list_column_migration.rewrite_block_config(config, {7: {"column_one": "a1", "column_two": "a2"}}, report, upgrade_snapshots=True)
    snapshot = result["list_snapshot"]
    assert snapshot["snapshot_version"] == 2 and snapshot["synced_version"] == 3
    assert [column["id"] for column in snapshot["columns"]] == ["a1", "a2"]
    assert snapshot["label_column_id"] == "a1" and snapshot["responsible_column_id"] == "a2"
    assert snapshot["entries"][0]["values"] == {"a1": {"text_value": "Kasse"}, "a2": {"participant_id": 5}}
    assert snapshot["entries"][0]["_tracked_before"] == {"values": {"a1": {"text_value": "Kasse"}, "a2": {"participant_id": 4}}}
    assert report.snapshots == 1


# ── v1-Adapter ───────────────────────────────────────────────────────────────────────────────


def test_adapter_uses_real_keys_while_the_list_exists(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    row_snapshot = {"entry_exists": True, "column_one_title": "Name", "column_one_value_type": "text", "column_two_title": "Wert",
                    "column_two_value_type": "text", "column_one_value": {"text_value": "x"}, "column_two_value": {},
                    "previous": {"entry_exists": True, "column_one_title": "Name", "column_one_value_type": "text", "column_one_value": {"text_value": "alt"}}}
    upgraded = list_legacy_adapter.upgrade_list_snapshot(row_snapshot, definition=definition)
    assert upgraded["values"] == {"k1": {"text_value": "x"}}
    assert upgraded["previous"]["values"] == {"k1": {"text_value": "alt"}}
    assert list_columns.resolve_column(definition, "column_two").key == "k2"
    assert list_columns.resolve_column(definition, "legacy:column_one").key == "k1"
    assert list_columns.resolve_column(definition, "gibt-es-nicht") is None


def test_normalizing_a_config_drops_foreign_columns(db):
    tenant, other = make_tenant(db, "Eigen"), make_tenant(db, "Fremd")
    own = make_list_definition(db, tenant.id)
    foreign = make_list_definition(db, other.id)
    config = {"linked_list_id": own.id, "linked_list_group_by": "column_two", "linked_list_sort_by": "erfunden",
              "rows": [{"row_config": {"linked_list_id": foreign.id, "list_fixed_column": "k1"}}]}
    result = list_columns.normalize_config_column_keys(db, config, tenant_id=tenant.id)
    assert result["linked_list_group_by"] == "k2" and result["linked_list_sort_by"] is None
    # Fremde Liste wird nicht aufgelöst: der Key bleibt unverändert, wirkt aber nirgends
    assert result["rows"][0]["row_config"]["list_fixed_column"] == "k1"
    assert uuid.UUID(str(own.public_id))


# ── Security-Review (Import, Verwendungs-Suche) ─────────────────────────────────────────────


def test_import_accepts_only_uuid_keys_and_known_legacy_keys():
    from app.services.tenant_import_service import validated_column_row

    key = str(uuid.uuid4())
    row = validated_column_row({"key": key, "title": "x" * 500, "value_type": "kaputt", "legacy_key": "column_two"})
    assert row["key"] == key and len(row["title"]) == 200 and row["value_type"] == "text"
    for bad in ({"key": "%"}, {"key": "k_1"}, {"key": None}, {"key": "a" * 65}, {"key": "a\\b"}, {"key": key, "legacy_key": "column_three"}):
        with pytest.raises(ValueError):
            validated_column_row(bad)


def test_column_usages_treat_the_key_as_text(db):
    tenant = make_tenant(db, "Verwendung")
    definition = make_list_definition(db, tenant.id, "Ämtli")
    from tests.factories import make_element_definition

    make_element_definition(db, tenant.id, "Baustein", [{"id": 1, "title": "A", "config": {"list_fixed_column": "k1"}}])
    assert lists_route.column_usages(db, tenant_id=tenant.id, column_key="%") == []
    assert lists_route.column_usages(db, tenant_id=tenant.id, column_key="k_") == []
    assert [usage.label for usage in lists_route.column_usages(db, tenant_id=tenant.id, column_key="k1")] == ["Baustein"]
    assert definition is not None
