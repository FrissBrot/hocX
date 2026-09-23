"""Feature-Gating pro Mandant (Finanzen als Pilot-Feature) - orthogonal zur Rollenpruefung
(siehe test_role_permissions.py). require_feature prueft nur, ob der Mandant das Feature
gebucht hat; die Rolle spielt hier keine Rolle."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.security import (
    require_abgabebox_read,
    require_abgabebox_write,
    require_feature,
    require_finance_read,
    require_finance_write,
)
from app.schemas.user import TenantDomainCreate
from app.services.tenant_service import TenantService
from tests.factories import make_current_user, make_tenant


def test_require_feature_allows_booked_feature():
    user = make_current_user(tenant_id=1, role="reader", features=frozenset({"finance"}))
    assert require_feature(user, "finance") is user


def test_require_feature_blocks_unbooked_feature():
    user = make_current_user(tenant_id=1, role="admin", features=frozenset())
    with pytest.raises(HTTPException) as exc_info:
        require_feature(user, "finance")
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("role", ["reader", "writer", "kassier", "admin"])
def test_finance_read_blocked_when_tenant_has_not_booked_finance(role):
    """Even a role that would normally pass (test_role_permissions.py) must be rejected once
    the tenant itself has not booked Finanzen - the two checks are independent layers."""
    user = make_current_user(tenant_id=1, role=role, features=frozenset())
    with pytest.raises(HTTPException) as exc_info:
        require_finance_read(user)
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("role", ["kassier", "admin"])
def test_finance_write_blocked_when_tenant_has_not_booked_finance(role):
    user = make_current_user(tenant_id=1, role=role, features=frozenset())
    with pytest.raises(HTTPException) as exc_info:
        require_finance_write(user)
    assert exc_info.value.status_code == 403


def test_finance_read_allowed_when_tenant_has_booked_finance():
    user = make_current_user(tenant_id=1, role="reader", features=frozenset({"finance"}))
    assert require_finance_read(user) is user


def test_default_factory_user_has_finance_booked():
    """make_current_user's default (features=None -> {'finance'}) mirrors migration 0084's
    backfill: every pre-existing tenant keeps Finanzen booked."""
    user = make_current_user(tenant_id=1, role="admin")
    assert require_finance_write(user) is user


@pytest.mark.parametrize("role", ["reader", "writer", "kassier", "admin"])
def test_abgabebox_read_blocked_when_tenant_has_not_booked_abgabebox(role):
    """Abgabebox lief bisher ungated - seit 0085_plan_pricing gilt dieselbe Trennung wie bei
    Finanzen: die Rolle allein reicht nicht mehr, der Mandant muss das Feature gebucht haben."""
    user = make_current_user(tenant_id=1, role=role, features=frozenset())
    with pytest.raises(HTTPException) as exc_info:
        require_abgabebox_read(user)
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("role", ["writer", "admin"])
def test_abgabebox_write_blocked_when_tenant_has_not_booked_abgabebox(role):
    user = make_current_user(tenant_id=1, role=role, features=frozenset())
    with pytest.raises(HTTPException) as exc_info:
        require_abgabebox_write(user)
    assert exc_info.value.status_code == 403


def test_abgabebox_read_allowed_when_tenant_has_booked_abgabebox():
    user = make_current_user(tenant_id=1, role="reader", features=frozenset({"abgabebox"}))
    assert require_abgabebox_read(user) is user


def test_default_factory_user_has_abgabebox_booked():
    """make_current_user's default (features=None -> {'finance', 'abgabebox'}) mirrors
    migration 0085's backfill: every pre-existing tenant keeps Abgabebox booked."""
    user = make_current_user(tenant_id=1, role="writer")
    assert require_abgabebox_write(user) is user


def test_create_domain_blocked_when_tenant_has_not_booked_custom_domain(db):
    """create_domain (tenant_service.py) was Self-Service for any tenant admin, gated only by
    _require_manageable() - not by plan. 0086_custom_domain_enforcement closes that gap the same
    way 0085 did for Abgabebox."""
    tenant = make_tenant(db)
    actor = make_current_user(tenant_id=tenant.id, role="admin", features=frozenset())
    with pytest.raises(HTTPException) as exc_info:
        TenantService().create_domain(db, tenant.id, actor, TenantDomainCreate(purpose="app", domain="app.example.com"))
    assert exc_info.value.status_code == 403


def test_create_domain_allowed_when_tenant_has_booked_custom_domain(db):
    tenant = make_tenant(db)
    actor = make_current_user(tenant_id=tenant.id, role="admin", features=frozenset({"custom_domain"}))
    created = TenantService().create_domain(db, tenant.id, actor, TenantDomainCreate(purpose="app", domain="app.example.com"))
    assert created.domain == "app.example.com"


def test_default_factory_user_has_custom_domain_booked():
    """make_current_user's default (features=None -> includes 'custom_domain') mirrors
    migration 0086's backfill: every pre-existing tenant keeps its Self-Service domain setup."""
    user = make_current_user(tenant_id=1, role="admin")
    assert require_feature(user, "custom_domain") is user
