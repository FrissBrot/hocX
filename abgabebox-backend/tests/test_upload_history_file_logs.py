"""Upload-Verlauf (Backend-Migration 0254): die Abgabebox meldet abgelehnte und doppelte Dateien
je Datei mit Grund in submission_upload_log - die öffentliche Antwort bleibt unverändert."""
import asyncio
import hashlib
import io
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app import repository
from app.routes import public
from tests.test_exact_upload_duplicates import NEW, PDF, setup_upload


def _collect(monkeypatch):
    calls = []
    monkeypatch.setattr(public.repository, "insert_file_logs", lambda db, **kwargs: calls.append(kwargs))
    return calls


class _Db:
    """Session-Ersatz: der Virenfund-Pfad räumt die Quarantäne mit commit/rollback auf."""

    def commit(self):
        pass

    def rollback(self):
        pass


def _upload(files):
    return asyncio.run(public.upload(
        Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)}),
        "token", "assignment", "event-1", captcha_session_token="token", db=_Db(),
        files=[UploadFile(io.BytesIO(data), filename=name) for name, data in files]))


def _stored_flow(monkeypatch, scan_result=("clean",), upload_id=42):
    monkeypatch.setattr(public.repository, "count_files_by_element", lambda *a, **k: {})
    monkeypatch.setattr(public, "save_to_quarantine", lambda db, content, **k: ("quarantine/t.pdf", hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(public, "move_from_quarantine", lambda *a: "t.pdf")
    monkeypatch.setattr(public, "delete_object", lambda *a: None)
    monkeypatch.setattr(public.repository, "insert_full_upload", lambda *a, **k: upload_id)
    monkeypatch.setattr(public.scanner, "scan_many", AsyncMock(return_value=list(scan_result)))


def test_duplicates_are_logged_with_the_stored_submission_but_not_revealed(monkeypatch):
    setup_upload(monkeypatch)
    calls = _collect(monkeypatch)
    _stored_flow(monkeypatch)
    result = _upload([("alt.pdf", PDF), ("neu.pdf", NEW)])
    assert result.ok and result.files_received == 2  # Antwort verrät das Duplikat nicht
    [call] = calls
    assert call["upload_id"] == 42 and call["files"] == [("duplicate_exact", "alt.pdf", len(PDF))]
    assert call["request_ref"] is not None


def test_all_duplicates_are_logged_per_request(monkeypatch):
    setup_upload(monkeypatch)
    calls = _collect(monkeypatch)
    monkeypatch.setattr(public.scanner, "scan_many", AsyncMock(return_value=[]))
    _upload([("a.pdf", PDF), ("b.pdf", PDF)])
    [call] = calls
    assert call["upload_id"] is None and [entry[0] for entry in call["files"]] == ["duplicate_exact", "duplicate_exact"]


def test_wrong_type_is_logged_with_reason_and_name(monkeypatch):
    setup_upload(monkeypatch)
    calls = _collect(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        _upload([("bild.exe", b"MZ")])
    assert caught.value.status_code == 400
    assert calls[0]["files"][0][:2] == ("unsupported_format", "bild.exe")


def test_infected_file_is_logged_as_infected(monkeypatch):
    setup_upload(monkeypatch)
    calls = _collect(monkeypatch)
    _stored_flow(monkeypatch, scan_result=("infected",))
    with pytest.raises(HTTPException) as caught:
        _upload([("virus.pdf", NEW)])
    assert caught.value.status_code == 400
    assert calls[-1]["files"] == [("infected", "virus.pdf", len(NEW))]


def test_file_log_rows_are_capped_and_typed():
    rows = []

    class FakeDb:
        def execute(self, statement, params):
            rows.extend(params)

        def commit(self):
            pass

    files = [("too_large", f"f{i}.pdf", 1) for i in range(50)] + [("duplicate_exact", "d.pdf", 1)]
    repository.insert_file_logs(FakeDb(), assignment_id=1, element_ref="event-1", request_ref=None, upload_id=None, files=files)
    assert len(rows) == repository.MAX_FILE_LOG_ROWS
    assert {row["status"] for row in rows} == {"file_rejected"}
    repository.insert_file_logs(FakeDb(), assignment_id=1, element_ref="event-1", request_ref=None, upload_id=None, files=[("duplicate_exact", "x" * 400, 1)])
    assert rows[-1]["status"] == "file_duplicate" and len(rows[-1]["file_name"]) == 255


def test_log_names_lose_paths_and_control_characters():
    assert repository.safe_log_name("C:\\daten\\rech\u202enung\x00.pdf") == "rechnung.pdf"
    assert repository.safe_log_name("") is None
