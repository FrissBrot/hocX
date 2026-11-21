"""Audit MAIN-SEC-002: Mandanten-Profilbild darf kein ausführbares Dokument werden."""
import asyncio
import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers
from starlette.requests import Request

from app.api.routes import admin as admin_routes
from app.api.routes import tenants as tenant_routes
from app.core.storage import MAIN, get_object_store
from app.services.tenant_service import apply_tenant_profile_image
from tests.factories import grant_tenant_feature, make_current_user, make_tenant, make_tenant_domain


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))


def _upload(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": content_type}))


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color=(200, 10, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("content", "filename", "content_type"),
    [
        (b"<html><script>alert(1)</script></html>", "logo.html", "text/html"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "logo.svg", "image/svg+xml"),
        (b"\x89PNG\r\n\x1a\n<script>kaputt</script>", "logo.png", "image/png"),
    ],
)
def test_profile_image_rejects_non_images(db, content, filename, content_type):
    tenant = make_tenant(db)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(apply_tenant_profile_image(db, tenant, _upload(content, filename, content_type)))
    assert exc.value.status_code == 400
    assert tenant.profile_image_path is None


def test_profile_image_is_reencoded_as_png_regardless_of_filename(db):
    tenant = make_tenant(db)
    asyncio.run(apply_tenant_profile_image(db, tenant, _upload(_png(), "logo.html", "text/html")))

    assert tenant.profile_image_path is not None
    assert tenant.profile_image_path.endswith(".png")
    stored = get_object_store().get_bytes(MAIN, tenant.profile_image_path)
    with Image.open(io.BytesIO(stored)) as image:
        assert image.format == "PNG"


def _request(headers: dict[str, str] | None = None, ip: str = "203.0.113.20") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": raw, "client": (ip, 1234)})


def _logo(db, tenant_public_id, user=None, ip: str = "203.0.113.20"):
    return tenant_routes.tenant_profile_image(str(tenant_public_id), request=_request(ip=ip), db=db, user=user)


def _assert_logo_404(db, tenant_public_id, user=None) -> None:
    with pytest.raises(HTTPException) as exc:
        _logo(db, tenant_public_id, user)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Tenant profile image not found"


def test_profile_image_route_sets_fixed_type_and_csp(db):
    tenant = make_tenant(db)
    asyncio.run(apply_tenant_profile_image(db, tenant, _upload(_png(), "logo.png", "image/png")))
    db.flush()

    response = _logo(db, tenant.public_id, make_current_user(tenant.id))

    assert response.media_type == "image/png"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_legacy_profile_image_with_unsafe_suffix_is_never_served_by_tenant_route(db):
    tenant = make_tenant(db)
    legacy_key = f"uploads/tenant-profiles/legacy-{tenant.id}.html"
    get_object_store().put_bytes(db, MAIN, legacy_key, b"<script>alert(1)</script>")
    tenant.profile_image_path = legacy_key
    db.flush()

    # Mandanten-Route: Altbestand ohne Rasterendung gar nicht, auch nicht für den eigenen Mandanten
    _assert_logo_404(db, tenant.public_id, make_current_user(tenant.id))

    # Plattform-Admin-Route: weiterhin nur als Download mit Sandbox-CSP
    response = admin_routes.tenant_profile_image(tenant.public_id, request=None, db=db)
    assert response.media_type == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"


# --- Zugriff (Härtung 2026-11): öffentlich nur, wo hocX das Logo ohnehin öffentlich zeigt ---------


def _tenant_with_logo(db, name: str):
    tenant = make_tenant(db, name=name)
    asyncio.run(apply_tenant_profile_image(db, tenant, _upload(_png(), "logo.png", "image/png")))
    db.flush()
    return tenant


def test_anonymous_gets_same_404_for_private_unknown_and_malformed(db):
    private = _tenant_with_logo(db, "Logo Privat")
    without_logo = make_tenant(db, name="Ohne Logo")
    _assert_logo_404(db, private.public_id)
    _assert_logo_404(db, without_logo.public_id)
    _assert_logo_404(db, uuid.uuid4())
    _assert_logo_404(db, "kein-uuid")


def test_anonymous_allowed_for_login_branding_of_active_app_domain(db):
    tenant = _tenant_with_logo(db, "Logo Domain")
    make_tenant_domain(db, tenant.id, domain="logo-domain.example.org", purpose="app", status="active")
    # Ohne gebuchtes custom_domain ist die Domain nicht live (FEAT-01) -> nicht öffentlich
    _assert_logo_404(db, tenant.public_id)
    grant_tenant_feature(db, tenant.id, "custom_domain")
    response = _logo(db, tenant.public_id)
    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_anonymous_allowed_for_verification_page_only_with_released_identity(db):
    tenant = _tenant_with_logo(db, "Logo Prüfseite")
    tenant.verify_show_identity = False
    db.flush()
    _assert_logo_404(db, tenant.public_id)
    tenant.verify_show_identity = True
    db.flush()
    assert _logo(db, tenant.public_id).status_code == 200


def test_logged_in_own_tenant_and_trusted_partner_only(db):
    from app.services import tenant_trust_service

    own = _tenant_with_logo(db, "Logo Eigen")
    partner = _tenant_with_logo(db, "Logo Partner")
    stranger = _tenant_with_logo(db, "Logo Fremd")
    user = make_current_user(own.id)

    response = _logo(db, own.public_id, user)
    assert response.status_code == 200
    # Nur für Angemeldete: nie in geteilten Caches
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert response.headers["vary"] == "Cookie"

    _assert_logo_404(db, partner.public_id, user)
    _assert_logo_404(db, stranger.public_id, user)
    tenant_trust_service.establish(db, own.id, partner.id)
    db.flush()
    assert _logo(db, partner.public_id, user).status_code == 200
    _assert_logo_404(db, stranger.public_id, user)


def test_failed_lookups_are_rate_limited_per_ip(db):
    from app.api.routes import tenants

    ip = "203.0.113.99"
    for _ in range(tenants.TENANT_LOGO_MISS_LIMIT_PER_MINUTE):
        with pytest.raises(HTTPException) as exc:
            _logo(db, uuid.uuid4(), ip=ip)
        assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _logo(db, uuid.uuid4(), ip=ip)
    assert exc.value.status_code == 429
    # Andere IP ist nicht betroffen
    _assert_logo_404(db, uuid.uuid4())


def test_logged_in_user_of_other_tenant_sees_public_domain_logo(db):
    tenant = _tenant_with_logo(db, "Logo Domain Öffentlich")
    make_tenant_domain(db, tenant.id, domain="logo-public.example.org", purpose="app", status="active")
    grant_tenant_feature(db, tenant.id, "custom_domain")
    other = make_tenant(db, name="Anderer Verein")
    response = _logo(db, tenant.public_id, make_current_user(other.id))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_logo_url_is_versioned_without_leaking_the_storage_key(db):
    from app.services.tenant_service import build_tenant_profile_image_url

    tenant = _tenant_with_logo(db, "Logo Version")
    first = build_tenant_profile_image_url(tenant.public_id, tenant.profile_image_path)
    asyncio.run(apply_tenant_profile_image(db, tenant, _upload(_png(), "logo.png", "image/png")))
    second = build_tenant_profile_image_url(tenant.public_id, tenant.profile_image_path)
    assert first != second
    assert first.startswith(f"/api/tenants/{tenant.public_id}/profile-image?v=")
    assert tenant.profile_image_path not in second and f"tenant-{tenant.id}" not in second
