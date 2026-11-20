"""Admin-API der Backup-Verwaltung: Berechtigungen, Idempotenz, Validierung, frische
Passkey-Bestätigung und Bestätigungsphrase für Restores, keine Secrets in Antworten."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes import admin_backups
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.db import get_db
from app.models import BackupJob, BackupRestoreJob, BackupSet, BackupSettings, PlatformAdmin
from app.services import backup_admin_service
from app.services.admin_mfa_service import AdminMfaService
from tests.soft_passkey import SoftPasskey

RP_ID = "admin.backup.example"
ORIGIN = f"https://{RP_ID}"


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    monkeypatch.setattr(admin_backups, "enforce_rate_limit", lambda *args, **kwargs: None)
    import app.services.admin_mfa_service as mfa

    monkeypatch.setattr(mfa, "enforce_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(mfa, "check_account_lockout", lambda *args, **kwargs: None)
    monkeypatch.setattr(mfa, "record_failed_attempt", lambda *args, **kwargs: None)


def _client(db, role: str = "owner", admin_id: int = 1) -> TestClient:
    app = FastAPI()
    app.include_router(admin_backups.router, prefix="/api/admin")
    current = CurrentAdmin(admin_id=admin_id, admin_public_id=uuid.uuid4(), email=f"{role}@example.com", display_name=role, role=role)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: current
    return TestClient(app)


def _actor(admin: PlatformAdmin) -> CurrentAdmin:
    return CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name, role=admin.role)


def _owner_with_passkey(db) -> tuple[PlatformAdmin, SoftPasskey]:
    admin = PlatformAdmin(email=f"owner-{uuid.uuid4().hex[:6]}@example.com", password_hash="x", display_name="Owner", role="owner")
    db.add(admin)
    db.flush()
    passkey = SoftPasskey()
    service = AdminMfaService()
    start = service.start_self_passkey_registration(db, _actor(admin), request_host=RP_ID, request_origin=ORIGIN)
    service.complete_self_passkey_registration(
        db, _actor(admin), flow_token=start.flow_token, label="p", credential=passkey.create(start.public_key, origin=ORIGIN)
    )
    return admin, passkey


def _step_up(db, admin: PlatformAdmin, passkey: SoftPasskey) -> dict:
    start = AdminMfaService().start_step_up(db, admin_id=admin.id, purpose="backup-restore", request_host=RP_ID, request_origin=ORIGIN)
    return {"flow_token": start.flow_token, "credential": passkey.get(start.public_key, origin=ORIGIN)}


def _set(db, **values) -> BackupSet:
    from app.backup.restore_core import schema_compatibility

    defaults = dict(id=uuid.uuid4(), archive_name=f"hocx-rp-20261015T000000Z-{uuid.uuid4().hex}", state="completed",
                    snapshot_at=datetime.now(UTC) - timedelta(hours=1), alembic_revision=schema_compatibility(None)["head"],
                    object_count=3, object_bytes=300, db_dump_bytes=1000,
                    tenants=[{"id": 5, "public_id": str(uuid.uuid4()), "name": "Verein", "users": 2, "objects": 3, "bytes": 300}])
    row = BackupSet(**{**defaults, **values})
    db.add(row)
    db.flush()
    return row


def test_status_and_settings_never_expose_secrets(db):
    row = db.get(BackupSettings, 1)
    row.worker_config = {"repository": "ssh://u1@u1.your-storagebox.de:23/./hocx", "passphrase_configured": True}
    row.repository_status = {"ok": True, "repository_id": "a" * 64, "stored_bytes": 10}
    db.flush()
    client = _client(db, "support")
    status = client.get("/api/admin/backups/status")
    settings = client.get("/api/admin/backups/settings")
    assert status.status_code == settings.status_code == 200
    body = status.text + settings.text
    for forbidden in ("BEGIN OPENSSH", "PRIVATE KEY", "passphrase\":\"", "secret_key"):
        assert forbidden not in body
    assert settings.json()["repository"]["repository_id"] == "a" * 64


def test_support_role_can_read_but_not_start_backups(db):
    client = _client(db, "support")
    assert client.get("/api/admin/backups").status_code == 200
    assert client.post("/api/admin/backups", json={}).status_code == 403
    assert client.put("/api/admin/backups/settings", json={}).status_code == 403
    assert client.post("/api/admin/restores/preview", json={"backup_set_id": str(uuid.uuid4()), "kind": "full"}).status_code == 403


def test_manual_backup_is_idempotent_and_returns_immediately(db):
    client = _client(db)
    first = client.post("/api/admin/backups", json={"idempotency_key": "klick-1"})
    second = client.post("/api/admin/backups", json={"idempotency_key": "klick-1"})
    third = client.post("/api/admin/backups", json={"idempotency_key": "klick-2"})  # offener Auftrag wird wiederverwendet
    assert first.status_code == 202 and first.json()["state"] == "queued"
    assert first.json()["id"] == second.json()["id"] == third.json()["id"]
    assert db.scalar(select(BackupJob).where(BackupJob.id == uuid.UUID(first.json()["id"]))).trigger == "manual"


def test_backup_rejected_when_not_configured(db, monkeypatch):
    monkeypatch.setenv("BACKUP_ENABLED", "false")
    assert _client(db).post("/api/admin/backups", json={}).status_code == 409


def test_settings_validation(db):
    client = _client(db)
    valid = {"schedule_enabled": True, "interval_hours": 6, "schedule_offset_minutes": 15, "keep_within_days": 14, "keep_daily": 14,
             "keep_weekly": 8, "keep_monthly": 12, "verify_interval_hours": 168, "verify_sample_objects": 200,
             "restore_test_interval_days": 30, "success_notification": "daily"}
    assert client.put("/api/admin/backups/settings", json={**valid, "interval_hours": 4}).json()["interval_hours"] == 4
    assert client.put("/api/admin/backups/settings", json={**valid, "interval_hours": 0}).status_code == 422
    assert client.put("/api/admin/backups/settings", json={**valid, "keep_within_days": 0, "keep_daily": 0, "keep_weekly": 0,
                                                           "keep_monthly": 0}).status_code == 422
    assert client.put("/api/admin/backups/settings", json={**valid, "success_notification": "spam"}).status_code == 422


def test_history_filters_are_validated(db):
    client = _client(db)
    assert client.get("/api/admin/backups?state=completed&kind=backup").status_code == 200
    assert client.get("/api/admin/backups?state=drop table").status_code == 422


def test_restore_preview_lists_risks_and_requires_tenant_in_backup(db):
    backup_set = _set(db)
    client = _client(db)
    full = client.post("/api/admin/restores/preview", json={"backup_set_id": str(backup_set.id), "kind": "full"})
    assert full.status_code == 200
    data = full.json()
    assert "full_replaces_data" in data["risks"] and data["confirmation_phrase"].startswith("WIEDERHERSTELLEN ")
    copy = client.post("/api/admin/restores/preview", json={"backup_set_id": str(backup_set.id), "kind": "tenant_copy",
                                                             "source_tenant_id": 5, "new_name": "Verein (Kopie)"})
    assert copy.status_code == 200 and copy.json()["tenant"]["name"] == "Verein"
    missing = client.post("/api/admin/restores/preview", json={"backup_set_id": str(backup_set.id), "kind": "tenant_copy",
                                                                "source_tenant_id": 999, "new_name": "x"})
    assert missing.status_code == 409


def test_restore_requires_fresh_passkey_and_confirmation(db):
    backup_set = _set(db)
    admin, passkey = _owner_with_passkey(db)
    client = _client(db, admin_id=admin.id)
    phrase = backup_admin_service.confirmation_phrase("tenant_copy", backup_set)
    base = {"backup_set_id": str(backup_set.id), "kind": "tenant_copy", "source_tenant_id": 5, "new_name": "Verein (Kopie)",
            "confirmation": phrase}
    # Ohne Step-up kein Restore; eine Assertion eines fremden Schlüssels gilt nicht
    assert client.post("/api/admin/restores", json=base).status_code == 422
    foreign = _step_up(db, admin, SoftPasskey())
    assert client.post("/api/admin/restores", json={**base, "step_up": foreign}).status_code == 401

    step_up = _step_up(db, admin, passkey)
    wrong = client.post("/api/admin/restores", json={**base, "step_up": step_up, "confirmation": "ja"})
    assert wrong.status_code == 422
    # BORG-009: die falsche Phrase hat die Bestätigung NICHT verbraucht - sie gilt noch.
    created = client.post("/api/admin/restores", json={**base, "step_up": step_up, "idempotency_key": "r1"})
    assert created.status_code == 202, created.text
    job = db.get(BackupRestoreJob, uuid.UUID(created.json()["id"]))
    assert job.options == {
        "source_tenant_id": 5, "new_name": "Verein (Kopie)", "replay_erasures": True, "replay_erasures_reason": None,
    } and job.mfa_verified_at is not None
    assert "step_up" not in created.text and "credential" not in created.text
    # Wiederholung derselben Anfrage (Netzwerkfehler): derselbe Auftrag, obwohl die Bestätigung verbraucht ist.
    again = client.post("/api/admin/restores", json={**base, "step_up": step_up, "idempotency_key": "r1"})
    assert again.status_code == 202 and again.json()["id"] == created.json()["id"]
    # Neue Anfrage mit anderem Schlüssel: fachlich blockiert (ein Restore läuft), bevor der Passkey geprüft wird.
    assert client.post("/api/admin/restores", json={**base, "step_up": step_up, "idempotency_key": "r2"}).status_code == 409


def test_restore_step_up_cannot_be_reused(db):
    """Eine Step-up-Assertion ist einmalig: der Vorgang wird vor der Prüfung atomar verbraucht."""
    from fastapi import HTTPException

    admin, passkey = _owner_with_passkey(db)
    step_up = _step_up(db, admin, passkey)
    service = AdminMfaService()
    service.verify_step_up(db, admin_id=admin.id, purpose="backup-restore", **step_up)
    with pytest.raises(HTTPException) as exc_info:
        service.verify_step_up(db, admin_id=admin.id, purpose="backup-restore", **step_up)
    assert exc_info.value.status_code == 401


def test_restore_step_up_is_bound_to_purpose_and_admin(db):
    from fastapi import HTTPException

    admin, passkey = _owner_with_passkey(db)
    other, _ = _owner_with_passkey(db)
    service = AdminMfaService()
    with pytest.raises(HTTPException):
        service.verify_step_up(db, admin_id=other.id, purpose="backup-restore", **_step_up(db, admin, passkey))
    with pytest.raises(HTTPException):
        service.verify_step_up(db, admin_id=admin.id, purpose="anderes", **_step_up(db, admin, passkey))


def test_restore_without_passkey_is_forbidden(db):
    admin = PlatformAdmin(email=f"nopasskey-{uuid.uuid4().hex[:6]}@example.com", password_hash="x", display_name="O", role="owner")
    db.add(admin)
    db.flush()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        AdminMfaService().start_step_up(db, admin_id=admin.id, purpose="backup-restore", request_host=RP_ID, request_origin=ORIGIN)
    assert exc_info.value.status_code == 403


def test_evaluate_reports_overdue_and_failed_states(db):
    row = db.get(BackupSettings, 1)
    row.repository_status = {"ok": True, "used_percent": 96.0}
    row.schedule_enabled = True
    db.flush()
    _set(db, snapshot_at=datetime.now(UTC) - timedelta(hours=20))
    db.add(BackupJob(kind="verify", trigger="schedule", state="failed", finished_at=datetime.now(UTC), error_code="verification_failed"))
    db.flush()
    overall, problems = backup_admin_service.evaluate(db)
    codes = {p.code: p.severity for p in problems}
    assert overall == "critical"
    assert codes["overdue"] == "critical" and codes["capacity_low"] == "critical" and codes["verify_failed"] == "critical"


def test_health_checks_include_backup(db):
    from app.services import system_health_service

    checks = {c.key: c for c in system_health_service._check_backup(db, datetime.now(UTC))}
    assert set(checks) == {"backup", "backup_repository", "backup_verification"}


def test_disabled_schedule_is_a_warning(db):
    row = db.get(BackupSettings, 1)
    row.schedule_enabled = False
    row.repository_status = {"ok": True}
    db.flush()
    _, problems = backup_admin_service.evaluate(db)
    assert any(p.code == "schedule_disabled" and p.severity == "warning" for p in problems)
