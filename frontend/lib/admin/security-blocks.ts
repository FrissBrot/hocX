// Sperren-Seite (/admin/security/blocks, 1.6): reine Hilfen für Countdown, Dauer-Auswahl und
// Gantt-Geometrie - ohne React testbar.

/** Voreinstellungen der Dauer in Minuten (1 h, 6 h, 24 h, 7 Tage, 30 Tage); dazu «Eigene». */
export const BLOCK_DURATION_PRESETS = [60, 360, 1440, 10080, 43200] as const;

export type DurationParts = { days: number; hours: number; minutes: number; seconds: number };

export function durationParts(totalSeconds: number): DurationParts {
  const seconds = Math.max(0, Math.round(totalSeconds));
  return {
    days: Math.floor(seconds / 86_400),
    hours: Math.floor((seconds % 86_400) / 3_600),
    minutes: Math.floor((seconds % 3_600) / 60),
    seconds: seconds % 60,
  };
}

/** Anteil der Restzeit an der gesetzten Dauer in Prozent (0-100). */
export function remainingPercent(until: number, created: number, nowSeconds: number): number {
  const total = until - created;
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, ((until - nowSeconds) / total) * 100));
}

/** Minuten aus Voreinstellung bzw. freiem Feld; null, wenn ungültig (1 bis max). */
export function parseBlockMinutes(preset: string, custom: string, max: number): number | null {
  const raw = preset === "custom" ? custom.trim() : preset;
  if (!/^\d{1,6}$/.test(raw)) return null;
  const value = Number.parseInt(raw, 10);
  return value >= 1 && value <= max ? value : null;
}

export type GanttGeometry = { left: number; width: number };

/** Lage eines Balkens im Fenster [start, end] in Prozent; ausserhalb abgeschnitten, mindestens 0.4 %. */
export function ganttGeometry(barStart: string, barEnd: string, windowStart: string, windowEnd: string): GanttGeometry {
  const from = new Date(windowStart).getTime();
  const to = new Date(windowEnd).getTime();
  const span = Math.max(1, to - from);
  const start = Math.max(from, new Date(barStart).getTime());
  const end = Math.min(to, new Date(barEnd).getTime());
  const left = ((start - from) / span) * 100;
  const width = Math.max(0.4, ((Math.max(start, end) - start) / span) * 100);
  return { left: Math.max(0, Math.min(100, left)), width: Math.min(width, 100 - Math.max(0, Math.min(100, left))) };
}

/** Tagesmarken (lokale Mitternacht) im Fenster als Prozent-Positionen. */
export function ganttDayTicks(windowStart: string, windowEnd: string): { date: Date; left: number }[] {
  const from = new Date(windowStart).getTime();
  const to = new Date(windowEnd).getTime();
  const span = Math.max(1, to - from);
  const first = new Date(from);
  first.setHours(24, 0, 0, 0);
  const ticks: { date: Date; left: number }[] = [];
  for (let at = first.getTime(); at < to; ) {
    const date = new Date(at);
    ticks.push({ date, left: ((at - from) / span) * 100 });
    const next = new Date(at);
    next.setDate(next.getDate() + 1);
    at = next.getTime();
  }
  return ticks;
}
