"""Speicherkontingent des Vereins erreicht: der Upload wird mit storage_limit abgelehnt. Wie jede
andere Ablehnung gehört das ins Upload-Protokoll der Abgabe (Verwaltung › Abgabe › Protokoll),
sonst steht dort nur «empfangen» ohne Ausgang. Der zweite, globale Limit-Pfad protokollierte
schon, der Kontingent-Pfad des Vereins nicht."""
import asyncio
import hashlib
import io
from contextlib import nullcontext

import pytest
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.public_errors import PublicError
from app.routes import public


@pytest.mark.parametrize(("tenant_quota", "global_usage"), [
    (10, 0),  # Kontingent des Vereins (Plan + Pakete) erreicht
    (None, 10 * 1024**3),  # globale Obergrenze der Abgabebox erreicht
])
def test_storage_limit_rejection_is_written_to_the_upload_log(monkeypatch, tenant_quota, global_usage):
    logged: list[tuple[str, str | None]] = []
    monkeypatch.setattr(public, "_get_tenant_or_404", lambda *a: {"id": 1})
    monkeypatch.setattr(public, "_get_assignment_or_404", lambda *a: {
        "id": 1, "title": "Bericht", "max_files_per_element": None, "auto_close": "never",
        "allowed_file_types": ["pdf"], "max_file_size_mb": 20})
    monkeypatch.setattr(public.element_resolver, "resolve_single_element", lambda *a: {
        "event_id": 1, "list_entry_id": None, "label": "Hock"})
    monkeypatch.setattr(public, "verify_captcha_session_token", lambda *a, **k: True)
    monkeypatch.setattr(public.repository, "insert_upload_log", lambda db, **k: logged.append((k["status"], k.get("error_message"))))
    monkeypatch.setattr(public.repository, "list_checksums_for_element", lambda *a, **k: set())
    monkeypatch.setattr(public, "tenant_upload_lock", lambda *a: nullcontext())
    monkeypatch.setattr(public, "tenant_storage_bytes", lambda *a: global_usage)
    monkeypatch.setattr(public.repository, "get_tenant_storage_quota_bytes", lambda *a, **k: tenant_quota)
    monkeypatch.setattr(public.repository, "get_tenant_storage_usage_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(public.repository, "list_assignment_image_hashes", lambda *a, **k: [])

    async def clean(items, **kwargs):
        return ["clean"] * len(items)

    monkeypatch.setattr(public.scanner, "scan_many", clean)
    monkeypatch.setattr(public, "save_to_quarantine", lambda db, content, **k: ("quarantine/x.pdf", hashlib.sha256(content).hexdigest()))

    with pytest.raises(PublicError) as exc_info:
        asyncio.run(public.upload(
            Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)}),
            "token", "bericht", "event-1", captcha_session_token="token", db=object(),
            files=[UploadFile(io.BytesIO(b"%PDF-1.7\n" + b"a" * 100), filename="a.pdf")]))

    assert exc_info.value.code == "storage_limit"
    assert logged[-1][0] == "validation_failed", logged
