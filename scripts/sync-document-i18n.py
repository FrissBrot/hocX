#!/usr/bin/env python3
"""Kopiert die festen PDF-Texte (Namespace documentPdf) ins Backend.

    python3 scripts/sync-document-i18n.py           # kopieren
    python3 scripts/sync-document-i18n.py --check   # nur pruefen (Exit 1 bei Abweichung), fuer CI

Quelle sind frontend/messages/<locale>/documentPdf.json - dort pflegen und pruefen die
i18n-Skripte (Vollstaendigkeit ueber alle Locales aus i18n/locales.json) sie wie jeden anderen
Namespace. Das Backend hat einen eigenen Docker-Build-Kontext und liest deshalb eine generierte
Kopie unter backend/app/documents/i18n/<locale>.json. Die Kopien nie von Hand bearbeiten.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES_SOURCE = ROOT / "i18n/locales.json"
SOURCE_DIR = ROOT / "frontend/messages"
TARGET_DIR = ROOT / "backend/app/documents/i18n"
NAMESPACE = "documentPdf"


def expected() -> dict[Path, str]:
    locales = json.loads(LOCALES_SOURCE.read_text(encoding="utf-8"))["locales"]
    files: dict[Path, str] = {}
    for locale in locales:
        source = SOURCE_DIR / locale / f"{NAMESPACE}.json"
        if not source.exists():
            raise SystemExit(f"{source.relative_to(ROOT)} fehlt")
        data = json.loads(source.read_text(encoding="utf-8"))
        files[TARGET_DIR / f"{locale}.json"] = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return files


def main() -> int:
    files = expected()
    stale = [path for path in TARGET_DIR.glob("*.json") if path not in files]
    if "--check" in sys.argv:
        problems = [path for path, content in files.items() if not path.exists() or path.read_text(encoding="utf-8") != content]
        problems += stale
        if problems:
            for path in problems:
                print(f"Dokumenttexte veraltet: {path.relative_to(ROOT)} (python3 scripts/sync-document-i18n.py ausfuehren)", file=sys.stderr)
            return 1
        print("Dokumenttexte: ok")
        return 0
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
        print(f"synchronisiert: {path.relative_to(ROOT)}")
    for path in stale:
        path.unlink()
        print(f"entfernt: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
