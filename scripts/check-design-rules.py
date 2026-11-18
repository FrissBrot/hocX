#!/usr/bin/env python3
"""Prueft das Frontend gegen die Design-Regeln aus design/DESIGN.md.

    python3 scripts/check-design-rules.py            # alles pruefen (CI, vor jedem Commit)
    python3 scripts/check-design-rules.py <dateien>  # nur diese Dateien

Ausnahmen: Zeile mit `design-ok` (Kommentar, mit kurzer Begruendung) oder Datei in
ALLOWED_FILES. Neue Ausnahmen nur, wenn es wirklich keine Token-Stufe gibt.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CSS_FILES = [
    ROOT / "frontend/app/globals.css",
    *sorted((ROOT / "frontend/app/styles").glob("*.css")),  # Bereichs-CSS (check-css-scopes.py)
    ROOT / "abgabebox-frontend/app/globals.css",
]
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

# Bausteine, die das native Auswahl-/Picker-Element selbst kapseln
NATIVE_PICKER_FILES = {
    "frontend/components/ui/select.tsx",
    "frontend/components/ui/date-input.tsx",
    "frontend/components/ui/time-input.tsx",
    "frontend/components/ui/color-input.tsx",
    "abgabebox-frontend/components/ui/select.tsx",
}

# Einziger Ort für das Parsen/Eingeben von Uhrzeiten (Standard, siehe DESIGN.md Abschnitt 6)
TIME_STANDARD_FILES = {
    "frontend/components/ui/time-input.tsx",
    "frontend/lib/utils/time.ts",
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
        if m.group(1) in GLOBAL_TOKENS:  # Fallbacks lokaler Variablen sind ok
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
        # Natives Auswahl-/Datums-/Zeit-/Farbfeld zeigt die Oberflaeche des Betriebssystems:
        # Select, DateInput, TimeInput, ColorInput nutzen (die Bausteine selbst kapseln das
        # native Element; die Abgabebox hat bisher nur Select)
        if r.startswith(("frontend/", "abgabebox-frontend/")) and r not in NATIVE_PICKER_FILES and not code.lstrip().startswith(("//", "*")):
            if re.search(r"<select\b", code):
                report(path, no, "auswahl", "Natives <select> - Select aus @/components/ui/select nutzen")
            m = re.search(r"type=[\"'{]+(date|time|datetime-local|color)[\"'}]", code)
            if m:
                component = {"date": "DateInput", "datetime-local": "DateInput + TimeInput", "time": "TimeInput", "color": "ColorInput"}[m.group(1)]
                report(path, no, "auswahl", f"Natives type=\"{m.group(1)}\" - {component} nutzen")
            # Uhrzeit als einfaches Textfeld (Platzhalter hh:mm oder Wert/Name eines Zeitfelds):
            # nur TimeInput versteht 1130, 230, 14 Uhr … und korrigiert auf HH:MM (DESIGN.md Abschnitt 6)
            if r not in TIME_STANDARD_FILES and (
                re.search(r"<input\b[^>]*placeholder=[\"'{][^\"'}]*\b[hH]{1,2}[:.][mM]{2}\b", code)
                or re.search(r"<input\b[^>]*\b(?:value|name)=\{?[^}>]*(?:_time|Time)\b(?!stamp|zone|out)", code)
            ):
                report(path, no, "zeit", "Uhrzeit-Eingabe ohne TimeInput - TimeInput aus @/components/ui/time-input nutzen")
            if r not in TIME_STANDARD_FILES and re.search(r"/\^?\(?\\d\{1,2\}\)?\s?(?:\[[^\]]*\]|:|\\.)", code):
                report(path, no, "zeit", "Eigene Zeit-Regex - parseTimeInputValue aus @/lib/utils/time nutzen")


# Bausteine, die die Abgabebox als Kopie der (dort getesteten) Hauptanwendung fuehrt: muessen
# gleich bleiben, bis auf Kommentarzeilen am Dateianfang (Herkunftshinweis).
SHARED_COPIES = {
    "abgabebox-frontend/components/ui/select.tsx": "frontend/components/ui/select.tsx",
}


def check_shared_copies() -> None:
    def body(path: Path) -> list[str]:
        lines = path.read_text().splitlines()
        return [line for line in lines if not line.startswith("// Auswahlfeld im hocX-Look")]

    for copy, source in SHARED_COPIES.items():
        if body(ROOT / copy) != body(ROOT / source):
            report(ROOT / copy, 1, "kopie", f"weicht von {source} ab - Aenderungen in beiden Apps gleich machen")


SHORTCUT_TEXT = re.compile(r"\b(?:Ctrl|Strg|Cmd|Control)\s*(?:[+/]|-?Klick|-?click|-?clic)", re.IGNORECASE)


def check_shortcut_texts() -> None:
    """Tastenkürzel nie fest als «Ctrl+K»/«Strg+Z» in Texten: auf Apple-Geräten heisst die Taste ⌘.
    Texte nehmen {shortcut}/{modifier} entgegen, die Komponenten füllen sie mit useShortcutLabel
    bzw. useModifierLabel (lib/search/shortcuts.ts, DESIGN.md Abschnitt 9)."""
    import json

    def walk(node: object, path: str, file: Path) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key, file)
        elif isinstance(node, str) and SHORTCUT_TEXT.search(node):
            violations.append(f"{rel(file)}: [kuerzel] «{path}» schreibt die Steuerungstaste fest - {{shortcut}} mit useShortcutLabel nutzen")

    for app in ("frontend", "abgabebox-frontend"):
        for file in sorted((ROOT / app / "messages").glob("*/*.json")):
            walk(json.loads(file.read_text()), "", file)


BUTTON_VARIANT = re.compile(r"\.button-(?:primary|secondary|danger|ghost)(?![\w-])")
# Grundregeln der Varianten (nur in globals.css): Selektor besteht allein aus Button-Klassen
BASE_BUTTON_SELECTOR = re.compile(r"^(?:a|button)?(?:\.button-[a-z-]+)+(?::[a-z-]+(?:\([^)]*\))?)*$|^:is\(\.button-")
HEIGHT_PROPS = re.compile(r"(?:^|;)\s*(min-height|height|padding|padding-top|padding-bottom|padding-block)\s*:", re.IGNORECASE)
BACKGROUND_PROP = re.compile(r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)", re.IGNORECASE)


def _css_rules(text: str):
    """(Selektor, Deklarationen, Zeile) aller innersten Regeln - einfacher Parser, genügt für
    unser CSS (keine Strings mit Klammern)."""
    # Kommentare entfernen, Zeilenumbrüche (Zeilennummern) und design-ok-Markierungen behalten
    text = re.sub(r"/\*.*?\*/", lambda m: ("design-ok" if "design-ok" in m.group(0) else "") + "\n" * m.group(0).count("\n"), text, flags=re.S)
    stack: list[tuple[str, int, int]] = []
    start = 0
    for index, char in enumerate(text):
        if char == "{":
            stack.append((text[start:index].strip(), index, text.count("\n", 0, index) + 1))
            start = index + 1
        elif char == "}":
            if stack:
                selector, open_index, line = stack.pop()
                body = text[open_index + 1:index]
                if "{" not in body:
                    yield selector.split(";")[-1].strip(), body, line
            start = index + 1
        elif char == ";" and not stack:
            start = index + 1


def _split_selectors(selector: str) -> list[str]:
    """Selektorliste an Kommas auf oberster Ebene trennen (nicht innerhalb von :is(...))."""
    parts, depth, current = [], 0, ""
    for char in selector:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    return parts + [current]


CLASSNAME_LITERAL = re.compile(r"""className=(?:"([^"]*)"|\{`([^`]*)`\}|\{"([^"]*)"\})""")
ICON_OR_PILL = re.compile(r"(?<![\w-])button-(?:icon|icon-soft|icon-soft-sm|pill)(?![\w-])")
TEXT_VARIANT = re.compile(r"(?<![\w-])button-(?:primary|secondary|danger|ghost)(?![\w-])")


def _button_companions() -> set[str]:
    """Klassen, die im TSX zusammen mit einer Text-Button-Variante vergeben werden
    (z. B. ``button-primary participant-header-button``). Setzt eine solche Begleitklasse Höhe
    oder vertikales Padding, ist der Button so ungleich hoch wie mit einer Varianten-Regel."""
    companions: set[str] = set()
    for base, globs in TSX_GLOBS:
        for glob in globs:
            for path in base.glob(glob):
                if ".test." in path.name:
                    continue
                for match in CLASSNAME_LITERAL.finditer(path.read_text()):
                    value = next(group for group in match.groups() if group is not None)
                    if not TEXT_VARIANT.search(value) or ICON_OR_PILL.search(value):
                        continue
                    companions.update(
                        token for token in re.split(r"[\s{}$?:\"'`()]+", value)
                        if re.fullmatch(r"[a-z][a-z0-9-]+", token) and not token.startswith("button-")
                    )
    return companions


def _vertical_padding(body: str) -> bool:
    """Höhe oder vertikales Padding gesetzt (``padding: 0 x`` bzw. ``padding-inline`` sind ok)."""
    for match in re.finditer(r"(?:^|;)\s*(min-height|height|padding|padding-top|padding-bottom|padding-block)\s*:\s*([^;]+)", body, re.IGNORECASE):
        prop, value = match.group(1).lower(), match.group(2).strip()
        if prop == "padding" and value.split()[0] in ("0", "0px"):
            continue
        return True
    return False


def check_button_variants() -> None:
    """Button-Varianten bleiben überall gleich (DESIGN.md 7):
    - [button-hoehe] Bereichs-CSS setzt keine Höhe/kein vertikales Padding einer Variante - sonst
      sind Buttons nebeneinander verschieden hoch (Token --button-height).
    - [button-hintergrund] Wer den Hintergrund einer Variante ändert, setzt --button-bg (und
      --button-hover-bg), nicht ``background`` direkt - sonst springt er beim Überfahren auf
      die Grundfarbe zurück.
    Bewusste Ausnahmen mit ``design-ok`` und Begründung in der Regel."""
    for path in CSS_FILES:
        for selector, body, line in _css_rules(path.read_text()):
            if not BUTTON_VARIANT.search(selector) or "design-ok" in body or "design-ok" in selector:
                continue
            selectors = [part.strip() for part in _split_selectors(selector)]
            if path.name == "globals.css" and path.parent.name == "app" and all(BASE_BUTTON_SELECTOR.match(part) for part in selectors):
                continue
            if HEIGHT_PROPS.search(body):
                report(path, line, "button-hoehe", f"«{selector[:80]}» ändert Höhe/Padding einer Button-Variante - Buttons nebeneinander wären verschieden hoch (--button-height)")
            background = BACKGROUND_PROP.search(body)
            if background and "--button-bg" not in body and not background.group(1).strip().startswith("var(--button-"):
                report(path, line, "button-hintergrund", f"«{selector[:80]}» setzt background direkt - --button-bg/--button-hover-bg setzen")
    # Begleitklassen (im TSX neben einer Variante): gleiche Höhenregel, sonst rutscht ein Button
    # über eine Feature-Klasse aus --button-height (so «CSV-Import» 42 px neben 40 px).
    companions = _button_companions()
    for path in CSS_FILES:
        for selector, body, line in _css_rules(path.read_text()):
            if BUTTON_VARIANT.search(selector) or "design-ok" in body or "design-ok" in selector:
                continue
            for part in _split_selectors(selector):
                last = re.split(r"[\s>+~]+", part.strip())[-1]
                classes = set(re.findall(r"\.([a-z][a-z0-9-]*)", last.split(":")[0]))
                hit = sorted(classes & companions)
                if hit and _vertical_padding(body):
                    report(path, line, "button-hoehe", f"«{part.strip()[:80]}» ändert Höhe/Padding von «.{hit[0]}», die im TSX neben einer Button-Variante steht (--button-height)")
                    break


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

    check_shared_copies()
    if not targets or any(path.suffix == ".css" for path in targets):
        check_button_variants()
    if not targets:
        check_shortcut_texts()
        # Bereichs-CSS: nur im Gesamtlauf, die Prüfung braucht den ganzen Importgraphen.
        scopes = subprocess.run([sys.executable, str(ROOT / "scripts/check-css-scopes.py")], capture_output=True, text=True)
        if scopes.returncode != 0:
            violations.extend(scopes.stdout.strip().splitlines())
    if violations:
        print("\n".join(violations))
        print(f"\n{len(violations)} Design-Regelverstoesse - siehe design/DESIGN.md")
        return 1
    print("Design-Regeln: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
