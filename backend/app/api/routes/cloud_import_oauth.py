"""Zentraler OAuth-Callback der Cloud-Quellen (Plan §5.2) - Route ohne Sitzung.

Die Redirect-URI ist beim Anbieter fest registriert (``…/api/cloud-import/oauth/<anbieter>/callback``
auf der zentralen Domain); Vereinsdomain-Cookies kommen dort nicht an. Sicherheitsmodell:

- ``state`` (Redis, 10 min, einmalig, an Person/Mandant/Auftrag/Anbieter gebunden) - unbekannt,
  abgelaufen oder schon benutzt → nichts passiert.
- PKCE (S256): der Code ist nur mit dem Verifier einlösbar, den nur der Server kennt.
- Die Tokens werden nicht hier einer Verbindung zugeordnet: erst ``/cloud-import/oauth/finish``
  mit der Sitzung derselben Person (Abschluss-Token im URL-Fragment) - Login-CSRF ausgeschlossen.
- Microsoft liefert den Code per ``form_post`` (POST-Body statt URL, SECURITY-RULES §3.2); der
  Origin-Guard lässt genau diesen Pfad zu (core/origin_guard.py), Schutz ist der ``state``.
  Anbieter, die nur ``query`` können (Google), nutzen GET - Einmal-Code, PKCE, sofort eingelöst.
- Rate-Limit je Quelladresse, Weiterleitung nur auf die zentrale bzw. eigene App-Domain des
  Mandanten (beim Start geprüft) oder relativ.

In ``public_links.EXEMPT_PUBLIC_ROUTES`` begründet ausgenommen (kein Zugang zu Vereinsdaten).
"""

from __future__ import annotations

import logging
from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.client_ip import rate_limit_source
from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.services.cloud_import import connections, oauth, providers
from app.services.cloud_import.http import ProviderError
from app.services.cloud_import.providers.base import ProviderContext, ReauthRequired

_logger = logging.getLogger(__name__)

router = APIRouter()

WIZARD_PATH = "/files/import"
_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _target(state: oauth.StateData | None, *, error: str | None = None, finish: str | None = None, notice: str | None = None) -> str:
    query: dict[str, str] = {}
    if state is not None and state.job_id:
        query["job"] = state.job_id
    if error:
        query["cloud_error"] = error
    if notice:
        query["cloud_notice"] = notice
    base = f"https://{state.return_host}" if state is not None and state.return_host else ""
    url = f"{base}{WIZARD_PATH}"
    if query:
        url += "?" + urlencode(query)
    if finish:
        # Fragment: der Browser schickt es an keinen Server (Logs, Referer), vgl. Domain-Bridge
        url += "#" + urlencode({"cloud_finish": finish})
    return url


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303, headers=_NO_STORE)


def _no_refresh() -> str:
    raise ReauthRequired()


def _complete(db: Session, request: Request, provider_key: str, params: dict[str, str | None]) -> RedirectResponse:
    enforce_rate_limit(f"cloud-import-callback:{rate_limit_source(request)}", limit=60, period_seconds=600)
    provider = providers.get(provider_key)
    state = oauth.consume_state(params.get("state"))
    if provider is None or state is None or state.provider != provider_key or not providers.is_available(provider_key):
        return _redirect(_target(None, error="state_invalid"))
    error = params.get("error")
    if error:
        code = provider.map_authorize_error(error[:100], (params.get("error_description") or "")[:2000])
        return _redirect(_target(state, error=code))
    code = params.get("code")
    if not code or len(code) > 4000:
        return _redirect(_target(state, error="authorize_failed"))
    client = providers.client_for(provider)
    try:
        tokens = oauth.exchange_code(provider, client, code=code, verifier=state.verifier, scopes=state.scopes)
        ctx = ProviderContext(client, token=lambda: tokens.access_token, refresh=_no_refresh)
        account = provider.account_info(ctx, tokens)
    except (ProviderError, ReauthRequired) as exc:
        # Erwartbar (Code schon benutzt, PKCE falsch, Anbieter nicht erreichbar): nur der Code ins Log
        _logger.warning("Cloud-Import: Code-Einlösung gescheitert (%s, %s)", provider_key, getattr(exc, "code", type(exc).__name__))
        return _redirect(_target(state, error="token_exchange_failed"))
    except Exception as exc:  # noqa: BLE001 - unerwartet: Fehlerprotokoll, Person bekommt nur den Code
        from app.core.error_log import record_system_error

        record_system_error(db, exc=exc, tenant_id=state.tenant_id)
        return _redirect(_target(state, error="internal"))
    finish = oauth.store_pending({
        "user_id": state.user_id, "tenant_id": state.tenant_id, "job_id": state.job_id, "provider": provider.key,
        "tokens": {
            "access_token": tokens.access_token, "refresh_token": tokens.refresh_token,
            "expires_in": tokens.expires_in, "scope": tokens.scope,
        },
        "account": {"label": account.label, "kind": account.kind, "tenant_id": account.tenant_id},
        "granted": sorted(connections.granted_from(tokens, state.scopes)),
    })
    return _redirect(_target(state, finish=finish))


