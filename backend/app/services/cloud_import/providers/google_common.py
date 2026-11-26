"""Gemeinsames der Google-Adapter (Google Drive, Google Fotos): OAuth, Konto, Widerruf.

Kein eigener Anbieter (steht nicht in ``providers._ADAPTER_MODULES``). Beide Adapter nutzen dasselbe
Google-Cloud-Projekt und denselben OAuth-Client (``CLOUD_IMPORT_GOOGLE_CLIENT_ID``/``_SECRET``), aber
je eine eigene Redirect-URI (``…/oauth/google_drive/callback`` bzw. ``…/google_photos/callback``)
und eigene Verbindungen mit je nur ihrem Scope (Plan §3.1, E-3 a).

- Google kann kein ``form_post``: der Code kommt als Query-Parameter (begründete Ausnahme, Plan
  §5.2: Einmal-Code, PKCE, sofort eingelöst). ``access_type=offline`` + ``prompt=consent`` liefern
  bei jeder Anmeldung ein Refresh-Token.
- Scopes werden als volle URLs angefragt, weil Google sie so in der Token-Antwort zurückgibt
  (``email`` käme als ``…/auth/userinfo.email`` zurück und gälte sonst als nicht erteilt).
  Bei der granularen Zustimmung kann die Person einzelne Scopes abwählen → ``tier_of`` ist dann
  ``None`` und der Wizard verlangt eine neue Anmeldung (``missing_scope``).
- Konto: aus dem ID-Token (kommt direkt vom Token-Endpunkt über TLS, OIDC Core 3.1.3.7) - ``sub``
  als stabile Kennung, ``email`` als Anzeige, ``hd`` (Workspace-Domain) → «work».
- Widerruf beim Anbieter (Plan §5.5): ``POST https://oauth2.googleapis.com/revoke`` mit dem
  Refresh-Token (widerruft auch die Access-Tokens).
"""

from __future__ import annotations

import base64
import json
import re

from app.core.config import settings
from app.services.cloud_import import oauth
from app.services.cloud_import.http import ProviderError, SafeHttpClient
from app.services.cloud_import.providers import fake_mode
from app.services.cloud_import.providers.base import AccountInfo, CloudProvider, OAuthConfig, ProviderContext, TokenSet

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
OAUTH_HOST = "oauth2.googleapis.com"

SCOPE_OPENID = "openid"
SCOPE_EMAIL = "https://www.googleapis.com/auth/userinfo.email"

# Seitengrössen/IDs von Google: Buchstaben, Ziffern, «-», «_» (Drive-IDs, Picker-Sitzungen, Medien)
GOOGLE_ID = re.compile(r"^[A-Za-z0-9_-]{1,300}\Z")  # \Z: kein angehängtes «\n» (re.match + $)
# Seiten-Cursor (pageToken) von Google: undurchsichtig, aber nur aus diesen Zeichen
PAGE_TOKEN = re.compile(r"^[A-Za-z0-9_.~=+/-]{1,2000}\Z")


def jwt_claims(token: str | None) -> dict:
    """Claims des ID-Tokens ohne Signaturprüfung: es kommt direkt vom Token-Endpunkt über TLS
    (OIDC Core 3.1.3.7) und dient nur der Anzeige bzw. der Kontokennung dieser Anmeldung."""
    if not token or token.count(".") != 2 or len(token) > 8000:
        return {}
    try:
        payload = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _short(value, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


class GoogleProvider(CloudProvider):
    """Basis beider Google-Adapter. Unterklassen setzen ``key``, ``host_policy``, ``scope``."""

    scope: str
    # Google drosselt je Projekt und Nutzer (Drive: «User rate limit», Plan §3.3 [G10])
    request_rate: tuple[float, int] | None = (8.0, 20)

    def _client_configured(self) -> bool:
        return bool(settings.cloud_import_google_client_id and settings.cloud_import_google_client_secret)

    def configured(self) -> bool:
        return self._client_configured()

    def fake_transport(self):
        from app.services.cloud_import.fake_google import shared_fake

        return shared_fake().transport

    def fake_scenarios(self):
        return [
            ("anna", "Google-Konto anna@verein.test", None),  # i18n-ok: Testseite nur im E2E-Stack
            ("work", "Google-Workspace-Konto", None),  # i18n-ok: Testseite nur im E2E-Stack
            ("noscope", "Ohne Zugriff auf die Dateien (Häkchen abgewählt)", None),  # i18n-ok: Testseite nur im E2E-Stack
            ("cancel", "Abbrechen", ("access_denied", "")),  # i18n-ok: Testseite nur im E2E-Stack
        ]

    def oauth_config(self) -> OAuthConfig:
        authorize = AUTHORIZE_URL
        client_id, secret = settings.cloud_import_google_client_id, settings.cloud_import_google_client_secret
        if fake_mode():
            authorize = f"{oauth.redirect_base() or ''}/api/cloud-import/fake-authorize/{self.key}"
            client_id, secret = client_id or "fake-google-client-id", secret or "fake-google-client-secret"
        return OAuthConfig(
            authorize_url=authorize,
            token_url=TOKEN_URL,
            client_id=client_id,
            client_secret=secret,
            scopes_by_tier={"basic": (SCOPE_OPENID, SCOPE_EMAIL, self.scope)},
            response_mode="query",
            # Refresh-Token bei jeder Anmeldung (sonst nur beim allerersten Consent)
            extra_authorize_params={"access_type": "offline", "prompt": "consent"},
            select_account_params={"prompt": "select_account consent"},
            send_scope_on_refresh=False,
        )

    def map_authorize_error(self, error: str, description: str) -> str:
        if error == "access_denied":
            return "cancelled"
        if error in ("admin_policy_enforced", "org_internal"):
            # Google Workspace der Organisation lässt die App nicht zu
            return "admin_consent_required"
        return "authorize_failed"

    def account_info(self, ctx: ProviderContext, tokens: TokenSet) -> AccountInfo:
        claims = jwt_claims(tokens.id_token)
        if not claims.get("sub"):
            claims = ctx.with_token(lambda token: ctx.client.get_json(USERINFO_URL, bearer=token))
        subject = _short(claims.get("sub"), 120)
        return AccountInfo(
            label=_short(claims.get("email"), 320),
            kind="work" if claims.get("hd") else "personal",
            subject=f"google:{subject}" if subject else None,
        )

    def has_scope(self, ctx: ProviderContext) -> bool:
        return self.tier_of(ctx.granted_scopes) is not None

    def revoke(self, client: SafeHttpClient, tokens: TokenSet | None) -> None:
        """Token bei Google widerrufen (Refresh-Token widerruft auch die Access-Tokens)."""
        if tokens is None:
            return
        token = tokens.refresh_token or tokens.access_token
        if not token:
            return
        response = client.post_form(REVOKE_URL, {"token": token})
        # 400 invalid_token: schon widerrufen/abgelaufen - Ziel erreicht
        if response.status >= 500:
            raise ProviderError("server_error", status=response.status)
