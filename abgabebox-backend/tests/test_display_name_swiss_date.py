"""Der Dateiname einer Abgabe trägt das Abgabedatum in Schweizer Zeit (Nachtlauf 2026-11-20).

Zeitfenster und Fristen gelten in Europe/Zurich (element_resolver.local_today), der Container
läuft in UTC. Der Dateiname nahm bisher das UTC-Datum: wer kurz nach Mitternacht abgab (bis
01:00 im Winter, 02:00 im Sommer), bekam das Datum des Vortags im Namen - auch für eine
Abgabe, die laut Fenster erst an diesem Tag öffnete."""
import asyncio
import io
from contextlib import nullcontext
from datetime import UTC, datetime

from starlette.datastructures import UploadFile
from starlette.requests import Request

from app import element_resolver
from app.routes import public

PDF = b"%PDF-1.7\nbericht\n"


class _FrozenDatetime(datetime):
    # 20.11.2026 23:30 UTC = 21.11.2026 00:30 in Zürich (Winterzeit)
    FIXED = datetime(2026, 11, 20, 23, 30, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        return cls.FIXED.astimezone(tz) if tz is not None else cls.FIXED.replace(tzinfo=None)


def test_display_name_uses_the_swiss_date_after_midnight(monkeypatch):
    monkeypatch.setattr(public, "datetime", _FrozenDatetime, raising=False)  # vor dem Fix: UTC-Zeit aus public
    monkeypatch.setattr(element_resolver, "datetime", _FrozenDatetime)
    monkeypatch.setattr(public, "_get_tenant_or_404", lambda *a: {"id": 1})
    monkeypatch.setattr(public, "_get_assignment_or_404", lambda *a: {
        "id": 1, "title": "Bericht", "max_files_per_element": None,
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
    monkeypatch.setattr(public, "save_to_quarantine", lambda db, content, **k: ("quarantine/x.pdf", "abc"))
    monkeypatch.setattr(public, "move_from_quarantine", lambda *a: "x.pdf")

    async def clean(contents, **kwargs):
        return ["clean"] * len(contents)

    monkeypatch.setattr(public.scanner, "scan_many", clean)
    stored: list[dict] = []
    monkeypatch.setattr(public.repository, "insert_full_upload", lambda db, **k: stored.extend(k["files"]))

    asyncio.run(public.upload(
        Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)}),
        "token", "bericht", "event-1", captcha_session_token="token", db=object(),
        files=[UploadFile(io.BytesIO(PDF), filename="bericht.pdf")]))

    assert [f["original_name"] for f in stored] == ["bericht_hock_20261121.pdf"]
