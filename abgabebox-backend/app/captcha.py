import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx

from app.config import is_dev_or_test_environment, settings

_logger = logging.getLogger(__name__)


def _session_scope(tenant_slug: str, assignment_slug: str, element_ref: str) -> str:
    return f"{tenant_slug}:{assignment_slug}:{element_ref}"


def captcha_configured() -> bool:
    """True the moment either FriendlyCaptcha key is set - see captcha_enabled()'s docstring
    for why this is a different question from "is captcha fully usable"."""
    return bool(settings.friendly_captcha_api_key or settings.friendly_captcha_sitekey)


def captcha_partially_configured() -> bool:
    """True only for the misconfigured "exactly one of the two keys is set" state - used by
    main.py's startup check. Deliberately independent of captcha_enabled()'s return value:
    that function now returns True for this same state (so verification actually runs and
    fails closed), which makes it useless as a signal for "is this the misconfigured case"."""
    return bool(settings.friendly_captcha_api_key) != bool(settings.friendly_captcha_sitekey)


def captcha_enabled() -> bool:
    """FriendlyCaptcha is only skippable when NEITHER key is set at all (genuine local-dev/
    test stacks with no FriendlyCaptcha account) - the frontend shows a placeholder instead
    of the real widget in that case, and verify_captcha/verify_captcha_session_token below
    used to let everything through unconditionally in that case.

    Exactly ONE key set (a typo, or an incomplete secret rotation touching only one of the
    two env vars) used to be treated identically to "neither set" - silently disabling every
    check with no warning at all, while the frontend widget kept rendering as if protection
    were active (audit finding, 2026-08-25). That's a real misconfiguration, not a deliberate
    "no captcha needed" choice, so it must not resolve to bypassing verification: this now
    counts as "enabled", which sends the partial config on to the real FriendlyCaptcha API
    call below and lets that fail (closed - uploads rejected) instead of skipping the check
    entirely. A clear warning is logged either way so this doesn't stay silent even while the
    uploads that would otherwise sail through here are legitimately being blocked.

    "Neither key set" itself is no longer an unconditional skip either (audit finding,
    2026-08-27): see _skip_captcha_when_unconfigured() below, which verify_captcha/
    verify_captcha_session_token now call instead of returning True outright whenever this
    function returns False - production must fail CLOSED (reject uploads) when captcha is
    entirely unconfigured, not just when it's half-configured."""
    if captcha_partially_configured():
        _logger.warning(
            "FriendlyCaptcha ist nur teilweise konfiguriert (Sitekey oder API-Key fehlt) - "
            "Verifikation wird durchgefuehrt und schlaegt fehl, bis beide Werte gesetzt sind."
        )
        return True
    return bool(settings.friendly_captcha_api_key and settings.friendly_captcha_sitekey)


def _skip_captcha_when_unconfigured() -> bool:
    """Called only when captcha_enabled() is False, i.e. NEITHER FriendlyCaptcha key is set at
    all (audit finding, 2026-08-27). That state is fine and intentional on a genuine local
    dev/test stack (no FriendlyCaptcha account needed there) - but the exact same state on a
    production deploy would previously mean uploads sail through with NO bot-check whatsoever,
    silently, for as long as the config stays missing. This is what tells the two situations
    apart, via ABGABEBOX_ENVIRONMENT (see config.py's is_dev_or_test_environment - unset
    defaults to production-like, i.e. fail closed, not fail open) - only a stack explicitly
    marked dev/test still gets the old skip-entirely behavior; everything else now rejects the
    upload instead of silently allowing it."""
    if is_dev_or_test_environment():
        return True
    _logger.warning(
        "FriendlyCaptcha ist nicht konfiguriert (FRIENDLY_CAPTCHA_SITEKEY und "
        "FRIENDLY_CAPTCHA_API_KEY fehlen beide) und ABGABEBOX_ENVIRONMENT ist nicht als "
        "dev/test markiert - Uploads werden abgelehnt (fail closed), statt die "
        "Bot-Verifikation stillschweigend zu ueberspringen."
    )
    return False


