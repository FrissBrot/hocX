#!/usr/bin/env python3
"""Prüft, dass Dokument-Engine und Document Studio vollständig verdrahtet sind.

    PYTHONPATH=backend python3 scripts/check-document-catalog.py

Fachkomponenten (Daten-Blöcke, backend/app/documents/model.py + catalog.py):
  1. Modell, Katalog-Eintrag mit Parameter-Modell und Provider (providers/__init__.py);
     innere Blöcke (catalog.CHILD_ONLY_BLOCKS) brauchen nur eine Basis-Komponente
  2. eine Basis-Komponente (typst/base/blocks.typ, base-components)
  3. die Texte blockType.<typ> und empty.<typ> im Namespace documentPdf
  4. im Namespace documentStudio: component.<typ>, componentHelp.<typ> sowie Labels für alle
     Parameter (params.<name>) und Auswahlwerte (enum.<wert>)

Document Studio (Labels, die das Frontend dynamisch zusammensetzt und die deshalb
check-i18n-key-resolution.py nicht statisch sieht), alle im Namespace documentStudio:
  nodeType.<typ>, library.entry/help.<key>, libraryGroup.<gruppe>, binding.<pfad>,
  bindingField.<feld>, bindingGroup.<gruppe>, bindingType.<typ>, docType/docTypeHelp.<typ>,
  category.<kategorie>, system.<key>.name/description, colorRef.<farbe>,
  brand.presetName/presetHelp.<preset>, font.<schrift>

Zusätzlich: jeder Paket-Import (@namespace/name:version) in den Typst-Dateien muss im vendorten
Paketverzeichnis liegen - der Compile darf nie ins Netz.

Die Vollständigkeit über alle Sprachen prüft check-i18n-completeness.py; hier genügt die
Standardsprache. Braucht die Backend-Abhängigkeiten (Pydantic) und läuft deshalb im
Backend-Container bzw. im Backend-Job der CI.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.documents.bindings import REGISTRY  # noqa: E402
from app.documents.brand import BRAND_PRESETS, BUILTIN_FONTS, BrandColors  # noqa: E402
from app.documents.catalog import CATALOG, CHILD_ONLY_BLOCKS  # noqa: E402
from app.documents.components import LIBRARY, NODE_TYPES  # noqa: E402
from app.documents.doc_types import CATEGORIES, DOCUMENT_TYPES  # noqa: E402
from app.documents.model import BLOCK_MODELS  # noqa: E402
from app.documents.providers import PROVIDERS  # noqa: E402
from app.documents.system_templates import SYSTEM_TEMPLATES  # noqa: E402

TYPST = ROOT / "backend/app/documents/typst"
PACKAGES = ROOT / "backend/app/documents/typst_packages"
DEFAULT_LOCALE = json.loads((ROOT / "i18n/locales.json").read_text(encoding="utf-8"))["defaultLocale"]
MESSAGES = ROOT / "frontend/messages" / DEFAULT_LOCALE
# Strukturblöcke ohne eigene Komponente (werden vom Layout bzw. der Protokoll-Komponente gesetzt)
WITHOUT_COMPONENT = {"protocol_element"}


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
    blocks_typ = (TYPST / "base/blocks.typ").read_text(encoding="utf-8")
    component_section = blocks_typ[blocks_typ.index("#let base-components = (") :]
    components = set(re.findall(r"^\s+([a-z_]+):", component_section, re.M))
    pdf_keys = flatten(json.loads((MESSAGES / "documentPdf.json").read_text(encoding="utf-8")))
    ui_keys = flatten(json.loads((MESSAGES / "documentStudio.json").read_text(encoding="utf-8")))

    def need(key: str, owner: str) -> None:
        if key not in ui_keys:
            problems.append(f"{owner}: Label {key} fehlt in documentStudio.json")

    # Fachkomponenten
    for block_type in sorted(model_types | set(CATALOG) | set(PROVIDERS)):
        if block_type not in model_types:
            problems.append(f"{block_type}: fehlt im Dokumentmodell (model.py, Block-Union)")
        if block_type in CHILD_ONLY_BLOCKS:
            # Innere Blöcke (z. B. Protokolltexte): kein eigener Katalog-Eintrag, kein Provider
            if block_type not in components:
                problems.append(f"{block_type}: keine Basis-Komponente (typst/base/blocks.typ)")
            continue
        if block_type not in CATALOG:
            problems.append(f"{block_type}: fehlt im Katalog (catalog.py)")
        if block_type not in PROVIDERS:
            problems.append(f"{block_type}: kein Provider (providers/__init__.py)")
        if block_type not in components and block_type not in WITHOUT_COMPONENT:
            problems.append(f"{block_type}: keine Basis-Komponente (typst/base/blocks.typ)")
        for key in (f"blockType.{block_type}", f"empty.{block_type}"):
            if key not in pdf_keys:
                problems.append(f"{block_type}: Text {key} fehlt in documentPdf.json")
        if block_type in CATALOG:
            need(f"component.{block_type}", block_type)
            need(f"componentHelp.{block_type}", block_type)
            names, values = schema_names(CATALOG[block_type].params.model_json_schema())
            for name in sorted(names):
                need(f"params.{name}", block_type)
            for value in sorted(values):
                need(f"enum.{value}", block_type)

    # Document Studio
    for node_type in NODE_TYPES:
        need(f"nodeType.{node_type}", "Knotentyp")
    for entry in LIBRARY:
        need(f"library.entry.{entry.key}", "Bibliothek")
        need(f"library.help.{entry.key}", "Bibliothek")
        need(f"libraryGroup.{entry.group}", "Bibliothek")
    for path, definition in REGISTRY.items():
        need(f"binding.{path.replace('.', '_')}", "Bindung")
        need(f"bindingGroup.{definition.group}", "Bindung")
        need(f"bindingType.{definition.type}", "Bindung")
        for item_field in definition.item_fields:
            need(f"bindingField.{item_field.key}", f"Bindung {path}")
    for key, doc_type in DOCUMENT_TYPES.items():
        need(f"docType.{key}", "Dokumenttyp")
        need(f"docTypeHelp.{key}", "Dokumenttyp")
    for category in CATEGORIES:
        need(f"category.{category}", "Kategorie")
    for template in SYSTEM_TEMPLATES:
        need(f"system.{template.key}.name", "Systemvorlage")
        need(f"system.{template.key}.description", "Systemvorlage")
        if template.document_type not in DOCUMENT_TYPES:
            problems.append(f"Systemvorlage {template.key}: unbekannter Dokumenttyp {template.document_type}")
    for color in BrandColors.model_fields:
        if color != "custom":
            need(f"colorRef.{color}", "Brand-Farbe")
    for preset in BRAND_PRESETS:
        need(f"brand.presetName.{preset}", "Brand-Vorlage")
        need(f"brand.presetHelp.{preset}", "Brand-Vorlage")
    for font in BUILTIN_FONTS:
        need(f"font.{font}", "Schrift")
    covered = {template.document_type for template in SYSTEM_TEMPLATES}
    for key in DOCUMENT_TYPES:
        if key not in covered:
            problems.append(f"Dokumenttyp {key}: keine Systemvorlage (system_templates.py)")

    for typ_file in TYPST.rglob("*.typ"):
        for namespace, name, version in re.findall(r'#import\s+"@([a-z0-9-]+)/([a-z0-9-]+):([0-9.]+)"', typ_file.read_text(encoding="utf-8")):
            if not (PACKAGES / namespace / name / version / "typst.toml").exists():
                problems.append(f"{typ_file.relative_to(ROOT)}: Paket @{namespace}/{name}:{version} ist nicht vendored ({PACKAGES.relative_to(ROOT)})")

    if problems:
        print("Dokument-Katalog unvollständig:", file=sys.stderr)
        for problem in sorted(set(problems)):
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"Dokument-Katalog: ok ({len(CATALOG)} Fachkomponenten, {len(NODE_TYPES)} Knotentypen, {len(LIBRARY)} Bibliothekseinträge, {len(SYSTEM_TEMPLATES)} Systemvorlagen)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
