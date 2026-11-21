"""Plattform-Admin 1.5.1: Zurücksetzungslink statt Passwort, Admin-Liste mit Passkeys/letzter
Anmeldung, Warnungen quittieren, Security-Export, Subjekt-Auflösung, Audit-Filter, Einstellungs-
seiten, Betriebsverläufe und Mandanten-Tabs (Features, Nutzung, Sicherheit).

Passkey-Bestätigungen prüft test_admin_step_up.py (Inventar); hier sind sie per Override erfüllt."""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.api.routes import admin as admin_routes
from app.api.routes import admin_auth_security, admin_console
from app.auth_security import read_service
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.admin_step_up import PURPOSES, require_step_up
from app.core.auth_pseudonym import subject_hash
from app.core.db import get_db
from app.models import AccountToken, PlatformAdmin
from app.services import export_crypto
from app.services.notification_settings_service import NotificationSettingsService
from tests.factories import make_app_user, make_tenant

PASSWORD = f"Kiesel-Tanne-Wolke-{secrets.randbelow(90) + 10}"


def _admin(db, role: str = "owner") -> CurrentAdmin:
    admin = PlatformAdmin(email=f"c151-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name=f"Admin {role}", role=role)
    db.add(admin)
    db.flush()
    return CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name, role=role)


