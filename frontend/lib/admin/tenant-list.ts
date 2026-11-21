// Mandantenliste im Plattform-Admin: Sortierung/Filter als URL-Zustand (Admin-Redesign §5.1).
// Reines Modul (kein "use client"), damit Server-Seite und Client-Komponente dieselbe Logik nutzen.

// Ab diesem Anteil wird der Speicherbalken in der Liste als Warnung eingefärbt (und Filter «Speicher ≥85 %»).
export const STORAGE_WARNING_RATIO = 0.85;

export type TenantSortKey = "name" | "created" | "users" | "storage" | "plan";
export type TenantStatusFilter = "" | "read_only" | "contract_ending" | "unverified";
export type TenantListView = { sort: TenantSortKey; dir: "asc" | "desc"; status: TenantStatusFilter; storageFull: boolean; q: string };

export const TENANT_SORT_KEYS: TenantSortKey[] = ["name", "created", "users", "storage", "plan"];
export const TENANT_STATUS_FILTERS: TenantStatusFilter[] = ["read_only", "contract_ending", "unverified"];

export const DEFAULT_TENANT_VIEW: TenantListView = { sort: "name", dir: "asc", status: "", storageFull: false, q: "" };

/** Query-String der Liste: dieselben Parameter für API und Browser-URL (ohne Standardwerte). */
export function tenantListQuery(view: TenantListView, plan: string): URLSearchParams {
  const params = new URLSearchParams();
  if (view.q.trim()) params.set("q", view.q.trim());
  if (plan) params.set("plan", plan);
  if (view.sort !== "name") params.set("sort", view.sort);
  if (view.dir !== "asc") params.set("dir", view.dir);
  if (view.status) params.set("status", view.status);
  if (view.storageFull) params.set("storage_min_ratio", String(STORAGE_WARNING_RATIO));
  return params;
}

/** Unbekannte Werte aus der URL fallen auf den Standard zurück (nie ungeprüft ans Backend). */
export function tenantViewFromParams(params: Record<string, string | undefined>): TenantListView {
  return {
    q: (params.q ?? "").slice(0, 200),
    sort: TENANT_SORT_KEYS.includes(params.sort as TenantSortKey) ? (params.sort as TenantSortKey) : DEFAULT_TENANT_VIEW.sort,
    dir: params.dir === "desc" ? "desc" : "asc",
    status: TENANT_STATUS_FILTERS.includes(params.status as TenantStatusFilter) ? (params.status as TenantStatusFilter) : "",
    storageFull: params.storage_min_ratio !== undefined,
  };
}
