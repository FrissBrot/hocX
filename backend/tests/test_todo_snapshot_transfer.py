"""Audit MAIN-BE-012: Import und Klon übernehmen die eingefrorene Todo-Liste abgeschlossener
Protokolle (Block-Keys und public_ids umgeschrieben)."""
from sqlalchemy import select

from app.models.entities import Protocol, ProtocolElement, ProtocolElementBlock, ProtocolTodo
from app.services.protocol_todo_service import ProtocolTodoService
from app.services.tenant_clone_service import TenantCloneService
from app.services.tenant_export_service import TenantExportService
from app.services.tenant_import_service import TenantImportService
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_todo, make_template, make_tenant


def _closed_protocol_with_snapshot(db):
    tenant = make_tenant(db, "Snapshot-Quelle")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-zu")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="todo")
    make_protocol_todo(db, block.id, task="Eingefrorene Aufgabe", tenant_id=tenant.id)
    protocol.todos_snapshot_json = ProtocolTodoService().build_protocol_snapshot(db, protocol)
    protocol.status = "abgeschlossen"
    db.flush()
    assert str(block.id) in protocol.todos_snapshot_json["blocks"]
    return tenant, protocol


def _assert_snapshot_follows_new_rows(db, new_tenant_id: int, source_block_id_key: str) -> None:
    new_protocol = db.scalar(select(Protocol).where(Protocol.tenant_id == new_tenant_id))
    snapshot = ProtocolTodoService.frozen_snapshot(new_protocol)
    assert snapshot is not None
    new_block = db.scalar(
        select(ProtocolElementBlock)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .where(ProtocolElement.protocol_id == new_protocol.id)
    )
    items = ProtocolTodoService().snapshot_todos_for_block(snapshot, new_block.id)
    assert [item.task for item in items] == ["Eingefrorene Aufgabe"]
    new_todo = db.scalar(select(ProtocolTodo).where(ProtocolTodo.protocol_element_block_id == new_block.id))
    assert str(items[0].id) == str(new_todo.public_id)
    if str(new_block.id) != source_block_id_key:
        assert source_block_id_key not in snapshot["blocks"]


def test_clone_keeps_remapped_todo_snapshot(db):
    tenant, protocol = _closed_protocol_with_snapshot(db)
    source_key = next(iter(protocol.todos_snapshot_json["blocks"]))

    cloned = TenantCloneService().clone_full(db, tenant.id, "Snapshot-Kopie")

    _assert_snapshot_follows_new_rows(db, cloned.id, source_key)


def test_import_keeps_remapped_todo_snapshot(db):
    tenant, protocol = _closed_protocol_with_snapshot(db)
    source_key = next(iter(protocol.todos_snapshot_json["blocks"]))

    zip_path, _ = TenantExportService().export(db, tenant.id, "full")
    try:
        new_tenant, _warnings = TenantImportService().import_zip(db, zip_path, "Snapshot-Import")
    finally:
        zip_path.unlink(missing_ok=True)

    _assert_snapshot_follows_new_rows(db, new_tenant.id, source_key)
