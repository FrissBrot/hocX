"""Produktionsgrenzen, Kontingentreservierung und atomare Import-Fortsetzung."""
import asyncio
import io
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select, text

from app import scanner
from app.api.routes.files import upload_gallery_images
from app.core.config import settings
from app.models import StoredFile
from app.models.entities import GalleryUploadJob
from app.repositories.file_repository import StoredFileRepository
from app.services.file_service import FileService
from app.services import upload_pipeline as pipeline
from app.upload_admission import UploadAdmissionMiddleware
from tests.factories import make_current_user, make_tenant


@pytest.fixture
def storage(monkeypatch, tmp_path):
    for attr, path in [('storage_root', tmp_path), ('upload_root', tmp_path / 'uploads'), ('thumbnail_root', tmp_path / 'thumbnails')]:
        monkeypatch.setattr(settings, attr, str(path))
    async def clean(contents, **kwargs):
        return ['clean'] * len(contents)
    monkeypatch.setattr(scanner, 'scan_many', clean)
    return tmp_path


def png(color):
    out = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(out, format='PNG')
    return out.getvalue()


def queue(db, tenant, files):
    return asyncio.run(upload_gallery_images(
        files=[UploadFile(io.BytesIO(data), filename=name, size=len(data)) for name, data in files],
        tags=None, event_id=None, submission_assignment_id=None, submission_element_ref=None,
        cycle_config_id=None, db=db, user=make_current_user(tenant.id, role='writer')))


def test_zip_and_direct_images_share_100_mib_limit(tmp_path):
    content = png('blue') + b'\0' * (21 * 1024**2)
    path = tmp_path / 'images.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('large.png', content)
    entries = list(pipeline.iter_gallery_zip_entries(path))
    assert len(entries) == 1 and entries[0][0] == 'large.png'
    assert len(entries[0][1]) == len(content)
    assert pipeline.GALLERY_DIRECT_IMAGE_MAX_BYTES == scanner.MAX_SCAN_BYTES == 100 * 1024**2
    assert pipeline.GALLERY_ZIP_MAX_BYTES == 10 * 1024**3


def test_zip_expansion_is_checked_before_queueing(db, storage, monkeypatch):
    tenant = make_tenant(db)
    monkeypatch.setattr(pipeline, 'GALLERY_ZIP_MAX_EXPANDED_BYTES', 10)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('image.png', png('blue'))
    with pytest.raises(HTTPException) as error:
        queue(db, tenant, [('image.zip', out.getvalue())])
    assert error.value.status_code == 413
    assert list((storage / 'uploads' / '_staging' / 'gallery').iterdir()) == []


def test_queued_job_reserves_quota_and_releases_after_import(db, storage):
    tenant = make_tenant(db)
    data = png('blue')
    tenant.storage_quota_bytes = len(data)
    db.commit()
    queued = queue(db, tenant, [('image.png', data)])
    job = db.get(GalleryUploadJob, queued.id)
    assert job.reserved_bytes == len(data)
    assert db.scalar(text('SELECT public.upload_storage_usage(:id)'), {'id': tenant.id}) == len(data)
    with pytest.raises(HTTPException):
        pipeline._enforce_tenant_storage_quota(db, tenant_id=tenant.id, repo=StoredFileRepository(), incoming_bytes=1)
    FileService().process_pending_gallery_upload_jobs(db)
    db.refresh(job)
    assert job.status == 'done' and job.reserved_bytes == 0
    assert len(job.imported_file_ids) == 1
    assert db.scalar(text('SELECT public.upload_storage_usage(:id)'), {'id': tenant.id}) == len(data)


def test_restart_continues_after_committed_batch_without_double_releasing_quota(db, storage, monkeypatch):
    tenant = make_tenant(db)
    first, second = png('blue'), png('red')
    tenant.storage_quota_bytes = len(first) + len(second)
    db.commit()
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('first.png', first)
        archive.writestr('second.png', second)
    queued = queue(db, tenant, [('photos.zip', out.getvalue())])
    job = db.get(GalleryUploadJob, queued.id)
    job.status = 'running'
    db.commit()
    # Simulate death immediately AFTER the file transaction but BEFORE returning its result.
    service = FileService()
    original = service._save_gallery_batch
    async def crash_after_commit(*args, **kwargs):
        await original(*args, **kwargs)
        raise asyncio.CancelledError()
    monkeypatch.setattr(service, '_save_gallery_batch', crash_after_commit)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service._ingest_gallery_batch(db, job, [('first.png', first)], upload_assignment=None, upload_cycle_config=None))
    db.refresh(job)
    assert job.processed_files == 1 and len(job.imported_file_ids) == 1
    assert job.reserved_bytes == len(second)
    monkeypatch.setattr(service, '_save_gallery_batch', original)
    service.process_pending_gallery_upload_jobs(db)
    db.refresh(job)
    assert job.status == 'done' and job.processed_files == 2
    assert len(job.imported_file_ids) == 2 and job.reserved_bytes == 0
    assert db.scalar(select(func.count()).select_from(StoredFile).where(StoredFile.tenant_id == tenant.id)) == 2
    assert all(not (storage / path).exists() for path in job.staged_paths)


