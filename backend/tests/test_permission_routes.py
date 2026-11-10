"""HTTP-level authorization matrix for security-sensitive role boundaries.

These tests intentionally exercise the FastAPI routers rather than calling guard functions
directly. They catch missing or incorrectly wired guards when endpoints are added or changed.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import admin, finance, fines, tag_config
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.db import get_db
from app.core.security import get_current_user
from tests.factories import (
    make_app_user,
    make_current_user,
    make_finance_account,
    make_fine,
    make_participant,
    make_protocol,
    make_template,
    make_tenant,
)


def _tenant_client(db, actor):
    app = FastAPI()
    app.include_router(finance.router, prefix="/api")
    app.include_router(fines.router, prefix="/api")
    app.include_router(tag_config.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app)


@pytest.mark.parametrize(
    ("role", "expected_get", "expected_post"),
    [
        ("reader", 200, 403),
        ("writer", 200, 403),
        ("kassier", 200, 201),
        ("admin", 200, 201),
    ],
)
def test_finance_account_http_permission_matrix(db, role, expected_get, expected_post):
    tenant = make_tenant(db, f"Finance Matrix {role}")
    client = _tenant_client(db, make_current_user(tenant.id, role=role))

    assert client.get("/api/finance/accounts").status_code == expected_get
    response = client.post(
        "/api/finance/accounts",
        json={"name": f"Account {role}", "currency_label": "CHF"},
    )
    assert response.status_code == expected_post


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [("reader", 403), ("writer", 403), ("kassier", 200), ("admin", 200)],
)
def test_finance_delete_http_permission_matrix(db, role, expected_status):
    tenant = make_tenant(db, f"Finance Delete {role}")
    account = make_finance_account(db, tenant.id, name=f"Delete {role}")
    client = _tenant_client(db, make_current_user(tenant.id, role=role))

    response = client.delete(f"/api/finance/accounts/{account.public_id}")
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [("reader", 403), ("writer", 403), ("kassier", 204), ("admin", 204)],
)
def test_fine_delete_http_permission_matrix(db, role, expected_status):
    tenant = make_tenant(db, f"Fine Delete {role}")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    fine = make_fine(db, protocol.id, account.id)
    client = _tenant_client(db, make_current_user(tenant.id, role=role))

    response = client.delete(f"/api/fines/{fine.public_id}")
    assert response.status_code == expected_status


def test_reader_fines_http_listing_only_returns_own_participant_fines(db):
    tenant = make_tenant(db, "Reader Own Fines")
    user = make_app_user(db, email="reader-fines@example.com", tenant_id=tenant.id)
    own_participant = user
    other_participant = make_participant(db, tenant.id, display_name="Other Person")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    own_fine = make_fine(db, protocol.id, account.id, participant_name_snapshot="Own Person")
    own_fine.participant_id = own_participant.id
    other_fine = make_fine(db, protocol.id, account.id, fine_type="absent", participant_name_snapshot="Other Person")
    other_fine.participant_id = other_participant.id
    db.flush()

    client = _tenant_client(db, make_current_user(tenant.id, role="reader", user_id=user.id))
    response = client.get("/api/fines")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(own_fine.public_id)]


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [("reader", 403), ("writer", 403), ("kassier", 403), ("admin", 200)],
)
def test_tag_config_patch_http_permission_matrix(db, role, expected_status):
    tenant = make_tenant(db, f"Tag Config {role}")
    client = _tenant_client(db, make_current_user(tenant.id, role=role))

    response = client.patch("/api/tag-config", json={"Vorstand": {"color": "#112233"}})
    assert response.status_code == expected_status


def test_tag_config_patch_merges_fields_per_tag(db):
    tenant = make_tenant(db, "Tag Config Merge")
    client = _tenant_client(db, make_current_user(tenant.id, role="admin"))

    client.patch("/api/tag-config", json={"Vorstand": {"color": "#112233"}})
    response = client.patch("/api/tag-config", json={"Vorstand": {"important": True}})
    assert response.json()["Vorstand"] == {"color": "#112233", "important": True}

    response = client.patch("/api/tag-config", json={"Vorstand": {}})
    assert response.json()["Vorstand"] == {}


def _platform_client(db, role: str):
    app = FastAPI()
    app.include_router(admin.router, prefix="/api/admin")
    current_admin = CurrentAdmin(
        admin_id=1,
        admin_public_id=uuid.uuid4(),
        email=f"{role}@example.com",
        display_name=role.title(),
        role=role,
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: current_admin
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    ["/api/admin/users", "/api/admin/error-logs", "/api/admin/admins"],
)
def test_support_cannot_read_sensitive_platform_routes(db, path):
    assert _platform_client(db, "support").get(path).status_code == 403


@pytest.mark.parametrize(
    "path",
    ["/api/admin/users", "/api/admin/error-logs", "/api/admin/admins"],
)
def test_owner_can_read_sensitive_platform_routes(db, path):
    assert _platform_client(db, "owner").get(path).status_code == 200


@pytest.mark.parametrize("kind", ["plans", "storage-packages"])
@pytest.mark.parametrize("role", ["support", "owner"])
def test_catalog_delete_requires_write_access(db, kind, role):
    from app.models.entities import Plan, StoragePackage
    from app.schemas.admin import AdminPlanWrite, AdminStoragePackageWrite
    from app.services.admin_tenant_service import AdminTenantService

    service = AdminTenantService()
    code = "test_delete_permission"
    if kind == "plans":
        service.upsert_plan(db, code, AdminPlanWrite(name="Delete permission"))
        model = Plan
    else:
        service.upsert_storage_package(db, code, AdminStoragePackageWrite(name="Delete permission", bytes=1024))
        model = StoragePackage
    client = _platform_client(db, role)
    response = client.delete(f"/api/admin/{kind}/{code}")
    assert response.status_code == (204 if role == "owner" else 403)
    assert (db.get(model, code) is None) == (role == "owner")
    if role == "owner":
        assert client.delete(f"/api/admin/{kind}/{code}").status_code == 404


@pytest.mark.parametrize("kind", ["plans", "storage-packages"])
def test_catalog_delete_returns_conflict_for_assigned_entry(db, kind):
    from app.models.entities import TenantStoragePackage
    from app.schemas.admin import AdminPlanWrite, AdminStoragePackageWrite, AdminTenantSubscriptionUpdate
    from app.services.admin_tenant_service import AdminTenantService

    service = AdminTenantService()
    tenant = make_tenant(db)
    code = "test_delete_conflict"
    if kind == "plans":
        service.upsert_plan(db, code, AdminPlanWrite(name="Assigned plan"))
        service.update_tenant_subscription(db, tenant.id, AdminTenantSubscriptionUpdate(plan_code=code), admin_id=None)
    else:
        service.upsert_storage_package(db, code, AdminStoragePackageWrite(name="Assigned package", bytes=1024))
        db.add(TenantStoragePackage(tenant_id=tenant.id, package_code=code, quantity=1))
        db.commit()
    assert _platform_client(db, "owner").delete(f"/api/admin/{kind}/{code}").status_code == 409
