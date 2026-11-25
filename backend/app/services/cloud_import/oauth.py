"""OAuth 2.0 Authorization Code mit PKCE für alle API-Quellen (Plan §5.2).

Ablauf:
1. ``start`` (Wizard, mit Sitzung): ``state`` (zufällig, 10 min, einmalig) und PKCE-Verifier in
   Redis, gebunden an Person, Mandant, Auftrag, Anbieter, Stufe und Rücksprung-Host. Im Browser
   landet nur der Hash des Verifiers (``code_challenge``, S256).
2. Anbieter → zentraler Callback ``/api/cloud-import/oauth/<anbieter>/callback`` (fest registrierte
   Redirect-URI auf ``CLOUD_IMPORT_REDIRECT_BASE_URL`` bzw. ``https://TRAEFIK_DOMAIN``). Der
   Callback hat keine Sitzung (die Vereinsdomain-Cookies fehlen dort): ``consume_state`` löscht den
   ``state`` beim ersten Lesen, der Code wird sofort mit dem Verifier eingelöst.
3. Die Tokens werden **nicht** sofort einer Verbindung zugeordnet, sondern verschlüsselt als
   «ausstehend» abgelegt (10 min). Der Browser springt auf die Vereinsdomain zurück, mit einem
   Einmal-Abschluss-Token im URL-Fragment (nie an Server/Logs/Referer). Erst ``finish`` mit der
   Sitzung legt die Verbindung an - und nur, wenn die angemeldete Person diejenige aus dem ``state``
   ist. Damit kann ein fremder Autorisierungs-Link (Login-CSRF) nie ein Cloud-Konto mit dem
   hocX-Konto einer anderen Person verbinden.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

from app.core.config import settings
from app.core.redis_client import get_redis_sync
from app.services.cloud_import import token_crypto
from app.services.cloud_import.http import ProviderError, ProviderThrottled, SafeHttpClient, raise_for_status
from app.services.cloud_import.providers.base import CloudProvider, ReauthRequired, TokenSet

STATE_TTL_SECONDS = 600
PENDING_TTL_SECONDS = 600
_STATE_PREFIX = "cloud_import_oauth_state:"
_PENDING_PREFIX = "cloud_import_oauth_pending:"


def _key(prefix: str, value: str) -> str:
    # Nur der Hash als Schlüssel: ein Redis-Dump verrät keine gültigen state-/Abschluss-Werte.
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()


def redirect_base() -> str | None:
    base = settings.cloud_import_redirect_base_url.strip().rstrip("/")
    if base:
        return base
    return f"https://{settings.traefik_domain}" if settings.traefik_domain else None


def redirect_uri(provider_key: str) -> str:
    base = redirect_base()
    if base is None:
        raise ProviderError("not_configured")
    return f"{base}/api/cloud-import/oauth/{provider_key}/callback"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


@dataclass
class StateData:
    provider: str
    tier: str
    user_id: int
    tenant_id: int
    job_id: str | None
    return_host: str | None
    verifier: str
    scopes: list[str]


def start(
    provider: CloudProvider, *, tier: str, user_id: int, tenant_id: int, job_id: str | None, return_host: str | None,
    select_account: bool = False, login_hint: str | None = None,
) -> str:
    """Autorisierungs-URL (der Browser navigiert dorthin)."""
    config = provider.oauth_config()
    if config is None or tier not in config.scopes_by_tier:
        raise ProviderError("not_configured")
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    scopes = list(provider.scopes_for(tier))
    data = StateData(provider.key, tier, user_id, tenant_id, job_id, return_host, verifier, scopes)
    get_redis_sync().set(_key(_STATE_PREFIX, state), json.dumps(asdict(data)), ex=STATE_TTL_SECONDS, nx=True)
    params = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(provider.key),
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **config.extra_authorize_params,
    }
    if config.response_mode == "form_post":
        params["response_mode"] = "form_post"
    if select_account:
        params.update(config.select_account_params)
    if login_hint:
        params["login_hint"] = login_hint
    return f"{config.authorize_url}?{urlencode(params)}"


def consume_state(state: str | None) -> StateData | None:
    """Einmalig: der state wird beim Lesen gelöscht. Unbekannt/abgelaufen → None."""
    if not state or len(state) > 200:
        return None
    raw = get_redis_sync().getdel(_key(_STATE_PREFIX, state))
    if raw is None:
        return None
    try:
        return StateData(**json.loads(raw))
    except (TypeError, ValueError):
        return None


def _token_set(data: dict, *, previous_refresh: str | None = None) -> TokenSet:
    access = data.get("access_token")
    if not isinstance(access, str) or not access:
        raise ProviderError("bad_response", detail="token")
    try:
        expires_in = int(data.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    refresh = data.get("refresh_token") if isinstance(data.get("refresh_token"), str) else None
    return TokenSet(
        access_token=access, refresh_token=refresh or previous_refresh, expires_in=max(60, min(expires_in, 24 * 3600)),
        scope=str(data.get("scope") or ""), id_token=data.get("id_token") if isinstance(data.get("id_token"), str) else None,
    )


def exchange_code(provider: CloudProvider, client: SafeHttpClient, *, code: str, verifier: str, scopes: list[str]) -> TokenSet:
    config = provider.oauth_config()
    if config is None:
        raise ProviderError("not_configured")
    form = {
        "grant_type": "authorization_code",
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code": code,
        "redirect_uri": redirect_uri(provider.key),
        "code_verifier": verifier,
    }
    if scopes:
        form["scope"] = " ".join(scopes)
    response = client.post_form(config.token_url, form)
    raise_for_status(response)
    return _token_set(response.json())


def refresh(provider: CloudProvider, client: SafeHttpClient, *, refresh_token: str, scopes: list[str]) -> TokenSet:
    """Erneuert das Access-Token. invalid_grant (Widerruf, Passwortwechsel, abgelaufen) →
    ReauthRequired; Drosselung/Netz → ProviderError (später erneut versuchen)."""
    config = provider.oauth_config()
    if config is None:
        raise ProviderError("not_configured")
    form = {
        "grant_type": "refresh_token",
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "refresh_token": refresh_token,
    }
    if scopes and config.send_scope_on_refresh:
        form["scope"] = " ".join(scopes)
    response = client.post_form(config.token_url, form)
    try:
        raise_for_status(response)
    except ProviderThrottled:
        raise
    except ProviderError as exc:
        if exc.status in (400, 401) and exc.detail in ("invalid_grant", "interaction_required", "consent_required", "invalid_client", None):
            raise ReauthRequired() from exc
        raise
    return _token_set(response.json(), previous_refresh=refresh_token)


# --- Ausstehende Verbindung (Callback → finish mit Sitzung) ------------------------------------


def store_pending(data: dict) -> str:
    finish = secrets.token_urlsafe(32)
    encrypted = token_crypto.encrypt(json.dumps(data))
    get_redis_sync().set(_key(_PENDING_PREFIX, finish), encrypted, ex=PENDING_TTL_SECONDS, nx=True)
    return finish


def consume_pending(finish: str | None) -> dict | None:
    if not finish or len(finish) > 200:
        return None
    raw = get_redis_sync().getdel(_key(_PENDING_PREFIX, finish))
    if raw is None:
        return None
    try:
        return json.loads(token_crypto.decrypt(raw if isinstance(raw, str) else raw.decode("ascii")) or "{}")
    except (token_crypto.TokenDecryptError, ValueError):
        return None
