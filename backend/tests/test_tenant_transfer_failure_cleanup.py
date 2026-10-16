"""Audit MAIN-BE-006: Ein fehlgeschlagener Import/Klon hinterlässt weder Mandant noch
kopierte Dateien, und die ursprüngliche Exception bleibt erhalten.

Hinweis: In der Test-Session rollt db.rollback() bis zum Testbeginn zurück (auch bereits
"committete" Zeilen) - geprüft werden deshalb Dateien und der Name des neuen Mandanten."""
import pytest
from sqlalchemy import select

from app.models.entities import ProtocolImage, StoredFile, Tenant
from app.services.tenant_clone_service import TenantCloneService
from app.services.tenant_export_service import TenantExportService
from app.services.tenant_import_service import TenantImportService
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template, make_tenant


@pytest.fixture
def storage(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services import tenant_import_service as import_module

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbs"))
    monkeypatch.setattr(import_module.scanner, "scan_file", lambda *args, **kwargs: "clean")
    (tmp_path / "storage").mkdir()
    (tmp_path / "abgabebox").mkdir()
    return tmp_path


def _tenant_with_protocol_image(db, storage):
    tenant = make_tenant(db, "Quelle")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    (storage / "storage" / "bild.png").write_bytes(b"fake-png-bytes")
    stored_file = StoredFile(tenant_id=tenant.id, original_name="bild.png", mime_type="image/png", storage_path="bild.png", file_size_bytes=14)
    db.add(stored_file)
    db.flush()
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, sort_index=0))
    db.flush()
    return tenant


def _boom(*_args, **_kwargs):
    raise RuntimeError("boom")


def test_failed_import_after_files_leaves_no_tenant_and_no_files(db, storage, monkeypatch):
    tenant = _tenant_with_protocol_image(db, storage)
    zip_path, _ = TenantExportService().export(db, tenant.id, "full")
    monkeypatch.setattr(TenantImportService, "_import_share_links", _boom, raising=False)
    try:
        with pytest.raises(RuntimeError, match="boom"):
            TenantImportService().import_zip(db, zip_path, "Import")
    finally:
        zip_path.unlink(missing_ok=True)

    assert db.scalar(select(Tenant.id).where(Tenant.name == "Import")) is None
    imports_dir = storage / "storage" / "tenant_imports"
    assert not imports_dir.exists() or not any(imports_dir.iterdir())


def test_failed_clone_after_files_leaves_no_tenant_and_no_files(db, storage, monkeypatch):
    tenant = _tenant_with_protocol_image(db, storage)
    monkeypatch.setattr(TenantCloneService, "_clone_finance_transactions", _boom, raising=False)

    with pytest.raises(RuntimeError, match="boom"):
        TenantCloneService().clone_full(db, tenant.id, "Kopie")

    assert db.scalar(select(Tenant.id).where(Tenant.name == "Kopie")) is None
    clones_dir = storage / "storage" / "tenant_clones"
    assert not clones_dir.exists() or not any(clones_dir.iterdir())


def test_cleanup_failure_does_not_mask_original_error(db, storage, monkeypatch):
    from app.services.admin_tenant_service import AdminTenantService

    tenant = _tenant_with_protocol_image(db, storage)

    def broken_delete(self, _db, _tenant_id):
        raise OSError("Aufräumen kaputt")

    monkeypatch.setattr(AdminTenantService, "delete_tenant", broken_delete)
    monkeypatch.setattr(TenantCloneService, "_clone_finance_transactions", _boom, raising=False)

    with pytest.raises(RuntimeError, match="boom"):
        TenantCloneService().clone_full(db, tenant.id, "Kopie")
