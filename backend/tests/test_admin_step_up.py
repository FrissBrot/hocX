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
    assert missing.status_code == 403 and missing.json()["detail"]["code"] == "admin_step_up_required"
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


STEP_UP = {
    ("POST", "/api/admin/mfa/passkeys/start"): "passkey-manage",
    ("DELETE", "/api/admin/mfa/factors/{factor_id}"): "passkey-manage",
    ("POST", "/api/admin/admins"): "admin-manage",
    ("PATCH", "/api/admin/admins/{admin_id}"): "admin-manage",
    ("POST", "/api/admin/users"): "user-manage",
    ("PATCH", "/api/admin/users/{user_id}"): "user-manage",
    ("PUT", "/api/admin/tenants/{tenant_id}/users/{user_id}"): "user-manage",
    ("DELETE", "/api/admin/tenants/{tenant_id}/users/{user_id}"): "user-manage",
    ("DELETE", "/api/admin/users/{user_id}/mfa/factors/{factor_id}"): "user-mfa-reset",
    ("PUT", "/api/admin/notifications"): "platform-settings",
    ("PUT", "/api/admin/notifications/email"): "platform-settings",
    ("POST", "/api/admin/notifications/status-token"): "platform-settings",
    ("DELETE", "/api/admin/tenants/{tenant_id}"): "tenant-delete",
    ("POST", "/api/admin/tenants/{tenant_id}/cleanup"): "tenant-delete",
    ("POST", "/api/admin/tenants/{tenant_id}/export"): "tenant-export",
    ("POST", "/api/admin/tenants/{tenant_id}/clone"): "tenant-export",
    ("PUT", "/api/admin/features/{code}"): "catalog-change",
    ("DELETE", "/api/admin/plans/{code}"): "catalog-change",
    ("DELETE", "/api/admin/storage-packages/{code}"): "catalog-change",
    ("POST", "/api/admin/catalog/import"): "catalog-change",
    ("DELETE", "/api/admin/storage/profiles/{profile_id}"): "storage-destructive",
    ("POST", "/api/admin/storage/migrations"): "storage-destructive",
    ("POST", "/api/admin/storage/migrations/{migration_id}/accept-missing"): "storage-destructive",
    ("POST", "/api/admin/storage/migrations/{migration_id}/confirm-cutover"): "storage-destructive",
    ("POST", "/api/admin/storage/generations/{generation_id}/purge"): "storage-destructive",
    ("PUT", "/api/admin/backups/settings"): "backup-settings",
    ("POST", "/api/admin/restores"): "backup-restore",
}

