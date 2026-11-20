"""Statische Prüfung der Admin-Isolation (Auth-Audit SEC-AUTH-001), aufgerufen von
scripts/tests/test_admin_isolation.sh mit `docker compose config --format json` auf stdin.

Wertet die Traefik-Regeln aller Router aus den Compose-Labels und aus
infra/traefik/dynamic/admin-isolation.yml mit einem kleinen Regel-Interpreter aus (Host, Path,
PathPrefix, Method, !, &&, ||, Klammern - mehr verwenden die Labels nicht) und prüft:

- jeder Router nennt seine Entrypoints ausdrücklich (ein Router ohne Angabe hinge an ALLEN,
  auch an adminsecure);
- ausser den Admin-Routern (nur adminsecure, Host = Admin-Domain, Middleware admin-gate@file)
  matcht kein Router einen Admin-Pfad - auf keiner Domain;
- der Sperr-Router admin-block fängt alle Admin-Pfade auf websecure für jeden Host ab und hat die
  höchste Priorität.

Nur Standardbibliothek (CI und Host haben kein PyYAML); die dynamische Datei wird deshalb nur über
die hier bekannten Zeilen gelesen.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ADMIN_PATHS = ["/admin", "/admin/", "/admin/login", "/admin/tenants", "/api/admin", "/api/admin/auth/login",
               "/api/admin/auth/oidc/public-config", "/api/admin/tenants/import"]
METHODS = ["GET", "POST"]


# ── Mini-Interpreter für Traefik-Regeln ─────────────────────────────────────────────────────

_TOKEN = re.compile(r"\s*(?:(&&|\|\||!|\(|\))|([A-Za-z]+)\(\s*`([^`]*)`\s*\))")


def _tokens(rule: str) -> list:
    out, pos = [], 0
    rule = rule.strip()
    while pos < len(rule):
        match = _TOKEN.match(rule, pos)
        if not match:
            raise ValueError(f"Regel nicht verstanden bei {rule[pos:]!r}: {rule}")
        out.append(match.group(1) or (match.group(2), match.group(3)))
        pos = match.end()
        while pos < len(rule) and rule[pos].isspace():
            pos += 1
    return out


def matches(rule: str, host: str, path: str, method: str) -> bool:
    tokens = _tokens(rule)
    index = 0

    def atom() -> bool:
        nonlocal index
        token = tokens[index]
        index += 1
        if token == "!":
            return not atom()
        if token == "(":
            value = disjunction()
            assert tokens[index] == ")", rule
            index += 1
            return value
        name, arg = token
        if name == "Host":
            return host.lower() == arg.lower()
        if name == "PathPrefix":
            return path.startswith(arg)
        if name == "Path":
            return path == arg
        if name == "Method":
            return method == arg
        raise ValueError(f"Matcher {name} unbekannt: {rule}")

    def conjunction() -> bool:
        nonlocal index
        value = atom()
        while index < len(tokens) and tokens[index] == "&&":
            index += 1
            value = atom() and value
        return value

    def disjunction() -> bool:
        nonlocal index
        value = conjunction()
        while index < len(tokens) and tokens[index] == "||":
            index += 1
            value = conjunction() or value
        return value

    result = disjunction()
    assert index == len(tokens), rule
    return result


# ── Router aus Compose-Labels ───────────────────────────────────────────────────────────────

def label_routers(services: dict) -> dict:
    routers: dict = {}
    for service_name, service in services.items():
        labels = service.get("labels") or {}
        if isinstance(labels, list):
            labels = dict(item.split("=", 1) for item in labels)
        for key, value in labels.items():
            match = re.match(r"traefik\.http\.routers\.([^.]+)\.(.+)$", key)
            if match:
                router = routers.setdefault(match.group(1), {"_service": service_name})
                router[match.group(2).lower()] = value
    return routers


def dynamic_block_router() -> dict:
    text = (REPO / "infra/traefik/dynamic/admin-isolation.yml").read_text(encoding="utf-8")
    rule = re.search(r'^\s+rule: "(.+)"$', text, re.M).group(1)
    priority = int(re.search(r"^\s+priority: (\d+)$", text, re.M).group(1))
    entrypoints = re.search(r"entryPoints:\n((?:\s+- \S+\n)+)", text).group(1).split()
    return {"rule": rule, "priority": priority, "entrypoints": [e for e in entrypoints if e != "-"]}


def main() -> None:
    config = json.load(sys.stdin)
    services = config["services"]
    env = services["backend"]["environment"]
    domains = {
        "main": env["TRAEFIK_DOMAIN"],
        "admin": env["TRAEFIK_ADMIN_DOMAIN"],
        "abgabebox": env["TRAEFIK_ABGABEBOX_DOMAIN"],
    }
    docs = env.get("TRAEFIK_DOCS_DOMAIN")
    hosts = [*domains.values(), "verein.example.org", "x." + domains["admin"], docs or "docs.example"]
    assert all(domains.values()), domains

    routers = label_routers(services)
    assert routers, "keine Traefik-Router in den Labels"
    errors: list[str] = []
    max_other_priority = 0
    admin_routers = []
    for name, router in sorted(routers.items()):
        entrypoints = [e.strip() for e in router.get("entrypoints", "").split(",") if e.strip()]
        if not entrypoints:
            errors.append(f"{name}: keine entrypoints (hinge sonst an allen, auch adminsecure)")
            continue
        max_other_priority = max(max_other_priority, int(router.get("priority", "0") or 0))
        if "adminsecure" in entrypoints:
            admin_routers.append(name)
            if entrypoints != ["adminsecure"]:
                errors.append(f"{name}: Admin-Router auch auf {entrypoints}")
            if f"Host(`{domains['admin']}`)" not in router.get("rule", ""):
                errors.append(f"{name}: Admin-Router ohne Host(Admin-Domain): {router.get('rule')}")
            middlewares = [m.strip() for m in router.get("middlewares", "").split(",")]
            if "admin-gate@file" not in middlewares:
                errors.append(f"{name}: Admin-Router ohne admin-gate@file (Gate-Header)")
            continue
        for host in hosts:
            for path in ADMIN_PATHS:
                for method in METHODS:
                    if matches(router["rule"], host, path, method):
                        errors.append(f"{name} ({entrypoints}) matcht {method} {host}{path}")
                        break
    expected_admin = {"admin-api", "admin-auth", "tenant-import", "admin-frontend"}
    found_admin = {name.split("-", 1)[1] for name in admin_routers}
    if not expected_admin <= found_admin:
        errors.append(f"Admin-Router fehlen: {sorted(expected_admin - found_admin)}")

    block = dynamic_block_router()
    if block["entrypoints"] != ["websecure"]:
        errors.append(f"admin-block: entryPoints {block['entrypoints']} statt [websecure]")
    if block["priority"] <= max_other_priority:
        errors.append(f"admin-block: Priorität {block['priority']} nicht über {max_other_priority}")
    for host in hosts:
        for path in ADMIN_PATHS:
            if not matches(block["rule"], host, path, "GET"):
                errors.append(f"admin-block fängt {host}{path} nicht ab")
    for path in ["/", "/login", "/api/health", "/.well-known/acme-challenge/x", "/api/auth/login"]:
        if matches(block["rule"], domains["main"], path, "GET"):
            errors.append(f"admin-block sperrt fälschlich {path}")

    # Selbsttest des Interpreters: die alte Regel der Mandanten-Domains (SEC-AUTH-001) muss auffallen.
    assert matches("Host(`v.example`) && (PathPrefix(`/api`) || PathPrefix(`/docs`))", "v.example", "/api/admin/x", "GET")
    assert not matches("Host(`v.example`) && ((PathPrefix(`/api`) && !PathPrefix(`/api/admin`)) || PathPrefix(`/docs`))",
                       "v.example", "/api/admin/x", "GET")

    if errors:
        print("Admin-Isolation verletzt:", *errors, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    print(f"admin isolation (labels): ok - {len(routers)} Router, Admin-Router: {', '.join(sorted(admin_routers))}")


if __name__ == "__main__":
    main()
