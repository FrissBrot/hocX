// Reine Hilfsfunktionen für den Reiter «Bussen» der Kasse (Design «Kasse und Bussen v2»):
// gemeinsame Zeilen aus Präsenz- und Pendenzen-Bussen, Filter, Kennzahlen und Gruppierung nach
// Person. Ohne React, damit Filter/Gruppierung direkt getestet werden können.
import { swissYear } from "@/lib/utils/format";
import type { AttendanceFineListItem, TodoFineListItem } from "@/types/api";

/** Seitengrösse der Präsenz-Bussen (Backend erlaubt bis 500). Die Gruppierung nach Person und die
 * Kennzahlen rechnen mit allem Geladenen, daher eine grosse erste Seite statt 50. Hier statt in
 * fines-view.tsx, weil die Server-Seite /fines sie braucht (Werte aus "use client"-Modulen
 * kommen dort nicht an). */
export const FINES_PAGE_SIZE = 500;

export type FineRow =
  | { kind: "attendance"; key: string; fine: AttendanceFineListItem }
  | { kind: "todo"; key: string; fine: TodoFineListItem };

export type FineBucket = "pending" | "collected" | "deleted";
export type FineStatusFilter = FineBucket | "all";
/** Anzeige-Status einer Zeile (Pill). Präsenz-Bussen kennen nur offen/kassiert/gelöscht. */
export type FineRowStatus = "pending" | "running" | "conflict" | "collected" | "deleted";

export function buildRows(fines: AttendanceFineListItem[], todoFines: TodoFineListItem[]): FineRow[] {
  return [
    ...fines.map((fine) => ({ kind: "attendance" as const, key: `a-${fine.id}`, fine })),
    ...todoFines.map((fine, index) => ({
      kind: "todo" as const,
      key: fine.id ? `t-${fine.id}` : `t-${fine.status}-${fine.todo_id}-${fine.participant_id}-${index}`,
      fine,
    })),
  ];
}

export function rowStatus(row: FineRow): FineRowStatus {
  return row.fine.status;
}

/** Laufende und strittige Pendenzen-Bussen zählen wie offene Bussen («Offen»). */
export function bucket(row: FineRow): FineBucket {
  const status = row.fine.status;
  if (status === "collected" || status === "deleted") return status;
  return "pending";
}

/** Nur offene Bussen mit festem Betrag lassen sich kassieren (nicht «läuft», nicht «Konflikt»). */
export function isCollectible(row: FineRow): boolean {
  return row.fine.status === "pending" && (row.kind === "attendance" || row.fine.id !== null);
}

export function rowName(row: FineRow): string {
  return row.kind === "attendance" ? row.fine.participant_name_snapshot : row.fine.participant_name ?? "";
}

/** Gleiche Person für Präsenz- und Pendenzen-Bussen: über die Teilnehmer-ID, sonst den Namen. */
export function personKey(row: FineRow): string {
  return row.fine.participant_id ? `p:${row.fine.participant_id}` : `n:${rowName(row).trim().toLowerCase()}`;
}

export function rowSource(row: FineRow): string {
  return row.kind === "attendance" ? row.fine.protocol_number ?? "" : row.fine.task;
}

export function rowAmount(row: FineRow): number {
  return row.fine.status === "conflict" ? 0 : Number(row.fine.amount) || 0;
}

/** Jahr eines Zeitstempels (z. B. collected_at, UTC) in Schweizer Zeit, wie das Buchungsdatum. */
export function rowYear(value: string | null | undefined): number | null {
  return value ? swissYear(value) : null;
}

export type FineFilter = {
  status: FineStatusFilter;
  search: string;
  /** Nur Pendenzen-Bussen im Konflikt («Anzeigen» im Konflikt-Hinweis). */
  conflictsOnly?: boolean;
  /** Zusätzliche Suchtexte je Zeile (übersetzter Grund, Regel …). */
  searchText?: (row: FineRow) => string[];
};

export function filterRows(rows: FineRow[], { status, search, conflictsOnly = false, searchText }: FineFilter): FineRow[] {
  const q = search.trim().toLowerCase();
  return rows.filter((row) => {
    if (conflictsOnly && row.fine.status !== "conflict") return false;
    if (status !== "all" && bucket(row) !== status) return false;
    if (!q) return true;
    const values = [rowName(row), rowSource(row), ...(row.kind === "todo" ? [row.fine.rule_name ?? ""] : []), ...(searchText?.(row) ?? [])];
    return values.some((value) => value.toLowerCase().includes(q));
  });
}

export function countBuckets(rows: FineRow[]): Record<FineBucket, number> {
  const counts: Record<FineBucket, number> = { pending: 0, collected: 0, deleted: 0 };
  for (const row of rows) counts[bucket(row)] += 1;
  return counts;
}

export type FineKpis = {
  openAmount: number;
  openCount: number;
  collectedAmount: number;
  collectedCount: number;
  peopleOpen: number;
  peopleTotal: number;
};

/** Kennzahlen über alle geladenen Bussen: offen, im Jahr `year` kassiert, Personen mit offenen. */
export function computeKpis(rows: FineRow[], year: number): FineKpis {
  const kpis: FineKpis = { openAmount: 0, openCount: 0, collectedAmount: 0, collectedCount: 0, peopleOpen: 0, peopleTotal: 0 };
  const open = new Set<string>();
  const all = new Set<string>();
  for (const row of rows) {
    const key = personKey(row);
    all.add(key);
    const b = bucket(row);
    if (b === "pending") {
      kpis.openAmount += rowAmount(row);
      kpis.openCount += 1;
      open.add(key);
    } else if (b === "collected" && rowYear(row.fine.collected_at) === year) {
      kpis.collectedAmount += rowAmount(row);
      kpis.collectedCount += 1;
    }
  }
  kpis.peopleOpen = open.size;
  kpis.peopleTotal = all.size;
  return kpis;
}

export type PersonGroup = {
  key: string;
  name: string;
  tariff: string | null;
  rows: FineRow[];
  openAmount: number;
  openCount: number;
  collectible: FineRow[];
};

const STATUS_ORDER: Record<FineRowStatus, number> = { conflict: 0, pending: 1, running: 2, collected: 3, deleted: 4 };

/** Gruppiert gefilterte Zeilen je Person: zuerst wer am meisten offen hat, dann nach Name. */
export function groupByPerson(rows: FineRow[], locale?: string): PersonGroup[] {
  const groups = new Map<string, PersonGroup>();
  for (const row of rows) {
    const key = personKey(row);
    let group = groups.get(key);
    if (!group) {
      group = { key, name: rowName(row) || "—", tariff: null, rows: [], openAmount: 0, openCount: 0, collectible: [] };
      groups.set(key, group);
    }
    group.rows.push(row);
    if (!group.tariff && row.kind === "todo" && row.fine.tariff_name) group.tariff = row.fine.tariff_name;
    if (bucket(row) === "pending") {
      group.openAmount += rowAmount(row);
      group.openCount += 1;
    }
    if (isCollectible(row)) group.collectible.push(row);
  }
  for (const group of groups.values()) {
    group.rows.sort((a, b) => STATUS_ORDER[rowStatus(a)] - STATUS_ORDER[rowStatus(b)] || rowSource(a).localeCompare(rowSource(b), locale));
  }
  return [...groups.values()].sort((a, b) => b.openAmount - a.openAmount || a.name.localeCompare(b.name, locale));
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] ?? "" : "";
  return `${first}${last}`.toUpperCase();
}
