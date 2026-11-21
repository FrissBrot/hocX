"""Mandanten-Detailseite und -Liste im Plattform-Admin (Admin-Redesign Phase C, Plan §5.1/§5.2):
Sortierung, abgeleitete Status-Filter, Speicher-Filter, Domains und Rechnungen pro Mandant."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import admin as admin_routes
from app.api.routes import admin_cashflow
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.db import get_db
from app.models import TenantFeature
from app.models.cashflow_entities import TenantCharge
from app.services.admin_tenant_service import AdminTenantService
from tests.factories import make_tenant, make_tenant_domain

MARK = "zzdetail"


def _names(page) -> list[str]:
    return [item.name for item in page.items if item.name.startswith(MARK)]


def _client(db) -> TestClient:
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/admin")
    app.include_router(admin_cashflow.router, prefix="/api/admin")
    current = CurrentAdmin(admin_id=1, admin_public_id=uuid.uuid4(), email="support@example.com", display_name="S", role="support")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: current
    return TestClient(app)


def test_sort_by_created_desc_and_name(db):
    first = make_tenant(db, f"{MARK} b")
    second = make_tenant(db, f"{MARK} a")
    first.created_at = datetime(2025, 1, 1, tzinfo=UTC)
    second.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    db.flush()
    service = AdminTenantService()

    assert _names(service.list_tenants(db, q=MARK)) == [f"{MARK} a", f"{MARK} b"]
    assert _names(service.list_tenants(db, q=MARK, sort="name", descending=True)) == [f"{MARK} b", f"{MARK} a"]
    assert _names(service.list_tenants(db, q=MARK, sort="created", descending=True)) == [f"{MARK} a", f"{MARK} b"]
    assert _names(service.list_tenants(db, q=MARK, sort="created")) == [f"{MARK} b", f"{MARK} a"]


def test_status_filters_are_derived(db):
    read_only = make_tenant(db, f"{MARK} ro")
    ending = make_tenant(db, f"{MARK} ending")
    verified = make_tenant(db, f"{MARK} verified")
    db.add(TenantFeature(tenant_id=read_only.id, feature_code="finance", access="read_only"))
    ending.contract_ends_on = date(2026, 12, 1)
    for tenant in (read_only, ending):
        tenant.identity_verified_at = datetime(2026, 1, 1, tzinfo=UTC)
    verified.identity_verified_at = datetime(2026, 1, 1, tzinfo=UTC)
    verified.contract_ends_on = date(2027, 6, 1)
    db.flush()
    service = AdminTenantService()
    today = date(2026, 11, 21)

    assert _names(service.list_tenants(db, q=MARK, status="read_only")) == [f"{MARK} ro"]
    assert _names(service.list_tenants(db, q=MARK, status="contract_ending", today=today)) == [f"{MARK} ending"]
    assert _names(service.list_tenants(db, q=MARK, status="unverified")) == []
    verified.identity_verified_at = None
    db.flush()
    assert _names(service.list_tenants(db, q=MARK, status="unverified")) == [f"{MARK} verified"]


def test_storage_ratio_filter_and_sort(db, monkeypatch):
    small = make_tenant(db, f"{MARK} small")
    full = make_tenant(db, f"{MARK} full")
    unlimited = make_tenant(db, f"{MARK} unlimited")
    small.storage_quota_bytes = 1000
    full.storage_quota_bytes = 1000
    db.flush()
    service = AdminTenantService()
    totals = {small.id: 100, full.id: 900, unlimited.id: 5000}
    monkeypatch.setattr(service.storage_service, "total_bytes_by_tenant", lambda _db: totals)

    page = service.list_tenants(db, q=MARK, storage_min_ratio=0.85)
    assert _names(page) == [f"{MARK} full"]
    assert page.total == 1
    assert _names(service.list_tenants(db, q=MARK, sort="storage", descending=True)) == [
        f"{MARK} unlimited", f"{MARK} full", f"{MARK} small",
    ]
    # Paginierung nach dem Sortieren
    assert _names(service.list_tenants(db, q=MARK, sort="storage", limit=1, offset=1)) == [f"{MARK} full"]


def test_list_route_validates_sort_and_status(db):
    client = _client(db)
    assert client.get("/api/admin/tenants?sort=evil").status_code == 422
    assert client.get("/api/admin/tenants?status=deleted").status_code == 422
    assert client.get("/api/admin/tenants?sort=users&dir=desc&limit=5").status_code == 200


def test_domains_filtered_by_tenant(db):
    tenant = make_tenant(db, f"{MARK} dom")
    other = make_tenant(db, f"{MARK} other")
    make_tenant_domain(db, tenant.id, domain="detail-a.example.org")
    make_tenant_domain(db, other.id, domain="detail-b.example.org")
    client = _client(db)

    body = client.get(f"/api/admin/domains?tenant_id={tenant.public_id}").json()
    assert [item["domain"] for item in body["items"]] == ["detail-a.example.org"]
    assert client.get(f"/api/admin/domains?tenant_id={uuid.uuid4()}").status_code == 404


def test_charges_filtered_by_tenant(db, monkeypatch):
    monkeypatch.setattr(admin_cashflow, "_sync", lambda _db: None)
    tenant = make_tenant(db, f"{MARK} pay")
    other = make_tenant(db, f"{MARK} nopay")
    for owner in (tenant, other):
        db.add(TenantCharge(
            tenant_id=owner.id, tenant_name=owner.name, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            amount_rp=1000, status="open", billing_cycle="monthly",
        ))
    db.flush()
    client = _client(db)

    body = client.get(f"/api/admin/cashflow/charges?tenant_id={tenant.public_id}").json()
    assert [item["tenant_name"] for item in body["items"]] == [tenant.name]
    assert client.get(f"/api/admin/cashflow/charges?tenant_id={uuid.uuid4()}").status_code == 404


@pytest.mark.parametrize("field", ["identity_verified_at"])
def test_read_model_exposes_verification(db, field):
    tenant = make_tenant(db, f"{MARK} rm")
    tenant.identity_verified_at = datetime.now(UTC) - timedelta(days=1)
    db.flush()
    read = AdminTenantService().get_tenant(db, tenant.id)
    assert getattr(read, field) is not None
