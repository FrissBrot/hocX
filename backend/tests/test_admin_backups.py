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
from app.core.admin_step_up import require_step_up
from app.core.db import get_db
from app.models import BackupJob, BackupRestoreJob, BackupSet, BackupSettings, PlatformAdmin
from app.services import backup_admin_service
from app.services.admin_mfa_service import AdminMfaService
from tests.soft_passkey import SoftPasskey, step_up_header

RP_ID = "admin.backup.example"
ORIGIN = f"https://{RP_ID}"


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    import app.services.admin_mfa_service as mfa_service

    monkeypatch.setattr(mfa_service.settings, "traefik_admin_domain", RP_ID)
    monkeypatch.setattr(admin_backups, "enforce_rate_limit", lambda *args, **kwargs: None)
    import app.services.admin_mfa_service as mfa

    monkeypatch.setattr(mfa, "enforce_rate_limit", lambda *args, **kwargs: None)
    # Passkey-Versuche zählt der Anmeldeschutz (consume_factor_attempt); conftest leert die Zähler
    # vor jedem Test.


def _client(db, role: str = "owner", admin_id: int = 1) -> TestClient:
    app = FastAPI()
    app.include_router(admin_backups.router, prefix="/api/admin")
    current = CurrentAdmin(admin_id=admin_id, admin_public_id=uuid.uuid4(), email=f"{role}@example.com", display_name=role, role=role)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: current
    # Einstellungen: die Step-up-Prüfung selbst testen test_admin_step_up.py und die Restore-Tests hier
    app.dependency_overrides[require_step_up("backup-settings")] = lambda: current
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


def _step_up(db, admin: PlatformAdmin, passkey: SoftPasskey, body: dict, path: str = "/api/admin/restores") -> dict:
    import json as _json

    return step_up_header(db, admin.id, passkey, purpose="backup-restore", method="POST", path=path,
                          body=_json.dumps(body).encode(), rp_id=RP_ID, origin=ORIGIN)


def _post(client, body: dict, headers: dict | None = None):
    import json as _json

    return client.post("/api/admin/restores", content=_json.dumps(body).encode(),
                       headers={"Content-Type": "application/json", **(headers or {})})


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
    body = {"backup_set_id": str(backup_set.id), "kind": "tenant_copy", "source_tenant_id": 5, "new_name": "Verein (Kopie)",
            "confirmation": phrase, "idempotency_key": "r1"}
    # Ohne Step-up kein Restore; ein fremder Schlüssel gilt nicht
    assert _post(client, body).status_code == 403
    assert _post(client, body, _step_up(db, admin, SoftPasskey(), body)).status_code == 401

    # Review L7: eine Bestätigung für andere Parameter gilt nicht
    other = {**body, "new_name": "Andere Kopie"}
    assert _post(client, body, _step_up(db, admin, passkey, other)).status_code == 401

    wrong = {**body, "confirmation": "ja"}
    assert _post(client, wrong, _step_up(db, admin, passkey, wrong)).status_code == 422
    headers = _step_up(db, admin, passkey, body)
    created = _post(client, body, headers)
    assert created.status_code == 202, created.text
    job = db.get(BackupRestoreJob, uuid.UUID(created.json()["id"]))
    assert job.options == {
        "source_tenant_id": 5, "new_name": "Verein (Kopie)", "replay_erasures": True, "replay_erasures_reason": None,
    } and job.mfa_verified_at is not None
    assert "credential" not in created.text
    # Wiederholung derselben Anfrage (Netzwerkfehler): derselbe Auftrag, obwohl die Bestätigung verbraucht ist.
    again = _post(client, body, headers)
    assert again.status_code == 202 and again.json()["id"] == created.json()["id"]
    # Neue Anfrage mit anderem Schlüssel: fachlich blockiert (ein Restore läuft), bevor der Passkey geprüft wird.
    second = {**body, "idempotency_key": "r2"}
    assert _post(client, second, _step_up(db, admin, passkey, second)).status_code == 409


def test_restore_step_up_cannot_be_reused(db):
    """Eine Step-up-Assertion ist einmalig: der Vorgang wird vor der Prüfung atomar verbraucht."""
    from fastapi import HTTPException

    from app.core.admin_step_up import step_up_binding

    admin, passkey = _owner_with_passkey(db)
    binding = step_up_binding("POST", "/api/admin/restores", b"{}")
    service = AdminMfaService()
    start = service.start_step_up(db, admin_id=admin.id, purpose="backup-restore", binding=binding, request_host=RP_ID, request_origin=ORIGIN)
    credential = passkey.get(start.public_key, origin=ORIGIN)
    service.verify_step_up(db, admin_id=admin.id, purpose="backup-restore", flow_token=start.flow_token, credential=credential, binding=binding)
    with pytest.raises(HTTPException) as exc_info:
        service.verify_step_up(db, admin_id=admin.id, purpose="backup-restore", flow_token=start.flow_token, credential=credential, binding=binding)
    assert exc_info.value.status_code == 401


