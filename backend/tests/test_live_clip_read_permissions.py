"""Live-Photo-Clips (video/mp4 neben einem Galerie-Foto) gehören zum Foto: lesen mit photos.read,
nicht mit files.read (Nachtlauf 2026-11-22, dateien-fotos/rechte). Die Fotos-Kachel spielt den Clip
über /api/stored-files/{clip}/content ab; die Leseprüfung kannte nur image/* als Foto."""
from __future__ import annotations

import dataclasses

import pytest
from fastapi import HTTPException

from app.models.entities import GalleryImage, StoredFile
from app.services.access_service import AccessService
from tests.factories import make_current_user, make_tenant


def _photo_with_clip(db, tenant_id: int) -> tuple[StoredFile, StoredFile]:
    photo = StoredFile(tenant_id=tenant_id, original_name="IMG_0001.HEIC", mime_type="image/jpeg", storage_path="uploads/live/img.jpg", scan_status="clean")
    clip = StoredFile(tenant_id=tenant_id, original_name="IMG_0001.MOV", mime_type="video/mp4", storage_path="uploads/live/img.mp4", scan_status="clean")
    db.add_all([photo, clip])
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=photo.id, live_video_stored_file_id=clip.id))
    db.flush()
    return photo, clip


def test_live_clip_follows_the_photo_permissions(db):
    tenant = make_tenant(db)
    base = make_current_user(tenant.id, role="writer")
    photos_only = dataclasses.replace(base, permissions=frozenset({"meetings.read", "photos.read"}))
    files_only = dataclasses.replace(base, permissions=frozenset({"meetings.read", "files.read"}))
    photo, clip = _photo_with_clip(db, tenant.id)
    access = AccessService()

    # Wer das Foto sehen darf, darf auch dessen Clip abspielen
    access.ensure_can_read_stored_file(db, photos_only, photo.id)
    access.ensure_can_read_stored_file(db, photos_only, clip.id)

    # Wer nur die Ablage (Dokumente) lesen darf, sieht weder Foto noch Clip
    with pytest.raises(HTTPException):
        access.ensure_can_read_stored_file(db, files_only, photo.id)
    with pytest.raises(HTTPException):
        access.ensure_can_read_stored_file(db, files_only, clip.id)
