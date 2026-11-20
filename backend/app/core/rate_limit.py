"""Zähler und Grenzen in Redis (Auth-Audit 2026-11-20: SEC-AUTH-002/-003/-005/-007/-019).

Gemeinsame Primitive für Mandanten- und Plattform-Login (der Admin-Branch ruft dieselben auf):

- **Schlüssel** sind immer ``ratelimit:<scope>:<HMAC(subject)>`` - nie E-Mail oder IP im
  Klartext, Länge fix (< 100 Byte). Eine 10-MiB-E-Mail erzeugt damit keinen 10-MiB-Schlüssel mehr.
- **Atomar** per Lua: Zählen und Ablauf setzen in einem Schritt (``EXPIRE`` nur, wenn der Schlüssel
  noch keinen Ablauf hat - repariert nebenbei Altschlüssel ohne TTL, SEC-AUTH-005).
- **Zählen vor Prüfen** (SEC-AUTH-003): ``SlidingCounter``s werden *vor* der teuren Prüfung
  (PBKDF2, TOTP) erhöht; geht die Prüfung gut, gibt ``refund`` den Versuch zurück. So kommen auch
  50 gleichzeitige Versuche nie über die Grenze hinaus.
- **Gleitendes Fenster** (zwei feste Fenster gewichtet, Audit 6.2) für Fehlversuchszähler,
  **GCRA** für Versuchsraten je Quelle.
- **Redis weg/voll** (Abschnitt 11): Fehler werden zu ``LimiterUnavailable``. Wer aufruft,
  entscheidet: ``enforce_rate_limit`` ist standardmässig fail-closed (503
  ``rate_limiter_unavailable``), mit ``fail_open=True`` greift eine lokale Notgrenze je Prozess.
  Jeder Ausfall wird gezählt und (gedrosselt) als Ereignis ``ratelimit.backend_error`` gemeldet.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import redis as redis_sync
from fastapi import HTTPException, status

from app.core.auth_pseudonym import counter_subject, normalize_email
from app.core.redis_client import get_redis_sync

_logger = logging.getLogger(__name__)

PREFIX = "ratelimit:"


class LimiterUnavailable(Exception):
    """Redis nicht erreichbar, zu langsam oder voll (noeviction/OOM)."""


def redis_key(scope: str, subject: str) -> str:
    return f"{PREFIX}{scope}:{counter_subject(scope, subject)}"


def _legacy_key(key: str) -> str:
    """Bestehende Aufrufer übergeben ``"<scope>:<subject>"`` - das Subjekt wird gehasht."""
    scope, _, subject = key.partition(":")
    return redis_key(scope, subject)


# ── Lua-Skripte ─────────────────────────────────────────────────────────

_FIXED_LUA = """
local out = {}
for i, key in ipairs(KEYS) do
  local n = redis.call('INCR', key)
  if redis.call('TTL', key) < 0 then redis.call('EXPIRE', key, tonumber(ARGV[i])) end
  out[i] = n
end
return out
"""

# ARGV: je Schlüssel (Fenster in s, Delta) - Delta 1 zählt, -1 gibt zurück, 0 liest nur.
# Rückgabe: geschätzte Zahl im gleitenden Fenster (aktuelles + gewichtetes vorheriges Fenster).
_SLIDING_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local out = {}
for i, base in ipairs(KEYS) do
  local window = tonumber(ARGV[2 * i - 1])
  local delta = tonumber(ARGV[2 * i])
  local w = window * 1000
  local idx = math.floor(now / w)
  local cur = base .. ':' .. idx
  local prev = base .. ':' .. (idx - 1)
  local c
  if delta > 0 then
    c = redis.call('INCRBY', cur, delta)
    if redis.call('TTL', cur) < 0 then redis.call('EXPIRE', cur, window * 2) end
  else
    c = tonumber(redis.call('GET', cur) or '0')
    if delta < 0 and c > 0 then c = redis.call('DECR', cur) end
  end
  local p = tonumber(redis.call('GET', prev) or '0')
  local weight = 1 - ((now - idx * w) / w)
  out[i] = math.floor(c + p * weight)
end
return out
"""

