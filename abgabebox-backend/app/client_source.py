"""Quelle einer öffentlichen Anfrage für Grenzen je Besucher (wie backend app/core/client_ip.py).

X-Forwarded-For wird nur ausgewertet, wenn die Verbindung von einem vertrauenswürdigen Proxy kommt
(Traefik im Compose-Netz, ``trusted_proxy_cidrs``), und zwar von rechts: der erste Eintrag, der
nicht selbst ein vertrauenswürdiger Proxy ist. ``rate_limit_source`` zählt IPv4 je Adresse und
IPv6 je /64 - ein Anschluss hat ein ganzes /64, Grenzen je /128 liessen sich sonst mit jeder neuen
Adresse umgehen (gleiche Regel wie backend ``rate_limit_source``).
"""
from __future__ import annotations

import ipaddress
from functools import lru_cache

from starlette.requests import HTTPConnection

from app.config import settings


@lru_cache(maxsize=8)
def _networks(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(part.strip(), strict=False) for part in raw.split(",") if part.strip())


def _is_trusted(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in _networks(settings.trusted_proxy_cidrs))


def client_ip(request: HTTPConnection) -> str:
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded or not _is_trusted(peer):
        return peer
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop):
            return hop
    return hops[0] if hops else peer


def source_key(address: str | None) -> str:
    """IPv4 (auch IPv4-in-IPv6) je Adresse, IPv6 je /64, Unlesbares gekürzt als eigener Schlüssel."""
    try:
        ip = ipaddress.ip_address((address or "").strip())
    except ValueError:
        return f"x:{(address or 'unknown')[:64]}"
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.version == 4:
        return str(ip)
    return str(ipaddress.ip_network(f"{ip}/64", strict=False))


def rate_limit_source(request: HTTPConnection) -> str:
    return source_key(client_ip(request))
