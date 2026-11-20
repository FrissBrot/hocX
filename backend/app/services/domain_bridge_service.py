from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis_client import get_redis_sync
from app.models import Tenant, TenantDomain
from app.services import traefik_config_service

# v3 (MAIN-SEC-006): the token carries "user_id:mfa:target_host" and is only redeemable on that
# host, after the user confirmed the handoff on a page there. The prefix changed with the
# format, so a still-live v2 token can never be misread. 120 s leave time for the confirmation.
# v4 (Auth-Audit 2026-11-20, SEC-AUTH-011): zusätzlich die Session-ID der Ausgangs-Session, damit
# die Session auf der Ziel-Domain als Kind registriert wird (Logout-Kaskade). v3-Tokens (vor dem
# Update ausgestellt, höchstens 120 s alt) werden weiter eingelöst.
_KEY_PREFIX = "domain_bridge_v4:"
_LEGACY_PREFIX = "domain_bridge_v3:"
_TTL_SECONDS = 120
# SEC-AUTH-020: /auth/session fragt auf der falschen Domain bei jedem Abruf ein Token an - für
# dieselbe Session und dasselbe Ziel wird das noch gültige Token wiederverwendet.
_ISSUED_PREFIX = "domain_bridge_issued:"
_REUSE_SECONDS = 90


@dataclass(frozen=True)
class BridgeToken:
    user_id: int
    mfa_verified: bool
    target_host: str
    parent_sid: str | None = None
    # v3-Token von vor dem Update (ohne Eltern-Session, höchstens 120 s alt)
    legacy: bool = False


def create_bridge_token(user_id: int, target_host: str, *, mfa_verified: bool = False, parent_sid: str | None = None) -> str:
    """Single-use, short-lived token used to hand a session off from the main domain to a
    tenant's custom domain (cookies aren't shared across unrelated domains)."""
    redis = get_redis_sync()
    issued_key = f"{_ISSUED_PREFIX}{user_id}:{parent_sid or '-'}:{int(bool(mfa_verified))}:{target_host}"
    existing = redis.get(issued_key)
    if existing and redis.exists(f"{_KEY_PREFIX}{existing}"):
        return existing
    token = secrets.token_urlsafe(32)
    redis.set(f"{_KEY_PREFIX}{token}", f"{user_id}:{int(bool(mfa_verified))}:{parent_sid or '-'}:{target_host}", nx=True, ex=_TTL_SECONDS)
    redis.set(issued_key, token, ex=_REUSE_SECONDS)
    return token


def _parse(value: str | None, request_host: str | None, *, legacy: bool = False) -> BridgeToken | None:
    if value is None:
        return None
    try:
        if legacy:
            user_id_str, mfa_str, target_host = value.split(":", 2)
            sid = "-"
        else:
            user_id_str, mfa_str, sid, target_host = value.split(":", 3)
        parsed = BridgeToken(int(user_id_str), mfa_str == "1", target_host, None if sid == "-" else sid, legacy)
    except (TypeError, ValueError):
        return None
    # Nur auf der Domain einlösbar, für die das Token ausgestellt wurde.
    if request_host is None or request_host.lower() != parsed.target_host.lower():
        return None
    return parsed


def peek_bridge_token(token: str, request_host: str | None) -> BridgeToken | None:
    """Reads the token without consuming it (for the confirmation page)."""
    redis = get_redis_sync()
    value = redis.get(f"{_KEY_PREFIX}{token}")
    if value is not None:
        return _parse(value, request_host)
    return _parse(redis.get(f"{_LEGACY_PREFIX}{token}"), request_host, legacy=True)


def token_predates_session_revoke(session_revoke_at: datetime | None) -> bool:
    """Wurden die Sessions des Kontos beendet, seit das Token höchstens ausgestellt sein kann
    (Passwortwechsel, Deaktivierung, MFA-Reset)? Dann darf das Token keine neue Session mehr
    erzeugen."""
    return session_revoke_at is not None and session_revoke_at > datetime.now(UTC) - timedelta(seconds=_TTL_SECONDS)


def consume_bridge_token(token: str, request_host: str | None) -> BridgeToken | None:
    """Atomically reads and deletes the token so it can never be replayed. A token presented
    on the wrong host is consumed too (and rejected), so a leaked link is dead afterwards."""
    redis = get_redis_sync()
    value = redis.getdel(f"{_KEY_PREFIX}{token}")
    if value is not None:
        return _parse(value, request_host)
    return _parse(redis.getdel(f"{_LEGACY_PREFIX}{token}"), request_host, legacy=True)


def resolve_bridge_redirect(
    db: Session,
    request_host: str | None,
    user_id: int,
    tenant_id: int,
    *,
    mfa_verified: bool = False,
    parent_sid: str | None = None,
) -> str | None:
    """Returns the URL to send the browser to so its session ends up on whichever domain this
    tenant belongs on: their own healthy custom domain if they have one, otherwise the shared
    main domain. Returns None if the browser is already on that exact host - this is what makes
    it safe to call on every request (login and passive session polling alike): it only ever
    redirects when the current host actually differs from the target, so a stable session
    converges to zero further redirects instead of looping.
    """
    if not settings.traefik_domain or request_host is None or not parent_sid:
        return None

    domain_row = (
        db.query(TenantDomain)
        .filter(
            TenantDomain.tenant_id == tenant_id,
            TenantDomain.purpose == "app",
            TenantDomain.status == "active",
            TenantDomain.is_healthy.is_(True),
            # security-audit FEAT-01: don't rely on is_healthy alone staying in sync after a
            # feature revoke - check the current booking directly too.
            TenantDomain.tenant_id.in_(traefik_config_service.tenant_ids_with_custom_domain_feature(db)),
        )
        .one_or_none()
    )
    target_host = domain_row.domain if domain_row is not None else settings.traefik_domain

    if request_host == target_host:
        return None

    token = create_bridge_token(user_id, target_host, mfa_verified=mfa_verified, parent_sid=parent_sid)
    # Token im URL-Fragment (SEC-019): der Browser schickt es an keinen Server, es landet weder in
    # Access-Logs noch im Referer; die Bestätigungsseite liest es aus und entfernt es aus dem Verlauf.
    return f"https://{target_host}/auth/bridge#{urlencode({'token': token})}"


def resolve_tenant_by_app_domain(db: Session, domain: str) -> Tenant | None:
    """Looks up which tenant an active app-purpose custom domain belongs to - used to
    auto-select the right tenant on the login page when a visitor got bounced here from
    their org's own domain, without exposing a manual tenant picker."""
    row = (
        db.query(TenantDomain)
        .filter(
            TenantDomain.domain == domain,
            TenantDomain.purpose == "app",
            TenantDomain.status == "active",
            TenantDomain.tenant_id.in_(traefik_config_service.tenant_ids_with_custom_domain_feature(db)),
        )
        .one_or_none()
    )
    if row is None:
        return None
    return db.get(Tenant, row.tenant_id)
