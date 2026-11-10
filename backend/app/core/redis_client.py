from __future__ import annotations

import redis as redis_sync
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

# Concurrency-Audit CONC-011: ohne Timeouts hing jeder Aufruf unbegrenzt, wenn Redis zwar erreichbar,
# aber blockiert war (Speicherdruck, Fork beim Snapshot) - sync-Aufrufe hielten Threads, async-
# Aufrufe Coroutines fest. Befehle bekommen kurze Fristen; Pub/Sub-Verbindungen warten bewusst
# beliebig lange auf Nachrichten und prüfen die Verbindung stattdessen per health_check_interval.
_CONNECT_TIMEOUT_SECONDS = 2
_SOCKET_TIMEOUT_SECONDS = 3
_HEALTH_CHECK_SECONDS = 30

_pool: ConnectionPool | None = None
_pubsub_pool: ConnectionPool | None = None
_sync_pool: redis_sync.ConnectionPool | None = None


def _common() -> dict:
    return {"decode_responses": True, "password": settings.redis_password or None, "socket_connect_timeout": _CONNECT_TIMEOUT_SECONDS, "health_check_interval": _HEALTH_CHECK_SECONDS}


def get_redis() -> Redis:
    """Returns a lightweight Redis client bound to the shared connection pool."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(settings.redis_url, socket_timeout=_SOCKET_TIMEOUT_SECONDS, **_common())
    return Redis(connection_pool=_pool)


def get_redis_pubsub() -> Redis:
    """Für Pub/Sub-Abonnements (Kollaboration): ohne socket_timeout, sonst bräche das Warten auf
    die nächste Nachricht nach wenigen Sekunden Ruhe ab."""
    global _pubsub_pool
    if _pubsub_pool is None:
        _pubsub_pool = ConnectionPool.from_url(settings.redis_url, **_common())
    return Redis(connection_pool=_pubsub_pool)


def get_redis_sync() -> redis_sync.Redis:
    """Synchronous counterpart of get_redis(), for use from the fully sync auth code path
    (login/select-tenant/bridge routes), which has no async context to await an async client in."""
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = redis_sync.ConnectionPool.from_url(settings.redis_url, socket_timeout=_SOCKET_TIMEOUT_SECONDS, **_common())
    return redis_sync.Redis(connection_pool=_sync_pool)


async def close_redis_pool() -> None:
    global _pool, _pubsub_pool, _sync_pool
    for pool in (_pool, _pubsub_pool):
        if pool is not None:
            await pool.disconnect()
    _pool = _pubsub_pool = None
    if _sync_pool is not None:
        _sync_pool.disconnect()
        _sync_pool = None


def publish_best_effort(channel: str, message: str) -> None:
    """Live-Hinweis an offene Editoren nach einem bereits gespeicherten Vorgang. Ist Redis gerade
    nicht erreichbar, bleibt das Speichern gültig (Concurrency-Audit CONC-011) - die anderen sehen
    die Änderung dann beim nächsten Laden."""
    import logging

    try:
        get_redis_sync().publish(channel, message)
    except redis_sync.RedisError:
        logging.getLogger(__name__).warning("Live-Hinweis an %s nicht gesendet (Redis nicht erreichbar)", channel, exc_info=True)
