#!/usr/bin/env python3
"""Generiert den Berechtigungskatalog (RBAC) für Backend und Frontend aus permissions/catalog.json.

    python3 scripts/sync-permission-catalog.py            # generieren
    python3 scripts/sync-permission-catalog.py --check    # nur prüfen (Exit 1 bei Abweichung), für CI

permissions/catalog.json ist die einzige Quelle für Permission-Keys, Bereiche, Feature-Bindung,
MFA-Pflicht, feste Implikationen und die Standardrollen (analog zu element-types/registry.json,
siehe sync-element-types.py). Die generierten Dateien werden nie von Hand editiert. Hintergrund:
docs/RBAC_ARCHITECTURE_PROPOSAL.md.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "permissions/catalog.json"
TS_TARGET = ROOT / "frontend/lib/permissions.generated.ts"
PY_TARGET = ROOT / "backend/app/core/permissions_generated.py"

HEADER = "GENERATED FILE - do not edit by hand. Source of truth: permissions/catalog.json (repo root)."
REGEN = "Regenerate with: python3 scripts/sync-permission-catalog.py"

KEY_PATTERN = re.compile(r"^[a-z_]+\.[a-z_]+$")
# Buchbare Features: einzige Quelle permissions/features.json (sync-feature-catalog.py)
FEATURES = tuple(entry["code"] for entry in json.loads((ROOT / "permissions/features.json").read_text(encoding="utf-8"))["features"])
SYSTEM_ROLE_KEYS = ("admin", "writer", "kassier", "reader")


def load_source() -> dict:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    areas = data["areas"]
    keys: list[str] = []
    for entry in data["permissions"]:
        key = entry["key"]
        if not KEY_PATTERN.match(key):
            raise SystemExit(f"permissions/catalog.json: ungültiger Key {key!r}")
        if key in keys:
            raise SystemExit(f"permissions/catalog.json: doppelter Key {key!r}")
        if entry["area"] not in areas:
            raise SystemExit(f"permissions/catalog.json: unbekannter Bereich bei {key}")
        if entry["feature"] is not None and entry["feature"] not in FEATURES:
            raise SystemExit(f"permissions/catalog.json: unbekanntes Feature bei {key}")
        keys.append(key)
    for entry in data["permissions"]:
        unknown = [implied for implied in entry["implies"] if implied not in keys]
        if unknown:
            raise SystemExit(f"permissions/catalog.json: {entry['key']} impliziert unbekannte {unknown}")
    _check_acyclic(data["permissions"])
    role_keys = [role["key"] for role in data["system_roles"]]
    if tuple(role_keys) != SYSTEM_ROLE_KEYS:
        raise SystemExit(f"permissions/catalog.json: Standardrollen müssen {SYSTEM_ROLE_KEYS} sein")
    for role in data["system_roles"]:
        unknown = [key for key in role["permissions"] if key not in keys]
        if unknown:
            raise SystemExit(f"permissions/catalog.json: Rolle {role['key']} mit unbekannten {unknown}")
        if role["all_permissions"] != (role["key"] == "admin"):
            raise SystemExit("permissions/catalog.json: nur die Rolle admin hat all_permissions")
    return data


def _check_acyclic(permissions: list[dict]) -> None:
    graph = {entry["key"]: entry["implies"] for entry in permissions}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(key: str) -> None:
        if key in done:
            return
        if key in visiting:
            raise SystemExit(f"permissions/catalog.json: Implikationen bilden einen Zyklus bei {key}")
        visiting.add(key)
        for implied in graph[key]:
            visit(implied)
        visiting.discard(key)
        done.add(key)

    for key in graph:
        visit(key)


def _enum_name(key: str) -> str:
    return key.replace(".", "_").upper()


def render_py(data: dict) -> str:
    members = "\n".join(f'    {_enum_name(entry["key"])} = "{entry["key"]}"' for entry in data["permissions"])
    defs = "\n".join(
        "    P.{name}: PermissionDef(area={area}, feature={feature}, requires_mfa={mfa}, implies=({implies})),".format(
            name=_enum_name(entry["key"]),
            area=json.dumps(entry["area"]),
            feature=json.dumps(entry["feature"]) if entry["feature"] else "None",
            mfa="True" if entry["requires_mfa"] else "False",
            implies="".join(f"P.{_enum_name(implied)}, " for implied in entry["implies"]).rstrip(" "),
        )
        for entry in data["permissions"]
    )
    roles = "\n".join(
        "    {key}: frozenset({{{perms}}}),".format(
            key=json.dumps(role["key"]),
            perms=", ".join(f"P.{_enum_name(key)}" for key in role["permissions"]),
        )
        if not role["all_permissions"]
        else f'    {json.dumps(role["key"])}: frozenset(P),'
        for role in data["system_roles"]
    )
    areas = ", ".join(json.dumps(area) for area in data["areas"])
    return f'''# {HEADER}
# {REGEN}
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class P(StrEnum):
{members}


@dataclass(frozen=True)
class PermissionDef:
    area: str
    feature: str | None
    requires_mfa: bool
    implies: tuple[P, ...]


AREAS: tuple[str, ...] = ({areas},)

CATALOG: dict[P, PermissionDef] = {{
{defs}
}}

# Standardrollen je Mandant (tenant_role.system_key). "admin" hat immer alle Permissions, auch
# künftig neu hinzukommende - beim Laden ausgewertet, nicht über tenant_role_permission.
SYSTEM_ROLE_KEYS: tuple[str, ...] = {tuple(role["key"] for role in data["system_roles"])!r}
SYSTEM_ROLE_PERMISSIONS: dict[str, frozenset[P]] = {{
{roles}
}}
'''


def render_ts(data: dict) -> str:
    keys = " | ".join(json.dumps(entry["key"]) for entry in data["permissions"])
    areas = " | ".join(json.dumps(area) for area in data["areas"])
    rows = "\n".join(
        "  {{ key: {key}, area: {area}, feature: {feature}, requiresMfa: {mfa}, implies: [{implies}] }},".format(
            key=json.dumps(entry["key"]),
            area=json.dumps(entry["area"]),
            feature=json.dumps(entry["feature"]),
            mfa=json.dumps(entry["requires_mfa"]),
            implies=", ".join(json.dumps(implied) for implied in entry["implies"]),
        )
        for entry in data["permissions"]
    )
    roles = "\n".join(
        "  {key}: {perms},".format(
            key=role["key"],
            perms="PERMISSION_KEYS" if role["all_permissions"] else "[" + ", ".join(json.dumps(key) for key in role["permissions"]) + "]",
        )
        for role in data["system_roles"]
    )
    return f"""// {HEADER}
