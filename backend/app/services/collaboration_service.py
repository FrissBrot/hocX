from __future__ import annotations

import json

from redis.asyncio import Redis

LOCK_TTL_SECONDS = 60
PRESENCE_TTL_SECONDS = 90


def _presence_key(protocol_id: int) -> str:
    return f"hocx:presence:{protocol_id}"


def _lock_key(protocol_id: int, field_key: str) -> str:
    return f"hocx:lock:{protocol_id}:{field_key}"


def _lock_index_key(protocol_id: int, connection_id: str) -> str:
    return f"hocx:lock-index:{protocol_id}:{connection_id}"


class CollaborationService:
    """Ephemeral Redis-backed presence, field locks and pub/sub for live protocol editing.

    Nothing here is persisted to Postgres - state naturally resets if Redis restarts,
    which is acceptable since it's a soft collaborative UX layer, not a source of truth.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def channel(self, protocol_id: int) -> str:
        return f"hocx:protocol:{protocol_id}:events"

    async def publish(self, protocol_id: int, message: dict) -> None:
        await self.redis.publish(self.channel(protocol_id), json.dumps(message))

    async def join(self, protocol_id: int, connection_id: str, user_id: int, display_name: str) -> None:
        key = _presence_key(protocol_id)
        await self.redis.hset(key, connection_id, json.dumps({"user_id": user_id, "display_name": display_name}))
        await self.redis.expire(key, PRESENCE_TTL_SECONDS)

    async def leave(self, protocol_id: int, connection_id: str) -> None:
        await self.redis.hdel(_presence_key(protocol_id), connection_id)

    async def presence_snapshot(self, protocol_id: int) -> list[dict]:
        raw = await self.redis.hgetall(_presence_key(protocol_id))
        by_user: dict[int, dict] = {}
        for value in raw.values():
            try:
                data = json.loads(value)
                by_user[int(data["user_id"])] = data
            except (TypeError, ValueError, KeyError):
                continue
        return list(by_user.values())

    async def try_acquire_lock(
        self, protocol_id: int, field_key: str, connection_id: str, user_id: int, display_name: str
    ) -> dict | None:
        """Acquires the lock (or grants it if the same user already owns it). Returns the
        current holder info if a *different* user holds it, otherwise None on success."""
        key = _lock_key(protocol_id, field_key)
        payload = json.dumps({"user_id": user_id, "display_name": display_name, "connection_id": connection_id})
        if await self.redis.set(key, payload, nx=True, ex=LOCK_TTL_SECONDS):
            await self.redis.sadd(_lock_index_key(protocol_id, connection_id), field_key)
            return None
        existing_raw = await self.redis.get(key)
        existing = json.loads(existing_raw) if existing_raw else None
        if existing is not None and int(existing.get("user_id", -1)) != user_id:
            return existing
        # Either the lock expired in the race between SET and GET, or it's already
        # owned by this same user (e.g. a second tab) - (re)claim it for this connection.
        await self.redis.set(key, payload, ex=LOCK_TTL_SECONDS)
        await self.redis.sadd(_lock_index_key(protocol_id, connection_id), field_key)
        return None

    async def refresh_lock(self, protocol_id: int, field_key: str, user_id: int) -> bool:
        key = _lock_key(protocol_id, field_key)
        existing_raw = await self.redis.get(key)
        if not existing_raw:
            return False
        existing = json.loads(existing_raw)
        if int(existing.get("user_id", -1)) != user_id:
            return False
        await self.redis.expire(key, LOCK_TTL_SECONDS)
        return True

    async def release_lock(self, protocol_id: int, field_key: str, user_id: int, connection_id: str) -> bool:
        key = _lock_key(protocol_id, field_key)
        existing_raw = await self.redis.get(key)
        if not existing_raw:
            return False
        existing = json.loads(existing_raw)
        if int(existing.get("user_id", -1)) != user_id:
            return False
        await self.redis.delete(key)
        await self.redis.srem(_lock_index_key(protocol_id, connection_id), field_key)
        return True

    async def release_all_for_connection(self, protocol_id: int, connection_id: str) -> list[str]:
        index_key = _lock_index_key(protocol_id, connection_id)
        field_keys = await self.redis.smembers(index_key)
        released: list[str] = []
        for field_key in field_keys:
            key = _lock_key(protocol_id, field_key)
            existing_raw = await self.redis.get(key)
            if not existing_raw:
                continue
            existing = json.loads(existing_raw)
            if existing.get("connection_id") == connection_id:
                await self.redis.delete(key)
                released.append(field_key)
        await self.redis.delete(index_key)
        return released

    async def locks_snapshot(self, protocol_id: int) -> dict[str, dict]:
        prefix = _lock_key(protocol_id, "")
        result: dict[str, dict] = {}
        async for key in self.redis.scan_iter(match=f"{prefix}*"):
            raw = await self.redis.get(key)
            if not raw:
                continue
            field_key = key[len(prefix):]
            try:
                result[field_key] = json.loads(raw)
            except (TypeError, ValueError):
                continue
        return result
