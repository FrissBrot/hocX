#!/usr/bin/env python3
"""Generiert die Locale-Konfiguration aller Apps aus der einzigen Quelle i18n/locales.json.

    python3 scripts/sync-i18n-config.py            # generieren
    python3 scripts/sync-i18n-config.py --check     # nur pruefen (Exit 1 bei Abweichung), fuer CI

i18n/locales.json ist die alleinige Source of Truth fuer unterstuetzte Sprachen (analog zu
design/tokens.css fuer Design-Tokens, siehe scripts/sync-design-tokens.sh). Die hier generierten
Dateien werden nie von Hand editiert - eine neue Sprache wird ausschliesslich in
i18n/locales.json ergaenzt, dieses Skript danach erneut ausgefuehrt.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "i18n/locales.json"

HEADER = "GENERATED FILE - do not edit by hand. Source of truth: i18n/locales.json (repo root)."
REGEN = "Regenerate with: python3 scripts/sync-i18n-config.py"


def load_source() -> dict:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    default_locale = data["defaultLocale"]
    locales = data["locales"]
    if default_locale not in locales:
        raise SystemExit(f"i18n/locales.json: defaultLocale {default_locale!r} fehlt in locales")
    if not data.get("cookieName"):
        raise SystemExit("i18n/locales.json: cookieName fehlt")
    return data


def render_ts(data: dict) -> str:
    locales = data["locales"]
    codes = list(locales.keys())
    union_type = " | ".join(f'"{code}"' for code in codes)
    codes_array = ", ".join(f'"{code}"' for code in codes)
    entries = ",\n".join(
        f'  "{code}": {{ label: {json.dumps(info["label"])}, nativeLabel: {json.dumps(info["nativeLabel"])} }}'
        for code, info in locales.items()
    )
    return f"""// {HEADER}
// {REGEN}

export type Locale = {union_type};

export interface LocaleInfo {{
  /** Anzeigename in der aktuellen UI-Sprache (z.B. fuer Listen im Platform-Admin). */
  label: string;
  /** Name der Sprache in sich selbst, fuer den Language Selector ("Français", "Italiano"). */
  nativeLabel: string;
}}

export const defaultLocale: Locale = "{data['defaultLocale']}";

export const localeCookieName = "{data['cookieName']}";

export const locales: readonly Locale[] = [{codes_array}] as const;

export const localeConfig: Record<Locale, LocaleInfo> = {{
{entries}
}};

export function isLocale(value: string | undefined | null): value is Locale {{
  return !!value && (locales as readonly string[]).includes(value);
}}
"""


def render_py(data: dict) -> str:
    locales = data["locales"]
    entries = ",\n".join(
        f'    "{code}": {{"label": {json.dumps(info["label"])}, "native_label": {json.dumps(info["nativeLabel"])}}}'
        for code, info in locales.items()
    )
    return f'''"""{HEADER}
{REGEN}
"""
from __future__ import annotations

DEFAULT_LOCALE = "{data['defaultLocale']}"

LOCALE_COOKIE_NAME = "{data['cookieName']}"

LOCALES: dict[str, dict[str, str]] = {{
{entries},
}}

SUPPORTED_LOCALES: frozenset[str] = frozenset(LOCALES)


def is_supported_locale(value: str | None) -> bool:
    return value in SUPPORTED_LOCALES


def normalize_locale(value: str | None) -> str:
    """Gibt value zurueck, falls unterstuetzt, sonst DEFAULT_LOCALE - eine unbekannte/leere
    Locale darf nie zu einem Fehler fuehren, nur zum Fallback."""
    return value if is_supported_locale(value) else DEFAULT_LOCALE
'''


TARGETS: list[tuple[Path, str]] = [
    (ROOT / "frontend/i18n/locale-config.generated.ts", "ts"),
    (ROOT / "abgabebox-frontend/i18n/locale-config.generated.ts", "ts"),
    # Kein Punkt im Dateinamen (anders als die .ts-Pendants): "locale_config.generated.py"
    # waere ueber den normalen `import`-Mechanismus nicht als app.core.locale_config.generated
    # importierbar (Python interpretiert das als Paketpfad, nicht als Dateiname mit Punkt).
    (ROOT / "backend/app/core/locale_config_generated.py", "py"),
]


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    data = load_source()
    renderers = {"ts": render_ts, "py": render_py}

    status = 0
    for target, kind in TARGETS:
        content = renderers[kind](data)
        if check_only:
            current = target.read_text(encoding="utf-8") if target.exists() else None
            if current != content:
                print(f"i18n-Konfiguration abweichend: {target.relative_to(ROOT)} (python3 scripts/sync-i18n-config.py ausfuehren)", file=sys.stderr)
                status = 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            print(f"synchronisiert: {target.relative_to(ROOT)}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
