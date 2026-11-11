#!/usr/bin/env python3
"""Grössenbudget des Frontend-Builds: JS und CSS, die eine Seite beim ersten Laden braucht.

Läuft in der CI nach ``next build`` (Job ``frontend-build``) und meldet nur, es korrigiert nichts.
Gemessen wird je Route aus den Manifesten des Builds (Turbopack): die Einstiegs-Chunks aller
Segmente (Layouts + Seite) plus die gemeinsamen Root-Chunks, gzip-komprimiert wie im Browser.
Messwerte sind deterministisch (gleicher Build = gleiche Zahl), daher taugen sie als harte Grenze -
anders als Ladezeiten, die auf CI-Runnern schwanken (die misst die Test-Host-Abnahme, TH-22).

Budget: ``frontend/bundle-budget.json``. Eine Route über ihrem Budget lässt die Prüfung scheitern.
Wird eine Route bewusst grösser (neue Bibliothek, neue Funktion), das Budget im selben Change
anheben und im Commit begründen: ``--update`` schreibt die aktuellen Werte plus Reserve.

Usage: scripts/check-bundle-budget.py [--next-dir frontend/.next] [--budget frontend/bundle-budget.json] [--update]
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Reserve beim Neuschreiben des Budgets: kleine Änderungen sollen nicht sofort anschlagen,
# ein deutlicher Sprung (neue grosse Abhängigkeit, versehentlich globales CSS) schon.
HEADROOM = 1.10
# Feste Obergrenze für rohes CSS je Seite, wie in der Test-Host-Abnahme (TH-22, browser-checks.mjs)
MAX_CSS_RAW_KB = 400
MANIFEST_RE = re.compile(r"=\s*(\{.*\})\s*;?\s*$", re.S)


def _gzip_size(path: Path, cache: dict[Path, int]) -> int:
    if path not in cache:
        cache[path] = len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))
    return cache[path]


def _route_name(manifest: Path, app_dir: Path) -> str:
    relative = manifest.parent.relative_to(app_dir).as_posix()
    return "/" if relative == "." else f"/{relative}"


def measure(next_dir: Path) -> dict[str, dict[str, float]]:
    build_manifest = json.loads((next_dir / "build-manifest.json").read_text())
    root_js = list(build_manifest.get("rootMainFiles", [])) + list(build_manifest.get("polyfillFiles", []))
    app_dir = next_dir / "server" / "app"
    cache: dict[Path, int] = {}
    routes: dict[str, dict[str, float]] = {}
    for manifest in sorted(app_dir.rglob("page_client-reference-manifest.js")):
        match = MANIFEST_RE.search(manifest.read_text())
        if match is None:
            raise SystemExit(f"Manifest nicht lesbar: {manifest}")
        data = json.loads(match.group(1))
        js = set(root_js)
        for files in data.get("entryJSFiles", {}).values():
            js.update(files)
        css = {entry["path"] for entries in data.get("entryCSSFiles", {}).values() for entry in entries if not entry.get("inlined")}
        routes[_route_name(manifest, app_dir)] = {
            "js_gzip_kb": round(sum(_gzip_size(next_dir / file, cache) for file in js) / 1024, 1),
            "css_gzip_kb": round(sum(_gzip_size(next_dir / file, cache) for file in css) / 1024, 1),
            "css_raw_kb": round(sum((next_dir / file).stat().st_size for file in css) / 1024, 1),
        }
    if not routes:
        raise SystemExit(f"Keine Routen in {app_dir} gefunden - lief «next build»?")
    return routes


def _budget_for(measured: dict[str, float]) -> dict[str, int]:
    budget = {key: int(math.ceil(value * HEADROOM)) for key, value in measured.items()}
    budget["css_raw_kb"] = min(budget["css_raw_kb"], MAX_CSS_RAW_KB)
    return budget


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--next-dir", default=str(ROOT / "frontend" / ".next"))
    parser.add_argument("--budget", default=str(ROOT / "frontend" / "bundle-budget.json"))
    parser.add_argument("--update", action="store_true", help="Budget aus dem aktuellen Build neu schreiben")
    args = parser.parse_args()
    routes = measure(Path(args.next_dir))
    budget_path = Path(args.budget)

    if args.update:
        budget = {
            "_hinweis": "Erzeugt mit scripts/check-bundle-budget.py --update (Messwert + 10 % Reserve, KB; rohes CSS höchstens 400). Anheben nur begründet im Commit.",
            "routes": {route: _budget_for(values) for route, values in sorted(routes.items())},
        }
        budget_path.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n")
        print(f"Budget geschrieben: {budget_path} ({len(routes)} Routen)")
        return 0

    budget = json.loads(budget_path.read_text())["routes"]
    problems: list[str] = []
    rows: list[str] = []
    for route, values in sorted(routes.items()):
        limits = budget.get(route)
        if limits is None:
            problems.append(f"{route}: kein Budget (neue Route? scripts/check-bundle-budget.py --update)")
            continue
        for key, value in values.items():
            limit = limits.get(key)
            if key == "css_raw_kb":
                limit = min(limit if limit is not None else MAX_CSS_RAW_KB, MAX_CSS_RAW_KB)
            if limit is not None and value > limit:
                problems.append(f"{route}: {key} {value} KB > Budget {limit} KB")
        rows.append(f"| `{route}` | {values['js_gzip_kb']} / {limits.get('js_gzip_kb')} | {values['css_gzip_kb']} / {limits.get('css_gzip_kb')} | {values['css_raw_kb']} / {limits.get('css_raw_kb')} |")
    gone = sorted(set(budget) - set(routes))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Bundle-Budget (gzip KB, Ist / Budget)\n\n| Route | JS | CSS | CSS roh |\n|---|---|---|---|\n")
            handle.write("\n".join(rows) + "\n")
            if problems:
                handle.write("\n**Über dem Budget:**\n\n" + "\n".join(f"- {problem}" for problem in problems) + "\n")
    heaviest = sorted(routes.items(), key=lambda item: item[1]["js_gzip_kb"], reverse=True)[:5]
    print("Schwerste Routen (JS gzip KB): " + ", ".join(f"{route} {values['js_gzip_kb']}" for route, values in heaviest))
    if gone:
        print("Hinweis: Budget für nicht mehr vorhandene Routen: " + ", ".join(gone))
    if problems:
        print("Bundle-Budget überschritten:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Bundle-Budget: ok ({len(routes)} Routen)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
