// Ereignisseite (/admin/security/events, 1.6, Design «hocX Sicherheit Ereignisse»): Filter in der URL
// (nur Codes, Pseudonym-Präfixe und Mandanten-ID - keine Namen) und Token-Eingabe «konto:…».
// Reine Hilfen, ohne React testbar.

export const EVENT_RANGES = ["1h", "24h", "7d", "14d"] as const;
export type EventRange = (typeof EVENT_RANGES)[number];
export const EVENT_OUTCOMES = ["success", "failure", "blocked", "challenged", "info"] as const;
export type EventOutcome = (typeof EVENT_OUTCOMES)[number];
export const EVENT_GROUPS = ["flat", "net", "subject"] as const;
export type EventGroup = (typeof EVENT_GROUPS)[number];
/** Pseudonym- und Länderfilter, die als Chip («Pivot») erscheinen. */
export const EVENT_PIVOTS = ["subject", "net", "device", "country"] as const;
export type EventPivot = (typeof EVENT_PIVOTS)[number];

export type EventFilters = {
  range: EventRange;
  outcome: EventOutcome | "";
  type: string;
  subject: string;
  net: string;
  device: string;
  country: string;
  tenant_id: string;
  group: EventGroup;
};

export const DEFAULT_EVENT_FILTERS: EventFilters = {
  range: "24h", outcome: "", type: "", subject: "", net: "", device: "", country: "", tenant_id: "", group: "flat",
};

const HEX_PREFIX = /^[0-9a-f]{4,32}$/;
const COUNTRY = /^[A-Z]{2}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidPivot(key: EventPivot, value: string): boolean {
  return key === "country" ? COUNTRY.test(value) : HEX_PREFIX.test(value);
}

/** Filter aus der URL; Ungültiges fällt auf den Standard zurück (nie ungeprüft ans Backend). */
export function eventFiltersFromParams(params: URLSearchParams, eventTypes: readonly string[]): EventFilters {
  const pick = <T extends string>(value: string | null, allowed: readonly T[], fallback: T): T =>
    value && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
  const filters: EventFilters = {
    range: pick(params.get("range"), EVENT_RANGES, "24h"),
    outcome: pick(params.get("outcome"), EVENT_OUTCOMES, "" as EventOutcome) as EventOutcome | "",
    type: pick(params.get("type"), eventTypes, ""),
    subject: "", net: "", device: "", country: "",
    tenant_id: UUID.test(params.get("tenant_id") ?? "") ? (params.get("tenant_id") as string) : "",
    group: pick(params.get("group"), EVENT_GROUPS, "flat"),
  };
  for (const key of EVENT_PIVOTS) {
    const value = params.get(key) ?? "";
    if (value && isValidPivot(key, value)) filters[key] = value;
  }
  return filters;
}

/** URL-Query (ohne Standardwerte); `event` = geöffnetes Ereignis. */
export function eventFiltersToParams(filters: EventFilters, event?: string | null): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters) as [keyof EventFilters, string][]) {
    if (value && value !== DEFAULT_EVENT_FILTERS[key]) params.set(key, value);
  }
  if (event && UUID.test(event)) params.set("event", event);
  return params;
}

/** API-Query für Liste, Histogramm und Gruppen (gleiche Filter). */
export function eventApiQuery(filters: EventFilters, extra: Record<string, string | number> = {}): URLSearchParams {
  const params = new URLSearchParams({ range: filters.range });
  if (filters.outcome) params.set("outcome", filters.outcome);
  if (filters.type) params.set("event_type", filters.type);
  if (filters.tenant_id) params.set("tenant_id", filters.tenant_id);
  for (const key of EVENT_PIVOTS) if (filters[key]) params.set(key, filters[key]);
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value));
  return params;
}

// Schlüssel der Token-Eingabe je Sprache: der Code und die übersetzten Namen (z. B. «konto», «netz»)
export type PivotAliases = Record<EventPivot, string[]>;

/** «konto:3f9a1c07» → { key: "subject", value: "3f9a1c07" }; null, wenn kein gültiger Token. */
export function parsePivotToken(input: string, aliases: PivotAliases): { key: EventPivot; value: string } | null {
  const match = /^\s*([^:\s]+)\s*:\s*(\S+)\s*$/.exec(input);
  if (!match) return null;
  const name = match[1].toLowerCase();
  const key = EVENT_PIVOTS.find((pivot) => pivot === name || aliases[pivot].some((alias) => alias.toLowerCase() === name));
  if (!key) return null;
  const value = key === "country" ? match[2].toUpperCase() : match[2].toLowerCase();
  return isValidPivot(key, value) ? { key, value } : null;
}

export type RiskLevel = "normal" | "moderate" | "high" | "critical";

/** Klassen wie backend risk.level_for mit den Standardschwellen 30/60/80 (nur Anzeige). */
export function riskLevel(score: number | null | undefined): RiskLevel | null {
  if (score === null || score === undefined) return null;
  if (score >= 80) return "critical";
  if (score >= 60) return "high";
  if (score >= 30) return "moderate";
  return "normal";
}
