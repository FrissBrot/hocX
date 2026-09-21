"""Exact duplicates must never reach the expensive scanner or image decoder."""
import asyncio
import hashlib
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models import StoredFile
from app.services import file_service as module
from app.services.file_service import FileService
from tests.factories import make_tenant

PDF = b'%PDF-1.7\nexact duplicate regression\n'


def existing_file(db, tenant_id, content=PDF, **extra):
    row = StoredFile(tenant_id=tenant_id, original_name='original.pdf',
                     storage_path='unused.pdf', checksum_sha256=hashlib.sha256(content).hexdigest(),
                     scan_status='clean', **extra)
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize('method', ['save_document_uploads', 'save_gallery_uploads'])
def test_existing_duplicate_skips_scanner(db, monkeypatch, tmp_path, method):
    tenant = make_tenant(db)
    existing_file(db, tenant.id)
    monkeypatch.setattr(FileService, 'ensure_storage', lambda self: None)
    scan = AsyncMock(side_effect=AssertionError('duplicate reached ClamAV'))
    monkeypatch.setattr(module.scanner, 'scan_many', scan)
    items, errors = asyncio.run(getattr(FileService(), method)(
        db, tenant_id=tenant.id, files=[('renamed.pdf', PDF)], tags=[], created_by=None))
    assert items == []
    assert len(errors) == 1 and 'Duplikat' in errors[0]
    scan.assert_not_called()


def test_batch_duplicates_and_tenant_isolation(db):
    tenant, other = make_tenant(db), make_tenant(db)
    existing_file(db, other.id)
    files, warnings = FileService()._filter_exact_duplicates(
        db, tenant.id, [('first.pdf', PDF), ('renamed.pdf', PDF), ('other.pdf', PDF + b'changed')])
    assert [name for name, _ in files] == ['first.pdf', 'other.pdf']
    assert len(warnings) == 1 and 'renamed.pdf' in warnings[0]


def test_original_hash_detects_converted_photo(db):
    tenant = make_tenant(db)
    existing_file(db, tenant.id, b'converted JPEG', source_checksum_sha256=hashlib.sha256(b'original HEIC').hexdigest())
    files, warnings = FileService()._filter_exact_duplicates(db, tenant.id, [('photo.heic', b'original HEIC')])
    assert not files and len(warnings) == 1


def test_word_import_duplicate_skips_scanner(db, monkeypatch):
    tenant = make_tenant(db)
    existing_file(db, tenant.id)
    def fail_scan(*args, **kwargs):
        pytest.fail('duplicate reached ClamAV')
    monkeypatch.setattr(module.scanner, 'scan_bytes', fail_scan)
    with pytest.raises(HTTPException, match='Duplikat') as exc:
        FileService().save_word_import_document(db, tenant_id=tenant.id, filename='again.pdf', content=PDF)
    assert exc.value.status_code == 409
