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
Jedes Setzen/Aufheben erzeugt ein Ereignis ``block.set``/``block.clear`` mit gekürztem Subjekt,
Admin und (ab 1.7) Vorfall, damit der Verlauf der Sperren-Seite daraus entsteht.

1.6 - Netz-Fingerprint-Sperre (Bereich ``net_fp``): Anmeldeereignisse tragen als Netz-Pseudonym
``ip_fingerprint`` (/24 bzw. /48, identisch mit ``audit_log.ip_hash``), die Sperren dagegen eigene
Zähler-Pseudonyme. Eine Sperre aus einem Ereignis («Quelle sperren») sperrt deshalb direkt den
Fingerprint; ``is_blocked`` prüft ihn zusätzlich. Die Pseudonyme unterscheiden sich in der Länge
(Fingerprint 16, Zähler 24 Zeichen) und kollidieren so nie im selben Schlüsselraum.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, fields

import redis as redis_sync

from app.auth_security import events
from app.auth_security import context as request_context
from app.core.auth_pseudonym import counter_subject, net_hash, source_address
from app.core.config import settings
from app.core.rate_limit import LimiterUnavailable, SlidingCounter, note_backend_error, sliding_consume
from app.core.redis_client import get_redis_sync

_PREFIX = "authblock:src:"
_HISTORY = "authblock:history:"
# Abgewiesene Anmeldeversuche je Sperre (Zähler der Sperren-Seite, läuft mit der Sperre ab)
_HITS = "authblock:hits:"
MAX_AUTOMATIC_MINUTES = 24 * 60
MAX_MANUAL_MINUTES = 30 * 24 * 60
SCOPES = ("source", "net", "net_fp")
# Länge der gekürzten Pseudonyme in Ereignissen und Oberfläche (wie read_service._short)
SHORT = 12


@dataclass(frozen=True)
class Block:
    subject: str          # Pseudonym der Quelle
    scope: str            # "source" (/32, /64), "net" (/24, /48) oder "net_fp" (Netz-Fingerprint aus Ereignissen)
    until: int            # Unix-Zeit
    reason: str
    manual: bool
    stage: int
    # 1.6 (ältere Redis-Einträge haben sie nicht - Standardwerte)
    created: int = 0      # Unix-Zeit des Setzens bzw. der letzten Verlängerung
    minutes: int = 0      # gesetzte Dauer
    admin_id: int | None = None      # Plattform-Admin bei Stufe 5
    incident_id: int | None = None   # Vorfall (vorbereitet für 1.7, bis dahin immer None)
    repeat: int = 0       # automatisch: wievielte Sperre dieser Quelle in 7 Tagen

    @classmethod
    def from_json(cls, raw: str | bytes) -> Block:
        data = json.loads(raw)
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})

    @property
    def short(self) -> str:
        return self.subject[:SHORT]


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


def automatic_durations() -> list[int]:
    return _durations()


def _checked_subjects(ip: str | None) -> list[str]:
    subjects = [subject for _scope, subject in _subjects(ip)]
    fingerprint = net_hash(ip)
    if fingerprint:
        subjects.append(fingerprint)
    return subjects


def is_blocked(ip: str | None) -> Block | None:
    """Aktive Sperre dieser Quelle, ihres Netzes (/24, /48) oder ihres Netz-Fingerprints. Redis weg:
    keine Sperre (die Notgrenzen der Anmeldung greifen dann, siehe guard.py)."""
    try:
        client = get_redis_sync()
        values = client.mget([f"{_PREFIX}{subject}" for subject in _checked_subjects(ip)])
    except redis_sync.RedisError as exc:
        note_backend_error(exc)
        return None
    for raw in values:
        if raw:
            block = Block.from_json(raw)
            if block.until > time.time():
                return block
    return None


def count_rejection(block: Block) -> None:
    """Abgewiesener Anmeldeversuch durch diese Sperre (Zähler «Abgewiesen»). Best effort."""
    try:
        client = get_redis_sync()
        key = f"{_HITS}{block.subject}"
        client.incr(key)
        client.expire(key, max(60, block.until - int(time.time()) + 3600))
    except redis_sync.RedisError:
        pass


def rejections(subjects: list[str]) -> dict[str, int]:
    if not subjects:
        return {}
    try:
        values = get_redis_sync().mget([f"{_HITS}{subject}" for subject in subjects])
    except redis_sync.RedisError:
        return {}
    return {subject: int(value or 0) for subject, value in zip(subjects, values, strict=True)}


def get(subject: str) -> Block | None:
    raw = get_redis_sync().get(f"{_PREFIX}{subject}")
    if not raw:
        return None
    block = Block.from_json(raw)
    return block if block.until > time.time() else None


def _store(block: Block) -> None:
    client = get_redis_sync()
    ttl = max(1, block.until - int(time.time()))
    client.set(f"{_PREFIX}{block.subject}", json.dumps(block.__dict__), ex=ttl)


