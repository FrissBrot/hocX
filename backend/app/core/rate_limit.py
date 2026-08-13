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
