// Vorfälle und Lagebild (/admin/security/incidents und /admin/security, 1.7). Reine Hilfen, ohne
// React testbar: URL-Zustand (nur Codes und die Vorfall-Nummer - keine Namen, keine Suchbegriffe),
// Anzeige der Nummer, Dauer, Status-Farben, Heatmap und Balkenhöhen.

import type { IncidentSeverity, IncidentStatus, SituationPoint } from "@/types/admin-security";

export const INCIDENT_STATUS_GROUPS = ["open", "new", "in_progress", "closed", "all"] as const;
export type IncidentStatusGroup = (typeof INCIDENT_STATUS_GROUPS)[number];
export const INCIDENT_STATUSES: readonly IncidentStatus[] = ["new", "in_progress", "resolved", "false_positive"];
export const INCIDENT_SEVERITIES: readonly IncidentSeverity[] = ["critical", "warning"];
export const INCIDENT_ASSIGNEE_FILTERS = ["all", "me", "none"] as const;
export type IncidentAssigneeFilter = (typeof INCIDENT_ASSIGNEE_FILTERS)[number];
export const INCIDENT_VIEWS = ["list", "board"] as const;
export type IncidentView = (typeof INCIDENT_VIEWS)[number];
export const SITUATION_RANGES = ["24h", "7d"] as const;
export type SituationRange = (typeof SITUATION_RANGES)[number];

export type IncidentFilters = {
  status: IncidentStatusGroup;
  severities: IncidentSeverity[];
  assignee: IncidentAssigneeFilter;
  view: IncidentView;
  page: number;
};

export const DEFAULT_INCIDENT_FILTERS: IncidentFilters = { status: "open", severities: [], assignee: "all", view: "list", page: 0 };

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

/** Vorfall-Nummer aus der URL («incident=42»); alles andere ist ungültig. */
export function parseIncidentId(value: string | null | undefined): number | null {
  if (!value || !/^[1-9][0-9]{0,15}$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

export function incidentFiltersFromParams(params: URLSearchParams): IncidentFilters {
  const severities = (params.get("severity") ?? "")
    .split(",")
    .filter((value): value is IncidentSeverity => (INCIDENT_SEVERITIES as readonly string[]).includes(value));
  const page = Number(params.get("page") ?? "0");
  return {
    status: pick(params.get("status"), INCIDENT_STATUS_GROUPS, "open"),
    severities: Array.from(new Set(severities)),
    assignee: pick(params.get("assignee"), INCIDENT_ASSIGNEE_FILTERS, "all"),
    view: pick(params.get("view"), INCIDENT_VIEWS, "list"),
    page: Number.isInteger(page) && page >= 0 && page < 10_000 ? page : 0,
  };
}

/** URL-Query ohne Standardwerte; `incident` = geöffneter Vorfall. */
export function incidentFiltersToParams(filters: IncidentFilters, incident?: number | null): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.status !== "open") params.set("status", filters.status);
  if (filters.severities.length) params.set("severity", [...filters.severities].sort().join(","));
  if (filters.assignee !== "all") params.set("assignee", filters.assignee);
  if (filters.view !== "list") params.set("view", filters.view);
  if (filters.page > 0) params.set("page", String(filters.page));
  if (incident) params.set("incident", String(incident));
  return params;
}

