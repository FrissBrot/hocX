"""Logos der Kundenleiste «Im Einsatz bei»: nur gelistete Mandanten, keine IDs/Pfade, kein Orakel."""
from __future__ import annotations

import asyncio
import io
import re

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers
from starlette.requests import Request

from app.api.routes import public_catalog
from app.core.storage import MAIN, get_object_store
from app.services import website_customer_logo_service as logos
from app.services.admin_tenant_service import AdminTenantService
from app.services.tenant_service import apply_tenant_profile_image
from tests.factories import make_tenant

service = AdminTenantService()


@pytest.fixture(autouse=True)
def _isolated_storage_and_cache(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    logos.clear_cache()
    yield
    logos.clear_cache()


def _png(size=(40, 30), color=(200, 10, 10)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _set_logo(db, tenant, content: bytes | None = None) -> None:
    upload = UploadFile(file=io.BytesIO(content or _png()), filename="logo.png", headers=Headers({"content-type": "image/png"}))
    asyncio.run(apply_tenant_profile_image(db, tenant, upload))
    db.flush()


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": raw, "client": ("203.0.113.7", 1234)})


def _get(db, key: str, headers: dict[str, str] | None = None):
    return public_catalog.get_public_customer_logo(key, _request(headers), db)


def _customer(db, name: str):
    return next(c for c in service.list_public_customers(db) if c.name == name)


def _key(url: str) -> str:
    match = re.fullmatch(r"/api/public/customers/logos/([A-Za-z0-9_-]{22})\.png", url)
    assert match, url
    return match.group(1)


def test_listed_tenant_with_logo_gets_logo_url_and_png(db):
    tenant = make_tenant(db, name="Logo Verein Gelistet")
    _set_logo(db, tenant, _png(size=(800, 200)))
    service.set_tenant_website_listing(db, tenant.id, True)

    customer = _customer(db, tenant.name)
    assert customer.logo is not None
    # Keine internen IDs oder Speicherpfade in der öffentlichen Antwort
    payload = customer.model_dump_json()
    assert str(tenant.public_id) not in payload and tenant.profile_image_path not in payload and "tenant-" not in payload
    assert (customer.logo.width, customer.logo.height) == (256, 64)

    response = _get(db, _key(customer.logo.url))
    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert response.headers["cache-control"] == "public, max-age=3600"
    with Image.open(io.BytesIO(response.body)) as image:
        assert image.format == "PNG"
        assert image.size == (256, 64)


def test_conditional_request_returns_304(db):
    tenant = make_tenant(db, name="Logo Verein Etag")
    _set_logo(db, tenant)
    service.set_tenant_website_listing(db, tenant.id, True)
    key = _key(_customer(db, tenant.name).logo.url)

    etag = _get(db, key).headers["etag"]
    for header in (etag, f"W/{etag}", f'"anderes", {etag}'):
        response = _get(db, key, {"If-None-Match": header})
        assert response.status_code == 304
        assert response.body == b""
    assert _get(db, key, {"If-None-Match": '"anderes"'}).status_code == 200


def test_listed_tenant_without_logo_is_name_only(db):
    tenant = make_tenant(db, name="Logo Verein Ohne Logo")
    service.set_tenant_website_listing(db, tenant.id, True)
    assert _customer(db, tenant.name).logo is None


def _assert_not_found(db, key: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _get(db, key)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Not found"


def test_unlisted_unknown_and_malformed_keys_give_identical_404(db):
    listed = make_tenant(db, name="Logo Verein Sichtbar")
    _set_logo(db, listed)
    service.set_tenant_website_listing(db, listed.id, True)
    hidden = make_tenant(db, name="Logo Verein Versteckt")
    _set_logo(db, hidden)

    # Nicht gelistet: auch mit korrekt berechneter Kennung nichts
    _assert_not_found(db, logos.logo_key(hidden))
    # Unbekannt, falsch geformt, Pfad-/ID-Versuche
    _assert_not_found(db, "A" * 22)
    _assert_not_found(db, "kurz")
    _assert_not_found(db, str(listed.public_id))
    _assert_not_found(db, "..%2F..%2Fetc%2Fpasswd")

    # Entlisten wirkt sofort, auch wenn das Logo im Prozess-Cache liegt
    key = _key(_customer(db, listed.name).logo.url)
    assert _get(db, key).status_code == 200
    service.set_tenant_website_listing(db, listed.id, False)
    _assert_not_found(db, key)


def test_new_logo_changes_url_and_old_key_stops_working(db):
    tenant = make_tenant(db, name="Logo Verein Neu")
    _set_logo(db, tenant, _png(color=(10, 200, 10)))
    service.set_tenant_website_listing(db, tenant.id, True)
    old_key = _key(_customer(db, tenant.name).logo.url)

    _set_logo(db, tenant, _png(color=(10, 10, 200)))
    new_key = _key(_customer(db, tenant.name).logo.url)
    assert new_key != old_key
    _assert_not_found(db, old_key)
    assert _get(db, new_key).status_code == 200


def test_unreadable_or_missing_logo_falls_back_to_name(db):
    broken = make_tenant(db, name="Logo Verein Kaputt")
    legacy_key = f"uploads/tenant-profiles/legacy-{broken.id}.png"
    get_object_store().put_bytes(db, MAIN, legacy_key, b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    broken.profile_image_path = legacy_key
    missing = make_tenant(db, name="Logo Verein Fehlt")
    missing.profile_image_path = f"uploads/tenant-profiles/missing-{missing.id}.png"
    db.flush()
    for tenant in (broken, missing):
        service.set_tenant_website_listing(db, tenant.id, True)
        assert _customer(db, tenant.name).logo is None
        _assert_not_found(db, logos.logo_key(tenant))


def test_failed_logo_is_not_reloaded_on_every_request(db, monkeypatch):
    tenant = make_tenant(db, name="Logo Verein Zu Gross")
    _set_logo(db, tenant)
    service.set_tenant_website_listing(db, tenant.id, True)
    monkeypatch.setattr(logos, "TENANT_PROFILE_IMAGE_MAX_BYTES", 10)
    calls = []
    store = get_object_store()
    original = type(store).get_bytes

    def counting_get_bytes(self, *args, **kwargs):
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(store), "get_bytes", counting_get_bytes)
    for _ in range(3):
        assert _customer(db, tenant.name).logo is None
    _assert_not_found(db, logos.logo_key(tenant))
    assert len(calls) == 1
