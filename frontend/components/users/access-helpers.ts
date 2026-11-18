import { expandPermissions } from "@/lib/permissions";
import { PERMISSIONS } from "@/lib/permissions.generated";
import type { RoleRead } from "@/types/api";

const MFA_PERMISSIONS = new Set<string>(PERMISSIONS.filter((permission) => permission.requiresMfa).map((permission) => permission.key));

/** Verlangt eine der Rollen MFA (Administrations-Berechtigung, wie backend permissions.requires_mfa)? */
export function rolesNeedMfa(roles: readonly RoleRead[], roleIds: Iterable<string>): boolean {
  const wanted = new Set(roleIds);
  return roles.some((role) => wanted.has(role.id) && [...expandPermissions(role.permissions)].some((key) => MFA_PERMISSIONS.has(key)));
}

/** Einzelne Rolle mit MFA-Pflicht (Badge «MFA» in Rollenlisten). */
export function roleNeedsMfa(role: RoleRead): boolean {
  return [...expandPermissions(role.permissions)].some((key) => MFA_PERMISSIONS.has(key));
}

export type MfaState = "active" | "missing" | "optional";

/** MFA-Status eines Logins für die Anzeige: eingerichtet, Pflicht aber fehlt, freiwillig. */
export function mfaState(hasFactor: boolean, required: boolean): MfaState {
  if (hasFactor) return "active";
  return required ? "missing" : "optional";
}