def test_restore_step_up_is_bound_to_purpose_admin_and_binding(db):
    from fastapi import HTTPException

    from app.core.admin_step_up import step_up_binding

    admin, passkey = _owner_with_passkey(db)
    other, _ = _owner_with_passkey(db)
    service = AdminMfaService()
    binding = step_up_binding("POST", "/api/admin/restores", b"{}")
    for admin_id, purpose, used_binding in (
        (other.id, "backup-restore", binding),
        (admin.id, "admin-manage", binding),
        (admin.id, "backup-restore", step_up_binding("POST", "/api/admin/restores", b"{\"x\":1}")),
    ):
        start = service.start_step_up(db, admin_id=admin.id, purpose="backup-restore", binding=binding, request_host=RP_ID, request_origin=ORIGIN)
        with pytest.raises(HTTPException) as exc_info:
            service.verify_step_up(db, admin_id=admin_id, purpose=purpose, flow_token=start.flow_token,
                                   credential=passkey.get(start.public_key, origin=ORIGIN), binding=used_binding)
        assert exc_info.value.status_code == 401


def test_restore_without_passkey_is_forbidden(db):
    admin = PlatformAdmin(email=f"nopasskey-{uuid.uuid4().hex[:6]}@example.com", password_hash="x", display_name="O", role="owner")
    db.add(admin)
    db.flush()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        AdminMfaService().start_step_up(db, admin_id=admin.id, purpose="backup-restore", binding="x", request_host=RP_ID, request_origin=ORIGIN)
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


# --- Backup-Redesign 1.6 -------------------------------------------------------------------------


def _failed_job(db, **values) -> BackupJob:
    job = BackupJob(kind="backup", trigger="schedule", state="failed", error_code="borg_connection_lost",
                    error_message="ssh: connect to host u412873.your-storagebox.de port 23: Connection timed out",
                    created_at=datetime.now(UTC) - timedelta(minutes=30), finished_at=datetime.now(UTC) - timedelta(minutes=28), **values)
    db.add(job)
    db.flush()
    return job


def test_support_gets_no_storage_box_address_and_no_raw_errors(db):
    """User-Entscheid 2026-11-25 (Frage 2 b): Support sieht weder Adresse/Benutzer der Storage Box
    noch rohe Fehlermeldungen - durchgesetzt in der API-Antwort, nicht nur in der Oberfläche."""
    from app.models import BackupEvent

    row = db.get(BackupSettings, 1)
    row.worker_config = {"repository": "ssh://u412873@u412873.your-storagebox.de:23/./hocx-borg", "remote_path": "borg-1.4",
                         "host_key_pinned": True, "repository_id_pinned": True}
    row.repository_status = {"ok": False, "error_code": "repository_unreachable", "error": "ssh: connect to host u412873.your-storagebox.de port 23"}
    job = _failed_job(db)
    db.add(BackupEvent(job_id=job.id, kind="retry", level="warning", message="ssh: connect to host u412873.your-storagebox.de port 23",
                       details={"code": "borg_connection_lost", "delay_seconds": 30, "stderr": "u412873@host"}))
    db.flush()
    paths = ["/api/admin/backups/status", "/api/admin/backups/settings", "/api/admin/backups?kind=backup", f"/api/admin/backups/{job.id}"]
    support = _client(db, "support")
    owner = _client(db, "owner")
    for path in paths:
        support_body = support.get(path)
        assert support_body.status_code == 200, path
        assert "u412873" not in support_body.text, path
        assert "storagebox" not in support_body.text, path
    settings = support.get("/api/admin/backups/settings").json()
    assert "repository" not in settings["worker_config"] and "remote_path" not in settings["worker_config"]
    assert settings["worker_config"]["host_key_pinned"] is True  # Rest bleibt
    assert settings["repository"]["error"] is None and settings["repository"]["error_code"] == "repository_unreachable"
    detail = support.get(f"/api/admin/backups/{job.id}").json()
    assert detail["error_message"] is None and detail["error_code"] == "borg_connection_lost"
    retry = next(event for event in detail["events"] if event["kind"] == "retry")
    assert retry["message"] is None and retry["details"] == {"code": "borg_connection_lost", "delay_seconds": 30}
    assert detail["result"] is None
    # Owner sieht alles wie bisher.
    assert "u412873" in owner.get("/api/admin/backups/settings").text
    assert owner.get(f"/api/admin/backups/{job.id}").json()["error_message"].startswith("ssh:")


