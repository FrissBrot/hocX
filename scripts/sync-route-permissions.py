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
  features      require_feature(user, "...") bzw. F.X; «(lesen)» = auch im Nur-Lesen-Zustand
  requires_if   require_permission(...) nur in einem Zweig (if/else, Schleife, except) - gilt
                nur in bestimmten Fällen (z. B. meetings.approve beim Zurückstufen aus
                «abgeschlossen»), ist kein Zugangstor für die Route
  branches      user.can(P.X) - verzweigt nur (z. B. mehr Daten), ist kein Zugangstor
  platform      Plattform-Admin-Route (Dependency aus core/admin_security.py)
  note          begründete Ausnahme aus dem Inventar-Test
"""
from __future__ import annotations

import argparse
import ast
import re
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
CATALOG = ROOT / "permissions/catalog.json"
# Berechtigungsmatrix (Plan «Berechtigungen», Phase 0): Standardrolle x Route -> erlaubt. Eine Kopie
# liegt bei den Backend-Tests (der Testcontainer sieht nur backend/), dort prüft
# tests/test_permission_matrix.py die Matrix gegen echte Aufrufe.
MATRIX = ROOT / "permissions/permission-matrix.json"
MATRIX_FIXTURE = ROOT / "backend/tests/fixtures/permission-matrix.json"
INVENTORY_DOC = ROOT / "docs/permissions-inventory.md"
# Antworten mit Dateiinhalt (Download, Vorschau, Thumbnail, ZIP, Export, Weiterleitung auf Speicher)
FILE_MARKERS = ("FileResponse", "StreamingResponse", "release_for_stream", "presign", "send_file", "stream_object", "media_type=", "Content-Disposition", "X-Accel-Redirect")

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
    # Feature-Konstanten (core/features_generated.py: F.TASK_PACKAGES = "task_packages")
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "F":
        return node.attr.lower()
    return f"<{ast.unparse(node)}>"  # dynamisch - im Diff sichtbar, im Zweifel genauer hinsehen


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def _empty() -> dict[str, set]:
    return {"requires": set(), "requires_any": set(), "requires_if": set(), "features": set(), "branches": set()}


def _conditional_nodes(function: ast.AST, alternatives: dict[int, list[str]]) -> set[int]:
    """ids aller Knoten, die nur in einem Zweig laufen: Rumpf/else von if, Schleifenrümpfe,
    except-/else-Zweige von try, match-Fälle, bedingte Ausdrücke und der rechte Teil von and/or.
    Die Bedingung selbst (if not user.can(...)) läuft immer und zählt nicht als bedingt."""
    conditional: set[int] = set()
    alternatives.clear()

    def can_test(test: ast.AST) -> tuple[list[str], bool] | None:
        # user.can(P.X) bzw. not user.can(P.X)
        negated = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
        call = test.operand if negated else test
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "can":
            return [_permission(arg) for arg in call.args], negated
        return None

    def mark(nodes) -> None:
        for node in nodes:
            for child in ast.walk(node):
                conditional.add(id(child))

    for node in ast.walk(function):
        if node is not function and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.If):
            mark(node.body + node.orelse)
            # «if user.can(P.X): … else: require_permission(user, P.Y)» heisst X oder Y: die
            # Pflichtprüfung direkt im Zweig ohne X wird zur Gruppe requires_any (X, Y).
            tested = can_test(node.test)
            if tested is not None:
                permissions, negated = tested
                for statement in node.body if negated else node.orelse:
                    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                        alternatives[id(statement.value)] = permissions
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            mark(node.body + node.orelse)
        elif isinstance(node, ast.Try):
            mark(node.handlers + node.orelse)
        elif isinstance(node, ast.Match):
            mark(node.cases)
        elif isinstance(node, ast.IfExp):
            mark([node.body, node.orelse])
        elif isinstance(node, ast.BoolOp):
            mark(node.values[1:])
    return conditional


def _direct_checks(node: ast.AST, external: dict[str, dict[str, set]]) -> tuple[dict[str, set], set[str]]:
    checks = _empty()
    called: set[str] = set()
    alternatives: dict[int, list[str]] = {}
    conditional = _conditional_nodes(node, alternatives)
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        name = _call_name(call)
        args = call.args[1:]
        if name == "require_permission" and id(call) in alternatives:
            checks["requires_any"].add(tuple(sorted({*alternatives[id(call)], *(_permission(arg) for arg in args)})))
        elif name == "require_permission":
            checks["requires_if" if id(call) in conditional else "requires"].update(_permission(arg) for arg in args)
        elif name == "require_any_permission":
            checks["requires_any"].add(tuple(sorted(_permission(arg) for arg in args)))
        elif name == "require_feature":
            # write=False: auch im Nur-Lesen-Zustand nach einem Downgrade erlaubt
            read_only = any(keyword.arg == "write" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False for keyword in call.keywords)
            checks["features"].update(_permission(arg) + (" (lesen)" if read_only else "") for arg in args)
        elif name == "can" and isinstance(call.func, ast.Attribute):
            checks["branches"].update(_permission(arg) for arg in call.args)
        if name in external:
            for field, values in external[name].items():
                checks[field] |= values
        # Nur direkte Aufrufe zählen als Hilfsfunktion des Moduls: service.repository.list_x(...)
        # ist nicht die gleichnamige Route list_x (sonst erbte die Route deren Prüfungen und die
        # Übersicht zeigte mehr, als geprüft wird - aufgefallen im Matrix-Test, Phase 0).
        if name and isinstance(call.func, ast.Name):
            called.add(name if id(call) not in conditional else f"?{name}")
        for arg in call.args:  # run_in_threadpool(helper, ...)
            if isinstance(arg, ast.Name):
                called.add(arg.id if id(call) not in conditional else f"?{arg.id}")
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
        for marked in direct[name][1]:
            # «?helper»: nur in einem Zweig aufgerufen - dessen Pflichtprüfungen gelten nur bedingt
            callee, only_sometimes = marked.lstrip("?"), marked.startswith("?")
            if callee in functions and callee not in stack and callee != name:
                for field, values in resolve(callee, stack | {name}).items():
                    target = "requires_if" if only_sometimes and field == "requires" else field
                    checks[target] |= values
        resolved[name] = checks
        return checks

    for name in functions:
        resolve(name, frozenset())
    return resolved


def _document_helpers() -> dict[str, dict[str, set]]:
    tree = ast.parse(DOCUMENT_PERMISSIONS.read_text(encoding="utf-8"))
    checks = _module_checks(tree, {})
    return {name: value for name, value in checks.items() if name.startswith("require_")}


def _module_file_servers(tree: ast.Module) -> set[str]:
    """Funktionen des Moduls, die Dateiinhalt ausliefern - direkt oder über eine Hilfsfunktion
    desselben Moduls (transitiv, wie die Rechteprüfungen)."""
    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    direct = {name for name, node in functions.items() if any(marker in ast.unparse(node) for marker in FILE_MARKERS)}
    calls = {
        name: {sub.func.id for sub in ast.walk(node) if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)}
        for name, node in functions.items()
    }
    serving = set(direct)
    changed = True
    while changed:
        changed = False
        for name, called in calls.items():
            if name not in serving and called & serving:
                serving.add(name)
                changed = True
    return serving


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
        file_servers = _module_file_servers(tree)
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
                conditional_only = found["requires_if"] - found["requires"]
                if conditional_only:
                    entry["requires_if"] = sorted(conditional_only)
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
                        # Stufe der Admin-Prüfung (Admin-Redesign §8.1 Nr. 2): A = jeder Admin,
                        # W = require_admin_write, O = require_admin_owner, dazu der Step-up-Zweck -
                        # damit eine abgeschwächte Prüfung im Diff dieser Datei auffällt.
                        whole = ast.unparse(node)
                        # nur echte Abhängigkeiten zählen (Depends(...)), keine Erwähnung in Docstrings
                        owner = re.search(r"Depends\(\s*require_admin_owner\s*\)", whole) is not None
                        write = re.search(r"Depends\(\s*require_admin_write\s*\)", whole) is not None
                        entry["admin_level"] = "O+W" if owner and write else "O" if owner else "W" if write else "A"
                        purposes = sorted(set(re.findall(r"(?:require_step_up|step_up_proof)\(['\"]([\w-]+)['\"]\)", whole)))
                        if purposes:
                            entry["step_up"] = ", ".join(purposes)
                note = allowed.get(f"{module}.{node.name}") or allowed.get(f"{module}.*")
                if module == "admin_auth":
                    note = "Plattform-Anmeldung: eigenes Sicherheitsmodell (core/admin_security.py, Rate-Limit)"
                if note:
                    entry["note"] = note
                if node.name in file_servers:
                    entry["serves_files"] = True
                key = f"{method} {prefixes[module]}{route_path}"
                if key in routes:
                    key = f"{key} ({module}.{node.name})"
                routes[key] = entry
    return dict(sorted(routes.items(), key=lambda item: (item[0].split(" ", 1)[1], item[0])))


def _role_permissions() -> dict[str, set[str]]:
    """Effektive Rechte der Standardrollen (inkl. implies), wie role_service sie vergibt."""
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    implies = {item["key"]: set(item.get("implies") or []) for item in catalog["permissions"]}
    every = set(implies)

    def closure(keys: set[str]) -> set[str]:
        result, todo = set(), list(keys)
        while todo:
            key = todo.pop()
            if key not in result:
                result.add(key)
                todo.extend(implies.get(key, ()))
        return result

    return {
        role["key"]: every if role.get("all_permissions") else closure(set(role.get("permissions") or []))
        for role in catalog["system_roles"]
    }


def build_matrix(routes: dict[str, dict]) -> dict[str, dict]:
    """Je Mandanten-Route mit Rechteprüfung: welche Standardrolle sie aufrufen darf (Features
    vorausgesetzt). Routen mit eigenem Sicherheitsmodell («note») und Plattform-Routen fehlen."""
    roles = _role_permissions()
    matrix: dict[str, dict] = {}
    for key, entry in routes.items():
        if entry.get("platform") or not (entry.get("requires") or entry.get("requires_any")):
            continue
        allowed = [
            role for role, perms in roles.items()
            if set(entry.get("requires") or []) <= perms
            and all(set(group) & perms for group in entry.get("requires_any") or [])
        ]
        matrix[key] = {"handler": entry["handler"], "allowed": allowed, **({"serves_files": True} if entry.get("serves_files") else {})}
    return matrix


def render_matrix(routes: dict[str, dict]) -> str:
    data = {
        "$comment": "GENERATED FILE - do not edit by hand. Regenerate with: python3 scripts/sync-route-permissions.py",
        "roles": sorted(_role_permissions()),
        "routes": build_matrix(routes),
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def render_inventory(routes: dict[str, dict]) -> str:
    """docs/permissions-inventory.md: Inventar (Plan «Berechtigungen», Phase 0), generiert."""
    tenant = {k: v for k, v in routes.items() if not v.get("platform")}
    checked = [k for k, v in tenant.items() if v.get("requires") or v.get("requires_any")]
    noted = {k: v for k, v in tenant.items() if "note" in v and not (v.get("requires") or v.get("requires_any"))}
    unchecked = [k for k, v in tenant.items() if not (v.get("requires") or v.get("requires_any")) and "note" not in v]
    files = {k: v for k, v in routes.items() if v.get("serves_files")}

    def check_text(entry: dict) -> str:
        parts = [", ".join(entry.get("requires") or [])]
        parts += [" oder ".join(group) for group in entry.get("requires_any") or []]
        text = " + ".join(p for p in parts if p)
        if entry.get("requires_if"):
            text += (" · " if text else "") + "je nach Fall: " + ", ".join(entry["requires_if"])
        if entry.get("platform"):
            text = f"Plattform-Admin ({entry.get('admin_level', 'A')})" + (f", Step-up {entry['step_up']}" if entry.get("step_up") else "")
        if entry.get("note"):
            text = (text + " · " if text else "") + entry["note"]
        if entry.get("features"):
            text += " · Feature " + ", ".join(entry["features"])
        return text or "**keine**"

    lines = [
        "# Berechtigungs-Inventar",
        "",
        "GENERIERT von `python3 scripts/sync-route-permissions.py` (Plan «Berechtigungen, Datei-Kontexte",
        "und Kontext-Freigaben», Phase 0). Nicht von Hand bearbeiten. Quelle: `permissions/route-map.json`;",
        "Rollen-Matrix: `permissions/permission-matrix.json` (geprüft von `tests/test_permission_matrix.py`).",
        "",
        "## Übersicht",
        "",
        f"- Routen gesamt: {len(routes)} (Plattform-Admin: {len(routes) - len(tenant)})",
        f"- Mandanten-Routen mit Rechteprüfung: {len(checked)}",
        f"- Mandanten-Routen mit eigenem Sicherheitsmodell (begründete Ausnahme): {len(noted)}",
        f"- Mandanten-Routen ohne Prüfung und ohne Begründung (Lücken): {len(unchecked)}",
        f"- Routen, die Dateiinhalt ausliefern: {len(files)}",
        "",
        "## Lücken (Routen ohne Prüfung und ohne Begründung)",
        "",
    ]
    lines += [f"- `{k}` ({tenant[k]['handler']})" for k in unchecked] or ["Keine – `tests/test_route_permission_inventory.py` verhindert neue."]
    lines += [
        "",
        "## Befunde Phase 0 (18.11.2026)",
        "",
        "- Die statische Analyse rechnete Methodenaufrufe (`service.repository.list_assignments(...)`)",
        "  der gleichnamigen Route zu und zeigte dadurch mehr Prüfungen als tatsächlich laufen. Behoben;",
        "  betroffen waren zehn Routen, inhaltlich nur `GET /api/submission-assignments/summaries`",
        "  (angezeigt `submissions.manage`, geprüft `submissions.read` – Leser sehen den Fortschritt aller",
        "  Abgaben; passt zu ihrem Leserecht, keine Lücke). Bei den übrigen fiel nur `meetings.read` weg,",
        "  das `meetings.edit`/`templates.edit`/`files.manage` ohnehin enthalten bzw. voraussetzen.",
        "- Laufzeit-Matrix (`tests/test_permission_matrix.py`): alle GET-Routen weisen genau die Rollen",
        "  ausserhalb der Matrix mit 403 ab.",
    ]
    lines += ["", "## Dateiauslieferung (Download, Vorschau, Thumbnail, ZIP, Export)", "", "| Route | Handler | Prüfung |", "|---|---|---|"]
    lines += [f"| `{k}` | {v['handler']} | {check_text(v)} |" for k, v in files.items()]
    lines += ["", "## Eigenes Sicherheitsmodell (begründete Ausnahmen)", "", "| Route | Begründung |", "|---|---|"]
    lines += [f"| `{k}` | {v['note']} |" for k, v in noted.items()]
    lines += ["", "## Alle Mandanten-Routen", "", "| Route | Prüfung |", "|---|---|"]
    lines += [f"| `{k}` | {check_text(v)} |" for k, v in tenant.items()]
    return "\n".join(lines) + "\n"


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
    routes = json.loads(content)["routes"]
    outputs = {
        TARGET: content,
        MATRIX: render_matrix(routes),
        MATRIX_FIXTURE: render_matrix(routes),
        INVENTORY_DOC: render_inventory(routes),
    }
    if args.check:
        stale = [path for path, text in outputs.items() if (path.read_text(encoding="utf-8") if path.exists() else "") != text]
        if stale:
            print(
                "Nicht aktuell: " + ", ".join(str(path.relative_to(ROOT)) for path in stale)
                + " - python3 scripts/sync-route-permissions.py ausführen und den Diff (geänderte Rechteprüfungen) bewusst prüfen.",
                file=sys.stderr,
            )
            return 1
        print("Rechte-Übersicht: ok")
        return 0
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
        print(f"geschrieben: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
