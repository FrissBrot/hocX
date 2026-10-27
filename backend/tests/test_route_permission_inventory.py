"""Routen-Inventar (RBAC, docs/RBAC_ARCHITECTURE_PROPOSAL.md T-1): jede Mandanten-Route prüft
eine Berechtigung - direkt (require_permission/require_any_permission/documents.permissions)
oder über eine Hilfsfunktion im selben Modul -, oder sie steht mit Begründung in ALLOWED.

Die Prüfungen laufen in hocX imperativ im Funktionsrumpf statt als Depends (SECURITY-RULES §1.3),
deshalb liest dieser Test den Quelltext statt der FastAPI-Dependencies. Eine neue Route ohne
Prüfung lässt ihn fehlschlagen - die Lösung ist eine Prüfung, nicht ein Eintrag in ALLOWED.
Plattform-Routen (admin*.py) brauchen stattdessen eine Admin-Dependency (core/admin_security.py).
"""
from __future__ import annotations

import ast
from pathlib import Path

ROUTES = Path(__file__).resolve().parents[1] / "app" / "api" / "routes"
CHECKS = {
    "require_permission",
    "require_any_permission",
    "require_export",
    "require_view",
    "require_edit",
    "require_publish",
    "require_brand",
    # documents/permissions.py: templates.edit + Feature document_designer
    "require_design",
}
ADMIN_DEPENDENCIES = ("get_current_admin", "require_admin_write", "require_admin_owner")

# Bewusst ohne eigene Funktionsberechtigung - Kategorie: Begründung.
ALLOWED = {
    # Öffentlich bzw. Anmeldung: eigenes Sicherheitsmodell (Token, Rate-Limit, Login-Ablauf).
    "auth.*": "Anmeldung, MFA beim Login, Session, Domain-Bridge",
    "public_share.*": "öffentliche Freigabelinks: Token + Rate-Limit (share_link_service)",
    "public_catalog.*": "öffentlicher Preis-/Kundenkatalog der Website",
    "maintenance_public.*": "öffentlicher Wartungsstatus",
    "system_status.*": "Status-Token (kein Benutzer)",
    "calendar_feeds.get_calendar_feed": "öffentlicher .ics-Abruf: Token + can_subscribe in calendar_feed_service.resolve",
    "tenants.tenant_profile_image": "Vereinslogo (auch für die Login-Seite)",
    # Eigene Daten (Ressourcenregel R4): ohne Permission, nur das eigene Konto.
    "users.get_me": "eigenes Konto",
    "users.patch_me": "eigenes Konto",
    "users.export_my_personal_data": "eigene Datenauskunft (rate-limitiert)",
    "users.get_my_mfa": "eigene MFA",
    "users.patch_my_preferred_mfa_method": "eigene MFA",
    "users.start_my_totp_enrollment": "eigene MFA",
    "users.complete_my_totp_enrollment": "eigene MFA",
    "users.start_my_passkey_registration": "eigene MFA",
    "users.complete_my_passkey_registration": "eigene MFA",
    "users.delete_my_mfa_factor": "eigene MFA",
    "users.change_my_password": "eigenes Passwort",
    "calendar_feeds.list_calendar_feeds": "eigene Kalender-Abos",
    "calendar_feeds.delete_calendar_feed": "eigene Kalender-Abos",
    "fines.list_fines": "eigene Bussen; alle nur mit reports.personal (im Rumpf)",
    # Prüfung im Service (dort mit require_permission, Tests in test_user_service.py usw.).
    "users.list_users": "UserService (access.manage)",
    "users.create_user": "UserService (access.manage)",
    "users.get_user": "UserService (access.manage)",
    "users.patch_user": "UserService (access.manage)",
    "users.delete_user": "UserService (access.manage)",
    "users.get_user_mfa": "MfaService._managed_user (access.manage)",
    "users.delete_user_mfa_factor": "MfaService._managed_user (access.manage)",
    "tenants.list_tenants": "TenantService._manageable_tenant_ids (settings.manage)",
    "tenants.patch_tenant": "TenantService (settings.manage)",
    "tenants.get_tenant_subscription": "TenantService (settings.manage)",
    "tenants.get_tenant_charges": "TenantService (settings.manage)",
    "tenants.list_tenant_domains": "TenantService (settings.manage)",
    "tenants.create_tenant_domain": "TenantService.require_manageable (settings.manage)",
    "tenants.verify_tenant_domain": "TenantService.require_manageable (settings.manage)",
    "tenants.delete_tenant_domain": "TenantService.require_manageable (settings.manage)",
    "collaboration_ws.protocol_collaboration": "WebSocket: can_read_protocol beim Verbinden und alle 30 s, Schreiben nur mit meetings.edit (_can_edit)",
}


