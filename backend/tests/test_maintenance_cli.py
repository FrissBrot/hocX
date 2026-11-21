"""Wartung während eines Updates (app/maintenance_cli.py, aufgerufen von scripts/deploy.sh)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app import maintenance_cli
from app.models import MaintenanceWindow
from app.services import maintenance_service


def _deploy_windows(db) -> list[MaintenanceWindow]:
    return list(db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.source_job_type == "deploy")).all())


def _full_active(db) -> bool:
    # Über die Session des Tests (die äussere Transaktion wird nie committet).
    return bool(db.execute(text("SELECT full_active FROM maintenance_effective_state()")).scalar())


def _audit_actions(db) -> list[str]:
    return list(db.execute(text("SELECT action FROM audit_log WHERE action LIKE 'admin.maintenance_deploy_%' ORDER BY id")).scalars())


def test_begin_deploy_starts_full_maintenance_immediately(db):
    message = maintenance_cli.begin_deploy(db, version="1.4.3")
    assert "Wartung aktiv" in message
    [window] = _deploy_windows(db)
    assert (window.kind, window.state, window.reason_code, window.source_job_id) == ("full", "active", "deploy", "1.4.3")
    assert window.estimated_end_at is not None
    assert _full_active(db)
    assert maintenance_service.public_status(db)["reason_code"] == "deploy"
    assert _audit_actions(db) == ["admin.maintenance_deploy_started"]


def test_begin_deploy_is_idempotent(db):
    maintenance_cli.begin_deploy(db, version="1.4.3")
    message = maintenance_cli.begin_deploy(db, version="1.4.3")
    assert "bereits offen" in message
    assert len(_deploy_windows(db)) == 1


def test_end_deploy_only_ends_deploy_windows(db):
    admin_window = maintenance_service.create_window(db, kind="full", reason_code="manual", state="preparing", actor_email="owner@example.com")
    maintenance_service.transition(db, admin_window, "active")
    planned = maintenance_service.create_window(
        db, kind="full", reason_code="manual", state="scheduled", scheduled_start_at=datetime.now(UTC) + timedelta(days=1),
    )
    job_window = maintenance_service.create_window(
        db, kind="partial", block_scope="writes", reason_code="storage_cutover", state="preparing",
        source_job_type="storage_cutover", source_job_id="00000000-0000-0000-0000-000000000000",
    )
    db.commit()
    maintenance_cli.begin_deploy(db, version="1.4.3")

    message = maintenance_cli.end_deploy(db, outcome="success")

    assert "Wartung beendet (1 Fenster, success)" in message
    [deploy] = _deploy_windows(db)
    assert deploy.state == "completed" and deploy.ended_at is not None
    for window in (admin_window, planned, job_window):
        db.refresh(window)
    assert (admin_window.state, planned.state, job_window.state) == ("active", "scheduled", "preparing")
    assert _full_active(db)  # Admin-Wartung bleibt
    assert _audit_actions(db) == ["admin.maintenance_deploy_started", "admin.maintenance_deploy_ended"]


def test_end_deploy_is_idempotent_and_ends_orphans(db):
    assert maintenance_cli.end_deploy(db, outcome="success") == "kein offenes Deploy-Fenster"
    # Verwaistes Fenster eines abgebrochenen Laufs (noch in Vorbereitung) wird ebenfalls beendet.
    orphan = maintenance_service.create_window(
        db, kind="full", reason_code="deploy", state="preparing", source_job_type="deploy", source_job_id="1.4.2",
    )
    db.commit()
    assert "1 Fenster, rollback" in maintenance_cli.end_deploy(db, outcome="rollback")
    db.refresh(orphan)
    assert orphan.state == "completed"
    assert maintenance_cli.end_deploy(db, outcome="rollback") == "kein offenes Deploy-Fenster"
    assert not _full_active(db)


def test_end_deploy_does_not_depend_on_release_conditions(db, monkeypatch):
    """Das Deploy-Fenster endet ohne release(): dessen Bedingungen (z. B. kein offener Cutover)
    schützen den Speicher - ein offener Cutover hat sein eigenes, weiter blockierendes Fenster."""
    maintenance_cli.begin_deploy(db, version="1.4.3")

    def rejected(*_args, **_kwargs):
        raise maintenance_service.MaintenanceError("Freigabebedingungen nicht erfüllt")

    monkeypatch.setattr(maintenance_service, "release", rejected)
    maintenance_cli.end_deploy(db, outcome="aborted")
    [window] = _deploy_windows(db)
    assert window.state == "completed"


def test_first_installation_is_skipped(db, monkeypatch):
    monkeypatch.setattr(maintenance_cli, "_tables_exist", lambda _db: False)
    assert "übersprungen" in maintenance_cli.begin_deploy(db, version="1.4.3")
    assert "übersprungen" in maintenance_cli.end_deploy(db, outcome="success")
    assert _deploy_windows(db) == []


def test_tables_exist_check_reports_real_schema(db):
    assert maintenance_cli._tables_exist(db) is True


def test_main_reports_errors_with_exit_code(monkeypatch, capsys):
    def boom(_db, **_kwargs):
        raise RuntimeError("db weg")

    monkeypatch.setattr(maintenance_cli, "end_deploy", boom)
    assert maintenance_cli.main(["end-deploy", "--outcome", "aborted"]) == 1
    assert "FEHLER RuntimeError" in capsys.readouterr().err


# --- Systemmonitoring: hängendes Deploy-Fenster (system_health_service._check_deploy_maintenance) ---


def test_health_check_reports_long_running_deploy_window(db):
    from app.services import system_alert_service, system_health_service

    now = datetime.now(UTC)
    assert system_health_service._check_deploy_maintenance(db, now).status == "ok"
    maintenance_cli.begin_deploy(db, version="1.4.3")
    [window] = _deploy_windows(db)

    check = system_health_service._check_deploy_maintenance(db, window.started_at + timedelta(minutes=5))
    assert (check.status, check.params["state"]) == ("ok", "active")
    check = system_health_service._check_deploy_maintenance(db, window.started_at + timedelta(minutes=45))
    assert (check.status, check.params["minutes"]) == ("warning", 45)
    check = system_health_service._check_deploy_maintenance(db, window.started_at + timedelta(hours=3))
    assert check.status == "critical"
    assert "end-deploy" in system_alert_service._check_message(check)
    assert "deploy_maintenance" in system_alert_service._CHECK_TITLES_DE
    assert "deploy_maintenance" in system_alert_service._CHECK_PROBLEM_TITLES_DE

    # Ein Admin-Fenster zählt hier nicht, ein beendetes Deploy-Fenster auch nicht.
    maintenance_cli.end_deploy(db, outcome="success")
    admin_window = maintenance_service.create_window(db, kind="full", reason_code="manual", state="preparing")
    db.commit()
    assert system_health_service._check_deploy_maintenance(db, admin_window.started_at + timedelta(hours=3)).status == "ok"
    assert "deploy_maintenance" in [c.key for c in system_health_service.collect_checks(db, now)]


# --- Öffentlicher Status während eines Updates (Update-Seite statt Wartung) ---------------------


def test_public_status_reports_update_with_versions(db):
    maintenance_cli.begin_deploy(db, version="1.5.1", from_version="1.5.0")
    status = maintenance_service.public_status(db)
    assert (status["kind"], status["from_version"], status["to_version"]) == ("update", "1.5.0", "1.5.1")
    assert status["active"] is True and status["started_at"] is not None
    assert status["estimate_state"] in ("estimated", "estimating")
    # Gleiche Sicht für die Abgabebox (SECURITY-DEFINER-Funktion, Migration 0212).
    row = db.execute(text("SELECT * FROM maintenance_public_update()")).one()
    assert (row.update_active, row.from_version, row.to_version) == (True, "1.5.0", "1.5.1")
    # Über die öffentliche Route: nur die Schema-Felder, keine internen Angaben.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes import maintenance_public
    from app.core.db import get_db

    app = FastAPI()
    app.include_router(maintenance_public.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    body = TestClient(app).get("/api/public/maintenance-status").json()
    assert (body["kind"], body["from_version"], body["to_version"]) == ("update", "1.5.0", "1.5.1")
    for internal in ("source_job_id", "source_job_type", "internal_note", "last_error", "progress", "estimate"):
        assert internal not in body


def test_public_status_drops_invalid_versions(db):
    maintenance_cli.begin_deploy(db, version="1.5.1<script>", from_version="../../etc/passwd")
    status = maintenance_service.public_status(db)
    assert status["kind"] == "update"
    assert status["from_version"] is None and status["to_version"] is None
    [window] = _deploy_windows(db)
    assert window.progress == {}


def test_rerun_updates_versions_of_an_open_deploy_window(db):
    maintenance_cli.begin_deploy(db, version="1.5.1", from_version="1.5.0")
    maintenance_cli.begin_deploy(db, version="1.5.2", from_version="1.5.0")
    assert maintenance_service.public_status(db)["to_version"] == "1.5.2"


def test_public_status_prefers_maintenance_when_an_admin_window_is_also_active(db):
    maintenance_cli.begin_deploy(db, version="1.5.1", from_version="1.5.0")
    admin_window = maintenance_service.create_window(db, kind="full", reason_code="manual", state="preparing", actor_email="owner@example.com")
    maintenance_service.transition(db, admin_window, "active")
    db.commit()
    status = maintenance_service.public_status(db)
    assert status["kind"] == "maintenance" and status["from_version"] is None and status["to_version"] is None
    assert db.execute(text("SELECT update_active FROM maintenance_public_update()")).scalar() is False


def test_public_status_kind_for_manual_partial_and_idle(db):
    assert maintenance_service.public_status(db)["kind"] is None
    maintenance_service.create_window(
        db, kind="partial", block_scope="writes", reason_code="storage_cutover", state="preparing",
        source_job_type="storage_cutover", source_job_id="00000000-0000-0000-0000-000000000000",
    )
    db.commit()
    status = maintenance_service.public_status(db)
    assert (status["kind"], status["partial"], status["to_version"]) == ("maintenance", True, None)


def test_cli_passes_from_version(monkeypatch):
    seen = {}

    def fake_begin(_db, **kwargs):
        seen.update(kwargs)
        return "ok"

    class Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(maintenance_cli, "begin_deploy", fake_begin)
    monkeypatch.setattr("app.core.db.SessionLocal", Session)
    assert maintenance_cli.main(["begin-deploy", "--version", "1.5.1", "--from-version", "1.5.0"]) == 0
    assert seen == {"version": "1.5.1", "from_version": "1.5.0"}
