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
from app.auth_security import blocks, read_service, threats
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
    monkeypatch.setattr(read_service, "_alerts_cache", None)
    monkeypatch.setattr(read_service, "_series_cache", {})
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


# ── Ereignisse ─────────────────────────────────────────────────────────────────────────────


def _hex(length: int = 32) -> str:
    return (uuid.uuid4().hex + uuid.uuid4().hex)[:length]


def _insert_event(db, *, minutes_ago: float = 1, **values) -> uuid.UUID:
    values = {"event_type": "login.password", "outcome": "failure", "actor_kind": "anonymous", **values}
    columns = ", ".join(values)
    params = ", ".join(f":{key}" if key != "details" else "CAST(:details AS jsonb)" for key in values)
    return db.execute(
        text(f"INSERT INTO auth_event (ts, {columns}) VALUES (now() - make_interval(secs => :ago), {params}) RETURNING event_id"),  # sql-ok: Spaltennamen aus dem Test
        {**values, "ago": minutes_ago * 60},
    ).scalar()


@pytest.fixture
def owner_client(db):
    from app.auth_security import event_query

    event_query.clear_cache()
    return _client(db, _admin(db))


def test_event_filters_by_prefixes_country_type_outcome_and_tenant(db, owner_client):
    from tests.factories import make_tenant

    tenant = make_tenant(db, "Ereignis Verein")
    subject, net, device = _hex(), _hex(16), _hex()
    _insert_event(db, subject_hash=subject, src_net_hash=net, device_hash=device, src_country="NL", tenant_id=tenant.id)
    _insert_event(db, subject_hash=subject, src_net_hash=_hex(16), outcome="blocked", event_type="login.locked")
    _insert_event(db, subject_hash=_hex(), src_net_hash=net, outcome="success", event_type="login.success", minutes_ago=60 * 30)

    def items(**query):
        response = owner_client.get("/api/admin/auth-security/events", params=query)
        assert response.status_code == 200, response.text
        return response.json()["items"]

    assert len(items(subject=subject[:12])) == 2
    assert items(subject=subject[:12])[0]["subject_hash"] == subject[:12]   # nur gekürzt
    assert len(items(net=net[:12])) == 1                                   # 30 h alt: ausserhalb 24 h
    assert len(items(net=net[:12], range="7d")) == 2
    assert len(items(device=device[:8])) == 1
    assert len(items(subject=subject[:12], country="NL")) == 1
    assert len(items(subject=subject[:12], outcome="blocked")) == 1
    assert len(items(subject=subject[:12], event_type="login.locked")) == 1
    row = items(subject=subject[:12], tenant_id=str(tenant.public_id))
    assert len(row) == 1 and row[0]["tenant_name"] == "Ereignis Verein" and row[0]["tenant_id"] == str(tenant.public_id)
    assert owner_client.get("/api/admin/auth-security/events", params={"tenant_id": str(uuid.uuid4())}).status_code == 404
    for bad in ({"range": "30d"}, {"subject": "XYZ1"}, {"net": "ab"}, {"country": "nl"}, {"event_type": "erfunden"}, {"cursor": "kaputt"}):
        assert owner_client.get("/api/admin/auth-security/events", params=bad).status_code == 422, bad


