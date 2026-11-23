"""Die Rolle hocx_abgabebox hat auf system_error_log bewusst nur INSERT (kein SELECT, die
Abgabebox darf das Fehlerprotokoll nie lesen). SQLAlchemy hängt an ein Core-insert() auf eine
Tabelle mit Primärschlüssel aber implizit «RETURNING id» an - Postgres verlangt dafür SELECT auf
id, der INSERT scheiterte mit «permission denied», und _record_error/_record_background_error
verschlucken das: kein einziger Fehler der Abgabebox kam im Fehlerprotokoll an.

Läuft mit der echten eingeschränkten Rolle gegen die Test-Datenbank."""
from __future__ import annotations

from sqlalchemy import insert

from app.db import SessionLocal
from app.models import system_error_log_table
from app.repository import insert_error_log


def test_insert_into_error_log_needs_no_returning():
    statement = insert(system_error_log_table).values(source="abgabebox-backend", error_type="X", error_message="y")
    compiled = statement.compile(dialect=SessionLocal.kw["bind"].dialect)
    assert "RETURNING" not in str(compiled).upper()


def test_error_log_insert_works_with_the_restricted_role():
    db = SessionLocal()
    try:
        insert_error_log(
            db, tenant_id=None, request_method="GET", request_path="/api/public/maintenance-status",
            status_code=500, error_type="RuntimeError", error_message="Testeintrag", traceback=None,
        )
    finally:
        db.rollback()
        db.close()


def test_record_background_error_reaches_the_error_log(monkeypatch):
    """_record_background_error (Quarantäne-Cleanup) verschluckt jeden Fehler beim Schreiben -
    hier sichtbar machen, ob der INSERT tatsächlich durchgeht."""
    from app import main

    failures: list = []
    original_rollback = main.SessionLocal.class_.rollback

    def _spy_rollback(self):
        failures.append("rollback")
        return original_rollback(self)

    monkeypatch.setattr(main.SessionLocal.class_, "rollback", _spy_rollback)
    main._record_background_error(RuntimeError("Testfehler im Hintergrund"))
    assert failures == []
