from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import urllib.parse
import urllib.request

import jwt
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.models import PlatformAdmin, PlatformOidcConfig
from app.schemas.oidc import PlatformOidcConfigPublic, PlatformOidcConfigRead, PlatformOidcConfigWrite


# ── Redirect target validation (open-redirect hardening) ────────────────────────────────────

def sanitize_redirect_to(redirect_to: str | None) -> str:
    """Only ever allow a same-origin relative path as an SSO redirect target - never a
    client-supplied absolute URL. Without this, `redirect_to` (attacker-controlled query param)
    would let `?redirect_to=https://evil.example` phish an admin straight off the platform right
    after a legitimate login. Applied both where redirect_to first enters the flow and again at
    the final redirect (defense in depth), matching how auth.py's /bridge endpoint deliberately
    never accepts a client-controlled redirect target at all."""
    if not redirect_to:
        return "/"
    # Browsers strip embedded tab/newline/CR before navigating, so strip them first too -
    # otherwise "/\t/evil.example" would pass a naive leading-slash check.
    candidate = redirect_to.strip().replace("\t", "").replace("\n", "").replace("\r", "")
    # Reject "//host/..." and "/\host" (backslash is treated like a forward slash by browsers) -
    # both are protocol-relative URLs that redirect off-site despite starting with "/".
    if not candidate.startswith("/") or candidate.startswith("//") or candidate.startswith("/\\"):
        return "/"
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return "/"
    return candidate


# ── State token (CSRF protection + carries PKCE verifier/nonce across the redirect) ─────────

def _make_state(redirect_to: str, code_verifier: str, nonce: str) -> str:
    # code_verifier and nonce are themselves cryptographically random per request, so the state
    # token is already unguessable without a separate salt field.
    payload = json.dumps({"r": redirect_to, "v": code_verifier, "n": nonce}, separators=(",", ":")).encode()
    sig = hmac.new(settings.admin_auth_secret.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def _verify_state(state: str) -> dict:
    try:
        payload_b64, sig_b64 = state.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64)
        expected = hmac.new(settings.admin_auth_secret.encode(), payload, hashlib.sha256).digest()
        provided = base64.urlsafe_b64decode(sig_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OIDC state")
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=400, detail="OIDC state signature invalid")
    return json.loads(payload)


# ── Discovery / JWKS ──────────────────────────────────────────────────────────────────────

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


