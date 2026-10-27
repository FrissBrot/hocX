"""Feature-Entitlements (0158_feature_entitlements, docs/FEATURE_ENTITLEMENT_ARCHITECTURE.md):
Nur-Lesen-Zustand nach Downgrade, Planwechsel mit Herkunft der Features, neue buchbare Features
und das durchgesetzte Benutzerlimit."""
from __future__ import annotations

import dataclasses

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.features_generated import F, FEATURES
from app.core.permissions import P
from app.core.security import require_feature, require_permission
from app.models import AppUser
from app.models.entities import Plan, PlanFeature, TenantFeature
from app.schemas.admin import AdminTenantSubscriptionUpdate
from app.services import user_limit_service
from app.services.admin_tenant_service import AdminTenantService

from tests.factories import make_current_user, make_tenant


def _plan(db, code: str, features: tuple[str, ...], *, user_limit: int | None = None) -> Plan:
    plan = Plan(code=code, name=code, included_user_limit=user_limit)
    db.add(plan)
    db.flush()
    for feature in features:
        db.add(PlanFeature(plan_code=code, feature_code=feature))
    db.flush()
    return plan


def _features(db, tenant_id: int) -> dict[str, tuple[str, str]]:
    rows = db.scalars(select(TenantFeature).where(TenantFeature.tenant_id == tenant_id)).all()
    return {row.feature_code: (row.access, row.source) for row in rows}


def _subscribe(db, tenant_id: int, plan_code: str) -> None:
    AdminTenantService().update_tenant_subscription(db, tenant_id, AdminTenantSubscriptionUpdate(plan_code=plan_code, billing_cycle="monthly"), admin_id=None)


def test_catalog_lists_every_feature_with_downgrade_rule():
    assert {feature.value for feature in F} == {"finance", "abgabebox", "custom_domain", "verify_domain", "task_packages", "custom_roles", "photo_sharing", "document_designer"}
    assert FEATURES[F.FINANCE].read_permissions == frozenset({"finances.read"})
    assert FEATURES[F.CUSTOM_DOMAIN].downgrade == "blocked"


def test_downgrade_keeps_plan_features_read_only_and_drops_blocked_ones(db):
    tenant = make_tenant(db, "Downgrade", features=())
    _plan(db, "test_big", ("finance", "task_packages", "custom_domain"))
    _plan(db, "test_small", ())
    _subscribe(db, tenant.id, "test_big")
    db.add(TenantFeature(tenant_id=tenant.id, feature_code="photo_sharing", source="addon"))
    db.flush()

    _subscribe(db, tenant.id, "test_small")

    state = _features(db, tenant.id)
    assert state["finance"] == ("read_only", "plan")
    assert state["task_packages"] == ("read_only", "plan")
    assert "custom_domain" not in state
    # Zusatzmodule folgen dem Plan nicht
    assert state["photo_sharing"] == ("full", "addon")


def test_upgrade_turns_read_only_back_to_full(db):
    tenant = make_tenant(db, "Upgrade", features=())
    _plan(db, "test_up_big", ("finance",))
    _plan(db, "test_up_small", ())
    _subscribe(db, tenant.id, "test_up_big")
    _subscribe(db, tenant.id, "test_up_small")
    _subscribe(db, tenant.id, "test_up_big")
    assert _features(db, tenant.id)["finance"] == ("full", "plan")


def test_read_only_allows_reading_but_blocks_writing():
    user = dataclasses.replace(make_current_user(1, role="admin"), current_tenant_features=frozenset(), current_tenant_read_only_features=frozenset({"finance", "task_packages"}))
    assert require_permission(user, P.FINANCES_READ) is user
    with pytest.raises(HTTPException) as blocked:
        require_permission(user, P.FINANCES_MANAGE)
    assert "nur noch lesend" in blocked.value.detail
    assert require_feature(user, F.TASK_PACKAGES, write=False) is user
    with pytest.raises(HTTPException):
        require_feature(user, F.TASK_PACKAGES)
    assert user.can(P.FINANCES_READ) and not user.can(P.FINANCES_MANAGE)


def test_unbooked_feature_blocks_reading_too():
    user = make_current_user(1, role="admin", features=frozenset())
    with pytest.raises(HTTPException) as blocked:
        require_feature(user, F.TASK_PACKAGES, write=False)
    assert "nicht gebucht" in blocked.value.detail


def test_admin_can_set_read_only_but_not_for_blocked_features(db):
    tenant = make_tenant(db, "Admin tri-state", features=())
    service = AdminTenantService()
    service.update_tenant_features(db, tenant.id, ["finance"], admin_id=None, read_only_codes=["task_packages"])
    assert _features(db, tenant.id) == {"finance": ("full", "addon"), "task_packages": ("read_only", "addon")}
    with pytest.raises(ValueError):
        service.update_tenant_features(db, tenant.id, [], admin_id=None, read_only_codes=["custom_domain"])


def test_user_limit_counts_active_logins_and_blocks_more(db):
    tenant = make_tenant(db, "Limit")
    _plan(db, "test_limit", (), user_limit=1)
    tenant.plan_code = "test_limit"
    db.add(AppUser(tenant_id=tenant.id, display_name="Ohne Login", login_enabled=False))
    db.add(AppUser(tenant_id=tenant.id, display_name="Mit Login", email="limit-login@example.com", password_hash="x", login_enabled=True))
    db.flush()
    assert user_limit_service.login_account_count(db, tenant.id) == 1
    with pytest.raises(HTTPException) as full:
        user_limit_service.ensure_login_capacity(db, tenant.id)
    assert full.value.status_code == 409
    tenant.user_limit_override = 2
    db.flush()
    user_limit_service.ensure_login_capacity(db, tenant.id)


def test_read_only_row_never_serves_a_domain(db):
    """Security-Review: Existenzprüfungen ohne access (Domain-Routing) dürfen eine Nur-Lesen-Zeile,
    etwa aus einem Import, nicht als gebucht werten."""
    from app.services import traefik_config_service

    tenant = make_tenant(db, "Domain read-only", features=())
    db.add(TenantFeature(tenant_id=tenant.id, feature_code="custom_domain", access="read_only"))
    db.flush()
    assert tenant.id not in set(db.scalars(traefik_config_service.tenant_ids_with_feature("custom_domain")))
    assert tenant.id not in set(db.scalars(traefik_config_service.tenant_ids_with_custom_domain_feature(db)))
