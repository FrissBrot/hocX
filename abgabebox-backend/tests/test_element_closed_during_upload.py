"""Schliessen von Hand und ein laufender Upload (Audit 2026-11-12): die Abgabe prüft unter dem
Element-Lock nochmals, ob das Element inzwischen geschlossen ist, und speichert dann nichts."""
import hashlib

import pytest
from fastapi import HTTPException

from app import repository
from app.routes import public
from tests.test_exact_upload_duplicates import NEW, setup_upload, upload


class _FakeDb:
    def __init__(self):
        self.statements = []
        self.rolled_back = 0

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))

    def rollback(self):
        self.rolled_back += 1

    def commit(self):
        pass


def test_insert_refuses_when_element_was_closed_meanwhile(monkeypatch):
    monkeypatch.setattr(repository, "latest_status_by_element", lambda db, assignment_id: {(7, None): "closed"})
    db = _FakeDb()
    with pytest.raises(repository.ElementClosedError):
        repository.insert_full_upload(db, assignment_id=3, event_id=7, list_entry_id=None, files=[])
    sql, params = db.statements[0]
    assert "pg_advisory_xact_lock" in sql
    assert params == {"ns": repository.SUBMISSION_ELEMENT_LOCK_NAMESPACE, "assignment_id": 3}
    assert len(db.statements) == 1 and db.rolled_back == 1  # nichts eingefügt


def test_lock_namespace_matches_the_backend():
    assert repository.SUBMISSION_ELEMENT_LOCK_NAMESPACE == 909100002


def test_upload_answers_400_and_removes_files_when_closed_meanwhile(monkeypatch):
    setup_upload(monkeypatch)
    monkeypatch.setattr(public.repository, "count_files_by_element", lambda *a, **k: {})
    monkeypatch.setattr(public, "save_to_quarantine", lambda db, content, **k: ("quarantine/x.pdf", hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(public, "move_from_quarantine", lambda *a: "x.pdf")

    async def scan(contents, **kwargs):
        return ["clean"] * len(contents)

    monkeypatch.setattr(public.scanner, "scan_many", scan)

    def closed(*a, **k):
        raise repository.ElementClosedError()

    monkeypatch.setattr(public.repository, "insert_full_upload", closed)
    deleted = []
    monkeypatch.setattr(public, "delete_object", lambda db, key: deleted.append(key))

    class Db:
        def rollback(self):
            pass

        def commit(self):
            pass

    import asyncio
    import io

    from starlette.datastructures import UploadFile
    from starlette.requests import Request

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(public.upload(
            Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)}),
            "token", "assignment", "event-1", captcha_session_token="token", db=Db(),
            files=[UploadFile(io.BytesIO(NEW), filename="0.pdf")],
        ))
    assert excinfo.value.status_code == 400
    assert deleted == ["x.pdf"]


def test_upload_is_refused_early_when_closed_by_hand(monkeypatch):
    setup_upload(monkeypatch)
    monkeypatch.setattr(public.repository, "latest_status_by_element", lambda *a, **k: {(1, None): "closed"})
    with pytest.raises(HTTPException) as excinfo:
        upload([NEW])
    assert excinfo.value.status_code == 400
