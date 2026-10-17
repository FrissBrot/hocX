"""Eigene Prüf-Domain je Mandant (Feature verify_domain, Migration 0126_verify_domain).

- unabhängig von custom_domain buchbar und gesperrt (Anlage, Aktivierung, Traefik-Routing),
- verify_document() liefert verify_domain nur bei aktiver, gesunder Domain, gebuchtem Feature
  und freigegebener Anzeige - sonst NULL (keine Weiterleitung),
- verify_site() liefert den Kopf der Prüfseite nur für eine aktive Prüf-Domain,
- neue PDFs verweisen auf die Prüfseite des Mandanten.
"""
from __future__ import annotations

import os
import uuid

import pytest
import yaml
from fastapi import HTTPException
from sqlalchemy import text

from app.documents import service as document_service
from app.models import DocumentRegistry, TenantDomain, TenantFeature
from app.schemas.user import TenantDomainCreate
from app.services import public_id_service, traefik_config_service, verify_domain_service
from app.services.admin_tenant_service import AdminTenantService
from app.services.tenant_service import TenantService
from tests.factories import grant_tenant_feature, make_current_user, make_tenant

ROLE = "hocx_abgabebox"


def _domain(db, tenant_id: int, domain: str, *, purpose: str = "verify", status: str = "active", healthy: bool = True) -> TenantDomain:
    row = TenantDomain(
        tenant_id=tenant_id, purpose=purpose, domain=domain, verification_token="tok-" + os.urandom(4).hex(),
        status=status, is_healthy=healthy,
    )
    db.add(row)
    db.flush()
    return row


def _as_abgabebox(db, sql: str, params: dict):
    savepoint = db.begin_nested()
    try:
        db.execute(text(f"SET LOCAL ROLE {ROLE}"))
        return db.execute(text(sql), params).mappings().first()
    finally:
        savepoint.rollback()
        db.execute(text("RESET ROLE"))


@pytest.fixture
def verein(db):
    tenant = make_tenant(db, "Turnverein Seedorf")
    tenant.verify_show_identity = True
    grant_tenant_feature(db, tenant.id, "verify_domain")
    entry = DocumentRegistry(tenant_id=tenant.id, sha256="a" * 64, document_type="todos", title="Pendenzen")
    db.add(entry)
    db.flush()
    return tenant, entry


def _verify(db, sha256: str):
    return _as_abgabebox(db, "SELECT * FROM verify_document(:sha)", {"sha": sha256})


def test_verify_document_returns_the_issuers_verify_domain(db, verein):
    tenant, entry = verein
    _domain(db, tenant.id, "verify.tv-seedorf.ch")
    assert _verify(db, entry.sha256)["verify_domain"] == "verify.tv-seedorf.ch"


@pytest.mark.parametrize(
    "change",
    ["hidden_identity", "not_booked", "pending", "unhealthy", "app_purpose"],
)
def test_no_redirect_target_unless_every_condition_holds(db, verein, change):
    tenant, entry = verein
    row = _domain(
        db, tenant.id, "verify.tv-seedorf.ch",
        status="pending" if change == "pending" else "active",
        healthy=change != "unhealthy",
        purpose="app" if change == "app_purpose" else "verify",
    )
    if change == "hidden_identity":
        tenant.verify_show_identity = False
    if change == "not_booked":
        db.query(TenantFeature).filter(TenantFeature.tenant_id == tenant.id).delete()
    if change == "app_purpose":
        # eine eigene App-Domain (custom_domain) ist keine Prüf-Domain
        grant_tenant_feature(db, tenant.id, "custom_domain")
    db.flush()
    assert row.id
    assert _verify(db, entry.sha256)["verify_domain"] is None
    assert verify_domain_service.usable_verify_domain(db, tenant.id) is None


def test_verify_site_shows_the_tenant_behind_an_active_verify_domain(db, verein):
    tenant, _ = verein
    _domain(db, tenant.id, "verify.tv-seedorf.ch", healthy=False)
    site = _as_abgabebox(db, "SELECT * FROM verify_site(:d)", {"d": "Verify.TV-Seedorf.ch"})
    # Die Seite selbst ist erreichbar, also kommt es auf den Health-Check nicht an
    assert site["domain"] == "verify.tv-seedorf.ch"
    assert site["tenant_name"] == "Turnverein Seedorf" and site["tenant_public_id"] == tenant.public_id
    assert site["organization_verified"] is False

    tenant.verify_show_identity = False
    db.flush()
    assert _as_abgabebox(db, "SELECT * FROM verify_site(:d)", {"d": "verify.tv-seedorf.ch"}) is None


def test_verify_site_ignores_other_purposes_and_unknown_hosts(db, verein):
    tenant, _ = verein
    grant_tenant_feature(db, tenant.id, "custom_domain")
    _domain(db, tenant.id, "app.tv-seedorf.ch", purpose="app")
    assert _as_abgabebox(db, "SELECT * FROM verify_site(:d)", {"d": "app.tv-seedorf.ch"}) is None
    assert _as_abgabebox(db, "SELECT * FROM verify_site(:d)", {"d": "unknown.example.ch"}) is None


def test_restricted_role_cannot_read_tenant_domain_directly(db, verein):
    from sqlalchemy.exc import ProgrammingError

    savepoint = db.begin_nested()
    try:
        db.execute(text(f"SET LOCAL ROLE {ROLE}"))
        with pytest.raises(ProgrammingError, match="permission denied"):
            db.execute(text("SELECT domain FROM tenant_domain LIMIT 1"))
    finally:
        savepoint.rollback()
        db.execute(text("RESET ROLE"))


# ── Feature-Gating unabhängig von custom_domain ──────────────────────────────


