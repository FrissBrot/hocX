// Gemeinsame Typen und reine Hilfsfunktionen für die Benutzer-Formulare in
// admin-user-management.tsx (globale Admin-Sicht, alle Mandanten) und
// user-management.tsx (mandanten-gebundene Sicht, nur der eigene Mandant).
//
// Jedes Konto gehört genau einem Mandanten und hat genau eine Rolle. Der Mandant wird nur
// beim Anlegen im globalen Admin-Formular gewählt; danach ist er fest.

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
  is_participant_account: boolean;
  // Leer im mandanten-gebundenen Formular: das Backend nimmt dort immer den eigenen Mandanten.
  tenant_id: string;
  role_code: string;
};

export const DEFAULT_ROLE_CODE = "reader";

/** Baut ein leeres Formular auf. `tenantId` nur im globalen Admin-Formular vorbelegen. */
export function emptyUserForm(tenantId = ""): UserFormState {
  return {
    first_name: "",
    last_name: "",
    display_name: "",
    email: "",
    password: "",
    preferred_language: "de",
    is_active: true,
    login_enabled: true,
    is_participant_account: false,
    tenant_id: tenantId,
    role_code: DEFAULT_ROLE_CODE
  };
}

/** Baut den PATCH/POST-Payload. Der Mandant wird nur beim Anlegen mitgeschickt. */
export function userFormToPayload(form: UserFormState) {
  return {
    first_name: form.first_name,
    last_name: form.last_name,
    display_name: form.display_name,
    email: form.email,
    preferred_language: form.preferred_language,
    is_active: form.is_active,
    login_enabled: form.login_enabled,
    role_code: form.role_code,
    ...(!form.id && form.tenant_id ? { tenant_id: form.tenant_id } : {}),
    ...(form.password ? { password: form.password } : {})
  };
}