// {REGEN}

export type PermissionKey = {keys};
export type PermissionArea = {areas};
export type PermissionFeature = {" | ".join(json.dumps(f) for f in FEATURES)};
export type SystemRoleKey = {" | ".join(json.dumps(k) for k in SYSTEM_ROLE_KEYS)};

export type PermissionInfo = {{
  key: PermissionKey;
  area: PermissionArea;
  feature: PermissionFeature | null;
  requiresMfa: boolean;
  implies: PermissionKey[];
}};

export const PERMISSION_AREAS: readonly PermissionArea[] = [{", ".join(json.dumps(area) for area in data["areas"])}];

export const PERMISSIONS: readonly PermissionInfo[] = [
{rows}
];

export const PERMISSION_KEYS: readonly PermissionKey[] = PERMISSIONS.map((permission) => permission.key);

export const SYSTEM_ROLE_KEYS: readonly SystemRoleKey[] = [{", ".join(json.dumps(k) for k in SYSTEM_ROLE_KEYS)}];

export const SYSTEM_ROLE_PERMISSIONS: Readonly<Record<SystemRoleKey, readonly PermissionKey[]>> = {{
{roles}
}};
"""


def consistency_problems(data: dict) -> list[str]:
    """Was der Katalog allein nicht garantiert (CLAUDE.md, Abschnitt RBAC "Neue Berechtigung"):
    Übersetzungen in allen Locales, eine Migration, die den Key in die Tabelle permission einfügt,
    und mindestens eine Verwendung im Backend - eine Berechtigung, die nichts prüft, ist ein
    Schalter ohne Wirkung und täuscht Mandanten-Admins."""
    problems: list[str] = []
    locales = json.loads((ROOT / "i18n/locales.json").read_text(encoding="utf-8"))["locales"]
    for locale in locales:
        path = ROOT / f"frontend/messages/{locale}/roles.json"
        messages = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        for area in data["areas"]:
            if not messages.get("areas", {}).get(area):
                problems.append(f"{path.relative_to(ROOT)}: areas.{area} fehlt")
        for entry in data["permissions"]:
            group, action = entry["key"].split(".")
            texts = messages.get("permissions", {}).get(group, {}).get(action, {})
            for field in ("label", "description"):
                if not texts.get(field):
                    problems.append(f"{path.relative_to(ROOT)}: permissions.{entry['key']}.{field} fehlt")
    migrations = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "backend/alembic/versions").glob("*.py"))
    backend = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "backend/app").rglob("*.py") if path != PY_TARGET
    )
    for entry in data["permissions"]:
        key = entry["key"]
        if f'"{key}"' not in migrations and f"'{key}'" not in migrations:
            problems.append(f"{key}: keine Migration fügt den Key in die Tabelle permission ein")
        if f"P.{key.replace('.', '_').upper()}" not in backend:
            problems.append(f"{key}: wird im Backend nirgends geprüft (P.{key.replace('.', '_').upper()})")
    return problems


def main() -> int:
    check = "--check" in sys.argv[1:]
    data = load_source()
    problems = consistency_problems(data)
    if problems:
        for problem in problems:
            print(problem)
        print("Berechtigungskatalog: unvollständig (siehe CLAUDE.md, Abschnitt Berechtigungen / RBAC)")
        return 1
    outputs = {TS_TARGET: render_ts(data), PY_TARGET: render_py(data)}
    stale = [path for path, content in outputs.items() if not path.exists() or path.read_text(encoding="utf-8") != content]
    if check:
        if stale:
            for path in stale:
                print(f"veraltet: {path.relative_to(ROOT)}")
            print("Berechtigungskatalog: veraltet - python3 scripts/sync-permission-catalog.py ausführen")
            return 1
        print("Berechtigungskatalog: ok")
        return 0
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"geschrieben: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
