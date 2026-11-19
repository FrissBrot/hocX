#!/usr/bin/env python3
"""Heuristischer Schutz gegen neue hart codierte, benutzersichtbare Texte in TSX-Komponenten.

    python3 scripts/check-i18n-hardcoded-text.py            # alles pruefen (CI, vor jedem Commit)
    python3 scripts/check-i18n-hardcoded-text.py <dateien>  # nur diese Dateien

Erkennt (regex-basiert, keine echte JSX-AST-Analyse - analog zu check-design-rules.py):
  - Literaler JSX-Text zwischen Tags: `<span>Benutzer löschen</span>`
  - Literale Werte fuer die ueblichen benutzersichtbaren Attribute: title=, aria-label=,
    placeholder=, alt=, description=, nullLabel=, emptySelectionLabel=, emptyMessage=,
    confirmLabel=, cancelLabel=

  - String-Literale als erstes Argument von Meldungs-Aufrufen - showToast(, setError(,
    setSaveError(, new Error(, new ApiError( - in .tsx UND .ts (auch lib/, contexts/,
    hooks/). Solche Texte landen ueber error.message bzw. als Toast unuebersetzt in der UI
    (Audit MAIN-FE-010). Technische Entwicklerfehler (z. B. "useToast must be used inside
    ToastProvider") mit `// i18n-ok: <Grund>` markieren.

  - JSX-Text neben einem Ausdruck in derselben Zeile: `{size} MB · zum Ersetzen klicken`,
    `<span>Das Feld {name}`, `{count} Hinweis{suffix} zur Analyse`, `<> {n} Einträge wurden …</>`
    (Nachtlauf 2026-11-19, Funde 4/5). Weil hier keine Tag-Klammer den JSX-Kontext belegt, muss
    der Text zusätzlich wie Prosa aussehen (beginnt mit einem Buchstaben, keine Code-Zeichen
    `;=|$[]"'` usw., kein Member-Zugriff/Funktionsaufruf, kein TS-Schlüsselwort wie `catch`,
    `finally`, `as`, kein einzelner Bezeichner in camelCase/SNAKE_CASE) - so bleiben
    `} catch (error) {`, `}: Readonly<`, `} as Record<` aussen vor.
  - Template-Literale mit `${…}`, deren feste Teile mindestens zwei freistehende Wörter enthalten:
    `` `${a} Anwesenheiten, ${b} Termine wurden übernommen.` `` - nicht aber Klassenlisten
    (`card card-${tone}`), Keys (`modal.${kind}Title`), Pfade oder CSS (`${x}px solid ${c}`).

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
# Fuer Meldungs-Aufrufe (MESSAGE_CALL_PATTERN) zusaetzlich alle .ts/.tsx ausserhalb von JSX.
MESSAGE_GLOBS = [
    (ROOT / "frontend", ["app/**/*.ts", "app/**/*.tsx", "components/**/*.ts", "components/**/*.tsx",
                         "lib/**/*.ts", "lib/**/*.tsx", "contexts/**/*.ts", "contexts/**/*.tsx"]),
    (ROOT / "abgabebox-frontend", ["app/**/*.ts", "app/**/*.tsx", "components/**/*.ts",
                                   "components/**/*.tsx", "lib/**/*.ts"]),
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
MESSAGE_CALL_PATTERN = re.compile(
    r"""(?:\bshowToast|\bsetError|\bsetSaveError|\bnew\s+Error|\bnew\s+ApiError)\(\s*(["'`])((?:\\.|(?!\1).)*)\1"""
)
TEMPLATE_EXPR = re.compile(r"\$\{[^}]*\}")
# Text neben einem JSX-Ausdruck (siehe Modulkommentar); Kandidaten zusätzlich über looks_like_prose.
EXPR_TEXT_PATTERNS = (
    re.compile(r"\}([^<>{}\n]+)<"),          # {x} Text</span>
    re.compile(r"(?<!=)>([^<>{}\n]+)\{"),       # <span>Text {x}
    re.compile(r"\}([^<>{}\n]+)\{"),         # {a} Text {b}
    re.compile(r"\}([^<>{}\n]+)$"),          # {x} Text (Zeile endet, JSX-Text läuft weiter)
)
TEMPLATE_LITERAL = re.compile(r"`((?:[^`\\\n]|\\.)*\$\{(?:[^`\\\n]|\\.)*)`")
TEMPLATE_SPLIT = re.compile(r"\$\{[^}]*\}")
HTML_ENTITY = re.compile(r"&[a-zA-Z]+;|&#\d+;")
CODE_CHARS = set(';=`|$[]"\'{}<>\\')
TS_KEYWORDS = {
    "as", "satisfies", "extends", "else", "keyof", "typeof", "in", "instanceof", "return", "of", "new",
    "await", "is", "infer", "readonly", "catch", "finally", "try", "do", "while", "if", "for", "switch",
    "case", "default", "function", "const", "let", "var", "type", "interface", "export", "import",
    "from", "throw", "break", "continue",
}
IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*$")
WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}[.,:;!?]?")
CSS_WORDS = {"px", "em", "rem", "vh", "vw", "solid", "dashed", "dotted", "auto", "none", "deg", "ms", "important"}
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


def looks_like_prose(candidate: str) -> bool:
    """Text neben einem `{Ausdruck}`: nur melden, wenn er wie Satztext statt wie TS-Code aussieht."""
    text = HTML_ENTITY.sub(" ", candidate).strip()
    if not text or not text[0].isalpha():
        return False  # `)`, `:`, `.`, `&&`, `=>` … am Anfang -> Code
    if any(ch in CODE_CHARS for ch in text):
        return False
    if text.count("(") != text.count(")"):
        return False
    if re.search(r"[A-Za-z_]\.[A-Za-z_]", text) or re.search(r"\w\(", text):
        return False  # Member-Zugriff (event.date) oder Funktionsaufruf
    if re.split(r"[\s:,]", text, maxsplit=1)[0] in TS_KEYWORDS:
        return False
    if IDENTIFIER.match(text) and ("_" in text or re.search(r"[a-z][A-Z]", text) or text.isupper()):
        return False  # einzelner Bezeichner (bestRank, SESSION_STALE_MS)
    return looks_like_user_text(text)


def template_has_prose(body: str) -> bool:
    """Template-Literal mit `${…}`: mindestens zwei freistehende Wörter in den festen Teilen. Ein
    Wort, das direkt an einem Ausdruck klebt (`modal.${kind}Title`, `card-${tone}`), zählt nicht,
    Klassenlisten/Keys/Pfade (Bindestrich, Punkt, Schrägstrich in einem Token) schliessen aus."""
    parts = TEMPLATE_SPLIT.split(body)
    words = 0
    for index, part in enumerate(parts):
        tokens = part.split()
        if not tokens:
            continue
        for position, token in enumerate(tokens):
            if re.search(r"[-/=_#@]|\.\w", token):
                return False
            glued_left = position == 0 and index > 0 and not part[:1].isspace()
            glued_right = position == len(tokens) - 1 and index < len(parts) - 1 and not part[-1:].isspace()
            if glued_left or glued_right:
                continue
            if WORD.fullmatch(token) and token.rstrip(".,:;!?").lower() not in CSS_WORDS:
                words += 1
    return words >= 2


def line_findings(line: str) -> list[str]:
    """Funde einer TSX-Zeile (ohne Dateiangabe), für check_file und die Tests."""
    if "i18n-ok" in line:
        return []
    stripped = line.strip()
    if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
        return []
    found: list[str] = []
    for match in ATTR_PATTERN.finditer(line):
        attr, value = match.group(1), match.group(2)
        if looks_like_user_text(value):
            found.append(f'{attr}="{value}" - Translation Key statt Literal verwenden')
    seen: set[str] = set()
    for match in TEXT_PATTERN.finditer(line):
        candidate = match.group(1)
        if looks_like_user_text(candidate):
            seen.add(candidate.strip())
            found.append(f"JSX-Text \"{candidate.strip()}\" - Translation Key statt Literal verwenden")
    for pattern in EXPR_TEXT_PATTERNS:
        for match in pattern.finditer(line):
            candidate = match.group(1).strip()
            if candidate not in seen and looks_like_prose(candidate):
                seen.add(candidate)
                found.append(f"JSX-Text neben Ausdruck \"{candidate}\" - Translation Key statt Literal verwenden")
    for match in TEMPLATE_LITERAL.finditer(line):
        if template_has_prose(match.group(1)):
            found.append(f"Template-Literal `{match.group(1).strip()}` - Translation Key mit Parametern verwenden")
    return found


def check_message_calls(path: Path) -> None:
    r = rel(path)
    if r in ALLOWED_FILES:
        return
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if "i18n-ok" in line:
            continue
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        for match in MESSAGE_CALL_PATTERN.finditer(line):
            literal = TEMPLATE_EXPR.sub(" ", match.group(2))
            if looks_like_user_text(literal):
                violations.append(
                    f'{r}:{no}: [hardcoded-text] Meldung "{match.group(2).strip()}" - Translation Key statt Literal verwenden'
                )


def check_file(path: Path) -> None:
    r = rel(path)
    if r in ALLOWED_FILES:
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    for no, line in enumerate(lines, start=1):
        for finding in line_findings(line):
            violations.append(f"{r}:{no}: [hardcoded-text] {finding}")


def collect_message_files(explicit: list[str]) -> list[Path]:
    if explicit:
        return [Path(p).resolve() for p in explicit if p.endswith((".ts", ".tsx")) and not p.endswith((".test.ts", ".test.tsx", ".d.ts"))]
    files: set[Path] = set()
    for base, globs in MESSAGE_GLOBS:
        for g in globs:
            for f in base.glob(g):
                if "node_modules" in f.parts or f.name.endswith((".test.ts", ".test.tsx", ".d.ts")):
                    continue
                files.add(f)
    return sorted(files)


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
    for f in collect_message_files(sys.argv[1:]):
        if f.exists():
            check_message_calls(f)

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
