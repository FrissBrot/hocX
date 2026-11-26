"""Ein Redis-Pub/Sub-Abonnement je Prozess für die Live-Zusammenarbeit (Collaboration-Audit F-02).

Vorher öffnete jede WebSocket-Verbindung ein eigenes Pub/Sub-Abo und damit eine eigene
Redis-Verbindung aus dem Pub/Sub-Pool (redis-py: höchstens 100). Ab rund 100 offenen
Protokoll-Editoren je Backend-Prozess scheiterte jeder weitere Verbindungsaufbau mit
``MaxConnectionsError``, plattformweit über alle Mandanten.

Jetzt hält jeder Prozess genau eine Pub/Sub-Verbindung. Ein Listener-Task liest alle Nachrichten
und verteilt sie im Prozess an die Sockets, die sich für genau diesen Kanal angemeldet haben.

Mandantentrennung: Ein Kanal gehört zu genau einem Protokoll (``hocx:collab:<interne id>``,
global eindeutig). Ein Socket meldet sich erst an, nachdem Sitzung, Mandant und Leserecht für
dieses Protokoll geprüft sind, und bekommt ausschliesslich Nachrichten des Kanals, für den er
angemeldet ist (exakter Vergleich des Kanalnamens, kein Muster-Abo).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from redis.asyncio import Redis

from app.core.redis_client import get_redis_pubsub

logger = logging.getLogger(__name__)

# Höchstens so viele Nachrichten warten je Socket. Ein Socket, der nicht nachkommt (z. B. sehr
# langsame Leitung), wird geschlossen und verbindet sich neu, statt alle anderen aufzuhalten oder
# den Speicher zu füllen (vorher trennte Redis selbst einen zu langsamen Abonnenten).
SUBSCRIBER_QUEUE_SIZE = 1000
# Zusätzlich höchstens so viele Bytes je Socket (Nachrichten bis 64 KiB, --ws-max-size): vorher
# begrenzte Redis den Puffer eines Abonnenten (client-output-buffer-limit), jetzt der Prozess.
SUBSCRIBER_MAX_BYTES = 4 * 1024 * 1024
# Takt, in dem der Listener ohne Nachrichten erneut liest; dabei prüft redis-py die Verbindung
# (health_check_interval) - ein blockierendes Lesen ohne Frist bemerkte eine tote Verbindung nie.
_POLL_SECONDS = 1.0


class SubscriptionClosed(Exception):
    """Das Abo endet: Listener ausgefallen (``reason="listener_failed"``) oder der Socket kam
    nicht nach (``reason="overflow"``). Der Socket wird geschlossen, der Client verbindet neu."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Subscription:
    """Anmeldung eines Sockets an einem Kanal; ``get()`` liefert die nächste Nachricht."""

    def __init__(self, channel: str, maxsize: int = SUBSCRIBER_QUEUE_SIZE, max_bytes: int = SUBSCRIBER_MAX_BYTES) -> None:
        self.channel = channel
        self._queue: asyncio.Queue[str | SubscriptionClosed] = asyncio.Queue(maxsize=maxsize)
        self._max_bytes = max_bytes
        self._queued_bytes = 0
        self.closed_reason: str | None = None

    def _deliver(self, data: str) -> None:
        if self.closed_reason is not None:
            return
        if self._queued_bytes + len(data) > self._max_bytes:
            self._close("overflow")
            return
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            self._close("overflow")
            return
        self._queued_bytes += len(data)

    def _close(self, reason: str) -> None:
        if self.closed_reason is not None:
            return
        self.closed_reason = reason
        # Wartende Nachrichten verwerfen: der Client lädt nach dem Neuverbinden ohnehin neu.
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queued_bytes = 0
        self._queue.put_nowait(SubscriptionClosed(reason))

    async def get(self) -> str:
        item = await self._queue.get()
        if isinstance(item, SubscriptionClosed):
            raise item
        self._queued_bytes -= len(item)
        return item


