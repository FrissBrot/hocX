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
  verb: string; // Vorgang (1.6, Token «vorgang:»), Code wie AUDIT_VERBS
};

/** Vorgänge, nach denen das Backend filtert (admin.py::AUDIT_VERB_PATTERNS). */
export const AUDIT_VERBS = ["deleted", "created", "updated", "viewed", "exported", "restored", "revoked", "published", "login", "loginFailed"] as const;
export type AuditVerbFilter = (typeof AUDIT_VERBS)[number];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** In der URL stehen nur IDs und Codes (DESIGN §11): Mandanten-/Akteur-ID, Bereichs- und Aktionscodes,
 * Quelle als Präfix des gekürzten Hashes (Pseudonym), Entitätstyp/-ID. */
export const AUDIT_URL_CONFIG: ServerTableConfig<AuditFilters> = {
  path: "/api/admin/audit-log",
  pageSize: 40,
  defaults: { range: "7d", tenant_id: "", action: "", outcome: "", area: "", actor_kind: "", actor_id: "", entity_type: "", entity_id: "", source: "", verb: "" },
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
    verb: (value) => (AUDIT_VERBS as readonly string[]).includes(value),
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
  for (const key of ["range", "tenant_id", "outcome", "actor_kind", "actor_id", "entity_type", "entity_id", "source", "verb"] as const) {
    if (filters[key]) params.set(key, filters[key]);
  }
  // Ein noch nicht übernommener Token («quelle:26…») ist kein Aktions-Präfix
  if (filters.action.trim() && !filters.action.includes(":")) params.set("action", filters.action.trim());
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

// ── Gespeicherte Ansichten und Token-Suche (1.6, Design «hocX Audit-Log») ─────────────────────

export const AUDIT_VIEWS = ["all", "failures", "auth", "deletions", "admin", "privacy"] as const;
export type AuditView = (typeof AUDIT_VIEWS)[number];

/** Filter je Ansicht (Zeitraum und Mandant bleiben, alles andere wird ersetzt). */
export const AUDIT_VIEW_FILTERS: Record<AuditView, Partial<AuditFilters>> = {
  all: {},
  failures: { outcome: "failure" },
  auth: { area: "auth" },
  deletions: { verb: "deleted" },
  admin: { actor_kind: "admin" },
  privacy: { area: "privacy" },
};

export function applyAuditView(filters: AuditFilters, view: AuditView, defaults: AuditFilters): AuditFilters {
  return { ...defaults, range: filters.range, tenant_id: filters.tenant_id, ...AUDIT_VIEW_FILTERS[view] };
}

/** Welche Ansicht genau den aktuellen Filtern entspricht (sonst null). */
export function activeAuditView(filters: AuditFilters, defaults: AuditFilters): AuditView | null {
  return AUDIT_VIEWS.find((view) => {
    const expected = applyAuditView(filters, view, defaults);
    return (Object.keys(expected) as (keyof AuditFilters)[]).every((key) => expected[key] === filters[key]);
  }) ?? null;
}

export const AUDIT_TOKEN_KEYS = ["person", "tenant", "source", "action", "verb"] as const;
export type AuditTokenKey = (typeof AUDIT_TOKEN_KEYS)[number];

export type AuditTokenResult = {
  /** Erkannte Filter (Quelle, Aktion, Vorgang) */
  patch: Partial<AuditFilters>;
  /** Freitext ohne Tokens (bleibt Aktions-Präfix wie bisher) */
  rest: string;
  /** «person:» bzw. «mandant:» verlangen eine Auswahl (Picker) - nie ein Name in der URL */
  pick: "person" | "tenant" | null;
  /** Tokens, die nicht verstanden wurden */
  invalid: string[];
};

/** «quelle:26ca aktion:protocol vorgang:gelöscht» → Filter. `aliases` je Schlüssel (Code + Übersetzung),
 * `verbAliases` übersetzte Vorgangsnamen → Code. Personen- und Mandantennamen werden nie übernommen. */
export function parseAuditTokens(
  input: string,
  aliases: Record<AuditTokenKey, string[]>,
  verbAliases: Record<string, AuditVerbFilter>,
): AuditTokenResult {
  const result: AuditTokenResult = { patch: {}, rest: "", pick: null, invalid: [] };
  const rest: string[] = [];
  for (const token of input.trim().split(/\s+/).filter(Boolean)) {
    const index = token.indexOf(":");
    if (index <= 0) {
      rest.push(token);
      continue;
    }
    const name = token.slice(0, index).toLowerCase();
    const value = token.slice(index + 1);
    const key = AUDIT_TOKEN_KEYS.find((candidate) => candidate === name || aliases[candidate].some((alias) => alias.toLowerCase() === name));
    if (!key) {
      result.invalid.push(token);
      continue;
    }
    if (key === "person" || key === "tenant") {
      result.pick = key;
      continue;
    }
    if (key === "source" && /^[0-9a-f]{4,64}$/.test(value.toLowerCase())) result.patch.source = value.toLowerCase();
    else if (key === "action" && /^[a-z0-9_.]{1,100}$/i.test(value)) result.patch.action = value;
    else if (key === "verb") {
      const code = (AUDIT_VERBS as readonly string[]).includes(value) ? (value as AuditVerbFilter) : verbAliases[value.toLowerCase()];
      if (code) result.patch.verb = code;
      else result.invalid.push(token);
    } else result.invalid.push(token);
  }
  // Nach «person:»/«mandant:» ist übriger Freitext meist der Rest eines Namens: verwerfen statt als
  // Aktions-Präfix an Backend und URL zu geben
  result.rest = result.pick ? "" : rest.join(" ");
  return result;
}
