"""Feste Texte im PDF (Leertexte, Spaltenköpfe, Status, «Seite X von Y» …).

Quelle: frontend/messages/<locale>/documentPdf.json, ins Backend kopiert von
scripts/sync-document-i18n.py nach app/documents/i18n/<locale>.json. Python und Typst enthalten
keine fest codierten Texte: der Hausstil schlägt jeden Text in ``Document.strings`` nach.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.locale_config_generated import DEFAULT_LOCALE, SUPPORTED_LOCALES

_I18N_DIR = Path(__file__).resolve().parent / "i18n"


def normalize_language(language: str | None) -> str:
    """Unbekannte oder leere Sprache fällt auf die Standardsprache zurück, nie ein Fehler."""
    value = str(language or "").strip().lower()
    return value if value in SUPPORTED_LOCALES else DEFAULT_LOCALE


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = str(value)
    return out


@lru_cache(maxsize=None)
def _load(language: str) -> dict[str, str]:
    path = _I18N_DIR / f"{language}.json"
    if not path.exists():
        return {}
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


def strings_for(language: str | None) -> dict[str, str]:
    """Alle Texte der Sprache; fehlende Schlüssel kommen aus der Standardsprache."""
    lang = normalize_language(language)
    merged = dict(_load(DEFAULT_LOCALE))
    merged.update(_load(lang))
    return merged


def text(language: str | None, key: str, **params: object) -> str:
    """Ein Text mit ``{param}``-Platzhaltern (für API-Meldungen und Dateinamen)."""
    value = strings_for(language).get(key, key)
    for name, param in params.items():
        value = value.replace("{" + name + "}", str(param))
    return value
