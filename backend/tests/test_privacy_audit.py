"""Datenschutz-Audit PRIV-013/PRIV-022 (Umsetzungsplan Paket 3): Sicherheitsereignisse im Audit-Log,
gehashte Quelle statt IP, Verlauf für Mandanten-Admins, Plattform-Ansicht, Schutz der Tabelle,
Entfernen von E-Mail-Adressen gelöschter Personen und Sicherheitsalarme."""
from __future__ import annotations

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.routes import admin as admin_routes
from app.api.routes.activity import list_activity
from app.core import audit_context
from app.core.admin_security import CurrentAdmin
from app.schemas.user import LoginRequest
from app.services import system_health_service
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.participant_service import ParticipantService
from tests.factories import make_app_user, make_current_user, make_tenant

PASSWORD = "correct horse battery staple"


def _rows(db, action: str):
    return db.execute(text("SELECT * FROM audit_log WHERE action = :a ORDER BY id"), {"a": action}).mappings().all()


@pytest.fixture
def client_ip():
    token = audit_context._client_ip.set("198.51.100.23")
    yield
    audit_context._client_ip.reset(token)


def test_ip_fingerprint_groups_a_network_and_hides_the_address():
    a = audit_context.ip_fingerprint("198.51.100.23")
    assert a == audit_context.ip_fingerprint("198.51.100.200")
    assert a != audit_context.ip_fingerprint("198.51.101.23")
    assert "198" not in a and len(a) == 16
    assert audit_context.ip_fingerprint("2001:db8:1:2::1") == audit_context.ip_fingerprint("2001:db8:1:ffff::1")
    assert audit_context.ip_fingerprint(None) is None


def test_failed_login_is_logged_without_the_entered_email(db, client_ip):
    tenant = make_tenant(db)
    user = make_app_user(db, email="anmeldung@example.com", password=PASSWORD, tenant_id=tenant.id)

    with pytest.raises(HTTPException):
        AuthService().login(db, Response(), LoginRequest(email="anmeldung@example.com", password="falsch-falsch-falsch"))
    with pytest.raises(HTTPException):
        AuthService().login(db, Response(), LoginRequest(email="niemand@example.com", password="falsch-falsch-falsch"))

    rows = [row for row in _rows(db, "user.login_failed") if row["tenant_id"] in (tenant.id, None)][-2:]
    known, unknown = rows
    assert known["actor_user_id"] == user.id and known["outcome"] == "failure"
    assert known["ip_hash"] == audit_context.ip_fingerprint("198.51.100.23")
    assert unknown["actor_user_id"] is None and unknown["details_json"] == {"reason": "unknown_account"}
    assert all(row["actor_email"] is None for row in rows)
    assert "niemand" not in str(unknown)


def _activity(db, user, **filters):
    values = {"category": None, "action": None, "outcome": None, "date_from": None, "date_to": None, "actor": None, "with_options": True}
    values.update(filters)
    return list_activity(**values, limit=50, offset=0, db=db, user=user)


def test_activity_shows_only_own_tenant_and_requires_admin(db):
    tenant = make_tenant(db, "Verlauf")
    other = make_tenant(db, "Fremd")
    admin = make_app_user(db, email="verlauf-admin@example.com", tenant_id=tenant.id, role_code="admin")
    audit = AuditService()
    audit.log(db, action="protocol.deleted", tenant_id=tenant.id, actor_user_id=admin.id)
    audit.log(db, action="admin.tenant_users_viewed", tenant_id=tenant.id, actor_email="support@hocx.invalid")
    audit.log(db, action="protocol.deleted", tenant_id=other.id)

    page = _activity(db, make_current_user(tenant.id, role="admin", user_id=admin.id))

    assert [(item.action, item.actor_kind) for item in page.items] == [("admin.tenant_users_viewed", "platform"), ("protocol.deleted", "user")]
    assert page.items[1].actor_name == admin.display_name
    assert "support@hocx.invalid" not in page.model_dump_json()
    with pytest.raises(HTTPException) as denied:
        _activity(db, make_current_user(tenant.id, role="writer"))
    assert denied.value.status_code == 403


