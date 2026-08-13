"""Regression tests for platform_oidc_service - the single global SSO login path for the
platform-admin panel (see security audit 2026-07-26). Covers what the critical-severity
sanitize_redirect_to fixes actually pin (open-redirect hardening, since redirect_to is an
attacker-controlled query param), plus the state token signing (CSRF/PKCE-carrier) and the
config CRUD, none of which had any coverage before. Network calls (OIDC discovery/token/JWKS
endpoints) are monkeypatched out - this is a unit-level test of the service's own logic, not
an integration test against a real IdP."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.secret_crypto import decrypt_secret
from app.schemas.oidc import PlatformOidcConfigWrite
from app.services.platform_oidc_service import (
    PlatformOidcService,
    _make_state,
    _verify_state,
    sanitize_redirect_to,
)


# --- sanitize_redirect_to (open-redirect hardening) --------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "/"),
        ("", "/"),
        ("/admin/tenants", "/admin/tenants"),
        ("/admin/tenants?x=1", "/admin/tenants?x=1"),
        # protocol-relative URL - starts with "/" but is actually off-site
        ("//evil.example.com", "/"),
        ("//evil.example.com/path", "/"),
        # backslash is treated like a forward slash by browsers
        ("/\\evil.example.com", "/"),
        # absolute URL with scheme
        ("https://evil.example.com", "/"),
        ("http://evil.example.com/admin", "/"),
        # embedded tab/newline/CR stripped by browsers before navigating, then re-checked
        ("/\t/evil.example.com", "/"),
        ("/\n/evil.example.com", "/"),
        # no leading slash at all
        ("evil.example.com", "/"),
        ("javascript:alert(1)", "/"),
    ],
)
def test_sanitize_redirect_to(raw, expected):
    assert sanitize_redirect_to(raw) == expected


def test_sanitize_redirect_to_strips_embedded_whitespace_but_keeps_valid_relative_path():
    assert sanitize_redirect_to("  /admin/tenants  ") == "/admin/tenants"


# --- state token (CSRF protection + PKCE verifier/nonce carrier) -------------------------


def test_make_state_and_verify_state_round_trip():
    state = _make_state("/admin/tenants", "verifier-abc", "nonce-xyz")
    data = _verify_state(state)
    assert data == {"r": "/admin/tenants", "v": "verifier-abc", "n": "nonce-xyz"}


def test_verify_state_rejects_tampered_payload():
    state = _make_state("/admin/tenants", "verifier-abc", "nonce-xyz")
    payload_b64, sig_b64 = state.split(".", 1)
    # Flip the state to point somewhere else while keeping the original signature.
    tampered = _make_state("/evil", "verifier-abc", "nonce-xyz").split(".", 1)[0] + "." + sig_b64
    with pytest.raises(HTTPException) as exc_info:
        _verify_state(tampered)
    assert exc_info.value.status_code == 400


def test_verify_state_rejects_malformed_state():
    with pytest.raises(HTTPException) as exc_info:
        _verify_state("not-a-valid-state-token")
    assert exc_info.value.status_code == 400


# --- config CRUD ---------------------------------------------------------------------------


def test_get_public_config_when_no_row_exists(db):
    service = PlatformOidcService()
    public = service.get_public_config(db)
    assert public.enabled is False
    assert public.issuer_url == ""


def test_upsert_config_then_get_config_round_trip(db):
    service = PlatformOidcService()
    service.upsert_config(
        db,
        PlatformOidcConfigWrite(
            enabled=True,
            issuer_url="https://idp.example.com",
            client_id="hocx-admin",
            client_secret="s3cret",
            scopes="openid email",
        ),
    )
    cfg = service.get_config(db)
    assert cfg.enabled is True
    assert cfg.issuer_url == "https://idp.example.com"
    assert cfg.client_id == "hocx-admin"
    assert cfg.scopes == "openid email"
    assert not hasattr(cfg, "client_secret")

    public = service.get_public_config(db)
    assert public.enabled is True
    assert public.issuer_url == "https://idp.example.com"


def test_upsert_config_keeps_existing_secret_when_not_provided(db):
    service = PlatformOidcService()
    service.upsert_config(
        db,
        PlatformOidcConfigWrite(enabled=True, issuer_url="https://idp.example.com", client_id="a", client_secret="orig-secret"),
    )
    service.upsert_config(
        db,
        PlatformOidcConfigWrite(enabled=True, issuer_url="https://idp.example.com", client_id="a", client_secret=""),
    )
    row = service._get_row(db)
    # client_secret is encrypted at rest (audit finding M3) - the stored column is ciphertext,
    # so compare the decrypted value rather than the raw row field.
    assert decrypt_secret(row.client_secret) == "orig-secret"


# --- build_authorize_url --------------------------------------------------------------------


def test_build_authorize_url_raises_404_when_sso_not_configured(db):
    service = PlatformOidcService()
    with pytest.raises(HTTPException) as exc_info:
        service.build_authorize_url(db, "https://admin.example.com")
    assert exc_info.value.status_code == 404


def test_build_authorize_url_includes_pkce_challenge_and_sanitized_state(db, monkeypatch):
    service = PlatformOidcService()
    service.upsert_config(
        db,
        PlatformOidcConfigWrite(enabled=True, issuer_url="https://idp.example.com", client_id="hocx-admin", client_secret="s3cret"),
    )
    monkeypatch.setattr(
        "app.services.platform_oidc_service._fetch_discovery",
        lambda issuer_url: {"authorization_endpoint": "https://idp.example.com/authorize"},
    )

    # A client-supplied absolute redirect target must be sanitized away before it ever
    # reaches the signed state token.
    url = service.build_authorize_url(db, "https://admin.example.com", redirect_to="https://evil.example.com")

    assert url.startswith("https://idp.example.com/authorize?")
    assert "client_id=hocx-admin" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "response_type=code" in url

    import urllib.parse

    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    state_data = _verify_state(query["state"][0])
    assert state_data["r"] == "/"  # sanitized from the malicious absolute URL


# --- handle_callback ------------------------------------------------------------------------


def test_handle_callback_rejects_tampered_state(db):
    service = PlatformOidcService()
    service.upsert_config(
        db,
        PlatformOidcConfigWrite(enabled=True, issuer_url="https://idp.example.com", client_id="a", client_secret="s"),
    )
    real_state = _make_state("/admin", "verifier", "nonce")
    tampered_state = real_state[:-1] + ("A" if real_state[-1] != "A" else "B")

    with pytest.raises(HTTPException) as exc_info:
        service.handle_callback(db, code="irrelevant", state=tampered_state, redirect_base="https://admin.example.com")
    assert exc_info.value.status_code == 400


def test_handle_callback_raises_when_sso_disabled(db):
    service = PlatformOidcService()
    # No config row at all -> disabled.
    state = _make_state("/admin", "verifier", "nonce")
    with pytest.raises(HTTPException) as exc_info:
        service.handle_callback(db, code="irrelevant", state=state, redirect_base="https://admin.example.com")
    assert exc_info.value.status_code == 400
    assert "not configured" in exc_info.value.detail