/** API-Query der Liste (Suchbegriff nur hier, nie in der Seiten-URL). */
export function incidentApiQuery(filters: IncidentFilters, { q, limit }: { q?: string; limit: number }): URLSearchParams {
  const params = new URLSearchParams({ status: filters.view === "board" ? "all" : filters.status, assignee: filters.assignee });
  for (const severity of filters.severities) params.append("severity", severity);
  const term = (q ?? "").trim();
  if (term && /^[A-Za-z0-9_#-]{1,40}$/.test(term)) params.set("q", term);
  params.set("limit", String(limit));
  params.set("offset", String(filters.view === "board" ? 0 : filters.page * limit));
  // Board ohne Mini-Verlauf (das Backend rechnet ihn je Zeile)
  if (filters.view === "board") params.set("spark", "false");
  return params;
}

/** «INC-0042» (wie im Design; ab 10 000 ohne führende Nullen). */
export function incidentLabel(id: number): string {
  return `INC-${String(id).padStart(4, "0")}`; // i18n-ok: feste Kennung, keine Sprache
}

export function isOpenStatus(status: IncidentStatus): boolean {
  return status === "new" || status === "in_progress";
}

export function statusVariant(status: IncidentStatus): "danger" | "warning" | "success" | "neutral" {
  return status === "new" ? "danger" : status === "in_progress" ? "warning" : status === "resolved" ? "success" : "neutral";
}

export function severityVariant(severity: IncidentSeverity): "danger" | "warning" {
  return severity === "critical" ? "danger" : "warning";
}

/** Sekunden → Tage/Stunden/Minuten (gerundet auf Minuten, mindestens 1 Minute bei > 0). */
export function durationParts(seconds: number): { days: number; hours: number; minutes: number } {
  const total = Math.max(0, Math.round(seconds / 60));
  const minutes = seconds > 0 ? Math.max(1, total) : 0;
  return { days: Math.floor(minutes / 1440), hours: Math.floor((minutes % 1440) / 60), minutes: minutes % 60 };
}

/** Dauer eines Vorfalls: bis zum Abschluss, sonst bis jetzt. */
export function incidentDurationSeconds(firstSeen: string, closedAt: string | null, now = Date.now()): number {
  const end = closedAt ? new Date(closedAt).getTime() : now;
  return Math.max(0, (end - new Date(firstSeen).getTime()) / 1000);
}

/** Veränderung zur Vorperiode in Prozent (null, wenn die Vorperiode 0 ist). */
export function percentChange(current: number, previous: number): number | null {
  if (previous <= 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}

export type HeatmapCell = { dow: number; hour: number; count: number; level: 0 | 1 | 2 | 3 | 4 };

/** 7 × 24 Zellen (Montag = 1) mit Stufe 0-4 (Wurzelskala, damit Grundrauschen neben Spitzen sichtbar bleibt). */
export function heatmapGrid(cells: { dow: number; hour: number; count: number }[]): { rows: HeatmapCell[][]; max: number } {
  const counts = new Map(cells.map((cell) => [`${cell.dow}:${cell.hour}`, cell.count]));
  const max = Math.max(0, ...cells.map((cell) => cell.count));
  const rows: HeatmapCell[][] = [];
  for (let dow = 1; dow <= 7; dow += 1) {
    const row: HeatmapCell[] = [];
    for (let hour = 0; hour < 24; hour += 1) {
      const count = counts.get(`${dow}:${hour}`) ?? 0;
      const level = count === 0 || max === 0 ? 0 : (Math.min(4, Math.max(1, Math.ceil(Math.sqrt(count / max) * 4))) as 1 | 2 | 3 | 4);
      row.push({ dow, hour, count, level });
    }
    rows.push(row);
  }
  return { rows, max };
}

export const SITUATION_SERIES = ["failures", "blocked", "challenged", "successes"] as const;
export type SituationSeries = (typeof SITUATION_SERIES)[number];

/** Höhen (Prozent) eines gestapelten Balkens, Wurzelskala über das Maximum aller sichtbaren Summen. */
export function stackedHeights(points: SituationPoint[], visible: readonly SituationSeries[]): Record<SituationSeries, number>[] {
  const total = (point: SituationPoint) => visible.reduce((sum, key) => sum + point[key], 0);
  const max = Math.max(1, ...points.map(total));
  return points.map((point) => {
    const sum = total(point);
    const height = sum ? Math.sqrt(sum / max) * 100 : 0;
    const result = { failures: 0, blocked: 0, challenged: 0, successes: 0 };
    for (const key of visible) result[key] = sum ? (point[key] / sum) * height : 0;
    return result;
  });
}

/** Position (Prozent) eines Zeitpunkts im Zeitraum, begrenzt auf 0-100. */
export function positionPercent(at: string, start: string, end: string): number {
  const from = new Date(start).getTime();
  const to = new Date(end).getTime();
  if (to <= from) return 0;
  return Math.min(100, Math.max(0, ((new Date(at).getTime() - from) / (to - from)) * 100));
}
