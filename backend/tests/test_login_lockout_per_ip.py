"""MAIN-SEC-007: Fehlversuche von einer IP sperren ein Konto nur für diese IP; eine deutlich
höhere Grenze pro Konto bremst verteiltes Raten. Die Client-IP wird nur hinter einem
vertrauenswürdigen Proxy aus X-Forwarded-For gelesen."""
import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.core import rate_limit
from app.core.client_ip import client_ip
from app.core.redis_client import get_redis_sync
from app.schemas.user import LoginRequest
from app.services.auth_service import AuthService
from tests.factories import make_app_user, make_tenant

EMAIL = "lockout@example.com"


@pytest.fixture(autouse=True)
def _clean_counters():
    redis = get_redis_sync()
    for key in redis.scan_iter(f"ratelimit:login-account:{EMAIL}*"):
        redis.delete(key)
    yield
    for key in redis.scan_iter(f"ratelimit:login-account:{EMAIL}*"):
        redis.delete(key)


def _login(db, password, ip):
    return AuthService().login(db, Response(), LoginRequest(email=EMAIL, password=password), request_host=None, client_address=ip)


def test_failures_from_one_ip_do_not_lock_out_the_owner_on_another_ip(db):
    tenant = make_tenant(db)
    make_app_user(db, email=EMAIL, password="correct-password", tenant_id=tenant.id, role_code="writer")

    for _ in range(rate_limit.LOGIN_LOCKOUT_PER_IP):
        with pytest.raises(HTTPException) as exc:
            _login(db, "falsch", "203.0.113.7")
        assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        _login(db, "correct-password", "203.0.113.7")
    assert exc.value.status_code == 429

    assert _login(db, "correct-password", "198.51.100.20").authenticated is True


def test_account_wide_limit_stops_distributed_guessing(db, monkeypatch):
    monkeypatch.setattr(rate_limit, "LOGIN_LOCKOUT_PER_ACCOUNT", 3)
    tenant = make_tenant(db)
    make_app_user(db, email=EMAIL, password="correct-password", tenant_id=tenant.id, role_code="writer")

    for index in range(3):
        with pytest.raises(HTTPException):
            _login(db, "falsch", f"203.0.113.{index}")

    with pytest.raises(HTTPException) as exc:
        _login(db, "correct-password", "198.51.100.20")
    assert exc.value.status_code == 429


def _request(peer: str, forwarded: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 12345), "method": "GET", "path": "/"})


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("172.20.0.5", "203.0.113.7", "203.0.113.7"),  # Traefik im Compose-Netz
        ("172.20.0.5", "1.1.1.1, 203.0.113.7", "203.0.113.7"),  # gefälschter linker Eintrag
        ("203.0.113.9", "1.1.1.1", "203.0.113.9"),  # direkter Zugriff: Header wird ignoriert
        ("172.20.0.5", None, "172.20.0.5"),
        ("172.20.0.5", "192.168.1.10", "192.168.1.10"),  # Zugriff aus dem LAN
    ],
)
def test_client_ip_trusts_forwarded_header_only_from_proxies(peer, forwarded, expected):
    assert client_ip(_request(peer, forwarded)) == expected
