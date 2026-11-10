"""GENERATED FILE - do not edit by hand. Source of truth: i18n/locales.json (repo root).
Regenerate with: python3 scripts/sync-i18n-config.py
"""
from __future__ import annotations

DEFAULT_LOCALE = "de"

LOCALE_COOKIE_NAME = "hocx_locale"

LOCALES: dict[str, dict[str, str]] = {
    "de": {"label": "Deutsch", "native_label": "Deutsch"},
    "en": {"label": "Englisch", "native_label": "English"},
    "fr": {"label": "Franz\u00f6sisch", "native_label": "Fran\u00e7ais"},
    "it": {"label": "Italienisch", "native_label": "Italiano"},
}

SUPPORTED_LOCALES: frozenset[str] = frozenset(LOCALES)


def is_supported_locale(value: str | None) -> bool:
    return value in SUPPORTED_LOCALES


def normalize_locale(value: str | None) -> str:
    """Gibt value zurueck, falls unterstuetzt, sonst DEFAULT_LOCALE - eine unbekannte/leere
    Locale darf nie zu einem Fehler fuehren, nur zum Fallback."""
    return value if is_supported_locale(value) else DEFAULT_LOCALE
