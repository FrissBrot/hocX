// Gemeinsamer Terminfilter - Gegenstück zu backend/app/services/event_filter.py (gleiche
// Logik, gleiches Speicherformat). Genutzt von Wiederholung «Pro Termin» (repeat_event_filter),
// Terminliste und Sitzungsdatum (event_filter), Matrix-Automodus (auto_source.event_filter) und
// Matrixzeilen vom Typ "events"/"7" (row_config.event_filter).
import { eventMatchesCycleFilter } from "@/lib/utils/cycle";

export type EventRangeMode = "all" | "future" | "past" | "window";

export type EventFilter = {
  /** Tag enthält einen der Werte (Gross/klein egal). */
  tags: string[];
  /** Titel enthält. */
  title: string;
  /** Beschreibung enthält. */
  description: string;
  range: { mode: EventRangeMode; start_days: number; end_days: number };
  /** null = kein Zyklus-Filter. config_id null = Zyklus der Vorlage; offset relativ zum Zyklus des Protokolldatums. */
  cycle: { config_id: string | null; offset: number } | null;
  /** Nur Matrix: Spalten-Tag-Filter (sonst Spaltentitel) zusätzlich anwenden. */
  use_column_filter: boolean;
  sort: "asc" | "desc";
  limit: number | null;
};

export const RANGE_MODES: readonly EventRangeMode[] = ["future", "past", "all", "window"];
export const DEFAULT_WINDOW_START_DAYS = 0;
export const DEFAULT_WINDOW_END_DAYS = 14;

export function defaultEventFilter(rangeMode: EventRangeMode = "all"): EventFilter {
  return {
    tags: [],
    title: "",
    description: "",
    range: { mode: rangeMode, start_days: DEFAULT_WINDOW_START_DAYS, end_days: DEFAULT_WINDOW_END_DAYS },
    cycle: null,
    use_column_filter: false,
    sort: "asc",
    limit: null,
  };
}

export function splitTags(value: unknown): string[] {
  const raw = Array.isArray(value) ? value : String(value ?? "").split(",");
  const result: string[] = [];
  for (const item of raw) {
    const tag = String(item ?? "").trim();
    if (tag && !result.includes(tag)) result.push(tag);
  }
  return result;
}

function toInt(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
}

/** Bringt einen gespeicherten Filter in die vollständige Form (fehlende Felder = Vorgabe). */
export function normalizeEventFilter(raw: unknown, defaultRangeMode: EventRangeMode = "all"): EventFilter {
  const result = defaultEventFilter(defaultRangeMode);
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return result;
  const source = raw as Record<string, unknown>;
  const range = (source.range && typeof source.range === "object" ? source.range : {}) as Record<string, unknown>;
  const mode = String(range.mode ?? defaultRangeMode) as EventRangeMode;
  const cycle = source.cycle && typeof source.cycle === "object" ? (source.cycle as Record<string, unknown>) : null;
  const limit = toInt(source.limit, 0);
  return {
    tags: splitTags(source.tags),
    title: String(source.title ?? "").trim(),
    description: String(source.description ?? "").trim(),
    range: {
      mode: RANGE_MODES.includes(mode) ? mode : defaultRangeMode,
      start_days: toInt(range.start_days, DEFAULT_WINDOW_START_DAYS),
      end_days: toInt(range.end_days, DEFAULT_WINDOW_END_DAYS),
    },
    cycle: cycle ? { config_id: cycle.config_id ? String(cycle.config_id) : null, offset: toInt(cycle.offset, 0) } : null,
    use_column_filter: source.use_column_filter === true,
    sort: source.sort === "desc" ? "desc" : "asc",
    limit: limit > 0 ? limit : null,
  };
}

/** Spalten-Tag-Filter einer Matrixspalte: eigener Tag-Filter, sonst der Spaltentitel. */
export function columnFilterTags(column: { event_tag_filter?: unknown; title?: unknown } | null | undefined): string[] {
  if (!column) return [];
  const own = splitTags(column.event_tag_filter);
  return own.length ? own : splitTags(column.title);
}

function matchesAnyTag(eventTag: string, tags: string[]) {
  const lowered = eventTag.toLowerCase();
  return tags.some((tag) => lowered.includes(tag.toLowerCase()));
}