def _client(db, actor: CurrentAdmin) -> TestClient:
    app = FastAPI()
    for module in (admin_routes, admin_auth_security, admin_console):
        app.include_router(module.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: actor
    for purpose in PURPOSES:
        app.dependency_overrides[require_step_up(purpose)] = lambda: actor
    return TestClient(app)


@pytest.fixture
def mail_ready(db):
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = True
    row.smtp_host = "smtp.example.com"
    row.email_from_address = "noreply@example.com"
    row.email_link_base_url = "https://app.example.com"
    db.flush()
    return row


@pytest.fixture(autouse=True)
def _no_alert_cache(monkeypatch):
    monkeypatch.setattr(read_service, "_alerts_cache", None)


# ── Zurücksetzungslink statt Passwort ─────────────────────────────────────────────────────


def test_admin_cannot_set_passwords_any_more(db, mail_ready):
    owner = _admin(db)
    client = _client(db, owner)
    tenant = make_tenant(db, "Link Verein")
    user = make_app_user(db, "link@example.com", tenant_id=tenant.id)
    patch = client.patch(f"/api/admin/users/{user.public_id}", json={"password": PASSWORD})
    assert patch.status_code == 422
    create = client.post("/api/admin/users", json={"tenant_id": str(tenant.public_id), "display_name": "Neu", "password": PASSWORD})
    assert create.status_code == 422
    create = client.post("/api/admin/users", json={"tenant_id": str(tenant.public_id), "display_name": "Neu", "login_enabled": True})
    assert create.status_code == 422


def test_password_reset_link_for_login_account(db, mail_ready):
    owner = _admin(db)
    client = _client(db, owner)
    tenant = make_tenant(db, "Reset Verein")
    user = make_app_user(db, "reset@example.com", tenant_id=tenant.id)
    response = client.post(f"/api/admin/users/{user.public_id}/password-reset")
    assert response.status_code == 200, response.text
    assert response.json() == {"purpose": "password_reset"}
    tokens = list(db.scalars(select(AccountToken).where(AccountToken.user_id == user.id)))
    assert [token.purpose for token in tokens] == ["password_reset"]
    # Passwort bleibt unverändert, der Admin sieht keinen Link
    assert "token" not in response.text
    action = db.execute(text("SELECT action FROM audit_log WHERE entity_id = :id AND action LIKE 'admin.user_%' ORDER BY id DESC LIMIT 1"), {"id": user.id}).scalar()
    assert action == "admin.user_password_reset_sent"


def test_invite_for_account_without_login_and_on_create(db, mail_ready):
    owner = _admin(db)
    client = _client(db, owner)
    tenant = make_tenant(db, "Invite Verein")
    created = client.post("/api/admin/users", json={
        "tenant_id": str(tenant.public_id), "display_name": "Neue Person", "email": "neu-invite@example.com", "send_invite": True,
    })
    assert created.status_code == 201, created.text
    assert created.json()["login_enabled"] is False
    internal = db.execute(text("SELECT id FROM app_user WHERE public_id = :id"), {"id": created.json()["id"]}).scalar()
    purposes = [token.purpose for token in db.scalars(select(AccountToken).where(AccountToken.user_id == internal))]
    assert purposes == ["invite"]
    # Ohne E-Mail keine Einladung (vor dem Anlegen geprüft)
    no_mail = client.post("/api/admin/users", json={"tenant_id": str(tenant.public_id), "display_name": "Ohne", "send_invite": True})
    assert no_mail.status_code == 400


def test_password_reset_requires_mail_and_unknown_user_404(db):
    owner = _admin(db)
    client = _client(db, owner)
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = False
    db.flush()
    tenant = make_tenant(db, "Ohne Mail")
    user = make_app_user(db, "ohne-mail@example.com", tenant_id=tenant.id)
    assert client.post(f"/api/admin/users/{user.public_id}/password-reset").status_code == 409
    assert client.post(f"/api/admin/users/{uuid.uuid4()}/password-reset").status_code == 404


def test_support_cannot_send_links(db, mail_ready):
    support = _admin(db, "support")
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: support
    tenant = make_tenant(db, "Support Verein")
    user = make_app_user(db, "support-target@example.com", tenant_id=tenant.id)
    # require_step_up prüft die Rolle vor der Bestätigung
    assert TestClient(app).post(f"/api/admin/users/{user.public_id}/password-reset").status_code == 403


# ── Admin-Liste ────────────────────────────────────────────────────────────────────────────


def test_admin_list_has_passkey_count_and_last_login(db):
    owner = _admin(db)
    db.execute(
        text("INSERT INTO user_mfa_factor (platform_admin_id, factor_type, label, webauthn_credential_id) VALUES (:id, 'webauthn', 'A', :cred)"),
        {"id": owner.admin_id, "cred": uuid.uuid4().hex},
    )
    db.execute(
        text("INSERT INTO auth_event (event_type, outcome, actor_kind, platform_admin_id, ts) VALUES ('admin.login.success', 'success', 'admin', :id, now())"),
        {"id": owner.admin_id},
    )
    items = _client(db, owner).get("/api/admin/admins").json()
    mine = next(item for item in items if item["id"] == str(owner.admin_public_id))
    assert mine["passkey_count"] == 1
    assert mine["last_login_at"] is not None


# ── Warnungen quittieren ───────────────────────────────────────────────────────────────────


def _fake_alert(monkeypatch, key="auth:spraying:abc123def456"):
    alert = {"key": key, "rule": "spraying", "subject": "abc123def456", "severity": "warning", "title": "T", "message": "M"}
    monkeypatch.setattr(read_service, "platform_alerts", lambda db: [dict(alert)])
    return alert


def test_acknowledge_and_reopen_alert(db, monkeypatch):
    owner = _admin(db)
    client = _client(db, owner)
    alert = _fake_alert(monkeypatch)
    assert client.get("/api/admin/auth-security/overview").json()["open_alerts"] == 1
    response = client.post("/api/admin/auth-security/alerts/ack", json={"key": alert["key"], "note": "wird geprüft"})
    assert response.status_code == 200, response.text
    listed = client.get("/api/admin/auth-security/alerts").json()
    assert listed[0]["acknowledged_at"] is not None and listed[0]["acknowledged_by"] == owner.display_name
    overview = client.get("/api/admin/auth-security/overview").json()
    assert overview["open_alerts"] == 0 and overview["acknowledged_alerts"] == 1
    assert client.post("/api/admin/auth-security/alerts/unack", json={"key": alert["key"]}).status_code == 200
    assert client.get("/api/admin/auth-security/overview").json()["open_alerts"] == 1


def test_acknowledge_rejects_inactive_or_foreign_keys(db, monkeypatch):
    client = _client(db, _admin(db))
    _fake_alert(monkeypatch)
    assert client.post("/api/admin/auth-security/alerts/ack", json={"key": "auth:spraying:anderes"}).status_code == 404
    # Nur Anmeldeschutz-Warnungen (keine Systemprobleme quittierbar)
    assert client.post("/api/admin/auth-security/alerts/ack", json={"key": "job:export_cleanup"}).status_code == 422


# ── Export ─────────────────────────────────────────────────────────────────────────────────


def test_security_export_is_encrypted_and_audited(db, tmp_path):
    owner = _admin(db)
    client = _client(db, owner)
    db.execute(text(
        "INSERT INTO auth_event (event_type, outcome, actor_kind, subject_hash, ts) VALUES ('login.password', 'failure', 'anonymous', :hash, now())"
    ), {"hash": "f" * 32})
    today = date.today().isoformat()
    password = secrets.token_urlsafe(16)
    response = client.post("/api/admin/auth-security/export", json={
        "kind": "auth_events", "date_from": today, "date_to": today, "password": password,
    })
    assert response.status_code == 200, response.text
    encrypted = tmp_path / "x.hocxenc"
    encrypted.write_bytes(response.content)
    assert export_crypto.is_encrypted(encrypted)
    plain = tmp_path / "x.jsonl"
    export_crypto.decrypt_file(encrypted, plain, password=password)
    lines = [json.loads(line) for line in plain.read_text().splitlines()]
    assert any(line["subject_hash"] == "f" * 12 for line in lines)
    assert all(len(line["subject_hash"] or "") <= 12 for line in lines)
    details = db.execute(text("SELECT details_json FROM audit_log WHERE action = 'admin.security_exported' ORDER BY id DESC LIMIT 1")).scalar()
    assert details["kind"] == "auth_events" and details["rows"] >= 1


def test_security_export_validates_range_and_password(db):
    client = _client(db, _admin(db))
    base = {"kind": "audit_log", "password": secrets.token_urlsafe(16)}
    assert client.post("/api/admin/auth-security/export", json={**base, "date_from": "2026-01-01", "date_to": "2026-06-01"}).status_code == 422
    assert client.post("/api/admin/auth-security/export", json={**base, "date_from": "2026-02-01", "date_to": "2026-01-01"}).status_code == 422
    assert client.post("/api/admin/auth-security/export", json={**base, "password": "kurz", "date_from": "2026-01-01", "date_to": "2026-01-02"}).status_code == 422


# ── Subjekt-Auflösung ──────────────────────────────────────────────────────────────────────


def _event(db, **values) -> uuid.UUID:
    columns = ", ".join(values)
    params = ", ".join(f":{key}" for key in values)
    return db.execute(text(f"INSERT INTO auth_event (event_type, outcome, actor_kind, {columns}) VALUES ('login.password', 'failure', 'anonymous', {params}) RETURNING event_id"), values).scalar()  # sql-ok: Spaltennamen aus dem Test selbst


def test_resolve_subject_via_event_related_and_hash(db):
    owner = _admin(db)
    client = _client(db, owner)
    tenant = make_tenant(db, "Resolve Verein")
    user = make_app_user(db, "resolve-me@example.com", tenant_id=tenant.id)

    direct = _event(db, actor_user_id=user.id, tenant_id=tenant.id, subject_hash=subject_hash(user.email))
    result = client.post(f"/api/admin/auth-security/events/{direct}/resolve-subject").json()
    assert result["kind"] == "user" and result["via"] == "event" and result["email"] == user.email
    assert result["tenant_id"] == str(tenant.public_id)

    anonymous = _event(db, subject_hash=subject_hash(user.email))
    assert client.post(f"/api/admin/auth-security/events/{anonymous}/resolve-subject").json()["via"] == "related_event"

    db.execute(text("DELETE FROM auth_event WHERE actor_user_id = :id"), {"id": user.id})
    by_hash = client.post(f"/api/admin/auth-security/events/{anonymous}/resolve-subject").json()
    assert by_hash["kind"] == "user" and by_hash["via"] == "hash"

    unknown = _event(db, subject_hash=subject_hash("gibt-es-nicht@example.com"))
    result = client.post(f"/api/admin/auth-security/events/{unknown}/resolve-subject").json()
    assert result == {**result, "kind": "unknown", "email": None, "display_name": None}

    audits = db.execute(text("SELECT details_json, tenant_id FROM audit_log WHERE action = 'admin.security_subject_resolved' ORDER BY id")).all()
    assert len(audits) >= 4
    assert audits[0][1] == tenant.id
    assert client.post(f"/api/admin/auth-security/events/{uuid.uuid4()}/resolve-subject").status_code == 404


# ── Audit-Filter ───────────────────────────────────────────────────────────────────────────


def test_audit_log_filters_by_range_actor_and_entity(db):
    owner = _admin(db)
    client = _client(db, owner)
    db.execute(text(
        "INSERT INTO audit_log (action, actor_email, entity_type, entity_id, created_at) VALUES "
        "('admin.c151_test', :email, 'tenant', 4242, now()), ('admin.c151_test', NULL, 'plan', 7, now() - interval '20 days')"
    ), {"email": owner.email})
    base = "/api/admin/audit-log?action=admin.c151_test"
    assert client.get(base).json()["total"] == 2
    assert client.get(f"{base}&actor_kind=admin&actor_id={owner.admin_public_id}").json()["total"] == 1
    assert client.get(f"{base}&actor_kind=system").json()["total"] == 1
    assert client.get(f"{base}&entity_type=tenant&entity_id=4242").json()["total"] == 1
    today = date.today().isoformat()
    assert client.get(f"{base}&from={today}&to={today}").json()["total"] == 1
    assert client.get(f"{base}&actor_id={owner.admin_public_id}").status_code == 422
    assert client.get(f"{base}&entity_type=DROP%20TABLE").status_code == 422
    options = client.get("/api/admin/audit-log/filter-options").json()
    assert any(item["id"] == str(owner.admin_public_id) for item in options["admins"])


# ── Einstellungen, Betrieb, Mandanten-Tabs ─────────────────────────────────────────────────


def test_settings_have_no_secrets(db):
    owner = _admin(db)
    client = _client(db, owner)
    security = client.get("/api/admin/settings/security").json()
    purposes = {item["purpose"] for item in security["step_up_actions"]}
    assert {"security-export", "user-credentials", "tenant-delete"} <= purposes
    for path in ("/api/admin/settings/integrations", "/api/admin/settings/system"):
        response = client.get(path)
        assert response.status_code == 200, response.text
        body = response.text.lower()
        for word in ("secret_key", "password\":\"", "token\":\"", "access_key"):
            assert word not in body, (path, word)
    system = client.get("/api/admin/settings/system").json()
    assert system["alembic_revision"]


def test_settings_integrations_and_system_owner_only(db):
    support = _admin(db, "support")
    client = _client(db, support)
    assert client.get("/api/admin/settings/security").status_code == 200
    assert client.get("/api/admin/settings/integrations").status_code == 403
    assert client.get("/api/admin/settings/system").status_code == 403
    assert client.get("/api/admin/system-status/history").status_code == 403


def test_system_history_buckets(db):
    db.execute(text("INSERT INTO system_metric_sample (ts, metric, subject, value) VALUES (now(), 'postgres.latency_ms', '', 4), (now(), 'redis.used_mb', '', 12)"))
    data = _client(db, _admin(db)).get("/api/admin/system-status/history?range=24h").json()
    assert data["bucket_minutes"] == 15
    values = {key for point in data["points"] for key in point["values"]}
    assert {"postgres.latency_ms.avg", "redis.used_mb.max"} <= values


def test_tenant_tabs(db):
    owner = _admin(db)
    client = _client(db, owner)
    tenant = make_tenant(db, "Tab Verein")
    db.execute(text("INSERT INTO tenant_metric_daily (tenant_id, day, metric, value) VALUES (:id, current_date - 1, 'logins', 3)"), {"id": tenant.id})
    features = client.get(f"/api/admin/tenants/{tenant.public_id}/features").json()
    assert features and {"code", "access", "source", "enabled_at"} <= set(features[0])
    usage = client.get(f"/api/admin/tenants/{tenant.public_id}/usage?range=30d").json()
    assert usage["totals"].get("logins") == 3
    security = client.get(f"/api/admin/tenants/{tenant.public_id}/security")
    assert security.status_code == 200 and set(security.json()) == {"summary", "warnings", "events"}
    assert client.get(f"/api/admin/tenants/{uuid.uuid4()}/usage").status_code == 404
    support = _client(db, _admin(db, "support"))
    assert support.get(f"/api/admin/tenants/{tenant.public_id}/security").status_code == 403
    assert support.get(f"/api/admin/tenants/{tenant.public_id}/features").status_code == 200


# ── Sicherheitsereignis beim Reset über das Gerätekontingent ───────────────────────────────


@pytest.mark.parametrize("limits, expected", [((True, True), ("info", "address_quota_exhausted")), ((False, True), ("blocked", "device_limit")),
                                               ((True, False), ("blocked", "account_limit"))])
def test_device_quota_reset_records_event(monkeypatch, limits, expected):
    from types import SimpleNamespace

    from app.api.routes import auth as auth_routes
    from app.auth_security import events

    recorded = []
    answers = iter(limits)
    monkeypatch.setattr(auth_routes.account_links, "password_reset_account", lambda db, email: SimpleNamespace(id=1, tenant_id=2))
    monkeypatch.setattr(auth_routes.account_links, "request_password_reset", lambda db, email: None)
    monkeypatch.setattr(auth_routes.devices, "known_device", lambda db, user_id, device_id: SimpleNamespace(id=9))
    monkeypatch.setattr(auth_routes, "within_limit", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(events, "record", lambda **kwargs: recorded.append(kwargs))
    auth_routes._issue_password_reset_from_known_device("x@example.com", "device")
    assert [(item["outcome"], item["details"]["reason"]) for item in recorded] == [expected]
    assert recorded[0]["event_type"] == "reset.request" and recorded[0]["details"]["layer"] == "device"


def test_user_list_filters_by_tenant(db):
    owner = _admin(db)
    client = _client(db, owner)
    tenant = make_tenant(db, "Filter Verein")
    make_app_user(db, "filter-a@example.com", tenant_id=tenant.id)
    other = make_tenant(db, "Anderer Verein")
    make_app_user(db, "filter-b@example.com", tenant_id=other.id)
    page = client.get(f"/api/admin/users?tenant_id={tenant.public_id}&limit=50").json()
    assert {item["email"] for item in page["items"]} == {"filter-a@example.com"}
    assert client.get(f"/api/admin/users?tenant_id={uuid.uuid4()}").status_code == 404


def test_resolve_by_hash_ignores_people_without_login(db):
    """Security-Review M1: eine gleichlautende Adresse ohne Login darf nicht getroffen werden."""
    from app.models import AppUser

    owner = _admin(db)
    client = _client(db, owner)
    other = make_tenant(db, "Unbeteiligt")
    db.add(AppUser(tenant_id=other.id, email="geteilt@example.com", display_name="Ohne Login", login_enabled=False))
    tenant = make_tenant(db, "Beteiligt")
    user = make_app_user(db, "geteilt@example.com", tenant_id=tenant.id)
    db.flush()
    event = _event(db, subject_hash=subject_hash("geteilt@example.com"))
    result = client.post(f"/api/admin/auth-security/events/{event}/resolve-subject").json()
    assert result["kind"] == "user" and result["user_id"] == str(user.public_id)


def test_integration_hosts_never_carry_credentials(db):
    row = NotificationSettingsService().get_row(db)
    row.ntfy_enabled = True
    row.ntfy_server_url = "https://nutzer:geheimes-token@ntfy.example.com"
    row.ntfy_topic = "t"
    db.flush()
    body = _client(db, _admin(db)).get("/api/admin/settings/integrations").text
    assert "geheimes-token" not in body and "nutzer" not in body