def test_event_keyset_pagination_is_complete_and_disjoint(db, owner_client):
    subject = _hex()
    for index in range(5):
        _insert_event(db, subject_hash=subject, minutes_ago=index + 1)
    seen, cursor = [], None
    for _ in range(5):
        params = {"subject": subject[:16], "limit": 2, **({"cursor": cursor} if cursor else {})}
        page = owner_client.get("/api/admin/auth-security/events", params=params).json()
        seen += [item["event_id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5 and len(set(seen)) == 5


def test_event_groups_and_histogram(db, owner_client):
    net = _hex(16)
    for outcome in ("failure", "failure", "blocked"):
        _insert_event(db, subject_hash=_hex(), src_net_hash=net, outcome=outcome, risk_score=40)
    (group,) = owner_client.get("/api/admin/auth-security/events/groups", params={"by": "net", "net": net[:12]}).json()
    assert group["key"] == net[:12] and group["events"] == 3 and group["failure"] == 2 and group["distinct_other"] == 3 and group["max_risk"] == 40
    histogram = owner_client.get("/api/admin/auth-security/events/histogram", params={"net": net[:12], "outcome": "blocked"}).json()
    assert len(histogram["buckets"]) == 48
    assert histogram["outcome_counts"]["failure"] == 2 and histogram["outcome_counts"]["blocked"] == 1   # ohne Ergebnis-Filter
    assert sum(bucket["failure"] for bucket in histogram["buckets"]) == 0                                # Balken mit Filter
    assert owner_client.get("/api/admin/auth-security/events/groups", params={"by": "device"}).status_code == 422


def test_event_detail_with_weights_and_related_counts(db, owner_client):
    from app.auth_security import events

    subject, net = _hex(), _hex(16)
    _insert_event(db, subject_hash=subject, src_net_hash=net, src_country="CH")
    event_id = _insert_event(
        db, subject_hash=subject, src_net_hash=net, src_country="CH", risk_score=35, risk_reasons=["new_device", "spraying"],
        details=json.dumps({"weights": {"new_device": 10, "spraying": 25}, "reason": "password"}),
    )
    detail = owner_client.get(f"/api/admin/auth-security/events/{event_id}").json()
    assert detail["reasons"] == [{"code": "new_device", "weight": 10}, {"code": "spraying", "weight": 25}]
    assert detail["has_weights"] and "weights" not in detail["details"]
    assert detail["related"]["net"] == 2 and detail["related"]["subject"] == 2 and detail["related"]["country"] >= 2
    assert detail["can_block"] and len(detail["src_net_hash"]) == 12
    assert owner_client.get(f"/api/admin/auth-security/events/{uuid.uuid4()}").status_code == 404
    # Neue Ereignisse speichern die Gewichte selbst (events.record)
    marker = _hex()
    events.record(event_type="login.password", outcome="failure", subject_hash=marker, risk_score=20, risk_reasons=["new_device"],
                  risk_weights={"new_device": 10, "kaputt grund": 5, "x": True})
    db.expire_all()
    stored = db.scalars(select(AuthEvent).where(AuthEvent.subject_hash == marker)).one()
    assert stored.details["weights"] == {"new_device": 10}


def test_block_event_source_blocks_the_net_fingerprint(db, owner_client):
    fingerprint = net_hash("198.51.100.50")
    event_id = _insert_event(db, subject_hash=_hex(), src_net_hash=fingerprint)
    response = owner_client.post(f"/api/admin/auth-security/events/{event_id}/block", json={"minutes": 60, "reason": "Spraying aus Netz"})
    assert response.status_code == 201, response.text
    block = blocks.is_blocked("198.51.100.61")
    assert block is not None and block.scope == "net_fp" and block.manual
    audit = db.execute(text("SELECT details_json FROM audit_log WHERE action = 'admin.auth_block_set' ORDER BY id DESC LIMIT 1")).scalar()
    assert audit["source"] == "event" and audit["event_id"] == str(event_id) and audit["subject"] == fingerprint[:12]
    (event,) = _block_events(db, fingerprint)
    assert event.src_net_hash == fingerprint   # Sperr-Ereignis erscheint beim Netz-Filter

    admin_event = _insert_event(db, actor_kind="admin", src_net_hash=net_hash("198.51.102.1"), event_type="admin.login.password")
    assert owner_client.post(f"/api/admin/auth-security/events/{admin_event}/block", json={"minutes": 5, "reason": "nicht erlaubt"}).status_code == 422
    no_net = _insert_event(db, subject_hash=_hex())
    assert owner_client.post(f"/api/admin/auth-security/events/{no_net}/block", json={"minutes": 5, "reason": "ohne Netz"}).status_code == 422
    assert owner_client.post(f"/api/admin/auth-security/events/{uuid.uuid4()}/block", json={"minutes": 5, "reason": "gibt es nicht"}).status_code == 404
    assert owner_client.post(f"/api/admin/auth-security/events/{event_id}/block", json={"minutes": 5, "reason": ""}).status_code == 422


def test_support_cannot_read_events_or_block_sources(db):
    event_id = _insert_event(db, subject_hash=_hex(), src_net_hash=net_hash("198.51.100.70"))
    client = _client(db, _admin(db, "support"))
    for path in ("/events", "/events/histogram", "/events/groups?by=net", f"/events/{event_id}"):
        assert client.get(f"/api/admin/auth-security{path}").status_code == 403, path
    assert client.get("/api/admin/auth-security/events", params={"tenant_id": str(uuid.uuid4())}).status_code == 403   # kein 404-Orakel
    assert client.post(f"/api/admin/auth-security/events/{event_id}/block", json={"minutes": 5, "reason": "nicht erlaubt"}).status_code == 403
    assert blocks.is_blocked("198.51.100.70") is None


# ── Alarmregeln ────────────────────────────────────────────────────────────────────────────


def _rule(rules: list[dict], name: str) -> dict:
    return next(item for item in rules if item["rule"] == name)


def test_alert_rules_show_values_below_threshold_and_fire(db, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_alert_spraying_accounts", 4)
    net = _hex(16)
    for _ in range(3):
        _insert_event(db, subject_hash=_hex(), src_net_hash=net, minutes_ago=2)
    client = _client(db, _admin(db))
    rules = client.get("/api/admin/auth-security/alert-rules").json()
    assert {item["rule"] for item in rules} == set(threats.RULE_WINDOW_MINUTES)
    spraying = _rule(rules, "spraying")
    assert spraying["value"] >= 3 and spraying["threshold"] == 4 and spraying["fired"] == 0
    assert spraying["state"] in ("near", "quiet") and spraying["settings"] == {"auth_alert_spraying_accounts": 4}
    assert _rule(rules, "blocks")["comparator"] == ">"

    _insert_event(db, subject_hash=_hex(), src_net_hash=net, minutes_ago=1)
    monkeypatch.setattr(read_service, "_alerts_cache", None)
    spraying = _rule(client.get("/api/admin/auth-security/alert-rules").json(), "spraying")
    assert spraying["state"] == "fired" and spraying["fired"] >= 1


def test_alert_rule_triggers_from_monitor_history_and_series(db):
    db.execute(text(
        "INSERT INTO system_health_event (kind, subject, reason, severity, title, message, created_at) VALUES "
        "('problem', 'auth:network:3f9a1c07be42abcd', 'network', 'warning', 't', 'm', now() - interval '2 days'), "
        "('resolved', 'auth:network:3f9a1c07be42abcd', 'network', 'info', 't', 'm', now() - interval '2 days'), "
        "('problem', 'auth:network_x', 'x', 'warning', 't', 'm', now() - interval '40 days')"
    ))
    client = _client(db, _admin(db))
    network = _rule(client.get("/api/admin/auth-security/alert-rules").json(), "network")
    assert network["triggers_30d"] >= 1 and len(network["daily_30d"]) == 30 and network["daily_30d"][-3] >= 1
    assert network["recent"][0]["subject"] == "3f9a1c07be42"
    _insert_event(db, subject_hash=_hex(), src_net_hash=_hex(16), minutes_ago=30)
    series = client.get("/api/admin/auth-security/alert-rules/account_attack/series").json()
    assert series["bucket_minutes"] == 15 and 95 <= len(series["points"]) <= 97
    assert any(point["value"] >= 1 for point in series["points"])
    assert client.get("/api/admin/auth-security/alert-rules/limiter/series").json()["bucket_minutes"] == 15
    assert client.get("/api/admin/auth-security/alert-rules/erfunden/series").status_code == 422


def test_alert_rules_are_owner_only(db):
    client = _client(db, _admin(db, "support"))
    assert client.get("/api/admin/auth-security/alert-rules").status_code == 403
    assert client.get("/api/admin/auth-security/alert-rules/spraying/series").status_code == 403
