// Plattform-Audit-Log (/admin/security/audit, Design «hocX Audit-Log», 1.5.1): reine Hilfen für
// Filter (URL ↔ API), Gruppierung nach Tagen, J/K-Auswahl und Vorher/Nachher - ohne React testbar.

import { AUDIT_AREAS, auditAreaCategories, type AuditArea } from "@/lib/audit-labels";
import type { ServerTableConfig } from "@/lib/admin/use-server-table";

export const AUDIT_RANGES = ["24h", "7d", "30d", "90d"] as const;
export type AuditRange = (typeof AUDIT_RANGES)[number];

export type AuditFilters = {
  range: string;
  tenant_id: string;
  action: string;
  outcome: string;
  area: string; // Bereichs-Codes, kommagetrennt (z. B. "auth,privacy")
  actor_kind: string;
  actor_id: string;
  entity_type: string;
  entity_id: string;
  source: string;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** In der URL stehen nur IDs und Codes (DESIGN §11): Mandanten-/Akteur-ID, Bereichs- und Aktionscodes,
 * Quelle als Präfix des gekürzten Hashes (Pseudonym), Entitätstyp/-ID. */
export const AUDIT_URL_CONFIG: ServerTableConfig<AuditFilters> = {
  path: "/api/admin/audit-log",
  pageSize: 40,
  defaults: { range: "7d", tenant_id: "", action: "", outcome: "", area: "", actor_kind: "", actor_id: "", entity_type: "", entity_id: "", source: "" },
  textKey: "action",
  syncTextToUrl: true,
  validate: {
    range: (value) => (AUDIT_RANGES as readonly string[]).includes(value),
    tenant_id: (value) => UUID.test(value),
    actor_id: (value) => UUID.test(value),
    outcome: (value) => value === "success" || value === "failure",
    area: (value) => value.split(",").every((code) => (AUDIT_AREAS as readonly string[]).includes(code)),
    actor_kind: (value) => ["admin", "user", "system"].includes(value),
    entity_type: (value) => /^[a-z0-9_.]{1,64}$/.test(value),
    entity_id: (value) => /^\d{1,18}$/.test(value),
    action: (value) => /^[a-z0-9_.]{0,100}$/i.test(value),
    source: (value) => /^[0-9a-f]{4,64}$/.test(value),
  },
};

export function selectedAreas(filters: Pick<AuditFilters, "area">): AuditArea[] {
  return filters.area ? (filters.area.split(",").filter((code) => (AUDIT_AREAS as readonly string[]).includes(code)) as AuditArea[]) : [];
}

export function toggleArea(filters: Pick<AuditFilters, "area">, area: AuditArea): string {
  const current = selectedAreas(filters);
  const next = current.includes(area) ? current.filter((item) => item !== area) : [...current, area];
  return AUDIT_AREAS.filter((item) => next.includes(item)).join(",");
}

/** API-Query: gleiche Filter für Liste und Zeitleiste; Bereiche als Kategorien (`category=` je Code). */
export function auditApiQuery(filters: AuditFilters, extra: Record<string, string | number> = {}): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of ["range", "tenant_id", "outcome", "actor_kind", "actor_id", "entity_type", "entity_id", "source"] as const) {
    if (filters[key]) params.set(key, filters[key]);
  }
  if (filters.action.trim()) params.set("action", filters.action.trim());
  for (const area of selectedAreas(filters)) for (const category of auditAreaCategories(area)) params.append("category", category);
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value));
  return params;
}

export function hasActiveAuditFilter(filters: AuditFilters): boolean {
  return Object.entries(filters).some(([key, value]) => key !== "range" && value !== "");
}

export type DayGroup<T> = { key: string; date: Date; entries: T[]; failures: number };

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** Einträge (neueste zuerst) nach Kalendertag der Anzeige gruppieren, Reihenfolge bleibt. */
export function groupByDay<T extends { created_at: string; outcome: string }>(entries: T[]): DayGroup<T>[] {
  const groups: DayGroup<T>[] = [];
  for (const entry of entries) {
    const date = new Date(entry.created_at);
    const key = dayKey(date);
    let group = groups.at(-1);
    if (!group || group.key !== key) {
      group = { key, date: new Date(date.getFullYear(), date.getMonth(), date.getDate()), entries: [], failures: 0 };
      groups.push(group);
    }
    group.entries.push(entry);
    if (entry.outcome === "failure") group.failures += 1;
  }
  return groups;
}

/** «Heute»/«Gestern»/sonst null - relativ zum heutigen Tag der Anzeige. */
export function relativeDay(date: Date, now: Date = new Date()): "today" | "yesterday" | null {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const diff = Math.round((today - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) / 86_400_000);
  return diff === 0 ? "today" : diff === 1 ? "yesterday" : null;
}

/** J/K: nächster bzw. vorheriger Eintrag; ohne Auswahl der erste. */
export function stepSelection(ids: number[], current: number | null, direction: 1 | -1): number | null {
  if (ids.length === 0) return null;
  const index = current === null ? -1 : ids.indexOf(current);
  if (index < 0) return ids[0];
  return ids[Math.max(0, Math.min(ids.length - 1, index + direction))];
}

export type AuditDiff = { field: string | null; before: string; after: string };

/** Vorher/Nachher nur, wenn die Details beides enthalten (sonst null - nichts erfinden). */
export function auditDiff(details: Record<string, unknown> | null | undefined): AuditDiff | null {
  if (!details || !("before" in details) || !("after" in details)) return null;
  const field = typeof details.field === "string" ? details.field : null;
  return { field, before: JSON.stringify(details.before), after: JSON.stringify(details.after) };
}