class PlatformOidcService:
    """Single, globally configured SSO provider used exclusively to log into the
    platform-admin panel (see security audit 2026-07-26: the previous per-tenant OIDC design
    was removed - tenants/customers have no OIDC option at all anymore). At most one config
    row is ever meaningful; this service always operates on the first/only row."""

    def _get_row(self, db: Session) -> PlatformOidcConfig | None:
        return db.query(PlatformOidcConfig).order_by(PlatformOidcConfig.id.asc()).first()

    # ── Config CRUD (platform-admin only, see admin.py) ──────────────────────────────────

    def get_public_config(self, db: Session) -> PlatformOidcConfigPublic:
        cfg = self._get_row(db)
        if cfg is None or not cfg.enabled:
            return PlatformOidcConfigPublic(enabled=False, issuer_url="")
        return PlatformOidcConfigPublic(enabled=True, issuer_url=cfg.issuer_url)

    def get_config(self, db: Session) -> PlatformOidcConfigRead:
        cfg = self._get_row(db)
        if cfg is None:
            return PlatformOidcConfigRead(enabled=False, issuer_url="", client_id="", scopes="openid email profile")
        return PlatformOidcConfigRead(enabled=cfg.enabled, issuer_url=cfg.issuer_url, client_id=cfg.client_id, scopes=cfg.scopes)

    def upsert_config(self, db: Session, payload: PlatformOidcConfigWrite) -> PlatformOidcConfigRead:
        cfg = self._get_row(db)
        if cfg is None:
            cfg = PlatformOidcConfig()
            db.add(cfg)
        cfg.enabled = payload.enabled
        cfg.issuer_url = payload.issuer_url
        cfg.client_id = payload.client_id
        cfg.scopes = payload.scopes
        if payload.client_secret:
            # Encrypted at rest (audit finding M3) - decrypted again only where it's actually
            # used, in the token-exchange request below.
            cfg.client_secret = encrypt_secret(payload.client_secret)
        db.commit()
        db.refresh(cfg)
        return self.get_config(db)

    # ── Authorization flow ────────────────────────────────────────────────────────────────

    def build_authorize_url(self, db: Session, redirect_base: str, redirect_to: str = "/") -> str:
        cfg = self._get_row(db)
        if cfg is None or not cfg.enabled:
            raise HTTPException(status_code=404, detail="SSO is not configured")

        discovery = _fetch_discovery(cfg.issuer_url)
        auth_endpoint = discovery["authorization_endpoint"]
        callback_uri = redirect_base.rstrip("/") + "/api/admin/auth/oidc/callback"

        # PKCE (S256) + nonce - the previous per-tenant implementation had neither, see audit
        # finding M2. code_verifier and nonce travel inside the HMAC-signed state token rather
        # than server-side session storage, since there's no session yet at this point.
        code_verifier = secrets.token_urlsafe(64)[:128]
        code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
        nonce = secrets.token_urlsafe(16)
        state = _make_state(sanitize_redirect_to(redirect_to), code_verifier, nonce)

        params = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": cfg.client_id,
            "redirect_uri": callback_uri,
            "scope": cfg.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })
        return f"{auth_endpoint}?{params}"

    def handle_callback(self, db: Session, code: str, state: str, redirect_base: str) -> tuple[str, int]:
        """Returns (redirect_target, admin_id). Deliberately does not set the session cookie
        itself - the caller must do that on the actual Response object it returns (see
        issue_admin_session_cookie), matching the existing pattern used by the customer-facing
        auth flows for the same FastAPI Response-on-RedirectResponse reason."""
        state_data = _verify_state(state)
        # Defense in depth: the state token is HMAC-signed so this value can't be tampered with
        # in transit, but re-validating here guards against a future bug upstream (e.g. a new
        # caller of _make_state that forgets to sanitize) still producing an open redirect.
        redirect_to: str = sanitize_redirect_to(state_data.get("r", "/"))
        code_verifier: str = state_data["v"]
        expected_nonce: str = state_data["n"]

        cfg = self._get_row(db)
        if cfg is None or not cfg.enabled:
            raise HTTPException(status_code=400, detail="SSO is not configured")

        discovery = _fetch_discovery(cfg.issuer_url)
        token_endpoint = discovery["token_endpoint"]
        callback_uri = redirect_base.rstrip("/") + "/api/admin/auth/oidc/callback"

        credentials = base64.b64encode(f"{cfg.client_id}:{decrypt_secret(cfg.client_secret)}".encode()).decode()
        token_data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_uri,
            "code_verifier": code_verifier,
        }).encode()
        tokens = _fetch_json(token_endpoint, data=token_data, headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        })

        id_token = tokens.get("id_token")
        if not id_token:
            raise HTTPException(status_code=502, detail="No id_token in OIDC response")

        claims = self._verify_id_token(id_token, discovery, cfg)
        if not hmac.compare_digest(str(claims.get("nonce") or ""), expected_nonce):
            raise HTTPException(status_code=400, detail="OIDC nonce mismatch")

        subject = claims.get("sub")
        email = claims.get("email")
        if not subject:
            raise HTTPException(status_code=502, detail="OIDC id_token missing sub claim")

        admin = db.query(PlatformAdmin).filter(
            PlatformAdmin.oidc_issuer == cfg.issuer_url,
            PlatformAdmin.oidc_subject == subject,
        ).one_or_none()

        if admin is None and email:
            # Link by email to an EXISTING admin account that has no OIDC identity yet - never
            # auto-provision a brand-new admin account via SSO. An admin account is the most
            # privileged principal in the whole system; it must always be created explicitly
            # (bootstrap env vars or an existing admin adding another one), SSO only ever links
            # an identity onto an account that was already deliberately granted admin access.
            candidate = db.query(PlatformAdmin).filter(PlatformAdmin.email == email).one_or_none()
            if candidate is not None and candidate.oidc_subject is None:
                candidate.oidc_subject = subject
                candidate.oidc_issuer = cfg.issuer_url
                db.commit()
                admin = candidate

        if admin is None:
            raise HTTPException(status_code=403, detail="No matching admin account for this SSO identity")
        if not admin.is_active:
            raise HTTPException(status_code=403, detail="Admin account deactivated")

        return redirect_to, admin.id

    def _verify_id_token(self, id_token: str, discovery: dict, cfg: PlatformOidcConfig) -> dict:
        jwks_uri = discovery.get("jwks_uri")
        if not jwks_uri:
            raise HTTPException(status_code=502, detail="OIDC discovery response is missing jwks_uri")
        jwks = _fetch_json(jwks_uri)

        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=502, detail=f"Could not read OIDC id_token header: {exc}") from exc

        signing_key = None
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == header.get("kid"):
                signing_key = jwt.PyJWK.from_dict(jwk).key
                break
        if signing_key is None:
            raise HTTPException(status_code=502, detail="No matching JWKS key for OIDC id_token")

        try:
            claims = jwt.decode(
                id_token,
                key=signing_key,
                # Never derive the accepted algorithm from the token's own (attacker-controlled)
                # header - that's the classic RS256->HS256 key-confusion attack: an attacker
                # forges a token with alg=HS256 and signs it with the RSA public key (known via
                # JWKS) treated as an HMAC secret, which jwt.decode would then happily "verify"
                # as if it were the real RSA signature. The JWKS keys fetched above are RSA
                # public keys (kty=RSA), so only RS256 is ever acceptable here, hard-coded
                # server-side regardless of what the token claims.
                algorithms=["RS256"],
                audience=cfg.client_id,
                issuer=discovery.get("issuer", cfg.issuer_url),
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=401, detail=f"Invalid OIDC id_token: {exc}") from exc
        return claims
