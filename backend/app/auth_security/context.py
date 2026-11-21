"""Merkmale des laufenden Requests für Anmeldeschutz und Ereignisse - nur als Pseudonyme."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core import geoip
from app.core.audit_context import current_client_ip, current_request_meta
from app.core.auth_pseudonym import net_hash, rotating_source_hash, source_address

_BROWSERS = (
    ("Edge", re.compile(r"Edg(e|A|iOS)?/")),
    ("Opera", re.compile(r"OPR/|Opera")),
    ("Samsung Internet", re.compile(r"SamsungBrowser/")),
    ("Firefox", re.compile(r"Firefox/|FxiOS/")),
    ("Chrome", re.compile(r"Chrome/|CriOS/")),
    ("Safari", re.compile(r"Safari/")),
)
_SYSTEMS = (
    ("iOS", re.compile(r"iPhone|iPad|iPod")),
    ("Android", re.compile(r"Android")),
    ("Windows", re.compile(r"Windows")),
    ("macOS", re.compile(r"Mac OS X|Macintosh")),
    ("ChromeOS", re.compile(r"CrOS")),
    ("Linux", re.compile(r"Linux")),
)


def user_agent_family(user_agent: str | None) -> str | None:
    """Grobe Gerätebeschreibung («Firefox · Windows») - keine Versionen, kein Fingerprint.
    Nur Anzeige und schwaches Signal (fälschbar, Audit 7.2: Gewicht nie > 5)."""
    if not user_agent:
        return None
    browser = next((name for name, pattern in _BROWSERS if pattern.search(user_agent)), None)
    system = next((name for name, pattern in _SYSTEMS if pattern.search(user_agent)), None)
    parts = [part for part in (browser, system) if part]
    return " · ".join(parts) if parts else "?"


def host_kind(host: str | None) -> str | None:
    from app.core.config import settings

    if not host:
        return None
    if settings.traefik_admin_domain and host == settings.traefik_admin_domain:
        return "admin"
    if not settings.traefik_domain or host == settings.traefik_domain or host in ("localhost", "127.0.0.1"):
        return "main"
    return "custom"


@dataclass(frozen=True)
class RequestContext:
    ip: str | None
    net_hash: str | None
    ip_hash: str | None
    private: bool
    request_id: str | None
    user_agent_family: str | None
    host: str | None
    host_kind: str | None
    endpoint: str | None
    # Ländercode (app/core/geoip.py, lokal), None ohne GeoIP-Datenbank oder bei privater Adresse
    country: str | None = None


def current(ip: str | None = None) -> RequestContext:
    meta = current_request_meta()
    address = ip if ip is not None else current_client_ip()
    host = meta.get("host")
    return RequestContext(
        ip=address,
        net_hash=net_hash(address),
        ip_hash=rotating_source_hash(address),
        private=source_address(address).private if address else False,
        request_id=meta.get("request_id"),
        user_agent_family=user_agent_family(meta.get("user_agent")),
        host=host,
        host_kind=host_kind(host),
        endpoint=meta.get("path"),
        country=geoip.country_for(address),
    )
