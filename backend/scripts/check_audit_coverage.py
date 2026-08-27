#!/usr/bin/env python3
"""Lists mutating API routes with no directly-visible AuditService.log(...) call.

Closes the gap named in hocX.wiki/Bekannte-offene-Punkte ("kein automatisches Inventar,
das alle schreibenden Endpunkte gegen erwartete Audit-Events abgleicht"). Informational
only, not a CI gate: a route can legitimately log through a service function this script
doesn't look inside (it only inspects the route handler's own body, one level deep - it
does not follow calls into app/services/*.py), and not every mutation is security/audit-
relevant. Treat the output as a checklist to review, not a pass/fail signal.

Usage: python3 scripts/check_audit_coverage.py [routes_dir]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MUTATING_METHODS = {"post", "put", "patch", "delete"}


def _audit_instance_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "AuditService"
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _route_decorator(func: ast.AsyncFunctionDef | ast.FunctionDef) -> tuple[str, str] | None:
    for dec in func.decorator_list:
        if (
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in MUTATING_METHODS
            and dec.args
            and isinstance(dec.args[0], ast.Constant)
            and isinstance(dec.args[0].value, str)
        ):
            return dec.func.attr.upper(), dec.args[0].value
    return None


def _calls_audit_log(func: ast.AsyncFunctionDef | ast.FunctionDef, audit_names: set[str]) -> bool:
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "log"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in audit_names
        ):
            return True
    return False


def check_file(path: Path) -> list[tuple[str, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    audit_names = _audit_instance_names(tree)
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        route = _route_decorator(node)
        if route is None:
            continue
        method, route_path = route
        if not audit_names or not _calls_audit_log(node, audit_names):
            findings.append((method, route_path, node.name))
    return findings


def main() -> int:
    routes_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "app/api/routes"
    total = 0
    for path in sorted(routes_dir.glob("*.py")):
        findings = check_file(path)
        if not findings:
            continue
        print(f"\n{path.relative_to(routes_dir.parents[2])}:")
        for method, route_path, func_name in findings:
            print(f"  {method:6} {route_path}  ({func_name})")
            total += 1

    print(f"\n{total} mutating route(s) with no directly-visible audit.log(...) call.")
    print("Informational only - see this script's docstring before treating any of these as a bug.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
