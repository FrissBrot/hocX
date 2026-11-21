// Abgeleiteter Mandantenstatus (Admin-Redesign §2 B). Es gibt kein Statusfeld im Datenmodell; die
// Regeln hier entsprechen den Server-Filtern in AdminTenantService.list_tenants (status=...).

export type TenantStatusKey = "active" | "readOnly" | "contractEnding" | "unverified";
export type TenantStatus = { key: TenantStatusKey; variant: "success" | "warning" | "danger" | "neutral" };

// Wie CONTRACT_ENDING_DAYS im Backend.
export const CONTRACT_ENDING_DAYS = 30;

type TenantLike = {
  read_only_features: string[];
  contract_ends_on: string | null;
  identity_verified_at?: string | null;
};

function isoToday(now: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return date.toISOString().slice(0, 10);
}

/** Alle zutreffenden Status; «aktiv» nur, wenn keine Einschränkung greift. Verifizierung wird nur
 *  bewertet, wenn das Feld geliefert wurde (undefined = unbekannt). */
export function deriveTenantStatus(tenant: TenantLike, now: Date = new Date()): TenantStatus[] {
  const result: TenantStatus[] = [];
  if (tenant.read_only_features.length > 0) result.push({ key: "readOnly", variant: "warning" });
  if (tenant.contract_ends_on && tenant.contract_ends_on < addDays(isoToday(now), CONTRACT_ENDING_DAYS)) {
    result.push({ key: "contractEnding", variant: "danger" });
  }
  if (tenant.identity_verified_at === null) result.push({ key: "unverified", variant: "neutral" });
  if (result.length === 0) result.push({ key: "active", variant: "success" });
  return result;
}
