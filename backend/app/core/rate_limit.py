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
