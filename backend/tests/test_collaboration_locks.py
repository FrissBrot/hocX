"""Concurrency-Audit CONC-011/-012: Feldsperren atomar (Lua), Zellsperren über Index-Sets statt
Keyspace-SCAN, Präsenz mit Zeitstempel statt einmaligem TTL, Sperrprüfung fail open."""

import asyncio
import json
import random
import time

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.redis_client import get_redis, get_redis_sync
from app.services import collaboration_service as module
from app.services.collaboration_service import CollaborationService, conflicting_lock_holder_sync


def _protocol() -> int:
    return random.randint(10**8, 10**9)


def _run(coro):
    async def wrapper():
        try:
            return await coro
        finally:
            await get_redis().connection_pool.disconnect()

    return asyncio.run(wrapper())


def test_lock_is_exclusive_reclaimable_and_only_released_by_its_holder():
    protocol_id = _protocol()

    async def scenario():
        collab = CollaborationService(get_redis())
        assert await collab.try_acquire_lock(protocol_id, "block-1", "c1", 1, "Anna") is None
        holder = await collab.try_acquire_lock(protocol_id, "block-1", "c2", 2, "Bruno")
        assert holder["user_id"] == 1
        # Gleiche Person, zweiter Tab: übernimmt
        assert await collab.try_acquire_lock(protocol_id, "block-1", "c3", 1, "Anna") is None
        assert await collab.release_lock(protocol_id, "block-1", 2, "c2") is False
        assert await collab.refresh_lock(protocol_id, "block-1", 2) is False
        assert await collab.refresh_lock(protocol_id, "block-1", 1) is True
        assert await collab.release_lock(protocol_id, "block-1", 1, "c3") is True
        assert await collab.locks_snapshot(protocol_id) == {}

    _run(scenario())


def test_cell_locks_are_found_without_scanning_the_keyspace(monkeypatch):
    protocol_id = _protocol()

    async def scenario():
        collab = CollaborationService(get_redis())
        await collab.try_acquire_lock(protocol_id, "block-7-cell-1-2", "c1", 1, "Anna")
        assert await collab.holds_lock_for_broadcast(protocol_id, "block-7", 1) is True
        assert await collab.holds_lock_for_broadcast(protocol_id, "block-7", 2) is False
        snapshot = await collab.locks_snapshot(protocol_id)
        assert set(snapshot) == {"block-7-cell-1-2"}

    def no_scan(*args, **kwargs):
        raise AssertionError("SCAN über den Keyspace")

    redis_sync = get_redis_sync()
    monkeypatch.setattr(type(redis_sync), "scan_iter", no_scan)
    _run(scenario())
    holder = conflicting_lock_holder_sync(redis_sync, protocol_id, "block-7", 2)
    assert holder is not None and holder["user_id"] == 1
    assert conflicting_lock_holder_sync(redis_sync, protocol_id, "block-7", 1) is None


def test_expired_cell_lock_is_pruned_from_the_index():
    protocol_id = _protocol()
    redis_sync = get_redis_sync()

    async def scenario():
        await CollaborationService(get_redis()).try_acquire_lock(protocol_id, "block-9-cell-0-0", "c1", 1, "Anna")

    _run(scenario())
    redis_sync.delete(module._lock_key(protocol_id, "block-9-cell-0-0"))  # wie abgelaufen
    assert conflicting_lock_holder_sync(redis_sync, protocol_id, "block-9", 2) is None
    assert not redis_sync.smembers(module._cell_locks_key(protocol_id, "block-9"))


def test_presence_survives_long_sessions_and_drops_dead_connections():
    protocol_id = _protocol()
    redis_sync = get_redis_sync()

    async def scenario():
        collab = CollaborationService(get_redis())
        await collab.join(protocol_id, "alive", 1, "Anna")
        await collab.join(protocol_id, "dead", 2, "Bruno")
        # "dead" hat sich seit über PRESENCE_TTL_SECONDS nicht gemeldet
        redis_sync.hset(module._presence_key(protocol_id), "dead", json.dumps({"user_id": 2, "display_name": "Bruno", "seen": int(time.time()) - 1000}))
        await collab.touch(protocol_id, "alive", 1, "Anna")
        return await collab.presence_snapshot(protocol_id)

    presence = _run(scenario())
    assert [entry["user_id"] for entry in presence] == [1]
    assert redis_sync.ttl(module._presence_key(protocol_id)) > 0


def test_block_write_proceeds_when_redis_is_unreachable(monkeypatch):
    from app.api.routes import protocol_elements
    from tests.factories import make_current_user

    def unreachable(*args, **kwargs):
        raise RedisConnectionError("down")

    monkeypatch.setattr(protocol_elements, "conflicting_lock_holder_sync", unreachable)
    # Wirft nicht (vorher 500 für jeden Protokoll-Schreibvorgang)
    protocol_elements._ensure_block_not_locked_by_other(1, 2, make_current_user(1))


def test_publish_after_save_is_best_effort(monkeypatch):
    from app.core import redis_client

    class Broken:
        def publish(self, *args):
            raise RedisConnectionError("down")

    monkeypatch.setattr(redis_client, "get_redis_sync", lambda: Broken())
    redis_client.publish_best_effort("hocx:protocol:1:events", "{}")


def test_client_field_keys_are_validated():
    from app.api.routes import collaboration_ws as ws

    good = ["block-7", "block-0f3c1e9a-1b2c-4d5e-8f90-123456789abc", "block-0f3c1e9a-1b2c-4d5e-8f90-123456789abc-cell-r1-2"]
    bad = ["block-7" + "x" * 300, "hocx:lock:1:x", "block-7 *", "element-titles", "block-7-cell-" + "a" * 200]
    assert all(ws._LOCK_FIELD_KEY.match(key) for key in good)
    assert not any(ws._LOCK_FIELD_KEY.match(key) for key in bad)
    assert ws._BROADCAST_FIELD_KEY.match("element-titles") and not ws._BROADCAST_FIELD_KEY.match("a" * 161)


def test_connection_lock_count_and_cleanup_of_expired_locks():
    protocol_id = _protocol()
    redis_sync = get_redis_sync()

    async def scenario():
        collab = CollaborationService(get_redis())
        for index in range(3):
            await collab.try_acquire_lock(protocol_id, f"block-{index}", "c1", 1, "Anna")
        assert await collab.connection_lock_count(protocol_id, "c1") == 3
        redis_sync.delete(module._lock_key(protocol_id, "block-0"))  # abgelaufen
        released = await collab.release_all_for_connection(protocol_id, "c1")
        assert sorted(released) == ["block-1", "block-2"]

    _run(scenario())
    assert not redis_sync.smembers(module._protocol_locks_key(protocol_id))
    assert 0 < redis_sync.ttl(module._protocol_locks_key(protocol_id)) or not redis_sync.exists(module._protocol_locks_key(protocol_id))
