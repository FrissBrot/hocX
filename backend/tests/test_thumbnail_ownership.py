"""Audit MAIN-BE-003: Import und Klon übernehmen thumbnail_path nicht; ensure_thumbnail und
die Löschpfade akzeptieren nur die eigene Vorschau "<id>.jpg"."""
import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.models.entities import StoredFile
from app.services.file_service import FileService, owned_thumbnail_path
from app.services.tenant_clone_service import TenantCloneService
from app.services.tenant_export_service import TenantExportService
from app.services.tenant_import_service import TenantImportService
from tests.factories import make_tenant


def _png_bytes(color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def storage(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services import tenant_import_service as import_module

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbs"))
    monkeypatch.setattr(import_module.scanner, "scan_file", lambda *args, **kwargs: "clean")
    (tmp_path / "storage").mkdir()
    (tmp_path / "thumbs").mkdir()
    return settings


def _image_with_thumbnail(db, settings, tenant_id: int, name: str, color) -> StoredFile:
    (Path(settings.storage_root) / name).write_bytes(_png_bytes(color))
    stored_file = StoredFile(tenant_id=tenant_id, original_name=name, mime_type="image/png", storage_path=name, file_size_bytes=10)
    db.add(stored_file)
    db.flush()
    assert FileService().ensure_thumbnail(db, stored_file, settings.storage_root) is not None
    return stored_file


def test_ensure_thumbnail_ignores_foreign_thumbnail_name(db, storage):
    tenant_a = make_tenant(db, "A")
    tenant_b = make_tenant(db, "B")
    foreign = _image_with_thumbnail(db, storage, tenant_a.id, "a.png", (255, 0, 0))
    own = _image_with_thumbnail(db, storage, tenant_b.id, "b.png", (0, 0, 255))
    foreign_thumb = owned_thumbnail_path(foreign)
    # Zustand nach einem alten Import: Name zeigt auf die Vorschau der fremden Datei.
    own.thumbnail_path = foreign.thumbnail_path
    db.flush()

    path = FileService().ensure_thumbnail(db, own, storage.storage_root)

    assert path is not None
    assert path.name == f"{own.id}.jpg"
    assert own.thumbnail_path == f"{own.id}.jpg"
    assert foreign_thumb.exists()


def test_delete_stored_file_keeps_foreign_thumbnail(db, storage):
    tenant = make_tenant(db, "A")
    foreign = _image_with_thumbnail(db, storage, tenant.id, "a.png", (255, 0, 0))
    other = StoredFile(tenant_id=tenant.id, original_name="c.png", mime_type="image/png", storage_path="c.png", thumbnail_path=foreign.thumbnail_path)
    db.add(other)
    db.flush()

    FileService().delete_stored_file(db, other)

    assert owned_thumbnail_path(foreign).exists()


def test_import_resets_thumbnail_path(db, storage):
    tenant = make_tenant(db, "Quelle")
    source = _image_with_thumbnail(db, storage, tenant.id, "a.png", (255, 0, 0))

    zip_path, _ = TenantExportService().export(db, tenant.id, "full")
    try:
        new_tenant, _warnings = TenantImportService().import_zip(db, zip_path, "Import")
    finally:
        zip_path.unlink(missing_ok=True)

    imported = db.scalar(select(StoredFile).where(StoredFile.tenant_id == new_tenant.id))
    assert imported is not None
    assert imported.id != source.id
    assert imported.thumbnail_path is None


def test_clone_gets_own_thumbnail_and_delete_keeps_source_preview(db, storage):
    tenant = make_tenant(db, "Quelle")
    source = _image_with_thumbnail(db, storage, tenant.id, "a.png", (255, 0, 0))
    source_thumb = owned_thumbnail_path(source)

    cloned_tenant = TenantCloneService().clone_full(db, tenant.id, "Kopie")
    cloned = db.scalar(select(StoredFile).where(StoredFile.tenant_id == cloned_tenant.id))
    assert cloned is not None
    assert cloned.thumbnail_path is None

    FileService().delete_stored_file(db, cloned)

    assert source_thumb.exists()


def test_delete_tenant_removes_own_thumbnails_only(db, storage):
    """Audit MAIN-BE-005: Mandant löschen entfernt auch die Vorschaubilder."""
    from app.services.admin_tenant_service import AdminTenantService

    doomed = make_tenant(db, "Weg")
    keeper = make_tenant(db, "Bleibt")
    doomed_file = _image_with_thumbnail(db, storage, doomed.id, "weg.png", (1, 2, 3))
    keeper_file = _image_with_thumbnail(db, storage, keeper.id, "bleibt.png", (4, 5, 6))
    doomed_thumb = owned_thumbnail_path(doomed_file)
    keeper_thumb = owned_thumbnail_path(keeper_file)
    # Fremdname aus altem Import darf die Vorschau des anderen Mandanten nicht mitnehmen.
    extra = StoredFile(tenant_id=doomed.id, original_name="x.png", mime_type="image/png", storage_path="x.png", thumbnail_path=keeper_file.thumbnail_path)
    db.add(extra)
    db.flush()

    assert AdminTenantService().delete_tenant(db, doomed.id) is True

    assert not doomed_thumb.exists()
    assert keeper_thumb.exists()
