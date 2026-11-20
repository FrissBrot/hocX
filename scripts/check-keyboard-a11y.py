#!/usr/bin/env python3
"""Prüft das Frontend auf Tastatur-Barrierefreiheit (design/KEYBOARD_ACCESSIBILITY.md).

    python3 scripts/check-keyboard-a11y.py                 # alles prüfen (CI, Pre-Commit)
    python3 scripts/check-keyboard-a11y.py <dateien>       # nur diese Dateien
    python3 scripts/check-keyboard-a11y.py --list          # alle Funde inkl. Altbestand zeigen
    python3 scripts/check-keyboard-a11y.py --update-baseline  # Altbestand neu einfrieren (nur bei Abbau!)

Statt Regex über ganze Zeilen liest ein kleiner JSX-Scanner die öffnenden Tags (Name, Attribute,
geschachtelte {…}-Ausdrücke, Strings, Template-Literale, Kommentare) - so fallen mehrzeilige
Tags, Attribute in beliebiger Reihenfolge und `>` in Ausdrücken nicht durch. ESLint/jsx-a11y ist
im Projekt nicht installiert; ein eigener, abhängigkeitsfreier Scanner hält die Prüfung schnell
und in Pre-Commit/CI ohne Node lauffähig.

Regeln (Kürzel in Klammern, Ausnahme mit `a11y-ok: <Begründung>` in derselben Zeile bzw. bei
mehrzeiligen Tags in einer Zeile des öffnenden Tags):
  clickable-no-keyboard   div/span/li/… mit onClick ohne role + tabIndex + onKeyDown
                          (besser: <button>; reine Weiterleitungen wie stopPropagation zählen nicht)
  pointer-only-activation <button>/<a>/role=button mit onPointerDown/onMouseDown als einziger
                          Aktion - Enter/Leertaste lösen dann nichts aus
  role-without-keyboard   role="button|link|tab|menuitem|checkbox|switch|option" auf einem
                          nicht-nativen Element ohne tabIndex (nicht erreichbar) bzw. ohne
                          onKeyDown (nicht auslösbar)
  positive-tabindex       tabIndex > 0 (zerstört die Tab-Reihenfolge)
  global-key-listener     addEventListener("keydown"/"keyup") ausserhalb der zentralen Module -
                          Shortcuts gehören in lib/keyboard/registry.ts + useShortcut
  alt-letter-by-key       Alt + Buchstabe über event.key geprüft (macOS-Option verändert das
                          Zeichen) - Registry/matchesCombo nutzen (event.code)
  outline-none            CSS: `outline: none|0` in einer :focus-Regel ohne Ersatz
                          (box-shadow/border/outline/background in derselben Regel)

Klickbare Tabellenzeilen sind erlaubt, wenn dieselbe Aktion als Knopf/Link in der Zeile steht
(Muster `button.table-row-link`); die Zeile bekommt dann `a11y-ok: … table-row-link …`.

Altbestand: `scripts/keyboard-a11y-baseline.json` friert bestehende Funde pro Datei und Regel als
Anzahl ein (wie bundle-budget). Neue Funde schlagen fehl; weniger Funde als eingefroren meldet
der Check als Hinweis - dann `--update-baseline` laufen lassen, damit der Abbau nicht wieder
zurückwachsen kann. Die Baseline wird nie erhöht, um einen neuen Fund durchzulassen.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts/keyboard-a11y-baseline.json"
TSX_ROOTS = [
    (ROOT / "frontend", ["components/**/*.tsx", "app/**/*.tsx", "lib/**/*.tsx", "lib/**/*.ts", "contexts/**/*.tsx"]),
    (ROOT / "abgabebox-frontend", ["components/**/*.tsx", "app/**/*.tsx", "lib/**/*.ts"]),
]
CSS_FILES = [
    ROOT / "frontend/app/globals.css",
    *sorted((ROOT / "frontend/app/styles").glob("*.css")),
    ROOT / "abgabebox-frontend/app/globals.css",
]
SKIP_PARTS = ("node_modules/", ".next/", "/e2e/")
SKIP_SUFFIXES = (".test.ts", ".test.tsx", ".spec.ts")

# Zentrale Module, die globale Tastatur-Listener besitzen dürfen
KEY_LISTENER_HOMES = {
    "frontend/lib/keyboard/use-shortcut.ts",
    "frontend/lib/hooks/use-popup-escape.ts",
    "frontend/lib/a11y/use-focus-trap.ts",
}

NON_INTERACTIVE = {
    "div", "span", "li", "ul", "ol", "tr", "td", "th", "img", "p", "section", "article", "header",
    "footer", "aside", "main", "nav", "figure", "figcaption", "label", "strong", "em", "small",
    "h1", "h2", "h3", "h4", "h5", "h6", "svg", "path", "i", "b", "dl", "dt", "dd", "table", "tbody",
}
NATIVE_INTERACTIVE = {"button", "a", "input", "select", "textarea", "summary", "option"}
INTERACTIVE_ROLES = {"button", "link", "tab", "menuitem", "menuitemradio", "menuitemcheckbox", "checkbox", "switch", "radio", "option", "treeitem", "slider", "spinbutton", "combobox", "textbox", "gridcell", "row"}
KEYBOARD_ROLES = {"button", "link", "tab", "menuitem", "menuitemradio", "menuitemcheckbox", "checkbox", "switch"}
# Elemente, deren onClick nur Ereignisse weiterreicht/abfängt (keine eigene Aktion)
PASSIVE_CLICK = re.compile(r"^\{\s*\(?\s*(?:e|event|ev)?\s*\)?\s*=>\s*\{?\s*(?:e|event|ev)\.stopPropagation\(\)\s*;?\s*\}?\s*\}$")

RULE_TEXT = {
    "clickable-no-keyboard": "klickbares Element ohne Tastaturbedienung (nimm <button>, sonst role + tabIndex + onKeyDown)",
    "pointer-only-activation": "Aktion nur auf onPointerDown/onMouseDown - Enter/Leertaste lösen nichts aus (onClick nutzen, Fokus mit onMouseDown preventDefault halten)",
    "role-without-keyboard": "interaktive Rolle ohne tabIndex bzw. onKeyDown",
    "positive-tabindex": "tabIndex > 0 zerstört die Tab-Reihenfolge",
    "global-key-listener": "globaler keydown/keyup-Listener - Shortcut in lib/keyboard/registry.ts eintragen und useShortcut nutzen",
    "alt-letter-by-key": "Alt + Buchstabe per event.key (macOS-Option ändert das Zeichen) - matchesCombo/useShortcut nutzen",
    "outline-none": ":focus-Regel mit outline: none ohne sichtbaren Ersatz (box-shadow/border/background)",
}

MARKER = "a11y-ok"


@dataclass
class Tag:
    name: str
    line: int
    end_line: int = 0
    attrs: dict[str, str | None] = field(default_factory=dict)
    spread: bool = False


class JsxScanner:
    """Findet öffnende JSX-Tags in TS/TSX-Quelltext.

    Zustände: Code (mit Strings, Template-Literalen, Kommentaren, Regex-Literalen) und JSX-Kinder
    (Text bis `<` oder `{`). Ein `<` gilt im Code als JSX-Anfang, wenn davor kein Bezeichner/
    keine Klammer zu steht (Abgrenzung zu Generics und Vergleichen).
    """

    JSX_PREV = set("(,=:?&|!{}[;>") | {""}
    KEYWORDS_BEFORE_JSX = ("return", "default", "yield", "await", "case", "else", "do")

    def __init__(self, text: str):
        self.text = text
        self.n = len(text)
        self.tags: list[Tag] = []

    def line_of(self, index: int) -> int:
        return self.text.count("\n", 0, index) + 1

    def scan(self) -> list[Tag]:
        try:
            self._code(0, None)
        except (IndexError, RecursionError):
            pass  # Unvollständige Datei: was bis hier gefunden wurde, zählt
        return self.tags

    # ── Code ──
    def _prev_significant(self, index: int) -> str:
        j = index - 1
        while j >= 0 and self.text[j] in " \t\r\n":
            j -= 1
        if j < 0:
            return ""
        end = j + 1
        if self.text[j].isalnum() or self.text[j] in "_$":
            start = j
            while start > 0 and (self.text[start - 1].isalnum() or self.text[start - 1] in "_$"):
                start -= 1
            word = self.text[start:end]
            return "kw" if word in self.KEYWORDS_BEFORE_JSX else "ident"
        return self.text[j]

    def _skip_string(self, i: int, quote: str) -> int:
        i += 1
        while i < self.n and self.text[i] != quote:
            if self.text[i] == "\\":
                i += 1
            elif self.text[i] == "\n" and quote != "`":
                return i
            i += 1
        return i + 1

    def _skip_template(self, i: int) -> int:
        i += 1
        while i < self.n:
            ch = self.text[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                return i + 1
            if ch == "$" and i + 1 < self.n and self.text[i + 1] == "{":
                i = self._code(i + 2, "}")
                continue
            i += 1
        return i

    def _skip_regex(self, i: int) -> int:
        i += 1
        in_class = False
        while i < self.n and self.text[i] != "\n":
            ch = self.text[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                i += 1
                while i < self.n and self.text[i].isalpha():
                    i += 1
                return i
            i += 1
        return i

    def _code(self, i: int, until: str | None) -> int:
        depth = 0
        while i < self.n:
            ch = self.text[i]
            nxt = self.text[i + 1] if i + 1 < self.n else ""
            if ch == "/" and nxt == "/":
                end = self.text.find("\n", i)
                i = self.n if end < 0 else end
                continue
            if ch == "/" and nxt == "*":
                end = self.text.find("*/", i + 2)
                i = self.n if end < 0 else end + 2
                continue
            if ch in "\"'":
                i = self._skip_string(i, ch)
                continue
            if ch == "`":
                i = self._skip_template(i)
                continue
            if ch == "/":
                prev = self._prev_significant(i)
                if prev in self.JSX_PREV or prev == "kw":
                    i = self._skip_regex(i)
                    continue
            if ch == "<" and (nxt.isalpha() or nxt == ">"):
                prev = self._prev_significant(i)
                if prev in self.JSX_PREV or prev == "kw":
                    i = self._element(i)
                    continue
            if ch in "{([":
                depth += 1
            elif ch in "})]":
                if depth == 0 and until == ch:
                    return i + 1
                depth -= 1
            i += 1
        return i

    # ── JSX ──
    def _element(self, i: int) -> int:
        start = i
        i += 1
        if self.text[i] == ">":  # Fragment
            return self._children(i + 1)
        m = re.match(r"[A-Za-z][\w.:-]*", self.text[i:])
        if not m:
            return i
        tag = Tag(m.group(0), self.line_of(start))
        i += m.end()
        # Generische Typargumente <Foo<Bar>> kommen in JSX nicht vor; Attribute lesen
        while i < self.n:
            ch = self.text[i]
            if ch in " \t\r\n":
                i += 1
                continue
            if ch == "/" and self.text.startswith("/>", i):
                tag.end_line = self.line_of(i)
                self.tags.append(tag)
                return i + 2
            if ch == ">":
                tag.end_line = self.line_of(i)
                self.tags.append(tag)
                return self._children(i + 1, tag.name)
            if ch == "{":
                end = self._code(i + 1, "}")
                if self.text[i + 1 : end].lstrip().startswith("..."):
                    tag.spread = True
                elif self.text.startswith("/*", i + 1):
                    pass
                i = end
                continue
            am = re.match(r"[\w:-]+", self.text[i:])
            if not am:
                i += 1
                continue
            name = am.group(0)
            i += am.end()
            j = i
            while j < self.n and self.text[j] in " \t\r\n":
                j += 1
            if j < self.n and self.text[j] == "=":
                j += 1
                while self.text[j] in " \t\r\n":
                    j += 1
                if self.text[j] in "\"'":
                    end = self._skip_string(j, self.text[j])
                    tag.attrs[name] = self.text[j:end]
                    i = end
                elif self.text[j] == "{":
                    end = self._code(j + 1, "}")
                    tag.attrs[name] = self.text[j:end]
                    i = end
                elif self.text[j] == "<":
                    i = self._element(j)
                    tag.attrs[name] = "<jsx>"
                else:
                    i = j
            else:
                tag.attrs[name] = None
        return i

    def _children(self, i: int, name: str | None = None) -> int:
        while i < self.n:
            ch = self.text[i]
            if ch == "{":
                i = self._code(i + 1, "}")
                continue
            if ch == "<":
                if self.text.startswith("</", i):
                    end = self.text.find(">", i)
                    return self.n if end < 0 else end + 1
                nxt = self.text[i + 1] if i + 1 < self.n else ""
                if nxt.isalpha() or nxt == ">":
                    i = self._element(i)
                    continue
            i += 1
        return i


def attr_value(tag: Tag, name: str) -> str | None:
    value = tag.attrs.get(name)
    if value is None:
        return None
    value = value.strip()
    if value[:1] in "\"'":
        return value[1:-1]
    if value.startswith("{") and value.endswith("}"):
        inner = value[1:-1].strip()
        string = re.fullmatch(r"[\"'`]([^\"'`]*)[\"'`]", inner)
        return string.group(1) if string else inner
    return value


def check_tag(tag: Tag) -> list[str]:
    found: list[str] = []
    name = tag.name
    lower = name.lower()
    is_html = name[:1].islower()
    attrs = tag.attrs
    role = attr_value(tag, "role") if "role" in attrs else None
    has = lambda key: key in attrs  # noqa: E731

    tab_index = attr_value(tag, "tabIndex")
    if tab_index is not None and re.fullmatch(r"[1-9]\d*", tab_index.strip()):
        found.append("positive-tabindex")

    if not is_html:
        return found

    activation = has("onClick") or has("onKeyDown") or has("onKeyUp")
    pointer_only = (has("onPointerDown") or has("onMouseDown") or has("onPointerUp") or has("onMouseUp")) and not activation
    if pointer_only and (lower in {"button", "a"} or role in KEYBOARD_ROLES):
        pointer_handlers = [attrs.get(key) or "" for key in ("onPointerDown", "onMouseDown", "onPointerUp", "onMouseUp") if key in attrs]
        # Nur Fokus halten (preventDefault) ist keine Aktion
        if not all(re.fullmatch(r"\{\s*\(?\s*\w*\s*\)?\s*=>\s*\w+\.preventDefault\(\)\s*\}|\{\s*\w+\s*\}", handler.strip()) for handler in pointer_handlers):
            found.append("pointer-only-activation")

    if lower in NATIVE_INTERACTIVE:
        return found

    if role in {"presentation", "none"} or attr_value(tag, "aria-hidden") == "true":
        return found

    if role in KEYBOARD_ROLES:
        if not has("tabIndex") and not tag.spread:
            found.append("role-without-keyboard")
        elif has("onClick") and not (has("onKeyDown") or has("onKeyUp")) and not tag.spread:
            found.append("role-without-keyboard")
        return found

    if lower in NON_INTERACTIVE and has("onClick") and role not in INTERACTIVE_ROLES:
        # Fokussierbar und per Taste auslösbar (z. B. Tabellenzeile mit tabIndex + onKeyDown) gilt als bedienbar
        if has("tabIndex") and (has("onKeyDown") or has("onKeyUp")) and attr_value(tag, "tabIndex") != "-1":
            return found
        if not PASSIVE_CLICK.match((attrs.get("onClick") or "").strip()):
            found.append("clickable-no-keyboard")
    return found


ALT_LETTER = re.compile(r"\.key\s*===?\s*[\"'][A-Za-z][\"']")
KEY_LISTENER = re.compile(r"addEventListener\(\s*[\"']key(?:down|up)[\"']")


def check_source(rel: str, text: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    lines = text.splitlines()

    def marked(line: int, end: int = 0) -> bool:
        return any(0 < number <= len(lines) and MARKER in lines[number - 1] for number in range(line, max(line, end) + 1))

    if rel.endswith(".tsx"):
        for tag in JsxScanner(text).scan():
            for rule in check_tag(tag):
                if not marked(tag.line, tag.end_line):
                    findings.append((rule, tag.line, f"<{tag.name}>"))
    for number, line in enumerate(lines, 1):
        if MARKER in line:
            continue
        if KEY_LISTENER.search(line) and rel not in KEY_LISTENER_HOMES:
            findings.append(("global-key-listener", number, line.strip()[:80]))
        if "altKey" in line and ALT_LETTER.search(line) and "!event.altKey" not in line and "!e.altKey" not in line:
            findings.append(("alt-letter-by-key", number, line.strip()[:80]))
    return findings


CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)


def check_css(rel: str, text: str) -> list[tuple[str, int, str]]:
    findings = []
    stripped = re.sub(r"/\*(?!\s*a11y-ok).*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    for match in CSS_RULE.finditer(stripped):
        selector, body = match.group(1), match.group(2)
        if ":focus" not in selector.replace(":focus-within", ""):
            continue
        if not re.search(r"outline\s*:\s*(none|0)\b", body):
            continue
        if MARKER in body or MARKER in selector:
            continue
        replacement = re.search(r"box-shadow\s*:\s*(?!none)[^;]+|border(-[a-z]+)?-color\s*:|border\s*:\s*(?!none)|outline\s*:\s*(?!none|0)\S|background(-color)?\s*:|text-decoration\s*:", body)
        if replacement:
            continue
        line = text.count("\n", 0, match.start(2)) + 1
        findings.append(("outline-none", line, " ".join(selector.split())[:80]))
    return findings


def iter_files(paths: list[str]) -> list[Path]:
    if paths:
        return [ROOT / p if not Path(p).is_absolute() else Path(p) for p in paths]
    files: list[Path] = []
    for base, globs in TSX_ROOTS:
        for pattern in globs:
            files.extend(base.glob(pattern))
    files.extend(CSS_FILES)
    return sorted(set(files))


def relevant(rel: str) -> bool:
    if not rel.startswith(("frontend/", "abgabebox-frontend/")):
        return False
    if any(part in rel for part in SKIP_PARTS) or rel.endswith(SKIP_SUFFIXES):
        return False
    return rel.endswith((".tsx", ".ts", ".css"))


def collect(paths: list[str]) -> dict[str, list[tuple[str, int, str]]]:
    result: dict[str, list[tuple[str, int, str]]] = {}
    for path in iter_files(paths):
        if not path.exists():
            continue
        rel = path.resolve().relative_to(ROOT).as_posix()
        if not relevant(rel):
            continue
        text = path.read_text(encoding="utf-8")
        findings = check_css(rel, text) if rel.endswith(".css") else check_source(rel, text)
        if findings:
            result[rel] = findings
    return result


def load_baseline() -> dict[str, dict[str, int]]:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text(encoding="utf-8")).get("files", {})


def write_baseline(findings: dict[str, list[tuple[str, int, str]]]) -> None:
    files = {rel: dict(sorted(Counter(rule for rule, _, _ in items).items())) for rel, items in sorted(findings.items())}
    payload = {
        "_comment": "Eingefrorener Altbestand von scripts/check-keyboard-a11y.py (Anzahl pro Datei und Regel). Nur verkleinern, nie erhöhen - siehe KEYBOARD_AUDIT.md.",
        "files": files,
    }
    BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--list", action="store_true", help="alle Funde inkl. Altbestand ausgeben")
    parser.add_argument("--update-baseline", action="store_true", help="Altbestand neu einfrieren")
    args = parser.parse_args()

    findings = collect(args.paths)
    if args.update_baseline:
        if args.paths:
            print("--update-baseline nur ohne Dateiliste (ganzes Repo)", file=sys.stderr)
            return 2
        old = load_baseline()
        grew = [
            f"{rel} {rule}: {count} > {old.get(rel, {}).get(rule, 0)}"
            for rel, items in findings.items()
            for rule, count in Counter(rule for rule, _, _ in items).items()
            if old and count > old.get(rel, {}).get(rule, 0)
        ]
        if grew:
            print("Baseline würde wachsen - neue Funde zuerst beheben:\n  " + "\n  ".join(grew), file=sys.stderr)
            return 1
        write_baseline(findings)
        print(f"Baseline aktualisiert: {sum(len(v) for v in findings.values())} Funde in {len(findings)} Dateien")
        return 0

    baseline = load_baseline()
    errors: list[str] = []
    shrunk: list[str] = []
    for rel, items in sorted(findings.items()):
        counts = Counter(rule for rule, _, _ in items)
        for rule, count in counts.items():
            allowed = baseline.get(rel, {}).get(rule, 0)
            if count > allowed or args.list:
                label = "neu" if count > allowed else "Altbestand"
                for found_rule, line, detail in items:
                    if found_rule == rule:
                        errors.append(f"{rel}:{line}: [{rule}] {RULE_TEXT[rule]} ({detail}) - {label}, {count} Fund(e), eingefroren {allowed}")
    for rel, rules in baseline.items():
        for rule, allowed in rules.items():
            current = Counter(r for r, _, _ in findings.get(rel, [])).get(rule, 0)
            if current < allowed and (not args.paths or any(rel in p or p.endswith(rel) for p in args.paths)):
                shrunk.append(f"{rel} [{rule}]: {current} statt {allowed}")

    if args.list:
        print("\n".join(errors) or "keine Funde")
        return 0
    if shrunk:
        print("Hinweis: weniger Altbestand als eingefroren - bitte `python3 scripts/check-keyboard-a11y.py --update-baseline`:\n  " + "\n  ".join(shrunk))
    if errors:
        print("Tastatur-Regeln verletzt (design/KEYBOARD_ACCESSIBILITY.md):\n" + "\n".join(errors), file=sys.stderr)
        print("\nBehebung bevorzugt; bewusste Ausnahme nur mit `a11y-ok: <Begründung>` in derselben Zeile.", file=sys.stderr)
        return 1
    print("Tastatur-Regeln: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
