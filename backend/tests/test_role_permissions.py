from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.admin_security import CurrentAdmin, require_admin_owner
from app.core.security import require_all_fines_read, require_finance_read, require_finance_write
from tests.factories import make_current_user


@pytest.mark.parametrize("role", ["reader", "writer", "kassier", "admin"])
def test_every_tenant_role_can_read_finance(role):
    user = make_current_user(tenant_id=1, role=role)
    assert require_finance_read(user) is user


@pytest.mark.parametrize("role", ["kassier", "admin"])
def test_only_cashier_and_admin_can_write_finance(role):
    user = make_current_user(tenant_id=1, role=role)
    assert require_finance_write(user) is user


@pytest.mark.parametrize("role", ["reader", "writer"])
def test_reader_and_writer_cannot_write_finance(role):
    with pytest.raises(HTTPException) as exc_info:
        require_finance_write(make_current_user(tenant_id=1, role=role))
    assert exc_info.value.status_code == 403


def test_reader_cannot_bypass_own_fines_scope_via_protocol_details():
    with pytest.raises(HTTPException) as exc_info:
        require_all_fines_read(make_current_user(tenant_id=1, role="reader"))
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("role", ["writer", "kassier", "admin"])
def test_privileged_roles_can_read_all_fines(role):
    user = make_current_user(tenant_id=1, role=role)
    assert require_all_fines_read(user) is user


def _platform_admin(role: str) -> CurrentAdmin:
    return CurrentAdmin(
        admin_id=1,
        admin_public_id=uuid.uuid4(),
        email=f"{role}@example.com",
        display_name=role.title(),
        role=role,
    )


def test_support_cannot_read_sensitive_platform_data():
    with pytest.raises(HTTPException) as exc_info:
        require_admin_owner(_platform_admin("support"))
    assert exc_info.value.status_code == 403


def test_owner_can_read_sensitive_platform_data():
    owner = _platform_admin("owner")
    assert require_admin_owner(owner) is owner
