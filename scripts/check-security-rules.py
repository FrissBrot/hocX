#!/usr/bin/env python3
"""Prüft Änderungen gegen die Sicherheitsregeln aus SECURITY-RULES.md.

Gemeldet werden nur NEU eingeführte Verstösse (gegenüber dem Vergleichsstand), damit der
Altbestand keinen Lärm macht und jede neue Stelle bewusst entschieden wird. Läuft als
Claude-Code-Hook nach jeder Dateiänderung (scripts/hooks/security-check-hook.sh), im
Pre-Commit-Hook (.githooks/pre-commit, gilt für alle Agents und Menschen) und in der CI.

Aufruf:
  scripts/check-security-rules.py DATEI...          # gegen HEAD
  scripts/check-security-rules.py --staged          # gestagte Dateien, Index gegen HEAD
  scripts/check-security-rules.py --base REF        # alle seit REF geänderten Dateien

Ausnahmen werden in derselben Zeile begründet markiert, z. B.
  # nosemgrep: public-id-lookup-without-tenant -- <Begründung>
  # sql-ok: <Begründung>        (nur feste Bezeichner, keine Benutzereingaben)
  # rls-ok: <Begründung>        (bewusst mandantenübergreifende Systemprüfung)
  {/* security-ok: <Begründung> */}
  # loop-ok: <Begründung>       (DB-Zugriff in async def, der den Event-Loop nicht blockiert)
  # stream-ok: <Begründung>     (Streaming-Antwort, deren Route die Session nicht hält)

Zusätzlich zu SECURITY-RULES.md zwei Regeln aus dem Concurrency-Audit (CONC-001/-002): ein
synchroner DB-Zugriff in einer async-Funktion blockiert den Event-Loop des ganzen Workers, und
eine Streaming-Antwort hält die Session der Route (get_db) bis zum letzten Byte.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_ROOTS = ("backend/app/", "abgabebox-backend/app/", "photo-analysis-worker/app/")
TS_ROOTS = ("frontend/", "abgabebox-frontend/")
TS_SKIP = ("node_modules/", ".next/", "e2e/", ".test.", ".spec.")

LOOKUPS = {"get_by_public_id", "resolve_internal_id", "resolve_internal_ids"}
SECRET_QUERY = re.compile(r"[?&](token|password|passwort|secret|api_key|apikey)=", re.IGNORECASE)

RULE_TEXT = {
    "public-id-lookup-without-tenant": "public_id-Lookup ohne tenant_id= (auf den Mandanten des Aufrufers scopen)",
    "sql-fstring": "SQL als f-String (Werte als gebundene Parameter übergeben)",
    "http-exception-without-cause": "raise HTTPException(...) im except-Block ohne `from exc` (Fehler verschwindet aus system_error_log)",
    "tenant-scope-suspended": "tenant_scope_suspended(...) ohne Begründung (# rls-ok: ...)",
    "dangerously-set-inner-html": "dangerouslySetInnerHTML ohne Begründung ({/* security-ok: ... */})",
    "secret-in-url": "Token/Passwort in einer URL-Query (gehört in Body oder Header)",
    "blocking-db-in-async": "synchroner DB-Zugriff in async def (blockiert den Event-Loop) - per run_in_threadpool/asyncio.to_thread ausführen",
    "stream-response-holds-db": "Streaming-/Datei-Antwort mit Depends(get_db) ohne scope=\"function\" (Verbindung bis zum letzten Byte belegt)",
}
MARKERS = {
    "public-id-lookup-without-tenant": ("nosemgrep: public-id-lookup-without-tenant", "tenant-scope-ok"),
    "sql-fstring": ("sql-ok",),
    "http-exception-without-cause": ("security-ok",),
    "tenant-scope-suspended": ("rls-ok",),
    "dangerously-set-inner-html": ("security-ok",),
    "secret-in-url": ("security-ok",),
    "blocking-db-in-async": ("loop-ok",),
    "stream-response-holds-db": ("stream-ok",),
}

OFFLOAD_CALLS = {"run_in_threadpool", "to_thread", "run_in_executor"}
STREAM_RESPONSES = {"object_response", "FileResponse", "StreamingResponse"}
DB_NAMES = {"db", "session"}


@dataclass(frozen=True)
class Finding:
    rule: str
    line: int
    snippet: str

    @property
    def key(self) -> tuple[str, str]:
        return self.rule, " ".join(self.snippet.split())


def _marked(lines: list[str], line: int, rule: str) -> bool:
    # Markierung in der Zeile selbst oder (bei umbrochenen Aufrufen) in der Zeile davor.
    window = " ".join(lines[max(0, line - 2) : line])
    return any(marker in window for marker in MARKERS[rule])


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _uses_db(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in DB_NAMES:
        return True
    values = [*node.args, *(keyword.value for keyword in node.keywords)]
    return any(isinstance(value, ast.Name) and value.id in DB_NAMES for value in values)


def _blocking_db_calls(function: ast.AsyncFunctionDef, add, lines: list[str]) -> None:
    """Aufrufe mit der Session im Rumpf einer async-Funktion. Ausgenommen: Übergabe an
    run_in_threadpool/to_thread, direkt erwartete Aufrufe (die aufgerufene async-Funktion wird
    selbst geprüft) und verschachtelte sync-Funktionen (laufen im Thread). Eine ganze Funktion,
    die nur in einem Worker-Thread mit eigenem Event-Loop läuft (core/offload.py), wird an der
    def-Zeile mit `# loop-ok: <Begründung>` ausgenommen."""
    if _marked(lines, function.lineno, "blocking-db-in-async"):
        return
    skip: set[int] = set()
    for node in ast.walk(function):
        if node is not function and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            skip.update(id(inner) for inner in ast.walk(node))
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            skip.add(id(node.value))
        if isinstance(node, ast.Call) and _call_name(node) in OFFLOAD_CALLS:
            skip.update(id(inner) for inner in ast.walk(node))
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and id(node) not in skip and _uses_db(node):
            add("blocking-db-in-async", node)


def _holds_db_dependency(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for default in [*function.args.defaults, *function.args.kw_defaults]:
        if (
            isinstance(default, ast.Call)
            and _call_name(default) == "Depends"
            and default.args
            and isinstance(default.args[0], ast.Name)
            and default.args[0].id == "get_db"
            and not any(keyword.arg == "scope" for keyword in default.keywords)
        ):
            return True
    return False


def _python_findings(source: str) -> list[Finding]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    findings: list[Finding] = []

    def add(rule: str, node: ast.AST) -> None:
        line = getattr(node, "lineno", 0)
        if not _marked(lines, line, rule):
            findings.append(Finding(rule, line, lines[line - 1].strip() if 0 < line <= len(lines) else ""))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in LOOKUPS:
            continue
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in LOOKUPS and not any(keyword.arg == "tenant_id" for keyword in node.keywords):
                add("public-id-lookup-without-tenant", node)
            if name in {"text", "execute", "exec_driver_sql"} and node.args and isinstance(node.args[0], ast.JoinedStr):
                if any(isinstance(part, ast.FormattedValue) for part in node.args[0].values):
                    add("sql-fstring", node)
            if name == "tenant_scope_suspended":
                add("tenant-scope-suspended", node)
            for arg in node.args:
                if isinstance(arg, ast.JoinedStr):
                    literal = "".join(part.value for part in arg.values if isinstance(part, ast.Constant) and isinstance(part.value, str))
                    if SECRET_QUERY.search(literal) and literal.lstrip().startswith(("http", "/")):
                        add("secret-in-url", node)
        if isinstance(node, ast.AsyncFunctionDef):
            _blocking_db_calls(node, add, lines)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _holds_db_dependency(node):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and _call_name(inner) in STREAM_RESPONSES:
                    add("stream-response-holds-db", inner)
        if isinstance(node, ast.ExceptHandler):
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Raise)
                    and isinstance(inner.exc, ast.Call)
                    and _call_name(inner.exc) == "HTTPException"
                    and inner.cause is None
                ):
                    add("http-exception-without-cause", inner)
    return findings


def _ts_findings(source: str) -> list[Finding]:
    lines = source.splitlines()
    findings: list[Finding] = []
    for number, text in enumerate(lines, start=1):
        if "dangerouslySetInnerHTML" in text and not _marked(lines, number, "dangerously-set-inner-html"):
            findings.append(Finding("dangerously-set-inner-html", number, text.strip()))
        if SECRET_QUERY.search(text) and ("`" in text or '"/' in text) and not _marked(lines, number, "secret-in-url"):
            findings.append(Finding("secret-in-url", number, text.strip()))
    return findings


def _relevant(path: str) -> str | None:
    if path.endswith(".py") and path.startswith(PY_ROOTS):
        return "py"
    if path.endswith((".ts", ".tsx")) and path.startswith(TS_ROOTS) and not any(skip in path for skip in TS_SKIP):
        return "ts"
    return None


def _findings(kind: str, source: str) -> list[Finding]:
    return _python_findings(source) if kind == "py" else _ts_findings(source)


def _git(*args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def new_findings(path: str, current: str, baseline: str | None) -> list[Finding]:
    kind = _relevant(path)
    if kind is None:
        return []
    found = _findings(kind, current)
    remaining = Counter(finding.key for finding in _findings(kind, baseline)) if baseline else Counter()
    new: list[Finding] = []
    for finding in found:
        if remaining[finding.key] > 0:
            remaining[finding.key] -= 1
        else:
            new.append(finding)
    return new


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--base")
    parser.add_argument("--exit-code", type=int, default=1)
    args = parser.parse_args()

    if args.staged:
        names = (_git("diff", "--cached", "--name-only", "--diff-filter=ACMR") or "").split()
        files = [(name, _git("show", f":{name}") or "", _git("show", f"HEAD:{name}")) for name in names]
    elif args.base:
        names = (_git("diff", "--name-only", "--diff-filter=ACMR", f"{args.base}...HEAD") or "").split()
        files = [(name, (ROOT / name).read_text(encoding="utf-8"), _git("show", f"{args.base}:{name}")) for name in names]
    else:
        files = []
        for raw in args.files:
            path = Path(raw).resolve()
            try:
                name = path.relative_to(ROOT).as_posix()
            except ValueError:
                continue
            if path.is_file():
                files.append((name, path.read_text(encoding="utf-8"), _git("show", f"HEAD:{name}")))

    problems = [(name, finding) for name, current, baseline in files for finding in new_findings(name, current, baseline)]
    if not problems:
        print("Sicherheitsregeln: ok")
        return 0
    print("Sicherheitsregeln verletzt (siehe SECURITY-RULES.md):", file=sys.stderr)
    for name, finding in problems:
        print(f"  {name}:{finding.line}: [{finding.rule}] {RULE_TEXT[finding.rule]}", file=sys.stderr)
        print(f"      {finding.snippet[:160]}", file=sys.stderr)
    print("Beheben, oder als bewusste Ausnahme in derselben Zeile begründet markieren (Marker siehe Kopf dieses Skripts).", file=sys.stderr)
    return args.exit_code


if __name__ == "__main__":
    sys.exit(main())
