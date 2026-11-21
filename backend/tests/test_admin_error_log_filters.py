"""Admin-Redesign Phase D: Fehlerprotokoll mit Zeitraumfilter (from/to) und Gruppenansicht."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes import admin as admin_routes
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.db import get_db
from app.models.entities import PlatformAdmin


def _admin(db, role: str) -> CurrentAdmin:
    admin = PlatformAdmin(email=f"el-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name=f"Admin {role}", role=role)
    db.add(admin)
    db.flush()
    return CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name, role=role)


def _client(db, actor: CurrentAdmin) -> TestClient:
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: actor
    return TestClient(app)


def _error(db, error_type: str, at: datetime) -> None:
    db.execute(
        text(
            "INSERT INTO system_error_log (source, error_type, error_message, traceback, created_at) "
            "VALUES ('backend', :t, 'geheime Meldung', 'Traceback geheim', :at)"
        ),
        {"t": error_type, "at": at},
    )


def test_error_log_date_filter_and_groups(db):
    db.execute(text("DELETE FROM system_error_log"))
    base = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    _error(db, "KeyError", base)
    _error(db, "KeyError", base + timedelta(days=1))
    _error(db, "ValueErrorX", base + timedelta(days=1))
    _error(db, "OldError", base - timedelta(days=10))
    owner = _client(db, _admin(db, "owner"))

    page = owner.get("/api/admin/error-logs?from=2026-11-10&to=2026-11-11").json()
    assert page["total"] == 3
    page = owner.get("/api/admin/error-logs?from=2026-11-11").json()
    assert page["total"] == 2

    groups = owner.get("/api/admin/error-logs/groups?from=2026-11-01").json()
    assert [(group["error_type"], group["count"]) for group in groups] == [("KeyError", 2), ("ValueErrorX", 1)]
    assert "geheim" not in str(groups)
    assert set(groups[0]) == {"error_type", "count", "tenants", "first_at", "last_at"}
    assert owner.get("/api/admin/error-logs/groups?from=kein-datum").status_code == 422


def test_error_log_groups_owner_only(db):
    support = _client(db, _admin(db, "support"))
    assert support.get("/api/admin/error-logs/groups").status_code == 403
