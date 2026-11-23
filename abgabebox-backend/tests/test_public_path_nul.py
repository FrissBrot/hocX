"""Ein NUL-Zeichen (%00) im Abgabe-Slug der öffentlichen URL ist ein unbekannter Slug: 404 wie
jeder andere unbekannte Slug, kein 500 mit Eintrag im Fehlerprotokoll. Postgres-Textfelder
können kein NUL enthalten; psycopg lehnt den Parameter vor dem Senden mit DataError ab, und jeder
anonyme Link-Inhaber konnte so beliebig viele Einträge in system_error_log erzeugen.

Läuft gegen die Test-Datenbank (echter Treiber), nur der Link selbst ist vorgetäuscht."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.routes import public

VALID_TOKEN = "A" * 32


def _client(monkeypatch, recorded: list):
    monkeypatch.setattr(public.repository, "get_link_by_token", lambda db, *, token: {"id": 7, "tenant_id": 42, "token": token})
    monkeypatch.setattr(public.repository, "is_feature_enabled", lambda *a, **k: True)
    monkeypatch.setattr(main, "_record_error", lambda request, exc, status_code: recorded.append((type(exc).__name__, status_code)))
    return TestClient(main.app, raise_server_exceptions=False)


def test_nul_in_assignment_slug_is_a_plain_404(monkeypatch):
    recorded: list = []
    client = _client(monkeypatch, recorded)

    for path in (
        f"/api/public/{VALID_TOKEN}/assignments/fo%00tos",
        f"/api/public/{VALID_TOKEN}/assignments/%00/elements",
    ):
        response = client.get(path)
        assert response.status_code == 404, (path, response.status_code, response.text)
        assert response.json()["code"] == "not_found"

    assert recorded == []


def test_nul_in_assignment_slug_on_upload_is_a_plain_404(monkeypatch):
    recorded: list = []
    client = _client(monkeypatch, recorded)

    response = client.post(
        f"/api/public/{VALID_TOKEN}/assignments/%00/elements/e1/upload",
        data={"captcha_session_token": "x"},
    )
    assert response.status_code == 404, response.text
    assert recorded == []


def test_error_log_and_upload_log_strip_nul():
    """request.url.path ist dekodiert: ein %00 im Pfad (oder ein NUL im Fehlertext/Dateinamen)
    liess den INSERT mit psycopg.DataError scheitern («PostgreSQL text fields cannot contain NUL»);
    _record_error bzw. _log verschlucken das, der Eintrag verschwand ganz."""
    from app.repository import insert_error_log, insert_upload_log

    class _CapturingSession:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)

        def commit(self):
            pass

    db = _CapturingSession()
    insert_error_log(
        db, tenant_id=None, request_method="GET",
        request_path=f"/api/public/{VALID_TOKEN}/assignments/fo\x00tos",
        status_code=500, error_type="RuntimeError", error_message="kaputt\x00", traceback="Traceback\x00",
    )
    insert_upload_log(db, assignment_id=1, element_ref="e\x001", status="validation_failed", error_message="Datei zu gross: a\x00.pdf")

    for statement in db.statements:
        params = statement.compile().params
        assert not any(isinstance(value, str) and "\x00" in value for value in params.values()), params
