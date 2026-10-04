#!/usr/bin/env python3
"""Prueft die Translation Catalogs beider Frontends gegen die zentrale Locale-Konfiguration.

    python3 scripts/check-i18n-completeness.py

Bezieht die unterstuetzten Sprachen AUSSCHLIESSLICH aus i18n/locales.json (Source of Truth,
siehe scripts/sync-i18n-config.py) - keine Sprachliste hier im Skript. Eine neu in
i18n/locales.json registrierte Sprache wird beim naechsten Lauf automatisch geprueft, ohne
dass dieses Skript angepasst werden muss.

Geprueft wird pro App (APP_ROOTS - das sind Verzeichnisse, keine Sprachen, daher bewusst fest):
  1. Jede registrierte Locale hat ein messages/<locale>/-Verzeichnis.
  2. Kein messages/<locale>/-Verzeichnis existiert fuer eine nicht (mehr) registrierte Locale.
  3. Jede Locale hat denselben Satz an Namespace-Dateien (messages/<locale>/<namespace>.json)
     wie die Default-Locale.
  4. Jede Namespace-Datei ist gueltiges JSON mit identischer, vollstaendig verschachtelter
     Key-Struktur ueber alle Locales hinweg (fehlende UND zusaetzliche/verwaiste Keys).
  5. Kein Leaf-Wert ist ein leerer String (das waere eine de-facto fehlende Uebersetzung).

Bei jedem Fund: Exit-Code 1 und eine fuer Menschen lesbare Liste, gruppiert wie
"Missing translations in fr: - participants.import.success".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCALES_SOURCE = ROOT / "i18n/locales.json"

# Nur Projektstruktur (welche Apps haben ueberhaupt Translation Catalogs), keine Sprachliste.
APP_ROOTS = ["frontend", "abgabebox-frontend"]


def load_registered_locales() -> tuple[str, list[str]]:
    data = json.loads(LOCALES_SOURCE.read_text(encoding="utf-8"))
    locales = sorted(data["locales"].keys())
    return data["defaultLocale"], locales


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Platt gezogene dotted-path -> Leaf-Wert Map, z.B. {'participants.delete.confirmTitle': '...'}."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            out.update(flatten(value, path))
    else:
        out[prefix] = obj
    return out


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def check_app(app: str, default_locale: str, locales: list[str]) -> list[str]:
    problems: list[str] = []
    messages_dir = ROOT / app / "messages"
    if not messages_dir.is_dir():
        # App hat (noch) keine Kataloge - kein Fehler an sich, wird aber nicht geprueft.
        return problems

    present_locale_dirs = sorted(p.name for p in messages_dir.iterdir() if p.is_dir())

    for locale in locales:
        if locale not in present_locale_dirs:
            problems.append(f"{app}: Locale '{locale}' ist registriert, hat aber kein messages/{locale}/-Verzeichnis")

    for present in present_locale_dirs:
        if present not in locales:
            problems.append(f"{app}: messages/{present}/ existiert, aber '{present}' ist in i18n/locales.json nicht (mehr) registriert")

    active_locales = [loc for loc in locales if loc in present_locale_dirs]
    if default_locale not in active_locales:
        # Ohne Default-Katalog ist ein Namespace-Soll-Vergleich sinnlos - oben bereits gemeldet.
        return problems

    default_dir = messages_dir / default_locale
    default_namespaces = sorted(p.name for p in default_dir.glob("*.json"))

    # Pro Namespace: geparste Inhalte aller Locales sammeln, dann Keys vergleichen.
    catalogs: dict[str, dict[str, dict[str, Any]]] = {}  # namespace -> locale -> flattened
    for locale in active_locales:
        locale_dir = messages_dir / locale
        locale_namespaces = sorted(p.name for p in locale_dir.glob("*.json"))

        missing_ns = sorted(set(default_namespaces) - set(locale_namespaces))
        extra_ns = sorted(set(locale_namespaces) - set(default_namespaces))
        for ns in missing_ns:
            problems.append(f"{app}/{locale}: Namespace-Datei fehlt: messages/{locale}/{ns}")
        for ns in extra_ns:
            problems.append(f"{app}/{locale}: verwaiste Namespace-Datei ohne Entsprechung in {default_locale}: messages/{locale}/{ns}")

        for ns_file in locale_dir.glob("*.json"):
            try:
                content = json.loads(ns_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                problems.append(f"{rel(ns_file)}: ungueltiges JSON ({exc})")
                continue
            if not isinstance(content, dict):
                problems.append(f"{rel(ns_file)}: oberste Ebene muss ein Objekt sein")
                continue
            catalogs.setdefault(ns_file.name, {})[locale] = flatten(content)

    for ns, by_locale in catalogs.items():
        if default_locale not in by_locale:
            continue  # bereits oben als fehlende Datei gemeldet
        default_keys = set(by_locale[default_locale].keys())
        for locale in active_locales:
            if locale == default_locale or locale not in by_locale:
                continue
            locale_keys = set(by_locale[locale].keys())
            missing = sorted(default_keys - locale_keys)
            extra = sorted(locale_keys - default_keys)
            if missing:
                problems.append(f"Missing translations in {app}/{locale} ({ns}):\n" + "\n".join(f"  - {k}" for k in missing))
            if extra:
                problems.append(f"Extra/verwaiste Keys in {app}/{locale} ({ns}) ohne Entsprechung in {default_locale}:\n" + "\n".join(f"  - {k}" for k in extra))

        # Leere Leaf-Werte (in jeder aktiven Locale, inkl. Default) sind de-facto fehlende
        # Uebersetzungen - ICU-Plural-/Variablen-Strings sind nie leer, ein leerer String ist
        # also immer ein Versehen, kein gueltiger Inhalt.
        for locale in active_locales:
            if locale not in by_locale:
                continue
            empty = sorted(k for k, v in by_locale[locale].items() if isinstance(v, str) and v.strip() == "")
            if empty:
                problems.append(f"Leere Uebersetzung in {app}/{locale} ({ns}):\n" + "\n".join(f"  - {k}" for k in empty))

    return problems


def main() -> int:
    default_locale, locales = load_registered_locales()
    all_problems: list[str] = []
    for app in APP_ROOTS:
        all_problems.extend(check_app(app, default_locale, locales))

    if all_problems:
        print(f"i18n-Completeness-Check: {len(all_problems)} Problem(e) gefunden\n", file=sys.stderr)
        for problem in all_problems:
            print(problem, file=sys.stderr)
            print(file=sys.stderr)
        return 1

    print(f"i18n-Completeness: ok ({len(locales)} Locales: {', '.join(locales)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