def _ip_fingerprint(client_ip: str | None) -> str | None:
    """A hash, not the raw IP, is embedded in the token below - the token round-trips
    through the client (it's sent back on every upload), so storing the address itself in
    it would needlessly expose it. None (IP unavailable) is a distinct value from any real
    hash, so a token minted without one can never accidentally match a later check that also
    has none."""
    if not client_ip:
        return None
    return hashlib.sha256(f"{client_ip}|{settings.captcha_session_secret}".encode("utf-8")).hexdigest()


def mint_captcha_session_token(tenant_slug: str, assignment_slug: str, element_ref: str, client_ip: str | None = None) -> str:
    """Issued once after a real FriendlyCaptcha solve passes verify_captcha() below - lets the
    frontend prove "a human already passed the bot-check on this page" for subsequent uploads
    without re-running the widget each time. Scoped to the exact tenant/assignment/element so a
    token minted for one upload page can't be replayed against another, and (client_ip) to the
    IP that solved the captcha - without that, this 120-minute-TTL bearer token was reusable
    from any number of different IPs, which quietly defeated the assumption that Traefik's
    per-IP rate limit on this endpoint (5/min) meaningfully bounds abuse per person: rotating
    IPs let one solved captcha be replayed indefinitely up to the tenant's storage quota with
    no further bot-check at all (audit finding, 2026-08-25). Same
    base64url(payload).base64url(hmac) shape as backend/app/core/security.py's
    _sign_payload/create_session_token - deliberately reimplemented rather than imported, this
    service intentionally keeps its own dependency/secret surface (see config.py docstring)."""
    now = datetime.now(UTC)
    payload = json.dumps(
        {
            "scope": _session_scope(tenant_slug, assignment_slug, element_ref),
            "exp": int((now + timedelta(minutes=settings.captcha_session_ttl_minutes)).timestamp()),
            "ip": _ip_fingerprint(client_ip),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(settings.captcha_session_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode("utf-8") + "." + base64.urlsafe_b64encode(signature).decode("utf-8")


def verify_captcha_session_token(
    token: str, tenant_slug: str, assignment_slug: str, element_ref: str, client_ip: str | None = None
) -> bool:
    if not captcha_enabled():
        # Kein FriendlyCaptcha konfiguriert -> nur in dev/test entfaellt der Sitzungs-Check
        # komplett; in Produktion fail closed (audit finding, 2026-08-27). Siehe
        # _skip_captcha_when_unconfigured() oben.
        return _skip_captcha_when_unconfigured()
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
    if data.get("ip") != _ip_fingerprint(client_ip):
        return False
    if data.get("scope") != _session_scope(tenant_slug, assignment_slug, element_ref):
        return False
    return int(data.get("exp", 0)) >= int(datetime.now(UTC).timestamp())


async def verify_captcha(solution: str) -> bool:
    if not captcha_enabled():
        # Nicht konfiguriert -> nur in dev/test kein Captcha noetig; in Produktion fail closed
        # (audit finding, 2026-08-27). Siehe _skip_captcha_when_unconfigured() oben.
        return _skip_captcha_when_unconfigured()
    if not solution:
        return False
    # Fail CLOSED on any failure to actually complete a verification against FriendlyCaptcha's
    # own API - a network error/timeout, a non-200 response, or a 200 with a body that isn't
    # the JSON shape expected (ValueError from response.json() on bad JSON) - not just the
    # already-handled httpx.HTTPError case (audit finding, 2026-08-27). This applies
    # unconditionally, in every environment including dev/test: captcha_enabled() being True
    # here means real keys ARE configured, so an API failure is never the deliberate "no
    # captcha needed" case _skip_captcha_when_unconfigured() covers above - it's FriendlyCaptcha
    # itself being unreachable/broken, and the safe assumption is that the solution was never
    # actually verified, not that it was valid.
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
        if response.status_code != 200:
            return False
        data = response.json()
        return bool(data.get("success"))
    except (httpx.HTTPError, ValueError) as exc:
        _logger.warning("FriendlyCaptcha-Verifikation fehlgeschlagen (%s) - Upload wird abgelehnt (fail closed).", exc)
        return False
