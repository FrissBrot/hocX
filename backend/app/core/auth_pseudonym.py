"""Pseudonyme für den Anmeldeschutz (Auth-Audit 2026-11-20, SEC-AUTH-002/-012, Datenschutz).

Weder E-Mail-Adressen noch IP-Adressen landen im Klartext in Redis-Schlüsseln oder in
``auth_event``. Stattdessen HMAC mit einem aus ``AUTH_SECRET`` abgeleiteten Schlüssel je Zweck
(kein nackter Hash: eine bekannte Adresse liesse sich sonst durch Nachrechnen wiederfinden).

Stufen der Quelladresse (Audit Abschnitt 6.3):
- ``exact``: IPv4 /32, IPv6 /64 - für IPv6 ist ein /64 das, was ein Anschluss bekommt; einzelne
  /128 zu zählen hiesse, dass ein Angreifer 2^64 Quellen hat (SEC-AUTH-007).
- ``net``: IPv4 /24, IPv6 /64 - Schicht L2 der Zähler.
- ``wide``: IPv6 /48 (nur Monitoring, L3); IPv4: None.
- ``baseline``: IPv4 /24, IPv6 /48 - «bekanntes Netz» eines Kontos (90 Tage) und identisch mit
  ``audit_log.ip_hash`` (app/core/audit_context.ip_fingerprint), damit beide korrelierbar sind.

``rotating_source_hash`` (exakte Quelle) wechselt den Schlüssel jede Kalenderwoche: kurzfristige
Korrelation ja, Langzeitprofil einer Adresse nein (Abschnitt 10.1).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from app.core.audit_context import ip_fingerprint

_EMAIL_MAX = 320


def _secret() -> bytes:
    from app.core.config import settings

    return settings.auth_secret.encode("utf-8")


@lru_cache(maxsize=64)
def _derived(secret: bytes, purpose: str) -> bytes:
    return hmac.new(secret, f"hocx auth pseudonym v1:{purpose}".encode(), hashlib.sha256).digest()


def pseudonym(purpose: str, value: str, *, length: int = 32) -> str:
    """HMAC-SHA256(Schlüssel je Zweck, value), hex gekürzt. Länge fix - unabhängig von der Eingabe."""
    key = _derived(_secret(), purpose)
    return hmac.new(key, value.encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()[:length]


def normalize_email(email: str | None) -> str:
    """Kleingeschrieben, ohne Rand; überlange Eingaben werden (nur für den Schlüssel) gekürzt -
    die Schemas lassen ohnehin höchstens 320 Zeichen durch."""
    return (email or "").strip().lower()[:_EMAIL_MAX]


def subject_hash(email: str | None) -> str:
    """Pseudonym der eingegebenen Login-E-Mail (auch für Konten, die es nicht gibt: Spraying)."""
    return pseudonym("subject", normalize_email(email))


@dataclass(frozen=True)
class SourceAddress:
    raw: str | None
    version: int | None
    exact: str
    net: str
    wide: str | None
    baseline: str
    # Liegt die aufgelöste Adresse in einem privaten Netz (LAN, docker-proxy bei IPv6 ohne
    # Docker-IPv6, SEC-AUTH-019)?
    private: bool


@lru_cache(maxsize=4096)
def source_address(address: str | None) -> SourceAddress:
    try:
        ip = ipaddress.ip_address((address or "").strip())
    except ValueError:
        unknown = address or "unknown"
        return SourceAddress(raw=address, version=None, exact=f"x:{unknown[:64]}", net=f"x:{unknown[:64]}", wide=None, baseline=f"x:{unknown[:64]}", private=False)
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.version == 4:
        exact = str(ip)
        net = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        return SourceAddress(raw=address, version=4, exact=exact, net=net, wide=None, baseline=net, private=ip.is_private or ip.is_loopback)
    net64 = str(ipaddress.ip_network(f"{ip}/64", strict=False))
    net48 = str(ipaddress.ip_network(f"{ip}/48", strict=False))
    return SourceAddress(raw=address, version=6, exact=net64, net=net64, wide=net48, baseline=net48, private=ip.is_private or ip.is_loopback)


def net_hash(address: str | None) -> str | None:
    """Stabiles Pseudonym des Netzes (/24 bzw. /48) - identisch mit audit_log.ip_hash."""
    return ip_fingerprint(address)


def _iso_week(now: datetime | None = None) -> str:
    year, week, _ = (now or datetime.now(UTC)).isocalendar()
    return f"{year}-W{week:02d}"


def rotating_source_hash(address: str | None, *, now: datetime | None = None) -> str | None:
    """Exakte Quelle (/32 bzw. /64) mit wöchentlich wechselndem Schlüssel."""
    if not address:
        return None
    return pseudonym(f"source:{_iso_week(now)}", source_address(address).exact, length=16)


def counter_subject(kind: str, value: str) -> str:
    """Kurzes, festes Pseudonym für Redis-Zählerschlüssel (immer <= 100 Byte, SEC-AUTH-002)."""
    return pseudonym(f"counter:{kind}", value, length=24)
