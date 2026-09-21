"""Public duplicates look successful and consume neither quota nor scan work."""
import asyncio
import hashlib
import io
from contextlib import nullcontext
from unittest.mock import AsyncMock

from starlette.requests import Request
from starlette.datastructures import UploadFile

from app.routes import public

PDF = b'%PDF-1.7\nexisting\n'
NEW = b'%PDF-1.7\nnew\n'


def setup_upload(monkeypatch):
    monkeypatch.setattr(public, '_get_tenant_or_404', lambda *a: {'id': 1})
    monkeypatch.setattr(public, '_get_assignment_or_404', lambda *a: {
        'id': 1, 'title': 'Test', 'max_files_per_element': 1,
        'allowed_file_types': ['pdf'], 'max_file_size_mb': 20})
    monkeypatch.setattr(public.element_resolver, 'resolve_single_element', lambda *a: {
        'event_id': 1, 'list_entry_id': None, 'label': 'Test'})
    monkeypatch.setattr(public, 'verify_captcha_session_token', lambda *a, **k: True)
    monkeypatch.setattr(public.repository, 'insert_upload_log', lambda *a, **k: None)
    monkeypatch.setattr(public.repository, 'list_checksums_for_element', lambda *a, **k: {hashlib.sha256(PDF).hexdigest()})
    monkeypatch.setattr(public, 'tenant_upload_lock', lambda *a: nullcontext())
    monkeypatch.setattr(public, 'tenant_storage_bytes', lambda *a: 0)
    monkeypatch.setattr(public.repository, 'list_tenant_image_hashes', lambda *a, **k: [])


def upload(contents):
    return asyncio.run(public.upload(
        Request({'type': 'http', 'headers': [], 'client': ('127.0.0.1', 1)}),
        'token', 'assignment', 'event-1', captcha_session_token='token', db=object(),
        files=[UploadFile(io.BytesIO(data), filename=f'{i}.pdf') for i, data in enumerate(contents)]))


def test_all_duplicates_succeed_without_scan_or_quota(monkeypatch):
    setup_upload(monkeypatch)
    def forbidden(*a, **k):
        raise AssertionError('duplicate reached expensive processing or quota')
    monkeypatch.setattr(public.repository, 'count_files_by_element', forbidden)
    monkeypatch.setattr(public, '_compute_perceptual_hash', forbidden)
    scan = AsyncMock(side_effect=forbidden)
    monkeypatch.setattr(public.scanner, 'scan_many', scan)
    result = upload([PDF, PDF])
    assert result.ok and result.files_received == 2
    assert result.image_duplicate_warnings == []
    scan.assert_not_called()


def test_mixed_batch_only_scans_and_stores_new_file(monkeypatch):
    setup_upload(monkeypatch)
    monkeypatch.setattr(public.repository, 'count_files_by_element', lambda *a, **k: {})
    monkeypatch.setattr(public, 'save_to_quarantine', lambda content, **k: ('quarantine/test.pdf', hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(public, 'move_from_quarantine', lambda *a: 'test.pdf')
    saved = []
    monkeypatch.setattr(public.repository, 'insert_full_upload', lambda *a, **k: saved.extend(k['files']))
    scan = AsyncMock(return_value=['clean'])
    monkeypatch.setattr(public.scanner, 'scan_many', scan)
    result = upload([PDF, NEW, NEW])
    assert result.ok and result.files_received == 3
    assert not result.image_duplicate_warnings
    assert scan.call_args.args[0] == [NEW]
    assert len(saved) == 1


def test_concurrent_duplicates_are_silently_accepted_but_scanned_once(monkeypatch):
    setup_upload(monkeypatch)
    committed = set()
    scans = []
    monkeypatch.setattr(public.repository, 'list_checksums_for_element', lambda *a, **k: set(committed))
    monkeypatch.setattr(public.repository, 'count_files_by_element', lambda *a, **k: {(1, None): len(committed)})
    monkeypatch.setattr(public, 'save_to_quarantine', lambda content, **k: ('quarantine/test.pdf', hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(public, 'move_from_quarantine', lambda *a: 'test.pdf')
    monkeypatch.setattr(public.repository, 'insert_full_upload', lambda *a, **k: committed.update(f['checksum_sha256'] for f in k['files']))

    async def scan(contents, **kwargs):
        scans.extend(contents)
        await asyncio.sleep(0.15)
        return ['clean'] * len(contents)
    monkeypatch.setattr(public.scanner, 'scan_many', scan)

    async def run():
        def request():
            return public.upload(
                Request({'type': 'http', 'headers': [], 'client': ('127.0.0.1', 1)}),
                'token', 'assignment', 'event-1', captcha_session_token='token', db=object(),
                files=[UploadFile(io.BytesIO(NEW), filename='new.pdf')])
        return await asyncio.wait_for(asyncio.gather(request(), request()), timeout=10)
    results = asyncio.run(run())
    assert len(scans) == 1 and len(committed) == 1
    assert all(result.ok and result.files_received == 1 and not result.image_duplicate_warnings for result in results)


def test_cancelled_upload_releases_lock():
    from app.db import serialized_upload

    async def run():
        entered = asyncio.Event()
        async def holder():
            async with serialized_upload(999993):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(holder())
        await entered.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        async def retry():
            async with serialized_upload(999993):
                pass
        await asyncio.wait_for(retry(), timeout=1)
    asyncio.run(run())
