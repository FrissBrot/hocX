"""Vorgänge zweiter Faktor (Redis ``mfa:flow:*``, 10 min) nur begrenzt je Konto anlegen.

Redis läuft mit ``noeviction`` (docker-compose.release.yml): ist der Speicher voll, scheitern
Schreibbefehle und damit auch Anmeldeschutz und Ratelimits (fail-closed) - plattformweit. Bisher
konnte jedes angemeldete Konto über ``POST /api/auth/step-up/passkey/start`` (Konto mit Passkey)
bzw. nach einem Step-up über ``/api/users/me/mfa/{totp,passkeys}/start`` unbegrenzt viele
Vorgänge anlegen. Jetzt: 429 ab einer grosszügigen Grenze je Konto.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import rate_limit
from app.core.redis_client import get_redis_sync
from app.core.security import build_current_user
from app.models import UserMfaFactor
from app.services.mfa_service import MfaService
from app.services.step_up_service import StepUpService
from tests.factories import make_app_user, make_tenant

HOST = "localhost"
ORIGIN = "http://localhost"
ATTEMPTS = 200


def _flush() -> None:
    client = get_redis_sync()
    for pattern in ("ratelimit:*", "mfa:flow:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    rate_limit.local_window.clear()


@pytest.fixture(autouse=True)
def _clean():
    _flush()
    yield
    _flush()


def _hits_limit(start) -> bool:
    for _ in range(ATTEMPTS):
        try:
            start()
        except HTTPException as exc:
            if exc.status_code == 429:
                return True
            raise
    return False


def test_step_up_passkey_start_is_limited_per_account(db):
    user = make_app_user(db, email="flow-stepup@example.com", tenant_id=make_tenant(db).id, role_code="reader")
    rp_id = MfaService().rp_id_for_request_host(HOST)
    db.add(UserMfaFactor(user_id=user.id, factor_type="webauthn", label="Schlüssel", webauthn_credential_id="Y3JlZA",
                         webauthn_public_key_pem="-", webauthn_rp_id=rp_id))
    db.flush()
    current = build_current_user(db, user)
    assert _hits_limit(lambda: StepUpService().start_passkey(db, current, request_host=HOST, request_origin=ORIGIN))


def test_self_totp_enrollment_start_is_limited_per_account(db):
    user = make_app_user(db, email="flow-totp@example.com", tenant_id=make_tenant(db).id, role_code="reader")
    current = build_current_user(db, user)
    assert _hits_limit(lambda: MfaService().start_self_totp_enrollment(db, current))


def test_self_passkey_registration_start_is_limited_per_account(db, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "traefik_domain", "")
    user = make_app_user(db, email="flow-passkey@example.com", tenant_id=make_tenant(db).id, role_code="reader")
    current = build_current_user(db, user)
    assert _hits_limit(lambda: MfaService().start_self_passkey_registration(db, current, request_host=HOST, request_origin=ORIGIN))
