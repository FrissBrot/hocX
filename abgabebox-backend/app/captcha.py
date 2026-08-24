import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx

from app.config import settings


def _session_scope(tenant_slug: str, assignment_slug: str, element_ref: str) -> str:
    return f"{tenant_slug}:{assignment_slug}:{element_ref}"


def captcha_enabled() -> bool:
    """FriendlyCaptcha ist nur aktiv, wenn Sitekey UND API-Key konfiguriert sind. Ohne beide gilt
    kein Captcha als noetig (typischerweise lokale Entwicklung oder Test-Stacks ohne eigene
    FriendlyCaptcha-Keys) - Frontend zeigt dann einen Platzhalter statt des echten Widgets, und
    verify_captcha/verify_captcha_session_token unten lassen entsprechend alles durch."""
    return bool(settings.friendly_captcha_api_key and settings.friendly_captcha_sitekey)


def mint_captcha_session_token(tenant_slug: str, assignment_slug: str, element_ref: str) -> str:
    """Issued once after a real FriendlyCaptcha solve passes verify_captcha() below - lets the
    frontend prove "a human already passed the bot-check on this page" for subsequent uploads
    without re-running the widget each time. Scoped to the exact tenant/assignment/element so a
    token minted for one upload page can't be replayed against another. Same
    base64url(payload).base64url(hmac) shape as backend/app/core/security.py's
    _sign_payload/create_session_token - deliberately reimplemented rather than imported, this
    service intentionally keeps its own dependency/secret surface (see config.py docstring)."""
    now = datetime.now(UTC)
    payload = json.dumps(
        {
            "scope": _session_scope(tenant_slug, assignment_slug, element_ref),
            "exp": int((now + timedelta(minutes=settings.captcha_session_ttl_minutes)).timestamp()),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(settings.captcha_session_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode("utf-8") + "." + base64.urlsafe_b64encode(signature).decode("utf-8")


def verify_captcha_session_token(token: str, tenant_slug: str, assignment_slug: str, element_ref: str) -> bool:
    if not captcha_enabled():
        # Kein FriendlyCaptcha konfiguriert -> Sitzungs-Check entfaellt komplett, siehe
        # captcha_enabled() oben.
        return True
    if not settings.captcha_session_secret:
        # Captcha-Keys gesetzt, Sitzungs-Secret aber nicht - fail closed, das ist ein echter
        # Konfigurationsfehler und keine bewusste "kein Captcha noetig"-Situation.
        return False
    if not token or "." not in token:
        return False
    payload_b64, signature_b64 = token.split(".", 1)
    try:
        payload = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        expected = hmac.new(settings.captcha_session_secret.encode("utf-8"), payload, hashlib.sha256).digest()
        provided = base64.urlsafe_b64decode(signature_b64.encode("utf-8"))
    except (ValueError, TypeError):
        return False
    if not hmac.compare_digest(expected, provided):
        return False
    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return False
    if data.get("scope") != _session_scope(tenant_slug, assignment_slug, element_ref):
        return False
    return int(data.get("exp", 0)) >= int(datetime.now(UTC).timestamp())


async def verify_captcha(solution: str) -> bool:
    if not captcha_enabled():
        # Nicht konfiguriert (z.B. lokale Entwicklung/Test-Stack) - kein Captcha noetig, siehe
        # captcha_enabled() oben.
        return True
    if not solution:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.friendly_captcha_verify_url,
                json={
                    "solution": solution,
                    "secret": settings.friendly_captcha_api_key,
                    "sitekey": settings.friendly_captcha_sitekey,
                },
            )
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    data = response.json()
    return bool(data.get("success"))
