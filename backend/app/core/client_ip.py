"""Echte Client-IP hinter Traefik (MAIN-SEC-007).

Traefik vertraut ohne `forwardedHeaders.trustedIPs` keinen vom Client mitgeschickten
X-Forwarded-*-Headern und setzt X-Forwarded-For selbst auf die Quelladresse. Der Header wird
trotzdem nur ausgewertet, wenn die Verbindung von einem vertrauenswürdigen Proxy kommt
(`trusted_proxy_cidrs`, Default: private Netze, in denen Traefik im Compose-Netz liegt) - wer
das Backend direkt erreicht, kann seine Adresse so nicht fälschen. Ausgewertet wird von rechts:
der erste Eintrag, der nicht selbst ein vertrauenswürdiger Proxy ist.
"""
from __future__ import annotations

import ipaddress
from functools import lru_cache

from starlette.requests import HTTPConnection

from app.core.config import settings


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
    # Alle Einträge im eigenen Netz (z. B. Zugriff aus dem LAN): ursprünglichster Eintrag.
    return hops[0] if hops else peer
