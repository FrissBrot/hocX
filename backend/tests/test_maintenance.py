"""Wartungssystem: Zustände, Freigabebedingungen, serverseitige Sperre, öffentlicher Status und
Dauerabschätzung (docs/storage/WARTUNG.md)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.api.routes import admin_maintenance, maintenance_public
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.db import get_db
from app.core.job_registry import JOBS_BY_NAME
from app.core.maintenance_middleware import MaintenanceMiddleware, blocked_reason
from app.models import MaintenanceWindow, StorageMigration
from app.services import maintenance_estimator, maintenance_service
from app.services.maintenance_service import EffectiveState, MaintenanceError
from tests.storage_support import committed_storage  # noqa: F401 - Fixture


def _app(db) -> TestClient:
    app = FastAPI()
    app.add_middleware(MaintenanceMiddleware)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/things")
    def things():
        return {"things": []}

    @app.post("/api/things")
    def create_thing():
        return {"created": True}

    @app.post("/api/auth/login")
    def login():
        return {"ok": True}

    @app.websocket("/api/ws/protocols/1")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    app.include_router(maintenance_public.router, prefix="/api")
    app.include_router(admin_maintenance.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: CurrentAdmin(admin_id=1, admin_public_id=uuid.uuid4(), email="owner@example.com", display_name="Owner", role="owner")
    return TestClient(app)


def _full(db, **kwargs) -> MaintenanceWindow:
    window = maintenance_service.create_window(db, kind="full", reason_code="manual", state="preparing", **kwargs)
    maintenance_service.transition(db, window, "active")
    db.commit()
    maintenance_service.invalidate_cache()
    return window


# --- Zustände ---------------------------------------------------------------------------------


def test_invalid_transitions_are_rejected(db):
    window = maintenance_service.create_window(db, kind="full", reason_code="manual", state="scheduled", scheduled_start_at=datetime.now(UTC) + timedelta(hours=1))
    with pytest.raises(MaintenanceError):
        maintenance_service.transition(db, window, "completed")  # geplant -> beendet ohne Lauf
    maintenance_service.transition(db, window, "cancelled")
    with pytest.raises(MaintenanceError):
        maintenance_service.transition(db, window, "active")  # abgesagt ist endgültig


def test_unknown_release_conditions_cannot_be_invented_by_a_job(db):
    with pytest.raises(MaintenanceError):
        maintenance_service.create_window(db, kind="full", reason_code="x", state="preparing", release_conditions=[{"key": "always_true"}])


def test_full_maintenance_blocks_all_api_but_keeps_exempt_paths(committed_storage):
    db = committed_storage
    _full(db)
    client = _app(db)
    for method, path in (("get", "/api/things"), ("post", "/api/things"), ("post", "/api/auth/login")):
        response = getattr(client, method)(path)
        assert response.status_code == 503, path
        assert response.json()["code"] == "maintenance"
        assert int(response.headers["retry-after"]) >= 30
        assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/health").status_code == 200
    status = client.get("/api/public/maintenance-status")
    assert status.status_code == 200 and status.json()["active"] is True
    assert "no-store" in status.headers["cache-control"]
    assert client.get("/api/admin/maintenance").status_code == 200  # Notfallzugang bleibt


def test_full_maintenance_closes_websockets(committed_storage):
    _full(committed_storage)
    client = _app(committed_storage)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws/protocols/1") as ws:
            ws.receive_text()
    assert exc.value.code == 1013


def test_partial_write_fence_blocks_only_writes():
    state = EffectiveState(writes_blocked=True)
    assert blocked_reason(state, method="GET", path="/api/things", content_type="") is None
    assert blocked_reason(state, method="POST", path="/api/things", content_type="application/json") == "maintenance_writes"
    uploads = EffectiveState(uploads_blocked=True)
    assert blocked_reason(uploads, method="POST", path="/api/things", content_type="application/json") is None
    assert blocked_reason(uploads, method="POST", path="/api/files/document-uploads", content_type="multipart/form-data; boundary=x") == "maintenance_uploads"


def test_release_requires_all_conditions_and_never_bypasses_a_fence(committed_storage):
    db = committed_storage
    window = _full(db, release_conditions=[{"key": "storage_not_fenced"}])
    db.execute(text("UPDATE storage_state SET write_fenced = true, fence_reason = 'test' WHERE id = 1"))
    db.commit()
    client = _app(db)
    rejected = client.post(f"/api/admin/maintenance/{window.id}/release")
    assert rejected.status_code == 409
    db.expire_all()
    assert db.get(MaintenanceWindow, window.id).state == "active"
    db.execute(text("UPDATE storage_state SET write_fenced = false, fence_reason = NULL WHERE id = 1"))
    db.commit()
    released = client.post(f"/api/admin/maintenance/{window.id}/release")
    assert released.status_code == 200 and released.json()["state"] == "completed"
    events = db.execute(text("SELECT kind FROM maintenance_event WHERE window_id = :id ORDER BY id"), {"id": window.id}).scalars().all()
    assert "release_rejected" in events


def test_maintenance_stays_active_until_every_blocking_reason_is_resolved(committed_storage):
    db = committed_storage
    first, second = _full(db), _full(db)
    maintenance_service.release(db, first.id, actor_email=None, source="admin")
    db.commit()
    assert maintenance_service.current_effective_state(force=True).full_active is True
    maintenance_service.release(db, second.id, actor_email=None, source="admin")
    db.commit()
    assert maintenance_service.current_effective_state(force=True).full_active is False


def test_a_failed_job_window_keeps_blocking(committed_storage):
    db = committed_storage
    window = _full(db)
    maintenance_service.transition(db, window, "failed", error="Job abgestürzt")
    db.commit()
    assert maintenance_service.current_effective_state(force=True).full_active is True


def test_a_storage_migration_window_cannot_be_released_while_the_migration_runs(committed_storage):
    db = committed_storage
    from tests.storage_support import create_test_profile, requires_s3  # noqa: F401
    from app.models import StorageGeneration, StorageState

    state = db.get(StorageState, 1)
    migration = StorageMigration(kind="initial", state="copying", source_profile_id=state.active_profile_id, source_generation=state.active_generation,
                                 source_config_version=1, target_profile_id=state.active_profile_id, target_generation=987654,
                                 target_config_version=1)
    db.add(migration)
    db.flush()
    window = _full(db, release_conditions=[{"key": "storage_migration_settled", "params": {"migration_id": str(migration.id)}}])
    with pytest.raises(MaintenanceError, match="storage_migration_settled"):
        maintenance_service.release(db, window.id, actor_email="owner@example.com", source="admin")
    db.rollback()
    db.execute(text("DELETE FROM storage_migration WHERE id = :id"), {"id": migration.id})
    db.commit()


def test_supervisor_starts_scheduled_maintenance_marks_overdue_and_never_releases(committed_storage):
    db = committed_storage
    scheduled = maintenance_service.create_window(db, kind="full", reason_code="manual", state="scheduled",
                                                  scheduled_start_at=datetime.now(UTC) - timedelta(seconds=1))
    db.commit()
    maintenance_service.supervise(db)
    db.refresh(scheduled)
    assert scheduled.state == "preparing"
    scheduled.started_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    maintenance_service.supervise(db)
    db.refresh(scheduled)
    assert scheduled.state == "active"
    scheduled.estimated_end_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    maintenance_service.supervise(db)
    db.refresh(scheduled)
    assert scheduled.state == "overdue"
    for _ in range(3):
        maintenance_service.supervise(db)
    db.refresh(scheduled)
    assert scheduled.state == "overdue", "ein Timer darf die Wartung nie beenden"


# --- Öffentlicher Status ----------------------------------------------------------------------


def test_public_status_shows_ranges_overdue_and_estimating_without_internal_details(committed_storage):
    db = committed_storage
    window = _full(db, public_message={"de": "Wir sind gleich zurück"})
    status = maintenance_service.public_status(db)
    assert status["estimate_state"] == "estimating" and status["remaining_high_seconds"] is None
    maintenance_service.apply_estimate(db, window, {"remaining_low_seconds": 17 * 60 + 23, "remaining_high_seconds": 26 * 60})
    db.commit()
    status = maintenance_service.public_status(db)
    assert status["estimate_state"] == "estimated"
    # Gerundete Spanne statt Scheingenauigkeit (5-Minuten-Schritte ab 15 Minuten).
    assert status["remaining_high_seconds"] % 300 == 0 and status["remaining_low_seconds"] % 300 == 0
    assert status["remaining_low_seconds"] <= status["remaining_high_seconds"]
    window.estimated_end_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    status = maintenance_service.public_status(db)
    assert status["estimate_state"] == "overdue" and status["remaining_high_seconds"] is None
    serialized = repr(status)
    for secret in ("source_job_id", "last_error", "internal_note", "bucket", "release_conditions"):
        assert secret not in serialized
    assert status["messages"] == {"de": "Wir sind gleich zurück"}


# --- Schätzer ---------------------------------------------------------------------------------


def _migration(**values) -> StorageMigration:
    defaults = dict(kind="initial", state="copying", source_profile_id=1, source_generation=0, source_config_version=1, target_profile_id=1,
                    target_generation=1, target_config_version=1, options={"parallelism": 4, "verify_mode": "full"}, checkpoint={},
                    throughput=[], total_objects=1000, total_bytes=10 * 1024**3, copied_objects=0, copied_bytes=0, verified_objects=0)
    defaults.update(values)
    return StorageMigration(**defaults)


def test_estimator_is_conservative_and_never_falsely_precise(db):
    estimate = maintenance_estimator.estimate_storage_migration(db, _migration())
    assert estimate["remaining_high_seconds"] > estimate["remaining_low_seconds"] > 0
    assert estimate["safety_margin_seconds"] >= 300  # Mindestreserve
    # Kopie + Prüfung (voller Lesedurchlauf) zu einer abgewerteten Standardrate.
    assert estimate["components"]["copy"] > 0 and estimate["components"]["verify"] > 0
    assert estimate["rate_basis"] == "default" and estimate["confidence"] == "low"


def test_estimator_uses_measured_throughput_and_slows_down_with_it(db):
    fast = _migration(throughput=[{"t": 0, "bytes": 0}, {"t": 100, "bytes": 5 * 1024**3}])
    slow = _migration(throughput=[{"t": 0, "bytes": 0}, {"t": 100, "bytes": 50 * 1024**2}])
    assert maintenance_estimator.estimate_storage_migration(db, slow)["remaining_high_seconds"] > \
        maintenance_estimator.estimate_storage_migration(db, fast)["remaining_high_seconds"]


def test_estimator_has_no_answer_without_a_basis(db):
    assert maintenance_estimator.estimate_storage_migration(db, _migration(total_objects=0, total_bytes=0, state="pending")) is None


def test_cutover_estimate_only_counts_the_actual_interruption(db):
    migration = _migration(kind="live", applied_outbox_seq=10**12)
    cutover = maintenance_estimator.estimate_storage_migration(db, migration, scope="cutover")
    full = maintenance_estimator.estimate_storage_migration(db, migration)
    assert cutover["remaining_high_seconds"] < full["remaining_high_seconds"] / 10


def test_percentile_helper():
    assert maintenance_estimator._percentile([1, 2, 3, 4, 10], 0.9) == 10
    assert maintenance_estimator._percentile([1, 2, 3, 4, 10], 0.1) == 1


# --- Hintergrundjobs --------------------------------------------------------------------------


def test_only_supervision_jobs_run_during_full_maintenance():
    running = {name for name, job in JOBS_BY_NAME.items() if job.runs_during_maintenance}
    assert running == {"system_monitor", "maintenance_supervisor"}
