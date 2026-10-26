#!/usr/bin/env python3
"""Erzeugt die Rechte-Übersicht der API: welche Route welche Berechtigung prüft (RBAC).

    python3 scripts/sync-route-permissions.py            # permissions/route-map.json neu schreiben
    python3 scripts/sync-route-permissions.py --check    # nur prüfen (Exit 1 bei Abweichung), für CI

Die Datei permissions/route-map.json wird eingecheckt. Jede Änderung an einer Rechteprüfung - neue
Route, entfernte oder schwächere Prüfung, neue Ausnahme - erscheint dadurch im Pull Request als
lesbarer Diff und wird bewusst geprüft. tests/test_route_permission_inventory.py stellt nur
sicher, DASS geprüft wird; diese Übersicht zeigt, WAS geprüft wird.

Gelesen wird der Quelltext (die Prüfungen laufen imperativ im Funktionsrumpf, SECURITY-RULES
§1.3), wie im Inventar-Test: Aufrufe in der Route und - transitiv - in Hilfsfunktionen desselben
Moduls. Prüfungen in Services stehen als "note" aus der ALLOWED-Liste des Inventar-Tests.

Felder je Route ("METHODE /pfad"):
  handler       Modul.Funktion
  requires      require_permission(user, P.X) - alle müssen erfüllt sein
  requires_any  require_any_permission(user, P.X, P.Y) - je Gruppe eine
  features      require_feature(user, "...")
  branches      user.can(P.X) - verzweigt nur (z. B. mehr Daten), ist kein Zugangstor
  platform      Plattform-Admin-Route (Dependency aus core/admin_security.py)
  note          begründete Ausnahme aus dem Inventar-Test
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "backend/app/api/routes"
MAIN = ROOT / "backend/app/main.py"
GENERATED = ROOT / "backend/app/core/permissions_generated.py"
DOCUMENT_PERMISSIONS = ROOT / "backend/app/documents/permissions.py"
INVENTORY_TEST = ROOT / "backend/tests/test_route_permission_inventory.py"
TARGET = ROOT / "permissions/route-map.json"

METHODS = {"get", "post", "put", "patch", "delete", "websocket"}
ADMIN_DEPENDENCIES = ("get_current_admin", "require_admin_write", "require_admin_owner")


def _permission_names() -> dict[str, str]:
    tree = ast.parse(GENERATED.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "P":
            return {
                item.targets[0].id: item.value.value
                for item in node.body
                if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name) and isinstance(item.value, ast.Constant)
            }
    raise SystemExit("permissions_generated.py: Klasse P fehlt")


PERMISSIONS = _permission_names()


def _allowed() -> dict[str, str]:
    spec = importlib.util.spec_from_file_location("route_inventory", INVENTORY_TEST)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ALLOWED


def _prefixes() -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for node in ast.walk(ast.parse(MAIN.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "include_router":
            target = node.args[0] if node.args else None
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                prefix = next((kw.value.value for kw in node.keywords if kw.arg == "prefix" and isinstance(kw.value, ast.Constant)), "")
                prefixes[target.value.id] = prefix
    return prefixes


def _permission(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "P" and node.attr in PERMISSIONS:
        return PERMISSIONS[node.attr]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return f"<{ast.unparse(node)}>"  # dynamisch - im Diff sichtbar, im Zweifel genauer hinsehen


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def _empty() -> dict[str, set]:
    return {"requires": set(), "requires_any": set(), "features": set(), "branches": set()}


def _direct_checks(node: ast.AST, external: dict[str, dict[str, set]]) -> tuple[dict[str, set], set[str]]:
    checks = _empty()
    called: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        name = _call_name(call)
        args = call.args[1:]
        if name == "require_permission":
            checks["requires"].update(_permission(arg) for arg in args)
        elif name == "require_any_permission":
            checks["requires_any"].add(tuple(sorted(_permission(arg) for arg in args)))
        elif name == "require_feature":
            checks["features"].update(_permission(arg) for arg in args)
        elif name == "can" and isinstance(call.func, ast.Attribute):
            checks["branches"].update(_permission(arg) for arg in call.args)
        if name in external:
            for field, values in external[name].items():
                checks[field] |= values
        if name:
            called.add(name)
        for arg in call.args:  # run_in_threadpool(helper, ...)
            if isinstance(arg, ast.Name):
                called.add(arg.id)
    return checks, called


def _module_checks(tree: ast.Module, external: dict[str, dict[str, set]]) -> dict[str, dict[str, set]]:
    """Prüfungen je Funktion des Moduls, transitiv über Hilfsfunktionen desselben Moduls."""
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    direct = {name: _direct_checks(node, external) for name, node in functions.items()}
    resolved: dict[str, dict[str, set]] = {}

    def resolve(name: str, stack: frozenset[str]) -> dict[str, set]:
        if name in resolved:
            return resolved[name]
        checks = {field: set(values) for field, values in direct[name][0].items()}
        for callee in direct[name][1]:
            if callee in functions and callee not in stack and callee != name:
                for field, values in resolve(callee, stack | {name}).items():
                    checks[field] |= values
        resolved[name] = checks
        return checks

    for name in functions:
        resolve(name, frozenset())
    return resolved


def _document_helpers() -> dict[str, dict[str, set]]:
    tree = ast.parse(DOCUMENT_PERMISSIONS.read_text(encoding="utf-8"))
    checks = _module_checks(tree, {})
    return {name: value for name, value in checks.items() if name.startswith("require_")}


def _route_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef):
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "router" and func.attr in METHODS:
            path = decorator.args[0].value if decorator.args and isinstance(decorator.args[0], ast.Constant) else ""
            yield func.attr.upper(), path


def build() -> dict[str, dict]:
    prefixes = _prefixes()
    allowed = _allowed()
    external = _document_helpers()
    routes: dict[str, dict] = {}
    for path in sorted(ROUTES.glob("*.py")):
        module = path.stem
        if module == "__init__" or module not in prefixes:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        checks = _module_checks(tree, external)
        module_admin = "APIRouter(dependencies=[Depends(get_current_admin)])" in source
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for method, route_path in _route_decorators(node):
                entry: dict = {"handler": f"{module}.{node.name}"}
                found = checks.get(node.name, _empty())
                if found["requires"]:
                    entry["requires"] = sorted(found["requires"])
                if found["requires_any"]:
                    entry["requires_any"] = sorted(list(group) for group in found["requires_any"])
                if found["features"]:
                    entry["features"] = sorted(found["features"])
                if found["branches"]:
                    entry["branches"] = sorted(found["branches"] - found["requires"])
                    if not entry["branches"]:
                        del entry["branches"]
                if module.startswith("admin"):
                    defaults = " ".join(ast.unparse(value) for value in node.args.defaults + node.args.kw_defaults if value is not None)
                    if module_admin or any(name in defaults for name in ADMIN_DEPENDENCIES):
                        entry["platform"] = True
                note = allowed.get(f"{module}.{node.name}") or allowed.get(f"{module}.*")
                if module == "admin_auth":
                    note = "Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit)"
                if note:
                    entry["note"] = note
                key = f"{method} {prefixes[module]}{route_path}"
                if key in routes:
                    key = f"{key} ({module}.{node.name})"
                routes[key] = entry
    return dict(sorted(routes.items(), key=lambda item: (item[0].split(" ", 1)[1], item[0])))


def render() -> str:
    data = {
        "$comment": "GENERATED FILE - do not edit by hand. Regenerate with: python3 scripts/sync-route-permissions.py",
        "routes": build(),
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != content:
            print(
                "permissions/route-map.json ist nicht aktuell - python3 scripts/sync-route-permissions.py ausführen "
                "und den Diff (geänderte Rechteprüfungen) bewusst prüfen.",
                file=sys.stderr,
            )
            return 1
        print("Rechte-Übersicht: ok")
        return 0
    TARGET.write_text(content, encoding="utf-8")
    print(f"geschrieben: {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
