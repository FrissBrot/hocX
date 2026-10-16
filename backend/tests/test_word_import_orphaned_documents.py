"""Audit MAIN-BE-014: Wort-Import-Dokumente ohne Protokoll bleiben nicht dauerhaft
"importiert" hängen."""
from datetime import UTC, datetime, timedelta

import pytest

from app.models.entities import StoredFile, WordImportDocument
from app.services.word_import_queue_service import WordImportQueueService
from tests.factories import make_template, make_tenant


def _document(db, *, imported_at=None, updated_at=None):
    tenant = make_tenant(db, "Wort-Import")
    template = make_template(db, tenant.id)
    stored_file = StoredFile(tenant_id=tenant.id, original_name="a.docx", storage_path="word-import-test/a.docx")
    db.add(stored_file)
    db.flush()
    document = WordImportDocument(
        tenant_id=tenant.id, template_id=template.id, stored_file_id=stored_file.id,
        original_filename="a.docx", display_name="A", status="importiert", protocol_id=None, imported_at=imported_at,
    )
    db.add(document)
    db.flush()
    if updated_at is not None:
        document.updated_at = updated_at
        db.flush()
    return tenant, document


def test_document_of_deleted_protocol_is_released_and_deletable(db):
    tenant, document = _document(db, imported_at=datetime.now(UTC) - timedelta(days=1))
    service = WordImportQueueService()

    assert service.release_orphaned_imports(db, tenant_id=tenant.id) == 1
    db.refresh(document)
    assert document.status == "eingelesen"
    assert service.delete_document(db, tenant_id=tenant.id, document_id=document.id) is True


def test_abandoned_claim_is_released(db):
    tenant, document = _document(db, updated_at=datetime.now(UTC) - timedelta(hours=2))

    assert WordImportQueueService().release_orphaned_imports(db, tenant_id=tenant.id) == 1
    db.refresh(document)
    assert document.status == "eingelesen"


def test_fresh_claim_is_left_alone(db):
    tenant, document = _document(db, updated_at=datetime.now(UTC))
    service = WordImportQueueService()

    assert service.release_orphaned_imports(db, tenant_id=tenant.id) == 0
    with pytest.raises(ValueError):
        service.delete_document(db, tenant_id=tenant.id, document_id=document.id)
