"""Audit 08 (2026-11, Migration 0179): «Domain hinzufügen» löschte sofort die aktive Domain
desselben Zwecks. Jetzt bleibt sie bestehen, bis die neue Domain verifiziert ist."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import TenantDomain
from app.schemas.user import TenantDomainCreate
from app.services import domain_health_check_service, domain_verification_service, public_id_service, traefik_config_service
from app.services.tenant_service import TenantService
from tests.factories import grant_tenant_feature, make_current_user, make_tenant


@pytest.fixture
def setup(db, monkeypatch):
    tenant = make_tenant(db, "Domainverein")
    grant_tenant_feature(db, tenant.id, "custom_domain")
    actor = make_current_user(tenant_id=tenant.id, role="admin", features=frozenset({"custom_domain"}))
    live = TenantDomain(
        tenant_id=tenant.id, purpose="app", domain="app.verein.example", verification_token="tok-live", status="active",
    )
    db.add(live)
    db.flush()
    regenerated: list[bool] = []
    monkeypatch.setattr(traefik_config_service, "regenerate", lambda _db: regenerated.append(True))
    monkeypatch.setattr(traefik_config_service, "target_host_for_purpose", lambda _purpose: "hocx.example.com")
    return tenant, actor, live, regenerated


def _rows(db, tenant_id):
    return {
        (row.domain, row.status)
        for row in db.query(TenantDomain).filter(TenantDomain.tenant_id == tenant_id, TenantDomain.purpose == "app")
    }


def test_adding_a_domain_keeps_the_active_one_until_verified(db, setup, monkeypatch):
    tenant, actor, _live, regenerated = setup
    service = TenantService()

    typo = service.create_domain(db, tenant.id, actor, TenantDomainCreate(purpose="app", domain="ap.verein.example"))
    assert typo.status == "pending"
    assert typo.replaces_domain == "app.verein.example"
    assert _rows(db, tenant.id) == {("app.verein.example", "active"), ("ap.verein.example", "pending")}
    assert regenerated == []  # Routing unverändert

    # Ein zweiter Versuch ersetzt nur die ausstehende Domain, nie die aktive.
    fixed = service.create_domain(db, tenant.id, actor, TenantDomainCreate(purpose="app", domain="neu.verein.example"))
    assert _rows(db, tenant.id) == {("app.verein.example", "active"), ("neu.verein.example", "pending")}
    listed = {row.domain: row for row in service.list_domains(db, tenant.id, actor)}
    assert listed["neu.verein.example"].replaces_domain == "app.verein.example"
    assert listed["app.verein.example"].replaces_domain is None

    # Fehlgeschlagene Prüfung: übersetzbarer Code, aktive Domain bleibt.
    monkeypatch.setattr(domain_verification_service, "verify_domain", lambda *_args: (False, "txt_missing"))
    fixed_id = public_id_service.resolve_internal_id(db, TenantDomain, fixed.id)
    with pytest.raises(HTTPException) as exc_info:
        service.verify_domain(db, tenant.id, actor, fixed_id)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "domain_txt_missing"
    assert ("app.verein.example", "active") in _rows(db, tenant.id)

    # Erst die erfolgreiche Prüfung tauscht die Domains.
    monkeypatch.setattr(domain_verification_service, "verify_domain", lambda *_args: (True, "ok"))
    verified = service.verify_domain(db, tenant.id, actor, fixed_id)
    assert verified.status == "active"
    assert _rows(db, tenant.id) == {("neu.verein.example", "active")}
    assert regenerated == [True]


def test_adding_the_already_active_domain_again_is_rejected(db, setup):
    tenant, actor, _live, _regenerated = setup
    with pytest.raises(HTTPException) as exc_info:
        TenantService().create_domain(db, tenant.id, actor, TenantDomainCreate(purpose="app", domain="APP.verein.example"))
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "domain_already_active"
    assert _rows(db, tenant.id) == {("app.verein.example", "active")}


def test_health_check_marks_domains_outside_the_subscription_unhealthy(db, monkeypatch):
    tenant = make_tenant(db, "Ohne Abo")
    row = TenantDomain(
        tenant_id=tenant.id, purpose="app", domain="ohne-abo.example", verification_token="tok", status="active", is_healthy=True,
    )
    db.add(row)
    db.flush()
    monkeypatch.setattr(domain_verification_service, "is_still_routable", lambda *_args: True)
    domain_health_check_service.run_health_check(db)
    db.refresh(row)
    assert row.is_healthy is False
