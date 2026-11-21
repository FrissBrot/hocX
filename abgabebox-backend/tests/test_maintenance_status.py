"""Öffentlicher Wartungsstatus der Abgabebox: Update statt Wartung während eines Deploys
(Migration 0212 maintenance_public_update), nur minimale Angaben."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main as main_module
from app import maintenance
from app.db import engine


def test_abgabebox_role_can_read_the_update_function():
    with engine.connect() as conn:
        assert conn.execute(text("SELECT session_user")).scalar() == "hocx_abgabebox"
        row = conn.execute(text("SELECT * FROM maintenance_public_update()")).one()
        # Ohne sperrendes Fenster: kein Update, keine Versionen.
        assert row.update_active is False


def test_load_update_info_validates_versions():
    class Row:
        def __init__(self, mapping):
            self._mapping = mapping

    class Result:
        def __init__(self, mapping):
            self.mapping = mapping

        def one(self):
            return Row(self.mapping)

    class Conn:
        def __init__(self, mapping):
            self.mapping = mapping

        def begin_nested(self):
            from contextlib import nullcontext
            return nullcontext()

        def execute(self, _statement):
            return Result(self.mapping)

    started = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
    info = maintenance._load_update_info(Conn({"update_active": True, "from_version": "1.5.0", "to_version": "<script>", "started_at": started}))
    assert info == {"update_active": True, "from_version": "1.5.0", "to_version": None, "started_at": started}
    assert maintenance._load_update_info(Conn({"update_active": False, "from_version": "1.5.0", "to_version": "1.5.1", "started_at": started})) == {}


def test_load_update_info_falls_back_to_maintenance_without_function():
    class Conn:
        def begin_nested(self):
            from contextlib import nullcontext
            return nullcontext()

        def execute(self, _statement):
            raise RuntimeError("function maintenance_public_update() does not exist")

    assert maintenance._load_update_info(Conn()) == {}


def _status(monkeypatch, state: maintenance.State) -> dict:
    monkeypatch.setattr(main_module, "current_state", lambda: state)
    return TestClient(main_module.app).get("/api/public/maintenance-status").json()


def test_status_reports_update_with_versions_only_during_a_deploy(monkeypatch):
    started = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
    body = _status(monkeypatch, maintenance.State(full_active=True, writes_blocked=True, uploads_blocked=True, update_active=True,
                                                  from_version="1.5.0", to_version="1.5.1", started_at=started))
    assert body["kind"] == "update" and body["from_version"] == "1.5.0" and body["to_version"] == "1.5.1"
    assert body["started_at"].startswith("2026-11-21T12:00")
    assert set(body) == {"active", "uploads_blocked", "kind", "from_version", "to_version", "started_at", "estimated_end_at"}

    body = _status(monkeypatch, maintenance.State(full_active=True, writes_blocked=True, uploads_blocked=True))
    assert body["kind"] == "maintenance" and body["from_version"] is None and body["started_at"] is None

    body = _status(monkeypatch, maintenance.State(uploads_blocked=True))
    assert body["kind"] == "maintenance" and body["active"] is False

    body = _status(monkeypatch, maintenance.State())
    assert body["kind"] is None and body["active"] is False
