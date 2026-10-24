#!/usr/bin/env python3
"""Erzeugt die Typst-Tokens der Dokument-Engine aus design/tokens.css (einzige Quelle).

    python3 scripts/sync-document-tokens.py           # generieren
    python3 scripts/sync-document-tokens.py --check   # nur pruefen (Exit 1 bei Abweichung), fuer CI

Uebernommen werden die Light-Werte aus dem ersten `:root`-Block: Neutral-, Akzent-, Status- und
Diagrammfarben, Abstaende und Radien. PDFs haben kein Dark-Theme. Pixelwerte werden in Punkt
umgerechnet (1px = 0.75pt). Die erzeugte Datei
backend/app/documents/typst/_tokens.typ wird nie von Hand bearbeitet - gleiche Regel wie fuer
die Kopien von sync-design-tokens.sh.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "design/tokens.css"
TARGET = ROOT / "backend/app/documents/typst/_tokens.typ"

COLOR_TOKENS = [
    "text", "muted", "border", "border-strong", "bg", "panel",
    "accent", "accent-strong", "accent-soft",
    "success", "warning", "danger",
    "success-bg", "success-fg", "warning-bg", "warning-fg", "danger-bg", "danger-fg",
    "neutral-bg", "neutral-fg",
    "chart-1", "chart-2", "chart-3", "chart-4", "chart-5",
    "on-solid",
]
SPACE_TOKENS = ["space-1", "space-2", "space-3", "space-4", "space-5", "space-6"]
RADIUS_TOKENS = ["radius-xs", "radius-sm", "radius-md", "radius-lg"]


def _root_block(css: str) -> str:
    match = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    if not match:
        raise SystemExit("design/tokens.css: kein :root-Block gefunden")
    return match.group(1)


def _values(block: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, value in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", block):
        values[name] = value.strip()
    return values


def _resolve(values: dict[str, str], name: str) -> str:
    value = values[name]
    seen = {name}
    while value.startswith("var("):
        ref = re.match(r"var\(--([a-z0-9-]+)\)", value)
        if not ref or ref.group(1) in seen:
            raise SystemExit(f"design/tokens.css: --{name} nicht aufloesbar ({value})")
        seen.add(ref.group(1))
        value = values[ref.group(1)]
    return value


def _typst_color(value: str, name: str) -> str:
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return f'rgb("{value.lower()}")'
    rgba = re.fullmatch(r"rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*([0-9.]+))?\s*\)", value)
    if rgba:
        r, g, b, a = rgba.groups()
        alpha = float(a) if a is not None else 1.0
        return f"rgb({r}, {g}, {b}, {round(alpha * 100)}%)"
    raise SystemExit(f"design/tokens.css: Farbe --{name} hat ein unbekanntes Format ({value})")


def _typst_length(value: str, name: str) -> str:
    px = re.fullmatch(r"(\d+(?:\.\d+)?)px", value)
    if not px:
        raise SystemExit(f"design/tokens.css: --{name} ist kein px-Wert ({value})")
    points = float(px.group(1)) * 0.75
    return f"{points:g}pt"


def _key(name: str) -> str:
    return name.replace("-", "_")


def render() -> str:
    values = _values(_root_block(SOURCE.read_text(encoding="utf-8")))
    lines = [
        "// GENERIERTE DATEI - nicht von Hand bearbeiten. Quelle: design/tokens.css",
        "// Neu erzeugen mit: python3 scripts/sync-document-tokens.py",
        "",
        "#let colors = (",
    ]
    for name in COLOR_TOKENS:
        lines.append(f"  {_key(name)}: {_typst_color(_resolve(values, name), name)},")
    lines += [")", "", "#let space = ("]
    for name in SPACE_TOKENS:
        # Typst-Schluessel duerfen nicht mit einer Ziffer beginnen: space-1 -> s1
        lines.append(f"  s{name.removeprefix('space-')}: {_typst_length(_resolve(values, name), name)},")
    lines += [")", "", "#let radius = ("]
    for name in RADIUS_TOKENS:
        lines.append(f"  {_key(name.removeprefix('radius-'))}: {_typst_length(_resolve(values, name), name)},")
    lines += [")", ""]
    return "\n".join(lines)


def main() -> int:
    content = render()
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != content:
            print(f"Dokument-Tokens veraltet: {TARGET.relative_to(ROOT)} (python3 scripts/sync-document-tokens.py ausfuehren)", file=sys.stderr)
            return 1
        print("Dokument-Tokens: ok")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(content, encoding="utf-8")
    print(f"generiert: {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