def _event(event_type: str, block: Block, *, reason: str, admin_id: int | None, tenant_id: int | None = None) -> None:
    """``block.set``/``block.clear`` mit gekürztem Subjekt, Admin und Vorfall. Setzt ein Admin die
    Sperre, gehört das Netz des Ereignisses nicht ihm, sondern der gesperrten Quelle: bei einer
    Fingerprint-Sperre ist das der Fingerprint selbst, sonst bleibt es leer (Adresse unbekannt)."""
    ctx = None
    if admin_id is not None:
        current = request_context.current()
        ctx = request_context.RequestContext(
            ip=None, net_hash=block.subject if block.scope == "net_fp" else None, ip_hash=None, private=False,
            request_id=current.request_id, user_agent_family=None, host=current.host, host_kind=current.host_kind,
            endpoint=current.endpoint, country=None,
        )
    events.record(
        ctx=ctx, event_type=event_type, outcome="info", platform_admin_id=admin_id, tenant_id=tenant_id,
        details={
            "reason": reason, "minutes": block.minutes, "stage": block.stage, "scope": block.scope, "subject": block.short,
            "admin_id": admin_id, "incident_id": block.incident_id, "kind": "manual" if block.manual else "automatic",
            "repeat": block.repeat or None,
        },
    )


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
    now = int(time.time())
    block = Block(subject=subject, scope=scope, until=now + minutes * 60, reason=reason, manual=False, stage=4, created=now, minutes=minutes, repeat=repeat)
    try:
        _store(block)
    except redis_sync.RedisError as exc:
        note_backend_error(exc)
        return None
    _event("block.set", block, reason=reason, admin_id=None, tenant_id=tenant_id)
    return block


def _check_subject(subject: str, scope: str) -> None:
    """Subjekte kommen nur aus eigenen Pseudonymen: Fingerprint 16 Hex-Zeichen, Zähler 24."""
    expected = 16 if scope == "net_fp" else 24
    if len(subject) != expected or any(ch not in "0123456789abcdef" for ch in subject):
        raise ValueError("ungültige Quelle")


def set_manual(*, ip: str | None = None, subject: str | None = None, scope: str = "source", minutes: int, reason: str, admin_id: int | None = None) -> Block:
    """Stufe 5: manuelle Sperre durch einen Plattform-Admin (Begründung und Ablauf Pflicht).
    ``scope="net_fp"`` sperrt einen Netz-Fingerprint aus einem Ereignis (``subject`` Pflicht) oder
    das Netz einer eingegebenen Adresse."""
    if not reason.strip():
        raise ValueError("Begründung fehlt")
    if scope not in SCOPES:
        raise ValueError("unbekannter Bereich")
    if subject:
        _check_subject(subject, scope)
    elif ip:
        subject = net_hash(ip) if scope == "net_fp" else subject_for(ip, scope)
    if not subject:
        raise ValueError("Quelle fehlt")
    minutes = max(1, min(int(minutes), MAX_MANUAL_MINUTES))
    now = int(time.time())
    block = Block(
        subject=subject, scope=scope, until=now + minutes * 60, reason=reason.strip()[:200], manual=True, stage=5,
        created=now, minutes=minutes, admin_id=admin_id,
    )
    _store(block)
    _event("block.set", block, reason="manual", admin_id=admin_id)
    return block


def extend(subject: str, *, minutes: int, reason: str, admin_id: int) -> Block | None:
    """Sperre verlängern = ab jetzt eine manuelle Sperre (Stufe 5) derselben Quelle, Ablauf um
    ``minutes`` später (höchstens 30 Tage ab jetzt). Auch eine automatische Sperre wird so manuell
    (User-Entscheid 2026-11-23); None, wenn es die Sperre nicht (mehr) gibt."""
    if not reason.strip():
        raise ValueError("Begründung fehlt")
    current = get(subject)
    if current is None:
        return None
    minutes = max(1, min(int(minutes), MAX_MANUAL_MINUTES))
    now = int(time.time())
    until = min(max(current.until, now) + minutes * 60, now + MAX_MANUAL_MINUTES * 60)
    block = Block(
        subject=current.subject, scope=current.scope, until=until, reason=reason.strip()[:200], manual=True, stage=5,
        created=now, minutes=max(1, (until - now) // 60), admin_id=admin_id, incident_id=current.incident_id,
    )
    _store(block)
    _event("block.set", block, reason="extend", admin_id=admin_id)
    return block


def clear(subject: str, *, admin_id: int | None = None) -> bool:
    client = get_redis_sync()
    raw = client.get(f"{_PREFIX}{subject}")
    removed = bool(client.delete(f"{_PREFIX}{subject}"))
    if removed:
        client.delete(f"{_HITS}{subject}")
        block = Block.from_json(raw) if raw else Block(subject=subject, scope="source", until=0, reason="", manual=False, stage=0)
        _event("block.clear", block, reason="manual" if admin_id else "cli", admin_id=admin_id)
    return removed


def active_blocks(limit: int = 500) -> list[Block]:
    client = get_redis_sync()
    blocks: list[Block] = []
    for key in client.scan_iter(f"{_PREFIX}*", count=200):
        raw = client.get(key)
        if raw:
            blocks.append(Block.from_json(raw))
        if len(blocks) >= limit:
            break
    return sorted(blocks, key=lambda block: block.until, reverse=True)
