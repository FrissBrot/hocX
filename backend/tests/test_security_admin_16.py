"""Sicherheitsbereich der Konsole 1.6 (Plan 2026-11-23): Sperren (Netz-Fingerprint, Verlängern,
Abgewiesen-Zähler, Verlauf, Abwehrleiter), Ereignisse (Filter, Keyset, Gruppen, Histogramm, Detail,
«Quelle sperren»), Alarmregeln (Messwerte, Kurve, Auslösungen) und Audit-Log-Ansichten.

Passkey-Bestätigungen prüft test_admin_step_up.py (Inventar); hier sind sie per Override erfüllt -
die Rollenprüfung der Route (require_admin_write/owner) bleibt dabei wirksam."""
from __future__ import annotations

import json
import time
import uuid

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from starlette.requests import Request

from app.api.routes import admin as admin_routes
from app.api.routes import admin_auth_security
from app.auth_security import blocks, read_service
from app.auth_security.guard import LoginGuard
from app.core import rate_limit
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.admin_step_up import PURPOSES, require_step_up
from app.core.auth_pseudonym import net_hash
from app.core.db import get_db
from app.core.redis_client import get_redis_sync
from app.models import AuthEvent, PlatformAdmin
from app.schemas.user import LoginRequest
from app.services.auth_service import AuthService