class CollaborationFanout:
    """Ein Pub/Sub-Abo je Prozess (und Event-Loop), Verteilung an lokale Sockets."""

    def __init__(self, redis_factory: Callable[[], Redis] = get_redis_pubsub, *, on_error: Callable[[Exception], None] | None = None) -> None:
        self._redis_factory = redis_factory
        self._on_error = on_error
        self._subscribers: dict[str, set[Subscription]] = {}
        self._pubsub = None
        self._task: asyncio.Task | None = None
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Anmeldung ─────────────────────────────────────────────────────────────────────────────

    def _bind_loop(self) -> None:
        """Zustand gehört zum laufenden Event-Loop. In Produktion gibt es je Worker genau einen;
        in Tests startet jeder Testclient einen neuen - der alte Zustand ist dort unbrauchbar."""
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        self._loop = loop
        self._lock = asyncio.Lock()
        self._subscribers = {}
        self._pubsub = None
        self._task = None

    async def subscribe(self, channel: str) -> Subscription:
        """Meldet einen Socket an. Wirft bei Redis-Fehlern (der Aufrufer schliesst dann mit 1013)."""
        self._bind_loop()
        assert self._lock is not None
        subscription = Subscription(channel)
        async with self._lock:
            if self._pubsub is None:
                self._pubsub = self._redis_factory().pubsub(ignore_subscribe_messages=True)
            local = self._subscribers.get(channel)
            if local is None:
                # Erst abonnieren, dann eintragen: scheitert das Abo, bleibt nichts zurück.
                await self._pubsub.subscribe(channel)
                local = self._subscribers[channel] = set()
            local.add(subscription)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._listen(self._pubsub))
        return subscription

    async def unsubscribe(self, subscription: Subscription) -> None:
        if self._loop is not asyncio.get_running_loop() or self._lock is None:
            return
        async with self._lock:
            local = self._subscribers.get(subscription.channel)
            if local is None or subscription not in local:
                return
            local.discard(subscription)
            if local:
                return
            del self._subscribers[subscription.channel]
            if self._pubsub is not None:
                try:
                    await self._pubsub.unsubscribe(subscription.channel)
                except Exception:
                    # Bleibt der Kanal abonniert, kommen nur unbeachtete Nachrichten an; der
                    # Listener verwirft sie (kein lokaler Empfänger). Fällt Redis aus, merkt es
                    # der Listener und meldet den Fehler selbst.
                    logger.warning("Pub/Sub-Abmeldung von %s fehlgeschlagen", subscription.channel, exc_info=True)

    def local_subscriber_count(self, channel: str | None = None) -> int:
        if channel is not None:
            return len(self._subscribers.get(channel, ()))
        return sum(len(local) for local in self._subscribers.values())

    # ── Listener ──────────────────────────────────────────────────────────────────────────────

    def _dispatch(self, channel: str, data: str) -> None:
        # Nur die Sockets genau dieses Kanals (= dieses Protokolls) bekommen die Nachricht.
        for subscription in tuple(self._subscribers.get(channel, ())):
            subscription._deliver(data)

    async def _listen(self, pubsub) -> None:
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=_POLL_SECONDS)
                if message is None or message.get("type") != "message":
                    continue
                channel = message.get("channel")
                data = message.get("data")
                if isinstance(channel, bytes):
                    channel = channel.decode()
                if isinstance(data, bytes):
                    data = data.decode()
                if isinstance(channel, str) and isinstance(data, str):
                    self._dispatch(channel, data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Läuft ausserhalb jedes Requests: selbst melden (CLAUDE.md, Fehlererfassung).
            if self._on_error is not None:
                try:
                    await asyncio.to_thread(self._on_error, exc)
                except Exception:
                    logger.exception("Fehler beim Melden eines Pub/Sub-Ausfalls")
            else:
                logger.exception("Pub/Sub-Listener der Zusammenarbeit ausgefallen")
            await self._fail_all(pubsub)

    async def _fail_all(self, pubsub) -> None:
        """Listener ausgefallen: alle lokalen Sockets schliessen (sie verbinden sich neu und
        abonnieren dann über eine frische Verbindung), Zustand zurücksetzen."""
        assert self._lock is not None
        async with self._lock:
            if self._pubsub is not pubsub:
                return
            subscribers, self._subscribers = self._subscribers, {}
            self._pubsub = None
            self._task = None
        for local in subscribers.values():
            for subscription in local:
                subscription._close("listener_failed")
        try:
            await pubsub.aclose()
        except Exception:
            logger.debug("Pub/Sub-Verbindung liess sich nicht schliessen", exc_info=True)

    async def close(self) -> None:
        """Beim Herunterfahren: Listener beenden, Verbindung schliessen."""
        if self._loop is not asyncio.get_running_loop():
            return
        task, pubsub = self._task, self._pubsub
        self._task = None
        self._pubsub = None
        for local in self._subscribers.values():
            for subscription in local:
                subscription._close("shutdown")
        self._subscribers = {}
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception:
                logger.debug("Pub/Sub-Verbindung liess sich nicht schliessen", exc_info=True)


def _record_listener_error(exc: Exception) -> None:
    from app.core.db import SessionLocal
    from app.core.error_log import record_system_error

    db = SessionLocal()
    try:
        record_system_error(db, exc=exc)
    finally:
        db.close()


_fanout = CollaborationFanout(on_error=_record_listener_error)


def get_collaboration_fanout() -> CollaborationFanout:
    return _fanout