def _route_functions(tree: ast.Module):
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "router":
                yield node
                break


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
        # run_coroutine_in_thread(_impl, ...) / run_in_threadpool(helper, ...)
        for arg in call.args:
            if isinstance(arg, ast.Name):
                names.add(arg.id)
    return names


def _checking_functions(tree: ast.Module) -> set[str]:
    """Funktionen des Moduls, die (transitiv über andere Modul-Funktionen) prüfen."""
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    calls = {name: _called_names(node) for name, node in functions.items()}
    checking = {name for name, names in calls.items() if names & CHECKS}
    changed = True
    while changed:
        changed = False
        for name, names in calls.items():
            if name not in checking and names & checking:
                checking.add(name)
                changed = True
    return checking


def _allowed(module: str, function: str) -> bool:
    return f"{module}.{function}" in ALLOWED or f"{module}.*" in ALLOWED


def test_every_tenant_route_checks_a_permission():
    missing = []
    for path in sorted(ROUTES.glob("*.py")):
        module = path.stem
        if module.startswith("admin") or module == "__init__":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        checking = _checking_functions(tree)
        for route in _route_functions(tree):
            if route.name in checking or _allowed(module, route.name):
                continue
            missing.append(f"{module}.{route.name} ({path.name}:{route.lineno})")
    assert missing == [], "Routen ohne Berechtigungsprüfung:\n" + "\n".join(missing)


def test_platform_routes_require_a_platform_admin():
    missing = []
    for path in sorted(ROUTES.glob("admin*.py")):
        if path.stem == "admin_auth":
            continue
        source = path.read_text(encoding="utf-8")
        if "APIRouter(dependencies=[Depends(get_current_admin)])" in source:
            continue  # gilt für jede Route des Moduls
        tree = ast.parse(source)
        for route in _route_functions(tree):
            defaults = " ".join(ast.unparse(value) for value in route.args.defaults + route.args.kw_defaults if value is not None)
            decorators = " ".join(ast.unparse(decorator) for decorator in route.decorator_list)
            if any(name in defaults or name in decorators for name in ADMIN_DEPENDENCIES):
                continue
            missing.append(f"{path.stem}.{route.name} ({path.name}:{route.lineno})")
    assert missing == [], "Plattform-Routen ohne Admin-Dependency:\n" + "\n".join(missing)


def test_allowlist_has_no_stale_entries():
    """Ein Eintrag für eine Route, die es nicht mehr gibt (oder die inzwischen selbst prüft),
    wird entfernt statt mitgeschleppt."""
    existing: dict[str, set[str]] = {}
    checking_by_module: dict[str, set[str]] = {}
    for path in ROUTES.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        existing[path.stem] = {route.name for route in _route_functions(tree)}
        checking_by_module[path.stem] = _checking_functions(tree)
    stale = []
    for entry in ALLOWED:
        module, function = entry.split(".", 1)
        if function == "*":
            if module not in existing:
                stale.append(entry)
        elif function not in existing.get(module, set()) or function in checking_by_module.get(module, set()):
            stale.append(entry)
    assert stale == []
