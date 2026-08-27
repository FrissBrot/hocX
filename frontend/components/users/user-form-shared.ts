// Gemeinsame Typen und reine Hilfsfunktionen für die Benutzer-Formulare in
// admin-user-management.tsx (globale Admin-Sicht, alle Mandanten) und
// user-management.tsx (mandanten-gebundene Sicht, nur verwaltbare Mandanten).
//
// Beide Formulare unterscheiden sich bewusst in Verhalten und Umfang (Merge-Dialog nur
// im Admin-Formular, Login-Aktivierung/Löschen nur im mandanten-gebundenen Formular,
// unterschiedliche Vorbefüllung neuer Mandantenrollen) - hier landet nur der Teil, der
// in beiden Komponenten identisch war.

export type MembershipEntry = {
  tenant_id: string;
  role_code: string;
};

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
  memberships: MembershipEntry[];
  // Auswahlfelder des "Mandantenrolle hinzufügen"-Reglers. In den Ursprungsdateien hießen
  // diese Felder je nach Komponente addTenantId/addRoleCode bzw. selectedTenantId/selectedRoleCode -
  // rein interner State, daher hier ohne Verhaltensänderung auf einen gemeinsamen Namen vereinheitlicht.
  pickerTenantId: string;
  pickerRoleCode: string;
};

type TenantLike = { id: string };

/**
 * Baut ein leeres Formular auf. `prefillMembership` steuert den einzigen echten
 * Verhaltensunterschied zwischen den beiden Aufrufern: Das mandanten-gebundene Formular
 * (user-management.tsx) legt für einen neuen Benutzer sofort eine Mitgliedschaft im ersten
 * verwaltbaren Mandanten an, das globale Admin-Formular (admin-user-management.tsx) startet
 * bewusst ohne vorbefüllte Mitgliedschaft.
 */
export function emptyUserForm<T extends TenantLike>(
  tenants: T[],
  options: { prefillMembership?: boolean } = {}
): UserFormState {
  const firstTenant = tenants[0];
  const prefillMembership = options.prefillMembership ?? false;
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
    memberships: prefillMembership && firstTenant ? [{ tenant_id: firstTenant.id, role_code: "reader" }] : [],
    pickerTenantId: firstTenant ? String(firstTenant.id) : "",
    pickerRoleCode: "reader"
  };
}

/** Baut den PATCH/POST-Payload, der in beiden Formularen identisch zusammengesetzt wurde. */
export function userFormToPayload(form: UserFormState) {
  return {
    first_name: form.first_name,
    last_name: form.last_name,
    display_name: form.display_name,
    email: form.email,
    preferred_language: form.preferred_language,
    is_active: form.is_active,
    login_enabled: form.login_enabled,
    memberships: form.memberships.map((membership) => ({
      tenant_id: membership.tenant_id,
      role_code: membership.role_code,
      is_active: true
    })),
    ...(form.password ? { password: form.password } : {})
  };
}

/**
 * Fügt eine Mitgliedschaft hinzu bzw. aktualisiert sie - je nach Modus mit dem im Audit
 * beschriebenen unterschiedlichen Verhalten:
 *  - "add" (admin-user-management.tsx): hängt immer eine neue Mitgliedschaft an, ohne
 *    auf einen bereits vorhandenen Eintrag für denselben Mandanten zu prüfen (das UI
 *    verhindert Duplikate bereits, indem bereits zugewiesene Mandanten aus der Auswahl
 *    entfernt werden) - unverändert gegenüber der ursprünglichen addMembership().
 *  - "upsert" (user-management.tsx): ersetzt eine vorhandene Mitgliedschaft für denselben
 *    Mandanten, statt einen zweiten Eintrag anzulegen - unverändert gegenüber der
 *    ursprünglichen upsertMembership().
 */
export function addOrUpsertMembership(
  memberships: MembershipEntry[],
  tenantId: string,
  roleCode: string,
  mode: "add" | "upsert"
): MembershipEntry[] {
  const next =
    mode === "upsert" && memberships.some((membership) => membership.tenant_id === tenantId)
      ? memberships.map((membership) =>
          membership.tenant_id === tenantId ? { tenant_id: tenantId, role_code: roleCode } : membership
        )
      : [...memberships, { tenant_id: tenantId, role_code: roleCode }];
  // Ids are opaque UUIDs now (no natural numeric order) - sort just keeps display order
  // stable/deterministic, not meaningful by itself.
  return next.sort((a, b) => a.tenant_id.localeCompare(b.tenant_id));
}

export function removeMembershipEntry(memberships: MembershipEntry[], tenantId: string): MembershipEntry[] {
  return memberships.filter((membership) => membership.tenant_id !== tenantId);
}

export function buildTenantNameMap<T extends TenantLike & { name: string }>(tenants: T[]): Map<string, string> {
  return new Map(tenants.map((tenant) => [tenant.id, tenant.name]));
}
