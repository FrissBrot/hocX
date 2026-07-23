from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AppUser, TenantOidcConfig
from app.schemas.oidc import OidcConfigPublic, OidcConfigRead, OidcConfigWrite
from app.services import domain_bridge_service
from app.services.auth_service import AuthService


_auth_service = AuthService()


# ── State token (CSRF protection) ────────────────────────────────────────────

def _make_state(tenant_id: int, redirect_to: str) -> str:
    payload = json.dumps({"t": tenant_id, "r": redirect_to, "n": base64.urlsafe_b64encode(os.urandom(16)).decode()}, separators=(",", ":")).encode()
    sig = hmac.new(settings.auth_secret.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def _verify_state(state: str) -> dict:
    try:
        payload_b64, sig_b64 = state.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64)
        expected = hmac.new(settings.auth_secret.encode(), payload, hashlib.sha256).digest()
        provided = base64.urlsafe_b64decode(sig_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OIDC state")
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=400, detail="OIDC state signature invalid")
    return json.loads(payload)


# ── Discovery ─────────────────────────────────────────────────────────────────

def _fetch_discovery(issuer_url: str) -> dict:
    url = issuer_url.rstrip("/") + "/.well-known/openid-configuration"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OIDC discovery failed: {exc}")


def _fetch_json(url: str, data: bytes | None = None, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OIDC request failed: {exc}")


def _decode_id_token_claims(id_token: str) -> dict:
    """Decode claims from JWT without signature verification (discovery endpoint already verified via TLS)."""
    try:
        parts = id_token.split(".")
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        raise HTTPException(status_code=502, detail="Could not decode OIDC id_token")


# ── Config CRUD ──────────────────────────────────────────────────────────────

class OidcService:
    def get_public_config(self, db: Session, tenant_id: int) -> OidcConfigPublic:
        cfg = db.query(TenantOidcConfig).filter(TenantOidcConfig.tenant_id == tenant_id).one_or_none()
        if cfg is None or not cfg.enabled:
            return OidcConfigPublic(tenant_id=tenant_id, enabled=False, auto_redirect=False, issuer_url="")
        return OidcConfigPublic(tenant_id=tenant_id, enabled=True, auto_redirect=cfg.auto_redirect, issuer_url=cfg.issuer_url)

    def get_config(self, db: Session, tenant_id: int) -> OidcConfigRead | None:
        cfg = db.query(TenantOidcConfig).filter(TenantOidcConfig.tenant_id == tenant_id).one_or_none()
        if cfg is None:
            return None
        return OidcConfigRead(
            tenant_id=cfg.tenant_id,
            enabled=cfg.enabled,
            auto_redirect=cfg.auto_redirect,
            issuer_url=cfg.issuer_url,
            client_id=cfg.client_id,
            scopes=cfg.scopes,
        )

    def upsert_config(self, db: Session, tenant_id: int, payload: OidcConfigWrite) -> OidcConfigRead:
        cfg = db.query(TenantOidcConfig).filter(TenantOidcConfig.tenant_id == tenant_id).one_or_none()
        if cfg is None:
            cfg = TenantOidcConfig(tenant_id=tenant_id)
            db.add(cfg)
        cfg.enabled = payload.enabled
        cfg.auto_redirect = payload.auto_redirect
        cfg.issuer_url = payload.issuer_url
        cfg.client_id = payload.client_id
        cfg.scopes = payload.scopes
        if payload.client_secret:
            cfg.client_secret = payload.client_secret
        db.commit()
        db.refresh(cfg)
        return OidcConfigRead(
            tenant_id=cfg.tenant_id,
            enabled=cfg.enabled,
            auto_redirect=cfg.auto_redirect,
            issuer_url=cfg.issuer_url,
            client_id=cfg.client_id,
            scopes=cfg.scopes,
        )

    # ── Authorization flow ────────────────────────────────────────────────────

    def build_authorize_url(self, db: Session, tenant_id: int, redirect_base: str, redirect_to: str = "/") -> str:
        cfg = db.query(TenantOidcConfig).filter(TenantOidcConfig.tenant_id == tenant_id, TenantOidcConfig.enabled.is_(True)).one_or_none()
        if cfg is None:
            raise HTTPException(status_code=404, detail="OIDC not configured for this tenant")

        discovery = _fetch_discovery(cfg.issuer_url)
        auth_endpoint = discovery["authorization_endpoint"]
        state = _make_state(tenant_id, redirect_to)
        callback_uri = redirect_base.rstrip("/") + "/api/auth/oidc/callback"

        params = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": cfg.client_id,
            "redirect_uri": callback_uri,
            "scope": cfg.scopes,
            "state": state,
        })
        return f"{auth_endpoint}?{params}"

    def handle_callback(
        self, db: Session, code: str, state: str, redirect_base: str, request_host: str | None = None
    ) -> tuple[str, int, int]:
        """Returns (redirect_target, user_id, tenant_id). Deliberately does not set the session
        cookie itself - the caller must do that on the actual Response object it returns, since
        FastAPI silently drops Set-Cookie headers set on an injected Response dependency the
        moment the route returns a *different* Response instance (like a RedirectResponse)."""
        state_data = _verify_state(state)
        tenant_id: int = int(state_data["t"])
        redirect_to: str = state_data.get("r", "/")

        cfg = db.query(TenantOidcConfig).filter(TenantOidcConfig.tenant_id == tenant_id, TenantOidcConfig.enabled.is_(True)).one_or_none()
        if cfg is None:
            raise HTTPException(status_code=400, detail="OIDC not configured")

        discovery = _fetch_discovery(cfg.issuer_url)
        token_endpoint = discovery["token_endpoint"]
        callback_uri = redirect_base.rstrip("/") + "/api/auth/oidc/callback"

        # Exchange code for tokens
        credentials = base64.b64encode(f"{cfg.client_id}:{cfg.client_secret}".encode()).decode()
        token_data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_uri,
        }).encode()
        tokens = _fetch_json(token_endpoint, data=token_data, headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        })

        id_token = tokens.get("id_token")
        if not id_token:
            raise HTTPException(status_code=502, detail="No id_token in OIDC response")

        claims = _decode_id_token_claims(id_token)
        subject = claims.get("sub")
        email = claims.get("email") or claims.get("preferred_username", "")
        name = claims.get("name", "")
        first_name = claims.get("given_name") or (name.split()[0] if name else email)
        last_name = claims.get("family_name") or (" ".join(name.split()[1:]) if name and " " in name else "")

        # Find or provision user — admins always use local login, never provisioned via OIDC
        user = db.query(AppUser).filter(
            AppUser.oidc_issuer == cfg.issuer_url,
            AppUser.oidc_subject == subject,
        ).one_or_none()

        if user is None and email:
            user = db.query(AppUser).filter(AppUser.email == email).one_or_none()

        if user is None:
            # Auto-provision
            from app.core.security import hash_password
            user = AppUser(
                first_name=first_name or email,
                last_name=last_name or "",
                display_name=name or email,
                email=email,
                password_hash=hash_password(os.urandom(32).hex()),
                oidc_subject=subject,
                oidc_issuer=cfg.issuer_url,
                oidc_email=email,
                is_active=True,
                login_enabled=True,
            )
            db.add(user)
            db.flush()
        else:
            # Update OIDC fields if not already set
            if not user.oidc_subject:
                user.oidc_subject = subject
                user.oidc_issuer = cfg.issuer_url
                user.oidc_email = email
        db.commit()
        db.refresh(user)

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account deaktiviert")

        bridge_redirect_url = domain_bridge_service.resolve_bridge_redirect(db, request_host, user.id, tenant_id)
        return bridge_redirect_url or redirect_to, user.id, tenant_id
