"""Audit MAIN-SEC-002: Mandanten-Profilbild darf kein ausführbares Dokument werden."""
import asyncio
import io
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.api.routes import tenants as tenant_routes
from app.services.tenant_service import apply_tenant_profile_image
from tests.factories import make_tenant


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
        asyncio.run(apply_tenant_profile_image(tenant, _upload(content, filename, content_type)))
    assert exc.value.status_code == 400
    assert tenant.profile_image_path is None


def test_profile_image_is_reencoded_as_png_regardless_of_filename(db):
    from app.core.config import settings

    tenant = make_tenant(db)
    asyncio.run(apply_tenant_profile_image(tenant, _upload(_png(), "logo.html", "text/html")))

    assert tenant.profile_image_path is not None
    assert tenant.profile_image_path.endswith(".png")
    stored = Path(settings.storage_root) / tenant.profile_image_path
    with Image.open(stored) as image:
        assert image.format == "PNG"


def test_profile_image_route_sets_fixed_type_and_csp(db):
    tenant = make_tenant(db)
    asyncio.run(apply_tenant_profile_image(tenant, _upload(_png(), "logo.png", "image/png")))
    db.flush()

    response = tenant_routes.tenant_profile_image(tenant.public_id, db=db)

    assert response.media_type == "image/png"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_legacy_profile_image_with_unsafe_suffix_is_served_as_download(db):
    from app.core.config import settings

    tenant = make_tenant(db)
    legacy = Path(settings.upload_root) / "tenant-profiles" / "legacy.html"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"<script>alert(1)</script>")
    tenant.profile_image_path = str(legacy.relative_to(settings.storage_root))
    db.flush()

    response = tenant_routes.tenant_profile_image(tenant.public_id, db=db)

    assert response.media_type == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
