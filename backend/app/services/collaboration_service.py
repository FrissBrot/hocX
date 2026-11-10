from __future__ import annotations

import json
import time

from redis.asyncio import Redis

LOCK_TTL_SECONDS = 60
PRESENCE_TTL_SECONDS = 90
# Index-Sets der Sperren (siehe unten) leben etwas länger als eine Sperre und werden beim Erwerb und
# Heartbeat verlängert; veraltete Einträge werden beim Lesen und beim Verbindungsende entfernt.
_INDEX_TTL_SECONDS = 5 * LOCK_TTL_SECONDS


def _presence_key(protocol_id: int) -> str:
    return f"hocx:presence:{protocol_id}"


def _lock_key(protocol_id: int, field_key: str) -> str:
    return f"hocx:lock:{protocol_id}:{field_key}"


def _lock_index_key(protocol_id: int, connection_id: str) -> str:
    return f"hocx:lock-index:{protocol_id}:{connection_id}"


def _protocol_locks_key(protocol_id: int) -> str:
    """Alle Feldschlüssel mit (möglicherweise) gehaltener Sperre in diesem Protokoll - ersetzt das
    SCAN über den ganzen Redis-Keyspace (Concurrency-Audit CONC-011)."""
    return f"hocx:locks:{protocol_id}"


def _cell_locks_key(protocol_id: int, block_field_key: str) -> str:
    """Zellsperren (block-<id>-cell-<r>-<c>) eines Matrixblocks."""
    return f"hocx:lock-cells:{protocol_id}:{block_field_key}"


def _block_of(field_key: str) -> str | None:
    return field_key.split("-cell-", 1)[0] if "-cell-" in field_key else None


def protocol_channel(protocol_id: int) -> str:
    return f"hocx:protocol:{protocol_id}:events"


