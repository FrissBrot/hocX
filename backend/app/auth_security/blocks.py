"""Temporäre Sperren von Quellen (Audit Abschnitt 8.2/8.3, Stufe 4/5).

Stufen: 1 Monitoring (nur Ereignis) → 2 reduzierte Grenzen (L1/L2 weich) → 3 zusätzliche Prüfung
für unbekannte Geräte (L1/L2 hart oder hohes Risiko) → **4 temporäre Sperre** der Quelle für die
Anmelde-Endpunkte (nicht die ganze App), wenn Stufe 3 in 24 h ``auth_block_strikes``-mal erreicht
wurde. Dauer exponentiell je Wiederholung in 7 Tagen (``auth_block_minutes``, Standard
60 → 360 → 1440 Minuten, nie länger als 24 h automatisch). Stufe 5 (manuell) setzt ein
Plattform-Admin mit Begründung und Ablauf.

Gesperrt wird ein Pseudonym (HMAC der Quelle /32 bzw. /64, oder des Netzes /24), nie eine Adresse
im Klartext. Bekannte Geräte sind ausgenommen (Abschnitt 6.3). Plattform-Admins (Ziti) sind von
App-IP-Sperren ausgenommen: der Admin-Login ruft ``is_blocked`` bewusst nicht auf (Notfallzugang).
Jedes Setzen/Aufheben erzeugt ein Ereignis ``block.set``/``block.clear``.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import redis as redis_sync

from app.auth_security import events
from app.core.auth_pseudonym import counter_subject, source_address
from app.core.config import settings
from app.core.rate_limit import LimiterUnavailable, SlidingCounter, note_backend_error, sliding_consume
from app.core.redis_client import get_redis_sync

_PREFIX = "authblock:src:"
_HISTORY = "authblock:history:"
MAX_AUTOMATIC_MINUTES = 24 * 60
MAX_MANUAL_MINUTES = 30 * 24 * 60


@dataclass(frozen=True)
class Block:
    subject: str          # Pseudonym der Quelle
    scope: str            # "source" (/32, /64) oder "net" (/24)
    until: int            # Unix-Zeit
    reason: str
    manual: bool
    stage: int


def _subjects(ip: str | None) -> list[tuple[str, str]]:
    address = source_address(ip)
    subjects = [("source", counter_subject("block-source", address.exact))]
    if address.version is not None:
        # IPv4 /24, IPv6 /48 (Security-Review M5)
        subjects.append(("net", counter_subject("block-net", address.net)))
    return subjects


def subject_for(ip: str, scope: str = "source") -> str:
    address = source_address(ip)
    return counter_subject("block-net", address.net) if scope == "net" else counter_subject("block-source", address.exact)


def _durations() -> list[int]:
    values = [int(part) for part in settings.auth_block_minutes.split(",") if part.strip().isdigit()]
    return [min(value, MAX_AUTOMATIC_MINUTES) for value in values] or [60]


def is_blocked(ip: str | None) -> Block | None:
    """Aktive Sperre dieser Quelle (oder ihres /24). Redis weg: keine Sperre (die Notgrenzen der
    Anmeldung greifen dann, siehe guard.py)."""
    try:
        client = get_redis_sync()
        values = client.mget([f"{_PREFIX}{subject}" for _scope, subject in _subjects(ip)])
    except redis_sync.RedisError as exc:
        note_backend_error(exc)
        return None
    for raw in values:
        if raw:
            data = json.loads(raw)
            if int(data["until"]) > time.time():
                return Block(**data)
    return None


def _store(block: Block) -> None:
    client = get_redis_sync()
    ttl = max(1, block.until - int(time.time()))
    client.set(f"{_PREFIX}{block.subject}", json.dumps(block.__dict__), ex=ttl)


def strike(ip: str | None, *, reason: str, tenant_id: int | None = None) -> Block | None:
    """Stufe 3 erreicht: zählt einen «Strike» (24 h). Ab ``auth_block_strikes`` wird die Quelle
    gesperrt. Liefert die neue Sperre oder None."""
    if not ip:
        return None
    address = source_address(ip)
    try:
        (count,) = sliding_consume([SlidingCounter("block-strike", address.exact, 24 * 3600)])
        if count < settings.auth_block_strikes:
            return None
        client = get_redis_sync()
        # IPv6: das /48 sperren, sonst wechselt ein Angreifer einfach das /64
        scope = "net" if address.version == 6 else "source"
        subject = subject_for(ip, scope)
        if client.exists(f"{_PREFIX}{subject}"):
            return None
        history_key = f"{_HISTORY}{subject}"
        repeat = int(client.incr(history_key))
        client.expire(history_key, 7 * 24 * 3600)
    except (LimiterUnavailable, redis_sync.RedisError):
        return None
    durations = _durations()
    minutes = durations[min(repeat - 1, len(durations) - 1)]
    block = Block(subject=subject, scope=scope, until=int(time.time()) + minutes * 60, reason=reason, manual=False, stage=4)
    try:
        _store(block)
    except redis_sync.RedisError as exc:
        note_backend_error(exc)
        return None
    events.record(event_type="block.set", outcome="info", tenant_id=tenant_id, details={"reason": reason, "minutes": minutes, "stage": 4, "scope": scope})
    return block


def set_manual(*, ip: str | None = None, subject: str | None = None, scope: str = "source", minutes: int, reason: str, admin_id: int | None = None) -> Block:
    """Stufe 5: manuelle Sperre durch einen Plattform-Admin (Begründung und Ablauf Pflicht)."""
    if not reason.strip():
        raise ValueError("Begründung fehlt")
    if scope not in ("source", "net"):
        raise ValueError("unbekannter Bereich")
    subject = subject or (subject_for(ip, scope) if ip else None)
    if not subject:
        raise ValueError("Quelle fehlt")
    minutes = max(1, min(int(minutes), MAX_MANUAL_MINUTES))
    block = Block(subject=subject, scope=scope, until=int(time.time()) + minutes * 60, reason=reason.strip()[:200], manual=True, stage=5)
    _store(block)
    events.record(event_type="block.set", outcome="info", platform_admin_id=admin_id, details={"reason": "manual", "minutes": minutes, "stage": 5, "scope": scope})
    return block


def clear(subject: str, *, admin_id: int | None = None) -> bool:
    client = get_redis_sync()
    removed = bool(client.delete(f"{_PREFIX}{subject}"))
    if removed:
        events.record(event_type="block.clear", outcome="info", platform_admin_id=admin_id, details={"reason": "manual" if admin_id else "cli"})
    return removed


def active_blocks(limit: int = 500) -> list[Block]:
    client = get_redis_sync()
    blocks: list[Block] = []
    for key in client.scan_iter(f"{_PREFIX}*", count=200):
        raw = client.get(key)
        if raw:
            blocks.append(Block(**json.loads(raw)))
        if len(blocks) >= limit:
            break
    return sorted(blocks, key=lambda block: block.until, reverse=True)
