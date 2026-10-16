from __future__ import annotations

from fastapi import HTTPException, status

from app.core.redis_client import get_redis_sync


def enforce_rate_limit(key: str, *, limit: int, period_seconds: int) -> None:
    """Fixed-window rate limit backed by Redis (INCR + EXPIRE-once). Raises 429 once `key` has
    been hit more than `limit` times within the current window. Intended for app-level limits
    on routes that Traefik's per-router rate limiting can't reach precisely (e.g. limits scoped
    per-tenant rather than per-source-IP)."""
    redis = get_redis_sync()
    redis_key = f"ratelimit:{key}"
    count = redis.incr(redis_key)
    if count == 1:
        redis.expire(redis_key, period_seconds)
    if count > limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests, please try again later")


def check_account_lockout(key: str, *, limit: int) -> None:
    """Read-only counterpart to record_failed_attempt: raises 429 if `key` has already recorded
    `limit` or more failed attempts within the current window, without itself counting as an
    attempt. Intended as a second, account-scoped line of defense against credential-stuffing
    alongside Traefik's per-source-IP rate limiting, which a distributed or shared-IP attacker
    can bypass."""
    redis = get_redis_sync()
    count = redis.get(f"ratelimit:{key}")
    if count is not None and int(count) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts for this account, please try again later",
        )


def record_failed_attempt(key: str, *, period_seconds: int) -> None:
    """Increments the failed-attempt counter checked by check_account_lockout. Only call this
    after an actual authentication failure, not on every request, so legitimate repeated logins
    don't lock an account out."""
    redis = get_redis_sync()
    redis_key = f"ratelimit:{key}"
    count = redis.incr(redis_key)
    if count == 1:
        redis.expire(redis_key, period_seconds)


# Login-Sperre (MAIN-SEC-007): pro Konto und Quell-IP eng, damit ein Angreifer ein fremdes
# Konto nur für sich selbst sperrt; pro Konto global deutlich höher als Bremse gegen
# verteiltes Raten über viele IPs.
LOGIN_LOCKOUT_PER_IP = 10
LOGIN_LOCKOUT_PER_ACCOUNT = 100
LOGIN_LOCKOUT_WINDOW_SECONDS = 15 * 60


def login_lockout_keys(scope: str, email: str, client_address: str | None) -> tuple[str, str]:
    account = f"{scope}:{email.strip().lower()}"
    return f"{account}:ip:{client_address or 'unknown'}", account


def check_login_lockout(scope: str, email: str, client_address: str | None) -> None:
    ip_key, account_key = login_lockout_keys(scope, email, client_address)
    check_account_lockout(ip_key, limit=LOGIN_LOCKOUT_PER_IP)
    check_account_lockout(account_key, limit=LOGIN_LOCKOUT_PER_ACCOUNT)


def record_failed_login(scope: str, email: str, client_address: str | None) -> None:
    for key in login_lockout_keys(scope, email, client_address):
        record_failed_attempt(key, period_seconds=LOGIN_LOCKOUT_WINDOW_SECONDS)

