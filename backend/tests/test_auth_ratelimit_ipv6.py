"""Öffentliche Auth-Endpunkte zählen IPv6-Quellen je /64 (SEC-AUTH-007, wie der Login in T4).

Ein Anschluss bekommt typischerweise ein ganzes /64; mit Grenzen je exakter Adresse (/128) genügt
es, für jeden Aufruf eine neue Adresse aus dem eigenen Präfix zu nehmen, um die Grenze nie zu
erreichen (Nachtlauf 2026-11-23, Feld auth-session/auth).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes import auth as auth_routes
from app.core import rate_limit
from app.core.redis_client import get_redis_sync
from app.schemas.notifications import AccountLinkToken

TRAEFIK_PEER = "172.20.0.5"  # vertrauenswürdiger Proxy im Compose-Netz (trusted_proxy_cidrs)


def _flush() -> None:
    client = get_redis_sync()
    for key in client.scan_iter("ratelimit:*"):
        client.delete(key)
    rate_limit.local_window.clear()


@pytest.fixture(autouse=True)
def _clean():
    _flush()
    yield
    _flush()


def _request_from(address: str, path: str) -> Request:
    return Request({
        "type": "http", "method": "POST", "path": path, "query_string": b"",
        "headers": [(b"x-forwarded-for", address.encode())], "client": (TRAEFIK_PEER, 40000),
    })


def _status(call) -> int:
    try:
        call()
    except HTTPException as exc:
        return exc.status_code
    return 200


def test_tenant_by_domain_limit_counts_an_ipv6_64_as_one_source(db):
    codes = [
        _status(lambda i=i: auth_routes.tenant_by_domain("unbekannt.example", _request_from(f"2001:db8:7:7::{i:x}", "/api/auth/tenant-by-domain"), db))
        for i in range(1, 26)
    ]
    assert codes[:20] == [404] * 20
    assert 429 in codes[20:]


def test_account_link_limit_counts_an_ipv6_64_as_one_source(db):
    payload = AccountLinkToken(token="kein-gueltiger-link")
    codes = [
        _status(lambda i=i: auth_routes.account_link_preview(payload, _request_from(f"2001:db8:7:8::{i:x}", "/api/auth/account-link/preview"), db))
        for i in range(1, 36)
    ]
    assert codes[:30] == [404] * 30
    assert 429 in codes[30:]


def test_ipv4_sources_are_still_counted_per_address(db):
    # Gegenprobe: verschiedene IPv4-Adressen (z. B. Mitglieder hinter verschiedenen Anschlüssen)
    # teilen sich keine Grenze.
    codes = [
        _status(lambda i=i: auth_routes.tenant_by_domain("unbekannt.example", _request_from(f"198.51.100.{i}", "/api/auth/tenant-by-domain"), db))
        for i in range(1, 26)
    ]
    assert codes == [404] * 25
