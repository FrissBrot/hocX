"""Token-Bucket je Anbieter und Konto (Plan §8.3), zusätzlich zu ``Retry-After``.

Anbieter drosseln je App und Konto/Tenant; wer gleichmässig bleibt, bekommt kaum 429. Jeder
API-Aufruf eines Adapters (``ProviderContext.with_token``) nimmt vorher ein Token aus dem Eimer
``cloud_import_bucket:<anbieter>:<konto>`` in Redis. Backend (Ordnerbaum) und job-worker (Auflisten,
Download) teilen sich damit dasselbe Budget.

- Rate und Grösse legt der Adapter fest (``CloudProvider.request_rate = (pro_sekunde, burst)``,
  ``None`` = ohne Bremse). Gleicher Mechanismus für alle Adapter.
- Fehlt ein Token kurz (≤ MAX_INLINE_WAIT s), wird gewartet; sonst ``ProviderThrottled`` mit der
  Wartezeit - der Auftrag pausiert wie bei einem 429 (``import_job.not_before``).
- Redis nicht erreichbar: Ersatz-Eimer je Prozess (fail-open mit lokaler Grenze), der Import
  bleibt nicht stehen.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time

from app.services.cloud_import.http import ProviderThrottled

_logger = logging.getLogger(__name__)

MAX_INLINE_WAIT = 2.0
_PREFIX = "cloud_import_bucket:"

# KEYS[1] Eimer; ARGV: rate (Token/s), burst, jetzt (s, float), Kosten
_LUA = """
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = burst; ts = now end
tokens = math.min(burst, tokens + math.max(0, now - ts) * rate)
local wait = 0
if tokens >= cost then
  tokens = tokens - cost
else
  wait = (cost - tokens) / rate
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], math.ceil(burst / rate) + 60)
return tostring(wait)
"""

_local_lock = threading.Lock()
_local: dict[str, tuple[float, float]] = {}


def _key(provider: str, account: str) -> str:
    # Konto nur gehasht (keine Kontokennung im Klartext in Redis)
    return f"{_PREFIX}{provider}:{hashlib.sha256(account.encode('utf-8')).hexdigest()[:32]}"


def _take_local(key: str, rate: float, burst: int, now: float) -> float:
    with _local_lock:
        tokens, ts = _local.get(key, (float(burst), now))
        tokens = min(float(burst), tokens + max(0.0, now - ts) * rate)
        if tokens >= 1:
            _local[key] = (tokens - 1, now)
            return 0.0
        _local[key] = (tokens, now)
        return (1 - tokens) / rate


def take(provider: str, account: str, rate: tuple[float, int] | None) -> float:
    """Wartezeit in Sekunden, bis ein Aufruf erlaubt ist (0 = sofort, Token entnommen)."""
    if not rate:
        return 0.0
    per_second, burst = rate
    key = _key(provider, account)
    now = time.time()
    try:
        from app.core.redis_client import get_redis_sync

        return float(get_redis_sync().eval(_LUA, 1, key, per_second, burst, now, 1))
    except Exception:  # noqa: BLE001 - Redis weg: lokale Grenze statt Stillstand (siehe Docstring)
        _logger.info("Cloud-Import: Token-Bucket ohne Redis, lokale Grenze")
        return _take_local(key, per_second, burst, now)


def pacer(provider: str, account: str, rate: tuple[float, int] | None):
    """Funktion für ``ProviderContext(pace=...)``: wartet kurz oder meldet Drosselung."""

    def pace() -> None:
        wait = take(provider, account, rate)
        if wait <= 0:
            return
        if wait <= MAX_INLINE_WAIT:
            time.sleep(wait)
            # Nach dem Warten erneut nehmen (andere Prozesse teilen den Eimer)
            again = take(provider, account, rate)
            if again <= 0:
                return
            wait = again
        raise ProviderThrottled(max(1, math.ceil(wait)), status=429)

    return pace