def _parse_lock_payload(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


# Sperren atomar (Concurrency-Audit CONC-012): vorher GET-dann-SET/EXPIRE/DEL in mehreren
# Roundtrips - zwischen Ablauf und Neuvergabe konnten zwei Personen dieselbe Sperre halten bzw.
# eine fremde, gerade neu vergebene Sperre gelöscht werden.
_ACQUIRE = """
local current = redis.call('GET', KEYS[1])
if current then
  local ok, holder = pcall(cjson.decode, current)
  if ok and tostring(holder['user_id']) ~= ARGV[3] then
    return current
  end
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
return false
"""
_REFRESH = """
local current = redis.call('GET', KEYS[1])
if not current then return 0 end
local ok, holder = pcall(cjson.decode, current)
if not ok or tostring(holder['user_id']) ~= ARGV[1] then return 0 end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return 1
"""
_RELEASE = """
local current = redis.call('GET', KEYS[1])
if not current then return 0 end
local ok, holder = pcall(cjson.decode, current)
if not ok or tostring(holder['user_id']) ~= ARGV[1] then return 0 end
if ARGV[2] ~= '' and holder['connection_id'] ~= ARGV[2] then return 0 end
redis.call('DEL', KEYS[1])
return 1
"""


def get_lock_holder_sync(redis_client, protocol_id: int, field_key: str) -> dict | None:
    """Sync counterpart of CollaborationService.get_lock_holder, for REST write endpoints
    (protocol_elements.py) which run in a plain sync request handler with no event loop to
    await the async Redis client in. Same key format (_lock_key) as everything else here."""
    return _parse_lock_payload(redis_client.get(_lock_key(protocol_id, field_key)))


def conflicting_lock_holder_sync(redis_client, protocol_id: int, field_key: str, user_id: int) -> dict | None:
    """For REST writes: returns the lock holder info if `field_key` - or, for matrix blocks
    which lock per-cell (`block-<id>-cell-<row>-<col>`) rather than the whole block
    (`block-<id>`), any cell lock nested under it - is currently held by a *different* user
    than `user_id`. Returns None (write allowed) when unlocked entirely or already owned by
    the caller. Deliberately does NOT require the caller to hold a lock at all: several
    legitimate write paths (matrix row/column edits, attendance batch edits, API-only
    writers) never call lock_request in the first place, and requiring one here would break
    those single-player workflows instead of the two-editors-collide case this guards."""
    holder = get_lock_holder_sync(redis_client, protocol_id, field_key)
    if holder is not None and int(holder.get("user_id", -1)) != user_id:
        return holder
    cell_keys = sorted(redis_client.smembers(_cell_locks_key(protocol_id, field_key)) or ())
    if not cell_keys:
        return None
    values = redis_client.mget([_lock_key(protocol_id, cell) for cell in cell_keys])
    for cell, raw in zip(cell_keys, values):
        data = _parse_lock_payload(raw)
        if data is None:
            redis_client.srem(_cell_locks_key(protocol_id, field_key), cell)
        elif int(data.get("user_id", -1)) != user_id:
            return data
    return None


class CollaborationService:
    """Ephemeral Redis-backed presence, field locks and pub/sub for live protocol editing.
    Nothing here is persisted to Postgres - state naturally resets if Redis restarts,
    which is acceptable since it's a soft collaborative UX layer, not a source of truth.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def channel(self, protocol_id: int) -> str:
        return protocol_channel(protocol_id)

    async def publish(self, protocol_id: int, message: dict) -> None:
        await self.redis.publish(self.channel(protocol_id), json.dumps(message))

    # ── Präsenz ────────────────────────────────────────────────────────────────────────────

    async def join(self, protocol_id: int, connection_id: str, user_id: int, display_name: str) -> None:
        await self.touch(protocol_id, connection_id, user_id, display_name)

    async def touch(self, protocol_id: int, connection_id: str, user_id: int, display_name: str) -> None:
        """Präsenz dieser Verbindung auffrischen (beim Beitritt und bei jeder Revalidierung).
        Vorher setzte nur der Beitritt das TTL - 90 s nach dem letzten Beitritt verschwand die
        ganze Präsenzliste, obwohl alle verbunden waren (CONC-012)."""
        key = _presence_key(protocol_id)
        payload = json.dumps({"user_id": user_id, "display_name": display_name, "seen": int(time.time())})
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, connection_id, payload)
            pipe.expire(key, PRESENCE_TTL_SECONDS)
            await pipe.execute()

    async def leave(self, protocol_id: int, connection_id: str) -> None:
        await self.redis.hdel(_presence_key(protocol_id), connection_id)

    async def presence_snapshot(self, protocol_id: int) -> list[dict]:
        key = _presence_key(protocol_id)
        raw = await self.redis.hgetall(key)
        cutoff = int(time.time()) - PRESENCE_TTL_SECONDS
        by_user: dict[int, dict] = {}
        stale: list[str] = []
        for connection_id, value in raw.items():
            try:
                data = json.loads(value)
                if int(data.get("seen", 0)) < cutoff:
                    stale.append(connection_id)  # Verbindung ohne Abmeldung verschwunden
                    continue
                by_user[int(data["user_id"])] = {"user_id": data["user_id"], "display_name": data.get("display_name")}
            except (TypeError, ValueError, KeyError):
                continue
        if stale:
            await self.redis.hdel(key, *stale)
        return list(by_user.values())

    # ── Feldsperren ────────────────────────────────────────────────────────────────────────

    async def try_acquire_lock(
        self, protocol_id: int, field_key: str, connection_id: str, user_id: int, display_name: str
    ) -> dict | None:
        """Acquires the lock (or grants it if the same user already owns it). Returns the
        current holder info if a *different* user holds it, otherwise None on success."""
        key = _lock_key(protocol_id, field_key)
        payload = json.dumps({"user_id": user_id, "display_name": display_name, "connection_id": connection_id})
        holder = await self.redis.eval(_ACQUIRE, 1, key, payload, LOCK_TTL_SECONDS, str(user_id))
        if holder:
            return _parse_lock_payload(holder)
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.sadd(_lock_index_key(protocol_id, connection_id), field_key)
            pipe.expire(_lock_index_key(protocol_id, connection_id), _INDEX_TTL_SECONDS)
            pipe.sadd(_protocol_locks_key(protocol_id), field_key)
            pipe.expire(_protocol_locks_key(protocol_id), _INDEX_TTL_SECONDS)
            block = _block_of(field_key)
            if block is not None:
                pipe.sadd(_cell_locks_key(protocol_id, block), field_key)
                pipe.expire(_cell_locks_key(protocol_id, block), _INDEX_TTL_SECONDS)
            await pipe.execute()
        return None

    async def get_lock_holder(self, protocol_id: int, field_key: str) -> dict | None:
        """Non-mutating lock lookup - unlike refresh_lock, doesn't touch the TTL. Used to
        verify ownership before honoring a field_update broadcast."""
        return _parse_lock_payload(await self.redis.get(_lock_key(protocol_id, field_key)))

    async def holds_lock_for_broadcast(self, protocol_id: int, field_key: str, user_id: int) -> bool:
        """Whether `user_id` may broadcast a field_update for `field_key`: either they hold
        that exact lock, or - for matrix blocks, which lock per-cell
        (`block-<id>-cell-<row>-<col>`) rather than the whole block while still saving and
        broadcasting under the whole-block key `block-<id>` - they hold at least one cell
        lock nested under it."""
        holder = await self.get_lock_holder(protocol_id, field_key)
        if holder is not None and int(holder.get("user_id", -1)) == user_id:
            return True
        cells = sorted(await self.redis.smembers(_cell_locks_key(protocol_id, field_key)) or ())
        if not cells:
            return False
        values = await self.redis.mget([_lock_key(protocol_id, cell) for cell in cells])
        return any((data := _parse_lock_payload(raw)) is not None and int(data.get("user_id", -1)) == user_id for raw in values)

    async def refresh_lock(self, protocol_id: int, field_key: str, user_id: int) -> bool:
        refreshed = bool(await self.redis.eval(_REFRESH, 1, _lock_key(protocol_id, field_key), str(user_id), LOCK_TTL_SECONDS))
        if refreshed:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.expire(_protocol_locks_key(protocol_id), _INDEX_TTL_SECONDS)
                block = _block_of(field_key)
                if block is not None:
                    pipe.expire(_cell_locks_key(protocol_id, block), _INDEX_TTL_SECONDS)
                await pipe.execute()
        return refreshed

    async def connection_lock_count(self, protocol_id: int, connection_id: str) -> int:
        return int(await self.redis.scard(_lock_index_key(protocol_id, connection_id)) or 0)

    async def release_lock(self, protocol_id: int, field_key: str, user_id: int, connection_id: str) -> bool:
        released = bool(await self.redis.eval(_RELEASE, 1, _lock_key(protocol_id, field_key), str(user_id), ""))
        if released:
            await self._forget(protocol_id, connection_id, field_key)
        return released

    async def _forget(self, protocol_id: int, connection_id: str, field_key: str) -> None:
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.srem(_lock_index_key(protocol_id, connection_id), field_key)
            pipe.srem(_protocol_locks_key(protocol_id), field_key)
            block = _block_of(field_key)
            if block is not None:
                pipe.srem(_cell_locks_key(protocol_id, block), field_key)
            await pipe.execute()

    async def release_all_for_connection(self, protocol_id: int, connection_id: str) -> list[str]:
        index_key = _lock_index_key(protocol_id, connection_id)
        field_keys = await self.redis.smembers(index_key)
        released: list[str] = []
        for field_key in field_keys:
            existing = _parse_lock_payload(await self.redis.get(_lock_key(protocol_id, field_key)))
            if existing is None:
                # Inzwischen abgelaufen: nur noch die Index-Einträge entfernen.
                await self._forget(protocol_id, connection_id, field_key)
                continue
            if existing.get("connection_id") != connection_id:
                continue
            if await self.redis.eval(_RELEASE, 1, _lock_key(protocol_id, field_key), str(existing.get("user_id")), connection_id):
                released.append(field_key)
                await self._forget(protocol_id, connection_id, field_key)
        await self.redis.delete(index_key)
        return released

    async def locks_snapshot(self, protocol_id: int) -> dict[str, dict]:
        index = _protocol_locks_key(protocol_id)
        field_keys = sorted(await self.redis.smembers(index) or ())
        if not field_keys:
            return {}
        values = await self.redis.mget([_lock_key(protocol_id, field_key) for field_key in field_keys])
        result: dict[str, dict] = {}
        expired: list[str] = []
        for field_key, raw in zip(field_keys, values):
            data = _parse_lock_payload(raw)
            if data is None:
                expired.append(field_key)
            else:
                result[field_key] = data
        if expired:
            await self.redis.srem(index, *expired)
        return result
