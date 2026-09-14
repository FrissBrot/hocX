"""Tests for AdminUploadPipelineStatusService (the "Datei-Pipeline" admin overview:
scan_status per file across every internal upload source plus abgabebox's quarantine
filesystem) and the GET /api/admin/upload-pipeline-status route. Row builders mirror
test_storage_usage.py's _make_protocol_image/_make_word_import_document/
_make_submission_upload_file/_make_gallery_image so a stored_file lands in the same
category the "Dateien" overview (and this pipeline view) would classify it under."""

from __future__ import annotations

import uuid

from app.api.routes import admin as admin_routes
from app.core.admin_security import CurrentAdmin
from app.models.entities import GalleryImage, ProtocolImage, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile, WordImportDocument
from app.services.admin_upload_pipeline_status_service import AdminUploadPipelineStatusService
from tests.factories import (
    make_list_definition,
    make_list_entry,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)

service = AdminUploadPipelineStatusService()


def _make_protocol_image(db, tenant_id, *, scan_status="clean"):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="lager-foto.png", mime_type="image/png",
        storage_path="uploads/tenant-x/block-x/lager-foto.png", file_size_bytes=1000, scan_status=scan_status,
    )
    db.add(stored_file)
    db.flush()
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, sort_index=0))
    db.flush()
    return stored_file


def _make_word_import_document(db, tenant_id, *, scan_status="pending"):
    template = make_template(db, tenant_id)
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="bericht.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_path="uploads/word-imports/tenant-x/doc.docx", file_size_bytes=2000, scan_status=scan_status,
    )
    db.add(stored_file)
    db.flush()
    db.add(WordImportDocument(
        tenant_id=tenant_id, template_id=template.id, stored_file_id=stored_file.id,
        original_filename="bericht.docx", display_name="bericht.docx", status="eingelesen",
    ))
    db.flush()
    return stored_file


def _make_gallery_image(db, tenant_id, *, scan_status="clean"):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="strand.png", mime_type="image/png",
        storage_path="uploads/tenant-x/gallery/strand.png", file_size_bytes=3000, scan_status=scan_status,
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def _make_submission_upload_file(db, tenant_id, *, scan_status="infected"):
    list_definition = make_list_definition(db, tenant_id)
    entry = make_list_entry(db, list_definition.id)
    assignment = SubmissionAssignment(
        tenant_id=tenant_id, title="Fotos Sommerlager", public_slug="fotos-sola",
        source_type="list", list_definition_id=list_definition.id,
    )
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=None, list_entry_id=entry.id, status="submitted")
    db.add(upload)
    db.flush()
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="beleg.pdf", mime_type="application/pdf",
        storage_path="abgabebox/beleg.pdf", file_size_bytes=4000, scan_status=scan_status,
    )
    db.add(stored_file)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def _admin() -> CurrentAdmin:
    return CurrentAdmin(
        admin_id=1, admin_public_id=uuid.uuid4(), email="admin@example.com", display_name="Test Admin", role="owner"
    )


def test_overview_summary_counts_every_source_and_scan_status(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id, scan_status="clean")
    _make_word_import_document(db, tenant.id, scan_status="pending")
    _make_gallery_image(db, tenant.id, scan_status="clean")
    _make_submission_upload_file(db, tenant.id, scan_status="infected")

    overview = service.get_overview(db)

    by_key = {(entry.source, entry.scan_status): entry.count for entry in overview.summary}
    assert by_key[("protocol_image", "clean")] == 1
    assert by_key[("word_import", "pending")] == 1
    assert by_key[("gallery_upload", "clean")] == 1
    assert by_key[("submission_upload", "infected")] == 1


def test_overview_files_includes_tenant_name_and_origin_tag(db):
    tenant = make_tenant(db, "Sommerlager e.V.")
    _make_gallery_image(db, tenant.id)

    overview = service.get_overview(db)

    item = next(item for item in overview.files.items if item.source == "gallery_upload")
    assert item.tenant_name == "Sommerlager e.V."
    assert item.origin_tag == "Direkt hochgeladen"
    assert item.scan_status == "clean"


def test_overview_is_cross_tenant_by_default_but_filterable_to_one_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    _make_gallery_image(db, tenant_a.id)
    _make_gallery_image(db, tenant_b.id)

    everyone = service.get_overview(db)
    assert everyone.files.total == 2

    only_a = service.get_overview(db, tenant_id=tenant_a.id)
    assert only_a.files.total == 1
    assert only_a.files.items[0].tenant_id == tenant_a.public_id


def test_overview_source_filter_narrows_to_one_origin(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)
    _make_gallery_image(db, tenant.id)

    only_gallery = service.get_overview(db, source="gallery_upload")

    assert only_gallery.files.total == 1
    assert only_gallery.files.items[0].source == "gallery_upload"


def test_overview_scan_status_filter_surfaces_infected_files(db):
    tenant = make_tenant(db)
    _make_gallery_image(db, tenant.id, scan_status="clean")
    _make_submission_upload_file(db, tenant.id, scan_status="infected")

    only_infected = service.get_overview(db, scan_status="infected")

    assert only_infected.files.total == 1
    assert only_infected.files.items[0].scan_status == "infected"


def test_overview_abgabebox_quarantine_reads_live_filesystem_not_db(db, monkeypatch, tmp_path):
    """A file the abgabebox scanner hasn't finished with yet has no StoredFile row at all
    (see abgabebox-backend's upload() route: quarantine write happens before the scan, the
    StoredFile insert only after) - it can only ever show up via the filesystem snapshot,
    never via `files`."""
    from app.core.config import settings

    tenant = make_tenant(db)
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path))
    quarantine_dir = tmp_path / "quarantine" / f"tenant-{tenant.id}" / "assignment-42"
    quarantine_dir.mkdir(parents=True)
    (quarantine_dir / "abc123.pdf").write_bytes(b"x" * 10)

    overview = service.get_overview(db)

    assert overview.files.total == 0
    assert len(overview.abgabebox_quarantine) == 1
    entry = overview.abgabebox_quarantine[0]
    assert entry.tenant_id == tenant.public_id
    assert entry.assignment_id == 42
    assert entry.file_name == "abc123.pdf"
    assert entry.file_size_bytes == 10
    assert entry.age_seconds >= 0


def test_overview_abgabebox_quarantine_omitted_when_source_filter_excludes_it(db, monkeypatch, tmp_path):
    from app.core.config import settings

    tenant = make_tenant(db)
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path))
    quarantine_dir = tmp_path / "quarantine" / f"tenant-{tenant.id}" / "assignment-1"
    quarantine_dir.mkdir(parents=True)
    (quarantine_dir / "x.pdf").write_bytes(b"x")

    overview = service.get_overview(db, source="gallery_upload")

    assert overview.abgabebox_quarantine == []


def test_route_resolves_tenant_public_id_and_delegates_to_service(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)

    result = admin_routes.get_upload_pipeline_status(
        tenant_id=tenant.public_id, source=None, scan_status=None, limit=50, offset=0, db=db, current_admin=_admin(),
    )

    assert result.files.total == 1
