#!/usr/bin/env python3
"""Prüft, dass jeder Block-Typ der Dokument-Engine vollständig ist.

    PYTHONPATH=backend python3 scripts/check-document-catalog.py

Für jeden Block-Typ im Dokumentmodell (backend/app/documents/model.py) muss es geben:
  1. einen Katalog-Eintrag mit Parameter-Modell (catalog.py)
  2. einen Provider (providers/__init__.py)
  3. eine Basis-Komponente (styles/base/blocks.typ, base-components)
  4. die Texte blockType.<typ> und empty.<typ> im Namespace documentPdf (alle Locales prüft
     check-i18n-completeness.py) sowie Labels für alle Parameter und Auswahlwerte im
     Namespace documents (params.<name>, enum.<wert>)

Zusätzlich: jeder Paket-Import (@namespace/name:version) in den Stilen muss im vendorten
Paketverzeichnis liegen - der Compile darf nie ins Netz.

Braucht die Backend-Abhängigkeiten (Pydantic) und läuft deshalb im Backend-Container bzw. im
Backend-Job der CI.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.documents.catalog import CATALOG  # noqa: E402
from app.documents.model import BLOCK_MODELS  # noqa: E402
from app.documents.providers import PROVIDERS  # noqa: E402

STYLES = ROOT / "backend/app/documents/styles"
PACKAGES = ROOT / "backend/app/documents/typst_packages"
DEFAULT_LOCALE = json.loads((ROOT / "i18n/locales.json").read_text(encoding="utf-8"))["defaultLocale"]
MESSAGES = ROOT / "frontend/messages" / DEFAULT_LOCALE


def flatten(data: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        keys.update(flatten(value, path) if isinstance(value, dict) else {path})
    return keys


def schema_names(schema: dict) -> tuple[set[str], set[str]]:
    """Parameternamen und Auswahlwerte eines Pydantic-JSON-Schemas (inkl. $defs)."""
    names: set[str] = set()
    values: set[str] = set()

    def walk(node, collect_names: bool):
        if isinstance(node, dict):
            if collect_names and isinstance(node.get("properties"), dict):
                for name, prop in node["properties"].items():
                    if (prop.get("x-widget") if isinstance(prop, dict) else None) == "hidden":
                        continue
                    names.add(name)
                    walk(prop, False)
            for enum_value in node.get("enum", []) or []:
                values.add("none" if enum_value in ("", None) else str(enum_value))
            for key, value in node.items():
                if key == "properties":
                    continue
                walk(value, key == "$defs" or collect_names and key in ("items",))
        elif isinstance(node, list):
            for item in node:
                walk(item, collect_names)

    walk(schema, True)
    for definition in (schema.get("$defs") or {}).values():
        walk(definition, True)
    return names, values


def main() -> int:
    problems: list[str] = []
    model_types = set(BLOCK_MODELS)
    blocks_typ = (STYLES / "base/blocks.typ").read_text(encoding="utf-8")
    component_section = blocks_typ[blocks_typ.index("#let base-components = (") :]
    components = set(re.findall(r"^\s+([a-z_]+):", component_section, re.M))
    pdf_keys = flatten(json.loads((MESSAGES / "documentPdf.json").read_text(encoding="utf-8")))
    ui_keys = flatten(json.loads((MESSAGES / "documents.json").read_text(encoding="utf-8")))

    for block_type in sorted(model_types | set(CATALOG) | set(PROVIDERS)):
        if block_type not in model_types:
            problems.append(f"{block_type}: fehlt im Dokumentmodell (model.py, Block-Union)")
        if block_type not in CATALOG:
            problems.append(f"{block_type}: fehlt im Katalog (catalog.py)")
        if block_type not in PROVIDERS:
            problems.append(f"{block_type}: kein Provider (providers/__init__.py)")
        if block_type not in components and block_type != "protocol_element":
            problems.append(f"{block_type}: keine Basis-Komponente (styles/base/blocks.typ)")
        for key in (f"blockType.{block_type}", f"empty.{block_type}"):
            if key not in pdf_keys:
                problems.append(f"{block_type}: Text {key} fehlt in documentPdf.json")
        if block_type in CATALOG:
            names, values = schema_names(CATALOG[block_type].params.model_json_schema())
            for name in sorted(names):
                if f"params.{name}" not in ui_keys:
                    problems.append(f"{block_type}: Parameter-Label params.{name} fehlt in documents.json")
            for value in sorted(values):
                if f"enum.{value}" not in ui_keys:
                    problems.append(f"{block_type}: Auswahl-Label enum.{value} fehlt in documents.json")
            if f"groups.{CATALOG[block_type].group}" not in ui_keys:
                problems.append(f"{block_type}: Gruppen-Label groups.{CATALOG[block_type].group} fehlt")

    for typ_file in STYLES.rglob("*.typ"):
        for namespace, name, version in re.findall(r'#import\s+"@([a-z0-9-]+)/([a-z0-9-]+):([0-9.]+)"', typ_file.read_text(encoding="utf-8")):
            if not (PACKAGES / namespace / name / version / "typst.toml").exists():
                problems.append(f"{typ_file.relative_to(ROOT)}: Paket @{namespace}/{name}:{version} ist nicht vendored ({PACKAGES.relative_to(ROOT)})")

    if problems:
        print("Dokument-Katalog unvollständig:", file=sys.stderr)
        for problem in sorted(set(problems)):
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"Dokument-Katalog: ok ({len(model_types)} Block-Typen)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
