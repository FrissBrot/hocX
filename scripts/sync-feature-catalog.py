#!/usr/bin/env python3
"""Generiert den Feature-Katalog (buchbare Produkt-Features) für Backend und Frontend aus
permissions/features.json.

    python3 scripts/sync-feature-catalog.py            # generieren
    python3 scripts/sync-feature-catalog.py --check    # nur prüfen (Exit 1 bei Abweichung), für CI

permissions/features.json ist die einzige Quelle für Feature-Codes, Modulzuordnung,
Downgrade-Verhalten (read_only/blocked), die im Nur-Lesen-Zustand weiter geltenden
Berechtigungen und Abhängigkeiten. Die generierten Dateien werden nie von Hand editiert.
--check verlangt zusätzlich je Feature eine Migration, die es in die Tabelle ``feature``
einträgt, und eine Prüfung im Backend. Hintergrund: docs/FEATURE_ENTITLEMENT_ARCHITECTURE.md.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "permissions/features.json"
PERMISSIONS_SOURCE = ROOT / "permissions/catalog.json"
TS_TARGET = ROOT / "frontend/lib/features.generated.ts"
PY_TARGET = ROOT / "backend/app/core/features_generated.py"

HEADER = "GENERATED FILE - do not edit by hand. Source of truth: permissions/features.json (repo root)."
REGEN = "Regenerate with: python3 scripts/sync-feature-catalog.py"

CODE_PATTERN = re.compile(r"^[a-z][a-z_]*$")
DOWNGRADES = ("read_only", "blocked")


def load_source() -> dict:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    permission_keys = {entry["key"] for entry in json.loads(PERMISSIONS_SOURCE.read_text(encoding="utf-8"))["permissions"]}
    codes: list[str] = []
    for entry in data["features"]:
        code = entry["code"]
        if not CODE_PATTERN.match(code) or code in codes:
            raise SystemExit(f"permissions/features.json: ungültiger oder doppelter Code {code!r}")
        if entry["module"] not in data["modules"]:
            raise SystemExit(f"permissions/features.json: unbekanntes Modul bei {code}")
        if entry["downgrade"] not in DOWNGRADES:
            raise SystemExit(f"permissions/features.json: downgrade muss {DOWNGRADES} sein ({code})")
        unknown = [key for key in entry["read_permissions"] if key not in permission_keys]
        if unknown:
            raise SystemExit(f"permissions/features.json: {code} mit unbekannten Berechtigungen {unknown}")
        if entry["read_permissions"] and entry["downgrade"] != "read_only":
            raise SystemExit(f"permissions/features.json: read_permissions nur bei downgrade read_only ({code})")
        codes.append(code)
    for entry in data["features"]:
        unknown = [code for code in entry["requires"] if code not in codes or code == entry["code"]]
        if unknown:
            raise SystemExit(f"permissions/features.json: {entry['code']} verlangt unbekannte {unknown}")
    return data


def feature_codes() -> tuple[str, ...]:
    """Für sync-permission-catalog.py (Feature-Bindung einer Berechtigung)."""
    return tuple(entry["code"] for entry in load_source()["features"])


def render_py(data: dict) -> str:
    lines = [
        f"# {HEADER}",
        f"# {REGEN}",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from enum import StrEnum",
        "",
        "",
        "class F(StrEnum):",
    ]
    for entry in data["features"]:
        lines.append(f'    {entry["code"].upper()} = "{entry["code"]}"')
    lines += [
        "",
        "",
        "@dataclass(frozen=True)",
        "class FeatureDef:",
        "    module: str",
        "    downgrade: str",
        "    read_permissions: frozenset[str]",
        "    requires: tuple[str, ...]",
        "",
        "",
        "# Produktmodule in fester Reihenfolge (docs/PRODUCT_MODULE_ARCHITECTURE.md)",
        f"MODULES: tuple[str, ...] = ({''.join(f'{chr(34)}{module}{chr(34)}, ' for module in data['modules'])})",
        "",
        "FEATURES: dict[F, FeatureDef] = {",
    ]
    for entry in data["features"]:
        read = ", ".join(f'"{key}"' for key in entry["read_permissions"])
        read_set = f"frozenset({{{read}}})" if read else "frozenset()"
        requires = "".join(f'"{code}", ' for code in entry["requires"])
        lines.append(
            f'    F.{entry["code"].upper()}: FeatureDef(module="{entry["module"]}", downgrade="{entry["downgrade"]}", '
            f"read_permissions={read_set}, requires=({requires})),"
        )
    lines += ["}", ""]
    return "\n".join(lines)


def render_ts(data: dict) -> str:
    codes = " | ".join(f'"{entry["code"]}"' for entry in data["features"])
    modules = " | ".join(f'"{module}"' for module in data["modules"])
    lines = [
        f"// {HEADER}",
        f"// {REGEN}",
        "",
        f"export type FeatureCode = {codes};",
        f"export type FeatureModule = {modules};",
        "",
        "export type FeatureInfo = {",
        "  code: FeatureCode;",
        "  module: FeatureModule;",
        '  downgrade: "read_only" | "blocked";',
        "  readPermissions: string[];",
        "  requires: FeatureCode[];",
        "};",
        "",
        "export const FEATURES: readonly FeatureInfo[] = [",
    ]
    for entry in data["features"]:
        read = ", ".join(f'"{key}"' for key in entry["read_permissions"])
        requires = ", ".join(f'"{code}"' for code in entry["requires"])
        lines.append(
            f'  {{ code: "{entry["code"]}", module: "{entry["module"]}", downgrade: "{entry["downgrade"]}", readPermissions: [{read}], requires: [{requires}] }},'
        )
    lines += ["];", ""]
    return "\n".join(lines)


def consistency_problems(data: dict) -> list[str]:
    """Jedes Feature braucht eine Migration (Eintrag in ``feature``) und eine Prüfung im Backend."""
    problems: list[str] = []
    migrations = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "backend/alembic/versions").glob("*.py"))
    backend = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "backend/app").rglob("*.py") if path != PY_TARGET)
    permissions = json.loads(PERMISSIONS_SOURCE.read_text(encoding="utf-8"))["permissions"]
    for entry in data["features"]:
        code = entry["code"]
        if f"'{code}'" not in migrations and f'"{code}"' not in migrations:
            problems.append(f"{code}: keine Migration trägt das Feature in die Tabelle feature ein")
        bound = any(permission["feature"] == code for permission in permissions)
        if not bound and f"F.{code.upper()}" not in backend and f'"{code}"' not in backend:
            problems.append(f"{code}: keine Prüfung im Backend (require_feature/F.{code.upper()} oder Berechtigungsbindung)")
    return problems


def main() -> int:
    check = "--check" in sys.argv[1:]
    data = load_source()
    outputs = {TS_TARGET: render_ts(data), PY_TARGET: render_py(data)}
    stale = [path for path, content in outputs.items() if not path.exists() or path.read_text(encoding="utf-8") != content]
    if check:
        problems = [f"{path.relative_to(ROOT)} ist nicht aktuell" for path in stale] + consistency_problems(data)
        if problems:
            print("Feature-Katalog: Abweichungen gefunden", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            print(f"  {REGEN}", file=sys.stderr)
            return 1
        print("Feature-Katalog: ok")
        return 0
    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
        print(f"Geschrieben: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
