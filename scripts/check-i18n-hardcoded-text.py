#!/usr/bin/env python3
"""Heuristischer Schutz gegen neue hart codierte, benutzersichtbare Texte in TSX-Komponenten.

    python3 scripts/check-i18n-hardcoded-text.py            # alles pruefen (CI, vor jedem Commit)
    python3 scripts/check-i18n-hardcoded-text.py <dateien>  # nur diese Dateien

Erkennt (regex-basiert, keine echte JSX-AST-Analyse - analog zu check-design-rules.py):
  - Literaler JSX-Text zwischen Tags: `<span>Benutzer löschen</span>`
  - Literale Werte fuer die ueblichen benutzersichtbaren Attribute: title=, aria-label=,
    placeholder=, alt=, description=, nullLabel=, emptySelectionLabel=, emptyMessage=,
    confirmLabel=, cancelLabel=

Bekannte Grenze (bewusst nicht behoben): JSX-Text, der sich über mehrere Zeilen erstreckt
(z.B. ein längerer Absatz in einem <p>), wird nicht erkannt, weil jede Zeile isoliert geprüft
wird - ein Versuch, das zeilenübergreifend zu matchen, erzeugte hunderte Falsch-Positive durch
TS-Generics (`useState<T>(...)`, `Record<K, V>` über mehrere Zeilen). Solche Stellen nur per
gezieltem Review/grep finden, nicht über diesen Check.

Ausnahmen (um False Positives auf technischen Strings klein zu halten):
  - Text ohne mindestens zwei aufeinanderfolgende Buchstaben (Symbole, Zahlen, "...", "→")
  - Reine Grossbuchstaben-Tokens ohne Leerzeichen (PDF, CSV, ID, URL, MFA, TOTP, SSO, ...)
  - Zeilen mit `i18n-ok`-Kommentar (gleiche Konvention wie `design-ok`), mit kurzer Begruendung
  - Dateien in ALLOWED_FILES (Tests, Storybook-aehnliche Mocks, rein technische Konstanten)
  - JSX-Ausdruecke `{...}` (t()-Aufrufe, Variablen) werden nicht als Literal gewertet
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TSX_GLOBS = [
    (ROOT / "frontend", ["components/**/*.tsx", "app/**/*.tsx"]),
    (ROOT / "abgabebox-frontend", ["components/**/*.tsx", "app/**/*.tsx"]),
]

# Dateien mit bewusst keinem/kaum UI-Text (reine Icon-/Wrapper-Komponenten) oder deren Strings
# technischer Natur sind (IDs, CSS-Klassen als Props, Testdaten) - neue Ausnahmen nur, wenn
# wirklich kein Translation Key passt, mit kurzer Begruendung in diesem Kommentar.
ALLOWED_FILES: set[str] = {
    # Icon-Sets: ausschliesslich SVG-Pfaddaten und Icon-Key-Literale ("dashboard", "tenants",
    # ...), keine einzige UI-Text-Stelle.
    "frontend/components/ui/nav-icons.tsx",
    "frontend/components/ui/action-icons.tsx",
}

ATTR_PATTERN = re.compile(
    r'\b(title|aria-label|placeholder|alt|description|nullLabel|emptySelectionLabel|emptyMessage|confirmLabel|cancelLabel)="([^"]+)"'
)
# (?<!=) schliesst `=>` aus (Arrow-Function-Pfeil, kein JSX-Tag-Ende) - sonst liest z.B.
# `() => void | Promise<void>;` den Text zwischen dem Pfeil und dem naechsten Generic-`<` als
# JSX-Text. Reine TS-Typzeilen ausserhalb von JSX koennen trotzdem vereinzelt durchrutschen
# (keine echte AST-Analyse, siehe Modulkommentar) - der `i18n-ok`-Kommentar deckt den Rest ab.
TEXT_PATTERN = re.compile(r"(?<!=)>([^<>{}\n]+)<")
LETTERS_RUN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}")
ALL_CAPS_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9/._-]*$")
# Produkt-/Markennamen werden nie uebersetzt (wie Eigennamen in jeder Sprache) - exaktes Match,
# damit ein Satz, der zufaellig "hocX" enthaelt, trotzdem noch als Fund auffaellt.
BRAND_TERMS = {"hocX", "hX", "Abgabebox"}

violations: list[str] = []


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def looks_like_user_text(candidate: str) -> bool:
    text = candidate.strip()
    if not text:
        return False
    if text in BRAND_TERMS:
        return False
    if not LETTERS_RUN.search(text):
        return False  # keine zwei Buchstaben hintereinander -> Symbol/Zahl/Trenner
    if ALL_CAPS_TOKEN.match(text) and " " not in text:
        return False  # z.B. PDF, CSV, SSO, TOTP, MFA, URL, ID
    if text.startswith("http://") or text.startswith("https://") or text.startswith("/"):
        return False  # URL/Pfad
    if re.fullmatch(r"[\d.,:%+\-–—()\[\]/ ]+", text):
        return False  # reine Zahlen-/Interpunktionsfolge
    return True


def check_file(path: Path) -> None:
    r = rel(path)
    if r in ALLOWED_FILES:
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    for no, line in enumerate(lines, start=1):
        if "i18n-ok" in line:
            continue
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue

        for match in ATTR_PATTERN.finditer(line):
            attr, value = match.group(1), match.group(2)
            if looks_like_user_text(value):
                violations.append(f'{r}:{no}: [hardcoded-text] {attr}="{value}" - Translation Key statt Literal verwenden')

        for match in TEXT_PATTERN.finditer(line):
            candidate = match.group(1)
            if looks_like_user_text(candidate):
                violations.append(f"{r}:{no}: [hardcoded-text] JSX-Text \"{candidate.strip()}\" - Translation Key statt Literal verwenden")


def collect_files(explicit: list[str]) -> list[Path]:
    if explicit:
        return [Path(p).resolve() for p in explicit if p.endswith(".tsx")]
    files: list[Path] = []
    for base, globs in TSX_GLOBS:
        for g in globs:
            for f in base.glob(g):
                if f.name.endswith(".test.tsx"):
                    continue
                files.append(f)
    return files


def main() -> int:
    for f in collect_files(sys.argv[1:]):
        if f.exists():
            check_file(f)

    if violations:
        print(f"Hardcoded-UI-Text-Check: {len(violations)} moegliche Fund(e)\n", file=sys.stderr)
        for v in violations:
            print(v, file=sys.stderr)
        print(
            "\nFalls einer dieser Funde kein benutzersichtbarer Text ist (z.B. eine technische "
            "Konstante), die Zeile mit einem `// i18n-ok: <kurze Begruendung>`-Kommentar markieren "
            "oder die Datei in ALLOWED_FILES (scripts/check-i18n-hardcoded-text.py) ergaenzen.",
            file=sys.stderr,
        )
        return 1

    print("Hardcoded-UI-Text-Check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
