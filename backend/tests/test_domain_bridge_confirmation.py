"""MAIN-SEC-006: Ein Bridge-Link meldet nicht mehr direkt an. Das Token gilt nur auf der
Ziel-Domain und wird erst nach Bestätigung (POST) eingelöst - so kann niemand einem anderen
per Link die eigene Sitzung unterschieben, ohne dass Name und Mandant angezeigt werden."""
import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.api.routes import auth as auth_routes
from app.core.config import settings
from app.schemas.user import BridgeRedeemRequest
from app.services import domain_bridge_service
from tests.factories import make_app_user, make_tenant

TARGET = "kunde.example.org"


def _request(host: str, origin: str | None = None) -> Request:
    headers = [(b"host", host.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "headers": headers, "method": "POST", "path": "/api/auth/bridge", "scheme": "https", "server": (host, 443)})


def _token(db):
    tenant = make_tenant(db, "Kunde")
    user = make_app_user(db, email="bridge@example.com", tenant_id=tenant.id, role_code="writer")
    return domain_bridge_service.create_bridge_token(user.id, TARGET), user


def test_get_link_only_redirects_to_the_confirmation_page(db):
    token, _ = _token(db)

    response = auth_routes.bridge(token)

    assert response.status_code == 307
    assert response.headers["location"] == f"/auth/bridge?token={token}"
    assert "set-cookie" not in response.headers
    # Token ist noch gültig (nicht verbraucht).
    assert domain_bridge_service.peek_bridge_token(token, TARGET) is not None


def test_preview_shows_whose_session_it_would_be(db):
    token, user = _token(db)

    preview = auth_routes.bridge_preview(token, _request(TARGET), db=db)

    assert (preview.email, preview.tenant_name) == (user.email, "Kunde")


def test_confirmation_sets_the_session_cookie_once(db):
    token, _ = _token(db)
    response = Response()

    assert auth_routes.redeem_bridge(BridgeRedeemRequest(token=token), _request(TARGET, f"https://{TARGET}"), response, db=db) == {"status": "ok"}
    assert any(name == b"set-cookie" and settings.auth_session_cookie.encode() in value for name, value in response.raw_headers)

    with pytest.raises(HTTPException) as exc:
        auth_routes.redeem_bridge(BridgeRedeemRequest(token=token), _request(TARGET), Response(), db=db)
    assert exc.value.status_code == 404


def test_token_is_rejected_on_another_host(db):
    token, _ = _token(db)

    with pytest.raises(HTTPException) as exc:
        auth_routes.bridge_preview(token, _request("andere.example.org"), db=db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        auth_routes.redeem_bridge(BridgeRedeemRequest(token=token), _request("andere.example.org"), Response(), db=db)
    assert exc.value.status_code == 404


def test_cross_site_origin_is_rejected(db):
    token, _ = _token(db)

    with pytest.raises(HTTPException) as exc:
        auth_routes.redeem_bridge(BridgeRedeemRequest(token=token), _request(TARGET, "https://angreifer.example"), Response(), db=db)
    assert exc.value.status_code == 403
    assert domain_bridge_service.peek_bridge_token(token, TARGET) is not None