# GCRA (Generic Cell Rate Algorithm): ein Schlüssel je Subjekt, glatte Rate mit Burst.
# ARGV: Abstand je Versuch (ms), Burst (Anzahl). Rückgabe {erlaubt (1/0), warten_ms}.
_GCRA_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local emission = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local tat = tonumber(redis.call('GET', KEYS[1]) or now)
if tat < now then tat = now end
local new_tat = tat + emission
local allow_at = new_tat - burst * emission
if now < allow_at then return {0, math.ceil(allow_at - now)} end
redis.call('SET', KEYS[1], new_tat, 'PX', math.ceil(new_tat - now) + 1000)
return {1, 0}
"""

_scripts: dict[str, object] = {}
_scripts_lock = threading.Lock()


def _script(name: str, source: str):
    client = get_redis_sync()
    with _scripts_lock:
        script = _scripts.get(name)
        if script is None:
            script = client.register_script(source)
            _scripts[name] = script
    return script, client


def _run(name: str, source: str, keys: list[str], args: list) -> list:
    try:
        script, client = _script(name, source)
        return script(keys=keys, args=args, client=client)
    except (redis_sync.ConnectionError, redis_sync.TimeoutError) as exc:
        note_backend_error(exc)
        raise LimiterUnavailable(str(exc)) from exc
    except redis_sync.ResponseError as exc:
        # OOM command not allowed (maxmemory + noeviction) oder Skriptfehler
        note_backend_error(exc)
        raise LimiterUnavailable(str(exc)) from exc


# ── Ausfälle zählen (SEC-AUTH-012: ratelimit.backend_error) ─────────────

_backend_errors = 0
_last_reported = 0.0
_error_lock = threading.Lock()
_REPORT_INTERVAL_SECONDS = 60.0


def backend_error_count() -> int:
    return _backend_errors


def note_backend_error(exc: Exception) -> None:
    """Zählt einen Limiter-Ausfall und meldet ihn höchstens einmal je Minute und Prozess als
    Sicherheitsereignis (der Systemcheck ``rate_limiter`` alarmiert daraus)."""
    global _backend_errors, _last_reported
    with _error_lock:
        _backend_errors += 1
        now = time.monotonic()
        report = now - _last_reported >= _REPORT_INTERVAL_SECONDS
        if report:
            _last_reported = now
    _logger.warning("Rate-Limiter nicht verfügbar: %s", exc)
    if report:
        from app.auth_security import events

        events.record(event_type="ratelimit.backend_error", outcome="failure", details={"error": type(exc).__name__})


# ── Lokale Notgrenze (Redis weg) ────────────────────────────────────────


class _LocalWindow:
    """Feste Minutenfenster je Prozess, begrenzte Grösse. Nur Notbetrieb."""

    def __init__(self, max_keys: int = 20_000) -> None:
        self._data: OrderedDict[str, tuple[int, int]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def hit(self, key: str, *, limit: int, period_seconds: int) -> bool:
        window = int(time.monotonic() // period_seconds)
        with self._lock:
            start, count = self._data.get(key, (window, 0))
            if start != window:
                start, count = window, 0
            count += 1
            self._data[key] = (start, count)
            self._data.move_to_end(key)
            while len(self._data) > self._max_keys:
                self._data.popitem(last=False)
        return count <= limit

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


local_window = _LocalWindow()


def _unavailable_response() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "rate_limiter_unavailable", "message": "Anmeldeschutz vorübergehend nicht verfügbar, bitte gleich nochmals versuchen"},
        headers={"Retry-After": "30"},
    )


def _too_many(code: str, message: str, retry_after: int | None = None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": code, "message": message},
        headers={"Retry-After": str(retry_after)} if retry_after else None,
    )


# ── Feste Fenster (bestehende Aufrufer) ─────────────────────────────────


def enforce_rate_limit(key: str, *, limit: int, period_seconds: int, fail_open: bool = False) -> None:
    """Festes Fenster, atomar (INCR + EXPIRE in einem Skript). 429 ab ``limit + 1`` Treffern.

    ``key`` ist ``"<scope>:<subject>"``; das Subjekt (IP, E-Mail, ID ...) wird gehasht. Redis weg:
    fail-closed (503) oder mit ``fail_open=True`` lokale Notgrenze je Prozess."""
    try:
        count = int(_run("fixed", _FIXED_LUA, [_legacy_key(key)], [period_seconds])[0])
    except LimiterUnavailable as exc:
        if not fail_open:
            raise _unavailable_response() from exc
        if not local_window.hit(f"fixed:{key}", limit=limit, period_seconds=period_seconds):
            raise _too_many("rate_limited", "Too many requests, please try again later") from exc
        return
    if count > limit:
        raise _too_many("rate_limited", "Too many requests, please try again later")


# ── Gleitende Fenster: zählen vor prüfen ────────────────────────────────


@dataclass(frozen=True)
class SlidingCounter:
    scope: str
    subject: str
    window_seconds: int

    @property
    def key(self) -> str:
        return redis_key(self.scope, self.subject)


def _sliding(counters: list[SlidingCounter], delta: int) -> list[int]:
    if not counters:
        return []
    args: list[int] = []
    for counter in counters:
        args += [counter.window_seconds, delta]
    return [int(value) for value in _run("sliding", _SLIDING_LUA, [c.key for c in counters], args)]


def sliding_consume(counters: list[SlidingCounter]) -> list[int]:
    """Zählt einen Versuch auf jedem Zähler und liefert die neuen Stände (inkl. diesem Versuch)."""
    return _sliding(counters, 1)


def sliding_peek(counters: list[SlidingCounter]) -> list[int]:
    return _sliding(counters, 0)


def sliding_refund(counters: list[SlidingCounter]) -> None:
    """Gibt einen vorab gezählten Versuch zurück (Prüfung war erfolgreich). Fehler hier sind
    harmlos (der Versuch bleibt gezählt) und werden nicht weitergereicht."""
    try:
        _sliding(counters, -1)
    except LimiterUnavailable:
        pass


def gcra_allow(scope: str, subject: str, *, per_minute: int, burst: int) -> tuple[bool, int]:
    """Versuchsrate je Subjekt (GCRA). Liefert (erlaubt, warten in Sekunden)."""
    emission_ms = max(1, int(60_000 / max(1, per_minute)))
    allowed, wait_ms = _run("gcra", _GCRA_LUA, [redis_key(scope, subject)], [emission_ms, max(1, burst)])
    return bool(int(allowed)), max(1, int(wait_ms) // 1000) if not int(allowed) else 0


def hll_observe(scope: str, subject: str, member: str, *, window_seconds: int) -> int:
    """Zählt verschiedene Werte (HyperLogLog) je Subjekt im aktuellen Zeitfenster, z. B. «Konten je
    Netz» (Spraying) oder «Netze je Konto» (verteiltes Stuffing). Liefert die Schätzung."""
    bucket = int(time.time() // window_seconds)
    key = f"{redis_key(scope, subject)}:{bucket}"
    try:
        client = get_redis_sync()
        pipe = client.pipeline(transaction=True)
        pipe.pfadd(key, member)
        pipe.expire(key, window_seconds * 2)
        pipe.pfcount(key)
        return int(pipe.execute()[2])
    except redis_sync.RedisError as exc:
        note_backend_error(exc)
        raise LimiterUnavailable(str(exc)) from exc


def hll_count(scope: str, subject: str, *, window_seconds: int) -> int:
    bucket = int(time.time() // window_seconds)
    try:
        return int(get_redis_sync().pfcount(f"{redis_key(scope, subject)}:{bucket}"))
    except redis_sync.RedisError as exc:
        note_backend_error(exc)
        raise LimiterUnavailable(str(exc)) from exc


# ── Kontosperren (auch für den Plattform-Login) ─────────────────────────

# Login-Sperre (MAIN-SEC-007): pro Konto und Quell-IP eng, damit ein Angreifer ein fremdes
# Konto nur für sich selbst sperrt; pro Konto global höher. Die Werte stehen in den Settings
# (auth_account_ip_failures, auth_account_failures_known_only); diese Konstanten bleiben für
# den Plattform-Login, bis der Admin-Branch auf consume_login_attempt umgestellt ist.
LOGIN_LOCKOUT_PER_IP = 10
LOGIN_LOCKOUT_PER_ACCOUNT = 100
LOGIN_LOCKOUT_WINDOW_SECONDS = 15 * 60


def check_account_lockout(key: str, *, limit: int) -> None:
    """Nur lesend: 429 ``login_locked``, wenn ``key`` im aktuellen Fenster schon ``limit``
    Fehlversuche hat. Achtung: check-then-act (SEC-AUTH-003) - neue Aufrufer nehmen
    ``consume_attempt``. Bleibt für den Plattform-Login (Admin-Branch)."""
    try:
        raw = get_redis_sync().get(_legacy_key(key))
    except redis_sync.RedisError as exc:
        note_backend_error(exc)
        raise _unavailable_response() from exc
    if raw is not None and int(raw) >= limit:
        raise _too_many("login_locked", "Too many failed login attempts for this account, please try again later")


def record_failed_attempt(key: str, *, period_seconds: int) -> None:
    """Zählt einen Fehlversuch (atomar mit Ablauf, SEC-AUTH-005)."""
    try:
        _run("fixed", _FIXED_LUA, [_legacy_key(key)], [period_seconds])
    except LimiterUnavailable as exc:
        raise _unavailable_response() from exc


def consume_attempt(key: str, *, limit: int, period_seconds: int, code: str = "login_locked") -> int:
    """Zählt einen Versuch *vor* der Prüfung (festes Fenster, atomar) und wirft 429, wenn die
    Grenze überschritten ist. Rückgabe: Stand inkl. dieses Versuchs. Bei Erfolg der Prüfung
    ``release_attempt`` aufrufen, wenn nur Fehlversuche zählen sollen."""
    try:
        count = int(_run("fixed", _FIXED_LUA, [_legacy_key(key)], [period_seconds])[0])
    except LimiterUnavailable as exc:
        raise _unavailable_response() from exc
    if count > limit:
        raise _too_many(code, "Too many failed attempts, please try again later")
    return count


def release_attempt(key: str) -> None:
    try:
        client = get_redis_sync()
        redis_key_value = _legacy_key(key)
        if int(client.get(redis_key_value) or 0) > 0:
            client.decr(redis_key_value)
    except redis_sync.RedisError as exc:
        note_backend_error(exc)


def login_lockout_keys(scope: str, email: str, client_address: str | None) -> tuple[str, str]:
    """Schlüssel (vor dem Hashen) für Konto+Quelle und Konto. IPv6 wird als /64 gezählt."""
    from app.core.auth_pseudonym import source_address

    account = f"{scope}:{normalize_email(email)}"
    return f"{account}:ip:{source_address(client_address).exact}", account


def check_login_lockout(scope: str, email: str, client_address: str | None) -> None:
    ip_key, account_key = login_lockout_keys(scope, email, client_address)
    check_account_lockout(ip_key, limit=LOGIN_LOCKOUT_PER_IP)
    check_account_lockout(account_key, limit=LOGIN_LOCKOUT_PER_ACCOUNT)


def record_failed_login(scope: str, email: str, client_address: str | None) -> None:
    for key in login_lockout_keys(scope, email, client_address):
        record_failed_attempt(key, period_seconds=LOGIN_LOCKOUT_WINDOW_SECONDS)


def repair_keys_without_ttl(*, max_scan: int = 50_000, default_ttl: int = 24 * 3600) -> int:
    """Wartung (SEC-AUTH-005): ``ratelimit:*``-Schlüssel ohne Ablauf bekommen einen. Liefert die
    Zahl reparierter Schlüssel (> 0 deutet auf einen Fehler im Zähler-Code)."""
    client = get_redis_sync()
    repaired = 0
    for index, key in enumerate(client.scan_iter(f"{PREFIX}*", count=500)):
        if index >= max_scan:
            break
        if client.ttl(key) == -1:
            client.expire(key, default_ttl)
            repaired += 1
    return repaired
