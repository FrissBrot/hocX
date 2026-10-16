#!/usr/bin/env python3
"""Generiert die Elementtyp-Registry für Frontend und Backend aus element-types/registry.json.

    python3 scripts/sync-element-types.py            # generieren
    python3 scripts/sync-element-types.py --check    # nur prüfen (Exit 1 bei Abweichung), für CI

element-types/registry.json ist die einzige Quelle für id, Code, Render-Typ, Kategorie und
die Fähigkeiten jedes Elementtyps (analog zu i18n/locales.json, siehe sync-i18n-config.py).
Vorher waren diese Angaben in mehreren, voneinander abweichenden Tabellen verteilt
(element-definition-manager.tsx, protocol-editor-shared.tsx, element_definition_service.py).
Die generierten Dateien werden nie von Hand editiert.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "element-types/registry.json"
TS_TARGET = ROOT / "frontend/lib/element-types/registry.generated.ts"
PY_TARGET = ROOT / "backend/app/core/element_types_generated.py"

HEADER = "GENERATED FILE - do not edit by hand. Source of truth: element-types/registry.json (repo root)."
REGEN = "Regenerate with: python3 scripts/sync-element-types.py"

FIELDS = (
    "id",
    "code",
    "category",
    "render_type_id",
    "allows_multiple_values",
    "default_editable",
    "pickable",
    "content",
    "repeat",
    "carry_over",
    "matrix_embeddable",
)
CATEGORIES = ("basics", "finance", "organisation")
REPEAT_SOURCES = ("event", "todo")


def load_source() -> list[dict]:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    types = data["types"]
    seen_ids: set[int] = set()
    seen_codes: set[str] = set()
    for entry in types:
        missing = [field for field in FIELDS if field not in entry]
        if missing:
            raise SystemExit(f"element-types/registry.json: Typ {entry.get('id')} ohne {missing}")
        if entry["id"] in seen_ids or entry["code"] in seen_codes:
            raise SystemExit(f"element-types/registry.json: doppelte id/code bei {entry['id']}/{entry['code']}")
        if entry["category"] not in CATEGORIES:
            raise SystemExit(f"element-types/registry.json: unbekannte Kategorie {entry['category']!r}")
        if any(source not in REPEAT_SOURCES for source in entry["repeat"]):
            raise SystemExit(f"element-types/registry.json: unbekannte Wiederholungsquelle bei {entry['code']}")
        seen_ids.add(entry["id"])
        seen_codes.add(entry["code"])
    return types


def render_ts(types: list[dict]) -> str:
    codes = " | ".join(json.dumps(entry["code"]) for entry in types)
    rows = []
    for entry in types:
        rows.append(
            "  {"
            f" id: {entry['id']},"
            f" code: {json.dumps(entry['code'])},"
            f" category: {json.dumps(entry['category'])},"
            f" renderTypeId: {entry['render_type_id']},"
            f" allowsMultipleValues: {json.dumps(entry['allows_multiple_values'])},"
            f" defaultEditable: {json.dumps(entry['default_editable'])},"
            f" pickable: {json.dumps(entry['pickable'])},"
            f" content: {json.dumps(entry['content'])},"
            f" repeat: {json.dumps(entry['repeat'])},"
            f" carryOver: {json.dumps(entry['carry_over'])},"
            f" matrixEmbeddable: {json.dumps(entry['matrix_embeddable'])}"
            " },"
        )
    body = "\n".join(rows)
    return f"""// {HEADER}
// {REGEN}

export type ElementTypeCode = {codes};
export type ElementTypeCategory = {" | ".join(json.dumps(c) for c in CATEGORIES)};
export type RepeatSource = {" | ".join(json.dumps(s) for s in REPEAT_SOURCES)};

export type ElementTypeInfo = {{
  id: number;
  code: ElementTypeCode;
  category: ElementTypeCategory;
  renderTypeId: number;
  allowsMultipleValues: boolean;
  defaultEditable: boolean;
  pickable: boolean;
  content: boolean;
  repeat: RepeatSource[];
  carryOver: boolean;
  matrixEmbeddable: boolean;
}};

export const ELEMENT_TYPES: readonly ElementTypeInfo[] = [
{body}
];
"""


def render_py(types: list[dict]) -> str:
    rows = []
    for entry in types:
        values = ", ".join(f"{json.dumps(field)}: {render_py_value(entry[field])}" for field in FIELDS)
        rows.append(f"    {{{values}}},")
    body = "\n".join(rows)
    return f'''# {HEADER}
# {REGEN}
from __future__ import annotations

ELEMENT_TYPES: tuple[dict, ...] = (
{body}
)
'''


def render_py_value(value: object) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, list):
        return "(" + "".join(f"{json.dumps(item)}, " for item in value).rstrip(" ") + ")"
    return json.dumps(value)


def main() -> int:
    check = "--check" in sys.argv[1:]
    types = load_source()
    outputs = {TS_TARGET: render_ts(types), PY_TARGET: render_py(types)}
    stale = [path for path, content in outputs.items() if not path.exists() or path.read_text(encoding="utf-8") != content]
    if check:
        if stale:
            for path in stale:
                print(f"veraltet: {path.relative_to(ROOT)}")
            print("Elementtyp-Registry: veraltet - python3 scripts/sync-element-types.py ausführen")
            return 1
        print("Elementtyp-Registry: ok")
        return 0
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"geschrieben: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