def test_activity_filters_every_column(db):
    """Verlauf: Filter je Spalte (Zeitpunkt, Vorgang, Von, Ergebnis) plus Auswahllisten."""
    from datetime import date, timedelta

    tenant = make_tenant(db, "Verlauf Filter")
    admin = make_app_user(db, email="filter-admin@example.com", tenant_id=tenant.id, role_code="admin")
    other = make_app_user(db, email="filter-andere@example.com", tenant_id=tenant.id)
    audit = AuditService()
    audit.log(db, action="protocol.deleted", tenant_id=tenant.id, actor_user_id=admin.id)
    audit.log(db, action="user.login", tenant_id=tenant.id, actor_user_id=other.id)
    audit.log(db, action="user.login", tenant_id=tenant.id, actor_user_id=other.id, outcome="failure")
    audit.log(db, action="admin.tenant_users_viewed", tenant_id=tenant.id, actor_email="support@hocx.invalid")
    db.execute(text("UPDATE audit_log SET created_at = now() - interval '10 days' WHERE tenant_id = :t AND action = 'protocol.deleted'"), {"t": tenant.id})
    db.flush()
    viewer = make_current_user(tenant.id, role="admin", user_id=admin.id)

    def actions(**filters):
        return sorted(item.action for item in _activity(db, viewer, **filters).items)

    assert actions(action="user.login") == ["user.login", "user.login"]
    assert actions(outcome="failure") == ["user.login"]
    assert actions(actor=str(other.public_id)) == ["user.login", "user.login"]
    assert actions(actor="platform") == ["admin.tenant_users_viewed"]
    assert actions(date_to=date.today() - timedelta(days=5)) == ["protocol.deleted"]
    # «activity.viewed»: das Öffnen des Verlaufs (erster Aufruf oben) steht selbst darin
    assert actions(date_from=date.today() - timedelta(days=1)) == ["activity.viewed", "admin.tenant_users_viewed", "user.login", "user.login"]
    assert actions(actor="kein-uuid") == []

    page = _activity(db, viewer)
    assert set(page.actions) >= {"protocol.deleted", "user.login", "admin.tenant_users_viewed"}
    assert {actor.key for actor in page.actors} == {str(admin.public_id), str(other.public_id), "platform"}


def test_activity_hides_successful_logins_after_30_days(db):
    """Datensparsamkeit: wer wann angemeldet war, sieht der Verein nur 30 Tage; Fehlversuche und
    Änderungen bleiben länger sichtbar."""
    tenant = make_tenant(db, "Verlauf Anmeldungen")
    admin = make_app_user(db, email="login-admin@example.com", tenant_id=tenant.id, role_code="admin")
    audit = AuditService()
    for action, outcome in (("user.login", "success"), ("user.login", "failure"), ("protocol.deleted", "success")):
        audit.log(db, action=action, tenant_id=tenant.id, actor_user_id=admin.id, outcome=outcome)
    db.execute(text("UPDATE audit_log SET created_at = now() - interval '31 days' WHERE tenant_id = :t"), {"t": tenant.id})
    audit.log(db, action="user.login", tenant_id=tenant.id, actor_user_id=admin.id)
    db.flush()

    page = _activity(db, make_current_user(tenant.id, role="admin", user_id=admin.id), with_options=False)

    assert sorted((item.action, item.outcome) for item in page.items) == [
        ("protocol.deleted", "success"), ("user.login", "failure"), ("user.login", "success"),
    ]
    assert page.total == 3
    # In der Datenbank (Plattform-Administration) bleibt die alte Anmeldung
    assert db.scalar(text("SELECT count(*) FROM audit_log WHERE tenant_id = :t AND action = 'user.login' AND outcome = 'success'"), {"t": tenant.id}) == 2


def test_opening_the_activity_log_is_itself_logged_once(db):
    tenant = make_tenant(db, "Verlauf geöffnet")
    admin = make_app_user(db, email="viewer-admin@example.com", tenant_id=tenant.id, role_code="admin")
    viewer = make_current_user(tenant.id, role="admin", user_id=admin.id)

    _activity(db, viewer)
    _activity(db, viewer, category="protocol")  # Filterwechsel: kein zweiter Eintrag
    _activity(db, viewer, with_options=False)  # Live-Aktualisierung/Blättern: auch nicht

    viewed = db.execute(
        text("SELECT actor_user_id FROM audit_log WHERE tenant_id = :t AND action = 'activity.viewed'"), {"t": tenant.id}
    ).all()
    assert [row.actor_user_id for row in viewed] == [admin.id]
    assert any(item.action == "activity.viewed" for item in _activity(db, viewer, with_options=False).items)


