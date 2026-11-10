"""FAR-001 (Feature-Recovery-Audit v1.2): Das Video eines Live Photos ist ein eigener StoredFile,
verknüpft nur über gallery_image.live_video_stored_file_id. War ClamAV beim Upload nicht
erreichbar, blieb der Clip 'pending' und wurde vom Nachscan nie erfasst - das Video war dauerhaft
nicht abrufbar."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app import scanner
from app.api.routes import files as files_routes
from app.core.config import settings
from app.models.entities import GalleryImage, StoredFile
from app.services.file_service import FileService
from tests.factories import make_current_user, make_tenant
from tests.image_fixtures import jpeg


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))


def _stored(db, tenant_id: int, name: str, content: bytes, mime: str, scan_status: str) -> StoredFile:
    key = f"uploads/test/{name}"
    path = Path(settings.storage_root) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type=mime, storage_path=key, scan_status=scan_status,
        file_size_bytes=len(content),
    )
    db.add(stored_file)
    db.flush()
    return stored_file


def _live_photo(db, tenant_id: int, *, photo_status: str = "clean", clip_status: str = "pending"):
    photo = _stored(db, tenant_id, f"foto-{tenant_id}.jpg", jpeg(), "image/jpeg", photo_status)
    clip = _stored(db, tenant_id, f"clip-{tenant_id}.mov", b"\x00\x00\x00\x14ftypqt  clip", "video/quicktime", clip_status)
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=photo.id, live_video_stored_file_id=clip.id))
    db.flush()
    return photo, clip


def _scan_as(monkeypatch, verdicts: dict[str, str]):
    monkeypatch.setattr(scanner, "scan_file", lambda path, **_kw: verdicts[Path(path).suffix])


def test_pending_live_clip_is_part_of_the_rescan(db):
    tenant = make_tenant(db)
    photo, clip = _live_photo(db, tenant.id, photo_status="pending")
    pending = {row.id for row in FileService().stored_file_repository.list_pending_internal_files(db)}
    assert photo.id in pending
    assert clip.id in pending


def test_clean_rescan_makes_the_live_video_downloadable(db, monkeypatch):
    tenant = make_tenant(db)
    photo, clip = _live_photo(db, tenant.id)
    user = make_current_user(tenant.id, role="writer")
    with pytest.raises(HTTPException) as before:
        files_routes.download_stored_file(photo.public_id, part="video", db=db, user=user)
    assert before.value.status_code == 404

    _scan_as(monkeypatch, {".mov": "clean"})
    result = FileService().rescan_pending_internal_files(db)

    assert result["clean"] == 1
    db.refresh(clip)
    assert clip.scan_status == "clean"
    response = files_routes.download_stored_file(photo.public_id, part="video", db=db, user=user)
    assert response.status_code == 200


def test_infected_live_clip_stays_blocked(db, monkeypatch):
    tenant = make_tenant(db)
    photo, clip = _live_photo(db, tenant.id)
    _scan_as(monkeypatch, {".mov": "infected"})

    result = FileService().rescan_pending_internal_files(db)

    assert result["infected"] == 1
    db.refresh(clip)
    assert clip.scan_status == "infected"
    user = make_current_user(tenant.id, role="writer")
    with pytest.raises(HTTPException) as blocked:
        files_routes.download_stored_file(photo.public_id, part="video", db=db, user=user)
    assert blocked.value.status_code == 404
    # Das Foto selbst bleibt abrufbar.
    assert files_routes.download_stored_file(photo.public_id, part="image", db=db, user=user).status_code == 200


def test_photo_without_clip_is_unchanged(db, monkeypatch):
    tenant = make_tenant(db)
    photo = _stored(db, tenant.id, "ohne-clip.jpg", jpeg(), "image/jpeg", "pending")
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=photo.id))
    db.flush()
    _scan_as(monkeypatch, {".jpg": "clean"})

    result = FileService().rescan_pending_internal_files(db)

    assert result == {"scanned": 1, "clean": 1, "infected": 0, "still_pending": 0}
