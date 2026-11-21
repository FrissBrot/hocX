"""Admin-Redesign Phase D: Kennzahlen-Rollup (Migration 0208), Stichproben und /api/admin/analytics.

Idempotenz, Backfill, keine Personendaten in den Rollup-Tabellen, RLS auf tenant_metric_daily,
Rechte der Analytics-Routen (support sieht keine Anmelde- und Fehlerreihen)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes import admin_analytics
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.db import get_db
from app.core.tenant_scope import bind_tenant_scope
from app.models.entities import AppUser, PlatformAdmin, Tenant
from app.schemas.admin import ContainerStatusRead, HealthCheckRead, SystemHealthSnapshot
from app.services import metrics_rollup_service as rollup

TODAY = date(2026, 11, 21)
YESTERDAY = TODAY - timedelta(days=1)


def _tenant_with_login(db, *, name: str, email: str) -> tuple[Tenant, AppUser]:
    tenant = Tenant(name=name)
    db.add(tenant)
    db.flush()
    user = AppUser(tenant_id=tenant.id, email=email, display_name="Erika Muster", first_name="Erika", last_name="Muster")
    db.add(user)
    db.flush()
    at = datetime.combine(YESTERDAY, datetime.min.time(), tzinfo=rollup.TZ) + timedelta(hours=10)
    db.execute(
        text("INSERT INTO audit_log (tenant_id, actor_user_id, actor_email, action, created_at) VALUES (:t, :u, :e, 'user.login', :at)"),
        {"t": tenant.id, "u": user.id, "e": email, "at": at},
    )
    db.execute(
        text("INSERT INTO audit_log (tenant_id, actor_email, action, outcome, created_at) VALUES (:t, :e, 'user.login_failed', 'failure', :at)"),
        {"t": tenant.id, "e": email, "at": at},
    )
    return tenant, user


def _platform(db, day: date, metric: str, dimension: str = "") -> float | None:
    value = db.execute(
        text("SELECT value FROM platform_metric_daily WHERE day = :d AND metric = :m AND dimension = :dim"), {"d": day, "m": metric, "dim": dimension}
    ).scalar()
    return None if value is None else float(value)


def _tenant_metric(db, tenant_id: int, day: date, metric: str) -> float | None:
    value = db.execute(
        text("SELECT value FROM tenant_metric_daily WHERE tenant_id = :t AND day = :d AND metric = :m"), {"t": tenant_id, "d": day, "m": metric}
    ).scalar()
    return None if value is None else float(value)


def _empty_rollup(db):
    db.execute(text("DELETE FROM platform_metric_daily"))
    db.execute(text("DELETE FROM tenant_metric_daily"))


def test_compute_day_counts_logins_and_is_idempotent(db):
    _empty_rollup(db)
    tenant, _ = _tenant_with_login(db, name="Rollup Verein", email="rollup-a@example.com")
    rollup.compute_day(db, YESTERDAY, snapshot=False)
    success = _platform(db, YESTERDAY, "logins.success")
    failure = _platform(db, YESTERDAY, "logins.failure")
    assert success is not None and success >= 1
    assert failure is not None and failure >= 1
    assert _tenant_metric(db, tenant.id, YESTERDAY, "logins") == 1
    assert _tenant_metric(db, tenant.id, YESTERDAY, "users.active") == 1
    rows_before = db.execute(text("SELECT count(*) FROM platform_metric_daily")).scalar()

    rollup.compute_day(db, YESTERDAY, snapshot=False)
    assert db.execute(text("SELECT count(*) FROM platform_metric_daily")).scalar() == rows_before
    assert _platform(db, YESTERDAY, "logins.success") == success
    assert _tenant_metric(db, tenant.id, YESTERDAY, "logins") == 1


def test_rollup_tables_hold_no_personal_data(db):
    _empty_rollup(db)
    _tenant_with_login(db, name="Datenschutz Verein", email="privacy-rollup@example.com")
    rollup.compute_day(db, YESTERDAY, snapshot=True)
    texts = db.execute(text("SELECT metric || ' ' || dimension FROM platform_metric_daily")).scalars().all()
    texts += db.execute(text("SELECT metric FROM tenant_metric_daily")).scalars().all()
    joined = " ".join(texts)
    assert "privacy-rollup@example.com" not in joined
    assert "Erika" not in joined and "Muster" not in joined
    # Nur bekannte Metrik-Namen - keine freien Texte.
    allowed_prefixes = ("tenants.", "users.", "logins", "errors.", "storage.", "mrr_rp", "feature.booked", "usage.")
    assert all(text_.startswith(allowed_prefixes) for text_ in texts)
    assert _platform(db, YESTERDAY, "storage.bytes_total") is not None


def test_run_job_backfills_once_then_only_missing_days(db):
    _empty_rollup(db)
    result = rollup.run_job(db, today=TODAY)
    assert result["computed"] == rollup.BACKFILL_DAYS
    days = db.execute(text("SELECT count(DISTINCT day) FROM platform_metric_daily WHERE metric = 'tenants.total'")).scalar()
    assert days == rollup.BACKFILL_DAYS
    # Momentaufnahmen nur für den jüngsten Tag, kein Backfill.
    assert db.execute(text("SELECT count(DISTINCT day) FROM platform_metric_daily WHERE metric = 'storage.bytes_total'")).scalar() == 1

    assert rollup.run_job(db, today=TODAY) == {"computed": 0}
    assert rollup.run_job(db, today=TODAY + timedelta(days=2))["computed"] == 2


def test_tenant_metric_daily_has_row_level_security(db):
    _empty_rollup(db)
    tenant_a, _ = _tenant_with_login(db, name="RLS A", email="rls-a-rollup@example.com")
    tenant_b, _ = _tenant_with_login(db, name="RLS B", email="rls-b-rollup@example.com")
    rollup.compute_day(db, YESTERDAY, snapshot=False)
    db.flush()
    db.execute(text("SET LOCAL ROLE hocx_app"))
    bind_tenant_scope(db, tenant_a.id)
    try:
        visible = set(db.execute(text("SELECT DISTINCT tenant_id FROM tenant_metric_daily")).scalars())
    finally:
        bind_tenant_scope(db, None)
        db.execute(text("RESET ROLE"))
    assert visible == {tenant_a.id}
    assert tenant_b.id not in visible


def test_samples_from_snapshot_and_cleanup(db):
    snapshot = SystemHealthSnapshot(
        collected_at=datetime.now(timezone.utc),
        docker_configured=True,
        docker_available=True,
        containers=[
            ContainerStatusRead(name="hocx-backend-1", service="backend", container_id="x", state="running", status="ok", cpu_percent=12.5, memory_bytes=200 * 1024 * 1024)
        ],
        checks=[
            HealthCheckRead(key="postgres", status="ok", params={"latencyMs": 3, "connections": 12, "maxConnections": 100, "sizeMb": 400}),
            HealthCheckRead(key="redis", status="ok", params={"latencyMs": 1, "usedMb": 20.5}),
        ],
    )
    samples = rollup.samples_from_snapshot(snapshot)
    metrics = {metric for metric, _, _ in samples}
    assert {"postgres.latency_ms", "postgres.connections", "postgres.size_mb", "redis.used_mb", "container.cpu_percent", "container.memory_mb"} <= metrics
    db.execute(text("DELETE FROM system_metric_sample"))
    rollup.maybe_write_samples(db, snapshot)
    first = db.execute(text("SELECT count(*) FROM system_metric_sample")).scalar()
    assert first == len(samples)
    rollup.maybe_write_samples(db, snapshot)  # innerhalb von 5 min: keine zweite Stichprobe
    assert db.execute(text("SELECT count(*) FROM system_metric_sample")).scalar() == first
    db.execute(text("UPDATE system_metric_sample SET ts = now() - interval '15 days'"))
    assert rollup.cleanup_samples(db)["deleted"] == first


def _admin(db, role: str) -> CurrentAdmin:
    admin = PlatformAdmin(email=f"an-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name=f"Admin {role}", role=role)
    db.add(admin)
    db.flush()
    return CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name, role=role)


def _client(db, actor: CurrentAdmin | None) -> TestClient:
    app = FastAPI()
    app.include_router(admin_analytics.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    if actor is not None:
        app.dependency_overrides[get_current_admin] = lambda: actor
    return TestClient(app)


@pytest.mark.parametrize("series", ["growth", "features", "revenue", "load", "storage", "usage", "errors"])
def test_analytics_requires_admin(db, series):
    assert _client(db, None).get(f"/api/admin/analytics/{series}").status_code == 401


def test_analytics_rights_support_vs_owner(db):
    support, owner = _client(db, _admin(db, "support")), _client(db, _admin(db, "owner"))
    for series in ("growth", "features", "revenue", "load", "storage"):
        assert support.get(f"/api/admin/analytics/{series}?range=90d").status_code == 200, series
    for series in ("usage", "errors"):
        assert support.get(f"/api/admin/analytics/{series}").status_code == 403, series
        assert owner.get(f"/api/admin/analytics/{series}").status_code == 200, series
    assert owner.get("/api/admin/analytics/unknown").status_code == 422
    assert owner.get("/api/admin/analytics/growth?range=5y").status_code == 422


def test_analytics_reads_rollup_with_collecting_since(db):
    _empty_rollup(db)
    tenant, _ = _tenant_with_login(db, name="Analytics Verein", email="analytics@example.com")
    rollup.compute_day(db, rollup.today_local() - timedelta(days=1), snapshot=True)
    owner = _client(db, _admin(db, "owner"))
    growth = owner.get("/api/admin/analytics/growth?range=30d").json()
    assert growth["collecting_since"] is not None
    assert growth["points"] and "tenants.total" in growth["points"][-1]["values"]
    year = owner.get("/api/admin/analytics/growth?range=12m").json()
    assert year["bucket"] == "month"
    storage = owner.get("/api/admin/analytics/storage").json()
    assert isinstance(storage["top_tenants"], list)
    for item in storage["top_tenants"]:
        assert set(item) == {"tenant_id", "name", "bytes"}
    features = owner.get("/api/admin/analytics/features").json()
    assert "items" in features and features["as_of"] is not None
    usage = owner.get("/api/admin/analytics/usage").json()
    assert "analytics@example.com" not in str(usage)