def test_creating_a_verify_domain_needs_verify_domain_not_custom_domain(db):
    tenant = make_tenant(db)
    only_custom = make_current_user(tenant_id=tenant.id, role="admin", features=frozenset({"custom_domain"}))
    with pytest.raises(HTTPException) as exc_info:
        TenantService().create_domain(db, tenant.id, only_custom, TenantDomainCreate(purpose="verify", domain="verify.example.ch"))
    assert exc_info.value.status_code == 403

    only_verify = make_current_user(tenant_id=tenant.id, role="admin", features=frozenset({"verify_domain"}))
    created = TenantService().create_domain(db, tenant.id, only_verify, TenantDomainCreate(purpose="verify", domain="verify.example.ch"))
    assert created.purpose == "verify"
    assert created.target_host == traefik_config_service.settings.traefik_abgabebox_domain
    with pytest.raises(HTTPException) as exc_info:
        TenantService().create_domain(db, tenant.id, only_verify, TenantDomainCreate(purpose="app", domain="app.example.ch"))
    assert exc_info.value.status_code == 403


def test_activating_a_verify_domain_is_blocked_after_the_feature_is_revoked(db):
    tenant = make_tenant(db)
    booked = make_current_user(tenant_id=tenant.id, role="admin", features=frozenset({"verify_domain"}))
    created = TenantService().create_domain(db, tenant.id, booked, TenantDomainCreate(purpose="verify", domain="verify.example.ch"))
    domain_id = public_id_service.resolve_internal_id(db, TenantDomain, created.id)
    # custom_domain allein reicht nicht für eine Prüf-Domain
    revoked = make_current_user(tenant_id=tenant.id, role="admin", features=frozenset({"custom_domain"}))
    with pytest.raises(HTTPException) as exc_info:
        TenantService().verify_domain(db, tenant.id, revoked, domain_id)
    assert exc_info.value.status_code == 403


def _regenerate(db, monkeypatch, tmp_path) -> dict:
    monkeypatch.setattr(traefik_config_service.settings, "traefik_dynamic_config_dir", str(tmp_path))
    traefik_config_service.regenerate(db)
    with open(tmp_path / "tenant-domains.yml") as fh:
        return yaml.safe_load(fh) or {}


def test_traefik_routes_only_the_verify_page_on_a_verify_domain(db, monkeypatch, tmp_path):
    tenant = make_tenant(db)
    grant_tenant_feature(db, tenant.id, "verify_domain")
    row = _domain(db, tenant.id, "verify.example.ch")

    config = _regenerate(db, monkeypatch, tmp_path)
    routers = config["http"]["routers"]
    base = f"tenant-verify-{row.id}"
    assert set(routers) == {f"{base}-root", f"{base}-frontend", f"{base}-check", f"{base}-maintenance"}
    assert "PathPrefix(`/verify`)" in routers[f"{base}-frontend"]["rule"]
    # keine Abgabe-Links, kein Upload und keine übrigen API-Routen auf der Prüf-Domain
    assert all("/api/public`)" not in r["rule"] for r in routers.values())
    assert routers[f"{base}-check"]["rule"] == "Host(`verify.example.ch`) && Path(`/api/public/verify`) && Method(`POST`)"
    assert routers[f"{base}-root"]["middlewares"] == ["tenant-verify-root-redirect@file"]
    redirect = config["http"]["middlewares"]["tenant-verify-root-redirect"]["redirectRegex"]
    assert redirect["replacement"] == "https://${1}/verify"


def test_traefik_needs_the_matching_feature_per_purpose(db, monkeypatch, tmp_path):
    tenant = make_tenant(db)
    grant_tenant_feature(db, tenant.id, "custom_domain")
    app_row = _domain(db, tenant.id, "app.example.ch", purpose="app")
    _domain(db, tenant.id, "verify.example.ch")

    config = _regenerate(db, monkeypatch, tmp_path)
    routers = config["http"]["routers"]
    assert f"tenant-app-{app_row.id}-frontend" in routers
    assert not any(key.startswith("tenant-verify-") for key in routers)
    assert "middlewares" not in config["http"]


def test_admin_revoking_verify_domain_unroutes_it_immediately(db, monkeypatch, tmp_path):
    tenant = make_tenant(db)
    grant_tenant_feature(db, tenant.id, "verify_domain")
    _domain(db, tenant.id, "verify.example.ch")
    assert _regenerate(db, monkeypatch, tmp_path)["http"]["routers"]

    AdminTenantService().update_tenant_features(db, tenant.id, [], admin_id=None)
    with open(tmp_path / "tenant-domains.yml") as fh:
        assert (yaml.safe_load(fh) or {}) == {}

    AdminTenantService().update_tenant_features(db, tenant.id, ["verify_domain"], admin_id=None)
    with open(tmp_path / "tenant-domains.yml") as fh:
        assert (yaml.safe_load(fh) or {})["http"]["routers"]


# ── PDFs verweisen auf die Prüfseite des Mandanten ───────────────────────────


def test_new_documents_use_the_tenants_verify_page(db, verein):
    tenant, _ = verein
    central = verify_domain_service.tenant_verify_base_url(db, tenant.id)
    assert central == traefik_config_service.settings.verify_base_url

    _domain(db, tenant.id, "verify.tv-seedorf.ch")
    base = verify_domain_service.tenant_verify_base_url(db, tenant.id)
    assert base == "https://verify.tv-seedorf.ch/verify"

    document_id = uuid.uuid4()
    info = document_service.verify_render_info(document_id, base=base)
    assert info.verify_link == f"https://verify.tv-seedorf.ch/verify?id={document_id}"
    assert info.verify_display == "verify.tv-seedorf.ch/verify"
    assert document_service.verify_render_info(document_id).verify_link.startswith(central)
