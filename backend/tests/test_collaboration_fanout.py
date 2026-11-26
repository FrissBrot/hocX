"""Collaboration-Audit F-02: ein Pub/Sub-Abo je Prozess, Verteilung an lokale Sockets.

Gegen das echte Test-Redis. Der Pool ist bewusst auf 2 Verbindungen begrenzt: mit einer
Verbindung je Socket (vorher) scheiterte schon die dritte Anmeldung mit MaxConnectionsError.
"""
from __future__ import annotations

import asyncio
import random

import pytest
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings
from app.services.collaboration_fanout import CollaborationFanout, Subscription, SubscriptionClosed


def _channel(protocol_id: int) -> str:
    return f"hocx:collab:{protocol_id}"


def _protocol_ids() -> tuple[int, int]:
    base = random.randint(10**8, 10**9)
    # 1 und 11: gleiche Präfixe dürfen sich nicht vermischen (exakter Kanalvergleich)
    return base, base * 10 + 1


def _small_pool() -> ConnectionPool:
    return ConnectionPool.from_url(settings.redis_url, decode_responses=True, max_connections=2)


async def _drain(subscription: Subscription, timeout: float = 0.3) -> list[str]:
    received: list[str] = []
    while True:
        try:
            received.append(await asyncio.wait_for(subscription.get(), timeout))
        except asyncio.TimeoutError:
            return received


async def _wait_subscribed(publisher: Redis, channel: str, count: int = 1) -> None:
    for _ in range(100):
        numsub = dict(await publisher.pubsub_numsub(channel))
        if numsub.get(channel, 0) >= count:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"{channel} nicht abonniert")


def test_many_sockets_share_one_connection_and_only_get_their_protocol():
    protocol_a, protocol_b = _protocol_ids()

    async def scenario():
        pool = _small_pool()
        fanout = CollaborationFanout(lambda: Redis(connection_pool=pool))
        publisher = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            subs_a = [await fanout.subscribe(_channel(protocol_a)) for _ in range(150)]
            subs_b = [await fanout.subscribe(_channel(protocol_b)) for _ in range(30)]
            assert fanout.local_subscriber_count() == 180
            await _wait_subscribed(publisher, _channel(protocol_a))
            await _wait_subscribed(publisher, _channel(protocol_b))
            # Ein Abo je Kanal und Prozess, nicht eines je Socket
            numsub = dict(await publisher.pubsub_numsub(_channel(protocol_a), _channel(protocol_b)))
            assert numsub == {_channel(protocol_a): 1, _channel(protocol_b): 1}

            await publisher.publish(_channel(protocol_a), '{"n":1}')
            await publisher.publish(_channel(protocol_a), '{"n":2}')
            await publisher.publish(_channel(protocol_b), '{"b":1}')
            for sub in subs_a:
                assert await asyncio.wait_for(sub.get(), 2) == '{"n":1}'
                assert await asyncio.wait_for(sub.get(), 2) == '{"n":2}'
            for sub in subs_b:
                assert await asyncio.wait_for(sub.get(), 2) == '{"b":1}'
            # Nichts landet beim falschen Protokoll
            assert await _drain(subs_a[0]) == []
            assert await _drain(subs_b[0]) == []
        finally:
            await fanout.close()
            await publisher.aclose()
            await pool.disconnect()

    asyncio.run(scenario())


def test_last_local_socket_unsubscribes_the_channel():
    protocol_a, _ = _protocol_ids()

    async def scenario():
        pool = _small_pool()
        fanout = CollaborationFanout(lambda: Redis(connection_pool=pool))
        publisher = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            first = await fanout.subscribe(_channel(protocol_a))
            second = await fanout.subscribe(_channel(protocol_a))
            await _wait_subscribed(publisher, _channel(protocol_a))
            await fanout.unsubscribe(first)
            assert fanout.local_subscriber_count(_channel(protocol_a)) == 1
            await publisher.publish(_channel(protocol_a), "x")
            assert await asyncio.wait_for(second.get(), 2) == "x"
            assert await _drain(first) == []
            await fanout.unsubscribe(second)
            for _ in range(100):
                if dict(await publisher.pubsub_numsub(_channel(protocol_a))).get(_channel(protocol_a), 0) == 0:
                    break
                await asyncio.sleep(0.02)
            assert dict(await publisher.pubsub_numsub(_channel(protocol_a)))[_channel(protocol_a)] == 0
            # Erneut anmelden funktioniert über dieselbe Verbindung
            again = await fanout.subscribe(_channel(protocol_a))
            await _wait_subscribed(publisher, _channel(protocol_a))
            await publisher.publish(_channel(protocol_a), "y")
            assert await asyncio.wait_for(again.get(), 2) == "y"
        finally:
            await fanout.close()
            await publisher.aclose()
            await pool.disconnect()

    asyncio.run(scenario())


def test_slow_socket_is_closed_without_affecting_others():
    subscription = Subscription("hocx:collab:1", maxsize=2)

    async def scenario():
        subscription._deliver("a")
        subscription._deliver("b")
        subscription._deliver("c")  # voll -> geschlossen
        with pytest.raises(SubscriptionClosed) as closed:
            await subscription.get()
        assert closed.value.reason == "overflow"

    asyncio.run(scenario())


class _BrokenPubSub:
    def __init__(self) -> None:
        self.closed = False
        self.fail = asyncio.Event()

    async def subscribe(self, *channels):
        return None

    async def unsubscribe(self, *channels):
        return None

    async def get_message(self, **kwargs):
        await self.fail.wait()
        raise ConnectionError("redis weg")

    async def aclose(self):
        self.closed = True


class _BrokenRedis:
    def __init__(self) -> None:
        self.created: list[_BrokenPubSub] = []

    def pubsub(self, **kwargs):
        pubsub = _BrokenPubSub()
        self.created.append(pubsub)
        return pubsub


def test_listener_failure_is_recorded_and_closes_all_local_sockets():
    errors: list[Exception] = []
    redis = _BrokenRedis()

    async def scenario():
        fanout = CollaborationFanout(lambda: redis, on_error=errors.append)
        subs = [await fanout.subscribe("hocx:collab:1"), await fanout.subscribe("hocx:collab:2")]
        redis.created[0].fail.set()
        for sub in subs:
            with pytest.raises(SubscriptionClosed) as closed:
                await asyncio.wait_for(sub.get(), 2)
            assert closed.value.reason == "listener_failed"
        assert len(errors) == 1 and isinstance(errors[0], ConnectionError)
        assert redis.created[0].closed
        assert fanout.local_subscriber_count() == 0
        # Danach baut die nächste Anmeldung eine frische Verbindung auf
        await fanout.subscribe("hocx:collab:1")
        assert len(redis.created) == 2
        await fanout.close()

    asyncio.run(scenario())


def test_slow_socket_is_closed_on_byte_budget():
    subscription = Subscription("hocx:collab:1", maxsize=100, max_bytes=10)

    async def scenario():
        subscription._deliver("12345")
        assert await subscription.get() == "12345"
        subscription._deliver("1234567")
        subscription._deliver("1234")  # 11 Bytes > 10 -> geschlossen
        with pytest.raises(SubscriptionClosed) as closed:
            await subscription.get()
        assert closed.value.reason == "overflow"

    asyncio.run(scenario())
