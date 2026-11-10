"""Datenschutz-Audit Paket 9: «GPS-Daten des Bildes mitsenden» aus -> Standort wird vor dem Speichern
entfernt; die Abgabe-Seite liefert Verantwortlichen und Datenschutz-Link."""
import asyncio
import hashlib
import io
from contextlib import nullcontext
from unittest.mock import AsyncMock

from PIL import Image
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.config import settings
from app.routes import public

_GPS = 0x8825


def _jpeg_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x0132] = "2026:07:01 10:00:00"
    exif[_GPS] = {1: "N", 2: (47.0, 22.0, 10.5), 3: "E", 4: (8.0, 32.0, 5.25)}
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 200)).save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


def _setup(monkeypatch, saved):
    monkeypatch.setattr(public, "_get_tenant_or_404", lambda *a: {"id": 1})
    monkeypatch.setattr(public, "_get_assignment_or_404", lambda *a: {
        "id": 1, "title": "Fotos", "max_files_per_element": None, "allowed_file_types": ["jpg"], "max_file_size_mb": 20})
    monkeypatch.setattr(public.element_resolver, "resolve_single_element", lambda *a: {"event_id": 1, "list_entry_id": None, "label": "Lager"})
    monkeypatch.setattr(public, "verify_captcha_session_token", lambda *a, **k: True)
    monkeypatch.setattr(public.repository, "insert_upload_log", lambda *a, **k: None)
    monkeypatch.setattr(public.repository, "list_checksums_for_element", lambda *a, **k: set())
    monkeypatch.setattr(public, "tenant_upload_lock", lambda *a: nullcontext())
    monkeypatch.setattr(public, "tenant_storage_bytes", lambda *a: 0)
    monkeypatch.setattr(public.repository, "get_tenant_storage_quota_bytes", lambda *a, **k: None)
    monkeypatch.setattr(public.repository, "get_tenant_storage_usage_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(public.repository, "list_assignment_image_hashes", lambda *a, **k: [])
    monkeypatch.setattr(public.repository, "count_files_by_element", lambda *a, **k: {})
    monkeypatch.setattr(public, "save_to_quarantine", lambda db, content, **k: (saved.append(content) or "quarantine/x.jpg", hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(public, "move_from_quarantine", lambda *a: "x.jpg")
    monkeypatch.setattr(public.repository, "insert_full_upload", lambda *a, **k: saved.append(k["files"]))
    monkeypatch.setattr(public.scanner, "scan_many", AsyncMock(return_value=["clean"]))


def _upload(include_gps: bool):
    return asyncio.run(public.upload(
        Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)}),
        "token", "assignment", "event-1", captcha_session_token="token", include_gps=include_gps, db=object(),
        files=[UploadFile(io.BytesIO(_jpeg_with_gps()), filename="foto.jpg")]))


def test_upload_without_gps_stores_the_image_without_location(monkeypatch):
    saved: list = []
    _setup(monkeypatch, saved)

    assert _upload(include_gps=False).ok

    content, rows = saved[0], saved[-1]
    with Image.open(io.BytesIO(content)) as image:
        assert dict(image.getexif().get_ifd(_GPS)) == {}
        assert image.getexif().get(0x0132) == "2026:07:01 10:00:00"
    assert not any(key.startswith("gps_") for key in rows[0]["image_metadata"])


def test_upload_with_gps_keeps_the_original(monkeypatch):
    saved: list = []
    _setup(monkeypatch, saved)

    assert _upload(include_gps=True).ok

    assert saved[0] == _jpeg_with_gps()


def test_assignment_names_the_responsible_club_and_privacy_link(monkeypatch):
    monkeypatch.setattr(public, "_get_tenant_or_404", lambda *a: {"id": 1})
    monkeypatch.setattr(public, "_get_assignment_or_404", lambda *a: {
        "public_slug": "fotos", "title": "Fotos", "description": None, "allowed_file_types": [], "max_files_per_element": None, "max_file_size_mb": 20})
    monkeypatch.setattr(public.repository, "get_privacy_notice", lambda db: {"tenant_name": "Pfadi Test", "privacy_notice_url": None})
    monkeypatch.setattr(settings, "default_privacy_url", "https://plattform.example/datenschutz")

    detail = public.get_assignment("token", "fotos", db=object())

    assert detail.tenant_name == "Pfadi Test" and detail.privacy_notice_url == "https://plattform.example/datenschutz"
