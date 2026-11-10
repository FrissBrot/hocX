// Berechtigungen (RBAC) im Frontend - nur zur Benutzerführung. Das Backend prüft jede Aktion
// unabhängig (backend/app/core/security.py::require_permission). Keys, Bereiche und Modulbindung
// kommen aus permissions/catalog.json (generiert nach permissions.generated.ts). Bewusst ohne
// "use client": Server Components (page.tsx) entscheiden damit, was sie laden und zeigen.

import { FEATURES, type FeatureCode } from "@/lib/features.generated";
import { PERMISSIONS, type PermissionKey, type SystemRoleKey } from "@/lib/permissions.generated";
import type { RoleRef, SessionInfo } from "@/types/api";

export type { PermissionKey, SystemRoleKey } from "@/lib/permissions.generated";

const FEATURE_BY_PERMISSION = new Map(PERMISSIONS.map((permission) => [permission.key, permission.feature]));
const IMPLIES = new Map(PERMISSIONS.map((permission) => [permission.key, permission.implies]));

type PermissionSource = Pick<SessionInfo, "permissions" | "current_tenant"> | null | undefined;

const READ_PERMISSIONS = new Map(FEATURES.map((feature) => [feature.code, feature.readPermissions]));

export type FeatureAccess = "full" | "read_only" | "none";

/** Buchungsstand eines Features (permissions/features.json): voll, nach Downgrade nur lesend, nicht gebucht. */
export function featureAccess(session: Pick<SessionInfo, "current_tenant"> | null | undefined, code: FeatureCode): FeatureAccess {
  if (session?.current_tenant?.enabled_features?.includes(code)) return "full";
  if (session?.current_tenant?.read_only_features?.includes(code)) return "read_only";
  return "none";
}

/** Permission vorhanden und - falls an ein Modul gebunden - das Modul für den Mandanten gebucht;
 * Lese-Berechtigungen gelten auch im Nur-Lesen-Zustand nach einem Downgrade (dieselbe Regel wie
 * CurrentUser.can im Backend). */
export function can(session: PermissionSource, permission: PermissionKey): boolean {
  if (!session?.permissions?.includes(permission)) return false;
  const feature = FEATURE_BY_PERMISSION.get(permission) as FeatureCode | null | undefined;
  if (!feature) return true;
  const access = featureAccess(session, feature);
  return access === "full" || (access === "read_only" && (READ_PERMISSIONS.get(feature) ?? []).includes(permission));
}

/** Mindestens eine der Permissions. */
export function canAny(session: PermissionSource, ...permissions: PermissionKey[]): boolean {
  return permissions.some((permission) => can(session, permission));
}

/** Anzeigename einer Rolle: eigener Name oder die übersetzte Standardbezeichnung (nav.roles.*).
 * `t` ist der "nav"-Übersetzer - Hilfsfunktion ohne eigenen Hook (Muster app-shell-nav.ts). */
export function roleName(role: Pick<RoleRef, "name" | "system_key">, t: (key: string) => string): string {
  if (role.name) return role.name;
  if (role.system_key) return t(`roles.${role.system_key}`);
  return "";
}

/** Alle Rollen eines Kontos, alphabetisch, kommagetrennt. */
export function rolesLabel(roles: readonly Pick<RoleRef, "name" | "system_key">[] | null | undefined, t: (key: string) => string): string {
  return (roles ?? [])
    .map((role) => roleName(role, t))
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b))
    .join(", ");
}

/** Ergänzt die festen Implikationen des Katalogs (wie core/permissions.py::expand). */
export function expandPermissions(keys: Iterable<string>): Set<PermissionKey> {
  const result = new Set<PermissionKey>();
  const pending = [...keys].filter((key): key is PermissionKey => IMPLIES.has(key as PermissionKey));
  while (pending.length > 0) {
    const key = pending.pop() as PermissionKey;
    if (result.has(key)) continue;
    result.add(key);
    pending.push(...(IMPLIES.get(key) ?? []));
  }
  return result;
}

/** Kleinste Menge, deren Implikationen `keys` ergeben - für das Rollenformular (implizierte
 * Berechtigungen werden dort automatisch gesetzt statt einzeln angekreuzt). */
export function minimalPermissions(keys: Iterable<string>): Set<PermissionKey> {
  const all = expandPermissions(keys);
  const implied = new Set<PermissionKey>();
  for (const key of all) {
    for (const other of expandPermissions(IMPLIES.get(key) ?? [])) implied.add(other);
  }
  return new Set([...all].filter((key) => !implied.has(key)));
}

export function isSystemRoleKey(value: string | null | undefined): value is SystemRoleKey {
  return value === "admin" || value === "writer" || value === "kassier" || value === "reader";
}
