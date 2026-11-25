// Reine Hilfen der Backup-Seite (Backup-Redesign 1.6): Zeitplan in Schweizer Zeit, 7-Tage-Raster,
// Nachweis-Fälligkeit und Aufbewahrungs-Schätzung. Ohne React, damit testbar (backup-utils.test.ts).
//
// Zeitplan: gespeichert ist ein Versatz ab Mitternacht UTC (User-Entscheid 2026-11-25: bleibt so).
// Angezeigt wird die Schweizer Uhrzeit des jeweiligen Tages - im Sommer liegen die Läufe darum eine
// Stunde später als im Winter.

import type { BackupJob, BackupJobState, BackupSettings } from "@/types/api";

export const ZONE = "Europe/Zurich";
const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;
// Basis wie im Worker (backup_worker.schedule_slot, backup_admin_service._SCHEDULE_BASE).
const SCHEDULE_BASE_MS = Date.UTC(2000, 0, 1);
/** Ab so vielen Läufen pro Tag zeigt das Raster nur noch eine Tageszusammenfassung (Frage 5 a). */
export const MAX_SLOTS_PER_DAY = 8;

export function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** Kalendertag in Schweizer Zeit als JJJJ-MM-TT. */
export function zurichDay(at: Date | number): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(at);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Stunden seit Mitternacht (Schweizer Zeit) als Bruch, z. B. 13.25 für 13:15. */
export function zurichHourOfDay(at: Date | number): number {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: ZONE, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(at);
  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? 0);
  const minute = Number(parts.find((part) => part.type === "minute")?.value ?? 0);
  return hour + minute / 60;
}

/** Geplante Läufe (UTC-Zeitpunkte), deren Schweizer Kalendertag `day` ist. */
export function scheduleSlotsForDay(day: string, intervalHours: number, offsetMinutes: number): number[] {
  const interval = Math.max(1, intervalHours) * HOUR_MS;
  const base = SCHEDULE_BASE_MS + offsetMinutes * 60_000;
  // Der Schweizer Tag liegt innerhalb von [day 00:00 UTC - 3 h, day 24:00 UTC + 1 h].
  const [year, month, date] = day.split("-").map(Number);
  const from = Date.UTC(year, month - 1, date) - 3 * HOUR_MS;
  const to = from + DAY_MS + 4 * HOUR_MS;
  const slots: number[] = [];
  for (let at = base + Math.ceil((from - base) / interval) * interval; at < to; at += interval) {
    if (zurichDay(at) === day) slots.push(at);
  }
  return slots;
}

export type SlotState = "ok" | "partial" | "failed" | "running" | "missed" | "planned";

export type TimelineSlot = { at: number; state: SlotState; jobId: string | null };
export type TimelineMark = { at: number; kind: "verify" | "restore_test" | "manual"; state: BackupJobState };
export type TimelineDay = {
  day: string;
  slots: TimelineSlot[];
  /** true: zu viele Läufe für Felder - nur die Zusammenfassung zeigen */
  summary: boolean;
  counts: Record<SlotState, number>;
  worst: SlotState | null;
  marks: TimelineMark[];
};

const OPEN_STATES: BackupJobState[] = ["queued", "preparing", "running", "verifying"];
const SEVERITY: SlotState[] = ["failed", "missed", "partial", "running", "ok", "planned"];

export function slotStateOf(state: BackupJobState): SlotState {
  if (state === "completed") return "ok";
  if (state === "partial") return "partial";
  if (OPEN_STATES.includes(state)) return "running";
  return "failed"; // failed, interrupted, cancelled
}

/**
 * 7-Tage-Raster: je Schweizer Tag die geplanten Läufe mit dem Ergebnis des Zeitplan-Backups.
 * Ein vergangener Slot ohne Auftrag ist «verpasst» (Worker lief nicht) - ein Auftrag entsteht im
 * Worker erst zum Slot. Ohne aktiven Zeitplan gibt es keine Slots, nur Markierungen.
 */
