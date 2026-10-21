"""Concurrency-Audit CONC-014: Thumbnails auf Abruf begrenzt (wenige gleichzeitige Erzeugungen,
wenige Wartende, sonst 503), atomar geschrieben, und ein Backfill im job-worker für Bilder ohne
Vorschau (vor allem Abgabebox-Uploads)."""

import io
import threading
from pathlib import Path

import pytest
from PIL import Image

from app.models.entities import StoredFile
from app.services import file_service as module
from app.services.file_service import FileService, ThumbnailBusy
from tests.factories import make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "storage-local" / "thumbnails"))
    monkeypatch.setattr(module, "_THUMBNAIL_BACKFILL_FAILED", set())


def _image(db, tenant_id, name, content=None):
    from app.core.config import settings

    path = Path(settings.storage_root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        buffer = io.BytesIO()
        Image.new("RGB", (640, 480), color=(40, 80, 120)).save(buffer, format="PNG")
        content = buffer.getvalue()
    path.write_bytes(content)
    stored_file = StoredFile(tenant_id=tenant_id, original_name=name, mime_type="image/png", storage_path=name, scan_status="clean")
    db.add(stored_file)
    db.flush()
    return stored_file


def test_generation_slots_and_waiting_are_bounded(monkeypatch):
    monkeypatch.setattr(module, "_thumbnail_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(module, "THUMBNAIL_WAIT_SECONDS", 0.05)
    with module._thumbnail_generation_slot():
        # Platz belegt: nach der Wartezeit 503 statt unbegrenzt zu warten
        with pytest.raises(ThumbnailBusy):
            with module._thumbnail_generation_slot():
                pass
        # Zu viele Wartende: sofort 503, ohne einen weiteren Threadpool-Platz zu blockieren
        monkeypatch.setattr(module, "_thumbnail_waiting", module.THUMBNAIL_MAX_WAITING)
        with pytest.raises(ThumbnailBusy):
            with module._thumbnail_generation_slot():
                pass
        monkeypatch.setattr(module, "_thumbnail_waiting", 0)
    with module._thumbnail_generation_slot():
        pass


def test_thumbnail_is_written_atomically(tmp_path):
    target = tmp_path / "thumbs" / "1.jpg"
    module._write_atomic(target, b"jpeg")
    assert target.read_bytes() == b"jpeg"
    assert [path.name for path in target.parent.iterdir()] == ["1.jpg"]  # keine Temp-Reste


def test_busy_thumbnail_route_answers_503_without_error_log(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    @app.get("/__test/thumbnail-busy")
    def busy():
        raise ThumbnailBusy

    try:
        response = TestClient(app).get("/__test/thumbnail-busy")
    finally:
        app.router.routes.pop()
    assert response.status_code == 503
    assert response.json()["code"] == "thumbnail_busy"
    assert response.headers["retry-after"]


def test_backfill_creates_missing_thumbnails_and_skips_undecodable_images(db):
    from app.core.config import settings

    tenant = make_tenant(db)
    good = _image(db, tenant.id, "good.png")
    broken = _image(db, tenant.id, "broken.png", content=b"kein Bild")

    service = FileService()
    created = service.backfill_missing_thumbnails(db, limit=2)
    assert created == 1
    db.refresh(good)
    assert good.thumbnail_path == f"{good.id}.jpg"
    assert (Path(settings.thumbnail_root) / good.thumbnail_path).exists()
    assert broken.id in module._THUMBNAIL_BACKFILL_FAILED

    # Nächster Lauf: weder das fertige noch das kaputte Bild erneut
    calls = []
    original = service.ensure_thumbnail

    def tracking(db_, stored_file, root, *args):
        calls.append(stored_file.id)
        return original(db_, stored_file, root, *args)

    service.ensure_thumbnail = tracking
    service.backfill_missing_thumbnails(db, limit=2)
    assert good.id not in calls and broken.id not in calls


def test_backfill_survives_an_image_that_raises(db, monkeypatch):
    """Security-Review 10b: eine Exception bei einem Bild hält den Backfill nicht dauerhaft an."""
    tenant = make_tenant(db)
    older = _image(db, tenant.id, "older.png")
    newer = _image(db, tenant.id, "newer.png")
    # Session.rollback() verwirft in der Test-Fixture das ganze Setup (äussere Transaktion);
    # im job-worker trifft er nur das eine Bild.
    monkeypatch.setattr(db, "rollback", lambda: None)
    service = FileService()
    original = service.ensure_thumbnail
    errors = []
    monkeypatch.setattr("app.core.error_log.record_system_error", lambda db_, exc, tenant_id=None, **kw: errors.append(tenant_id))

    def flaky(db_, stored_file, root, *args):
        if stored_file.id == newer.id:
            raise OSError("Objektspeicher weg")
        return original(db_, stored_file, root, *args)

    service.ensure_thumbnail = flaky
    assert service.backfill_missing_thumbnails(db, limit=2) == 1
    assert errors == [tenant.id]
    assert newer.id in module._THUMBNAIL_BACKFILL_FAILED
    db.refresh(older)
    assert older.thumbnail_path == f"{older.id}.jpg"


def test_stale_thumbnail_file_of_a_reused_id_is_not_adopted(db):
    """Security-Review 10b: eine alte "<id>.jpg" (z. B. nach DB-Restore) wird neu erzeugt."""
    import os

    from app.core.config import settings

    tenant = make_tenant(db)
    stored_file = _image(db, tenant.id, "fresh.png")
    stale = Path(settings.thumbnail_root) / f"{stored_file.id}.jpg"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"fremdes Bild")
    os.utime(stale, (1_000_000_000, 1_000_000_000))
    path = FileService().ensure_thumbnail(db, stored_file, settings.storage_root)
    assert path.read_bytes() != b"fremdes Bild"
