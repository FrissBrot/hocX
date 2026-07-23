from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis_client import get_redis_sync
from app.models import Tenant, TenantDomain

_KEY_PREFIX = "domain_bridge:"
_TTL_SECONDS = 60


def create_bridge_token(user_id: int, tenant_id: int) -> str:
    """Single-use, short-lived token used to hand a session off from the main domain to a
    tenant's custom domain (cookies aren't shared across unrelated domains)."""
    token = secrets.token_urlsafe(32)
    redis = get_redis_sync()
    redis.set(f"{_KEY_PREFIX}{token}", f"{user_id}:{tenant_id}", nx=True, ex=_TTL_SECONDS)
    return token


def consume_bridge_token(token: str) -> tuple[int, int] | None:
    """Atomically reads and deletes the token so it can never be replayed."""
    redis = get_redis_sync()
    value = redis.getdel(f"{_KEY_PREFIX}{token}")
    if value is None:
        return None
    user_id_str, _, tenant_id_str = value.partition(":")
    try:
        return int(user_id_str), int(tenant_id_str)
    except ValueError:
        return None


def resolve_bridge_redirect(db: Session, request_host: str | None, user_id: int, tenant_id: int | None) -> str | None:
    """Returns the URL to send the browser to so its session ends up on whichever domain this
    tenant belongs on: their own healthy custom domain if they have one, otherwise the shared
    main domain. Returns None if the browser is already on that exact host - this is what makes
    it safe to call on every request (login, tenant switch, and passive session polling alike):
    it only ever redirects when the current host actually differs from the target, so a stable
    session converges to zero further redirects instead of looping.

    Symmetric by design - this is what makes switching tenants "just work" regardless of
    direction: main → custom domain, custom domain → main (target tenant has none), or one
    custom domain → another (switching between two domain-linked tenants).
    """
    if tenant_id is None or not settings.traefik_domain or request_host is None:
        return None

    domain_row = (
        db.query(TenantDomain)
        .filter(
            TenantDomain.tenant_id == tenant_id,
            TenantDomain.purpose == "app",
            TenantDomain.status == "active",
            TenantDomain.is_healthy.is_(True),
        )
        .one_or_none()
    )
    target_host = domain_row.domain if domain_row is not None else settings.traefik_domain

    if request_host == target_host:
        return None

    token = create_bridge_token(user_id, tenant_id)
    return f"https://{target_host}/api/auth/bridge?token={token}"


def resolve_tenant_by_app_domain(db: Session, domain: str) -> Tenant | None:
    """Looks up which tenant an active app-purpose custom domain belongs to - used to
    auto-select the right tenant on the login page when a visitor got bounced here from
    their org's own domain, without exposing a manual tenant picker."""
    row = (
        db.query(TenantDomain)
        .filter(TenantDomain.domain == domain, TenantDomain.purpose == "app", TenantDomain.status == "active")
        .one_or_none()
    )
    if row is None:
        return None
    return db.get(Tenant, row.tenant_id)
