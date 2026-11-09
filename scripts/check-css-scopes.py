#!/usr/bin/env python3
"""Prueft die Aufteilung des Frontend-CSS nach Bereichen (design/DESIGN.md Abschnitt 10).

frontend/app/styles/<bundle>.css wird nur von den Routen geladen, deren Layout die Datei importiert.
Eine Klasse daraus, die spaeter auch in einer Komponente einer anderen Route verwendet wird, bliebe
dort stillschweigend ohne Stil. Dieses Skript ermittelt ueber den Importgraphen, auf welchen Routen
jede Klasse vorkommen kann, und meldet Regeln, die auf einer Route greifen, die ihr Bundle nicht laedt.

    python3 scripts/check-css-scopes.py

Abhilfe bei einem Fund: Regel nach globals.css oder in ein Bundle verschieben, das die Route laedt,
bzw. das Bundle im Layout der Route importieren.
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
APP = FE / "app"
STYLES = APP / "styles"

IMPORT_RE = re.compile(r"""(?:from\s+|import\s*\(\s*|import\s+|require\(\s*)["']([^"']+)["']""")
CLASS_RE = re.compile(r"\.(-?[A-Za-z_][\w-]*)")
TOKEN_RE = re.compile(r"[A-Za-z_][\w-]*")
SKIP_DIRS = {"node_modules", ".next", "test-results", "coverage", "e2e", "public", "messages"}


def source_files() -> list[Path]:
    out = []
    for base, dirs, names in os.walk(FE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name.endswith((".ts", ".tsx")) and not name.endswith(".d.ts") and not re.search(r"\.(test|spec)\.tsx?$", name):
                out.append(Path(base) / name)
    return out


def resolve(base: Path, spec: str) -> Path | None:
    if spec.startswith("@/"):
        target = FE / spec[2:]
    elif spec.startswith("."):
        target = Path(os.path.normpath(base.parent / spec))
    else:
        return None
    for candidate in (target, Path(f"{target}.ts"), Path(f"{target}.tsx"), target / "index.ts", target / "index.tsx"):
        if candidate.is_file():
            return candidate
    return None


def route_of(path: Path) -> str | None:
    """Oberstes Routen-Segment einer Datei unter app/; 'home' ist die Startseite."""
    rel = path.relative_to(APP)
    if len(rel.parts) > 1:
        return rel.parts[0] if rel.parts[0] != "styles" else None
    return "home" if rel.name == "page.tsx" else None


def strip_functional(selector: str) -> str:
    """Klassen in :not()/:is()/:where()/:has() und Attributselektoren schraenken nicht sicher ein."""
    selector = re.sub(r"\[[^\]]*\]", "", selector)
    out, depth = "", 0
    for char in selector:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0:
            out += char
    return out


def selectors_of(css: str) -> list[str]:
    """Alle Selektoren einer CSS-Datei (auch innerhalb von @media/@supports)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: list[str] = []
    for match in re.finditer(r"([^{}]+)\{", css):
        prelude = match.group(1).strip()
        if prelude.startswith("@"):
            continue
        current, depth = "", 0
        for char in prelude:
            if char in "([":
                depth += 1
            elif char in ")]":
                depth -= 1
            if char == "," and depth == 0:
                out.append(current.strip())
                current = ""
            else:
                current += char
        out.append(current.strip())
    return [s for s in out if s and not re.fullmatch(r"[\d.]+%|from|to", s)]


def main() -> int:
    files = source_files()
    texts = {f: f.read_text(errors="replace") for f in files}
    graph = {f: {r for r in (resolve(f, m) for m in IMPORT_RE.findall(t)) if r} for f, t in texts.items()}

    routes: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        if f.is_relative_to(APP) and (route := route_of(f)):
            routes[route].append(f)

    def reach(roots: list[Path]) -> set[Path]:
        seen: set[Path] = set()
        stack = list(roots)
        while stack:
            current = stack.pop()
            if current not in seen and current in graph:
                seen.add(current)
                stack.extend(graph[current])
        return seen

    all_routes = set(routes)
    file_routes: dict[Path, set[str]] = defaultdict(set)
    for route, roots in routes.items():
        for f in reach(roots):
            file_routes[f].add(route)
    for f in reach([p for p in (APP / "layout.tsx", APP / "error.tsx") if p.exists()]):
        file_routes[f] = set(all_routes)

    # Welche Route laedt welches Bundle? Import irgendwo unterhalb der Route (Layout oder Seite).
    bundle_routes: dict[str, set[str]] = defaultdict(set)
    for route, roots in routes.items():
        for f in roots:
            for bundle in re.findall(r"""@/app/styles/([\w-]+)\.css""", texts[f]):
                bundle_routes[bundle].add(route)

    class_routes: dict[str, set[str]] = defaultdict(set)
    prefixes: dict[str, set[str]] = defaultdict(set)
    for f, text in texts.items():
        used = file_routes.get(f) or all_routes
        for token in TOKEN_RE.findall(text):
            class_routes[token] |= used
        for match in re.finditer(r"([A-Za-z_][\w-]*-)\$\{", text):
            prefixes[match.group(1)] |= used
        for match in re.finditer(r"""([A-Za-z_][\w-]*-)["'`]\s*\+""", text):
            prefixes[match.group(1)] |= used

    def routes_of_class(name: str) -> set[str]:
        out = set(class_routes.get(name, set()))
        for prefix, used in prefixes.items():
            if name.startswith(prefix):
                out |= used
        return out

    problems: list[str] = []
    for path in sorted(STYLES.glob("*.css")):
        loaded = bundle_routes.get(path.stem, set())
        if not loaded:
            problems.append(f"{path.relative_to(ROOT)}: wird von keiner Route importiert")
            continue
        for selector in selectors_of(path.read_text()):
            required = set(CLASS_RE.findall(strip_functional(selector)))
            hit: set[str] | None = None
            for name in required:
                used = routes_of_class(name)
                if used:
                    hit = used if hit is None else hit & used
            if hit is not None and not hit <= loaded:
                problems.append(f"{path.relative_to(ROOT)}: «{selector[:80]}» greift auch auf {', '.join(sorted(hit - loaded))}")
    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} CSS-Bereichsverstoesse - siehe design/DESIGN.md Abschnitt 10")
        return 1
    print("CSS-Bereiche: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
