"""Regression tests for fines tenant scoping (same K1-K4 audit class as finance)."""
from app.repositories.fines_repository import FinesRepository

from tests.factories import make_finance_account, make_fine, make_protocol, make_template, make_tenant


def _build_protocol_with_fine(db, tenant):
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number=f"P-{tenant.id}")
    account = make_finance_account(db, tenant.id)
    fine = make_fine(db, protocol.id, account.id)
    return protocol, fine


def test_list_pending_fines_for_protocol_scoped_to_tenant(db):
    repo = FinesRepository()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    protocol_a, _fine_a = _build_protocol_with_fine(db, tenant_a)

    # Tenant B must get nothing back for a protocol it doesn't own, even by guessing the id.
    assert repo.list_pending_fines_for_protocol(db, protocol_a.id, tenant_id=tenant_b.id) == []


def test_list_fines_for_protocol_scoped_to_tenant(db):
    repo = FinesRepository()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    protocol_a, fine_a = _build_protocol_with_fine(db, tenant_a)

    own_tenant_result = repo.list_fines_for_protocol(db, protocol_a.id, tenant_id=tenant_a.id)
    assert [f.id for f in own_tenant_result] == [fine_a.id]

    other_tenant_result = repo.list_fines_for_protocol(db, protocol_a.id, tenant_id=tenant_b.id)
    assert other_tenant_result == []


def test_list_fines_for_tenant_does_not_leak_other_tenants(db):
    repo = FinesRepository()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    _protocol_a, fine_a = _build_protocol_with_fine(db, tenant_a)
    _protocol_b, fine_b = _build_protocol_with_fine(db, tenant_b)

    result_a = repo.list_fines_for_tenant(db, tenant_id=tenant_a.id, limit=200)
    result_b = repo.list_fines_for_tenant(db, tenant_id=tenant_b.id, limit=200)

    assert fine_a.id in [f.id for f in result_a]
    assert fine_b.id not in [f.id for f in result_a]
    assert fine_b.id in [f.id for f in result_b]
    assert fine_a.id not in [f.id for f in result_b]