export function buildTimeline(jobs: BackupJob[], settings: Pick<BackupSettings, "interval_hours" | "schedule_offset_minutes" | "schedule_enabled">,
  now: number, days = 7): TimelineDay[] {
  const interval = Math.max(1, settings.interval_hours) * HOUR_MS;
  const scheduled = jobs.filter((job) => job.kind === "backup" && job.trigger === "schedule")
    .map((job) => ({ job, at: new Date(job.created_at).getTime() }))
    .sort((a, b) => a.at - b.at);
  const result: TimelineDay[] = [];
  for (let index = days - 1; index >= 0; index -= 1) {
    const day = zurichDay(now - index * DAY_MS);
    const slotTimes = settings.schedule_enabled ? scheduleSlotsForDay(day, settings.interval_hours, settings.schedule_offset_minutes) : [];
    const slots: TimelineSlot[] = slotTimes.map((at) => {
      // Der Auftrag eines Slots entsteht kurz nach dem Slot (Worker-Takt), spätestens vor dem nächsten.
      const match = scheduled.find((entry) => entry.at >= at - 5 * 60_000 && entry.at < at + interval);
      if (match) return { at, state: slotStateOf(match.job.state), jobId: match.job.id };
      return { at, state: at > now ? "planned" : "missed", jobId: null };
    });
    const counts = { ok: 0, partial: 0, failed: 0, running: 0, missed: 0, planned: 0 } as Record<SlotState, number>;
    for (const slot of slots) counts[slot.state] += 1;
    const worst = SEVERITY.find((state) => counts[state] > 0) ?? null;
    const marks: TimelineMark[] = jobs
      .filter((job) => (job.kind === "verify" || job.kind === "restore_test" || (job.kind === "backup" && job.trigger !== "schedule"))
        && zurichDay(new Date(job.created_at)) === day)
      .map((job) => ({ at: new Date(job.created_at).getTime(), kind: job.kind === "backup" ? "manual" as const : job.kind as "verify" | "restore_test", state: job.state }))
      .sort((a, b) => a.at - b.at);
    result.push({ day, slots, summary: slots.length > MAX_SLOTS_PER_DAY, counts, worst, marks });
  }
  return result;
}

export type LevelDue = { pct: number; overdue: boolean; dueAt: number | null };

/** Anteil des Intervalls, der seit dem letzten Nachweis verstrichen ist (Meter auf den Karten). */
export function levelDue(lastAt: string | null | undefined, intervalMs: number, now: number): LevelDue {
  if (!lastAt) return { pct: 100, overdue: true, dueAt: null };
  const last = new Date(lastAt).getTime();
  const elapsed = Math.max(0, now - last);
  return { pct: Math.min(100, Math.round((elapsed / Math.max(1, intervalMs)) * 100)), overdue: elapsed > intervalMs, dueAt: last + intervalMs };
}

/**
 * Grobe Schätzung der Aufbewahrung: Punkte bei vollem Ausbau und Rückblick in Tagen. Regeln
 * überlappen sich (ein Punkt kann täglich UND wöchentlich gehalten werden), darum «ca.».
 */
export function retentionEstimate(settings: Pick<BackupSettings, "interval_hours" | "keep_within_days" | "keep_daily" | "keep_weekly" | "keep_monthly">) {
  const within = Math.round((settings.keep_within_days * 24) / Math.max(1, settings.interval_hours));
  const dailyDays = Math.max(0, settings.keep_daily - settings.keep_within_days);
  const weeklyDays = settings.keep_weekly * 7;
  const monthlyDays = settings.keep_monthly * 30;
  const lookbackDays = Math.max(settings.keep_within_days, settings.keep_daily, weeklyDays, monthlyDays);
  // Tägliche/wöchentliche/monatliche Punkte, die nicht schon von einer kürzeren Regel abgedeckt sind.
  const points = within + dailyDays
    + Math.max(0, settings.keep_weekly - Math.ceil(Math.max(settings.keep_within_days, settings.keep_daily) / 7))
    + Math.max(0, settings.keep_monthly - Math.ceil(Math.max(settings.keep_within_days, settings.keep_daily, weeklyDays) / 30));
  // Segmente für den Balken (Anteil am Rückblick)
  const segments = [
    { key: "within" as const, days: settings.keep_within_days },
    { key: "daily" as const, days: Math.max(0, settings.keep_daily - settings.keep_within_days) },
    { key: "weekly" as const, days: Math.max(0, weeklyDays - Math.max(settings.keep_within_days, settings.keep_daily)) },
    { key: "monthly" as const, days: Math.max(0, monthlyDays - Math.max(settings.keep_within_days, settings.keep_daily, weeklyDays)) },
  ].filter((segment) => segment.days > 0);
  return { points, lookbackDays, segments };
}

/** Läufe eines Tages (für die 24-h-Leiste der Einstellungen) als Stunden in Schweizer Zeit. */
export function runHoursOfDay(day: string, intervalHours: number, offsetMinutes: number): number[] {
  return scheduleSlotsForDay(day, intervalHours, offsetMinutes).map((at) => zurichHourOfDay(at));
}

/** Ersparnis durch Deduplizierung/Kompression: 1 - belegt / Summe aller Punkte. */
export function savingsPercent(originalBytes: number | null | undefined, storedBytes: number | null | undefined): number | null {
  if (!originalBytes || storedBytes === null || storedBytes === undefined || originalBytes <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((1 - storedBytes / originalBytes) * 100)));
}
