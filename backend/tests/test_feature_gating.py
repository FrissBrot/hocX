"""Feature-Gating pro Mandant (Finanzen als Pilot-Feature) - orthogonal zur Rollenpruefung
(siehe test_role_permissions.py). require_feature prueft nur, ob der Mandant das Feature
gebucht hat; die Rolle spielt hier keine Rolle."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.security import require_feature, require_finance_read, require_finance_write
from tests.factories import make_current_user


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
