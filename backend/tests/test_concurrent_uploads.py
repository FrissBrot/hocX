"""Independent DB sessions must not scan or store the same concurrent upload twice."""
import asyncio
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.config import settings
from app.models import StoredFile, Tenant
from app.services import file_service as module
from app.services.file_service import FileService
from app.services.upload_lock import acquire_upload_lock, acquire_upload_lock_sync


@pytest.mark.parametrize('method', ['save_document_uploads', 'save_gallery_uploads'])
def test_concurrent_upload_scans_and_stores_once(monkeypatch, tmp_path, method):
    # Two connections need a committed tenant; delete this test-owned tenant in finally.
    with Session(engine) as setup:
        tenant = Tenant(name='Concurrent upload regression')
        setup.add(tenant)
        setup.commit()
        tenant_id = tenant.id
    monkeypatch.setattr(settings, 'storage_root', str(tmp_path))
    monkeypatch.setattr(settings, 'upload_root', str(tmp_path / 'uploads'))
    monkeypatch.setattr(settings, 'thumbnail_root', str(tmp_path / 'thumbnails'))
    content, filename = b'%PDF-1.7\nconcurrent upload', 'file.pdf'
    if method == 'save_gallery_uploads':
        buffer = BytesIO()
        Image.new('RGB', (12, 12), 'blue').save(buffer, format='PNG')
        content, filename = buffer.getvalue(), 'file.png'
    scans = []

    async def scan(contents, **kwargs):
        scans.extend(contents)
        await asyncio.sleep(0.15)  # Give the competing session time to reach its check.
        return ['clean'] * len(contents)
    monkeypatch.setattr(module.scanner, 'scan_many', scan)

    async def run():
        async def upload():
            with Session(engine) as db:
                return await getattr(FileService(), method)(db, tenant_id=tenant_id,
                    files=[(filename, content)], tags=[], created_by=None)
        return await asyncio.wait_for(asyncio.gather(upload(), upload()), timeout=10)

    try:
        results = asyncio.run(run())
        assert len(scans) == 1
        assert sum(len(items) for items, _ in results) == 1
        assert sum('Duplikat' in error for _, errors in results for error in errors) == 1
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(StoredFile).where(StoredFile.tenant_id == tenant_id)) == 1
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()


def test_waiter_yields_and_rollback_releases_lock():
    async def run():
        with Session(engine) as first, Session(engine) as second, Session(engine) as other:
            await acquire_upload_lock(first, 999991)
            waiter = asyncio.create_task(acquire_upload_lock(second, 999991))
            await asyncio.sleep(0.08)
            assert not waiter.done()
            await asyncio.wait_for(acquire_upload_lock(other, 999992), timeout=1)
            first.rollback()
            await asyncio.wait_for(waiter, timeout=1)
            second.rollback()
            # The synchronous import path shares the same namespace and transaction lifetime.
            await acquire_upload_lock(first, 999991)
            def sync_waiter():
                with Session(engine) as db:
                    acquire_upload_lock_sync(db, 999991)
            sync_task = asyncio.create_task(asyncio.to_thread(sync_waiter))
            await asyncio.sleep(0.08)
            assert not sync_task.done()
            first.rollback()
            await asyncio.wait_for(sync_task, timeout=1)
    asyncio.run(run())
