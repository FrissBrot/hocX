"""Nebenläufigkeit: Foto löschen, während capture_date_file_sync das Aufnahmedatum in die Datei schreibt.

Der Job sperrt die Zeile, legt die Datei mit dem korrigierten Datum als NEUES Objekt ab, markiert
das alte zum Löschen und trägt den neuen Schlüssel ein. Löscht jemand das Foto in dieser Zeit
(Mehrfachauswahl «Löschen», «Nur beste behalten»), hat die Lösch-Anfrage die Zeile schon vorher
gelesen: sie wartet auf die Sperre, löscht danach die Zeile und den ALTEN Schlüssel. Das neu
geschriebene Bild blieb als aktives Objekt im Speicher - ein gelöschtes Foto, das niemand mehr
sieht und keine Bereinigung findet.
Erwartet: nach dem Löschen ist kein Objekt der Datei mehr aktiv.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import engine
from app.core.storage import MAIN, get_object_store
from app.models import Tenant
from app.models.entities import AppUser, GalleryImage, StoredFile
from app.services import capture_date_file_sync
from app.services.file_service import FileService
from tests.factories import make_app_user, make_tenant
from tests.image_fixtures import jpeg

ORIGINAL = datetime(2019, 3, 4, 10, 30, 0)


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _wait_until_blocked(timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            if probe.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted")):
                return True
            probe.rollback()
            time.sleep(0.05)
    return False


def test_deleting_a_photo_while_the_job_rewrites_it_leaves_no_active_object():
    content = jpeg(taken_at=ORIGINAL)
    with Session(engine) as setup:
        tenant = make_tenant(setup, "Aufnahmedatum löschen parallel")
        app_user = make_app_user(setup, email=f"{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id, role_code="writer")
        key = f"uploads/tenant-{tenant.id}/gallery/{uuid.uuid4().hex}.jpeg"
        get_object_store().put_bytes(setup, MAIN, key, content, content_type="image/jpeg")
        photo = StoredFile(
            tenant_id=tenant.id, original_name="foto.jpg", mime_type="image/jpeg", storage_path=key,
            file_size_bytes=len(content), checksum_sha256=hashlib.sha256(content).hexdigest(),
            exif_taken_at=ORIGINAL.replace(tzinfo=UTC), metadata_scanned_at=datetime.now(UTC),
            capture_corrected_at=datetime(2021, 6, 5, 14, 15, tzinfo=UTC), capture_corrected_has_time=True,
            capture_file_state="pending",
        )
        setup.add(photo)
        setup.flush()
        setup.add(GalleryImage(tenant_id=tenant.id, stored_file_id=photo.id))
        setup.commit()
        tenant_id, user_id, photo_id, public_id = tenant.id, app_user.id, photo.id, photo.public_id

    def delete_photo():
        with Session(engine) as db:
            try:
                deleted, errors = FileService().delete_gallery_images(db, tenant_id, [public_id])
                db.commit()
                return deleted, errors
            except Exception as exc:  # Befund festhalten
                db.rollback()
                return type(exc).__name__

    pool = ThreadPoolExecutor(1)
    job = Session(engine)
    try:
        # Job mitten im Lauf: Zeile gesperrt, neues Objekt geschrieben, Commit noch nicht durch.
        claimed = capture_date_file_sync._claim_next(job)
        assert claimed is not None and claimed.id == photo_id
        assert capture_date_file_sync._sync_one(job, claimed) == "written"
        written_key = claimed.storage_path
        assert written_key != key
        future = pool.submit(delete_photo)
        blocked = _wait_until_blocked()
        job.commit()
        result = future.result(timeout=30)
    finally:
        job.rollback()
        job.close()
        pool.shutdown(wait=True)

    try:
        assert blocked, "Löschen wartet nicht auf den Job"
        assert result == ([public_id], []), f"Löschen scheitert: {result}"
        with Session(engine) as check:
            active = check.scalars(
                text("SELECT key FROM storage_object WHERE namespace = 'main' AND key IN (:old, :new) AND status <> 'deleted'"),
                {"old": key, "new": written_key},
            ).all()
            assert check.get(StoredFile, photo_id) is None
        assert active == [], f"gelöschtes Foto noch im Speicher: {active}"
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(text("DELETE FROM storage_object WHERE namespace = 'main' AND key LIKE :prefix"), {"prefix": f"uploads/tenant-{tenant_id}/%"})
            cleanup.execute(delete(GalleryImage).where(GalleryImage.tenant_id == tenant_id))
            cleanup.execute(delete(StoredFile).where(StoredFile.tenant_id == tenant_id))
            cleanup.execute(delete(AppUser).where(AppUser.id == user_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