def _flush() -> None:
    client = get_redis_sync()
    for pattern in ("ratelimit:*", "authsec:*", "authblock:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    rate_limit.local_window.clear()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _flush()
    monkeypatch.setattr(read_service, "_ladder_cache", None)
    yield
    _flush()


def _admin(db, role: str = "owner") -> CurrentAdmin:
    admin = PlatformAdmin(email=f"s16-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name=f"Admin {role}", role=role)
    db.add(admin)
    db.flush()
    return CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name, role=role)


def _client(db, actor: CurrentAdmin) -> TestClient:
    app = FastAPI()
    for module in (admin_routes, admin_auth_security):
        app.include_router(module.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: actor
    for purpose in PURPOSES:
        app.dependency_overrides[require_step_up(purpose)] = lambda: actor
    return TestClient(app)


def _login(db, email: str, ip: str):
    request = Request({"type": "http", "method": "POST", "path": "/api/auth/login", "query_string": b"", "headers": []})
    return AuthService().login(db, Response(), LoginRequest(email=email, password="falsch-falsch"), client_address=ip, request=request)


def _block_events(db, subject: str, event_type: str = "block.set") -> list[AuthEvent]:
    db.expire_all()
    return [
        event for event in db.scalars(select(AuthEvent).where(AuthEvent.event_type == event_type).order_by(AuthEvent.id))
        if (event.details or {}).get("subject") == subject[:12]
    ]


# ── Sperren ────────────────────────────────────────────────────────────────────────────────


def test_fingerprint_block_covers_the_whole_net_and_counts_rejections(db):
    fingerprint = net_hash("198.51.100.7")
    block = blocks.set_manual(subject=fingerprint, scope="net_fp", minutes=30, reason="Abuse-Meldung", admin_id=None)
    assert block.scope == "net_fp" and block.stage == 5 and block.created and block.minutes == 30
    assert blocks.is_blocked("198.51.100.200") is not None   # gleiches /24
    assert blocks.is_blocked("198.51.101.7") is None         # anderes Netz
    with pytest.raises(HTTPException) as exc:
        _login(db, f"fp-{uuid.uuid4().hex[:6]}@example.com", "198.51.100.9")
    assert exc.value.detail["code"] == "source_blocked"
    assert blocks.rejections([fingerprint])[fingerprint] == 1
    listed = read_service.active_blocks(db)
    assert listed[0]["short"] == fingerprint[:12] and listed[0]["rejected"] == 1


def test_platform_admin_login_ignores_fingerprint_blocks():
    blocks.set_manual(subject=net_hash("198.51.100.7"), scope="net_fp", minutes=30, reason="Test", admin_id=None)
    guard = LoginGuard("login-admin")
    result = guard.check(email="ops@example.com", ip="198.51.100.8", known_device=False, device_hash=None, exempt_from_source_blocks=True)
    assert result is not None
    with pytest.raises(HTTPException):
        LoginGuard().check(email="person@example.com", ip="198.51.100.8", known_device=False, device_hash=None)


def test_manual_subject_must_be_an_own_pseudonym():
    with pytest.raises(ValueError):
        blocks.set_manual(subject="abc", scope="net_fp", minutes=5, reason="x x x")
    with pytest.raises(ValueError):
        blocks.set_manual(subject="z" * 24, scope="source", minutes=5, reason="x x x")
    with pytest.raises(ValueError):
        blocks.set_manual(ip="198.51.100.7", scope="anderes", minutes=5, reason="x x x")


def test_old_redis_entries_without_new_fields_still_load():
    raw = json.dumps({"subject": "a" * 24, "scope": "source", "until": int(time.time()) + 60, "reason": "r", "manual": False, "stage": 4})
    block = blocks.Block.from_json(raw)
    assert block.created == 0 and block.admin_id is None and block.incident_id is None


def test_block_events_carry_short_subject_admin_and_no_admin_network(db):
    owner = _admin(db)
    client = _client(db, owner)
    response = client.post("/api/admin/auth-security/blocks", json={"ip": "203.0.113.77", "scope": "net", "minutes": 60, "reason": "Abuse-Meldung #1"})
    assert response.status_code == 201, response.text
    subject = response.json()["subject"]
    (event,) = _block_events(db, subject)
    assert event.platform_admin_id == owner.admin_id
    assert event.details["admin_id"] == owner.admin_id and event.details["incident_id"] is None
    assert event.details["kind"] == "manual" and event.details["stage"] == 5
    # Das Netz des Ereignisses ist nie das des setzenden Admins
    assert event.src_net_hash is None and event.src_ip_hash is None
    audit = db.execute(text("SELECT details_json FROM audit_log WHERE action = 'admin.auth_block_set' AND actor_email = :email"), {"email": owner.email}).scalar()
    assert audit["subject"] == subject[:12] and audit["reason"] == "Abuse-Meldung #1"


def test_extend_turns_automatic_block_into_manual_stage5(db, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_block_strikes", 1)
    automatic = blocks.strike("192.0.2.230", reason="source_hard")
    assert automatic is not None and not automatic.manual
    owner = _admin(db)
    client = _client(db, owner)
    response = client.post(f"/api/admin/auth-security/blocks/{automatic.subject}/extend", json={"minutes": 120, "reason": "Vorfall prüfen"})
    assert response.status_code == 200, response.text
    extended = blocks.get(automatic.subject)
    assert extended.manual and extended.stage == 5 and extended.admin_id == owner.admin_id
    assert extended.until >= automatic.until + 120 * 60 - 2
    assert client.post(f"/api/admin/auth-security/blocks/{automatic.subject}/extend", json={"minutes": 5, "reason": ""}).status_code == 422
    assert client.post(f"/api/admin/auth-security/blocks/{'0' * 24}/extend", json={"minutes": 5, "reason": "gibt es nicht"}).status_code == 404
    assert db.execute(text("SELECT count(*) FROM audit_log WHERE action = 'admin.auth_block_extended' AND actor_email = :email"), {"email": owner.email}).scalar() == 1
    reasons = [event.details["reason"] for event in _block_events(db, automatic.subject)]
    assert reasons == ["source_hard", "extend"]


def test_history_shows_bars_and_early_clear(db):
    owner = _admin(db)
    client = _client(db, owner)
    subject = client.post("/api/admin/auth-security/blocks", json={"ip": "203.0.113.90", "minutes": 60, "reason": "Test Verlauf"}).json()["subject"]
    assert client.delete(f"/api/admin/auth-security/blocks/{subject}").status_code == 204
    history = client.get("/api/admin/auth-security/blocks/history").json()
    source = next(item for item in history["sources"] if item["subject"] == subject[:12])
    assert source["bars"][-1]["cleared"] and source["bars"][-1]["manual"]
    assert _block_events(db, subject, "block.clear")[0].details["admin_id"] == owner.admin_id


def test_ladder_counts_and_rules(db):
    blocks.set_manual(ip="203.0.113.91", minutes=10, reason="Leiter", admin_id=None)
    ladder = _client(db, _admin(db)).get("/api/admin/auth-security/blocks/ladder").json()
    assert ladder["manual"] >= 1 and set(ladder["events_24h"]) == {"observed", "limited", "challenged"}
    assert ladder["strikes"] >= 1 and ladder["durations"] and ladder["max_manual_minutes"] == blocks.MAX_MANUAL_MINUTES


def test_support_cannot_read_or_change_blocks(db):
    subject = blocks.set_manual(ip="203.0.113.92", minutes=10, reason="Support-Test", admin_id=None).subject
    client = _client(db, _admin(db, "support"))
    for path in ("/blocks", "/blocks/ladder", "/blocks/history"):
        assert client.get(f"/api/admin/auth-security{path}").status_code == 403, path
    assert client.post(f"/api/admin/auth-security/blocks/{subject}/extend", json={"minutes": 5, "reason": "nicht erlaubt"}).status_code == 403
    assert client.delete(f"/api/admin/auth-security/blocks/{subject}").status_code == 403
    assert blocks.get(subject) is not None
