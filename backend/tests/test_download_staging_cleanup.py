"""Nachtlauf 2026-11-25 (dateien-fotos/fehlerbehandlung): temporäre Download-Kopien unter
``_staging/download`` (gefilterte Fotos öffentlicher Links, Live-Photo-ZIPs, Clips ohne Metadaten)
löscht nur ein BackgroundTask nach vollständigem Senden. Bricht der Client ab (Lightbox weiter-
geblättert, Verbindung weg), läuft er nie - und keine Aufräumroutine kannte das Verzeichnis: die
Kopien blieben für immer auf dem Upload-Datenträger liegen."""

import asyncio
import io
import os
import time
import uuid
from pathlib import Path

import pytest
from PIL import Image

from app.api.routes import public_share as public_share_routes
from app.api.routes import share_links as share_links_routes
from app.core.config import settings
from app.core.storage import MAIN, get_object_store
from app.models.entities import GalleryImage, StoredFile
from app.schemas.files import ShareLinkCreate
from app.services.file_service import FileService
from tests.factories import make_current_user, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))


class _FakeRequest:
    def __init__(self) -> None:
        self.client = type("C", (), {"host": f"198.51.100.{uuid.uuid4().int % 250}"})()
        self.headers: dict[str, str] = {}


def _download_dir() -> Path:
    return Path(settings.upload_root) / "_staging" / "download"


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), "blue").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_aborted_public_view_leaves_its_filtered_copy_behind(db):
    """Ursache: der Abbruch beim Senden überspringt den BackgroundTask (unlink)."""
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    key = f"uploads/tenant-{tenant.id}/share/bild.jpg"
    get_object_store().put_bytes(db, MAIN, key, _jpeg())
    stored = StoredFile(tenant_id=tenant.id, original_name="bild.jpg", mime_type="image/jpeg", storage_path=key)
    db.add(stored)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=stored.id))
    db.flush()
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[stored.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    response = public_share_routes.view_public_share_file(token, stored.public_id, _FakeRequest(), db)

    async def receive():
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("Verbindung vom Client getrennt")

    with pytest.raises(OSError):
        asyncio.run(response({"type": "http", "method": "GET", "headers": [], "extensions": {}}, receive, send))
    assert [p.name for p in _download_dir().iterdir() if p.is_file()]  # Kopie liegt noch da


def test_gallery_maintenance_sweeps_stale_download_copies(db):
    directory = _download_dir()
    (directory / "share-zip").mkdir(parents=True)
    stale = directory / f"{uuid.uuid4().hex}.jpg"
    fresh = directory / f"{uuid.uuid4().hex}.zip"
    zip_cache = directory / "share-zip" / "abc.zip"
    for path in (stale, fresh, zip_cache):
        path.write_bytes(b"x")
    two_days_ago = time.time() - 2 * 24 * 60 * 60
    os.utime(stale, (two_days_ago, two_days_ago))

    FileService().cleanup_gallery_staging(db)

    assert not stale.exists()
    assert fresh.exists()  # ein laufender Download wird nie weggeräumt
    assert zip_cache.exists()  # eigener Cache mit eigener Frist (public_share._purge_expired_share_zips)
