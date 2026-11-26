"""Sicherheitsbereich 1.7 (Plan 2026-11-23, Abschnitt «1.7: Vorfälle und Lagebild"): Bündelung der
Alarmregeln zu Vorfällen, Rechte (nur owner), Passkey-Pflicht, Audit, Aufbewahrung, Mitlöschen mit
dem Mandanten und Lagebild.

Passkey-Bestätigungen sind wie in test_security_admin_16.py per Override erfüllt; der eigene Test
``test_incident_mutations_need_step_up`` prüft die Pflicht ohne Override."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes import admin_auth_security
from app.auth_security import blocks, incidents, read_service, situation
from app.auth_security.threats import Threat
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.admin_step_up import PURPOSES, require_step_up
from app.core.db import get_db
from app.core.redis_client import get_redis_sync
from app.models import PlatformAdmin
from tests.factories import make_tenant

NET = "abc123def4567890"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    client = get_redis_sync()
    for key in client.scan_iter("authblock:*"):
        client.delete(key)
    monkeypatch.setattr(read_service, "_alerts_cache", None)
    situation.clear_cache()
    yield
    for key in client.scan_iter("authblock:*"):
        client.delete(key)


@pytest.fixture(autouse=True)
def _no_other_incidents(db):
    # Vorfälle aus anderen Tests/Monitor-Läufen stören die Zähler (Testtransaktion, wird zurückgerollt)
    db.execute(text("DELETE FROM security_incident"))


def _admin(db, role: str = "owner") -> CurrentAdmin:
    admin = PlatformAdmin(email=f"s17-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name=f"Admin {role} {uuid.uuid4().hex[:4]}", role=role)
    db.add(admin)
    db.flush()
    return CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name, role=role)


def _client(db, actor: CurrentAdmin, *, step_up: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(admin_auth_security.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: actor
    if step_up:
        for purpose in PURPOSES:
            app.dependency_overrides[require_step_up(purpose)] = lambda: actor
    return TestClient(app)


def _threat(rule="spraying", subject=NET[:12], severity="warning", last_at=None) -> Threat:
    return Threat(rule, subject, severity, "T", "M", last_at or datetime.now(UTC))


def _incident(db, key="auth:spraying:" + NET[:12]):
    return db.execute(text("SELECT * FROM security_incident WHERE rule_key = :key ORDER BY id DESC LIMIT 1"), {"key": key}).mappings().first()


def _kinds(db, incident_id: int) -> list[str]:
    return list(db.scalars(text("SELECT kind FROM security_incident_activity WHERE incident_id = :id ORDER BY created_at, id"), {"id": incident_id}))


def _audit(db, action: str) -> list[dict]:
    return [dict(row) for row in db.execute(
        text("SELECT details_json AS details, entity_type, entity_id FROM audit_log WHERE action = :action ORDER BY id"), {"action": action}
    ).mappings()]


# ── Bündelung ────────────────────────────────────────────────────────────────────────────


def test_one_open_incident_per_rule_key_with_clear_retrigger_and_escalation(db):
    first = datetime.now(UTC) - timedelta(minutes=10)
    assert incidents.correlate(db, [_threat(last_at=first)])["created"] == 1
    # gleicher Schlüssel: gebündelt, kein zweiter Vorfall
    result = incidents.correlate(db, [_threat(last_at=first + timedelta(minutes=2))])
    assert result == {"created": 0, "bundled": 1, "cleared": 0}
    # anderes Netz: eigener Vorfall (1 Regelschlüssel = 1 Vorfall)
    incidents.correlate(db, [_threat(last_at=first), _threat(subject="ffff00001111")])
    assert db.scalar(text("SELECT count(*) FROM security_incident")) == 2
    # abgeklungen: bleibt offen, Zeitleiste «cleared»
    incidents.correlate(db, [])
    row = _incident(db)
    assert row["status"] == "new" and not row["active"] and row["cleared_at"] is not None
    # erneut ausgelöst und verschärft: derselbe Vorfall
    incidents.correlate(db, [_threat(severity="critical")])
    row = _incident(db)
    assert row["active"] and row["trigger_count"] == 2 and row["severity"] == "critical"
    assert _kinds(db, row["id"]) == ["triggered", "cleared", "retriggered", "escalated"]
    assert db.scalar(text("SELECT count(*) FROM security_incident WHERE rule_key LIKE 'auth:spraying:abc%'")) == 1


def test_closed_incident_reopens_only_with_a_new_event(db):
    owner = _admin(db)
    burst = datetime.now(UTC) - timedelta(minutes=5)
    incidents.correlate(db, [_threat(last_at=burst)])
    row = _incident(db)
    incidents.set_status(db, row["id"], "resolved", admin_id=owner.admin_id)
    # derselbe Ausbruch (Ereignis vor dem Abschluss) eröffnet keinen neuen Vorfall
    incidents.correlate(db, [_threat(last_at=burst)])
    assert db.scalar(text("SELECT count(*) FROM security_incident")) == 1
    # neues Ereignis nach dem Abschluss: neuer Vorfall
    incidents.correlate(db, [_threat(last_at=datetime.now(UTC) + timedelta(seconds=1))])
    assert db.scalar(text("SELECT count(*) FROM security_incident")) == 2
    # Wiederöffnen des alten geht jetzt nicht (genau ein offener je Schlüssel)
    with pytest.raises(incidents.IncidentConflict):
        incidents.set_status(db, row["id"], "in_progress", admin_id=owner.admin_id)


def test_monitor_tick_correlates_and_survives_detection_errors(db, monkeypatch):
    from app.services import system_alert_service

    monkeypatch.setattr(system_alert_service, "_auth_threats", lambda db: [_threat()])
    system_alert_service.evaluate_and_notify(db, None)
    assert _incident(db)["status"] == "new"
    # Erkennung fehlgeschlagen (None): Vorfälle klingen nicht scheinbar ab
    monkeypatch.setattr(system_alert_service, "_auth_threats", lambda db: None)
    system_alert_service.evaluate_and_notify(db, None)
    assert _incident(db)["active"]


def test_tenant_rule_links_tenant_and_is_deleted_with_it(db):
    tenant = make_tenant(db, f"Verein {uuid.uuid4().hex[:6]}")
    incidents.correlate(db, [_threat(rule="tenant", subject=str(tenant.id))])
    row = _incident(db, f"auth:tenant:{tenant.id}")
    assert row["tenant_id"] == tenant.id
    db.execute(text("DELETE FROM tenant WHERE id = :id"), {"id": tenant.id})
    assert db.scalar(text("SELECT count(*) FROM security_incident WHERE id = :id"), {"id": row["id"]}) == 0
    assert db.scalar(text("SELECT count(*) FROM security_incident_activity WHERE incident_id = :id"), {"id": row["id"]}) == 0


# ── Aufbewahrung ─────────────────────────────────────────────────────────────────────────


def test_retention_deletes_incidents_365_days_after_last_activity(db):
    incidents.correlate(db, [_threat(), _threat(subject="ffff00001111")])
    old = _incident(db)
    db.execute(
        text("UPDATE security_incident SET updated_at = now() - interval '366 days', last_triggered_at = now() - interval '366 days' WHERE id = :id"),
        {"id": old["id"]},
    )
    assert incidents.purge(db, retention_days=365) == 1
    assert db.scalar(text("SELECT count(*) FROM security_incident")) == 1
    assert db.scalar(text("SELECT count(*) FROM security_incident_activity WHERE incident_id = :id"), {"id": old["id"]}) == 0


def test_retention_job_is_registered():
    from app.core.background_loops import BACKGROUND_LOCK_IDS
    from app.core.job_registry import JOB_DEFINITIONS

    assert BACKGROUND_LOCK_IDS["security_incident_retention"] == 202600071
    assert any(job.name == "security_incident_retention" for job in JOB_DEFINITIONS)


# ── Rechte, Passkey, Audit ───────────────────────────────────────────────────────────────


def test_only_owner_reads_and_changes_incidents(db):
    incidents.correlate(db, [_threat()])
    incident_id = _incident(db)["id"]
    support = _client(db, _admin(db, "support"))
    for path in ("/incidents", "/incidents/stats", f"/incidents/{incident_id}", "/situation"):
        assert support.get(f"/api/admin/auth-security{path}").status_code == 403, path
    for path, body in (("status", {"status": "resolved"}), ("assign", {"admin_id": None}), ("notes", {"note": "x"}),
                       ("block", {"minutes": 5, "reason": "Test"})):
        assert support.post(f"/api/admin/auth-security/incidents/{incident_id}/{path}", json=body).status_code == 403, path
    owner = _client(db, _admin(db))
    assert owner.get(f"/api/admin/auth-security/incidents/{incident_id}").status_code == 200
    assert owner.get("/api/admin/auth-security/incidents/999999999").status_code == 404
    assert owner.get("/api/admin/auth-security/incidents/abc").status_code == 422


def test_incident_mutations_need_step_up(db):
    incidents.correlate(db, [_threat()])
    incident_id = _incident(db)["id"]
    client = _client(db, _admin(db), step_up=False)
    for path, body in (("status", {"status": "resolved"}), ("assign", {"admin_id": None}), ("notes", {"note": "x"}),
                       ("block", {"minutes": 5, "reason": "Test"})):
        response = client.post(f"/api/admin/auth-security/incidents/{incident_id}/{path}", json=body)
        assert response.status_code == 403 and response.json()["detail"]["code"] == "admin_step_up_required", path
    assert _incident(db)["status"] == "new"


def test_take_over_status_note_and_audit(db):
    owner = _admin(db)
    other = _admin(db)
    support = _admin(db, "support")
    incidents.correlate(db, [_threat()])
    incident_id = _incident(db)["id"]
    client = _client(db, owner)

    # Übernehmen: zuständig + «In Bearbeitung», Zeitpunkt der Übernahme gesetzt
    response = client.post(f"/api/admin/auth-security/incidents/{incident_id}/assign", json={"admin_id": str(owner.admin_public_id)})
    assert response.status_code == 200, response.text
    row = _incident(db)
    assert row["status"] == "in_progress" and row["assignee_admin_id"] == owner.admin_id and row["acknowledged_at"] is not None
    assert client.post(f"/api/admin/auth-security/incidents/{incident_id}/assign", json={"admin_id": str(owner.admin_public_id)}).status_code == 409
    # nur aktive owner sind zuweisbar
    assert client.post(f"/api/admin/auth-security/incidents/{incident_id}/assign", json={"admin_id": str(support.admin_public_id)}).status_code == 404
    assert client.post(f"/api/admin/auth-security/incidents/{incident_id}/assign", json={"admin_id": str(other.admin_public_id)}).status_code == 200

    note = "Hosting-Netz, beobachte bis 11 Uhr"
    assert client.post(f"/api/admin/auth-security/incidents/{incident_id}/notes", json={"note": note}).status_code == 201
    assert client.post(f"/api/admin/auth-security/incidents/{incident_id}/notes", json={"note": "   "}).status_code == 422
    response = client.post(f"/api/admin/auth-security/incidents/{incident_id}/status", json={"status": "false_positive", "note": "Vereinsabend"})
    assert response.status_code == 200, response.text
    assert client.post(f"/api/admin/auth-security/incidents/{incident_id}/status", json={"status": "false_positive"}).status_code == 409
    assert client.post(f"/api/admin/auth-security/incidents/{incident_id}/status", json={"status": "kaputt"}).status_code == 422
    # abgeschlossen: keine Zuweisung mehr
    assert client.post(f"/api/admin/auth-security/incidents/{incident_id}/assign", json={"admin_id": None}).status_code == 409

    detail = client.get(f"/api/admin/auth-security/incidents/{incident_id}").json()
    assert detail["status"] == "false_positive" and detail["closed_at"]
    assert [item["note"] for item in detail["notes"]] == [note, "Vereinsabend"]
    assert [item["type"] for item in detail["timeline"] if item["kind"] == "activity"] == ["triggered", "assigned", "status", "assigned", "status"]

    assigned = _audit(db, "admin.security_incident_assigned")
    assert len(assigned) == 2 and assigned[0]["details"]["status_changed"] is True and assigned[0]["entity_type"] == "security_incident"
    notes = _audit(db, "admin.security_incident_note")
    assert notes[0]["details"] == {"incident": incident_id, "length": len(note)}
    status = _audit(db, "admin.security_incident_status")
    assert status[0]["details"] == {"incident": incident_id, "from": "in_progress", "to": "false_positive", "with_note": True}
    # Notiztexte stehen nicht im Audit-Log
    assert note not in str(notes + status + assigned) and "Vereinsabend" not in str(status)

    stats = client.get("/api/admin/auth-security/incidents/stats").json()
    assert stats["false_positives"] == 1 and stats["false_positive_rate"] == 1.0 and stats["mtta_seconds"] is not None


def test_list_filters_counts_and_search(db):
    owner = _admin(db)
    incidents.correlate(db, [_threat(), _threat(subject="ffff00001111", severity="critical"), _threat(rule="limiter", subject=None, severity="critical")])
    mine = _incident(db)["id"]
    incidents.assign(db, mine, owner.admin_public_id, admin_id=owner.admin_id)
    client = _client(db, owner)
    body = client.get("/api/admin/auth-security/incidents").json()
    assert body["counts"] == {"open": 3, "new": 2, "in_progress": 1, "closed": 0, "all": 3}
    # kritische zuerst, Verlauf mit 12 Abschnitten
    assert [item["severity"] for item in body["items"]][:2] == ["critical", "critical"] and len(body["items"][0]["spark"]) == 12
    assert client.get("/api/admin/auth-security/incidents?assignee=me").json()["total"] == 1
    assert client.get("/api/admin/auth-security/incidents?assignee=none").json()["total"] == 2
    assert client.get("/api/admin/auth-security/incidents?severity=critical").json()["total"] == 2
    assert client.get("/api/admin/auth-security/incidents?status=new").json()["total"] == 2
    assert client.get("/api/admin/auth-security/incidents?q=ffff0000").json()["total"] == 1
    assert client.get(f"/api/admin/auth-security/incidents?q=INC-{mine:04d}").json()["items"][0]["id"] == mine
    assert client.get("/api/admin/auth-security/incidents?q=limiter").json()["total"] == 1
    assert client.get("/api/admin/auth-security/incidents?q=a%27%20OR").status_code == 422


# ── Detail und Netzsperre ────────────────────────────────────────────────────────────────


def _failure(db, net: str, subject: str, *, tenant_id=None, minutes_ago=1, outcome="failure", reasons=("new_device",)):
    db.execute(
        text(
            "INSERT INTO auth_event (event_type, outcome, actor_kind, subject_hash, src_net_hash, src_country, tenant_id, ts, risk_score, "
            "risk_reasons, details) VALUES ('login.password', :outcome, 'anonymous', :subject, :net, 'NL', :tenant, "
            "now() - make_interval(mins => :ago), 35, :reasons, '{\"weights\": {\"new_device\": 10}}'::jsonb)"
        ),
        {"subject": subject, "net": net, "tenant": tenant_id, "ago": minutes_ago, "outcome": outcome, "reasons": list(reasons)},
    )


def test_detail_shows_facts_participants_and_blocks_the_network(db):
    tenant = make_tenant(db, f"Verein {uuid.uuid4().hex[:6]}")
    net = NET
    for index in range(4):
        _failure(db, net, f"{index:x}" * 32, tenant_id=tenant.id)
    _failure(db, net, "e" * 32, outcome="blocked")
    _failure(db, "9" * 32, "f" * 32)   # anderes Netz: nicht im Vorfall
    incidents.correlate(db, [_threat(subject=net[:12])])
    incident_id = _incident(db, "auth:spraying:" + net[:12])["id"]
    owner = _admin(db)
    client = _client(db, owner)
    detail = client.get(f"/api/admin/auth-security/incidents/{incident_id}").json()
    assert detail["facts"]["failures"] == 4 and detail["facts"]["blocked"] == 1 and detail["facts"]["accounts"] == 5
    assert detail["stage"] == 4 and detail["can_block"] and detail["event_filter"] == {"net": net[:12]}
    assert detail["participants"]["networks"][0]["key"] == net[:12] and len(detail["participants"]["networks"]) == 1
    assert detail["participants"]["tenants"][0]["name"] == tenant.name
    assert detail["reasons"][0] == {"code": "new_device", "count": 5, "weight": 10}
    # nur gekürzte Pseudonyme in der Antwort
    assert net not in str(detail) and "0" * 32 not in str(detail) and "e" * 32 not in str(detail)

    response = client.post(f"/api/admin/auth-security/incidents/{incident_id}/block", json={"minutes": 30, "reason": "Spraying"})
    assert response.status_code == 201, response.text
    block = blocks.get(net)
    assert block.incident_id == incident_id and block.stage == 5
    assert "block" in _kinds(db, incident_id)
    assert _audit(db, "admin.auth_block_set")[-1]["details"]["incident"] == incident_id
    assert client.get(f"/api/admin/auth-security/incidents/{incident_id}").json()["stage"] == 5


def test_block_only_for_network_incidents(db):
    incidents.correlate(db, [_threat(rule="limiter", subject=None, severity="critical")])
    incident_id = _incident(db, "auth:limiter")["id"]
    response = _client(db, _admin(db)).post(f"/api/admin/auth-security/incidents/{incident_id}/block", json={"minutes": 5, "reason": "Test"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "no_network"


# ── Lagebild ─────────────────────────────────────────────────────────────────────────────


def test_situation_with_real_counts_and_posture(db, monkeypatch):
    _failure(db, NET, "a" * 32)
    client = _client(db, _admin(db))
    monkeypatch.setattr(read_service, "_detect", lambda db: ([], {}))
    body = client.get("/api/admin/auth-security/situation?range=24h").json()
    assert body["posture"]["level"] == "calm"
    assert len(body["points"]) == 48 and body["bucket_minutes"] == 30
    assert body["totals"]["failures"] >= 1 and sum(cell["count"] for cell in body["heatmap"]) >= 1
    assert any(country["code"] == "NL" for country in body["countries"])
    assert all(len(item["net"]) == 12 for item in body["networks"])
    assert len(client.get("/api/admin/auth-security/situation?range=7d").json()["points"]) == 56
    assert client.get("/api/admin/auth-security/situation?range=30d").status_code == 422

    situation.clear_cache()
    incidents.correlate(db, [_threat(severity="critical")])
    body = client.get("/api/admin/auth-security/situation?range=24h").json()
    assert body["posture"]["level"] == "attack" and body["markers"][0]["severity"] == "critical"
    situation.clear_cache()
    monkeypatch.setattr(read_service, "_detect", lambda db: ([{"rule": "stuffing"}], {}))
    assert client.get("/api/admin/auth-security/situation?range=24h").json()["posture"]["level"] == "attack_mode"


def test_nav_badge_counts_new_incidents(db):
    from app.services import admin_overview_service

    incidents.correlate(db, [_threat(), _threat(subject="ffff00001111")])
    assert incidents.open_new_count(db) == 2
    admin_overview_service.invalidate_nav_counts()
    assert admin_overview_service.nav_counts(db, owner=True)["security_alerts"] == 2
    admin_overview_service.invalidate_nav_counts()