# Mutierende Admin-Routen ohne Passkey-Bestätigung - jede mit Begründung (Review-Inventar).
_LOGIN = "Anmeldung selbst (führt erst zur Session)"
_OPERATIONAL = "betrieblich und umkehrbar, kein Zugang zu Daten oder Konten; Audit-Log"
_COMMERCIAL = "kaufmännisch (Abo, Preise, Forderungen), kein Zugang zu Daten oder Konten; Audit-Log"
EXEMPT = {
    ("POST", "/api/admin/auth/login"): _LOGIN,
    ("POST", "/api/admin/auth/logout"): "beendet nur die eigene Session",
    ("POST", "/api/admin/auth/mfa/passkey/start"): _LOGIN,
    ("POST", "/api/admin/auth/mfa/passkey/verify"): _LOGIN,
    ("POST", "/api/admin/auth/mfa/passkey/setup/start"): _LOGIN,
    ("POST", "/api/admin/auth/mfa/passkey/setup/complete"): _LOGIN,
    ("POST", "/api/admin/mfa/step-up/start"): "holt die Challenge der Bestätigung selbst",
    ("POST", "/api/admin/mfa/passkeys/complete"): "an den Vorgang aus passkeys/start gebunden (der hat die Bestätigung)",
    ("POST", "/api/admin/notifications/test"): "sendet nur eine Testnachricht an das bereits bestätigte Ziel",
    ("POST", "/api/admin/notifications/email/test"): "sendet nur eine Testnachricht an das bereits bestätigte Ziel",
    ("POST", "/api/admin/catalog/import/preview"): "nur Vorschau, ändert nichts",
    ("POST", "/api/admin/restores/preview"): "nur Vorschau, ändert nichts",
    ("POST", "/api/admin/restores/{restore_id}/cancel"): _OPERATIONAL,
    ("POST", "/api/admin/backups"): "erstellt ein zusätzliches Backup",
    ("POST", "/api/admin/backups/restore-test"): "Probe-Wiederherstellung in isolierter Umgebung",
    ("POST", "/api/admin/backups/{job_id}/verify"): _OPERATIONAL,
    ("POST", "/api/admin/backups/{job_id}/cancel"): _OPERATIONAL,
    ("POST", "/api/admin/tenants"): "legt einen leeren Mandanten an (Konten darin brauchen user-manage)",
    ("POST", "/api/admin/tenants/import"): "legt einen neuen Mandanten aus einer Datei an, kein Zugriff auf bestehende Daten; "
                                           "Body bis 2 GiB (Hash im Browser unpraktisch)",
    ("PATCH", "/api/admin/tenants/{tenant_id}"): "nur Name und Profilbild",
    ("PUT", "/api/admin/tenants/{tenant_id}/website-listing"): "Anzeige auf der Website",
    ("PUT", "/api/admin/tenants/{tenant_id}/features"): _COMMERCIAL,
    ("PATCH", "/api/admin/tenants/{tenant_id}/subscription"): _COMMERCIAL,
    ("PUT", "/api/admin/tenants/{tenant_id}/storage-packages"): _COMMERCIAL,
    ("POST", "/api/admin/plans"): _COMMERCIAL,
    ("PUT", "/api/admin/plans/{code}"): _COMMERCIAL,
    ("POST", "/api/admin/storage-packages"): _COMMERCIAL,
    ("PUT", "/api/admin/storage-packages/{code}"): _COMMERCIAL,
    ("PATCH", "/api/admin/cashflow/charges/{charge_id}"): _COMMERCIAL,
    ("POST", "/api/admin/cashflow/charges/{charge_id}/recalculate"): _COMMERCIAL,
    ("POST", "/api/admin/cashflow/costs"): _COMMERCIAL,
    ("PUT", "/api/admin/cashflow/costs/{cost_id}"): _COMMERCIAL,
    ("PATCH", "/api/admin/cashflow/costs/{cost_id}/status"): _COMMERCIAL,
    ("DELETE", "/api/admin/cashflow/costs/{cost_id}"): _COMMERCIAL,
    ("DELETE", "/api/admin/domains/{domain_id}"): "nimmt eine Mandanten-Domain aus dem Routing (Verfügbarkeit, kein Datenzugang)",
    ("POST", "/api/admin/tenants/{tenant_id}/identity-verification/approve"): "Prüfvermerk, kein Datenzugang; Audit-Log",
    ("POST", "/api/admin/tenants/{tenant_id}/identity-verification/reject"): "Prüfvermerk, kein Datenzugang; Audit-Log",
    ("POST", "/api/admin/tenants/{tenant_id}/identity-verification/revoke"): "Prüfvermerk, kein Datenzugang; Audit-Log",
    ("POST", "/api/admin/document-templates/{template_id}/archive"): "Vorlagenpflege, kein Datenzugang",
    ("POST", "/api/admin/document-templates/{template_id}/platform-default"): "Vorlagenpflege, kein Datenzugang",
    ("POST", "/api/admin/maintenance"): "Wartungsfenster (Verfügbarkeit, kein Datenzugang); Audit-Log",
    ("PATCH", "/api/admin/maintenance/{window_id}"): "Wartungsfenster (Verfügbarkeit, kein Datenzugang); Audit-Log",
    ("POST", "/api/admin/maintenance/{window_id}/start"): "Wartungsfenster (Verfügbarkeit, kein Datenzugang); Audit-Log",
    ("POST", "/api/admin/maintenance/{window_id}/release"): "Wartungsfenster (Verfügbarkeit, kein Datenzugang); Audit-Log",
    ("POST", "/api/admin/maintenance/{window_id}/cancel"): "Wartungsfenster (Verfügbarkeit, kein Datenzugang); Audit-Log",
    ("POST", "/api/admin/storage/profiles"): "legt nur ein Profil an; Umschalten braucht storage-destructive",
    ("PATCH", "/api/admin/storage/profiles/{profile_id}"): "aktive Profile sind gesperrt (409); Umschalten braucht storage-destructive",
    ("POST", "/api/admin/storage/profiles/{profile_id}/test"): "Verbindungstest",
    ("POST", "/api/admin/storage/local-s3/request"): _OPERATIONAL,
    ("POST", "/api/admin/storage/migrations/{migration_id}/start"): "kopiert nur; Umschalten braucht storage-destructive",
    ("POST", "/api/admin/storage/migrations/{migration_id}/pause"): _OPERATIONAL,
    ("POST", "/api/admin/storage/migrations/{migration_id}/resume"): _OPERATIONAL,
    ("POST", "/api/admin/storage/migrations/{migration_id}/cancel"): _OPERATIONAL,
    ("POST", "/api/admin/storage/migrations/{migration_id}/retry-failed"): _OPERATIONAL,
    ("POST", "/api/admin/storage/migrations/{migration_id}/acknowledge-rollback"): _OPERATIONAL,
}


