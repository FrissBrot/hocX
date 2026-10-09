from __future__ import annotations

import redis as redis_sync

from app.core.config import settings

_sync_pool: redis_sync.ConnectionPool | None = None


def get_redis_sync() -> redis_sync.Redis:
    """Synchroner Redis-Client fuer die Caches (Kartenkacheln, Hoehenprofil)."""
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = redis_sync.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    return redis_sync.Redis(connection_pool=_sync_pool)
