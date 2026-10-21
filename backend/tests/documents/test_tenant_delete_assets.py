"""TYPST-006: Mandanten-Löschung entfernt auch die aus alten Dokumentvorlagen übernommenen
Hausstil-Dateien (Migration 0115 lässt sie unter document_template_parts/ liegen)."""
from __future__ import annotations

from app.core.config import settings
from app.models import DocumentAsset
from app.services.admin_tenant_service import AdminTenantService
from tests.factories import make_tenant


def test_delete_tenant_removes_migrated_style_asset_files(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    tenant = make_tenant(db, "Löschverein")
    other = make_tenant(db, "Bleibeverein")
    legacy = tmp_path / f"document_template_parts/tenant-{tenant.id}/logo/v1.png"
    current = tmp_path / f"document_style_assets/tenant-{tenant.id}/schrift.ttf"
    foreign = tmp_path / f"document_template_parts/tenant-{other.id}/logo/v1.png"
    for path in (legacy, current, foreign):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    db.add_all(
        [
            DocumentAsset(tenant_id=tenant.id, kind="image", name="Logo", original_name="v1.png", mime_type="image/png", storage_path=str(legacy.relative_to(tmp_path))),
            DocumentAsset(tenant_id=tenant.id, kind="font", name="Schrift", original_name="schrift.ttf", mime_type="font/ttf", storage_path=str(current.relative_to(tmp_path))),
            DocumentAsset(tenant_id=other.id, kind="image", name="Logo", original_name="v1.png", mime_type="image/png", storage_path=str(foreign.relative_to(tmp_path))),
        ]
    )
    db.flush()

    assert AdminTenantService().delete_tenant(db, tenant.id) is not None

    assert not legacy.exists() and not current.exists()
    assert not legacy.parent.parent.exists()
    assert foreign.exists()