export type FilterableEvent = {
  id: string;
  title: string;
  description?: string | null;
  tag?: string | null;
  event_date: string;
  event_end_date?: string | null;
  cycle_assignments?: { cycle_config_id: string; cycle_year: number }[] | null;
};

export type CycleConfigRef = { id: string; reset_month: number; reset_day: number };

export type EventFilterContext = {
  /** ISO-Datum des Protokolls; ohne Datum wird nicht nach Zeitraum/Zyklus gefiltert. */
  protocolDate?: string | null;
  /** Auflösung von cycle.config_id (null = Zyklus der Vorlage). Liefert null, wenn unbekannt. */
  resolveCycle?: (configId: string | null) => CycleConfigRef | null;
  /** Matrixspalte, nur relevant mit use_column_filter. */
  column?: { event_tag_filter?: unknown; title?: unknown } | null;
  /** Der Termin-Pool ist bereits nach Zyklus gefiltert (z. B. vom Backend geladen). */
  cycleAlreadyApplied?: boolean;
};

function addDays(isoDate: string, days: number) {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function matchesRange(event: FilterableEvent, filter: EventFilter, protocolDate: string | null | undefined) {
  const mode = filter.range.mode;
  if (mode === "all" || !protocolDate) return true;
  const start = event.event_date;
  const end = event.event_end_date || start;
  if (mode === "future") return end >= protocolDate;
  if (mode === "past") return end < protocolDate;
  const from = addDays(protocolDate, Math.min(filter.range.start_days, filter.range.end_days));
  const to = addDays(protocolDate, Math.max(filter.range.start_days, filter.range.end_days));
  return end >= from && start <= to;
}

export function eventMatchesFilter(event: FilterableEvent, filter: EventFilter, context: EventFilterContext = {}): boolean {
  const eventTag = String(event.tag ?? "");
  if (filter.tags.length && !matchesAnyTag(eventTag, filter.tags)) return false;
  if (filter.use_column_filter && context.column) {
    const columnTags = columnFilterTags(context.column);
    if (columnTags.length && !matchesAnyTag(eventTag, columnTags)) return false;
  }
  if (filter.title && !String(event.title ?? "").toLowerCase().includes(filter.title.toLowerCase())) return false;
  if (filter.description && !String(event.description ?? "").toLowerCase().includes(filter.description.toLowerCase())) return false;
  if (!matchesRange(event, filter, context.protocolDate)) return false;
  if (filter.cycle && !context.cycleAlreadyApplied && context.protocolDate) {
    const config = context.resolveCycle?.(filter.cycle.config_id) ?? null;
    // Unauflösbarer Zyklus (Vorlage ohne Zyklus): nicht filtern, wie im Backend.
    if (config && !eventMatchesCycleFilter(event.cycle_assignments, config, context.protocolDate, filter.cycle.offset)) return false;
  }
  return true;
}

function compareEvents(left: FilterableEvent, right: FilterableEvent) {
  return left.event_date.localeCompare(right.event_date) || String(left.id).localeCompare(String(right.id));
}

/** Filtert, sortiert und begrenzt Termine. */
export function applyEventFilter<T extends FilterableEvent>(events: readonly T[], filter: EventFilter, context: EventFilterContext = {}): T[] {
  const matching = events.filter((event) => eventMatchesFilter(event, filter, context)).sort(compareEvents);
  if (filter.sort === "desc") matching.reverse();
  return filter.limit ? matching.slice(0, filter.limit) : matching;
}

/** Tags als Text für die Vorbelegung beim Anlegen eines Termins aus einem Block heraus. */
export function eventFilterTagText(filter: EventFilter, column?: { event_tag_filter?: unknown; title?: unknown } | null): string {
  const columnTags = filter.use_column_filter && column ? columnFilterTags(column) : [];
  return (columnTags.length ? columnTags : filter.tags).join(", ");
}

/** Wo ein Block seinen Filter speichert (siehe Kopfkommentar). */
export function blockEventFilter(config: Record<string, unknown> | null | undefined, defaultRangeMode: EventRangeMode = "future"): EventFilter {
  return normalizeEventFilter(config?.event_filter, defaultRangeMode);
}
