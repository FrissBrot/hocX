"""Tests for the "Dateien" overview page's backend: StoredFileRepository.list_tenant_files
(UNION ALL across protocol_image / word_import / submission_upload) and FileService.
list_tenant_files (content_url/ref_href derivation on top). Route-level require_writer
gating is tested by calling the route function directly as a plain callable, same
convention as tests/test_protocol_element_list_snapshot_routes.py.
"""
from datetime import date

import pytest
from fastapi import HTTPException

from app.api.routes import files as files_routes
from app.models.entities import StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile, WordImportDocument
from app.services.file_service import FileService
from tests.factories import (
    make_current_user,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)

service = FileService()


def _make_protocol_image(db, tenant_id, *, mime_type="image/png", scan_status="clean"):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, protocol_number="7/2026", protocol_date=date(2026, 3, 4))
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="lager-foto.png", mime_type=mime_type,
        storage_path="uploads/tenant-x/block-x/lager-foto.png", scan_status=scan_status,
    )
    db.add(stored_file)
    db.flush()
    from app.models.entities import ProtocolImage
    image = ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, sort_index=0)
    db.add(image)
    db.flush()
    return protocol, stored_file


def _make_word_import_document(db, tenant_id, *, display_name="1. Hock vom 14.10.2026.docx"):
    template = make_template(db, tenant_id)
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=display_name,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_path="uploads/word-imports/tenant-x/doc.docx",
    )
    db.add(stored_file)
    db.flush()
    document = WordImportDocument(
        tenant_id=tenant_id, template_id=template.id, stored_file_id=stored_file.id,
        original_filename=display_name, display_name=display_name, status="eingelesen",
    )
    db.add(document)
    db.flush()
    return document, stored_file


def _make_submission_upload_file(db, tenant_id, *, filename="beleg.pdf", delete_comment=None):
    assignment = SubmissionAssignment(
        tenant_id=tenant_id, title="Fotos Sommerlager", public_slug="fotos-sola",
        source_type="events", tag_filter="lager",
    )
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=None, list_entry_id=None, status="submitted")
    # SubmissionUpload requires exactly one of event_id/list_entry_id per its CHECK constraint;
    # tests here only exercise the file-listing join, not the assignment/upload domain logic,
    # so a minimal list-backed assignment is used to satisfy that constraint cheaply.
    from tests.factories import make_list_definition, make_list_entry
    list_definition = make_list_definition(db, tenant_id)
    entry = make_list_entry(db, list_definition.id)
    assignment.source_type = "list"
    assignment.list_definition_id = list_definition.id
    assignment.tag_filter = None
    upload.list_entry_id = entry.id
    db.add(upload)
    db.flush()
    stored_file = StoredFile(tenant_id=tenant_id, original_name=filename, mime_type="application/pdf", storage_path=f"abgabebox/{filename}")
    db.add(stored_file)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id, delete_comment=delete_comment))
    db.flush()
    return assignment, upload, stored_file


def test_list_tenant_files_includes_protocol_image_with_context(db):
    tenant = make_tenant(db)
    protocol, stored_file = _make_protocol_image(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    item = items[0]
    assert item.source == "protocol_image"
    assert item.is_image is True
    assert item.ref_label == "7/2026"
    assert item.ref_href == f"/protocols/{protocol.id}"
    assert item.content_url == f"/api/stored-files/{stored_file.id}/content"


def test_list_tenant_files_includes_word_import_document(db):
    tenant = make_tenant(db)
    document, stored_file = _make_word_import_document(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    item = items[0]
    assert item.source == "word_import"
    assert item.is_image is False
    assert item.ref_label == document.display_name
    assert item.ref_href is None
    assert item.content_url == f"/api/stored-files/{stored_file.id}/content"
    # .docx/.pdf are never images - no thumbnail to load, the grid shows a type icon instead.
    assert item.thumbnail_url is None


def test_list_tenant_files_sets_thumbnail_url_for_protocol_images(db):
    tenant = make_tenant(db)
    _, stored_file = _make_protocol_image(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert items[0].thumbnail_url == f"/api/stored-files/{stored_file.id}/thumbnail"


def test_list_tenant_files_sets_thumbnail_url_for_image_submission_uploads(db):
    tenant = make_tenant(db)
    _, upload, stored_file = _make_submission_upload_file(db, tenant.id, filename="foto.png")
    stored_file.mime_type = "image/png"
    db.flush()

    items = service.list_tenant_files(db, tenant.id)

    assert items[0].is_image is True
    assert items[0].thumbnail_url == f"/api/submission-uploads/{upload.id}/files/{stored_file.id}/thumbnail"


def test_list_tenant_files_includes_submission_upload_with_correct_content_url(db):
    tenant = make_tenant(db)
    assignment, upload, stored_file = _make_submission_upload_file(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    item = items[0]
    assert item.source == "submission_upload"
    assert item.ref_label == "Fotos Sommerlager"
    assert item.ref_href == f"/submission-assignments/{assignment.id}"
    assert item.content_url == f"/api/submission-uploads/{upload.id}/files/{stored_file.id}/content"


def test_list_tenant_files_excludes_other_tenant_files(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    _make_protocol_image(db, tenant_a.id)
    _make_protocol_image(db, tenant_b.id)

    items = service.list_tenant_files(db, tenant_a.id)

    assert len(items) == 1


def test_list_tenant_files_only_images_filters_out_documents(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)
    _make_word_import_document(db, tenant.id)

    all_items = service.list_tenant_files(db, tenant.id)
    image_items = service.list_tenant_files(db, tenant.id, only_images=True)

    assert len(all_items) == 2
    assert len(image_items) == 1
    assert image_items[0].is_image is True


def test_list_tenant_files_source_filter(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)
    _make_submission_upload_file(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id, source="submission_upload")

    assert len(items) == 1
    assert items[0].source == "submission_upload"


def test_list_tenant_files_search_matches_original_name_case_insensitively(db):
    tenant = make_tenant(db)
    _make_word_import_document(db, tenant.id, display_name="Jahresbericht 2026.docx")

    hits = service.list_tenant_files(db, tenant.id, search="jahresbericht")
    misses = service.list_tenant_files(db, tenant.id, search="protokoll")

    assert len(hits) == 1
    assert len(misses) == 0


def test_list_tenant_files_excludes_infected_files(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id, scan_status="infected")

    items = service.list_tenant_files(db, tenant.id)

    assert items == []


def test_list_tenant_files_excludes_soft_deleted_submission_upload_files(db):
    tenant = make_tenant(db)
    _make_submission_upload_file(db, tenant.id, delete_comment="Falsche Datei hochgeladen")

    items = service.list_tenant_files(db, tenant.id)

    assert items == []


def test_list_files_route_requires_writer_role(db):
    tenant = make_tenant(db)
    reader = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.list_files(
            skip=0, limit=60, source=None, only_images=False, search=None,
            sort_by="created_at", sort_dir="desc", db=db, user=reader,
        )
    assert exc_info.value.status_code == 403


def test_list_files_route_returns_items_for_writer_role(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")

    result = files_routes.list_files(
        skip=0, limit=60, source=None, only_images=False, search=None,
        sort_by="created_at", sort_dir="desc", db=db, user=writer,
    )

    assert len(result) == 1
    assert result[0].source == "protocol_image"
