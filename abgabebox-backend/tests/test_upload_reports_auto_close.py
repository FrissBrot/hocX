"""Die Upload-Antwort meldet, ob das Element nach dieser Abgabe automatisch geschlossen wurde
(Nachtlauf 2026-11-20).

Mit auto_close 'first_upload' bzw. 'max_files' schliesst upload() das Element. Die Erfolgsseite
der Abgabebox bot trotzdem «Weitere Datei hochladen» an (sie kennt auto_close nicht), und der
nächste Versuch scheiterte mit «Element ist nicht (mehr) offen»."""
import asyncio
import hashlib
import io
from contextlib import nullcontext

import pytest
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.routes import public


def _upload(monkeypatch, *, auto_close: str, max_files: int | None, already: int = 0, contents=(b"%PDF-1.7\na\n",)):
    monkeypatch.setattr(public, "_get_tenant_or_404", lambda *a: {"id": 1})
    monkeypatch.setattr(public, "_get_assignment_or_404", lambda *a: {
        "id": 1, "title": "Bericht", "max_files_per_element": max_files, "auto_close": auto_close,
        "allowed_file_types": ["pdf"], "max_file_size_mb": 20})
    monkeypatch.setattr(public.element_resolver, "resolve_single_element", lambda *a: {
        "event_id": 1, "list_entry_id": None, "label": "Hock"})
    monkeypatch.setattr(public, "verify_captcha_session_token", lambda *a, **k: True)
    monkeypatch.setattr(public.repository, "insert_upload_log", lambda *a, **k: None)
    monkeypatch.setattr(public.repository, "list_checksums_for_element", lambda *a, **k: set())
    monkeypatch.setattr(public, "tenant_upload_lock", lambda *a: nullcontext())
    monkeypatch.setattr(public, "tenant_storage_bytes", lambda *a: 0)
    monkeypatch.setattr(public.repository, "get_tenant_storage_quota_bytes", lambda *a, **k: None)
    monkeypatch.setattr(public.repository, "get_tenant_storage_usage_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(public.repository, "list_assignment_image_hashes", lambda *a, **k: [])
    monkeypatch.setattr(public.repository, "latest_status_by_element", lambda *a, **k: {})
    monkeypatch.setattr(public.repository, "count_files_by_element", lambda *a, **k: {public.repository.element_key({"event_id": 1, "list_entry_id": None}): already})
    monkeypatch.setattr(public, "save_to_quarantine", lambda db, content, **k: ("quarantine/x.pdf", hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(public, "move_from_quarantine", lambda *a: "x.pdf")

    async def clean(items, **kwargs):
        return ["clean"] * len(items)

    monkeypatch.setattr(public.scanner, "scan_many", clean)
    closed: list[bool] = []
    monkeypatch.setattr(public.repository, "insert_full_upload", lambda db, **k: closed.append(k["close_after"]))
    result = asyncio.run(public.upload(
        Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)}),
        "token", "bericht", "event-1", captcha_session_token="token", db=object(),
        files=[UploadFile(io.BytesIO(data), filename=f"{i}.pdf") for i, data in enumerate(contents)]))
    return result, closed


@pytest.mark.parametrize(("auto_close", "max_files", "already", "expected"), [
    ("first_upload", None, 0, True),
    ("max_files", 2, 1, True),
    ("max_files", 3, 1, False),
    ("never", 1, 0, False),
])
def test_upload_result_reports_whether_the_element_was_closed(monkeypatch, auto_close, max_files, already, expected):
    result, closed = _upload(monkeypatch, auto_close=auto_close, max_files=max_files, already=already)
    assert closed == [expected]
    assert result.element_closed is expected
