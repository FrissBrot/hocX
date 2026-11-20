"""Security-Review M2/L7: kritische Admin-Aktionen nur mit frischer, an die Anfrage gebundener
Passkey-Bestätigung (app/core/admin_step_up.py)."""
from __future__ import annotations

import json
import secrets
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from app.api.routes import admin as admin_routes
from app.api.routes import admin_backups, admin_storage
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.admin_step_up import PURPOSES, step_up_binding
from app.core.db import get_db
from app.models import PlatformAdmin
from app.services import admin_mfa_service as mfa_module
from app.services.admin_mfa_service import AdminMfaService
from tests.soft_passkey import SoftPasskey, step_up_header

RP_ID = "admin.stepup.example"
ORIGIN = f"https://{RP_ID}"


@pytest.fixture(autouse=True)
def _admin_domain(monkeypatch):
    monkeypatch.setattr(mfa_module.settings, "traefik_admin_domain", RP_ID)


def _owner(db) -> tuple[PlatformAdmin, SoftPasskey, CurrentAdmin]:
    admin = PlatformAdmin(email=f"stepup-{uuid.uuid4().hex[:6]}@example.com", password_hash="x", display_name="Owner", role="owner")
    db.add(admin)
    db.flush()
    actor = CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name="Owner", role="owner")
    passkey = SoftPasskey()
    service = AdminMfaService()
    start = service.start_self_passkey_registration(db, actor, request_host=None, request_origin=ORIGIN)
    service.complete_self_passkey_registration(db, actor, flow_token=start.flow_token, label=None,
                                               credential=passkey.create(start.public_key, origin=ORIGIN))
    return admin, passkey, actor


def _client(db, actor: CurrentAdmin) -> TestClient:
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: actor
    return TestClient(app)


def _post_admin(client, body: dict, headers: dict | None = None):
    return client.post("/api/admin/admins", content=json.dumps(body).encode(),
                       headers={"Content-Type": "application/json", **(headers or {})})


def test_create_admin_requires_bound_step_up(db):
    admin, passkey, actor = _owner(db)
    client = _client(db, actor)
    body = {"email": f"neu-{uuid.uuid4().hex[:6]}@example.com", "display_name": "Neu", "password": secrets.token_urlsafe(18)}

    missing = _post_admin(client, body)
    assert missing.status_code == 403 and missing.json()["detail"]["code"] == "step_up_required"
    assert _post_admin(client, body, {"X-Hocx-Step-Up": "kaputt"}).status_code == 403

    # Bestätigung für einen anderen Body (anderes Konto) gilt nicht
    other = {**body, "email": "jemand-anderes@example.com"}
    headers = step_up_header(db, admin.id, passkey, purpose="admin-manage", method="POST", path="/api/admin/admins",
                             body=json.dumps(other).encode(), rp_id=RP_ID, origin=ORIGIN)
    mismatch = _post_admin(client, body, headers)
    assert mismatch.status_code == 401 and mismatch.json()["detail"]["code"] == "step_up_mismatch"

    # Falscher Zweck
    headers = step_up_header(db, admin.id, passkey, purpose="tenant-delete", method="POST", path="/api/admin/admins",
                             body=json.dumps(body).encode(), rp_id=RP_ID, origin=ORIGIN)
    assert _post_admin(client, body, headers).status_code == 401

    headers = step_up_header(db, admin.id, passkey, purpose="admin-manage", method="POST", path="/api/admin/admins",
                             body=json.dumps(body).encode(), rp_id=RP_ID, origin=ORIGIN)
    created = _post_admin(client, body, headers)
    assert created.status_code == 201, created.text
    # Einmalig: dieselbe Bestätigung ein zweites Mal
    assert _post_admin(client, body, headers).status_code == 401


def test_passkey_management_requires_step_up(db):
    admin, passkey, actor = _owner(db)
    client = _client(db, actor)
    assert client.post("/api/admin/mfa/passkeys/start").status_code == 403
    headers = step_up_header(db, admin.id, passkey, purpose="passkey-manage", method="POST", path="/api/admin/mfa/passkeys/start",
                             rp_id=RP_ID, origin=ORIGIN)
    assert client.post("/api/admin/mfa/passkeys/start", headers=headers).status_code == 200


def test_step_up_start_route_binds_purpose_and_request(db):
    admin, passkey, actor = _owner(db)
    client = _client(db, actor)
    body = json.dumps({"x": 1}).encode()
    start = client.post("/api/admin/mfa/step-up/start", json={
        "purpose": "tenant-delete", "method": "DELETE", "path": "/api/admin/tenants/abc", "body_sha256": step_up_binding("DELETE", "/x", body).split()[-1],
    })
    assert start.status_code == 200
    assert start.json()["public_key"]["rpId"] == RP_ID
    bad = client.post("/api/admin/mfa/step-up/start", json={
        "purpose": "unbekannt", "method": "DELETE", "path": "/api/admin/x", "body_sha256": "0" * 64,
    })
    assert bad.status_code == 422
    outside = client.post("/api/admin/mfa/step-up/start", json={
        "purpose": "tenant-delete", "method": "DELETE", "path": "/api/auth/x", "body_sha256": "0" * 64,
    })
    assert outside.status_code == 422


EXPECTED = {
    ("POST", "/api/admin/mfa/passkeys/start"): "passkey-manage",
    ("DELETE", "/api/admin/mfa/factors/{factor_id}"): "passkey-manage",
    ("POST", "/api/admin/admins"): "admin-manage",
    ("PATCH", "/api/admin/admins/{admin_id}"): "admin-manage",
    ("DELETE", "/api/admin/tenants/{tenant_id}"): "tenant-delete",
    ("POST", "/api/admin/tenants/{tenant_id}/cleanup"): "tenant-delete",
    ("POST", "/api/admin/tenants/{tenant_id}/export"): "tenant-export",
    ("PUT", "/api/admin/features/{code}"): "catalog-change",
    ("DELETE", "/api/admin/plans/{code}"): "catalog-change",
    ("DELETE", "/api/admin/storage-packages/{code}"): "catalog-change",
    ("POST", "/api/admin/catalog/import"): "catalog-change",
    ("DELETE", "/api/admin/users/{user_id}/mfa/factors/{factor_id}"): "user-mfa-reset",
    ("DELETE", "/api/admin/storage/profiles/{profile_id}"): "storage-destructive",
    ("POST", "/api/admin/storage/migrations"): "storage-destructive",
    ("POST", "/api/admin/storage/migrations/{migration_id}/accept-missing"): "storage-destructive",
    ("POST", "/api/admin/storage/migrations/{migration_id}/confirm-cutover"): "storage-destructive",
    ("POST", "/api/admin/storage/generations/{generation_id}/purge"): "storage-destructive",
    ("PUT", "/api/admin/backups/settings"): "backup-settings",
    ("POST", "/api/admin/restores"): "backup-restore",
}


def test_critical_routes_carry_step_up():
    """Inventar: jede kritische Admin-Route hat ihre Step-up-Prüfung (Liste im Review-Bericht)."""
    from app.core.admin_step_up import require_step_up, step_up_proof

    found = {}
    for module in (admin_routes, admin_storage, admin_backups):
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            calls = {d.call for d in route.dependant.dependencies}
            for dep in route.dependant.dependencies:
                calls |= {sub.call for sub in dep.dependencies}
            for purpose in PURPOSES:
                if require_step_up(purpose) in calls or step_up_proof(purpose) in calls:
                    for method in route.methods:
                        found[(method, "/api/admin" + route.path)] = purpose
    assert found == EXPECTED
