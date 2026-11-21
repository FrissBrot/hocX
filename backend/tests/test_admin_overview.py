"""Admin-Redesign: /api/admin/overview, /overview/series, /nav-counts, POST /search.

Rechte-Matrix (anonym/support/owner), keine Personendaten im Overview, Suche mit Limits, Maskierung,
Rate-Limit und Audit ohne Suchbegriff."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes import admin_overview as overview_routes
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.db import get_db
from app.core.redis_client import get_redis_sync
from app.models.entities import AppUser, PlatformAdmin, Tenant
from app.services import admin_overview_service


@pytest.fixture(autouse=True)
def _clear_cache():
    def clear():
        redis = get_redis_sync()
        for key in redis.scan_iter("admin-overview*"):
            redis.delete(key)
        for key in redis.scan_iter("admin-nav-counts*"):
            redis.delete(key)

    clear()
    yield
    clear()


def _admin(db, role: str) -> CurrentAdmin:
    admin = PlatformAdmin(email=f"ov-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name=f"Admin {role}", role=role)
    db.add(admin)
    db.flush()
    return CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name, role=role)


def _client(db, actor: CurrentAdmin | None) -> TestClient:
    app = FastAPI()
    app.include_router(overview_routes.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    if actor is not None:
        app.dependency_overrides[get_current_admin] = lambda: actor
    return TestClient(app)


def _tenant_with_user(db, name: str, email: str) -> tuple[Tenant, AppUser]:
    tenant = Tenant(name=name)
    db.add(tenant)
    db.flush()
    user = AppUser(tenant_id=tenant.id, email=email, display_name="Erika Muster", first_name="Erika", last_name="Muster")
    db.add(user)
    db.flush()
    return tenant, user


def test_anonymous_gets_401(db):
    client = _client(db, None)
    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/nav-counts").status_code == 401
    assert client.post("/api/admin/search", json={"q": "abc"}).status_code == 401


def test_overview_owner_has_all_fields_and_no_personal_data(db):
    marker = uuid.uuid4().hex[:8]
    _tenant_with_user(db, f"Verein {marker}", f"person-{marker}@example.org")
    response = _client(db, _admin(db, "owner")).get("/api/admin/overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "owner"
    assert body["status"] is not None
    assert body["kpis"]["errors_24h"] is not None
    assert body["kpis"]["login_failures_24h"] is not None
    assert isinstance(body["feed"], list)
    assert body["kpis"]["tenants"]["value"] >= 1
    assert f"person-{marker}" not in json.dumps(body)
    assert "Erika" not in json.dumps(body)


def test_overview_support_gets_null_for_owner_only_sources(db):
    response = _client(db, _admin(db, "support")).get("/api/admin/overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "support"
    assert body["status"] is None
    assert body["feed"] is None
    assert body["kpis"]["errors_24h"] is None
    assert body["kpis"]["login_failures_24h"] is None
    assert all(todo["key"] not in ("jobs", "backups") for todo in body["todos"])


def test_overview_is_cached_per_role(db):
    owner = _client(db, _admin(db, "owner")).get("/api/admin/overview").json()
    support = _client(db, _admin(db, "support")).get("/api/admin/overview").json()
    assert owner["role"] == "owner" and support["role"] == "support"


def test_series_only_for_owner(db):
    assert _client(db, _admin(db, "support")).get("/api/admin/overview/series?kind=logins").status_code == 403
    owner = _client(db, _admin(db, "owner"))
    for kind in ("logins", "errors"):
        for range_ in ("24h", "7d", "30d", "90d"):
            response = owner.get(f"/api/admin/overview/series?kind={kind}&range={range_}")
            assert response.status_code == 200, response.text
            assert response.json()["points"], (kind, range_)
    assert owner.get("/api/admin/overview/series?kind=users").status_code == 422
    assert owner.get("/api/admin/overview/series?kind=logins&range=1y").status_code == 422


def test_nav_counts_contract(db):
    owner = _client(db, _admin(db, "owner")).get("/api/admin/nav-counts").json()
    assert set(owner) == {"tenants", "verifications_open", "security_alerts", "operations_problems"}
    assert isinstance(owner["tenants"], int) and isinstance(owner["security_alerts"], int)
    support = _client(db, _admin(db, "support")).get("/api/admin/nav-counts").json()
    assert support["security_alerts"] is None and support["operations_problems"] is None
    assert isinstance(support["verifications_open"], int)


def _audit_rows(db, email: str) -> list:
    return db.execute(text("SELECT details_json FROM audit_log WHERE action = 'admin.search' AND actor_email = :e"), {"e": email}).all()


def test_search_finds_tenant_and_masks_user_email(db):
    marker = uuid.uuid4().hex[:8]
    tenant, _ = _tenant_with_user(db, f"Turnverein {marker}", f"kontakt.{marker}@example.org")
    actor = _admin(db, "owner")
    response = _client(db, actor).post("/api/admin/search", json={"q": marker})
    assert response.status_code == 200, response.text
    groups = {group["group"]: group["items"] for group in response.json()["groups"]}
    assert groups["tenants"][0]["href"] == f"/admin/tenants/{tenant.public_id}"
    user_item = groups["users"][0]
    assert f"kontakt.{marker}" not in json.dumps(user_item)
    assert "k***@example.org" in user_item["sublabel"]
    assert user_item["href"] == f"/admin/tenants/{tenant.public_id}/users"
    rows = _audit_rows(db, actor.email)
    assert len(rows) == 1
    details = rows[0][0]
    assert set(details) == {"groups", "result_count", "q_len"}
    assert marker not in json.dumps(details)


def test_search_support_has_no_person_groups_and_no_audit(db):
    marker = uuid.uuid4().hex[:8]
    _tenant_with_user(db, f"Club {marker}", f"x{marker}@example.org")
    actor = _admin(db, "support")
    response = _client(db, actor).post("/api/admin/search", json={"q": marker})
    assert response.status_code == 200
    names = {group["group"] for group in response.json()["groups"]}
    assert names <= {"tenants", "domains"}
    assert "tenants" in names
    assert _audit_rows(db, actor.email) == []


def test_search_limits_and_validation(db):
    marker = uuid.uuid4().hex[:6]
    for index in range(8):
        db.add(Tenant(name=f"Limit {marker} {index}"))
    db.flush()
    client = _client(db, _admin(db, "owner"))
    groups = {group["group"]: group["items"] for group in client.post("/api/admin/search", json={"q": f"Limit {marker}"}).json()["groups"]}
    assert len(groups["tenants"]) == admin_overview_service.SEARCH_GROUP_LIMIT
    assert client.post("/api/admin/search", json={"q": "a"}).status_code == 422
    assert client.post("/api/admin/search", json={"q": "a" * 101}).status_code == 422
    # LIKE-Platzhalter werden escaped: «%%» findet nicht alles
    wildcard = client.post("/api/admin/search", json={"q": "%%"}).json()["groups"]
    assert all("%" in item["label"] for group in wildcard if group["group"] == "tenants" for item in group["items"])


def test_search_short_query_skips_users(db):
    client = _client(db, _admin(db, "owner"))
    names = {group["group"] for group in client.post("/api/admin/search", json={"q": "ab"}).json()["groups"]}
    assert "users" not in names


def test_search_jobs_and_audit_prefix(db):
    client = _client(db, _admin(db, "owner"))
    groups = {group["group"]: group["items"] for group in client.post("/api/admin/search", json={"q": "log_cleanup"}).json()["groups"]}
    assert groups["jobs"][0]["href"] == "/admin/jobs?job=log_cleanup"


def test_search_rate_limit(db, monkeypatch):
    monkeypatch.setattr(overview_routes, "SEARCH_RATE_LIMIT_PER_MINUTE", 2)
    client = _client(db, _admin(db, "support"))
    assert client.post("/api/admin/search", json={"q": "zz"}).status_code == 200
    assert client.post("/api/admin/search", json={"q": "zz"}).status_code == 200
    assert client.post("/api/admin/search", json={"q": "zz"}).status_code == 429


def test_mask_email():
    assert admin_overview_service.mask_email("anna.muster@verein.ch") == "a***@verein.ch"
    assert admin_overview_service.mask_email(None) is None
    assert admin_overview_service.mask_email("kaputt") is None
