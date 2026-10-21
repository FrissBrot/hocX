"""Independent DB sessions must not scan or store the same concurrent upload twice."""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.config import settings
from app.models import StoredFile, Tenant
from app.services import file_service as module
from app.services.file_service import FileService
from app.services.upload_lock import UploadLockBusy, acquire_upload_lock_sync


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

    # Wie in Produktion: jeder Upload in einem eigenen Worker-Thread mit eigenem Event-Loop
    # (core/offload.py) - der Upload-Lock wartet dort blockierend.
    def upload():
        async def run():
            with Session(engine) as db:
                return await getattr(FileService(), method)(db, tenant_id=tenant_id,
                    files=[(filename, content)], tags=[], created_by=None)
        return asyncio.run(run())

    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(upload), pool.submit(upload)]
            results = [future.result(timeout=10) for future in futures]
        assert len(scans) == 1
        assert sum(len(items) for items, _ in results) == 1
        assert sum('Duplikat' in error for _, errors in results for error in errors) == 1
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(StoredFile).where(StoredFile.tenant_id == tenant_id)) == 1
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()


def test_waiter_blocks_until_release_and_times_out():
    with Session(engine) as first, Session(engine) as other:
        acquire_upload_lock_sync(first, 999991)
        # Anderer Mandant: sofort frei.
        acquire_upload_lock_sync(other, 999992)
        other.rollback()

        def waiter(timeout_seconds):
            with Session(engine) as db:
                acquire_upload_lock_sync(db, 999991, timeout_seconds=timeout_seconds)
                db.rollback()
                return True

        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(waiter, 10)
            time.sleep(0.3)
            assert not pending.done()
            first.rollback()
            assert pending.result(timeout=5) is True

        # Belegt und Zeit abgelaufen: UploadLockBusy (Route antwortet 503 mit Retry-After).
        acquire_upload_lock_sync(first, 999991)
        with ThreadPoolExecutor(1) as pool:
            started = time.monotonic()
            with pytest.raises(UploadLockBusy):
                pool.submit(waiter, 1).result(timeout=10)
            assert time.monotonic() - started < 5
        first.rollback()


def test_lock_timeout_applies_only_to_the_wait():
    with Session(engine) as db:
        before = db.scalar(text("SELECT current_setting('lock_timeout')"))
        acquire_upload_lock_sync(db, 999993, timeout_seconds=2)
        assert db.scalar(text("SELECT current_setting('lock_timeout')")) == before
        db.rollback()