def test_support_restore_list_has_no_raw_errors(db):
    backup_set = _set(db)
    restore = BackupRestoreJob(kind="full", state="failed", archive_name=backup_set.archive_name, backup_set_id=backup_set.id,
                               options={}, requested_by_email="owner@example.com", error_code="cutover_inconsistent",
                               error_message="Datenbanken hocx_live, hocx_pre_restore_x manuell prüfen",
                               result={"pre_restore_db": "hocx_pre_restore_x", "generation": 2, "smoke": {"problems": ["x"]}})
    db.add(restore)
    db.flush()
    support = _client(db, "support")
    listed = support.get("/api/admin/restores").json()
    assert listed[0]["error_message"] is None and listed[0]["error_code"] == "cutover_inconsistent"
    assert support.get(f"/api/admin/restores/{restore.id}").json()["error_message"] is None
    detail = support.get(f"/api/admin/restores/{restore.id}").json()
    assert detail["result"] == {"generation": 2} and "hocx_pre_restore_x" not in support.get(f"/api/admin/restores/{restore.id}").text
    assert _client(db).get(f"/api/admin/restores/{restore.id}").json()["error_message"]


def test_history_counts_summary_job_id_and_since(db):
    backup_set = _set(db)
    backup = BackupJob(kind="backup", trigger="schedule", state="completed", backup_set_id=backup_set.id, created_at=datetime.now(UTC) - timedelta(hours=1))
    verify = BackupJob(kind="verify", trigger="manual", state="completed", backup_set_id=backup_set.id, created_at=datetime.now(UTC) - timedelta(minutes=30),
                       result={"content_sample": {"contents_checked": 200, "path": "/secret/path"}, "verify_data": "ok"})
    retention = BackupJob(kind="retention", trigger="schedule", state="completed", created_at=datetime.now(UTC) - timedelta(minutes=20),
                          result={"removed": 3, "kept": 42, "removed_names": ["x"]})
    old = BackupJob(kind="backup", trigger="schedule", state="failed", created_at=datetime.now(UTC) - timedelta(days=10))
    db.add_all([backup, verify, retention, old])
    db.flush()
    client = _client(db)
    page = client.get("/api/admin/backups?limit=200").json()
    assert page["counts"]["completed"] >= 3 and page["counts"]["failed"] >= 1
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id[str(verify.id)]["summary"] == {"contents_checked": 200, "deep": True}
    assert by_id[str(retention.id)]["summary"] == {"removed": 3, "kept": 42}
    # Sicherungspunkt kennt den Backup-Auftrag, auch wenn ein Prüfauftrag darauf zeigt.
    assert by_id[str(verify.id)]["backup_set"]["job_id"] == str(backup.id)
    assert by_id[str(backup.id)]["backup_set"]["job_id"] == str(backup.id)
    # Zähler gelten für den Filter ohne Zustandsfilter.
    filtered = client.get("/api/admin/backups?state=failed&limit=200").json()
    assert all(item["state"] == "failed" for item in filtered["items"]) and filtered["counts"]["completed"] >= 3
    since = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    recent = client.get("/api/admin/backups", params={"since": since, "limit": 200}).json()
    assert str(old.id) not in {item["id"] for item in recent["items"]}
    assert client.get("/api/admin/backups", params={"since": "2026-11-01T00:00:00"}).status_code == 422  # ohne Zeitzone
    sets = client.get("/api/admin/backups/sets").json()
    assert next(item for item in sets if item["id"] == str(backup_set.id))["job_id"] == str(backup.id)


def test_restore_request_event_mentions_passkey_not_totp(db):
    from app.models import BackupEvent

    admin, passkey = _owner_with_passkey(db)
    backup_set = _set(db)
    client = _client(db, admin_id=admin.id)
    body = {"backup_set_id": str(backup_set.id), "kind": "tenant_copy", "source_tenant_id": 5, "new_name": f"Kopie {uuid.uuid4().hex[:6]}",
            "confirmation": backup_admin_service.confirmation_phrase("tenant_copy", backup_set)}
    response = _post(client, body, _step_up(db, admin, passkey, body))
    assert response.status_code == 202, response.text
    event = db.scalars(select(BackupEvent).where(BackupEvent.restore_job_id == uuid.UUID(response.json()["id"]))).first()
    assert "Passkey" in event.message and "TOTP" not in event.message


def test_nav_counts_report_backup_status(db, monkeypatch):
    from app.services import admin_overview_service

    monkeypatch.setattr(admin_overview_service, "_cached", lambda key, ttl, compute: compute())
    _failed_job(db)
    row = db.get(BackupSettings, 1)
    row.repository_status = {"ok": False, "error_code": "repository_unreachable"}
    db.flush()
    assert admin_overview_service.nav_counts(db, owner=False)["backup_status"] == "critical"
    monkeypatch.setenv("BACKUP_ENABLED", "false")
    assert admin_overview_service.nav_counts(db, owner=False)["backup_status"] is None
