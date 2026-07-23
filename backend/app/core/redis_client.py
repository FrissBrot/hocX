from __future__ import annotations

import redis as redis_sync
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

_pool: ConnectionPool | None = None
_sync_pool: redis_sync.ConnectionPool | None = None


def get_redis() -> Redis:
    """Returns a lightweight Redis client bound to the shared connection pool."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    return Redis(connection_pool=_pool)


def get_redis_sync() -> redis_sync.Redis:
    """Synchronous counterpart of get_redis(), for use from the fully sync auth code path
    (login/select-tenant/bridge routes), which has no async context to await an async client in."""
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = redis_sync.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    return redis_sync.Redis(connection_pool=_sync_pool)


async def close_redis_pool() -> None:
    global _pool, _sync_pool
    if _pool is not None:
        await _pool.disconnect()
        _pool = None
    if _sync_pool is not None:
        _sync_pool.disconnect()
        _sync_pool = None