def test_deleting_a_person_removes_their_email_from_the_audit_log(db):
    tenant = make_tenant(db, "Vergessen")
    make_app_user(db, email="bleibt-admin@example.com", tenant_id=tenant.id, role_code="admin")
    person = make_app_user(db, email="weg@example.com", tenant_id=tenant.id)
    AuditService().log(db, action="user.password_changed", actor=make_current_user(tenant.id, role="reader", user_id=person.id))

    ParticipantService().delete_participant(db, person.id, tenant_id=tenant.id)

    row = db.execute(text("SELECT actor_email, actor_user_id FROM audit_log WHERE action = 'user.password_changed' ORDER BY id DESC LIMIT 1")).one()
    assert row.actor_email is None and row.actor_user_id is None


def test_tenant_with_audit_entries_of_its_accounts_can_be_deleted(db):
    # Migration 0162: forget_tenant änderte die Zeilen in derselben Transaktion, danach scheiterte
    # DELETE tenant an audit_log_actor_user_id_fkey (zwei ON DELETE SET NULL auf dieselbe Zeile).
    from app.services.admin_tenant_service import AdminTenantService

    tenant = make_tenant(db, "Wird gelöscht")
    person = make_app_user(db, email="login@example.com", tenant_id=tenant.id, role_code="admin")
    other = make_tenant(db, "Bleibt")
    stays = make_app_user(db, email="bleibt@example.com", tenant_id=other.id)
    for user, tenant_id in ((person, tenant.id), (stays, other.id)):
        AuditService().log(db, action="user.login", tenant_id=tenant_id, actor_user_id=user.id, actor_email=user.email)
    db.commit()
    person_id, stays_id = person.id, stays.id

    assert AdminTenantService().delete_tenant(db, tenant.id)

    rows = db.execute(
        text("SELECT tenant_id, actor_user_id, actor_email FROM audit_log WHERE action = 'user.login' AND actor_user_id IN (:a, :b) OR (action = 'user.login' AND actor_user_id IS NULL AND tenant_id IS NULL)"),
        {"a": person_id, "b": stays_id},
    ).all()
    assert (None, None, None) in [tuple(row) for row in rows]
    assert (other.id, stays_id, "bleibt@example.com") in [tuple(row) for row in rows]


def test_purge_refuses_short_retention_and_app_role_cannot_delete(db):
    with pytest.raises(DBAPIError):
        nested = db.begin_nested()
        try:
            db.execute(text("SELECT audit_log_purge(5)"))
        finally:
            nested.rollback()
    assert db.scalar(text("SELECT has_table_privilege('hocx_app', 'audit_log', 'DELETE')")) is False
    assert db.scalar(text("SELECT has_table_privilege('hocx_app', 'audit_log', 'UPDATE')")) is False
    assert db.scalar(text("SELECT has_table_privilege('hocx_app', 'audit_log', 'INSERT')")) is True


def test_security_check_warns_on_many_failed_logins(db):
    baseline = system_health_service._check_security(db)
    assert baseline.params["failedLogins"] < 50
    for _ in range(60):
        AuditService().log(db, action="user.login_failed", outcome="failure", details={"reason": "password"})

    check = system_health_service._check_security(db)

    assert check.status in ("warning", "critical")
    assert check.params["failedLogins"] >= 60


def test_platform_audit_log_filters_by_tenant_and_action(db):
    tenant = make_tenant(db, "Plattformsicht")
    AuditService().log(db, action="user.login", tenant_id=tenant.id)
    AuditService().log(db, action="protocol.deleted", tenant_id=tenant.id)
    admin = CurrentAdmin(admin_id=1, admin_public_id=None, email="owner@hocx.invalid", display_name="Owner", role="owner")

    page = admin_routes.list_audit_log(
        filters=admin_routes.AuditFilter(tenant_id=tenant.id, action="user.login"), limit=50, offset=0, db=db, current_admin=admin,
    )

    assert [item.action for item in page.items] == ["user.login"]
    assert page.items[0].tenant_name == "Plattformsicht"
