"""Systemmonitoring für den Objektspeicher (/admin/system, ntfy-Alarme)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.models import StorageMigration, StorageState
from app.services import system_alert_service, system_health_service


def test_object_storage_check_reports_the_active_generation(db):
    check = system_health_service._check_object_storage()
    assert check.status == "ok" and check.params["generation"] == 0


def test_storage_migration_check_escalates_rollback_and_stale_workers(db):
    assert system_health_service._check_storage_migration(db, datetime.now(UTC)).status == "ok"
    state = db.get(StorageState, 1)
    migration = StorageMigration(kind="live", state="copying", source_profile_id=state.active_profile_id, source_generation=0,
                                 source_config_version=1, target_profile_id=state.active_profile_id, target_generation=424242,
                                 target_config_version=1, heartbeat_at=datetime.now(UTC) - timedelta(hours=1))
    db.add(migration)
    db.flush()
    assert system_health_service._check_storage_migration(db, datetime.now(UTC)).status == "warning"
    migration.state = "rollback_required"
    db.flush()
    check = system_health_service._check_storage_migration(db, datetime.now(UTC))
    assert check.status == "critical"
    assert "Storage" in system_alert_service._check_message(check)


def test_new_checks_have_german_alert_titles():
    for key in ("object_storage", "storage_migration"):
        assert key in system_alert_service._CHECK_TITLES_DE
        assert key in system_alert_service._CHECK_PROBLEM_TITLES_DE