@router.post("/cloud-import/oauth/{provider_key}/callback")
def oauth_callback_form(
    provider_key: str,
    request: Request,
    state: str | None = Form(default=None, max_length=200),
    code: str | None = Form(default=None, max_length=4000),
    error: str | None = Form(default=None, max_length=200),
    error_description: str | None = Form(default=None, max_length=4000),
    db: Session = Depends(get_db),
):
    """response_mode=form_post (Microsoft): Code im Body, nie in der URL."""
    provider = providers.get(provider_key)
    config = provider.oauth_config() if provider is not None else None
    if config is None or config.response_mode != "form_post":
        oauth.consume_state(state)
        return _redirect(_target(None, error="state_invalid"))
    return _complete(db, request, provider_key, {"state": state, "code": code, "error": error, "error_description": error_description})


@router.get("/cloud-import/oauth/{provider_key}/callback")
def oauth_callback_query(
    provider_key: str,
    request: Request,
    state: str | None = Query(default=None, max_length=200),
    code: str | None = Query(default=None, max_length=4000),
    error: str | None = Query(default=None, max_length=200),
    error_description: str | None = Query(default=None, max_length=4000),
    admin_consent: str | None = Query(default=None, max_length=10),
    db: Session = Depends(get_db),
):
    """Anbieter mit Code in der Query (Google) bzw. Rückkehr nach einem Admin-Consent (Microsoft)."""
    provider = providers.get(provider_key)
    config = provider.oauth_config() if provider is not None else None
    if admin_consent is not None and code is None:
        # Admin hat die App im Vereins-Tenant freigegeben: nur ein Hinweis, nichts wird gespeichert
        enforce_rate_limit(f"cloud-import-callback:{rate_limit_source(request)}", limit=60, period_seconds=600)
        ok = admin_consent.lower() == "true" and not error
        return _redirect(_target(None, notice="admin_consent_done" if ok else None, error=None if ok else "admin_consent_failed"))
    if config is None or config.response_mode != "query":
        # Code in der URL, obwohl der Anbieter form_post nutzt: verwerfen (und state entwerten)
        oauth.consume_state(state)
        return _redirect(_target(None, error="state_invalid"))
    return _complete(db, request, provider_key, {"state": state, "code": code, "error": error, "error_description": error_description})


# --- Nachgebaute Anmeldeseite (nur Test-Stacks, CLOUD_IMPORT_FAKE_PROVIDERS) ------------------

fake_router = APIRouter()


@fake_router.get("/cloud-import/fake-authorize/{provider_key}", response_class=HTMLResponse)
def fake_authorize(provider_key: str, request: Request):
    """Ersetzt die Anmeldeseite des Anbieters im E2E-Stack. Wird nur eingebunden, wenn
    providers.fake_mode() gilt (main.py); in jeder anderen Umgebung existiert die Route nicht."""
    provider = providers.get(provider_key)
    if not providers.fake_mode() or provider is None:
        raise HTTPException(status_code=404)
    params = dict(request.query_params)
    if params.get("redirect_uri") != oauth.redirect_uri(provider_key):
        raise HTTPException(status_code=400, detail="redirect_uri")
    method = "post" if params.get("response_mode") == "form_post" else "get"
    forms = []
    for scenario, label, error in getattr(provider, "fake_scenarios", lambda: [])():
        fields = {"state": params.get("state") or ""}
        if error:
            fields["error"] = error[0]
            fields["error_description"] = error[1]
        else:
            # Der Nachbau prüft PKCE wie der echte Anbieter: die Challenge reist im Code mit
            fields["code"] = f"fake-{scenario}.{params.get('code_challenge') or ''}"
        hidden = "".join(f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">' for k, v in fields.items())
        forms.append(
            f'<form method="{method}" action="{escape(oauth.redirect_uri(provider_key))}">{hidden}'
            f'<button type="submit" data-scenario="{escape(scenario)}">{escape(label)}</button></form>'
        )
    body = (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\"><title>Test-Anmeldung</title></head>"  # i18n-ok: Testseite nur im E2E-Stack
        f"<body><h1>Test-Anmeldung {escape(provider_key)}</h1>{''.join(forms)}</body></html>"  # i18n-ok: Testseite nur im E2E-Stack
    )
    return HTMLResponse(body, headers={**_NO_STORE, "Content-Security-Policy": "default-src 'none'; form-action 'self'"})
