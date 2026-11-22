"""Rückmeldungen der öffentlichen Abgabe sind übersetzbar (Nachtlauf 2026-11-22).

Die Abgabebox-Oberfläche gibt es in allen hocX-Sprachen, das Backend antwortete aber nur mit
deutschem Freitext: Fehler wie «Element ist nicht (mehr) offen» oder «Speicherlimit erreicht»
und der Hinweis «<Datei> ähnelt einem bereits in dieser Abgabe hochgeladenen Bild.» erschienen
auf Englisch, Französisch und Italienisch unverändert deutsch. Jetzt trägt jeder kuratierte Fehler
einen stabilen ``code`` mit ``params``, und die Duplikat-Hinweise kommen nur als Dateinamen."""
import asyncio
import hashlib
import io
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.db import get_db
from app.main import app
from app.public_errors import PublicError
from app.routes import public


def _prepare_upload(monkeypatch, *, max_files=None, already=0):
    monkeypatch.setattr(public, "_get_tenant_or_404", lambda *a: {"id": 1})
    monkeypatch.setattr(public, "_get_assignment_or_404", lambda *a: {
        "id": 1, "title": "Fotos", "max_files_per_element": max_files, "auto_close": "never",
        "allowed_file_types": ["png", "pdf"], "max_file_size_mb": 20})
    monkeypatch.setattr(public.element_resolver, "resolve_single_element", lambda *a: {
        "event_id": 1, "list_entry_id": None, "label": "Hock"})
    monkeypatch.setattr(public, "verify_captcha_session_token", lambda *a, **k: True)
    monkeypatch.setattr(public.repository, "insert_upload_log", lambda *a, **k: None)
    monkeypatch.setattr(public.repository, "list_checksums_for_element", lambda *a, **k: set())
    monkeypatch.setattr(public, "tenant_upload_lock", lambda *a: nullcontext())
    monkeypatch.setattr(public, "tenant_storage_bytes", lambda *a: 0)
    monkeypatch.setattr(public.repository, "get_tenant_storage_quota_bytes", lambda *a, **k: None)
    monkeypatch.setattr(public.repository, "get_tenant_storage_usage_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(public.repository, "list_assignment_image_hashes", lambda *a, **k: [(7, "0" * 16)])
    monkeypatch.setattr(public.repository, "latest_status_by_element", lambda *a, **k: {})
    monkeypatch.setattr(public.repository, "count_files_by_element", lambda *a, **k: {
        public.repository.element_key({"event_id": 1, "list_entry_id": None}): already})
    monkeypatch.setattr(public, "save_to_quarantine", lambda db, content, **k: ("quarantine/x", hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(public, "move_from_quarantine", lambda *a: "x")
    monkeypatch.setattr(public.repository, "insert_full_upload", lambda *a, **k: None)
    # Jedes Bild gilt als ähnlich zu einem bereits hochgeladenen.
    monkeypatch.setattr(public, "_compute_perceptual_hash", lambda content, mime: "0" * 16)
    monkeypatch.setattr(public, "_has_close_perceptual_match", lambda *a: True)

    async def clean(items, **kwargs):
        return ["clean"] * len(items)

    monkeypatch.setattr(public.scanner, "scan_many", clean)


def _run_upload(files):
    return asyncio.run(public.upload(
        Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)}),
        "token", "fotos", "event-1", captcha_session_token="token", db=object(),
        files=[UploadFile(io.BytesIO(data), filename=name) for name, data in files]))


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_duplicate_hint_lists_file_names_without_german_text(monkeypatch):
    _prepare_upload(monkeypatch)
    result = _run_upload([("ferienlager.png", PNG)])
    body = result.model_dump()
    assert body["image_duplicate_files"] == ["ferienlager.png"]
    assert "ähnelt" not in str(body)


def test_too_many_files_carries_code_and_numbers(monkeypatch):
    _prepare_upload(monkeypatch, max_files=2, already=2)
    with pytest.raises(PublicError) as raised:
        _run_upload([("bericht.pdf", b"%PDF-1.7\na\n")])
    assert raised.value.code == "too_many_files_total"
    assert raised.value.params == {"maxFiles": 2, "remaining": 0}


def test_disallowed_extension_carries_code(monkeypatch):
    _prepare_upload(monkeypatch)
    with pytest.raises(PublicError) as raised:
        _run_upload([("setup.exe", b"MZ")])
    assert raised.value.code == "file_type_not_allowed"
    assert raised.value.params == {"extension": "exe"}


def test_error_response_contains_code_and_params(monkeypatch):
    def closed(*_args):
        raise PublicError(400, "element_closed", "Element ist nicht (mehr) offen")

    monkeypatch.setattr(public, "_get_tenant_or_404", closed)
    app.dependency_overrides[get_db] = lambda: None
    try:
        response = TestClient(app).get("/api/public/token/assignments")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 400
    assert response.json() == {"detail": "Element ist nicht (mehr) offen", "code": "element_closed", "params": {}}


def test_not_found_has_a_code():
    assert public.NOT_FOUND.code == "not_found"
    assert public.FEATURE_DISABLED.code == "feature_disabled"