def test_every_mutating_admin_route_has_step_up_or_a_reason():
    """Review-Inventar: ALLE mutierenden Routen unter /api/admin (alle Router der App) - jede hat
    ihre Passkey-Bestätigung oder steht begründet in EXEMPT. Eine neue Route ohne beides lässt diesen
    Test scheitern."""
    import importlib
    import re
    from pathlib import Path

    from app.core.admin_step_up import require_step_up, step_up_proof

    def calls(dependant):
        found = {dependant.call}
        for sub in dependant.dependencies:
            found |= calls(sub)
        return found

    # Alle in main.py unter /api/admin eingebundenen Router (FastAPI kopiert die Routen nicht mehr
    # flach nach app.routes - deshalb über die Einbindungen statt über app.routes).
    main_source = (Path(__file__).resolve().parents[1] / "app/main.py").read_text(encoding="utf-8")
    includes = re.findall(r'app\.include_router\((\w+)\.router, prefix="(/api/admin[^"]*)"', main_source)
    assert len(includes) >= 8, includes
    routes = []
    for module_name, prefix in includes:
        module = importlib.import_module(f"app.api.routes.{module_name}")
        routes += [(prefix + route.path, route) for route in module.router.routes if isinstance(route, APIRoute)]

    found_step_up, unlisted = {}, []
    for path, route in routes:
        route_calls = calls(route.dependant)
        for method in sorted(route.methods & {"POST", "PUT", "PATCH", "DELETE"}):
            key = (method, path)
            purposes = [p for p in PURPOSES if require_step_up(p) in route_calls or step_up_proof(p) in route_calls]
            if purposes:
                found_step_up[key] = purposes[0]
            elif key not in EXEMPT:
                unlisted.append(key)
    assert unlisted == [], f"mutierende Admin-Routen ohne Passkey-Bestätigung und ohne Begründung: {unlisted}"
    assert found_step_up == STEP_UP
    assert not set(STEP_UP) & set(EXEMPT)


def test_step_up_path_binding_is_percent_decoded(db):
    """Das Frontend kodiert Pfadteile (encodeURIComponent); Start und Prüfung vergleichen dekodiert."""
    from app.core.admin_step_up import normalize_step_up_path, step_up_binding

    assert normalize_step_up_path("/api/admin/features/a%20b%C3%BC") == "/api/admin/features/a bü"
    assert step_up_binding("put", "/api/admin/features/a%20b", b"{}") == step_up_binding("PUT", "/api/admin/features/a b", b"{}")


def test_step_up_with_encoded_path_over_http(db):
    """Ende zu Ende: Start mit kodiertem Pfad (wie encodeURIComponent im Frontend), Anfrage mit
    demselben kodierten Pfad - die Bindung passt (kein 401/403), ein anderer Pfad nicht."""
    import base64
    import hashlib

    admin, passkey, actor = _owner(db)
    client = _client(db, actor)
    body = b"{}"

    def header_for(path: str) -> dict:
        start = client.post("/api/admin/mfa/step-up/start", json={
            "purpose": "catalog-change", "method": "PUT", "path": path, "body_sha256": hashlib.sha256(body).hexdigest(),
        }).json()
        proof = {"flow_token": start["flow_token"], "credential": passkey.get(start["public_key"], origin=ORIGIN)}
        return {"X-Hocx-Step-Up": base64.urlsafe_b64encode(json.dumps(proof).encode()).decode().rstrip("=")}

    encoded = "/api/admin/features/gibt%20es%C3%BC"
    ok = client.put(encoded, content=body, headers={"Content-Type": "application/json", **header_for(encoded)})
    assert ok.status_code not in (401, 403), ok.text
    other = client.put("/api/admin/features/anderes", content=body, headers={"Content-Type": "application/json", **header_for(encoded)})
    assert other.status_code == 401
