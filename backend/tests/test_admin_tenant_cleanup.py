"""Tests for TenantCleanupService and the admin 'Mandant aufräumen' routes.

Covers: each checkbox category deletes only what it claims to (protocols cascade their
block-attached todos and clear the word-import queue but leave standalone todos and other
tenants alone; list_entries clears rows but keeps the list_definition; lists_full clears
both and also detaches a submission_assignment RESTRICT-linked to the list, which would
otherwise block the delete; documents sweeps stored_file rows only once nothing references
them anymore, including files orphaned by a protocols run in the same call), that the
confirm_name check and empty-categories check on the route reject bad requests before
touching the DB, and that an unrelated tenant's data survives untouched.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.entities import (
    ListDefinition,
    ListEntry,
    Participant,
    Protocol,
    ProtocolImage,
    ProtocolTodo,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    TodoStatus,
    WordImportDocument,
)
from app.api.routes import admin as admin_routes
from app.core.admin_security import CurrentAdmin
from app.schemas.admin import TenantCleanupRequest
from app.services.tenant_cleanup_service import TenantCleanupService

from tests.factories import (
    make_event,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)

# local row builders - not added to tests/factories.py, same convention as
# test_audit_2026_08_12_high_fixes_H.py ("kept local ... task's scope is limited").


def make_stored_file(db, tenant_id: int, name: str = "file.pdf") -> StoredFile:
    # Relative path (not "/tmp/...") so app.services.file_service._safe_storage_path
    # resolves it under storage_root instead of raising "Invalid file path" - the cleanup
    # service's orphan sweep calls that helper on every candidate row.
    row = StoredFile(tenant_id=tenant_id, original_name=name, storage_path=f"test-cleanup/{name}")
    db.add(row)
    db.flush()
    return row


def make_protocol_image(db, protocol_element_block_id: int, stored_file_id: int) -> ProtocolImage:
    row = ProtocolImage(protocol_element_block_id=protocol_element_block_id, stored_file_id=stored_file_id)
    db.add(row)
    db.flush()
    return row


def make_word_import_document(db, tenant_id: int, template_id: int, stored_file_id: int, status: str = "eingelesen") -> WordImportDocument:
    row = WordImportDocument(
        tenant_id=tenant_id, template_id=template_id, stored_file_id=stored_file_id,
        original_filename="import.docx", display_name="Import", status=status,
    )
    db.add(row)
    db.flush()
    return row


def make_submission_assignment(db, tenant_id: int, list_definition_id: int, public_slug: str) -> SubmissionAssignment:
    row = SubmissionAssignment(
        tenant_id=tenant_id, title="Test Abgabe", public_slug=public_slug,
        source_type="list", list_definition_id=list_definition_id, deadline=date(2026, 1, 1),
    )
    db.add(row)
    db.flush()
    return row


def make_submission_upload(db, assignment_id: int, list_entry_id: int) -> SubmissionUpload:
    row = SubmissionUpload(assignment_id=assignment_id, list_entry_id=list_entry_id, status="submitted")
    db.add(row)
    db.flush()
    return row


def make_submission_upload_file(db, upload_id: int, stored_file_id: int) -> SubmissionUploadFile:
    row = SubmissionUploadFile(upload_id=upload_id, stored_file_id=stored_file_id)
    db.add(row)
    db.flush()
    return row


def make_standalone_todo(db, tenant_id: int, task: str = "Standalone") -> ProtocolTodo:
    open_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open"))
    todo = ProtocolTodo(tenant_id=tenant_id, protocol_element_block_id=None, task=task, todo_status_id=open_status_id)
    db.add(todo)
    db.flush()
    return todo


@pytest.fixture
def service() -> TenantCleanupService:
    return TenantCleanupService()


def exists(db, model, id_: int) -> bool:
    # Not db.get(model, id_): TenantCleanupService.cleanup() commits internally, which
    # expires every object already in this session's identity map (e.g. one a factory
    # handed back earlier in the same test) - db.get() on an expired-but-identity-mapped
    # instance tries to refresh it and raises ObjectDeletedError instead of returning None
    # once the row is actually gone. A fresh SELECT has no such instance to refresh.
    return db.scalar(select(model.id).where(model.id == id_)) is not None


def test_protocols_cascades_block_todo_but_spares_standalone_todo(db, service):
    tenant = make_tenant(db, "Cleanup Tenant")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    make_protocol_todo(db, block.id, tenant_id=None)
    standalone = make_standalone_todo(db, tenant.id)

    counts = service.cleanup(db, tenant.id, ["protocols"])

    assert counts.protocols == 1
    assert db.scalar(select(func.count(Protocol.id)).where(Protocol.tenant_id == tenant.id)) == 0
    assert db.scalar(select(func.count(ProtocolTodo.id)).where(ProtocolTodo.id == standalone.id)) == 1


def test_protocols_clears_word_import_queue(db, service):
    tenant = make_tenant(db, "Cleanup Tenant")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    stored_file = make_stored_file(db, tenant.id)
    make_word_import_document(db, tenant.id, template.id, stored_file.id, status="importiert")
    protocol_id = protocol.id

    service.cleanup(db, tenant.id, ["protocols"])

    assert db.scalar(select(func.count(WordImportDocument.id)).where(WordImportDocument.tenant_id == tenant.id)) == 0
    assert not exists(db, Protocol, protocol_id)


def test_list_entries_keeps_definition(db, service):
    tenant = make_tenant(db, "Cleanup Tenant")
    definition = make_list_definition(db, tenant.id)
    make_list_entry(db, definition.id)
    make_list_entry(db, definition.id, sort_index=1)

    counts = service.cleanup(db, tenant.id, ["list_entries"])

    assert counts.list_entries == 2
    assert exists(db, type(definition), definition.id)


def test_lists_full_detaches_restrict_linked_submission_assignment(db, service):
    tenant = make_tenant(db, "Cleanup Tenant")
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id)
    assignment = make_submission_assignment(db, tenant.id, definition.id, public_slug="abgabe-1")
    # Captured before cleanup() commits: entry is cascade-deleted at the DB level (via
    # list_definition's ON DELETE CASCADE), which the ORM session was never told about
    # directly - touching entry.id afterward would try to reload the now-gone row and raise
    # ObjectDeletedError instead of the plain "not found" this test wants to assert.
    definition_id, entry_id, assignment_id = definition.id, entry.id, assignment.id

    counts = service.cleanup(db, tenant.id, ["lists_full"])

    assert counts.lists_full == 1
    assert not exists(db, ListDefinition, definition_id)
    assert not exists(db, ListEntry, entry_id)
    assert not exists(db, SubmissionAssignment, assignment_id)


def test_events_and_participants_and_todos(db, service):
    tenant = make_tenant(db, "Cleanup Tenant")
    make_event(db, tenant.id)
    make_participant(db, tenant.id)
    make_standalone_todo(db, tenant.id)

    counts = service.cleanup(db, tenant.id, ["events", "participants", "todos"])

    assert (counts.events, counts.participants, counts.todos) == (1, 1, 1)


def test_documents_sweeps_orphaned_files_but_spares_referenced_ones(db, service):
    tenant = make_tenant(db, "Cleanup Tenant")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})

    referenced_file = make_stored_file(db, tenant.id, "referenced.pdf")
    make_protocol_image(db, block.id, referenced_file.id)

    orphan_file = make_stored_file(db, tenant.id, "orphan.pdf")
    protocol_id, referenced_file_id, orphan_file_id = protocol.id, referenced_file.id, orphan_file.id

    counts = service.cleanup(db, tenant.id, ["documents"])

    assert counts.documents == 1
    assert exists(db, StoredFile, referenced_file_id)
    assert not exists(db, StoredFile, orphan_file_id)
    # Protocol itself untouched - "documents" alone doesn't delete protocols.
    assert exists(db, Protocol, protocol_id)


def test_documents_plus_protocols_sweeps_newly_orphaned_protocol_image_file(db, service):
    tenant = make_tenant(db, "Cleanup Tenant")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    stored_file = make_stored_file(db, tenant.id, "will-be-orphaned.pdf")
    make_protocol_image(db, block.id, stored_file.id)
    protocol_id, stored_file_id = protocol.id, stored_file.id

    service.cleanup(db, tenant.id, ["protocols", "documents"])

    assert not exists(db, Protocol, protocol_id)
    assert not exists(db, StoredFile, stored_file_id)


def test_documents_deletes_submission_uploads_and_their_files(db, service):
    tenant = make_tenant(db, "Cleanup Tenant")
    definition = make_list_definition(db, tenant.id)
    entry = make_list_entry(db, definition.id)
    assignment = make_submission_assignment(db, tenant.id, definition.id, public_slug="abgabe-2")
    upload = make_submission_upload(db, assignment.id, entry.id)
    stored_file = make_stored_file(db, tenant.id, "submission.pdf")
    make_submission_upload_file(db, upload.id, stored_file.id)
    assignment_id, upload_id, stored_file_id = assignment.id, upload.id, stored_file.id

    counts = service.cleanup(db, tenant.id, ["documents"])

    assert counts.documents == 2  # 1 submission_upload row + 1 swept stored_file
    assert not exists(db, SubmissionUpload, upload_id)
    assert not exists(db, StoredFile, stored_file_id)
    # Untouched: the assignment/list themselves aren't part of "documents".
    assert exists(db, SubmissionAssignment, assignment_id)


def test_other_tenant_untouched(db, service):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    make_participant(db, tenant_a.id)
    other_participant = make_participant(db, tenant_b.id)

    service.cleanup(db, tenant_a.id, ["participants"])

    assert db.scalar(select(func.count(Participant.id)).where(Participant.tenant_id == tenant_a.id)) == 0
    assert exists(db, Participant, other_participant.id)


def test_cleanup_returns_none_for_unknown_tenant(db, service):
    assert service.cleanup(db, 999_999_999, ["participants"]) is None


def _admin() -> CurrentAdmin:
    return CurrentAdmin(admin_id=1, email="admin@example.com", display_name="Test Admin", role="owner")


def test_route_rejects_name_mismatch(db):
    tenant = make_tenant(db, "Route Tenant")
    make_participant(db, tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        admin_routes.cleanup_tenant(
            tenant.id,
            TenantCleanupRequest(categories=["participants"], confirm_name="wrong name"),
            db=db,
            current_admin=_admin(),
        )
    assert exc_info.value.status_code == 400
    # Nothing deleted.
    assert db.scalar(select(func.count(Participant.id)).where(Participant.tenant_id == tenant.id)) == 1


def test_route_rejects_empty_categories(db):
    tenant = make_tenant(db, "Route Tenant")

    with pytest.raises(HTTPException) as exc_info:
        admin_routes.cleanup_tenant(
            tenant.id,
            TenantCleanupRequest(categories=[], confirm_name=tenant.name),
            db=db,
            current_admin=_admin(),
        )
    assert exc_info.value.status_code == 400


def test_route_success_returns_counts(db):
    tenant = make_tenant(db, "Route Tenant")
    make_participant(db, tenant.id)
    make_event(db, tenant.id)

    result = admin_routes.cleanup_tenant(
        tenant.id,
        TenantCleanupRequest(categories=["participants", "events"], confirm_name=tenant.name),
        db=db,
        current_admin=_admin(),
    )

    assert result.participants == 1
    assert result.events == 1


def test_preview_matches_pre_cleanup_counts(db):
    tenant = make_tenant(db, "Route Tenant")
    make_participant(db, tenant.id)
    make_participant(db, tenant.id, display_name="Second Person")

    preview = admin_routes.preview_tenant_cleanup(tenant.id, db=db)

    assert preview.participants == 2
