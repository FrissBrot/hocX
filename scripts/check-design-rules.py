#!/usr/bin/env python3
"""Prueft das Frontend gegen die Design-Regeln aus design/DESIGN.md.

    python3 scripts/check-design-rules.py            # alles pruefen (CI, vor jedem Commit)
    python3 scripts/check-design-rules.py <dateien>  # nur diese Dateien

Ausnahmen: Zeile mit `design-ok` (Kommentar, mit kurzer Begruendung) oder Datei in
ALLOWED_FILES. Neue Ausnahmen nur, wenn es wirklich keine Token-Stufe gibt.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CSS_FILES = [ROOT / "frontend/app/globals.css", ROOT / "abgabebox-frontend/app/globals.css"]
TSX_GLOBS = [
    (ROOT / "frontend", ["components/**/*.tsx", "app/**/*.tsx", "lib/**/*.tsx"]),
    (ROOT / "abgabebox-frontend", ["components/**/*.tsx", "app/**/*.tsx"]),
]
TOKEN_FILE = ROOT / "design/tokens.css"

# Dateien mit bewusst festen Farben (Daten, keine Oberflaechen-Farben).
ALLOWED_HEX_FILES = {
    "frontend/components/settings/document-template-manager.tsx",  # Mockup des PDF-Papiers
    "frontend/components/ui/tag-input.tsx",  # vom Nutzer waehlbare Tag-Farben
    "frontend/components/storage/storage-usage-view.tsx",  # Kategorienfarben (getestet)
    "frontend/components/protocol/collaboration-presence.tsx",  # Avatar-Farben pro Person
}

SPACE_SCALE = {4, 8, 12, 16, 24, 32}
DEPRECATED = {
    "button-inline": "button-secondary",
    "btn-icon-danger": "button-icon-soft-danger",
    "btn-icon-sm": "button-icon-soft-sm",
    "btn-icon": "button-icon-soft",
}

violations: list[str] = []
GLOBAL_TOKENS = set(re.findall(r"(--[a-z0-9-]+)\s*:", TOKEN_FILE.read_text()))


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def report(path: Path, no: int, rule: str, msg: str) -> None:
    violations.append(f"{rel(path)}:{no}: [{rule}] {msg}")


def defined_vars() -> set[str]:
    names = set(re.findall(r"(--[a-z0-9-]+)\s*:", TOKEN_FILE.read_text()))
    for f in CSS_FILES:
        names |= set(re.findall(r"(--[a-z0-9-]+)\s*:", f.read_text()))
    for base, globs in TSX_GLOBS:
        for g in globs:
            for f in base.glob(g):
                names |= set(re.findall(r'"(--[a-z0-9-]+)"\s*:', f.read_text()))
                names |= set(re.findall(r"(--[a-z0-9-]+)\s*:", f.read_text()))
    names |= {"--font-inter", "--button-bg", "--button-hover-bg"}
    return names


def px_values(value: str) -> list[int]:
    if "calc(" in value or "var(" in value and "px" not in re.sub(r"var\([^)]*\)", "", value):
        return []
    return [int(round(float(m))) for m in re.findall(r"(?<![\w.#-])(\d+(?:\.\d+)?)px\b", value)]


def check_line(path: Path, no: int, line: str, defined: set[str], is_css: bool) -> None:
    if "design-ok" in line:
        return
    r = rel(path)
    code = re.sub(r"/\*.*?\*/", "", line)  # Kommentare ignorieren

    # --- Farben -----------------------------------------------------------------
    if r not in ALLOWED_HEX_FILES:
        for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b", code):
            if is_css and re.match(r"\s*--[a-z0-9-]+:", code):
                continue  # lokale Paletten (--c0.., --pv-*) werden am Ort definiert
            report(path, no, "farbe", f"Hex-Farbe {m.group(0)} - Token aus design/tokens.css nutzen")
    for m in re.finditer(r"var\((--[a-z0-9-]+),\s*#", code):
        if m.group(1) in GLOBAL_TOKENS:  # Fallbacks lokaler Variablen (--dt-accent) sind ok
            report(path, no, "farbe", f"Hex-Fallback fuer {m.group(1)} - Token ist immer definiert, Fallback entfernen")

    # --- undefinierte Variablen ---------------------------------------------------
    for m in re.finditer(r"var\((--[a-z0-9-]+)", code):
        if m.group(1) not in defined:
            report(path, no, "variable", f"{m.group(1)} ist nirgends definiert")

    # --- Radius -----------------------------------------------------------------------
    for m in re.finditer(r"(?:border-[a-z-]*radius|borderRadius|border-radius)\s*[:=]\s*([^;,}]+)", code):
        v = m.group(1).strip().strip("\"'")
        if re.fullmatch(r"\d+(\.\d+)?(px)?", v) and v not in ("0", "0px"):
            report(path, no, "radius", f"Radius-Literal {v} - var(--radius-xs|sm|md|lg|xl|pill)")
        elif "px" in v and "var(" not in v and "calc(" not in v:
            report(path, no, "radius", f"Radius-Literal {v} - Radius-Token nutzen")

    # --- Schriftgroesse -----------------------------------------------------------------
    if "tick=" in code or "<Legend" in code:
        code_fs = ""  # Diagramm-Props (SVG-Einheiten), keine CSS-Schrift
    else:
        code_fs = code
    for m in re.finditer(r"(?:font-size|fontSize)\s*[:=]\s*\{?\s*([^;,}]+)", code_fs):
        v = m.group(1).strip().strip("\"'")
        if re.fullmatch(r"\d+(\.\d+)?(px|rem)?", v):
            report(path, no, "schrift", f"Schrift-Literal {v} - var(--text-xs|sm|base|md|lg|xl|2xl|3xl)")

    # --- z-index --------------------------------------------------------------------------
    for m in re.finditer(r"(?:z-index|zIndex)\s*[:=]\s*\{?\s*(\d+)", code):
        if int(m.group(1)) > 5:
            report(path, no, "z-index", f"z-index {m.group(1)} - Ebenen-Token (--z-*) nutzen; lokal nur 0-5")

    # --- Bewegung (nur CSS) ----------------------------------------------------------------
    if is_css and re.search(r"(?<![\w-])transition[a-z-]*\s*:", code):
        if re.search(r"(?<![\w.-])0?\.\d+s\b|(?<![\w.-])\d{2,3}ms\b", code):
            report(path, no, "bewegung", "Transition-Dauer als Literal - var(--dur-fast|base|slow)")

    # --- Abstaende -------------------------------------------------------------------------------
    for m in re.finditer(r"(?<![\w-])(gap|row-gap|column-gap|padding[a-zA-Z-]*|margin[a-zA-Z-]*)\s*[:=]\s*([^;}]+)", code):
        prop, value = m.group(1), m.group(2)
        if re.search(r"vh|clamp\(", value):
            continue
        for n in px_values(value):
            if n > 36 or n <= 3:
                continue  # Feinabstaende und grosse Flaechen bleiben frei
            if n not in SPACE_SCALE:
                report(path, no, "abstand", f"{prop}: {n}px liegt nicht auf der Skala 4/8/12/16/24/32 - var(--space-N)")

    # --- Box-Shadow ------------------------------------------------------------------------------
    if re.search(r"(?:box-shadow|boxShadow)\s*[:=]", code) and re.search(r"rgba?\(\s*(0|16|12|22)\s*,", code) and not re.fullmatch(r"\s*(?:box-shadow\s*:\s*)?0\s+\d+px\s+[1-8]px\s+rgba?\([^)]*\)\s*;?\s*", code):
        report(path, no, "schatten", "Schatten mit festem rgba - var(--shadow|--shadow-soft|--shadow-popover|--shadow-overlay)")

    # --- veraltete Klassen ------------------------------------------------------------------------------
    if not is_css:
        for old, new in DEPRECATED.items():
            if re.search(r"(?<![\w-])" + re.escape(old) + r"(?![\w-])", code):
                report(path, no, "klasse", f"'{old}' ist umbenannt - '{new}' nutzen")
        if re.search(r"\bwindow\.(confirm|alert|prompt)\(|(?<![\w.])(?:alert|prompt)\(", code):
            report(path, no, "dialog", "Native Dialoge vermeiden - useConfirm()/useToast() nutzen")
        if re.search(r"<(?:select|dialog)\b", code):
            pass  # <select> ist fuer einfache Listen erlaubt


def main() -> int:
    defined = defined_vars()
    targets = [Path(a).resolve() for a in sys.argv[1:]]
    files: list[tuple[Path, bool]] = [(f, True) for f in CSS_FILES]
    for base, globs in TSX_GLOBS:
        for g in globs:
            files += [(f, False) for f in base.glob(g) if ".test." not in f.name]
    for path, is_css in files:
        if targets and path.resolve() not in targets:
            continue
        for no, line in enumerate(path.read_text().splitlines(), 1):
            check_line(path, no, line, defined, is_css)

    if violations:
        print("\n".join(violations))
        print(f"\n{len(violations)} Design-Regelverstoesse - siehe design/DESIGN.md")
        return 1
    print("Design-Regeln: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
