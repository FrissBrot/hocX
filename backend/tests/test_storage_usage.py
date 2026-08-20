"""Tests for StorageService (per-tenant disk-usage breakdown + quota) and the tenant-scoped
/api/storage/usage route plus the admin storage endpoints. Row builders mirror
test_files_overview.py's _make_protocol_image/_make_word_import_document/
_make_submission_upload_file so a stored_file lands in the same category the "Dateien"
overview would classify it under.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.api.routes import admin as admin_routes
from app.api.routes import storage as storage_routes
from app.core.admin_security import CurrentAdmin
from app.models.entities import (
    ProtocolExportCache,
    ProtocolImage,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    WordImportDocument,
)
from app.schemas.admin import AdminTenantStorageQuotaUpdate
from app.services.storage_service import StorageService
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

service = StorageService()


def _make_protocol_image(db, tenant_id, *, size=1000, protocol_number="7/2026"):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, protocol_number=protocol_number, protocol_date=date(2026, 3, 4))
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="lager-foto.png", mime_type="image/png",
        storage_path="uploads/tenant-x/block-x/lager-foto.png", file_size_bytes=size,
    )
    db.add(stored_file)
    db.flush()
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, sort_index=0))
    db.flush()
    return protocol, stored_file


def _make_word_import_document(db, tenant_id, *, size=2000):
    template = make_template(db, tenant_id)
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="bericht.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_path="uploads/word-imports/tenant-x/doc.docx", file_size_bytes=size,
    )
    db.add(stored_file)
    db.flush()
    db.add(WordImportDocument(
        tenant_id=tenant_id, template_id=template.id, stored_file_id=stored_file.id,
        original_filename="bericht.docx", display_name="bericht.docx", status="eingelesen",
    ))
    db.flush()
    return stored_file


def _make_submission_upload_file(db, tenant_id, *, size=3000):
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
        storage_path="abgabebox/beleg.pdf", file_size_bytes=size,
    )
    db.add(stored_file)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def _make_export(db, tenant_id, protocol, *, size=4000):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="protokoll.pdf", mime_type="application/pdf",
        storage_path="exports/protokoll.pdf", file_size_bytes=size,
    )
    db.add(stored_file)
    db.flush()
    db.add(ProtocolExportCache(protocol_id=protocol.id, export_format="pdf", generated_file_id=stored_file.id))
    db.flush()
    return stored_file


def _make_orphan(db, tenant_id, *, size=5000):
    """A stored_file with no association at all - e.g. a tenant-import/-clone artifact or an
    orphaned row (see project memory: orphaned word-import stored_file rows found on tenant 3).
    Should land entirely in "other"."""
    stored_file = StoredFile(tenant_id=tenant_id, original_name="misc.bin", storage_path="misc/misc.bin", file_size_bytes=size)
    db.add(stored_file)
    db.flush()
    return stored_file


def test_breakdown_categorizes_each_source_correctly(db):
    tenant = make_tenant(db)
    _, protocol_stored = _make_protocol_image(db, tenant.id, size=1000)
    _make_word_import_document(db, tenant.id, size=2000)
    _make_submission_upload_file(db, tenant.id, size=3000)
    protocol, _ = _make_protocol_image(db, tenant.id, size=0, protocol_number="8/2026")
    _make_export(db, tenant.id, protocol, size=4000)
    _make_orphan(db, tenant.id, size=5000)

    result = service.breakdown_for_tenant(db, tenant.id)
    by_key = {c.key: c.bytes for c in result.categories}

    assert by_key["protocol_image"] == 1000
    assert by_key["word_import"] == 2000
    assert by_key["submission_upload"] == 3000
    assert by_key["export"] == 4000
    assert by_key["other"] == 5000
    assert result.total_bytes == 1000 + 2000 + 3000 + 4000 + 5000
    assert result.quota_bytes is None


def test_breakdown_excludes_other_tenants(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    _make_protocol_image(db, tenant_a.id, size=1000)
    _make_protocol_image(db, tenant_b.id, size=9999)

    result = service.breakdown_for_tenant(db, tenant_a.id)

    assert result.total_bytes == 1000


def test_total_bytes_by_tenant_covers_multiple_tenants_in_one_query(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    _make_protocol_image(db, tenant_a.id, size=1000)
    _make_word_import_document(db, tenant_b.id, size=500)

    totals = service.total_bytes_by_tenant(db)

    assert totals[tenant_a.id] == 1000
    assert totals[tenant_b.id] == 500


def test_set_quota_persists_and_clears(db):
    tenant = make_tenant(db)

    updated = service.set_quota(db, tenant.id, 1024 * 1024)
    assert updated.storage_quota_bytes == 1024 * 1024
    assert service.breakdown_for_tenant(db, tenant.id).quota_bytes == 1024 * 1024

    cleared = service.set_quota(db, tenant.id, None)
    assert cleared.storage_quota_bytes is None


def test_set_quota_returns_none_for_unknown_tenant(db):
    assert service.set_quota(db, 999999, 1024) is None


def test_storage_usage_route_requires_admin_role(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        storage_routes.get_storage_usage(db=db, user=writer)
    assert exc_info.value.status_code == 403


def test_storage_usage_route_returns_breakdown_for_admin(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id, size=1234)
    admin = make_current_user(tenant.id, role="admin")

    result = storage_routes.get_storage_usage(db=db, user=admin)

    assert result.total_bytes == 1234


def _admin() -> CurrentAdmin:
    return CurrentAdmin(admin_id=1, email="admin@example.com", display_name="Test Admin", role="owner")


def test_admin_list_tenants_includes_storage_used_bytes(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id, size=777)

    page = admin_routes.list_tenants(limit=None, offset=0, q=None, db=db)

    row = next(t for t in page.items if t.id == tenant.id)
    assert row.storage_used_bytes == 777
    assert row.storage_quota_bytes is None


def test_admin_get_tenant_storage_returns_breakdown(db):
    tenant = make_tenant(db)
    _make_word_import_document(db, tenant.id, size=42)

    result = admin_routes.get_tenant_storage(tenant.id, db=db)

    by_key = {c.key: c.bytes for c in result.categories}
    assert by_key["word_import"] == 42


def test_admin_get_tenant_storage_404s_for_unknown_tenant(db):
    with pytest.raises(HTTPException) as exc_info:
        admin_routes.get_tenant_storage(999999, db=db)
    assert exc_info.value.status_code == 404


def test_admin_update_tenant_storage_quota_sets_bytes_from_mb(db):
    tenant = make_tenant(db)

    result = admin_routes.update_tenant_storage_quota(
        tenant.id, AdminTenantStorageQuotaUpdate(quota_mb=10), db=db, current_admin=_admin(),
    )

    assert result.storage_quota_bytes == 10 * 1024 * 1024


def test_admin_update_tenant_storage_quota_clears_with_none(db):
    tenant = make_tenant(db)
    admin_routes.update_tenant_storage_quota(tenant.id, AdminTenantStorageQuotaUpdate(quota_mb=10), db=db, current_admin=_admin())

    result = admin_routes.update_tenant_storage_quota(tenant.id, AdminTenantStorageQuotaUpdate(quota_mb=None), db=db, current_admin=_admin())

    assert result.storage_quota_bytes is None


def test_admin_update_tenant_storage_quota_404s_for_unknown_tenant(db):
    with pytest.raises(HTTPException) as exc_info:
        admin_routes.update_tenant_storage_quota(999999, AdminTenantStorageQuotaUpdate(quota_mb=10), db=db, current_admin=_admin())
    assert exc_info.value.status_code == 404
