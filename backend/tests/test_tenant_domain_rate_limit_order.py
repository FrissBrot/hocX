"""Audit MAIN-SEC-008: Fremde verbrauchen das Domain-Kontingent eines Mandanten nicht."""
import pytest
from fastapi import HTTPException

from app.api.routes import tenants as tenant_routes
from app.core.redis_client import get_redis_sync
from app.schemas.user import TenantDomainCreate
from tests.factories import make_current_user, make_tenant


def test_foreign_user_gets_403_and_does_not_count_against_quota(db):
    victim = make_tenant(db, "Opfer")
    attacker_tenant = make_tenant(db, "Angreifer")
    attacker = make_current_user(attacker_tenant.id, role="admin")
    key = f"ratelimit:tenant-domain-mutation:{victim.id}"
    redis = get_redis_sync()
    redis.delete(key)

    for _ in range(7):
        with pytest.raises(HTTPException) as exc:
            tenant_routes.create_tenant_domain(
                victim.public_id, TenantDomainCreate(purpose="app", domain="x.example.com"), db=db, user=attacker
            )
        assert exc.value.status_code == 403

    assert redis.get(key) is None
