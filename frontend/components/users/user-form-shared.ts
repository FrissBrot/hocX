import type { SystemRoleKey } from "@/lib/permissions";
import type { RoleRef } from "@/types/api";

// Gemeinsame Typen und reine Hilfsfunktionen für die Benutzer-Formulare in
// admin-user-management.tsx (globale Admin-Sicht, alle Mandanten) und
// user-management.tsx (mandanten-gebundene Sicht, nur der eigene Mandant).
//
// Jedes Konto gehört genau einem Mandanten und hat eine oder mehrere Rollen dieses Mandanten
// (RBAC). Der Mandant wird nur beim Anlegen im globalen Admin-Formular gewählt; danach ist er
// fest. Die mandanten-gebundene Sicht setzt Rollen per ID (role_ids), das Plattform-Admin-Panel
// setzt genau eine Standardrolle (system_role) - eigene Rollen verwaltet der Mandant selbst.

export type UserFormState = {
  id?: string;
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  password: string;
  preferred_language: string;
  is_active: boolean;
  login_enabled: boolean;
  // Leer im mandanten-gebundenen Formular: das Backend nimmt dort immer den eigenen Mandanten.
  tenant_id: string;
  role_ids: string[];
  system_role: SystemRoleKey;
};

export const DEFAULT_SYSTEM_ROLE: SystemRoleKey = "reader";

/** ID der Standardrolle "reader" eines Mandanten - Vorbelegung für neue Konten (wie im Backend). */
export function defaultRoleIds(roles: readonly Pick<RoleRef, "id" | "system_key">[]): string[] {
  const reader = roles.find((role) => role.system_key === DEFAULT_SYSTEM_ROLE);
  return reader ? [reader.id] : [];
}

/** Höchste Standardrolle eines Kontos (für die Einzelauswahl im Plattform-Admin-Panel). */
export function primarySystemRole(roles: readonly Pick<RoleRef, "system_key">[]): SystemRoleKey {
  const order: SystemRoleKey[] = ["admin", "writer", "kassier", "reader"];
  return order.find((key) => roles.some((role) => role.system_key === key)) ?? DEFAULT_SYSTEM_ROLE;
}

// Backend minimum (UserCreate.password, backend/app/schemas/user.py) - kept in sync here so
// the disabled-submit check below matches what the API actually accepts.
const MIN_PASSWORD_LENGTH = 12;

// Treibt das disabled-Attribut des Speichern-Buttons statt natives `required` (Design-Regeln
// Abschnitt 8) - natives `required` liess den Browser bei leerem Absenden eine englische
// Meldung ("Please fill out this field.") zeigen, UX-Audit-Befund F5.
export function isUserFormValid(form: UserFormState, { requireTenant = false }: { requireTenant?: boolean } = {}): boolean {
  const isEdit = Boolean(form.id);
  return (
    form.display_name.trim() !== "" &&
    (!form.login_enabled || form.email.trim() !== "") &&
    (!form.login_enabled || (isEdit && form.password === "") || form.password.length >= MIN_PASSWORD_LENGTH) &&
    (!requireTenant || isEdit || form.tenant_id !== "")
  );
}

/** Baut ein leeres Formular auf. `tenantId` nur im globalen Admin-Formular vorbelegen. */
export function emptyUserForm(tenantId = "", roleIds: string[] = []): UserFormState {
  return {
    first_name: "",
    last_name: "",
    display_name: "",
    email: "",
    password: "",
    preferred_language: "de",
    is_active: true,
    login_enabled: false,
    tenant_id: tenantId,
    role_ids: roleIds,
    system_role: DEFAULT_SYSTEM_ROLE
  };
}

/** Baut den PATCH/POST-Payload. Der Mandant wird nur beim Anlegen mitgeschickt; "tenant"
 * schickt die Rollen-IDs, "platform" die eine Standardrolle. */
export function userFormToPayload(form: UserFormState, mode: "tenant" | "platform" = "tenant") {
  return {
    first_name: form.first_name,
    last_name: form.last_name,
    display_name: form.display_name,
    email: form.email.trim() || null,
    preferred_language: form.preferred_language,
    is_active: form.is_active,
    login_enabled: form.login_enabled,
    ...(mode === "platform" ? { system_role: form.system_role } : { role_ids: form.role_ids }),
    ...(!form.id && form.tenant_id ? { tenant_id: form.tenant_id } : {}),
    ...(form.password ? { password: form.password } : {})
  };
}
