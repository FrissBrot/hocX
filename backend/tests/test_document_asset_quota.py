"""Nachtlauf 2026-11-19 (Verdacht «Document-Studio-Assets ausserhalb des Speicherkontingents»):
Assets (Logos, Bilder, Schriften) liegen nicht in stored_file. Sie wurden weder gegen
Tenant.storage_quota_bytes geprüft noch in der Belegung gezählt - wer Brand-Profile verwalten
darf, konnte das Kontingent unbegrenzt umgehen."""

import asyncio
import io

import pytest
from PIL import Image

from app import scanner
from app.documents import assets as asset_service
from app.models import Tenant
from app.repositories.file_repository import StoredFileRepository
from app.services.storage_service import StorageService
from tests.factories import make_tenant


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (16, 16), "teal").save(out, format="PNG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def _clean_scan(monkeypatch):
    async def clean(contents, **kwargs):
        return ["clean"] * len(contents)

    monkeypatch.setattr(scanner, "scan_many", clean)


def _create(db, tenant_id: int, content: bytes):
    return asyncio.run(asset_service.create_asset(db, tenant_id, kind="image", filename="logo.png", content=content, user_id=None))


def test_asset_bytes_count_towards_the_tenant_usage(db):
    tenant = make_tenant(db, "Kontingent")
    content = _png()

    _create(db, tenant.id, content)

    assert StoredFileRepository().total_bytes_for_tenant(db, tenant.id) == len(content)
    assert StorageService().breakdown_for_tenant(db, tenant.id).total_bytes == len(content)
    assert StorageService().total_bytes_by_tenant(db).get(tenant.id) == len(content)


def test_asset_upload_over_quota_is_rejected(db):
    tenant = make_tenant(db, "Kontingent knapp")
    content = _png()
    db.get(Tenant, tenant.id).storage_quota_bytes = len(content) * 2 - 1
    db.flush()
    _create(db, tenant.id, content)

    with pytest.raises(asset_service.AssetValidationError, match="apiError.quotaExceeded"):
        _create(db, tenant.id, content)


def test_asset_upload_within_quota_is_accepted(db):
    tenant = make_tenant(db, "Kontingent reicht")
    content = _png()
    db.get(Tenant, tenant.id).storage_quota_bytes = len(content) * 2
    db.flush()

    _create(db, tenant.id, content)
    _create(db, tenant.id, content)