def test_admission_rejects_unknown_length_stream_and_closes_parser_files(monkeypatch):
    import starlette.formparsers as parser
    files = []
    original = parser.SpooledTemporaryFile
    def track(*args, **kwargs):
        handle = original(*args, **kwargs)
        files.append(handle)
        return handle
    monkeypatch.setattr(parser, 'SpooledTemporaryFile', track)
    app = FastAPI()
    app.add_middleware(UploadAdmissionMiddleware, path='/upload', max_bytes=2048)
    @app.post('/upload')
    async def upload(file: UploadFile = File(...)):
        return {'bytes': file.size}
    def body():
        yield b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="a.bin"\r\n\r\n'
        yield b'x' * 1024
        yield b'x' * 2048 + b'\r\n--boundary--\r\n'
    async def send_chunks():
        chunks = iter(body())
        messages = []
        async def receive():
            try:
                return {"type": "http.request", "body": next(chunks), "more_body": True}
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            messages.append(message)
        await app({"type": "http", "method": "POST", "path": "/upload", "query_string": b"",
                   "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
                   "server": ("test", 80), "client": ("test", 1), "scheme": "http"}, receive, send)
        assert messages[0]['status'] == 413
    asyncio.run(send_chunks())
    assert files and all(handle.closed for handle in files)
    with TestClient(app) as client:
        assert client.post('/upload', files={'file': ('tiny', b'a')}).status_code == 200


def test_scanner_distinguishes_size_errors_from_malware(monkeypatch, tmp_path):
    import pyclamd
    monkeypatch.setattr(pyclamd.ClamdNetworkSocket, "__init__", lambda *a, **k: None)
    scan = Mock(return_value={'stream': ('ERROR', 'scanner failed')})
    monkeypatch.setattr(pyclamd.ClamdNetworkSocket, 'scan_stream', scan)
    assert scanner.scan_bytes(b'x', host='unused') == 'error'
    scan.return_value = {'stream': ('FOUND', 'Eicar-Signature')}
    assert scanner.scan_bytes(b'x', host='unused') == 'infected'
    scan.side_effect = pyclamd.BufferTooLongError('too large')
    assert scanner.scan_bytes(b'x', host='unused') == 'error'
    path = tmp_path / 'oversize'
    with path.open('wb') as handle:
        handle.truncate(scanner.MAX_SCAN_BYTES + 1)
    scan.reset_mock()
    assert scanner.scan_file(path, host='unused') == 'error'
    scan.assert_not_called()


def test_gallery_parser_adopts_file_without_copy_and_removes_rejected_files(monkeypatch, storage):
    from fastapi import APIRouter
    from app import gallery_upload_route as module
    monkeypatch.setattr(module, 'authorize_gallery_upload', lambda request: None)
    app = FastAPI()
    router = APIRouter(route_class=module.GalleryUploadRoute)
    adopted = []
    @router.post('/api/files/gallery-uploads')
    async def upload(files: list[UploadFile] = File(...)):
        file = files[0]
        inode = file.file.path.stat().st_ino
        async def forbidden_read(*args):
            raise AssertionError('Upload wurde unnötig kopiert')
        file.read = forbidden_read
        target = await pipeline.stage_upload_to_disk(file, target_dir=storage / 'uploads' / '_staging' / 'gallery', max_bytes=10, suffix='.zip')
        adopted.append(target)
        assert target.stat().st_ino == inode
        return {'bytes': target.stat().st_size}
    app.include_router(router)
    with TestClient(app) as client:
        assert client.post('/api/files/gallery-uploads', files={'files': ('small.zip', b'12345')}).json() == {'bytes': 5}
        assert adopted[0].read_bytes() == b'12345'
        assert client.post('/api/files/gallery-uploads', files={'files': ('large.zip', b'x' * 11)}).status_code == 413
    assert not list((storage / 'uploads' / '_multipart').iterdir())


def test_gallery_rejects_unauthenticated_before_parsing(monkeypatch, storage):
    from fastapi import APIRouter
    from app import gallery_upload_route as module
    def deny(request):
        raise HTTPException(401, 'Authentication required')
    monkeypatch.setattr(module, 'authorize_gallery_upload', deny)
    app = FastAPI()
    router = APIRouter(route_class=module.GalleryUploadRoute)
    @router.post('/api/files/gallery-uploads')
    async def upload(files: list[UploadFile] = File(...)):
        raise AssertionError('Unerlaubter Handler-Aufruf')
    app.include_router(router)
    with TestClient(app) as client:
        assert client.post('/api/files/gallery-uploads', files={'files': ('file.zip', b'data')}).status_code == 401
    assert not (storage / 'uploads' / '_multipart').exists()
