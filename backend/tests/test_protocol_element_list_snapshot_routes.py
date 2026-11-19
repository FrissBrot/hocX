"""Route-level tests for the three new list-snapshot endpoints. Route functions are
called directly as plain Python callables (bypassing Depends/ASGI/auth entirely) since
FastAPI decorators don't change how a function behaves when invoked directly - this
avoids needing a TestClient/auth-cookie test harness that doesn't exist yet in this repo."""
import pytest
from fastapi import HTTPException

from app.api.routes import protocol_elements
from app.schemas.protocol import ProtocolUpdate
from app.services.protocol_service import ProtocolService

from tests.factories import (
    make_current_user,
    make_list_definition,
    make_list_entry,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def _row_block(db, tenant, definition, entry):
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(
        db,
        element.id,
        configuration_snapshot_json={
            "linked_list_id": None,
            "rows": [{
                "id": "row-1", "value_type": "list_entry",
                "linked_list_id": definition.id, "linked_list_entry_id": entry.id,
                "list_fixed_column": "column_one", "label": "",
            }],
        },
    )
    return protocol, block


def test_refresh_is_scoped_to_owning_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    definition = make_list_definition(db, tenant_a.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "v1"})
    _protocol, block = _row_block(db, tenant_a, definition, entry)

    # ensure_can_read_protocol_block (the existing, reused access-control guard) rejects
    # this as 403 "not assigned to current reader" rather than 404 - matches its behavior
    # for every other route that reuses it, not something new to this feature.
    other_tenant_user = make_current_user(tenant_b.id)
    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.refresh_block_list_snapshot(block.public_id, db=db, user=other_tenant_user)
    # 404 unter Row-Level-Security (Migration 0134): der fremde Block ist dann gar nicht sichtbar.
    assert exc_info.value.status_code in (403, 404)

    same_tenant_user = make_current_user(tenant_a.id)
    result = protocol_elements.refresh_block_list_snapshot(block.public_id, db=db, user=same_tenant_user)
    assert result.configuration_snapshot_json["rows"][0]["list_snapshot"]["column_one_value"]["text_value"] == "v1"


def test_refresh_returns_409_when_protocol_is_abgeschlossen(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id)
    protocol, block = _row_block(db, tenant, definition, entry)

    ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(status="vorbereitet"))
    ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(status="durchgeführt"))
    ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))

    user = make_current_user(tenant.id)
    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.refresh_block_list_snapshot(block.public_id, db=db, user=user)
    assert exc_info.value.status_code == 409


def test_sync_then_undo_round_trip(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "v1"})
    _protocol, block = _row_block(db, tenant, definition, entry)
    user = make_current_user(tenant.id)

    protocol_elements.refresh_block_list_snapshot(block.public_id, db=db, user=user)
    entry.column_one_value_json = {"text_value": "v2"}
    db.add(entry)
    db.commit()
    refreshed = protocol_elements.refresh_block_list_snapshot(block.public_id, db=db, user=user)
    assert refreshed.configuration_snapshot_json["rows"][0]["list_snapshot"]["column_one_value"]["text_value"] == "v2"

    undone = protocol_elements.undo_block_list_snapshot(block.public_id, db=db, user=user)
    assert undone.configuration_snapshot_json["rows"][0]["list_snapshot"]["column_one_value"]["text_value"] == "v1"

    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.undo_block_list_snapshot(block.public_id, db=db, user=user)
    assert exc_info.value.status_code == 409


def test_sync_does_not_require_writer_role_change_but_rejects_reader(db):
    tenant = make_tenant(db)
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id)
    _protocol, block = _row_block(db, tenant, definition, entry)

    reader = make_current_user(tenant.id, role="reader")
    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.sync_block_list_snapshot(block.public_id, db=db, user=reader)
    assert exc_info.value.status_code == 403


def test_row_link_with_foreign_list_entry_id_does_not_copy_foreign_values(db):
    """Nachtlauf 2026-11-19 (protokolle/mandantentrennung): rows[].linked_list_entry_id ist
    frei setzbar (PATCH configuration_snapshot_json speichert das JSON ungeprüft). Die Liste
    selbst wird auf den Mandanten geprüft, der Eintrag aber per db.get geladen - ohne Bezug
    zur Liste. Ein Schreiber verweist so auf eine eigene Liste und eine fremde (fortlaufende,
    erratbare) Eintrags-ID und liest beim Aktualisieren die Werte des fremden Mandanten."""
    from app.schemas.protocol import ProtocolElementBlockUpdate

    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    own_definition = make_list_definition(db, tenant_a.id)
    own_entry = make_list_entry(db, own_definition.id, column_one_value={"text_value": "eigen"})
    foreign_definition = make_list_definition(db, tenant_b.id)
    foreign_entry = make_list_entry(db, foreign_definition.id, column_one_value={"text_value": "geheim"})
    _protocol, block = _row_block(db, tenant_a, own_definition, own_entry)
    user = make_current_user(tenant_a.id)

    config = dict(block.configuration_snapshot_json)
    config["rows"] = [{**config["rows"][0], "linked_list_entry_id": foreign_entry.id}]
    protocol_elements.patch_protocol_element_block(
        block.public_id, ProtocolElementBlockUpdate(configuration_snapshot_json=config), db=db, user=user
    )
    refreshed = protocol_elements.refresh_block_list_snapshot(block.public_id, db=db, user=user)

    snapshot = refreshed.configuration_snapshot_json["rows"][0]["list_snapshot"]
    assert snapshot["entry_exists"] is False
    assert "geheim" not in str(refreshed.configuration_snapshot_json)


def test_row_link_with_entry_of_other_own_list_is_not_resolved(db):
    """Gleiche Ursache innerhalb eines Mandanten: der Eintrag muss zur verknüpften Liste gehören."""
    from app.services import list_snapshot_service

    tenant = make_tenant(db)
    list_one = make_list_definition(db, tenant.id)
    list_two = make_list_definition(db, tenant.id, name="Zweite Liste")
    entry_two = make_list_entry(db, list_two.id, column_one_value={"text_value": "andere Liste"})

    snapshot = list_snapshot_service.compute_row_list_snapshot(db, list_one.id, entry_two.id, tenant.id)
    assert snapshot["entry_exists"] is False
