"""Regression tests for die zentrale Locale-Konfiguration und ihre Verankerung im Backend
(Pydantic-Validierung von preferred_language, Locale-Cookie bei Login/Session/Self-Update).

Bewusst KEINE hart codierte Sprachliste hier: alle Tests iterieren ueber
app.core.locale_config_generated.SUPPORTED_LOCALES - das ist dieselbe generierte Datei, die
backend/app/core/security.py und backend/app/schemas/user.py tatsaechlich verwenden (Quelle:
i18n/locales.json, siehe scripts/sync-i18n-config.py). Eine neu registrierte Sprache wird von
diesen Tests automatisch mitgeprueft, ohne dass diese Datei angepasst werden muss."""
from __future__ import annotations

import pytest
from fastapi import Response
from pydantic import ValidationError

from app.core.locale_config_generated import DEFAULT_LOCALE, SUPPORTED_LOCALES, is_supported_locale, normalize_locale
from app.core.security import LOCALE_COOKIE_NAME, issue_locale_cookie
from app.schemas.user import UserCreate, UserSelfUpdate, UserUpdate
from app.services.auth_service import AuthService

from tests.factories import make_app_user, make_current_user, make_tenant


# --- locale_config_generated --------------------------------------------------------------


def test_default_locale_is_itself_supported():
    assert DEFAULT_LOCALE in SUPPORTED_LOCALES


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_is_supported_locale_true_for_every_registered_locale(locale):
    assert is_supported_locale(locale) is True


def test_is_supported_locale_false_for_unknown_value():
    assert is_supported_locale("xx") is False
    assert is_supported_locale(None) is False


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_normalize_locale_passes_through_every_registered_locale(locale):
    assert normalize_locale(locale) == locale


def test_normalize_locale_falls_back_to_default_for_unknown_value():
    # Eine unbekannte/nicht unterstuetzte Locale darf die Anwendung nie beschaedigen - sie faellt
    # auf die Default-Locale zurueck statt einen Fehler zu werfen.
    assert normalize_locale("xx") == DEFAULT_LOCALE
    assert normalize_locale(None) == DEFAULT_LOCALE
    assert normalize_locale("") == DEFAULT_LOCALE


# --- Pydantic-Validierung in schemas/user.py -----------------------------------------------


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_user_self_update_accepts_every_registered_locale(locale):
    UserSelfUpdate(preferred_language=locale)  # darf nicht raisen


def test_user_self_update_rejects_unknown_locale():
    with pytest.raises(ValidationError):
        UserSelfUpdate(preferred_language="xx")


def test_user_self_update_allows_omitted_locale():
    # preferred_language ist optional (nur Felder aendern, die mitgeschickt werden)
    UserSelfUpdate(preferred_language=None)


def test_user_update_rejects_unknown_locale():
    with pytest.raises(ValidationError):
        UserUpdate(preferred_language="xx")


def test_user_create_rejects_unknown_locale():
    with pytest.raises(ValidationError):
        UserCreate(
            first_name="New",
            last_name="Person",
            display_name="New Person",
            email="new@example.com",
            password="a-very-long-password-123",
            preferred_language="xx",
        )


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_user_create_accepts_every_registered_locale(locale):
    UserCreate(
        first_name="New",
        last_name="Person",
        display_name="New Person",
        email="new@example.com",
        password="a-very-long-password-123",
        preferred_language=locale,
    )


# --- issue_locale_cookie --------------------------------------------------------------------


def _cookie_value(response: Response, name: str) -> str | None:
    for raw_key, raw_value in response.raw_headers:
        if raw_key != b"set-cookie":
            continue
        decoded = raw_value.decode("latin-1")
        if decoded.startswith(f"{name}="):
            return decoded.split(";", 1)[0].split("=", 1)[1]
    return None


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_issue_locale_cookie_sets_registered_locale_verbatim(locale):
    response = Response()
    issue_locale_cookie(response, locale)
    assert _cookie_value(response, LOCALE_COOKIE_NAME) == locale


def test_issue_locale_cookie_falls_back_to_default_for_unknown_value():
    response = Response()
    issue_locale_cookie(response, "xx")
    assert _cookie_value(response, LOCALE_COOKIE_NAME) == DEFAULT_LOCALE


def test_issue_locale_cookie_falls_back_to_default_for_none():
    response = Response()
    issue_locale_cookie(response, None)
    assert _cookie_value(response, LOCALE_COOKIE_NAME) == DEFAULT_LOCALE


# --- Verankerung in AuthService.login/session -----------------------------------------------


def test_login_sets_locale_cookie_matching_user_preference(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="locale-login@example.com", password="correct-password", tenant_id=tenant.id, role_code="writer")
    user.preferred_language = "fr"
    db.flush()

    from app.schemas.user import LoginRequest

    service = AuthService()
    response = Response()
    service.login(db, response, LoginRequest(email="locale-login@example.com", password="correct-password"), request_host=None)

    assert _cookie_value(response, LOCALE_COOKIE_NAME) == "fr"


def test_session_refreshes_locale_cookie_from_current_preference(db):
    # Deckt Prioritaetsstufe 1 ab ("explizit gespeicherte Benutzerpraeferenz"): jeder
    # Session-Abruf haelt den Cookie frisch, auch wenn preferred_language sich zwischenzeitlich
    # geaendert hat (z.B. auf einem anderen Geraet) - siehe issue_locale_cookie-Docstring.
    tenant = make_tenant(db)
    current_user = make_current_user(tenant.id, role="writer")
    current_user.preferred_language = "it"

    service = AuthService()
    response = Response()
    service.session(current_user, response)

    assert _cookie_value(response, LOCALE_COOKIE_NAME) == "it"


def test_session_sets_no_cookie_for_anonymous_request(db):
    service = AuthService()
    response = Response()
    result = service.session(None, response)

    assert result.authenticated is False
    assert _cookie_value(response, LOCALE_COOKIE_NAME) is None
